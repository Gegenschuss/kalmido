// 2.90.0 A (#1921): bookkeeping light in the office (tab "Bookkeeping"): EUeR, VAT return figures, receipt photo
// Admins of the office area only (a personal office: its owner). On top a big button "Photograph receipt" (camera on the
// phone, the file dialog on a desktop; PDF too) -> a document in the office's documents space and a small sheet (category,
// VAT rate, amount, date; prefilled once the recognition is done); below the receipts of this month, the income/expense
// statement of the year (CSV / PDF), the VAT return figures of a month / quarter (#office/books/ustva jumps there), the
// settings (tax reserve, VAT on payment / on invoicing) and the tax dates of part C (txdSectionHtml). Server:
// kalmido/office/books.py. No tax advice: every part carries the same short note.
const BK = {oid: null, year: new Date().getFullYear(), info: null, euer: null, ustva: null, mode: null, period: null, err: null, seq: 0, jumped: false};
BK.billed = {};  // 2.121.0 C (#2094): receipts billed on to a client {node_id: {doc_id, number, kind}}
const BK_VATS = [['19', '19 %'], ['7', '7 %'], ['0', '0 %']];
OFC_TABS.splice(OFC_TABS.findIndex(t => t[0] === 'settings'), 0, ['books', 'book', N_('Bookkeeping'), 1, () => bkTabHtml(), 'money']);  // admins only; 2.92.1 (#1917): in the menu group Money

const bkSub = () => (location.hash.split('/')[2] || '');
const bkNote = () => `<p class="muted bk-note">${esc(tr('No tax advice; figures without guarantee.'))}</p>`;
const bkVatLabel = v => v == null ? tr('VAT rate unknown') : tr('VAT {0} %', v);
function bkDefaultPeriod(mode) {  // the period one files now: the last month / quarter
  const d = new Date(); d.setDate(1);
  if (mode === 'year') return {year: d.getFullYear() - 1, period: 'y'};  // 2.122.0 D (#2315): the annual return of last year
  if (mode === 'month') { d.setMonth(d.getMonth() - 1); return {year: d.getFullYear(), period: 'm' + String(d.getMonth() + 1).padStart(2, '0')}; }
  const q = Math.floor(d.getMonth() / 3); return q ? {year: d.getFullYear(), period: 'q' + q} : {year: d.getFullYear() - 1, period: 'q4'};
}
function bkReset() {
  const m = OFC.info?.settings?.tax_dates?.ustva;
  BK.mode = m === 'month' ? 'month' : m === 'year' ? 'year' : 'quarter';
  const p = bkDefaultPeriod(BK.mode);
  Object.assign(BK, {oid: OFC.info?.org_id, info: null, euer: null, ustva: null, err: null, period: p.period, pyear: p.year, jumped: false});
}
async function bkLoad() {
  const seq = ++BK.seq, y = BK.year, q = `year=${BK.pyear}&period=${BK.period}`;
  try {
    const [info, euer, ustva] = await Promise.all([api('GET', `/api/office/books?year=${y}`), api('GET', `/api/office/books/euer?year=${y}`), api('GET', `/api/office/books/ustva?${q}`)]);
    if (seq !== BK.seq) return;
    BK.billed = await bkBilledLoad(info);
    if (seq !== BK.seq) return;
    Object.assign(BK, {info, euer, ustva, err: null});
  } catch (x) { if (seq === BK.seq) BK.err = x.message || tr('unknown'); }
  ofcDraw();
}
async function bkBilledLoad(info) {  // 2.121.0 C (#2094)
  const ids = [...new Set([...(info.receipts || []), ...(info.missing || [])].map(r => r.node_id))];
  if (!ids.length) return {};
  try { return (await api('GET', `/api/office/receipts/billed?ids=${ids.join(',')}`)).billed || {}; } catch { return {}; }
}
// 2.121.0 review N4: billed by another office before a move (no kind) -> the plain note
const bkBilledTxt = b => !b ? '' : !b.kind ? tr('A receipt has already been billed') : tr('billed on {0} {1}', b.kind === 'invoice' ? tr('Invoice') : tr('Quotation'), b.number || tr('Draft'));
async function bkLoadUstva() {
  const seq = ++BK.seq;
  try { const j = await api('GET', `/api/office/books/ustva?year=${BK.pyear}&period=${BK.period}`); if (seq === BK.seq) BK.ustva = j; }
  catch (x) { toast(x.message || tr('unknown')); }
  ofcDraw();
}
const bkReload = () => { BK.info = null; BK.euer = null; if (typeof RKF === 'object') RKF.data = null; ofcDraw(); };  // 2.114.1 B (#2018): receipts count in the cash flow

