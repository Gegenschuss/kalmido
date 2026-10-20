/* Kalmido web client: the file store "Ablage" (2.48.0, #1207). Folders and files per person and per organisation, shared
   with people, groups and agents (view / edit, inherited by everything below, optional expiry), versions, trash with undo,
   the history of every agent access. Route #ablage (the top of the shown space) and #ablage/<id> (a folder, or a file:
   its folder with the file's details). The rules live on the server (kalmido/files); this module only shows them.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

const ab_on = () => feat('files') && !S.me?.kid;
FEAT_DESC.files = N_('Folders and files of your own and of your organisation; share them with people, groups and agents (view or edit, with an end date), versions and a trash');
const AB = {space: LS.get('abSpace', ''), key: '', dkey: '', data: null, err: '', loading: false, seq: 0, sel: new Set(), drag: null};
const ab_spaces = () => { const w = wsCur(); return [...(w === 'all' || w === 'private' || !wsOn() ? ['private'] : []), ...(wsOn() ? (S.me?.workspaces || []).filter(o => w === 'all' || w === 'org:' + o.id).map(o => 'org:' + o.id) : []), 'shared', 'trash']; };
const ab_spaceName = s => s === 'private' ? tr('My files') : s === 'shared' ? tr('Shared with me') : s === 'trash' ? tr('Trash') : wsName(s);
const ab_spaceIcon = s => s === 'private' ? ic('home', 's') : s === 'shared' ? ic('users', 's') : s === 'trash' ? ic('trash', 's') : wsIcon(s);
const ab_curSpace = () => { const sp = ab_spaces(); return sp.includes(AB.space) ? AB.space : sp[0]; };
const ab_url = (n, dl, v) => `/api/files/nodes/${n.id}/content?${[dl ? 'dl=1' : '', v ? 'v=' + v : ''].filter(Boolean).join('&')}`;
const ab_isImg = n => /^image\/(png|jpe?g|gif|webp|avif)$/.test(n.mime || '');
const ab_isPdf = n => n.mime === 'application/pdf';
const ab_canWrite = r => r === 'owner' || r === 'edit';
const ab_role = r => r === 'owner' ? tr('Owner') : r === 'edit' ? tr('Can edit') : r === 'view' ? tr('Can view') : '';
const ab_when = iso => iso ? fmtDay('short', new Date(iso)) : '';
const ab_icon = n => n.kind === 'folder' ? ic(n.agent_id ? 'bot' : 'folder') : n.kind === 'link' ? ic('link') : ab_isPdf(n) ? ic('pdf') : ab_isImg(n) ? ic('picture') : ic('file');

// ---- loading
async function ab_load() {
  const r = S.route, key = r.nid ? 'n:' + r.nid : 's:' + ab_curSpace(), seq = ++AB.seq;
  AB.key = key; AB.loading = true;
  try {
    const j = await api('GET', r.nid ? `/api/files?parent=${r.nid}` : `/api/files?space=${encodeURIComponent(ab_curSpace())}`);
    if (seq !== AB.seq) return;
    AB.data = j; AB.dkey = key; AB.err = '';
  } catch (x) {
    if (seq !== AB.seq) return;
    if (r.nid) {  // a file: open its folder and the file's details
      try { const n = await api('GET', `/api/files/nodes/${r.nid}`); if (n.kind !== 'folder') { AB.loading = false; go(n.parent_id ? 'ablage/' + n.parent_id : 'ablage'); setTimeout(() => ab_details(n.id), 50); return; } } catch { /* below */ }
    }
    AB.data = null; AB.dkey = ''; AB.err = x.message || tr('unknown');
  }
  AB.loading = false;
  ab_draw();
}
function ab_draw() { if (S.route.mod !== 'ablage') return; const el = $('#view'); if (el) keepFocus(el, () => setHtml(el, mg_wrap('ablage', viewAblage()))); }
const ab_reload = () => { AB.key = ''; if (S.route.mod === 'ablage') ab_load(); };

