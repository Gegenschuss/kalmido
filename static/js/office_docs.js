// Office & finance (2.36.1, #1021), part C: quotations -- the tab "Quotations" of the office view (office.js calls
// ofdOffersTab(el)) with the list and the editor (#office/offers/<id>). The server computes the sums (kalmido/office/calc.py)
// on every change and returns them; the editor shows exactly those figures in the document's language and currency.
const OFD = {list: null, loading: false, q: '', status: '', kind: 'offer', doc: null, docId: null, docLoading: false, seq: 0, saving: 0, err: '', open: {head: true, rights: true, texts: false, fields: false, log: false, pay: true}, log: null, logFor: 0};
const OFD_STATUS = [['draft', N_('Draft')], ['sent', N_('Sent')], ['accepted', N_('Accepted')], ['declined', N_('Declined')]];
// 2.38.0 (#1021, F1): invoices, credit notes and reminders share the tab; the server derives partial / overdue / cancelled
const OFD_KINDS = [['offer', N_('Quotations')], ['invoice', N_('Invoices')], ['credit', N_('Credit notes')], ['reminder', N_('Reminders')], ['delivery', N_('Delivery notes')], ['archive', N_('Archive|documents')]];  // 2.39.1 (#1182): + the legacy archive (office_import.js)
const OFD_STATE = {done: N_('Settled'), draft: N_('Draft'), issued: N_('Finalised'), sent: N_('Sent'), paid: N_('Paid'), partial: N_('Partly paid'), overdue: N_('Overdue'), cancelled: N_('Cancelled'), accepted: N_('Accepted'), declined: N_('Declined')};
const OFD_INV_STATUS = {invoice: ['draft', 'issued', 'sent', 'paid', 'cancelled'], credit: ['draft', 'issued', 'sent', 'paid'], reminder: ['draft', 'issued', 'sent'], delivery: ['draft', 'issued', 'sent']};  // 2.120.0 D (#2089): + delivery
const OFD_PAY = [['transfer', N_('Bank transfer')], ['cash', N_('Cash')], ['card', N_('Card')], ['other', N_('Other|payment')]];
const OFD_VATN = [['', N_('choose…')], ['reverse', N_('Reverse charge (recipient pays the VAT)')], ['abroad', N_('Not taxable domestically')], ['small', N_('Small business, no VAT')]];
const ofdIsInv = d => !!d && d.kind !== 'offer';
const ofdKindName = (k, one) => tr(one ? {offer: N_('Quotation'), invoice: N_('Invoice'), credit: N_('Credit note'), reminder: N_('Reminder'), delivery: N_('Delivery note')}[k] || k : OFD_KINDS.find(x => x[0] === k)?.[1] || k);
const OFD_RAW = [['optional', N_('optional (shown, not counted)')], ['included', N_('included (counted)')], ['none', N_('no raw data line')]];
const ofdLang = d => (d || OFD.doc)?.lang === 'en' ? 'en' : 'de';
// money and quantities in the DOCUMENT's language and currency (not the person's locale): 1.234,56 € / €1,234.50 / $1,234.50
function ofdMoney(n, d) {
  d = d || OFD.doc || {}; const en = ofdLang(d) === 'en', cur = d.currency === 'USD' ? '$' : '€';
  const neg = n < 0, a = Math.abs(+n || 0).toFixed(2), [w, f] = a.split('.'), g = w.replace(/\B(?=(\d{3})+(?!\d))/g, en ? ',' : '.');
  return en ? `${neg ? '-' : ''}${cur}${g}.${f}` : `${neg ? '-' : ''}${g},${f} ${cur}`;
}
const ofdQty = (n, d) => { const s = String(+(+n || 0).toFixed(4)); return ofdLang(d) === 'en' ? s : s.replace('.', ','); };
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
  const q = parseFloat(String(inp.value).replace(',', '.'));
  for (const o of sel.options) o.textContent = ofu_label(o.value, isNaN(q) ? 0 : q, d);
}
const ofdSvcName = (s, d) => (ofdLang(d) === 'en' ? s.name_en || s.name_de : s.name_de || s.name_en) || '';

// ---- loading
async function ofdLoadList(force) {
  if (OFD.loading) return;
  if (OFD.list && !force) return;
  if (OFD.kind === 'archive') { if (typeof OIM !== 'undefined') OIM.list = null; OFD.list = []; ofdDraw(); return; }  // 2.39.1 (#1182): office_import.js loads it
  OFD.loading = true;
  try { const j = await api('GET', `/api/office/docs?kind=${OFD.kind}${OFD.status ? '&status=' + OFD.status : ''}`); OFD.list = j.docs || []; OFD.role = j.role; OFD.err = ''; }
  catch (x) { OFD.list = []; OFD.err = x.message || tr('unknown'); }
  OFD.loading = false;
  ofdDraw();
}
async function ofdLoadDoc(id, force) {
  if (OFD.docLoading) return;
  if (OFD.doc && OFD.doc.id === id && !force) return;
  OFD.docLoading = true; OFD.docId = id;
  try { OFD.doc = await api('GET', `/api/office/docs/${id}`); OFD.err = ''; if (OFD.doc?.kind && OFD.doc.kind !== OFD.kind) { OFD.kind = OFD.doc.kind; OFD.list = null; } }
  catch (x) { OFD.doc = null; OFD.err = x.message || tr('unknown'); }
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
}
// the entry from office.js: fills the tab's body (list or editor)
function ofdOffersTab(el) {
  const id = S.route.id;
  if (id) {
    if ((!OFD.doc || OFD.doc.id !== id) && !OFD.docLoading) setTimeout(() => ofdLoadDoc(id), 0);
    if (!OFC.data.services && !OFC.loading.services) setTimeout(() => ofcLoad('services'), 0);
    if (!OFC.data.texts && !OFC.loading.texts) setTimeout(() => ofcLoad('texts'), 0);
    if (!OFC.data.contracts && !OFC.loading.contracts) setTimeout(() => ofcLoad('contracts'), 0);
  } else if (!OFD.list && !OFD.loading) setTimeout(ofdLoadList, 0);
  keepFocus(el, () => fl_set(el, id ? ofdEditorHtml() : ofdListHtml()));  // 2.46.2 (#1718): morphed
  if (!el._ofd) { el._ofd = true; el.addEventListener('contextmenu', ofdCtx); if (typeof ms_longPress === 'function') OFD.lp = ms_longPress('#view .ofdrow', () => false, r => ofdRowMenu(r.dataset.id, r)); el.addEventListener('click', ofdClick); el.addEventListener('change', ofdChange); el.addEventListener('input', ofdInput); el.addEventListener('keydown', ofdKey); }
}

