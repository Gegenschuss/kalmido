// @ts-check
// 2.778.0 (#5383): the walk-through of the open credit card positions of a statement (office_cards.js) and of the open bank
// bookings (office_bank.js): one booking after the other (name, date, amount, original currency, "n of m"), its candidates as
// cards with the receipt's preview (office_cand.js), and what can be done with it: take a candidate, search another receipt,
// upload one, "No receipt needed", "Private" (bank: also "Ignore", "Cash box transfer", "Split across invoices…" -- that one
// opens the list's own split view), "Skip". After a step the next open booking comes by itself; "Undo" takes the last step back
// (the step's own way back: the history entry the list's action recorded, undo.js). Mouse / keyboard: 1-3 choose a candidate,
// Enter takes it, the arrows go back and forth. A phone: the candidates one per screen width (swiped sideways), a swipe on the
// booking goes to the next / previous one. Loaded on its first use (lazyload.js LD_CALL wlk_open); no own store, no own route.
const WLK = {md: null, kind: '', sid: null, items: [], i: 0, cands: null, tok: 0, q: '', search: false, sel: 0, last: null, busy: false, taken: new Set(), px: null};
const wlk_top = () => HIST.undo[HIST.undo.length - 1];
const wlk_fine = () => { try { return matchMedia('(pointer: fine)').matches; } catch { return true; } };

