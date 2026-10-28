/* Kalmido web client: knowledge pages (#1199). Route #wiki (the pages of the current space) and
   #wiki/<id> (one page). A space = an organisation (every member reads and writes) or "Private" (only me); the sidebar's
   workspace switch picks it, else the last one used here. Pages are Markdown with a path as their name ("Processes/
   Shoot day/Checklist": the folders of the tree), [[Path]] links another page (suggestions while typing), #123 a task
   (only tasks I see become links), the backlinks are listed below the page, the frontmatter (a leading --- block) shows
   as small fields, pages under Templates/ are offered by "New page", a ```mindmap block draws its list as a mind map
   (mindmap.js), a ```seiten block lists the space's pages (2.376, #3294). Saving is automatic like notes (a change by someone else in between asks which version stays);
   create, rename, delete and import are one Undo step each. Export / import: a ZIP of .md files (SilverBullet-compatible).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

const WK = {space: null, idx: {}, pg: null, pgErr: '', edit: false, dirty: false, saveT: 0, q: '', ac: null, busy: {}, selOn: false, sel: new Set(), selSp: null, selVis: []};
const wk_spaces = () => ['private', ...(S.me?.workspaces || []).map(w => 'org:' + w.id)];
function wk_cur() {
  const ok = v => !!v && wk_spaces().includes(v);
  if (WK.pg && WK.pg.id === S.route.wid && ok(WK.pg.space)) return WK.pg.space;
  const ws = wsCur?.(); if (ws && ws !== 'all' && ok(ws)) return ws;
  if (S.route.mod === 'wiki' && ok(S.route.wsp)) return S.route.wsp;  // 2.198.0 A (#2743): #wiki/s/<space>
  if (ok(WK.space)) return WK.space;
  const ls = LS.get('wkSpace', ''); if (ok(ls)) return ls;
  return wk_spaces()[1] || 'private';
}
const wk_spaceName = sp => sp === 'private' ? tr('Private|workspace') : (wsOrg(sp.slice(4))?.name || tr('Organisation'));
// 2.198.0 A (#2743): "All workspaces" with more than one space: each space is an entry of its own (the panel's root nodes,
// the phone's list, the overview), the open one is in the address (#wiki/s/<space>[/d/<path>]), a page brings its own
// space; null = no space open (the overview). One space shown above (or only Private) = that space, as before.
const wk_all = () => wk_spaces().length > 1 && (!wsCur?.() || wsCur() === 'all');
// 2.319 (#3287): the open page's space and path -- the loaded page, else its row in a loaded index (a click in the tree
// draws the panel before the page has loaded: the tree stays open down to it)
function wk_pgAt(id) {
  if (!id) return null;
  if (WK.pg && WK.pg.id === id) return {space: WK.pg.space, path: WK.pg.path};
  for (const sp of wk_spaces()) { const p = WK.idx[sp]?.pages?.find(x => x.id === id); if (p) return {space: sp, path: p.path}; }
  return null;
}
function wk_open() {
  if (!wk_all()) return wk_cur();
  const r = S.route, ok = v => !!v && wk_spaces().includes(v); if (r.mod !== 'wiki') return null;
  if (r.wid) { const x = wk_pgAt(r.wid); return x && ok(x.space) ? x.space : null; }
  if (ok(r.wsp)) return r.wsp;
  return r.wdir != null ? wk_cur() : null;  // an older #wiki/d/<path> link: the space used last
}
const wk_home = sp => wk_all() ? 'wiki/s/' + sp : 'wiki';
const wk_spIcon = sp => typeof wsIcon === 'function' ? wsIcon(sp) : ic(sp === 'private' ? 'home' : 'brief', 's');
const wk_locked = sp => typeof wkeLockHtml === 'function' && !!WK.idx[sp]?.pages && !!wkeLockHtml(sp);
function wk_spacesHtml() {  // the entries per space (phone list, computer overview); 2.200.0 A (#2747, audit B 1): named like the file store's spaces
  return `<ul class="wktree wkdlist wkspaces" aria-label="${esc(tr('Workspaces'))}">${wk_spaces().map(s => `<li><a href="#wiki/s/${esc(s)}" class="wkitem wkdrow" data-wksp="${esc(s)}">${wk_locked(s) ? ic('lock', 's') : wk_spIcon(s)}<span>${esc(wk_spaceName(s))}</span>${typeof wkeMark === 'function' ? wkeMark(s) : ''}</a></li>`).join('')}</ul>`;
}
// search under "All": the names in every loaded space (locked ones only after unlocking), each hit with its space's name
function wk_allHits(q) {
  const out = [];
  for (const s of wk_spaces()) { const d = WK.idx[s]; if (!d?.pages || wk_locked(s)) continue; for (const p of d.pages) if (p.path.toLowerCase().includes(q) || d.off && String(p.body || '').toLowerCase().includes(q)) out.push({...p, space: s}); }
  return out;
}
const wk_hitHtml = (p, i) => `<li><a href="#wiki/${p.id}" class="wkitem">${ic('note', 's')}${wk_hitName(p, i)}<small class="muted wkspn">${esc(wk_spaceName(p.space))}</small></a></li>`;
// 2.376 (#3292): a hit's name with the snippet of its text when the text is here already (a space with the lock, offline;
// wkhist.js wks_nameHtml), for the first 30 hits; nothing is loaded for it
const wk_hitName = (p, i) => i < 30 && typeof wks_nameHtml === 'function' ? wks_nameHtml(p, WK.q) : `<span>${esc(p.path)}</span>`;
function wk_allHitsHtml(q, cls = '') {
  const v = wk_allHits(q), wait = wk_spaces().some(s => !WK.idx[s]?.pages && !WK.idx[s]?.err);
  return `<nav id="wk-res" class="${cls}" aria-label="${esc(tr('Pages'))}">${v.length ? `<ul class="wktree">${v.map(wk_hitHtml).join('')}</ul>` : wait ? '' : `<div class="empty">${tr('No page matches.')}</div>`}${wait ? `<div class="muted mhint">${tr('Loading…')}</div>` : ''}${typeof wks_html === 'function' ? wks_html('', WK.q, v.filter(p => p.path.toLowerCase().includes(q))) : ''}</nav>`;
}
const wk_base = p => p.split('/').pop();
const wk_isTpl = p => /^(templates|vorlagen)\//i.test(p);
const wk_e2e = sp => typeof wkeOn === 'function' && wkeOn(sp);  // 2.64.3 B (#1817): the space is encrypted in the browser (wikie2e.js)
// 2.376 (#3292): the index or a page arrived: drawn at once while one types into the search (the field keeps its focus, its
// own input draws the same way); other fields being edited hold the redraw as before (viewSafeRender)
const wk_redraw = () => document.activeElement?.id === 'wk-q' ? renderView() : viewSafeRender();
async function wk_load(sp, force) {
  const d = WK.idx[sp] || (WK.idx[sp] = {});
  if (WK.busy['i' + sp] || (!force && d.pages && d.v === S.v)) return;
  WK.busy['i' + sp] = true;
  try { let j = await wko_sync(sp); if (typeof wkeIndex === 'function') j = await wkeIndex(sp, j); d.pages = j.pages; d.folders = j.folders || []; d.root = j.root || null; d.mayWrite = j.may_write; d.style = j.style || ''; d.may_style = !!j.may_style; d.err = ''; d.off = j._off || ''; d.more = !!j.more; }  // 2.64.3 B (#1817): texts of an encrypted space open here; 2.169.0 (#2671): from the offline copy when offline
  catch (e) { if (e.message === 'auth') return; d.err = e instanceof Offline ? tr('Knowledge pages are only available online.') : e.message; d.pages = d.pages || null; if ([403, 404].includes(e.status) && typeof wkeForget === 'function') wkeForget(sp); }  // 2.64.3 E (#1817): no access any more
  finally { d.v = S.v; WK.busy['i' + sp] = false; }
  if (S.route.mod === 'wiki') wk_redraw();
  if (typeof sbb_sync === 'function') sbb_sync('wiki');  // 2.152.3 B (#2620): the panel's folders
}
async function wk_loadPage(id, force) {
  if (WK.busy['p' + id] || (!force && WK.pg && WK.pg.id === id && (WK.pg._v === S.v || WK.dirty || WK.edit))) return;
  WK.busy['p' + id] = true;
  try {
    let p; try { p = await rawFetch('GET', '/api/wiki/pages/' + id); if (typeof wkePage === 'function') await wkePage(p); }  // 2.64.3 B (#1817)
    catch (e) { if (!(e instanceof Offline) || !(p = await wko_page(id))) throw e; }  // 2.169.0 (#2671): offline = the page from the copy
    p._v = S.v; WK.pgErrFor = null; if (WK.pg?.id !== id) { WK.edit = !!WK.editNext && WK.editNext === id; WK.editNext = null; } WK.pg = p; WK.pgErr = ''; WK.pgLost = null; WK.space = p.space;
  }
  catch (e) { if (e.message === 'auth') return; WK.pgErrFor = id + ':' + S.v; WK.pgLost = e.data?.code === 'wiki_unreadable' ? id : null;  // 2.139.0 C (#2386): the message names the way out, deleting stays possible
    WK.pgErr = e.status === 404 ? tr('This page does not exist or you cannot see it.') : e instanceof Offline ? tr('Knowledge pages are only available online.') : e.message; if (WK.pg?.id === id) WK.pg = null; }
  finally { WK.busy['p' + id] = false; }
  if (S.route.mod === 'wiki') wk_redraw();
  if (typeof sbb_sync === 'function') sbb_sync('wiki');  // 2.319 (#3287): the panel follows the loaded page (its space, its folder)
}
const wk_pages = sp => WK.idx[sp]?.pages || [];
const wk_byPath = (sp, p) => wk_pages(sp).find(x => x.path.toLowerCase() === String(p).trim().toLowerCase());
// ---- the tree from the paths: {name, path, page, kids: Map}; 2.200.0 A (#2747): + the folders of the index (empty ones too):
// fid / fsort / fpar = the folder's node, its place sorted by hand and its parent's node (null: the root); a page's node_id /
// sort_no / folder_id come with the page (wkfolder.py). A page "A" and a folder "A" share the tree node (page + kids).
function wk_tree(pages, folders = []) {
  const root = {name: '', path: '', page: null, kids: new Map()};
  const at = path => {
    let n = root, acc = '';
    for (const part of path.split('/')) {
      acc = acc ? acc + '/' + part : part;
      const k = part.toLowerCase();
      if (!n.kids.has(k)) n.kids.set(k, {name: part, path: acc, page: null, kids: new Map()});
      n = n.kids.get(k);
    }
    return n;
  };
  for (const f of folders) { const n = at(f.path); n.fid = f.id; n.fsort = f.sort_no; n.fpar = f.parent_id; }
  for (const p of pages) at(p.path).page = p;
  return root;
}
const wk_isDir = k => k.kids.size > 0 || !!k.fid;
const wk_sortBy = (a, b, x) => (x(a) ?? 1e9) - (x(b) ?? 1e9) || a.name.localeCompare(b.name, LOCALE());  // by hand first, then by name (like the file store)
// 2.152.5 (#2699): folders opened by hand stay open after a page and Back (phone): kept per device in LS sbbOpen with the
// keys of the computer panel ('wk:<space>:<path>'), closing one by hand wins over "open by itself" until reload (WK_SHUT)
const WK_SHUT = new Set();
function wk_treeHtml(n, cur, many, depth = 0, sp = wk_cur(), kept = new Set(LS.get('sbbOpen', []) || [])) {
  const kids = [...n.kids.values()].sort((a, b) => wk_isDir(b) - wk_isDir(a) || wk_sortBy(a, b, k => wk_isDir(k) ? k.fsort : k.page?.sort_no));  // 2.200.0 A (#2747): empty folders, sorted by hand
  return `<ul class="wktree" role="${depth ? 'group' : 'tree'}">${kids.map(k => {
    const kk = 'wk:' + sp + ':' + k.path.toLowerCase(), on = cur && k.page && k.page.id === cur.id;
    const open = kept.has(kk) || !WK_SHUT.has(kk) && (!many || (cur && cur.path.toLowerCase().startsWith(k.path.toLowerCase() + '/')));
    const name = k.page ? `<a href="#wiki/${k.page.id}" class="wkitem ${on ? 'on' : ''}" ${on ? 'aria-current="page"' : ''} role="treeitem">${ic(wk_isTpl(k.path) ? 'copy' : 'note', 's')}<span>${esc(k.name)}</span>${k.page.shared && typeof wsh_markHtml === 'function' ? wsh_markHtml(1) : ''}</a>`
      : `<span class="wkitem wkdir">${ic('folder', 's')}<span>${esc(k.name)}</span></span>`;
    const more = wk_rowMore(sp, k.fid && !k.page ? k.fid : k.page?.node_id, k.page && !k.fid ? k.page.updated_at : '');  // 2.200.0 A (#2747): the row's "…"
    const box = wk_selBox(sp, wk_isDir(k) ? k.fid : k.page?.node_id, k.name);  // 2.353.0 C (#2829)
    return wk_isDir(k) ? `<li class="wkrow${box ? ' wkselrow' : ''}">${box}<details data-wkk="${esc(kk)}" ${open ? 'open' : ''}><summary><span class="wktog" aria-hidden="true">${ic('chev', 's')}</span>${name}${more}</summary>${wk_treeHtml(k, cur, many, depth + 1, sp, kept)}</details></li>` : `<li class="wkrow${box ? ' wkselrow' : ''}">${box}${name}${more}</li>`;
  }).join('')}</ul>`;
}
document.addEventListener('click', e => {
  const s = e.target.closest?.('.wktree summary'); if (!s || e.target.closest('a, [data-wk]')) return;  // 2.200.0 A (#2747): not the row's "…"
  const d = s.parentElement, k = d.dataset.wkk, x = new Set(LS.get('sbbOpen', []) || []); if (!k) return;
  if (d.open) { x.delete(k); WK_SHUT.add(k); } else { x.add(k); WK_SHUT.delete(k); }  // the click toggles it right after
  LS.set('sbbOpen', [...x].slice(-300));
});
// 2.376 (#3293): a step in the panel (another space, folder or page) or a hit opened ends the search: the field empties and
// the folder shows as usual (Back then finds it without the hits); the same place clicked again draws it at once
document.addEventListener('click', e => {
  if (!WK.q || e.button) return;
  if (!e.target.closest?.('#side [data-go^="wiki"], #wk-res a[href^="#wiki"]')) return;
  WK.q = ''; const f = $('#wk-q'); if (f) f.value = '';
  setTimeout(() => { if (S.route.mod === 'wiki' && !WK.q) renderView(); }, 0);
}, true);
// 2.152.5 (#2699): a phone shows the list or the page: the list's place is kept for Back, a page starts at its top
document.addEventListener('click', e => {
  const a = e.target.closest?.('#wk-res a[href^="#wiki/"]'), v = $('#view'); if (!a || !v || !isMobile()) return;
  WK.listTop = v.scrollTop; WK.pgTop = true;
}, true);
function wk_scrollAfter(id, ready) {
  if (id ? !WK.pgTop : WK.listTop == null || !ready) return;
  const y = id ? 0 : WK.listTop; if (id) WK.pgTop = false; else WK.listTop = null;
  requestAnimationFrame(() => { const v = $('#view'); if (v && S.route.mod === 'wiki') v.scrollTop = y; });
}
// 2.210 A (#2755): more pages than the index carries (WIKI_INDEX_MAX on the server): said, not silently cut
const wk_moreHtml = d => d?.more ? `<div class="muted mhint wkcapped" role="status">${ic('info', 's')}${esc(tr('Only the first {0} pages of this space are shown here.', 5000))}</div>` : '';
// ---- the view
function viewWiki() {
  const all = wk_all(), op = wk_open(), sp = op || wk_cur(), d = WK.idx[sp];
  if (!d || d.v !== S.v) wk_load(sp);
  if (all && op && S.route.wsp === op && WK.space !== op) { WK.space = op; LS.set('wkSpace', op); }  // 2.198.0 A (#2743): the space used last (New page, older links)
  if (all && (!op || WK.q.trim())) for (const s of wk_spaces()) if (!WK.idx[s] || WK.q.trim() && WK.idx[s].v !== S.v) wk_load(s);  // the overview's locks, the search over every space
  const id = S.route.wid;
  if (id && WK.pgErrFor !== id + ':' + S.v && (!WK.pg || WK.pg.id !== id || WK.pg._v !== S.v)) wk_loadPage(id);  // a page that failed: again only with new data
  const cur = id && WK.pg && WK.pg.id === id ? WK.pg : null, mob = isMobile();
  const pages = d?.pages || [], q = WK.q.trim().toLowerCase();
  const vis = q ? pages.filter(p => p.path.toLowerCase().includes(q) || d.off && String(p.body || '').toLowerCase().includes(q)) : pages;  // 2.169.0 (#2671): offline the texts are searched here
  const sel = op && typeof wkeMark === 'function' ? wkeMark(op) : '';  // 2.64.3 (#1817): the lock mark; 2.198.0 A (#2743): the space switch is gone (the panel / the list has an entry per space)
  const wst = typeof wki_statHtml === 'function' ? wki_statHtml() : '';  // 2.350.0 C (#2744): a running import on top (wkimport.js)
  if (typeof sbb_on === 'function' && sbb_on()) { const h = wk_deskHtml(sp, d, id, cur, sel, op); return wst ? h.replace(/^(<div class="ntwrap[^>]*>)/, '$1' + wst) : h; }  // 2.152.3 B (#2620): a computer: the folders are in the panel
  const side = `<div class="ntlist wkside">
    ${all && op ? `<div class="ntbar wkspbar"><a href="#wiki" class="iconbtn" aria-label="${esc(tr('Back'))}">${ic('back')}</a><b>${esc(wk_spaceName(op))}</b>${sel}</div>` : sel ? `<div class="ntbar">${sel}</div>` : ''}
    <div class="ntbar"><div class="ssearch">${ic('search', 's')}<input id="wk-q" type="search" value="${esc(WK.q)}" placeholder="${esc(tr('Find a page'))}" aria-label="${esc(tr('Find a page'))}" autocomplete="off"></div>
      <button type="button" class="btn sm pri" data-wk="new">${ic('plus', 's')}${tr('New page')}</button>${wk_canFolder(sp) && (!all || op) ? wk_folderBtn() + wk_selBtn(sp, !q && vis.length) : ''}</div>
    ${op && d?.off ? wko_offHtml(d.off, d.more) : op ? wk_moreHtml(d) : ''}${op && typeof wkeBarHtml === 'function' ? wkeBarHtml(sp) : ''}${all && q ? wk_allHitsHtml(q) : all && !op ? `<nav id="wk-res" aria-label="${esc(tr('Pages'))}">${wk_spacesHtml()}</nav>` : `<nav id="wk-res" aria-label="${esc(tr('Pages'))}">${typeof wkeLockHtml === 'function' && d?.pages && wkeLockHtml(sp) ? wkeLockHtml(sp) : !d?.pages ? `<div class="muted mhint">${d?.err ? esc(d.err) : tr('Loading…')}</div>`
      : vis.length ? (q ? `<ul class="wktree">${vis.map((p, i) => `<li><a href="#wiki/${p.id}" class="wkitem">${ic('note', 's')}${wk_hitName(p, i)}</a></li>`).join('')}</ul>` : wk_treeHtml(wk_treeOf(sp), cur, vis.length > 30))  // 2.200.0 A (#2747): with the folders
      : q ? `<div class="empty">${tr('No page matches.')}</div>` : symEmpty('book', tr('No pages yet.'), (sp === 'private' ? tr('Processes, checklists, how-tos: write down what you need to know.') : tr('Processes, checklists, how-tos: write down what the team needs to know.')))}${q && d?.pages && !d.off && typeof wks_html === 'function' ? wks_html(sp, WK.q, vis) : ''}</nav>${wk_selBar(sp)}`}${typeof wsh_sideHtml === 'function' ? wsh_sideHtml() : ''}</div>`;  // 2.123.0 A (#2106): + found in the text (wkhist.js)
  const main = id ? `<article class="ntedit wkpage${typeof wkst_cls === 'function' ? wkst_cls(cur?.space || sp) : ''}" aria-label="${esc(cur ? wk_base(cur.path) : tr('Page'))}">${cur ? (cur._wke && typeof wkeLockHtml === 'function' ? wkeLockHtml(cur.space, true) : wk_pageHtml(cur)) : (WK.pgErr && WK.pgLost === id ? wk_lostHtml() : `<div class="muted mhint">${WK.pgErr ? esc(WK.pgErr) : tr('Loading…')}</div>`)}</article>` : '';
  if (mob) wk_scrollAfter(id, !!d?.pages);
  return `<div class="ntwrap wkwrap">${wst}<div class="ntview ${id ? 'open' : ''}">${mob && id ? '' : side}${main}</div></div>`;
}
// 2.152.3 B (#2620): knowledge on a computer with sidebar B: the panel holds the folders (wk_panelHtml), the page shows a bar
// (space, search, "New page", the space's menu) and below it the open page or the open folder as a list like a file manager
// (#wiki/d/<path>: its path on top, its subfolders, then its pages); search hits replace the list. The tree column is gone.
const wk_dirOf = path => path.split('/').slice(0, -1).join('/');
const wk_dirGo = (path, sp) => (wk_all() ? 'wiki/s/' + (sp || wk_cur()) + '/' : 'wiki/') + 'd/' + encodeURIComponent(path);  // 2.198.0 A (#2743): + the space under "All"
function wk_treeOf(sp) {  // the tree of a space, built once per loaded index (thousands of pages stay quick)
  const ps = wk_pages(sp); WK.tc = WK.tc || new WeakMap();
  if (!WK.tc.has(ps)) WK.tc.set(ps, wk_tree(ps, WK.idx[sp]?.folders || []));
  return WK.tc.get(ps);
}
function wk_node(root, path) {
  let n = root;
  for (const part of String(path || '').split('/').filter(Boolean)) { n = n.kids.get(part.toLowerCase()); if (!n) return null; }
  return n;
}
const wk_dirs = n => [...n.kids.values()].filter(wk_isDir).sort((a, b) => wk_sortBy(a, b, k => k.fsort));  // 2.200.0 A (#2747): + empty folders, sorted by hand
const wk_leaves = n => [...n.kids.values()].filter(k => k.page).sort((a, b) => wk_sortBy(a, b, k => k.page.sort_no));
// ---- 2.200.0 A (#2747): the folders are folders of the file store (wkfolder.py): the panel's tree shows folders AND pages,
// dragged (moved / sorted) and with a menu (sbb_treeReg 'wk'); the lists get the row's date and "…"; "New folder" in the bar.
// Moving / renaming / the trash go through the file store's routes, the server writes the pages' paths (and their links).
// A space with the lock keeps its tree from the names (no nodes): nothing to drag, no folder button.
// 2.200.0 A (#2747, audit B 1): the top of the tree has ONE name in the panel and in the path, by the file store's bar: one
// workspace = the area's name ("Knowledge", like "Files"), several = the space's name (like the file store's spaces)
const wk_rootName = sp => wk_all() ? wk_spaceName(sp) : tr('Knowledge|area');
const wk_canFolder = sp => { const d = WK.idx[sp]; return !!d?.pages && d.mayWrite !== false && !wk_e2e(sp) && !S.me?.kid; };
const wk_folderBtn = () => `<button type="button" class="btn sm" data-wk="newfolder">${ic('folder', 's')}${tr('New folder')}</button>`;
const wk_kidsN = n => wk_dirs(n).length + wk_leaves(n).length;
function wk_rowMore(sp, nid, when) {
  const w = when ? `<small class="muted wkwhen">${esc(fmtDay('short', new Date(when)))}</small>` : '';
  return w + (nid && wk_canFolder(sp) ? `<button type="button" class="iconbtn sm wkmore" data-wk="rmenu" data-nid="${nid}" data-wsp="${esc(sp)}" aria-haspopup="menu" aria-label="${esc(tr('More'))}" title="${esc(tr('More'))}">${ic('dots', 's')}</button>` : '');
}
function wk_dnd(sp, k, page) {  // the sbb_treeHtml marks of a folder / a page that has its node
  const d = WK.idx[sp]; if (!wk_canFolder(sp) || !d?.root) return {};
  if (page) return page.node_id ? {ns: 'wk', id: page.node_id, par: 'n:' + (page.folder_id || d.root), drag: true, menu: true} : {};
  return k.fid ? {ns: 'wk', id: k.fid, par: 'n:' + (k.fpar || d.root), drag: true, drop: true, menu: true} : {};
}
function wk_subNodes(sp, n, node) {
  const id = S.route.mod === 'wiki' ? S.route.wid : null;
  return [...wk_dirs(n).map(node), ...wk_leaves(n).map(k => ({k: 'wk:' + sp + ':#' + k.page.id, name: k.name, go: 'wiki/' + k.page.id, icon: wk_isTpl(k.path) ? 'copy' : 'note',
    on: id === k.page.id, kids: false, ...wk_dnd(sp, k, k.page)}))];
}
function wk_nodeInfo(nid) {  // a node of a loaded space: {sp, folder | page}
  for (const sp of Object.keys(WK.idx)) {
    const d = WK.idx[sp]; if (!d?.pages) continue;
    const f = (d.folders || []).find(x => x.id === nid); if (f) return {sp, folder: f, parent: f.parent_id || d.root};
    const p = d.pages.find(x => x.node_id === nid); if (p) return {sp, page: p, parent: p.folder_id || d.root};
  }
  return null;
}
async function wk_nodeMove(nid, b) {  // b = {parent_id?, before?, after?} -> the file store's order route; the paths follow on the server
  const x = wk_nodeInfo(nid); if (!x) return;
  await wk_flush();
  try { await rawFetch('POST', `/api/files/nodes/${nid}/order`, b); } catch (e) { toast(e.message); return; }
  wk_after(x.sp);
  if ('parent_id' in b) {
    const back = x.parent;
    histToast(tr('Moved'), histAdd({label: tr('Moved'), ids: [], snaps: [], lids: [], wsp: x.sp,
      undo: async () => { await rawFetch('POST', `/api/files/nodes/${nid}/order`, {parent_id: back}); wk_after(x.sp); return {skipped: []}; },
      redo: async () => { await rawFetch('POST', `/api/files/nodes/${nid}/order`, {parent_id: b.parent_id}); wk_after(x.sp); return {skipped: []}; }}));
  }
}
async function wk_newFolder(sp, parent) {
  const d = WK.idx[sp]; if (!wk_canFolder(sp)) return;
  if (parent == null && S.route.mod === 'wiki' && S.route.wdir) parent = wk_node(wk_treeOf(sp), S.route.wdir)?.fid || null;  // the open folder
  const name = await askPrompt(tr('New folder'), '', {ok: tr('Create'), input: {placeholder: tr('Name'), max: 150}});
  if (!name || !name.trim()) return;
  let r; try { r = await rawFetch('POST', '/api/wiki/folders', {space: sp, name: name.trim(), ...(parent && parent !== d.root ? {parent_id: parent} : {})}); } catch (e) { toast(e.message); return; }
  wk_after(sp);
  const f = r.folder;
  histToast(tr('Folder “{0}” created', f.name), histAdd({label: tr('New folder “{0}”', f.name), ids: [], snaps: [], lids: [], wsp: sp,
    undo: async () => { await rawFetch('DELETE', `/api/files/nodes/${f.id}`); wk_after(sp); return {skipped: []}; },
    redo: async () => { await rawFetch('POST', `/api/files/nodes/${f.id}/restore`); wk_after(sp); return {skipped: []}; }}));
}
async function wk_fRename(sp, f) {
  const name = await askPrompt(tr('Rename folder'), f.name, {ok: tr('Rename'), input: {max: 150}});
  if (!name || !name.trim() || name.trim() === f.name) return;
  await wk_flush();
  const up = f.path.includes('/') ? f.path.slice(0, f.path.lastIndexOf('/') + 1) : '';
  const follow = (a, b) => {  // 2.210 B (#2757) on the 2.200 menu: the open folder (or one below it) follows its new name
    const dir = S.route.mod === 'wiki' && S.route.wdir, l = (up + a).toLowerCase(); if (!dir || wk_open() !== sp) return;
    if (dir.toLowerCase() === l || dir.toLowerCase().startsWith(l + '/')) go(wk_dirGo(up + b + dir.slice(l.length), sp));
  };
  const ren = async (nm, was) => { const r = await rawFetch('PATCH', `/api/files/nodes/${f.id}`, {name: nm}); follow(was, r?.name || nm); wk_after(sp); };
  try { await ren(name.trim(), f.name); } catch (e) { toast(e.message); return; }
  histToast(tr('Renamed'), histAdd({label: tr('Renamed {0}', qn(f.name)), ids: [], snaps: [], lids: [], wsp: sp,
    undo: async () => { await ren(f.name, name.trim()); return {skipped: []}; }, redo: async () => { await ren(name.trim(), f.name); return {skipped: []}; }}));
}
async function wk_fTrash(sp, f) {
  await wk_flush();
  try { await rawFetch('DELETE', `/api/files/nodes/${f.id}`); } catch (e) { toast(e.message); return; }
  if (S.route.mod === 'wiki' && S.route.wdir && (S.route.wdir + '/').toLowerCase().startsWith(f.path.toLowerCase() + '/')) go(wk_home(sp));
  wk_after(sp);
  histToast(tr('“{0}” moved to the trash', f.name), histAdd({label: tr('Delete “{0}”', f.name), ids: [], snaps: [], lids: [], wsp: sp,
    undo: async () => { await rawFetch('POST', `/api/files/nodes/${f.id}/restore`); wk_after(sp); return {skipped: []}; },
    redo: async () => { await rawFetch('DELETE', `/api/files/nodes/${f.id}`); wk_after(sp); return {skipped: []}; }}));
}
function wk_moveTo(nid, anchor) {  // "Move to …": the folders of the space (not into itself), the top
  const x = wk_nodeInfo(nid); if (!x) return;
  const d = WK.idx[x.sp], own = x.folder ? x.folder.path.toLowerCase() + '/' : null;
  const fs = (d.folders || []).filter(f => f.id !== x.parent && f.id !== nid && !(own && (f.path.toLowerCase() + '/').startsWith(own)))
    .sort((a, b) => a.path.localeCompare(b.path, LOCALE()));
  const items = [...(x.parent !== d.root ? [{label: tr('Top level'), icon: 'up', fn: () => wk_nodeMove(nid, {parent_id: d.root})}] : []),
    ...fs.map(f => ({label: f.path, icon: 'folder', fn: () => wk_nodeMove(nid, {parent_id: f.id})}))];
  if (!items.length) { toast(tr('No other folder in this space')); return; }
  menu(anchor || document.body, [{head: tr('Move to …')}, ...items.slice(0, 80)], null, null, tr('Move to …'));
}
// ---- 2.353.0 C (#2829, audit B 2): "Select" next to "New folder": several folders / pages (their nodes) moved or put into the
// trash at once -- the file store's selection bar (ablage.js ab_smvBar: same look and texts), ONE undo step per action. Only
// where the folders' menu works today (wk_canFolder: not in a space with the lock, not read-only, not for agents).
const wk_selOk = sp => WK.selOn && WK.selSp === sp && wk_canFolder(sp);
function wk_selBtn(sp, any) {
  if (WK.selOn && WK.selSp !== sp) wk_selEnd();
  WK.selVis = [];
  return any ? `<button type="button" class="btn sm ${WK.selOn ? 'on' : ''}" data-wksel="mode" data-wsp="${esc(sp)}" aria-pressed="${!!WK.selOn}">${ic('check', 's')} ${tr('Select')}</button>` : '';
}
function wk_selBox(sp, nid, name) {
  if (!nid || !wk_selOk(sp)) return '';
  WK.selVis.push(nid);
  return `<label class="absel" title="${esc(tr('Select {0}', name))}"><input type="checkbox" data-wksel="one" data-id="${nid}" ${WK.sel.has(nid) ? 'checked' : ''} aria-label="${esc(tr('Select {0}', name))}"></label>`;
}
function wk_selBar(sp) {
  if (!wk_selOk(sp)) return '';
  const ns = [...WK.sel].filter(x => WK.selVis.includes(x)), n = ns.length, all = n > 0 && n === new Set(WK.selVis).size;
  return `<div class="abselbar wkselbar" role="toolbar" aria-label="${esc(tr('Selection'))}"><span class="absn" aria-live="polite">${esc(tr('{0} selected', n))}</span>
    <button type="button" class="linkbtn" data-wksel="all">${all ? tr('Select none') : tr('Select all')}</button><span class="spacer"></span>
    <button type="button" class="btn sm" data-wksel="trash" ${n ? '' : 'disabled'} aria-label="${esc(tr('Move to the trash'))}" title="${esc(tr('Move to the trash'))}">${ic('trash', 's')} <span class="abselt">${tr('Move to the trash')}</span></button>
    <button type="button" class="btn sm" data-wksel="move" ${n ? '' : 'disabled'} aria-label="${esc(tr('Move to…'))}" title="${esc(tr('Move to…'))}">${ic('arrow', 's')} <span class="abselt">${tr('Move to…')}</span></button>
    <button type="button" class="iconbtn" data-wksel="off" aria-label="${esc(tr('Cancel'))}" title="${esc(tr('Cancel'))}">${ic('x')}</button></div>`;
}
function wk_selEnd() { WK.sel.clear(); WK.selOn = false; WK.selSp = null; }
function wk_selNodes() {  // the chosen nodes of the open space, without one that lies in a chosen folder (it goes with that one)
  const xs = [...WK.sel].map(id => ({id, ...wk_nodeInfo(id)})).filter(x => x.sp === WK.selSp);
  const dirs = xs.filter(x => x.folder).map(x => x.folder.path.toLowerCase() + '/');
  return xs.filter(x => !dirs.some(p => (x.folder ? x.folder.path : x.page.path).toLowerCase().startsWith(p)));
}
function wk_selMove(anchor) {
  const xs = wk_selNodes(); if (!xs.length) return;
  const sp = WK.selSp, d = WK.idx[sp], own = xs.filter(x => x.folder).map(x => x.folder.path.toLowerCase() + '/');
  const fs = (d.folders || []).filter(f => !own.some(p => (f.path.toLowerCase() + '/').startsWith(p))).sort((a, b) => a.path.localeCompare(b.path, LOCALE()));
  const go2 = async to => {
    await wk_flush();
    const done = [], mv = (id, par) => rawFetch('POST', `/api/files/nodes/${id}/order`, {parent_id: par});
    for (const x of xs) {
      if (x.parent === to) continue;
      try { await mv(x.id, to); done.push(x); } catch (e) { toast(e.message); break; }
    }
    wk_selEnd(); wk_after(sp);
    if (!done.length) return;
    const all = async back => { for (const x of done) await mv(x.id, back ? x.parent : to); wk_after(sp); return {skipped: []}; };
    histToast(trn('{0} item moved', '{0} items moved', done.length), histAdd({label: tr('Move to…'), ids: [], snaps: [], lids: [], wsp: sp,
      undo: () => all(true), redo: () => all(false)}));
  };
  menu(anchor || document.body, [{head: tr('Move to …')}, {label: tr('Top level'), icon: 'up', fn: () => go2(d.root)},
    ...fs.slice(0, 80).map(f => ({label: f.path, icon: 'folder', fn: () => go2(f.id)}))], null, null, tr('Move to …'));
}
async function wk_selTrash() {  // pages through the knowledge trash (wk_delete's routes), folders through the file store's (their pages follow)
  const xs = wk_selNodes(), sp = WK.selSp; if (!xs.length) return;
  const pids = xs.filter(x => x.page).map(x => x.page.id), fids = xs.filter(x => x.folder).map(x => x.id);
  await wk_flush();
  let kept = [];
  try {
    if (pids.length) await rawFetch('POST', '/api/wiki/trash', {ids: pids});
    if (fids.length) kept = (await rawFetch('POST', '/api/files/trash', {ids: fids})).kept || [];
  } catch (e) { toast(e.message); wk_selEnd(); wk_after(sp); return; }
  if (S.route.wid && pids.includes(S.route.wid)) go(wk_home(sp));
  wk_selEnd(); wk_after(sp);
  const step = async back => {
    if (back) { if (fids.length) await rawFetch('POST', '/api/files/restore', {ids: fids}); if (pids.length) await rawFetch('POST', '/api/wiki/restore', {ids: pids}); }
    else { if (pids.length) await rawFetch('POST', '/api/wiki/trash', {ids: pids}); if (fids.length) await rawFetch('POST', '/api/files/trash', {ids: fids}); }
    wk_after(sp); return {skipped: []};
  };
  histToast([trn('{0} item moved to the trash', '{0} items moved to the trash', xs.length), typeof fs_keptText === 'function' ? fs_keptText(kept) : ''].filter(Boolean).join(' · '),
    histAdd({label: tr('Move to the trash'), ids: [], snaps: [], lids: [], wsp: sp, undo: () => step(true), redo: () => step(false)}));
}
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-wksel]'); if (!b || b.dataset.wksel === 'one' || !$('#view')?.contains(b)) return;
  const a = b.dataset.wksel;
  if (a === 'mode') { const on = !WK.selOn; wk_selEnd(); if (on) { WK.selOn = true; WK.selSp = b.dataset.wsp; } renderView(); }
  else if (a === 'off') { wk_selEnd(); renderView(); }
  else if (a === 'all') { const vis = new Set(WK.selVis), all = vis.size && [...vis].every(x => WK.sel.has(x)); WK.sel = new Set(all ? [] : vis); renderView(); }
  else if (a === 'move') wk_selMove(b);
  else if (a === 'trash') wk_selTrash();
});
document.addEventListener('change', e => {
  const b = e.target.closest?.('[data-wksel="one"]'); if (!b) return;
  const id = +b.dataset.id; if (b.checked) WK.sel.add(id); else WK.sel.delete(id);
  renderView();
});
function wk_nodeItems(nid, anchor) {  // the menu of a folder / a page (the row's "…", the tree's right-click / long press)
  const x = wk_nodeInfo(nid); if (!x) return [];
  // 2.200.0 F (#2747, review 11): Share… (the one dialog, wkshare.js; an encrypted space gets its hint there)
  const share = t => typeof wkfs_share === 'function' && WK.idx[x.sp]?.mayWrite !== false && !S.me?.kid ? [{label: tr('Share…|wiki'), icon: 'users', fn: () => wkfs_share(nid, t)}] : [];
  if (x.folder) {
    const f = x.folder;
    return [{label: tr('New page'), icon: 'plus', fn: () => wk_new('', f.path + '/', x.sp)}, {label: tr('New folder…'), icon: 'folder', fn: () => wk_newFolder(x.sp, f.id)},
      {label: tr('Rename…'), icon: 'edit', fn: () => wk_fRename(x.sp, f)}, {label: tr('Move to…'), icon: 'arrow', fn: () => wk_moveTo(nid, anchor)},
      ...share({space: x.sp, path: f.path, folder: true}), '-', {label: tr('Move to the trash'), icon: 'trash', cls: 'flag-5', fn: () => wk_fTrash(x.sp, f)}];
  }
  const p = {...x.page, space: x.sp};
  return [{label: tr('Open'), icon: 'note', fn: () => go('wiki/' + p.id)}, {label: tr('Rename…'), icon: 'edit', fn: () => wk_rename(p)},
    {label: tr('Move to…'), icon: 'arrow', fn: () => wk_moveTo(nid, anchor)}, ...share({space: x.sp, path: p.path, page_id: p.id}),
    '-', {label: tr('Move to the trash'), icon: 'trash', cls: 'flag-5', fn: () => wk_delete(p)}];
}
sbb_treeReg('wk', {
  move: (id, into) => wk_nodeMove(+id, {parent_id: +into}),
  order: (id, pos) => {
    const x = wk_nodeInfo(+id); if (!x) return;
    const b = pos.before ? {before: +pos.before} : pos.after ? {after: +pos.after} : {};
    if (pos.into !== undefined && String(pos.into).startsWith('n:') && +String(pos.into).slice(2) !== x.parent) b.parent_id = +String(pos.into).slice(2);
    return wk_nodeMove(+id, b);
  },
  menu: id => wk_nodeItems(+id)});
function wk_deskHtml(sp, d, id, cur, sel, op) {
  const q = WK.q.trim().toLowerCase(), pages = d?.pages || [], all = wk_all();
  if (all && !op) d = null;  // 2.198.0 A (#2743): no space open: no space's menu, offline mark or lock bar
  const bar = `<div class="wkbar">${sel}<div class="ssearch">${ic('search', 's')}<input id="wk-q" type="search" value="${esc(WK.q)}" placeholder="${esc(tr('Find a page'))}" aria-label="${esc(tr('Find a page'))}" autocomplete="off"></div>
    <button type="button" class="btn sm pri" data-wk="new">${ic('plus', 's')}${tr('New page')}</button>${wk_canFolder(sp) && (!all || op) ? wk_folderBtn() + wk_selBtn(sp, !q && !id && !!pages.length) : ''}
    ${S.me?.kid || !op ? '' : `<button type="button" class="iconbtn" data-wk="amenu" aria-haspopup="menu" title="${esc(tr('Space'))}" aria-label="${esc(tr('Space'))}">${ic('dots')}</button>`}</div>${d?.off ? wko_offHtml(d.off, d.more) : wk_moreHtml(d)}${d && typeof wkeBarHtml === 'function' ? wkeBarHtml(sp) : ''}`;  // 2.169 (#2671): the offline mark; 2.210 A (#2755): the cap online
  const hits = all && q ? wk_allHitsHtml(q, 'wkdlist') : q && d?.pages ? `<nav id="wk-res" class="wkdlist" aria-label="${esc(tr('Pages'))}">${(v => v.length ? `<ul class="wktree">${v.map((p, i) => `<li><a href="#wiki/${p.id}" class="wkitem">${ic('note', 's')}${wk_hitName(p, i)}</a></li>`).join('')}</ul>` : `<div class="empty">${tr('No page matches.')}</div>`)(pages.filter(p => p.path.toLowerCase().includes(q) || d.off && String(p.body || '').toLowerCase().includes(q)))}${!d.off && typeof wks_html === 'function' ? wks_html(sp, WK.q, pages.filter(p => p.path.toLowerCase().includes(q))) : ''}</nav>` : '';  // 2.169 (#2671): offline the texts are searched here
  if (id && !hits) return `<div class="ntwrap wkwrap wkdesk">${bar}<article class="ntedit wkpage${typeof wkst_cls === 'function' ? wkst_cls(cur?.space || sp) : ''}" aria-label="${esc(cur ? wk_base(cur.path) : tr('Page'))}">${cur ? (cur._wke && typeof wkeLockHtml === 'function' ? wkeLockHtml(cur.space, true) : wk_pageHtml(cur)) : (WK.pgErr && WK.pgLost === id ? wk_lostHtml() : `<div class="muted mhint">${WK.pgErr ? esc(WK.pgErr) : tr('Loading…')}</div>`)}</article></div>`;
  if (all && !op && !hits) return `<div class="ntwrap wkwrap wkdesk">${bar}<section class="wkfolder" aria-label="${esc(tr('Workspaces'))}"><div class="nthead"><div class="wktitle"><h2>${esc(tr('All workspaces'))}</h2></div></div><nav id="wk-res" aria-label="${esc(tr('Pages'))}">${wk_spacesHtml()}</nav>${typeof wsh_sideHtml === 'function' ? wsh_sideHtml() : ''}</section></div>`;  // 2.200.0 B (#2747): + Shared with me (a guest's start)
  const dir = S.route.wdir || '', parts = dir.split('/').filter(Boolean), n = d?.pages ? wk_node(wk_treeOf(sp), dir) : null;
  const crumbs = `<nav class="wkcrumbs" aria-label="${esc(tr('Path'))}">${parts.length ? `<a href="#${esc(wk_home(sp))}">${esc(wk_rootName(sp))}</a>` : ''}${parts.slice(0, -1).map((x, i) => `<span aria-hidden="true">/</span><a href="#${esc(wk_dirGo(parts.slice(0, i + 1).join('/'), sp))}">${esc(x)}</a>`).join('')}</nav>`;
  const head = `<div class="nthead"><div class="wktitle">${crumbs}<h2>${esc(parts.length ? (n?.name || parts[parts.length - 1]) : wk_rootName(sp))}</h2></div>${n?.fid && parts.length ? wk_rowMore(sp, n.fid, '') : ''}</div>`;  // 2.210 B (#2757): the open folder's "…" (2.200 menu)
  let body;
  if (hits) body = hits;
  else if (typeof wkeLockHtml === 'function' && d?.pages && wkeLockHtml(sp)) body = wkeLockHtml(sp);
  else if (!d?.pages) body = `<div class="muted mhint">${d?.err ? esc(d.err) : tr('Loading…')}</div>`;
  else if (!pages.length) body = symEmpty('book', tr('No pages yet.'), sp === 'private' ? tr('Processes, checklists, how-tos: write down what you need to know.') : tr('Processes, checklists, how-tos: write down what the team needs to know.'));
  else if (!n) body = `<div class="empty">${tr('This folder is empty')}</div>`;  // 2.200.0 A (#2747): an empty folder has its node (wk_tree)
  else {
    const ps = wk_leaves(n);  // 2.200.0 A (#2747): rows like the file store's -- sorted by hand, the date, the menu "…"
    const box = (nid, nm) => wk_selBox(sp, nid, nm), rc = WK.selOn ? 'wkrow wkselrow' : 'wkrow';  // 2.353.0 C (#2829): Select
    const rows = wk_dirs(n).map(k => `<li class="${rc}">${box(k.fid, k.name)}<a href="#${esc(wk_dirGo(k.path, sp))}" class="wkitem wkdrow">${ic('folder', 's')}<span>${esc(k.name)}</span></a>${wk_rowMore(sp, k.fid, '')}</li>`).join('')
      + ps.map(k => `<li class="${rc}">${box(k.page.node_id, k.name)}<a href="#wiki/${k.page.id}" class="wkitem">${ic(wk_isTpl(k.path) ? 'copy' : 'note', 's')}<span>${esc(k.name)}</span>${k.page.shared && typeof wsh_markHtml === 'function' ? wsh_markHtml(1) : ''}</a>${wk_rowMore(sp, k.page.node_id, k.page.updated_at)}</li>`).join('');
    body = rows ? `<ul class="wktree wkdlist" aria-label="${esc(tr('Pages'))}">${rows}</ul>` : `<div class="empty">${tr('This folder is empty')}</div>`;
  }
  if (!hits) body = `<nav id="wk-res" aria-label="${esc(tr('Pages'))}">${body}</nav>${wk_selBar(sp)}`;
  return `<div class="ntwrap wkwrap wkdesk">${bar}<section class="wkfolder" aria-label="${esc(tr('Folder'))}">${hits ? '' : head}${body}${!parts.length && !hits && typeof wsh_sideHtml === 'function' ? wsh_sideHtml() : ''}</section></div>`;
}
// the panel: "All pages" (the top of the space), then the top folders; subfolders are drawn only when opened (sbb_treeHtml)
function wk_panelHtml() {
  if (wk_all()) return wk_panelAllHtml();  // 2.198.0 A (#2743)
  const sp = wk_cur(), d = WK.idx[sp]; if (!d || d.v === -1) wk_load(sp);  // 2.152.3: only a missing or marked index (wk_after), the bodies are big - no fetch per render
  const r = S.route, onW = r.mod === 'wiki';
  const pa = onW && r.wid ? wk_pgAt(r.wid) : null;
  const at = (onW && r.wdir != null ? r.wdir : pa && pa.space === sp ? wk_dirOf(pa.path) : '').toLowerCase();  // the open folder (a page: its folder)
  const node = n => { const lp = n.path.toLowerCase(); return {k: 'wk:' + sp + ':' + lp, name: n.name, go: wk_dirGo(n.path), on: !!at && at === lp, kids: wk_kidsN(n) > 0, open: at.startsWith(lp + '/') || !!pa && at === lp, sub: () => wk_subNodes(sp, n, node), ...wk_dnd(sp, n)}; };  // 2.319 (#3287): a page's own folder is open
  const top = `<div class="sgroup sbbp">${sbb_row('wiki', 'book', wk_rootName(sp), onW && !r.wid && !r.wdir)}</div>`;  // 2.200.0 A (#2747, audit B 1)
  if (!d?.pages) return top + `<p class="muted sbbtl">${esc(d?.err || tr('Loading…'))}</p>`;
  const ds = wk_subNodes(sp, wk_treeOf(sp), node);  // 2.200.0 A (#2747): folders AND pages, dragged / sorted / with a menu
  return top + (ds.length ? `<div class="sgroup sbbp sbbtree" role="group" aria-label="${esc(tr('Folders'))}">${sbb_treeHtml(ds)}</div>` : '');
}
// 2.198.0 A (#2743): under "All workspaces" each space is a root node "All pages <space>" of the shared tree (sbb_treeHtml,
// key 'wk:<space>:', below it 'wk:<space>:<path>' as before): its name opens the space's list, its arrow its folders (the index
// loads then: "Loading…"); a locked space has the lock and no folders until it is unlocked on its page
function wk_panelAllHtml() {
  const r = S.route, onW = r.mod === 'wiki', op = onW ? wk_open() : null;
  return `<div class="sgroup sbbp sbbtree" role="group" aria-label="${esc(tr('Workspaces'))}">${wk_spaces().map(sp => {
    const d = WK.idx[sp], lock = wk_locked(sp), here = op === sp;
    const pa = here && r.wid ? wk_pgAt(r.wid) : null;  // 2.319 (#3287)
    const at = here ? (r.wdir != null ? r.wdir : pa ? wk_dirOf(pa.path) : '').toLowerCase() : '';
    const node = n => { const lp = n.path.toLowerCase(); return {k: 'wk:' + sp + ':' + lp, name: n.name, go: wk_dirGo(n.path, sp), on: !!at && at === lp, kids: wk_kidsN(n) > 0, open: at.startsWith(lp + '/') || !!pa && at === lp, sub: () => wk_subNodes(sp, n, node), ...wk_dnd(sp, n)}; };
    const root = {k: 'wk:' + sp + ':', name: wk_rootName(sp), icon: lock ? 'lock' : 'book', go: 'wiki/s/' + sp, on: here && !r.wid && !r.wdir,
      kids: !lock && !(d?.pages && !wk_kidsN(wk_treeOf(sp))), open: here, attrs: `data-wksp="${esc(sp)}"`,  // the open space shows its folders
      ...(d?.root && !wk_e2e(sp) && d.mayWrite !== false ? {ns: 'wk', id: d.root, par: 'wk:', drop: true} : {}),  // 2.200.0 A (#2747): dropped on = to the top
      sub: () => { if (!d || d.v === -1) wk_load(sp); return d?.pages ? wk_subNodes(sp, wk_treeOf(sp), node) : d?.err ? [] : null; }};
    const h = sbb_treeHtml([root]), mark = ic('book');  // 2.406.0 A (#3492): the tree draws full-size symbols
    return lock ? h : h.replace(mark, () => wk_spIcon(sp));  // the space's own symbol (the shared tree takes icon names only)
  }).join('')}</div>`;
}
// 2.139.0 C (#2386): a page whose text cannot be read -- the message with its way out, and deleting (save, rename, move are refused)
function wk_lostHtml() {
  const may = WK.idx[wk_cur()]?.mayWrite !== false;
  return `<div class="wklost" role="alert">${ic('lock')}<p>${esc(WK.pgErr)}</p>${may ? `<button type="button" class="btn sm" data-wk="lostdel">${ic('trash', 's')}${tr('Delete page')}</button>` : ''}</div>`;
}
function wk_crumbs(p) {
  const parts = p.path.split('/'), sp = p.space;
  return `<nav class="wkcrumbs" aria-label="${esc(tr('Path'))}"><a href="#${esc(wk_home(sp))}" data-wk="home">${esc(wk_rootName(sp))}</a>${parts.slice(0, -1).map((x, i) => {
    const pg = wk_byPath(sp, parts.slice(0, i + 1).join('/'));
    if (typeof sbb_on === 'function' && sbb_on()) return `<span aria-hidden="true">/</span><a href="#${esc(wk_dirGo(parts.slice(0, i + 1).join('/'), sp))}">${esc(x)}</a>`;  // 2.152.3 B (#2620): the folder's list
    return `<span aria-hidden="true">/</span>${pg ? `<a href="#wiki/${pg.id}">${esc(x)}</a>` : `<span>${esc(x)}</span>`}`;
  }).join('')}</nav>`;
}
function wk_attrsHtml(a) {
  const ks = Object.keys(a || {}); if (!ks.length) return '';
  return `<dl class="wkattrs">${ks.map(k => `<div><dt>${esc(k)}</dt><dd>${esc(Array.isArray(a[k]) ? a[k].join(', ') : String(a[k]))}</dd></div>`).join('')}</dl>`;
}
function wk_pageHtml(p) {
  const may = WK.idx[p.space]?.mayWrite !== false, edit = WK.edit && may, mob = isMobile();
  return `<div class="nthead">${mob ? `<button type="button" class="iconbtn" data-wk="close" aria-label="${esc(tr('Back'))}">${ic('back')}</button>` : ''}
    <div class="wktitle">${wk_crumbs(p)}<h2>${esc(wk_base(p.path))}${typeof wsh_markHtml === 'function' ? wsh_markHtml(p.shares) : ''}</h2></div>
    ${may && typeof wsh_btnHtml === 'function' ? wsh_btnHtml(p) : ''}
    ${may ? `<button type="button" class="iconbtn" data-wk="pmenu" aria-haspopup="menu" title="${esc(tr('More'))}" aria-label="${esc(tr('More'))}">${ic('dots')}</button>` : ''}
    ${mob ? '' : `<button type="button" class="iconbtn" data-wk="close" title="${esc(tr('Close'))}" aria-label="${esc(tr('Close'))}">${ic('x')}</button>`}</div>
    ${may ? `<div class="seg ntmode" role="group" aria-label="${esc(tr('Mode'))}"><button type="button" data-wk="mode" data-m="read" class="${edit ? '' : 'on'}" aria-pressed="${!edit}">${tr('Read')}</button><button type="button" data-wk="mode" data-m="edit" class="${edit ? 'on' : ''}" aria-pressed="${edit}">${tr('Edit')}</button></div>` : ''}
    ${edit ? `<div class="wkedwrap">${typeof wem_bar === 'function' ? wem_bar(p) : ''}${typeof wklv_on === 'function' && wklv_on() ? wklv_html(p) : `<textarea id="wk-body" class="ntbody" aria-label="${esc(tr('Text'))}" placeholder="${esc(tr('Write … ([[Page]], #123)'))}">${esc(p.body)}</textarea>`}<div id="wk-ac" class="wkac hidden" role="listbox" aria-label="${esc(tr('Pages'))}"></div></div>`
      : `${wk_attrsHtml(p.attrs)}<div class="md ntmd wkmd" id="wk-md">${wk_bodyStrip(p.body).trim() ? wk_render(p) : `<p class="muted">${may ? tr('Empty page. Switch to Edit to write.') : tr('Empty page.')}</p>`}</div>`}
    ${wka_html(p, may)}${wko_cfHtml(p)}
    ${p.backlinks?.length ? `<section class="wkback" aria-label="${esc(tr('Linked from'))}"><h4>${ic('link', 's')}${tr('Linked from')}</h4><ul>${p.backlinks.map(b => `<li><a href="#wiki/${b.id}">${esc(b.path)}</a></li>`).join('')}</ul></section>` : ''}
    <div class="ntfoot muted"><span id="wk-saved" role="status" aria-live="polite"></span><span class="spacer"></span>${p._off ? `<span class="wkoff">${esc(tr('Offline · as of {0}', fmtWhen(p._off)))}</span> · ` : ''}<span>${esc(tr('Changed {0}', fmtWhen(p.updated_at)))}${p.updated_by_name ? ' · ' + esc(p.updated_by_name) : ''}</span></div>${wk_smvLine(p.moved)}`;
}
const wk_unesc = h => { const d = document.createElement('textarea'); d.innerHTML = h; return d.value; };
const wk_bodyStrip = b => String(b || '').replace(/^---[ \t]*\r?\n[\s\S]*?\r?\n---[ \t]*(?:\r?\n|$)/, '');
// 2.382.0 (#3153): formulas and Mermaid diagrams (diagram.js draws them, loaded only when a page has one): outside code
// blocks a "$$ … $$" line / a block between two "$$" lines becomes a ```math block; an inline \( … \) becomes a placeholder
// (Markdown would take its backslash as an escape) and later a .wkimath span with its source. No single $ (amounts of money).
const WK_DG_RE = /^\s*```\s*(?:math|mermaid)\s*$/m;
function wk_dgCut(src, ims) {
  if (!src.includes('$$') && !src.includes('\\(')) return src;
  const ls = src.split('\n'), out = [];
  let fence = false;
  for (let i = 0; i < ls.length; i++) {
    const l = ls[i];
    if (fence) { if (/^\s*```\s*$/.test(l)) fence = false; out.push(l); continue; }  // like renderMd: any ``` opens, a bare ``` closes
    if (/^\s*```/.test(l)) { fence = true; out.push(l); continue; }
    let m;
    if ((m = /^\s*\$\$(.+?)\$\$\s*$/.exec(l))) { out.push('```math', m[1].trim(), '```'); continue; }
    if (/^\s*\$\$\s*$/.test(l)) {
      const z = ls.findIndex((x, j) => j > i && /^\s*\$\$\s*$/.test(x));
      if (z > i) { out.push('```math', ...ls.slice(i + 1, z), '```'); i = z; continue; }
    }
    out.push(l.includes('\\(') ? l.split(/(`[^`]*`)/).map((x, k) => k % 2 ? x : x.replace(/\\\((.+?)\\\)/g, (_, t) => { ims.push(t); return `\u2063IM${ims.length - 1}\u2063`; })).join('') : l);
  }
  return out.join('\n');
}
function wk_dgNeed(src, ims) {
  if (!ims.length && !WK_DG_RE.test(src)) return;
  if (typeof dg_draw === 'function') setTimeout(() => dg_draw(), 0);
  else loadModule('diagram').then(() => dg_draw(), () => {});
}
// Markdown of the app + [[links]] + ```mindmap blocks (drawn by mindmap.js) + #123 (tasks I see)
function wk_render(p) {
  if (typeof wem_cut !== 'function') { ld_later('wiki'); return `<p class="muted">${esc(tr('Loading…'))}</p>`; }  // 2.200.0 (#2747): the page can draw before wkembed.js arrived (tree / panel)
  const mms = [], fls = [], ems = [], tcs = [], ims = [];  // 2.123.0 C (#2103): ems = files of the file store (wkembed.js); 2.376 (#3294): tcs = ```seiten blocks; 2.382.0 (#3153): ims = inline formulas
  const src = wem_cut(wka_cut(wk_dgCut(wk_bodyStrip(p.body), ims).replace(/^```mindmap[ \t]*\r?\n([\s\S]*?)^```[ \t]*$/gm, (_, t) => { mms.push(t); return `\nMM${mms.length - 1}\n`; })
    .replace(WKT_RE, (_, t) => { tcs.push(t); return `\n\n\u2063WKT${tcs.length - 1}\u2063\n\n`; }), fls), ems);
  wk_dgNeed(src, ims);
  let h = mdTaskRefs(renderMd(src, true));
  if (ims.length) h = h.replace(/\u2063IM(\d+)\u2063/g, (_, n) => { const t = ims[+n] ?? ''; return `<span class="wkimath" data-tex="${esc(t)}">\\(${esc(t)}\\)</span>`; });
  // [[links]] only in text: every tag is passed whole (no match inside an attribute), nothing inside code / pre / links
  let skip = 0;
  h = h.replace(/<(\/?)([a-zA-Z][\w-]*)[^>]*>|\[\[([^\[\]|#\n<>]{1,500})(#[^\[\]|\n<>]*)?(?:\|([^\[\]\n<>]*))?\]\]/g, (m, cl, tag, path, _a, label) => {
    if (tag) { if (/^(code|pre|a)$/i.test(tag)) skip = Math.max(0, skip + (cl ? -1 : 1)); return m; }
    if (skip > 0) return m;
    const t = path.trim(), pg = wk_byPath(p.space, wk_unesc(t)), lb = label ? label : t;  // t is HTML already
    if (/^\s*(datei|tabelle)\s*:/i.test(t)) return wem_link(p, wk_unesc(t), label);  // 2.123.0 C (#2107): a file / table (wkembed.js)
    return pg ? `<a href="#wiki/${pg.id}" class="wklink">${lb}</a>` : `<a href="#wiki" class="wklink wkmissing" data-wk="create" data-path="${t}" title="${esc(tr('Create this page'))}">${lb}</a>`;
  });
  h = h.replace(/(?:<p>)?\u2063WKT(\d+)\u2063(?:<\/p>)?/g, (_, n) => wk_tocHtml(p.space, tcs[+n] || ''));  // 2.376 (#3294)
  return wem_put(p, wka_put(h.replace(/(?:<p>)?MM(\d+)(?:<\/p>)?/g, (_, i) => typeof mm_blockHtml === 'function' ? mm_blockHtml(mms[+i] || '') : `<pre class="mdpre">${esc(mms[+i] || '')}</pre>`), fls), ems);  // 2.123.0 C (#2103, #2108)
}
// 2.376 (#3294): a ```seiten block (English ```pages): the pages of the page's space as a nested list of links sorted by path,
// live from the index this browser has (WK.idx: so also in a space with the lock, only pages the reader sees); nothing is
// stored, no server route. Lines: "ohne: A, B" (exclude:) leaves out pages whose path begins so or that have that name (case
// ignored), "ab: Folder/" (from:) only that folder, its paths shown below it, "tiefe: 2" (depth:) at most that many levels
const WKT_RE = /^```(?:seiten|pages)[ \t]*\r?\n([\s\S]*?)^```[ \t]*$/gim;
function wk_tocOpts(t) {
  const o = {ex: [], from: '', depth: 0};
  for (const ln of String(t || '').split(/\r?\n/)) {
    const m = /^\s*(ohne|exclude|ab|from|tiefe|depth)\s*:\s*(.*?)\s*$/i.exec(ln); if (!m) continue;
    const k = m[1].toLowerCase(), v = m[2];
    if (k === 'ohne' || k === 'exclude') o.ex.push(...v.split(',').map(x => x.trim().toLowerCase()).filter(Boolean));
    else if (k === 'ab' || k === 'from') o.from = v.replace(/^\/+|\/+$/g, '').toLowerCase();
    else o.depth = Math.max(0, Math.min(12, parseInt(v, 10) || 0));
  }
  return o;
}
function wk_tocHtml(sp, t) {
  const d = WK.idx[sp];
  if (!d?.pages) { if (sp && !d?.err) wk_load(sp); return `<p class="muted wktoc">${esc(d?.err || tr('Loading…'))}</p>`; }
  const o = wk_tocOpts(t), pre = o.from ? o.from + '/' : '', root = {kids: new Map()};
  for (const p of d.pages) {
    const lp = p.path.toLowerCase(), rel = lp.slice(pre.length);
    if (pre && !lp.startsWith(pre) || o.ex.some(x => lp.startsWith(x) || pre && rel.startsWith(x) || wk_base(lp) === x)) continue;
    const parts = p.path.slice(pre.length).split('/').filter(Boolean);
    if (!parts.length || o.depth && parts.length > o.depth) continue;
    let n = root;
    for (const part of parts) { const k = part.toLowerCase(); if (!n.kids.has(k)) n.kids.set(k, {name: part, page: null, kids: new Map()}); n = n.kids.get(k); }
    n.page = p;
  }
  const ul = n => `<ul>${[...n.kids.values()].sort((a, b) => a.name.localeCompare(b.name, LOCALE(), {numeric: true, sensitivity: 'base'})).map(k => `<li>${k.page ? `<a href="#wiki/${k.page.id}" class="wklink">${esc(k.name)}</a>` : `<span class="muted">${esc(k.name)}</span>`}${k.kids.size ? ul(k) : ''}</li>`).join('')}</ul>`;
  return root.kids.size ? `<nav class="wktoc" aria-label="${esc(tr('Pages'))}">${ul(root)}</nav>` : `<p class="muted wktoc">${esc(tr('No pages to list here.'))}</p>`;
}
// 2.99.0 A (#2182): the page's own files in its text -- ![label](/api/wiki/files/<id>/<name>) shows the picture,
// [label](…) opens the file (the app's Markdown takes web addresses only): cut out before the Markdown, put back after it
const WKA_RE = /(!?)\[([^\[\]\n]*)\]\(\/api\/wiki\/files\/(\d{1,15})(?:\/([^\s()]*))?\)/g;
const wka_cut = (src, out) => src.replace(WKA_RE, (_, bang, label, id, name) => { out.push({img: !!bang, label, id, name: name || ''}); return `\u2063WKA${out.length - 1}\u2063`; });
const wka_dec = n => { try { return decodeURIComponent(n); } catch { return n; } };
function wka_put(h, fls) {
  return h.replace(/\u2063WKA(\d+)\u2063/g, (m, i) => {
    const f = fls[+i]; if (!f) return '';
    const url = `/api/wiki/files/${f.id}/${encodeURIComponent(wka_dec(f.name))}`;
    return f.img ? `<a href="${esc(url)}" target="_blank" rel="noopener"><img class="wkimg" src="${esc(url)}" alt="${esc(f.label)}" loading="lazy"></a>`
      : `<a href="${esc(url)}" target="_blank" rel="noopener" class="wklink">${esc(f.label || wka_dec(f.name))}</a>`;
  });
}
function wka_html(p, may) {
  const fs = p.files || [], open = !wk_e2e(p.space);
  if (!fs.length && !(may && open)) return '';
  return `<section class="wkfiles" aria-label="${esc(tr('Files'))}"><h4>${ic('file', 's')}${tr('Files')}${fs.length ? ` · ${fs.length}` : ''}<span class="spacer"></span>${may && open ? `<button type="button" class="btn" data-wka="add">${ic('upload', 's')}${tr('Attach files')}</button>` : ''}</h4>
    ${fs.length ? `<ul>${fs.map(f => `<li><a class="wkfile" href="${esc(f.url)}" target="_blank" rel="noopener" title="${esc(f.name)}">${f.image ? `<img src="${esc(f.url)}" alt="" loading="lazy">` : ic('pdf')}<span class="an">${esc(f.name)}</span><span class="as">${fmtSize(f.size)}</span></a>
      <button type="button" class="iconbtn" data-wka="copy" data-id="${f.id}" title="${esc(tr('Copy link'))}" aria-label="${esc(tr('Copy link'))}">${ic('link')}</button>${may ? `<button type="button" class="iconbtn" data-wka="del" data-id="${f.id}" title="${esc(tr('Delete'))}" aria-label="${esc(tr('Delete'))}">${ic('trash')}</button>` : ''}</li>`).join('')}</ul>` : ''}</section>`;
}
const wka_md = f => `${f.image ? '!' : ''}[${f.name.replace(/[[\]]/g, '')}](${f.url})`;
function wka_add(p) {
  const inp = document.createElement('input');
  inp.type = 'file'; inp.multiple = true; inp.accept = '.pdf,.png,.jpg,.jpeg,.gif,.webp,.svg,application/pdf,image/*';
  inp.onchange = async () => {
    const fl = [...(inp.files || [])]; if (!fl.length) return;
    const fd = new FormData(); fl.forEach(f => fd.append('file', f));
    let r; try { r = await rawFetch('POST', `/api/wiki/pages/${p.id}/files`, fd); } catch (e) { toast(e.message); return; }
    const files = (r.files || []).map(f => f.id);
    wk_after(p.space);
    const e = histAdd({label: tr('Attach files'), ids: [], snaps: [], lids: [], wsp: p.space,
      undo: async () => { await rawFetch('POST', '/api/wiki/trash', {ids: [], files}); wk_after(p.space); return {skipped: []}; },
      redo: async () => { await rawFetch('POST', '/api/wiki/restore', {ids: [], files}); wk_after(p.space); return {skipped: []}; }});
    histToast(tr('{0} files attached', files.length), e);
  };
  inp.click();
}
async function wka_del(p, f) {
  try { await rawFetch('DELETE', '/api/wiki/files/' + f.id); } catch (e) { toast(e.message); return; }
  wk_after(p.space);
  const e = histAdd({label: tr('Deleted {0}', qn(f.name)), ids: [], snaps: [], lids: [], wsp: p.space,
    undo: async () => { const r = await rawFetch('POST', '/api/wiki/restore', {ids: [], files: [f.id]}); wk_after(p.space); return {skipped: r.files_skipped?.length ? [f.name] : []}; },
    redo: async () => { await rawFetch('POST', '/api/wiki/trash', {ids: [], files: [f.id]}); wk_after(p.space); return {skipped: []}; }});
  histToast(tr('Deleted {0}', qn(f.name)), e);
}
// the import report: pages, files, what was skipped and why (at most 200 lines from the server)
const wka_sum = r => [tr('{0} pages imported', (r.created || []).length), ...(r.files_n ? [tr('{0} files', r.files_n)] : []),
  ...(r.shortened_n ? [tr('{0} names shortened', r.shortened_n)] : []),  // 2.210 A (#2755)
  ...((r.skipped_n || r.skipped?.length) ? [tr('{0} skipped', r.skipped_n || r.skipped.length)] : [])].join(' · ');
function wka_report(r) {
  const sk = r.skipped_detail || (r.skipped || []).map(n => ({name: n, reason: ''})), sh = r.shortened || [];
  if (!sk.length && !sh.length) return;
  const md = modal(`<h3>${esc(tr('Import'))}</h3><p>${esc(wka_sum(r))}</p>
    ${sh.length ? `<details class="wkrep wkrep-short"><summary>${esc(tr('{0} names shortened', r.shortened_n || sh.length))}</summary><p class="muted">${esc(tr('Too long or too many folder levels: the page is there under a shorter name.'))}</p><ul>${sh.map(s => `<li><b>${esc(s.name)}</b> · ${esc(s.path)}</li>`).join('')}</ul></details>` : ''}
    ${sk.length ? `<details class="wkrep"><summary>${esc(tr('{0} skipped', r.skipped_n || sk.length))}</summary><ul>${sk.map(s => `<li><b>${esc(s.name)}</b>${s.reason ? ' · ' + esc(s.reason) : ''}</li>`).join('')}</ul></details>` : ''}
    <div class="foot"><button type="button" class="btn" data-m="close">${esc(tr('OK'))}</button></div>`);
  md.addEventListener('click', e => { if (e.target.closest('[data-m="close"]')) modalClose(md); });
}
document.addEventListener('click', e => {
  const a = e.target.closest?.('[data-wka]'); if (!a || !$('#view')?.contains(a)) return;
  const p = WK.pg, f = p?.files?.find(x => x.id === +a.dataset.id); if (!p) return;
  if (a.dataset.wka === 'add') wka_add(p);
  else if (a.dataset.wka === 'copy' && f) navigator.clipboard?.writeText(wka_md(f)).then(() => toast(tr('Link copied')));
  else if (a.dataset.wka === 'del' && f) wka_del(p, f);
});
// ---- saving (like notes: debounced, a change by someone else in between asks)
// 2.350.0 B (#3147): the field one writes in: the plain text editor or the open block of the live preview (wklive.js)
const wk_ta = () => /** @type {any} */ ($('#wk-body') || $('#wk-blk'));
const wk_isTa = t => t?.id === 'wk-body' || t?.id === 'wk-blk';
function wk_queue() { WK.dirty = true; clearTimeout(WK.saveT); WK.saveT = setTimeout(wk_flush, 1000); }
async function wk_flush(hide) {
  clearTimeout(WK.saveT);
  const p = WK.pg, b = $('#wk-body') || (typeof wklv_src === 'function' ? wklv_src(p) : null); if (!p || !WK.dirty) return;  // 2.350.0 B (#3147): + the live preview
  WK.dirty = false;
  if (!b || b.value === p.body) return;
  const patch = {body: b.value, expect_updated_at: p.updated_at}, url = '/api/wiki/pages/' + p.id;
  // 2.169.0 (#2671): offline (or with a change of this page still waiting) the text waits in the outbox: closing the tab keeps it
  if (hide || p._off || OUT.q.some(x => x.url === url)) { await wko_queue(p, patch); return; }  // the tab goes: the outbox (IndexedDB) keeps it, a fetch would be cut off
  try {
    const r = typeof wkeApi === 'function' ? await wkeApi('PATCH', url, patch, p.space) : await rawFetch('PATCH', url, patch);  // 2.64.3 B (#1817)
    Object.assign(p, r, {backlinks: p.backlinks, _v: S.v});
    wko_keep(p.space, r);
    wk_savedHint(tr('Saved'));
  } catch (e) {
    if (e.status === 409 && e.data?.page) { wk_conflict(p, e.data.page, patch); return; }
    if (e instanceof Offline) { await wko_queue(p, patch); return; }
    WK.dirty = true; toast(e.message);
  }
}
function wk_savedHint(t) { const s = $('#wk-saved'); if (s) { s.textContent = t; setTimeout(() => { if (s.isConnected) s.textContent = ''; }, 2500); } }
// true = settled (mine saved or theirs taken), false = mine could not be saved, null = closed without a choice (as before: theirs shown)
async function wk_conflict(mine, theirs, patch) {
  let took = false;
  const keep = await askDialog({after: md => md.querySelector('[data-cd="no"]')?.addEventListener('click', () => { took = true; }), title: tr('Changed in the meantime by {0}', theirs.updated_by_name || '?'), html: `<p>${tr('Keep your version or take theirs?')}</p><div class="ntdiff"><div><b>${tr('Yours')}</b><pre>${esc(patch.body)}</pre></div><div><b>${tr('Theirs')}</b><pre>${esc(theirs.body)}</pre></div></div>`, ok: tr('Keep mine'), cancel: tr('Take theirs')});
  let ok = true;
  if (keep) { try { Object.assign(mine, typeof wkeApi === 'function' ? await wkeApi('PATCH', '/api/wiki/pages/' + mine.id, {...patch, expect_updated_at: theirs.updated_at}, mine.space) : await rawFetch('PATCH', '/api/wiki/pages/' + mine.id, {...patch, expect_updated_at: theirs.updated_at})); } catch (e) { toast(e.message); ok = false; } }
  else { Object.assign(mine, theirs); if (!took) ok = null; }
  renderView();
  return ok;
}
// ---- actions (each one Undo step)
const wk_tplOpts = sp => `<option value="0">${tr('Empty page')}</option>${wk_pages(sp).filter(p => wk_isTpl(p.path)).map(t => `<option value="${t.id}">${esc(wk_base(t.path))}</option>`).join('')}`;
async function wk_new(path0 = '', dir = '', spx = '') {  // 2.210 B (#2757): dir = the folder the dialog starts in, spx = its space
  const ask = !spx && !wk_open() && !path0;  // 2.198.0 A (#2743): under "All" into the open space; none open = the dialog asks, the space used last first
  if (ask) await Promise.all(wk_spaces().map(s => WK.idx[s]?.pages ? null : wk_load(s)));
  const sps = ask ? wk_spaces().filter(s => !wk_locked(s) && WK.idx[s]?.mayWrite !== false) : [];
  const sp0 = spx || (ask && sps.length && !sps.includes(wk_cur()) ? sps[0] : wk_cur()), tpls = wk_pages(sp0).filter(p => wk_isTpl(p.path));
  WK.spPick = sp0;
  const pre = dir || path0 || (S.route.mod === 'wiki' && S.route.wdir ? S.route.wdir + '/' : '') || (WK.pg && WK.pg.space === sp0 && WK.pg.path.includes('/') ? WK.pg.path.split('/').slice(0, -1).join('/') + '/' : '');  // 2.152.3 B (#2620): + the open folder
  WK.tplPick = 0;
  const tsel = (tpls.length || ask) && !path0 ? `<label class="wktpl ${tpls.length ? '' : 'hidden'}">${tr('Template')}<select data-wk-tpl aria-label="${esc(tr('Template'))}">${wk_tplOpts(sp0)}</select></label>` : '';
  const ssel = ask ? `<label class="wktpl">${tr('Space')}<select data-wk-sp aria-label="${esc(tr('Space'))}">${sps.map(s => `<option value="${esc(s)}" ${s === sp0 ? 'selected' : ''}>${esc(wk_spaceName(s))}</option>`).join('')}</select></label>` : '';
  const path = path0 || await askDialog({title: tr('New page'), html: ssel + tsel, input: {value: pre, placeholder: tr('Name, folders with / (e.g. Processes/Checklist)'), max: 500}, ok: tr('Create')});
  if (!path || !path.trim()) return;
  const tpl = +WK.tplPick || 0, sp = ask && wk_spaces().includes(WK.spPick) ? WK.spPick : sp0;
  let r; try { r = wk_e2e(sp) ? await wkeCreate(sp, path.trim(), tpl) : await rawFetch('POST', '/api/wiki/pages', {space: sp, path: path.trim(), ...(tpl ? {template_id: tpl} : {})}); } catch (e) { toast(e.message); return; }  // 2.64.3 B (#1817): name check + template here
  wk_after(sp); WK.editNext = r.id; go('wiki/' + r.id);
  const e = histAdd({label: tr('Created {0}', qn(wk_base(r.path))), ids: [], snaps: [], lids: [], wsp: sp,
    undo: async () => { await rawFetch('POST', '/api/wiki/trash', {ids: [r.id]}); wk_after(sp); return {skipped: []}; },
    redo: async () => { await rawFetch('POST', '/api/wiki/restore', {ids: [r.id]}); wk_after(sp); return {skipped: []}; }});
  histToast(tr('Page {0} created', qn(wk_base(r.path))), e);
}
function wk_after(sp) { if (WK.idx[sp]) WK.idx[sp].v = -1; if (WK.pg) WK.pg._v = -1; if (S.route.mod === 'wiki') renderView(); if (typeof sbb_sync === 'function') sbb_sync('wiki'); }  // 2.152.3 B (#2620): + the panel
async function wk_rename(p) {
  await wk_flush();
  const np = await askPrompt(tr('Rename page'), p.path, {input: {max: 500}, ok: tr('Rename')});
  if (!np || np.trim() === p.path) return;
  const old = p.path;
  const ren = async (path) => { const r = wk_e2e(p.space) ? await wkeRename(p, path) : await rawFetch('PATCH', '/api/wiki/pages/' + p.id, {path}); if (WK.pg?.id === p.id) Object.assign(WK.pg, r); wk_after(p.space); return r; };  // 2.64.3 B (#1817): links renamed here
  let r; try { r = await ren(np.trim()); } catch (e) { toast(e.message); return; }
  const e = histAdd({label: tr('Renamed {0}', qn(wk_base(r.path))), ids: [], snaps: [], lids: [], wsp: p.space,
    undo: async () => { await ren(old); return {skipped: []}; }, redo: async () => { await ren(r.path); return {skipped: []}; }});
  histToast(r.relinked ? trn('Renamed, {0} link changed', 'Renamed, {0} links changed', r.relinked) : tr('Renamed'), e);
}
async function wk_moveFolder(p) {  // the folder of the page (and everything under it) gets another name
  await wk_flush();
  const from = p.path.split('/').slice(0, -1).join('/'); if (!from) return;
  const to = await askPrompt(tr('Rename folder'), from, {input: {max: 500}, ok: tr('Rename')});
  if (!to || !to.trim() || to.trim() === from) return;
  const mv = async (a, b) => { const r = wk_e2e(p.space) ? await wkeMove(p.space, a, b) : await rawFetch('POST', '/api/wiki/move', {space: p.space, from: a, to: b}); wk_after(p.space); return r; };  // 2.64.3 B (#1817): one PATCH per page
  let r; try { r = await mv(from, to.trim()); } catch (e) { toast(e.message); return; }
  const nf = to.trim().split('/').filter(Boolean).join('/');
  const e = histAdd({label: tr('Renamed {0}', qn(from)), ids: [], snaps: [], lids: [], wsp: p.space,
    undo: async () => { await mv(nf, from); return {skipped: []}; }, redo: async () => { await mv(from, nf); return {skipped: []}; }});
  histToast(trn('{0} page moved', '{0} pages moved', r.moved.length), e);
}
async function wk_delete(p) {
  await wk_flush();
  try { await rawFetch('DELETE', '/api/wiki/pages/' + p.id); } catch (e) { toast(e.message); return; }
  WK.pg = null; wk_after(p.space); go(wk_home(p.space));  // 2.198.0 A (#2743)
  const e = histAdd({label: tr('Deleted {0}', qn(wk_base(p.path))), ids: [], snaps: [], lids: [], wsp: p.space,
    undo: async () => { const r = await rawFetch('POST', '/api/wiki/restore', {ids: [p.id]}); wk_after(p.space); return {skipped: r.skipped?.length ? [p.path] : []}; },
    redo: async () => { await rawFetch('POST', '/api/wiki/trash', {ids: [p.id]}); wk_after(p.space); return {skipped: []}; }});
  histToast(tr('Page {0} deleted', qn(wk_base(p.path))), e);
}
function wk_export() { if (wk_e2e(wk_cur())) { wkeExport(wk_cur()).catch(e => toast(e.message)); return; }  // 2.64.3 B (#1817): the ZIP is made in the browser
  const a = document.createElement('a'); a.href = '/api/wiki/export?space=' + encodeURIComponent(wk_cur()); a.download = 'wiki.zip'; document.body.append(a); a.click(); a.remove(); }
