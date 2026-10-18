// 2.90.0 B (#1921): bank reconciliation in the office (tab "Bank", admins of the office area only): import a statement
// (CSV export of the bank with a column mapping like the household budget, or CAMT.052 / .053 XML), then match every booking
// with one tap: money in -> an open invoice (a payment is recorded; less than open = partly paid), money out -> a receipt
// (its payment day), or private / ignore. Every step has its undo; an import can be taken back while none of it is matched.
// Server: kalmido/office/bank.py. No bank access.
const BNK = {oid: null, state: 'open', data: null, q: '', err: null, imports: null, showImp: false, other: null, cand: null, candQ: '', busy: false};
OFC_TABS.splice(OFC_TABS.findIndex(t => t[0] === 'settings'), 0, ['bank', 'bank', N_('Bank'), 1, () => bnkHtml(), 'money']);  // admins only; 2.92.1 (#1917): in the menu group Money
const BNK_KIND = {invoice: N_('Invoice'), receipt: N_('Receipt'), private: N_('Private'), ignored: N_('Ignored')};

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
const bnkReload = () => { BNK.data = null; BNK.imports = BNK.showImp ? BNK.imports : null; BNK.other = null; BNK.cand = null; ofcDraw(); };
const bnkAmt = v => `${+v > 0 ? '+' : '−'}${ofcMoney(Math.abs(+v))}`;

