/* Kalmido web client: the file store "Ablage" (2.48.0, #1207). Folders and files per person and per organisation, shared
   with people, groups and agents (view / edit, inherited by everything below, optional expiry), versions, trash with undo,
   the history of every agent access. Route #ablage (the top of the shown space) and #ablage/<id> (a folder, or a file:
   its folder with the file's details). The rules live on the server (kalmido/files); this module only shows them.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

const AB = {space: LS.get('abSpace', ''), key: '', dkey: '', data: null, err: '', loading: false, seq: 0, sel: new Map(), selOn: false, drag: null};  // 2.768.0 (#4888): sel = the area's ONE selection (ab_selInfo)
const ab_spaces = () => { const w = wsCur(); return [...(w === 'all' || w === 'private' || !wsOn() ? ['private'] : []), ...(wsOn() ? (S.me?.workspaces || []).filter(o => w === 'all' || w === 'org:' + o.id).map(o => 'org:' + o.id) : []), 'shared', 'trash']; };
// 2.540.0 (#4575): "All workspaces" with more than one space of one's own (Private + an organisation): the top of the file
// store is the overview of the spaces (areas.js spo_html, + Shared with me and the trash), the open one is in the address
// (#ablage/s/<space>, ab_home). AB.space (LS 'abSpace') is only kept and used while one workspace is shown; under "All"
// AB.allSp = the space opened last (in memory: a collection ablage/aus-<key> of it, the panel's highlight)
const ab_all = () => wsCur() === 'all' && ab_spaces().filter(s => s === 'private' || s.startsWith('org:')).length > 1;
const ab_curSpace = () => {
  const sp = ab_spaces(), r = S.route;
  if (!ab_all()) return sp.includes(AB.space) ? AB.space : sp[0];
  if (r.mod === 'ablage' && sp.includes(r.wsp)) return (AB.allSp = r.wsp);
  return sp.includes(AB.allSp) ? AB.allSp : sp[0];
};
const ab_ovr = () => ab_all() && S.route.mod === 'ablage' && !S.route.nid && !S.route.aus && !ab_spaces().includes(S.route.wsp);
const ab_home = s => ab_all() && s ? 'ablage/s/' + s : 'ablage';
const ab_pick = s => { if (ab_all()) AB.allSp = s; else { AB.space = s; LS.set('abSpace', s); } };
// the space a node lies in (the top of it under "All": its space's page)
const ab_nodeSp = n => n?.space || (n?.org_id ? 'org:' + n.org_id : n?.role === 'owner' ? 'private' : 'shared');
const ab_url = (n, dl, v) => `/api/files/nodes/${n.id}/content?${[dl ? 'dl=1' : '', v ? 'v=' + v : ''].filter(Boolean).join('&')}`;
const ab_isImg = n => /^image\/(png|jpe?g|gif|webp|avif)$/.test(n.mime || '');
const ab_isPdf = n => n.mime === 'application/pdf';
const ab_canWrite = r => r === 'owner' || r === 'edit';
const ab_role = r => r === 'owner' ? tr('Owner') : r === 'edit' ? tr('Can edit') : r === 'view' ? tr('Can view') : '';
const ab_when = iso => iso ? fmtDay('short', new Date(iso)) : '';
// 2.199.0 A (#2742): FS_REF_ICON[ref_kind] = the icon of a filed office document / sheet (set by its module)
const FS_REF_ICON = {address_book: 'book', contact: 'user', contract_file: 'pdf', office_agreement: 'shield'};  // 2.351.0 B (#2749): + address books, contacts, contracts
// 2.351.0 B (#2749): a filed object the file store shows itself (its content): 'pdf' | 'text' (a person without the office's role reads it here)
const FS_REF_VIEW = {contract_file: 'pdf', office_agreement: 'text'};
const ab_icon = n => n.kind === 'folder' ? ic(n.agent_id ? 'bot' : 'folder') : n.kind === 'link' ? ic('link') : n.kind === 'ref' ? ic(FS_REF_ICON[n.ref_kind] || 'file') : ab_isPdf(n) ? ic('pdf') : ab_isImg(n) ? ic('picture') : ic('file');
// 2.199.0 A (#2742): the hint after a folder went into the trash: what may not be deleted stayed, one level up (kept of the server)

// ---- loading
const ab_key = r => r.nid ? 'n:' + r.nid : r.aus ? 'c:' + r.aus + ':' + ab_curSpace() : 's:' + ab_curSpace();  // 2.429.0 (#3580): + a collection
async function ab_load() {
  if (ab_ovr()) return;  // 2.540.0 (#4575): the overview loads nothing
  const r = S.route, key = ab_key(r), seq = ++AB.seq;
  AB.key = key; AB.loading = true;
  if (r.aus) {  // 2.429.0 (#3580): a collection "From <area>" (read-only, grouped by its object)
    try { const j = await api('GET', `/api/files/collections/${encodeURIComponent(r.aus)}?space=${encodeURIComponent(ab_curSpace())}`); if (seq !== AB.seq) return; AB.data = {...j, items: [], coll: true}; AB.dkey = key; AB.err = ''; }
    catch (x) { if (seq !== AB.seq) return; AB.data = null; AB.dkey = ''; AB.err = x.message || tr('unknown'); }
    AB.loading = false; ab_draw(); return;
  }
  const dq = typeof abd_cardsOn === 'function' && abd_cardsOn(key) ? '&docs=1' : '';  // 2.353.0 D (#2759): the cards need the documents' fields
  try {
    // 2.780.0 (#5391): a node address may be a file (#ablage/<file id>): its folder query says 409 "Not a folder" -- rawFetch says nothing,
    // the way below opens the file; any other failure of a folder load is toasted in the catch as api() did
    const j = await (r.nid ? rawFetch('GET', `/api/files?parent=${r.nid}` + dq) : api('GET', `/api/files?space=${encodeURIComponent(ab_curSpace())}` + dq));
    if (typeof fsl_prep !== 'function' && typeof loadModule === 'function') await loadModule('fslock').catch(() => {});  // 2.353.0 A (#2758)
    if (typeof fsl_prep === 'function') await fsl_prep(j);  // 2.353.0 A (#2758): names of a locked folder decrypted here
    if (seq !== AB.seq) return;
    AB.data = j; AB.dkey = key; AB.err = ''; AB.dq = dq;  // 2.353.0 D (#2759): dq = loaded with the documents' fields
    if (AB.pt[key] && !AB.pt[key].busy) Object.assign(AB.pt[key], {items: (j.items || []).filter(n => n.kind === 'folder'), coll: j.collections || [], stale: false});  // 2.152.3 B (#2621): the panel's copy follows
  } catch (x) {
    if (seq !== AB.seq) return;
    if (r.nid) {  // a file: open its folder and the file's details
      try { const n = await api('GET', `/api/files/nodes/${r.nid}`);
        // 2.752.0 (#4887): #ablage/<id> of a file = its document view (core.js AB_FILEIDS: the route of the module docs); a locked /
        // encrypted file and the trash keep the way before (its folder with the file's details)
        if (n.kind === 'file' && !n.in_trash && !n.locked && !n._enc && !upLocked(n) && feat('docs') && !S.me?.kid && S.route.nid === n.id) { AB_FILEIDS.add(n.id); AB.loading = false; route(); return; }
        if (n.kind !== 'folder') { AB.loading = false; go(n.parent_id ? 'ablage/' + n.parent_id : ab_home(ab_nodeSp(n))); setTimeout(() => ab_details(n.id), 50); return; } } catch { /* below */ }
    }
    if (r.nid && x.message !== 'auth' && !(x instanceof Offline) && !x.shown) toast(x.message || tr('unknown'));  // 2.780.0 (#5391): what api() would have said
    AB.data = null; AB.dkey = ''; AB.err = x.message || tr('unknown');
  }
  AB.loading = false;
  ab_draw();
  if (typeof sbb_sync === 'function') sbb_sync('ablage');  // 2.152.3 B (#2621): the path in the panel
  if (typeof fsl_auto === 'function') fsl_auto(AB.data);  // 2.353.0 A (#2758): an owner hands over waiting keys
}
function ab_draw() { if (S.route.mod !== 'ablage') return; const el = $('#view'); if (el) keepFocus(el, () => setHtml(el, mg_wrap('ablage', viewAblage()))); }
const ab_reload = () => { AB.key = ''; ab_ptStale(); if (S.route.mod === 'ablage') { ab_load(); if (typeof dc_inFold === 'function' && dc_inFold()) dc_load(); } };  // 2.752.0 (#4887): + a folder's documents  // 2.152.3 B (#2621): + the panel's folders
// 2.979.0 (#5667): after an undo / redo the server took back by its group (the step's own undo with ab_reload / ab_verAfter no
// longer runs; undo.js histRedraw lists a shown file store / documents list itself): a file store not shown and the panel's
// folders are old, an open details dialog reads its node again (the document view: docs.js, its reloader 'docs')
histReloader('ablage', () => {
  if (!['ablage', 'docs'].includes(S.route.mod) && (AB.dkey || Object.keys(AB.pt || {}).length)) { AB.key = ''; ab_ptStale(); }
  const dl = $('.abdlg')?.dataset.abid; if (dl) return ab_details(+dl);
});

