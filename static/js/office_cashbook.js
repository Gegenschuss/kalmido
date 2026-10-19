// @ts-check
// 2.121.0 B (#2095): the cash book in the office (tab "Cash book", menu group Money, admins only). On top the balance of
// the cash box and the quick entry (phone first: in / out, amount, text, today), below the entries of the year with the
// running balance (newest first), the day closings and the cash boxes (settings: name, opening balance, archive; autosave).
// Nothing is deleted: an entry goes back only by a cancellation (a counter entry with a new number). "Close day" is final
// (confirmation, no undo); every other action is one undo step (toast). Server: kalmido/office/cashbook.py.
const CB = {oid: null, base: null, list: null, q: '', loading: false, err: null, bid: null, year: String(new Date().getFullYear()), view: 'entries', dir: 'in', links: null};
OFC_TABS.splice(OFC_TABS.findIndex(t => t[0] === 'settings'), 0, /** @type {any} */ (['cashbook', 'wallet', N_('Cash book'), 1, () => cbHtml(), 'money']));  // admins only

/** @param {string} s @param {any} [r] @returns {any} */
const cb$ = (s, r) => (r || document).querySelector(s);  // $ with a dialog as root (typed loosely)
const cbReload = (all) => { if (all) CB.base = null; CB.list = null; ofcDraw(); };
const cbBook = id => (CB.base?.books || []).find(b => b.id === id);
const cbToday = () => CB.base?.today || new Date().toISOString().slice(0, 10);
const cbVat = v => v ? `${v} %` : '';

async function cbLoad() {
  if (CB.loading) return;
  CB.loading = true;
  try {
    if (!CB.base) CB.base = await api('GET', '/api/office/cashbooks');
    const act = CB.base.books.filter(b => !b.archived);
    if (!cbBook(CB.bid)) CB.bid = (act[0] || CB.base.books[0])?.id || null;
    const q = `${CB.bid}:${CB.year}`;
    if (CB.bid && (!CB.list || CB.q !== q)) { CB.list = await api('GET', `/api/office/cashbooks/${CB.bid}/entries?year=${CB.year}`); CB.q = q; }
    CB.err = null;
  } catch (x) { CB.err = x.message || tr('unknown'); }
  CB.loading = false;
  ofcDraw();
}

