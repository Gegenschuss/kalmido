// @ts-check
// 2.444.0 (#3447): credit card statements (Office > Credit cards). Only the total leaves the business account, the positions need
// their receipts: cards (holder, provider, last four digits, business account) -> one PDF per month -> the positions read from it,
// confirmed by a person -> per open position the receipt found (best hit first, matched only by a press), an upload, "No receipt
// needed" or "Private". The bookkeeping sees every card, a holder with an account only their own. Every step has its undo.
// Server: kalmido/office/cards.py, cardlines.py, cardnorc.py (reminder).
const CC = {oid: null, data: null, loading: false, err: null, card: null, stmts: null, sid: null, sheet: null, pick: null, cand: null, q: '', bank: null, rem: null, remLoading: false};
OFC_TABS.splice(OFC_TABS.findIndex(t => t[0] === 'settings'), 0, /** @type {any} */ (['cards', 'card', N_('Credit cards'), 0, () => ccHtml(), 'money']));
const CC_KIND = {fee: N_('Fee'), credit: N_('Money back')};

async function ccLoad() {
  if (CC.loading) return;
  CC.loading = true;
  try { CC.data = await api('GET', '/api/office/cards'); CC.err = null; } catch (x) { CC.err = x.message || tr('unknown'); }
  CC.loading = false;
  ofcDraw();
}
async function ccStmts() { try { CC.stmts = (await api('GET', `/api/office/cards/${CC.card}/statements`)).items || []; } catch (x) { CC.stmts = []; } ofcDraw(); }
async function ccSheet() { try { CC.sheet = await api('GET', `/api/office/cards/statements/${CC.sid}`); } catch (x) { CC.sid = null; CC.sheet = null; } ofcDraw(); }
// a write changes the receipts' payment days too: the bookkeeping's loaded figures go
const ccStale = () => { CC.sheet = null; CC.stmts = null; CC.data = null; CC.pick = null; CC.cand = null; CC.bank = null; if (typeof bfbBooksStale === 'function') bfbBooksStale(); ofcDraw(); };
const ccName = k => `${k.provider_name} ·· ${k.last4}`;
const ccMon = m => typeof bnr_mon === 'function' ? bnr_mon(m) : m;