// ---- the view
function viewAblage() {
  if (!ab_on()) return `<div class="empty">${setLinkHtml(tr('The file store is off (Settings > Modules)'))}</div>`;
  ab_selKeep();  // 2.768.0 (#4888)
  if (typeof dt_abOn !== 'function' && typeof ld_later === 'function') ld_later('tagsel');  // 2.122.0 B (#2099 #2295): tags, Shift ranges
  if (typeof abd_cardsHtml !== 'function' && feat('docs') && typeof ld_later === 'function') ld_later('docs');  // 2.353.0 D (#2759): cards, recognition (abdocs.js)
  const r = S.route;
  if (r.zle) { AB.selHere = false; return `<div class="abview abovr"><div class="abmain">${/*html-ok*/ spo_recentPage('ablage', ab_spaces().map(s => [s, ab_spaceName(s), ab_spaceIcon(s)]))}</div></div>`; }  // 2.880.0 (#5561): #ablage/recent
  if (ab_ovr()) {  // 2.540.0 (#4575): "All workspaces": the spaces first (also with the panel folded on a tablet); the search spans all of them
    AB.selHere = false;
    const search = typeof ftxtBox === 'function' ? ftxtBox() : '', found = search && ftxtActive();
    return `<div class="abview abovr ${typeof sbb_on === 'function' && sbb_on() ? 'abdesk' : ''}"><div class="abmain">${search}${found ? `<h3 class="abtitle">${tr('Search results')}</h3>${ftxtResults()}` : spo_recentHtml('ablage', 'ablage', ab_spaces().map(s => [s, ab_spaceName(s), ab_spaceIcon(s)]))}</div></div>`;  // 2.769.0 (#5352): "Recently edited"
  }
  const key = ab_key(r);
  if (AB.key !== key && !AB.loading) setTimeout(ab_load, 0);
  const d = AB.dkey === key ? AB.data : null, sp = r.nid ? (d?.space || '') : ab_curSpace();
  // the tree: the spaces; below the open one the path down to the open folder and its subfolders (desktop; phones: the path on top)
  const tree = r.nid && d ? [...(d.crumbs || []).map((c, i) => ({id: c.id, name: c.name, lvl: i + 1, on: c.id === r.nid})),
    ...d.items.filter(n => n.kind === 'folder').map(n => ({id: n.id, name: n.name, lvl: (d.crumbs || []).length + 1, sub: true}))] : [];
  const treeHtml = tree.map(t => `<button type="button" class="abspace abtree ${t.on ? 'on' : ''}" style="--ablvl:${Math.min(t.lvl, 6)}" data-go="ablage/${t.id}" data-abdrop="${t.id}" ${t.on ? 'aria-current="page"' : ''}>${ic('folder', 's')}<span>${esc(t.name)}</span></button>`).join('');
  const spaces = `<nav class="abspaces" aria-label="${esc(tr('File store'))}">${ab_spaces().map(s => `<button type="button" class="abspace ${!r.nid && s === sp ? 'on' : ''}" data-ab="space" data-sp="${esc(s)}" ${!r.nid && s === sp ? 'aria-current="page"' : ''}>${ab_spaceIcon(s)}<span>${esc(ab_spaceName(s))}</span></button>${r.nid && s === (sp || 'shared') ? treeHtml : ''}`).join('')}${ab_docBtns(true)}</nav>`;  // 2.353.0 D (#2759): + the saved filters; 2.752.0 (#4887): All documents, To review
  const desk = typeof sbb_on === 'function' && sbb_on();  // 2.152.3 B (#2621): a computer: spaces and folders are in the panel (ab_panelHtml), the path on top
  const trash = !r.nid && sp === 'trash', canAdd = r.nid ? ab_canWrite(d?.node?.role) : (sp === 'private' || (sp || '').startsWith('org:'));
  // 2.752.0 (#4887): a folder with recognition shows the documents' view (abdocs.js abd_foldHtml: their bar, the documents' cards,
  // its subfolders before them); every other folder its list as before
  const fold = !!(r.nid && d?.node && typeof abd_recogHere === 'function' && abd_recogHere(key) && typeof abd_foldHtml === 'function');
  const crumbs = r.nid && d ? `<nav class="abcrumbs" aria-label="${esc(tr('Path'))}">${ab_all() ? spo_upHtml('ablage') : '' /* 2.540.0 (#4575) */}<button type="button" class="linkbtn" data-ab="space" data-sp="${esc(sp === 'shared' || !sp ? 'shared' : sp)}" data-abdrop="top">${esc(ab_spaceName(sp || 'shared'))}</button>${(d.crumbs || []).map((c, i, a) => `<span class="abcsep" aria-hidden="true">/</span>${i === a.length - 1 ? `<span class="abccur" aria-current="page">${esc(c.name)}</span>` : `<button type="button" class="linkbtn" data-go="ablage/${c.id}" data-abdrop="${c.id}">${esc(c.name)}</button>`}`).join('')}</nav>` : ab_all() ? spo_crumbHtml('ablage', ab_spaceName(sp)) : `<h3 class="abtitle">${esc(ab_spaceName(sp))}</h3>`;  // 2.540.0 (#4575): under "All" the path back to the overview
  const tools = trash ? ab_trashTools(d) : fold ? ab_foldTools(d, canAdd) : `<div class="abtools">${canAdd ? `<button type="button" class="btn sm" data-ab="new-folder">${ic('folder', 's')} ${tr('New folder')}</button><button type="button" class="btn sm pri" data-ab="upload">${ic('upload', 's')} ${tr('Upload')}</button>${d?.node?.locked ? '' : `<button type="button" class="btn sm" data-ab="scan">${ic('camera', 's')} ${tr('Scan')}</button>`}<input type="file" id="ab-file" multiple hidden>` : ''}${typeof dt_abOn === 'function' && dt_abOn(sp || d?.space) ? '' : ab_selTools(d)}${typeof dt_abBtn === 'function' ? dt_abBtn(sp || d?.space) : ''}${!trash && d && typeof abd_toolsHtml === 'function' ? abd_toolsHtml(d, key) : ''}${r.nid && d?.node?.share_with ? `<button type="button" class="btn sm abshbtn" data-ab="share" data-id="${d.node.id}" title="${esc(tr('Share…'))}">${ic('users', 's')} ${tr('Share')}</button>` : '' /* 2.558.0 (#4693) */}${r.nid && d?.node ? `<button type="button" class="iconbtn" data-ab="menu" data-id="${d.node.id}" aria-label="${esc(tr('More actions for {0}', d.node.name))}" title="${esc(tr('More'))}">${ic('dots')}</button>` : ''}</div>`;
  // 2.428.0 A (#3581): where "Select" is offered the rows' boxes show on hover too (ab_selBox), not in the trash / tag filter / search
  AB.selHere = !!d?.items?.length && !fold &&  /* 2.589.0 (#4875): the trash too */ !(typeof dt_abOn === 'function' && dt_abOn(sp || d.space)) && !(typeof ftxtActive === 'function' && ftxtActive());
  let body;
  if (r.aus) return `<div class="abview ${desk ? 'abdesk' : ''}">${desk ? '' : spaces}<div class="abmain">${ab_collHtml(d, sp)}</div></div>`;  // 2.429.0 (#3580)
  if (AB.err && AB.key === key) body = `<div class="empty">${ic('folder')}<span>${esc(AB.err)}</span><button type="button" class="btn" data-ab="space" data-sp="private">${tr('Private|workspace')}</button></div>`;
  else if (!d) body = `<p class="muted lempty">${tr('Loading…')}</p>`;
  else if (!d.items.length && !d.collections?.length) body = `<div class="empty abempty">${ic(trash ? 'trash' : 'folder')}<span>${trash ? tr('The trash is empty') : sp === 'shared' && !r.nid ? tr('Nothing is shared with you yet') : canAdd ? tr('Drop files here or use “Upload”') : tr('This folder is empty')}</span>${/*html-ok*/ trash ? '' : hlp_linkHtml('files')/* 2.1086.0 (#5820): How it works */}${!r.nid && sp.startsWith('org:') && !ab_orgAdmin(sp) ? `<span class="muted abemptyhint">${tr('You see the organisation’s folders once an admin opens them to everyone or shares them with you.')}</span>` : ''}</div>`;
  else body = `<div class="ablist${AB.selOn ? ' abselon' : ''}" role="list">${d.items.map(n => ab_rowHtml(n, trash)).join('')}${(d.collections || []).map(ab_collRow).join('')}</div>`;  // 2.429.0 (#3580): + "From <area>" after the folders and files
  if (d?.items.length && !trash && typeof abd_cardsOn === 'function' && abd_cardsOn(key)) body = abd_cardsHtml(d, key);  // 2.353.0 D (#2759): the folder as cards
  if (fold) body = abd_foldHtml(d, key);  // 2.752.0 (#4887)
  if (d?.node?.locked && typeof fsl_bannerHtml === 'function') body = fsl_bannerHtml(d) + body;  // 2.353.0 A (#2758)
  if (!fold && d && typeof dt_abOn === 'function' && dt_abOn(sp || d.space)) body = dt_abBody(sp || d.space);  // 2.122.0 B (#2099): the tag filter of the space
  const search = !trash && !fold /* 2.752.0 (#4887): the documents' search of the folder */ && !d?.node?.locked && typeof ftxtBox === 'function' ? ftxtBox() : '';  // 2.61.0 (#1820): names + recognised text; 2.353.0 F (#2758, review N9): a locked folder searches its names here only (the banner)
  if (search && ftxtActive()) body = ftxtResults();
  const hint = !r.nid && sp === 'private' && d && !d.items.length ? `<p class="muted abhint">${tr('Share a folder with a person or an agent: they see exactly that folder, nothing else.')}</p>` : '';
  const tdays = trash && d?.trash_days ? `<p class="muted abhint abtrashdays">${esc(trashNote(tr('Files and folders in the trash are deleted permanently after {0} days.', d.trash_days), d.purge_on === false))}</p>` : '';  // 2.152.0 B (#2165)
  return `<div class="abview ${canAdd ? 'abdropok' : ''} ${desk ? 'abdesk' : ''}" data-abzone="${r.nid || ''}">${desk ? '' : spaces}<div class="abmain">${search}${search && ftxtActive() ? `<h3 class="abtitle">${tr('Search results')}</h3>` : crumbs + tools + (r.nid ? ab_shHead(d) : '') + ab_scanDoneHtml() + (!trash && d && typeof abd_recogLine === 'function' ? abd_recogLine(d) : '')}${body}${search && ftxtActive() ? '' : hint + tdays + ab_selBar(trash)}</div></div>`;
}
// 2.752.0 (#4887): the file store's tools above a folder with recognition: New folder, Share, its menu (Upload and Scan are
// "Add documents" / "Scan" in the documents' bar, the same way into the folder)
function ab_foldTools(d, canAdd) {
  const n = d.node;
  // 2.783.0 (#5356): one line at 320 px too - on a narrow screen New folder and Share as icons (ablage.css .abfoldtools)
  return `<div class="abtools abfoldtools">${canAdd ? `<button type="button" class="btn sm" data-ab="new-folder" title="${esc(tr('New folder'))}">${ic('folder', 's')}<span class="abtl"> ${tr('New folder')}</span></button>` : ''}${typeof abd_foldSeg === 'function' ? abd_foldSeg(d) : '' /* 2.769.0 (#5340): List | Cards */}${n.share_with ? `<button type="button" class="btn sm abshbtn" data-ab="share" data-id="${n.id}" title="${esc(tr('Share…'))}" aria-label="${esc(tr('Share'))}">${ic('users', 's')}<span class="abtl"> ${tr('Share')}</span></button>` : ''}<button type="button" class="iconbtn" data-ab="menu" data-id="${n.id}" aria-label="${esc(tr('More actions for {0}', n.name))}" title="${esc(tr('More'))}">${ic('dots')}</button></div>`;
}
// 2.752.0 (#4887): ONE area "Files": below the folders "All documents" and "To review" (the documents' saved filters, routes
// #ablage/docs and #ablage/review, docs.js). Phones / tablets without the panel: as buttons in the bar of the spaces on top;
// in the documents' own list its switch "All | To review" stays the only "To review" there (#4472)
const ab_docsOn = () => feat('docs') && !S.me?.kid;
function ab_docBtns(review) {
  if (!ab_docsOn()) return '';
  const r = S.route, rv = typeof DC !== 'undefined' && DC.review ? ` <span class="dc-count">${DC.review}</span>` : '';
  const b = (go, icon, name, on, after = '') => `<button type="button" class="abspace abfilt ${on ? 'on' : ''}" data-go="${go}" ${on ? 'aria-current="page"' : ''}>${ic(icon, 's')}<span>${esc(name)}</span>${after}</button>`;
  return b('ablage/docs', 'file', tr('All documents'), r.mod === 'docs' && !r.review && !r.dv && !r.id) + (review ? b('ablage/review', 'check', tr('To review'), r.mod === 'docs' && !!r.review, rv) : '');
}
function ab_phoneNav() {  // the documents' list (docs.js viewDocs) without the panel: the spaces and All documents, like a folder's bar
  if (typeof sbb_on === 'function' && sbb_on()) return '';
  return `<nav class="abspaces abdnav" aria-label="${esc(tr('Files'))}">${ab_spaces().map(s => `<button type="button" class="abspace" data-go="${esc(ab_home(s))}" data-absp="${esc(s)}">${ab_spaceIcon(s)}<span>${esc(ab_spaceName(s))}</span></button>`).join('')}${ab_docBtns(false)}</nav>`;
}
// 2.152.3 B (#2621): the panel of the file store (sidebar B on a computer): its parts (Files, Documents) as entries; below
// Files the top folders of the shown workspace (several workspaces: each one first), a folder's subfolders loaded and drawn
// only once opened, then "Shared with me" and the trash. A folder opens on the right with its path on top; a file row dragged
// onto a folder here moves it, files from the computer dropped on it are uploaded into it (data-abdrop as before).
// The folders per parent ('s:<space>' / 'n:<id>', the keys of ab_load) are loaded once, again after a change (ab_reload)
AB.pt = {};
async function ab_ptLoad(key) {
  const e = AB.pt[key] || (AB.pt[key] = {}); if (e.busy) return;
  e.busy = true;
  try { const j = await rawFetch('GET', key.startsWith('n:') ? `/api/files?parent=${+key.slice(2)}` : `/api/files?space=${encodeURIComponent(key.slice(2))}`); if (typeof fsl_prep === 'function') await fsl_prep(j); e.items = (j.items || []).filter(n => n.kind === 'folder'); e.coll = j.collections || []; e.err = ''; }  // 2.429.0 (#3580): + the collections
  catch (x) { e.items = e.items || []; e.err = x.message; }
  finally { e.busy = false; e.stale = false; }
  if (typeof sbb_sync === 'function') sbb_sync('ablage');
}
const ab_ptGet = key => { const e = AB.pt[key]; if (!e || e.stale) ab_ptLoad(key); return e?.items || null; };
function ab_ptStale() { for (const e of Object.values(AB.pt)) e.stale = true; if (typeof sbb_sync === 'function') sbb_sync('ablage'); }
function ab_panelHtml() {
  const a = mg_area('ablage'), r = S.route, on = r.mod === 'ablage', cur = on && !r.nid && !r.aus && !ab_ovr() ? ab_curSpace() : '';  // 2.540.0 (#4575): the overview marks none
  const real = ab_spaces().filter(s => s === 'private' || s.startsWith('org:'));
  const path = on && r.nid && AB.dkey === 'n:' + r.nid ? (AB.data?.crumbs || []).map(c => c.id) : [];  // the open folder's path stays open
  // 2.199.0 A (#2742): dragged to move / sort, a menu (sbb_treeReg('ab') below)
  const node = n => ({k: 'ab:' + n.id, name: n.name, go: 'ablage/' + n.id, on: on && r.nid === n.id, icon: n.agent_id ? 'bot' : 'folder', attrs: `data-abdrop="${n.id}"`,
    ns: 'ab', id: n.id, par: n.parent_id ? 'n:' + n.parent_id : 'top:' + (n.org_id || 'p'), drag: ab_canWrite(n.role), drop: ab_canWrite(n.role), menu: true,
    kids: AB.pt['n:' + n.id]?.items?.length !== 0, open: path.includes(n.id) && n.id !== r.nid, sub: () => (it => it && it.map(node))(ab_ptGet('n:' + n.id))});
  // 2.429.0 (#3580): a space's collections "From <area>" after its folders (read-only: no drag, no drop, no menu)
  // 2.1148.0 (#4895): "Receipts" (x.subs) with its parts Office / Entertainment / Household below it; open while one of them is shown
  const collNode = (s, x) => ({k: 'ab:c:' + s + ':' + x.key, name: x.name, go: 'ablage/aus-' + x.key, on: on && r.aus === x.key && ab_curSpace() === s, icon: AB_COLL_ICON[x.key] || 'folder', battrs: `data-absp="${esc(s)}"`,
    kids: !!x.subs?.length, open: !!x.subs?.some(y => on && r.aus === y.key && ab_curSpace() === s), sub: () => (x.subs || []).map(y => collNode(s, y))});
  const collNodes = s => (AB.pt['s:' + s]?.coll || []).map(x => collNode(s, x));
  const withColl = (s, it) => it && [...it.map(node), ...collNodes(s)];
  const spaceNode = s => ({k: 'ab:s:' + s, name: ab_spaceName(s), go: ab_home(s) /* 2.540.0 (#4575) */, on: cur === s, icon: s === 'private' ? 'home' : s === 'shared' ? 'users' : s === 'trash' ? 'trash' : 'folder', battrs: `data-absp="${esc(s)}"`,
    kids: real.includes(s) && (AB.pt['s:' + s]?.items?.length !== 0 || !!AB.pt['s:' + s]?.coll?.length), open: !!path.length && AB.data?.space === s, sub: () => withColl(s, ab_ptGet('s:' + s))});
  // 2.752.0 (#4887): ONE tree (the documents' own tree with the same folders again is gone); below it "All documents", "To
  // review" and the saved views (2.579.0 #4802, docviews.js, loaded without redrawing the view: it draws the panel itself,
  // sbb_sync), then "Shared with me" and the trash. The part docs of the area stays the switch of the documents (Settings >
  // Modules, the menu's hidden parts: hidden = no documents' rows here)
  const rv = typeof DC !== 'undefined' && DC.review ? `<span class="c">${DC.review}</span>` : '';
  const docRows = () => `<div class="abfilt" role="group" aria-label="${esc(tr('Documents'))}">${sbb_row('ablage/docs', 'file', tr('All documents'), r.mod === 'docs' && !r.review && !r.dv && !r.id, 'data-sbbpart="docs"')}${sbb_row('ablage/review', 'check', tr('To review'), r.mod === 'docs' && !!r.review, 'data-sbbpart="docs-review"', rv)}${typeof dcv_sideHtml === 'function' ? dcv_sideHtml() : (typeof loadModule === 'function' && ab_docsOn() ? (loadModule('docviews').catch(() => {}), '') : '')}</div>${typeof dfc_sideHtml === 'function' ? dfc_sideHtml() : ''}`;  // 2.772.0 (#4890): the filters with numbers (docfacets.js, loaded with docviews)
  const files = dOn => {
    const one = real.length === 1, top = one ? ab_ptGet('s:' + real[0]) : [];
    const tree = one ? (top ? sbb_treeHtml(withColl(real[0], top), 1) : `<p class="muted sbbtl" style="--sbbl:1">${esc(tr('Loading…'))}</p>`) : sbb_treeHtml(real.map(spaceNode), 1);
    const rest = sbb_treeHtml(ab_spaces().filter(s => !real.includes(s)).map(spaceNode));  // 2.932.0 (#5603): "Shared with me" and the trash on the left edge of Files / All documents (level 0), not stepped in like a sub folder; below the filter groups it starts with a group's gap, so it does not read as a value of the last group
    // 2.768.0 (#4888): "+" at the head of the tree = a new folder at the top of the space it shows (one space: that one; several: the one open)
    const add = `<button type="button" class="iconbtn abtadd" data-abtadd="${esc(one ? real[0] : (real.includes(ab_curSpace()) ? ab_curSpace() : real[0] || ''))}" title="${esc(tr('New folder'))}" aria-label="${esc(tr('New folder'))}">${ic('plus', 's')}</button>`;
    return `<div class="abthead">${sbb_row('ablage', 'folder', tr('Files'), one && cur === real[0], `data-sbbpart="ablage" ${one ? `data-absp="${esc(real[0])}"` : ''}`)}${real.length ? add : ''}</div>` + `<div class="sbbtree" role="group" aria-label="${esc(tr('Folders'))}">${tree}</div>`
      + (dOn ? docRows() : '') + `<div class="sbbtree abrest${dOn ? ' sgroup' : ''}" role="group" aria-label="${esc(tr('Shared with me'))}">${rest}</div>`;
  };
  const parts = nav_sort('ablage', mg_parts(a).filter(p => !nav_orgOff('ablage', p[0]) && (p[0] === r.mod || !nav_hid('ablage', p[0]))), p => p[0]);
  const dOn = ab_docsOn() && parts.some(p => p[0] === 'docs'), fOn = parts.some(p => p[0] === 'ablage');
  return `<div class="sgroup sbbp">${parts.map(p => p[0] === 'ablage' ? files(dOn) : p[0] === 'docs' ? (fOn || !dOn ? '' : docRows()) : sbb_row(p[0], p[1], tr(p[2]), p[0] === r.mod, `data-sbbpart="${p[0]}"`)).join('')}</div>`;  // 2.418.0 (#3560): the menu's order and hidden parts
}
// 2.199.0 A (#2742): the panel's folders are dragged into another folder (move) or before / after one (sort by hand), and
// have the menu of a row (right-click, long press, context key)
const ab_ptItem = id => { id = +id; for (const e of Object.values(AB.pt)) { const x = (e.items || []).find(n => n.id === id); if (x) return x; } return ab_item(id); };
async function ab_order(n, pos) {
  const b = {};
  if (pos.before) b.before = +pos.before; else if (pos.after) b.after = +pos.after;
  if (pos.into !== undefined) b.parent_id = String(pos.into).startsWith('n:') ? +String(pos.into).slice(2) : null;
  if ('parent_id' in b && b.parent_id === (n.parent_id ?? null)) delete b.parent_id;
  // the place before, for undo: in front of its next sibling (or after the one before it), as drawn
  const t = $(`#side .sbbt[data-sbbns="ab"][data-sbbid="${n.id}"]`), sib = t ? sbb_tsibs(t) : [], i = sib.indexOf(t);
  const back = {...(i >= 0 && i < sib.length - 1 ? {before: +sib[i + 1].dataset.sbbid} : i > 0 ? {after: +sib[i - 1].dataset.sbbid} : {}), ...('parent_id' in b ? {parent_id: n.parent_id ?? null} : {})};
  try { await api('POST', `/api/files/nodes/${n.id}/order`, b); } catch { return; }
  ab_reload();
  offerUndo(tr('“{0}” moved', n.name), histAdd({label: tr('Sort “{0}”', n.name), undo: () => ab_req('POST', `/api/files/nodes/${n.id}/order`, back), redo: () => ab_req('POST', `/api/files/nodes/${n.id}/order`, b)}));
}
sbb_treeReg('ab', {
  move: (id, into) => { const n = ab_ptItem(id); if (n) ab_move(n, +into); },
  order: (id, pos) => { const n = ab_ptItem(id); if (n) ab_order(n, pos); },
  menu: id => { const n = ab_ptItem(id); return n ? ab_menuItems(n, true) : []; }});
