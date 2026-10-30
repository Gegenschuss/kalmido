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
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
// every group: the number in its head = the single modules that are on; a row is dimmed exactly when its switch is off
// 2.171.0 (#2676): an area counts by its parts (was one per area); its switch is on only with every part on, its row is
// dimmed only with no part on
function consistent(d) {
  const bad = [];
  for (const g of d.querySelectorAll('.smodal [data-modgrp]')) {
    const ins = [...g.querySelectorAll('input[data-feat]:not(:disabled)')], ks = [...new Set(ins.map(x => x.dataset.feat))];
    const on = ks.filter(k => ins.find(x => x.dataset.feat === k).checked).length;
    const m = (g.querySelector('.mgc')?.textContent || '').match(/(\d+)\D+(\d+)/);
    if (!m || +m[1] !== on || +m[2] !== ks.length) bad.push(`${g.querySelector('.mgn')?.textContent}: ${g.querySelector('.mgc')?.textContent} vs ${on}/${ks.length}`);
    for (const x of g.querySelectorAll(':scope > .modlist > .modrow > label.mmain input[data-feat]')) if (x.closest('.modrow').classList.contains('off') === x.checked) bad.push('row ' + x.dataset.feat);
    for (const x of g.querySelectorAll('input[data-mgarea]')) {
      const r = x.closest('.modrow'), ps = [...r.querySelectorAll('input[data-feat]:not(:disabled)')];
      if (x.checked !== ps.every(p => p.checked)) bad.push('area ' + x.dataset.mgarea);
      if (r.classList.contains('off') === ps.some(p => p.checked)) bad.push('area row ' + x.dataset.mgarea);
    }
  }
  return bad;
}
const change = (w, el) => el.dispatchEvent(new w.Event('change', {bubbles: true}));

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const w = await boot({user: 'alice'}), d = w.document;
  await sleep(400);
  w.eval(`settingsModal('modules')`); await sleep(400);
  // 2.171.0 (#2676): the switch shows the real state - the setup switched on only some modules, so it is off (was: on by default)
  check(d.querySelector('.smodal #s-modsall') && !d.querySelector('.smodal #s-modsall').checked, '#1591/#2676: the switch under the purposes, off while modules are off');
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
  // 2.56.1 (#1808): switch on again = every module, the counter says N of N, the hint stands under the title
  const sw2 = d.querySelector('.smodal #s-modsall'); sw2.checked = true; sw2.dispatchEvent(new w.Event('change', {bubbles: true}));
  await until(async () => (await call('GET', '/api/state')).settings.mods_all === '1', 40); await sleep(500);
  const feats = (await call('GET', '/api/state')).settings.features.split(',');
  const allKeys = w.eval('FEATS.map(x => x[0])');
  check(allKeys.every(k => feats.includes(k)), '#1808: every module is on ' + allKeys.filter(k => !feats.includes(k)));
  const tot = d.querySelector('#s-modtot').textContent.match(/(\d+) of (\d+)/);
  check(tot && tot[1] === tot[2], '#1808: counter N of N ' + (tot && tot[0]));
  check(d.querySelector('.smodal #s-modsall').checked && consistent(d).length === 0, '#2676: all on: the switch on, counts agree ' + consistent(d));
  // ================= 2.171.0 (#2676): two parts of Home off -> the counter below the total, the switch off, Home "partly"
  for (const k of ['feeds', 'budget']) { const x = d.querySelector(`.smodal input[data-feat="${k}"]`); x.checked = false; change(w, x);
    await until(async () => !(await call('GET', '/api/state')).settings.features.split(',').includes(k)); await sleep(800); }  // one after the other, like a person
  await until(async () => { const f = (await call('GET', '/api/state')).settings.features.split(','); return !f.includes('feeds') && !f.includes('budget'); }); await sleep(400);
  const t2 = d.querySelector('#s-modtot').textContent.match(/(\d+) of (\d+)/), life = d.querySelector('.smodal input[data-mgarea="life"]');
  check(t2 && +t2[1] === +t2[2] - 2, '#2676: Feeds + Budget off = two less than all ' + (t2 && t2[0]));
  check(!d.querySelector('.smodal #s-modsall').checked, '#2676: the switch is off while two modules are off');
  check(life && !life.checked && life.indeterminate && !life.closest('.modrow').classList.contains('off') && life.closest('.modrow').classList.contains('part'), '#2676: Home shows "partly on"');
  check(consistent(d).length === 0, '#2676: the group counts agree ' + consistent(d));
  const sw3 = d.querySelector('.smodal #s-modsall'); sw3.checked = true; change(w, sw3);
  await until(async () => { const f = (await call('GET', '/api/state')).settings.features.split(','); return f.includes('feeds') && f.includes('budget'); }); await sleep(500);
  const t3 = d.querySelector('#s-modtot').textContent.match(/(\d+) of (\d+)/);
  check(t3 && t3[1] === t3[2] && d.querySelector('.smodal #s-modsall').checked && d.querySelector('.smodal input[data-mgarea="life"]').checked, '#2676: switched on = every module again, Home on ' + (t3 && t3[0]));
  // 2.171.0 (#2676): the same in a fresh dialog (the half state is set on opening, no HTML attribute)
  // 2.172.0 (#2679): Feeds moved to the area Reading, so Budget stands for a part of Home here
  { const x = d.querySelector('.smodal input[data-feat="budget"]'); x.checked = false; change(w, x); await until(() => !w.eval(`feat('budget')`)); await sleep(300);
    d.querySelector('.smodal').remove(); w.eval(`settingsModal('modules')`); await until(() => d.querySelector('.smodal [data-mgarea="life"]'));
    const l2 = d.querySelector('.smodal input[data-mgarea="life"]');
    check(!l2.checked && l2.indeterminate && !d.querySelector('.smodal #s-modsall').checked && consistent(d).length === 0, '#2676: reopened: Home partly, the switch off ' + consistent(d)); }
  const pb = d.querySelector('.smodal .pmsw b'), ps = d.querySelector('.smodal .pmsw small');
  check(pb && ps && ps.getBoundingClientRect().top >= pb.getBoundingClientRect().bottom - 1, '#1808: hint below the title');
  w.close();
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
