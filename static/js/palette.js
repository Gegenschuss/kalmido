/* Kalmido web client: Keyboard shortcuts, the command palette, the welcome tour.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ------------------------------------------------------------------ v1.1: keyboard, command palette, shortcuts, tour, celebration
// ---- keyboard: shortcut hints (<kbd>, Geist Mono), list navigation (j / k / Enter / x / s), "g" sequences
const keyName = k => k === 'Mod' ? (IS_MAC ? '⌘' : 'Ctrl') : k === 'Shift' ? (IS_MAC ? '⇧' : 'Shift') : k === 'Alt' ? (IS_MAC ? '⌥' : 'Alt') : k.length === 1 ? k.toUpperCase() : k;
// 'Mod+K' -> ⌘ K keys; 'g t' -> G, T (a sequence)
const kb = s => `<span class="kbs">${s.split(' ').map(ch => ch.split('+').map(k => `<kbd>${esc(keyName(k))}</kbd>`).join('')).join('')}</span>`;
const kbText = s => s.split(' ').map(ch => ch.split('+').map(keyName).join(IS_MAC ? '' : '+')).join(' ');
const SHORTCUTS_ALL = [
  [N_('General'), [['Mod+K', N_('Search and commands')], ['?', N_('Keyboard shortcuts')], ['n', N_('New task')], ['q', N_('Quick capture to the inbox')], ['Ctrl+Space', N_('Quick capture, also while typing')], ['/', N_('Search')], ['Mod+Z', N_('Undo')], ['Mod+Shift+Z', N_('Redo')], ['Esc', N_('Close')]]],
  [N_('Tasks'), [['↓', N_('Next task (or J)')], ['↑', N_('Previous task (or K)')], ['Enter', N_('Open task')], ['Space', N_('Complete task (or X)')], ['e', N_('Edit title in the list (or double-click)')], ['s', N_('Snooze task')], ['d', N_('Change date')], ['t', N_('Due today')], ['Shift+T', N_('Due tomorrow')], ['m', N_('Move to list')], ['Shift+C', N_('Collapse or expand all')]]],
  // 2.0.6 (#191): multi-select and the calendar views
  [N_('Multi-select'), [['Mod+A', N_('Select all tasks of the view')], ['Shift+↓', N_('Extend the selection down (or Shift+J)')], ['Shift+↑', N_('Extend the selection up (or Shift+K)')], ['Shift+X', N_('Select or unselect the task')],
    ['Space', N_('Complete the selected tasks (or X)')], ['m', N_('Move the selected tasks to a list')], ['d', N_('Change the date of the selected tasks')], ['Esc', N_('Clear the selection')]]],
  [N_('Calendar'), [['1', N_('Month')], ['2', N_('Week')], ['3', N_('Day')], ['4', N_('Timeline')], ['←', N_('Previous period')], ['→', N_('Next period')], ['.', N_('Jump to today')]]],
  [N_('Timeline'), [['Tab', N_('Focus a bar')], ['c', N_('Connect to the task it blocks')], ['Shift+F10', N_('Bar menu')], ['d', N_('Pick a date…')], ['Esc', N_('Cancel connecting')]]],
  [N_('Go to'), [['g t', N_('Today')], ['g m', N_('Tomorrow')], ['g w', N_('Next 7 days')], ['g d', N_('Now doable')], ['g i', N_('Inbox')], ['g a', N_('All')], ['g c', N_('Calendar')], ['g h', N_('Habits')], ['g f', N_('Focus timer')], ['g s', N_('Settings')]]],
];
// only what the switched-on modules offer (the Timeline group needs the timeline with dependencies)
const SC_MOD = {'g c': 'cal', 'g h': 'habits', 'g f': 'pomo'};
const SHORTCUTS = () => SHORTCUTS_ALL.filter(([g]) => (g !== 'Timeline' || (feat('timeline') && depsOn())) && (g !== 'Calendar' || feat('cal')))
  .map(([g, rows]) => [g, rows.filter(([k]) => (!SC_MOD[k] || feat(SC_MOD[k])) && !(g === 'Calendar' && k === '4' && !feat('timeline')))]);
const CAL_KEYS = {1: 'month', 2: 'week', 3: 'day', 4: 'timeline'};
// multi-select from the keyboard: the task rows of the view, the focused one (j / k), the multi bar's own buttons
function kbSelect(ids) { for (const i of ids) S.multi.add(i); if (ids.length) S.multiLast = ids[ids.length - 1]; $$('#view .trow').forEach(r => r.classList.toggle('msel', S.multi.has(+r.dataset.id))); renderMultiBar(); }
const GO_KEYS = {t: () => go('today'), m: () => go('tomorrow'), w: () => go('week'), d: () => go('doable'), i: () => go('inbox'), c: () => feat('cal') && go('cal'), h: () => feat('habits') && go('habits'), f: () => feat('pomo') && go('pomo'), s: () => settingsModal(), a: () => go('all')};
S.kf = null;  // keyboard-focused task row (j / k)
const rowIds = () => $$('#view .trow').map(r => +r.dataset.id).filter(Boolean);
function kfocus(id) {
  S.kf = id;
  $$('#view .trow.kfocus').forEach(r => r.classList.remove('kfocus'));
  const r = id && $(`#view .trow[data-id="${id}"]`);
  if (r) { r.classList.add('kfocus'); r.scrollIntoView({block: 'nearest'}); }
  // 2.16.0 (#473): the keyboard focus is the real focus (screen readers follow it): the row's title gets it while the
  // focus is in the list or nowhere
  const tt = r && $('.ttl[data-kt]', r), a = document.activeElement;
  if (tt && (!a || a === document.body || a === $('#view') || a.matches?.('.ttl[data-kt],.trow .chk'))) { rowRove(tt); try { tt.focus({preventScroll: true}); } catch { tt.focus(); } }
}
// 2.16.0 (#473): one task row per view is a Tab stop (its checkbox and title), ↑ ↓ / j k move it (roving tabindex);
// before, every row's checkbox was a stop and the title none (a task could not be opened with Tab + Enter)
function rowRove(cur) {
  const ts = $$('#view .trow[data-id] > .tmain > .ttl[data-kt]'); if (!ts.length) return;
  const a = document.activeElement, rowId = x => x.closest('.trow')?.dataset.id;
  cur = cur || ts.find(x => x === a || x.closest('.trow')?.contains(a)) || (S.kf && ts.find(x => rowId(x) === String(S.kf))) || ts.find(x => x.closest('.trow').classList.contains('sel')) || ts[0];
  for (const x of ts) {
    const v = x === cur ? 0 : -1, row = x.closest('.trow');
    if (x.tabIndex !== v) x.tabIndex = v;
    // the row's checkbox and its other controls (assign, link, …) are stops only in the current row (2.16.2: the
    // assignee column added one stop per row)
    for (const c of row.querySelectorAll('button, a[href], input, select')) if (c.tabIndex !== v) c.tabIndex = v;
  }
}
document.addEventListener('focusin', e => {
  const tt = e.target.closest?.('#view .trow[data-id] .ttl[data-kt], #view .trow[data-id] > .chk'); if (!tt) return;
  const row = tt.closest('.trow'), id = +row.dataset.id;
  let kb = true; try { kb = e.target.matches(':focus-visible'); } catch { /* old engine */ }
  rowRove(row.querySelector('.ttl[data-kt]'));
  if (kb && S.kf !== id) { S.kf = id; $$('#view .trow.kfocus').forEach(r => r.classList.remove('kfocus')); row.classList.add('kfocus'); }
});
// 2.16.0 (#473, WCAG 2.5.7): move a task one place up / down in its list (section, parent) without dragging: task menu
// "Move up / down", Alt+↑ / ↓. In a view sorted by priority it moves among the tasks of the same priority; other sort
// orders switch to "Priority" first (as a drop does)
async function taskNudge(id, d) {
  const t = taskById(id); if (!t || !(t.id > 0)) return;
  if (!canEdit(t)) { roToast(); return; }
  if (S.route.mod === 'tasks' && !['prio'].includes(sortMode())) LS.set('sort2.' + S.route.key, 'prio');
  const sib = siblings(t).filter(x => x.priority === t.priority && (x.section_id || null) === (t.section_id || null));
  const i = sib.findIndex(x => x.id === id), o = sib[i + d];
  if (i < 0 || !o) {  // sorted by priority, a task moves among the tasks of its priority only: say so
    const other = siblings(t).filter(x => (x.section_id || null) === (t.section_id || null) && x.priority !== t.priority).length;
    toast(other && S.route.mod === 'tasks' ? (d < 0 ? tr('Already the first task with this priority') : tr('Already the last task with this priority')) : d < 0 ? tr('Already at the top') : tr('Already at the bottom')); return;
  }
  const n2 = sib[i + 2 * d];
  const sort = n2 ? (o.sort + n2.sort) / 2 : o.sort + d;
  t.sort = sort; render();
  try { await api('POST', '/api/tasks/reorder', {items: [{id, sort}]}); } catch { await load().catch(() => {}); render(); return; }
  await load(); render(); kfocus(id);
  announce(d < 0 ? tr('Moved up') : tr('Moved down'));
}
const curTask = () => { const id = S.sel || (S.kf && $(`#view .trow[data-id="${S.kf}"]`) ? S.kf : null); return id ? taskById(id) : null; };
const typing = t => t && (/INPUT|TEXTAREA|SELECT/.test(t.tagName) || t.isContentEditable);
let gPending = 0;
window.addEventListener('keydown', e => {
  if (e.defaultPrevented || e.isComposing) return;
  const k = e.key;
  // 2.0.6 (#191): Ctrl/Cmd+A selects every task row of the view (outside text fields and dialogs)
  if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && k.toLowerCase() === 'a' && !typing(e.target) && !$('.modal') && !$('.palette') && $('#view .trow')) {
    e.preventDefault(); e.stopPropagation();
    S.multiMode = true; kbSelect($$('#view .trow').map(r => +r.dataset.id).filter(Boolean)); render(); return;
  }
  if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && k.toLowerCase() === 'k') {  // anywhere, also while typing
    if ($('.authscreen')) return;
    e.preventDefault(); e.stopPropagation();
    $('.palette') ? closePalette() : openPalette();
    return;
  }
  if (TOUR.on) {  // the tour owns the keyboard while it is open
    if (k === 'Escape') { e.preventDefault(); e.stopPropagation(); tourEnd(true); }
    else if (k === 'ArrowRight' || k === 'Enter') { e.preventDefault(); e.stopPropagation(); tourGo(TOUR.i + 1); }
    else if (k === 'ArrowLeft') { e.preventDefault(); e.stopPropagation(); tourGo(TOUR.i - 1); }
    return;
  }
  if ($('.palette')) return;  // its input handles the keys
  // 2.16.0 (#473, WCAG 2.5.7): Alt+↑ / Alt+↓ moves the focused task up / down (the same as dragging it)
  if (e.altKey && !e.ctrlKey && !e.metaKey && !e.shiftKey && (k === 'ArrowUp' || k === 'ArrowDown') && S.kf && !typing(e.target) && !$('.modal') && $('#pop').classList.contains('hidden') && $(`#view .trow[data-id="${S.kf}"]`)) {
    e.preventDefault(); e.stopPropagation(); taskNudge(S.kf, k === 'ArrowUp' ? -1 : 1); return;
  }
  if (typing(e.target) || e.ctrlKey || e.metaKey || e.altKey || $('.modal') || !$('#pop').classList.contains('hidden') || $('.qadd.sheet') || $('.lightbox') || $('.tsheet')) { gPending = 0; return; }
  if (k === '?') { e.preventDefault(); e.stopPropagation(); shortcutsModal(); return; }
  if (gPending && Date.now() - gPending < 1200) {
    gPending = 0;
    const f = GO_KEYS[k.toLowerCase()]; if (f) { e.preventDefault(); e.stopPropagation(); f(); }
    return;
  }
  if (k === 'g') { gPending = Date.now(); e.preventDefault(); return; }
  const inList = S.route.mod === 'tasks' || S.route.mod === 'cal' || S.route.mod === 'matrix';
  if (!inList) return;
  // 2.16.0 (#473): a focused row title is the keyboard row (also when the focus came without :focus-visible, e.g. a
  // screen reader moving it)
  if (e.target.matches?.('#view .ttl[data-kt]')) { const rid = +e.target.closest('.trow')?.dataset.id; if (rid && rid !== S.kf) { S.kf = rid; $$('#view .trow.kfocus').forEach(r => r.classList.remove('kfocus')); e.target.closest('.trow').classList.add('kfocus'); } }
  if (S.route.mod === 'cal' && !e.shiftKey) {  // 2.0.6 (#191): 1-4 = month / week / day / timeline, ← → = period, . = today
    const mode = CAL_KEYS[k], nav = {ArrowLeft: 'cal-prev', ArrowRight: 'cal-next', '.': 'cal-today'}[k];
    const b = mode ? $(`#view [data-act="cal-mode"][data-k="${mode}"]`) : nav ? $(`#view [data-act="${nav}"]`) : null;
    if (b) { e.preventDefault(); b.click(); return; }
  }
  if (S.multi.size && !e.shiftKey && (k === 'x' || k === ' ' || k === 'm' || k === 'd')) {  // bulk actions on the selection
    const b = $(`#mbar [data-act="${k === 'm' ? 'mb-list' : k === 'd' ? 'mb-date' : 'mb-done'}"]`);
    if (b) { e.preventDefault(); b.click(); }
    return;
  }
  if (e.shiftKey && (k === 'X' || k === 'J' || k === 'K' || k === 'ArrowDown' || k === 'ArrowUp')) {  // select / extend
    const ids = rowIds(); if (!ids.length) return;
    e.preventDefault();
    if (k === 'X') { if (!S.kf || !ids.includes(S.kf)) return; S.multi.has(S.kf) ? S.multi.delete(S.kf) : S.multi.add(S.kf); kbSelect([S.kf].filter(i => S.multi.has(i))); S.multiLast = S.kf; return; }
    const i = ids.indexOf(S.kf), d = k === 'J' || k === 'ArrowDown' ? 1 : -1;
    if (i < 0) { kfocus(ids[d > 0 ? 0 : ids.length - 1]); kbSelect([S.kf]); return; }
    const j = Math.max(0, Math.min(ids.length - 1, i + d));
    kbSelect([ids[i], ids[j]]); kfocus(ids[j]);
    return;
  }
  if (k === 'C' && e.shiftKey && S.route.mod === 'tasks') { if (collapseKeys().length) { e.preventDefault(); collapseAll(collapseAnyOpen()); } return; }
  if (k === 'j' || k === 'k' || k === 'ArrowDown' || k === 'ArrowUp') {
    const ids = rowIds(); if (!ids.length) return;
    e.preventDefault();
    const i = ids.indexOf(S.kf), d = k === 'j' || k === 'ArrowDown' ? 1 : -1;
    kfocus(ids[i < 0 ? (d > 0 ? 0 : ids.length - 1) : Math.max(0, Math.min(ids.length - 1, i + d))]);
    if (S.sel && !isMobile()) openDetail(S.kf);
    return;
  }
  if ((k === 't' || k === 'T') && !e.target.closest?.('button,a,label')) {  // 1.5.1: due today / tomorrow (selection, focused or open task)
    const ct = curTask();
    if (S.multi.size) { e.preventDefault(); batch('patch', {due: addDays(today(), k === 'T' ? 1 : 0)}); return; }
    if (ct) { e.preventDefault(); quickDue(ct.id, k === 'T' ? 1 : 0); }
    return;
  }
  const t = S.kf && $(`#view .trow[data-id="${S.kf}"]`) ? taskById(S.kf) : null;
  if (!t || (e.target !== document.body && !e.target.matches?.('.ttl[data-kt]') && e.target.closest?.('button,a,[tabindex],label'))) return;
  const row = $(`#view .trow[data-id="${t.id}"]`);
  if (k === 'Enter' || k === 'o') { e.preventDefault(); S.kbOpen = true; openDetail(t.id); }
  else if (k === 'x' || k === ' ') { e.preventDefault(); toggleTask(t.id); }
  else if (k === 'e' || k === 'F2') { e.preventDefault(); inlineEditStart(t.id); }
  else if (k === 's') { e.preventDefault(); snoozeSheet(t.id, row); }
  else if (k === 'd') { e.preventDefault(); datePop(row, t.id); }
  else if (k === 'm') { e.preventDefault(); openPalette('move'); }
}, true);
document.addEventListener('mousedown', e => { if (S.kf && e.target.closest('#view .trow')) kfocus(null); });

