// @ts-check
// 2.153.0 (#2055): the receipts list of the bookkeeping over all months (#office/books/receipts, "All receipts" below
// "Receipts this month"): a filter bar (period with quick choices, status, category, supplier, project, only without VAT
// rate, search; on the phone folded away), the rows as in the month list, the sums below, "Load more" from 200 rows on,
// and the export for the tax adviser (CSV, ZIP with the original files) of exactly the filtered list (only while the country
// pack has the export on, books.export_csv; the whole booking list of the year stays in the bookkeeping, #2461). A tap on a row opens
// the receipt sheet of office_books.js (bkSheet); after saving the list reloads (rclReload). The filters stay for the
// session (sessionStorage). Server: kalmido/office/receiptlist.py.
const RCL = {oid: null, f: null, data: null, rows: [], err: null, seq: 0, key: '', loading: false, open: null};
const RCL_PERIODS = [['year', N_('This year')], ['lastyear', N_('Last year')], ['quarter', N_('This quarter')], ['lastquarter', N_('Last quarter')],
  ['month', N_('This month')], ['lastmonth', N_('Last month')], ['custom', N_('Custom period')]];
const rclIso = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
function rclPeriod(k) {  // a quick choice -> [from, to] (ISO days, local time)
  const n = new Date(), y = n.getFullYear(), m = n.getMonth(), q = Math.floor(m / 3);
  const span = (a, b) => [rclIso(a), rclIso(b)];
  if (k === 'lastyear') return span(new Date(y - 1, 0, 1), new Date(y - 1, 11, 31));
  if (k === 'quarter') return span(new Date(y, q * 3, 1), new Date(y, q * 3 + 3, 0));
  if (k === 'lastquarter') return span(new Date(y, q * 3 - 3, 1), new Date(y, q * 3, 0));
  if (k === 'month') return span(new Date(y, m, 1), new Date(y, m + 1, 0));
  if (k === 'lastmonth') return span(new Date(y, m - 1, 1), new Date(y, m, 0));
  return span(new Date(y, 0, 1), new Date(y, 11, 31));
}
const rclDefault = () => { const [from, to] = rclPeriod('year'); return {per: 'year', from, to, by: 'doc', status: 'all', category: '', supplier: '', project: '', novat: false, hints: false, q: ''}; };
const rclStoreKey = () => `kalmido.rcl.${OFC.info?.org_id || 0}`;
function rclRestore() {
  let f = null;
  try { f = JSON.parse(sessionStorage.getItem(rclStoreKey()) || 'null'); } catch { f = null; }
  f = {...rclDefault(), ...(f && typeof f === 'object' ? f : {})};
  if (f.per !== 'custom') [f.from, f.to] = rclPeriod(f.per);  // "this month" stays this month
  return f;
}
function rclSave() { try { sessionStorage.setItem(rclStoreKey(), JSON.stringify(RCL.f)); } catch { /* private mode */ } }
function rclQuery() {
  const f = RCL.f, p = new URLSearchParams({from: f.from, to: f.to, by: f.by, status: f.status});
  for (const k of ['category', 'supplier', 'project', 'q']) if (f[k]) p.set(k, f[k]);
  if (f.novat) p.set('novat', '1');
  if (f.hints) p.set('hints', '1');  // 2.299.0 D (#3193)
  return p.toString();
}
let rclPend = Infinity;  // 2.299.0 D (#3193): receipts the last request left unchecked
async function rclLoad(more) {
  const seq = ++RCL.seq, q = rclQuery();
  RCL.loading = true;
  try {
    const j = await api('GET', `/api/office/books/receipts?${q}&limit=200&offset=${more ? RCL.rows.length : 0}`);
    if (seq !== RCL.seq) return;
    RCL.rows = more ? RCL.rows.concat(j.rows) : j.rows;
    Object.assign(RCL, {data: j, err: null, key: q});
    // 2.299.0 D (#3193): receipts not checked yet -> the next request checks the next ones (only while the number goes down)
    if (!more && j.hints_pending && j.hints_pending < rclPend) { rclPend = j.hints_pending; RCL.key = ''; } else rclPend = Infinity;
  } catch (x) { if (seq === RCL.seq) { RCL.err = x.message || tr('unknown'); RCL.key = q; } }
  if (seq === RCL.seq) RCL.loading = false;
  ofcDraw();
}
function rclReload() { if (RCL.data) { RCL.key = ''; if (rclHere()) rclLoad(false); } }  // 2.276.0 A (#3039): rclHere (Office > Receipts too)
function rclSet(patch) { Object.assign(RCL.f, patch); rclSave(); rclLoad(false); }

