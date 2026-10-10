// 1.5.1 UI tests (jsdom), fresh DB: statistics / time / overview / search / settings exist once (sidebar footer while the
// sidebar shows, rail only while it is folded); calendar ghosts of recurring tasks refetch when a task gets / changes /
// loses its repeat, is completed or changes on another device; "Show completed" per view in the header "…" (lists,
// filters, smart lists; synced per user, undoable, the old global value as the default, calendar unchanged); one tap
// "Today" / "Tomorrow" (task menu, detail panel, keys t / Shift+T, selection bar; time and repeat stay, undo); archived
// lists hide their tasks outside the list; the locale's first weekday in timeline, roadmap and statistics; the list
// dialog saves itself ("Saved · Undo", history, no Save button; a new list keeps Create). 1.5.2: the running timer as a
// card on top of the time page (live time, task, project, start, Stop, one-tap restart); search at the rail's bottom;
// archived lists as one plain sidebar row that opens an "Archived" view (1.6.1); "Delete completed…" on the Completed view; the folder view.
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
const task = async id => (await st()).tasks.find(t => t.id === id);

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {features: 'cal,timeline,matrix,habits,pomo,kanban,paperless,collab,stats,time,progress,deps,fields'});
  const T0 = today(), T1 = addD(T0, 1);
  const WORK = (await call('POST', '/api/lists', {name: 'Work'})).id;
  const OLD = (await call('POST', '/api/lists', {name: 'Old'})).id;
  const mk = async (title, list_id, extra = {}) => (await call('POST', '/api/tasks', {title, list_id, ...extra})).id;
  const a = await mk('Alpha', WORK, {due: T0, due_time: '14:30', repeat: 'FREQ=WEEKLY', priority: 3});
  const b = await mk('Bravo', WORK, {due: T0});
  const c = await mk('Charlie', WORK, {due: addD(T0, -2)});
  const done1 = await mk('Done one', WORK, {due: T0});
  await call('POST', `/api/tasks/${done1}/complete`, {});
  const hid = await mk('Hidden in archive', OLD, {due: T0, priority: 5});
  await mk('Old recurring', OLD, {due: T0, repeat: 'FREQ=DAILY'});
  await call('PATCH', `/api/lists/${OLD}`, {archived: 1});

  // ================= (a) navigation exists once
  let w = await boot({user: 'alice', hash: 'today'}), d = w.document;
  // 2.8.0 (#434): no rail; the sidebar holds search / statistics / time / overview / settings once (desktop and drawer)
  check(!d.querySelector('#rail'), 'no rail any more');
  const navK = [...d.querySelectorAll('#side .srow')].map(x => x.dataset.go || x.dataset.act);
  const want = ['stats', 'time', ...(w.eval('overviewOn()') ? ['overview'] : []), 'settings'];
  // 2.13.3: the search is the command-bar field at the top (no "Search" row)
  check(want.every(k => navK.filter(x => x === k).length === 1) && d.querySelectorAll('#side .scmd[data-act="palette"]').length === 1 && !navK.includes('search'), 'sidebar: search (the field) / statistics / time / overview / settings, each once: ' + navK);
  const css = await (await fetch(B + 'static/app.css')).text();
  check(!/#side \.dupnav\{display:none\}/.test(css.split('2.8.0 "Leitstand"').pop()), 'CSS: nothing in the new sidebar is hidden on the desktop');

  // ================= (e) archived lists: hidden outside the list
  const txt = () => d.querySelector('#view').textContent;
  check(!txt().includes('Hidden in archive'), 'Today: task of an archived list hidden');
  check(w.eval('counts().today') === 3, 'Today count without the archived task: ' + w.eval('counts().today'));
  check(!w.eval(`openTasks().some(t => t.list_id === ${OLD})`), 'openTasks leaves out the archived list (matrix, overview, filters, tags)');
  w.eval(`go('matrix')`); await sleep(300);
  check(!txt().includes('Hidden in archive') && txt().includes('Alpha'), 'matrix: archived task hidden');
  w.eval(`go('l/${OLD}')`); await sleep(400);
  check(txt().includes('Hidden in archive'), 'the archived list itself still shows its tasks');
  w.eval(`go('cal')`); await sleep(1500);
  check(!w.eval(`[...calByDay('${T0}', '${addD(T0, 6)}').values()].flat().some(t => t.list_id === ${OLD})`), 'calendar: no tasks or ghosts of the archived list');

  // ================= (b) calendar ghosts follow the recurring tasks
  // the checks ask calByDay for three weeks themselves; the open calendar would ask for its own range in between
  w.eval(`go('today')`); await sleep(300);
  const ghosts = () => w.eval(`[...calByDay('${T0}', '${addD(T0, 20)}').values()].flat().filter(t => t.ghost).map(t => t.id + '@' + t.due)`);
  check(await until(() => ghosts().includes(`${a}@${addD(T0, 7)}`)), 'weekly task: ghost a week later: ' + ghosts());
  check(!ghosts().some(g => g.startsWith(b + '@')), 'no ghosts for a one-off task');
  await w.eval(`patchTask(${b}, {repeat: 'FREQ=DAILY'})`);
  check(await until(() => ghosts().includes(`${b}@${T1}`)), 'a task that gets a repeat shows its ghosts without reloading the calendar: ' + ghosts());
  const keyBefore = w.eval('S.occ.key');
  await w.eval(`patchTask(${b}, {repeat: 'FREQ=WEEKLY'})`);
  check(await until(() => !ghosts().includes(`${b}@${T1}`) && ghosts().includes(`${b}@${addD(T0, 7)}`)), 'a changed repeat refetches (daily -> weekly)');
  check(w.eval('S.occ.key') !== keyBefore, 'cache key follows the recurring tasks');
  await w.eval(`patchTask(${b}, {repeat: ''})`);
  check(await until(() => !ghosts().some(g => g.startsWith(b + '@'))), 'repeat removed: ghosts gone at once');
  await w.eval(`toggleTask(${a})`); await sleep(300);
  check(await until(() => ghosts().includes(`${a}@${addD(T0, 14)}`) && !ghosts().includes(`${a}@${addD(T0, 7)}`)), 'completed occurrence: the series moves on (next ghost two weeks out)');
  // another device changes the repeat (sync = the state reload)
  await call('PATCH', `/api/tasks/${c}`, {repeat: 'FREQ=DAILY', due: T0});
  await w.eval('load()'); w.eval('render()');
  check(await until(() => ghosts().includes(`${c}@${T1}`)), 'a repeat set on another device shows after the sync');
  // old items stay while the new answer loads
  w.eval(`S.occ.want = 'x'; window.__n = S.occ.items.length`);
  check(w.eval('S.occ.items.length') === w.eval('window.__n') && w.eval('S.occ.items.length') > 0, 'items stay while a newer request loads');
  w.eval(`S.occ.want = ''`);
  w.eval(`go('cal')`); await sleep(300);
  for (const v of ['week', 'day', 'month']) {  // the open views show the ghosts too (c repeats daily now)
    w.eval(`S.calSel = '${T1}'; S.calMonth = '${T1}'.slice(0, 7); S.calMode = '${v}'; renderView()`);
    check(await until(() => !!d.querySelector(`#view .ghost[data-id="${c}"]`)), `${v} view shows the ghost of tomorrow`);
  }
  w.eval(`S.calSel = '${T0}'; S.calMode = 'month'`);

  // ================= (c) "Show completed" per view
  w.eval(`go('today')`); await sleep(400);
  const doneGroup = () => [...d.querySelectorAll('#view .ghead')].some(g => /Completed/.test(g.textContent));
  check(doneGroup(), 'Today: Completed group (shown by default)');
  click(w, d.querySelector('#top [data-act="top-more"]')); await sleep(80);
  check(menuLabels(d).includes('Hide completed'), 'header "…": Hide completed: ' + menuLabels(d));
  click(w, [...d.querySelectorAll('#pop .menu-list button')].find(x => x.textContent.trim() === 'Hide completed')); await sleep(300);
  check(!doneGroup(), 'Today: group gone');
  check(await until(async () => JSON.parse((await st()).settings.show_done_views).today === 0), 'stored per view on the server');
  check(!('show_completed' in (await st()).settings), '1.8.1: no global setting any more');
  check(w.eval('HIST.undo[HIST.undo.length - 1].label') === 'Hide completed: Today', 'history step: ' + w.eval('HIST.undo[HIST.undo.length - 1]?.label'));
  w.eval(`go('l/${WORK}')`); await sleep(400);
  check(doneGroup(), 'the list keeps its own (default) choice');
  w.eval(`go('today')`); await sleep(300);
  await w.eval(`histStep('undo')`); await sleep(200);
  check(doneGroup() && !('today' in JSON.parse((await st()).settings.show_done_views)), 'undo: back to the default');
  await w.eval(`histStep('redo')`); await sleep(200);
  check(!doneGroup(), 'redo');
  // sort menu + palette act on the current view
  w.eval(`sortMenu(document.querySelector('#top h1'))`); await sleep(80);
  check(menuLabels(d).includes('Show completed'), 'sort menu: the current view: ' + menuLabels(d));
  w.eval('closePop()');
  w.eval('openPalette()'); await sleep(100);
  check(w.eval(`palAll().some(x => x.id === 'a:showdone' && x.label === 'Show completed: Today')`), 'palette: names the view');
  w.eval('closePalette()');
  // filters and smart lists have their completed tasks too
  const FID = (await call('POST', '/api/filters', {name: 'Mine', rules: {lists: [WORK]}})).id;
  await w.eval('load()');
  for (const k of ['week', 'all', `f/${FID}`]) {
    w.eval(`go('${k}')`); await sleep(300);
    click(w, d.querySelector('#top [data-act="top-more"]')); await sleep(60);
    check(menuLabels(d).includes('Hide completed') && doneGroup(), `${k}: Completed group + toggle`);
    w.eval('closePop()');
  }
  // 1.8.1: no global default any more: an old show_completed value is ignored, a view without its own choice shows
  w.eval(`S.settings.show_completed = '0'; render()`);
  w.eval(`go('l/${WORK}')`); await sleep(300);
  check(doneGroup() && w.eval(`showDone('inbox')`), 'a view without its own choice shows (old global value ignored)');
  await w.eval(`setShowDone(false)`); await sleep(200);
  check(!doneGroup() && !w.eval(`showDone('l:${WORK}')`) && w.eval(`showDone('inbox')`), 'own choice only for this view');
  await w.eval(`setShowDone(true)`); await sleep(200);
  w.eval(`settingsModal('general')`); await sleep(200);
  check(!d.querySelector('.smodal #s-showdone') && !/Show in lists/.test(d.querySelector('.smodal').textContent), 'Settings: the global switch is gone');
  d.querySelector('.smodal').remove();
  // the calendar: own entry "cal" in show_done_views, toggle in its bar, default shown
  const z = await mk('Done in the calendar', WORK, {due: T0}); await w.eval('load()'); await w.eval(`toggleTask(${z})`); await sleep(300);
  const calDone = () => w.eval(`[...calByDay('${T0}', '${T0}').values()].flat().some(t => t.id === ${z} && t.status)`);
  w.eval(`go('cal')`); await sleep(300); w.eval(`S.calSel = '${T0}'; S.calMonth = '${T0}'.slice(0, 7); S.calMode = 'month'; renderView()`);
  const chip = () => d.querySelector('#view .calbar [data-act="cal-done"]');
  check(calDone() && chip() && chip().getAttribute('aria-pressed') === 'true', 'calendar: completed shown by default, toggle pressed');
  click(w, chip()); await sleep(300);
  check(!calDone() && chip().getAttribute('aria-pressed') === 'false', 'calendar toggle hides completed tasks');
  check(await until(async () => JSON.parse((await st()).settings.show_done_views).cal === 0), 'stored as the calendar\'s own entry');
  check(w.eval(`showDone('l:${WORK}')`), 'lists keep their own choice');
  check(w.eval('HIST.undo[HIST.undo.length - 1].label') === 'Hide completed: Calendar', 'history step names the calendar: ' + w.eval('HIST.undo[HIST.undo.length - 1]?.label'));
  w.eval('openPalette()'); await sleep(100);
  check(w.eval(`palAll().some(x => x.id === 'a:showdone' && x.label === 'Show completed: Calendar')`), 'palette: calendar toggle');
  w.eval('closePalette()');
  for (const v of ['week', 'day']) { w.eval(`S.calMode = '${v}'; renderView()`); check(!!chip(), `${v} view has the toggle`); }
  await w.eval(`histStep('undo')`); await sleep(200);
  check(calDone() && !('cal' in JSON.parse((await st()).settings.show_done_views)), 'undo: calendar back to the default (shown)');
  if (w.eval(`feat('timeline')`)) { w.eval(`S.calMode = 'timeline'; renderView()`); check(!chip(), 'timeline mode: no toggle'); }
  w.eval(`S.calSel = '${T0}'; S.calMode = 'month'`);
  // a checklist has no toggle
  const CKL = (await call('POST', '/api/lists', {name: 'Shop', kind: 'checklist'})).id;
  await w.eval('load()'); w.eval(`go('l/${CKL}')`); await sleep(300);
  check(!w.eval('doneToggleView()'), 'checklists keep their Done section, no toggle');

  // ================= (d) one tap Today / Tomorrow
  w.eval(`go('l/${WORK}')`); await sleep(300);
  await call('PATCH', `/api/tasks/${a}`, {due: addD(T0, 3), due_time: '14:30'}); await w.eval('load()'); w.eval('render()');
  w.eval(`taskMenu(document.querySelector('#view .trow[data-id="${a}"]'), ${a})`); await sleep(80);
  // 2.31.0 (#1056): the menu is grouped; the first group "Plan" starts with the two buttons (right under its small heading)
  const g0 = d.querySelector('#pop .menu-list').firstElementChild;
  const q = [...d.querySelectorAll('#pop .menu-list > .mgrp:first-child > .mgh + .mquick button')];
  check(q.length === 2 && g0.classList.contains('mgrp') && g0.querySelector('.mgh').textContent === 'Plan' && g0.children[1].classList.contains('mquick'), 'task menu: two buttons on top');
  check(q.map(x => x.textContent.trim()).join('|') === 'Today|Tomorrow', 'labels: ' + q.map(x => x.textContent.trim()));
  click(w, q[1]);
  check(await until(async () => (await task(a)).due === T1), 'Tomorrow: due tomorrow');
  let t = await task(a);
  check(t.due_time === '14:30' && t.repeat === 'FREQ=WEEKLY', 'time and repeat stay');
  check(await until(() => /Date of/.test(w.eval('HIST.undo[HIST.undo.length - 1]?.label || ""'))), 'one history step: ' + w.eval('HIST.undo[HIST.undo.length - 1]?.label'));
  await w.eval(`histStep('undo')`);
  check(await until(async () => (await task(a)).due === addD(T0, 3)), 'undo puts the old day back');
  // detail panel
  w.eval(`openDetail(${a})`); await sleep(300);
  const dq = [...d.querySelectorAll('#detail .dtop [data-act="due-q"]')];
  check(dq.length === 2 && /^Due: Today/.test(dq[0].title), 'detail panel: two buttons next to the date');
  click(w, dq[0]);
  check(await until(async () => (await task(a)).due === T0), 'detail: Today');
  check(await until(() => d.querySelector('#detail [data-act="due-q"][data-d="0"]')?.classList.contains('on')), 'detail: Today marked');
  w.eval('closeDetail()'); await sleep(100);
  // keyboard: t / Shift+T on the focused row
  w.eval(`kfocus(${b})`);
  key(w, d.body, 'T', {shiftKey: true});
  check(await until(async () => (await task(b)).due === T1), 'Shift+T: tomorrow');
  key(w, d.body, 't');
  check(await until(async () => (await task(b)).due === T0), 't: today');
  w.eval('shortcutsModal()'); await sleep(100);
  check(/Due today/.test(d.querySelector('.modal').textContent) && /Due tomorrow/.test(d.querySelector('.modal').textContent), 'shortcut help lists t / Shift+T');
  d.querySelector('.modal').remove();
  // selection bar
  // 2.26.0 (#936): the date of a selection is set in the multi panel (the bar keeps Complete / Delete)
  w.eval(`S.multi.add(${a}); S.multi.add(${b}); render()`); await sleep(100);
  click(w, d.querySelector('#detail.multi [data-act="me-f"][data-f="date"]')); await sleep(100);
  const tmw = [...d.querySelectorAll('#pop .menu-list button')].find(x => x.textContent.trim() === 'Tomorrow');
  check(!!tmw && !!d.querySelector('#detail.multi [data-act="me-shift"]'), 'selection: Today / Tomorrow / shift in the multi panel');
  click(w, tmw);
  check(await until(async () => (await task(a)).due === T1 && (await task(b)).due === T1), 'selection: both tomorrow');
  check((await task(a)).due_time === '14:30', 'selection: time kept');
  await w.eval(`histStep('undo')`);
  check(await until(async () => (await task(a)).due === T0 && (await task(b)).due === T0), 'selection: one undo for both');
  w.eval(`S.multiMode = false; S.multi.clear(); render()`);

  // ================= (f) first weekday: timeline, roadmap, statistics
  const ws = w.eval('weekStart()');
  w.eval(`S.tlStart = null; go('l/${WORK}')`);
  await call('PATCH', `/api/lists/${WORK}`, {view: 'timeline'}); await w.eval('load()'); w.eval('render()'); await sleep(300);
  check(w.eval('pd(S.tlStart).getDay()') === ws, `timeline starts on the first weekday (${ws})`);
  w.eval(`go('all')`); await sleep(200);
  w.eval(`S.rmStart = null; viewRoadmap()`);
  check(w.eval('pd(S.rmStart).getDay()') === ws, 'roadmap starts on the first weekday');
  const seen = [];
  const f0 = w.fetch; w.fetch = (u, o) => { seen.push(String(u)); return f0(u, o); };
  w.eval(`S.st.loading = false; loadStats()`); await sleep(500);
  check(seen.some(u => u.includes('/api/stats?ws=' + ws)), 'statistics ask for the first weekday: ' + seen.join(','));
  check(w.eval('pd(S.st.data.weeks[0]).getDay()') === ws, 'statistics weeks start on it');
  w.fetch = f0;
  await call('PATCH', `/api/lists/${WORK}`, {view: 'list'}); await w.eval('load()');

  // ================= (g) the list dialog saves itself
  w.eval(`go('l/${WORK}')`); await sleep(200);
  w.eval(`listModal(${WORK})`); await sleep(200);
  const md = () => d.querySelector('.modal.lmodal');
  check(md() && !md().querySelector('[data-m="save"]') && !/Cancel/.test(md().querySelector('.foot').textContent), 'no Save / Cancel');
  check(!!md().querySelector('.lhdr [data-m="close"]'), 'close button in the header');
  const col = [...md().querySelectorAll('#l-col button')].find(x => x.dataset.c && !x.classList.contains('on'));
  click(w, col);
  check(await until(async () => (await st()).lists.find(l => l.id === WORK).color === col.dataset.c), 'colour saves at once');
  check(await until(() => md().querySelector('.ssaved.on [data-m="l-undo"]')), '"Saved · Undo" in the header');
  check(await until(() => /Settings of/.test(w.eval('HIST.undo[HIST.undo.length - 1]?.label || ""'))), 'history step: ' + w.eval('HIST.undo[HIST.undo.length - 1]?.label'));
  click(w, md().querySelector('[data-m="l-undo"]'));
  check(await until(async () => (await st()).lists.find(l => l.id === WORK).color === ''), 'Undo in the dialog');
  check(await until(() => !md().querySelector('#l-col button.on') || md().querySelector('#l-col button.on').dataset.c === ''), 'the dialog shows the old colour again');
  const nm = md().querySelector('#l-name');
  nm.value = 'Work stuff'; nm.dispatchEvent(new w.Event('input', {bubbles: true}));
  nm.dispatchEvent(new w.FocusEvent('focusout', {bubbles: true}));
  check(await until(async () => (await st()).lists.find(l => l.id === WORK).name === 'Work stuff'), 'name saves on leaving the field');
  nm.value = '  '; nm.dispatchEvent(new w.FocusEvent('focusout', {bubbles: true})); await sleep(400);
  check((await st()).lists.find(l => l.id === WORK).name === 'Work stuff' && nm.value === 'Work stuff', 'an empty name is not saved, the field gets the name back');
  const fo = md().querySelector('#l-folder');
  fo.value = 'Jobs'; fo.dispatchEvent(new w.Event('input', {bubbles: true}));
  click(w, md().querySelector('[data-m="close"]'));
  check(await until(async () => (await st()).lists.find(l => l.id === WORK).folder === 'Jobs'), 'typed text is saved when the dialog closes');
  const vw = () => { w.eval(`listModal(${WORK})`); return d.querySelector('.modal.lmodal'); };
  const m2 = vw(); await sleep(100);
  m2.querySelector('#l-view').value = 'kanban'; m2.querySelector('#l-view').dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(async () => (await st()).lists.find(l => l.id === WORK).view === 'kanban'), 'select saves at once');
  m2.remove();
  w.eval(`listModal()`); await sleep(100);
  const nw = [...d.querySelectorAll('.modal')].pop();
  check(!nw.classList.contains('lmodal') && nw.querySelector('[data-m="save"]')?.textContent === 'Create', 'a new list keeps Create');
  nw.querySelector('#l-name').value = 'Fresh'; click(w, nw.querySelector('[data-m="save"]'));
  check(await until(async () => (await st()).lists.some(l => l.name === 'Fresh')), 'Create works');

  // ================= (i) sidebar: 2.13.0: search at the top (no longer in the footer); 2.13.3: the command-bar field is the one
  // search entry (no separate "Search" row next to it)
  const rk = [...d.querySelectorAll('#side .sfoot > *')].map(x => x.dataset.go || x.dataset.act || '');
  check(!rk.includes('search') && d.querySelector('#side .scmd[data-act="palette"]') && !d.querySelector('#side [data-go="search"]') && rk.includes('settings'), 'sidebar: the command-bar field at the top is the search, settings in the footer: ' + rk.join(','));

  // ================= (h) time page: the running timer as a card
  const PRJ = (await call('POST', '/api/lists', {name: 'Client X', kind: 'project', color: '#f59e0b'})).id;
  const tt = await mk('Write offer', PRJ);
  await w.eval('load()'); w.eval(`go('time')`); await sleep(400);
  check(!!d.querySelector('.tvrun.idle') && /No timer running/.test(d.querySelector('.tvrun').textContent), 'nothing running: short hint');
  await w.eval(`timerStart({task_id: ${tt}})`); await sleep(300);
  const card = () => d.querySelector('#view .tvrun:not(.idle)');
  check(!!card() && d.querySelector('#view').firstElementChild.firstElementChild === card(), 'running: card on top of the page');
  check(/Write offer/.test(card().querySelector('.tvr-task').textContent) && /Client X/.test(card().querySelector('.tvr-list').textContent) && /since \d\d:\d\d/.test(card().textContent), 'card: task, project, start time');
  w.eval(`S.timer.start = new Date(Date.now() - 3723e3).toISOString()`); await sleep(1300);
  check(/1:02:0\d/.test(card().querySelector('[data-timer-live]').textContent), 'card: live time ticks: ' + card().querySelector('[data-timer-live]').textContent);
  click(w, card().querySelector('.tvr-task')); await sleep(300);
  check(w.eval('S.sel') === tt, 'task title opens the task');
  w.eval('closeDetail()');
  click(w, card().querySelector('[data-act="tv-stop"]'));
  check(await until(async () => !(await call('GET', '/api/state')).timer && !card()), 'Stop ends the timer, the card goes');
  check(await until(() => !!d.querySelector(`.tvrun.idle [data-act="timer-toggle"][data-id="${tt}"]`)), 'hint offers the task just tracked');
  click(w, d.querySelector(`.tvrun.idle [data-act="timer-toggle"][data-id="${tt}"]`));
  check(await until(async () => (await call('GET', '/api/state')).timer?.task_id === tt), 'one tap starts it again');
  await w.eval('timerStop()');
  const css2 = await (await fetch(B + 'static/app.css')).text();
  check(/@media \(max-width:899px\)\{\s*\.tvrun\{grid-template-columns:minmax\(0,1fr\)/.test(css2), 'phone: the card stacks');

  // ================= (j) archived lists: one plain row "Archived" like Trash (1.6.1), a main view lists them
  w.eval(`go('today')`); await sleep(300);
  const sarch = () => d.querySelector('#side .sarch');
  const archRow = () => d.querySelector(`#side .srow[data-list="${OLD}"]`);
  const trashRow = d.querySelector('#side .srow[data-go="trash"]');
  check(sarch() && /Archived/.test(sarch().textContent) && sarch().querySelector('.c').textContent === '1', 'one row "Archived 1"');
  check(!sarch().querySelector('.fcar') && !sarch().hasAttribute('aria-expanded') && !sarch().classList.contains('closed') && sarch().dataset.go === 'archived', 'plain row: no chevron, no fold, goes to #archived');
  const shape = r => [...r.children].map(x => x.tagName + '.' + [...x.classList].filter(c => c !== 'over').join(' ')).join().replace(/trash/g, 'archive');
  check(shape(sarch()) === shape(trashRow), 'same structure as the Trash row: ' + shape(sarch()) + ' / ' + shape(trashRow));
  check(sarch().parentElement === trashRow.parentElement && sarch().previousElementSibling === trashRow, 'right below Trash in the footer');
  check(!archRow(), 'the archived list itself is never in the sidebar');
  check(!w.eval(`S.collapsed.has('side:arch-open')`) && !w.eval(`/side:arch-open|side-arch/.test(renderSide.toString())`), 'no fold state any more');
  click(w, sarch()); await sleep(400);
  check(w.eval('S.route.key') === 'archived' && w.location.hash === '#archived', 'opens the "Archived" view (own hash)');
  check(sarch().classList.contains('on') && d.querySelector('#top h1').textContent.startsWith('Archived'), 'row lit, title "Archived"');
  check(!d.querySelector('#view #qinput') && w.eval('noFab()'), 'no quick add on the view');
  const arow = () => d.querySelector(`#view .arow[data-list="${OLD}"]`);
  check(!!arow() && /Old/.test(arow().querySelector('.aname').textContent), 'lists the archived list');
  check(/2 open · 0 done/.test(arow().querySelector('.ameta').textContent) && /archived /.test(arow().querySelector('.ameta').textContent), 'task counts and the archived date: ' + arow().querySelector('.ameta').textContent);
  check(!!arow().querySelector('.aname .sw, .aname .aemo') &&  // 2.36.2 (#1135): line icon / dot instead of the swatch
    !!arow().querySelector(`[data-go="l/${OLD}"]`) && !!arow().querySelector('[data-act="arch-restore"]') && !!arow().querySelector('[data-act="arch-del"]'), 'colour, Open, Restore, Delete permanently');
  check(!!(await st()).lists.find(l => l.id === OLD).archived_at, 'server keeps when it was archived');
  click(w, arow().querySelector('.aacts [data-go]')); await sleep(400);
  check(w.eval('S.route.key') === `l:${OLD}` && txt().includes('Hidden in archive'), 'Open shows the list as before');
  check(!archRow() && sarch().classList.contains('on'), 'an open archived list lights the "Archived" row, not a row of its own');
  // Restore (undoable) from the view
  w.eval(`go('archived')`); await sleep(300);
  click(w, arow().querySelector('[data-act="arch-restore"]'));
  check(await until(async () => !(await st()).lists.find(l => l.id === OLD).archived), 'Restore brings the list back');
  check(await until(() => !arow() && !sarch() && /No archived lists/.test(txt())), 'empty state, the row goes: ' + txt().slice(0, 80));
  check(!(await st()).lists.find(l => l.id === OLD).archived_at, 'archived date cleared on restore');
  check(await until(() => !!d.querySelector(`#side .srow[data-list="${OLD}"]`)), 'back among the lists');
  await w.eval(`histStep('undo')`); await w.eval('load()'); w.eval('render()'); await sleep(200);
  check((await st()).lists.find(l => l.id === OLD).archived && !!arow() && !!sarch(), 'undo archives it again');
  // Delete permanently: only for an archived list of the owner, the app's own dialog
  const GONE = (await call('POST', '/api/lists', {name: 'Gone'})).id;
  await mk('Gone task', GONE);
  await call('PATCH', `/api/lists/${GONE}`, {archived: 1});
  await w.eval('load()'); w.eval('render()'); await sleep(200);
  check(sarch().querySelector('.c').textContent === '2', 'count follows');
  let asked = '';
  w.confirm = m => { asked = m; return false; };
  click(w, d.querySelector(`#view .arow[data-list="${GONE}"] [data-act="arch-del"]`)); await sleep(300);
  check(/Delete “Gone” permanently/.test(asked) && (await st()).lists.some(l => l.id === GONE), 'asks with the own dialog; Cancel keeps it');
  w.confirm = () => true;
  click(w, d.querySelector(`#view .arow[data-list="${GONE}"] [data-act="arch-del"]`));
  check(await until(async () => !(await st()).lists.some(l => l.id === GONE)), 'confirmed: deleted for good');
  check(await until(() => !d.querySelector(`#view .arow[data-list="${GONE}"]`) && sarch()?.querySelector('.c').textContent === '1'), 'gone from the view');
  // a member sees an archived shared list, may open it, but not restore / delete it
  const BEA = (await call('POST', '/api/users', {username: 'bea', display_name: 'Bea', password: 'password123'})).id;
  const SH = (await call('POST', '/api/lists', {name: 'Shared old'})).id;
  const shr = await call('PUT', `/api/lists/${SH}/members`, {user_id: BEA, role: 'edit'});
  await call('PATCH', `/api/lists/${SH}`, {archived: 1});
  if (shr.status < 300) {
    const wb = await boot({user: 'bea', hash: 'archived'}), db = wb.document;
    const r = db.querySelector(`#view .arow[data-list="${SH}"]`);
    check(!!r && /Shared by Alice/.test(r.textContent) && !!r.querySelector('[data-go]') && !r.querySelector('[data-act="arch-restore"]') && !r.querySelector('[data-act="arch-del"]'), 'member: owner shown, Open only');
    wb.close();
  } else check(false, 'share for the member test: ' + JSON.stringify(shr));
  await call('PATCH', `/api/lists/${SH}`, {archived: 0});
  // phone drawer: the same row; an old fold state on the device is dropped
  const wp = await boot({user: 'alice', mobile: true, hash: 'l/' + OLD, ls: {'tasks.collapsed': JSON.stringify(['side:arch-open', 'fold:x'])}}), dp = wp.document;
  const ps = dp.querySelector('#side .sarch');
  check(!!ps && ps.classList.contains('on') && !ps.querySelector('.fcar') && !dp.querySelector(`#side .srow[data-list="${OLD}"]`), 'phone drawer: plain row, lit for the open archived list');
  check(!wp.eval(`S.collapsed.has('side:arch-open')`) && wp.eval(`S.collapsed.has('fold:x')`), 'old "side:arch-open" state ignored, others kept');
  click(wp, ps); await sleep(400);
  check(wp.eval('S.route.key') === 'archived' && !!dp.querySelector(`#view .arow[data-list="${OLD}"]`), 'phone: opens the view');
  wp.close();
  w.eval(`go('l/${OLD}')`); await sleep(300);

  // ================= (l) folder view
  const SIDE = (await call('POST', '/api/lists', {name: 'Side gig', folder: 'Jobs', color: '#f472b6'})).id;
  await mk('Invoice side gig', SIDE);
  await mk('Loose inbox thing', null);
  await w.eval('load()'); w.eval(`go('today')`); await sleep(300);
  const fh = () => d.querySelector('#side .fhead[data-folder="Jobs"]');
  check(!!fh().querySelector('.fgo[data-go="folder/Jobs"]'), 'folder name links to the folder view');
  click(w, fh().querySelector('.fgo')); await sleep(400);
  check(w.eval('S.route.key') === 'folder:Jobs' && w.location.hash === '#folder/Jobs', 'opens the folder view (own hash)');
  check(fh().classList.contains('on'), 'folder row marked as the current view');
  const heads = [...d.querySelectorAll('#view .ghead')].map(x => x.textContent);
  check(heads.some(x => /Work stuff/.test(x)) && heads.some(x => /Side gig/.test(x)) && !!d.querySelector('#view .ghead .gsw'), 'grouped by list with colour: ' + heads.join(' | '));
  check(txt().includes('Invoice side gig') && txt().includes('Alpha') && !txt().includes('Loose inbox thing'), 'tasks of the folder only');
  check(d.querySelector('#top h1').textContent.startsWith('Jobs'), 'title = folder name');
  check(w.eval('quickDefaults().list_id') === w.eval(`folderLists('Jobs')[0].id`), 'quick add goes to the first list of the folder');
  check(w.eval('doneToggleView()'), 'has its own "Show completed"');
  const wasClosed = fh().classList.contains('closed');
  click(w, fh().querySelector('.fcar')); await sleep(200);
  check(fh().classList.contains('closed') !== wasClosed && w.eval('S.route.key') === 'folder:Jobs', 'the chevron still folds, the view stays');
  check(w.eval(`tabItem('folder:Jobs').go`) === 'folder/Jobs', 'can be pinned as a tab');

  // ================= (k) "Delete completed…" on the Completed view
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const BK = await login('bob');
  const BL = (await call('POST', '/api/lists', {name: 'Bob list'}, BK)).id;
  await call('PUT', `/api/lists/${BL}/members`, {user_id: 1, role: 'view'}, BK);
  const bt = (await call('POST', '/api/tasks', {title: 'Bob done', list_id: BL}, BK)).id;
  await call('POST', `/api/tasks/${bt}/complete`, {}, BK);
  const ckt = await mk('Butter', CKL); await call('POST', `/api/tasks/${ckt}/complete`, {});
  const dn = await mk('Finished thing', WORK); await call('POST', `/api/tasks/${dn}/complete`, {});
  await w.eval('load()'); w.eval(`go('done')`); await sleep(600);
  check(!!d.querySelector('#top [data-act="done-clean"]'), 'Completed view: "Delete completed…" in the header');
  w.__dialogs = 'manual';
  click(w, d.querySelector('#top [data-act="done-clean"]')); await sleep(500);
  const dlg = () => d.querySelector('.modal.cdlg');
  const doneMine = (await call('GET', '/api/tasks?scope=done')).tasks.filter(t => t.list_id !== BL && t.list_id !== CKL);
  check(dlg() && dlg().querySelectorAll('input[name="dc-age"]').length === 3, 'dialog: all / 30 / 90 days');
  check(new RegExp(`Move ${doneMine.length} tasks? to the trash`).test(dlg().querySelector('[data-cd="yes"]').textContent), 'OK names the count: ' + dlg().querySelector('[data-cd="yes"]').textContent + ' / ' + doneMine.length);
  check(/1 task in a list you may only view stays/.test(dlg().textContent) && /Items of lists that show completed tasks at the bottom stay/.test(dlg().textContent), 'says what stays: ' + dlg().querySelector('#dc-note').textContent);
  const r90 = dlg().querySelector('input[value="90"]'); r90.checked = true; r90.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(dlg().querySelector('[data-cd="yes"]').disabled && /Move 0 tasks/.test(dlg().querySelector('[data-cd="yes"]').textContent), 'older than 90 days: nothing, OK disabled');
  const r0 = dlg().querySelector('input[value="0"]'); r0.checked = true; r0.dispatchEvent(new w.Event('change', {bubbles: true}));
  click(w, dlg().querySelector('[data-cd="yes"]'));
  check(await until(async () => (await call('GET', '/api/tasks?scope=done')).tasks.every(t => t.list_id === BL || t.list_id === CKL)), 'all of mine moved to the trash');
  const left = (await call('GET', '/api/tasks?scope=done')).tasks.map(t => t.title).sort().join(',');
  check(left === 'Bob done,Butter', 'view-only and checklist items stay: ' + left);
  check((await call('GET', '/api/tasks?scope=trash')).tasks.some(t => t.id === dn), 'in the trash');
  // 2.18.0 (#652, the flake): the server is done before the app records the step (it reloads its state first), so wait
  // for the step itself instead of reading it right after the server check
  check(await until(() => /Deleted \d+ completed tasks?/.test(w.eval('HIST.undo[HIST.undo.length - 1]?.label || ""'))), 'one history step: ' + w.eval('HIST.undo[HIST.undo.length - 1]?.label'));
  const ser = (await call('GET', '/api/state')).tasks.find(t => t.id === a);
  check(ser && ser.status === 0 && ser.repeat === 'FREQ=WEEKLY', 'the recurring series stays open');
  await w.eval(`histStep('undo')`);
  check(await until(async () => (await call('GET', '/api/tasks?scope=done')).tasks.length === doneMine.length + 2), 'one undo brings them all back');
  w.__dialogs = undefined;

  // ================= 1.5.3 (m) Filters: no placeholder line, the text is the tooltip
  w.eval(`go('today')`); await sleep(200);
  const fhd = [...d.querySelectorAll('#side .shead')].find(x => /Filters/.test(x.textContent));
  check(fhd && /Combine lists, dates, priorities, tags/.test(fhd.title) && /Combine lists/.test(fhd.querySelector('[data-act="filter-new"]').title) && fhd.querySelector('[data-act="filter-new"]').getAttribute('aria-label') === 'New filter', 'Filters heading + "+" carry the text as tooltip');
  check(!/Combine lists, dates, priorities, tags/.test(d.querySelector('#side').textContent), 'no placeholder line');

  // ================= (n) tooltips, keyboard hints, show-once hints (desktop jsdom = mouse)
  check(/\(G T\)/.test(d.querySelector('#side .srow[data-go="today"]').title), 'sidebar Today: shortcut in the tooltip: ' + d.querySelector('#side .srow[data-go="today"]').title);
  w.eval(`openDetail(${a})`); await sleep(300);
  check(/\(D\)/.test(d.querySelector('#detail .dchip').title) && /\(X\)/.test(d.querySelector('#detail .dtop .chk').title) && /Shift\+T/.test(d.querySelector('#detail [data-act="due-q"][data-d="1"]').title), 'task panel: date (D), complete (X), tomorrow (Shift+T)');
  check(!d.querySelector('#detail .atthint') && /drop files here/.test(d.querySelector('#detail .attadd')?.title || ''), 'attachments: the drop hint is the tooltip');
  w.eval('closeDetail()');
  check(w.eval(`hintOnce('x', 'y')`) === '', 'mouse: no one-time hint lines');
  const mm0 = w.matchMedia; w.matchMedia = q => ({matches: /hover: none/.test(q), addEventListener() {}, addListener() {}});
  check(/data-hint="x"/.test(w.eval(`hintOnce('x', 'y')`)), 'touch: the hint shows once');
  w.eval(`hintDone('x')`);
  check(w.eval(`hintOnce('x', 'y')`) === '', 'dismissed: gone for good on this device');
  w.eval(`settingsModal('look')`); await sleep(200);
  click(w, d.querySelector('.smodal [data-m="hints-reset"]')); await sleep(100);
  check(/data-hint="x"/.test(w.eval(`hintOnce('x', 'y')`)), 'Settings > Appearance: "Show tips again" brings them back');
  d.querySelector('.smodal').remove();
  w.matchMedia = mm0;

  // ================= (o) matrix scope
  w.eval(`LS.del('mx'); go('matrix')`); await sleep(300);
  check(!!d.querySelector('.mxbar [data-act="mx-scope"]') && /All lists/.test(d.querySelector('.mxbar').textContent), 'matrix: scope button "All lists"');
  check(w.eval(`mxTasks().some(t => t.list_id === ${CKL}) || mxTasks().some(t => t.title === 'Alpha')`), 'all lists by default');
  w.eval(`mxSet({scope: 'folder:Jobs'})`); await sleep(200);
  check(w.eval(`mxTasks().every(t => folderLists('Jobs').some(l => l.id === t.list_id))`) && /Matrix · Folder Jobs/.test(d.querySelector('#top h1').textContent), 'folder scope + title: ' + d.querySelector('#top h1').textContent);
  check(w.eval('mxList()') === w.eval(`folderLists('Jobs')[0].id`), 'quick add in the scoped matrix goes to the folder\'s first list');
  w.eval(`mxSet({scope: 'f:${FID}', due: 'today'})`); await sleep(200);
  check(w.eval(`mxTasks().every(t => t.list_id === ${WORK} && t.due && t.due <= today())`), 'filter scope (same engine) + due by today');
  check(!!d.querySelector('.mxbar [data-act="mx-reset"]'), 'reset × shown');
  click(w, d.querySelector('.mxbar [data-act="mx-reset"]')); await sleep(100);
  check(!w.eval(`mxActive(mxGet())`) && d.querySelector('#top h1').textContent.startsWith('Eisenhower'), 'reset: everything again');
  w.eval(`go('l/${SIDE}')`); await sleep(300);
  click(w, d.querySelector('#top [data-act="top-more"]')); await sleep(80);
  const smx = [...d.querySelectorAll('#pop .menu-list button')].find(x => /Show as matrix/.test(x.textContent));
  check(!!smx, 'list "…": Show as matrix');
  click(w, smx); await sleep(300);
  check(w.eval('S.route.mod') === 'matrix' && w.eval('mxGet().scope') === 'l:' + SIDE, 'opens the matrix with that list');
  w.eval(`LS.del('mx')`);

  // ================= (p) the docked composer
  w.eval(`go('l/${SIDE}')`); await sleep(300);
  const dock = d.querySelector('#view .lwrap > .qdock .qadd.dock');
  check(!!dock && dock.querySelector('#qinput')?.placeholder === 'Add task…' && /Dentist/.test(dock.querySelector('#qinput').title) && !!dock.querySelector('.qplus') && !!dock.querySelector('.qkey kbd'), 'composer at the bottom: +, short placeholder, example as tooltip, key badge');
  check(!d.querySelector('#view .qadd.inline'), 'no old input on top');
  const qi = d.querySelector('#qinput'); qi.focus(); qi.value = 'Draft email tomorrow !high'; qi.dispatchEvent(new w.Event('input', {bubbles: true})); w.eval(`updateChips(document.querySelector('#qinput'))`);
  const qc = () => [...d.querySelectorAll('#qdchips .qdc')].map(x => x.textContent.trim());
  check(qc().length === 3 && qc()[0] === 'Tomorrow' && /Side gig/.test(qc()[1]) && qc()[2] === 'High', 'chips: date, list, priority from the text + view: ' + qc().join(' | '));
  click(w, d.querySelector('#qdchips [data-act="qd-prio"]')); await sleep(60);
  click(w, [...d.querySelectorAll('#pop .menu-list button')].find(x => x.textContent.trim() === 'Low')); await sleep(60);
  check(qc()[2] === 'Low', 'priority chip changes it');
  key(w, d.querySelector('#qinput'), 'Enter'); await sleep(600);
  const nt = (await st()).tasks.find(t => t.title === 'Draft email');
  check(nt && nt.priority === 1 && nt.due === T1 && nt.list_id === SIDE, 'Enter adds with the chips (chip wins over the text)');
  check(d.activeElement === d.querySelector('#qinput') && d.querySelector('#qinput').value === '', 'focus stays for the next task');
  w.eval(`go('matrix')`); await sleep(200);
  check(!d.querySelector('.qdock'), 'not in the matrix');

  // ================= (q) undated tasks in the timeline, (r) bigger bars
  const PJ = (await call('POST', '/api/lists', {name: 'Launch', kind: 'project'})).id;
  const dt1 = await mk('Plan', PJ, {due: T0}), nd1 = await mk('Someday', PJ), nd2 = await mk('Sub someday', PJ, {parent_id: nd1});
  await call('PATCH', `/api/lists/${PJ}`, {view: 'timeline'}); await w.eval('load()'); w.eval(`LS.del('tlnd'); go('l/${PJ}')`); await sleep(500);
  check(w.eval(`tlNdOn(${PJ})`) && !!d.querySelector('.tl-ndhead') && /No date\s*2/.test(d.querySelector('.tl-ndhead').textContent), 'project list: "No date (2)" group on by default');
  const ndr = [...d.querySelectorAll('.tl-nd .tl-name')].map(x => x.textContent.trim());
  check(ndr[0] === 'Someday' && /Sub someday/.test(ndr[1]), 'subtask under its parent: ' + ndr.join(' | '));
  await w.eval(`tlDraw(${nd1}, '${addD(T0, 2)}', '${addD(T0, 4)}')`);
  check(await until(async () => (await task(nd1)).due === addD(T0, 4) && (await task(nd1)).start === addD(T0, 2)), 'drawing across days sets start + due');
  check(await until(() => !!d.querySelector(`.tl-bar[data-id="${nd1}"]`)), 'then it is a normal bar');
  await w.eval(`histStep('undo')`);
  check(await until(async () => !(await task(nd1)).due), 'one undo takes it back');
  await w.eval(`tlDraw(${nd2}, '${T1}', '${T1}')`);
  check(await until(async () => (await task(nd2)).due === T1 && !(await task(nd2)).start), 'a click = that day');
  await w.eval(`tlUndate(${nd2})`);
  check(await until(async () => !(await task(nd2)).due), '"Remove date" (bar menu) clears it');
  w.eval(`tlBarMenu(document.querySelector('.tl-bar[data-id="${dt1}"]'))`); await sleep(60);
  check([...d.querySelectorAll('#pop .menu-list button')].some(x => /Remove date/.test(x.textContent)), 'bar menu offers "Remove date"');
  w.eval('closePop()');
  click(w, d.querySelector('[data-act="tl-nd"]')); await sleep(200);
  check(!d.querySelector('.tl-ndhead') && w.eval(`LS.get('tlnd')`)['l' + PJ] === false, 'header switch "No date" (remembered per device)');
  check(!w.eval(`tlNdOn(null)`), 'off by default outside project lists');
  const css3 = await (await fetch(B + 'static/app.css')).text();
  check(/\.tl-row\{display:flex;height:2\.75rem/.test(css3) && /\.tl-bar\{position:absolute;top:\.3125rem;height:2\.125rem/.test(css3) && /\.tl-bar \.h\.l\{left:-\.375rem\}/.test(css3), '(r) taller rows / bars, handles past the ends');
  check(w.eval('TL_MINW') >= 18, '(r) minimum bar width');

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  w.close();
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
