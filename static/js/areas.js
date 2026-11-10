/* Kalmido web client: the areas (#1187). Modules that belong together are ONE entry in the sidebar, the tab bar and
   Settings > Modules, and one page with tabs for their parts: Office (office & finance, contacts, clients), Time (time
   tracking, focus timer), Review (review & journal, statistics), Home (home & life, family). Each part keeps its own
   route (#pomo, #stats, #contacts, #client/3 …), so every old link opens the area on that tab; the switches stay the old
   module keys (settings "features"), an area is on while one of its parts is.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// 2.44.0 (#1187): [area, icon, name, parts: [route, icon, name, on(), feature keys]]; the area's id is its first part
const MG_AREAS = [
  ['office', 'receipt', N_('Office|area'), [['office', 'receipt', N_('Office & finance'), () => officeOn(), () => ['office']],
    ['contacts', 'users', N_('Contacts'), () => feat('contacts'), () => ['contacts']], ['clients', 'brief', N_('Clients'), () => clientsOn(), () => ['clients']]]],
  ['time', 'clock', N_('Time|area'), [['time', 'clock', N_('Time tracking'), () => timeOn(), () => ['time']], ['pomo', 'timer', N_('Focus timer'), () => feat('pomo'), () => ['pomo']]]],
  ['review', 'journal', N_('Review|area'), [['review', 'journal', N_('Review & journal'), () => feat('review'), () => ['review']], ['stats', 'chart', N_('Statistics'), () => feat('stats'), () => ['stats']]]],
  ['life', 'home', N_('Home|area'), [['life', 'home', N_('Home & life'), () => lifeOn(), () => LIFE_MODS], ['family', 'family', N_('Family'), () => famOn(), () => ['family']],
    ['budget', 'wallet', N_('Budget'), () => feat('budget'), () => ['budget']]]],  // 2.72.0 (#1333): the household budget (budget.js)
  // 2.172.0 B (#2679 #2677): Reading, out of Home -- read later (readlater.js), feeds (2.85.0 B, #1162: feeds.js) and bookmarks
  // (2.97.0 A, #1950: bookmarks.js); the switches stay the modules reading (read later + bookmarks) and feeds
  ['reading', 'bookmark', N_('Reading|area'), [['reading', 'book', N_('Read later'), () => feat('reading'), () => ['reading']],
    ['feeds', 'news', N_('Feeds'), () => feat('feeds'), () => ['feeds']],
    ['bookmarks', 'bookmark', N_('Bookmarks'), () => feat('reading'), () => ['reading']]]],
  // 2.48.0 (#1207, #1111): the file store with its parts files (ablage.js) and documents (docs.js); 2.752.0 (#4887): ONE area
  // "Files" with one tree, the part docs is only the documents' switch (no entry of its own, MG_NONAV; routes #ablage/docs …)
  ['ablage', 'folder', N_('Files'), [['ablage', 'folder', N_('Files'), () => ab_on(), () => ['files']],
    ['docs', 'file', N_('Documents'), () => typeof viewDocs === 'function' && feat('docs'), () => ['docs']]]]];
const MG_IDS = MG_AREAS.map(a => a[0]);
const mg_area = id => MG_AREAS.find(a => a[0] === id) || null;
const mg_areaOf = mod => MG_AREAS.find(a => a[3].some(p => p[0] === mod)) || null;
const mg_parts = a => a ? a[3].filter(p => p[3]()) : [];
const mg_on = id => mg_parts(mg_area(id)).length > 0;
const mg_feats = id => (mg_area(id)?.[3] || []).flatMap(p => p[4]());
// 2.171.0 (#2676): the area's switch is on only with every part on; some on = "partly" (the switch half, the row not dimmed)
const mg_allOn = id => { const f = new Set(pma_full()), ks = mg_feats(id).filter(k => f.has(k)); return ks.length > 0 && ks.every(k => feat(k)); };
// the tab the area opens with: the one last used on this device (LS mgTab), else its first switched-on part
function mg_target(id) {
  const ps = (a => [...mg_partsMenu(a), ...mg_partsShown(a)])(mg_area(id)), last = (LS.get('mgTab', {}) || {})[id];  // 2.173.0 A (#2680): an organisation's view: its parts only; 2.418.0 (#3560): the menu's first
  if (id === 'office' && !isMobile() && ps.some(p => p[0] === 'office')) return ofm_entry().go;  // 2.161.2 (#2616)
  return (ps.find(p => p[0] === last) || ps[0] || mg_parts(mg_area(id))[0] || [id])[0];  // 2.353.0 D (#2759): only a part without an entry on: that one
}
function mg_seen(mod) {
  const a = mg_areaOf(mod); if (!a) return;
  const o = LS.get('mgTab', {}) || {}; if (o[a[0]] !== mod) { o[a[0]] = mod; LS.set('mgTab', o); }
}
// an old link to a part that is off now opens the area on another tab (null: nothing of the area is on)
function mg_alt(mod) { const a = mg_areaOf(mod); return a && !a[3].find(p => p[0] === mod)[3]() && mg_parts(a).length ? mg_target(a[0]) : null; }
// the header: the area's name above its tabs; with one part on (no tabs) that part's own name stays
const mg_title = mod => { const a = mg_areaOf(mod); return a && mg_partsShown(a).length > 1 ? tr(mg_nameKey(a)) : ''; };
// the tabs on top of an area's page (only with two parts or more on); the route of a part = data-go
function mg_tabsHtml(mod) {
  const a = mg_areaOf(mod); if (!a || S.me?.kid) return '';
  mg_seen(mod);
  if (a[0] === 'office') { setTimeout(ofr_after, 0); return ofm_menuHtml(mod); }  // 2.87.9 (#1917): the office menu (a phone's; a computer: ofr_wrap, the points in the panel of sidebar B)
  const sb = sbb_on(), ps = mg_partsMenu(a);  // 2.224.0 A (#2817): a part hidden in the sidebar settings is no tab either; 2.418.0 (#3560): on a phone too (the menu's order, hidden points out)
  if (ps.length < 2 || sb && !sbb_noPan(a[0])) return '';  // 2.152.2 (#2618): a computer: the parts are in the panel of sidebar B (2.224.0 A #2817: areas without a panel keep their tabs)
  return `<div class="seg mgtabs" role="tablist" aria-label="${esc(tr(mg_nameKey(a)))}" data-mgtabs="${a[0]}">${ps.map(([m, i, n]) => `<button type="button" role="tab" data-go="${m}" aria-selected="${m === mod}" class="${m === mod ? 'on' : ''}">${ic(i, 's')}<span>${esc(tr(mg_partName(m, n)))}</span>${m === 'time' && S.timer || m === 'pomo' && S.pomo ? '<span class="recdot"></span>' : ''}</button>`).join('')}</div>`;
}
// 2.98.0 C (#2180): the office on a computer = the page with its own heading (2.152.2, #2617: its points in the panel)
const mg_wrap = (mod, html) => mg_areaOf(mod)?.[0] === 'office' && !isMobile() && !S.me?.kid ? ofr_wrap(mod, html) : mg_tabsHtml(mod) + html;
// ---- 2.87.9 (#1917): the office menu. The area Office is four groups (Sell, Money, On the road, Administration) instead of
// two tab rows; a part joins its group with an entry {key, go, icon, name, group, on, adm} (adm = admins of the office only).
// Empty groups and points without rights stay hidden. Computer: the groups side by side on top (sticky); phone: the start
// page office/start with four tiles and the figures, on every other page the path "Office › group" (back to the tiles) and
// the group's points. The old routes stay (#office/offers, #clients, #contacts …); the path on detail pages is text only.
// 2.98.0 C (#2180): three groups (On the road is gone: travel expenses -> Money, framework contracts -> Sell); services and
// text blocks are no menu points any more but Settings > Company & office > Texts & templates (2.470.0, #3596), their routes stay
// 2.489.0 (#2664, decision #2647): the address book is no part of Sell any more but an entry of its own (group 'book', [3] = 1:
// no heading, never folded), below the groups and right above its folders
/** @type {Array<[string, string, string, number?]>} */
const OFM_GROUPS = [['sell', 'tag', N_('Sell|office')], ['money', 'wallet', N_('Money|office')], ['admin', 'sliders', N_('Administration|office')], ['book', 'users', N_('Address book'), 1]];
const ofm_ofc = () => officeOn();
const ofm_sub = () => typeof OFC !== 'undefined' && !!OFC.info?.submit;  // 2.356.0 D (#3129)
const ofm_cc = () => typeof OFC !== 'undefined' && !!OFC.info?.cards;  // 2.444.0 (#3447): the person holds a card here
const OFM_ITEMS = [
  {key: 'pipeline', go: 'office/pipeline', icon: 'target', name: N_('Pipeline'), group: 'sell', on: ofm_ofc, adm: 1},
  {key: 'offers', go: 'office/offers', icon: 'file', name: N_('Quotations'), group: 'sell', on: ofm_ofc},  // 2.380.0 B (#3409): quotations and invoices are two points
  {key: 'invoices', go: 'office/invoices', icon: 'receipt', name: N_('Invoices'), group: 'sell', on: ofm_ofc, lvk: 'offers'},  // the rights of the quotations' area
  {key: 'clients', go: 'clients', icon: 'brief', name: N_('Clients'), group: 'sell', on: () => clientsOn()},
  {key: 'contacts', go: 'contacts', icon: 'users', name: N_('Address book'), group: 'book', on: () => feat('contacts')},  // 2.489.0 (#2664): own entry
  {key: 'cashflow', go: 'office/cashflow', need: 'money.cashflow', icon: 'trend', name: N_('Cash flow'), group: 'money', on: ofm_ofc, adm: 1},
  {key: 'kpi', go: 'office/kpi', need: 'money.kpi', icon: 'chart', name: N_('Figures'), group: 'money', on: ofm_ofc, adm: 1},
  {key: 'travel', go: 'office/travel', need: 'money.travel', icon: 'plane', name: N_('Travel expenses'), group: 'money', on: ofm_ofc, adm: 1},
  {key: 'services', go: 'office/services', icon: 'list', name: N_('Services'), group: 'admin', on: ofm_ofc, tpl: 1},
  {key: 'equipment', go: 'office/equipment', icon: 'camera', name: N_('Equipment'), group: 'admin', on: ofm_ofc},
  {key: 'contracts', go: 'office/contracts', icon: 'file', name: N_('Framework contracts'), group: 'sell', on: ofm_ofc},
  {key: 'texts', go: 'office/texts', icon: 'note', name: N_('Text blocks'), group: 'admin', on: ofm_ofc, tpl: 1},
  {key: 'settings', go: 'office/settings', icon: 'gear', name: N_('Settings'), group: 'admin', on: ofm_ofc},
  // 2.152.2 (#2632): the parts of the office's own scripts too (their OFC_TABS entries only bring the tab's content), so the
  // menu / panel shows the same points on #clients, #contacts, #office and #time, before the office is loaded as after
  {key: 'gendocs', go: 'office/gendocs', icon: 'file', name: N_('Letters & contracts'), group: 'sell', on: ofm_ofc, adm: 1},  // 2.489.0 (#2664, decision #2646): Schreiben & Verträge, as the office's own tab
  {key: 'letters', go: 'office/letters', icon: 'mail', name: N_('Correspondence'), group: 'sell', on: ofm_ofc, adm: 1},
  {key: 'bank', go: 'office/bank', icon: 'bank', name: N_('Bank'), group: 'money', on: ofm_ofc, adm: 1},
  {key: 'cards', go: 'office/cards', icon: 'card', name: N_('Credit cards'), group: 'money', on: ofm_ofc, get adm() { return ofm_cc() ? 0 : 1; }},  // 2.444.0 (#3447): also for the holder of a card
  {key: 'books', go: 'office/books', icon: 'book', name: N_('Bookkeeping'), group: 'money', on: ofm_ofc, adm: 1},
  // 2.276.0 A (#3039): the receipts (upload + list, office_receipts.js rcp_tabHtml) for everybody with the bookkeeping (lvk = its area)
  // 2.356.0 D (#3129): the same point is "Submit receipt" for the people who may hand in receipts but do not see the
  // bookkeeping (GET /api/office/settings submit; office_receipts.js rsb_tabHtml): shown by their right in the area receipts
  {key: 'receipts', go: 'office/receipts', icon: 'ticket', get name() { return ofm_sub() ? N_('Submit receipt') : N_('Receipts'); }, group: 'money', on: ofm_ofc,
    get adm() { return ofm_sub() ? 0 : 1; }, get lvk() { return ofm_sub() ? 'receipts' : 'books'; }},
  {key: 'subs', go: 'office/subs', need: 'money.subs', icon: 'repeat', name: N_('Subscriptions & tools'), group: 'money', on: ofm_ofc, adm: 1},
  {key: 'meals', go: 'office/meals', need: 'money.meals', icon: 'meal', name: N_('Entertainment receipts'), group: 'money', on: ofm_ofc, adm: 1},
  {key: 'cashbook', go: 'office/cashbook', icon: 'wallet', name: N_('Cash book'), group: 'money', on: ofm_ofc, adm: 1},
  {key: 'agreements', go: 'office/agreements', icon: 'shield', name: N_('Contracts & subscriptions'), group: 'admin', on: ofm_ofc, adm: 1},
  // 2.187.1 B (#2735): the own times to bill -- only a person ruled by office groups (the others bill from the quotations)
  {key: 'time', go: 'office/time', icon: 'clock', name: N_('Times to bill'), group: 'sell', on: () => ofm_ofc() && !!ofm_lv()}];
