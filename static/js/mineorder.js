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
// 2.363.3 (#3133): S.mineBase = the order the server confirmed, sent as _prev: an order that waited offline does not overwrite one set elsewhere
const moIds = o => Object.entries(o).sort((a, b) => a[1] - b[1]).map(x => +x[0]);
const moFromState = j => { mtFromState(j); mseFromState(j); if (OUT.q.some(e => e.url === '/api/tasks/mine-order')) return S.mineOrder || {}; S.mineBase = moIds(j.mine_order || {}); return j.mine_order || {}; };
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
async function moSave(ids, secs) {  // 2.569.0 (#4395): secs = {task id: own section id} put there by hand
  S.mineOrder = Object.fromEntries(ids.map((id, i) => [id, i]));
  if (secs && S.mineSecs) S.mineSecs.tasks = {...S.mineSecs.tasks, ...secs};
  render();
  const send = ids.filter(id => id > 0), seen = S.mineBase;
  S.mineBase = send;  // the next drag builds on this one
  try {
    const r = await api('PUT', '/api/tasks/mine-order', {ids: send, ...(seen ? {_prev: {ids: seen}} : {}), ...(secs ? {secs} : {})});
    if (r?.order_kept) { toast(tr(MO_KEPT)); await load(); render(); }
  } catch { if (S.mineBase === send) S.mineBase = seen; /* api() showed it; the server never confirmed this order; offline it waits in the outbox */ }
}
// dnd.js dropTask0: a drop onto a row of "My tasks" -> true when handled here (never a change of tasks.sort)
async function moDrop(t, row, after) {
  if (!moActive() || !row) return false;
  const target = S.tasks.get(+row.dataset.id);
  if (!target || target.id === t.id) return true;
  const all = moAll().map(x => x.id);
  if (!all.includes(t.id) || !all.includes(target.id)) return true;  // e.g. "From your lists, without a date": no own order there
  if (mseOn()) return mseDrop(t, row.closest('.group')?.querySelector('.ghead[data-key^="ms:"]'), target.id, after);  // 2.569.0 (#4395)
  const ids = all.filter(x => x !== t.id);
  ids.splice(ids.indexOf(target.id) + (after ? 1 : 0), 0, t.id);
  if (moView() === 'lists' && target.list_id !== t.list_id) {  // grouped: into another group = into that list
    if (!canEditList(target.list_id)) { roToast(); return true; }
    if (tlkHits(t, {list_id: target.list_id})) { tlkToast(t); render(); return true; }  // a locked task keeps its list
    if (!await mv_ask([t.id], listById(target.list_id))) return true;  // 2.455.0 (#3848)
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
  return [{label: tr('Own order'), icon: 'sort', on: moView() === 'own', fn: set('own')}, {label: tr('Grouped by project'), icon: 'list', on: moView() === 'lists', fn: set('lists')},
    ...(moView() === 'own' && !isMobile() ? [{label: tr('Project as a column'), icon: 'columns', on: moListCol(), fn: () => { LS.set('moListCol', !moListCol()); render(); }}] : [])];  // 2.569.0 (#4395)
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
  let h = `<div class="mobar"><div class="seg mbseg" role="group" aria-label="${esc(tr('View'))}">${btn('mo-view', 'list', !b, 'list', tr('List'))}${btn('mo-view', 'board', b, 'kanban', tr('Kanban'))}</div>`;  // 2.365.0 (#3010): "Kanban" as in a project
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

// ---- 2.569.0 (#4395): own sections in the own order (/api/mine-sections, kalmido/tasks/mineorder.py; /api/state mine_sections
// {list, tasks}). Personal: they never change a list, its sections or its order. On top the fixed section "Recently assigned"
// (kind recent: tasks without a place; shown while it has tasks, never renamed or deleted); the first opening makes "Now",
// "Soon", "Someday" (kinds now / soon / later, the name '' = the translated default). A task due today or overdue goes into the
// section of kind now (also renamed) unless the person put it into a section by hand (tasks map); without such a section the
// rule is gone. A task with a place but no section stands in the topmost section. Deleting a section moves its tasks into the
// topmost one left (Undo brings it back); renaming and deleting carry the version (409 = changed on another device).
const MSE_KIND = {recent: N_('Recently assigned'), now: N_('Now'), soon: N_('Soon'), later: N_('Someday')};
const mseList = () => S.mineSecs?.list || [];
const mseName = s => s.name || tr(MSE_KIND[s.kind] || '');
const mseOn = () => moOwn() && !moBoard() && mseList().length > 0;
const moListCol = () => moOwn() && !isMobile() && LS.get('moListCol', false) === true;  // (4): "Project" as a column (this device)
// #3506 (CI red of 2.614.0, p2569_a): a folding whose PATCH has not come back yet - an answer the server gave before it (the
// DELETE of another section, a state load) carried the old value and folded the section again under the hand that opened it
const mseFoldP = new Map();
const mseKeepFold = ms => { for (const s of ms?.list || []) if (mseFoldP.has(s.id)) s.collapsed = mseFoldP.get(s.id); return ms; };
function mseFromState(j) {
  if (!j.mine_sections) return;
  const q = OUT.q.some(e => e.url === '/api/tasks/mine-order');  // a drag waiting offline keeps its sections
  S.mineSecs = {list: mseKeepFold(j.mine_sections).list || [], tasks: q && S.mineSecs ? S.mineSecs.tasks : j.mine_sections.tasks || {}};
}
let mseIniting = false;
async function mseInit() {  // the first opening of the own order: the default sections (once; the server does nothing a second time)
  if (mseIniting || !moOwn() || !S.mineSecs || mseList().length) return;
  mseIniting = true;
  try { const j = await api('POST', '/api/mine-sections/init', {}); if (j?.mine_sections) { S.mineSecs = j.mine_sections; render(); } } catch { mseIniting = false; /* offline: next time */ }
}
// the section a task stands in (id; null = no own section left)
function mseOf(t, x) {
  const p = x.map[t.id];
  if (p && x.ids.has(p)) return p;  // put there by hand: wins
  if (x.now && mtUrgent(t, x.t0)) return x.now.id;
  if (moPos(t) == null && x.rec) return x.rec.id;
  return x.top ? x.top.id : null;
}
function mseCtx() {
  const L = mseList(), own = L.filter(s => s.kind !== 'recent');
  return {rec: L.find(s => s.kind === 'recent'), own, now: own.find(s => s.kind === 'now'), top: own[0], ids: new Set(own.map(s => s.id)), map: S.mineSecs?.tasks || {}, t0: today()};
}
// views.js groupTasks: the groups of the own order (arr = the shown tasks in the own order)
function mseGroups(arr) {
  const x = mseCtx(), by = new Map();
  for (const t of arr) { const k = mseOf(t, x); if (!by.has(k)) by.set(k, []); by.get(k).push(t); }
  const mk = s => {
    const id = 'ms:' + s.id;
    if (s.collapsed) S.collapsed.add(id); else S.collapsed.delete(id);  // the folding of every device (the server keeps it)
    return {id, name: mseName(s), tasks: by.get(s.id) || [], cls: 'mosec' + (s.kind === 'recent' ? ' msrec' : ''), mosec: s};
  };
  const out = x.rec && by.get(x.rec.id)?.length ? [mk(x.rec)] : [];
  out.push(...x.own.map(mk));
  if (by.get(null)?.length) out.push({id: 'ms:none', name: '', tasks: by.get(null)});
  return out;
}
// render.js: the "…" of an own section in its head; the button "New section" under the last one
const mseHeadHtml = g => g.mosec && g.mosec.kind !== 'recent' ? `<button type="button" class="iconbtn gact" data-mse-menu="${g.mosec.id}" title="${esc(tr('More') + ': ' + g.name)}" aria-label="${esc(tr('More') + ': ' + g.name)}">${ic('dots', 's')}</button>` : '';
const mseAddHtml = () => mseOn() ? `<button type="button" class="linkbtn msenew" data-mse-add="1">${ic('plus', 's')}<span>${esc(tr('New section'))}</span></button>` : '';
// a drop into an own section (moDrop: onto a row of it; dnd.js: onto its head = on top of it). Only the tasks shown in own
// sections are sent (with their places); "Recently assigned" takes nothing.
async function mseDrop(t, head, targetId = null, after = false) {
  const sid = head ? +head.dataset.key.slice(3) : NaN, s = mseList().find(x => x.id === sid);
  if (!s || s.kind === 'recent') return true;
  const x = mseCtx(), all = moAll().filter(y => y.id !== t.id), flat = [];
  for (const o of x.own) flat.push(...all.filter(y => mseOf(y, x) === o.id).map(y => y.id));
  flat.push(...all.filter(y => mseOf(y, x) === null).map(y => y.id));
  let at = targetId != null && flat.includes(targetId) ? flat.indexOf(targetId) + (after ? 1 : 0) : -1;
  if (at < 0) { const first = all.find(y => mseOf(y, x) === sid); at = first ? flat.indexOf(first.id) : flat.length; }
  flat.splice(at, 0, t.id);
  await moSave(flat, {[t.id]: sid});
  return true;
}
const mseDropHead = async (t, el) => { const h = moActive() && mseOn() && el.closest?.('#view .ghead[data-key^="ms:"]'); return h ? mseDrop(t, h) : false; };
async function mseCall(method, url, b) {
  try { const j = await api(method, url, b); if (j?.mine_sections) S.mineSecs = {...mseKeepFold(j.mine_sections), ...(OUT.q.some(e => e.url === '/api/tasks/mine-order') ? {tasks: S.mineSecs.tasks} : {})}; if (j?.order_kept) toast(tr('The sections were changed on another device: that order stays.')); render(); return j; }
  catch (e) { if (e?.status === 409 || e?.status === 404) { await load(); render(); } return null; }  // api() showed the reason; the current state instead of an old one
}
async function mseRename(s) {
  const old = mseName(s), n = (await askPrompt(tr('Rename section'), old, {ok: tr('Rename'), input: {max: 200}}))?.trim();
  if (!n || n === old) return;
  const j = await mseCall('PATCH', `/api/mine-sections/${s.id}`, {name: n, expect_updated_at: s.updated_at});
  if (j?.section) toast(tr('Section renamed'), () => mseCall('PATCH', `/api/mine-sections/${s.id}`, {name: old, expect_updated_at: j.section.updated_at}));
}
async function mseMove(s, d) {
  const ids = mseList().filter(x => x.kind !== 'recent').map(x => x.id), i = ids.indexOf(s.id), k = i + d;
  if (i < 0 || k < 0 || k >= ids.length) return;
  const nw = ids.slice(); nw.splice(i, 1); nw.splice(k, 0, s.id);
  await mseCall('PUT', '/api/mine-sections/order', {ids: nw, _prev: {ids}});
}
async function mseDelete(s) {
  const j = await mseCall('DELETE', `/api/mine-sections/${s.id}`, {expect_updated_at: s.updated_at});
  if (j?.restore) toast(tr('Section deleted'), () => mseCall('POST', '/api/mine-sections', {name: j.restore.name, restore: j.restore}));
}
async function mseAdd() {
  const n = (await askPrompt(tr('New section'), '', {ok: tr('Create'), input: {placeholder: tr('Name'), max: 200}}))?.trim();
  if (n) await mseCall('POST', '/api/mine-sections', {name: n});
}
function mseMenu(anchor, sid) {
  const s = mseList().find(x => x.id === sid); if (!s) return;
  const own = mseList().filter(x => x.kind !== 'recent'), i = own.indexOf(s);
  menu(anchor, [
    {label: tr('Rename'), icon: 'edit', fn: () => mseRename(s)},
    ...(i > 0 ? [{label: tr('Move up'), icon: 'up', fn: () => mseMove(s, -1)}] : []),
    ...(i < own.length - 1 ? [{label: tr('Move down'), icon: 'down', fn: () => mseMove(s, 1)}] : []),
    '-',
    {label: tr('Delete section (tasks stay)'), icon: 'trash', cls: 'flag-5', fn: () => mseDelete(s)},
  ]);
}
document.addEventListener('click', e => {
  const m = e.target.closest?.('#view [data-mse-menu]'), a = !m && e.target.closest?.('#view [data-mse-add]');
  if (m || a) { e.preventDefault(); e.stopPropagation(); if (m) mseMenu(m, +m.dataset.mseMenu); else mseAdd(); return; }
  const h = e.target.closest?.('#view .ghead[data-key^="ms:"]');  // folding: the server keeps it for every device (events.js toggles it here)
  if (!h || e.target.closest('.gact, .shandle') || h.dataset.key === 'ms:none') return;
  const s = mseList().find(x => x.id === +h.dataset.key.slice(3)); if (!s) return;
  const v = s.collapsed = !s.collapsed;
  mseFoldP.set(s.id, v);
  api('PATCH', `/api/mine-sections/${s.id}`, {collapsed: v}).catch(() => {}).finally(() => { if (mseFoldP.get(s.id) === v) mseFoldP.delete(s.id); });
}, true);
