/* Kalmido web client: Drag & drop (desktop) and swipe (touch).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ------------------------------------------------------------------ drag & drop (desktop)
let dragId = null;
document.addEventListener('dragstart', e => {
  const r = e.target.closest('.trow[draggable="true"], .cal .ev[draggable="true"], .week .ev[draggable="true"], .wev[draggable="true"]'); if (!r) return;
  dragId = +r.dataset.id; e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', String(dragId));
  // 2.19.0 (#667): the drop zones appear right after the drag began; a layout change inside dragstart can end the drag
  setTimeout(() => { if (dragId) document.body.classList.add('tdrag'); }, 0);
  requestAnimationFrame(() => r.classList.add('dragging'));
});
document.addEventListener('dragend', () => { dragId = null; DSE.v = 0; document.body.classList.remove('tdrag'); $$('.dragging,.dropbefore,.dropafter,.drop').forEach(x => x.classList.remove('dragging', 'dropbefore', 'dropafter', 'drop')); });
const DROP_SEL = '.trow, .kcol, .quad, .cal .cell, .srow[data-drop], .wcol, .wad, .wh, #view .ghead[data-section], #view .sdrop, #view .sprh[data-sprdrop]';  // 2.60.0 (#343): + the sprint header
// lower half of a row = drop after it (so the end of a block / list is reachable)
const dropAfter = (row, y) => { const r = row.getBoundingClientRect(); return y != null && r.height > 0 && y > r.top + r.height / 2; };
// 2.87.9 (#1965): the highlight changes only when the target or its half changes (dragover fires on every mouse move; the
// search for the old highlights and the restyle ran each time). A highlight someone else took away is set again.
let mdLast = null;
function markDrop(el, id, y) {
  const tgt = el && el.closest(DROP_SEL), row = tgt && tgt.classList.contains('trow');
  const ok = !!tgt && !tgt.closest('#detail') && !(row && +tgt.dataset.id === id);
  const cls = !ok ? null : row ? (dropAfter(tgt, y) ? 'dropafter' : 'dropbefore') : 'drop', col = row ? tgt.closest('.kcol,.quad') : null;
  if (cls && mdLast && mdLast.tgt === tgt && mdLast.cls === cls && tgt.classList.contains(cls) && (!col || col.classList.contains('drop'))) return true;
  mdLast = null;
  $$('.dropbefore,.dropafter,.drop').forEach(x => x.classList.remove('dropbefore', 'dropafter', 'drop'));
  if (!cls) return false;
  tgt.classList.add(cls); if (col) col.classList.add('drop');
  mdLast = {tgt, cls};
  return true;
}
document.addEventListener('dragover', e => {
  if (!dragId) return;
  if (dgOver(e, dragId)) { mdLast = null; e.preventDefault(); dsEdge(e.clientY); return; }  // 2.43.0 (#1330, #1003): Alt = dependency, a selection, the panel's drop fields
  if (markDrop(e.target, dragId, e.clientY)) e.preventDefault();
  dsEdge(e.clientY);
});
// 2.13.4: mouse drags scroll the list too, held near its top or bottom edge (the browser only scrolls the page)
const DSE = {v: 0, raf: 0};
function dsEdge(y) {
  const v = $('#view'); if (!v) return;
  const r = v.getBoundingClientRect(), E = 64, M = 14;
  DSE.v = y < r.top + E ? -M * Math.min(1, (r.top + E - y) / E) : y > r.bottom - E ? M * Math.min(1, (y - (r.bottom - E)) / E) : 0;
  if (DSE.v && !DSE.raf) {
    const step = () => { if (!dragId || !DSE.v) { DSE.raf = 0; return; } v.scrollTop += DSE.v; DSE.raf = requestAnimationFrame(step); };
    DSE.raf = requestAnimationFrame(step);
  }
}
document.addEventListener('drop', async e => {
  if (!dragId) return;
  e.preventDefault();
  const id = dragId; dragId = null;
  if (dgDrop(e, id)) return;  // 2.43.0 (#1330, #1003): dragmulti.js
  dropTask(id, e.target, e.clientY);
});
// one drop = one history step (a subtask made standalone and moved counts once)
function dropTask(id, el, clientY) { return histGroup(async () => { if (await swlDrop(id, el)) return dropTask0(id, el, clientY); }); }  // 2.138.0 D (#2060): a swimlane's value first (same step)
async function dropTask0(id, el, clientY) {
  const t = S.tasks.get(id); if (!t || !el) return;
  if (!canEdit(t) && !ml_in(t, ml_viewList())) { roToast(); return; }  // 2.71.0 B (#1459): a further list's writer moves the link
  const side = el.closest('.srow[data-drop]');
  const row = el.closest('.trow');
  const kcol = el.closest('.kcol');
  const quad = el.closest('.quad');
  const cell = el.closest('.cal .cell');
  const wcol = el.closest('.wcol'), wad = el.closest('.wad, .wh');
  const sec = !row && el.closest('#view .ghead[data-section], #view .sdrop');
  $$('.dragging,.dropbefore,.dropafter,.drop').forEach(x => x.classList.remove('dragging', 'dropbefore', 'dropafter', 'drop'));
  document.body.classList.remove('tdrag');
  if (el.closest('#detail')) return;
  if (await mbDropHook(t, el)) return;  // 2.156.0 C (#2072): the board of My tasks (its column = date / priority / list)
  if (await ml_drop(t, {sec, kcol, row, side, cell, wcol, wad, quad, y: clientY})) return;  // 2.71.0 B (#1459): in a further list only the link moves
  if (sec && sec.dataset.newsec) { taskToNewSection(id); return; }  // (sec is false over a row)
  if (sec) { taskToSection(id, sec.dataset.section ? +sec.dataset.section : null); return; }
  const sprh = el.closest('#view .sprh[data-sprdrop]');  // 2.60.0 (#343): dropped on the sprint header
  if (sprh) { spr_dropTask(id, +sprh.dataset.sprdrop); return; }
  const item = {id};
  if (side) {
    const k = side.dataset.drop;
    if (k.startsWith('l:')) item.list_id = +k.slice(2);
    else if (k === 'inbox') item.list_id = inbox().id;
    else if (k === 'today') item.due = today();
    else if (k === 'tomorrow') item.due = addDays(today(), 1);
    else if (k === 'trash') { deleteTask(id); return; }
    else if (k === 'done') { toggleTask(id); return; }
    else return;
    if (item.list_id && t.parent_id) {
      try { await patchUndoable(id, {parent_id: null, list_id: item.list_id, section_id: null}, tr('Standalone in {0}', lname(listById(item.list_id)))); } catch { return; }
      return;
    }
    if (item.list_id && item.list_id !== t.list_id) item.section_id = null;
  } else if (cell) {
    item.due = cell.dataset.day;
  } else if (wcol) {
    const y = clientY - wcol.getBoundingClientRect().top, m = Math.max(0, Math.min(23 * 60 + 45, Math.round(y / weekH() * 4) * 15));
    item.due = wcol.dataset.day; item.due_time = `${pad(Math.floor(m / 60))}:${pad(m % 60)}`;
  } else if (wad) {
    item.due = wad.dataset.day; item.due_time = null;
  } else if (quad) {
    item.priority = +quad.dataset.quad;
  } else {
    if (kcol) item.section_id = kcol.dataset.kcol ? +kcol.dataset.kcol : null;
    if (kcol && t.parent_id && !row) { try { await patchTask(id, {parent_id: null, section_id: item.section_id}); } catch { return; } toast(tr('Subtask is now standalone')); return; }
    if (row && moActive() && await moDrop(t, row, dropAfter(row, clientY))) return;  // 2.40.0 (#1344): My tasks = the own order
    if (row && +row.dataset.id !== id) {
      const target = S.tasks.get(+row.dataset.id);
      if (!target) return;
      // insert before target: sort between the target and its predecessor in the rendered order
      const mode = sortMode();
      // 2.36.2 (#1136): completed tasks shown in their section do not count as neighbours (only the target itself)
      let rows = vl_ids().map(i => S.tasks.get(i)).filter(x => x && x.parent_id === target.parent_id && x.id !== id && (x.status === 0 || x.id === target.id));  // 2.65.0 (#1825): neighbours from the data (vl_ids)
      if (mode === 'prio' && !kcol) {  // dropping into another priority block takes over that priority
        if (target.priority !== t.priority) { item.priority = target.priority; toast(tr('Priority: {0}', tr([N_('None'), N_('Low'), '', N_('Medium'), '', N_('High')][target.priority]))); }
        rows = rows.filter(x => x.priority === target.priority);
      }
      const i = rows.findIndex(x => x.id === target.id);
      if (dropAfter(row, clientY)) {  // after the target: between it and its successor
        const next = rows[i + 1];
        item.sort = next && next.list_id === target.list_id ? (target.sort + next.sort) / 2 : target.sort + 1;
      } else {
        const prev = rows[i - 1];
        item.sort = prev && prev.list_id === target.list_id ? (prev.sort + target.sort) / 2 : target.sort - 1;
      }
      if (target.list_id !== t.list_id) item.list_id = target.list_id;
      if (target.parent_id !== t.parent_id) {
        try { await patchTask(id, {parent_id: target.parent_id, ...(target.list_id !== t.list_id ? {list_id: target.list_id} : {})}); } catch { return; }
        if (!target.parent_id) toast(tr('Subtask is now standalone'));
      }
      if (!kcol) { const g = row.closest('.group')?.querySelector('.ghead[data-section]'); if (g) item.section_id = g.dataset.section ? +g.dataset.section : null; }
      if (((mode === 'date' || mode === 'title' || mode === 'creator' || mode.startsWith('created') || sortByCol(mode)) && !kcol) || mode === 'flow') LS.set('sort2.' + S.route.key, 'prio');  // a manual drop switches to prio + manual
    } else if (!kcol) return;
  }
  if (item.list_id && !canEditList(item.list_id)) { roToast(); return; }
  if (tlkHits(t, item)) { tlkToast(t); render(); return; }  // 2.36.0 (#1118): a locked task keeps its list / day / priority
  const before = snapTask(t);
  // 2.64.1 (#1817): into / out of a list with the lock: a PATCH, so the browser re-encrypts the texts on the way (reorder cannot)
  const xe2e = item.list_id && item.list_id !== t.list_id && typeof le2eOn === 'function' && (le2eOn(item.list_id) || le2eOn(t.list_id));
  if (!xe2e) { Object.assign(t, item); render(); }
  let res;
  try { res = xe2e ? await api('PATCH', `/api/tasks/${id}`, Object.fromEntries(Object.entries(item).filter(([k]) => k !== 'id'))) : await api('POST', '/api/tasks/reorder', {items: [{...item, _prev: dndPrev(before, item)}]}); } catch { /* api() showed it */ return; }
  if (res?.conflicts?.length) addConflicts(id, res.conflicts, t.title);  // 2.270.0 D (#3028): changed elsewhere meanwhile: kept
  await load(); render();
  // a move to another list or day can be undone (plain reordering not)
  const after = snapTask(S.tasks.get(id)), rev = after && (before.list_id !== after.list_id || before.due !== after.due || (before.due_time || null) !== (after.due_time || null) || (before.section_id || null) !== (after.section_id || null) || before.priority !== after.priority) && reverseOf(before, after);
  if (res?.shifted?.length) { shiftUndo(before, {...after, shifted: res.shifted}, after?.due ? tr('Date: {0}', dayLabel(after.due)) : ''); return; }
  { const wn = rev && before.list_id !== after.list_id && wsc_moveMsg(before.list_id, after.list_id, ''); if (wn) { offerUndo(wn, histFields(histLabel(before, after), [[before, after, UNDO_FIELDS]], {res})); return; } }  // 2.53.0 (#1474): Private -> organisation
  if (rev) offerUndo(before.list_id !== after.list_id ? tr('Moved to {0}', lname(listById(after.list_id))) : (before.section_id || null) !== (after.section_id || null) && before.due === after.due ? wip_msg(tr('Moved to section {0}', secName(after.section_id)), after.section_id) : before.priority !== after.priority && before.due === after.due ? tr('Priority: {0}', tr([N_('None'), N_('Low'), '', N_('Medium'), '', N_('High')][after.priority] || N_('None'))) : after.due ? tr('Date: {0}', dayLabel(after.due)) : tr('Date removed'),
    histFields(histLabel(before, after), [[before, after, UNDO_FIELDS]], {res}));
}