function ccHtml() {
  if (CC.oid !== OFC.info?.org_id) Object.assign(CC, {oid: OFC.info?.org_id, data: null, err: null, card: null, stmts: null, sid: null, sheet: null, rem: null});
  if (CC.err) return `<div class="empty">${esc(CC.err)}</div>`;
  if (!CC.data) { setTimeout(ccLoad, 0); return `<p class="muted lempty">${tr('Loading…')}</p>`; }
  if (CC.sid) return ccSheetHtml();
  if (CC.card) return ccCardHtml();
  const d = CC.data, items = d.items || [];
  const rows = items.length ? `<ul class="bnklist" role="list">${items.map(k => `<li class="bnkrow"><button type="button" class="ccopen" data-cc="card" data-id="${k.id}"><span class="bnkn"><b>${esc(k.holder || ccName(k))}</b><small class="muted">${esc([ccName(k), k.account && cfb_acct(k.account)].filter(Boolean).join(' · '))}</small></span>
    ${k.open ? `<span class="rotag">${esc(trn('{0} receipt missing', '{0} receipts missing', k.open))}</span>` : ''}${ic('chev', 's')}</button></li>`).join('')}</ul>`
    : `<div class="empty">${ic('card')}<span>${d.manage ? tr('No cards yet. Add a card, then upload its monthly statement as a PDF.') : tr('No card of yours here yet.')}</span></div>`;
  return `<div class="ofcbar">${d.manage && ofcCan('cards', 'edit') ? `<button class="btn pri" data-cc="add">${ic('plus', 's')}<span>${tr('Add card')}</span></button>` : ''}</div>${rows}
    <p class="muted ofchint">${tr('Only the total leaves the business account. Upload the statement and every position gets its receipt.')}</p>`;
}
function ccCardHtml() {
  const k = (CC.data.items || []).find(x => x.id === CC.card);
  if (!k) { CC.card = null; return ccHtml(); }
  if (CC.stmts === null) { setTimeout(ccStmts, 0); return `<p class="muted lempty">${tr('Loading…')}</p>`; }
  const rows = CC.stmts.length ? `<ul class="bnklist" role="list">${CC.stmts.map(s => `<li class="bnkrow"><button type="button" class="ccopen" data-cc="stmt" data-id="${s.id}"><span class="bnkn"><b>${esc(ccMon(s.month))}</b><small class="muted">${esc(s.state === 'draft' ? tr('Waiting for confirmation') : s.open ? trn('{0} receipt missing', '{0} receipts missing', s.open) : tr('Every position has its receipt.'))}</small></span>
    <span class="bnkamt">${ofcMoney(s.total)}</span>${ic('chev', 's')}</button></li>`).join('')}</ul>`
    : `<div class="empty">${ic('file')}<span>${tr('No statement yet. Upload the PDF of a month.')}</span></div>`;
  const edit = CC.data.manage && ofcCan('cards', 'edit');
  return `<div class="ofcbar"><button class="btn ghost" data-cc="back">${ic('back', 's')}<span>${tr('Back')}</span></button>
    <label class="btn pri">${ic('upload', 's')}<span>${tr('Upload statement')}</span><input type="file" data-cc-up="${k.id}" accept="application/pdf,.pdf" hidden></label><span class="spacer"></span>
    ${edit ? `<button class="btn ghost" data-cc="edit" data-id="${k.id}">${tr('Edit')}</button><button class="btn ghost" data-cc="delcard" data-id="${k.id}">${tr('Delete')}</button>` : ''}</div>
    <h3 class="ofcgrp">${esc(k.holder)} · ${esc(ccName(k))}</h3>${rows}`;
}
function ccSheetHtml() {
  if (!CC.sheet) { setTimeout(ccSheet, 0); return `<p class="muted lempty">${tr('Loading…')}</p>`; }
  const s = CC.sheet.statement, ls = CC.sheet.lines || [], draft = s.state === 'draft', lock = s.locked;
  const diff = +s.diff !== 0, priv = +s.private !== 0;
  const facts = `<dl class="ccfacts"><div><dt>${tr('Total of the statement')}</dt><dd>${s.total_missing ? esc(tr('Not found')) : ofcMoney(s.total)}${draft && !lock ? ` <button class="btn sm ghost" data-cc="total">${tr('Edit')}</button>` : ''}</dd></div>
    <div><dt>${tr('Sum of the positions')}</dt><dd class="${diff ? 'ccdiff' : ''}">${ofcMoney(s.sum)}</dd></div>
    ${priv ? `<div><dt>${tr('Holder pays back')}</dt><dd>${ofcMoney(s.private)}</dd></div>` : ''}
    ${s.bank ? `<div><dt>${tr('Bank booking')}</dt><dd>${esc(fmtDateLoc(s.bank.day))}</dd></div>` : ''}</dl>`;
  const hint = lock ? `<p class="muted">${tr('This month is locked: nothing can be changed here.')}</p>`
    : draft ? `<p class="muted">${s.reader === 'manual' && !ls.length ? tr('This statement could not be read. Enter its positions by hand.') : tr('Please check the positions. They count once you confirm them.')}</p>` : '';
  const acts = `<a class="btn sm" href="/api/office/cards/statements/${s.id}/file" target="_blank" rel="noopener">${ic('file', 's')}<span>PDF</span></a>
    ${lock ? '' : draft ? `<button class="btn sm" data-cc="addline">${ic('plus', 's')}<span>${tr('Add position')}</span></button><button class="btn sm pri" data-cc="confirm">${ic('check', 's')}<span>${tr('Confirm positions')}</span></button>`
    : `<button class="btn sm ghost" data-cc="reopen">${tr('Take confirmation back')}</button>${CC.data.manage && !s.bank && ofcCan('bank', 'edit', 'pay') ? `<button class="btn sm" data-cc="bank" aria-expanded="${!!CC.bank}">${ic('bank', 's')}<span>${tr('Match bank booking')}</span></button>` : ''}`}
    ${lock ? '' : `<button class="btn sm ghost" data-cc="delstmt">${tr('Delete')}</button>`}`;
  return `<div class="ofcbar"><button class="btn ghost" data-cc="tocard">${ic('back', 's')}<span>${tr('Back')}</span></button><span class="spacer"></span></div>
    <h3 class="ofcgrp">${esc(ccMon(s.month))}</h3>${facts}${hint}${draft && !lock && !ls.length && typeof ccs_html === 'function' ? ccs_html(s, CC.sheet.agent_read) : ''}<div class="bnkacts">${acts}</div>${CC.bank ? ccBankHtml(s) : ''}
    ${ls.length ? `<ul class="bnklist ccl" role="list">${ls.map(x => ccLine(x, s)).join('')}</ul>` : ''}`;
}
function ccBankHtml(s) {
  const rows = CC.bank.length ? `<ul class="ofclist" role="list">${CC.bank.map(t => `<li><button type="button" class="ofcrow" data-cc="banklink" data-id="${t.id}" data-fits="${t.fits ? 1 : 0}"><span class="ofcn"><b>${esc(t.counterpart || t.purpose || tr('Booking'))}</b><small class="muted">${esc(fmtDateLoc(t.day))}${t.fits ? ` · ${esc(tr('same amount'))}` : ''}</small></span><span class="rksum">${esc(bnkAmt(t.amount))}</span></button></li>`).join('')}</ul>` : `<p class="muted">${tr('No open booking found.')}</p>`;
  return `<div class="bnkother" data-stmt="${s.id}">${rows}</div>`;
}
function ccLine(x, s) {
  const sub = [fmtDateLoc(x.day), x.orig_amount ? `${x.orig_amount} ${x.orig_currency}` : '', CC_KIND[x.kind] ? tr(CC_KIND[x.kind]) : ''].filter(Boolean).join(' · ');
  const head = `<div class="bnkhead"><span class="bnkn"><b>${esc(x.merchant)}</b><small class="muted">${esc(sub)}</small></span><span class="bnkamt ${+x.amount < 0 ? 'in' : 'out'}">${ofcMoney(x.amount)}</span></div>`;
  if (s.locked) return `<li class="bnkrow done">${head}</li>`;
  if (s.state === 'draft') return `<li class="bnkrow">${head}<div class="bnkacts"><button class="btn sm ghost" data-cc="editline" data-id="${x.id}">${tr('Edit')}</button><button class="btn sm ghost" data-cc="delline" data-id="${x.id}">${tr('Delete')}</button></div></li>`;
  if (x.state === 'matched') return `<li class="bnkrow done">${head}<div class="bnkacts"><span class="rotag bnkm">${ic('check', 's')} ${esc(x.gone ? tr('The receipt was deleted') : x.receipt || tr('Receipt'))}</span>${x.gone ? '' : `<a class="btn sm ghost" href="#docs/${x.node_id}">${tr('Open')}</a>`}<button class="btn sm ghost" data-cc="unmatch" data-id="${x.id}">${ic('undo', 's')}<span>${tr('Undo match')}</span></button></div></li>`;
  if (x.state !== 'open') return `<li class="bnkrow done">${head}<div class="bnkacts"><span class="rotag">${esc(x.state === 'private' ? tr('Private') : tr('No receipt needed'))}</span><button class="btn sm ghost" data-cc="mark" data-id="${x.id}" data-v="open">${ic('undo', 's')}<span>${tr('Needs a receipt')}</span></button></div></li>`;
  const sg = x.suggestion;
  return `<li class="bnkrow">${head}
    ${sg ? `<div class="bnkacts ccsug"><button class="btn sm pri" data-cc="match" data-id="${x.id}" data-node="${sg.id}">${ic('check', 's')}<span>${esc(tr('Take “{0}”', sg.label || tr('Receipt')))}</span></button><small class="muted">${esc(sg.reason)}</small></div>` : ''}
    <div class="bnkacts"><label class="btn sm">${ic('upload', 's')}<span>${tr('Upload receipt')}</span><input type="file" data-cc-rc="${x.id}" accept="${esc(typeof BK_ACCEPT === 'string' ? BK_ACCEPT : 'application/pdf,image/*')}" hidden></label>
    <button class="btn sm" data-cc="pick" data-id="${x.id}" aria-expanded="${CC.pick === x.id}">${ic('search', 's')}<span>${tr('Choose receipt…')}</span></button>
    <button class="btn sm ghost" data-cc="mark" data-id="${x.id}" data-v="noreceipt">${tr('No receipt needed')}</button><button class="btn sm ghost" data-cc="mark" data-id="${x.id}" data-v="private">${tr('Private')}</button></div>
    ${CC.pick === x.id ? ccPickHtml(x) : ''}</li>`;
}
function ccPickHtml(x) {
  const c = CC.cand;
  const rows = !c ? `<p class="muted">${tr('Loading…')}</p>` : !c.length ? `<p class="muted">${tr('Nothing found')}</p>`
    : `<ul class="ofclist" role="list">${c.map(d => `<li><button type="button" class="ofcrow" data-cc="match" data-id="${x.id}" data-node="${d.id}"><span class="ofcn"><b>${esc(d.label || d.title)}</b><small class="muted">${esc([d.date && fmtDateLoc(d.date), d.reason].filter(Boolean).join(' · '))}</small></span>${d.amount ? `<span class="rksum">${ofcMoney(d.amount)}</span>` : ''}</button></li>`).join('')}</ul>`;
  return `<div class="bnkother"><input type="search" data-cc-q="${x.id}" value="${esc(CC.q)}" placeholder="${esc(tr('Search all receipts'))}" aria-label="${esc(tr('Search all receipts'))}">${rows}</div>`;
}
async function ccCand(lid) {
  try { const j = await api('GET', `/api/office/cards/lines/${lid}/candidates?q=${encodeURIComponent(CC.q)}`); if (CC.pick === lid) CC.cand = j.items || []; } catch (x) { CC.cand = []; }
  if (CC.pick === lid) ofcDraw();
}