// ---- the view
function viewAblage() {
  if (!ab_on()) return `<div class="empty">${tr('The file store is off (Settings > Modules)')}</div>`;
  if (typeof dt_abOn !== 'function' && typeof ld_later === 'function') ld_later('tagsel');  // 2.122.0 B (#2099 #2295): tags, Shift ranges
  const r = S.route, key = r.nid ? 'n:' + r.nid : 's:' + ab_curSpace();
  if (AB.key !== key && !AB.loading) setTimeout(ab_load, 0);
  const d = AB.dkey === key ? AB.data : null, sp = r.nid ? (d?.space || '') : ab_curSpace();
  // the tree: the spaces; below the open one the path down to the open folder and its subfolders (desktop; phones: the path on top)
  const tree = r.nid && d ? [...(d.crumbs || []).map((c, i) => ({id: c.id, name: c.name, lvl: i + 1, on: c.id === r.nid})),
    ...d.items.filter(n => n.kind === 'folder').map(n => ({id: n.id, name: n.name, lvl: (d.crumbs || []).length + 1, sub: true}))] : [];
  const treeHtml = tree.map(t => `<button type="button" class="abspace abtree ${t.on ? 'on' : ''}" style="--ablvl:${Math.min(t.lvl, 6)}" data-go="ablage/${t.id}" data-abdrop="${t.id}" ${t.on ? 'aria-current="page"' : ''}>${ic('folder', 's')}<span>${esc(t.name)}</span></button>`).join('');
  const spaces = `<nav class="abspaces" aria-label="${esc(tr('File store'))}">${ab_spaces().map(s => `<button type="button" class="abspace ${!r.nid && s === sp ? 'on' : ''}" data-ab="space" data-sp="${esc(s)}" ${!r.nid && s === sp ? 'aria-current="page"' : ''}>${ab_spaceIcon(s)}<span>${esc(ab_spaceName(s))}</span></button>${r.nid && s === (sp || 'shared') ? treeHtml : ''}`).join('')}</nav>`;
  const trash = !r.nid && sp === 'trash', canAdd = r.nid ? ab_canWrite(d?.node?.role) : (sp === 'private' || (sp || '').startsWith('org:'));
  const crumbs = r.nid && d ? `<nav class="abcrumbs" aria-label="${esc(tr('Path'))}"><button type="button" class="linkbtn" data-ab="space" data-sp="${esc(sp === 'shared' || !sp ? 'shared' : sp)}" data-abdrop="top">${esc(ab_spaceName(sp || 'shared'))}</button>${(d.crumbs || []).map((c, i, a) => `<span class="abcsep" aria-hidden="true">/</span>${i === a.length - 1 ? `<span class="abccur" aria-current="page">${esc(c.name)}</span>` : `<button type="button" class="linkbtn" data-go="ablage/${c.id}" data-abdrop="${c.id}">${esc(c.name)}</button>`}`).join('')}</nav>` : `<h3 class="abtitle">${esc(ab_spaceName(sp))}</h3>`;
  const tools = trash ? '' : `<div class="abtools">${canAdd ? `<button type="button" class="btn sm" data-ab="new-folder">${ic('folder', 's')} ${tr('New folder')}</button><button type="button" class="btn sm pri" data-ab="upload">${ic('upload', 's')} ${tr('Upload')}</button><button type="button" class="btn sm" data-ab="scan">${ic('camera', 's')} ${tr('Scan')}</button><input type="file" id="ab-file" multiple hidden>` : ''}${typeof dt_abOn === 'function' && dt_abOn(sp || d?.space) ? '' : ab_smvTools(d)}${typeof dt_abBtn === 'function' ? dt_abBtn(sp || d?.space) : ''}${r.nid && d?.node ? `<button type="button" class="iconbtn" data-ab="menu" data-id="${d.node.id}" aria-label="${esc(tr('More actions for {0}', d.node.name))}" title="${esc(tr('More'))}">${ic('dots')}</button>` : ''}</div>`;
  let body;
  if (AB.err && AB.key === key) body = `<div class="empty">${ic('folder')}<span>${esc(AB.err)}</span><button type="button" class="btn" data-ab="space" data-sp="private">${tr('My files')}</button></div>`;
  else if (!d) body = `<p class="muted lempty">${tr('Loading…')}</p>`;
  else if (!d.items.length) body = `<div class="empty abempty">${ic(trash ? 'trash' : 'folder')}<span>${trash ? tr('The trash is empty') : sp === 'shared' && !r.nid ? tr('Nothing is shared with you yet') : canAdd ? tr('Drop files here or use “Upload”') : tr('This folder is empty')}</span></div>`;
  else body = `<div class="ablist${AB.selOn ? ' abselon' : ''}" role="list">${d.items.map(n => ab_rowHtml(n, trash)).join('')}</div>`;
  if (d && typeof dt_abOn === 'function' && dt_abOn(sp || d.space)) body = dt_abBody(sp || d.space);  // 2.122.0 B (#2099): the tag filter of the space
  const search = !trash && typeof ftxtBox === 'function' ? ftxtBox() : '';  // 2.61.0 (#1820): names + recognised text
  if (search && ftxtActive()) body = ftxtResults();
  const hint = !r.nid && sp === 'private' && d && !d.items.length ? `<p class="muted abhint">${tr('Share a folder with a person or an agent: they see exactly that folder, nothing else.')}</p>` : '';
  return `<div class="abview ${canAdd ? 'abdropok' : ''}" data-abzone="${r.nid || ''}">${spaces}<div class="abmain">${search}${search && ftxtActive() ? `<h3 class="abtitle">${tr('Search results')}</h3>` : crumbs + tools}${body}${search && ftxtActive() ? '' : hint + (trash ? '' : ab_smvBar())}</div></div>`;
}
function ab_rowHtml(n, trash) {
  const meta = [n.path || '', n.kind === 'folder' ? '' : fmtSize(n.size || 0), ab_when(trash ? n.deleted_at : n.updated_at), n.created_by_name && n.created_by !== S.me?.id ? n.created_by_name : ''].filter(Boolean).join(' · ');
  const badges = (n.shared ? `<span class="abbadge" title="${esc(tr('Shared'))}" aria-label="${esc(tr('Shared'))}">${ic('users', 's')}</span>` : '')
    + (n.agent_id ? `<span class="abbadge" title="${esc(tr('Folder of an agent'))}">${ic('bot', 's')}</span>` : '')
    + (n.version > 1 ? `<span class="abver" title="${esc(tr('Version {0}', n.version))}">v${n.version}</span>` : '')
    + upMarkHtml(n.up)  // 2.61.0 (#1818): not checked by the virus scanner yet / locked
    + (typeof xl_badge === 'function' ? xl_badge(n) : '');  // 2.112.1 B (#2058): a live external link
  const main = trash ? `<span class="abopen">${ab_icon(n)}<span class="abtxt"><span class="abname">${esc(n.name)}</span>${meta ? `<span class="abmeta2 muted">${esc(meta)}</span>` : ''}</span></span>`
    : `<button type="button" class="abopen" data-ab="open" data-id="${n.id}" ${n.kind === 'folder' ? `data-abdrop="${n.id}"` : ''}>${ab_icon(n)}<span class="abtxt"><span class="abname">${esc(n.name)}</span>${meta ? `<span class="abmeta2 muted">${esc(meta)}</span>` : ''}</span></button>`;  // abmeta2: the details below the name on phones
  const acts = trash ? `<button type="button" class="btn sm" data-ab="restore" data-id="${n.id}">${ic('undo', 's')} ${tr('Restore')}</button>`
    : `<button type="button" class="iconbtn" data-ab="menu" data-id="${n.id}" aria-label="${esc(tr('More actions for {0}', n.name))}" title="${esc(tr('More'))}">${ic('dots')}</button>`;
  return `<div class="abrow" role="listitem" data-abid="${n.id}" ${!trash && ab_canWrite(n.role) ? 'draggable="true"' : ''}>${trash ? '' : ab_smvBox(n)}${main}${typeof dt_abTags === 'function' ? dt_abTags(n) : ''}<span class="abmeta muted">${esc(meta)}</span><span class="abbadges">${badges}</span>${acts}</div>`;
}
const ab_item = id => (AB.data?.items || []).find(x => x.id === +id) || (AB.data?.node?.id === +id ? AB.data.node : null) || (typeof ftxtItem === 'function' ? ftxtItem(id) : null) || (typeof dt_abItem === 'function' ? dt_abItem(id) : null);  // 2.61.0 (#1820): + search hits; 2.122.0 B: + tag filter hits

