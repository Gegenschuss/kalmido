// @ts-check
/* Kalmido web client: the office's document areas as trees in the panel (2.351.0 A, #3312). Quotes & invoices, Documents,
   Correspondence and Receipts open like a list / a folder (sbb_treeHtml, the panel's rows of the office's menu): the area's
   folders with their subfolders, the 20 newest documents in no folder and "More…" (the area's full list). Data per area from
   GET /api/office/<segment>/tree (office/oftree.py: folders below the area's root folder + other folders that hold the area's
   documents, shown with their path). Folders: New folder… (at the area / a folder), Share… (the file store's one dialog),
   Rename…, Move to the trash; documents: dragged into a folder (a computer), "Move…" in their menu (a phone too), out of the
   folder. Filing is the folder system's (POST /api/files/refs: the office's rights decide, a folder gives only the document).
   Client / project / year are filters at the top of the list (office_docs.js), no groups in the tree.
   Classic script sharing the global scope with the others (lazy module "office", after office_docs.js). */
'use strict';

const OFT = {d: {}, busy: {}};
// area -> [route segment, icon of its documents]
// 2.380.0 B (#3409): [2] = the query of the area (quotations / invoices share the documents' route)
const OFT_AREAS = {offers: ['docs', 'file'], invoices: ['docs', 'receipt', '?sec=invoices'], gendocs: ['gen-docs', 'file'], letters: ['letters', 'mail'], receipts: ['receipts', 'ticket']};
const oft_key = () => `${S.me?.id || ''}:${typeof wsCur === 'function' ? wsCur() : 'all'}`;
// 2.373.0 (#3337): OFT.busy[area] = the running load; a second call gets it to wait on (ltSentModal's folders)
function oft_load(area) {
  return OFT.busy[area] || (OFT.busy[area] = oft_fetch(area).finally(() => { OFT.busy[area] = null; }));
}
async function oft_fetch(area) {
  const key = oft_key();
  try { OFT.d[area] = {...(await rawFetch('GET', `/api/office/${OFT_AREAS[area][0]}/tree${OFT_AREAS[area][2] || ''}`)), key, v: S.v, at: Date.now()}; }
  catch (e) { if (e.message === 'auth') return; OFT.d[area] = {key, v: S.v, at: Date.now(), folders: [], docs: [], err: e.message}; }
  if (typeof sbb_officeSync === 'function') sbb_officeSync();
  if ((area === 'gendocs' || area === 'letters') && OFT.d[area]?.shared?.length && S.route.mod === 'office' && S.route.tab === area && !S.route.id && typeof ofcDraw === 'function') ofcDraw();
}
// the tree of an area: loaded once per person / workspace, again after a change (S.v) at most every few seconds
function oft_get(area) {
  const d = OFT.d[area];
  if (!d || d.key !== oft_key() || (d.v !== S.v && Date.now() - d.at > 4000)) oft_load(area);
  return d && d.key === oft_key() ? d : null;
}
const oft_folder = (area, id) => (OFT.d[area]?.folders || []).find(f => f.id === +id) || null;
const oft_doc = (area, id) => (OFT.d[area]?.docs || []).find(x => x.id === +id) || null;
const oft_canW = f => !!f && (f.role === 'edit' || f.role === 'owner');
const oft_byNo = (a, b, na, nb) => ((a ?? Infinity) - (b ?? Infinity)) || String(na || '').localeCompare(String(nb || ''), undefined, {sensitivity: 'base'});
// the folders at the top of the area (below its root; the outside ones with their path) / below folder pid
function oft_kids(area, pid) {
  const d = OFT.d[area]; if (!d) return [];
  return d.folders.filter(f => pid ? f.parent_id === pid && !f.outside : f.outside || f.parent_id === d.root).sort((a, b) => oft_byNo(a.sort_no, b.sort_no, a.path || a.name, b.path || b.name));
}
const oft_docsIn = (area, fid) => (OFT.d[area]?.docs || []).filter(x => (x.folder_id || null) === (fid || null)).sort((a, b) => fid ? oft_byNo(a.fsort, b.fsort, a.title, b.title) : 0);
const oft_path = (area, f) => { if (f.outside) return f.path; const p = []; for (let y = f, g = 0; y && g < 40; y = oft_folder(area, y.parent_id), g++) p.unshift(y.name); return p.join(' / '); };