// 2.270.0 D (#3028): the values the drop changes as this device saw them (server: reorder _prev; the position is never one)
const dndPrev = (before, item) => Object.fromEntries(Object.keys(item).filter(k => k !== 'id' && k !== 'sort').map(k => [k, before?.[k] ?? null]));

// ---- sections (D3): drop a task onto a section header or into an empty section, reorder sections by their handle
// (list view + kanban columns, mouse), long-press on a task = "Move to section…", on a section header = move up / down
const secHandle = sid => `<span class="shandle" draggable="true" data-sdrag="${sid}" title="${esc(tr('Drag to reorder sections'))}" aria-hidden="true">${ic('grip', 's')}</span>`;
const secName = sid => sid ? (S.sections.find(x => x.id === sid)?.name || '') : tr('Unassigned');
// a task into a section, at its top; a subtask becomes a standalone task there (as in kanban); one undo
function taskToSection(id, sid) { return histGroup(() => taskToSection0(id, sid)); }
async function taskToSection0(id, sid) {
  const t = S.tasks.get(id); if (!t) return;
  if (!canEdit(t)) { roToast(); return; }
  if (sid && !S.sections.some(x => x.id === sid && x.list_id === t.list_id)) return;
  const before = snapTask(t);
  const inSec = [...S.tasks.values()].filter(x => x.list_id === t.list_id && !x.parent_id && x.status === 0 && x.id !== id && (sid ? x.section_id === sid : !S.sections.some(z => z.id === x.section_id)));
  const item = {id, section_id: sid, sort: inSec.length ? Math.min(...inSec.map(x => x.sort)) - 1 : 0};
  if (['date', 'title', 'creator', 'flow', 'created', 'created_asc'].includes(sortMode()) || sortByCol(sortMode())) LS.set('sort2.' + S.route.key, 'prio');  // a manual drop switches to prio + manual
  if (t.parent_id) { try { await patchTask(id, {parent_id: null}); } catch { return; } }
  Object.assign(t, item); render();
  let res;
  try { res = await api('POST', '/api/tasks/reorder', {items: [{...item, _prev: dndPrev(before, item)}]}); } catch { await load().catch(() => {}); render(); return; }
  if (res?.conflicts?.length) addConflicts(id, res.conflicts, t.title);  // 2.270.0 D (#3028)
  await load().catch(() => {}); render();  // CI of 2.307.4: a failed reload after the move no longer swallows the message + undo
  const after = snapTask(S.tasks.get(id)), rev = after && reverseOf(before, after, ['section_id', 'parent_id']);
  const msg = wip_msg(before.parent_id ? tr('Subtask is now standalone') + ' · ' + tr('Moved to section {0}', secName(sid)) : tr('Moved to section {0}', secName(sid)), sid);  // 2.60.0 (#1510): + over the WIP limit
  if (rev) offerUndo(msg, histFields(tr('Moved {0} to section {1}', qn(t.title.slice(0, 40)), secName(sid)), [[before, after, ['section_id']]], {res})); else toast(msg);
}
// 2.41.2 (#1501): the sections of list lid in the order ids, locally (S.sections keeps its slots; the server's sort follows)
const secPut = (lid, ids) => () => {
  const mine = S.sections.filter(s => s.list_id === lid), at = [], old = mine.map(s => s.id);
  S.sections.forEach((s, i) => { if (s.list_id === lid) at.push(i); });
  const ord = [...ids.map(i => mine.find(s => s.id === i)).filter(Boolean), ...mine.filter(s => !ids.includes(s.id))];
  ord.forEach((s, k) => { s.sort = k; S.sections[at[k]] = s; });
  return () => secPut(lid, old)();
};
// the sections of a list in a new order: one request (one transaction), undo sends the old order back
async function saveSectionOrder(lid, ids, msg) {
  if (!canEditList(lid)) { roToast(); return; }
  let j;
  const was = S.sections.filter(s => s.list_id === lid).map(s => secId(s.id));  // 2.273.0 B (#3051): the order the drag started from
  try { j = await optWrite(secPut(lid, ids), () => api('POST', `/api/lists/${lid}/sections/order`, {ids, _prev: was})); } catch { return; }  // 2.41.2 (#1501): at once
  if (!j.ok) { toast(tr('Changed in the meantime')); await load(); render(); return; }  // someone else reordered meanwhile: their order stays
  const ord = (ids2, prev) => async () => {
    const r = await api('POST', `/api/lists/${lid}/sections/order`, {ids: ids2.map(secId), _prev: prev.map(secId)});
    return {skipped: r.ok ? [] : [tr('Section order')], none: !r.ok};
  };
  offerUndo(msg || tr('Sections reordered'), histAdd({label: tr('Sections of {0} reordered', lname(listById(lid)) || ''), lids: [lid], undo: ord(j.prev, j.ids), redo: ord(j.ids, j.prev)}));
}
// sections with history steps: added, renamed, deleted (the undo brings it back with its tasks, at its old place)
async function sectionCreate(lid, name) {
  let s;
  try { s = await api('POST', '/api/sections', {list_id: lid, name}); } catch { return; }
  { const {moved, skipped, ...row} = s; if (!S.sections.some(x => x.id === row.id)) S.sections.push(row); render(); }  // 2.41.2 (#1501): the answer, no reload
  const nm = qn(name.slice(0, 40));
  histAdd({label: tr('Section {0} added', nm), lids: [lid], sid: s.id,
    undo: async e => { const r = await api('DELETE', '/api/sections/' + secId(e.sid), {_prev: {name, tasks: []}}); return r.ok ? {} : {skipped: [tr('Section {0}', nm)], none: true}; },
    redo: async e => { const r = await api('POST', '/api/sections', {list_id: lid, name, sort: s.sort}); HIST.secmap.set(secId(e.sid), r.id); return {}; }});
}
async function sectionRename(sid, name) {
  const s0 = S.sections.find(x => x.id === sid); if (!s0) return;
  const old = s0.name, lid = s0.list_id;
  try { await optWrite(optSet(() => S.sections.find(x => x.id === sid), {name}), () => api('PATCH', '/api/sections/' + sid, {name})); } catch { return; }  // 2.41.2 (#1501): at once
  if (old === name) return;
  const go = (to, from) => async e => { const r = await api('PATCH', '/api/sections/' + secId(e.sid), {name: to, _prev: {name: from}}); return r.conflicts?.length ? {skipped: [tr('Section {0}', qn(from.slice(0, 40)))], none: true} : {}; };
  histAdd({label: tr('Section renamed to {0}', qn(name.slice(0, 40))), lids: [lid], sid, undo: go(old, name), redo: go(name, old)});
}
async function sectionDelete(sid) {
  const s0 = S.sections.find(x => x.id === sid); if (!s0) return;
  let r;
  try { r = await api('DELETE', '/api/sections/' + sid); } catch { return; }
  S.sections = S.sections.filter(x => x.id !== sid);  // 2.41.2 (#1501): its tasks stay without a section; no reload
  for (const t of S.tasks.values()) if (t.section_id === sid) t.section_id = null;
  render();
  const sec = r.section || {name: s0.name, sort: s0.sort, list_id: s0.list_id}, nm = qn(sec.name.slice(0, 40));
  const e = histAdd({label: tr('Section {0} deleted', nm), lids: [sec.list_id], sid, tasks: r.tasks || [],
    undo: async x => {
      const j = await api('POST', '/api/sections', {list_id: sec.list_id, name: sec.name, sort: sec.sort, wip_limit: sec.wip_limit ?? null, tasks: x.tasks.map(rid)});
      HIST.secmap.set(secId(x.sid), j.id); x.tasks = j.moved || [];
      return {skipped: (j.skipped || []).map(t => `${histTitle(t)}: ${tr('Section')}`)};
    },
    redo: async x => {
      const j = await api('DELETE', '/api/sections/' + secId(x.sid), {_prev: {name: sec.name, tasks: x.tasks}});
      if (!j.ok) return {skipped: [tr('Section {0}', nm)], none: true};
      x.tasks = j.tasks || []; return {};
    }});
  offerUndo(tr('Section {0} deleted', nm), e);
}
const secIds = lid => S.sections.filter(x => x.list_id === lid).map(x => x.id);
async function moveSection(sid, dir) {
  const s = S.sections.find(x => x.id === sid); if (!s) return;
  const ids = secIds(s.list_id), i = ids.indexOf(sid), j = i + dir;
  if (j < 0 || j >= ids.length) return;
  [ids[i], ids[j]] = [ids[j], ids[i]];
  await saveSectionOrder(s.list_id, ids, dir < 0 ? tr('Section moved up') : tr('Section moved down'));
}
function sectionPicker(anchor, id) {
  const t = S.tasks.get(id); if (!t) return;
  if (!canEdit(t)) { roToast(); return; }
  const secs = S.sections.filter(x => x.list_id === t.list_id), add = canEditList(t.list_id);
  if (!secs.length && !add) return;
  const cur = secs.some(x => x.id === t.section_id) ? t.section_id : null;
  menu(anchor, [...(secs.length ? [{label: tr('Unassigned'), icon: 'list', on: !cur && !t.parent_id, fn: () => taskToSection(id, null)},
    ...secs.map(x => ({label: x.name, icon: 'folder', on: cur === x.id && !t.parent_id, fn: () => taskToSection(id, x.id)}))] : []),
    ...(add ? [...(secs.length ? ['-'] : []), {label: tr('New section…'), icon: 'plus', fn: () => taskToNewSection(id)}] : [])]);
}
// 2.19.0 (#667): a task into a section that does not exist yet (the "+ New section" drop zone, "Move to section…"):
// name it (prefilled), the section is created, the task lands in it; Undo puts the task back and removes the section
async function taskToNewSection(id) {
  const t = S.tasks.get(id); if (!t) return;
  if (!canEdit(t) || !canEditList(t.list_id)) { roToast(); return; }
  const name = (await askPrompt(tr('New section'), tr('New section'), {ok: tr('Create'), input: {max: 100}}))?.trim();
  if (!name) return;
  const before = {section_id: t.section_id ?? null, sort: t.sort, parent_id: t.parent_id ?? null};
  let s; try { s = await api('POST', '/api/sections', {list_id: t.list_id, name}); } catch { return; }
  try {
    if (t.parent_id) await patchTask(id, {parent_id: null});
    await api('POST', '/api/tasks/reorder', {items: [{id, section_id: s.id, sort: 0, _prev: {section_id: before.section_id}}]});  // 2.270.0 D (#3028)
  } catch { await load().catch(() => {}); render(); return; }
  if (['date', 'title', 'creator', 'flow', 'created', 'created_asc'].includes(sortMode()) || sortByCol(sortMode())) LS.set('sort2.' + S.route.key, 'prio');
  await load(); render();
  toast(tr('New section {0}', qn(name)), async () => {
    try {
      if (before.parent_id) await patchTask(id, {parent_id: before.parent_id});
      else await api('POST', '/api/tasks/reorder', {items: [{id, section_id: before.section_id, sort: before.sort, _prev: {section_id: s.id}}]});
      await api('DELETE', `/api/sections/${s.id}`);
    } catch { /* api() said it */ }
    await load(); render();
  }, 8000, tr('Undo'));
}
function secHeadMenu(anchor, sid) {
  const s = S.sections.find(x => x.id === sid); if (!s) return;
  if (!canEditList(s.list_id)) { roToast(); return; }
  const ids = secIds(s.list_id), i = ids.indexOf(sid);
  menu(anchor, [...(i > 0 ? [{label: tr('Move section up'), icon: 'left', fn: () => moveSection(sid, -1)}] : []),
    ...(i < ids.length - 1 ? [{label: tr('Move section down'), icon: 'right', fn: () => moveSection(sid, 1)}] : []),
    '-', {label: tr('Section menu…'), icon: 'dots', fn: () => sectionMenu(anchor, sid)}]);
}
let secDrag = null;
const secOf = el => el.classList.contains('kcol') ? el.dataset.kcol : el.dataset.section;
document.addEventListener('dragstart', e => {
  const h = e.target.closest?.('[data-sdrag]'); if (!h) return;
  e.stopPropagation();
  secDrag = +h.dataset.sdrag; e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', 'section:' + secDrag);
  requestAnimationFrame(() => sb_secFold(h, true));  // 2.46.1 (#1635): the section folds while it is dragged
}, true);
document.addEventListener('dragover', e => {
  if (secDrag === null) return;
  // 2.46.1 (#1635): anywhere on the sections; past the middle of the last one = the end
  const sp = sb_secSpot(e.clientX, e.clientY, e.target), ok = !!sb_secOrder(secDrag, sp);
  sb_secMark(ok ? sp : null);
  if (ok) e.preventDefault();
});
document.addEventListener('drop', e => {
  if (secDrag === null) return;
  e.preventDefault(); e.stopImmediatePropagation();
  const sid = secDrag; secDrag = null;
  const o = sb_secOrder(sid, sb_secSpot(e.clientX, e.clientY, e.target));  // 2.46.1 (#1635): before the target ("Unassigned" = first) or at the end (measured while folded)
  $$('#view .dropbefore, #view .dropafter, #view .dragging').forEach(x => x.classList.remove('dropbefore', 'dropafter', 'dragging', 'sb-secfold'));
  if (o) saveSectionOrder(o.lid, o.ids);
}, true);
document.addEventListener('dragend', () => { if (secDrag !== null) { secDrag = null; $$('#view .dropbefore, #view .dropafter, #view .dragging').forEach(x => x.classList.remove('dropbefore', 'dropafter', 'dragging', 'sb-secfold')); } });
// touch: long-press a section header (list view, kanban) = drag it (2.46.1 #1635, secdrag.js); held without moving = move up / down
let secHold = null, secHeld = false;
document.addEventListener('touchstart', e => {
  const h = e.target.closest?.('#view .ghead[data-section], #view .khead[data-ksec]');
  const sid = h && +(h.dataset.section || h.dataset.ksec);
  if (!sid || e.target.closest('.iconbtn, .gact')) { secHold = null; return; }
  const p = e.touches[0];
  secHold = {h, sid, x: p.clientX, y: p.clientY, timer: setTimeout(() => { if (!secHold) return; secHold.fired = true; if (!canEditList(S.sections.find(x => x.id === secHold.sid)?.list_id)) { secHeadMenu(secHold.h, secHold.sid); return; } sb_secHoldStart(secHold.h, secHold.sid, secHold.x, secHold.y); }, 450)};
}, {passive: true});
document.addEventListener('touchmove', e => { if (secHold && !secHold.fired && Math.hypot(e.touches[0].clientX - secHold.x, e.touches[0].clientY - secHold.y) > 8) { clearTimeout(secHold.timer); secHold = null; } }, {passive: true});
function secHoldEnd(e) {
  if (!secHold) return;
  clearTimeout(secHold.timer);
  const f = secHold.fired; secHold = null;
  if (f) { secHeld = true; setTimeout(() => { secHeld = false; }, 400); if (e.cancelable) e.preventDefault(); }
}
document.addEventListener('touchend', secHoldEnd);
document.addEventListener('touchcancel', secHoldEnd);