function bkTabHtml() {
  if (bkSub() === 'procdoc' && typeof pdHtml === 'function') return pdHtml();  // 2.148.0 C (#2472): the procedure documentation
  if (BK.oid !== OFC.info?.org_id || !BK.period) bkReset();  // another office area
  if (!ofcAdmin()) return `<div class="empty">${tr('Only the admins of the office see the bookkeeping.')}</div>`;
  if (BK.err) return `<div class="empty">${esc(BK.err)}</div>`;
  if (!BK.info || !BK.euer || !BK.ustva) { if (!BK.loadingT) BK.loadingT = setTimeout(() => { BK.loadingT = 0; bkLoad(); }, 0); return `<p class="muted lempty">${tr('Loading…')}</p>`; }
  if (bkSub() === 'ustva' && !BK.jumped) { BK.jumped = true; setTimeout(() => $('#bk-ustva')?.scrollIntoView({block: 'start'}), 0); }
  const yNow = new Date().getFullYear(), years = [];
  for (let y = yNow + 1; y >= yNow - 6; y--) years.push([y, String(y)]);
  const head = `<div class="ofcbar bk-bar"><label class="bk-year"><span class="muted">${tr('Year')}</span>${ofcSel('bk-year', BK.year, years)}</label><span class="spacer"></span>
    <a class="btn sm ghost" href="#office/books/procdoc" data-bk-procdoc>${ic('file', 's')}<span>${tr('Procedure documentation')}</span></a></div>
    <div class="bk-photo"><label class="btn pri bk-shot">${ic('camera')}<span>${tr('Photograph receipt')}</span><input type="file" id="bk-file" accept="image/*,application/pdf" capture="environment" hidden></label>
    <span class="muted bk-photohint">${tr('The receipt goes into the documents; amount and date are recognised.')}</span></div>`;
  const txd = typeof txdSectionHtml === 'function' ? txdSectionHtml() : '';  // part C: the tax dates
  const dob = typeof dimp_obHtml === 'function' ? dimp_obHtml(BK.year) : '';  // 2.148.0 D (#2458): opening balances of the DATEV import
  const plk = typeof plSectionHtml === 'function' ? plSectionHtml() : '';  // 2.148.0 A (#2471): lock periods + auditor export
  return head + bkReceiptsHtml() + bkEuerHtml() + bkUstvaHtml() + bkSettingsHtml() + txd + dob + plk;
}

function bkRcRow(r) {
  return `<li><button type="button" class="ofcrow" data-bk="rc" data-id="${r.node_id}"><span class="ofcn"><b>${esc(r.title || tr('Receipt'))}</b>
    <small class="muted">${esc([fmtDateLoc(r.date), r.category, bkVatLabel(r.vat_pct), bkBilledTxt(BK.billed[r.node_id])].filter(Boolean).join(' · '))}</small></span>
    ${r.vat_pct == null && !BK.info.small_business ? `<span class="rotag bk-miss">${tr('without VAT rate')}</span>` : ''}<span class="rksum">${ofcMoney(r.amount)}</span>${ic('chev', 's')}</button></li>`;
}
function bkReceiptsHtml() {
  const d = BK.info, rs = d.receipts || [], miss = d.missing || [];
  const missHtml = miss.length ? `<details class="bk-missing"><summary>${esc(trn('{0} receipt without VAT rate', '{0} receipts without VAT rate', miss.length))} · ${tr('add it')}</summary>
    <ul class="ofclist" role="list">${miss.map(bkRcRow).join('')}</ul></details>` : '';
  const billable = rs.some(r => !BK.billed[r.node_id]);
  return `<section class="bk-sec" aria-labelledby="bk-rch"><h3 class="ofcgrp" id="bk-rch">${tr('Receipts this month')}</h3>${missHtml}
    ${billable ? `<p><button type="button" class="btn" data-bk="bill">${tr('Bill receipts on to a client …')}</button></p>` : ''}
    ${rs.length ? `<ul class="ofclist" role="list">${rs.slice(-30).reverse().map(bkRcRow).join('')}</ul>` : `<p class="muted lempty">${tr('No receipts this month yet.')}</p>`}</section>`;
}

