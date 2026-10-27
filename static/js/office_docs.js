// Office & finance (2.36.1, #1021), part C: quotations -- the tab "Quotations" of the office view (office.js calls
// ofdOffersTab(el)) with the list and the editor (#office/offers/<id>). The server computes the sums (kalmido/office/calc.py)
// on every change and returns them; the editor shows exactly those figures in the document's language and currency.
const OFD = {list: null, loading: false, q: '', status: '', trial: LS.get('ofdTrial', '') || '', first: null, office: null, trialCount: 0, kind: 'offer', doc: null, docId: null, docLoading: false, seq: 0, saving: 0, err: '', open: {head: true, rights: true, texts: false, fields: false, log: false, pay: true}, log: null, logFor: 0};
const OFD_STATUS = [['draft', N_('Draft')], ['sent', N_('Sent|document')], ['accepted', N_('Accepted|document')], ['declined', N_('Declined')]];
// 2.38.0 (#1021, F1): invoices, credit notes and reminders share the tab; the server derives partial / overdue / cancelled
const OFD_KINDS = [['offer', N_('Quotations')], ['invoice', N_('Invoices')], ['credit', N_('Credit notes')], ['reminder', N_('Reminders|dunning')], ['delivery', N_('Delivery notes')], ['archive', N_('Archive|documents')]];  // 2.39.1 (#1182): + the legacy archive (office_import.js)
const OFD_STATE = {done: N_('Settled'), draft: N_('Draft'), issued: N_('Finalised'), sent: N_('Sent|document'), paid: N_('Paid'), partial: N_('Partly paid'), overdue: N_('Overdue'), open: N_('Open items'), cancelled: N_('Cancelled'), accepted: N_('Accepted|document'), declined: N_('Declined')};
const OFD_INV_STATUS = {invoice: ['draft', 'issued', 'sent', 'paid', 'cancelled'], credit: ['draft', 'issued', 'sent', 'paid'], reminder: ['draft', 'issued', 'sent'], delivery: ['draft', 'issued', 'sent']};  // 2.120.0 D (#2089): + delivery
const OFD_PAY = [['transfer', N_('Bank transfer')], ['cash', N_('Cash')], ['card', N_('Card')], ['other', N_('Other|payment')]];
const OFD_VATN = [['', N_('choose…')], ['reverse', N_('Reverse charge (recipient pays the VAT)')], ['abroad', N_('Not taxable domestically')], ['small', N_('Small business, no VAT')],
  ['eu_goods', N_('Goods to a business in the EU (tax-exempt)')], ['export', N_('Export of goods outside the EU (tax-exempt)')]];  // 2.355.0 C (#2844)
const ofdIsInv = d => !!d && d.kind !== 'offer';
const ofdKindName = (k, one) => tr(one ? {offer: N_('Quotation'), invoice: N_('Invoice'), credit: N_('Credit note'), reminder: N_('Reminder|dunning'), delivery: N_('Delivery note')}[k] || k : OFD_KINDS.find(x => x[0] === k)?.[1] || k);
const OFD_RAW = [['optional', N_('optional (shown, not counted)')], ['included', N_('included (counted)')], ['none', N_('no raw data line')]];
// 2.185.0 C (#2520): the de / en source of a document's free texts (names, text blocks, pack words): nl / fr / es / it take
// the English one; numbers follow the document's own language (ofdNumEn: only English writes the point)
const ofdLang = d => ['', 'de', undefined, null].includes((d || OFD.doc)?.lang) ? 'de' : 'en';
const ofdNumEn = d => (d || OFD.doc)?.lang === 'en';
// money and quantities in the DOCUMENT's language and currency (not the person's locale): 1.234,56 € / €1,234.50 / $1,234.50
function ofdMoney(n, d) {
  d = d || OFD.doc || {}; const en = ofdNumEn(d), cur = ofcSym(d.currency);  // 2.189.0 (#2475): €, $, £, else the code
  const neg = n < 0, a = Math.abs(+n || 0).toFixed(2), [w, f] = a.split('.'), g = w.replace(/\B(?=(\d{3})+(?!\d))/g, en ? ',' : '.');
  return en ? `${neg ? '-' : ''}${cur}${cur.length > 1 ? ' ' : ''}${g}.${f}` : `${neg ? '-' : ''}${g},${f} ${cur}`;
}
// 2.189.0 (#2475): every currency of the pack (homecur.HC_CODES; the document's own one stays choosable) and the rate hint
const ofdCurOpts = d => [...new Set([...(OFC.info?.pack?.currencies || ['EUR', 'USD']), d.currency].filter(Boolean))].map(c => [c, c]);
const ofdFxHint = d => ofcHome() === 'EUR' && d.currency === 'USD' ? tr('1 € in USD; rates stay in EUR and are converted')
  : tr('1 {0} in {1}; prices stay in {0} and are converted', ofcHome(), d.currency);
const ofdQty = (n, d) => { const s = String(+(+n || 0).toFixed(4)); return ofdNumEn(d) ? s : s.replace('.', ','); };
const ofdDec = () => { try { return (1.1).toLocaleString(LOCALE()).includes(',') ? ',' : '.'; } catch { return '.'; } };
const ofdNumIn = v => v == null || v === '' ? '' : String(+(+v).toFixed(4)).replace('.', ofdDec());
const ofdUnit = (u, d) => { const L = OFC.info?.pack?.labels?.[ofdLang(d)]?.units; return L?.[u] || tr(OFC_UNITS.find(x => x[0] === u)?.[1] || u); };
// 2.138.0 A (#2249): unit option text by quantity (singular only for exactly 1, like calc.unit_text; plural otherwise)
const OFU_PLURAL = { day: N_('Days|unit'), hour: N_('Hours|unit'), piece: N_('Pieces|unit'), minute: N_('Minutes|unit') };
function ofu_label(u, qty, d) {
  if (!OFU_PLURAL[u]) return tr(OFC_UNITS.find(x => x[0] === u)?.[1] || u);
  const L = OFC.info?.pack?.labels?.[ofdLang(d)];
  if (+qty === 1 && String(qty).trim() !== '') return L?.units_one?.[u] || tr(OFC_UNITS.find(x => x[0] === u)[1]);
  return L?.units?.[u] || tr(OFU_PLURAL[u]);
}
function ofu_sync(inp, d) {
  const sel = inp.closest('.ofdnums')?.querySelector('select[data-k="unit"]'); if (!sel) return;
  const q = parseNum(inp.value) ?? NaN;
  for (const o of sel.options) o.textContent = ofu_label(o.value, isNaN(q) ? 0 : q, d);
}
const ofdSvcName = (s, d) => (ofdLang(d) === 'en' ? s.name_en || s.name_de : s.name_de || s.name_en) || '';

// ---- loading
async function ofdLoadList(force) {
  if (OFD.loading) return;
  if (OFD.list && !force) return;
  if (OFD.kind === 'archive') { if (typeof OIM !== 'undefined') OIM.list = null; OFD.list = []; ofdDraw(); return; }  // 2.39.1 (#1182): office_import.js loads it
  OFD.loading = true;
  const k0 = OFD.kind, st0 = OFD.status;  // 2.356.0 C (#3004): a tab changed while this list loaded -> load that one instead
  try { const j = await api('GET', `/api/office/docs?kind=${OFD.kind}${OFD.status ? '&status=' + OFD.status : ''}${OFD.trial ? '&trial=' + OFD.trial : ''}${ofd_grpQs()}`);
    if (OFD.kind !== k0 || OFD.status !== st0) { OFD.loading = false; return ofdLoadList(true); }
    OFD.list = j.docs || []; OFD.role = j.role; OFD.err = ''; OFD.dunning = j.dunning || null; tri_meta(j); }  // 2.147.1 B (#2054): dunning; 2.144.10 C (#2576): + trial filter / meta
  catch (x) { OFD.list = []; OFD.err = x.message || tr('unknown'); }
  OFD.loading = false;
  ofdDraw();
}
async function ofdLoadDoc(id, force) {
  if (OFD.docLoading) return;
  if (OFD.doc && OFD.doc.id === id && !force) return;
  OFD.docLoading = true; OFD.docId = id;
  try { OFD.doc = await api('GET', `/api/office/docs/${id}`); OFD.viaFolder.delete(id); OFD.err = ''; OFD.conflict = null; if (OFD.doc?.kind && OFD.doc.kind !== OFD.kind) { OFD.kind = OFD.doc.kind; OFD.list = null; } }
  catch (x) {  // 2.199.0 B (#2742): no office right for it, but a shared folder holds it -> read through the folder (its PDF too)
    OFD.doc = null; OFD.err = x.message || tr('unknown');
    // 2.351.0 A (#2823): a draft with edit through the folder is edited (saved over the folder way, ofd_viaUrl)
    try { const j = await rawFetch('GET', `/api/fsref/office_doc/${id}`); OFD.doc = ofd_viaDoc(j, j.folder_role); OFD.viaFolder.add(id); OFD.err = ''; } catch { /* keep the office's answer */ }
  }
  OFD.docLoading = false;
  ofdDraw();
  fx8a_clientsFresh(force);
}
// 2.80.0 (#1842): the client list of the state is read again when a document opens; only a changed list redraws
// (review: the list with its statistics is heavy -- asked only when forced, when the office has no client yet or after a minute)
let fx8a_clAt = 0;
async function fx8a_clientsFresh(force) {
  if (typeof clientsOn !== 'function' || !clientsOn()) return;
  const none = !(S.clients || []).some(c => !c.archived && (c.org_id || null) === pb_clOrg());
  if (!force && !none && Date.now() - fx8a_clAt < 6e4) return;
  fx8a_clAt = Date.now();
  try {
    const j = await api('GET', '/api/clients'), sig = a => a.filter(c => !c.archived).map(c => `${c.id}:${c.name}:${c.org_id || ''}`).sort().join('|');
    if (sig(j.clients || []) !== sig(S.clients || [])) { await load(); ofdDraw(); }
  } catch { /* the open document stays as it is */ }
}
function ofdDraw() {
  if (S.route.mod !== 'office' || ofcTab() !== 'offers') return;
  const el = $('.office .ofcbody .pboffers') || $('.office .ofcbody'); if (el) ofdOffersTab(el);  // 2.47.3 (#1360): below the hint of an empty personal office
  ofd_crumbSync();
}
// 2.356.0 C (#3004): the path line is drawn with the page (before the document has loaded) -> it follows the open document here
function ofd_crumbSync() {
  if (typeof ofm_detail !== 'function') return;
  const html = ofm_detail('office'), old = $('#view .ofmcrumb');
  if (old) { if (!html) old.remove(); else if (old.outerHTML !== html) old.outerHTML = html; return; }
  if (!html) return;
  const h = $('#view .ofbody > .ofpt'), nav = $('#view .ofpb'), body = $('#view .ofbody');
  if (h) h.outerHTML = html; else if (nav) nav.insertAdjacentHTML('afterend', html); else if (body) body.insertAdjacentHTML('afterbegin', html);
}
// the entry from office.js: fills the tab's body (list or editor)
function ofdOffersTab(el) {
  const id = S.route.id;
  if (id) {
    if ((!OFD.doc || OFD.doc.id !== id) && !OFD.docLoading) setTimeout(() => ofdLoadDoc(id), 0);
    if (!OFC.data.services && !OFC.loading.services) setTimeout(() => ofcLoad('services'), 0);
    if (!OFC.data.texts && !OFC.loading.texts) setTimeout(() => ofcLoad('texts'), 0);
    if (!OFC.data.contracts && !OFC.loading.contracts) setTimeout(() => ofcLoad('contracts'), 0);
  } else { ofd_kindHash(); if (!OFD.list && !OFD.loading) setTimeout(ofdLoadList, 0); }
  keepFocus(el, () => fl_set(el, id ? ofdEditorHtml() : ofdListHtml()));  // 2.46.2 (#1718): morphed
  // 2.308.0 (#3251): the listeners sit on the tab body, not on a box inside it (the body and the box in it were both wired depending on timing: one click opened two dialogs)
  const host = el.closest('.ofcbody') || el;
  if (!host._ofd) { host._ofd = true; host.addEventListener('contextmenu', ofdCtx); if (typeof ms_longPress === 'function') OFD.lp = ms_longPress('#view .ofdrow', () => false, r => ofdRowMenu(r.dataset.id, r)); host.addEventListener('click', ofdClick); host.addEventListener('change', ofdChange); host.addEventListener('input', ofdInput); host.addEventListener('keydown', ofdKey); }
}

// 2.356.0 C (#3004): the kind tab is part of the address (#office/offers/invoice): a new address (link, Back) chooses the tab,
// a tab changed in place (reminder drafts, the cockpit) rewrites the address without a history step
function ofd_kindHash() {
  const p = location.hash.slice(1).split('/');
  if (p[0] !== 'office' || p[1] !== 'offers' || +p[2]) return;
  const hk = OFD_KINDS.some(x => x[0] === p[2]) ? p[2] : '';
  if (hk && hk !== OFD.kind && location.hash !== OFD.hashSeen) { OFD.kind = hk; OFD.status = ''; OFD.list = null; }
  // the bare #office/offers stays as it is for the first tab (the office's remembered page #2622, the menu's own address)
  if (hk !== OFD.kind && (hk || OFD.kind !== OFD_KINDS[0][0])) history.replaceState(history.state, '', `#office/offers/${OFD.kind}`);
  OFD.hashSeen = location.hash;
}
// ---- the list
function ofdListHtml() {
  const rows = OFD.list, k = OFD.kind, inv = k === 'invoice' || k === 'credit';
  const q = OFD.q.trim().toLowerCase();
  if (k === 'archive') return `<div class="seg ofdkinds" role="tablist" aria-label="${esc(tr('Document kind'))}">${OFD_KINDS.map(([v, n]) => `<button type="button" role="tab" data-ofd="kind" data-kind="${v}" aria-selected="${v === k}" class="${v === k ? 'on' : ''}">${tr(n)}</button>`).join('')}</div><div class="ofcbar ofdbar"><div class="ctsearch">${ic('search', 's')}<input id="ofd-q" type="search" value="${esc(OFD.q)}" placeholder="${esc(tr('Search'))}" aria-label="${esc(tr('Search documents'))}" autocomplete="off" enterkeyhint="search"></div></div>` + (typeof oimArchiveListHtml === 'function' ? oimArchiveListHtml(q) : '');
  const sts = k === 'offer' ? OFD_STATUS : (k === 'invoice' ? ['open', 'draft', 'issued', 'sent', 'partial', 'overdue', 'paid', 'cancelled'] : OFD_INV_STATUS[k]).map(v => [v, OFD_STATE[v]]);  // 2.356.0 D (#3007): + the open items
  const newBtn = k === 'offer' ? `<button class="btn sm pri" data-ofd="new">${ic('plus', 's')}<span>${tr('New quotation')}</span></button>`
    : k === 'invoice' ? `${typeof dx_btn === 'function' && ofcFeat('books.datev') ? dx_btn() : ''}<button class="btn sm" data-ofd="remind">${ic('clock', 's')}<span>${tr('Create reminder')}</span></button><button class="btn sm pri" data-ofd="new-inv" aria-haspopup="menu">${ic('plus', 's')}<span>${tr('New invoice')}</span></button>`
    : k === 'reminder' ? `<button class="btn sm pri" data-ofd="remind">${ic('plus', 's')}<span>${tr('Create reminder')}</span></button>`
    : k === 'delivery' ? `<button class="btn sm pri" data-ofd="new-ls">${ic('plus', 's')}<span>${tr('New delivery note')}</span></button>` : '';  // 2.120.0 D (#2089)
  const kinds = `<div class="seg ofdkinds" role="tablist" aria-label="${esc(tr('Document kind'))}">${OFD_KINDS.map(([v, n]) => `<button type="button" role="tab" data-ofd="kind" data-kind="${v}" aria-selected="${v === k}" class="${v === k ? 'on' : ''}">${tr(n)}</button>`).join('')}</div>`;
  // 2.46.1 (#1637): an empty offer list shows its one big button below the text, not a second one up here
  const noTop = k === 'offer' && rows && !rows.length && !q && !OFD.status && !OFD.trial;
  const bar = kinds + `<div class="ofcbar ofdbar"><div class="ctsearch">${ic('search', 's')}<input id="ofd-q" type="search" value="${esc(OFD.q)}" placeholder="${esc(tr('Search'))}" aria-label="${esc(tr('Search documents'))}" autocomplete="off" enterkeyhint="search"></div>
    <select id="ofd-status" aria-label="${esc(tr('Status'))}"><option value="">${tr('All|status')}</option>${sts.map(([v, n]) => `<option value="${v}" ${OFD.status === v ? 'selected' : ''}>${tr(n)}</option>`).join('')}</select>${ofd_fltHtml()}${tri_filterHtml()}<span class="spacer"></span>${ofcAdmin('offers') ? `<button type="button" class="btn sm" data-ofd="trash" title="${esc(tr('Trash'))}" aria-label="${esc(tr('Trash'))}">${ic('trash', 's')}</button>` : ''}${noTop ? '' : newBtn}</div>${tri_barHtml()}`;
  if (!rows) return bar + `<p class="muted lempty">${tr('Loading…')}</p>`;
  if (OFD.err && !rows.length) return bar + `<div class="empty">${esc(OFD.err)}</div>`;
  const hit = r => !q || [r.number, r.recipient_name, r.project_title, r.project_ref].some(v => (v || '').toLowerCase().includes(q));
  const list = rows.filter(hit);
  const emptyTxt = {offer: N_('No quotations yet.'),  // 2.298.0 A1 (#3186): the button sits right below
    invoice: N_('No invoices yet. Make one from a quotation, from time entries or start empty.'),
    credit: N_('No credit notes yet. A credit note is made from a finalised invoice.'), reminder: N_('No reminders yet. Pick open invoices in the invoice list.'),
    delivery: N_('No delivery notes yet. From a quotation, an invoice or empty – without prices.')};  // 2.120.0 D (#2089)
  if (!list.length) return bar + `<div class="empty nempty eact">${ic('receipt')}<span>${q || OFD.status || OFD.trial || ofd_grpQs() ? tr('Nothing matches.') : tr(emptyTxt[k])}</span>${!q && !OFD.status && !OFD.trial && !ofd_grpQs() && k === 'offer' ? `<button class="btn pri" data-ofd="new">${ic('plus', 's')}<span>${tr('New quotation')}</span></button>` : ''}</div>`;
  // 2.40.0 (#1368 point 9): settled reminders (all their invoices paid or cancelled) below the open ones
  const grp = k === 'reminder' && list.some(r => r.settled) && list.some(r => !r.settled);
  if (k === 'reminder') list.sort((a, b) => (a.settled ? 1 : 0) - (b.settled ? 1 : 0));
  const feeTxt = r => +r.fee_open > 0 ? `<small class="ofdfee">${esc(k === 'reminder' ? tr('fee open: {0}', r.fee_open_text || r.fee_open) : tr('reminder fee open: {0}', r.fee_open_text || r.fee_open))}</small>` : '';
  return bar + (k === 'invoice' && typeof oa_ppBox === 'function' ? oa_ppBox() : '') + (k === 'invoice' && typeof rinListHtml === 'function' ? rinListHtml() : '') /* 2.91.0 A (#1923) */ + (typeof dun_listHint === 'function' ? dun_listHint(k) : '') /* 2.147.1 B (#2054) */ + `<ul class="ofclist ofdlist" role="list">${list.map((r, i) => `${grp && r.settled && !list[i - 1]?.settled ? `<li class="ofdgrp muted" role="presentation">${tr('Settled')}</li>` : ''}<li class="ofdli"${isTouch() ? '' : ' draggable="true"' /* 2.351.0 A (#2823): onto a folder of the panel */}><button type="button" class="ofcrow ofdrow st-${r.state || r.status}" data-ofd="open" data-id="${r.id}">
    <span class="ofcn"><b>${r.locked ? `<span class="ofdlk" title="${esc(tr('Finalised'))}">${ic('lock', 's')}</span>` : ''}${esc(r.number || tr('(no number)'))}${r.recipient_name ? ` · ${esc(r.recipient_name)}` : ''}${typeof dun_rowTag === 'function' ? dun_rowTag(r) : '' /* 2.147.1 B (#2054) */}${tri_tag(r) /* 2.144.10 C (#2576) */}</b><small class="muted">${esc([r.project_title, r.date ? fmtDateLoc(r.date) : '', inv && r.due_date && !['paid', 'cancelled'].includes(r.state) ? tr('due {0}', fmtDateLoc(r.due_date)) : ''].filter(Boolean).join(' · '))}</small>${k === 'invoice' && typeof rinRowTag === 'function' ? rinRowTag(r) : ''}${k === 'invoice' && r.inv_type ? `<small class="rin-tag abs-tag">${esc(absKindName(r))}</small>` : ''}</span>
    <span class="ofdsum"><b>${esc(k === 'delivery' ? '' : inv ? r.gross_text : r.net_text)}</b>${k === 'delivery' ? '' : `<small class="muted oil_amt">${esc(inv ? (r.net !== r.gross ? tr('gross, net {0}', r.net_text) : tr('gross')) : tr('net'))}</small>` /* 2.356.0 C (#3003): which amount the row shows */}${inv && r.open && !['draft', 'paid', 'cancelled'].includes(r.state) && r.open !== r.gross ? `<small class="muted">${esc(tr('open: {0}', r.open_text || r.open))}</small>` : ''}${feeTxt(r)}<small class="rotag st-${r.state || r.status}">${esc(r.status_text)}</small></span></button><button type="button" class="iconbtn ofdrmore" data-ofd="rowmore" data-id="${r.id}" aria-haspopup="menu" aria-label="${esc(tr('More'))}" title="${esc(tr('More'))}">${ic('dots', 's')}</button></li>`).join('')}</ul>`;
}

