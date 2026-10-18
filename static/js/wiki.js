/* Kalmido web client: knowledge pages (#1199, "SilverBullet lite"). Route #wiki (the pages of the current space) and
   #wiki/<id> (one page). A space = an organisation (every member reads and writes) or "Private" (only me); the sidebar's
   workspace switch picks it, else the last one used here. Pages are Markdown with a path as their name ("Processes/
   Shoot day/Checklist": the folders of the tree), [[Path]] links another page (suggestions while typing), #123 a task
   (only tasks I see become links), the backlinks are listed below the page, the frontmatter (a leading --- block) shows
   as small fields, pages under Templates/ are offered by "New page", a ```mindmap block draws its list as a mind map
   (mindmap.js). Saving is automatic like notes (a change by someone else in between asks which version stays);
   create, rename, delete and import are one Undo step each. Export / import: a ZIP of .md files (SilverBullet-compatible).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

const WK = {space: null, idx: {}, pg: null, pgErr: '', edit: false, dirty: false, saveT: 0, q: '', ac: null, busy: {}};
const wk_spaces = () => ['private', ...(S.me?.workspaces || []).map(w => 'org:' + w.id)];
function wk_cur() {
  const ok = v => !!v && wk_spaces().includes(v);
  if (WK.pg && WK.pg.id === S.route.wid && ok(WK.pg.space)) return WK.pg.space;
  const ws = wsCur?.(); if (ws && ws !== 'all' && ok(ws)) return ws;
  if (ok(WK.space)) return WK.space;
  const ls = LS.get('wkSpace', ''); if (ok(ls)) return ls;
  return wk_spaces()[1] || 'private';
}
const wk_spaceName = sp => sp === 'private' ? tr('Private|workspace') : (wsOrg(sp.slice(4))?.name || tr('Organisation'));
const wk_base = p => p.split('/').pop();
const wk_isTpl = p => /^(templates|vorlagen)\//i.test(p);
const wk_e2e = sp => typeof wkeOn === 'function' && wkeOn(sp);  // 2.64.3 B (#1817): the space is encrypted in the browser (wikie2e.js)
async function wk_load(sp, force) {
  const d = WK.idx[sp] || (WK.idx[sp] = {});
  if (WK.busy['i' + sp] || (!force && d.pages && d.v === S.v)) return;
  WK.busy['i' + sp] = true;
  try { let j = await rawFetch('GET', '/api/wiki?space=' + encodeURIComponent(sp) + '&bodies=1'); if (typeof wkeIndex === 'function') j = await wkeIndex(sp, j); d.pages = j.pages; d.mayWrite = j.may_write; d.err = ''; }  // 2.64.3 B (#1817): texts of an encrypted space open here
  catch (e) { if (e.message === 'auth') return; d.err = e instanceof Offline ? tr('Knowledge pages are only available online.') : e.message; d.pages = d.pages || null; if ([403, 404].includes(e.status) && typeof wkeForget === 'function') wkeForget(sp); }  // 2.64.3 E (#1817): no access any more
  finally { d.v = S.v; WK.busy['i' + sp] = false; }
  if (S.route.mod === 'wiki') viewSafeRender();
}
async function wk_loadPage(id, force) {
  if (WK.busy['p' + id] || (!force && WK.pg && WK.pg.id === id && (WK.pg._v === S.v || WK.dirty || WK.edit))) return;
  WK.busy['p' + id] = true;
  try { const p = await rawFetch('GET', '/api/wiki/pages/' + id); if (typeof wkePage === 'function') await wkePage(p); p._v = S.v; WK.pgErrFor = null; if (WK.pg?.id !== id) { WK.edit = !!WK.editNext && WK.editNext === id; WK.editNext = null; } WK.pg = p; WK.pgErr = ''; WK.space = p.space; }  // 2.64.3 B (#1817)
  catch (e) { if (e.message === 'auth') return; WK.pgErrFor = id + ':' + S.v; WK.pgErr = e.status === 404 ? tr('This page does not exist or you cannot see it.') : e instanceof Offline ? tr('Knowledge pages are only available online.') : e.message; if (WK.pg?.id === id) WK.pg = null; }
  finally { WK.busy['p' + id] = false; }
  if (S.route.mod === 'wiki') viewSafeRender();
}
const wk_pages = sp => WK.idx[sp]?.pages || [];
const wk_byPath = (sp, p) => wk_pages(sp).find(x => x.path.toLowerCase() === String(p).trim().toLowerCase());
// ---- the tree from the paths: {name, path, page, kids: Map}
function wk_tree(pages) {
  const root = {name: '', path: '', page: null, kids: new Map()};
  for (const p of pages) {
    let n = root, acc = '';
    for (const part of p.path.split('/')) {
      acc = acc ? acc + '/' + part : part;
      const k = part.toLowerCase();
      if (!n.kids.has(k)) n.kids.set(k, {name: part, path: acc, page: null, kids: new Map()});
      n = n.kids.get(k);
    }
    n.page = p;
  }
  return root;
}
function wk_treeHtml(n, cur, many, depth = 0) {
  const kids = [...n.kids.values()].sort((a, b) => (b.kids.size > 0) - (a.kids.size > 0) || a.name.localeCompare(b.name, LOCALE()));
  return `<ul class="wktree" role="${depth ? 'group' : 'tree'}">${kids.map(k => {
    const on = cur && k.page && k.page.id === cur.id, open = !many || (cur && cur.path.toLowerCase().startsWith(k.path.toLowerCase() + '/'));
    const name = k.page ? `<a href="#wiki/${k.page.id}" class="wkitem ${on ? 'on' : ''}" ${on ? 'aria-current="page"' : ''} role="treeitem">${ic(wk_isTpl(k.path) ? 'copy' : 'note', 's')}<span>${esc(k.name)}</span></a>`
      : `<span class="wkitem wkdir">${ic('folder', 's')}<span>${esc(k.name)}</span></span>`;
    return k.kids.size ? `<li><details ${open ? 'open' : ''}><summary>${name}</summary>${wk_treeHtml(k, cur, many, depth + 1)}</details></li>` : `<li>${name}</li>`;
  }).join('')}</ul>`;
}
// ---- the view
function viewWiki() {
  const sp = wk_cur(), d = WK.idx[sp];
  if (!d || d.v !== S.v) wk_load(sp);
  const id = S.route.wid;
  if (id && WK.pgErrFor !== id + ':' + S.v && (!WK.pg || WK.pg.id !== id || WK.pg._v !== S.v)) wk_loadPage(id);  // a page that failed: again only with new data
  const cur = id && WK.pg && WK.pg.id === id ? WK.pg : null, mob = isMobile();
  const pages = d?.pages || [], q = WK.q.trim().toLowerCase();
  const vis = q ? pages.filter(p => p.path.toLowerCase().includes(q)) : pages;
  const sel = wk_spaces().length > 1 && (!wsCur?.() || wsCur() === 'all') ?  // 2.63.0 (#1857): the switch above picks the space, this list only with "All"
     `<label class="wkspace"><span class="sr">${tr('Space')}</span><select data-wk="space" aria-label="${esc(tr('Space'))}">${wk_spaces().map(s => `<option value="${esc(s)}" ${s === sp ? 'selected' : ''}>${esc(wk_spaceName(s))}</option>`).join('')}</select>${typeof wkeMark === 'function' ? wkeMark(sp) : ''}</label>` : (typeof wkeMark === 'function' ? wkeMark(sp) : '');  // 2.64.3 (#1817): the lock mark
  const side = `<div class="ntlist wkside">
    <div class="ntbar">${sel}<button type="button" class="iconbtn" data-wk="menu" aria-haspopup="menu" title="${esc(tr('More'))}" aria-label="${esc(tr('More'))}">${ic('dots')}</button></div>
    <div class="ntbar"><div class="ssearch">${ic('search', 's')}<input id="wk-q" type="search" value="${esc(WK.q)}" placeholder="${esc(tr('Find a page'))}" aria-label="${esc(tr('Find a page'))}" autocomplete="off"></div>
      <button type="button" class="btn sm pri" data-wk="new">${ic('plus', 's')}${tr('New page')}</button></div>
    ${typeof wkeBarHtml === 'function' ? wkeBarHtml(sp) : ''}<nav id="wk-res" aria-label="${esc(tr('Pages'))}">${typeof wkeLockHtml === 'function' && d?.pages && wkeLockHtml(sp) ? wkeLockHtml(sp) : !d?.pages ? `<div class="muted mhint">${d?.err ? esc(d.err) : tr('Loading…')}</div>`
      : vis.length ? (q ? `<ul class="wktree">${vis.map(p => `<li><a href="#wiki/${p.id}" class="wkitem">${ic('note', 's')}<span>${esc(p.path)}</span></a></li>`).join('')}</ul>` : wk_treeHtml(wk_tree(vis), cur, vis.length > 30))
      : q ? `<div class="empty">${tr('No page matches.')}</div>` : heronEmpty('empty', tr('No pages yet.'), tr('Processes, checklists, how-tos: write down what the team needs to know.'))}</nav></div>`;
  const main = id ? `<article class="ntedit wkpage" aria-label="${esc(cur ? wk_base(cur.path) : tr('Page'))}">${cur ? (cur._wke && typeof wkeLockHtml === 'function' ? wkeLockHtml(cur.space, true) : wk_pageHtml(cur)) : `<div class="muted mhint">${WK.pgErr ? esc(WK.pgErr) : tr('Loading…')}</div>`}</article>` : '';
  return `<div class="ntwrap wkwrap"><div class="ntview ${id ? 'open' : ''}">${mob && id ? '' : side}${main}</div></div>`;
}
function wk_crumbs(p) {
  const parts = p.path.split('/'), sp = p.space;
  return `<nav class="wkcrumbs" aria-label="${esc(tr('Path'))}"><a href="#wiki" data-wk="home">${esc(wk_spaceName(sp))}</a>${parts.slice(0, -1).map((x, i) => {
    const pg = wk_byPath(sp, parts.slice(0, i + 1).join('/'));
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
    <div class="wktitle">${wk_crumbs(p)}<h2>${esc(wk_base(p.path))}</h2></div>
    ${may ? `<button type="button" class="iconbtn" data-wk="pmenu" aria-haspopup="menu" title="${esc(tr('More'))}" aria-label="${esc(tr('More'))}">${ic('dots')}</button>` : ''}
    ${mob ? '' : `<button type="button" class="iconbtn" data-wk="close" title="${esc(tr('Close'))}" aria-label="${esc(tr('Close'))}">${ic('x')}</button>`}</div>
    ${may ? `<div class="seg ntmode" role="group" aria-label="${esc(tr('Mode'))}"><button type="button" data-wk="mode" data-m="read" class="${edit ? '' : 'on'}" aria-pressed="${!edit}">${tr('Read')}</button><button type="button" data-wk="mode" data-m="edit" class="${edit ? 'on' : ''}" aria-pressed="${edit}">${tr('Edit')}</button></div>` : ''}
    ${edit ? `<div class="wkedwrap"><textarea id="wk-body" class="ntbody" aria-label="${esc(tr('Text'))}" placeholder="${esc(tr('Markdown: # heading, - list, [[Page]] links a page, #123 a task'))}">${esc(p.body)}</textarea><div id="wk-ac" class="wkac hidden" role="listbox" aria-label="${esc(tr('Pages'))}"></div></div>`
      : `${wk_attrsHtml(p.attrs)}<div class="md ntmd wkmd" id="wk-md">${wk_bodyStrip(p.body).trim() ? wk_render(p) : `<p class="muted">${may ? tr('Empty page. Switch to Edit to write.') : tr('Empty page.')}</p>`}</div>`}
    ${p.backlinks?.length ? `<section class="wkback" aria-label="${esc(tr('Linked from'))}"><h4>${ic('link', 's')}${tr('Linked from')}</h4><ul>${p.backlinks.map(b => `<li><a href="#wiki/${b.id}">${esc(b.path)}</a></li>`).join('')}</ul></section>` : ''}
    <div class="ntfoot muted"><span id="wk-saved" role="status" aria-live="polite"></span><span class="spacer"></span><span>${esc(tr('Changed {0}', fmtWhen(p.updated_at)))}${p.updated_by_name ? ' · ' + esc(p.updated_by_name) : ''}</span></div>`;
}
const wk_unesc = h => { const d = document.createElement('textarea'); d.innerHTML = h; return d.value; };
const wk_bodyStrip = b => String(b || '').replace(/^---[ \t]*\r?\n[\s\S]*?\r?\n---[ \t]*(?:\r?\n|$)/, '');
// Markdown of the app + [[links]] + ```mindmap blocks (drawn by mindmap.js) + #123 (tasks I see)
function wk_render(p) {
  const mms = [];
  const src = wk_bodyStrip(p.body).replace(/^```mindmap[ \t]*\r?\n([\s\S]*?)^```[ \t]*$/gm, (_, t) => { mms.push(t); return `\nMM${mms.length - 1}\n`; });
  let h = mdTaskRefs(renderMd(src, true));
  // [[links]] only in text: every tag is passed whole (no match inside an attribute), nothing inside code / pre / links
  let skip = 0;
  h = h.replace(/<(\/?)([a-zA-Z][\w-]*)[^>]*>|\[\[([^\[\]|#\n<>]{1,250})(#[^\[\]|\n<>]*)?(?:\|([^\[\]\n<>]*))?\]\]/g, (m, cl, tag, path, _a, label) => {
    if (tag) { if (/^(code|pre|a)$/i.test(tag)) skip = Math.max(0, skip + (cl ? -1 : 1)); return m; }
    if (skip > 0) return m;
    const t = path.trim(), pg = wk_byPath(p.space, wk_unesc(t)), lb = label ? label : t;  // t is HTML already
    return pg ? `<a href="#wiki/${pg.id}" class="wklink">${lb}</a>` : `<a href="#wiki" class="wklink wkmissing" data-wk="create" data-path="${t}" title="${esc(tr('Create this page'))}">${lb}</a>`;
  });
  return h.replace(/(?:<p>)?MM(\d+)(?:<\/p>)?/g, (_, i) => typeof mm_blockHtml === 'function' ? mm_blockHtml(mms[+i] || '') : `<pre class="mdpre">${esc(mms[+i] || '')}</pre>`);
}
// ---- saving (like notes: debounced, a change by someone else in between asks)
function wk_queue() { WK.dirty = true; clearTimeout(WK.saveT); WK.saveT = setTimeout(wk_flush, 1000); }
async function wk_flush() {
  clearTimeout(WK.saveT);
  const p = WK.pg, b = $('#wk-body'); if (!p || !WK.dirty) return;
  WK.dirty = false;
  if (!b || b.value === p.body) return;
  const patch = {body: b.value, expect_updated_at: p.updated_at};
  try {
    const r = typeof wkeApi === 'function' ? await wkeApi('PATCH', '/api/wiki/pages/' + p.id, patch, p.space) : await rawFetch('PATCH', '/api/wiki/pages/' + p.id, patch);  // 2.64.3 B (#1817)
    Object.assign(p, r, {backlinks: p.backlinks, _v: S.v});
    const s = $('#wk-saved'); if (s) { s.textContent = tr('Saved'); setTimeout(() => { if (s.isConnected) s.textContent = ''; }, 1500); }
  } catch (e) {
    if (e.status === 409 && e.data?.page) { wk_conflict(p, e.data.page, patch); return; }
    WK.dirty = true; toast(e instanceof Offline ? tr('You are offline: the page is saved as soon as the server is reachable') : e.message);
  }
}
async function wk_conflict(mine, theirs, patch) {
  const keep = await askDialog({title: tr('Changed in the meantime by {0}', theirs.updated_by_name || '?'), html: `<p>${tr('Keep your version or take theirs?')}</p><div class="ntdiff"><div><b>${tr('Yours')}</b><pre>${esc(patch.body)}</pre></div><div><b>${tr('Theirs')}</b><pre>${esc(theirs.body)}</pre></div></div>`, ok: tr('Keep mine'), cancel: tr('Take theirs')});
  if (keep) { try { Object.assign(mine, typeof wkeApi === 'function' ? await wkeApi('PATCH', '/api/wiki/pages/' + mine.id, {...patch, expect_updated_at: theirs.updated_at}, mine.space) : await rawFetch('PATCH', '/api/wiki/pages/' + mine.id, {...patch, expect_updated_at: theirs.updated_at})); } catch (e) { toast(e.message); } }
  else Object.assign(mine, theirs);
  renderView();
}
// ---- actions (each one Undo step)
async function wk_new(path0 = '') {
  const sp = wk_cur(), tpls = wk_pages(sp).filter(p => wk_isTpl(p.path));
  const pre = path0 || (WK.pg && WK.pg.space === sp && WK.pg.path.includes('/') ? WK.pg.path.split('/').slice(0, -1).join('/') + '/' : '');
  WK.tplPick = 0;
  const tsel = tpls.length && !path0 ? `<label class="wktpl">${tr('Template')}<select data-wk-tpl aria-label="${esc(tr('Template'))}"><option value="0">${tr('Empty page')}</option>${tpls.map(t => `<option value="${t.id}">${esc(wk_base(t.path))}</option>`).join('')}</select></label>` : '';
  const path = path0 || await askDialog({title: tr('New page'), html: tsel, input: {value: pre, placeholder: tr('Name, folders with / (e.g. Processes/Checklist)'), max: 200}, ok: tr('Create')});
  if (!path || !path.trim()) return;
  const tpl = +WK.tplPick || 0;
  let r; try { r = wk_e2e(sp) ? await wkeCreate(sp, path.trim(), tpl) : await rawFetch('POST', '/api/wiki/pages', {space: sp, path: path.trim(), ...(tpl ? {template_id: tpl} : {})}); } catch (e) { toast(e.message); return; }  // 2.64.3 B (#1817): name check + template here
  wk_after(sp); WK.editNext = r.id; go('wiki/' + r.id);
  const e = histAdd({label: tr('Created {0}', qn(wk_base(r.path))), ids: [], snaps: [], lids: [], wsp: sp,
    undo: async () => { await rawFetch('POST', '/api/wiki/trash', {ids: [r.id]}); wk_after(sp); return {skipped: []}; },
    redo: async () => { await rawFetch('POST', '/api/wiki/restore', {ids: [r.id]}); wk_after(sp); return {skipped: []}; }});
  histToast(tr('Page {0} created', qn(wk_base(r.path))), e);
}
function wk_after(sp) { if (WK.idx[sp]) WK.idx[sp].v = -1; if (WK.pg) WK.pg._v = -1; if (S.route.mod === 'wiki') renderView(); }
async function wk_rename(p) {
  await wk_flush();
  const np = await askPrompt(tr('Rename page'), p.path, {input: {max: 200}, ok: tr('Rename')});
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
  const to = await askPrompt(tr('Rename folder'), from, {input: {max: 200}, ok: tr('Rename')});
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
  WK.pg = null; wk_after(p.space); go('wiki');
  const e = histAdd({label: tr('Deleted {0}', qn(wk_base(p.path))), ids: [], snaps: [], lids: [], wsp: p.space,
    undo: async () => { const r = await rawFetch('POST', '/api/wiki/restore', {ids: [p.id]}); wk_after(p.space); return {skipped: r.skipped?.length ? [p.path] : []}; },
    redo: async () => { await rawFetch('POST', '/api/wiki/trash', {ids: [p.id]}); wk_after(p.space); return {skipped: []}; }});
  histToast(tr('Page {0} deleted', qn(wk_base(p.path))), e);
}
function wk_export() { if (wk_e2e(wk_cur())) { wkeExport(wk_cur()).catch(e => toast(e.message)); return; }  // 2.64.3 B (#1817): the ZIP is made in the browser
  const a = document.createElement('a'); a.href = '/api/wiki/export?space=' + encodeURIComponent(wk_cur()); a.download = 'wiki.zip'; document.body.append(a); a.click(); a.remove(); }
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
    const fd = new FormData(); fd.append('file', f);
    let r; try { r = wk_e2e(sp) ? await wkeImport(sp, f) : await rawFetch('POST', '/api/wiki/import?space=' + encodeURIComponent(sp), fd); } catch (e) { toast(e.message); return; }  // 2.64.3 B (#1817): read and encrypted in the browser
    wk_after(sp);
    const ids = r.created || [];
    const msg = tr('{0} pages imported', ids.length) + (r.skipped?.length ? ' · ' + tr('{0} skipped', r.skipped.length) : '');
    if (!ids.length) { toast(msg); return; }
    const e = histAdd({label: tr('Import of {0} pages', ids.length), ids: [], snaps: [], lids: [], wsp: sp,
      undo: async () => { await rawFetch('POST', '/api/wiki/trash', {ids}); wk_after(sp); return {skipped: []}; },
      redo: async () => { await rawFetch('POST', '/api/wiki/restore', {ids}); wk_after(sp); return {skipped: []}; }});
    histToast(msg, e);
  };
  inp.click();
}
// ---- [[ suggestions while typing: the pages of the space whose name has what follows [[
function wk_acUpdate(ta) {
  const box = $('#wk-ac'); if (!box) return;
  const before = ta.value.slice(0, ta.selectionStart), m = /\[\[([^\[\]\n|#]{0,80})$/.exec(before);
  if (!m) { box.classList.add('hidden'); WK.ac = null; return; }
  const q = m[1].toLowerCase(), sp = WK.pg?.space || wk_cur();
  const hits = wk_pages(sp).filter(p => p.id !== WK.pg?.id && p.path.toLowerCase().includes(q)).slice(0, 8);
  if (!hits.length) { box.classList.add('hidden'); WK.ac = null; return; }
  WK.ac = {hits, i: 0, from: before.length - m[1].length};
  wk_acDraw(box);
}
function wk_acDraw(box) {
  box.innerHTML = WK.ac.hits.map((p, i) => `<button type="button" role="option" class="${i === WK.ac.i ? 'on' : ''}" aria-selected="${i === WK.ac.i}" data-wk="ac" data-i="${i}">${ic('note', 's')}<span>${esc(p.path)}</span></button>`).join('');
  box.classList.remove('hidden');
}
function wk_acPick(i) {
  const ta = $('#wk-body'), a = WK.ac; if (!ta || !a) return;
  const p = a.hits[i], end = ta.selectionStart, rest = ta.value.slice(end), close = rest.startsWith(']]') ? '' : ']]';
  ta.value = ta.value.slice(0, a.from) + p.path + close + rest;
  const pos = a.from + p.path.length + 2; ta.setSelectionRange(pos, pos); ta.focus();
  WK.ac = null; $('#wk-ac')?.classList.add('hidden'); wk_queue();
}
// ---- events (own listeners: data-wk)
document.addEventListener('click', async e => {
  const a = e.target.closest?.('[data-wk]'); if (!a || !$('#view')?.contains(a) && a.dataset.wk !== 'ac') return;
  const k = a.dataset.wk, p = WK.pg;
  if (k === 'new') { wk_new(); }
  else if (k === 'create') { e.preventDefault(); if (WK.idx[p?.space || wk_cur()]?.mayWrite !== false) wk_new(a.dataset.path); }
  else if (k === 'close' || k === 'home') { e.preventDefault(); await wk_flush(); WK.edit = false; go('wiki'); }
  else if (k === 'mode') { if (a.dataset.m === 'read') await wk_flush(); WK.edit = a.dataset.m === 'edit'; renderView(); if (WK.edit) setTimeout(() => $('#wk-body')?.focus(), 30); }
  else if (k === 'ac') { e.preventDefault(); wk_acPick(+a.dataset.i); }
  else if (k === 'menu') menu(a, [{label: tr('Export as ZIP'), icon: 'download', fn: wk_export}, ...(WK.idx[wk_cur()]?.mayWrite !== false ? [{label: tr('Import ZIP…'), icon: 'upload', fn: wk_import}] : []),
    ...(typeof wkeDlg === 'function' && S.me?.kind !== 'agent' && globalThis.crypto?.subtle ? ['-', {label: tr('Encryption…'), icon: 'lock', fn: () => wkeDlg(wk_cur())}] : [])]);  // 2.64.3 B (#1817)
  else if (k === 'pmenu' && p) menu(a, [{label: tr('Rename…'), icon: 'edit', fn: () => wk_rename(p)},
    ...(p.path.includes('/') ? [{label: tr('Rename folder…'), icon: 'folder', fn: () => wk_moveFolder(p)}] : []),
    {label: tr('Copy link'), icon: 'link', fn: () => { navigator.clipboard?.writeText(`${location.origin}${location.pathname}#wiki/${p.id}`).then(() => toast(tr('Link copied'))); }},
    {label: tr('Copy as [[link]]'), icon: 'copy', fn: () => { navigator.clipboard?.writeText(`[[${p.path}]]`).then(() => toast(tr('Link copied'))); }},
    '-', {label: tr('Delete'), icon: 'trash', cls: 'flag-5', fn: () => wk_delete(p)}]);
});
document.addEventListener('change', e => {
  if (e.target.matches?.('[data-wk-tpl]')) WK.tplPick = +e.target.value;
  if (e.target.matches?.('[data-wk="space"]')) { WK.space = e.target.value; LS.set('wkSpace', WK.space); WK.pg = null; go('wiki'); renderView(); }
});
document.addEventListener('input', e => {
  if (e.target.id === 'wk-body') { wk_queue(); wk_acUpdate(e.target); }
  else if (e.target.id === 'wk-q') { WK.q = e.target.value; const r = $('#wk-res'); if (r) { const v = document.createElement('div'); v.innerHTML = viewWiki(); const n = $('#wk-res', v); if (n) r.innerHTML = n.innerHTML; } }
});
document.addEventListener('keydown', e => {
  if (e.target.id !== 'wk-body' || !WK.ac) return;
  const box = $('#wk-ac'), n = WK.ac.hits.length;
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); WK.ac.i = (WK.ac.i + (e.key === 'ArrowDown' ? 1 : n - 1)) % n; wk_acDraw(box); }
  else if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); wk_acPick(WK.ac.i); }
  else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); WK.ac = null; box?.classList.add('hidden'); }
}, true);
document.addEventListener('focusout', e => { if (e.target.id === 'wk-body') wk_flush(); });
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