async function wlk_open(kind) {
  WLK.md?.remove();
  let rows = [];
  if (kind === 'cc') {
    if (!CC.sheet) return;
    WLK.sid = CC.sid;
    rows = (CC.sheet.lines || []).filter(x => x.state === 'open');
  } else {
    try { rows = (await api('GET', '/api/office/bank/tx?state=open')).items || []; } catch (x) { return; }
  }
  Object.assign(WLK, {kind, items: rows.map(x => ({x, done: ''})), i: 0, cands: null, q: '', search: false, sel: 0, last: null, busy: false, taken: new Set()});
  const md = WLK.md = modal('');
  md.classList.add('ofcdlg', 'wlkdlg');
  const card = /** @type {HTMLElement} */ (md.querySelector('.card'));
  card.tabIndex = -1;
  md.addEventListener('click', wlk_click);
  md.addEventListener('change', wlk_change);
  md.addEventListener('input', wlk_input);
  md.addEventListener('pointerdown', e => { if (e.pointerType !== 'mouse' && /** @type {any} */ (e.target).closest?.('.wlk-tx')) WLK.px = {x: e.clientX, y: e.clientY}; });
  md.addEventListener('pointerup', e => {
    const p = WLK.px; WLK.px = null; if (!p) return;
    const dx = e.clientX - p.x, dy = e.clientY - p.y;
    if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy) * 1.5) wlk_go(dx < 0 ? 1 : -1);
  });
  md.addEventListener('pointercancel', () => { WLK.px = null; });
  onRemove(md, () => { if (WLK.md === md) WLK.md = null; });
  wlk_load();
}
const wlk_cur = () => WLK.items[WLK.i];
// the candidates of the shown booking: card position = the documents that fit (or the words searched); bank = its suggestions,
// searching = everything the words find (the list's "Other receipt…")
async function wlk_load() {
  const it = wlk_cur(), tok = ++WLK.tok;
  WLK.cands = null; WLK.sel = 0;
  wlk_draw();
  if (!it || it.done) return;
  let c = [];
  try {
    if (WLK.kind === 'cc') c = (await api('GET', `/api/office/cards/lines/${it.x.id}/candidates?q=${encodeURIComponent(WLK.search ? WLK.q : '')}`)).items || [];
    else if (WLK.search) c = (await api('GET', `/api/office/bank/tx/${it.x.id}/candidates?q=${encodeURIComponent(WLK.q)}`)).items || [];
    else c = (it.x.suggestions || []).filter(s => !(s.kind === 'receipt' && WLK.taken.has(s.id)));  // a receipt taken by a booking before
  } catch (x) { c = []; }
  if (tok !== WLK.tok) return;
  WLK.cands = WLK.kind === 'bnk' ? c.map(s => ({...s, label: s.label || tr(BNK_KIND[s.kind] || 'Receipt')})) : c;
  wlk_draw();
}
function wlk_head(x) {
  if (WLK.kind === 'cc') {
    const sub = [fmtDateLoc(x.day), x.orig_amount ? `${x.orig_amount} ${x.orig_currency}` : '', CC_KIND[x.kind] ? tr(CC_KIND[x.kind]) : ''].filter(Boolean).join(' · ');
    return `<span class="bnkn"><b>${esc(x.merchant)}</b><small class="muted">${esc(sub)}</small></span><span class="bnkamt ${+x.amount < 0 ? 'in' : 'out'}">${esc(ofcMoney(x.amount))}</span>`;
  }
  return `<span class="bnkn"><b>${esc(x.counterpart || x.purpose || tr('Booking'))}</b><small class="muted">${esc([fmtDateLoc(x.day), x.counterpart ? x.purpose : ''].filter(Boolean).join(' · '))}</small></span><span class="bnkamt ${+x.amount > 0 ? 'in' : 'out'}">${esc(bnkAmt(x.amount))}</span>`;
}
function wlk_draw() {
  const md = WLK.md; if (!md) return;
  const card = /** @type {HTMLElement} */ ($('.card', md)), n = WLK.items.length, it = wlk_cur();
  const undo = WLK.last && wlk_top() === WLK.last.e ? `<button type="button" class="btn ghost" data-wlk="undo">${ic('undo', 's')}<span>${tr('Undo')}</span></button>` : '';
  const top = `<div class="wlk-top"><h3>${tr('Go through')}</h3><span class="wlk-n" data-wlk-n>${it ? esc(tr('{0} of {1}', String(WLK.i + 1), String(n))) : ''}</span><span class="spacer"></span>
    <button type="button" class="btn ghost icon" data-wlk="close" aria-label="${esc(tr('Close'))}">${ic('x', 's')}</button></div>`;
  if (!it) {
    card.innerHTML = `${/*html-ok*/ top}<div class="wlk-end"><p>${n ? tr('Every booking has its answer.') : tr('Nothing open here.')}</p></div><div class="foot">${/*html-ok*/ undo}<span class="spacer"></span><button type="button" class="btn pri" data-wlk="close">${tr('Close')}</button></div>`;
    return;
  }
  const x = it.x, bank = WLK.kind === 'bnk', out = !bank || +x.amount < 0, fine = wlk_fine();
  let body;
  if (it.done) body = `<p class="wlk-done"><span class="rotag bnkm">${ic('check', 's')} ${esc(it.done)}</span></p>`;
  else {
    const c = WLK.cands, many = WLK.search;
    const cards = !c ? `${loadingHtml('row')}` : !c.length ? (out ? emptyState({title: tr('No suitable receipt found. Search another one or upload it.'), size: 'row', cls: 'wlk-none'}) : ofcNoHit('', 'row', 'wlk-none'))
      : ocd_row((many ? c : c.slice(0, 3)).map((d, k) => ocd_card(d, {btn: `data-wlk="take" data-k="${k}"`, key: fine && k < 3 ? k + 1 : '', on: k === WLK.sel})).join(''), 'wlk-cands');
    const search = many ? `<input type="search" class="wlk-q" data-wlk-q value="${esc(WLK.q)}" placeholder="${esc(bank && !out ? tr('Number or client') : tr('Search all receipts'))}" aria-label="${esc(tr('Search'))}">` : '';
    const acc = esc(bank ? BNK_ACCEPT_RC() : (typeof BK_ACCEPT === 'string' ? BK_ACCEPT : 'application/pdf,image/*'));
    const acts = [
      `<button type="button" class="btn sm" data-wlk="search" aria-expanded="${esc(String(many))}">${ic('search', 's')}<span>${bank && !out ? tr('Other invoice…') : tr('Search another receipt')}</span></button>`,
      out ? `<label class="btn sm">${ic('upload', 's')}<span>${tr('Upload receipt')}</span><input type="file" data-wlk-up accept="${/*html-ok*/ acc}" hidden></label>` : '',
      `<button type="button" class="btn sm ghost" data-wlk="mark" data-v="noreceipt">${tr('No receipt needed')}</button>`,
      `<button type="button" class="btn sm ghost" data-wlk="mark" data-v="private">${tr('Private')}</button>`,
      bank ? `<button type="button" class="btn sm ghost" data-wlk="mark" data-v="ignored">${tr('Ignore')}</button><button type="button" class="btn sm ghost" data-wlk="mark" data-v="cash">${tr('Cash box transfer')}</button>` : '',
      bank && !out ? `<button type="button" class="btn sm ghost" data-wlk="split">${tr('Split across invoices…')}</button>` : ''].join('');
    body = `${/*html-ok*/ search}${/*html-ok*/ cards}<div class="bnkacts wlk-acts">${/*html-ok*/ acts}</div>`;
  }
  card.innerHTML = `${/*html-ok*/ top}<div class="wlk-tx bnkhead">${/*html-ok*/ wlk_head(x)}</div><div class="wlk-body">${/*html-ok*/ body}</div>
    <div class="foot wlk-foot"><button type="button" class="btn ghost" data-wlk="prev" ${WLK.i ? '' : 'disabled'}>${ic('back', 's')}<span>${tr('Back')}</span></button>${/*html-ok*/ undo}
    ${fine ? `<small class="muted wlk-keys">${tr('1-3 select · Enter takes over · arrows back and forth')}</small>` : ''}<span class="spacer"></span>
    ${!it.done && WLK.cands?.length ? `<button type="button" class="btn pri" data-wlk="take" data-k="${esc(String(WLK.sel))}">${ic('check', 's')}<span>${tr('Take over')}</span></button>` : ''}
    <button type="button" class="btn" data-wlk="skip">${it.done ? tr('Next') : tr('Skip')}${ic('right', 's')}</button></div>`;
  if (!md.contains(document.activeElement) || document.activeElement === document.body) card.focus({preventScroll: true});
}
// the accepted files of a bank receipt upload (as the list "Without receipt", office_banknorc.js)
const BNK_ACCEPT_RC = () => typeof BK_ACCEPT === 'string' ? BK_ACCEPT : 'application/pdf,image/*';
// back / forth by d; after a step: the next open booking (then from the start), none left = the end view
function wlk_go(d) {
  const n = WLK.items.length;
  if (d === 0) {
    const nx = [...WLK.items.keys()].filter(k => !WLK.items[k].done);
    WLK.i = nx.find(k => k > WLK.i) ?? nx[0] ?? n;
  } else WLK.i = Math.max(0, Math.min(n, WLK.i + d));
  WLK.search = false; WLK.q = '';
  wlk_load();
}
// one step through the list's own action; done = its history entry is the new newest one (an error left none)
async function wlk_step(what, fn, taken) {
  if (WLK.busy) return;
  const it = wlk_cur(); if (!it || it.done) return;
  WLK.busy = true;
  const before = wlk_top();
  try { await fn(); } catch (x) { /* the action showed its message */ }
  WLK.busy = false;
  const e = wlk_top();
  if (!e || e === before) { wlk_draw(); return; }
  it.done = what; if (taken) WLK.taken.add(taken);
  WLK.last = {e, i: WLK.i, taken};
  wlk_go(0);
}
async function wlk_undo() {
  const l = WLK.last; if (!l || WLK.busy || wlk_top() !== l.e) return;
  WLK.busy = true;
  await histIdle(); await histStep('undo', 1, [l.e]);  // 2.905.0 (#5255): exactly this step
  WLK.busy = false;
  if (wlk_top() === l.e) { wlk_draw(); return; }  // refused (changed elsewhere): the history said why
  WLK.items[l.i].done = ''; if (l.taken) WLK.taken.delete(l.taken);
  WLK.last = null; WLK.i = l.i; WLK.search = false; WLK.q = '';
  if (WLK.kind === 'bnk') bnkReload();
  wlk_load();
}
function wlk_take(k) {
  const d = WLK.cands?.[k], it = wlk_cur(); if (!d || !it) return;
  const what = tr('Matched') + ' · ' + (d.label || d.title || '');
  if (WLK.kind === 'cc') wlk_step(what, () => ccMatchLine(it.x.id, d.id), d.id);
  else wlk_step(what, () => bnkMatch(it.x.id, d.kind, d.id), d.kind === 'receipt' ? d.id : null);
}
const WLK_MARK = {noreceipt: N_('No receipt needed'), private: N_('Private'), ignored: N_('Ignored'), cash: N_('Cash box transfer')};
function wlk_click(e) {
  const b = /** @type {any} */ (e.target).closest?.('[data-wlk]'); if (!b || b.disabled) return;
  const a = b.dataset.wlk, it = wlk_cur();
  e.preventDefault();
  if (a === 'close') WLK.md?.remove();
  else if (a === 'take') wlk_take(+b.dataset.k);
  else if (a === 'skip') wlk_go(1);
  else if (a === 'prev') wlk_go(-1);
  else if (a === 'undo') wlk_undo();
  else if (a === 'search') { WLK.search = !WLK.search; WLK.q = ''; wlk_load().then(() => /** @type {any} */ ($('[data-wlk-q]', WLK.md))?.focus()); }
  else if (a === 'mark' && it) {
    const v = b.dataset.v, what = tr(WLK_MARK[v]);
    if (WLK.kind === 'cc') wlk_step(what, () => ccMarkLine(it.x.id, v, 'open'));
    else wlk_step(what, () => bnkMatch(it.x.id, v));
  } else if (a === 'split' && it) {  // the list's own split view (office_bank.js), at the booking
    WLK.md?.remove();
    Object.assign(BNK, {state: 'open', other: it.x.id, split: true, parts: {}, cand: null, candQ: ''});
    ofcDraw(); bnkCand(it.x.id);
    requestAnimationFrame(() => $(`.bnkrow[data-tx="${it.x.id}"]`)?.scrollIntoView({block: 'start'}));
  }
}
function wlk_change(e) {
  const t = /** @type {any} */ (e.target), it = wlk_cur();
  if (!t.matches?.('[data-wlk-up]') || !t.files?.length || !it) return;
  const f = t.files[0]; t.value = '';
  wlk_step(tr('Receipt added'), async () => { if (WLK.kind === 'cc') await ccRcUpload(it.x.id, f); else { await bnr_upload(it.x.id, f); bnkReload(); } });
}
// the search of another receipt: the list reloads 250 ms after the last key (core.js debounce, tools/perf_budget.py CLEARTIMEOUT_MAX)
const wlk_qLoad = debounce(async () => { await wlk_load(); const i = /** @type {any} */ ($('[data-wlk-q]', WLK.md)); if (i) { i.focus(); i.setSelectionRange(WLK.q.length, WLK.q.length); } }, 250);
function wlk_input(e) {
  const t = /** @type {any} */ (e.target); if (!t.matches?.('[data-wlk-q]')) return;
  WLK.q = t.value; wlk_qLoad();
}
// the keys while the walk-through is the open dialog on top: 1-3, Enter, the arrows (not while typing in the search field)
document.addEventListener('keydown', e => {
  const md = WLK.md; if (!md || !md.isConnected || [...document.querySelectorAll('.modal')].pop() !== md) return;
  if (e.ctrlKey || e.metaKey || e.altKey || e.isComposing) return;
  const t = /** @type {any} */ (e.target);
  if (t.matches?.('input,textarea,select,[contenteditable="true"]')) return;
  const it = wlk_cur(), n = WLK.cands?.length || 0;
  if (/^[1-3]$/.test(e.key) && it && !it.done && +e.key <= n) { WLK.sel = +e.key - 1; wlk_draw(); }
  else if (e.key === 'Enter' && it && !it.done && n && !t.closest?.('button,a,label')) wlk_take(WLK.sel);
  else if (e.key === 'ArrowRight') wlk_go(1);
  else if (e.key === 'ArrowLeft') { if (WLK.i) wlk_go(-1); }
  else return;
  e.preventDefault();
});
