// 2.47.0 (#1215): parts of a quotation (Teilangebote). A quotation may have parts (own pages behind the title page); the
// title page lists them like services (position kind 'part' with a quantity). Opening a part shows the quotation's own
// position editor for it (ofdItemsHtml / ofdAutoHtml): tpCur() hands the shared handlers of office_docs.js a view of the
// document whose items / totals / calculation values are the part's; ofdPutItems / ofdPatch go to the part's routes.
// Opening / closing a part are links: they work inside the disabled fieldset of a sent or finalised quotation too.
// 2.113.0 (#2248): parts open in place on the title page (several at once, each in its own colour); TP.open is the part the
// current event happens in (tpf_ctx), not a view of its own any more.
const TP = {open: null};  // {doc, part}: the open part the current event happens in (2.113.0 #2248, tpf_ctx)
const tpOpenId = d => TP.open && d && TP.open.doc === d.id ? TP.open.part : null;
const tpPart = (d, pid) => (d?.parts || []).find(p => p.id === pid) || null;
const TP_SETTINGS = ['raw_mode', 'raw_factor', 'prod_quotient', 'producing_rate', 'producing_on', 'discount_pct'];
// the document as the open part sees it (null: the title page is open); items is the part's own array (edits stay in it)
function tpView() {
  return tpf_view(OFD.doc, tpPart(OFD.doc, tpOpenId(OFD.doc)));
}
// 2.113.0 (#2248): the view of one given part (several parts are drawn open on the title page at once)
function tpf_view(d, p) {
  if (!p || p.kind !== 'items') return null;
  const st = p.settings || {};
  const v = {...d, items: p.items || [], totals: p.totals || {}, tpPart: p, discount_pct: st.discount_pct ?? 0};
  for (const k of TP_SETTINGS) if (k !== 'discount_pct' && st[k] != null) v[k] = st[k];
  return v;
}
const tpCur = () => tpView() || OFD.doc;
function tpPutItems() {
  const v = tpView();
  const src = (v.items || []).filter(bfaFilled), items = src.map(it => ({id: it.id, kind: it.kind, service_id: it.service_id, title: it.title, detail: it.detail, qty: it.qty, unit: it.unit, rate: it.rate, tax: it.tax,
    raw_fee: it.raw_fee, producing: it.producing, in_handling: it.in_handling, in_markup: it.in_markup, intext: it.intext, cost: it.cost, discountable: it.discountable, markup_pct: it.markup_pct}));  // 2.113.1 (#2252): + the surcharge flags
  return ofdSave('PUT', `/api/office/docs/${OFD.doc.id}/parts/${v.tpPart.id}/items`, {items}, src);  // 2.269.0 A (#3012): + the lines sent (their new ids)
}
// a change of the calculation values while a part is open goes to the part's settings, everything else to the document
function tpPatch(body) {
  const v = tpView(), st = {}, rest = {};
  for (const [k, x] of Object.entries(body || {})) (TP_SETTINGS.includes(k) ? st : rest)[k] = x;
  if (!v || !Object.keys(st).length) return ofdSave('PATCH', `/api/office/docs/${OFD.doc.id}`, body);
  return ofdSave('PATCH', `/api/office/docs/${OFD.doc.id}/parts/${v.tpPart.id}`, {settings: st}).then(j => Object.keys(rest).length ? ofdSave('PATCH', `/api/office/docs/${OFD.doc.id}`, rest) : j);
}
const tpMoney = (v, d) => ofdMoney(v || 0, d);

