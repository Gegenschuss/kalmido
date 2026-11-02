// @ts-check
/* Kalmido web client: Office & finance, online payment of invoices (2.469.0, #3459; server: kalmido/office/payonline.py).
   The block in Office > Settings > Invoices (the own account at the provider: key, webhook secret, the webhook address to copy,
   a short guide; every field saves itself, a secret is never shown again; held payments with Try again / Done, the payouts), and
   in an invoice the switch, the link to copy and what is held.
   Classic script sharing the global scope with the others (load order: lazyload.js LD_MODS office). */
'use strict';

const POL = {conf: null, oid: null, loading: false};
Object.assign(OFD_ACTIONS, {payonline_setup: N_('online payment connection changed'), payonline_switch: N_('online payment switched'), payonline_held_done: N_('held online payment closed')});

async function pol_load(draw) {
  POL.loading = true;
  try { POL.conf = await api('GET', '/api/office/payonline'); } catch { POL.conf = {provider: '', providers: [], can_edit: false, error: true}; }
  POL.loading = false;
  if (draw) pol_redraw();
}
function pol_redraw() { const box = $('#pol-set'); if (box) box.outerHTML = pol_settingsHtml(); }
function pol_conf() {
  if (POL.oid !== OFC.info?.org_id) { POL.oid = OFC.info?.org_id; POL.conf = null; }
  if (!POL.conf && !POL.loading) setTimeout(() => pol_load(true), 0);
  return POL.conf;
}

