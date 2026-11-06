// @ts-check
// 2.207.0 A (#2763): "Scans from your computer" in the document settings (docs.js dc_sDraw): the folder watcher (downloads,
// the scan inboxes of this workspace, a new inbox shows its setup code once) and the forwarding address with a copy button and
// the note, shown big once per person, that mail is not end-to-end encrypted.
const DSCN = {code: '', ws: '', md: null, es: /** @type {any} */ (null), edit: 0};  // edit: the inbox whose edit form is open (#4886)  // the setup code just made: only while this settings dialog is open
// 2.353.0 B (#2773): the folder watcher lives in Settings > Integrations (dsc_integrDraw)
// 2.365.2 B (#2789): the whole block "Documents: inboxes" is there now (the folder of the file store, the folder watcher with
// the scan inboxes, the forwarding address); the document settings only point to it
// Settings > Integrations: the whole part (download, set-up code, inboxes with their last use) for the shown workspace
function dsc_integrHtml() {
  return `<h4 id="s-scan-h">${tr('Documents: inboxes')}</h4><div id="s-scan" class="dsc-embed"><div class="muted mhint">${tr('Loading…')}</div></div>${typeof fx_html === 'function' ? fx_html() : ''}`;  // 2.425.0 C (#3453): + the receipt fetcher (docfetch.js)
}
async function dsc_integrDraw(md) {
  if (typeof fx_draw === 'function') fx_draw(md);  // 2.425.0 C (#3453)
  const box = md.querySelector('#s-scan'); if (!box) return;
  const cur = typeof wsCur === 'function' ? wsCur() : 'private', ws = cur.startsWith('org:') ? cur : 'private';
  try { DSCN.es = await api('GET', `/api/docs/settings?ws=${encodeURIComponent(ws)}`); } catch { box.innerHTML = ''; return; }
  if (DSCN.es?.mail?.enabled) DSCN.es.named = await dsc_namedLoad(ws);  // 2.577.0 C (#4466)
  if (!box.isConnected) return;
  dsc_embedDraw(box);
}
function dsc_embedDraw(box) {
  const s = DSCN.es; if (!s || !box) return;
  const dis = s.can_manage ? '' : 'disabled', sc = s.scan || {api: false, downloads: [], keys: [], encrypted: false, mail_notice: true};
  box.innerHTML = `<p class="muted">${esc(typeof dc_wsName === 'function' ? dc_wsName(s.ws) : s.ws)}</p>
    <div class="dsc-way"><h5>${ic('folder', 's')} ${tr('Folder in the file store')}</h5><label class="chkl"><input type="checkbox" data-dsc="inbox" ${s.inbox ? 'checked' : ''} ${dis}> ${esc(tr('Recognise files put into the folder “{0}” of the file store', s.inbox_path || tr('Documents|folder') + '/' + tr('Inbox|folder')))}</label></div>
    ${dsc_watcherHtml(s, box)}${dsc_mailHtml(s, sc)}`;
}
function dsc_watcherHtml(s, host) {
  const sc = s.scan || {api: false, downloads: [], keys: [], encrypted: false, mail_notice: true};
  if (DSCN.code && (DSCN.ws !== s.ws || DSCN.md !== host)) DSCN.code = '';  // the set-up code belongs to the box that made it
  const dl = d => `<a class="btn sm" href="/api/docs/folder-watcher/${encodeURIComponent(d.file)}" download="${esc(d.file)}">${ic('download', 's')} ${esc(d.label)}</a>`;
  const small = d => `<a class="linkbtn" href="/api/docs/folder-watcher/${encodeURIComponent(d.file)}" download="${esc(d.file)}">${esc(d.label)}</a>`;
  const main = sc.downloads.filter(d => d.id.startsWith('mac') || d.id === 'windows'), more = sc.downloads.filter(d => !main.includes(d));
  const key = k => `<li class="dc-rule dsc-key${k.ok ? '' : ' off'}"><span><b>${esc(k.name)}</b> <span class="muted">${esc(k.target)}</span><small class="muted">${k.last_used_at ? esc(tr('last used {0}', relTime(k.last_used_at))) : tr('never used')}${k.expires_at ? ' · ' + esc(k.expired ? tr('expired') : tr('expires {0}', fmtDateLoc(k.expires_at.slice(0, 10)))) : ''}</small></span>
    <button type="button" class="iconbtn" data-dsc="edit:${k.id}" aria-label="${esc(tr('Edit {0}', k.name))}" title="${esc(tr('Edit'))}" aria-expanded="${DSCN.edit === k.id}">${ic('edit')}</button>
    <button type="button" class="iconbtn danger" data-dsc="del:${k.id}" aria-label="${esc(tr('Revoke {0}', k.name))}" title="${esc(tr('Revoke'))}">${ic('trash')}</button></li>${DSCN.edit === k.id ? dsc_editHtml(k, s) : ''}`;
  const folders = [{id: 0, name: tr('Documents (directly)')}, ...(s.folders || [])];
  const watcher = `<div class="dsc-way"><h5>${ic('folder', 's')} ${tr('Folder watcher')}</h5>
    <p class="muted">${tr('Watches a folder on your Mac or Windows PC and uploads new scans here; afterwards they lie in its subfolder “Uploaded”.')}</p>
    ${sc.downloads.length ? `<div class="dsc-dl">${main.map(dl).join('')}</div>${more.length ? `<p class="dsc-more muted">${more.map(small).join(' · ')}</p>` : ''}`
      : `<p class="muted">${tr('Not available on this server - the image builds the programs (Dockerfile)')}</p>`}
    ${sc.encrypted ? `<p class="muted">${tr('The file travels encrypted (HTTPS) and is stored encrypted on the server.')}</p>` : ''}
    ${!sc.api ? `<p class="muted">${tr('The API is switched off on this server, so there are no scan inboxes.')}</p>` : `
    ${sc.keys.length ? `<ul class="dc-rules">${sc.keys.map(key).join('')}</ul>` : ''}
    ${DSCN.code ? dsc_codeHtml() : ''}
    <details class="dc-radd dsc-new"${sc.keys.length || DSCN.code ? '' : ' open'}><summary>${tr('New scan inbox')}</summary>
      <div class="row"><label for="dsc-name">${tr('Name')}</label><input id="dsc-name" maxlength="60" value="${esc(tr('Scanner'))}" autocomplete="off"></div>
      <div class="row"><label for="dsc-folder">${tr('Into folder')}</label><select id="dsc-folder">${folders.map(f => `<option value="${f.id}">${esc(f.name)}</option>`).join('')}</select></div>
      <p class="muted">${tr('Two scanner profiles = two inboxes, for example your own documents and those of your organisation.')}</p>
      <div class="foot"><span class="spacer"></span><button type="button" class="btn pri" data-dsc="new">${tr('Create inbox')}</button></div></details>`}</div>`;
  return watcher;
}
// 2.591.0 B (#4886): edit a scan inbox below its row: name, folder (only folders one may add to), extend by a year; the key stays
function dsc_editHtml(k, s) {
  const fs = [{id: 0, name: tr('Documents (directly)')}, ...(s.folders || []).filter(f => f.role === 'owner' || f.role === 'edit' || f.id === k.parent_id)];
  return `<li class="dc-radd dsc-edit" data-dsc-edit="${k.id}"><div class="row"><label for="dsc-ename">${tr('Name')}</label><input id="dsc-ename" maxlength="60" value="${esc(k.name)}" autocomplete="off"></div>
    <div class="row"><label for="dsc-efolder">${tr('Into folder')}</label><select id="dsc-efolder">${fs.map(f => `<option value="${f.id}"${(k.parent_id || 0) === f.id ? ' selected' : ''}>${esc(f.path || f.name)}</option>`).join('')}</select></div>
    <label class="chkl"><input type="checkbox" id="dsc-eext"${k.expired ? ' checked' : ''}> ${tr('Extend by 1 year')}</label>
    <p class="muted">${tr('The setup code stays the same; the folder watcher goes on without a new setup.')}</p>
    <div class="foot"><span class="spacer"></span><button type="button" class="btn" data-dsc="ecancel">${tr('Cancel')}</button><button type="button" class="btn pri" data-dsc="esave:${k.id}">${tr('Save')}</button></div></li>`;
}
function dsc_codeHtml() {
  return `<div class="dsc-code" role="status"><p><b>${tr('Setup code')}</b> <span class="muted">${tr('Only visible now')}</span></p>
    <div class="dsc-row"><input id="dsc-code" readonly value="${esc(DSCN.code)}" aria-label="${esc(tr('Setup code'))}"><button type="button" class="btn sm" data-dsc="copy">${ic('copy', 's')} ${tr('Copy')}</button></div>
    <ol class="dsc-steps"><li>${tr('Start the program. Mac: the first time open System Settings > Privacy & Security and select “Open Anyway” (the program is not signed by Apple). Windows: in the SmartScreen notice select “More info” > “Run anyway”.')}</li>
      <li>${tr('Paste the code and select the folder to watch.')}</li>
      <li>${tr('Scanner: in the scan software set up a profile that saves as PDF into this folder (searchable is not needed, Kalmido recognises the text itself).')}</li></ol></div>`;
}
function dsc_mailHtml(s, sc) {
  const m = s.mail || {enabled: false, address: ''};
  if (!m.enabled) return '';
  const big = !sc.mail_notice;
  return `<div class="dsc-way"><h5>${ic('mail', 's')} ${tr('By e-mail')}</h5>
    <p class="muted">${tr('PDFs and images attached to e-mails sent to this address become documents here.')}</p>
    ${m.address ? `<div class="dsc-row dc-mail"><code>${esc(m.address)}</code><button type="button" class="btn sm" data-dsc="mailcopy">${ic('copy', 's')} ${tr('Copy')}</button></div>
      <p><button type="button" class="linkbtn" data-dsc="mailnew">${tr('New address')}</button> · <button type="button" class="linkbtn" data-dsc="maildel">${tr('Switch off')}</button></p>
      <p class="muted">${tr('Scanner: in the scan software select “Send by e-mail” and send to this address.')}</p>`
      : `<button type="button" class="btn sm" data-dsc="mailnew">${tr('Create address')}</button>`}
    ${dsc_namedHtml(s)}
    ${big ? `<div class="dsc-note" role="note">${ic('info', 's')}<div><p>${tr('E-mail is not end-to-end encrypted. E-mail providers on the way can read the content and the attachments, like a postcard. For confidential papers use the folder watcher.')}</p>
      <button type="button" class="btn sm" data-dsc="notice">${tr('Got it')}</button></div></div>`
      : `<p class="muted dsc-hint">${tr('E-mail is not end-to-end encrypted; confidential papers better via the folder watcher.')}</p>`}
    ${sc.encrypted ? `<p class="muted">${tr('E-mails into this encrypted area were unencrypted on their way before they were filed.')}</p>` : ''}</div>`;
}
// 2.577.0 C (#4466): named addresses next to the general one: a name, a fixed folder, fixed tags, on / off, a new address
async function dsc_namedLoad(ws) {
  try { return (await api('GET', `/api/docs/mail-addresses?ws=${encodeURIComponent(ws)}`)).addresses.filter(a => !a.general); } catch { return null; }
}
function dsc_namedForm(s, a) {
  const k = a ? a.id : 'new', folders = [{id: 0, path: tr('Documents (directly)')}, ...(s.folders || [])];
  return `<div class="row"><label for="dsn-name-${k}">${tr('Name')}</label><input id="dsn-name-${k}" maxlength="60" value="${esc(a ? a.name : '')}" placeholder="${esc(tr('for example Bank statements'))}" autocomplete="off"></div>
    <div class="row"><label for="dsn-folder-${k}">${tr('Into folder')}</label><select id="dsn-folder-${k}">${folders.map(f => `<option value="${f.id}"${a && (a.target_folder || 0) === f.id ? ' selected' : ''}>${esc(f.path || f.name)}</option>`).join('')}</select></div>
    <div class="row"><label for="dsn-tags-${k}">${tr('Tags')}</label><input id="dsn-tags-${k}" maxlength="400" value="${esc(a ? a.tags.join(', ') : '')}" placeholder="${esc(tr('comma separated'))}" autocomplete="off"></div>
    <div class="foot"><span class="spacer"></span><button type="button" class="btn pri" data-dsc="${a ? 'nsave:' + a.id : 'nnew'}">${a ? tr('Save') : tr('Create address')}</button></div>`;
}
function dsc_namedHtml(s) {
  const list = s.named; if (!Array.isArray(list)) return '';
  const row = a => `<li class="dc-rule dsn-addr${a.ok && a.active ? '' : ' off'}" data-aid="${esc(a.id)}"><span><b>${esc(a.name)}</b> <span class="muted">${esc(a.target || tr('Documents (directly)'))}${a.tags.length ? ' · ' + esc(a.tags.join(', ')) : ''}</span>
      ${a.address ? `<code class="dsn-code">${esc(a.address)}</code>` : ''}${a.note ? `<small class="muted">${esc(a.note)}</small>` : ''}</span>
    <span class="dsn-acts"><label class="chkl"><input type="checkbox" data-dsc="non:${esc(a.id)}" ${a.active ? 'checked' : ''}> ${tr('On')}</label>
      <button type="button" class="iconbtn" data-dsc="ncopy:${esc(a.id)}" aria-label="${esc(tr('Copy {0}', a.name))}" title="${esc(tr('Copy'))}">${ic('copy')}</button>
      <button type="button" class="iconbtn" data-dsc="nrenew:${esc(a.id)}" aria-label="${esc(tr('New address for {0}', a.name))}" title="${esc(tr('New address'))}">${ic('sync')}</button>
      <button type="button" class="iconbtn danger" data-dsc="ndel:${esc(a.id)}" aria-label="${esc(tr('Delete {0}', a.name))}" title="${esc(tr('Delete'))}">${ic('trash')}</button></span>
    <details class="dc-radd dsn-edit"><summary>${tr('Edit')}</summary>${dsc_namedForm(s, a)}</details></li>`;
  return `<div class="dsn-named"><h5>${tr('Named addresses')}</h5>
    <p class="muted">${tr('Each address files into its own folder with fixed tags, for example one for bank statements and one for the credit card.')}</p>
    ${list.length ? `<ul class="dc-rules">${list.map(row).join('')}</ul>` : ''}
    <details class="dc-radd dsn-new"><summary>${tr('New named address')}</summary>${dsc_namedForm(s, null)}</details></div>`;
}
function dsc_namedVals(md, k) {
  const q = sel => /** @type {HTMLInputElement|null} */ (md.querySelector(sel));
  return {name: (q(`#dsn-name-${k}`)?.value || '').trim(), target_folder: +(q(`#dsn-folder-${k}`)?.value || 0) || null,
    tags: (q(`#dsn-tags-${k}`)?.value || '').split(',').map(t => t.trim()).filter(Boolean)};
}
async function dsc_namedSave(md, a, patch) {  // PATCH with the version read; changed meanwhile (409) -> the current state
  const s = DSCN.es;
  try { await api('PATCH', `/api/docs/mail-addresses/${encodeURIComponent(a.id)}`, {...patch, expect_updated_at: a.updated_at}); }
  catch { s.named = await dsc_namedLoad(s.ws); dsc_embedDraw(md); return false; }
  s.named = await dsc_namedLoad(s.ws); dsc_embedDraw(md);
  return true;
}
async function dsc_reload(md) {
  const s = DSCN.es; if (!s) return;
  try { s.scan = await api('GET', `/api/docs/scan-keys?ws=${encodeURIComponent(s.ws)}`); } catch { return; }
  dsc_embedDraw(md);
}
async function dsc_copy(text) {
  try { await navigator.clipboard.writeText(text); toast(tr('Copied')); } catch { toast(tr('Copy failed, select the text by hand')); }
}
document.addEventListener('click', async e => {
  const b = /** @type {HTMLElement|null} */ (/** @type {HTMLElement} */ (e.target).closest?.('.dsc-embed [data-dsc]')); if (!b || b.matches('input')) return;
  const md = /** @type {HTMLElement} */ (b.closest('.dsc-embed')), a = b.dataset.dsc || '', s = DSCN.es;
  if (!s) return;
  if (a === 'copy') { dsc_copy(DSCN.code); return; }
  if (a === 'mailcopy') { dsc_copy(s.mail?.address || ''); return; }
  if (a === 'notice') {
    try { await api('POST', '/api/docs/mail-notice', {}); } catch { return; }
    if (s.scan) s.scan.mail_notice = true; dsc_embedDraw(md);
    return;
  }
  if (a === 'mailnew') {  // 2.365.2 B (#2789): from the document settings (docs.js), the only place of the address now
    if (s.mail.address && !await askConfirm(tr('New address?'), tr('The old address stops working.'), {ok: tr('New address')})) return;
    const j = await api('POST', '/api/docs/mail', {ws: s.ws}).catch(() => null); if (!j) return;
    s.mail.address = j.address; dsc_embedDraw(md);
    return;
  }
  if (a === 'maildel') {
    if (!await askConfirm(tr('Switch off the address?'), tr('E-mails to it no longer arrive.'), {ok: tr('Switch off'), danger: true})) return;
    await api('DELETE', `/api/docs/mail?ws=${encodeURIComponent(s.ws)}`).catch(() => null);
    s.mail.address = ''; dsc_embedDraw(md);
    return;
  }
  if (a === 'nnew' || a.startsWith('n') && a.includes(':')) { await dsc_namedClick(md, b, a); return; }
  if (a === 'new') {
    const name = (/** @type {HTMLInputElement|null} */ (md.querySelector('#dsc-name'))?.value || '').trim();
    if (!name) { /** @type {HTMLElement|null} */ (md.querySelector('#dsc-name'))?.focus(); return; }
    const pid = +(/** @type {HTMLSelectElement|null} */ (md.querySelector('#dsc-folder'))?.value || 0);
    let j; b.setAttribute('disabled', ''); try { j = await api('POST', '/api/docs/scan-keys', {ws: s.ws, name, parent_id: pid || null}); } catch { b.removeAttribute('disabled'); return; }
    DSCN.code = j.code; DSCN.ws = s.ws; DSCN.md = md;
    await dsc_reload(md);
    /** @type {HTMLElement|null} */ (md.querySelector('#dsc-code'))?.focus();
    return;
  }
  if (a.startsWith('edit:')) { const id = +a.slice(5); DSCN.edit = DSCN.edit === id ? 0 : id; dsc_embedDraw(md); /** @type {HTMLElement|null} */ (md.querySelector('#dsc-ename'))?.focus(); return; }  // 2.591.0 B (#4886)
  if (a === 'ecancel') { DSCN.edit = 0; dsc_embedDraw(md); return; }
  if (a.startsWith('esave:')) {
    const id = +a.slice(6), name = (/** @type {HTMLInputElement|null} */ (md.querySelector('#dsc-ename'))?.value || '').trim();
    if (!name) { /** @type {HTMLElement|null} */ (md.querySelector('#dsc-ename'))?.focus(); return; }
    const pid = +(/** @type {HTMLSelectElement|null} */ (md.querySelector('#dsc-efolder'))?.value || 0);
    const extend = !!(/** @type {HTMLInputElement|null} */ (md.querySelector('#dsc-eext'))?.checked);
    b.setAttribute('disabled', ''); try { await api('PATCH', `/api/docs/scan-keys/${id}`, {name, parent_id: pid || null, extend}); } catch { b.removeAttribute('disabled'); return; }
    DSCN.edit = 0; toast(tr('Saved'));
    await dsc_reload(md);
    return;
  }
  if (a.startsWith('del:')) {
    const id = +a.slice(4), k = (s.scan?.keys || []).find(x => x.id === id); if (!k) return;
    if (!await askConfirm(tr('Revoke the scan inbox “{0}”?', k.name), tr('The folder watcher with this code stops uploading at once.'), {ok: tr('Revoke'), danger: true})) return;
    try { await api('DELETE', `/api/docs/scan-keys/${id}`); } catch { return; }
    toast(tr('Revoked: {0}', k.name));
    await dsc_reload(md);
  }
});
async function dsc_namedClick(md, b, a) {
  const s = DSCN.es, id = a.slice(a.indexOf(':') + 1), x = (s.named || []).find(n => n.id === id);
  if (a === 'nnew') {
    const v = dsc_namedVals(md, 'new');
    if (!v.name) { /** @type {HTMLElement|null} */ (md.querySelector('#dsn-name-new'))?.focus(); return; }
    b.setAttribute('disabled', '');
    try { await api('POST', '/api/docs/mail-addresses', {ws: s.ws, ...v}); } catch { b.removeAttribute('disabled'); return; }
    s.named = await dsc_namedLoad(s.ws); dsc_embedDraw(md);
    return;
  }
  if (!x) return;
  if (a.startsWith('ncopy:')) { dsc_copy(x.address); return; }
  if (a.startsWith('nsave:')) {
    const v = dsc_namedVals(md, x.id); if (!v.name) return;
    if (await dsc_namedSave(md, x, v)) toast(tr('Saved'));
    return;
  }
  if (a.startsWith('nrenew:')) {
    if (!await askConfirm(tr('New address?'), tr('The old address stops working.'), {ok: tr('New address')})) return;
    try { await api('POST', `/api/docs/mail-addresses/${encodeURIComponent(x.id)}/renew`, {}); } catch { return; }
    s.named = await dsc_namedLoad(s.ws); dsc_embedDraw(md);
    return;
  }
  if (a.startsWith('ndel:')) {
    if (!await askConfirm(tr('Delete the address “{0}”?', x.name), tr('E-mails to it no longer arrive.'), {ok: tr('Delete'), danger: true})) return;
    try { await api('DELETE', `/api/docs/mail-addresses/${encodeURIComponent(x.id)}`); } catch { return; }
    s.named = await dsc_namedLoad(s.ws); dsc_embedDraw(md);
  }
}
document.addEventListener('change', async e => {  // 2.577.0 C (#4466): a named address on / off
  const el = /** @type {HTMLInputElement} */ (e.target); if (!el.matches?.('.dsc-embed [data-dsc^="non:"]')) return;
  const s = DSCN.es, id = (el.dataset.dsc || '').slice(4), x = (s?.named || []).find(n => n.id === id), md = /** @type {HTMLElement|null} */ (el.closest('.dsc-embed'));
  if (!x || !md) return;
  if (!await dsc_namedSave(md, x, {active: el.checked})) return;
  toast(el.checked ? tr('Address on: {0}', x.name) : tr('Address off: {0}', x.name));
});
document.addEventListener('change', async e => {  // 2.365.2 B (#2789): the folder of the file store (was in the document settings)
  const el = /** @type {HTMLInputElement} */ (e.target); if (!el.matches?.('.dsc-embed [data-dsc="inbox"]')) return;
  const s = DSCN.es; if (!s) return;
  const put = v => async () => { const j = await api('PUT', '/api/docs/settings', {ws: s.ws, inbox: v}); s.inbox = j.inbox; const b = document.querySelector('.dsc-embed'); if (b) dsc_embedDraw(b); return {}; };
  try { await put(el.checked)(); } catch { el.checked = !el.checked; return; }
  const l = tr('Changed setting: {0}', tr('Folder in the file store'));
  histToast(l, histAdd({label: l, sett: true, undo: put(!el.checked), redo: put(el.checked)}));
});
