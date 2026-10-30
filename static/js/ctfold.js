// @ts-check
/* Kalmido web client: the address book in folders (2.351.0 B, #2749). Address books and single contacts can lie in folders
   of the file store below the workspace's root folder "Address book" (GET /api/contacts/folders: the root per workspace,
   the folders the person sees, the books / contacts filed in them). The panel of the address book draws one entry per
   workspace with the shared tree (sbb_treeHtml): folders (drag to move / sort, menu: New folder, Rename, Share, Move to
   the trash), the books and contacts filed in them. A folder opens as a filter of the contacts list (#contacts/f/<id>), a
   book as the book filter (#contacts/b/<id>). Sharing a folder, a book or a contact in a folder: the one dialog of the file
   store (fs_shareDialog); the books' own sharing (book_members) stays as it is. Classic script sharing the global scope
   with the others (lazy module "contacts", after contacts.js). */
'use strict';

/** @type {{d: any, v: number, at: number, busy: Promise<void>|null, err: string}} */
const CTF = {d: null, v: -1, at: 0, busy: null, err: ''};
// 2.373.0 (#3337): CTF.busy = the running load; a second call waits on it
function ctf_load(force) {
  if (CTF.busy) return CTF.busy;
  if (!force && CTF.d && CTF.v !== -1) return Promise.resolve();
  return (CTF.busy = Promise.resolve().then(ctf_fetch).finally(() => { CTF.busy = null; }));  // busy before the fetch starts
}
async function ctf_fetch() {
  try { CTF.d = {spaces: [], folders: [], items: [], ...(await rawFetch('GET', '/api/contacts/folders'))}; CTF.err = ''; }
  catch (e) { if (e.message === 'auth') return; CTF.err = e.message; CTF.d = CTF.d || {spaces: [], folders: [], items: []}; }
  finally { CTF.v = S.v; CTF.at = Date.now(); }
  if (S.route.mod === 'contacts' && typeof renderSide === 'function') renderSide();
}
// 2.373.0 (#3337): like office_tree.js oft_get -- again after a change (S.v, e.g. another person's folder) at most every few seconds
const ctf_data = () => {
  if (!CTF.d || CTF.v === -1) ctf_load();
  else if (CTF.v !== S.v && Date.now() - CTF.at > 4000) ctf_load(true);
  return CTF.d || {spaces: [], folders: [], items: []};
};
const ctf_folder = id => ctf_data().folders.find(f => f.id === +id) || null;
const ctf_space = sp => ctf_data().spaces.find(s => s.space === sp) || null;
const ctf_canW = f => !!f && (f.role === 'edit' || f.role === 'owner');
const ctf_byNo = (a, b, na, nb) => ((a ?? Infinity) - (b ?? Infinity)) || String(na || '').localeCompare(String(nb || ''), undefined, {sensitivity: 'base'});
const ctf_spaceName = sp => sp === 'private' ? tr('Private|workspace') : typeof wsName === 'function' ? wsName(sp) : sp;
function ctf_kids(sp, pid) {
  const root = ctf_space(sp)?.root;
  return ctf_data().folders.filter(f => f.space === sp && (pid ? f.parent_id === pid : f.parent_id === root)).sort((a, b) => ctf_byNo(a.sort_no, b.sort_no, a.name, b.name));
}
const ctf_items = fid => ctf_data().items.filter(x => x.parent_id === fid).sort((a, b) => ctf_byNo(a.sort_no, b.sort_no, a.name, b.name));
// the node of a book / contact (null: in no folder the person sees)
const ctf_nodeOf = (kind, id) => ctf_data().items.find(x => x.kind === kind && x.id === +id) || null;

