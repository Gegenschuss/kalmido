// Office & finance (2.36.1, #1021), part C: quotations -- the tab "Quotations" of the office view (office.js calls
// ofdOffersTab(el)) with the list and the editor (#office/offers/<id>). The server computes the sums (kalmido/office/calc.py)
// on every change and returns them; the editor shows exactly those figures in the document's language and currency.
const OFD = {list: null, next: null, more: false, listQ: '', loading: false, q: '', status: '', trial: LS.get('ofdTrial', '') || '', first: null, office: null, trialCount: 0, kind: 'offer', kindOf: {}, sec: '', doc: null, docId: null, docLoading: false, seq: 0, saving: 0, err: '', open: {head: true, rights: true, texts: false, fields: false, log: false, pay: true}, log: null, logFor: 0};
const OFD_STATUS = [['draft', N_('Draft')], ['sent', N_('Sent|document')], ['accepted', N_('Accepted|document')], ['declined', N_('Rejected')], ['superseded', N_('Superseded')]];
// 2.38.0 (#1021, F1): invoices, credit notes and reminders share the tab; the server derives partial / overdue / cancelled
const OFD_KINDS = [['offer', N_('Quotations')], ['invoice', N_('Invoices')], ['credit', N_('Credit notes')], ['reminder', N_('Payment reminders|dunning')], ['delivery', N_('Delivery notes')], ['archive', N_('Archive|documents')]];  // 2.39.1 (#1182): + the legacy archive (office_import.js)
// 2.380.0 B (#3409): two areas of the menu instead of one tab "Quotes & invoices": Quotations (office/offers: quotations and
// the archived ones) and Invoices (office/invoices: invoices, credit notes, reminders, delivery notes and their archive). A
// document opens in its own area (office/<area>/<id>); an old link #office/offers/<id> of an invoice moves on (ofdLoadDoc)
const OFD_SECS = {offers: ['offer', 'archive'], invoices: ['invoice', 'credit', 'reminder', 'delivery', 'archive']};
const ofd_sec = () => S.route?.tab === 'invoices' ? 'invoices' : 'offers';
const ofd_secOf = kind => kind === 'offer' ? 'offers' : 'invoices';
const ofd_lsOn = () => typeof ofcFeat !== 'function' || ofcFeat('docs.delivery');  // 2.434.0 B (#3608): delivery notes switched off = no tab, no buttons (existing ones stay readable by link)
const ofd_kinds = () => OFD_KINDS.filter(x => OFD_SECS[ofd_sec()].includes(x[0]) && (x[0] !== 'delivery' || ofd_lsOn()));
const ofd_href = (id, kind) => `office/${kind ? ofd_secOf(kind) : ofd_sec()}/${id}`;
const ofd_tabOn = () => typeof ofcTab === 'function' && Object.hasOwn(OFD_SECS, ofcTab());
// the kind tab shown when the area changes: each area keeps its own (a kind set before a go() of its area wins)
function ofd_secSync() {
  const sec = ofd_sec(); if (OFD.sec === sec) return;
  if (OFD.sec && OFD_SECS[OFD.sec].includes(OFD.kind)) OFD.kindOf[OFD.sec] = OFD.kind;
  OFD.sec = sec;
  if (S.route.id) return;  // the document decides (ofdLoadDoc)
  const ks = OFD_SECS[sec].filter(x => x !== 'delivery' || ofd_lsOn()), k = ks.includes(OFD.kind) && OFD.kind !== 'archive' ? OFD.kind : ks.includes(OFD.kindOf[sec]) ? OFD.kindOf[sec] : ks[0];
  if (k !== OFD.kind) { OFD.kind = k; OFD.status = ''; OFD.list = null; }
}
// an old link #office/offers/<id> of an invoice (or a quotation under office/invoices): the address of the document's area
function ofd_docArea() {
  const d = OFD.doc, id = S.route?.id;
  if (!d?.kind || !id || d.id !== id || S.route.mod !== 'office' || !ofd_tabOn() || ofd_secOf(d.kind) === ofd_sec()) return false;
  history.replaceState(history.state, '', '#' + ofd_href(id, d.kind)); route();
  return true;
}
// an old address of an invoice kind (#office/offers/invoice, a bookmark of the time with one tab) -> its area
function ofd_oldLink() {
  const p = location.hash.slice(1).split('/');
  if (p[0] !== 'office' || p[1] !== 'offers' || p[2] === 'archive' || !OFD_SECS.invoices.includes(p[2])) return false;
  history.replaceState(history.state, '', `#office/invoices/${p[2]}`); route();
  return true;
}
const OFD_STATE = {done: N_('Settled'), draft: N_('Draft'), issued: N_('Finalised'), sent: N_('Sent|document'), paid: N_('Paid'), partial: N_('Partly paid'), overdue: N_('Overdue'), open: N_('Open items'), cancelled: N_('Cancelled'), accepted: N_('Accepted|document'), declined: N_('Rejected')};
const OFD_INV_STATUS = {invoice: ['draft', 'issued', 'sent', 'paid', 'cancelled'], credit: ['draft', 'issued', 'sent', 'paid'], reminder: ['draft', 'issued', 'sent'], delivery: ['draft', 'issued', 'sent']};  // 2.120.0 D (#2089): + delivery
const OFD_PAY = [['transfer', N_('Bank transfer')], ['cash', N_('Cash')], ['card', N_('Card')], ['other', N_('Other|payment')]];
const OFD_PAY_ONLINE = N_('Online payment');  // 2.469.0 (#3459): only the provider's webhook books it
const OFD_VATN = [['', N_('select…')], ['reverse', N_('Reverse charge (recipient pays the VAT)')], ['abroad', N_('Not taxable domestically')], ['small', N_('Small business: no VAT')],
  ['eu_goods', N_('Goods to a business in the EU (tax-exempt)')], ['export', N_('Export of goods outside the EU (tax-exempt)')]];  // 2.355.0 C (#2844)
const ofdIsInv = d => !!d && d.kind !== 'offer';
const ofdKindName = (k, one) => tr(one ? {offer: N_('Quotation'), invoice: N_('Invoice'), credit: N_('Credit note'), reminder: N_('Payment reminder|dunning'), delivery: N_('Delivery note')}[k] || k : OFD_KINDS.find(x => x[0] === k)?.[1] || k);
const OFD_RAW = [['optional', N_('optional (shown, not counted)')], ['included', N_('included (counted)')], ['none', N_('no raw data line')]];
// 2.185.0 C (#2520): the de / en source of a document's free texts (names, text blocks, pack words): nl / fr / es / it take
// the English one; numbers follow the document's own language (ofdNumEn: only English writes the point)
const ofdLang = d => ['', 'de', undefined, null].includes((d || OFD.doc)?.lang) ? 'de' : 'en';
const ofdNumEn = d => (d || OFD.doc)?.lang === 'en';
// money and quantities in the DOCUMENT's language and currency (not the person's locale): 1.234,56 € / €1,234.50 / $1,234.50
// 2.368.0 C (#2983): through curMoney in the document's language (like calc.fmt_money on the PDF: "1 234,50 €" in French)
const OFD_LOCS = ['de', 'en', 'fr', 'es', 'it', 'nl'];
function ofdMoney(n, d) {
  d = d || OFD.doc || {};
  return curMoney(+n || 0, d.currency || ofcHome(), OFD_LOCS.includes(d.lang) ? d.lang : 'de');  // 2.189.0 (#2475): €, $, £, else the code
}
// 2.189.0 (#2475): every currency of the pack (homecur.HC_CODES; the document's own one stays choosable) and the rate hint
const ofdCurOpts = d => [...new Set([...(OFC.info?.pack?.currencies || ['EUR', 'USD']), d.currency].filter(Boolean))].map(c => [c, c]);
const ofdFxHint = d => ofcHome() === 'EUR' && d.currency === 'USD' ? tr('1 € in USD; rates stay in EUR and are converted')
  : tr('1 {0} in {1}; prices stay in {0} and are converted', ofcHome(), d.currency);
const ofdQty = (n, d) => (+n || 0).toLocaleString(OFD_LOCS.includes((d || OFD.doc)?.lang) ? (d || OFD.doc).lang : 'de', {useGrouping: false, maximumFractionDigits: 4});  // 2.450.0 (#3770): the document's language
const ofdNumIn = v => numField(v, 4);
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
// 2.460.0 (#3767): the document's own language (ofdLang: the pack's de / en)
const ofdTl = d => { const l = String((d || OFD.doc)?.lang || 'de'); return l.startsWith('en') ? 'en' : l; };
const ofdSvcName = (s, d) => ofcOwn(s, 'name', ofdTl(d));

// ---- loading
// 2.358.0 B (#3302): a switch of kind / filter while a list loads is no longer dropped: the answer of the old one is thrown
// away and the list loaded again (before: the offers stayed under "Invoices" after a quick click on the kind)
const ofdListUrl = () => `/api/office/docs?kind=${OFD.kind}${OFD.status ? '&status=' + OFD.status : ''}${OFD.trial ? '&trial=' + OFD.trial : ''}${ofd_grpQs()}${ofd_sortQs()}${OFD.listQ ? '&q=' + encodeURIComponent(OFD.listQ) : ''}`;
// 2.458.0 (#3839): a list the server cuts at 500 is sorted there too (docs.py odoc_list), the newest first is its own order
const ofd_sortQs = () => { const s = lst_sort(ofd_listKey(OFD.kind)); return s.k === 'date' && s.d === 'desc' ? '' : `&sort=${s.k}&dir=${s.d}`; };
// 2.369.0 A (#3200): the list comes in pages; another sorting than newest first needs the rows, so it takes the largest page
const ofd_page = () => { const s = lst_sort(ofd_listKey(OFD.kind)); return s.k === 'date' && s.d === 'desc' ? 100 : 500; };
// a reload keeps what "Load more" has shown (to one largest page)
const ofd_reloadN = () => Math.max(ofd_page(), Math.min(OFD.list?.length || 0, 500));
// 2.369.0 A (#3200): the search looks at the loaded rows at once; rows still on the server: it asks the server too
function ofd_qLoad() {
  clearTimeout(OFD.qTimer);
  const q = OFD.q.trim();
  if (OFD.kind === 'archive' || q === OFD.listQ || !(OFD.next || OFD.listQ)) return;
  OFD.qTimer = setTimeout(() => { OFD.listQ = OFD.q.trim(); ofdLoadList(true); }, 300);
}
async function ofdMore() {
  if (!OFD.next || OFD.more || OFD.loading) return;
  const u = ofdListUrl(), list = OFD.list;
  OFD.more = true; ofdDraw();
  try {
    const j = await api('GET', `${u}&limit=${ofd_page()}&before=${encodeURIComponent(OFD.next)}`);
    if (u === ofdListUrl() && list === OFD.list) {
      const seen = new Set(list.map(r => r.id));
      list.push(...(j.docs || []).filter(r => !seen.has(r.id))); OFD.next = j.next_cursor || null;
    }
  } catch (x) { ofcErr(x); }
  OFD.more = false; ofdDraw();
}
async function ofdLoadList(force) {
  if (OFD.loading) { if (force) OFD.loadAgain = true; return; }
  if (OFD.list && !force) return;
  if (OFD.kind === 'archive') { if (typeof OIM !== 'undefined') OIM.list = null; OFD.list = []; ofdDraw(); return; }  // 2.39.1 (#1182): office_import.js loads it
  OFD.loading = true; OFD.loadAgain = false;
  const u = ofdListUrl();
  try { const j = await api('GET', `${u}&limit=${ofd_reloadN()}`); if (u === ofdListUrl()) { OFD.list = j.docs || []; OFD.next = j.next_cursor || null; OFD.role = j.role; OFD.err = ''; OFD.dunning = j.dunning || null; tri_meta(j); } }  // 2.147.1 B (#2054): dunning; 2.144.10 C (#2576): + trial filter / meta
  catch (x) { if (u === ofdListUrl()) { OFD.list = []; OFD.next = null; OFD.err = ofcErrHere(x); } }
  OFD.loading = false;
  if (OFD.loadAgain || u !== ofdListUrl()) { ofdLoadList(true); return; }
  const el = $('.office .ofcbody'); if (el) keepFocus(el, ofdDraw); else ofdDraw();  // 2.369.0 A (#3200): the search box keeps the cursor
  ofd_qLoad();
}
async function ofdLoadDoc(id, force) {
  if (OFD.docLoading) return;
  if (OFD.doc && OFD.doc.id === id && !force) return;
  OFD.docLoading = true; OFD.docId = id;
  try { OFD.doc = await api('GET', `/api/office/docs/${id}`); OFD.viaFolder.delete(id); OFD.err = ''; OFD.conflict = null; if (OFD.doc?.kind && OFD.doc.kind !== OFD.kind) { OFD.kind = OFD.doc.kind; OFD.list = null; } }
  catch (x) {  // 2.199.0 B (#2742): no office right for it, but a shared folder holds it -> read through the folder (its PDF too)
    OFD.doc = null; OFD.err = ofcErrHere(x);
    // 2.351.0 A (#2823): a draft with edit through the folder is edited (saved over the folder way, ofd_viaUrl)
    try { const j = await rawFetch('GET', `/api/fsref/office_doc/${id}`); OFD.doc = ofd_viaDoc(j, j.folder_role); OFD.viaFolder.add(id); OFD.err = ''; } catch { /* keep the office's answer */ }
  }
  OFD.docLoading = false;
  if (ofd_docArea()) return;  // 2.380.0 B (#3409)
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
  if (S.route.mod !== 'office' || !ofd_tabOn()) return;  // 2.380.0 B (#3409): quotations or invoices
  const el = $('.office .ofcbody .pboffers') || $('.office .ofcbody'); if (el) ofdOffersTab(el);  // 2.47.3 (#1360): below the hint of an empty personal office
  ofd_crumbSync();
}
// 2.1004.0 (#5572): a phone's office list has ONE navigation line: the kinds of Quotations / Invoices follow their point in the
// row of the office menu (areas.js ofm_menuHtml), the point itself is its first kind; the kind tabs of the body hide then
// (app.css #view:has(.ofpb .ofpk)). The address carries the kind (ofd_kindHash), so a kind tab is a plain link.
function ofd_navKind(sec, ks) {
  const p = location.hash.slice(1).split('/');
  if (p[0] === 'office' && p[1] === sec && ks.includes(p[2])) return p[2];
  if (OFD.sec === sec && ks.includes(OFD.kind)) return OFD.kind;
  return ks.includes(OFD.kindOf?.[sec]) ? OFD.kindOf[sec] : ks[0];
}
function ofd_navKindsHtml(cur, btn) {
  if (!Object.hasOwn(OFD_SECS, cur) || S.route.id || S.route.tab !== cur) return btn;
  const ks = ofd_kinds().map(x => x[0]); if (ks.length < 2) return btn;
  const k = ofd_navKind(cur, ks), sub = k !== ks[0];
  const pt = btn.replace(`data-go="office/${cur}"`, `data-go="office/${cur}/${ks[0]}"`).replace('class="ofpt2 ', `class="ofpt2 ${sub ? 'ofpsub ' : ''}`);
  return pt + ofd_kinds().slice(1).map(([v, n], i) => `<button type="button" class="ofpt2 ofpk${i ? '' : ' ofpk1'}${v === k ? ' on' : ''}" data-go="office/${esc(cur)}/${esc(v)}" data-ofk="${esc(v)}"${v === k ? ' aria-current="true"' : ''}>${esc(tr(n))}</button>`).join('');
}
// after a draw of the list: the row follows a kind changed in place (reminder drafts, the cockpit; the address without a step)
function ofd_navSync() {
  const row = $('#view .ofpb .ofpts'), pt = row && $(`[data-ofm="${ofd_sec()}"]`, row); if (!pt) return;
  if (!$('.ofpk', row)) {  // the row was drawn before this module had loaded (lazyload.js): the kinds join it now
    const h = ofd_navKindsHtml(ofd_sec(), pt.outerHTML); if (h !== pt.outerHTML) { pt.outerHTML = h; if (typeof ofr_fade === 'function') ofr_fade(); }
    return;
  }
  pt.classList.toggle('ofpsub', OFD.kind !== ofd_kinds()[0]?.[0]);
  for (const b of $$('.ofpk', row)) { const on = b.dataset.ofk === OFD.kind; b.classList.toggle('on', on); if (on) b.setAttribute('aria-current', 'true'); else b.removeAttribute('aria-current'); }
}
// a function, not typeof OFD in areas.js: the module comes later, and a typeof on a const of a later script can stay "undefined" in jsdom (p2380_b_buero_ui)
function ofd_openDoc() { return OFD.doc; }
// 2.936.0 (#5448): a phone on an open document: its head (back + number + status) is the page's only way back (areas.js
// leaves out the office menu row and the path); the big heading of a computer names the document (render.js, ofd_crumbSync)
function ofd_phoneDoc() { return !!S.route.id && isMobile() && ofd_tabOn(); }
function ofd_docTitle() { const d = OFD.doc; return d && d.id === S.route.id && ofd_tabOn() ? `${ofdKindName(d.kind, true)} ${d.number || tr('Draft')}` : ''; }
// 2.356.0 C (#3004): the path line is drawn with the page (before the document has loaded) -> it follows the open document here
function ofd_crumbSync() {
  if (typeof ofm_detail !== 'function') return;
  const html = ofm_detail('office'), old = $('#view .ofmcrumb');
  const dt = isMobile() ? '' : ofd_docTitle(), h1 = dt && $('#top h1 .ht');  // 2.936.0 (#5448): the heading follows the document once it has loaded
  if (h1 && h1.textContent !== dt) { h1.textContent = dt; h1.parentElement.title = dt; }
  if (old) { if (!html) old.remove(); else if (old.outerHTML !== html) old.outerHTML = html; return; }
  if (!html) return;
  const h = $('#view .ofbody > .ofpt'), nav = $('#view .ofpb'), body = $('#view .ofbody');
  if (h) h.outerHTML = html; else if (nav) nav.insertAdjacentHTML('afterend', html); else if (body) body.insertAdjacentHTML('afterbegin', html);
}
// the entry from office.js: fills the tab's body (list or editor)
function ofdOffersTab(el) {
  if (ofd_oldLink() || ofd_docArea()) return;  // 2.380.0 B (#3409)
  ofd_secSync();
  const id = S.route.id;
  if (id) {
    if ((!OFD.doc || OFD.doc.id !== id) && !OFD.docLoading) setTimeout(() => ofdLoadDoc(id), 0);
    if (!OFC.data.services && !OFC.loading.services) setTimeout(() => ofcLoad('services'), 0);
    if (!OFC.data.texts && !OFC.loading.texts) setTimeout(() => ofcLoad('texts'), 0);
    if (!OFC.data.contracts && !OFC.loading.contracts) setTimeout(() => ofcLoad('contracts'), 0);
    if (ofd_pairOn() && !OFD.list && !OFD.loading && OFD.doc?.id === id) setTimeout(ofdLoadList, 0);  // 2.557.0 A (#4553): the list beside the document (of the document's kind)
  } else { ofd_kindHash(); if (!OFD.list && !OFD.loading) setTimeout(ofdLoadList, 0); }
  keepFocus(el, () => fl_set(el, id ? ofd_pairHtml() : ofdListHtml()));  // 2.46.2 (#1718): morphed
  if (typeof ofr_fade === 'function') ofr_fade(el);  // 2.936.0 (#5448): the kind tabs of a narrow screen fade at a cut edge
  if (!id) ofd_navSync();  // 2.1004.0 (#5572)
  const sl = id && $('.lsdl', el); if (sl && OFD.lsdTop) sl.scrollTop = OFD.lsdTop;  // 2.557.0 A (#4553): the list keeps its place when the next document opens
  if (id) el.querySelectorAll('textarea[data-grow-min]').forEach(t => ofcGrow(t, +t.dataset.grow || 3));  // 2.431.0 (#3594 review): a long subject wrapped by the field's width fits at once
  // 2.308.0 (#3251): the listeners sit on the tab body, not on a box inside it (the body and the box in it were both wired depending on timing: one click opened two dialogs)
  const host = el.closest('.ofcbody') || el;
  if (!host._ofd) { host._ofd = true; host.addEventListener('contextmenu', ofdCtx); if (!OFD.lp && typeof ms_longPress === 'function') OFD.lp = ms_longPress('#view .ofdrow', () => false, r => ofdRowMenu(r.dataset.id, r)); host.addEventListener('click', ofdClick); host.addEventListener('change', ofdChange); host.addEventListener('input', ofdInput); host.addEventListener('keydown', ofdKey); }
}

