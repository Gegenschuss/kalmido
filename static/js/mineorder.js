/* Kalmido web client: "My tasks" in the person's own order (2.40.0, #1344).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md).
   - the view menu switches between "Own order" (default) and "Grouped by list" (setting mine_view: own | lists)
   - dragging a task in "My tasks" changes only the person's own order (PUT /api/tasks/mine-order, queued offline like the other
     task writes; /api/state: mine_order {task id: pos}); tasks.sort of the shared list stays untouched
   - new and newly assigned tasks (no place yet) stand on top, newest first
   - "Own order": a grey subtitle "List › Section" under every task, a tap opens the list
   - "Grouped by list": the groups can be put in an own order (#1221); a task dropped into another group moves to that list */
'use strict';

const moView = () => S.settings?.mine_view === 'lists' ? 'lists' : 'own';
const moActive = () => S.route.mod === 'tasks' && S.route.key === 'assigned';
const moOwn = () => moActive() && moView() === 'own';
// what counts as mine: assigned to me or one of my groups; without collaboration every task of my lists (#1344: always shown)
const moPred = () => collab() ? mineAssigned : mineTask;
const moFromState = j => { mtFromState(j); return OUT.q.some(e => e.url === '/api/tasks/mine-order') ? (S.mineOrder || {}) : (j.mine_order || {}); };
const moPos = t => { const p = S.mineOrder?.[t.id]; return p == null ? null : +p; };
function moCmp(a, b) {
  const x = moPos(a), y = moPos(b);
  if (x == null && y == null) return (b.created_at || '').localeCompare(a.created_at || '') || b.id - a.id;  // not placed yet: newest first
  if (x == null) return -1;
  if (y == null) return 1;
  return x - y || a.id - b.id;
}
const moSort = arr => arr.sort(moCmp);
// every task of "My tasks" in the current own order (unfiltered: a view filtered to favourites keeps the hidden tasks' places)
function moAll() {
  const p = moPred(), m = openTasks(true).filter(t => !t.context && p(t)), ids = new Set(m.map(t => t.id));
  return moSort(m.filter(t => !t.parent_id || !ids.has(t.parent_id)));
}
async function moSave(ids) {
  S.mineOrder = Object.fromEntries(ids.map((id, i) => [id, i]));
  render();
  try { await api('PUT', '/api/tasks/mine-order', {ids: ids.filter(id => id > 0)}); } catch { /* api() showed it; offline it waits in the outbox */ }
}
// dnd.js dropTask0: a drop onto a row of "My tasks" -> true when handled here (never a change of tasks.sort)
async function moDrop(t, row, after) {
  if (!moActive() || !row) return false;
  const target = S.tasks.get(+row.dataset.id);
  if (!target || target.id === t.id) return true;
  const all = moAll().map(x => x.id);
  if (!all.includes(t.id) || !all.includes(target.id)) return true;  // e.g. "From your lists, without a date": no own order there
  const ids = all.filter(x => x !== t.id);
  ids.splice(ids.indexOf(target.id) + (after ? 1 : 0), 0, t.id);
  if (moView() === 'lists' && target.list_id !== t.list_id) {  // grouped: into another group = into that list
    if (!canEditList(target.list_id)) { roToast(); return true; }
    if (tlkHits(t, {list_id: target.list_id})) { tlkToast(t); render(); return true; }  // a locked task keeps its list
    S.mineOrder = Object.fromEntries(ids.map((id, i) => [id, i]));
    try { await patchUndoable(t.id, {list_id: target.list_id, section_id: null}, tr('Moved to {0}', lname(listById(target.list_id)))); } catch { return true; }
  }
  await moSave(ids);
  return true;
}
// the grey subtitle "List › Section" (render.js taskRow, own order only)
function moSubHtml(t) {
  const l = listById(t.list_id); if (!l) return '';
  const sec = t.section_id ? S.sections.find(s => s.id === t.section_id)?.name : '';
  const txt = lname(l) + (sec ? ' › ' + sec : '');
  return `<button type="button" class="mosub" data-go="${esc(keyToHash(l.is_inbox ? 'inbox' : 'l:' + l.id))}" title="${esc(tr('Open {0}', lname(l)))}">${licMark(l, 'lsm')}<span>${esc(txt)}</span></button>`;
}
// the view menu (render.js topMoreItems)
function moViewItems() {
  if (!moActive() || moBoard()) return [];  // 2.156.0 C (#2072): the board has its own columns
  const set = v => () => { if (moView() === v) return; S.settings.mine_view = v; render(); api('PATCH', '/api/settings', {mine_view: v}).catch(() => {}); };
  return [{label: tr('Own order'), icon: 'sort', on: moView() === 'own', fn: set('own')}, {label: tr('Grouped by project'), icon: 'list', on: moView() === 'lists', fn: set('lists')}];
}

