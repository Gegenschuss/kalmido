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
const rclDefault = () => { const [from, to] = rclPeriod('year'); return {per: 'year', from, to, by: 'doc', status: 'all', category: '', supplier: '', project: '', novat: false, q: ''}; };
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
  return p.toString();
}
async function rclLoad(more) {
  const seq = ++RCL.seq, q = rclQuery();
  RCL.loading = true;
  try {
    const j = await api('GET', `/api/office/books/receipts?${q}&limit=200&offset=${more ? RCL.rows.length : 0}`);
    if (seq !== RCL.seq) return;
    RCL.rows = more ? RCL.rows.concat(j.rows) : j.rows;
    Object.assign(RCL, {data: j, err: null, key: q});
  } catch (x) { if (seq === RCL.seq) { RCL.err = x.message || tr('unknown'); RCL.key = q; } }
  if (seq === RCL.seq) RCL.loading = false;
  ofcDraw();
}
function rclReload() { if (RCL.data) { RCL.key = ''; if (S.route?.mod === 'office' && bkSub() === 'receipts') rclLoad(false); } }
function rclSet(patch) { Object.assign(RCL.f, patch); rclSave(); rclLoad(false); }

function rclHtml() {
  if (RCL.oid !== OFC.info?.org_id || !RCL.f) Object.assign(RCL, {oid: OFC.info?.org_id, f: rclRestore(), data: null, rows: [], key: '', err: null});
  if (RCL.open == null) RCL.open = !window.matchMedia?.('(max-width: 600px)').matches;
  const back = `<div class="ofcbar rcl-top"><a class="btn sm ghost" href="#office/books">${ic('back', 's')}<span>${tr('Bookkeeping')}</span></a><span class="spacer"></span></div>
    <h3 class="ofcgrp" id="rcl-h">${tr('All receipts')}</h3>`;
  if (RCL.key !== rclQuery() && !RCL.loading) setTimeout(() => rclLoad(false), 0);
  if (RCL.err) return back + rclFiltersHtml() + `<div class="empty">${esc(RCL.err)}</div>`;
  if (!RCL.data) return back + rclFiltersHtml() + `<p class="muted lempty">${tr('Loading…')}</p>`;
  return back + rclFiltersHtml() + rclListHtml();
}

function rclFiltersHtml() {
  const f = RCL.f, d = RCL.data || {}, all = tr('All');
  const opt = (list, cur, name) => { const o = list.map(x => [String(x.id ?? x), x.name ?? x]); if (cur && !o.some(([v]) => v === String(cur))) o.push([String(cur), name ?? String(cur)]); return o; };
  const n = ['category', 'supplier', 'project', 'q'].filter(k => f[k]).length + (f.novat ? 1 : 0) + (f.status !== 'all' ? 1 : 0);
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
      ${n ? `<button type="button" class="btn sm ghost rcl-reset" data-rcl="reset">${tr('Reset filters')}</button>` : ''}
    </div></details>`;
}

function rclRow(r) {
  const sub = [fmtDateLoc(r.date), r.supplier, r.number, r.category, r.project?.name, bkVatLabel(r.vat_pct)].filter(Boolean).join(' · ');
  const orig = r.orig_currency ? ` <small class="muted">(${esc(fmtNum(+r.orig_amount, 2))} ${esc(r.orig_currency)})</small>` : '';
  return `<li><button type="button" class="ofcrow" data-rcl="rc" data-id="${r.node_id}"><span class="ofcn"><b>${esc(r.title || tr('Receipt'))}</b>
    <small class="muted">${esc(sub)}</small></span>${r.einvoice ? `<span class="rotag">${tr('E-invoice')}</span>` : ''}${r.paid_at || !RCL.paidMark ? '' : `<span class="rotag rcl-open">${tr('Not paid')}</span>`}
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
const rclHere = () => S.route?.mod === 'office' && ofcTab() === 'books' && bkSub() === 'receipts';
let rclQT = 0;
document.addEventListener('input', e => {
  if (e.target.id !== 'rcl-q' || !rclHere()) return;
  clearTimeout(rclQT);
  const v = e.target.value.trim();
  rclQT = setTimeout(() => { if (v !== RCL.f.q) rclSet({q: v}); }, 300);
});
document.addEventListener('change', e => {
  if (!rclHere()) return;
  const t = e.target;
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
  if (t.id === 'rcl-novat') { rclSet({novat: t.checked}); }
});
document.addEventListener('toggle', e => { if (e.target.classList?.contains('rcl-filters')) RCL.open = e.target.open; }, true);
document.addEventListener('click', e => {
  const b = e.target.closest('[data-rcl]'); if (!b || !rclHere()) return;
  const k = b.dataset.rcl;
  if (k === 'rc') { bkSheet(+b.dataset.id, false); return; }
  if (k === 'more') { b.disabled = true; rclLoad(true); return; }
  if (k === 'reset') { const d = rclDefault(); rclSet({category: '', supplier: '', project: '', novat: false, q: '', status: d.status}); return; }
  if ((k === 'status' || k === 'by') && RCL.f[k] !== b.dataset.v) rclSet({[k]: b.dataset.v});
});
