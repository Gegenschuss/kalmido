// 2.90.0 A (#1921): bookkeeping light in the office (tab "Bookkeeping"): EUeR, VAT return figures, receipt photo
// Admins of the office area only (a personal office: its owner). On top a big button "Photograph receipt" (camera on the
// phone, the file dialog on a desktop; PDF too) -> a document in the office's documents space and a small sheet (category,
// VAT rate, amount, date; prefilled once the recognition is done); below the receipts of this month, the income/expense
// statement of the year (CSV / PDF), the VAT return figures of a month / quarter (#office/books/ustva jumps there), the
// settings (tax reserve, VAT on payment / on invoicing) and the tax dates of part C (txdSectionHtml). Server:
// kalmido/office/books.py. No tax advice: the page carries the same short note once at its end (2.298.0, R7).
const BK = {oid: null, year: new Date().getFullYear(), info: null, euer: null, ustva: null, mode: null, period: null, err: null, seq: 0, jumped: false, acc: null};
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
  Object.assign(BK, {oid: OFC.info?.org_id, acc: null, info: null, euer: null, ustva: null, err: null, period: p.period, pyear: p.year, jumped: false});
}
async function bkLoad() {
  const seq = ++BK.seq, y = BK.year, q = `year=${BK.pyear}&period=${BK.period}`;
  try {
    const [info, euer, ustva] = await Promise.all([api('GET', `/api/office/books?year=${y}`), api('GET', `/api/office/books/euer?year=${y}`),
      ofcFeat('books.vat_return') ? api('GET', `/api/office/books/ustva?${q}`) : {off: true}]);  // 2.147.0 (#2460): VAT return figures switched off / not in the pack
    if (seq !== BK.seq) return;
    BK.billed = await bkBilledLoad(info);
    if (seq !== BK.seq) return;
    Object.assign(BK, {info, euer, ustva, err: null});
    bkAcctLines();  // 2.144.2 B (#2352)
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
const bkReload = () => { BK.info = null; BK.euer = null; if (typeof RKF === 'object') RKF.data = null; if (typeof rclReload === 'function') rclReload(); ofcDraw(); };  // 2.276.0 A (#3039): + the receipts list  // 2.114.1 B (#2018): receipts count in the cash flow

function bkTabHtml() {
  if (bkSub() === 'procdoc' && typeof pdHtml === 'function') return pdHtml();  // 2.148.0 C (#2472): the procedure documentation
  if (BK.oid !== OFC.info?.org_id || !BK.period) bkReset();  // another office area
  if (!ofcAdmin()) return `<div class="empty">${tr('Only for admins of the office.')}</div>`;
  if (bkSub() === 'receipts' && typeof rclHtml === 'function') return rclHtml();  // 2.110.0 B (#2055): all receipts (office_receipts.js)
  if (BK.err) return `<div class="empty">${esc(BK.err)}</div>`;
  if (!BK.info || !BK.euer || !BK.ustva) { if (!BK.loadingT) BK.loadingT = setTimeout(() => { BK.loadingT = 0; bkLoad(); }, 0); return `<p class="muted lempty">${tr('Loading…')}</p>`; }
  if (bkSub() === 'ustva' && !BK.jumped) { BK.jumped = true; setTimeout(() => $('#bk-ustva')?.scrollIntoView({block: 'start'}), 0); }
  const yNow = new Date().getFullYear(), years = [];
  for (let y = yNow + 1; y >= yNow - 6; y--) years.push([y, String(y)]);
  const head = `<div class="ofcbar bk-bar"><label class="bk-year"><span class="muted">${tr('Year')}</span>${ofcSel('bk-year', BK.year, years)}</label><span class="spacer"></span>
    <a class="btn sm ghost" href="#office/books/procdoc" data-bk-procdoc>${ic('file', 's')}<span>${tr('Procedure documentation')}</span></a></div>
    ${bkPhotoHtml()}`;
  const txd = typeof txdSectionHtml === 'function' && ofcFeat('books.tax_dates') ? txdSectionHtml() : '';  // part C: the tax dates; 2.147.0 (#2460): only while on
  const dob = typeof dimp_obHtml === 'function' && ofcFeat('books.datev') ? dimp_obHtml(BK.year) : '';  // 2.148.0 D (#2458): opening balances of the DATEV import
  const plk = typeof plSectionHtml === 'function' && ofcFeat('books.gobd') ? plSectionHtml() : '';  // 2.148.0 A (#2471): lock periods + auditor export
  // 2.298.0 A2 (#3186): the tax note once at the end of the page, no longer under every part (R7)
  return head + bkReceiptsHtml() + bkEuerHtml() + (BK.ustva?.off ? '' : bkUstvaHtml()) + bkExportHtml() + bkSettingsHtml() + txd + dob + plk + bkNote();
}
// the upload of receipts (camera / files); 2.276.0 A (#3039): also on top of Office > Receipts (office_receipts.js rcp_tabHtml)
const bkPhotoHtml = () => `<div class="bk-photo"><label class="btn pri bk-shot">${ic('camera')}<span>${tr('Photograph receipt')}</span><input type="file" id="bk-file" accept="image/*,application/pdf,.xml,application/xml,text/xml" capture="environment" multiple hidden></label>
    <label class="btn bk-files">${ic('upload')}<span>${tr('Upload files')}</span><input type="file" id="bk-files" accept="${BK_ACCEPT}" multiple hidden></label>
    ${(typeof BK !== 'undefined' && BK.info?.receipts || []).length ? '' : `<span class="muted bk-photohint">${tr('The receipt is saved in the file store (folder “Dokumente”) and listed under Office > Receipts; amount and date are recognised.')}</span>`}</div>`;  // 2.298.0 A2 (#3186): only while empty
// 2.147.0 (#2461): the export for any tax advisor -- the booking list of the year as CSV, or with invoices and receipts as ZIP
function bkExportHtml() {
  if (!ofcFeat('books.export_csv')) return '';
  const y = BK.year, q = `from=${y}-01-01&to=${y}-12-31`;
  return `<section class="bk-sec" aria-labelledby="bk-exh"><div class="ofcbar"><h3 class="ofcgrp" id="bk-exh">${tr('Export for the tax advisor {0}', y)}</h3><div class="shint">${tr('All invoices, credit notes, payments, receipts and travel expenses of the year in one list; the ZIP also holds the invoice PDFs and the receipt files.')}</div><span class="spacer"></span>
    <a class="btn sm ghost" href="/api/office/books/export?${q}" download>${ic('download', 's')}<span>CSV</span></a><a class="btn sm ghost" href="/api/office/books/export?${q}&zip=1" download>${ic('download', 's')}<span>ZIP</span></a></div></section>`;
}

function bkRcRow(r) {
  return `<li><button type="button" class="ofcrow" data-bk="rc" data-id="${r.node_id}"><span class="ofcn"><b>${esc(r.title || tr('Receipt'))}</b>
    <small class="muted">${esc([fmtDateLoc(r.date), r.category, bkVatLabel(r.vat_pct), bkBilledTxt(BK.billed[r.node_id])].filter(Boolean).join(' · '))}</small></span>
    ${r.vat_pct == null && !BK.info.small_business ? `<span class="rotag bk-miss">${tr('without VAT rate')}</span>` : ''}${r.dup ? `<span class="rotag bk-dup">${tr('Possible duplicate')}</span>` : ''}<span class="rksum">${ofcMoney(r.amount)}</span>${ic('chev', 's')}</button></li>`;
}
function bkReceiptsHtml() {
  const d = BK.info, rs = d.receipts || [], miss = d.missing || [];
  const missHtml = miss.length ? `<details class="bk-missing"><summary>${esc(trn('{0} receipt without VAT rate', '{0} receipts without VAT rate', miss.length))} · ${tr('add it')}</summary>
    <ul class="ofclist" role="list">${miss.map(bkRcRow).join('')}</ul></details>` : '';
  const billable = rs.some(r => !BK.billed[r.node_id]);
  return `<section class="bk-sec" aria-labelledby="bk-rch"><h3 class="ofcgrp" id="bk-rch">${tr('Receipts this month')}</h3>${missHtml}
    ${billable ? `<p><button type="button" class="btn" data-bk="bill">${tr('Bill receipts on to a client …')}</button></p>` : ''}
    ${rs.length ? `<ul class="ofclist" role="list">${rs.slice(-30).reverse().map(bkRcRow).join('')}</ul>` : `<p class="muted lempty">${tr('No receipts this month yet.')}</p>`}
    <p class="bk-all"><a class="btn ghost" href="#office/books/receipts">${ic('list', 's')}<span>${tr('All receipts')}</span>${ic('chev', 's')}</a></p></section>`;  // 2.153.0 (#2055)
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
    <p class="muted ofchint">${esc(d.notes[1] || '')}</p></section>`;
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
    ${BK.mode === 'year' ? '' : ofcSel('bk-period', BK.period, bkPeriods(BK.mode), null, tr('Period'))}${ofcSel('bk-pyear', BK.pyear, years, null, tr('Year'))}</div>`;
  let body;
  if (d.small_business) body = `<p class="bk-warn">${tr('Small business: no VAT return')}</p>`;
  else {
    const shown = BK_KZ.filter(([k]) => ['81', '86', '66', '83'].includes(k) || +d.kz[k]);
    body = `<dl class="bk-kz">${shown.map(([k, n]) => `<div class="${k === '83' ? 'bk-kz83' : ''}"><dt><span class="bk-kzn">${tr('Field {0}', k)}</span> ${esc(tr(n))}</dt><dd>${['81', '86', '35', '21', '45'].includes(k) ? esc(fmtNum(+d.kz[k], 0)) + ' ' + ofcSym(ofcHome()) : ofcMoney(d.kz[k])}</dd></div>`).join('')}</dl>
      <p class="muted ofchint">${esc(tr('VAT 19 %: {0} · VAT 7 %: {1}', ofcMoney(d.tax['19']), ofcMoney(d.tax['7'])))} · ${d.basis === 'soll' ? tr('VAT on invoicing (by invoice date)') : tr('VAT on payment received')}</p>
      ${+d.exempt_other ? `<p class="bk-warn">${esc(tr('Other tax-free sales of {0} have no field here: please check.', ofcMoney(d.exempt_other)))}</p>` : ''}
      ${d.missing_vat ? `<p class="bk-warn">${esc(trn('{0} receipt without VAT rate counts without input tax.', '{0} receipts without VAT rate count without input tax.', d.missing_vat))}</p>` : ''}
      <details class="bk-items"><summary>${esc(trn('Based on {0} entry', 'Based on {0} entries', d.items.length))}</summary><ul class="ofclist" role="list">${d.items.map(bkItemRow).join('')}</ul></details>`;
  }
  return `<section class="bk-sec" id="bk-ustva" aria-labelledby="bk-uh"><h3 class="ofcgrp" id="bk-uh">${tr('VAT return (figures to type in)')}</h3>${bar}${body}</section>`;
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
// 2.146.0 B (#2453): several files at once (at most BK_FILES_MAX, as in the file store), a ZIP / winmail.dat is unpacked on
// the server; several photos can become ONE receipt (the phone scan's PDF, abscan.js); a file already there is not stored
// again (#2452: the answer's dups, "Open" shows it)
const BK_FILES_MAX = 50, BK_MERGE_MAX = 30;
const BK_ACCEPT = 'image/*,application/pdf,.pdf,.heic,.heif,.zip,application/zip,.dat,application/ms-tnef,.xml,application/xml,text/xml';  // 2.146.0 A (#2451): e-invoice XML
const bkIsImg = f => /^image\//.test(f.type || '') || /\.(jpe?g|png|webp|heic|heif)$/i.test(f.name || '');
async function bkFiles(files) {
  files = files.filter(f => f && f.size);
  if (!files.length) return;
  if (files.length > BK_FILES_MAX) { toast(tr('At most {0} files at once', BK_FILES_MAX)); files = files.slice(0, BK_FILES_MAX); }
  if (files.length >= 2 && files.length <= BK_MERGE_MAX && files.every(bkIsImg)) {
    let how = 'each';
    const ok = await askDialog({title: tr('{0} photos', files.length), ok: tr('Upload'),
      html: `<fieldset class="bk-merge"><legend>${esc(tr('How should the photos be filed?'))}</legend>
        <label class="chkl"><input type="radio" name="bk-merge" value="each" checked> ${esc(tr('One receipt per photo'))}</label>
        <label class="chkl"><input type="radio" name="bk-merge" value="one"> ${esc(tr('Merge into one receipt (pages of a long receipt)'))}</label></fieldset>`,
      after: md => md.addEventListener('change', e => { if (e.target.name === 'bk-merge') how = e.target.value; })});
    if (!ok) return;
    if (how === 'one') { const pdf = await bkMerge(files); if (pdf) bkUpload([pdf]); return; }
  }
  bkUpload(files);
}
async function bkMerge(files) {  // the photos -> one PDF (abscan.js: smaller on the phone, the server builds the PDF)
  try {
    await loadModule('abscan');
    const fd = new FormData(), name = abm_scanName();
    for (const [i, f] of files.entries()) { fd.append('page', await abm_shrink(f), `page-${i + 1}.jpg`); fd.append('rot', '0'); }
    fd.append('name', name); fd.append('bw', '0'); fd.append('out', 'pdf');
    const r = await fetch('/api/files/scan', {method: 'POST', body: fd, headers: {'X-Requested-With': 'kalmido'}});
    if (!r.ok) { const j = await r.json().catch(() => ({})); throw new Error(j.error || httpErrText(r.status)); }
    return new File([await r.blob()], name + '.pdf', {type: 'application/pdf'});
  } catch (x) { toast(x?.message || tr('unknown')); return null; }
}
function bkDups(dups) {
  if (!dups.length) return;
  if (dups.length === 1) { toast(tr('This file already exists: {0}', dups[0].name), () => bkSheet(dups[0].id, false), 8000, tr('Open')); return; }
  toast(tr('{0} files already exist', dups.length), () => {
    const md = modal(`<h3>${tr('Already there')}</h3><ul class="ofclist" role="list">${dups.map(d => `<li><button type="button" class="ofcrow" data-bk="rc" data-id="${+d.id}"><span class="ofcn"><b>${esc(d.name)}</b></span>${ic('chev', 's')}</button></li>`).join('')}</ul>
      <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Close')}</button></div>`);
    md.classList.add('ofcdlg'); fgModal(md);
    md.addEventListener('click', e => { if (e.target.closest('[data-bk="rc"]')) md.remove(); });
  }, 8000, tr('Show'));
}
async function bkUpload(files) {
  const fd = new FormData();
  for (const f of files) fd.append('files', f, f.name || 'receipt.jpg');
  fd.append('ws', BK.info?.upload_ws || (OFC.info?.personal ? 'private' : `org:${OFC.info?.org_id}`)); fd.append('unzip', '1');  // 2.276.0 A (#3039): Receipts loads no BK.info
  let j; try { j = await api('POST', '/api/docs', fd); } catch (x) { toast(x.message || tr('unknown')); return; }
  for (const e of j.errors || []) toast(e);
  const ids = j.ids || [], dups = j.dups || [];
  if (ids.length) {
    if (OFC.info?.used) OFC.info.used.receipt = true;  // 2.276.0 A (#3039): the group Money opens without a new load
    const label = ids.length === 1 ? tr('Receipt added') : tr('{0} receipts added', ids.length);
    histToast(label, histAdd({label, undo: async () => { for (const id of ids) await api('DELETE', `/api/files/nodes/${id}`); bkReload(); return {}; },
      redo: async () => { for (const id of ids) await api('POST', `/api/files/nodes/${id}/restore`); bkReload(); return {}; }}));
  }
  bkDups(dups);  // after the undo toast: the hint with its Open button is the last word
  if (ids.length === 1 && !dups.length) bkSheet(ids[0], true);
  else if (ids.length) bkReload();
}
async function bkSheet(id, fresh) {
  let doc, rc;
  try { [doc, rc] = await Promise.all([api('GET', `/api/docs/${id}`), api('GET', `/api/docs/${id}/receipt`)]); } catch (x) { toast(x.message || tr('unknown')); return; }
  const r = rc.receipt || {}, cats = [...new Set([...(BK.info?.categories || []), ...(rc.categories || [])])];
  const wait = doc.state === 'wait' || doc.state === 'run';
  const md = modal(`<h3>${tr('Receipt')}</h3><p class="muted bk-sname">${esc(doc.name)}${doc.einvoice ? ` · <a class="bk-einv" href="/api/docs/${id}/einvoice" target="_blank" rel="noopener">${tr('Readable view')}</a>` : ''}</p><div class="bk-rx"></div><div class="bk-rcs"></div>
    <p class="muted bk-rec" role="status">${wait ? tr('Being recognised…') : ''}</p>
    ${ofcRowF('bk-cat', tr('Category'), ofcIn('bk-cat', r.category, {max: 60, list: 'bk-cats', ph: tr('e.g. Travel, Material, Software')}) + `<datalist id="bk-cats">${cats.map(k => `<option value="${esc(k)}"${bkAcct(k) ? ` label="${esc(bkAcct(k).account)}"` : ''}>`).join('')}</datalist>`)}
    <div class="bk-acct muted" aria-live="polite"></div>
    ${ofcRowF('bk-vat', tr('VAT rate'), ofcSel('bk-vat', r.vat_pct ?? '', BK_VATS, tr('unknown')))}
    ${ofcRowF('bk-amount', tr('Amount (gross)'), ofcIn('bk-amount', doc.amount ? fmtNum(+doc.amount, 2) : '', {num: true}), ofcCur(), {keep: 1})}
    <div class="row"><label id="bk-datel">${tr('Date')}</label>${dateIn('bk-date', doc.date || '', {label: tr('Date')})}</div>
    <div class="aerr" role="alert"></div>
    ${BK.billed[id] ? `<p class="muted bk-billed">${esc(bkBilledTxt(BK.billed[id]))}</p>` : ''}
    <div class="foot"><a class="btn ghost" href="#docs/${id}">${tr('Open document')}</a>${!BK.billed[id] && r.is_receipt && doc.amount ? `<button class="btn ghost" data-m="bill">${tr('Bill on to a client …')}</button>` : ''}<span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Save')}</button></div>`);
  md.classList.add('ofcdlg', 'bk-sheet');
  md.dataset.rxid = String(id);
  // 2.121.0 A (#2092): the recognised values (supplier, VAT rate, net / gross) with Take over (receipts.js of the documents)
  // 2.154.0 A (#1356): the agents' open suggestions of the receipt (Accept / Reject) and who confirmed one (receipts.js)
  if (rc.suggestions?.length || rc.confirmed) loadModule('docs').then(() => { if (typeof rc_bkSlot === 'function') rc_bkSlot(md, id, rc); }).catch(() => 0);
  if (doc.extracted || doc.duplicate_of) loadModule('docs').then(() => { const el = $('.bk-rx', md); if (el && typeof rx_html === 'function') el.innerHTML = rx_html(doc); }).catch(() => 0);
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
// 2.144.2 B (#2352): while BK.info is reloading (after Take over / undo) the last known accounts keep the line (BK.acc);
// an open receipt sheet draws its account line again once fresh data is there
const bkAccs = () => { if (BK.info) BK.acc = BK.info.accounts; return BK.acc; };
const bkAcctLines = () => document.querySelectorAll('.bk-sheet').forEach(md => { if (!$('#bk-acctin', md)) bkAcctLine(md); });
async function bkAcctFresh() { try { BK.info = await api('GET', `/api/office/books?year=${BK.year}`); } catch { /* drawn on the next visit */ } bkAcctLines(); }
const bkAcct = cat => {
  const a = bkAccs(), k = (cat || '').toLowerCase();
  if (!a || !k) return null;
  const n = Object.keys(a.categories).find(x => x.toLowerCase() === k);
  return n ? a.categories[n] : null;
};
function bkAcctLine(md) {
  const el = $('.bk-acct', md), a = bkAccs(), cat = ($('#bk-cat', md)?.value || '').trim();
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
  await bkAcctFresh(); bkAcctLine(md);
  const label = tr('Changed account');
  // 2.144.2 B (#2352): undo / redo draw the line of an open sheet from the data put back
  histToast(label, histAdd({label, undo: async () => { await bkAcctPut(from); await bkAcctFresh(); ofcDraw(); return {}; }, redo: async () => { await bkAcctPut(to); await bkAcctFresh(); ofcDraw(); return {}; }}));
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
  bkReload();  // 2.110.0 B (#2055): the receipts list too (rclReload)
  return {};
}
async function bkPoll(id, md, touched, n) {  // the recognition runs in the background: fill what the person has not typed yet
  await new Promise(res => setTimeout(res, n < 5 ? 1500 : 4000));
  if (!md.isConnected || n > 40) return;
  let d; try { d = await api('GET', `/api/docs/${id}`); } catch { return; }
  if (!md.isConnected) return;
  if (d.state === 'wait' || d.state === 'run') { bkPoll(id, md, touched, n + 1); return; }
  const st = $('.bk-rec', md); if (st) st.textContent = d.state === 'done' ? tr('Recognised') : (d.error_text || '');
  if (d.einvoice && !$('.bk-einv', md)) $('.bk-sname', md)?.insertAdjacentHTML('beforeend', ` · <a class="bk-einv" href="/api/docs/${id}/einvoice" target="_blank" rel="noopener">${tr('Readable view')}</a>`);  // 2.146.0 A (#2451)
  if (d.amount && !touched.has('bk-amount') && !$('#bk-amount', md).value) $('#bk-amount', md).value = fmtNum(+d.amount, 2);
  const di = $('#bk-date', md);
  if (d.date && di && !touched.has('bk-date') && !di.value) { di.value = d.date; if (typeof dpSync === 'function') dpSync(di); }
}

// ---- events (delegated)
document.addEventListener('change', e => {
  if (S.route?.mod !== 'office' || !['books', 'receipts'].includes(ofcTab())) return;  // 2.276.0 A (#3039): the upload sits on Receipts too
  const t = e.target;
  if (t.id === 'bk-file' || t.id === 'bk-files') { const fs = [...(t.files || [])]; t.value = ''; if (fs.length) bkFiles(fs); return; }  // 2.146.0 B (#2453)
  if (ofcTab() !== 'books') return;
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
