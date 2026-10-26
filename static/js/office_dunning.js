// @ts-check
// 2.147.1 B (#2054): payment reminders suggested for overdue invoices + the GiroCode. The watchdog makes reminder DRAFTS
// (server: kalmido/office/dunning.py); the invoice list shows how many wait with a jump to them, the reminder list marks
// them. Nothing is sent without a person (the usual send dialog). The office settings: suggestions on / off, the days
// after the due date, the GiroCode on invoices + reminders (kalmido/office/girocode.py).
'use strict';

// the hint above the invoice / reminder list (OFD.dunning comes with GET /api/office/docs)
function dun_listHint(k) {
  const n = +(OFD.dunning?.suggested || 0);
  if (!n || (k !== 'invoice' && k !== 'reminder')) return '';
  const txt = n === 1 ? tr('1 payment reminder suggested') : tr('{0} payment reminders suggested', n);
  if (k === 'reminder') return `<p class="dun-hint" role="status">${ic('clock', 's')}<span>${esc(txt)} · ${esc(tr('Check the drafts and send them yourself - nothing goes out automatically.'))}</span></p>`;
  return `<button type="button" class="dun-hint dun-go" data-ofd="dun-open">${ic('clock', 's')}<span>${esc(txt)}</span><span class="muted">${esc(tr('Show drafts'))}</span>${ic('chev', 's')}</button>`;
}
// a suggested draft in the reminder list
const dun_rowTag = r => r.suggested ? `<small class="rotag dun-tag">${esc(tr('suggested'))}</small>` : '';
// the jump: the reminder tab with its drafts
function dun_open() { OFD.kind = 'reminder'; OFD.status = 'draft'; OFD.list = null; ofdLoadList(true); }

// the office settings (section Invoices)
function dun_settingsHtml(s, dis) {
  return `${ofcChk('os-dun-on', tr('Suggest payment reminders for overdue invoices'), +(s.dunning_suggest ?? 1))}
    ${ofcRowF('os-dun-days', tr('Suggest after'), `<span class="lacts"><input id="os-dun-days" value="${esc(String(s.dunning_grace_days ?? 7))}" inputmode="numeric" class="numin" maxlength="2" ${dis}><span class="muted">${tr('days')}</span></span>`, tr('after the due date or the last reminder\'s deadline; only drafts, you send them'))}
    ${ofcChk('os-girocode', tr('GiroCode on invoices and reminders (QR code for banking apps, EUR only)'), +(s.girocode ?? 1))}
    ${ofcChk('os-dun-int', tr('Default interest on reminders (base rate + 5 points, businesses + 9)'), +(s.dunning_interest ?? 0))}
    ${ofcChk('os-dun-flat', tr('40 EUR flat fee on reminders to businesses (per invoice)'), +(s.dunning_flat_fee ?? 0))}
    ${ofcRowF('os-dun-base', tr('Base rate'), `<span class="lacts"><input id="os-dun-base" value="${esc(fmtNum(s.base_rate ?? 1.52, 2))}" inputmode="decimal" class="numin" maxlength="6" ${dis}><span class="muted">%</span></span>`, tr('published by the Bundesbank each 1 January and 1 July; please update it then'))}
    ${ofcRowF('os-dun-kind', tr('Clients count as'), ofcSel('os-dun-kind', s.dunning_client_kind || 'auto', [['auto', tr('businesses if they have a VAT ID, buyer reference or Peppol ID')], ['business', tr('all businesses')], ['consumer', tr('all consumers')]]), tr('decides the interest rate and the flat fee'))}`;
}
// 2.355.0 D (#2846): + default interest, flat fee, base rate, who counts as a business (all off by default)
const dun_settingsBody = form => $('#os-dun-on', form) ? {dunning_suggest: $('#os-dun-on', form).checked ? 1 : 0, dunning_grace_days: ofcNum($('#os-dun-days', form).value), girocode: $('#os-girocode', form)?.checked ? 1 : 0,
  ...($('#os-dun-int', form) ? {dunning_interest: $('#os-dun-int', form).checked ? 1 : 0, dunning_flat_fee: $('#os-dun-flat', form).checked ? 1 : 0, base_rate: ofcNum($('#os-dun-base', form).value), dunning_client_kind: $('#os-dun-kind', form).value} : {})} : {};
