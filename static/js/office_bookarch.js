// @ts-check
/* Kalmido web client: Office & finance, the booking archive (2.414.0 A, #3502; server: office/bookarch.py). Bookkeeping ->
   "Booking archive" (#office/books/archive): the complete DATEV data of past years, read only. A year at a time: the bookings
   (filters account, counter account, period, amount, receipt field, text; pages of 200 from the server, never a whole year
   in the page), the sums per account, one booking with every column of its line and its receipt image; below the runs
   (original files, undo) and the server's note. The dialog "Read DATEV data" checks the files first (counts per year,
   debit = credit), then takes them over as one run. Office admins only, with the DATEV function on.
   Classic script sharing the global scope with the others (load order: lazyload.js, module "office"). */
'use strict';

const BKA = /** @type {any} */ ({oid: null, ov: null, err: null, year: 0, view: 'list', f: {}, list: null, sums: null, seq: 0, files: null, busy: false});
const BKA_PAGE = 200;
const BKA_FILTERS = [['account', N_('Account')], ['counter', N_('Counter account')], ['from', N_('From')], ['to', N_('To')],
  ['min', N_('Amount from')], ['max', N_('Amount to')], ['doc', N_('Receipt field')], ['q', N_('Text')]];
const BKA_KIND = {batch: N_('Booking batch'), labels: N_('Account labels'), master: N_('Debtors and creditors'), docs: N_('Receipt images'),
  duplicate: N_('Already in the archive'), unknown: N_('Not read')};
const BKA_URL = '/api/office/books/archive';

const bkaReset = () => Object.assign(BKA, {oid: OFC.info?.org_id, ov: null, err: null, year: 0, view: 'list', f: {}, list: null, sums: null});
const bkaSide = s => s === 'H' ? tr('Credit|side') : tr('Debit|side');
const bkaAmt = (n, s) => `${esc(ofcMoney(n))} <small class="muted">${esc(s === 'H' ? 'H' : 'S')}</small>`;
const bkaDay = s => fmtDateLoc(s) || esc(s || '');
const bkaAcct = (a, l) => a ? `<b>${esc(a)}</b>${l ? ` <small class="muted">${esc(l)}</small>` : ''}` : '';

async function bkaLoad() {
  const seq = ++BKA.seq;
  try {
    const ov = await api('GET', BKA_URL);
    if (seq !== BKA.seq) return;
    const ys = (ov.years || []).map(y => y.year);
    if (!ys.includes(BKA.year)) { BKA.year = ys[0] || 0; BKA.list = null; BKA.sums = null; }
    Object.assign(BKA, {ov, err: null});
  } catch (x) { if (seq === BKA.seq) BKA.err = /** @type {any} */ (x).message || tr('unknown'); }
  ofcDraw();
}
const bkaQuery = (offset = 0) => {
  const p = new URLSearchParams({year: String(BKA.year), offset: String(offset), limit: String(BKA_PAGE)});
  for (const [k, v] of Object.entries(BKA.f)) if (String(v).trim()) p.set(k, String(v).trim());
  return p.toString();
};
async function bkaLoadList(more) {
  const seq = ++BKA.seq, old = more ? BKA.list : null;
  if (old) old.loading = true;
  try {
    const j = await api('GET', `${BKA_URL}/bookings?${bkaQuery(old ? old.items.length : 0)}`);
    if (seq !== BKA.seq) return;
    BKA.list = old ? {...j, items: [...old.items, ...j.items]} : j;
  } catch (x) { if (seq === BKA.seq) BKA.list = {error: /** @type {any} */ (x).message || tr('unknown'), items: []}; }
  ofcDraw();
}
async function bkaLoadSums() {
  const seq = ++BKA.seq;
  try { const j = await api('GET', `${BKA_URL}/accounts?year=${BKA.year}`); if (seq === BKA.seq) BKA.sums = j.items || []; }
  catch (x) { if (seq === BKA.seq) BKA.sums = {error: /** @type {any} */ (x).message || tr('unknown')}; }
  ofcDraw();
}