// ---- the editor
const ofdSec = (key, title, body, extra = '') => `<details class="ofdsec" ${OFD.open[key] ? 'open' : ''} data-sec="${key}"><summary><h3>${esc(title)}</h3>${extra}</summary><div class="ofdsecb">${body}</div></details>`;
// 2.298.0 A1 (#3186): the help is a .shint behind the (i) of the label (o.keep = stays visible: units, follow-ups); with an
// (i) text of its own the help joins it (one (i) per label)
const ofdF = (k, label, field, hint, o) => { const ii = typeof OFC_II === 'object' && OFC_II['ed_' + k] && hint && !o?.keep;
  return `<div class="row"><label for="ofd-${k}">${esc(label)}</label>${field}${ii ? '' : ofcHint(hint, o)}</div>${typeof ofcII === 'function' ? ofcII('ed_' + k, ii ? hint : '') : ''}`; };  // 2.47.3 (#1382): (i) per field
const ofdSel = (k, cur, opts, empty) => `<select id="ofd-${k}" data-f="${k}">${empty != null ? `<option value="">${esc(empty)}</option>` : ''}${opts.map(([v, n]) => `<option value="${esc(v)}" ${String(v) === String(cur ?? '') ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select>`;
// 2.113.1 (#2251, #2252): the calculation options of the industry packs switched on (share by amount, handling costs,
// markup): switch / fields / position marks only with the option or on a document that already computes with it
const PRD_SLOTS = ['handling', 'markup'];
function prd_opts() {
  const o = {share: null, handling: null, markup: null};
  for (const p of OFC.info?.industry || []) for (const k of Object.keys(o)) if (!o[k] && p?.calc?.[k]) o[k] = p.calc[k];
  return o;
}
const prd_lbl = (l, d) => l ? (ofdLang(d) === 'en' ? l.en : l.de) || l.de || l.en || '' : '';
const prd_prodShown = d => (d.producing_on != null && d.producing_on !== 0) || (d.producing_on == null && d.kind === 'offer') || (d.producing_mode === 'amount' && !!prd_opts().share);
const prd_slotShown = (d, k) => d.kind === 'offer' && (d[k + '_pct'] != null || !!prd_opts()[k]);
const prd_slotName = (d, k) => prd_lbl(d[k + '_label'] || prd_opts()[k]?.label, d) || (k === 'handling' ? tr('Handling costs') : tr('Markup'));
const ofdIn = (k, v, o = {}) => `<input id="ofd-${k}" data-f="${k}" value="${esc(v ?? '')}" maxlength="${o.max || 200}" ${o.num ? 'inputmode="decimal" class="numin"' : ''} ${o.ph ? `placeholder="${esc(o.ph)}"` : ''} ${o.ro ? 'readonly' : ''}>`;
const ofdTa = (k, v, rows = 3, o = {}) => `<textarea id="ofd-${k}" data-f="${k}" rows="${rows}" maxlength="${o.max || 8000}" ${o.ph ? `placeholder="${esc(o.ph)}"` : ''}>${esc(v ?? '')}</textarea>`;
function ofdEditorHtml() {
  const d = OFD.doc && OFD.doc.id === S.route.id ? OFD.doc : null;
  const back = `<button type="button" class="btn sm ofdback" data-ofd="back">${ic('left', 's')}<span>${ofdKindName(OFD.kind)}</span></button>`;
  if (!d) return `<div class="ofdhead">${back}</div>` + (OFD.err ? `<div class="empty">${ic('receipt')}<span>${esc(OFD.err)}</span></div>` : `<p class="muted lempty">${tr('Loading…')}</p>`);
  const adm = ofcAdmin(), lg = ofdLang(d), t = d.totals || {};
  const texts = kind => ofcRows('texts').filter(x => x.kind === kind && !x.archived);
  const txtOpt = kind => texts(kind).map(x => [x.id, (x.key ? x.key + ': ' : '') + (lg === 'en' && !x.text_en && x.text_de ? tr('(no English text)') + ' ' : '') + ((lg === 'en' ? x.text_en || x.text_de : x.text_de || x.text_en) || '').slice(0, 70)]);  // 2.40.0 (#1381): no silent German
  const contracts = ofcRows('contracts').filter(x => !x.archived || x.id === d.contract_id).map(x => [x.id, x.name]);
  const clients = typeof clientsOn === 'function' && clientsOn() ? (S.clients || []).filter(c => (!c.archived && (c.org_id || null) === pb_clOrg()) || c.id === d.client_id).map(c => [c.id, cdn_label(c)]) : [];
  const lk = !!d.locked, inv = ofdIsInv(d), kind = d.kind, ro = !d.can_edit;
  const vf = !!d.via_folder;  // 2.351.0 F (#2823, review M4): through a folder: no status, next steps, parts, links into the master data
  const numTxt = d.number || (d.number_at_finalize ? tr('Draft') : tr('(no number)'));
  const stOpts = kind === 'offer' ? OFD_STATUS : OFD_INV_STATUS[kind].map(v => [v, OFD_STATE[v]]);
  const stCan = v => (kind === 'offer' && (v !== 'draft' || d.status === 'draft')) || v === d.status || (lk && d.status !== 'cancelled' && (v === 'sent' || (v === 'paid' && kind === 'invoice' && adm)) && (d.status !== 'paid' || adm));  // 2.39.1 (#1210 N3): paid only by admins
  const stSel = vf ? '' : `<select id="ofd-status" data-f="status" aria-label="${esc(tr('Status'))}" class="ofdstat st-${d.state || d.status}" ${inv && !lk ? 'disabled' : ''}>${stOpts.map(([v, n]) => `<option value="${v}" ${d.status === v ? 'selected' : ''} ${stCan(v) ? '' : 'disabled'}>${tr(n)}${v === d.status && d.state && d.state !== d.status ? ` (${tr(OFD_STATE[d.state])})` : ''}</option>`).join('')}</select>`;
  const acts = [];
  if (kind === 'offer') acts.push(kvaNextHtml(d, lk, ro));  // 2.138.0 E (#2235): the next step of the quotation; 2.144.7 (#2572): + "Create invoice"
  if (kind === 'invoice' && lk && d.status !== 'cancelled' && adm) acts.push(`<button type="button" class="btn sm" data-ofd="pay">${ic('plus', 's')}<span>${tr('Record payment')}</span></button>`);
  if (kind === 'offer' || kind === 'invoice') acts.push(`<button type="button" class="btn sm" data-ofd="to-ls" title="${esc(tr('A delivery note or proof of service with the positions, without prices'))}">${ic('file', 's')}<span>${tr('Delivery note')}</span></button>`);  // 2.120.0 D (#2089)
  if ((inv || kind === 'offer') && lk && !ofr_noSp('offers', 'release')) acts.push(`<button type="button" class="btn sm" data-ofd="send">${ic('send', 's')}<span>${tr('Send|mail')}</span></button>`);  // 2.113.2 (#2253): a finalised quotation is mailed too
  if (vf) acts.length = 0;
  const head = `<div class="ofdhead">${back}<span class="ofdnum"><b>${lk ? ic('lock', 's') + ' ' : ''}${inv ? esc(absKindName(d) || ofdKindName(kind, true)) + ' ' : ''}${esc(numTxt)}</b>${tri_tag(d) /* 2.144.10 C (#2576) */}${typeof onumDocHtml === 'function' ? onumDocHtml(d) : ''}${d.number || lk || d.number_at_finalize || !adm ? '' : `<button type="button" class="btn sm" data-ofd="number">${tr('Assign number')}</button>`}</span>
    ${stSel}<span class="spacer"></span>
    <span class="ofdsave muted" aria-live="polite">${OFD.saving ? tr('Saving…') : OFD.err ? esc(OFD.err) : ''}</span>${acts.join('')}
    ${lk || ro || ofr_noSp('offers', 'release') /* 2.187.0 A (#2476) */ ? '' : `<button type="button" class="btn sm ofdfin" data-ofd="finalize" title="${esc(tr('Freeze number, positions, sums, sender and tax rates'))}">${ic('lock', 's')}<span>${tr('Finalise')}</span></button>`}
    <span class="oil_tail">${lk || ro || d.status !== 'draft' ? `<a class="btn sm ofdpdf" href="${ofdPdfUrl(d.id, true)}" target="_blank" rel="noopener" data-ofd="pdf"${typeof pv_attr === 'function' ? pv_attr(ofdPdfView(d)) : ''} aria-label="${esc(tr('Open PDF'))}" title="${esc(tr('Open PDF'))}">${ic('pdf', 's')}<span class="ofdpdft">${tr('Preview')}</span></a>
    <a class="btn sm ofddl" href="${ofdPdfUrl(d.id)}" download data-ofd="pdf" aria-label="${esc(tr('Download PDF'))}" title="${esc(tr('Download PDF'))}">${ic('download', 's')}<span class="ofdpdft">${tr('Download')}</span></a>`
    : `<button type="button" class="btn sm ofdpdf" data-ofd="pdf-ask" aria-label="${esc(tr('Open PDF'))}" title="${esc(tr('Open PDF'))}">${ic('pdf', 's')}<span class="ofdpdft">${tr('Preview')}</span></button>
    <button type="button" class="btn sm ofddl" data-ofd="pdf-ask" data-dl="1" aria-label="${esc(tr('Download PDF'))}" title="${esc(tr('Download PDF'))}">${ic('download', 's')}<span class="ofdpdft">${tr('Download')}</span></button>`}
    <button type="button" class="btn sm" data-ofd="more" aria-haspopup="menu" aria-label="${esc(tr('More'))}">${ic('dots', 's')}</button></span></div>`;  // 2.356.0 C (#3004): "…" never wraps alone into a line of its own
  const invFields = inv && kind !== 'reminder' ? `
    ${d.dup_times_from && !lk ? `<p class="cdnmiss" role="status">${ic('info', 's')} ${esc(tr('Copy of {0}: the hours of that invoice are already billed. This copy binds no times.', d.dup_times_from))}</p>` : ''}
    ${ofdF('order_ref', tr('Order number / reference'), ofdIn('order_ref', d.order_ref, {max: 80, ph: tr('the client\'s order reference')}))}
    ${kind === 'invoice' ? ofdF('payment_days', tr('Payment terms'), `<span class="lacts">${ofdIn('payment_days', d.payment_days ?? '', {num: true, max: 3})}<span class="muted">${tr('days')}</span></span>`) : ''}
    ${kind === 'invoice' ? ofdF('due_date', tr('Due on'), dateIn('ofd-due_date', d.due_date || '', {label: tr('Due on'), attrs: 'data-f="due_date"'})) : ''}
    ${kind === 'invoice' ? absHeadFields(d) : ''}
    ${d.vat_mode === 'novat' && kind !== 'delivery' ? ofdF('vat_note', tr('VAT note'), ofdSel('vat_note', d.vat_note || '', OFD_VATN.map(([v, n]) => [v, tr(n)])), tr('printed on the invoice; required when finalising'), {keep: 1}) : ''}
    ${kind === 'delivery' || !ofcFeat('docs.einvoice') ? '' : ofdF('einvoice_format', tr('E-invoice format'), ofdSel('einvoice_format', d.einvoice_format || 'zugferd', ofdEinvOpts()))}` : '';  // 2.147.0 (#2460, #2461): only while e-invoices are on, the pack's formats  // 2.120.0 D (#2089): no e-invoice
  const remFields = kind === 'reminder' ? `
    ${ofdF('reminder_level', tr('Reminder level'), ofdSel('reminder_level', d.reminder_level || 1, [[1, tr('1 - payment reminder')], [2, tr('2 - reminder')], [3, tr('3 - final reminder')]]))}
    ${ofdF('reminder_fee', tr('Reminder fee'), `<span class="lacts">${ofdIn('reminder_fee', ofdNumIn(d.reminder_fee), {num: true, max: 10})}<span class="muted">${ofcSym(d.currency)}</span></span>`)}
    ${ofdF('reminder_deadline_days', tr('Payment deadline'), `<span class="lacts">${ofdIn('reminder_deadline_days', d.reminder_deadline_days ?? '', {num: true, max: 3})}<span class="muted">${tr('days')}</span></span>`)}` : '';
  // 2.356.0 C (#3005): the client comes first; language, currency, VAT and framework contract wait folded below ("More details",
  // the summary names their values) -- quotations and invoices alike
  const moreF = `${ofdF('lang', tr('Document language'), ofdSel('lang', d.lang, (S.languages || []).map(L => [L.code, L.name])))}
    ${ofdF('currency', tr('Currency'), ofdSel('currency', d.currency, ofdCurOpts(d)))}
    ${d.currency !== ofcHome() ? ofdF('fx_rate', tr('Exchange rate'), ofdIn('fx_rate', ofdNumIn(d.fx_rate), {num: true, max: 12}), ofdFxHint(d)) : ''}
    ${kind !== 'reminder' && kind !== 'delivery' ? ofdF('vat_mode', tr('VAT'), ofdSel('vat_mode', d.vat_mode, [['vat', tr('with VAT')], ['novat', tr('without VAT (reverse charge / abroad)')]])) : ''}
    ${!vf && kind !== 'reminder' && kind !== 'delivery' ? ofdF('contract_id', tr('Framework contract'), ofdSel('contract_id', d.contract_id, contracts, tr('none|contract')), d.contract ? tr('presets raw data, rights and closing; special rates apply to new positions') : '') : ''}`;
  const moreSum = [(S.languages || []).find(L => L.code === d.lang)?.name || d.lang, d.currency, kind === 'reminder' || kind === 'delivery' ? '' : d.vat_mode === 'novat' ? tr('without VAT') : tr('with VAT'), d.contract?.name || ''].filter(Boolean).join(' · ');
  const headSec = ofdSec('head', tr('Head'), `
    <div class="ofdgrid">
    ${vf ? '' : clients.length ? ofdF('client_id', tr('Client'), ofdSel('client_id', d.client_id, clients, cdn_on() ? tr('No client') : tr('free recipient'))) : typeof clientsOn === 'function' && clientsOn() ? `<div class="row fx8a_nocl"><label>${esc(tr('Client'))}</label><span class="muted">${esc(tr('No clients in this area yet'))}</span>${ro ? '' : `<button type="button" class="btn sm" data-ofd="client-new">${ic('plus', 's')}<span>${tr('Add client')}</span></button>`}</div>` : ''}
    ${d.client_id && (d.client_contacts || []).length ? ofdF('contact_id', tr('Contact person'), ofdSel('contact_id', d.contact_id ?? d.client_contacts[0].id, [...d.client_contacts.map(k => [k.id, k.name + (k.role ? ` (${k.role})` : '') + (k.is_default ? ' · ' + tr('default') : '')]), [0, tr('no contact person')]]), tr('the attention line of the address follows the choice')) : ''}
    ${cdn_on() ? cdn_recHtml(d, ro) : `${ofdF('recipient_name', tr('Recipient'), ofdIn('recipient_name', d.recipient?.name, {ph: tr('Company or name')}))}
    ${ofdF('recipient_lines', tr('Address lines'), ofdTa('recipient_lines', (d.recipient?.lines || []).join('\n'), 3, {ph: tr('one line each: name, attention, street, place')}))}`}
    ${ofdF('project_title', tr('Project title'), ofdIn('project_title', d.project_title))}
    ${kind === 'delivery' ? ofdF('delivery_title', tr('Document title'), ofdSel('delivery_title', d.delivery_title || '', [['', tr('Delivery note')], ['service', tr('Proof of service')]])) : ''}
    ${kind === 'offer' ? ofdF('project_ref', tr('Order number / reference'), ofdIn('project_ref', d.project_ref, {max: 80})) : ''}
    ${ofdF('date', tr('Date'), dateIn('ofd-date', d.date, {label: tr('Date'), clear: false, attrs: 'data-f="date"'}))}
    ${kind === 'offer' ? ofdF('valid_until', tr('Valid until'), dateIn('ofd-valid_until', d.valid_until, {label: tr('Valid until'), attrs: 'data-f="valid_until"'})) : ''}
    ${kind !== 'reminder' ? ofdF('service_from', tr('Service from'), dateIn('ofd-service_from', d.service_from || '', {label: tr('Service from'), attrs: 'data-f="service_from"'})) : ''}
    ${kind !== 'reminder' ? ofdF('service_to', tr('Service until'), dateIn('ofd-service_to', d.service_to || '', {label: tr('Service until'), attrs: 'data-f="service_to"', after: 'ofd-service_from'})) : ''}
    ${invFields}${remFields}
    </div><details class="oil_more" ${OFD.open.more ? 'open' : ''}><summary>${ic('chev', 's fcar')}<span>${tr('More details')}</span> <span class="muted">${esc(moreSum)}</span></summary><div class="ofdgrid">${moreF}</div></details>${kind === 'credit' && d.cancels ? `<p class="muted ofchint">${esc(tr('Credit note for invoice {0}', d.cancels.number || '#' + d.cancels.id))} <a href="#office/offers/${d.cancels.id}">${tr('open')}</a></p>` : ''}`);
  const items = kind === 'reminder' ? ofdRefsHtml(d, t) : ofdItemsHtml(d, adm);
  const auto = inv ? '' : ofdAutoHtml(d, t);
  const rights = d.rights || {};
  const dim = (k, kind, label) => `<div class="row ofdrt"><label for="ofd-r-${k}">${esc(label)}</label><span class="lacts ofdrtf">${ofdSel('r-' + k, rights[k]?.id, txtOpt(kind), tr('free text'))}${ofdIn('r-' + k + '-t', rights[k]?.text, {max: 1000, ph: tr('Text in the document')})}</span></div>`;
  const rightsSec = ofdSec('rights', tr('Transfer of rights'), dim('time', 'rights_time', tr('Duration')) + dim('territory', 'rights_territory', tr('Territory')) + dim('media', 'rights_media', tr('Media'))
    + ofdF('r-exceptions', tr('Exceptions'), ofdIn('r-exceptions', rights.exceptions, {max: 2000, ph: tr('e.g. music, stock material')}))
    + `<div class="row"><label class="chkl" style="min-width:0"><input type="checkbox" id="ofd-r-exclusive" data-f="r-exclusive" ${rights.exclusive ? 'checked' : ''}> ${tr('Exclusive')}</label></div>`
    + ofdF('r-note', tr('Note'), ofdTa('r-note', rights.note, 2, {max: 2000})));
  const textsSec = ofdSec('texts', tr('Introduction and closing'), `
    <div class="row"><label for="ofd-intro">${tr('Introduction')}</label><span class="lacts ofdtxt">${ofdSel('intro_pick', '', txtOpt('intro'), tr('from a text block…'))}</span></div>${ofdTa('intro', d.intro, 3)}
    <div class="row"><label for="ofd-closing">${tr('Closing')}</label><span class="lacts ofdtxt">${ofdSel('closing_pick', '', txtOpt('closing'), tr('from a text block…'))}</span></div>${ofdTa('closing', d.closing, 3)}${typeof ast_ofdBtn === 'function' ? ast_ofdBtn(d) : '' /* 2.126.1 A (#2123) */}${kind === 'offer' ? ofdAcceptHtml(d) : ''}`);
  const fields = d.fields || [];
  const fieldsSec = ofdSec('fields', tr('Own fields'), `<div id="ofd-fields">${fields.map((f, i) => `<div class="row ofdfld"><input data-fld="${i}" data-k="name" value="${esc(f.name)}" maxlength="80" placeholder="${esc(tr('Name'))}" aria-label="${esc(tr('Name'))}"><input data-fld="${i}" data-k="value" value="${esc(f.value)}" maxlength="500" placeholder="${esc(tr('Value'))}" aria-label="${esc(tr('Value'))}"><button type="button" class="ib" data-ofd="fld-del" data-i="${i}" aria-label="${esc(tr('Remove'))}">${ic('x', 's')}</button></div>`).join('')}</div><button type="button" class="btn sm" data-ofd="fld-add">${ic('plus', 's')} ${tr('Add field')}</button>`,
    fields.length ? `<span class="c muted">${fields.length}</span>` : '');
  const totals = kind === 'delivery' ? '' : ofdTotalsHtml(d, t, adm);  // 2.120.0 D (#2089): no sums
  const banner = lk ? `<p class="ofdlocked" role="status">${ic('lock', 's')}<span>${esc(tr('Finalised on {0} by {1}. It can no longer be changed; duplicate it for a new version.', d.locked_at ? ofdWhen(d.locked_at) : '', d.locked_by_name || '?'))}</span>${kind === 'invoice' && d.status !== 'cancelled' ? `<button type="button" class="btn sm" data-ofd="credit">${ic('receipt', 's')}<span>${tr('Credit note / cancel')}</span></button>` : ''}<button type="button" class="btn sm" data-ofd="dup">${ic('copy', 's')}<span>${tr('Duplicate')}</span></button></p>`
    : ro ? `<p class="ofdlocked" role="status">${ic('lock', 's')}<span>${esc(tr('Sent documents cannot be changed; duplicate it for a new version.'))}</span><button type="button" class="btn sm" data-ofd="dup">${ic('copy', 's')}<span>${tr('Duplicate')}</span></button></p>` : '';
  const paySec = kind === 'invoice' && lk ? ofdSec('pay', tr('Payments'), ofdPaymentsHtml(d, adm)) : '';
  const logSec = adm ? ofdSec('log', tr('History'), ofdLogHtml(d)) : '';
  const ln = OFD.langNotes && OFD.langNotes.id === d.id && !lk ? OFD.langNotes.notes : [];  // 2.40.0 (#1381): what the language switch left as it was
  const langNote = ln.length ? `<div class="ofdlnote" role="status">${ic('info', 's')}<span>${tr('Language changed. Standard texts were translated; these stayed as they were:')}<br>${ln.map(esc).join('<br>')}</span><button type="button" class="ib" data-ofd="ln-x" aria-label="${esc(tr('Close'))}">${ic('x', 's')}</button></div>` : '';
  return `${head}${banner}${kind === 'invoice' && typeof rinBox === 'function' ? rinBox(d) : '' /* 2.91.0 A (#1923) */}${typeof oa_docBanner === 'function' ? oa_docBanner(d) : ''}${ofd_cfBar(d) /* 2.269.0 A (#3012) */}${langNote}${typeof sg_box === 'function' ? sg_box(d) : ''}${typeof pep_box === 'function' ? pep_box(d) : '' /* 2.154.0 B (#1960) */}${vf ? '' : oil_linkHtml(d) /* 2.356.0 C (#3003); 2.351 vf: no links into the master data */}<div class="ofdeditor${kind === 'delivery' ? ' ofdls' : ''}" data-fg="ofd:${d.id}" data-fg-live><fieldset class="ofdfs" ${ro ? 'disabled' : ''}>${headSec}</fieldset>${!vf && typeof dpj_rowHtml === 'function' ? dpj_rowHtml(d) : '' /* 2.168.0 A (#2665): outside the locked fieldset; 2.356.0 C (#3005): below the head (client first) */}<fieldset class="ofdfs" ${ro ? 'disabled' : ''}>${`<section class="ofdsec open"><h3>${kind === 'reminder' ? tr('Reminded invoices') : tr('Positions')}</h3>${items}${auto}${totals}</section>${!vf && typeof tpPartsHtml === 'function' ? tpPartsHtml(d, adm) : ''}` /* 2.113.0 (#2248): parts open in place in "Parts" */}${kind === 'reminder' || kind === 'delivery' ? '' : kind === 'offer' || oil_hasRights(d) ? rightsSec : ro ? '' : `<button type="button" class="btn sm oil_rtadd" data-ofd="rights-add">${ic('plus', 's')}<span>${tr('Transfer of rights')}</span></button>` /* 2.356.0 C (#3005): an invoice shows it once it has rights */}${textsSec}${kind === 'reminder' ? '' : fieldsSec}</fieldset>${kind === 'offer' && typeof cf8_box === 'function' ? cf8_box(d) : '' /* 2.88.0 (#1915) */}${ofdFeeHtml(d, adm)}${paySec}${logSec}</div>`;  // 2.50.0 (#1200): sg_box = the approval link of a sent quotation
}
// 2.38.0 (#1021, F1): the invoices a reminder lists (read-only rows), the payments of an invoice
function ofdRefsHtml(d, t) {
  const rows = (t.lines || []).filter(l => l.kind === 'ref');
  if (!rows.length) return `<p class="muted">${tr('No invoices chosen.')}</p>`;
  return `<ul class="ofdits ofdrefs" role="list">${rows.map(l => `<li class="ofdit ofdref"><span class="ofdpos muted">${ic('receipt', 's')}</span><span class="ofcn"><b><a href="#office/offers/${l.id}">${esc(l.number || '#' + l.id)}</a></b><small class="muted">${esc([l.date ? fmtDateLoc(l.date) : '', l.due_date ? tr('due {0}', fmtDateLoc(l.due_date)) : ''].filter(Boolean).join(' · '))}</small></span><b class="ofdlt">${esc(l.open_text || ofdMoney(l.open, d))}</b></li>`).join('')}</ul>`;
}
// 2.40.0 (#1368 point 8): the fee of a finalised reminder is an own open item (stays after the invoice is paid); admins waive it or mark it paid
function ofdFeeHtml(d, adm) {
  if (d.kind === 'invoice') return (d.fee_reminders || []).length ? `<p class="ofdfeeinfo muted">${esc(tr('Reminder fee still open: {0}', d.fee_reminders.map(f => `${f.number} (${ofdMoney(f.fee, d)})`).join(', ')))}</p>` : '';
  if (d.kind !== 'reminder' || !d.locked || !(+d.fee > 0)) return '';
  const st = d.fee_state || '', txt = {'': N_('open'), waived: N_('waived'), paid: N_('paid|fee'), cancelled: N_('cancelled with the invoice')}[st] || st;  // 2.355.0 D (#2846): + cancelled (final)
  const btn = (v, label) => `<button type="button" class="btn sm" data-ofd="fee" data-st="${v}">${esc(tr(label))}</button>`;
  return `<div class="ofdfeeinfo"><span>${esc(tr('Reminder fee {0}: {1}', ofdMoney(d.fee, d), tr(txt)))}</span>${adm && st !== 'cancelled' ? (st ? btn('', N_('Open again')) : btn('waived', N_('Waive fee')) + btn('paid', N_('Fee paid'))) : ''}</div>`;
}
function ofdPaymentsHtml(d, adm) {
  const ps = d.payments || [];
  const list = ps.length ? `<ul class="ofdits ofdpays" role="list">${ps.map(p => `<li class="ofdit ofdpay"><span class="ofdpos muted">${ic('check', 's')}</span><span class="ofcn"><b>${esc(ofdMoney(p.amount, d))}</b><small class="muted">${esc([p.reverses_id ? tr('Reversal') : p.reversed ? tr('Reversed') : '', p.date ? fmtDateLoc(p.date) : '', tr(OFD_PAY.find(x => x[0] === p.method)?.[1] || p.method), p.note, p.created_by_name].filter(Boolean).join(' · '))}</small></span>${adm && !p.reverses_id && !p.reversed ? `<button type="button" class="ib" data-ofd="pay-del" data-pid="${p.id}" aria-label="${esc(tr('Reverse payment'))}" title="${esc(tr('Reverse payment'))}">${ic('x', 's')}</button>` : ''}</li>`).join('')}</ul>` : `<p class="muted">${tr('No payments yet.')}</p>`;
  const sum = `<p class="ofdpaysum"><span>${tr('Paid: {0}', ofdMoney(d.paid || 0, d))}</span>${+d.credits ? `<span>${tr('Credited: {0}', ofdMoney(d.credits, d))}</span>` : ''}<b>${tr('Open: {0}', ofdMoney(d.open || 0, d))}</b>${+d.overpaid > 0 ? `<b>${tr('To pay back: {0}', ofdMoney(d.overpaid, d))}</b>` /* 2.355.0 A (#2847) */ : ''}</p>`;
  const cr = (d.credits_of || []).length ? `<p class="muted ofchint">${tr('Credit notes')}: ${d.credits_of.map(c => `<a href="#office/offers/${c.id}">${esc(c.number || tr('Draft'))}</a>`).join(', ')}</p>` : '';
  if (d.status === 'cancelled') return list + sum + cr;
  return list + sum + cr + (adm ? `<button type="button" class="btn sm" data-ofd="pay">${ic('plus', 's')}<span>${tr('Record payment')}</span></button>` : `<p class="muted ofchint">${tr('Only an admin of this organisation can record payments')}</p>`);  // 2.39.1 (#1210 N3)
}
function ofdItemsHtml(d, adm) {
  const its = d.items || [], inv = ofdIsInv(d);
  const taxes = OFC_TAXES.map(([v, n]) => [v, ofcTax(v)]);
  const rows = its.map((it, i) => {
    const mv = `<span class="ofdmv"><button type="button" class="ib" data-ofd="it-up" data-i="${i}" ${i === 0 ? 'disabled' : ''} aria-label="${esc(tr('Move up'))}">${ic('up', 's')}</button><button type="button" class="ib" data-ofd="it-down" data-i="${i}" ${i === its.length - 1 ? 'disabled' : ''} aria-label="${esc(tr('Move down'))}">${ic('down', 's')}</button><button type="button" class="ib" data-ofd="it-del" data-i="${i}" aria-label="${esc(tr('Remove'))}">${ic('x', 's')}</button></span>`;
    if (it.kind === 'heading') return `<li class="ofdit ofdhd"><span class="ofdpos muted">${ic('list', 's')}</span><input data-i="${i}" data-k="title" value="${esc(it.title)}" maxlength="500" placeholder="${esc(tr('Heading (category)'))}" aria-label="${esc(tr('Heading'))}">${mv}</li>`;
    if (it.kind === 'text') return `<li class="ofdit ofdtx"><span class="ofdpos muted">${ic('note', 's')}</span><textarea data-i="${i}" data-k="detail" rows="2" maxlength="4000" placeholder="${esc(tr('Text block'))}" aria-label="${esc(tr('Text block'))}">${esc(it.detail)}</textarea>${mv}</li>`;
    const line = (d.totals?.lines || []).find(l => (l.kind === 'item' || l.kind === 'discount') && l.id === it.id);
    if (it.kind === 'part' && typeof tpItemRow === 'function') return tpItemRow(it, i, d, line, mv);  // 2.47.0 (#1215): a part on the title page
    if (it.kind === 'discount') return `<li class="ofdit ofddisc"><span class="ofdpos">${line?.pos || ''}</span>
      <div class="ofditb"><input class="ofdtt" data-i="${i}" data-k="title" value="${esc(it.title)}" maxlength="500" placeholder="${esc(tr('Discount'))}" aria-label="${esc(tr('Discount'))}">
      <span class="ofdnums"><span class="muted">−</span><input data-i="${i}" data-k="rate" inputmode="decimal" class="numin ofdrate" value="${esc(ofdNumIn(it.rate))}" aria-label="${esc(tr('Amount'))}"><span class="muted">€</span>
      <select data-i="${i}" data-k="tax" aria-label="${esc(tr('VAT'))}">${taxes.map(([v, n]) => `<option value="${v}" ${it.tax === v ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select>
      <b class="ofdlt">${line ? esc(line.total_text || ofdMoney(line.total, d)) : ''}</b></span></div>${mv}</li>`;
    return `<li class="ofdit${it.agent_flag ? ' oa_flag' : ''}${it.producing && !inv ? ' ofdprod' : ''}"><span class="ofdpos">${line?.pos || ''}</span>
      <div class="ofditb"><input class="ofdtt" data-i="${i}" data-k="title" value="${esc(it.title)}" maxlength="500" placeholder="${esc(tr('Service'))}" aria-label="${esc(tr('Service'))}">
      <input class="ofddt" data-i="${i}" data-k="detail" value="${esc(it.detail)}" maxlength="4000" placeholder="${esc(tr('Detail (optional)'))}" aria-label="${esc(tr('Detail'))}">
      <span class="ofdnums">${it.unit === 'percent' ? ekUnitSel(it, i, d) + ekPctHtml(it, i, line, d) : `<input data-i="${i}" data-k="qty" inputmode="decimal" class="numin" value="${esc(ofdNumIn(it.qty))}" aria-label="${esc(tr('Quantity'))}">
      ${ekUnitSel(it, i, d)}
      <span class="muted">×</span><input data-i="${i}" data-k="rate" inputmode="decimal" class="numin ofdrate" value="${esc(ofdNumIn(it.rate))}" aria-label="${esc(ofcHome() === 'EUR' ? tr('Rate (EUR)') : tr('Rate ({0})', ofcHome()))}"><span class="muted">${ofcSym(ofcHome())}</span>`}
      <select data-i="${i}" data-k="tax" aria-label="${esc(tr('VAT'))}">${taxes.map(([v, n]) => `<option value="${v}" ${it.tax === v ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select>
      <b class="ofdlt">${line ? esc(line.total_text || ofdMoney(line.total, d)) : ''}</b></span>
      <span class="ofdflags">${inv ? '' : `<label class="chkl"><input type="checkbox" data-i="${i}" data-k="raw_fee" ${it.raw_fee ? 'checked' : ''}> ${tr('raw data')}</label>${prd_prodShown(d) ? `<label class="chkl ofdprodf${it.producing ? ' on' : ''}"><input type="checkbox" data-i="${i}" data-k="producing" ${it.producing ? 'checked' : ''}> ${d.producing_mode === 'amount' ? esc(prd_lbl(d.share_label, d) || tr('producing')) : tr('producing')}</label>` : ''}${PRD_SLOTS.filter(k => prd_slotShown(d, k)).map(k => `<label class="chkl"><input type="checkbox" data-i="${i}" data-k="in_${k}" ${it['in_' + k] ? 'checked' : ''}> ${esc(prd_slotName(d, k))}</label>`).join('')}<label class="chkl"><input type="checkbox" data-i="${i}" data-k="discountable" ${it.discountable ? 'checked' : ''}> ${tr('discount')}</label>`}
      ${adm ? `<label class="chkl ofdcost">${tr('Purchase')} <input data-i="${i}" data-k="cost" inputmode="decimal" class="numin" value="${esc(ofdNumIn(it.cost))}" aria-label="${esc(tr('External cost per unit (internal)'))}"></label>${it.margin != null ? `<span class="ofdmargin${it.margin < 0 ? ' neg' : ''}">${esc(tr('Surplus {0}', ofdMoney(it.margin, d)))}</span>` : ''}` : ''}</span>${typeof oa_flagHtml === 'function' ? oa_flagHtml(it, i) : ''}</div>${mv}</li>`;  // 2.51.0 A (#1348): an agent's marks
  }).join('');
  return `<ul class="ofdits" role="list">${rows}</ul><div class="ofdadd"><button type="button" class="btn sm pri" data-ofd="it-svc">${ic('plus', 's')}<span>${tr('Add service')}</span></button><button type="button" class="btn sm" data-ofd="it-head">${ic('list', 's')}<span>${tr('Heading')}</span></button><button type="button" class="btn sm" data-ofd="it-text">${ic('note', 's')}<span>${tr('Text block')}</span></button>${inv && d.kind !== 'delivery' ? `<button type="button" class="btn sm" data-ofd="it-disc">${ic('calc', 's')}<span>${tr('Discount')}</span></button>` : ''}</div>`;
}
// 2.114.3 (#2266): which positions the producing switch counts; in a part whether its producing values are the document's or its own
function ofdProdHint(d) {
  const p = d.tpPart;
  if (!p) return `<div class="shint ofdprodhint">${esc(d.kind === 'offer' ? tr('Applies to the positions of this page with a producing tick. Parts without an own setting take over the switch and calculate their producing themselves.') : tr('Applies to the positions with a producing tick.'))}</div>`;  // 2.298.0 A1 (#3186): behind the (i) of the switch
  const own = ['producing_on', 'prod_quotient', 'producing_rate'].some(k => (p.settings || {})[k] != null);
  return `<div class="shint ofdprodhint">${esc(tr('Applies to the positions of this part with a producing tick.'))}</div>
    <span class="tpprodsrc${own ? ' own' : ''}"><span class="rotag">${esc(own ? tr('own setting') : tr('like the document'))}</span>${own ? `<a href="#" role="button" class="btn sm" data-ofd="tp-prod-doc" data-pid="${p.id}">${esc(tr('Use the values of the document'))}</a>` : ''}</span>`;
}
// 2.114.4 B (#2270): the order confirmation block (place / date + the client's signature) per quotation: like the setting / on / off
function ofdAcceptHtml(d) {
  const set = d.accept_on == null ? d.accept_print : null;
  const opts = [['', tr('Like the settings ({0})', set ? tr('on') : tr('off'))], ['1', tr('On')], ['0', tr('Off')]];
  const cur = d.locked ? String(d.accept_print ? 1 : 0) : (d.accept_on == null ? '' : String(d.accept_on));
  return ofdF('accept_on', tr('Order confirmation with signature line'), `<select id="ofd-accept_on" data-f="accept_on">${(d.locked ? opts.slice(1) : opts).map(([v, n]) => `<option value="${v}" ${v === cur ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select>`);
}
function ofdAutoHtml(d, t) {
  const pOn = d.producing_on !== 0;  // 2.47.0 (#1645): the switches of the document, always shown (null = a document of 2.46: as before)
  // 2.138.5 (#2266 x #2251): in a part the switch and its source (like the document / own setting + reset) always show
  const pShow = prd_prodShown(d) || !!d.tpPart, share = d.producing_mode === 'amount', slots = PRD_SLOTS.filter(k => prd_slotShown(d, k));  // 2.113.1 (#2251, #2252)
  const lines = (t.lines || []).filter(l => ['producing', 'surcharge', 'raw', 'discount'].includes(l.kind));
  const prod = lines.find(l => l.kind === 'producing'), raw = lines.find(l => l.kind === 'raw'), disc = lines.find(l => l.kind === 'discount'), surs = lines.filter(l => l.kind === 'surcharge');
  const pTitle = share ? prd_lbl(d.share_label, d) || t.labels?.producing || 'Producing' : t.labels?.producing || 'Producing';
  const rowL = (title, detail, total) => `<li class="ofdauto"><span class="ofdpos muted">${ic('calc', 's')}</span><span class="ofcn"><b>${esc(title)}</b>${detail ? `<small class="muted">${esc(detail)}</small>` : ''}</span><b class="ofdlt">${esc(total)}</b></li>`;
  return `<ul class="ofdits ofdautos" role="list">
    ${prod ? rowL(prod.title, prod.detail, prod.total_text || ofdMoney(prod.total, d)) : pOn && pShow ? rowL(pTitle, share ? tr('no position is marked for {0}', pTitle) : tr('no position counts towards producing'), '') : ''}
    ${surs.map(x => rowL(x.title, x.detail, x.total_text || ofdMoney(x.total, d))).join('')}
    ${raw ? rowL(raw.title, raw.detail, raw.total_text || ofdMoney(raw.total, d)) : ''}
    ${disc ? rowL(disc.title, disc.detail, disc.total_text || ofdMoney(disc.total, d)) : ''}</ul>
    <div class="ofdgrid ofdrules">
    ${ofdF('raw_mode', tr('Raw data'), ofdSel('raw_mode', d.raw_mode, OFD_RAW.map(([v, n]) => [v, tr(n)])))}
    ${d.raw_mode !== 'none' ? ofdF('raw_factor', tr('Raw data factor'), ofdIn('raw_factor', ofdNumIn(d.raw_factor), {num: true, max: 10}), tr('share of the positions with raw data')) : ''}
    ${pShow ? `<div class="row"><label class="chkl" style="min-width:0"><input type="checkbox" id="ofd-producing_on" data-f="producing_on" ${pOn ? 'checked' : ''}> ${share ? esc(tr('Calculate {0}', pTitle)) : tr('Calculate producing')}</label>${ofdProdHint(d)}</div>` : ''}
    ${pOn && pShow && share ? `<div class="row"><label for="ofd-prod_quotient">${esc(tr('Factor'))}</label>${ofdIn('prod_quotient', ofdNumIn(d.prod_quotient), {num: true, max: 10})}<div class="shint">${esc(tr('days = amount of the marked positions ÷ day rate × factor, rounded to half days'))}</div></div>
    ${ofdF('producing_rate', tr('Day rate'), ofdIn('producing_rate', ofdNumIn(d.producing_rate), {num: true, max: 12}), ofcSym(ofcHome()), {keep: 1})}` : ''}
    ${pOn && pShow && !share ? `${ofdF('prod_quotient', tr('Producing quotient'), ofdIn('prod_quotient', ofdNumIn(d.prod_quotient), {num: true, max: 10}), tr('production days per producing day'))}
    ${ofdF('producing_rate', tr('Producing rate'), ofdIn('producing_rate', ofdNumIn(d.producing_rate), {num: true, max: 12}), ofcSym(ofcHome()), {keep: 1})}` : ''}
    ${slots.map(k => `<div class="row"><label class="chkl" style="min-width:0"><input type="checkbox" id="ofd-${k}_on" data-f="${k}_on" ${d[k + '_pct'] != null ? 'checked' : ''}> ${esc(tr('Calculate {0}', prd_slotName(d, k)))}</label></div>
    ${d[k + '_pct'] != null ? `${ofdF(k + '_label', tr('Line title'), ofdIn(k + '_label', prd_slotName(d, k), {max: 80}))}
    ${ofdF(k + '_pct', tr('Percent'), ofdIn(k + '_pct', ofdNumIn(d[k + '_pct']), {num: true, max: 8}), tr('on the marked positions'))}
    ${k === 'markup' ? `<div class="row"><label class="chkl" style="min-width:0"><input type="checkbox" id="ofd-markup_stacked" data-f="markup_stacked" ${d.markup_stacked ? 'checked' : ''}> ${esc(tr('Also on the handling costs'))}</label></div>` : ''}` : ''}`).join('')}
    ${ofdF('discount_pct', tr('Discount'), ofdIn('discount_pct', ofdNumIn(d.discount_pct), {num: true, max: 8}), '%', {keep: 1})}
    </div>`;
}
function ofdTotalsHtml(d, t, adm) {
  const L = t.labels || {};
  if (ofdIsInv(d)) {  // 2.38.0: invoice sums are exact strings; subtotal, tax per rate, total, paid / open
    // 2.355.0 D (#2846): + default interest per invoice and the flat fee (the same rows as the PDF)
    const rmx = d.kind === 'reminder' ? [...(t.lines || []).filter(l => l.kind === 'ref' && +l.interest > 0).map(l => [tr('Default interest {0}: {1} % p.a., {2} days|document', l.number || '', fmtNum(+t.interest_rate || 0, 2), l.interest_days || 0), l.interest_text || ofdMoney(l.interest, d), 'tax']),
      ...(+t.flat_fee > 0 ? [[tr('Flat fee for late payment (section 288 (5) BGB)|document'), t.flat_fee_text || ofdMoney(t.flat_fee, d), 'tax']] : [])] : [];
    const rows = d.kind === 'reminder' ? [[tr('Amount outstanding'), ofdMoney(t.net || 0, d), 'net'], ...rmx, ...(+t.fee ? [[tr('Reminder fee'), ofdMoney(t.fee, d), 'tax']] : []), [tr('Total'), ofdMoney(t.gross || 0, d), 'gross']]
      : [[tr('Subtotal'), ofdMoney(t.net || 0, d), 'net'], ...(t.tax_lines || []).map(x => [x.label, x.amount_text || ofdMoney(x.amount, d), 'tax']), [tr('Total'), ofdMoney(t.gross || 0, d), 'gross']];
    if (d.kind === 'invoice' && d.locked && (+d.paid || +d.credits)) rows.push([tr('Amount outstanding'), ofdMoney(d.open || 0, d), 'open']);
    if (d.kind === 'invoice' && d.locked && +d.overpaid > 0) rows.push([tr('To pay back'), ofdMoney(d.overpaid, d), 'open']);  // 2.355.0 A (#2847): overpaid
    return `<div class="ofdtotals" id="ofd-totals"><dl>${rows.map(([k, v, c]) => `<div class="ofdtr tr-${c}"><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('')}</dl>
      <p class="muted ofdnote">${esc(t.vat_note || '')}${t.fx_note ? ` · ${esc(t.fx_note)}` : ''}${t.tax_eur_text ? ` · ${esc((t.home || 'EUR') === 'EUR' ? tr('tax in EUR: {0}', t.tax_eur_text) : tr('tax in {0}: {1}', t.home, t.tax_eur_text))}` : ''}</p>
      ${adm && t.costs != null && d.kind !== 'reminder' ? `<p class="muted ofdint">${ic('eye', 's')} ${tr('Internal: external costs {0}, surplus {1}', ofdMoney(t.costs, d), ofdMoney(t.margin, d))}</p>` : ''}</div>`;
  }
  const rows = [[L.net || tr('Net total'), ofdMoney(t.net || 0, d), 'net']];
  if (t.net_incl_raw != null) rows.push([L.net_incl_raw, ofdMoney(t.net_incl_raw, d), 'incl']);
  if (t.net_excl_raw != null) rows.push([L.net_excl_raw, ofdMoney(t.net_excl_raw, d), 'excl']);
  for (const x of t.tax_lines || []) rows.push([x.label, ofdMoney(x.amount, d), 'tax']);
  if (d.vat_mode !== 'novat') rows.push([L.gross || tr('Gross total'), ofdMoney(t.gross || 0, d), 'gross']);
  return `<div class="ofdtotals" id="ofd-totals"><dl>${rows.map(([k, v, c]) => `<div class="ofdtr tr-${c}"><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('')}</dl>
    <p class="muted ofdnote">${esc(t.vat_note || '')}${t.fx_note ? ` · ${esc(t.fx_note)}` : ''}</p>
    ${adm && t.costs != null ? `<p class="muted ofdint">${ic('eye', 's')} ${tr('Internal: external costs {0}, surplus {1}', ofdMoney(t.costs, d), ofdMoney(t.margin, d))}</p>` : ''}
    ${adm && d.items_margin != null ? `<p class="muted ofdint ofdmsum">${tr('Surplus of the positions: {0}', ofdMoney(d.items_margin, d))}</p>` : ''}</div>`;
}
// 2.47.0 (#1649): a position of unit "percent" (e.g. artists' social insurance): its rate in % of the positions marked extern
const ekUnits = () => OFC_UNITS.some(u => u[0] === 'percent') ? OFC_UNITS : [...OFC_UNITS, ['percent', '%']];
// 2.138.0 A (#2236): the unit choice also in a percent row (before the rate), so it can be switched back to day / piece / ...
const ekUnitSel = (it, i, d) => `<select data-i="${i}" data-k="unit" aria-label="${esc(tr('Unit'))}">${ekUnits().map(([v, n]) => `<option value="${v}" ${it.unit === v ? 'selected' : ''}>${ofu_label(v, it.qty, d)}</option>`).join('')}</select>`;  // 2.138.0 A (#2249): option text by quantity
const ekPctHtml = (it, i, line, d) => `<input data-i="${i}" data-k="rate" inputmode="decimal" class="numin ofdrate" value="${esc(ofdNumIn(it.rate))}" aria-label="${esc(tr('Rate in percent'))}"><span class="muted">%</span>`
  + `<span class="muted ofdpctof">${esc(tr('of {0} external', ofdMoney(line?.base ?? 0, d)))}</span>`;

// 2.138.0 E (#2235): the quotation's next step in the bar: draft -> Finalise (the button behind), finalised -> Mark as sent,
// sent -> Accepted / Declined, accepted -> Create invoice. Before acceptance the invoice asks once (no lock).
// 2.144.7 (#2572): "Create invoice" is always a visible button (main button once accepted, a plain one before), no longer in "…"
function kvaNextHtml(d, lk, ro) {
  const st = (v, icon, label, cls = '') => `<button type="button" class="btn sm ofdnext${cls}" data-ofd="kva-st" data-st="${v}" aria-label="${esc(tr(label))}" title="${esc(tr(label))}">${ic(icon, 's')}<span>${tr(label)}</span></button>`;
  const acc = d.status === 'accepted';
  const inv = `<button type="button" class="btn sm${acc ? ' pri' : ''} ofdnext ofdtoinv" data-ofd="to-invoice" aria-label="${esc(tr('Create invoice'))}" title="${esc(tr('An invoice draft with the positions of this quotation'))}">${ic('receipt', 's')}<span>${tr('Create invoice')}</span></button>`;
  if (d.status === 'sent') return st('accepted', 'check', N_('Accepted|document'), ' pri') + st('declined', 'x', N_('Declined')) + inv;
  if (d.status === 'draft' && (lk || ro)) return st('sent', 'send', N_('Mark as sent'), ' pri') + inv;
  return inv;  // accepted: the main button; a draft that can be edited ("Finalise" behind) or declined: a plain one
}
async function kvaToInvoice(d, row) {
  if (row) try { d = await api('GET', `/api/office/docs/${d.id}`); } catch (x) { toast(x.message || tr('unknown')); return; }  // 2.144.7 (#2572): a list row lacks parts / currency
  const have = oil_open(d);  // 2.356.0 C (#3003): an invoice of this quotation exists -> one question (it replaces the "not accepted" one)
  if (have.length) { if (!await askConfirm(tr('This quotation already has an invoice ({0}). Create another one?', have.map(x => x.number || tr('Draft')).join(', ')), '', {ok: tr('Create another invoice')})) return; d = {...d, oil_force: true}; }
  else if (d.status !== 'accepted' && !await askConfirm(tr('The offer has not been accepted yet. Create the invoice anyway?'), '', {ok: tr('Create invoice')})) return;
  absInvoiceDialog(d);  // 2.120.0 A (#2087): full / progress / final (a quotation with parts: full -> tpInvoiceDialog)
}
// 2.356.0 C (#3003): the quotation <-> its invoices (server: office/offerlink.py)
const oil_open = d => (d?.offer_invoices || []).filter(x => x.state !== 'cancelled' && !x.inv_type);
function oil_linkHtml(d) {
  if (d.kind === 'invoice' && d.source_offer) return `<p class="oil_link muted">${ic('file', 's')}<span>${esc(tr('From quotation'))} <a href="#office/offers/${d.source_offer.id}">${esc(d.source_offer.number || tr('Draft'))}</a></span></p>`;
  const xs = d.kind === 'offer' ? d.offer_invoices || [] : [];
  if (!xs.length) return '';
  return `<p class="oil_link muted">${ic('receipt', 's')}<span>${esc(tr('Invoices for this quotation'))}: ${xs.map(x => `<a href="#office/offers/${x.id}">${esc(x.number || tr('Draft'))}</a> <small class="rotag st-${esc(x.state)}">${esc(x.status_text)}</small>`).join(', ')}</span></p>`;
}
// 2.356.0 C (#3005): an invoice shows "Transfer of rights" only with rights (taken from the quotation or filled in) or after "+"
const oil_hasRights = d => OFD.rightsFor === d.id || Object.values(d.rights || {}).some(v => v && (typeof v !== 'object' || v.id || v.text));
// 2.356.0 C (#3005): "New invoice" > "From a quotation…": the open quotations (not declined, no invoice yet); a click is "Create invoice"
async function oil_pickOffer() {
  let rows; try { rows = (await api('GET', '/api/office/docs?kind=offer')).docs || []; } catch (x) { toast(x.message || tr('unknown')); return; }
  rows = rows.filter(r => r.status !== 'declined' && !r.invoiced).sort((a, b) => (b.status === 'accepted') - (a.status === 'accepted'));
  const md = modal(`<h3>${esc(tr('Invoice from a quotation'))}</h3>${rows.length ? `<ul class="ofdpick oil_pick" role="list">${rows.map(r => `<li><button type="button" class="ofcrow" data-oil-pick="${r.id}"><span class="ofcn"><b>${esc(r.number || tr('(no number)'))}${r.recipient_name ? ` · ${esc(r.recipient_name)}` : ''}</b><small class="muted">${esc([r.project_title, r.date ? fmtDateLoc(r.date) : '', r.status_text].filter(Boolean).join(' · '))}</small></span><span class="ofdsum"><b>${esc(r.net_text)}</b><small class="muted">${esc(tr('net'))}</small></span></button></li>`).join('')}</ul>` : `<p class="muted">${esc(tr('No open quotations.'))}</p>`}<div class="foot"><span class="spacer"></span><button type="button" class="btn" data-m="close">${tr('Cancel')}</button></div>`);
  md.addEventListener('click', e => {
    if (e.target.closest('[data-m="close"]')) { md.remove(); return; }
    const b = e.target.closest('[data-oil-pick]'); if (!b) return;
    const r = rows.find(x => String(x.id) === b.dataset.oilPick); md.remove(); if (r) kvaToInvoice(r, true);
  });
}
// the invoice from quotation d (b: parts_mode / inv_type ...); another person or an agent made one meanwhile -> the server's 409 asks once
async function oil_post(d, b) {
  const call = extra => ofdRefCall(`inv${d.id}`, ref => rawFetch('POST', `/api/office/docs/${d.id}/invoice`, {...b, ...(d.oil_force ? {force: true} : {}), ...extra, client_ref: ref}));
  try { return await call({}); } catch (x) {
    if (x.data?.code !== 'invoice_exists' || d.oil_force) throw x;
    if (!await askConfirm(x.message, '', {ok: tr('Create another invoice')})) return null;
    return call({force: true});
  }
}

// ---- the history (organisation admins; office log of this document)
const OFD_ACTIONS = {create: N_('created'), update: N_('changed'), items: N_('positions changed'), number: N_('number set'), status: N_('status changed'),
  finalize: N_('finalised'), unlock: N_('finalising undone'), duplicate: N_('created as a copy'), cashflow: N_('cash flow choice changed'), delete: N_('deleted'), open: N_('opened'), pdf: N_('PDF opened'), render: N_('preview opened'),
  export: N_('exported'), import: N_('imported'), archive: N_('archived'), upload: N_('uploaded'),
  payment: N_('payment recorded'), payment_delete: N_('payment reversed'), send: N_('sent by e-mail'), datev: N_('sent to the DATEV inbox'), undo: N_('import undone'), reminder_fee: N_('reminder fee waived / paid / open again / cancelled'), recovery_key: N_('recovery key shown'),
  agent_read: N_('read (agent)'), agent_write: N_('drafted (agent)'), from_sheet: N_('created from a table'), restore: N_('restored|office log')};  // 2.113.2 (#2253): + restore  // 2.89.0 (#1916, D): + from_sheet  // 2.51.0 A (#1348)  // 2.42.0 (#828): + recovery_key  // 2.39.1 (#1182): + undo; 2.40.0 (#1368): + reminder_fee
const ofdActText = a => tr(OFD_ACTIONS[a] || a);
const ofdWhen = iso => { try { return new Date(iso).toLocaleString(LOCALE(), {dateStyle: 'short', timeStyle: 'short'}); } catch { return iso || ''; } };
function ofdLogHtml(d) {
  if (!OFD.open.log) return `<p class="muted">${tr('Open to load the history.')}</p>`;
  if (OFD.logFor !== d.id || !OFD.log) { setTimeout(() => ofdLoadLog(d.id), 0); return `<p class="muted lempty">${tr('Loading…')}</p>`; }
  if (!OFD.log.length) return `<p class="muted">${tr('No entries yet.')}</p>`;
  return `<ul class="ofdlog" role="list">${OFD.log.map(x => { const ks = Object.keys(x.detail?.after || {}); return `<li><span class="muted">${esc(ofdWhen(x.at))}</span> <b>${esc(x.user_name || x.detail?.name || '?')}</b> ${esc(ofdActText(x.action))}${ks.length && x.action === 'update' ? ` <span class="muted">(${esc(ks.join(', '))})</span>` : ''}${typeof agbLogNote === 'function' ? agbLogNote(x) : ''}</li>`; }).join('')}</ul>`;
}
async function ofdLoadLog(id) {
  if (OFD.logLoading) return;
  OFD.logLoading = true;
  try { const j = await api('GET', `/api/office/docs/${id}/log`); OFD.log = j.log || []; OFD.logFor = id; }
  catch (x) { OFD.log = []; OFD.logFor = id; }
  OFD.logLoading = false; ofdDraw();
}

// ---- saving
// 2.40.0 (#1366): the PDF opens in the browser; the Android app's WebView shows no PDF itself, there the link downloads as before
// 2.138.2 A (#2393): the PDF of a document not yet finalised: asked first ("Finalise now" = the normal finalising, then the
// PDF; "Show as draft" = the PDF the server marks DRAFT on every page). A finalised, sent or read-only one opens as before.
const ofdPdfView = d => ({url: ofdPdfUrl(d.id, true), name: (d.number || tr('Document')) + '.pdf', dlUrl: ofdPdfUrl(d.id)});
function ofdPdfOpen(d, dl) {
  if (!dl && typeof pdfView === 'function') { pdfView(ofdPdfView(d)); return; }
  const a = document.createElement('a'); a.href = ofdPdfUrl(d.id, !dl);
  if (dl) a.download = ''; else { a.target = '_blank'; a.rel = 'noopener'; }
  document.body.appendChild(a); a.click(); a.remove();
}
function ofdPdfAsk() {
  return new Promise(res => {
    let done = false;
    const md = modal(`<h3 id="ofdpa-t">${esc(tr('This document is not finalised yet'))}</h3><div class="cdlg-b" id="ofdpa-b">${esc(tr('Finalise it now: number, positions, sums, sender and tax rates are frozen. Or look at it as a draft: every page is marked DRAFT.'))}</div>
      <div class="foot"><button type="button" class="btn" data-pa="">${esc(tr('Cancel'))}</button><span class="spacer"></span><button type="button" class="btn" data-pa="draft">${esc(tr('Show as draft'))}</button><button type="button" class="btn pri" data-pa="final">${ic('lock', 's')} ${esc(tr('Finalise now'))}</button></div>`);
    md.classList.add('cdlg', 'ofdpa');
    md.setAttribute('role', 'alertdialog'); md.setAttribute('aria-modal', 'true'); md.setAttribute('aria-labelledby', 'ofdpa-t'); md.setAttribute('aria-describedby', 'ofdpa-b');
    const prev = document.activeElement;
    const fin = v => { if (done) return; done = true; res(v); if (md.isConnected) md.remove(); try { if (prev && prev.isConnected) prev.focus({preventScroll: true}); } catch { /* gone */ } };
    md.addEventListener('click', e => { const b = e.target.closest('[data-pa]'); if (b) fin(b.dataset.pa || null); });
    onRemove(md, () => fin(null));
    setTimeout(() => $('[data-pa="draft"]', md)?.focus(), 30);
  });
}
// 2.154.0 D (#2567): duplicating an invoice made from times: say that the hours stay with the original
async function ofdDupAsk(d) {
  if (d.kind !== 'invoice' || !d.timesheet_ok) return true;
  return askConfirm(tr('Duplicate this invoice?'), tr('The hours of this invoice are already billed; the copy binds no times.'), {ok: tr('Duplicate')});
}

async function ofdPdfAskGo(d, dl) {
  const v = await ofdPdfAsk(); if (!v) return;
  if (v === 'final') {
    const j = await ofdSave('POST', `/api/office/docs/${d.id}/finalize`, {}); if (!j) return;  // the server's checks: the error stays as toast
    toast(tr('Finalised as {0}', j.number || '')); d = {...d, ...j};
  }
  ofdPdfOpen(d, dl);
}
const ofdPdfUrl = (id, inline) => `${OFD.viaFolder.has(id) ? '/api/fsref/office_doc' : '/api/office/docs'}/${id}/pdf${inline && !/; wv\)/.test(navigator.userAgent || '') ? '?inline=1' : ''}`;  // 2.199.0 B (#2742): + through a folder
// 2.269.0 A (#3012): the saves run one after another (never two PUT at once); those of the document's head, positions and parts
// carry the version they build on (expect_updated_at), a 409 shows the conflict bar instead of overwriting the other one's save.
// src = the local positions sent: a line added by one save is sent with its new id by the next one (no double line)
const ofd_verUrl = url => !!OFD.doc && new RegExp(`^/api/(office/docs/${OFD.doc.id}(/items|/parts(/\\d+(/items)?)?)?|fsref/office_doc/${OFD.doc.id}(/items)?)$`).test(url);  // 2.351.0 F (#2823, review M4): + the folder way
// 2.351.0 F (#2823, review M4): a document reached through a folder keeps that mark after a save / a conflict (the answers
// of the folder way carry no folder role): read-only office menu, no delete / unlock
const ofd_viaDoc = (j, role) => ({...j, folder_role: role, can_edit: role === 'edit' && !j.locked && j.can_edit !== false, can_delete: false, can_unlock: false, via_folder: true});
const ofd_keepVia = j => OFD.doc?.via_folder && j && j.id === OFD.doc.id ? ofd_viaDoc(j, OFD.doc.folder_role) : j;
// 2.351.0 A (#2823): a draft reached only through a folder share with edit saves over the folder way (office/docref.py: the
// document's own fields and positions; links into the master data are refused there)
const ofd_viaUrl = url => { const m = String(url).match(/^\/api\/office\/docs\/(\d+)(\/items)?$/); return m && OFD.viaFolder.has(+m[1]) ? `/api/fsref/office_doc/${m[1]}${m[2] || ''}` : url; };
const ofdSave = (method, url, body, src) => ofd_inChain(() => ofd_save1(method, ofd_viaUrl(url), body, src));
// a save outside ofdSave (the calculation sheet) in the same row; ofd_ver = its version field
const ofd_inChain = fn => { const p = (OFD.chain || Promise.resolve()).then(fn, fn); OFD.chain = p.catch(() => { /* the caller reports it */ }); return p; };
const ofd_ver = () => OFD.doc?.updated_at ? {expect_updated_at: OFD.doc.updated_at} : {};
async function ofd_save1(method, url, body, src) {
  OFD.saving++; ofdSaveHint();
  const ver = ofd_verUrl(url) && body && typeof body === 'object' && !Array.isArray(body) ? OFD.doc.updated_at : null;
  if (ver) {
    if (src && Array.isArray(body.items)) body.items.forEach((x, i) => { if (!x.id && src[i]?.id) x.id = src[i].id; });
    body = {...body, expect_updated_at: ver};
  }
  try {
    const j = await rawFetch(method, url, body);
    if (src && j) { const its = (j.part ? j.part.items : j.items) || []; src.forEach((x, i) => { if (!x.id && its[i]?.id) x.id = its[i].id; }); }
    if (OFD.doc && j && j.id === OFD.doc.id) OFD.doc = ofd_keepVia(j.items ? j : {...OFD.doc, ...j}); /* the status answer has no positions */ OFD.err = ''; if (j && j.lang_notes) OFD.langNotes = {id: j.id, notes: j.lang_notes};
    if (!ver && method !== 'GET' && OFD.doc && j && !j.updated_at && url.startsWith(`/api/office/docs/${OFD.doc.id}/`)) {  // a status / number / payment answer without the version: the current state
      try { const f = await rawFetch('GET', `/api/office/docs/${OFD.doc.id}`); if (OFD.doc && f && f.id === OFD.doc.id) OFD.doc = f; } catch { /* the next save reports it */ }
    }
    return j;
  }
  catch (x) {
    if (x.status === 409 && x.data?.doc && OFD.doc && x.data.doc.id === OFD.doc.id) { OFD.conflict = {id: OFD.doc.id, doc: x.data.doc}; OFD.err = ''; return null; }
    OFD.err = x.message || tr('unknown'); toast(OFD.err); return null;
  }
  finally { OFD.saving--; OFD.log = null; ofdDraw(); OFD.list = null; }
}
// 2.269.0 A (#3012): the conflict bar (no merging, decision 23.10.2026): "Reload" shows the stored state, the own unsaved change is named
const ofd_cfBar = d => OFD.conflict && OFD.conflict.id === d.id ? `<div class="ofdlnote ofdcf" role="alert">${ic('info', 's')}<span><b>${esc(tr('Changed in the meantime'))}</b><br>${esc(tr('Someone else saved this document in the meantime. Your last change was not saved; reload to see the current version.'))}</span><button type="button" class="btn sm" data-ofd="cf-reload">${esc(tr('Reload'))}</button></div>` : '';
function ofd_cfReload() {
  const cf = OFD.conflict; OFD.conflict = null;
  if (cf && OFD.doc && cf.id === OFD.doc.id) OFD.doc = ofd_keepVia(cf.doc);
  OFD.log = null; ofdDraw();
  if (OFD.doc) ofdLoadDoc(OFD.doc.id, true);  // and once more from the server (another save may have come since)
}
function ofdSaveHint() { const s = $('.ofdsave'); if (s) s.textContent = OFD.saving ? tr('Saving…') : ''; }
const ofdPatch = body => typeof tpView === 'function' && tpView() ? tpPatch(body) : ofdSave('PATCH', `/api/office/docs/${OFD.doc.id}`, body);
// 2.114.1 A (#2254): a new heading / text line stays local until something is typed; the server would reject it empty (a saved
// one keeps its id and is sent as before, emptying it never drops it silently)
const bfaFilled = it => it.id || !((it.kind === 'heading' || it.kind === 'text') && !(it.title || '').trim() && !(it.detail || '').trim());
function ofdItemsBody() {
  return (OFD.doc.items || []).filter(bfaFilled).map(it => ({id: it.id, kind: it.kind, service_id: it.service_id, title: it.title, detail: it.detail, qty: it.qty, unit: it.unit, rate: it.rate, tax: it.tax,
    raw_fee: it.raw_fee, producing: it.producing, in_handling: it.in_handling, in_markup: it.in_markup, intext: it.intext, cost: it.cost, discountable: it.discountable, ref_part_id: it.ref_part_id, confirm: it.confirm || undefined}));  // 2.47.0 (#1215): + ref_part_id; 2.51.0 A (#1348): + confirm (an agent's mark)
}
// 2.47.0 (#1215): with a part open, positions and calculation values go to the part (office_parts.js)
const ofdPutItems = () => typeof tpView === 'function' && tpView() ? tpPutItems() : ofdSave('PUT', `/api/office/docs/${OFD.doc.id}/items`, {items: ofdItemsBody(), ...(OFD.doc.kind === 'offer' ? {parts_known: (OFD.doc.parts || []).map(p => p.id)} : {})}, (OFD.doc.items || []).filter(bfaFilled));  // 2.138.0 A (#2239): + parts_known; 2.269.0 A (#3012): + the lines sent
function ofdRightsBody() {
  const r = OFD.doc.rights || {}, g = id => $('#ofd-' + id);
  const dim = k => ({id: g('r-' + k)?.value ? +g('r-' + k).value : null, text: g('r-' + k + '-t')?.value ?? r[k]?.text ?? ''});
  return {time: dim('time'), territory: dim('territory'), media: dim('media'), exceptions: g('r-exceptions')?.value ?? r.exceptions, exclusive: g('r-exclusive')?.checked ? 1 : 0, note: g('r-note')?.value ?? r.note};
}

// ---- events (delegated on the tab's body)
function ofdInput(e) {
  const t = e.target;
  if (t.dataset?.k === 'qty' && t.dataset.i != null && OFD.doc) { ofu_sync(t, typeof tpCur === 'function' ? tpCur() : OFD.doc); return; }  // 2.138.0 A (#2249)
  if (t.id === 'ofd-q') { OFD.q = t.value; const el = t.closest('.pboffers, .ofcbody'); if (el) keepFocus(el, () => fl_set(el, ofdListHtml())); }
}
function ofdKey(e) { if (e.key === 'Enter' && e.target.id === 'ofd-q') e.preventDefault(); }
async function ofdChange(e) {
  const t = e.target;
  if (t.id === 'ofd-trial') { OFD.trial = t.value; LS.set('ofdTrial', t.value); OFD.list = null; ofdLoadList(true); return; }  // 2.144.10 C (#2576)
  if (t.dataset.oflt && !S.route.id) { OFD.flt[t.dataset.oflt] = t.value; OFD.list = null; ofdLoadList(true); return; }  // 2.351.0 A (#3312)
  if (t.id === 'ofd-status' && !OFD.doc) { OFD.status = t.value; OFD.list = null; ofdLoadList(true); return; }
  if (t.id === 'ofd-status' && OFD.doc && S.route.id !== OFD.doc.id) { OFD.status = t.value; OFD.list = null; ofdLoadList(true); return; }
  if (!OFD.doc) return;
  if (typeof tpf_ctx === 'function') tpf_ctx(t);  // 2.113.0 (#2248): the open part the field belongs to
  if (t.dataset.tp && typeof tpChange === 'function') { await tpChange(t); return; }  // 2.47.0 (#1215): title / print of a part
  const d = typeof tpCur === 'function' ? tpCur() : OFD.doc;  // 2.47.0 (#1215): an open part's positions
  if (t.dataset.i != null && t.dataset.k) {  // a position
    const it = d.items[+t.dataset.i]; if (!it) return;
    const k = t.dataset.k;
    if (t.type === 'checkbox') it[k] = t.checked ? 1 : 0;
    else if (['qty', 'rate', 'cost'].includes(k)) { const v = ofcNum(t.value); it[k] = v == null ? (k === 'qty' ? 1 : 0) : v; }
    else it[k] = t.value;
    if (k === 'unit' && it.unit !== 'percent' && !(+it.qty > 0)) it.qty = 1;  // 2.138.0 A (#2236): back from percent: quantity 1 when empty / 0
    await ofdPutItems(); return;
  }
  if (t.dataset.fld != null) {  // own fields
    const f = d.fields[+t.dataset.fld]; if (!f) return;
    f[t.dataset.k] = t.value; await ofdPatch({fields: d.fields}); return;
  }
  const f = t.dataset.f; if (!f) return;
  if (f === 'status') {
    if (ofdIsInv(d) && t.value === 'paid' && !await askConfirm(tr('Mark as paid without a payment?'), tr('Record a payment to keep the amounts; this only sets the status.'), {ok: tr('Mark as paid')})) { ofdDraw(); return; }
    const j = await ofdSave('POST', `/api/office/docs/${d.id}/status`, {status: t.value}); if (j) { d.status = j.status; d.state = j.state; d.status_text = j.status_text; d.sent_at = j.sent_at; d.paid_at = j.paid_at; d.can_edit = j.can_edit; if (j.cf_chain) d.cf_chain = j.cf_chain; ofdDraw(); } return;  // 2.88.0 (#1915): cf_chain
  }
  if (f.startsWith('r-')) {
    const k = f.slice(2);
    if (['time', 'territory', 'media'].includes(k)) {  // a catalogue choice takes the catalogue's text
      const tx = $('#ofd-r-' + k + '-t'); if (tx && t.value) tx.value = ofcText(+t.value, ofdLang(d));
    }
    await ofdPatch({rights: ofdRightsBody()}); return;
  }
  if (f === 'intro_pick' || f === 'closing_pick') { if (!t.value) return; const k = f.replace('_pick', ''); const ta = $('#ofd-' + k); const v = ofcText(+t.value, ofdLang(d)); if (ta) ta.value = v; await ofdPatch({[k]: v}); return; }
  if (f === 'recipient_name' || f === 'recipient_lines') { await ofdPatch({recipient: {name: $('#ofd-recipient_name')?.value ?? d.recipient?.name, lines: ($('#ofd-recipient_lines')?.value ?? (d.recipient?.lines || []).join('\n')).split('\n')}}); return; }
  if (f === 'client_id') { await ofdPatch({client_id: t.value ? +t.value : null, recipient_from_client: !!t.value}); return; }
  if (f === 'contract_id') { await ofdPatch({contract_id: t.value ? +t.value : null}); return; }
  if (f === 'producing_on') { await ofdPatch({producing_on: t.checked ? 1 : 0}); return; }  // 2.47.0 (#1645)
  if (f === 'accept_on') { await ofdPatch({accept_on: t.value === '' ? null : +t.value}); return; }  // 2.114.4 B (#2270)
  if (/^(handling|markup)_on$/.test(f)) { const k = f.slice(0, -3); await ofdPatch({[k + '_pct']: t.checked ? prd_opts()[k]?.pct ?? 0 : null}); return; }  // 2.113.1 (#2252)
  if (f === 'markup_stacked') { await ofdPatch({markup_stacked: t.checked ? 1 : 0}); return; }
  if (f === 'handling_pct' || f === 'markup_pct') { await ofdPatch({[f]: ofcNum(t.value) ?? 0}); return; }
  if (['fx_rate', 'raw_factor', 'prod_quotient', 'producing_rate', 'discount_pct', 'payment_days', 'reminder_level', 'reminder_fee', 'reminder_deadline_days', 'skonto_pct', 'skonto_days'].includes(f)) { const v = ofcNum(t.value, ['fx_rate', 'raw_factor', 'prod_quotient'].includes(f)); await ofdPatch({[f]: v}); return; }
  await ofdPatch({[f]: t.value});
}
// 2.87.9 (#1920): the "More" menu of a document - one list for the editor and for the rows of the list (d = the document or a list row)
function ofdMoreItems(d, inList) {
  const gone = () => { OFD.doc = null; OFD.list = null; if (inList) ofdLoadList(true); else go('office/offers'); };
  if (d.via_folder) return [{label: tr('Preview (PDF)'), icon: 'eye', fn: () => ofdPdfOpen(d, false)}];  // 2.199.0 B (#2742): read through a folder only
  const items = [
      !d.trial ? {label: tr('File in a folder…'), icon: 'folder', fn: () => ofd_fileDlg(d)} : null,  // 2.199.0 B (#2742)
      {label: tr('Duplicate'), icon: 'copy', fn: async () => { try { if (!await ofdDupAsk(d)) return; const j = await ofdRefCall(`dup${d.id}`, ref => rawFetch('POST', `/api/office/docs/${d.id}/duplicate`, {client_ref: ref})); OFD.list = null; OFD.doc = j; toast(tr('Copied as {0}', j.number || tr('Draft'))); go(`office/offers/${j.id}`); } catch (x) { toast(x.message || tr('unknown')); } }},
      d.kind === 'offer' && d.client_id && ofcAdmin() && typeof dtFromOffer === 'function' ? {label: tr('Create order confirmation'), icon: 'file', fn: () => dtFromOffer(d)} : null,  // 2.93.0 A (#1927)
      inList && d.kind === 'offer' ? {label: tr('Create invoice'), icon: 'receipt', fn: () => kvaToInvoice(d, true)} : null,  // 2.144.7 (#2572): in the list row menu; the editor has the button in its bar
      !inList ? null : {label: tr('Preview (PDF)'), icon: 'eye', fn: () => !inList && !d.locked && d.can_edit && d.status === 'draft' ? ofdPdfAskGo(d, false) : ofdPdfOpen(d, false)},  // 2.40.0 (#1364): the PDF, not the JSON print model; 2.138.2 A (#2393): a draft asks first (a list row opens marked); 2.356.0 C (#3005): the editor has its Preview button, the menu no second one
      ...(typeof ls_moreItems === 'function' ? ls_moreItems(d, inList) : []),  // 2.120.0 D (#2089)
      ofdIsInv(d) && d.kind !== 'reminder' && d.kind !== 'delivery' && d.locked && (ofcFeat('docs.einvoice') || d.xml_sha256) ? {label: tr('E-invoice XML'), icon: 'download', fn: () => window.open(`/api/office/docs/${d.id}/xml`, '_blank', 'noopener')} : null,
      ...(typeof pep_moreItems === 'function' ? pep_moreItems(d) : []),  // 2.154.0 B (#1960): send over Peppol, UBL
      ofdIsInv(d) && d.kind !== 'reminder' && d.kind !== 'delivery' && d.locked && ofcFeat('books.datev') ? {label: tr('Send to the DATEV inbox'), icon: 'send', fn: async () => { const j = await ofdSave('POST', `/api/office/docs/${d.id}/datev`); if (j) toast(tr('Sent to the DATEV inbox')); }} : null,
      d.status === 'draft' && !d.locked && typeof ofm_can === 'function' && ofm_can(ofm_officeFrom()) ? {label: tr('Move to another workspace…'), icon: 'brief',  // 2.97.0 C (#2049)
        fn: () => ofm_move({what: 'drafts', ids: [d.id], from: ofm_officeFrom(), label: qn(d.number || d.project_title || ofdKindName(d.kind, true)), after: async () => gone()})} : null,
      d.can_unlock ? {label: tr('Undo finalising'), icon: 'undo', fn: async () => {  // 2.114.2 A (#2263): a finalised quotation never sent
        if (!await askConfirm(tr('Back to a draft?'), tr('The quotation can be changed again and keeps its number {0}.', d.number || ''), {ok: tr('Undo finalising')})) return;
        try { const j = await rawFetch('POST', `/api/office/docs/${d.id}/unlock`); OFD.list = null; OFD.log = null; if (inList) ofdLoadList(true); else { OFD.doc = j; ofdDraw(); } toast(tr('Back to a draft')); } catch (x) { toast(x.message || tr('unknown')); }
      }} : null,
      d.kind === 'invoice' && d.status === 'cancelled' && d.time_billed?.entries && ofcAdmin() ? {label: tr('Release the time again'), icon: 'clock', fn: () => tbill_release(d)} : null,  // 2.144.6 A (#2053)
      d.can_delete ? '-' : null,
      d.can_delete ? {label: tr('Delete'), icon: 'trash', cls: 'danger', fn: async () => {
        if (d.delete_confirm && !d.trial) { await ofdInvDelete(d, gone); return; }  // 2.162.0 A (#2603): test phase, a finalised / sent invoice
        if (d.trial) { if (!await askConfirm(tr('Delete trial document?'), tr('{0} is a trial document and disappears for good.', d.number || ofdKindName(d.kind, true)), {ok: tr('Delete'), danger: true})) return; }  // 2.144.10 C (#2576)
        else if (!await askConfirm(tr('Delete {0}?', d.number || ofdKindName(d.kind, true)), (d.locked ? tr('Its number stays used and shows as a gap in the office log.') : tr('Its number stays used.')) + (d.delete_sent ? ' ' + tr('The quotation was sent; it disappears anyway.') : ''), {ok: tr('Delete'), danger: true})) return;  // 2.114.2 A (#2263); 2.144.8 (#2573): test phase, a sent one too
        try { const j = await api('DELETE', `/api/office/docs/${d.id}`); gone();  // 2.272.0 E2 (#3038): a draft goes to the office trash, the toast undoes it
          if (j?.trash_id) toast(tr('“{0}” moved to the trash', d.number || ofdKindName(d.kind, true)), () => otb_restore(j.trash_id)); else toast(tr('Deleted')); } catch (x) { toast(x.message || tr('unknown')); }
      }} : null];
  return inList ? [{label: tr('Open'), icon: 'edit', fn: () => go(`office/offers/${d.id}`)}, ...items] : items;
}
// 2.162.0 A (#2603): test phase - deleting a finalised / sent invoice: the number is typed (Delete stays off until it matches),
// the hint names what goes with it (the server sends delete_info); cash book entries only after a second question
async function ofdInvDelete(d, gone) {
  let info;  // 2.162.0 A (#2603 review): the hint is loaded for the dialog only (fresh, not with every document view)
  try { const j = await api('GET', `/api/office/docs/${d.id}?delete_info=1`); if (!j.can_delete) { toast(j.delete_block || tr('unknown')); return; } info = j.delete_info; }
  catch (x) { toast(x.message || tr('unknown')); return; }
  if (!info) return;
  const num = String(info.number || d.number || '');
  const lines = [tr('The number {0} stays used and shows as a gap in the office log.', num)];
  if (info.sent) lines.push(tr('The invoice was sent to the client.'));
  if (info.einvoice) lines.push(tr('It went out as an e-invoice.'));
  if (info.export) lines.push(tr('It is already in an accounting export (DATEV / CSV); correct it there as well.'));
  if (info.credits?.length) lines.push(tr('The cancellation invoice goes with it: {0}', info.credits.filter(Boolean).join(', ') || '-'));
  if (info.reminders?.length) lines.push(tr('Its reminders go with it: {0}', info.reminders.filter(Boolean).join(', ') || '-'));
  if (info.payments || info.bank) lines.push(tr('Its payments go with it; matched bank bookings are open again.'));
  if (info.time) lines.push(tr('The billed time entries are open again.'));
  if (info.cash_closed) lines.push(tr('Cash book entries on a closed day stay.'));
  const val = await askDialog({title: tr('Delete invoice {0}?', num), danger: true, ok: tr('Delete'),
    html: lines.map(x => `<p>${esc(x)}</p>`).join('') + `<p><b>${esc(tr('Type the number to confirm.'))}</b></p>`,
    input: {placeholder: num, max: 120},
    after: md => { const inp = $('#cdlg-in', md), btn = $('[data-cd="yes"]', md); const upd = () => { btn.disabled = inp.value.trim() !== num; }; inp.addEventListener('input', upd); upd(); }});
  if (val == null || String(val).trim() !== num) return;
  let cash = '';
  for (;;) {
    try {
      const j = await rawFetch('DELETE', `/api/office/docs/${d.id}?confirm_number=${encodeURIComponent(num)}${cash ? `&cash=${cash}` : ''}`);
      gone(); toast(j.cash_kept ? tr('Deleted; cash book entries on a closed day stay') : tr('Deleted')); return;
    } catch (x) {
      if (x.data?.code === 'cash' && !cash) {
        cash = await askConfirm(tr('Delete the cash book entries ({0}) too?', x.data.cash), tr('No: they stay in the cash book without the invoice.'), {ok: tr('Delete'), cancel: tr('No'), danger: true}) ? '1' : '0';
        continue;
      }
      toast(x.message || tr('unknown')); return;
    }
  }
}
// 2.87.9 (#1920): right click / long press on a row opens the same menu as the dots button
function ofdRowMenu(id, anchor) {
  const r = (OFD.list || []).find(x => String(x.id) === String(id)); if (!r) return;
  menu(anchor, ofdMoreItems({...r, can_delete: OFD.role === 'admin' && (r.can_delete || (!r.locked && r.status !== 'sent' && !(['invoice', 'credit'].includes(r.kind) && r.number)))}, true));  // 2.114.2 A (#2263): the server marks the finalised quotations that may go; 2.126.0 A (#1966): a numbered invoice / credit note draft stays
}
function ofdCtx(e) { const b = e.target.closest('.ofdrow'); if (!b) return; e.preventDefault(); ofdRowMenu(b.dataset.id, b); }
async function ofdClick(e) {
  if (typeof tpf_ctx === 'function') tpf_ctx(e.target);  // 2.113.0 (#2248): the open part the click happens in (also for the agent marks' own listener)
  const b = e.target.closest('[data-ofd]'); if (!b) return;
  const a = b.dataset.ofd, d = typeof tpCur === 'function' ? tpCur() : OFD.doc;  // 2.47.0 (#1215): an open part's positions
  const sc = typeof tpf_sc === 'function' ? tpf_sc() : '';  // 2.113.0 (#2248): focus inside that part after the redraw
  if (a === 'pdf') return;  // the link itself
  e.preventDefault();
  if (a === 'trash') { otb_open(); return; }  // 2.272.0 E2 (#3038)
  if (a === 'new') { tri_newDialog('offer'); return; }  // 2.144.10 C (#2576): a small dialog with "Just to try" (was: created at once)
  if (a === 'tri-del-all') { await tri_deleteAll(); return; }
  if (a === 'new-ls' || a === 'to-ls') return ls_click(a, d);  // 2.120.0 D (#2089)
  if (a === 'open') { if (typeof ms_lpRecent === 'function' && OFD.lp && ms_lpRecent(OFD.lp)) return; go(`office/offers/${b.dataset.id}`); return; }
  if (a === 'rowmore') { ofdRowMenu(b.dataset.id, b); return; }
  if (a === 'back') { OFD.doc = null; OFD.list = null; go('office/offers'); return; }
  if (a === 'kind') { OFD.kind = b.dataset.kind; OFD.status = ''; OFD.list = null; go(`office/offers/${OFD.kind}`); return; }  // 2.356.0 C (#3004): a history step per tab
  if (a === 'dun-open') { dun_open(); return; }  // 2.147.1 B (#2054): the suggested reminder drafts
  if (a === 'new-inv') {
    menu(b, [{label: tr('Empty invoice'), icon: 'plus', fn: () => tri_newDialog('invoice')}, {label: tr('From time entries…'), icon: 'clock', fn: ofdFromTimeDialog},
      {label: tr('From a quotation…'), icon: 'receipt', fn: oil_pickOffer}]);  // 2.356.0 C (#3005): a choice of the open quotations (was a text only)
    return;
  }
  if (a === 'remind') { ofdReminderDialog(); return; }
  if (!d) return;
  if (a === 'pdf-ask') { await ofdPdfAskGo(OFD.doc, !!b.dataset.dl); return; }  // 2.138.2 A (#2393)
  if (a.startsWith('tp-') && typeof tpClick === 'function') { await tpClick(a, b); return; }  // 2.47.0 (#1215): the parts
  if (a === 'to-invoice') { await kvaToInvoice(OFD.doc); return; }
  if (a === 'kva-st') { await ofdSave('POST', `/api/office/docs/${OFD.doc.id}/status`, {status: b.dataset.st}); return; }  // 2.138.0 E (#2235): the answer updates OFD.doc
  if (a === 'credit') {
    if (!await askConfirm(tr('Credit note for {0}?', d.number || ''), tr('A draft with all positions is made. Shorten it for a partial credit; finalised over the full amount it cancels the invoice.'), {ok: tr('Create credit note')})) return;
    try { const j = await ofdRefCall(`credit${d.id}`, ref => rawFetch('POST', `/api/office/docs/${d.id}/credit`, {client_ref: ref})); OFD.list = null; OFD.kind = 'credit'; OFD.doc = j; go(`office/offers/${j.id}`); } catch (x) { toast(x.message || tr('unknown')); } return;
  }
  if (a === 'pay') { ofdPaymentDialog(d); return; }
  if (a === 'pay-del') {  // 2.152.0 C (#2168): a payment is reversed by a second line (both stay visible), never deleted
    ofdDlg(tr('Reverse payment'), `<p class="muted">${esc(tr('A reversal line with the negative amount is booked; the payment stays visible.'))}</p>`
      + ofdF('p-rnote', tr('Reason (optional)'), `<input id="ofd-p-rnote" maxlength="500">`),
      tr('Reverse payment'), async md => { const j = await ofdSave('DELETE', `/api/office/docs/${d.id}/payments/${b.dataset.pid}`, {note: $('#ofd-p-rnote', md).value}); if (!j) return false; toast(tr('Payment reversed')); });
    return;
  }
  if (a === 'send') { ofdSendDialog(d); return; }
  if (a === 'ln-x') { OFD.langNotes = null; ofdDraw(); return; }
  if (a === 'rights-add') { OFD.rightsFor = d.id; OFD.open.rights = true; ofdDraw(); return; }  // 2.356.0 C (#3005)
  if (a === 'cf-reload') { ofd_cfReload(); return; }  // 2.269.0 A (#3012)
  if (a === 'fee') { const j = await ofdSave('POST', `/api/office/docs/${d.id}/fee`, {state: b.dataset.st || ''}); if (j) savedTick('.ofdfeeinfo > span'); return; }  // 2.298.0 A1 (#3186): the quiet tick
  if (a === 'it-disc') { d.items.push({kind: 'discount', title: '', detail: '', qty: 1, unit: 'flat', rate: 0, tax: 'standard', raw_fee: 0, producing: 0, intext: 'intern', cost: 0, discountable: 1}); await ofdPutItems(); $(`${sc}.ofdits [data-i="${d.items.length - 1}"][data-k="rate"]`)?.focus(); return; }
  if (a === 'number') { const j = await ofdSave('POST', `/api/office/docs/${d.id}/number`, {}); if (j) { d.number = j.number; ofdDraw(); } return; }
  if (a === 'finalize') {
    if (!await askConfirm(tr('Finalise this document?'), tr('Number, positions, sums, sender and tax rates are frozen. Afterwards it can only be duplicated.'), {ok: tr('Finalise')})) return;
    const j = await ofdSave('POST', `/api/office/docs/${d.id}/finalize`, {}); if (j) toast(tr('Finalised as {0}', j.number || ''));
    return;
  }
  if (a === 'dup') { try { if (!await ofdDupAsk(d)) return; const j = await ofdRefCall(`dup${d.id}`, ref => rawFetch('POST', `/api/office/docs/${d.id}/duplicate`, {client_ref: ref})); OFD.list = null; OFD.doc = j; toast(tr('Copied as {0}', j.number || tr('Draft'))); go(`office/offers/${j.id}`); } catch (x) { toast(x.message || tr('unknown')); } return; }
  if (a === 'more') { menu(b, ofdMoreItems(d)); return; }
  if (a === 'it-svc') { ofdServicePicker(); return; }
  if (a === 'it-head') { d.items.push({kind: 'heading', title: '', detail: '', qty: 1, unit: 'day', rate: 0, tax: 'standard', raw_fee: 0, producing: 0, intext: 'intern', cost: 0, discountable: 1}); ofdDraw();  // 2.114.1 A (#2254): saved with the first typed title
    $(`${sc}.ofdits [data-i="${d.items.length - 1}"][data-k="title"]`)?.focus(); return; }
  if (a === 'it-text') {
    const blocks = ofcRows('texts').filter(x => x.kind === 'block' && !x.archived);
    const add = async text => { d.items.push({kind: 'text', title: '', detail: text, qty: 1, unit: 'day', rate: 0, tax: 'standard', raw_fee: 0, producing: 0, intext: 'intern', cost: 0, discountable: 1}); if (text) await ofdPutItems(); else ofdDraw(); if (!text) $(`${sc}.ofdits [data-i="${d.items.length - 1}"][data-k="detail"]`)?.focus(); };
    if (!blocks.length) { await add(''); return; }
    menu(b, [{label: tr('Free text'), icon: 'edit', fn: () => add('')}, '-', ...blocks.map(x => ({label: x.key || (x.text_de || x.text_en).slice(0, 50), fn: () => add(ofcText(x.id, ofdLang(d)))}))]);
    return;
  }
  if (a === 'it-del') { d.items.splice(+b.dataset.i, 1); await ofdPutItems(); return; }
  if (a === 'it-up' || a === 'it-down') { const i = +b.dataset.i, j = a === 'it-up' ? i - 1 : i + 1; if (j < 0 || j >= d.items.length) return; [d.items[i], d.items[j]] = [d.items[j], d.items[i]]; await ofdPutItems(); setTimeout(() => $(`${sc}.ofdits [data-ofd="${a}"][data-i="${j}"]`)?.focus(), 0); return; }
  if (a === 'client-new') { if (typeof clientModal === 'function') clientModal(null, {org_id: pb_clOrg(), stay: true, quick: true, done: r => ofdPatch({client_id: r.id})}); return; }  // 2.80.0 (#1842); 2.97.0 B (#1951): set as the document's client
  if (a === 'client-edit') { await cdn_editClient(d); return; }
  if (a === 'fld-add') { d.fields = [...(d.fields || []), {name: '', value: ''}]; OFD.open.fields = true; ofdDraw(); setTimeout(() => $(`#ofd-fields [data-fld="${d.fields.length - 1}"][data-k="name"]`)?.focus(), 0); return; }
  if (a === 'fld-del') { d.fields.splice(+b.dataset.i, 1); await ofdPatch({fields: d.fields}); return; }
}
// 2.97.0 B (#1951): the recipient comes from the client (name, attn., street, extra line, postcode city, country): the head
// shows it read-only with "Edit client"; without a client "Add client" makes one and sets it. A finished / sent document
// shows what was frozen; an old one with free lines keeps them. With the client module off the free fields stay.
const cdn_on = () => typeof clientsOn === 'function' && clientsOn();
function cdn_recHtml(d, ro) {
  const r = d.recipient || {}, lines = (r.lines || []).filter(x => String(x).trim());
  const addr = lines.length ? `<address class="cdnadr">${lines.map(x => esc(String(x))).join('<br>')}</address>` : '';
  if (!d.client_id) return `<div class="row cdnrec"><label>${esc(tr('Recipient'))}</label><div class="cdnrecb">${addr || `<span class="muted">${esc(tr('No client chosen'))}</span>`}${ro ? '' : `<button type="button" class="btn sm" data-ofd="client-new">${ic('plus', 's')}<span>${tr('Add client')}</span></button>`}</div></div>`;
  const miss = d.recipient_missing && !ro ? `<p class="cdnmiss" role="status">${ic('info', 's')} ${esc(tr('Address missing - add it at the client'))}</p>` : '';
  return `<div class="row cdnrec"><label>${esc(tr('Address'))}</label><div class="cdnrecb">${addr}${miss}${ro ? '' : `<button type="button" class="linkbtn" data-ofd="client-edit">${ic('edit', 's')} ${tr('Edit client')}</button>`}</div></div>`;
}
async function cdn_editClient(d) {
  if (typeof clientModal !== 'function' || !d.client_id) return;
  let c; try { c = await api('GET', `/api/clients/${d.client_id}`); } catch (x) { toast(x.message || tr('unknown')); return; }
  clientModal(c, {stay: true, done: () => ofdLoadDoc(d.id, true)});
}
// 2.38.0 (#1021, F1): creating, payments, sending, reminders (small dialogs; the server validates)
async function ofdCreate(body) {
  try { const j = await ofdRefCall('new', ref => rawFetch('POST', '/api/office/docs', {...body, client_ref: ref})); OFD.doc = j; OFD.list = null; OFD.kind = j.kind; go(`office/offers/${j.id}`); } catch (x) { toast(x.message || tr('unknown')); }
}
// 2.144.10 C (#2576): trial documents ("Just to try": TEST number, watermark MUSTER, deletable any time). The switch sits in
// the create dialogs (off by default, focus on "Create" so daily work stays one Enter); the first quotation / invoice of an
// office shows a hint once per person (setting trial_hint_seen, "<office id>:offer|invoice"); list: tag, filter, "Delete all"
function tri_meta(j) {
  if (j.first) OFD.first = j.first;
  OFD.office = j.office_id ?? j.org_id ?? OFD.office;
  OFD.trialCount = +j.trial_count || 0;
}
const tri_tag = r => r?.trial ? `<small class="tri-tag" data-trial="1">${esc(tr('Trial|document'))}</small>` : '';
function tri_seen() {
  const v = S.settings?.trial_hint_seen;
  if (Array.isArray(v)) return v;
  try { const a = JSON.parse(v || '[]'); return Array.isArray(a) ? a : []; } catch { return []; }
}
const tri_key = kind => `${OFD.office}:${kind === 'offer' ? 'offer' : 'invoice'}`;
const tri_hintOn = kind => OFD.office != null && !!OFD.first?.[kind === 'offer' ? 'offer' : 'invoice'] && !tri_seen().includes(tri_key(kind));
function tri_markSeen(kind) {
  if (OFD.office == null || tri_seen().includes(tri_key(kind))) return;
  const a = [...tri_seen(), tri_key(kind)];
  if (S.settings) S.settings.trial_hint_seen = JSON.stringify(a);
  api('PATCH', '/api/settings', {set_delta: {trial_hint_seen: {add: [tri_key(kind)]}}}).catch(() => { /* the local copy holds until the next load */ }); // 2.269.0 B (#3014): only this entry (another tab keeps its own)
}
function tri_switchHtml(kind) {
  const hint = tri_hintOn(kind) ? `<div class="onehint tri-hint" data-trial-hint="${kind}">${ic('info', 's')}<span>${esc(tr('Real documents are locked once finalised.'))}</span><button type="button" class="iconbtn hx" data-tri="x" aria-label="${esc(tr('Dismiss'))}" title="${esc(tr('Dismiss'))}">${ic('x', 's')}</button></div>` : '';
  return hint + `<div class="row tri-row"><label class="chkl swl"><span class="swc"><input type="checkbox" role="switch" id="ofd-trial-new"><span class="swt" aria-hidden="true"></span></span><span>${tr('Just to try')}</span></label>
    <div class="shint keep">${tr('TEST number, watermark MUSTER, deletable any time')}</div></div>`;
}
// the dialog's part: the X of the hint; returns {trial: true} for the request and remembers the hint as seen
function tri_body(md, kind) {
  if ($('.tri-hint', md)) tri_markSeen(kind);
  return $('#ofd-trial-new', md)?.checked ? {trial: true} : {};
}
function tri_wire(md, kind) {
  md.addEventListener('click', e => { if (e.target.closest('[data-tri="x"]')) { tri_markSeen(kind); $('.tri-hint', md)?.remove(); } });
  md.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.id === 'ofd-trial-new') { e.preventDefault(); $('[data-m="ok"]', md)?.click(); } });
}
function tri_newDialog(kind) {
  const md = ofdDlg(kind === 'offer' ? tr('New quotation') : tr('New invoice'), tri_switchHtml(kind), tr('Create'), async m => {
    const j = await ofdRefCall('new', ref => rawFetch('POST', '/api/office/docs', {...(kind === 'offer' ? {} : {kind}), ...tri_body(m, kind), client_ref: ref}));
    OFD.doc = j; OFD.list = null; OFD.kind = j.kind || kind; go(`office/offers/${j.id}`);
  });
  md.classList.add('tri-dlg');
  tri_wire(md, kind);
  $('[data-m="ok"]', md)?.setAttribute('data-mfocus', '');  // CI of 2.223.2: also the dialog's fallback focus (modal)
  setTimeout(() => $('[data-m="ok"]', md)?.focus(), 60);  // after ofdDlg's own focus: Enter creates
}
function tri_filterHtml() {
  if (!OFD.trialCount && !OFD.trial) return '';
  return `<select id="ofd-trial" aria-label="${esc(tr('Trial documents'))}"><option value="">${tr('All|trial filter')}</option><option value="0" ${OFD.trial === '0' ? 'selected' : ''}>${tr('Real only')}</option><option value="1" ${OFD.trial === '1' ? 'selected' : ''}>${tr('Trial only')}</option></select>`;
}
function tri_barHtml() {
  if (OFD.role !== 'admin' || !OFD.trialCount) return '';
  return `<div class="tri-bar muted"><span>${esc(trn('{0} trial document in this office', '{0} trial documents in this office', OFD.trialCount))}</span><button type="button" class="linkbtn tri-delall" data-ofd="tri-del-all">${ic('trash', 's')} ${tr('Delete all trial documents')}</button></div>`;
}
async function tri_deleteAll() {
  const n = OFD.trialCount;
  if (!await askConfirm(tr('Delete all trial documents?'), trn('{0} trial document (with its PDFs and share links) disappears for good. Real documents stay.', '{0} trial documents (with their PDFs and share links) disappear for good. Real documents stay.', n), {ok: tr('Delete all'), danger: true})) return;
  try { const j = await rawFetch('POST', '/api/office/trial/delete-all', {}); OFD.list = null; OFD.doc = null; await ofdLoadList(true); toast(trn('{0} trial document deleted', '{0} trial documents deleted', (+j.docs || 0) + (+j.gen_docs || 0))); }
  catch (x) { toast(x.message || tr('unknown')); }
}
const ofdClientOpts = () => typeof clientsOn === 'function' && clientsOn() ? (S.clients || []).filter(c => !c.archived && (c.org_id || null) === pb_clOrg()).map(c => [c.id, cdn_label(c)]) : [];
function ofdDlg(title, body, okLabel, onOk) {
  const md = modal(`<h3>${esc(title)}</h3><div class="ofddlg">${body}</div><div class="foot"><span class="aerr" role="alert"></span><span class="spacer"></span><button type="button" class="btn" data-m="close">${tr('Cancel')}</button><button type="button" class="btn pri" data-m="ok">${esc(okLabel)}</button></div>`);
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    if (b.dataset.m === 'ok') { b.disabled = true; try { if (await onOk(md) !== false) md.remove(); } catch (x) { $('.aerr', md).textContent = x.message || tr('unknown'); } b.disabled = false; }
  });
  setTimeout(() => { if (!isTouch()) $('input,select,textarea', md)?.focus(); }, 50);
  return md;
}
// 2.120.0 A (#2087): progress / final invoices and the cash discount (server: office/abschlag.py)
const absKindName = d => d?.inv_type === 'progress' ? tr('Progress invoice') : d?.inv_type === 'final' ? tr('Final invoice') : '';
function absHeadFields(d) {
  const t = d.inv_type || '';
  return ofdF('inv_type', tr('Type of invoice'), ofdSel('inv_type', t, [['', tr('Invoice')], ['progress', tr('Progress invoice')], ...(t === 'final' ? [['final', tr('Final invoice')]] : [])]),
    t === 'final' ? tr('deducts the finalised progress invoices of the quotation') : '', {keep: 1})
    + ofdF('skonto_pct', tr('Cash discount'), `<span class="lacts">${ofdIn('skonto_pct', d.skonto_pct ? ofdNumIn(d.skonto_pct) : '', {num: true, max: 6})}<span class="muted">%</span>${ofdIn('skonto_days', d.skonto_days ?? '', {num: true, max: 3})}<span class="muted">${tr('days')}</span></span>`, tr('empty = no cash discount'));
}
async function absInvoiceDialog(d) {
  let info;
  try { info = await api('GET', `/api/office/docs/${d.id}/progress`); } catch (x) { toast(x.message || tr('unknown')); return; }
  const pl = info.progress || [], cur = ofcSym(d.currency);  // 2.189.0 (#2475)
  const plist = pl.length ? `<ul class="ofdpick abs-list" role="list">${pl.map(p => `<li><span class="ofcn"><b>${esc(p.number || tr('Draft'))}</b><small class="muted">${esc([p.date ? fmtDateLoc(p.date) : '', p.gross_text, !p.locked ? tr('Draft') : +p.open <= 0 ? tr('Paid') : tr('open: {0}', p.open_text || p.open)].filter(Boolean).join(' · '))}</small></span></li>`).join('')}</ul>`
    : `<p class="muted">${tr('No progress invoices yet')}</p>`;
  const modes = [['full', tr('Full invoice')], ['progress', tr('Progress invoice')], ['final', tr('Final invoice')]];
  const md = ofdDlg(tr('Create invoice'), `<fieldset class="tpmodes"><legend class="muted">${tr('Type of invoice')}</legend>${modes.map(([v, n], i) => `<label class="tpmode"><input type="radio" name="abs-type" value="${v}" ${i ? '' : 'checked'}> <span>${esc(n)}</span></label>`).join('')}</fieldset>
    <div class="abs-p" hidden>${ofdF('abs-val', tr('Progress payment'), `<span class="lacts"><input id="ofd-abs-val" inputmode="decimal" class="numin" maxlength="14">${ofcSel('ofd-abs-unit', 'pct', [['pct', '%'], ['amount', cur + ' ' + tr('net')]])}</span>`, tr('quotation net {0}, not yet billed {1}', info.net_text, info.remaining_text), {keep: 1})}</div>
    <div class="abs-f" hidden><p class="muted ofchint">${tr('The whole quotation, less these progress invoices (finalised ones only):')}</p>${plist}</div>`,
    tr('Create invoice'), async m => {
      const typ = $('input[name="abs-type"]:checked', m)?.value || 'full';
      if (typ === 'full' && d.parts?.length && typeof tpInvoiceDialog === 'function') { setTimeout(() => tpInvoiceDialog(d), 0); return; }
      const b = {};
      if (typ !== 'full') b.inv_type = typ;
      if (typ === 'progress') { const v = ofcNum($('#ofd-abs-val', m).value); if (!v) throw new Error(tr('Enter an amount or a percentage')); b[$('#ofd-abs-unit', m).value] = v; }
      const j = await oil_post(d, b); if (!j) return;  // 2.356.0 C (#3003)
      OFD.list = null; OFD.kind = 'invoice'; OFD.doc = j; toast(tr('Invoice draft created')); go(`office/offers/${j.id}`);
    });
  md.addEventListener('change', e => {
    if (e.target.name !== 'abs-type') return;
    $('.abs-p', md).hidden = e.target.value !== 'progress'; $('.abs-f', md).hidden = e.target.value !== 'final';
    if (e.target.value === 'progress' && !isTouch()) $('#ofd-abs-val', md)?.focus();
  });
}
function ofdFromTimeDialog() {
  const cl = ofdClientOpts();
  if (!cl.length) { toast(tr('No clients in this organisation yet')); return; }
  const today = new Date(), first = new Date(today.getFullYear(), today.getMonth(), 1), iso = ds;
  const md = ofdDlg(tr('Invoice from time entries'), ofdF('ft-client', tr('Client'), ofcSel('ofd-ft-client', '', cl)) + ofdF('ft-from', tr('From'), dateIn('ofd-ft-from', iso(first), {label: tr('From'), clear: false}))
    + ofdF('ft-to', tr('Until'), dateIn('ofd-ft-to', iso(today), {label: tr('Until'), clear: false, after: 'ofd-ft-from'})) + `<p class="muted ofchint">${tr('One position per project; rate from the client or fill it in later.')}</p><p class="ofchint tbill-open" role="status" aria-live="polite"></p>` + tri_switchHtml('invoice'),
    tr('Create'), async m => { const j = await ofdRefCall('fromtime', ref => rawFetch('POST', '/api/office/docs/from-time', {client_id: +$('#ofd-ft-client', m).value, from: $('#ofd-ft-from', m).value, to: $('#ofd-ft-to', m).value, ...tri_body(m, 'invoice'), client_ref: ref})); OFD.list = null; OFD.kind = 'invoice'; OFD.doc = j; tbill_ftDone(j.time); go(`office/offers/${j.id}`); });
  tbill_ftPreview(md); md.addEventListener('change', () => tbill_ftPreview(md));
  tri_wire(md, 'invoice');  // 2.144.10 C (#2576)
}
// 2.144.6 A (#2053): the open billable hours of the period before the draft is made, the skipped entries after it
const tbill_h = s => fmtNum(s / 3600, 2);
async function tbill_ftPreview(md) {
  const out = $('.tbill-open', md); if (!out) return;
  const q = new URLSearchParams({client_id: $('#ofd-ft-client', md).value, from: $('#ofd-ft-from', md).value, to: $('#ofd-ft-to', md).value});
  let j; try { j = await rawFetch('GET', `/api/office/time-open?${q}`); } catch { out.textContent = ''; return; }
  const more = [j.billed_entries ? tr('{0} h already billed', tbill_h(j.billed_seconds)) : '', j.unbillable_entries ? tr('{0} h not billable', tbill_h(j.unbillable_seconds)) : ''].filter(Boolean);
  out.textContent = tr('Open billable: {0} h', tbill_h(j.open_seconds)) + (more.length ? ` (${more.join(', ')})` : '');
}
// the time entries of a cancelled invoice can be billed again (one undo step binds them again)
async function tbill_release(d) {
  const h = tbill_h(d.time_billed.seconds);
  if (!await askConfirm(tr('Release the time again?'), tr('{0} h of this cancelled invoice can then go onto a new invoice.', h), {ok: tr('Release')})) return;
  let j; try { j = await api('POST', `/api/office/docs/${d.id}/time-release`, {}); } catch { return; }
  const ids = j.released || [], again = async undo => { await api('POST', `/api/office/docs/${d.id}/time-release`, undo ? {undo: ids} : {}); await ofdLoadDoc(d.id, true); return {}; };
  await ofdLoadDoc(d.id, true);
  offerUndo(tr('Time released ({0} h)', h), histAdd({label: tr('Time released ({0} h)', h), res: j, lids: [], undo: () => again(true), redo: () => again(false)}));
}
function tbill_ftDone(t) {
  if (!t) return;
  if (!t.taken_entries) toast(tr('No open billable time in this period'));
  else if (t.skipped_billed || t.skipped_unbillable) toast(tr('{0} entries taken; skipped: {1} already billed, {2} not billable', t.taken_entries, t.skipped_billed, t.skipped_unbillable));
}
// 2.187.1 B (#2735): "Times to bill" of a person ruled by office groups (e.g. the template Staff on the level "own"): the
// own open hours of a period per client, without the client list of the quotations (the server: time-open without client_id)
OFC_TABS.splice(OFC_TABS.findIndex(t => t[0] === 'settings'), 0, /** @type {any} */ (['time', 'clock', N_('Times to bill'), 1, () => tbill_html(), 'sell']));
const TBL = {from: '', to: '', data: null, key: '', err: ''};
function tbill_html() {
  const today = new Date(), iso = ds;
  if (!TBL.from) Object.assign(TBL, {from: iso(new Date(today.getFullYear(), today.getMonth(), 1)), to: iso(today)});
  const key = `${OFC.info?.org_id || ''}:${TBL.from}:${TBL.to}`;
  if (TBL.key !== key) { Object.assign(TBL, {key, data: null, err: ''}); setTimeout(tbill_load, 0); }
  const bar = `<div class="ofcbar"><h3 class="ofcgrp">${tr('Times to bill')}</h3><span class="spacer"></span>
    <span class="lacts">${dateIn('tbl-from', TBL.from, {label: tr('From'), clear: false})}${dateIn('tbl-to', TBL.to, {label: tr('Until'), clear: false, after: 'tbl-from'})}</span></div>`;
  if (TBL.err) return bar + `<div class="empty">${esc(TBL.err)}</div>`;
  if (!TBL.data) return bar + `<p class="muted lempty">${tr('Loading…')}</p>`;
  const j = TBL.data, cl = j.clients || [];
  if (!cl.length) return bar + `<p class="muted lempty">${tr('No time entries in projects of a client in this period.')}</p>`;
  const more = x => [x.billed_seconds ? tr('{0} h already billed', tbill_h(x.billed_seconds)) : '', x.unbillable_seconds ? tr('{0} h not billable', tbill_h(x.unbillable_seconds)) : ''].filter(Boolean).join(' · ');
  return bar + `<p class="ofchint" role="status">${esc(tr('Open billable: {0} h', tbill_h(j.open_seconds)))}</p>
    <ul class="ofdpick" role="list">${cl.map(x => `<li><span class="ofcn"><b>${esc(x.name || tr('Client'))}</b><small class="muted">${esc([tr('Open billable: {0} h', tbill_h(x.open_seconds)), more(x)].filter(Boolean).join(' · '))}</small></span></li>`).join('')}</ul>`;
}
async function tbill_load() {
  const key = TBL.key;
  try { const j = await rawFetch('GET', `/api/office/time-open?${new URLSearchParams({from: TBL.from, to: TBL.to})}`); if (TBL.key === key) TBL.data = j; }
  catch (x) { if (TBL.key === key) TBL.err = x.message || tr('unknown'); }
  if (TBL.key === key && S.route.mod === 'office' && OFC.tab === 'time') renderView();
}
// 2.218.0 B (#2805): a number field in the editor selects its content on focus, so typing replaces the preset ("1" + 2 = "12")
document.addEventListener('focusin', e => { const f = e.target; if (f && f.matches && f.matches('.numin') && f.closest('.ofdeditor, .modal')) setTimeout(() => { if (document.activeElement === f) try { f.select(); } catch {} }, 0); });
document.addEventListener('change', e => {
  const t = /** @type {HTMLInputElement} */ (e.target);
  if (!t || (t.id !== 'tbl-from' && t.id !== 'tbl-to') || !t.value) return;
  TBL[t.id === 'tbl-from' ? 'from' : 'to'] = t.value;
  if (TBL.to < TBL.from) TBL.to = TBL.from;
  renderView();
});
function ofdPaymentDialog(d) {
  ofdDlg(tr('Record payment'), ofdF('p-date', tr('Date'), dateIn('ofd-p-date', today(), {label: tr('Date'), clear: false}))
    + ofdF('p-amount', tr('Amount'), `<span class="lacts"><input id="ofd-p-amount" inputmode="decimal" class="numin" value="${esc(ofdNumIn(d.open))}" maxlength="14"><span class="muted">${ofcSym(d.currency)}</span></span>`)
    + ofdF('p-method', tr('Method'), ofcSel('ofd-p-method', 'transfer', OFD_PAY.map(([v, n]) => [v, tr(n)]))) + ofdF('p-note', tr('Note'), `<input id="ofd-p-note" maxlength="500">`),
    tr('Record'), async md => { const j = await ofdRefCall(`pay${d.id}`, ref => ofdSave('POST', `/api/office/docs/${d.id}/payments`, {date: $('#ofd-p-date', md).value, amount: ofcNum($('#ofd-p-amount', md).value), method: $('#ofd-p-method', md).value, note: $('#ofd-p-note', md).value, client_ref: ref})); if (!j) return false; toast(j.state === 'paid' ? tr('Paid in full') : tr('Payment recorded')); });
}
// 2.147.0 (#2461): the e-invoice formats of the country pack (the base pack: ZUGFeRD / Factur-X only)
function ofdEinvOpts() {
  const fm = OFC.info?.pack?.einvoice_formats?.length ? OFC.info.pack.einvoice_formats : ['zugferd', 'xrechnung'];
  return [['zugferd', fm.includes('xrechnung') ? tr('ZUGFeRD (PDF with XML)') : tr('ZUGFeRD / Factur-X (PDF with XML)')], ['xrechnung', tr('XRechnung (XML, public clients)')]].filter(o => fm.includes(o[0]));  // 2.356.0 C (#3005): translated
}
// 2.269.0 D (#3046): a request that makes a document / books a payment carries one client_ref per action (key): pressed
// twice or sent again after an error = the same ref (the server answers with the first result), a fresh one after success
const OFD_REF = {};
async function ofdRefCall(key, fn) {
  const o = OFD_REF[key] && Date.now() - OFD_REF[key].t < 600000 ? OFD_REF[key] : (OFD_REF[key] = {r: outKey(), t: Date.now()});
  const j = await fn(o.r);
  if (j && OFD_REF[key] === o) delete OFD_REF[key];
  return j;
}
async function ofdSendDialog(d) {
  let ms = {smtp: true, datev_email: ''}, tm = null;
  try { ms = await api('GET', '/api/office/mail-status'); } catch {}
  try { tm = await api('GET', `/api/office/docs/${d.id}/terms`); } catch {}  // 2.113.2 (#2253): the terms of the document's language
  const cl = (S.clients || []).find(c => c.id === d.client_id);
  const to = cl?.billing?.email_invoice || cl?.email || '';
  // 2.40.0 (#1368 point 10): plain words for people who do not run the server; without mail the button downloads the PDF
  const hint = !ms.smtp ? `<p class="ofdwarn">${esc(tr('E-mail sending is not set up: download the PDF and send it yourself.') + (S.me?.is_admin ? ' (KALMIDO_SMTP_HOST)' : ''))}</p>` : '';
  ofdDlg(tr('Send {0}', d.number || ''), hint + ofdF('s-to', tr('To|mail recipient'), `<input id="ofd-s-to" type="email" value="${esc(to)}" maxlength="200" ${ms.smtp ? '' : 'disabled'}>`)
    + ofdF('s-cc', tr('Copy to'), `<input id="ofd-s-cc" type="email" maxlength="200" ${ms.smtp ? '' : 'disabled'}>`)
    + ofdF('s-subject', tr('Subject'), `<input id="ofd-s-subject" value="${esc(`${ofdKindName(d.kind, true)} ${d.number || ''}`)}" maxlength="200" ${ms.smtp ? '' : 'disabled'}>`)
    + ofdF('s-text', tr('Text'), `<textarea id="ofd-s-text" rows="4" maxlength="8000" placeholder="${esc(tr('empty = the standard text'))}" ${ms.smtp ? '' : 'disabled'}></textarea>`)
    + (d.timesheet_ok ? `<div class="row"><label class="chkl" style="min-width:0"><input type="checkbox" id="ofd-s-ts"> ${tr('Attach the timesheet')}</label></div>` : '')  // 2.120.0 D (#2089)
    + (d.kind !== 'reminder' && d.kind !== 'delivery' && ms.datev_on !== false ? `<div class="row"><label class="chkl" style="min-width:0"><input type="checkbox" id="ofd-s-datev" ${ms.datev_email && ms.datev_auto ? 'checked' : ''} ${ms.datev_email && ms.smtp ? '' : 'disabled'}> ${tr('Copy to the DATEV inbox')}${ms.datev_email ? ` <span class="muted">(${esc(ms.datev_email)})</span>` : ` <span class="muted">${tr('(no address in the settings)')}</span>`}</label></div>` : '')
    + (typeof agbSendRow === 'function' ? agbSendRow(tm, ms.smtp) : ''),
    ms.smtp ? tr('Send|mail') : tr('Download PDF'), async md => { if (!ms.smtp) { const a = document.createElement('a'); a.href = ofdPdfUrl(d.id); a.download = ''; document.body.appendChild(a); a.click(); a.remove(); return; } const j = await ofdSave('POST', `/api/office/docs/${d.id}/send`, {to: $('#ofd-s-to', md).value.trim(), cc: $('#ofd-s-cc', md).value.trim(), subject: $('#ofd-s-subject', md).value, text: $('#ofd-s-text', md).value, datev: !!$('#ofd-s-datev', md)?.checked, timesheet: !!$('#ofd-s-ts', md)?.checked, terms: !!$('#ofd-s-terms', md)?.checked}); if (!j) return false; toast(j.datev_error || tr('Sent')); });  // 2.269.0 D (#3046): DATEV failed after the mail = a hint, the dialog closes
}
async function ofdReminderDialog() {
  let rows = [];
  try { rows = (await api('GET', '/api/office/docs?kind=invoice')).docs.filter(r => ['issued', 'sent', 'partial', 'overdue'].includes(r.state)); } catch (x) { toast(x.message || tr('unknown')); return; }
  if (!rows.length) { toast(tr('No open invoices')); return; }
  const s = OFC.info?.settings || {};
  // 2.355.0 D (#2846): only invoices past their due date can be reminded of (the server answers 409); the others stay visible, greyed out
  const day0 = today(), early = r => !!r.due_date && r.due_date >= day0;
  const list = `<ul class="ofdpick" role="list">${rows.map(r => `<li><label class="chkl"><input type="checkbox" data-rid="${r.id}" data-cid="${r.client_id || ''}" ${r.state === 'overdue' && !early(r) ? 'checked' : ''} ${early(r) ? 'disabled' : ''}> <span class="ofcn"><b>${esc(r.number)}${r.recipient_name ? ` · ${esc(r.recipient_name)}` : ''}</b><small class="muted">${esc([r.due_date ? tr('due {0}', fmtDateLoc(r.due_date)) : '', early(r) ? tr('not yet overdue') : r.status_text, tr('open: {0}', r.open_text || r.open)].filter(Boolean).join(' · '))}</small></span></label></li>`).join('')}</ul>`;
  const md0 = ofdDlg(tr('Create reminder'), `<p class="muted ofchint">${tr('Pick the overdue invoices of one client.')}</p>${list}<p class="ofdwarn" id="ofd-r-warn" hidden></p>` + ofdF('r-level', tr('Reminder level'), ofcSel('ofd-r-level', 1, [[1, tr('1 - payment reminder')], [2, tr('2 - reminder')], [3, tr('3 - final reminder')]]))
    + ofdF('r-fee', tr('Reminder fee'), `<input id="ofd-r-fee" inputmode="decimal" class="numin" value="${esc(ofdNumIn(0))}" maxlength="10">`) + ofdF('r-days', tr('Payment deadline'), `<span class="lacts"><input id="ofd-r-days" inputmode="numeric" class="numin" value="${esc(String(s.reminder_deadline_days ?? 10))}" maxlength="3"><span class="muted">${tr('days')}</span></span>`),
    tr('Create'), async md => {
      const picked = [...md.querySelectorAll('[data-rid]:checked')];
      if (!picked.length) throw new Error(tr('Pick at least one invoice'));
      if (new Set(picked.map(x => x.dataset.cid)).size > 1) throw new Error(tr('One reminder covers the invoices of one client'));
      const j = await ofdRefCall('reminder', ref => rawFetch('POST', '/api/office/docs/reminder', {doc_ids: picked.map(x => +x.dataset.rid), level: +$('#ofd-r-level', md).value, fee: ofcNum($('#ofd-r-fee', md).value), deadline_days: ofcNum($('#ofd-r-days', md).value), client_ref: ref}));
      OFD.list = null; OFD.kind = 'reminder'; OFD.doc = j; go(`office/offers/${j.id}`);
    });
  // 2.40.0 (#1368 point 7): a hint, no block: a high fee (private clients: only the actual costs, usually 2-5 €); 2.355.0 D (#2846): invoices not yet due can no longer be picked
  const warn = () => {
    const w = $('#ofd-r-warn', md0); if (!w) return;
    const fee = ofcNum($('#ofd-r-fee', md0).value) || 0;
    const msg = [fee > 5 ? tr('Private clients may only be charged the actual costs of a reminder (usually 2 to 5 €).') : ''].filter(Boolean);
    w.innerHTML = msg.map(esc).join('<br>'); w.hidden = !msg.length;
  };
  // 2.296.0 D (#3174): the office's fee is the default from level 2 on (level 1 is the friendly payment reminder, no fee); a typed fee stays
  const feeIn = $('#ofd-r-fee', md0);
  feeIn.addEventListener('input', e => { if (e.isTrusted) feeIn.dataset.typed = '1'; });
  $('#ofd-r-level', md0).addEventListener('change', e => { if (!feeIn.dataset.typed) { feeIn.value = ofdNumIn(+e.target.value >= 2 ? (s.reminder_fee ?? 0) : 0); warn(); } });
  md0.addEventListener('input', warn); md0.addEventListener('change', warn); warn();
}
// the service picker: search the catalogue, tap = a new position with the service's name (document language), rate and flags
function ofdServicePicker() {
  const d = typeof tpCur === 'function' ? tpCur() : OFD.doc;  // 2.47.0 (#1215): into an open part
  const tpc = typeof TP === 'object' ? TP.open : null, sc = typeof tpf_sc === 'function' ? tpf_sc() : '';  // 2.113.0 (#2248): the part it was opened in
  const md = modal(`<h3>${tr('Add service')}</h3><div class="ctsearch">${ic('search', 's')}<input id="ofd-sq" type="search" placeholder="${esc(tr('Search'))}" aria-label="${esc(tr('Search services'))}" autocomplete="off"></div><div id="ofd-slist" class="ofdslist"></div>
    <div class="foot"><button type="button" class="btn" data-m="free">${tr('Free position')}</button><span class="spacer"></span><button type="button" class="btn" data-m="close">${tr('Close')}</button></div>`);
  md.classList.add('ofdpick');
  const draw = () => {
    const q = ($('#ofd-sq', md)?.value || '').trim().toLowerCase();
    // 2.47.0 (#1216): services of the kind shooting belong only to the shoot calculation, never among the positions
    const rows = ofcRows('services').filter(s => !s.archived && s.intext !== 'shooting' && (!q || [s.name_de, s.name_en, s.category].some(v => (v || '').toLowerCase().includes(q))));
    const groups = new Map(); for (const s of rows) { const k = s.category || tr('No category'); if (!groups.has(k)) groups.set(k, []); groups.get(k).push(s); }
    $('#ofd-slist', md).innerHTML = rows.length ? [...groups].map(([k, ss]) => `<h4 class="ofcgrp">${esc(k)}</h4><ul class="ofclist" role="list">${ss.map(s => { const ct = d.contract?.rates?.[s.id]; const rate = ct ?? (s.unit === 'hour' && s.hourly_rate != null ? s.hourly_rate : s.daily_rate); return `<li><button type="button" class="ofcrow" data-sid="${s.id}"><span class="ofcn"><b>${esc(ofdSvcName(s, d))}</b><small class="muted">${esc([rate != null ? `${s.unit === 'percent' ? `${fmtNum(rate, 2)} %` : `${fmtNum(rate, 2)} € / ${tr(OFC_UNITS.find(u => u[0] === s.unit)?.[1] || s.unit)}`}` : '', ct != null ? tr('contract rate') : '', ofcTax(s.tax)].filter(Boolean).join(' · '))}</small></span>${ic('plus', 's')}</button></li>`; }).join('')}</ul>`).join('')
      + (typeof tpPickerHtml === 'function' && !q ? tpPickerHtml(d) : '')  // 2.47.0 (#1215): after the services, the parts
      : (typeof tpPickerHtml === 'function' && tpPickerHtml(d)) || `<p class="muted lempty">${ofcRows('services').length ? tr('Nothing matches.') : esc(tr('No services yet (tab {0}).', '\u0001')).replace('\u0001', `<a href="#office/services" data-m="tab">${esc(tr('Services'))}</a>`)}</p>`;  // 2.39.1 (#1220): the tab as a link
  };
  draw();
  if (!Array.isArray(OFC.data.services)) {  // the catalogue may still be loading: show it once it is there
    $('#ofd-slist', md).innerHTML = `<p class="muted lempty">${tr('Loading…')}</p>`;
    (async () => { for (let i = 0; i < 60 && !Array.isArray(OFC.data.services) && md.isConnected; i++) { if (!OFC.loading.services) ofcLoad('services', true); await sleep(150); } if (md.isConnected) draw(); })();
  }
  md.addEventListener('input', e => { if (e.target.id === 'ofd-sq') draw(); });
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-sid],[data-m]'); if (!b) return;
    if (typeof TP === 'object') TP.open = tpc;  // 2.113.0 (#2248)
    if (b.dataset.m === 'close' || b.dataset.m === 'tab') { md.remove(); return; }  // (tab: the link goes on to #office/services)
    if (b.dataset.m === 'part' && typeof tpPick === 'function') { md.remove(); await tpPick(+b.dataset.pid); return; }  // 2.47.0 (#1215)
    const blank = {kind: 'service', service_id: null, title: '', detail: '', qty: 1, unit: 'day', rate: 0, tax: 'standard', raw_fee: 0, producing: 0, intext: 'intern', cost: 0, discountable: 1};
    if (b.dataset.m === 'free') { d.items.push(blank); md.remove(); await ofdPutItems(); $(`${sc}.ofdits [data-i="${d.items.length - 1}"][data-k="title"]`)?.focus(); return; }
    const s = ofcRow('services', +b.dataset.sid); if (!s) return;
    const ct = d.contract?.rates?.[s.id];
    d.items.push({...blank, cost: null /* 2.47.0 (#1649): the server takes the purchase of the service's role */, service_id: s.id, title: ofdSvcName(s, d), unit: s.unit || 'day', rate: ct ?? (s.unit === 'hour' && s.hourly_rate != null ? s.hourly_rate : s.daily_rate) ?? 0, tax: s.tax || 'standard', raw_fee: s.raw_fee ? 1 : 0, producing: s.producing ? 1 : 0, intext: s.intext || 'intern'});
    md.remove(); await ofdPutItems();
    $(`${sc}.ofdits [data-i="${d.items.length - 1}"][data-k="qty"]`)?.focus();
  });
  setTimeout(() => { if (!isTouch()) $('#ofd-sq', md)?.focus(); }, 50);
}
// the editor's open sections are remembered while the page lives
document.addEventListener('toggle', e => { if (e.target?.classList?.contains('oil_more')) OFD.open.more = e.target.open; }, true);  // 2.356.0 C (#3005)
document.addEventListener('toggle', e => { const s = e.target?.dataset?.sec; if (s && e.target.classList?.contains('ofdsec')) { const was = OFD.open[s]; OFD.open[s] = e.target.open; if (s === 'log' && e.target.open && !was) ofdDraw(); } }, true);

