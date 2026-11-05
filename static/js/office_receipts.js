// @ts-check
// 2.153.0 (#2055): the receipts list of the bookkeeping over all months (#office/books/receipts, "All receipts" below
// "Receipts this month"): a filter bar (period with quick choices, status, category, supplier, project, only without VAT
// rate, search; on the phone folded away), the rows as in the month list, the sums below, "Load more" from 200 rows on,
// and the export for the tax adviser (CSV, ZIP with the original files) of exactly the filtered list (only while the country
// pack has the export on, books.export_csv; the whole booking list of the year stays in the bookkeeping, #2461). A tap on a row opens
// the receipt sheet of office_books.js (bkSheet); after saving the list reloads (rclReload). The filters stay for the
// session (sessionStorage). Server: kalmido/office/receiptlist.py.
// 2.420.0 C (#3448): sel = the receipts ticked in the multiple choice (null: not choosing), busy = a check request running
const RCL = {oid: null, f: null, data: null, rows: [], err: null, seq: 0, key: '', loading: false, open: null, sel: null, busy: false};
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
const rclDefault = () => { const [from, to] = rclPeriod('year'); return {per: 'year', from, to, by: 'doc', status: 'all', checked: 'all', category: '', supplier: '', project: '', novat: false, hints: false, q: ''}; };
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
  if (f.checked && f.checked !== 'all') p.set('checked', f.checked);  // 2.420.0 C (#3448)
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
  const n = ['category', 'supplier', 'project', 'q'].filter(k => f[k]).length + (f.novat ? 1 : 0) + (f.hints ? 1 : 0) + (f.status !== 'all' ? 1 : 0) + (f.checked && f.checked !== 'all' ? 1 : 0);
  const seg = (k, opts) => `<div class="seg" role="group" aria-label="${esc(tr(k === 'status' ? 'Status' : k === 'checked' ? 'Checked' : 'Date by'))}">${opts.map(([v, t]) => `<button type="button" data-rcl="${k}" data-v="${v}" class="${f[k] === v ? 'on' : ''}" aria-pressed="${f[k] === v}">${esc(t)}</button>`).join('')}</div>`;
  return `<details class="rcl-filters" ${RCL.open ? 'open' : ''}><summary>${ic('filter', 's')}<span>${tr('Filters')}</span>${n ? `<span class="rotag">${n}</span>` : ''}</summary>
    <div class="rcl-grid">
      <label class="rcl-f"><span class="muted">${tr('Period')}</span>${ofcSel('rcl-per', f.per, RCL_PERIODS.map(([k, t]) => [k, tr(t)]))}</label>
      ${f.per === 'custom' ? `<span class="rcl-f rcl-days"><span class="muted">${tr('From')}</span>${dateIn('rcl-from', f.from, {label: tr('From'), clear: false})}<span class="muted">${tr('To')}</span>${dateIn('rcl-to', f.to, {label: tr('To'), clear: false})}</span>` : ''}
      <span class="rcl-f"><span class="muted">${tr('Status')}</span>${seg('status', [['all', all], ['paid', tr('Paid')], ['open', tr('Not paid')]])}</span>
      <span class="rcl-f rcl-chkf"><span class="muted">${tr('Checked')}</span>${seg('checked', [['all', all], ['yes', tr('Checked')], ['no', tr('Not checked')]])}</span>
      <span class="rcl-f"><span class="muted">${tr('Date by')}</span>${seg('by', [['doc', tr('Receipt date')], ['paid', tr('Payment date')]])}</span>
      <label class="rcl-f"><span class="muted">${tr('Category')}</span>${ofcSel('rcl-cat', f.category, opt(d.categories || [], f.category), all)}</label>
      <label class="rcl-f"><span class="muted">${tr('Supplier')}</span>${ofcSel('rcl-sup', f.supplier, opt(d.suppliers || [], f.supplier, tr('(none in this period)')), all)}</label>
      <label class="rcl-f"><span class="muted">${tr('Project')}</span>${ofcSel('rcl-pro', f.project, opt(d.projects || [], f.project, tr('(none in this period)')), all)}</label>
      <label class="rcl-f rcl-q"><span class="muted">${tr('Search')}</span><input id="rcl-q" type="search" value="${esc(f.q)}" maxlength="200" placeholder="${esc(tr('Title, supplier, invoice number'))}"></label>
      <label class="chkl rcl-novat"><input type="checkbox" id="rcl-novat" ${f.novat ? 'checked' : ''}><span>${tr('Only without VAT rate')}</span></label>
      <label class="chkl rcl-hints"><input type="checkbox" id="rcl-hints" ${f.hints ? 'checked' : ''}><span>${tr('Only with hints')}${d.hints ? ` <span class="rotag">${d.hints}</span>` : ''}</span></label>
      ${n ? `<button type="button" class="btn sm ghost rcl-reset" data-rcl="reset">${tr('Reset filters')}</button>` : ''}
    </div></details>`;
}