function bnkHtml() {
  if (BNK.oid !== OFC.info?.org_id) Object.assign(BNK, {oid: OFC.info?.org_id, data: null, imports: null, err: null, other: null, cand: null});  // another office area
  if (!ofcAdmin()) return `<div class="empty">${tr('Only the admins of the office see the bank reconciliation.')}</div>`;
  if (BNK.err) return `<div class="empty">${esc(BNK.err)}</div>`;
  if (!BNK.data || BNK.q !== 'state=' + BNK.state) { setTimeout(() => { if (BNK.q !== 'state=' + BNK.state || !BNK.data) bnkLoad(); }, 0); if (!BNK.data) return `<p class="muted lempty">${tr('Loading…')}</p>`; }
  const d = BNK.data, n = d.counts || {};
  const segs = [['open', tr('Open'), n.open], ['matched', tr('Matched'), n.matched], ['all', tr('All'), null]];
  const bar = `<div class="ofcbar bnkbar"><button class="btn pri" data-bnk="imp">${ic('upload', 's')}<span>${tr('Import bank statement')}</span></button><span class="spacer"></span>
    <div class="seg" role="group" aria-label="${esc(tr('Show'))}">${segs.map(([k, t, c]) => `<button type="button" data-bnk="state" data-v="${k}" class="${BNK.state === k ? 'on' : ''}" aria-pressed="${BNK.state === k}">${esc(t)}${c ? ` <small>${c}</small>` : ''}</button>`).join('')}</div>
    <button class="btn ghost" data-bnk="imps" aria-expanded="${BNK.showImp}">${ic('list', 's')}<span>${tr('Imports')}</span></button></div>`;
  const items = d.items || [];
  const list = items.length ? `<ul class="bnklist" role="list">${items.map(bnkRow).join('')}</ul>`
    : `<div class="empty">${ic('bank')}<span>${BNK.state === 'open' && (n.open || 0) + (n.matched || 0) ? tr('Every booking is matched.') : tr('No bookings yet. Import the statement you download from your bank (CSV or CAMT).')}</span></div>`;
  return bar + (BNK.showImp ? bnkImpHtml() : '') + list + `<p class="muted ofchint">${tr('No bank access – only the file you download from your bank yourself. A match with an invoice records a payment; with a receipt it sets its payment day.')}</p>`;
}
function bnkRow(t) {
  const inn = +t.amount > 0;
  const head = `<div class="bnkhead"><span class="bnkn"><b>${esc(t.counterpart || t.purpose || tr('Booking'))}</b><small class="muted">${esc([fmtDateLoc(t.day), t.counterpart ? t.purpose : ''].filter(Boolean).join(' · '))}</small></span>
    <span class="bnkamt ${inn ? 'in' : 'out'}">${esc(bnkAmt(t.amount))}</span></div>`;
  let act;
  if (t.match) {
    act = `<div class="bnkacts"><span class="rotag bnkm">${ic('check', 's')} ${esc(tr(BNK_KIND[t.match.kind] || t.match.kind))}${t.match.label ? ` · ${esc(t.match.label)}` : ''}</span><span class="spacer"></span>
      ${t.match.kind === 'invoice' ? `<a class="btn sm ghost" href="#office/offers/${t.match.id}">${tr('Open')}</a>` : ''}<button class="btn sm ghost" data-bnk="unmatch" data-id="${t.id}">${ic('undo', 's')}<span>${tr('Undo match')}</span></button></div>`;
  } else {
    const s = (t.suggestions || [])[0];
    const sug = s ? `<div class="bnksug"><span class="bnksn"><small class="muted">${tr('Suggestion')}</small><b>${esc(tr(BNK_KIND[s.kind]))} · ${esc(s.label)}</b><small class="muted">${esc(s.reason)}</small></span>
      <button class="btn sm pri" data-bnk="match" data-id="${t.id}" data-kind="${s.kind}" data-mid="${s.id}">${tr('Match')}</button></div>`
      : !inn ? `<p class="muted bnkmiss">${tr('Receipt missing? Upload it in the documents of the office, then match it here.')}</p>` : '';
    act = `${sug}<div class="bnkacts"><button class="btn sm" data-bnk="other" data-id="${t.id}" aria-expanded="${BNK.other === t.id}">${ic('search', 's')}<span>${inn ? tr('Other invoice…') : tr('Other receipt…')}</span></button>
      <button class="btn sm ghost" data-bnk="match" data-id="${t.id}" data-kind="private">${tr('Private')}</button><button class="btn sm ghost" data-bnk="match" data-id="${t.id}" data-kind="ignored">${tr('Ignore')}</button></div>
      ${BNK.other === t.id ? bnkOtherHtml(t) : ''}`;
  }
  return `<li class="bnkrow ${t.match ? 'done' : ''}" data-tx="${t.id}">${head}${act}</li>`;
}
function bnkOtherHtml(t) {
  const c = BNK.cand;
  const rows = !c ? `<p class="muted">${tr('Loading…')}</p>` : !c.length ? `<p class="muted">${tr('Nothing found')}</p>`
    : `<ul class="ofclist" role="list">${c.map(x => `<li><button type="button" class="ofcrow" data-bnk="match" data-id="${t.id}" data-kind="${x.kind}" data-mid="${x.id}"><span class="ofcn"><b>${esc(x.label || tr(BNK_KIND[x.kind]))}</b><small class="muted">${esc(fmtDateLoc(x.date))}${x.kind === 'invoice' ? ` · ${tr('open')}` : ''}</small></span><span class="rksum">${ofcMoney(x.amount)}</span></button></li>`).join('')}</ul>`;
  return `<div class="bnkother"><input type="search" class="bnkq" data-bnk-q="${t.id}" value="${esc(BNK.candQ)}" placeholder="${esc(+t.amount > 0 ? tr('Number or customer') : tr('Name of the receipt'))}" aria-label="${esc(tr('Search'))}">${rows}</div>`;
}
function bnkImpHtml() {
  if (!BNK.imports) { setTimeout(() => bnkImpLoad(), 0); return `<p class="muted">${tr('Loading…')}</p>`; }
  if (!BNK.imports.length) return `<p class="muted bnkimps">${tr('No imports yet.')}</p>`;
  return `<ul class="ofclist bnkimps" role="list">${BNK.imports.map(i => `<li class="ofcrow ${i.undone_at ? 'arch' : ''}"><span class="ofcn"><b>${esc(i.filename || i.fmt.toUpperCase())}</b><small class="muted">${esc([fmtDateLoc(i.created_at.slice(0, 10)), trn('{0} booking', '{0} bookings', i.count), i.dup_count ? trn('{0} already there', '{0} already there', i.dup_count) : '', i.undone_at ? tr('taken back') : ''].filter(Boolean).join(' · '))}</small></span>
    ${i.undone_at ? '' : `<button class="btn sm ghost" data-bnk="impundo" data-id="${i.id}">${tr('Take back')}</button>`}</li>`).join('')}</ul>`;
}