// 2.120.0 D (#2089): delivery notes / proofs of service and the timesheet of an invoice
function ls_click(a, d) {
  if (a === 'new-ls') return ofdCreate({kind: 'delivery'});
  const make = async title => { try { const j = await ofdRefCall(`ls${d.id}`, ref => rawFetch('POST', `/api/office/docs/${d.id}/delivery`, {title, client_ref: ref})); OFD.list = null; OFD.kind = 'delivery'; OFD.doc = j; go(`office/offers/${j.id}`); } catch (x) { toast(x.message || tr('unknown')); } };
  menu($('[data-ofd="to-ls"]'), [{label: tr('Create delivery note'), icon: 'file', fn: () => make('delivery')}, {label: tr('Create proof of service'), icon: 'file', fn: () => make('service')}]);
}
function ls_moreItems(d, inList) {
  return !inList && d.timesheet_ok ? [{label: tr('Timesheet (PDF)'), icon: 'clock', fn: () => window.open(`/api/office/docs/${d.id}/timesheet.pdf?inline=1`, '_blank', 'noopener')}] : [];
}

// 2.199.0 B (#2742): a quotation / invoice filed in a folder of its office's file tree (a reference node: nothing moves, the
// folder's shares reach the document -- reading / changing a draft, never sending or paying). The folders of the office's
// space (the organisation's, a personal office: the own private tree), "Take out of the folder", "Show in the file store".
FS_REF_ICON.office_doc = 'receipt';
OFD.viaFolder = OFD.viaFolder || new Set();
async function ofd_fileDlg(d) {
  let fs, cur;
  try { [fs, cur] = await Promise.all([api('GET', '/api/files/folders').then(j => j.folders || []), api('GET', `/api/files/refs/office_doc/${d.id}`).catch(() => ({}))]); } catch { return; }
  const node = cur?.node && !cur.node.deleted_at ? cur.node : null;
  const org = (S.me?.workspaces || []).some(w => w.id === d.org_id);  // else a personal office: its owner's private tree
  const ok = fs.filter(f => org ? f.org_id === d.org_id : !f.org_id && f.owner_id === S.me?.id);  // the folders one may add to
  const put = async pid => {
    const was = node?.parent_id ?? null;
    try { await api('POST', '/api/files/refs', {ref_kind: 'office_doc', ref_id: d.id, parent_id: pid}); } catch { return; }
    const back = () => ab_req('POST', '/api/files/refs', {ref_kind: 'office_doc', ref_id: d.id, parent_id: was});
    offerUndo(pid ? tr('Filed in {0}', (ok.find(f => f.id === pid) || {}).path || '') : tr('Taken out of the folder'),
      histAdd({label: tr('File “{0}”', d.number || ofdKindName(d.kind, true)), undo: back, redo: () => ab_req('POST', '/api/files/refs', {ref_kind: 'office_doc', ref_id: d.id, parent_id: pid})}));
    if (typeof ab_ptStale === 'function') ab_ptStale();
  };
  const items = [...(node ? [{label: tr('Show in the file store'), icon: 'folder', fn: () => go('ablage/' + node.parent_id)}, {label: tr('Take out of the folder'), icon: 'up', fn: () => put(null)}, '-'] : []),
    ...ok.filter(f => f.id !== node?.parent_id).slice(0, 80).map(f => ({label: f.path, icon: 'folder', fn: () => put(f.id)}))];
  if (!items.length) { toast(tr('No folder yet: create one in the file store first')); return; }
  const anchor = $('[data-ofd="more"]') || document.body;
  menu(anchor, [{head: tr('File in a folder…')}, ...items], null, null, tr('File in a folder…'));
}

