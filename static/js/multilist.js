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
// 2.320.0 (#3289): no budget either (the server refuses it since 2.72.0)
const ml_okTarget = (t, l) => { const o = listById(t.list_id); return !!o && !!l && l.id !== t.list_id && (o.org_id ?? null) === (l.org_id ?? null)
  && !['health', 'budget'].includes(o.life) && !['health', 'budget'].includes(l.life) && o.e2e == null && l.e2e == null && !l.archived && canEditList(l.id); };
const ml_also = t => (t?.also || []).filter(a => listById(a.list_id));
// 2.320.0 (#3289): why task t cannot be shown also in list l ('' = it can); the server checks the same (multilist.py ml_check)
function ml_why(t, l) {
  if (!t || !l || t.id < 0 || t.deleted_at || t.context) return tr('Not possible here');
  if (t.parent_id) return tr('Only main tasks');
  if (l.id === t.list_id) return tr('Its own project');
  if (ml_in(t, l.id)) return tr('Already shown here');
  if (!canEdit(t) || !canEditList(l.id)) return tr('No permission');
  if (!ml_okTarget(t, l)) return tr('Not possible for this project');  // other workspace, health, budget, locked, archived
  if (ml_also(t).length >= ML_MAX) return tr('Already in {0} further projects', ML_MAX);
  return '';
}

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
  const al = ml_also(t);
  const add = ml_canAdd(t) ? [{label: tr('Show also in project…'), icon: 'link', fn: () => ml_pick(anchor, t)}] : [];
  return [...add, ...al.map(a => ({label: tr('Remove from {0}', lname(listById(a.list_id))), icon: 'x', fn: () => ml_remove(t.id, a.list_id)}))];
}

const ml_canAdd = t => S.lists.some(l => !ml_why(t, l));
const ml_pick = (anchor, t) => tch_listPicker(anchor, {title: tr('Show also in project'), filter: l => !ml_why(t, l), pick: l => ml_add(t.id, l.id)});

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

// ------------------------------------------------------------------ 2.320.0 (#3289): easier to find
// The task panel's field "Projects": its own project (fixed), the further ones with x, + opens the project picker (the
// rules of ml_why). The same on a phone and a desktop. Only for a main task that has further projects or could get one.
function ml_detailHtml(t) {
  if (!t || t.id <= 0 || t.parent_id || t.context || t.deleted_at) return '';
  const own = listById(t.list_id); if (!own) return '';
  const al = ml_also(t), add = canEdit(t) && ml_canAdd(t);
  if (!al.length && !add) return '';
  const icon = l => l.is_inbox ? ic('inbox', 's') : licMark(l, 's', true) || ic('list', 's');
  const item = l => `<span class="mlp"><button type="button" class="mlpn" data-act="ml-open" data-lid="${l.id}" title="${esc(tr('Open {0}', lname(l)))}">${icon(l)}<span>${esc(lname(l))}</span></button>${
    canEdit(t) || canEditList(l.id) ? `<button type="button" class="mlpx" data-act="ml-rm" data-lid="${l.id}" title="${esc(tr('Remove from {0}', lname(l)))}" aria-label="${esc(tr('Remove from {0}', lname(l)))}">${ic('x', 's')}</button>` : ''}</span>`;
  return `<div class="dmlp" role="group" aria-label="${esc(tr('Projects'))}"><span class="dmlpk">${esc(tr('Projects'))}</span>
    <span class="mlp own" title="${esc(tr('Its own project'))}">${icon(own)}<span>${esc(lname(own))}</span></span>${al.map(a => item(listById(a.list_id))).join('')}${
    add ? `<button type="button" class="mlpadd" data-act="ml-add" title="${esc(tr('Show also in project…'))}" aria-label="${esc(tr('Show also in project…'))}">${ic('plus', 's')}${al.length ? '' : `<span>${esc(tr('Also in…'))}</span>`}</button>` : ''}</div>`;
}

