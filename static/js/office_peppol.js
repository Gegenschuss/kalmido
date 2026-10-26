// @ts-check
/* Kalmido web client: Office & finance, e-invoices over the Peppol network (2.154.0 B, #1960; server: kalmido/office/peppol.py).
   The connection block in Office > Settings > Invoices (the own account at a Peppol access point provider: provider, URL,
   account, test mode, own Peppol ID, API key; every field saves itself, the key is never shown again), the menu entries of
   a finalised invoice / credit note (send, UBL download), the send dialog (what is missing, the client's Peppol ID or a
   suggestion from its VAT ID, reachability, the sends with their status) and the status line in the document.
   Classic script sharing the global scope with the others (load order: lazyload.js LD_MODS office). */
'use strict';

const PEP = {conf: null, oid: null, loading: false};
Object.assign(OFD_ACTIONS, {peppol_send: N_('sent over the Peppol network'), peppol_status: N_('Peppol status changed'), peppol_setup: N_('Peppol connection changed'),
  ubl: N_('UBL e-invoice downloaded')});

async function pep_load(draw) {
  PEP.loading = true;
  try { PEP.conf = await api('GET', '/api/office/peppol'); } catch { PEP.conf = {provider: '', providers: [], can_edit: false, error: true}; }
  PEP.loading = false;
  if (draw) { const box = $('#pep-set'); if (box) box.outerHTML = pep_settingsHtml(); }
}
// the configuration is per office area: reload when the area changes
function pep_conf() {
  if (PEP.oid !== OFC.info?.org_id) { PEP.oid = OFC.info?.org_id; PEP.conf = null; }
  if (!PEP.conf && !PEP.loading) setTimeout(() => pep_load(true), 0);
  return PEP.conf;
}