// ---- actions (one undo step each)
async function bnkMatch(tid, kind, mid) {
  const req = {kind, ...(mid ? {id: +mid} : {})};
  try { await api('POST', `/api/office/bank/tx/${tid}/match`, req); } catch (x) { toast(x.message || tr('unknown')); return; }
  bnkReload();
  offerUndo(tr('Matched'), histAdd({label: tr('Bank booking matched'),
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
function bnkPick() {
  const i = document.createElement('input'); i.type = 'file'; i.accept = '.csv,.txt,.xml,text/csv,text/plain,application/xml,text/xml';
  i.onchange = () => { if (i.files[0]) bnkRead(i.files[0]); }; i.click();
}
async function bnkRead(f) {
  const rd = enc => new Promise((ok, no) => { const r = new FileReader(); r.onload = () => ok(r.result); r.onerror = () => no(r.error); r.readAsText(f, enc); });
  let text;
  try { text = await f.text(); if (text.includes('�')) text = await rd('windows-1252'); } catch (x) { toast(x.message || tr('unknown')); return; }  // as the budget: UTF-8, else windows-1252
  bnkImpModal(text, f.name);
}
function bnkImpModal(text, name) {
  const md = modal(''), card = $('.card', md), st = {p: null, mapping: null, rows: null};
  md.classList.add('ofcdlg', 'bnkdlg');
  const errEl = () => $('.aerr', md), err = m => { const e = errEl(); if (e) e.textContent = m || ''; };
  const foot = (ok, back) => `<div class="aerr" role="alert"></div><div class="foot">${back ? `<button class="btn" data-bi="back">${tr('Back')}</button>` : ''}<span class="spacer"></span><button class="btn" data-bi="close">${tr('Cancel')}</button>${ok ? `<button class="btn pri" data-bi="next">${esc(ok)}</button>` : ''}</div>`;
  const sel = (id, label, val, opt) => `<div class="row"><label for="${id}">${esc(label)}</label><select id="${id}">${opt ? `<option value="">${tr('none')}</option>` : ''}${st.p.columns.map((c, i) => `<option value="${i}" ${val === i ? 'selected' : ''}>${esc(c || tr('Column {0}', i + 1))}</option>`).join('')}</select></div>`;
  const cols = () => {
    const g = st.mapping || st.p.guess || {}, two = g.amount == null && (g.amount_in != null || g.amount_out != null);
    card.innerHTML = `<h3>${tr('Import bank statement')}</h3><p class="muted">${esc(name)} · ${tr('Which column holds what? Kalmido has guessed; please check.')}</p>
      ${sel('bi-date', tr('Date'), g.date)}
      <div class="row"><label>${tr('Amount')}</label><div class="seg" role="radiogroup" id="bi-am" aria-label="${esc(tr('Amount'))}"><button type="button" role="radio" data-am="one" aria-checked="${!two}" class="${two ? '' : 'on'}">${tr('One column (minus = expense)')}</button><button type="button" role="radio" data-am="two" aria-checked="${two}" class="${two ? 'on' : ''}">${tr('Income and expense apart')}</button></div></div>
      <div class="bi-one" ${two ? 'hidden' : ''}>${sel('bi-amt', tr('Amount'), g.amount)}</div>
      <div class="bi-two" ${two ? '' : 'hidden'}>${sel('bi-in', tr('Income'), g.amount_in, true)}${sel('bi-out', tr('Expense'), g.amount_out, true)}</div>
      ${sel('bi-title', tr('Purpose'), g.title, true)}${sel('bi-cp', tr('Paid to / from'), g.counterpart, true)}
      <div class="row"><label for="bi-dec">${tr('Decimal separator')}</label><select id="bi-dec"><option value="," ${g.decimal !== '.' ? 'selected' : ''}>${tr('comma (1.234,56)')}</option><option value="." ${g.decimal === '.' ? 'selected' : ''}>${tr('point (1,234.56)')}</option></select></div>
      <div class="row"><label for="bi-df">${tr('Date format')}</label><select id="bi-df">${['DD.MM.YYYY', 'DD.MM.YY', 'YYYY-MM-DD', 'MM/DD/YYYY'].map(f => `<option ${g.date_format === f ? 'selected' : ''}>${f}</option>`).join('')}</select></div>
      <div class="bgtblw"><table class="bgtbl"><thead><tr>${st.p.columns.map(c => `<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${st.p.sample.map(r => `<tr>${r.map(x => `<td>${esc(x)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>
      ${foot(tr('Preview'))}`;
  };
  const mapOf = () => {
    const n = id => { const v = $(id, md)?.value; return v === '' || v == null ? null : +v; }, two = $('#bi-am [aria-checked="true"]', md)?.dataset.am === 'two';
    return {date: n('#bi-date'), amount: two ? null : n('#bi-amt'), amount_in: two ? n('#bi-in') : null, amount_out: two ? n('#bi-out') : null, title: n('#bi-title'), counterpart: n('#bi-cp'), decimal: $('#bi-dec', md).value, date_format: $('#bi-df', md).value};
  };
  const rowsView = () => {
    const p = st.p;
    card.innerHTML = `<h3>${tr('Import bank statement')}</h3><p class="muted">${esc(name)} · ${esc([trn('{0} new', '{0} new', p.count), p.dup_count ? trn('{0} already there', '{0} already there', p.dup_count) : '', p.skipped ? trn('{0} with an error', '{0} with an error', p.skipped) : ''].filter(Boolean).join(' · '))}</p>
      <ul class="ofclist bnkprev" role="list">${p.rows.slice(0, 200).map(r => `<li class="ofcrow ${r.error || r.dup ? 'arch' : ''}"><span class="ofcn"><b>${esc(r.counterpart || r.purpose || tr('Row {0}', r.n))}</b><small class="muted">${esc([r.day ? fmtDateLoc(r.day) : '', r.error || (r.dup ? tr('already there') : r.purpose)].filter(Boolean).join(' · '))}</small></span>${r.amount != null ? `<span class="bnkamt ${+r.amount > 0 ? 'in' : 'out'}">${esc(bnkAmt(r.amount))}</span>` : ''}</li>`).join('')}</ul>
      ${p.rows.length > 200 ? `<p class="muted">${tr('Showing the first 200 rows')}</p>` : ''}${foot(p.count ? trn('Import {0} booking', 'Import {0} bookings', p.count) : '', p.fmt === 'csv')}`;
  };
  const preview = async mapping => {
    try { st.p = await api('POST', '/api/office/bank/import/preview', {text, filename: name, ...(mapping ? {mapping} : {})}); }
    catch (x) { if (st.p) err(x.message); else { md.remove(); toast(x.message || tr('unknown')); } $$('button[data-bi]', md).forEach(b => { b.disabled = false; }); return; }
    if (st.p.columns) cols(); else rowsView();
  };
  md.addEventListener('click', async e => {
    const am = e.target.closest('#bi-am [data-am]');
    if (am) { for (const x of $$('#bi-am [data-am]', md)) { x.classList.toggle('on', x === am); x.setAttribute('aria-checked', x === am); } $('.bi-one', md).hidden = am.dataset.am === 'two'; $('.bi-two', md).hidden = am.dataset.am !== 'two'; return; }
    const b = e.target.closest('button[data-bi]'); if (!b) return;
    if (b.dataset.bi === 'close') { md.remove(); return; }
    if (b.dataset.bi === 'back') { await preview(null); return; }
    if (st.p?.columns) { st.mapping = mapOf(); b.disabled = true; await preview(st.mapping); return; }
    b.disabled = true;
    const req = {text, filename: name, ...(st.mapping ? {mapping: st.mapping} : {})};
    try {
      const j = await api('POST', '/api/office/bank/import', req), iid = j.import.id;
      md.remove(); BNK.state = 'open'; BNK.imports = null; bnkReload();
      offerUndo(trn('{0} booking imported', '{0} bookings imported', j.count), histAdd({label: tr('Bank statement imported'),
        undo: async () => { await api('POST', `/api/office/bank/imports/${iid}/undo`); BNK.imports = null; bnkReload(); },
        redo: async () => { await api('POST', `/api/office/bank/imports/${iid}/restore`); BNK.imports = null; bnkReload(); }}));
    } catch (x) { b.disabled = false; err(x.message); }
  });
  card.innerHTML = `<p class="muted">${tr('Loading…')}</p>`;
  preview(null);
  return md;
}

let bnkQT = null;
document.addEventListener('input', e => {
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
  else if (a === 'other') { BNK.other = BNK.other === id ? null : id; BNK.cand = null; BNK.candQ = ''; ofcDraw(); if (BNK.other) bnkCand(id); }
  else return;
  e.preventDefault();
});