// admin of the office shown: from the office's settings once loaded, before that the last answer for this workspace (LS),
// so the contacts / clients pages need not load the office. The server checks every admin route on its own.
const ofm_ws = () => `${S.me?.id || ''}:${typeof wsCur === 'function' ? wsCur() : 'all'}`;  // per person and workspace
const OFM_ASKED = new Set();  // workspaces whose role was read in this session
function ofm_adm() {
  if (typeof OFC !== 'undefined' && OFC.info) return OFC.info.role === 'admin';
  const ws = ofm_ws();
  // the contacts / clients pages without the office loaded: its role once per workspace and session, quietly (a 4xx
  // leaves the menu as it is); the office itself reads it with its settings (ofcInfo)
  if ((typeof OFC === 'undefined' || !OFC.info) && officeOn() && !OFM_ASKED.has(ws)) {  // 2.152.2 (#2632): also while the office script is there without its settings yet
    OFM_ASKED.add(ws);
    rawFetch('GET', '/api/office/settings').then(j => {
      if (!j || ofm_ws() !== ws) return;
      const seen = () => ofm_adm() + JSON.stringify([ofm_lv(), ofm_used(), ofm_offList()]), was = seen(); ofm_admSeen(j.role === 'admin', j.rights, j.used, j.settings?.menu_off);
      if (was !== seen() && mg_areaOf(S.route.mod)?.[0] === 'office') renderView();
    }, () => {});
  }
  return !!(LS.get('ofmAdm', {}) || {})[ws];
}
function ofm_admSeen(adm, rights, used, menuOff = []) {
  const f = LS.get('ofmOff', {}) || {}; if (JSON.stringify(f[ofm_ws()] || []) !== JSON.stringify(menuOff)) { f[ofm_ws()] = menuOff; LS.set('ofmOff', f); }  // 2.440.0 (#3609)
  const o = LS.get('ofmAdm', {}) || {}; if (!!o[ofm_ws()] !== adm) { o[ofm_ws()] = adm; LS.set('ofmAdm', o); }
  const u = LS.get('ofmUsed', {}) || {}; if (used && JSON.stringify(u[ofm_ws()] || null) !== JSON.stringify(used)) { u[ofm_ws()] = used; LS.set('ofmUsed', u); }  // 2.276.0 A (#3039)
  // 2.187.0 A (#2476): + the levels of a person ruled by office groups (null = as before), so #clients / #contacts show the right menu
  const lv = rights && rights.levels && !rights.legacy && rights.manager !== 'admin' ? rights.levels : null, l = LS.get('ofmLv', {}) || {};
  if (JSON.stringify(l[ofm_ws()] || null) !== JSON.stringify(lv)) { if (lv) l[ofm_ws()] = lv; else delete l[ofm_ws()]; LS.set('ofmLv', l); }
  const ow = LS.get('ofmOwn', {}) || {}, on = ofm_legOwnOf(rights);  // 2.545.0 (#4592): the own areas of a member in "Previous access"
  if (JSON.stringify(ow[ofm_ws()] || []) !== JSON.stringify(on)) { if (on.length) ow[ofm_ws()] = on; else delete ow[ofm_ws()]; LS.set('ofmOwn', ow); }
}
// 2.545.0 (#4592): a member in "Previous access" has the level "own" in some areas (server: office/rights.py LEGACY_OWN,
// the travel expenses): their menu point shows, everything else stays as before
const ofm_legOwnOf = r => r && r.legacy && r.levels ? Object.keys(r.levels).filter(k => r.levels[k] === 'own') : [];
const ofm_legOwn = k => (typeof OFC !== 'undefined' && OFC.info ? ofm_legOwnOf(OFC.info.rights) : (LS.get('ofmOwn', {}) || {})[ofm_ws()] || []).includes(k);
// 2.187.0 A (#2476): {area: level} of a person ruled by office groups in the workspace shown (null = not ruled by groups)
function ofm_lv() {
  if (typeof OFC !== 'undefined' && OFC.info) { const r = OFC.info.rights; return r && r.levels && !r.legacy && r.manager !== 'admin' ? r.levels : null; }
  return (LS.get('ofmLv', {}) || {})[ofm_ws()] || null;
}
// a menu point: an office area = its level is not "none" (Settings stays: "My rights" lives there); else as before (adm)
// 2.436.0 (#3620): "View as member" in an organisation's office: no settings / contracts / bank; daily work stays
const MV_OFM = ['settings', 'agreements', 'bank'];
const mvOfc = () => mvOn() && (typeof OFC !== 'undefined' && OFC.info ? !OFC.info.personal : String(wsCur()).startsWith('org:'));
const ofm_ok = i => { if (MV_OFM.includes(i.key) && mvOfc()) return false; const lv = ofm_lv(), k = i.lvk || i.key; return lv && k in lv ? i.key === 'settings' || lv[k] !== 'none' : !i.adm || ofm_adm() || ofm_legOwn(k); };  // 2.276.0 A (#3039): lvk; 2.545.0 (#4592): + ofm_legOwn
// 2.276.0 A (#3039): what the office already holds (GET /api/office/settings used: invoice, receipt, inquiry, meal, travel,
// sub, fixed), per person and workspace like the role (LS ofmUsed); null = not known yet (everything as before)
function ofm_used() { return typeof OFC !== 'undefined' && OFC.info ? OFC.info.used || null : (LS.get('ofmUsed', {}) || {})[ofm_ws()] || null; }
// 2.380 F (#3411): every point of Money shows at once; 2.448.0 (#3784): also before its first use, a point nobody needs is
// switched off under Settings > Functions (need: money.*, office_packs.js OCF_FEATS) or hidden in the menu's editor
// ---- 2.418.0 (#3560): each person arranges the menus of the areas (navmenu.js draws the editor): the order, the points
// hidden (only not in the menu: data, function and rights stay, the search finds them) and the points that start hidden but
// were brought back. User setting nav_menus, json {area: {order, hidden, shown}} (accounts/navmenus.py), the same on phone
// and computer. An organisation's admins switch points off for all members (orgs.nav_off "<area>:<key>"): those are not in
// the menu, not even under Hidden. The point open now always shows.
const NAV = {s: null, o: {}, edit: null};  // edit = the area whose menu is being arranged in place (panel / office start page)
function nav_pref(area) {
  const s = S.settings?.nav_menus || '{}';
  if (s !== NAV.s) { NAV.s = s; try { const o = JSON.parse(s); NAV.o = o && typeof o === 'object' && !Array.isArray(o) ? o : {}; } catch { NAV.o = {}; } }
  const m = NAV.o[area] || {};
  return {order: Array.isArray(m.order) ? m.order : [], hidden: new Set(m.hidden || []), shown: new Set(m.shown || [])};
}
const nav_orgOff = (area, key) => { const w = typeof wsCur === 'function' ? wsCur() : ''; return w.startsWith('org:') && (wsOrg(w.slice(4))?.nav_off || []).includes(area + ':' + key); };
// hidden by the person: by hand; the parts hidden in the old sidebar settings
// (sidebar "e:<part>", before 2.418.0) count as hidden too until shown again
const nav_hid = (area, key) => { const p = nav_pref(area); return p.hidden.has(key) || !p.shown.has(key) && area !== 'office' && sideHidden('e:' + key); };
const nav_open = (area, key) => area === 'office' ? S.route?.mod === 'office' && S.route.tab === key || S.route?.mod === key && key !== 'office' : S.route?.mod === key;
// the menus that can be arranged (the editor: navmenu.js, loaded on the first use)
const NAV_AREAS = ['office', 'life', 'reading', 'time', 'review', 'ablage'];
const nav_canEdit = id => NAV_AREAS.includes(id) && !S.me?.kid && !!S.settings;
// a computer: "Customize" as the last row of the area's panel; a phone: a pen on top of the area's menu
const nav_editBtn = (id, cls = 'srow smod sbbi navedb') => nav_canEdit(id) && !isMobile() && NAV.edit !== id ? `<button type="button" class="${cls}" data-act="nav-edit" data-area="${id}">${ic('edit')}<span class="n">${esc(tr('Customise'))}</span></button>` : '';
const nav_penHtml = id => nav_canEdit(id) && isMobile() && NAV.edit !== id ? `<div class="navpen"><button type="button" class="iconbtn" data-act="nav-edit" data-area="${id}" title="${esc(tr('Edit menu'))}" aria-label="${esc(tr('Edit menu'))}">${ic('edit', 's')}</button></div>` : '';
// the editor in place of the menu (its script first loads, then the panel / page draws again)
const nav_editSlot = id => typeof nav_edHtml === 'function' ? nav_edHtml(id) : (loadModule('navmenu').then(() => { renderSide(); if (id === 'office' && S.route.mod === 'office') renderView(); }, () => {}), `<p class="muted navedl0">${esc(tr('Loading…'))}</p>`);
function nav_edit(id, on = true) {
  NAV.edit = on ? id : null;
  const go = () => { renderSide(); if (S.route.mod === 'office' && id === 'office') renderView(); setTimeout(() => $(on ? '.naved [data-act="nav-done"]' : `[data-act="nav-edit"][data-area="${id}"]`)?.focus({preventScroll: true}), 0); };
  if (on && typeof nav_edHtml !== 'function') loadModule('navmenu').then(go, () => {}); else go();
}
// 2.484.0 (#3949): the Projects page (render.js viewProjStart): a long press (phone) or a right click (computer) on a project row opens
// the sidebar's project menu, on a folder row the sidebar's folder menu; the click ending the press opens nothing (ms_rowMenu, #3836)
const PS_MENU = '.pstart .psrow[data-pl], .pstart .psfold[data-pf]';
const ps_menu = r => r.dataset.pl ? listMenu(r, +r.dataset.pl) : folderMenu(r, r.dataset.pf);
ms_rowMenu(PS_MENU, ps_menu);
document.addEventListener('contextmenu', e => {
  if (S.listReorder || e.shiftKey || e.pointerType === 'touch' || isTouch()) return;  // touch: the long press above
  const r = e.target.closest?.(PS_MENU); if (!r) return;
  e.preventDefault(); ps_menu(r);
});
// a computer: right-click on a point of a panel = "Hide from menu" / "Customize" (navmenu.js nav_rowMenu)
// 2.655.0 (#5083): touch: the same menu by the shared long press (ms_rowMenu, like #4616), also on a tablet
ms_rowMenu('#side [data-navk]', b => { if (!nav_canEdit(b.dataset.navk.split(':')[0])) return; loadModule('navmenu').then(() => nav_rowMenu(b), () => {}); });
document.addEventListener('contextmenu', e => {
  const b = e.target.closest?.('#side [data-navk]'); if (!b || isMobile() || isTouch() || !nav_canEdit(b.dataset.navk.split(':')[0])) return;
  e.preventDefault(); e.stopPropagation();
  loadModule('navmenu').then(() => nav_rowMenu(b), () => {});
}, true);
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-act="nav-edit"]'); if (!b) return;
  e.preventDefault(); e.stopPropagation(); nav_edit(b.dataset.area);
}, true);
// the choices of the "More" of the office (LS ofmAll / ofmSeen, one device, before 2.418.0): 2.448.0 (#3784) nothing starts hidden any more
function nav_legacy() { LS.del('ofmAll'); LS.del('ofmSeen'); }
// the person's order: named keys first in that order, the others after them in their usual order (rank)
const nav_sort = (area, xs, key = x => x.key, rank = () => 0) => { const o = nav_pref(area).order, r = x => { const n = o.indexOf(key(x)); return n < 0 ? o.length + rank(x) : n; }; return xs.map((x, i) => [x, i]).sort((a, b) => r(a[0]) - r(b[0]) || a[1] - b[1]).map(a => a[0]); };
// a tab of the office (OFC_TABS: [key, icon, name, admins only, html, group]) without an entry here joins its group
// ([5], else Administration) once the office is loaded, so a new office part is never out of reach
const ofm_all = () => typeof OFC_TABS === 'undefined' ? OFM_ITEMS : [...OFM_ITEMS, ...OFC_TABS.filter(t => !OFM_ITEMS.some(i => i.key === t[0]))
  .map(t => ({key: t[0], go: 'office/' + t[0], icon: t[1], name: t[2], group: OFM_GROUPS.some(g => g[0] === t[5]) ? t[5] : 'admin', on: ofm_ofc, adm: t[3], need: t[6]}))];  // 2.147.0: [6] = need
