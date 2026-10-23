// @ts-check
/* Kalmido web client: tables in folders (2.199.0 C, #2742). The folders of the tables live in the file store below the
   workspace's root folder "Tables" (GET /api/sheets/folders: the root per workspace, the folders the person sees); a table
   lies in at most one folder (GET /api/sheets: folder_id, fnode = its node, fsort = its place sorted by hand). The panel
   draws one entry per workspace (a single workspace shown: only its entry) with the shared tree (sbb_treeHtml): the real
   folders (drag to move / sort, menu: New folder, New table, Rename, Share, Move to the trash), the tables in no folder,
   then one automatic group per project (a filter view: other look, no drag, no menu). The overview (and the phone) shows
   the folders as cards; #sheets/f/<id> is one folder. Sharing a folder: the one dialog of the file store (fs_shareDialog).
   Classic script sharing the global scope with the others (lazy module "sheets", after sheets.js). */
'use strict';

const SHF = {d: null, v: -1, busy: false, err: ''};
async function shf_load(force) {
  if (SHF.busy || (!force && SHF.d && SHF.v !== -1)) return;
  SHF.busy = true;
  try { SHF.d = await rawFetch('GET', '/api/sheets/folders'); SHF.err = ''; }
  catch (e) { if (e.message === 'auth') return; SHF.err = e.message; SHF.d = SHF.d || {spaces: [], folders: []}; }
  finally { SHF.busy = false; SHF.v = S.v; }
  if (typeof sbb_sync === 'function') sbb_sync('sheets');
  if (S.route.mod === 'sheets' && !S.route.sh) viewSafeRender();
}
const shf_data = () => { if (!SHF.d || SHF.v === -1) shf_load(); return SHF.d || {spaces: [], folders: []}; };
const shf_folder = id => shf_data().folders.find(f => f.id === +id) || null;
const shf_space = sp => shf_data().spaces.find(s => s.space === sp) || null;
const shf_canW = f => !!f && (f.role === 'edit' || f.role === 'owner');
const shf_byNo = (a, b, na, nb) => ((a ?? Infinity) - (b ?? Infinity)) || String(na || '').localeCompare(String(nb || ''), undefined, {sensitivity: 'base'});
// the folders below folder pid (null: the top of workspace sp, i.e. below its root), sorted like the server: by hand, then name
function shf_kids(sp, pid) {
  const root = shf_space(sp)?.root;
  return shf_data().folders.filter(f => f.space === sp && (pid ? f.parent_id === pid : f.parent_id === root))
    .sort((a, b) => shf_byNo(a.sort_no, b.sort_no, a.name, b.name));
}
// the tables in folder fid; fid null: the tables of sp in no folder the person sees (shared ones have their own group)
function shf_tables(items, sp, fid) {
  const known = new Set(shf_data().folders.map(f => f.id));
  return items.filter(x => !x.shared_in && (fid ? x.folder_id === fid : x.space === sp && !known.has(x.folder_id)))
    .sort((a, b) => fid ? shf_byNo(a.fsort, b.fsort, a.title, b.title) : 0);
}
// every table of the index (the panel's and the overview's)
const shf_items = () => Object.values(SHV.idx).flatMap(d => d.items || []).filter((x, i, a) => a.findIndex(y => y.id === x.id) === i);
const shf_item = id => shf_items().find(x => x.id === +id) || null;