// 2.351.0 A (#3312): client / project / year are filters at the top of the list (decision of 26.10.2026) -- the
// automatic groups By client / By project / By year and the group "Folders" of the panel (2.199) are gone: every document
// area of the panel opens as a tree of its own (office_tree.js). The choices: the clients, projects and years of the
// quotations / invoices (GET /api/office/docs/groups); they combine.
OFD.flt = OFD.flt || {client_id: '', project: '', year: ''};
const ofd_grpQs = () => Object.entries(OFD.flt).filter(([, v]) => v).map(([k, v]) => `&${k}=${encodeURIComponent(v)}`).join('');
async function ofd_grpLoad() {
  const key = OFC.info ? String(OFC.info.org_id) : ''; if (!key || OFD.grpBusy) return;
  OFD.grpBusy = true;
  try { OFD.groups = {key, ...(await rawFetch('GET', '/api/office/docs/groups'))}; } catch { OFD.groups = {key, clients: [], projects: [], years: []}; }
  OFD.grpBusy = false;
  ofdDraw();
}
function ofd_fltHtml() {
  const g = OFD.groups?.key === String(OFC.info?.org_id) ? OFD.groups : (ofd_grpLoad(), null); if (!g) return '';
  const sel = (k, label, all, opts) => opts.length || OFD.flt[k] ? `<select id="ofd-flt-${k}" data-oflt="${k}" aria-label="${esc(label)}"><option value="">${esc(all)}</option>${opts.map(([v, n]) => `<option value="${esc(String(v))}" ${String(OFD.flt[k]) === String(v) ? 'selected' : ''}>${esc(String(n))}</option>`).join('')}</select>` : '';
  return sel('client_id', tr('Client'), tr('All clients'), g.clients.map(x => [x.id, x.name])) + sel('project', tr('Project'), tr('All projects'), g.projects.map(x => [x.name, x.name]))
    + sel('year', tr('Year'), tr('All years'), g.years.map(x => [x.year, x.year]));
}