const rclChkTxt = r => r.checked_at ? tr('Checked by {0} on {1}', r.checked_by || '?', fmtDateLoc(String(r.checked_at).slice(0, 10))) : '';  // 2.420.0 C (#3448)
function rclRow(r) {
  const sub = [fmtDateLoc(r.date), r.supplier, r.number, r.category, r.project?.name, bkVatLabel(r.vat_pct)].filter(Boolean).join(' · ');
  const orig = r.orig_currency ? ` <small class="muted">(${esc(fmtNum(+r.orig_amount, 2))} ${esc(r.orig_currency)})</small>` : '';
  const chk = r.checked_at ? `<span class="rotag rcl-chk" title="${esc(rclChkTxt(r))}">${ic('check', 's')}${tr('Checked')}</span>` : '';  // 2.420.0 C (#3448)
  if (RCL.sel) {  // 2.420.0 C (#3448): the multiple choice -- a tap ticks the row instead of opening the receipt
    return `<li><label class="ofcrow rcl-pick"><input type="checkbox" class="rcl-pickin" data-id="${r.node_id}" ${RCL.sel.has(r.node_id) ? 'checked' : ''}>
      <span class="ofcn"><b>${esc(r.title || tr('Receipt'))}</b><small class="muted">${esc(sub)}</small></span>${chk}<span class="rksum">${ofcMoney(r.amount)}${orig}</span></label></li>`;
  }
  return `<li><button type="button" class="ofcrow" data-rcl="rc" data-id="${r.node_id}"${RCL.dockId === r.node_id ? ' aria-current="true"' : '' /* 2.557.0 A (#4553) */}><span class="ofcn"><b>${esc(r.title || tr('Receipt'))}</b>
    <small class="muted">${esc(sub)}</small></span>${chk}${r.einvoice ? `<span class="rotag">${tr('E-invoice')}</span>` : ''}${r.dup ? `<span class="rotag bk-dup">${tr('Possible duplicate')}</span>` : ''}${r.hints > (r.dup ? 1 : 0) ? `<span class="rotag rcl-hint">${tr('With hints')}</span>` : ''}${r.paid_at || !RCL.paidMark ? '' : `<span class="rotag rcl-open">${tr('Not paid')}</span>`}${r.submitted_by ? `<span class="rotag rcl-sub">${esc(tr('Handed in by {0}', r.submitted_by))}</span>` : ''}
    <span class="rksum">${ofcMoney(r.amount)}${orig}</span>${ic('right', 's')}</button></li>`;
}
// 2.420.0 C (#3448): the bar of the multiple choice: "Select" -> {n} selected, Mark as checked, Remove check, Cancel
// 2.557.0 A (#4553): a content area of 100rem and more (#view.lsdw, render.js lsd_sync): the receipt opens on the right beside
// the list (about 40 % on the left) instead of in the middle; the list stays visible and clickable, a click on another row
// replaces the receipt (unsaved changes ask first), Esc / Cancel close it and the list stays. Narrower = the dialog as before.
const rcl_docked = () => $('.modal.bk-sheet.lsddock');
async function rcl_open(id) {
  const old = rcl_docked();
  if (old) { if (+old.dataset.rxid === id) return; if (old._close) await old._close(); else modalClose(old); if (old.isConnected) return; }
  bkSheet(id, false);
}
function rcl_mark() {
  const id = RCL.dockId || 0;
  for (const b of $$('#view [data-rcl="rc"]')) { if (+b.dataset.id === id) b.setAttribute('aria-current', 'true'); else b.removeAttribute('aria-current'); }
}
function rcl_dock(md) {
  if (!rclHere() || typeof lsd_wide !== 'function' || !lsd_wide()) return;
  md.classList.add('lsddock'); RCL.dockId = +md.dataset.rxid;
  onRemove(md, () => { if (rcl_docked()) return; RCL.dockId = 0; document.body.classList.remove('rcldock'); rcl_mark(); });
  rcl_dockSync(); rcl_mark();
}
function rcl_dockSync() {
  const md = rcl_docked(); if (!md) return;
  const wrap = $('#view > .ofwrap');
  if (!rclHere() || !lsd_wide() || !wrap) { md.classList.remove('lsddock'); md.style.inset = ''; document.body.classList.remove('rcldock'); RCL.dockId = 0; rcl_mark(); return; }  // narrower again: the dialog in the middle
  document.body.classList.add('rcldock');  // start-lsd-4553.css: the list on the left 40 % of the pair
  const place = () => { const w = $('#view > .ofwrap'); if (!w || !md.classList.contains('lsddock')) return; const r = w.getBoundingClientRect(), rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
    md.style.inset = `${Math.round(r.top)}px ${Math.max(0, Math.round(innerWidth - r.right))}px 0 ${Math.round(r.left + r.width * .4 + rem)}px`; };
  place(); requestAnimationFrame(() => requestAnimationFrame(place));  // again once the wider pair is laid out (measured at once it was still the narrow page)
}
window.addEventListener('hashchange', () => setTimeout(rcl_dockSync, 0));  // another page: the receipt goes back into the middle
function rclSelBar() {
  if (!RCL.sel) return `<div class="ofcbar rcl-selbar"><button type="button" class="btn sm ghost" data-rcl="sel">${ic('check', 's')}<span>${tr('Select')}</span></button><span class="spacer"></span></div>`;
  const n = RCL.sel.size, off = !n || RCL.busy ? 'disabled' : '';
  return `<div class="ofcbar rcl-selbar on" role="toolbar" aria-label="${esc(tr('Select'))}"><button type="button" class="btn sm ghost" data-rcl="selall">${tr('Select all')}</button>
    <span class="muted rcl-seln" aria-live="polite">${esc(tr('{0} selected', n))}</span><span class="spacer"></span>
    <button type="button" class="btn sm pri" data-rcl="chk" ${off}>${ic('check', 's')}<span>${tr('Mark as checked')}</span></button>
    <button type="button" class="btn sm ghost" data-rcl="unchk" ${off}>${tr('Remove check')}</button>
    <button type="button" class="btn sm ghost" data-rcl="selx">${tr('Cancel')}</button></div>`;
}
// tick / untick receipts as checked (one undo step: only the receipts whose state changed go back)
// 2.559.0 (#4659): at once (optWrite): the rows carry the tick before the answer, a refusal takes it back; the lists follow in
// the background (bkRefresh: the rows stay until the fresh ones are there)
async function rclChecked(ids, on) {
  const put = typeof bkRowsPut === 'function' ? bkRowsPut(ids, bkChkStamp(on)) : () => null;
  const j = await optWrite(put, () => api('POST', '/api/office/books/receipts/checked', {node_ids: ids, checked: on}), ofcDraw);
  if (typeof bkRefresh === 'function') bkRefresh(); else rclReload();  // (bkRefresh reads the receipts list again too)
  return j;
}
async function rclCheckSel(on) {
  const ids = [...(RCL.sel || [])]; if (!ids.length || RCL.busy) return;
  const sel = RCL.sel; RCL.sel = null;  // 2.559.0 (#4659): the choice closes at once, a refusal brings it back
  let j; try { j = await rclChecked(ids, on); } catch { if (!RCL.sel) RCL.sel = sel; ofcDraw(); return; }  // api() said why
  const ch = j.changed || [];
  if (!ch.length) { toast(on ? tr('Already checked') : tr('Not checked')); return; }
  const label = on ? trn('{0} receipt marked as checked', '{0} receipts marked as checked', ch.length) : trn('Check removed from {0} receipt', 'Check removed from {0} receipts', ch.length);
  histToast(label, histAdd({label, undo: async () => { await rclChecked(ch, !on); return {}; }, redo: async () => { await rclChecked(ch, on); return {}; }}));
}
function rclListHtml() {
  const d = RCL.data, t = d.total, q = rclQuery();
  const exp = !ofcFeat('books.export_csv') ? '' : `<div class="ofcbar rcl-exp"><span class="spacer"></span>
    <a class="btn sm ghost" id="rcl-csv" href="/api/office/books/receipts.csv?${esc(q)}" download>${ic('download', 's')}<span>CSV</span></a>
    <a class="btn sm" id="rcl-zip" href="/api/office/books/receipts.zip?${esc(q)}" download>${ic('download', 's')}<span>${tr('ZIP for the tax adviser')}</span></a></div>`;
  if (!t.count) RCL.sel = null;
  if (!t.count) return `${exp}<p class="muted lempty rcl-empty">${tr('No receipts match these filters.')}</p>${bkNote()}`;
  // the mark "Not paid" only where payments are recorded at all (bank reconciliation) and the list mixes both
  RCL.paidMark = RCL.f.status === 'all' && RCL.rows.some(r => r.paid_at);
  return `${exp}${rclSelBar()}<ul class="ofclist rcl-list${RCL.sel ? ' rcl-choosing' : ''}" role="list" aria-labelledby="rcl-h">${RCL.rows.map(rclRow).join('')}</ul>
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
  if (t.id === 'rcl-hints') { rclSet({hints: t.checked}); return; }  // 2.299.0 D (#3193)
  if (t.classList?.contains('rcl-pickin') && RCL.sel) { const id = +t.dataset.id; if (t.checked) RCL.sel.add(id); else RCL.sel.delete(id); ofcDraw(); }  // 2.420.0 C (#3448)
});
document.addEventListener('toggle', e => { const t = /** @type {any} */ (e.target); if (t.classList?.contains('rcl-filters')) RCL.open = t.open; }, true);
document.addEventListener('click', e => {
  const b = /** @type {any} */ (e.target).closest?.('[data-rcl]'); if (!b || !rclHere()) return;
  const k = b.dataset.rcl;
  if (k === 'rc') { rcl_open(+b.dataset.id); return; }  // 2.557.0 A (#4553): beside the list on a wide area
  if (k === 'more') { b.disabled = true; rclLoad(true); return; }
  if (k === 'reset') { const d = rclDefault(); rclSet({category: '', supplier: '', project: '', novat: false, hints: false, q: '', status: d.status, checked: d.checked}); return; }
  // 2.420.0 C (#3448): the multiple choice
  if (k === 'sel') { RCL.sel = new Set(); ofcDraw(); return; }
  if (k === 'selx') { RCL.sel = null; ofcDraw(); return; }
  if (k === 'selall' && RCL.sel) { const all = RCL.rows.every(r => RCL.sel.has(r.node_id)); RCL.sel = new Set(all ? [] : RCL.rows.map(r => r.node_id)); ofcDraw(); return; }
  if (k === 'chk' || k === 'unchk') { rclCheckSel(k === 'chk'); return; }
  if ((k === 'status' || k === 'by' || k === 'checked') && (RCL.f[k] || 'all') !== b.dataset.v) rclSet({[k]: b.dataset.v});
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
  return `<div class="rcp">${typeof bkPhotoHtml === 'function' ? bkPhotoHtml() : ''}${kinds}${rsb_inHtml()}${amv_html()}${rcn_html()}${rclHtml(true)}</div>`;  // 2.356.0 D (#3129): + handed in; 2.522.0 (#4433): + new in the office; 2.547.0 (#4434): + the old receipts' move
}

// ---- 2.522.0 (#4433): "New in the office" -- the documents the general input sorted into the office (or a person moved there)
// that nobody recorded as a receipt yet (GET /api/docs?area=office&unbooked=1, docs/area.py); a row opens the document sheet
// (record as receipt, "Wrong area"). Nothing becomes a receipt by itself.
const RCN = {key: '', rows: null, loading: false};
async function rcn_load(key) {
  RCN.loading = true;
  try { const j = await api('GET', '/api/docs?ws=all&area=office&unbooked=1&facets=0&limit=50'); if (RCN.key === key) RCN.rows = j.docs || []; }
  catch { if (RCN.key === key) RCN.rows = []; }
  RCN.loading = false; ofcDraw();
}
function rcn_html() {
  const key = String(OFC.info?.org_id || '');
  if (RCN.key !== key) Object.assign(RCN, {key, rows: null});
  if (RCN.rows === null) { if (!RCN.loading) setTimeout(() => rcn_load(key), 0); return ''; }
  if (!RCN.rows.length) return '';
  return `<section class="rcn" aria-labelledby="rcn-h"><h3 class="ofcgrp" id="rcn-h">${tr('New in the office')}</h3>
    <ul class="ofclist rcn-list" role="list">${RCN.rows.map(d => `<li class="ofcrow rcn-row"><a href="#docs/${d.id}" class="ofcn"><b>${esc(d.sender?.name || d.name)}</b><small class="muted">${esc([d.date ? fmtDateLoc(d.date) : '', d.amount ? curMoney(d.amount, d.currency) : ''].filter(Boolean).join(' · '))}</small></a></li>`).join('')}</ul></section>`;
}

// ---- 2.547.0 (#4434): the old receipts of the own documents into the office, once (docs/areamove.py): a hint with the number,
// the preview (each row "Move" / "Stays", preset by the server: the tag Tax and every doubt stay), one click moves, one undo of
// the whole move for 30 days. Nothing moves by itself.
const AMV = {key: '', info: null, loading: false};
async function amv_load(key) {
  AMV.loading = true;
  try { const j = await api('GET', '/api/docs/office-move?count=1'); if (AMV.key === key) AMV.info = j; }
  catch { if (AMV.key === key) AMV.info = {n: 0}; }
  AMV.loading = false; ofcDraw();
}
const amv_undoKey = id => 'kalmido.amv.undo.' + id;
function amv_html() {
  const key = String(OFC.info?.org_id || '');
  if (AMV.key !== key) Object.assign(AMV, {key, info: null});
  if (!AMV.info) { if (!AMV.loading) setTimeout(() => amv_load(key), 0); return ''; }
  const i = AMV.info, u = i.undo;
  let seen = false; try { seen = !!(u && localStorage.getItem(amv_undoKey(u.id))); } catch { /* private mode */ }
  if (u && !seen) {
    return `<div class="shint amv" role="group"><span>${esc(trn('{0} receipt was moved from your documents into the office.', '{0} receipts were moved from your documents into the office.', u.n))} <small class="muted">${esc(tr('Undo possible until {0}', fmtDateLoc(String(u.until).slice(0, 10))))}</small></span>
      <button type="button" class="btn sm ghost" data-amv="undo">${ic('undo', 's')} ${tr('Undo')}</button><button type="button" class="btn sm ghost" data-amv="seen">${tr('Hide')}</button></div>`;
  }
  if (!i.n || i.hidden) return '';
  return `<div class="shint amv" role="group"><span>${esc(trn('{0} receipt is still in your documents', '{0} receipts are still in your documents', i.n))}</span>
    <button type="button" class="btn sm" data-amv="open">${tr('Show')}</button><button type="button" class="btn sm ghost" data-amv="hide">${tr('Hide')}</button></div>`;
}
const amv_again = () => { AMV.info = null; RCN.rows = null; ofcDraw(); };
function amv_row(x) {
  const why = [x.why, x.tax ? tr('Tag Tax') : '', x.sure ? '' : tr('Not sure'), x.block || ''].filter(Boolean).join(' · ');
  return `<li class="amv-row"><span class="amv-n"><b>${esc(x.name)}</b><small class="muted">${esc(why)}</small></span>
    <select data-amv-id="${x.id}" aria-label="${esc(x.name)}" ${x.block ? 'disabled' : ''}><option value="move" ${x.pick === 'move' ? 'selected' : ''}>${tr('Move')}</option><option value="stay" ${x.pick === 'move' ? '' : 'selected'}>${tr('Stays')}</option></select></li>`;
}
async function amv_open() {
  let j; try { j = await api('GET', '/api/docs/office-move'); } catch { return; }
  const md = modal(`<h3>${tr('Move receipts into the office')}</h3>
    <p class="muted">${esc(tr('These documents in your own documents are receipts. Only your click moves them; you can undo the whole move for 30 days.'))}</p>
    <ul class="list amv-list" role="list">${(j.items || []).map(amv_row).join('')}</ul>
    ${j.more ? `<p class="muted">${esc(trn('{0} more receipt follows after this move', '{0} more receipts follow after this move', j.more))}</p>` : ''}
    <div class="foot"><span class="spacer"></span><button type="button" class="btn" data-m="close">${tr('Cancel')}</button><button type="button" class="btn pri" data-m="go">${ic('check', 's')} <span class="amv-go"></span></button></div>`);
  md.classList.add('amvmd');
  const ids = () => $$('select[data-amv-id]', md).filter(s => !s.disabled && s.value === 'move').map(s => +s.dataset.amvId);
  const sync = () => { const n = ids().length; $('.amv-go', md).textContent = trn('Move {0} receipt', 'Move {0} receipts', n); $('[data-m="go"]', md).disabled = !n; };
  sync();
  md.addEventListener('change', sync);
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    b.disabled = true;
    let r; try { r = await api('POST', '/api/docs/office-move', {ids: ids()}); } catch { b.disabled = false; return; }
    md.remove();
    toast(trn('{0} receipt moved into the office', '{0} receipts moved into the office', r.moved) + (r.stayed?.length ? ' · ' + trn('{0} stays', '{0} stay', r.stayed.length) : ''));
    amv_again();
  });
}
document.addEventListener('click', async e => {
  const b = e.target.closest?.('[data-amv]'); if (!b) return;
  const k = b.dataset.amv, u = AMV.info?.undo;
  if (k === 'open') { amv_open(); return; }
  if (k === 'seen' && u) { try { localStorage.setItem(amv_undoKey(u.id), '1'); } catch { /* private mode */ } ofcDraw(); return; }
  b.disabled = true;
  try {
    if (k === 'hide') await api('POST', '/api/docs/office-move/hide');
    if (k === 'undo' && u) {
      if (!await askConfirm(tr('Undo the move?'), tr('The receipts go back into your own documents, to their folders. A receipt changed since stays in the office.'), {ok: tr('Undo')})) { b.disabled = false; return; }
      const r = await api('POST', `/api/docs/office-move/${u.id}/undo`);
      toast(trn('{0} receipt is back in your documents', '{0} receipts are back in your documents', r.back) + (r.stayed?.length ? ' · ' + trn('{0} stays', '{0} stay', r.stayed.length) : ''));
    }
  } catch { b.disabled = false; return; }
  amv_again();
});

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
    <div class="bk-photo rsb-up">${isTouch() ? `<label class="btn pri">${ic('camera')}<span>${tr('Photograph receipt')}</span><input type="file" id="rsb-shot" accept="image/*,application/pdf" capture="environment" multiple hidden></label>` : ''}
    <label class="btn${isTouch() ? '' : ' pri'}">${ic('upload')}<span>${tr('Upload files')}</span><input type="file" id="rsb-files" accept="${typeof BK_ACCEPT === 'string' ? BK_ACCEPT : 'image/*,application/pdf'}" multiple hidden></label></div>
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
    <small class="muted">${esc([tr('Handed in by {0}', r.by?.name || '?'), fmtDateLoc(String(r.submitted_at || '').slice(0, 10))].join(' · '))}</small></span>${ic('right', 's')}</button></li>`).join('')}</ul></section>`;
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

// ---- 2.424.0 B (#3450): receipts by e-mail (office settings, area Data): the forwarding address of this office (the
// company's and the personal office's apart, GET /api/office/receipt-mail), a copy button and a short Gmail filter guide.
// A mail to it with a PDF, or with a download link to one that needs no login, becomes a document and a receipt suggestion.
const RCM = {d: null, oid: undefined, loading: false};
async function rcm_load() {
  if (RCM.loading) return;
  RCM.loading = true;
  const oid = OFC.info?.org_id;
  try { RCM.d = await api('GET', '/api/office/receipt-mail'); } catch { RCM.d = false; }
  RCM.oid = oid; RCM.loading = false;
  ofcDraw();
}
function rcm_settingsHtml() {
  if (RCM.oid !== OFC.info?.org_id && !RCM.loading) { RCM.d = null; setTimeout(rcm_load, 0); return ''; }
  const d = RCM.d;
  if (!d || !d.enabled) return '';  // no mail input on this server (or not loaded yet)
  return `<h3 id="rcm-h">${tr('Receipts by e-mail')}</h3>
    <p class="shint keep">${tr('Forward invoices to this address: attached PDFs and download links that need no sign-in become documents and receipt suggestions.')}</p>
    ${d.address ? `<p class="rcm-addr"><code id="rcm-addr">${esc(d.address)}</code> <button type="button" class="btn sm" data-rcm="copy">${ic('copy', 's')}<span>${tr('Copy')}</span></button> <button type="button" class="linkbtn" data-rcm="renew">${tr('New address')}</button></p>`
      : `<p><button type="button" class="btn sm" data-rcm="make">${tr('Create address')}</button></p>`}
    <details class="rcm-gmail"><summary>${tr('Forward automatically from Gmail')}</summary><ol>
      <li>${esc(tr('In Gmail: Settings > See all settings > Forwarding and POP/IMAP > Add a forwarding address. Enter this address; the confirmation code arrives here as a document.'))}</li>
      <li>${esc(tr('Search for the e-mails of your invoice senders, for example from:(stripe.com OR paddle.com OR apple.com), and select “Create filter”.'))}</li>
      <li>${esc(tr('Tick “Forward it to”, select this address and create the filter.'))}</li></ol></details>`;
}
document.addEventListener('click', async e => {
  const b = /** @type {any} */ (e.target).closest?.('[data-rcm]'); if (!b) return;
  const k = b.dataset.rcm;
  if (k === 'copy') {
    const v = RCM.d?.address || '';
    try { await navigator.clipboard.writeText(v); toast(tr('Copied')); } catch { toast(v); }
    return;
  }
  // 2.424.0 B2 (#3450, review): the address is the documents space's one -- its documents address and letters' reply address change too
  if (k === 'renew' && !await askConfirm(tr('New address?'), tr('The old address stops working. The documents address and the reply address of letters of this area change with it.'), {ok: tr('New address')})) return;
  try { RCM.d = await api('POST', '/api/office/receipt-mail', {renew: k === 'renew'}); } catch { return; }
  ofcDraw();
});