// ---- the panel (office panel, on the address book's page)
function ctf_panelTree() {
  const r = S.route, at = r.mod === 'contacts' ? r.ctf || null : null, path = [];
  for (let f = at ? ctf_folder(at) : null, g = 0; f && g < 40; f = ctf_folder(f.parent_id), g++) path.push(f.id);
  const item = (x, par) => ({k: 'ct:' + x.kind[0] + x.id, name: x.name, icon: x.kind === 'book' ? 'book' : 'user', kids: false,
    go: x.kind === 'book' ? 'contacts/b/' + x.id : 'contacts/' + x.id, on: x.kind === 'book' ? r.ctb === x.id : r.mod === 'contacts' && r.contact === x.id,
    ns: 'ct', id: x.kind[0] + x.id, par, drag: !!x.may_file, menu: true});
  const fold = f => ({k: 'ct:f' + f.id, name: f.name, icon: f.shared ? 'users' : 'folder', go: 'contacts/f/' + f.id, on: at === f.id, ns: 'ct', id: 'f' + f.id,
    par: f.parent_id === ctf_space(f.space)?.root ? 'r:' + f.space : 'f' + f.parent_id, drag: ctf_canW(f), drop: ctf_canW(f), menu: true,
    kids: ctf_kids(f.space, f.id).length > 0 || ctf_items(f.id).length > 0, open: path.includes(f.id) && f.id !== at,
    sub: () => [...ctf_kids(f.space, f.id).map(fold), ...ctf_items(f.id).map(x => item(x, 'f' + f.id))]});
  const ws = typeof wsCur === 'function' ? wsCur() : 'all';
  const sps = ctf_data().spaces.filter(s => (s.root || s.can_add) && (!ws || ws === 'all' || s.space === ws));
  return sps.map(s => ({k: 'ct:s:' + s.space, name: ctf_spaceName(s.space), icon: s.space === 'private' ? 'home' : 'building', go: 'contacts',
    ns: 'ct', id: 'r:' + s.space, par: '', drop: !!s.can_add, menu: !!s.can_add, kids: ctf_kids(s.space, null).length > 0, open: true,
    sub: () => ctf_kids(s.space, null).map(fold)}));
}
function ctf_panelHtml() {
  if (S.route.mod !== 'contacts' || typeof sbb_treeHtml !== 'function') return '';
  const nodes = ctf_panelTree(); if (!nodes.length) return '';
  const g = 'office:ctf', fo = typeof sbb_folded === 'function' && sbb_folded(g);
  return `<div class="sgroup sbbp sbbtree ctfpanel" role="group" aria-label="${esc(tr('Folders'))}">${sbb_head(g, tr('Folders'), 0, false)}${fo ? '' : sbb_treeHtml(nodes)}</div>`;
}