// ---- the page
function bkaHtml() {
  if (BKA.oid !== OFC.info?.org_id) bkaReset();
  const back = `<a class="btn sm ghost" href="#office/books">${ic('back', 's')}<span>${tr('Bookkeeping')}</span></a>`;
  if (!ofcFeat('books.datev')) return `<div class="ofcbar">${back}</div><div class="empty">${tr('The DATEV function is switched off for this office.')}</div>`;
  if (BKA.err) return `<div class="ofcbar">${back}</div><div class="empty">${esc(BKA.err)}</div>`;
  if (!BKA.ov) { if (!BKA.loadingT) BKA.loadingT = setTimeout(() => { BKA.loadingT = 0; bkaLoad(); }, 0); return `<p class="muted lempty">${tr('Loading…')}</p>`; }
  const ov = BKA.ov, years = ov.years || [];
  const read = `<button type="button" class="btn sm" data-bka="read">${ic('upload', 's')}<span>${tr('Read DATEV data')}</span></button>`;
  const head = `<div class="ofcbar bka-bar">${back}<span class="spacer"></span>${years.length ? `<label class="bk-year"><span class="muted">${tr('Year')}</span>${ofcSel('bka-year', BKA.year, years.map(y => [y.year, String(y.year)]))}</label>` : ''}${read}</div>
    <h2 class="bka-h">${tr('Booking archive')}</h2>`;
  const note = `<p class="muted bk-note bka-note">${esc(ov.note || '')}</p>`;
  if (!years.length) {
    return head + `<div class="bka-empty"><p>${tr('The archive holds the complete DATEV data of past years: every booking, the account labels and the receipt images, read only.')}</p>
      <p class="muted">${tr('Ask your tax advisor for the DATEV export of each year (booking batch, account labels, receipt images as ZIP) and read it in here.')}</p><p>${read}</p></div>`
      + bkaRunsHtml() + note;
  }
  const y = years.find(x => x.year === BKA.year) || years[0];
  const seg = `<div class="seg bka-seg" role="group" aria-label="${esc(tr('View'))}">${[['list', tr('Bookings|ledger')], ['sum', tr('Sums per account')]].map(([k, n]) =>
    `<button type="button" data-bka="view" data-v="${k}" class="${BKA.view === k ? 'on' : ''}" aria-pressed="${BKA.view === k}">${esc(n)}</button>`).join('')}</div>`;
  const info = `<p class="muted ofchint bka-yinfo">${esc([trn('{0} booking', '{0} bookings', y.bookings), y.first && y.last ? `${fmtDateLoc(y.first)} – ${fmtDateLoc(y.last)}` : '',
    y.docs ? trn('{0} receipt image', '{0} receipt images', y.docs) : '', tr('kept until {0}', fmtDateLoc(y.keep_until))].filter(Boolean).join(' · '))}</p>`;
  return head + info + seg + (BKA.view === 'sum' ? bkaSumsHtml() : bkaListHtml()) + bkaRunsHtml() + note;
}