function bkTable(rows, total, count) {
  const th = `<thead><tr><th>${tr('Group')}</th>${count ? `<th class="num">${tr('Receipts')}</th>` : ''}<th class="num">${tr('Net')}</th><th class="num">${tr('VAT')}</th><th class="num">${tr('Gross')}</th></tr></thead>`;
  const td = (r, b) => `<tr${b ? ' class="bk-tot"' : ''}><th scope="row">${esc(r.label)}${r.account ? ` <small class="muted">${esc(r.account)}</small>` : ''}</th>${count ? `<td class="num" data-l="${esc(tr('Receipts'))}">${r.count ?? ''}</td>` : ''}<td class="num" data-l="${esc(tr('Net'))}">${ofcMoney(r.net)}</td><td class="num" data-l="${esc(tr('VAT'))}">${ofcMoney(r.vat)}</td><td class="num" data-l="${esc(tr('Gross'))}">${ofcMoney(r.gross)}</td></tr>`;
  return `<table class="bk-tab">${th}<tbody>${rows.length ? rows.map(r => td(r)).join('') : `<tr><td colspan="${count ? 5 : 4}" class="muted">${tr('None')}</td></tr>`}${td({...total, label: tr('Total')}, true)}</tbody></table>`;
}
function bkEuerHtml() {
  const d = BK.euer;
  return `<section class="bk-sec" aria-labelledby="bk-euh"><div class="ofcbar"><h3 class="ofcgrp" id="bk-euh">${tr('Income/expense statement {0}', d.year)}</h3><span class="spacer"></span>
    <a class="btn sm ghost" href="/api/office/books/euer.csv?year=${d.year}" download>${ic('download', 's')}<span>CSV</span></a><a class="btn sm ghost" href="/api/office/books/euer.pdf?year=${d.year}" download>${ic('download', 's')}<span>PDF</span></a></div>
    <h4 class="bk-h">${tr('Income')}</h4>${bkTable(d.income, d.income_total)}
    <h4 class="bk-h">${tr('Expenses')}</h4>${bkTable(d.expenses, d.expense_total, true)}
    <div class="bk-profit"><span>${tr('Profit')}${d.small_business ? ` <small class="muted">(${tr('small business: gross')})</small>` : ''}</span><b class="${+d.profit < 0 ? 'neg' : ''}">${ofcMoney(d.profit)}</b></div>
    ${d.tax_reserve_pct ? `<div class="bk-profit bk-res"><span>${tr('Tax reserve for the year ({0} % of the profit)', d.tax_reserve_pct)}</span><b>${ofcMoney(d.tax_reserve)}</b></div>` : ''}
    ${d.missing_vat ? `<p class="bk-warn">${esc(trn('{0} receipt without VAT rate counts without input tax.', '{0} receipts without VAT rate count without input tax.', d.missing_vat))}</p>` : ''}
    <p class="muted ofchint">${esc(d.notes[1] || '')}</p>${bkNote()}</section>`;
}

