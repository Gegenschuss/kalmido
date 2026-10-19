// 2.47.0 (#1215): parts of a quotation (Teilangebote). A quotation may have parts (own pages behind the title page); the
// title page lists them like services (position kind 'part' with a quantity). Opening a part shows the quotation's own
// position editor for it (ofdItemsHtml / ofdAutoHtml): tpCur() hands the shared handlers of office_docs.js a view of the
// document whose items / totals / calculation values are the part's; ofdPutItems / ofdPatch go to the part's routes.
// Opening / closing a part are links: they work inside the disabled fieldset of a sent or finalised quotation too.
const TP = {open: null};  // {doc, part}: the part open in the editor
const tpOpenId = d => TP.open && d && TP.open.doc === d.id ? TP.open.part : null;
const tpPart = (d, pid) => (d?.parts || []).find(p => p.id === pid) || null;
const TP_SETTINGS = ['raw_mode', 'raw_factor', 'prod_quotient', 'producing_rate', 'producing_on', 'discount_pct'];
// the document as the open part sees it (null: the title page is open); items is the part's own array (edits stay in it)
function tpView() {
  const d = OFD.doc, p = tpPart(d, tpOpenId(d));
  if (!p || p.kind !== 'items') return null;
  const st = p.settings || {};
  const v = {...d, items: p.items || [], totals: p.totals || {}, tpPart: p, discount_pct: st.discount_pct ?? 0};
  for (const k of TP_SETTINGS) if (k !== 'discount_pct' && st[k] != null) v[k] = st[k];
  return v;
}
const tpCur = () => tpView() || OFD.doc;
function tpPutItems() {
  const v = tpView();
  const items = (v.items || []).filter(bfaFilled).map(it => ({id: it.id, kind: it.kind, service_id: it.service_id, title: it.title, detail: it.detail, qty: it.qty, unit: it.unit, rate: it.rate, tax: it.tax,
    raw_fee: it.raw_fee, producing: it.producing, intext: it.intext, cost: it.cost, discountable: it.discountable, markup_pct: it.markup_pct}));
  return ofdSave('PUT', `/api/office/docs/${OFD.doc.id}/parts/${v.tpPart.id}/items`, {items});
}
// a change of the calculation values while a part is open goes to the part's settings, everything else to the document
function tpPatch(body) {
  const v = tpView(), st = {}, rest = {};
  for (const [k, x] of Object.entries(body || {})) (TP_SETTINGS.includes(k) ? st : rest)[k] = x;
  if (!v || !Object.keys(st).length) return ofdSave('PATCH', `/api/office/docs/${OFD.doc.id}`, body);
  return ofdSave('PATCH', `/api/office/docs/${OFD.doc.id}/parts/${v.tpPart.id}`, {settings: st}).then(j => Object.keys(rest).length ? ofdSave('PATCH', `/api/office/docs/${OFD.doc.id}`, rest) : j);
}
const tpMoney = (v, d) => ofdMoney(v || 0, d);

// ---- the title page: a part line (title, quantity x the part's net, open)
function tpItemRow(it, i, d, line, mv) {
  const p = tpPart(d, it.ref_part_id);
  return `<li class="ofdit tppl"><span class="ofdpos">${line?.pos || ''}</span>
    <div class="ofditb"><input class="ofdtt" data-i="${i}" data-k="title" value="${esc(it.title)}" maxlength="500" placeholder="${esc(p?.title || tr('Part'))}" aria-label="${esc(tr('Part'))}">
    <span class="ofdnums"><input data-i="${i}" data-k="qty" inputmode="decimal" class="numin" value="${esc(ofdNumIn(it.qty))}" aria-label="${esc(tr('Quantity'))}">
    <span class="muted">× ${esc(tpMoney(p?.totals?.net ?? it.rate, d))}</span>
    <b class="ofdlt">${line ? esc(line.total_text || ofdMoney(line.total, d)) : ''}</b></span>
    <span class="ofdflags"><label class="chkl"><input type="checkbox" data-i="${i}" data-k="discountable" ${it.discountable ? 'checked' : ''}> ${tr('discount')}</label>
    ${p ? `<a href="#" role="button" class="btn sm" data-ofd="tp-open" data-pid="${p.id}">${ic('right', 's')}<span>${tr('Open part')}</span></a>` : ''}</span></div>${mv}</li>`;
}