// a space in the panel: picked before the click's data-go opens #ablage (capture: ahead of the router's click)
// 2.752.0 (#4887): + the spaces of the documents' bar on phones (ab_phoneNav)
document.addEventListener('click', e => { const b = e.target.closest?.('#side [data-absp], .abdnav [data-absp]'); if (b) { ab_pick(b.dataset.absp); AB.key = ''; } }, true);  // 2.540.0 (#4575): ab_pick
// 2.429.0 (#3580): the file store shows only its own folders; what hangs on the other areas' objects (files of knowledge
// pages, project files, files left in an area's folders) is a read-only collection "From <area>" at the top of the space,
// grouped by its object (route ablage/aus-<key>, the space shown: AB.space). Open / download only; deleting stays on the
// page / in the project. Knowledge pages themselves: the global search.
const AB_COLL_ICON = {wiki: 'book', sheets: 'sheet', office: 'brief', lists: 'proj', contacts: 'user', receipts: 'receipt', rcoffice: 'brief', rcmeals: 'meal', rcbudget: 'wallet'};  // 2.1148.0 (#4895): + Receipts and its parts
// 2.1148.0 (#4895): "Receipts" below the tree = references: a receipt opens in its own area (it stays there, no copy). The
// server names the area's address (office/..., budget/<list>/<month>); under "All workspaces" the office's address carries the space
const AB_RCX = ['receipts', 'rcoffice', 'rcmeals', 'rcbudget'];
const ab_rcGo = (o, sp) => /^office\//.test(o || '') && ab_all() && sp ? 'office/s/' + sp + '/' + o.slice(7) : o;
const ab_collRow = x => `<div class="abrow abcoll" role="listitem" data-abcoll="${esc(x.key)}"><button type="button" class="abopen" data-go="ablage/aus-${esc(x.key)}">${ic(AB_COLL_ICON[x.key] || 'folder')}<span class="abtxt"><span class="abname">${esc(x.name)}</span><span class="abmeta2 muted">${esc(tr('Read-only'))}</span></span></button><span class="abmeta muted">${esc(tr('Read-only'))}</span><span class="abbadges"><span class="abbadge" title="${esc(tr('Read-only'))}">${ic('lock', 's')}</span></span></div>`;
function ab_collHtml(d, sp) {
  const rcPart = d && d.key !== 'receipts' && AB_RCX.includes(d.key);  // 2.1148.0 (#4895): a part of Receipts: Space / Receipts / Office
  const crumbs = `<nav class="abcrumbs" aria-label="${esc(tr('Path'))}">${ab_all() ? spo_upHtml('ablage') : '' /* 2.540.0 (#4575) */}<button type="button" class="linkbtn" data-ab="space" data-sp="${esc(sp)}">${esc(ab_spaceName(sp))}</button><span class="abcsep" aria-hidden="true">/</span>${rcPart ? `<button type="button" class="linkbtn" data-go="ablage/aus-receipts">${esc(tr('Receipts'))}</button><span class="abcsep" aria-hidden="true">/</span>` : ''}<span class="abccur" aria-current="page">${esc(d?.name || '')}</span></nav>`;
  if (AB.err && !d) return crumbs + `<div class="empty">${ic('folder')}<span>${esc(AB.err)}</span><button type="button" class="btn" data-ab="space" data-sp="${esc(sp)}">${esc(ab_spaceName(sp))}</button></div>`;
  if (!d) return `<p class="muted lempty">${tr('Loading…')}</p>`;
  const note = `<p class="muted abhint abcollnote">${esc(d.key === 'wiki' ? tr('Files of knowledge pages, read-only. Delete them on the page itself.') : d.key === 'lists' ? tr('Files of projects, read-only. Delete them in the project itself.') : d.key === 'sheets' ? tr('Files of tables, read-only. Delete them in the table itself.') : tr('Files of this area, read-only.'))}</p>`;
  if (AB_RCX.includes(d.key)) return crumbs + ab_rcxHtml(d, sp);  // 2.1148.0 (#4895)
  if (!d.groups?.length) return crumbs + note + `<div class="empty abempty">${ic('folder')}<span>${tr('This folder is empty')}</span></div>`;
  const row = (f, gi) => `<div class="abrow" role="listitem"><button type="button" class="abopen" data-abc="open" data-g="${gi}" data-id="${f.id}">${ab_icon({kind: 'file', mime: f.mime})}<span class="abtxt"><span class="abname">${esc(f.name)}</span><span class="abmeta2 muted">${esc([fmtSize(f.size || 0), ab_when(f.created_at)].filter(Boolean).join(' · '))}</span></span></button><span class="abmeta muted">${esc([fmtSize(f.size || 0), ab_when(f.created_at)].filter(Boolean).join(' · '))}</span><a class="iconbtn" href="${esc(f.dl)}" download="${esc(f.name)}" aria-label="${esc(tr('Download') + ' ' + f.name)}" title="${esc(tr('Download'))}">${ic('download')}</a></div>`;
  const grp = (g, gi) => `<section class="abcollg"><h4 class="abcollh">${g.open ? `<button type="button" class="linkbtn" data-go="${esc(g.open)}">${esc(g.title)}</button>` : esc(g.title)}</h4><div class="ablist" role="list">${g.items.map(f => row(f, gi)).join('')}</div></section>`;
  return crumbs + note + d.groups.map(grp).join('') + (d.more ? `<p class="muted abhint">${tr('Only the first {0} files are shown.', 500)}</p>` : '');
}
// 2.1148.0 (#4895): the receipts of a part (or of all three, one section each): name, day, amount, what it is; a tap opens
// the receipt's area (the office's receipts list / entertainment receipts, the budget list in the receipt's month)
function ab_rcxHtml(d, sp) {
  const note = `<p class="muted abhint abcollnote">${esc(tr('Receipts stay in their area. Open one to view, change or book it there.'))}</p>`;
  if (!d.groups?.length) return note + `<div class="empty abempty">${ic('receipt')}<span>${tr('No receipts here yet')}</span></div>`;
  const meta = f => [ab_when(f.created_at), f.amount ? curMoney(f.amount, f.currency || (S.settings.time_currency ?? '€')) : '', f.sub].filter(Boolean).join(' · ');
  const row = f => `<div class="abrow abrcx" role="listitem"><button type="button" class="abopen" data-go="${esc(ab_rcGo(f.open, sp))}">${/*html-ok*/ f.kind === 'meal' ? ic('meal') : ab_icon({kind: 'file', mime: f.mime}) /* icons only */}<span class="abtxt"><span class="abname">${esc(f.name)}</span><span class="abmeta2 muted">${esc(meta(f))}</span></span></button><span class="abmeta muted">${esc(meta(f))}</span>${ic('right', 's abrcgo')}</div>`;
  const grp = g => `<section class="abcollg"><h4 class="abcollh">${g.open ? `<button type="button" class="linkbtn" data-go="${esc(ab_rcGo(g.open, sp))}">${esc(g.title)}</button>` : esc(g.title)}</h4><div class="ablist" role="list">${/*html-ok*/ g.items.map(row).join('') /* row(): escaped above */}</div></section>`;
  return note + d.groups.map(grp).join('') + (d.more ? `<p class="muted abhint">${tr('Only the first {0} files are shown.', 500)}</p>` : '');
}
function ab_collOpen(f) {  // like a search hit of a project file (filetext.js ftxtOpenLf): PDF viewer, picture in a new tab, else download
  if (f.mime === 'application/pdf' && typeof pdfView === 'function') { pdfView({url: f.url, name: f.name, size: f.size, dlUrl: f.dl}); return; }
  if (/^image\//.test(f.mime || '')) { ftxtImgView(f, f.url, f.dl); return; }  // 2.537.0 (#4574)
  const a = document.createElement('a'); a.href = f.dl; a.download = f.name; document.body.appendChild(a); a.click(); a.remove();
}
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-abc="open"]'); if (!b || !b.closest('.abview')) return;
  const f = AB.data?.groups?.[+b.dataset.g]?.items.find(x => x.id === +b.dataset.id); if (f) ab_collOpen(f);
});
// 2.558.0 (#4693): who a node is shared with, like the lists (render.js licShareTip): n.share_with (files/fsshnames.py, only
// for who may share it: owner / an area) = [{n: name, k: u|g|a|o}], the folders above included. "Anna, Ben · agent X"
const ab_shName = e => e.k === 'o' ? tr('Whole organisation') : e.n;
function ab_shText(sw) {
  const p = sw.filter(e => e.k !== 'a').map(ab_shName), a = sw.filter(e => e.k === 'a').map(e => e.n);
  return [p.join(', '), a.length ? trn('agent {1}', 'agents {1}', a.length, a.join(', ')) : ''].filter(Boolean).join(' · ');
}
const ab_shShort = sw => { const x = sw.map(ab_shName); return x.length > 2 ? x[0] + ' ' + tr('+{0}', x.length - 1) : x.join(', '); };  // from three on "Anna +2"
// the line of a folder's head / the scan's end: "Shared with …" / "Only you" (who may share), "Shared by <owner>" (a receiver)
const ab_shLineTxt = n => n.share_with ? (n.share_with.length ? tr('Shared with {0}', ab_shText(n.share_with)) : tr('Only you')) : n.owner && n.owner_id !== S.me?.id ? tr('Shared by {0}', n.owner) : '';
// the names in a row / on a card instead of the bare symbol; a click opens the Share dialog (fsshare.js)
function ab_shChip(n, own) {
  if (n.share_with?.length) { const t = tr('Shared with {0}', ab_shText(n.share_with)); return `<button type="button" class="abbadge abshw" data-ab="share" data-id="${n.id}" title="${esc(t)}" aria-label="${esc(t)}">${n.share_with.some(e => e.k === 'a') && !n.share_with.some(e => e.k !== 'a') ? ic('bot', 's') : ic('users', 's')}<span>${esc(ab_shShort(n.share_with))}</span></button>`; }
  if (n.share_with || !n.shared) return '';
  const by = n.owner && n.owner_id !== S.me?.id && n.owner_id !== own ? tr('Shared by {0}', n.owner) : '';  // a receiver: from whom (once per owner: not again inside their folder)
  return by ? `<span class="abbadge abshby" title="${esc(by)}">${ic('users', 's')}<span>${esc(by)}</span></span>` : `<span class="abbadge" title="${esc(tr('Shared'))}" aria-label="${esc(tr('Shared'))}">${ic('users', 's')}</span>`;
}
function ab_shHead(d) {  // the open folder: "Share" on top (who may share) and the line below it
  const n = d?.node; if (!n || S.route.aus) return '';
  const t = ab_shLineTxt(n); if (!t) return '';
  const sw = n.share_with || [], bot = sw.length && sw.every(e => e.k === 'a');  // the robot only for agents alone (as the row)
  return `<p class="muted abshline">${ic(bot ? 'bot' : 'users', 's')}<span>${esc(t)}</span></p>`;
}
function ab_rowHtml(n, trash) {
  const meta = [n.path || '', n.kind === 'folder' ? '' : fmtSize(n.size || 0), ab_when(trash ? n.deleted_at : n.updated_at), n.created_by_name && n.created_by !== S.me?.id ? n.created_by_name : ''].filter(Boolean).join(' · ');
  const badges = (trash ? (n.shared ? `<span class="abbadge" title="${esc(tr('Shared'))}" aria-label="${esc(tr('Shared'))}">${ic('users', 's')}</span>` : '') : ab_shChip(n, AB.data?.node?.owner_id))  // 2.558.0 (#4693): the names
    + (n.agent_id ? `<span class="abbadge" title="${esc(tr('Folder of an agent'))}">${ic('bot', 's')}</span>` : '')
    + (n.version > 1 ? `<span class="abver" title="${esc(tr('Version {0}', n.version))}">v${n.version}</span>` : '')
    + upMarkHtml(n.up)  // 2.61.0 (#1818): not checked by the virus scanner yet / locked
    + (typeof xl_badge === 'function' ? xl_badge(n) : '')  // 2.112.1 B (#2058): a live external link
    + (typeof abd_badge === 'function' ? abd_badge(n) : '')  // 2.353.0 D (#2759): a document (being recognised / to review)
    + (typeof dsc_folderBadge === 'function' ? dsc_folderBadge(n) : '');  // 2.1048.0 (#5821): a folder with a scan inbox
  const main = trash ? `<span class="abopen">${ab_icon(n)}<span class="abtxt"><span class="abname">${esc(n.name)}</span>${meta ? `<span class="abmeta2 muted">${esc(meta)}</span>` : ''}</span></span>`
    : `<button type="button" class="abopen" data-ab="open" data-id="${n.id}" ${n.kind === 'folder' ? `data-abdrop="${n.id}"` : ''}>${ab_icon(n)}<span class="abtxt"><span class="abname">${esc(n.name)}</span>${meta ? `<span class="abmeta2 muted">${esc(meta)}</span>` : ''}</span></button>`;  // abmeta2: the details below the name on phones
  const acts = trash ? `<button type="button" class="btn sm" data-ab="restore" data-id="${n.id}">${ic('undo', 's')} ${tr('Restore')}</button>${n.role === 'owner' ? `<button type="button" class="btn sm danger" data-ab="purge" data-id="${n.id}">${ic('trash', 's')} ${tr('Delete permanently')}</button>` : ''}`  // 2.589.0 (#4875): + for good (owners)
    : `<button data-rowmenu="abrow" type="button" class="iconbtn" data-ab="menu" data-id="${n.id}" aria-label="${esc(tr('More actions for {0}', n.name))}" title="${esc(tr('More'))}">${ic('dots')}</button>`;
  return `<div class="abrow" role="listitem" data-abid="${n.id}" ${!trash && ab_canWrite(n.role) ? (rowd_touch() ? 'data-abmv="1"' : 'draggable="true"') : '' /* 2.627.0 (#4961): a finger by drag.js */}>${ab_selBox(n)}${main}${typeof dt_abTags === 'function' ? dt_abTags(n) : ''}<span class="abmeta muted">${esc(meta)}</span><span class="abbadges">${badges}</span>${acts}</div>`;
}
const ab_item = id => (AB.data?.items || []).find(x => x.id === +id) || (AB.data?.node?.id === +id ? AB.data.node : null) || (typeof ftxtItem === 'function' ? ftxtItem(id) : null) || (typeof dt_abItem === 'function' ? dt_abItem(id) : null);  // 2.61.0 (#1820): + search hits; 2.122.0 B: + tag filter hits

