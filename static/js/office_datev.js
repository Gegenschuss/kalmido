/* Kalmido web client: Office & finance, the DATEV booking batch export (2.47.3, #1460): the settings block (advisor and
   client number, chart, accounts) inside the office settings and the export dialog of the invoice list (period ->
   EXTF CSV download). Classic script sharing the global scope with the others (load order: index.html). */
'use strict';

const DX_CASES = [['standard', N_('Revenue at the standard rate')], ['reduced', N_('Revenue at the reduced rate')], ['exempt', N_('Tax-exempt revenue')],
  ['reverse', N_('Reverse charge (services in the EU)')], ['abroad', N_('Not taxable domestically')], ['small', N_('Small business (no VAT)')],
  // 2.355.0 C (#2840): the cash discounts granted
  ['skonto_standard', N_('Cash discount at the standard rate')], ['skonto_reduced', N_('Cash discount at the reduced rate')], ['skonto_other', N_('Cash discount without VAT')],
  // 2.355.0 C (#2844): reverse = services to EU businesses (8336); section 13b at home, goods to the EU, exports
  ['reverse_dom', N_('Reverse charge at home (section 13b)')], ['eu_goods', N_('Goods to businesses in the EU')], ['export', N_('Exports of goods')]];
const DX_CHART = {SKR03: {standard: '8400', reduced: '8300', exempt: '8100', reverse: '8336', abroad: '8338', small: '8195', skonto_standard: '8736', skonto_reduced: '8731', skonto_other: '8730', reverse_dom: '8337', eu_goods: '8125', export: '8120', debtor: '10000', bank: '1200', cash: '1000'},
  SKR04: {standard: '4400', reduced: '4300', exempt: '4100', reverse: '4336', abroad: '4338', small: '4185', skonto_standard: '4736', skonto_reduced: '4731', skonto_other: '4730', reverse_dom: '4337', eu_goods: '4125', export: '4120', debtor: '10000', bank: '1800', cash: '1600'}};
const dx_months = () => Array.from({length: 12}, (_, i) => [i + 1, new Date(2026, i, 1).toLocaleDateString(S.lang || undefined, {month: 'long'})]);
const dx_ph = (st, k) => { const d = (DX_CHART[st.chart] || DX_CHART.SKR03)[k] || ''; return d.padEnd((+st.acct_len || 4) + (k === 'debtor' ? 1 : 0), '0'); };

