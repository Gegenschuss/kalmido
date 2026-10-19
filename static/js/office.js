// Office & finance (2.36.1, #1021, module "office"): the view with its tabs -- quotations (office_docs.js), services,
// equipment + sets, text blocks, framework contracts, settings (company, logo, colour, language, currency, number scheme,
// producing / raw data rules, country pack, import / export of the master data). Everything belongs to the organisation
// one works in (the workspace switch); members read the master data, the organisation's admins edit it.
const OFC = {tab: '', data: {}, loading: {}, seq: 0, q: '', arch: false, info: null, infoErr: null, infoLoading: false};
const OFC_TABS = [['offers', 'receipt', N_('Quotes & invoices')], ['services', 'list', N_('Services')], ['equipment', 'camera', N_('Equipment')],
  ['texts', 'note', N_('Text blocks')], ['contracts', 'file', N_('Framework contracts')], ['settings', 'gear', N_('Settings')]];
const OFC_UNITS = [['day', N_('Day|unit')], ['hour', N_('Hour|unit')], ['piece', N_('Piece|unit')], ['minute', N_('Minute|unit')], ['flat', N_('Flat rate|unit')], ['percent', N_('Percent|unit')]];  // 2.47.0 (#1649): percent (KSK)
const OFC_TAXES = [['standard', N_('standard rate')], ['reduced', N_('reduced rate')], ['exempt', N_('exempt')]];
const OFC_TEXT_KINDS = [['rights_time', N_('Rights: duration')], ['rights_territory', N_('Rights: territory')], ['rights_media', N_('Rights: media')],
  ['intro', N_('Introduction')], ['closing', N_('Closing')], ['note', N_('Note|office')], ['block', N_('Text block between positions')], ['raw_note', N_('Raw data note')]];
// 2.53.0 (#1410): officeOn lives in lazyload.js (asked at start, before the office is loaded)
const ofcAdmin = () => OFC.info?.role === 'admin';
const pb_clOrg = () => OFC.info?.personal ? null : (OFC.info?.org_id || null);  // 2.47.3 (#1360): a personal office's clients are the private ones
const ofcWs = () => pb_clOrg() ? 'org:' + pb_clOrg() : 'private';  // 2.87.9 (#1940): the workspace of the shown office (importTargetConfirm)
const ofcTab = () => OFC_TABS.some(t => t[0] === S.route.tab) ? S.route.tab : S.route.tab === 'import' ? 'settings'
  : S.route.tab === 'start' || (!S.route.tab && isMobile()) ? 'start' : 'offers';  // 2.39.1 (#1182): the import page sits under Settings; 2.87.9 (#1917): the start page (phone without a tab)