// ---- the section "Parts" below the title page's positions
function tpPartsHtml(d, adm) {
  if (d.kind !== 'offer') return '';
  const ps = d.parts || [];
  if (OFD.open.parts == null) OFD.open.parts = ps.length > 0;
  const rows = ps.map((p, i) => `<li class="ofdit tprow">
    <a href="#" role="button" class="tpopen" data-ofd="tp-open" data-pid="${p.id}"><span class="ofcn"><b>${esc(p.title || tr('Part'))}</b><small class="muted">${esc([p.kind === 'shoot' ? tr('Shoot calculation') : tr('{0} positions', (p.items || []).filter(x => x.kind === 'service').length),
      p.used ? (p.used > 1 ? tr('{0} times on the title page', p.used) : '') : '', p.print ? '' : tr('not printed')].filter(Boolean).join(' · '))}</small>${p.used ? '' : `<small class="tpunused">${esc(tr('not on the title page: does not count'))}</small>`}</span>
      <b class="ofdlt">${esc(tpMoney(p.totals?.net, d))}</b></a>
    <label class="chkl tpprint"><input type="checkbox" data-tp="print" data-pid="${p.id}" ${p.print ? 'checked' : ''}> ${tr('Print')}</label>
    <span class="ofdmv"><button type="button" class="ib" data-ofd="tp-up" data-pid="${p.id}" ${i === 0 ? 'disabled' : ''} aria-label="${esc(tr('Move up'))}">${ic('up', 's')}</button><button type="button" class="ib" data-ofd="tp-down" data-pid="${p.id}" ${i === ps.length - 1 ? 'disabled' : ''} aria-label="${esc(tr('Move down'))}">${ic('down', 's')}</button><button type="button" class="ib" data-ofd="tp-del" data-pid="${p.id}" aria-label="${esc(tr('Remove'))}">${ic('x', 's')}</button></span></li>`).join('');
  const add = `<div class="ofdadd"><button type="button" class="btn sm" data-ofd="tp-add" data-kind="items">${ic('plus', 's')}<span>${tr('Add part')}</span></button>${d.parts_shoot && OFC.info?.industry?.length ? `<button type="button" class="btn sm" data-ofd="tp-add" data-kind="shoot">${ic('plus', 's')}<span>${tr('Add shoot calculation')}</span></button>` : ''}</div>`;
  return ofdSec('parts', tr('Parts'), `${ps.length ? `<ul class="ofdits tplist" role="list">${rows}</ul>` : `<p class="muted">${tr('A part is an own page of the quotation (e.g. a module or a shooting day). The title page lists it with a quantity.')}</p>`}${add}`,
    ps.length ? `<span class="c muted">${ps.length}</span>` : '');
}

