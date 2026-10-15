/* Kalmido web client: Office & finance, the DATEV booking batch export (2.47.3, #1460): the settings block (advisor and
   client number, chart, accounts) inside the office settings and the export dialog of the invoice list (period ->
   EXTF CSV download). Classic script sharing the global scope with the others (load order: index.html). */
'use strict';

const DX_CASES = [['standard', N_('Revenue at the standard rate')], ['reduced', N_('Revenue at the reduced rate')], ['exempt', N_('Tax-exempt revenue')],
  ['reverse', N_('Reverse charge')], ['abroad', N_('Not taxable domestically')], ['small', N_('Small business (no VAT)')]];
const DX_CHART = {SKR03: {standard: '8400', reduced: '8300', exempt: '8100', reverse: '8337', abroad: '8338', small: '8195', debtor: '10000', bank: '1200', cash: '1000'},
  SKR04: {standard: '4400', reduced: '4300', exempt: '4100', reverse: '4337', abroad: '4338', small: '4185', debtor: '10000', bank: '1800', cash: '1600'}};
const dx_months = () => Array.from({length: 12}, (_, i) => [i + 1, new Date(2026, i, 1).toLocaleDateString(S.lang || undefined, {month: 'long'})]);
const dx_ph = (st, k) => { const d = (DX_CHART[st.chart] || DX_CHART.SKR03)[k] || ''; return d.padEnd((+st.acct_len || 4) + (k === 'debtor' ? 1 : 0), '0'); };

// the block in Office > Settings > Invoices (admins edit, members see)
function dx_settingsHtml(s, dis) {
  const st = Object.assign({advisor_no: '', client_no: '', fy_start: 1, acct_len: 4, chart: 'SKR03', accounts: {}, bu: {}, debtor: '', bank: '', cash: ''}, s.datev_extf || {});
  const num = (id, v, mx, ph) => `<input id="${id}" value="${esc(String(v ?? ''))}" inputmode="numeric" maxlength="${mx}" class="numin" ${ph ? `placeholder="${esc(ph)}"` : ''} ${dis}>`;
  return `<details class="ofcfree dxset"><summary>${tr('DATEV export (booking batch)')}</summary>
    <p class="muted ofchint">${tr('The tax advisor imports the file into DATEV. Empty account fields use the chart’s default account.')}</p>
    ${ofcRowF('dx-adv', tr('Advisor number'), num('dx-adv', st.advisor_no, 7), tr('from your tax advisor'))}
    ${ofcRowF('dx-cli', tr('Client number'), num('dx-cli', st.client_no, 5), tr('from your tax advisor'))}
    ${ofcRowF('dx-fy', tr('Fiscal year starts in'), ofcSel('dx-fy', st.fy_start, dx_months()))}
    ${ofcRowF('dx-chart', tr('Chart of accounts'), ofcSel('dx-chart', st.chart, [['SKR03', 'SKR03'], ['SKR04', 'SKR04']]))}
    ${ofcRowF('dx-len', tr('Length of the ledger accounts'), ofcSel('dx-len', st.acct_len, [4, 5, 6, 7, 8].map(n => [n, String(n)])), tr('usually 4'))}
    ${DX_CASES.map(([k, n]) => ofcRowF('dx-a-' + k, tr(n), `<span class="lacts">${num('dx-a-' + k, st.accounts[k], 8, dx_ph(st, k))}${k === 'small' ? '' : `<label for="dx-bu-${k}" class="muted">${tr('Tax key')}</label>${num('dx-bu-' + k, st.bu[k], 4)}`}</span>`)).join('')}
    ${ofcRowF('dx-debtor', tr('Collective debtor'), num('dx-debtor', st.debtor, 9, dx_ph(st, 'debtor')), tr('a client whose customer number is a debtor number gets its own'))}
    ${ofcRowF('dx-bank', tr('Bank account'), num('dx-bank', st.bank, 8, dx_ph(st, 'bank')), tr('payments by transfer or card'))}
    ${ofcRowF('dx-cash', tr('Cash account'), num('dx-cash', st.cash, 8, dx_ph(st, 'cash')), tr('payments in cash'))}
  </details>`;
}
function dx_settingsBody(form) {
  if (!$('#dx-adv', form)) return {};
  const v = id => ($('#' + id, form)?.value || '').trim(), acc = {}, bu = {};
  for (const [k] of DX_CASES) { acc[k] = v('dx-a-' + k); if (k !== 'small') bu[k] = v('dx-bu-' + k); }
  return {datev_extf: {advisor_no: v('dx-adv'), client_no: v('dx-cli'), fy_start: +v('dx-fy') || 1, chart: v('dx-chart') || 'SKR03', acct_len: +v('dx-len') || 4,
    accounts: acc, bu, debtor: v('dx-debtor'), bank: v('dx-bank'), cash: v('dx-cash')}};
}

// the button in the invoice list (admins only) and its dialog: period (default the previous month) -> check -> download
const dx_btn = () => typeof ofcAdmin === 'function' && ofcAdmin() ? `<button class="btn sm" type="button" data-dx="extf">${ic('download', 's')}<span>${tr('DATEV export')}</span></button>` : '';
const dx_iso = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
function dx_dialog() {
  const n = new Date(), from = new Date(n.getFullYear(), n.getMonth() - 1, 1), to = new Date(n.getFullYear(), n.getMonth(), 0);
  const md = ofdDlg(tr('DATEV export'), `<p class="muted ofchint">${tr('Finalised invoices, credit notes and payments of the period as a DATEV booking batch (CSV) for your tax advisor.')}</p>
    <div class="row"><label for="dx-from">${tr('From')}</label><input id="dx-from" type="date" value="${dx_iso(from)}"></div>
    <div class="row"><label for="dx-to">${tr('To')}</label><input id="dx-to" type="date" value="${dx_iso(to)}"></div>
    <p class="muted" id="dx-res" aria-live="polite"></p>`, tr('Download'), async m => {
    const q = `from=${encodeURIComponent($('#dx-from', m).value)}&to=${encodeURIComponent($('#dx-to', m).value)}`;
    const j = await api('GET', `/api/office/datev/extf?${q}&check=1`);
    const a = document.createElement('a'); a.href = `/api/office/datev/extf?${q}`; a.download = j.file || ''; document.body.appendChild(a); a.click(); a.remove();
    toast(j.count === 1 ? tr('1 booking exported') : tr('{0} bookings exported', j.count));
  });
  return md;
}
document.addEventListener('click', e => { const b = e.target.closest?.('[data-dx="extf"]'); if (b) dx_dialog(); });