// 2.114.3 (#2266): the producing inside a part's net (display only: its days, a shoot part its share line); '' = none
function tpProdNote(p) {
  const t = p?.totals || {};
  if (p?.kind === 'shoot') { const s = (t.lines || []).find(l => l?.block === 'share'); return s && +s.total > 0 ? tr('incl. producing ({0})', s.detail || '') : ''; }
  const days = +t.producing_days || 0;
  return days > 0 ? (days === 1 ? tr('incl. producing 1 day') : tr('incl. producing {0} days', ofdNumIn(days))) : '';
}
// ---- the title page: a part line (title, quantity x the part's net, open)
function tpItemRow(it, i, d, line, mv) {
  const p = tpPart(d, it.ref_part_id), pn = tpProdNote(p);
  return `<li class="ofdit tppl"><span class="ofdpos">${line?.pos || ''}</span>
    <div class="ofditb"><input class="ofdtt" data-i="${i}" data-k="title" value="${esc(it.title)}" maxlength="500" placeholder="${esc(p?.title || tr('Part'))}" aria-label="${esc(tr('Part'))}">
    ${pn ? `<small class="muted tpprod">${esc(pn)}</small>` : ''}
    <span class="ofdnums"><input data-i="${i}" data-k="qty" inputmode="decimal" class="numin" value="${esc(ofdNumIn(it.qty))}" aria-label="${esc(tr('Quantity'))}">
    <span class="muted">× ${esc(tpMoney(p?.totals?.net ?? it.rate, d))}</span>
    <b class="ofdlt">${line ? esc(line.total_text || ofdMoney(line.total, d)) : ''}</b></span>
    <span class="ofdflags"><label class="chkl"><input type="checkbox" data-i="${i}" data-k="discountable" ${it.discountable ? 'checked' : ''}> ${tr('discount')}</label>
    ${p ? `<a href="#" role="button" class="btn sm ${tpf_cls(d, p.id)}" data-ofd="tp-open" data-pid="${p.id}"><span class="tpfdot" aria-hidden="true"></span>${ic('right', 's')}<span>${tr('Open part')}</span></a>` : ''}</span></div>${mv}</li>`;  // 2.113.0 (#2248): the part's colour dot
}

// ---- the section "Parts" below the title page's positions

// 2.154.0 D (#1876): one button per industry pack that is switched on (one pack = the plain button, as before)
function tpPackBtns(packs) {
  const nm = x => (typeof x?.name === 'string' ? x.name : x?.name?.[uiLang()] || x?.name?.en || x?.name?.de || x?.code || '');
  if (packs.length < 2) return `<button type="button" class="btn sm" data-ofd="tp-add" data-kind="shoot" data-pack="${esc(packs[0].code)}">${ic('plus', 's')}<span>${tr('Add shoot calculation')}</span></button>`;
  return packs.map(x => `<button type="button" class="btn sm" data-ofd="tp-add" data-kind="shoot" data-pack="${esc(x.code)}">${ic('plus', 's')}<span>${esc(tr('Add calculation: {0}', nm(x)))}</span></button>`).join('');
}
function tpPartsHtml(d, adm) {
  if (d.kind !== 'offer') return '';
  const ps = d.parts || [];
  if (OFD.open.parts == null) OFD.open.parts = ps.length > 0;
  // 2.113.0 (#2248): a part opens right here (several at once), in its own colour; the row toggles it
  const rows = ps.map((p, i) => { const on = tpf_isOpen(d, p.id); return `<li class="ofdit tprow ${tpf_cls(d, p.id)}${on ? ' tpfon' : ''}">
    <a href="#" role="button" class="tpopen" data-ofd="tp-open" data-tog="1" data-pid="${p.id}" aria-expanded="${on}"><span class="tpfdot" aria-hidden="true"></span><span class="ofcn"><b>${esc(p.title || tr('Part'))}</b><small class="muted">${esc([p.kind === 'shoot' ? tr('Shoot calculation') : tr('{0} positions', (p.items || []).filter(x => x.kind === 'service').length),
      tpProdNote(p), p.used ? (p.used > 1 ? tr('{0} times on the title page', p.used) : '') : '', p.print ? '' : tr('not printed')].filter(Boolean).join(' · '))}</small>${p.used ? '' : `<small class="tpunused">${esc(tr('not on the title page: does not count'))}</small>`}</span>
      <b class="ofdlt">${esc(tpMoney(p.totals?.net, d))}</b><span class="tpfchev" aria-hidden="true">${ic('right', 's')}</span></a>
    ${on ? '' : `<label class="chkl tpprint"><input type="checkbox" data-tp="print" data-pid="${p.id}" ${p.print ? 'checked' : ''}> ${tr('Print')}</label>`}
    <span class="ofdmv"><button type="button" class="ib" data-ofd="tp-up" data-pid="${p.id}" ${i === 0 ? 'disabled' : ''} aria-label="${esc(tr('Move up'))}">${ic('up', 's')}</button><button type="button" class="ib" data-ofd="tp-down" data-pid="${p.id}" ${i === ps.length - 1 ? 'disabled' : ''} aria-label="${esc(tr('Move down'))}">${ic('down', 's')}</button><button type="button" class="ib" data-ofd="tp-del" data-pid="${p.id}" aria-label="${esc(tr('Remove'))}">${ic('x', 's')}</button></span>${on ? `<div class="tpfbox" data-pid="${p.id}">${tpPartEditorHtml(d, adm, p.id)}</div>` : ''}</li>`; }).join('');
  const add = `<div class="ofdadd"><button type="button" class="btn sm" data-ofd="tp-add" data-kind="items">${ic('plus', 's')}<span>${tr('Add part')}</span></button>${d.parts_shoot && OFC.info?.industry?.length ? tpPackBtns(OFC.info.industry) : ''}</div>`;
  return ofdSec('parts', tr('Parts'), `${ps.length ? `<ul class="ofdits tplist" role="list">${rows}</ul>` : `<p class="muted">${tr('A part is an own page of the quotation (e.g. a module or a shooting day). The title page lists it with a quantity.')}</p>`}${add}`,
    ps.length ? `<span class="c muted">${ps.length}</span>` : '');
}

