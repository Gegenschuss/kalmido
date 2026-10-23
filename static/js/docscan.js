// @ts-check
// 2.207.0 A (#2763): "Scans from your computer" in the document settings (docs.js dc_sDraw): the folder watcher (downloads,
// the scan inboxes of this workspace, a new inbox shows its setup code once) and the forwarding address with a copy button and
// the note, shown big once per person, that mail is not end-to-end encrypted.
const DSCN = {code: '', ws: '', md: null};  // the setup code just made: only while this settings dialog is open
const dsc_mdNow = () => document.querySelector('.dc-smd');
function dsc_slot(s) {
  const sc = s.scan || {api: false, downloads: [], keys: [], encrypted: false, mail_notice: true};
  if (DSCN.code && (DSCN.ws !== s.ws || DSCN.md !== dsc_mdNow())) DSCN.code = '';
  const dl = d => `<a class="btn sm" href="/api/docs/folder-watcher/${encodeURIComponent(d.file)}" download="${esc(d.file)}">${ic('download', 's')} ${esc(d.label)}</a>`;
  const small = d => `<a class="linkbtn" href="/api/docs/folder-watcher/${encodeURIComponent(d.file)}" download="${esc(d.file)}">${esc(d.label)}</a>`;
  const main = sc.downloads.filter(d => d.id.startsWith('mac') || d.id === 'windows'), more = sc.downloads.filter(d => !main.includes(d));
  const key = k => `<li class="dc-rule dsc-key${k.ok ? '' : ' off'}"><span><b>${esc(k.name)}</b> <span class="muted">${esc(k.target)}</span><small class="muted">${k.last_used_at ? esc(tr('last used {0}', relTime(k.last_used_at))) : tr('never used')}</small></span>
    <button type="button" class="iconbtn danger" data-dsc="del:${k.id}" aria-label="${esc(tr('Revoke {0}', k.name))}" title="${esc(tr('Revoke'))}">${ic('trash')}</button></li>`;
  const folders = [{id: 0, name: tr('Documents (directly)')}, ...(s.folders || [])];
  const watcher = `<div class="dsc-way"><h5>${ic('folder', 's')} ${tr('Folder watcher')}</h5>
    <p class="muted">${tr('Watches a folder on your Mac or Windows PC and uploads new scans here; afterwards they lie in its subfolder “Uploaded”.')}</p>
    ${sc.downloads.length ? `<div class="dsc-dl">${main.map(dl).join('')}</div>${more.length ? `<p class="dsc-more muted">${more.map(small).join(' · ')}</p>` : ''}`
      : `<p class="muted">${tr('Not available on this server - the image builds the programs (Dockerfile)')}</p>`}
    ${sc.encrypted ? `<p class="muted">${tr('The file travels encrypted (HTTPS) and is stored encrypted on the server.')}</p>` : ''}
    ${!sc.api ? `<p class="muted">${tr('The API is turned off on this server, so there are no scan inboxes.')}</p>` : `
    ${sc.keys.length ? `<ul class="dc-rules">${sc.keys.map(key).join('')}</ul>` : ''}
    ${DSCN.code ? dsc_codeHtml() : ''}
    <details class="dc-radd dsc-new"${sc.keys.length || DSCN.code ? '' : ' open'}><summary>${tr('New scan inbox')}</summary>
      <div class="row"><label for="dsc-name">${tr('Name')}</label><input id="dsc-name" maxlength="60" value="${esc(tr('Scanner'))}" autocomplete="off"></div>
      <div class="row"><label for="dsc-folder">${tr('Into folder')}</label><select id="dsc-folder">${folders.map(f => `<option value="${f.id}">${esc(f.name)}</option>`).join('')}</select></div>
      <p class="muted">${tr('Two scanner profiles = two inboxes, for example your own documents and those of your organisation.')}</p>
      <div class="foot"><span class="spacer"></span><button type="button" class="btn pri" data-dsc="new">${tr('Create inbox')}</button></div></details>`}</div>`;
  return `<h4>${tr('Scans from your computer')}</h4>${watcher}${dsc_mailHtml(s, sc)}`;
}
function dsc_codeHtml() {
  return `<div class="dsc-code" role="status"><p><b>${tr('Setup code')}</b> <span class="muted">${tr('Only visible now')}</span></p>
    <div class="dsc-row"><input id="dsc-code" readonly value="${esc(DSCN.code)}" aria-label="${esc(tr('Setup code'))}"><button type="button" class="btn sm" data-dsc="copy">${ic('copy', 's')} ${tr('Copy')}</button></div>
    <ol class="dsc-steps"><li>${tr('Start the program. Mac: the first time open System Settings > Privacy & Security and choose “Open Anyway” (the program is not signed by Apple). Windows: in the SmartScreen notice choose “More info” > “Run anyway”.')}</li>
      <li>${tr('Paste the code and choose the folder to watch.')}</li>
      <li>${tr('ScanSnap: in ScanSnap Home create or edit a profile and set “Save to” to this folder (PDF; searchable is not needed, Kalmido recognises the text itself).')}</li></ol></div>`;
}
function dsc_mailHtml(s, sc) {
  const m = s.mail || {enabled: false, address: ''};
  if (!m.enabled) return '';
  const big = !sc.mail_notice;
  return `<div class="dsc-way"><h5>${ic('mail', 's')} ${tr('By e-mail')}</h5>
    <p class="muted">${tr('PDFs and images attached to mails sent to this address become documents here.')}</p>
    ${m.address ? `<div class="dsc-row dc-mail"><code>${esc(m.address)}</code><button type="button" class="btn sm" data-dsc="mailcopy">${ic('copy', 's')} ${tr('Copy')}</button></div>
      <p><button type="button" class="linkbtn" data-dcs="mailnew">${tr('New address')}</button> · <button type="button" class="linkbtn" data-dcs="maildel">${tr('Turn off')}</button></p>
      <p class="muted">${tr('ScanSnap: in a profile choose “Send by e-mail” and send to this address.')}</p>`
      : `<button type="button" class="btn sm" data-dcs="mailnew">${tr('Create address')}</button>`}
    ${big ? `<div class="dsc-note" role="note">${ic('info', 's')}<div><p>${tr('E-mail is not end-to-end encrypted. Mail providers on the way can read the content and the attachments, like a postcard. For confidential papers use the folder watcher.')}</p>
      <button type="button" class="btn sm" data-dsc="notice">${tr('Got it')}</button></div></div>`
      : `<p class="muted dsc-hint">${tr('Mail is not end-to-end encrypted; confidential papers better via the folder watcher.')}</p>`}
    ${sc.encrypted ? `<p class="muted">${tr('Mails into this encrypted area were unencrypted on their way before they were filed.')}</p>` : ''}</div>`;
}
async function dsc_reload(md) {
  const s = DC.set; if (!s) return;
  try { s.scan = await api('GET', `/api/docs/scan-keys?ws=${encodeURIComponent(s.ws)}`); } catch { return; }
  dc_sDraw(md);
}
async function dsc_copy(text) {
  try { await navigator.clipboard.writeText(text); toast(tr('Copied')); } catch { toast(tr('Copy failed, select the text by hand')); }
}
document.addEventListener('click', async e => {
  const b = /** @type {HTMLElement|null} */ (/** @type {HTMLElement} */ (e.target).closest?.('.dc-smd [data-dsc]')); if (!b) return;
  const md = /** @type {HTMLElement} */ (b.closest('.dc-smd')), s = DC.set, a = b.dataset.dsc || ''; if (!s) return;
  if (a === 'copy') { dsc_copy(DSCN.code); return; }
  if (a === 'mailcopy') { dsc_copy(s.mail?.address || ''); return; }
  if (a === 'notice') {
    try { await api('POST', '/api/docs/mail-notice', {}); } catch { return; }
    if (s.scan) s.scan.mail_notice = true; dc_sDraw(md);
    return;
  }
  if (a === 'new') {
    const name = (/** @type {HTMLInputElement|null} */ ($('#dsc-name', md))?.value || '').trim();
    if (!name) { $('#dsc-name', md)?.focus(); return; }
    const pid = +(/** @type {HTMLSelectElement|null} */ ($('#dsc-folder', md))?.value || 0);
    let j; b.setAttribute('disabled', ''); try { j = await api('POST', '/api/docs/scan-keys', {ws: s.ws, name, parent_id: pid || null}); } catch { b.removeAttribute('disabled'); return; }
    DSCN.code = j.code; DSCN.ws = s.ws; DSCN.md = md;
    await dsc_reload(md);
    $('#dsc-code', md)?.focus();
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