// ---- the panel
function shf_panelTree(items, sps, cur) {
  const r = S.route, at = r.mod === 'sheets' ? r.shf : null, path = [];
  for (let f = at ? shf_folder(at) : null, g = 0; f && g < 40; f = shf_folder(f.parent_id), g++) path.push(f.id);
  const tbl = (x, par, ns) => ({k: 'sh:t' + x.id, name: x.title || tr('Untitled table'), icon: 'sheet', go: 'sheets/' + x.id, on: x.id === cur, kids: false,
    attrs: `data-sbbsh="${x.id}"`, ...(ns ? {ns: 'sh', id: 't' + x.id, par, drag: true, menu: true} : {})});
  const fold = f => ({k: 'sh:f' + f.id, name: f.name, icon: f.shared ? 'users' : 'folder', go: 'sheets/f/' + f.id, on: at === f.id, ns: 'sh', id: 'f' + f.id,
    par: f.parent_id === shf_space(f.space)?.root ? 'r:' + f.space : 'f' + f.parent_id, drag: shf_canW(f), drop: shf_canW(f), menu: true,
    kids: shf_kids(f.space, f.id).length > 0 || shf_tables(items, f.space, f.id).length > 0, open: path.includes(f.id) && f.id !== at,
    sub: () => [...shf_kids(f.space, f.id).map(fold), ...shf_tables(items, f.space, f.id).map(x => tbl(x, 'f' + f.id, true))]});
  return sps.map(sp => {
    const s = shf_space(sp), lists = new Map();
    for (const x of items) if (!x.shared_in && x.list_id && x.space === sp) { if (!lists.has(x.list_id)) lists.set(x.list_id, []); lists.get(x.list_id).push(x); }
    const auto = [...lists].map(([lid, xs]) => ({k: 'sh:l' + lid, name: xs[0].list_title || (listById(lid) ? lname(listById(lid)) : tr('Project')), go: 'sheets/l/' + lid, auto: true,
      kids: true, on: r.mod === 'sheets' && r.shl === lid, open: xs.some(x => x.id === cur), sub: () => xs.map(x => tbl(x))}));
    const loose = shf_tables(items, sp, null).filter(x => !x.list_id);
    return {k: 'sh:s:' + sp, name: shvSpaceName(sp), icon: sp === 'private' ? 'home' : 'building', go: 'sheets', battrs: `data-shsp="${esc(sp)}"`,
      ns: 'sh', id: 'r:' + sp, par: '', drop: !!s?.can_add, menu: !!s?.can_add, kids: true, open: true,
      sub: () => [...shf_kids(sp, null).map(fold), ...loose.map(x => tbl(x, 'r:' + sp, true)), ...auto]};
  });
}
// a workspace in the panel: the overview of the tables shows that workspace's group first (capture, before the router's click)
document.addEventListener('click', e => { const b = /** @type {any} */ (e.target).closest?.('#side [data-shsp]'); if (b) LS.set('shvSpace', b.dataset.shsp); }, true);