// ---- command palette (Ctrl/Cmd+K): fuzzy search over actions, views, lists, filters, tags, settings and tasks
const PAL = {q: '', i: 0, mode: null, items: []};
const fold = s => String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
// subsequence match with bonuses for word starts and runs; 0 = no match
function fuzzy(q, s) {
  if (!q) return 1;
  const a = fold(s), b = fold(q);
  const at = a.indexOf(b);
  if (at >= 0) return 1000 - at * 2 - a.length * 0.1 + (at === 0 || /[\s\-_/#~.(]/.test(a[at - 1]) ? 200 : 0);
  let score = 0, j = 0, run = 0, last = -2, good = 0;
  for (let i = 0; i < a.length && j < b.length; i++) {
    if (a[i] !== b[j]) continue;
    run = i === last + 1 ? run + 1 : 0;
    const ws = i === 0 || /[\s\-_/#~.(]/.test(a[i - 1]);
    if (ws || run) good++;
    score += 10 + run * 8 + (ws ? 25 : 0);
    last = i; j++;
  }
  // scattered letters are noise: at least half of the query must hit word starts or continue a run
  return j === b.length && good >= Math.ceil(b.replace(/\s/g, '').length / 2) ? score - a.length * 0.1 : 0;
}
function palAll() {
  const it = [], t = curTask(), ct = t && canEdit(t) && t.id > 0;
  const add = (id, kind, label, icon, fn, extra = {}) => it.push({id, kind, label, icon, fn, ...extra});
  // actions
  add('a:new', 'action', tr('New task'), 'plus', () => { const q = currentQuickInput(); if (q && (!isMobile() || tabletDock())) q.focus(); else openQuickSheet(); }, {keys: 'n'});
  add('a:capture', 'action', tr('Capture to the inbox'), 'zap', () => quickCapture(), {keys: 'q', sub: tr('Lands in the inbox, wherever you are')});  // 2.4.0 (#187); 2.25.0 (UX-32): one name that says where it goes
  add('a:newlist', 'action', tr('New list'), 'list', () => listModal());
  add('a:newproject', 'action', tr('New project…'), 'brief', () => listModal(null, '', {kind: 'project'}));  // 2.4.0 (#243)
  add('a:newfilter', 'action', tr('New filter'), 'filter', () => filterModal());
  add('a:dayplan', 'action', tr('Plan my day'), 'cal', () => dayplanModal('day'));  // 2.10.0 (#440)
  add('a:dayfill', 'action', tr('Fill free time'), 'clock', () => dayplanModal('fill'));
  if (feat('habits')) add('a:newhabit', 'action', tr('New habit'), 'habit', () => { go('habits'); habitModal(); });
  if (famOn()) {  // 2.19.0 (#653)
    add('a:occ', 'action', tr('New birthday or anniversary'), 'cake', () => occModal());
    add('a:dl', 'action', tr('New household deadline'), 'hourglass', () => dlModal());
    for (const [k, n] of PACK_UI) add('a:pack:' + k, 'action', tr('New packing list: {0}', tr(n)), 'bag', () => famPack(k));
    for (const l of S.lists.filter(x => x.family === 'shopping' && !x.archived)) add('a:shop:' + l.id, 'action', tr('Shopping mode: {0}', lname(l)), 'cart', () => shopModeOpen(l.id));
  }
  // 2.22.0 (#663): Home & life
  if (feat('contracts')) add('a:contract', 'action', tr('New contract'), 'file', () => contractModal());
  if (feat('home')) { add('a:device', 'action', tr('New device'), 'tool', () => deviceModal()); add('a:upkeep', 'action', tr('New upkeep task'), 'repeat', () => upkeepModal()); }
  if (feat('health')) add('a:health', 'action', tr('New health entry'), 'heart', () => healthModal());
  if (feat('travel')) add('a:trip', 'action', tr('New trip'), 'plane', () => tripModal());
  if (propOn()) {  // 2.3.0 (#260 #262 #263): ask an agent for a proposal
    add('a:propproject', 'action', tr('New project from briefing…'), 'bot', () => propRequest('project'));
    add('a:propinbox', 'action', propWith(N_('Sort the inbox with {0}…'), N_('Sort the inbox with an agent…')), 'bot', () => propRequest('triage', {}));
    const rl = routeList();
    if (rl && !rl.is_inbox && canEditList(rl.id)) add('a:propnotes', 'action', tr('Tasks from notes…'), 'bot', () => propRequest('extract', {lid: rl.id}));
  }
  if (ct) {
    const n = `“${t.title.length > 40 ? t.title.slice(0, 39) + '…' : t.title}”`;
    if (t.status === 0) add('a:done', 'task', tr('Complete {0}', n), 'check', () => toggleTask(t.id), {keys: 'x'});
    else add('a:reopen', 'task', tr('Reopen {0}', n), 'undo', () => toggleTask(t.id));
    add('a:snooze', 'task', tr('Snooze {0}', n), 'clock', () => snoozeSheet(t.id, $(`#view .trow[data-id="${t.id}"]`) || $('#top h1')), {keys: 's'});
    add('a:date', 'task', tr('Change date of {0}', n), 'cal', () => datePop($(`#view .trow[data-id="${t.id}"]`) || $('#top h1'), t.id), {keys: 'd'});
    add('a:today', 'task', tr('Move {0} to today', n), 'sun', () => patchUndoable(t.id, {due: today()}, tr('Date: {0}', dayLabel(today()))));
    add('a:tomorrow', 'task', tr('Move {0} to tomorrow', n), 'sunrise', () => patchUndoable(t.id, {due: addDays(today(), 1)}, tr('Date: {0}', dayLabel(addDays(today(), 1)))));
    add('a:move', 'task', tr('Move {0} to another list…', n), 'folder', () => openPalette('move'), {keep: true, keys: 'm'});
    if (t.status === 0) add('a:wait', 'task', t.waiting_at ? tr('{0}: no longer waiting', n) : tr('{0}: waiting on someone…', n), 'hourglass', () => t.waiting_at ? waitClear(t.id) : waitDialog(t.id));  // 2.22.0 (#686)
    for (const [p, nm] of [[5, N_('High')], [3, N_('Medium')], [1, N_('Low')], [0, N_('None')]]) add('a:prio' + p, 'task', tr('Priority of {0}: {1}', n, tr(nm)), 'flag', () => patchTask(t.id, {priority: p}), {cls: p ? 'pf' + p : '', qonly: true});
    if (feat('pomo') && t.status === 0) add('a:focus', 'task', tr('Start focus on {0}', n), 'timer', () => { pomoStart(t.id); go('pomo'); });
    if (propBreakOk(t)) add('a:propbreak', 'task', tr('Break down {0} with an agent…', n), 'bot', () => propRequest('subtasks', {tid: t.id}));  // 2.3.0 (#261)
    if (tFor(t)) add('a:ttimer', 'task', S.timer && S.timer.task_id === t.id ? tr('Stop timer') : tr('Start timer on {0}', n), 'clock', () => S.timer && S.timer.task_id === t.id ? timerStop() : timerStart({task_id: t.id}));
  }
  if (timeOn() && S.timer) add('a:stoptimer', 'action', tr('Stop timer'), 'stop', timerStop);
  if (timeOn()) add('a:addtime', 'action', tr('Add time…'), 'plus', () => entryModal(null, {}));
  const light = document.documentElement.dataset.theme === 'light' || (document.documentElement.dataset.theme === 'auto' && matchMedia('(prefers-color-scheme: light)').matches);
  add('a:theme', 'action', light ? tr('Switch to dark theme') : tr('Switch to light theme'), 'eye', () => { LS.set('theme', light ? 'dark' : 'light'); applyTheme(); });
  const dens = document.documentElement.dataset.density;
  add('a:density', 'action', dens === 'compact' ? tr('Density: comfortable') : tr('Density: compact'), 'sliders', () => { LS.set('density', dens === 'compact' ? 'comfortable' : 'compact'); applyDensity(); });
  // appearance (per device): only listed when searching, e.g. "font", "accent", "size", "theme"
  for (const [k, n] of THEMES) add('a:theme-' + k, 'action', tr('Color scheme: {0}', tr(n)), 'eye', () => lookSet('theme', k), {qonly: true});
  if (fsPct() < FS_MAX) add('a:fsize-up', 'action', tr('Font size: larger'), 'plus', () => fsStep(5), {qonly: true, keys: 'Mod+='});
  if (fsPct() > FS_MIN) add('a:fsize-down', 'action', tr('Font size: smaller'), 'sliders', () => fsStep(-5), {qonly: true, keys: 'Mod+-'});
  for (const v of FSIZE_ORDER) { const [, n, z] = LOOK.fsize.find(x => x[0] === v); add('a:fsize-' + v, 'action', tr('Font size: {0}', `${tr(n)} (${zPct(z)})`), 'sliders', () => lookSet('fsize', v), {qonly: true}); }
  for (const [v, n] of LOOK.font) add('a:font-' + v, 'action', tr('Font: {0}', tr(n)), 'edit', () => lookSet('font', v), {qonly: true});
  for (const [v, n, d, l] of LOOK.accent) add('a:accent-' + v, 'action', tr('Accent color: {0}', tr(n)), 'palette', () => lookSet('accent', v), {qonly: true, sw: light ? l : d});
  add('a:look-reset', 'action', tr('Reset appearance to the defaults'), 'undo', () => { for (const k of LOOK_KEYS) LS.del(k); applyTheme(); applyDensity(); applyLook(); render(); }, {qonly: true});
  add('a:keys', 'action', tr('Keyboard shortcuts'), 'help', shortcutsModal, {keys: '?'});
  add('a:tour', 'action', tr('Restart the welcome tour'), 'arrow', () => tourStart());
  if (S.sample) add('a:sample-rm', 'action', tr('Remove sample project'), 'trash', () => sampleRemove());
  else add('a:sample', 'action', tr('Create sample project'), 'plus', () => sampleCreate());
  add('a:website', 'action', tr('Open website'), 'link', () => openExt(ABOUT_LINKS[0][0]));
  add('a:issue', 'action', tr('Report a problem'), 'alert', () => openExt(ABOUT_LINKS[2][0]));
  if (doneToggleView()) add('a:showdone', 'action', `${showDone() ? tr('Hide completed') : tr('Show completed')}: ${titleFor(S.route.key)}`, 'eye', () => setShowDone(!showDone()));
  else if (S.route.mod === 'cal' && S.calMode !== 'timeline') add('a:showdone', 'action', `${showDoneCal() ? tr('Hide completed') : tr('Show completed')}: ${tr('Calendar')}`, 'eye', () => setShowDone(!showDoneCal(), 'cal'));
  // views
  // 2.25.0 (UX-15): Pinned and Waiting on someone only while they hold something, like in the sidebar
  const cn = counts();
  for (const k of ['inbox', 'today', 'tomorrow', 'week', 'doable', 'pinned', 'waiting', 'all', 'done', 'trash', 'search']) {
    if ((k === 'pinned' && !cn.pinned) || (k === 'waiting' && !cn.waiting)) continue;
    add('v:' + k, 'view', tr(SMART[k].name), SMART[k].icon, () => go(k), {keys: {today: 'g t', tomorrow: 'g m', week: 'g w', doable: 'g d', inbox: 'g i', all: 'g a'}[k]});
  }
  if (collab()) add('v:assigned', 'view', tr('Assigned to me'), 'user', () => go('assigned'));
  // 2.25.0 (UX-47): "Message to …" for everyone one can write to (when typing)
  if (teamOn()) for (const p of teamPeople()) add('dm:' + p.id, 'action', tr('Message to {0}', p.name), 'comment', () => dmOpen(p.id, p.name), {qonly: true});
  add('v:home', 'view', tr('Start|home'), 'home', () => go('home'));  // 2.17.0 (#475)
  if (teamOn()) add('v:team', 'view', tr('Team chat'), 'comment', () => go('team'));  // 2.17.0 (#419)
  for (const n of S.notes || []) add('n:' + n.id, 'note', n.title, 'edit', () => go('note/' + n.id), {sub: lname(listById(n.list_id)) || ''});  // 2.17.0 (#442)
  for (const [m, icon, name] of [['cal', 'cal', N_('Calendar')], ['matrix', 'grid', N_('Eisenhower matrix')], ['habits', 'habit', N_('Habits')], ['pomo', 'timer', N_('Focus timer')], ['news', 'bell', N_('News')], ['stats', 'chart', N_('Statistics')], ['time', 'clock', N_('Time tracking')], ['overview', 'pulse', N_('Project status')], ['family', 'family', N_('Family')], ['contacts', 'users', N_('Contacts')], ['life', 'home', N_('Home & life')], ['review', 'journal', N_('Review & journal')], ['clients', 'brief', N_('Clients')], ['workload', 'chart', N_('Workload')]])
    if (modOn(m)) add('v:' + m, 'view', tr(name), icon, () => go(m), {keys: m === 'cal' ? 'g c' : ''});
  // 2.8.0 (#434): the command bar also opens the timeline, the agents and their chats ("ask an agent")
  if (feat('timeline')) add('v:timeline', 'view', tr('Timeline'), 'timeline', () => { S.rmScrollReset = true; rmSet({v: 'timeline'}, 'none'); go('all'); });
  if (agentsTab()) {
    add('v:agents', 'view', tr('Agents'), 'bot', () => go('agents'));
    for (const a of (S.agents || []).filter(x => x.enabled)) add('a:chat-' + a.id, 'action', tr('Chat with {0}', a.name), 'comment', () => chatOpen(a.id));
  }
  // lists, filters, tags
  for (const l of S.lists.filter(x => !x.archived && !x.is_inbox)) add('l:' + l.id, 'list', lname(l), 'list', () => go('l/' + l.id), {sw: cssColor(l.color), img: l.icon || '', ...(l.folder ? {sub: fDisp(l.folder)} : {})});
  for (const f of folderNames()) add('folder:' + f, 'folder', fDisp(f), 'folder', () => go('folder/' + encodeURIComponent(f)));  // 2.4.0 (#361)
  for (const f of S.filters) add('f:' + f.id, 'filter', f.name, 'filter', () => go('f/' + f.id));
  for (const g of Object.keys(counts().tags).sort()) add('tag:' + g, 'tag', '#' + g, 'tag', () => go('tag/' + encodeURIComponent(g)));
  // settings tabs
  for (const [k, icon, n] of SET_SECS) {
    if (k === 'account' && !S.me) continue;
    if (k === 'users' && !S.me?.is_admin) continue;
    if (k === 'ai' && !aiPaneOn()) continue;  // 2.7.0 (#405 S2/S8: was a dead branch for a "time" tab)
    add('s:' + k, 'setting', tr('Settings: {0}', tr(n)), icon, () => settingsModal(k), {keys: k === 'general' ? 'g s' : ''});
  }
  // tasks (open ones + the recently completed that are in the state)
  for (const x of S.tasks.values()) if (x.status === 0 && x.id > 0 && !archivedTask(x)) add('t:' + x.id, 'tasks', x.title, 'check', () => { const r = $(`#view .trow[data-id="${x.id}"]`); if (!r && x.list_id) go(x.list_id === inbox()?.id ? 'inbox' : 'l/' + x.list_id); setTimeout(() => openDetail(x.id), 30); },
    {sub: [lname(listById(x.list_id)), x.due ? dayLabel(x.due) : ''].filter(Boolean).join('  ·  ')});
  return it;
}
const PAL_KIND = {note: N_('note|palette kind'), folder: N_('folder|palette kind'), action: N_('action'), task: N_('task|palette kind'), view: N_('view'), list: N_('list|palette kind'), filter: N_('filter'), tag: N_('tag'), setting: N_('setting'), tasks: N_('task|palette kind')};
function palItems() {
  const q = PAL.q.trim();
  if (PAL.mode === 'move') {
    const t = curTask(); if (!t) return [];
    return (canEditList(t.list_id) ? S.lists : []).filter(l => !l.archived && canEditList(l.id) && l.id !== t.list_id).map(l => ({id: 'mv:' + l.id, kind: 'list', label: lname(l), icon: l.is_inbox ? 'inbox' : 'list', sw: cssColor(l.color),
      fn: () => patchUndoable(t.id, {list_id: l.id, section_id: null}, tr('Moved to {0}', lname(l)))}))
      .map(x => ({...x, score: fuzzy(q, x.label)})).filter(x => x.score > 0).sort((a, b) => b.score - a.score);
  }
  const all = palAll();
  if (!q) {  // recently viewed tasks / lists, recent commands, then the actions for the current task, the rest of the actions + views
    const viewed = palViewed();
    const recent = LS.get('palRecent', []).map(id => all.find(x => x.id === id)).filter(x => x && x.kind !== 'task').slice(0, 5).map(x => ({...x, group: 'recent'}));
    const seen = new Set(recent.map(x => x.id)), order = {task: 0, action: 1, view: 2};
    return [...viewed, ...recent, ...all.filter(x => !seen.has(x.id) && !x.qonly && x.kind in order).sort((a, b) => order[a.kind] - order[b.kind]).map(x => ({...x, group: x.kind}))];
  }
  const boost = {action: 30, task: 40, view: 25, list: 20, note: 18, filter: 15, tag: 10, setting: 5, tasks: 0};
  // 2.13.0: "#447" or "447" jumps straight to that task (only one this person can see)
  const nm = q.match(/^#?(\d{1,9})$/), hit = nm && taskById(+nm[1]);
  const jump = hit ? [{id: 'tid:' + hit.id, kind: 'tasks', label: `#${hit.id} ${hit.title}`, sub: lname(listById(hit.list_id)) || '', icon: 'hash', fn: () => openDetail(hit.id)}] : [];
  const hits = jump.concat(all.map(x => ({...x, score: Math.max(fuzzy(q, x.label), x.sub ? fuzzy(q, x.sub) * 0.3 : 0)}))
    .filter(x => x.score > 0).map(x => ({...x, score: x.score + boost[x.kind]})).sort((a, b) => b.score - a.score).slice(0, 60));
  // 2.16.0 (#644): what the field can do with the text itself: ask an agent (the text goes to its chat) and create a task
  // (quick add syntax, the list like the quick add). Real matches first; without one, "Create" is on top (Enter = create)
  const r = parseQuick(q, new Set()), d = quickDefaults(), tl = listById(r.list_id || d.list_id) || inbox();
  const create = {id: 'new:', kind: 'action', cls: 'pdo', label: tr('Create as task: {0}', r.title || q), sub: [tl ? lname(tl) : '', r.due ? dayLabel(r.due) + (r.due_time ? ' ' + r.due_time : '') : ''].filter(Boolean).join(' · '), icon: 'plus', fn: () => palCreate(q)};
  const asks = (S.agents || []).filter(x => x.enabled && x.chat !== false).slice(0, 3).map(x => ({id: 'ask:' + x.id, kind: 'action', cls: 'pdo', label: tr('Ask {0}: {1}', x.name, q), sub: tr('Sends it to the chat'), icon: 'bot', img: x.avatar || null, fn: () => palAsk(x.id, q)}));
  return hits.length ? [...hits, ...asks, create] : [create, ...asks];
}
function palCreate(q) {
  const r = parseQuick(q, new Set()), d = quickDefaults();
  return createTask({title: r.title || q, list_id: r.list_id || d.list_id, due: r.due || d.due, due_time: r.due_time, priority: r.priority ?? 0, tags: [...(d.tags || []), ...(r.tags || [])], repeat: r.repeat || ''});
}
// 2.16.0 (#644): "Ask <agent>: …" from the command field: the text as a chat message, then the chat opens
async function palAsk(aid, text) {
  try { await api('POST', `/api/agents/${aid}/chat`, {body: text}); } catch { return; }
  chatOpen(aid);
}
const PAL_GROUP = {viewed: N_('Recently viewed'), recent: N_('Recent'), task: N_('Selected task'), action: N_('Actions'), view: N_('Go to')};
function palDraw() {
  const el = $('.palette'); if (!el) return;
  PAL.items = palItems();
  PAL.i = Math.max(0, Math.min(PAL.i, PAL.items.length - 1));
  let last = null, h = '';
  PAL.items.forEach((x, i) => {
    if (x.group && x.group !== last) { h += `<div class="pgroup">${tr(PAL_GROUP[x.group])}</div>`; last = x.group; }
    h += `<button class="pitem ${i === PAL.i ? 'on' : ''} ${x.cls || ''}" data-pi="${i}" role="option" aria-selected="${i === PAL.i}" id="pi-${i}">
      <span class="pic">${x.img ? `<img class="picon" src="${esc(x.img)}" alt="">` : x.sw !== undefined ? `<span class="psw" style="${x.sw ? 'background:' + x.sw : ''}"></span>` : ic(x.icon, 's')}</span>
      <span class="pl"><span class="plt">${esc(x.label)}</span>${x.sub ? `<span class="pls">${esc(x.sub)}</span>` : ''}</span>
      ${x.keys ? kb(x.keys) : ''}${x.kind === 'action' || x.kind === 'setting' || x.kind === 'view' ? '' : `<span class="pk">${esc(tr(PAL_KIND[x.kind] || x.kind))}</span>`}</button>`;
  });
  // 2.16.0 (#644): an empty field says what it can do (only what exists; no key hints on touch)
  const ags = (S.agents || []).filter(x => x.enabled);
  const hints = !PAL.q.trim() && !PAL.mode ? `<div class="phints" role="note">${[
    [ic('search', 's'), tr('Type to find tasks, lists, views, settings and actions')],
    [ic('hash', 's'), tr('#123 jumps to task 123')],
    [ic('plus', 's'), tr('Text + Enter creates a task: “Dentist tomorrow 3pm !high”')],
    ...(ags.length ? [[ic('bot', 's'), tr('Ask {0}: type the question, then pick “Ask {0}”', ags[0].name)]] : [])].map(([i, t]) => `<div class="phint">${i}<span>${esc(t)}</span></div>`).join('')}</div>` : '';
  const hw = $('.phintw', el); if (hw) hw.innerHTML = hints;  // outside the listbox (only options in there)
  $('.plist', el).innerHTML = h || (hints ? '' : `<div class="pempty">${tr('Nothing found. Enter adds it as a new task.')}</div>`);
  $('.pqin', el).setAttribute('aria-activedescendant', PAL.items.length ? 'pi-' + PAL.i : '');
  $('.plist .pitem.on', el)?.scrollIntoView({block: 'nearest'});
}
function openPalette(mode = null) {
  if (S.me?.kid) return;  // 2.19.0: no commands for a child account
  const ret = document.activeElement && document.activeElement !== document.body && !document.activeElement.closest?.('.palette') ? document.activeElement : PAL.ret;
  closePalette(); closePop(); PAL.ret = ret;
  PAL.q = ''; PAL.i = 0; PAL.mode = mode;
  const t = curTask();
  const md = document.createElement('div');
  md.className = 'modal palette';
  md.innerHTML = `<div class="card" role="dialog" aria-label="${tr('Search and commands')}">
    <div class="pqbar">${ic('search')}${mode === 'move' && t ? `<span class="pmode">${esc(tr('Move “{0}” to', t.title.slice(0, 30)))}</span>` : ''}<input class="pqin" role="combobox" aria-expanded="true" aria-controls="plist" autocomplete="off" spellcheck="false" placeholder="${mode === 'move' ? tr('List…') : tr('Search tasks, lists, views and actions…')}">${kb('Esc')}</div>
    <div class="phintw"></div><div class="plist" id="plist" role="listbox" aria-label="${esc(tr('Search and commands'))}"></div>
    <div class="pfoot">${kb('↑')}${kb('↓')}<span>${tr('select')}</span>${kb('Enter')}<span>${tr('run')}</span><span class="spacer"></span>${kb('?')}<span>${tr('all shortcuts')}</span></div></div>`;
  md.addEventListener('mousedown', e => { if (e.target === md) closePalette(); });
  document.body.appendChild(md);
  const inp = $('.pqin', md);
  inp.addEventListener('input', () => { PAL.q = inp.value; PAL.i = 0; palDraw(); });
  inp.addEventListener('keydown', e => {
    if (e.key === 'ArrowDown' || (e.key === 'n' && e.ctrlKey)) { e.preventDefault(); PAL.i = Math.min(PAL.items.length - 1, PAL.i + 1); palDraw(); }
    else if (e.key === 'ArrowUp' || (e.key === 'p' && e.ctrlKey)) { e.preventDefault(); PAL.i = Math.max(0, PAL.i - 1); palDraw(); }
    else if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); e.stopPropagation(); palRun(PAL.i); }
    else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); if (PAL.mode) openPalette(); else closePalette(); }
    else if (e.key === 'Backspace' && !inp.value && PAL.mode) { e.preventDefault(); openPalette(); }
  });
  $('.plist', md).addEventListener('click', e => { const b = e.target.closest('[data-pi]'); if (b) palRun(+b.dataset.pi); });
  $('.plist', md).addEventListener('mousemove', e => { const b = e.target.closest('[data-pi]'); if (b && +b.dataset.pi !== PAL.i) { PAL.i = +b.dataset.pi; $$('.pitem', md).forEach(x => x.classList.toggle('on', x === b)); } });
  palDraw();
  // 2.15.1 (#633): on touch screens focus at once, still inside the tap (iOS opens the keyboard only then)
  if (isTouch()) inp.focus();
  setTimeout(() => inp.focus(), 0);
}
function closePalette() {
  if (!$('.palette')) return;
  $('.palette').remove();
  // 2.16.2: the focus goes back to where it was (a row, a button), not to the page
  const r = PAL.ret; PAL.ret = null;
  if (r && r.isConnected && (!document.activeElement || document.activeElement === document.body)) { try { r.focus({preventScroll: true}); } catch { /* gone */ } }
}
function palRun(i) {
  const x = PAL.items[i];
  if (!x) {  // no match: the text becomes a new task (quick add syntax)
    const q = PAL.q.trim(); if (!q || PAL.mode) return;
    closePalette(); palCreate(q);
    return;
  }
  if (!x.id.startsWith('mv:') && !x.id.startsWith('ask:') && !x.id.startsWith('new:') && !x.id.startsWith('a:move') && !x.id.startsWith('rv:')) LS.set('palRecent', [x.id, ...LS.get('palRecent', []).filter(y => y !== x.id)].slice(0, 8));
  if (!x.keep) closePalette();
  x.fn();
}

