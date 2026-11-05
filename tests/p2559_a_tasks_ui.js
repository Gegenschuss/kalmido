// 2.559.0 UI tests, part A (#4659): frequent actions on tasks show at once (optimistic like #1501), jsdom, invented data:
// kalmido-suite: fresh
// - table cells (sheetgrid.js sgWrite): the new title / date stand in the row while the batch answer is still held; a refusal
//   (409) puts the old values back with the server's message; no GET /api/state follows the action
// - several tasks dragged into a section (dragmulti.js dgApply): in the section at once; a refusal (500) puts them back
// - the multi-select action (sidebar.js batch): a date for two tasks at once, a delete gone at once, a refused delete back
// - "Delete completed" (trashui.js doneCleanup): the completed rows are gone at once, the server follows
// - a person without an organisation (freelancer parity): a table cell shows at once, too
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
// requests matching re ("METHOD /url") wait in w.__held until the test calls go() (the real request) or fail(text, status);
// every request of the page lands in w.__log (to see that no GET /api/state follows an action)
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
    return re.test(k) ? new Promise(res => w.__held.push({u: String(u), go: () => res(f1(u, o).then(x => { x.clone().text().then(t => w.__resp.push(t)); return x; })), fail: (msg, st = 409) => res(new Response(JSON.stringify({error: msg}), {status: st, headers: {'content-type': 'application/json'}}))})) : f1(u, o); };
  await idle(w);
};
const unhold = w => { if (w.__f1) w.fetch = w.__f1; for (const v of w.__vers || []) v(); w.__vers = []; };
const noState = w => !w.__log.some(k => /^GET \/api\/state\b/.test(k) && !/[?&]auto=1/.test(k));  // auto=1 = the live update's poll, no consequence of the action
const BATCH = /^POST \/api\/tasks\/batch$/;

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', modules: []});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const L = (await call(CA, 'POST', '/api/lists', {name: 'Garden'})).id;
  await call(CA, 'PATCH', `/api/lists/${L}`, {columns: ['due']});
  const SEC = (await call(CA, 'POST', '/api/sections', {list_id: L, name: 'Later'})).id;
  const T1 = (await call(CA, 'POST', '/api/tasks', {title: 'Cut the hedge', list_id: L})).id;
  const T2 = (await call(CA, 'POST', '/api/tasks', {title: 'Buy seeds', list_id: L})).id;
  const T3 = (await call(CA, 'POST', '/api/tasks', {title: 'Water the roses', list_id: L})).id;
  const T4 = (await call(CA, 'POST', '/api/tasks', {title: 'Old fence', list_id: L})).id;
  const get = async id => call(CA, 'GET', `/api/tasks/${id}`);

  let w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  const row = id => d.querySelector(`#view .trow[data-id="${id}"]`);
  const ttl = id => (row(id)?.querySelector('.tmain .ttl')?.textContent || '').trim();
  const due = id => (d.querySelector(`#tc-${id} .lc[data-k="due"]`)?.textContent || '').trim();
  const secOf = id => row(id)?.closest('.group')?.querySelector('.ghead')?.dataset.section;
  check(await until(() => row(T1) && d.querySelector(`#tc-${T2} .lc[data-k="due"]`)), 'the list shows its rows with the date column');
  const due0 = due(T2);  // the empty cell's own text (a placeholder)

  // ================= table cells: shown before the answer
  await hold(w, BATCH);
  w.eval(`window.__p = sgWrite([{tid: ${T1}, k: 'title', v: 'Cut the hedge short'}, {tid: ${T2}, k: 'due', v: '2026-12-01'}], 'test')`);
  check(await until(() => w.__held.length === 1), 'cells: the batch is on its way (held)');
  check(await until(() => ttl(T1) === 'Cut the hedge short' && due(T2) !== due0), 'cells: the new title and the date stand in the rows before the answer: ' + ttl(T1) + ' / ' + due(T2));
  check((await get(T1)).title === 'Cut the hedge', 'cells: the server has the old title still');
  w.__held[0].go();
  check(await w.eval('window.__p') === 2, 'cells: sgWrite reports two tasks');
  check((await get(T1)).title === 'Cut the hedge short' && (await get(T2)).due === '2026-12-01', 'cells: the server follows');
  check(noState(w), 'cells: no GET /api/state after the change: ' + w.__log.filter(k => /state/.test(k)).join(' | '));
  check(w.eval('HIST.undo.length') >= 1, 'cells: one undo step');

  // ================= table cells: a refusal puts the old values back
  await hold(w, BATCH);
  w.eval(`window.__p = sgWrite([{tid: ${T1}, k: 'title', v: 'Refused title'}], 'test')`);
  check(await until(() => w.__held.length === 1 && ttl(T1) === 'Refused title'), 'refused cell: shown at once');
  w.__held[0].fail('Refused for the test', 409);
  check(await until(() => ttl(T1) === 'Cut the hedge short'), 'refused cell: the old title is back: ' + ttl(T1));
  check(await until(() => /Refused for the test/.test(d.querySelector('#toast')?.textContent || '')), 'refused cell: with the server\'s message');
  check(await w.eval('window.__p') === 0 && noState(w), 'refused cell: nothing saved, no reload');
  unhold(w);

  // ================= several tasks into a section: at once
  await hold(w, BATCH);
  check(secOf(T2) !== String(SEC) && secOf(T3) !== String(SEC), 'drag: T2 and T3 are not in the section yet');
  w.eval(`window.__p = dgToSection([${T2}, ${T3}], ${L}, ${SEC})`);
  check(await until(() => w.__held.length === 1), 'drag: the batch is held');
  check(await until(() => secOf(T2) === String(SEC) && secOf(T3) === String(SEC)), 'drag: both rows stand in the section before the answer');
  check((await get(T2)).section_id !== SEC, 'drag: the server has the old section still');
  w.__held[0].go(); await w.eval('window.__p');
  check((await get(T2)).section_id === SEC && (await get(T3)).section_id === SEC, 'drag: the server follows');
  check(noState(w), 'drag: no GET /api/state after the move: ' + w.__log.join(' | ') + ' ' + w.__resp.join(' '));

  // ================= several tasks: a refusal puts them back (no reload)
  await hold(w, BATCH);
  w.eval(`window.__p = dgToSection([${T2}], ${L}, null)`);
  check(await until(() => w.__held.length === 1 && secOf(T2) !== String(SEC)), 'drag back: T2 left the section at once');
  w.__held[0].fail('Server trouble', 500);
  check(await until(() => secOf(T2) === String(SEC)), 'drag refused (500): T2 is back in the section');
  check(noState(w), 'drag refused: no GET /api/state (put back, not reloaded)');
  unhold(w);

  // ================= the multi-select action: a date for two tasks, a delete
  await hold(w, BATCH);
  w.eval(`window.__p = batch('patch', {due: '2026-12-24'}, false, [${T3}, ${T4}])`);
  check(await until(() => w.__held.length === 1 && due(T3) !== due0 && due(T4) !== due0), 'multi: both dates stand before the answer');
  w.__held[0].go(); await w.eval('window.__p');
  check((await get(T3)).due === '2026-12-24' && (await get(T4)).due === '2026-12-24', 'multi: the server follows');
  check(noState(w), 'multi: no GET /api/state after the change: ' + w.__log.join(' | ') + ' ' + w.__resp.join(' '));
  await hold(w, BATCH);
  w.eval(`window.__p = batch('delete', {}, true, [${T4}])`);
  check(await until(() => w.__held.length === 1 && !row(T4)), 'multi delete: the row is gone before the answer');
  w.__held[0].fail('Not now', 409);
  check(await until(() => row(T4)), 'multi delete refused: the row is back');
  await hold(w, BATCH);
  w.eval(`window.__p = batch('delete', {}, true, [${T4}])`);
  check(await until(() => w.__held.length === 1 && !row(T4)), 'multi delete again: gone at once');
  w.__held[0].go(); await w.eval('window.__p');
  check((await get(T4)).deleted_at || (await get(T4)).http === 404, 'multi delete: in the trash on the server');
  check(noState(w), 'multi delete: no GET /api/state: ' + w.__log.join(' | '));
  unhold(w);
  w.close();

  // ================= "Delete completed": gone at once
  const D1 = (await call(CA, 'POST', '/api/tasks', {title: 'Done chore', list_id: L})).id;
  await call(CA, 'POST', `/api/tasks/${D1}/complete`, {});
  w = await boot({user: 'alice', hash: 'l/' + L}); d = w.document;
  await until(() => row(T1));
  const had = w.eval(`!!taskById(${D1})`);  // the completed task in the page's state (the clean-up fetches its own list too)
  await hold(w, BATCH);
  w.confirm = () => true;  // boot.js dialogBridge answers the question with it
  w.eval(`window.__p = doneCleanup()`);
  check(await until(() => w.__held.length === 1), 'clean-up: the delete is held');
  check(!w.eval(`!!taskById(${D1})`) && !row(D1), `clean-up: the completed task is gone here before the answer (was in the state: ${had})`);
  w.__held[0].go(); await w.eval('window.__p');
  check(await until(async () => { const t = await get(D1); return t.deleted_at || t.http === 404; }), 'clean-up: the server moved it to the trash');
  unhold(w);
  w.close();

  // ================= a person without an organisation: a table cell at once
  await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  check(((await call(CF, 'GET', '/api/state')).me.workspaces || []).length === 0, 'frida has no organisation');
  const LF = (await call(CF, 'POST', '/api/lists', {name: 'Jobs'})).id;
  await call(CF, 'PATCH', `/api/lists/${LF}`, {columns: ['due']});
  const TF = (await call(CF, 'POST', '/api/tasks', {title: 'Logo draft', list_id: LF})).id;
  w = await boot({user: 'frida', hash: 'l/' + LF}); d = w.document;
  check(await until(() => row(TF)), 'freelancer: the list shows');
  const dueF0 = due(TF);
  await hold(w, BATCH);
  w.eval(`window.__p = sgWrite([{tid: ${TF}, k: 'due', v: '2026-11-30'}], 'test')`);
  check(await until(() => w.__held.length === 1 && due(TF) !== dueF0), 'freelancer: the date stands before the answer');
  w.__held[0].go(); await w.eval('window.__p');
  check((await call(CF, 'GET', `/api/tasks/${TF}`)).due === '2026-11-30' && noState(w), 'freelancer: the server follows, no reload');
  unhold(w);
  w.close();

  console.log(`p2559_a_tasks_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