// ---- an open part: its title, print switch, positions (the quotation's editor) and sums
function tpPartEditorHtml(d, adm, pid = tpOpenId(d)) {
  const p = tpPart(d, pid);
  if (!p) return '';
  // 2.113.0 (#2248): drawn open on the title page: "Part 2 of 3" in the part's colour instead of the way back to the title page
  const ps = d.parts || [];
  const head = `<div class="tphead"><span class="tpfkick">${esc(tr('Part {0}', tr('{0} of {1}', ps.indexOf(p) + 1, ps.length)))}</span>
    <input class="tptitle" data-tp="title" data-pid="${p.id}" value="${esc(p.title)}" maxlength="300" aria-label="${esc(tr('Title of the part'))}">
    <label class="chkl tpprint"><input type="checkbox" data-tp="print" data-pid="${p.id}" ${p.print ? 'checked' : ''}> ${tr('Print in the PDF')}</label></div>
    ${p.used ? '' : `<p class="muted ofchint tpunused">${esc(tr('This part is not on the title page and does not count. Add it there with "Add service".'))}</p>`}`;
  if (p.kind === 'shoot') {
    // 2.47.0 (#1216): bound once on the office body (a morph replaces .tpsheet, a listener on it got lost)
    setTimeout(() => { const root = $('.office .ofcbody') || $('.tpsheet'); if (root && typeof dkSheetBind === 'function') dkSheetBind(root, p); }, 0);
    return head + `<div class="tpsheet" data-pid="${p.id}">${typeof dkSheetHtml === 'function' ? dkSheetHtml(p, d, adm) : `<p class="muted">${tr('Not available')}</p>`}</div>`;
  }
  const v = tpf_view(d, p), t = p.totals || {};
  const rows = [[t.labels?.net || tr('Net total'), tpMoney(t.net, d)]];
  if (t.net_incl_raw != null) rows.push([t.labels?.net_incl_raw, tpMoney(t.net_incl_raw, d)]);
  if (t.net_excl_raw != null) rows.push([t.labels?.net_excl_raw, tpMoney(t.net_excl_raw, d)]);
  const sums = `<div class="ofdtotals tptotals"><dl>${rows.map(([k, x], i) => `<div class="ofdtr tr-${i ? 'incl' : 'net'}"><dt>${esc(k)}</dt><dd>${esc(x)}</dd></div>`).join('')}</dl>
    ${adm && t.costs != null ? `<p class="muted ofdint">${ic('eye', 's')} ${tr('Internal: external costs {0}, surplus {1}', tpMoney(t.costs, d), tpMoney(t.margin, d))}</p>` : ''}</div>`;
  // 2.113.0 (#2248): the title page shows the same fields: the part's ids get its own prefix (no double ids)
  return head + tpf_ids(ofdItemsHtml(v, adm) + ofdAutoHtml(v, t), p.id) + sums;
}
const tpf_ids = (h, pid) => h.replace(/ (id|for)="ofd-/g, ` $1="tpf${pid}-`);
// ---- 2.113.0 (#2248): open parts on the title page (per document, while the page lives) and their colours
const TPF = {exp: {}};  // doc id -> ids of the open parts
const TPF_N = 6;  // colours of the palette (office.css .tpf-c0 … .tpf-c5)
const tpf_isOpen = (d, pid) => !!d && (TPF.exp[d.id] || []).includes(pid);
function tpf_set(d, pid, on) { const l = (TPF.exp[d.id] || []).filter(x => x !== pid); if (on) l.push(pid); TPF.exp[d.id] = l; }
// stable by the place in the list: the title page's lines and the open part share it
function tpf_cls(d, pid) { const i = (d?.parts || []).findIndex(p => p.id === pid); return i < 0 ? '' : `tpf-c${i % TPF_N}`; }
// an event inside an open part makes it the part the shared handlers of office_docs.js work on (tpView / tpCur /
// ofdPutItems / ofdPatch); any other event in the editor works on the title page
function tpf_ctx(el) {
  const box = el?.closest?.('.tpfbox[data-pid]'), d = OFD.doc;
  TP.open = box && d ? {doc: d.id, part: +box.dataset.pid} : null;
}
// the selector prefix for focusing a field after a redraw (the title page comes first in the editor)
const tpf_sc = () => TP.open ? `.tpfbox[data-pid="${TP.open.part}"] ` : '';
function tpf_scroll(pid) {
  const el = $(`.tpfbox[data-pid="${pid}"]`)?.closest('.tprow'), calm = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  el?.scrollIntoView?.({block: 'start', behavior: calm ? 'auto' : 'smooth'});
}

// ---- events (from ofdClick / ofdChange of office_docs.js)
async function tpClick(a, b) {
  const d = OFD.doc, pid = +b.dataset.pid || null;
  // 2.113.0 (#2248): the row in "Parts" opens / closes the part in place; "Open part" on a title page line opens it and goes there
  if (a === 'tp-open') {
    const on = !b.dataset.tog || !tpf_isOpen(d, pid);
    tpf_set(d, pid, on); if (on) OFD.open.parts = true; ofdDraw();
    if (on && !b.dataset.tog) setTimeout(() => tpf_scroll(pid), 0);
    return;
  }
  if (!d.can_edit) return;
  if (a === 'tp-add') {
    for (let n = 0; OFD.saving && n < 50; n++) await new Promise(r => setTimeout(r, 100));  // 2.138.0 A (#2239): a running save of the title page first
    const j = await ofdSave('POST', `/api/office/docs/${d.id}/parts`, {kind: b.dataset.kind || 'items', ...(b.dataset.pack ? {pack: b.dataset.pack} : {})});
    if (j?.part) { tpf_set(d, j.part.id, true); OFD.open.parts = true; ofdDraw(); setTimeout(() => { const el = $(`.tpfbox[data-pid="${j.part.id}"] .tptitle`); el?.focus(); el?.select?.(); }, 0); }  // 2.113.0 (#2248)
    return;
  }
  const ps = d.parts || [], i = ps.findIndex(p => p.id === pid), p = ps[i];
  if (!p) return;
  if (a === 'tp-prod-doc') { await ofdSave('PATCH', `/api/office/docs/${d.id}/parts/${pid}`, {settings: {producing_on: null, prod_quotient: null, producing_rate: null}}); return; }  // 2.114.3 (#2266)
  if (a === 'tp-del') {
    if (!await askConfirm(tr('Remove part "{0}"?', p.title || tr('Part')), tr('Its positions and its lines on the title page are removed as well.'), {ok: tr('Remove'), danger: true})) return;
    tpf_set(d, pid, false); TP.open = null;  // 2.113.0 (#2248)
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
      const j = await oil_post(d, {parts_mode: mode, parts_title: mode === 'summary' ? $('#ofd-tp-sum-title', md).value : ''});  // 2.269.0 D (#3046); 2.356.0 C (#3003): asks before a second invoice
      if (!j) return;
      OFD.list = null; OFD.kind = 'invoice'; OFD.doc = j; TP.open = null; toast(tr('Invoice draft created')); go(`office/invoices/${j.id}`);
    });
}
// the office settings: the preset for invoices from quotations with parts
function tpSettingsHtml(s, dis) {
  return `${ofcRowF('os-parts-inv', tr('Invoice from a quotation with parts'), ofcSel('os-parts-inv', s.parts_invoice_mode || 'full', [['full', tr('like the quotation')], ['title', tr('title page only')], ['summary', tr('one position per VAT rate')]]), tr('preset; chosen again when the invoice is created'))}
    ${ofcRowF('os-parts-t-de', tr('Title of the summary (German)'), `<input id="os-parts-t-de" value="${esc(s.parts_summary_title_de ?? 'Filmherstellung')}" maxlength="300" ${dis}>`)}
    ${ofcRowF('os-parts-t-en', tr('Title of the summary (English)'), `<input id="os-parts-t-en" value="${esc(s.parts_summary_title_en ?? 'Film production')}" maxlength="300" ${dis}>`)}`;
}
const tpSettingsBody = form => $('#os-parts-inv', form) ? {parts_invoice_mode: $('#os-parts-inv', form).value, parts_summary_title_de: $('#os-parts-t-de', form).value, parts_summary_title_en: $('#os-parts-t-en', form).value} : {};