function pol_heldHtml(rows, adm) {
  return rows.length ? `<ul class="peplist" role="list">${rows.map(h => `<li><b class="pep-bad">${esc(h.text)}</b> <span class="muted">${esc([h.number, h.amount ? ofcMoney(h.amount) : '', h.day ? fmtDateLoc(h.day) : ''].filter(Boolean).join(' · '))}</span>${adm ? `<span class="lacts">${h.reason === 'mismatch' ? '' : `<button type="button" class="btn sm" data-pola="retry" data-id="${h.id}">${tr('Try again')}</button>`}<button type="button" class="btn sm" data-pola="done" data-id="${h.id}">${tr('Done')}</button></span>` : ''}</li>`).join('')}</ul>` : '';
}
// ---- Office > Settings > Invoices
function pol_settingsHtml() {
  const s = pol_conf();
  const head = `<summary>${tr('Online payment of invoices')}</summary><p class="muted ofchint">${tr('Through your own provider account: the money goes directly to you, the provider bills its fees to you, Kalmido charges nothing.')}</p>`;
  if (!s) return `<details class="ofcfree pepset" id="pol-set" data-fg-skip>${head}<p class="muted">${tr('Loading…')}</p></details>`;
  const dis = s.can_edit ? '' : 'disabled';
  const held = pol_heldHtml(s.held || [], s.can_edit);
  return `<details class="ofcfree pepset" id="pol-set" data-fg-skip ${s.provider ? 'open' : ''}>${head}
    ${ofcRowF('pol-provider', tr('Provider'), `<select id="pol-provider" data-pol="provider" ${dis}><option value="">${esc(tr('Not used'))}</option>${(s.providers || []).map(p => `<option value="${esc(p.id)}" ${p.id === s.provider ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select>`)}
    ${s.provider ? `${ofcRowF('pol-key', tr('Secret API key'), `<input id="pol-key" data-pol="secret_key" type="password" autocomplete="off" maxlength="2000" value="" placeholder="${esc(s.key_set ? tr('saved - enter a new one to replace it') : tr('from your provider account'))}" ${dis}>`)}
    ${s.webhook_url ? ofcRowF('pol-url', tr('Webhook address'), `<span class="lacts"><input id="pol-url" readonly value="${esc(s.webhook_url)}"><button type="button" class="btn sm" data-pola="copy">${tr('Copy')}</button></span>`, tr('Enter it at the provider as the webhook endpoint with the events: checkout.session.completed, checkout.session.async_payment_succeeded, checkout.session.async_payment_failed, checkout.session.expired, charge.refunded, charge.dispute.funds_withdrawn, charge.dispute.funds_reinstated, payout.paid.')) : ''}
    ${ofcRowF('pol-sec', tr('Webhook secret'), `<input id="pol-sec" data-pol="webhook_secret" type="password" autocomplete="off" maxlength="2000" value="" placeholder="${esc(s.webhook_secret_set ? tr('saved - enter a new one to replace it') : tr('shown by the provider with the webhook endpoint'))}" ${dis}>`)}
    <div class="row"><label class="chkl" style="min-width:0"><input type="checkbox" id="pol-on" data-pol="enabled" ${s.enabled ? 'checked' : ''} ${dis || (s.key_set && s.webhook_secret_set ? '' : 'disabled')}> ${esc(tr('Offer online payment on invoices'))}</label></div>
    ${s.can_edit ? `<div class="row"><span class="lacts"><button type="button" class="btn sm" data-pola="check" ${s.key_set ? '' : 'disabled'}>${ic('sync', 's')}<span>${tr('Check connection')}</span></button><button type="button" class="btn sm" data-pola="rotate">${tr('New webhook address')}</button></span></div>` : ''}
    ${held ? `<h4>${tr('Payments waiting for you')}</h4>${held}` : ''}
    ${(s.payouts || []).length ? `<h4>${tr('Payouts')}</h4><ul class="peplist" role="list">${s.payouts.map(p => `<li>${esc(fmtDateLoc(p.day))} · ${esc(ofcMoney(p.amount))}${+p.fee ? ` <span class="muted">· ${esc(tr('fees {0}', ofcMoney(p.fee)))}</span>` : ''}</li>`).join('')}</ul>` : ''}` : ''}
    <p class="aerr" role="alert" id="pol-err"></p></details>`;
}
async function pol_save(el) {
  const k = el.dataset.pol, err = $('#pol-err');
  const v = el.type === 'checkbox' ? (el.checked ? 1 : 0) : el.value.trim();
  if ((k === 'secret_key' || k === 'webhook_secret') && !v) return;
  try {
    POL.conf = await api('PUT', '/api/office/payonline', {[k]: v});
    if (err) err.textContent = '';
    pol_redraw();
    toast(tr('Saved'));
  } catch (x) { if (err) err.textContent = x.message || tr('unknown'); }
}
document.addEventListener('change', e => { const el = e.target; if (el instanceof HTMLElement && el.dataset?.pol && el.closest('#pol-set')) pol_save(el); });
document.addEventListener('click', async e => {
  const b = e.target instanceof Element ? e.target.closest('#pol-set [data-pola]') : null; if (!(b instanceof HTMLElement)) return;
  const a = b.dataset.pola, err = $('#pol-err');
  if (a === 'copy') { const i = /** @type {HTMLInputElement|null} */ ($('#pol-url')); try { await navigator.clipboard.writeText(i?.value || ''); toast(tr('Copied')); } catch { i?.select(); } return; }
  try {
    if (a === 'check') { const j = await api('POST', '/api/office/payonline/check'); toast(j.ok ? tr('Connection works') : j.code === 'auth' ? tr('The provider refuses this key') : tr('The provider cannot be reached')); return; }
    if (a === 'rotate') { if (!await askConfirm(tr('New webhook address?'), tr('The old address stops at once: enter the new one at the provider.'), {ok: tr('New webhook address')})) return; POL.conf = await api('POST', '/api/office/payonline/rotate'); }
    if (a === 'retry' || a === 'done') POL.conf = await api('POST', `/api/office/payonline/events/${b.dataset.id}/${a}`);
    pol_redraw();
  } catch (x) { if (err) err.textContent = x.message || tr('unknown'); }
});

// ---- an invoice: the switch, the link, what is held
function pol_box(d) {
  const p = d?.pay_online; if (!p || d.kind !== 'invoice') return '';
  const adm = p.held !== undefined;
  const open = d.locked && !['paid', 'cancelled'].includes(d.status);
  return `<div class="pepline" id="pol-doc"><label class="chkl" style="min-width:0"><input type="checkbox" data-poldoc="on" ${p.on ? 'checked' : ''} ${adm ? '' : 'disabled'}> ${esc(tr('Offer online payment'))}</label>${adm && p.ready && p.on && open ? ` <button type="button" class="linkbtn" data-poldoc="copy">${tr('Copy pay link')}</button>` : ''}${p.held?.length ? pol_heldHtml(p.held, false) : ''}</div>`;
}
document.addEventListener('change', async e => {
  const el = /** @type {HTMLInputElement} */ (e.target); if (el.dataset?.poldoc !== 'on' || !OFD.doc) return;
  try { OFD.doc.pay_online = await api('PUT', `/api/office/docs/${OFD.doc.id}/pay-online`, {on: el.checked ? 1 : 0}); ofdDraw(); } catch (x) { toast(x.message || tr('unknown')); el.checked = !el.checked; }
});
document.addEventListener('click', async e => {
  const b = e.target instanceof Element ? e.target.closest('[data-poldoc="copy"]') : null; if (!(b instanceof HTMLElement) || !OFD.doc) return;
  try {
    const j = await api('PUT', `/api/office/docs/${OFD.doc.id}/pay-online`, {on: 1});  // the link is made on this first need
    OFD.doc.pay_online = j;
    await navigator.clipboard.writeText(j.url || '');
    toast(tr('Link copied'));
  } catch (x) { toast(x.message || tr('unknown')); }
});