// ---- changes
function ctf_after() {
  CTF.v = -1; ctf_load(true);
  if (S.route.mod === 'contacts') { if (S.route.ctf) ctLoad(); else ctDraw(); }
}
const ctf_req = async (m, url, b) => { try { const r = await rawFetch(m, url, b); ctf_after(); return r || true; } catch (e) { toast(e.message); return null; } };
async function ctf_newFolder(sp, pid) {
  const v = await askDialog({title: tr('New folder'), input: {value: '', placeholder: tr('Folder name'), max: 120}, ok: tr('Create'), cancel: undefined, after: undefined});
  if (!v || !v.trim()) return;
  const r = await ctf_req('POST', '/api/contacts/folders', {name: v.trim(), space: sp, ...(pid ? {parent_id: pid} : {})});
  if (r?.folder) { const x = new Set(LS.get('sbbOpen', []) || []); x.add('ct:s:' + sp); if (pid) x.add('ct:f' + pid); LS.set('sbbOpen', [...x].slice(-300)); }
  return r?.folder || null;
}
async function ctf_rename(f) {
  const v = await askDialog({title: tr('Rename folder'), input: {value: f.name, placeholder: tr('Folder name'), max: 120}, ok: tr('Save'), cancel: undefined, after: undefined});
  if (!v || !v.trim() || v.trim() === f.name) return;
  await ctf_req('PATCH', `/api/files/nodes/${f.id}`, {name: v.trim()});
}
async function ctf_delete(f) {
  const r = await ctf_req('DELETE', `/api/files/nodes/${f.id}`); if (!r) return;
  if (S.route.mod === 'contacts' && S.route.ctf === f.id) go('contacts');
  const kept = typeof fs_keptText === 'function' ? fs_keptText(r.kept) : (r.kept || []).map(k => k.reason).join(', ');
  offerUndo([tr('“{0}” moved to the trash', f.name), kept].filter(Boolean).join(' · '), histAdd({label: tr('Delete “{0}”', f.name),
    undo: async () => { await rawFetch('POST', `/api/files/nodes/${f.id}/restore`); ctf_after(); return {skipped: []}; },
    redo: async () => { await rawFetch('DELETE', `/api/files/nodes/${f.id}`); ctf_after(); return {skipped: []}; }}));
}
// a folder, or a book / contact in a folder: the file store's Share dialog
const ctf_share = nid => fs_shareDialog(nid, {onChange: ctf_after, hint: tr('A shared address book works like sharing it in the address book: its contacts can be read or changed as the role says. Agents only see what is shared with exactly them.')});
// a book ('book') / contact ('contact') into folder fid (null: into no folder)
async function ctf_place(kind, id, name, fid) {
  const was = ctf_nodeOf(kind, id)?.parent_id ?? null;
  if ((fid || null) === was) return;
  const rk = kind === 'book' ? 'address_book' : 'contact';
  const put = v => rawFetch('POST', '/api/files/refs', {ref_kind: rk, ref_id: +id, parent_id: v});
  if (!await ctf_req('POST', '/api/files/refs', {ref_kind: rk, ref_id: +id, parent_id: fid || null})) return;
  offerUndo(tr('“{0}” moved', name), histAdd({label: tr('Move “{0}”', name), undo: async () => { await put(was); ctf_after(); return {skipped: []}; },
    redo: async () => { await put(fid || null); ctf_after(); return {skipped: []}; }}));
}
async function ctf_moveFolder(f, pid) {
  const was = f.parent_id;
  if (!pid || pid === was || pid === f.id) return;
  if (!await ctf_req('PATCH', `/api/files/nodes/${f.id}`, {parent_id: pid})) return;
  offerUndo(tr('“{0}” moved', f.name), histAdd({label: tr('Move “{0}”', f.name),
    undo: async () => { await rawFetch('PATCH', `/api/files/nodes/${f.id}`, {parent_id: was}); ctf_after(); return {skipped: []}; },
    redo: async () => { await rawFetch('PATCH', `/api/files/nodes/${f.id}`, {parent_id: pid}); ctf_after(); return {skipped: []}; }}));
}
// "Move to folder…": the folders of the workspace sp the person may add to, "No folder", "New folder…"
async function ctf_moveDlg(kind, id, name, sp, anchor) {
  if (!CTF.d || CTF.v === -1) await ctf_load(true);
  const cur = ctf_nodeOf(kind, id);
  const path = f => { const p = []; for (let y = f, g = 0; y && g < 40; y = ctf_folder(y.parent_id), g++) p.unshift(y.name); return p.join(' / '); };
  const fs = ctf_data().folders.filter(f => f.space === sp && ctf_canW(f) && f.id !== cur?.parent_id);
  const s = ctf_space(sp);
  menu(anchor || document.body, [...(cur ? [{label: tr('No folder'), icon: 'up', fn: () => ctf_place(kind, id, name, null)}] : []),
    ...fs.map(f => ({label: path(f), icon: 'folder', fn: () => ctf_place(kind, id, name, f.id)})),
    s?.can_add ? {label: tr('New folder…'), icon: 'plus', fn: async () => { const f = await ctf_newFolder(sp, null); if (f) ctf_place(kind, id, name, f.id); }} : null].filter(Boolean),
  null, null, tr('Move to folder…'));
}
const ctf_parOf = par => String(par).startsWith('f') ? +String(par).slice(1) : String(par).startsWith('r:') ? ctf_space(String(par).slice(2))?.root ?? null : null;
const ctf_itemOf = id => { id = String(id); const k = id[0] === 'b' ? 'book' : id[0] === 'c' ? 'contact' : ''; return k ? ctf_nodeOf(k, id.slice(1)) : null; };
async function ctf_order(id, pos) {
  const x = ctf_itemOf(id), f = x ? null : ctf_folder(String(id).slice(1));
  if (!x && !f) return;
  if (pos.into !== undefined) {  // dropped next to a node of another folder: into that folder
    const pid = ctf_parOf(pos.into);
    if (x) { if (String(pos.into).startsWith('f')) ctf_place(x.kind, x.id, x.name, pid); } else if (pid) ctf_moveFolder(f, pid);
    return;
  }
  const sib = String(pos.before || pos.after), sx = ctf_itemOf(sib), sibNode = sx ? sx.node : sib.startsWith('f') ? +sib.slice(1) : null;
  const node = x ? x.node : f.id;
  if (!node || !sibNode) return;
  await ctf_req('POST', `/api/files/nodes/${node}/order`, pos.before ? {before: sibNode} : {after: sibNode});
}
function ctf_menuItems(id) {
  id = String(id);
  if (id.startsWith('r:')) {
    const sp = id.slice(2), s = ctf_space(sp); if (!s?.can_add) return [];
    return [{label: tr('New folder…'), icon: 'plus', fn: () => ctf_newFolder(sp, null)}];
  }
  if (id.startsWith('f')) {
    const f = ctf_folder(id.slice(1)); if (!f) return [];
    const w = ctf_canW(f);
    return [{label: tr('Open'), icon: 'folder', fn: () => go('contacts/f/' + f.id)},
      w ? {label: tr('New folder…'), icon: 'plus', fn: () => ctf_newFolder(f.space, f.id)} : null,
      f.role === 'owner' ? {label: tr('Share…'), icon: 'users', fn: () => ctf_share(f.id)} : null,
      '-', w ? {label: tr('Rename…'), icon: 'edit', fn: () => ctf_rename(f)} : null,
      '-', w ? {label: tr('Move to the trash'), icon: 'trash', cls: 'danger', fn: () => ctf_delete(f)} : null];
  }
  const x = ctf_itemOf(id); if (!x) return [];
  return [{label: tr('Open'), icon: x.kind === 'book' ? 'book' : 'user', fn: () => go(x.kind === 'book' ? 'contacts/b/' + x.id : 'contacts/' + x.id)},
    x.may_file ? {label: tr('Move to folder…'), icon: 'folder', fn: () => ctf_moveDlg(x.kind, x.id, x.name, x.space)} : null,
    x.may_file ? {label: tr('Share…'), icon: 'users', fn: () => ctf_share(x.node)} : null,
    x.may_file ? {label: tr('Out of the folder'), icon: 'up', fn: () => ctf_place(x.kind, x.id, x.name, null)} : null];
}
sbb_treeReg('ct', {
  move: (id, into) => {
    into = String(into);
    const x = ctf_itemOf(id);
    if (x) { if (into.startsWith('f')) ctf_place(x.kind, x.id, x.name, +into.slice(1)); return; }
    const f = ctf_folder(String(id).slice(1)); if (f) ctf_moveFolder(f, ctf_parOf(into));
  },
  order: (id, pos) => ctf_order(id, pos),
  menu: id => ctf_menuItems(id)});