function rclHtml(own) {  // 2.276.0 A (#3039): own = the page Office > Receipts (no way back to the bookkeeping)
  if (RCL.oid !== OFC.info?.org_id || !RCL.f) Object.assign(RCL, {oid: OFC.info?.org_id, f: rclRestore(), data: null, rows: [], key: '', err: null});
  if (RCL.open == null) RCL.open = !window.matchMedia?.('(max-width: 600px)').matches;
  const back = (own ? '' : `<div class="ofcbar rcl-top"><a class="btn sm ghost" href="#office/books">${ic('back', 's')}<span>${tr('Bookkeeping')}</span></a><span class="spacer"></span></div>`) + `
    <h3 class="ofcgrp" id="rcl-h">${tr('All receipts')}</h3>`;
  if (RCL.key !== rclQuery() && !RCL.loading) setTimeout(() => rclLoad(false), 0);
  if (RCL.err) return back + rclFiltersHtml() + `<div class="empty">${esc(RCL.err)}</div>`;
  if (!RCL.data) return back + rclFiltersHtml() + `<p class="muted lempty">${tr('Loading…')}</p>`;
  return back + rclFiltersHtml() + rclListHtml();
}

function rclFiltersHtml() {
  const f = RCL.f, d = RCL.data || {}, all = tr('All');
  const opt = (list, cur, name) => { const o = list.map(x => [String(x.id ?? x), x.name ?? x]); if (cur && !o.some(([v]) => v === String(cur))) o.push([String(cur), name ?? String(cur)]); return o; };
  const n = ['category', 'supplier', 'project', 'q'].filter(k => f[k]).length + (f.novat ? 1 : 0) + (f.hints ? 1 : 0) + (f.status !== 'all' ? 1 : 0);
  const seg = (k, opts) => `<div class="seg" role="group" aria-label="${esc(tr(k === 'status' ? 'Status' : 'Day'))}">${opts.map(([v, t]) => `<button type="button" data-rcl="${k}" data-v="${v}" class="${f[k] === v ? 'on' : ''}" aria-pressed="${f[k] === v}">${esc(t)}</button>`).join('')}</div>`;
  return `<details class="rcl-filters" ${RCL.open ? 'open' : ''}><summary>${ic('filter', 's')}<span>${tr('Filters')}</span>${n ? `<span class="rotag">${n}</span>` : ''}</summary>
    <div class="rcl-grid">
      <label class="rcl-f"><span class="muted">${tr('Period')}</span>${ofcSel('rcl-per', f.per, RCL_PERIODS.map(([k, t]) => [k, tr(t)]))}</label>
      ${f.per === 'custom' ? `<span class="rcl-f rcl-days"><span class="muted">${tr('From')}</span>${dateIn('rcl-from', f.from, {label: tr('From'), clear: false})}<span class="muted">${tr('To')}</span>${dateIn('rcl-to', f.to, {label: tr('To'), clear: false})}</span>` : ''}
      <span class="rcl-f"><span class="muted">${tr('Status')}</span>${seg('status', [['all', all], ['paid', tr('Paid')], ['open', tr('Not paid')]])}</span>
      <span class="rcl-f"><span class="muted">${tr('Day')}</span>${seg('by', [['doc', tr('Receipt date')], ['paid', tr('Payment date')]])}</span>
      <label class="rcl-f"><span class="muted">${tr('Category')}</span>${ofcSel('rcl-cat', f.category, opt(d.categories || [], f.category), all)}</label>
      <label class="rcl-f"><span class="muted">${tr('Supplier')}</span>${ofcSel('rcl-sup', f.supplier, opt(d.suppliers || [], f.supplier, tr('(none in this period)')), all)}</label>
      <label class="rcl-f"><span class="muted">${tr('Project')}</span>${ofcSel('rcl-pro', f.project, opt(d.projects || [], f.project, tr('(none in this period)')), all)}</label>
      <label class="rcl-f rcl-q"><span class="muted">${tr('Search')}</span><input id="rcl-q" type="search" value="${esc(f.q)}" maxlength="200" placeholder="${esc(tr('Title, supplier, invoice number'))}"></label>
      <label class="chkl rcl-novat"><input type="checkbox" id="rcl-novat" ${f.novat ? 'checked' : ''}><span>${tr('Only without VAT rate')}</span></label>
      <label class="chkl rcl-hints"><input type="checkbox" id="rcl-hints" ${f.hints ? 'checked' : ''}><span>${tr('Only with hints')}${d.hints ? ` <span class="rotag">${d.hints}</span>` : ''}</span></label>
      ${n ? `<button type="button" class="btn sm ghost rcl-reset" data-rcl="reset">${tr('Reset filters')}</button>` : ''}
    </div></details>`;
}