const BK_KZ = [['81', N_('Taxable sales at 19 % (base)')], ['86', N_('Taxable sales at 7 % (base)')], ['35', N_('Sales at other rates (base)')], ['36', N_('Tax on sales at other rates')],
  ['21', N_('Services to businesses in the EU (reverse charge)')], ['45', N_('Other sales not taxable domestically')], ['66', N_('Input tax from receipts')], ['83', N_('Advance payment (negative = refund)')]];
function bkPeriods(mode) {
  if (mode === 'month') return Array.from({length: 12}, (_, i) => ['m' + String(i + 1).padStart(2, '0'), new Date(2000, i, 1).toLocaleDateString(LOCALE(), {month: 'long'})]);
  return [1, 2, 3, 4].map(q => ['q' + q, tr('Quarter {0}', q)]);
}
function bkUstvaHtml() {
  const d = BK.ustva, yNow = new Date().getFullYear(), years = [];
  for (let y = yNow; y >= yNow - 3; y--) years.push([y, String(y)]);
  const bar = `<div class="ofcbar bk-ubar"><div class="seg" role="group" aria-label="${esc(tr('Period'))}">${[['month', tr('Month')], ['quarter', tr('Quarter')], ['year', tr('Whole year')]].map(([k, n]) => `<button type="button" data-bk="mode" data-v="${k}" class="${BK.mode === k ? 'on' : ''}" aria-pressed="${BK.mode === k}">${esc(n)}</button>`).join('')}</div>
    ${BK.mode === 'year' ? '' : ofcSel('bk-period', BK.period, bkPeriods(BK.mode))}${ofcSel('bk-pyear', BK.pyear, years)}</div>`;
  let body;
  if (d.small_business) body = `<p class="bk-warn">${tr('Small business: no VAT return')}</p>`;
  else {
    const shown = BK_KZ.filter(([k]) => ['81', '86', '66', '83'].includes(k) || +d.kz[k]);
    body = `<dl class="bk-kz">${shown.map(([k, n]) => `<div class="${k === '83' ? 'bk-kz83' : ''}"><dt><span class="bk-kzn">${tr('Field {0}', k)}</span> ${esc(tr(n))}</dt><dd>${['81', '86', '35', '21', '45'].includes(k) ? esc(fmtNum(+d.kz[k], 0)) + ' ' + (ofcCur() === 'USD' ? '$' : '€') : ofcMoney(d.kz[k])}</dd></div>`).join('')}</dl>
      <p class="muted ofchint">${esc(tr('VAT 19 %: {0} · VAT 7 %: {1}', ofcMoney(d.tax['19']), ofcMoney(d.tax['7'])))} · ${d.basis === 'soll' ? tr('VAT on invoicing (by invoice date)') : tr('VAT on payment received')}</p>
      ${+d.exempt_other ? `<p class="bk-warn">${esc(tr('Other tax-free sales of {0} have no field here: please check.', ofcMoney(d.exempt_other)))}</p>` : ''}
      ${d.missing_vat ? `<p class="bk-warn">${esc(trn('{0} receipt without VAT rate counts without input tax.', '{0} receipts without VAT rate count without input tax.', d.missing_vat))}</p>` : ''}
      <details class="bk-items"><summary>${esc(trn('Based on {0} entry', 'Based on {0} entries', d.items.length))}</summary><ul class="ofclist" role="list">${d.items.map(bkItemRow).join('')}</ul></details>`;
  }
  return `<section class="bk-sec" id="bk-ustva" aria-labelledby="bk-uh"><h3 class="ofcgrp" id="bk-uh">${tr('VAT return (figures to type in)')}</h3>${bar}${body}${bkNote()}</section>`;
}
function bkItemRow(it) {
  const rc = it.kind === 'receipt';
  const t = rc ? (it.title || tr('Receipt')) : `${it.kind === 'credit' ? tr('Credit note') : tr('Invoice')} ${it.number || ''}`;
  const sub = [fmtDateLoc(it.date), rc ? bkVatLabel(it.vat_pct) : it.source === 'payment' ? tr('Payment') : ''].filter(Boolean).join(' · ');
  return `<li><a class="ofcrow" href="${rc ? `#docs/${it.node_id}` : `#office/offers/${it.doc_id}`}"><span class="ofcn"><b>${esc(t)}</b><small class="muted">${esc(sub)}</small></span><span class="rksum">${ofcMoney(it.gross)}</span>${ic('chev', 's')}</a></li>`;
}
function bkSettingsHtml() {
  const s = OFC.info?.settings || {};
  return `<section class="bk-sec" aria-labelledby="bk-sh"><h3 class="ofcgrp" id="bk-sh">${tr('Settings')}</h3>
    ${ofcRowF('bk-reserve', tr('Tax reserve'), `<input id="bk-reserve" type="number" min="0" max="60" step="1" inputmode="numeric" class="numin bk-pct" value="${+s.tax_reserve_pct || 0}"><span class="muted">%</span>`, tr('Share of the net money received that is put aside in the cash flow (0 = off).'))}
    <div class="row"><label id="bk-basisl">${tr('VAT')}</label><div class="seg" role="group" aria-labelledby="bk-basisl">${[['ist', tr('Cash basis (on payment)')], ['soll', tr('Accrual basis (on invoicing)')]].map(([k, n]) => `<button type="button" data-bk="basis" data-v="${k}" class="${(s.vat_basis || 'ist') === k ? 'on' : ''}" aria-pressed="${(s.vat_basis || 'ist') === k}">${esc(n)}</button>`).join('')}</div></div></section>`;
}