// ------------------------------------------------------------------ swipe (touch)
let swipe = null, swiped = false;
document.addEventListener('touchstart', e => {
  const r = e.target.closest('#view .trow'); swiped = false;
  if (!r || e.target.closest('.chk')) { swipe = null; return; }
  swipe = {r, x: e.touches[0].clientX, y: e.touches[0].clientY, dx: 0, lock: null};
}, {passive: true});
document.addEventListener('touchmove', e => {
  if (!swipe || (lp && lp.active)) return;
  const dx = e.touches[0].clientX - swipe.x, dy = e.touches[0].clientY - swipe.y;
  if (swipe.lock === null && (Math.abs(dx) > 8 || Math.abs(dy) > 8)) swipe.lock = Math.abs(dx) > Math.abs(dy) ? 'x' : 'y';
  if (swipe.lock !== 'x') return;
  swipe.dx = dx;
  swipe.r.style.transform = `translateX(${dx}px)`;
  swipe.r.style.background = dx > 60 ? 'color-mix(in srgb,var(--ok) 25%,var(--bg))' : dx < -60 ? 'color-mix(in srgb,var(--danger) 25%,var(--bg))' : 'var(--bg2)';
}, {passive: true});
function swipeEnd(e) {
  if (!swipe) return;
  const {r, dx, lock} = swipe; swipe = null;
  // 2.46.1 (#1559): a swipe that completes the task carries the row on out to the right (like a dismissed news item) instead of snapping back
  const going = lock === 'x' && dx > 90 && e?.type !== 'touchcancel' && an_on();
  r.style.transition = going ? 'transform .18s ease-in, opacity .18s ease-in' : 'transform .18s'; r.style.transform = going ? 'translateX(110%)' : ''; r.style.background = going ? r.style.background : '';
  if (going) r.style.opacity = '0';
  setTimeout(() => { r.style.transition = ''; }, 200);
  if (lock !== 'x' || e?.type === 'touchcancel') return;  // 2.13.4: a cancelled swipe snaps back and does nothing
  swiped = true; setTimeout(() => { swiped = false; }, 350);
  const id = +r.dataset.id;
  if (dx > 90) {
    const back = () => { if (going && r.isConnected) { r.style.transition = 'transform .18s, opacity .18s'; r.style.transform = ''; r.style.opacity = ''; r.style.background = ''; setTimeout(() => { r.style.transition = ''; }, 200); } };
    Promise.resolve(toggleTask(id)).then(back, back);  // the list redraws without the row; if it stayed (cancelled, error) it slides back
  }
  // 2.24.0 (UX-09 / UX-14 / UX-37): the short menu names its task, keeps the order of the task menu (date, list, …) and ends
  // with "All…"; "Move to list…" sorts the inbox
  else if (dx < -90) {  // 2.25.0 (UX-37): emptying the inbox = putting tasks into lists: there "Move to list…" leads the menu
    const inb = S.tasks.get(id)?.list_id === inbox()?.id;
    // 2.31.0 (#1056): the same entries, in two groups with a small heading (Snooze / Task), delete last and set apart
    snoozeSheet(id, r, [{head: tr('Task')}, ...(inb ? [] : [moveListItem(r, id)]), {label: tr('Completed'), icon: 'done', fn: () => toggleTask(id)}, {label: tr('All…'), icon: 'dots', fn: () => taskMenu(r, id)}, '-', {label: tr('Delete'), icon: 'trash', cls: 'flag-5', fn: () => deleteTask(id)}], true, [...(inb ? [moveListItem(r, id)] : []), {head: tr('Snooze')}]);
  }
}
document.addEventListener('touchend', swipeEnd);
document.addEventListener('touchcancel', swipeEnd);