function rclRow(r) {
  const sub = [fmtDateLoc(r.date), r.supplier, r.number, r.category, r.project?.name, bkVatLabel(r.vat_pct)].filter(Boolean).join(' · ');
  const orig = r.orig_currency ? ` <small class="muted">(${esc(fmtNum(+r.orig_amount, 2))} ${esc(r.orig_currency)})</small>` : '';
  return `<li><button type="button" class="ofcrow" data-rcl="rc" data-id="${r.node_id}"><span class="ofcn"><b>${esc(r.title || tr('Receipt'))}</b>
    <small class="muted">${esc(sub)}</small></span>${r.einvoice ? `<span class="rotag">${tr('E-invoice')}</span>` : ''}${r.dup ? `<span class="rotag bk-dup">${tr('Possible duplicate')}</span>` : ''}${r.hints > (r.dup ? 1 : 0) ? `<span class="rotag rcl-hint">${tr('With hints')}</span>` : ''}${r.paid_at || !RCL.paidMark ? '' : `<span class="rotag rcl-open">${tr('Not paid')}</span>`}${r.submitted_by ? `<span class="rotag rcl-sub">${esc(tr('Handed in by {0}', r.submitted_by))}</span>` : ''}
    <span class="rksum">${ofcMoney(r.amount)}${orig}</span>${ic('chev', 's')}</button></li>`;
}
function rclListHtml() {
  const d = RCL.data, t = d.total, q = rclQuery();
  const exp = !ofcFeat('books.export_csv') ? '' : `<div class="ofcbar rcl-exp"><span class="spacer"></span>
    <a class="btn sm ghost" id="rcl-csv" href="/api/office/books/receipts.csv?${esc(q)}" download>${ic('download', 's')}<span>CSV</span></a>
    <a class="btn sm" id="rcl-zip" href="/api/office/books/receipts.zip?${esc(q)}" download>${ic('download', 's')}<span>${tr('ZIP for the tax adviser')}</span></a></div>`;
  if (!t.count) return `${exp}<p class="muted lempty rcl-empty">${tr('No receipts match these filters.')}</p>${bkNote()}`;
  // the mark "Not paid" only where payments are recorded at all (bank reconciliation) and the list mixes both
  RCL.paidMark = RCL.f.status === 'all' && RCL.rows.some(r => r.paid_at);
  return `${exp}<ul class="ofclist rcl-list" role="list" aria-labelledby="rcl-h">${RCL.rows.map(rclRow).join('')}</ul>
    ${d.more ? `<p class="rcl-more"><button type="button" class="btn ghost" data-rcl="more" ${RCL.loading ? 'disabled' : ''}>${tr('Load more')}</button></p>` : ''}
    <div class="bk-profit rcl-sum"><span>${esc(trn('{0} receipt', '{0} receipts', t.count))} <small class="muted">· ${tr('Net')} ${ofcMoney(t.net)} · ${tr('VAT')} ${ofcMoney(t.vat)}</small></span><b>${ofcMoney(t.gross)}</b></div>
    ${bkNote()}`;
}

// ---- events (delegated)
const rclHere = () => S.route?.mod === 'office' && (ofcTab() === 'books' && bkSub() === 'receipts' || ofcTab() === 'receipts');  // 2.276.0 A (#3039): + Office > Receipts
let rclQT = 0;
document.addEventListener('input', e => {
  const t = /** @type {any} */ (e.target);
  if (t.id !== 'rcl-q' || !rclHere()) return;
  clearTimeout(rclQT);
  const v = t.value.trim();
  rclQT = setTimeout(() => { if (v !== RCL.f.q) rclSet({q: v}); }, 300);
});
document.addEventListener('change', e => {
  if (!rclHere()) return;
  const t = /** @type {any} */ (e.target);
  if (t.id === 'rcl-per') { const per = t.value; if (per === 'custom') { RCL.f.per = per; rclSave(); ofcDraw(); return; } const [from, to] = rclPeriod(per); rclSet({per, from, to}); return; }
  if (t.id === 'rcl-from' || t.id === 'rcl-to') {
    const k = t.id === 'rcl-from' ? 'from' : 'to', v = t.value;
    if (!v) return;
    const o = {...RCL.f, [k]: v};
    if (o.from > o.to) { if (k === 'from') o.to = v; else o.from = v; }
    rclSet({from: o.from, to: o.to}); return;
  }
  if (t.id === 'rcl-cat') { rclSet({category: t.value}); return; }
  if (t.id === 'rcl-sup') { rclSet({supplier: t.value}); return; }
  if (t.id === 'rcl-pro') { rclSet({project: t.value}); return; }
  if (t.id === 'rcl-novat') { rclSet({novat: t.checked}); return; }
  if (t.id === 'rcl-hints') { rclSet({hints: t.checked}); }  // 2.299.0 D (#3193)
});
document.addEventListener('toggle', e => { const t = /** @type {any} */ (e.target); if (t.classList?.contains('rcl-filters')) RCL.open = t.open; }, true);
document.addEventListener('click', e => {
  const b = /** @type {any} */ (e.target).closest?.('[data-rcl]'); if (!b || !rclHere()) return;
  const k = b.dataset.rcl;
  if (k === 'rc') { bkSheet(+b.dataset.id, false); return; }
  if (k === 'more') { b.disabled = true; rclLoad(true); return; }
  if (k === 'reset') { const d = rclDefault(); rclSet({category: '', supplier: '', project: '', novat: false, hints: false, q: '', status: d.status}); return; }
  if ((k === 'status' || k === 'by') && RCL.f[k] !== b.dataset.v) rclSet({[k]: b.dataset.v});
});