// ---- the view
function cbHtml() {
  if (CB.oid !== OFC.info?.org_id) Object.assign(CB, {oid: OFC.info?.org_id, base: null, list: null, err: null, bid: null, links: null});  // another office area
  if (!ofcAdmin()) return `<div class="empty">${tr('Only the admins of the office see the cash book.')}</div>`;
  if (CB.err) return `<div class="empty">${esc(CB.err)}</div>`;
  if (!CB.base || (CB.view !== 'books' && (!CB.list || CB.q !== `${CB.bid}:${CB.year}`))) { if (!CB.loading) setTimeout(cbLoad, 0); return `<p class="muted lempty">${tr('Loading…')}</p>`; }
  const bs = CB.base.books, act = bs.filter(b => !b.archived || b.id === CB.bid), b = cbBook(CB.bid);
  const y0 = new Date().getFullYear(), years = [y0, y0 - 1, y0 - 2, y0 - 3, y0 - 4].map(String);
  const q = `book_id=${CB.bid}&year=${CB.year}`;
  const bar = `<div class="ofcbar cb-bar">${act.length > 1 ? `<select id="cb-book" aria-label="${esc(tr('Cash box'))}">${act.map(x => `<option value="${x.id}" ${x.id === CB.bid ? 'selected' : ''}>${esc(x.name + (x.archived ? ` · ${tr('archived')}` : ''))}</option>`).join('')}</select>` : ''}
    <select id="cb-year" aria-label="${esc(tr('Year'))}">${years.map(y => `<option ${y === CB.year ? 'selected' : ''}>${y}</option>`).join('')}</select>
    <div class="seg" role="group" aria-label="${esc(tr('Show'))}">${[['entries', tr('Entries')], ['closings', tr('Day closings')], ['books', tr('Cash boxes')]].map(([k, n]) => `<button type="button" data-cb="view" data-v="${k}" class="${CB.view === k ? 'on' : ''}" aria-pressed="${CB.view === k}">${n}</button>`).join('')}</div>
    <span class="spacer"></span><a class="btn sm ghost" href="/api/office/cashbook.csv?${q}" download>${ic('download', 's')}<span>CSV</span></a><a class="btn sm ghost" href="/api/office/cashbook.pdf?${q}" download>${ic('download', 's')}<span>PDF</span></a></div>`;
  const note = `<details class="lgb-note cb-note"><summary>${ic('alert', 's')}<span>${tr('Note on the cash book')}</span></summary><p class="muted">${esc(CB.base.note)}</p></details>`;
  const body = CB.view === 'books' ? cbBooksHtml() : CB.view === 'closings' ? cbClosingsHtml() : cbHeadHtml(b) + cbQuickHtml(b) + cbListHtml();
  return bar + body + note;
}
function cbHeadHtml(b) {
  const l = CB.list;
  return `<div class="cb-head"><div><span class="muted">${tr('Cash balance')}</span><b class="cb-bal">${ofcMoney(l.balance)}</b>
    <small class="muted">${esc(l.last_closed ? tr('Closed up to {0}', fmtDateLoc(l.last_closed)) : tr('No day closed yet'))}</small></div>
    <button class="btn" data-cb="close">${ic('check', 's')}<span>${tr('Close day')}</span></button></div>`
    + `<p class="muted ofchint cb-euer">${esc(tr('The cash book does not count in the income/expense statement: book the receipts and invoice payments there as usual.'))}</p>`;
}
function cbQuickHtml(b) {
  if (!b || b.archived) return '';
  return `<form class="cb-quick" id="cb-quick" autocomplete="off" aria-label="${esc(tr('New cash entry'))}">
    <div class="seg cb-dir" role="group" aria-label="${esc(tr('Kind'))}">${[['in', tr('Income')], ['out', tr('Expense')]].map(([k, n]) => `<button type="button" data-cb="dir" data-v="${k}" class="${CB.dir === k ? 'on' : ''}" aria-pressed="${CB.dir === k}">${n}</button>`).join('')}</div>
    <input id="cb-amount" inputmode="decimal" class="numin cb-amount" placeholder="${esc(tr('Amount'))}" aria-label="${esc(tr('Amount'))}" required>
    <input id="cb-text" maxlength="300" placeholder="${esc(tr('Text, e.g. sale at the counter'))}" aria-label="${esc(tr('Text'))}" required>
    <div class="cb-qrow">${dateIn('cb-day', cbToday(), {label: tr('Date'), clear: false})}
    <select id="cb-vat" aria-label="${esc(tr('VAT rate'))}">${['19', '7', '0'].map(v => `<option value="${v}">${v} %</option>`).join('')}</select>
    <input id="cb-cat" maxlength="60" list="cb-cats" placeholder="${esc(tr('Category'))}" aria-label="${esc(tr('Category'))}"><datalist id="cb-cats">${CB.base.categories.map(c => `<option value="${esc(c)}">`).join('')}</datalist></div>
    <div class="aerr" role="alert" id="cb-qerr"></div>
    <button class="btn pri cb-go" type="submit">${ic('plus', 's')}<span>${tr('Book')}</span></button></form>`;
}
function cbRef(e) {
  if (e.storno_of_no) return tr('Cancels no. {0}', e.storno_of_no);
  if (e.cancelled_by_no) return tr('Cancelled by no. {0}', e.cancelled_by_no);
  return '';
}
function cbListHtml() {
  const es = CB.list.entries;
  if (!es.length) return `<div class="empty nempty">${ic('wallet')}<span>${tr('No entries in this year.')}</span></div>`;
  return `<ul class="ofclist cb-list" role="list">${es.map(e => `<li><button type="button" class="ofcrow cb-row${e.cancelled_by || e.storno_of ? ' cb-x' : ''}" data-cb="open" data-id="${e.id}">
    <span class="cb-no">${e.no}</span><span class="ofcn"><b>${esc(e.text)}</b>
    <small class="muted">${esc([fmtDateLoc(e.day), e.category, cbVat(e.vat_pct), e.node ? tr('Receipt') + ': ' + e.node.name : '', e.invoice ? tr('Invoice') + ' ' + e.invoice.number : ''].filter(Boolean).join(' · '))}</small>
    ${cbRef(e) ? `<small class="cb-ref">${esc(cbRef(e))}</small>` : ''}</span>
    ${e.locked ? `<span class="cb-lock" title="${esc(tr('Day closed'))}" aria-label="${esc(tr('Day closed'))}">${ic('lock', 's')}</span>` : ''}
    <span class="cb-amt"><b class="${e.dir === 'in' ? 'cb-in' : 'cb-out'}">${e.dir === 'in' ? '+' : '−'} ${ofcMoney(e.amount)}</b><small class="muted">${ofcMoney(e.balance)}</small></span></button></li>`).join('')}</ul>`;
}
function cbClosingsHtml() {
  const cs = (CB.list?.closings || []).slice().reverse();
  if (!cs.length) return `<div class="empty nempty">${ic('check')}<span>${tr('No day closed in this year.')}</span></div>`;
  return `<div class="lgb-cards cb-cards">${cs.map(x => `<div class="lgb-card"><h4>${esc(fmtDateLoc(x.day))}</h4><p class="muted">${esc([trn('{0} entry', '{0} entries', x.count), x.by].filter(Boolean).join(' · '))}</p>
    <dl class="lgb-dl"><dt>${tr('Opening balance')}</dt><dd>${ofcMoney(x.opening)}</dd><dt>${tr('Income')}</dt><dd>${ofcMoney(x.sum_in)}</dd>
    <dt>${tr('Expense')}</dt><dd>${ofcMoney(x.sum_out)}</dd><dt>${tr('Closing balance')}</dt><dd><b>${ofcMoney(x.closing)}</b></dd></dl></div>`).join('')}</div>`;
}
function cbBooksHtml() {  // the settings of the cash boxes: sections like the general settings, saved on change
  const bs = CB.base.books;
  return `<div class="cb-books">${bs.map(b => `<section class="cb-bk${b.archived ? ' cb-arch' : ''}" data-bid="${b.id}" aria-labelledby="cb-bk${b.id}"><h3 id="cb-bk${b.id}">${esc(b.name)}${b.is_default ? ` <span class="rotag">${tr('Default')}</span>` : ''}${b.archived ? ` <span class="rotag">${tr('archived')}</span>` : ''}</h3>
    ${ofcRowF(`cb-n${b.id}`, tr('Name'), `<input id="cb-n${b.id}" data-cbf="name" value="${esc(b.name)}" maxlength="80">`)}
    ${ofcRowF(`cb-o${b.id}`, tr('Opening balance'), `<input id="cb-o${b.id}" data-cbf="opening" inputmode="decimal" class="numin" value="${esc(fmtNum(+b.opening, 2))}" ${b.last_closed ? 'disabled' : ''}>`, b.last_closed ? tr('Fixed after the first day closing.') : '')}
    <div class="row"><label>${tr('Opening day')}</label>${dateIn(`cb-od${b.id}`, b.opening_day, {label: tr('Opening day'), clear: false})}</div>
    <p class="muted">${esc([tr('Balance {0}', ofcMoney(b.balance)), trn('{0} entry', '{0} entries', b.entries), b.last_closed ? tr('Closed up to {0}', fmtDateLoc(b.last_closed)) : ''].filter(Boolean).join(' · '))}</p>
    ${b.is_default ? '' : `<button class="btn sm" data-cb="arch" data-id="${b.id}">${b.archived ? tr('Restore') : tr('Archive')}</button>`}</section>`).join('')}
    <button class="btn" data-cb="bnew">${ic('plus', 's')}<span>${tr('Add cash box')}</span></button></div>`;
}