// ---- opening a file: images in the lightbox, PDFs in the PDF view, text in the text view, the rest downloads
function ab_openFile(n) {
  if (upLocked(n)) { toast(tr('Locked: malware was found in this file ({0})', n.up.sig || '?')); return; }  // 2.61.0 (#1818)
  if (ab_isImg(n)) { const imgs = (AB.data?.items || []).filter(x => ab_isImg(x) && !upLocked(x)); attLightbox(n.id, imgs, (a, dl) => ab_url(a, dl)); return; }
  if (n.kind === 'file' && dv_is(n)) { dpvOpen({url: `/api/files/nodes/${encodeURIComponent(n.id)}/preview`, name: n.name, size: n.size, dlUrl: ab_url(n, true)}); return; }  // 2.92.0 C (#1926)
  if (ab_isPdf(n)) { if (typeof pdfView === 'function') pdfView({url: ab_url(n), name: n.name, size: n.size, dlUrl: ab_url(n, true)}); else window.open(ab_url(n), '_blank', 'noopener'); return; }
  if (isTextFile(n) && (n.size || 0) <= TV_MAX) { textView({url: ab_url(n, true), name: n.name, size: n.size, md: isMdFile(n), ext: attExt(n)}); return; }
  const a = document.createElement('a'); a.href = ab_url(n, true); a.download = n.name; document.body.appendChild(a); a.click(); a.remove();
}

// ---- actions (each one = ONE undo step)
async function ab_newFolder() {
  const name = await askPrompt(tr('New folder'), '', {ok: tr('Create'), input: {placeholder: tr('Name'), max: 150}});
  if (!name || !name.trim()) return;
  const b = S.route.nid ? {parent_id: S.route.nid, name} : {space: ab_curSpace(), name};
  let n; try { n = await api('POST', '/api/files/folders', b); } catch { return; }
  ab_reload();
  offerUndo(tr('Folder “{0}” created', n.name), histAdd({label: tr('New folder “{0}”', n.name), undo: () => ab_req('DELETE', `/api/files/nodes/${n.id}`), redo: () => ab_req('POST', `/api/files/nodes/${n.id}/restore`)}));
}
// a request of an undo / redo step: the view follows, an error is a toast (api() shows it)
async function ab_req(m, url, b) { try { await api(m, url, b); } catch { /* shown */ } ab_reload(); return {}; }
async function ab_upload(files, target) {
  files = [...(files || [])]; if (!files.length) return;
  const fd = new FormData();
  for (const f of files) fd.append('file', f, f.name);
  if (target) fd.append('parent_id', String(target)); else fd.append('space', ab_curSpace());
  const old = new Set((AB.data?.items || []).map(x => x.id));
  toast(trn('Uploading {0} file…', 'Uploading {0} files…', files.length));
  let j; try { j = await api('POST', '/api/files/upload', fd); } catch { return; }
  ab_reload();
  const created = (j.items || []).filter(x => !old.has(x.id) && x.version <= 1), ver = (j.items || []).length - created.length;
  const msg = ver ? tr('{0} uploaded, {1} as a new version', (j.items || []).length, ver) : trn('{0} file uploaded', '{0} files uploaded', created.length);
  if (!created.length) { toast(msg); return; }
  offerUndo(msg, histAdd({label: tr('Upload'), undo: async () => { for (const x of created) await ab_req('DELETE', `/api/files/nodes/${x.id}`); return {}; },
    redo: async () => { for (const x of created) await ab_req('POST', `/api/files/nodes/${x.id}/restore`); return {}; }}));
}
async function ab_rename(n) {
  const name = await askPrompt(tr('Rename'), n.name, {ok: tr('Save'), input: {max: 150}});
  if (!name || !name.trim() || name === n.name) return;
  let r; try { r = await api('PATCH', `/api/files/nodes/${n.id}`, {name}); } catch { return; }
  ab_reload();
  const was = n.name;
  offerUndo(tr('Renamed to “{0}”', r.name), histAdd({label: tr('Rename “{0}”', was), undo: () => ab_req('PATCH', `/api/files/nodes/${n.id}`, {name: was}), redo: () => ab_req('PATCH', `/api/files/nodes/${n.id}`, {name: r.name})}));
}
async function ab_move(n, target) {
  if (target === undefined) return ab_moveDlg(n);
  const was = n.parent_id ?? null;
  if ((target || null) === was) return;
  try { await api('PATCH', `/api/files/nodes/${n.id}`, {parent_id: target || null}); } catch { return; }
  ab_reload();
  offerUndo(tr('“{0}” moved', n.name), histAdd({label: tr('Move “{0}”', n.name), undo: () => ab_req('PATCH', `/api/files/nodes/${n.id}`, {parent_id: was}), redo: () => ab_req('PATCH', `/api/files/nodes/${n.id}`, {parent_id: target || null})}));
}
async function ab_moveDlg(n) {
  let fs; try { fs = (await api('GET', '/api/files/folders')).folders; } catch { return; }
  // the same space and tree only (the server refuses the rest, and a folder into itself)
  const ok = fs.filter(f => (f.org_id || null) === (n.org_id || null) && f.owner_id === n.owner_id && f.id !== n.id && f.id !== n.parent_id);
  const items = [...(n.parent_id ? [{label: tr('Top level'), icon: 'up', fn: () => ab_move(n, null)}] : []), ...ok.map(f => ({label: f.path, icon: 'folder', fn: () => ab_move(n, f.id)}))];
  if (!items.length) { toast(tr('No other folder in this space')); return; }
  const anchor = $(`[data-abid="${n.id}"] [data-ab="menu"]`) || $('[data-ab="menu"]') || document.body;
  menu(anchor, [{head: tr('Move to …')}, ...items.slice(0, 60)], null, null, tr('Move to …'));
}
async function ab_delete(n) {
  try { await api('DELETE', `/api/files/nodes/${n.id}`); } catch { return; }
  if (S.route.nid === n.id) go(n.parent_id ? 'ablage/' + n.parent_id : 'ablage'); else ab_reload();
  offerUndo(tr('“{0}” moved to the trash', n.name), histAdd({label: tr('Delete “{0}”', n.name), undo: () => ab_req('POST', `/api/files/nodes/${n.id}/restore`), redo: () => ab_req('DELETE', `/api/files/nodes/${n.id}`)}));
}
async function ab_restore(n) {
  try { await api('POST', `/api/files/nodes/${n.id}/restore`); } catch { return; }
  ab_reload();
  offerUndo(tr('“{0}” restored', n.name), histAdd({label: tr('Restore “{0}”', n.name), undo: () => ab_req('DELETE', `/api/files/nodes/${n.id}`), redo: () => ab_req('POST', `/api/files/nodes/${n.id}/restore`)}));
}
async function ab_purge(n) {
  if (!await askConfirm(tr('Delete “{0}” for good?', n.name), tr('All versions are removed. This cannot be undone.'), {ok: tr('Delete for good'), danger: true})) return;
  try { await api('DELETE', `/api/files/nodes/${n.id}?purge=1`); } catch { return; }
  ab_reload(); toast(tr('Deleted for good'));
}
function ab_newVersion(n) {
  const inp = document.createElement('input'); inp.type = 'file';
  inp.addEventListener('change', async () => {
    const f = inp.files?.[0]; if (!f) return;
    const fd = new FormData(); fd.append('file', f, f.name);
    try { await api('POST', `/api/files/nodes/${n.id}/versions`, fd); } catch { return; }
    ab_reload(); toast(tr('New version of “{0}” saved', n.name));
    if ($('.abdlg')) ab_details(n.id);
  });
  inp.click();
}
function ab_menu(anchor, n) {
  const w = ab_canWrite(n.role), own = n.role === 'owner', f = n.kind !== 'folder';
  menu(anchor, [
    f ? {label: tr('Open'), icon: 'eye', fn: () => ab_openFile(n)} : null,
    f ? {label: tr('Download'), icon: 'download', fn: () => { const a = document.createElement('a'); a.href = ab_url(n, true); a.download = n.name; document.body.appendChild(a); a.click(); a.remove(); }} : null,
    n.kind === 'folder' ? {label: tr('Download as ZIP'), icon: 'download', fn: () => abm_download([n])} : null,  // 2.112.1 A (#2058)
    {label: tr('Details and history'), icon: 'info', fn: () => ab_details(n.id)},
    w && n.kind === 'folder' && !n.agent_id ? {label: tr('Request files…'), icon: 'upload', fn: () => frq_open(n)} : null,  // 2.122.0 A (#2097)
    own ? {label: tr('Share…'), icon: 'users', fn: () => ab_share(n.id)} : null,
    typeof xl_menuItem === 'function' ? xl_menuItem(n) : null,  // 2.112.1 B (#2058)
    '-',
    w && n.kind === 'file' ? {label: tr('Upload a new version…'), icon: 'upload', fn: () => ab_newVersion(n)} : null,
    w ? {label: tr('Rename…'), icon: 'edit', fn: () => ab_rename(n)} : null,
    w && typeof dt_abEdit === 'function' ? {label: tr('Tags…'), icon: 'tag', fn: () => dt_abEdit(n)} : null,  // 2.122.0 B (#2099)
    w ? {label: tr('Move to…'), icon: 'arrow', fn: () => ab_moveDlg(n)} : null,
    ab_smvOk(n) && smv_can(n.org_id) ? {label: tr('Move to another workspace…'), icon: 'building', fn: () => ab_smvSpace([n])} : null,  // 2.96.0 A (#1941)
    '-',
    w && (n.parent_id || own) ? {label: tr('Move to the trash'), icon: 'trash', cls: 'danger', fn: () => ab_delete(n)} : null], null, null, n.name);
}

