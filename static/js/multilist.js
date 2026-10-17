/* Kalmido web client: 2.71.0 B (#1459) a task in several lists without a copy.
   The task stays one object (its own list = t.list_id decides every right); t.also = [{list_id, section_id, sort}] are
   the further lists it is shown in (only the ones this person sees). A list view shows its own tasks and the linked
   ones; there the task has the link's section / place, and dragging it changes only the link, never its own list.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

const ML_MAX = 10;
// the list the current view shows (a list or the inbox), else 0
const ml_viewList = () => { const k = S.route.key; return k.startsWith('l:') ? +k.slice(2) : k === 'inbox' ? inbox()?.id || 0 : 0; };
const ml_of = (t, lid) => !t || t.parent_id ? null : (t.also || []).find(a => a.list_id === lid) || null;
const ml_in = (t, lid) => !!ml_of(t, lid);
// the task's section in list lid: its own in its list, the link's in a further list
const ml_sec = (t, lid) => t.list_id === lid ? t.section_id : ml_of(t, lid)?.section_id ?? null;
// same workspace (organisation or private), no health list, no locked list (2.64a: lists.e2e)
const ml_okTarget = (t, l) => { const o = listById(t.list_id); return !!o && !!l && l.id !== t.list_id && (o.org_id ?? null) === (l.org_id ?? null)
  && o.life !== 'health' && l.life !== 'health' && o.e2e == null && l.e2e == null && !l.archived && canEditList(l.id); };

// the row's mark: in a further list "from <its list>", elsewhere "also in <list>" (+ more)
function ml_rowMark(t) {
  const v = ml_viewList(), al = (t.also || []).filter(a => listById(a.list_id));
  if (v && t.list_id !== v && ml_in(t, v)) {
    const n = lname(listById(t.list_id)), tip = tr('From {0}', n);
    return `<span class="mlm" title="${esc(tip)}">${ic('link', 's')}<span class="mll">${esc(tip)}</span></span>`;
  }
  if (!al.length) return '';
  const names = al.map(a => lname(listById(a.list_id))), tip = tr('Also in {0}', names.join(', '));
  const txt = names.length > 1 ? tr('Also in {0}', names[0]) + ' +' + (names.length - 1) : tip;
  return `<span class="mlm" title="${esc(tip)}">${ic('link', 's')}<span class="mll">${esc(txt)}</span></span>`;
}

// the task menu: "Show also in list…" + "Remove from <list>" per further list
function ml_menuItems(anchor, t) {
  if (!t || t.parent_id || t.id < 0 || !canEdit(t) || t.deleted_at) return [];
  const al = (t.also || []).filter(a => listById(a.list_id));
  const add = al.length < ML_MAX && S.lists.some(l => ml_okTarget(t, l) && !ml_in(t, l.id))
    ? [{label: tr('Show also in list…'), icon: 'link', fn: () => tch_listPicker(anchor, {title: tr('Show also in list'),
        filter: l => ml_okTarget(t, l) && !ml_in(t, l.id), pick: l => ml_add(t.id, l.id)})}] : [];
  return [...add, ...al.map(a => ({label: tr('Remove from {0}', lname(listById(a.list_id))), icon: 'x', fn: () => ml_remove(t.id, a.list_id)}))];
}

async function ml_req(m, tid, lid, b) {
  const r = await api(m, `/api/tasks/${tid}/links` + (m === 'POST' ? '' : '/' + lid), b);
  if (r && r.id) { putTask(r); render(); if (S.sel === tid) renderDetail(); }
  return r;
}
async function ml_add(tid, lid, quiet) {
  const t = taskById(tid);
  try { await ml_req('POST', tid, lid, {list_id: lid}); } catch { return; }  // api() said why
  const n = lname(listById(lid)), e = histAdd({label: tr('Also in {0}', n), ids: [tid], lids: [lid],
    undo: () => ml_req('DELETE', tid, lid), redo: () => ml_req('POST', tid, lid, {list_id: lid})});
  if (!quiet) offerUndo(tr('{0} is now also in {1}', qn((t?.title || '').slice(0, 40)), n), e);
}
async function ml_remove(tid, lid) {
  const t = taskById(tid), a = ml_of(t, lid), back = {list_id: lid, section_id: a?.section_id ?? null, ...(a ? {sort: a.sort} : {})};
  try { await ml_req('DELETE', tid, lid); } catch { return; }
  const n = lname(listById(lid)), e = histAdd({label: tr('Removed from {0}', n), ids: [tid], lids: [lid],
    undo: () => ml_req('POST', tid, lid, back), redo: () => ml_req('DELETE', tid, lid)});
  offerUndo(tr('Removed from {0}', n), e);
}

// drag & drop in a further list: only the link's section / place changes (true = handled). A drop on the sidebar or a
// calendar keeps the usual meaning (an explicit target).
async function ml_drop(t, o) {
  const v = ml_viewList(), a = ml_of(t, v);
  if (!v || !a || t.list_id === v || o.side || o.cell || o.wcol || o.wad || o.quad) return false;
  if (!canEditList(v)) { roToast(); return true; }
  const b = {};
  if (o.sec && !o.sec.dataset.newsec) b.section_id = o.sec.dataset.section ? +o.sec.dataset.section : null;
  else if (o.kcol) b.section_id = o.kcol.dataset.kcol ? +o.kcol.dataset.kcol : null;
  else if (o.row) { const g = o.row.closest('.group')?.querySelector('.ghead[data-section]'); if (g) b.section_id = g.dataset.section ? +g.dataset.section : null; }
  const tg = o.row && S.tasks.get(+o.row.dataset.id);
  if (tg && tg.id !== t.id) b.sort = ml_sortOf(tg, v) + (dropAfter(o.row, o.y) ? 0.5 : -0.5);
  if (!Object.keys(b).length) return true;
  const prev = {section_id: a.section_id ?? null, sort: a.sort};
  try { await api('PATCH', `/api/tasks/${t.id}/links/${v}`, b).then(r => { if (r?.id) putTask(r); }); } catch { render(); return true; }
  render();
  const put = x => () => api('PATCH', `/api/tasks/${t.id}/links/${v}`, x).then(r => { if (r?.id) putTask(r); });
  if ('section_id' in b && b.section_id !== prev.section_id) offerUndo(tr('Moved to section {0}', secName(b.section_id)), histAdd({label: tr('Moved to section {0}', secName(b.section_id)), ids: [t.id], lids: [v], undo: put(prev), redo: put(b)}));
  return true;
}
// the place of a task in list lid (its own sort there, the link's in a further list)
const ml_sortOf = (t, lid) => t.list_id === lid ? t.sort : ml_of(t, lid)?.sort ?? t.sort;