// ---- changes
function shf_after() {
  SHF.v = -1; shf_load(true);
  for (const d of Object.values(SHV.idx)) d.v = -1;
  if (typeof sbb_sync === 'function') sbb_sync('sheets');
  if (S.route.mod === 'sheets') renderView();
}
const shf_req = async (m, url, b) => { try { const r = await rawFetch(m, url, b); shf_after(); return r || true; } catch (e) { toast(e.message); return null; } };
async function shf_newFolder(sp, pid) {
  const v = await askDialog({title: tr('New folder'), input: {value: '', placeholder: tr('Folder name'), max: 120}, ok: tr('Create'), cancel: undefined, after: undefined});
  if (!v || !v.trim()) return;
  const r = await shf_req('POST', '/api/sheets/folders', {name: v.trim(), space: sp, ...(pid ? {parent_id: pid} : {})});
  if (r?.folder && !isMobile()) { const x = new Set(LS.get('sbbOpen', []) || []); x.add('sh:s:' + sp); if (pid) x.add('sh:f' + pid); LS.set('sbbOpen', [...x].slice(-300)); }
}
async function shf_rename(f) {
  const v = await askDialog({title: tr('Rename folder'), input: {value: f.name, placeholder: tr('Folder name'), max: 120}, ok: tr('Save'), cancel: undefined, after: undefined});
  if (!v || !v.trim() || v.trim() === f.name) return;
  await shf_req('PATCH', `/api/files/nodes/${f.id}`, {name: v.trim()});
}
async function shf_delete(f) {
  const r = await shf_req('DELETE', `/api/files/nodes/${f.id}`); if (!r) return;
  if (S.route.mod === 'sheets' && S.route.shf === f.id) go(f.parent_id && shf_folder(f.parent_id) ? 'sheets/f/' + f.parent_id : 'sheets');
  const kept = typeof fs_keptText === 'function' ? fs_keptText(r.kept) : (r.kept || []).map(k => k.reason).join(', ');
  offerUndo([tr('“{0}” moved to the trash', f.name), kept].filter(Boolean).join(' · '), histAdd({label: tr('Delete “{0}”', f.name),
    undo: async () => { await rawFetch('POST', `/api/files/nodes/${f.id}/restore`); shf_after(); return {skipped: []}; },
    redo: async () => { await rawFetch('DELETE', `/api/files/nodes/${f.id}`); shf_after(); return {skipped: []}; }}));
}
const shf_share = f => fs_shareDialog(f.id, {onChange: shf_after});
// a table into folder fid (null: into no folder)
async function shf_place(x, fid) {
  const was = x.folder_id ?? null;
  if ((fid || null) === was) return;
  const put = v => rawFetch('POST', '/api/files/refs', {ref_kind: 'sheet', ref_id: x.id, parent_id: v});
  if (!await shf_req('POST', '/api/files/refs', {ref_kind: 'sheet', ref_id: x.id, parent_id: fid || null})) return;
  offerUndo(tr('“{0}” moved', x.title || ''), histAdd({label: tr('Move “{0}”', x.title || ''),
    undo: async () => { await put(was); shf_after(); return {skipped: []}; }, redo: async () => { await put(fid || null); shf_after(); return {skipped: []}; }}));
}
async function shf_moveFolder(f, pid) {
  const was = f.parent_id;
  if (!pid || pid === was || pid === f.id) return;
  if (!await shf_req('PATCH', `/api/files/nodes/${f.id}`, {parent_id: pid})) return;
  offerUndo(tr('“{0}” moved', f.name), histAdd({label: tr('Move “{0}”', f.name),
    undo: async () => { await rawFetch('PATCH', `/api/files/nodes/${f.id}`, {parent_id: was}); shf_after(); return {skipped: []}; },
    redo: async () => { await rawFetch('PATCH', `/api/files/nodes/${f.id}`, {parent_id: pid}); shf_after(); return {skipped: []}; }}));
}
// "Move to folder…": the folders of the table's workspace the person may add to, and "No folder"
function shf_moveDlg(x, anchor) {
  const fs = shf_data().folders.filter(f => f.space === x.space && shf_canW(f) && f.id !== x.folder_id);
  const path = f => { const p = []; for (let y = f, g = 0; y && g < 40; y = shf_folder(y.parent_id), g++) p.unshift(y.name); return p.join(' / '); };
  const items = [...(x.folder_id ? [{label: tr('No folder'), icon: 'up', fn: () => shf_place(x, null)}] : []), ...fs.map(f => ({label: path(f), icon: 'folder', fn: () => shf_place(x, f.id)}))];
  if (!items.length) { toast(tr('No folder yet: create one with “New folder…”')); return; }
  menu(anchor || $(`#side .sbbt[data-sbbid="t${x.id}"]`) || document.body, items, null, null, tr('Move to folder…'));
}
// the node id of a tree id ('t<sheet>' -> its node, 'f<folder>' -> the folder; null: no node, e.g. a table in no folder)
const shf_nodeOf = id => String(id).startsWith('t') ? shf_item(String(id).slice(1))?.fnode ?? null : String(id).startsWith('f') ? +String(id).slice(1) : null;
const shf_parOf = par => String(par).startsWith('f') ? +String(par).slice(1) : String(par).startsWith('r:') ? shf_space(String(par).slice(2))?.root ?? null : null;
async function shf_order(id, pos) {
  const isT = String(id).startsWith('t'), x = isT ? shf_item(String(id).slice(1)) : null, f = isT ? null : shf_folder(String(id).slice(1));
  if (!x && !f) return;
  const sibNode = shf_nodeOf(pos.before || pos.after);
  if (pos.into !== undefined) {  // dropped next to a node of another folder: into that folder (at the end, by name)
    const pid = shf_parOf(pos.into);
    if (x) shf_place(x, String(pos.into).startsWith('f') ? pid : null); else if (pid) shf_moveFolder(f, pid);
    return;
  }
  const node = x ? x.fnode : f.id;
  if (!node || !sibNode) return;  // a table in no folder keeps the order by name
  await shf_req('POST', `/api/files/nodes/${node}/order`, pos.before ? {before: sibNode} : {after: sibNode});
}
function shf_menuItems(id) {
  id = String(id);
  if (id.startsWith('r:')) {
    const sp = id.slice(2), s = shf_space(sp); if (!s?.can_add) return [];
    return [{label: tr('New folder…'), icon: 'plus', fn: () => shf_newFolder(sp, null)}, {label: tr('New table'), icon: 'sheet', fn: () => { SHV.newSp = sp; LS.set('shvSpace', sp); shvNew(null); }}];
  }
  if (id.startsWith('f')) {
    const f = shf_folder(id.slice(1)); if (!f) return [];
    const w = shf_canW(f);
    return [{label: tr('Open'), icon: 'folder', fn: () => go('sheets/f/' + f.id)},
      w ? {label: tr('New folder…'), icon: 'plus', fn: () => shf_newFolder(f.space, f.id)} : null,
      w ? {label: tr('New table'), icon: 'sheet', fn: () => shvNew(null, f.id)} : null,
      f.role === 'owner' ? {label: tr('Share…'), icon: 'users', fn: () => shf_share(f)} : null,
      '-', w ? {label: tr('Rename…'), icon: 'edit', fn: () => shf_rename(f)} : null,
      '-', w ? {label: tr('Move to the trash'), icon: 'trash', cls: 'danger', fn: () => shf_delete(f)} : null];
  }
  const x = shf_item(id.slice(1)); if (!x) return [];
  return [{label: tr('Open'), icon: 'sheet', fn: () => go('sheets/' + x.id)},
    {label: tr('Move to folder…'), icon: 'folder', fn: () => shf_moveDlg(x)},
    x.folder_id ? {label: tr('Out of the folder'), icon: 'up', fn: () => shf_place(x, null)} : null];
}
sbb_treeReg('sh', {
  move: (id, into) => {
    id = String(id); into = String(into);
    if (id.startsWith('t')) { const x = shf_item(id.slice(1)); if (x) shf_place(x, into.startsWith('f') ? +into.slice(1) : null); return; }
    const f = shf_folder(id.slice(1)); if (f) shf_moveFolder(f, shf_parOf(into));
  },
  order: (id, pos) => shf_order(id, pos),
  menu: id => shf_menuItems(id)});

