/* Kalmido web client: the household budget (module "budget", part of the area Home): the budget view of a budget list
   (lists.life 'budget'), its dialogs (entry, categories, recurring entries, taking over contracts, CSV import) and the
   card on Home & life. Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// 2.72.0 (#1333): a budget is a list without tasks; sharing it = sharing the list (reading = visible, writing = write
// access). Entries are always positive with a kind ("in" / "out"); plan per category = its monthly limit, else the
// recurring entries due that month; recurring entries are templates, booked by hand ("Booked"). Never visible to agents.
// Server routes: /api/budget (kalmido/life/budget.py). Live: the area "budget" of /api/version (liveparts.js -> bg_live).
const BG = {lid: null, month: null, data: null, home: null, loading: false, done: false, seq: 0, hseq: 0, stale: false};  // done: loaded once (no loop without a budget)
const BG_PER = {month: N_('monthly'), quarter: N_('quarterly'), year: N_('yearly')};
const bg_month = (d = new Date()) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
const bg_addMonth = (m, n) => { const [y, mo] = m.split('-').map(Number); return bg_month(new Date(y, mo - 1 + n, 1)); };
const bg_monthName = (m, short) => { const [y, mo] = m.split('-').map(Number); try { return new Intl.DateTimeFormat(LOCALE(), short ? {month: 'short'} : {month: 'long', year: 'numeric'}).format(new Date(y, mo - 1, 1)); } catch { return m; } };
const bg_money = n => fmtMoney(+n || 0);
// "1.234,56", "1234.56", "12,5" -> 1234.56 / 12.5; null when it is no amount
function bg_num(s) {
  let v = String(s ?? '').trim().replace(/\s|€/g, ''); if (!v) return null;
  if (/,\d{1,2}$/.test(v)) v = v.replace(/\./g, '').replace(',', '.'); else v = v.replace(/,/g, '');
  if (!/^\d{1,8}(\.\d{1,2})?$/.test(v)) return null;
  const n = +v; return n > 0 && n <= 10000000 ? n : null;
}
const bg_numStr = n => n == null ? '' : String(n).replace('.', LOCALE().startsWith('en') ? '.' : ',');
const bg_lidOfHash = () => +(/^#budget\/(\d+)/.exec(location.hash)?.[1] || 0) || null;
const bg_url = (p = '') => `/api/budget/${BG.lid}${p}`;

// ---- loading
async function bg_load() {
  const seq = ++BG.seq; BG.loading = true;
  try {
    if (!BG.lid || !BG.home) { const h = await api('GET', '/api/budget'); BG.home = h; BG.lid = BG.lid || h.lists[0]?.id || null; }
    BG.month = BG.month || bg_month();
    const j = BG.lid ? await api('GET', `${bg_url()}?month=${BG.month}`) : null;
    if (seq === BG.seq) { BG.data = j; BG.stale = false; }
  } catch (e) { if (seq === BG.seq) { BG.data = null; if (e.status === 404) { BG.lid = null; BG.home = null; } } }
  BG.loading = false; BG.done = true;
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
  const hl = bg_lidOfHash();
  if (hl && hl !== BG.lid) { BG.lid = hl; BG.data = null; BG.done = false; }
  if (BG.stale && !$('.modal.bgdlg')) { BG.stale = false; BG.done = false; }
  if (!BG.done && !BG.loading) setTimeout(bg_load, 0);
  const d = BG.data;
  if (!d && (BG.loading || !BG.done)) return `<div class="bgview"><p class="muted lempty">${tr('Loading…')}</p></div>`;
  if (!d) return `<div class="bgview"><div class="empty nempty eact">${ic('wallet')}<span>${tr('What comes in, what goes out, and what is left at the end of the month. Shared with the family if you like.')}</span><button type="button" class="btn pri" data-bg="create">${ic('plus', 's')} ${tr('Create a budget')}</button></div></div>`;
  const w = d.can_write, t = d.totals, lists = (BG.home?.lists || []);
  const pick = lists.length > 1 ? `<select class="bglist" data-bg-list aria-label="${esc(tr('Budget'))}">${lists.map(l => `<option value="${l.id}" ${l.id === d.list_id ? 'selected' : ''}>${esc(l.name)}</option>`).join('')}</select>` : `<h2 class="bgname">${esc(d.name)}</h2>`;
  const menu = `<details class="bgmenu"><summary class="iconbtn" aria-label="${esc(tr('More'))}" title="${esc(tr('More'))}">${ic('dots')}</summary><div class="bgmenul" role="menu">
    ${w ? `<button type="button" role="menuitem" data-bg="cats">${ic('tag', 's')}<span>${tr('Categories')}</span></button>
    <button type="button" role="menuitem" data-bg="rec">${ic('repeat', 's')}<span>${tr('Recurring entries')}</span></button>
    ${feat('contracts') ? `<button type="button" role="menuitem" data-bg="contracts">${ic('file', 's')}<span>${tr('Take over from contracts')}</span></button>` : ''}
    <button type="button" role="menuitem" data-bg="csv">${ic('upload', 's')}<span>${tr('Import a CSV file')}</span></button>` : ''}
    ${shareOk(listById(d.list_id)) ? `<button type="button" role="menuitem" data-bg="share">${ic('users', 's')}<span>${tr('Share')}</span></button>` : ''}
    ${w ? `<button type="button" role="menuitem" data-bg="create">${ic('plus', 's')}<span>${tr('New budget')}</span></button>` : ''}</div></details>`;
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
  return `<div class="bgview">${head}${sums}${trend}${add}${open}${cats}<section class="bgsec"><h3>${tr('Entries')}</h3>${ents}</section></div>`;
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
function bg_entryModal(e) {
  const d = BG.data, w = d.can_write, kind = e?.kind || 'out';
  const day0 = e?.day || (d.month === bg_month() ? today() : d.month + '-01');
  const filesHtml = x => !x ? '' : `<div class="row bgfiles"><label>${tr('Receipts')}</label><div class="bgfl">${(x.files || []).map(f => `<span class="bgfile"><a href="/api/budget/files/${f.id}?inline=1" target="_blank" rel="noopener">${ic('clip', 's')}<span>${esc(f.name)}</span></a>${w ? `<button type="button" class="iconbtn" data-bgf-del="${f.id}" aria-label="${esc(tr('Delete {0}', f.name))}" title="${esc(tr('Delete'))}">${ic('x', 's')}</button>` : ''}</span>`).join('')}
    ${w ? `<label class="btn sm bgup">${ic('upload', 's')}<span>${tr('Add a receipt')}</span><input type="file" multiple data-bgf-up hidden></label>` : ''}${!w && !(x.files || []).length ? `<span class="muted">${tr('none')}</span>` : ''}</div></div>`;
  const md = bg_modal(`<h3>${ic('wallet', 's')} ${e ? tr('Edit entry') : tr('New entry')}</h3>
    <div class="row"><label>${tr('Kind')}</label>${bg_kindSeg(kind)}</div>
    <div class="row"><label for="bg-amt">${tr('Amount')}</label><input id="bg-amt" inputmode="decimal" class="numin" autocomplete="off" value="${esc(bg_numStr(e?.amount))}" placeholder="0,00"></div>
    <div class="row"><label id="bg-dayl">${tr('Date')}</label>${dateIn('bg-day', day0, {label: tr('Date')})}</div>
    <div class="row"><label for="bg-title">${tr('What')}</label><input id="bg-title" maxlength="200" autocomplete="off" value="${esc(e?.title || '')}" placeholder="${esc(tr('e.g. Groceries, rent, salary'))}"></div>
    <div class="row"><label for="bg-cat">${tr('Category')}</label><select id="bg-cat">${bg_catOpts(kind, e?.cat_id)}</select></div>
    <div class="row"><label for="bg-cp">${tr('Paid to / from')}</label><input id="bg-cp" maxlength="200" autocomplete="off" value="${esc(e?.counterpart || '')}" placeholder="${esc(tr('optional'))}"></div>
    <div class="row"><label for="bg-note">${tr('Note')}</label><textarea id="bg-note" rows="2" maxlength="2000" placeholder="${esc(tr('optional'))}">${esc(e?.note || '')}</textarea></div>
    <div class="bgfwrap">${filesHtml(e)}</div>
    ${e && w ? `<div class="row"><span></span><button type="button" class="btn sm danger" data-bg-del>${ic('trash', 's')}<span>${tr('Delete entry')}</span></button></div>` : ''}
    ${w ? lifeFoot(e ? tr('Save') : tr('Add')) : `<div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Close')}</button></div>`}`, async md => {
    const v = id => $(id, md)?.value?.trim() ?? '';
    const amount = bg_num(v('#bg-amt')), title = v('#bg-title'), day = v('#bg-day');
    if (!amount) { $('#bg-amt', md).focus(); throw new Error(tr('Please enter an amount (up to 10,000,000)')); }
    if (!title) { $('#bg-title', md).focus(); throw new Error(tr('Please enter what it was')); }
    if (!day) throw new Error(tr('Please enter the date'));
    const body = {day, amount, kind: bg_kindOf(md), title, note: v('#bg-note'), counterpart: v('#bg-cp'), cat_id: +v('#bg-cat') || null};
    if (!e) {
      const r = await api('POST', bg_url('/entries'), body);
      let cur = r;
      offerUndo(tr('Added: {0}', title), histAdd({label: tr('New entry “{0}”', title), undo: async () => { await api('DELETE', `/api/budget/entries/${cur.id}`); bg_after(); },
        redo: async () => { cur = await api('POST', `/api/budget/${cur.list_id}/entries`, bg_body(cur)); bg_after(); }}));
      md.remove(); await bg_after();
      return;
    }
    const before = bg_body(e), id = e.id;
    await api('PATCH', `/api/budget/entries/${id}`, body);
    histAdd({label: tr('Entry “{0}” changed', title), undo: async () => { await api('PATCH', `/api/budget/entries/${id}`, before); bg_after(); },
      redo: async () => { await api('PATCH', `/api/budget/entries/${id}`, body); bg_after(); }});
    md.remove(); toast(tr('Saved')); await bg_after();
  }, e ? null : '#bg-amt');
  bg_kindWire(md, 'bg-kind', k => { const s = $('#bg-cat', md); s.innerHTML = bg_catOpts(k, +s.value || null); });
  if (!w) for (const x of $$('input, select, textarea, .bgkind button', md)) x.disabled = true;  // read access: look only
  if (!e) {
    // new: receipts can be added once it is saved (a hint instead of the upload)
    $('.bgfwrap', md).innerHTML = w ? `<div class="shint lhint keep">${tr('Receipts can be added after saving: open the entry again.')}</div>` : '';
  }
  md.addEventListener('click', async ev => {
    const del = ev.target.closest('[data-bg-del]'), fdel = ev.target.closest('[data-bgf-del]');
    if (del) {
      if (e.files?.length && !await askConfirm(tr('Delete “{0}”?', e.title), trn('The {0} receipt is deleted with it and cannot be brought back.', 'The {0} receipts are deleted with it and cannot be brought back.', e.files.length), {ok: tr('Delete'), danger: true})) return;
      await bg_delEntry(e); md.remove();
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
async function bg_delEntry(e) {
  let r; try { r = await api('DELETE', `/api/budget/entries/${e.id}`); } catch { return; }
  let cur = r.entry || e;
  offerUndo(tr('Deleted: {0}', e.title), histAdd({label: tr('Entry “{0}” deleted', e.title), undo: async () => { cur = await api('POST', `/api/budget/${cur.list_id}/entries`, bg_body(cur)); bg_after(); },
    redo: async () => { await api('DELETE', `/api/budget/entries/${cur.id}`); bg_after(); }}));
  bg_after();
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
// categories: name, kind, monthly limit, order (arrows); every change at once, each ONE undo step
function bg_catsModal() {
  const lid = BG.lid;
  const rowHtml = (c, i, n) => `<li class="bgcr" data-cid="${c.id}"><input class="bgcn" data-f="name" value="${esc(c.name)}" maxlength="80" aria-label="${esc(tr('Name'))}">
    <select data-f="kind" aria-label="${esc(tr('Kind'))}"><option value="out" ${c.kind === 'out' ? 'selected' : ''}>${tr('Expense')}</option><option value="in" ${c.kind === 'in' ? 'selected' : ''}>${tr('Income')}</option></select>
    <input class="numin" data-f="limit" inputmode="decimal" value="${esc(bg_numStr(c.limit))}" placeholder="${esc(tr('no limit'))}" aria-label="${esc(tr('Limit per month'))}">
    <span class="bgca"><button type="button" class="iconbtn" data-cmv="-1" ${i === 0 ? 'disabled' : ''} aria-label="${esc(tr('Move up'))}" title="${esc(tr('Move up'))}">${ic('up', 's')}</button><button type="button" class="iconbtn" data-cmv="1" ${i === n - 1 ? 'disabled' : ''} aria-label="${esc(tr('Move down'))}" title="${esc(tr('Move down'))}">${ic('down', 's')}</button><button type="button" class="iconbtn danger" data-cdel aria-label="${esc(tr('Delete {0}', c.name))}" title="${esc(tr('Delete'))}">${ic('trash', 's')}</button></span></li>`;
  const cats = () => [...(BG.data?.cats || [])].sort((a, b) => (a.sort ?? 0) - (b.sort ?? 0) || a.id - b.id);
  const listHtml = () => { const cs = cats(); return cs.length ? `<ul class="bgcrs">${cs.map((c, i) => rowHtml(c, i, cs.length)).join('')}</ul>` : `<p class="muted">${tr('No categories yet.')}</p>`; };
  const md = bg_modal(`<h3>${ic('tag', 's')} ${tr('Categories')}</h3>
    <div class="shint lhint keep">${tr('Monthly limit = what you plan to spend in a month. Without a limit the plan is the sum of the recurring entries of the category.')}</div>
    <div class="bgcwrap">${listHtml()}</div>
    <div class="bgcnew"><input id="bg-cnew" maxlength="80" placeholder="${esc(tr('New category'))}" aria-label="${esc(tr('New category'))}"><select id="bg-cnk" aria-label="${esc(tr('Kind'))}"><option value="out">${tr('Expense')}</option><option value="in">${tr('Income')}</option></select><input id="bg-cnl" class="numin" inputmode="decimal" placeholder="${esc(tr('no limit'))}" aria-label="${esc(tr('Limit per month'))}"><button type="button" class="btn sm" data-cadd>${ic('plus', 's')}<span>${tr('Add')}</span></button></div>
    <div class="aerr" role="alert"></div><div class="foot"><span class="spacer"></span><button class="btn pri" data-m="close">${tr('Done')}</button></div>`, async () => {}, '#bg-cnew');
  const redraw = async () => { await bg_load(); const w = $('.bgcwrap', md); if (w) w.innerHTML = listHtml(); };
  const patch = async (id, body, before, label) => {
    await api('PATCH', `/api/budget/cats/${id}`, body);
    histAdd({label, undo: async () => { await api('PATCH', `/api/budget/cats/${id}`, before); bg_after(); }, redo: async () => { await api('PATCH', `/api/budget/cats/${id}`, body); bg_after(); }});
  };
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
      const o = cs[j], sc = c.sort ?? i, so = o.sort ?? j, a = sc === so ? i : sc, b = sc === so ? j : so;
      try { await histGroup(async () => { await patch(c.id, {sort: b}, {sort: c.sort ?? null}, tr('Order of the categories')); await patch(o.id, {sort: a}, {sort: o.sort ?? null}, tr('Order of the categories')); }, tr('Order of the categories')); } catch (er) { lifeErr(md, er); }
      await redraw(); $(`.bgcr[data-cid="${c.id}"] [data-cmv="${mv.dataset.cmv}"]`, md)?.focus();
    } else if (del && c) {
      if (!await askConfirm(tr('Delete the category “{0}”?', c.name), tr('Its entries stay, without a category.'), {ok: tr('Delete'), danger: true})) return;
      let gone;
      try { gone = await api('DELETE', `/api/budget/cats/${c.id}`); } catch { return; }
      let cur = c;
      // 2.72.0 (#1333): undo re-creates the category and hangs its entries / recurring entries back on it
      const rehang = async (j) => { cur = await api('POST', `/api/budget/${lid}/cats`, {name: c.name, kind: c.kind, limit: c.limit});
        for (const id of j?.entry_ids || []) await api('PATCH', `/api/budget/entries/${id}`, {cat_id: cur.id}).catch(() => {});
        for (const id of j?.recurring_ids || []) await api('PATCH', `/api/budget/recurring/${id}`, {cat_id: cur.id}).catch(() => {}); };
      offerUndo(tr('Deleted: {0}', c.name), histAdd({label: tr('Category “{0}” deleted', c.name), undo: async () => { await rehang(gone); bg_after(); },
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
    <div class="row"><label for="bg-ra">${tr('Amount')}</label><input id="bg-ra" class="numin" inputmode="decimal" value="${esc(bg_numStr(r?.amount))}" placeholder="0,00"></div>
    <div class="row"><label for="bg-rper">${tr('How often')}</label><select id="bg-rper">${Object.entries(BG_PER).map(([k, w]) => `<option value="${k}" ${(r?.per || 'month') === k ? 'selected' : ''}>${tr(w)}</option>`).join('')}</select></div>
    <div class="row"><label for="bg-rc">${tr('Category')}</label><select id="bg-rc">${bg_catOpts(r?.kind || 'out', r?.cat_id)}</select></div>
    <div class="row"><label for="bg-rs">${tr('From')}</label><select id="bg-rs">${bg_monthOpts(r?.start || BG.data?.month || bg_month())}</select></div>
    <div class="row"><label for="bg-ru">${tr('Until')}</label><select id="bg-ru">${bg_monthOpts(r?.until || '', tr('open-ended'))}</select></div>
    <div class="row"><span></span><span class="lacts">${r ? `<button type="button" class="btn sm" data-rcancel>${tr('Cancel')}</button>` : ''}<button type="button" class="btn sm pri" data-rsave>${r ? tr('Save') : tr('Add')}</button></span></div></div>`;
  const md = bg_modal(`<h3>${ic('repeat', 's')} ${tr('Recurring entries')}</h3><div class="bgrwrap">${listHtml()}</div><div class="bgrfw">${formHtml(null)}</div>
    <div class="aerr" role="alert"></div><div class="foot"><span class="spacer"></span><button class="btn pri" data-m="close">${tr('Done')}</button></div>`, async () => {}, '#bg-rt');
  const wireForm = () => bg_kindWire(md, 'bg-rkind', k => { const s = $('#bg-rc', md); s.innerHTML = bg_catOpts(k, +s.value || null); });
  wireForm();
  const refresh = async () => { try { items = (await api('GET', `/api/budget/${lid}/recurring`)).items; } catch { /* keep */ } $('.bgrwrap', md).innerHTML = listHtml(); bg_after(); };
  const keys = ['title', 'amount', 'kind', 'cat_id', 'per', 'start', 'until'], pickR = r => Object.fromEntries(keys.map(k => [k, r[k] ?? null]));
  md.addEventListener('click', async ev => {
    const ed = ev.target.closest('[data-redit]'), del = ev.target.closest('[data-rdel]'), sy = ev.target.closest('[data-rsync]');
    if (ev.target.closest('[data-rcancel]')) { $('.bgrfw', md).innerHTML = formHtml(null); wireForm(); return; }
    if (ed) { $('.bgrfw', md).innerHTML = formHtml(items.find(x => x.id === +ed.dataset.redit)); wireForm(); $('#bg-rt', md).focus(); return; }
    if (sy) {
      const r = items.find(x => x.id === +sy.dataset.rsync); if (!r) return;
      try { await api('PATCH', `/api/budget/recurring/${r.id}`, {sync_contract: true}); } catch { return; }
      const before = {amount: r.amount, per: r.per};
      offerUndo(tr('Matched to the contract'), histAdd({label: tr('“{0}” matched to the contract', r.title), undo: async () => { await api('PATCH', `/api/budget/recurring/${r.id}`, before); bg_after(); }, redo: async () => { await api('PATCH', `/api/budget/recurring/${r.id}`, {sync_contract: true}); bg_after(); }}));
      return refresh();
    }
    if (del) {
      const r = items.find(x => x.id === +del.dataset.rdel); if (!r) return;
      if (!await askConfirm(tr('Delete “{0}”?', r.title), tr('Entries booked from it stay.'), {ok: tr('Delete'), danger: true})) return;
      try { await api('DELETE', `/api/budget/recurring/${r.id}`); } catch { return; }
      let cur = r;
      offerUndo(tr('Deleted: {0}', r.title), histAdd({label: tr('Recurring entry “{0}” deleted', r.title), undo: async () => { cur = await api('POST', `/api/budget/${lid}/recurring`, pickR(cur)); bg_after(); }, redo: async () => { await api('DELETE', `/api/budget/recurring/${cur.id}`); bg_after(); }}));
      return refresh();
    }
    if (ev.target.closest('[data-rsave]')) {
      const f = $('.bgrform', md), rid = +f.dataset.rid || 0, v = id => $(id, md)?.value?.trim() ?? '';
      const amount = bg_num(v('#bg-ra')), title = v('#bg-rt');
      if (!title) { $('#bg-rt', md).focus(); lifeErr(md, {message: tr('Please enter what it was')}); return; }
      if (!amount) { $('#bg-ra', md).focus(); lifeErr(md, {message: tr('Please enter an amount (up to 10,000,000)')}); return; }
      if (v('#bg-ru') && v('#bg-ru') < v('#bg-rs')) { lifeErr(md, {message: tr('“Until” is before “From”')}); return; }
      const body = {title, amount, kind: bg_kindOf(md, 'bg-rkind'), cat_id: +v('#bg-rc') || null, per: v('#bg-rper'), start: v('#bg-rs'), until: v('#bg-ru') || null};
      lifeErr(md, {message: ''});
      try {
        if (rid) {
          const before = pickR(items.find(x => x.id === rid));
          await api('PATCH', `/api/budget/recurring/${rid}`, body);
          histAdd({label: tr('Recurring entry “{0}” changed', title), undo: async () => { await api('PATCH', `/api/budget/recurring/${rid}`, before); bg_after(); }, redo: async () => { await api('PATCH', `/api/budget/recurring/${rid}`, body); bg_after(); }});
        } else {
          let cur = await api('POST', `/api/budget/${lid}/recurring`, body);
          histAdd({label: tr('New recurring entry “{0}”', title), undo: async () => { await api('DELETE', `/api/budget/recurring/${cur.id}`); bg_after(); }, redo: async () => { cur = await api('POST', `/api/budget/${lid}/recurring`, body); bg_after(); }});
        }
      } catch (er) { lifeErr(md, er); return; }
      $('.bgrfw', md).innerHTML = formHtml(null); wireForm(); refresh();
    }
  });
  return md;
}
// take over contracts (module Contracts) as recurring entries
async function bg_contractsModal() {
  const lid = BG.lid; let items;
  try { items = (await api('GET', bg_url('/contracts'))).items; } catch { return; }
  const per = p => tr(PERIOD_WORD[p] || BG_PER[p] || '');
  const body = items.length ? `<ul class="bgctr">${items.map(x => `<li><label class="chkl ${x.taken ? 'bgtaken' : ''}"><input type="checkbox" data-ctid="${x.task_id}" ${x.taken ? 'disabled' : x.cost != null ? 'checked' : ''} ${x.cost == null ? 'disabled' : ''}><span class="bgel"><b>${esc(x.name)}</b><small class="muted">${esc([x.provider, x.cost != null ? bg_money(x.cost) + ' ' + per(x.per) : tr('no cost entered'), x.taken ? tr('already taken over') : ''].filter(Boolean).join(' · '))}</small></span></label></li>`).join('')}</ul>
    <div class="row"><label for="bg-ctc">${tr('Category')}</label><select id="bg-ctc">${bg_catOpts('out', (BG.data?.cats || []).find(c => c.kind === 'out' && /versicher|insur/i.test(c.name))?.id)}</select></div>`
    : `<p class="muted">${tr('No contracts with a cost yet. Add them on Home & life under Contracts.')}</p>`;
  return bg_modal(`<h3>${ic('file', 's')} ${tr('Take over from contracts')}</h3>
    <div class="shint lhint keep">${tr('Each contract becomes a recurring entry with its cost. The values are copied: if the contract changes later, the budget shows it and you can match it.')}</div>
    ${body}${items.some(x => !x.taken && x.cost != null) ? lifeFoot(tr('Take over')) : `<div class="aerr" role="alert"></div><div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Close')}</button></div>`}`, async md => {
    const ids = $$('[data-ctid]:checked:not(:disabled)', md).map(x => +x.dataset.ctid);
    if (!ids.length) throw new Error(tr('Please choose at least one contract'));
    const j = await api('POST', `/api/budget/${lid}/contracts`, {task_ids: ids, ...(+$('#bg-ctc', md)?.value ? {cat_id: +$('#bg-ctc', md).value} : {})});
    let made = j.items || [];
    offerUndo(trn('{0} contract taken over', '{0} contracts taken over', j.created), histAdd({label: tr('Taken over from contracts'),
      undo: async () => { for (const r of made) await api('DELETE', `/api/budget/recurring/${r.id}`); bg_after(); },
      redo: async () => { made = (await api('POST', `/api/budget/${lid}/contracts`, {task_ids: ids})).items || []; bg_after(); }}));
    md.remove(); bg_after();
  });
}