// ---- 2.276.0 A (#3039): the menu point Office > Receipts (#office/receipts, group Money, everybody with the bookkeeping):
// the upload of the bookkeeping (office_books.js bkPhotoHtml / bkFiles / bkUpload), the kinds of receipts with pages of their
// own (entertainment receipts, travel expenses: links, also while their menu points wait behind "More") and the list of all
// receipts above. The bookkeeping keeps its upload.
OFC_TABS.splice(OFC_TABS.findIndex(t => t[0] === 'settings'), 0, /** @type {any} */ (['receipts', 'ticket', N_('Receipts'), 1, () => rcp_tabHtml(), 'money']));
function rcp_tabHtml() {
  if (!ofcAdmin()) return OFC.info?.submit ? rsb_tabHtml() : ofcLockedHtml();  // 2.356.0 D (#3129, #3006): members hand in receipts
  const ks = typeof ofm_all === 'function' ? ofm_all().filter(i => ['meals', 'travel'].includes(i.key) && i.on() && ofm_need(i) && ofm_ok(i)) : [];
  const kinds = ks.length ? `<nav class="rcp-kinds" aria-label="${esc(tr('Other receipts'))}">${ks.map(i => `<a class="btn sm ghost" href="#${i.go}" data-rcp="${i.key}">${ic(i.icon, 's')}<span>${esc(tr(i.name))}</span></a>`).join('')}</nav>` : '';
  return `<div class="rcp">${typeof bkPhotoHtml === 'function' ? bkPhotoHtml() : ''}${kinds}${rsb_inHtml()}${rclHtml(true)}</div>`;  // 2.356.0 D (#3129): + handed in
}