// ---- actions
async function cbQuick(f) {
  const val = id => cb$(id, f)?.value ?? '', err = cb$('#cb-qerr', f);
  const amount = ofcNum(val('#cb-amount'));
  if (amount == null || amount <= 0) { err.textContent = tr('Invalid value: {0}', tr('Amount')); cb$('#cb-amount', f)?.focus(); return; }
  const body = {dir: CB.dir, amount: String(amount), text: val('#cb-text'), day: val('#cb-day') || cbToday(), vat_pct: val('#cb-vat'), category: val('#cb-cat')};
  try {
    const j = await api('POST', `/api/office/cashbooks/${CB.bid}/entries`, body);
    CB.year = j.day.slice(0, 4); cbReload(true);
    toast(tr('Booked as no. {0}', j.no), async () => { await api('POST', `/api/office/cash-entries/${j.id}/cancel`, {}); cbReload(true); });
  } catch (x) { if (err) err.textContent = x.message || ''; }
}
const CB_KEYS = ['day', 'dir', 'amount', 'vat_pct', 'text', 'category', 'node_id', 'invoice_id'];
async function cbLinks() {
  if (!CB.links) { try { CB.links = await api('GET', '/api/office/cashbooks/links'); } catch { CB.links = {receipts: [], invoices: []}; } }
  return CB.links;
}
async function cbEntryModal(e) {
  const ro = e.locked || e.cancelled_by || e.storno_of, links = ro ? {receipts: [], invoices: []} : await cbLinks();
  const rcs = links.receipts.map(r => [r.node_id, [fmtDateLoc(r.date), r.title, ofcMoney(r.amount)].filter(Boolean).join(' · ')]);
  if (e.node && !rcs.some(r => r[0] === e.node.id)) rcs.unshift([e.node.id, e.node.name]);
  const inv = links.invoices.map(i => [i.id, [i.number, i.client, fmtDateLoc(i.date)].filter(Boolean).join(' · ')]);
  if (e.invoice && !inv.some(i => i[0] === e.invoice.id)) inv.unshift([e.invoice.id, e.invoice.number]);
  const dis = ro ? 'disabled' : '';
  const md = modal(`<h3>${tr('Cash entry no. {0}', e.no)}</h3>
    ${ro ? `<p class="muted">${esc([e.locked ? tr('The day is closed: the entry cannot change any more; cancel it instead.') : '', cbRef(e)].filter(Boolean).join(' · '))}</p>` : ''}
    <fieldset class="cb-fs" ${dis}>
    <div class="row"><label>${tr('Kind')}</label>${ofcSel('cb-edir', e.dir, [['in', tr('Income')], ['out', tr('Expense')]])}</div>
    ${ofcRowF('cb-eamount', tr('Amount'), ofcIn('cb-eamount', fmtNum(+e.amount, 2), {num: true}))}
    ${ofcRowF('cb-etext', tr('Text'), ofcIn('cb-etext', e.text, {max: 300}))}
    <div class="row"><label>${tr('Date')}</label>${dateIn('cb-eday', e.day, {label: tr('Date'), clear: false})}</div>
    ${ofcRowF('cb-evat', tr('VAT rate'), ofcSel('cb-evat', e.vat_pct || '', [['19', '19 %'], ['7', '7 %'], ['0', '0 %']], tr('unknown')))}
    ${ofcRowF('cb-ecat', tr('Category'), ofcIn('cb-ecat', e.category, {max: 60, list: 'cb-cats2'}))}<datalist id="cb-cats2">${CB.base.categories.map(c => `<option value="${esc(c)}">`).join('')}</datalist>
    ${ofcRowF('cb-enode', tr('Receipt'), ofcSel('cb-enode', e.node?.id || '', rcs, tr('none')))}
    ${ofcRowF('cb-einv', tr('Invoice paid in cash'), ofcSel('cb-einv', e.invoice?.id || '', inv, tr('none')))}</fieldset>
    <p class="muted">${esc(tr('Balance after this entry: {0}', ofcMoney(e.balance)))} · ${esc(e.by)}</p>
    <div class="aerr" role="alert"></div>
    <div class="foot cb-foot">${!e.cancelled_by && !e.storno_of ? `<button class="btn danger" data-m="cancel">${tr('Cancel entry')}</button>` : ''}<button class="btn" data-m="log">${ic('clock', 's')}<span>${tr('History')}</span></button>
    <span class="spacer"></span><button class="btn" data-m="close">${tr('Close')}</button>${ro ? '' : `<button class="btn pri" data-m="save">${tr('Save')}</button>`}</div>`);
  md.classList.add('ofcdlg');
  const close = fgModal(md);
  const val = id => cb$(id, md)?.value ?? '';
  md.addEventListener('click', async ev => {
    const b = /** @type {any} */ (ev.target).closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { close(); return; }
    try {
      if (b.dataset.m === 'log') { cbLogModal(e); return; }
      if (b.dataset.m === 'cancel') {
        if (!await askConfirm(tr('Cancel entry no. {0}?', e.no), tr('A counter entry with a new number books the amount back; both stay in the cash book.'), {ok: tr('Cancel entry')})) return;
        const j = await api('POST', `/api/office/cash-entries/${e.id}/cancel`, {}); md.remove(); cbReload(true);
        // the undo books the original once more (nothing is deleted)
        toast(tr('Cancelled by no. {0}', j.entry.no), async () => {
          await api('POST', `/api/office/cashbooks/${e.book_id}/entries`, {day: j.entry.day, dir: e.dir, amount: e.amount, vat_pct: e.vat_pct, text: e.text, category: e.category});
          cbReload(true);
        });
        return;
      }
      const amount = ofcNum(val('#cb-eamount'));
      const body = {dir: val('#cb-edir'), amount: amount == null ? '' : String(amount), text: val('#cb-etext'), day: val('#cb-eday'), vat_pct: val('#cb-evat') || null,
        category: val('#cb-ecat'), node_id: +val('#cb-enode') || null, invoice_id: +val('#cb-einv') || null};
      const old = {dir: e.dir, amount: e.amount, text: e.text, day: e.day, vat_pct: e.vat_pct, category: e.category, node_id: e.node_id, invoice_id: e.invoice_id};
      await api('PATCH', `/api/office/cash-entries/${e.id}`, body); md.remove(); cbReload(true);
      toast(tr('Saved'), async () => { await api('PATCH', `/api/office/cash-entries/${e.id}`, old); cbReload(true); });
    } catch (x) { const el = cb$('.aerr', md); if (el) el.textContent = x.message || ''; }
  });
}
const CB_ACT = {create: N_('Created'), change: N_('Changed'), cancel: N_('Cancelled'), close: N_('Day closed'), book_create: N_('Cash box created'), book_change: N_('Cash box changed')};
const CB_FLD = {day: N_('Date'), dir: N_('Kind'), amount: N_('Amount'), vat_pct: N_('VAT rate'), text: N_('Text'), category: N_('Category'), node_id: N_('Receipt'), invoice_id: N_('Invoice')};
function cbPrev(p) {
  return Object.entries(p || {}).filter(([k]) => CB_FLD[k]).map(([k, v]) => {
    const s = k === 'dir' ? (v === 'in' ? tr('Income') : tr('Expense')) : k === 'day' ? (v ? fmtDateLoc(v) : '') : k === 'amount' ? ofcMoney(v) : k === 'vat_pct' ? cbVat(v) : v;
    return `${tr(CB_FLD[k])}: ${s ?? ''}`;
  }).join(' · ');
}
async function cbLogModal(e) {
  let rows;
  try { rows = (await api('GET', `/api/office/cash-entries/${e.id}/log`)).log; } catch (x) { toast(x.message || ''); return; }
  const md = modal(`<h3>${tr('History')}</h3><p class="muted">${esc(tr('Cash entry no. {0}', e.no))} · ${esc(e.text)}</p>
    <ol class="lgb-log">${rows.slice().reverse().map(r => `<li><b>${esc(tr(CB_ACT[r.action] || r.action))}</b> <span class="muted">${esc(new Date(r.at).toLocaleString(LOCALE(), {dateStyle: 'medium', timeStyle: 'short'}))} · ${esc(r.by)}</span>
      ${r.action === 'cancel' && r.prev.by_no ? `<small>${esc(tr('Cancelled by no. {0}', r.prev.by_no))}</small>` : cbPrev(r.prev) ? `<small>${esc((r.action === 'create' ? '' : tr('Before') + ': ') + cbPrev(r.prev))}</small>` : ''}</li>`).join('')}</ol>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Close')}</button></div>`);
  md.classList.add('ofcdlg');
  const close = fgModal(md);
  md.addEventListener('click', ev => { if (/** @type {any} */ (ev.target).closest('[data-m="close"]')) close(); });
}
async function cbCloseModal() {
  const b = cbBook(CB.bid); if (!b) return;
  const md = modal(`<h3>${tr('Close day')}</h3><p class="muted">${esc(b.name)}</p>
    <div class="row"><label>${tr('Day')}</label>${dateIn('cb-cday', cbToday(), {label: tr('Day'), clear: false})}</div>
    <div class="cb-plan" aria-live="polite"></div>
    <p class="muted">${esc(tr('Closing is final and cannot be undone: afterwards no entry up to this day can change, corrections only by cancellation.'))}</p>
    <div class="aerr" role="alert"></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save" disabled>${tr('Close for good')}</button></div>`);
  md.classList.add('ofcdlg');
  const close = fgModal(md), err = cb$('.aerr', md), go = cb$('[data-m="save"]', md);
  const preview = async () => {
    err.textContent = ''; go.disabled = true;
    try {
      const p = await api('GET', `/api/office/cashbooks/${b.id}/closing?day=${encodeURIComponent(cb$('#cb-cday', md).value)}`);
      cb$('.cb-plan', md).innerHTML = `<dl class="lgb-dl"><dt>${tr('Opening balance')}</dt><dd>${ofcMoney(p.opening)}</dd><dt>${tr('Income')}</dt><dd>${ofcMoney(p.sum_in)}</dd>
        <dt>${tr('Expense')}</dt><dd>${ofcMoney(p.sum_out)}</dd><dt>${tr('Closing balance')}</dt><dd><b>${ofcMoney(p.closing)}</b></dd></dl>
        <p class="muted">${esc([p.from !== p.day ? tr('Closes {0} to {1}', fmtDateLoc(p.from), fmtDateLoc(p.day)) : fmtDateLoc(p.day), trn('{0} entry', '{0} entries', p.count)].join(' · '))}</p>`;
      go.disabled = false;
    } catch (x) { cb$('.cb-plan', md).innerHTML = ''; err.textContent = x.message || ''; }
  };
  md.addEventListener('change', ev => { if (/** @type {any} */ (ev.target).id === 'cb-cday') preview(); });
  md.addEventListener('click', async ev => {
    const x = /** @type {any} */ (ev.target).closest('[data-m]'); if (!x) return;
    if (x.dataset.m === 'close') { close(); return; }
    if (!await askConfirm(tr('Close the day for good?'), tr('This cannot be undone.'), {ok: tr('Close for good')})) return;
    try { await api('POST', `/api/office/cashbooks/${b.id}/closing`, {day: cb$('#cb-cday', md).value}); md.remove(); cbReload(true); toast(tr('Day closed')); }
    catch (y) { err.textContent = y.message || ''; }
  });
  preview();
}
async function cbBookNew() {
  try {
    const j = await api('POST', '/api/office/cashbooks', {name: tr('Cash box {0}', (CB.base?.books.length || 0) + 1), opening: '0', opening_day: cbToday()});
    CB.bid = j.id; cbReload(true);
    toast(tr('Added'), async () => { await api('PATCH', `/api/office/cashbooks/${j.id}`, {archived: 1}); cbReload(true); });
  } catch (x) { toast(x.message || ''); }
}
async function cbBookSet(bid, key, v) {  // autosave of one field of a cash box; one undo step
  const b = cbBook(bid); if (!b || String(b[key]) === String(v)) return;
  const old = b[key];
  try {
    await api('PATCH', `/api/office/cashbooks/${bid}`, {[key]: v}); cbReload(true);
    toast(key === 'archived' ? (v ? tr('Archived') : tr('Restored')) : tr('Saved'), async () => { await api('PATCH', `/api/office/cashbooks/${bid}`, {[key]: old}); cbReload(true); });
  } catch (x) { toast(x.message || ''); cbReload(true); }
}

