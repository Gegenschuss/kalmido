// 2.46.1 part B (jsdom): Settings > Modules.
//  - #1601: quick clicks between the purposes (one switch at a time) leave ONE dialog whose counts ("3 of 7 on") match
//    the switches, and each row's dimming matches its switch
//  - #1591: the switch "Switch on all modules" under the purposes: off = only lists and tasks, on = every module, ONE
//    undo step; the counts follow
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
// every group: the number in its head = the switches that are on; a row is dimmed exactly when its switch is off
function consistent(d) {
  const bad = [];
  for (const g of d.querySelectorAll('.smodal [data-modgrp]')) {
    const ins = [...g.querySelectorAll(':scope > .modlist > .modrow > label.mmain input')];
    const m = (g.querySelector('.mgc')?.textContent || '').match(/(\d+)\D+(\d+)/);
    if (!m || +m[1] !== ins.filter(x => x.checked).length || +m[2] !== ins.length) bad.push(`${g.querySelector('.mgn')?.textContent}: ${g.querySelector('.mgc')?.textContent} vs ${ins.filter(x => x.checked).length}/${ins.length}`);
    for (const x of ins) if (x.closest('.modrow').classList.contains('off') === x.checked) bad.push('row ' + (x.dataset.feat || x.dataset.mgarea));
  }
  return bad;
}

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const w = await boot({user: 'alice'}), d = w.document;
  await sleep(400);
  w.eval(`settingsModal('modules')`); await sleep(400);
  check(d.querySelector('.smodal #s-modsall') && d.querySelector('.smodal #s-modsall').checked, '#1591: the switch under the purposes, on by default');
  check(consistent(d).length === 0, '#1601: counts match at the start ' + consistent(d));
  // ================= #1601: quick clicks between the purposes
  let asked = 0; w.confirm = () => { asked++; return true; };
  for (const p of ['team', 'family', 'me', 'office']) click(w, d.querySelector(`.smodal [data-purpose="${p}"]`));
  await until(() => d.querySelector('.smodal [data-purpose="team"].on'), 60); await sleep(800);
  check(asked === 1 && w.eval('S.settings.purpose') === 'team', `#1601: one purpose switch at a time (asked ${asked}, ${w.eval('S.settings.purpose')})`);
  check(d.querySelectorAll('.smodal').length === 1, '#1601: one dialog');
  check(consistent(d).length === 0, '#1601: counts and switches agree after the quick clicks ' + consistent(d));
  for (const p of ['family', 'me', 'software']) {
    click(w, d.querySelector(`.smodal [data-purpose="${p}"]`));
    await until(() => d.querySelector(`.smodal [data-purpose="${p}"].on`), 60); await sleep(300);
  }
  const srv = (await call('GET', '/api/state')).settings.features;
  check(w.eval('S.settings.features') === srv, '#1601: the app has the server state ' + srv);
  check(d.querySelectorAll('.smodal').length === 1 && consistent(d).length === 0, '#1601: one after the other: still in step ' + consistent(d));
  // ================= #1591: the switch off / on
  const sw = d.querySelector('.smodal #s-modsall'); sw.checked = false; sw.dispatchEvent(new w.Event('change', {bubbles: true}));
  await until(async () => (await call('GET', '/api/state')).settings.mods_all === '0', 40);
  const st = (await call('GET', '/api/state')).settings;
  check(!['cal', 'kanban', 'events', 'contacts', 'timeline'].some(k => st.features.split(',').includes(k)), '#1591: off = lists and tasks only ' + st.features);
  await sleep(300);
  check(consistent(d).length === 0 && !d.querySelector('.smodal [data-feat="cal"]')?.checked, '#1591: the switches follow ' + consistent(d));
  await w.eval('histStep("undo")'); await until(async () => (await call('GET', '/api/state')).settings.mods_all === '1', 40);
  check((await call('GET', '/api/state')).settings.features.split(',').includes('kanban'), '#1591: one undo step brings the modules back');
  w.close();
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
