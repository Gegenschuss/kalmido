/* Kalmido web client: Dependencies by dragging (#1330) and several selected tasks moved at once (#1003).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md).
   Loaded after dnd.js: its drag handlers ask dgOver / dgDrop first. */
'use strict';

// ------------------------------------------------------------------ 2.43.0 (#1330): dependencies by dragging
// Desktop: a task dragged with Alt (Option) held onto another task waits on it; the target row shows "Waits on this task"
// instead of the insert line (pressing / releasing the key during the drag switches). With a selection every selected
// task waits on it. While a task is dragged, the dependencies of the open task panel show two drop fields: "Waiting on"
// (the open task waits on the dragged one) and "Blocking" (the dragged one waits on the open task). One drop = one history
// step with Undo; the server refuses loops and names both tasks. Phone: no dragging, "Waiting on a task…" in the
// long-press menu picks the task with the task search.
// ------------------------------------------------------------------ 2.43.0 (#1003): several tasks at once
// A drag that starts on a selected row takes the whole selection (badge "3 tasks" on the drag image). Upper / lower part of
// a row = the block goes before / after it (order kept), the middle = they become its subtasks (at most maxDepth() levels: a
// task whose own subtasks would go deeper stays, the message counts it). A section header, a kanban column or a list in
// the sidebar takes them as standalone tasks. One batch request = one Undo. Without dragging: the multi panel and the
// phone's selection menu have "Subtasks of…" and "Out of the parent task".
const DG = {ids: null, zones: false};
const dgShort = s => { s = String(s || ''); return s.length > 40 ? s.slice(0, 39) + '…' : s; };
const dgRowsOrder = () => new Map(vl_ids().map((id, i) => [id, i]));  // 2.65.0 (#1825): also the rows a long list does not draw
// the ids in the order the user sees them (rows on screen first, then by sort)
function dgOrder(ids) {
  const pos = dgRowsOrder(), big = 1e9;
  return [...ids].filter(i => S.tasks.get(i)).sort((a, b) => (pos.get(a) ?? big) - (pos.get(b) ?? big) || (S.tasks.get(a).sort || 0) - (S.tasks.get(b).sort || 0));
}
function dgAncestors(id) { const out = []; let p = S.tasks.get(id)?.parent_id; for (let n = 0; p && n < 10; n++) { out.push(p); p = S.tasks.get(p)?.parent_id; } return out; }
// a selected task whose parent (any level) is selected too moves with that parent
const dgRoots = ids => { const set = new Set(ids); return ids.filter(i => !dgAncestors(i).some(a => set.has(a))); };
function dgHeight(id, n = 0) { const k = children(id); return !k.length || n > 6 ? 0 : 1 + Math.max(...k.map(x => dgHeight(x.id, n + 1))); }
const dgFits = (pid, id) => depthOf(S.tasks.get(pid)) + 1 + dgHeight(id) < maxDepth();