// ---- the list
function ofdListHtml() {
  const rows = OFD.list, k = OFD.kind, inv = k === 'invoice' || k === 'credit';
  const q = OFD.q.trim().toLowerCase();
  if (k === 'archive') return `<div class="seg ofdkinds" role="tablist" aria-label="${esc(tr('Document kind'))}">${OFD_KINDS.map(([v, n]) => `<button type="button" role="tab" data-ofd="kind" data-kind="${v}" aria-selected="${v === k}" class="${v === k ? 'on' : ''}">${tr(n)}</button>`).join('')}</div><div class="ofcbar ofdbar"><div class="ctsearch">${ic('search', 's')}<input id="ofd-q" type="search" value="${esc(OFD.q)}" placeholder="${esc(tr('Search'))}" aria-label="${esc(tr('Search documents'))}" autocomplete="off" enterkeyhint="search"></div></div>` + (typeof oimArchiveListHtml === 'function' ? oimArchiveListHtml(q) : '');
  const sts = k === 'offer' ? OFD_STATUS : (k === 'invoice' ? ['draft', 'issued', 'sent', 'partial', 'overdue', 'paid', 'cancelled'] : OFD_INV_STATUS[k]).map(v => [v, OFD_STATE[v]]);
  const newBtn = k === 'offer' ? `<button class="btn sm pri" data-ofd="new">${ic('plus', 's')}<span>${tr('New quotation')}</span></button>`
    : k === 'invoice' ? `${typeof dx_btn === 'function' ? dx_btn() : ''}<button class="btn sm" data-ofd="remind">${ic('clock', 's')}<span>${tr('Create reminder')}</span></button><button class="btn sm pri" data-ofd="new-inv" aria-haspopup="menu">${ic('plus', 's')}<span>${tr('New invoice')}</span></button>`
    : k === 'reminder' ? `<button class="btn sm pri" data-ofd="remind">${ic('plus', 's')}<span>${tr('Create reminder')}</span></button>`
    : k === 'delivery' ? `<button class="btn sm pri" data-ofd="new-ls">${ic('plus', 's')}<span>${tr('New delivery note')}</span></button>` : '';  // 2.120.0 D (#2089)
  const kinds = `<div class="seg ofdkinds" role="tablist" aria-label="${esc(tr('Document kind'))}">${OFD_KINDS.map(([v, n]) => `<button type="button" role="tab" data-ofd="kind" data-kind="${v}" aria-selected="${v === k}" class="${v === k ? 'on' : ''}">${tr(n)}</button>`).join('')}</div>`;
  // 2.46.1 (#1637): an empty offer list shows its one big button below the text, not a second one up here
  const noTop = k === 'offer' && rows && !rows.length && !q && !OFD.status;
  const bar = kinds + `<div class="ofcbar ofdbar"><div class="ctsearch">${ic('search', 's')}<input id="ofd-q" type="search" value="${esc(OFD.q)}" placeholder="${esc(tr('Search'))}" aria-label="${esc(tr('Search documents'))}" autocomplete="off" enterkeyhint="search"></div>
    <select id="ofd-status" aria-label="${esc(tr('Status'))}"><option value="">${tr('All|status')}</option>${sts.map(([v, n]) => `<option value="${v}" ${OFD.status === v ? 'selected' : ''}>${tr(n)}</option>`).join('')}</select><span class="spacer"></span>${noTop ? '' : newBtn}</div>`;
  if (!rows) return bar + `<p class="muted lempty">${tr('Loading…')}</p>`;
  if (OFD.err && !rows.length) return bar + `<div class="empty">${esc(OFD.err)}</div>`;
  const hit = r => !q || [r.number, r.recipient_name, r.project_title, r.project_ref].some(v => (v || '').toLowerCase().includes(q));
  const list = rows.filter(hit);
  const emptyTxt = {offer: N_('No quotations yet. The first one takes your services, rates and text blocks.'), invoice: N_('No invoices yet. Make one from a quotation, from time entries or start empty.'),
    credit: N_('No credit notes yet. A credit note is made from a finalised invoice.'), reminder: N_('No reminders yet. Pick open invoices in the invoice list.'),
    delivery: N_('No delivery notes yet. Make one from a quotation or an invoice (no prices are printed) or start empty.')};  // 2.120.0 D (#2089)
  if (!list.length) return bar + `<div class="empty nempty eact">${ic('receipt')}<span>${q || OFD.status ? tr('Nothing matches.') : tr(emptyTxt[k])}</span>${!q && !OFD.status && k === 'offer' ? `<button class="btn pri" data-ofd="new">${ic('plus', 's')}<span>${tr('New quotation')}</span></button>` : ''}</div>`;
  // 2.40.0 (#1368 point 9): settled reminders (all their invoices paid or cancelled) below the open ones
  const grp = k === 'reminder' && list.some(r => r.settled) && list.some(r => !r.settled);
  if (k === 'reminder') list.sort((a, b) => (a.settled ? 1 : 0) - (b.settled ? 1 : 0));
  const feeTxt = r => +r.fee_open > 0 ? `<small class="ofdfee">${esc(k === 'reminder' ? tr('fee open: {0}', r.fee_open_text || r.fee_open) : tr('reminder fee open: {0}', r.fee_open_text || r.fee_open))}</small>` : '';
  return bar + (k === 'invoice' && typeof oa_ppBox === 'function' ? oa_ppBox() : '') + (k === 'invoice' && typeof rinListHtml === 'function' ? rinListHtml() : '') /* 2.91.0 A (#1923) */ + `<ul class="ofclist ofdlist" role="list">${list.map((r, i) => `${grp && r.settled && !list[i - 1]?.settled ? `<li class="ofdgrp muted" role="presentation">${tr('Settled')}</li>` : ''}<li class="ofdli"><button type="button" class="ofcrow ofdrow st-${r.state || r.status}" data-ofd="open" data-id="${r.id}">
    <span class="ofcn"><b>${r.locked ? `<span class="ofdlk" title="${esc(tr('Finalised'))}">${ic('lock', 's')}</span>` : ''}${esc(r.number || tr('(no number)'))}${r.recipient_name ? ` · ${esc(r.recipient_name)}` : ''}</b><small class="muted">${esc([r.project_title, r.date ? fmtDateLoc(r.date) : '', inv && r.due_date && !['paid', 'cancelled'].includes(r.state) ? tr('due {0}', fmtDateLoc(r.due_date)) : ''].filter(Boolean).join(' · '))}</small>${k === 'invoice' && typeof rinRowTag === 'function' ? rinRowTag(r) : ''}${k === 'invoice' && r.inv_type ? `<small class="rin-tag abs-tag">${esc(absKindName(r))}</small>` : ''}</span>
    <span class="ofdsum"><b>${esc(k === 'delivery' ? '' : inv ? r.gross_text : r.net_text)}</b>${inv && r.open && !['draft', 'paid', 'cancelled'].includes(r.state) && r.open !== r.gross ? `<small class="muted">${esc(tr('open: {0}', r.open_text || r.open))}</small>` : ''}${feeTxt(r)}<small class="rotag st-${r.state || r.status}">${esc(r.status_text)}</small></span></button><button type="button" class="iconbtn ofdrmore" data-ofd="rowmore" data-id="${r.id}" aria-haspopup="menu" aria-label="${esc(tr('More'))}" title="${esc(tr('More'))}">${ic('dots', 's')}</button></li>`).join('')}</ul>`;
}