function bkaListHtml() {
  const f = BKA.f, active = Object.values(f).some(v => String(v).trim());
  const wide = typeof matchMedia === 'function' && matchMedia('(min-width: 768px)').matches;
  const inp = ([k, n]) => {
    const t = k === 'from' || k === 'to' ? 'date' : 'text', num = k === 'min' || k === 'max' || k === 'account' || k === 'counter';
    return `<label class="bka-f"><span class="muted">${esc(tr(n))}</span><input type="${t}" data-bkaf="${k}" value="${esc(f[k] || '')}"${num ? ' inputmode="decimal"' : ''} maxlength="${k === 'q' ? 100 : 36}"></label>`;
  };
  const filt = `<details class="bka-filt"${wide || active ? ' open' : ''}><summary>${ic('filter', 's')}<span>${tr('Filter')}</span>${active ? ` <span class="rotag">${tr('active')}</span>` : ''}</summary>
    <form class="bka-fgrid" data-bka-form>${BKA_FILTERS.map(inp).join('')}
    <div class="lacts"><button type="submit" class="btn sm pri">${ic('search', 's')}<span>${tr('Search')}</span></button>${active ? `<button type="button" class="btn sm ghost" data-bka="clear">${tr('Reset filters')}</button>` : ''}</div></form></details>`;
  const l = BKA.list;
  if (!l) { setTimeout(() => { if (!BKA.list) bkaLoadList(false); }, 0); return filt + `<p class="muted bka-wait">${tr('Loading…')}</p>`; }
  if (l.error) return filt + `<p class="aerr" role="alert">${esc(l.error)}</p>`;
  const any = f.any ? `<p class="muted bka-anyl">${esc(tr('Account {0}, either side', f.any))}</p>` : '';
  const sum = `<p class="bka-sum" aria-live="polite"><b>${esc(trn('{0} booking', '{0} bookings', l.total))}</b> · ${esc(tr('Debit {0} · Credit {1}', ofcMoney(l.debit), ofcMoney(l.credit)))}</p>`;
  const row = x => `<li><button type="button" class="ofcrow bka-row" data-bka="row" data-id="${x.id}"><span class="bka-day">${bkaDay(x.day)}</span>
    <span class="ofcn"><span class="bka-acc">${bkaAcct(x.account, x.account_label)}${x.counter ? ` <span class="muted">→</span> ${bkaAcct(x.counter, x.counter_label)}` : ''}</span>
    <small class="muted">${esc([x.doc1, x.text].filter(Boolean).join(' · '))}</small></span>
    ${x.doc_id ? `<span class="bka-doc" title="${esc(tr('Receipt image'))}">${ic('clip', 's')}<span class="sr">${tr('Receipt image')}</span></span>` : ''}<span class="rksum">${bkaAmt(x.amount, x.side)}</span></button></li>`;
  const list = l.items.length ? `<ul class="ofclist bka-list" role="list">${l.items.map(row).join('')}</ul>` : `<p class="muted lempty bka-none">${tr('No bookings match the filter.')}</p>`;
  const more = l.items.length < l.total ? `<p class="bka-more"><button type="button" class="btn ghost" data-bka="more"${l.loading ? ' disabled' : ''}>${esc(tr('Load more ({0} of {1})', l.items.length, l.total))}</button></p>` : '';
  return filt + any + sum + list + more;
}

function bkaSumsHtml() {
  const s = BKA.sums;
  if (!s) { setTimeout(() => { if (!BKA.sums) bkaLoadSums(); }, 0); return `<p class="muted bka-wait">${tr('Loading…')}</p>`; }
  if (s.error) return `<p class="aerr" role="alert">${esc(s.error)}</p>`;
  if (!s.length) return `<p class="muted lempty">${tr('None')}</p>`;
  const th = `<thead><tr><th>${tr('Account')}</th><th class="num">${tr('Bookings|ledger')}</th><th class="num">${tr('Debit|side')}</th><th class="num">${tr('Credit|side')}</th><th class="num">${tr('Balance')}</th></tr></thead>`;
  const td = x => `<tr data-bka="acct" data-acct="${esc(x.account)}" tabindex="0"><th scope="row">${bkaAcct(x.account, x.label)}</th><td class="num" data-l="${esc(tr('Bookings|ledger'))}">${x.count}</td>
    <td class="num" data-l="${esc(tr('Debit|side'))}">${esc(ofcMoney(x.debit))}</td><td class="num" data-l="${esc(tr('Credit|side'))}">${esc(ofcMoney(x.credit))}</td><td class="num" data-l="${esc(tr('Balance'))}">${bkaAmt(x.balance, x.side)}</td></tr>`;
  return `<p class="muted ofchint">${tr('Every booking counts on its account and on its counter account. Tap an account for its bookings.')}</p>
    <table class="bk-tab bka-sums">${th}<tbody>${s.map(td).join('')}</tbody></table>`;
}

