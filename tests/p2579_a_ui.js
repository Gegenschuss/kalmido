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

  // ================= #4199 drawing with many tasks: counted, not timed
  const LS2 = [];
  for (let i = 0; i < 20; i++) LS2.push((await call('POST', '/api/lists', {name: `Project ${i + 1}`})).id);
  const SECS = [];
  for (const n of ['Doing', 'Review', 'Done-ish']) SECS.push((await call('POST', '/api/sections', {list_id: LS2[0], name: n})).id);
  const due = n => { const x = new Date(); x.setDate(x.getDate() + n); return `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}`; };
  const jobs = [];
  for (let i = 0; i < LS2.length; i++) for (let j = 0; j < 15; j++)
    jobs.push(() => mk(`Job ${i + 1}.${j + 1}`, LS2[i], {...(j % 3 === 0 ? {due: due(1 + (j % 5))} : {}), ...(i === 0 && j % 4 ? {section_id: SECS[j % 4 - 1]} : {})}));
  for (let k = 0; k < jobs.length; k += 25) await Promise.all(jobs.slice(k, k + 25).map(f => f()));
  const PRUNE = await mk('Prune the apple tree', LS2[3]);
  for (const [n, lid] of [['Early', LS2[1]], ['Second', LS2[2]], ['Third', LS2[0]]]) await call('POST', '/api/filters', {name: n, rules: {lists: [lid]}});
  w = await boot({user: 'alice', hash: 'all'}); d = w.document;
  check(await until(() => w.eval('S.tasks.size') > 300 && w.eval('S.filters.length') === 3), '#4199: setup: 300 tasks in 20 projects, 3 filters on the page ' + w.eval('S.tasks.size'));
  await idle(w);
  // a list lookup per task is no scan of S.lists any more (counted: find on the array)
  w.eval(`window.__lf = 0; (() => { const a = S.lists, f = a.find; a.find = function (...x) { window.__lf++; return f.apply(this, x); }; })()`);
  w.eval('render()');
  const lf = w.eval('window.__lf'), nt = w.eval('S.tasks.size');
  console.log(`perf: S.lists.find per render with ${nt} tasks / ${w.eval('S.lists.length')} lists = ${lf}`);
  check(lf < 30, '#4199: a render scans S.lists only a few times, not per task: ' + lf);
  // counts(): the open tasks once per call, the whole once per draw (counted: S.tasks.values)
  w.eval(`window.__tv = 0; (() => { const m = S.tasks; m.values = function () { window.__tv++; return Map.prototype.values.call(this); }; })()`);
  const fresh = w.eval('JSON.stringify(counts())'), tv1 = w.eval('window.__tv');
  w.eval('window.__tv = 0');
  const cached = w.eval('JSON.stringify(td_rcRun(() => { counts(); counts(); return counts(); }))'), tv3 = w.eval('window.__tv');
  console.log(`perf: S.tasks.values per counts() = ${tv1}, per three counts() in one draw = ${tv3}`);
  check(tv1 === 1, '#4199: counts() goes over the open tasks once (not once per filter + 1): ' + tv1);
  check(tv3 === 1, '#4199: three counts() in one draw count once: ' + tv3);
  check(cached === fresh && JSON.parse(fresh).filters && Object.keys(JSON.parse(fresh).filters).length === 3, '#4199: the cached counts are the fresh ones');
  w.eval('window.__tv = 0; render()');
  console.log(`perf: S.tasks.values per render = ${w.eval('window.__tv')}`);
  // listById stays right while S.lists changes under it (pushed, an entry swapped, an id changed in place, the array replaced)
  const lb = w.eval(`(() => {
    const r = [], a = S.lists, l0 = a[0], l1 = a[1], id1 = l1.id;
    a.push({id: 990001, name: 'Pushed'}); r.push(listById(990001)?.name === 'Pushed');
    a[0] = {...l0, name: 'Swapped'}; r.push(listById(l0.id)?.name === 'Swapped');
    l1.id = -77; r.push(listById(-77) === l1 && listById(id1) === undefined); l1.id = id1; r.push(listById(id1) === l1 && listById(-77) === undefined);
    a[0] = l0; S.lists = a.filter(x => x.id !== 990001); r.push(listById(990001) === undefined && listById(l0.id) === l0);
    r.push(listById(null) === undefined && listById(123456789) === undefined);
    return r.join();
  })()`);
  check(lb === 'true,true,true,true,true,true', '#4199: listById follows S.lists (push, swap, id change, new array, unknown) ' + lb);
  // the command field: its set once per opening, the search after a short pause in typing, Enter takes the typed text at once
  w.eval(`window.__pa = 0; window.__pd = 0; (() => { const a = palAll, b = palDraw; palAll = function (...x) { window.__pa++; return a.apply(this, x); }; palDraw = function (...x) { window.__pd++; return b.apply(this, x); }; })()`);
  // 2.595.0 (#4896): a fetched part (tables, document facets, folders) that arrives after the set was built resets it - count those
  w.eval(`window.__pr = 0; (() => { let v = PAL.all; Object.defineProperty(PAL, 'all', {configurable: true, get: () => v, set: x => { if (x === null && v) window.__pr++; v = x; }}); })()`);
  w.eval('openPalette()');
  const pin = await until(() => d.querySelector('.palette .pqin'));
  const typeIn = v => { pin.value = v; pin.dispatchEvent(new w.Event('input', {bubbles: true})); };
  const pd0 = w.eval('window.__pd');
  typeIn('Jo'); typeIn('Job'); typeIn('Job 7.1');
  check(w.eval('!!PAL.tq') && w.eval('window.__pd') === pd0, '#4199: palette: three quick keys, no search yet (it waits for the pause)');
  check(await until(() => !w.eval('PAL.tq')), '#4199: palette: the search ran after the pause');
  check(w.eval('window.__pd') === pd0 + 1, '#4199: palette: one search for the three keys ' + (w.eval('window.__pd') - pd0));
  check([...d.querySelectorAll('.palette .pitem .plt')].some(x => x.textContent === 'Job 7.1'), '#4199: palette: the typed task is found');
  typeIn('prune apple');
  pin.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Enter', bubbles: true, cancelable: true}));
  check(await until(() => w.eval('S.sel') === PRUNE), '#4199: palette: Enter right after typing runs the typed hit (not the list of before) ' + w.eval('S.sel'));
  console.log(`perf: palAll per opening with 4 searches = ${w.eval('window.__pa')}`);
  // 2.595.0 (#4896): once per opening, plus at most once again per fetched part that came in after it (not per key)
  check(w.eval('window.__pa') >= 1 && w.eval('window.__pa') <= 1 + w.eval('window.__pr'), '#4199: palette: the set is built once per opening (+ once per arrived part) ' + w.eval('window.__pa') + ' / ' + w.eval('window.__pr'));
  w.eval('closeDetail && closeDetail()');
  // the board: every task in its column as before (one pass)
  await w.eval(`setListView(listById(${LS2[0]}), 'kanban')`); w.eval(`go('l/${LS2[0]}')`);
  check(await until(() => d.querySelectorAll('#view .kanban .kcol').length === 4), '#4199: board: "Tasks" + three columns');
  const srv = (await call('GET', '/api/state')).tasks.filter(t => t.list_id === LS2[0] && !t.parent_id && t.status === 0);
  const colOk = [...d.querySelectorAll('#view .kanban .kcol')].every(c => { const sid = c.dataset.kcol ? +c.dataset.kcol : null; const ids = [...c.querySelectorAll('.trow[data-id]')].map(r => +r.dataset.id).sort().join(); return ids === srv.filter(t => (t.section_id || null) === sid).map(t => t.id).sort().join(); });
  check(colOk && srv.length === 15, '#4199: board: each column has exactly its tasks');
  // the timeline: every bar under its own project
  const tl = w.eval(`(() => { S.tlStart = addDays(weekStartOf(today()), -7); const v = document.createElement('div'); v.innerHTML = viewTimeline(null); let g = null, bad = 0, n = 0;
    for (const r of v.querySelectorAll('.tl-row')) { if (r.matches('.tl-grp[data-l]')) { g = +r.dataset.l; continue; } const x = r.querySelector('.tl-name[data-act="open"][data-id]'); if (!x) continue; n++; if (S.tasks.get(+x.dataset.id)?.list_id !== g) bad++; }
    return {n, bad, groups: v.querySelectorAll('.tl-grp[data-l]').length}; })()`);
  check(tl.n >= 100 && !tl.bad && tl.groups >= 20, '#4199: timeline: every bar in the row group of its project ' + JSON.stringify(tl));
  w.close();

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  console.log(`p2579_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
