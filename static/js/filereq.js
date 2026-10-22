// @ts-check
/* Kalmido web client: file requests (2.122.0 A, #2097). A folder of the file store gets a public link /u/<token>: a client
   uploads documents into it without an account (never sees what is in the folder). The folder's menu "Request files…"
   opens the list of its requests (active / over / stopped, how many files arrived, copy the link, QR code, extend, stop,
   remove) and the dialog for a new one (title, note, end date, size per file, number of files, allowed kinds, subfolder).
   The rules live on the server (kalmido/files/filereq.py). Classic script sharing the global scope (after ablage.js). */
'use strict';

const FRQ_KINDS = [['docs', N_('Documents (PDF, Office, text)')], ['images', N_('Pictures')], ['design', N_('Design files (AI, EPS, PSD)')],
  ['archives', N_('Archives (ZIP)')], ['media', N_('Audio and video')]];
const frq_until = iso => iso ? fmtDay('short', new Date(iso)) : '';
const frq_stateText = r => r.state === 'active' ? tr('Open until {0}', frq_until(r.expires_at)) : r.state === 'expired' ? tr('Expired on {0}', frq_until(r.expires_at))
  : r.state === 'revoked' ? tr('Turned off') : tr('Not working: the creator can no longer add files to this folder');
const frq_dayPlus = n => { const d = new Date(); d.setDate(d.getDate() + n); return ds(d); };