// ---- Office > Settings > Invoices
function pep_settingsHtml() {
  const s = pep_conf();
  const head = `<summary>${tr('E-invoices over the Peppol network')}</summary><p class="muted ofchint">${tr('Through your own Peppol access point provider (own account). The provider bills you directly; Kalmido only connects.')}</p>`;
  if (!s) return `<details class="ofcfree pepset" id="pep-set" data-fg-skip>${head}<p class="muted">${tr('Loading…')}</p></details>`;
  const dis = s.can_edit ? '' : 'disabled', pv = (s.providers || []).find(p => p.id === s.provider);
  const st = s.check_state === 'ok' ? `<span class="pep-ok">${ic('check', 's')} ${tr('Connection works')}</span>` : s.check_text ? `<span class="pep-bad">${esc(s.check_text)}</span>` : '';
  return `<details class="ofcfree pepset" id="pep-set" data-fg-skip ${s.provider ? 'open' : ''}>${head}
    ${ofcRowF('pep-provider', tr('Provider'), `<select id="pep-provider" data-pep="provider" ${dis}><option value="">${esc(tr('Not used'))}</option>${(s.providers || []).map(p => `<option value="${esc(p.id)}" ${p.id === s.provider ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select>`)}
    ${s.provider ? `${pv?.needs_url ? ofcRowF('pep-url', tr('Address of the endpoint'), `<input id="pep-url" data-pep="endpoint_url" type="url" maxlength="300" value="${esc(s.endpoint_url || '')}" placeholder="https://" ${dis}>`, tr('https; the protocol is described in the documentation (office)')) : ''}
    ${pv?.needs_account ? ofcRowF('pep-acc', tr('Account ID at the provider'), `<input id="pep-acc" data-pep="account" maxlength="80" value="${esc(s.account || '')}" inputmode="numeric" ${dis}>`, tr('the id of your company at the provider (legal entity)')) : ''}
    ${ofcRowF('pep-key', tr('API key'), `<input id="pep-key" data-pep="api_key" type="password" autocomplete="off" maxlength="2000" value="" placeholder="${esc(s.key_set ? tr('saved - enter a new one to replace it') : tr('from your provider account'))}" ${dis}>`)}
    <div class="row"><label class="chkl" style="min-width:0"><input type="checkbox" id="pep-sandbox" data-pep="sandbox" ${s.sandbox ? 'checked' : ''} ${dis}> ${esc(tr('Test mode (sandbox of the provider)'))}</label></div>
    ${ofcRowF('pep-sender', tr('Your Peppol ID'), `<span class="lacts"><input id="pep-sender" data-pep="sender_id" maxlength="90" value="${esc(s.sender_id || '')}" placeholder="9930:DE123456789" autocapitalize="characters" ${dis}>${s.sender_suggest && s.can_edit ? `<button type="button" class="btn sm" data-pepa="suggest" data-v="${esc(s.sender_suggest)}">${esc(tr('Use {0}', s.sender_suggest))}</button>` : ''}</span>`, tr('scheme:number, e.g. 0088 (GLN), 0208 (Belgian enterprise number), 9930 (German VAT ID), 0204 (routing ID)'))}
    ${s.can_edit ? `<div class="row"><span class="lacts"><button type="button" class="btn sm" data-pepa="check" ${s.key_set ? '' : 'disabled'}>${ic('sync', 's')}<span>${tr('Check connection')}</span></button><span aria-live="polite">${st}</span></span></div>` : st}` : ''}
    <p class="aerr" role="alert" id="pep-err"></p></details>`;
}
async function pep_save(el) {
  const k = el.dataset.pep, err = $('#pep-err');
  const v = el.type === 'checkbox' ? (el.checked ? 1 : 0) : el.value.trim();
  if (k === 'api_key' && !v) return;
  try {
    PEP.conf = await api('PUT', '/api/office/peppol', {[k]: v});
    if (err) err.textContent = '';
    const box = $('#pep-set'); if (box) box.outerHTML = pep_settingsHtml();
    toast(k === 'api_key' ? tr('API key saved') : tr('Saved'));
  } catch (x) { if (err) err.textContent = x.message || tr('unknown'); }
}
document.addEventListener('change', e => { const el = e.target; if (el instanceof HTMLElement && el.dataset?.pep && el.closest('#pep-set')) pep_save(el); });
document.addEventListener('click', async e => {
  const b = e.target instanceof Element ? e.target.closest('#pep-set [data-pepa]') : null; if (!(b instanceof HTMLElement)) return;
  const err = $('#pep-err');
  if (b.dataset.pepa === 'suggest') { const i = /** @type {HTMLInputElement|null} */ ($('#pep-sender')); if (i) { i.value = b.dataset.v || ''; pep_save(i); } return; }
  if (b.dataset.pepa === 'check') {
    b.setAttribute('disabled', '');
    try { PEP.conf = await api('POST', '/api/office/peppol/check'); const box = $('#pep-set'); if (box) box.outerHTML = pep_settingsHtml(); toast(PEP.conf.ok ? tr('Connection works') : PEP.conf.check_text || tr('unknown')); } catch (x) { if (err) err.textContent = x.message || tr('unknown'); }
    b.removeAttribute('disabled');
  }
});

// ---- a document: menu entries, status line, dialog
const pep_isDoc = d => ['invoice', 'credit'].includes(d?.kind) && d.locked && ofcFeat('docs.einvoice');
function pep_moreItems(d) {
  if (!pep_isDoc(d)) return [];
  const s = pep_conf();
  return [s?.provider ? {label: tr('Send e-invoice over the Peppol network'), icon: 'send', fn: () => pep_dialog(d)} : null,
    {label: tr('E-invoice UBL (Peppol)'), icon: 'download', fn: () => window.open(`/api/office/docs/${d.id}/ubl`, '_blank', 'noopener')}].filter(Boolean);
}
function pep_box(d) {
  const p = d?.peppol; if (!p || !pep_isDoc(d)) return '';
  const cls = p.status === 'delivered' ? 'pep-ok' : ['rejected', 'error'].includes(p.status) ? 'pep-bad' : 'muted';
  return `<p class="pepline"><span class="${cls}">${ic('send', 's')} ${esc(p.status_text)}</span>${p.at ? ` <span class="muted">· ${esc(ofdWhen(p.at))}</span>` : ''}${p.message ? ` <span class="muted">· ${esc(p.message)}</span>` : ''} <button type="button" class="linkbtn" data-pepdoc="${d.id}">${tr('Details')}</button></p>`;
}
document.addEventListener('click', e => { const b = e.target instanceof Element ? e.target.closest('[data-pepdoc]') : null; if (b instanceof HTMLElement && OFD.doc && String(OFD.doc.id) === b.dataset.pepdoc) pep_dialog(OFD.doc); });

function pep_viewHtml(d, v) {
  const fix = v.missing.map(m => `<li>${esc(m.text)}${m.key === 'receiver' && v.receiver_suggest ? ` <button type="button" class="btn sm" data-pepd="take" data-v="${esc(v.receiver_suggest)}">${esc(tr('Use {0}', v.receiver_suggest))}</button>` : ''}</li>`).join('');
  const sends = v.sends.map(x => `<li><b class="${x.status === 'delivered' ? 'pep-ok' : ['rejected', 'error'].includes(x.status) ? 'pep-bad' : ''}">${esc(x.status_text)}</b> <span class="muted">· ${esc(ofdWhen(x.updated_at || x.created_at))} · ${esc(x.receiver_id)}</span>${x.message ? `<br><span class="muted">${esc(x.message)}</span>` : ''}</li>`).join('');
  return `<p class="muted ofchint">${esc(tr('Through your own Peppol access point provider (own account).'))}${v.provider_name ? ` ${esc(v.provider_name)}` : ''}${v.sandbox ? ` <span class="rotag">${tr('Test mode')}</span>` : ''}</p>
    ${fix ? `<div class="pepmiss"><h4>${tr('Still missing')}</h4><ul>${fix}</ul></div>` : ''}
    ${v.receiver_id ? `<div class="row"><label>${tr('Recipient')}</label><span class="lacts"><code>${esc(v.receiver_id)}</code><button type="button" class="btn sm" data-pepd="lookup">${tr('Check reachability')}</button><span id="pep-reach" aria-live="polite"></span></span></div>` : ''}
    ${sends ? `<h4>${tr('Sends')}</h4><ul class="peplist" role="list">${sends}</ul>` : ''}${v.note ? `<p class="muted ofchint">${esc(v.note)}</p>` : ''}`;
}
async function pep_dialog(d) {
  const md = modal(`<h3>${esc(tr('Send e-invoice over the Peppol network'))}</h3><div class="ofddlg" id="pep-dlg"><p class="muted">${tr('Loading…')}</p></div>
    <div class="foot"><span class="aerr" role="alert"></span><span class="spacer"></span><button type="button" class="btn" data-pepd="close">${tr('Close')}</button><button type="button" class="btn" data-pepd="refresh">${ic('sync', 's')}<span>${tr('Refresh')}</span></button><button type="button" class="btn pri" data-pepd="send" hidden>${ic('send', 's')}<span>${tr('Send')}</span></button></div>`);
  const box = () => md.querySelector('#pep-dlg'), aerr = () => md.querySelector('.aerr');
  let v = null;
  const draw = () => {
    const bx = box(); if (bx) bx.innerHTML = pep_viewHtml(d, v);
    const sb = md.querySelector('[data-pepd="send"]');
    if (sb instanceof HTMLElement) { sb.hidden = !(v.can_send); const t = sb.querySelector('span'); if (t) t.textContent = v.can_retry ? tr('Send again') : tr('Send'); }
  };
  const load = async refresh => {
    try { v = await api(refresh ? 'POST' : 'GET', `/api/office/docs/${d.id}/peppol${refresh ? '/refresh' : ''}`); draw(); const a = aerr(); if (a) a.textContent = ''; } catch (x) { const a = aerr(); if (a) a.textContent = x.message || tr('unknown'); }
  };
  md.addEventListener('click', async e => {
    const b = e.target instanceof Element ? e.target.closest('[data-pepd]') : null; if (!(b instanceof HTMLElement)) return;
    const a = b.dataset.pepd, ae = aerr();
    if (a === 'close') { md.remove(); return; }
    b.setAttribute('disabled', '');
    try {
      if (a === 'refresh') await load(true);
      else if (a === 'take') { await api('PATCH', `/api/clients/${v.client_id}`, {peppol_id: b.dataset.v}); toast(tr('Saved at the client')); await load(false); }
      else if (a === 'lookup') { const j = await api('POST', `/api/office/docs/${d.id}/peppol/lookup`); const r = md.querySelector('#pep-reach'); if (r) r.innerHTML = j.reachable ? `<span class="pep-ok">${ic('check', 's')} ${tr('reachable')}</span>` : `<span class="pep-bad">${tr('not reachable over Peppol')}</span>`; }
      else if (a === 'send') {
        if (v.can_retry && !await askConfirm(tr('Send again?'), tr('The last attempt failed or was rejected. Check with your provider that it did not arrive, then send it again.'), {ok: tr('Send again')})) return;
        v = await api('POST', `/api/office/docs/${d.id}/peppol`, v.can_retry ? {again: 1} : {}); draw();
        toast(tr('Sent over the Peppol network')); OFD.log = null; if (typeof ofdLoadList === 'function') OFD.list = null;
        try { const j = await api('GET', `/api/office/docs/${d.id}`); if (OFD.doc && OFD.doc.id === d.id) { OFD.doc = j; ofdDraw(); } } catch { /* the document view refreshes on its next load */ }
      }
      if (ae) ae.textContent = '';
    } catch (x) { if (ae) ae.textContent = x.message || tr('unknown'); if (a === 'send') await load(false); } finally { b.removeAttribute('disabled'); }
  });
  await load(true);
  return md;
}