function bkaRunsHtml() {
  const runs = BKA.ov?.runs || [];
  if (!runs.length) return '';
  const cnt = c => [c.bookings ? trn('{0} booking', '{0} bookings', c.bookings) : '', c.labels ? trn('{0} account label', '{0} account labels', c.labels) : '',
    c.docs ? trn('{0} receipt image', '{0} receipt images', c.docs) : '', c.skipped ? tr('{0} skipped', c.skipped) : ''].filter(Boolean).join(' · ');
  const run = r => `<li class="bka-run${r.undone_at ? ' bka-undone' : ''}" data-run="${r.id}"><span class="ofcn"><b>${esc(fmtDateNum(new Date(r.created_at)))}${r.user_name ? ` · ${esc(r.user_name)}` : ''}</b>
    <small class="muted">${esc(cnt(r.counts || {}))}</small>
    ${r.undone_at ? '' : `<span class="bka-files">${(r.files || []).map(f => `<a href="${BKA_URL}/files/${f.id}" download title="SHA-256 ${esc(f.sha256 || '')}">${ic('download', 's')}<span>${esc(f.name)}</span></a>`).join('')}</span>`}</span>
    ${r.undone_at ? `<span class="rotag">${tr('undone')}</span>` : `<button type="button" class="btn sm ghost" data-bka="undo" data-id="${r.id}">${ic('undo', 's')}<span>${tr('Undo')}</span></button>`}</li>`;
  return `<section class="bk-sec bka-runs" aria-labelledby="bka-rh"><h3 class="ofcgrp" id="bka-rh">${tr('Imports')}</h3><ul class="ofclist" role="list">${runs.map(run).join('')}</ul></section>`;
}

// ---- one booking: every column of its line
async function bkaOpen(id) {
  let j;
  try { j = await api('GET', `${BKA_URL}/bookings/${id}`); } catch (x) { toast(/** @type {any} */ (x).message || tr('unknown')); return; }
  const raw = Object.entries(j.raw || {});
  const md = modal(`<h3>${esc(tr('Booking {0}', fmtDateLoc(j.day) || j.day || ''))}</h3>
    <p class="bka-dsum">${bkaAcct(j.account, j.account_label)}${j.counter ? ` <span class="muted">→</span> ${bkaAcct(j.counter, j.counter_label)}` : ''} · <b>${esc(ofcMoney(j.amount))}</b> ${esc(bkaSide(j.side))}</p>
    <div class="bka-raw scroll"><table class="bka-rawt"><tbody>${raw.map(([k, v]) => `<tr><th scope="row">${esc(k)}</th><td>${esc(v)}</td></tr>`).join('')}</tbody></table></div>
    <p class="muted ofchint">${esc(tr('Line {0} of the booking batch; read only.', j.line))}</p>
    <div class="foot">${j.doc_id ? `<a class="btn" href="${BKA_URL}/docs/${j.doc_id}" target="_blank" rel="noopener" data-bka-doc>${ic('file', 's')}<span>${tr('Open receipt')}</span></a>` : ''}<span class="spacer"></span><button type="button" class="btn pri" data-m="close">${tr('Close')}</button></div>`);
  md.classList.add('bka-dlg');
  md.addEventListener('click', e => { if (/** @type {any} */ (e.target).closest('[data-m="close"]')) md.remove(); });
}