// ---- shortcuts overlay ("?")
function shortcutsModal() {
  if ($('.kbmodal')) return;
  const md = modal(`<div class="kbhead"><h3>${tr('Keyboard shortcuts')}</h3><button class="iconbtn" data-m="close" aria-label="${tr('Close')}">${ic('x')}</button></div>
    <div class="kbgrid">${SHORTCUTS().map(([g, rows]) => `<section><h4>${tr(g)}</h4>${rows.map(([k, n]) => `<div class="kbrow"><span>${tr(n)}</span>${kb(k)}</div>`).join('')}</section>`).join('')}</div>
    <div class="shint kbnote">${tr('Keys work when no text field is focused. In the command palette, Enter on text without a match adds it as a new task.')}</div>`);
  md.classList.add('kbmodal');
  md.addEventListener('click', e => { if (e.target.closest('[data-m="close"]')) md.remove(); });
}

// ---- welcome tour: coach marks on the real interface; first start of a new account, restartable (Settings > Help)
const TOUR = {on: false, i: 0, steps: []};
function unionRect(els) {
  const rs = els.filter(Boolean).map(e => e.getBoundingClientRect()).filter(r => r.width || r.height);
  if (!rs.length) return null;
  const l = Math.min(...rs.map(r => r.left)), t = Math.min(...rs.map(r => r.top)), rr = Math.max(...rs.map(r => r.right)), b = Math.max(...rs.map(r => r.bottom));
  return {left: l, top: t, width: rr - l, height: b - t, right: rr, bottom: b};
}
function tourSteps() {
  const m = isMobile(), touch = isTouch(), s = [];
  const rect = sel => () => { const e = typeof sel === 'function' ? sel() : $(sel); return e ? e.getBoundingClientRect() : null; };
  s.push(m ? {id: 'side', t: N_('Smart lists'), d: N_('The Inbox comes first: new tasks without a list land there. Today, Tomorrow and Next 7 days collect tasks from all your lists. Lists, filters and tags are in this menu.'), sel: '#top .menu', r: rect('#top .menu')}
    : {id: 'side', sel: '#side .sg-focus .srow', t: N_('Smart lists'), d: N_('The Inbox comes first: new tasks without a list land there. Today, Tomorrow and Next 7 days collect tasks from all your lists. Your own lists, filters and tags follow below.'),
      r: () => unionRect($$('#side .sg-focus .srow').slice(0, 4))});
  s.push({id: 'add', sel: m ? '#fab' : '#view .qadd .box', t: N_('Quick add'), d: N_('Type the way you think: “Dentist tomorrow 3pm !high #private in Family”. Dates, priority, tags and the list (~list, “in list …”) are picked up as you type.'), r: rect(m ? '#fab' : '#view .qadd .box')});
  s.push({id: 'detail', sel: '#view .trow', t: N_('Details'), d: touch ? N_('Tap a task for notes, subtasks, files and comments. Swipe right to complete, left to reschedule.') : N_('Click a task for notes, subtasks, files and comments. Drag it onto a day or a list to move it.'), r: rect('#view .trow')});
  // steps only name modules that are on (a "Simple list" setup has no habits / focus)
  if (m) s.push({id: 'tabs', sel: '#tabs', t: N_('Tab bar'), d: feat('habits') || feat('pomo') ? N_('Your modules: calendar, habits, focus and more. Pin lists or filters here under Settings > Appearance.') : N_('Your lists and views. Pin lists or filters here under Settings > Appearance.'), r: rect('#tabs')});
  else if (!touch) s.push({id: 'keys', sel: '#top .kbtn', t: N_('Keyboard first'), d: N_('{0} opens search and commands for everything, {1} lists all shortcuts. j and k move through tasks, x completes.'), args: [kbText('Mod+K'), '?'], r: rect('#top .kbtn')});
  const pp = S.me?.is_admin || collab() ? projectParts() : [];  // "Make a list a project": admins and teams, when a project module is on
  s.push({id: 'settings', sel: m ? '#tabs [data-act="tabs-more"]' : '#side .sset', t: N_('Settings and modules'), d: pp.length ? N_('Switch modules on or off, pick the language and the appearance. A list becomes a project (Edit list > Project features) to get {0}. This tour can be restarted under Settings > Help.') : N_('Switch modules on or off, pick the language and the appearance (theme, font size, font, accent color). This tour can be restarted under Settings > Help.'), args: pp.length ? [pp.join(', ')] : [],
    r: rect(m ? () => $('#tabs [data-act="tabs-more"]') || $('#tabs [data-act="settings"]') || $('#top .menu') : '#side .sset')});
  if (collab()) s.push({id: 'news', sel: '#top .bell', t: N_('News'), d: N_('Mentions, assignments and comments on your tasks arrive here.'), r: rect('#top .bell')});
  return s.slice(0, 6);
}
function tourStart() {
  closePalette(); $$('.modal:not(.authscreen)').forEach(x => x.remove()); closePop(); if (S.sel) closeDetail();
  const inList = S.route.mod === 'tasks' && !NOLIST_KEYS.includes(S.route.key) && !isKanban() && !isTimeline();
  if (!inList || !$('#view .trow')) go('today');  // the tour points at a task (a fresh account's Inbox is empty)
  TOUR.on = true; TOUR.steps = tourSteps(); TOUR.i = 0;
  // 1.8.0: first start of an account: "Create a sample project" on the first card (preticked for project setups)
  TOUR.sample = S.settings.tour === 'pending' && !S.sample && S.settings.sample_ask !== '0'; TOUR.sampleOn = TOUR.sample && sampleDefault(); TOUR.sampleSent = false; TOUR.sampleShown = false;
  let el = $('.tour');
  if (!el) { el = document.createElement('div'); el.className = 'tour'; el.innerHTML = '<div class="tring"></div><div class="tcard" role="dialog" aria-live="polite"></div>'; document.body.appendChild(el); }
  el.addEventListener('click', e => {
    const b = e.target.closest('[data-tour]'); if (!b) return;
    const a = b.dataset.tour;
    if (a === 'next') tourGo(TOUR.i + 1); else if (a === 'back') tourGo(TOUR.i - 1); else tourEnd(true);
  });
  el.addEventListener('change', e => { if (e.target.id === 't-sample') TOUR.sampleOn = e.target.checked; if (e.target.id === 't-ptype') TOUR.ptype = e.target.value; });
  el.addEventListener('click', e => { const b = e.target.closest('[data-tpurpose]'); if (!b) return; TOUR.purpose = TOUR.purpose === b.dataset.tpurpose ? '' : b.dataset.tpurpose; tourGo(TOUR.i); $(`.tour [data-tpurpose="${b.dataset.tpurpose}"]`)?.focus(); });  // 2.19.0 (#653)
  TOUR.ptype = ''; TOUR.purpose = '';
  setTimeout(() => tourGo(0), 60);
}
// ring around the target + card placement: right of narrow targets on the left (sidebar, rail), else below / above
function tourPlace(r, vw, vh, mh) {  // mh: the card's measured height (2.5.2, K05: was a fixed 210 px)
  const z = typeof uiZ === 'function' ? uiZ() : 1, pad = 6, cw = Math.min(340 * z, vw - 24), ch = Math.min(mh || 210 * z, vh - 24);
  // no target (or it is hidden): the card in the middle of the screen (1.8.1: was 30 % from the top, high on tall tablets)
  if (!r || !(r.width || r.height)) return {ring: '', card: `width:${cw}px;left:50%;top:50%;transform:translate(-50%,-50%);max-height:calc(100dvh - 24px);overflow:auto`};
  const ring = `left:${r.left - pad}px;top:${r.top - pad}px;width:${r.width + pad * 2}px;height:${r.height + pad * 2}px`;
  if (r.right + 16 + cw < vw && r.width < vw * 0.3 && r.left < vw / 3)
    return {ring, card: `width:${cw}px;left:${r.right + 16}px;top:${Math.max(12, Math.min(vh - ch - 12, r.top))}px`};
  const below = r.bottom + 14 + ch < vh || r.top < ch + 20;
  const left = Math.max(12, Math.min(vw - cw - 12, r.left > vw / 2 ? r.right - cw : r.left));
  return {ring, card: `width:${cw}px;left:${left}px;${below ? `top:${Math.min(vh - ch, r.bottom + 14)}px` : `bottom:${Math.max(12, vh - r.top + 14)}px`}`};
}
function tourGo(i) {
  if (!TOUR.on) return;
  if (i >= TOUR.steps.length) { tourEnd(false); return; }
  TOUR.i = Math.max(0, i);
  const st = TOUR.steps[TOUR.i], el = $('.tour'); if (!el) return;
  const n = TOUR.steps.length, last = TOUR.i === n - 1;
  const card = $('.tcard', el), ring = $('.tring', el);
  el.dataset.step = st.id; el.dataset.sel = st.sel || '';
  card.innerHTML = `<div class="tstep"><span>${TOUR.i + 1}/${n}</span><span class="tdots">${TOUR.steps.map((_, j) => `<i class="${j === TOUR.i ? 'on' : j < TOUR.i ? 'past' : ''}"></i>`).join('')}</span></div>
    <h3>${TOUR.i === 0 ? heron('stand', 'htour') : ''}${tr(st.t)}</h3><p>${esc(tr(st.d, ...(st.args || []))).replace(/!(\p{L})/gu, '!\u2060$1')}</p>
    ${last && TOUR.sample && !TOUR.sampleSent ? `<label class="tsample"><input type="checkbox" id="t-sample" ${TOUR.sampleOn ? 'checked' : ''}><span><b>${tr('Create a sample project')}</b><small>${tr('A small video production with dates, dependencies and a packing list. Remove it any time under Settings > Data.')}</small></span></label>` : ''}
    <div class="tfoot"><button class="btn sm tskip" data-tour="skip">${tr('Skip tour')}</button><span class="spacer"></span>${TOUR.i ? `<button class="btn sm" data-tour="back">${tr('Back')}</button>` : ''}<button class="btn sm pri" data-tour="next">${last ? tr('Done') : tr('Next')}</button></div>`;
  const r = st.r && st.r();
  let pl = tourPlace(r, innerWidth, innerHeight);
  ring.classList.toggle('none', !pl.ring); ring.style.cssText = pl.ring; card.style.cssText = pl.card;
  // 2.5.2 (K05): place again with the real height of the card, then keep it inside the window (Back / Next always visible)
  const mh = card.offsetHeight;
  if (mh) {
    pl = tourPlace(r, innerWidth, innerHeight, mh); card.style.cssText = pl.card + ';max-height:calc(100dvh - 24px);overflow-y:auto';
    const cr = card.getBoundingClientRect();
    if (cr.height && pl.ring && (cr.bottom > innerHeight - 12 || cr.top < 12)) { card.style.bottom = 'auto'; card.style.top = Math.max(12, Math.min(innerHeight - cr.height - 12, cr.top)) + 'px'; }
  }
  if (last && TOUR.sample) TOUR.sampleShown = true;  // 2.25.0 (UX-24)
  $('[data-tour="next"]', card)?.focus();
}
async function tourSample() {  // 2.25.0 (UX-24): once, when the tour ends and its last card offered the sample project
  if (!TOUR.sample || TOUR.sampleSent || !TOUR.sampleShown) return;
  TOUR.sampleSent = true;
  if (TOUR.purpose) {  // 2.19.0 (#653): "What do you use Kalmido for?" -> the modules + starter lists of that purpose
    try { await api('POST', '/api/me/purpose', {purpose: TOUR.purpose}); await load(); render(); } catch { /* offline: Settings > Modules */ }
  }
  if (TOUR.ptype) {  // 2.4.0 (#243): "Start with a project" of a built-in type
    const pt = PTYPE_UI.find(x => x[0] === TOUR.ptype);
    try { const n = await api('POST', '/api/lists', {name: tr(pt[1]), ptype: pt[0]}); await load(); render(); modulesOnToast(n.modules_on); } catch { /* offline: New list > Project */ }
  }
  if (!TOUR.sampleOn) return;
  try { const j = await api('POST', '/api/sample', {}); await load(); render(); if (TOUR.on) tourGo(TOUR.i); if (j?.created) toast(tr('Sample project created. Remove it any time under Settings > Data.')); } catch { /* offline: Settings > Data */ }
}
async function tourEnd(skipped) {
  tourSample();
  TOUR.on = false; $('.tour')?.remove();
  if (S.settings.tour === 'pending') { S.settings.tour = 'done'; try { await api('PATCH', '/api/settings', {tour: 'done'}); } catch { /* offline: shows again next start */ } }
  if (!skipped) toast(tr('Tour finished. Restart it any time under Settings > Help.'));
}
window.addEventListener('resize', () => { if (TOUR.on) tourGo(TOUR.i); });

