// @ts-check
// 2.144.3 B (#2054): payment reminders suggested for overdue invoices + the GiroCode. The watchdog makes reminder DRAFTS
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
    ${ofcChk('os-girocode', tr('GiroCode on invoices and reminders (QR code for banking apps, EUR only)'), +(s.girocode ?? 1))}`;
}
const dun_settingsBody = form => $('#os-dun-on', form) ? {dunning_suggest: $('#os-dun-on', form).checked ? 1 : 0, dunning_grace_days: ofcNum($('#os-dun-days', form).value), girocode: $('#os-girocode', form)?.checked ? 1 : 0} : {};