// long press (380 ms) on a row / chip, then drag: reorder, other kanban column, quadrant, calendar day
let lp = null;
// 2.13.4: a drag that never got its touchend (a second finger, the system taking the gesture, the app going to the
// background) left its ghost on top of the list for good. Every way out of a drag ends here; a new touch first clears
// whatever is left of an old one.
function tdKill() {
  $$('.ghost-drag:not(.side-ghost)').forEach(g => g.remove());
  $('#tdmove')?.remove();
  $$('#view .trow.dragging, #view .ev.dragging, #view .wev.dragging').forEach(x => x.classList.remove('dragging'));
  $$('.dropbefore,.dropafter,.drop').forEach(x => x.classList.remove('dropbefore', 'dropafter', 'drop'));
  dgs_touchMark(null);  // 2.122.3 B (#2334): the middle mark goes too
  document.body.classList.remove('tdrag');
}
function tdCancel() {
  const d = lp; lp = null;
  if (d) { tdOff(d, true); if (drg_cur && drg_cur.d === d) drg_cancel(); }  // 2.193.0 C (#2219): the drag.js side ends too
  tdKill();
}
document.addEventListener('visibilitychange', () => { if (document.hidden && (lp?.active || $('.ghost-drag:not(.side-ghost)'))) tdCancel(); });
window.addEventListener('blur', () => { if (lp?.active) tdCancel(); });
document.addEventListener('keydown', e => { if (e.key === 'Escape' && lp?.active) { e.preventDefault(); tdCancel(); } }, true);
// 2.13.4: held near the top or bottom edge of the list, it scrolls on its own (the deeper in the edge zone, the faster),
// also while the finger stays still
const TD_EDGE = 72, TD_MAX = 16;
function tdScroller(el) {
  for (let n = el; n && n !== document.body; n = n.parentElement) {
    const cs = getComputedStyle(n);
    if (/(auto|scroll)/.test(cs.overflowY) && n.scrollHeight > n.clientHeight + 1) return n;
  }
  return document.scrollingElement || document.documentElement;
}
// 2.13.0 (#453 A4): Kanban by touch: near the left / right edge the board scrolls smoothly, the deeper in the edge zone the
// faster (at most ~1 column per second), with snapping off while dragging; it used to jump a column per touchmove (the
// mandatory snap turned every 16 px into a whole column: 3 columns in 300 ms)
const KB_EDGE = 56, KB_MAX = 5;
function kbEdge(x, y) {
  const k = $('#view .kanban'); if (!k || !lp) return;
  const r = k.getBoundingClientRect(), a = Math.max(0, r.left), b = Math.min(innerWidth, r.right);
  const v = x < a + KB_EDGE ? -KB_MAX * Math.min(1, (a + KB_EDGE - x) / KB_EDGE) : x > b - KB_EDGE ? KB_MAX * Math.min(1, (x - (b - KB_EDGE)) / KB_EDGE) : 0;
  lp.kv = v; lp.kx = x; lp.ky = y;
  if (v && !lp.kraf) {
    k.classList.add('kbscroll');
    const step = () => {
      if (!lp || !lp.active || !lp.kv || !k.isConnected) { if (lp) lp.kraf = 0; return; }
      const before = k.scrollLeft; k.scrollLeft = before + lp.kv;
      if (k.scrollLeft !== before) { const at = document.elementFromPoint(lp.kx, lp.ky); if (!dgs_touchMark(at, lp.id, lp.ky)) markDrop(at, lp.id, lp.ky); }  // 2.122.3 B (#2334)
      lp.kraf = requestAnimationFrame(step);
    };
    lp.kraf = requestAnimationFrame(step);
  }
}
function kbEdgeEnd(st) { if (st.kraf) cancelAnimationFrame(st.kraf); $('#view .kanban.kbscroll')?.classList.remove('kbscroll'); }
// a drop beside the cards of a Kanban column (the gap, the board's padding, the edge) lands in the column under the finger
function kbColAt(x, y) {
  const cols = swlColsAt(y) || $$('#view .kanban .kcol'); if (!cols.length) return null;  // 2.138.0 D (#2060): with swimlanes the lane under the finger
  let best = null, bd = Infinity;
  for (const c of cols) { const r = c.getBoundingClientRect(); if (r.right < 0 || r.left > innerWidth) continue; const d = x < r.left ? r.left - x : x > r.right ? x - r.right : 0; if (d < bd) { bd = d; best = c; } }
  return best;
}
// 2.193.0 C (#2219): the long press on a row / chip and the drag after it run on drag.js (hold = the long press, the ghost,
// auto-scroll at the list's top / bottom, Esc, a second finger cancels, no click after it); here only what is the list's:
// where a task may go and what a drop does. The swipe above stays its own: a move during the hold ends the press (a swipe
// or a scroll, never a drag), after the hold the swipe is off (lp.active).
function tdBox(sc, d = lp) {  // d: the drag (its cache: lp or a section's, secdrag.js)
  const side = !!d?.at?.closest?.('#side');
  // 2.87.9 (#1965): the view's box and the fixed bars are measured once per drag (the drawer's box each frame: it slides in)
  const page = sc === document.scrollingElement || sc === document.documentElement;
  const r = page ? {top: 0, bottom: innerHeight} : side || !d ? sc.getBoundingClientRect() : (d.scR?.sc === sc ? d.scR.r : (d.scR = {sc, r: sc.getBoundingClientRect()}).r);
  if (side || !d) return {top: r.top, bottom: Math.min(r.bottom, innerHeight)};
  // the tab bar / docked add box cover the list's bottom (fixed: no offsetParent, so measured)
  if (d.tb == null) {
    d.tb = Math.min(innerHeight, ...['#tabs', '#view .qdock', '#fab'].map(q => $(q)).filter(e => e && getComputedStyle(e).display !== 'none' && e.getBoundingClientRect().height > 0 && e.getBoundingClientRect().top > innerHeight / 2).map(e => e.getBoundingClientRect().top));
    d.topB = $('#top')?.getBoundingClientRect().bottom || 0;
  }
  return {top: Math.max(r.top, d.topB), bottom: Math.min(r.bottom, d.tb, (visualViewport?.height || innerHeight))};
}
// over the drawer / sidebar its list scrolls (lists further down are reachable), elsewhere the view; not over "Move to project"
function tdScrollEl() {
  const d = lp; if (!d || !d.active || d.onMv) return null;
  const side = d.at?.closest?.('#side');
  return side ? (d.ssc || (d.ssc = tdScroller(d.at))) : (d.sc || (d.sc = tdScroller(d.r.isConnected ? d.r : $('#view'))));
}
// the finger over "Move to project" (measured once per drag)
function tdOnMove(d, x, y) {
  const mv = $('#tdmove'), b = mv && (d.mvR || (d.mvR = mv.getBoundingClientRect()));
  return !!b && x >= b.left - 8 && x <= b.right + 8 && y >= b.top - 8 && y <= b.bottom + 8;
}
// what the finger is over; below the last open row of a list (its bottom padding, the bottom auto-scroll strip with the
// list scrolled to its end) = after that row
function tdAt(x, y) {
  const at = document.elementFromPoint(x, y);
  if (!at || at.closest(DROP_SEL) || !at.closest('#view') || isKanban() || $('#view .cal, #view .week, #wbody')) return {at, y};
  const rows = $$('#view .trow[data-id]:not(.done):not(.ghost)'), last = rows[rows.length - 1], r = last?.getBoundingClientRect();
  return r && r.height > 0 && y > r.bottom && x >= r.left && x <= r.right ? {at: last, y: r.bottom - 1, end: true} : {at, y};
}
function tdStart(t) {
  const r = t.closest?.('#view .trow, #view .ev, #view .wev, #detail .subs .trow');
  // 2.32.0 (#1055): while selecting, a row is dragged by its grip (at once, no long press); elsewhere a tap selects
  const grip = !!t.closest?.('.tgrip');
  if (!r || !r.dataset.id || t.closest('.chk, input, .caret') || (S.multiMode && !grip) || r.classList.contains('ghost')) { lp = null; return null; }
  return (lp = {r, id: +r.dataset.id, active: false, grip});
}
// the hold ended: the row lifts
function tdLift(d) {
  if (lp !== d || !S.tasks.has(d.id)) { drg_cancel(); return; }
  d.active = true; swipe = null;
  d.r.classList.add('dragging');
  document.body.classList.add('tdrag');
  // 2.13.4: "Move to list…" at the top while dragging a task row: drop it there and pick the list (the drawer at the
  // left edge collides with the system's back gesture on Android)
  const t = S.tasks.get(d.id);
  if (d.r.matches('#view .trow') && t && canEdit(t) && S.lists.filter(l => !l.archived && canEditList(l.id)).length > 1) {
    const m = document.createElement('div'); m.id = 'tdmove'; m.className = 'tdmove'; m.innerHTML = `${ic('folder', 's')}<span>${esc(tr('Move to project'))}</span>`;
    document.body.appendChild(m);
  }
  if (navigator.vibrate) navigator.vibrate(12);
}
// once per frame (drag.js raf), also after an auto-scroll step: the mark under the finger, the drawer, the board's edges
function tdOver(d, x, y) {
  if (lp !== d || !d.active) return;
  d.lx = x; d.ly = y;
  const onMv = d.onMv = tdOnMove(d, x, y), mv = $('#tdmove');
  if (mv) mv.classList.toggle('on', onMv);
  const p = tdAt(x, y); d.at = p.at;
  if (onMv) { mdLast = null; $$('.dropbefore,.dropafter,.drop').forEach(x => x.classList.remove('dropbefore', 'dropafter', 'drop')); }
  else if (!dgs_touchMark(p.at, d.id, p.y)) markDrop(p.at, d.id, p.y);  // 2.122.3 B (#2334): the middle of a row = its subtask (dragmulti.js)
  // hold at the left edge: open the list drawer so the task can be dropped on another list
  if (isMobile() && x < 26 && !$('#side').classList.contains('open')) {
    if (!d.edge) d.edge = setTimeout(() => { $('#side').classList.add('open'); if (S.sel) $('#detail').style.visibility = 'hidden'; d.opened = true; }, 450);
  } else if (d.edge && x >= 26) { clearTimeout(d.edge); d.edge = null; }
  kbEdge(x, y);
  const wb = $('#wbody'); if (wb && wb !== d.sc) { const r = d.wbR || (d.wbR = wb.getBoundingClientRect()); if (y < r.top + 40) wb.scrollBy(0, -12); else if (y > r.bottom - 40) wb.scrollBy(0, 12); }
}
// every way out of a lifted drag: the row, the drawer, the board's scrolling
function tdOff(d, now) {
  if (lp === d) lp = null;
  clearTimeout(d.edge); kbEdgeEnd(d);
  d.r.classList.remove('dragging');
  if (d.opened) { d.opened = false; const c = () => { closeSide(); $('#detail').style.visibility = ''; }; if (now) c(); else setTimeout(c, 150); }
}
function tdDrop(d, x, y) {
  if (!d.active) { if (lp === d) lp = null; return; }
  const toMove = tdOnMove(d, x, y);  // measured here: the last move may not have had its frame
  tdOff(d);
  // 2.19.0 (#667): a drop zone under the finger is read while the zones still show (tdKill hides them)
  const zone = document.elementFromPoint(x, y)?.closest?.('#view .sdrop'), p = tdAt(x, y);
  tdKill();
  let el = zone || p.at;
  if (toMove) { S.kf = d.id; setTimeout(() => openPalette('move'), 0); return; }
  swiped = true; setTimeout(() => { swiped = false; }, 400);
  if (el && isKanban() && !el.closest(DROP_SEL) && el.closest('#view')) el = kbColAt(x, y) || el;  // #453 A4
  $$('.dropbefore,.dropafter,.drop').forEach(x => x.classList.remove('dropbefore', 'dropafter', 'drop'));
  if (el && dgs_touchDrop(el, d.id, p.y)) return;  // 2.122.3 B (#2334): onto the middle of a row = its subtask
  // after the last row also when the list moves once the drop zones go (it was scrolled into their room)
  if (el) dropTask(d.id, el, zone ? y : p.end ? 1e9 : p.y);
}
// held without moving
function tdHeld(d) {
  if (!d.active) { if (lp === d) lp = null; return; }
  tdOff(d); tdKill();
  swiped = true; setTimeout(() => { swiped = false; }, 400);
  if (d.r.closest('#view') && isKanban() && S.sections.some(x => x.list_id === S.tasks.get(d.id)?.list_id)) sectionPicker(d.r, d.id);  // "Move to column…"
  else if (d.r.matches('#view .trow') && !isKanban() && !d.grip) {
    // 2.32.0 (#1055): a long press selects the task (bar: Move, Date, Complete, More; the task's menu is under More); more
    // rows join with a tap. Was (2.25.0, UX-11): the task's menu with "Select" first
    S.multiMode = true; S.multi.add(d.id); S.multiLast = d.id; render();
  }
}
document.addEventListener('touchstart', e => {
  if ((e.touches?.length || 0) > 1) return;  // a second finger: drag.js cancels the drag
  if (lp?.active || $('.ghost-drag:not(.side-ghost)')) tdCancel();  // 2.13.4: a drag whose end got lost: its ghost goes
}, {passive: true});
drg_attach(document, {
  mouse: false, onTarget: true,  // 2.13.4: a live update that redraws the list mid-drag must not cut the touch off
  hold: d => d.grip ? 0 : 380, holdMove: 8, raf: true,
  ghost: {el: d => d.r, cls: 'ghost-drag'},
  scroll: tdScrollEl, scrollBox: tdBox, edge: TD_EDGE, step: TD_MAX,
  start: tdStart, onHold: tdLift, onMove: tdOver, onDrop: tdDrop, onTap: tdHeld,
  onCancel: d => { if (!d.active) { if (lp === d) lp = null; return; } tdOff(d); tdKill(); },
});
// 2.38.0 (#1178): on a touch screen the long press on a task row (its title too) is the app's: the browser's own menu (Copy,
// Select all, Search) never opens over it. When the browser took the press away from the app (touchcancel, so no selection
// above), its menu event starts the selection instead. A mouse (also in a narrow window) keeps the browser's menu.
document.addEventListener('contextmenu', e => {
  const r = e.target.closest?.('#view .trow[data-id]');
  if (!r || !(e.pointerType ? e.pointerType === 'touch' : isTouch()) || e.target.closest('input,textarea,.ttlin')) return;
  e.preventDefault();
  const id = +r.dataset.id;
  if (lp || S.multiMode || isKanban() || !S.tasks.has(id) || r.classList.contains('ghost')) return;
  S.multiMode = true; S.multi.add(id); S.multiLast = id; render();
});