// ---- settings: one undo step each
async function bkSet(key, val) {
  const j = await api('PUT', '/api/office/settings', {[key]: val});
  OFC.info.settings = j.settings; BK.euer = null; BK.ustva = null; ofcDraw();
  return {};
}
async function bkSetUndo(key, val) {
  const from = OFC.info?.settings?.[key];
  if (String(from) === String(val)) return;
  try { await bkSet(key, val); } catch (x) { toast(x.message || tr('unknown')); ofcDraw(); return; }
  const label = tr('Changed setting');
  histToast(label, histAdd({label, undo: () => bkSet(key, from), redo: () => bkSet(key, val)}));
}

// ---- the receipt sheet (after a photo, or a tap on a receipt)
async function bkUpload(file) {
  const fd = new FormData(); fd.append('files', file, file.name || 'receipt.jpg'); fd.append('ws', BK.info.upload_ws);
  let j; try { j = await api('POST', '/api/docs', fd); } catch (x) { toast(x.message || tr('unknown')); return; }
  for (const e of j.errors || []) toast(e);
  const id = j.ids?.[0]; if (!id) return;
  const label = tr('Receipt added');
  histToast(label, histAdd({label, undo: async () => { await api('DELETE', `/api/files/nodes/${id}`); bkReload(); return {}; },
    redo: async () => { await api('POST', `/api/files/nodes/${id}/restore`); bkReload(); return {}; }}));
  bkSheet(id, true);
}
async function bkSheet(id, fresh) {
  let doc, rc;
  try { [doc, rc] = await Promise.all([api('GET', `/api/docs/${id}`), api('GET', `/api/docs/${id}/receipt`)]); } catch (x) { toast(x.message || tr('unknown')); return; }
  const r = rc.receipt || {}, cats = [...new Set([...(BK.info?.categories || []), ...(rc.categories || [])])];
  const wait = doc.state === 'wait' || doc.state === 'run';
  const md = modal(`<h3>${tr('Receipt')}</h3><p class="muted bk-sname">${esc(doc.name)}</p><div class="bk-rx"></div>
    <p class="muted bk-rec" role="status">${wait ? tr('Being recognised…') : ''}</p>
    ${ofcRowF('bk-cat', tr('Category'), ofcIn('bk-cat', r.category, {max: 60, list: 'bk-cats', ph: tr('e.g. Travel, Material, Software')}) + `<datalist id="bk-cats">${cats.map(k => `<option value="${esc(k)}"${bkAcct(k) ? ` label="${esc(bkAcct(k).account)}"` : ''}>`).join('')}</datalist>`)}
    <div class="bk-acct muted" aria-live="polite"></div>
    ${ofcRowF('bk-vat', tr('VAT rate'), ofcSel('bk-vat', r.vat_pct ?? '', BK_VATS, tr('unknown')))}
    ${ofcRowF('bk-amount', tr('Amount (gross)'), ofcIn('bk-amount', doc.amount ? fmtNum(+doc.amount, 2) : '', {num: true}), ofcCur())}
    <div class="row"><label id="bk-datel">${tr('Date')}</label>${dateIn('bk-date', doc.date || '', {label: tr('Date')})}</div>
    <div class="aerr" role="alert"></div>
    ${BK.billed[id] ? `<p class="muted bk-billed">${esc(bkBilledTxt(BK.billed[id]))}</p>` : ''}
    <div class="foot"><a class="btn ghost" href="#docs/${id}">${tr('Open document')}</a>${!BK.billed[id] && r.is_receipt && doc.amount ? `<button class="btn ghost" data-m="bill">${tr('Bill on to a client …')}</button>` : ''}<span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Save')}</button></div>`);
  md.classList.add('ofcdlg', 'bk-sheet');
  md.dataset.rxid = String(id);
  // 2.121.0 A (#2092): the recognised values (supplier, VAT rate, net / gross) with Take over (receipts.js of the documents)
  if (doc.extracted) loadModule('docs').then(() => { const el = $('.bk-rx', md); if (el && typeof rx_html === 'function') el.innerHTML = rx_html(doc); }).catch(() => 0);
  const close = fgModal(md), touched = new Set();
  md.addEventListener('input', e => { if (e.target.id) touched.add(e.target.id); });
  md.addEventListener('change', e => { if (e.target.id) touched.add(e.target.id); });
  if (wait) bkPoll(id, md, touched, 0);
  bkAcctLine(md);
  $('#bk-cat', md)?.addEventListener('input', () => bkAcctLine(md));
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { close(); return; }
    if (b.dataset.m === 'acct') { bkAcctEdit(md); return; }
    if (b.dataset.m === 'acct-save') { bkAcctSave(md); return; }
    if (b.dataset.m === 'bill') { close(); bkBillModal([id]); return; }
    const v = s => $(s, md)?.value ?? '';
    const amt = ofcNum(v('#bk-amount'));
    if (v('#bk-amount').trim() && amt == null) { $('.aerr', md).textContent = tr('Invalid value: {0}', tr('Amount')); return; }
    const before = {doc: {amount: doc.amount || '', date: doc.date || ''}, rc: {project_id: r.project?.id || null, category: r.category || '', vat_pct: r.vat_pct ?? null, keep: !!r.is_receipt}};
    const after = {doc: {amount: amt == null ? '' : amt.toFixed(2), date: v('#bk-date')}, rc: {project_id: r.project?.id || null, category: v('#bk-cat').trim(), vat_pct: v('#bk-vat') || null, keep: true}};
    b.disabled = true;
    try { await bkSave(id, after); } catch (x) { b.disabled = false; $('.aerr', md).textContent = x.message || ''; return; }
    md.remove();
    const label = tr('Changed receipt');
    histToast(label, histAdd({label, undo: () => bkSave(id, before), redo: () => bkSave(id, after)}));
  });
  if (fresh) setTimeout(() => $('#bk-cat', md)?.focus(), 0);
}
// 2.121.0 (#2093): the SKR03 / SKR04 account of a receipt category (the one the DATEV export books on); changed here through
// the office settings (datev_extf.cat_accounts), one undo step. BK.info.accounts is null without the DATEV input side.
const bkAcct = cat => {
  const a = BK.info?.accounts, k = (cat || '').toLowerCase();
  if (!a || !k) return null;
  const n = Object.keys(a.categories).find(x => x.toLowerCase() === k);
  return n ? a.categories[n] : null;
};
function bkAcctLine(md) {
  const el = $('.bk-acct', md), a = BK.info?.accounts, cat = ($('#bk-cat', md)?.value || '').trim();
  if (!el) return;
  if (!a || !cat) { el.innerHTML = ''; return; }
  const x = bkAcct(cat);
  el.innerHTML = x ? `<span>${esc(tr('Account {0} ({1})', x.account, a.chart))}${x.own ? '' : ' · ' + esc(tr('default account'))}</span> <button type="button" class="btn sm ghost" data-m="acct">${tr('Change account')}</button>`
    : `<span>${esc(tr('New category: account after saving'))}</span>`;
}
function bkAcctEdit(md) {
  const el = $('.bk-acct', md), cat = ($('#bk-cat', md)?.value || '').trim(), x = bkAcct(cat);
  if (!el || !x) return;
  el.innerHTML = `${ofcIn('bk-acctin', x.own ? x.account : '', {num: true, max: 9, ph: x.default})}<button type="button" class="btn sm" data-m="acct-save">${tr('Save')}</button>`;
  $('#bk-acctin', md)?.focus();
}
async function bkAcctPut(own) {
  await api('PUT', '/api/office/settings', {datev_extf: {cat_accounts: own}});
  BK.info = null; BK.euer = null;
}
async function bkAcctSave(md) {
  const cat = ($('#bk-cat', md)?.value || '').trim(), val = ($('#bk-acctin', md)?.value || '').replace(/\D/g, '');
  const from = {...(BK.info?.accounts?.own || {})}, to = {...from};
  if (val) to[cat.toLowerCase()] = val; else delete to[cat.toLowerCase()];
  try { await bkAcctPut(to); } catch (x) { $('.aerr', md).textContent = x.message || ''; return; }
  try { BK.info = await api('GET', `/api/office/books?year=${BK.year}`); } catch (x) { /* drawn on the next visit */ }
  bkAcctLine(md);
  const label = tr('Changed account');
  histToast(label, histAdd({label, undo: async () => { await bkAcctPut(from); ofcDraw(); return {}; }, redo: async () => { await bkAcctPut(to); ofcDraw(); return {}; }}));
}
// 2.121.0 C (#2094): bill receipts on to a client (positions "external costs"; one undo step)
async function bkBillModal(pre) {
  const all = [...(BK.info?.receipts || [])].reverse().filter(r => !BK.billed[r.node_id] && r.amount);
  const list = all;
  let docs = [];
  try { docs = (await api('GET', '/api/office/trips/bill-docs')).docs || []; } catch (x) { toast(x.message || ''); return; }
  const kind = d => d.kind === 'invoice' ? tr('Invoice') : tr('Quotation');
  const md = modal(`<h3>${tr('Bill receipts on to a client')}</h3>
    <p class="muted">${tr('Each receipt becomes a position with the amount as purchase price (net where the receipt has a VAT rate).')}</p>
    ${pre ? '' : `<ul class="ofclist bk-pick" role="list">${list.map(r => `<li>${ofcChk('bkb-' + r.node_id, [r.title || tr('Receipt'), fmtDateLoc(r.date), ofcMoney(r.amount)].filter(Boolean).join(' · '), false)}</li>`).join('')}</ul>`}
    ${docs.length ? ofcRowF('bkb-doc', tr('Quotation or invoice (draft)'), ofcSel('bkb-doc', docs[0].id, docs.map(d => [d.id, [kind(d), d.number || tr('Draft'), d.project_title].filter(Boolean).join(' · ')])))
      : `<div class="empty nempty">${tr('There is no quotation or invoice in draft. Create one first.')}</div>`}
    ${ofcRowF('bkb-mk', tr('Markup in %'), ofcIn('bkb-mk', '', {num: true, ph: '0'}))}
    ${pre ? '' : ofcChk('bkb-one', tr('One position for all receipts'), false)}
    <div class="aerr" role="alert"></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button>${docs.length ? `<button class="btn pri" data-m="save">${tr('Bill on')}</button>` : ''}</div>`);
  md.classList.add('ofcdlg');
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    const ids = pre || list.filter(r => $('#bkb-' + r.node_id, md)?.checked).map(r => r.node_id);
    if (!ids.length) { $('.aerr', md).textContent = tr('Tick at least one receipt.'); return; }
    b.disabled = true;
    try {
      const j = await api('POST', '/api/office/receipts/bill', {doc_id: +$('#bkb-doc', md).value, node_ids: ids, markup_pct: ofcNum($('#bkb-mk', md).value), one: $('#bkb-one', md)?.checked ? 1 : 0});
      md.remove(); bkReload();
      toast(tr('Billed on {0}', j.number || tr('Draft')), async () => { await api('POST', '/api/office/receipts/unbill', {node_ids: j.items, positions: j.positions}); bkReload(); });
    } catch (x) { b.disabled = false; const el = $('.aerr', md); if (el) el.textContent = x.message || ''; }
  });
}
function bkRxAfter(id) {  // 2.121.0 A (#2092): taken over / undone -> the sheet shows the new values
  const md = $(`.bk-sheet[data-rxid="${id}"]`);
  if (!md) return;
  md.remove(); bkSheet(id); bkReload();
}
async function bkSave(id, v) {
  await api('PATCH', `/api/docs/${id}`, v.doc);
  await api('PUT', `/api/docs/${id}/receipt`, v.rc);
  bkReload();
  return {};
}
async function bkPoll(id, md, touched, n) {  // the recognition runs in the background: fill what the person has not typed yet
  await new Promise(res => setTimeout(res, n < 5 ? 1500 : 4000));
  if (!md.isConnected || n > 40) return;
  let d; try { d = await api('GET', `/api/docs/${id}`); } catch { return; }
  if (!md.isConnected) return;
  if (d.state === 'wait' || d.state === 'run') { bkPoll(id, md, touched, n + 1); return; }
  const st = $('.bk-rec', md); if (st) st.textContent = d.state === 'done' ? tr('Recognised') : (d.error_text || '');
  if (d.amount && !touched.has('bk-amount') && !$('#bk-amount', md).value) $('#bk-amount', md).value = fmtNum(+d.amount, 2);
  const di = $('#bk-date', md);
  if (d.date && di && !touched.has('bk-date') && !di.value) { di.value = d.date; if (typeof dpSync === 'function') dpSync(di); }
}