// ---- an open part: its title, print switch, positions (the quotation's editor) and sums
function tpPartEditorHtml(d, adm) {
  const p = tpPart(d, tpOpenId(d));
  if (!p) return '';
  const head = `<div class="tphead"><a href="#" role="button" class="btn sm" data-ofd="tp-back">${ic('left', 's')}<span>${tr('Title page')}</span></a>
    <input class="tptitle" data-tp="title" data-pid="${p.id}" value="${esc(p.title)}" maxlength="300" aria-label="${esc(tr('Title of the part'))}">
    <label class="chkl tpprint"><input type="checkbox" data-tp="print" data-pid="${p.id}" ${p.print ? 'checked' : ''}> ${tr('Print in the PDF')}</label></div>
    ${p.used ? '' : `<p class="muted ofchint tpunused">${esc(tr('This part is not on the title page and does not count. Add it there with "Add service".'))}</p>`}`;
  if (p.kind === 'shoot') {
    // 2.47.0 (#1216): bound once on the office body (a morph replaces .tpsheet, a listener on it got lost)
    setTimeout(() => { const root = $('.office .ofcbody') || $('.tpsheet'); if (root && typeof dkSheetBind === 'function') dkSheetBind(root, p); }, 0);
    return head + `<div class="tpsheet">${typeof dkSheetHtml === 'function' ? dkSheetHtml(p, d, adm) : `<p class="muted">${tr('Not available')}</p>`}</div>`;
  }
  const v = tpView(), t = p.totals || {};
  const rows = [[t.labels?.net || tr('Net total'), tpMoney(t.net, d)]];
  if (t.net_incl_raw != null) rows.push([t.labels?.net_incl_raw, tpMoney(t.net_incl_raw, d)]);
  if (t.net_excl_raw != null) rows.push([t.labels?.net_excl_raw, tpMoney(t.net_excl_raw, d)]);
  const sums = `<div class="ofdtotals tptotals"><dl>${rows.map(([k, x], i) => `<div class="ofdtr tr-${i ? 'incl' : 'net'}"><dt>${esc(k)}</dt><dd>${esc(x)}</dd></div>`).join('')}</dl>
    ${adm && t.costs != null ? `<p class="muted ofdint">${ic('eye', 's')} ${tr('Internal: external costs {0}, surplus {1}', tpMoney(t.costs, d), tpMoney(t.margin, d))}</p>` : ''}</div>`;
  return head + ofdItemsHtml(v, adm) + ofdAutoHtml(v, t) + sums;
}

