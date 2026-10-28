// 2.90.0 B (#1921): bank reconciliation in the office (tab "Bank", admins of the office area only): import a statement
// (CSV export of the bank with a column mapping like the household budget, CAMT.052 / .053 XML or MT940), then match every booking
// with one tap: money in -> an open invoice (a payment is recorded; less than open = partly paid), money out -> a receipt
// (its payment day), or private / ignore. Every step has its undo; an import can be taken back while none of it is matched.
// Server: kalmido/office/bank.py. No bank access.
const BNK = {oid: null, state: 'open', data: null, q: '', err: null, imports: null, showImp: false, other: null, cand: null, candQ: '', busy: false, split: false};
OFC_TABS.splice(OFC_TABS.findIndex(t => t[0] === 'settings'), 0, ['bank', 'bank', N_('Bank'), 1, () => bnkHtml(), 'money']);  // admins only; 2.92.1 (#1917): in the menu group Money
const BNK_KIND = {invoice: N_('Invoice'), receipt: N_('Receipt'), private: N_('Private'), ignored: N_('Ignored'), noreceipt: N_('No receipt needed')};  // 2.299.0 C (#3192): noreceipt

async function bnkLoad() {
  const q = 'state=' + BNK.state; BNK.q = q;
  try { const j = await api('GET', '/api/office/bank/tx?' + q); if (BNK.q === q) { BNK.data = j; BNK.err = null; } }
  catch (x) { BNK.err = x.message || tr('unknown'); }
  if (BNK.showImp) await bnkImpLoad(false);
  ofcDraw();
}
async function bnkImpLoad(draw = true) {
  try { BNK.imports = (await api('GET', '/api/office/bank/imports')).items || []; } catch (x) { BNK.imports = []; }
  if (draw) ofcDraw();
}
// 2.114.1 B (#2016): every bank write (match, unmatch, their undo/redo, an import taken back / restored) changes the books, the cash
// flow, the key figures and the paid state of invoices: their loaded data goes, each tab loads again when it is opened
const bfbBooksStale = () => {
  if (typeof BK === 'object') { BK.info = null; BK.euer = null; BK.ustva = null; }
  if (typeof RKF === 'object') RKF.data = null;
  if (typeof KPS === 'object') KPS.data = null;
  if (typeof OFD === 'object') OFD.list = null;
};
const bnkReload = () => { BNK.data = null; BNK.imports = BNK.showImp ? BNK.imports : null; BNK.other = null; BNK.cand = null; bfbBooksStale(); ofcDraw(); };
const bnkAmt = v => `${+v > 0 ? '+' : '−'}${ofcMoney(Math.abs(+v))}`;