// ---- details: versions, shares, history
const AB_ACT = {list: N_('opened the folder'), read: N_('read'), download: N_('downloaded'), text: N_('read the text'), meta: N_('looked at the details'),
  write: N_('created'), upload: N_('uploaded'), version: N_('uploaded a new version'), restore_version: N_('restored a version'), rename: N_('renamed'),
  move: N_('moved'), trash: N_('moved to the trash'), restore: N_('restored'), share: N_('shared'), share_change: N_('changed a share'),
  unshare: N_('stopped sharing'), org_access: N_('changed who in the organisation sees it'), create: N_('created'), link: N_('linked'),
  moved_space: N_('moved to another workspace'),  // 2.96.0 A (#1941)
  tags: N_('changed the tags')};  // 2.122.0 B (#2099)
// 2.123.0 C (#2103, #2107): the knowledge pages (that I may read) which show or link this file
async function ab_wikiRefs(md, id) {
  let ps; try { ps = (await rawFetch('GET', '/api/wiki/refs?file=' + id)).pages || []; } catch { return; }
  if (!ps.length || !md.isConnected) return;
  const sec = document.createElement('div');
  sec.className = 'dsec wkmen';
  sec.innerHTML = `${ic('book', 's')}<span class="muted">${tr('Mentioned in')}</span>${ps.map(p => `<a href="#wiki/${p.id}" data-m="close">${esc(p.path)}</a>`).join('<span class="muted">,</span>')}`;
  $('.foot', md)?.before(sec);
}
async function ab_details(id) {
  let n; try { n = await api('GET', `/api/files/nodes/${id}`); } catch { return; }
  $('.abdlg')?.remove();
  const vers = (n.versions || []).map(v => `<div class="abvrow"><span><b>v${v.no}</b> · ${esc(ab_when(v.created_at))} · ${fmtSize(v.size)}${v.by ? ' · ' + esc(v.by) : ''}</span><span class="spacer"></span><a class="iconbtn" href="${ab_url(n, true, v.no)}" download="${esc(n.name)}" title="${esc(tr('Download'))}" aria-label="${esc(tr('Download version {0}', v.no))}">${ic('download', 's')}</a>${ab_canWrite(n.role) && v.no !== n.version ? `<button type="button" class="btn sm" data-abv="${v.no}">${tr('Restore')}</button>` : ''}</div>`).join('');
  const log = (n.log || []).map(x => `<div class="ablrow ${x.agent ? 'abag' : ''}">${x.agent ? ic('bot', 's') : ic('user', 's')}<span><b>${esc(x.name || (typeof xl_logWho === 'function' && xl_logWho(x)) || '?')}</b> ${esc(tr(AB_ACT[x.action] || x.action))}</span><span class="spacer"></span><small class="muted">${esc(fmtDay('short', new Date(x.at)))} ${esc(new Date(x.at).toLocaleTimeString(LOCALE(), {hour: '2-digit', minute: '2-digit'}))}</small></div>`).join('');
  const shares = n.role === 'owner' ? [...(n.shares || []), ...(n.inherited || [])] : [];
  const md = modal(`<div class="lhdr"><h3>${ab_icon(n)} ${esc(n.name)}</h3><span class="spacer"></span><button class="iconbtn" data-m="close" aria-label="${tr('Close')}" title="${tr('Close')}">${ic('x')}</button></div>
    <div class="muted abpath">${esc((n.crumbs || []).map(c => c.name).join(' / '))}</div>
    <div class="abfacts">${n.kind !== 'folder' ? `<span>${fmtSize(n.size || 0)}</span>` : ''}<span>${esc(tr('Changed {0}', ab_when(n.updated_at)))}</span>${n.owner ? `<span>${esc(tr('Owner: {0}', n.owner))}</span>` : ''}<span>${esc(ab_role(n.role))}</span></div>
    ${typeof dt_abDetails === 'function' ? dt_abDetails(n) : ''}
    ${n.kind === 'link' ? `<div class="shint keep">${ic('link', 's')} ${esc(tr('A link to a file of a task or project. Whoever opens it needs access to the original.'))}</div>` : ''}
    ${n.kind !== 'folder' ? `<div class="row"><button type="button" class="btn sm" data-abd="open">${ic('eye', 's')} ${tr('Open')}</button>${ab_canWrite(n.role) && n.kind === 'file' ? `<button type="button" class="btn sm" data-abd="ver">${ic('upload', 's')} ${tr('Upload a new version…')}</button>` : ''}</div>` : ''}
    ${vers ? `<h4>${tr('Versions')}</h4><div class="abvers">${vers}</div>` : ''}
    ${n.role === 'owner' ? `<h4>${tr('Shared with')}</h4><div class="abshsum">${shares.length || n.org_access || n.org_access_from ? shares.map(s => `<span class="abshp">${s.agent_id ? ic('bot', 's') : s.group_id ? ic('users', 's') : ic('user', 's')}${esc(s.name)} · ${esc(ab_role(s.role))}${s.from ? ` <small class="muted">${esc(tr('from “{0}”', s.from))}</small>` : ''}</span>`).join('') + (n.org_access || n.org_access_from ? `<span class="abshp">${ic('building', 's')}${esc(tr('Whole organisation'))}</span>` : '') : `<span class="muted">${tr('Only you')}</span>`}</div><div class="row"><button type="button" class="btn sm" data-abd="share">${ic('users', 's')} ${tr('Share…')}</button></div>` : ''}
    ${n.log ? `<h4>${tr('History')}</h4><div class="ablog">${log || `<span class="muted">${tr('Nothing yet')}</span>`}</div><p class="muted abhint">${tr('Every access of an agent is listed here.')}</p>` : ''}
    <div class="foot"><span class="spacer"></span><button class="btn pri" data-m="close">${tr('Done')}</button></div>`);
  md.classList.add('abdlg');
  if (n.kind === 'file' && feat('wiki')) ab_wikiRefs(md, n.id);  // 2.123.0 C (#2107)
  if (typeof xl_mount === 'function') xl_mount(md, n);  // 2.112.1 B (#2058): "Link for external people"
  md.addEventListener('click', async e => {
    if (e.target.closest('[data-m="close"]')) { modalClose(md); return; }
    const v = e.target.closest('[data-abv]');
    if (v) {
      const no = +v.dataset.abv; let r; try { r = await api('POST', `/api/files/nodes/${n.id}/versions/${no}/restore`); } catch { return; }
      toast(tr('Version {0} is the newest again (as version {1})', no, r.version)); ab_reload(); ab_details(n.id); return;
    }
    const b = e.target.closest('[data-abd]'); if (!b) return;
    if (b.dataset.abd === 'open') ab_openFile(n);
    else if (b.dataset.abd === 'ver') ab_newVersion(n);
    else if (b.dataset.abd === 'tags' && typeof dt_abEdit === 'function') dt_abEdit(n, () => ab_details(n.id));  // 2.122.0 B (#2099)
    else if (b.dataset.abd === 'share') { modalClose(md); ab_share(n.id); }
  });
}