// ---- events (from ofdClick / ofdChange of office_docs.js)
async function tpClick(a, b) {
  const d = OFD.doc, pid = +b.dataset.pid || null;
  if (a === 'tp-open') { TP.open = {doc: d.id, part: pid}; ofdDraw(); setTimeout(() => $('.tphead .tptitle')?.scrollIntoView?.({block: 'nearest'}), 0); return; }
  if (a === 'tp-back') { TP.open = null; ofdDraw(); return; }
  if (!d.can_edit) return;
  if (a === 'tp-add') {
    const j = await ofdSave('POST', `/api/office/docs/${d.id}/parts`, {kind: b.dataset.kind || 'items'});
    if (j?.part) { TP.open = {doc: d.id, part: j.part.id}; OFD.open.parts = true; ofdDraw(); setTimeout(() => { const el = $('.tphead .tptitle'); el?.focus(); el?.select?.(); }, 0); }
    return;
  }
  const ps = d.parts || [], i = ps.findIndex(p => p.id === pid), p = ps[i];
  if (!p) return;
  if (a === 'tp-del') {
    if (!await askConfirm(tr('Remove part "{0}"?', p.title || tr('Part')), tr('Its positions and its lines on the title page are removed as well.'), {ok: tr('Remove'), danger: true})) return;
    if (tpOpenId(d) === pid) TP.open = null;
    await ofdSave('DELETE', `/api/office/docs/${d.id}/parts/${pid}`); return;
  }
  if (a === 'tp-up' || a === 'tp-down') {
    const j = a === 'tp-up' ? i - 1 : i + 1; if (j < 0 || j >= ps.length) return;
    const k = a === 'tp-up' ? j - 1 : j + 1, lo = ps[Math.min(j, k)]?.sort, hi = ps[Math.max(j, k)]?.sort, at = ps[j].sort;  // between the neighbour and the one behind it
    const sort = a === 'tp-up' ? (lo != null ? (lo + at) / 2 : at - 1) : (hi != null ? (hi + at) / 2 : at + 1);
    await ofdSave('PATCH', `/api/office/docs/${d.id}/parts/${pid}`, {sort});
    setTimeout(() => $(`.tplist [data-ofd="${a}"][data-pid="${pid}"]`)?.focus(), 0);
  }
}
async function tpChange(t) {
  const d = OFD.doc, pid = +t.dataset.pid;
  if (!d || !tpPart(d, pid)) return;
  if (t.dataset.tp === 'print') { await ofdSave('PATCH', `/api/office/docs/${d.id}/parts/${pid}`, {print: t.checked ? 1 : 0}); return; }
  if (t.dataset.tp === 'title') await ofdSave('PATCH', `/api/office/docs/${d.id}/parts/${pid}`, {title: t.value});
}
// the choice in "Add service" on the title page: after the services, the parts
function tpPickerHtml(d) {
  if (d.kind !== 'offer' || tpOpenId(d) || !(d.parts || []).length) return '';
  return `<h4 class="ofcgrp">${tr('Parts')}</h4><ul class="ofclist" role="list">${d.parts.map(p => `<li><button type="button" class="ofcrow" data-m="part" data-pid="${p.id}"><span class="ofcn"><b>${esc(p.title || tr('Part'))}</b><small class="muted">${esc([tpMoney(p.totals?.net, d), p.used ? tr('{0} times on the title page', p.used) : tr('not on the title page yet')].join(' · '))}</small></span>${ic('plus', 's')}</button></li>`).join('')}</ul>`;
}
async function tpPick(pid) {
  const d = OFD.doc, p = tpPart(d, pid); if (!p) return;
  d.items.push({kind: 'part', ref_part_id: p.id, service_id: null, title: p.title, detail: '', qty: 1, unit: 'piece', rate: p.totals?.net || 0, tax: 'standard', raw_fee: 0, producing: 0, intext: 'intern', cost: 0, discountable: 1});
  await ofdPutItems();
  $(`.ofdits [data-i="${d.items.length - 1}"][data-k="qty"]`)?.focus();
}
// ---- the invoice from a quotation with parts: title page / summary / like the quotation (preset of the office settings)
function tpInvoiceDialog(d) {
  const s = OFC.info?.settings || {}, lg = ofdLang(d);
  const modes = [['full', tr('Like the quotation: title page and every printed part with its positions')], ['title', tr('Title page only: every part as one position with its amount')],
    ['summary', tr('Everything in one position (one per VAT rate)')]];
  const cur = s.parts_invoice_mode || 'full';
  ofdDlg(tr('Create invoice'), `<fieldset class="tpmodes"><legend class="muted">${tr('This quotation has parts. What should the invoice show?')}</legend>${modes.map(([v, n]) => `<label class="tpmode"><input type="radio" name="tp-mode" value="${v}" ${v === cur ? 'checked' : ''}> <span>${esc(n)}</span></label>`).join('')}</fieldset>
    ${ofdF('tp-sum-title', tr('Title of the position'), `<input id="ofd-tp-sum-title" maxlength="300" value="${esc(s['parts_summary_title_' + lg] || (lg === 'en' ? 'Film production' : 'Filmherstellung'))}">`)}`,
    tr('Create invoice'), async md => {
      const mode = $('input[name="tp-mode"]:checked', md)?.value || cur;
      const j = await rawFetch('POST', `/api/office/docs/${d.id}/invoice`, {parts_mode: mode, parts_title: mode === 'summary' ? $('#ofd-tp-sum-title', md).value : ''});
      OFD.list = null; OFD.kind = 'invoice'; OFD.doc = j; TP.open = null; toast(tr('Invoice draft created')); go(`office/offers/${j.id}`);
    });
}
// the office settings: the preset for invoices from quotations with parts
function tpSettingsHtml(s, dis) {
  return `${ofcRowF('os-parts-inv', tr('Invoice from a quotation with parts'), ofcSel('os-parts-inv', s.parts_invoice_mode || 'full', [['full', tr('like the quotation')], ['title', tr('title page only')], ['summary', tr('one position per VAT rate')]]), tr('preset; chosen again when the invoice is created'))}
    ${ofcRowF('os-parts-t-de', tr('Title of the summary (German)'), `<input id="os-parts-t-de" value="${esc(s.parts_summary_title_de ?? 'Filmherstellung')}" maxlength="300" ${dis}>`)}
    ${ofcRowF('os-parts-t-en', tr('Title of the summary (English)'), `<input id="os-parts-t-en" value="${esc(s.parts_summary_title_en ?? 'Film production')}" maxlength="300" ${dis}>`)}`;
}
const tpSettingsBody = form => $('#os-parts-inv', form) ? {parts_invoice_mode: $('#os-parts-inv', form).value, parts_summary_title_de: $('#os-parts-t-de', form).value, parts_summary_title_en: $('#os-parts-t-en', form).value} : {};