function bnkHtml() {
  if (BNK.oid !== OFC.info?.org_id) Object.assign(BNK, {oid: OFC.info?.org_id, data: null, imports: null, err: null, other: null, cand: null});  // another office area
  if (!ofcAdmin()) return ofcLockedHtml();  // 2.356.0 D (#3006): why, and the way to hand in receipts
  if (BNK.err) return `<div class="empty">${esc(BNK.err)}</div>`;
  const norc = typeof BNR === 'object' && bnr_route() && BNK.state === 'norc';  // 2.299.0 C (#3192): #office/bank/norc (the reminder task's link)
  if (!norc && (!BNK.data || BNK.q !== 'state=' + BNK.state)) { setTimeout(() => { if (BNK.q !== 'state=' + BNK.state || !BNK.data) bnkLoad(); }, 0); if (!BNK.data) return `<p class="muted lempty">${tr('Loading…')}</p>`; }
  const d = BNK.data || {}, n = d.counts || {};
  const segs = [['open', tr('Open|payment state'), n.open], ['matched', tr('Matched'), n.matched], ['all', tr('All'), null]];
  if (typeof BNR === 'object') segs.splice(1, 0, ['norc', tr('Without receipt'), BNR.data?.counts?.out]);  // 2.299.0 C (#3192)
  const bar = `<div class="ofcbar bnkbar"><button class="btn pri" data-bnk="imp">${ic('upload', 's')}<span>${tr('Import bank statement')}</span></button><span class="spacer"></span>
    <div class="seg" role="group" aria-label="${esc(tr('Show'))}">${segs.map(([k, t, c]) => `<button type="button" data-bnk="state" data-v="${k}" class="${BNK.state === k ? 'on' : ''}" aria-pressed="${BNK.state === k}">${esc(t)}${c ? ` <small>${c}</small>` : ''}</button>`).join('')}</div>
    <button class="btn ghost" data-bnk="imps" aria-expanded="${BNK.showImp}">${ic('list', 's')}<span>${tr('Imports')}</span></button></div>`;
  if (norc) return bar + (BNK.showImp ? bnkImpHtml() : '') + bnr_html();
  const items = d.items || [];
  const list = items.length ? `<ul class="bnklist" role="list">${items.map(bnkRow).join('')}</ul>`
    : `<div class="empty">${ic('bank')}<span>${BNK.state === 'open' && (n.open || 0) + (n.matched || 0) ? tr('Every booking is matched.') : tr('No bookings yet. Import the statement you download from your bank (CSV, CAMT or MT940).')}</span></div>`;
  return bar + (BNK.showImp ? bnkImpHtml() : '') + (typeof brl_sugHtml === 'function' ? brl_sugHtml() : '') + list + `<div class="muted ofchint">${tr('No bank access: only the file you download yourself.')}<div class="shint">${tr('A match with an invoice records a payment; with a receipt it sets its payment day.')}</div></div>`;  // 2.298.0 A2 (#3186): the matching rule behind (i)
}
function bnkRow(t) {
  const inn = +t.amount > 0;
  const head = `<div class="bnkhead"><span class="bnkn"><b>${esc(t.counterpart || t.purpose || tr('Booking'))}</b><small class="muted">${esc([fmtDateLoc(t.day), t.counterpart ? t.purpose : ''].filter(Boolean).join(' · '))}</small></span>
    <span class="bnkamt ${inn ? 'in' : 'out'}">${esc(bnkAmt(t.amount))}</span></div>`;
  let act;
  if (t.match) {
    // 2.355.0 B (#2843): a split names its invoices and the rest of the booking (an overpayment)
    const rest = t.match.rest && +t.match.rest > 0 ? ` · ${tr('overpaid {0}', ofcMoney(t.match.rest))}` : '';
    act = `<div class="bnkacts"><span class="rotag bnkm">${ic('check', 's')} ${esc(tr(BNK_KIND[t.match.kind] || t.match.kind))}${t.match.label ? ` · ${esc(t.match.label)}` : ''}${esc(rest)}</span>${typeof brl_byRule === 'function' ? brl_byRule(t.match) : ''}<span class="spacer"></span>
      ${t.match.kind === 'invoice' ? `<a class="btn sm ghost" href="#office/offers/${t.match.id}">${tr('Open')}</a>` : ''}<button class="btn sm ghost" data-bnk="unmatch" data-id="${t.id}">${ic('undo', 's')}<span>${tr('Undo match')}</span></button></div>`;
  } else {
    const s = (t.suggestions || [])[0];
    const sug = s ? `<div class="bnksug"><span class="bnksn"><small class="muted">${tr('Suggestion')}</small><b>${esc(tr(BNK_KIND[s.kind]))} · ${esc(s.label)}</b><small class="muted">${esc(s.reason)}</small></span>
      <button class="btn sm pri" data-bnk="match" data-id="${t.id}" data-kind="${s.kind}" data-mid="${s.id}">${tr('Assign match')}</button></div>`
      : !inn ? `<p class="muted bnkmiss">${tr('Receipt missing? Upload it in the documents of the office, then match it here.')}</p>` : '';
    act = `${typeof brl_rowHint === 'function' ? brl_rowHint(t) : ''}${sug}<div class="bnkacts"><button class="btn sm" data-bnk="other" data-id="${t.id}" aria-expanded="${BNK.other === t.id}">${ic('search', 's')}<span>${inn ? tr('Other invoice…') : tr('Other receipt…')}</span></button>
      <button class="btn sm ghost" data-bnk="match" data-id="${t.id}" data-kind="private">${tr('Private')}</button><button class="btn sm ghost" data-bnk="match" data-id="${t.id}" data-kind="ignored">${tr('Ignore')}</button><button class="btn sm ghost" data-bnk="match" data-id="${t.id}" data-kind="noreceipt">${tr('No receipt needed')}</button></div>
      ${BNK.other === t.id ? bnkOtherHtml(t) : ''}`;
  }
  return `<li class="bnkrow ${t.match ? 'done' : ''}" data-tx="${t.id}">${head}${act}</li>`;
}
function bnkOtherHtml(t) {
  const c = BNK.cand;
  if (+t.amount > 0 && BNK.split) return bnkSplitHtml(t, c);
  const rows = !c ? `<p class="muted">${tr('Loading…')}</p>` : !c.length ? `<p class="muted">${tr('Nothing found')}</p>`
    : `<ul class="ofclist" role="list">${c.map(x => `<li><button type="button" class="ofcrow" data-bnk="match" data-id="${t.id}" data-kind="${x.kind}" data-mid="${x.id}"><span class="ofcn"><b>${esc(x.label || tr(BNK_KIND[x.kind]))}</b><small class="muted">${esc(fmtDateLoc(x.date))}${x.kind === 'invoice' ? ` · ${x.refund ? tr('refund open') : tr('open')}` : ''}</small></span><span class="rksum">${ofcMoney(x.amount)}</span></button></li>`).join('')}</ul>`;
  const sp = +t.amount > 0 ? `<button type="button" class="btn sm ghost" data-bnk="split" data-id="${t.id}">${tr('Split across invoices…')}</button>` : '';
  return `<div class="bnkother"><input type="search" class="bnkq" data-bnk-q="${t.id}" value="${esc(BNK.candQ)}" placeholder="${esc(+t.amount > 0 ? tr('Number or customer') : tr('Name of the receipt'))}" aria-label="${esc(tr('Search'))}">${rows}${sp}</div>`;
}
// 2.355.0 B (#2843): one booking on several invoices (a collective transfer) or more than the open amount: an amount per
// invoice, the rest of the booking stays visible as overpaid (server: bank.py bnk_parts)
function bnkSplitHtml(t, c) {
  const rows = !c ? `<p class="muted">${tr('Loading…')}</p>` : !c.length ? `<p class="muted">${tr('Nothing found')}</p>`
    : `<ul class="ofclist" role="list">${c.map(x => `<li class="ofcrow"><span class="ofcn"><b>${esc(x.label)}</b><small class="muted">${esc(fmtDateLoc(x.date))} · ${tr('open')} ${ofcMoney(x.amount)}</small></span><input class="numin" inputmode="decimal" maxlength="16" data-bnk-part="${x.id}" data-open="${esc(x.amount)}" value="${esc(BNK.parts?.[x.id] ?? '')}" aria-label="${esc(tr('Amount for {0}', x.label))}" placeholder="${esc(ofcMoney(x.amount))}"></li>`).join('')}</ul>`;
  return `<div class="bnkother"><input type="search" class="bnkq" data-bnk-q="${t.id}" value="${esc(BNK.candQ)}" placeholder="${esc(tr('Number or customer'))}" aria-label="${esc(tr('Search'))}">${rows}
    <div class="bnkacts"><span class="muted" data-bnk-rest="${t.id}" data-amount="${esc(t.amount)}">${esc(bnkSplitRest(t.amount))}</span><span class="spacer"></span><button type="button" class="btn sm ghost" data-bnk="split" data-id="${t.id}">${tr('Cancel')}</button><button type="button" class="btn sm pri" data-bnk="splitgo" data-id="${t.id}">${tr('Assign match')}</button></div></div>`;
}
function bnkSplitRest(amount) {
  const sum = Object.values(BNK.parts || {}).reduce((a, v) => a + (ofcNum(v) || 0), 0);
  return tr('Assigned {0} · rest {1}', ofcMoney(Math.round(sum * 100) / 100), ofcMoney(Math.round((+amount - sum) * 100) / 100));
}
function bnkImpHtml() {
  if (!BNK.imports) { setTimeout(() => bnkImpLoad(), 0); return `<p class="muted">${tr('Loading…')}</p>`; }
  if (!BNK.imports.length) return `<p class="muted bnkimps">${tr('No imports yet.')}</p>`;
  return `<ul class="ofclist bnkimps" role="list">${BNK.imports.map(i => `<li class="ofcrow ${i.undone_at ? 'arch' : ''}"><span class="ofcn"><b>${esc(i.filename || i.fmt.toUpperCase())}</b><small class="muted">${esc([fmtDateLoc(i.created_at.slice(0, 10)), trn('{0} booking', '{0} bookings', i.count), i.dup_count ? trn('{0} already there', '{0} already there', i.dup_count) : '', i.undone_at ? tr('taken back') : ''].filter(Boolean).join(' · '))}</small></span>
    ${i.undone_at ? '' : `<button class="btn sm ghost" data-bnk="impundo" data-id="${i.id}">${tr('Take back|import')}</button>`}</li>`).join('')}</ul>`;
}