// ---- events (delegated)
document.addEventListener('change', e => {
  if (S.route?.mod !== 'office' || ofcTab() !== 'books') return;
  const t = e.target;
  if (t.id === 'bk-file') { const f = t.files?.[0]; t.value = ''; if (f) bkUpload(f); return; }
  if (t.id === 'bk-year') { BK.year = +t.value; BK.info = null; BK.euer = null; ofcDraw(); return; }
  if (t.id === 'bk-period') { BK.period = t.value; bkLoadUstva(); return; }
  if (t.id === 'bk-pyear') { BK.pyear = +t.value; bkLoadUstva(); return; }
  if (t.id === 'bk-reserve') { const n = Math.round(+t.value); if (!Number.isFinite(n) || n < 0 || n > 60) { toast(tr('Invalid value: {0}', tr('Tax reserve'))); t.value = +OFC.info?.settings?.tax_reserve_pct || 0; return; } bkSetUndo('tax_reserve_pct', n); }
});
document.addEventListener('click', e => {
  const b = e.target.closest('[data-bk]'); if (!b || S.route?.mod !== 'office') return;
  const k = b.dataset.bk;
  if (k === 'rc') { bkSheet(+b.dataset.id, false); return; }
  if (k === 'bill') { bkBillModal(null); return; }
  if (k === 'basis') { bkSetUndo('vat_basis', b.dataset.v); return; }
  if (k === 'mode' && BK.mode !== b.dataset.v) {
    BK.mode = b.dataset.v;
    const p = bkDefaultPeriod(BK.mode); BK.period = p.period; BK.pyear = p.year; bkLoadUstva();
  }
});
