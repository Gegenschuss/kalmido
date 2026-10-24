/* Kalmido web client: "Tap to complete" of a list (2.46.4, #1751).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ---- 2.46.4 (#1751): a list switch (lists.tap_done, the same for every member; owner / list admins change it). On, a tap
// on a task row of the list (its title, the gaps of the row) ticks the task off or back on like its circle (with the undo
// message); the details stay one step away: the row's menu ("Open details": right-click on a desktop, long press > More on
// a phone), Enter on the focused row, the columns of a table list. A double click on a desktop still renames the task
// (the first click waits for it). Only in the list's own list view (not Kanban, Today, search); on by default for new
// shopping and packing lists, existing ones got it on once (server).
const tp_on = l => !!l && !!+(l.tap_done || 0);
// the task of a click this switch takes over, else 0
function tp_hit(e) {
  if (e.button || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey || S.multiMode || S.multi.size) return 0;
  const r = e.target.closest?.('#view .trow[data-id]'); if (!r || r.classList.contains('ghost') || r.classList.contains('iedit')) return 0;
  const l = routeList(); if (!tp_on(l) || isKanban() || (typeof swiped !== 'undefined' && swiped)) return 0;
  if (e.target.closest('a[href], button, input, textarea, select, .caret, [data-mcard], .ttlin')) return 0;
  const a = e.target.closest('[data-act]');
  if (a ? !(a.dataset.act === 'open' && a.matches('.tmain, .tgut') && r.contains(a)) : e.target !== r) return 0;
  const t = taskById(+r.dataset.id);
  return t && t.id > 0 && t.list_id === l.id && canEdit(t) ? t.id : 0;  // read-only: the tap opens the task as before
}
let tp_wait = null;  // {id, timer}: a mouse click waits for a possible double click (= rename)
document.addEventListener('click', e => {
  const id = tp_hit(e); if (!id) return;
  e.preventDefault(); e.stopPropagation();
  if (tp_wait) { clearTimeout(tp_wait.timer); const same = tp_wait.id === id; tp_wait = null; if (same && e.detail > 1) return; }
  const go = () => { tp_wait = null; toggleTask(id).catch(() => {}); };
  if ((e.pointerType || (isTouch() ? 'touch' : 'mouse')) === 'touch') { go(); return; }
  tp_wait = {id, timer: setTimeout(go, 280)};
}, true);
document.addEventListener('dblclick', e => {
  if (tp_wait && e.target.closest?.(`#view .trow[data-id="${tp_wait.id}"]`)) { clearTimeout(tp_wait.timer); tp_wait = null; }
}, true);
// "Open details" on top of the row's menu (taskMenu) and of the phone's selection menu (multiMoreMenu) for such a task
function tp_menuItems(t, anchor) {
  if (!t || !(t.id > 0) || anchor?.closest?.('#detail') || !tp_on(listById(t.list_id))) return [];
  return [{label: tr('Open details'), icon: 'edit', fn: () => { if (S.multiMode || S.multi.size) { S.multi.clear(); S.multiMode = false; renderMultiBar(); } openDetail(t.id); }}, '-'];
}
// ---- the switch in the list's settings (dialogs.js listModal)
function tp_rowHtml(l) {
  if (!l || l.is_inbox || !canManage(l)) return '';
  return `<div class="row ltaprow"><label>${tr('Tap')}</label><label class="chkl"><input type="checkbox" id="l-tap" ${tp_on(l) ? 'checked' : ''}> ${tr('Tap to complete')}</label></div>
    <div class="shint lhint">${tr('A tap on a task ticks it off. Details with a long press or the menu.')}</div>`;
}
function tp_wire(md, id) {
  $('#l-tap', md)?.addEventListener('change', e => { e.stopPropagation(); tp_set(id, e.target.checked).then(() => tp_sync(md, listById(id))); });
}
function tp_sync(md, l) { const c = $('#l-tap', md); if (c && l) c.checked = tp_on(l); }
async function tp_set(id, on) {
  const l = listById(id); if (!l) return;
  const was = tp_on(l) ? 1 : 0, v = on ? 1 : 0;
  if (was === v) return;
  try { await optWrite(optSet(() => listById(id), {tap_done: v}), () => api('PATCH', '/api/lists/' + id, {tap_done: v})); } catch { return; }
  offerUndo(on ? tr('A tap ticks the task off') : tr('A tap opens the details'), histAdd({label: tr('Tap to complete'),
    undo: async () => { await api('PATCH', '/api/lists/' + id, {tap_done: was}); await load(); render(); return {skipped: []}; },
    redo: async () => { await api('PATCH', '/api/lists/' + id, {tap_done: v}); await load(); render(); return {skipped: []}; }}));
}