// ---- 2.356.0 D (#3129): "Submit receipt" (#office/receipts, rcp_tabHtml) for the people who may hand in a receipt but do not see the
// bookkeeping (GET /api/office/settings submit): a photo or a file to the bookkeeping, below only the person's own receipts
// handed in with their status. The people with the bookkeeping see what waits on top of Office > Receipts (rsb_inHtml) and
// work on it in the receipt sheet like on every receipt. Server: kalmido/office/rcsubmit.py.
const RSB = {oid: null, rows: null, err: null, loading: false, busy: false, inOid: null, inRows: null, inLoading: false};
const RSB_STATE = {submitted: N_('Handed in'), processed: N_('In progress|receipt'), paid: N_('Paid'), removed: N_('Removed')};  // 2.356.0 (#3129): also when the person took it back
async function rsb_load() {
  const oid = OFC.info?.org_id;
  RSB.loading = true;
  try { const j = await api('GET', '/api/office/receipts/mine'); if (oid === OFC.info?.org_id) Object.assign(RSB, {rows: j.rows || [], err: null}); }
  catch (x) { if (oid === OFC.info?.org_id) Object.assign(RSB, {rows: [], err: x.message || tr('unknown')}); }
  RSB.loading = false; ofcDraw();
}
function rsb_tabHtml() {
  if (!OFC.info?.submit && !ofcAdmin('receipts')) return ofcLockedHtml();
  if (RSB.oid !== OFC.info?.org_id) Object.assign(RSB, {oid: OFC.info?.org_id, rows: null, err: null});
  if (RSB.rows === null && !RSB.loading) setTimeout(rsb_load, 0);
  const st = r => `<span class="rotag rsb-st rsb-${esc(r.status)}">${esc(tr(RSB_STATE[r.status] || r.status))}</span>`;
  const list = RSB.err ? `<div class="empty">${esc(RSB.err)}</div>` : RSB.rows === null ? `<p class="muted lempty">${tr('Loading…')}</p>`
    : !RSB.rows.length ? `<p class="muted lempty rsb-empty">${tr('You have not handed in a receipt yet.')}</p>`
    : `<ul class="ofclist rsb-list" role="list" aria-labelledby="rsb-mine">${RSB.rows.map(r => `<li class="ofcrow rsb-row"><span class="ofcn"><b>${esc(r.name || tr('Receipt'))}</b><small class="muted">${esc(fmtDateLoc(String(r.submitted_at || '').slice(0, 10)))}</small></span>${st(r)}</li>`).join('')}</ul>`;
  return `<div class="rsb"><h3 class="ofcgrp">${tr('Submit receipt')}</h3>
    <p class="muted rsb-hint">${tr('Photograph a receipt or upload the file: it goes to the bookkeeping. You only see your own receipts here.')}</p>
    <div class="bk-photo rsb-up"><label class="btn pri">${ic('camera')}<span>${tr('Photograph receipt')}</span><input type="file" id="rsb-shot" accept="image/*,application/pdf" capture="environment" multiple hidden></label>
    <label class="btn">${ic('upload')}<span>${tr('Upload files')}</span><input type="file" id="rsb-files" accept="${typeof BK_ACCEPT === 'string' ? BK_ACCEPT : 'image/*,application/pdf'}" multiple hidden></label></div>
    <h3 class="ofcgrp" id="rsb-mine">${tr('My receipts handed in')}</h3>${list}</div>`;
}
async function rsb_upload(files) {
  files = files.filter(f => f && f.size);
  if (!files.length || RSB.busy) return;
  const fd = new FormData();
  for (const f of files) fd.append('files', f, f.name || 'receipt.jpg');
  RSB.busy = true;
  let j; try { j = await api('POST', '/api/office/receipts/submit', fd); } catch (x) { RSB.busy = false; toast(x.message || tr('unknown')); return; }
  RSB.busy = false;
  for (const e of j.errors || []) toast(e);
  if ((j.dups || []).length && !(j.ids || []).length) toast(tr('This file already exists: {0}', j.dups[0].name));
  if ((j.ids || []).length) toast(j.ids.length === 1 ? tr('Receipt handed in') : tr('{0} receipts handed in', j.ids.length));
  RSB.rows = null; ofcDraw();
}
// the receipts handed in that wait for the bookkeeping (on top of Office > Receipts; a 403 = nothing shown)
async function rsb_inLoad() {
  const oid = OFC.info?.org_id;
  RSB.inLoading = true;
  try { const j = await api('GET', '/api/office/receipts/submitted'); if (oid === OFC.info?.org_id) RSB.inRows = j.rows || []; } catch { if (oid === OFC.info?.org_id) RSB.inRows = []; }
  RSB.inLoading = false; ofcDraw();
}
function rsb_inHtml() {
  if (OFC.info?.personal) return '';
  if (RSB.inOid !== OFC.info?.org_id) Object.assign(RSB, {inOid: OFC.info?.org_id, inRows: null});
  if (RSB.inRows === null) { if (!RSB.inLoading) setTimeout(rsb_inLoad, 0); return ''; }
  if (!RSB.inRows.length) return '';
  return `<section class="rsb-in"><h3 class="ofcgrp" id="rsb-in-h">${tr('Handed in by members')} <span class="rotag">${RSB.inRows.length}</span></h3>
    <ul class="ofclist" role="list" aria-labelledby="rsb-in-h">${RSB.inRows.map(r => `<li><button type="button" class="ofcrow" data-rsb="open" data-id="${+r.node_id}"><span class="ofcn"><b>${esc(r.name || tr('Receipt'))}</b>
    <small class="muted">${esc([tr('Handed in by {0}', r.by?.name || '?'), fmtDateLoc(String(r.submitted_at || '').slice(0, 10))].join(' · '))}</small></span>${ic('chev', 's')}</button></li>`).join('')}</ul></section>`;
}
document.addEventListener('change', e => {
  const t = /** @type {any} */ (e.target);
  if (t.id !== 'rsb-shot' && t.id !== 'rsb-files') return;
  const fs = [...(t.files || [])]; t.value = '';
  if (fs.length) rsb_upload(fs);
});
document.addEventListener('click', e => {
  const b = /** @type {any} */ (e.target).closest?.('[data-rsb="open"]'); if (!b) return;
  bkSheet(+b.dataset.id, false);  // (bkReload after saving reads the list again)
});
