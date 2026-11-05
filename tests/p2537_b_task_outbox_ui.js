// 2.537.0 B (#4568) UI tests (jsdom), fresh DB: a change of a task goes into the outbox online too
// - a slow server: a new title (typed in the detail) and a priority are on screen and in the page at once, before the server
//   answered; the server has them afterwards and a fresh page shows them
// - a date change that moves a dependent task: the step is there at once, the moved task follows with the server's answer
//   (joins the same undo step); Undo puts both back on the server
// - a locked list: its change never waits in the outbox (only ciphers leave; straight to the server as before)
// - a refusal (409) and a field changed elsewhere meanwhile land in the conflicts dialog, never lost silently
// kalmido-suite: fresh
const {boot, errs, B, login, until} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const jres = (st, j) => new Response(JSON.stringify(j), {status: st, headers: {'content-type': 'application/json'}});
const D = n => { const x = new Date(2027, 2, 1 + n); return `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}`; };
// every request that leaves the window [method, path]; fake(m, p, o, pass) may answer instead (a Response or a Promise of one)
const stub = (w, fake) => { const calls = [], of = w.fetch; w.fetch = (u, o = {}) => { const m = (o.method || 'GET').toUpperCase(), p = new URL(String(u), B).pathname; calls.push([m, p]); const r = fake && fake(m, p, o, () => of(u, o)); return r ? Promise.resolve(r) : of(u, o); }; return calls; };
// a gate: requests matching it wait until open() (the slow server)
const gate = () => { let open; const p = new Promise(r => { open = r; }); return {p, open}; };
const rejected = w => w.eval('S.conflicts').filter(c => c.field === 'rejected');

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const P = (await call('POST', '/api/lists', {name: 'Launch', kind: 'project'})).id;
  const L2 = (await call('POST', '/api/lists', {name: 'Secret plans'})).id;
  const mk = async (title, list_id, extra = {}) => (await call('POST', '/api/tasks', {title, list_id, ...extra})).id;
  const A = await mk('Design the poster', P, {due: D(2)});
  const Bt = await mk('Print the poster', P, {start: D(3), due: D(5)});
  const C = await mk('Hidden plan', L2);
  check((await call('POST', '/api/deps', {task_id: Bt, blocker_id: A})).status < 300, 'setup: Print waits on Design');
  const task = async id => call('GET', '/api/tasks/' + id);

  let w = await boot({user: 'alice', hash: 'l/' + P});
  check(await until(() => w.eval('OUT.me === S.me.id')), 'setup: the server said who is logged in');
  let fake = null;
  const calls = stub(w, (m, p, o, pass) => fake && fake(m, p, o, pass));
  const patches = id => calls.filter(([m, p]) => m === 'PATCH' && p === '/api/tasks/' + id).length;

  // ================= a slow server: the title typed in the detail and a priority are there at once
  let g = gate();
  fake = (m, p, o, pass) => m === 'PATCH' && p === '/api/tasks/' + A ? g.p.then(pass) : null;
  w.eval(`openDetail(${A})`);
  check(await until(() => w.document.querySelector('#d-title')), 'the detail of Design is open');
  w.eval(`queueSave(${A}, 'title', 'Design the big poster'); flushSaves().then(() => { window.__fsd = 1; })`);
  check(await until(() => w.eval('window.__fsd') === 1), 'slow server: the save is done for the page before the server answered');
  check(w.eval(`S.tasks.get(${A}).title`) === 'Design the big poster', 'slow server: the title is in the page at once');
  check(await until(() => [...w.document.querySelectorAll(`#view .trow[data-id="${A}"]`)].some(r => /Design the big poster/.test(r.textContent))), 'slow server: the row shows the new title at once');
  check(await until(() => patches(A) === 1) && w.eval('OUT.q.length') === 1, 'slow server: one change on its way (outbox) ' + w.eval('OUT.q.length'));
  const pr = await w.eval(`patchTask(${A}, {priority: 5}).then(t => t.priority)`);
  check(pr === 5 && w.eval(`S.tasks.get(${A}).priority`) === 5, 'slow server: the priority is in the page at once ' + pr);
  check((await task(A)).title === 'Design the poster', 'slow server: the server does not have it yet');
  g.open();
  check(await until(() => w.eval('OUT.q.length') === 0 && !w.eval('OUT.flushing')), 'the outbox went through');
  let ta = await task(A);
  check(ta.title === 'Design the big poster' && ta.priority === 5, 'the server has title and priority ' + JSON.stringify([ta.title, ta.priority]));
  check(!rejected(w).length && !w.eval('S.conflicts').length, 'no conflict for an own change ' + JSON.stringify(w.eval('S.conflicts')));
  w.close();
  w = await boot({user: 'alice', hash: 'l/' + P});
  check(await until(() => [...w.document.querySelectorAll(`#view .trow[data-id="${A}"]`)].some(r => /Design the big poster/.test(r.textContent))), 'after a reload: the new title from the server');
  fake = null;
  const calls2 = stub(w, (m, p, o, pass) => fake && fake(m, p, o, pass));
  const patches2 = id => calls2.filter(([m, p]) => m === 'PATCH' && p === '/api/tasks/' + id).length;

  // ================= a date with a dependent task: the moved task comes with the answer, one undo step for both
  g = gate();
  fake = (m, p, o, pass) => m === 'PATCH' && p === '/api/tasks/' + A ? g.p.then(pass) : null;
  const n0 = w.eval('HIST.undo.length');
  const due = await w.eval(`patchTask(${A}, {due: '${D(5)}'}).then(t => t.due)`);
  check(due === D(5) && w.eval(`S.tasks.get(${A}).due`) === D(5), 'date: in the page at once ' + due);
  check(w.eval('HIST.undo.length') === n0 + 1 && w.eval('HIST.undo[HIST.undo.length - 1].pairs.length') === 1, 'date: the undo step is there at once (the task itself)');
  check(w.eval(`S.tasks.get(${Bt}).due`) === D(5), 'date: the dependent task waits for the server');
  g.open();
  check(await until(() => w.eval(`S.tasks.get(${Bt})?.due`) === D(8)), 'date: the moved dependent task follows with the answer ' + w.eval(`S.tasks.get(${Bt})?.due`));
  check(await until(() => w.eval('HIST.undo[HIST.undo.length - 1].pairs.length') === 2), 'date: the moved task joined the same undo step');
  check(w.eval('HIST.undo.length') === n0 + 1 && /dependent task/.test(w.eval('HIST.undo[HIST.undo.length - 1].label')), 'date: still one step, named with the moved task ' + w.eval('HIST.undo[HIST.undo.length - 1].label'));
  check(await until(() => /1 dependent task moved/.test(w.document.querySelector('#toast')?.textContent || '')), 'date: the toast says it ' + w.document.querySelector('#toast')?.textContent);
  check((await task(Bt)).due === D(8) && (await task(A)).due === D(5), 'date: the server moved both');
  await w.eval(`histStep('undo')`);
  check(await until(async () => (await task(A)).due === D(2) && (await task(Bt)).due === D(5)), 'Undo: both dates back on the server');
  fake = null;

  // ================= a locked list: no plain text waits in the outbox, straight to the server
  w.eval(`Object.assign(listById(${L2}), {e2e: 'on'})`);  // the flag the page knows a locked list by (this server has no lock set up)
  check(w.eval(`outNow('PATCH', '/api/tasks/${C}', {title: 'x'})`) === false && w.eval(`outNow('PATCH', '/api/tasks/${A}', {title: 'x'})`) === true, 'a locked list never goes the outbox way, an open one does');
  g = gate();
  fake = (m, p, o, pass) => m === 'PATCH' && p === '/api/tasks/' + C ? g.p.then(pass) : null;
  w.eval(`window.__lk = patchTask(${C}, {title: 'Very secret words'}).then(() => 1, () => 2)`);
  check(await until(() => patches2(C) === 1), 'locked list: the change went straight out');
  check(w.eval('OUT.q.length') === 0 && !JSON.stringify(Object.values(w.__store || {})).includes('Very secret words') && !w.eval('JSON.stringify(OUT.q)').includes('Very secret words'),
    'locked list: nothing in the outbox (memory, storage)');
  g.open();
  check(await until(() => w.eval('window.__lk') && w.eval(`S.tasks.get(${C}).title`) === 'Very secret words'), 'locked list: the answer as before');
  fake = null;

  // ================= a refusal (409) and a field changed elsewhere: the conflicts dialog
  fake = (m, p) => m === 'PATCH' && p === '/api/tasks/' + A ? jres(409, {error: 'Changed elsewhere'}) : null;
  const t409 = await w.eval(`patchTask(${A}, {title: 'Refused words'}).then(t => t.title)`);
  check(t409 === 'Refused words', '409: shown at once');
  check(await until(() => w.eval('OUT.q.length') === 0 && rejected(w).some(c => c.tid === A && /Refused words/.test(c.mine) && /Changed elsewhere/.test(c.server))), '409: the change waits in the conflicts dialog with its text ' + JSON.stringify(rejected(w)));
  check(await until(() => w.eval(`S.tasks.get(${A}).title`) === 'Design the big poster'), '409: the page shows the server state again');
  fake = null;
  w.eval("S.conflicts = []; LS.set('conflicts', [])");
  await call('PATCH', '/api/tasks/' + A, {content: 'Written on the phone'});
  await w.eval(`(S.tasks.get(${A}).content = '', patchTask(${A}, {content: 'Written on the laptop'}))`);  // the page has not seen the phone's text yet
  check(await until(() => w.eval('S.conflicts').some(c => c.tid === A && c.field === 'content' && c.server === 'Written on the phone' && c.mine === 'Written on the laptop')), 'changed elsewhere: both versions in the conflicts dialog ' + JSON.stringify(w.eval('S.conflicts')));
  check((await task(A)).content === 'Written on the phone', 'changed elsewhere: the other version is not overwritten');
  w.close();

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  console.log(`p2537_b_task_outbox_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