// ---- actions (one undo step each)
async function bnkMatch(tid, kind, mid, parts) {
  const req = {kind, ...(mid ? {id: +mid} : {}), ...(parts ? {parts} : {})};  // 2.355.0 B (#2843): parts of a split
  let j;
  try { j = await api('POST', `/api/office/bank/tx/${tid}/match`, req); } catch (x) { toast(x.message || tr('unknown')); return; }
  if (typeof brl_learned === 'function') brl_learned(j);  // 2.299.0 B (#3191): "Always like this?" after the second time
  bnkReload();
  // 2.355.0 B (#2843): a receipt with another amount than the booking is matched, but said (undo right in the toast)
  const msg = j?.amount_differs ? tr('Matched, but the receipt says {0} and the booking {1}', ofcMoney(j.amount_differs.receipt), ofcMoney(j.amount_differs.booking))
    : j?.rule_category ? tr('Matched · category {0} by rule', j.rule_category.category || '') : tr('Matched');
  offerUndo(msg, histAdd({label: tr('Bank booking matched'),
    undo: async () => { await api('POST', `/api/office/bank/tx/${tid}/unmatch`); bnkReload(); },
    redo: async () => { await api('POST', `/api/office/bank/tx/${tid}/match`, req); bnkReload(); }}));
}
async function bnkUnmatch(tid) {
  let j;
  try { j = await api('POST', `/api/office/bank/tx/${tid}/unmatch`); } catch (x) { toast(x.message || tr('unknown')); return; }
  const was = {kind: j.was.kind, ...(j.was.id ? {id: j.was.id} : {})};
  bnkReload();
  offerUndo(tr('Match undone'), histAdd({label: tr('Bank match undone'),
    undo: async () => { await api('POST', `/api/office/bank/tx/${tid}/match`, was); bnkReload(); },
    redo: async () => { await api('POST', `/api/office/bank/tx/${tid}/unmatch`); bnkReload(); }}));
}
async function bnkImpUndo(iid) {
  try { await api('POST', `/api/office/bank/imports/${iid}/undo`); } catch (x) { toast(x.message || tr('unknown')); return; }
  BNK.imports = null; bnkReload();
  offerUndo(tr('Import taken back'), histAdd({label: tr('Import taken back'),
    undo: async () => { await api('POST', `/api/office/bank/imports/${iid}/restore`); BNK.imports = null; bnkReload(); },
    redo: async () => { await api('POST', `/api/office/bank/imports/${iid}/undo`); BNK.imports = null; bnkReload(); }}));
}
async function bnkCand(tid) {
  const q = BNK.candQ;
  try { const j = await api('GET', `/api/office/bank/tx/${tid}/candidates?q=${encodeURIComponent(q)}`); if (BNK.other === tid && BNK.candQ === q) BNK.cand = j.items || []; }
  catch (x) { BNK.cand = []; }
  if (BNK.other === tid) { ofcDraw(); const i = $(`[data-bnk-q="${tid}"]`); if (i && q) { i.focus(); i.setSelectionRange(q.length, q.length); } }
}