// 2.557.0 A (#4553): a content area of 100rem and more (#view.lsdw, render.js lsd_sync): the list of the document's kind stays
// on the left (about 40 %), the document on the right; only the rows (no search / filter bar: their fields would clash with
// the editor's), the open one marked. Below it the editor stands in place of the list as before.
const ofd_pairOn = () => typeof lsd_wide === 'function' && lsd_wide() && OFD.kind !== 'archive';
function ofd_pairHtml() {
  const ed = ofdEditorHtml(); if (!ofd_pairOn()) return ed;
  const l = OFD.list ? ofdListHtml() : '', i = l.indexOf('<ul class="ofclist ofdlist"'), id = S.route.id;
  const rows = i < 0 ? `<p class="muted lempty">${OFD.list ? '' : tr('Loading…')}</p>` : l.slice(i).replace(`data-ofd="open" data-id="${id}">`, `data-ofd="open" data-id="${id}" aria-current="true">`);
  return `<div class="lsd2"><nav class="lsdl" aria-label="${esc(ofdKindName(OFD.kind))}">${rows}</nav><div class="lsdr">${ed}</div></div>`;
}

// 2.356.0 C (#3004): the kind tab is part of the address (#office/offers/invoice): a new address (link, Back) chooses the tab,
// a tab changed in place (reminder drafts, the cockpit) rewrites the address without a history step
function ofd_kindHash() {
  const p = location.hash.slice(1).split('/');
  if (p[0] !== 'office' || !Object.hasOwn(OFD_SECS, p[1]) || +p[2]) return;  // 2.380.0 B (#3409): + office/invoices/<kind>
  const ks = OFD_SECS[p[1]], hk = ks.includes(p[2]) ? p[2] : '';
  if (hk && hk !== OFD.kind && location.hash !== OFD.hashSeen) { OFD.kind = hk; OFD.status = ''; OFD.list = null; }
  // the bare #office/<area> stays as it is for the area's first tab (the office's remembered page #2622, the menu's own address)
  if (hk !== OFD.kind && (hk || OFD.kind !== ks[0])) history.replaceState(history.state, '', `#office/${p[1]}/${OFD.kind}`);
  OFD.hashSeen = location.hash;
}
// ---- 2.451.0 (#3834): the sort of an office list: same choice on computer and phone, remembered per list on the device.
// sorts: [[key, label]]; a list with a manual order (the pipeline) has the key '' first = no sort
const LST_SORTS = [['date', N_('Date')], ['client', N_('Client')], ['amount', N_('Amount')], ['name', N_('Name')]];
const LST_MANUAL = [['', N_('Default')], ...LST_SORTS];
const lst_dir0 = k => (k === 'name' || k === 'client' ? 'asc' : 'desc');
function lst_sort(list, sorts = LST_SORTS) {
  const s = LS.get('lst.sort.' + list, null) || {}, k = sorts.some(x => x[0] === s.k) ? s.k : sorts[0][0];
  return {k, d: s.d === 'asc' || s.d === 'desc' ? s.d : lst_dir0(k)};
}
function lst_sortMenu(anchor, list, sorts, draw) {
  const s = lst_sort(list, sorts), set = (k, d) => { LS.set('lst.sort.' + list, {k, d}); draw(); };
  menu(anchor, [...sorts.map(([k, n]) => ({label: tr(n), on: s.k === k, title: k && s.k === k ? tr('Click again to reverse the direction') : '', fn: () => set(k, s.k === k ? (s.d === 'asc' ? 'desc' : 'asc') : lst_dir0(k))})),
    ...(s.k ? ['-', {label: tr('ascending|sort'), on: s.d === 'asc', fn: () => set(s.k, 'asc')}, {label: tr('descending|sort'), on: s.d === 'desc', fn: () => set(s.k, 'desc')}] : [])]);
}
function lst_sortBtn(list, sorts = LST_SORTS) {
  const s = lst_sort(list, sorts), name = tr(sorts.find(x => x[0] === s.k)[1]), lbl = tr('Sorting') + ': ' + name + (s.k ? ', ' + (s.d === 'asc' ? tr('ascending|sort') : tr('descending|sort')) : '');
  return `<button type="button" class="btn sm lst-sortb" data-lstsort="${esc(list)}" aria-haspopup="menu" title="${esc(lbl)}" aria-label="${esc(lbl)}">${ic('sort', 's')} <span>${esc(name)}</span>${s.k ? (s.d === 'asc' ? ' ↑' : ' ↓') : ''}</button>`;
}
// get(row) -> {date, client, amount, name}; rows without the value stay last in both directions
function lst_sorted(rows, list, get, sorts = LST_SORTS) {
  const {k, d} = lst_sort(list, sorts), f = d === 'asc' ? 1 : -1; if (!k) return rows;
  const val = r => { const v = get(r)[k]; return v == null || v === '' ? null : k === 'amount' ? +v : v; };
  return rows.map(r => [r, val(r)]).sort(([, a], [, b]) => a === null || b === null ? (a === null) - (b === null) : f * (k === 'amount' ? a - b : k === 'date' ? (a < b ? -1 : a > b ? 1 : 0) : String(a).localeCompare(String(b), uiLang(), {numeric: true, sensitivity: 'base'}))).map(x => x[0]);
}
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-lstsort]'); if (!b) return;  // not data-lsort: that is the "…" of a list in the sidebar sort mode
  e.preventDefault(); e.stopPropagation();
  const l = b.dataset.lstsort; lst_sortMenu(b, l, l === 'pipeline' ? LST_MANUAL : LST_SORTS, () => { ofcDraw(); if (l.startsWith('docs.') && OFD.next) ofdLoadList(true); });  // 2.369.0 A (#3200): another sorting asks the server
});
const ofd_listKey = k => (k === 'archive' ? 'archive.' + oim_secKind() : 'docs.' + k);
// ---- the list
function ofdListHtml() {
  const rows = OFD.list, k = OFD.kind, inv = k === 'invoice' || k === 'credit';
  const q = OFD.q.trim().toLowerCase();
  if (k === 'archive') return `<div class="seg ofdkinds" role="tablist" aria-label="${esc(tr('Document kind'))}">${ofd_kinds().map(([v, n]) => `<button type="button" role="tab" data-ofd="kind" data-kind="${v}" aria-selected="${v === k}" class="${v === k ? 'on' : ''}">${tr(n)}</button>`).join('')}</div><div class="ofcbar ofdbar"><div class="ctsearch">${ic('search', 's')}<input id="ofd-q" type="search" value="${esc(OFD.q)}" placeholder="${esc(tr('Search'))}" aria-label="${esc(tr('Search documents'))}" autocomplete="off" enterkeyhint="search"></div>${lst_sortBtn(ofd_listKey(k))}</div>` + (typeof oimArchiveListHtml === 'function' ? oimArchiveListHtml(q) : '');
  const sts = k === 'offer' ? OFD_STATUS : (k === 'invoice' ? ['open', 'draft', 'issued', 'sent', 'partial', 'overdue', 'paid', 'cancelled'] : OFD_INV_STATUS[k]).map(v => [v, OFD_STATE[v]]);  // 2.356.0 D (#3007): + the open items
  const newBtn = k === 'offer' ? `<button class="btn pri" data-ofd="new">${ic('plus', 's')}<span>${tr('New quotation')}</span></button>`  // 2.417.0 C (#3445): one button again (the test mode decides)
    : k === 'invoice' ? `${typeof dx_btn === 'function' && ofcFeat('books.datev') ? dx_btn() : ''}<button class="btn" data-ofd="remind">${ic('clock', 's')}<span>${tr('Create payment reminder')}</span></button><button class="btn pri" data-ofd="new-inv" aria-haspopup="menu">${ic('plus', 's')}<span>${tr('New invoice')}</span></button>`
    : k === 'reminder' ? `<button class="btn pri" data-ofd="remind">${ic('plus', 's')}<span>${tr('Create payment reminder')}</span></button>`
    : k === 'delivery' && ofd_lsOn() ? `<button class="btn pri" data-ofd="new-ls">${ic('plus', 's')}<span>${tr('New delivery note')}</span></button>` : '';  // 2.120.0 D (#2089)
  const kinds = `<div class="seg ofdkinds" role="tablist" aria-label="${esc(tr('Document kind'))}">${ofd_kinds().map(([v, n]) => `<button type="button" role="tab" data-ofd="kind" data-kind="${v}" aria-selected="${v === k}" class="${v === k ? 'on' : ''}">${tr(n)}</button>`).join('')}</div>`;
  // 2.46.1 (#1637): an empty offer list shows its one big button below the text, not a second one up here
  const noTop = k === 'offer' && rows && !rows.length && !q && !OFD.status && !OFD.trial;
  const bar = kinds + `${rows?.length ? hintOnce('ofclp', tr('Hold a row to see what you can do with it.')) : ''}<div class="ofcbar ofdbar"><div class="ctsearch">${ic('search', 's')}<input id="ofd-q" type="search" value="${esc(OFD.q)}" placeholder="${esc(tr('Search'))}" aria-label="${esc(tr('Search documents'))}" autocomplete="off" enterkeyhint="search"></div>
    <select id="ofd-status" aria-label="${esc(tr('Status'))}"><option value="">${tr('All|status')}</option>${sts.map(([v, n]) => `<option value="${v}" ${OFD.status === v ? 'selected' : ''}>${tr(n)}</option>`).join('')}</select>${ofd_fltHtml()}${tri_filterHtml()}${lst_sortBtn(ofd_listKey(k))}<span class="spacer"></span>${ofcAdmin('offers') ? `<button type="button" class="btn sm" data-ofd="trash" title="${esc(tr('Trash'))}" aria-label="${esc(tr('Trash'))}">${ic('trash', 's')}</button>` : ''}${noTop ? '' : newBtn}</div>${tri_barHtml()}`;
  if (!rows) return bar + `<p class="muted lempty">${tr('Loading…')}</p>`;
  if (OFD.err && !rows.length) return bar + `<div class="empty">${esc(OFD.err)}</div>`;
  const hit = r => !q || [r.number, r.recipient_name, r.project_title, r.project_ref].some(v => (v || '').toLowerCase().includes(q));
  const more = OFD.next ? `<p class="rcl-more"><button type="button" class="btn ghost" data-ofd="listmore" ${OFD.more ? 'disabled' : ''}>${tr('Load more')}</button></p>` : '';  // 2.369.0 A (#3200)
  const list = lst_sorted(rows.filter(hit), ofd_listKey(k), r => ({date: r.date, client: r.recipient_name, amount: inv ? r.gross : k === 'delivery' ? null : r.net, name: r.project_title || r.number}));  // 2.451.0 (#3834)
  const emptyTxt = {offer: N_('No quotations yet.'),  // 2.298.0 A1 (#3186): the button sits right below
    invoice: N_('No invoices yet. Make one from a quotation, from time entries or start empty.'),
    credit: N_('No credit notes yet. A credit note is made from a finalised invoice.'), reminder: N_('No payment reminders yet. Select open invoices in the invoice list.'),
    delivery: N_('No delivery notes yet. From a quotation, an invoice or empty – without prices.')};  // 2.120.0 D (#2089)
  if (!list.length) return bar + `<div class="empty nempty eact">${ic('receipt')}<span>${q || OFD.status || OFD.trial || ofd_grpQs() ? tr('Nothing matches.') : tr(emptyTxt[k])}</span>${!q && !OFD.status && !OFD.trial && !ofd_grpQs() && k === 'offer' ? `<button class="btn pri" data-ofd="new">${ic('plus', 's')}<span>${tr('New quotation')}</span></button>` : ''}</div>` + more;
  // 2.40.0 (#1368 point 9): settled reminders (all their invoices paid or cancelled) below the open ones
  const grp = k === 'reminder' && list.some(r => r.settled) && list.some(r => !r.settled);
  if (k === 'reminder') list.sort((a, b) => (a.settled ? 1 : 0) - (b.settled ? 1 : 0));
  const feeTxt = r => +r.fee_open > 0 ? `<small class="ofdfee">${esc(k === 'reminder' ? tr('fee open: {0}', r.fee_open_text || r.fee_open) : tr('reminder fee open: {0}', r.fee_open_text || r.fee_open))}</small>` : '';
  return bar + (k === 'invoice' && typeof oa_ppBox === 'function' ? oa_ppBox() : '') + (k === 'invoice' && typeof rinListHtml === 'function' ? rinListHtml() : '') /* 2.91.0 A (#1923) */ + (typeof dun_listHint === 'function' ? dun_listHint(k) : '') /* 2.147.1 B (#2054) */ + `<ul class="ofclist ofdlist" role="list">${list.map((r, i) => `${grp && r.settled && !list[i - 1]?.settled ? `<li class="ofdgrp muted" role="presentation">${tr('Settled')}</li>` : ''}<li class="ofdli"${isTouch() ? ' data-ofdmv="1"' /* 2.633.0 (#4964): a finger by drag.js (office_tree.js) */ : ' draggable="true"' /* 2.351.0 A (#2823): onto a folder of the panel */}><button type="button" class="ofcrow ofdrow st-${r.state || r.status}" data-ofd="open" data-id="${r.id}">
    <span class="ofcn"><b>${r.locked ? `<span class="ofdlk" title="${esc(tr('Finalised'))}">${ic('lock', 's')}</span>` : ''}${esc(r.number || (r.locked ? tr('(no number)') : ofdKindName(r.kind || k, true)) /* 2.947.0 (#5454): a draft names its kind, not "(no number)" */)}${r.recipient_name ? ` · ${esc(r.recipient_name)}` : ''}${typeof dun_rowTag === 'function' ? dun_rowTag(r) : '' /* 2.147.1 B (#2054) */}${tri_tag(r) /* 2.144.10 C (#2576) */}</b><small class="muted">${ofd_stTag(r, 'ofdst') /* 2.543.0 (#4473): phones: the status in the meta line */}${esc([r.project_title, r.date ? fmtDateLoc(r.date) : '', inv && r.due_date && !['paid', 'cancelled'].includes(r.state) ? tr('due {0}', fmtDateLoc(r.due_date)) : ''].filter(Boolean).join(' · '))}</small>${k === 'invoice' && typeof rinRowTag === 'function' ? rinRowTag(r) : ''}${k === 'invoice' && r.inv_type ? `<small class="rin-tag abs-tag">${esc(absKindName(r))}</small>` : ''}</span>
    <span class="ofdsum"><b>${esc(k === 'delivery' ? '' : inv ? r.gross_text : r.net_text)}</b>${k === 'delivery' ? '' : `<small class="muted oil_amt">${inv && r.net !== r.gross ? `<span class="ofdlong">${esc(tr('gross, net {0}', r.net_text))}</span><span class="ofdshort">${esc(tr('gross'))}</span>` : esc(inv ? tr('gross') : tr('net'))}</small>` /* 2.356.0 C (#3003): which amount the row shows; 2.543.0 (#4473): phones only "gross" */}${inv && r.open && !['draft', 'paid', 'cancelled'].includes(r.state) && r.open !== r.gross ? `<small class="muted">${esc(tr('open: {0}', r.open_text || r.open))}</small>` : ''}${feeTxt(r)}${ofd_stTag(r, 'ofdsr')}</span></button><button data-rowmenu="ofdrow" type="button" class="iconbtn ofdrmore" data-ofd="rowmore" data-id="${r.id}" aria-haspopup="menu" aria-label="${esc(tr('More'))}" title="${esc(tr('More'))}">${ic('dots', 's')}</button></li>`).join('')}</ul>` + more;
}

// 2.543.0 (#4473): the status label of a list row: right under the amount (ofdsr, desktop) and in the meta line (ofdst, phones)
const ofd_stTag = (r, c) => `<small class="rotag ${c} st-${r.state || r.status}">${esc(r.status_text)}</small>`;

// ---- the editor
const ofdSec = (key, title, body, extra = '') => `<details class="ofdsec" ${OFD.open[key] ? 'open' : ''} data-sec="${key}"><summary><h3>${esc(title)}</h3>${extra}</summary><div class="ofdsecb">${body}</div></details>`;
// 2.298.0 A1 (#3186): the help is a .shint behind the (i) of the label (o.keep = stays visible: units, follow-ups); with an
// (i) text of its own the help joins it (one (i) per label)
const ofdF = (k, label, field, hint, o) => { const ii = typeof OFC_II === 'object' && OFC_II['ed_' + k] && hint && !o?.keep;
  return `<div class="row"><label for="ofd-${k}">${esc(label)}</label>${field}${ii ? '' : ofcHint(hint, o)}</div>${typeof ofcII === 'function' ? ofcII('ed_' + k, ii ? hint : '') : ''}`; };  // 2.47.3 (#1382): (i) per field