// ---- dependencies
function dgDepOk(w, b) {
  const wt = S.tasks.get(w), bt = S.tasks.get(b);
  return !!wt && !!bt && w !== b && w > 0 && b > 0 && canEdit(wt) && dFor(wt) && dFor(bt);
}
// pairs [[waiting, blocker], ...]: added one by one (the server checks rights and loops), one history step for all
async function dgDepAdd(pairs) {
  const ok = [], errs = [];
  for (const [w, b] of pairs) {
    if ((S.tasks.get(w)?.blockers || []).includes(b)) continue;
    try { await api('POST', '/api/deps', {task_id: w, blocker_id: b}); ok.push([w, b]); } catch (e) { errs.push(e?.message || ''); }
  }
  if (!ok.length) { if (!errs.length) toast(tr('Already waiting on it')); return; }
  await load(); render();
  if (S.sel && ok.some(p => p.includes(S.sel))) loadDeps(S.sel);
  const [w0, b0] = ok[0], tw = S.tasks.get(w0), tb = S.tasks.get(b0);
  const lab = ok.length === 1 ? tr('“{0}” waits on “{1}”', dgShort(tw?.title), dgShort(tb?.title)) : trn('{0} task waits on “{1}”', '{0} tasks wait on “{1}”', ok.length, dgShort(tb?.title));
  const go = add => async () => {
    const skipped = [];
    for (const [w, b] of ok) {
      try { await api(add ? 'POST' : 'DELETE', add ? '/api/deps' : `/api/deps/${rid(w)}/${rid(b)}`, add ? {task_id: rid(w), blocker_id: rid(b)} : undefined); } catch { skipped.push(histTitle(w)); }
    }
    return {skipped, none: skipped.length === ok.length};
  };
  const ids = [...new Set(ok.flat())];
  const e = histAdd({label: lab, snaps: ids.map(i => snapTask(S.tasks.get(i))).filter(Boolean), ids, undo: go(false), redo: go(true),
    post: () => { if (S.sel && ids.includes(S.sel)) loadDeps(S.sel); }});
  offerUndo(errs.length ? lab + ' · ' + trn('{0} not possible', '{0} not possible', errs.length) + (errs[0] ? ': ' + errs[0] : '') : lab, e);
}
// the phone's way (and the menu's): "Waiting on a task…" with the task search
function dgDepPick(id) {
  const t = S.tasks.get(id); if (!t) return;
  dgPick({title: tr('Waiting on a task…'), hint: tr('“{0}” can only really start once the chosen task is done.', t.title),
    filter: x => x.id !== id && dFor(x) && !(t.blockers || []).includes(x.id) && !tlReaches(x.id, id), near: t,
    pick: x => dgDepAdd([[id, x.id]])});
}
// a task search in a dialog (the look of every task picker, .tpk): this list first, then the others under their name
function dgPick(o) {
  const md = modal(`<h3>${esc(o.title)}</h3>${o.hint ? `<div class="shint keep">${esc(o.hint)}</div>` : ''}
    <input id="dg-q" placeholder="${esc(tr('Search open tasks'))}" autocomplete="off" style="width:100%;margin-top:.5rem">
    <div class="dplist tpk" id="dg-list" role="listbox" aria-label="${esc(tr('Open tasks'))}"></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button></div>`);
  md.classList.add('dpmodal', 'dgpick');
  const self = o.near;
  const draw = () => {
    const q = norm($('#dg-q', md).value || '');
    const arr = openTasks().filter(x => x.id > 0 && o.filter(x) && (!q || norm(x.title).includes(q)))
      .sort((a, b) => (b.list_id === self?.list_id) - (a.list_id === self?.list_id) || (a.due || '9999').localeCompare(b.due || '9999') || bySort(a, b)).slice(0, 60);
    const row = x => `<button type="button" class="tpkrow" role="option" data-pick="${x.id}"><span class="tpkt">${esc(x.title)}</span><span class="tpkm">${esc(lname(listById(x.list_id)))}${x.due ? ' · ' + esc(dayLabel(x.due)) : ''}</span></button>`;
    const same = arr.filter(x => x.list_id === self?.list_id), others = arr.filter(x => x.list_id !== self?.list_id);
    $('#dg-list', md).innerHTML = !arr.length ? `<div class="muted mhint">${tr('No matching open task.')}</div>`
      : (same.length ? `<div class="tpkg" role="group" aria-label="${esc(tr('This project'))}"><div class="tpkh">${esc(tr('This project'))}</div>${same.map(row).join('')}</div>` : '')
        + [...new Set(others.map(x => x.list_id))].map(lid => `<div class="tpkg" role="group" aria-label="${esc(lname(listById(lid)))}"><div class="tpkh">${esc(lname(listById(lid)))}</div>${others.filter(x => x.list_id === lid).map(row).join('')}</div>`).join('');
  };
  draw();
  md.addEventListener('input', e => { if (e.target.id === 'dg-q') draw(); });
  md.addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    if (b.dataset.pick) { const x = S.tasks.get(+b.dataset.pick); md.remove(); if (x) o.pick(x); }
  });
  setTimeout(() => { if (!isMobile()) $('#dg-q', md).focus(); }, 50);
}