// ---- the contacts list: the folder filter (#contacts/f/<id>) and the book filter (#contacts/b/<id>)
function ctf_barHtml() {
  const f = CT.folder ? ctf_folder(CT.folder) : null; if (!CT.folder) return '';
  return `<div class="ctfbar" role="status">${ic(f?.shared ? 'users' : 'folder', 's')}<span>${esc(f ? f.name : tr('Folder'))}</span>${f?.role === 'owner' ? `<button type="button" class="btn sm" data-ctf="share">${ic('users', 's')}${tr('Share…')}</button>` : ''}<button type="button" class="iconbtn" data-ctf="clear" title="${esc(tr('All contacts'))}" aria-label="${esc(tr('All contacts'))}">${ic('x', 's')}</button></div>`;
}
document.addEventListener('click', e => {
  const b = /** @type {any} */ (e.target).closest?.('#view [data-ctf]'); if (!b) return;
  if (b.dataset.ctf === 'clear') go('contacts'); else if (b.dataset.ctf === 'share' && CT.folder) ctf_share(CT.folder);
});
// the menu items of a contact's card and of an address book (contacts.js): file it, share it in its folder
// filing and sharing need the right to manage the address book (its owner; neither a folder nor a book share is enough)
function ctf_cardItems(c) {
  const b = ctBook(c.book_id), x = ctf_nodeOf('contact', c.id);
  if (!b || b.role !== 'owner' || b.imported) return [];
  return [{label: tr('Move to folder…'), icon: 'folder', fn: () => ctf_moveDlg('contact', c.id, c.fn || c.org || '?', b.org_id ? 'org:' + b.org_id : 'private')},
    x ? {label: tr('Share…'), icon: 'users', fn: () => ctf_share(x.node)} : null];
}
function ctf_bookItems(b, anchor) {
  if (b.role !== 'owner' || b.imported) return [];
  const sp = b.org_id ? 'org:' + b.org_id : 'private';
  return [{label: tr('Move to folder…'), icon: 'folder', fn: () => ctf_moveDlg('book', b.id, b.name, sp, anchor)}];
}