// several selected tasks also into list lid: the ones that may (one request each), one history step; the others are skipped
// and counted (subtasks, another workspace, a health / budget / locked project, already 10 further ones, no permission)
async function ml_addMany(ids, lid) {
  const l = listById(lid), ts = ids.map(i => taskById(i)).filter(Boolean); if (!l || !ts.length) return;
  const ok = ts.filter(t => !ml_why(t, l)), there = ts.filter(t => !t.parent_id && ml_in(t, lid)).length;
  if (ts.length === 1 && ok.length === 1) { await ml_add(ok[0].id, lid); return; }
  let skip = ts.length - ok.length - there;
  const done = [];
  for (const t of ok) {
    try { const r = await rawFetch('POST', `/api/tasks/${t.id}/links`, {list_id: lid}); if (r?.id) { putTask(r); done.push(t.id); } else skip++; }
    catch (e) { if (e instanceof Offline) { toast(tr('Offline: only works again with a connection')); break; } skip++; }
  }
  render(); if (S.sel && done.includes(S.sel)) renderDetail();
  const n = lname(l), rest = [there ? trn('{0} already there', '{0} already there', there) : '', skip ? trn('{0} skipped (not possible there)', '{0} skipped (not possible there)', skip) : ''].filter(Boolean);
  if (!done.length) { toast(ts.length === 1 ? ml_why(ts[0], l) : [tr('Not possible for the selected tasks'), ...rest].join(' · ')); return; }
  const lab = trn('{0} task is now also in {1}', '{0} tasks are now also in {1}', done.length, n);
  const each = m => () => Promise.all(done.map(i => ml_req(m, i, lid, m === 'POST' ? {list_id: lid} : undefined)));
  offerUndo([lab, ...rest].join(' · '), histAdd({label: lab, ids: done, lids: [lid], undo: each('DELETE'), redo: each('POST')}));
}
// the multi panel (multiedit.js) and the phone's selection menu (sidebar.js): "Show also in project…" for all selected
const ml_multiOk = ids => ids.some(i => { const t = taskById(i); return t && !t.parent_id && canEdit(t) && ml_canAdd(t); });
function ml_multiPick(anchor, ids) {
  const ts = ids.map(i => taskById(i)).filter(Boolean);
  if (!ml_multiOk(ids)) { toast(tr('Not possible for the selected tasks')); return; }
  tch_listPicker(anchor, {title: tr('Show also in project'), filter: l => ts.some(t => !ml_why(t, l)), pick: l => ml_addMany(ids, l.id)});
}
const ml_multiItems = (ids, anchor) => ml_multiOk(ids) ? [{label: tr('Show also in project…'), icon: 'link', fn: () => ml_multiPick(anchor, ids)}] : [];
function ml_meHtml(ts) {
  const ids = ts.map(t => t.id);
  return ml_multiOk(ids) ? `<div class="dsec mlme"><h5>${ic('link', 's')}${tr('Projects')}</h5><div class="dgmeb"><button type="button" class="btn sm" data-act="ml-multi">${ic('link', 's')} ${esc(tr('Show also in project…'))}</button></div></div>` : '';
}
document.addEventListener('click', e => {
  const a = e.target.closest?.('[data-act="ml-add"], [data-act="ml-rm"], [data-act="ml-open"], [data-act="ml-multi"]'); if (!a || a.disabled) return;
  const k = a.dataset.act;
  if (k === 'ml-multi') { ml_multiPick(a, [...S.multi].filter(i => taskById(i))); return; }
  const t = taskById(S.sel), lid = +a.dataset.lid; if (!t) return;
  if (k === 'ml-add') ml_pick(a, t);
  else if (k === 'ml-rm') ml_remove(t.id, lid);
  else { const l = listById(lid); if (!l) return; if (isMobile()) closeDetail(); go(keyToHash(l.is_inbox ? 'inbox' : 'l:' + l.id)); }
});

// Desktop: dropping onto a project in the sidebar with Alt (Option on a Mac) held = show also there instead of moving (a
// selection: every selected main task that may). While dragging the project says what happens ("Also show in X"); without
// Alt a project that could take it says "Alt: also show here". dnd.js asks ml_altOver on every dragover, ml_altDrop first.
let mlAlt = null;
function ml_side(el) {
  const s = el?.closest?.('.srow[data-drop]'), k = s?.dataset.drop || '';
  const l = k.startsWith('l:') ? listById(+k.slice(2)) : k === 'inbox' ? inbox() : null;
  return s && l ? {s, l} : null;
}
const ml_dragIds = id => DG.ids || [id];
function ml_altClear() { if (!mlAlt) return; mlAlt.s.classList.remove('mlalt', 'mlno', 'mlhint'); delete mlAlt.s.dataset.ml; mlAlt = null; }
// true = handled (the caller does nothing more)
function ml_altOver(e, id) {
  const sd = ml_side(e.target), alt = !!e.altKey;
  if (sd && mlAlt && mlAlt.s === sd.s && mlAlt.alt === alt) { if (alt && mlAlt.ok) { e.preventDefault(); e.dataTransfer.dropEffect = 'link'; } return alt; }
  ml_altClear();
  if (!sd) return false;
  const ts = ml_dragIds(id).map(i => taskById(i)).filter(Boolean), n = ts.filter(t => !ml_why(t, sd.l)).length;
  if (!alt) {
    if (n) { sd.s.dataset.ml = IS_MAC ? tr('Option: also show here') : tr('Alt: also show here'); sd.s.classList.add('mlhint'); mlAlt = {s: sd.s, alt, ok: true}; }
    return false;
  }
  $$('.dropbefore,.dropafter,.drop').forEach(x => x.classList.remove('dropbefore', 'dropafter', 'drop'));
  sd.s.dataset.ml = !n ? (ts.length === 1 ? ml_why(ts[0], sd.l) : tr('Not possible here'))
    : ts.length > 1 ? trn('{0} task also in {1}', '{0} tasks also in {1}', n, lname(sd.l)) : tr('Also show in {0}', lname(sd.l));
  sd.s.classList.add(n ? 'mlalt' : 'mlno');
  mlAlt = {s: sd.s, alt, ok: !!n};
  if (n) { e.preventDefault(); e.dataTransfer.dropEffect = 'link'; }
  return true;
}
function ml_altDrop(e, id) {
  const sd = e.altKey && ml_side(e.target);
  ml_altClear();
  if (!sd) return false;
  const ids = ml_dragIds(id);
  dgClear(); dgEnd();
  $$('.dragging,.dropbefore,.dropafter,.drop').forEach(x => x.classList.remove('dragging', 'dropbefore', 'dropafter', 'drop'));
  document.body.classList.remove('tdrag');
  ml_addMany(ids, sd.l.id);
  return true;
}
document.addEventListener('dragend', ml_altClear);