// 2.652.0 (#5071): a PDF of the folder leafs in the full screen through the folder's PDFs and pictures in the order shown
// (a swipe on a touch screen, the arrow keys and two buttons, pdfview.js o.step); alone in its folder: no leafing
function ab_pvOpts(n) {
  const o = {url: ab_url(n), name: n.name, size: n.size, dlUrl: ab_url(n, true)};
  if (!ab_isPdf(n)) { o.img = ab_url(n); o.kind = 'img'; }
  const list = (AB.data?.items || []).filter(x => x.kind === 'file' && !x._enc && !upLocked(x) && (ab_isPdf(x) || ab_isImg(x))), i = list.findIndex(x => x.id === n.id);
  if (i < 0 || list.length < 2) return o;
  Object.assign(o, {pos: tr('{0} of {1}', i + 1, list.length), first: i <= 0, last: i >= list.length - 1, prevT: tr('Previous document'), nextT: tr('Next document'),
    step: async dir => (list[i + dir] ? ab_pvOpts(list[i + dir]) : null), peek: dir => ({img: list[i + dir] && ab_isImg(list[i + dir]) ? ab_url(list[i + dir]) : ''})});  // 2.727.0 (#5202): a picture glides in as itself
  // 2.755.0 (#5236): on a touch screen (where the swipe is) the direct neighbours are made ready ahead by pdfview.js (o.near:
  // their file opened, the first page drawn, a picture decoded): a swipe shows them as they will stand, no placeholder
  if (navigator.maxTouchPoints > 0 || isTouch()) o.near = dir => (list[i + dir] ? ab_pvOpts(list[i + dir]) : null);
  return o;
}
const ab_navFiles = () => (AB.data?.items || []).filter(x => x.kind === 'file' && !x._enc && !upLocked(x) && (ab_isPdf(x) || ab_isImg(x))).map(x => x.id);  // 2.583.0 + 2.652.0 (#5071): the folder's PDFs and pictures the view leafs through (as ab_pvOpts)
// ---- opening a file: images in the lightbox, PDFs in the PDF view, text in the text view, the rest downloads
function ab_openDoc(n) {  // 2.750.0 (#5228): dc_open / abd_navIds are in the documents' module (lazyload.js docs): loaded first when needed
  const open = () => dc_open(n.id, {list: abd_navIds()});
  if (typeof dc_open === 'function' && typeof abd_navIds === 'function') open(); else loadModule('docs').then(open, () => {});
}
function ab_openFile(n, o = {}) {  // 2.583.0 (#4832): o.raw = the viewer of its kind (the document view's full screen)
  if (n.kind === 'ref' && FS_REF_VIEW[n.ref_kind] === 'pdf' && typeof pdfView === 'function') { pdfView({url: ab_url(n), name: n.name, size: n.size, dlUrl: ab_url(n, true)}); return; }  // 2.351.0 B (#2749)
  if (n.kind === 'ref' && FS_REF_VIEW[n.ref_kind] === 'text') { textView({url: ab_url(n, true), name: n.name, size: n.size, md: false, ext: 'txt'}); return; }
  if (n.kind === 'ref') { if (n.open) go(n.open); else toast(tr('No access')); return; }  // 2.199.0 A (#2742): a filed document opens in its area
  if (upLocked(n)) { toast(tr('Locked: malware was found in this file ({0})', n.up.sig || '?')); return; }  // 2.61.0 (#1818)
  if (n._enc && typeof fsl_open === 'function') { fsl_open(n); return; }  // 2.353.0 A (#2758): decrypted in the browser
  // 2.750.0 (#5228): a recognised document (n.doc) opens the document view in the list as in the cards (abdocs.js), leafing
  // through the folder's documents - before, the list opened the plain PDF viewer while the documents' module was not loaded yet
  if (n.kind === 'file' && n.doc && !o.raw && !n.locked && feat('docs') && !S.me?.kid) { ab_openDoc(n); return; }
  // 2.583.0 (#4832): a file opens the document view (one sheet for files and documents); 2.652.0 (#5071): it leafs through the
  // folder's documents, PDFs and pictures in the order shown (the view's arrows, its full screen with the swipe)
  if (n.kind === 'file' && !o.raw && typeof abd_on === 'function' && abd_on() && typeof dc_open === 'function') { const l = ab_navFiles(); dc_open(n.id, l.length > 1 && l.includes(n.id) ? {list: l} : {}); return; }
  if (ab_isImg(n)) { const imgs = (AB.data?.items || []).filter(x => ab_isImg(x) && !upLocked(x)); attLightbox(n.id, imgs, (a, dl) => ab_url(a, dl)); return; }
  if (n.kind === 'file' && dv_is(n)) { dpvOpen({url: `/api/files/nodes/${encodeURIComponent(n.id)}/preview`, name: n.name, size: n.size, dlUrl: ab_url(n, true)}); return; }  // 2.92.0 C (#1926)
  if (ab_isPdf(n)) { if (typeof pdfView === 'function') pdfView(ab_pvOpts(n)); else window.open(ab_url(n), '_blank', 'noopener'); return; }  // 2.652.0 (#5071): ab_pvOpts
  if (isTextFile(n) && (n.size || 0) <= TV_MAX) { textView({url: ab_url(n, true), name: n.name, size: n.size, md: isMdFile(n), ext: attExt(n)}); return; }
  const a = document.createElement('a'); a.href = ab_url(n, true); a.download = attDlName(n.name, n.mime); document.body.appendChild(a); a.click(); a.remove();  // 2.750.0 (#4876)
}

// ---- actions (each one = ONE undo step)
// 2.364.0 D (#3020): is the person an admin of the organisation space sp ('org:<id>')? Members see its folders only when opened / shared
const ab_orgAdmin = sp => (S.me?.workspaces || []).some(o => 'org:' + o.id === sp && o.role === 'admin');
// 2.353.0 F (#2758, review N8): the locked folder a target lies in -- a folder outside the open view is asked for; without the
// module (fslock.js did not load) nothing goes the plain way (ab_noFsl: a toast)
async function ab_lockOf(id) {
  if (!id) return null;
  const d = AB.data, n = d?.node?.id === +id ? d.node : ab_ptItem?.(id) || ab_item(id);
  if (n) return n.locked ? n.lock_id : null;
  try { const t = await rawFetch('GET', `/api/files/nodes/${id}`); return t?.locked ? t.lock_id : null; } catch { return null; }
}
const ab_noFsl = () => toast(tr('This browser cannot encrypt'));
async function ab_newFolder(parent, space) {  // 2.199.0 A (#2742): parent = a folder of the tree's menu (default: the open one); 2.768.0 (#4888): space = at the top of that space (the tree's "+")
  const pid = space ? null : typeof parent === 'number' ? parent : S.route.nid;
  const sp = space || ab_curSpace();
  // 2.364.0 D (#3020): an admin's new folder at the top of an organisation asks "Visible to all members?" (default off = as before)
  const ask = !pid && sp.startsWith('org:') && ab_orgAdmin(sp);
  let all = false;
  const name = await askPrompt(tr('New folder'), '', {ok: tr('Create'), input: {placeholder: tr('Name'), max: 150},
    ...(ask ? {html: `<label class="chkl"><input type="checkbox" id="ab-nfall"> ${tr('Visible to all members?')}</label>`, after: md => $('#ab-nfall', md).addEventListener('change', e => { all = e.target.checked; })} : {})});
  if (!name || !name.trim()) return;
  const lid = await ab_lockOf(pid);  // 2.353.0 A (#2758); F (review N8): never the plain way into a locked folder
  if (lid) return typeof fsl_newFolder === 'function' ? fsl_newFolder(pid, name, lid) : ab_noFsl();
  const b = pid ? {parent_id: pid, name} : {space: sp, name};
  let n; try { n = await api('POST', '/api/files/folders', b); } catch { return; }
  if (ask && all) { try { n = await api('PATCH', `/api/files/nodes/${n.id}`, {org_access: 'view'}); } catch { /* shown; the folder stays private to the admins */ } }
  ab_reload();
  offerUndo(tr('Folder “{0}” created', n.name), histAdd({label: tr('New folder “{0}”', n.name), undo: () => ab_req('DELETE', `/api/files/nodes/${n.id}`), redo: () => ab_req('POST', `/api/files/nodes/${n.id}/restore`)}));
}
document.addEventListener('click', e => { const b = e.target.closest?.('#side [data-abtadd]'); if (b) { e.preventDefault(); ab_newFolder(null, b.dataset.abtadd); } });  // 2.768.0 (#4888)
// a request of an undo / redo step: the view follows, an error is a toast (api() shows it)
async function ab_req(m, url, b) { try { await api(m, url, b); } catch { /* shown */ } ab_reload(); return {}; }
async function ab_upload(files, target) {
  files = [...(files || [])]; if (!files.length) return;
  const lid = await ab_lockOf(target);  // 2.353.0 A (#2758): encrypted here; F (review N8): also a folder outside the view, never plain
  if (lid) return typeof fsl_upload === 'function' ? fsl_upload(files, target, lid) : ab_noFsl();
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
  if (n.locked && n.lock_id !== n.id) return typeof fsl_rename === 'function' ? fsl_rename(n) : ab_noFsl();  // 2.353.0 A (#2758); F (review N8): never plain
  // 2.359.2 B (#3049): renamed before the dialog closes; on an error it stays open with the typed name (api() said why)
  let r = null;
  await askPrompt(tr('Rename'), n.name, {ok: tr('Save'), input: {max: 150},
    submit: async v => { if (v && v.trim() && v !== n.name) r = await api('PATCH', `/api/files/nodes/${n.id}`, {name: v}); }});
  if (!r) return;  // (r alone: a dialog cancelled while the save ran has renamed all the same - review 2.359.2)
  ab_reload();
  const was = n.name;
  offerUndo(tr('Renamed to “{0}”', r.name), histAdd({label: tr('Rename “{0}”', was), undo: () => ab_req('PATCH', `/api/files/nodes/${n.id}`, {name: was}), redo: () => ab_req('PATCH', `/api/files/nodes/${n.id}`, {name: r.name})}));
}
async function ab_move(n, target) {
  if (target === undefined) return ab_moveDlg(n);
  const was = n.parent_id ?? null;
  if ((target || null) === was) return;
  if (typeof fsl_moveHook === 'function' && await fsl_moveHook(n, target)) return;  // 2.353.0 A (#2758): across a locked folder's border
  try { await api('PATCH', `/api/files/nodes/${n.id}`, {parent_id: target || null}); } catch { return; }
  ab_reload();
  offerUndo(tr('“{0}” moved', n.name), histAdd({label: tr('Move “{0}”', n.name), undo: () => ab_req('PATCH', `/api/files/nodes/${n.id}`, {parent_id: was}), redo: () => ab_req('PATCH', `/api/files/nodes/${n.id}`, {parent_id: target || null})}));
}
// 2.953 (#3348, review N16): the folders of "Move to…" -- the names below a locked folder decrypted here (fslock.js), never as ciphers
async function ab_moveTargets() {
  const fs = (await api('GET', '/api/files/folders?ablage=1')).folders || [];
  if (fs.some(f => f.lock_id)) {
    if (typeof fsl_paths !== 'function' && typeof loadModule === 'function') await loadModule('fslock').catch(() => {});
    if (typeof fsl_paths === 'function') await fsl_paths(fs); else for (const f of fs) if (f.lock_id) f.path = f.parts.map(p => p.startsWith('e2e1:') ? tr('Encrypted') : p).join(' / ');
  }
  return fs;
}
async function ab_moveDlg(n, at) {  // 2.768.0 (#4888): at = the anchor of the menu (the document view's Actions)
  let fs; try { fs = await ab_moveTargets(); } catch { return; }
  // the same space and tree only (the server refuses the rest, and a folder into itself)
  const ok = fs.filter(f => (f.org_id || null) === (n.org_id || null) && f.owner_id === n.owner_id && f.id !== n.id && f.id !== n.parent_id);
  const items = [...(n.parent_id ? [{label: tr('Top level'), icon: 'up', fn: () => ab_move(n, null)}] : []), ...ok.map(f => ({label: f.path, icon: 'folder', fn: () => ab_move(n, f.id)}))];
  if (!items.length) { toast(tr('No other folder in this workspace')); return; }
  const anchor = at || $(`[data-abid="${n.id}"] [data-ab="menu"]`) || $('[data-ab="menu"]') || document.body;
  menu(anchor, [{head: tr('Move to …')}, ...items.slice(0, 60)], null, null, tr('Move to …'));
}
const ab_delete = n => abm_trash([n]);  // 2.768.0 (#4888): the same way as the bar (POST /api/files/trash, ONE undo)
async function ab_restore(n) {
  let r; try { r = await api('POST', `/api/files/nodes/${n.id}/restore`); } catch { return; }
  ab_reload();
  const st = r?.stays?.sheet, sw = r?.stays?.wiki;  // 2.373.0 (#3335): a table the person may not edit stays in the tables' trash; 2.528.0 D (#4306): a page too
  offerUndo([tr('“{0}” restored', n.name), st ? trn("{0} table stays in the tables' trash", "{0} tables stay in the tables' trash", st) : '', sw ? trn('{0} page stays in the knowledge trash', '{0} pages stay in the knowledge trash', sw) : ''].filter(Boolean).join(' · '), histAdd({label: tr('Restore “{0}”', n.name), undo: () => ab_req('DELETE', `/api/files/nodes/${n.id}`), redo: () => ab_req('POST', `/api/files/nodes/${n.id}/restore`)}));
}
async function ab_purge(n) {
  if (!await askConfirm(tr('Delete “{0}” permanently?', n.name), tr('All versions are removed. This cannot be undone.'), {ok: tr('Delete permanently'), danger: true})) return;
  try { await api('DELETE', `/api/files/nodes/${n.id}?purge=1`); } catch { return; }
  AB.sel.delete(n.id); ab_reload(); toast(tr('Deleted permanently'));
}
function ab_newVersion(n) {
  if (n.locked) return typeof fsl_newVersion === 'function' ? fsl_newVersion(n) : ab_noFsl();  // 2.353.0 A (#2758); F (review N8): never plain
  const inp = document.createElement('input'); inp.type = 'file';
  inp.addEventListener('change', () => { const f = inp.files?.[0]; if (f) ab_newVersionFile(n, f); });
  inp.click();
}
// 2.633.0 (#4920): the chosen / dropped file as a new version (the details dialog's fixed input, ab_details)
async function ab_newVersionFile(n, f) {
  if (n.locked) return typeof fsl_newVersionFile === 'function' ? fsl_newVersionFile(n, f) : ab_noFsl();  // never plain (as above)
  const fd = new FormData(); fd.append('file', f, f.name);
  if (n.version) fd.append('expect_version', n.version);  // 2.577.0 (#4708 3): another version came meanwhile -> 409, nothing stored
  const was = n.version;
  let r; try { r = await api('POST', `/api/files/nodes/${n.id}/versions`, fd); } catch { return; }
  ab_verAfter(n.id);
  // 2.768.0 (#4888): one undo step - the version before becomes the newest again (the server keeps every version)
  if (!was || !r?.version) { toast(tr('New version of “{0}” saved', n.name)); return; }
  offerUndo(tr('New version of “{0}” saved', n.name), histAdd({label: tr('New version of “{0}”', n.name), undo: () => ab_verStep(n, was), redo: () => ab_verStep(n, r.version)}));
}
function ab_menu(anchor, n, pick) { menu(anchor, pick ? [...cm_selHead(n.name, pick), ...ab_menuItems(n)] : ab_menuItems(n), null, null, pick ? '' : n.name); }  // 2.607.0 (#4612): pick = "Select" on top
// 2.199.0 A (#2742): the items of a node's menu (the row's "…", the tree's right-click / long press); tree: + New folder…
function ab_menuItems(n, tree) {
  const w = ab_canWrite(n.role), own = n.role === 'owner', f = n.kind !== 'folder', ref = n.kind === 'ref';
  return [
    f ? {label: tr('Open'), icon: 'eye', fn: () => n._open ? n._open() : ab_openFile(n)} : null,  // 2.768.0 (#4888): _open = a document card's own way (its list to leaf through)
    ...(f && n._spl && typeof spl_item === 'function' ? spl_item(n._spl) : []),  // 2.742.0 (#4858): a document card: Open on the right
    ...(ref ? [] : fv2_menuRow('file:' + n.id)),  // 2.441.0 (#3592)
    f && !ref ? {label: tr('Download'), icon: 'download', fn: () => { if (n._enc && typeof fsl_open === 'function') return fsl_open(n, true); const a = document.createElement('a'); a.href = ab_url(n, true); a.download = attDlName(n.name, n.mime); document.body.appendChild(a); a.click(); a.remove(); }} : null,  // 2.750.0 (#4876): + the ending
    tree && w && !f ? {label: tr('New folder…'), icon: 'plus', fn: () => ab_newFolder(n.id)} : null,
    n.kind === 'folder' ? {label: tr('Download as ZIP'), icon: 'download', fn: () => abm_download([n])} : null,  // 2.112.1 A (#2058)
    {label: tr('Details and history'), icon: 'info', fn: () => ab_detailsOf(n)},  // 2.768.0 (#4888): a file: the document view's tab History
    w && n.kind === 'folder' && !n.agent_id && !n.locked ? {label: tr('Request files…'), icon: 'upload', fn: () => frq_open(n)} : null,  // 2.122.0 A (#2097)
    own ? {label: tr('Share…'), icon: 'users', fn: () => ab_share(n.id)} : null,
    typeof xl_menuItem === 'function' && !n.locked ? xl_menuItem(n) : null,  // 2.112.1 B (#2058); 2.353.0 A (#2758): no links for externals
    typeof fsl_menuItem === 'function' ? fsl_menuItem(n) : null,  // 2.353.0 A (#2758): lock / the lock's dialog
    ...(typeof abd_menuItems === 'function' ? abd_menuItems(n) : []),  // 2.353.0 D (#2759): Recognise / Recognition…
    ...(typeof dsc_folderItems === 'function' ? dsc_folderItems(n) : []),  // 2.1048.0 (#5821): Scan inbox for this folder… (docscan.js)
    '-',
    w && n.kind === 'file' ? {label: tr('Upload a new version…'), icon: 'upload', fn: () => ab_newVersion(n)} : null,
    w && !ref ? {label: tr('Rename…'), icon: 'edit', fn: () => ab_rename(n)} : null,
    w && typeof dt_abEdit === 'function' ? {label: tr('Tags…'), icon: 'tag', fn: () => dt_abEdit(n)} : null,  // 2.122.0 B (#2099)
    w ? {label: tr('Move to…'), icon: 'arrow', fn: () => ab_moveDlg(n)} : null,
    ab_smvOk(n) && !n.locked && smv_can(n.org_id) ? {label: tr('Move to another workspace…'), icon: 'building', fn: () => ab_smvSpace([n])} : null,  // 2.96.0 A (#1941)
    '-',
    w && (n.parent_id || own) ? {label: tr('Move to the trash'), icon: 'trash', cls: 'danger', fn: () => ab_delete(n)} : null];
}

