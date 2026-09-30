// 1.7.0 UI tests (jsdom), fresh DB: the sort mode "Flow" (topological order by "Waiting on", ties by start / due /
// priority / manual order, the "Next" marker, sections, cycles fall back to date order with a hint, default in project
// lists only with the dependencies module, hidden without it); "Overdue in one click" on Today (Today / Tomorrow / Next
// week / pick a date, time and repeat kept, view-only tasks skipped and counted, one undo step, x hides it until tomorrow,
// only on Today); the smart list "Now doable" (open, not waiting, due today / overdue / undated, mine; collaboration
// off = all; sidebar row + count, g d, palette, tab item, German).
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const st = (ck = CK) => call('GET', '/api/state', null, ck);
const until = async (fn, ms = 5000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (await fn()) return true; await sleep(80); } return false; };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const key = (w, el, k, o = {}) => el.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true, ...o}));
const today = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
const addD = (s, n) => { const [y, m, d] = s.split('-').map(Number); const x = new Date(y, m - 1, d + n); return `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}`; };
const menuLabels = d => [...d.querySelectorAll('#pop .menu-list button')].map(b => b.textContent.trim());
const ALL = 'cal,timeline,matrix,habits,pomo,kanban,paperless,collab,stats,time,progress,deps,fields';

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const BK = await login('bob');
  const ME = (await st()).me.id;
  await call('PATCH', '/api/settings', {features: ALL});
  await call('PATCH', '/api/settings', {features: ALL}, BK);
  const T0 = today(), T1 = addD(T0, 1);
  const PRJ = (await call('POST', '/api/lists', {name: 'Launch', kind: 'project'})).id;
  const PLAIN = (await call('POST', '/api/lists', {name: 'Errands'})).id;
  const mk = async (title, list_id, extra = {}, ck = CK) => (await call('POST', '/api/tasks', {title, list_id, ...extra}, ck)).id;
  const dep = (t, b, ck = CK) => call('POST', '/api/deps', {task_id: t, blocker_id: b}, ck);
  // Flow: Build (due today) waits on Spec (due in 2 days), Test (overdue) waits on Build; Docs is free but later
  const spec = await mk('Spec', PRJ, {due: addD(T0, 2)});
  const build = await mk('Build', PRJ, {due: T0, priority: 5});
  const test = await mk('Test', PRJ, {due: addD(T0, -1)});
  const docs = await mk('Docs', PRJ, {due: addD(T0, 5)});
  check((await dep(build, spec)).status < 300 && (await dep(test, build)).status < 300, 'setup: dependencies created');

  // ================= (1) Flow in a project list (default with the dependencies module)
  let w = await boot({user: 'alice', hash: 'l/' + PRJ}), d = w.document;
  const order = () => [...d.querySelectorAll('#view .trow')].map(r => +r.dataset.id);
  check(w.eval('sortMode()') === 'flow', 'project list: Flow is the default sort: ' + w.eval('sortMode()'));
  check(JSON.stringify(order()) === JSON.stringify([spec, build, test, docs]), 'Flow: a task comes after what it waits on (Spec, Build, Test, then Docs by date): ' + order());
  const nextRows = [...d.querySelectorAll('#view .trow.flownext')].map(r => +r.dataset.id);
  check(nextRows.length === 1 && nextRows[0] === spec, 'the first ready task carries the "Next" marker: ' + nextRows);
  check(/Ready to start/.test(d.querySelector(`#view .trow[data-id="${spec}"] .nxt`)?.textContent || ''), '"Ready to start" chip on the row (2.0.4)');
  check(d.querySelector(`#view .trow[data-id="${build}"] .blk`) && d.querySelector(`#view .trow[data-id="${test}"] .blk`), 'waiting tasks keep the lock');
  check(!d.querySelector('#view .flowhint'), 'no cycle hint without a cycle');
  // the sort menu offers Flow and marks it
  w.eval(`sortMenu(document.querySelector('#top h1'))`); await sleep(100);
  check(menuLabels(d).includes('Flow'), 'sort menu: "Flow" offered: ' + menuLabels(d));
  const onBtn = [...d.querySelectorAll('#pop .menu-list button')].find(b => b.classList.contains('on'));
  check(onBtn && /Flow/.test(onBtn.textContent), 'sort menu: Flow is the active mode');
  w.eval(`closePop && closePop()`);
  // an explicit choice wins over the default
  w.eval(`LS.set('sort2.l:${PRJ}', 'date'); render()`); await sleep(100);
  check(order()[0] === test && !d.querySelector('#view .trow.flownext'), 'Date sort: overdue Test first, no marker');
  w.eval(`LS.del('sort2.l:${PRJ}'); render()`); await sleep(100);
  // ties: start date, then due date + time, then priority, then manual order
  const tie = w.eval(`(() => { const m = (id, o) => ({id, sort: id, priority: 0, due: null, due_time: null, start: null, blockers: [], ...o});
    return flowSort([m(1, {due: '${addD(T0, 3)}'}), m(2, {due: '${addD(T0, 3)}', start: '${T0}'}), m(3, {due: '${T1}', due_time: '10:00'}), m(4, {due: '${T1}', due_time: '09:00'}),
      m(5, {due: '${addD(T0, 4)}', priority: 5}), m(6, {due: '${addD(T0, 4)}', priority: 1}), m(8, {}), m(7, {})]).map(t => t.id).join(','); })()`);
  check(tie === '2,4,3,1,5,6,7,8', 'ties: start, due + time, priority, manual order: ' + tie);
  // a dependency on a task outside the set is ignored for the order
  const outside = w.eval(`flowSort([{id: 1, sort: 1, priority: 0, due: '${T0}', blockers: [99]}, {id: 2, sort: 2, priority: 0, due: '${T1}', blockers: []}]).map(t => t.id).join(',')`);
  check(outside === '1,2', 'blocker outside the view does not reorder: ' + outside);
  // cycle: date order for the tasks in it + one hint
  const cyc = w.eval(`(() => { FLOW.cyc = false; const r = flowSort([{id: 1, sort: 1, priority: 0, due: '${addD(T0, 2)}', blockers: [2]}, {id: 2, sort: 2, priority: 0, due: '${T0}', blockers: [1]}, {id: 3, sort: 3, priority: 0, due: '${T1}', blockers: [1]}]).map(t => t.id).join(','); return r + '|' + FLOW.cyc; })()`);
  check(cyc === '2,1,3|true', 'cycle falls back to date order and is flagged: ' + cyc);
  w.eval(`S.tasks.get(${spec}).blockers = [${test}]; S.tasks.get(${spec}).blocked = 1; renderView()`); await sleep(50);
  check(d.querySelectorAll('#view .flowhint').length === 1 && /circle/.test(d.querySelector('#view .flowhint').textContent), 'cycle: one hint in the view');
  check(order().length === 4, 'cycle: every task still shown');
  w.close();

  // ================= (2) sections: order within each section, a marker per section
  const SEC = (await call('POST', '/api/sections', {list_id: PRJ, name: 'Later'})).id;
  await call('PATCH', `/api/tasks/${test}`, {section_id: SEC});
  await call('PATCH', `/api/tasks/${docs}`, {section_id: SEC});
  w = await boot({user: 'alice', hash: 'l/' + PRJ}); d = w.document;
  const grp = sid => [...d.querySelectorAll(`#view .ghead[data-section="${sid}"]`)].map(g => [...g.parentElement.querySelectorAll('.trow')].map(r => +r.dataset.id))[0] || [];
  check(JSON.stringify(grp('')) === JSON.stringify([spec, build]), 'section "Unassigned": Spec, Build: ' + grp(''));
  check(JSON.stringify(grp(SEC)) === JSON.stringify([test, docs]), 'section "Later": Test (waits) before Docs by flow order: ' + grp(SEC));
  const marks = [...d.querySelectorAll('#view .trow.flownext')].map(r => +r.dataset.id);
  check(marks.includes(spec) && marks.includes(docs) && !marks.includes(test), 'a "Next" marker per section, never on a waiting task: ' + marks);
  w.close();

  // ================= (3) Flow elsewhere: plain lists default unchanged, filters / smart lists can pick it; module off hides it
  w = await boot({user: 'alice', hash: 'l/' + PLAIN}); d = w.document;
  check(w.eval('sortMode()') === 'prio', 'plain list: default stays "Priority, then manual"');
  w.eval(`sortMenu(document.querySelector('#top h1'))`); await sleep(100);
  check(menuLabels(d).includes('Flow'), 'plain list: Flow can be chosen');
  w.eval(`go('all')`); await sleep(300);
  w.eval(`LS.set('sort2.all', 'flow'); render()`); await sleep(100);
  const allOrder = [...d.querySelectorAll('#view .trow')].map(r => +r.dataset.id).filter(id => [spec, build, test].includes(id));
  check(JSON.stringify(allOrder) === JSON.stringify([spec, build, test]), 'smart list "All" with Flow: ' + allOrder);
  const filt = (await call('POST', '/api/filters', {name: 'Launch only', rules: {lists: [PRJ]}})).id;
  await w.eval('load()'); w.eval(`go('f/${filt}')`); await sleep(300);
  w.eval(`LS.set('sort2.f:${filt}', 'flow'); render()`); await sleep(100);
  const fo = [...d.querySelectorAll('#view .trow')].map(r => +r.dataset.id);
  check(JSON.stringify(fo) === JSON.stringify([spec, build, test, docs]) && !d.querySelector('#view .ghead'), 'filter view with Flow: one sequence instead of date groups: ' + fo);
  w.close();
  await call('PATCH', '/api/settings', {features: ALL.replace(',deps', '')});
  w = await boot({user: 'alice', hash: 'l/' + PRJ}); d = w.document;
  check(w.eval('sortMode()') === 'prio', 'dependencies module off: project list default is "Priority, then manual" again');
  w.eval(`sortMenu(document.querySelector('#top h1'))`); await sleep(100);
  check(!menuLabels(d).includes('Flow'), 'dependencies module off: no "Flow" in the sort menu');
  w.eval(`LS.set('sort2.l:${PRJ}', 'flow')`);
  check(w.eval('sortMode()') === 'prio', 'a stored Flow choice falls back while the module is off');
  check(!d.querySelector('#view .trow.flownext'), 'no marker without the module');
  w.close();
  await call('PATCH', '/api/settings', {features: ALL});

  // ================= (4) Overdue in one click (Today only)
  const SH = (await call('POST', '/api/lists', {name: 'Bob shared'}, BK)).id;
  await call('PUT', `/api/lists/${SH}/members`, {user_id: ME, role: 'view'}, BK);
  const o1 = await mk('Overdue timed', PLAIN, {due: addD(T0, -3), due_time: '08:15', repeat: 'FREQ=WEEKLY'});
  const o2 = await mk('Overdue plain', PLAIN, {due: addD(T0, -1)});
  const o3 = await mk('Overdue of bob', SH, {due: addD(T0, -2)}, BK);
  const onToday = await mk('Due today', PLAIN, {due: T0});
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  const ban = () => d.querySelector('#view .odban');
  // overdue on Today: Test (project, waiting), o1, o2, o3
  const odN = w.eval('overdueTasks().length');
  check(ban() && new RegExp(`${odN} overdue`).test(ban().textContent), `banner on Today: "${ban()?.textContent.replace(/\s+/g, ' ').trim()}"`);
  check(odN === 4, 'overdue counted: Test, two own tasks, one view-only: ' + odN);
  check([...ban().querySelectorAll('[data-act="od-move"]')].map(b => b.textContent.trim()).join('|') === 'Today|Tomorrow|Next week (Mon)|Pick a date…', 'banner: Today / Tomorrow / Next week (Mon) / Pick a date…');
  const h0 = w.eval('HIST.undo.length');
  click(w, ban().querySelector('[data-d="1"]'));
  check(await until(async () => (await st()).tasks.find(t => t.id === o1)?.due === T1), 'Tomorrow: overdue task moved');
  let s = await st(); const g = id => s.tasks.find(t => t.id === id);
  check(g(o1).due_time === '08:15' && g(o1).repeat === 'FREQ=WEEKLY', 'time and repeat kept');
  check(g(o2).due === T1 && g(test).due === T1, 'all editable overdue tasks moved');
  check(g(o3).due === addD(T0, -2), 'view-only task untouched');
  check(g(onToday).due === T0, 'a task due today is not touched');
  await until(() => /skipped/.test(d.querySelector('#toast')?.textContent || ''), 2000);
  check(/3 tasks changed/.test(d.querySelector('#toast')?.textContent || '') && /1 task skipped \(view only\)/.test(d.querySelector('#toast')?.textContent || ''), 'toast counts moved and skipped: ' + d.querySelector('#toast')?.textContent);
  check(w.eval('HIST.undo.length') === h0 + 1, 'one undo step');
  await until(() => !w.eval('HIST.busy'));
  check(ban() && /1 overdue/.test(ban().textContent), 'banner now counts the view-only one only');
  click(w, ban().querySelector('[data-d="0"]')); await sleep(400);
  check(/view/.test(d.querySelector('#toast')?.textContent || '') && (await st()).tasks.find(t => t.id === o3).due === addD(T0, -2), 'only view-only overdue left: a toast, nothing moves');
  d.querySelector('#top [data-act="hist-undo"]').click();
  check(await until(async () => { s = await st(); return g(o1).due === addD(T0, -3) && g(o2).due === addD(T0, -1) && g(test).due === addD(T0, -1); }), 'undo puts every date back in one step');
  check(g(o1).due_time === '08:15', 'undo keeps the time');
  // next week
  await sleep(300);
  click(w, ban().querySelector('[data-d="w"]'));
  check(await until(async () => (await st()).tasks.find(t => t.id === o2)?.due === w.eval('nextWeekday(1)')), 'Next week (Mon)');
  await until(() => !w.eval('HIST.busy'));
  d.querySelector('#top [data-act="hist-undo"]')?.click();
  await until(async () => (await st()).tasks.find(t => t.id === o2)?.due === addD(T0, -1));
  await sleep(300);
  // pick a date opens the picker
  click(w, ban().querySelector('[data-d="pick"]')); await sleep(100);
  check(w.eval('!!DP.el'), 'Pick a date… opens the date picker');
  w.eval('dpClose(false)');
  // only on Today
  w.eval(`go('week')`); await sleep(300);
  check(!ban(), 'no banner on Next 7 days');
  w.eval(`go('l/${PLAIN}')`); await sleep(300);
  check(!ban(), 'no banner in a list');
  w.eval(`go('today')`); await sleep(300);
  click(w, ban().querySelector('[data-act="od-hide"]')); await sleep(100);
  check(!ban() && w.eval(`LS.get('odHide')`) === T0, 'x hides it until tomorrow (per device)');
  w.eval(`LS.set('odHide', '${addD(T0, -1)}'); renderView()`);
  check(!!ban(), 'hidden yesterday = shown again today');
  w.close();

  // ================= (5) Now doable
  const BL = (await call('POST', '/api/lists', {name: 'Bob team'}, BK)).id;
  await call('PUT', `/api/lists/${BL}/members`, {user_id: ME, role: 'edit'}, BK);
  const nd1 = await mk('Undated mine', PLAIN);
  const nd2 = await mk('Future', PLAIN, {due: addD(T0, 3)});
  await call('PUT', `/api/lists/${PLAIN}/members`, {user_id: BOB, role: 'edit'});
  const nd3b = await mk('Bob does it', PLAIN, {assignee_id: BOB});
  const nd4 = await mk('Unassigned in bob list', BL, {}, BK);
  const nd5 = await mk('Assigned to me in bob list', BL, {assignee_id: ME}, BK);
  const nd6 = await mk('Starts later', PLAIN, {start: addD(T0, 2), due: addD(T0, 4)});
  const ndp = await mk('Later parent', PLAIN, {due: addD(T0, 5)});
  const ndk = await mk('Undated step of a later task', PLAIN, {parent_id: ndp});
  const ndk2 = await mk('Step of the undated one', PLAIN, {parent_id: nd1});
  w = await boot({user: 'alice', hash: 'doable'}); d = w.document;
  const ids = () => [...d.querySelectorAll('#view .trow')].map(r => +r.dataset.id);
  // 2.1.0: CI timing: the view may still be drawing after boot; wait (max. 5 s) until the four expected rows are there
  const want = {nd1, onToday, o1, nd5};
  for (let i = 0; i < 25 && !Object.values(want).every(x => ids().includes(x)); i++) await sleep(200);
  const v = ids();
  check(d.querySelector('#top h1')?.textContent.includes('Now doable'), 'title "Now doable"');
  check(Object.values(want).every(x => v.includes(x)), 'undated, due today, overdue, assigned to me in a shared list: shown; missing: ' + Object.keys(want).filter(k => !v.includes(want[k])));
  check(!v.includes(nd2) && !v.includes(nd6), 'future and later-starting tasks: not shown');
  check(!v.includes(nd3b) && !v.includes(nd4), 'assigned to someone else / unassigned in a list I do not own: not shown');
  check(!v.includes(build) && !v.includes(test), 'waiting tasks: not shown');
  check(!v.includes(ndp) && !v.includes(ndk), 'an undated subtask of a later task: not shown (it follows its parent)');
  check(v.includes(ndk2) && d.querySelector(`#view .trow.sub[data-id="${ndk2}"]`), 'a subtask of a doable task: below its parent');
  check(!v.includes(o3), 'unassigned in a view-only list of bob: not shown');
  check(v.includes(spec) === false, 'Spec (due in 2 days): not shown');
  check(w.eval('sortMode()') === 'flow', 'Now doable sorts by Flow');
  check(v.indexOf(o1) < v.indexOf(onToday) && v.indexOf(onToday) < v.indexOf(nd1), 'order: overdue, today, undated: ' + v);
  const side = [...d.querySelectorAll('#side > .srow')].map(r => r.dataset.go);
  check(side.indexOf('doable') === side.indexOf('week') + 1, 'sidebar: row right after Next 7 days: ' + side);
  const cnt = +(d.querySelector('#side .srow[data-go="doable"] .c')?.textContent || 0);
  const tops = d.querySelectorAll('#view .trow:not(.sub)').length;
  check(cnt === tops && cnt === w.eval('counts().doable'), `sidebar count = top-level rows (${cnt} / ${tops})`);
  check(w.eval(`tabItem('s:doable')?.go`) === 'doable', 'can be pinned as a tab');
  check(w.eval(`palAll().some(x => x.id === 'v:doable' && x.keys === 'g d')`), 'palette entry with g d');
  w.eval(`go('today')`); await sleep(300);
  key(w, d.body, 'g'); key(w, d.body, 'd'); await sleep(300);
  check(w.eval('S.route.key') === 'doable', 'g d opens Now doable');
  check(w.eval(`SHORTCUTS().flatMap(g => g[1]).some(([k]) => k === 'g d')`), 'g d in the shortcuts overlay');
  // completing the blocker makes the waiting task doable
  await call('PATCH', `/api/tasks/${spec}`, {due: T0});
  await call('POST', `/api/tasks/${spec}/complete`, {});
  await w.eval('load()'); w.eval('render()');
  check(ids().includes(build), 'blocker done: the waiting task becomes doable');
  w.close();
  // collaboration off: every task counts as mine
  await call('PATCH', '/api/settings', {features: ALL.replace(',collab', '')});
  w = await boot({user: 'alice', hash: 'doable'}); d = w.document;
  check(ids().includes(nd4) && ids().includes(nd3b), 'collaboration off: all tasks, whoever they are for');
  check(w.eval('sortMode()') === 'flow', 'still Flow');
  w.close();
  await call('PATCH', '/api/settings', {features: ALL.replace(',deps', '')});
  w = await boot({user: 'alice', hash: 'doable'}); d = w.document;
  check(w.eval('sortMode()') === 'date', 'dependencies off: Now doable sorts by date');
  w.close();
  await call('PATCH', '/api/settings', {features: ALL, lang: 'de'});
  w = await boot({user: 'alice', hash: 'doable'}); d = w.document;
  check(/Jetzt machbar/.test(d.querySelector('#side .srow[data-go="doable"]')?.textContent || ''), 'German: "Jetzt machbar"');
  w.eval(`go('l/${PRJ}')`); await sleep(300);
  w.eval(`sortMenu(document.querySelector('#top h1'))`); await sleep(100);
  check(menuLabels(d).includes('Ablauf'), 'German: "Ablauf" in the sort menu: ' + menuLabels(d));
  w.eval(`go('today')`); await sleep(300);
  check(/überfällig/.test(d.querySelector('#view .odban')?.textContent || '') && /Nächste Woche \(Mo\)/.test(d.querySelector('#view .odban')?.textContent || ''), 'German banner');
  w.close();

  const bad = errs.filter(e => !/Could not parse CSS/.test(e));
  check(!bad.length, 'no script errors: ' + bad.slice(0, 3).join(' | '));
  console.log(`\np170_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