// ---- completion celebration: the heron flies across the screen, checkmark confetti falls behind it, a dry one-liner
const QUIPS = {data: null, last: -1};
async function quipsLoad() {
  if (QUIPS.data) return QUIPS.data;
  try { const r = await fetch('/static/quips.json'); if (r.ok) QUIPS.data = await r.json(); } catch { /* offline, no cache: no line */ }
  return QUIPS.data;
}
function nextQuip() {
  const d = QUIPS.data; if (!d) return '';
  const arr = d[I18N.code] || d.en || []; if (!arr.length) return '';
  let i = Math.floor(Math.random() * arr.length);
  if (arr.length > 1 && i === QUIPS.last) i = (i + 1 + Math.floor(Math.random() * (arr.length - 1))) % arr.length;  // no immediate repeat
  QUIPS.last = i; LS.set('quipLast', i);
  return arr[i];
}
QUIPS.last = LS.get('quipLast', -1);
// the small standing heron of the app icon: the calm variant (reduced motion) next to its line
const HERON_SWING_SVG = `<svg class="cheron" viewBox="-90 -10 150 200" aria-hidden="true"><g transform="translate(48 -3) scale(2.2) translate(-77 -26)" fill="none" stroke="currentColor" stroke-width="4.5" stroke-linecap="round" stroke-linejoin="round">
  <path d="M24 50C34 42 52 43 62 51C55 58 40 60 30 55"/><path d="M54 48C51 39 49 32 51 25C53 20 58 19 61 22"/><path d="M61 22L77 26"/>
  <path d="M44 58V84"/><path d="M44 68L37 64L41 60" stroke-width="3.6"/></g></svg>`;