// ---- the Share dialog (built like the folder's Share dialog: people, groups, agents; a role and an optional end date each)
async function ab_share(id) {
  let n, t; try { [n, t] = await Promise.all([api('GET', `/api/files/nodes/${id}`), api('GET', `/api/files/nodes/${id}/share-targets`)]); } catch { return; }
  $('.abshdlg')?.remove();
  const roleSel = (attr, cur) => `<select ${attr} aria-label="${esc(tr('Role'))}"><option value="view" ${cur === 'view' ? 'selected' : ''}>${tr('Can view')}</option><option value="edit" ${cur === 'edit' ? 'selected' : ''}>${tr('Can edit')}</option></select>`;
  const md = modal(`<div class="lhdr"><h3>${esc(tr('Share “{0}”', n.name))}</h3><span class="spacer"></span><button class="iconbtn" data-m="close" aria-label="${tr('Close')}" title="${tr('Close')}">${ic('x')}</button></div>
    <div class="shint lhint keep">${n.kind === 'folder' ? tr('The share applies to everything in this folder, also what is added later.') : tr('The share applies to this file and all its versions.')} ${tr('Agents see exactly what is shared with them, nothing else; every access shows up in the history.')}</div>
    <div class="shws">${ab_spaceIcon(n.org_id ? 'org:' + n.org_id : 'private')} ${esc(n.org_id ? wsName('org:' + n.org_id) : tr('Private|workspace'))} <small class="muted">${esc(tr('Only people, groups and agents of this workspace'))}</small></div>
    <div id="ab-shl" class="members"></div>
    <div class="abshadd">
      <select id="ab-sht" aria-label="${esc(tr('Share with …'))}"><option value="">${tr('Share with …')}</option>
        ${t.people.length ? `<optgroup label="${esc(tr('People'))}">${t.people.map(p => `<option value="user_id:${p.id}">${esc(p.name)}</option>`).join('')}</optgroup>` : ''}
        ${t.groups.length ? `<optgroup label="${esc(tr('Groups'))}">${t.groups.map(p => `<option value="group_id:${p.id}">${esc(p.name)}</option>`).join('')}</optgroup>` : ''}
        ${t.agents.length ? `<optgroup label="${esc(tr('Agents'))}">${t.agents.map(p => `<option value="agent_id:${p.id}">${esc(p.name)}</option>`).join('')}</optgroup>` : ''}</select>
      ${roleSel('id="ab-shr"', 'view')}
      <span class="abexp"><span class="muted">${tr('until')}</span>${dateIn('ab-she', '', {label: tr('Valid until (optional)'), min: today()})}</span>
      <button type="button" class="btn sm" data-abs="add">${ic('plus', 's')} ${tr('Add')}</button></div>
    ${n.org_id ? `<h4>${tr('Whole organisation')}</h4><div class="row"><select id="ab-sho" aria-label="${esc(tr('Whole organisation'))}"><option value="">${tr('Only the people it is shared with')}</option><option value="view" ${n.org_access === 'view' ? 'selected' : ''}>${tr('Every member can view')}</option><option value="edit" ${n.org_access === 'edit' ? 'selected' : ''}>${tr('Every member can edit')}</option></select></div>${n.org_access_from ? `<div class="muted">${esc(tr('Already open through the folder “{0}”', n.org_access_from.name))}</div>` : ''}<div class="muted abhint">${tr('Never for agents. The organisation’s admins always see everything.')}</div>` : ''}
    <div class="foot"><span class="spacer"></span><button class="btn pri" data-m="close">${tr('Done')}</button></div>`);
  md.classList.add('shmodal', 'abshdlg');
  let shares = n.shares || [];
  const inh = n.inherited || [];
  const draw = () => {
    const box = $('#ab-shl', md); if (!box) return;
    box.innerHTML = shares.map(s => `<div class="mrow" data-sid="${s.id}">${s.agent_id ? av(s.agent_id, s.name) : s.group_id ? ic('users') : av(s.user_id, s.name)}<span class="n">${esc(s.name)}${s.agent_id ? agentBadge() : ''}${s.expires_at ? ` <small class="muted">${esc(tr('until {0}', ab_when(s.expires_at)))}</small>` : ''}</span>${roleSel(`data-absr="${s.id}"`, s.role)}<button class="iconbtn" data-absx="${s.id}" title="${esc(tr('Stop sharing'))}" aria-label="${esc(tr('Stop sharing with {0}', s.name))}">${ic('x', 's')}</button></div>`).join('')
      + inh.map(s => `<div class="mrow abinh"><span class="n">${esc(s.name)} <small class="muted">${esc(tr('from the folder “{0}”', s.from))}</small></span><span class="muted">${esc(ab_role(s.role))}</span></div>`).join('')
      || `<div class="muted mhint">${tr('Not shared yet')}</div>`;
  };
  draw();
  const add = async (target, role, exp) => {
    const [k, v] = target.split(':');
    const r = await api('POST', `/api/files/nodes/${id}/shares`, {[k]: +v, role, expires_at: exp || null, tz: evTz()});
    shares = r.shares; draw(); ab_reload(); return r.id;
  };
  md.addEventListener('click', async e => {
    if (e.target.closest('[data-m="close"]')) { modalClose(md); return; }
    if (e.target.closest('[data-abs="add"]')) {
      const tg = $('#ab-sht', md).value; if (!tg) { $('#ab-sht', md).focus(); return; }
      const role = $('#ab-shr', md).value, exp = $('#ab-she', md).value;
      let sid; try { sid = await add(tg, role, exp); } catch { return; }
      $('#ab-sht', md).value = '';
      const nm = $(`#ab-sht option[value="${tg}"]`, md)?.textContent || '';
      offerUndo(tr('Shared with {0}', nm), histAdd({label: tr('Share “{0}”', n.name), undo: () => ab_req('DELETE', `/api/files/shares/${sid}`), redo: async () => { try { sid = await add(tg, role, exp); } catch { /* shown */ } return {}; }}));
      return;
    }
    const x = e.target.closest('[data-absx]');
    if (x) {
      const s = shares.find(q => q.id === +x.dataset.absx); if (!s) return;
      let r; try { r = await api('DELETE', `/api/files/shares/${s.id}`); } catch { return; }
      shares = r.shares; draw(); ab_reload();
      const tg = s.user_id ? 'user_id:' + s.user_id : s.group_id ? 'group_id:' + s.group_id : 'agent_id:' + s.agent_id;
      offerUndo(tr('No longer shared with {0}', s.name), histAdd({label: tr('Stop sharing “{0}”', n.name), undo: async () => { try { await add(tg, s.role, s.expires_at || ''); } catch { /* shown */ } return {}; }, redo: () => ab_req('DELETE', `/api/files/shares/${(shares.find(q => (q.user_id || q.group_id || q.agent_id) === (s.user_id || s.group_id || s.agent_id)) || s).id}`)}));
    }
  });
  md.addEventListener('change', async e => {
    const r = e.target.closest('[data-absr]');
    if (r) { const s = shares.find(q => q.id === +r.dataset.absr), was = s?.role; try { shares = (await api('PATCH', `/api/files/shares/${r.dataset.absr}`, {role: r.value})).shares; } catch { return; } draw(); offerUndo(tr('Role changed'), histAdd({label: tr('Role in “{0}”', n.name), undo: () => ab_req('PATCH', `/api/files/shares/${r.dataset.absr}`, {role: was}), redo: () => ab_req('PATCH', `/api/files/shares/${r.dataset.absr}`, {role: r.value})})); return; }
    if (e.target.id === 'ab-sho') {
      const was = n.org_access || '', v = e.target.value;
      try { await api('PATCH', `/api/files/nodes/${id}`, {org_access: v}); } catch { return; }
      n.org_access = v; ab_reload();
      offerUndo(v ? tr('Open to the whole organisation') : tr('Only the people it is shared with'), histAdd({label: tr('Whole organisation: “{0}”', n.name), undo: () => ab_req('PATCH', `/api/files/nodes/${id}`, {org_access: was}), redo: () => ab_req('PATCH', `/api/files/nodes/${id}`, {org_access: v})}));
    }
  });
}