async function frq_open(n) {
  let j; try { j = await api('GET', `/api/files/nodes/${n.id}/requests`); } catch { return; }
  $('.frqdlg')?.remove();
  /** @type {any} */
  const md = modal(`<div class="lhdr"><h3 id="frq-t">${ic('upload')} ${esc(tr('Request files'))}</h3><span class="spacer"></span><button class="iconbtn" data-frq="close" aria-label="${esc(tr('Close'))}" title="${esc(tr('Close'))}">${ic('x')}</button></div>
    <div class="muted abpath">${esc(n.name)}</div><div class="frq-body"></div>`);
  md.classList.add('frqdlg'); md.setAttribute('aria-labelledby', 'frq-t');
  const draw = () => {
    const rows = j.requests.map(r => `<div class="frq-row frq-${esc(r.state)}" data-rid="${r.id}">
        <div class="frq-head"><b>${esc(r.title)}</b><span class="spacer"></span>${r.manage ? `<button type="button" class="iconbtn" data-frq="menu" aria-label="${esc(tr('More actions for {0}', r.title))}" title="${esc(tr('More'))}">${ic('dots')}</button>` : ''}</div>
        <div class="muted frq-facts"><span>${esc(frq_stateText(r))}</span><span>${esc(trn('{0} file arrived', '{0} files arrived', r.count))}</span>${r.mine ? '' : `<span>${esc(tr('by {0}', r.created_by_name))}</span>`}</div>
        ${r.url && r.state === 'active' ? `<div class="frq-link"><input readonly value="${esc(r.url)}" aria-label="${esc(tr('Upload link'))}"><button type="button" class="btn sm" data-frq="copy">${ic('copy', 's')} ${esc(tr('Copy'))}</button><button type="button" class="iconbtn" data-frq="qr" aria-label="${esc(tr('QR code'))}" title="${esc(tr('QR code'))}">${ic('grid', 's')}</button></div><div class="frq-qr" hidden></div>` : ''}</div>`).join('');
    $('.frq-body', md).innerHTML = `<div class="shint lhint keep">${esc(tr('Clients upload files into this folder through the link, without an account. They never see what is in it.'))}</div>
      ${j.public_links ? '' : `<p class="muted mhint">${esc(tr('Public links are turned off on this server'))}</p>`}
      <div class="frq-list">${rows || `<p class="muted mhint">${esc(tr('No file requests yet'))}</p>`}</div>
      <div class="foot">${j.public_links ? `<button type="button" class="btn" data-frq="new">${ic('plus', 's')} ${esc(tr('New file request'))}</button>` : ''}<span class="spacer"></span><button type="button" class="btn pri" data-frq="close">${esc(tr('Done'))}</button></div>`;
  };
  const reload = async () => { try { j = await api('GET', `/api/files/nodes/${n.id}/requests`); } catch { return; } if (md.isConnected) draw(); };
  const patch = (rid, b) => api('PATCH', `/api/files/requests/${rid}`, b).then(reload);
  draw();
  md.addEventListener('click', async e => {
    const k = /** @type {any} */ (e.target).closest('[data-frq]')?.dataset.frq; if (!k) return;
    const r = j.requests.find(x => x.id === +/** @type {any} */ (e.target).closest('[data-rid]')?.dataset.rid);
    if (k === 'close') { modalClose(md); return; }
    if (k === 'new') { frq_new(n, j.limits, reload); return; }
    if (!r) return;
    if (k === 'copy') copyText(r.url);
    else if (k === 'qr') {
      const box = $(`[data-rid="${r.id}"] .frq-qr`, md); if (!box) return;
      if (!box.hidden) { box.hidden = true; return; }
      try { const q = await api('POST', '/api/qr', {text: r.url}); box.innerHTML = `<img src="${esc(q.qr)}" alt="${esc(tr('QR code of the link'))}" width="240" height="240">`; box.hidden = false; } catch { /* the toast said it */ }
    } else if (k === 'menu') {
      const b = /** @type {any} */ (e.target).closest('[data-frq="menu"]'), was = r.expires_at;
      const ext = r.state === 'active' || r.state === 'expired';
      menu(b, [ext ? {label: tr('Extend by {0} days', 14), icon: 'clock', fn: async () => {
        const to = frq_dayPlus(Math.min(j.limits.days, Math.max(0, Math.ceil((+new Date(was) - Date.now()) / 864e5)) + 14));
        try { await patch(r.id, {expires_at: to, tz: evTz()}); } catch { return; }
        offerUndo(tr('Open until {0}', frq_until(j.requests.find(x => x.id === r.id)?.expires_at)), histAdd({label: tr('Extend “{0}”', r.title),
          undo: async () => { try { await patch(r.id, {expires_at: was}); } catch { /* shown */ } return {}; }, redo: async () => { try { await patch(r.id, {expires_at: to, tz: evTz()}); } catch { /* shown */ } return {}; }}));
      }} : null,
      r.state === 'revoked' ? {label: tr('Open again'), icon: 'undo', fn: async () => {
        try { await patch(r.id, {revoked: false}); } catch { return; }
        offerUndo(tr('The link works again'), histAdd({label: tr('Open “{0}” again', r.title), undo: async () => { try { await patch(r.id, {revoked: true}); } catch { /* shown */ } return {}; }, redo: async () => { try { await patch(r.id, {revoked: false}); } catch { /* shown */ } return {}; }}));
      }} : {label: tr('Stop the link'), icon: 'x', fn: async () => {
        try { await patch(r.id, {revoked: true}); } catch { return; }
        offerUndo(tr('The link no longer works'), histAdd({label: tr('Stop “{0}”', r.title), undo: async () => { try { await patch(r.id, {revoked: false}); } catch { /* shown */ } return {}; }, redo: async () => { try { await patch(r.id, {revoked: true}); } catch { /* shown */ } return {}; }}));
      }},
      '-',
      {label: tr('Remove'), icon: 'trash', cls: 'danger', fn: async () => {
        try { await api('DELETE', `/api/files/requests/${r.id}`); } catch { return; }
        reload();
        offerUndo(tr('File request removed'), histAdd({label: tr('Remove “{0}”', r.title), undo: () => api('POST', `/api/files/requests/${r.id}/restore`).then(reload).then(() => ({})), redo: () => api('DELETE', `/api/files/requests/${r.id}`).then(reload).then(() => ({}))}));
      }}], null, null, r.title);
    }
  });
}