// 2.22.0 (#688): the heron in flight, in the line style of the icon: neck tucked in (an S onto the shoulders), the long beak
// ahead, the legs straight out behind, one broad wing that beats slowly (the wing group scales around the shoulder)
const HERON_FLY_SVG = `<svg class="cheron cfly" viewBox="0 0 140 80" aria-hidden="true"><g fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round">
  <path d="M44 48C55 41 77 39 92 43C84 50 62 54 47 52Z"/><path d="M91 43C97 42 100 38 98 34C96 30 99 27 104 28"/><path d="M104 28L127 33"/>
  <path d="M47 50L13 55M49 52L15 59" stroke-width="2.2"/><path d="M13 55L8 53M15 59L10 60" stroke-width="1.8"/>
  <g class="cwing"><path d="M58 45C55 27 70 11 99 3C92 15 88 29 83 45"/><path d="M66 41C66 29 74 19 89 11" stroke-width="1.8"/></g></g>
  <circle class="d" cx="103" cy="30" r="1.6" fill="currentColor"/></svg>`;
const CHECK_SVG = '<svg viewBox="0 0 16 16" fill="none" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M2 8.5 6 12.5 14 3.5"/></svg>';
const reducedMotion = () => { try { return matchMedia('(prefers-reduced-motion: reduce)').matches; } catch { return false; } };
const CELE_MS = 2600;
// the flight at progress p (0..1): from beyond the left edge to beyond the right edge on a shallow arc, a slight bob per
// wing beat; WINGS beats over the whole flight (calm: about one beat every 0.65 s)
const WINGS = 4;
function flyAt(p, vw, vh) {
  const x = -140 + (vw + 280) * p, y = vh * 0.34 - Math.sin(Math.PI * p) * vh * 0.1 + Math.sin(Math.PI * 2 * WINGS * p) * 5;
  const tilt = -Math.cos(Math.PI * p) * 6;  // climbs a little at first, glides down at the end
  return {transform: `translate(${x.toFixed(1)}px,${y.toFixed(1)}px) rotate(${tilt.toFixed(2)}deg)`};
}
const wingAt = p => ({transform: `scaleY(${(0.2 + 0.8 * Math.cos(Math.PI * 2 * WINGS * p)).toFixed(3)})`});
function celebrate(kind, {name = '', frame = null, force = false} = {}) {
  if (!force && S.settings.celebrate === '0') return;
  $$('.cele,.cele-quip').forEach(x => x.remove());
  const quip = nextQuip() || (kind === 'today' ? tr('Today is done.') : tr('All done.'));
  const title = kind === 'today' ? tr('Today is clear') : kind === 'project' ? tr('Project complete: {0}', name) : tr('List complete: {0}', name);
  const q = document.createElement('div');
  q.className = 'cele-quip'; q.setAttribute('role', 'status');
  q.innerHTML = `${reducedMotion() ? HERON_SWING_SVG : ''}<div><b>${esc(title)}</b><span>${esc(quip)}</span></div>`;
  if (reducedMotion()) {  // calm variant: small heron + line, no motion
    q.classList.add('calm'); q.dataset.kind = kind;
    document.body.appendChild(q);
    if (frame === null) setTimeout(() => q.remove(), 4200);
    return q;
  }
  const vw = innerWidth || 1440, vh = innerHeight || 900;
  const el = document.createElement('div');
  el.className = 'cele'; el.dataset.kind = kind; el.setAttribute('aria-hidden', 'true');
  el.innerHTML = `<div class="cbird">${HERON_FLY_SVG}</div>`;
  document.body.appendChild(el); document.body.appendChild(q);
  const bird = $('.cbird', el), wing = $('.cwing', el);
  // confetti: checkmarks let go behind the heron along its way (start p0), they drift back a little and fall
  const N = 28, pieces = [];
  for (let i = 0; i < N; i++) {
    const c = document.createElement('span');
    c.className = 'cconf' + (i % 5 === 0 ? ' alt' : '');
    c.innerHTML = CHECK_SVG;
    el.appendChild(c);
    const p0 = 0.12 + 0.72 * (i / (N - 1)) + (Math.random() - 0.5) * 0.04;
    pieces.push({c, p0, vx: -40 - Math.random() * 90, vy: -30 + Math.random() * 60, spin: (Math.random() - 0.5) * 720, s: 0.65 + Math.random() * 0.7, life: 0.9 + Math.random() * 0.5});
  }
  const birdW = Math.min(150, Math.max(104, vw * 0.12));
  bird.style.width = birdW + 'px';
  const confAt = (pc, tt) => {  // tt: seconds since the piece was let go (behind the tail)
    const f = flyAt(pc.p0, vw, vh).transform.match(/translate\(([-\d.]+)px,([-\d.]+)px/);
    const x0 = +f[1] + birdW * 0.12, y0 = +f[2] + birdW * 0.32;
    const x = x0 + pc.vx * tt, y = y0 + pc.vy * tt + 520 * tt * tt;
    return {transform: `translate(${x.toFixed(1)}px,${y.toFixed(1)}px) rotate(${(pc.spin * tt).toFixed(1)}deg) scale(${pc.s})`,
      opacity: tt <= 0 ? 0 : Math.max(0, 1 - Math.max(0, tt - pc.life * 0.55) / (pc.life * 0.45))};
  };
  if (frame !== null || !el.animate) {  // a still frame (screenshots, tests, browsers without Web Animations)
    const p = frame ?? 0.5;
    Object.assign(bird.style, flyAt(p, vw, vh)); Object.assign(wing.style, wingAt(p));
    for (const pc of pieces) Object.assign(pc.c.style, confAt(pc, (p - pc.p0) * CELE_MS / 1000));
    q.classList.add('on');
    if (frame === null) setTimeout(() => { el.remove(); q.remove(); }, 3200);
    return el;
  }
  const K = 48, steps = [...Array(K + 1)].map((_, i) => i / K);
  bird.animate(steps.map(p => ({...flyAt(p, vw, vh), offset: p})), {duration: CELE_MS, easing: 'linear', fill: 'both'});
  wing.animate(steps.map(p => ({...wingAt(p), offset: p})), {duration: CELE_MS, easing: 'linear', fill: 'both'});
  for (const pc of pieces) {
    const dur = pc.life * 1000, ks = [...Array(13)].map((_, i) => i / 12);
    pc.c.animate(ks.map(f => ({...confAt(pc, f * pc.life), offset: f})), {duration: dur, delay: CELE_MS * pc.p0, easing: 'linear', fill: 'both'});
  }
  setTimeout(() => q.classList.add('on'), CELE_MS * 0.3);
  setTimeout(() => el.remove(), CELE_MS + 1600);
  setTimeout(() => q.classList.remove('on'), 3600);
  setTimeout(() => q.remove(), 4000);
  return el;
}
// trigger check around a completion: snapshot before, compare after the state reload
const openByList = () => { const m = {}; for (const t of S.tasks.values()) if (t.status === 0) m[t.list_id] = (m[t.list_id] || 0) + 1; return m; };
function celeSnap(ids) {
  const ts = ids.map(taskById).filter(Boolean);
  return {today: counts().today, lists: openByList(), lids: [...new Set(ts.map(t => t.list_id))], inToday: ts.some(t => t.due && t.due <= today())};
}
function celeCheck(b) {
  if (!b || S.settings.celebrate === '0') return;
  if (b.inToday && b.today > 0 && counts().today === 0) { celebrate('today'); return; }
  const after = openByList();
  for (const lid of b.lids) {
    const l = listById(lid);
    if (l && !l.is_inbox && b.lists[lid] > 0 && !after[lid]) { celebrate('list', {name: lname(l)}); return; }
  }
}
