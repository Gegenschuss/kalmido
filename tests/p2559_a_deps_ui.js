// 2.559.0 UI tests, part A (#4660): dependencies made by dragging / the task picker show at once (optimistic like #1501),
// kalmido-suite: fresh
// jsdom, invented data:
// - dgDepAdd (dragmulti.js): the waiting task is marked "blocked" while the request is still held, the server follows; no
//   GET /api/state follows the action
// - two pairs at once: both waiting tasks are blocked at once
// - a refusal (409) takes the mark back with the server's message
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
// requests matching re ("METHOD /url") wait in w.__held until go() / fail(text, status); every request lands in w.__log
// the live update's poll (GET /api/version every 4 s) waits while a test holds requests, so a GET /api/state it would start
// (its retry after a crossing write has no auto=1) is never mistaken for a consequence of the action; what is still on its
// way (a timeline the poll asked for) arrives before the action
const hold = async (w, re) => {
  if (w.__f1) w.fetch = w.__f1;  // the parked polls of a hold before go on first
  for (const v of w.__vers || []) v();
  await until(() => !w.eval('td_polling'));
  w.__held = []; w.__log = []; w.__resp = []; w.__vers = []; const f1 = w.__f1 || (w.__f1 = w.fetch);
  w.fetch = (u, o = {}) => { const k = `${o.method || 'GET'} ${u}`; w.__log.push(k);
    if (/^GET \/api\/version\b/.test(k)) return new Promise(res => w.__vers.push(() => res(f1(u, o))));
    return re.test(k) ? new Promise(res => w.__held.push({u: String(u), go: () => res(f1(u, o)), fail: (msg, st = 409) => res(new Response(JSON.stringify({error: msg}), {status: st, headers: {'content-type': 'application/json'}}))})) : f1(u, o); };
  await idle(w);
};
const unhold = w => { if (w.__f1) w.fetch = w.__f1; for (const v of w.__vers || []) v(); w.__vers = []; };
const noState = w => !w.__log.some(k => /^GET \/api\/state\b/.test(k) && !/[?&]auto=1/.test(k));  // auto=1 = the live update's poll, no consequence of the action
const DEPS = /^POST \/api\/deps$/;
const FEAT = 'deps';

async function person(ck, name) {
  const P = (await call(ck, 'POST', '/api/lists', {name, kind: 'project'})).id;
  const ids = [];
  for (const t of ['Draft', 'Review', 'Print', 'Ship']) ids.push((await call(ck, 'POST', '/api/tasks', {title: t, list_id: P})).id);
  return {P, ids};
}
const blockers = async (ck, id) => (await call(ck, 'GET', `/api/tasks/${id}`)).blockers || [];

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', modules: ['deps']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const {P, ids: [A, Bk, C, D]} = await person(CA, 'Flyer');

  let w = await boot({user: 'alice', hash: 'l/' + P}), d = w.document;
  const row = id => d.querySelector(`#view .trow[data-id="${id}"]`);
  const blk = id => !!row(id)?.querySelector('.blk');
  check(await until(() => row(A) && row(Bk)) && !blk(Bk), 'the project shows its tasks, none blocked');

  // ================= one pair at once
  await hold(w, DEPS);
  w.eval(`window.__p = dgDepAdd([[${Bk}, ${A}]])`);
  check(await until(() => w.__held.length === 1), 'one pair: the request is held');
  check(await until(() => blk(Bk)) && w.eval(`S.tasks.get(${Bk}).blockers.includes(${A})`), '"Review" is marked blocked before the answer');
  check(!(await blockers(CA, Bk)).length, 'the server has no dependency yet');
  w.__held[0].go(); await w.eval('window.__p');
  check((await blockers(CA, Bk)).includes(A), 'the server follows');
  check(noState(w), 'no GET /api/state after the dependency: ' + w.__log.filter(k => /state/.test(k)).join(' | '));

  // ================= two pairs at once
  await hold(w, DEPS);
  w.eval(`window.__p = dgDepAdd([[${C}, ${Bk}], [${D}, ${Bk}]])`);
  check(await until(() => w.__held.length === 1 && blk(C) && blk(D)), 'two pairs: both waiting tasks are blocked before the first answer');
  w.__held[0].go();
  check(await until(() => w.__held.length === 2), 'the second request follows the first');
  w.__held[1].go(); await w.eval('window.__p');
  check((await blockers(CA, C)).includes(Bk) && (await blockers(CA, D)).includes(Bk), 'two pairs: the server has both');
  check(noState(w), 'two pairs: no GET /api/state');

  // ================= a refusal takes it back
  await hold(w, DEPS);
  w.eval(`window.__p = dgDepAdd([[${A}, ${D}]])`);
  check(await until(() => w.__held.length === 1 && blk(A)), 'refused: "Draft" blocked at once');
  w.__held[0].fail('Refused for the test', 409);
  check(await until(() => !blk(A) && !w.eval(`S.tasks.get(${A}).blockers.includes(${D})`)), 'refused: the mark goes again');
  check(await until(() => /Refused for the test/.test(d.querySelector('#toast')?.textContent || '')), 'refused: with the server\'s message');
  await w.eval('window.__p');
  check(noState(w), 'refused: no GET /api/state');
  unhold(w);
  w.close();

  // ================= a person without an organisation
  await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(((await call(CF, 'GET', '/api/state')).me.workspaces || []).length === 0, 'frida has no organisation');
  const {P: PF, ids: [FA, FB]} = await person(CF, 'Jobs');
  w = await boot({user: 'frida', hash: 'l/' + PF}); d = w.document;
  check(await until(() => row(FA) && row(FB)), 'freelancer: the project shows');
  await hold(w, DEPS);
  w.eval(`window.__p = dgDepAdd([[${FB}, ${FA}]])`);
  check(await until(() => w.__held.length === 1 && blk(FB)), 'freelancer: blocked before the answer');
  w.__held[0].go(); await w.eval('window.__p');
  check((await blockers(CF, FB)).includes(FA) && noState(w), 'freelancer: the server follows, no reload');
  unhold(w);
  w.close();

  console.log(`p2559_a_deps_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