// ---- details: versions, shares, history
const AB_ACT = {list: N_('opened the folder'), read: N_('read'), download: N_('downloaded'), text: N_('read the text'), meta: N_('looked at the details'),
  write: N_('created'), upload: N_('uploaded'), version: N_('uploaded a new version'), restore_version: N_('restored a version'), rename: N_('renamed'),
  move: N_('moved'), order: N_('sorted'), trash: N_('moved to the trash'), restore: N_('restored'), share: N_('shared'), share_change: N_('changed a share'),
  unshare: N_('stopped sharing'), org_access: N_('changed who in the organisation sees it'), create: N_('created'), link: N_('linked'),
  moved_space: N_('moved to another workspace'),  // 2.96.0 A (#1941)
  tags: N_('changed the tags'),  // 2.122.0 B (#2099)
  recognise: N_('changed the recognition'),  // 2.353.0 D (#2759)
  flow: N_('ran a document flow'), 'flow-undo': N_('took a document flow back')};  // 2.581.0 (#4803): docs/flows.py
// 2.768.0 (#4888): the details of a file are the document view (docview.js), its tab History: versions, history, "Mentioned in".
// The dialog below stays for folders and for the files the view does not open (encrypted, locked by the virus scanner, a link,
// the trash, documents off) - both draw the same parts (ab_versHtml, ab_logHtml, ab_wikiRefs), nothing twice.
const ab_viewOk = n => n.kind === 'file' && !n.in_trash && !n.deleted_at && !n.locked && !n._enc && !upLocked(n) && typeof abd_on === 'function' && abd_on() && typeof dc_open === 'function';
function ab_detailsOf(n) { if (ab_viewOk(n)) dc_open(n.id, {tab: 'hist'}); else ab_details(n.id); }
// the versions: each one to view (the viewer of its kind), to download and - with the right to write - to restore; on top the
// upload of a new version (a fixed hidden input: a file dropped onto the window lands there too, dropany.js)
function ab_versHtml(n) {
  if (n.kind !== 'file') return '';
  const w = ab_canWrite(n.role);
  const vers = (n.versions || []).map(v => {
    const cur = v.no === n.version, see = !n._enc && !n.locked && ab_verKind(n, v);
    return `<div class="abvrow" data-abvno="${v.no}"><span><b>v${v.no}</b>${cur ? ` <small class="muted">(${esc(tr('current'))})</small>` : ''} · ${esc(ab_when(v.created_at))} · ${fmtSize(v.size)}${v.by ? ' · ' + esc(v.by) : ''}</span><span class="spacer"></span>${see ? `<button type="button" class="iconbtn" data-abvv="${v.no}" title="${esc(tr('View version {0}', v.no))}" aria-label="${esc(tr('View version {0}', v.no))}">${ic('eye', 's')}</button>` : ''}<a class="iconbtn" href="${n._enc ? '#' : ab_url(n, true, v.no)}" ${n._enc ? `data-fslv="${v.no}" data-fslid="${n.id}" data-fsllk="${n.lock_id}"` : ''} download="${esc(n.name)}" title="${esc(tr('Download'))}" aria-label="${esc(tr('Download version {0}', v.no))}">${ic('download', 's')}</a>${w && !cur ? `<button type="button" class="btn sm" data-abv="${v.no}">${tr('Restore')}</button>` : ''}</div>`;
  }).join('');
  const up = w ? `<div class="row abvup"><input type="file" id="abd-verfile" hidden><button type="button" class="btn sm" data-abd="ver">${ic('upload', 's')} ${tr('Upload a new version…')}</button></div>` : '';
  return `<h4>${tr('Versions')}</h4>${up}${vers ? `<div class="abvers">${vers}</div>` : ''}`;
}
// the history (owners and editors get it from the server, readers not)
function ab_logHtml(n) {
  if (!n.log) return '';
  const log = n.log.map(x => `<div class="ablrow ${x.agent ? 'abag' : ''}">${x.agent ? ic('bot', 's') : ic('user', 's')}<span><b>${esc(x.name || (typeof xl_logWho === 'function' && xl_logWho(x)) || '?')}</b> ${esc(tr(AB_ACT[x.action] || x.action))}</span><span class="spacer"></span><small class="muted">${esc(fmtDay('short', new Date(x.at)))} ${esc(fmtTimeAt(new Date(x.at)))}</small></div>`).join('');
  return `<h4>${tr('History')}</h4><div class="ablog">${log || `<span class="muted">${tr('Nothing yet')}</span>`}</div><p class="muted abhint">${tr('Every access of an agent is listed here.')}</p>`;
}
// which viewer a version opens in ('' = none, it downloads)
function ab_verKind(n, v) {
  const m = {...n, mime: v.mime || n.mime};
  return ab_isPdf(m) ? 'pdf' : ab_isImg(m) ? 'img' : typeof isTextFile === 'function' && isTextFile(m) && (v.size || 0) <= TV_MAX ? 'text' : '';
}
function ab_verOpen(n, no) {
  const v = (n.versions || []).find(x => x.no === no); if (!v) return;
  const k = ab_verKind(n, v), name = `${n.name} · v${no}`, o = {url: ab_url(n, false, no), name, size: v.size, dlUrl: ab_url(n, true, no)};
  if (k === 'pdf' && typeof pdfView === 'function') pdfView(o);
  else if (k === 'img' && typeof pdfView === 'function') pdfView({...o, img: o.url, kind: 'img'});
  else if (k === 'text') textView({url: o.dlUrl, name, size: v.size, md: isMdFile(n), ext: attExt(n)});
}
// one version back on top (the restore of the server: a new version with its content), the dialog / the view follow
async function ab_verStep(n, no) {
  try { await api('POST', `/api/files/nodes/${n.id}/versions/${no}/restore`); } catch { /* shown */ }
  ab_verAfter(n.id); return {};
}
async function ab_verRestore(n, no) {
  const was = n.version;
  let r; try { r = await api('POST', `/api/files/nodes/${n.id}/versions/${no}/restore`, was ? {expect_version: was} : undefined); } catch { return; }
  ab_verAfter(n.id);
  const msg = tr('Version {0} is the newest again (as version {1})', no, r.version);
  if (!was || n.locked) { toast(msg); return; }  // an encrypted file: as before, no step back
  offerUndo(msg, histAdd({label: tr('Restore version {0}', no), undo: () => ab_verStep(n, was), redo: () => ab_verStep(n, no)}));
}
// a click inside the versions (the dialog, the view's tab History); true = it was one of theirs
function ab_verClick(n, e, box) {
  const t = /** @type {any} */ (e.target), b = t.closest?.('[data-abv], [data-abvv], [data-abd="ver"]'); if (!b) return false;
  if (b.dataset.abvv) ab_verOpen(n, +b.dataset.abvv);
  else if (b.dataset.abv) ab_verRestore(n, +b.dataset.abv);
  else $('#abd-verfile', box)?.click();  // 2.633.0 (#4920): fixed hidden file input, its change uploads (a drop onto the window too, dropany.js)
  return true;
}
// after a new / restored version: the list, the open dialog and the open view (docview.js) read it again
function ab_verAfter(id) {
  ab_reload();
  if ($('.abdlg')?.dataset.abid === String(id)) ab_details(id);
  if (typeof dcv_verAfter === 'function') dcv_verAfter(id);
}
// 2.123.0 C (#2103, #2107): the knowledge pages (that I may read) which show or link this file; 2.768.0 (#4888): into box
async function ab_wikiRefs(box, id) {
  if (!box || !feat('wiki')) return;
  let ps; try { ps = (await rawFetch('GET', '/api/wiki/refs?file=' + id)).pages || []; } catch { return; }
  if (!box.isConnected) return;
  box.innerHTML = ps.length ? `<div class="dsec wkmen">${ic('book', 's')}<span class="muted">${tr('Mentioned in')}</span>${ps.map(p => `<a href="#wiki/${p.id}" data-m="close">${esc(p.path)}</a>`).join('<span class="muted">,</span>')}</div>` : '';
}
async function ab_details(id) {
  let n; try { n = await api('GET', `/api/files/nodes/${id}`); } catch { return; }
  if (ab_viewOk(n)) { $('.abdlg')?.remove(); dc_open(n.id, {tab: 'hist'}); return; }  // 2.768.0 (#4888): a file: the view
  if (typeof fsl_prep1 === 'function') await fsl_prep1(n);  // 2.353.0 A (#2758)
  $('.abdlg')?.remove();
  const shares = n.role === 'owner' ? [...(n.shares || []), ...(n.inherited || [])] : [];
  const md = modal(`<div class="lhdr"><h3>${ab_icon(n)} ${esc(n.name)}</h3><span class="spacer"></span><button class="iconbtn" data-m="close" aria-label="${tr('Close')}" title="${tr('Close')}">${ic('x')}</button></div>
    <div class="muted abpath">${esc((n.crumbs || []).map(c => c.name).join(' / '))}</div>
    <div class="abfacts">${n.kind !== 'folder' ? `<span>${fmtSize(n.size || 0)}</span>` : ''}<span>${esc(tr('Changed {0}', ab_when(n.updated_at)))}</span>${n.owner ? `<span>${esc(tr('Owner: {0}', n.owner))}</span>` : ''}<span>${esc(ab_role(n.role))}</span></div>
    ${typeof dt_abDetails === 'function' ? dt_abDetails(n) : ''}
    ${n.kind === 'link' ? `<div class="shint keep">${ic('link', 's')} ${esc(tr('A link to a file of a task or project. Whoever opens it needs access to the original.'))}</div>` : ''}
    ${n.kind !== 'folder' ? `<div class="row"><button type="button" class="btn sm" data-abd="open">${ic('eye', 's')} ${tr('Open')}</button></div>` : ''}
    ${ab_versHtml(n)}
    ${n.role === 'owner' ? `<h4>${tr('Shared with')}</h4><div class="abshsum">${shares.length || n.org_access || n.org_access_from ? shares.map(s => `<span class="abshp">${s.agent_id ? ic('bot', 's') : s.group_id ? ic('users', 's') : ic('user', 's')}${esc(s.name)} · ${esc(ab_role(s.role))}${s.from ? ` <small class="muted">${esc(tr('from “{0}”', s.from))}</small>` : ''}</span>`).join('') + (n.org_access || n.org_access_from ? `<span class="abshp">${ic('building', 's')}${esc(tr('Whole organisation'))}</span>` : '') : `<span class="muted">${tr('Only you')}</span>`}</div><div class="row"><button type="button" class="btn sm" data-abd="share">${ic('users', 's')} ${tr('Share…')}</button></div>` : ''}
    ${ab_logHtml(n)}
    ${n.kind === 'file' ? '<div class="abrefs"></div>' : ''}
    <div class="foot"><span class="spacer"></span><button class="btn pri" data-m="close">${tr('Done')}</button></div>`);
  md.classList.add('abdlg'); md.dataset.abid = String(n.id);
  ab_wikiRefs($('.abrefs', md), n.id);  // 2.123.0 C (#2107)
  if (typeof xl_mount === 'function') xl_mount(md, n);  // 2.112.1 B (#2058): "Link for external people"
  md.addEventListener('change', e => { const t = e.target; if (t.id === 'abd-verfile' && t.files?.length) { const f = t.files[0]; t.value = ''; ab_newVersionFile(n, f); } });  // 2.633.0 (#4920)
  md.addEventListener('click', async e => {
    if (e.target.closest('[data-m="close"]')) { modalClose(md); return; }
    if (ab_verClick(n, e, md)) return;
    const b = e.target.closest('[data-abd]'); if (!b) return;
    if (b.dataset.abd === 'open') ab_openFile(n);
    else if (b.dataset.abd === 'tags' && typeof dt_abEdit === 'function') dt_abEdit(n, () => ab_details(n.id));  // 2.122.0 B (#2099)
    else if (b.dataset.abd === 'share') { modalClose(md); ab_share(n.id); }
  });
}

