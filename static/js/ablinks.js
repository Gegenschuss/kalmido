// @ts-check
/* Kalmido web client: external share links of the file store (2.112.1 B, #2058). The section "Link for external people" in
   the details of a file / folder (its owners only), the dialog that makes a link (expiry, optional password and label), the
   list of links with copy / new address / revoke (each one undo step), the badge of a row with a live link, the history
   lines of views / downloads through a link, and the organisation's switch in Settings > Workspaces (its admins decide).
   The page people open is server-rendered without scripts (kalmido/files/extlinks.py).
   Classic script sharing the global scope with the others (load order: index.html; after ablage.js and photometa.js). */
'use strict';

Object.assign(AB_ACT, {ext_view: N_('opened it through the link'), ext_download: N_('downloaded it through the link'),
  ext_link: N_('created a link for external people'), ext_unlink: N_('revoked a link for external people')});
// the "who" of a history line written by the page (nobody signed in): the link's label
const xl_logWho = x => x.action === 'ext_view' || x.action === 'ext_download' ? (x.detail ? tr('External link “{0}”', x.detail) : tr('External link')) : '';
const xl_badge = n => n.xl ? `<span class="abbadge" title="${esc(tr('Shared through an external link'))}" aria-label="${esc(tr('Shared through an external link'))}">${ic('link', 's')}</span>` : '';
const xl_menuItem = n => n.role === 'owner' && (n.kind === 'file' || n.kind === 'folder') && !n.agent_id
  ? {label: tr('Link for external people…'), icon: 'link', fn: () => xl_newDlg(n.id)} : null;

// ---- the section in the details (after "Shared with"); md = the details dialog, n = the node
async function xl_mount(md, n) {
  if (n.role !== 'owner' || (n.kind !== 'file' && n.kind !== 'folder') || n.in_trash) return;
  const anchor = $('[data-abd="share"]', md)?.closest('.row'); if (!anchor) return;
  /** @type {any} */
  const box = document.createElement('div');
  box.className = 'xl-sec';
  box.innerHTML = `<h4>${tr('Link for external people')}</h4><div class="xl-links"><span class="muted">${tr('Loading…')}</span></div>`;
  anchor.after(box);
  let j; try { j = await api('GET', `/api/files/nodes/${n.id}/ext-links`); } catch { box.remove(); return; }
  xl_draw(box, n, j);
  box.addEventListener('click', e => xl_click(e, box, n));
}
function xl_rowHtml(l) {
  const meta = [l.expired ? tr('Expired') : l.expires_at ? tr('until {0}', ab_when(l.expires_at)) : tr('No end date'),
    trn('{0} view', '{0} views', l.views || 0), l.last_seen_at ? tr('last opened {0}', ab_when(l.last_seen_at)) : '',
    l.has_password ? tr('Password') : '', l.by && l.created_by !== S.me?.id ? l.by : ''].filter(Boolean).join(' · ');
  return `<div class="xl-row${l.expired ? ' xl-dead' : ''}" data-xlid="${l.id}">${ic(l.has_password ? 'lock' : 'link', 's')}<span class="xl-main"><span class="xl-name">${esc(l.label || tr('Link'))}</span><small class="muted">${esc(meta)}</small></span>
    <button type="button" class="iconbtn" data-xl="copy" title="${esc(tr('Copy'))}" aria-label="${esc(tr('Copy the link {0}', l.label || ''))}">${ic('copy', 's')}</button>
    <button type="button" class="iconbtn" data-xl="regen" title="${esc(tr('New link'))}" aria-label="${esc(tr('New link'))}">${ic('key', 's')}</button>
    <button type="button" class="iconbtn" data-xl="revoke" title="${esc(tr('Revoke'))}" aria-label="${esc(tr('Revoke'))}">${ic('x', 's')}</button></div>`;
}
function xl_draw(box, n, j) {
  if (!box.isConnected) return;
  box._j = j;
  const links = j.links || [];
  $('.xl-links', box).innerHTML = (j.blocked ? `<div class="muted xl-why">${esc(j.blocked)}</div>` : '')
    + links.map(xl_rowHtml).join('')
    + (!links.length && !j.blocked ? `<div class="muted">${tr('People without an account can open and download it through a secret link.')}</div>` : '')
    + (j.blocked ? '' : `<div class="row"><button type="button" class="btn sm" data-xl="new">${ic('link', 's')} ${tr('Create link')}</button></div>`);
}
async function xl_reload(box, n) { try { xl_draw(box, n, await api('GET', `/api/files/nodes/${n.id}/ext-links`)); } catch { /* shown */ } ab_reload(); return {}; }
async function xl_copy(url) {
  try { await navigator.clipboard.writeText(url); toast(tr('Link copied')); } catch { await askPrompt(tr('Copy the selected link'), url); }
}
async function xl_click(e, box, n) {
  const b = /** @type {any} */ (e.target).closest('[data-xl]'); if (!b) return;
  const a = b.dataset.xl, id = +b.closest('[data-xlid]')?.dataset.xlid, l = (box._j?.links || []).find(x => x.id === id);
  if (a === 'new') { xl_newDlg(n.id, () => xl_reload(box, n)); return; }
  if (!l) return;
  if (a === 'copy') { xl_copy(l.url); return; }
  if (a === 'regen') {
    if (!await askConfirm(tr('Create a new link?'), tr('The old one stops working at once.'), {ok: tr('New link'), danger: true})) return;
    let j; try { j = await calReq('POST', `/api/files/ext-links/${id}/regenerate`); } catch (x) { toast(x.message); return; }
    xl_draw(box, n, j); toast(tr('New link created, the old one no longer works')); return;
  }
  if (a === 'revoke') {
    let j; try { j = await calReq('DELETE', `/api/files/ext-links/${id}`); } catch (x) { toast(x.message); return; }
    xl_draw(box, n, j); ab_reload();
    const label = tr('Link for external people of {0}', qn(n.name));
    offerUndo(tr('Link revoked'), histAdd({label, undo: () => xl_req('POST', `/api/files/ext-links/${id}/restore`, box, n),
      redo: () => xl_req('DELETE', `/api/files/ext-links/${id}`, box, n)}));
  }
}
async function xl_req(m, url, box, n) {
  try { const j = await calReq(m, url); if (box) xl_draw(box, n, j); } catch (x) { toast(x.message); }
  ab_reload(); return {};
}