// 2.143.0 B (#2211): the trash of the space -- restore a page, delete one for good, empty it (server: wiki/pages.py wiki_purge)
async function wk_trashDlg(sp = wk_cur()) {
  const md = modal(`<h3>${tr('Trash')} · ${esc(wk_spaceName(sp))}</h3><div class="wktrash"><div class="muted mhint">${tr('Loading…')}</div></div>
    <div class="foot"><button type="button" class="btn danger hidden" data-wkt="empty">${ic('trash', 's')} ${tr('Empty trash')}</button><span class="spacer"></span><button type="button" class="btn" data-wkt="close">${tr('Close')}</button></div>`);
  md.classList.add('wktrashdlg');
  let pages = [];
  const draw = async () => {
    const box = $('.wktrash', md);
    let j; try { j = await rawFetch('GET', '/api/wiki/trash?space=' + encodeURIComponent(sp)); } catch (e) { box.innerHTML = `<div class="muted mhint">${esc(e instanceof Offline ? tr('Knowledge pages are only available online.') : e.message)}</div>`; return; }
    pages = j.pages || [];
    if (wk_e2e(sp) && typeof wkeOpen === 'function') { const ks = await wkeKeys(sp).catch(() => null); for (const p of pages) if (!await wkeOpen(sp, p, ks).catch(() => false)) p.path = ''; }
    $('[data-wkt="empty"]', md).classList.toggle('hidden', !pages.length || j.may_empty === false);  // 2.306.0 D3 (#2875): an organisation's admins
    box.innerHTML = (pages.length ? `<div class="members">${pages.map(p => `<div class="mrow wktrow" data-wktid="${p.id}"><span class="n"><b>${p.path ? esc(p.path) : `<span class="muted">${tr('Encrypted page')}</span>`}</b><small class="muted">${esc([tr('Moved to the trash on {0}', fmtWhen(p.deleted_at)), p.files ? trn('{0} file', '{0} files', p.files) + ' · ' + fmtBytes(p.size) : ''].filter(Boolean).join(' · '))}</small></span>`
      + `<span class="oadmb"><button type="button" class="btn sm" data-wkt="restore">${ic('undo', 's')}<span>${tr('Restore')}</span></button><button type="button" class="btn sm danger" data-wkt="purge">${ic('trash', 's')}<span>${tr('Delete permanently…')}</span></button></span></div>`).join('')}</div>`
      : `<div class="muted mhint">${tr('Trash is empty.')}</div>`) + `<div class="shint">${esc(trashNote(tr('Pages in the trash are deleted for good after {0} days, with their files.', j.days || 30), j.purge_on === false))}</div>`;
  };
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-wkt]'); if (!b) return;
    const k = b.dataset.wkt, id = +b.closest('[data-wktid]')?.dataset.wktid, p = pages.find(x => x.id === id);
    if (k === 'close') { modalClose(md); return; }
    b.disabled = true;
    try {
      if (k === 'restore' && p) { const r = await rawFetch('POST', '/api/wiki/restore', {ids: [id]}); if (r.skipped?.length) toast(tr('A page with this name already exists')); }
      if (k === 'purge' && p) {
        if (!await askConfirm(tr('Delete “{0}” permanently?', p.path ? wk_base(p.path) : tr('Encrypted page')), tr('The page and its files are deleted for good. This cannot be undone.'), {danger: true, ok: tr('Delete permanently')})) return;
        await rawFetch('POST', '/api/wiki/purge', {space: sp, ids: [id]});
      }
      if (k === 'empty') {
        if (!await askConfirm(tr('Empty the trash permanently?'), tr('All pages in the trash and their files are deleted for good. This cannot be undone.'), {danger: true, ok: tr('Empty trash')})) return;
        await rawFetch('POST', '/api/wiki/purge', {space: sp, all: true});
      }
      wk_after(sp); await draw();
    } catch (x) { toast(x.message); } finally { b.disabled = false; }
  });
  await draw();
}
function wk_import() {
  let sp = wk_cur();
  const inp = document.createElement('input');
  inp.type = 'file'; inp.accept = '.zip,application/zip';
  inp.onchange = async () => {
    const f = inp.files?.[0]; if (!f) return;
    // 2.87.9 (#1940): where the pages go, in words; from an organisation's knowledge also into the private one
    const to = await importTargetConfirm({what: tr('the pages'), ws: sp, place: tr('Knowledge pages'), privOk: true});
    if (!to) return;
    if (to === 'private') sp = 'private';
    if (!wk_e2e(sp)) { wki_start(sp, f); return; }  // 2.177.0 (#2685): in pieces with progress, unpacked in the background (wkimport.js)
    let r; try { r = await wki_e2e(sp, f); } catch (e) { toast(e.message); return; }  // 2.64.3 B (#1817): read and encrypted in the browser
    if (r) wka_done(sp, r);
  };
  inp.click();
}
// the end of an import: the report, one Undo step (2.177.0 #2685: also from wkimport.js when the server finished)
function wka_done(sp, r) {
  wk_after(sp);
  const ids = r.created || [], files = r.files || [];  // 2.99.0 A (#2182): + the new files (also those on pages that were there)
  const msg = wka_sum(r) + (sp !== wk_cur() ? ' · ' + tr('Into {0}', wk_spaceName(sp)) : '');  // 2.210 A (#2755): another space than the one shown
  wka_report(r);
  if (!ids.length && !files.length) { toast(msg); return; }
  const e = histAdd({label: tr('Import of {0} pages', ids.length), ids: [], snaps: [], lids: [], wsp: sp,
    undo: async () => { await rawFetch('POST', '/api/wiki/trash', {ids, files}); wk_after(sp); return {skipped: []}; },
    redo: async () => { await rawFetch('POST', '/api/wiki/restore', {ids, files}); wk_after(sp); return {skipped: []}; }});
  histToast(msg, e);
}
// ---- [[ suggestions while typing: the pages of the space whose name has what follows [[
function wk_acUpdate(ta) {
  const box = $('#wk-ac'); if (!box) return;
  const before = ta.value.slice(0, ta.selectionStart), m = /\[\[([^\[\]\n|#]{0,80})$/.exec(before);
  if (typeof wklv_tk === 'function' && wklv_tk(ta, box)) return;  // 2.371.3 (#3333): the task search after "/" -> "Task (#)"
  if (typeof wklv_slash === 'function' && wklv_slash(ta, box)) return;  // 2.350.0 B (#3149): "/" at the start of a line
  if (!m) { box.classList.add('hidden'); WK.ac = null; return; }
  if (wem_ac(ta, box, m[1], before.length - m[1].length)) return;  // 2.123.0 C (#2107): [[datei: / [[tabelle: (wkembed.js)
  const q = m[1].toLowerCase(), sp = WK.pg?.space || wk_cur();
  const hits = wk_pages(sp).filter(p => p.id !== WK.pg?.id && p.path.toLowerCase().includes(q)).slice(0, 8);
  if (!hits.length) { box.classList.add('hidden'); WK.ac = null; return; }
  WK.ac = {hits, i: 0, from: before.length - m[1].length};
  wk_acDraw(box);
}
function wk_acDraw(box) {
  box.innerHTML = WK.ac.hits.map((p, i) => `<button type="button" role="option" class="${i === WK.ac.i ? 'on' : ''}" aria-selected="${i === WK.ac.i}" data-wk="ac" data-i="${i}">${typeof wem_fi === 'function' ? wem_fi(p._ic || 'note') : ic(p._ic || 'note', 's')}<span>${esc(p._label || p.path)}</span></button>`).join('');
  box.classList.remove('hidden');
  if (typeof wem_acPlace === 'function') wem_acPlace(box);  // 2.126.2 A (#2363): stay above the on-screen keyboard
  if (typeof wklv_acPlace === 'function') wklv_acPlace(box);  // 2.350.0 B (#3147): below the live preview's open block
}
function wk_acPick(i) {
  const ta = wk_ta(), a = WK.ac; if (!ta || !a) return;
  if (a.cmd) { wklv_slashPick(ta, a.hits[i]); return; }  // 2.350.0 B (#3149)
  if (a.tk) { wklv_tkPick(ta, a.hits[i]); return; }  // 2.371.3 (#3333)
  const p = a.hits[i], end = ta.selectionStart, rest = ta.value.slice(end), close = rest.startsWith(']]') ? '' : ']]';
  ta.value = ta.value.slice(0, a.from) + p.path + close + rest;
  const pos = a.from + p.path.length + 2; ta.setSelectionRange(pos, pos); ta.focus();
  WK.ac = null; $('#wk-ac')?.classList.add('hidden'); wk_queue();
}
// 2.99.0 B (#2183): the former sidebar menu, now the "Space" section (de: Bereich) of the header "…" menu (same rights as before)
function w299_areaItems() {
  return [{head: tr('Space')}, {label: tr('Export as ZIP'), icon: 'download', fn: wk_export}, ...(WK.idx[wk_cur()]?.mayWrite !== false ? [{label: tr('Import ZIP…'), icon: 'upload', fn: wk_import}, {label: tr('Trash'), icon: 'trash', fn: () => wk_trashDlg()}] : []),  // 2.143.0 B (#2211): + Trash
    ...(typeof wkeDlg === 'function' && S.me?.kind !== 'agent' && globalThis.crypto?.subtle ? [{label: tr('Encryption…'), icon: 'lock', fn: () => wkeDlg(wk_cur())}] : []),
    ...(typeof wkst_items === 'function' && WK.idx[wk_cur()]?.may_style ? wkst_items({space: wk_cur()}) : [])];  // 2.371.3 (#3152): the space's reading style
}
// ---- events (own listeners: data-wk)
document.addEventListener('click', async e => {
  const a = e.target.closest?.('[data-wk]'); if (!a || !$('#view')?.contains(a) && a.dataset.wk !== 'ac') return;
  const k = a.dataset.wk, p = WK.pg;
  if (k === 'new') { wk_new(); }
  else if (k === 'newfolder') wk_newFolder(wk_open() || wk_cur());  // 2.200.0 A (#2747)
  else if (k === 'rmenu') { e.preventDefault(); menu(a, wk_nodeItems(+a.dataset.nid, a)); }
  else if (k === 'lostdel') { const id = WK.pgLost; if (id) await wk_delete(wk_pages(wk_cur()).find(x => x.id === id) || {id, path: '', space: wk_cur()}); }  // 2.139.0 C (#2386)
  else if (k === 'create') { e.preventDefault(); if (WK.idx[p?.space || wk_cur()]?.mayWrite !== false) wk_new(a.dataset.path); }
  else if (k === 'close' || k === 'home') { e.preventDefault(); await wk_flush(); WK.edit = false; go(k === 'close' && p && wk_dirOf(p.path) && typeof sbb_on === 'function' && sbb_on() ? wk_dirGo(wk_dirOf(p.path), p.space) : p ? wk_home(p.space) : 'wiki'); }  // 2.198.0 A (#2743): under "All" into the page's space  // 2.152.3 B (#2620): a computer: back to the page's folder
  else if (k === 'amenu') menu(a, w299_areaItems());  // 2.152.3 B (#2620): the space's menu in the bar
  else if (k === 'mode') { if (a.dataset.m === 'read') await wk_flush(); WK.edit = a.dataset.m === 'edit'; renderView(); if (WK.edit) setTimeout(() => wk_ta()?.focus(), 30); }
  else if (k === 'ac') { e.preventDefault(); wk_acPick(+a.dataset.i); }
  else if (k === 'cfshow' && p) wko_cfShow(p);  // 2.169.0 (#2671)
  else if (k === 'pmenu' && p) menu(a, [{label: tr('Rename…'), icon: 'edit', fn: () => wk_rename(p)},
    ...(p.path.includes('/') ? [{label: tr('Rename folder…'), icon: 'folder', fn: () => wk_moveFolder(p)}] : []),
    ...wk_smvItems(p),  // 2.96.0 B (#1941)
    ...(typeof wsh_menuItems === 'function' ? wsh_menuItems(p) : []),  // 2.123.0 B (#2104): Share… / Share folder…
    ...(typeof wkh_items === 'function' ? wkh_items(p) : []),  // 2.123.0 A (#2102): the page history (wkhist.js)
    {label: tr('Copy link'), icon: 'link', fn: () => { navigator.clipboard?.writeText(`${location.origin}${location.pathname}#wiki/${p.id}`).then(() => toast(tr('Link copied'))); }},
    {label: tr('Copy as [[link]]'), icon: 'copy', fn: () => { navigator.clipboard?.writeText(`[[${p.path}]]`).then(() => toast(tr('Link copied'))); }},
    ...(typeof wklv_menuItem === 'function' ? [wklv_menuItem()] : []),  // 2.350.0 B (#3147): live preview <-> plain text
    ...(typeof wkst_items === 'function' ? wkst_items(p) : []),  // 2.371.3 (#3152): reading style (mine / the space's)
    '-', {label: tr('Delete'), icon: 'trash', cls: 'flag-5', fn: () => wk_delete(p)}]);
});
document.addEventListener('change', e => {
  if (e.target.matches?.('[data-wk-tpl]')) WK.tplPick = +e.target.value;
  if (e.target.matches?.('[data-wk-sp]')) { WK.spPick = e.target.value; const t = e.target.closest('.cdlg-b')?.querySelector('[data-wk-tpl]'); if (t) { t.innerHTML = wk_tplOpts(WK.spPick); t.closest('.wktpl')?.classList.toggle('hidden', !wk_pages(WK.spPick).some(x => wk_isTpl(x.path))); WK.tplPick = 0; } }  // 2.198.0 A (#2743): New page without an open space: its templates follow the space
});
document.addEventListener('input', async e => {
  if (wk_isTa(e.target)) { wk_queue(); wk_acUpdate(e.target); }  // 2.350.0 B (#3147): + the live preview's block
  else if (e.target.id === 'wk-q') { WK.q = e.target.value; const r = $('#wk-res'); if ($('#view .wkdesk')) { if (WK.dirty) await wk_flush(); renderView(); return; }  /* 2.152.3: save a page being edited before the hits replace it */ if (r) {  /* 2.152.3 B (#2620): the bar of a computer: hits replace the page / folder */ const v = document.createElement('div'); v.innerHTML = viewWiki(); const n = $('#wk-res', v); if (n) r.innerHTML = n.innerHTML; } }
});
document.addEventListener('keydown', e => {
  if (!wk_isTa(e.target)) return;
  if (!WK.ac) { if (e.key === 'Escape' && typeof WKLV !== 'undefined' && WKLV.tk) { WKLV.tk = null; e.preventDefault(); e.stopPropagation(); } return; }  // 2.371.3 (#3333): Esc also ends a task search without hits
  const box = $('#wk-ac'), n = WK.ac.hits.length;
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); WK.ac.i = (WK.ac.i + (e.key === 'ArrowDown' ? 1 : n - 1)) % n; wk_acDraw(box); }
  else if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); wk_acPick(WK.ac.i); }
  else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); WK.ac = null; if (typeof WKLV !== 'undefined') WKLV.tk = null; box?.classList.add('hidden'); }  // 2.371.3 (#3333): + the task search
}, true);
document.addEventListener('focusout', e => { if (wk_isTa(e.target)) wk_flush(); });
// ---- the command field: the pages of every space (their indexes load once in the background, the next opening has them)
function wk_palAdd(add) {
  if (!feat('wiki')) return;
  for (const sp of wk_spaces()) {
    if (!WK.idx[sp]) { wk_load(sp); continue; }
    for (const p of wk_pages(sp)) add('wk:' + p.id, 'note', wk_base(p.path), 'book', () => go('wiki/' + p.id), {sub: [wk_spaceName(sp), p.path.includes('/') ? p.path.split('/').slice(0, -1).join('/') : ''].filter(Boolean).join(' · ')});
  }
}
// ---- a task's "Mentioned in": the pages I may read that name #id (asked once per change of the data)
WK.men = {};
function wk_mentionHtml(t) {
  if (!feat('wiki') || !(t.id > 0)) return '';
  const m = WK.men[t.id];
  if (!m || m.v !== S.v) {
    if (!m?.busy) { WK.men[t.id] = {...(m || {}), busy: true}; wk_mentions(t.id).then(ps => { WK.men[t.id] = {v: S.v, pages: ps}; if (S.sel === t.id && ps.length !== (m?.pages || []).length) renderDetail(); }); }
    if (!m?.pages) return '';
  }
  const ps = (WK.men[t.id].pages || m?.pages || []); if (!ps.length) return '';
  return `<div class="dsec wkmen">${ic('book', 's')}<span class="muted">${tr('Mentioned in')}</span>${ps.map(p => `<a href="#wiki/${p.id}" class="wklink">${esc(p.path)}</a>`).join('<span class="muted">,</span>')}</div>`;
}
// ---- search / command field: pages of every space ("Knowledge page")
async function wk_search(q) {
  if (!feat('wiki') || !q || q.length < 2) return [];
  let ps; try { ps = (await rawFetch('GET', '/api/wiki/search?q=' + encodeURIComponent(q))).pages || []; } catch { ps = []; }
  return typeof wkeSearch === 'function' ? [...ps, ...wkeSearch(q)] : ps;  // 2.64.3 B (#1817): + the unlocked encrypted spaces, searched here
}
// ---- a task's "Mentioned in" (the detail asks once per opening)
async function wk_mentions(tid) {
  if (!feat('wiki') || !(tid > 0)) return [];
  let ps; try { ps = (await rawFetch('GET', '/api/wiki/mentions?task=' + tid)).pages || []; } catch { ps = []; }
  if (typeof wkeMentions !== 'function') return ps;
  await Promise.all(wk_spaces().filter(sp => !WK.idx[sp]).map(sp => wk_load(sp)));  // 2.64.3 B (#1817): + the unlocked encrypted spaces
  return [...ps, ...await wkeMentions(tid)];
}
// 2.66.1 (#1945): an open page keeps its own space (wk_cur); switching to another workspace leaves it for that workspace's pages
if (typeof p61b_wsOn === 'function') p61b_wsOn('wiki', after => {
  const ws = wsCur();
  if (after || ws === 'all' || S.route.mod !== 'wiki' || !WK.pg || WK.pg.space === ws) return;
  WK.pg = null; S.route.wid = null; go('wiki');
});
// ---- 2.96.0 B (#1941): a page, or its folder with everything below it, to the other workspace (private <-> organisation).
// The shared dialog (spacemove.js) names the source, lets the person pick the target space and a folder there and shows the
// server's dry run (names taken, links that point to the other space, linked files that stay); the move back is ONE undo
// step. 2.97.0 D (#2050): with the lock on either side this browser re-encrypts the pages (wikie2e.js wkr_run).
const wk_smvOrg = sp => sp && sp !== 'private' ? +sp.slice(4) : null;
function wk_smvItems(p) {
  if (S.me?.kind === 'agent' || !smv_can(wk_smvOrg(p.space)) || p._wke || (wk_e2e(p.space) && typeof wkr_run !== 'function')) return [];
  const it = [{label: tr('Move to another workspace…'), icon: 'brief', fn: () => wk_smvMove(p, false)}];
  if (p.path.includes('/')) it.push({label: tr('Move folder to another workspace…'), icon: 'folder', fn: () => wk_smvMove(p, true)});
  return it;
}
async function wk_smvFolders(sp) {  // the folders of a space (from the paths of its pages)
  await wk_load(sp);
  const fs = new Set();
  for (const x of wk_pages(sp)) { const ps = x.path.split('/'); for (let i = 1; i < ps.length; i++) fs.add(ps.slice(0, i).join('/')); }
  return [...fs].sort((a, b) => a.localeCompare(b)).map(f => ({id: f, label: f}));
}
async function wk_smvMove(p, folder) {
  await wk_flush();
  const from = p.space, fpath = folder ? p.path.split('/').slice(0, -1).join('/') : '';
  const what = folder ? tr('Folder {0}', qn(fpath)) : qn(wk_base(p.path));
  const req = (to, dest, dry) => rawFetch('POST', '/api/wiki/move-space', {...(folder ? {folder: fpath} : {pages: [p.id]}), space: from, to: smv_ws(to), dest, dry: dry ? 1 : 0});
  // 2.97.0 D (#2050): the lock on a side -> the pages and their new names are worked out here (the server sees no names)
  const locked = async to => { await wk_load(smv_ws(to)); return wk_e2e(from) || wk_e2e(smv_ws(to)); };
  const plan = d => {
    const fl = fpath.toLowerCase(), cut = folder ? fpath.length - wk_base(fpath).length : 0;
    const ps = folder ? wk_pages(from).filter(x => x.path.toLowerCase().startsWith(fl + '/')) : [p];
    return ps.map(x => { const rest = folder ? x.path.slice(cut) : wk_base(x.path); return {id: x.id, path: wkeClean(d ? d + '/' + rest : rest)}; });
  };
  let dest = '', lk = false;
  const r = await smv_open({what, from: wk_smvOrg(from), places: to => wk_smvFolders(smv_ws(to)),
    check: async (to, d) => await locked(to) ? wkr_check(from, smv_ws(to), plan(d)) : req(to, d, true),
    run: async (to, d) => {
      try {
        dest = d; lk = await locked(to);
        if (!lk) return await req(to, d, false);
        if (wk_e2e(from) && !wk_e2e(smv_ws(to)) && !await askConfirm(tr('Move to another workspace'), tr('The pages are no longer end-to-end encrypted in the target.'), {ok: tr('Move'), danger: true})) return null;
        return await wkr_run(from, smv_ws(to), plan(d));
      } catch (e) { toast(e.message); throw e; }
    }});
  if (!r || !r.moved) return;
  const to = r.space, oldDest = (folder ? fpath : p.path).split('/').slice(0, -1).join('/'), moved = r.moved;
  const newFolder = folder ? (dest ? dest + '/' : '') + fpath.split('/').pop() : null;
  const back = async (src, dst, dest, fd, fwd) => {
    const x = lk ? await wkr_run(src, dst, moved.map(m => ({id: m.id, path: fwd ? m.to : m.from})))  // 2.97.0 D (#2050): re-encrypted again
      : await rawFetch('POST', '/api/wiki/move-space', {...(fd ? {folder: fd} : {pages: moved.map(m => m.id)}), space: src, to: dst, dest});
    wk_after(src); wk_after(dst); return x;
  };
  wk_after(from); wk_after(to); WK.space = to;
  if (WK.pg?.id === p.id) { WK.pg = null; go('wiki/' + p.id); }
  const e = histAdd({label: tr('Moved {0}', what), ids: [], snaps: [], lids: [], wsp: to,
    undo: async () => { await back(to, from, oldDest, newFolder, false); return {skipped: []}; },
    redo: async () => { await back(from, to, dest, folder ? fpath : null, true); return {skipped: []}; }});
  histToast(trn('{0} page moved', '{0} pages moved', moved.length), e);
}
function wk_smvLine(m) {  // the last move between workspaces (both sides see it below the page; 2.97.0 D #2051: names from the server)
  if (!m) return '';
  return `<p class="muted wksmv">${ic('brief', 's')} ${esc(tr('Moved out of {0}', m.from_name || (m.from ? wk_spaceName(m.from) : tr('Organisation'))))} · ${esc(fmtWhen(m.at))}${m.by_name ? ' · ' + esc(m.by_name) : ''}</p>`;
}
if (typeof sbb_sync === 'function') sbb_sync('wiki');  // 2.152.3 B: loaded later than the panel was drawn (lazyload.js): its panel now
// ---- 2.169.0 (#2671): the offline copy. Every space read here stays in IndexedDB "kalmido-wiki" (store "c", one record per key):
// s:<space> = the index with every text as the server sent it (a locked space only as ciphers: wkeIndex opens them in memory),
// e:<space> = the lock's state of a locked space (wrapped keys only, wikie2e.js wkeInfo), x:<page> = an offline change the server
// refused (changed elsewhere in the meantime): it waits at the page until mine or theirs is picked. A sync asks only for the texts
// changed since the newest one here; offline the view reads the copy ("Offline · as of …") and a changed text waits in the outbox
// (core.js) like a task's. Files stay online-only. Logout empties the database (icons.js clearLocal); a space this account
// no longer has, and another account's records, go at the next sync (wko_syncAll). 2.238.0 B (#2872): every record carries the
// sign-in mark (me.sgen); another sign-in, a lost session or 14 days without an online sync empty it (core.js sessGuard).
const WKO = {st: null, cf: {}, syncP: null, dead: false, swept: null};
const wko_rq = r => new Promise((ok, no) => { r.onsuccess = () => ok(r.result); r.onerror = () => no(r.error); });
// the small store over IndexedDB: get(k), put(v), del(k), all(), clear(), close(); tests hand in their own (__wkoStore)
function wko_idb() {
  if (!globalThis.indexedDB) return null;
  let dbp = null;
  const db = () => dbp ||= new Promise((ok, no) => {
    const r = indexedDB.open('kalmido-wiki', 1);
    r.onupgradeneeded = () => { if (!r.result.objectStoreNames.contains('c')) r.result.createObjectStore('c', {keyPath: 'k'}); };
    r.onsuccess = () => { r.result.onversionchange = () => { r.result.close(); dbp = null; }; ok(r.result); };  // logout in another tab deletes it
    r.onerror = () => no(r.error); r.onblocked = () => no(new Error('blocked'));
  }).catch(e => { dbp = null; throw e; });
  const os = async mode => (await db()).transaction('c', mode).objectStore('c');
  return {get: async k => wko_rq((await os('readonly')).get(k)), put: async v => wko_rq((await os('readwrite')).put(v)), del: async k => wko_rq((await os('readwrite')).delete(k)),
    all: async () => wko_rq((await os('readonly')).getAll()),
    pre: async x => wko_rq((await os('readonly')).getAll(IDBKeyRange.bound(x, x + '\uffff'))),  // 2.169.1 (#2672): only the keys starting with x
    clear: async () => wko_rq((await os('readwrite')).clear()), close: async () => { const p = dbp; dbp = null; if (p) (await p.catch(() => null))?.close(); }};
}
const wko_st = () => WKO.dead ? null : WKO.st ||= globalThis.__wkoStore || wko_idb();  // after logout nothing is written again (a sync still on its way)
async function wko_get(k) { try { const r = S.me ? await wko_st()?.get(k) : null; return r && r.uid === S.me.id && (r.g || '') === (S.me.sgen || '') ? r : null; } catch { return null; } }  // private mode: no copy, as before; 2.238.0 B (#2872): only this sign-in's records
async function wko_put(r) {
  if (!S.me || WKO.dead) return;
  const v = JSON.parse(JSON.stringify({...r, uid: S.me.id, g: S.me.sgen || ''}));  // the copy is taken now (wkeIndex opens the texts of the caller's object afterwards)
  try { await wko_st()?.put(v); } catch (e) { console.warn('wiki offline copy: write failed', e); }
}
async function wko_del(k) { try { await wko_st()?.del(k); } catch { /* gone already */ } }
async function wko_all() { try { return (await wko_st()?.all()) || []; } catch { return []; } }
// 2.169.1 (#2672): the records of one kind (x: = waiting conflicts) without reading the whole copy; a store without pre() filters all()
async function wko_pre(x) { try { const st = wko_st(); return (st?.pre ? await st.pre(x) : (await st?.all() || []).filter(r => r.k.startsWith(x))) || []; } catch { return []; } }
// 2.238.0 B (#2872): another sign-in or too old (core.js sessGuard): everything out, a new copy may follow
async function wko_reset() { WKO.cf = {}; try { await wko_st()?.clear(); } catch { /* gone */ } }
// logout (icons.js clearLocal): everything out, the database closed (clearLocal deletes it then)
async function wko_wipe() { const st = WKO.st; WKO.cf = {}; WKO.dead = true; if (!st) return; try { await st.clear(); } catch { /* gone */ } try { await st.close?.(); } catch { /* closed */ } WKO.st = null; }
const wko_sig = e => e?.mode ? `${e.mode}:${e.gen || 0}:${e.reenc || 0}` : '';
const wko_clone = v => JSON.parse(JSON.stringify(v));
// the index of a space with its texts: from the server (only the texts changed since the copy's newest), the copy kept; offline the copy
// 2.280.0 C (#3114): the texts come in pages of WKO_BN (bn=, the cursor bnext); the index with the first page, the rest after it
const WKO_BN = 500;
async function wko_fetch(url) {
  const j = await rawFetch('GET', url + '&bn=' + WKO_BN), by = new Map((j.pages || []).map(p => [p.id, p]));
  for (let nx = j.bnext, i = 0; nx && i < 20; i++) {
    const r = await rawFetch('GET', url + '&bn=' + WKO_BN + '&nolist=1&bafter=' + encodeURIComponent(nx));
    for (const [id, b] of Object.entries(r.bodies || {})) { const p = by.get(+id); if (p) p.body = b; }
    nx = r.bnext;
  }
  delete j.bnext;
  return j;
}
async function wko_sync(sp) {
  WKO.swept ||= wko_sweep();  // 2.280.0 C (#3114): the copy's tidying once per session, at the first space opened (no start sync any more)
  const c = await wko_get('s:' + sp), url = '/api/wiki?space=' + encodeURIComponent(sp) + '&bodies=1&offline=1';
  const since = (c?.pages || []).reduce((m, p) => p.updated_at > m ? p.updated_at : m, '');
  let j;
  try {
    j = await wko_fetch(url + (since ? '&since=' + encodeURIComponent(since) : ''));
    if (!since) for (const p of j.pages) if (!('body' in p)) p.body = '';  // as one answer did: a page added between two pages of texts
    if (since) {
      const old = new Map(c.pages.map(p => [p.id, p]));
      // a page the copy lacks (moved in from another space) or another state of the lock: everything once more
      if (wko_sig(j.e2e) !== wko_sig(c.e2e) || j.pages.some(p => !('body' in p) && old.get(p.id)?.updated_at !== p.updated_at)) { j = await wko_fetch(url); for (const p of j.pages) if (!('body' in p)) p.body = ''; }
      else for (const p of j.pages) if (!('body' in p)) p.body = old.get(p.id).body;
    }
    await wko_put({k: 's:' + sp, sp, at: new Date().toISOString(), space: j.space, may_write: j.may_write, e2e: j.e2e || null, more: !!j.more, pages: wko_clone(j.pages), folders: wko_clone(j.folders || []), root: j.root || null});  // 2.200.0 A (#2747): + the folders
    if (!WKO.dead && S.me) LS.set('wko', {g: S.me.sgen || '', at: new Date().toISOString()});  // 2.238.0 B (#2872): the last online sync (core.js sessGuard)
  } catch (e) {
    if ([403, 404].includes(e.status)) { wko_del('s:' + sp); wko_del('e:' + sp); }  // no access any more: the copy goes too
    if (!(e instanceof Offline) || !c) throw e;
    j = {space: c.space, may_write: c.may_write, e2e: c.e2e, more: !!c.more, pages: wko_clone(c.pages), folders: wko_clone(c.folders || []), root: c.root || null, _off: c.at};
  }
  await wko_cfLoad(sp);
  return wko_overlay(j);
}
// the texts still waiting in the outbox are what this device shows (also after the server's older answer)
function wko_overlay(j) {
  const by = new Map((j.pages || []).map(p => [p.id, p]));
  for (const x of OUT.q) { const m = x.method === 'PATCH' && !x.done && x.url.match(/^\/api\/wiki\/pages\/(\d+)$/), p = m && by.get(+m[1]); if (p && typeof x.body?.body === 'string') p.body = x.body.body; }
  return j;
}
// an online save: the copy gets the new text (a locked space's cipher; without one the page leaves the copy, the next sync fetches it)
async function wko_keep(sp, r) {
  if (!r?.id) return;
  const c = await wko_get('s:' + sp); if (!c) return;
  const body = wk_e2e(sp) ? r._enc?.body : r.body, i = c.pages.findIndex(p => p.id === r.id);
  if (i < 0) return;
  if (typeof body !== 'string') c.pages.splice(i, 1);
  else c.pages[i] = {...c.pages[i], body, updated_at: r.updated_at || c.pages[i].updated_at, updated_by: r.updated_by ?? c.pages[i].updated_by};
  await wko_put(c);
}
// a page offline: from the index (opened already), its backlinks found here; files need a connection
async function wko_page(id) {
  const find = () => { for (const sp of wk_spaces()) { const p = wk_pages(sp).find(x => x.id === id); if (p) return [sp, p]; } return null; };
  let f = find();
  if (!f) { await Promise.all(wk_spaces().filter(sp => !WK.idx[sp]?.pages).map(sp => wk_load(sp, true))); f = find(); }
  if (!f) return null;
  const [sp, p] = f, d = WK.idx[sp];
  return {...p, space: sp, files: [], moved: null, backlinks: typeof wkeBacklinks === 'function' ? wkeBacklinks(sp, p) : [], _off: d?.off || new Date().toISOString()};
}
// a changed text into the outbox: a locked space's text only as its cipher; a waiting change of the page takes the newer text
async function wko_queue(p, patch) {
  const url = '/api/wiki/pages/' + p.id;
  let b = {...patch};
  if (wk_e2e(p.space)) {
    if (typeof wkeReady !== 'function' || !wkeReady(p.space)) { WK.dirty = true; toast(tr('Unlock first: this space is encrypted in the browser.')); return; }
    b = await wkeSeal(p.space, {body: patch.body}); b.expect_updated_at = patch.expect_updated_at;
  }
  const q = outSync().find((x, i) => (i > 0 || !OUT.flushing) && !x.sending && !x.done && x.method === 'PATCH' && x.url === url);
  if (q) { outSave(() => { q.body = {...q.body, body: b.body}; }); renderTop(); }
  else enqueue('PATCH', url, b);
  p.body = patch.body;
  const c = await wko_get('s:' + p.space), cp = c?.pages.find(x => x.id === p.id);
  if (cp) { cp.body = b.body; await wko_put(c); }
  wk_savedHint(OUT.online ? tr('Saved') : tr('Saved on this device, sent when online'));
}
// core.js outFlush: a sent change came back -- the copy's text and the base of the changes still waiting
async function wkoSent(e, j) {
  if (!j?.id) return;
  const old = e.body?.expect_updated_at;
  if (old && j.updated_at) outSave(() => { for (const x of OUT.q) if (x !== e && x.url === e.url && x.body?.expect_updated_at === old) x.body = {...x.body, expect_updated_at: j.updated_at}; });
  if (WK.pg?.id === j.id) { WK.pg.updated_at = j.updated_at; WK.pg._v = -1; }
  const c = await wko_get('s:' + j.space), cp = c?.pages.find(x => x.id === j.id);
  if (cp) { Object.assign(cp, {body: j.body, updated_at: j.updated_at, updated_by: j.updated_by}); await wko_put(c); }
}
// core.js outFlush: the server refused a waiting text because the page was changed elsewhere -- it waits at the page (true =
// handled here); other refusals (deleted, no right) go to the conflicts dialog as before
async function wkoReject(e, err) {
  const pg = err?.status === 409 ? err.data?.page : null, id = +((e.url.match(/^\/api\/wiki\/pages\/(\d+)$/) || [])[1]);
  if (!pg || !id || typeof e.body?.body !== 'string') return false;
  if (pg.body === e.body.body) { await wkoSent(e, pg); return true; }  // sent twice (the first answer got lost): saved already
  WKO.cf[id] = {k: 'x:' + id, id, sp: pg.space, mine: e.body.body, at: new Date().toISOString()};
  await wko_put(WKO.cf[id]);
  if (WK.pg?.id === id) WK.pg._v = -1;
  setTimeout(() => toast(tr('A knowledge page was changed elsewhere in the meantime: your version waits at the page')), 400);
  return true;
}
async function wko_cfLoad(sp) { for (const r of await wko_pre('x:')) if (r.sp === sp && r.uid === S.me?.id) WKO.cf[r.id] = r; }
function wko_cfHtml(p) {
  if (!WKO.cf[p.id]) return '';
  return `<div class="cfbar wkocf" role="status"><span>${esc(tr('Your offline change was not saved: the page was changed elsewhere in the meantime'))}</span><button type="button" class="btn sm" data-wk="cfshow">${tr('Compare')}</button></div>`;
}
async function wko_cfShow(p) {
  const r = WKO.cf[p.id]; if (!r) return;
  if (!OUT.online) { toast(tr('Offline: only works again with a connection')); return; }
  await wk_loadPage(p.id, true);
  const cur = WK.pg; if (!cur || cur.id !== p.id || cur._off) return;
  let mine = r.mine;
  if (typeof wkeIs === 'function' && wkeIs(mine)) { mine = await wkeDec(cur.space, 'body', mine).catch(() => null); if (mine == null) { toast(tr('Unlock first: this space is encrypted in the browser.')); return; } }
  if (await wk_conflict(cur, {...cur}, {body: mine, expect_updated_at: cur.updated_at}) === true) { delete WKO.cf[p.id]; await wko_del(r.k); renderView(); }  // closed without a choice: mine keeps waiting
}
// 2.169.1 (#2672): a space with more pages than the index holds says that only the first ones are kept here
const wko_offHtml = (at, more) => `<div class="muted mhint wkoff" role="status">${ic('sync', 's')}${esc(tr('Offline · as of {0}', fmtWhen(at)))}${more ? ' · ' + esc(tr('only the first {0} pages', 5000)) : ''}</div>`;
// a space this account no longer has and another account's records leave the copy
async function wko_sweep() {
  const sps = wk_spaces();
  for (const r of await wko_all()) if (r.uid !== S.me?.id || !sps.includes(r.sp)) await wko_del(r.k);
}
// when the connection is back: the spaces opened here since the start into the copy. 2.280.0 C (#3114): no sync at the
// start any more (main.js) - a space comes into the copy when it is opened (wk_load), the copy of an earlier visit stays
async function wko_syncAll() {
  if (!feat('wiki') || !OUT.online || !S.me || S.me.kind === 'agent') return;
  return WKO.syncP ||= (async () => {
    for (const sp of wk_spaces().filter(s => WK.idx[s]?.pages)) await wk_load(sp, true).catch(() => {});
  })().finally(() => { WKO.syncP = null; });
}
window.addEventListener('online', () => setTimeout(wko_syncAll, 3000));
// a text typed within the last second is not lost when the tab goes away
document.addEventListener('visibilitychange', () => { if (document.hidden && WK.dirty) wk_flush(true); });
window.addEventListener('pagehide', () => { if (WK.dirty) wk_flush(true); });
// 2.210 B (#2757): a right click / long press on a row of the folder list = its "…" menu (2.200.0 #2747, wk_nodeItems)
cm_bind('#view .wkrow', r => {
  const a = r.querySelector(':scope > .wkmore, :scope > details > summary > .wkmore'); if (!a) return false;
  menu(a, wk_nodeItems(+a.dataset.nid, a)); return true;
});