// ---- the Share dialog: since 2.199.0 A (#2742) the shared one of fsshare.js (loaded on first use, lazyload.js)
const ab_share = (id, opts) => fs_shareDialog(id, opts);

// ---- events
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-ab]'); if (!b || !b.closest('.abview, #pop')) return;
  const n = ab_item(b.dataset.id), a = b.dataset.ab;
  if (a === 'space') { ab_pick(b.dataset.sp); AB.key = ''; if (ab_all()) go(ab_home(b.dataset.sp)); else if (S.route.nid || S.route.aus) go('ablage'); else ab_load(); return; }  // 2.540.0 (#4575): under "All" its address  // 2.429.0 (#3580): + from a collection
  if (a === 'new-folder') { ab_newFolder(); return; }
  if (a === 'upload') { $('#ab-file')?.click(); return; }
  if (a === 'scan') { abm_scan(); return; }  // 2.112.1 A (#2058)
  if (a === 'open' && n && b.closest('.ablist') && AB.selHere && (AB.selOn || (ms_modClick(e) && !isMobile()))) { e.preventDefault(); ab_selPick(n.id, e.shiftKey); return; }  // 2.428.0 A (#3581)
  if (a === 'open' && n) { if (n.kind === 'folder') go('ablage/' + n.id); else ab_openFile(n); return; }
  if (a === 'menu' && b.closest('.dc-card')) { ab_cardMenu(b.closest('.dc-card'), b); return; }  // 2.768.0 (#4888): a card's "…" = its menu with "Select" on top
  if (a === 'menu' && n && b.closest('.ablist') && ab_selMany(n.id)) { ab_selMenu(b); return; }  // 2.768.0 (#4888): a chosen row of several: the selection's menu
  if (a === 'menu' && n) { ab_menu(b, n); return; }
  if (a === 'share') { e.preventDefault(); e.stopPropagation(); ab_share(+b.dataset.id); return; }  // 2.558.0 (#4693): the names / "Share" on top
  if (a === 'scandone-x') { AB.scanDone = null; ab_draw(); return; }
  if (a === 'restore' && n) ab_restore(n);
  if (a === 'purge' && n) ab_purge(n);  // 2.589.0 (#4875)
  if (a === 'trash-empty') abm_purge(null);
});
// 2.210 B (#2757): a right click / long press on a row of the list or a folder of the panel = its "…" menu (ab_menu)
function ab_ctxNode(id) {  // the panel's folders: from its cache, else asked for (the menu opens once it is there)
  const n = ab_item(id) || Object.values(AB.pt).flatMap(x => x.items || []).find(x => x.id === +id);
  return n ? Promise.resolve(n) : api('GET', `/api/files/nodes/${+id}`).catch(() => null);
}
// 2.607.0 (#4612): a long press too opens the menu, "Select" on top (a row of the list where choosing is offered); while choosing runs
// a long press ticks the row (like a tap)
const ab_canPickRow = r => AB.selHere && !!r.closest('.ablist') && !!ab_item(+r.dataset.abid);
const ab_rowCm = r => {  // the panel's folders: sbb_treeReg('ab') menu (2.199.0)
  const m = r.querySelector('[data-ab="menu"]'), id = m && m.dataset.id; if (!id) return false;  // trash rows: no menu
  if (r.closest('.ablist') && ab_selMany(id)) { ab_selMenu(m); return true; }  // 2.768.0 (#4888)
  const pick = ab_canPickRow(r) ? (rid => () => ab_selPick(rid))(+r.dataset.abid) : null;
  ab_ctxNode(id).then(n => { if (n && r.isConnected) ab_menu(m || r.querySelector('.sbbtn') || r, n, pick); });
  return true;
}, ab_rowPick = r => { if (!AB.selOn || !ab_canPickRow(r)) return false; ab_selPick(+r.dataset.abid); return true; };
const AB_LP = cm_bind('#view .abview .abrow', ab_rowCm, ab_rowPick);
document.addEventListener('change', e => { if (e.target.id === 'ab-file') { const fs = e.target.files; ab_upload(fs, S.route.nid || null); e.target.value = ''; } });
// dropping files from the computer into the open folder / onto a folder row; dragging a row onto a folder (or the path) moves it
// 2.750.0 (#4879): every part of a row or card starts the move (its picture and link too - their own drag carried a file and
// uploaded it as a new version onto itself); the drag carries the node id as KN_MIME (dropany.js kn_dragSet, shared with the
// documents' cards later), the drops below move by it and upload only a drag that did not begin in Kalmido (kn_has)
// 2.768.0 (#4888): + the cards of "All documents" / "To review" (onto a folder of the panel); a row or card of the choice drags the
// whole choice (what the person may change), one drop = ONE undo step (ab_selMoveTo, the bar's Move)
const ab_dragSrc = t => /** @type {any} */ (t)?.closest?.('.abview .abrow[data-abid], #view .dc-view .dc-card [data-dco], .abview .dc-card [data-ab="open"][data-id], #view .dc-view .dc-card[draggable], .abview .dc-card[draggable]');
const ab_dragObj = id => (typeof ab_selObj === 'function' ? ab_selObj(id) : null) || ab_item(id);
// the nodes a drag of id moves: the choice when id is ticked in it (only what the person may change), else id alone
function ab_dragIds(id) {
  if (!(AB.selOn && AB.sel.has(id) && AB.sel.size > 1)) return [id];
  return [...AB.sel.values()].filter(x => ab_canWrite(x.role)).map(x => x.id);
}
// a target folder takes the drag: not one of the dragged nodes, not (for one node) its own folder
const ab_dropOk = to => { const ids = AB.dragIds || []; if (!ids.length || ids.includes(to)) return false; return ids.length > 1 || ab_moveTo(ab_dragObj(ids[0]), to); };
// the drop: one node the plain way (ab_move: locked folders, its undo), several as the bar's Move (one undo, the skipped counted)
function ab_dragDrop(to) {
  const ids = AB.dragIds || []; AB.drag = null; AB.dragIds = null;
  if (!ids.length || ids.includes(to)) return;
  if (ids.length === 1) { const n = ab_dragObj(ids[0]); if (n && ab_canMove(n) && ab_moveTo(n, to)) { if (ab_item(n.id)) ab_move(n, to); else ab_selMoveTo([ab_selInfo(n)], to); } return; }
  const xs = ids.map(i => AB.sel.get(i)).filter(Boolean);
  ab_selMoveTo(xs, to, AB.sel.size - xs.length);
}
const ab_dragId = r => r.classList.contains('dc-card') ? ab_cardId(r) : +(r.dataset.abid || r.dataset.dco || r.dataset.id) || 0;
const ab_canMove = n => !!n && ab_canWrite(n.role) && !(!S.route.nid && ab_curSpace() === 'trash');
const ab_moveTo = (n, to) => !!n && to !== n.id && (to ?? null) !== (n.parent_id ?? null);  // not onto itself, not into its own folder (nothing to do)
document.addEventListener('dragstart', e => {
  const r = ab_dragSrc(e.target); if (!r || !e.dataTransfer) return;
  const id = ab_dragId(r), n = ab_dragObj(id), ids = ab_dragIds(id); kn_dragSet(e, ids);
  if (!ab_canMove(n) || !ids.length) return;  // read-only / the trash: no move (KN_MIME still keeps it from uploading)
  AB.drag = id; AB.dragIds = ids; e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', ids.length > 1 || n?.locked ? '' : n?.name || '');  // 2.353.0 F (#2758, review N9): no plain name of a locked folder
});
document.addEventListener('dragend', () => { AB.drag = null; AB.dragIds = null; $$('.abdrop').forEach(x => x.classList.remove('abdrop')); });
document.addEventListener('dragover', e => {
  const v = e.target.closest?.('.abview'); if (!v) { ab_sideOver(e); return; }
  const files = [...(e.dataTransfer?.types || [])].includes('Files') && !kn_has(e), t = e.target.closest('[data-abdrop]');  // 2.750.0 (#4879)
  if (AB.drag && t && ab_dropOk(t.dataset.abdrop === 'top' ? null : +t.dataset.abdrop)) { e.preventDefault(); $$('.abdrop').forEach(x => x !== t && x.classList.remove('abdrop')); t.classList.add('abdrop'); return; }  // 2.750.0 (#4879): its own folder takes nothing
  if (files && v.classList.contains('abdropok')) { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; v.classList.add('abdrop'); }
});
document.addEventListener('dragleave', e => { if (e.target.classList?.contains('abview') && !e.target.contains(e.relatedTarget)) e.target.classList.remove('abdrop'); });
document.addEventListener('drop', e => {
  const v = e.target.closest?.('.abview'); if (!v) { ab_sideDrop(e); return; }
  e.preventDefault(); $$('.abdrop').forEach(x => x.classList.remove('abdrop'));
  const t = e.target.closest('[data-abdrop]');
  if (AB.drag || kn_has(e)) { if (!AB.dragIds && !AB.drag) AB.dragIds = kn_ids(e).slice(0, 1); const to = t ? (t.dataset.abdrop === 'top' ? null : +t.dataset.abdrop) : undefined; if (t && to !== undefined) ab_dragDrop(to); else { AB.drag = null; AB.dragIds = null; } return; }  // 2.750.0 (#4879): a drag from Kalmido never uploads; 2.768.0 (#4888): the whole choice
  const fs = e.dataTransfer?.files; if (!fs?.length || !v.classList.contains('abdropok')) return;
  ab_upload(fs, t && t.dataset.abdrop !== 'top' ? +t.dataset.abdrop : S.route.nid || null);
});

// 2.627.0 (#4961): the finger by drag.js: hold a row, then drag it onto a folder (a row, the path, the panel's folders) = the
// same ab_move as the mouse's drop; a swipe without the hold scrolls, a quick tap opens as before, held and let go without
// moving = what the long press did (the menu, or a tick while choosing). The mouse keeps the browser's drag above.
const ab_fingerT = (d, x, y) => {
  const t = /** @type {any} */ (document.elementFromPoint(x, y))?.closest?.('#view .abview [data-abdrop], #side [data-abdrop]');
  return t && t.dataset.abdrop !== String(d.id) && !(d.ids || []).includes(+t.dataset.abdrop) ? t : null;  // 2.768.0 (#4888): not one of the dragged
};
// 2.768.0 (#4888): the finger's drop = the mouse's (ab_dragDrop: one node, or the whole choice with one undo)
const ab_fingerDrop = (d, x, y) => { const t = ab_fingerT(d, x, y); ab_fingerOff(d); if (!t) return; AB.drag = d.id; AB.dragIds = d.ids; ab_dragDrop(t.dataset.abdrop === 'top' ? null : +t.dataset.abdrop); };
const ab_fingerOff = d => { d.r.classList.remove('dragging'); $$('.abdrop').forEach(x => x.classList.remove('abdrop')); };
drg_attach(document, {
  mouse: false, hold: ROWD_HOLD, holdMove: 8, onTarget: true, raf: true, ghost: {el: d => d.r, cls: 'ghost-drag'},
  scroll: () => tdScroller($('#view')), edge: TD_EDGE, step: TD_MAX,
  start: t => {
    const r = /** @type {any} */ (t).closest?.('#view .abview .abrow[data-abmv]');
    return r && !t.closest('input, textarea, select') && ab_item(+r.dataset.abid) ? {r, id: +r.dataset.abid, ids: ab_dragIds(+r.dataset.abid)} : null;
  },
  onHold: d => { ms_lpTake(AB_LP); d.r.classList.add('dragging'); if (navigator.vibrate) navigator.vibrate(12); },
  onMove: (d, x, y) => { const t = ab_fingerT(d, x, y); $$('.abdrop').forEach(b => b !== t && b.classList.remove('abdrop')); t?.classList.add('abdrop'); },
  onDrop: ab_fingerDrop,
  onTap: d => { ab_fingerOff(d); const r = d.r.isConnected ? d.r : $(`#view .abview .abrow[data-abid="${d.id}"]`); if (r) ab_rowPick(r) || ab_rowCm(r); },
  onCancel: ab_fingerOff,
});
// 2.768.0 (#4888): the cards the same way (documents, files, folders): hold, then drag onto a folder; held and let go unmoved =
// the long press (the card's menu with "Select" on top, or a tick while choosing)
drg_attach(document, {
  mouse: false, hold: ROWD_HOLD, holdMove: 8, onTarget: true, raf: true, ghost: {el: d => d.r, cls: 'ghost-drag'},
  scroll: () => tdScroller($('#view')), edge: TD_EDGE, step: TD_MAX,
  start: t => {
    const r = /** @type {any} */ (t).closest?.('#view .dc-card[data-abmv]'), id = r && ab_cardId(r);
    return id && !t.closest('input, textarea, select, [data-ab="menu"]') ? {r, id, ids: ab_dragIds(id)} : null;
  },
  onHold: d => { ms_lpTake(AB_CARDLP); d.r.classList.add('dragging'); if (navigator.vibrate) navigator.vibrate(12); },
  onMove: (d, x, y) => { const t = ab_fingerT(d, x, y); $$('.abdrop').forEach(b => b !== t && b.classList.remove('abdrop')); t?.classList.add('abdrop'); },
  onDrop: ab_fingerDrop,
  onTap: d => { ab_fingerOff(d); if (d.r.isConnected) ab_cardPick(d.r) || ab_cardMenu(d.r); },
  onCancel: ab_fingerOff,
});