// ---- the import: file -> (CSV: columns) -> preview -> take over
// 2.144.1 B (#2446, #2450): the button opens the dialog first: which file to take from the online banking + "Choose files"
// (several files or one ZIP, also dropped onto the dialog). The files go as they are (multipart, field files); the server reads
// UTF-8, else windows-1252, opens a ZIP in memory and merges everything into one preview. after = called once imported (the
// cash flow loads again).
// 2.146.0 C (#2455): the date formats of core/csvimport.DATE_FORMATS (the household import offers the same)
const BNK_DATE_FORMATS = ['DD.MM.YYYY', 'DD.MM.YY', 'YYYY-MM-DD', 'MM/DD/YYYY', 'DD-MM-YYYY', 'YYYYMMDD', 'DD/MM/YYYY'];
const BNK_ACCEPT = '.xml,.csv,.txt,.sta,.mt940,.mt942,.zip,text/csv,text/plain,application/xml,text/xml,application/zip,application/x-zip-compressed';
function bnkPick(after) { return bnkImpModal(null, null, after); }
function bnkHintHtml() {
  return `<ul class="bnk-hint" role="list">
    <li class="ok">${ic('check', 's')}<span>${tr('Recommended: account statement as XML (CAMT.053), booked transactions. Only this brings the account balance along. Several files or one ZIP work too.')}</span></li>
    <li>${ic('info', 's')}<span>${tr('Also works: CSV export (you choose the columns) – the account balance only when the CSV has a balance column.')}</span></li>
    <li>${ic('info', 's')}<span>${tr('Also works: MT940 / MT942 (.sta, .mt940) – with the account balance.')}</span></li>
    <li class="no">${ic('ban', 's')}<span>${tr('Better not: CAMT.052 (day reports – pending transactions are only shown, never imported).')}</span></li></ul>`;
}
// 2.146.0 C (#2469): CAMT.052 read -- pending entries stay out, the booked version comes with a later report
function bnk052Html() {
  return `<p class="shint lhint keep bnk052">${ic('info', 's')} ${tr('These are day reports (CAMT.052). Pending transactions are shown but not imported; a booking that appears in several reports counts once. For the bookkeeping, better export the account statement (CAMT.053).')}</p>`;
}
function bnkImpModal(text, name, after) {  // text + name: one statement read already (as before); without them the start step
  const md = modal(''), card = $('.card', md), st = {p: null, mapping: null, rows: null, account: null};  // 2.124.0 D (#2342): account = the name for a CSV balance
  md.classList.add('ofcdlg', 'bnkdlg');
  let files = typeof text === 'string' ? [new File([text], name || 'statement.txt', {type: 'text/plain'})] : [];
  const label = () => files.length === 1 ? files[0].name : trn('{0} file', '{0} files', files.length);
  const form = mapping => {
    const fd = new FormData();
    for (const f of files) fd.append('files', f, f.name);
    if (mapping) fd.append('mapping', JSON.stringify(mapping));
    if (st.account) fd.append('account', st.account);
    return fd;
  };
  const errEl = () => $('.aerr', md), err = m => { const e = errEl(); if (e) e.textContent = m || ''; };
  const foot = (ok, back) => `<div class="aerr" role="alert"></div><div class="foot">${back ? `<button class="btn" data-bi="back">${tr('Back')}</button>` : ''}<span class="spacer"></span><button class="btn" data-bi="close">${tr('Cancel')}</button>${ok ? `<button class="btn pri" data-bi="next">${esc(ok)}</button>` : ''}</div>`;
  const sel = (id, label, val, opt) => `<div class="row"><label for="${id}">${esc(label)}</label><select id="${id}">${opt ? `<option value="">${tr('none')}</option>` : ''}${st.p.columns.map((c, i) => `<option value="${i}" ${val === i ? 'selected' : ''}>${esc(c || tr('Column {0}', i + 1))}</option>`).join('')}</select></div>`;
  const cols = () => {
    const g = st.mapping || st.p.guess || {}, two = g.amount == null && (g.amount_in != null || g.amount_out != null);  // 2.140.0 B (#2134): + the recognised bank layout
    card.innerHTML = `<h3>${tr('Import bank statement')}</h3><p class="muted">${esc(label())} · ${tr('Which column holds what? Kalmido has guessed; please check.')}</p>${st.p.files > 1 ? `<p class="muted">${tr('The columns apply to every CSV file.')}</p>` : ''}${filesInfo(st.p)}
      ${st.p.guess?.preset_name ? `<p class="shint lhint keep bgpreset">${ic('check', 's')} ${esc(tr('Recognised layout: {0}', st.p.guess.preset_name))}</p>` : ''}
      ${sel('bi-date', tr('Date'), g.date)}
      <div class="row"><label>${tr('Amount')}</label><div class="seg" role="radiogroup" id="bi-am" aria-label="${esc(tr('Amount'))}"><button type="button" role="radio" data-am="one" aria-checked="${!two}" class="${two ? '' : 'on'}">${tr('One column (minus = expense)')}</button><button type="button" role="radio" data-am="two" aria-checked="${two}" class="${two ? 'on' : ''}">${tr('Income and expense apart')}</button></div></div>
      <div class="bi-one" ${two ? 'hidden' : ''}>${sel('bi-amt', tr('Amount'), g.amount)}${sel('bi-sign', tr('Column with S/H (debit/credit), if the bank gives amounts without a minus'), g.sign, true)}</div>
      <div class="bi-two" ${two ? '' : 'hidden'}>${sel('bi-in', tr('Income'), g.amount_in, true)}${sel('bi-out', tr('Expense'), g.amount_out, true)}</div>
      ${sel('bi-title', tr('Purpose'), g.title, true)}${sel('bi-cp', tr('Paid to / from'), g.counterpart, true)}${cfb_mapHtml(st, sel, g)}
      <div class="row"><label for="bi-dec">${tr('Decimal separator')}</label><select id="bi-dec"><option value="," ${g.decimal !== '.' ? 'selected' : ''}>${tr('comma (1.234,56)')}</option><option value="." ${g.decimal === '.' ? 'selected' : ''}>${tr('point (1,234.56)')}</option></select></div>
      <div class="row"><label for="bi-df">${tr('Date format')}</label><select id="bi-df">${BNK_DATE_FORMATS.map(f => `<option ${g.date_format === f ? 'selected' : ''}>${f}</option>`).join('')}</select></div>
      <div class="bgtblw"><table class="bgtbl"><thead><tr>${st.p.columns.map(c => `<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${st.p.sample.map(r => `<tr>${r.map(x => `<td>${esc(x)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>
      ${foot(tr('Preview'))}`;
  };
  const mapOf = () => {
    const n = id => { const v = $(id, md)?.value; return v === '' || v == null ? null : +v; }, two = $('#bi-am [aria-checked="true"]', md)?.dataset.am === 'two';
    st.account = $('#bi-accname', md)?.value.trim() || null;  // 2.124.0 D (#2342): balance + own account column (optional)
    return {date: n('#bi-date'), amount: two ? null : n('#bi-amt'), amount_in: two ? n('#bi-in') : null, amount_out: two ? n('#bi-out') : null, sign: two ? null : n('#bi-sign'), title: n('#bi-title'), counterpart: n('#bi-cp'), decimal: $('#bi-dec', md).value, date_format: $('#bi-df', md).value, balance: n('#bi-bal'), account: n('#bi-acc')};
  };
  const start = () => {
    card.innerHTML = `<h3>${tr('Import bank statement')}</h3><p class="muted">${tr('Which file from your online banking?')}</p>${bnkHintHtml()}
      <div class="bnk-drop" data-bi-drop><button type="button" class="btn pri" data-bi="pick">${ic('upload', 's')}<span>${tr('Choose files')}</span></button><small class="muted">${tr('or drop them here')}</small></div>
      ${foot('')}`;
  };
  const filesInfo = p => {
    const errs = p.file_errors || [], skip = p.skipped_files || [];
    if (!errs.length && !skip.length) return '';
    return `<ul class="bnk-files" role="list">${errs.map(e => `<li class="no">${ic('alert', 's')}<span><b>${esc(e.file)}</b> ${esc(e.error)}</span></li>`).join('')}${skip.length ? `<li>${ic('info', 's')}<span>${esc(tr('Skipped: {0}', skip.join(', ')))}</span></li>` : ''}</ul>`;
  };
  const rowsView = () => {
    const p = st.p, many = (p.files || 1) > 1;
    card.innerHTML = `<h3>${tr('Import bank statement')}</h3><p class="muted">${esc(label())} · ${esc(tr('Import into: {0}', wsName(ofcWs())))/* 2.356.0 B (#2934) */} · ${esc([many && files.length === 1 ? trn('{0} file', '{0} files', p.files) : '', trn('{0} new', '{0} new', p.count), p.dup_count ? trn('{0} already there', '{0} already there', p.dup_count) : '', p.pending_count ? trn('{0} pending', '{0} pending', p.pending_count) : '', p.skipped ? trn('{0} with an error', '{0} with an error', p.skipped) : ''].filter(Boolean).join(' · '))}</p>
      ${p.camt052 ? bnk052Html() : ''}${cfb_prevHtml(p.balances)}${filesInfo(p)}<ul class="ofclist bnkprev" role="list">${p.rows.slice(0, 200).map(r => `<li class="ofcrow ${r.error || r.dup || r.pending ? 'arch' : ''} ${r.pending ? 'pend' : ''}"><span class="ofcn"><b>${esc(r.counterpart || r.purpose || tr('Row {0}', r.n))}</b><small class="muted">${esc([r.day ? fmtDateLoc(r.day) : '', r.error || (r.pending ? tr('pending – not imported') : r.dup ? tr('already there') : r.purpose), many ? r.file : ''].filter(Boolean).join(' · '))}</small></span>${r.amount != null ? `<span class="bnkamt ${+r.amount > 0 ? 'in' : 'out'}">${esc(bnkAmt(r.amount))}</span>` : ''}</li>`).join('')}</ul>
      ${p.rows.length > 200 ? `<p class="muted">${tr('Showing the first 200 rows')}</p>` : ''}${foot(p.count ? trn('Import {0} booking', 'Import {0} bookings', p.count) : '', p.fmt === 'csv')}`;
  };
  const preview = async mapping => {
    try { st.p = await api('POST', '/api/office/bank/import/preview', form(mapping)); }
    catch (x) {
      if (st.p) err(x.message); else if (typeof text === 'string') { md.remove(); toast(x.message || tr('unknown')); }
      else { start(); err(x.message || tr('unknown')); }  // 2.144.1 B (#2446): e.g. MT940 -> the message in the start step
      $$('button[data-bi]', md).forEach(b => { b.disabled = false; }); return;
    }
    if (st.p.columns) cols(); else rowsView();
  };
  const take = fl => {
    files = [...(fl || [])]; if (!files.length) return;
    Object.assign(st, {p: null, mapping: null}); card.innerHTML = botBusy(`<p class="muted">${tr('Loading…')}</p>`); preview(null);  // 2.161.2 (#2611): + the bot at work
  };
  md.addEventListener('click', async e => {
    const am = e.target.closest('#bi-am [data-am]');
    if (am) { for (const x of $$('#bi-am [data-am]', md)) { x.classList.toggle('on', x === am); x.setAttribute('aria-checked', x === am); } $('.bi-one', md).hidden = am.dataset.am === 'two'; $('.bi-two', md).hidden = am.dataset.am !== 'two'; return; }
    const b = e.target.closest('button[data-bi]'); if (!b) return;
    if (b.dataset.bi === 'close') { md.remove(); return; }
    if (b.dataset.bi === 'pick') { const i = document.createElement('input'); i.type = 'file'; i.multiple = true; i.accept = BNK_ACCEPT; i.className = 'bnk-file'; i.hidden = true; i.onchange = () => { take(i.files); i.remove(); }; md.append(i); i.click(); return; }
    if (b.dataset.bi === 'back') { await preview(null); return; }
    if (st.p?.columns) { st.mapping = mapOf(); b.disabled = true; await preview(st.mapping); return; }
    // 2.356.0 B (#2934): the target before the start, in words: the office area of the account(s) + the account (#1940)
    const accts = [...new Set((st.p?.balances || []).map(x => x.account).filter(Boolean))].map(cfb_acct);
    if (!await importTargetConfirm({what: trn('{0} booking', '{0} bookings', st.p?.count || 0), ws: ofcWs(), place: st.account || accts.join(', ') || tr('Bank account')})) return;
    b.disabled = true;
    try {
      const j = await api('POST', '/api/office/bank/import', form(st.mapping)), iid = j.import.id;
      md.remove(); BNK.state = 'open'; BNK.imports = null; bnkReload(); if (after) after();
      offerUndo(trn('{0} booking imported', '{0} bookings imported', j.count) + (j.ruled ? ` · ${trn('{0} marked by rule', '{0} marked by rule', j.ruled)}` : ''), histAdd({label: tr('Bank statement imported'),
        undo: async () => { await api('POST', `/api/office/bank/imports/${iid}/undo`); BNK.imports = null; bnkReload(); },
        redo: async () => { await api('POST', `/api/office/bank/imports/${iid}/restore`); BNK.imports = null; bnkReload(); }}));
    } catch (x) { b.disabled = false; err(x.message); }
  });
  // 2.144.1 B (#2446): files dropped onto the dialog
  md.addEventListener('dragover', e => { if ([...(e.dataTransfer?.types || [])].includes('Files')) { e.preventDefault(); $('[data-bi-drop]', md)?.classList.add('on'); } });
  md.addEventListener('dragleave', e => { if (!md.contains(e.relatedTarget)) $('[data-bi-drop]', md)?.classList.remove('on'); });
  md.addEventListener('drop', e => { if (!e.dataTransfer?.files?.length) return; e.preventDefault(); if (!st.p || !st.p.rows) take(e.dataTransfer.files); });
  if (files.length) { card.innerHTML = botBusy(`<p class="muted">${tr('Loading…')}</p>`); preview(null); } else start();
  md.bnkTake = take;  // the UI tests hand files over here
  return md;
}

let bnkQT = null;
document.addEventListener('input', e => {
  const pi = e.target.closest?.('[data-bnk-part]');
  if (pi) {  // 2.355.0 B (#2843): the rest of a split, live
    (BNK.parts ||= {})[pi.dataset.bnkPart] = pi.value;
    const r = $('[data-bnk-rest]', pi.closest('.bnkother')); if (r) r.textContent = bnkSplitRest(r.dataset.amount);
    return;
  }
  const i = e.target.closest?.('[data-bnk-q]'); if (!i) return;
  BNK.candQ = i.value; clearTimeout(bnkQT); bnkQT = setTimeout(() => bnkCand(+i.dataset.bnkQ), 250);
});
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-bnk]'); if (!b) return;
  const a = b.dataset.bnk, id = +b.dataset.id;
  if (a === 'imp') bnkPick();
  else if (a === 'state') { BNK.state = b.dataset.v; BNK.other = null; ofcDraw(); }
  else if (a === 'imps') { BNK.showImp = !BNK.showImp; ofcDraw(); }
  else if (a === 'impundo') bnkImpUndo(id);
  else if (a === 'match') bnkMatch(id, b.dataset.kind, b.dataset.mid);
  else if (a === 'unmatch') bnkUnmatch(id);
  else if (a === 'other') { BNK.other = BNK.other === id ? null : id; BNK.cand = null; BNK.candQ = ''; BNK.split = false; BNK.parts = {}; ofcDraw(); if (BNK.other) bnkCand(id); }
  else if (a === 'split') { BNK.split = !BNK.split; BNK.parts = {}; ofcDraw(); }  // 2.355.0 B (#2843)
  else if (a === 'splitgo') {
    const parts = Object.entries(BNK.parts || {}).filter(([, v]) => String(v).trim()).map(([k, v]) => ({id: +k, amount: ofcNum(v)}));
    if (!parts.length || parts.some(p => !(p.amount > 0))) { toast(tr('Invalid value: {0}', tr('Amount'))); return; }
    BNK.split = false; BNK.parts = {}; BNK.other = null; bnkMatch(id, 'invoice', null, parts);
  }
  else return;
  e.preventDefault();
});

// ---- 2.124.0 D (#2342): the balance of the statement. CSV: an optional balance column, an optional column with the own IBAN,
// else the account's name (default "Main account"; known names offered). The preview names the closing balance per account.
// Server: kalmido/office/cfbank.py.
const cfb_day = d => fmtDay('year', pd(d));  // always with the year (TT.MM.JJJJ)
const cfb_acct = a => /^[A-Z]{2}\d{2}[A-Z0-9]{8,}$/.test(a || '') ? `${a.slice(0, 4)} … ${a.slice(-4)}` : (a || '');
function cfb_mapHtml(st, sel, g) {
  const known = st.p.accounts || [], v = st.account ?? (known.find(a => !/^[A-Z]{2}\d{2}/.test(a)) || tr('Main account'));
  return `${sel('bi-bal', tr('Balance (optional)'), g.balance, true)}${sel('bi-acc', tr('Own account (IBAN, optional)'), g.account, true)}
      <div class="row"><label for="bi-accname">${tr('Account name for the balance')}</label><input id="bi-accname" maxlength="60" list="bi-accl" autocomplete="off" value="${esc(v)}"><datalist id="bi-accl">${known.map(a => `<option value="${esc(a)}">`).join('')}</datalist></div>`;
}
function cfb_prevHtml(bals) {
  const last = {};
  for (const b of (bals || []).filter(x => x.kind === 'close')) if (!last[b.account] || b.day >= last[b.account].day) last[b.account] = b;
  const ls = Object.values(last);
  if (!ls.length) return '';
  return `<ul class="cfb-prev" role="list">${ls.map(b => `<li>${esc(tr('Account balance according to the bank on {0}: {1}', cfb_day(b.day), ofcMoney(b.amount)))}${ls.length > 1 || /^[A-Z]{2}\d{2}/.test(b.account) ? ` <small class="muted">${esc(cfb_acct(b.account))}</small>` : ''}</li>`).join('')}</ul>`;
}