// ---- several tasks: one patch_each batch = one history step
async function dgApply(items, lab, notes = []) {
  const ids = Object.keys(items).map(Number);
  if (!ids.length) { toast(notes.filter(Boolean).join(' · ') || tr('Nothing to move')); return null; }
  const snaps = ids.flatMap(withKids);
  let j;
  try { j = await api('POST', '/api/tasks/batch', {ids, action: 'patch_each', data: {items}}); } catch { await load().catch(() => {}); render(); return null; }
  await load(); render();
  const pairs = snaps.filter(b => ids.includes(b.id)).map(b => [b, snapTask(S.tasks.get(b.id))]);
  const e = histFields(lab, pairs, {res: j, fields: [...UNDO_FIELDS, 'sort']});
  const fail = ids.length - (j?.count ?? ids.length);
  const msg = [lab, fail ? trn('{0} task not changed', '{0} tasks not changed', fail) + (j?.errors?.[0] ? ': ' + j.errors[0] : '') : '', ...notes].filter(Boolean).join(' · ');
  if (e) offerUndo(msg, e); else toast(msg);
  return j;
}
// the selected tasks become subtasks of pid, after its own subtasks, in their order
async function dgMakeSubs(ids, pid) {
  const p = S.tasks.get(pid); if (!p) return;
  if (!canEdit(p)) { roToast(); return; }
  if (isMs(p)) { toast(tr('A milestone cannot have subtasks')); return; }
  const set = new Set(ids);
  if (set.has(pid) || dgAncestors(pid).some(a => set.has(a))) { toast(tr('A task cannot be nested under itself')); return; }
  let list = dgRoots(dgOrder(ids));
  const ro = list.filter(i => !canEdit(S.tasks.get(i))), ms = list.filter(i => isMs(S.tasks.get(i)) && !ro.includes(i));
  list = list.filter(i => !ro.includes(i) && !ms.includes(i));
  const deep = list.filter(i => !dgFits(pid, i));
  list = list.filter(i => !deep.includes(i));
  const kids = children(pid).filter(k => !set.has(k.id));
  const s0 = kids.length ? Math.max(...kids.map(k => k.sort || 0)) + 1 : 0;
  const items = {};
  list.forEach((i, k) => { items[i] = {parent_id: pid, sort: s0 + k}; });
  const notes = [deep.length ? trn('{0} task stays: its own subtasks would go deeper than {1} levels', '{0} tasks stay: their own subtasks would go deeper than {1} levels', deep.length, maxDepth()) : '',
    ro.length ? trn('{0} task skipped (view only)', '{0} tasks skipped (view only)', ro.length) : '',
    ms.length ? tr('A milestone cannot be a subtask') : ''];
  return dgApply(items, trn('{0} task is now a subtask of “{1}”', '{0} tasks are now subtasks of “{1}”', list.length, dgShort(p.title)), notes);
}
// out of the parent task: standalone right after the main task they were under (same section), order kept
async function dgDetach(ids) {
  const list = dgOrder(ids).filter(i => S.tasks.get(i)?.parent_id), ro = list.filter(i => !canEdit(S.tasks.get(i)));
  const may = list.filter(i => !ro.includes(i));
  if (!list.length) { toast(tr('None of them is a subtask')); return; }
  const top = i => { const a = dgAncestors(i); return S.tasks.get(a[a.length - 1]); };
  const items = {}, byTop = new Map();
  for (const i of may) { const tp = top(i); if (!tp) continue; if (!byTop.has(tp.id)) byTop.set(tp.id, []); byTop.get(tp.id).push(i); }
  for (const [tid, arr] of byTop) {
    const tp = S.tasks.get(tid);
    const nexts = [...S.tasks.values()].filter(x => x.list_id === tp.list_id && !x.parent_id && x.id !== tid && (x.section_id || null) === (tp.section_id || null) && (x.sort || 0) > (tp.sort || 0) && !may.includes(x.id));
    const hi = nexts.length ? Math.min(...nexts.map(x => x.sort || 0)) : (tp.sort || 0) + arr.length + 1;
    arr.forEach((i, k) => { items[i] = {parent_id: null, section_id: tp.section_id || null, sort: (tp.sort || 0) + (hi - (tp.sort || 0)) * (k + 1) / (arr.length + 1)}; });
  }
  return dgApply(items, trn('{0} subtask is now standalone', '{0} subtasks are now standalone', Object.keys(items).length),
    [ro.length ? trn('{0} task skipped (view only)', '{0} tasks skipped (view only)', ro.length) : '']);
}
// "Subtasks of…": the task search, without the selection and what is under it, only where another level fits
function dgSubPick(ids) {
  const set = new Set(ids), roots = dgRoots(ids);
  dgPick({title: tr('Subtasks of…'), hint: trn('The {0} selected task becomes a subtask of the chosen task.', 'The {0} selected tasks become subtasks of the chosen task.', roots.length),
    near: S.tasks.get(roots[0]),
    filter: x => !set.has(x.id) && !dgAncestors(x.id).some(a => set.has(a)) && canEdit(x) && !isMs(x) && depthOf(x) < maxDepth() - 1,
    pick: x => dgMakeSubs(ids, x.id)});
}
// a block before / after a row: the same parent, list and section as the row, sorted between it and its neighbour
async function dgBlock(ids, row, after) {
  const target = S.tasks.get(+row.dataset.id); if (!target) return;
  const set = new Set(ids), kcol = row.closest('.kcol');
  if (set.has(target.id) || dgAncestors(target.id).some(a => set.has(a))) return;
  let list = dgRoots(dgOrder(ids));
  const ro = list.filter(i => !canEdit(S.tasks.get(i)));
  list = list.filter(i => !ro.includes(i));
  const deep = target.parent_id ? list.filter(i => !dgFits(target.parent_id, i)) : [];
  list = list.filter(i => !deep.includes(i));
  if (target.list_id && list.some(i => S.tasks.get(i).list_id !== target.list_id) && !canEditList(target.list_id)) { roToast(); return; }
  const mode = sortMode();
  let rows = vl_ids().map(i => S.tasks.get(i)).filter(x => x && x.parent_id === target.parent_id && !set.has(x.id) && (x.status === 0 || x.id === target.id));
  if (mode === 'prio' && !kcol) rows = rows.filter(x => x.priority === target.priority);
  const i = rows.findIndex(x => x.id === target.id), n = list.length;
  let lo, hi;
  if (after) { const nx = rows[i + 1]; lo = target.sort; hi = nx && nx.list_id === target.list_id ? nx.sort : target.sort + n + 1; }
  else { const pv = rows[i - 1]; hi = target.sort; lo = pv && pv.list_id === target.list_id ? pv.sort : target.sort - n - 1; }
  const g = !kcol && row.closest('.group')?.querySelector('.ghead[data-section]');
  const sec = target.parent_id ? undefined : kcol ? (kcol.dataset.kcol ? +kcol.dataset.kcol : null) : g ? (g.dataset.section ? +g.dataset.section : null) : target.section_id ?? null;
  const items = {};
  list.forEach((id, k) => {
    const t = S.tasks.get(id), it = {sort: lo + (hi - lo) * (k + 1) / (n + 1)};
    if ((t.parent_id || null) !== (target.parent_id || null)) it.parent_id = target.parent_id || null;
    if (!target.parent_id && t.list_id !== target.list_id) it.list_id = target.list_id;
    if (sec !== undefined && (t.section_id || null) !== sec) it.section_id = sec;
    if (mode === 'prio' && !kcol && t.priority !== target.priority) it.priority = target.priority;
    items[id] = it;
  });
  if (((mode === 'date' || mode === 'title' || mode === 'creator' || mode.startsWith('created') || sortByCol(mode)) && !kcol) || mode === 'flow') LS.set('sort2.' + S.route.key, 'prio');  // a manual drop: prio + manual (as one task)
  return dgApply(items, trn('{0} task moved', '{0} tasks moved', n), [deep.length ? trn('{0} task stays: its own subtasks would go deeper than {1} levels', '{0} tasks stay: their own subtasks would go deeper than {1} levels', deep.length, maxDepth()) : '',
    ro.length ? trn('{0} task skipped (view only)', '{0} tasks skipped (view only)', ro.length) : '']);
}
// into a section / kanban column of a list as standalone tasks, at its top, order kept
async function dgToSection(ids, lid, sid) {
  if (!canEditList(lid)) { roToast(); return; }
  let list = dgRoots(dgOrder(ids));
  const ro = list.filter(i => !canEdit(S.tasks.get(i)));
  list = list.filter(i => !ro.includes(i));
  const inSec = [...S.tasks.values()].filter(x => x.list_id === lid && !x.parent_id && x.status === 0 && !list.includes(x.id) && (sid ? x.section_id === sid : !S.sections.some(z => z.id === x.section_id)));
  const top = inSec.length ? Math.min(...inSec.map(x => x.sort || 0)) : 0;
  const items = {};
  list.forEach((id, k) => { const t = S.tasks.get(id); items[id] = {parent_id: null, section_id: sid, sort: top - list.length + k, ...(t.list_id !== lid ? {list_id: lid} : {})}; });
  if (['date', 'title', 'creator', 'flow', 'created', 'created_asc'].includes(sortMode()) || sortByCol(sortMode())) LS.set('sort2.' + S.route.key, 'prio');
  return dgApply(items, trn('{0} task moved to section {1}', '{0} tasks moved to section {1}', list.length, secName(sid)),
    [ro.length ? trn('{0} task skipped (view only)', '{0} tasks skipped (view only)', ro.length) : '']);
}
async function dgToNewSection(ids) {
  const lid = S.tasks.get(ids[0])?.list_id; if (!lid) return;
  if (!canEditList(lid)) { roToast(); return; }
  const name = (await askPrompt(tr('New section'), tr('New section'), {ok: tr('Create'), input: {max: 100}}))?.trim();
  if (!name) return;
  return histGroup(async () => {
    const had = new Set(S.sections.map(s => s.id));
    await sectionCreate(lid, name);
    const s = S.sections.find(x => x.list_id === lid && !had.has(x.id));
    if (s) await dgToSection(ids, lid, s.id);
  });
}
// a list in the sidebar: standalone tasks there (subtasks leave their parent)
async function dgToList(ids, lid) {
  if (!canEditList(lid)) { roToast(); return; }
  let list = dgRoots(dgOrder(ids));
  const ro = list.filter(i => !canEdit(S.tasks.get(i)));
  list = list.filter(i => !ro.includes(i));
  const items = {};
  for (const id of list) { const t = S.tasks.get(id); if (t.list_id !== lid || t.parent_id) items[id] = {list_id: lid, ...(t.list_id !== lid ? {section_id: null} : {}), ...(t.parent_id ? {parent_id: null} : {})}; }
  return dgApply(items, trn('Moved {0} task to {1}', 'Moved {0} tasks to {1}', Object.keys(items).length, lname(listById(lid)) || '?'),
    [ro.length ? trn('{0} task skipped (view only)', '{0} tasks skipped (view only)', ro.length) : '']);
}

