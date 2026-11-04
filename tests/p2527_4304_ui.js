// 2.527.0 (#4304) UI tests (jsdom), fresh DB: no typed or changed data gets lost offline or at the end of a session
// - A4: a conflict in the answer of /api/tasks/reorder or /api/tasks/batch (conflicts[{id, ...}], the answer has no id of its
//   own) belongs to that entry's task: the dialog names it, "Use mine" sends PATCH /api/tasks/<that id> (not /undefined)
// kalmido-suite: fresh
const {boot, errs, B, login, until} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
// every request that leaves the window [method, path, body]; w.__offline = the network is gone
const stub = w => { const calls = [], of = w.fetch; w.fetch = (u, o = {}) => { const m = (o.method || 'GET').toUpperCase(), p = new URL(String(u), B).pathname; if (w.__offline) return Promise.reject(new TypeError('Failed to fetch')); calls.push([m, p, o.body]); return of(u, o); }; return calls; };
const online = w => { w.__offline = false; w.eval('OUT.retryAt = 0'); w.dispatchEvent(new w.Event('online')); };

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const P = (await call('POST', '/api/lists', {name: 'Garden'})).id;
  const T1 = (await call('POST', '/api/tasks', {title: 'Cut the hedge', list_id: P})).id;
  const T2 = (await call('POST', '/api/tasks', {title: 'Water the roses', list_id: P})).id;
  const w = await boot({user: 'alice', hash: 'l/' + P});
  check(await until(() => w.eval('S.booted') && w.eval('S.tasks.has(' + T1 + ')')), 'setup: the app is up');
  const calls = stub(w);

  // ================= A4: a conflict of /api/tasks/reorder sent from the queue
  w.__offline = true;
  await w.eval(`api('POST', '/api/tasks/reorder', {items: [{id: ${T1}, sort: 5, priority: 5, _prev: {priority: 0}}]})`);
  check(w.eval('OUT.q.length') === 1, 'A4: the reorder waits in the queue');
  await call('PATCH', '/api/tasks/' + T1, {priority: 3});  // meanwhile on another device
  online(w);
  check(await until(() => w.eval('OUT.q.length') === 0 && !w.eval('OUT.flushing')), 'A4: the queue went through');
  let cf = w.eval('S.conflicts');
  check(cf.length === 1 && cf[0].tid === T1 && cf[0].field === 'priority' && cf[0].title === 'Cut the hedge', 'A4: the conflict names the task of its entry ' + JSON.stringify(cf));
  w.eval('conflictModal()');
  const md = await until(() => [...w.document.querySelectorAll('.modal')].find(x => x.querySelector('#cf-list .cfitem')));
  check(!!md && /Cut the hedge/.test(md.querySelector('#cf-list').textContent), 'A4: the dialog shows the task\'s title');
  calls.length = 0;
  md?.querySelector('[data-cf="mine"]')?.click();
  check(await until(() => calls.some(([m, p]) => m === 'PATCH' && p === '/api/tasks/' + T1)), 'A4: "Use mine" patches the right task ' + JSON.stringify(calls.map(c => c[0] + ' ' + c[1])));
  check(!calls.some(([, p]) => /undefined|null/.test(p)), 'A4: never PATCH /api/tasks/undefined');
  check(await until(async () => (await call('GET', '/api/tasks/' + T1)).priority === 5), 'A4: the server has my priority');
  md?.remove();

  // ================= A4: a batch answer with entries of two tasks (as the service worker hands it over: swres)
  w.eval(`addConflicts(undefined, [{id: ${T1}, title: 'Cut the hedge', field: 'due', server: '2026-11-10', mine: '2026-11-12'}, {id: ${T2}, title: 'Water the roses', field: 'due', server: null, mine: '2026-11-13'}], undefined)`);
  cf = w.eval('S.conflicts');
  check(cf.length === 2 && cf.some(c => c.tid === T1 && c.title === 'Cut the hedge') && cf.some(c => c.tid === T2 && c.title === 'Water the roses'), 'A4: two tasks of one batch, each its own entry ' + JSON.stringify(cf));
  // a PATCH of one task (no id per entry) keeps the id it was given
  w.eval(`addConflicts(${T2}, [{field: 'title', server: 'Water the roses', mine: 'Water all roses'}], 'Water the roses')`);
  check(w.eval('S.conflicts').some(c => c.tid === T2 && c.field === 'title'), 'A4: a single PATCH conflict keeps its task id');
  w.eval("S.conflicts = []; LS.set('conflicts', [])");

  w.close();
  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  console.log(`p2527_4304_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
