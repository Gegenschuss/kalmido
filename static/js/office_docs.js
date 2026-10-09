// Office & finance (2.36.1, #1021), part C: quotations -- the tab "Quotations" of the office view (office.js calls
// ofdOffersTab(el)) with the list and the editor (#office/offers/<id>). The server computes the sums (kalmido/office/calc.py)
// on every change and returns them; the editor shows exactly those figures in the document's language and currency.
const OFD = {list: null, loading: false, q: '', status: '', doc: null, docId: null, docLoading: false, seq: 0, saving: 0, err: '', open: {head: true, rights: true, texts: false, fields: false}};
const OFD_STATUS = [['draft', N_('Draft')], ['sent', N_('Sent')], ['accepted', N_('Accepted')], ['declined', N_('Declined')]];
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
const ofdSvcName = (s, d) => (ofdLang(d) === 'en' ? s.name_en || s.name_de : s.name_de || s.name_en) || '';

// ---- loading
async function ofdLoadList(force) {
  if (OFD.loading) return;
  if (OFD.list && !force) return;
  OFD.loading = true;
  try { const j = await api('GET', `/api/office/docs?kind=offer${OFD.status ? '&status=' + OFD.status : ''}`); OFD.list = j.docs || []; OFD.err = ''; }
  catch (x) { OFD.list = []; OFD.err = x.message || tr('unknown'); }
  OFD.loading = false;
  ofdDraw();
}
async function ofdLoadDoc(id, force) {
  if (OFD.docLoading) return;
  if (OFD.doc && OFD.doc.id === id && !force) return;
  OFD.docLoading = true; OFD.docId = id;
  try { OFD.doc = await api('GET', `/api/office/docs/${id}`); OFD.err = ''; }
  catch (x) { OFD.doc = null; OFD.err = x.message || tr('unknown'); }
  OFD.docLoading = false;
  ofdDraw();
}
function ofdDraw() {
  if (S.route.mod !== 'office' || ofcTab() !== 'offers') return;
  const el = $('.office .ofcbody'); if (el) ofdOffersTab(el);
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
  keepFocus(el, () => setHtml(el, id ? ofdEditorHtml() : ofdListHtml()));
  if (!el._ofd) { el._ofd = true; el.addEventListener('click', ofdClick); el.addEventListener('change', ofdChange); el.addEventListener('input', ofdInput); el.addEventListener('keydown', ofdKey); }
}

// ---- the list
function ofdListHtml() {
  const rows = OFD.list;
  const q = OFD.q.trim().toLowerCase();
  const bar = `<div class="ofcbar ofdbar"><div class="ctsearch">${ic('search', 's')}<input id="ofd-q" type="search" value="${esc(OFD.q)}" placeholder="${esc(tr('Search'))}" aria-label="${esc(tr('Search quotations'))}" autocomplete="off" enterkeyhint="search"></div>
    <select id="ofd-status" aria-label="${esc(tr('Status'))}"><option value="">${tr('All|status')}</option>${OFD_STATUS.map(([v, n]) => `<option value="${v}" ${OFD.status === v ? 'selected' : ''}>${tr(n)}</option>`).join('')}</select><span class="spacer"></span>
    <button class="btn sm pri" data-ofd="new">${ic('plus', 's')}<span>${tr('New quotation')}</span></button></div>`;
  if (!rows) return bar + `<p class="muted lempty">${tr('Loading…')}</p>`;
  if (OFD.err && !rows.length) return bar + `<div class="empty">${esc(OFD.err)}</div>`;
  const hit = r => !q || [r.number, r.recipient_name, r.project_title, r.project_ref].some(v => (v || '').toLowerCase().includes(q));
  const list = rows.filter(hit);
  if (!list.length) return bar + `<div class="empty">${ic('receipt')}<span>${q || OFD.status ? tr('Nothing matches.') : tr('No quotations yet. The first one takes your services, rates and text blocks.')}</span>${!q && !OFD.status ? `<button class="btn pri" data-ofd="new">${ic('plus', 's')} ${tr('New quotation')}</button>` : ''}</div>`;
  return bar + `<ul class="ofclist ofdlist" role="list">${list.map(r => `<li><button type="button" class="ofcrow ofdrow st-${r.status}" data-ofd="open" data-id="${r.id}">
    <span class="ofcn"><b>${esc(r.number || tr('(no number)'))}${r.recipient_name ? ` · ${esc(r.recipient_name)}` : ''}</b><small class="muted">${esc([r.project_title, r.date ? fmtDateLoc(r.date) : ''].filter(Boolean).join(' · '))}</small></span>
    <span class="ofdsum"><b>${esc(r.net_text)}</b><small class="rotag st-${r.status}">${esc(r.status_text)}</small></span>${ic('chev', 's')}</button></li>`).join('')}</ul>`;
}