// ---- dragging (desktop); dnd.js asks dgOver on every dragover and dgDrop on the drop
const dgZone = (row, y) => { const r = row.getBoundingClientRect(), f = r.height > 0 ? (y - r.top) / r.height : .5; return f < .28 ? 'before' : f > .72 ? 'after' : 'onto'; };
function dgClear() { $$('.dgdep,.dgonto,.dgno').forEach(x => { x.classList.remove('dgdep', 'dgonto', 'dgno'); delete x.dataset.dg; }); $$('.dgzone.drop').forEach(x => x.classList.remove('drop')); }
function dgMark(el, cls, text) { el.classList.add(cls); el.dataset.dg = text; }
// true = handled here (the caller then allows the drop)
// 2.87.9 (#1965): moving a selection over the same third of the same row changes nothing (no search, no restyle)
let dgLast = null;
function dgOver(e, id) {
  const lr = dgLast && !e.altKey && (DG.ids || dgLast.one) && !e.target.closest?.('.dgzone') && e.target.closest?.('#view .trow');
  if (lr && lr === dgLast.row && lr.isConnected && dgZone(lr, e.clientY) === dgLast.zn && lr.classList.contains(dgLast.cls)) return true;
  dgLast = null;
  dgClear();
  const z = e.target.closest?.('.dgzone');
  if (z) { $$('.dropbefore,.dropafter,.drop').forEach(x => x.classList.remove('dropbefore', 'dropafter', 'drop')); if (z.classList.contains('dgoff')) return false; z.classList.add('drop'); e.dataTransfer.dropEffect = 'link'; return true; }
  const row = e.target.closest?.('#view .trow');
  if (!row || row.closest('#detail')) return false;
  const tid = +row.dataset.id, ids = DG.ids || [id];
  if (ids.includes(tid)) return false;
  if (e.altKey) {
    $$('.dropbefore,.dropafter,.drop').forEach(x => x.classList.remove('dropbefore', 'dropafter', 'drop'));
    const bad = ids.find(w => !dgDepOk(w, tid));
    if (bad !== undefined) dgMark(row, 'dgno', !dFor(S.tasks.get(tid)) || !dFor(S.tasks.get(bad)) ? tr('Dependencies only between tasks of projects') : tr('No permission'));
    else if (ids.some(w => tlReaches(tid, w))) dgMark(row, 'dgno', tr('Not possible: that would be a loop'));
    else dgMark(row, 'dgdep', ids.length > 1 ? trn('{0} task waits on this one', '{0} tasks wait on this one', ids.length) : tr('Waits on this task'));
    e.dataTransfer.dropEffect = 'link';
    return true;
  }
  if (!DG.ids) return dgs_over(e, row, id, tid);  // 2.122.3 B (#2334): one task, the middle of a row
  $$('.dropbefore,.dropafter,.drop').forEach(x => x.classList.remove('dropbefore', 'dropafter', 'drop'));
  const zn = dgZone(row, e.clientY);
  if (zn === 'onto') dgMark(row, 'dgonto', trn('{0} task becomes its subtask', '{0} tasks become its subtasks', dgRoots(ids).length));
  else row.classList.add(zn === 'after' ? 'dropafter' : 'dropbefore');
  dgLast = {row, zn, cls: zn === 'onto' ? 'dgonto' : zn === 'after' ? 'dropafter' : 'dropbefore'};
  return true;
}
// true = handled here (dnd.js does nothing more)
function dgDrop(e, id) {
  const el = e.target, ids = DG.ids, y = e.clientY, alt = e.altKey;
  const z = el.closest?.('.dgzone'), row = el.closest?.('#view .trow');
  const end = () => { dgClear(); dgEnd(); $$('.dragging,.dropbefore,.dropafter,.drop').forEach(x => x.classList.remove('dragging', 'dropbefore', 'dropafter', 'drop')); document.body.classList.remove('tdrag'); };
  if (z) {
    end();
    if (z.classList.contains('dgoff') || !S.sel || S.sel === id) return true;
    const w = z.dataset.dgz === 'by' ? S.sel : id, b = z.dataset.dgz === 'by' ? id : S.sel;
    if (!dgDepOk(w, b)) { roToast(); return true; }
    dgDepAdd([[w, b]]);
    return true;
  }
  if (alt && row && !row.closest('#detail')) {
    const tid = +row.dataset.id, ws = (ids || [id]).filter(w => w !== tid);
    end();
    const ok = ws.filter(w => dgDepOk(w, tid));
    if (!ok.length) { toast(!dFor(S.tasks.get(tid)) ? tr('Dependencies only between tasks of projects') : tr('No permission')); return true; }
    dgDepAdd(ok.map(w => [w, tid]));
    return true;
  }
  if (!ids && row && !row.closest('#detail') && dgs_mid(row, y) && dgs_ok(id, +row.dataset.id)) { end(); dgMakeSubs([id], +row.dataset.id); return true; }  // 2.122.3 B (#2334)
  if (!ids) return false;
  end();
  if (el.closest?.('#detail')) return true;
  const side = el.closest?.('.srow[data-drop]'), kcol = el.closest?.('.kcol'), quad = el.closest?.('.quad'), cell = el.closest?.('.cal .cell');
  const wcol = el.closest?.('.wcol'), wad = el.closest?.('.wad, .wh'), sec = !row && el.closest?.('#view .ghead[data-section], #view .sdrop');
  const may = ids.filter(i => canEdit(S.tasks.get(i)));
  if (!may.length) { roToast(); return true; }
  if (side) {
    const k = side.dataset.drop;
    if (k.startsWith('l:')) dgToList(ids, +k.slice(2));
    else if (k === 'inbox') dgToList(ids, inbox().id);
    else if (k === 'today' || k === 'tomorrow') batch('patch', {due: k === 'today' ? today() : addDays(today(), 1)}, false, may);
    else if (k === 'trash') batch('delete', {}, true, may);
    else if (k === 'done') batch('complete', {}, false, may);
    return true;
  }
  if (sec) {
    if (sec.dataset.newsec) { dgToNewSection(ids); return true; }
    const sid = sec.dataset.section ? +sec.dataset.section : null;
    const lid = sid ? S.sections.find(s => s.id === sid)?.list_id : S.tasks.get(ids[0])?.list_id;
    if (lid) dgToSection(ids, lid, sid);
    return true;
  }
  if (row) {
    const tid = +row.dataset.id;
    if (ids.includes(tid)) return true;
    const zn = dgZone(row, y);
    if (zn === 'onto') dgMakeSubs(ids, tid);
    else if (moActive()) { DG.ids = null; return false; }  // My tasks keeps its own order: the dragged task alone (2.40.0, #1344)
    else dgBlock(ids, row, zn === 'after');
    return true;
  }
  if (kcol && kcol.dataset.mbcol != null) { DG.ids = null; return false; }  // 2.156.0 C (#2072): the board of My tasks: the dragged task alone
  if (kcol) { const sid = kcol.dataset.kcol ? +kcol.dataset.kcol : null, lid = S.tasks.get(ids[0])?.list_id; if (lid) dgToSection(ids, lid, sid); return true; }
  if (cell) { batch('patch', {due: cell.dataset.day}, false, may); return true; }
  if (wad) { batch('patch', {due: wad.dataset.day, due_time: null}, false, may); return true; }
  if (wcol) {
    const m = Math.max(0, Math.min(23 * 60 + 45, Math.round((y - wcol.getBoundingClientRect().top) / weekH() * 4) * 15));
    batch('patch', {due: wcol.dataset.day, due_time: `${pad(Math.floor(m / 60))}:${pad(m % 60)}`}, false, may);
    return true;
  }
  if (quad) { batch('patch', {priority: +quad.dataset.quad}, false, may); return true; }
  return true;
}
// 2.122.3 B (#2334): a single dragged task (mouse or finger) onto the middle of another becomes its subtask, as a
// selection does (dgMakeSubs: one batch, one Undo). Only where it may: both editable, no milestone, not under itself or
// its own subtask, not already there, the depth fits, no move into / out of a list with the lock (that needs a PATCH).
// Elsewhere (and the upper / lower part of a row) dnd.js moves it as before.
function dgs_ok(id, tid) {
  const t = S.tasks.get(id), p = S.tasks.get(tid);
  if (!t || !p || id <= 0 || tid <= 0 || id === tid || t.context || p.context || !canEdit(t) || !canEdit(p) || isMs(t) || isMs(p)) return false;
  if (t.parent_id === tid || dgAncestors(tid).includes(id) || !dgFits(tid, id)) return false;
  return t.list_id === p.list_id || !(typeof le2eOn === 'function' && (le2eOn(t.list_id) || le2eOn(p.list_id)));
}
// the middle of a row that has a size (a row without one keeps the old halves)
const dgs_mid = (row, y) => row.getBoundingClientRect().height > 0 && dgZone(row, y) === 'onto';
function dgs_over(e, row, id, tid) {
  if (!dgs_mid(row, e.clientY) || !dgs_ok(id, tid)) return false;
  $$('.dropbefore,.dropafter,.drop').forEach(x => x.classList.remove('dropbefore', 'dropafter', 'drop'));
  dgMark(row, 'dgonto', tr('As a subtask of this task'));
  dgLast = {row, zn: 'onto', cls: 'dgonto', one: true};
  return true;
}
// the finger's drag (dnd.js, once per frame): true = the middle of a row is marked here, else dnd.js marks before / after
let dgsRow = null;
function dgs_touchMark(at, id, y) {
  const row = at?.closest?.('#view .trow'), on = !!row && !row.closest('#detail') && dgs_mid(row, y) && dgs_ok(id, +row.dataset.id);
  if (on && row === dgsRow && row.classList.contains('dgonto')) return true;
  if (dgsRow) { dgsRow.classList.remove('dgonto'); delete dgsRow.dataset.dg; dgsRow = null; }
  if (!on) return false;
  $$('.dropbefore,.dropafter,.drop').forEach(x => x.classList.remove('dropbefore', 'dropafter', 'drop'));
  dgMark(row, 'dgonto', tr('As a subtask of this task'));
  dgsRow = row;
  return true;
}
function dgs_touchDrop(el, id, y) {
  const row = el?.closest?.('#view .trow');
  if (!row || row.closest('#detail') || y == null || !dgs_mid(row, y) || !dgs_ok(id, +row.dataset.id)) return false;
  dgMakeSubs([id], +row.dataset.id);
  return true;
}
// the two drop fields in the open task's dependencies (only while a task is dragged)
function dgZonesShow(id) {
  const box = $('#detail #d-deps'), t = S.sel && taskById(S.sel), d = S.tasks.get(id);
  if (!box || !t || !d || t.id === id || $('.dgzones', box)) return;
  const by = dgDepOk(t.id, id), bl = dgDepOk(id, t.id);
  const zone = (k, ok, lab, sub) => `<div class="dgzone ${ok ? '' : 'dgoff'}" data-dgz="${k}" ${ok ? '' : `title="${esc(tr('Not possible here'))}"`}><b>${esc(lab)}</b><span>${esc(sub)}</span></div>`;
  const div = document.createElement('div');
  div.className = 'dgzones'; div.setAttribute('aria-hidden', 'true');
  div.innerHTML = zone('by', by, tr('Waiting on'), tr('“{0}” waits on the dragged task', dgShort(t.title))) + zone('blocking', bl, tr('Blocking'), tr('The dragged task waits on “{0}”', dgShort(t.title)));
  box.querySelector('h5')?.after(div);
  DG.zones = true;
}
function dgEnd() { DG.ids = null; if (DG.zones) { $$('.dgzones').forEach(x => x.remove()); DG.zones = false; } }
document.addEventListener('dragstart', e => {
  dgEnd();
  const r = e.target.closest?.('#view .trow[draggable="true"]'); if (!r) return;
  const id = +r.dataset.id, t = S.tasks.get(id); if (!t) return;
  if (S.multi.size >= 2 && S.multi.has(id)) {
    DG.ids = dgOrder([...S.multi]);
    const g = document.createElement('div');
    g.className = 'dgghost'; g.textContent = trn('{0} task', '{0} tasks', DG.ids.length);
    document.body.appendChild(g);
    try { e.dataTransfer.setDragImage(g, 14, 14); } catch { /* old browsers: the row as the image */ }
    setTimeout(() => g.remove(), 0);
    requestAnimationFrame(() => DG.ids?.forEach(i => $(`#view .trow[data-id="${i}"]`)?.classList.add('dragging')));
  }
  e.dataTransfer.effectAllowed = 'all';  // move, and link for Alt (dependencies)
  setTimeout(() => dgZonesShow(id), 0);  // after the drag began (a layout change inside dragstart can end it)
  // the first drag on this device explains the extra ways (as the timeline does); after dragstart (no layout change inside it)
  const tip = DG.ids ? !hintSeen('dgmulti') && 'dgmulti' : dFor(t) && canEdit(t) && !hintSeen('dgalt') && 'dgalt';
  if (tip) setTimeout(() => { hintDone(tip); toast(tip === 'dgmulti' ? tr('Tip: drop onto the middle of a task and the selected tasks become its subtasks; above or below it moves them as a block.') : tr('Tip: hold Alt (Option on a Mac) while you drop onto another task: it then waits on that task.'), null, 9000); }, 0);
});
document.addEventListener('dragend', () => { dgClear(); dgEnd(); });
// the multi panel and the phone's selection menu (multiedit.js, sidebar.js)
function dgMeHtml(ts) {
  if (!ts.length || ts.some(t => t.context)) return '';
  const subs = ts.some(t => t.parent_id), lock = ts.every(t => !canEdit(t));
  return `<div class="dsec dgme"><h5>${ic('indent', 's')}${tr('Structure')}</h5><div class="dgmeb">
    <button type="button" class="btn sm" data-act="dg-sub" ${lock ? 'disabled' : ''}>${ic('indent', 's')} ${esc(tr('Subtasks of…'))}</button>
    ${subs ? `<button type="button" class="btn sm" data-act="dg-out" ${lock ? 'disabled' : ''}>${ic('outdent', 's')} ${esc(tr('Out of the parent task'))}</button>` : ''}</div></div>`;
}
const dgMenuItems = ids => [{label: tr('Subtasks of…'), icon: 'indent', fn: () => dgSubPick(ids)},
  ...(ids.some(i => S.tasks.get(i)?.parent_id) ? [{label: tr('Out of the parent task'), icon: 'outdent', fn: () => dgDetach(ids)}] : [])];
document.addEventListener('click', e => {
  const a = e.target.closest?.('[data-act="dg-sub"], [data-act="dg-out"]'); if (!a || a.disabled) return;
  const ids = [...S.multi].filter(i => S.tasks.get(i));
  if (a.dataset.act === 'dg-sub') dgSubPick(ids); else dgDetach(ids);
});