// 2.152.3 B (#2621): a folder in the panel takes a dragged file row (moves it) or files from the computer (upload into it)
const ab_sideT = e => { const t = e.target.closest?.('#side [data-abdrop]'); return t && (AB.drag ? ab_dropOk(+t.dataset.abdrop) : [...(e.dataTransfer?.types || [])].includes('Files') && !kn_has(e)) ? t : null; };  // 2.750.0 (#4879): + not a drag from Kalmido
function ab_sideOver(e) {
  const t = ab_sideT(e); $$('#side .abdrop').forEach(x => x !== t && x.classList.remove('abdrop')); if (!t) return;
  e.preventDefault(); e.dataTransfer.dropEffect = AB.drag ? 'move' : 'copy'; t.classList.add('abdrop');
}
function ab_sideDrop(e) {
  const t = ab_sideT(e); if (!t) return;
  e.preventDefault(); $$('.abdrop').forEach(x => x.classList.remove('abdrop'));
  if (AB.drag) { ab_dragDrop(+t.dataset.abdrop); return; }  // 2.768.0 (#4888): one node or the whole choice
  if (e.dataTransfer?.files?.length && !kn_has(e)) ab_upload(e.dataTransfer.files, +t.dataset.abdrop);
}
// ---- "Show in the file store" for a task / project file: a link at the top of the file's workspace (no copy; the original's
// rights stay). The button sits on the file tiles of tasks (attachments.js) and project pages (projects.js).
async function ab_linkFile(refKind, refId, org) {
  let n; try { n = await api('POST', '/api/files/links', {ref_kind: refKind, ref_id: refId, space: org ? 'org:' + org : 'private'}); } catch { return; }
  if (S.route.mod === 'ablage') ab_reload();
  offerUndo(tr('“{0}” is now in your files', n.name), histAdd({label: tr('Show “{0}” in the file store', n.name), undo: () => ab_req('DELETE', `/api/files/nodes/${n.id}`), redo: () => ab_req('POST', `/api/files/nodes/${n.id}/restore`)}));
}

// ---- 2.768.0 (#4888): ONE selection of the area "Files" for rows AND cards (documents, files, folders) in every view of it: a
// folder's list or cards, a folder with recognition (abdocs.js), All documents and To review (docs.js). AB.sel = id -> what the
// bar needs of the node (ab_selInfo: the node's own field names, isdoc = a document); ONE bar (ab_selBar, multisel.js ms_barHtml):
// All, Move (a folder of the area), Download (one file as it is, else a ZIP), Edit (tags, type, sender, what was learned: only with
// documents chosen, docs.js dc_bulkMenu), Move to the trash (asks with the number, ONE undo), More (CSV of the documents, another
// workspace). What the person may not change is left out and counted ("2 skipped"): the server's bulk routes are all or nothing.
// The trash keeps its own bar (ab_trashBar). Replaces AB.sel / AB.selOn of the rows + DC.sel / DC.selOn of the document cards and
// their two bars (2.96.0 A #1941, 2.428.0 A #3581, 2.430.0 #3582). Each action = ONE undo step.
const ab_smvOk = n => !!n && n.kind !== 'link' && !n.agent_id && !n.locked && ab_canWrite(n.role);  // another workspace (2.96.0 A, #1941); 2.953 (#3348, review N16): a locked folder stays in its workspace
const ab_selInfo = x => ({id: x.id, name: x.name || '', kind: x.kind || 'file', role: x.role || '', org_id: x.org_id || null, parent_id: x.parent_id ?? null,
  owner_id: x.owner_id ?? null, agent_id: x.agent_id || null, locked: !!x.locked, up: x.up || null, isdoc: x.kind ? !!x.doc : !x.file,
  lock_id: x.lock_id || null, mime: x.mime || '', _enc: !!x._enc});  // 2.953 (#3348, review N16): what a locked folder's moves / downloads need
// a node of the open folder (with its document, when the documents' list has it) or a document of the list (docs.js DC.docs)
function ab_selObj(id) {
  const n = ab_item(id), d = typeof DC === 'undefined' ? null : (DC.docs || []).find(x => x.id === id);
  return n ? (d && !n.doc ? {...n, doc: d} : n) : d;
}
const ab_selFold = () => typeof dc_inFold === 'function' && dc_inFold();
const ab_selDocs = () => S.route.mod === 'docs' || ab_selFold();  // the documents' list is on screen (its own route or a folder's)
const ab_selOrder = () => $$('#view .ablist .abrow[data-abid], #view .dc-card [data-dcchk], #view .abdl .abdlrow [data-dcchk]')  /* 2.769.0 (#5340): + the list of a recognising folder */.map(x => +(x.dataset.abid || x.dataset.dcchk));
// everything one can choose here: the rows / cards shown and the documents the list has not loaded yet ("All" = every hit, dc_smvAll)
const ab_selTotal = () => ab_selDocs() ? ab_selOrder().length + Math.max(0, (DC.total || 0) - (DC.docs || []).length) : (AB.data?.items || []).length;
const ab_selCtx = () => S.route.mod === 'docs' ? 'docs:' + (S.route.review ? 'r' : '') + ':' + (S.route.dv || '') : 'ab:' + ab_key(S.route);
function ab_selKeep() { const k = ab_selCtx(); if (AB.selCtx !== k) { AB.selCtx = k; ab_selEnd(); } }  // another folder / list: the choice ends
const ab_selEnd = () => { AB.sel.clear(); AB.selOn = false; AB.selLast = null; };
const ab_selDraw = () => { if (S.route.mod === 'docs' && typeof dc_draw === 'function') dc_draw(); else ab_draw(); };
const ab_selVals = () => [...AB.sel.values()];
const ab_skipTxt = k => k ? tr('{0} skipped', k) : '';
const ab_selTools = d => d?.items?.length && !(typeof ftxtActive === 'function' && ftxtActive()) ? `<button type="button" class="btn sm ${AB.selOn ? 'on' : ''}" data-absel="mode" aria-pressed="${!!AB.selOn}">${ic('check', 's')} ${tr('Select')}</button>` : '';
const ab_selBox = n => AB.selOn || AB.selHere ? `<label class="absel" title="${esc(tr('Select {0}', n.name))}"><input type="checkbox" data-absel="one" data-id="${n.id}" ${AB.sel.has(n.id) ? 'checked' : ''} aria-label="${esc(tr('Select {0}', n.name))}"></label>` : '';
function ab_selBar(trash) {
  if (!AB.selOn) return '';
  if (trash) return ab_trashBar();  // 2.589.0 (#4875)
  const xs = ab_selVals(), n = xs.length, docs = xs.some(x => x.isdoc), more = docs || smv_can(xs[0]?.org_id || null);
  return ms_barHtml('ab-sbar', 'absel', n, tr('Tap files'), [['all', 'all', n && n >= ab_selTotal() ? tr('Select none') : tr('All')],
    ['move', 'arrow', tr('Move')], ['dl', 'download', tr('Download')], ...docs ? [['edit', 'edit', tr('Edit')]] : [], ['trash', 'trash', isMobile() ? tr('Trash') : tr('Move to the trash'), 'danger']  /* a phone: the short word (its question says it all) */, ...more ? [['more', 'dots', tr('More')]] : []]);
}
// a tap while choosing / Ctrl- or Cmd-click / the box: one row or card; Shift: the range from the last one (the anchor stays)
function ab_selPick(id, shift) {
  id = +id;
  if (!AB.selOn) { AB.selOn = true; AB.sel.clear(); AB.selLast = null; }
  const on = !AB.sel.has(id), ids = shift && AB.selLast != null && AB.selLast !== id ? ms_range(ab_selOrder(), AB.selLast, id) : [id];
  for (const x of ids) { const o = on && ab_selObj(x); if (o) AB.sel.set(x, ab_selInfo(o)); else if (!on) AB.sel.delete(x); }
  if (ids.length === 1) AB.selLast = id;
  ab_selDraw();
}
async function ab_selAll() {
  if (AB.sel.size && AB.sel.size >= ab_selTotal()) { AB.sel.clear(); ab_selDraw(); return; }
  for (const id of ab_selOrder()) if (!AB.sel.has(id)) { const o = ab_selObj(id); if (o) AB.sel.set(id, ab_selInfo(o)); }
  if (ab_selDocs() && typeof dc_smvAll === 'function' && (DC.total || 0) > (DC.docs || []).length) await dc_smvAll();  // every hit (at most DC_SMV_MAX)
  ab_selDraw();
}
const ab_relist = () => { ab_reload(); if (S.route.mod === 'docs' && typeof dc_load === 'function') { DC.facets = null; dc_load(); } };
// several nodes into one folder of the same space (the server refuses another tree / a folder into itself: counted as skipped)
async function ab_selMove(anchor) {
  const xs = ab_selVals(), ok = xs.filter(x => ab_canWrite(x.role)), skip = xs.length - ok.length;
  if (!ok.length) { toast(ab_skipTxt(skip)); return; }
  const org = ok[0].org_id || null;
  if (ok.some(x => (x.org_id || null) !== org)) { toast(tr('Select items of one workspace')); return; }
  let fs; try { fs = await ab_moveTargets(); } catch { return; }  // no folder in the trash (#4881); 2.953 (#3348): names decrypted
  const own = ok.find(x => x.owner_id != null)?.owner_id, ids = new Set(ok.map(x => x.id));
  const tg = fs.filter(f => (f.org_id || null) === org && (own == null || f.owner_id === own) && !ids.has(f.id));
  const items = [{label: tr('Top level'), icon: 'up', fn: () => ab_selMoveTo(ok, null, skip)}, ...tg.map(f => ({label: f.path, icon: 'folder', fn: () => ab_selMoveTo(ok, f.id, skip)}))];
  menu(anchor || $('[data-absel="move"]') || document.body, [{head: tr('Move to …')}, ...items.slice(0, 60)], null, null, tr('Move to …'));
}
async function ab_selMoveTo(xs, target, skip = 0) {
  const done = [];
  // 2.953 (#3348, review N16): what crosses a locked folder's border goes re-encrypted in the browser, after one question
  let fx = null;
  if (typeof fsl_moveMany === 'function') { try { fx = await fsl_moveMany(xs, target); } catch (e) { if (!e.shown) toast(e.message || tr('unknown')); return; } }
  if (fx?.cancel) return;
  if (fx) { xs = fx.rest; skip += fx.skip; }
  for (const x of xs) {
    if ((x.parent_id ?? null) === (target || null)) continue;
    try { await rawFetch('PATCH', `/api/files/nodes/${x.id}`, {parent_id: target || null}); done.push({id: x.id, was: x.parent_id ?? null}); }
    catch (e) { if (!e.status || e.status >= 500) { toast(e.message || tr('unknown')); break; } skip++; }  // refused: skipped, the rest goes on
  }
  ab_selEnd(); ab_relist(); ab_selDraw();
  if (!done.length) { if (fx?.moved || skip) toast([fx?.moved ? trn('{0} item moved', '{0} items moved', fx.moved) : '', ab_skipTxt(skip)].filter(Boolean).join(' · ')); return; }
  const all = async to => { for (const x of done) { try { await api('PATCH', `/api/files/nodes/${x.id}`, {parent_id: to(x)}); } catch { /* shown */ } } ab_relist(); return {}; };
  offerUndo([trn('{0} item moved', '{0} items moved', done.length + (fx?.moved || 0)), ab_skipTxt(skip)].filter(Boolean).join(' · '), histAdd({label: tr('Move to…'), undo: () => all(x => x.was), redo: () => all(() => target || null)}));
}
function ab_selDl() {
  const xs = ab_selVals(), enc = xs.filter(x => x.locked && x.lock_id !== x.id);  // 2.953 (#3348, review N16): the server holds only ciphertexts
  const ok = xs.filter(x => !enc.includes(x) && abm_dlOk(x)), dec = enc.filter(x => x.kind === 'file' && typeof fsl_open === 'function');
  const skip = xs.length - ok.length - dec.length;
  (async () => { for (const x of dec) await fsl_open(x, true); })();  // each one decrypted here and saved (no ZIP of ciphertexts)
  if (!ok.length) { if (skip) toast(ab_skipTxt(skip)); return; }
  if (ok.length > 1 && ok.every(x => x.isdoc) && typeof dc_zip === 'function') dc_zip(ok.map(x => x.id)); else abm_download(ok);
  if (skip) toast(ab_skipTxt(skip));
}
async function ab_selTrash() {
  const xs = ab_selVals(), ok = xs.filter(abm_trashOk), skip = xs.length - ok.length;
  if (!ok.length) { toast(ab_skipTxt(skip)); return; }
  if (!await askConfirm(trn('Move {0} item to the trash?', 'Move {0} items to the trash?', ok.length), [abm_countText(ok), ab_skipTxt(skip)].filter(Boolean).join(' · '),
    {ok: tr('Move to the trash'), danger: true})) return;
  abm_trash(ok, {skip, end: true});
}
function ab_selMoreItems() {
  const xs = ab_selVals(), docs = xs.filter(x => x.isdoc), orgs = new Set(xs.map(x => x.org_id || null)), from = orgs.size === 1 ? [...orgs][0] : null;
  return [docs.length && typeof dcx_csv === 'function' ? {label: tr('Export as CSV'), icon: 'download', cls: 'msm-csv', fn: () => dcx_csv(docs.map(x => x.id))} : null,
    orgs.size <= 1 && smv_can(from) ? {label: tr('Move to another workspace…'), icon: 'building', cls: 'msm-space', fn: () => ab_selSpace(xs)} : null,
    docs.length && typeof po_selItem === 'function' ? po_selItem(docs) : null,  // 2.892.0 (#4873): Optimise PDF (pdfopt.js)
    docs.length > 1 && docs.length === xs.length && typeof dpm_selItem === 'function' ? dpm_selItem(docs) : null].filter(Boolean);  // 2.959.0 (#4805): Merge PDFs (docpages.js)
}
const ab_selMore = b => menu(b, ab_selMoreItems(), null, null, tr('Selection'));
// a right click (or the "…") on a chosen row / card while several are chosen: what the bar offers, as a menu (the same functions)
function ab_selMenu(anchor) {
  const n = AB.sel.size, docs = ab_selVals().some(x => x.isdoc), later = fn => () => setTimeout(fn, 0);  // a second menu after this one closed
  menu(anchor, [{label: tr('{0} selected', n), cls: 'mhead', dis: true, fn: () => {}}, '-', {label: tr('Move to…'), icon: 'arrow', cls: 'msm-move', fn: later(() => ab_selMove(anchor))},
    {label: tr('Download'), icon: 'download', cls: 'msm-dl', fn: ab_selDl}, docs && typeof dc_bulkMenu === 'function' ? {label: tr('Edit'), icon: 'edit', cls: 'msm-edit', fn: later(() => dc_bulkMenu(anchor))} : null,
    ...ab_selMoreItems(), '-', {label: tr('Move to the trash'), icon: 'trash', cls: 'danger msm-trash', fn: ab_selTrash}].filter(Boolean), null, null, tr('Selection'));
}
const ab_selMany = id => AB.selOn && AB.sel.size > 1 && AB.sel.has(+id);
// documents of the documents' list go into the documents folder there (docs.js dc_smvMove), anything else asks for the place
function ab_selSpace(xs) {
  if (S.route.mod === 'docs' && xs.every(x => x.isdoc) && typeof dc_smvMove === 'function') return dc_smvMove(new Map(xs.map(x => [x.id, x.org_id || null])), trn('{0} document', '{0} documents', xs.length));
  return ab_smvSpace(xs);
}
async function ab_smvPlaces(to) {
  const fs = await ab_moveTargets();  // 2.953 (#3348, review N16)
  return fs.filter(f => (f.org_id || null) === (to || null) && (to || f.owner_id === S.me?.id)).map(f => ({id: f.id, label: f.path}));
}
async function ab_smvDry(b) {  // the dry run: an error of the server is the dialog's block (no toast)
  try { return await rawFetch('POST', '/api/files/move-space', {...b, dry: 1}); } catch (x) { return {block: x.message || tr('The check failed. Please try again.')}; }
}
async function ab_smvSpace(ns) {
  ns = (ns || []).filter(ab_smvOk); if (!ns.length) return;
  const from = ns[0].org_id || null;
  if (ns.some(n => (n.org_id || null) !== from)) { toast(tr('Select items of one workspace')); return; }
  const ids = ns.map(n => n.id), req = (to, p) => ({ids, to: smv_ws(to), parent: p ? +p : null});
  let last = null;
  const r = await smv_open({what: ns.length === 1 ? `“${ns[0].name}”` : trn('{0} item', '{0} items', ns.length), from, places: ab_smvPlaces, total: ids.length,  // 2.147.1 B (#2230): batches + progress
    check: (to, p) => ab_smvDry(req(to, p)), run: (to, p, _o, step) => { last = req(to, p); return smv_post('/api/files/move-space', last, 'ids', step); }});
  if (!r?.moved || !last) return;
  ab_selEnd();
  if (S.route.nid && ids.includes(S.route.nid)) go(r.moved[0].parent_was ? 'ablage/' + r.moved[0].parent_was : 'ablage'); else ab_relist();
  const back = {items: r.moved.map(m => ({id: m.id, parent: m.parent_was, name: m.name_was})), to: smv_ws(r.org_was)}, again = last;
  const post = async (b, key) => { try { await smv_post('/api/files/move-space', b, key); } catch { /* shown */ } ab_relist(); return {}; };
  offerUndo(smv_label(r, ids.length), histAdd({label: tr('Move to another workspace'),
    undo: () => post(back, 'items'), redo: () => post(again, 'ids')}));
}
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-absel]'); if (!b || !b.closest('.abview, .dc-view') || b.dataset.absel === 'one') return;
  const a = b.dataset.absel;
  if (a === 'mode') { const on = !AB.selOn; ab_selEnd(); AB.selOn = on; ab_selDraw(); }
  else if (a === 'off' || a === 'close') { ab_selEnd(); ab_selDraw(); }
  else if (a === 'all') ab_selAll();
  else if (a === 'move') ab_selMove(b);
  else if (a === 'dl') ab_selDl();  // 2.112.1 A (#2058)
  else if (a === 'edit' && typeof dc_bulkMenu === 'function') dc_bulkMenu(b);  // 2.122.0 B (#2294)
  else if (a === 'trash') ab_selTrash();
  else if (a === 'more') ab_selMore(b);
  else if (a === 'restore') abm_restoreSel(ab_selVals());  // 2.589.0 (#4875): the trash's bar
  else if (a === 'purge') abm_purge(ab_selVals());
});
kb_on('view', 'Escape', () => { if (!(AB.selOn && $('#view .abview, #view .dc-view') && !$('.modal, .lightbox') && $('#pop')?.classList.contains('hidden'))) return false; ab_selEnd(); ab_selDraw(); }); // 2.630.0 (#4510): key registry (keys.js), after the open dialogs / menus
// a row's box ticked on hover starts choosing (2.428.0 A, #3581)
document.addEventListener('change', e => {
  const b = e.target.closest?.('[data-absel="one"]'); if (!b) return;
  const id = +b.dataset.id;
  if (!AB.selOn) { AB.selOn = true; AB.sel.clear(); }
  if (b.checked) { const o = ab_selObj(id); if (o) AB.sel.set(id, ab_selInfo(o)); } else AB.sel.delete(id);
  AB.selLast = id; ab_selDraw();
});
// Shift / Ctrl / Cmd on a row's box (2.122.0 B #2295, was tagsel.js); a card's mark, Ctrl- / Cmd- / Shift-click (computer) and a
// tap while choosing on a card (#4612: while choosing runs a tap ticks, like the rows). Before the cards' own click (open)
document.addEventListener('click', e => {
  const t = e.target, box = t.closest?.('#view [data-absel="one"]');
  if (box) {
    if (!(e.shiftKey || e.ctrlKey || e.metaKey)) return;
    e.preventDefault(); e.stopPropagation(); ab_selPick(+box.dataset.id, e.shiftKey);
    setTimeout(() => { for (const x of $$('#view [data-absel="one"]')) x.checked = AB.sel.has(+x.dataset.id); }, 0);  // the cancelled click puts the box back
    return;
  }
  const c = t.closest?.('#view .dc-card, #view .abdl .abdlrow[data-abid]'); if (!c || !c.closest('.dc-view, .abcards')) return;  // 2.769.0 (#5340): + list rows
  const k = t.closest('[data-dcchk]');
  if (k) { e.preventDefault(); e.stopPropagation(); ab_selPick(+k.dataset.dcchk, e.shiftKey); return; }
  if (t.closest('.abcmenu, .abcshw, .abdl-act') || !(AB.selOn || (ms_modClick(e) && !isMobile()))) return;
  const id = ab_cardId(c); if (!id) return;
  e.preventDefault(); e.stopPropagation(); ab_selPick(id, e.shiftKey);
}, true);

