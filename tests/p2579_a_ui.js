// 2.579.0 A UI tests (jsdom), fresh DB:
// - #4798 a task dragged onto a subtask of another list: the drop's step is offered with Undo ("Moved to …"), the reorder
//   request's _prev carries the values before the drop (the old list), Undo puts parent and list back on the server; in the same
//   list (the parent change goes through the outbox and changes the task in the page at once, #4568) the drop's step still
//   remembers the parent before the drop, Undo puts parent and section back
// - #4199 drawing: listById looks a list up through a map (no scan per task), counts() / openTasks() are worked out once per data
//   state (a render draws them from the cache), the command field builds its set once per opening and searches only after a short
//   pause in typing; the board / timeline group in one pass. Counted with counters, not with a stop watch
// kalmido-suite: fresh
const {boot, errs, B, login, until, undoToast, idle} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
// every request that leaves the window: [method, path, body]
const stub = w => { const calls = [], of = w.fetch; w.fetch = (u, o = {}) => { calls.push([(o.method || 'GET').toUpperCase(), new URL(String(u), B).pathname, o.body ? (() => { try { return JSON.parse(o.body); } catch { return null; } })() : null]); return of(u, o); }; return calls; };

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const L1 = (await call('POST', '/api/lists', {name: 'Home jobs'})).id;
  const L2 = (await call('POST', '/api/lists', {name: 'Garden'})).id;
  const mk = async (title, list_id, extra = {}) => (await call('POST', '/api/tasks', {title, list_id, ...extra})).id;
  const X = await mk('Fix the fence', L1);
  const Q = await mk('Plant the beds', L2);
  const S = await mk('Buy seeds', L2, {parent_id: Q});
  const task = async id => call('GET', '/api/tasks/' + id);
  check((await task(S)).parent_id === Q, 'setup: Buy seeds is a subtask of Plant the beds');

  // ================= #4798 onto a subtask of another list: Undo and _prev see the values before the drop
  let w = await boot({user: 'alice', hash: 'all'}); let d = w.document;
  check(await until(() => w.eval('OUT.me === S.me.id')), 'setup: the server said who is logged in');
  const calls = stub(w);
  const rowS = await until(() => d.querySelector(`#view .trow[data-id="${S}"]`));
  check(rowS && d.querySelector(`#view .trow[data-id="${X}"]`), '#4798: "All" shows the task and the subtask of the other list');
  w.eval(`dropTask(${X}, document.querySelector('#view .trow[data-id="${S}"]'), 0)`);
  const moved = await until(async () => { const t = await task(X); return t.parent_id === Q && t.list_id === L2 && t; });
  check(moved, '#4798: the drop made it a subtask in the other list on the server');
  const ro = await until(() => calls.find(c => c[0] === 'POST' && c[1] === '/api/tasks/reorder' && c[2]?.items?.[0]?.id === X));
  const prev = ro?.[2]?.items?.[0]?._prev || {};
  check(prev.list_id === L1, '#4798: the reorder request\'s _prev has the list before the drop ' + JSON.stringify(prev));
  check(await undoToast(w, /Moved to Garden/), '#4798: the drop offers Undo ("Moved to Garden")');
  const back = await until(async () => { const t = await task(X); return !t.parent_id && t.list_id === L1 && t; });
  check(back, '#4798: Undo puts parent and list back on the server ' + JSON.stringify(await task(X).then(t => [t.parent_id, t.list_id])));
  await idle(w);
  check(!w.eval('S.conflicts').length, '#4798: no conflict for the own drop and its undo ' + JSON.stringify(w.eval('S.conflicts')));
  w.close();

  // ================= #4798 the same list: the parent change is in the page at once (outbox); the step keeps the state before the drop
  const SEC = (await call('POST', '/api/sections', {list_id: L2, name: 'Beds'})).id;
  const Y = await mk('Rake the leaves', L2);
  const Q2 = await mk('Water the plants', L2, {section_id: SEC});
  const S2 = await mk('Fill the can', L2, {parent_id: Q2});
  w = await boot({user: 'alice', hash: 'l/' + L2}); d = w.document;
  check(await until(() => w.eval('OUT.me === S.me.id')), 'setup: the server said who is logged in (2)');
  check(await until(() => d.querySelector(`#view .trow[data-id="${S2}"]`) && d.querySelector(`#view .trow[data-id="${Y}"]`)), '#4798: the list shows the task and the subtask under the section');
  const n0 = w.eval('HIST.undo.length');
  w.eval(`dropTask(${Y}, document.querySelector('#view .trow[data-id="${S2}"]'), 0)`);
  const m2 = await until(async () => { const t = await task(Y); return t.parent_id === Q2 && t.section_id === SEC && t; });
  check(m2, '#4798: same list: a subtask of Water the plants in the section on the server ' + JSON.stringify(await task(Y).then(t => [t.parent_id, t.section_id])));
  check(await until(() => !w.eval('HIST.busy') && w.eval('HIST.undo.length') === n0 + 1), '#4798: same list: one step for the drop');
  // the drop's own part (section, sort) remembers the task as it was before the drop - before the fix it had the new parent already
  const snap0 = w.eval(`(() => { const e = HIST.undo[HIST.undo.length - 1]; const ps = (e.parts || [e]).filter(p => p.pairs); const p = ps[ps.length - 1]; return p && p.pairs[0][0]; })()`);
  check(snap0 && snap0.id === Y && snap0.parent_id == null && snap0.section_id == null, '#4798: same list: the step\'s state before = no parent, no section ' + JSON.stringify(snap0 && [snap0.parent_id, snap0.section_id]));
  check(await undoToast(w, /Beds/), '#4798: same list: the drop offers Undo (moved to the section)');
  const b2 = await until(async () => { const t = await task(Y); return !t.parent_id && !t.section_id && t; });
  check(b2, '#4798: same list: Undo puts parent and section back on the server ' + JSON.stringify(await task(Y).then(t => [t.parent_id, t.section_id])));
  await idle(w);
  check(!w.eval('S.conflicts').length, '#4798: same list: no conflict ' + JSON.stringify(w.eval('S.conflicts')));
  w.close();

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  console.log(`p2579_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