// money / numbers of the master data: in the person's locale, the organisation's currency
const ofcCur = () => OFC.info?.settings?.currency || 'EUR';
const ofcMoney = n => n == null || n === '' ? '' : `${(+n).toLocaleString(LOCALE(), {minimumFractionDigits: 2, maximumFractionDigits: 2})} ${ofcCur() === 'USD' ? '$' : '€'}`;
// 2.50.1: thousands separators of the locale ("1.500,00", "1,500.00", "1.500") are read as such - a field filled with
// fmtNum(1500, 2) = "1.500" came back as 1.5 on save; a single separator without three digits after it stays the decimal one
const ofcNum = v => {
  let s = String(v ?? '').trim().replace(/[\s\u00a0\u202f']/g, ''); if (s === '') return null;
  const dec = (1.5).toLocaleString(LOCALE()).charAt(1) === ',' ? ',' : '.', grp = dec === ',' ? '.' : ',';
  if (s.includes(dec)) s = s.split(grp).join('');
  else if (new RegExp(`^-?\\d{1,3}(\\${grp}\\d{3})+$`).test(s)) s = s.split(grp).join('');
  const f = parseFloat(s.replace(',', '.')); return Number.isFinite(f) ? f : null;
};
const ofcTax = k => { const t = OFC.info?.pack?.tax; const pct = t ? t[k] : null; return pct == null ? tr(OFC_TAXES.find(x => x[0] === k)?.[1] || k) : `${fmtNum(pct, 1)} %`; };

// ---- loading
async function ofcInfo(force) {
  if (OFC.infoLoading || OFC.pbWait) return;  // 2.47.3 (#1360): not while the new workspace is being saved
  if (OFC.info && !force) return;
  OFC.infoLoading = true;
  const ws = OFC.ws;  // 2.80.0 (#1842): an answer for the workspace before a switch is dropped and read again
  let info = null, err = null;
  try { info = await api('GET', '/api/office/settings'); }
  catch (x) { err = x.message || tr('unknown'); }
  OFC.infoLoading = false;
  if (OFC.ws !== ws) { ofcInfo(); return; }
  OFC.info = info; OFC.infoErr = err;
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
function ofcDraw() { if (S.route.mod !== 'office') return; const el = $('#view'); if (el) keepFocus(el, () => setHtml(el, mg_wrap('office', viewOffice()))); }
const ofcReload = kind => { if (kind) delete OFC.data[kind]; else OFC.data = {}; if (S.route.mod === 'office') ofcDraw(); };
const ofcRows = kind => Array.isArray(OFC.data[kind]) ? OFC.data[kind] : [];
const ofcRow = (kind, id) => ofcRows(kind).find(r => r.id === id);
const ofcText = (id, lg) => { const t = ofcRow('texts', id); return t ? (lg === 'en' ? t.text_en || t.text_de : t.text_de || t.text_en) : ''; };

// ---- the view
function viewOffice() {
  if (!officeOn()) return `<div class="empty">${tr('Office & finance is off (Settings > Modules)')}</div>`;
  const tab = ofcTab();
  if (OFC.tab !== tab) { OFC.tab = tab; OFC.q = ''; }  // the search belongs to one tab
  pb_wsFollow();
  if (!OFC.info && !OFC.infoErr && !OFC.infoLoading) setTimeout(ofcInfo, 0);
  // 2.87.9 (#1917): no tab row any more -- the office menu (areas.js ofm_menuHtml, via mg_wrap) leads to every tab
  if (OFC.info) ofm_admSeen(OFC.info.role === 'admin');
  let body;
  if (OFC.infoErr) body = `<div class="empty nempty eact">${ic('building')}<span>${esc(OFC.infoErr)}</span><a class="btn" href="#settings">${tr('Settings')}</a></div>`;
  else if (!OFC.info) body = `<p class="muted lempty">${tr('Loading…')}</p>`;
  else if (tab === 'start') body = (pb_hintHtml() || '') + ofm_startHtml();  // 2.87.9 (#1917)
  else if (pb_hintHtml()) body = pb_hintHtml() + (tab === 'offers' ? '<div class="pboffers"></div>' : tab === 'settings' ? (S.route.tab === 'import' && typeof oimHtml === 'function' ? oimHtml() : ofcSettingsHtml()) : typeof OFC_TABS.find(t => t[0] === tab)?.[4] === 'function' ? OFC_TABS.find(t => t[0] === tab)[4]() : ofcListHtml(tab));  // 2.47.3 (#1360); 2.92.0 A (#1925): tabs of their own module here too
  else if (tab === 'offers') body = typeof ofdOffersTab === 'function' ? '' : `<div class="empty">${ic('receipt')}<span>${tr('Quotations arrive with the next step of this module.')}</span></div>`;
  else if (tab === 'settings') body = S.route.tab === 'import' && typeof oimHtml === 'function' ? oimHtml() : ofcSettingsHtml();  // 2.39.1 (#1182): office/import
  else if (typeof OFC_TABS.find(t => t[0] === tab)?.[4] === 'function') body = OFC_TABS.find(t => t[0] === tab)[4]();  // 2.47.3 (B, #1022 #1652): tabs of their own module, [3] = admins only
  else body = ofcListHtml(tab);
  const html = `<div class="dash office" data-ofctab="${tab}"><div class="ofchead">${OFC.info ? `<span class="muted ofcorg">${esc(OFC.info.settings?.company?.name || (OFC.info.personal ? tr('Private|workspace') : orgLabelOf(OFC.info.org_id)))}${OFC.info.role === 'admin' ? ` · ${tr('Admin|role')}` : ''}</span>` : ''}</div><div class="ofcbody"${tab === 'offers' && !body ? ' data-fl-fill' : ''}>${body}</div></div>`;
  if (tab === 'offers' && OFC.info && typeof ofdOffersTab === 'function') setTimeout(() => { const el = $('.office .ofcbody .pboffers') || $('.office .ofcbody'); if (el && ofcTab() === 'offers') ofdOffersTab(el); }, 0);  // 2.47.3 (#1360): below the hint
  return html;
}
// ---- 2.47.3 (#1360): the office follows the workspace switch ("Private" = the person's own office, an organisation's =
// its office). wsSet (workspace.js) calls pb_wsChanged(true) before saving the setting and pb_wsChanged(false) after it,
// so the office is read for the new workspace only once the server knows it; a switch on another device is caught here.
function pb_reset(nav) {
  OFC.info = null; OFC.infoErr = null; OFC.data = {};
  if (typeof OFD !== 'undefined') { OFD.list = null; OFD.doc = null; OFD.docId = null; OFD.log = null; }
  if (typeof OIM !== 'undefined') { OIM.list = null; OIM.runs = null; OIM.clients = null; }  // 2.80.0 (#1836): runs, counter and clients of the new workspace
  if (nav && S.route.mod === 'office' && S.route.id) setTimeout(() => go('office/' + (S.route.tab || 'offers')), 0);  // a document of the other area
}
function pb_wsFollow() {
  if (!S.me || !S.settings) return;
  const ws = typeof wsCur === 'function' ? wsCur() : '';
  if (OFC.ws !== undefined && OFC.ws !== ws) pb_reset();
  OFC.ws = ws;
}
function pb_wsChanged(saving) {
  OFC.pbWait = !!saving;
  if (saving) { pb_reset(true); OFC.ws = typeof wsCur === 'function' ? wsCur() : ''; }
  else ofcDraw();
}
// the empty personal office of a person with organisations points to the offices of these organisations
function pb_hintHtml() {
  const h = OFC.info?.personal ? OFC.info.org_offices || [] : [];
  if (!h.length) return '';
  return `<div class="pbhint shint keep">${ic('building', 's')}<div>${h.map(o => `<p>${esc(tr('The office of your organisation {0} is in the workspace {0}.', o.name))}</p>
    <button type="button" class="btn sm" data-ofc="pb-ws" data-ws="org:${o.id}">${esc(tr('Switch to {0}', o.name))}</button>`).join('')}
    <p class="muted">${esc(tr('This is your personal office in the workspace Private: its clients, documents and settings are yours alone.'))}</p></div></div>`;
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
  if (kind === 'services') list = ofcGrouped(rows, r => r.category || tr('No category'), r => ofcRowBtn('services', r, r.name_de, [r.name_en, r.unit === 'percent' && r.daily_rate != null ? `${fmtNum(r.daily_rate, 2)} %` : r.unit === 'hour' && r.hourly_rate != null ? `${ofcMoney(r.hourly_rate)}/${tr('h|unit')}` : r.daily_rate != null ? `${ofcMoney(r.daily_rate)}/${tr('Day|unit')}` : '', ofcTax(r.tax), r.raw_fee ? tr('raw data') : '', r.producing ? tr('producing') : '', r.intext === 'intern' ? tr('internal') : r.intext === 'shooting' ? tr('Shoot') : ''].filter(Boolean).join(' · ')));
  else if (kind === 'equipment') {
    list = ofcGrouped(rows, r => r.category || tr('No category'), r => ofcRowBtn('equipment', r, r.name, [r.name_en, r.daily_rate != null ? `${ofcMoney(r.daily_rate)}/${tr('Day|unit')}` : '', ...(typeof astRowInfo === 'function' ? astRowInfo(r) : [])].filter(Boolean).join(' · ')));  // 2.45.1 (#1556): + English name; 2.92.0 B (#1931): + value
    list = (typeof astSummaryHtml === 'function' ? astSummaryHtml(d) : '') + list;  // 2.92.0 B (#1931): sums + insurance list export (admins); 2.92.3: office_assets.js may still be loading (a redraw follows)
    const sets = ofcRows('sets').filter(r => hit(r) && (OFC.arch || !r.archived));
    list += `<h3 class="ofcgrp">${tr('Sets')}</h3>` + (sets.length ? `<ul class="ofclist" role="list">${sets.map(r => ofcRowBtn('sets', r, r.name, [trn('{0} device', '{0} devices', (r.items || []).length), r.discount_pct ? tr('{0} % discount', fmtNum(r.discount_pct, 1)) : ''].filter(Boolean).join(' · '))).join('')}</ul>` : `<p class="muted lempty">${tr('No sets yet. A set bundles devices with one discount.')}</p>`);
  } else if (kind === 'texts') list = ofcGrouped(rows, r => tr(OFC_TEXT_KINDS.find(k => k[0] === r.kind)?.[1] || r.kind), r => ofcRowBtn('texts', r, r.key || (r.text_de || r.text_en).slice(0, 60), (r.text_de && !r.text_en ? tr('no English text stored') + ' · ' : '') + (r.key ? [r.text_de, r.text_en].filter(Boolean).join(' / ').slice(0, 120) : (r.text_en || '').slice(0, 80))), OFC_TEXT_KINDS.map(k => tr(k[1])));
  else list = rows.length ? `<ul class="ofclist" role="list">${rows.map(r => ofcRowBtn('contracts', r, r.name, [r.date ? fmtDateLoc(r.date) : '', r.raw_included ? tr('raw data included') : '', r.client_id && cdn_label((S.clients || []).find(c => c.id === r.client_id))].filter(Boolean).join(' · '))).join('')}</ul>` : '';
  if (!rows.length && !list) list = `<div class="empty nempty eact">${ic(kind === 'texts' ? 'note' : 'list')}<span>${q ? tr('Nothing matches.') : adm ? tr('Nothing here yet. Add the first entry or import a file under Settings.') : tr('Nothing here yet.')}</span></div>`;
  return bar + list + (kind === 'services' ? sr_roleSections(hit) : '');  // 2.47.0 (#1649)
}
// 2.47.0 (#1649): the masters Freelancer-Rollen (purchase price per day / hour, a service points to its role) and
// Drehpersonal (for the shoot calculation) below the services, like the sets below the equipment. Members get no prices.
function sr_roleSections(hit) {
  for (const k of ['roles', 'crew']) if (!OFC.data[k] && !OFC.loading[k]) setTimeout(() => ofcLoad(k), 0);
  const adm = ofcAdmin(), day = v => v != null ? `${ofcMoney(v)}/${tr('Day|unit')}` : '';
  const sec = (k, title, hint, sub) => {
    const rows = ofcRows(k).filter(r => hit(r) && (OFC.arch || !r.archived));
    return `<h3 class="ofcgrp srhead">${esc(title)}<span class="c muted">${rows.length}</span>${adm ? `<button type="button" class="btn sm ghost" data-ofc="new" data-kind="${k}">${ic('plus', 's')}<span>${tr('Add')}</span></button>` : ''}</h3><p class="muted ofchint">${esc(hint)}</p>`
      + (rows.length ? `<ul class="ofclist" role="list">${rows.map(r => ofcRowBtn(k, r, r.name_de, sub(r))).join('')}</ul>` : `<p class="muted lempty">${tr('Nothing here yet.')}</p>`);
  };
  return sec('roles', tr('Freelancer roles'), tr('Purchase price per day and hour; a service points to its role.'),
    r => [r.name_en, r.cost_day != null ? `${tr('Purchase')} ${day(r.cost_day)}` : '', r.cost_hour != null ? `${ofcMoney(r.cost_hour)}/${tr('h|unit')}` : ''].filter(Boolean).join(' · '))
    + sec('crew', tr('Crew'), tr('For the shoot calculation: daily rate for the client, internal or external.'),
      r => [r.name_en, day(r.rate_day), r.intext === 'intern' ? tr('internal') : tr('external'), r.markup_pct ? tr('{0} % markup', fmtNum(r.markup_pct, 1)) : ''].filter(Boolean).join(' · '));
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
// 2.40.0 (#1381): the choice shows the text in the field's language (lg); a block without English text says so
const ofcTextOpts = (kind, lg) => ofcRows('texts').filter(t => t.kind === kind && !t.archived).map(t => [t.id, (t.key ? t.key + ': ' : '') + (lg === 'en' ? (t.text_en ? t.text_en.slice(0, 70) : tr('(no English text)') + ' ' + (t.text_de || '').slice(0, 50)) : (t.text_de || t.text_en).slice(0, 70))]);
function ofcModal(kind, r) {
  const adm = ofcAdmin(), rate = v => v != null ? fmtNum(v, 2) : '';
  const titles = {services: [N_('New service'), N_('Edit service')], equipment: [N_('New device'), N_('Edit device')], sets: [N_('New set'), N_('Edit set')],
    texts: [N_('New text block'), N_('Edit text block')], contracts: [N_('New contract'), N_('Edit contract')],
    roles: [N_('New freelancer role'), N_('Edit freelancer role')], crew: [N_('New crew role'), N_('Edit crew role')]};  // 2.47.0 (#1649)
  let f = '';
  if (kind === 'services') {
    const cats = [...new Set(ofcRows('services').map(x => x.category).filter(Boolean))];
    f = ofcRowF('of-name_de', tr('Name (German)'), ofcIn('of-name_de', r?.name_de)) + ofcRowF('of-name_en', tr('Name (English)'), ofcIn('of-name_en', r?.name_en))
      + ofcRowF('of-category', tr('Category'), ofcIn('of-category', r?.category, {max: 80, list: 'of-cats', ph: tr('e.g. Video, Audio, Office')})) + `<datalist id="of-cats">${cats.map(c => `<option value="${esc(c)}">`).join('')}</datalist>`
      + ofcRowF('of-unit', tr('Unit'), ofcSel('of-unit', r?.unit || 'day', OFC_UNITS.map(([v, n]) => [v, tr(n)])))
      + ofcRowF('of-daily_rate', tr('Daily rate'), ofcIn('of-daily_rate', rate(r?.daily_rate), {num: true}), ofcCur()) + ofcRowF('of-hourly_rate', tr('Hourly rate'), ofcIn('of-hourly_rate', rate(r?.hourly_rate), {num: true}), ofcCur())
      + ofcRowF('of-tax', tr('VAT'), ofcSel('of-tax', r?.tax || 'standard', OFC_TAXES.map(([v, n]) => [v, `${tr(n)} (${ofcTax(v)})`])))
      + ofcChk('of-raw_fee', tr('Counts towards the raw data amount'), r?.raw_fee) + ofcChk('of-producing', tr('Counts towards the producing days'), r?.producing)  // 2.47.0 (#1645): always shown
      + ofcRowF('of-intext', tr('Internal / external'), ofcSel('of-intext', r?.intext || 'extern', [['extern', tr('external')], ['intern', tr('internal')], ['shooting', tr('Shoot')]]),
        r?.intext === 'shooting' ? tr('Only in the shoot calculation, never among the positions') : '')  // 2.47.0 (#1216)
      // 2.47.0 (#1649): the freelancer role (its purchase price is the default of a position); the old text role only while it holds a value
      + ofcRowF('of-role_id', tr('Freelancer role'), ofcSel('of-role_id', r?.role_id, ofcRows('roles').filter(x => !x.archived || x.id === r?.role_id).map(x => [x.id, x.name_de]), tr('none')))
      + (r?.role ? ofcRowF('of-role', tr('Role'), ofcIn('of-role', r.role, {max: 80})) : `<input type="hidden" id="of-role" value="">`) + ofcRowF('of-sort', tr('Order'), ofcIn('of-sort', r?.sort ?? '', {num: true}));
  } else if (kind === 'roles') {  // 2.47.0 (#1649): purchase prices only for admins (members do not get them)
    f = ofcRowF('of-name_de', tr('Name (German)'), ofcIn('of-name_de', r?.name_de)) + ofcRowF('of-name_en', tr('Name (English)'), ofcIn('of-name_en', r?.name_en))
      + (adm ? ofcRowF('of-cost_day', tr('Purchase per day'), ofcIn('of-cost_day', rate(r?.cost_day), {num: true}), ofcCur()) + ofcRowF('of-cost_hour', tr('Purchase per hour'), ofcIn('of-cost_hour', rate(r?.cost_hour), {num: true}), ofcCur()) : '')
      + ofcRowF('of-sort', tr('Order'), ofcIn('of-sort', r?.sort ?? '', {num: true}));
  } else if (kind === 'crew') {
    f = ofcRowF('of-name_de', tr('Name (German)'), ofcIn('of-name_de', r?.name_de)) + ofcRowF('of-name_en', tr('Name (English)'), ofcIn('of-name_en', r?.name_en))
      + ofcRowF('of-rate_day', tr('Daily rate'), ofcIn('of-rate_day', rate(r?.rate_day), {num: true}), ofcCur())
      + ofcRowF('of-intext', tr('Internal / external'), ofcSel('of-intext', r?.intext || 'extern', [['extern', tr('external')], ['intern', tr('internal')]]))
      + (adm ? ofcRowF('of-markup_pct', tr('Markup'), ofcIn('of-markup_pct', r?.markup_pct != null ? fmtNum(r.markup_pct, 1) : '', {num: true, ph: tr('optional')}), '%') : '')
      + ofcRowF('of-sort', tr('Order'), ofcIn('of-sort', r?.sort ?? '', {num: true}));
  } else if (kind === 'equipment') {
    const cats = [...new Set(ofcRows('equipment').map(x => x.category).filter(Boolean))];
    // 2.45.1 (#1556): German + English name, like a service
    f = ofcRowF('of-name', tr('Name (German)'), ofcIn('of-name', r?.name)) + ofcRowF('of-name_en', tr('Name (English)'), ofcIn('of-name_en', r?.name_en)) + ofcRowF('of-category', tr('Category'), ofcIn('of-category', r?.category, {max: 80, list: 'of-cats'})) + `<datalist id="of-cats">${cats.map(c => `<option value="${esc(c)}">`).join('')}</datalist>`
      + ofcRowF('of-daily_rate', tr('Daily rate'), ofcIn('of-daily_rate', rate(r?.daily_rate), {num: true}), ofcCur()) + astFields(r);  // 2.92.0 B (#1931)
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
    const cl = (typeof clientsOn === 'function' && clientsOn()) ? (S.clients || []).filter(c => !c.archived).map(c => [c.id, cdn_label(c)]) : [];
    const svc = ofcRows('services').filter(x => !x.archived);
    const rates = r?.rates || {};
    f = ofcRowF('of-name', tr('Name'), ofcIn('of-name', r?.name, {ph: tr('e.g. framework contract with Beispielkunde AG')}))
      + (cl.length ? ofcRowF('of-client_id', tr('Client'), ofcSel('of-client_id', r?.client_id, cl, tr('none'))) : '')
      + `<div class="row"><label id="of-datel">${tr('Date')}</label>${dateIn('of-date', r?.date || '', {label: tr('Date'), empty: tr('optional')})}</div>`
      + ofcChk('of-raw_included', tr('Raw data always included (no option line)'), r?.raw_included)  // 2.47.0 (#1645): always shown
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
  const close = fgModal(md);  // 2.40.0 (#1371): Cancel / Esc / backdrop ask before unsaved input is lost
  if (!adm) for (const el of $$('input,select,textarea,button[data-dpfor]', md)) el.disabled = true;
  if (kind === 'equipment') astBind(md, r);  // 2.92.0 B (#1931)
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    const m = b.dataset.m;
    if (m === 'close') { close(); return; }
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
      if (kind === 'services') Object.assign(body, {name_de: v('#of-name_de'), name_en: v('#of-name_en'), category: v('#of-category'), unit: v('#of-unit'), daily_rate: ofcNum(v('#of-daily_rate')), hourly_rate: ofcNum(v('#of-hourly_rate')), tax: v('#of-tax'), raw_fee: $('#of-raw_fee', md).checked ? 1 : 0, producing: $('#of-producing', md).checked ? 1 : 0, intext: v('#of-intext'), role: v('#of-role'), role_id: +v('#of-role_id') || null, sort: ofcNum(v('#of-sort')) ?? 0});
      else if (kind === 'roles') Object.assign(body, {name_de: v('#of-name_de'), name_en: v('#of-name_en'), cost_day: ofcNum(v('#of-cost_day')), cost_hour: ofcNum(v('#of-cost_hour')), sort: ofcNum(v('#of-sort')) ?? 0});  // 2.47.0 (#1649)
      else if (kind === 'crew') Object.assign(body, {name_de: v('#of-name_de'), name_en: v('#of-name_en'), rate_day: ofcNum(v('#of-rate_day')), intext: v('#of-intext'), markup_pct: ofcNum(v('#of-markup_pct')), sort: ofcNum(v('#of-sort')) ?? 0});
      else if (kind === 'equipment') Object.assign(body, {name: v('#of-name'), name_en: v('#of-name_en'), category: v('#of-category'), daily_rate: ofcNum(v('#of-daily_rate')), ...astBody(md)});
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
      md.remove(); ofcReload(kind);
      if (kind === 'equipment' && r && ofcAdmin()) astUndo(r, body); else toast(r ? tr('Saved') : tr('Added'));  // 2.92.0 B (#1931): one undo step
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
  return `<form class="ofcset" id="ofc-set" data-fg="ofc-set:${OFC.info.org_id}" autocomplete="off">
    <h3>${tr('Company')}</h3>
    ${ofcRowF('os-name', tr('Company name'), `<textarea id="os-name" rows="${Math.min(3, Math.max(1, String(cf.name || co.name || '').split('\n').length))}" maxlength="200" ${dis}>${esc(cf.name || co.name || '')}</textarea>`, tr('up to three lines; the letterhead and the footer print them one under the other'))}
    ${ofcCompanyFieldsHtml(cf, dis)}
    <details class="ofcfree"><summary>${tr('Free lines (used where the fields above are empty)')}</summary>
    ${ofcII('lines')}${ta('os-lines', tr('Address lines'), co.lines, tr('one line each: street, postcode and city'))}
    ${ta('os-contact', tr('Contact lines'), co.contact_lines, tr('phone, e-mail, website'))}
    ${ta('os-register', tr('Register lines'), co.register_lines, tr('legal form, register, managing director'))}
    ${ta('os-bank', tr('Bank lines'), co.bank_lines, tr('bank, IBAN, BIC; tax number / VAT id'))}</details>
    <div class="row"><label>${tr('Logo')}</label><span class="lacts">${logo}${adm ? `<input type="file" id="os-logo" accept="image/png,image/jpeg,image/webp" aria-label="${esc(tr('Upload logo'))}">${s.logo ? `<button type="button" class="btn sm" data-ofc="logo-del">${tr('Remove')}</button>` : ''}` : ''}</span><span class="muted ofchint">${tr('PNG at least 600 px wide (also JPEG or WebP, up to 4 MB)')}</span></div>
    ${ofcRowF('os-color', tr('Brand colour'), `<span class="lacts"><input id="os-color" value="${esc(s.color || '')}" maxlength="7" placeholder="#2f5d8a" class="numin" ${dis}><i class="ofcsw" style="background:${cssColor(s.color) || 'var(--accent)'}"></i></span>`, tr('accent in the printed documents; empty = the app’s accent colour'))}${ofcII('color')}
    <h3>${tr('Documents')}</h3>
    ${ofcRowF('os-lang', tr('Document language'), ofcSel('os-lang', s.lang, [['de', 'Deutsch'], ['en', 'English']]))}
    ${ofcRowF('os-currency', tr('Currency'), `<span class="lacts">${ofcSel('os-currency', s.currency, [['EUR', 'EUR'], ['USD', 'USD']])}<label for="os-fx" class="muted">${tr('1 € in USD')}</label><input id="os-fx" value="${esc(fmtNum(s.fx_usd, 4))}" inputmode="decimal" class="numin" ${dis}></span>`)}${ofcII('currency')}
    ${ofcSchemeHtml('os-scheme', 'offer', tr('Number scheme'), s.offer_scheme, dis)}
    ${ofcRowF('os-numat', tr('Quotation number'), ofcSel('os-numat', s.offer_number_at || 'create', [['create', tr('when the quotation is created')], ['finalize', tr('when it is finalised')]]))}${ofcII('numat')}
    ${ofcRowF('os-valid', tr('Quotation valid for'), `<span class="lacts"><input id="os-valid" value="${esc(String(s.offer_valid_days ?? 30))}" inputmode="numeric" class="numin" ${dis}><span class="muted">${tr('days')}</span></span>`)}${ofcII('valid')}
    <h3>${tr('Invoices')}</h3>
    ${ofcChk('os-small', tr('Small business: no VAT (section 19 UStG)'), s.small_business)}${typeof ux_info === 'function' ? ux_info('small_business') : ''}
    ${ofcSchemeHtml('os-inv-scheme', 'invoice', tr('Invoice numbers'), s.invoice_scheme, dis)}
    ${ofcSchemeHtml('os-cr-scheme', 'credit', tr('Credit note numbers'), s.credit_scheme, dis)}
    ${ofcSchemeHtml('os-rm-scheme', 'reminder', tr('Reminder numbers'), s.reminder_scheme, dis)}
    ${ofcRowF('os-paydays', tr('Payment terms'), `<span class="lacts"><input id="os-paydays" value="${esc(String(s.payment_days ?? 14))}" inputmode="numeric" class="numin" ${dis}><span class="muted">${tr('days')}</span></span>`, tr('a client\'s own payment terms win'))}${ofcII('paydays')}
    ${ofcRowF('os-rmfee', tr('Reminder fee'), `<span class="lacts"><input id="os-rmfee" value="${esc(fmtNum(s.reminder_fee ?? 0, 2))}" inputmode="decimal" class="numin" ${dis}><span class="muted">${ofcCur() === 'USD' ? '$' : '€'}</span></span>`)}${ofcII('rmfee')}
    ${ofcRowF('os-rmdays', tr('Payment deadline'), `<span class="lacts"><input id="os-rmdays" value="${esc(String(s.reminder_deadline_days ?? 10))}" inputmode="numeric" class="numin" ${dis}><span class="muted">${tr('days')}</span></span>`, tr('on reminders'))}${ofcII('rmdays')}
    ${typeof tpSettingsHtml === 'function' ? tpSettingsHtml(s, dis) : ''}
    ${ofcRowF('os-einv', tr('E-invoice format'), ofcSel('os-einv', s.einvoice_format || 'zugferd', [['zugferd', 'ZUGFeRD (PDF with XML)'], ['xrechnung', 'XRechnung (XML)']]), tr('clients with a buyer reference get XRechnung proposed'))}${ofcII('einv')}
    ${ofcRowF('os-datev', tr('DATEV inbox'), `<input id="os-datev" type="email" value="${esc(s.datev_email || '')}" maxlength="200" placeholder="${esc(tr('e-mail address of the document inbox'))}" ${dis}>`, tr('finalised invoices are mailed there as PDF + XML'))}${ofcII('datev')}
    ${ofcChk('os-datev-auto', tr('Send every invoice to the DATEV inbox when it is sent'), s.datev_auto)}${ofcII('datev_auto')}
    ${typeof dx_settingsHtml === 'function' ? dx_settingsHtml(s, dis) : ''}
    ${ofcRowF('os-inv-close-de', tr('Invoice closing (German)'), `<textarea id="os-inv-close-de" rows="2" maxlength="3000" placeholder="${esc(tr('empty = the standard text'))}" ${dis}>${esc(s.invoice_closing_de || '')}</textarea>`)}
    ${ofcRowF('os-inv-close-en', tr('Invoice closing (English)'), `<textarea id="os-inv-close-en" rows="2" maxlength="3000" placeholder="${esc(tr('empty = the standard text'))}" ${dis}>${esc(s.invoice_closing_en || '')}</textarea>`)}
    ${ofcRowF('os-rm-text-de', tr('Reminder closing (German)'), `<textarea id="os-rm-text-de" rows="2" maxlength="3000" placeholder="${esc(tr('empty = the standard text'))}" ${dis}>${esc(s.reminder_text_de || '')}</textarea>`)}
    ${ofcRowF('os-rm-text-en', tr('Reminder closing (English)'), `<textarea id="os-rm-text-en" rows="2" maxlength="3000" placeholder="${esc(tr('empty = the standard text'))}" ${dis}>${esc(s.reminder_text_en || '')}</textarea>`)}
    <h3>${tr('Calculation rules')}</h3>
    <p class="muted ofchint">${tr('Default for new quotations, can be changed in each quotation')}</p>
    ${ofcChk('os-prod-on', tr('Markup (producing) by production days'), s.producing_on)}
    <div class="ofcrule" data-rule="prod">
    ${ofcRowF('os-pq', tr('Producing quotient'), `<input id="os-pq" value="${esc(fmtNum(s.prod_quotient, 2))}" inputmode="decimal" class="numin" ${dis}>`, tr('producing days = production days ÷ quotient, rounded to half days'))}${ofcII('pq')}
    ${ofcRowF('os-ps', tr('Producing rate from'), ofcSel('os-ps', s.producing_service_id, svc, tr('fixed rate below')))}
    ${ofcRowF('os-pr', tr('Producing rate'), `<input id="os-pr" value="${esc(fmtNum(s.producing_rate, 2))}" inputmode="decimal" class="numin" ${dis}>`, `${ofcCur()} ${tr('per day')}`)}${ofcII('prod_rate')}
    </div>
    ${ofcChk('os-raw-on', tr('Raw data surcharge'), s.raw_on)}
    <div class="ofcrule" data-rule="raw">
    ${ofcRowF('os-rf', tr('Raw data factor'), `<input id="os-rf" value="${esc(fmtNum(s.raw_factor, 2))}" inputmode="decimal" class="numin" ${dis}>`, tr('raw data amount = sum of the raw data positions × factor'))}${ofcII('rf')}
    </div>
    ${typeof pkc_indHtml === 'function' ? pkc_indHtml(s, dis) : ofcChk('os-ind-film', tr('Industry pack Film & Video (shoot calculation in quotations)'), (s.industry_packs || []).includes('film')) + ofcII('indfilm')}
    <h3>${tr('Default texts')}</h3>
    ${ofcRowF('os-intro-de', tr('Introduction (German)'), ofcSel('os-intro-de', s.intro_text_id?.de, ofcTextOpts('intro'), tr('none')))}${ofcII('texts')}
    ${ofcRowF('os-intro-en', tr('Introduction (English)'), ofcSel('os-intro-en', s.intro_text_id?.en, ofcTextOpts('intro', 'en'), tr('none')))}
    ${ofcRowF('os-closing-de', tr('Closing (German)'), ofcSel('os-closing-de', s.closing_text_id?.de, ofcTextOpts('closing'), tr('none')))}
    ${ofcRowF('os-closing-en', tr('Closing (English)'), ofcSel('os-closing-en', s.closing_text_id?.en, ofcTextOpts('closing', 'en'), tr('none')))}
    ${ofcRowF('os-rt', tr('Rights: duration'), ofcSel('os-rt', s.rights_default?.time_id, ofcTextOpts('rights_time'), tr('none')))}${ofcII('rights')}
    ${ofcRowF('os-rr', tr('Rights: territory'), ofcSel('os-rr', s.rights_default?.territory_id, ofcTextOpts('rights_territory'), tr('none')))}
    ${ofcRowF('os-rm', tr('Rights: media'), ofcSel('os-rm', s.rights_default?.media_id, ofcTextOpts('rights_media'), tr('none')))}
    <h3>${tr('Country pack')}</h3>
    ${ofcRowF('os-pack', tr('Country pack'), `<span class="lacts">${ofcSel('os-pack', s.pack, (OFC.packs || [[p.code, p.name]]))}<span class="muted">${esc(tr('VAT: {0} standard, {1} reduced, {2} exempt', `${fmtNum(p.tax.standard, 1)} %`, `${fmtNum(p.tax.reduced, 1)} %`, `${fmtNum(p.tax.exempt, 1)} %`))}</span></span>`)}${ofcII('pack')}
    ${typeof oa_settingsHtml === 'function' ? oa_settingsHtml(s, dis) : ''}
    ${adm ? `<div class="foot stfoot"><span class="aerr" role="alert"></span><span class="spacer"></span><button type="submit" class="btn pri" data-ofc="save-settings">${tr('Save')}</button></div>` : ''}
    ${typeof pkc_html === 'function' ? pkc_html() : ''}
    <h3>${tr('Master data file')}</h3>
    <p class="muted">${tr('Export writes services, equipment, sets, text blocks, contracts and these settings into one JSON file; import reads such a file (also one made from a spreadsheet) and adds what is missing.')}</p>
    <div class="lacts"><a class="btn sm" href="/api/office/export" download="office-master-data.json">${ic('download', 's')} ${tr('Export')}</a>
      ${adm ? `<input type="file" id="os-import" accept="application/json,.json" hidden><button type="button" class="btn sm" data-ofc="import">${ic('upload', 's')} ${tr('Import')}</button><label class="chkl" data-fg-skip><input type="checkbox" id="os-overwrite"> ${tr('overwrite existing')}</label>` : ''}</div>
    ${adm ? `<h3>${tr('Import legacy data')}</h3><p class="muted">${tr('Clients, services and equipment from a spreadsheet; old invoices and quotations as an archive.')}</p><div class="lacts"><a class="btn sm" href="#office/import">${ic('upload', 's')} ${tr('Import legacy data')}</a></div>` : ''}
    ${adm ? `<h3>${tr('Access log')}</h3><p class="muted">${tr('Who opened, printed, changed or exported documents and master data of this organisation.')}</p>${ofcLogHtml()}` : ''}
    ${adm && OFC.info.personal && OFC.info.can_move ? `<h3>${tr('Move into an organisation')}</h3><p class="muted">${tr('Turns this personal office into a new organisation with you as its admin: documents, numbers, settings, master data and your private clients go with it. This cannot be undone.')}</p><div class="lacts"><button type="button" class="btn sm" data-ofc="pb-move">${ic('building', 's')} ${tr('Create organisation…')}</button></div>` : ''}
  </form>`;
}
// 2.47.3 (#1360): the personal office becomes a new organisation (one way: name, then a confirmation)
async function pb_move() {
  const name = ((await askPrompt(tr('Name of the new organisation'), (OFC.info?.settings?.company?.name || OFC.info?.company_fields?.name || '').split('\n').join(' '), {ok: tr('Next'), input: {max: 60}})) || '').trim();
  if (!name) return;
  if (!await askConfirm(tr('Move your personal office into “{0}”?', name), tr('Turns this personal office into a new organisation with you as its admin: documents, numbers, settings, master data and your private clients go with it. This cannot be undone.'), {ok: tr('Move'), danger: true})) return;
  try {
    const j = await api('POST', '/api/office/move', {name, confirm: true});
    await refreshMe(); S.workspaces = true; S.settings.workspace = 'org:' + j.org_id; LS.set('ws', S.settings.workspace);
    pb_reset(true); OFC.ws = typeof wsCur === 'function' ? wsCur() : ''; render();
    toast(tr('The organisation “{0}” now holds your office', j.name));
  } catch (x) { toast(x.message || tr('unknown')); }
}
// 2.36.2 (#1021 P4): the company as single fields (print lines are made from them; the free lines stay the fallback)
const OFC_CO_FIELDS = [['street', N_('Street'), 200], ['address_extra', N_('Address extra'), 200], ['zip', N_('Postcode'), 20],  // 2.99.0 D (#2188): + BT-36 ['city', N_('City'), 120], ['country', N_('Country'), 2],
  ['email', N_('E-mail'), 200], ['phone', N_('Phone'), 60], ['tax_number', N_('Tax number'), 40], ['vat_id', N_('VAT ID'), 20], ['bank_name', N_('Bank'), 120],
  ['iban', N_('IBAN'), 42], ['bic', N_('BIC'), 11], ['register_court', N_('Register court'), 120], ['register_no', N_('Register number'), 60],
  ['managing_directors', N_('Managing directors'), 300]];
function ofcCompanyFieldsHtml(cf, dis) {
  return `<div class="ofcco">${OFC_CO_FIELDS.map(([k, n, mx]) => ofcCoHint(k, k === 'country' ? ofcRowF('osc-country-q', tr(n), ctyField('osc-country', cf.country, {attrs: 'data-co="country"', dis, label: tr(n)})) : ofcRowF('osc-' + k, tr(n), `<input id="osc-${k}" data-co="${k}" value="${esc(cf[k] || '')}" maxlength="${mx}" ${k === 'country' ? 'class="numin" autocapitalize="characters"' : ''} ${dis}>`))).join('')}${ofcMdLabelHtml(cf, dis)}</div>`;
}
// 2.40.0 (#1377): the word printed before the management's names (Geschäftsführung, Gesellschafter, ...); the options show the
// German and English print word, the document's language picks one; '' = Geschäftsführung as before
const OFC_MD_LABELS = [['', 'Geschäftsführung', 'Managing directors'], ['shareholders', 'Gesellschafter', 'Shareholders'], ['owner_m', 'Inhaber', 'Owner'],
  ['owner_f', 'Inhaberin', 'Owner'], ['board', 'Vorstand', 'Executive board'], ['partners', 'Partner', 'Partners']];
const ofcMdLabelHtml = (cf, dis) => ofcRowF('osc-md_label', tr('Printed as'), `<select id="osc-md_label" data-co="md_label" ${dis}>${OFC_MD_LABELS.map(([v, de, en]) => `<option value="${v}" ${(cf.md_label || '') === v ? 'selected' : ''}>${esc(de)} · ${esc(en)}</option>`).join('')}</select>`)
  + `<div class="shint">${esc(tr('The word before the names in the footer of every document. Usual: GmbH, UG → Geschäftsführung; AG → Vorstand; GbR / eGbR → Gesellschafter; sole proprietor → Inhaber / Inhaberin; partnership company → Partner. eGbR, GmbH and UG also print the register court and number.'))}</div>`;
// 2.40.0 (#1382): the number schemes explained -- building blocks as buttons (inserted at the caret), a table behind (i),
// the next number of each scheme with its counter (restarts every year or never), errors in plain words from the server
const OFC_BB = [['{yyyy}', N_('Year'), '2026'], ['{yy}', N_('Year, short'), '26'], ['{seq:03}', N_('Running number, 3 digits'), '001'], ['{seq}', N_('Running number'), '1'],
  ['{project}', N_('Project'), 'Imagefilm'], ['{client}', N_('Client'), 'Beispiel-AG'], ['{date}', N_('Date'), '20261014'], ['{initials}', N_('Initials'), 'AB']];
OFC.pv = OFC.pv || {};
function ofcSchemeHtml(id, kind, label, val, dis) {
  const pv = OFC.pv[kind], cur = val || '';
  if (!pv || pv.scheme !== cur) setTimeout(() => { const el = $('#' + id); if (el && !OFC.pv[kind]?.busy) ofcSchemePv(el, true); }, 0);
  const pvText = pv && pv.scheme === cur ? pv.text : kind === 'offer' && OFC.info.number_preview ? tr('next: {0}', OFC.info.number_preview) : '';
  const table = tr('Building blocks of a number:') + '\n' + OFC_BB.map(([b, n, ex]) => `${b} = ${tr(n)} (${ex})`).join('\n') + '\n' + tr('Examples: RE-{yyyy}-{seq:03} gives RE-2026-001; {yyyy}-{seq:04} gives 2026-0001; R{yy}{seq:03} gives R26001.')
    + '\n' + tr('With a year in the scheme the counter starts again at 1 every year; without one it simply counts on.') + (kind === 'invoice' ? '\n' + tr('Invoices get their number only when they are finalised, one after the other without gaps.') : '');
  return ofcRowF(id, label, `<span class="lacts ofcscheme"><input id="${id}" data-scheme="${kind}" value="${esc(cur)}" maxlength="80" autocomplete="off" spellcheck="false" ${dis}><span class="muted ofcpv" id="${ofcPvId(id)}" aria-live="polite">${esc(pvText)}</span></span>`,
    kind === 'invoice' ? tr('the number comes only when the invoice is finalised; the series has no gaps') : '')
    + (dis ? '' : `<div class="ofcbb" role="group" aria-label="${esc(tr('Building blocks'))}">${OFC_BB.filter(x => x[0] !== '{seq}').map(([b, n]) => `<button type="button" class="btn sm" data-ofc="bb" data-for="${id}" data-bb="${b}" title="${esc(b)}">${esc(tr(n))}</button>`).join('')}</div>`)
    + `<div class="shint pl">${esc(table)}</div>`;
}
const ofcPvId = id => id === 'os-scheme' ? 'os-preview' : id + '-pv';  // (the quotation's preview keeps its id)
function ofcSchemePv(inp, now) {
  const kind = inp.dataset.scheme, v = inp.value;
  OFC.pv[kind] = {...(OFC.pv[kind] || {}), busy: true};
  clearTimeout(OFC['pvT' + kind]);
  OFC['pvT' + kind] = setTimeout(async () => {
    let text;
    try { const j = await api('GET', `/api/office/number-preview?kind=${kind}&scheme=${encodeURIComponent(v)}`);
      text = j.valid ? tr('next: {0}', j.preview) + ' · ' + (j.yearly ? tr('starts again every year') : tr('counts on without a restart')) : (j.error || tr('Invalid value: {0}', tr('Number scheme'))); }
    catch { text = ''; }
    OFC.pv[kind] = {scheme: v, text};
    const el = $('#' + ofcPvId(inp.id)); if (el) { el.textContent = text; el.classList.toggle('err', !!text && !text.startsWith(tr('next: {0}', '').trim())); }
  }, now ? 0 : 250);
}
// 2.40.0 (#1382): (i) explanations of the technical terms (one sentence + an example); shown behind the (i) of the row above
const OFC_II = {
  numat: N_('At once: the draft shows its number. When finalised: drafts have no number, so discarded drafts leave no gaps.'),
  paydays: N_('Payment terms: the days a client has to pay an invoice, printed as the due date (e.g. 14 days). A client\'s own payment terms win.'),
  rmdays: N_('Payment deadline: the new, shorter period a reminder gives, counted from its date (e.g. 10 days).'),
  einv: N_('ZUGFeRD is a normal PDF with the invoice data inside, fine for most clients. XRechnung is pure XML, required by public authorities (they give you a routing ID, the Leitweg-ID).'),
  datev: N_('The e-mail address of the document inbox your tax advisor gives you (DATEV Unternehmen online). Invoices sent there arrive in the accounting by themselves.'),
  pq: N_('Example: 6 production days with quotient 3 make 2 producing days, charged at the producing rate. A markup for organising the production.'),
  rf: N_('Example: positions with raw data add up to 2,000 €; factor 0.25 makes a raw data surcharge of 500 €, as an option or included (set per quotation).'),
  pack: N_('A country pack brings the VAT rates, the formats and the printed words and legal texts of one country.'),
  register_court: N_('From the commercial register, e.g. Amtsgericht Hamburg, HRB 12345. Needed for GmbH, UG, AG and eGbR; empty for sole proprietors and a GbR.'),
  vat_id: N_('VAT identification number (USt-IdNr.), e.g. DE123456789: needed on invoices to companies in other EU countries.'),
  tax_number: N_('The tax number from your tax office, e.g. 12/345/67890; printed when there is no VAT ID.'),
  cl_buyer_reference: N_('Public clients give you a routing ID (Leitweg-ID, e.g. 991-12345-67); companies sometimes an order or reference number. It is printed and goes into the e-invoice.'),
  cl_email_invoice: N_('Where invoices of this client are sent, e.g. the accounting department; empty = the client\'s normal e-mail.'),
  cl_payment_terms_days: N_('Days this client has to pay; empty = the payment terms of the settings.'),
};
// 2.47.3 (#1382): (i) texts for the remaining settings fields, the quotation/invoice editor (ed_*) and the client card
Object.assign(OFC_II, {
  currency: N_('The currency of your quotations and invoices. Rates stay in euros; for US dollars the exchange rate converts them (1.09 means 1 € = 1.09 $).'),
  color: N_('The colour of headings and lines in your printed documents, as a hex code, e.g. #2f5d8a.'),
  valid: N_('How long a quotation stays valid after its date; printed on it, e.g. 30 days.'),
  rmfee: N_('A flat fee added to every reminder for late payment, e.g. 5 €. 0 = no fee.'),
  prod_rate: N_('What one producing day costs: taken from a service of your price list, or a fixed amount (e.g. 600 € per day).'),
  rights: N_('Default usage rights printed in quotations: how long, where and in which media the client may use the result (e.g. 1 year, Germany, online).'),
  indfilm: N_('Adds the shoot calculation (shooting days, crew, equipment) to quotations. Only useful for film and video productions.'),
  lines: N_('Free text for letterhead and footer, only used where the single fields above are empty.'),
  datev_auto: N_('Every invoice you send by e-mail is also mailed to the DATEV inbox, so you need not forward it by hand.'),
  texts: N_('Introduction and closing are text blocks (tab Text blocks) that new quotations start with; each quotation can change them.'),
  small_business: N_('Under the small business rule (§ 19 UStG) you charge no VAT and print a note on your invoices instead. It applies only below the turnover limit; ask your tax advisor.'),
  cl_customer_no: N_('The customer number you give this client in your accounting (e.g. K-1042).'),
  ed_order_ref: N_('The client\'s own order number; printed on the invoice so their accounting can match it (e.g. PO-4711).'),
  ed_payment_days: N_('Days until the invoice is due, e.g. 14. Empty = the client\'s payment terms, else the ones from the settings.'),
  ed_vat_mode: N_('Without VAT is for reverse charge (a company in another EU country with a VAT ID) or customers outside the EU; a note on the invoice then says why.'),
  ed_contract_id: N_('A framework contract holds the special rates and standard rights agreed with one client (e.g. a yearly agreement); it presets new positions.'),
  ed_raw_mode: N_('Raw data = the unedited material. Optional: shown as an extra line, not counted. Included: counted in the total. None: no line.'),
  ed_reminder_level: N_('Level 1 is a friendly payment reminder, 2 a reminder, 3 the final reminder before further steps.'),
});
Object.assign(OFC_II, {ed_einvoice_format: OFC_II.einv, ed_raw_factor: OFC_II.rf, ed_prod_quotient: OFC_II.pq, ed_producing_rate: OFC_II.prod_rate,
  ed_reminder_deadline_days: OFC_II.rmdays, cl_vat_id: OFC_II.vat_id});
// (i) text of a field by key, for other parts of the office (e.g. the personal-office company fields, the client page)

const ofcII = k => OFC_II[k] ? `<div class="shint">${esc(tr(OFC_II[k]))}</div>` : '';
// (i) text of a field by key, for other parts of the office (personal-office company fields, client page)
const ux_info = k => ofcII(k);
const ofcCoHint = (k, row) => row + ofcII(k);
function ofcLogHtml() {
  if (!OFC.log) return `<button type="button" class="btn sm" data-ofc="log">${ic('clock', 's')} ${tr('Show the latest entries')}</button>`;
  if (!OFC.log.length) return `<p class="muted">${tr('No entries yet.')}</p>`;
  const tg = {doc: N_('Document'), settings: N_('Settings'), company: N_('Company'), logo: N_('Logo'), master_data: N_('Master data'), services: N_('Services'),
    equipment: N_('Equipment'), sets: N_('Sets'), texts: N_('Text blocks'), contracts: N_('Framework contracts'), legacy: N_('Legacy import'), archive: N_('Archive|documents'), datev: N_('DATEV export')};  // 2.47.3 (#1460): + datev
  if (typeof OA_LOG_TG === 'object') Object.assign(tg, OA_LOG_TG);  // 2.51.0 A (#1348): what agents read / drafted, the filter "Agents"
  const rows = OFC.logAg ? OFC.log.filter(x => /^agent_/.test(x.action)) : OFC.log;
  return (typeof oa_logFilter === 'function' ? oa_logFilter() : '') + `<ul class="ofdlog" role="list">${rows.map(x => `<li><span class="muted">${esc(typeof ofdWhen === 'function' ? ofdWhen(x.at) : x.at)}</span> <b>${esc(x.user_name || '?')}</b> ${esc(typeof ofdActText === 'function' ? ofdActText(x.action) : x.action)} · ${esc(tr(tg[x.target] || x.target))}${x.doc_id ? ` <a href="#office/offers/${x.doc_id}">#${x.doc_id}</a>` : ''}</li>`).join('')}</ul>`;
}
async function ofcSaveSettings(form) {
  const v = id => $(id, form)?.value ?? '', lines = id => v(id).split('\n').map(x => x.trim()).filter(Boolean);
  const cof = {name: v('#os-name')}; for (const [k] of OFC_CO_FIELDS) cof[k] = v('#osc-' + k).trim();
  if ($('#osc-md_label', form)) cof.md_label = v('#osc-md_label');  // 2.40.0 (#1377)
  const body = {company: {name: v('#os-name'), lines: lines('#os-lines'), contact_lines: lines('#os-contact'), register_lines: lines('#os-register'), bank_lines: lines('#os-bank')},
    company_fields: cof, offer_number_at: v('#os-numat') || 'create',
    color: v('#os-color').trim(), lang: v('#os-lang'), currency: v('#os-currency'), fx_usd: ofcNum(v('#os-fx')), offer_scheme: v('#os-scheme'), offer_valid_days: ofcNum(v('#os-valid')),
    prod_quotient: ofcNum(v('#os-pq')), producing_service_id: +v('#os-ps') || null, producing_rate: ofcNum(v('#os-pr')), raw_factor: ofcNum(v('#os-rf')),
    producing_on: $('#os-prod-on', form)?.checked ? 1 : 0, raw_on: $('#os-raw-on', form)?.checked ? 1 : 0,
    industry_packs: typeof pkc_indBody === 'function' ? pkc_indBody(form) : $('#os-ind-film', form)?.checked ? ['film'] : [],  // 2.47.0 (#1216), 2.76.0 (#1023): every os-ind-*
    intro_text_id: {de: +v('#os-intro-de') || null, en: +v('#os-intro-en') || null}, closing_text_id: {de: +v('#os-closing-de') || null, en: +v('#os-closing-en') || null},
    rights_default: {time_id: +v('#os-rt') || null, territory_id: +v('#os-rr') || null, media_id: +v('#os-rm') || null}, pack: v('#os-pack'),
    invoice_scheme: v('#os-inv-scheme'), credit_scheme: v('#os-cr-scheme'), reminder_scheme: v('#os-rm-scheme'), payment_days: ofcNum(v('#os-paydays')), reminder_fee: ofcNum(v('#os-rmfee')),
    reminder_deadline_days: ofcNum(v('#os-rmdays')), einvoice_format: v('#os-einv'), datev_email: v('#os-datev').trim(), datev_auto: $('#os-datev-auto', form)?.checked ? 1 : 0, small_business: $('#os-small', form)?.checked ? 1 : 0,
    invoice_closing_de: v('#os-inv-close-de'), invoice_closing_en: v('#os-inv-close-en'), reminder_text_de: v('#os-rm-text-de'), reminder_text_en: v('#os-rm-text-en')};
  if (typeof tpSettingsBody === 'function') Object.assign(body, tpSettingsBody(form));  // 2.47.0 (#1215)
  if (typeof dx_settingsBody === 'function') Object.assign(body, dx_settingsBody(form));  // 2.47.3 (#1460)
  if (typeof oa_settingsBody === 'function') Object.assign(body, oa_settingsBody(form));  // 2.51.0 A (#1348): agents_read
  try { const j = await api('PUT', '/api/office/settings', body); OFC.info.settings = j.settings; OFC.info.company_fields = j.company_fields || OFC.info.company_fields; OFC.info.number_preview = j.number_preview; OFC.log = null; fgDone(form.dataset.fg); toast(tr('Saved')); ofcDraw(); }
  catch (x) { const el = $('.aerr', form); if (el) el.textContent = x.message || ''; }
}
// 2.40.0 (#1378): one upload helper for the office (FormData + the CSRF header X-Requested-With via rawFetch, the server's error text)
const ofcUpload = (url, file) => { const fd = new FormData(); fd.append('file', file); return rawFetch('POST', url, fd); };
const ofcUpErr = x => x instanceof Offline ? tr('Offline: only works again with a connection') : (x?.message || tr('unknown'));
async function ofcLogoUpload(file) {
  if (!file) return;
  try { await ofcUpload('/api/office/logo', file); await ofcInfo(true); toast(tr('Logo saved')); }
  catch (x) { toast(ofcUpErr(x)); }
}
async function ofcImport(file, overwrite) {
  if (!file) return;
  if (!await importTargetConfirm({what: tr('the master data'), ws: ofcWs(), place: tr('Office')})) return;  // 2.87.9 (#1940)
  try {
    const j = await ofcUpload(`/api/office/import${overwrite ? '?overwrite=1' : ''}`, file);
    const c = j.counts || {}, n = Object.values(c).reduce((a, x) => a + (x && typeof x === 'object' ? (x.added || 0) + (x.updated || 0) : 0), 0);
    const um = Array.isArray(c.unmapped) ? c.unmapped.length : 0;
    toast(trn('Imported: {0} entry', 'Imported: {0} entries', n) + (um ? ' · ' + trn('{0} reference not found, left empty', '{0} references not found, left empty', um) : '')); ofcReload(); await ofcInfo(true);
  } catch (x) { toast(ofcUpErr(x)); }
}

// ---- events
document.addEventListener('click', async e => {
  const b = e.target.closest?.('[data-ofc]'); if (!b) return;
  const a = b.dataset.ofc;
  if (a === 'pb-move') { pb_move(); return; }  // 2.47.3 (#1360)
  if (a === 'pb-ws') { if (typeof wsSet === 'function') wsSet(b.dataset.ws); return; }  // 2.47.3 (#1360)
  if (a === 'new') { e.preventDefault(); ofcModal(b.dataset.kind, null); }
  else if (a === 'open') { e.preventDefault(); const r = ofcRow(b.dataset.kind, +b.dataset.id); if (r) ofcModal(b.dataset.kind, r); }
  else if (a === 'log-all' || a === 'log-ag') { e.preventDefault(); OFC.logAg = a === 'log-ag'; ofcDraw(); }  // 2.51.0 A (#1348)
  else if (a === 'import') { e.preventDefault(); const inp = $('#os-import'); if (inp) { inp.onchange = () => { ofcImport(inp.files[0], $('#os-overwrite')?.checked); inp.value = ''; }; inp.click(); } }
  else if (a === 'log') { e.preventDefault(); try { const j = await api('GET', '/api/office/log?limit=50'); OFC.log = j.log || []; } catch (x) { toast(x.message || ''); OFC.log = []; } ofcDraw(); }
  else if (a === 'bb') { e.preventDefault(); const inp = $('#' + b.dataset.for); if (!inp || inp.disabled) return;  // 2.40.0 (#1382): a building block at the caret
    const p0 = inp.selectionStart ?? inp.value.length, p1 = inp.selectionEnd ?? p0, t = b.dataset.bb;
    inp.value = inp.value.slice(0, p0) + t + inp.value.slice(p1); inp.focus(); inp.setSelectionRange(p0 + t.length, p0 + t.length); inp.dispatchEvent(new Event('input', {bubbles: true})); }
  else if (a === 'logo-del') { e.preventDefault(); try { await api('DELETE', '/api/office/logo'); await ofcInfo(true); toast(tr('Removed')); } catch (x) { toast(x.message || ''); } }
});
document.addEventListener('submit', e => { const f = e.target.closest?.('#ofc-set'); if (!f) return; e.preventDefault(); ofcSaveSettings(f); });
document.addEventListener('input', e => {
  const t = e.target;
  if (t.id === 'ofc-q') { OFC.q = t.value; ofcDraw(); }
  else if (t.id === 'os-color') { const sw = $('.ofcsw'); if (sw) sw.style.background = /^#[0-9a-fA-F]{6}$/.test(t.value.trim()) ? t.value.trim() : 'var(--accent)'; }
  else if (t.dataset?.scheme) ofcSchemePv(t);  // 2.40.0 (#1382): every number scheme with its preview
});
document.addEventListener('change', e => {
  const t = e.target;
  if (t.id === 'ofc-arch') { OFC.arch = t.checked; ofcDraw(); }
  else if (t.id === 'os-logo') { ofcLogoUpload(t.files[0]); t.value = ''; }
});