// ---- the dialog: files -> preview -> take over
function bkaDialog() {
  BKA.files = null;
  const md = ofdDlg(tr('Read DATEV data'), `<p class="muted ofchint">${tr('The DATEV export of past years from your tax advisor: booking batches, account labels, debtors / creditors and receipt images (document.xml with its files), also as one ZIP.')}</p>
    <p class="bka-ro">${tr('Read only: the past years do not flow into the income statement, VAT or reserve.')}</p>
    <div class="row"><label for="bka-file">${tr('Files')}</label><input type="file" id="bka-file" multiple accept=".csv,.txt,.zip,.xml,.pdf,.jpg,.jpeg,.png,.tif,.tiff,text/csv,application/zip,application/xml"></div>
    <div id="bka-pv" class="bkapv" aria-live="polite"></div>`, tr('Take over'), async () => {
    const fs = BKA.files;
    if (!fs?.length) throw new Error(tr('Choose a file first'));
    if (!await importTargetConfirm({what: tr('the data of the files'), ws: ofcWs(), place: tr('Office')})) return false;
    const fd = new FormData(); for (const f of fs) fd.append('file', f);
    const j = await api('POST', `${BKA_URL}/import`, fd);
    BKA.year = Math.max(0, ...(j.years || []).map(y => y.year)); bkaReload();
    const skip = j.counts?.docs_skipped ? ' · ' + trn('{0} receipt without image content left out', '{0} receipts without image content left out', j.counts.docs_skipped) : '';
    toast(trn('{0} booking taken over', '{0} bookings taken over', j.counts?.bookings || 0) + skip, async () => { await api('POST', `${BKA_URL}/runs/${j.run_id}/undo`); bkaReload(); }, 12000);
  });
  md.classList.add('bka-imp');
  const ok = /** @type {any} */ ($('[data-m="ok"]', /** @type {any} */ (md))); if (ok) ok.disabled = true;
  return md;
}
async function bkaCheck(input) {
  const md = input.closest('.modal') || document, pv = $('#bka-pv', md), ok = $('[data-m="ok"]', md);
  const fs = [...(input.files || [])]; BKA.files = fs.length ? fs : null;
  if (ok) ok.disabled = true;
  if (!fs.length || !pv) { if (pv) pv.innerHTML = ''; return; }
  pv.innerHTML = `<p class="muted">${tr('Loading…')}</p>`;
  const fd = new FormData(); for (const f of fs) fd.append('file', f);
  let j;
  try { j = await api('POST', `${BKA_URL}/check`, fd); } catch (x) { pv.innerHTML = `<p class="aerr" role="alert">${esc(/** @type {any} */ (x).message || tr('unknown'))}</p>`; BKA.files = null; return; }
  pv.innerHTML = bkaPreviewHtml(j);
  if (ok) ok.disabled = !j.ok;
}
function bkaPreviewHtml(j) {
  const c = j.counts || {};
  const years = (j.years || []).map(y => `<li class="bka-pyear" data-year="${y.year}"><span class="ofcn"><b>${esc(String(y.year))} · ${esc(trn('{0} booking', '{0} bookings', y.bookings))}</b>
    <small class="muted">${esc([tr('Debit {0} · Credit {1}', ofcMoney(y.debit), ofcMoney(y.credit)),
      y.lines_debit != null ? tr('lines: debit {0}, credit {1}', ofcMoney(y.lines_debit), ofcMoney(y.lines_credit)) : '', y.no_counter ? tr('{0} without counter account', y.no_counter) : '',
      y.bad ? tr('{0} lines not readable', y.bad) : ''].filter(Boolean).join(' · '))}</small></span>
    ${y.balanced ? `<span class="rotag bka-bal">${tr('Debit = Credit')}</span>` : `<span class="bk-warn bka-unbal">${esc(tr('Debit and credit differ: {0} / {1}', ofcMoney(y.debit), ofcMoney(y.credit)))}</span>`}</li>`).join('');
  const files = (j.files || []).map(f => `<li class="bka-pfile" data-kind="${esc(f.kind)}"><span class="ofcn"><b>${esc(f.name)}</b>
    <small class="muted">${esc([tr(BKA_KIND[f.kind] || f.kind), f.year ? String(f.year) : '', f.rows ? trn('{0} row', '{0} rows', f.rows) : '', f.reason].filter(Boolean).join(' · '))}</small></span>
    ${f.kind === 'duplicate' ? `<span class="rotag bka-dup">${tr('Already in the archive')}</span>` : ''}</li>`).join('');
  const docs = c.docs || c.docs_known || c.docs_no_booking || c.docs_missing
    ? `<p class="bka-pdocs">${esc([tr('Receipt images: {0} linked', c.docs || 0), c.docs_known ? tr('{0} already in the archive', c.docs_known) : '',
      c.docs_no_booking ? tr('{0} without booking', c.docs_no_booking) : '', c.docs_missing ? tr('{0} files missing', c.docs_missing) : ''].filter(Boolean).join(' · '))}</p>` : '';
  const errs = (j.errors || []).map(e => `<p class="aerr">${esc([e.file, e.error].filter(Boolean).join(': '))}</p>`).join('');
  return (years ? `<h4>${tr('Years')}</h4><ul class="ofclist bka-pyears" role="list">${years}</ul>` : '')
    + (files ? `<h4>${tr('Files')}</h4><ul class="ofclist bka-pfiles" role="list">${files}</ul>` : '') + docs + errs
    + (j.ok ? '' : `<p class="muted bka-pnone">${tr('Nothing to take over')}</p>`);
}