// ---- the panel: the row of an area as a tree node (areas.js sbb_officeHtml; '' = a plain row)
function oft_rowHtml(i, on) {
  const area = i.key; if (!OFT_AREAS[area]) return '';
  const r = S.route, here = r.mod === 'office' && r.tab === area ? r.id : null;
  const doc = (x, par) => ({k: `of:d:${area}:${x.id}`, name: x.title + (x.sub ? ' · ' + x.sub : ''), icon: OFT_AREAS[area][1], go: x.open, on: here === x.id,
    ns: 'oft', id: `d:${area}:${x.id}`, par, drag: true, menu: true, kids: false, attrs: `data-oftdoc="${area}:${x.id}"`});
  const fold = f => ({k: `of:f:${f.id}`, name: f.outside ? f.path : f.name, icon: f.shared ? 'users' : 'folder', go: 'ablage/' + f.id, ns: 'oft', id: `f:${area}:${f.id}`,
    par: f.outside || !f.parent_id || f.parent_id === OFT.d[area]?.root ? 'a:' + area : `f:${area}:${f.parent_id}`, drag: oft_canW(f) && !f.outside, drop: oft_canW(f), menu: true,
    kids: oft_kids(area, f.id).length > 0 || oft_docsIn(area, f.id).length > 0, sub: () => [...oft_kids(area, f.id).map(fold), ...oft_docsIn(area, f.id).map(x => doc(x, `f:${area}:${f.id}`))]});
  const node = {k: 'of:a:' + area, name: tr(i.name), icon: i.icon, go: i.go, on, battrs: `data-ofm="${esc(area)}"`, ns: 'oft', id: 'a:' + area, par: '', drop: true, menu: true, kids: true,
    sub: () => { const d = oft_get(area); if (!d) return null;
      if (d.err && !d.folders.length && !d.docs.length) return [];
      return [...oft_kids(area, null).map(fold), ...oft_docsIn(area, null).map(x => doc(x, 'a:' + area)),
        ...(d.more ? [{k: 'of:m:' + area, name: tr('More…'), icon: 'dots', go: i.go, battrs: `data-oftmore="${esc(area)}"`}] : [])]; }};
  return sbb_treeHtml([node], 0);
}

// ---- 2.351.0 A (#2823): the lists of Documents / Correspondence also show what another office shares through a folder (read:
// the PDF through the file store; the tree's data, office/oftree.py oft_shared)
function oft_sharedHtml(area) {
  const xs = oft_get(area)?.shared || []; if (!xs.length) return '';
  return `<h3 class="ofcgrp">${esc(tr('Shared through a folder'))}</h3><ul class="ofclist dtp-list" role="list" data-oftshared="${esc(area)}">${xs.map(x => `<li><a class="ofcrow" href="/api/files/nodes/${x.node}/content" target="_blank" rel="noopener">
    <span class="ofcn"><b>${esc(x.title)}</b><small class="muted">${esc(tr('Read only'))}</small></span>${ic('pdf', 's')}</a></li>`).join('')}</ul>`;
}