// 2.354.0 D (#2838): a credit note keeps currency, rate, client and VAT of its invoice (the server refuses a change)
const ofdBound = (d, h) => d.kind === 'credit' && d.cancels_id ? h.replace(/^<(select|input) /, `<$1 disabled title="${esc(tr('Taken from the invoice'))}" `) : h;
const ofdSel = (k, cur, opts, empty) => `<select id="ofd-${k}" data-f="${k}">${empty != null ? `<option value="">${esc(empty)}</option>` : ''}${opts.map(([v, n]) => `<option value="${esc(v)}" ${String(v) === String(cur ?? '') ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select>`;
// 2.113.1 (#2251, #2252): the calculation options of the industry packs switched on (share by amount, handling costs,
// markup): switch / fields / position marks only with the option or on a document that already computes with it
const PRD_SLOTS = ['handling', 'markup'];
function prd_opts() {
  const o = {share: null, handling: null, markup: null};
  for (const p of OFC.info?.industry || []) for (const k of Object.keys(o)) if (!o[k] && p?.calc?.[k]) o[k] = p.calc[k];
  return o;
}
const prd_lbl = (l, d) => l ? l[(d || OFD.doc)?.lang] || (ofdLang(d) === 'en' ? l.en : l.de) || l.de || l.en || '' : '';  // 2.449.0 (#3768): + the pack's other languages
const prd_prodShown = d => (d.producing_on != null && d.producing_on !== 0) || (d.producing_on == null && d.kind === 'offer') || (d.producing_mode === 'amount' && !!prd_opts().share)
  || (d.kind === 'offer' && !d.locked && !!prd_opts().share);  // 2.380.0 (#3420): also a quotation made before the pack was on
const prd_slotShown = (d, k) => d.kind === 'offer' && (d[k + '_pct'] != null || !!prd_opts()[k]);
const prd_slotName = (d, k) => prd_lbl(d[k + '_label'] || prd_opts()[k]?.label, d) || (k === 'handling' ? tr('Handling costs') : tr('Markup'));
const ofdIn = (k, v, o = {}) => `<input id="ofd-${k}" data-f="${k}" value="${esc(v ?? '')}" maxlength="${o.max || 200}" ${o.num ? 'inputmode="decimal" class="numin"' : ''} ${o.ph ? `placeholder="${esc(o.ph)}"` : ''} ${o.ro ? 'readonly' : ''}>`;
// 2.431.0 B (#3594): o.grow = the field grows with its text from `rows` up to o.grow rows (ofcGrow)
const ofdTa = (k, v, rows = 3, o = {}) => `<textarea id="ofd-${k}" data-f="${k}" rows="${o.grow ? Math.min(o.grow, Math.max(rows, String(v ?? '').split('\n').length)) : rows}" maxlength="${o.max || 8000}" ${o.grow ? `data-grow="${o.grow}" data-grow-min="${rows}"` : ''} ${o.ph ? `placeholder="${esc(o.ph)}"` : ''}>${esc(v ?? '')}</textarea>`;
// 2.435.0 B (#3618): the send button's condition, shared by the editor bar and the list row menu
const ofdCanSend = d => !!d && !!d.locked && !d.via_folder && !ofr_noSp('offers', 'release');
function ofdEditorHtml() {
  const d = OFD.doc && OFD.doc.id === S.route.id ? OFD.doc : null;
  const back = `<button type="button" class="btn sm ofdback" data-ofd="back" aria-label="${esc(tr('Back to {0}', ofdKindName(OFD.kind)))}" title="${esc(tr('Back to {0}', ofdKindName(OFD.kind)))}">${ic('left', 's')}<span>${ofdKindName(OFD.kind)}</span></button>`;  // 2.936.0 (#5448): a phone shows the arrow only (office.css)
  if (!d) return `<div class="ofdhead">${back}</div>` + (OFD.err ? `<div class="empty">${ic('receipt')}<span>${esc(OFD.err)}</span></div>` : `<p class="muted lempty">${tr('Loading…')}</p>`);
  const adm = ofcAdmin(), t = d.totals || {};
  const txtOpt = kind => ofcTextOpts(kind, ofdTl(d));  // 2.40.0 (#1381): no silent German
  const contracts = ofcRows('contracts').filter(x => !x.archived || x.id === d.contract_id).map(x => [x.id, x.name]);
  const clients = typeof clientsOn === 'function' && clientsOn() ? (S.clients || []).filter(c => (!c.archived && (c.org_id || null) === pb_clOrg()) || c.id === d.client_id).map(c => [c.id, cdn_label(c)]) : [];
  const lk = !!d.locked, inv = ofdIsInv(d), kind = d.kind, ro = !d.can_edit;
  const vf = !!d.via_folder;  // 2.351.0 F (#2823, review M4): through a folder: no status, next steps, parts, links into the master data
  const numTxt = d.number || (d.number_at_finalize ? tr('Draft') : tr('(no number)'));
  const stOpts = kind === 'offer' ? OFD_STATUS : OFD_INV_STATUS[kind].map(v => [v, OFD_STATE[v]]);
  const stCan = v => (kind === 'offer' && (v !== 'draft' || d.status === 'draft') && (v !== 'superseded' || ['sent', 'accepted', 'superseded'].includes(d.status))) || v === d.status || (lk && d.status !== 'cancelled' && (v === 'sent' || (v === 'paid' && kind === 'invoice' && adm)) && (d.status !== 'paid' || adm));  // 2.39.1 (#1210 N3): paid only by admins
  const stSel = vf ? '' : `<select id="ofd-status" data-f="status" aria-label="${esc(tr('Status'))}" class="ofdstat st-${d.state || d.status}" ${inv && !lk ? 'disabled' : ''}>${stOpts.map(([v, n]) => `<option value="${v}" ${d.status === v ? 'selected' : ''} ${stCan(v) ? '' : 'disabled'}>${tr(n)}${v === d.status && d.state && d.state !== d.status ? ` (${tr(OFD_STATE[d.state])})` : ''}</option>`).join('')}</select>`;
  const acts = [];
  if (kind === 'offer') acts.push(kvaNextHtml(d, lk, ro));  // 2.138.0 E (#2235): the next step of the quotation; 2.144.7 (#2572): + "Create invoice"
  if (kind === 'invoice' && lk && d.status !== 'cancelled' && adm) acts.push(`<button type="button" class="btn sm" data-ofd="pay">${ic('plus', 's')}<span>${tr('Record payment')}</span></button>`);
  if ((kind === 'offer' || kind === 'invoice') && ofd_lsOn()) acts.push(`<button type="button" class="btn sm ofd2m" data-ofd="to-ls" title="${esc(tr('A delivery note or proof of service with the positions, without prices'))}">${ic('file', 's')}<span>${tr('Delivery note')}</span></button>`);  // 2.120.0 D (#2089)
  if (ofdCanSend(d)) acts.push(d.trial ? `<button type="button" class="btn sm" data-ofd="send" disabled title="${esc(tr('A trial document cannot be sent by e-mail; create a real document for your client'))}">${ic('send', 's')}<span>${tr('Send|mail')}</span></button>` : `<button type="button" class="btn sm" data-ofd="send">${ic('send', 's')}<span>${tr('Send|mail')}</span></button>`);  // 2.542.0 (#4594): a trial document: the button is off with the reason  // 2.113.2 (#2253): a finalised quotation is mailed too
  if (vf) acts.length = 0;
  const head = `<div class="ofdhead">${back}<span class="ofdnum"><b>${inv ? `<span class="ofdkn">${esc(absKindName(d) || ofdKindName(kind, true))} </span>` : '' /* 2.936.0 (#5448): a phone puts the kind small above the number (office.css) */}${lk ? ic('lock', 's') + ' ' : ''}${esc(numTxt)}</b>${tri_tag(d) /* 2.144.10 C (#2576) */}${typeof onumDocHtml === 'function' ? onumDocHtml(d) : ''}${d.number || lk || d.number_at_finalize || !adm ? '' : `<button type="button" class="btn sm" data-ofd="number">${tr('Assign number')}</button>`}</span>
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
    ${d.vat_mode === 'novat' && kind !== 'delivery' ? ofdF('vat_note', tr('VAT note'), ofdBound(d, ofdSel('vat_note', d.vat_note || '', OFD_VATN.map(([v, n]) => [v, tr(n)]))), tr('printed on the invoice; required when finalising'), {keep: 1}) : ''}
    ${d.vat_mode === 'novat' && d.vat_note === 'reverse' && d.client_vat_id_missing ? `<p class="cdnmiss" role="status">${ic('info', 's')} ${esc(tr('The client has no VAT ID yet - reverse charge needs it; add it at the client'))}</p>` : ''}
    ${kind === 'delivery' || !ofcFeat('docs.einvoice') ? '' : ofdF('einvoice_format', tr('E-invoice format'), ofdSel('einvoice_format', d.einvoice_format || 'zugferd', ofdEinvOpts()))}` : '';  // 2.147.0 (#2460, #2461): only while e-invoices are on, the pack's formats  // 2.120.0 D (#2089): no e-invoice
  const remFields = kind === 'reminder' ? `
    ${ofdF('reminder_level', tr('Reminder level'), ofdSel('reminder_level', d.reminder_level || 1, [[1, tr('1 - payment reminder')], [2, tr('2 - reminder')], [3, tr('3 - final reminder')]]))}
    ${ofdF('reminder_fee', tr('Reminder fee'), `<span class="lacts">${ofdIn('reminder_fee', ofdNumIn(d.reminder_fee), {num: true, max: 10})}<span class="muted">${ofcSym(d.currency)}</span></span>`)}
    ${ofdF('reminder_deadline_days', tr('Payment deadline'), `<span class="lacts">${ofdIn('reminder_deadline_days', d.reminder_deadline_days ?? '', {num: true, max: 3})}<span class="muted">${tr('days')}</span></span>`)}` : '';
  // 2.356.0 C (#3005): the client comes first; language, currency, VAT and framework contract wait folded below ("More details",
  // the summary names their values) -- quotations and invoices alike
  // 2.368.0 (#2979): a note when the document is written in another language than the app shows
  const langOther = d.lang && String(d.lang).slice(0, 2) !== String(I18N.code || 'en').slice(0, 2);
  const moreF = `${ofdF('lang', tr('Document language'), ofdSel('lang', d.lang, (S.languages || []).map(L => [L.code, L.name])), langOther ? tr('Differs from your app language: the client receives the document in this language.') : '', {keep: true})}
    ${ofdF('currency', tr('Currency'), ofdBound(d, ofdSel('currency', d.currency, ofdCurOpts(d))))}
    ${d.currency !== ofcHome() ? ofdF('fx_rate', tr('Exchange rate'), ofdBound(d, ofdIn('fx_rate', ofdNumIn(d.fx_rate), {num: true, max: 12})), ofdFxHint(d)) : ''}
    ${kind !== 'reminder' && kind !== 'delivery' ? ofdF('vat_mode', tr('VAT'), ofdBound(d, ofdSel('vat_mode', d.vat_mode, [['vat', tr('with VAT')], ['novat', tr('without VAT (reverse charge / abroad)')]]))) : ''}
    ${!vf && kind !== 'reminder' && kind !== 'delivery' ? ofdF('contract_id', tr('Framework contract'), ofdSel('contract_id', d.contract_id, contracts, tr('none|contract')), d.contract ? tr('presets raw data, rights and closing; special rates apply to new positions') : '') : ''}`;
  const moreSum = [(S.languages || []).find(L => L.code === d.lang)?.name || d.lang, d.currency, kind === 'reminder' || kind === 'delivery' ? '' : d.vat_mode === 'novat' ? tr('without VAT') : tr('with VAT'), d.contract?.name || ''].filter(Boolean).join(' · ');
  const headSec = ofdSec('head', tr('Head'), `
    <div class="ofdgrid">
    ${vf ? '' : clients.length ? ofdF('client_id', tr('Client'), ofdBound(d, ofdSel('client_id', d.client_id, clients, cdn_on() ? tr('No client') : tr('free recipient')))) : typeof clientsOn === 'function' && clientsOn() ? `<div class="row fx8a_nocl"><label>${esc(tr('Client'))}</label><span class="muted">${esc(tr('No clients in this area yet'))}</span>${ro ? '' : `<button type="button" class="btn sm" data-ofd="client-new">${ic('plus', 's')}<span>${tr('Add client')}</span></button>`}</div>` : ''}
    ${d.client_id && (d.client_contacts || []).length ? ofdF('contact_id', tr('Contact person'), ofdSel('contact_id', d.contact_id ?? d.client_contacts[0].id, [...d.client_contacts.map(k => [k.id, k.name + (k.role ? ` (${k.role})` : '') + (k.is_default ? ' · ' + tr('default') : '')]), [0, tr('no contact person')]]), tr('the attention line of the address follows the choice')) : ''}
    ${cdn_on() ? cdn_recHtml(d, ro) : `${ofdF('recipient_name', tr('Recipient'), ofdIn('recipient_name', d.recipient?.name, {ph: tr('Company or name')}))}
    ${ofdF('recipient_lines', tr('Address lines'), ofdTa('recipient_lines', (d.recipient?.lines || []).join('\n'), 3, {ph: tr('one line each: name, attention, street, place')}))}`}
    ${ofdF('project_title', tr('Project title'), ofdTa('project_title', d.project_title, 2, {max: 1000, grow: 10}))}
    ${kind === 'delivery' ? ofdF('delivery_title', tr('Document title'), ofdSel('delivery_title', d.delivery_title || '', [['', tr('Delivery note')], ['service', tr('Proof of service')]])) : ''}
    ${kind === 'offer' ? ofdF('project_ref', tr('Order number / reference'), ofdIn('project_ref', d.project_ref, {max: 80})) : ''}
    ${ofdF('date', tr('Date'), dateIn('ofd-date', d.date, {label: tr('Date'), clear: false, attrs: 'data-f="date"'}))}
    ${kind === 'offer' ? ofdF('valid_until', tr('Valid until'), dateIn('ofd-valid_until', d.valid_until, {label: tr('Valid until'), attrs: 'data-f="valid_until"'})) : ''}
    ${kind !== 'reminder' ? ofdF('service_from', tr('Service from'), dateIn('ofd-service_from', d.service_from || '', {label: tr('Service from'), attrs: 'data-f="service_from"'})) : ''}
    ${kind !== 'reminder' ? ofdF('service_to', tr('Service until'), dateIn('ofd-service_to', d.service_to || '', {label: tr('Service until'), attrs: 'data-f="service_to"', after: 'ofd-service_from'})) : ''}
    ${invFields}${remFields}
    </div><details class="oil_more" ${OFD.open.more ? 'open' : ''}><summary>${ic('chev', 's fcar')}<span>${tr('More details')}</span> <span class="muted${langOther ? ' ofd_langother' : ''}">${esc(moreSum)}</span></summary><div class="ofdgrid">${moreF}</div></details>${kind === 'credit' && d.cancels ? `<p class="muted ofchint">${esc(tr('Credit note for invoice {0}', d.cancels.number || '#' + d.cancels.id))} <a href="#office/offers/${d.cancels.id}">${tr('open')}</a></p>` : ''}`);
  const items = kind === 'reminder' ? ofdRefsHtml(d, t) : ofdItemsHtml(d, adm);
  const auto = inv ? '' : ofdAutoHtml(d, t);
  const rights = d.rights || {};
  const dim = (k, kind, label) => `<div class="row ofdrt"><label for="ofd-r-${k}">${esc(label)}</label><span class="lacts ofdrtf">${ofdSel('r-' + k, rights[k]?.id, txtOpt(kind), tr('free text'))}${ofdIn('r-' + k + '-t', rights[k]?.text, {max: 1000, ph: tr('Text in the document')})}</span></div>`;
  const rightsSec = ofdSec('rights', tr('Transfer of rights'), dim('time', 'rights_time', tr('Duration')) + dim('territory', 'rights_territory', tr('Territory')) + dim('media', 'rights_media', tr('Media'))
    + ofdF('r-exceptions', tr('Exceptions'), ofdIn('r-exceptions', rights.exceptions, {max: 2000, ph: tr('e.g. music, stock material')}))
    + `<div class="row ofdchk"><label class="chkl"><input type="checkbox" id="ofd-r-exclusive" data-f="r-exclusive" ${rights.exclusive ? 'checked' : ''}> ${tr('Exclusive')}</label></div>`  // 2.855.0 (#5456): tick and text in the field column
    + ofdF('r-note', tr('Note'), ofdTa('r-note', rights.note, 2, {max: 2000})));
  const textsSec = ofdSec('texts', tr('Introduction and closing'), `
    <div class="row"><label for="ofd-intro">${tr('Introduction')}</label><span class="lacts ofdtxt">${ofdSel('intro_pick', '', txtOpt('intro'), tr('from a text block…'))}</span></div>${ofdTa('intro', d.intro, 3)}
    <div class="row"><label for="ofd-closing">${tr('Closing')}</label><span class="lacts ofdtxt">${ofdSel('closing_pick', '', txtOpt('closing'), tr('from a text block…'))}</span></div>${ofdTa('closing', d.closing, 3)}${typeof ast_ofdBtn === 'function' ? ast_ofdBtn(d) : '' /* 2.126.1 A (#2123) */}${kind === 'offer' ? ofdAcceptHtml(d) : ''}`);
  const fields = d.fields || [];
  const fieldsSec = ofdSec('fields', tr('Own fields'), `<div id="ofd-fields">${fields.map((f, i) => `<div class="row ofdfld"><input data-fld="${i}" data-k="name" value="${esc(f.name)}" maxlength="80" placeholder="${esc(tr('Name'))}" aria-label="${esc(tr('Name'))}"><input data-fld="${i}" data-k="value" value="${esc(f.value)}" maxlength="500" placeholder="${esc(tr('Value'))}" aria-label="${esc(tr('Value'))}"><button type="button" class="ib" data-ofd="fld-del" data-i="${i}" aria-label="${esc(tr('Remove'))}">${ic('x', 's')}</button></div>`).join('')}</div><button type="button" class="btn sm" data-ofd="fld-add">${ic('plus', 's')} ${tr('Add field')}</button>`,
    fields.length ? `<span class="c muted">${fields.length}</span>` : '');
  const totals = kind === 'delivery' ? '' : ofdTotalsHtml(d, t, adm);  // 2.120.0 D (#2089): no sums
  const banner = lk ? `<p class="ofdlocked" role="status">${ic('lock', 's')}<span>${esc(tr('Finalised on {0} by {1}. It can no longer be changed; duplicate it for a new version.', d.locked_at ? ofdWhen(d.locked_at) : '', d.locked_by_name || '?'))}</span>${kind === 'invoice' && d.status !== 'cancelled' ? `<button type="button" class="btn sm" data-ofd="credit">${ic('receipt', 's')}<span>${tr('Credit note / cancel')}</span></button>` : ''}${kind === 'credit' ? '' /* 2.354.0 D (#2838): a credit note comes from its invoice */ : `<button type="button" class="btn sm" data-ofd="dup">${ic('copy', 's')}<span>${tr('Duplicate')}</span></button>`}</p>`
    : ro ? `<p class="ofdlocked" role="status">${ic('lock', 's')}<span>${esc(tr('Sent documents cannot be changed; duplicate it for a new version.'))}</span><button type="button" class="btn sm" data-ofd="dup">${ic('copy', 's')}<span>${tr('Duplicate')}</span></button></p>` : '';
  const paySec = kind === 'invoice' && lk ? ofdSec('pay', tr('Payments'), ofdPaymentsHtml(d, adm)) : kind === 'credit' && lk ? ofdSec('pay', tr('Refunds'), ofdRefundsHtml(d, adm)) : '';  // 2.354.0 D (#2837)
  const logSec = adm ? ofdSec('log', tr('History'), ofdLogHtml(d)) : '';
  const ln = OFD.langNotes && OFD.langNotes.id === d.id && !lk ? OFD.langNotes.notes : [];  // 2.40.0 (#1381): what the language switch left as it was
  const langNote = ln.length ? `<div class="ofdlnote" role="status">${ic('info', 's')}<span>${tr('Language changed. Default texts were translated; these stayed as they were:')}<br>${ln.map(esc).join('<br>')}</span><button type="button" class="ib" data-ofd="ln-x" aria-label="${esc(tr('Close'))}">${ic('x', 's')}</button></div>` : '';
  const gaps = !ln.length && !lk ? d.lang_gaps || [] : [];  // 2.460.0 (#3767)
  const gapNote = gaps.length ? `<div class="ofdlnote" role="status">${ic('info', 's')}<span>${tr('Some of your own texts are missing in this language:')}<br>${gaps.map(esc).join('<br>')}</span></div>` : '';
  return `${head}${banner}${kind === 'invoice' && typeof rinBox === 'function' ? rinBox(d) : '' /* 2.91.0 A (#1923) */}${typeof oa_docBanner === 'function' ? oa_docBanner(d) : ''}${ofd_cfBar(d) /* 2.269.0 A (#3012) */}${langNote}${gapNote}${typeof sg_box === 'function' ? sg_box(d) : ''}${typeof pep_box === 'function' ? pep_box(d) : '' /* 2.154.0 B (#1960) */}${typeof pol_box === 'function' ? pol_box(d) : '' /* 2.469.0 (#3459) */}${vf ? '' : ofr_linkHtml(d) + oil_linkHtml(d) /* 2.437.0 B (#3621): ofr_linkHtml; 2.356.0 C (#3003); 2.351 vf: no links into the master data */}<div class="ofdeditor${kind === 'delivery' ? ' ofdls' : ''}" data-fg="ofd:${d.id}" data-fg-live><fieldset class="ofdfs" ${ro ? 'disabled' : ''}>${headSec}</fieldset>${!vf && typeof dpj_rowHtml === 'function' ? dpj_rowHtml(d) : '' /* 2.168.0 A (#2665): outside the locked fieldset; 2.356.0 C (#3005): below the head (client first) */}<fieldset class="ofdfs" ${ro ? 'disabled' : ''}>${`<section class="ofdsec open"><h3>${kind === 'reminder' ? tr('Reminded invoices') : tr('Positions')}</h3>${items}${auto}${totals}</section>${!vf && typeof tpPartsHtml === 'function' ? tpPartsHtml(d, adm) : ''}` /* 2.113.0 (#2248): parts open in place in "Parts" */}${kind === 'reminder' || kind === 'delivery' ? '' : kind === 'offer' || oil_hasRights(d) ? rightsSec : ro ? '' : `<button type="button" class="btn sm oil_rtadd" data-ofd="rights-add">${ic('plus', 's')}<span>${tr('Transfer of rights')}</span></button>` /* 2.356.0 C (#3005): an invoice shows it once it has rights */}${textsSec}${kind === 'reminder' ? '' : fieldsSec}</fieldset>${kind === 'offer' && typeof cf8_box === 'function' ? cf8_box(d) : '' /* 2.88.0 (#1915) */}${ofdFeeHtml(d, adm)}${paySec}${logSec}</div>`;  // 2.50.0 (#1200): sg_box = the approval link of a sent quotation
}
// 2.38.0 (#1021, F1): the invoices a reminder lists (read-only rows), the payments of an invoice
function ofdRefsHtml(d, t) {
  const rows = (t.lines || []).filter(l => l.kind === 'ref');
  if (!rows.length) return `<p class="muted">${tr('No invoices selected.')}</p>`;
  return `<ul class="ofdits ofdrefs" role="list">${rows.map(l => `<li class="ofdit ofdref"><span class="ofdpos muted">${ic('receipt', 's')}</span><span class="ofcn"><b><a href="#office/offers/${l.id}">${esc(l.number || '#' + l.id)}</a></b><small class="muted">${esc([l.date ? fmtDateLoc(l.date) : '', l.due_date ? tr('due {0}', fmtDateLoc(l.due_date)) : ''].filter(Boolean).join(' · '))}</small></span><b class="ofdlt">${esc(l.open_text || ofdMoney(l.open, d))}</b></li>`).join('')}</ul>`;
}
// 2.40.0 (#1368 point 8): the fee of a finalised reminder is an own open item (stays after the invoice is paid); admins waive it or mark it paid
function ofdFeeHtml(d, adm) {
  if (d.kind === 'invoice') return (d.fee_reminders || []).length ? `<p class="ofdfeeinfo muted">${esc(tr('Reminder fee still open: {0}', d.fee_reminders.map(f => `${f.number} (${ofdMoney(f.fee, d)})`).join(', ')))}</p>` : '';
  if (d.kind !== 'reminder' || !d.locked || !(+d.fee > 0)) return '';
  const st = d.fee_state || '', txt = {'': N_('open'), waived: N_('waived'), paid: N_('paid|fee'), cancelled: N_('cancelled with the invoice')}[st] || st;  // 2.355.0 D (#2846): + cancelled (final)
  const btn = (v, label) => `<button type="button" class="btn sm" data-ofd="fee" data-st="${v}">${esc(tr(label))}</button>`;
  const day = st === 'paid' && d.fee_paid_at ? ` · ${tr('Paid on')} ${fmtDateLoc(d.fee_paid_at)}` : '';  // 2.912.0 (#5419): the day it counts on
  return `<div class="ofdfeeinfo"><span>${esc(tr('Reminder fee {0}: {1}', ofdMoney(d.fee, d), tr(txt)) + day)}</span>${/*html-ok*/ adm && st !== 'cancelled' ? (st ? (st === 'paid' ? btn('paid', N_('Change date')) : '') + btn('', N_('Open again')) : btn('waived', N_('Waive fee')) + btn('paid', N_('Fee paid'))) : ''}</div>`;
}
function ofdPayList(d, adm) {  // 2.354.0 D (#2837): also the refunds of a credit note
  const ps = d.payments || [];
  return ps.length ? `<ul class="ofdits ofdpays" role="list">${ps.map(p => `<li class="ofdit ofdpay"><span class="ofdpos muted">${ic('check', 's')}</span><span class="ofcn"><b>${esc(ofdMoney(p.amount, d))}</b><small class="muted">${esc([p.reverses_id ? tr('Reversal') : p.reversed ? tr('Reversed') : '', p.date ? fmtDateLoc(p.date) : '', tr(p.method === 'online' ? OFD_PAY_ONLINE : OFD_PAY.find(x => x[0] === p.method)?.[1] || p.method), p.note, p.created_by_name].filter(Boolean).join(' · '))}</small></span>${adm && !p.reverses_id && !p.reversed ? `<button type="button" class="ib" data-ofd="pay-del" data-pid="${p.id}" aria-label="${esc(tr('Reverse payment'))}" title="${esc(tr('Reverse payment'))}">${ic('x', 's')}</button>` : ''}</li>`).join('')}</ul>` : '';
}
// 2.545.0 (#4387): a final invoice with a negative rest (progress invoices above the work done): its payments are refunds
const ofdNegRest = d => d.kind === 'invoice' && d.locked && +(d.totals?.gross || 0) < 0;
function ofdPaymentsHtml(d, adm) {
  if (ofdNegRest(d) && d.status !== 'cancelled') {
    const sum = `<p class="ofdpaysum"><span>${trh('Paid back: {0}', ofdMoney(Math.abs(+d.paid || 0), d))}</span><b>${trh('To pay back: {0}', ofdMoney(d.overpaid || 0, d))}</b></p>`;
    return (ofdPayList(d, adm) || `<p class="muted">${tr('No refund booked yet.')}</p>`) + sum
      + (adm && +d.overpaid > 0 ? `<button type="button" class="btn sm" data-ofd="pay">${ic('plus', 's')}<span>${tr('Record refund')}</span></button>` : '');
  }
  const list = ofdPayList(d, adm) || `<p class="muted">${tr('No payments yet.')}</p>`;
  const sum = `<p class="ofdpaysum"><span>${trh('Paid: {0}', ofdMoney(d.paid || 0, d))}</span>${+d.credits ? `<span>${trh('Credited: {0}', ofdMoney(d.credits, d))}</span>` : ''}<b>${trh('Open: {0}', ofdMoney(d.open || 0, d))}</b>${+d.overpaid > 0 && !(d.credits_of || []).length ? `<b>${trh('To pay back: {0}', ofdMoney(d.overpaid, d))}</b>` /* 2.355.0 A (#2847); 2.354.0 D (#2837): with credit notes the refund line below says it, less the refunds booked */ : ''}</p>`;
  const cr = (d.credits_of || []).length ? `<p class="muted ofchint">${tr('Credit notes')}: ${d.credits_of.map(c => `<a href="#office/invoices/${c.id}">${esc(c.number || tr('Draft'))}</a>`).join(', ')}</p>`
    + (+d.refund_open > 0 ? `<p class="ofdfeeinfo ofdrefund" role="status">${esc(tr('Refund open: {0}. Record it on the credit note.', ofdMoney(d.refund_open, d)))}</p>` : '') : '';  // 2.354.0 D (#2837)
  if (d.status === 'cancelled') return list + sum + cr;
  return list + sum + cr + (adm ? `<button type="button" class="btn sm" data-ofd="pay">${ic('plus', 's')}<span>${tr('Record payment')}</span></button>` : `<p class="muted ofchint">${tr('Only an admin of this organisation can record payments')}</p>`);  // 2.39.1 (#1210 N3)
}
// 2.456.0 (#3837): a position to another place, by the arrows and by dragging its symbol
async function ofdMoveItem(d, i, j) { d.items.splice(j, 0, d.items.splice(i, 1)[0]); await ofdPutItems(); }
rowd_attach(document, {kind: 'it', row: '.ofdit', move: (from, to, row, list) => {
  if (typeof tpf_ctx === 'function') tpf_ctx(list);  // the open part the list belongs to
  return ofdMoveItem(typeof tpCur === 'function' ? tpCur() : OFD.doc, from, to);
}});
function ofdItemsHtml(d, adm) {
  const its = d.items || [], inv = ofdIsInv(d);
  const taxes = OFC_TAXES.map(([v, n]) => [v, ofcTax(v)]), gp = rowd_attr('it');  // 2.456.0 (#3837): the position symbol is the grip
  const subs = {}, hd = {n: -1};  // 2.1041.0 (#5816): the subtotal lines of the calculation by their section (heading number)
  for (const l of d.totals?.lines || []) if (l.kind === 'subtotal') subs[l.sec] = l;
  const subRow = n => subs[n] ? `<li class="ofdit ofdsub"><span class="ofdpos muted">${ic('calc', 's')}</span><span class="ofcn">${esc(subs[n].label || '')}</span><b class="ofdlt">${esc(subs[n].total_text || ofdMoney(subs[n].total, d))}</b></li>` : '';
  const rows = its.map((it, i) => {
    const pre = it.kind === 'heading' && bfaFilled(it) ? subRow(hd.n++) : '';
    return pre + ofd_itRow(d, adm, it, i, its, inv, taxes, gp);
  }).join('') + subRow(hd.n);
  return ofd_itsWrap(d, rows, inv);
}
// 2.1041.0 (#5814): one position of the editor (was inside ofdItemsHtml)
function ofd_itRow(d, adm, it, i, its, inv, taxes, gp) {
    const mv = `<span class="ofdmv">${rowd_arrows(`<button type="button" class="ib" data-ofd="it-up" data-i="${i}" ${i === 0 ? 'disabled' : ''} aria-label="${esc(tr('Move up'))}">${ic('up', 's')}</button><button type="button" class="ib" data-ofd="it-down" data-i="${i}" ${i === its.length - 1 ? 'disabled' : ''} aria-label="${esc(tr('Move down'))}">${ic('down', 's')}</button>`)}<button type="button" class="ib" data-ofd="it-del" data-i="${i}" aria-label="${esc(tr('Remove'))}">${ic('x', 's')}</button></span>`;
    if (it.kind === 'heading') return `<li class="ofdit ofdhd"><span class="ofdpos muted rowgrip" ${gp}>${ic('list', 's')}</span><input data-i="${i}" data-k="title" value="${esc(it.title)}" maxlength="500" placeholder="${esc(tr('Heading (category)'))}" aria-label="${esc(tr('Heading'))}">${mv}</li>`;
    if (it.kind === 'text') return `<li class="ofdit ofdtx"><span class="ofdpos muted rowgrip" ${gp}>${ic('note', 's')}</span><textarea data-i="${i}" data-k="detail" rows="2" maxlength="4000" placeholder="${esc(tr('Text block'))}" aria-label="${esc(tr('Text block'))}">${esc(it.detail)}</textarea>${mv}</li>`;
    const line = (d.totals?.lines || []).find(l => (l.kind === 'item' || l.kind === 'discount') && l.id === it.id);
    if (it.kind === 'part' && typeof tpItemRow === 'function') return tpItemRow(it, i, d, line, mv);  // 2.47.0 (#1215): a part on the title page
    if (it.kind === 'discount') return `<li class="ofdit ofddisc"><span class="ofdpos rowgrip" ${gp}>${line?.pos || ''}</span>
      <div class="ofditb"><input class="ofdtt" data-i="${i}" data-k="title" value="${esc(it.title)}" maxlength="500" placeholder="${esc(tr('Discount'))}" aria-label="${esc(tr('Discount'))}">
      <span class="ofdnums"><span class="muted">−</span><input data-i="${i}" data-k="rate" inputmode="decimal" class="numin ofdrate" value="${esc(ofdNumIn(it.rate))}" aria-label="${esc(tr('Amount'))}"><span class="muted">${esc(ofcSym(ofcHome()))}</span>
      <select data-i="${i}" data-k="tax" aria-label="${esc(tr('VAT'))}">${taxes.map(([v, n]) => `<option value="${v}" ${it.tax === v ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select>
      <b class="ofdlt">${line ? esc(line.total_text || ofdMoney(line.total, d)) : ''}</b></span></div>${mv}</li>`;
    const opt = d.kind === 'offer' && it.opt ? it.opt : '';  // 2.1041.0 (#5814): marked, its amount in brackets (not in the sum)
    return `<li class="ofdit${it.agent_flag ? ' oa_flag' : ''}${it.producing && !inv ? ' ofdprod' : ''}${opt ? ' ofdopt' : ''}"><span class="ofdpos rowgrip" ${gp}>${line?.pos || ''}</span>${opt ? `<span class="rotag ofdopttag">${esc(opt === 'optional' ? tr('Optional') : tr('Alternative'))}</span>` : ''}
      <div class="ofditb"><input class="ofdtt" data-i="${i}" data-k="title" value="${esc(it.title)}" maxlength="500" placeholder="${esc(tr('Service'))}" aria-label="${esc(tr('Service'))}">
      <input class="ofddt" data-i="${i}" data-k="detail" value="${esc(it.detail)}" maxlength="4000" placeholder="${esc(tr('Detail (optional)'))}" aria-label="${esc(tr('Detail'))}">
      <span class="ofdnums">${it.unit === 'percent' ? ekUnitSel(it, i, d) + ekPctHtml(it, i, line, d) : `<input data-i="${i}" data-k="qty" inputmode="decimal" class="numin" value="${esc(ofdNumIn(it.qty))}" aria-label="${esc(tr('Quantity'))}">
      ${ekUnitSel(it, i, d)}
      <span class="muted">×</span><input data-i="${i}" data-k="rate" inputmode="decimal" class="numin ofdrate" value="${esc(ofdNumIn(it.rate))}" aria-label="${esc(ofcHome() === 'EUR' ? tr('Rate (EUR)') : tr('Rate ({0})', ofcHome()))}"><span class="muted">${ofcSym(ofcHome())}</span>`}
      <select data-i="${i}" data-k="tax" aria-label="${esc(tr('VAT'))}">${taxes.map(([v, n]) => `<option value="${v}" ${it.tax === v ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select>
      ${/*html-ok*/ ofdItDiscHtml(it, i, line, d)}<b class="ofdlt">${line ? esc(opt ? '(' + (line.total_text || ofdMoney(line.total, d)) + ')' : line.total_text || ofdMoney(line.total, d)) : ''}</b></span>
      ${/*html-ok*/ ofdItDiscNote(it, line, d)}<span class="ofdflags">${/*html-ok*/ ofdItDiscBtn(it, i, d)}${inv ? '' : `<label class="chkl"><input type="checkbox" data-i="${i}" data-k="raw_fee" ${it.raw_fee ? 'checked' : ''}> ${tr('raw data')}</label>${prd_prodShown(d) ? `<label class="chkl ofdprodf${it.producing ? ' on' : ''}"><input type="checkbox" data-i="${i}" data-k="producing" ${it.producing ? 'checked' : ''}> ${d.producing_mode === 'amount' ? esc(prd_lbl(d.share_label, d) || tr('producing')) : tr('producing')}</label>` : ''}${PRD_SLOTS.filter(k => prd_slotShown(d, k)).map(k => `<label class="chkl"><input type="checkbox" data-i="${i}" data-k="in_${k}" ${it['in_' + k] ? 'checked' : ''}> ${esc(prd_slotName(d, k))}</label>`).join('')}<label class="chkl"><input type="checkbox" data-i="${i}" data-k="discountable" ${it.discountable ? 'checked' : ''}> ${tr('discount')}</label>`}
      ${adm ? `<label class="chkl ofdcost">${tr('Purchase')} <input data-i="${i}" data-k="cost" inputmode="decimal" class="numin" value="${esc(ofdNumIn(it.cost))}" aria-label="${esc(tr('External cost per unit (internal)'))}"></label>${it.margin != null ? `<span class="ofdmargin${it.margin < 0 ? ' neg' : ''}">${esc(tr('Surplus {0}', ofdMoney(it.margin, d)))}</span>` : ''}` : ''}${/*html-ok*/ d.kind === 'offer' ? ofd_optSel(it, i) : ''}</span>${typeof oa_flagHtml === 'function' ? oa_flagHtml(it, i) : ''}</div>${mv}</li>`;  // 2.51.0 A (#1348): an agent's marks
}
// 2.1041.0 (#5814): normal / optional / alternative per position of a quotation (counted in no sum, printed with its amount)
const OFD_OPT = [['', N_('Normal position')], ['optional', N_('Optional position')], ['alternative', N_('Alternative position')]];
const ofd_optSel = (it, i) => `<select class="ofdoptsel" data-i="${esc(i)}" data-k="opt" aria-label="${esc(tr('Kind of position'))}">${OFD_OPT.map(([v, n]) => `<option value="${esc(v)}" ${(it.opt || '') === v ? 'selected' : ''}>${esc(tr(n))}</option>`).join('')}</select>`;
// 2.1041.0 (#5816, #5817): the document's print switches below the positions (not inside a part: they belong to the document)
function ofd_printSw(d) {
  if (d.tpPart || !['offer', 'invoice'].includes(d.kind)) return '';
  const sub = `<label class="chkl"><input type="checkbox" id="ofd-subtotals" data-f="subtotals" ${d.subtotals ? 'checked' : ''}> ${esc(tr('Subtotal under every section'))}</label>`;
  const flat = d.kind === 'offer' ? `<label class="chkl"><input type="checkbox" id="ofd-flat_print" data-f="flat_print" ${d.flat_print ? 'checked' : ''}> ${esc(tr('Print as a flat price'))}</label>` : '';
  return `<div class="ofdprintsw">${/*html-ok*/ sub}${/*html-ok*/ flat}${d.flat_print && d.kind === 'offer' ? `<p class="shint ofdflathint" role="note">${ic('info', 's')} ${esc(tr('The client sees only the total: no quantities or prices per position in the PDF and on the approval page.'))}</p>` : ''}</div>`;
}
function ofd_itsWrap(d, rows, inv) {
  return `<ul class="ofdits" role="list">${rows}</ul>${/*html-ok*/ ofd_printSw(d)}<div class="ofdadd"><button type="button" class="btn sm pri" data-ofd="it-svc">${ic('plus', 's')}<span>${tr('Add service')}</span></button><button type="button" class="btn sm" data-ofd="it-head">${ic('list', 's')}<span>${tr('Heading')}</span></button><button type="button" class="btn sm" data-ofd="it-text">${ic('note', 's')}<span>${tr('Text block')}</span></button>${inv && d.kind !== 'delivery' ? `<button type="button" class="btn sm" data-ofd="it-disc">${ic('calc', 's')}<span>${tr('Discount')}</span></button>` : ''}</div>`;
}
// 2.114.3 (#2266): which positions the producing switch counts; in a part whether its producing values are the document's or its own
function ofdProdHint(d) {
  const p = d.tpPart;
  if (!p) return `<div class="shint ofdprodhint">${esc(d.kind === 'offer' ? tr('Applies to the positions of this page with a producing tick. Parts without a separate setting use the switch and calculate their producing themselves.') : tr('Applies to the positions with a producing tick.'))}</div>`;  // 2.298.0 A1 (#3186): behind the (i) of the switch
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
    ${/*html-ok*/ ofdDiscHtml(d)}
    </div>`;
}
// 2.1042.0 (#5815): the discount of a quotation as a percent or a fixed net amount (switch next to the field); a part keeps the percent
function ofdDiscHtml(d) {
  if (d.tpPart || d.kind !== 'offer') return ofdF('discount_pct', tr('Discount'), ofdIn('discount_pct', ofdNumIn(d.discount_pct), {num: true, max: 8}), '%', {keep: 1});
  // the switch alone decides only while neither value is set (the server's value wins: undo, another device)
  const amt = +d.discount_amount > 0 ? true : +d.discount_pct > 0 ? false : OFD.discAmt?.id === d.id && OFD.discAmt.on, k = amt ? 'discount_amount' : 'discount_pct';
  const sel = `<select id="ofd-discount_mode" data-f="discount_mode" aria-label="${esc(tr('Discount as'))}"><option value="pct" ${/*html-ok*/ amt ? '' : 'selected'}>%</option><option value="amount" ${/*html-ok*/ amt ? 'selected' : ''}>${esc(ofcSym(ofcHome()))}</option></select>`;
  const cap = amt && d.totals?.discount_capped ? `<div class="shint keep warn" role="status">${esc(tr('The discount is higher than the sum of the discountable positions ({0})', curMoney(+d.totals.discount_base_home || 0, ofcHome(), OFD_LOCS.includes(d.lang) ? d.lang : 'de')))}</div>` : '';
  return `<div class="row"><label for="ofd-${/*html-ok*/ k}">${esc(tr('Discount'))}</label><span class="ofddiscin">${/*html-ok*/ ofdIn(k, ofdNumIn(amt ? d.discount_amount : d.discount_pct), {num: true, max: amt ? 14 : 8})}${/*html-ok*/ sel}</span>${/*html-ok*/ ofcHint(amt ? tr('fixed net amount on the marked positions') : tr('on the marked positions'), {keep: 1})}${/*html-ok*/ cap}</div>`;
}
// 2.1042.0 (#5815): a position's own discount in percent: the field shows when it has one or "Discount" was tapped in its row
const ofdItDiscOn = it => +it.discount_pct > 0 || it._pdisc;
function ofdItDiscHtml(it, i, line, d) {
  if (it.unit === 'percent' || !ofdItDiscOn(it)) return '';
  return `<span class="ofdipd"><span class="muted">−</span><input data-i="${/*html-ok*/ i}" data-k="discount_pct" inputmode="decimal" class="numin ofdipct" value="${esc(ofdNumIn(it.discount_pct || ''))}" aria-label="${esc(tr('Discount on this position (%)'))}"><span class="muted">%</span></span>`;
}
function ofdItDiscNote(it, line, d) {
  if (!line || !(+line.line_discount > 0)) return '';
  return `<small class="muted ofdipdn">${esc(tr('{0} less {1} % discount ({2})', ofdMoney(line.list_total, d), ofdQty(line.discount_pct, d), ofdMoney(-line.line_discount, d)))}</small>`;
}
const ofdItDiscBtn = (it, i, d) => it.unit === 'percent' || ofdItDiscOn(it) || d?.kind === 'delivery' ? '' :  /* no prices on a delivery note */ `<button type="button" class="btn sm ofdipdb" data-ofd="it-pdisc" data-i="${/*html-ok*/ i}">${esc(tr('Discount %'))}</button>`;
function ofdTotalsHtml(d, t, adm) {
  const L = t.labels || {};
  if (ofdIsInv(d)) {  // 2.38.0: invoice sums are exact strings; subtotal, tax per rate, total, paid / open
    // 2.355.0 D (#2846): + default interest per invoice and the flat fee (the same rows as the PDF)
    const rmx = d.kind === 'reminder' ? [...(t.lines || []).filter(l => l.kind === 'ref' && +l.interest > 0).map(l => [tr('Default interest {0}: {1} % p.a., {2} days|document', l.number || '', fmtNum(+t.interest_rate || 0, 2), l.interest_days || 0), l.interest_text || ofdMoney(l.interest, d), 'tax']),
      ...(+t.flat_fee > 0 ? [[tr(+t.flat_credited > 0 ? 'Flat fee for late payment (section 288 (5) BGB), less the reminder fee|document' : 'Flat fee for late payment (section 288 (5) BGB)|document'), t.flat_fee_text || ofdMoney(t.flat_fee, d), 'tax']] : [])] : [];  // 2.545.0 (#4387): credited against the fee
    const rows = d.kind === 'reminder' ? [[tr('Amount outstanding'), ofdMoney(t.net || 0, d), 'net'], ...rmx, ...(+t.fee ? [[tr('Reminder fee'), ofdMoney(t.fee, d), 'tax']] : []), [tr('Total'), ofdMoney(t.gross || 0, d), 'gross']]
      : [[tr('Subtotal'), ofdMoney(t.net || 0, d), 'net'], ...(t.tax_lines || []).map(x => [x.label, x.amount_text || ofdMoney(x.amount, d), 'tax']), [tr('Total'), ofdMoney(t.gross || 0, d), 'gross']];
    if (d.kind === 'invoice' && d.locked && (+d.paid || +d.credits)) rows.push([tr('Amount outstanding'), ofdMoney(d.open || 0, d), 'open']);
    if (d.kind === 'invoice' && d.locked && +d.overpaid > 0) rows.push([tr('To pay back'), ofdMoney(d.overpaid, d), 'open']);  // 2.355.0 A (#2847): overpaid
    return `<div class="ofdtotals" id="ofd-totals"><dl>${rows.map(([k, v, c]) => `<div class="ofdtr tr-${c}"><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('')}</dl>
      <p class="muted ofdnote">${esc(t.vat_note || '')}${t.fx_note ? ` · ${esc(t.fx_note)}` : ''}${t.tax_eur_text ? ` · ${esc((t.home || 'EUR') === 'EUR' ? tr('tax in EUR: {0}', t.tax_eur_text) : tr('tax in {0}: {1}', t.home, t.tax_eur_text))}` : ''}</p>
      ${adm && t.costs != null && d.kind !== 'reminder' ? `<p class="muted ofdint">${ic('eye', 's')} ${trh('Internal: external costs {0}, surplus {1}', ofdMoney(t.costs, d), ofdMoney(t.margin, d))}</p>` : ''}</div>`;
  }
  const rows = [[L.net || tr('Net total'), ofdMoney(t.net || 0, d), 'net']];
  if (t.net_incl_raw != null) rows.push([L.net_incl_raw, ofdMoney(t.net_incl_raw, d), 'incl']);
  if (t.net_excl_raw != null) rows.push([L.net_excl_raw, ofdMoney(t.net_excl_raw, d), 'excl']);
  for (const x of t.tax_lines || []) rows.push([x.label, ofdMoney(x.amount, d), 'tax']);
  if (d.vat_mode !== 'novat') rows.push([L.gross || tr('Gross total'), ofdMoney(t.gross || 0, d), 'gross']);
  return `<div class="ofdtotals" id="ofd-totals"><dl>${rows.map(([k, v, c]) => `<div class="ofdtr tr-${c}"><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('')}</dl>
    ${t.opt_note ? `<p class="muted ofdnote ofdoptnote">${esc(t.opt_note)}</p>` : '' /* 2.1041.0 (#5814) */}<p class="muted ofdnote">${esc(t.vat_note || '')}${t.fx_note ? ` · ${esc(t.fx_note)}` : ''}</p>
    ${adm && t.costs != null ? `<p class="muted ofdint">${ic('eye', 's')} ${trh('Internal: external costs {0}, surplus {1}', ofdMoney(t.costs, d), ofdMoney(t.margin, d))}</p>` : ''}
    ${adm && d.items_margin != null ? `<p class="muted ofdint ofdmsum">${trh('Surplus of the positions: {0}', ofdMoney(d.items_margin, d))}</p>` : ''}</div>`;
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
  // 2.936.0 (#5448): ofd2m = a phone shows it in "…" (ofdMoreItems); the main step keeps its button with its word
  const st = (v, icon, label, cls = ' ofd2m') => `<button type="button" class="btn sm ofdnext${cls}" data-ofd="kva-st" data-st="${v}" aria-label="${esc(tr(label))}" title="${esc(tr(label))}">${ic(icon, 's')}<span>${tr(label)}</span></button>`;
  const acc = d.status === 'accepted';
  const inv = `<button type="button" class="btn sm${acc ? ' pri' : ' ofd2m'} ofdnext ofdtoinv" data-ofd="to-invoice" aria-label="${esc(tr('Create invoice'))}" title="${esc(tr('An invoice draft with the positions of this quotation'))}">${ic('receipt', 's')}<span>${tr('Create invoice')}</span></button>`;
  if (d.status === 'sent') return st('accepted', 'check', N_('Accepted|document'), ' pri') + st('declined', 'x', N_('Rejected')) + inv;
  if (d.status === 'draft' && (lk || ro)) return st('sent', 'send', N_('Mark as sent'), ' pri') + inv;
  return inv;  // accepted: the main button; a draft that can be edited ("Finalise" behind) or declined: a plain one
}
async function kvaToInvoice(d, row) {
  if (row) try { d = await api('GET', `/api/office/docs/${d.id}`); } catch (x) { ofcErr(x); return; }  // 2.144.7 (#2572): a list row lacks parts / currency
  const have = oil_open(d);  // 2.356.0 C (#3003): an invoice of this quotation exists -> one question (it replaces the "not accepted" one)
  if (have.length) { if (!await askConfirm(tr('This quotation already has an invoice ({0}). Create another one?', have.map(x => x.number || tr('Draft')).join(', ')), '', {ok: tr('Create another invoice')})) return; d = {...d, oil_force: true}; }
  else if (d.status !== 'accepted' && !await askConfirm(tr('The quotation has not been accepted yet. Create the invoice anyway?'), '', {ok: tr('Create invoice')})) return;
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
// 2.437.0 B (#3621): "replaced by" on the old quotation, "replaces" on the new one
function ofr_linkHtml(d) {
  const a = x => `<a href="#office/offers/${x.id}">${esc(x.number || tr('Draft'))}</a>`;
  const line = (label, xs) => xs.length ? `<p class="oil_link muted ofr_link">${ic('file', 's')}<span>${esc(tr(label))} ${xs.map(a).join(', ')}</span></p>` : '';
  return d.kind === 'offer' ? line(N_('Replaced by'), d.replaced_by || []) + line(N_('Replaces'), d.replaces ? [d.replaces] : []) : '';
}
// 2.356.0 C (#3005): an invoice shows "Transfer of rights" only with rights (taken from the quotation or filled in) or after "+"
const oil_hasRights = d => OFD.rightsFor === d.id || Object.values(d.rights || {}).some(v => v && (typeof v !== 'object' || v.id || v.text));
// 2.356.0 C (#3005): "New invoice" > "From a quotation…": the open quotations (not declined, no invoice yet); a click is "Create invoice"
async function oil_pickOffer() {
  let rows; try { rows = await docsAll('/api/office/docs?kind=offer', api); } catch (x) { ofcErr(x); return; }
  rows = rows.filter(r => !['declined', 'superseded'].includes(r.status) && !r.invoiced).sort((a, b) => (b.status === 'accepted') - (a.status === 'accepted'));
  const md = modal(`<h3>${esc(tr('Invoice from a quotation'))}</h3>${rows.length ? `<ul class="ofdpick oil_pick" role="list">${rows.map(r => `<li><button type="button" class="ofcrow" data-oil-pick="${r.id}"><span class="ofcn"><b>${esc(r.number || (r.locked ? tr('(no number)') : ofdKindName(r.kind || 'offer', true)) /* 2.947.0 (#5454) */)}${r.recipient_name ? ` · ${esc(r.recipient_name)}` : ''}</b><small class="muted">${esc([r.project_title, r.date ? fmtDateLoc(r.date) : '', r.status_text].filter(Boolean).join(' · '))}</small></span><span class="ofdsum"><b>${esc(r.net_text)}</b><small class="muted">${esc(tr('net'))}</small></span></button></li>`).join('')}</ul>` : `<p class="muted">${esc(tr('No open quotations.'))}</p>`}<div class="foot"><span class="spacer"></span><button type="button" class="btn" data-m="close">${tr('Cancel')}</button></div>`);
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
const ofdActText = (a, x) => a !== 'reprice' ? tr(OFD_ACTIONS[a] || a) : x?.detail?.pct != null ? tr('prices changed by {0} %', fmtNum(x.detail.pct, 2)) : tr('prices changed');  // 2.1041.0 (#5812): the repricing names its percentage
const ofdWhen = iso => { const d = new Date(iso); return isNaN(+d) ? iso || '' : fmtStamp(d); };  // 2.368.0 B (#2982)
function ofdLogHtml(d) {
  if (!OFD.open.log) return `<p class="muted">${tr('Open to load the history.')}</p>`;
  if (OFD.logFor !== d.id || !OFD.log) { setTimeout(() => ofdLoadLog(d.id), 0); return `<p class="muted lempty">${tr('Loading…')}</p>`; }
  if (!OFD.log.length) return `<p class="muted">${tr('No entries yet.')}</p>`;
  return `<ul class="ofdlog" role="list">${/*html-ok*/ OFD.log.map(x => { /* every value esc(), agbLogNote escapes too (2.1041.0 #5812) */ const ks = Object.keys(x.detail?.after || {}); return `<li><span class="muted">${esc(ofdWhen(x.at))}</span> <b>${esc(x.user_name || x.detail?.name || '?')}</b> ${esc(ofdActText(x.action, x))}${ks.length && x.action === 'update' ? ` <span class="muted">(${esc(ks.join(', '))})</span>` : ''}${typeof agbLogNote === 'function' ? agbLogNote(x) : ''}</li>`; }).join('')}</ul>`;
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
// 2.892.0 (#5455): built on askDialog (Cancel left of the main button, focus on "Finalise now"); "Show as draft" is the extra middle button
async function ofdPdfAsk() {
  let pick = '';
  const r = await askDialog({title: tr('This document is not finalised yet'), body: tr('Finalise it now: number, positions, sums, sender and tax rates are frozen. Or look at it as a draft: every page is marked DRAFT.'),
    ok: tr('Finalise now'), after: md => {
      md.classList.add('ofdpa');
      const yes = md.querySelector('[data-cd="yes"]');
      yes.insertAdjacentHTML('beforebegin', `<button type="button" class="btn" data-pa="draft">${esc(tr('Show as draft'))}</button>`);
      md.querySelector('[data-pa="draft"]').addEventListener('click', () => { pick = 'draft'; yes.click(); });
    }});
  return r ? (pick || 'final') : null;
}
// 2.154.0 D (#2567): duplicating an invoice made from times: say that the hours stay with the original
// 2.437.0 B (#3621): a sent / accepted quotation asks whether the copy replaces it (ticked by default; a supplement stays next to it):
// false = cancelled, else true or the extra fields of the request
async function ofdDupAsk(d) {
  if (d.kind === 'offer' && ['sent', 'accepted'].includes(d.status)) return new Promise(res => {
    let out = false;
    const md = ofdDlg(tr('Mark the old quotation as superseded?'), `<label class="chkl"><input type="checkbox" id="ofd-dup-replaces" checked> ${esc(tr('Yes, {0} no longer counts', d.number || tr('Draft')))}</label><p class="muted">${esc(tr('For a supplement with only the new items, untick this: both quotations stay valid.'))}</p>`,
      tr('Duplicate'), m => { out = {replaces: $('#ofd-dup-replaces', m).checked}; });
    onRemove(md, () => res(out));
  });
  if (d.kind !== 'invoice' || !d.timesheet_ok) return true;
  return askConfirm(tr('Duplicate this invoice?'), tr('The hours of this invoice are already billed; the copy binds no times.'), {ok: tr('Duplicate')});
}

async function ofdPdfAskGo(d, dl) {
  if (!dl) { ofdPdfOpen(d, false); return; }  // 2.380.0 A (#3410): the preview of a draft opens at once (the server marks it DRAFT); only a download asks
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
const ofd_lnShut = j => !!OFD.langNotesShut && OFD.langNotesShut.id === j.id && OFD.langNotesShut.key === JSON.stringify(j.lang_notes);  // 2.482.0 (#3940)
// 2.855.0 (#5451): the error of the last failed save (a field's change says it at the field)
let OFD_SAVEX = /** @type {any} */ (null);
async function ofd_save1(method, url, body, src) {
  OFD.saving++; ofdSaveHint();
  const ver = ofd_verUrl(url) && body && typeof body === 'object' && !Array.isArray(body) ? OFD.doc.updated_at : null;
  if (ver) {
    if (src && Array.isArray(body.items)) body.items.forEach((x, i) => { if (!x.id && src[i]?.id) x.id = src[i].id; });
    body = {...body, expect_updated_at: ver};
  }
  if (body && typeof body === 'object' && ('lang' in body || 'reminder_level' in body)) OFD.langNotesShut = null;  // 2.482.0 (#3940): only a new language switch shows a closed note again
  // 2.552.0 (#4547): positions and fields of the document are kept in this browser until the server has them (core.js fdWrite):
  // the session ends during the save (401 -> sign-in -> reload) = sent after the sign-in under the same key and version
  // (saved elsewhere since: 409, not overwritten); the page going away (ofd_unload) sends it with keepalive
  const fk = ver && (method === 'PUT' || method === 'PATCH') ? fdWrite(method, url, body, {slot: `ofd.${method}.${url}`, send: !!OFD.unload}) : null;
  if (fk && OFD.unload) return null;
  try {
    const j = await rawFetch(method, url, body, fk ? fdGet('fdw', fk)?.b?.k : undefined);
    if (fk) fdDrop('fdw', fk);
    if (src && j) { const its = (j.part ? j.part.items : j.items) || []; src.forEach((x, i) => { if (!x.id && its[i]?.id) x.id = its[i].id; }); }
    if (OFD.doc && j && j.id === OFD.doc.id) OFD.doc = ofd_keepVia(j.items ? j : {...OFD.doc, ...j}); /* the status answer has no positions */ OFD.err = ''; if (j && j.lang_notes && !ofd_lnShut(j)) OFD.langNotes = {id: j.id, notes: j.lang_notes};  // 2.482.0 (#3940): a late answer does not reopen a closed note
    if (!ver && method !== 'GET' && OFD.doc && j && !j.updated_at && url.startsWith(`/api/office/docs/${OFD.doc.id}/`)) {  // a status / number / payment answer without the version: the current state
      try { const f = await rawFetch('GET', `/api/office/docs/${OFD.doc.id}`); if (OFD.doc && f && f.id === OFD.doc.id) OFD.doc = f; } catch { /* the next save reports it */ }
    }
    return j;
  }
  catch (x) {
    if (fk && x.message !== 'auth') fdDrop('fdw', fk);  // 2.552.0 (#4547): refused / offline: the field keeps the input (ofdChange), not sent later
    if (x.status === 409 && x.data?.doc && OFD.doc && x.data.doc.id === OFD.doc.id) { OFD.conflict = {id: OFD.doc.id, doc: x.data.doc}; OFD.err = ''; return null; }
    if (x.status === 409 && x.data?.code === 'terms_missing') { OFD.err = ''; return {terms_missing: x.data, message: x.message}; }  // 2.534.0 (#4339): the send dialog asks (ofcSendTerms)
    OFD_SAVEX = x; ofcErr(x); return null;  // 2.855.0 (#5451): said once (a field's save: at the field, ofdChange), never raw in the head
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
    raw_fee: it.raw_fee, producing: it.producing, in_handling: it.in_handling, in_markup: it.in_markup, intext: it.intext, cost: it.cost, discountable: it.discountable, discount_pct: it.discount_pct || 0, ref_part_id: it.ref_part_id, confirm: it.confirm || undefined,
    ...(OFD.doc.kind === 'offer' && it.kind !== 'heading' && it.kind !== 'text' ? {opt: it.opt || ''} : {})}));  // 2.1042.0 (#5815): + discount_pct; 2.1041.0 (#5814): optional / alternative  // 2.47.0 (#1215): + ref_part_id; 2.51.0 A (#1348): + confirm (an agent's mark)
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
  if (t.id === 'ofd-q') { OFD.q = t.value; const el = t.closest('.pboffers, .ofcbody'); if (el) keepFocus(el, () => fl_set(el, ofdListHtml())); ofd_qLoad(); }
}
function ofdKey(e) { if (e.key === 'Enter' && e.target.id === 'ofd-q') e.preventDefault(); }
// 2.359.2 B (#3049): a field of the document whose save failed keeps what was typed (also through the redraw and later ones, closing
// the page asks) and says so at the field, like ost_save in the office settings
async function ofdChange(e) {
  const t = e.target, form = t?.closest?.('.ofdeditor[data-fg]');
  if (!form || !OFD.doc || !fgField(t)) return ofdChange0(e);
  const fk = form.dataset.fg, k = fgKey(t), v = fgVal(t);
  OFD_SAVEX = null;
  await ofdChange0(e);
  const sx = OFD_SAVEX; OFD_SAVEX = null; if (!sx) return;
  const n = fgFields(document).find(x => x.closest('[data-fg]')?.dataset.fg === fk && fgKey(x) === k); if (!n) return;
  if (fgVal(n) !== v) { if (n.type === 'checkbox' || n.type === 'radio') n.checked = v; else n.value = v; }
  (FG.d[fk] ||= {f: {}}).f[k] = v;
  if (typeof ost_mark === 'function') ost_mark(n, 'err', tr('Not saved: {0}', ofcErrHere(sx)));  // 2.855.0 (#5451): the toast goes, the field says it
}
// a position field's input into its line (d = the document or the open part); false = no such line
function ofd_itSet(d, t) {
  const it = d.items[+t.dataset.i]; if (!it) return false;
  const k = t.dataset.k;
  if (t.type === 'checkbox') it[k] = t.checked ? 1 : 0;
  else if (['qty', 'rate', 'cost', 'discount_pct'].includes(k)) { const v = ofcNum(t.value); it[k] = v == null ? (k === 'qty' ? 1 : 0) : v; }  // 2.1042.0 (#5815): + its own discount
  else it[k] = t.value;
  if (k === 'unit' && it.unit !== 'percent' && !(+it.qty > 0)) it.qty = 1;  // 2.138.0 A (#2236): back from percent: quantity 1 when empty / 0
  return true;
}
// 2.552.0 (#4547): the page goes (the reload of an ended session, a closed tab) while a position is typed in and not left yet
// (no "change" yet): its input goes with keepalive and stays kept until the server has it (ofd_save1, core.js fdWrite)
function ofd_unload() {
  const t = document.activeElement;
  if (!OFD.doc?.can_edit || !t?.closest?.('.ofdeditor') || t.dataset?.i == null || !t.dataset.k || t.type === 'checkbox' || t.tagName === 'SELECT' || t.value === t.defaultValue) return;
  if (typeof tpf_ctx === 'function') tpf_ctx(t);
  if (!ofd_itSet(typeof tpCur === 'function' ? tpCur() : OFD.doc, t)) return;
  t.defaultValue = t.value;  // once (pagehide and a later bfcache leave)
  OFD.unload = true;
  try { ofdPutItems(); } finally { setTimeout(() => { OFD.unload = false; }, 0); }
}
addEventListener('pagehide', ofd_unload);
// 2.552.0 (#4547): a kept write of the open document went out after the sign-in: shown as the server has it now
addEventListener('fdw-sent', e => {
  const u = String(e.detail?.url || ''), m = u.match(/^\/api\/(?:office\/docs|fsref\/office_doc)\/(\d+)\//) || u.match(/^\/api\/(?:office\/docs|fsref\/office_doc)\/(\d+)$/);
  if (!m) return;
  if (e.detail.err) toast(e.detail.err.status === 409 ? tr('Changed in the meantime') : e.detail.err.message || tr('unknown'));
  const id = +m[1], again = () => { if ((OFD.doc?.id ?? OFD.docId) !== id) return; if (OFD.docLoading) setTimeout(again, 200); else ofdLoadDoc(id, true); };  // a load on its way may predate the write
  again();
});
async function ofdChange0(e) {
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
    if (!ofd_itSet(d, t)) return;
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
      const tx = $('#ofd-r-' + k + '-t'); if (tx && t.value) tx.value = ofcText(+t.value, ofdTl(d));
    }
    await ofdPatch({rights: ofdRightsBody()}); return;
  }
  if (f === 'intro_pick' || f === 'closing_pick') { if (!t.value) return; const k = f.replace('_pick', ''); const ta = $('#ofd-' + k); const v = ofcText(+t.value, ofdTl(d)); if (ta) ta.value = v; await ofdPatch({[k]: v}); return; }
  if (f === 'recipient_name' || f === 'recipient_lines') { await ofdPatch({recipient: {name: $('#ofd-recipient_name')?.value ?? d.recipient?.name, lines: ($('#ofd-recipient_lines')?.value ?? (d.recipient?.lines || []).join('\n')).split('\n')}}); return; }
  if (f === 'client_id') { await ofdPatch({client_id: t.value ? +t.value : null, recipient_from_client: !!t.value}); return; }
  if (f === 'contract_id') { await ofdPatch({contract_id: t.value ? +t.value : null}); return; }
  if (f === 'producing_on') { await ofdPatch({producing_on: t.checked ? 1 : 0}); return; }  // 2.47.0 (#1645)
  if (f === 'subtotals' || f === 'flat_print') { await ofdSave('PATCH', `/api/office/docs/${OFD.doc.id}`, {[f]: t.checked ? 1 : 0}); return; }  // 2.1041.0 (#5816, #5817): the document's, also with a part open
  if (f === 'accept_on') { await ofdPatch({accept_on: t.value === '' ? null : +t.value}); return; }  // 2.114.4 B (#2270)
  if (/^(handling|markup)_on$/.test(f)) { const k = f.slice(0, -3); await ofdPatch({[k + '_pct']: t.checked ? prd_opts()[k]?.pct ?? 0 : null}); return; }  // 2.113.1 (#2252)
  if (f === 'markup_stacked') { await ofdPatch({markup_stacked: t.checked ? 1 : 0}); return; }
  if (f === 'handling_pct' || f === 'markup_pct') { await ofdPatch({[f]: ofcNum(t.value) ?? 0}); return; }
  if (f === 'discount_mode') {  // 2.1042.0 (#5815): percent <-> fixed amount; the other value is cleared on the server once one is set
    OFD.discAmt = {id: d.id, on: t.value === 'amount'};
    if (t.value === 'amount' && +d.discount_pct > 0) await ofdPatch({discount_pct: 0});
    else if (t.value !== 'amount' && +d.discount_amount > 0) await ofdPatch({discount_amount: null});
    else ofdDraw();
    $('#ofd-' + (t.value === 'amount' ? 'discount_amount' : 'discount_pct'))?.focus({preventScroll: true});
    return;
  }
  if (['fx_rate', 'raw_factor', 'prod_quotient', 'producing_rate', 'discount_pct', 'discount_amount', 'payment_days', 'reminder_level', 'reminder_fee', 'reminder_deadline_days', 'skonto_pct', 'skonto_days'].includes(f)) { const v = ofcNum(t.value, ['fx_rate', 'raw_factor', 'prod_quotient'].includes(f)); await ofdPatch({[f]: v}); return; }
  await ofdPatch({[f]: t.value});
}
// 2.87.9 (#1920): the "More" menu of a document - one list for the editor and for the rows of the list (d = the document or a list row)
function ofdMoreItems(d, inList) {
  const gone = () => { OFD.doc = null; OFD.list = null; if (inList) ofdLoadList(true); else go(`office/${ofd_sec()}`); };
  if (d.via_folder) return [{label: tr('Preview (PDF)'), icon: 'eye', fn: () => ofdPdfOpen(d, false)}];  // 2.199.0 B (#2742): read through a folder only
  // 2.936.0 (#5448): the editor's next steps a phone hides in its head (office.css .ofd2m) come first here, a tap = that button
  const mvIc = b => ({'to-invoice': 'receipt', 'to-ls': 'file'})[b.dataset.ofd] || (b.dataset.onum ? 'edit' : b.dataset.st === 'declined' ? 'x' : b.dataset.st === 'sent' ? 'send' : 'check');
  const mv = inList ? [] : $$('#view .ofdhead .ofd2m, #view .ofdhead .onumpen').filter(b => getComputedStyle(b).display === 'none')  // + "Change number" (its pen)
    .map(b => ({label: b.textContent.trim() || b.getAttribute('aria-label') || '', icon: mvIc(b), next: b.dataset.ofd === 'to-ls', fn: () => b.click()}));
  const items = [
      ...mv, mv.length ? '-' : null,
      !d.trial ? {label: tr('File in a folder…'), icon: 'folder', fn: () => ofd_fileDlg(d)} : null,  // 2.199.0 B (#2742)
      d.kind === 'credit' ? null : {label: tr('Duplicate'), icon: 'copy', fn: async () => { try { const ask = await ofdDupAsk(d); if (!ask) return; const j = await ofdRefCall(`dup${d.id}`, ref => rawFetch('POST', `/api/office/docs/${d.id}/duplicate`, {client_ref: ref, ...ask})); OFD.list = null; OFD.doc = j; toast(tr('Copied as {0}', j.number || tr('Draft'))); go(ofd_href(j.id, j.kind)); } catch (x) { ofcErr(x); } }},
      !inList && d.kind === 'offer' && d.status === 'draft' && !d.locked && !d.via_folder && d.can_edit !== false ? {label: tr('Adjust prices…'), icon: 'calc', fn: () => loadModule('reprice').then(() => orp_open(OFD.doc || d), x => ofcErr(x))} : null,  // 2.1041.0 (#5812): Nachkalkulieren (office_reprice.js)
      d.kind === 'offer' && d.client_id && ofcAdmin() && typeof dtFromOffer === 'function' ? {label: tr('Create order confirmation'), icon: 'file', fn: () => dtFromOffer(d)} : null,  // 2.93.0 A (#1927)
      inList && d.kind === 'offer' ? {label: tr('Create invoice'), icon: 'receipt', fn: () => kvaToInvoice(d, true)} : null,  // 2.144.7 (#2572): in the list row menu; the editor has the button in its bar
      !inList ? null : {label: tr('Preview (PDF)'), icon: 'eye', fn: () => ofdPdfOpen(d, false)},  // 2.40.0 (#1364): the PDF, not the JSON print model; 2.138.2 A (#2393): a list row opens marked; 2.380.0 A (#3410): a draft opens at once, too; 2.356.0 C (#3005): the editor has its Preview button, the menu no second one
      !inList ? null : {label: tr('Download PDF'), icon: 'download', fn: () => d.status === 'draft' && !d.locked ? ofdPdfAskGo(d, true) : ofdPdfOpen(d, true)},  // 2.435.0 B (#3618)
      !inList || !ofdCanSend(d) || d.trial ? null : {label: tr('Send by e-mail…'), icon: 'send', fn: async () => { try { ofdSendDialog(d.timesheet_ok === undefined ? await api('GET', `/api/office/docs/${d.id}`) : d); } catch (x) { ofcErr(x); } }},  // 2.435.0 B (#3618): the list row may lack fields, load the whole document first
      ...(typeof ls_moreItems === 'function' ? ls_moreItems(d, inList) : []),  // 2.120.0 D (#2089)
      ofdIsInv(d) && d.kind !== 'reminder' && d.kind !== 'delivery' && d.locked && (ofcFeat('docs.einvoice') || d.xml_sha256) ? {label: tr('E-invoice XML'), icon: 'download', fn: () => window.open(ofc_spUrl(`/api/office/docs/${d.id}/xml`), '_blank', 'noopener')} : null,
      ...(typeof pep_moreItems === 'function' ? pep_moreItems(d) : []),  // 2.154.0 B (#1960): send over Peppol, UBL
      ofdIsInv(d) && d.kind !== 'reminder' && d.kind !== 'delivery' && d.locked && ofcFeat('books.datev') ? {label: tr('Send to the DATEV inbox'), icon: 'send', fn: async () => { const j = await ofdSave('POST', `/api/office/docs/${d.id}/datev`); if (j) toast(tr('Sent to the DATEV inbox')); }} : null,
      d.status === 'draft' && !d.locked && typeof ofm_can === 'function' && ofm_can(ofm_officeFrom()) ? {label: tr('Move to another workspace…'), icon: 'brief',  // 2.97.0 C (#2049)
        fn: () => ofm_move({what: 'drafts', ids: [d.id], from: ofm_officeFrom(), label: qn(d.number || d.project_title || ofdKindName(d.kind, true)), after: async () => gone()})} : null,
      d.can_unlock ? {label: tr('Undo finalising'), icon: 'undo', fn: async () => {  // 2.114.2 A (#2263): a finalised quotation never sent
        if (!await askConfirm(tr('Back to a draft?'), tr('The quotation can be changed again and keeps its number {0}.', d.number || ''), {ok: tr('Undo finalising')})) return;
        try { const j = await rawFetch('POST', `/api/office/docs/${d.id}/unlock`); OFD.list = null; OFD.log = null; if (inList) ofdLoadList(true); else { OFD.doc = j; ofdDraw(); } toast(tr('Back to a draft')); } catch (x) { ofcErr(x); }
      }} : null,
      d.kind === 'invoice' && d.status === 'cancelled' && d.time_billed?.entries && ofcAdmin() ? {label: tr('Release the time again'), icon: 'clock', fn: () => tbill_release(d)} : null,  // 2.144.6 A (#2053)
      d.can_delete ? '-' : null,
      d.can_delete ? {label: tr('Delete'), icon: 'trash', cls: 'danger', fn: async () => {
        if (d.trial) { if (!await askConfirm(tr('Delete trial document?'), tr('{0} is a trial document and disappears permanently.', d.number || ofdKindName(d.kind, true)), {ok: tr('Delete'), danger: true})) return; }  // 2.144.10 C (#2576)
        else if (!await askConfirm(tr('Delete {0}?', d.number || ofdKindName(d.kind, true)), d.locked ? tr('Its number stays used and shows as a gap in the office log.') : tr('Its number stays used.'), {ok: tr('Delete'), danger: true})) return;  // 2.114.2 A (#2263); 2.417.0 C (#2604): no test phase rule for sent quotations any more
        try { const j = await api('DELETE', `/api/office/docs/${d.id}`); gone();  // 2.272.0 E2 (#3038): a draft goes to the office trash, the toast undoes it
          if (j?.trash) toast(tr('“{0}” moved to the trash', d.number || ofdKindName(d.kind, true)), () => otb_restore(j.trash.id, null, j.trash.kind, true));  // 2.1005.0 (#5415): a draft in the core's trash
          else toast(tr('Deleted')); } catch (x) { ofcErr(x); }
      }} : null];
  return inList ? [{label: tr('Open'), icon: 'edit', fn: () => go(ofd_href(d.id, d.kind))}, ...fv2_menuRow('r:office_doc:' + d.id) /* 2.441.0 (#3592) */, ...items] : items;
}
// 2.87.9 (#1920): right click / long press on a row opens the same menu as the dots button
function ofdRowMenu(id, anchor) {
  if (anchor?.dataset.arch) { oim_rowMenu(anchor.dataset.arch, anchor); return; }  // 2.451.0 (#3834): an archive row
  const r = (OFD.list || []).find(x => String(x.id) === String(id)); if (!r) return;
  menu(anchor, ofdMoreItems({...r, can_delete: OFD.role === 'admin' && (r.can_delete ?? (!r.locked && r.status !== 'sent' && !(['invoice', 'credit'].includes(r.kind) && r.number)))}, true));  // 2.114.2 A (#2263): the server marks the finalised quotations that may go; 2.126.0 A (#1966): a numbered invoice / credit note draft stays; 2.417.0 C (#2604): the server's false counts (an open quotation past draft)
}
window.addEventListener('click', e => { if (OFD.lp && ms_lpRecent(OFD.lp) && e.target.closest?.('.oimarch a.ofdrow')) { e.preventDefault(); e.stopPropagation(); } }, true);  // 2.451.0 (#3834): the press ends on a link: no preview under the menu
function ofdCtx(e) { const b = e.target.closest('.ofdrow'); if (!b) return; e.preventDefault(); ofdRowMenu(b.dataset.id, b); }
async function ofdClick(e) {
  if (typeof tpf_ctx === 'function') tpf_ctx(e.target);  // 2.113.0 (#2248): the open part the click happens in (also for the agent marks' own listener)
  const b = e.target.closest('[data-ofd]'); if (!b) return;
  const a = b.dataset.ofd, d = typeof tpCur === 'function' ? tpCur() : OFD.doc;  // 2.47.0 (#1215): an open part's positions
  const sc = typeof tpf_sc === 'function' ? tpf_sc() : '';  // 2.113.0 (#2248): focus inside that part after the redraw
  if (a === 'pdf') return;  // the link itself
  e.preventDefault();
  if (a === 'trash') { otb_open(); return; }  // 2.272.0 E2 (#3038)
  if (a === 'new') { await tri_new('offer'); return; }  // 2.380.0 B (#3418): created at once; 2.417.0 C (#3445): trial in the test mode
  if (a === 'new-ls' || a === 'to-ls') return ls_click(a, d);  // 2.120.0 D (#2089)
  if (a === 'open') { if (typeof ms_lpRecent === 'function' && OFD.lp && ms_lpRecent(OFD.lp)) return; OFD.lsdTop = b.closest('.lsdl')?.scrollTop || 0; go(ofd_href(b.dataset.id)); return; }  // 2.557.0 A (#4553): + the place of the list beside it
  if (a === 'rowmore') { ofdRowMenu(b.dataset.id, b); return; }
  if (a === 'back') { OFD.doc = null; OFD.list = null; navUp(`office/${ofd_sec()}/${OFD.kind}`); return; }  // 2.743.0 (#5235): navUp  // 2.380.0 B (#3409): the area's list, its tab named (Back from a later tab returns here)
  if (a === 'kind') { OFD.kind = b.dataset.kind; OFD.status = ''; OFD.list = null; go(`office/${ofd_sec()}/${OFD.kind}`); return; }  // 2.356.0 C (#3004): a history step per tab
  if (a === 'dun-open') { dun_open(); return; }  // 2.147.1 B (#2054): the suggested reminder drafts
  if (a === 'new-inv') {
    menu(b, [{label: tr('Empty invoice'), icon: 'plus', fn: () => tri_new('invoice')}, {label: tr('From time entries…'), icon: 'clock', fn: ofdFromTimeDialog},
      {label: tr('From a quotation…'), icon: 'receipt', fn: oil_pickOffer}]);  // 2.356.0 C (#3005): a choice of the open quotations (was a text only); 2.417.0 C (#3445): no trial entry (the test mode decides)
    return;
  }
  if (a === 'remind') { ofdReminderDialog(); return; }
  if (a === 'listmore') { ofdMore(); return; }
  if (!d) return;
  if (a === 'pdf-ask') { await ofdPdfAskGo(OFD.doc, !!b.dataset.dl); return; }  // 2.138.2 A (#2393)
  if (a.startsWith('tp-') && typeof tpClick === 'function') { await tpClick(a, b); return; }  // 2.47.0 (#1215): the parts
  if (a === 'to-invoice') { await kvaToInvoice(OFD.doc); return; }
  if (a === 'kva-st') { await ofdSave('POST', `/api/office/docs/${OFD.doc.id}/status`, {status: b.dataset.st}); return; }  // 2.138.0 E (#2235): the answer updates OFD.doc
  if (a === 'credit') {
    if (!await askConfirm(tr('Credit note for {0}?', d.number || ''), tr('A draft with all positions is made. Shorten it for a partial credit; finalised over the full amount it cancels the invoice.'), {ok: tr('Create credit note')})) return;
    try { const j = await ofdRefCall(`credit${d.id}`, ref => rawFetch('POST', `/api/office/docs/${d.id}/credit`, {client_ref: ref})); OFD.list = null; OFD.kind = 'credit'; OFD.doc = j; go(ofd_href(j.id, j.kind)); } catch (x) { ofcErr(x); } return;
  }
  if (a === 'pay') { ofdPaymentDialog(d); return; }
  if (a === 'pay-del') {  // 2.152.0 C (#2168): a payment is reversed by a second line (both stay visible), never deleted
    ofdDlg(tr('Reverse payment'), `<p class="muted">${esc(tr('A reversal line with the negative amount is booked; the payment stays visible.'))}</p>`
      + ofdF('p-rnote', tr('Reason (optional)'), `<input id="ofd-p-rnote" maxlength="500">`),
      tr('Reverse payment'), async md => { const j = await ofdSave('DELETE', `/api/office/docs/${d.id}/payments/${b.dataset.pid}`, {note: $('#ofd-p-rnote', md).value}); if (!j) return false; toast(tr('Payment reversed')); });
    return;
  }
  if (a === 'send') { if (d.trial) { toast(tr('A trial document cannot be sent by e-mail; create a real document for your client')); return; } ofdSendDialog(d); return; }  // 2.542.0 (#4594)
  if (a === 'ln-x') { const n = OFD.langNotes; OFD.langNotesShut = n ? {id: n.id, key: JSON.stringify(n.notes)} : null; OFD.langNotes = null; ofdDraw(); return; }  // 2.482.0 (#3940): remembered as closed
  if (a === 'rights-add') { OFD.rightsFor = d.id; OFD.open.rights = true; ofdDraw(); return; }  // 2.356.0 C (#3005)
  if (a === 'cf-reload') { ofd_cfReload(); return; }  // 2.269.0 A (#3012)
  if (a === 'fee' && b.dataset.st === 'paid') { ofdFeeDayDialog(d); return; }  // 2.912.0 (#5419): asks the day the money came
  if (a === 'fee') { const j = await ofdSave('POST', `/api/office/docs/${d.id}/fee`, {state: b.dataset.st || ''}); if (j) savedTick('.ofdfeeinfo > span'); return; }  // 2.298.0 A1 (#3186): the quiet tick
  if (a === 'it-disc') { d.items.push({kind: 'discount', title: '', detail: '', qty: 1, unit: 'flat', rate: 0, tax: 'standard', raw_fee: 0, producing: 0, intext: 'intern', cost: 0, discountable: 1}); await ofdPutItems(); $(`${sc}.ofdits [data-i="${d.items.length - 1}"][data-k="rate"]`)?.focus(); return; }
  if (a === 'number') { const j = await ofdSave('POST', `/api/office/docs/${d.id}/number`, {}); if (j) { d.number = j.number; ofdDraw(); } return; }
  if (a === 'finalize') {
    // 2.431.0 B (#3605): the dialog names the number it gets (its own one, else the next of the scheme, only looked at); no preview = as before
    const pv = await rawFetch('GET', `/api/office/docs/${d.id}/number-preview`).catch(() => null);
    const fin = tr('Number, positions, sums, sender and tax rates are frozen. Afterwards it can only be duplicated.');
    if (!await askConfirm(tr('Finalise this document?'), fin, {ok: tr('Finalise'), ...(pv?.number ? {html: `<p class="ofdfinno">${esc(tr('Will be finalised as {0}', '\u0000')).replace('\u0000', `<b>${esc(pv.number)}</b>`)}</p><p>${esc(fin)}</p>`} : {})})) return;
    const j = await ofdSave('POST', `/api/office/docs/${d.id}/finalize`, {}); if (j) toast(tr('Finalised as {0}', j.number || ''));
    return;
  }
  if (a === 'dup') { try { const ask = await ofdDupAsk(d); if (!ask) return; const j = await ofdRefCall(`dup${d.id}`, ref => rawFetch('POST', `/api/office/docs/${d.id}/duplicate`, {client_ref: ref, ...ask})); OFD.list = null; OFD.doc = j; toast(tr('Copied as {0}', j.number || tr('Draft'))); go(ofd_href(j.id, j.kind)); } catch (x) { ofcErr(x); } return; }
  if (a === 'more') { menu(b, ofdMoreItems(d)); return; }
  if (a === 'it-svc') { ofdServicePicker(); return; }
  if (a === 'it-head') { d.items.push({kind: 'heading', title: '', detail: '', qty: 1, unit: 'day', rate: 0, tax: 'standard', raw_fee: 0, producing: 0, intext: 'intern', cost: 0, discountable: 1}); ofdDraw();  // 2.114.1 A (#2254): saved with the first typed title
    $(`${sc}.ofdits [data-i="${d.items.length - 1}"][data-k="title"]`)?.focus(); return; }
  if (a === 'it-text') {
    const blocks = ofcRows('texts').filter(x => x.kind === 'block' && !x.archived);
    const add = async text => { d.items.push({kind: 'text', title: '', detail: text, qty: 1, unit: 'day', rate: 0, tax: 'standard', raw_fee: 0, producing: 0, intext: 'intern', cost: 0, discountable: 1}); if (text) await ofdPutItems(); else ofdDraw(); if (!text) $(`${sc}.ofdits [data-i="${d.items.length - 1}"][data-k="detail"]`)?.focus(); };
    if (!blocks.length) { await add(''); return; }
    menu(b, [{label: tr('Free text'), icon: 'edit', fn: () => add('')}, '-', ...blocks.map(x => ({label: x.key || (x.text_de || x.text_en).slice(0, 50), fn: () => add(ofcText(x.id, ofdTl(d)))}))]);
    return;
  }
  if (a === 'it-del') { d.items.splice(+b.dataset.i, 1); await ofdPutItems(); return; }
  if (a === 'it-pdisc') { const it = d.items[+b.dataset.i]; if (!it) return; it._pdisc = 1; ofdDraw(); $(`${sc}.ofdits [data-i="${b.dataset.i}"][data-k="discount_pct"]`)?.focus({preventScroll: true}); return; }  // 2.1042.0 (#5815)
  if (a === 'it-up' || a === 'it-down') { const i = +b.dataset.i, j = a === 'it-up' ? i - 1 : i + 1; if (j < 0 || j >= d.items.length) return; await ofdMoveItem(d, i, j); setTimeout(() => $(`${sc}.ofdits [data-ofd="${a}"][data-i="${j}"]`)?.focus(), 0); return; }
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
  if (!d.client_id) return `<div class="row cdnrec"><label>${esc(tr('Recipient'))}</label><div class="cdnrecb">${addr || `<span class="muted">${esc(tr('No client selected'))}</span>`}${ro ? '' : `<button type="button" class="btn sm" data-ofd="client-new">${ic('plus', 's')}<span>${tr('Add client')}</span></button>`}</div></div>`;
  const miss = d.recipient_missing && !ro ? `<p class="cdnmiss" role="status">${ic('info', 's')} ${esc(tr('Address missing - add it at the client'))}</p>` : '';
  return `<div class="row cdnrec"><label>${esc(tr('Address'))}</label><div class="cdnrecb">${addr}${miss}${ro ? '' : `<button type="button" class="linkbtn" data-ofd="client-edit">${ic('edit', 's')} ${tr('Edit client')}</button>`}</div></div>`;
}
async function cdn_editClient(d) {
  if (typeof clientModal !== 'function' || !d.client_id) return;
  let c; try { c = await api('GET', `/api/clients/${d.client_id}`); } catch (x) { ofcErr(x); return; }
  clientModal(c, {stay: true, done: () => ofdLoadDoc(d.id, true)});
}
// 2.38.0 (#1021, F1): creating, payments, sending, reminders (small dialogs; the server validates)
async function ofdCreate(body) {
  try { const j = await ofdRefCall('new', ref => rawFetch('POST', '/api/office/docs', {...body, client_ref: ref})); OFD.doc = j; OFD.list = null; OFD.kind = j.kind; go(ofd_href(j.id, j.kind)); } catch (x) { ofcErr(x); }
}
// 2.144.10 C (#2576): trial documents (TEST number, watermark MUSTER, deletable any time); list: tag, filter, count.
// 2.417.0 C (#3445): one test mode instead - a switch in the office settings, per person and office (setting trial_mode =
// ["<office id>"], set_delta). On: a strip above the office with "Switch off", every new document is a trial one, the list
// has the filter "All / Real only / Trial only" and the line "N trial documents". Off (the default): none of it; existing
// trial documents keep their tag. "Delete all trial documents" sits in the test mode section of the settings.
const TRI = {count: null, office: null};
function tri_meta(j) {
  if (j.first) OFD.first = j.first;
  OFD.office = j.office_id ?? j.org_id ?? OFD.office;
  OFD.trialCount = +j.trial_count || 0;
  TRI.count = OFD.trialCount; TRI.office = String(OFD.office ?? '');  // 2.417.0 C (#3445): the settings' "Delete all" count
}
const tri_tag = r => r?.trial ? `<small class="tri-tag" data-trial="1">${esc(tr('Trial|document'))}</small>` : '';
const tri_office = () => String(OFC.info?.org_id ?? OFD.office ?? '');
function tri_modes() {
  const v = S.settings?.trial_mode;
  if (Array.isArray(v)) return v.map(String);
  try { const a = JSON.parse(v || '[]'); return Array.isArray(a) ? a.map(String) : []; } catch { return []; }
}
const tri_on = () => !!tri_office() && tri_modes().includes(tri_office());
const tri_flag = () => tri_on() ? {trial: true} : {};
async function tri_set(on) {
  const off = tri_office(); if (!off) return;
  const was = S.settings?.trial_mode;
  if (S.settings) S.settings.trial_mode = JSON.stringify([...tri_modes().filter(x => x !== off), ...(on ? [off] : [])]);
  if (!on) { OFD.trial = ''; LS.set('ofdTrial', ''); }  // the filter's memory goes with the mode
  OFD.list = null;
  if (typeof ofcDraw === 'function') ofcDraw();
  try { await api('PATCH', '/api/settings', {set_delta: {trial_mode: on ? {add: [off]} : {remove: [off]}}}); }  // only this office (another tab keeps its own)
  catch (x) {  // 2.417.0 (#3445 review F4): the switch goes back when the server did not take it
    if (S.settings) S.settings.trial_mode = was;
    OFD.list = null;
    if (typeof ofcDraw === 'function') ofcDraw();
    ofcErr(x);
  }
}
function tri_stripHtml() {
  if (!tri_on()) return '';
  return `<div class="tri-strip" role="status">${ic('info', 's')}<span>${esc(tr('Test mode - documents get a TEST number and the watermark MUSTER'))}</span><button type="button" class="btn sm" data-tri="off">${tr('Switch off')}</button></div>`;
}
// "New quotation" / "Empty invoice" / "From time entries…" / a letter create at once; in the test mode as a trial document
async function tri_new(kind) {
  if (!OFC.info && typeof ofcInfo === 'function') await ofcInfo();  // the palette starts it before the office was opened (whose test mode?)
  try {
    const j = await ofdRefCall('new', ref => rawFetch('POST', '/api/office/docs', {...(kind === 'offer' ? {} : {kind}), ...tri_flag(), client_ref: ref}));
    OFD.doc = j; OFD.list = null; OFD.kind = j.kind || kind; go(ofd_href(j.id, j.kind || kind));
  } catch (x) { ofcErr(x); }
}
function tri_filterHtml() {
  if (!tri_on()) return '';
  return `<select id="ofd-trial" aria-label="${esc(tr('Trial documents'))}"><option value="">${tr('All|trial filter')}</option><option value="0" ${OFD.trial === '0' ? 'selected' : ''}>${tr('Real only')}</option><option value="1" ${OFD.trial === '1' ? 'selected' : ''}>${tr('Trial only')}</option></select>`;
}
function tri_barHtml() {
  if (!tri_on() || !OFD.trialCount) return '';
  return `<div class="tri-bar muted"><span>${esc(trn('{0} trial document in this office', '{0} trial documents in this office', OFD.trialCount))}</span></div>`;
}
// the test mode section of the office settings (every person; "Delete all" for the admin, with the count of the office)
function tri_settingsHtml() {
  const on = tri_on(), adm = OFC.info?.role === 'admin';
  if (TRI.office !== tri_office()) { TRI.office = tri_office(); TRI.count = null; }
  if (adm && TRI.count == null) { TRI.count = 0; api('GET', '/api/office/trial').then(j => { TRI.count = +j.trial_count || 0; const b = $('#tri-del-all'); if (b) { b.hidden = !TRI.count; $('span', b).textContent = tri_delLabel(); } }).catch(() => { /* the button stays hidden */ }); }
  return `<h3 id="tri-h">${tr('Test mode')}</h3><div class="row tri-row"><label class="chkl swl" data-fg-skip><span class="swc"><input type="checkbox" role="switch" id="tri-mode" ${on ? 'checked' : ''}><span class="swt" aria-hidden="true"></span></span><span>${tr('Test mode on')}</span></label>${''/* 2.555.0 (#4664): not the heading's word once more */}
    <div class="shint keep">${tr('New documents get a TEST number and the watermark MUSTER, no e-invoice and no bookkeeping. Only for you; colleagues do not see it.')}</div></div>
    ${adm ? `<div class="lacts"><button type="button" class="btn sm danger" id="tri-del-all" data-tri="del-all" ${TRI.count ? '' : 'hidden'}>${ic('trash', 's')}<span>${esc(tri_delLabel())}</span></button></div>` : ''}`;
}
const tri_delLabel = () => trn('Delete {0} trial document', 'Delete all {0} trial documents', TRI.count || 0);
async function tri_deleteAll() {
  const n = TRI.count || OFD.trialCount;
  if (!await askConfirm(tr('Delete all trial documents?'), trn('{0} trial document (with its PDFs and share links) disappears permanently. Real documents stay.', '{0} trial documents (with their PDFs and share links) disappear permanently. Real documents stay.', n), {ok: tr('Delete all'), danger: true})) return;
  try { const j = await rawFetch('POST', '/api/office/trial/delete-all', {}); OFD.list = null; OFD.doc = null; TRI.count = 0; const b = $('#tri-del-all'); if (b) b.hidden = true; toast(trn('{0} trial document deleted', '{0} trial documents deleted', (+j.docs || 0) + (+j.gen_docs || 0))); }
  catch (x) { ofcErr(x); }
}
document.addEventListener('change', e => { if (e.target.id === 'tri-mode') tri_set(e.target.checked); });
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-tri]'); if (!b) return;
  if (b.dataset.tri === 'off') tri_set(false);
  else if (b.dataset.tri === 'del-all') tri_deleteAll();
});
const ofdClientOpts = () => typeof clientsOn === 'function' && clientsOn() ? (S.clients || []).filter(c => !c.archived && (c.org_id || null) === pb_clOrg()).map(c => [c.id, cdn_label(c)]) : [];
function ofdDlg(title, body, okLabel, onOk) {
  const md = modal(`<h3>${esc(title)}</h3><div class="ofddlg">${body}</div><div class="foot"><span class="aerr" role="alert"></span><span class="spacer"></span><button type="button" class="btn" data-m="close">${tr('Cancel')}</button><button type="button" class="btn pri" data-m="ok">${esc(okLabel)}</button></div>`);
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    if (b.dataset.m === 'ok') { b.disabled = true; try { if (await onOk(md) !== false) md.remove(); } catch (x) { $('.aerr', md).textContent = ofcErrHere(x); } b.disabled = false; }
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
  try { info = await api('GET', `/api/office/docs/${d.id}/progress`); } catch (x) { ofcErr(x); return; }
  const pl = info.progress || [], cur = ofcSym(d.currency);  // 2.189.0 (#2475)
  const plist = pl.length ? `<ul class="ofdpick abs-list" role="list">${pl.map(p => `<li><span class="ofcn"><b>${esc(p.number || tr('Draft'))}</b><small class="muted">${esc([p.date ? fmtDateLoc(p.date) : '', p.gross_text, !p.locked ? tr('Draft') : +p.open <= 0 ? tr('Paid') : tr('open: {0}', p.open_text || p.open)].filter(Boolean).join(' · '))}</small></span></li>`).join('')}</ul>`
    : `<p class="muted">${tr('No progress invoices yet')}</p>`;
  const modes = [['full', tr('Full invoice')], ['progress', tr('Progress invoice')], ['final', tr('Final invoice')]];
  const hasP = pl.some(p => p.locked), pick = hasP ? 'final' : 'full';  // 2.354.0 B (#2836): with finalised progress invoices only progress / final (the server answers 409)
  const md = ofdDlg(tr('Create invoice'), `<fieldset class="tpmodes"><legend class="muted">${tr('Type of invoice')}</legend>${modes.map(([v, n]) => `<label class="tpmode"><input type="radio" name="abs-type" value="${v}" ${v === pick ? 'checked' : ''} ${hasP && v === 'full' ? 'disabled' : ''}> <span>${esc(n)}</span></label>`).join('')}</fieldset>
    ${hasP ? `<p class="muted ofchint abs-has">${tr('The quotation has progress invoices; create the final invoice instead')}</p>` : ''}
    <div class="abs-p" hidden>${ofdF('abs-val', tr('Progress payment'), `<span class="lacts"><input id="ofd-abs-val" inputmode="decimal" class="numin" maxlength="14">${ofcSel('ofd-abs-unit', 'pct', [['pct', '%'], ['amount', cur + ' ' + tr('net')]])}</span>`, tr('quotation net {0}, not yet billed {1}', info.net_text, info.remaining_text), {keep: 1})}</div>
    <div class="abs-f" ${hasP ? '' : 'hidden'}><p class="muted ofchint">${tr('The whole quotation, less these progress invoices (finalised ones only):')}</p>${plist}</div>`,
    tr('Create invoice'), async m => {
      const typ = $('input[name="abs-type"]:checked', m)?.value || 'full';
      if (typ === 'full' && d.parts?.length && typeof tpInvoiceDialog === 'function') { setTimeout(() => tpInvoiceDialog(d), 0); return; }
      const b = {};
      if (typ !== 'full') b.inv_type = typ;
      if (typ === 'progress') { const v = ofcNum($('#ofd-abs-val', m).value); if (!v) throw new Error(tr('Enter an amount or a percentage')); b[$('#ofd-abs-unit', m).value] = v; }
      const j = await oil_post(d, b); if (!j) return;  // 2.356.0 C (#3003)
      OFD.list = null; OFD.kind = 'invoice'; OFD.doc = j; toast(tr('Invoice draft created')); go(ofd_href(j.id, j.kind));
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
    + ofdF('ft-to', tr('Until'), dateIn('ofd-ft-to', iso(today), {label: tr('Until'), clear: false, after: 'ofd-ft-from'})) + `<p class="muted ofchint">${tr('One position per project; rate from the client or fill it in later.')}</p><p class="ofchint tbill-open" role="status" aria-live="polite"></p>`,
    tr('Create'), async m => { const j = await ofdRefCall('fromtime', ref => rawFetch('POST', '/api/office/docs/from-time', {client_id: +$('#ofd-ft-client', m).value, from: $('#ofd-ft-from', m).value, to: $('#ofd-ft-to', m).value, ...tri_flag(), client_ref: ref})); OFD.list = null; OFD.kind = 'invoice'; OFD.doc = j; tbill_ftDone(j.time); go(ofd_href(j.id, j.kind)); });
  tbill_ftPreview(md); md.addEventListener('change', () => tbill_ftPreview(md));
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
  else if (t.skipped_billed || t.skipped_unbillable) toast(trn('{0} entry taken; skipped: {1} already billed, {2} not billable', '{0} entries taken; skipped: {1} already billed, {2} not billable', t.taken_entries, t.skipped_billed, t.skipped_unbillable));
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
  catch (x) { if (TBL.key === key) TBL.err = ofcErrHere(x); }
  if (TBL.key === key && S.route.mod === 'office' && OFC.tab === 'time') renderView();
}
// 2.979.0 (#5667): an undo / redo the server did: the list of quotations / invoices (an open document histRedraw reads itself) and the times to bill come again
histReloader('office-docs', () => { if (TBL.data) { TBL.key = ''; if (S.route.mod === 'office' && OFC.tab === 'time') renderView(); } if (Array.isArray(OFD.list) && !OFD.doc?.id) { OFD.list = null; ofdDraw(); } });
// 2.218.0 B (#2805): a number field in the editor selects its content on focus, so typing replaces the preset ("1" + 2 = "12")
document.addEventListener('focusin', e => { const f = e.target; if (f && f.matches && f.matches('.numin') && f.closest('.ofdeditor, .modal')) setTimeout(() => { if (document.activeElement === f) try { f.select(); } catch {} }, 0); });
document.addEventListener('change', e => {
  const t = /** @type {HTMLInputElement} */ (e.target);
  if (!t || (t.id !== 'tbl-from' && t.id !== 'tbl-to') || !t.value) return;
  TBL[t.id === 'tbl-from' ? 'from' : 'to'] = t.value;
  if (TBL.to < TBL.from) TBL.to = TBL.from;
  renderView();
});
// 2.354.0 D (#2837): the refunds paid back on a finalised credit note (same payment lines, same dialog)
function ofdRefundsHtml(d, adm) {
  const list = ofdPayList(d, adm) || `<p class="muted">${tr('No refund booked yet.')}</p>`;
  const sum = `<p class="ofdpaysum"><span>${trh('Paid back: {0}', ofdMoney(d.paid || 0, d))}</span><b>${trh('Refund open: {0}', ofdMoney(d.refund_open || 0, d))}</b></p>`;
  return list + sum + (adm && +d.refund_open > 0 ? `<button type="button" class="btn sm" data-ofd="pay">${ic('plus', 's')}<span>${tr('Record refund')}</span></button>` : '');
}
function ofdPaymentDialog(d) {
  const rf = d.kind === 'credit' || ofdNegRest(d);  // 2.354.0 D (#2837): a refund on a credit note; 2.545.0 (#4387): on a negative final invoice
  ofdDlg(rf ? tr('Record refund') : tr('Record payment'), ofdF('p-date', tr('Date'), dateIn('ofd-p-date', today(), {label: tr('Date'), clear: false}))
    + ofdF('p-amount', tr('Amount'), `<span class="lacts"><input id="ofd-p-amount" inputmode="decimal" class="numin" value="${esc(ofdNumIn(d.kind === 'credit' ? d.refund_open : rf ? d.overpaid : d.open))}" maxlength="14"><span class="muted">${ofcSym(d.currency)}</span></span>`)
    + ofdF('p-method', tr('Method'), ofcSel('ofd-p-method', 'transfer', OFD_PAY.map(([v, n]) => [v, tr(n)]))) + ofdF('p-note', tr('Note'), `<input id="ofd-p-note" maxlength="500">`),
    tr('Record'), async md => { const j = await ofdRefCall(`pay${d.id}`, ref => ofdSave('POST', `/api/office/docs/${d.id}/payments`, {date: $('#ofd-p-date', md).value, amount: ofcNum($('#ofd-p-amount', md).value), method: $('#ofd-p-method', md).value, note: $('#ofd-p-note', md).value, client_ref: ref})); if (!j) return false; toast(rf ? tr('Refund recorded') : j.state === 'paid' ? tr('Paid in full') : tr('Payment recorded')); });
}
// 2.912.0 (#5419): a reminder fee marked paid (or its day changed) asks the day the money came (default: the stored day, else
// today; not before the reminder, not in the future - the server checks it too); it decides the month and year the fee counts in
function ofdFeeDayDialog(d) {
  const t = today(), chg = d.fee_state === 'paid', v = chg && d.fee_paid_at ? d.fee_paid_at : t;
  ofdDlg(chg ? tr('Change date') : tr('Fee paid'), ofdF('fee-day', tr('Paid on'), dateIn('ofd-fee-day', v, {label: tr('Paid on'), clear: false, max: t, min: d.date || ''}),
    tr('The day the money came: the fee counts in its month and year.')),
    chg ? tr('Save') : tr('Mark as paid'), async md => { const j = await ofdSave('POST', `/api/office/docs/${d.id}/fee`, {state: 'paid', day: $('#ofd-fee-day', md).value}); if (!j) return false; savedTick('.ofdfeeinfo > span'); });
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
// 2.534.0 (#4339): the server refuses a mail whose terms are due but cannot go along (409 terms_missing, terms.ofc_agb_missing):
// the sender reads why and decides - pages that could not be joined go as a separate file (terms: true), a missing file
// goes without them (agb_ok_without); Cancel sends nothing. send(extra) = the request with extra body fields.
async function ofcSendTerms(send) {
  const j = await send({});
  if (!j?.terms_missing) return j;
  const join = j.terms_missing.reason === 'join';
  if (!await askConfirm(tr('Terms and conditions missing'), j.message, {ok: join ? tr('Send them as a separate file') : tr('Send without terms')})) return null;
  const k = await send(join ? {terms: true} : {[j.terms_missing.field || 'agb_ok_without']: true});
  return k?.terms_missing ? (toast(k.message), null) : k;
}
async function ofdSendDialog(d) {
  let ms = {smtp: true, datev_email: ''}, tm = null;
  // 2.855.0 (#5451): what could not be loaded is named once in the dialog (no toast each, no part silently missing)
  const miss = [], get = async (url, what) => { try { return await api('GET', url); } catch (x) { ofcErrHere(x); miss.push(what); return null; } };
  ms = await get('/api/office/mail-status', tr('E-mail settings')) || ms;
  const prof = typeof ofmProfile === 'function' ? await ofmProfile() : null;  // 2.439.0 (#3617): the person's signature, answer address, sender
  tm = await get(`/api/office/docs/${d.id}/terms`, tr('Terms and conditions'));  // 2.113.2 (#2253): the terms of the document's language
  // 2.433.0 (#3599): invoices / reminders to the e-mail for invoices with the contact persons for invoices in copy,
  // quotations to the default contact person with the e-mail for invoices in copy (server: fk_send_rcpts)
  let rc = {to: '', cc: []};
  if (d.client_id) rc = await get(`/api/office/docs/${d.id}/recipients`, tr('Recipients|mail')) || rc;
  const to = rc.to || '', cc = (rc.cc || []).join(', ');
  // 2.40.0 (#1368 point 10): plain words for people who do not run the server; without mail the button downloads the PDF
  const hint = (!ms.smtp ? `<p class="ofdwarn">${esc(tr('E-mail sending is not set up: download the PDF and send it yourself.') + (S.me?.is_admin ? ' ' + ofcNoMail() : ''))}</p>` : '')  // 2.855.0 (#5451): no variable name
    + (miss.length ? `<p class="ofdwarn ofdmiss" role="status">${esc(tr('Could not be loaded: {0}. Check the fields before sending.', miss.join(', ')))}</p>` : '');
  ofdDlg(tr('Send {0}', d.number || ''), hint + ofdF('s-to', tr('To|mail recipient'), `<input id="ofd-s-to" type="email" value="${esc(to)}" maxlength="200" ${ms.smtp ? '' : 'disabled'}>`)
    + ofdF('s-cc', tr('Copy to'), `<input id="ofd-s-cc" type="email" multiple value="${esc(cc)}" maxlength="1000" placeholder="${esc(tr('several: separated by commas'))}" ${ms.smtp ? '' : 'disabled'}>`)
    + ofdF('s-subject', tr('Subject'), `<input id="ofd-s-subject" value="${esc(`${ofdKindName(d.kind, true)} ${d.number || ''}`)}" maxlength="200" ${ms.smtp ? '' : 'disabled'}>`)
    + ofdF('s-text', tr('Text'), `<textarea id="ofd-s-text" rows="4" maxlength="8000" placeholder="${esc(tr('empty = the default text'))}" ${ms.smtp ? '' : 'disabled'}></textarea>`)
    + (typeof ofmSendHtml === 'function' ? ofmSendHtml(prof, true, !ms.smtp) : '')
    + (d.timesheet_ok ? `<div class="row"><label class="chkl" style="min-width:0"><input type="checkbox" id="ofd-s-ts"> ${tr('Attach the timesheet')}</label></div>` : '')  // 2.120.0 D (#2089)
    + (d.timesheet_ok ? `<div class="row"><label class="chkl" style="min-width:0"><input type="checkbox" id="ofd-s-tsnb"> ${tr('Show non-billable entries')}</label></div>` : '')  // 2.955.0 (#5648): off = the client's sheet without them
    + (d.kind !== 'reminder' && d.kind !== 'delivery' && ms.datev_on !== false ? `<div class="row"><label class="chkl" style="min-width:0"><input type="checkbox" id="ofd-s-datev" ${ms.datev_email && ms.datev_auto ? 'checked' : ''} ${ms.datev_email && ms.smtp ? '' : 'disabled'}> ${tr('Copy to the DATEV inbox')}${ms.datev_email ? ` <span class="muted">(${esc(ms.datev_email)})</span>` : ` <span class="muted">${tr('(no address in the settings)')}</span>`}</label></div>` : '')
    + (typeof agbSendRow === 'function' ? agbSendRow(tm, ms.smtp) : ''),
    ms.smtp ? tr('Send|mail') : tr('Download PDF'), async md => { if (!ms.smtp) { const a = document.createElement('a'); a.href = ofdPdfUrl(d.id); a.download = ''; document.body.appendChild(a); a.click(); a.remove(); return; } const tk = $('#ofd-s-terms', md); const j = await ofcSendTerms(x => ofdSave('POST', `/api/office/docs/${d.id}/send`, {to: $('#ofd-s-to', md).value.trim(), cc: $('#ofd-s-cc', md).value.trim(), subject: $('#ofd-s-subject', md).value, text: $('#ofd-s-text', md).value, datev: !!$('#ofd-s-datev', md)?.checked, timesheet: !!$('#ofd-s-ts', md)?.checked, nonbillable: !!$('#ofd-s-tsnb', md)?.checked, ...(tk ? {terms: tk.checked} : {}), ...(typeof ofmSendBody === 'function' ? ofmSendBody(md) : {}), ...x})); if (!j) return false; toast(j.datev_error || tr('Sent')); });  // 2.534.0 (#4339): terms only with the tick (a quotation: the server's default, its terms as pages or a separate file)  // 2.269.0 D (#3046): DATEV failed after the mail = a hint, the dialog closes
}
async function ofdReminderDialog() {
  let rows = [];
  try { rows = await docsAll(`/api/office/docs?kind=invoice&status=open${tri_on() ? '&trial=1' : ''}`, api); } catch (x) { ofcErr(x); return; }
  if (!rows.length) { toast(tr('No open invoices')); return; }
  const s = OFC.info?.settings || {};
  // 2.355.0 D (#2846): only invoices past their due date can be reminded of (the server answers 409); the others stay visible, greyed out
  const day0 = today(), early = r => !!r.due_date && r.due_date >= day0;
  const list = `<ul class="ofdpick" role="list">${rows.map(r => `<li><label class="chkl"><input type="checkbox" data-rid="${r.id}" data-cid="${r.client_id || ''}" ${r.state === 'overdue' && !early(r) ? 'checked' : ''} ${early(r) ? 'disabled' : ''}> <span class="ofcn"><b>${esc(r.number)}${r.recipient_name ? ` · ${esc(r.recipient_name)}` : ''}</b><small class="muted">${esc([r.due_date ? tr('due {0}', fmtDateLoc(r.due_date)) : '', early(r) ? tr('not yet overdue') : r.status_text, tr('open: {0}', r.open_text || r.open)].filter(Boolean).join(' · '))}</small></span></label></li>`).join('')}</ul>`;
  const md0 = ofdDlg(tr('Create payment reminder'), `<p class="muted ofchint">${tr('Select the overdue invoices of one client.')}</p>${list}<p class="ofdwarn" id="ofd-r-warn" hidden></p>` + ofdF('r-level', tr('Reminder level'), ofcSel('ofd-r-level', 1, [[1, tr('1 - payment reminder')], [2, tr('2 - reminder')], [3, tr('3 - final reminder')]]))
    + ofdF('r-fee', tr('Reminder fee'), `<input id="ofd-r-fee" inputmode="decimal" class="numin" value="${esc(ofdNumIn(0))}" maxlength="10">`) + ofdF('r-days', tr('Payment deadline'), `<span class="lacts"><input id="ofd-r-days" inputmode="numeric" class="numin" value="${esc(String(s.reminder_deadline_days ?? 10))}" maxlength="3"><span class="muted">${tr('days')}</span></span>`),
    tr('Create'), async md => {
      const picked = [...md.querySelectorAll('[data-rid]:checked')];
      if (!picked.length) throw new Error(tr('Select at least one invoice'));
      if (new Set(picked.map(x => x.dataset.cid)).size > 1) throw new Error(tr('One payment reminder covers the invoices of one client'));
      const j = await ofdRefCall('reminder', ref => rawFetch('POST', '/api/office/docs/reminder', {doc_ids: picked.map(x => +x.dataset.rid), level: +$('#ofd-r-level', md).value, fee: ofcNum($('#ofd-r-fee', md).value), deadline_days: ofcNum($('#ofd-r-days', md).value), client_ref: ref}));
      OFD.list = null; OFD.kind = 'reminder'; OFD.doc = j; go(ofd_href(j.id, j.kind));
    });
  // 2.40.0 (#1368 point 7): a hint, no block: a high fee (private clients: only the actual costs, usually 2-5 €); 2.355.0 D (#2846): invoices not yet due can no longer be picked
  const warn = () => {
    const w = $('#ofd-r-warn', md0); if (!w) return;
    const fee = ofcNum($('#ofd-r-fee', md0).value) || 0;
    const msg = [fee > 5 ? tr('Private clients may only be charged the actual costs of a payment reminder (usually 2 to 5 €).') : ''].filter(Boolean);
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
    $('#ofd-slist', md).innerHTML = rows.length ? [...groups].map(([k, ss]) => `<h4 class="ofcgrp">${esc(k)}</h4><ul class="ofclist" role="list">${ss.map(s => { const ct = d.contract?.rates?.[s.id]; const rate = ct ?? (s.unit === 'hour' && s.hourly_rate != null ? s.hourly_rate : s.daily_rate); return `<li><button type="button" class="ofcrow" data-sid="${s.id}"><span class="ofcn"><b>${esc(ofdSvcName(s, d))}</b><small class="muted">${esc([rate != null ? `${s.unit === 'percent' ? `${fmtNum(rate, 2)} %` : `${ofcMoney(rate)} / ${tr(OFC_UNITS.find(u => u[0] === s.unit)?.[1] || s.unit)}`}` : '', ct != null ? tr('contract rate') : '', ofcTax(s.tax)].filter(Boolean).join(' · '))}</small></span>${ic('plus', 's')}</button></li>`; }).join('')}</ul>`).join('')
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
  if (a === 'new-ls') return ofdCreate({kind: 'delivery', ...tri_flag()});  // 2.417.0 C (#3445)
  const make = async title => { try { const j = await ofdRefCall(`ls${d.id}`, ref => rawFetch('POST', `/api/office/docs/${d.id}/delivery`, {title, client_ref: ref})); OFD.list = null; OFD.kind = 'delivery'; OFD.doc = j; go(ofd_href(j.id, j.kind)); } catch (x) { ofcErr(x); } };
  menu($('[data-ofd="to-ls"]'), [{label: tr('Create delivery note'), icon: 'file', fn: () => make('delivery')}, {label: tr('Create proof of service'), icon: 'file', fn: () => make('service')}]);
}
function ls_moreItems(d, inList) {
  return !inList && d.timesheet_ok ? [{label: tr('Timesheet (PDF)'), icon: 'clock', fn: () => ls_sheetDlg(d)}] : [];
}
// 2.955.0 (#5648): the timesheet for the client lists the billable entries; the switch adds the non-billable ones (marked)
function ls_sheetDlg(d) {
  ofdDlg(tr('Timesheet (PDF)'), `<div class="row"><label class="chkl" style="min-width:0"><input type="checkbox" id="ofd-ts-nb"> ${tr('Show non-billable entries')}</label></div>`,
    tr('Open'), md => { window.open(ofc_spUrl(`/api/office/docs/${d.id}/timesheet.pdf?inline=1${$('#ofd-ts-nb', md).checked ? '&nonbillable=1' : ''}`), '_blank', 'noopener'); });
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
async function otb_restore(tid, after, core, undo) {  // 2.905.0 (#5414): core = the kind of a row in the core's trash (tid = its id); 2.1005.0 (#5415): undo = the toast's
  let j; try { j = await api('POST', core ? `/api/office/trash/core/${core}/${tid}/restore${undo ? '?undo=1' : ''}` : `/api/office/trash/${tid}/restore`); } catch (x) { ofcErr(x); return; }
  toast(j.note || tr('Restored'));  // 2.552.0 (#4561 B19): a draft whose client is gone for good comes back without one
  if (j.kind === 'trip' || j.kind === 'trip_item') { if (typeof RK !== 'undefined') RK.data = null; }  // 2.530.0 C (#4315)
  if (['fixed_cost', 'cf_start', 'cf_adjust'].includes(j.kind)) { if (typeof RKF !== 'undefined') RKF.data = null; if (typeof ABO !== 'undefined') ABO.data = null; if (j.kind === 'cf_start' && typeof CFS !== 'undefined') CFS.oid = null; }  /* cfs_settingsHtml loads it again */
  if (j.kind === 'cc_line' && typeof ccStale === 'function') ccStale();  // 2.552.0 (#4561 B21)
  if (j.kind === 'meal' && typeof BW !== 'undefined') BW.data = null;  // 2.993.0 (#5413): a meal from the core's trash
  if (j.kind === 'contract_file' && typeof ofcReload === 'function') ofcReload('contracts');  // its paper clip count
  if (j.kind === 'part' && j.doc_id) { OFD.list = null; go(`office/offers/${j.doc_id}`); if (after) after(); return; }  // 2.747.0 (#5246): back in its quotation
  if (j.kind === 'rgroup' || j.kind === 'signoff') { if (typeof ORR !== 'undefined') ORR.data = null; if (after) after(); return; }  // 2.747.0 (#5246)
  if (j.kind === 'doc') { OFD.list = null; go(`office/offers/${j.id}`); }  /* a quotation's address; an invoice moves on to its area (ofdLoadDoc) */ else if (typeof ofcReload === 'function') ofcReload(j.kind);
  if (after) after();
}
async function otb_open() {
  let d; try { d = await api('GET', '/api/office/trash'); } catch (x) { ofcErr(x); return; }
  const row = x => `<li data-id="${x.id}"${x.core ? ` data-core="${esc(x.core)}"` : ''}><span class="an">${esc(x.kind === 'doc' ? ofdKindName(x.sub, true) : x.kind === 'trip' ? tr('Trip') : x.kind === 'trip_item' ? tr('Receipt') : x.kind === 'cc_line' ? tr('Credit card position') : ({part: tr('Part'), rgroup: tr('Rights group'), signoff: tr('Video sign-off'), fixed_cost: tr('Fixed cost'), cf_start: tr('Starting balance'), cf_adjust: tr('Correction'), letter_link: tr('Letter'), meal: tr('Entertainment receipt'), contract_file: tr('Contract (PDF)')})[x.kind] || tr('Master data'))}${x.label ? ' · ' + esc(x.label) : ''}</span> <span class="muted">${esc(fmtDayAbs(x.deleted_at.slice(0, 10)))}</span>
    <button type="button" class="linkbtn" data-m="restore">${esc(tr('Restore'))}</button> <button type="button" class="linkbtn" data-m="purge">${esc(tr('Delete permanently'))}</button></li>`;
  const md = modal(`<h3>${esc(tr('Trash'))}</h3>${d.items.length ? `<ul class="atrash otblist">${d.items.map(row).join('')}</ul>` : `<p class="muted">${esc(tr('The trash is empty'))}</p>`}
    <p class="muted">${esc(trashNote(tr('Items in the trash are deleted permanently after {0} days.', d.days)))}</p><div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Close')}</button></div>`);
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    const li = b.closest('li'), id = +li?.dataset.id; if (!id) return;
    if (b.dataset.m === 'restore') { md.remove(); await otb_restore(id, null, li.dataset.core); return; }
    if (b.dataset.m === 'purge') {
      if (!await askConfirm(tr('Delete “{0}” permanently?', li.querySelector('.an')?.textContent || ''), tr('This cannot be undone.'), {ok: tr('Delete permanently'), danger: true})) return;
      try { await api('DELETE', li.dataset.core ? `/api/office/trash/core/${li.dataset.core}/${id}` : `/api/office/trash/${id}`); li.remove(); } catch (x) { ofcErr(x); }
    }
  });
}
