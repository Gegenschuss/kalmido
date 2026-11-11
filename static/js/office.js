// Office & finance (2.36.1, #1021, module "office"): the view with its tabs -- quotations (office_docs.js), services,
// equipment + sets, text blocks, framework contracts, settings (company, logo, colour, language, currency, number scheme,
// producing / raw data rules, country pack, import / export of the master data). Everything belongs to the organisation
// one works in (the workspace switch); members read the master data, the organisation's admins edit it.
const OFC = {tab: '', data: {}, loading: {}, seq: 0, q: '', arch: false, info: null, infoErr: null, infoLoading: false};  // 2.577.0 (#4638): fromAll (2.543.0) gone, the address says the area (ofc_sp)
const OFC_TABS = [['offers', 'file', N_('Quotations')], ['invoices', 'receipt', N_('Invoices')], ['services', 'list', N_('Services')], ['equipment', 'camera', N_('Equipment')],
  ['texts', 'note', N_('Text blocks')], ['contracts', 'file', N_('Framework contracts')], ['settings', 'gear', N_('Settings')]];
const OFC_UNITS = [['day', N_('Day|unit')], ['hour', N_('Hour|unit')], ['piece', N_('Piece|unit')], ['minute', N_('Minute|unit')], ['flat', N_('Flat rate|unit')], ['percent', N_('Percent|unit')]];  // 2.47.0 (#1649): percent (KSK)
const OFC_TAXES = [['standard', N_('standard rate')], ['reduced', N_('reduced rate')], ['exempt', N_('exempt')]];
const OFC_TEXT_KINDS = [['rights_time', N_('Rights: duration')], ['rights_territory', N_('Rights: territory')], ['rights_media', N_('Rights: media')],
  ['intro', N_('Introduction')], ['closing', N_('Closing')], ['note', N_('Note|office')], ['block', N_('Text block between positions')], ['raw_note', N_('Raw data note')], ['letter', N_('Letters')]];  // 2.470.0 (#3596): letter: one sealed text, the same rows as the letters' text blocks
// 2.53.0 (#1410): officeOn lives in lazyload.js (asked at start, before the office is loaded)
// 2.143.0 A (#2151): the organisation role accounting reads the admins' bookkeeping too (the server refuses every change)
// 2.187.0 A (#2476): a person ruled by office groups: "admin" = the area of the shown tab allows it (an area that was the
// admins' before: view; the others: manage); everybody else exactly as before
const ofcAdmin = area => ofr_grp() ? ofr_admLike(area) : OFC.info?.role === 'admin' || OFC.info?.role === 'accounting' || ofr_legOwn(area);
// 2.187.0 A (#2476): the office rights (GET /api/office/settings rights); null = not ruled by groups (admins, a personal
// office's owner, members in "Previous access": the client behaves exactly as before)
const OFR_LVS = ['none', 'own', 'view', 'edit', 'manage'];
const ofr_grp = () => { const r = OFC.info?.rights; return r && r.levels && !r.legacy && r.manager !== 'admin' ? r : null; };
const ofr_area = tab => { const t = tab || OFC.tab || S.route.tab; const lv = OFC.info?.rights?.levels || {}; return t in lv ? t : ['import', 'rights'].includes(t) ? 'settings' : t === 'receipts' ? 'books' : t === 'invoices' ? 'offers' : null; };  // 2.380.0 B (#3409): invoices = the quotations' area  // 2.276.0 A (#3039): receipts = the bookkeeping's area
const ofr_lvOf = area => ofr_grp()?.levels?.[area || ''] || (ofr_legOwn(area) ? 'own' : 'none');
// 2.545.0 (#4592): a member in "Previous access" works on the level "own" in the travel expenses (server: rights.py LEGACY_OWN)
const ofr_legOwn = area => { const r = OFC.info?.rights, a = area || ofr_area(); return !!(r && r.legacy && a && r.levels?.[a] === 'own'); };
const ofr_admLike = area => { const a = area || ofr_area(); if (!a) return false; const lv = ofr_lvOf(a); return (OFC.info.rights.adm || []).includes(a) ? lv !== 'none' : lv === 'manage'; };
// may I (level of area, optional special: release / pay / lock / export)? Not ruled by groups = ofcAdmin() (the places
// that asked it before keep their answer). The server checks every route on its own
// a step that needs a special the group lacks (true only for a person ruled by groups): its button is hidden
const ofr_noSp = (area, special) => (!!ofr_grp() && !ofcCan(area, 'view', special)) || (!!special && ofr_legOwn(area));  // 2.545.0 (#4592): + level "own" of "Previous access" (no specials)
function ofcCan(area, level = 'view', special = '') {
  const r = ofr_grp(); if (!r) return ofr_legOwn(area) ? level === 'own' && !special : ofcAdmin();  // 2.545.0 (#4592)
  const lv = r.levels?.[area] || 'none';
  if (lv === 'none' || OFR_LVS.indexOf(lv) < OFR_LVS.indexOf(level)) return false;
  return !special || (r.specials || []).includes(special);
}
// 2.356.0 D (#3006, #3129): a person of an organisation's office without the bookkeeping (members, read-only, a group
// without it): one line why Bookkeeping, Cash book and Receipts are missing and -- when the person may hand in receipts
// (GET /api/office/settings submit) -- the way to "Submit receipt"; on a locked page instead of the dead end
const ofcNoBooks = () => !!OFC.info && !OFC.info.personal && !(ofr_grp() ? ofr_lvOf('books') !== 'none' : ['admin', 'accounting'].includes(OFC.info.role));
const ofcMemberHint = () => !ofcNoBooks() ? '' : `<p class="muted ofcmbr">${ic('lock', 's')}<span>${OFC.info.submit ? tr('Bookkeeping, cash book and receipts are only seen by admins and the bookkeeping. You hand in receipts with “Submit receipt”.') : tr('Bookkeeping, cash book and receipts are only seen by admins and the bookkeeping.')}</span>${OFC.info.submit ? `<a class="btn sm" href="#office/receipts" data-ofc-submit>${ic('upload', 's')}<span>${tr('Submit receipt')}</span></a>` : ''}</p>`;
const ofcLockedHtml = () => ofcNoBooks() ? `<div class="empty ofclocked">${ofcMemberHint()}</div>` : `<div class="empty">${tr('Only for admins of the office.')}</div>`;
// 2.147.0 (#2459, #2460): a function of the country pack is on (office_packs.js OCF_FEATS); unknown before the office is
// loaded = on (as before). The server checks the same on every route
const ofcFeat = k => !OFC.info?.features || OFC.info.features[k] !== false;
const pb_clOrg = () => OFC.info?.personal ? null : (OFC.info?.org_id || null);  // 2.47.3 (#1360): a personal office's clients are the private ones
const ofcWs = () => pb_clOrg() ? 'org:' + pb_clOrg() : 'private';  // 2.87.9 (#1940): the workspace of the shown office (importTargetConfirm)
// 2.380.0 B (#3409): the documents' two tabs (office_docs.js): quotations and invoices
const ofcDocTab = t => t === 'offers' || t === 'invoices';
const ofcTab = () => ofm_menuOff(S.route.tab) ? 'start' : OFC_TABS.some(t => t[0] === S.route.tab && (!t[6] || ofcFeat(t[6]))) ? S.route.tab : S.route.tab === 'import' ? 'settings'
  : S.route.tab === 'rights' ? 'settings'  // 2.187.0 A (#2476): the rights page sits under Settings
  : S.route.tab === 'start' || (!S.route.tab && isMobile()) ? 'start' : (OFC_TABS.some(t => t[0] === ofm_entry().key) ? ofm_entry().key : 'offers');  // 2.39.1 (#1182): the import page sits under Settings; 2.87.9 (#1917): the start page (phone without a tab)
// 2.147.0 (#2459): a tab with [6] = a function of the country pack that is off is no tab (a direct link opens the quotations)
// 2.440.0 (#3609): a point the office switched off opens the start page (viewOffice puts the address right)
// money / numbers of the master data: in the person's locale, the organisation's currency
// 2.189.0 (#2475): the home currency (price list, books, cash flow) and the short sign of a currency (office/homecur.py)
const ofcHome = () => OFC.info?.settings?.home_currency || 'EUR';
const ofcSym = cur => ({EUR: '€', USD: '$', GBP: '£'})[cur || ofcHome()] || cur || '';
const ofcCur = ofcHome;  // 2.189.0 (#2475): amounts of the office (rates, fees, books) are in the home currency
const ofcMoney = n => curMoney(n, ofcHome());  // 2.368.0 C (#2983): the sign where the locale puts it ("€1,234.50" in English)
// 2.50.1: thousands separators of the locale ("1.500,00", "1,500.00", "1.500") are read as such - a field filled with
// fmtNum(1500, 2) = "1.500" came back as 1.5 on save; a single separator without three digits after it stays the decimal one
// 2.263.0 (#2976): parseNum of core.js (a rate "0.856" was 856); frac = rate / factor with up to four decimals
const ofcNum = (v, frac) => parseNum(String(v ?? '').replace(/^[\s€$£¥]+|[\s€$£¥%]+$/g, ''), frac);
const ofcTax = k => { const t = OFC.info?.pack?.tax; const pct = t ? t[k] : null; return pct == null ? tr(OFC_TAXES.find(x => x[0] === k)?.[1] || k) : `${fmtNum(pct, 1)} %`; };

// ---- loading
async function ofcInfo(force) {
  if (OFC.infoLoading || OFC.pbWait) return;  // 2.47.3 (#1360): not while the new workspace is being saved
  if (OFC.info && !force) return;
  OFC.infoLoading = true;
  const ws = OFC.ws;  // 2.80.0 (#1842): an answer for the workspace before a switch is dropped and read again
  let info = null, err = null;
  try { info = await api('GET', '/api/office/settings'); }
  catch (x) { err = ofcErrHere(x); }
  OFC.infoLoading = false;
  if (OFC.ws !== ws) { ofcInfo(); return; }
  OFC.info = info; OFC.infoErr = err;
  if (info) ofcAreaHint();
  ofcDraw();
}
// 2.356.0 B (#2932): the first time the office shows another area than before (a switch, a new organisation), one hint
// which office this is; once per person (setting office_ws_hint), the last area per device
function ofcAreaHint() {
  const cur = ofcWs(), prev = LS.get('ofcArea', '');
  LS.set('ofcArea', cur);
  if (!prev || prev === cur || !wsOn() || S.settings?.office_ws_hint === '1') return;
  S.settings.office_ws_hint = '1';
  toast(tr('This office belongs to the workspace {0}. The switch at the top of the office changes the workspace.', wsName(cur)), null, 9000);
  api('PATCH', '/api/settings', {office_ws_hint: '1'}).catch(() => { /* the local copy holds until the next load */ });
}
// ---- 2.543.0 (#4606): "All workspaces" with more than one area (Private and an organisation, or more): the office shows the
// overview of the areas (areas.js spo_html, like Knowledge) instead of silently one office or "Choose a workspace". The server reads the office from the workspace
// setting, so a tap switches the workspace to that area (wsSet, the page stays) and its office opens; "All workspaces /" in
// its head switches back to the overview. A workspace chosen = as before.
// 2.577.0 (#4638): a tap opens the area's own address #office/s/<space> (like #workload/s/<space>) instead of switching the
// workspace: the area goes along with every office request (core.js ofc_spHdr), the workspace on top stays "All", the
// browser's Back and "All workspaces /" in the head lead to the overview again.
// 2.794.0 (#5392): only the workspaces whose office is on for me ("Also private" off = no Private here; an area / module I
// switched off per workspace too, areas.js wsa_wsOn / mc_wsOn)
const ofc_spaces = () => wsOptions().filter(w => w !== 'all' && wsa_wsOn(w, 'office') && mc_wsOn(w, 'office'));
const ofc_sp = () => { const sp = ofc_spOpen(); return sp && ofc_spaces().includes(sp) ? sp : ''; };  // the open area under "All" ('' = none / not mine)
const ofc_allOvr = () => wsOn() && wsCur() === 'all' && ofc_spaces().length > 1 && !ofc_sp();
const ofc_allUpHtml = () => ofc_sp() ? `<a href="#office" class="linkbtn ofcallup" data-ofcall="up">${esc(tr('All workspaces'))}</a><span class="abcsep" aria-hidden="true">/</span>` : '';
const ofc_wsKey = () => (typeof wsCur === 'function' ? wsCur() : '') + (ofc_sp() ? '>' + ofc_sp() : '');  // OFC.ws: the shown office (a workspace, or "All" + an area)
// the office's area in its header (Private / the organisation), with organisations the workspace switch itself
function ofcAreaHtml() {
  const ws = ofcWs(), nm = OFC.info.personal ? tr('Private|workspace') : (orgLabelOf(OFC.info.org_id) || wsName(ws));
  return wsOn() ? `<button type="button" class="wsbadge ofcws" data-act="ws-menu" aria-haspopup="menu" title="${esc(tr('Workspace: {0}', nm))}" aria-label="${esc(tr('Workspace: {0}', nm))}">${wsIcon(ws)}<span>${esc(nm)}</span></button>`
    : `<span class="ofcws">${esc(nm)}</span>`;
}
async function ofcLoad(kind, force) {
  if (!kind || ofcDocTab(kind) || kind === 'settings') return;
  if (OFC.loading[kind]) return;
  if (OFC.data[kind] && !force) return;
  OFC.loading[kind] = true;
  ++OFC.seq;
  try { const j = await api('GET', `/api/office/${kind}?archived=1`); OFC.data[kind] = j.items || []; }
  catch (x) { OFC.data[kind] = {error: ofcErrHere(x)}; }
  OFC.loading[kind] = false;
  ofcDraw();
}
function ofcDraw() { if ($('#s-biz')) biz_paint(); if (S.route.mod !== 'office') return; const el = $('#view'); if (el) keepFocus(el, () => ofcPaint(el)); ost_markBack(); }
// 2.122.2 (#2327): a reload of the same office view (save, archive switch, year) keeps the old content until the new data
// is there -- no short "Loading…" page that made the browser lose the scroll position -- and the scroll position stays.
// A view that is still loading after 4 s is drawn anyway (a part that never loads must not freeze the old page).
// A tap on the old content while it waits (its data is already gone) is held and repeated on the same button of the new
// content (2.122.2 CI: "Add receipt" / a pipeline card did nothing right after a save).
const OFCP = {key: null, t: 0, stale: false, replay: null};
function ofcPaint(el, force) {
  const key = [OFC.info?.org_id ?? '-', S.route.tab || '', S.route.id || ''].join('|');
  const html = mg_wrap('office', viewOffice()), same = OFCP.key === key && !!el.querySelector('.dash.office .ofcbody');
  const wait = `<p class="muted lempty">${tr('Loading…')}</p>`;
  if (!force && same && html.includes(wait) && ![...el.querySelectorAll('.dash.office .ofcbody p.lempty')].some(p => p.textContent === tr('Loading…'))) {
    if (!OFCP.t) OFCP.t = setTimeout(() => { OFCP.t = 0; if (S.route.mod === 'office') { const v = $('#view'); if (v) keepFocus(v, () => ofcPaint(v, true)); } }, 4000);
    OFCP.stale = true; return;
  }
  clearTimeout(OFCP.t); OFCP.t = 0; OFCP.stale = false;
  const top = el.scrollTop, btop = $('.ofbody', el)?.scrollTop || 0; setHtml(el, html); OFCP.key = key;
  if (same && el.scrollTop !== top) el.scrollTop = top;
  const ob = $('.ofbody', el); if (same && ob && btop && ob.scrollTop !== btop) ob.scrollTop = btop;  // 2.144.1 A (#2445): touch tablets scroll the page in .ofbody
  const r = OFCP.replay; OFCP.replay = null;
  if (r && same) { const b = el.querySelector(r); if (b) setTimeout(() => b.click(), 0); }
  ost_markBack();
}
document.addEventListener('click', e => {
  const v = $('#view'); if (!OFCP.stale || !v || !v.contains(e.target) || !v.querySelector('.dash.office')) return;
  let b = e.target; while (b && b !== v && ![...b.attributes].some(a => a.name.startsWith('data-'))) b = b.parentElement;
  if (!b || b === v) return;
  const sel = b.tagName.toLowerCase() + [...b.attributes].filter(a => a.name.startsWith('data-')).map(a => `[${a.name}="${CSS.escape(a.value)}"]`).join('');
  e.preventDefault(); e.stopPropagation(); OFCP.replay = sel;
}, true);
const ofcReload = kind => { if (kind) delete OFC.data[kind]; else OFC.data = {}; if (S.route.mod === 'office') ofcDraw(); };
const ofcRows = kind => Array.isArray(OFC.data[kind]) ? OFC.data[kind] : [];
const ofcRow = (kind, id) => ofcRows(kind).find(r => r.id === id);
// 2.460.0 (#3767): an own text in language lg: de / en in their columns, the others in r.trans[lg][base]; missing = English, then German
const ofcOwn = (r, base, lg, de = base + '_de', en = base + '_en') => (lg === 'de' ? r[de] || r[en] : (lg !== 'en' && r.trans?.[lg]?.[base]) || r[en] || r[de]) || '';
const ofcOwnGap = (r, base, lg, de = base + '_de', en = base + '_en') => lg === 'de' ? false : !(lg === 'en' ? r[en] : r.trans?.[lg]?.[base]) && !!(r[en] || r[de]);
const ofcText = (id, lg) => { const t = ofcRow('texts', id); return t ? ofcOwn(t, 'text', lg) : ''; };