// ---- changes
function oft_after(area) {
  if (area) { if (OFT.d[area]) OFT.d[area].at = 0; OFT.d[area] && (OFT.d[area].v = -1); oft_load(area); }
  if (typeof ab_ptStale === 'function') ab_ptStale();
  if (S.route.mod === 'office' && (area === 'offers' || area === 'invoices') && typeof OFD !== 'undefined') OFD.list = null;
}
const oft_req = async (area, m, url, b) => { try { const r = await rawFetch(m, url, b); oft_after(area); return r || true; } catch (e) { toast(e.message); return null; } };
const oft_open = (area, k) => { if (isMobile()) return; const x = new Set(LS.get('sbbOpen', []) || []); x.add(k); LS.set('sbbOpen', [...x].slice(-300)); };
async function oft_newFolder(area, pid) {
  const v = await askDialog({title: tr('New folder'), input: {value: '', placeholder: tr('Folder name'), max: 120}, ok: tr('Create'), cancel: undefined, after: undefined});
  if (!v || !v.trim()) return;
  const r = await oft_req(area, 'POST', `/api/office/${OFT_AREAS[area][0]}/tree/folders${OFT_AREAS[area][2] || ''}`, {name: v.trim(), ...(pid ? {parent_id: pid} : {})});
  if (r?.folder) { oft_open(area, 'of:a:' + area); if (pid) oft_open(area, 'of:f:' + pid); }
}
async function oft_rename(area, f) {
  const v = await askDialog({title: tr('Rename folder'), input: {value: f.name, placeholder: tr('Folder name'), max: 120}, ok: tr('Save'), cancel: undefined, after: undefined});
  if (!v || !v.trim() || v.trim() === f.name) return;
  await oft_req(area, 'PATCH', `/api/files/nodes/${f.id}`, {name: v.trim()});
}
async function oft_delete(area, f) {
  const r = await oft_req(area, 'DELETE', `/api/files/nodes/${f.id}`); if (!r) return;
  const kept = typeof fs_keptText === 'function' ? fs_keptText(r.kept) : (r.kept || []).map(k => k.reason).join(', ');
  offerUndo([tr('“{0}” moved to the trash', f.name), kept].filter(Boolean).join(' · '), histAdd({label: tr('Delete “{0}”', f.name),
    undo: async () => { await rawFetch('POST', `/api/files/nodes/${f.id}/restore`); oft_after(area); return {skipped: []}; },
    redo: async () => { await rawFetch('DELETE', `/api/files/nodes/${f.id}`); oft_after(area); return {skipped: []}; }}));
}
// a document into folder fid of its area (null: into no folder), with undo
async function oft_place(area, x, fid) {
  const was = x.folder_id ?? null, kind = OFT.d[area]?.kind;
  if ((fid || null) === was || !kind) return;
  const put = v => rawFetch('POST', '/api/files/refs', {ref_kind: kind, ref_id: x.id, parent_id: v});
  if (!await oft_req(area, 'POST', '/api/files/refs', {ref_kind: kind, ref_id: x.id, parent_id: fid || null})) return;
  const f = fid ? oft_folder(area, fid) : null;
  offerUndo(f ? tr('Filed in {0}', oft_path(area, f)) : tr('Taken out of the folder'), histAdd({label: tr('Move “{0}”', x.title || ''),
    undo: async () => { await put(was); oft_after(area); return {skipped: []}; }, redo: async () => { await put(fid || null); oft_after(area); return {skipped: []}; }}));
}
async function oft_moveFolder(area, f, pid) {
  const was = f.parent_id;
  if (!pid || pid === was || pid === f.id) return;
  if (!await oft_req(area, 'PATCH', `/api/files/nodes/${f.id}`, {parent_id: pid})) return;
  offerUndo(tr('“{0}” moved', f.name), histAdd({label: tr('Move “{0}”', f.name),
    undo: async () => { await rawFetch('PATCH', `/api/files/nodes/${f.id}`, {parent_id: was}); oft_after(area); return {skipped: []}; },
    redo: async () => { await rawFetch('PATCH', `/api/files/nodes/${f.id}`, {parent_id: pid}); oft_after(area); return {skipped: []}; }}));
}
// "Move…": the area's folders the person may add to (with their path) and "No folder" -- the phone's way (no dragging needed)
function oft_moveDlg(area, x, anchor) {
  const fs = (OFT.d[area]?.folders || []).filter(f => oft_canW(f) && f.id !== x.folder_id);
  const items = [...(x.folder_id ? [{label: tr('No folder'), icon: 'up', fn: () => oft_place(area, x, null)}] : []),
    ...fs.map(f => ({label: oft_path(area, f), icon: 'folder', fn: () => oft_place(area, x, f.id)}))];
  if (!items.length) { toast(tr('No folder yet: create one with “New folder…”')); return; }
  menu(anchor || $(`#side [data-oftdoc="${area}:${x.id}"]`) || document.body, items, null, null, tr('Move…'));
}
// tree ids: 'a:<area>' (the area), 'f:<area>:<folder>', 'd:<area>:<document>'
const oft_id = id => { const [t, area, n] = String(id).split(':'); return {t, area, n: n ? +n : null}; };
function oft_menuItems(id) {
  const {t, area, n} = oft_id(id); if (!OFT_AREAS[area]) return [];
  const d = OFT.d[area];
  if (t === 'a') return [{label: tr('Open'), icon: OFT_AREAS[area][1], fn: () => go(OFM_ITEMS.find(i => i.key === area)?.go || 'office')},
    !d || d.can_add ? {label: tr('New folder…'), icon: 'plus', fn: () => oft_newFolder(area, null)} : null];
  if (t === 'f') {
    const f = oft_folder(area, n); if (!f) return [];
    const w = oft_canW(f);
    return [{label: tr('Open'), icon: 'folder', fn: () => go('ablage/' + f.id)},
      w && !f.outside ? {label: tr('New folder…'), icon: 'plus', fn: () => oft_newFolder(area, f.id)} : null,
      f.role === 'owner' ? {label: tr('Share…'), icon: 'users', fn: () => fs_shareDialog(f.id, {onChange: () => oft_after(area)})} : null,
      '-', w && !f.outside ? {label: tr('Rename…'), icon: 'edit', fn: () => oft_rename(area, f)} : null,
      '-', w && !f.outside ? {label: tr('Move to the trash'), icon: 'trash', cls: 'danger', fn: () => oft_delete(area, f)} : null];
  }
  const x = oft_doc(area, n); if (!x) return [];
  return [{label: tr('Open'), icon: OFT_AREAS[area][1], fn: () => go(x.open)},
    {label: tr('Move…'), icon: 'folder', fn: () => oft_moveDlg(area, x)},
    x.folder_id ? {label: tr('Take out of the folder'), icon: 'up', fn: () => oft_place(area, x, null)} : null];
}
// the node id of a tree id (a document: its node, a folder: itself; null: none, e.g. a document in no folder)
const oft_nodeOf = id => { const {t, area, n} = oft_id(id); return t === 'd' ? oft_doc(area, n)?.fnode ?? null : t === 'f' ? n : null; };
function oft_move(id, into) {
  const a = oft_id(id), b = oft_id(into);
  if (a.area !== b.area) { toast(tr('Documents stay in their own area')); return; }
  const fid = b.t === 'f' ? b.n : null;
  if (a.t === 'd') { const x = oft_doc(a.area, a.n); if (x) oft_place(a.area, x, fid); return; }
  const f = oft_folder(a.area, a.n), root = OFT.d[a.area]?.root;
  if (f) oft_moveFolder(a.area, f, fid || root);
}
async function oft_order(id, pos) {
  if (pos.into !== undefined) { oft_move(id, pos.into); return; }
  const node = oft_nodeOf(id), sib = oft_nodeOf(pos.before || pos.after);
  if (!node || !sib) return;  // a document in no folder keeps the order by date
  await oft_req(oft_id(id).area, 'POST', `/api/files/nodes/${node}/order`, pos.before ? {before: sib} : {after: sib});
}
sbb_treeReg('oft', {move: oft_move, order: oft_order, menu: id => oft_menuItems(id)});