// ---- 2.768.0 (#4888): ONE menu of a card (document, file, folder) by a right click, a long press and its "…": "Select" on top
// (#4612, multisel.js cm_selHead), then the file row's items (ab_menuItems; the node from GET /api/files/nodes/<id> when the
// folder did not load it, as ab_ctxNode); while choosing runs a long press ticks the card. Replaces docs.js dc_cardMenu (Open
// and Select only) and abdocs.js abd_lpS (the click on the "…")
const ab_cardId = c => +(c.querySelector('[data-dcchk]')?.dataset.dcchk || c.querySelector('[data-dco]')?.dataset.dco || c.querySelector('[data-ab="open"]')?.dataset.id || 0);
function ab_cardMenu(c, anchor) {
  const id = ab_cardId(c); if (!id) return false;
  if (ab_selMany(id)) { ab_selMenu(anchor || c); return true; }
  const doc = !!c.querySelector('[data-dco]'), fold = !!c.closest('.abview');
  ab_ctxNode(id).then(n => {
    if (!n || !c.isConnected) return;
    const x = doc ? {...n, doc: n.doc || {id}, _spl: '#docs/' + id, _open: () => dc_open(id, fold && typeof abd_navIds === 'function' ? {list: abd_navIds()} : {})} : n;
    ab_menu(anchor || c.querySelector('[data-ab="menu"]') || c, x, () => ab_selPick(id));
  });
  return true;
}
const ab_cardPick = c => { if (!AB.selOn) return false; const id = ab_cardId(c); if (!id) return false; ab_selPick(id); return true; };
const AB_CARDLP = cm_bind('.dc-view .dc-card, .abcards .dc-card, .dc-view .abdl .abdlrow[data-abid]' /* 2.769.0 (#5340): + the list's rows */, c => ab_cardMenu(c), ab_cardPick, lm_keep);

// ---- 2.112.1 A (#2058): the selection into the trash (ONE undo step for all), download (one file as it is, else a ZIP),
// a folder as a ZIP, the phone scan (abscan.js) into the open folder
const abm_trashOk = n => ab_canWrite(n.role) && (n.parent_id || n.role === 'owner');
const abm_dlOk = n => n.kind === 'folder' || (n.kind === 'file' && !upLocked(n));
// 2.768.0 (#4888): the ONE way into the trash - the bar, a row's or card's menu, the document view (docs.js): POST /api/files/trash
// in parts of 500 (all or nothing per part: what may not go is left out first and counted), ONE undo step (POST /api/files/restore).
// o.skip = already left out, o.end = the selection ends (the bar; otherwise only these leave it). -> the ids that went, or null
async function abm_trash(ns, o = {}) {
  const ok = ns.filter(abm_trashOk), skip = (o.skip || 0) + ns.length - ok.length;
  if (!ok.length) { if (skip) toast(ab_skipTxt(skip)); return null; }
  const ids = [], kept = [];
  for (let i = 0; i < ok.length; i += 500) {
    const part = ok.slice(i, i + 500).map(n => n.id);
    let r; try { r = await api('POST', '/api/files/trash', {ids: part}); } catch { break; }
    ids.push(...(r.ids || part)); kept.push(...(r.kept || []));
  }
  if (o.end) ab_selEnd(); else for (const n of ok) AB.sel.delete(n.id);
  const cur = ok.find(n => n.id === S.route.nid && S.route.mod === 'ablage');  // the open folder went: its parent
  if (cur) go(cur.parent_id ? 'ablage/' + cur.parent_id : ab_home(AB.data?.space || ab_nodeSp(cur))); else ab_relist();
  if (!ids.length) return null;
  const post = async url => { for (let i = 0; i < ids.length; i += 500) { try { await api('POST', url, {ids: ids.slice(i, i + 500)}); } catch { /* shown */ } } ab_relist(); return {}; };
  const what = ok.length === 1 ? tr('“{0}” moved to the trash', ok[0].name) : trn('{0} item moved to the trash', '{0} items moved to the trash', ok.length);
  offerUndo([what, fs_keptText(kept), ab_skipTxt(skip)].filter(Boolean).join(' · '), histAdd({label: ok.length === 1 ? tr('Delete “{0}”', ok[0].name) : tr('Move to the trash'),  // 2.199.0 A (#2742): + what stayed
    undo: () => post('/api/files/restore'), redo: () => post('/api/files/trash')}));
  return ids;
}
// ---- 2.589.0 (#4875): the trash: "Empty trash" on top, several rows back or for good (POST /api/files/trash/purge: only what
// the person owns goes, the rest stays and is counted)
const ab_trashTools = d => d?.items?.length ? `<div class="abtools">${ab_selTools(d)}<button type="button" class="btn sm danger" data-ab="trash-empty">${ic('trash', 's')} ${tr('Empty trash')}</button></div>` : '';
function ab_trashBar() {
  const ns = ab_selVals(), all = (AB.data?.items || []).length;
  const h = ms_barHtml('ab-sbar', 'absel', ns.length, tr('Tap files'), [['all', 'all', ns.length && ns.length === all ? tr('Select none') : tr('All')],
    ['restore', 'undo', tr('Restore')], ['purge', 'trash', tr('Delete permanently'), 'danger']]);
  return ns.length && !ns.some(n => n.role === 'owner') ? h.replace(/(data-absel="purge")/, '$1 disabled') : h;
}
// "1 file, 2 folders" of the rows (a folder: with everything in it)
const abm_countText = ns => { const d = ns.filter(n => n.kind === 'folder').length, f = ns.length - d;
  return [f ? trn('{0} file', '{0} files', f) : '', d ? trn('{0} folder', '{0} folders', d) : ''].filter(Boolean).join(', '); };
async function abm_restoreSel(ns) {
  if (!ns.length) return;
  const ids = ns.map(n => n.id);
  let r; try { r = await api('POST', '/api/files/restore', {ids}); } catch { return; }
  ab_selEnd(); ab_reload();
  offerUndo(trn('{0} item restored', '{0} items restored', (r.ids || ids).length), histAdd({label: tr('Restore'),
    undo: () => ab_req('POST', '/api/files/trash', {ids}), redo: () => ab_req('POST', '/api/files/restore', {ids})}));
}
// ns = the chosen rows; null = the whole trash ("Empty trash")
async function abm_purge(ns) {
  const rows = ns || AB.data?.items || [];
  if (!rows.length) return;
  const own = rows.filter(n => n.role === 'owner'), other = rows.length - own.length;
  const what = abm_countText(own);
  const txt = [what ? tr('Deleted permanently: {0}. Folders go with everything in them. This cannot be undone.', what) : '',
    other ? trn('{0} item stays: it belongs to someone else, only they can delete it permanently.', '{0} items stay: they belong to others, only they can delete them permanently.', other) : ''].filter(Boolean).join(' ');
  if (!own.length) { toast(txt); return; }
  if (!await askConfirm(ns ? trn('Delete {0} item permanently?', 'Delete {0} items permanently?', own.length) : tr('Empty the trash permanently?'), txt,
    {ok: ns ? tr('Delete permanently') : tr('Empty trash'), danger: true})) return;
  let r; try { r = await api('POST', '/api/files/trash/purge', ns ? {ids: rows.map(n => n.id)} : {all: true}); } catch { return; }
  ab_selEnd(); ab_reload();
  toast([trn('{0} item deleted permanently', '{0} items deleted permanently', r.deleted || 0),
    r.kept ? trn('{0} stayed, it belongs to someone else', '{0} stayed, they belong to others', r.kept) : '',
    r.locked ? trn('{0} stayed, it is kept by law (retention)', '{0} stayed, they are kept by law (retention)', r.locked) : ''].filter(Boolean).join(' · '), null, r.kept || r.locked ? 6000 : undefined);
}
async function abm_download(ns) {
  ns = ns.filter(abm_dlOk); if (!ns.length) return;
  const a = document.createElement('a');
  if (ns.length === 1 && ns[0].kind === 'file') { a.href = ab_url(ns[0], true); a.download = attDlName(ns[0].name, ns[0].mime); }  // 2.750.0 (#4876)
  else {
    const q = ns.map(n => n.id).join(',');
    try { await api('GET', `/api/files/zip?ids=${q}&check=1`); } catch { return; }  // the limits first: the refusal as a message, not as a file
    a.href = `/api/files/zip?ids=${q}`;
    toast(tr('The ZIP is being prepared…'));
  }
  document.body.appendChild(a); a.click(); a.remove();
}
function ab_scanDoneHtml() {  // 2.558.0 (#4693): the end of a scan above the list, until closed or another folder opens
  const x = AB.scanDone; if (!x) return '';
  if (x.key !== ab_key(S.route)) { AB.scanDone = null; return ''; }
  return `<div class="abscdone" role="status">${ic('check', 's')}<span><b>${esc(tr('“{0}” saved', x.name))}</b>${x.txt ? ' · ' + esc(x.txt) : ''}</span>${x.share ? `<button type="button" class="btn sm" data-ab="share" data-id="${x.id}">${ic('users', 's')} ${tr('Share…')}</button>` : ''}<button type="button" class="iconbtn" data-ab="scandone-x" aria-label="${esc(tr('Close'))}" title="${esc(tr('Close'))}">${ic('x', 's')}</button></div>`;
}
function abm_scan() {
  const parent = S.route.nid || null, space = ab_curSpace(), old = new Set((AB.data?.items || []).map(x => x.id));
  abm_scanOpen({parent, space, done: items => {
    ab_reload();
    const created = items.filter(x => !old.has(x.id));
    if (!created.length) return;
    const ids = created.map(x => x.id);
    // 2.558.0 (#4693): the end says who sees it now (the shares of the folder it went into) and offers Share
    const fold = parent && AB.data?.node?.id === parent ? AB.data.node : null;
    AB.scanDone = {id: created[0].id, name: created[0].name, key: ab_key(S.route), txt: ab_shLineTxt(fold || created[0]), share: !!(fold || created[0]).share_with};  // at the top: its own (none yet)
    offerUndo(tr('“{0}” saved', created[0].name), histAdd({label: tr('Scan'), undo: () => ab_req('POST', '/api/files/trash', {ids}), redo: () => ab_req('POST', '/api/files/restore', {ids})}));
  }});
}
if (typeof sbb_sync === 'function') sbb_sync('ablage');  // 2.501.0 (#4198): loaded later than the panel was drawn (lazyload.js): its panel now