// the block in Office > Settings > Invoices (admins edit, members see); 2.148.0 D (#2458): + the DATEV import (office_datevimp.js)
// 2.298.0 A2 (#3186): one sentence on top says where the values come from (no "from your tax advisor" per field)
function dx_settingsHtml(s, dis) {
  const st = Object.assign({advisor_no: '', client_no: '', fy_start: 1, acct_len: 4, chart: 'SKR03', accounts: {}, bu: {}, debtor: '', bank: '', cash: ''}, s.datev_extf || {});
  const num = (id, v, mx, ph) => `<input id="${id}" value="${esc(String(v ?? ''))}" inputmode="numeric" maxlength="${mx}" class="numin" ${ph ? `placeholder="${esc(ph)}"` : ''} ${dis}>`;
  return `<details class="ofcfree dxset"><summary>${tr('DATEV export (booking batch)')}</summary>
    <p class="muted ofchint">${tr('These values come from your tax advisor; empty account fields use the default account.')}</p>
    ${ofcRowF('dx-adv', tr('Advisor number'), num('dx-adv', st.advisor_no, 7))}
    ${ofcRowF('dx-cli', tr('Client number'), num('dx-cli', st.client_no, 5))}
    ${ofcRowF('dx-fy', tr('Fiscal year starts in'), ofcSel('dx-fy', st.fy_start, dx_months()))}
    ${ofcRowF('dx-chart', tr('Chart of accounts'), ofcSel('dx-chart', st.chart, [['SKR03', 'SKR03'], ['SKR04', 'SKR04']]))}
    ${ofcRowF('dx-len', tr('Length of the ledger accounts'), ofcSel('dx-len', st.acct_len, [4, 5, 6, 7, 8].map(n => [n, String(n)])), tr('usually 4'))}
    ${DX_CASES.map(([k, n]) => ofcRowF('dx-a-' + k, tr(n), `<span class="lacts">${num('dx-a-' + k, st.accounts[k], 8, dx_ph(st, k))}${k === 'small' ? '' : `<label for="dx-bu-${k}" class="muted">${tr('Tax key')}</label>${num('dx-bu-' + k, st.bu[k], 4)}`}</span>`)).join('')}
    ${ofcRowF('dx-debtor', tr('Collective debtor'), num('dx-debtor', st.debtor, 9, dx_ph(st, 'debtor')), tr('account for all clients without their own debtor number'))}
    ${ofcRowF('dx-bank', tr('Bank account'), num('dx-bank', st.bank, 8, dx_ph(st, 'bank')), tr('payments by transfer or card'))}
    ${ofcRowF('dx-cash', tr('Cash account'), num('dx-cash', st.cash, 8, dx_ph(st, 'cash')), tr('payments in cash'))}
    ${typeof ofcAdmin === 'function' && ofcAdmin() && !dis ? dv_settingsHtml(st) : ''}
    ${!dis && typeof dimp_sectionHtml === 'function' ? dimp_sectionHtml() : ''}
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
const dx_btn = () => typeof ofcAdmin === 'function' && ofcAdmin() && !ofr_noSp('books', 'export') /* 2.187.0 A (#2476) */ ? `<button class="btn sm" type="button" data-dx="extf">${ic('download', 's')}<span>${tr('DATEV export')}</span></button>` : '';
const dx_iso = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
function dx_dialog() {
  const n = new Date(), from = new Date(n.getFullYear(), n.getMonth() - 1, 1), to = new Date(n.getFullYear(), n.getMonth(), 0);
  let checked = '';  // 2.148.0 B (#2470): with receipt images the first press checks, the second downloads
  const md = ofdDlg(tr('DATEV export'), `<p class="muted ofchint">${tr('Finalised invoices, credit notes and payments of the period as a DATEV booking batch (CSV) for your tax advisor.')}</p>
    <div class="row"><label id="dx-fl">${tr('From')}</label>${dateIn('dx-from', dx_iso(from), {label: tr('From'), clear: false})}</div>
    <div class="row"><label id="dx-tl">${tr('To')}</label>${dateIn('dx-to', dx_iso(to), {label: tr('To'), clear: false, after: 'dx-from'})}</div>
    ${ofcChk('dx-in', tr('Include receipts and travel expenses'), (OFC.info?.settings?.datev_extf || {}).in_on ?? 1)}
    ${ofcChk('dx-img', tr('With receipt images (ZIP for DATEV Unternehmen online)'), 1)}
    ${ofcChk('dx-locked', tr('Only locked months'), 0)}
    ${ofcChk('dx-dups', tr('Include possibly duplicate receipts'), 0)}
    <div class="muted" id="dx-res" aria-live="polite"></div>`, tr('Download'), async m => {
    const img = !!$('#dx-img', m)?.checked;
    // 2.146.0 B (#2452): possible duplicates stay out unless ticked (the toast names how many)
    const q = `from=${encodeURIComponent($('#dx-from', m).value)}&to=${encodeURIComponent($('#dx-to', m).value)}${$('#dx-in', m)?.checked ? '' : '&in=0'}${$('#dx-locked', m)?.checked ? '&locked=1' : ''}${$('#dx-dups', m)?.checked ? '&dups=1' : ''}`;
    const url = img ? '/api/office/datev/zip' : '/api/office/datev/extf';
    if (img && checked !== q) {  // first press (or changed fields): show what is missing before the download
      const j = await api('GET', `${url}?${q}&check=1`);
      checked = q;
      const res = $('#dx-res', m); if (res) res.innerHTML = dx_checkHtml(j);
      const ok = $('[data-m="ok"]', m); if (ok) ok.textContent = tr('Download');
      return false;
    }
    const j = img ? null : await api('GET', `${url}?${q}&check=1`);
    const a = document.createElement('a'); a.href = `${url}?${q}`; a.download = j?.file || ''; document.body.appendChild(a); a.click(); a.remove();
    if (j) toast([j.count === 1 ? tr('1 booking exported') : tr('{0} bookings exported', j.count), ...(j.hints || []).map(h => h.text)].join('. '));  // 2.120.0 C (#2090)
  });
  const ok = $('[data-m="ok"]', md); if (ok) ok.textContent = tr('Check');
  md.addEventListener('change', e => { if (/** @type {any} */ (e.target).id === 'dx-img') { const b = $('[data-m="ok"]', md); if (b) b.textContent = /** @type {any} */ (e.target).checked && !checked ? tr('Check') : tr('Download'); } });
  return md;
}
// 2.148.0 B (#2470): the check of the ZIP: bookings, files, receipts without a booking, bookings without a receipt
function dx_checkHtml(j) {
  const li = x => `<li>${esc([fmtDateLoc(x.date), x.title || x.text || '', x.amount ? ofcMoney(x.amount) : ''].filter(Boolean).join(' · '))}</li>`;
  const nb = j.no_booking || [], nr = j.no_receipt || [];
  return `<p>${esc(tr('{0} bookings, {1} receipt files ({2} to {3})', j.count, j.files, fmtDateLoc(j.from), fmtDateLoc(j.to)))}</p>
    ${(j.hints || []).map(h => `<p>${esc(h.text)}</p>`).join('')}
    ${nb.length ? `<details class="dxchk"><summary>${esc(trn('{0} receipt without a booking (no amount)', '{0} receipts without a booking (no amount)', nb.length))}</summary><ul>${nb.map(li).join('')}</ul></details>` : ''}
    ${nr.length ? `<details class="dxchk"><summary>${esc(trn('{0} booking without a receipt', '{0} bookings without a receipt', nr.length))}</summary><ul>${nr.map(li).join('')}</ul></details>` : ''}
    ${!nb.length && !nr.length ? `<p>${esc(tr('Every booking has its receipt.'))}</p>` : ''}`;
}
document.addEventListener('click', e => { const b = e.target.closest?.('[data-dx="extf"]'); if (b) dx_dialog(); });

// 2.120.0 C (#2090): the input side of the batch (receipts, travel expenses): its own section, every field saves itself on
// change (one undo step in the toast), the accounts of the receipt categories come from the server
const DV_TRAVEL = [['fares', N_('Travel: fares')], ['hotel', N_('Travel: hotel')], ['vma', N_('Per diem')], ['other', N_('Travel: other costs')]];
const DV = {acc: null, oid: null};
async function dv_load() {
  try { DV.acc = await api('GET', '/api/office/datev/accounts'); } catch (x) { DV.acc = {categories: [], travel: [], error: x.message || tr('unknown')}; }
  const box = $('#dv-acc'); if (box) box.innerHTML = dv_accHtml();
}
function dv_accHtml() {
  const a = DV.acc; if (!a) return `<p class="muted">${tr('Loading…')}</p>`;
  if (a.error) return `<p class="muted">${esc(a.error)}</p>`;
  const num = (k, name, v, ph, label) => `<input value="${esc(v || '')}" inputmode="numeric" maxlength="8" class="numin" data-dv="${k}" data-name="${esc(name)}" placeholder="${esc(ph)}" aria-label="${esc(label)}">`;
  const cats = a.categories.length ? a.categories.map(c => `<div class="row"><label>${esc(c.name)}</label>${num('cat', c.name, c.account, c.default, tr('Expense account for {0}', c.name))}</div>`).join('')
    : `<p class="muted ofchint">${tr('No receipt categories yet.')}</p>`;
  return `<h4>${tr('Expense accounts of the receipt categories')}</h4>${cats}
    <h4>${tr('Travel expenses')}</h4>${a.travel.map(t => `<div class="row"><label>${esc(tr((DV_TRAVEL.find(x => x[0] === t.key) || [, t.key])[1]))}</label>${num('travel', t.key, t.account, t.default, tr((DV_TRAVEL.find(x => x[0] === t.key) || [, t.key])[1]))}</div>`).join('')}`;
}
function dv_settingsHtml(st) {
  if (DV.oid !== OFC.info?.org_id || !DV.acc) { DV.oid = OFC.info?.org_id; DV.acc = null; setTimeout(dv_load, 0); }
  const bu = st.bu_in || {}, num = (id, k, v, mx, ph) => `<input id="${id}" value="${esc(String(v ?? ''))}" inputmode="numeric" maxlength="${mx}" class="numin" data-dv="${k}" ${ph ? `placeholder="${esc(ph)}"` : ''}>`;
  const ph = (n, plus) => n.padEnd((+st.acct_len || 4) + (plus || 0), '0');
  return `<section class="dvset" data-fg-skip aria-labelledby="dv-h"><h4 id="dv-h">${tr('Receipts and travel expenses')}</h4>
    <p class="muted ofchint">${tr('Receipts with an amount and travel expenses go into the same booking batch.')}</p>
    <div class="row"><label class="chkl" style="min-width:0"><input type="checkbox" id="dv-on" data-dv="in_on" ${st.in_on ?? 1 ? 'checked' : ''}> ${tr('Include receipts and travel expenses')}</label></div>
    ${ofcRowF('dv-counter', tr('Counter account of the receipts'), `<select id="dv-counter" data-dv="in_counter">${[['creditor', tr('Collective creditor')], ['bank', tr('Bank account')]].map(([v, n]) => `<option value="${v}" ${(st.in_counter || 'creditor') === v ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select>`)}
    ${ofcRowF('dv-cred', tr('Collective creditor'), num('dv-cred', 'creditor', st.creditor, 9, ph('7', 1)))}
    ${ofcRowF('dv-other', tr('Other expenses'), num('dv-other', 'in_other', st.in_other, 8, ph(st.chart === 'SKR04' ? '63' : '49')), tr('receipts without a category or a known one'))}
    ${ofcRowF('dv-bu19', tr('Input tax key 19 %'), num('dv-bu19', 'bu19', bu['19'], 4, '9'))}
    ${ofcRowF('dv-bu7', tr('Input tax key 7 %'), num('dv-bu7', 'bu7', bu['7'], 4, '8'))}
    <div id="dv-acc">${dv_accHtml()}</div>
    <p class="aerr" role="alert" id="dv-err"></p></section>`;
}
function dv_body(el) {
  const k = el.dataset.dv, v = el.type === 'checkbox' ? (el.checked ? 1 : 0) : el.value.trim(), st = OFC.info?.settings?.datev_extf || {};
  if (k === 'cat') return {cat_accounts: Object.assign({}, st.cat_accounts || {}, {[el.dataset.name.toLowerCase()]: v})};
  if (k === 'travel') return {travel: Object.assign({}, st.travel || {}, {[el.dataset.name]: v})};
  if (k === 'bu19' || k === 'bu7') return {bu_in: Object.assign({}, st.bu_in || {}, {[k.slice(2)]: v})};
  return {[k]: v};
}
async function dv_save(el) {
  const err = $('#dv-err'), before = JSON.parse(JSON.stringify(OFC.info?.settings?.datev_extf || {})), b = dv_body(el);
  const old = Object.fromEntries(Object.keys(b).map(k => [k, before[k] ?? (typeof b[k] === 'object' ? {} : '')]));
  const put = async x => { const j = await api('PUT', '/api/office/settings', {datev_extf: x}); OFC.info.settings = j.settings; };
  try {
    await put(b); if (err) err.textContent = '';
    toast(tr('Saved'), async () => { await put(old); DV.acc = null; ofcDraw(); });
  } catch (x) { if (err) err.textContent = x.message || tr('unknown'); }
}
document.addEventListener('change', e => { const el = e.target; if (el.dataset?.dv && el.closest?.('.dvset')) dv_save(el); });