// ---- the editor
const ofdSec = (key, title, body, extra = '') => `<details class="ofdsec" ${OFD.open[key] ? 'open' : ''} data-sec="${key}"><summary><h3>${esc(title)}</h3>${extra}</summary><div class="ofdsecb">${body}</div></details>`;
const ofdF = (k, label, field, hint) => `<div class="row"><label for="ofd-${k}">${esc(label)}</label>${field}${hint ? `<span class="muted ofchint">${esc(hint)}</span>` : ''}</div>${typeof ofcII === 'function' ? ofcII('ed_' + k) : ''}`;  // 2.47.3 (#1382): (i) per field
const ofdSel = (k, cur, opts, empty) => `<select id="ofd-${k}" data-f="${k}">${empty != null ? `<option value="">${esc(empty)}</option>` : ''}${opts.map(([v, n]) => `<option value="${esc(v)}" ${String(v) === String(cur ?? '') ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select>`;
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
  const numTxt = d.number || (d.number_at_finalize ? tr('Draft') : tr('(no number)'));
  const stOpts = kind === 'offer' ? OFD_STATUS : OFD_INV_STATUS[kind].map(v => [v, OFD_STATE[v]]);
  const stCan = v => (kind === 'offer' && (v !== 'draft' || d.status === 'draft')) || v === d.status || (lk && d.status !== 'cancelled' && (v === 'sent' || (v === 'paid' && kind === 'invoice' && adm)) && (d.status !== 'paid' || adm));  // 2.39.1 (#1210 N3): paid only by admins
  const stSel = `<select id="ofd-status" data-f="status" aria-label="${esc(tr('Status'))}" class="ofdstat st-${d.state || d.status}" ${inv && !lk ? 'disabled' : ''}>${stOpts.map(([v, n]) => `<option value="${v}" ${d.status === v ? 'selected' : ''} ${stCan(v) ? '' : 'disabled'}>${tr(n)}${v === d.status && d.state && d.state !== d.status ? ` (${tr(OFD_STATE[d.state])})` : ''}</option>`).join('')}</select>`;
  const acts = [];
  if (kind === 'offer') acts.push(`<button type="button" class="btn sm" data-ofd="to-invoice" title="${esc(tr('An invoice draft with the positions of this quotation'))}">${ic('receipt', 's')}<span>${tr('Create invoice')}</span></button>`);
  if (kind === 'invoice' && lk && d.status !== 'cancelled' && adm) acts.push(`<button type="button" class="btn sm" data-ofd="pay">${ic('plus', 's')}<span>${tr('Record payment')}</span></button>`);
  if (kind === 'offer' || kind === 'invoice') acts.push(`<button type="button" class="btn sm" data-ofd="to-ls" title="${esc(tr('A delivery note or proof of service with the positions, without prices'))}">${ic('file', 's')}<span>${tr('Delivery note')}</span></button>`);  // 2.120.0 D (#2089)
  if (inv && lk) acts.push(`<button type="button" class="btn sm" data-ofd="send">${ic('send', 's')}<span>${tr('Send|mail')}</span></button>`);
  const head = `<div class="ofdhead">${back}<span class="ofdnum"><b>${lk ? ic('lock', 's') + ' ' : ''}${inv ? esc(absKindName(d) || ofdKindName(kind, true)) + ' ' : ''}${esc(numTxt)}</b>${typeof onumDocHtml === 'function' ? onumDocHtml(d) : ''}${d.number || lk || d.number_at_finalize ? '' : `<button type="button" class="btn sm" data-ofd="number">${tr('Assign number')}</button>`}</span>
    ${stSel}<span class="spacer"></span>
    <span class="ofdsave muted" aria-live="polite">${OFD.saving ? tr('Saving…') : OFD.err ? esc(OFD.err) : ''}</span>${acts.join('')}
    ${lk || ro ? '' : `<button type="button" class="btn sm ofdfin" data-ofd="finalize" title="${esc(tr('Freeze number, positions, sums, sender and tax rates'))}">${ic('lock', 's')}<span>${tr('Finalise')}</span></button>`}
    <a class="btn sm ofdpdf" href="${ofdPdfUrl(d.id, true)}" target="_blank" rel="noopener" data-ofd="pdf"${typeof pv_attr === 'function' ? pv_attr({url: ofdPdfUrl(d.id, true), name: (d.number || tr('Document')) + '.pdf', dlUrl: ofdPdfUrl(d.id)}) : ''} aria-label="${esc(tr('Open PDF'))}" title="${esc(tr('Open PDF'))}">${ic('pdf', 's')}<span class="ofdpdft">PDF</span></a>
    <a class="btn sm ofddl" href="${ofdPdfUrl(d.id)}" download data-ofd="pdf" aria-label="${esc(tr('Download PDF'))}" title="${esc(tr('Download PDF'))}">${ic('download', 's')}<span class="ofdpdft">${tr('Download')}</span></a>
    <button type="button" class="btn sm" data-ofd="more" aria-haspopup="menu" aria-label="${esc(tr('More'))}">${ic('dots', 's')}</button></div>`;
  const invFields = inv && kind !== 'reminder' ? `
    ${ofdF('order_ref', tr('PO number'), ofdIn('order_ref', d.order_ref, {max: 80, ph: tr('the client\'s order reference')}))}
    ${kind === 'invoice' ? ofdF('payment_days', tr('Payment terms'), `<span class="lacts">${ofdIn('payment_days', d.payment_days ?? '', {num: true, max: 3})}<span class="muted">${tr('days')}</span></span>`, tr('the due date is set from this when it is empty')) : ''}
    ${kind === 'invoice' ? ofdF('due_date', tr('Due on'), dateIn('ofd-due_date', d.due_date || '', {label: tr('Due on'), attrs: 'data-f="due_date"'})) : ''}
    ${kind === 'invoice' ? absHeadFields(d) : ''}
    ${d.vat_mode === 'novat' && kind !== 'delivery' ? ofdF('vat_note', tr('VAT note'), ofdSel('vat_note', d.vat_note || '', OFD_VATN.map(([v, n]) => [v, tr(n)])), tr('printed on the invoice; required when finalising')) : ''}
    ${kind === 'delivery' ? '' : ofdF('einvoice_format', tr('E-invoice format'), ofdSel('einvoice_format', d.einvoice_format || 'zugferd', [['zugferd', 'ZUGFeRD (PDF with XML)'], ['xrechnung', 'XRechnung (XML, public clients)']]))}` : '';  // 2.120.0 D (#2089): no e-invoice
  const remFields = kind === 'reminder' ? `
    ${ofdF('reminder_level', tr('Reminder level'), ofdSel('reminder_level', d.reminder_level || 1, [[1, tr('1 - payment reminder')], [2, tr('2 - reminder')], [3, tr('3 - final reminder')]]))}
    ${ofdF('reminder_fee', tr('Reminder fee'), `<span class="lacts">${ofdIn('reminder_fee', ofdNumIn(d.reminder_fee), {num: true, max: 10})}<span class="muted">${d.currency === 'USD' ? '$' : '€'}</span></span>`)}
    ${ofdF('reminder_deadline_days', tr('Payment deadline'), `<span class="lacts">${ofdIn('reminder_deadline_days', d.reminder_deadline_days ?? '', {num: true, max: 3})}<span class="muted">${tr('days')}</span></span>`)}` : '';
  const headSec = ofdSec('head', tr('Head'), `
    <div class="ofdgrid">
    ${ofdF('lang', tr('Document language'), ofdSel('lang', d.lang, [['de', 'Deutsch'], ['en', 'English']]))}
    ${ofdF('currency', tr('Currency'), ofdSel('currency', d.currency, [['EUR', 'EUR'], ['USD', 'USD']]))}
    ${d.currency === 'USD' ? ofdF('fx_rate', tr('Exchange rate'), ofdIn('fx_rate', ofdNumIn(d.fx_rate), {num: true, max: 12}), tr('1 € in USD; rates stay in EUR and are converted')) : ''}
    ${kind !== 'reminder' && kind !== 'delivery' ? ofdF('vat_mode', tr('VAT'), ofdSel('vat_mode', d.vat_mode, [['vat', tr('with VAT')], ['novat', tr('without VAT (reverse charge / abroad)')]])) : ''}
    ${kind !== 'reminder' && kind !== 'delivery' ? ofdF('contract_id', tr('Framework contract'), ofdSel('contract_id', d.contract_id, contracts, tr('none|contract')), d.contract ? tr('presets raw data, rights and closing; special rates apply to new positions') : '') : ''}
    ${clients.length ? ofdF('client_id', tr('Client'), ofdSel('client_id', d.client_id, clients, cdn_on() ? tr('No client') : tr('free recipient'))) : typeof clientsOn === 'function' && clientsOn() ? `<div class="row fx8a_nocl"><label>${esc(tr('Client'))}</label><span class="muted">${esc(tr('No clients in this area yet'))}</span>${ro ? '' : `<button type="button" class="btn sm" data-ofd="client-new">${ic('plus', 's')}<span>${tr('Add client')}</span></button>`}</div>` : ''}
    ${d.client_id && (d.client_contacts || []).length ? ofdF('contact_id', tr('Contact person'), ofdSel('contact_id', d.contact_id ?? d.client_contacts[0].id, [...d.client_contacts.map(k => [k.id, k.name + (k.role ? ` (${k.role})` : '') + (k.is_default ? ' · ' + tr('default') : '')]), [0, tr('no contact person')]]), tr('the attention line of the address follows the choice')) : ''}
    ${cdn_on() ? cdn_recHtml(d, ro) : `${ofdF('recipient_name', tr('Recipient'), ofdIn('recipient_name', d.recipient?.name, {ph: tr('Company or name')}))}
    ${ofdF('recipient_lines', tr('Address lines'), ofdTa('recipient_lines', (d.recipient?.lines || []).join('\n'), 3, {ph: tr('one line each: name, attention, street, place')}))}`}
    ${ofdF('project_title', tr('Project title'), ofdIn('project_title', d.project_title))}
    ${kind === 'delivery' ? ofdF('delivery_title', tr('Document title'), ofdSel('delivery_title', d.delivery_title || '', [['', tr('Delivery note')], ['service', tr('Proof of service')]])) : ''}
    ${kind === 'offer' ? ofdF('project_ref', tr('Ref. / PO no.'), ofdIn('project_ref', d.project_ref, {max: 80})) : ''}
    ${ofdF('date', tr('Date'), dateIn('ofd-date', d.date, {label: tr('Date'), clear: false, attrs: 'data-f="date"'}))}
    ${kind === 'offer' ? ofdF('valid_until', tr('Valid until'), dateIn('ofd-valid_until', d.valid_until, {label: tr('Valid until'), attrs: 'data-f="valid_until"'})) : ''}
    ${kind !== 'reminder' ? ofdF('service_from', tr('Service from'), dateIn('ofd-service_from', d.service_from || '', {label: tr('Service from'), attrs: 'data-f="service_from"'})) : ''}
    ${kind !== 'reminder' ? ofdF('service_to', tr('Service until'), dateIn('ofd-service_to', d.service_to || '', {label: tr('Service until'), attrs: 'data-f="service_to"', after: 'ofd-service_from'})) : ''}
    ${invFields}${remFields}
    </div>${kind === 'credit' && d.cancels ? `<p class="muted ofchint">${esc(tr('Credit note for invoice {0}', d.cancels.number || '#' + d.cancels.id))} <a href="#office/offers/${d.cancels.id}">${tr('open')}</a></p>` : ''}`);
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
  return `${head}${banner}${kind === 'invoice' && typeof rinBox === 'function' ? rinBox(d) : '' /* 2.91.0 A (#1923) */}${typeof oa_docBanner === 'function' ? oa_docBanner(d) : ''}${langNote}${typeof sg_box === 'function' ? sg_box(d) : ''}<div class="ofdeditor${kind === 'delivery' ? ' ofdls' : ''}" data-fg="ofd:${d.id}" data-fg-live><fieldset class="ofdfs" ${ro ? 'disabled' : ''}>${headSec}${kind === 'offer' && typeof tpOpenId === 'function' && tpPart(d, tpOpenId(d)) ? `<section class="ofdsec open tpsec"><h3>${esc(tr('Part'))}</h3>${tpPartEditorHtml(d, adm)}</section>` /* 2.47.0 (#1215): an open part */ : `<section class="ofdsec open"><h3>${kind === 'reminder' ? tr('Reminded invoices') : tr('Positions')}</h3>${items}${auto}${totals}</section>${typeof tpPartsHtml === 'function' ? tpPartsHtml(d, adm) : ''}`}${kind === 'reminder' || kind === 'delivery' ? '' : rightsSec}${textsSec}${kind === 'reminder' ? '' : fieldsSec}</fieldset>${kind === 'offer' && typeof cf8_box === 'function' ? cf8_box(d) : '' /* 2.88.0 (#1915) */}${ofdFeeHtml(d, adm)}${paySec}${logSec}</div>`;  // 2.50.0 (#1200): sg_box = the approval link of a sent quotation
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
  const st = d.fee_state || '', txt = {'': N_('open'), waived: N_('waived'), paid: N_('paid|fee')}[st] || st;
  const btn = (v, label) => `<button type="button" class="btn sm" data-ofd="fee" data-st="${v}">${esc(tr(label))}</button>`;
  return `<div class="ofdfeeinfo"><span>${esc(tr('Reminder fee {0}: {1}', ofdMoney(d.fee, d), tr(txt)))}</span>${adm ? (st ? btn('', N_('Open again')) : btn('waived', N_('Waive fee')) + btn('paid', N_('Fee paid'))) : ''}</div>`;
}
function ofdPaymentsHtml(d, adm) {
  const ps = d.payments || [];
  const list = ps.length ? `<ul class="ofdits ofdpays" role="list">${ps.map(p => `<li class="ofdit ofdpay"><span class="ofdpos muted">${ic('check', 's')}</span><span class="ofcn"><b>${esc(ofdMoney(p.amount, d))}</b><small class="muted">${esc([p.date ? fmtDateLoc(p.date) : '', tr(OFD_PAY.find(x => x[0] === p.method)?.[1] || p.method), p.note, p.created_by_name].filter(Boolean).join(' · '))}</small></span>${adm ? `<button type="button" class="ib" data-ofd="pay-del" data-pid="${p.id}" aria-label="${esc(tr('Remove'))}">${ic('x', 's')}</button>` : ''}</li>`).join('')}</ul>` : `<p class="muted">${tr('No payments yet.')}</p>`;
  const sum = `<p class="ofdpaysum"><span>${tr('Paid: {0}', ofdMoney(d.paid || 0, d))}</span>${+d.credits ? `<span>${tr('Credited: {0}', ofdMoney(d.credits, d))}</span>` : ''}<b>${tr('Open: {0}', ofdMoney(d.open || 0, d))}</b></p>`;
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
      <span class="muted">×</span><input data-i="${i}" data-k="rate" inputmode="decimal" class="numin ofdrate" value="${esc(ofdNumIn(it.rate))}" aria-label="${esc(tr('Rate (EUR)'))}"><span class="muted">€</span>`}
      <select data-i="${i}" data-k="tax" aria-label="${esc(tr('VAT'))}">${taxes.map(([v, n]) => `<option value="${v}" ${it.tax === v ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select>
      <b class="ofdlt">${line ? esc(line.total_text || ofdMoney(line.total, d)) : ''}</b></span>
      <span class="ofdflags">${inv ? '' : `<label class="chkl"><input type="checkbox" data-i="${i}" data-k="raw_fee" ${it.raw_fee ? 'checked' : ''}> ${tr('raw data')}</label><label class="chkl ofdprodf${it.producing ? ' on' : ''}"><input type="checkbox" data-i="${i}" data-k="producing" ${it.producing ? 'checked' : ''}> ${tr('producing')}</label><label class="chkl"><input type="checkbox" data-i="${i}" data-k="discountable" ${it.discountable ? 'checked' : ''}> ${tr('discount')}</label>`}
      ${adm ? `<label class="chkl ofdcost">${tr('Purchase')} <input data-i="${i}" data-k="cost" inputmode="decimal" class="numin" value="${esc(ofdNumIn(it.cost))}" aria-label="${esc(tr('External cost per unit (internal)'))}"></label>${it.margin != null ? `<span class="ofdmargin${it.margin < 0 ? ' neg' : ''}">${esc(tr('Surplus {0}', ofdMoney(it.margin, d)))}</span>` : ''}` : ''}</span>${typeof oa_flagHtml === 'function' ? oa_flagHtml(it, i) : ''}</div>${mv}</li>`;  // 2.51.0 A (#1348): an agent's marks
  }).join('');
  return `<ul class="ofdits" role="list">${rows}</ul><div class="ofdadd"><button type="button" class="btn sm pri" data-ofd="it-svc">${ic('plus', 's')}<span>${tr('Add service')}</span></button><button type="button" class="btn sm" data-ofd="it-head">${ic('list', 's')}<span>${tr('Heading')}</span></button><button type="button" class="btn sm" data-ofd="it-text">${ic('note', 's')}<span>${tr('Text block')}</span></button>${inv && d.kind !== 'delivery' ? `<button type="button" class="btn sm" data-ofd="it-disc">${ic('calc', 's')}<span>${tr('Discount')}</span></button>` : ''}</div>`;
}
// 2.114.3 (#2266): which positions the producing switch counts; in a part whether its producing values are the document's or its own
function ofdProdHint(d) {
  const p = d.tpPart;
  if (!p) return `<span class="muted ofchint ofdprodhint">${esc(d.kind === 'offer' ? tr('Applies to the positions of this page with a producing tick. Parts without an own setting take over the switch and calculate their producing themselves.') : tr('Applies to the positions with a producing tick.'))}</span>`;
  const own = ['producing_on', 'prod_quotient', 'producing_rate'].some(k => (p.settings || {})[k] != null);
  return `<span class="muted ofchint ofdprodhint">${esc(tr('Applies to the positions of this part with a producing tick.'))}</span>
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
  const lines = (t.lines || []).filter(l => ['producing', 'raw', 'discount'].includes(l.kind));
  const prod = lines.find(l => l.kind === 'producing'), raw = lines.find(l => l.kind === 'raw'), disc = lines.find(l => l.kind === 'discount');
  const rowL = (title, detail, total) => `<li class="ofdauto"><span class="ofdpos muted">${ic('calc', 's')}</span><span class="ofcn"><b>${esc(title)}</b>${detail ? `<small class="muted">${esc(detail)}</small>` : ''}</span><b class="ofdlt">${esc(total)}</b></li>`;
  return `<ul class="ofdits ofdautos" role="list">
    ${prod ? rowL(prod.title, prod.detail, prod.total_text || ofdMoney(prod.total, d)) : pOn ? rowL(t.labels?.producing || 'Producing', tr('no position counts towards producing'), '') : ''}
    ${raw ? rowL(raw.title, raw.detail, raw.total_text || ofdMoney(raw.total, d)) : ''}
    ${disc ? rowL(disc.title, disc.detail, disc.total_text || ofdMoney(disc.total, d)) : ''}</ul>
    <div class="ofdgrid ofdrules">
    ${ofdF('raw_mode', tr('Raw data'), ofdSel('raw_mode', d.raw_mode, OFD_RAW.map(([v, n]) => [v, tr(n)])))}
    ${d.raw_mode !== 'none' ? ofdF('raw_factor', tr('Raw data factor'), ofdIn('raw_factor', ofdNumIn(d.raw_factor), {num: true, max: 10}), tr('share of the positions with raw data')) : ''}
    <div class="row"><label class="chkl" style="min-width:0"><input type="checkbox" id="ofd-producing_on" data-f="producing_on" ${pOn ? 'checked' : ''}> ${tr('Calculate producing')}</label>${ofdProdHint(d)}</div>
    ${pOn ? `${ofdF('prod_quotient', tr('Producing quotient'), ofdIn('prod_quotient', ofdNumIn(d.prod_quotient), {num: true, max: 10}), tr('production days per producing day'))}
    ${ofdF('producing_rate', tr('Producing rate'), ofdIn('producing_rate', ofdNumIn(d.producing_rate), {num: true, max: 12}), '€')}` : ''}
    ${ofdF('discount_pct', tr('Discount'), ofdIn('discount_pct', ofdNumIn(d.discount_pct), {num: true, max: 8}), '%')}
    </div>`;
}
function ofdTotalsHtml(d, t, adm) {
  const L = t.labels || {};
  if (ofdIsInv(d)) {  // 2.38.0: invoice sums are exact strings; subtotal, tax per rate, total, paid / open
    const rows = d.kind === 'reminder' ? [[tr('Amount outstanding'), ofdMoney(t.net || 0, d), 'net'], ...(+t.fee ? [[tr('Reminder fee'), ofdMoney(t.fee, d), 'tax']] : []), [tr('Total'), ofdMoney(t.gross || 0, d), 'gross']]
      : [[tr('Subtotal'), ofdMoney(t.net || 0, d), 'net'], ...(t.tax_lines || []).map(x => [x.label, x.amount_text || ofdMoney(x.amount, d), 'tax']), [tr('Total'), ofdMoney(t.gross || 0, d), 'gross']];
    if (d.kind === 'invoice' && d.locked && (+d.paid || +d.credits)) rows.push([tr('Amount outstanding'), ofdMoney(d.open || 0, d), 'open']);
    return `<div class="ofdtotals" id="ofd-totals"><dl>${rows.map(([k, v, c]) => `<div class="ofdtr tr-${c}"><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('')}</dl>
      <p class="muted ofdnote">${esc(t.vat_note || '')}${t.fx_note ? ` · ${esc(t.fx_note)}` : ''}${t.tax_eur_text ? ` · ${esc(tr('tax in EUR: {0}', t.tax_eur_text))}` : ''}</p>
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

// ---- the history (organisation admins; office log of this document)
const OFD_ACTIONS = {create: N_('created'), update: N_('changed'), items: N_('positions changed'), number: N_('number set'), status: N_('status changed'),
  finalize: N_('finalised'), unlock: N_('finalising undone'), duplicate: N_('created as a copy'), cashflow: N_('cash flow choice changed'), delete: N_('deleted'), open: N_('opened'), pdf: N_('PDF opened'), render: N_('preview opened'),
  export: N_('exported'), import: N_('imported'), archive: N_('archived'), upload: N_('uploaded'),
  payment: N_('payment recorded'), payment_delete: N_('payment removed'), send: N_('sent by e-mail'), datev: N_('sent to the DATEV inbox'), undo: N_('import undone'), reminder_fee: N_('reminder fee waived / paid / open again'), recovery_key: N_('recovery key shown'),
  agent_read: N_('read (agent)'), agent_write: N_('drafted (agent)'), from_sheet: N_('created from a table')};  // 2.89.0 (#1916, D): + from_sheet  // 2.51.0 A (#1348)  // 2.42.0 (#828): + recovery_key  // 2.39.1 (#1182): + undo; 2.40.0 (#1368): + reminder_fee
const ofdActText = a => tr(OFD_ACTIONS[a] || a);
const ofdWhen = iso => { try { return new Date(iso).toLocaleString(LOCALE(), {dateStyle: 'short', timeStyle: 'short'}); } catch { return iso || ''; } };
function ofdLogHtml(d) {
  if (!OFD.open.log) return `<p class="muted">${tr('Open to load the history.')}</p>`;
  if (OFD.logFor !== d.id || !OFD.log) { setTimeout(() => ofdLoadLog(d.id), 0); return `<p class="muted lempty">${tr('Loading…')}</p>`; }
  if (!OFD.log.length) return `<p class="muted">${tr('No entries yet.')}</p>`;
  return `<ul class="ofdlog" role="list">${OFD.log.map(x => { const ks = Object.keys(x.detail?.after || {}); return `<li><span class="muted">${esc(ofdWhen(x.at))}</span> <b>${esc(x.user_name || x.detail?.name || '?')}</b> ${esc(ofdActText(x.action))}${ks.length && x.action === 'update' ? ` <span class="muted">(${esc(ks.join(', '))})</span>` : ''}</li>`; }).join('')}</ul>`;
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
const ofdPdfUrl = (id, inline) => `/api/office/docs/${id}/pdf${inline && !/; wv\)/.test(navigator.userAgent || '') ? '?inline=1' : ''}`;
async function ofdSave(method, url, body) {
  OFD.saving++; ofdSaveHint();
  try { const j = await rawFetch(method, url, body); if (OFD.doc && j && j.id === OFD.doc.id) OFD.doc = j.items ? j : {...OFD.doc, ...j}; /* the status answer has no positions */ OFD.err = ''; if (j && j.lang_notes) OFD.langNotes = {id: j.id, notes: j.lang_notes}; return j; }
  catch (x) { OFD.err = x.message || tr('unknown'); toast(OFD.err); return null; }
  finally { OFD.saving--; OFD.log = null; ofdDraw(); OFD.list = null; }
}
function ofdSaveHint() { const s = $('.ofdsave'); if (s) s.textContent = OFD.saving ? tr('Saving…') : ''; }
const ofdPatch = body => typeof tpView === 'function' && tpView() ? tpPatch(body) : ofdSave('PATCH', `/api/office/docs/${OFD.doc.id}`, body);
// 2.114.1 A (#2254): a new heading / text line stays local until something is typed; the server would reject it empty (a saved
// one keeps its id and is sent as before, emptying it never drops it silently)
const bfaFilled = it => it.id || !((it.kind === 'heading' || it.kind === 'text') && !(it.title || '').trim() && !(it.detail || '').trim());
function ofdItemsBody() {
  return (OFD.doc.items || []).filter(bfaFilled).map(it => ({id: it.id, kind: it.kind, service_id: it.service_id, title: it.title, detail: it.detail, qty: it.qty, unit: it.unit, rate: it.rate, tax: it.tax,
    raw_fee: it.raw_fee, producing: it.producing, intext: it.intext, cost: it.cost, discountable: it.discountable, ref_part_id: it.ref_part_id, confirm: it.confirm || undefined}));  // 2.47.0 (#1215): + ref_part_id; 2.51.0 A (#1348): + confirm (an agent's mark)
}
// 2.47.0 (#1215): with a part open, positions and calculation values go to the part (office_parts.js)
const ofdPutItems = () => typeof tpView === 'function' && tpView() ? tpPutItems() : ofdSave('PUT', `/api/office/docs/${OFD.doc.id}/items`, {items: ofdItemsBody(), ...(OFD.doc.kind === 'offer' ? {parts_known: (OFD.doc.parts || []).map(p => p.id)} : {})});  // 2.138.0 A (#2239): + parts_known
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
  if (t.id === 'ofd-status' && !OFD.doc) { OFD.status = t.value; OFD.list = null; ofdLoadList(true); return; }
  if (t.id === 'ofd-status' && OFD.doc && S.route.id !== OFD.doc.id) { OFD.status = t.value; OFD.list = null; ofdLoadList(true); return; }
  if (!OFD.doc) return;
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
  if (['fx_rate', 'raw_factor', 'prod_quotient', 'producing_rate', 'discount_pct', 'payment_days', 'reminder_level', 'reminder_fee', 'reminder_deadline_days', 'skonto_pct', 'skonto_days'].includes(f)) { const v = ofcNum(t.value); await ofdPatch({[f]: v}); return; }
  await ofdPatch({[f]: t.value});
}
// 2.87.9 (#1920): the "More" menu of a document - one list for the editor and for the rows of the list (d = the document or a list row)
function ofdMoreItems(d, inList) {
  const gone = () => { OFD.doc = null; OFD.list = null; if (inList) ofdLoadList(true); else go('office/offers'); };
  const items = [
      {label: tr('Duplicate'), icon: 'copy', fn: async () => { try { const j = await rawFetch('POST', `/api/office/docs/${d.id}/duplicate`); OFD.list = null; OFD.doc = j; toast(tr('Copied as {0}', j.number || tr('Draft'))); go(`office/offers/${j.id}`); } catch (x) { toast(x.message || tr('unknown')); } }},
      d.kind === 'offer' && d.client_id && ofcAdmin() && typeof dtFromOffer === 'function' ? {label: tr('Create order confirmation'), icon: 'file', fn: () => dtFromOffer(d)} : null,  // 2.93.0 A (#1927)
      {label: tr('Preview (PDF)'), icon: 'eye', fn: () => typeof pdfView === 'function' ? pdfView({url: ofdPdfUrl(d.id, true), name: (d.number || tr('Document')) + '.pdf', dlUrl: ofdPdfUrl(d.id)}) : window.open(ofdPdfUrl(d.id, true), '_blank', 'noopener')},  // 2.40.0 (#1364): the PDF, not the JSON print model
      ...(typeof ls_moreItems === 'function' ? ls_moreItems(d, inList) : []),  // 2.120.0 D (#2089)
      ofdIsInv(d) && d.kind !== 'reminder' && d.kind !== 'delivery' && d.locked ? {label: tr('E-invoice XML'), icon: 'download', fn: () => window.open(`/api/office/docs/${d.id}/xml`, '_blank', 'noopener')} : null,
      ofdIsInv(d) && d.kind !== 'reminder' && d.kind !== 'delivery' && d.locked ? {label: tr('Send to the DATEV inbox'), icon: 'send', fn: async () => { const j = await ofdSave('POST', `/api/office/docs/${d.id}/datev`); if (j) toast(tr('Sent to the DATEV inbox')); }} : null,
      d.status === 'draft' && !d.locked && typeof ofm_can === 'function' && ofm_can(ofm_officeFrom()) ? {label: tr('Move to another workspace…'), icon: 'brief',  // 2.97.0 C (#2049)
        fn: () => ofm_move({what: 'drafts', ids: [d.id], from: ofm_officeFrom(), label: qn(d.number || d.project_title || ofdKindName(d.kind, true)), after: async () => gone()})} : null,
      d.can_unlock ? {label: tr('Undo finalising'), icon: 'undo', fn: async () => {  // 2.114.2 A (#2263): a finalised quotation never sent
        if (!await askConfirm(tr('Back to a draft?'), tr('The quotation can be changed again and keeps its number {0}.', d.number || ''), {ok: tr('Undo finalising')})) return;
        try { const j = await rawFetch('POST', `/api/office/docs/${d.id}/unlock`); OFD.list = null; OFD.log = null; if (inList) ofdLoadList(true); else { OFD.doc = j; ofdDraw(); } toast(tr('Back to a draft')); } catch (x) { toast(x.message || tr('unknown')); }
      }} : null,
      d.can_delete ? '-' : null,
      d.can_delete ? {label: tr('Delete'), icon: 'trash', cls: 'danger', fn: async () => {
        if (!await askConfirm(tr('Delete {0}?', d.number || ofdKindName(d.kind, true)), d.locked ? tr('Its number stays used and shows as a gap in the office log.') : tr('Its number stays used.'), {ok: tr('Delete'), danger: true})) return;  // 2.114.2 A (#2263)
        try { await api('DELETE', `/api/office/docs/${d.id}`); gone(); toast(tr('Deleted')); } catch (x) { toast(x.message || tr('unknown')); }
      }} : null];
  return inList ? [{label: tr('Open'), icon: 'edit', fn: () => go(`office/offers/${d.id}`)}, ...items] : items;
}
// 2.87.9 (#1920): right click / long press on a row opens the same menu as the dots button
function ofdRowMenu(id, anchor) {
  const r = (OFD.list || []).find(x => String(x.id) === String(id)); if (!r) return;
  menu(anchor, ofdMoreItems({...r, can_delete: OFD.role === 'admin' && (r.can_delete || (!r.locked && r.status !== 'sent' && !(['invoice', 'credit'].includes(r.kind) && r.number)))}, true));  // 2.114.2 A (#2263): the server marks the finalised quotations that may go; 2.126.0 A (#1966): a numbered invoice / credit note draft stays
}
function ofdCtx(e) { const b = e.target.closest('.ofdrow'); if (!b) return; e.preventDefault(); ofdRowMenu(b.dataset.id, b); }
async function ofdClick(e) {
  const b = e.target.closest('[data-ofd]'); if (!b) return;
  const a = b.dataset.ofd, d = typeof tpCur === 'function' ? tpCur() : OFD.doc;  // 2.47.0 (#1215): an open part's positions
  if (a === 'pdf') return;  // the link itself
  e.preventDefault();
  if (a === 'new') {
    try { const j = await rawFetch('POST', '/api/office/docs', {}); OFD.doc = j; OFD.list = null; go(`office/offers/${j.id}`); } catch (x) { toast(x.message || tr('unknown')); }
    return;
  }
  if (a === 'new-ls' || a === 'to-ls') return ls_click(a, d);  // 2.120.0 D (#2089)
  if (a === 'open') { if (typeof ms_lpRecent === 'function' && OFD.lp && ms_lpRecent(OFD.lp)) return; go(`office/offers/${b.dataset.id}`); return; }
  if (a === 'rowmore') { ofdRowMenu(b.dataset.id, b); return; }
  if (a === 'back') { OFD.doc = null; OFD.list = null; go('office/offers'); return; }
  if (a === 'kind') { OFD.kind = b.dataset.kind; OFD.status = ''; OFD.list = null; ofdLoadList(true); return; }
  if (a === 'new-inv') {
    menu(b, [{label: tr('Empty invoice'), icon: 'plus', fn: () => ofdCreate({kind: 'invoice'})}, {label: tr('From time entries…'), icon: 'clock', fn: ofdFromTimeDialog},
      {label: tr('From a quotation: open it and press "Create invoice"'), fn: () => { OFD.kind = 'offer'; OFD.list = null; ofdLoadList(true); }}]);
    return;
  }
  if (a === 'remind') { ofdReminderDialog(); return; }
  if (!d) return;
  if (a.startsWith('tp-') && typeof tpClick === 'function') { await tpClick(a, b); return; }  // 2.47.0 (#1215): the parts
  if (a === 'to-invoice') { absInvoiceDialog(d); return; }  // 2.120.0 A (#2087): full / progress / final (a quotation with parts: full -> tpInvoiceDialog)
  if (a === 'to-invoice' && d.parts?.length && typeof tpInvoiceDialog === 'function') { tpInvoiceDialog(d); return; }  // 2.47.0 (#1215): choose the form
  if (a === 'to-invoice') { try { const j = await rawFetch('POST', `/api/office/docs/${d.id}/invoice`); OFD.list = null; OFD.kind = 'invoice'; OFD.doc = j; toast(tr('Invoice draft created')); go(`office/offers/${j.id}`); } catch (x) { toast(x.message || tr('unknown')); } return; }
  if (a === 'credit') {
    if (!await askConfirm(tr('Credit note for {0}?', d.number || ''), tr('A draft with all positions is made. Shorten it for a partial credit; finalised over the full amount it cancels the invoice.'), {ok: tr('Create credit note')})) return;
    try { const j = await rawFetch('POST', `/api/office/docs/${d.id}/credit`); OFD.list = null; OFD.kind = 'credit'; OFD.doc = j; go(`office/offers/${j.id}`); } catch (x) { toast(x.message || tr('unknown')); } return;
  }
  if (a === 'pay') { ofdPaymentDialog(d); return; }
  if (a === 'pay-del') {
    if (!await askConfirm(tr('Remove this payment?'), '', {ok: tr('Remove'), danger: true})) return;
    const j = await ofdSave('DELETE', `/api/office/docs/${d.id}/payments/${b.dataset.pid}`); if (j) toast(tr('Removed')); return;
  }
  if (a === 'send') { ofdSendDialog(d); return; }
  if (a === 'ln-x') { OFD.langNotes = null; ofdDraw(); return; }
  if (a === 'fee') { const j = await ofdSave('POST', `/api/office/docs/${d.id}/fee`, {state: b.dataset.st || ''}); if (j) toast(tr('Saved')); return; }
  if (a === 'it-disc') { d.items.push({kind: 'discount', title: '', detail: '', qty: 1, unit: 'flat', rate: 0, tax: 'standard', raw_fee: 0, producing: 0, intext: 'intern', cost: 0, discountable: 1}); await ofdPutItems(); $(`.ofdits [data-i="${d.items.length - 1}"][data-k="rate"]`)?.focus(); return; }
  if (a === 'number') { const j = await ofdSave('POST', `/api/office/docs/${d.id}/number`, {}); if (j) { d.number = j.number; ofdDraw(); } return; }
  if (a === 'finalize') {
    if (!await askConfirm(tr('Finalise this document?'), tr('Number, positions, sums, sender and tax rates are frozen. Afterwards it can only be duplicated.'), {ok: tr('Finalise')})) return;
    const j = await ofdSave('POST', `/api/office/docs/${d.id}/finalize`, {}); if (j) toast(tr('Finalised as {0}', j.number || ''));
    return;
  }
  if (a === 'dup') { try { const j = await rawFetch('POST', `/api/office/docs/${d.id}/duplicate`); OFD.list = null; OFD.doc = j; toast(tr('Copied as {0}', j.number || tr('Draft'))); go(`office/offers/${j.id}`); } catch (x) { toast(x.message || tr('unknown')); } return; }
  if (a === 'more') { menu(b, ofdMoreItems(d)); return; }
  if (a === 'it-svc') { ofdServicePicker(); return; }
  if (a === 'it-head') { d.items.push({kind: 'heading', title: '', detail: '', qty: 1, unit: 'day', rate: 0, tax: 'standard', raw_fee: 0, producing: 0, intext: 'intern', cost: 0, discountable: 1}); ofdDraw();  // 2.114.1 A (#2254): saved with the first typed title
    $(`.ofdits [data-i="${d.items.length - 1}"][data-k="title"]`)?.focus(); return; }
  if (a === 'it-text') {
    const blocks = ofcRows('texts').filter(x => x.kind === 'block' && !x.archived);
    const add = async text => { d.items.push({kind: 'text', title: '', detail: text, qty: 1, unit: 'day', rate: 0, tax: 'standard', raw_fee: 0, producing: 0, intext: 'intern', cost: 0, discountable: 1}); if (text) await ofdPutItems(); else ofdDraw(); if (!text) $(`.ofdits [data-i="${d.items.length - 1}"][data-k="detail"]`)?.focus(); };
    if (!blocks.length) { await add(''); return; }
    menu(b, [{label: tr('Free text'), icon: 'edit', fn: () => add('')}, '-', ...blocks.map(x => ({label: x.key || (x.text_de || x.text_en).slice(0, 50), fn: () => add(ofcText(x.id, ofdLang(d)))}))]);
    return;
  }
  if (a === 'it-del') { d.items.splice(+b.dataset.i, 1); await ofdPutItems(); return; }
  if (a === 'it-up' || a === 'it-down') { const i = +b.dataset.i, j = a === 'it-up' ? i - 1 : i + 1; if (j < 0 || j >= d.items.length) return; [d.items[i], d.items[j]] = [d.items[j], d.items[i]]; await ofdPutItems(); setTimeout(() => $(`.ofdits [data-ofd="${a}"][data-i="${j}"]`)?.focus(), 0); return; }
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
  try { const j = await rawFetch('POST', '/api/office/docs', body); OFD.doc = j; OFD.list = null; OFD.kind = j.kind; go(`office/offers/${j.id}`); } catch (x) { toast(x.message || tr('unknown')); }
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
    t === 'final' ? tr('deducts the finalised progress invoices of the quotation') : '')
    + ofdF('skonto_pct', tr('Cash discount'), `<span class="lacts">${ofdIn('skonto_pct', d.skonto_pct ? ofdNumIn(d.skonto_pct) : '', {num: true, max: 6})}<span class="muted">%</span>${ofdIn('skonto_days', d.skonto_days ?? '', {num: true, max: 3})}<span class="muted">${tr('days')}</span></span>`, tr('empty = no cash discount'));
}
async function absInvoiceDialog(d) {
  let info;
  try { info = await api('GET', `/api/office/docs/${d.id}/progress`); } catch (x) { toast(x.message || tr('unknown')); return; }
  const pl = info.progress || [], cur = d.currency === 'USD' ? '$' : '€';
  const plist = pl.length ? `<ul class="ofdpick abs-list" role="list">${pl.map(p => `<li><span class="ofcn"><b>${esc(p.number || tr('Draft'))}</b><small class="muted">${esc([p.date ? fmtDateLoc(p.date) : '', p.gross_text, !p.locked ? tr('Draft') : +p.open <= 0 ? tr('Paid') : tr('open: {0}', p.open_text || p.open)].filter(Boolean).join(' · '))}</small></span></li>`).join('')}</ul>`
    : `<p class="muted">${tr('No progress invoices yet')}</p>`;
  const modes = [['full', tr('Full invoice')], ['progress', tr('Progress invoice')], ['final', tr('Final invoice')]];
  const md = ofdDlg(tr('Create invoice'), `<fieldset class="tpmodes"><legend class="muted">${tr('Type of invoice')}</legend>${modes.map(([v, n], i) => `<label class="tpmode"><input type="radio" name="abs-type" value="${v}" ${i ? '' : 'checked'}> <span>${esc(n)}</span></label>`).join('')}</fieldset>
    <div class="abs-p" hidden>${ofdF('abs-val', tr('Progress payment'), `<span class="lacts"><input id="ofd-abs-val" inputmode="decimal" class="numin" maxlength="14">${ofcSel('ofd-abs-unit', 'pct', [['pct', '%'], ['amount', cur + ' ' + tr('net')]])}</span>`, tr('quotation net {0}, not yet billed {1}', info.net_text, info.remaining_text))}</div>
    <div class="abs-f" hidden><p class="muted ofchint">${tr('The whole quotation, less these progress invoices (finalised ones only):')}</p>${plist}</div>`,
    tr('Create invoice'), async m => {
      const typ = $('input[name="abs-type"]:checked', m)?.value || 'full';
      if (typ === 'full' && d.parts?.length && typeof tpInvoiceDialog === 'function') { setTimeout(() => tpInvoiceDialog(d), 0); return; }
      const b = {};
      if (typ !== 'full') b.inv_type = typ;
      if (typ === 'progress') { const v = ofcNum($('#ofd-abs-val', m).value); if (!v) throw new Error(tr('Enter an amount or a percentage')); b[$('#ofd-abs-unit', m).value] = v; }
      const j = await rawFetch('POST', `/api/office/docs/${d.id}/invoice`, b);
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
  const today = new Date(), first = new Date(today.getFullYear(), today.getMonth(), 1), iso = x => x.toISOString().slice(0, 10);
  ofdDlg(tr('Invoice from time entries'), ofdF('ft-client', tr('Client'), ofcSel('ofd-ft-client', '', cl)) + ofdF('ft-from', tr('From'), dateIn('ofd-ft-from', iso(first), {label: tr('From'), clear: false}))
    + ofdF('ft-to', tr('Until'), dateIn('ofd-ft-to', iso(today), {label: tr('Until'), clear: false, after: 'ofd-ft-from'})) + `<p class="muted ofchint">${tr('One position per list with the hours of the period; the rate comes from the client or is filled in afterwards.')}</p>`,
    tr('Create'), async md => { const j = await rawFetch('POST', '/api/office/docs/from-time', {client_id: +$('#ofd-ft-client', md).value, from: $('#ofd-ft-from', md).value, to: $('#ofd-ft-to', md).value}); OFD.list = null; OFD.kind = 'invoice'; OFD.doc = j; go(`office/offers/${j.id}`); });
}
function ofdPaymentDialog(d) {
  ofdDlg(tr('Record payment'), ofdF('p-date', tr('Date'), dateIn('ofd-p-date', new Date().toISOString().slice(0, 10), {label: tr('Date'), clear: false}))
    + ofdF('p-amount', tr('Amount'), `<span class="lacts"><input id="ofd-p-amount" inputmode="decimal" class="numin" value="${esc(ofdNumIn(d.open))}" maxlength="14"><span class="muted">${d.currency === 'USD' ? '$' : '€'}</span></span>`)
    + ofdF('p-method', tr('Method'), ofcSel('ofd-p-method', 'transfer', OFD_PAY.map(([v, n]) => [v, tr(n)]))) + ofdF('p-note', tr('Note'), `<input id="ofd-p-note" maxlength="500">`),
    tr('Record'), async md => { const j = await ofdSave('POST', `/api/office/docs/${d.id}/payments`, {date: $('#ofd-p-date', md).value, amount: ofcNum($('#ofd-p-amount', md).value), method: $('#ofd-p-method', md).value, note: $('#ofd-p-note', md).value}); if (!j) return false; toast(j.state === 'paid' ? tr('Paid in full') : tr('Payment recorded')); });
}
async function ofdSendDialog(d) {
  let ms = {smtp: true, datev_email: ''};
  try { ms = await api('GET', '/api/office/mail-status'); } catch {}
  const cl = (S.clients || []).find(c => c.id === d.client_id);
  const to = cl?.billing?.email_invoice || cl?.email || '';
  // 2.40.0 (#1368 point 10): plain words for people who do not run the server; without mail the button downloads the PDF
  const hint = !ms.smtp ? `<p class="ofdwarn">${esc(S.me?.is_admin ? tr('Sending e-mail is not set up on this server (KALMIDO_SMTP_HOST); download the PDF instead.')
    : tr('Sending e-mail is not set up yet. Download the PDF and send it with your own mail program, or ask the administrator to set up mail sending.'))}</p>` : '';
  ofdDlg(tr('Send {0}', d.number || ''), hint + ofdF('s-to', tr('To|mail recipient'), `<input id="ofd-s-to" type="email" value="${esc(to)}" maxlength="200" ${ms.smtp ? '' : 'disabled'}>`)
    + ofdF('s-cc', tr('Copy to'), `<input id="ofd-s-cc" type="email" maxlength="200" ${ms.smtp ? '' : 'disabled'}>`)
    + ofdF('s-subject', tr('Subject'), `<input id="ofd-s-subject" value="${esc(`${ofdKindName(d.kind, true)} ${d.number || ''}`)}" maxlength="200" ${ms.smtp ? '' : 'disabled'}>`)
    + ofdF('s-text', tr('Text'), `<textarea id="ofd-s-text" rows="4" maxlength="8000" placeholder="${esc(tr('empty = the standard text'))}" ${ms.smtp ? '' : 'disabled'}></textarea>`)
    + (d.timesheet_ok ? `<div class="row"><label class="chkl" style="min-width:0"><input type="checkbox" id="ofd-s-ts"> ${tr('Attach the timesheet')}</label></div>` : '')  // 2.120.0 D (#2089)
    + (d.kind !== 'reminder' && d.kind !== 'delivery' ? `<div class="row"><label class="chkl" style="min-width:0"><input type="checkbox" id="ofd-s-datev" ${ms.datev_email && ms.datev_auto ? 'checked' : ''} ${ms.datev_email && ms.smtp ? '' : 'disabled'}> ${tr('Copy to the DATEV inbox')}${ms.datev_email ? ` <span class="muted">(${esc(ms.datev_email)})</span>` : ` <span class="muted">${tr('(no address in the settings)')}</span>`}</label></div>` : ''),
    ms.smtp ? tr('Send|mail') : tr('Download PDF'), async md => { if (!ms.smtp) { const a = document.createElement('a'); a.href = ofdPdfUrl(d.id); a.download = ''; document.body.appendChild(a); a.click(); a.remove(); return; } const j = await ofdSave('POST', `/api/office/docs/${d.id}/send`, {to: $('#ofd-s-to', md).value.trim(), cc: $('#ofd-s-cc', md).value.trim(), subject: $('#ofd-s-subject', md).value, text: $('#ofd-s-text', md).value, datev: !!$('#ofd-s-datev', md)?.checked, timesheet: !!$('#ofd-s-ts', md)?.checked}); if (!j) return false; toast(tr('Sent')); });
}
async function ofdReminderDialog() {
  let rows = [];
  try { rows = (await api('GET', '/api/office/docs?kind=invoice')).docs.filter(r => ['issued', 'sent', 'partial', 'overdue'].includes(r.state)); } catch (x) { toast(x.message || tr('unknown')); return; }
  if (!rows.length) { toast(tr('No open invoices')); return; }
  const s = OFC.info?.settings || {};
  const list = `<ul class="ofdpick" role="list">${rows.map(r => `<li><label class="chkl"><input type="checkbox" data-rid="${r.id}" data-cid="${r.client_id || ''}" ${r.state === 'overdue' ? 'checked' : ''}> <span class="ofcn"><b>${esc(r.number)}${r.recipient_name ? ` · ${esc(r.recipient_name)}` : ''}</b><small class="muted">${esc([r.due_date ? tr('due {0}', fmtDateLoc(r.due_date)) : '', r.status_text, tr('open: {0}', r.open_text || r.open)].filter(Boolean).join(' · '))}</small></span></label></li>`).join('')}</ul>`;
  const md0 = ofdDlg(tr('Create reminder'), `<p class="muted ofchint">${tr('Pick the open invoices of one client.')}</p>${list}<p class="ofdwarn" id="ofd-r-warn" hidden></p>` + ofdF('r-level', tr('Reminder level'), ofcSel('ofd-r-level', 1, [[1, tr('1 - payment reminder')], [2, tr('2 - reminder')], [3, tr('3 - final reminder')]]))
    + ofdF('r-fee', tr('Reminder fee'), `<input id="ofd-r-fee" inputmode="decimal" class="numin" value="${esc(ofdNumIn(s.reminder_fee ?? 0))}" maxlength="10">`) + ofdF('r-days', tr('Payment deadline'), `<span class="lacts"><input id="ofd-r-days" inputmode="numeric" class="numin" value="${esc(String(s.reminder_deadline_days ?? 10))}" maxlength="3"><span class="muted">${tr('days')}</span></span>`),
    tr('Create'), async md => {
      const picked = [...md.querySelectorAll('[data-rid]:checked')];
      if (!picked.length) throw new Error(tr('Pick at least one invoice'));
      if (new Set(picked.map(x => x.dataset.cid)).size > 1) throw new Error(tr('One reminder covers the invoices of one client'));
      const j = await rawFetch('POST', '/api/office/docs/reminder', {doc_ids: picked.map(x => +x.dataset.rid), level: +$('#ofd-r-level', md).value, fee: ofcNum($('#ofd-r-fee', md).value), deadline_days: ofcNum($('#ofd-r-days', md).value)});
      OFD.list = null; OFD.kind = 'reminder'; OFD.doc = j; go(`office/offers/${j.id}`);
    });
  // 2.40.0 (#1368 point 7): hints only, no block: a high fee (private clients: only the actual costs, usually 2-5 €) and invoices not yet due
  const warn = () => {
    const w = $('#ofd-r-warn', md0); if (!w) return;
    const fee = ofcNum($('#ofd-r-fee', md0).value) || 0, today = new Date().toISOString().slice(0, 10);
    const notDue = [...md0.querySelectorAll('[data-rid]:checked')].map(x => rows.find(r => r.id === +x.dataset.rid)).filter(r => r && (!r.due_date || r.due_date >= today));
    const msg = [fee > 5 ? tr('Private clients may only be charged the actual costs of a reminder (usually 2 to 5 €).') : '', notDue.length ? tr('Not yet due: {0}. A reminder usually follows the due date.', notDue.map(r => r.number).join(', ')) : ''].filter(Boolean);
    w.innerHTML = msg.map(esc).join('<br>'); w.hidden = !msg.length;
  };
  md0.addEventListener('input', warn); md0.addEventListener('change', warn); warn();
}
// the service picker: search the catalogue, tap = a new position with the service's name (document language), rate and flags
function ofdServicePicker() {
  const d = typeof tpCur === 'function' ? tpCur() : OFD.doc;  // 2.47.0 (#1215): into an open part
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
    if (b.dataset.m === 'close' || b.dataset.m === 'tab') { md.remove(); return; }  // (tab: the link goes on to #office/services)
    if (b.dataset.m === 'part' && typeof tpPick === 'function') { md.remove(); await tpPick(+b.dataset.pid); return; }  // 2.47.0 (#1215)
    const blank = {kind: 'service', service_id: null, title: '', detail: '', qty: 1, unit: 'day', rate: 0, tax: 'standard', raw_fee: 0, producing: 0, intext: 'intern', cost: 0, discountable: 1};
    if (b.dataset.m === 'free') { d.items.push(blank); md.remove(); await ofdPutItems(); $(`.ofdits [data-i="${d.items.length - 1}"][data-k="title"]`)?.focus(); return; }
    const s = ofcRow('services', +b.dataset.sid); if (!s) return;
    const ct = d.contract?.rates?.[s.id];
    d.items.push({...blank, cost: null /* 2.47.0 (#1649): the server takes the purchase of the service's role */, service_id: s.id, title: ofdSvcName(s, d), unit: s.unit || 'day', rate: ct ?? (s.unit === 'hour' && s.hourly_rate != null ? s.hourly_rate : s.daily_rate) ?? 0, tax: s.tax || 'standard', raw_fee: s.raw_fee ? 1 : 0, producing: s.producing ? 1 : 0, intext: s.intext || 'intern'});
    md.remove(); await ofdPutItems();
    $(`.ofdits [data-i="${d.items.length - 1}"][data-k="qty"]`)?.focus();
  });
  setTimeout(() => { if (!isTouch()) $('#ofd-sq', md)?.focus(); }, 50);
}
// the editor's open sections are remembered while the page lives
document.addEventListener('toggle', e => { const s = e.target?.dataset?.sec; if (s && e.target.classList?.contains('ofdsec')) { const was = OFD.open[s]; OFD.open[s] = e.target.open; if (s === 'log' && e.target.open && !was) ofdDraw(); } }, true);

// 2.120.0 D (#2089): delivery notes / proofs of service and the timesheet of an invoice
function ls_click(a, d) {
  if (a === 'new-ls') return ofdCreate({kind: 'delivery'});
  const make = async title => { try { const j = await rawFetch('POST', `/api/office/docs/${d.id}/delivery`, {title}); OFD.list = null; OFD.kind = 'delivery'; OFD.doc = j; go(`office/offers/${j.id}`); } catch (x) { toast(x.message || tr('unknown')); } };
  menu($('[data-ofd="to-ls"]'), [{label: tr('Create delivery note'), icon: 'file', fn: () => make('delivery')}, {label: tr('Create proof of service'), icon: 'file', fn: () => make('service')}]);
}
function ls_moreItems(d, inList) {
  return !inList && d.timesheet_ok ? [{label: tr('Timesheet (PDF)'), icon: 'clock', fn: () => window.open(`/api/office/docs/${d.id}/timesheet.pdf?inline=1`, '_blank', 'noopener')}] : [];
}
