// 2.559.0 UI tests, part C (#4660): dependencies added / removed show at once (optimistic as #1501), jsdom:
// kalmido-suite: fresh
// - "Blocked by…" picker: the dialog closes, the task panel shows the blocker and the task counts as blocked while the
//   server's answer is still held; no GET /api/state for it
// - removing it in the task panel: gone at once; a refusal (500) brings it back with the server's message
// - the timeline's link (tlConnect / tlUnlink, timeline.js): the same at once
// - a person without an organisation (freelancer parity): the same at once
// The held answers wait in the page (window.fetch wrapped) until the test lets them go: every wait is on a real state.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, idle, until: until0} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
const until = fn => until0(fn, {timeout: 15000, step: 100});
// the page's requests: those matching re ("METHOD /url") wait in w.__held until go() (the real request) or fail() (a 500 with
// the text); every GET /api/state is counted (w.__st). The change poll is held meanwhile (holdPoll): a poll of its own that saw
// the new server version would count as a GET /api/state of the action
const hold = (w, re) => {
  w.__held = []; w.__st = w.__st || 0; const f1 = w.__f1 || (w.__f1 = w.fetch);
  w.fetch = (u, o = {}) => {
    const k = `${(o.method || 'GET').toUpperCase()} ${u}`;
    if (/^GET \/api\/state/.test(k)) w.__st++;
    return re.test(k) ? new Promise(res => w.__held.push({u: String(u), go: () => res(f1(u, o)), fail: msg => res(new Response(JSON.stringify({error: msg}), {status: 500, headers: {'content-type': 'application/json'}}))})) : f1(u, o);
  };
};
const unhold = w => { if (w.__f1) w.fetch = w.__f1; };
const holdPoll = w => until(() => w.eval('td_polling ? false : (td_polling = true)'));
const freePoll = w => w.eval('td_polling = false');
const toastHas = (d, re) => until(() => re.test(d.querySelector('#toast')?.textContent || ''));
const setupAlice = async features => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', modules: ['comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features});
  return CA;
};
// a person without an organisation (freelancer parity)
const setupFrida = async (CA, features) => {
  await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features});
  check(((await call(CF, 'GET', '/api/state')).me.workspaces || []).length === 0, 'frida has no organisation');
  return CF;
};
const FEAT = 'comments,deps,progress';
const depsOf = async (ck, id) => ((await call(ck, 'GET', `/api/tasks/${id}/deps`)).blocked_by || []).map(x => x.id);
const panelHas = (d, title) => [...d.querySelectorAll('#d-deps .dep .dt')].some(b => b.textContent === title);