// ---- the overview: folder cards (a phone opens them by a tap), one folder (#sheets/f/<id>)
function shf_cardsHtml(sp, fid) {
  return shf_kids(sp, fid).map(f => `<li class="shvcard shfcard" data-fid="${f.id}"><a href="#sheets/f/${f.id}" class="shvcl">${ic(f.shared ? 'users' : 'folder')}<span class="shvct"><b>${esc(f.name)}</b>
      <span class="muted">${esc(trn('{0} table', '{0} tables', shf_tables(shf_items(), sp, f.id).length))}</span></span></a>
    <button type="button" class="iconbtn" data-shf="fmenu" data-id="${f.id}" aria-haspopup="menu" title="${esc(tr('More'))}" aria-label="${esc(tr('More') + ': ' + f.name)}">${ic('dots')}</button></li>`).join('');
}
// the overview's tables of sp at its top: those in no folder the person sees
const shf_topItems = (xs, sp) => { const known = new Set(shf_data().folders.map(f => f.id)); return xs.filter(x => x.shared_in || x.space !== sp || !known.has(x.folder_id)); };
function shf_folderView(fid, card) {
  const f = shf_folder(fid), d = SHV.idx.all;
  if (!d || d.v !== S.v) shvLoadIdx('all');
  if (!f) return `<div class="shvwrap shvov"><div class="shvtop"><a class="btn sm" href="#sheets">${ic('back', 's')}${tr('Tables')}</a></div><p class="muted lempty" role="status">${SHF.d && SHF.v !== -1 ? esc(SHF.err || tr('Not found')) : tr('Loading…')}</p></div>`;
  const up = shf_folder(f.parent_id), w = shf_canW(f);
  const head = `<div class="shvtop"><a class="btn sm" href="#${up ? 'sheets/f/' + up.id : 'sheets'}">${ic('back', 's')}<span class="shvbk">${esc(up ? up.name : shvSpaceName(f.space))}</span></a>
    <h2 class="shvh">${ic(f.shared ? 'users' : 'folder', 's')} ${esc(f.name)}</h2><span class="spacer"></span>
    <button type="button" class="iconbtn" data-shf="fmenu" data-id="${f.id}" aria-haspopup="menu" title="${esc(tr('More'))}" aria-label="${esc(tr('More'))}">${ic('dots')}</button>
    ${w ? `<button type="button" class="btn sm pri" data-shf="new" data-id="${f.id}">${ic('plus', 's')}${tr('New table')}</button>` : ''}</div>`;
  const xs = shf_tables(d?.items || [], f.space, f.id), sub = shf_cardsHtml(f.space, f.id);
  if (!sub && !xs.length) return `<div class="shvwrap shvov">${head}<p class="muted lempty">${tr('This folder is empty')}</p></div>`;
  return `<div class="shvwrap shvov">${head}<section class="shvgrp" aria-label="${esc(f.name)}"><ul class="shvcards">${sub}${xs.map(card).join('')}</ul></section></div>`;
}
document.addEventListener('click', e => {
  const a = /** @type {any} */ (e.target).closest?.('[data-shf]'); if (!a || !$('#view')?.contains(a)) return;
  const f = shf_folder(a.dataset.id); if (!f) return;
  if (a.dataset.shf === 'new') shvNew(null, f.id);
  else if (a.dataset.shf === 'fmenu') menu(a, shf_menuItems('f' + f.id).filter(Boolean), null, null, f.name);
});
