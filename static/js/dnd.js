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
const DROP_SEL = '.trow, .kcol, .quad, .cal .cell, .srow[data-drop], .wcol, .wad, .wh, #view .ghead[data-section], #view .sdrop';
// lower half of a row = drop after it (so the end of a block / list is reachable)
const dropAfter = (row, y) => { const r = row.getBoundingClientRect(); return y != null && r.height > 0 && y > r.top + r.height / 2; };
function markDrop(el, id, y) {
  $$('.dropbefore,.dropafter,.drop').forEach(x => x.classList.remove('dropbefore', 'dropafter', 'drop'));
  const tgt = el && el.closest(DROP_SEL);
  if (!tgt || tgt.closest('#detail')) return false;
  if (tgt.classList.contains('trow') && +tgt.dataset.id === id) return false;
  if (tgt.classList.contains('trow')) { if (+tgt.dataset.id !== id) tgt.classList.add(dropAfter(tgt, y) ? 'dropafter' : 'dropbefore'); const c = tgt.closest('.kcol,.quad'); if (c) c.classList.add('drop'); }
  else tgt.classList.add('drop');
  return true;
}
document.addEventListener('dragover', e => {
  if (!dragId) return;
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
  dropTask(id, e.target, e.clientY);
});
// one drop = one history step (a subtask made standalone and moved counts once)
function dropTask(id, el, clientY) { return histGroup(() => dropTask0(id, el, clientY)); }
async function dropTask0(id, el, clientY) {
  const t = S.tasks.get(id); if (!t || !el) return;
  if (!canEdit(t)) { roToast(); return; }
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
  if (sec && sec.dataset.newsec) { taskToNewSection(id); return; }  // (sec is false over a row)
  if (sec) { taskToSection(id, sec.dataset.section ? +sec.dataset.section : null); return; }
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
    if (row && +row.dataset.id !== id) {
      const target = S.tasks.get(+row.dataset.id);
      if (!target) return;
      // insert before target: sort between the target and its predecessor in the rendered order
      const mode = sortMode();
      let rows = $$('#view .trow').map(r => S.tasks.get(+r.dataset.id)).filter(x => x && x.parent_id === target.parent_id && x.id !== id);
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
  const before = snapTask(t);
  Object.assign(t, item);
  render();
  let res;
  try { res = await api('POST', '/api/tasks/reorder', {items: [item]}); } catch { /* api() showed it */ return; }
  await load(); render();
  // a move to another list or day can be undone (plain reordering not)
  const after = snapTask(S.tasks.get(id)), rev = after && (before.list_id !== after.list_id || before.due !== after.due || (before.due_time || null) !== (after.due_time || null) || (before.section_id || null) !== (after.section_id || null) || before.priority !== after.priority) && reverseOf(before, after);
  if (res?.shifted?.length) { shiftUndo(before, {...after, shifted: res.shifted}, after?.due ? tr('Date: {0}', dayLabel(after.due)) : ''); return; }
  if (rev) offerUndo(before.list_id !== after.list_id ? tr('Moved to {0}', lname(listById(after.list_id))) : (before.section_id || null) !== (after.section_id || null) && before.due === after.due ? tr('Moved to section {0}', secName(after.section_id)) : before.priority !== after.priority && before.due === after.due ? tr('Priority: {0}', tr([N_('None'), N_('Low'), '', N_('Medium'), '', N_('High')][after.priority] || N_('None'))) : after.due ? tr('Date: {0}', dayLabel(after.due)) : tr('Date removed'),
    histFields(histLabel(before, after), [[before, after, UNDO_FIELDS]], {res}));
}

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
  try { res = await api('POST', '/api/tasks/reorder', {items: [item]}); } catch { await load().catch(() => {}); render(); return; }
  await load(); render();
  const after = snapTask(S.tasks.get(id)), rev = after && reverseOf(before, after, ['section_id', 'parent_id']);
  const msg = before.parent_id ? tr('Subtask is now standalone') + ' · ' + tr('Moved to section {0}', secName(sid)) : tr('Moved to section {0}', secName(sid));
  if (rev) offerUndo(msg, histFields(tr('Moved {0} to section {1}', qn(t.title.slice(0, 40)), secName(sid)), [[before, after, ['section_id']]], {res})); else toast(msg);
}
// the sections of a list in a new order: one request (one transaction), undo sends the old order back
async function saveSectionOrder(lid, ids, msg) {
  if (!canEditList(lid)) { roToast(); return; }
  let j;
  try { j = await api('POST', `/api/lists/${lid}/sections/order`, {ids}); } catch { await load().catch(() => {}); render(); return; }
  await load(); render();
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
  await load(); render();
  const nm = qn(name.slice(0, 40));
  histAdd({label: tr('Section {0} added', nm), lids: [lid], sid: s.id,
    undo: async e => { const r = await api('DELETE', '/api/sections/' + secId(e.sid), {_prev: {name, tasks: []}}); return r.ok ? {} : {skipped: [tr('Section {0}', nm)], none: true}; },
    redo: async e => { const r = await api('POST', '/api/sections', {list_id: lid, name, sort: s.sort}); HIST.secmap.set(secId(e.sid), r.id); return {}; }});
}
async function sectionRename(sid, name) {
  const s0 = S.sections.find(x => x.id === sid); if (!s0) return;
  const old = s0.name, lid = s0.list_id;
  try { await api('PATCH', '/api/sections/' + sid, {name}); } catch { return; }
  await load(); render();
  if (old === name) return;
  const go = (to, from) => async e => { const r = await api('PATCH', '/api/sections/' + secId(e.sid), {name: to, _prev: {name: from}}); return r.conflicts?.length ? {skipped: [tr('Section {0}', qn(from.slice(0, 40)))], none: true} : {}; };
  histAdd({label: tr('Section renamed to {0}', qn(name.slice(0, 40))), lids: [lid], sid, undo: go(old, name), redo: go(name, old)});
}
async function sectionDelete(sid) {
  const s0 = S.sections.find(x => x.id === sid); if (!s0) return;
  let r;
  try { r = await api('DELETE', '/api/sections/' + sid); } catch { return; }
  await load(); render();
  const sec = r.section || {name: s0.name, sort: s0.sort, list_id: s0.list_id}, nm = qn(sec.name.slice(0, 40));
  const e = histAdd({label: tr('Section {0} deleted', nm), lids: [sec.list_id], sid, tasks: r.tasks || [],
    undo: async x => {
      const j = await api('POST', '/api/sections', {list_id: sec.list_id, name: sec.name, sort: sec.sort, tasks: x.tasks.map(rid)});
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
    await api('POST', '/api/tasks/reorder', {items: [{id, section_id: s.id, sort: 0}]});
  } catch { await load().catch(() => {}); render(); return; }
  if (['date', 'title', 'creator', 'flow', 'created', 'created_asc'].includes(sortMode()) || sortByCol(sortMode())) LS.set('sort2.' + S.route.key, 'prio');
  await load(); render();
  toast(tr('New section {0}', qn(name)), async () => {
    try {
      if (before.parent_id) await patchTask(id, {parent_id: before.parent_id});
      else await api('POST', '/api/tasks/reorder', {items: [{id, section_id: before.section_id, sort: before.sort}]});
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
const secTarget = el => el?.closest?.('#view .ghead[data-section], #view .kcol[data-kcol]');
const secOf = el => el.classList.contains('kcol') ? el.dataset.kcol : el.dataset.section;
document.addEventListener('dragstart', e => {
  const h = e.target.closest?.('[data-sdrag]'); if (!h) return;
  e.stopPropagation();
  secDrag = +h.dataset.sdrag; e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', 'section:' + secDrag);
  requestAnimationFrame(() => h.closest('.ghead, .kcol')?.classList.add('dragging'));
}, true);
document.addEventListener('dragover', e => {
  if (secDrag === null) return;
  $$('#view .dropbefore').forEach(x => x.classList.remove('dropbefore'));
  const t = secTarget(e.target); if (!t || +secOf(t) === secDrag) return;
  e.preventDefault(); t.classList.add('dropbefore');
});
document.addEventListener('drop', e => {
  if (secDrag === null) return;
  e.preventDefault(); e.stopImmediatePropagation();
  const sid = secDrag; secDrag = null;
  $$('#view .dropbefore, #view .dragging').forEach(x => x.classList.remove('dropbefore', 'dragging'));
  const t = secTarget(e.target); if (!t) return;
  const s = S.sections.find(x => x.id === sid); if (!s) return;
  const tid = secOf(t) ? +secOf(t) : null, ids = secIds(s.list_id).filter(x => x !== sid);
  ids.splice(tid ? ids.indexOf(tid) : 0, 0, sid);  // before the target ("Unassigned" = first)
  if (ids.join() !== secIds(s.list_id).join()) saveSectionOrder(s.list_id, ids);
}, true);
document.addEventListener('dragend', () => { if (secDrag !== null) { secDrag = null; $$('#view .dropbefore, #view .dragging').forEach(x => x.classList.remove('dropbefore', 'dragging')); } });
// touch: long-press a section header (list view, kanban) = move up / down
let secHold = null, secHeld = false;
document.addEventListener('touchstart', e => {
  const h = e.target.closest?.('#view .ghead[data-section], #view .khead[data-ksec]');
  const sid = h && +(h.dataset.section || h.dataset.ksec);
  if (!sid || e.target.closest('.iconbtn, .gact')) { secHold = null; return; }
  const p = e.touches[0];
  secHold = {h, sid, x: p.clientX, y: p.clientY, timer: setTimeout(() => { if (!secHold) return; secHold.fired = true; if (navigator.vibrate) navigator.vibrate(12); secHeadMenu(secHold.h, secHold.sid); }, 450)};
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
  r.style.transition = 'transform .18s'; r.style.transform = ''; r.style.background = '';
  setTimeout(() => { r.style.transition = ''; }, 200);
  if (lock !== 'x' || e?.type === 'touchcancel') return;  // 2.13.4: a cancelled swipe snaps back and does nothing
  swiped = true; setTimeout(() => { swiped = false; }, 350);
  const id = +r.dataset.id;
  if (dx > 90) toggleTask(id);
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
  document.body.classList.remove('tdrag');
}
function tdCancel() {
  if (lp) { clearTimeout(lp.timer); clearTimeout(lp.edge); kbEdgeEnd(lp); tdScrollEnd(lp); if (lp.opened) { closeSide(); $('#detail').style.visibility = ''; } }
  lp = null; tdKill();
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
function tdScroll(x, y) {
  if (!lp || !lp.active) return;
  // over the drawer / sidebar its list scrolls (lists further down are reachable), elsewhere the view
  const side = document.elementFromPoint(x, y)?.closest('#side');
  const sc = side ? (lp.ssc || (lp.ssc = tdScroller(document.elementFromPoint(x, y)))) : (lp.sc || (lp.sc = tdScroller(lp.r.isConnected ? lp.r : $('#view'))));
  if (lp.cur && lp.cur !== sc) { tdScrollEnd(lp); }
  lp.cur = sc;
  const r = sc === document.scrollingElement || sc === document.documentElement ? {top: 0, bottom: innerHeight} : sc.getBoundingClientRect();
  // the tab bar / docked add box cover the list's bottom (fixed: no offsetParent, so measured)
  const tb = Math.min(innerHeight, ...['#tabs', '#view .qdock', '#fab'].map(q => $(q)).filter(e => e && getComputedStyle(e).display !== 'none' && e.getBoundingClientRect().height > 0 && e.getBoundingClientRect().top > innerHeight / 2).map(e => e.getBoundingClientRect().top));
  const top = side ? r.top : Math.max(r.top, $('#top')?.getBoundingClientRect().bottom || 0), bot = side ? Math.min(r.bottom, innerHeight) : Math.min(r.bottom, tb, (visualViewport?.height || innerHeight));
  const v = y < top + TD_EDGE ? -TD_MAX * Math.min(1, (top + TD_EDGE - y) / TD_EDGE) : y > bot - TD_EDGE ? TD_MAX * Math.min(1, (y - (bot - TD_EDGE)) / TD_EDGE) : 0;
  lp.sv = v; lp.sx = x; lp.sy = y;
  if (v && !lp.sraf) {
    const step = () => {
      if (!lp || !lp.active || !lp.sv) { if (lp) lp.sraf = 0; return; }
      const b = sc.scrollTop; sc.scrollTop = b + lp.sv;
      if (sc.scrollTop !== b) markDrop(document.elementFromPoint(lp.sx, lp.sy), lp.id, lp.sy);
      lp.sraf = requestAnimationFrame(step);
    };
    lp.sraf = requestAnimationFrame(step);
  }
}
function tdScrollEnd(st) { if (st && st.sraf) { cancelAnimationFrame(st.sraf); st.sraf = 0; } }
document.addEventListener('touchstart', e => {
  if (lp?.active && e.touches.length > 1) return;  // a second finger while dragging: the drag goes on
  if (lp?.active || $('.ghost-drag:not(.side-ghost)')) tdCancel();  // 2.13.4: a drag whose end got lost: its ghost goes
  const r = e.target.closest('#view .trow, #view .ev, #view .wev, #detail .subs .trow');
  // 2.32.0 (#1055): while selecting, a row is dragged by its grip (at once, no long press); elsewhere a tap selects
  const grip = !!e.target.closest('.tgrip');
  if (!r || !r.dataset.id || e.target.closest('.chk, input, .caret') || (S.multiMode && !grip) || r.classList.contains('ghost')) { lp = null; return; }
  const t0 = e.touches[0];
  lp = {r, id: +r.dataset.id, x: t0.clientX, y: t0.clientY, active: false, tgt: e.target, grip};
  e.target.addEventListener('touchmove', tdMove, {passive: false});
  e.target.addEventListener('touchend', endTouchDrag);
  e.target.addEventListener('touchcancel', endTouchDrag);
  if (grip) startTouchDrag(); else lp.timer = setTimeout(startTouchDrag, 380);
}, {passive: true});
function startTouchDrag() {
  if (!lp || !S.tasks.has(lp.id)) { lp = null; return; }
  lp.active = true; swipe = null;
  const rect = lp.r.getBoundingClientRect();
  const g = lp.r.cloneNode(true);
  g.classList.add('ghost-drag');
  g.style.cssText = `position:fixed;left:${rect.left}px;top:${rect.top}px;width:${rect.width}px;z-index:95;pointer-events:none`;
  document.body.appendChild(g);
  lp.ghost = g; lp.dy = lp.y - rect.top; lp.dx0 = lp.x - rect.left;
  lp.r.classList.add('dragging');
  document.body.classList.add('tdrag');
  // 2.13.4: "Move to list…" at the top while dragging a task row: drop it there and pick the list (the drawer at the
  // left edge collides with the system's back gesture on Android)
  const t = S.tasks.get(lp.id);
  if (lp.r.matches('#view .trow') && t && canEdit(t) && S.lists.filter(l => !l.archived && canEditList(l.id)).length > 1) {
    const m = document.createElement('div'); m.id = 'tdmove'; m.className = 'tdmove'; m.innerHTML = `${ic('folder', 's')}<span>${esc(tr('Move to list'))}</span>`;
    document.body.appendChild(m);
  }
  if (navigator.vibrate) navigator.vibrate(12);
}
// 2.13.4: touch events go to the element the finger first touched. A live update that re-renders the list during a drag
// takes that element out of the page, and its touchmove / touchend no longer reach the document: the drag froze and its
// ghost stayed. So the drag also listens on that element itself (each event is handled once).
function tdMove(e) {
  if (e._td) return; e._td = 1;
  if (!lp) return;
  const t = e.touches[0];
  if (!lp.active) { if (Math.hypot(t.clientX - lp.x, t.clientY - lp.y) > 8) { clearTimeout(lp.timer); lp = null; } return; }
  e.preventDefault();
  lp.ghost.style.top = (t.clientY - lp.dy) + 'px';
  lp.ghost.style.left = (t.clientX - lp.dx0) + 'px';
  lp.lx = t.clientX; lp.ly = t.clientY;
  const mv = $('#tdmove'), onMv = !!mv && (() => { const b = mv.getBoundingClientRect(); return t.clientX >= b.left - 8 && t.clientX <= b.right + 8 && t.clientY >= b.top - 8 && t.clientY <= b.bottom + 8; })();
  if (mv) mv.classList.toggle('on', onMv);
  if (onMv) $$('.dropbefore,.dropafter,.drop').forEach(x => x.classList.remove('dropbefore', 'dropafter', 'drop'));
  else markDrop(document.elementFromPoint(t.clientX, t.clientY), lp.id, t.clientY);
  // hold at the left edge: open the list drawer so the task can be dropped on another list
  if (isMobile() && t.clientX < 26 && !$('#side').classList.contains('open')) {
    if (!lp.edge) lp.edge = setTimeout(() => { $('#side').classList.add('open'); if (S.sel) $('#detail').style.visibility = 'hidden'; lp && (lp.opened = true); }, 450);
  } else if (lp.edge && t.clientX >= 26) { clearTimeout(lp.edge); lp.edge = null; }
  if (!onMv) tdScroll(t.clientX, t.clientY); else lp.sv = 0;
  kbEdge(t.clientX, t.clientY);
  const wb = $('#wbody'); if (wb) { const r = wb.getBoundingClientRect(); if (t.clientY < r.top + 40) wb.scrollBy(0, -12); else if (t.clientY > r.bottom - 40) wb.scrollBy(0, 12); }
}
document.addEventListener('touchmove', tdMove, {passive: false});
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
      if (k.scrollLeft !== before) markDrop(document.elementFromPoint(lp.kx, lp.ky), lp.id, lp.ky);
      lp.kraf = requestAnimationFrame(step);
    };
    lp.kraf = requestAnimationFrame(step);
  }
}
function kbEdgeEnd(st) { if (st.kraf) cancelAnimationFrame(st.kraf); $('#view .kanban.kbscroll')?.classList.remove('kbscroll'); }
// a drop beside the cards of a Kanban column (the gap, the board's padding, the edge) lands in the column under the finger
function kbColAt(x) {
  const cols = $$('#view .kanban .kcol'); if (!cols.length) return null;
  let best = null, bd = Infinity;
  for (const c of cols) { const r = c.getBoundingClientRect(); if (r.right < 0 || r.left > innerWidth) continue; const d = x < r.left ? r.left - x : x > r.right ? x - r.right : 0; if (d < bd) { bd = d; best = c; } }
  return best;
}
function endTouchDrag(e) {
  if (e) { if (e._td) return; e._td = 1; }
  if (lp && lp.tgt) { lp.tgt.removeEventListener('touchmove', tdMove); lp.tgt.removeEventListener('touchend', endTouchDrag); lp.tgt.removeEventListener('touchcancel', endTouchDrag); }
  if (!lp) { if ($('.ghost-drag:not(.side-ghost)')) tdKill(); return; }
  if (e && e.touches && e.touches.length && lp.active) return;  // another finger lifted: the drag goes on
  clearTimeout(lp.timer); kbEdgeEnd(lp); tdScrollEnd(lp);
  const st = lp; lp = null;
  if (!st.active) return;
  if (e && e.cancelable) e.preventDefault();  // no click after the hold (it would close a menu opened here)
  clearTimeout(st.edge);
  const mv = $('#tdmove'), toMove = !!mv && mv.classList.contains('on') && e?.type !== 'touchcancel';
  // 2.19.0 (#667): a drop zone under the finger is read while the zones still show (tdKill hides them)
  st.ghost.remove(); st.r.classList.remove('dragging');
  const zone = st.ly != null ? document.elementFromPoint(st.lx, st.ly)?.closest?.('#view .sdrop') : null;
  tdKill();
  let el = zone || (st.ly != null ? document.elementFromPoint(st.lx, st.ly) : null);
  if (toMove) { S.kf = st.id; setTimeout(() => openPalette('move'), 0); return; }
  if (e?.type === 'touchcancel') { if (st.opened) setTimeout(() => { closeSide(); $('#detail').style.visibility = ''; }, 150); return; }
  if (st.opened) setTimeout(() => { closeSide(); $('#detail').style.visibility = ''; }, 150);
  swiped = true; setTimeout(() => { swiped = false; }, 400);
  if (el && isKanban() && !el.closest(DROP_SEL) && el.closest('#view')) el = kbColAt(st.lx) || el;  // #453 A4
  $$('.dropbefore,.dropafter,.drop').forEach(x => x.classList.remove('dropbefore', 'dropafter', 'drop'));
  if (el) dropTask(st.id, el, st.ly);
  else if (st.ly == null && st.r.closest('#view') && isKanban() && S.sections.some(x => x.list_id === S.tasks.get(st.id)?.list_id)) sectionPicker(st.r, st.id);  // held without moving: "Move to column…"
  else if (st.ly == null && st.r.matches('#view .trow') && !isKanban() && !st.grip) {
    // 2.32.0 (#1055): a long press selects the task (bar: Move, Date, Complete, More; the task's menu is under More); more
    // rows join with a tap. Was (2.25.0, UX-11): the task's menu with "Select" first
    S.multiMode = true; S.multi.add(st.id); S.multiLast = st.id; render();
  }
}
document.addEventListener('touchend', endTouchDrag);
document.addEventListener('touchcancel', endTouchDrag);