// ---- the dialog that makes a link (then shows it with "Copy")
function xl_newDlg(nid, done) {
  $('.xldlg')?.remove();
  const node = ab_item(nid);
  /** @type {any} */
  const md = modal(`<div class="lhdr"><h3>${tr('Link for external people')}</h3><span class="spacer"></span><button class="iconbtn" data-m="close" aria-label="${tr('Close')}" title="${tr('Close')}">${ic('x')}</button></div>
    <div class="shint lhint keep">${node?.kind === 'folder' ? tr('Whoever has the link can open this folder with everything in it and download the files. No account needed.') : tr('Whoever has the link can open and download this file. No account needed.')}</div>
    <div class="xl-form">
      <label for="xl-exp">${tr('Valid')}</label>
      <select id="xl-exp"><option value="1d">${tr('1 day')}</option><option value="7d" selected>${tr('7 days')}</option><option value="30d">${tr('30 days')}</option><option value="date">${tr('Until a date')}</option><option value="none">${tr('No end date')}</option></select>
      <span class="xl-date" hidden>${dateIn('xl-day', '', {label: tr('Valid until'), min: today()})}</span>
      <label for="xl-pw">${tr('Password (optional)')}</label>
      <input id="xl-pw" type="password" autocomplete="new-password" maxlength="200">
      <label for="xl-lbl">${tr('Label (optional, only you see it)')}</label>
      <input id="xl-lbl" maxlength="80" placeholder="${esc(tr('e.g. the customer’s name'))}">
    </div>
    <div class="xl-out" hidden><label for="xl-url">${tr('Link')}</label><div class="row"><input id="xl-url" readonly><button type="button" class="btn sm pri" data-xn="copy">${ic('copy', 's')} ${tr('Copy')}</button></div></div>
    <div class="calerr" role="alert" id="xl-err" hidden></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-xn="make">${ic('link', 's')} ${tr('Create link')}</button></div>`);
  md.classList.add('xldlg');
  $('#xl-exp', md).addEventListener('change', e => { $('.xl-date', md).hidden = /** @type {any} */ (e.target).value !== 'date'; });
  md.addEventListener('click', async e => {
    if (/** @type {any} */ (e.target).closest('[data-m="close"]')) { modalClose(md); return; }
    const b = /** @type {any} */ (e.target).closest('[data-xn]'); if (!b) return;
    if (b.dataset.xn === 'copy') { const i = $('#xl-url', md); try { await navigator.clipboard.writeText(i.value); toast(tr('Link copied')); } catch { i.focus(); i.select(); toast(tr('Copy the selected link')); } return; }
    const err = $('#xl-err', md), show = m => { err.textContent = m || ''; err.hidden = !m; };
    let exp = $('#xl-exp', md).value;
    if (exp === 'date') { exp = $('#xl-day', md).value; if (!exp) { show(tr('Please choose a date')); return; } }
    const pw = $('#xl-pw', md).value;
    if (pw && pw.length < 4) { show(tr('Password: at least {0} characters', 4)); return; }
    b.disabled = true; show('');
    let j; try { j = await calReq('POST', `/api/files/nodes/${nid}/ext-links`, {expires: exp, tz: evTz(), password: pw, label: $('#xl-lbl', md).value}); }
    catch (x) { show(x.message); b.disabled = false; return; }
    const l = (j.links || []).find(x => x.id === j.id);
    $('.xl-form', md).hidden = true; b.hidden = true;
    $('.xl-out', md).hidden = false; $('#xl-url', md).value = l?.url || '';
    $('[data-m="close"].btn', md).textContent = tr('Done');
    $('#xl-url', md).select();
    const name = node?.name || '';
    histAdd({label: tr('Link for external people of {0}', qn(name)), undo: () => xl_req('DELETE', `/api/files/ext-links/${j.id}`, $('.abdlg .xl-sec'), {id: nid}),
      redo: () => xl_req('POST', `/api/files/ext-links/${j.id}/restore`, $('.abdlg .xl-sec'), {id: nid})});
    if (done) done(); else ab_reload();
  });
}