// ---- events
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-ab]'); if (!b || !b.closest('.abview, #pop')) return;
  const n = ab_item(b.dataset.id), a = b.dataset.ab;
  if (a === 'space') { AB.space = b.dataset.sp; LS.set('abSpace', AB.space); AB.key = ''; if (S.route.nid) go('ablage'); else ab_load(); return; }
  if (a === 'new-folder') { ab_newFolder(); return; }
  if (a === 'upload') { $('#ab-file')?.click(); return; }
  if (a === 'scan') { abm_scan(); return; }  // 2.112.1 A (#2058)
  if (a === 'open' && n) { if (n.kind === 'folder') go('ablage/' + n.id); else ab_openFile(n); return; }
  if (a === 'menu' && n) { ab_menu(b, n); return; }
  if (a === 'restore' && n) ab_restore(n);
});
document.addEventListener('change', e => { if (e.target.id === 'ab-file') { const fs = e.target.files; ab_upload(fs, S.route.nid || null); e.target.value = ''; } });
// dropping files from the computer into the open folder / onto a folder row; dragging a row onto a folder (or the path) moves it
document.addEventListener('dragstart', e => { const r = e.target.closest?.('.abrow[draggable="true"]'); if (!r) return; AB.drag = +r.dataset.abid; e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', r.querySelector('.abname')?.textContent || ''); });
document.addEventListener('dragend', () => { AB.drag = null; $$('.abdrop').forEach(x => x.classList.remove('abdrop')); });
document.addEventListener('dragover', e => {
  const v = e.target.closest?.('.abview'); if (!v) return;
  const files = [...(e.dataTransfer?.types || [])].includes('Files'), t = e.target.closest('[data-abdrop]');
  if (AB.drag && t && +t.dataset.abdrop !== AB.drag) { e.preventDefault(); $$('.abdrop').forEach(x => x !== t && x.classList.remove('abdrop')); t.classList.add('abdrop'); return; }
  if (files && v.classList.contains('abdropok')) { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; v.classList.add('abdrop'); }
});
document.addEventListener('dragleave', e => { if (e.target.classList?.contains('abview') && !e.target.contains(e.relatedTarget)) e.target.classList.remove('abdrop'); });
document.addEventListener('drop', e => {
  const v = e.target.closest?.('.abview'); if (!v) return;
  e.preventDefault(); $$('.abdrop').forEach(x => x.classList.remove('abdrop'));
  const t = e.target.closest('[data-abdrop]');
  if (AB.drag) { const n = ab_item(AB.drag); AB.drag = null; if (n && t) ab_move(n, t.dataset.abdrop === 'top' ? null : +t.dataset.abdrop); return; }
  const fs = e.dataTransfer?.files; if (!fs?.length || !v.classList.contains('abdropok')) return;
  ab_upload(fs, t && t.dataset.abdrop !== 'top' ? +t.dataset.abdrop : S.route.nid || null);
});

// ---- "Show in the file store" for a task / project file: a link at the top of the file's workspace (no copy; the original's
// rights stay). The button sits on the file tiles of tasks (attachments.js) and project pages (projects.js).
const ab_linkBtn = (kind, id, org, cls) => ab_on() ? `<button type="button" class="${cls} ablink" data-ablink="${kind}:${id}:${org || ''}" title="${esc(tr('Show in the file store'))}" aria-label="${esc(tr('Show in the file store'))}">${ic('folder', 's')}</button>` : '';
async function ab_linkFile(refKind, refId, org) {
  let n; try { n = await api('POST', '/api/files/links', {ref_kind: refKind, ref_id: refId, space: org ? 'org:' + org : 'private'}); } catch { return; }
  if (S.route.mod === 'ablage') ab_reload();
  offerUndo(tr('“{0}” is now in your files', n.name), histAdd({label: tr('Show “{0}” in the file store', n.name), undo: () => ab_req('DELETE', `/api/files/nodes/${n.id}`), redo: () => ab_req('POST', `/api/files/nodes/${n.id}/restore`)}));
}
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-ablink]'); if (!b) return;
  e.preventDefault(); e.stopPropagation();
  const [k, id, org] = b.dataset.ablink.split(':');
  ab_linkFile(k, +id, +org || null);
}, true);