// 2.98.0 C (#2180): the order inside the groups (a part not named here keeps its place at the end of its group);
// tpl = a tab under Settings, not in the menu
const OFR_ORDER = ['pipeline', 'offers', 'invoices', 'gendocs', 'clients', 'contacts', 'contracts', 'receipts', 'cashflow', 'kpi', 'bank', 'cards', 'books', 'subs', 'travel', 'meals', 'equipment', 'agreements', 'settings'];
const ofr_rank = i => { const n = OFR_ORDER.indexOf(i.key); return n < 0 ? OFR_ORDER.length : n; };
// 2.147.0 (#2459): need = a function of the country pack ('books.…'); off in this office = no menu point (office.js ofcFeat)
const ofm_need = i => !i.need || typeof ofcFeat !== 'function' || ofcFeat(i.need);
// 2.440.0 (#3609): points the office switched off for everybody (office setting menu_off, Settings > Functions > Menu points):
// not in the menu, the tiles or the search, a link opens the start page (office.js ofcTab); per workspace like the role (LS ofmOff)
const ofm_offList = () => (typeof OFC !== 'undefined' && OFC.info ? OFC.info.settings?.menu_off : (LS.get('ofmOff', {}) || {})[ofm_ws()]) || [];
const ofm_menuOff = k => ofm_offList().includes(k);
// 2.418.0 (#3560): every point that may show (switched on, the country pack, the rights, not off in the organisation), in
// the person's order; ofm_items = those in the menu, ofm_hidden = those under "Hidden" of the editor
// 2.489.0 (#2648): the subscriptions live in "Contracts & subscriptions" (one point, the kind as a filter, office_agreements.js
// agr_filterHtml): the point subs leaves the menu while the contracts' point may show; its page #office/subs stays (the filter)
const ofm_merged = its => its.some(i => i.key === 'agreements') ? its.filter(i => i.key !== 'subs') : its;
const ofm_avail = () => (nav_legacy(), nav_sort('office', ofm_merged(ofm_all().filter(i => !i.tpl && i.on() && ofm_need(i) && ofm_ok(i) && !nav_orgOff('office', i.key) && !ofm_menuOff(i.key))).sort((a, b) => ofr_rank(a) - ofr_rank(b))));
const ofm_items = () => ofm_avail().filter(i => !nav_hid('office', i.key) || nav_open('office', i.key));
const ofm_hidden = () => ofm_avail().filter(i => nav_hid('office', i.key) && !nav_open('office', i.key));
// the point shown: the office's tab (import sits under Settings; no tab = the start page on a phone, quotations on a computer)
function ofm_cur(mod) {
  if (mod !== 'office') return mod;
  const t = ['import', 'services', 'texts', 'rights'].includes(S.route.tab) ? 'settings' : S.route.tab === 'subs' && ofm_avail().some(i => i.key === 'agreements') ? 'agreements' : S.route.tab;  // 2.489.0 (#2648)  // 2.98.0 C (#2180): + the templates; 2.187.0 A (#2476): + the rights
  if (mod === S.route.mod && t && t !== 'start') ofm_remember(t);
  return t === 'start' || ofm_all().some(i => i.key === t && i.go.startsWith('office/')) ? t : isMobile() ? 'start' : (ofm_entry().key);
}
// 2.161.2 (#2616): the office opens on the point used last on this device (LS ofmLast); nothing kept, or gone / not allowed: the
// Pipeline for admins (a person without an organisation is the admin of the own office), else Quotes & invoices
// 2.276.0 A (#3039): nothing kept = Quotes & invoices for everybody; the Pipeline only once the office has an inquiry / lead
function ofm_remember(key) {
  const o = LS.get('ofmLast', null); if (o !== key) LS.set('ofmLast', key);
}
// 2.470.0 (#3596): Settings is a dialog, no page to open the office on
function ofm_entry() {
  const its = ofm_items(), last = LS.get('ofmLast', null);
  return its.find(i => i.key === last && i.key !== 'settings') || its.find(i => i.key === (ofm_adm() && ofm_used()?.inquiry ? 'pipeline' : 'offers')) || its.find(i => i.key === 'offers') || its[0] || {key: 'offers', go: 'office/offers'};
}
const ofm_btn = (i, cur, cls) => `<button type="button" class="${cls} ${i.key === cur ? 'on' : ''}" data-go="${i.go}" data-ofm="${i.key}"${i.key === cur ? ' aria-current="page"' : ''}>${ic(i.icon, 's')}<span>${esc(tr(i.name))}</span></button>`;
// the path of a detail page ("Clients › Example Ltd"), grey text, not a navigation
function ofm_detail(mod) {
  let p = null;
  if (mod === 'clients' && S.route.client && S.route.client !== 'mailhub' && typeof CLV !== 'undefined' && CLV.id === S.route.client && CLV.data?.name) p = [tr('Clients'), CLV.data.name];
  else if (mod === 'contacts' && typeof CT !== 'undefined' && CT.sel && CT.card) p = [tr('Address book'), CT.card.fn || CT.card.org || '?'];
  else if (mod === 'office' && S.route.id && typeof ofd_openDoc === 'function' && ofd_openDoc()?.id === S.route.id) p = [tr(ofd_openDoc().kind === 'offer' ? 'Quotations' : 'Invoices'), `${ofdKindName(ofd_openDoc().kind, true)} ${ofd_openDoc().number || tr('Draft')}`];  // 2.356.0 C (#3004): the open document, never the one before
  else if (mod === 'office' && S.route.tab === 'travel' && typeof RK !== 'undefined' && RK.open && typeof rk_trip === 'function' && rk_trip(RK.open)) p = [tr('Travel expenses'), rk_trip(RK.open).dest || tr('Trip')];
  return p ? `<nav class="ofmcrumb" aria-label="${esc(tr('Path'))}">${p.map(x => `<span>${esc(x)}</span>`).join('<span aria-hidden="true">›</span>')}</nav>` : '';
}
function ofm_menuHtml(mod) {
  const cur = ofm_cur(mod), its = ofm_items(), crumb = ofm_detail(mod);
  if (its.length < 2 || cur === 'start') return crumb;  // the start page's list is the menu
  const grp = g => its.filter(i => i.group === g[0]);
  // 2.98.0 C (#2180): a phone's sub page = "< Office · group" (back to the start list) and the group's points as one row
  // of underlined tabs that never wraps (it scrolls sideways; ofr_after shows the active one)
  const g = OFM_GROUPS.find(x => x[0] === ofm_all().find(i => i.key === cur)?.group); if (!g) return crumb;
  const lbl = `${esc(tr('Office|area'))} · ${esc(tr(g[2]))}`;
  const home = officeOn() ? `<button type="button" class="ofpback" data-go="office/start">${ic('chev', 's')}<span>${lbl}</span></button>` : `<span class="ofpback">${lbl}</span>`;
  return `<nav class="ofpb" aria-label="${esc(tr('Office|area'))}" data-mgtabs="office">${home}${grp(g).length > 1 ? `<div class="ofpts">${grp(g).map(i => ofm_btn(i, cur, 'ofpt2')).join('')}</div>` : ''}</nav>${crumb}`;
}
// ---- 2.98.0 C (#2180): the office on a computer: the page starts with its own heading (.ofpt), a detail page with its path
// instead. 2.152.2 (#2617): the second column (the office rail) is gone, its groups and points are the office's panel of
// sidebar B (sbb_officeHtml); the content takes the width.
function ofr_wrap(mod, html) {
  mg_seen(mod); sbb_officeSync();
  const cur = ofm_cur(mod), crumb = ofm_detail(mod), it = ofm_items().find(i => i.key === cur);
  const head = crumb || (it && !sbb_on() ? `<h2 class="ofpt">${esc(tr(it.name))}</h2>` : '');
  return `<div class="ofwrap"><div class="ofbody">${head}${html}</div></div>`;
}
// left / right (Home / End) inside a phone's tab row; Tab keeps the reading order
function ofr_key(e) {
  const b = e.target.closest?.('.ofpb .ofpt2'), ks = ['ArrowLeft', 'ArrowRight', 'Home', 'End']; if (!b) return false;
  if (!ks.includes(e.key) || e.altKey || e.ctrlKey || e.metaKey) return false;
  const all = $$('.ofpt2', b.closest('nav')), i = all.indexOf(b); if (i < 0) return false;
  const j = e.key === 'Home' ? 0 : e.key === 'End' ? all.length - 1 : Math.max(0, Math.min(all.length - 1, i + (e.key === ks[1] ? 1 : -1)));
  all[j].focus(); e.preventDefault(); return true;
}
document.addEventListener('keydown', e => { if (ofr_key(e)) e.stopPropagation(); }, true);
// after a draw: the active tab of a phone's row in sight (the row scrolls sideways)
function ofr_after(root) {
  const b = $('.ofpb .ofpt2.on', root || document); if (!b) return;
  const row = b.parentElement, r = row.getBoundingClientRect(), x = b.getBoundingClientRect();  // sideways only, the page stays
  if (x.left < r.left || x.right > r.right) row.scrollLeft += x.left - r.left - Math.max(0, (r.width - x.width) / 2);
}
// the office start page (office/start, a phone's way in): the figures (admins), then per group a small caps heading and a
// card with one row per point (2.98.0 C, #2180: one column, was a tile per group)
function ofm_startHtml() {
  const its = ofm_items();
  const fig = (ofm_lv() ? ofm_lv().kpi && ofm_lv().kpi !== 'none' : ofm_adm()) && typeof kp_tile === 'function' ? kp_tile(c => `<section class="ofmfig">${c}</section>`) : '';
  const row = i => `<button type="button" class="oflr" data-go="${i.go}" data-ofm="${i.key}">${ic(i.icon)}<span>${esc(tr(i.name))}</span>${ic('chev', 's')}</button>`;
  // 2.276.0 A (#3039): Money folds like in the panel (same state, sbb_folded); 2.418.0 (#3560): no "More" any more, the
  // menu's editor (pen on top, navmenu.js) hides and brings back points
  if (NAV.edit === 'office') return `<div class="ofmstart">${nav_editSlot('office')}</div>`;
  const head = g => g[3] ? '' : g[0] !== 'money' ? `<h3>${esc(tr(g[2]))}</h3>` : `<h3><button type="button" class="oflgt" data-act="ofm-group" aria-expanded="${!sbb_folded('office:money')}">${ic('chev', 's fcar')}<span>${esc(tr(g[2]))}</span></button></h3>`;
  const fold = g => g[0] === 'money' && sbb_folded('office:money');
  const norc = typeof bnr_startHtml === 'function' && ofm_adm() && !ofm_menuOff('bank') ? bnr_startHtml() : '';  // 2.299.0 C (#3192): "12 bookings without a receipt"
  return `<div class="ofmstart">${nav_penHtml('office')}${fig}${norc}<div class="ofl">${OFM_GROUPS.map(g => { const gi = its.filter(i => i.group === g[0]); return gi.length ? `<section class="oflg${fold(g) ? ' closed' : ''}" data-ofmg="${g[0]}">${head(g)}${fold(g) ? '' : `<div class="oflc">${gi.map(row).join('')}</div>`}</section>` : ''; }).join('')}</div></div>`;
}
// ---- the sidebar row of an area. Hidden (Settings > Appearance > Sidebar) while every part is ("e:<route>" of each part,
// so an arrangement from before 2.44.0 that hid both still hides the area, and 2.43.1 reads what this one writes)
const mg_sideKeys = id => mg_area(id)[3].map(p => p[0]);
const mg_sideHidden = (id, hid) => mg_sideKeys(id).every(k => hid('e:' + k));
function mg_sideRow(id, hid) {
  const a = mg_area(id), here = mg_areaOf(S.route.mod) === a;
  if (!mg_on(id) || (mg_sideHidden(id, hid) && !here) || o3a_hid(id)) return '';  // 2.83.0 (#1845)
  const rec = id === 'time' && (S.timer || S.pomo), req = id === 'life' && famOn() ? (S.kids || []).reduce((n, k) => n + (k.requests || 0), 0) : 0;
  const after = rec ? '<span class="c"><span class="recdot"></span></span>' : req ? `<span class="c nunread">${req}</span>` : '';
  return `<button class="srow smod ${here ? 'on' : ''}" data-go="${mg_target(id)}" data-mgside="${id}">${ic(mg_icon(a))}<span class="n">${esc(tr(mg_nameKey(a)))}</span>${after}</button>`;
}
// [keys, name] for the sidebar editor (one check box per area, for all its parts)
const mg_sideEntry = id => mg_on(id) ? [mg_sideKeys(id).join(','), mg_area(id)[2]] : null;
// ---- the tab bar (phone): one tab per area ("a:<id>"); a tab pinned before 2.44.0 for a part becomes its area's tab
const MG_TAB_OLD = {'m:pomo': 'a:time', time: 'a:time', stats: 'a:review', 'm:family': 'a:life', office: 'a:office'};
const mg_tabIds = ids => ids ? [...new Set(ids.map(x => MG_TAB_OLD[x] || x))] : ids;
function mg_tabItem(id) {
  const a = mg_area(id.slice(2)); if (!a || !mg_on(a[0])) return null;
  return {id, go: sbb_target(a[0]) /* 2.417.0 A (#3559): the page kept in the area, like the bar */, icon: ic(mg_icon(a), 'l'), ico: mg_icon(a), label: tr(mg_nameKey(a)), mod: a[0], area: a[0]};
}
const mg_tabOpts = opt => MG_IDS.filter(mg_on).map(id => opt('a:' + id, tr(mg_area(id)[2]))).join('');
// ---- Settings > Modules: ONE switch per area; its parts below it (each can still be switched on its own)
const MG_DESC = {office: N_('Quotations, invoices and bookkeeping'),  // 2.298.0 A1 (#3186): the parts are listed right below
  time: N_('Time tracking on tasks with reports, and the focus timer; finished focus sessions can count as time entries'),
  review: N_('Your day and week in review with a private journal, and the statistics'),
  life: N_('Home & life (contracts, devices, staying in touch, health, trips) and family; trips and staying in touch also in each organisation'),  // 2.173.0 A (#2680)
  reading: N_('Read later, feeds and bookmarks: your own in Private, shared ones in each organisation; never visible to agents'),  // 2.172.0 B (#2679)
  ablage: N_('Folders and files of your own and of your organisation, shared with people and agents, with versions')};  // 2.48.0 (#1207)