const bkaReload = () => { BKA.ov = null; BKA.list = null; BKA.sums = null; ofcDraw(); };
async function bkaUndo(id) {
  if (!await askConfirm(tr('Undo this import?'), tr('Its bookings, labels, receipt images and original files leave the archive.'), {ok: tr('Undo'), danger: true})) return;
  try { await api('POST', `${BKA_URL}/runs/${id}/undo`); } catch (x) { toast(/** @type {any} */ (x).message || tr('unknown')); return; }
  bkaReload(); toast(tr('Import undone'));
}
const bkaSetList = () => { BKA.list = null; BKA.view = 'list'; ofcDraw(); };

document.addEventListener('click', e => {
  const b = /** @type {any} */ (e.target).closest?.('[data-bka]'); if (!b) return;
  const k = b.dataset.bka;
  if (k === 'read') bkaDialog();
  else if (k === 'view') { BKA.view = b.dataset.v; ofcDraw(); }
  else if (k === 'row') bkaOpen(+b.dataset.id);
  else if (k === 'more') { b.disabled = true; bkaLoadList(true); }
  else if (k === 'clear') { BKA.f = {}; bkaSetList(); }
  else if (k === 'acct') { BKA.f = {any: b.dataset.acct}; bkaSetList(); }
  else if (k === 'undo') bkaUndo(+b.dataset.id);
});
document.addEventListener('keydown', e => {
  const t = /** @type {any} */ (e.target);
  if ((e.key === 'Enter' || e.key === ' ') && t.dataset?.bka === 'acct') { e.preventDefault(); t.click(); }
});
document.addEventListener('submit', e => {
  const f = /** @type {any} */ (e.target); if (!f.matches?.('[data-bka-form]')) return;
  e.preventDefault();
  const v = {}; for (const i of f.querySelectorAll('[data-bkaf]')) if (i.value.trim()) v[i.dataset.bkaf] = i.value.trim();
  if (BKA.f.any && !v.account && !v.counter) v.any = BKA.f.any;  // the account picked in the sums stays until reset
  BKA.f = v; bkaSetList();
});
document.addEventListener('change', e => {
  const t = /** @type {any} */ (e.target);
  if (t.id === 'bka-file') bkaCheck(t);
  else if (t.id === 'bka-year') { BKA.year = +t.value; BKA.list = null; BKA.sums = null; ofcDraw(); }
});