// ---- 2.96.0 A (#1941): choose several rows (checkboxes, big targets on phones) and move them -- within the space ("Move to…")
// or into the other workspace (private <-> organisation, the shared dialog of spacemove.js). Each action = ONE undo step.
const ab_smvOk = n => !!n && n.kind !== 'link' && !n.agent_id && ab_canWrite(n.role);
const ab_smvSel = () => (AB.data?.items || []).filter(n => AB.sel.has(n.id));
const ab_smvTools = d => d?.items?.length && !(typeof ftxtActive === 'function' && ftxtActive()) ? `<button type="button" class="btn sm ${AB.selOn ? 'on' : ''}" data-absel="mode" aria-pressed="${!!AB.selOn}">${ic('check', 's')} ${tr('Select')}</button>` : '';
const ab_smvBox = n => AB.selOn ? `<label class="absel" title="${esc(tr('Select {0}', n.name))}"><input type="checkbox" data-absel="one" data-id="${n.id}" ${AB.sel.has(n.id) ? 'checked' : ''} aria-label="${esc(tr('Select {0}', n.name))}"></label>` : '';
function ab_smvBar() {
  if (!AB.selOn) return '';
  const ns = ab_smvSel(), all = (AB.data?.items || []).length, ok = ns.length > 0 && ns.every(ab_smvOk), from = ns[0]?.org_id || null;
  return `<div class="abselbar" role="toolbar" aria-label="${esc(tr('Selection'))}"><span class="absn" aria-live="polite">${esc(tr('{0} selected', ns.length))}</span>
    <button type="button" class="linkbtn" data-absel="all">${ns.length === all ? tr('Select none') : tr('Select all')}</button><span class="spacer"></span>
    <button type="button" class="btn sm" data-absel="dl" ${ns.length && ns.some(abm_dlOk) ? '' : 'disabled'}>${ic('download', 's')} <span class="abselt">${tr('Download')}</span></button>
    <button type="button" class="btn sm" data-absel="trash" ${ns.length && ns.every(abm_trashOk) ? '' : 'disabled'} aria-label="${esc(tr('Move to the trash'))}" title="${esc(tr('Move to the trash'))}">${ic('trash', 's')} <span class="abselt">${tr('Move to the trash')}</span></button>
    <button type="button" class="btn sm abselx" data-absel="move" ${ok ? '' : 'disabled'}>${ic('arrow', 's')} ${tr('Move to…')}</button>
    ${smv_can(from) ? `<button type="button" class="btn sm abselx" data-absel="space" ${ok ? '' : 'disabled'}>${ic('building', 's')} ${tr('Move to another workspace…')}</button>` : ''}
    <button type="button" class="iconbtn abselm" data-absel="more" ${ok ? '' : 'disabled'} aria-label="${esc(tr('More'))}" title="${esc(tr('More'))}">${ic('dots')}</button>
    <button type="button" class="iconbtn" data-absel="off" aria-label="${esc(tr('Cancel'))}" title="${esc(tr('Cancel'))}">${ic('x')}</button></div>`;
}
const ab_smvEnd = () => { AB.sel.clear(); AB.selOn = false; };
// several rows into one folder of the same space (the server refuses another tree / a folder into itself)
async function ab_smvMoveDlg(ns) {
  let fs; try { fs = (await api('GET', '/api/files/folders')).folders; } catch { return; }
  const n0 = ns[0], ids = new Set(ns.map(n => n.id));
  const ok = fs.filter(f => (f.org_id || null) === (n0.org_id || null) && f.owner_id === n0.owner_id && !ids.has(f.id));
  const go2 = async target => {
    const done = [];
    for (const n of ns) {
      if ((n.parent_id ?? null) === (target || null)) continue;
      try { await api('PATCH', `/api/files/nodes/${n.id}`, {parent_id: target || null}); done.push({id: n.id, was: n.parent_id ?? null}); } catch { break; }
    }
    ab_smvEnd(); ab_reload();
    if (!done.length) return;
    const all = async to => { for (const x of done) await ab_req('PATCH', `/api/files/nodes/${x.id}`, {parent_id: to(x)}); return {}; };
    offerUndo(trn('{0} item moved', '{0} items moved', done.length), histAdd({label: tr('Move to…'), undo: () => all(x => x.was), redo: () => all(() => target || null)}));
  };
  const items = [{label: tr('Top level'), icon: 'up', fn: () => go2(null)}, ...ok.map(f => ({label: f.path, icon: 'folder', fn: () => go2(f.id)}))];
  menu($('[data-absel="move"]') || document.body, [{head: tr('Move to …')}, ...items.slice(0, 60)], null, null, tr('Move to …'));
}
async function ab_smvPlaces(to) {
  const fs = (await api('GET', '/api/files/folders')).folders || [];
  return fs.filter(f => (f.org_id || null) === (to || null) && (to || f.owner_id === S.me?.id)).map(f => ({id: f.id, label: f.path}));
}
async function ab_smvDry(b) {  // the dry run: an error of the server is the dialog's block (no toast)
  try { return await rawFetch('POST', '/api/files/move-space', {...b, dry: 1}); } catch (x) { return {block: x.message || tr('The check failed. Please try again.')}; }
}
async function ab_smvSpace(ns) {
  ns = (ns || []).filter(ab_smvOk); if (!ns.length) return;
  const from = ns[0].org_id || null;
  if (ns.some(n => (n.org_id || null) !== from)) { toast(tr('Choose items of one workspace')); return; }
  const ids = ns.map(n => n.id), req = (to, p) => ({ids, to: smv_ws(to), parent: p ? +p : null});
  let last = null;
  const r = await smv_open({what: ns.length === 1 ? `“${ns[0].name}”` : trn('{0} item', '{0} items', ns.length), from, places: ab_smvPlaces,
    check: (to, p) => ab_smvDry(req(to, p)), run: (to, p) => { last = req(to, p); return api('POST', '/api/files/move-space', last); }});
  if (!r?.moved || !last) return;
  ab_smvEnd();
  if (S.route.nid && ids.includes(S.route.nid)) go(r.moved[0].parent_was ? 'ablage/' + r.moved[0].parent_was : 'ablage'); else ab_reload();
  const back = {items: r.moved.map(m => ({id: m.id, parent: m.parent_was, name: m.name_was})), to: smv_ws(r.org_was)}, again = last;
  offerUndo(tr('Moved to {0}', wsName(r.to)), histAdd({label: tr('Move to another workspace'),
    undo: () => ab_req('POST', '/api/files/move-space', back), redo: () => ab_req('POST', '/api/files/move-space', again)}));
}
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-absel]'); if (!b || !b.closest('.abview') || b.dataset.absel === 'one') return;
  const a = b.dataset.absel, items = AB.data?.items || [];
  if (a === 'mode') { AB.selOn = !AB.selOn; AB.sel.clear(); ab_draw(); }
  else if (a === 'off') { ab_smvEnd(); ab_draw(); }
  else if (a === 'all') { const all = ab_smvSel().length === items.length; AB.sel = new Set(all ? [] : items.map(n => n.id)); ab_draw(); }
  else if (a === 'move') ab_smvMoveDlg(ab_smvSel());
  else if (a === 'space') ab_smvSpace(ab_smvSel());
  else if (a === 'dl') abm_download(ab_smvSel());  // 2.112.1 A (#2058)
  else if (a === 'trash') abm_trash(ab_smvSel());
  else if (a === 'more') { const ns = ab_smvSel(); menu(b, [{label: tr('Move to…'), icon: 'arrow', fn: () => ab_smvMoveDlg(ns)},
    smv_can(ns[0]?.org_id || null) ? {label: tr('Move to another workspace…'), icon: 'building', fn: () => ab_smvSpace(ns)} : null], null, null, tr('Selection')); }
});
document.addEventListener('change', e => {
  const b = e.target.closest?.('[data-absel="one"]'); if (!b) return;
  const id = +b.dataset.id; if (b.checked) AB.sel.add(id); else AB.sel.delete(id);
  ab_draw();
});

