// Office & finance (2.36.1, #1021, module "office"): the view with its tabs -- quotations (office_docs.js), services,
// equipment + sets, text blocks, framework contracts, settings (company, logo, colour, language, currency, number scheme,
// producing / raw data rules, country pack, import / export of the master data). Everything belongs to the organisation
// one works in (the workspace switch); members read the master data, the organisation's admins edit it.
const OFC = {tab: '', data: {}, loading: {}, seq: 0, q: '', arch: false, info: null, infoErr: null, infoLoading: false};
const OFC_TABS = [['offers', 'receipt', N_('Quotations')], ['services', 'list', N_('Services')], ['equipment', 'camera', N_('Equipment')],
  ['texts', 'note', N_('Text blocks')], ['contracts', 'file', N_('Framework contracts')], ['settings', 'gear', N_('Settings')]];
const OFC_UNITS = [['day', N_('Day|unit')], ['hour', N_('Hour|unit')], ['piece', N_('Piece|unit')], ['minute', N_('Minute|unit')], ['flat', N_('Flat rate|unit')]];
const OFC_TAXES = [['standard', N_('standard rate')], ['reduced', N_('reduced rate')], ['exempt', N_('exempt')]];
const OFC_TEXT_KINDS = [['rights_time', N_('Rights: duration')], ['rights_territory', N_('Rights: territory')], ['rights_media', N_('Rights: media')],
  ['intro', N_('Introduction')], ['closing', N_('Closing')], ['note', N_('Note|office')], ['block', N_('Text block between positions')], ['raw_note', N_('Raw data note')]];
const officeOn = () => feat('office') && !S.me?.kid;
const ofcAdmin = () => OFC.info?.role === 'admin';
const ofcTab = () => OFC_TABS.some(t => t[0] === S.route.tab) ? S.route.tab : 'offers';
// money / numbers of the master data: in the person's locale, the organisation's currency
const ofcCur = () => OFC.info?.settings?.currency || 'EUR';
const ofcMoney = n => n == null || n === '' ? '' : `${(+n).toLocaleString(LOCALE(), {minimumFractionDigits: 2, maximumFractionDigits: 2})} ${ofcCur() === 'USD' ? '$' : '€'}`;
const ofcNum = v => { const s = String(v ?? '').trim().replace(/\s/g, ''); if (s === '') return null; const f = parseFloat(s.replace(',', '.')); return Number.isFinite(f) ? f : null; };
const ofcTax = k => { const t = OFC.info?.pack?.tax; const pct = t ? t[k] : null; return pct == null ? tr(OFC_TAXES.find(x => x[0] === k)?.[1] || k) : `${fmtNum(pct, 1)} %`; };

// ---- loading
async function ofcInfo(force) {
  if (OFC.infoLoading) return;
  if (OFC.info && !force) return;
  OFC.infoLoading = true;
  try { OFC.info = await api('GET', '/api/office/settings'); OFC.infoErr = null; }
  catch (x) { OFC.info = null; OFC.infoErr = x.message || tr('unknown'); }
  OFC.infoLoading = false;
  ofcDraw();
}
async function ofcLoad(kind, force) {
  if (!kind || kind === 'offers' || kind === 'settings') return;
  if (OFC.loading[kind]) return;
  if (OFC.data[kind] && !force) return;
  OFC.loading[kind] = true;
  const seq = ++OFC.seq;
  try { const j = await api('GET', `/api/office/${kind}?archived=1`); OFC.data[kind] = j.items || []; }
  catch (x) { OFC.data[kind] = {error: x.message || tr('unknown')}; }
  OFC.loading[kind] = false;
  ofcDraw();
}
function ofcDraw() { if (S.route.mod !== 'office') return; const el = $('#view'); if (el) keepFocus(el, () => setHtml(el, viewOffice())); }
const ofcReload = kind => { if (kind) delete OFC.data[kind]; else OFC.data = {}; if (S.route.mod === 'office') ofcDraw(); };
const ofcRows = kind => Array.isArray(OFC.data[kind]) ? OFC.data[kind] : [];
const ofcRow = (kind, id) => ofcRows(kind).find(r => r.id === id);
const ofcText = (id, lg) => { const t = ofcRow('texts', id); return t ? (lg === 'en' ? t.text_en || t.text_de : t.text_de || t.text_en) : ''; };