function mg_modAreaHtml(id, partRow) {
  const a = mg_area(id), on = mg_on(id), all = mg_allOn(id), ks = a[3].flatMap(p => p[4]());
  return `<div class="modrow mgarea ${on ? '' : 'off'} ${on && !all ? 'part' : ''}" data-mgrow="${id}"><label class="mmain"><span class="swc"><input type="checkbox" data-mgarea="${id}" ${all ? 'checked' : ''}><span class="swt" aria-hidden="true"></span></span><span><b>${tr(a[2])}</b><small class="muted">${tr(MG_DESC[id])}</small>${modPrivHtml(ks)}</span></label>
    <details class="mopt mgparts"><summary>${trh('Parts: {0}', a[3].map(p => tr(p[2])).join(', '))}</summary><div class="modlist">${ks.map(partRow).join('')}</div></details></div>`;
}
function mg_setSync(md) { wsa_raw(() => mg_setSyncMain(md)); }  // 2.409.0 (#3490): the main switches
function mg_setSyncMain(md) {
  for (const el of $$('[data-mgarea]', md)) if (el.matches('input')) { const id = el.dataset.mgarea; el.checked = mg_allOn(id); el.indeterminate = !el.checked && mg_on(id); }  // 2.171.0 (#2676)
  $$('[data-mgrow]', md).forEach(r => { const id = r.dataset.mgrow; r.classList.toggle('off', !mg_on(id)); r.classList.toggle('part', mg_on(id) && !mg_allOn(id)); });
}
// the area's switch: all its parts on or off, ONE undo step
async function mg_areaSwitch(md, el) {
  const id = el.dataset.mgarea, on = el.checked, n = tr(mg_area(id)[2]);
  const fs = new Set((S.settings.features ?? FEATS.map(x => x[0]).join(',')).split(',').filter(Boolean));
  for (const k of mg_feats(id)) on ? fs.add(k) : fs.delete(k);
  await setApply({features: FEATS.map(x => x[0]).filter(x => fs.has(x)).join(',')}, on ? tr('{0} on', n) : tr('{0} off', n));
  wsa_raw(() => { for (const x of $$('[data-feat]', md)) { x.checked = feat(x.dataset.feat); x.closest('[data-modrow]')?.classList.toggle('off', !x.checked); } });  // 2.409.0 (#3490)
  mg_setSync(md); modCountsSync(md);
  if (id === 'time' && on && !$('#s-trnd', md)) { const cur = LS.get('settingsSec'); md._noflush = true; md.remove(); settingsModal(cur); }  // the time options
}
// ---- 2.83.0 (#1845): an organisation's view shows only what belongs to the organisation. Home (home & life, family,
// budget) and habits are private -- hidden in the sidebar, the phone's tab bar and the search while an organisation is the
// shown workspace (Time stays); an old link opens them in Private. 2.398.0 (#3405 #3406): notes, review and statistics are in
// every workspace, each showing only that workspace's data (notes: its projects + my private list Notes; review, statistics:
// its projects, the journal only outside an organisation)
// 2.173.0 A (#2680): Home is in an organisation's view too while travel or staying in touch is on -- as "Travel & contacts"
// with only these two (contracts, devices, health, budget and family stay private); its view shows the organisation's own
const O3A_PRIV = ['family', 'budget', 'habits'];  // 2.85.0 B (#1162): + feeds; 2.172.0 B (#2677): feeds out (Reading is in every workspace)
const O3A_LIFE_ORG = ['travel', 'care'];
const o3a_lifeOrg = () => O3A_LIFE_ORG.some(m => feat(m));
const o3a_privOnly = mod => O3A_PRIV.includes(mod) || (mod === 'life' && !o3a_lifeOrg());
// 2.172.0 B (#2677 #2679): the space a view of Reading shows -- the shown workspace, never a mixed view.
// 2.540.0 (#4588): under "All workspaces" (more than one space) the top of each view of Reading (Read later, Bookmarks,
// Feeds, Home & life) is the overview of the spaces (spo_html, like Knowledge); the open one is in the address
// (#<view>/s/<space>, rd_home). The picker of #2677 (Private by default) is gone; where a new link is saved (#4025) stays.
const rd_spaces = () => wsOptions().filter(w => w !== 'all');
const rd_all = () => typeof wsCur === 'function' && wsCur() === 'all' && wsOn() && rd_spaces().length > 1;
const rd_open = () => rd_all() && rd_spaces().includes(S.route.wsp) ? S.route.wsp : null;  // null under "All" = the overview
const rd_space = () => { const w = typeof wsCur === 'function' ? wsCur() : 'all'; return w !== 'all' ? w : rd_open() || 'private'; };
const rd_ovr = () => rd_all() && !rd_open();
const rd_home = (mod, sp = rd_open()) => rd_all() && sp ? mod + '/s/' + sp : mod;
// the overview of a view of Reading and, inside a space under "All", the path back to it
const rd_ovrHtml = mod => spo_html(mod, rd_spaces().map(w => [w, wsName(w), wsIcon(w)]));
const rd_crumb = mod => rd_open() ? spo_crumbHtml(mod, wsName(rd_open())) : '';
// 2.769.0 (#5352): the overview "All workspaces" of Knowledge, Files and Reading is "Recently edited" (recent.js zle_ovrHtml, loaded
// on demand: the workspaces only where no sidebar lists them, as chips); until it is here a placeholder of the same height
const spo_recentHtml = (mod, to, rows, o) => typeof zle_ovrHtml === 'function' ? zle_ovrHtml(mod, to, rows, o) : (ld_later('recent'), '<div class="zleov"><div class="zleph" style="--zlen:8" aria-busy="true"></div></div>');
const rd_recentHtml = mod => spo_recentHtml(mod, mod, rd_spaces().map(w => [w, wsName(w), wsIcon(w)]));
// ---- 2.540.0 (#4575 #4588): the overview of the spaces under "All workspaces", shared by the file store (ablage.js),
// the views of Reading and later other areas (as Knowledge does it, wiki.js wk_spacesHtml): one row per space, a tap opens
// it, the address carries it, the path above an open space leads back (spo_crumbHtml). to = where a tap leads: a route
// ('ablage' -> #ablage/s/<space>) or a function space -> hash without '#'; rows = [[space, name, icon html]] (any spaces:
// Private, organisations, Shared with me, the trash ...); o.title = the heading (default "All workspaces"), o.label = the
// list's name for screen readers (default "Workspaces")
const spo_href = (to, sp) => '#' + (typeof to === 'function' ? to(sp) : to + '/s/' + sp);
const spo_html = (to, rows, o = {}) => `<section class="spov" aria-label="${esc(o.label || tr('Workspaces'))}"><h3 class="spovt">${esc(o.title || tr('All workspaces'))}</h3><ul class="spovl">${rows.map(([sp, name, icon]) => `<li><a href="${esc(spo_href(to, sp))}" class="spovr" data-spov="${esc(sp)}">${icon}<span>${esc(name)}</span></a></li>`).join('')}</ul></section>`;
// the path back above an open space: "All workspaces /" (spo_upHtml, the file store puts its own path after it) + its name
// 2.769.0 (#5339): a button like the other path links (an anchor is inline: no min-height, other baseline)
const spo_upHtml = route => `<button type="button" class="linkbtn" data-go="${esc(route)}" data-spovup="1">${esc(tr('All workspaces'))}</button><span class="abcsep" aria-hidden="true">/</span>`;
const spo_crumbHtml = (route, name) => `<nav class="abcrumbs spovc" aria-label="${esc(tr('Path'))}">${spo_upHtml(route)}<span class="abccur" aria-current="page">${esc(name)}</span></nav>`;
// 2.490.0 C (#4025): where a link is saved to (Read later / a bookmark) is picked, not the shown workspace: Private, then
// every organisation the person may add to (member or admin, Reading on there for the person). "(Team)" says that all its
// members see it. Used by the share question (agentchat.js shareDest) and the bookmark button (bookmarks.js
// bm_confirmSave); the server checks the space again (life/rss.py rss_space, life/bookmarks.py bm_space).
const rd_targets = () => ['private', ...(wsOn() ? (S.me?.workspaces || []).filter(w => (w.role === 'admin' || w.role === 'member') && wsa_wsOn('org:' + w.id, 'reading')).map(w => 'org:' + w.id) : [])];
const rd_tgtName = sp => sp === 'private' ? tr('Private|workspace') : tr('{0} (Team)', wsName(sp));
// kind 'later' | 'bookmark': the label "Read later · Private" / "Bookmark · Alpha (Team)"
const rd_tgtLabel = (kind, sp) => `${kind === 'later' ? tr('Read later') : tr('Bookmark')} · ${rd_tgtName(sp)}`;
// a select of the targets for a form ('' with Private only); Private is preselected
const rd_tgtSel = (kind, id) => { const ts = rd_targets(); return ts.length < 2 ? '' : `<div class="row"><label for="${id}">${tr('Save in')}</label><select id="${id}">${ts.map(sp => `<option value="${sp}">${esc(rd_tgtLabel(kind, sp))}</option>`).join('')}</select></div>`; };
// the answer of the share question 'later' | 'later:org:5' | 'bookmark' | 'bookmark:org:5' -> [kind, space] (others stay as they are)
const rd_destSplit = v => typeof v === 'string' && /^(bookmark|later):/.test(v) ? [v.slice(0, v.indexOf(':')), v.slice(v.indexOf(':') + 1)] : [v, 'private'];
const o3a_orgView = () => typeof wsCur === 'function' && wsCur().startsWith('org:');
// 2.173.0 A (#2680): the parts of an area shown in the current view (an organisation's: without the private ones) and the
// name of Home there (only travel and staying in touch: not "Home")
// 2.353.0 D (#2759): parts without an own entry in the navigation (tabs, panel, menus): Documents is a saved filter of the
// file store now (abdocs.js); its switch and its old links stay (2.752.0, #4887: #docs leads to #ablage/docs, core.js)
const MG_NONAV = new Set(['docs']);
const mg_partsShown = a => mg_parts(a).filter(p => !o3a_hid(p[0]) && !MG_NONAV.has(p[0]) && !nav_orgOff(a[0], p[0]));  // 2.418.0 (#3560): + off in the organisation
// 2.418.0 (#3560): the parts in the area's menu (panel, tabs): the person's order, without the hidden ones (the open one stays)
const mg_partsMenu = a => nav_sort(a[0], mg_partsShown(a), p => p[0]).filter(p => !nav_hid(a[0], p[0]) || nav_open(a[0], p[0]));
const O3A_LIFE_NAME = N_('Travel & contacts|area');
// 2.364.0 B (#3018): with Office & finance off the area is called and drawn like its first part on (Contacts, else Clients)
const mg_ofOff = a => a?.[0] === 'office' && !officeOn() && mg_parts(a).length > 0;
const mg_nameKey = a => a && a[0] === 'life' && o3a_orgView() ? O3A_LIFE_NAME : mg_ofOff(a) ? mg_parts(a)[0][2] : a?.[2];
const mg_icon = a => mg_ofOff(a) ? mg_parts(a)[0][1] : a?.[1];
const mg_partName = (m, n) => m === 'life' && o3a_orgView() ? O3A_LIFE_NAME : n;
const o3a_hid = mod => !!mod && o3a_privOnly(mod) && o3a_orgView();
// a tab bar / "More" item ({mod}) or a sidebar row (its data-go route) hidden in an organisation's view
const o3a_hidT = t => !!t && o3a_hid(t.mod);
const o3a_hidRow = h => { const m = /data-go="(\w+)/.exec(h); return !!m && o3a_hid(m[1]); };
// the router: a private module opened in an organisation's view switches quietly to Private (like wsFollow), then opens it
function o3a_toPrivate(mod) {
  if (!o3a_hid(mod)) return;
  const from = wsCur();
  S.settings.workspace = 'private'; LS.set('ws', 'private');
  api('PATCH', '/api/settings', {workspace: 'private'}).catch(() => {});
  ws_autoNote(from);  // 2.484.0 (#3950): a short note with "Back"
}
// ---- 2.152.2 (#2622): sidebar B on a computer. Left a narrow bar of the areas (icon, small word below), next to it ONE
// panel with the chosen area's content (#side), the page on the right. A click on an icon changes panel and page together:
// the area opens the page used last there on this device (LS sbbLast, the first time its usual way in), like Slack / Teams.
// The panel always follows the page (the page's area), so both always match. Phones keep the drawer and the tab bar.
// [id, icon, name, on(), routes]; an area of MG_AREAS takes its icon, name and parts from there. Tasks is every other route.
// 2.208.0 (#2771): the area 'tasks' is called Projects (its entries stay tasks), icon proj instead of the tick
// 2.364.0 B (#3031): Start (the overview, route home) is the first icon, on the computer's bar and in the phone's drawer
const SBB_RAIL = [['home', 'start', N_('Start|home'), () => true, ['home']], ['tasks', 'proj', N_('Projects')], ['cal', 'cal', N_('Calendar'), () => feat('cal'), ['cal']],
  ['notes', 'note', N_('Notes'), () => !S.me?.kid, ['notes']],  // 2.398.0 (#3405): Notes are an area of their own (were a view of Projects), in every workspace
  ['office'], ['time'], ['review'], ['life'], ['reading'], ['ablage'],
  ['wiki', 'book', N_('Knowledge|area'), () => feat('wiki'), ['wiki']], ['sheets', 'sheet', N_('Tables'), () => feat('sheets'), ['sheets']],
  ['habits', 'habit', N_('Habits'), () => feat('habits'), ['habits']],
  ['team', 'comment', N_('Chat'), () => teamOn(), ['team']],  // 2.479.0 (#2814): the team chat is an area of its own (was in Projects, its list a second column)
  ['agents', 'bot', N_('Agents'), () => agentsTab(), ['agents']]];
const sbb_def = id => { const r = SBB_RAIL.find(x => x[0] === id); if (!r) return null; const a = mg_area(id); return a ? [id, mg_icon(a), mg_nameKey(a), () => mg_on(id), a[3].map(p => p[0])] : r; };  // 2.173.0 A (#2680): mg_nameKey
const sbb_on = () => !isMobile() && !S.me?.kid && !document.documentElement.classList.contains('mini') && !document.documentElement.classList.contains('mini-task') && !!$('#srail');
// 2.224.0 A (#2817): areas whose panel only repeated the page's head (the calendar: its views are the head's tabs, its
// Calendars window the head's button; Habits one entry; Time / Review two): on a computer no panel, the page takes the
// width and an area's parts are the tabs on top (mg_tabsHtml). The phone's drawer keeps them (sbm_*)
const SBB_NOPANEL = ['cal', 'habits', 'time', 'review', 'home'];  // 2.364.0 B (#3031): Start has no panel either; 2.602.0 (#4817): Notes have one again - their list (chat.js nt_panelHtml, was on the page since 2.398.0 #3405)
const sbb_noPan = (id = sbb_area()) => sbb_on() && SBB_NOPANEL.includes(id);
// 2.196.0 A (#2737): the phone's drawer follows sidebar B: the row of the area icons and ONE panel (sbm_*); children and
// mini windows keep their sidebar. sbb_panelOn = the panel logic runs (computer bar or phone drawer)
const sbm_on = () => isMobile() && !S.me?.kid && !document.documentElement.classList.contains('mini') && !document.documentElement.classList.contains('mini-task');
const sbb_panelOn = () => sbb_on() || sbm_on();
const sbb_areaOfMod = mod => (SBB_RAIL.map(r => sbb_def(r[0])).find(d => d[0] !== 'tasks' && (d[4] || []).includes(mod)) || ['tasks'])[0];
const sbb_area = () => sbb_areaOfMod(S.route.mod);
// the area of a kept hash (the router's first word; old links like client/3 or ev/5 belong to their module)
const SBB_HMOD = {client: 'clients', mailhub: 'clients', ev: 'cal', job: 'agents', note: 'notes'};  // 2.398.0 (#3405): + a single note
const sbb_hashMod = h => { const a = String(h || '').split('/')[0]; return SBB_HMOD[a] || a; };
const sbb_shown = id => { const d = sbb_def(id); return !!d && (id === 'tasks' || d[3]()) && !o3a_hid(id); };
// a page left: the area keeps it (a task / reply / push link keeps the view below it)
function sbb_seen(r) {
  const h = r.task || r.prop || r.msg || r.snooze || r.complete || r.nagoff ? keyToHash(S.route.key) : location.hash.slice(1);
  if (!h) return;
  const id = sbb_areaOfMod(S.route.mod), o = LS.get('sbbLast', {}) || {};
  if (o[id] !== h) { o[id] = h; LS.set('sbbLast', o); }
}
// where an icon leads: the kept page while it still belongs to the area and is switched on, else the area's way in
function sbb_target(id) {
  const h = (LS.get('sbbLast', {}) || {})[id], mod = h && sbb_hashMod(h), a = mg_area(id);
  const ok = !!h && (id === 'tasks' ? sbb_areaOfMod(mod) === 'tasks' : (sbb_def(id)[4] || []).includes(mod) && (!a || !!mg_parts(a).find(p => p[0] === mod)))
    && (mod !== 'office' || (t => !t || ['import', 'services', 'texts', 'settings'].includes(t) || ofm_items().some(i => i.go === 'office/' + t || t === 'subs' && i.key === 'agreements'))(h.split('/')[1]));  // an office point no longer shown (role, pack): not kept
  if (ok) return h;
  return id === 'tasks' ? keyToHash(LS.get('lastKey', START_KEY)) : a ? mg_target(id) : id;
}
// 2.417.0 A (#3559): an area's start page: tapping the icon (or tab) of the area already open leads there. Projects: its start
// page (#projects), an area of MG_AREAS: its first part shown (Office: the office overview), the others their own route
const sbb_home = id => id === 'tasks' ? 'projects' : mg_area(id) ? (mg_partsShown(mg_area(id))[0] || mg_parts(mg_area(id))[0] || [id])[0] : id;
// 2.319.0 B (#3288): Settings > Appearance "Show labels in the app bar" (LOOK_KEYS railLabels, on by default; only off is
// stored). Off: icons only, the bar gets narrower (app.css :root.rail-nolabel), the name stays as title / aria-label
const sbb_labelsOn = () => LS.get('railLabels', true) !== false;
const sbb_nameAttr = name => sbb_labelsOn() ? '' : ` title="${esc(name)}" aria-label="${esc(name)}"`;
function sbb_labelsHtml() {
  return `<h4>${tr('App bar')}</h4>
    <div class="row"><label class="chkl"><input type="checkbox" id="s-rail-lbl" ${sbb_labelsOn() ? 'checked' : ''}> ${tr('Show labels in the app bar')}</label></div>
    <div class="shint">${tr('Off: only the icons, the bar gets narrower. The name shows when you point at an icon.')}</div>`;
}
document.addEventListener('change', e => {
  if (e.target?.id !== 's-rail-lbl') return;
  e.stopPropagation();
  setLocal(tr('Show labels in the app bar'), sbb_labelsOn,
    on => { if (on) LS.del('railLabels'); else LS.set('railLabels', false); const c = document.getElementById('s-rail-lbl'); if (c) c.checked = on; applyLook(); render(); }, e.target.checked);
}, true);
// one area's icon (the computer's bar and the phone's row, 2.196.0 A #2737)
// 2.867.0 (#5540): m = the phone's drawer: a count is a plain dot there (the numbers stand in the rows below it - one count per
// thing; the agents had three: the header pill, the tile, their rows), named for screen readers and on a long look
function sbb_btnHtml(id, cur, hid, aw, m = false) {
  const d = sbb_def(id), on = id === cur;
  if (!sbb_shown(id) || (!on && id !== 'tasks' && (a => a ? mg_sideHidden(id, hid) : hid('e:' + id))(mg_area(id)))) return '';  // Settings > Appearance > Sidebar per part
  const req = id === 'life' && famOn() ? (S.kids || []).reduce((n, k) => n + (k.requests || 0), 0) : 0, n = id === 'agents' ? aw : id === 'team' ? S.team?.unread || 0 : req;  // 2.479.0 (#2814)
  const dot = id === 'time' && (S.timer || S.pomo) ? '<span class="srbd recdot"></span>' : n && m ? `<span class="srbd srdot" role="img" aria-label="${esc(trn('{0} new', '{0} new', n))}" title="${esc(trn('{0} new', '{0} new', n))}"></span>` : n ? `<span class="srbd nunread">${n}</span>` : id === 'wiki' && typeof wki_dotHtml === 'function' ? wki_dotHtml() : '';  // 2.350.0 C (#2744): a running import
  return `<button type="button" class="srb ${on ? 'on' : ''}" data-go="${esc(on ? sbb_home(id) : sbb_target(id))}" data-sbb="${id}"${on ? ' aria-current="page"' : ''}${sbb_on() && !S.me?.kid && !rowd_touch() ? ' draggable="true"' : '' /* 2.575.0 D (#4051); 2.627.0 (#4962): a finger by drag.js */}${sbb_nameAttr(tr(d[2]))}>${ic(d[1])}<span class="srbn">${esc(tr(d[2]))}</span>${dot}</button>`;
}
const sbb_aw = () => (S.agents || []).reduce((n, x) => n + x.waiting + x.chat_unread + (x.approvals_open || 0), 0);
function sbb_railHtml(hid) {
  const cur = sbb_area(), aw = sbb_aw();
  const btn = id => sbb_btnHtml(id, cur, hid, aw);
  // 2.152.3 A (#2619): the account moved up into the head bar (sbb_barHtml). 2.542.0 (#4610): the button "Show the panel" on top
  // of the bar is gone (its place came and went, the icons below moved): a tap on the open area's icon brings the panel back,
  // and a change of the area opens it again (sbb_unfoldOnSwitch)
  return `<div class="srbs">${sbb_ids().map(btn).join('')}</div>`;  // 2.380.2 (#3400): Settings moved into the Kalmido menu of the head bar (sbb_wsMenu); 2.575.0 D (#4051): the person's order
}
// ---- 2.575.0 D (#4051): a right click (computer) or a long press (phone) on an area's icon (the computer's bar, the phone's
// row in the drawer) opens the area's menu: Move up / down (the computer also drags), Hide from the bar (Settings > Appearance >
// Sidebar, the same setting "sidebar"; Projects stays), Customise menu (nav_edit, only areas with an editor), Set as start area
// (setting start_page "a:<id>", core.js st_landing), and for an organisation's admins, apart at the end, Switch off in this
// organisation (orgs.areas_off, the same switch as Settings > Workspaces; the server checks the role). No renaming, no icons.
// The order is the person's (setting nav_menus "rail", one setting the same on every device); an area not named yet keeps its
// usual place after the named ones (nav_sort)
const sbb_ids = () => nav_sort('rail', SBB_RAIL.map(r => r[0]), x => x);
// the keys of an area in the setting "sidebar" ('e:<key>'): only what Settings > Appearance > Sidebar can bring back
const sbb_hideKeys = id => id === 'tasks' || id === 'home' ? null : mg_area(id) ? mg_sideKeys(id) : SIDE_AREA_KEYS.includes(id) || SIDE_VIEW_KEYS.includes(id) ? [id] : null;
const sbb_startKey = id => id === 'home' ? 'home' : 'a:' + id;
// the page an area set as the start opens on (like a click on its icon); an area not shown (off, hidden): Start
const sbb_startHash = id => sbb_def(id) && sbb_shown(id) ? sbb_target(id) : 'home';
// one setting with Undo in the toast; written at once, put back on an error
function sbb_setUndo(k, v, label) {
  const from = S.settings[k] ?? '';
  if (String(from) === String(v)) return Promise.resolve();
  // writes go one after the other through the queue of nav_write (#3506): "Nach oben" pressed twice quickly were two requests
  // at once, the server could store the first move last
  const put = x => async () => { S.settings[k] = x; render(); const q = NAV_Q.then(() => api('PATCH', '/api/settings', {[k]: x})); NAV_Q = q.catch(() => {}); await q; return {}; };
  return put(v)().then(() => offerUndo(label, histAdd({label, undo: put(from), redo: put(v)})), () => { S.settings[k] = from; render(); });
}
// move an area before / after another (to: an area id); the whole order is stored
function sbb_move(id, to, where, name) {
  const o = sbb_ids().filter(x => x !== id), i = o.indexOf(to); if (i < 0 || id === to) return Promise.resolve();
  o.splice(where === 'after' ? i + 1 : i, 0, id);
  nav_pref('rail'); const m = {...NAV.o, rail: {...(NAV.o.rail || {}), order: o}};
  return sbb_setUndo('nav_menus', JSON.stringify(m), tr('{0} moved', name));
}
function sbb_hide(id, name) {
  const keys = sbb_hideKeys(id); if (!keys) return Promise.resolve();
  const p = sidePref(), h = new Set(p.hidden); for (const k of keys) h.add('e:' + k);
  return sbb_setUndo('sidebar', JSON.stringify({order: p.order, hidden: [...h]}), tr('{0} hidden from the bar. Bring it back under Settings > Appearance > Sidebar.', name));
}
// Customise: the area opens first (the editor is drawn in its panel / menu)
function sbb_custom(id) {
  if (sbb_area() !== id) go(sbb_target(id));
  nav_edit(id);
}
// the organisation of the shown workspace whose admin I am (or null): its areas_off is the switch of point 5
const sbb_admOrg = () => { const w = typeof wsCur === 'function' ? wsCur() : ''; const o = w.startsWith('org:') ? wsOrg(w.slice(4)) : null; return o && o.role === 'admin' && Array.isArray(o.areas_off) ? o : null; };
function sbb_orgOff(id, name) {
  const o = sbb_admOrg(); if (!o || !WSA_ORG.includes(id)) return Promise.resolve();
  const put = off => async () => { const j = await api('PATCH', `/api/orgs/${o.id}`, {areas_off: WSA_ORG.filter(x => off.has(x))}); o.areas_off = j?.areas_off || WSA_ORG.filter(x => off.has(x)); WSA.ws = null; render(); return {}; };
  const was = new Set(o.areas_off), now = new Set([...was, id]), label = `${name} · ${o.name}`;
  return put(now)().then(() => offerUndo(tr('{0} off', label), histAdd({label, undo: put(was), redo: put(now)})), () => {});
}
function sbb_railMenu(b) {
  const id = b.dataset.sbb, d = sbb_def(id); if (!d || S.me?.kid) return;
  const name = tr(d[2]), sib = [...b.parentElement.querySelectorAll('.srb[data-sbb]')], i = sib.indexOf(b);
  const up = i > 0 ? sib[i - 1].dataset.sbb : null, down = i >= 0 && i < sib.length - 1 ? sib[i + 1].dataset.sbb : null;
  const start = (S.settings?.start_page || 'home') === sbb_startKey(id), org = WSA_ORG.includes(id) && sbb_admOrg();
  menu(b, [
    up ? {label: tr('Move up'), icon: 'up', act: 'sbb-up', fn: () => sbb_move(id, up, 'before', name)} : null,
    down ? {label: tr('Move down'), icon: 'down', act: 'sbb-down', fn: () => sbb_move(id, down, 'after', name)} : null,
    sbb_hideKeys(id) ? {label: tr('Hide from the bar'), icon: 'eyeoff', act: 'sbb-hide', fn: () => sbb_hide(id, name)} : null,
    nav_canEdit(id) ? {label: tr('Customise menu …'), icon: 'edit', act: 'sbb-custom', fn: () => sbb_custom(id)} : null,
    {label: tr('Set as start area'), icon: 'start', act: 'sbb-start', on: start, dis: start, title: start ? tr('The app opens on this area') : '', fn: () => sbb_setUndo('start_page', sbb_startKey(id), tr('The app opens on {0}', name))},
    org ? '-' : null,
    org ? {label: tr('Switch off in this organisation'), icon: 'ban', cls: 'danger', act: 'sbb-orgoff', fn: () => sbb_orgOff(id, name)} : null,
  ].filter(Boolean), null, null, name);
}
const SBB_RMENU = '#srail .srb[data-sbb], #side .sbmr .srb[data-sbb]';
const SBB_RLP = ms_rowMenu(SBB_RMENU, sbb_railMenu);  // touch: a long press (the click ending it opens nothing)
document.addEventListener('contextmenu', e => {
  const b = e.target.closest?.(SBB_RMENU); if (!b || S.me?.kid) return;
  e.preventDefault(); if (e.pointerType === 'touch' || isTouch()) return;  // touch: the long press above
  sbb_railMenu(b);
});
// the computer drags an icon before / after another (a line marks the place)
let SBB_RDRAG = null;
const sbb_rzone = (t, y) => { const r = t.getBoundingClientRect(); return y < r.top + r.height / 2 ? 'before' : 'after'; };
const sbb_rmark = (t, z) => { for (const x of $$('#srail .srb.srbdbef, #srail .srb.srbdaft')) x.classList.remove('srbdbef', 'srbdaft'); t?.classList.add(z === 'after' ? 'srbdaft' : 'srbdbef'); };
document.addEventListener('dragstart', e => {
  const b = e.target.closest?.('#srail .srb[data-sbb][draggable="true"]'); if (!b) return;
  SBB_RDRAG = b.dataset.sbb; e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', b.textContent.trim()); b.classList.add('dragging');
});
document.addEventListener('dragover', e => {
  if (!SBB_RDRAG) return;
  const t = e.target.closest?.('#srail .srb[data-sbb]'); if (!t || t.dataset.sbb === SBB_RDRAG) { sbb_rmark(null); return; }
  e.preventDefault(); e.dataTransfer.dropEffect = 'move'; sbb_rmark(t, sbb_rzone(t, e.clientY));
});
document.addEventListener('drop', e => {
  if (!SBB_RDRAG) return;
  const id = SBB_RDRAG, t = e.target.closest?.('#srail .srb[data-sbb]'); SBB_RDRAG = null; sbb_rmark(null);
  if (!t || t.dataset.sbb === id) return;
  e.preventDefault(); sbb_move(id, t.dataset.sbb, sbb_rzone(t, e.clientY), tr(sbb_def(id)?.[2] || id));
});
document.addEventListener('dragend', () => { if (!SBB_RDRAG && !$('#srail .srb.dragging')) return; SBB_RDRAG = null; sbb_rmark(null); $$('#srail .srb.dragging').forEach(x => x.classList.remove('dragging')); });
// 2.627.0 (#4962): the finger by drag.js: hold an icon, then drag it before / after another one (the same sbb_move as the mouse);
// a swipe without the hold scrolls the bar, a quick tap opens the area as before, held and let go without moving = its menu
// (what the long press did). The mouse keeps the browser's drag above.
const sbb_rfinger = (d, x, y) => { const t = /** @type {any} */ (document.elementFromPoint(x, y))?.closest?.('#srail .srb[data-sbb]'); return t && t.dataset.sbb !== d.id ? t : null; };
const sbb_rfOff = d => { d.b.classList.remove('dragging'); sbb_rmark(null); };
drg_attach(document, {
  mouse: false, hold: ROWD_HOLD, holdMove: 8, onTarget: true, raf: true, ghost: {el: d => d.b, cls: 'ghost-drag'},
  scroll: () => $('#srail'), edge: 40, step: 10,
  start: t => {
    const b = /** @type {any} */ (t).closest?.('#srail .srb[data-sbb]');
    return b && sbb_on() && !S.me?.kid && sbb_def(b.dataset.sbb) ? {b, id: b.dataset.sbb} : null;
  },
  onHold: d => { ms_lpTake(SBB_RLP); d.b.classList.add('dragging'); if (navigator.vibrate) navigator.vibrate(12); },
  onMove: (d, x, y) => { const t = sbb_rfinger(d, x, y); sbb_rmark(t, t && sbb_rzone(t, y)); },
  onDrop: (d, x, y) => { const t = sbb_rfinger(d, x, y); sbb_rfOff(d); if (t) sbb_move(d.id, t.dataset.sbb, sbb_rzone(t, y), tr(sbb_def(d.id)?.[2] || d.id)); },
  onTap: d => { sbb_rfOff(d); const b = d.b.isConnected ? d.b : $(`#srail .srb[data-sbb="${d.id}"]`); if (b) sbb_railMenu(b); },
  onCancel: sbb_rfOff,
});
// 2.542.0 (#4610): another area than the one drawn last opens the panel again (LS sideFold back to false, the layout follows
// at once; no extra render). The first drawing after a load keeps the hidden panel; folded for room (#3163) and areas
// without a panel (SBB_NOPANEL) stay as they are
let sbb_lastArea = null;
function sbb_unfoldOnSwitch() {
  if (!S.booted) return;  // the cached state drawn before the first route() still says Tasks
  const cur = sbb_area(), was = sbb_lastArea; sbb_lastArea = cur;
  if (was === null || was === cur || !LS.get('sideFold', false)) return;
  LS.set('sideFold', false); fitLayout(true);
}
// called by renderSide: the bar (or nothing on a phone); the account node stays the same <img> when nothing changed
function sbb_render(hid) {
  const r = $('#srail'), on = sbb_on(); $('#app')?.classList.toggle('sb-b', on); if (!r) return;
  $('#app')?.classList.toggle('sbb-nopan', sbb_noPan());  // 2.224.0 A (#2817): app.css drops the panel's column
  sbb_bar();  // 2.152.3 A (#2619)
  if (!on) { if (r.innerHTML) r.innerHTML = ''; return; }
  sbb_unfoldOnSwitch();  // 2.542.0 (#4610)
  r.setAttribute('aria-label', tr('Areas|nav'));
  r.innerHTML = sbb_railHtml(hid);
  sbb_rove();
  requestAnimationFrame(sbb_fit);
}
// 2.458.0 (#3880): a name never breaks inside a word (app.css .srbn): too wide = a smaller type, down to 9 px; wider still "…" + title
// #3506 (#3405): a smaller type can break a name into other lines: measured again after each step (scrollWidth too) until it fits
// #4047: phone: never cut or split: a word too wide in 9 px: each column as wide as its names need; if that is too wide, the row scrolls
function sbb_fit() {
  const row = $('#side .sbmr'), y = row?.closest('#side').scrollTop;
  if (row) row.style.gridTemplateColumns = row.style.overflow = '';
  let far;
  const wide = n => { const rg = document.createRange(); rg.selectNodeContents(n); return Math.max(rg.getBoundingClientRect?.().width || 0, n.scrollWidth); };
  for (const n of $$('#srail .srbn, #side .sbmr .srbn')) {
    n.classList.remove('srcut'); n.style.fontSize = '';
    const box = n.clientWidth; if (!box) continue;
    let need = wide(n);
    if (need <= box + .5) continue;
    let px = parseFloat(getComputedStyle(n).fontSize) * box / need;
    for (let i = 0; i < 12 && px >= 9; i++) {
      n.style.fontSize = `${Math.floor(px * 10) / 10}px`;
      need = wide(n);
      if (need <= box + .5) break;
      px = Math.min(px - .2, px * box / need);
    }
    if (px < 9 || need > box + .5) {
      if (n.closest('.sbmr')) { n.style.fontSize = '9px'; far = 1; continue; }
      n.style.fontSize = ''; n.classList.add('srcut'); n.closest('.srb').title ||= n.textContent;
    }
  }
  // 2.867.0 (#5540): the drawer writes every name in ONE size - the smallest any of its names needed ("Gewohnheiten" smaller than
  // the rest looked uneven); the bar of a computer keeps its own size per name
  const mn = row ? $$('.srbn', row) : [], one = mn.length ? Math.min(...mn.map(n => parseFloat(n.style.fontSize) || Infinity)) : Infinity;
  if (one < Infinity) for (const n of mn) n.style.fontSize = `${one}px`;
  if (far) {
    // 2.660.0 (#5103): a column needs its widest name's text plus the tile's padding and border - no longer the box a fitting
    // name fills (its scrollWidth) plus 4 px: that widened every column that already fitted, 11 areas scrolled 5 px at 320 px
    const c = +row.style.getPropertyValue('--sbmc'), w = [], t = $('.srb', row), ts = getComputedStyle(t);
    const pad = t.offsetWidth - t.clientWidth + parseFloat(ts.paddingLeft) + parseFloat(ts.paddingRight);
    const text = n => { if (n.scrollWidth > n.clientWidth + .5) return wide(n); const rg = document.createRange(); rg.selectNodeContents(n); return rg.getBoundingClientRect?.().width || n.scrollWidth; };
    $$('.srbn', row).forEach((n, i) => { w[i % c] = Math.max(w[i % c] || 0, Math.ceil(text(n) + pad)); });
    // 2.867.0 (#5540): equal columns here too (the widest name's width for every column; the row scrolls)
    row.style.gridTemplateColumns = `repeat(${c},minmax(${Math.max(...w)}px,1fr))`; row.style.overflow = 'auto hidden';
    row.closest('#side').scrollTop = y;  // measuring moved the row's height: the drawer stays where it was
  }
  sbb_fitWatch();
}
// 2.651.0 (#5063): a name's size can change after the fit without a redraw, resize or font event (Firefox measured a reset
// name in its old 9 px type during a font load; a moment later it drew in 10 px, too wide for its column, and nothing fitted it
// again: "Rückblick" split / cut in the 320 px drawer). Each name's box is noted at the end of a fit; when it differs later,
// the fit runs again in the next frame. The fit's own result is noted, so a fit never wakes itself (no loop)
// 2.660.0 (#5103): that holds only while the fit's sizes take effect at once: under "reduce motion" they were transitions,
// the fit measured the old size and woke itself every other frame (since 2.665.0 #5115 app.css gives sizes no transition, so
// 2.677.0 #5126 dropped the own exception css/start-sbfit-5103.css). Width AND height are noted: a name in a
// full column grows only in height (a second line) when its type grows
const SBB_FITSZ = new WeakMap();
let sbb_fitRO = null, sbb_fitDue = false;
function sbb_fitWatch() {
  if (typeof ResizeObserver !== 'function') return;
  sbb_fitRO ||= new ResizeObserver(es => {
    const moved = e => { const o = SBB_FITSZ.get(e.target); return !!o && (Math.abs(e.contentRect.width - o.w) > .5 || Math.abs(e.contentRect.height - o.h) > .5); };
    if (sbb_fitDue || !es.some(e => e.target.isConnected && moved(e))) return;
    sbb_fitDue = true; requestAnimationFrame(() => { sbb_fitDue = false; sbb_fit(); });
  });
  for (const n of $$('#srail .srbn, #side .sbmr .srbn')) { const r = n.getBoundingClientRect(); SBB_FITSZ.set(n, {w: r.width, h: r.height}); sbb_fitRO.observe(n); }
}
window.addEventListener('resize', () => requestAnimationFrame(sbb_fit));
document.fonts?.addEventListener('loadingdone', sbb_fit);
// ---- 2.196.0 A (#2737): the phone's drawer like sidebar B. On top (fixed) search, Today, Inbox and ONE row of the area icons
// (the bar's icons, order and rights; it scrolls sideways, never wraps), below the chosen area's panel, at the bottom Settings
// and the account. An icon opens the page its area kept and the drawer stays open; the first change in an open drawer adds
// one history entry, the next ones replace it, so one Back closes the drawer (route() closes it on that entry)
const SBM = {keep: false, focus: ''};
// the row is one tab stop of its own (a scrolling region reachable by keyboard; its icons rove with the sidebar)
// 2.442.0 (#3739): --sbmc = columns (2.867.0 #5540: sbm_cols, a fixed grid of 4 instead of at most two rows)
// 2.867.0 (#5540): a fixed grid of equal columns: up to 5 areas one row, more = 4 per row (was up to 7 x 2, the columns as wide
// as their names: Office airy, Projects / Calendar / Notes tight)
const sbm_cols = n => n <= 5 ? n : 4;
const sbm_rowHtml = hid => { const cur = sbb_area(), aw = sbb_aw(), bs = sbb_ids().map(id => sbb_btnHtml(id, cur, hid, aw, true)).filter(Boolean);  /* 2.575.0 D (#4051): the person's order */ return `<div class="sbmr" style="--sbmc:${/*html-ok*/ sbm_cols(bs.length)}" role="group" tabindex="0" aria-label="${esc(tr('Areas|nav'))}">${bs.join('')}</div>`; };
// route() asks once whether this route came from the row (the drawer stays open)
const sbm_hold = () => { const k = SBM.keep; SBM.keep = false; return k && !!$('#side.open'); };
function sbm_go(b) {
  const h = b.dataset.go; SBM.focus = b.dataset.sbb;
  if (!h) { b.focus({preventScroll: true}); return; }
  if ('#' + h === location.hash) { closeSide(); return; }  // 2.619.0 (#4943): the icon of the page already open closes the drawer like any other entry (was: the focus only, the drawer stayed); 2.417.0 A (#3559): else the open area's icon leads to its start page (sbb_btnHtml)
  SBM.keep = true; setTimeout(() => { SBM.keep = false; }, 3000);  // no route followed (same page): never hold a later one
  // the entry the drawer was opened on forgets "reopen the drawer" (#953), so Back from the area lands closed
  if (!history.state?.sbm && history.state?.side) try { const {side, ...st} = history.state; history.replaceState(Object.keys(st).length ? st : null, '', location.href); } catch { /* old browser */ }
  if (history.state?.sbm) location.replace('#' + h); else go(h);
  try { history.replaceState({...(history.state || {}), sbm: 1}, '', location.href); } catch { /* old browser */ }
}
document.addEventListener('click', e => {
  const b = e.target.closest?.('#side .sbmr .srb[data-sbb]'); if (!b) return;
  e.preventDefault(); e.stopPropagation(); sbm_go(b);
}, true);
// 2.867.0 (#5540): the phone's drawer: a tap on an agent's status dot explains it (name, state, what the colours mean) instead of
// opening the chat; the rest of the row opens it as before. The computer keeps the dot's title on hover
document.addEventListener('click', e => {
  const s = e.target.closest?.('#side .steam .sdot'); if (!s || !sbm_on()) return;
  const r = s.closest('.steam'), a = agentById(+(r.dataset.aid || String(r.dataset.go || '').split('/')[1]));
  if (!a) return;
  e.preventDefault(); e.stopPropagation();
  toast(`${agentHstLine(a)} · ${tr('Green: ready · Blue: working · Yellow: waiting for you · Grey: off or not connected · Red: error')}`, undefined, 6000);
}, true);
// after renderSide: the row keeps its sideways position, the open area's icon in sight; the tapped icon keeps the focus
function sbm_after(x) {
  const r = $('#side .sbmr'); if (!r) return;
  requestAnimationFrame(sbb_fit);
  if (x != null) r.scrollLeft = x;
  const b = $('.srb.on', r);
  const rr = r.getBoundingClientRect(), br = b?.getBoundingClientRect();
  if (br && (br.left < rr.left || br.right > rr.right)) r.scrollLeft = Math.max(0, r.scrollLeft + br.left - rr.left - (rr.width - br.width) / 2);
  const f = SBM.focus && $(`.srb[data-sbb="${CSS.escape(SBM.focus)}"]`, r);
  if (f && $('#side.open') && (!document.activeElement || document.activeElement === document.body)) { SBM.focus = ''; f.focus({preventScroll: true}); }
}
// ---- 2.152.3 A (#2619, direction 4 of 22.10.): ONE low bar over everything on a computer (#kbar, above the bar of the
// areas, the panel and the page): the brand with the shown workspace (its menu switches, adds a company, opens its
// settings), the search (the command palette, Mod+K), the bell, the connection dot and the account. Phones, the mini
// windows and children keep the header as before (sbb_on). The page's header (#top) keeps the title and its own buttons.
let sbb_barLast = '';
function sbb_barHtml() {
  // P4: without an organisation the switch shows the private space (its menu: Private + "Add a company")
  const cur = wsOn() ? wsCur() : 'private', nm = wsName(cur);
  const acct = S.me ? `<button type="button" class="kbacct" data-act="user-menu" aria-haspopup="menu" title="${esc(acctLabel())}" aria-label="${esc(acctLabel())}">${av(S.me.id, S.me.display_name, 'avatar', '', '', true)}</button>` : '';
  return `<button type="button" class="kbsw" data-act="sbb-ws" aria-haspopup="menu" aria-label="${esc(APP_NAME + ' · ' + tr('Workspace') + ': ' + nm)}" title="${esc(tr('Switch to'))}"${wsp_attr(cur)}><span class="kbbrand">${logoSvg(28)}${wordSvg()}</span><span class="kbfirm">${cur === 'all' ? ic('grid', 's') : wsp_dot(cur)}<span class="wsn">${esc(nm)}</span>${ic('chev', 's')}</span>${updDot() ? `<span class="kbupd" title="${esc(tr('Update available'))}"></span>` : ''}</button>`
    + '<div class="fv2bar" role="group"></div>'  // 2.441.0 (#3592): the favourites, only in the free room (favtiles.js fv2_barDraw)
    + `<button type="button" class="kbsrch" data-act="palette" title="${esc(tr('Search and commands'))} (${kbText('Mod+K')})" aria-label="${esc(tr('Search and commands'))}">${ic('search', 's')}<span>${esc(tr('Search'))}</span></button>`
    + `<span class="kbend">${bellBtn()}${netDotHtml()}${acct}</span>`;
}
// drawn with the sidebar and with the page's header (the bell's number); only when something changed, the account keeps its <img>
function sbb_bar() {
  const k = $('#kbar'); if (!k) return;
  if (!sbb_on()) { if (k.innerHTML) { k.innerHTML = ''; sbb_barLast = ''; } fv2_barDraw(); return; }
  const html = sbb_barHtml(); if (html === sbb_barLast && k.firstChild) { fv2_barDraw(); return; }
  sbb_barLast = html; k.setAttribute('aria-label', APP_NAME);
  const old = $('.kbacct', k);
  keepFocus(k, () => setHtml(k, html));
  const nu = $('.kbacct', k); if (old && nu && old !== nu && old.innerHTML === nu.innerHTML && old.title === nu.title) nu.replaceWith(old);
  fv2_barDraw();
}
// the workspace menu of the bar: "Switch to", each company with its own sign (picture / symbol / initial), Private (house),
// the shown one ticked; then "Add a company" and, while a company is shown, its settings. The switch itself is wsSet.
function sbb_wsMenu(anchor) {
  const cur = wsOn() ? wsCur() : 'private', all = wsOn() ? wsOptions() : ['private'];
  const opts = [...all.filter(w => w.startsWith('org:')), ...all.filter(w => !w.startsWith('org:'))];  // the companies first (sketch)
  const set = cur.startsWith('org:') && typeof lmOrgPaneOn === 'function' && lmOrgPaneOn();
  const p = menu(anchor, [{head: tr('Switch to')}, ...opts.map(ws => ({label: wsName(ws), icon: ws === 'private' ? 'home' : ws === 'all' ? 'grid' : 'brief', on: ws === cur, cls: 'kbwsi', title: wsName(ws), fn: () => { if (ws !== wsCur()) wsSet(ws); }})),
    '-', {label: tr('Settings'), icon: 'gear', cls: 'kbws-settings', keys: 'g s', sub: updDot() ? tr('Update available') : '', fn: () => settingsModal()},  // 2.380.2 (#3400)
    {label: tr('Add an organisation'), icon: 'plus', cls: 'kbws-add', fn: sbb_orgAdd},
    ...(set ? [{label: tr('Company settings'), icon: 'building', cls: 'kbws-set', fn: () => settingsModal('org')}] : [])]);
  // each company's own sign in place of the icon: its picture or symbol, else its initial on a tile
  opts.forEach((ws, i) => {
    if (!ws.startsWith('org:')) return;
    const b = p?.querySelector(`[role="menuitem"][data-i="${i + 1}"]`), o = wsOrg(ws.slice(4)), x = b?.querySelector('svg.i');
    if (x) x.outerHTML = `<span class="kbwsic">${orgIconHtml(o, `<span class="kbini" aria-hidden="true">${esc(String(o?.name || '?').trim().charAt(0).toUpperCase())}</span>`)}</span>`;
  });
}
// "Add a company": an admin of the server creates one (the dialog of Administration); 2.422.0 (#2937): anybody else creates
// a company of her own by its name (POST /api/orgs, she becomes its admin) and lands in it; where the server does not allow
// that (not the mode workspaces, the limit reached) the answer says why
async function sbb_orgAdd() {
  if (S.me?.is_admin && typeof orgModal !== 'function') await loadModule('settings').catch(() => {});  // 2.152.3: orgModal lives in the lazy settings module
  if (S.me?.is_admin && typeof orgModal === 'function') { orgModal(null, () => load().then(render).catch(() => {})); return; }
  const name = ((await askPrompt(tr('Name of the new company'), '', {body: tr('Keeps your work apart from your private things. You become its admin and can invite people by e-mail.'), ok: tr('Create'), input: {max: 60}})) || '').trim();
  if (!name) return;
  let o; try { o = await api('POST', '/api/orgs', {name}); } catch (x) {
    await askConfirm(tr('Add an organisation'), x.status === 403 ? tr('A company is set up by the admin of this server. A company’s admin can then invite you by e-mail.') : (x.message || tr('unknown')), {ok: tr('OK')});
    return;
  }
  await load().catch(() => {});
  if (typeof wsSet === 'function') wsSet('org:' + o.id); else render();
  toast(tr('The company “{0}” is set up', o.name));
}
// the panel's head: the area's name, "Fold all" / "Unfold all" (only a panel with groups that fold: Tasks, or a panel whose
// html has sbb_head groups or a tree marked data-sbbfold) and "Hide the panel". pan = the panel's html (not Tasks)
const sbb_foldGroups = pan => pan == null ? $$('#side [data-act="sbb-group"]').map(b => b.dataset.g)
  : [...pan.matchAll(/data-act="sbb-group" data-g="([^"]*)"/g)].map(m => m[1].replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&'));
function sbb_foldOpen(id, pan) {
  if (id === 'tasks') return kbSideAnyOpen();
  return sbb_foldGroups(pan).some(g => !sbb_folded(g)) || sbb_treeShown(pan);  // 2.276.0 A (#3039): sbb_folded (Money folded at first)
}
// 2.198.0 B (#2764): a tree counts as open when any of its nodes is drawn open (measured at the html, so folders open by
// themselves on the way to the open one count too)
const sbb_treeShown = pan => pan == null ? !!$('#side [data-act="sbb-tree"][data-open="1"]') : /data-act="sbb-tree"[^>]*data-open="1"/.test(pan);
// 2.152.3 (#2620 #2621): a folder tree of Knowledge / File store counts while a folder is open (fold all only, the trees
// load lazily, so there is no unfold all for them)
function sbb_headHtml(id, pan = '') {
  const d = sbb_def(id), groups = id === 'tasks' || /data-act="sbb-group"|data-sbbfold/.test(pan) || /data-act="sbb-tree"/.test(pan);  // 2.198.0 B (#2764): with a tree the button always stays
  const open = groups && sbb_foldOpen(id, pan), lab = open ? tr('Fold all') : tr('Unfold all');
  const fold = groups ? `<button type="button" class="iconbtn sbbfa" data-act="sbb-foldall" aria-pressed="${!open}" title="${esc(lab)}" aria-label="${esc(lab)}">${ic(open ? 'collapse' : 'expand', 's')}</button>` : '';
  const hide = `<button type="button" class="iconbtn sbbhide" data-act="sbb-panel" title="${esc(tr('Hide the panel'))}" aria-label="${esc(tr('Hide the panel'))}">${ic('panelhide', 's')}</button>`;
  return `<h2 class="sbbpt">${esc(tr(d ? d[2] : 'Projects'))}</h2><span class="spacer"></span><span class="sbtools">${fold}${id === 'tasks' ? fv2_svToolBtn() /* 2.156.0 D (#2186) */ : ''}${id === 'team' ? tc_newBtnHtml() /* 2.479.0 (#2814) */ : ''}${hide}</span>`;
}
function sbb_foldAll() {
  const id = sbb_area(), close = sbb_foldOpen(id);
  if (id === 'tasks') { kbSideSetAll(close); return; }
  for (const g of sbb_foldGroups()) sbb_foldSet(g, close);  // 2.276.0 A (#3039)
  if ($('#side [data-act="sbb-tree"]')) close ? sbb_treeCloseAll() : sbb_treeOpenAll();
  renderSide();
  $('#side .sbbfa')?.focus({preventScroll: true});
}
// hide / show the panel: kept per device (LS sideFold, the same switch as before); while a narrow window shows the panel
// as a drawer the button opens / closes that drawer
function sbb_panel() {
  const fold = !!LS.get('sideFold', false), rail = !!$('#app')?.classList.contains('side-rail');
  if ($('#side')?.classList.contains('open')) { closeSide(); if (!fold) return; }
  if (rail && !fold) { $('#top .menu')?.click(); return; }
  sideFold(!fold);
  if (fold && $('#app')?.classList.contains('side-rail')) { $('#top .menu')?.click(); return; }  // still too narrow: the drawer
  setTimeout(() => (fold ? $('#side .sbbhide') : $('#srail .srb.on'))?.focus({preventScroll: true}), 0);  // 2.542.0 (#4610): hidden: the open area's icon (it brings the panel back)
}
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-act="sbb-ws"], [data-act="sbb-foldall"], [data-act="sbb-panel"]'); if (!b) return;
  e.preventDefault(); e.stopPropagation();
  const a = b.dataset.act;
  if (a === 'sbb-ws') sbb_wsMenu(b); else if (a === 'sbb-foldall') sbb_foldAll(); else sbb_panel();
}, true);
// with the panel hidden by hand (or folded for room) a click on the open area's icon brings it back
document.addEventListener('click', e => {
  const b = e.target.closest?.('#srail .srb.on[data-sbb]'); if (!b || !(LS.get('sideFold', false) || $('#app')?.classList.contains('side-rail')) || !sbb_on() || sbb_noPan()) return;  // 2.224.0 A (#2817): no panel to bring back; 2.290.0 C (#3163): folded for room (task open) = the drawer
  e.preventDefault(); e.stopPropagation(); sbb_panel();
}, true);
const sbb_railItems = () => $$('#srail .srb');  // 2.152.3 A (#2619); 2.542.0 (#4610): no panel button to leave out any more
// the bar is ONE tab stop: Tab lands on the open area, up / down (Home / End) walk the icons
function sbb_rove(cur) {
  const it = sbb_railItems(); if (!it.length) return;
  const keep = cur || it.find(b => b === document.activeElement) || it.find(b => b.classList.contains('on')) || it[0];
  for (const b of it) b.tabIndex = b === keep ? 0 : -1;
}
document.addEventListener('keydown', e => {
  const b = e.target.closest?.('#srail .srb'); if (!b || e.ctrlKey || e.metaKey || e.altKey) return;
  const it = sbb_railItems(), i = it.indexOf(b), to = {ArrowDown: i + 1, ArrowUp: i - 1, Home: 0, End: it.length - 1}[e.key];
  if (to === undefined || i < 0) return;
  e.preventDefault(); e.stopPropagation();
  const n = it[Math.max(0, Math.min(it.length - 1, to))]; sbb_rove(n); n.focus();
}, true);
// the panel of an area other than Tasks: its name, then its entries (rows like the sidebar's, the open one in the accent)
const sbb_row = (go, icon, name, on, attrs = '', after = '') => `<button type="button" class="srow smod sbbi ${on ? 'on' : ''}" data-go="${esc(go)}"${on ? ' aria-current="page"' : ''} ${attrs}>${ic(icon)}<span class="n">${esc(name)}</span>${after}</button>`;
// the calendar: its views (the page's Month / Week / … buttons) and its calendars window, nothing new
function sbb_calHtml() {
  const modes = [['month', N_('Month')], ['week', N_('Week')], ['day', N_('Day')], ['year', N_('Year')], ...(feat('events') ? [['agenda', N_('Agenda')]] : []), ...(feat('timeline') ? [['timeline', N_('Timeline')]] : [])];
  const onCal = S.route.mod === 'cal' && !S.lcal;
  const rows = modes.map(([k, n]) => `<button type="button" class="srow smod sbbi ${onCal && S.calMode === k ? 'on' : ''}" data-act="cal-mode" data-k="${k}" data-sbbcal="${k}"${onCal && S.calMode === k ? ' aria-current="true"' : ''}>${ic(k === 'timeline' ? 'timeline' : k === 'agenda' ? 'list' : 'cal')}<span class="n">${esc(tr(n))}</span></button>`).join('');
  const cals = feat('events') || S.calendars?.enabled ? `<button type="button" class="srow smod sbbi" data-act="ev-cals">${ic('cal')}<span class="n">${esc(tr('Calendars'))}</span></button>` : '';
  return `<div class="sgroup sbbp"><div class="shead sgh"><span class="sgt">${esc(tr('View'))}</span></div>${rows}</div>${cals ? `<div class="sgroup sbbp">${cals}</div>` : ''}`;
}
// 2.152.2 (#2617): the office: Sell / Money / Administration as small headings, each folds on its own (per device, LS
// sbbFold, open at first), the points below (order of #2616), the open one in the accent
// 2.276.0 A (#3039): Money starts folded until the office has its first invoice or receipt (not known yet: open as before) and
// opens while one of its points is shown; a group folded (sbbFold) or opened (sbbUnfold) by hand keeps that choice
const sbb_folded = g => (LS.get('sbbFold', []) || []).includes(g) || g === 'office:money' && !(LS.get('sbbUnfold', []) || []).includes(g) && ofm_moneyNew();
const ofm_moneyNew = () => { const u = ofm_used(); if (!u || u.invoice || u.receipt) return false; return !(mg_areaOf(S.route.mod)?.[0] === 'office' && ofm_all().find(i => i.key === ofm_cur(S.route.mod))?.group === 'money'); };
// 2.276.0 A (#3039): a fold by hand (panel, phone start page, fold all): the choice in sbbFold / sbbUnfold
function sbb_foldSet(g, fold) {
  const x = new Set(LS.get('sbbFold', []) || []), y = new Set(LS.get('sbbUnfold', []) || []);
  if (fold) { x.add(g); y.delete(g); } else { x.delete(g); if (g === 'office:money') y.add(g); }
  LS.set('sbbFold', [...x]); LS.set('sbbUnfold', [...y]);
}
const sbb_head = (g, label, n, on) => `<div class="shead sgh sbbg ${sbb_folded(g) ? 'closed' : ''} ${on ? 'sgon' : ''}"><button class="sgt" data-act="sbb-group" data-g="${esc(g)}" aria-expanded="${!sbb_folded(g)}">${ic('chev', 's fcar')}<span>${esc(label)}</span>${sbb_folded(g) && n ? `<span class="c">${n}</span>` : ''}</button></div>`;
function sbb_officeHtml() {
  const its = ofm_items(), here = sbb_area() === 'office', cur = here ? ofm_cur(S.route.mod) : '';
  return OFM_GROUPS.map(g => {
    const gi = its.filter(i => i.group === g[0]), k = 'office:' + g[0], on = gi.some(i => i.key === cur), solo = !!g[3]; if (!gi.length) return '';
    return `<div class="sgroup sbbp" data-ofmg="${g[0]}">${solo ? '' : sbb_head(k, tr(g[2]), gi.length, on && sbb_folded(k))}${!solo && sbb_folded(k) ? '' : gi.map(i => (typeof oft_rowHtml === 'function' && oft_rowHtml(i, i.key === cur)) || sbb_row(i.go, i.icon, tr(i.name), i.key === cur, `data-ofm="${i.key}" data-navk="office:${i.key}"`)).join('')}</div>`;
  }).join('')  // 2.351.0 A (#3312): a document area opens as a tree (office_tree.js: its folders, 20 newest, More…); no group "Folders"
    + (typeof ctf_panelHtml === 'function' ? ctf_panelHtml() : '');  // 2.351.0 B (#2749): the address book's folders (ctfold.js, on its page)
}
// the office's points can change after the sidebar was drawn (the office loads lazily, its role arrives): a draw of an office
// page redraws the sidebar once its panel would look different
let sbb_ofcLast = '';
function sbb_officeSync() {
  if (!sbb_panelOn() || sbb_area() !== 'office') return;
  setTimeout(() => { const h = sbb_officeHtml(); if (h !== sbb_ofcLast && sbb_area() === 'office') renderSide(); }, 0);
}
// 2.152.3 B (#2619 #2620 #2621): the panels of tables, knowledge and the file store draw from data that arrives later (and
// changes): their module calls sbb_sync(id) after a load, the panel is drawn again once it would look different
const SBB_LAST = {};
function sbb_sync(id) {
  if (!sbb_panelOn() || sbb_area() !== id) return;
  setTimeout(() => { const old = SBB_LAST[id]; if (sbb_area() === id && (sbb_panelHtml(id), SBB_LAST[id] !== old)) renderSide(); }, 0);
}
// 2.152.3 B (#2620 #2621): folder trees in the panel (knowledge, file store), rows like the project rows (arrow, indent, the
// open one in the accent). A folder's subfolders are drawn (and loaded) only once its arrow opened it, the path down to the
// open folder is always open. Open nodes per device in LS sbbOpen ('wk:<space>:<path>', 'ab:<id>'); "Collapse all" of the
// panel head empties it (sbb_treeCloseAll). nodes: [{k, name, go, on, kids, open, icon, attrs (row), battrs (name button), sub() -> nodes (null = loading)}]
const sbb_treeOpen = k => (LS.get('sbbOpen', []) || []).includes(k);
// 2.199.0 A (#2742): the key prefixes of each area's trees (Fold all / Unfold all); the first one names the remembered state
// (LS sbbMem). Knowledge 'wk:', file store 'ab:' + documents 'dc:', office 'of:', tables 'sh:'
const SBB_TPRE = {wiki: ['wk:'], ablage: ['ab:', 'dc:'], office: ['of:'], sheets: ['sh:']};
const sbb_tpre = () => SBB_TPRE[sbb_area()] || [];
const sbb_tpreHas = (pre, k) => pre.some(p => k.startsWith(p));
// 2.152.3: folders on the path to the open folder are open by themselves; closing one by hand (or Fold all) wins until reload
const SBB_SHUT = new Set();
function sbb_treeCloseAll() {
  // 2.198.0 B (#2764): remember what was open (per area prefix, per device in LS sbbMem) so "Unfold all" brings it back
  const pre = sbb_tpre(), keys = $$('#side [data-act="sbb-tree"][data-open="1"]').map(b => b.dataset.k), o = LS.get('sbbOpen', []) || [];
  if (pre.length) { const m = LS.get('sbbMem', {}) || {}; m[pre[0]] = [...new Set([...keys, ...o.filter(k => sbb_tpreHas(pre, k))])].slice(-300); LS.set('sbbMem', m); }
  const rest = pre.length ? o.filter(k => !sbb_tpreHas(pre, k)) : [];
  if (o.length !== rest.length) LS.set('sbbOpen', rest);
  keys.forEach(k => SBB_SHUT.add(k));
}
// 2.198.0 B (#2764): restore the remembered state; without one open the first level (the level-0 arrows of the drawn panel)
function sbb_treeOpenAll() {
  const pre = sbb_tpre()[0], m = LS.get('sbbMem', {}) || {};
  let keys = pre && m[pre] || [];
  if (!keys.length) keys = $$('#side .sbbt[style*="--sbbl:0"] [data-act="sbb-tree"]').map(b => b.dataset.k);
  keys.forEach(k => SBB_SHUT.delete(k));
  LS.set('sbbOpen', [...new Set([...(LS.get('sbbOpen', []) || []), ...keys])].slice(-300));
  if (pre && m[pre]) { delete m[pre]; LS.set('sbbMem', m); }
}
function sbb_treeAnyOpen() {
  const pre = sbb_tpre();
  return !!pre.length && (LS.get('sbbOpen', []) || []).some(k => sbb_tpreHas(pre, k));
}
// 2.199.0 A (#2742): a node may also carry ns (the module's handlers, sbb_treeReg), id, par (its parent's key: siblings share
// it), drag (dragged to move / sort), drop (takes nodes into it), menu (right-click / long press / the context key) and auto
// (an automatic group: a filter view -- other look, never dragged, dropped on, sorted, shared or given a menu)
// 2.352.0 E (#2748): + raw (a row the area draws itself: the projects' lists and folder bodies), cls / after (classes of the
// row, what follows the name: count, share mark, menu button), ichtml (the icon's own markup) and fold ({open, attrs}: the
// area keeps the open state itself)
function sbb_treeHtml(nodes, lvl = 0) {
  return nodes.map(n => {
    if (n.raw != null) return n.raw;
    const open = !!n.kids && (n.fold ? !!n.fold.open : n.open && !SBB_SHUT.has(n.k) || sbb_treeOpen(n.k)), sub = open ? n.sub() : [];
    // 2.406.0 A (#3492): the fold arrow sits at the row's end (after the name), a leaf has none (no placeholder); the symbol
    // has the size of a plain sidebar row's (app.css: one row rule for tree rows and .srow)
    const arrow = n.kids ? `<button type="button" class="sbbtar" ${n.fold ? n.fold.attrs : `data-act="sbb-tree" data-k="${esc(n.k)}" data-open="${open ? 1 : ''}"`} aria-expanded="${open}" aria-label="${esc(tr(open ? 'Collapse' : 'Expand') + ': ' + n.name)}">${ic('chev', 's fcar')}</button>` : '';
    const dn = n.ns && !n.auto ? ` data-sbbns="${esc(n.ns)}" data-sbbid="${esc(String(n.id))}" data-sbbpar="${esc(String(n.par ?? ''))}"${n.drop ? ' data-sbbdrop="1"' : ''}${n.menu ? ' data-sbbmenu="1" aria-haspopup="menu"' : ''}${n.drag && !isTouch() ? ' draggable="true"' : n.drag ? ' data-sbbdrag="1"' : ''}` : '';
    return `<div class="fhead sbbt ${open ? '' : 'closed'} ${n.on ? 'on' : ''}${n.auto ? ' sbbauto' : ''}${n.cls ? ' ' + n.cls : ''}" style="--sbbl:${Math.min(lvl, 8)}" ${n.attrs || ''}${dn}><button type="button" class="sbbtn" data-go="${esc(n.go)}"${n.on ? ' aria-current="page"' : ''} ${n.battrs || ''}${n.auto ? ` title="${esc(tr('Automatic group'))}"` : ''}>${n.ichtml ?? ic(n.icon || (n.auto ? 'filter' : 'folder'))}<span class="n">${esc(n.name)}</span></button>${arrow}${n.after || ''}</div>`
      + (!open ? '' : sub === null ? `<div class="sbbtl muted" style="--sbbl:${Math.min(lvl + 1, 8)}">${esc(tr('Loading…'))}</div>` : sbb_treeHtml(sub, lvl + 1));
  }).join('');
}
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-act="sbb-tree"]'); if (!b) return;
  const k = b.dataset.k, x = new Set(LS.get('sbbOpen', []) || []);
  if (b.dataset.open) { x.delete(k); SBB_SHUT.add(k); } else { x.add(k); SBB_SHUT.delete(k); }
  LS.set('sbbOpen', [...x].slice(-300)); an_rowsIn(renderSide);  // 2.573.0 (#4763): opened rows roll in
  $$('#side [data-act="sbb-tree"]').find(x => x.dataset.k === k)?.focus({preventScroll: true});  // 2.199.0 A (#2742): no CSS.escape (jsdom has none)
});
// 2.199.0 A (#2742): moving and sorting in a tree (sbb_treeHtml nodes with ns): the module registers its handlers --
// move(id, into) puts node id into node into, order(id, {before | after: sibling id, into?: the new parent's id}) sorts it,
// menu(id) -> the menu items of the node (Share…, Rename…, New folder…, Move to…, Move to the trash), the tree adds "Move up"
// / "Move down" from the drawn siblings. Mouse: drag onto the middle of a folder = into it, onto its upper / lower edge =
// before / after it; touch: hold, then drag (held without moving: the menu); keyboard: the context key / Shift+F10.
const SBB_TREE = {};
const sbb_treeReg = (ns, h) => { SBB_TREE[ns] = h; };
let SBB_DRAG = null;
const sbb_tnode = el => el?.closest?.('#side .sbbt[data-sbbns]') || null;
const sbb_tsibs = t => $$('#side .sbbt[data-sbbns]').filter(x => x.dataset.sbbns === t.dataset.sbbns && x.dataset.sbbpar === t.dataset.sbbpar);
function sbb_tzone(t, y) {  // 'in' | 'before' | 'after' for a pointer at height y over node t
  const r = t.getBoundingClientRect(), f = r.height ? (y - r.top) / r.height : .5;
  if (t.dataset.sbbdrop) return f < .25 ? 'before' : f > .75 ? 'after' : 'in';
  return f < .5 ? 'before' : 'after';
}
function sbb_tmark(t, z) {
  $$('#side .sbbdin, #side .sbbdbef, #side .sbbdaft').forEach(x => { if (x !== t) x.classList.remove('sbbdin', 'sbbdbef', 'sbbdaft'); });
  if (!t) return;
  t.classList.toggle('sbbdin', z === 'in'); t.classList.toggle('sbbdbef', z === 'before'); t.classList.toggle('sbbdaft', z === 'after');
}
const sbb_tok = (d, t) => !!d && !!t && t.dataset.sbbns === d.ns && t.dataset.sbbid !== d.id;
function sbb_tdrop(d, t, z) {
  const h = SBB_TREE[d.ns]; if (!h || !sbb_tok(d, t)) return;
  if (z === 'in') { if (typeof h.move === 'function') h.move(d.id, t.dataset.sbbid); return; }
  if (typeof h.order === 'function') h.order(d.id, {[z]: t.dataset.sbbid, ...(t.dataset.sbbpar !== d.par ? {into: t.dataset.sbbpar} : {})});
}
function sbb_tmenu(t, anchor) {
  const h = SBB_TREE[t.dataset.sbbns]; if (!h || typeof h.menu !== 'function') return;
  const items = (h.menu(t.dataset.sbbid) || []).filter(Boolean); if (!items.length) return;
  if (t.hasAttribute('draggable') || t.dataset.sbbdrag) {
    const sib = sbb_tsibs(t), i = sib.indexOf(t), id = t.dataset.sbbid;
    const up = i > 0 ? sib[i - 1].dataset.sbbid : null, down = i >= 0 && i < sib.length - 1 ? sib[i + 1].dataset.sbbid : null;
    if (typeof h.order === 'function' && (up || down)) items.push('-', up ? {label: tr('Move up'), icon: 'up', fn: () => h.order(id, {before: up})} : null,
      down ? {label: tr('Move down'), icon: 'down', fn: () => h.order(id, {after: down})} : null);
  }
  menu(anchor || t, items.filter(Boolean), null, null, t.querySelector('.n')?.textContent || '');
}
// capture + stopPropagation: the projects' folder drag (sidebar.js, any #side .fhead[draggable]) never takes a tree node
document.addEventListener('dragstart', e => {
  const t = e.target.closest?.('#side .sbbt[data-sbbns][draggable="true"]'); if (!t) return;
  e.stopPropagation();
  SBB_DRAG = {ns: t.dataset.sbbns, id: t.dataset.sbbid, par: t.dataset.sbbpar};
  e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', t.querySelector('.n')?.textContent || '');
  t.classList.add('dragging');
}, true);
document.addEventListener('dragover', e => {
  if (!SBB_DRAG) return;
  const t = sbb_tnode(e.target); if (!sbb_tok(SBB_DRAG, t)) { sbb_tmark(null); return; }
  e.preventDefault(); e.dataTransfer.dropEffect = 'move'; sbb_tmark(t, sbb_tzone(t, e.clientY));
});
document.addEventListener('drop', e => {
  if (!SBB_DRAG) return;
  const d = SBB_DRAG, t = sbb_tnode(e.target); SBB_DRAG = null; sbb_tmark(null);
  if (!sbb_tok(d, t)) return;
  e.preventDefault(); sbb_tdrop(d, t, sbb_tzone(t, e.clientY));
});
document.addEventListener('dragend', () => { SBB_DRAG = null; sbb_tmark(null); $$('#side .sbbt.dragging').forEach(x => x.classList.remove('dragging')); });
document.addEventListener('contextmenu', e => {
  const t = e.target.closest?.('#side .sbbt[data-sbbmenu]'); if (!t) return;
  e.preventDefault();
  if (e.pointerType === 'touch' || isTouch()) return;  // the long press below opens it (as the project rows, sidebar.js)
  sbb_tmenu(t, e.target.closest('.sbbtn') || t);
});
// touch: hold a node (380 ms) -- let go without moving: its menu; drag on: move / sort like the mouse. 2.627.0 (#4966): by
// drag.js (was an own touch path): the same hold and targets, the panel's edge scrolls, Esc and a second finger cancel. A
// node with a menu only: moving after the hold drags nothing, letting go opens the menu.
const sbb_tfOff = x => { x.t.classList.remove('dragging'); sbb_tmark(null); };
drg_attach(document, {
  mouse: false, onTarget: true, hold: ROWD_HOLD, holdMove: 8, scroll: () => $('#side'), edge: 48, step: 12,
  accept: (x, dx, dy) => x.drag && Math.hypot(dx, dy) >= 1 ? true : null,
  start: el => {
    const t = sbb_tnode(el); if (!t || /** @type {any} */ (el).closest('.sbbtar') || !(t.dataset.sbbmenu || t.dataset.sbbdrag)) return null;
    return {t, drag: !!(t.dataset.sbbdrag || t.hasAttribute('draggable')), d: {ns: t.dataset.sbbns, id: t.dataset.sbbid, par: t.dataset.sbbpar}};
  },
  onHold: x => { x.t.classList.add('dragging'); if (navigator.vibrate) navigator.vibrate(12); },
  onMove: (x, px, py) => { const t = sbb_tnode(document.elementFromPoint(px, py)); x.to = sbb_tok(x.d, t) ? t : null; sbb_tmark(x.to, x.to && sbb_tzone(x.to, py)); },
  onDrop: (x, px, py) => { const t = x.to; sbb_tfOff(x); if (sbb_tok(x.d, t)) sbb_tdrop(x.d, t, sbb_tzone(t, py)); },
  onTap: x => { sbb_tfOff(x); if (x.t.dataset.sbbmenu) sbb_tmenu(x.t); },
  onCancel: sbb_tfOff,
});
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-act="sbb-group"]'); if (!b) return;
  const g = b.dataset.g;
  sbb_foldSet(g, !sbb_folded(g)); renderSide();  // 2.276.0 A (#3039): was the toggle in sbbFold
  $(`#side [data-act="sbb-group"][data-g="${CSS.escape(g)}"]`)?.focus({preventScroll: true});
});
// 2.276.0 A (#3039): the phone's start page folds Money (same choice as the panel)
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-act="ofm-group"]'); if (!b) return;
  sbb_foldSet('office:money', !sbb_folded('office:money'));
  renderSide(); if (b.closest('#view')) renderView();
  $('#view [data-act="ofm-group"]')?.focus({preventScroll: true});
});
// 2.418.0 (#3560): the menus that can be arranged: the editor in place while it is open, else a pen on top (phone) or
// "Customize" as the last row (computer)
function sbb_panelHtml(id) {
  if (!NAV_AREAS.includes(id) || sbb_noPan(id)) return sbb_panelHtml0(id);
  if (NAV.edit === id) return nav_editSlot(id);
  const h = sbb_panelHtml0(id); return h && nav_penHtml(id) + h + nav_editBtn(id);
}
function sbb_panelHtml0(id) {
  const d = sbb_def(id); if (!d) return '';
  const title = '';  // 2.152.3 A (#2619): the area's name sits in the panel's head (sbb_headHtml)
  if (sbb_noPan(id)) return '';  // 2.224.0 A (#2817): no panel on a computer
  if (id === 'cal') return title + sbb_calHtml();
  if (id === 'office') return title + (sbb_ofcLast = sbb_officeHtml());
  // 2.152.3 B (#2619 #2620): sheets.js / wiki.js come with their page (lazyload.js); their load draws the panel (sbb_sync)
  if (id === 'sheets') return title + (typeof shv_panelHtml === 'function' ? (SBB_LAST.sheets = shv_panelHtml()) : (ld_later('sheets'), ''));
  if (id === 'wiki') return title + (typeof wk_panelHtml === 'function' ? (SBB_LAST.wiki = wk_panelHtml()) : (ld_later('wiki'), ''));
  if (id === 'ablage') return title + (typeof ab_panelHtml === 'function' ? (SBB_LAST.ablage = ab_panelHtml()) : (ld_later('ablage'), ''));  // 2.152.3 B (#2621): ablage.js; 2.501.0 (#4198): on demand
  // 2.152.2 (#2618): time, review, home, file store: their parts as entries (hidden ones per part stay hidden, unless open)
  const a = mg_area(id);
  if (a) return title + `<div class="sgroup sbbp">${mg_partsMenu(a).map(p => {
    const after = p[0] === 'time' && S.timer || p[0] === 'pomo' && S.pomo ? '<span class="c"><span class="recdot"></span></span>'
      : p[0] === 'family' ? (n => n ? `<span class="c nunread">${n}</span>` : '')((S.kids || []).reduce((n, k) => n + (k.requests || 0), 0)) : '';
    return sbb_row(p[0], p[1], tr(mg_partName(p[0], p[2])), p[0] === S.route.mod, `data-sbbpart="${p[0]}" data-navk="${id}:${p[0]}"`, after);
  }).join('')}</div>`;
  if (id === 'notes' && sbb_on()) return title + (SBB_LAST.notes = nt_panelHtml());  // 2.602.0 (#4817): the note list (the phone's drawer keeps its entry)
  if (id === 'team') return title + tc_panelHtml();  // 2.479.0 (#2814): channels and direct messages (chat.js)
  // the agents: their overview, then each agent (its page; the status dot as in the sidebar's conversations)
  if (id === 'agents') return title + `<div class="sgroup sbbp">${sbb_row('agents', 'bot', tr('Agents'), S.route.mod === 'agents' && !S.route.agent)}${(S.agents || []).map(x => `<button type="button" class="srow steam sbbi ${S.route.agent === x.id ? 'on' : ''}" data-go="agents/${x.id}"${S.route.agent === x.id ? ' aria-current="page"' : ''}><span class="sdot">${hdot(agentHst(x))}</span><span class="n">${esc(x.name)}</span>${x.waiting || x.chat_unread ? `<span class="c nunread">${x.waiting + x.chat_unread}</span>` : ''}</button>`).join('')}</div>`;
  return title + `<div class="sgroup sbbp">${sbb_row(sbb_target(id), d[1], tr(d[2]), true)}</div>`;
}
// ---- 2.409.0 (#3490): areas on / off per workspace. The module switches ("features") stay the main switch (off = off
// everywhere); below it each person switches areas off per own workspace (setting ws_areas_off, json {ws: [area]}, Settings >
// Modules "Areas per workspace") and an organisation's admins switch areas off for all its members (orgs.areas_off, Settings >
// Workspaces; the server then refuses the area's routes there, accounts/wsareas.py). "All workspaces" shows an area that is
// on in at least one workspace. Nothing is deleted. feat() (core.js) asks wsa_featOff; WSA.raw > 0 = the main switches only
// (Settings > Modules shows and changes those)
const WSA_AREAS = ['office', 'time', 'review', 'life', 'reading', 'ablage', 'wiki', 'sheets'];
const WSA_ORG = WSA_AREAS;  // 2.398.0 (#3406): review is in an organisation's view too (was private only)
const WSA = {raw: 0, cur: null, own: null, ws: null, off: new Set(), ownS: null, ownO: {}};
function wsa_raw(fn) { WSA.raw++; try { return fn(); } finally { WSA.raw--; } }
const wsa_feats = id => mg_area(id) ? mg_feats(id) : [id];  // wiki, sheets: the module itself
const wsa_name = (id, ws) => id === 'life' && ws?.startsWith('org:') ? O3A_LIFE_NAME : mg_area(id)?.[2] || (id === 'wiki' ? N_('Knowledge|area') : N_('Tables'));
const wsa_areaOfMod = mod => mod === 'wiki' || mod === 'sheets' ? mod : mg_areaOf(mod === 'bookmarks' ? 'reading' : mod)?.[0] || null;
function wsa_own() {
  const s = S.settings?.ws_areas_off || '{}';
  if (s !== WSA.ownS) { WSA.ownS = s; try { const o = JSON.parse(s); WSA.ownO = o && typeof o === 'object' && !Array.isArray(o) ? o : {}; } catch { WSA.ownO = {}; } }
  return WSA.ownO;
}
const wsa_adm = ws => ws?.startsWith('org:') ? wsOrg(ws.slice(4))?.areas_off || [] : [];
const wsa_spaces = () => wsOn() ? wsOptions().filter(w => w !== 'all') : ['private'];
// on in workspace ws (below the main switch); 2.398.0 (#3406): review in every workspace (was Private only)
const wsa_wsOn = (ws, id) => !wsa_adm(ws).includes(id) && !(wsa_own()[ws] || []).includes(id);
const wsa_areaOn = (id, ws = wsCur()) => ws === 'all' ? wsa_spaces().some(w => wsa_wsOn(w, id)) : wsa_wsOn(ws, id);
function wsa_featOff(f) {
  if (WSA.raw || !S.settings) return false;
  const cur = wsCur();
  if (cur !== WSA.cur || S.settings.ws_areas_off !== WSA.own || S.me?.workspaces !== WSA.ws || S.settings.ws_mods_off !== WSA.mods || MC.gen !== WSA.mcg) {
    WSA.cur = cur; WSA.own = S.settings.ws_areas_off; WSA.ws = S.me?.workspaces; WSA.mods = S.settings.ws_mods_off; WSA.mcg = MC.gen;
    WSA.off = new Set(WSA_AREAS.filter(id => !wsa_areaOn(id, cur)).flatMap(wsa_feats));  // 2.398.0 (#3406): review like the others
    mc_offIn(cur).forEach(x => WSA.off.add(x));  // 2.575.0 (#3778): outside the card's cap / hidden by me in this workspace
  }
  return WSA.off.has(f);
}
// ---- 2.575.0 (#3778): module cards. An organisation's cards cap the modules of a member there (S.me.workspaces[].mods_cap,
// null = no cap; the server refuses the routes outside it, accounts/modcards.py mc_gate); below the cap and the main switch
// every person hides modules per workspace (setting ws_mods_off, json {ws: [module]}; a private card writes it for Private).
// "All workspaces" shows a module that is on in at least one workspace. Nothing is deleted. Settings > Modules: settings.js mc_*
const MC = {gen: 0, ownS: null, ownO: {}};
const mc_all = () => FEATS.map(x => x[0]);
const mc_capOf = ws => ws?.startsWith('org:') ? wsOrg(ws.slice(4))?.mods_cap ?? null : null;
function mc_own() {
  const s = S.settings?.ws_mods_off || '{}';
  if (s !== MC.ownS) { MC.ownS = s; try { const o = JSON.parse(s); MC.ownO = o && typeof o === 'object' && !Array.isArray(o) ? o : {}; } catch { MC.ownO = {}; } }
  return MC.ownO;
}
const mc_inCap = (ws, f) => { const cap = mc_capOf(ws); return !cap || !mc_all().includes(f) || cap.includes(f); };
const mc_wsOn = (ws, f) => mc_inCap(ws, f) && !(mc_own()[ws] || []).includes(f);
const mc_offIn = cur => mc_all().filter(f => cur === 'all' ? !wsa_spaces().some(w => mc_wsOn(w, f)) : !mc_wsOn(cur, f));
// an area of the main switch that is on (some part) -- what Settings > Modules offers per workspace
const wsa_mainOn = id => wsa_raw(() => mg_area(id) ? mg_on(id) : modOn(id));
// Settings > Modules: one group per workspace with a switch per area (only with organisations: alone, Private = the main switches)
function wsa_modHtml() {
  const sps = wsa_spaces(); if (sps.length < 2 || S.me?.kid) return '';
  const ids = WSA_AREAS.filter(wsa_mainOn); if (!ids.length) return '';
  const grp = ws => {
    const rows = ids.map(id => {  // 2.398.0 (#3406): review in every workspace
      const adm = wsa_adm(ws).includes(id), on = wsa_wsOn(ws, id);
      return `<div class="modrow ${on ? '' : 'off'}" data-wsarow="${id}"><label class="mmain"><span class="swc"><input type="checkbox" data-wsa="${id}" data-wsaws="${ws}" ${on ? 'checked' : ''} ${adm ? 'disabled' : ''}><span class="swt" aria-hidden="true"></span></span><span><b>${esc(tr(wsa_name(id, ws)))}</b>${adm ? `<small class="muted">${esc(tr('Switched off by the admins of {0}', wsName(ws)))}</small>` : ''}</span></label></div>`;
    });
    const n = ids.filter(id => wsa_wsOn(ws, id)).length, t = ids.length;
    return `<details class="modgrp wsagrp" data-wsagrp="${ws}"><summary><span class="mgn">${wsIcon(ws)} ${esc(wsName(ws))}</span><span class="mgc muted">${esc(tr('{0} of {1} on', n, t))}</span>${ic('chev', 's fcar')}</summary><div class="modlist">${rows.join('')}</div></details>`;
  };
  return `<h4 id="s-wsa-h">${tr('Areas per workspace')}</h4><div class="shint">${tr('Switched off here, an area disappears only in that workspace; the switches above apply everywhere. Nothing is deleted.')}</div>${sps.map(grp).join('')}`;
}
document.addEventListener('change', async e => {
  const el = e.target; if (!el?.dataset?.wsa || !el.dataset.wsaws) return;
  e.stopPropagation();
  const id = el.dataset.wsa, ws = el.dataset.wsaws, on = el.checked, o = JSON.parse(JSON.stringify(wsa_own())), xs = new Set(o[ws] || []);
  on ? xs.delete(id) : xs.add(id);
  if (xs.size) o[ws] = WSA_AREAS.filter(x => xs.has(x)); else delete o[ws];
  const n = `${tr(wsa_name(id, ws))} · ${wsName(ws)}`;
  el.closest('[data-wsarow]')?.classList.toggle('off', !on);
  await setApply({ws_areas_off: JSON.stringify(o)}, on ? tr('{0} on', n) : tr('{0} off', n));
  wsa_sync(); render();
}, true);
// the switches follow an undo / another device (settingsSync)
function wsa_sync(md = $$('.smodal').pop()) {
  if (!md) return;
  for (const el of $$('input[data-wsa]', md)) { const on = wsa_wsOn(el.dataset.wsaws, el.dataset.wsa); el.checked = on; el.closest('[data-wsarow]')?.classList.toggle('off', !on); }
  for (const d of $$('[data-wsagrp]', md)) { const ins = $$('input[data-wsa]', d), c = $('.mgc', d); if (c) c.textContent = tr('{0} of {1} on', ins.filter(x => x.checked).length, ins.length); }
}
// Settings > Workspaces: the areas an organisation's members see (its admins decide, every member sees it; box._j = GET /api/orgs)
function wsa_orgPaneDraw(box) {
  if (!box?.isConnected) return;
  const orgs = (box._j || {}).orgs || [];
  for (const det of box.querySelectorAll('details.wsorg[data-oid]')) {
    const o = orgs.find(x => x.id === +det.dataset.oid); if (!o || det.querySelector('.wsa-org') || !Array.isArray(o.areas_off)) continue;
    const adm = o.role === 'admin', ws = 'org:' + o.id;
    const sec = document.createElement('div');
    sec.className = 'wsa-org';
    sec.innerHTML = `<h4>${tr('Areas in this organisation')}</h4><div class="shint keep">${esc(tr('Switched off, an area disappears for every member in this organisation and cannot be opened there; nothing is deleted.') + (adm ? '' : ' ' + tr('Only an admin of the organisation can change this.')))}</div>`
      + `<div class="wsa-orgrows">${WSA_ORG.map(id => `<label class="chkl"><input type="checkbox" data-wsaorg="${id}" ${o.areas_off.includes(id) ? '' : 'checked'} ${adm ? '' : 'disabled'}> ${esc(tr(wsa_name(id, ws)))}</label>`).join('')}</div>`;
    det.appendChild(sec);
    loadModule('navmenu').then(() => nav_orgDraw(sec, o), () => {});  // 2.418.0 (#3560): the menu points of the organisation
    if (!adm) continue;
    sec.addEventListener('change', async e => {
      const cb = e.target.closest('input[data-wsaorg]'); if (!cb) return;
      e.stopPropagation();
      const id = cb.dataset.wsaorg, on = cb.checked;
      const put = v => async () => {
        const off = new Set(o.areas_off); v ? off.delete(id) : off.add(id);
        const j = await api('PATCH', `/api/orgs/${o.id}`, {areas_off: WSA_ORG.filter(x => off.has(x))});
        o.areas_off = j?.areas_off || WSA_ORG.filter(x => off.has(x));
        const w = wsOrg(o.id); if (w) { w.areas_off = o.areas_off; WSA.ws = null; }
        const x = $(`input[data-wsaorg="${id}"]`, sec); if (x) x.checked = v;
        render(); return {};
      };
      try { await put(on)(); } catch { cb.checked = !on; return; }
      const label = `${tr(wsa_name(id, ws))} · ${o.name}`;
      offerUndo(on ? tr('{0} on', label) : tr('{0} off', label), histAdd({label, undo: put(!on), redo: put(on)}));
    });
  }
}
// the router: an old link to an area that is off in the shown workspace (but on in another): a hint with a button to it
function wsa_routeHint(mod) {
  const id = wsa_areaOfMod(mod), cur = wsCur(); if (!id || cur === 'all' || S.me?.kid || modOn(mod) || !wsa_raw(() => modOn(mod))) return;
  const to = wsa_spaces().find(w => w !== cur && wsa_wsOn(w, id)), h = location.hash.slice(1), n = tr(wsa_name(id, to || cur));
  setTimeout(() => to ? toast(tr('{0} is off in this workspace. You find it in the workspace {1}.', n, wsName(to)), async () => { await wsSet(to); go(h); }, 10000, tr('Open'))
    : toast(tr('{0} is off in this workspace.', n), null, 5000), 0);
}