// ---- Settings > Workspaces: the organisation's switch (after pmeta_paneDraw; box._j = GET /api/orgs)
function xl_paneDraw(box) {
  if (!box?.isConnected) return;
  const orgs = (box._j || {}).orgs || [];
  for (const det of box.querySelectorAll('details.wsorg[data-oid]')) {
    const o = orgs.find(x => x.id === +det.dataset.oid); if (!o || det.querySelector('.xl-orgrow') || o.ext_links === undefined) continue;
    const adm = o.role === 'admin' && box._j.manage, id = `xl-o${o.id}`;
    const row = document.createElement('div');
    row.className = 'row xl-orgrow';
    row.innerHTML = `<label class="chkl"><input type="checkbox" id="${id}" ${o.ext_links ? 'checked' : ''} ${adm ? '' : 'disabled'}> ${tr('Allow external share links')}</label>`;
    const hint = document.createElement('div');
    hint.className = 'shint keep';
    hint.textContent = tr('Owners of a file or folder can share it with people without an account through a secret link. Off: every such link of the organisation stops working at once; nothing is deleted.') + (adm ? '' : ' ' + tr('Only an admin of this organisation can change it.'));
    const after = det.querySelector('.pmeta-row + .shint') || det.querySelector('summary');
    after.after(row); row.after(hint);
    if (!adm) continue;
    const cb = $('#' + id, /** @type {any} */ (row));
    cb.addEventListener('change', async () => {
      const on = cb.checked, put = v => async () => {
        await api('PATCH', `/api/orgs/${o.id}`, {ext_links: v});
        o.ext_links = v; if (cb.isConnected) cb.checked = v; return {};
      };
      try { await put(on)(); } catch { cb.checked = !on; return; }
      const label = tr('External share links of {0}', qn(o.name));
      offerUndo(label, histAdd({label, undo: put(!on), redo: put(on)}));
    });
  }
}