// ---- the view
function viewOffice() {
  if (!officeOn()) return `<div class="empty">${tr('Office & finance is off (Settings > Modules)')}</div>`;
  const tab = ofcTab();
  if (OFC.tab !== tab) { OFC.tab = tab; OFC.q = ''; }  // the search belongs to one tab
  if (!OFC.info && !OFC.infoErr && !OFC.infoLoading) setTimeout(ofcInfo, 0);
  const tabs = `<div class="seg ofctabs wrap" role="tablist" aria-label="${esc(tr('Office & finance'))}">${OFC_TABS.map(([k, i, n]) => `<button type="button" role="tab" data-go="office/${k}" aria-selected="${k === tab}" class="${k === tab ? 'on' : ''}">${ic(i, 's')}<span>${tr(n)}</span></button>`).join('')}</div>`;
  let body;
  if (OFC.infoErr) body = `<div class="empty">${ic('building')}<span>${esc(OFC.infoErr)}</span><a class="btn" href="#settings">${tr('Settings')}</a></div>`;
  else if (!OFC.info) body = `<p class="muted lempty">${tr('Loading…')}</p>`;
  else if (tab === 'offers') body = typeof ofdOffersTab === 'function' ? '' : `<div class="empty">${ic('receipt')}<span>${tr('Quotations arrive with the next step of this module.')}</span></div>`;
  else if (tab === 'settings') body = ofcSettingsHtml();
  else body = ofcListHtml(tab);
  const html = `<div class="dash office" data-ofctab="${tab}"><div class="ofchead"><h2>${ic('receipt')} ${tr('Office & finance')}</h2>${OFC.info ? `<span class="muted ofcorg">${esc(OFC.info.settings?.company?.name || orgLabelOf(OFC.info.org_id))}${OFC.info.role === 'admin' ? ` · ${tr('Admin|role')}` : ''}</span>` : ''}</div>${tabs}<div class="ofcbody">${body}</div></div>`;
  if (tab === 'offers' && OFC.info && typeof ofdOffersTab === 'function') setTimeout(() => { const el = $('.office .ofcbody'); if (el && ofcTab() === 'offers') ofdOffersTab(el); }, 0);
  return html;
}
const orgLabelOf = oid => (S.me?.workspaces || []).find(o => o.id === oid)?.name || '';

// ---- master data lists (services, equipment + sets, texts, contracts): rows with a tap target, search, archived
function ofcListHtml(kind) {
  if (!OFC.data[kind] && !OFC.loading[kind]) setTimeout(() => ofcLoad(kind), 0);
  if (kind === 'equipment' && !OFC.data.sets && !OFC.loading.sets) setTimeout(() => ofcLoad('sets'), 0);
  if (kind === 'contracts' && !OFC.data.texts && !OFC.loading.texts) setTimeout(() => ofcLoad('texts'), 0);
  const d = OFC.data[kind];
  if (!d) return `<p class="muted lempty">${tr('Loading…')}</p>`;
  if (d.error) return `<div class="empty">${esc(d.error)}</div>`;
  const q = OFC.q.trim().toLowerCase(), adm = ofcAdmin();
  const hit = r => !q || [r.name, r.name_de, r.name_en, r.category, r.key, r.text_de, r.text_en, r.note].some(v => (v || '').toLowerCase().includes(q));
  const bar = `<div class="ofcbar"><div class="ctsearch">${ic('search', 's')}<input id="ofc-q" type="search" value="${esc(OFC.q)}" placeholder="${esc(tr('Search'))}" aria-label="${esc(tr('Search'))}" autocomplete="off" enterkeyhint="search"></div>
    <label class="chkl"><input type="checkbox" id="ofc-arch" ${OFC.arch ? 'checked' : ''}> ${tr('Archived')}</label><span class="spacer"></span>
    ${adm ? `<button class="btn sm pri" data-ofc="new" data-kind="${kind}">${ic('plus', 's')}<span>${kind === 'services' ? tr('New service') : kind === 'equipment' ? tr('New device') : kind === 'texts' ? tr('New text block') : tr('New contract')}</span></button>` : ''}
    ${kind === 'equipment' && adm ? `<button class="btn sm" data-ofc="new" data-kind="sets">${ic('plus', 's')}<span>${tr('New set')}</span></button>` : ''}</div>`;
  const rows = d.filter(r => hit(r) && (OFC.arch || !r.archived));
  let list;
  if (kind === 'services') list = ofcGrouped(rows, r => r.category || tr('No category'), r => ofcRowBtn('services', r, r.name_de, [r.name_en, r.unit === 'hour' && r.hourly_rate != null ? `${ofcMoney(r.hourly_rate)}/${tr('h|unit')}` : r.daily_rate != null ? `${ofcMoney(r.daily_rate)}/${tr('Day|unit')}` : '', ofcTax(r.tax), r.raw_fee ? tr('raw data') : '', r.producing ? tr('producing') : '', r.intext === 'intern' ? tr('internal') : ''].filter(Boolean).join(' · ')));
  else if (kind === 'equipment') {
    list = ofcGrouped(rows, r => r.category || tr('No category'), r => ofcRowBtn('equipment', r, r.name, r.daily_rate != null ? `${ofcMoney(r.daily_rate)}/${tr('Day|unit')}` : ''));
    const sets = ofcRows('sets').filter(r => hit(r) && (OFC.arch || !r.archived));
    list += `<h3 class="ofcgrp">${tr('Sets')}</h3>` + (sets.length ? `<ul class="ofclist" role="list">${sets.map(r => ofcRowBtn('sets', r, r.name, [trn('{0} device', '{0} devices', (r.items || []).length), r.discount_pct ? tr('{0} % discount', fmtNum(r.discount_pct, 1)) : ''].filter(Boolean).join(' · '))).join('')}</ul>` : `<p class="muted lempty">${tr('No sets yet. A set bundles devices with one discount.')}</p>`);
  } else if (kind === 'texts') list = ofcGrouped(rows, r => tr(OFC_TEXT_KINDS.find(k => k[0] === r.kind)?.[1] || r.kind), r => ofcRowBtn('texts', r, r.key || (r.text_de || r.text_en).slice(0, 60), r.key ? [r.text_de, r.text_en].filter(Boolean).join(' / ').slice(0, 120) : (r.text_en || '').slice(0, 80)), OFC_TEXT_KINDS.map(k => tr(k[1])));
  else list = rows.length ? `<ul class="ofclist" role="list">${rows.map(r => ofcRowBtn('contracts', r, r.name, [r.date ? fmtDateLoc(r.date) : '', r.raw_included ? tr('raw data included') : '', r.client_id && (S.clients || []).find(c => c.id === r.client_id)?.name].filter(Boolean).join(' · '))).join('')}</ul>` : '';
  if (!rows.length && !list) list = `<div class="empty">${ic(kind === 'texts' ? 'note' : 'list')}<span>${q ? tr('Nothing matches.') : adm ? tr('Nothing here yet. Add the first entry or import a file under Settings.') : tr('Nothing here yet.')}</span></div>`;
  return bar + list;
}
function ofcGrouped(rows, keyOf, rowHtml, order) {
  const g = new Map();
  for (const r of rows) { const k = keyOf(r); if (!g.has(k)) g.set(k, []); g.get(k).push(r); }
  const keys = order ? [...order.filter(k => g.has(k)), ...[...g.keys()].filter(k => !order.includes(k))] : [...g.keys()];
  return keys.map(k => `<h3 class="ofcgrp">${esc(k)}<span class="c muted">${g.get(k).length}</span></h3><ul class="ofclist" role="list">${g.get(k).map(rowHtml).join('')}</ul>`).join('');
}
const ofcRowBtn = (kind, r, title, sub) => `<li><button type="button" class="ofcrow ${r.archived ? 'arch' : ''}" data-ofc="open" data-kind="${kind}" data-id="${r.id}"><span class="ofcn"><b>${esc(title)}</b>${sub ? `<small class="muted">${esc(sub)}</small>` : ''}</span>${r.archived ? `<span class="rotag">${ic('archive', 's')}${tr('Archived')}</span>` : ''}${ic('chev', 's')}</button></li>`;