function frq_new(n, lim, done) {
  const kinds = FRQ_KINDS.filter(([k]) => lim.types.includes(k));
  /** @type {any} */
  const md = modal(`<form class="frq-form" novalidate><div class="lhdr"><h3 id="frq-nt">${esc(tr('New file request'))}</h3><span class="spacer"></span><button type="button" class="iconbtn" data-frq="cancel" aria-label="${esc(tr('Close'))}">${ic('x')}</button></div>
    <div class="row"><label for="frq-title">${esc(tr('Title'))}</label><input id="frq-title" maxlength="120" required value="${esc(tr('Files for {0}', n.name))}"></div>
    <div class="row"><label for="frq-note">${esc(tr('Note for the client'))}</label><textarea id="frq-note" rows="3" maxlength="2000" placeholder="${esc(tr('e.g. Please upload your logo and the signed contract.'))}"></textarea></div>
    <div class="row"><label for="frq-exp">${esc(tr('The link works until'))}</label>${dateIn('frq-exp', frq_dayPlus(lim.default_days), {label: tr('The link works until'), min: frq_dayPlus(1), max: frq_dayPlus(lim.days), clear: false})}</div>
    <div class="row frq-nums"><label for="frq-mb">${esc(tr('At most MB per file'))}</label><input id="frq-mb" type="number" inputmode="numeric" min="1" max="${lim.max_mb}" value="${lim.default_mb}">
      <label for="frq-n">${esc(tr('At most files in all'))}</label><input id="frq-n" type="number" inputmode="numeric" min="1" max="${lim.max_files}" value="${lim.default_files}"></div>
    <fieldset class="frq-kinds"><legend>${esc(tr('Allowed files'))}</legend>${kinds.map(([k, l]) => `<label class="chkl"><input type="checkbox" value="${k}" ${lim.default_types.includes(k) ? 'checked' : ''}> ${esc(tr(l))}</label>`).join('')}
      <p class="muted mhint">${esc(tr('Programs, web pages and SVG files are never accepted.'))}</p></fieldset>
    <label class="chkl"><input type="checkbox" id="frq-sub"> ${esc(tr('Put the files into their own subfolder'))}</label>
    <p class="frq-err err" role="alert" hidden></p>
    <div class="foot"><span class="spacer"></span><button type="button" class="btn" data-frq="cancel">${esc(tr('Cancel'))}</button><button type="submit" class="btn pri">${esc(tr('Create link'))}</button></div></form>`);
  md.classList.add('frqnew'); md.setAttribute('aria-labelledby', 'frq-nt');
  const fail = t => { const x = $('.frq-err', md); x.textContent = t; x.hidden = !t; };
  md.addEventListener('click', e => { if (/** @type {any} */ (e.target).closest('[data-frq="cancel"]')) modalClose(md); });
  $('form', md).addEventListener('submit', async e => {
    e.preventDefault();
    const types = $$('.frq-kinds input:checked', md).map(x => x.value), mb = +$('#frq-mb', md).value, nf = +$('#frq-n', md).value;
    const b = {title: $('#frq-title', md).value.trim(), note: $('#frq-note', md).value, expires_at: $('#frq-exp', md).value, tz: evTz(),
      max_mb: mb, max_files: nf, types, subfolder: $('#frq-sub', md).checked};
    if (!b.title) { fail(tr('Title missing')); $('#frq-title', md).focus(); return; }
    if (!b.expires_at) { fail(tr('Please choose until when the link works')); return; }
    if (!types.length) { fail(tr('Please allow at least one kind of file')); return; }
    if (!(mb >= 1 && mb <= lim.max_mb) || !(nf >= 1 && nf <= lim.max_files)) { fail(tr('Please check the limits')); return; }
    let r; try { r = await api('POST', `/api/files/nodes/${n.id}/requests`, b); } catch (x) { fail(x?.message || ''); return; }
    modalClose(md); await done();
    if (r.url) copyText(r.url);
    offerUndo(tr('Link created'), histAdd({label: tr('File request “{0}”', r.title), undo: () => api('DELETE', `/api/files/requests/${r.id}`).then(done).then(() => ({})),
      redo: () => api('POST', `/api/files/requests/${r.id}/restore`).then(done).then(() => ({}))}));
  });
  setTimeout(() => $('#frq-title', md)?.select(), 0);
}

// ---- the file store's history lines, the notification row "filereq" (account.js matrix) and the News line
Object.assign(AB_ACT, {frq_upload: N_('received through a file request'), frq_create: N_('requested files'), frq_revoke: N_('stopped a file request'),
  frq_open: N_('opened a file request again'), frq_delete: N_('removed a file request')});
NOTIF_ROWS.push(['filereq', N_('Files from file requests'), N_('a client uploaded files through your link (one message per link every 10 minutes at most)')]);
NM_NEWS_NEW.filereq = 1; NM_PUSH.filereq = 1;
NEWS_ICON.filereq = 'upload';