// ---- dialogs
function ccCardDlg(k) {
  const d = CC.data, ppl = d.people || [], ac = d.accounts || [];
  const md = ofdDlg(k ? tr('Edit card') : tr('Add card'), `${ofcRowF('cc-h', tr('Holder'), `<select id="cc-h"><option value="">${esc(tr('Other person (name)'))}</option>${ppl.map(p => `<option value="${p.id}" ${k?.holder_id === p.id ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select>`)}
    ${ofcRowF('cc-n', tr('Name'), ofcIn('cc-n', k?.holder_name, {max: 120}), tr('only when the holder has no account here'))}
    ${ofcRowF('cc-p', tr('Provider'), ofcSel('cc-p', k?.provider || 'mastercard', (d.providers || []).map(p => [p.id, p.name])))}
    ${ofcRowF('cc-l', tr('Last four digits'), ofcIn('cc-l', k?.last4, {max: 4, num: true}))}
    ${ofcRowF('cc-a', tr('Business account'), ofcIn('cc-a', k?.account, {max: 120, list: 'cc-al'}) + `<datalist id="cc-al">${ac.map(a => `<option value="${esc(a)}">`).join('')}</datalist>`, tr('the total of the statements leaves this account'))}`, tr('Save'), async m => {
    const v = id => $('#' + id, m).value.trim(), h = v('cc-h');
    const req = {holder_id: h ? +h : null, holder_name: h ? '' : v('cc-n'), provider: v('cc-p'), last4: v('cc-l'), account: v('cc-a')};
    if (k) await api('PATCH', `/api/office/cards/${k.id}`, req); else await api('POST', '/api/office/cards', req);
    ccStale(); return true;
  });
  return md;
}
function ccLineDlg(x) {
  const s = CC.sheet.statement;
  return ofdDlg(x ? tr('Edit position') : tr('Add position'), `<div class="row"><label>${tr('Date')}</label>${dateIn('cl-d', x?.day || s.day, {label: tr('Date'), clear: false})}</div>
    ${ofcRowF('cl-m', tr('Merchant'), ofcIn('cl-m', x?.merchant, {max: 120}))}
    ${ofcRowF('cl-a', tr('Amount'), ofcIn('cl-a', x?.amount, {max: 14}), tr('in the office currency; money back with a minus'))}
    ${ofcRowF('cl-o', tr('Original amount'), ofcIn('cl-o', x?.orig_amount, {max: 14}))}
    ${ofcRowF('cl-c', tr('Original currency'), ofcIn('cl-c', x?.orig_currency, {max: 3}))}
    ${ofcRowF('cl-k', tr('Kind'), ofcSel('cl-k', x?.kind || 'purchase', [['purchase', tr('Purchase')], ['fee', tr('Fee')], ['credit', tr('Money back')]]))}`, tr('Save'), async m => {
    const v = id => $('#' + id, m).value.trim(), n = id => { const t = v(id); if (!t) return null; const r = ofcNum(t); return r == null ? t : String(r); };
    const req = {day: v('cl-d'), merchant: v('cl-m'), amount: n('cl-a'), orig_amount: n('cl-o'), orig_currency: v('cl-c'), kind: v('cl-k')};
    if (x) await api('PATCH', `/api/office/cards/lines/${x.id}`, req); else await api('POST', `/api/office/cards/statements/${s.id}/lines`, req);
    ccStale(); return true;
  });
}

// ---- actions (one undo step each)
async function ccDo(label, doit, undo) {
  try { await doit(); } catch (x) { return false; }
  ccStale();
  offerUndo(label, histAdd({label, undo: async () => { await undo(); ccStale(); }, redo: async () => { await doit(); ccStale(); }}));
  return true;
}
async function ccUpload(cid, file) {
  const fd = new FormData(); fd.append('file', file, file.name || 'statement.pdf');
  let j; try { j = await api('POST', `/api/office/cards/${cid}/statements`, fd); } catch (x) { return; }
  CC.sid = j.statement.id; ccStale();
  if (j.digits_differ) toast(tr('The statement names other digits than this card'));
  else toast(j.read ? (j.total_found ? tr('Statement read: please check the positions') : tr('Statement read, but its total was not found: please enter it')) : tr('This statement could not be read. Enter its positions by hand.'));
}
async function ccRcUpload(lid, file) {
  const fd = new FormData(); fd.append('file', file, file.name || 'receipt.pdf');
  let j; try { j = await api('POST', `/api/office/cards/lines/${lid}/upload`, fd); } catch (x) { return; }
  ccStale();
  const id = j.node_id, fresh = j.fresh;
  offerUndo(tr('Receipt added'), histAdd({label: tr('Card position matched'),
    undo: async () => { await api('POST', `/api/office/cards/lines/${lid}/unmatch`); if (fresh) await api('DELETE', `/api/files/nodes/${id}`); ccStale(); },
    redo: async () => { if (fresh) await api('POST', `/api/files/nodes/${id}/restore`); await api('POST', `/api/office/cards/lines/${lid}/match`, {node_id: id}); ccStale(); }}));
}
async function ccConfirm(sid) {
  const s = CC.sheet.statement;
  let accept = false;
  if (s.total_missing) { toast(tr('Enter the total of the statement first')); return; }
  if (+s.diff !== 0) {
    if (!await askConfirm(tr('The positions do not add up to the total of the statement'), tr('Difference: {0}', ofcMoney(s.diff)), {ok: tr('Confirm positions')})) return;
    accept = true;
  }
  ccDo(tr('Positions confirmed'), () => api('POST', `/api/office/cards/statements/${sid}/confirm`, {accept_diff: accept}), () => api('POST', `/api/office/cards/statements/${sid}/reopen`));
}
async function ccBankLink(tid, fits) {
  const sid = CC.sid;
  let accept = false;
  if (!fits) {
    if (!await askConfirm(tr('The booking does not match the total of the statement'), tr('Match it all the same?'), {ok: tr('Match')})) return;
    accept = true;
  }
  ccDo(tr('Matched'), () => api('POST', `/api/office/bank/tx/${tid}/match`, {kind: 'card', id: sid, accept_diff: accept}), () => api('POST', `/api/office/bank/tx/${tid}/unmatch`));
}
const ccLineOf = id => (CC.sheet?.lines || []).find(x => x.id === id);
document.addEventListener('click', async e => {
  // 2.525.0 (#4281): data-cc="pick" / "send" are the choice cards' too (choicecard.js) - only buttons inside the office view
  // count here (one-meaning guard: data-cc)
  const b = /** @type {any} */ (e.target).closest?.('[data-cc]'); if (!b || !b.closest('.dash.office')) return;
  const a = b.dataset.cc, id = +b.dataset.id, sid = CC.sid;
  e.preventDefault();
  if (a === 'add') ccCardDlg(null);
  else if (a === 'card') { CC.card = id; CC.stmts = null; ofcDraw(); }
  else if (a === 'stmt') { CC.sid = id; CC.sheet = null; ofcDraw(); }
  else if (a === 'back') { CC.card = null; ofcDraw(); }
  else if (a === 'tocard') { CC.sid = null; CC.sheet = null; CC.pick = null; CC.bank = null; CC.stmts = null; ofcDraw(); }
  else if (a === 'edit') ccCardDlg((CC.data.items || []).find(x => x.id === id));
  else if (a === 'delcard') { const ok = await ccDo(tr('Card removed'), () => api('DELETE', `/api/office/cards/${id}`), () => api('POST', `/api/office/cards/${id}/restore`)); if (ok) { CC.card = null; ofcDraw(); } }
  else if (a === 'delstmt') { const ok = await ccDo(tr('Statement removed'), () => api('DELETE', `/api/office/cards/statements/${sid}`), () => api('POST', `/api/office/cards/statements/${sid}/restore`)); if (ok) { CC.sid = null; ofcDraw(); } }
  else if (a === 'confirm') ccConfirm(sid);
  else if (a === 'reopen') ccDo(tr('Confirmation taken back'), () => api('POST', `/api/office/cards/statements/${sid}/reopen`), () => api('POST', `/api/office/cards/statements/${sid}/confirm`, {accept_diff: true}));
  else if (a === 'total') {
    const was = CC.sheet.statement.total, md = ofdDlg(tr('Total of the statement'), ofcRowF('cc-t', tr('Amount'), ofcIn('cc-t', was, {max: 14})), tr('Save'), async m => {
      const t = $('#cc-t', m).value.trim(), r = ofcNum(t);
      await api('PATCH', `/api/office/cards/statements/${sid}`, {total: r == null ? t : String(r)}); ccStale(); return true;
    });
    void md;
  } else if (a === 'addline') ccLineDlg(null);
  else if (a === 'editline') ccLineDlg(ccLineOf(id));
  else if (a === 'delline') {
    const x = ccLineOf(id), req = {day: x.day, merchant: x.merchant, amount: x.amount, orig_amount: x.orig_amount, orig_currency: x.orig_currency, kind: x.kind};
    let cur = id;
    ccDo(tr('Position removed'), () => api('DELETE', `/api/office/cards/lines/${cur}`), async () => { cur = (await api('POST', `/api/office/cards/statements/${sid}/lines`, req)).line.id; });
  } else if (a === 'mark') {
    const was = ccLineOf(id)?.state || 'open', v = b.dataset.v;
    ccDo(tr('Saved'), () => api('PATCH', `/api/office/cards/lines/${id}`, {state: v}), () => api('PATCH', `/api/office/cards/lines/${id}`, {state: was}));
  } else if (a === 'match') {
    const node = +b.dataset.node;
    ccDo(tr('Matched'), () => api('POST', `/api/office/cards/lines/${id}/match`, {node_id: node}), () => api('POST', `/api/office/cards/lines/${id}/unmatch`));
  } else if (a === 'unmatch') {
    const node = ccLineOf(id)?.node_id;
    ccDo(tr('Match undone'), () => api('POST', `/api/office/cards/lines/${id}/unmatch`), () => api('POST', `/api/office/cards/lines/${id}/match`, {node_id: node}));
  } else if (a === 'pick') { CC.pick = CC.pick === id ? null : id; CC.cand = null; CC.q = ''; ofcDraw(); if (CC.pick) ccCand(id); }
  else if (a === 'bank') {
    if (CC.bank) { CC.bank = null; ofcDraw(); return; }
    try { CC.bank = (await api('GET', `/api/office/cards/statements/${sid}/bank`)).items || []; } catch (x) { CC.bank = null; }
    ofcDraw();
  } else if (a === 'banklink') ccBankLink(id, b.dataset.fits === '1');
});
document.addEventListener('change', e => {
  const t = /** @type {any} */ (e.target);
  const up = t.closest?.('[data-cc-up]'); if (up && up.files?.length) { ccUpload(+up.dataset.ccUp, up.files[0]); up.value = ''; return; }
  const rc = t.closest?.('[data-cc-rc]'); if (rc && rc.files?.length) { ccRcUpload(+rc.dataset.ccRc, rc.files[0]); rc.value = ''; return; }
  const q = t.closest?.('[data-cc-q]'); if (q) { CC.q = q.value; CC.cand = null; ofcDraw(); ccCand(+q.dataset.ccQ); }
});

// ---- the reminder (office settings, area Data): off / weekly / monthly; every field saves itself
async function ccn_load() {
  if (CC.remLoading) return;
  CC.remLoading = true;
  try { CC.rem = await api('GET', '/api/office/cards/reminder'); } catch (x) { CC.rem = false; }
  CC.remLoading = false;
  ofcDraw();
}
function ccn_settingsHtml(dis) {
  if (!ofcAdmin()) return '';
  const d = CC.rem;
  if (d === false) return '';
  if (!d) { if (!CC.remLoading) setTimeout(ccn_load, 0); return ''; }
  const ppl = d.people || [], opt = (v, t) => `<option value="${v}" ${d.every === v ? 'selected' : ''}>${esc(t)}</option>`;
  return `<h3 id="ccn-h">${tr('Card positions without a receipt')}</h3>
    ${ofcRowF('ccn-every', tr('Reminder'), `<select id="ccn-every" data-ccn="every" ${dis}>${opt('off', tr('Off'))}${opt('week', tr('Weekly'))}${opt('month', tr('Monthly'))}</select>`, tr('a task for the card holder while positions without a receipt are open; done by itself once they have their receipts'))}
    ${ppl.length > 1 && d.every !== 'off' ? ofcRowF('ccn-user', tr('Cards of people without an account'), `<select id="ccn-user" data-ccn="user" ${dis}>${ppl.map(p => `<option value="${p.id}" ${p.id === (d.user || S.me?.id) ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select>`) : ''}`;
}
document.addEventListener('change', async e => {
  const el = /** @type {any} */ (e.target).closest?.('[data-ccn]'); if (!el) return;
  const k = el.dataset.ccn, v = k === 'user' ? +el.value : el.value, was = CC.rem ? CC.rem[k] : null;
  try { CC.rem = await api('PUT', '/api/office/cards/reminder', {[k]: v}); } catch (x) { ccn_load(); return; }
  ofcDraw();
  if (was != null && was !== v) offerUndo(tr('Saved'), histAdd({label: tr('Reminder changed'),
    undo: async () => { CC.rem = await api('PUT', '/api/office/cards/reminder', {[k]: was}); ofcDraw(); },
    redo: async () => { CC.rem = await api('PUT', '/api/office/cards/reminder', {[k]: v}); ofcDraw(); }}));
});
