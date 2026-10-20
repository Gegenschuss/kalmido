// @ts-check
// 2.123.0 B (#2104): read-only shares of knowledge pages (wiki.js). The page's "…" menu: "Share…" (this page) and "Share
// folder…" (the page's folder: every page in it, also later ones). The dialog (built like the list's Share dialog): People
// (only in the private space: a person with an account reads it in the app; in an organisation every member reads anyway,
// people outside get the public link) and Public link (a read-only page without an account, optional "valid until", copy,
// turn off). Shares of a folder above show as "via folder …". Every create / end is one Undo step. A space encrypted in the
// browser cannot share (hint). The mark: a small people icon at shared pages (tree + title). "Shared with me" in the side
// bar of the pages view lists what others shared with me; a page opens read-only in a dialog (links only to pages shared
// with me too). Server: kalmido/wiki/wkshare.py.
const WSH = {mine: /** @type {any[]|null} */ (null), v: -1, busy: false};
/** @param {string} s @param {any} [r] @returns {any} */
const wsh$ = (s, r) => (r || document).querySelector(s);
const wsh_baseName = p => String(p || '').split('/').pop();
const wsh_dir = p => String(p.path).split('/').slice(0, -1).join('/');
const wsh_day = x => x ? ds(new Date(new Date(x).getTime() - 1000)) : '';  // stored: the start of the day after the last valid day
const wsh_markHtml = n => n ? `<span class="wshmark" title="${esc(tr('Shared|wiki'))}" aria-label="${esc(tr('Shared|wiki'))}" role="img">${ic('users', 's')}</span>` : '';
// the page's "…" menu (wiki.js)
function wsh_menuItems(p) {
  return [{label: tr('Share…|wiki'), icon: 'users', fn: () => wsh_dlg(p, false)},
    ...(String(p.path).includes('/') && !String(p.path).startsWith('e2e1:') ? [{label: tr('Share folder…|wiki'), icon: 'folder', fn: () => wsh_dlg(p, true)}] : [])];
}
// ---- the dialog
function wsh_dlg(p, folder) {
  const target = folder ? wsh_dir(p) : p.path, sp = p.space;
  const q = folder ? `space=${encodeURIComponent(sp)}&folder=${encodeURIComponent(target)}` : `page=${p.id}`;
  const title = folder ? tr('Share folder “{0}”|wiki', wsh_baseName(target)) : tr('Share “{0}”|wiki', wsh_baseName(p.path));
  const md = modal(`<div class="lhdr"><h3>${esc(title)}</h3><span class="spacer"></span><button class="iconbtn" data-m="close" aria-label="${esc(tr('Close'))}" title="${esc(tr('Close'))}">${ic('x')}</button></div>
    <div class="shint lhint keep">${esc(folder ? tr('Read only: every page in this folder, also pages added later.') : tr('Read only: only this page.'))}</div>
    <div id="wsh-body"><div class="muted mhint">${tr('Loading…')}</div></div>
    <div class="calerr" role="alert" id="wsh-err" hidden></div>
    <div class="foot"><span class="spacer"></span><button class="btn pri" data-m="close">${tr('Done')}</button></div>`);
  md.classList.add('shmodal', 'wshmodal');
  /** @type {any} */ let j = null;
  /** @type {any[]|null} */ let users = null;
  const show = m => { const x = wsh$('#wsh-err', md); if (x) { x.textContent = m || ''; x.hidden = !m; } };
  const via = s => s.direct ? '' : `<small class="muted">${esc(tr('via folder “{0}”', wsh_baseName(s.path)))}</small>`;
  const exp = s => s.expired ? `<span class="calerr">${tr('Expired')}</span>` : s.expires_at ? esc(tr('valid until {0}', fmtDate(wsh_day(s.expires_at)))) : '';
  const draw = () => {
    const box = wsh$('#wsh-body', md); if (!box || !j) return;
    if (j.locked) { box.innerHTML = `<div class="shint keep" role="note">${ic('lock', 's')} ${esc(tr('This space is encrypted in the browser: the server cannot show its pages to others, so they cannot be shared.'))}</div>`; return; }
    const ppl = j.shares.filter(s => s.kind === 'person'), links = j.shares.filter(s => s.kind === 'link');
    const cand = (users || []).filter(u => !ppl.some(s => s.direct && s.user?.id === u.id));
    const people = j.person ? `<div class="members" id="wsh-ppl" aria-labelledby="wsh-ppl-h">${ppl.length ? ppl.map(s => `<div class="mrow"><span class="n"><b>${esc(s.user?.name || '?')}</b>${via(s)}<small class="muted">${tr('Read only')}${exp(s) ? ' · ' + exp(s) : ''}</small></span>${s.direct ? `<button type="button" class="iconbtn" data-wsh="end" data-id="${s.id}" aria-label="${esc(tr('Stop sharing with {0}|wiki', s.user?.name || '?'))}" title="${esc(tr('Stop sharing|wiki'))}">${ic('x', 's')}</button>` : ''}</div>`).join('') : `<div class="muted mhint">${tr('Not shared with anyone yet.')}</div>`}</div>
      <div class="row shmail">${cand.length ? `<select id="wsh-user" aria-label="${esc(tr('Person'))}"><option value="">${tr('Choose a person…')}</option>${cand.map(u => `<option value="${u.id}">${esc(u.display_name || u.username || '?')}</option>`).join('')}</select>` : ''}<input id="wsh-email" type="email" autocomplete="off" placeholder="${esc(tr('Share by e-mail address'))}" aria-label="${esc(tr('Share by e-mail address'))}"><button type="button" class="btn sm" data-wsh="person">${ic('plus', 's')} ${tr('Add')}</button></div>`
      : `<div class="shint keep">${esc(tr('Every member of the organisation reads these pages already. For people outside it, use a public link.'))}</div>`;
    const pub = !j.enabled ? `<div class="shint keep">${esc(tr('Public links are turned off on this server'))}</div>`
      : `${links.map(s => `<div class="wshlink"><div class="row icalrow"><input readonly value="${esc(s.url)}" data-wsh-url="${s.id}" aria-label="${esc(tr('Public link'))}"><button type="button" class="btn sm pri" data-wsh="copy" data-id="${s.id}">${ic('copy', 's')} ${tr('Copy')}</button></div>
          <div class="shint">${via(s)}${exp(s) ? exp(s) + ' · ' : ''}${esc(trn('opened {0} time', 'opened {0} times', s.views))}${s.last_used_at ? ' · ' + esc(tr('last {0}', relTime(s.last_used_at))) : ''}${s.direct ? ` <button type="button" class="btn sm danger" data-wsh="end" data-id="${s.id}">${tr('Turn off')}</button>` : ''}</div></div>`).join('')}
        ${links.length ? '' : `<div class="shint keep">${esc(tr('People without an account can read it through a secret link: only what you share here, nothing else of your pages.'))}</div>`}
        <div class="row"><label for="wsh-exp">${tr('Valid until')}</label>${dateIn('wsh-exp', '', {min: today(), label: tr('Valid until'), empty: tr('no expiry')})}</div>
        <div class="row"><button type="button" class="btn sm${links.some(s => s.direct) ? '' : ' pri'}" data-wsh="link">${ic('link', 's')} ${tr(links.some(s => s.direct) ? N_('Another public link') : N_('Create public link'))}</button></div>`;
    box.innerHTML = `<h4 id="wsh-ppl-h">${tr('People')}</h4>${people}<h4>${tr('Public link')}</h4><div id="wsh-pub">${pub}</div>`;
  };
  const load = async () => {
    try { j = await calReq('GET', '/api/wiki/shares?' + q); } catch (x) { const b = wsh$('#wsh-body', md); if (b) b.innerHTML = `<div class="muted mhint">${esc(x.message)}</div>`; return; }
    if (j.person && users === null) { users = []; try { users = (await api('GET', '/api/users')).users.filter(u => !u.disabled && !u.agent && u.id !== S.me?.id); } catch { /* offline: by e-mail address */ } }
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
    if (t.closest('[data-m="close"]')) { md.remove(); return; }
    const b = t.closest('[data-wsh]'); if (!b) return;
    const a = b.dataset.wsh; show('');
    if (a === 'copy') { const i = wsh$(`[data-wsh-url="${b.dataset.id}"]`, md); try { await navigator.clipboard.writeText(i.value); toast(tr('Link copied')); } catch { i.focus(); i.select(); toast(tr('Copy the selected link')); } return; }
    const exp = wsh$('#wsh-exp', md)?.value || null;
    const tgt = folder ? {space: sp, folder: target} : {page_id: p.id};
    b.disabled = true;
    try {
      if (a === 'link') {
        const s = await calReq('POST', '/api/wiki/shares', {...tgt, kind: 'link', expires: exp});
        await changed(); step(tr('Public link created'), s.id, true);
        try { await navigator.clipboard.writeText(s.url); toast(tr('Link copied')); } catch { /* the field shows it */ }
      } else if (a === 'person') {
        const uid = +(wsh$('#wsh-user', md)?.value || 0), em = (wsh$('#wsh-email', md)?.value || '').trim();
        if (!uid && !em) { show(tr('Choose a person or type an e-mail address')); return; }
        const s = await calReq('POST', '/api/wiki/shares', {...tgt, kind: 'person', ...(uid ? {user_id: uid} : {email: em}), expires: exp});
        if (s.by_email) toast(tr('If an account has this address, it can read the page now.'));
        else { step(tr('Shared with {0}|wiki', s.user?.name || '?'), s.id, true); }
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
  return md;
}
// ---- "Shared with me" (side bar of the pages view) and the read-only page
async function wsh_loadMine() {
  if (WSH.busy) return;
  WSH.busy = true;
  try { WSH.mine = (await rawFetch('GET', '/api/wiki/shared')).pages || []; } catch { WSH.mine = WSH.mine || []; } finally { WSH.v = S.v; WSH.busy = false; }
  if (S.route.mod === 'wiki' && WSH.mine.length) viewSafeRender();
}
function wsh_sideHtml() {
  if (WSH.v !== S.v) wsh_loadMine();
  const pg = WSH.mine || []; if (!pg.length) return '';
  return `<section class="wshside" aria-labelledby="wsh-side-h"><h4 id="wsh-side-h">${ic('users', 's')}${tr('Shared with me')}</h4><ul class="wktree">${pg.map(x => `<li><a href="#" class="wkitem" data-wsh-open="${x.id}">${ic('note', 's')}<span>${esc(x.path)}</span><small class="muted">${esc(x.owner_name)}</small></a></li>`).join('')}</ul></section>`;
}
async function wsh_read(id, md) {
  let p;
  try { p = await calReq('GET', '/api/wiki/shared/pages/' + id); } catch (x) { toast(x.status === 404 ? tr('This page does not exist or you cannot see it.') : x.message); return; }
  const inner = `<div class="lhdr"><h3>${esc(wsh_baseName(p.path))}</h3><span class="spacer"></span><button class="iconbtn" data-m="close" aria-label="${esc(tr('Close'))}" title="${esc(tr('Close'))}">${ic('x')}</button></div>
    <div class="shint keep">${esc(tr('Shared by {0} · read only', p.owner_name || '?'))} · ${esc(p.path)}</div>
    <div class="md ntmd wkmd wshmd">${p.html || `<p class="muted">${tr('Empty page.')}</p>`}</div>
    ${p.files?.length ? `<section class="wkfiles" aria-label="${esc(tr('Files'))}"><h4>${ic('file', 's')}${tr('Files')} · ${p.files.length}</h4><ul>${p.files.map(f => `<li><a class="wkfile" href="${esc(f.url)}" target="_blank" rel="noopener" title="${esc(f.name)}">${f.image ? `<img src="${esc(f.url)}" alt="" loading="lazy">` : ic('pdf')}<span class="an">${esc(f.name)}</span><span class="as">${fmtSize(f.size)}</span></a></li>`).join('')}</ul></section>` : ''}
    <div class="ntfoot muted"><span class="spacer"></span><span>${esc(tr('Changed {0}', fmtWhen(p.updated_at)))}${p.updated_by_name ? ' · ' + esc(p.updated_by_name) : ''}</span></div>`;
  if (md && md.isConnected) { md.querySelector('.card').innerHTML = inner; return; }
  const m = modal(inner);
  m.classList.add('wshread');
  m.addEventListener('click', ev => {
    const t = /** @type {any} */ (ev.target);
    if (t.closest('[data-m="close"]')) { m.remove(); return; }
    const a = t.closest('a[href^="#wsh/"]');
    if (a) { ev.preventDefault(); wsh_read(+a.getAttribute('href').slice(5), m); }
  });
}
document.addEventListener('click', ev => {
  const a = /** @type {any} */ (ev.target).closest?.('[data-wsh-open]'); if (!a) return;
  ev.preventDefault(); wsh_read(+a.dataset.wshOpen);
});