// ---- CSV import: file -> columns -> preview -> commit
function bg_readFile(f) {
  const rd = enc => new Promise((ok, no) => { const r = new FileReader(); r.onload = () => ok(r.result); r.onerror = () => no(r.error); r.readAsText(f, enc); });
  return rd('utf-8').then(t => t.includes('�') ? rd('windows-1252') : t);
}
function bg_csvModal() {
  const lid = BG.lid, st = {text: '', p: null, rows: null, mapping: null};
  const md = bg_modal(`<h3>${ic('upload', 's')} ${tr('Import a CSV file')}</h3><div class="bgcsv"></div><div class="aerr" role="alert"></div><div class="foot bgcfoot"></div>`, async () => {});
  const area = $('.bgcsv', md), foot = $('.bgcfoot', md), err = m => lifeErr(md, {message: m || ''});
  const footHtml = (ok, back) => `${back ? `<button class="btn" data-cs="back">${tr('Back')}</button>` : ''}<span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button>${ok ? `<button class="btn pri" data-cs="next">${esc(ok)}</button>` : ''}`;
  const step1 = () => {
    area.innerHTML = `<div class="shint lhint keep">${ic('lock', 's')} ${tr('No bank access – only the file you download from your bank yourself (CSV export of your account statement).')}</div>
      <label class="btn bgpick">${ic('upload', 's')}<span>${tr('Choose a CSV file')}</span><input type="file" accept=".csv,.txt,text/csv,text/plain" data-cs-file hidden></label>`;
    foot.innerHTML = footHtml(''); err();
  };
  const sel = (id, label, val, opt) => `<div class="row"><label for="${id}">${esc(label)}</label><select id="${id}">${opt ? `<option value="">${tr('none')}</option>` : ''}${st.p.columns.map((c, i) => `<option value="${i}" ${val === i ? 'selected' : ''}>${esc(c || tr('Column {0}', i + 1))}</option>`).join('')}</select></div>`;
  const step2 = () => {
    const g = st.p.guess || {}, two = g.amount == null && (g.amount_in != null || g.amount_out != null);
    area.innerHTML = `<p class="muted">${tr('Which column holds what? Kalmido has guessed; please check.')}</p>
      ${sel('cs-date', tr('Date'), g.date)}
      <div class="row"><label>${tr('Amount')}</label><div class="seg" role="radiogroup" id="cs-am" aria-label="${esc(tr('Amount'))}"><button type="button" role="radio" data-am="one" aria-checked="${!two}" class="${two ? '' : 'on'}">${tr('One column (minus = expense)')}</button><button type="button" role="radio" data-am="two" aria-checked="${two}" class="${two ? 'on' : ''}">${tr('Income and expense apart')}</button></div></div>
      <div class="cs-one" ${two ? 'hidden' : ''}>${sel('cs-amt', tr('Amount'), g.amount)}</div>
      <div class="cs-two" ${two ? '' : 'hidden'}>${sel('cs-in', tr('Income'), g.amount_in, true)}${sel('cs-out', tr('Expense'), g.amount_out, true)}</div>
      ${sel('cs-title', tr('Text'), g.title)}${sel('cs-cp', tr('Paid to / from'), g.counterpart, true)}
      <div class="row"><label for="cs-dec">${tr('Decimal separator')}</label><select id="cs-dec"><option value="," ${g.decimal !== '.' ? 'selected' : ''}>${tr('comma (1.234,56)')}</option><option value="." ${g.decimal === '.' ? 'selected' : ''}>${tr('point (1,234.56)')}</option></select></div>
      <div class="row"><label for="cs-df">${tr('Date format')}</label><select id="cs-df">${['DD.MM.YYYY', 'DD.MM.YY', 'YYYY-MM-DD', 'MM/DD/YYYY'].map(f => `<option ${g.date_format === f ? 'selected' : ''}>${f}</option>`).join('')}</select></div>
      <div class="bgtblw"><table class="bgtbl"><thead><tr>${st.p.columns.map(c => `<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${st.p.sample.map(r => `<tr>${r.map(x => `<td>${esc(x)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
    foot.innerHTML = footHtml(tr('Preview'), true); err();
    $('#cs-am', md).addEventListener('click', e => { const b = e.target.closest('[data-am]'); if (!b) return; for (const x of $$('#cs-am [data-am]', md)) { x.classList.toggle('on', x === b); x.setAttribute('aria-checked', x === b); } $('.cs-one', md).hidden = b.dataset.am === 'two'; $('.cs-two', md).hidden = b.dataset.am !== 'two'; });
  };
  const mapOf = () => {
    const n = id => { const v = $(id, md)?.value; return v === '' || v == null ? null : +v; }, two = $('#cs-am [aria-checked="true"]', md)?.dataset.am === 'two';
    return {date: n('#cs-date'), amount: two ? null : n('#cs-amt'), amount_in: two ? n('#cs-in') : null, amount_out: two ? n('#cs-out') : null, title: n('#cs-title'), counterpart: n('#cs-cp'), decimal: $('#cs-dec', md).value, date_format: $('#cs-df', md).value};
  };
  const cnt = () => $$('[data-csr]:checked', md).length;
  const okLabel = () => trn('Take over {0} entry', 'Take over {0} entries', cnt());
  const step3 = () => {
    const rows = st.rows, recName = id => (BG.data?.open_recurring || []).find(o => o.recurring.id === id)?.recurring.title || '';
    area.innerHTML = `<p class="muted">${esc(trn('{0} row read', '{0} rows read', rows.length))}${st.skipped ? ' · ' + esc(trn('{0} row skipped', '{0} rows skipped', st.skipped)) : ''}</p>
      <ul class="bgprev">${rows.map((r, i) => `<li class="bgpr ${r.error ? 'err' : r.dup ? 'dup' : ''}"><label class="bgprc"><input type="checkbox" data-csr="${i}" ${r.error || r.dup ? '' : 'checked'} ${r.error ? 'disabled' : ''} aria-label="${esc(r.title || tr('Row {0}', r.n))}"></label>
        <span class="bgel"><b>${esc(r.title || '–')}</b><small class="muted">${esc([r.day ? fmtDateLoc(r.day) : '', r.counterpart].filter(Boolean).join(' · '))}</small>
        ${r.error ? `<small class="bgwarn">${ic('alert', 's')} ${esc(r.error)}</small>` : r.dup ? `<small class="bgwarn">${esc(tr('Already in the budget'))}</small>` : ''}
        ${r.recurring_id ? `<label class="chkl bgrecs2"><input type="checkbox" data-csrec="${i}" checked> ${esc(tr('belongs to “{0}”', recName(r.recurring_id) || tr('recurring entry')))}</label>` : ''}
        ${r.error ? '' : `<select data-cscat="${i}" aria-label="${esc(tr('Category'))}">${bg_catOpts(r.kind, r.cat_id)}</select>`}</span>
        ${r.amount != null ? `<span class="bgamt ${r.kind}">${r.kind === 'in' ? '+' : '−'}${esc(bg_money(r.amount))}</span>` : ''}</li>`).join('')}</ul>`;
    foot.innerHTML = footHtml(okLabel(), true); err();
  };
  const next = async () => {
    const b = $('[data-cs="next"]', md); if (b) b.disabled = true;
    try {
      if (st.rows) {
        const rows = st.rows.map((r, i) => [r, i]).filter(([, i]) => $(`[data-csr="${i}"]`, md)?.checked).map(([r, i]) => ({day: r.day, amount: r.amount, kind: r.kind, title: r.title, counterpart: r.counterpart || '', cat_id: +$(`[data-cscat="${i}"]`, md)?.value || null, ...(r.recurring_id && $(`[data-csrec="${i}"]`, md)?.checked ? {recurring_id: r.recurring_id} : {})}));
        if (!rows.length) { err(tr('Nothing chosen')); return; }
        const j = await api('POST', `/api/budget/${lid}/import/commit`, {rows, mapping: st.mapping, columns: st.p.columns});  // columns: the server remembers the mapping for this header
        md.remove(); await bg_after();
        toast(trn('{0} entry imported', '{0} entries imported', j.created) + (j.skipped_dup ? ' · ' + trn('{0} already there', '{0} already there', j.skipped_dup) : ''));
        return;
      }
      st.mapping = mapOf();
      if (st.mapping.date == null || st.mapping.title == null || (st.mapping.amount == null && st.mapping.amount_in == null && st.mapping.amount_out == null)) { err(tr('Please choose the columns for date, amount and text')); return; }
      const j = await api('POST', `/api/budget/${lid}/import/parse`, {text: st.text, mapping: st.mapping});
      st.rows = j.rows || []; st.skipped = j.skipped || 0; step3();
    } catch (er) { err(er.message); } finally { const b2 = $('[data-cs="next"]', md); if (b2) b2.disabled = false; }
  };
  md.addEventListener('click', e => {
    const b = e.target.closest('[data-cs]'); if (!b) return;
    if (b.dataset.cs === 'next') next();
    else if (b.dataset.cs === 'back') { if (st.rows) { st.rows = null; step2(); } else { st.p = null; step1(); } }
  });
  md.addEventListener('change', async e => {
    if (e.target.matches('[data-csr]')) { const b = $('[data-cs="next"]', md); if (b) b.textContent = okLabel(); return; }
    const inp = e.target.closest('[data-cs-file]'); if (!inp || !inp.files[0]) return;
    const f = inp.files[0];
    if (f.size > 2 * 1024 * 1024) { err(tr('The file is too big (at most 2 MB)')); return; }
    try { st.text = await bg_readFile(f); st.p = await api('POST', `/api/budget/${lid}/import/parse`, {text: st.text}); }
    catch (er) { err(er.message || tr('The file could not be read')); return; }
    if (!st.p.columns?.length) { err(tr('No columns found in the file')); return; }
    step2();
  });
  step1();
  return md;
}

// ---- new budget list
async function bg_create() {
  let j; try { j = await api('POST', '/api/budget/lists', {}); } catch { return; }
  await load(); BG.home = null; BG.lid = j.list_id; BG.data = null; BG.month = bg_month();
  histAdd({label: tr('New budget'), undo: async () => { await api('DELETE', `/api/lists/${j.list_id}`); await load(); BG.lid = null; BG.home = null; BG.data = null; render(); }, redo: async () => { toast(tr('Create the budget again with “Create a budget”')); }});
  go(`budget/${j.list_id}`);
}

// ---- clicks
document.addEventListener('click', async e => {
  const a = e.target.closest?.('[data-bg]'); if (!a || a.disabled) return;
  e.preventDefault();
  a.closest('details.bgmenu')?.removeAttribute('open');
  const k = a.dataset.bg, id = +a.dataset.id || 0;
  if (k === 'create') bg_create();
  else if (!BG.data) return;
  else if (k === 'prev' || k === 'next') { BG.month = bg_addMonth(BG.data.month, k === 'prev' ? -1 : 1); await bg_load(); $(`#view [data-bg="${k}"]`)?.focus(); }
  else if (k === 'now') { BG.month = bg_month(); await bg_load(); $('#view [data-bg="next"]')?.focus(); }
  else if (k === 'add') bg_entryModal(null);
  else if (k === 'entry') { const en = BG.data.entries.find(x => x.id === id); if (en) bg_entryModal(en); }
  else if (k === 'book') { a.disabled = true; await bg_book(id); }
  else if (k === 'cats') bg_catsModal();
  else if (k === 'rec') bg_recModal();
  else if (k === 'contracts') bg_contractsModal();
  else if (k === 'csv') bg_csvModal();
  else if (k === 'share') shareModal(BG.data.list_id);
});
document.addEventListener('change', e => {
  const s = e.target.closest?.('[data-bg-list]'); if (!s) return;
  go(`budget/${+s.value}`);
});
// the menu closes on a tap elsewhere
document.addEventListener('click', e => { for (const d of $$('details.bgmenu[open]')) if (!d.contains(e.target)) d.removeAttribute('open'); });