// 2.272.0 E2 (#3038): the office trash - deleted drafts and master data, restore or delete for good, the trash period
async function otb_restore(tid, after) {
  let j; try { j = await api('POST', `/api/office/trash/${tid}/restore`); } catch (x) { toast(x.message || tr('unknown')); return; }
  toast(tr('Restored'));
  if (j.kind === 'doc') { OFD.list = null; go(`office/offers/${j.id}`); } else if (typeof ofcReload === 'function') ofcReload(j.kind);
  if (after) after();
}
async function otb_open() {
  let d; try { d = await api('GET', '/api/office/trash'); } catch (x) { toast(x.message || tr('unknown')); return; }
  const row = x => `<li data-id="${x.id}"><span class="an">${esc(x.kind === 'doc' ? ofdKindName(x.sub, true) : tr('Master data'))}${x.label ? ' · ' + esc(x.label) : ''}</span> <span class="muted">${esc(fmtDayAbs(x.deleted_at.slice(0, 10)))}</span>
    <button type="button" class="linkbtn" data-m="restore">${esc(tr('Restore'))}</button> <button type="button" class="linkbtn" data-m="purge">${esc(tr('Delete for good'))}</button></li>`;
  const md = modal(`<h3>${esc(tr('Trash'))}</h3>${d.items.length ? `<ul class="atrash otblist">${d.items.map(row).join('')}</ul>` : `<p class="muted">${esc(tr('The trash is empty'))}</p>`}
    <p class="muted">${esc(trashNote(tr('Items in the trash are deleted for good after {0} days.', d.days)))}</p><div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Close')}</button></div>`);
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    const li = b.closest('li'), id = +li?.dataset.id; if (!id) return;
    if (b.dataset.m === 'restore') { md.remove(); await otb_restore(id); return; }
    if (b.dataset.m === 'purge') {
      if (!await askConfirm(tr('Delete “{0}” for good?', li.querySelector('.an')?.textContent || ''), tr('This cannot be undone.'), {ok: tr('Delete for good'), danger: true})) return;
      try { await api('DELETE', `/api/office/trash/${id}`); li.remove(); } catch (x) { toast(x.message || tr('unknown')); }
    }
  });
}