// ---- 2.41.0 (#1365): "Show in My tasks" per list, only for me (PUT /api/lists/<id>/in-mine; /api/state mine_hidden = ids of
// the lists switched off). Their tasks leave "My tasks" for the group "Hidden (N)" at the end (folded until opened, every list
// with "Show the list again"); my assigned tasks of such a list due today or overdue stay visible in the small group "From
// hidden lists" above it. The sidebar counts what "My tasks" shows openly (hidden ones only when due today or overdue).
// The own order (#1344) keeps the hidden tasks' places; the other views do not look at it.
function mtFromState(j) { if (!OUT.q.some(e => /^\/api\/lists\/\d+\/in-mine$/.test(e.url))) S.mineHidden = new Set(j.mine_hidden || []); }
const mtHid = t => !!S.mineHidden?.has(t.list_id);
const mtUrgent = (t, t0 = today()) => !!t.due && t.due <= t0;
const mtCounts = (t, t0) => !mtHid(t) || mtUrgent(t, t0);
const mtShown = id => !S.mineHidden?.has(id);
// views.js groupTasks: the two groups at the end of "My tasks" (hid: hidden roots of my tasks, kb: hidden undated tasks of
// "From your lists, without a date")
function mtGroups(hid, kb) {
  const t0 = today(), urg = hid.filter(t => mtUrgent(t, t0)).sort((a, b) => dueKey(a).localeCompare(dueKey(b)) || a.id - b.id);
  const ord = kbListOrder().map(l => l.id), rest = [...hid.filter(t => !mtUrgent(t, t0)), ...kb]
    .sort((a, b) => ord.indexOf(a.list_id) - ord.indexOf(b.list_id) || moCmp(a, b));
  const out = [];
  if (urg.length) out.push({id: 'mt:urgent', name: tr('From hidden projects'), tasks: urg, cls: 'mturg'});
  if (rest.length) out.push({id: 'mt:hidden', name: tr('Hidden'), tasks: rest, cls: 'mthid', folded: true, byList: true});
  return out;
}
// the head of one list inside "Hidden" (render.js viewListBody, before its first task)
function mtListHead(lid) {
  const l = listById(lid); if (!l) return '';
  return `<div class="mthl">${licMark(l, 'lsm')}<span class="mthn">${esc(lname(l))}</span><button type="button" class="linkbtn" data-mt="show" data-id="${l.id}">${esc(tr('Show the project again'))}</button></div>`;
}
async function mtSet(id, on, o = {}) {
  const was = mtShown(id);
  if (was === on) return;
  if (!S.mineHidden) S.mineHidden = new Set();
  if (on) S.mineHidden.delete(id); else S.mineHidden.add(id);
  render();
  try {
    const j = await api('PUT', `/api/lists/${id}/in-mine`, {on});
    if (Array.isArray(j?.mine_hidden)) S.mineHidden = new Set(j.mine_hidden);
  } catch { if (was) S.mineHidden.delete(id); else S.mineHidden.add(id); render(); return; }
  render();
  o.post?.();
  if (!o.quiet) toast(on ? tr('{0} shows in My tasks again', lname(listById(id))) : tr('{0} is hidden in My tasks', lname(listById(id))), () => mtSet(id, was, {...o, quiet: true}));
}
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-mt="show"]'); if (!b) return;
  e.preventDefault(); e.stopPropagation(); mtSet(+b.dataset.id, true);
}, true);

// ---- 2.156.0 C (#2072): "My tasks" as a board (mineboard.js, module mineboard, loaded on demand): the switch List / Board
// and the board's columns (by due date, priority or list) at the top of the view; settings mine_board (0 | 1) and
// mine_board_by (due | prio | list), per person on every device
const moBoard = () => S.settings?.mine_board === '1';
const moBoardBy = () => ['prio', 'list'].includes(S.settings?.mine_board_by) ? S.settings.mine_board_by : 'due';
function moSetPref(k, v) {
  if (!S.settings || S.settings[k] === v) return;
  S.settings[k] = v; render();
  api('PATCH', '/api/settings', {[k]: v}).catch(() => {});
}
function moSegHtml() {
  if (!moActive()) return '';
  const b = moBoard(), btn = (act, k, on, ico, label) => `<button type="button" class="${on ? 'on' : ''}" data-act="${act}"${k ? ` data-k="${k}"` : ''} aria-pressed="${on}" title="${esc(label)}">${ico ? ic(ico, 's') : ''}<span>${esc(label)}</span></button>`;
  let h = `<div class="mobar"><div class="seg mbseg" role="group" aria-label="${esc(tr('View'))}">${btn('mo-view', 'list', !b, 'list', tr('List'))}${btn('mo-view', 'board', b, 'kanban', tr('Board'))}</div>`;
  if (b) h += `<div class="seg mbby" role="group" aria-label="${esc(tr('Columns by'))}">${[['due', N_('Due')], ['prio', N_('Priority')], ['list', N_('Project')]].map(([k, n]) => btn('mo-by', k, moBoardBy() === k, '', tr(n))).join('')}</div>`;
  return h + '</div>';
}
// dnd.js dropTask0: a drop inside the board -> true when handled there (mineboard.js mb_drop)
const mbDropHook = (t, el) => moActive() && moBoard() && typeof mb_drop === 'function' ? mb_drop(t, el) : false;
document.addEventListener('click', e => {
  const b = e.target.closest?.('#view .mobar [data-act="mo-view"], #view .mobar [data-act="mo-by"]'); if (!b) return;
  e.preventDefault(); e.stopPropagation();
  if (b.dataset.act === 'mo-view') moSetPref('mine_board', b.dataset.k === 'board' ? '1' : '0');
  else moSetPref('mine_board_by', b.dataset.k);
}, true);