// ---- events
document.addEventListener('click', e => {
  const b = /** @type {any} */ (e.target).closest?.('[data-cb]'); if (!b || b.tagName === 'INPUT') return;
  const a = b.dataset.cb;
  if (a === 'open') { const x = (CB.list?.entries || []).find(y => y.id === +b.dataset.id); if (x) cbEntryModal(x); }
  else if (a === 'view') { CB.view = b.dataset.v; ofcDraw(); }
  else if (a === 'dir') { CB.dir = b.dataset.v; $$('[data-cb="dir"]').forEach(x => { const on = x.dataset.v === CB.dir; x.classList.toggle('on', on); x.setAttribute('aria-pressed', on); }); }
  else if (a === 'close') cbCloseModal();
  else if (a === 'bnew') cbBookNew();
  else if (a === 'arch') { const x = cbBook(+b.dataset.id); if (x) cbBookSet(x.id, 'archived', x.archived ? 0 : 1); }
  else return;
  e.preventDefault();
});
document.addEventListener('submit', e => { const f = /** @type {any} */ (e.target); if (f.id === 'cb-quick') { e.preventDefault(); cbQuick(f); } });
document.addEventListener('change', e => {
  const x = /** @type {any} */ (e.target);
  if (x.id === 'cb-year') { CB.year = x.value; cbReload(); }
  else if (x.id === 'cb-book') { CB.bid = +x.value; cbReload(); }
  else if (x.closest?.('.cb-bk')) {
    const bid = +x.closest('.cb-bk').dataset.bid, f = x.dataset.cbf || (x.id === `cb-od${bid}` ? 'opening_day' : '');
    if (f === 'opening') { const n = ofcNum(x.value); if (n == null || n < 0) { toast(tr('Invalid value: {0}', tr('Opening balance'))); return; } cbBookSet(bid, f, n.toFixed(2)); }
    else if (f) cbBookSet(bid, f, x.value);
  }
});