// ---- the dialogs (one per kind; members get a read-only view)
const ofcSel = (id, cur, opts, empty) => `<select id="${id}">${empty != null ? `<option value="">${esc(empty)}</option>` : ''}${opts.map(([v, n]) => `<option value="${esc(v)}" ${String(v) === String(cur ?? '') ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select>`;
const ofcIn = (id, v, o = {}) => `<input id="${id}" value="${esc(v ?? '')}" maxlength="${o.max || 200}" ${o.num ? 'inputmode="decimal" class="numin"' : ''} ${o.ph ? `placeholder="${esc(o.ph)}"` : ''} ${o.list ? `list="${o.list}"` : ''}>`;
const ofcRowF = (id, label, field, hint) => `<div class="row"><label for="${id}">${esc(label)}</label>${field}${hint ? `<span class="muted ofchint">${esc(hint)}</span>` : ''}</div>`;
const ofcChk = (id, label, on) => `<div class="row"><label class="chkl" style="min-width:0"><input type="checkbox" id="${id}" ${on ? 'checked' : ''}> ${esc(label)}</label></div>`;
const ofcTextOpts = kind => ofcRows('texts').filter(t => t.kind === kind && !t.archived).map(t => [t.id, (t.key ? t.key + ': ' : '') + (t.text_de || t.text_en).slice(0, 70)]);
function ofcModal(kind, r) {
  const adm = ofcAdmin(), rate = v => v != null ? fmtNum(v, 2) : '';
  const titles = {services: [N_('New service'), N_('Edit service')], equipment: [N_('New device'), N_('Edit device')], sets: [N_('New set'), N_('Edit set')],
    texts: [N_('New text block'), N_('Edit text block')], contracts: [N_('New contract'), N_('Edit contract')]};
  let f = '';
  if (kind === 'services') {
    const cats = [...new Set(ofcRows('services').map(x => x.category).filter(Boolean))];
    f = ofcRowF('of-name_de', tr('Name (German)'), ofcIn('of-name_de', r?.name_de)) + ofcRowF('of-name_en', tr('Name (English)'), ofcIn('of-name_en', r?.name_en))
      + ofcRowF('of-category', tr('Category'), ofcIn('of-category', r?.category, {max: 80, list: 'of-cats', ph: tr('e.g. Video, Audio, Office')})) + `<datalist id="of-cats">${cats.map(c => `<option value="${esc(c)}">`).join('')}</datalist>`
      + ofcRowF('of-unit', tr('Unit'), ofcSel('of-unit', r?.unit || 'day', OFC_UNITS.map(([v, n]) => [v, tr(n)])))
      + ofcRowF('of-daily_rate', tr('Daily rate'), ofcIn('of-daily_rate', rate(r?.daily_rate), {num: true}), ofcCur()) + ofcRowF('of-hourly_rate', tr('Hourly rate'), ofcIn('of-hourly_rate', rate(r?.hourly_rate), {num: true}), ofcCur())
      + ofcRowF('of-tax', tr('VAT'), ofcSel('of-tax', r?.tax || 'standard', OFC_TAXES.map(([v, n]) => [v, `${tr(n)} (${ofcTax(v)})`])))
      + ofcChk('of-raw_fee', tr('Counts towards the raw data amount'), r?.raw_fee) + ofcChk('of-producing', tr('Counts towards the producing days'), r?.producing)
      + ofcRowF('of-intext', tr('Internal / external'), ofcSel('of-intext', r?.intext || 'extern', [['extern', tr('external')], ['intern', tr('internal')]]))
      + ofcRowF('of-role', tr('Role'), ofcIn('of-role', r?.role, {max: 80, ph: tr('optional')})) + ofcRowF('of-sort', tr('Order'), ofcIn('of-sort', r?.sort ?? '', {num: true}));
  } else if (kind === 'equipment') {
    const cats = [...new Set(ofcRows('equipment').map(x => x.category).filter(Boolean))];
    f = ofcRowF('of-name', tr('Name'), ofcIn('of-name', r?.name)) + ofcRowF('of-category', tr('Category'), ofcIn('of-category', r?.category, {max: 80, list: 'of-cats'})) + `<datalist id="of-cats">${cats.map(c => `<option value="${esc(c)}">`).join('')}</datalist>`
      + ofcRowF('of-daily_rate', tr('Daily rate'), ofcIn('of-daily_rate', rate(r?.daily_rate), {num: true}), ofcCur());
  } else if (kind === 'sets') {
    const eq = ofcRows('equipment').filter(x => !x.archived).map(x => [x.id, x.name]);
    const items = (r?.items || []);
    f = ofcRowF('of-name', tr('Name'), ofcIn('of-name', r?.name)) + ofcRowF('of-discount_pct', tr('Discount'), ofcIn('of-discount_pct', r?.discount_pct != null ? fmtNum(r.discount_pct, 1) : '', {num: true}), '%')
      + `<div class="row"><label>${tr('Devices')}</label></div><div id="of-items" class="ofcitems">${items.map(it => ofcSetItemHtml(eq, it)).join('')}</div>${adm ? `<button type="button" class="btn sm" data-m="add-item">${ic('plus', 's')} ${tr('Add device')}</button>` : ''}`;
  } else if (kind === 'texts') {
    f = ofcRowF('of-kind', tr('Kind'), ofcSel('of-kind', r?.kind || 'block', OFC_TEXT_KINDS.map(([v, n]) => [v, tr(n)]))) + ofcRowF('of-key', tr('Short name'), ofcIn('of-key', r?.key, {max: 80, ph: tr('optional')}))
      + `<div class="row"><label for="of-text_de">${tr('Text (German)')}</label><textarea id="of-text_de" rows="4" maxlength="8000">${esc(r?.text_de || '')}</textarea></div>`
      + `<div class="row"><label for="of-text_en">${tr('Text (English)')}</label><textarea id="of-text_en" rows="4" maxlength="8000">${esc(r?.text_en || '')}</textarea></div>` + ofcRowF('of-sort', tr('Order'), ofcIn('of-sort', r?.sort ?? '', {num: true}));
  } else if (kind === 'contracts') {
    const cl = (typeof clientsOn === 'function' && clientsOn()) ? (S.clients || []).filter(c => !c.archived).map(c => [c.id, c.name]) : [];
    const svc = ofcRows('services').filter(x => !x.archived);
    const rates = r?.rates || {};
    f = ofcRowF('of-name', tr('Name'), ofcIn('of-name', r?.name, {ph: tr('e.g. framework contract with Beispielkunde AG')}))
      + (cl.length ? ofcRowF('of-client_id', tr('Client'), ofcSel('of-client_id', r?.client_id, cl, tr('none'))) : '')
      + `<div class="row"><label id="of-datel">${tr('Date')}</label>${dateIn('of-date', r?.date || '', {label: tr('Date'), empty: tr('optional')})}</div>`
      + ofcChk('of-raw_included', tr('Raw data always included (no option line)'), r?.raw_included)
      + ofcRowF('of-rights_time_id', tr('Rights: duration'), ofcSel('of-rights_time_id', r?.rights_time_id, ofcTextOpts('rights_time'), tr('none')))
      + ofcRowF('of-rights_territory_id', tr('Rights: territory'), ofcSel('of-rights_territory_id', r?.rights_territory_id, ofcTextOpts('rights_territory'), tr('none')))
      + ofcRowF('of-rights_media_id', tr('Rights: media'), ofcSel('of-rights_media_id', r?.rights_media_id, ofcTextOpts('rights_media'), tr('none')))
      + `<div class="row"><label for="of-rights_note_de">${tr('Rights note (German)')}</label><textarea id="of-rights_note_de" rows="2" maxlength="8000">${esc(r?.rights_note_de || '')}</textarea></div>`
      + `<div class="row"><label for="of-rights_note_en">${tr('Rights note (English)')}</label><textarea id="of-rights_note_en" rows="2" maxlength="8000">${esc(r?.rights_note_en || '')}</textarea></div>`
      + `<div class="row"><label for="of-closing_de">${tr('Closing (German)')}</label><textarea id="of-closing_de" rows="2" maxlength="8000">${esc(r?.closing_de || '')}</textarea></div>`
      + `<div class="row"><label for="of-closing_en">${tr('Closing (English)')}</label><textarea id="of-closing_en" rows="2" maxlength="8000">${esc(r?.closing_en || '')}</textarea></div>`
      + `<details class="ofcrates"><summary>${tr('Special rates')} <span class="muted">(${Object.keys(rates).length})</span></summary><div class="ofcrl">${svc.map(s => `<div class="row"><label for="of-rate-${s.id}">${esc(s.name_de)}</label><input id="of-rate-${s.id}" data-rate="${s.id}" inputmode="decimal" class="numin" value="${rates[s.id] != null ? esc(fmtNum(rates[s.id], 2)) : ''}" placeholder="${esc(s.daily_rate != null ? fmtNum(s.daily_rate, 2) : '–')}"></div>`).join('') || `<p class="muted">${tr('Add services first.')}</p>`}</div></details>`
      + `<div class="row"><label for="of-note">${tr('Note')}</label><textarea id="of-note" rows="2" maxlength="8000">${esc(r?.note || '')}</textarea></div>`;
  }
  const md = modal(`<h3>${tr(titles[kind][r ? 1 : 0])}</h3>${f}
    ${r ? ofcChk('of-archived', tr('Archived (hidden from the lists and the pickers)'), r.archived) : ''}
    <div class="aerr" role="alert"></div>
    <div class="foot">${r && adm ? `<button class="btn danger" data-m="del">${tr('Delete')}</button>` : ''}<span class="spacer"></span><button class="btn" data-m="close">${adm ? tr('Cancel') : tr('Close')}</button>${adm ? `<button class="btn pri" data-m="save">${r ? tr('Save') : tr('Add')}</button>` : ''}</div>`);
  md.classList.add('ofcdlg');
  if (!adm) for (const el of $$('input,select,textarea,button[data-dpfor]', md)) el.disabled = true;
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    const m = b.dataset.m;
    if (m === 'close') { md.remove(); return; }
    if (m === 'add-item') { const eq = ofcRows('equipment').filter(x => !x.archived).map(x => [x.id, x.name]); $('#of-items', md).insertAdjacentHTML('beforeend', ofcSetItemHtml(eq, {equipment_id: eq[0]?.[0], qty: 1})); return; }
    if (m === 'rm-item') { b.closest('.ofcitem').remove(); return; }
    try {
      if (m === 'del') {
        if (!await askConfirm(tr('Delete “{0}”?', r.name || r.name_de || r.key || ''), tr('Entries that documents, contracts or sets still use are archived instead.'), {ok: tr('Delete'), danger: true})) return;
        const j = await api('DELETE', `/api/office/${kind}/${r.id}`); md.remove(); ofcReload(kind); toast(j.result === 'archived' ? tr('Archived (still in use)') : tr('Deleted'));
        return;
      }
      const v = id => $(id, md)?.value ?? '';
      const body = {};
      if (kind === 'services') Object.assign(body, {name_de: v('#of-name_de'), name_en: v('#of-name_en'), category: v('#of-category'), unit: v('#of-unit'), daily_rate: ofcNum(v('#of-daily_rate')), hourly_rate: ofcNum(v('#of-hourly_rate')), tax: v('#of-tax'), raw_fee: $('#of-raw_fee', md).checked ? 1 : 0, producing: $('#of-producing', md).checked ? 1 : 0, intext: v('#of-intext'), role: v('#of-role'), sort: ofcNum(v('#of-sort')) ?? 0});
      else if (kind === 'equipment') Object.assign(body, {name: v('#of-name'), category: v('#of-category'), daily_rate: ofcNum(v('#of-daily_rate'))});
      else if (kind === 'sets') Object.assign(body, {name: v('#of-name'), discount_pct: ofcNum(v('#of-discount_pct')), items: $$('.ofcitem', md).map(it => ({equipment_id: +$('select', it).value, qty: ofcNum($('input', it).value) ?? 1})).filter(it => it.equipment_id)});
      else if (kind === 'texts') Object.assign(body, {kind: v('#of-kind'), key: v('#of-key'), text_de: v('#of-text_de'), text_en: v('#of-text_en'), sort: ofcNum(v('#of-sort')) ?? 0});
      else if (kind === 'contracts') {
        const rates = {}; for (const inp of $$('[data-rate]', md)) { const n = ofcNum(inp.value); if (n != null) rates[inp.dataset.rate] = n; }
        Object.assign(body, {name: v('#of-name'), date: v('#of-date'), raw_included: $('#of-raw_included', md).checked ? 1 : 0, rights_time_id: +v('#of-rights_time_id') || null, rights_territory_id: +v('#of-rights_territory_id') || null,
          rights_media_id: +v('#of-rights_media_id') || null, rights_note_de: v('#of-rights_note_de'), rights_note_en: v('#of-rights_note_en'), closing_de: v('#of-closing_de'), closing_en: v('#of-closing_en'), rates, note: v('#of-note')});
        if ($('#of-client_id', md)) body.client_id = +v('#of-client_id') || null;
      }
      if ($('#of-archived', md)) body.archived = $('#of-archived', md).checked ? 1 : 0;
      await api(r ? 'PATCH' : 'POST', r ? `/api/office/${kind}/${r.id}` : `/api/office/${kind}`, body);
      md.remove(); ofcReload(kind); toast(r ? tr('Saved') : tr('Added'));
    } catch (x) { const el = $('.aerr', md); if (el) el.textContent = x.message || ''; }
  });
  setTimeout(() => { if (!isTouch() && adm) $('input:not([type=hidden]),select,textarea', md)?.focus(); }, 50);
  return md;
}
const ofcSetItemHtml = (eq, it) => `<div class="ofcitem"><select aria-label="${esc(tr('Device'))}">${eq.map(([v, n]) => `<option value="${v}" ${v === it.equipment_id ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select><input inputmode="decimal" class="numin" value="${esc(fmtNum(it.qty ?? 1, 2))}" aria-label="${esc(tr('Quantity'))}"><button type="button" class="iconbtn" data-m="rm-item" aria-label="${esc(tr('Remove'))}">${ic('x', 's')}</button></div>`;

// ---- settings tab (admins edit; members see the values)
function ofcSettingsHtml() {
  const s = OFC.info.settings, p = OFC.info.pack, adm = ofcAdmin(), co = s.company || {}, cf = OFC.info.company_fields || {};
  if (!OFC.data.texts && !OFC.loading.texts) setTimeout(() => ofcLoad('texts'), 0);
  if (!OFC.data.services && !OFC.loading.services) setTimeout(() => ofcLoad('services'), 0);
  const ta = (id, label, lines, hint) => `<div class="row"><label for="${id}">${esc(label)}</label><textarea id="${id}" rows="${Math.max(2, (lines || []).length + 1)}" maxlength="3000" ${adm ? '' : 'disabled'}>${esc((lines || []).join('\n'))}</textarea>${hint ? `<span class="muted ofchint">${esc(hint)}</span>` : ''}</div>`;
  const svc = ofcRows('services').filter(x => !x.archived).map(x => [x.id, x.name_de]);
  const logo = s.logo ? `<img class="ofclogo" src="/api/office/logo?v=${encodeURIComponent(s.logo)}" alt="${esc(tr('Logo'))}">` : `<span class="muted">${tr('No logo yet')}</span>`;
  const dis = adm ? '' : 'disabled';
  return `<form class="ofcset" id="ofc-set" autocomplete="off">
    <h3>${tr('Company')}</h3>
    ${ofcRowF('os-name', tr('Company name'), `<input id="os-name" value="${esc(cf.name || co.name || '')}" maxlength="200" ${dis}>`)}
    ${ofcCompanyFieldsHtml(cf, dis)}
    <details class="ofcfree"><summary>${tr('Free lines (used where the fields above are empty)')}</summary>
    ${ta('os-lines', tr('Address lines'), co.lines, tr('one line each: street, postcode and city'))}
    ${ta('os-contact', tr('Contact lines'), co.contact_lines, tr('phone, e-mail, website'))}
    ${ta('os-register', tr('Register lines'), co.register_lines, tr('legal form, register, managing director'))}
    ${ta('os-bank', tr('Bank lines'), co.bank_lines, tr('bank, IBAN, BIC; tax number / VAT id'))}</details>
    <div class="row"><label>${tr('Logo')}</label><span class="lacts">${logo}${adm ? `<input type="file" id="os-logo" accept="image/png,image/jpeg,image/webp" aria-label="${esc(tr('Upload logo'))}">${s.logo ? `<button type="button" class="btn sm" data-ofc="logo-del">${tr('Remove')}</button>` : ''}` : ''}</span><span class="muted ofchint">${tr('PNG at least 600 px wide (also JPEG or WebP, up to 4 MB)')}</span></div>
    ${ofcRowF('os-color', tr('Brand colour'), `<span class="lacts"><input id="os-color" value="${esc(s.color || '')}" maxlength="7" placeholder="#2f5d8a" class="numin" ${dis}><i class="ofcsw" style="background:${cssColor(s.color) || 'var(--accent)'}"></i></span>`, tr('accent in the printed documents; empty = the app’s accent colour'))}
    <h3>${tr('Documents')}</h3>
    ${ofcRowF('os-lang', tr('Document language'), ofcSel('os-lang', s.lang, [['de', 'Deutsch'], ['en', 'English']]))}
    ${ofcRowF('os-currency', tr('Currency'), `<span class="lacts">${ofcSel('os-currency', s.currency, [['EUR', 'EUR'], ['USD', 'USD']])}<label for="os-fx" class="muted">${tr('1 € in USD')}</label><input id="os-fx" value="${esc(fmtNum(s.fx_usd, 4))}" inputmode="decimal" class="numin" ${dis}></span>`)}
    ${ofcRowF('os-scheme', tr('Number scheme'), `<span class="lacts"><input id="os-scheme" value="${esc(s.offer_scheme || '')}" maxlength="80" ${dis}><span class="muted" id="os-preview">${tr('next: {0}', esc(OFC.info.number_preview || ''))}</span></span>`, tr('placeholders: {yyyy} {yy} {seq:03} {project} {client} {date} {initials}'))}
    ${ofcRowF('os-numat', tr('Quotation number'), ofcSel('os-numat', s.offer_number_at || 'create', [['create', tr('when the quotation is created')], ['finalize', tr('when it is finalised')]]))}
    ${ofcRowF('os-valid', tr('Quotation valid for'), `<span class="lacts"><input id="os-valid" value="${esc(String(s.offer_valid_days ?? 30))}" inputmode="numeric" class="numin" ${dis}><span class="muted">${tr('days')}</span></span>`)}
    <h3>${tr('Calculation rules')}</h3>
    ${ofcRowF('os-pq', tr('Producing quotient'), `<input id="os-pq" value="${esc(fmtNum(s.prod_quotient, 2))}" inputmode="decimal" class="numin" ${dis}>`, tr('producing days = production days ÷ quotient, rounded to half days'))}
    ${ofcRowF('os-ps', tr('Producing rate from'), ofcSel('os-ps', s.producing_service_id, svc, tr('fixed rate below')))}
    ${ofcRowF('os-pr', tr('Producing rate'), `<input id="os-pr" value="${esc(fmtNum(s.producing_rate, 2))}" inputmode="decimal" class="numin" ${dis}>`, `${ofcCur()} ${tr('per day')}`)}
    ${ofcRowF('os-rf', tr('Raw data factor'), `<input id="os-rf" value="${esc(fmtNum(s.raw_factor, 2))}" inputmode="decimal" class="numin" ${dis}>`, tr('raw data amount = sum of the raw data positions × factor'))}
    <h3>${tr('Default texts')}</h3>
    ${ofcRowF('os-intro-de', tr('Introduction (German)'), ofcSel('os-intro-de', s.intro_text_id?.de, ofcTextOpts('intro'), tr('none')))}
    ${ofcRowF('os-intro-en', tr('Introduction (English)'), ofcSel('os-intro-en', s.intro_text_id?.en, ofcTextOpts('intro'), tr('none')))}
    ${ofcRowF('os-closing-de', tr('Closing (German)'), ofcSel('os-closing-de', s.closing_text_id?.de, ofcTextOpts('closing'), tr('none')))}
    ${ofcRowF('os-closing-en', tr('Closing (English)'), ofcSel('os-closing-en', s.closing_text_id?.en, ofcTextOpts('closing'), tr('none')))}
    ${ofcRowF('os-rt', tr('Rights: duration'), ofcSel('os-rt', s.rights_default?.time_id, ofcTextOpts('rights_time'), tr('none')))}
    ${ofcRowF('os-rr', tr('Rights: territory'), ofcSel('os-rr', s.rights_default?.territory_id, ofcTextOpts('rights_territory'), tr('none')))}
    ${ofcRowF('os-rm', tr('Rights: media'), ofcSel('os-rm', s.rights_default?.media_id, ofcTextOpts('rights_media'), tr('none')))}
    <h3>${tr('Country pack')}</h3>
    ${ofcRowF('os-pack', tr('Country pack'), `<span class="lacts">${ofcSel('os-pack', s.pack, (OFC.packs || [[p.code, p.name]]))}<span class="muted">${esc(tr('VAT: {0} standard, {1} reduced, {2} exempt', `${fmtNum(p.tax.standard, 1)} %`, `${fmtNum(p.tax.reduced, 1)} %`, `${fmtNum(p.tax.exempt, 1)} %`))}</span></span>`)}
    ${adm ? `<div class="foot stfoot"><span class="aerr" role="alert"></span><span class="spacer"></span><button type="submit" class="btn pri" data-ofc="save-settings">${tr('Save')}</button></div>` : ''}
    <h3>${tr('Master data file')}</h3>
    <p class="muted">${tr('Export writes services, equipment, sets, text blocks, contracts and these settings into one JSON file; import reads such a file (also one made from a spreadsheet) and adds what is missing.')}</p>
    <div class="lacts"><a class="btn sm" href="/api/office/export" download="office-master-data.json">${ic('download', 's')} ${tr('Export')}</a>
      ${adm ? `<input type="file" id="os-import" accept="application/json,.json" hidden><button type="button" class="btn sm" data-ofc="import">${ic('upload', 's')} ${tr('Import')}</button><label class="chkl"><input type="checkbox" id="os-overwrite"> ${tr('overwrite existing')}</label>` : ''}</div>
    ${adm ? `<h3>${tr('Access log')}</h3><p class="muted">${tr('Who opened, printed, changed or exported documents and master data of this organisation.')}</p>${ofcLogHtml()}` : ''}
  </form>`;
}
// 2.36.2 (#1021 P4): the company as single fields (print lines are made from them; the free lines stay the fallback)
const OFC_CO_FIELDS = [['street', N_('Street'), 200], ['zip', N_('Postcode'), 20], ['city', N_('City'), 120], ['country', N_('Country (ISO code)'), 2],
  ['email', N_('E-mail'), 200], ['phone', N_('Phone'), 60], ['tax_number', N_('Tax number'), 40], ['vat_id', N_('VAT ID'), 20], ['bank_name', N_('Bank'), 120],
  ['iban', N_('IBAN'), 42], ['bic', N_('BIC'), 11], ['register_court', N_('Register court'), 120], ['register_no', N_('Register number'), 60],
  ['managing_directors', N_('Managing directors'), 300]];
function ofcCompanyFieldsHtml(cf, dis) {
  return `<div class="ofcco">${OFC_CO_FIELDS.map(([k, n, mx]) => ofcRowF('osc-' + k, tr(n), `<input id="osc-${k}" data-co="${k}" value="${esc(cf[k] || '')}" maxlength="${mx}" ${k === 'country' ? 'class="numin" autocapitalize="characters"' : ''} ${dis}>`)).join('')}</div>`;
}
function ofcLogHtml() {
  if (!OFC.log) return `<button type="button" class="btn sm" data-ofc="log">${ic('clock', 's')} ${tr('Show the latest entries')}</button>`;
  if (!OFC.log.length) return `<p class="muted">${tr('No entries yet.')}</p>`;
  const tg = {doc: N_('Quotation'), settings: N_('Settings'), company: N_('Company'), logo: N_('Logo'), master_data: N_('Master data'), services: N_('Services'),
    equipment: N_('Equipment'), sets: N_('Sets'), texts: N_('Text blocks'), contracts: N_('Framework contracts')};
  return `<ul class="ofdlog" role="list">${OFC.log.map(x => `<li><span class="muted">${esc(typeof ofdWhen === 'function' ? ofdWhen(x.at) : x.at)}</span> <b>${esc(x.user_name || '?')}</b> ${esc(typeof ofdActText === 'function' ? ofdActText(x.action) : x.action)} · ${esc(tr(tg[x.target] || x.target))}${x.doc_id ? ` <a href="#office/offers/${x.doc_id}">#${x.doc_id}</a>` : ''}</li>`).join('')}</ul>`;
}
async function ofcSaveSettings(form) {
  const v = id => $(id, form)?.value ?? '', lines = id => v(id).split('\n').map(x => x.trim()).filter(Boolean);
  const cof = {name: v('#os-name')}; for (const [k] of OFC_CO_FIELDS) cof[k] = v('#osc-' + k).trim();
  const body = {company: {name: v('#os-name'), lines: lines('#os-lines'), contact_lines: lines('#os-contact'), register_lines: lines('#os-register'), bank_lines: lines('#os-bank')},
    company_fields: cof, offer_number_at: v('#os-numat') || 'create',
    color: v('#os-color').trim(), lang: v('#os-lang'), currency: v('#os-currency'), fx_usd: ofcNum(v('#os-fx')), offer_scheme: v('#os-scheme'), offer_valid_days: ofcNum(v('#os-valid')),
    prod_quotient: ofcNum(v('#os-pq')), producing_service_id: +v('#os-ps') || null, producing_rate: ofcNum(v('#os-pr')), raw_factor: ofcNum(v('#os-rf')),
    intro_text_id: {de: +v('#os-intro-de') || null, en: +v('#os-intro-en') || null}, closing_text_id: {de: +v('#os-closing-de') || null, en: +v('#os-closing-en') || null},
    rights_default: {time_id: +v('#os-rt') || null, territory_id: +v('#os-rr') || null, media_id: +v('#os-rm') || null}, pack: v('#os-pack')};
  try { const j = await api('PUT', '/api/office/settings', body); OFC.info.settings = j.settings; OFC.info.company_fields = j.company_fields || OFC.info.company_fields; OFC.info.number_preview = j.number_preview; OFC.log = null; toast(tr('Saved')); ofcDraw(); }
  catch (x) { const el = $('.aerr', form); if (el) el.textContent = x.message || ''; }
}
async function ofcLogoUpload(file) {
  if (!file) return;
  const fd = new FormData(); fd.append('file', file);
  try {
    const r = await fetch('/api/office/logo', {method: 'POST', body: fd, credentials: 'same-origin'});
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || r.statusText);
    await ofcInfo(true); toast(tr('Logo saved'));
  } catch (x) { toast(x.message || tr('unknown')); }
}
async function ofcImport(file, overwrite) {
  if (!file) return;
  const fd = new FormData(); fd.append('file', file);
  try {
    const r = await fetch(`/api/office/import${overwrite ? '?overwrite=1' : ''}`, {method: 'POST', body: fd, credentials: 'same-origin'});
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || r.statusText);
    const c = j.counts || {}, n = Object.values(c).reduce((a, x) => a + (x && typeof x === 'object' ? (x.added || 0) + (x.updated || 0) : 0), 0);
    const um = Array.isArray(c.unmapped) ? c.unmapped.length : 0;
    toast(trn('Imported: {0} entry', 'Imported: {0} entries', n) + (um ? ' · ' + trn('{0} reference not found, left empty', '{0} references not found, left empty', um) : '')); ofcReload(); await ofcInfo(true);
  } catch (x) { toast(x.message || tr('unknown')); }
}

// ---- events
document.addEventListener('click', async e => {
  const b = e.target.closest?.('[data-ofc]'); if (!b) return;
  const a = b.dataset.ofc;
  if (a === 'new') { e.preventDefault(); ofcModal(b.dataset.kind, null); }
  else if (a === 'open') { e.preventDefault(); const r = ofcRow(b.dataset.kind, +b.dataset.id); if (r) ofcModal(b.dataset.kind, r); }
  else if (a === 'import') { e.preventDefault(); const inp = $('#os-import'); if (inp) { inp.onchange = () => { ofcImport(inp.files[0], $('#os-overwrite')?.checked); inp.value = ''; }; inp.click(); } }
  else if (a === 'log') { e.preventDefault(); try { const j = await api('GET', '/api/office/log?limit=50'); OFC.log = j.log || []; } catch (x) { toast(x.message || ''); OFC.log = []; } ofcDraw(); }
  else if (a === 'logo-del') { e.preventDefault(); try { await api('DELETE', '/api/office/logo'); await ofcInfo(true); toast(tr('Removed')); } catch (x) { toast(x.message || ''); } }
});
document.addEventListener('submit', e => { const f = e.target.closest?.('#ofc-set'); if (!f) return; e.preventDefault(); ofcSaveSettings(f); });
document.addEventListener('input', e => {
  const t = e.target;
  if (t.id === 'ofc-q') { OFC.q = t.value; ofcDraw(); }
  else if (t.id === 'os-color') { const sw = $('.ofcsw'); if (sw) sw.style.background = /^#[0-9a-fA-F]{6}$/.test(t.value.trim()) ? t.value.trim() : 'var(--accent)'; }
  else if (t.id === 'os-scheme') { clearTimeout(OFC.pvT); OFC.pvT = setTimeout(async () => { try { const j = await api('GET', `/api/office/number-preview?scheme=${encodeURIComponent(t.value)}`); const el = $('#os-preview'); if (el) el.textContent = j.valid ? tr('next: {0}', j.preview) : (j.error || tr('Invalid value: {0}', tr('Number scheme'))); } catch {} }, 250); }
});
document.addEventListener('change', e => {
  const t = e.target;
  if (t.id === 'ofc-arch') { OFC.arch = t.checked; ofcDraw(); }
  else if (t.id === 'os-logo') { ofcLogoUpload(t.files[0]); t.value = ''; }
});
