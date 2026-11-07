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
    <button type="button" class="iconbtn" data-xl="revoke" title="${esc(tr('Switch off'))}" aria-label="${esc(tr('Switch off'))}">${ic('x', 's')}</button></div>`;
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
  if (a === 'new') { xl_newDlg(n.id, () => xl_reload(box, n), box._j?.default_expires); return; }
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
const xl_expOpts = (cur, day) => [['1d', tr('1 day')], ['7d', tr('7 days')], ['30d', tr('30 days')], ...(day ? [['date', tr('Until a date')]] : []), ['none', tr('No end date')]]
  .map(([v, t]) => `<option value="${v}" ${v === cur ? 'selected' : ''}>${t}</option>`).join('');
// 2.470.0 (#3596): std = the workspace's default validity (the server's answer; asked here when the caller has none)
async function xl_newDlg(nid, done, std) {
  if (!std) { try { std = (await api('GET', `/api/files/nodes/${nid}/ext-links`)).default_expires; } catch { /* the toast said it */ } }
  $('.xldlg')?.remove();
  const node = ab_item(nid);
  /** @type {any} */
  const md = modal(`<div class="lhdr"><h3>${tr('Link for external people')}</h3><span class="spacer"></span><button class="iconbtn" data-m="close" aria-label="${tr('Close')}" title="${tr('Close')}">${ic('x')}</button></div>
    <div class="shint lhint keep">${node?.kind === 'folder' ? tr('Whoever has the link can open this folder with everything in it and download the files. No account needed.') : tr('Whoever has the link can open and download this file. No account needed.')}</div>
    <div class="xl-form">
      <label for="xl-exp">${tr('Valid')}</label>
      <select id="xl-exp">${xl_expOpts(std || '7d', true)}</select>
      <span class="xl-date" hidden>${dateIn('xl-day', '', {label: tr('Valid until'), min: today()})}</span>
      <label for="xl-pw">${tr('Password (optional)')}</label>
      <input id="xl-pw" type="password" autocomplete="new-password" maxlength="200">
      <label for="xl-lbl">${tr('Label (optional, only you see it)')}</label>
      <input id="xl-lbl" maxlength="80" placeholder="${esc(tr('e.g. the client’s name'))}">
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
    if (exp === 'date') { exp = $('#xl-day', md).value; if (!exp) { show(tr('Please select a date')); return; } }
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

// the kinds of file a request may allow (here since 2.470.0, #3596: filereq.js loads on demand, Settings needs them too)
const FRQ_KINDS = [['docs', N_('Documents (PDF, Office, text)')], ['images', N_('Pictures')], ['design', N_('Design files (AI, EPS, PSD)')],
  ['archives', N_('Archives (ZIP)')], ['media', N_('Audio and video')]];

// ---- 2.470.0 (#3596): Settings > Data: the sharing defaults of a workspace (kalmido/accounts/sharedefs.py). Private: the person,
// an organisation: its admins (the others read them); opens on the current workspace, a select reaches the others
const xl_stdHtml = hint => S.me?.kid ? '' : `<h4 id="s-xlstd-h">${tr('Sharing defaults')}</h4>${hint(tr('What new external links and file requests start with. You can still change it each time.'))}<div id="s-xlstd"></div>`;
function xl_stdMount(md) {
  /** @type {any} */
  const box = $('#s-xlstd', md); if (!box) return;
  box.addEventListener('change', e => xl_stdChange(box, /** @type {any} */ (e.target)));
  box.addEventListener('click', e => { if (/** @type {any} */ (e.target).closest('[data-xlstd="reset"]')) xl_stdSave(box, {}); });
  const w = wsOn() ? wsCur() : 'private';
  xl_stdLoad(box, w === 'all' ? 'private' : w);
}
async function xl_stdLoad(box, ws) {
  let j; try { j = await api('GET', `/api/share-defaults?space=${encodeURIComponent(ws)}`); } catch { return; }
  if (box.isConnected) xl_stdDraw(box, j);
}
function xl_stdDraw(box, j) {
  box._j = j;
  const d = j.defaults, lim = j.limits, dis = j.can_edit ? '' : 'disabled', oid = j.space === 'private' ? '' : j.space.slice(4);
  box.innerHTML = `${wsOn() ? `<div class="row"><label for="s-xlstd-ws">${tr('Workspace')}</label>${wsSelectHtml('s-xlstd-ws', oid)}</div>` : ''}
    <div class="row"><label for="s-xlstd-exp">${tr('External links valid for')}</label><select id="s-xlstd-exp" ${dis}>${xl_expOpts(d.link_expires)}</select></div>
    <div class="row"><label for="s-xlstd-days">${tr('File requests valid for (days)')}</label><input id="s-xlstd-days" type="number" inputmode="numeric" min="1" max="${lim.days}" value="${d.req_days}" ${dis}></div>
    <div class="row"><label for="s-xlstd-mb">${tr('At most MB per file')}</label><input id="s-xlstd-mb" type="number" inputmode="numeric" min="1" max="${lim.max_mb}" value="${d.req_mb}" ${dis}></div>
    <div class="row"><label for="s-xlstd-n">${tr('At most files in all')}</label><input id="s-xlstd-n" type="number" inputmode="numeric" min="1" max="${lim.max_files}" value="${d.req_files}" ${dis}></div>
    <fieldset class="frq-kinds"><legend>${tr('Allowed files')}</legend>${FRQ_KINDS.filter(([k]) => lim.types.includes(k)).map(([k, l]) => `<label class="chkl"><input type="checkbox" value="${k}" ${d.req_types.includes(k) ? 'checked' : ''} ${dis}> ${esc(tr(l))}</label>`).join('')}</fieldset>
    ${j.can_edit ? (Object.keys(j.stored).length ? `<div class="row"><button type="button" class="btn sm" data-xlstd="reset">${tr('Back to the default values')}</button></div>` : '') : `<div class="shint keep">${tr('Only an admin of this organisation can change it.')}</div>`}`;
}
function xl_stdChange(box, el) {
  if (el.id === 's-xlstd-ws') { xl_stdLoad(box, el.value ? 'org:' + el.value : 'private'); return; }
  xl_stdSave(box, {link_expires: $('#s-xlstd-exp', box).value, req_days: +$('#s-xlstd-days', box).value, req_mb: +$('#s-xlstd-mb', box).value,
    req_files: +$('#s-xlstd-n', box).value, req_types: $$('.frq-kinds input:checked', box).map(x => x.value)});
}
async function xl_stdSave(box, v) {
  const {space: ws, stored: was} = box._j;
  const put = x => async () => {
    if (ws === 'private') { const t = JSON.stringify(x); await api('PATCH', '/api/settings', {share_defaults: t}); S.settings.share_defaults = t; }
    else await api('PATCH', `/api/orgs/${ws.slice(4)}`, {share_defaults: x});
    await xl_stdLoad(box, ws); return {};
  };
  try { await put(v)(); } catch { if (box.isConnected) xl_stdDraw(box, box._j); return; }
  const label = tr('Sharing defaults of {0}', qn(wsName(ws)));
  offerUndo(label, histAdd({label, undo: put(was), redo: put(v)}));
}