// ---- the view
// 2.470.0 (#3596): the page office/settings is gone: an old link or bookmark opens Settings > Company & office over the office's
// start page and the address is replaced, so Back never lands on the jump again; a person without the settings gets "My rights"
function ofc_setJump() {
  if (OFC.jump) return;
  OFC.jump = true;
  setTimeout(() => {
    OFC.jump = false;
    if (S.route.mod !== 'office' || S.route.tab !== 'settings') return;
    if (ofr_grp() && ofr_lvOf('settings') === 'none') { location.replace('#office/rights'); return; }
    location.replace('#office/start');
    const sm = $('.smodal'); if (sm) { sm._noflush = true; sm.remove(); }
    settingsModal('biz');
  }, 0);
}
const ofc_setBody = () => S.route.tab === 'import' && typeof oimHtml === 'function' ? oimHtml() : `<p class="muted lempty">${tr('Loading…')}</p>`;
// 2.470.0 (#3596): the pages behind Settings (services, text blocks, rights) lead back there; was the tab row General | Templates
// 2.855.0 (#5456): the button names where it leads (Settings › Company & office [› Texts & templates]), not just "Settings"
const ofr_backHtml = tab => ofr_grp() && ofr_lvOf('settings') === 'none' ? '' : `<div class="ofcbar"><button type="button" class="btn sm" data-setgo="${tab === 'settings' ? 'biz' : 'biz-tpl'}">${ic('back', 's')} ${esc(tab === 'settings' ? tr('Settings › Company & office') : tr('Settings › Company & office › {0}', tr('Texts & templates')))}</button></div>`;
function viewOffice() {
  if (!officeOn()) return `<div class="empty">${setLinkHtml(tr('Office & finance is off (Settings > Modules)'))}</div>`;
  const tab = ofcTab();
  if (OFC.tab !== tab) { OFC.tab = tab; OFC.q = ''; }  // the search belongs to one tab
  if (tab === 'start' && ofm_menuOff(S.route.tab)) setTimeout(() => { if (ofm_menuOff(S.route.tab)) location.replace('#office/start'); }, 0);  // 2.440.0 (#3609)
  pb_wsFollow();
  if (ofc_allOvr()) return `<div class="dash office ofcall">${spo_html(sp => 'office/s/' + sp, ofc_spaces().map(w => [w, wsName(w), wsIcon(w)]))}</div>`;  // 2.543.0 (#4606); 2.577.0 (#4638): the area's own address
  if (!OFC.info && !OFC.infoErr && !OFC.infoLoading) setTimeout(ofcInfo, 0);
  // 2.87.9 (#1917): no tab row any more -- the office menu (areas.js ofm_menuHtml, via mg_wrap) leads to every tab
  if (OFC.info) ofm_admSeen(OFC.info.role === 'admin', OFC.info.rights, OFC.info.used, OFC.info.settings?.menu_off);  // 2.276.0 A (#3039): + used; 2.440.0 (#3609): + the points switched off
  if (OFC.info && !OFC.infoErr && S.route.tab === 'settings' && tab === 'settings') ofc_setJump();
  let body;
  if (OFC.infoErr) body = `<div class="empty nempty eact">${ic('building')}<span>${esc(OFC.infoErr)}</span><a class="btn" href="#settings">${tr('Settings')}</a></div>`;
  else if (!OFC.info) body = `<p class="muted lempty">${tr('Loading…')}</p>`;
  else if (tab === 'start') body = (pb_hintHtml() || '') + ofcMemberHint() + ofm_startHtml();  // 2.87.9 (#1917); 2.356.0 D (#3006): + the members' line
  else if (tab === 'settings' && (S.route.tab === 'rights' || (ofr_grp() && ofr_lvOf('settings') === 'none')) && typeof orr_html === 'function') body = orr_html();  // 2.187.0 A (#2476): the page "Rights" (a person without the settings: only "My rights")
  else if (ofr_grp() && ofr_area(tab) && ofr_lvOf(ofr_area(tab)) === 'none' && !(tab === 'receipts' && OFC.info.submit)) body = `<div class="empty">${ic('lock')}<span>${tr('Your office rights do not include this area')}</span>${ofcMemberHint()}</div>`;  // 2.356.0 D (#3006): + the way to hand in receipts  // 2.187.0 A (#2476): a direct link to a hidden area
  else if (pb_hintHtml()) body = pb_hintHtml() + (ofcDocTab(tab) ? '<div class="pboffers"></div>' : tab === 'settings' ? ofc_setBody() : typeof OFC_TABS.find(t => t[0] === tab)?.[4] === 'function' ? OFC_TABS.find(t => t[0] === tab)[4]() : ofcListHtml(tab));  // 2.47.3 (#1360); 2.92.0 A (#1925): tabs of their own module here too
  else if (ofcDocTab(tab) && ofcMemberHint()) body = ofcMemberHint() + '<div class="pboffers"></div>';  // 2.356.0 D (#3006): the desktop start of members
  else if (ofcDocTab(tab)) body = typeof ofdOffersTab === 'function' ? '' : `<div class="empty">${ic('receipt')}<span>${tr('Quotations arrive with the next step of this module.')}</span></div>`;
  else if (tab === 'settings') body = ofc_setBody();  // 2.39.1 (#1182): office/import
  else if (typeof OFC_TABS.find(t => t[0] === tab)?.[4] === 'function') body = OFC_TABS.find(t => t[0] === tab)[4]();  // 2.47.3 (B, #1022 #1652): tabs of their own module, [3] = admins only
  else body = ofcListHtml(tab);
  if (OFC.info && !OFC.infoErr && (['services', 'texts'].includes(tab) || S.route.tab === 'rights')) body = ofr_backHtml(tab) + body;  // 2.470.0 (#3596): the way back into Settings (was the tabs General | Templates)
  const och = OFC.info && !OFC.infoErr && typeof ocf_chooseHtml === 'function' ? ocf_chooseHtml() : '';  // 2.147.0 (#2462): the country of a new office
  if (och) body = och + (ofcDocTab(tab) && !body ? '<div class="pboffers"></div>' : body);  // (the quotations fill .pboffers below it)
  const ro = ['readonly', 'accounting'].includes(OFC.info?.role)  // 2.143.0 A (#2151): reads only (create / delete hidden in app.css)
    || (!!ofr_grp() && !!ofr_area(tab) && ['none', 'view'].includes(ofr_lvOf(ofr_area(tab))) && !(tab === 'receipts' && OFC.info?.submit));  // 2.356.0 D (#3129): hands in  // 2.187.0 A (#2476): the group's level of this area
  // 2.147.2 A (#2500): the role words here, not oinvRoleSel (settings module): a direct start of the office threw and stayed on "Loading…"
  const html = `<div class="dash office" data-ofctab="${tab}"${ro ? ' data-ofcro="1"' : ''}>${OFC.info && typeof tri_stripHtml === 'function' ? tri_stripHtml() : '' /* 2.417.0 C (#3445): the test mode strip */}<div class="ofchead">${OFC.info ? `${ofc_allUpHtml() /* 2.543.0 (#4606) */}${ofcAreaHtml()/* 2.356.0 B (#2932) */}<span class="muted ofcorg">${OFC.info.settings?.company?.name ? ` · ${esc(OFC.info.settings.company.name)}` : ''}${OFC.info.role === 'admin' ? ` · ${tr('Admin|role')}` : ro ? ` · ${esc(OFC.info.role === 'readonly' || ofr_grp() ? tr('Read-only') : tr('Accounting'))}` : ''}</span>` : ''}</div><div class="ofcbody"${ofcDocTab(tab) && !body ? ' data-fl-fill' : ''}>${body}</div></div>`;
  if (ofcDocTab(tab) && OFC.info && typeof ofdOffersTab === 'function') setTimeout(() => { const el = $('.office .ofcbody .pboffers') || $('.office .ofcbody'); if (el && ofcTab() === tab) ofdOffersTab(el); }, 0);  // 2.47.3 (#1360): below the hint
  return html;
}
// ---- 2.47.3 (#1360): the office follows the workspace switch ("Private" = the person's own office, an organisation's =
// its office). wsSet (workspace.js) calls pb_wsChanged(true) before saving the setting and pb_wsChanged(false) after it,
// so the office is read for the new workspace only once the server knows it; a switch on another device is caught here.
function pb_reset(nav) {
  OFC.info = null; OFC.infoErr = null; OFC.data = {};
  if (typeof OFD !== 'undefined') { OFD.list = null; OFD.doc = null; OFD.docId = null; OFD.log = null; OFD.flt = {client_id: '', project: '', year: ''}; }  // 2.351.0 F (#3312, review N7): + the filters (clients / projects of the other office)
  if (typeof OIM !== 'undefined') { OIM.list = null; OIM.runs = null; OIM.clients = null; }  // 2.80.0 (#1836): runs, counter and clients of the new workspace
  if (nav && S.route.mod === 'office' && S.route.id) setTimeout(() => go('office/' + (S.route.tab || 'offers')), 0);  // a document of the other area
}
function pb_wsFollow() {
  if (!S.me || !S.settings) return;
  const ws = ofc_wsKey();  // 2.577.0 (#4638): + the area open under "All"
  if (OFC.ws !== undefined && OFC.ws !== ws) pb_reset();
  OFC.ws = ws;
}
function pb_wsChanged(saving) {
  OFC.pbWait = !!saving;
  if (saving) { pb_reset(true); OFC.ws = ofc_wsKey(); }
  else ofcDraw();
}
// the empty personal office of a person with organisations points to the offices of these organisations
function pb_hintHtml() {
  const h = OFC.info?.personal ? OFC.info.org_offices || [] : [];
  if (!h.length) return '';
  return `<div class="pbhint shint keep">${ic('building', 's')}<div>${h.map(o => `<p>${esc(tr('The office of your organisation {0} is in the workspace {0}.', o.name))}</p>
    <button type="button" class="btn sm" data-ofc="pb-ws" data-ws="org:${o.id}">${esc(tr('Switch to {0}', o.name))}</button>`).join('')}
    <p class="muted">${esc(tr('This is your office in the workspace Private: its clients, documents and settings are yours alone.'))}</p></div></div>`;
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
  const adm = ofcAdmin();
  const bar = `<div class="ofcbar"><div class="ctsearch">${ic('search', 's')}<input id="ofc-q" type="search" value="${esc(OFC.q)}" placeholder="${esc(tr('Search'))}" aria-label="${esc(tr('Search'))}" autocomplete="off" enterkeyhint="search"></div>
    <label class="chkl"><input type="checkbox" id="ofc-arch" ${OFC.arch ? 'checked' : ''}> ${tr('Archived')}</label><span class="spacer"></span>
    ${adm ? `<button class="btn sm pri" data-ofc="new" data-kind="${kind}">${ic('plus', 's')}<span>${kind === 'services' ? tr('New service') : kind === 'equipment' ? tr('New device') : kind === 'texts' ? tr('New text block') : tr('New contract')}</span></button>` : ''}
    ${kind === 'services' && adm && d.length > 1 ? `<button class="btn sm" data-imr="renumber">${ic('sort', 's')}<span>${tr('Renumber')}</span></button>` : ''}
    ${kind === 'equipment' && adm ? `<button class="btn sm" data-ofc="new" data-kind="sets">${ic('plus', 's')}<span>${tr('New set')}</span></button>` : ''}</div>`;
  // 2.144.2 B (#1644): typing in the search redraws only the results (ofcListBody), never the field itself (Android lost it)
  return bar + `<div class="ofclistw" data-kind="${kind}">${ofcListBody(kind)}</div>`;
}
function ofcListBody(kind) {
  const d = OFC.data[kind]; if (!Array.isArray(d)) return '';
  const q = OFC.q.trim().toLowerCase();  // 2.298.0 A1 (#3186): the empty text is the same for members (no adm)
  const hit = r => !q || [r.name, r.name_de, r.name_en, r.category, r.key, r.text_de, r.text_en, r.note].some(v => (v || '').toLowerCase().includes(q));
  const rows = d.filter(r => hit(r) && (OFC.arch || !r.archived));
  let list;
  if (kind === 'services') list = ofcGrouped(rows, r => r.category || tr('No category'), r => ofcRowBtn('services', r, r.name_de, [r.name_en, r.unit === 'percent' && r.daily_rate != null ? `${fmtNum(r.daily_rate, 2)} %` : r.unit === 'hour' && r.hourly_rate != null ? `${ofcMoney(r.hourly_rate)}/${tr('h|unit')}` : r.daily_rate != null ? `${ofcMoney(r.daily_rate)}/${tr('Day|unit')}` : '', ofcTax(r.tax), r.raw_fee ? tr('raw data') : '', r.producing ? tr('producing') : '', r.intext === 'intern' ? tr('internal') : r.intext === 'shooting' ? tr('Shoot') : ''].filter(Boolean).join(' · ')));
  else if (kind === 'equipment') {
    list = ofcGrouped(rows, r => r.category || tr('No category'), r => ofcRowBtn('equipment', r, r.name, [r.name_en, r.daily_rate != null ? `${ofcMoney(r.daily_rate)}/${tr('Day|unit')}` : '', ...(typeof astRowInfo === 'function' ? astRowInfo(r) : [])].filter(Boolean).join(' · ')));  // 2.45.1 (#1556): + English name; 2.92.0 B (#1931): + value
    list = (typeof astSummaryHtml === 'function' ? astSummaryHtml(d) : '') + list;  // 2.92.0 B (#1931): sums + insurance list export (admins); 2.92.3: office_assets.js may still be loading (a redraw follows)
    const sets = ofcRows('sets').filter(r => hit(r) && (OFC.arch || !r.archived));
    list += `<h3 class="ofcgrp">${tr('Sets')}</h3>` + (sets.length ? `<ul class="ofclist" role="list">${sets.map(r => ofcRowBtn('sets', r, r.name, [trn('{0} device', '{0} devices', (r.items || []).length), r.discount_pct ? tr('{0} % discount', fmtNum(r.discount_pct, 1)) : ''].filter(Boolean).join(' · '))).join('')}</ul>` : `<p class="muted lempty">${tr('No sets yet. A set bundles devices with one discount.')}</p>`);
  } else if (kind === 'texts') list = ofcGrouped(rows, r => tr(OFC_TEXT_KINDS.find(k => k[0] === r.kind)?.[1] || r.kind), r => ofcRowBtn('texts', r, r.key ? (uiLang().slice(0, 2) === 'de' ? r.text_de || r.text_en : r.text_en || r.text_de) || r.key : (r.text_de || r.text_en).slice(0, 60), (r.text_de && !r.text_en && r.kind !== 'letter' ? tr('no English text stored') + ' · ' : '') + (r.key ? r.key : (r.text_en || '').slice(0, 80)))  /* 2.223.0 B (#2822): a keyed block shows its text as the title, the key small and grey below */, OFC_TEXT_KINDS.map(k => tr(k[1])));
  else list = rows.length ? `<ul class="ofclist" role="list">${rows.map(r => ofcRowBtn('contracts', r, r.name, [r.date ? fmtDateLoc(r.date) : '', r.raw_included ? tr('raw data included') : '', r.client_id && cdn_label((S.clients || []).find(c => c.id === r.client_id))].filter(Boolean).join(' · '), typeof dmaClip === 'function' ? dmaClip(r.files) : '')).join('')}</ul>` : '';
  if (!rows.length && !list) list = `<div class="empty nempty eact">${ic(kind === 'texts' ? 'note' : 'list')}<span>${q ? tr('Nothing matches.') : kind === 'services' ? tr('No services yet.') : kind === 'equipment' ? tr('No equipment yet.') : tr('Nothing here yet.')}</span></div>`;
  if (!q && (kind === 'services' || kind === 'equipment')) list += oim_link('master', !rows.length);  // 2.122.3 A (#2335)
  return list + (kind === 'services' ? sr_roleSections(hit) : '');  // 2.47.0 (#1649)
}
// 2.47.0 (#1649): the masters Freelancer-Rollen (purchase price per day / hour, a service points to its role) and
// Drehpersonal (for the shoot calculation) below the services, like the sets below the equipment. Members get no prices.
function sr_roleSections(hit) {
  for (const k of ['roles', 'crew']) if (!OFC.data[k] && !OFC.loading[k]) setTimeout(() => ofcLoad(k), 0);
  const adm = ofcAdmin('equipment'), day = v => v != null ? `${ofcMoney(v)}/${tr('Day|unit')}` : ''; // 2.187.1 A (#2735): roles / crew belong to the equipment area
  const sec = (k, title, hint, sub) => {
    const rows = ofcRows(k).filter(r => hit(r) && (OFC.arch || !r.archived));
    return `<h3 class="ofcgrp srhead">${esc(title)}<span class="c muted">${rows.length}</span>${adm ? `<button type="button" class="btn sm ghost" data-ofc="new" data-kind="${k}">${ic('plus', 's')}<span>${tr('Add')}</span></button>` : ''}</h3><p class="shint">${esc(hint)}</p>`
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
const ofcRowBtn = (kind, r, title, sub, extra = '') => `<li><button type="button" class="ofcrow ${r.archived ? 'arch' : ''}" data-ofc="open" data-kind="${kind}" data-id="${r.id}"><span class="ofcn"><b>${esc(title)}</b>${sub ? `<small class="muted">${esc(sub)}</small>` : ''}</span>${extra}${r.archived ? `<span class="rotag">${ic('archive', 's')}${tr('Archived')}</span>` : ''}${ic('right', 's')}</button></li>`;  // 2.117.0 B (#2285): extra = the paper clip of a contract

// ---- the dialogs (one per kind; members get a read-only view)
const ofcSel = (id, cur, opts, empty, label) => `<select id="${id}"${label ? ` aria-label="${esc(label)}"` : ''}>${empty != null ? `<option value="">${esc(empty)}</option>` : ''}${opts.map(([v, n]) => `<option value="${esc(v)}" ${String(v) === String(cur ?? '') ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select>`;
// 2.593.0 (#4891): the years of a year picker of the office from the data, newest first: from the oldest year with data
// (yr = the server's years {min, max}, null: no data) up to this year without gaps, later years only when data lies there;
// back = years before this one shown even without data (books: the annual return of last year); sel = the chosen year stays
// a choice even outside the span (a jump to an imported year)
const ofcYearOpts = (yr, sel, back = 0) => {
  const now = new Date().getFullYear(), lo = Math.max(1900, Math.min(now - back, +yr?.min || now)), hi = Math.min(9999, Math.max(now, +yr?.max || now)), out = [];
  for (let y = hi; y >= lo; y--) out.push(String(y));
  const s = String(sel ?? '');
  if (/^\d{4}$/.test(s) && !out.includes(s)) { out.push(s); out.sort((a, b) => b - a); }
  return out;
};
const ofcIn = (id, v, o = {}) => `<input id="${id}" value="${esc(v ?? '')}" maxlength="${o.max || 200}" ${o.num ? 'inputmode="decimal" class="numin"' : ''} ${o.ph ? `placeholder="${esc(o.ph)}"` : ''} ${o.list ? `list="${o.list}"` : ''}>`;
// 2.298.0 A1 (#3186): the help of a field is a .shint: infoize() puts it behind the (i) of the label; o.keep = it stays
// visible under the field (only follow-ups, one-way steps, a state - and units like % or the currency)
const ofcHint = (hint, o) => hint ? `<div class="shint${o?.keep ? ' keep' : ''}">${esc(hint)}</div>` : '';
const ofcRowF = (id, label, field, hint, o) => `<div class="row"><label for="${id}">${esc(label)}</label>${field}${ofcHint(hint, o)}</div>`;
const imr_cur = () => `<span class="muted imrcur">${esc(ofcCur())}</span>`;  // 2.138.0 E (#2237)
// 2.489.0 (#2652): the project of a trip / drive: a choice of the real projects the person may see (server: travel.py
// rk_real_projects) and "Free text" as the fallback (the suggestions of the datalist sugg); the value stays
// the project's name as text. An old text that is no project's name shows as "Free text" with that text.
function ofcProjSel(id, label, val, projs, sugg) {
  const ns = (projs || []).map(p => p.name), cur = val || '', other = !!cur && !ns.includes(cur);
  return `<div class="row"><label for="${id}">${esc(label)}</label><select id="${id}" data-ofcproj="${id}"><option value="">${esc(tr('none'))}</option>${ns.map(n => `<option value="${esc(n)}" ${n === cur ? 'selected' : ''}>${esc(n)}</option>`).join('')}<option value="__other" ${other ? 'selected' : ''}>${esc(tr('Free text'))}</option></select></div>
    <div class="row ${other ? '' : 'hidden'}" id="${id}-r"><label for="${id}-t">${esc(tr('Free text'))}</label>${ofcIn(id + '-t', other ? cur : '', {list: id + '-l'})}<datalist id="${id}-l">${(sugg || []).map(p => `<option value="${esc(p)}">`).join('')}</datalist></div>`;
}
const ofcProjVal = (md, id) => { const v = $('#' + id, md)?.value || ''; return v === '__other' ? ($('#' + id + '-t', md)?.value || '').trim() : v; };
document.addEventListener('change', e => {
  const s = /** @type {any} */ (e.target).closest?.('[data-ofcproj]'); if (!s) return;
  const r = document.getElementById(s.id + '-r'), on = s.value === '__other'; r?.classList.toggle('hidden', !on); if (on) document.getElementById(s.id + '-t')?.focus();
});
const ofcChk = (id, label, on) => `<div class="row"><label class="chkl" style="min-width:0"><input type="checkbox" id="${id}" ${on ? 'checked' : ''}> ${esc(label)}</label></div>`;
// 2.40.0 (#1381): the choice shows the text in the field's language (lg); a block without English text says so
const ofcTextOpts = (kind, lg = 'de') => ofcRows('texts').filter(t => t.kind === kind && !t.archived).map(t => { const gap = ofcOwnGap(t, 'text', lg); return [t.id, (t.key ? t.key + ': ' : '') + (gap ? (lg === 'en' ? tr('(no English text)') : tr('(no text in this language)')) + ' ' : '') + ofcOwn(t, 'text', lg).slice(0, gap ? 50 : 70)]; });
// 2.460.0 (#3767): one tab per language over the own texts of a form. fields: [{base, label, id: lg => input id, val: lg => value, rows, max, ph}]
const ofcLangList = () => { const L = (S.languages || []).map(x => [x.code, x.name]); return L.length ? L : [['de', 'Deutsch'], ['en', 'English']]; };
function ofcLangTabs(fields, o = {}) {
  const ls = ofcLangList(), dis = o.dis || '';
  const inp = (x, lg) => { const id = x.id(lg), ph = x.ph ? ` placeholder="${esc(x.ph)}"` : '', tr_ = ['de', 'en'].includes(lg) ? '' : ` data-tr="${esc(x.base)}" data-lg="${lg}"`;
    return ofcRowF(id, x.label, x.rows ? `<textarea id="${id}" rows="${x.rows}" maxlength="${x.max || 8000}"${ph}${tr_} ${dis}>${esc(x.val(lg) || '')}</textarea>` : `<input id="${id}" value="${esc(x.val(lg) || '')}" maxlength="${x.max || 200}"${ph}${tr_} ${dis}>`); };
  return `<div class="ofclts"><div class="seg" role="tablist" aria-label="${esc(tr('Language'))}">${ls.map(([lg, n], i) => `<button type="button" role="tab" data-lt="${lg}" aria-selected="${i ? 'false' : 'true'}" class="${i ? '' : 'on'}${fields.some(x => x.val(lg)) ? ' ltfill' : ''}">${esc(n)}</button>`).join('')}</div>
    ${ls.map(([lg], i) => `<div data-ltp="${lg}" role="tabpanel"${i ? ' hidden' : ''}>${fields.map(x => inp(x, lg)).join('')}</div>`).join('')}</div>`;
}
// 2.525.0 (#4281): one-meaning guard: data-lt - inside .ofclts only (the language tabs)
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-lt]'), box = b?.closest('.ofclts');
  if (!box) return;
  for (const x of $$('[data-lt]', box)) { const on = x === b; x.classList.toggle('on', on); x.setAttribute('aria-selected', on ? 'true' : 'false'); }
  for (const p of $$('[data-ltp]', box)) p.hidden = p.dataset.ltp !== b.dataset.lt;
});
const ofcTrField = (r, base, de, en, o) => ({base, id: lg => lg === 'de' ? 'of-' + de : lg === 'en' ? 'of-' + en : `of-tr-${base}-${lg}`, val: lg => lg === 'de' ? r?.[de] : lg === 'en' ? r?.[en] : r?.trans?.[lg]?.[base], ...o});
const ofcTransBody = md => { const t = {}; for (const el of $$('[data-tr]', md)) (t[el.dataset.lg] ||= {})[el.dataset.tr] = el.value; return t; };
// 2.460.0 (#3767): the office's own closing texts, one tab per language
const OST_CLOSE = [['inv', 'invoice_closing', N_('Invoice closing')], ['dl', 'delivery_closing', N_('Delivery note closing')], ['rm', 'reminder_text', N_('Payment reminder closing')]];
const ost_closeId = (k, lg) => `os-${k}-${k === 'rm' ? 'text' : 'close'}-${lg}`;
const ofcClosingTabs = (s, dis) => ofcLangTabs(OST_CLOSE.filter(([k]) => k !== 'dl' || ofcFeat('docs.delivery')).map(([k, key, n]) => ({base: key, label: tr(n), id: lg => ost_closeId(k, lg), val: lg => s[`${key}_${lg}`], rows: 2, max: 3000, ph: tr('empty = the default text')})), {dis});
function ofcModal(kind, r) {
  // 2.451.0 (#3809): the service dialog waits for the roles: built before them its choice read "none" and Save wiped the role
  if (kind === 'services' && !OFC.data.roles) {
    if (!OFC.modalWait) { OFC.modalWait = true; (async () => { for (let i = 0; i < 60 && !OFC.data.roles; i++) { if (!OFC.loading.roles) ofcLoad('roles'); await sleep(150); } OFC.modalWait = false; if (!OFC.data.roles) OFC.data.roles = {error: tr('unknown')}; ofcModal(kind, r); })(); }
    return;
  }
  const adm = ofcAdmin(['roles', 'crew', 'sets'].includes(kind) ? 'equipment' : undefined), rate = v => v != null ? fmtNum(v, 2) : '';  // 2.187.1 A (#2735): roles / crew / sets = equipment area
  const titles = {services: [N_('New service'), N_('Edit service')], equipment: [N_('New device'), N_('Edit device')], sets: [N_('New set'), N_('Edit set')],
    texts: [N_('New text block'), N_('Edit text block')], contracts: [N_('New contract'), N_('Edit contract')],
    roles: [N_('New freelancer role'), N_('Edit freelancer role')], crew: [N_('New crew role'), N_('Edit crew role')]};  // 2.47.0 (#1649)
  let f = '';
  if (kind === 'services') {
    const cats = [...new Set(ofcRows('services').map(x => x.category).filter(Boolean))];
    f = ofcLangTabs([ofcTrField(r, 'name', 'name_de', 'name_en', {label: tr('Name')})])
      + ofcRowF('of-category', tr('Category'), ofcIn('of-category', r?.category, {max: 80, list: 'of-cats', ph: tr('e.g. Video, Audio, Office')})) + `<datalist id="of-cats">${cats.map(c => `<option value="${esc(c)}">`).join('')}</datalist>`
      + ofcRowF('of-unit', tr('Unit'), ofcSel('of-unit', r?.unit || 'day', OFC_UNITS.map(([v, n]) => [v, tr(n)])))
      // 2.138.0 E (#2237): the currency beside the field, not below it
      + ofcRowF('of-daily_rate', tr('Daily rate'), ofcIn('of-daily_rate', rate(r?.daily_rate), {num: true}) + imr_cur()) + ofcRowF('of-hourly_rate', tr('Hourly rate'), ofcIn('of-hourly_rate', rate(r?.hourly_rate), {num: true}) + imr_cur())
      + ofcRowF('of-tax', tr('VAT'), ofcSel('of-tax', r?.tax || 'standard', OFC_TAXES.map(([v, n]) => [v, `${tr(n)} (${ofcTax(v)})`])))
      + ofcChk('of-raw_fee', tr('Counts towards the raw data amount'), r?.raw_fee) + ofcChk('of-producing', tr('Counts towards the producing days'), r?.producing)  // 2.47.0 (#1645): always shown
      + ofcRowF('of-intext', tr('Internal / external'), ofcSel('of-intext', r?.intext || 'extern', [['extern', tr('external')], ['intern', tr('internal')], ['shooting', tr('Shoot')]]),
        r?.intext === 'shooting' ? tr('Only in the shoot calculation, never among the positions') : '', {keep: 1})  // 2.47.0 (#1216)
      // 2.47.0 (#1649): the freelancer role (its purchase price is the default of a position); the old text role only while it holds a value
      + ofcRowF('of-role_id', tr('Freelancer role'), ofcSel('of-role_id', r?.role_id, ofcRows('roles').filter(x => !x.archived || x.id === r?.role_id).map(x => [x.id, x.name_de]), tr('none')))
      + (r?.role ? ofcRowF('of-role', tr('Role'), ofcIn('of-role', r.role, {max: 80})) : `<input type="hidden" id="of-role" value="">`) + ofcRowF('of-sort', tr('Order'), ofcIn('of-sort', r?.sort ?? '', {num: true}));
  } else if (kind === 'roles') {  // 2.47.0 (#1649): purchase prices only for admins (members do not get them)
    f = ofcLangTabs([ofcTrField(r, 'name', 'name_de', 'name_en', {label: tr('Name')})])
      + (adm ? ofcRowF('of-cost_day', tr('Purchase per day'), ofcIn('of-cost_day', rate(r?.cost_day), {num: true}), ofcCur(), {keep: 1}) + ofcRowF('of-cost_hour', tr('Purchase per hour'), ofcIn('of-cost_hour', rate(r?.cost_hour), {num: true}), ofcCur(), {keep: 1}) : '')
      + ofcRowF('of-sort', tr('Order'), ofcIn('of-sort', r?.sort ?? '', {num: true}));
  } else if (kind === 'crew') {
    f = ofcLangTabs([ofcTrField(r, 'name', 'name_de', 'name_en', {label: tr('Name')})])
      + ofcRowF('of-rate_day', tr('Daily rate'), ofcIn('of-rate_day', rate(r?.rate_day), {num: true}), ofcCur(), {keep: 1})
      + ofcRowF('of-intext', tr('Internal / external'), ofcSel('of-intext', r?.intext || 'extern', [['extern', tr('external')], ['intern', tr('internal')]]))
      + (adm ? ofcRowF('of-markup_pct', tr('Markup'), ofcIn('of-markup_pct', r?.markup_pct != null ? fmtNum(r.markup_pct, 1) : '', {num: true, ph: tr('optional')}), '%') : '')
      + ofcRowF('of-sort', tr('Order'), ofcIn('of-sort', r?.sort ?? '', {num: true}));
  } else if (kind === 'equipment') {
    const cats = [...new Set(ofcRows('equipment').map(x => x.category).filter(Boolean))];
    // 2.45.1 (#1556): German + English name, like a service
    f = ofcLangTabs([ofcTrField(r, 'name', 'name', 'name_en', {label: tr('Name')})]) + ofcRowF('of-category', tr('Category'), ofcIn('of-category', r?.category, {max: 80, list: 'of-cats'})) + `<datalist id="of-cats">${cats.map(c => `<option value="${esc(c)}">`).join('')}</datalist>`
      + ofcRowF('of-daily_rate', tr('Daily rate'), ofcIn('of-daily_rate', rate(r?.daily_rate), {num: true}), ofcCur(), {keep: 1}) + astFields(r);  // 2.92.0 B (#1931)
  } else if (kind === 'sets') {
    const eq = ofcRows('equipment').filter(x => !x.archived).map(x => [x.id, x.name]);
    const items = (r?.items || []);
    f = ofcRowF('of-name', tr('Name'), ofcIn('of-name', r?.name)) + ofcRowF('of-discount_pct', tr('Discount'), ofcIn('of-discount_pct', r?.discount_pct != null ? fmtNum(r.discount_pct, 1) : '', {num: true}), '%', {keep: 1})
      + `<div class="row"><label>${tr('Devices')}</label></div><div id="of-items" class="ofcitems">${items.map(it => ofcSetItemHtml(eq, it)).join('')}</div>${adm ? `<button type="button" class="btn sm" data-m="add-item">${ic('plus', 's')} ${tr('Add device')}</button>` : ''}`;
  } else if (kind === 'texts') {
    // 2.470.0 (#3596): a letter block stays one (the server refuses a change of kind), the kind only for people with the correspondence; one text, in its own language
    const ltr = r?.kind === 'letter', lv = ofm_lv(), kinds = OFC_TEXT_KINDS.filter(([v]) => (v === 'letter') === ltr || (!r && v === 'letter' && (!lv || ['edit', 'manage'].includes(lv.letters))));
    f = ofcRowF('of-kind', tr('Kind'), ofcSel('of-kind', r?.kind || 'block', kinds.map(([v, n]) => [v, tr(n)]))) + ofcRowF('of-key', ltr ? tr('Name') : tr('Short name'), ofcIn('of-key', r?.key, {max: ltr ? 120 : 80, ph: ltr ? '' : tr('optional')}))
      + (ltr ? `<div class="row"><label for="of-text_de">${tr('Text')}</label><textarea id="of-text_de" rows="4" maxlength="20000">${esc(r?.text_de || '')}</textarea></div><input type="hidden" id="of-text_en" value="">` : ofcLangTabs([ofcTrField(r, 'text', 'text_de', 'text_en', {label: tr('Text'), rows: 4})])) + ofcRowF('of-sort', tr('Order'), ofcIn('of-sort', r?.sort ?? '', {num: true}));
  } else if (kind === 'contracts') {
    const cl = (typeof clientsOn === 'function' && clientsOn()) ? (S.clients || []).filter(c => !c.archived).map(c => [c.id, cdn_label(c)]) : [];
    const svc = ofcRows('services').filter(x => !x.archived);
    const rates = r?.rates || {};
    f = ofcRowF('of-name', tr('Name'), ofcIn('of-name', r?.name, {ph: tr('e.g. framework contract with Beispielkunde AG')}))
      + (cl.length ? ofcRowF('of-client_id', tr('Client'), ofcSel('of-client_id', r?.client_id, cl, tr('none'))) : '')
      + `<div class="row"><label id="of-datel">${tr('Date')}</label>${dateIn('of-date', r?.date || '', {label: tr('Date'), empty: tr('optional')})}</div>`
      + (typeof dmaRowHtml === 'function' ? dmaRowHtml(r) : '')  // 2.117.0 B (#2285): the contract's PDF files, right under its date
      + ofcChk('of-raw_included', tr('Raw data always included (no option line)'), r?.raw_included)  // 2.47.0 (#1645): always shown
      + ofcRowF('of-rights_time_id', tr('Rights: duration'), ofcSel('of-rights_time_id', r?.rights_time_id, ofcTextOpts('rights_time'), tr('none')))
      + ofcRowF('of-rights_territory_id', tr('Rights: territory'), ofcSel('of-rights_territory_id', r?.rights_territory_id, ofcTextOpts('rights_territory'), tr('none')))
      + ofcRowF('of-rights_media_id', tr('Rights: media'), ofcSel('of-rights_media_id', r?.rights_media_id, ofcTextOpts('rights_media'), tr('none')))
      + ofcLangTabs([ofcTrField(r, 'rights_note', 'rights_note_de', 'rights_note_en', {label: tr('Rights note'), rows: 2}), ofcTrField(r, 'closing', 'closing_de', 'closing_en', {label: tr('Closing'), rows: 2})])
      + `<details class="ofcrates"><summary>${tr('Special rates')} <span class="muted">(${Object.keys(rates).length})</span></summary><div class="ofcrl">${svc.map(s => `<div class="row"><label for="of-rate-${s.id}">${esc(s.name_de)}</label><input id="of-rate-${s.id}" data-rate="${s.id}" inputmode="decimal" class="numin" value="${rates[s.id] != null ? esc(fmtNum(rates[s.id], 2)) : ''}" placeholder="${esc(s.daily_rate != null ? fmtNum(s.daily_rate, 2) : '–')}"></div>`).join('') || `<p class="muted">${tr('Add services first.')}</p>`}</div></details>`
      + `<div class="row"><label for="of-note">${tr('Note')}</label><textarea id="of-note" rows="2" maxlength="8000">${esc(r?.note || '')}</textarea></div>`;
  }
  const md = modal(`<h3>${tr(titles[kind][r ? 1 : 0])}</h3>${f}
    ${r ? ofcChk('of-archived', tr('Archived (hidden from the lists and the pickers)'), r.archived) : ''}
    <div class="aerr" role="alert"></div>
    <div class="foot">${r && adm ? `<button class="btn danger" data-m="del">${tr('Delete')}</button>` : ''}<span class="spacer"></span><button class="btn" data-m="close">${adm ? tr('Cancel') : tr('Close')}</button>${adm ? `<button class="btn pri" data-m="save">${r ? tr('Save') : tr('Add')}</button>` : ''}</div>`);
  md.classList.add('ofcdlg');
  const close = fgModal(md);  // 2.40.0 (#1371): Cancel / Esc / backdrop ask before unsaved input is lost
  if (r?.updated_at && adm) loadModule('objsave').then(() => dlgStale(md, `/api/office/${kind}/${r.id}`, () => (md._objBase || r).updated_at)).catch(() => {});  // 2.576.0 (#4764): saved elsewhere meanwhile -> the calm bar
  if (!adm) for (const el of $$('input,select,textarea,button[data-dpfor]', md)) el.disabled = true;
  if (kind === 'equipment') astBind(md, r);  // 2.92.0 B (#1931)
  if (kind === 'texts' && !r) $('#of-kind', md).addEventListener('change', e => { const l = /** @type {any} */ (e.target).value === 'letter', box = $('.ofclts', md); $('#of-text_de', md).maxLength = l ? 20000 : 8000; if (l) { $('[data-lt="de"]', box)?.click(); $$('textarea', box).forEach(t => { if (t.id !== 'of-text_de') t.value = ''; }); } $('.seg', box).style.display = l ? 'none' : ''; });  // 2.470.0 (#3596): a letter block has one text, no language tabs
  if (kind === 'contracts' && typeof dmaLoad === 'function') dmaLoad(md);  // 2.117.0 B (#2285)
  // 2.119.1 C (#2298): a contract (with its PDF files) into another workspace, admins of the office (officemove.py)
  if (['contracts', 'services', 'equipment', 'texts', 'sets'].includes(kind) && r && adm && typeof ofm_can === 'function' && ofm_can(ofm_officeFrom())) $('.foot .spacer', md)?.insertAdjacentHTML('beforebegin', `<button class="btn" data-m="move">${ic('brief', 's')} ${esc(tr('Move to another workspace…'))}</button>`);
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    const m = b.dataset.m;
    if (m === 'close') { close(); return; }
    if (m === 'add-item') { const eq = ofcRows('equipment').filter(x => !x.archived).map(x => [x.id, x.name]); $('#of-items', md).insertAdjacentHTML('beforeend', ofcSetItemHtml(eq, {equipment_id: eq[0]?.[0], qty: 1})); return; }
    if (m === 'rm-item') { b.closest('.ofcitem').remove(); return; }
    if (m === 'move') { md.remove(); ofm_move({what: kind, ids: [r.id], from: ofm_officeFrom(), label: qn(r.name || r.name_de || r.key || r.text_de || ''), after: async () => { if (kind === 'sets') delete OFC.data.equipment; ofcReload(kind); }}); return; }  // 2.119.1 C (#2298); 2.356.0 A (#2926): + services, equipment, text blocks; 2.356.1 (#3345): + sets (with their devices)
    try {
      if (m === 'del') {
        if (!await askConfirm(tr('Delete “{0}”?', r.name || r.name_de || r.key || ''), tr('Entries that documents, contracts or sets still use are archived instead.'), {ok: tr('Delete'), danger: true})) return;
        const j = await api('DELETE', `/api/office/${kind}/${r.id}`); md.remove(); ofcReload(kind);
        if (j.trash_id) toast(tr('“{0}” moved to the trash', r.name || r.name_de || r.key || ''), () => api('POST', `/api/office/trash/${j.trash_id}/restore`).then(() => ofcReload(kind), x => ofcErr(x)));  // 2.272.0 E2 (#3038)
        else toast(j.result === 'archived' ? tr('Archived (still in use)') : tr('Deleted'));
        return;
      }
      const v = id => $(id, md)?.value ?? '';
      const body = {};
      if (kind === 'services') Object.assign(body, {name_de: v('#of-name_de'), name_en: v('#of-name_en'), category: v('#of-category'), unit: v('#of-unit'), daily_rate: ofcNum(v('#of-daily_rate')), hourly_rate: ofcNum(v('#of-hourly_rate')), tax: v('#of-tax'), raw_fee: $('#of-raw_fee', md).checked ? 1 : 0, producing: $('#of-producing', md).checked ? 1 : 0, intext: v('#of-intext'), role: v('#of-role'), ...(Array.isArray(OFC.data.roles) ? {role_id: +v('#of-role_id') || null} : {}) /* 2.451.0 (#3809): roles not readable: the choice is empty, the stored role stays */, sort: ofcNum(v('#of-sort')) ?? 0});
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
      if (['services', 'roles', 'crew', 'equipment', 'texts', 'contracts'].includes(kind)) body.trans = ofcTransBody(md);  // 2.460.0 (#3767)
      if ($('#of-archived', md)) body.archived = $('#of-archived', md).checked ? 1 : 0;
      // 2.576.0 (#4764): a change through objsave.js (saveDialog: only the fields that differ from the row as opened, with
      // expect_updated_at; saved elsewhere meanwhile -> 409 "current" (2.747.0, #5246: was "row") -> the merge bar on this dialog, what was typed stays)
      let sv;
      const ourl = r ? `/api/office/${kind}/${r.id}` : '';
      if (r && kind !== 'equipment') { await loadModule('objsave'); objSess(ourl, r.updated_at); }  // 2.747.0 (#5246): the undo session of this save (was office_undo.js)
      if (r?.updated_at) {
        await loadModule('objsave');
        const base = md._objBase || r, j = await saveDialog(ourl, base, body);
        if (j?.conflict) { $('.aerr', md).textContent = ''; objMerge(md, j.conflict, cur => { md._objBase = cur; }, {field: k => $('#of-' + k, md)}); return; }
        if (j === base) { objClose(ourl); md.remove(); return; }  // nothing changed
        sv = j;
      } else sv = await api(r ? 'PATCH' : 'POST', r ? `/api/office/${kind}/${r.id}` : `/api/office/${kind}`, body);
      md.remove(); ofcReload(kind);
      if (kind === 'contracts' && !r && sv?.id && typeof dmaAfterSave === 'function') dmaAfterSave(sv.id);  // 2.117.0 B (#2285): the chosen PDFs
      if (kind === 'equipment' && r && ofcAdmin()) astUndo(r, body, sv); else if (!(r && typeof objSaved === 'function' && objSaved(ourl, body.name_de || body.name || body.key || r.name_de || r.name || r.key, () => ofcReload(kind)))) toast(r ? tr('Saved') : tr('Added'));  // 2.92.0 B (#1931): one undo step; 2.111.0 A (#2233): "… saved · Undo"; 2.747.0 (#5246): objsave.js
    } catch (x) {
      const el = $('.aerr', md); if (!el) return;
      el.textContent = ofcErrHere(x);
    }
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
  const ta = (id, label, lines, hint) => `<div class="row"><label for="${id}">${esc(label)}</label><textarea id="${id}" rows="${Math.max(2, (lines || []).length + 1)}" maxlength="3000" ${adm ? '' : 'disabled'}>${esc((lines || []).join('\n'))}</textarea>${ofcHint(hint)}</div>`;  // 2.298.0 A1 (#3186)
  const svc = ofcRows('services').filter(x => !x.archived).map(x => [x.id, x.name_de]);
  const psh = typeof prd_opts === 'function' ? prd_opts().share : null, pshl = psh ? (s.lang && s.lang !== 'de' ? psh.label.en : psh.label.de) || psh.label.de : '';  // 2.185.0 C: nl / fr / es / it English  // 2.113.1 (#2251): only with an industry pack offering it
  const logo = s.logo ? `<img class="ofclogo" src="${esc(ofc_spUrl(`/api/office/logo?v=${encodeURIComponent(s.logo)}`))}" alt="${esc(tr('Logo'))}">` : `<span class="muted">${tr('No logo yet')}</span>`;
  const dis = adm ? '' : 'disabled';
  const orgN = OFC.info.personal ? '' : orgLabelOf(OFC.info.org_id) || '';  // 2.356.0 D (#3006): an empty company name shows the organisation's name (never saved on its own)
  // 2.113.0 (#2247): five areas (one shown) and every field saves itself (data-fg-live: no bar "Unsaved changes", no Save button)
  return `<form class="ofcset" id="ofc-set" data-fg="ofc-set:${OFC.info.org_id}" data-fg-live autocomplete="off">
    ${adm ? '' : `<p class="muted ofclockhint">${ic('lock', 's')}<span>${tr('Only admins and the bookkeeping change this.')}</span></p>`}${/* 2.356.0 D (#3006) */ ''}
    ${ost_p('company', dis)}${''/* 2.555.0 (#4664): no own heading "Company" here: the group heading above says it (biz_paint) */}
    ${ofcRowF('os-name', tr('Company name'), `<textarea id="os-name" data-grow="3" style="overflow:hidden" rows="${Math.min(3, Math.max(1, String(cf.name || co.name || orgN).split('\n').length))}" maxlength="200" ${dis}>${esc(cf.name || co.name || orgN)}</textarea>`, orgN && !cf.name && !co.name ? tr('Suggested from the organisation’s name, saved once you change or confirm it') : tr('up to three lines'))}${orgN && adm && !cf.name && !co.name ? `<p class="ofcnamesug"><button type="button" class="btn sm" data-ofc="name-take">${tr('Confirm name')}</button></p>` : ''}
    ${ofcCompanyFieldsHtml(cf, dis)}
    <details class="ofcfree"><summary>${tr('Free lines (used where the fields above are empty)')}</summary>
    ${ofcII('lines')}${ta('os-lines', tr('Address lines'), co.lines, tr('one line each: street, postcode and city'))}
    ${ta('os-contact', tr('Contact lines'), co.contact_lines, tr('phone, e-mail, website'))}
    ${ta('os-register', tr('Register lines'), co.register_lines, tr('legal form, register, managing director'))}
    ${ta('os-bank', tr('Bank lines'), co.bank_lines, tr('bank, IBAN, BIC; tax number / VAT id'))}</details>
    <div class="row"><label>${tr('Logo')}</label><span class="lacts">${logo}${adm ? `<input type="file" id="os-logo" accept="image/png,image/jpeg,image/webp" aria-label="${esc(tr('Upload logo'))}">${s.logo ? `<button type="button" class="btn sm" data-ofc="logo-del">${tr('Remove')}</button>` : ''}` : ''}</span><div class="shint keep">${tr('PNG, JPEG or WebP, at least 600 px wide, up to 4 MB')}</div></div>
    ${ofcRowF('os-logo-size', tr('Logo size'), ofcSel('os-logo-size', ['s', 'l'].includes(s.logo_size) ? s.logo_size : 'm', [['s', tr('Small')], ['m', tr('Medium')], ['l', tr('Large')]]))}${/* 2.406.0 (#3501) */ ''}
    ${ofcRowF('os-logo-pos', tr('Logo position'), ofcSel('os-logo-pos', s.logo_pos === 'l' ? 'l' : 'r', [['l', tr('Left')], ['r', tr('Right')]]), tr('For all office documents created from now on. No effect when your own letterhead leaves out our head.'))}
    ${typeof agbSettingsHtml === 'function' ? agbSettingsHtml() : ''}${/* 2.113.2 (#2253): the terms and conditions (PDF) */ ''}
    ${ofcRowF('os-color', tr('Brand colour'), `<span class="lacts"><input id="os-color" value="${esc(s.color || '')}" maxlength="7" placeholder="#2f5d8a" class="numin" ${dis}><i class="ofcsw" style="background:${cssColor(s.color) || 'var(--accent)'}"></i></span>`)}${ofcII('color', tr('empty = the app’s accent colour'))}
    <p class="muted" id="os-color-note"${ofcColorLight(s.color) ? '' : ' hidden'}>${esc(tr('Text in a light brand colour is printed in a darker variant of it.'))}</p>
    ${ofcRowF('os-paper', tr('Paper size'), ofcSel('os-paper', s.paper === 'letter' ? 'letter' : 'a4', [['a4', tr('A4 (DIN 5008)')], ['letter', tr('US-Letter (8.5 × 11 in)')]]))}${/* 2.357.0 A (#3156) */ ''}
    ${/* 2.469.0 (#3352); 2.555.0 (#4664): the paper size hint stands once, in the letterhead part right below (#bp-paper-hint) */ ''}
    ${typeof bp_settingsHtml === 'function' ? bp_settingsHtml(s, dis) : ''}
    </fieldset>${ost_p('tax', dis)}${ost_taxHtml()}${/* 2.365.2 D (#2789) */ ''}
    </fieldset>${ost_p('docs', dis)}${''/* 2.555.0 (#4664): the group heading says "Documents & numbers" */}
    ${ofcRowF('os-lang', tr('Document language'), ofcSel('os-lang', s.lang, (S.languages || []).map(L => [L.code, L.name])))}
    ${ost_homeHtml(s, dis)}
    ${ofcRowF('os-currency', tr('Currency'), `<span class="lacts">${ofcSel('os-currency', s.currency, ost_curs(s.currency))}${ost_fxHtml(s, dis)}</span>`)}${ofcII((s.home_currency || 'EUR') === 'EUR' ? 'currency' : 'currency_x')}
    ${ofcSchemeHtml('os-scheme', 'offer', tr('Number scheme'), s.offer_scheme, dis)}
    ${ofcRowF('os-numat', tr('Quotation number'), ofcSel('os-numat', s.offer_number_at || 'create', [['create', tr('when the quotation is created (drafts leave gaps)')], ['finalize', tr('when it is finalised')]]))}${ofcII('numat')}
    ${ofcRowF('os-counter', tr('Counter for quotations'), ofcSel('os-counter', s.offer_counter || 'org', [['org', OFC.info.personal ? tr('one for all quotations') : tr('per organisation')], ['client', tr('per client')], ['project', tr('per project')]]))}${ofcII('counter')}
    ${ofcRowF('os-valid', tr('Quotation valid for'), `<span class="lacts"><input id="os-valid" value="${esc(String(s.offer_valid_days ?? 30))}" inputmode="numeric" class="numin" ${dis}><span class="muted">${tr('days')}</span></span>`)}${ofcII('valid')}
    ${ofcChk('os-accept-on', tr('Print the order confirmation with signature line'), s.accept_on ?? 1)}
    <div class="row"><button type="button" class="btn sm" data-ltm="sig">${ic('edit', 's')} ${tr('E-mail signature…')}</button></div>
    ${ofcChk('os-sign-offers', tr('Signature under quotations and payment reminders'), s.sign_offers)}<p class="muted ofchint">${esc(tr('The signature picture of the person who finalises the document (Correspondence > Signature); drafts stay without.'))}</p>
    <h3>${tr('Invoices')}</h3>
    ${ofcChk('os-small', p.code === 'DE' ? tr('Small business: no VAT (section 19 UStG)') : tr('Small business: no VAT'), s.small_business)}${typeof ux_info === 'function' ? ux_info('small_business') : ''}
    ${ofcSchemeHtml('os-inv-scheme', 'invoice', tr('Invoice numbers'), s.invoice_scheme, dis)}
    ${ofcSchemeHtml('os-cr-scheme', 'credit', tr('Credit note numbers'), s.credit_scheme, dis)}
    ${ofcChk('os-cr-shared', tr('Invoice corrections count in the invoice series'), s.credit_shared)}${ofcII('credit_shared')/* 2.433.0 (#3597) */}
    ${ofcSchemeHtml('os-rm-scheme', 'reminder', tr('Payment reminder numbers'), s.reminder_scheme, dis)}
    ${ofcFeat('docs.delivery') ? ofcSchemeHtml('os-ls-scheme', 'delivery', tr('Delivery note numbers'), s.delivery_scheme, dis) : ''}
    ${typeof onumHtml === 'function' ? onumHtml() : ''}
    ${ofcRowF('os-paydays', tr('Payment terms'), `<span class="lacts"><input id="os-paydays" value="${esc(String(s.payment_days ?? 14))}" inputmode="numeric" class="numin" ${dis}><span class="muted">${tr('days')}</span></span>`)}${ofcII('paydays')}
    ${ofcRowF('os-skonto', tr('Cash discount'), `<span class="lacts"><input id="os-skonto" value="${esc(+s.skonto_pct ? fmtNum(s.skonto_pct, 2) : '')}" inputmode="decimal" class="numin" ${dis}><span class="muted">%</span><input id="os-skonto-days" aria-label="${esc(tr('days'))}" value="${esc(+s.skonto_days ? String(s.skonto_days) : '')}" inputmode="numeric" class="numin" ${dis}><span class="muted">${tr('days')}</span></span>`, tr('default for new invoices; empty = none'))}
    ${ofcRowF('os-exempt', tr('Reason for tax exemption'), `<input id="os-exempt" value="${esc(s.exempt_reason || '')}" maxlength="300" ${dis}>`, tr('printed on invoices with tax-exempt positions (0 %), required for them'))/* 2.296.0 B (#3169) */}
    ${ofcRowF('os-rmfee', tr('Reminder fee'), `<span class="lacts"><input id="os-rmfee" value="${esc(fmtNum(s.reminder_fee ?? 0, 2))}" inputmode="decimal" class="numin" ${dis}><span class="muted">${ofcCur() === 'USD' ? '$' : '€'}</span></span>`)}${ofcII('rmfee')}
    ${ofcRowF('os-rmdays', tr('Payment deadline in payment reminders'), `<span class="lacts"><input id="os-rmdays" value="${esc(String(s.reminder_deadline_days ?? 10))}" inputmode="numeric" class="numin" ${dis}><span class="muted">${tr('days')}</span></span>`)}${ofcII('rmdays')}
    ${typeof dun_settingsHtml === 'function' ? dun_settingsHtml(s, dis) : '' /* 2.147.1 B (#2054) */}
    ${typeof tpSettingsHtml === 'function' ? tpSettingsHtml(s, dis) : ''}
    ${ofcFeat('docs.einvoice') ? ofcEinvRow(s) : ''}
    ${ofcFeat('docs.einvoice') && typeof pep_settingsHtml === 'function' ? pep_settingsHtml() : '' /* 2.154.0 B (#1960) */}
    ${typeof pol_settingsHtml === 'function' ? pol_settingsHtml() : '' /* 2.469.0 (#3459) */}
    </fieldset>${ost_p('tpl')}${ost_tplHtml()}${/* 2.470.0 (#3596) */ ''}
    </fieldset>${ost_p('data', dis)}
    ${ofcFeat('books.datev') ? `${ofcRowF('os-datev', tr('DATEV inbox'), `<input id="os-datev" type="email" value="${esc(s.datev_email || '')}" maxlength="200" placeholder="${esc(tr('e-mail address of the document inbox'))}" ${dis}>`)}${ofcII('datev')}
    ${ofcChk('os-datev-auto', tr('Send every invoice to the DATEV inbox when it is sent'), s.datev_auto)}${ofcII('datev_auto')}` : ''}
    ${ofcChk('os-portal-docs', tr('Show documents in the client portal'), s.portal_docs)}<p class="shint">${tr('You send the access at the client via “Send portal link”.')}</p>
    ${typeof dx_settingsHtml === 'function' && ofcFeat('books.datev') ? dx_settingsHtml(s, dis) : ''}
    ${typeof brl_settingsHtml === 'function' ? brl_settingsHtml() : '' /* 2.299.0 B (#3191): bank rules */}
    ${typeof bnr_settingsHtml === 'function' ? bnr_settingsHtml(dis) : '' /* 2.299.0 C (#3192): the reminder of the bank bookings without a receipt */}
    ${typeof ccn_settingsHtml === 'function' ? ccn_settingsHtml(dis) : '' /* 2.444.0 (#3447): the reminder of the card positions without a receipt */}
    ${typeof rcm_settingsHtml === 'function' ? rcm_settingsHtml() : '' /* 2.424.0 B (#3450): receipts by e-mail */}
    </fieldset>${ost_p('docs', dis)}
    <h3>${tr('Closing texts')}</h3>${''/* 2.555.0 (#4664): the language tabs of the closing texts had no heading */}
    ${ofcClosingTabs(s, dis)}
    <h3>${tr('Calculation rules')}</h3>
    <p class="shint">${tr('Default for new quotations, can be changed in each quotation')}</p>
    ${psh ? `${ofcChk('os-prod-on', tr('{0} by amount', pshl), s.producing_on)}
    <div class="ofcrule" data-rule="prod">
    ${ofcRowF('os-sf', tr('Factor'), `<input id="os-sf" value="${esc(fmtNum(s.share_factor ?? psh.factor, 2))}" inputmode="decimal" class="numin" ${dis}>`, tr('days = amount of the marked positions ÷ day rate × factor, rounded to half days'))}
    ${ofcRowF('os-ps', tr('Day rate from'), ofcSel('os-ps', s.producing_service_id, svc, tr('fixed rate below')))}
    ${ofcRowF('os-sr', tr('Day rate'), `<input id="os-sr" value="${esc(fmtNum(s.share_rate ?? psh.rate, 2))}" inputmode="decimal" class="numin" ${dis}>`, `${ofcCur()} ${tr('per day')}`, {keep: 1})}
    </div>` : ''}
    ${ofcChk('os-raw-on', tr('Raw data surcharge'), s.raw_on)}
    <div class="ofcrule" data-rule="raw">
    ${ofcRowF('os-rf', tr('Raw data factor'), `<input id="os-rf" value="${esc(fmtNum(s.raw_factor, 2))}" inputmode="decimal" class="numin" ${dis}>`)}${ofcII('rf', tr('raw data amount = sum of the raw data positions × factor'))}
    </div>
    ${ost_indLinkHtml(s)}${''/* 2.555.0 (#4664): the industry packs are switched only on their cards under Packs; here the way there */}
    <h3>${tr('Default texts')}</h3>
    ${ofcRowF('os-intro-de', tr('Introduction (German)'), ofcSel('os-intro-de', s.intro_text_id?.de, ofcTextOpts('intro'), tr('none')))}${ofcII('texts')}
    ${ofcRowF('os-intro-en', tr('Introduction (English)'), ofcSel('os-intro-en', s.intro_text_id?.en, ofcTextOpts('intro', 'en'), tr('none')))}
    ${ofcRowF('os-closing-de', tr('Closing (German)'), ofcSel('os-closing-de', s.closing_text_id?.de, ofcTextOpts('closing'), tr('none')))}
    ${ofcRowF('os-closing-en', tr('Closing (English)'), ofcSel('os-closing-en', s.closing_text_id?.en, ofcTextOpts('closing', 'en'), tr('none')))}
    ${ofcRowF('os-rt', tr('Rights: duration'), ofcSel('os-rt', s.rights_default?.time_id, ofcTextOpts('rights_time'), tr('none')))}${ofcII('rights')}
    ${ofcRowF('os-rr', tr('Rights: territory'), ofcSel('os-rr', s.rights_default?.territory_id, ofcTextOpts('rights_territory'), tr('none')))}
    ${ofcRowF('os-rm', tr('Rights: media'), ofcSel('os-rm', s.rights_default?.media_id, ofcTextOpts('rights_media'), tr('none')))}
    </fieldset>${ost_p('packs', dis)}${''/* 2.555.0 (#4664): no heading "Country pack" over the row "Country pack" */}
    ${ofcRowF('os-pack', tr('Country pack'), `<span class="lacts">${ofcSel('os-pack', s.pack, (OFC.packs || [[p.code, p.name]]))}<span class="muted">${esc(tr('VAT: {0} standard, {1} reduced, {2} exempt', `${fmtNum(p.tax.standard, 1)} %`, `${fmtNum(p.tax.reduced, 1)} %`, `${fmtNum(p.tax.exempt, 1)} %`))}</span></span>`)}${ofcII('pack')}
    ${ofcOwnRatesHtml(s, p, dis)}
    </fieldset>${ost_p('functions', dis)}
    ${typeof ocf_settingsHtml === 'function' ? ocf_settingsHtml(dis) : ''}
    </fieldset>${ost_p('access', dis)}
    ${typeof oa_settingsHtml === 'function' ? oa_settingsHtml(s, dis) : ''}
    </fieldset>${ost_p('packs')}
    ${typeof pkc_html === 'function' ? pkc_html() : ''}
    </fieldset>${ost_p('tax')}${''/* 2.555.0 (#4664): travel expenses and entertainment receipts belong to Bank & taxes, not to Packs */}
    ${typeof rk_settingsHtml === 'function' ? rk_settingsHtml() : ''}
    ${typeof bw_settingsHtml === 'function' ? bw_settingsHtml() : ''}
    </fieldset>${ost_p('docs')}${''/* 2.417.0 C (#3445): the test mode, per person (members too: a fieldset of its own, never disabled) */}
    ${typeof tri_settingsHtml === 'function' ? tri_settingsHtml() : ''}
    </fieldset>${ost_p('data')}${''/* 2.365.2 D (#2789): the start balance moved to Bank & taxes, the master data file to Data */}
    <h3>${tr('Master data file')}</h3>
    <p class="muted">${tr('Services, equipment, sets, text blocks, contracts and these settings as a JSON file. Import adds what is missing.')}</p>
    <div class="lacts"><a class="btn sm" href="/api/office/export" download="office-master-data.json">${ic('download', 's')} ${tr('Export')}</a>
      ${adm ? `<input type="file" id="os-import" accept="application/json,.json" hidden><button type="button" class="btn sm" data-ofc="import">${ic('upload', 's')} ${tr('Import')}</button><label class="chkl" data-fg-skip><input type="checkbox" id="os-overwrite"> ${tr('overwrite existing')}</label>` : ''}</div>
    </fieldset>${ost_p('data')}
    ${adm ? `<h3>${tr('Import legacy data')}</h3><p class="muted">${tr('Clients, services, equipment and fixed costs from a spreadsheet, leads from a CSV file; old invoices and quotations as an archive.')}</p><div class="lacts"><a class="btn sm" href="#office/import">${ic('upload', 's')} ${tr('Import legacy data')}</a></div>` : ''}
    </fieldset>${ost_p('access')}
    ${adm ? `<h3>${tr('Access log')}</h3><p class="muted">${tr('Who opened, printed, changed or exported documents and master data of this organisation.')}</p>${ofcLogHtml()}${ofcChainHtml()}` : ''}
    </fieldset>${ost_p('data')}
    ${adm ? rthHtml() : ''}${''/* 2.545.0 (#4595): the switch "Extend the lock" */}
    ${adm && OFC.info.personal && (OFC.info.can_move || OFC.info.move_orgs?.length) ? `<h3>${tr('Transfer into an organisation')}</h3>${''/* 2.144.6 C (#2436): one section, one word (übertragen) for both ways */}
    ${OFC.info.can_move ? `<p class="muted">${tr('Documents, numbers, settings, master data and clients go with it. This cannot be undone.')}</p><div class="lacts"><button type="button" class="btn sm" data-ofc="pb-move">${ic('building', 's')} ${tr('Transfer into a new organisation…')}</button></div>` : ''}
    ${OFC.info.move_orgs?.length ? `<p class="muted">${tr('Finalised invoices stay locked and keep their numbers. This cannot be undone.')}</p><div class="lacts"><button type="button" class="btn sm" data-ofc="pb-transfer">${ic('building', 's')} ${tr('Transfer into an organisation…')}</button></div>` : ''}` : ''}
    ${adm && !OFC.info.personal && OFC.info.org_id && S.me?.kind !== 'agent' ? `<h3>${tr('Transfer into your private office')}</h3><p class="muted">${tr('What you created in this office (clients, drafts, framework contracts, trips, templates) moves into your private office, for example when you leave an office community. Issued invoices stay here; a read-only copy can go along. Can be undone.')}</p><div class="lacts"><button type="button" class="btn sm" data-ofc="org-out">${ic('user', 's')} ${tr('Transfer into your private office…')}</button></div>` : ''}${''/* 2.356.0 A (#2926) */}
    ${adm && OFC.info.personal && typeof ox_pbBoxHtml === 'function' ? ox_pbBoxHtml(0) : ''}${''/* 2.137.0 A (#2344): export of the personal office */}
    ${adm && OFC.info.personal && typeof rxBoxHtml === 'function' ? rxBoxHtml('me') : ''}${''/* 2.146.0 D (#2468): the retention export of the own records */}
    </fieldset>
  </form>`;
}
// 2.545.0 (#4595): the switch "Extend the lock" (a tax audit is open): nothing this office keeps by law is deleted while it is on,
// also after its period; its own route (not a field of the settings form: data-fg-skip), each step in the office log
function rthHtml() {
  setTimeout(() => rthLoad(), 0);
  return `<h3 id="os-rth-h">${tr('Extend the lock')}</h3><div id="os-rth" data-fg-skip><div class="muted mhint">${tr('Loading…')}</div></div>`;
}
async function rthLoad(j) {
  const box = $('#os-rth'); if (!box) return;
  if (typeof OFD_ACTIONS === 'object') OFD_ACTIONS.retention_hold = N_('retention lock extended / ended');  // the office log's word
  if (!j) { try { j = await api('GET', '/api/office/settings/retention-hold'); } catch { box.innerHTML = ''; return; } }
  const ky = j.keep_years || {};
  box.innerHTML = `<div class="featgrid"><label class="wide"><input type="checkbox" id="rth-on" ${j.on ? 'checked' : ''}><span>${tr('Extend the lock (tax audit)')}<small class="muted">${tr('While a tax audit is open: nothing this office keeps by law is deleted, not even after its period, until you switch it off again.')}</small></span></label></div>
    ${j.on ? `<div class="shint cnote" id="rth-since">${esc(tr('On since {0} ({1}).', fmtStamp(new Date(j.since)), j.by_name || '?'))}</div>` : ''}
    <div class="shint">${esc(tr('Kept from the end of the year: invoices and receipts {0} years, books {1} years, the logbook {2} years, business letters {3} years.', ky.receipt, ky.book, ky.logbook, ky.letter))}</div>`;
  $('#rth-on', box).onchange = async e => {
    const el = e.target, on = el.checked; el.disabled = true;
    try { await rthLoad(await api('PUT', '/api/office/settings/retention-hold', {on})); } catch (x) { el.checked = !on; el.disabled = false; ofcErr(x); }
  };
}
// 2.147.0 (#2461): the e-invoice format -- only the formats the country pack offers (the base pack: ZUGFeRD / Factur-X)
function ofcEinvRow(s) {
  const fm = OFC.info.pack?.einvoice_formats?.length ? OFC.info.pack.einvoice_formats : ['zugferd', 'xrechnung'];
  const all = [['zugferd', fm.includes('xrechnung') ? tr('ZUGFeRD (PDF with XML)') : tr('ZUGFeRD / Factur-X (PDF with XML)')], ['xrechnung', tr('XRechnung (XML)')]].filter(o => fm.includes(o[0]));  // 2.356.0 C (#3005): translated
  return `${ofcRowF('os-einv', tr('E-invoice format'), ofcSel('os-einv', fm.includes(s.einvoice_format) ? s.einvoice_format : fm[0], all))}${ofcII('einv', fm.includes('xrechnung') ? tr('clients with a buyer reference get XRechnung proposed') : '')}`;
}
// 2.147.0 (#2461): a pack that leaves the VAT rates and the retention to the office (the international base pack)
function ofcOwnRatesHtml(s, p, dis) {
  const own = s.tax_rates || {}, rt = p.retention || {};
  const rate = (id, k, label) => ofcRowF(id, label, `<span class="lacts"><input id="${id}" value="${esc(own[k] != null ? fmtNum(own[k], 2) : '')}" placeholder="${esc(fmtNum(p.tax[k], 2))}" inputmode="decimal" class="numin" ${dis}><span class="muted">%</span></span>`);
  return (p.tax_editable ? `${rate('os-tax-std', 'standard', tr('Standard VAT rate'))}${rate('os-tax-red', 'reduced', tr('Reduced VAT rate'))}<p class="shint keep">${tr('Empty = the rate of the pack. Open documents are calculated with the new rate, finalised ones keep theirs.')}</p>` : '')
    + (rt.editable ? ofcRowF('os-ret', tr('Retention period'), `<span class="lacts"><input id="os-ret" value="${esc(s.retention_years != null ? String(s.retention_years) : '')}" placeholder="${esc(String(rt.receipts ?? 10))}" inputmode="numeric" class="numin" ${dis}><span class="muted">${tr('years')}</span></span>`, tr('how long receipts are kept before they may be deleted; at least {0} years', rt.min_years ?? 1), {keep: 1}) : '');
}
// 2.47.3 (#1360): the personal office becomes a new organisation (one way: name, then a confirmation)
async function pb_move() {
  const name = ((await askPrompt(tr('Name of the new organisation'), (OFC.info?.settings?.company?.name || OFC.info?.company_fields?.name || '').split('\n').join(' '), {ok: tr('Next'), input: {max: 60}})) || '').trim();
  if (!name) return;
  if (!await askConfirm(tr('Move your private office into “{0}”?', name), tr('Turns this private office into a new organisation with you as its admin: documents, numbers, settings, master data and your private clients go with it. This cannot be undone.'), {ok: tr('Move'), danger: true})) return;
  try {
    const j = await api('POST', '/api/office/move', {name, confirm: true});
    await refreshMe(); S.workspaces = true; S.settings.workspace = 'org:' + j.org_id; LS.set('ws', S.settings.workspace);
    pb_reset(true); OFC.ws = typeof wsCur === 'function' ? wsCur() : ''; render();
    toast(tr('The organisation “{0}” now holds your office', j.name));
  } catch (x) { ofcErr(x); }
}
// 2.137.0 D (#1981): the personal office into an organisation the person is an admin of (one way: preview with the
// conflicts, then the confirmation; GET /api/office/move/check, POST /api/office/move/org)
async function pb_transfer() {
  const orgs = OFC.info?.move_orgs || []; if (!orgs.length) return;
  let org = orgs[0].id, pv = null;
  const ul = a => a?.length ? `<ul>${a.map(x => `<li>${esc(x)}</li>`).join('')}</ul>` : '';
  const show = async md => {
    const box = $('#pbt-pv', md), ok = $('[data-cd="yes"]', md), want = org;
    pv = null; ok.disabled = true; box.innerHTML = `<p class="muted">${esc(tr('Loading…'))}</p>`;
    let j; try { j = await api('GET', `/api/office/move/check?org=${encodeURIComponent(want)}`); } catch (x) { if (want === org) box.innerHTML = `<p class="aerr">${esc(ofcErrHere(x))}</p>`; return; }
    if (want !== org) return;
    pv = j;
    box.innerHTML = (j.conflicts.length ? `<p><b>${esc(tr('Cannot be transferred'))}</b></p>${ul(j.conflicts)}` : '')
      + `<p><b>${esc(tr('Goes along'))}</b></p>${ul(j.moves)}<p><b>${esc(tr('Stays in your private office'))}</b></p>${ul(j.keeps)}${ul(j.notes)}<p>${esc(j.who)}</p><p class="muted">${esc(tr('This cannot be undone.'))}</p>`;
    ok.disabled = !j.ok;
  };
  const html = (orgs.length > 1 ? `<label>${esc(tr('Organisation'))} <select id="pbt-org">${orgs.map(o => `<option value="${o.id}">${esc(o.name)}</option>`).join('')}</select></label>` : `<p>${esc(tr('Into “{0}”', orgs[0].name))}</p>`) + '<div id="pbt-pv"></div>';
  const yes = await askDialog({title: tr('Transfer into an organisation'), html, ok: tr('Transfer'), danger: true,
    after: md => { $('#pbt-org', md)?.addEventListener('change', e => { org = +e.target.value; show(md); }); show(md); }});
  if (!yes || !pv?.ok) return;
  try {
    const j = await api('POST', '/api/office/move/org', {org, confirm: true});
    await refreshMe(); S.settings.workspace = 'org:' + j.org_id; LS.set('ws', S.settings.workspace);
    pb_reset(true); OFC.ws = typeof wsCur === 'function' ? wsCur() : ''; render();
    toast(tr('Your office is now in “{0}”', j.name));
  } catch (x) { ofcErr(x); }
}
// 2.356.0 A (#2926): the own part of an organisation's office into the personal office (POST /api/office/move-space what office:
// the shared move dialog with the read-only copy option, one undo step)
function ofc_orgOut() {
  const org = OFC.info?.org_id; if (!org || typeof ofm_move !== 'function') return;
  ofm_move({what: 'office', ids: [org], from: org, only: ['private'], label: tr('What you created in this office'),
    after: async () => { OFC.info = null; OFC.data = {}; await ofcInfo(true); }});
}
// 2.36.2 (#1021 P4): the company as single fields (print lines are made from them; the free lines stay the fallback)
const OFC_CO_FIELDS = [['street', N_('Street'), 200], ['address_extra', N_('Address extra'), 200], ['zip', N_('Postcode'), 20], ['city', N_('City'), 120], ['country', N_('Country'), 2],  // 2.99.0 D (#2188): + BT-36
  ['email', N_('E-mail'), 200], ['website', N_('Website'), 200], ['phone', N_('Phone'), 60], ['tax_number', N_('Tax number'), 40], ['vat_id', N_('VAT ID'), 20], ['bank_name', N_('Bank'), 120],  // 2.408.0 (#3494): + website
  ['iban', N_('IBAN'), 42], ['bic', N_('BIC'), 11], ['register_court', N_('Register court'), 120], ['register_no', N_('Register number'), 60],
  ['managing_directors', N_('Managing directors'), 300]];
const OFC_CO_BANK = ['bank_name', 'iban', 'bic'];  // 2.470.0 (#3596): with bank accounts these live in Bank & taxes (office_bankacc.js)
function ofcCompanyFieldsHtml(cf, dis) {
  const acc = !!OFC.info?.bank_accounts;
  return `<div class="ofcco">${OFC_CO_FIELDS.filter(([k]) => !acc || !OFC_CO_BANK.includes(k)).map(([k, n, mx]) => ofcCoHint(k, k === 'country' ? ofcRowF('osc-country-q', tr(n), ctyField('osc-country', cf.country, {attrs: 'data-co="country"', dis, label: tr(n)})) : ofcRowF('osc-' + k, tr(n), `<input id="osc-${k}" data-co="${k}" value="${esc(cf[k] || '')}" maxlength="${mx}" ${k === 'country' ? 'class="numin" autocapitalize="characters"' : ''}${k === 'website' ? ' inputmode="url" autocapitalize="off" spellcheck="false" placeholder="www.example.com"' : ''} ${dis}>`))).join('')}${ofcMdLabelHtml(cf, dis)}${acc ? ofcSetLink('tax', tr('Bank accounts')) : ''}</div>`;
}
// 2.40.0 (#1377): the word printed before the management's names (Geschäftsführung, Gesellschafter, ...); the options show the
// print word of the document's language (German in the German interface, otherwise English; 2.446.0 #3763); '' = Geschäftsführung as before
const OFC_MD_LABELS = [['', 'Geschäftsführung', 'Managing directors'], ['shareholders', 'Gesellschafter', 'Shareholders'], ['owner_m', 'Inhaber', 'Owner'],
  ['owner_f', 'Inhaberin', 'Owner'], ['board', 'Vorstand', 'Executive board'], ['partners', 'Partner', 'Partners'],
  ['gbr_partners', 'Gesellschafter (GbR)', 'Partners (GbR)']];  // 2.138.0 E (#2242): prints Gesellschafter / Partners
const ofcMdLabelHtml = (cf, dis) => ofcRowF('osc-md_label', tr('Printed as'), `<select id="osc-md_label" data-co="md_label" ${dis}>${OFC_MD_LABELS.map(([v, de, en]) => `<option value="${v}" ${(cf.md_label || '') === v ? 'selected' : ''}>${esc(I18N.code === 'de' ? de : en)}</option>`).join('')}</select>`)
  + `<div class="shint">${esc(tr('The word before the names in the footer, e.g. GmbH: Geschäftsführung, sole proprietor: Inhaber/in.'))}</div>`;
// 2.40.0 (#1382): the number schemes explained -- building blocks as buttons (inserted at the caret), a table behind (i),
// the next number of each scheme with its counter (restarts every year or never), errors in plain words from the server
const OFC_BB = [['{yyyy}', N_('Year'), '2026'], ['{yy}', N_('Year, short'), '26'], ['{seq:03}', N_('Running number, 3 digits'), '001'], ['{seq}', N_('Running number'), '1'],
  ['{project}', N_('Project'), N_('Promo film')], ['{client}', N_('Client'), N_('Example Ltd')], ['{kuerzel}', N_('Short code of the client'), 'TNP'], ['{date}', N_('Date'), '20261014'],
  ['{isodate}', N_('Date with hyphens'), '2026-10-14'], ['{initials}', N_('Initials of the person'), 'AB']];  // 2.138.2 A (#2391); 2.433.0 (#3604): {kuerzel}
const OFC_BB_VER = ['{version}', N_('Version'), '2'];  // 2.118.0 A (#2265): quotations only (the duplicate of a quotation = the next version)
OFC.pv = OFC.pv || {};
function ofcSchemeHtml(id, kind, label, val, dis) {
  const pv = OFC.pv[kind], cur = val || '';
  if (!pv || pv.scheme !== cur) setTimeout(() => { const el = $('#' + id); if (el && !OFC.pv[kind]?.busy) ofcSchemePv(el, true); }, 0);
  const pvText = pv && pv.scheme === cur ? pv.text : kind === 'offer' && OFC.info.number_preview ? tr('next: {0}', OFC.info.number_preview) : '';
  const bbs = kind === 'offer' ? [...OFC_BB, OFC_BB_VER] : OFC_BB;  // 2.118.0 A (#2265)
  const table = tr('Building blocks of a number:') + '\n' + bbs.map(([b, n, ex]) => `${b} = ${tr(n)} (${tr(ex)})`).join('\n') + '\n' + tr('Examples: RE-{yyyy}-{seq:03} gives RE-2026-001; {yyyy}-{seq:04} gives 2026-0001; R{yy}{seq:03} gives R26001.')
    + '\n' + tr('With a year in the scheme the counter starts again at 1 every year; without one it simply counts on.') + (kind === 'invoice' ? '\n' + tr('Invoices get their number only when they are finalised, one after the other without gaps.') : '')
    + (kind === 'offer' ? '\n' + tr('{version}: the first quotation is 1, each duplicate of it the next version with the same running number.') : '');
  return ofcRowF(id, label, `<span class="lacts ofcscheme"><input id="${id}" data-scheme="${kind}" value="${esc(cur)}" maxlength="80" autocomplete="off" spellcheck="false" ${dis}><span class="muted ofcpv" id="${ofcPvId(id)}" aria-live="polite">${esc(pvText)}</span><button type="button" class="btn sm ofcrs" id="${id}-rs" data-ofc="scheme-reset" data-for="${id}" data-kind="${kind}" hidden>${esc(tr('Reset'))}</button></span>`,  // 2.114.2 (#2264): error under the field + reset
    kind === 'invoice' ? tr('the number comes only when the invoice is finalised; the series has no gaps') : '', {keep: 1})
    + (dis ? '' : `<div class="ofcbb" role="group" aria-label="${esc(tr('Building blocks'))}">${bbs.filter(x => x[0] !== '{seq}').map(([b, n]) => `<button type="button" class="btn sm" data-ofc="bb" data-for="${id}" data-bb="${b}" title="${esc(b)}">${esc(tr(n))}</button>`).join('')}</div>`)
    + `<div class="shint pl">${esc(table)}</div>`;
}
const ofcPvId = id => id === 'os-scheme' ? 'os-preview' : id + '-pv';  // (the quotation's preview keeps its id)
function ofcSchemePv(inp, now) {
  const kind = inp.dataset.scheme, v = inp.value;
  OFC.pv[kind] = {...(OFC.pv[kind] || {}), busy: true};
  clearTimeout(OFC['pvT' + kind]);
  OFC['pvT' + kind] = setTimeout(async () => {
    let text;
    const cnt = kind === 'offer' && $('#os-counter') ? `&counter=${encodeURIComponent($('#os-counter').value)}` : '';  // 2.118.0 A (#2265)
    try { const j = await api('GET', `/api/office/number-preview?kind=${kind}&scheme=${encodeURIComponent(v)}${cnt}`);
      text = j.valid ? tr('next: {0}', j.preview) + ' · ' + (j.yearly ? tr('starts again every year') : tr('counts on without a restart')) : (j.error || tr('Invalid value: {0}', tr('Number scheme'))); }
    catch { text = ''; }
    OFC.pv[kind] = {scheme: v, text};
    const el = $('#' + ofcPvId(inp.id)); if (el) { el.textContent = text; const er = !!text && !text.startsWith(tr('next: {0}', '').trim()); el.classList.toggle('err', er); const rs = $('#' + inp.id + '-rs'); if (rs) rs.hidden = !er; }  // 2.114.2 (#2264)
  }, now ? 0 : 250);
}
// 2.40.0 (#1382): (i) explanations of the technical terms (one sentence + an example); shown behind the (i) of the row above
const OFC_II = {
  numat: N_('At once: the draft shows its number. When finalised: drafts have no number, so discarded drafts leave no gaps.'),
  counter: N_('Per client or per project each one counts on its own, e.g. KV-{client}-{yyyy}-{seq:02} gives KV-ACME-2026-03. A new quotation gets its number once the client or project is set. Invoices always keep one counter.'),  // 2.118.0 A (#2265)
  paydays: N_('Payment terms: the days a client has to pay an invoice, printed as the due date (e.g. 14 days). A client\'s own payment terms win.'),
  rmdays: N_('Payment deadline: the new, shorter period a payment reminder gives, counted from its date (e.g. 10 days).'),
  einv: N_('ZUGFeRD is a normal PDF with the invoice data inside, fine for most clients. XRechnung is pure XML, required by public authorities (they give you a routing ID, the Leitweg-ID).'),
  datev: N_('The e-mail address of the document inbox your tax advisor gives you (DATEV Unternehmen online). Finalised invoices go there as PDF (ZUGFeRD with the invoice data inside, XRechnung also as XML) and land in the accounting by themselves.'),  // 2.434.0 (#3616): ZUGFeRD as PDF alone  // 2.298.0 A1 (#3186): + PDF + XML (the line under the field is gone)
  pq: N_('Example: 6 production days with quotient 3 make 2 producing days, charged at the producing rate. A markup for organising the production.'),
  rf: N_('Example: positions with raw data add up to 2,000 €; factor 0.25 makes a raw data surcharge of 500 €, as an option or included (set per quotation).'),
  pack: N_('A country pack brings the VAT rates, the formats and the printed words and legal texts of one country.'),
  register_court: N_('From the commercial register, e.g. Amtsgericht Hamburg, HRB 12345. Needed for GmbH, UG, AG and eGbR; empty for sole proprietors and a GbR.'),
  vat_id: N_('VAT identification number (USt-IdNr.), e.g. DE123456789: needed on invoices to companies in other EU countries.'),
  tax_number: N_('The tax number from your tax office, e.g. 12/345/67890; printed when there is no VAT ID.'),
  cl_peppol_id: N_('For e-invoices over the Peppol network: scheme and number of the client, e.g. 0208:0123456749 (Belgium), 9930:DE123456789 or 0088:GLN. The client or its software provider knows it.'),  // 2.154.0 B (#1960)
  cl_buyer_reference: N_('Public clients give you a routing ID (Leitweg-ID, e.g. 991-12345-67); companies sometimes an order or reference number. It is printed and goes into the e-invoice.'),
  cl_email_invoice: N_('Where invoices of this client are sent, e.g. the accounting department; empty = the client\'s normal e-mail.'),
  cl_payment_terms_days: N_('Days this client has to pay; empty = the payment terms of the settings.'),
};
// 2.47.3 (#1382): (i) texts for the remaining settings fields, the quotation/invoice editor (ed_*) and the client card
Object.assign(OFC_II, {
  currency: N_('The currency of your quotations and invoices. Rates stay in euros; for US dollars the exchange rate converts them (1.09 means 1 € = 1.09 $).'),
  currency_x: N_('The currency of new quotations and invoices. Prices stay in the home currency; for another currency the exchange rate converts them (1.09 means 1 unit of the home currency = 1.09 of the other).'),  // 2.189.0 (#2475)
  home: N_('The currency of your price list, books, cash flow and travel expenses. Documents in another currency are converted with their exchange rate; the tax is also shown in the home currency.'),  // 2.189.0 (#2475)
  color: N_('The colour of headings and lines in your printed documents, as a hex code, e.g. #2f5d8a.'),
  valid: N_('How long a quotation stays valid after its date; printed on it, e.g. 30 days.'),
  rmfee: N_('A flat fee added to every payment reminder for late payment, e.g. 5 €. 0 = no fee.'),
  prod_rate: N_('What one producing day costs: taken from a service of your price list, or a fixed amount (e.g. 600 € per day).'),
  rights: N_('Default usage rights printed in quotations: how long, where and in which media the client may use the result (e.g. 1 year, Germany, online).'),
  indfilm: N_('Adds the shoot calculation (shooting days, crew, equipment) to quotations. Only useful for film and video productions.'),
  lines: N_('Free text for letterhead and footer, only used where the single fields above are empty.'),
  datev_auto: N_('Every invoice you send by e-mail is also mailed to the DATEV inbox, so you need not forward it by hand.'),
  credit_shared: N_('On: a correction takes the next number of the invoice counter (e.g. 423_R, 424_RK, 425_R) and keeps its own scheme. Off: corrections have their own counter. Numbers already given stay.'),
  texts: N_('Introduction and closing are text blocks (tab Text blocks) that new quotations start with; each quotation can change them.'),
  small_business: N_('Under the small business rule (§ 19 UStG) you charge no VAT and print a note on your invoices instead. It applies only below the turnover limit; ask your tax advisor.'),
  cl_customer_no: N_('The client number you give this client in your accounting (e.g. K-1042).'),
  ed_order_ref: N_('The client\'s own order number; printed on the invoice so their accounting can match it (e.g. PO-4711).'),
  ed_payment_days: N_('Days until the invoice is due, e.g. 14. Empty = the client\'s payment terms, else the ones from the settings.'),
  ed_vat_mode: N_('Without VAT is for reverse charge (a company in another EU country with a VAT ID) or clients outside the EU; a note on the invoice then says why.'),
  ed_contract_id: N_('A framework contract holds the special rates and standard rights agreed with one client (e.g. a yearly agreement); it presets new positions.'),
  ed_raw_mode: N_('Raw data = the unedited material. Optional: shown as an extra line, not counted. Included: counted in the total. None: no line.'),
  ed_reminder_level: N_('Level 1 is a friendly payment reminder, 2 a reminder, 3 the final reminder before further steps.'),
});
Object.assign(OFC_II, {ed_einvoice_format: OFC_II.einv, ed_raw_factor: OFC_II.rf, ed_prod_quotient: OFC_II.pq, ed_producing_rate: OFC_II.prod_rate,
  ed_reminder_deadline_days: OFC_II.rmdays, cl_vat_id: OFC_II.vat_id});
// (i) text of a field by key, for other parts of the office (e.g. the personal-office company fields, the client page)

// 2.298.0 A1 (#3186): more = the field's own help line, shown in the same (i) as its own line (one (i) per label, not two)
const ofcII = (k, more) => OFC_II[k] ? `<div class="shint${more ? ' pl' : ''}">${esc(tr(OFC_II[k]) + (more ? '\n' + more : ''))}</div>` : more ? ofcHint(more) : '';
// (i) text of a field by key, for other parts of the office (personal-office company fields, client page)
const ux_info = k => ofcII(k);
const ofcCoHint = (k, row) => row + ofcII(k);
function ofcLogHtml() {
  if (!OFC.log) return `<button type="button" class="btn sm" data-ofc="log">${ic('clock', 's')} ${tr('Show the latest entries')}</button>`;
  if (!OFC.log.length) return `<p class="muted">${tr('No entries yet.')}</p>`;
  const tg = {doc: N_('Document'), settings: N_('Settings'), company: N_('Company'), logo: N_('Logo'), master_data: N_('Master data'), services: N_('Services'),
    equipment: N_('Equipment'), sets: N_('Sets'), texts: N_('Text blocks'), contracts: N_('Framework contracts'), legacy: N_('Legacy import'), archive: N_('Archive|documents'), datev: N_('DATEV export'), terms: N_('Terms and conditions')};  // 2.47.3 (#1460): + datev; 2.113.2 (#2253): + terms
  if (typeof OA_LOG_TG === 'object') Object.assign(tg, OA_LOG_TG);  // 2.51.0 A (#1348): what agents read / drafted, the filter "Agents"
  const rows = OFC.logAg ? OFC.log.filter(x => /^agent_/.test(x.action)) : OFC.log;
  return (typeof oa_logFilter === 'function' ? oa_logFilter() : '') + `<ul class="ofdlog" role="list">${rows.map(x => `<li><span class="muted">${esc(typeof ofdWhen === 'function' ? ofdWhen(x.at) : x.at)}</span> <b>${esc(x.user_name || '?')}</b> ${x.action === 'delete' && x.detail?.testphase ? esc(tr(x.detail.kind === 'invoice' ? N_('Invoice {0} deleted in the test phase') : N_('{0} deleted in the test phase'), x.detail.number || '#' + x.doc_id)) : `${esc(typeof ofdActText === 'function' ? ofdActText(x.action) : x.action)} · ${esc(tr(tg[x.target] || x.target))}${x.doc_id ? ` <a href="#office/offers/${x.doc_id}">#${x.doc_id}</a>` : ''}`}</li>`).join('')}</ul>`;  // 2.162.0 A (#2603): no link to the gone document
}
// 2.528.0 (#4305 A3): only what differs from the saved settings (a field another admin changed meanwhile is never sent back
// with the old value this page still showed); a group of fields (company, the text ids, ...) per field
function oxaChanged(body) {
  const old = ost_old(body), same = (a, b) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null), out = {};
  for (const [k, v] of Object.entries(body)) {
    const o = old[k];
    if (k !== 'tax_rates' && v && typeof v === 'object' && !Array.isArray(v) && o && typeof o === 'object' && !Array.isArray(o) && Object.keys(o).length) {
      const sub = Object.fromEntries(Object.entries(v).filter(([f, x]) => !same(x, o[f])));
      if (Object.keys(sub).length) out[k] = sub;
    } else if (!same(v, o)) out[k] = v;
  }
  return out;
}
// 2.528.0 (#4305 A3): the settings changed elsewhere since this page loaded them (409 with the current ones)
const oxaStale = x => x?.status === 409 && !!x.data?.settings;
const oxaAt = () => OFC.info?.settings?.updated_at ?? '';
// the PUT with the version; errors shown as api() shows them, except the 409 of a newer version (handled by the caller)
const oxaPut = b => rawFetch('PUT', '/api/office/settings', {...b, expect_updated_at: oxaAt()}).catch(x => {
  if (!oxaStale(x) && x.message !== 'auth' && !x.shown) toast(x instanceof Offline ? tr('Offline: only works again with a connection') : x.message);
  throw x;
});
// 2.531.0 (#4497): the check of the hash chain over the finalised documents (GET /api/office/log/chain)
function ofcChainHtml() {
  const k = OFC.chain, btn = `<button type="button" class="btn sm" data-ofc="chain">${ic('check', 's')} ${tr('Check: chain intact')}</button>`;
  if (!k) return `<div class="ofc-chain">${btn}</div>`;
  const pend = k.pending ? ` ${esc(trn('{0} finalised document is not chained yet (it is added at the next finalising).', '{0} finalised documents are not chained yet (they are added at the next finalising).', k.pending))}` : '';
  const msg = k.ok ? esc(trn('Chain intact: {0} finalised document checked.', 'Chain intact: {0} finalised documents checked.', k.count)) + pend
    : esc(tr(k.first_bad.reason === 'gap' ? N_('Chain broken: a document before {0} is missing.') : N_('Chain broken: document {0} differs from what was finalised.'), k.first_bad.number || '#' + k.first_bad.id)) + ` <a href="#office/offers/${+k.first_bad.id}">#${+k.first_bad.id}</a>`;
  return `<div class="ofc-chain">${btn} <p class="${k.ok ? 'muted' : 'bad'}" role="status">${msg}</p></div>`;
}
async function ofcSaveSettings(form) {
  const body = oxaChanged(ofcSettingsBody(form)), at = document.activeElement?.closest?.('#ofc-set') ? document.activeElement : null;
  // 2.298.0 A1 (#3186): Enter saves the page quietly: the mark at the field instead of the toast "Saved"
  try { const j = await oxaPut(body); OFC.info.settings = j.settings; OFC.info.company_fields = j.company_fields || OFC.info.company_fields; OFC.info.number_preview = j.number_preview; OFC.log = null; fgDone(form.dataset.fg); ofcDraw(); const f = at && (at.isConnected ? at : ost_find(at)); if (f) ost_mark(f, 'ok'); else toast(tr('Saved')); }
  catch (x) {
    // 2.528.0 (#4305 A3): changed elsewhere: the current settings are drawn, what was typed here stays (formguard draft), save again
    if (oxaStale(x)) { await ofcInfo(true); toast(tr('Someone else changed the settings meanwhile. The page shows their state, your changes are kept: check and save again.')); return; }
    const el = $('.aerr', form); if (el) el.textContent = ofcErrHere(x);
  }
}
// 2.189.0 (#2475): the home currency (chosen only in a pack that allows it, fixed after the first bookings), the currency of new
// documents and its office rate (EUR offices keep "1 € in USD" in fx_usd; any other pair goes to fx_rates)
const OFC_HC_LOCKED = N_('The home currency can no longer be changed: this office already has bookings (invoices, payments, receipts).');
const ost_curs = cur => [...new Set([...(OFC.info.pack?.currencies || ['EUR', 'USD']), cur].filter(Boolean))].map(x => [x, x]);
function ost_homeHtml(s, dis) {
  const home = s.home_currency || 'EUR', pk = OFC.info.pack || {};
  if (!pk.currency_editable) return '';
  const field = OFC.info.home_locked ? `<span class="lacts"><b id="os-home-v">${esc(home)}</b></span>` : ofcSel('os-home', home, ost_curs(home));
  return ofcRowF(OFC.info.home_locked ? 'os-home-v' : 'os-home', tr('Home currency'), field, OFC.info.home_locked ? tr(OFC_HC_LOCKED) : tr('Fixed after the first bookings.'), {keep: 1}) + ofcII('home');
}
const ost_fxPair = s => { const home = s.home_currency || 'EUR', cur = s.currency || home; return home === 'EUR' && (cur === 'EUR' || cur === 'USD') ? ['EUR', 'USD'] : cur !== home ? [home, cur] : null; };
function ost_fxHtml(s, dis) {
  const p = ost_fxPair(s); if (!p) return '';
  const usd = p[0] === 'EUR' && p[1] === 'USD', v = usd ? s.fx_usd : (s.fx_rates || {})[p[1]];
  return `<label for="os-fx" class="muted">${usd ? tr('1 € in USD') : esc(tr('1 {0} in {1}', p[0], p[1]))}</label><input id="os-fx" value="${esc(v == null ? '' : fmtNum(v, 4))}" inputmode="decimal" class="numin" ${dis}>`;
}
function ost_fxBody(s, val) {
  const p = ost_fxPair(s); if (!p) return {};
  return p[0] === 'EUR' && p[1] === 'USD' ? {fx_usd: val} : {fx_rates: {...(s.fx_rates || {}), [p[1]]: val}};
}
// 2.113.0 (#2247): the full PUT body of the page (Save all; a single field takes its part of it, ost_part)
function ofcSettingsBody(form) {
  const v = id => $(id, form)?.value ?? '', lines = id => v(id).split('\n').map(x => x.trim()).filter(Boolean);
  const cof = {name: v('#os-name')}; for (const [k] of OFC_CO_FIELDS) if ($('#osc-' + k, form)) cof[k] = v('#osc-' + k).trim();  // 2.470.0 (#3596): a field not shown stays as it is
  if ($('#osc-md_label', form)) cof.md_label = v('#osc-md_label');  // 2.40.0 (#1377)
  const body = {company: {name: v('#os-name'), lines: lines('#os-lines'), contact_lines: lines('#os-contact'), register_lines: lines('#os-register'), bank_lines: lines('#os-bank')},
    company_fields: cof, offer_number_at: v('#os-numat') || 'create',
    ...($('#os-counter', form) ? {offer_counter: v('#os-counter') || 'org'} : {}),  // 2.118.0 A (#2265)
    color: v('#os-color').trim(), ...($('#os-paper', form) ? {paper: v('#os-paper')} : {}),
    ...($('#os-logo-size', form) ? {logo_size: v('#os-logo-size'), logo_pos: v('#os-logo-pos')} : {}),  // 2.406.0 (#3501)
    lang: v('#os-lang'), currency: v('#os-currency'), ...($('#os-fx', form) ? ost_fxBody(OFC.info.settings || {}, ofcNum(v('#os-fx'), true)) : {}),  // 2.424.0 A (#3572): out of the comment again
    ...($('select#os-home', form) ? {home_currency: v('#os-home')} : {}), offer_scheme: v('#os-scheme'), offer_valid_days: ofcNum(v('#os-valid')),
    raw_factor: ofcNum(v('#os-rf'), true),  // 2.113.1 (#2251): producing only through an industry pack's option (below)
    ...($('#os-sf', form) ? {share_factor: ofcNum(v('#os-sf'), true), share_rate: ofcNum(v('#os-sr')), producing_service_id: +v('#os-ps') || null, producing_on: $('#os-prod-on', form)?.checked ? 1 : 0} : {}),
    raw_on: $('#os-raw-on', form)?.checked ? 1 : 0,
    ...($('#os-ls-scheme', form) ? {delivery_scheme: v('#os-ls-scheme'), ...ost_closeBody('dl', v)} : {}),  // 2.434.0 B (#3608): hidden while delivery notes are off
    ...($('#os-accept-on', form) ? {accept_on: $('#os-accept-on', form).checked ? 1 : 0} : {}),  // 2.114.4 B (#2270)
    ...($('#os-sign-offers', form) ? {sign_offers: $('#os-sign-offers', form).checked ? 1 : 0} : {}),  // 2.357.0 C (#3158)
    ...($('#os-portal-docs', form) ? {portal_docs: $('#os-portal-docs', form).checked ? 1 : 0} : {}),  // 2.120.0 B (#2088)
    industry_packs: [...(OFC.info.settings?.industry_packs || [])],  // 2.555.0 (#4664): switched only on the pack cards (each saves at once, ost_part), the page sends the saved list unchanged
    intro_text_id: {de: +v('#os-intro-de') || null, en: +v('#os-intro-en') || null}, closing_text_id: {de: +v('#os-closing-de') || null, en: +v('#os-closing-en') || null},
    rights_default: {time_id: +v('#os-rt') || null, territory_id: +v('#os-rr') || null, media_id: +v('#os-rm') || null}, pack: v('#os-pack'),
    ...($('#os-cr-shared', form) ? {credit_shared: $('#os-cr-shared', form).checked ? 1 : 0} : {}),  // 2.433.0 (#3597)
    invoice_scheme: v('#os-inv-scheme'), credit_scheme: v('#os-cr-scheme'), reminder_scheme: v('#os-rm-scheme'), payment_days: ofcNum(v('#os-paydays')), reminder_fee: ofcNum(v('#os-rmfee')),
    ...($('#os-skonto', form) ? {skonto_pct: ofcNum(v('#os-skonto')) || 0, skonto_days: ofcNum(v('#os-skonto-days')) || 0} : {}),  // 2.120.0 A (#2087)
    ...($('#os-exempt', form) ? {exempt_reason: v('#os-exempt').trim()} : {}),  // 2.296.0 B (#3169)
    reminder_deadline_days: ofcNum(v('#os-rmdays')), small_business: $('#os-small', form)?.checked ? 1 : 0,
    // 2.147.0 (#2460): a function that is off has no fields on the page -- its saved values are never sent (never emptied)
    ...($('#os-einv', form) ? {einvoice_format: v('#os-einv')} : {}),
    ...($('#os-datev', form) ? {datev_email: v('#os-datev').trim(), datev_auto: $('#os-datev-auto', form)?.checked ? 1 : 0} : {}),
    ...($('#os-tax-std', form) ? {tax_rates: Object.fromEntries([['standard', ofcNum(v('#os-tax-std'))], ['reduced', ofcNum(v('#os-tax-red'))]].filter(x => x[1] != null))} : {}),
    ...($('#os-ret', form) ? {retention_years: ofcNum(v('#os-ret'))} : {}),
    ...ost_closeBody('inv', v), ...ost_closeBody('rm', v)};
  if (typeof tpSettingsBody === 'function') Object.assign(body, tpSettingsBody(form));  // 2.47.0 (#1215)
  if (typeof dun_settingsBody === 'function') Object.assign(body, dun_settingsBody(form));  // 2.147.1 B (#2054)
  if (typeof dx_settingsBody === 'function' && $('.dxset', form)) Object.assign(body, dx_settingsBody(form));  // 2.47.3 (#1460); 2.147.0 (#2460): only while DATEV is on
  if (typeof oa_settingsBody === 'function') Object.assign(body, oa_settingsBody(form));  // 2.51.0 A (#1348): agents_read
  return body;
}
// ---- 2.113.0 (#2247): the settings in areas; an area may have several parts in the form's order (ost_p, biz_paint gathers them
// under one heading), fields sit in a fieldset that is disabled for members
const OST_SUBS = [['company', 'building', N_('Company')], ['tax', 'wallet', N_('Bank & taxes')], ['docs', 'file', N_('Documents & numbers')], ['tpl', 'note', N_('Texts & templates')], ['packs', 'pack', N_('Packs')], ['functions', 'sliders', N_('Functions')], ['data', 'archive', N_('Data')], ['access', 'shield', N_('Access')]];  // 2.147.0 (#2460): Functions
// 2.365.2 D (#2789): Bank & taxes -- what the tabs Bookkeeping, Logbook, Cash flow and Cash book set before (tax reserve and VAT
// basis, tax dates, mileage allowance, start balance and monthly check of the cash flow, cash boxes). Every part keeps its own
// route, autosave and undo (data-fg-skip: not a field of this form); the tabs keep a link here (ofcSetLink).
function ost_taxHtml() {
  if (!ofcAdmin()) return '';  // 2.555.0 (#4664): the lock hint stands once on top of the page; the group falls away for members
  return `<div class="ostax" data-fg-skip>${[typeof bka_settingsHtml === 'function' ? bka_settingsHtml() : '' /* 2.470.0 (#3596) */, typeof bkSettingsHtml === 'function' ? bkSettingsHtml() : '',
    typeof ldb_setHtml === 'function' ? ldb_setHtml() : '' /* 2.666.0 (#3461): income statement or balance sheet */,
    typeof txdSectionHtml === 'function' && ofcFeat('books.tax_dates') ? txdSectionHtml() : '',
    typeof lb_rateSetHtml === 'function' ? lb_rateSetHtml() : '', typeof cfs_settingsHtml === 'function' ? cfs_settingsHtml() : '',
    typeof fci_setHtml === 'function' ? fci_setHtml() : '', typeof cb_setHtml === 'function' ? cb_setHtml() : ''].join('')}</div>`;
}
// 2.555.0 (#4664): the calculation rules no longer have their own boxes for the industry packs (the same setting as the switch
// on a pack's card under Packs, which stays the one place): one quiet line names the packs switched on and leads there
function ost_indLinkHtml(s) {
  const on = s.industry_packs || [], all = typeof PKC !== 'undefined' && PKC.packs?.industry || [];
  const nm = c => { const p = all.find(x => x.code === c); return p && typeof pkc_nm === 'function' ? pkc_nm(p) : c; };
  return `<p class="muted ofchint ostind">${esc(on.length ? tr('Industry packs switched on: {0}', on.map(nm).join(', ')) : tr('No industry pack switched on.'))} <button type="button" class="linkbtn" data-ostgo="pkc">${esc(tr('Switch industry packs'))}</button></p>`;
}
// Enter in one of these fields saves it (blur = its change), never the whole settings form
document.addEventListener('keydown', e => { const x = e.target; if (e.key === 'Enter' && !e.isComposing && x.tagName === 'INPUT' && x.closest?.('#ofc-set .ostax')) { e.preventDefault(); x.blur(); } }, true);
// where a setting of a tab moved: a quiet line with the way into Settings > Company & office (events.js data-setgo)
const ofcSetLink = (k, what) => `<p class="muted ofchint ofcsetl">${ic('gear', 's')} <span>${esc(what)}:</span> <button type="button" class="linkbtn" data-setgo="biz-${k}">${esc(tr('Settings › Company & office › {0}', tr(OST_SUBS.find(x => x[0] === k)?.[2] || 'Company & office')))}</button></p>`;
const ost_p = (k, dis) => `<fieldset class="ostp" data-ostp="${k}" ${dis || ''}>`;
const ost_show = k => ($('#s-biz-' + k) || $('#ofc-set #' + k))?.scrollIntoView?.({block: 'start'});  // 2.365.2 (#2789): the areas stand one below the other; 2.555.0 (#4664): or a part's own id (pkc)
// 2.470.0 (#3596): Texts & templates: the catalogues keep their own pages (office/services, office/texts, the document templates);
// here one row each with what it holds and the way there, as far as the person reaches that point of the office
const OST_TPL = [['services', 'list', N_('Services'), 'office/services'], ['texts', 'note', N_('Text blocks'), 'office/texts'], ['gendocs', 'file', N_('Document templates'), 'office/gendocs']];
function ost_tplHtml() {
  const rows = OST_TPL.filter(([k]) => { const i = OFM_ITEMS.find(x => x.key === k); return !!i && i.on() && ofm_ok(i) && !ofm_menuOff(k); }).map(([k, i, n, go]) => {
    const c = Array.isArray(OFC.data[k]) ? OFC.data[k].filter(x => !x.archived).length : null;
    return `<div class="row ostpl"><span class="ostpl-n">${ic(i, 's')} ${esc(tr(n))}${c === null ? '' : ` <span class="muted">${c}</span>`}</span><a class="btn sm" href="#${go}" data-osttpl="${k}">${esc(tr('Open'))}</a></div>`;
  });
  return rows.length ? `<p class="shint keep">${esc(tr('What your quotations, invoices and letters are built from.'))}</p>${rows.join('')}` : '';
}
// ---- 2.365.2 (#2789): the settings live in Settings > Company & office (settings.js biz_draw): the same form #ofc-set with its
// autosave for the current workspace (private = the person's own office), the areas one below the other with a heading each
// (no tab row) and the office's rights as a link; the workspace badge switches the workspace like in the office
function biz_paint() {
  const box = $('#s-biz'); if (!box) return;
  pb_wsFollow();
  if (OFC.infoErr) { box.innerHTML = `<p class="muted">${esc(OFC.infoErr)}</p>`; return; }
  if (!OFC.info) { if (!OFC.infoLoading && !OFC.pbWait) setTimeout(ofcInfo, 0); box.innerHTML = `<div class="muted mhint">${tr('Loading…')}</div>`; return; }
  const rights = typeof orr_html === 'function' && OFC.info.rights;  // 2.470.0 (#3596): members too, their "My rights" (was a tab of the old page)
  // 2.470.0 (#3596): the areas are put in order before the drawing: setHtml keeps input being typed, and a field moved afterwards would lose the focus
  const t = document.createElement('template');
  // 2.555.0 (#4664): no "Applies to" with the workspace menu (it offered "All workspaces"): the settings hold for the area
  // ofcWs() picks, named once as plain text; the switch is the workspace at the top of the app
  t.innerHTML = `<p class="sbizws muted">${esc(tr('Workspace: {0}', biz_areaName()))}</p>${pb_hintHtml()}${typeof ocf_chooseHtml === 'function' ? ocf_chooseHtml(true) : '' /* 2.470.0 (#3596): were on the old page */}${ofcSettingsHtml()}
    ${rights ? `<h3 id="s-biz-rights" class="sbizg">${esc(tr('Rights|office'))}</h3><p class="shint">${esc(tr('Who may see and change which part of the office.'))}</p><div class="row"><a class="btn sm" href="#office/rights" data-bizgo>${ic('shield', 's')} ${esc(tr('Rights in the office'))}</a></div>` : ''}`;
  const form = $('#ofc-set', t.content);
  for (const [k, , n] of OST_SUBS) {
    const fs = form ? $$(`[data-ostp="${k}"]`, form).filter(f => f.children.length) : []; if (!fs.length) continue;
    const h = document.createElement('h3'); h.id = 's-biz-' + k; h.className = 'sbizg'; h.textContent = tr(n);  // 2.555.0 (#4664): the groups h3, their parts h4 (biz_lvl)
    form.append(h, ...fs);
    fs.forEach(f => f.setAttribute('aria-labelledby', h.id));
  }
  biz_lvl(t.content);
  keepFocus(box, () => setHtml(box, t.innerHTML));
  if (!box._bizLvl) { box._bizLvl = new MutationObserver(() => biz_lvl(box)); box._bizLvl.observe(box, {childList: true, subtree: true}); }
  if (S.bizJump) biz_jump(box);
}
// 2.555.0 (#4664): the name of the office area the page sets (the office's own head keeps ofcAreaHtml with its switch)
const biz_areaName = () => OFC.info.personal ? tr('Private|workspace') : (orgLabelOf(OFC.info.org_id) || wsName(ofcWs()));
// 2.555.0 (#4664): the heading levels of the page: group h3 (biz_paint), the parts one level below it. The part functions write
// h3 (and h4 inside) as on their own office pages, so here every h3 of a part becomes h4 and every h4 h5, once (data-hl), also
// when a part draws itself again later (the observer in biz_paint); id, class and content stay
function biz_lvl(root) {
  for (const h of root.querySelectorAll('#ofc-set .ostp h3:not([data-hl]), #ofc-set .ostp h4:not([data-hl])')) {
    const n = document.createElement(h.tagName === 'H3' ? 'h4' : 'h5');
    for (const a of h.attributes) n.setAttribute(a.name, a.value);
    n.dataset.hl = '1'; n.append(...h.childNodes); h.replaceWith(n);
  }
}
// 2.365.2 D (#2789): settingsModal('biz-<part>') (settings.js sets S.bizJump) scrolls once to the part's heading or to one of
// these places, with the soft ring of the settings search
const BIZ_AT = {peppol: '#pep-set', agents: '#os-agents-read', datev: '.dxset'};
function biz_jump(box) {
  const k = S.bizJump; S.bizJump = null;
  const at = () => $(BIZ_AT[k] || '#s-biz-' + k, box) || $('#s-biz-' + (k === 'peppol' ? 'docs' : k === 'agents' ? 'access' : k === 'datev' ? 'data' : k), box);
  setTimeout(() => {
    const el = at(), r = el && (el.closest('.row, details, h3, h4, h5') || el); if (!r) return;
    for (let det = r.closest('details'); det; det = det.parentElement?.closest('details')) det.open = true;
    r.scrollIntoView?.({block: el.matches('h3, h4') ? 'start' : 'center'}); r.classList.add('sflash'); setTimeout(() => r.classList.remove('sflash'), 1600);
  }, 30);
}
// every field saves itself: the part of the PUT body that belongs to it (null = no setting: the country's text field, search, ...);
// a group the server keeps together goes as one (the DATEV booking export)
const ost_closeBody = (k, v) => { const key = OST_CLOSE.find(x => x[0] === k)[1], o = {}; for (const [lg] of ofcLangList()) { const id = '#' + ost_closeId(k, lg); if ($(id)) o[`${key}_${lg}`] = v(id); } return o; };
const OST_FLAT = {'os-color': 'color', 'os-lang': 'lang', 'os-currency': 'currency', 'os-home': 'home_currency', 'os-scheme': 'offer_scheme', 'os-numat': 'offer_number_at',
  'os-valid': 'offer_valid_days', 'os-small': 'small_business', 'os-inv-scheme': 'invoice_scheme', 'os-cr-scheme': 'credit_scheme', 'os-cr-shared': 'credit_shared', 'os-rm-scheme': 'reminder_scheme',
  'os-paydays': 'payment_days', 'os-rmfee': 'reminder_fee', 'os-rmdays': 'reminder_deadline_days', 'os-einv': 'einvoice_format', 'os-datev': 'datev_email',
  'os-datev-auto': 'datev_auto', ...Object.fromEntries(OST_CLOSE.flatMap(([k, key]) => ['de', 'en', 'nl', 'fr', 'es', 'it'].map(lg => [ost_closeId(k, lg), `${key}_${lg}`]))),
  'os-prod-on': 'producing_on', 'os-pq': 'prod_quotient', 'os-ps': 'producing_service_id', 'os-pr': 'producing_rate',
  'os-counter': 'offer_counter',  // 2.118.0 A (#2265)
  'os-paper': 'paper',  // 2.357.0 A (#3156)
  'os-logo-size': 'logo_size', 'os-logo-pos': 'logo_pos',  // 2.406.0 (#3501)
  'os-ovd-on': 'overdue_notice', 'os-dun-on': 'dunning_suggest', 'os-dun-days': 'dunning_grace_days', 'os-girocode': 'girocode',  // 2.147.1 B (#2054): each saves alone
  'os-dun-int': 'dunning_interest', 'os-dun-flat': 'dunning_flat_fee', 'os-dun-base': 'base_rate', 'os-dun-kind': 'dunning_client_kind',  // 2.355.0 D (#2846)
  'os-sf': 'share_factor', 'os-sr': 'share_rate',  // 2.113.1 (#2251): producing by amount (film pack option)
  'os-raw-on': 'raw_on', 'os-rf': 'raw_factor', 'os-pack': 'pack', 'os-parts-inv': 'parts_invoice_mode', 'os-parts-t-de': 'parts_summary_title_de',
  'os-parts-t-en': 'parts_summary_title_en', 'os-agents-read': 'agents_read', 'os-ret': 'retention_years'};  // 2.147.0 (#2461): os-ret
const OST_SUB = {'os-intro-de': ['intro_text_id', 'de'], 'os-intro-en': ['intro_text_id', 'en'], 'os-closing-de': ['closing_text_id', 'de'], 'os-closing-en': ['closing_text_id', 'en'],
  'os-rt': ['rights_default', 'time_id'], 'os-rr': ['rights_default', 'territory_id'], 'os-rm': ['rights_default', 'media_id'],
  'os-tax-std': ['tax_rates', 'standard'], 'os-tax-red': ['tax_rates', 'reduced']};  // 2.147.0 (#2461)
const OST_CO = {'os-lines': 'lines', 'os-contact': 'contact_lines', 'os-register': 'register_lines', 'os-bank': 'bank_lines'};
function ost_part(el, full) {
  const id = el.id || '';
  if (id === 'os-name') return {company: {name: full.company.name}, company_fields: {name: full.company_fields.name}};
  if (el.dataset.co && el.dataset.co in full.company_fields) return {company_fields: {[el.dataset.co]: full.company_fields[el.dataset.co]}};
  if (OST_CO[id]) return {company: {[OST_CO[id]]: full.company[OST_CO[id]]}};
  if (OST_FLAT[id] && OST_FLAT[id] in full) return {[OST_FLAT[id]]: full[OST_FLAT[id]]};
  if (id === 'os-fx') return 'fx_usd' in full ? {fx_usd: full.fx_usd} : {fx_rates: full.fx_rates || {}};  // 2.189.0 (#2475)
  if (OST_SUB[id] && OST_SUB[id][0] === 'tax_rates') return {tax_rates: full.tax_rates || {}};  // 2.147.0 (#2461): both rates at once (an empty one = the pack's)
  if (OST_SUB[id]) { const [k, f] = OST_SUB[id]; return {[k]: {[f]: full[k][f]}}; }
  if (el.dataset.feat) return {features_off: ocf_off(el.dataset.feat, !el.checked)};  // 2.147.0 (#2460): one function on / off
  if (el.dataset.ocm) return {menu_off: ocm_off(el.dataset.ocm, !el.checked)};  // 2.440.0 (#3609): one point of the office menu
  if (el.dataset.ccb) return {client_blocks_off: ccb_off(el.dataset.ccb, !el.checked)};  // 2.435.0 A (#3600): one block of the client card
  // an industry pack box: only this pack switches (the list of the others stays as saved, also when not all boxes are drawn)
  if (el.dataset.pkcOn) return {industry_packs: ost_packs(el.dataset.pkcOn, el.checked)};  // 2.113.0 (#2246): the switch on a pack's card
  if (el.closest('.dxset') && full.datev_extf) return {datev_extf: full.datev_extf};
  return /^os-/.test(id) ? full : null;  // a settings field this map does not know yet (e.g. added later): the whole page, never a silent loss
}
const ost_packs = (code, on) => { const l = (OFC.info.settings.industry_packs || []).filter(x => x !== code); return on ? [...l, code] : l; };
// what the part was before (for undo): the saved settings
function ost_old(part) {
  const s = OFC.info.settings || {}, cf = OFC.info.company_fields || {}, cp = x => JSON.parse(JSON.stringify(x ?? null)), o = {};
  for (const [k, v] of Object.entries(part)) {
    if (k === 'company_fields') o[k] = Object.fromEntries(Object.keys(v).map(f => [f, cf[f] ?? '']));
    else if (k === 'tax_rates') o[k] = cp(s[k] || {});  // 2.147.0 (#2461)
    else if (['company', 'intro_text_id', 'closing_text_id', 'rights_default'].includes(k)) o[k] = Object.fromEntries(Object.keys(v).map(f => [f, cp((s[k] || {})[f] ?? (k === 'company' ? (f === 'name' ? '' : []) : null))]));
    else o[k] = cp(s[k]);
  }
  return o;
}
async function ost_put(b) {
  // 2.528.0 (#4305 A3): with the version this page loaded; moved on and this field was not changed elsewhere = sent again on
  // top of the current settings (the page is drawn again: pk true); changed elsewhere too = the hint, the input stays
  const seen = ost_old(b);
  let j, stale = false;
  try { j = await oxaPut(b); }
  catch (x) {
    if (!oxaStale(x)) throw x;
    const cur = await api('GET', '/api/office/settings');
    OFC.info.settings = cur.settings; OFC.info.company_fields = cur.company_fields || OFC.info.company_fields; stale = true;
    if (JSON.stringify(ost_old(b)) !== JSON.stringify(seen)) { const e = new Error(tr('Someone else changed this setting meanwhile. Check it and save again.')); e.oxaRedraw = true; throw e; }  // the caller keeps the input, then draws
    j = await oxaPut(b);
  }
  const pk = stale ? null : OFC.info.settings?.pack;
  OFC.info.settings = j.settings; OFC.info.company_fields = j.company_fields || OFC.info.company_fields; OFC.info.number_preview = j.number_preview; OFC.log = null;
  if (j.features) OFC.info.features = j.features;  // 2.147.0 (#2460): menus, tabs and buttons follow at once
  if ('home_locked' in j) OFC.info.home_locked = j.home_locked;  // 2.189.0 (#2475)
  if (j.pack && j.settings?.pack === pk) OFC.info.pack = j.pack;
  return j.settings?.pack !== pk;
}
// what changes more than the field itself is drawn again (pack: its tax rates; currency: the symbols; industry packs: the cards)
const ost_redraw = (part, pk) => pk ? ofcInfo(true) : ['currency', 'home_currency', 'industry_packs', 'features_off', 'menu_off', 'tax_rates', 'retention_years', 'credit_shared'].some(k => k in part) ? ofcDraw() : null;  // 2.147.0 (#2460, #2461)
const OST = {q: Promise.resolve()};
function ost_save(el) {
  const form = el.closest?.('#ofc-set');
  if (!form || OFC.info?.role !== 'admin' || el.disabled || (el.closest('[data-fg-skip]') && !el.dataset.pkcOn) || el.type === 'file') return;
  let part = null; try { part = ost_part(el, ofcSettingsBody(form)); } catch { part = null; }
  if (!part) return;
  const v = fgVal(el); if (el._ostV === v) return;  // (change and focusout of the same edit)
  el._ostV = v;
  const old = ost_old(part), fk = form.dataset.fg, k = fgKey(el);
  OST.q = OST.q.then(async () => {
    try {
      // 2.147.0 (#2462): a new country pack is confirmed first (what is hidden, open documents); no = the old choice again
      if ('pack' in part && part.pack !== OFC.info.settings?.pack && typeof ocf_confirmSwitch === 'function' && !await ocf_confirmSwitch(part.pack)) {
        el.value = OFC.info.settings?.pack || ''; el._ostV = undefined; return;
      }
      const pk = await ost_put(part);
      if (el.type === 'checkbox' || el.type === 'radio') el.defaultChecked = el.checked;
      else if (el.tagName === 'SELECT') [...el.options].forEach(o => { o.defaultSelected = o.selected; });
      else el.defaultValue = el.value;
      if (FG.d[fk]) delete FG.d[fk].f[k];
      const e = histAdd({label: tr('Settings'), undo: () => ost_back(old), redo: () => ost_back(part)});  // one undo step per field
      await ost_redraw(part, pk);
      ost_mark(el.isConnected ? el : ost_find(el), 'ok', e);
    } catch (x) {
      el._ostV = undefined;
      const d = FG.d[fk] || (FG.d[fk] = {f: {}}); d.f[k] = v;  // the value stays (a redraw puts it back, closing the page asks)
      if (x?.oxaRedraw) await ofcInfo(true);  // 2.528.0 (#4305 A3): changed elsewhere: the current settings, the typed value on top
      ost_mark(el.isConnected ? el : ost_find(el) || el, 'err', tr('Not saved: {0}', ofcErrHere(x)));  // 2.528.0 (#4305 A3): the field drawn again (changed elsewhere); 2.855.0 (#5451): said once, at the field
    }
  });
  return OST.q;
}
async function ost_back(b) {
  const a = document.activeElement; if (a?.closest?.('#ofc-set')) a.blur();  // (a redraw keeps the value of a focused field)
  try { const pk = await ost_put(b); if (pk) await ofcInfo(true); else ofcDraw(); } catch (x) { if (x?.oxaRedraw) { toast(x.message); await ofcInfo(true); } /* else shown by api() */ }  // 2.528.0 (#4305 A3)
  return {skipped: []};
}
// the field again after a redraw
const ost_find = el => el.id ? $('#ofc-set #' + CSS.escape(el.id)) : el.dataset.pkcOn ? $(`#ofc-set [data-pkc-on="${CSS.escape(el.dataset.pkcOn)}"]`) : null;
// "Saved" (with Undo) or the error at the field, for a few seconds
function ost_mark(el, st, x) {
  const row = el?.closest('.row, .pkc-on') || el?.closest('label') || el?.parentElement; if (!row) return;
  let m = row.querySelector(':scope > .ostok');
  if (!m) { m = document.createElement('span'); m.className = 'ostok'; m.setAttribute('role', 'status'); row.append(m); }
  el.toggleAttribute('aria-invalid', st === 'err'); m.classList.toggle('err', st === 'err');
  m.innerHTML = st === 'err' ? `${ic('alert', 's')}<span>${esc(x)}</span>` : `${ic('check', 's')}<span>${esc(tr('Saved'))}</span>${x ? `<button type="button" class="linkbtn" data-ost-undo>${esc(tr('Undo'))}</button>` : ''}`;
  m._e = st === 'ok' ? x : null; m.classList.add('on');
  clearTimeout(m._t); if (st === 'ok') m._t = setTimeout(() => { m.classList.remove('on'); m._e = null; }, 4000);
  OST.mk = st === 'ok' && el.id ? {m, id: el.id} : null;
}
// 2.440.0 (#3782): a redraw after the save (a part that finished loading) took "Saved" away: the mark goes back to its field
function ost_markBack() {
  const k = OST.mk; if (!k || k.m.isConnected || !k.m.classList.contains('on')) return;
  const row = $(`#ofc-set [id="${k.id}"]`)?.closest('.row, .pkc-on');  // 2.368.4: an own id (os-...), no CSS.escape needed
  if (row && !row.querySelector(':scope > .ostok')) row.append(k.m);
}
// 2.40.0 (#1378): one upload helper for the office (FormData + the CSRF header X-Requested-With via rawFetch, the server's error text)
const ofcUpload = (url, file) => { const fd = new FormData(); fd.append('file', file); return rawFetch('POST', url, fd); };
const ofcUpErr = x => ofcErrTxt(x);  // 2.855.0 (#5451)
// 2.855.0 (#5451): an error of the office is said once and in plain words. api() already says a refused or failed request
// (it marks the error shown); ofcErr says only what nobody said yet (an own check, rawFetch), an empty text as a plain sentence.
// ofcErrHere = the text for a place on the page (a dialog's .aerr, an empty list): api()'s toast of the same text goes, the
// place keeps it (one message, where it belongs)
const ofcErrTxt = (/** @type {any} */ x) => x instanceof Offline ? tr('Offline: only works again with a connection') : (x?.message && x.message !== 'auth' && x.message !== 'down' ? String(x.message) : tr('That did not work. Please try again.'));
/** @param {any} x */
function ofcErr(x) {
  if (x?.shown || x?.message === 'auth') return;
  toast(ofcErrTxt(x));
  if (x && typeof x === 'object') x.shown = true;
}
// 2.855.0 (#5451): mail sending missing on the server, in plain words (the variable only in the server's docs)
const ofcNoMail = () => tr('E-mail sending is not set up on this server yet: whoever runs the server sets it up.');
/** @param {any} x @returns {string} */
function ofcErrHere(x) {
  const t = ofcErrTxt(x), el = x?.shown && $('#toast');
  if (el && !el.classList.contains('hidden') && el.textContent.trim().startsWith(t)) el.classList.add('hidden');
  if (x && typeof x === 'object') x.shown = true;
  return t;
}
async function ofcLogoUpload(file) {
  if (!file) return;
  // 2.357.0 B (#3179): a logo below 300 px prints small (never scaled up beyond 200 dpi) -- say so after the upload
  let w = 0;
  try { const bm = await window.createImageBitmap(file); w = bm.width; bm.close?.(); } catch { w = 0; }
  try { await ofcUpload('/api/office/logo', file); await ofcInfo(true); toast(w && w < 300 ? tr('Logo saved. It is only {0} px wide and prints small; 600 px or more print sharp.', w) : tr('Logo saved')); }
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
  if (a === 'pb-transfer') { pb_transfer(); return; }  // 2.137.0 D (#1981)
  if (a === 'org-out') { ofc_orgOut(); return; }  // 2.356.0 A (#2926)
  if (a === 'pb-ws') { if (ofc_sp()) go('office/s/' + b.dataset.ws); else if (typeof wsSet === 'function') wsSet(b.dataset.ws, {keep: true}); return; }  // 2.577.0 (#4638): under "All" the area's address  // 2.47.3 (#1360); 2.397.0 (#3404): the office stays
  if (a === 'new') { e.preventDefault(); ofcModal(b.dataset.kind, null); }
  else if (a === 'open') { e.preventDefault(); const r = ofcRow(b.dataset.kind, +b.dataset.id); if (r) ofcModal(b.dataset.kind, r); }
  else if (a === 'log-all' || a === 'log-ag') { e.preventDefault(); OFC.logAg = a === 'log-ag'; ofcDraw(); }  // 2.51.0 A (#1348)
  else if (a === 'import') { e.preventDefault(); $('#os-import')?.click(); }  // 2.591.0 (#4894): the input's change reads the file (a drop onto the window too, dropany.js)
  else if (a === 'chain') { e.preventDefault(); try { OFC.chain = await api('GET', '/api/office/log/chain'); } catch (x) { ofcErr(x); OFC.chain = null; } ofcDraw(); }  // 2.531.0 (#4497)
  else if (a === 'log') { e.preventDefault(); try { const j = await api('GET', '/api/office/log?limit=50'); OFC.log = j.log || []; } catch (x) { ofcErr(x); OFC.log = []; } ofcDraw(); }
  else if (a === 'scheme-reset') { e.preventDefault(); const inp = $('#' + b.dataset.for); if (!inp || inp.disabled) return;  // 2.114.2 (#2264): last saved valid scheme (the server fills the default when none is saved)
    inp.value = OFC.info.settings?.[b.dataset.kind + '_scheme'] || ''; inp.focus(); inp.dispatchEvent(new Event('input', {bubbles: true})); }
  else if (a === 'bb') { e.preventDefault(); const inp = $('#' + b.dataset.for); if (!inp || inp.disabled) return;  // 2.40.0 (#1382): a building block at the caret
    const p0 = inp.selectionStart ?? inp.value.length, p1 = inp.selectionEnd ?? p0, t = b.dataset.bb;
    inp.value = inp.value.slice(0, p0) + t + inp.value.slice(p1); inp.focus(); inp.setSelectionRange(p0 + t.length, p0 + t.length); inp.dispatchEvent(new Event('input', {bubbles: true})); }
  else if (a === 'logo-del') { e.preventDefault(); try { await api('DELETE', '/api/office/logo'); await ofcInfo(true); toast(tr('Removed')); } catch (x) { ofcErr(x); } }
  else if (a === 'name-take') { e.preventDefault(); const el = $('#os-name'); if (el) { ost_save(el); b.closest('.ofcnamesug')?.remove(); } }  // 2.356.0 D (#3006): the organisation's name as the company name
});
document.addEventListener('submit', e => { const f = e.target.closest?.('#ofc-set'); if (!f) return; e.preventDefault(); if (OFC.info?.role === 'admin') ofcSaveSettings(f); });
// 2.113.0 (#2247): an area of the settings; a field saves on its change (boxes, choices, the country) or when it is left
document.addEventListener('click', e => {
  if (e.target.closest?.('[data-osttpl="gendocs"]') && typeof DT !== 'undefined') DT.view = 'templates';  // 2.470.0 (#3596): the templates of the documents' page
  const g = e.target.closest?.('#ofc-set [data-ostgo]'); if (g) { e.preventDefault(); ost_show(g.dataset.ostgo); return; }  // 2.147.0 (#2460): "Change country"
  const u = e.target.closest?.('#ofc-set [data-ost-undo]'); if (!u) return;
  e.preventDefault(); const m = u.closest('.ostok');
  if (m?._e && HIST.undo[HIST.undo.length - 1] === m._e) { m.classList.remove('on'); histStep('undo', 1, [m._e]); }  // 2.905.0 (#5255): exactly this step
});
document.addEventListener('change', e => { if (e.target.closest?.('#ofc-set')) ost_save(e.target); });
document.addEventListener('mousedown', e => { if (e.target.closest?.('#ofc-set [data-ofc="bb"]')) e.preventDefault(); });  // a building block keeps the scheme field focused (no save in between)
// 2.298.0 A1 (#3186): the building blocks show while their scheme field or one of them has the focus (class on, next to the
// CSS :focus-within, which a window without focus does not match)
const ofcBbFocus = () => { const a = document.activeElement; $$('#ofc-set .ofcbb').forEach(bb => bb.classList.toggle('on', !!a && (bb.contains(a) || !!bb.previousElementSibling?.contains(a)))); };
document.addEventListener('focusin', e => { if (e.target.closest?.('#ofc-set')) ofcBbFocus(); });
document.addEventListener('focusout', e => { if (e.target.closest?.('#ofc-set')) setTimeout(ofcBbFocus, 0); });
document.addEventListener('focusout', e => { const t = e.target; if (/^(INPUT|TEXTAREA)$/.test(t.tagName) && !/^(checkbox|radio|file|hidden)$/.test(t.type) && t.closest('#ofc-set') && t.value !== t.defaultValue) ost_save(t); });
// 2.138.2 B (#2395): a short multi-line field (company name) grows with its text up to `max` rows, no inner scrollbar
function ofcGrow(ta, max = 3) {
  const lo = Math.max(1, +ta.dataset.growMin || 1);  // 2.431.0 B (#3594): a field may start with more than one row
  ta.rows = lo;
  const n = Math.max(lo, String(ta.value).split('\n').length);
  ta.rows = Math.min(max, n);
  while (ta.rows < max && ta.scrollHeight > ta.clientHeight + 1) ta.rows++;
}
// 2.296.0 D (#3172): true when a brand colour is too light for text on white (contrast < 4.5, as the PDF writer judges it)
function ofcColorLight(c) {
  const m = /^#([0-9a-fA-F]{6})$/.exec(String(c || '').trim());
  if (!m) return false;
  const l = [0, 2, 4].map(i => { const v = parseInt(m[1].slice(i, i + 2), 16) / 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
  return 1.05 / (0.2126 * l[0] + 0.7152 * l[1] + 0.0722 * l[2] + 0.05) < 4.5;
}
document.addEventListener('input', e => {
  const t = e.target;
  if (t.dataset?.grow) ofcGrow(t, +t.dataset.grow || 3);
  if (t.id === 'ofc-q') { OFC.q = t.value; const w = $('#view .ofclistw'); if (w && !OFCP.stale) fl_set(w, ofcListBody(w.dataset.kind)); else ofcDraw(); }  // 2.144.2 B (#1644)
  else if (t.id === 'os-color') { const nt = $('#os-color-note'); if (nt) nt.hidden = !ofcColorLight(t.value); const sw = $('.ofcsw'); if (sw) sw.style.background = /^#[0-9a-fA-F]{6}$/.test(t.value.trim()) ? t.value.trim() : 'var(--accent)'; }
  else if (t.dataset?.scheme) ofcSchemePv(t);  // 2.40.0 (#1382): every number scheme with its preview
});
document.addEventListener('change', e => {
  const t = e.target;
  if (t.id === 'ofc-arch') { OFC.arch = t.checked; ofcDraw(); }
  else if (t.id === 'os-logo') { ofcLogoUpload(t.files[0]); t.value = ''; }
  else if (t.id === 'os-import' && t.files?.length) { ofcImport(t.files[0], $('#os-overwrite')?.checked); t.value = ''; }  // 2.591.0 (#4894)
  else if (t.id === 'os-counter') { const sc = $('#os-scheme'); if (sc) ofcSchemePv(sc, true); }  // 2.118.0 A (#2265): the preview of the counter chosen
});
