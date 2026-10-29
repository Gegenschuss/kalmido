// @ts-check
// 2.123.0 B (#2104): read-only shares of knowledge pages (wiki.js). The page's "…" menu: "Share…" (this page) and "Share
// folder…" (the page's folder: every page in it, also later ones). The dialog (built like the list's Share dialog): People
// (only in the private space: a person with an account reads it in the app; in an organisation every member reads anyway,
// people outside get the public link) and Public link (a read-only page without an account, optional "valid until", copy,
// turn off). Shares of a folder above show as "via folder …". Every create / end is one Undo step. A space encrypted in the
// browser cannot share (hint). The mark: a small people icon at shared pages (tree + title). "Shared with me" in the side
// bar of the pages view lists what others shared with me; a page opens read-only in a dialog (links only to pages shared
// with me too). Server: kalmido/wiki/wkshare.py.
// 2.200.0 B (#2747): "Share…" opens the one Share dialog of the file store (fsshare.js) on the page's / folder's node: view or
// edit for people, groups and agents, inherited at run time; the links and older shares of this file show there as their own
// section ("Links and earlier shares": copy, turn off, a new public link). A space encrypted in the browser: the item stays,
// says why it cannot share. "Shared with me" also lists pages of shared folders by their folders (from the shared folder on);
// with 'edit' a page can be changed in the reading dialog, and new pages / folders go into the shared folder.
const WSH = {mine: /** @type {any[]|null} */ (null), folders: /** @type {any[]} */ ([]), cur: /** @type {any} */ (null), v: -1, busy: false};
/** @param {string} s @param {any} [r] @returns {any} */
const wsh$ = (s, r) => (r || document).querySelector(s);
const wsh_baseName = p => String(p || '').split('/').pop();
const wsh_dir = p => String(p.path).split('/').slice(0, -1).join('/');
const wsh_day = x => x ? ds(new Date(new Date(x).getTime() - 1000)) : '';  // stored: the start of the day after the last valid day
const wsh_markHtml = n => n ? `<span class="wshmark" title="${esc(tr('Shared|wiki'))}" aria-label="${esc(tr('Shared|wiki'))}" role="img">${ic('users', 's')}</span>` : '';
// the page's "…" menu (wiki.js)
function wsh_menuItems(p) {
  return [{label: tr('Share…|wiki'), icon: 'users', fn: () => wsh_sharePage(p)},
    ...(String(p.path).includes('/') && !String(p.path).startsWith('e2e1:') ? [{label: tr('Share folder…|wiki'), icon: 'folder', fn: () => wsh_shareFolder(p)}] : [])];
}
// 2.200.0 B (#2747): the one Share dialog on the node (fsshare.js), the links / older shares as its own section
const wsh_lockedSp = sp => typeof wk_locked === 'function' && !!wk_locked(sp);
const wsh_lockHint = () => toast(tr('This space is encrypted in the browser: the server cannot show its pages to others, so they cannot be shared.'));
/** @param {number} nodeId @param {{space: string, path: string, folder?: boolean, page_id?: number}} t */
function wkfs_share(nodeId, t) {
  if (wsh_lockedSp(t.space)) { wsh_lockHint(); return; }
  if (!nodeId) { wsh_dlg(t.folder ? {path: t.path + '/x', space: t.space} : {id: t.page_id, path: t.path, space: t.space}, !!t.folder); return; }  // no node yet (an older page): the links as before
  fs_shareDialog(nodeId, {org: false, onChange: () => { if (typeof wk_after === 'function') wk_after(t.space); },
    hint: t.space !== 'private' ? tr('Every member of the organisation reads these pages already: a share adds guests, the accounting and agents, or the right to edit.') : '',
    extra: (/** @type {any} */ box) => wsh_fill(box, t.folder ? {space: t.space, folder: t.path} : {page_id: t.page_id}, t.space, !!t.folder, true)});
}
function wsh_sharePage(p) { wkfs_share(p.node_id, {space: p.space, path: p.path, page_id: p.id}); }
async function wsh_shareFolder(p) {
  if (wsh_lockedSp(p.space)) { wsh_lockHint(); return; }
  let fid = p.folder_id || null;
  if (!fid && p.node_id) { try { fid = (await api('GET', `/api/files/nodes/${p.node_id}`)).parent_id; } catch { return; } }
  wkfs_share(fid, {space: p.space, path: wsh_dir(p), folder: true});
}
// the button next to the page's title (wiki.js wk_pageHtml)
const wsh_btnHtml = p => p && !S.me?.kid ? `<button type="button" class="iconbtn" data-wsh-share="${p.id}" title="${esc(tr('Share…|wiki'))}" aria-label="${esc(tr('Share…|wiki'))}">${ic(wsh_lockedSp(p.space) ? 'lock' : 'users')}</button>` : '';
document.addEventListener('click', ev => {
  const b = /** @type {any} */ (ev.target).closest?.('[data-wsh-share]'); if (!b) return;
  const p = typeof WK !== 'undefined' && WK.pg?.id === +b.dataset.wshShare ? WK.pg : null; if (p) wsh_sharePage(p);
});
// ---- the dialog
function wsh_dlg(p, folder) {
  const target = folder ? wsh_dir(p) : p.path, sp = p.space;
  const title = folder ? tr('Share folder “{0}”|wiki', wsh_baseName(target)) : tr('Share “{0}”|wiki', wsh_baseName(p.path));
  const md = modal(`<div class="lhdr"><h3>${esc(title)}</h3><span class="spacer"></span><button class="iconbtn" data-m="close" aria-label="${esc(tr('Close'))}" title="${esc(tr('Close'))}">${ic('x')}</button></div>
    <div class="shint lhint keep">${esc(folder ? tr('Read only: every page in this folder, also pages added later.') : tr('Read only: only this page.'))}</div>
    <div class="wshbox"></div>
    <div class="foot"><span class="spacer"></span><button class="btn pri" data-m="close">${tr('Done')}</button></div>`);
  md.classList.add('shmodal', 'wshmodal');
  md.addEventListener('click', ev => { if (/** @type {any} */ (ev.target).closest('[data-m="close"]')) md.remove(); });
  wsh_fill(wsh$('.wshbox', md), folder ? {space: sp, folder: target} : {page_id: p.id}, sp, folder, false);
  return md;
}
// 2.200.0 B (#2747): the links and person shares of a page / folder into box -- in the old dialog (above) or as the section
// "Links and earlier shares" of the one Share dialog (legacy: no new person share there, people come through the dialog)
function wsh_fill(md, tgt, sp, folder, legacy) {
  const q = tgt.page_id ? `page=${tgt.page_id}` : `space=${encodeURIComponent(sp)}&folder=${encodeURIComponent(tgt.folder)}`;
  md.innerHTML = `${legacy ? `<h4 class="wshleg">${ic('link', 's')} ${tr('Links and earlier shares')}</h4>` : ''}<div class="wsh-body"><div class="muted mhint">${tr('Loading…')}</div></div><div class="calerr" role="alert" data-wsh-err hidden></div>`;
  /** @type {any} */ let j = null;
  /** @type {any[]|null} */ let users = null;
  const show = m => { const x = wsh$('[data-wsh-err]', md); if (x) { x.textContent = m || ''; x.hidden = !m; } };
  const via = s => s.direct ? '' : `<small class="muted">${esc(tr('via folder “{0}”', wsh_baseName(s.path)))}</small>`;
  // 2.126.2 B (#2358): a public link whose maker left the organisation does not work any more -- shown like an expired one
  // 2.380 H (#2356): a share that shows the file store pictures embedded in the page says so; a direct one switches it here
  const img = s => (s.images ? ` · ${esc(tr('Pictures shown'))}` : '') + (s.direct && !s.ended ? ` <button type="button" class="btn sm" data-wsh="img" data-id="${s.id}" aria-pressed="${!!s.images}">${esc(s.images ? tr('Hide pictures') : tr('Show pictures'))}</button>` : '');
  const exp = s => s.ended ? `<span class="calerr">${tr('Ended')}</span> · ${esc(tr('Its creator is no longer in the organisation'))}` : s.expired ? `<span class="calerr">${tr('Expired')}</span>` : s.expires_at ? esc(tr('valid until {0}', fmtDate(wsh_day(s.expires_at)))) : '';
  const draw = () => {
    const box = wsh$('.wsh-body', md); if (!box || !j) return;
    if (j.locked) { box.innerHTML = `<div class="shint keep" role="note">${ic('lock', 's')} ${esc(tr('This space is encrypted in the browser: the server cannot show its pages to others, so they cannot be shared.'))}</div>`; return; }
    const ppl = j.shares.filter(s => s.kind === 'person'), links = j.shares.filter(s => s.kind === 'link');
    const cand = legacy ? [] : (users || []).filter(u => !ppl.some(s => s.direct && s.user?.id === u.id));  // 2.200.0 B (#2747): people are chosen above, by e-mail address here
    const people = j.person ? `<div class="members" id="wsh-ppl" aria-labelledby="wsh-ppl-h">${ppl.length ? ppl.map(s => `<div class="mrow"><span class="n"><b>${esc(s.user?.name || '?')}</b>${via(s)}<small class="muted">${tr('Read only')}${exp(s) ? ' · ' + exp(s) : ''}${img(s)}</small></span>${s.direct ? `<button type="button" class="iconbtn" data-wsh="end" data-id="${s.id}" aria-label="${esc(tr('Stop sharing with {0}|wiki', s.user?.name || '?'))}" title="${esc(tr('Stop sharing|wiki'))}">${ic('x', 's')}</button>` : ''}</div>`).join('') : `<div class="muted mhint">${tr('Not shared with anyone yet.')}</div>`}</div>
      <div class="row shmail">${cand.length ? `<select id="wsh-user" aria-label="${esc(tr('Person'))}"><option value="">${tr('Choose a person…')}</option>${cand.map(u => `<option value="${u.id}">${esc(u.display_name || u.username || '?')}</option>`).join('')}</select>` : ''}<input id="wsh-email" type="email" autocomplete="off" placeholder="${esc(tr('Share by e-mail address'))}" aria-label="${esc(tr('Share by e-mail address'))}"><button type="button" class="btn sm" data-wsh="person">${ic('plus', 's')} ${tr('Add')}</button></div>`
      : legacy ? '' : `<div class="shint keep">${esc(tr('Every member of the organisation reads these pages already. For people outside it, use a public link.'))}</div>`;
    const pub = !j.enabled ? `<div class="shint keep">${esc(tr('Public links are turned off on this server'))}</div>`
      : `${links.map(s => `<div class="wshlink"><div class="row icalrow"><input readonly value="${esc(s.url)}" data-wsh-url="${s.id}" aria-label="${esc(tr('Public link'))}"><button type="button" class="btn sm pri" data-wsh="copy" data-id="${s.id}"${s.ended ? ' disabled' : ''}>${ic('copy', 's')} ${tr('Copy')}</button></div>
          <div class="shint">${via(s)}${exp(s) ? exp(s) + ' · ' : ''}${esc(trn('opened {0} time', 'opened {0} times', s.views))}${s.last_used_at ? ' · ' + esc(tr('last {0}', relTime(s.last_used_at))) : ''}${img(s)}${s.direct ? ` <button type="button" class="btn sm danger" data-wsh="end" data-id="${s.id}">${tr('Turn off')}</button>` : ''}</div></div>`).join('')}
        ${links.length ? '' : `<div class="shint keep">${esc(tr('People without an account can read it through a secret link: only what you share here, nothing else of your pages.'))}</div>`}
        <div class="row"><label for="wsh-exp">${tr('Valid until')}</label>${dateIn('wsh-exp', '', {min: today(), label: tr('Valid until'), empty: tr('no expiry')})}</div>
        <div class="row"><button type="button" class="btn sm${links.some(s => s.direct && !s.ended) ? '' : ' pri'}" data-wsh="link">${ic('link', 's')} ${tr(links.some(s => s.direct && !s.ended) ? N_('Another public link') : N_('Create public link'))}</button></div>`;
    // 2.380 H (#2356): new shares show the pictures of the file store embedded in the page only with this switch (default off)
    const imgRow = `<div class="row"><label for="wsh-img">${tr('Show embedded pictures')}</label><label class="swc"><input type="checkbox" id="wsh-img"><span class="swt" aria-hidden="true"></span><span class="sr">${esc(tr('Show embedded pictures'))}</span></label></div><div class="shint">${esc(tr('Only pictures from the file store that are embedded in the page and that you may see. Other files stay hidden.'))}</div>`;
    box.innerHTML = (people ? `<h4 id="wsh-ppl-h">${tr(legacy ? 'Read only by e-mail address' : 'People')}</h4>${people}` : '') + `<h4>${tr('Public link')}</h4><div id="wsh-pub">${pub}</div>` + imgRow;
  };
  const load = async () => {
    try { j = await calReq('GET', '/api/wiki/shares?' + q); } catch (x) { const b = wsh$('.wsh-body', md); if (b) b.innerHTML = `<div class="muted mhint">${esc(x.status === 404 ? tr('No links yet: a public link can be made once the folder holds a page.') : x.message)}</div>`; return; }
    if (j.person && !legacy && users === null) { users = []; try { users = (await api('GET', '/api/users')).users.filter(u => !u.disabled && !u.agent && u.id !== S.me?.id); } catch { /* offline: by e-mail address */ } }
    draw();
  };
  const changed = () => { if (typeof wk_after === 'function') wk_after(sp); return load(); };
  const step = (label, id, created) => {  // one Undo step: create <-> end
    const end = () => rawFetch('DELETE', `/api/wiki/shares/${id}`), back = () => rawFetch('POST', `/api/wiki/shares/${id}/restore`);
    const e = histAdd({label, ids: [], snaps: [], lids: [], wsp: sp,
      undo: async () => { await (created ? end() : back()); if (md.isConnected) await changed(); else if (typeof wk_after === 'function') wk_after(sp); return {skipped: []}; },
      redo: async () => { await (created ? back() : end()); if (md.isConnected) await changed(); else if (typeof wk_after === 'function') wk_after(sp); return {skipped: []}; }});
    histToast(label, e);
  };
  md.addEventListener('click', async ev => {
    const t = /** @type {any} */ (ev.target);
    const b = t.closest('[data-wsh]'); if (!b) return;
    const a = b.dataset.wsh; show('');
    if (a === 'copy') { const i = wsh$(`[data-wsh-url="${b.dataset.id}"]`, md); try { await navigator.clipboard.writeText(i.value); toast(tr('Link copied')); } catch { i.focus(); i.select(); toast(tr('Copy the selected link')); } return; }
    const exp = wsh$('#wsh-exp', md)?.value || null, images = !!wsh$('#wsh-img', md)?.checked;
    b.disabled = true;
    try {
      if (a === 'link') {
        const s = await calReq('POST', '/api/wiki/shares', {...tgt, kind: 'link', expires: exp, images});
        await changed(); step(tr('Public link created'), s.id, true);
        try { await navigator.clipboard.writeText(s.url); toast(tr('Link copied')); } catch { /* the field shows it */ }
      } else if (a === 'person') {
        const uid = +(wsh$('#wsh-user', md)?.value || 0), em = (wsh$('#wsh-email', md)?.value || '').trim();
        if (!uid && !em) { show(tr('Choose a person or type an e-mail address')); return; }
        const s = await calReq('POST', '/api/wiki/shares', {...tgt, kind: 'person', ...(uid ? {user_id: uid} : {email: em}), expires: exp, images});
        if (s.by_email) toast(tr('If an account has this address, it can read the page now.'));
        else { step(tr('Shared with {0}|wiki', s.user?.name || '?'), s.id, true); }
        await changed();
      } else if (a === 'img') {  // 2.380 H (#2356)
        const s = j.shares.find(x => x.id === +b.dataset.id); if (!s) return;
        await calReq('PATCH', `/api/wiki/shares/${s.id}`, {images: !s.images});
        await changed();
      } else if (a === 'end') {
        const s = j.shares.find(x => x.id === +b.dataset.id); if (!s) return;
        if (s.kind === 'link' && !await askConfirm(tr('Turn the public link off?'), tr('It stops working at once.'), {ok: tr('Turn off'), danger: true})) return;
        await calReq('DELETE', `/api/wiki/shares/${s.id}`);
        await changed(); step(s.kind === 'link' ? tr('Public link turned off') : tr('Stopped sharing with {0}', s.user?.name || '?'), s.id, false);
      }
    } catch (x) { show(x.message); } finally { b.disabled = false; }
  });
  load();
}
// ---- "Shared with me" (side bar of the pages view) and the read-only page
async function wsh_loadMine() {
  if (WSH.busy) return;
  WSH.busy = true;
  try { const j = await rawFetch('GET', '/api/wiki/shared'); WSH.mine = j.pages || []; WSH.folders = j.folders || []; } catch { WSH.mine = WSH.mine || []; } finally { WSH.v = S.v; WSH.busy = false; }
  if (S.route.mod === 'wiki' && (WSH.mine.length || WSH.folders.length)) viewSafeRender();
  wsh_focus();
}
// 2.126.2 B (#2355): the News item "… shared … with you" (collab.js) opens the pages view on "Shared with me"
function wsh_focus() {
  if (!S.wshFocus || S.route.mod !== 'wiki' || WSH.busy || WSH.v !== S.v) return;
  S.wshFocus = false;
  requestAnimationFrame(() => { const h = document.getElementById('wsh-side-h'); if (h) { h.scrollIntoView({block: 'center', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'}); h.closest('section')?.querySelector('a')?.focus({preventScroll: true}); } else toast(tr('Nothing is shared with you at the moment.')); });
}
function wsh_sideHtml() {
  if (WSH.v !== S.v) wsh_loadMine(); else if (S.wshFocus) wsh_focus();
  const pg = WSH.mine || [], fs = WSH.folders || []; if (!pg.length && !fs.length) return '';
  const item = x => `<li><a href="#" class="wkitem" data-wsh-open="${x.id}">${ic('note', 's')}<span>${esc(x.folder_id ? wsh_baseName(x.path) : x.path)}</span>${x.role === 'edit' ? `<small class="muted">${tr('Can edit')}</small>` : ''}<small class="muted">${esc(x.owner_name || (x.space !== 'private' && typeof wsName === 'function' ? wsName(x.space) : ''))}</small></a></li>`;
  // 2.200.0 B (#2747): shared folders with their subfolders (from the shared folder on), the pages in each; 'edit' adds there
  const fold = f => `<li class="wshfold"><div class="wkitem wshfh">${ic('folder', 's')}<span>${esc(f.name)}</span>${f.parent_id ? '' : `<small class="muted">${esc(f.owner_name || (f.space !== 'private' && typeof wsName === 'function' ? wsName(f.space) : ''))}</small>`}${f.role === 'edit' ? `<button type="button" class="iconbtn" data-wsh-new="${f.id}" title="${esc(tr('New page'))}" aria-label="${esc(tr('New page') + ': ' + f.name)}">${ic('plus', 's')}</button><button type="button" class="iconbtn" data-wsh-newf="${f.id}" title="${esc(tr('New folder'))}" aria-label="${esc(tr('New folder') + ': ' + f.name)}">${ic('folder', 's')}</button>` : ''}</div>`
    + `<ul class="wktree">${fs.filter(x => x.parent_id === f.id).map(fold).join('')}${pg.filter(x => x.folder_id === f.id).map(item).join('')}</ul></li>`;
  const known = new Set(fs.map(f => f.id));
  return `<section class="wshside" aria-labelledby="wsh-side-h"><h4 id="wsh-side-h">${ic('users', 's')}${tr('Shared with me')}</h4><ul class="wktree">${fs.filter(f => !f.parent_id).map(fold).join('')}${pg.filter(x => !x.folder_id || !known.has(x.folder_id)).map(item).join('')}</ul></section>`;
}
async function wsh_newIn(fid, folder) {
  const v = await askDialog({title: tr(folder ? 'New folder' : 'New page'), input: {value: '', placeholder: tr(folder ? 'Folder name' : 'Page name'), max: 150}, ok: tr('Create'), cancel: undefined, after: undefined});
  if (!v || !String(v).trim()) return;
  try {
    const r = await calReq('POST', folder ? '/api/wiki/shared/folders' : '/api/wiki/shared/pages', folder ? {parent_id: fid, name: String(v).trim()} : {folder_id: fid, name: String(v).trim(), body: ''});
    WSH.v = -1; await wsh_loadMine();
    if (!folder) wsh_read(r.id);
  } catch (x) { toast(x.message); }
}
document.addEventListener('click', ev => {
  const b = /** @type {any} */ (ev.target).closest?.('[data-wsh-new], [data-wsh-newf]'); if (!b) return;
  ev.preventDefault(); wsh_newIn(+(b.dataset.wshNew || b.dataset.wshNewf), !!b.dataset.wshNewf);
});
async function wsh_read(id, md) {
  let p;
  try { p = await calReq('GET', '/api/wiki/shared/pages/' + id); } catch (x) { toast(x.status === 404 ? tr('This page does not exist or you cannot see it.') : x.message); return; }
  const inner = `<div class="lhdr"><h3>${esc(wsh_baseName(p.path))}</h3><span class="spacer"></span><button class="iconbtn" data-m="close" aria-label="${esc(tr('Close'))}" title="${esc(tr('Close'))}">${ic('x')}</button></div>
    <div class="shint keep">${esc(p.role === 'edit' ? tr('Shared with you · you can edit it') : tr('Shared by {0} · read only', p.owner_name || '?'))} · ${esc(p.path)}</div>
    <div class="md ntmd wkmd wshmd">${p.html || `<p class="muted">${tr('Empty page.')}</p>`}</div>
    ${p.files?.length ? `<section class="wkfiles" aria-label="${esc(tr('Files'))}"><h4>${ic('file', 's')}${tr('Files')} · ${p.files.length}</h4><ul>${p.files.map(f => `<li><a class="wkfile" href="${esc(f.url)}" target="_blank" rel="noopener" title="${esc(f.name)}">${f.image ? `<img src="${esc(f.url)}" alt="" loading="lazy">` : ic('pdf')}<span class="an">${esc(f.name)}</span><span class="as">${fmtSize(f.size)}</span></a></li>`).join('')}</ul></section>` : ''}
    <div class="ntfoot muted">${p.role === 'edit' ? `<button type="button" class="btn sm" data-wsh-edit="${p.id}">${ic('edit', 's')} ${tr('Edit')}</button>` : ''}<span class="spacer"></span><span>${esc(tr('Changed {0}', fmtWhen(p.updated_at)))}${p.updated_by_name ? ' · ' + esc(p.updated_by_name) : ''}</span></div>`;
  WSH.cur = p;
  if (/<pre data-lang="(?:math|mermaid)"/.test(p.html || '')) loadModule('diagram').then(() => dg_draw(), () => {});  // 2.382.0 (#3153)
  if (md && md.isConnected) { md.querySelector('.card').innerHTML = inner; return; }
  const m = modal(inner);
  m.classList.add('wshread');
  m.addEventListener('click', async ev => {
    const t = /** @type {any} */ (ev.target);
    if (t.closest('[data-m="close"]')) { m.remove(); return; }
    if (t.closest('[data-wsh-edit]')) { wsh_editIn(m, WSH.cur); return; }  // 2.200.0 B (#2747): an edit share
    const sv = t.closest('[data-wsh-save]');
    if (sv) {
      const c = WSH.cur, ta = /** @type {any} */ (m.querySelector('#wsh-ed')); if (!c || !ta) return;
      sv.disabled = true;
      try { await calReq('PATCH', `/api/wiki/pages/${c.id}`, {body: ta.value, expect_updated_at: c.updated_at}); toast(tr('Saved')); WSH.v = -1; wsh_read(c.id, m); }
      catch (x) { sv.disabled = false; toast(x.message); }
      return;
    }
    if (t.closest('[data-wsh-cancel]')) { if (WSH.cur) wsh_read(WSH.cur.id, m); return; }
    const a = t.closest('a[href^="#wsh/"]');
    if (a) { ev.preventDefault(); wsh_read(+a.getAttribute('href').slice(5), m); }
  });
}
// 2.200.0 B (#2747): the text of a page shared with 'edit' (Markdown, saved as a whole; someone else saving meanwhile = 409)
function wsh_editIn(m, p) {
  if (!p) return;
  m.querySelector('.card').innerHTML = `<div class="lhdr"><h3>${esc(wsh_baseName(p.path))}</h3><span class="spacer"></span><button class="iconbtn" data-m="close" aria-label="${esc(tr('Close'))}" title="${esc(tr('Close'))}">${ic('x')}</button></div>
    <textarea id="wsh-ed" class="wshed" rows="16" aria-label="${esc(tr('Text'))}">${esc(p.body || '')}</textarea>
    <div class="foot"><button type="button" class="btn" data-wsh-cancel="1">${tr('Cancel')}</button><span class="spacer"></span><button type="button" class="btn pri" data-wsh-save="1">${tr('Save')}</button></div>`;
  m.querySelector('#wsh-ed')?.focus();
}
document.addEventListener('click', ev => {
  const a = /** @type {any} */ (ev.target).closest?.('[data-wsh-open]'); if (!a) return;
  ev.preventDefault(); wsh_read(+a.dataset.wshOpen);
});