// ---- 2.112.1 A (#2058): the selection into the trash (ONE undo step for all), download (one file as it is, else a ZIP),
// a folder as a ZIP, the phone scan (abscan.js) into the open folder
const abm_trashOk = n => ab_canWrite(n.role) && (n.parent_id || n.role === 'owner');
const abm_dlOk = n => n.kind === 'folder' || (n.kind === 'file' && !upLocked(n));
async function abm_trash(ns) {
  ns = ns.filter(abm_trashOk); if (!ns.length) return;
  let r; try { r = await api('POST', '/api/files/trash', {ids: ns.map(n => n.id)}); } catch { return; }
  const ids = r.ids || ns.map(n => n.id);
  ab_smvEnd(); ab_reload();
  offerUndo(trn('{0} item moved to the trash', '{0} items moved to the trash', ns.length), histAdd({label: tr('Move to the trash'),
    undo: () => ab_req('POST', '/api/files/restore', {ids}), redo: () => ab_req('POST', '/api/files/trash', {ids})}));
}
async function abm_download(ns) {
  ns = ns.filter(abm_dlOk); if (!ns.length) return;
  const a = document.createElement('a');
  if (ns.length === 1 && ns[0].kind === 'file') { a.href = ab_url(ns[0], true); a.download = ns[0].name; }
  else {
    const q = ns.map(n => n.id).join(',');
    try { await api('GET', `/api/files/zip?ids=${q}&check=1`); } catch { return; }  // the limits first: the refusal as a message, not as a file
    a.href = `/api/files/zip?ids=${q}`;
    toast(tr('The ZIP is being prepared…'));
  }
  document.body.appendChild(a); a.click(); a.remove();
}
function abm_scan() {
  const parent = S.route.nid || null, space = ab_curSpace(), old = new Set((AB.data?.items || []).map(x => x.id));
  abm_scanOpen({parent, space, done: items => {
    ab_reload();
    const created = items.filter(x => !old.has(x.id));
    if (!created.length) return;
    const ids = created.map(x => x.id);
    offerUndo(tr('“{0}” saved', created[0].name), histAdd({label: tr('Scan'), undo: () => ab_req('POST', '/api/files/trash', {ids}), redo: () => ab_req('POST', '/api/files/restore', {ids})}));
  }});
}