(async () => {
  const CA = await setupAlice(FEAT);
  const L = (await call(CA, 'POST', '/api/lists', {name: 'Website', kind: 'project'})).id;
  const A = (await call(CA, 'POST', '/api/tasks', {title: 'Launch', list_id: L})).id, Bt = (await call(CA, 'POST', '/api/tasks', {title: 'Design', list_id: L})).id;
  const C = (await call(CA, 'POST', '/api/tasks', {title: 'Copy', list_id: L})).id;

  let w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  w.eval(`openDetail(${A})`);
  check(await until(() => d.querySelector('#d-deps .dgrp')), 'the task panel shows its dependencies');
  await holdPoll(w);

  // ================= "Blocked by…": shown at once, the answer held
  hold(w, /^POST \/api\/deps$/);
  w.eval(`depPicker(${A}, 'by')`);
  (await until(() => d.querySelector(`.dpmodal [data-pick="${Bt}"]`))).click();
  check(await until(() => w.__held.length === 1), 'add: the request is on its way (held)');
  const st0 = w.__st;
  check(!d.querySelector('.dpmodal'), 'add: the dialog closed at once');
  check(w.eval(`(S.tasks.get(${A}).blockers || []).includes(${Bt}) && S.tasks.get(${A}).blocked === 1 && S.tasks.get(${Bt}).blocking === 1`), 'add: the tasks carry it before the answer');
  check(await until(() => panelHas(d, 'Design')), 'add: the panel lists the blocker before the answer');
  check(!(await depsOf(CA, A)).length, 'add: the server has none yet');
  w.__held[0].go();
  check(await until(async () => (await depsOf(CA, A)).includes(Bt)), 'add: the server follows');
  await idle(w);
  check(w.__st === st0, 'add: no GET /api/state for it (' + (w.__st - st0) + ')');
  check(panelHas(d, 'Design') && w.eval(`S.tasks.get(${A}).blocked`) === 1, 'add: stays after the answer');

  // ================= removing in the panel: gone at once, a refusal brings it back
  hold(w, /^DELETE \/api\/deps\/\d+\/\d+$/);
  d.querySelector(`#d-deps [data-act="dep-rm"][data-b="${Bt}"]`).click();
  check(await until(() => w.__held.length === 1), 'remove: the request is held');
  check(!panelHas(d, 'Design') && w.eval(`!(S.tasks.get(${A}).blockers || []).includes(${Bt}) && S.tasks.get(${A}).blocked === 0`), 'remove: gone at once');
  w.__held[0].fail('Refused for the test');
  check(await until(() => panelHas(d, 'Design') && w.eval(`(S.tasks.get(${A}).blockers || []).includes(${Bt}) && S.tasks.get(${A}).blocked === 1`)), 'remove: the refusal brings it back');
  check(await toastHas(d, /Refused for the test/), 'remove: with the server\'s message');
  check((await depsOf(CA, A)).includes(Bt), 'remove: the server kept it');
  // and removed for real
  hold(w, /^DELETE \/api\/deps\/\d+\/\d+$/);
  d.querySelector(`#d-deps [data-act="dep-rm"][data-b="${Bt}"]`).click();
  check(await until(() => w.__held.length === 1 && !panelHas(d, 'Design')), 'remove again: gone at once');
  const st1 = w.__st;
  w.__held[0].go();
  check(await until(async () => !(await depsOf(CA, A)).length), 'remove: the server follows');
  await idle(w);
  check(w.__st === st1, 'remove: no GET /api/state for it');

  // ================= the timeline's link (timeline.js, loaded on demand)
  await w.eval(`loadModule('timeline')`);
  hold(w, /^POST \/api\/deps$/);
  w.eval(`tlConnect(${C}, ${A})`);
  check(await until(() => w.__held.length === 1), 'timeline: the link is held');
  check(w.eval(`(S.tasks.get(${A}).blockers || []).includes(${C})`) && await until(() => panelHas(d, 'Copy')), 'timeline: linked at once (task + panel)');
  w.__held[0].go();
  check(await until(async () => (await depsOf(CA, A)).includes(C)), 'timeline: the server follows');
  hold(w, /^DELETE \/api\/deps\/\d+\/\d+$/);
  w.eval(`tlUnlink(${A}, ${C})`);
  check(await until(() => w.__held.length === 1), 'timeline: the unlink is held');
  check(w.eval(`!(S.tasks.get(${A}).blockers || []).includes(${C})`) && !panelHas(d, 'Copy'), 'timeline: unlinked at once');
  w.__held[0].go();
  check(await until(async () => !(await depsOf(CA, A)).length), 'timeline: the server follows the unlink');
  unhold(w); freePoll(w);
  w.close();

  // ================= a person without an organisation: the same at once
  const CF = await setupFrida(CA, FEAT);
  const LF = (await call(CF, 'POST', '/api/lists', {name: 'Jobs', kind: 'project'})).id;
  const FA = (await call(CF, 'POST', '/api/tasks', {title: 'Invoice', list_id: LF})).id, FB = (await call(CF, 'POST', '/api/tasks', {title: 'Logo', list_id: LF})).id;
  w = await boot({user: 'frida', hash: 'l/' + LF}); d = w.document;
  w.eval(`openDetail(${FA})`);
  check(await until(() => d.querySelector('#d-deps .dgrp')), 'freelancer: the panel shows its dependencies');
  await holdPoll(w);
  hold(w, /^POST \/api\/deps$/);
  w.eval(`depPicker(${FA}, 'by')`);
  (await until(() => d.querySelector(`.dpmodal [data-pick="${FB}"]`))).click();
  check(await until(() => w.__held.length === 1), 'freelancer: the request is held');
  check(await until(() => panelHas(d, 'Logo')) && !d.querySelector('.dpmodal'), 'freelancer: shown at once');
  w.__held[0].go(); unhold(w); freePoll(w);
  check(await until(async () => (await depsOf(CF, FA)).includes(FB)), 'freelancer: the server follows');
  w.close();

  console.log(`p2559_c_deps_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