// ---- the editor
const ofdSec = (key, title, body, extra = '') => `<details class="ofdsec" ${OFD.open[key] ? 'open' : ''} data-sec="${key}"><summary><h3>${esc(title)}</h3>${extra}</summary><div class="ofdsecb">${body}</div></details>`;
const ofdF = (k, label, field, hint) => `<div class="row"><label for="ofd-${k}">${esc(label)}</label>${field}${hint ? `<span class="muted ofchint">${esc(hint)}</span>` : ''}</div>`;
const ofdSel = (k, cur, opts, empty) => `<select id="ofd-${k}" data-f="${k}">${empty != null ? `<option value="">${esc(empty)}</option>` : ''}${opts.map(([v, n]) => `<option value="${esc(v)}" ${String(v) === String(cur ?? '') ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select>`;
const ofdIn = (k, v, o = {}) => `<input id="ofd-${k}" data-f="${k}" value="${esc(v ?? '')}" maxlength="${o.max || 200}" ${o.num ? 'inputmode="decimal" class="numin"' : ''} ${o.ph ? `placeholder="${esc(o.ph)}"` : ''} ${o.ro ? 'readonly' : ''}>`;
const ofdTa = (k, v, rows = 3, o = {}) => `<textarea id="ofd-${k}" data-f="${k}" rows="${rows}" maxlength="${o.max || 8000}" ${o.ph ? `placeholder="${esc(o.ph)}"` : ''}>${esc(v ?? '')}</textarea>`;
function ofdEditorHtml() {
  const d = OFD.doc && OFD.doc.id === S.route.id ? OFD.doc : null;
  const back = `<button type="button" class="btn sm ofdback" data-ofd="back">${ic('left', 's')}<span>${tr('Quotations')}</span></button>`;
  if (!d) return `<div class="ofdhead">${back}</div>` + (OFD.err ? `<div class="empty">${ic('receipt')}<span>${esc(OFD.err)}</span></div>` : `<p class="muted lempty">${tr('Loading…')}</p>`);
  const adm = ofcAdmin(), lg = ofdLang(d), t = d.totals || {};
  const texts = kind => ofcRows('texts').filter(x => x.kind === kind && !x.archived);
  const txtOpt = kind => texts(kind).map(x => [x.id, (x.key ? x.key + ': ' : '') + ((lg === 'en' ? x.text_en || x.text_de : x.text_de || x.text_en) || '').slice(0, 70)]);
  const contracts = ofcRows('contracts').filter(x => !x.archived || x.id === d.contract_id).map(x => [x.id, x.name]);
  const clients = typeof clientsOn === 'function' && clientsOn() ? (S.clients || []).filter(c => (!c.archived && c.org_id === OFC.info?.org_id) || c.id === d.client_id).map(c => [c.id, c.name]) : [];
  const head = `<div class="ofdhead">${back}<span class="ofdnum"><b>${esc(d.number || tr('(no number)'))}</b>${d.number ? '' : `<button type="button" class="btn sm" data-ofd="number">${tr('Assign number')}</button>`}</span>
    <select id="ofd-status" data-f="status" aria-label="${esc(tr('Status'))}" class="ofdstat st-${d.status}">${OFD_STATUS.map(([v, n]) => `<option value="${v}" ${d.status === v ? 'selected' : ''}>${tr(n)}</option>`).join('')}</select><span class="spacer"></span>
    <span class="ofdsave muted" aria-live="polite">${OFD.saving ? tr('Saving…') : OFD.err ? esc(OFD.err) : ''}</span>
    <a class="btn sm" href="/api/office/docs/${d.id}/pdf" target="_blank" rel="noopener" data-ofd="pdf">${ic('file', 's')}<span>PDF</span></a>
    <button type="button" class="btn sm" data-ofd="more" aria-haspopup="menu" aria-label="${esc(tr('More'))}">${ic('dots', 's')}</button></div>`;
  const headSec = ofdSec('head', tr('Head'), `
    <div class="ofdgrid">
    ${ofdF('lang', tr('Document language'), ofdSel('lang', d.lang, [['de', 'Deutsch'], ['en', 'English']]))}
    ${ofdF('currency', tr('Currency'), ofdSel('currency', d.currency, [['EUR', 'EUR'], ['USD', 'USD']]))}
    ${d.currency === 'USD' ? ofdF('fx_rate', tr('Exchange rate'), ofdIn('fx_rate', ofdNumIn(d.fx_rate), {num: true, max: 12}), tr('1 € in USD; rates stay in EUR and are converted')) : ''}
    ${ofdF('vat_mode', tr('VAT'), ofdSel('vat_mode', d.vat_mode, [['vat', tr('with VAT')], ['novat', tr('without VAT (reverse charge / abroad)')]]))}
    ${ofdF('contract_id', tr('Framework contract'), ofdSel('contract_id', d.contract_id, contracts, tr('none|contract')), d.contract ? tr('presets raw data, rights and closing; special rates apply to new positions') : '')}
    ${clients.length ? ofdF('client_id', tr('Client'), ofdSel('client_id', d.client_id, clients, tr('free recipient'))) : ''}
    ${ofdF('recipient_name', tr('Recipient'), ofdIn('recipient_name', d.recipient?.name, {ph: tr('Company or name')}))}
    ${ofdF('recipient_lines', tr('Address lines'), ofdTa('recipient_lines', (d.recipient?.lines || []).join('\n'), 3, {ph: tr('one line each: name, attention, street, place')}))}
    ${ofdF('project_title', tr('Project title'), ofdIn('project_title', d.project_title))}
    ${ofdF('project_ref', tr('Ref. / PO no.'), ofdIn('project_ref', d.project_ref, {max: 80}))}
    ${ofdF('date', tr('Date'), dateIn('ofd-date', d.date, {label: tr('Date'), clear: false, attrs: 'data-f="date"'}))}
    ${ofdF('valid_until', tr('Valid until'), dateIn('ofd-valid_until', d.valid_until, {label: tr('Valid until'), attrs: 'data-f="valid_until"'}))}
    </div>`);
  const items = ofdItemsHtml(d, adm);
  const auto = ofdAutoHtml(d, t);
  const rights = d.rights || {};
  const dim = (k, kind, label) => `<div class="row ofdrt"><label for="ofd-r-${k}">${esc(label)}</label><span class="lacts ofdrtf">${ofdSel('r-' + k, rights[k]?.id, txtOpt(kind), tr('free text'))}${ofdIn('r-' + k + '-t', rights[k]?.text, {max: 1000, ph: tr('Text in the document')})}</span></div>`;
  const rightsSec = ofdSec('rights', tr('Transfer of rights'), dim('time', 'rights_time', tr('Duration')) + dim('territory', 'rights_territory', tr('Territory')) + dim('media', 'rights_media', tr('Media'))
    + ofdF('r-exceptions', tr('Exceptions'), ofdIn('r-exceptions', rights.exceptions, {max: 2000, ph: tr('e.g. music, stock material')}))
    + `<div class="row"><label class="chkl" style="min-width:0"><input type="checkbox" id="ofd-r-exclusive" data-f="r-exclusive" ${rights.exclusive ? 'checked' : ''}> ${tr('Exclusive')}</label></div>`
    + ofdF('r-note', tr('Note'), ofdTa('r-note', rights.note, 2, {max: 2000})));
  const textsSec = ofdSec('texts', tr('Introduction and closing'), `
    <div class="row"><label for="ofd-intro">${tr('Introduction')}</label><span class="lacts ofdtxt">${ofdSel('intro_pick', '', txtOpt('intro'), tr('from a text block…'))}</span></div>${ofdTa('intro', d.intro, 3)}
    <div class="row"><label for="ofd-closing">${tr('Closing')}</label><span class="lacts ofdtxt">${ofdSel('closing_pick', '', txtOpt('closing'), tr('from a text block…'))}</span></div>${ofdTa('closing', d.closing, 3)}`);
  const fields = d.fields || [];
  const fieldsSec = ofdSec('fields', tr('Own fields'), `<div id="ofd-fields">${fields.map((f, i) => `<div class="row ofdfld"><input data-fld="${i}" data-k="name" value="${esc(f.name)}" maxlength="80" placeholder="${esc(tr('Name'))}" aria-label="${esc(tr('Name'))}"><input data-fld="${i}" data-k="value" value="${esc(f.value)}" maxlength="500" placeholder="${esc(tr('Value'))}" aria-label="${esc(tr('Value'))}"><button type="button" class="ib" data-ofd="fld-del" data-i="${i}" aria-label="${esc(tr('Remove'))}">${ic('x', 's')}</button></div>`).join('')}</div><button type="button" class="btn sm" data-ofd="fld-add">${ic('plus', 's')} ${tr('Add field')}</button>`,
    fields.length ? `<span class="c muted">${fields.length}</span>` : '');
  const totals = ofdTotalsHtml(d, t, adm);
  return `${head}<div class="ofdeditor">${headSec}<section class="ofdsec open"><h3>${tr('Positions')}</h3>${items}${auto}${totals}</section>${rightsSec}${textsSec}${fieldsSec}</div>`;
}
function ofdItemsHtml(d, adm) {
  const its = d.items || [], lg = ofdLang(d);
  const taxes = OFC_TAXES.map(([v, n]) => [v, ofcTax(v)]);
  const rows = its.map((it, i) => {
    const mv = `<span class="ofdmv"><button type="button" class="ib" data-ofd="it-up" data-i="${i}" ${i === 0 ? 'disabled' : ''} aria-label="${esc(tr('Move up'))}">${ic('up', 's')}</button><button type="button" class="ib" data-ofd="it-down" data-i="${i}" ${i === its.length - 1 ? 'disabled' : ''} aria-label="${esc(tr('Move down'))}">${ic('down', 's')}</button><button type="button" class="ib" data-ofd="it-del" data-i="${i}" aria-label="${esc(tr('Remove'))}">${ic('x', 's')}</button></span>`;
    if (it.kind === 'heading') return `<li class="ofdit ofdhd"><span class="ofdpos muted">${ic('list', 's')}</span><input data-i="${i}" data-k="title" value="${esc(it.title)}" maxlength="500" placeholder="${esc(tr('Heading (category)'))}" aria-label="${esc(tr('Heading'))}">${mv}</li>`;
    if (it.kind === 'text') return `<li class="ofdit ofdtx"><span class="ofdpos muted">${ic('note', 's')}</span><textarea data-i="${i}" data-k="detail" rows="2" maxlength="4000" placeholder="${esc(tr('Text block'))}" aria-label="${esc(tr('Text block'))}">${esc(it.detail)}</textarea>${mv}</li>`;
    const line = (d.totals?.lines || []).find(l => l.kind === 'item' && l.id === it.id);
    return `<li class="ofdit"><span class="ofdpos">${line?.pos || ''}</span>
      <div class="ofditb"><input class="ofdtt" data-i="${i}" data-k="title" value="${esc(it.title)}" maxlength="500" placeholder="${esc(tr('Service'))}" aria-label="${esc(tr('Service'))}">
      <input class="ofddt" data-i="${i}" data-k="detail" value="${esc(it.detail)}" maxlength="4000" placeholder="${esc(tr('Detail (optional)'))}" aria-label="${esc(tr('Detail'))}">
      <span class="ofdnums"><input data-i="${i}" data-k="qty" inputmode="decimal" class="numin" value="${esc(ofdNumIn(it.qty))}" aria-label="${esc(tr('Quantity'))}">
      <select data-i="${i}" data-k="unit" aria-label="${esc(tr('Unit'))}">${OFC_UNITS.map(([v, n]) => `<option value="${v}" ${it.unit === v ? 'selected' : ''}>${tr(n)}</option>`).join('')}</select>
      <span class="muted">×</span><input data-i="${i}" data-k="rate" inputmode="decimal" class="numin ofdrate" value="${esc(ofdNumIn(it.rate))}" aria-label="${esc(tr('Rate (EUR)'))}"><span class="muted">€</span>
      <select data-i="${i}" data-k="tax" aria-label="${esc(tr('VAT'))}">${taxes.map(([v, n]) => `<option value="${v}" ${it.tax === v ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select>
      <b class="ofdlt">${line ? esc(line.total_text || ofdMoney(line.total, d)) : ''}</b></span>
      <span class="ofdflags"><label class="chkl"><input type="checkbox" data-i="${i}" data-k="raw_fee" ${it.raw_fee ? 'checked' : ''}> ${tr('raw data')}</label><label class="chkl"><input type="checkbox" data-i="${i}" data-k="producing" ${it.producing ? 'checked' : ''}> ${tr('producing')}</label><label class="chkl"><input type="checkbox" data-i="${i}" data-k="discountable" ${it.discountable ? 'checked' : ''}> ${tr('discount')}</label>
      ${adm ? `<label class="chkl ofdcost">${tr('Cost')} <input data-i="${i}" data-k="cost" inputmode="decimal" class="numin" value="${esc(ofdNumIn(it.cost))}" aria-label="${esc(tr('External cost per unit (internal)'))}"></label>` : ''}</span></div>${mv}</li>`;
  }).join('');
  return `<ul class="ofdits" role="list">${rows}</ul><div class="ofdadd"><button type="button" class="btn sm pri" data-ofd="it-svc">${ic('plus', 's')}<span>${tr('Add service')}</span></button><button type="button" class="btn sm" data-ofd="it-head">${ic('list', 's')}<span>${tr('Heading')}</span></button><button type="button" class="btn sm" data-ofd="it-text">${ic('note', 's')}<span>${tr('Text block')}</span></button></div>`;
}
function ofdAutoHtml(d, t) {
  const lines = (t.lines || []).filter(l => ['producing', 'raw', 'discount'].includes(l.kind));
  const prod = lines.find(l => l.kind === 'producing'), raw = lines.find(l => l.kind === 'raw'), disc = lines.find(l => l.kind === 'discount');
  const rowL = (title, detail, total) => `<li class="ofdauto"><span class="ofdpos muted">${ic('calc', 's')}</span><span class="ofcn"><b>${esc(title)}</b>${detail ? `<small class="muted">${esc(detail)}</small>` : ''}</span><b class="ofdlt">${esc(total)}</b></li>`;
  return `<ul class="ofdits ofdautos" role="list">
    ${prod ? rowL(prod.title, prod.detail, prod.total_text || ofdMoney(prod.total, d)) : rowL(t.labels?.producing || 'Producing', tr('no position counts towards producing'), '')}
    ${raw ? rowL(raw.title, raw.detail, raw.total_text || ofdMoney(raw.total, d)) : ''}
    ${disc ? rowL(disc.title, disc.detail, disc.total_text || ofdMoney(disc.total, d)) : ''}</ul>
    <div class="ofdgrid ofdrules">
    ${ofdF('raw_mode', tr('Raw data'), ofdSel('raw_mode', d.raw_mode, OFD_RAW.map(([v, n]) => [v, tr(n)])))}
    ${ofdF('raw_factor', tr('Raw data factor'), ofdIn('raw_factor', ofdNumIn(d.raw_factor), {num: true, max: 10}), tr('share of the positions with raw data'))}
    ${ofdF('prod_quotient', tr('Producing quotient'), ofdIn('prod_quotient', ofdNumIn(d.prod_quotient), {num: true, max: 10}), tr('production days per producing day'))}
    ${ofdF('producing_rate', tr('Producing rate'), ofdIn('producing_rate', ofdNumIn(d.producing_rate), {num: true, max: 12}), '€')}
    ${ofdF('discount_pct', tr('Discount'), ofdIn('discount_pct', ofdNumIn(d.discount_pct), {num: true, max: 8}), '%')}
    </div>`;
}
function ofdTotalsHtml(d, t, adm) {
  const L = t.labels || {};
  const rows = [[L.net || tr('Net total'), ofdMoney(t.net || 0, d), 'net']];
  if (t.net_incl_raw != null) rows.push([L.net_incl_raw, ofdMoney(t.net_incl_raw, d), 'incl']);
  if (t.net_excl_raw != null) rows.push([L.net_excl_raw, ofdMoney(t.net_excl_raw, d), 'excl']);
  for (const x of t.tax_lines || []) rows.push([x.label, ofdMoney(x.amount, d), 'tax']);
  if (d.vat_mode !== 'novat') rows.push([L.gross || tr('Gross total'), ofdMoney(t.gross || 0, d), 'gross']);
  return `<div class="ofdtotals" id="ofd-totals"><dl>${rows.map(([k, v, c]) => `<div class="ofdtr tr-${c}"><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('')}</dl>
    <p class="muted ofdnote">${esc(t.vat_note || '')}${t.fx_note ? ` · ${esc(t.fx_note)}` : ''}</p>
    ${adm && t.costs != null ? `<p class="muted ofdint">${ic('eye', 's')} ${tr('Internal: external costs {0}, surplus {1}', ofdMoney(t.costs, d), ofdMoney(t.margin, d))}</p>` : ''}</div>`;
}

// ---- saving
async function ofdSave(method, url, body) {
  OFD.saving++; ofdSaveHint();
  try { const j = await rawFetch(method, url, body); if (OFD.doc && j && j.id === OFD.doc.id) OFD.doc = j.items ? j : {...OFD.doc, ...j}; /* the status answer has no positions */ OFD.err = ''; return j; }
  catch (x) { OFD.err = x.message || tr('unknown'); toast(OFD.err); return null; }
  finally { OFD.saving--; ofdDraw(); OFD.list = null; }
}
function ofdSaveHint() { const s = $('.ofdsave'); if (s) s.textContent = OFD.saving ? tr('Saving…') : ''; }
const ofdPatch = body => ofdSave('PATCH', `/api/office/docs/${OFD.doc.id}`, body);
function ofdItemsBody() {
  return (OFD.doc.items || []).map(it => ({id: it.id, kind: it.kind, service_id: it.service_id, title: it.title, detail: it.detail, qty: it.qty, unit: it.unit, rate: it.rate, tax: it.tax,
    raw_fee: it.raw_fee, producing: it.producing, intext: it.intext, cost: it.cost, discountable: it.discountable}));
}
const ofdPutItems = () => ofdSave('PUT', `/api/office/docs/${OFD.doc.id}/items`, {items: ofdItemsBody()});
function ofdRightsBody() {
  const r = OFD.doc.rights || {}, g = id => $('#ofd-' + id);
  const dim = k => ({id: g('r-' + k)?.value ? +g('r-' + k).value : null, text: g('r-' + k + '-t')?.value ?? r[k]?.text ?? ''});
  return {time: dim('time'), territory: dim('territory'), media: dim('media'), exceptions: g('r-exceptions')?.value ?? r.exceptions, exclusive: g('r-exclusive')?.checked ? 1 : 0, note: g('r-note')?.value ?? r.note};
}

// ---- events (delegated on the tab's body)
function ofdInput(e) {
  const t = e.target;
  if (t.id === 'ofd-q') { OFD.q = t.value; const el = t.closest('.ofcbody'); if (el) keepFocus(el, () => setHtml(el, ofdListHtml())); }
}
function ofdKey(e) { if (e.key === 'Enter' && e.target.id === 'ofd-q') e.preventDefault(); }
async function ofdChange(e) {
  const t = e.target;
  if (t.id === 'ofd-status' && !OFD.doc) { OFD.status = t.value; OFD.list = null; ofdLoadList(true); return; }
  if (!OFD.doc) return;
  const d = OFD.doc;
  if (t.dataset.i != null && t.dataset.k) {  // a position
    const it = d.items[+t.dataset.i]; if (!it) return;
    const k = t.dataset.k;
    if (t.type === 'checkbox') it[k] = t.checked ? 1 : 0;
    else if (['qty', 'rate', 'cost'].includes(k)) { const v = ofcNum(t.value); it[k] = v == null ? (k === 'qty' ? 1 : 0) : v; }
    else it[k] = t.value;
    await ofdPutItems(); return;
  }
  if (t.dataset.fld != null) {  // own fields
    const f = d.fields[+t.dataset.fld]; if (!f) return;
    f[t.dataset.k] = t.value; await ofdPatch({fields: d.fields}); return;
  }
  const f = t.dataset.f; if (!f) return;
  if (f === 'status') { const j = await ofdSave('POST', `/api/office/docs/${d.id}/status`, {status: t.value}); if (j) { d.status = j.status; d.status_text = j.status_text; d.sent_at = j.sent_at; ofdDraw(); } return; }
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
  if (['fx_rate', 'raw_factor', 'prod_quotient', 'producing_rate', 'discount_pct'].includes(f)) { const v = ofcNum(t.value); await ofdPatch({[f]: v}); return; }
  await ofdPatch({[f]: t.value});
}
async function ofdClick(e) {
  const b = e.target.closest('[data-ofd]'); if (!b) return;
  const a = b.dataset.ofd, d = OFD.doc;
  if (a === 'pdf') return;  // the link itself
  e.preventDefault();
  if (a === 'new') {
    try { const j = await rawFetch('POST', '/api/office/docs', {}); OFD.doc = j; OFD.list = null; go(`office/offers/${j.id}`); } catch (x) { toast(x.message || tr('unknown')); }
    return;
  }
  if (a === 'open') { go(`office/offers/${b.dataset.id}`); return; }
  if (a === 'back') { OFD.doc = null; OFD.list = null; go('office/offers'); return; }
  if (!d) return;
  if (a === 'number') { const j = await ofdSave('POST', `/api/office/docs/${d.id}/number`, {}); if (j) { d.number = j.number; ofdDraw(); } return; }
  if (a === 'more') {
    menu(b, [
      {label: tr('Duplicate'), icon: 'copy', fn: async () => { try { const j = await rawFetch('POST', `/api/office/docs/${d.id}/duplicate`); OFD.list = null; OFD.doc = j; toast(tr('Copied as {0}', j.number)); go(`office/offers/${j.id}`); } catch (x) { toast(x.message || tr('unknown')); } }},
      {label: tr('Preview (print model)'), icon: 'eye', fn: () => window.open(`/api/office/docs/${d.id}/render`, '_blank', 'noopener')},
      d.can_delete ? '-' : null,
      d.can_delete ? {label: tr('Delete'), icon: 'trash', cls: 'danger', fn: async () => {
        if (!await askConfirm(tr('Delete the quotation {0}?', d.number || ''), tr('Its number stays used.'), {ok: tr('Delete'), danger: true})) return;
        try { await api('DELETE', `/api/office/docs/${d.id}`); OFD.doc = null; OFD.list = null; toast(tr('Deleted')); go('office/offers'); } catch (x) { toast(x.message || tr('unknown')); }
      }} : null]);
    return;
  }
  if (a === 'it-svc') { ofdServicePicker(); return; }
  if (a === 'it-head') { d.items.push({kind: 'heading', title: '', detail: '', qty: 1, unit: 'day', rate: 0, tax: 'standard', raw_fee: 0, producing: 0, intext: 'intern', cost: 0, discountable: 1}); await ofdPutItems(); $(`.ofdits [data-i="${d.items.length - 1}"][data-k="title"]`)?.focus(); return; }
  if (a === 'it-text') {
    const blocks = ofcRows('texts').filter(x => x.kind === 'block' && !x.archived);
    const add = async text => { d.items.push({kind: 'text', title: '', detail: text, qty: 1, unit: 'day', rate: 0, tax: 'standard', raw_fee: 0, producing: 0, intext: 'intern', cost: 0, discountable: 1}); await ofdPutItems(); if (!text) $(`.ofdits [data-i="${d.items.length - 1}"][data-k="detail"]`)?.focus(); };
    if (!blocks.length) { await add(''); return; }
    menu(b, [{label: tr('Free text'), icon: 'edit', fn: () => add('')}, '-', ...blocks.map(x => ({label: x.key || (x.text_de || x.text_en).slice(0, 50), fn: () => add(ofcText(x.id, ofdLang(d)))}))]);
    return;
  }
  if (a === 'it-del') { d.items.splice(+b.dataset.i, 1); await ofdPutItems(); return; }
  if (a === 'it-up' || a === 'it-down') { const i = +b.dataset.i, j = a === 'it-up' ? i - 1 : i + 1; if (j < 0 || j >= d.items.length) return; [d.items[i], d.items[j]] = [d.items[j], d.items[i]]; await ofdPutItems(); setTimeout(() => $(`.ofdits [data-ofd="${a}"][data-i="${j}"]`)?.focus(), 0); return; }
  if (a === 'fld-add') { d.fields = [...(d.fields || []), {name: '', value: ''}]; OFD.open.fields = true; ofdDraw(); setTimeout(() => $(`#ofd-fields [data-fld="${d.fields.length - 1}"][data-k="name"]`)?.focus(), 0); return; }
  if (a === 'fld-del') { d.fields.splice(+b.dataset.i, 1); await ofdPatch({fields: d.fields}); return; }
}
// the service picker: search the catalogue, tap = a new position with the service's name (document language), rate and flags
function ofdServicePicker() {
  const d = OFD.doc, lg = ofdLang(d);
  const md = modal(`<h3>${tr('Add service')}</h3><div class="ctsearch">${ic('search', 's')}<input id="ofd-sq" type="search" placeholder="${esc(tr('Search'))}" aria-label="${esc(tr('Search services'))}" autocomplete="off"></div><div id="ofd-slist" class="ofdslist"></div>
    <div class="foot"><button type="button" class="btn" data-m="free">${tr('Free position')}</button><span class="spacer"></span><button type="button" class="btn" data-m="close">${tr('Close')}</button></div>`);
  md.classList.add('ofdpick');
  const draw = () => {
    const q = ($('#ofd-sq', md)?.value || '').trim().toLowerCase();
    const rows = ofcRows('services').filter(s => !s.archived && (!q || [s.name_de, s.name_en, s.category].some(v => (v || '').toLowerCase().includes(q))));
    const groups = new Map(); for (const s of rows) { const k = s.category || tr('No category'); if (!groups.has(k)) groups.set(k, []); groups.get(k).push(s); }
    $('#ofd-slist', md).innerHTML = rows.length ? [...groups].map(([k, ss]) => `<h4 class="ofcgrp">${esc(k)}</h4><ul class="ofclist" role="list">${ss.map(s => { const ct = d.contract?.rates?.[s.id]; const rate = ct ?? (s.unit === 'hour' && s.hourly_rate != null ? s.hourly_rate : s.daily_rate); return `<li><button type="button" class="ofcrow" data-sid="${s.id}"><span class="ofcn"><b>${esc(ofdSvcName(s, d))}</b><small class="muted">${esc([rate != null ? `${fmtNum(rate, 2)} € / ${tr(OFC_UNITS.find(u => u[0] === s.unit)?.[1] || s.unit)}` : '', ct != null ? tr('contract rate') : '', ofcTax(s.tax)].filter(Boolean).join(' · '))}</small></span>${ic('plus', 's')}</button></li>`; }).join('')}</ul>`).join('')
      : `<p class="muted lempty">${ofcRows('services').length ? tr('Nothing matches.') : tr('No services yet (tab Services).')}</p>`;
  };
  draw();
  if (!Array.isArray(OFC.data.services)) {  // the catalogue may still be loading: show it once it is there
    $('#ofd-slist', md).innerHTML = `<p class="muted lempty">${tr('Loading…')}</p>`;
    (async () => { for (let i = 0; i < 60 && !Array.isArray(OFC.data.services) && md.isConnected; i++) { if (!OFC.loading.services) ofcLoad('services', true); await sleep(150); } if (md.isConnected) draw(); })();
  }
  md.addEventListener('input', e => { if (e.target.id === 'ofd-sq') draw(); });
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-sid],[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    const blank = {kind: 'service', service_id: null, title: '', detail: '', qty: 1, unit: 'day', rate: 0, tax: 'standard', raw_fee: 0, producing: 0, intext: 'intern', cost: 0, discountable: 1};
    if (b.dataset.m === 'free') { d.items.push(blank); md.remove(); await ofdPutItems(); $(`.ofdits [data-i="${d.items.length - 1}"][data-k="title"]`)?.focus(); return; }
    const s = ofcRow('services', +b.dataset.sid); if (!s) return;
    const ct = d.contract?.rates?.[s.id];
    d.items.push({...blank, service_id: s.id, title: ofdSvcName(s, d), unit: s.unit || 'day', rate: ct ?? (s.unit === 'hour' && s.hourly_rate != null ? s.hourly_rate : s.daily_rate) ?? 0, tax: s.tax || 'standard', raw_fee: s.raw_fee ? 1 : 0, producing: s.producing ? 1 : 0, intext: s.intext || 'intern'});
    md.remove(); await ofdPutItems();
    $(`.ofdits [data-i="${d.items.length - 1}"][data-k="qty"]`)?.focus();
  });
  setTimeout(() => { if (!isTouch()) $('#ofd-sq', md)?.focus(); }, 50);
}
// the editor's open sections are remembered while the page lives
document.addEventListener('toggle', e => { const s = e.target?.dataset?.sec; if (s && e.target.classList?.contains('ofdsec')) OFD.open[s] = e.target.open; }, true);