// ---- a quotation / invoice row of the list dragged onto a folder of the panel (a computer)
let OFT_EXT = null;
document.addEventListener('dragstart', e => {
  const li = /** @type {any} */ (e.target).closest?.('#view .ofdli[draggable="true"]'), r = li?.querySelector('.ofdrow[data-id]'); if (!r) return;
  OFT_EXT = {area: typeof ofd_sec === 'function' ? ofd_sec() : 'offers', id: +r.dataset.id};  // 2.380.0 B (#3409): the list's area
  e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', r.querySelector('.ofcn b')?.textContent || '');
});
const oft_extTo = e => { const t = /** @type {any} */ (e.target).closest?.('#side .sbbt[data-sbbns="oft"][data-sbbdrop]'); return t && oft_id(t.dataset.sbbid).area === OFT_EXT?.area ? t : null; };
document.addEventListener('dragover', e => {
  if (!OFT_EXT) return;
  const t = oft_extTo(e); $$('#side .sbbdin').forEach(x => { if (x !== t) x.classList.remove('sbbdin'); });
  if (!t) return;
  e.preventDefault(); e.dataTransfer.dropEffect = 'move'; t.classList.add('sbbdin');
});
document.addEventListener('drop', async e => {
  if (!OFT_EXT) return;
  const x = OFT_EXT, t = oft_extTo(e); OFT_EXT = null; $$('#side .sbbdin').forEach(y => y.classList.remove('sbbdin'));
  if (!t) return;
  e.preventDefault();
  const b = oft_id(t.dataset.sbbid);
  let doc = oft_doc(x.area, x.id);
  if (!doc) {  // not among the tree's documents: where it lies now (for the undo)
    const cur = await rawFetch('GET', `/api/files/refs/${OFT.d[x.area]?.kind || 'office_doc'}/${x.id}`).catch(() => null);
    doc = {id: x.id, title: (OFD.list || []).find(r => r.id === x.id)?.number || '', folder_id: cur?.node?.parent_id ?? null};
  }
  oft_place(x.area, doc, b.t === 'f' ? b.n : null);
});
document.addEventListener('dragend', () => { OFT_EXT = null; });
