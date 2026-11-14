/* Kalmido web client: the household budget (module "budget", part of the area Home): the budget view of a budget list
   (lists.life 'budget'), its dialogs (entry, categories, recurring entries, taking over contracts, CSV import) and the
   card on Home & life. Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// 2.72.0 (#1333): a budget is a list without tasks; sharing it = sharing the list (reading = visible, writing = write
// access). Entries are always positive with a kind ("in" / "out"); plan per category = its monthly limit, else the
// recurring entries due that month; recurring entries are templates, booked by hand ("Booked"). Never visible to agents.
// Server routes: /api/budget (kalmido/life/budget.py). Live: the area "budget" of /api/version (liveparts.js -> bg_live).
const BG = {lid: null, month: null, data: null, home: null, loading: false, done: false, seq: 0, hseq: 0, stale: false, hm: null};  // done: loaded once (no loop without a budget)
const BG_PER = {month: N_('monthly'), quarter: N_('quarterly'), year: N_('yearly')};
const bg_month = (d = new Date()) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
const bg_addMonth = (m, n) => { const [y, mo] = m.split('-').map(Number); return bg_month(new Date(y, mo - 1 + n, 1)); };
const bg_monthName = (m, short) => { const [y, mo] = m.split('-').map(Number); try { return new Intl.DateTimeFormat(LOCALE(), short ? {month: 'short'} : {month: 'long', year: 'numeric'}).format(new Date(y, mo - 1, 1)); } catch { return m; } };
const bg_money = n => fmtMoney(+n || 0);
// "1.234,56", "1234.56", "12,5" -> 1234.56 / 12.5; null when it is no amount
function bg_num(s) {
  let v = String(s ?? '').trim().replace(/\s|€/g, ''); if (!v) return null;
  const n = parseNum(v); return n != null && n > 0 && n <= 10000000 && Math.abs(Math.round(n * 100) - n * 100) < 1e-6 ? n : null;  // 2.263.0 (#2976)
}
const bg_numStr = n => numField(n);  // 2.450.0 (#3770)
const bg_lidOfHash = () => +(/^#budget\/(\d+)/.exec(location.hash)?.[1] || 0) || null;
const bg_monthOfHash = () => /^#budget\/\d+\/(\d{4}-(0[1-9]|1[0-2]))$/.exec(location.hash)?.[1] || null;  // 2.1148.0 (#4895): budget/<list>/<YYYY-MM>
const bg_url = (p = '') => `/api/budget/${BG.lid}${p}`;

// ---- loading
async function bg_load() {
  const seq = ++BG.seq; BG.loading = true;
  try {
    if (!BG.lid || !BG.home) { const h = await api('GET', '/api/budget'); BG.home = h; BG.lid = BG.lid || h.lists[0]?.id || null; }
    BG.month = BG.month || bg_month();
    const j = BG.lid ? await api('GET', `${bg_url()}?month=${BG.month}`) : null;
    if (seq === BG.seq) { BG.data = j; BG.stale = false; if (j) for (const p of OPT) p.put(); }  // 2.651.0 (#5025): own changes still on the way stay on top of the fresh rows (a load the closing dialog started put the old amount back)
  } catch (e) { if (seq === BG.seq) { BG.data = null; if (e.status === 404) { BG.lid = null; BG.home = null; } } }
  if (seq === BG.seq) { BG.loading = false; BG.done = true; }  // 2.607.0 (#4925): an outdated load must not mark a newer budget as loaded
  if (seq === BG.seq && S.route.mod === 'budget') { const el = $('#view'); if (el) keepFocus(el, () => setHtml(el, mg_wrap('budget', viewBudget()))); }
}
async function bg_homeLoad() {
  const seq = ++BG.hseq;
  try { const j = await api('GET', '/api/budget'); if (seq === BG.hseq) BG.home = j; } catch { if (seq === BG.hseq) BG.home = BG.home || {lists: [], month: bg_month(), summary: null}; }
  if (seq === BG.hseq && S.route.mod === 'life' && typeof lifeLoad === 'function') { const el = $('#view'); if (el && LF.data) keepFocus(el, () => setHtml(el, mg_wrap('life', viewLife()))); }
}
// a change in the area "budget" (someone else, another device): the open view loads again; with a dialog open later
function bg_live() {
  if (S.route.mod === 'budget') { if ($('.modal.bgdlg') || lpBusy()) BG.stale = true; else bg_load(); }
  if (S.route.mod === 'life' && feat('budget')) bg_homeLoad();
}
// after an own change
async function bg_after() { BG.home = null; await bg_load(); }
// 2.979.0 (#5667): an undo / redo the server did (undo.js histRedraw): the open budget (or the card on Home & life) comes again, a budget not shown is old (the next view fetches)
histReloader('budget', () => { if (!BG.done && !BG.home) return; BG.home = null; if (S.route.mod === 'budget') return bg_load(); if (S.route.mod === 'life' && feat('budget')) return bg_homeLoad(); BG.stale = true; });
// 2.559.0 (#4660): an own entry shows at once (optWrite): the rows of BG.data change before the answer, the view is drawn
// again; afterwards the totals / month values (the server's) are fetched in the background (bg_load replaces BG.data only on
// its answer, so the rows stay; the card on Home & life refetches by itself)
const bg_draw = () => { if (S.route.mod !== 'budget') return; const el = $('#view'); if (el) keepFocus(el, () => setHtml(el, mg_wrap('budget', viewBudget()))); };
const bg_refresh = () => { bg_load(); bg_homeLoad(); };
const BG_PEND = new Map();  // a new entry still on its way: its provisional (negative) id -> the promise of the real id
// a provisional entry into the shown month (sorted like the server: newest day first); idempotent, returns the way back
const bg_entPut = row => () => {
  const d = BG.data; if (!d || d.list_id !== row.list_id || d.month !== String(row.day).slice(0, 7)) return null;
  if (!d.entries.some(x => x.id === row.id)) { const i = d.entries.findIndex(x => x.day < row.day); d.entries.splice(i < 0 ? d.entries.length : i, 0, row); }
  return () => { if (BG.data) BG.data.entries = BG.data.entries.filter(x => x.id !== row.id); };
};
// an entry out of the shown month (filter, idempotent); the way back puts it at its old place
const bg_entCut = id => () => {
  const d = BG.data, i = d ? d.entries.findIndex(x => x.id === id) : -1; if (i < 0) return null;
  const row = d.entries[i]; d.entries = d.entries.filter(x => x.id !== id);
  return () => { const e = BG.data?.entries; if (e && !e.some(x => x.id === id)) e.splice(Math.min(i, e.length), 0, row); };
};

// ---- the card on Home & life
function bg_homeCard() {
  if (!BG.home) { setTimeout(bg_homeLoad, 0); return `<section class="dcard fcard lcard lc-budget" aria-labelledby="lh-budget"><h2 id="lh-budget">${ic('wallet', 's')}<span>${esc(tr('Budget'))}</span></h2><p class="muted">${tr('Loading…')}</p></section>`; }
  const h = BG.home, l = h.lists[0], s = h.summary;
  let body, acts;
  if (!l) {
    body = `<p class="muted">${tr('What comes in, what goes out, and what is left at the end of the month. Shared with the family if you like.')}</p>`;
    acts = `<button type="button" class="btn sm pri" data-bg="create">${ic('plus', 's')}<span>${tr('Create a budget')}</span></button>`;
  } else {
    const out = s ? +s.ist_out : 0, plan = s ? +s.soll_out : 0, pct = plan > 0 ? Math.min(100, Math.round(out / plan * 100)) : 0;
    body = `<div class="bgcard"><div class="bgcm muted">${esc(bg_monthName(h.month))}</div>
      <div class="bgcrow"><span>${esc(tr('Spent'))}</span><b>${esc(bg_money(out))}</b>${plan > 0 ? `<span class="muted">${esc(tr('of {0} planned', bg_money(plan)))}</span>` : ''}</div>
      ${plan > 0 ? `<div class="bgbar ${out > plan ? 'over' : ''}" role="img" aria-label="${esc(tr('{0} of {1} spent', bg_money(out), bg_money(plan)))}"><i style="width:${pct}%"></i></div>` : ''}
      <div class="bgcrow"><span>${esc(tr('Left over'))}</span><b class="${s && +s.saldo < 0 ? 'bgneg' : ''}">${esc(bg_money(s ? s.saldo : 0))}</b></div></div>`;
    acts = `<a class="btn sm" href="#budget/${l.id}">${ic('wallet', 's')}<span>${tr('Open')}</span></a>`;
  }
  return `<section class="dcard fcard lcard lc-budget" aria-labelledby="lh-budget"><h2 id="lh-budget">${ic('wallet', 's')}<span>${esc(l ? lname(listById(l.id)) || l.name : tr('Budget'))}</span><span class="spacer"></span></h2>${body}<div class="fcfoot">${acts}</div></section>`;
}

// ---- the view
function viewBudget() {
  if (typeof lifeModal !== 'function') { ld_later('life'); return `<div class="bgview"><p class="muted lempty">${tr('Loading…')}</p></div>`; }  // 2.65.0 (#1823): the dialogs use life.js (loaded on demand)
  const hl = bg_lidOfHash(), hm = bg_monthOfHash();
  if (hl && hl !== BG.lid) { BG.lid = hl; BG.data = null; BG.done = false; }
  if (!hm) BG.hm = null;
  else if (hm !== BG.hm) { BG.hm = hm; BG.month = hm; BG.data = null; BG.done = false; }  // 2.1148.0 (#4895): a receipt from Files opens its month (once per address)
  if (BG.stale && !$('.modal.bgdlg')) { BG.stale = false; BG.done = false; }
  if (!BG.done && !BG.loading) setTimeout(bg_load, 0);
  const d = BG.data;
  if (!d && (BG.loading || !BG.done)) return `<div class="bgview"><p class="muted lempty">${tr('Loading…')}</p></div>`;
  if (!d) return `<div class="bgview"><div class="empty nempty eact">${ic('wallet')}<span>${tr('What comes in, what goes out, and what is left at the end of the month. Shared with the family if you like.')}</span><button type="button" class="btn pri" data-bg="create">${ic('plus', 's')} ${tr('Create a budget')}</button></div></div>`;
  const w = d.can_write, t = d.totals, lists = (BG.home?.lists || []);
  const pick = lists.length > 1 ? `<select class="bglist" data-bg-list aria-label="${esc(tr('Budget'))}">${lists.map(l => `<option value="${l.id}" ${l.id === d.list_id ? 'selected' : ''}>${esc(l.name)}</option>`).join('')}</select>` : `<h2 class="bgname">${esc(d.name)}</h2>`;
  // 2.1012.0 (#5690): the shared menu() (popovers.js), opened by the click handler below (data-bg="more")
  const menu = !bg_moreItems(d).length ? '' : `<button type="button" class="iconbtn" data-bg="more" aria-haspopup="menu" aria-label="${esc(tr('More'))}" title="${esc(tr('More'))}">${ic('dots')}</button>`;
  const head = `<div class="bghead">${pick}<span class="spacer"></span>${menu}</div>
    <div class="bgmonth"><button type="button" class="iconbtn" data-bg="prev" aria-label="${esc(tr('Previous month'))}" title="${esc(tr('Previous month'))}">${ic('left')}</button><b class="bgmn" aria-live="polite">${esc(bg_monthName(d.month))}</b><button type="button" class="iconbtn" data-bg="next" aria-label="${esc(tr('Next month'))}" title="${esc(tr('Next month'))}">${ic('right')}</button>${d.month !== bg_month() ? `<button type="button" class="btn sm" data-bg="now">${tr('This month')}</button>` : ''}</div>`;
  const tile = (k, label, ist, soll) => `<div class="bgtile bg-${k}"><small class="muted">${esc(label)}</small><b>${esc(bg_money(ist))}</b>${soll != null ? `<small class="muted">${esc(tr('{0} planned', bg_money(soll)))}</small>` : ''}</div>`;
  const sums = `<div class="bgtiles">${tile('in', tr('Received'), t.ist_in, t.soll_in)}${tile('out', tr('Spent'), t.ist_out, t.soll_out)}<div class="bgtile bg-saldo"><small class="muted">${esc(tr('Left over'))}</small><b class="${+t.saldo < 0 ? 'bgneg' : ''}">${esc(bg_money(t.saldo))}</b><small class="muted">${esc(tr('received minus spent'))}</small></div></div>`;
  const tmax = Math.max(1, ...d.trend.map(x => Math.max(+x.ist_in, +x.ist_out)));
  const trend = d.trend.length ? `<div class="bgtrend" role="img" aria-label="${esc(tr('The last six months'))}">${d.trend.map(x => `<div class="bgtm ${x.month === d.month ? 'on' : ''}" title="${esc(`${bg_monthName(x.month)}: ${tr('Received')} ${bg_money(x.ist_in)}, ${tr('Spent')} ${bg_money(x.ist_out)}`)}"><span class="bgtb"><i class="in" style="height:${Math.round(+x.ist_in / tmax * 100)}%"></i><i class="out" style="height:${Math.round(+x.ist_out / tmax * 100)}%"></i></span><small>${esc(bg_monthName(x.month, true))}</small></div>`).join('')}</div>` : '';
  const catRow = c => {
    const soll = +c.soll || 0, ist = +c.ist || 0, pct = soll > 0 ? Math.min(100, Math.round(ist / soll * 100)) : 0, over = soll > 0 && ist > soll && c.kind === 'out';
    return `<li class="bgcat ${over ? 'over' : ''}"><div class="bgcl"><b>${esc(c.name)}</b><span class="muted">${esc(bg_money(ist))}${soll > 0 ? ' ' + esc(tr('of {0}', bg_money(soll))) : ''}</span></div>${soll > 0 ? `<div class="bgbar ${over ? 'over' : ''}" role="img" aria-label="${esc(tr('{0} of {1}', bg_money(ist), bg_money(soll)))}"><i style="width:${pct}%"></i></div>` : ''}</li>`;
  };
  const cOut = d.cats.filter(c => c.kind === 'out' && (+c.soll || +c.ist)), cIn = d.cats.filter(c => c.kind === 'in' && (+c.soll || +c.ist));
  const none = d.none && (+d.none.ist_out || +d.none.ist_in) ? `<li class="bgcat"><div class="bgcl"><b>${esc(tr('No category'))}</b><span class="muted">${esc([+d.none.ist_out ? '−' + bg_money(d.none.ist_out) : '', +d.none.ist_in ? '+' + bg_money(d.none.ist_in) : ''].filter(Boolean).join(' · '))}</span></div></li>` : '';
  const cats = cOut.length || cIn.length || none ? `<section class="bgsec"><h3>${tr('Categories')}</h3><ul class="bgcats">${cOut.map(catRow).join('')}${cIn.map(catRow).join('')}${none}</ul></section>` : '';
  const catName = id => d.cats.find(c => c.id === id)?.name || '';
  const open = d.open_recurring.length ? `<section class="bgsec bgopen"><h3>${tr('Open this month')}</h3><ul class="bgents">${d.open_recurring.map(o => `<li class="bgent"><span class="bgel"><b>${esc(o.recurring.title)}</b><small class="muted">${esc([catName(o.recurring.cat_id), tr(BG_PER[o.recurring.per]), o.day ? fmtDateLoc(o.day) : ''].filter(Boolean).join(' · '))}</small></span><span class="bgamt ${o.recurring.kind}">${o.recurring.kind === 'in' ? '+' : '−'}${esc(bg_money(o.amount))}</span>${w ? `<button type="button" class="btn sm" data-bg="book" data-id="${o.recurring.id}">${ic('check', 's')}<span>${tr('Booked')}</span></button>` : ''}</li>`).join('')}</ul></section>` : '';
  const days = [...new Set(d.entries.map(e => e.day))];
  const ents = d.entries.length ? days.map(day => `<h4 class="bgday">${esc(fmtDateLoc(day))}</h4><ul class="bgents">${d.entries.filter(e => e.day === day).map(e => `<li><button type="button" class="bgent bgrow" data-bg="entry" data-id="${e.id}"><span class="bgel"><b>${esc(e.title)}</b><small class="muted">${esc([catName(e.cat_id), e.counterpart].filter(Boolean).join(' · '))}</small></span>${e.files?.length ? `<span class="bgclip" title="${esc(trn('{0} receipt', '{0} receipts', e.files.length))}">${ic('clip', 's')}</span>` : ''}<span class="bgamt ${e.kind}">${e.kind === 'in' ? '+' : '−'}${esc(bg_money(e.amount))}</span></button></li>`).join('')}</ul>`).join('')
    : `<p class="muted bgnone">${tr('No entries in this month yet.')}</p>`;
  const add = w ? `<button type="button" class="btn pri bgadd" data-bg="add">${ic('plus', 's')}<span>${tr('Entry')}</span></button>` : `<p class="muted bgro">${ic('eye', 's')} ${tr('You can look at this budget but not change it.')}</p>`;
  const cmp = `<button type="button" class="btn sm bgcmpb" data-bg="compare">${ic('chart', 's')}<span>${tr('Month comparison')}</span></button>`;  // 2.140.0 B (#2134)
  return `<div class="bgview">${head}${sums}${trend}${cmp}${add}${open}${cats}<section class="bgsec"><h3>${tr('Entries')}</h3>${ents}</section></div>`;
}

// ---- dialogs (lifeModal from life.js: data-m="save" / "close")
const bg_modal = (html, save, focus) => { const md = lifeModal(html, save, focus); md.classList.add('bgdlg'); onRemove(md, () => { if (BG.stale && S.route.mod === 'budget') bg_load(); }); return md; };
const bg_kindSeg = (k, id = 'bg-kind') => `<div class="seg bgkind" role="radiogroup" id="${id}" aria-label="${esc(tr('Kind'))}"><button type="button" role="radio" data-kind="out" aria-checked="${k === 'out'}" class="${k === 'out' ? 'on' : ''}">${tr('Expense')}</button><button type="button" role="radio" data-kind="in" aria-checked="${k === 'in'}" class="${k === 'in' ? 'on' : ''}">${tr('Income')}</button></div>`;
const bg_kindOf = (md, id = 'bg-kind') => $(`#${id} [aria-checked="true"]`, md)?.dataset.kind || 'out';
const bg_catOpts = (kind, sel) => `<option value="">${tr('No category')}</option>${(BG.data?.cats || []).filter(c => c.kind === kind).map(c => `<option value="${c.id}" ${c.id === sel ? 'selected' : ''}>${esc(c.name)}</option>`).join('')}`;
function bg_kindWire(md, id, onSwitch) {
  $(`#${id}`, md)?.addEventListener('click', e => {
    const b = e.target.closest('[data-kind]'); if (!b) return;
    for (const x of $$(`#${id} [data-kind]`, md)) { const on = x === b; x.classList.toggle('on', on); x.setAttribute('aria-checked', on); }
    onSwitch?.(b.dataset.kind);
  });
}
const bg_body = e => ({day: e.day, amount: e.amount, kind: e.kind, title: e.title, note: e.note || '', counterpart: e.counterpart || '', cat_id: e.cat_id ?? null, ...(e.recurring_id ? {recurring_id: e.recurring_id} : {}), ...(e.source ? {source: e.source} : {})});  // source: an undo brings a csv / recurring entry back as it was
// one entry: new (e null) or change / delete
// 2.576.0 (#4764): a change goes through the core's dialog helper (objsave.js saveDialog): only the fields changed in the dialog,
// with the version it was opened on; saved elsewhere meanwhile -> the dialog again with the saved entry, the input of the person
// over it and the other's fields marked (cf = that conflict); an open dialog shows the bar "Changed ..." with "Take over"
const BG_FLD = {kind: 'bg-kind', amount: 'bg-amt', day: 'bg-day', title: 'bg-title', cat_id: 'bg-cat', counterpart: 'bg-cp', note: 'bg-note'};
// the server's entry in the dialog's shape (the month view and the single entry write the amount / empty fields differently)
const bg_view = x => ({...x, amount: x.amount == null || x.amount === '' ? null : +x.amount, note: x.note || '', counterpart: x.counterpart || '', cat_id: x.cat_id ?? null});
const bg_field = (md, k) => BG_FLD[k] ? ($('#' + BG_FLD[k], md)?.closest('.row') || null) : null;
function bg_entryModal(e, cf) {
  const d = BG.data, w = d.can_write, kind = e?.kind || 'out';
  const day0 = e?.day || (d.month === bg_month() ? today() : d.month + '-01');
  // 2.809.0: html-ok below - the receipts' names go through esc(), ids are numbers, the rest is tr() / ic() (check_innerhtml's span ran over the dialog)
  const filesHtml = x => !x ? '' : `<div class="row bgfiles"><label>${tr('Receipts')}</label><div class="bgfl">${/*html-ok*/ (x.files || []).map(f => `<span class="bgfile"><a href="/api/budget/files/${f.id}?inline=1" target="_blank" rel="noopener">${ic('clip', 's')}<span>${esc(f.name)}</span></a>${w ? `<button type="button" class="iconbtn" data-bgf-del="${f.id}" aria-label="${esc(tr('Delete {0}', f.name))}" title="${esc(tr('Delete'))}">${ic('x', 's')}</button>` : ''}</span>`).join('')}
    ${w ? `<label class="btn sm bgup">${ic('upload', 's')}<span>${tr('Add a receipt')}</span><input type="file" multiple data-bgf-up hidden></label>` : ''}${!w && !(x.files || []).length ? `<span class="muted">${tr('none')}</span>` : ''}</div></div>`;
  const md = bg_modal(`<h3>${ic('wallet', 's')} ${e ? tr('Edit entry') : tr('New entry')}</h3>
    <div class="row"><label>${tr('Kind')}</label>${bg_kindSeg(kind)}</div>
    <div class="row"><label for="bg-amt">${tr('Amount')}</label><input id="bg-amt" inputmode="decimal" class="numin" autocomplete="off" value="${esc(bg_numStr(e?.amount))}" placeholder="${esc(fmtNum(0, 2, 2))}"></div>
    <div class="row"><label id="bg-dayl">${tr('Date')}</label>${dateIn('bg-day', day0, {label: tr('Date')})}</div>
    <div class="row"><label for="bg-title">${tr('What')}</label><input id="bg-title" maxlength="200" autocomplete="off" value="${esc(e?.title || '')}" placeholder="${esc(tr('e.g. Groceries, rent, salary'))}"></div>
    <div class="row"><label for="bg-cat">${tr('Category')}</label><select id="bg-cat">${bg_catOpts(kind, e?.cat_id)}</select></div>
    <div class="row"><label for="bg-cp">${tr('Paid to / from')}</label><input id="bg-cp" maxlength="200" autocomplete="off" value="${esc(e?.counterpart || '')}" placeholder="${esc(tr('optional'))}"></div>
    <div class="row"><label for="bg-note">${tr('Note')}</label><textarea id="bg-note" rows="2" maxlength="1000" placeholder="${esc(tr('optional'))}">${esc(e?.note || '')}</textarea></div>
    <div class="bgfwrap">${filesHtml(e)}</div>
    ${e && w ? `<div class="row"><span></span><button type="button" class="btn sm danger" data-bg-del>${ic('trash', 's')}<span>${tr('Delete entry')}</span></button></div>` : ''}
    ${w ? lifeFoot(e ? tr('Save') : tr('Add')) : `<div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Close')}</button></div>`}`, async md => {
    const v = id => $(id, md)?.value?.trim() ?? '';
    const amount = bg_num(v('#bg-amt')), title = v('#bg-title'), day = v('#bg-day');
    if (!amount) { $('#bg-amt', md).focus(); throw new Error(tr('Please enter an amount (up to 10,000,000)')); }
    if (!title) { $('#bg-title', md).focus(); throw new Error(tr('Please enter what it was')); }
    if (!day) throw new Error(tr('Please enter the date'));
    const body = form();
    // 2.559.0 (#4660): the dialog closes at once, the row shows before the answer; a refusal takes it back (api() says why)
    md.remove();
    if (!e) {
      const tmp = -Date.now(), lid = BG.lid, row = {id: tmp, list_id: lid, ...body, amount: String(amount), recurring_id: null, source: null, files: [], updated_at: null};
      const req = optWrite(bg_entPut(row), () => api('POST', `/api/budget/${lid}/entries`, body), bg_draw, {mod: true});
      BG_PEND.set(tmp, req.then(r => r.id, () => null));  // a refusal: nothing to open (null), no unhandled rejection
      let r; try { r = await req; } catch { BG_PEND.delete(tmp); return; }
      BG_PEND.delete(tmp);
      const x = BG.data?.entries.find(y => y.id === tmp); if (x) Object.assign(x, r);  // the real id (the undo / an upload need it)
      let cur = r;
      offerUndo(tr('Added: {0}', title), histAdd({label: tr('New entry “{0}”', title), undo: async () => { await api('DELETE', `/api/budget/entries/${cur.id}`); bg_after(); },
        redo: async () => { cur = await api('POST', `/api/budget/${cur.list_id}/entries`, bg_body(cur)); bg_after(); }}));
      bg_draw(); bg_refresh();
      return;
    }
    const before = bg_body(open), id = e.id, url = `/api/budget/entries/${id}`;
    // 2.559.0 (#4660): saved elsewhere in between (409 with the saved entry): the row goes back and the dialog opens again;
    // 2.576.0 (#4764): with the saved entry, the input of the person over it and the other's fields marked (objsave.js)
    if (typeof saveDialog !== 'function') await loadModule('objsave').catch(() => { /* offline without the copy: the whole entry as before */ });
    const o0 = bg_view(open), v0 = open.updated_at;  // before the optimistic row: it changes the very entry object (optSet)
    const req = typeof saveDialog === 'function'
      ? () => saveDialog(url, o0, body, {key: 'entry', base, view: bg_view}).then(j => { if (j?.conflict) throw Object.assign(new Error('conflict'), {cf: j.conflict}); return j; })
      : () => rawFetch('PATCH', url, v0 ? {...body, expect_updated_at: v0} : body);  // 2.269.0 C (#3017)
    let r;
    try { r = await optWrite(optSet(() => BG.data?.entries.find(x => x.id === id), {...body, amount: String(amount)}), req, bg_draw, {mod: true}); }
    catch (x) {
      if (x?.cf) { bg_entryModal({...x.cf.cur, ...x.cf.mine}, x.cf); toast(tr('Changed by someone else in the meantime')); bg_refresh(); return; }
      if (x.message !== 'auth') toast(x.message || tr('Error'));  // rawFetch says nothing itself
      return;
    }
    const x = BG.data?.entries.find(y => y.id === id); if (x && r?.id === id) Object.assign(x, r);  // the new updated_at (the next save's check)
    // 2.566.0 (#4704): undo / redo send only the changed keys against the version the step before left (core.js undoStep):
    // someone else changed the entry since -> "Changed elsewhere, not undone", their change stays
    let ver = r?.updated_at || '';
    const st = (b, from) => undoStep(`/api/budget/entries/${id}`, b, ver, {now: from, label: title, then: j => { ver = j?.updated_at || ver; }}).finally(bg_after);
    histAdd({label: tr('Entry “{0}” changed', title), ...(r?.undo_group ? {srv: true} : {}), undo: () => st(before, body), redo: () => st(body, before)});  // 2.809.0 (#5476)
    toast(tr('Saved')); bg_refresh();
  }, e ? null : '#bg-amt');
  bg_kindWire(md, 'bg-kind', k => { const s = $('#bg-cat', md); s.innerHTML = bg_catOpts(k, +s.value || null); });
  // 2.576.0 (#4764): what the dialog would save now; the entry it builds on (after a conflict: the server's) and the form as it
  // opened (fields typed before the conflict always count as changed)
  function form() {
    const v = id => $(id, md)?.value?.trim() ?? '';
    return {day: v('#bg-day'), amount: bg_num(v('#bg-amt')), kind: bg_kindOf(md), title: v('#bg-title'), note: v('#bg-note'), counterpart: v('#bg-cp'), cat_id: +v('#bg-cat') || null};
  }
  const open = cf ? cf.cur : e;
  const base = e ? (typeof objBase === 'function' ? objBase(form(), cf?.mine) : form()) : null;  // lazy-ok: objsave.js is in once a conflict brings cf
  if (e && w) {
    const again = (cur, theirs, mine) => { md.remove(); bg_entryModal({...cur, ...mine}, {cur, theirs, mine, both: []}); };
    loadModule('objsave').then(() => {
      if (!md.isConnected) return;
      dlgStale(md, `/api/budget/entries/${e.id}`, () => open.updated_at, cur => { const o = bg_view(open), c = bg_view(cur); again(cur, Object.keys(form()).filter(k => !objSame(o[k], c[k])), objDiff(base, form())); });
      if (cf?.theirs.length) objMerge(md, cf, () => {}, {field: k => bg_field(md, k),
        take: keys => again(cf.cur, [], Object.fromEntries(Object.entries(cf.mine || {}).filter(([k]) => !keys.includes(k))))});
    }, () => { /* offline without the copy: saved as before */ });
  }
  if (!w) for (const x of $$('input, select, textarea, .bgkind button', md)) x.disabled = true;  // read access: look only
  if (!e) {
    // new: receipts can be added once it is saved (a hint instead of the upload)
    $('.bgfwrap', md).innerHTML = w ? `<div class="shint lhint keep">${tr('Receipts can be added after saving: open the entry again.')}</div>` : '';
  }
  md.addEventListener('click', async ev => {
    const del = ev.target.closest('[data-bg-del]'), fdel = ev.target.closest('[data-bgf-del]');
    if (del) {
      // 2.567.0 A (#4707): no question any more -- the entry and its receipts wait in the trash, the toast takes them back
      md.remove(); bg_delEntry(e);  // 2.559.0 (#4660): the entry goes at once
    } else if (fdel) {
      const f = (e.files || []).find(x => x.id === +fdel.dataset.bgfDel); if (!f) return;
      if (!await askConfirm(tr('Delete “{0}”?', f.name), tr('The receipt cannot be brought back.'), {ok: tr('Delete'), danger: true})) return;
      try { await api('DELETE', `/api/budget/files/${f.id}`); } catch { return; }
      e.files = e.files.filter(x => x.id !== f.id); $('.bgfwrap', md).innerHTML = filesHtml(e); bg_after();
    }
  });
  md.addEventListener('change', async ev => {
    const inp = ev.target.closest('[data-bgf-up]'); if (!inp || !inp.files.length) return;
    const fd = new FormData(); for (const f of inp.files) fd.append('file', f);
    try { const j = await api('POST', `/api/budget/entries/${e.id}/files`, fd); e.files = [...(e.files || []), ...(j.files || [])].filter((x, i, a) => a.findIndex(y => y.id === x.id) === i); $('.bgfwrap', md).innerHTML = filesHtml(e); bg_after(); }
    catch { /* api() said it */ }
  });
  return md;
}
// 2.559.0 (#4660): the row goes at once, a refusal brings it back (api() says why); the undo after the answer
async function bg_delEntry(e) {
  let r; try { r = await optWrite(bg_entCut(e.id), () => api('DELETE', `/api/budget/entries/${e.id}`), bg_draw, {mod: true}); } catch { return; }
  let cur = r.entry || e;
  // 2.567.0 A (#4707): the entry waits in the trash with its receipts; the undo takes it back out (another device too)
  offerUndo(tr('Deleted: {0}', e.title), histAdd({label: tr('Entry “{0}” deleted', e.title), ...(r.undo_group ? {srv: true} : {}), undo: async () => { cur = r.trash ? await api('POST', `/api/budget/entries/${cur.id}/restore`) : await api('POST', `/api/budget/${cur.list_id}/entries`, bg_body(cur)); bg_after(); },
    redo: async () => { await api('DELETE', `/api/budget/entries/${cur.id}`); bg_after(); }}));
  bg_refresh();
}
// book a recurring entry in the shown month
async function bg_book(rid) {
  const o = BG.data.open_recurring.find(x => x.recurring.id === rid); if (!o) return;
  let r; try { r = await api('POST', `/api/budget/recurring/${rid}/book`, {month: BG.data.month}); } catch { return; }
  let cur = r;
  offerUndo(tr('Booked: {0}', o.recurring.title), histAdd({label: tr('Booked “{0}”', o.recurring.title), undo: async () => { await api('DELETE', `/api/budget/entries/${cur.id}`); bg_after(); },
    redo: async () => { cur = await api('POST', `/api/budget/recurring/${rid}/book`, {month: cur.day.slice(0, 7), day: cur.day}); bg_after(); }}));
  bg_after();
}
// categories: name, kind, monthly limit, order (arrows, 2.456.0 #3837: and the grip); every change at once, each ONE undo step
function bg_catsModal() {
  const lid = BG.lid;
  const rowHtml = (c, i, n) => `<li class="bgcr" data-cid="${c.id}">${rowd_grip('bgc')}<input class="bgcn" data-f="name" value="${esc(c.name)}" maxlength="60" aria-label="${esc(tr('Name'))}">
    <select data-f="kind" aria-label="${esc(tr('Kind'))}"><option value="out" ${c.kind === 'out' ? 'selected' : ''}>${tr('Expense')}</option><option value="in" ${c.kind === 'in' ? 'selected' : ''}>${tr('Income')}</option></select>
    <input class="numin" data-f="limit" inputmode="decimal" value="${esc(bg_numStr(c.limit))}" placeholder="${esc(tr('no limit'))}" aria-label="${esc(tr('Limit per month'))}">
    <span class="bgca">${rowd_arrows(`<button type="button" class="iconbtn" data-cmv="-1" ${i === 0 ? 'disabled' : ''} aria-label="${esc(tr('Move up'))}" title="${esc(tr('Move up'))}">${ic('up', 's')}</button><button type="button" class="iconbtn" data-cmv="1" ${i === n - 1 ? 'disabled' : ''} aria-label="${esc(tr('Move down'))}" title="${esc(tr('Move down'))}">${ic('down', 's')}</button>`)}<button type="button" class="iconbtn danger" data-cdel aria-label="${esc(tr('Delete {0}', c.name))}" title="${esc(tr('Delete'))}">${ic('trash', 's')}</button></span></li>`;
  const cats = () => [...(BG.data?.cats || [])].sort((a, b) => (a.sort ?? 0) - (b.sort ?? 0) || a.id - b.id);
  const listHtml = () => { const cs = cats(); return cs.length ? `<ul class="bgcrs">${cs.map((c, i) => rowHtml(c, i, cs.length)).join('')}</ul>` : `<p class="muted">${tr('No categories yet.')}</p>`; };
  const md = bg_modal(`<h3>${ic('tag', 's')} ${tr('Categories')}</h3>
    <div class="shint lhint keep">${tr('Monthly limit = what you plan to spend in a month. Without a limit the plan is the sum of the recurring entries of the category.')}</div>
    <div class="bgcwrap">${listHtml()}</div>
    <div class="bgcnew"><input id="bg-cnew" maxlength="60" placeholder="${esc(tr('New category'))}" aria-label="${esc(tr('New category'))}"><select id="bg-cnk" aria-label="${esc(tr('Kind'))}"><option value="out">${tr('Expense')}</option><option value="in">${tr('Income')}</option></select><input id="bg-cnl" class="numin" inputmode="decimal" placeholder="${esc(tr('no limit'))}" aria-label="${esc(tr('Limit per month'))}"><button type="button" class="btn sm" data-cadd>${ic('plus', 's')}<span>${tr('Add')}</span></button></div>
    <div class="aerr" role="alert"></div><div class="foot"><span class="spacer"></span><button class="btn pri" data-m="close">${tr('Done')}</button></div>`, async () => {}, '#bg-cnew');
  const redraw = async () => { await bg_load(); const w = $('.bgcwrap', md); if (w) w.innerHTML = listHtml(); };
  const patch = async (id, body, before, label) => {
    const cur = cats().find(x => x.id === id);
    let ver = '';
    try { const j = await rawFetch('PATCH', `/api/budget/cats/${id}`, cur?.updated_at ? {...body, expect_updated_at: cur.updated_at} : body); if (cur) cur.updated_at = j.updated_at; ver = j.updated_at || ''; }  // 2.370.2 (#3088)
    catch (x) { if (x.status === 409 && x.data?.category) { toast(tr('Changed in the meantime')); await redraw(); } throw x; }
    // 2.566.0 (#4704): each way against the version the step before left (core.js undoStep), changed since -> said, kept
    const st = b => undoStep(`/api/budget/cats/${id}`, b, ver, {label, then: j => { ver = j?.updated_at || ver; const x = cats().find(y => y.id === id); if (x && j?.updated_at) x.updated_at = j.updated_at; }}).finally(bg_after);
    histAdd({label, undo: () => st(before), redo: () => st(body)});
  };
  // 2.456.0 (#3837): a category to another place, by the arrows and by dragging: the changed places, ONE undo step
  const moveTo = async (c, to) => {
    const cs = cats(); cs.splice(to, 0, cs.splice(cs.indexOf(c), 1)[0]);
    try { await histGroup(async () => { for (const [n, x] of cs.entries()) if (x.sort !== n) await patch(x.id, {sort: n}, {sort: x.sort ?? null}, tr('Order of the categories')); }, tr('Order of the categories')); } catch (er) { lifeErr(md, er); }
    await redraw();
  };
  rowd_attach(md, {kind: 'bgc', row: '.bgcr', move: (from, to, li) => { const c = cats().find(x => x.id === +li.dataset.cid); return c && moveTo(c, to); }});
  md.addEventListener('change', async ev => {
    const li = ev.target.closest('.bgcr'), f = ev.target.dataset.f; if (!li || !f) return;
    const c = cats().find(x => x.id === +li.dataset.cid); if (!c) return;
    let val = ev.target.value.trim();
    if (f === 'name' && !val) { ev.target.value = c.name; return; }
    if (f === 'limit') { if (val === '') val = null; else { val = bg_num(val); if (!val) { lifeErr(md, {message: tr('Invalid value: {0}', tr('Limit per month'))}); return; } } }
    lifeErr(md, {message: ''});
    try { await patch(c.id, {[f]: val}, {[f]: c[f] ?? null}, tr('Category “{0}” changed', c.name)); } catch (er) { lifeErr(md, er); }
    redraw();
  });
  md.addEventListener('click', async ev => {
    const li = ev.target.closest('.bgcr'), c = li && cats().find(x => x.id === +li.dataset.cid);
    const mv = ev.target.closest('[data-cmv]'), del = ev.target.closest('[data-cdel]'), add = ev.target.closest('[data-cadd]');
    if (mv && c) {
      const cs = cats(), i = cs.indexOf(c), j = i + +mv.dataset.cmv; if (j < 0 || j >= cs.length) return;
      await moveTo(c, j); $(`.bgcr[data-cid="${c.id}"] [data-cmv="${mv.dataset.cmv}"]`, md)?.focus();
    } else if (del && c) {
      if (!await askConfirm(tr('Delete the category “{0}”?', c.name), tr('Its entries stay, without a category.'), {ok: tr('Delete'), danger: true})) return;
      let gone;
      try { gone = await api('DELETE', `/api/budget/cats/${c.id}`); } catch { return; }
      let cur = c;
      // 2.72.0 (#1333): undo re-creates the category and hangs its entries / recurring entries back on it
      // 2.359.2 B (#3049): an entry that could not be hung back is counted: the undo names the category as not fully undone
      const rehang = async (j) => { cur = await api('POST', `/api/budget/${lid}/cats`, {name: c.name, kind: c.kind, limit: c.limit}); let bad = 0;
        for (const id of j?.entry_ids || []) await api('PATCH', `/api/budget/entries/${id}`, {cat_id: cur.id}).catch(() => { bad++; });
        for (const id of j?.recurring_ids || []) await api('PATCH', `/api/budget/recurring/${id}`, {cat_id: cur.id}).catch(() => { bad++; });
        return bad; };
      // 2.567.0 A (#4707): the category waits in the trash; the server hangs its entries back on restore
      offerUndo(tr('Deleted: {0}', c.name), histAdd({label: tr('Category “{0}” deleted', c.name), undo: async () => { if (gone?.trash) { cur = await api('POST', `/api/budget/cats/${cur.id}/restore`); bg_after(); return {}; } const bad = await rehang(gone); bg_after(); return bad ? {skipped: [c.name]} : {}; },
        redo: async () => { gone = await api('DELETE', `/api/budget/cats/${cur.id}`); bg_after(); }}));
      redraw();
    } else if (add) {
      const name = $('#bg-cnew', md).value.trim(), lv = $('#bg-cnl', md).value.trim(), limit = lv ? bg_num(lv) : null;
      if (!name) { $('#bg-cnew', md).focus(); return; }
      if (lv && !limit) { lifeErr(md, {message: tr('Invalid value: {0}', tr('Limit per month'))}); return; }
      let cur; try { cur = await api('POST', `/api/budget/${lid}/cats`, {name, kind: $('#bg-cnk', md).value, ...(limit ? {limit} : {})}); } catch (er) { lifeErr(md, er); return; }
      histAdd({label: tr('New category “{0}”', name), undo: async () => { await api('DELETE', `/api/budget/cats/${cur.id}`); bg_after(); }, redo: async () => { cur = await api('POST', `/api/budget/${lid}/cats`, {name, kind: cur.kind, limit: cur.limit}); bg_after(); }});
      $('#bg-cnew', md).value = ''; $('#bg-cnl', md).value = ''; lifeErr(md, {message: ''});
      await redraw(); $('#bg-cnew', md).focus();
    }
  });
  return md;
}
// the months for start / until (two years back, three ahead)
const bg_monthOpts = (sel, empty) => { const now = bg_month(), out = []; for (let i = -24; i <= 36; i++) out.push(bg_addMonth(now, i)); if (sel && !out.includes(sel)) out.unshift(sel);
  return (empty ? `<option value="">${esc(empty)}</option>` : '') + out.map(m => `<option value="${m}" ${m === sel ? 'selected' : ''}>${esc(bg_monthName(m))}</option>`).join(''); };
// recurring entries: the list, and the form for a new / changed one
async function bg_recModal() {
  const lid = BG.lid; let items;
  try { items = (await api('GET', bg_url('/recurring'))).items; } catch { return; }
  const catName = id => (BG.data?.cats || []).find(c => c.id === id)?.name || '';
  const listHtml = () => items.length ? `<ul class="bgents bgrecs">${items.map(r => `<li class="bgent"><span class="bgel"><b>${esc(r.title)}</b><small class="muted">${esc([tr(BG_PER[r.per]), catName(r.cat_id), tr('from {0}', bg_monthName(r.start)), r.until ? tr('until {0}', bg_monthName(r.until)) : '', r.contract_task_id ? tr('from a contract') : ''].filter(Boolean).join(' · '))}</small>${r.contract_changed ? `<small class="bgchg">${ic('alert', 's')} ${esc(tr('Contract changed: now {0} {1}', bg_money(r.contract?.cost), tr(BG_PER[r.contract?.per] || '')))} <button type="button" class="linkbtn" data-rsync="${r.id}">${tr('Match it')}</button></small>` : ''}</span><span class="bgamt ${r.kind}">${r.kind === 'in' ? '+' : '−'}${esc(bg_money(r.amount))}</span><span class="bgca"><button type="button" class="iconbtn" data-redit="${r.id}" aria-label="${esc(tr('Edit {0}', r.title))}" title="${esc(tr('Edit'))}">${ic('edit', 's')}</button><button type="button" class="iconbtn danger" data-rdel="${r.id}" aria-label="${esc(tr('Delete {0}', r.title))}" title="${esc(tr('Delete'))}">${ic('trash', 's')}</button></span></li>`).join('')}</ul>`
    : `<p class="muted">${tr('Rent, salary, insurance: what comes back every month, quarter or year. Not booked automatically: the month shows it under “Open this month”.')}</p>`;
  const formHtml = r => `<div class="bgrform" data-rid="${r?.id || ''}"><h4>${r ? tr('Edit recurring entry') : tr('New recurring entry')}</h4>
    <div class="row"><label>${tr('Kind')}</label>${bg_kindSeg(r?.kind || 'out', 'bg-rkind')}</div>
    <div class="row"><label for="bg-rt">${tr('What')}</label><input id="bg-rt" maxlength="200" autocomplete="off" value="${esc(r?.title || '')}" placeholder="${esc(tr('e.g. Rent'))}"></div>
    <div class="row"><label for="bg-ra">${tr('Amount')}</label><input id="bg-ra" class="numin" inputmode="decimal" value="${esc(bg_numStr(r?.amount))}" placeholder="${esc(fmtNum(0, 2, 2))}"></div>
    <div class="row"><label for="bg-rper">${tr('How often')}</label><select id="bg-rper">${Object.entries(BG_PER).map(([k, w]) => `<option value="${k}" ${(r?.per || 'month') === k ? 'selected' : ''}>${tr(w)}</option>`).join('')}</select></div>
    <div class="row"><label for="bg-rc">${tr('Category')}</label><select id="bg-rc">${bg_catOpts(r?.kind || 'out', r?.cat_id)}</select></div>
    <div class="row"><label for="bg-rs">${tr('From')}</label><select id="bg-rs">${bg_monthOpts(r?.start || BG.data?.month || bg_month())}</select></div>
    <div class="row"><label for="bg-ru">${tr('Until')}</label><select id="bg-ru">${bg_monthOpts(r?.until || '', tr('open-ended'))}</select></div>
    <div class="row"><span></span><span class="lacts">${r ? `<button type="button" class="btn sm" data-rcancel>${tr('Cancel')}</button>` : ''}<button type="button" class="btn sm pri" data-rsave>${r ? tr('Save') : tr('Add')}</button></span></div></div>`;
  const md = bg_modal(`<h3>${ic('repeat', 's')} ${tr('Recurring entries')}</h3><div class="bgrwrap">${listHtml()}</div><div class="bgrfw">${formHtml(null)}</div>
    <div class="aerr" role="alert"></div><div class="foot"><span class="spacer"></span><button class="btn pri" data-m="close">${tr('Done')}</button></div>`, async () => {}, '#bg-rt');
  // 2.576.0 (#4764): the form of a template that is changed goes through the core's dialog helper (objsave.js saveDialog): only the
  // fields changed in it, with the version it was opened on; saved elsewhere meanwhile -> the form again with the saved template,
  // the input over it and the other's fields marked; while it is open the bar "Changed ..." with "Take over" (rd = that form)
  let rd = null;
  const recForm = () => { const v = id => $(id, md)?.value?.trim() ?? '';
    return {title: v('#bg-rt'), amount: bg_num(v('#bg-ra')), kind: bg_kindOf(md, 'bg-rkind'), cat_id: +v('#bg-rc') || null, per: v('#bg-rper'), start: v('#bg-rs'), until: v('#bg-ru') || null}; };
  const R_FLD = {title: 'bg-rt', amount: 'bg-ra', kind: 'bg-rkind', cat_id: 'bg-rc', per: 'bg-rper', start: 'bg-rs', until: 'bg-ru'};
  const wireForm = () => bg_kindWire(md, 'bg-rkind', k => { const s = $('#bg-rc', md); s.innerHTML = bg_catOpts(k, +s.value || null); });
  // r = the template to change (null = a new one), cf = a conflict: the form shows cf.cur with cf.mine over it
  const showForm = (r, cf) => {
    rd?.stop?.(); rd = null; md.querySelector('.obj-merge')?.remove(); md.querySelector('.obj-stale')?.remove();
    $('.bgrfw', md).innerHTML = formHtml(r && cf ? {...cf.cur, ...cf.mine} : r); wireForm();
    if (!r || typeof saveDialog !== 'function') return;
    const open = cf ? cf.cur : r, d = rd = {open, base: objBase(recForm(), cf?.mine)};
    const again = (cur, mine, theirs) => { items = items.map(y => y.id === cur.id ? cur : y); $('.bgrwrap', md).innerHTML = listHtml(); showForm(cur, {cur, mine, theirs, both: []}); };
    d.stop = dlgStale(md, `/api/budget/recurring/${r.id}`, () => d.open.updated_at, cur => {
      if (rd !== d) return;
      const o = bg_view(d.open), c = bg_view(cur);
      again(cur, objDiff(d.base, recForm()), Object.keys(recForm()).filter(k => !objSame(o[k], c[k])));
    });
    if (cf?.theirs.length) objMerge(md, cf, () => {}, {field: k => R_FLD[k] ? $('#' + R_FLD[k], md)?.closest('.row') || null : null,
      take: keys => again(cf.cur, Object.fromEntries(Object.entries(cf.mine || {}).filter(([k]) => !keys.includes(k))), [])});
  };
  wireForm();
  const refresh = async () => { try { items = (await api('GET', `/api/budget/${lid}/recurring`)).items; } catch { /* keep */ } $('.bgrwrap', md).innerHTML = listHtml(); bg_after(); };
  const keys = ['title', 'amount', 'kind', 'cat_id', 'per', 'start', 'until'], pickR = r => Object.fromEntries(keys.map(k => [k, r[k] ?? null]));
  md.addEventListener('click', async ev => {
    const ed = ev.target.closest('[data-redit]'), del = ev.target.closest('[data-rdel]'), sy = ev.target.closest('[data-rsync]');
    if (ev.target.closest('[data-rcancel]')) { showForm(null); return; }
    if (ed) { if (typeof saveDialog !== 'function') await loadModule('objsave').catch(() => { /* offline without the copy: saved as before */ }); showForm(items.find(x => x.id === +ed.dataset.redit)); $('#bg-rt', md).focus(); return; }
    if (sy) {
      const r = items.find(x => x.id === +sy.dataset.rsync); if (!r) return;
      let ver; try { ver = (await api('PATCH', `/api/budget/recurring/${r.id}`, {sync_contract: true}))?.updated_at || ''; } catch { return; }
      const before = {amount: r.amount, per: r.per}, lbl = tr('“{0}” matched to the contract', r.title), then = j => { ver = j?.updated_at || ver; };
      // 2.566.0 (#4704): against the version the step before left (core.js undoStep), changed since -> said, kept
      offerUndo(tr('Matched to the contract'), histAdd({label: lbl, undo: () => undoStep(`/api/budget/recurring/${r.id}`, before, ver, {label: lbl, then}).finally(bg_after), redo: () => undoStep(`/api/budget/recurring/${r.id}`, {sync_contract: true}, ver, {label: lbl, then}).finally(bg_after)}));
      return refresh();
    }
    if (del) {
      const r = items.find(x => x.id === +del.dataset.rdel); if (!r) return;
      if (!await askConfirm(tr('Delete “{0}”?', r.title), tr('Entries booked from it stay.'), {ok: tr('Delete'), danger: true})) return;
      let gone; try { gone = await api('DELETE', `/api/budget/recurring/${r.id}`); } catch { return; }
      let cur = r;
      // 2.567.0 A (#4707): the template waits in the trash (contract link, booked entries); the undo takes it back out
      offerUndo(tr('Deleted: {0}', r.title), histAdd({label: tr('Recurring entry “{0}” deleted', r.title), undo: async () => { cur = gone?.trash ? await api('POST', `/api/budget/recurring/${cur.id}/restore`) : await bg_recBack(lid, cur, pickR(cur)); bg_after(); }, redo: async () => { await api('DELETE', `/api/budget/recurring/${cur.id}`); bg_after(); }}));
      return refresh();
    }
    if (ev.target.closest('[data-rsave]')) {
      const f = $('.bgrform', md), rid = +f.dataset.rid || 0, v = id => $(id, md)?.value?.trim() ?? '';
      const amount = bg_num(v('#bg-ra')), title = v('#bg-rt'), d = rd;
      if (!title) { $('#bg-rt', md).focus(); lifeErr(md, {message: tr('Please enter what it was')}); return; }
      if (!amount) { $('#bg-ra', md).focus(); lifeErr(md, {message: tr('Please enter an amount (up to 10,000,000)')}); return; }
      if (v('#bg-ru') && v('#bg-ru') < v('#bg-rs')) { lifeErr(md, {message: tr('“Until” is before “From”')}); return; }
      const body = recForm();
      lifeErr(md, {message: ''});
      try {
        if (rid) {
          const r0 = d?.open || items.find(x => x.id === rid), before = pickR(r0), url = `/api/budget/recurring/${rid}`;
          let ver = '';
          if (d) {  // 2.576.0 (#4764): saved elsewhere meanwhile: the form again with the saved template + the input (objsave.js)
            const o0 = bg_view(r0), j = await saveDialog(url, o0, body, {key: 'item', base: d.base, view: bg_view});
            if (j?.conflict) { const c = j.conflict; items = items.map(y => y.id === c.raw.id ? c.raw : y); $('.bgrwrap', md).innerHTML = listHtml(); showForm(c.cur, c); toast(tr('Changed by someone else in the meantime')); return; }
            if (j === o0) { showForm(null); return; }  // nothing changed: no request, no undo step
            ver = j?.updated_at || '';
          } else ver = (await rawFetch('PATCH', url, r0?.updated_at ? {...body, expect_updated_at: r0.updated_at} : body))?.updated_at || '';  // 2.269.0 C (#3017)
          // 2.566.0 (#4704): only the changed keys, against the version the step before left (core.js undoStep)
          const st = (b, from) => undoStep(`/api/budget/recurring/${rid}`, b, ver, {now: from, label: title, then: j => { ver = j?.updated_at || ver; }}).finally(bg_after);
          histAdd({label: tr('Recurring entry “{0}” changed', title), undo: () => st(before, body), redo: () => st(body, before)});
        } else {
          let cur = await api('POST', `/api/budget/${lid}/recurring`, body);
          histAdd({label: tr('New recurring entry “{0}”', title), undo: async () => { await api('DELETE', `/api/budget/recurring/${cur.id}`); bg_after(); }, redo: async () => { cur = await api('POST', `/api/budget/${lid}/recurring`, body); bg_after(); }});
        }
      } catch (er) { lifeErr(md, er); return; }
      showForm(null); refresh();
    }
  });
  return md;
}
// undo of a deleted recurring entry: one taken over from a contract comes back through the contracts route (keeps its link), then its own values
async function bg_recBack(lid, r, vals) {
  if (r.contract_task_id) {
    try {
      const it = ((await api('POST', `/api/budget/${lid}/contracts`, {task_ids: [r.contract_task_id], ...(r.cat_id ? {cat_id: r.cat_id} : {})})).items || [])[0];
      if (it) return await api('PATCH', `/api/budget/recurring/${it.id}`, vals);
    } catch { /* the contract is gone or no longer visible: without the link */ }
  }
  return api('POST', `/api/budget/${lid}/recurring`, vals);
}
// take over contracts (module Contracts) as recurring entries
async function bg_contractsModal() {
  const lid = BG.lid; let items;
  try { items = (await api('GET', bg_url('/contracts'))).items; } catch { return; }
  const per = p => tr(PERIOD_WORD[p] || BG_PER[p] || '');
  const body = items.length ? `<ul class="bgctr">${items.map(x => `<li><label class="chkl ${x.taken ? 'bgtaken' : ''}"><input type="checkbox" data-ctid="${x.task_id}" ${x.taken ? 'disabled' : x.cost != null ? 'checked' : ''} ${x.cost == null ? 'disabled' : ''}><span class="bgel"><b>${esc(x.name)}</b><small class="muted">${esc([x.provider, x.cost != null ? bg_money(x.cost) + ' ' + per(x.per) : tr('no cost entered'), x.taken ? tr('already added') : ''].filter(Boolean).join(' · '))}</small></span></label></li>`).join('')}</ul>
    <div class="row"><label for="bg-ctc">${tr('Category')}</label><select id="bg-ctc">${bg_catOpts('out', (BG.data?.cats || []).find(c => c.kind === 'out' && /versicher|insur/i.test(c.name))?.id)}</select></div>`
    : `<p class="muted">${tr('No contracts with a cost yet. Add them on Home & life under Contracts.')}</p>`;
  return bg_modal(`<h3>${ic('file', 's')} ${tr('Add from contracts')}</h3>
    <div class="shint lhint keep">${tr('Each contract becomes a recurring entry with its cost. The values are copied: if the contract changes later, the budget shows it and you can match it.')}</div>
    ${body}${items.some(x => !x.taken && x.cost != null) ? lifeFoot(tr('Add')) : `<div class="aerr" role="alert"></div><div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Close')}</button></div>`}`, async md => {
    const ids = $$('[data-ctid]:checked:not(:disabled)', md).map(x => +x.dataset.ctid);
    if (!ids.length) throw new Error(tr('Please select at least one contract'));
    const cat = +$('#bg-ctc', md)?.value || 0, req = {task_ids: ids, ...(cat ? {cat_id: cat} : {})};
    const j = await api('POST', `/api/budget/${lid}/contracts`, req);
    let made = j.items || [];
    offerUndo(trn('{0} contract added', '{0} contracts added', j.created), histAdd({label: tr('Added from contracts'),
      undo: async () => { for (const r of made) await api('DELETE', `/api/budget/recurring/${r.id}`); bg_after(); },
      redo: async () => { made = (await api('POST', `/api/budget/${lid}/contracts`, req)).items || []; bg_after(); }}));
    md.remove(); bg_after();
  });
}

// ---- CSV import: file(s) -> columns -> preview -> commit
// 2.146.0 C (#2455 #2469): several files or one ZIP (multipart, field files, like the office's bank import; the server reads
// UTF-8, else windows-1252, and opens a ZIP in memory), the debit / credit mark (S/H), pending CAMT.052 entries shown apart
// and never taken over, long imports taken over in parts under one import run, and the last runs can be taken back.
const BG_ACCEPT = '.csv,.txt,.xml,.sta,.mt940,.mt942,.zip,text/csv,text/plain,text/xml,application/xml,application/zip,application/x-zip-compressed';
const BG_SHOW = 300, BG_PART = 3000, BG_UPLOAD_MAX = 20 * 1024 * 1024;
const BG_DATE_FORMATS = ['DD.MM.YYYY', 'DD.MM.YY', 'YYYY-MM-DD', 'MM/DD/YYYY', 'DD-MM-YYYY', 'YYYYMMDD', 'DD/MM/YYYY'];  // core/csvimport.DATE_FORMATS
function bg_runsHtml(items) {
  const live = (items || []).filter(x => x.left > 0).slice(0, 5);
  if (!live.length) return '';
  return `<section class="bgsec bgruns"><h4>${tr('Last imports')}</h4><ul class="bgrunl" role="list">${live.map(x => `<li class="bgrun"><span class="bgel"><b>${esc(x.label || x.fmt.toUpperCase())}</b><small class="muted">${esc([x.at ? fmtDateLoc(x.at.slice(0, 10)) : '', trn('{0} entry', '{0} entries', x.left)].filter(Boolean).join(' · '))}</small></span><button type="button" class="btn sm" data-csundo="${esc(x.id)}">${ic('undo', 's')}<span>${tr('Undo this import')}</span></button></li>`).join('')}</ul></section>`;
}
// takes one import run back; entries changed after the import (or with a receipt) are named and kept unless chosen too
async function bg_runUndo(lid, run) {
  let items; try { items = (await api('GET', `/api/budget/${lid}/import/runs`)).items; } catch { return null; }
  const it = items.find(x => x.id === run); if (!it || !it.left) return null;
  let all = false;
  const ok = await askDialog({title: tr('Undo this import?'), danger: true, ok: tr('Undo'),
    html: `<p>${esc(trn('{0} entry of this import will be deleted, with its receipts.', '{0} entries of this import will be deleted, with their receipts.', it.left - it.edited))}</p>${it.edited ? `<p>${esc(trn('{0} entry was changed after the import and stays.', '{0} entries were changed after the import and stay.', it.edited))}</p><label class="chkl"><input type="checkbox" data-csall> ${tr('Delete the changed ones too')}</label>` : ''}`,
    after: md => md.addEventListener('change', e => { if (e.target.matches('[data-csall]')) all = e.target.checked; })});
  if (!ok) return null;
  const j = await api('POST', `/api/budget/${lid}/import/runs/${run}/undo`, {edited: all ? 'delete' : 'keep'});
  toast(trn('{0} entry deleted', '{0} entries deleted', j.deleted) + (j.kept?.length ? ' · ' + trn('{0} changed entry kept: {1}', '{0} changed entries kept: {1}', j.kept.length, j.kept.slice(0, 3).map(e => e.title).join(', ')) : ''));
  await bg_after();
  return j;
}
function bg_csvModal() {
  const lid = BG.lid, st = {files: [], p: null, rows: null, mapping: null};
  const md = bg_modal(`<h3>${ic('upload', 's')} ${tr('Import a CSV file')}</h3><div class="bgcsv"></div><div class="aerr" role="alert"></div><div class="foot bgcfoot"></div>`, async () => {});
  const area = $('.bgcsv', md), foot = $('.bgcfoot', md), err = m => lifeErr(md, {message: m || ''});
  const footHtml = (ok, back) => `${back ? `<button class="btn" data-cs="back">${tr('Back')}</button>` : ''}<span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button>${ok ? `<button class="btn pri" data-cs="next">${esc(ok)}</button>` : ''}`;
  const form = mapping => { const fd = new FormData(); for (const f of st.files) fd.append('files', f, f.name); if (mapping) fd.append('mapping', JSON.stringify(mapping)); return fd; };
  const label = () => st.files.length === 1 ? st.files[0].name : trn('{0} file', '{0} files', st.files.length);
  const step1 = () => {  // 2.140.0 B (#2134): CSV or CAMT; 2.146.0 C (#2455): several files / a ZIP, the last imports
    area.innerHTML = `<div class="shint lhint keep">${ic('lock', 's')} ${tr('No bank access – only the file you download from your bank yourself (CSV export of your account statement).')}</div>
      <label class="btn bgpick">${ic('upload', 's')}<span>${tr('Select files')}</span><input type="file" multiple accept="${BG_ACCEPT}" data-cs-file hidden></label>
      <p class="muted bgfmts">${tr('CSV of any bank, or CAMT (XML) or MT940 like in the office’s bank import. Several files or one ZIP work too.')}</p><div class="bgrunsw"></div>`;
    foot.innerHTML = footHtml(''); err();
    api('GET', `/api/budget/${lid}/import/runs`).then(j => { const w = $('.bgrunsw', md); if (w && !st.p) w.innerHTML = bg_runsHtml(j.items); }).catch(() => {});
  };
  const sel = (id, label, val, opt) => `<div class="row"><label for="${id}">${esc(label)}</label><select id="${id}">${opt ? `<option value="">${tr('none')}</option>` : ''}${st.p.columns.map((c, i) => `<option value="${i}" ${val === i ? 'selected' : ''}>${esc(c || tr('Column {0}', i + 1))}</option>`).join('')}</select></div>`;
  const filesInfo = p => {
    const errs = p.file_errors || [], skip = p.skipped_files || [];
    if (!errs.length && !skip.length) return '';
    return `<ul class="bnk-files" role="list">${errs.map(e => `<li class="no">${ic('alert', 's')}<span><b>${esc(e.file)}</b> ${esc(e.error)}</span></li>`).join('')}${skip.length ? `<li>${ic('info', 's')}<span>${esc(tr('Skipped: {0}', skip.join(', ')))}</span></li>` : ''}</ul>`;
  };
  const step2 = () => {  // 2.140.0 B (#2134): + the recognised bank layout; 2.146.0 C (#2455): + the S/H mark, two date formats
    const g = st.mapping || st.p.guess || {}, two = g.amount == null && (g.amount_in != null || g.amount_out != null);
    area.innerHTML = `<p class="muted">${esc(label())} · ${tr('Which column holds what? Kalmido has guessed; please check.')}</p>${st.p.files > 1 ? `<p class="muted">${tr('The columns apply to every CSV file.')}</p>` : ''}${filesInfo(st.p)}
      ${st.p.guess?.preset_name ? `<p class="shint lhint keep bgpreset">${ic('check', 's')} ${esc(tr('Recognised layout: {0}', st.p.guess.preset_name))}</p>` : ''}
      ${sel('cs-date', tr('Date'), g.date)}
      <div class="row"><label>${tr('Amount')}</label><div class="seg" role="radiogroup" id="cs-am" aria-label="${esc(tr('Amount'))}"><button type="button" role="radio" data-am="one" aria-checked="${!two}" class="${two ? '' : 'on'}">${tr('One column (minus = expense)')}</button><button type="button" role="radio" data-am="two" aria-checked="${two}" class="${two ? 'on' : ''}">${tr('Income and expense apart')}</button></div></div>
      <div class="cs-one" ${two ? 'hidden' : ''}>${sel('cs-amt', tr('Amount'), g.amount)}${sel('cs-sign', tr('Debit / credit mark (S/H, optional)'), g.sign, true)}</div>
      <div class="cs-two" ${two ? '' : 'hidden'}>${sel('cs-in', tr('Income'), g.amount_in, true)}${sel('cs-out', tr('Expense'), g.amount_out, true)}</div>
      ${sel('cs-title', tr('Text'), g.title)}${sel('cs-cp', tr('Paid to / from'), g.counterpart, true)}
      <div class="row"><label for="cs-dec">${tr('Decimal separator')}</label><select id="cs-dec"><option value="," ${g.decimal !== '.' ? 'selected' : ''}>${tr('comma (1.234,56)')}</option><option value="." ${g.decimal === '.' ? 'selected' : ''}>${tr('point (1,234.56)')}</option></select></div>
      <div class="row"><label for="cs-df">${tr('Date format')}</label><select id="cs-df">${BG_DATE_FORMATS.map(f => `<option ${g.date_format === f ? 'selected' : ''}>${f}</option>`).join('')}</select></div>
      <div class="bgtblw"><table class="bgtbl"><thead><tr>${st.p.columns.map(c => `<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${st.p.sample.map(r => `<tr>${r.map(x => `<td>${esc(x)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
    foot.innerHTML = footHtml(tr('Preview'), true); err();
    $('#cs-am', md).addEventListener('click', e => { const b = e.target.closest('[data-am]'); if (!b) return; for (const x of $$('#cs-am [data-am]', md)) { x.classList.toggle('on', x === b); x.setAttribute('aria-checked', x === b); } $('.cs-one', md).hidden = b.dataset.am === 'two'; $('.cs-two', md).hidden = b.dataset.am !== 'two'; });
  };
  const mapOf = () => {
    const n = id => { const v = $(id, md)?.value; return v === '' || v == null ? null : +v; }, two = $('#cs-am [aria-checked="true"]', md)?.dataset.am === 'two';
    return {date: n('#cs-date'), amount: two ? null : n('#cs-amt'), amount_in: two ? n('#cs-in') : null, amount_out: two ? n('#cs-out') : null, sign: two ? null : n('#cs-sign'), title: n('#cs-title'), counterpart: n('#cs-cp'), decimal: $('#cs-dec', md).value, date_format: $('#cs-df', md).value};
  };
  const takeable = r => !r.error && !r.pending;
  const chosen = () => st.rows.map((r, i) => [r, i]).filter(([r, i]) => takeable(r) && (i < BG_SHOW ? $(`[data-csr="${i}"]`, md)?.checked : !r.dup));
  const okLabel = () => trn('Import {0} entry', 'Import {0} entries', chosen().length);
  const step3 = () => {
    const rows = st.rows, p = st.p, recName = id => (BG.data?.open_recurring || []).find(o => o.recurring.id === id)?.recurring.title || '';
    const shown = rows.slice(0, BG_SHOW), pend = rows.filter(r => r.pending && !r.error), many = (p.files || 1) > 1;
    area.innerHTML = `<p class="muted">${esc([trn('{0} row read', '{0} rows read', rows.length - pend.length), st.skipped ? trn('{0} row skipped', '{0} rows skipped', st.skipped) : '', many ? trn('{0} file', '{0} files', p.files) : ''].filter(Boolean).join(' · '))}</p>
      ${p.camt052 ? `<p class="shint lhint keep bnk052">${ic('info', 's')} ${tr('These are day reports (CAMT.052). Pending transactions are shown but not imported; a booking that appears in several reports counts once. For the bookkeeping, better export the account statement (CAMT.053).')}</p>` : ''}${filesInfo(p)}
      ${rows.some(r => r.cut && !r.error) ? `<p class="shint lhint keep bgcut">${ic('info', 's')} ${esc(trn('{0} purpose is longer than {1} characters and is cut off on import.', '{0} purposes are longer than {1} characters and are cut off on import.', rows.filter(r => r.cut && !r.error).length, 200))}</p>` /* 2.363.3 (#3134) */ : ''}
      <ul class="bgprev">${shown.map((r, i) => r.pending && !r.error ? '' : `<li class="bgpr ${r.error ? 'err' : r.dup ? 'dup' : ''}"><label class="bgprc"><input type="checkbox" data-csr="${i}" ${r.error || r.dup ? '' : 'checked'} ${r.error ? 'disabled' : ''} aria-label="${esc(r.title || tr('Row {0}', r.n))}"></label>
        <span class="bgel"><b>${esc(r.title || '–')}</b><small class="muted">${esc([r.day ? fmtDateLoc(r.day) : '', r.counterpart, many ? r.file : ''].filter(Boolean).join(' · '))}</small>
        ${r.error ? `<small class="bgwarn">${ic('alert', 's')} ${esc(r.error)}</small>` : r.dup ? `<small class="bgwarn">${esc(tr('Already in the budget'))}</small>` : ''}
        ${r.recurring_id ? `<label class="chkl bgrecs2"><input type="checkbox" data-csrec="${i}" checked> ${esc(tr('belongs to “{0}”', recName(r.recurring_id) || tr('recurring entry')))}</label>` : ''}
        ${r.error ? '' : `<select data-cscat="${i}" aria-label="${esc(tr('Category'))}">${bg_catOpts(r.kind, r.cat_id)}</select>`}</span>
        ${r.amount != null ? `<span class="bgamt ${r.kind}">${r.kind === 'in' ? '+' : '−'}${esc(bg_money(r.amount))}</span>` : ''}</li>`).join('')}</ul>
      ${rows.length > BG_SHOW ? `<p class="muted bgmore">${esc(trn('{0} more row is imported as suggested', '{0} more rows are imported as suggested', rows.slice(BG_SHOW).filter(r => takeable(r) && !r.dup).length))}</p>` : ''}
      ${pend.length ? `<section class="bgsec bgpend"><h4>${esc(trn('{0} pending booking – not imported', '{0} pending bookings – not imported', pend.length))}</h4><p class="muted">${tr('Not booked yet: the booked version comes with a later statement.')}</p><ul class="bgpendl" role="list">${pend.slice(0, 50).map(r => `<li><span class="bgel"><b>${esc(r.title || '–')}</b><small class="muted">${esc([r.day ? fmtDateLoc(r.day) : '', r.counterpart].filter(Boolean).join(' · '))}</small></span>${r.amount != null ? `<span class="bgamt ${r.kind}">${r.kind === 'in' ? '+' : '−'}${esc(bg_money(r.amount))}</span>` : ''}</li>`).join('')}</ul></section>` : ''}`;
    foot.innerHTML = footHtml(okLabel(), true); err();
  };
  // the chosen rows in parts of at most BG_PART, the rows of one file together; one import run for all parts
  const commit = async rows => {
    const parts = [], byFile = new Map();
    for (const r of rows) { if (!byFile.has(r.fi)) byFile.set(r.fi, []); byFile.get(r.fi).push(r); }
    let cur = [];
    for (const list of byFile.values()) {
      if (cur.length && cur.length + list.length > BG_PART) { parts.push(cur); cur = []; }
      for (const r of list) { if (cur.length >= BG_PART) { parts.push(cur); cur = []; } cur.push(r); }
    }
    if (cur.length) parts.push(cur);
    let run = null, created = 0, dup = 0;
    for (const part of parts) {
      const j = await api('POST', `/api/budget/${lid}/import/commit`, {rows: part, mapping: st.mapping, columns: st.p.columns, ...(run ? {run} : {label: st.p.label || label(), fmt: st.p.fmt})});  // columns: the server remembers the mapping for this header
      run = j.run; created += j.created; dup += j.skipped_dup;
    }
    return {run, created, dup};
  };
  const next = async () => {
    const b = $('[data-cs="next"]', md); if (b) b.disabled = true;
    try {
      if (st.rows) {
        const rows = chosen().map(([r, i]) => {
          const cat = i < BG_SHOW ? +$(`[data-cscat="${i}"]`, md)?.value || null : r.cat_id, rec = i < BG_SHOW ? $(`[data-csrec="${i}"]`, md)?.checked : true;
          return {day: r.day, amount: r.amount, kind: r.kind, title: r.title, counterpart: r.counterpart || '', cat_id: cat, iban: r.iban || null, ref: r.ref || null, e2e: r.e2e || null, fi: r.fi || 0, ...(r.recurring_id && rec ? {recurring_id: r.recurring_id} : {})};
        });
        if (!rows.length) { err(tr('Nothing selected')); return; }
        const bl = listById(lid);  // 2.87.9 (#1940): where the entries go, in words (the budget's list decides the workspace)
        if (!await importTargetConfirm({what: trn('{0} entry', '{0} entries', rows.length), ws: wsOf(bl), place: bl ? lname(bl) : ''})) return;
        let j = await commit(rows);
        md.remove(); await bg_after();
        const msg = trn('{0} entry imported', '{0} entries imported', j.created) + (j.dup ? ' · ' + trn('{0} already there', '{0} already there', j.dup) : '');
        if (!j.created) { toast(msg); return; }
        offerUndo(msg, histAdd({label: tr('Bank import'),  // 2.146.0 C (#2455): undo = this import run back (changed entries stay)
          undo: async () => { await api('POST', `/api/budget/${lid}/import/runs/${j.run}/undo`, {edited: 'keep'}); await bg_after(); },
          redo: async () => { j = await commit(rows); await bg_after(); }}));
        return;
      }
      st.mapping = mapOf();
      if (st.mapping.date == null || st.mapping.title == null || (st.mapping.amount == null && st.mapping.amount_in == null && st.mapping.amount_out == null)) { err(tr('Please select the columns for date, amount and text')); return; }
      const j = await api('POST', `/api/budget/${lid}/import/parse`, form(st.mapping));
      st.rows = j.rows || []; st.skipped = j.skipped || 0; st.p = {...st.p, ...j, columns: st.p.columns, sample: st.p.sample, guess: st.p.guess}; step3(); f8d_step(md, backOne);
    } catch (er) { err(er.message); } finally { const b2 = $('[data-cs="next"]', md); if (b2) b2.disabled = false; }
  };
  // 2.962.0 (#5232): the view before (Back / Android Back): the columns again, or the start (CAMT has no column step)
  const backOne = () => { if (st.rows && st.p?.columns) { st.rows = null; step2(); } else { st.rows = null; st.p = null; step1(); } };
  const take = async fl => {
    st.files = [...(fl || [])]; if (!st.files.length) return;
    if (st.files.reduce((n, f) => n + f.size, 0) > BG_UPLOAD_MAX) { err(tr('The upload is too large (at most {0} MB)', 20)); return; }
    Object.assign(st, {p: null, rows: null, mapping: null});
    try { st.p = await api('POST', `/api/budget/${lid}/import/parse`, form(null)); }
    catch (er) { err(er.message || tr('The file could not be read')); return; }
    if (st.p.rows) { st.rows = st.p.rows; st.skipped = st.p.skipped || 0; step3(); f8d_step(md, backOne); return; }  // 2.140.0 B (#2134): CAMT -- the rows at once
    if (!st.p.columns?.length) { err(tr('No columns found in the file')); return; }
    step2(); f8d_step(md, backOne);  // 2.962.0 (#5232): a step of Back
  };
  md.addEventListener('click', async e => {
    const u = e.target.closest('[data-csundo]');
    if (u) { u.disabled = true; try { if (await bg_runUndo(lid, u.dataset.csundo)) step1(); } catch (er) { err(er.message); } finally { u.disabled = false; } return; }
    const b = e.target.closest('[data-cs]'); if (!b) return;
    if (b.dataset.cs === 'next') next();
    else if (b.dataset.cs === 'back') f8d_backBtn(md, backOne);  // 2.962.0 (#5232): = Android Back (its history entry goes along)
  });
  md.addEventListener('change', e => {
    if (e.target.matches('[data-csr]')) { const b = $('[data-cs="next"]', md); if (b) b.textContent = okLabel(); return; }
    const inp = e.target.closest('[data-cs-file]'); if (!inp || !inp.files?.length) return;
    take(inp.files);
  });
  // files dropped onto the dialog (like the office's bank import)
  md.addEventListener('dragover', e => { if (!st.p && [...(e.dataTransfer?.types || [])].includes('Files')) e.preventDefault(); });
  md.addEventListener('drop', e => { if (st.p || !e.dataTransfer?.files?.length) return; e.preventDefault(); take(e.dataTransfer.files); });
  md.bgTake = take;  // the UI tests hand files over here
  step1();
  return md;
}

// ---- 2.140.0 B (#2134): the month comparison -- the shown month against the months before it, one card per category
// (actual, plan, the difference to the month before and to the average), small bars per month; cards, no wide table
const BG_CMP = {n: 6};
function bg_cmpDiff(v, pct, kind) {
  if (v == null) return '';
  const up = +v > 0, worse = kind === 'out' ? up : !up, sign = up ? '+' : +v < 0 ? '−' : '±';
  return `<span class="bgcd ${+v === 0 ? '' : worse ? 'worse' : 'better'}">${sign}${esc(bg_money(Math.abs(+v)))}${pct != null ? ` (${sign}${esc(fmtNum(Math.abs(pct)))} %)` : ''}</span>`;
}
function bg_cmpCard(c, months) {
  const name = c.name ?? (c.key.startsWith('total') ? (c.kind === 'in' ? tr('Received') : tr('Spent')) : tr('No category'));
  const max = Math.max(1, ...c.months.map(x => Math.max(+x.ist, +x.soll)));
  const bars = !c.months.some(x => +x.ist) ? '' : `<div class="bgcmpbars" role="img" aria-label="${esc(c.months.map(x => `${bg_monthName(x.month)}: ${bg_money(x.ist)}`).join(', '))}">${c.months.map((x, i) => `<span class="bgcmpm ${i === months.length - 1 ? 'on' : ''}"><i style="transform:scaleY(${(+x.ist / max).toFixed(3)})"></i></span>`).join('')}</div>`;
  const line = (label, v) => v ? `<div class="bgcmpl"><span class="muted">${esc(label)}</span>${v}</div>` : '';
  return `<li class="bgcmpc ${c.kind}"><div class="bgcl"><b>${esc(name)}</b><span class="bgamt ${c.kind}">${esc(bg_money(c.ist))}</span></div>
    ${+c.soll ? line(tr('Plan'), `<span>${esc(bg_money(c.soll))}</span>`) : ''}
    ${line(tr('Compared with the month before'), bg_cmpDiff(c.diff_prev, c.pct_prev, c.kind))}
    ${months.length > 2 ? line(tr('Compared with the average'), bg_cmpDiff(c.diff_avg, c.pct_avg, c.kind)) : ''}${bars}</li>`;
}
async function bg_cmpModal() {
  const lid = BG.lid, month = BG.data.month;
  const md = bg_modal(`<h3>${ic('chart', 's')} ${tr('Month comparison')}</h3><div class="seg bgcmpn" role="radiogroup" aria-label="${esc(tr('Period'))}">${[3, 6, 12].map(n => `<button type="button" role="radio" data-cmpn="${n}" aria-checked="${n === BG_CMP.n}" class="${n === BG_CMP.n ? 'on' : ''}">${esc(trn('{0} month', '{0} months', n))}</button>`).join('')}</div><div class="bgcmp" aria-live="polite"><p class="muted">${tr('Loading…')}</p></div><div class="aerr" role="alert"></div><div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Close')}</button></div>`, async () => {});
  let seq = 0;
  const draw = async () => {
    const my = ++seq, box = $('.bgcmp', md);
    let j; try { j = await api('GET', `/api/budget/${lid}/compare?month=${month}&months=${BG_CMP.n}`); } catch (er) { if (my === seq) lifeErr(md, er); return; }
    if (my !== seq) return;
    const sec = (title, list) => list.length ? `<section class="bgsec"><h4>${esc(title)}</h4><ul class="bgcmpl0">${list.map(c => bg_cmpCard(c, j.months)).join('')}</ul></section>` : '';
    const outs = j.cats.filter(c => c.kind === 'out'), ins = j.cats.filter(c => c.kind === 'in');
    box.innerHTML = `<p class="muted">${esc(tr('{0} to {1}', bg_monthName(j.months[0]), bg_monthName(j.months[j.months.length - 1])))}</p>
      <ul class="bgcmpl0 bgcmpt">${bg_cmpCard(j.totals.out, j.months)}${bg_cmpCard(j.totals.in, j.months)}</ul>
      ${sec(tr('Expenses'), outs)}${sec(tr('Income'), ins)}${outs.length || ins.length ? '' : `<p class="muted">${tr('No entries in this period yet.')}</p>`}`;
  };
  md.addEventListener('click', e => {
    const b = e.target.closest('[data-cmpn]'); if (!b) return;
    BG_CMP.n = +b.dataset.cmpn;
    for (const x of $$('[data-cmpn]', md)) { x.classList.toggle('on', x === b); x.setAttribute('aria-checked', x === b); }
    draw();
  });
  draw();
  return md;
}

// ---- new budget list
// 2.607.0 (#4925): switching to another (new) budget = load it again; BG.done stayed true from the empty view, so the
// view kept the intro text until a reload. ++seq drops a load still under way for the old state.
function bg_reset(lid) { BG.seq++; BG.home = null; BG.lid = lid; BG.data = null; BG.loading = false; BG.done = false; }
async function bg_create() {
  let j; try { j = await api('POST', '/api/budget/lists', {}); } catch { return; }
  await load(); bg_reset(j.list_id); BG.month = bg_month();
  // undo = archive (a list is only deleted from the archive), redo = out of the archive again
  const arch = async v => { await api('PATCH', `/api/lists/${j.list_id}`, {archived: v}); await load(); bg_reset(v ? null : j.list_id); v ? render() : go(`budget/${j.list_id}`); };
  histAdd({label: tr('New budget'), undo: () => arch(1), redo: () => arch(0)});
  go(`budget/${j.list_id}`);
}

// 2.1012.0 (#5690): the "..." menu of the budget on the shared menu() (sheet with a title on the phone, Escape, arrow keys)
// (read only and not shareable = no entries: the view then draws no "..." at all, never an empty menu)
function bg_moreItems(d) {
  const w = d.can_write;
  return [
    w ? {label: tr('Categories'), icon: 'tag', fn: () => bg_catsModal()} : null,
    w ? {label: tr('Recurring entries'), icon: 'repeat', fn: () => bg_recModal()} : null,
    w && feat('contracts') ? {label: tr('Add from contracts'), icon: 'file', fn: () => bg_contractsModal()} : null,
    w ? {label: tr('Import a CSV file'), icon: 'upload', fn: () => bg_csvModal()} : null,
    shareOk(listById(d.list_id)) ? {label: tr('Share'), icon: 'users', fn: () => shareModal(d.list_id)} : null,
    w ? {label: tr('New budget'), icon: 'plus', fn: () => bg_create()} : null,
  ].filter(Boolean);
}
function bg_moreMenu(anchor) {
  const d = BG.data; if (!d) return;
  const it = bg_moreItems(d); if (it.length) menu(anchor, it, null, null, tr('More'));
}

// ---- clicks
document.addEventListener('click', async e => {
  const a = e.target.closest?.('[data-bg]'); if (!a || a.disabled) return;
  e.preventDefault();
  const k = a.dataset.bg, id = +a.dataset.id || 0;
  if (k === 'create') bg_create();
  else if (k === 'more') bg_moreMenu(a);
  else if (!BG.data) return;
  else if (k === 'prev' || k === 'next') { BG.month = bg_addMonth(BG.data.month, k === 'prev' ? -1 : 1); await bg_load(); $(`#view [data-bg="${k}"]`)?.focus(); }
  else if (k === 'now') { BG.month = bg_month(); await bg_load(); $('#view [data-bg="next"]')?.focus(); }
  else if (k === 'add') bg_entryModal(null);
  else if (k === 'entry' && id < 0) { const p = BG_PEND.get(id); if (p) p.then(rid => { const en = BG.data?.entries.find(x => x.id === rid); if (en) bg_entryModal(en); }, () => {}); }  // 2.559.0 (#4660): a new entry on its way opens once it has its id
  else if (k === 'entry') { const en = BG.data.entries.find(x => x.id === id); if (en) bg_entryModal(en); }
  else if (k === 'book') { a.disabled = true; await bg_book(id); }
  else if (k === 'compare') bg_cmpModal();
});
document.addEventListener('change', e => {
  const s = e.target.closest?.('[data-bg-list]'); if (!s) return;
  go(`budget/${+s.value}`);
});
