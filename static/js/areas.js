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
  // 2.48.0 (#1207, #1111): the file store with its parts files (ablage.js) and documents (docs.js)
  ['ablage', 'folder', N_('File store|area'), [['ablage', 'folder', N_('Files'), () => ab_on(), () => ['files']],
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
  const ps = mg_partsShown(mg_area(id)), last = (LS.get('mgTab', {}) || {})[id];  // 2.173.0 A (#2680): an organisation's view: its parts only
  if (id === 'office' && !isMobile() && ps.some(p => p[0] === 'office')) return ofm_entry().go;  // 2.161.2 (#2616)
  return (ps.find(p => p[0] === last) || ps[0] || [id])[0];
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
  const ps = mg_partsShown(a); if (ps.length < 2 || sbb_on()) return '';  // 2.152.2 (#2618): a computer: the parts are in the panel of sidebar B
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
// text blocks are no menu points any more but the tab "Templates" under Settings (ofr_setTabsHtml), their routes stay
const OFM_GROUPS = [['sell', 'tag', N_('Sell|office')], ['money', 'wallet', N_('Money|office')], ['admin', 'sliders', N_('Administration|office')]];
const ofm_ofc = () => officeOn();
const OFM_ITEMS = [
  {key: 'pipeline', go: 'office/pipeline', icon: 'target', name: N_('Pipeline'), group: 'sell', on: ofm_ofc, adm: 1},
  {key: 'offers', go: 'office/offers', icon: 'receipt', name: N_('Quotes & invoices'), group: 'sell', on: ofm_ofc},
  {key: 'clients', go: 'clients', icon: 'brief', name: N_('Clients'), group: 'sell', on: () => clientsOn()},
  {key: 'contacts', go: 'contacts', icon: 'users', name: N_('Address book'), group: 'sell', on: () => feat('contacts')},
  {key: 'cashflow', go: 'office/cashflow', icon: 'trend', name: N_('Cash flow'), group: 'money', on: ofm_ofc, adm: 1},
  {key: 'kpi', go: 'office/kpi', icon: 'chart', name: N_('Figures'), group: 'money', on: ofm_ofc, adm: 1},
  {key: 'travel', go: 'office/travel', icon: 'plane', name: N_('Travel expenses'), group: 'money', on: ofm_ofc, adm: 1},
  {key: 'services', go: 'office/services', icon: 'list', name: N_('Services'), group: 'admin', on: ofm_ofc, tpl: 1},
  {key: 'equipment', go: 'office/equipment', icon: 'camera', name: N_('Equipment'), group: 'admin', on: ofm_ofc},
  {key: 'contracts', go: 'office/contracts', icon: 'file', name: N_('Framework contracts'), group: 'sell', on: ofm_ofc},
  {key: 'texts', go: 'office/texts', icon: 'note', name: N_('Text blocks'), group: 'admin', on: ofm_ofc, tpl: 1},
  {key: 'settings', go: 'office/settings', icon: 'gear', name: N_('Settings'), group: 'admin', on: ofm_ofc},
  // 2.152.2 (#2632): the parts of the office's own scripts too (their OFC_TABS entries only bring the tab's content), so the
  // menu / panel shows the same points on #clients, #contacts, #office and #time, before the office is loaded as after
  {key: 'gendocs', go: 'office/gendocs', icon: 'file', name: N_('Documents'), group: 'sell', on: ofm_ofc, adm: 1},
  {key: 'letters', go: 'office/letters', icon: 'mail', name: N_('Correspondence'), group: 'sell', on: ofm_ofc, adm: 1},
  {key: 'bank', go: 'office/bank', icon: 'bank', name: N_('Bank'), group: 'money', on: ofm_ofc, adm: 1},
  {key: 'books', go: 'office/books', icon: 'book', name: N_('Bookkeeping'), group: 'money', on: ofm_ofc, adm: 1},
  {key: 'subs', go: 'office/subs', icon: 'repeat', name: N_('Subscriptions & tools'), group: 'money', on: ofm_ofc, adm: 1},
  {key: 'meals', go: 'office/meals', icon: 'meal', name: N_('Entertainment receipts'), group: 'money', on: ofm_ofc, adm: 1},
  {key: 'cashbook', go: 'office/cashbook', icon: 'wallet', name: N_('Cash book'), group: 'money', on: ofm_ofc, adm: 1},
  {key: 'agreements', go: 'office/agreements', icon: 'shield', name: N_('Contracts & insurance'), group: 'admin', on: ofm_ofc, adm: 1},
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
      const was = ofm_adm() + JSON.stringify(ofm_lv()); ofm_admSeen(j.role === 'admin', j.rights);
      if (was !== ofm_adm() + JSON.stringify(ofm_lv()) && mg_areaOf(S.route.mod)?.[0] === 'office') renderView();
    }, () => {});
  }
  return !!(LS.get('ofmAdm', {}) || {})[ws];
}
function ofm_admSeen(adm, rights) {
  const o = LS.get('ofmAdm', {}) || {}; if (!!o[ofm_ws()] !== adm) { o[ofm_ws()] = adm; LS.set('ofmAdm', o); }
  // 2.187.0 A (#2476): + the levels of a person ruled by office groups (null = as before), so #clients / #contacts show the right menu
  const lv = rights && rights.levels && !rights.legacy && rights.manager !== 'admin' ? rights.levels : null, l = LS.get('ofmLv', {}) || {};
  if (JSON.stringify(l[ofm_ws()] || null) !== JSON.stringify(lv)) { if (lv) l[ofm_ws()] = lv; else delete l[ofm_ws()]; LS.set('ofmLv', l); }
}
// 2.187.0 A (#2476): {area: level} of a person ruled by office groups in the workspace shown (null = not ruled by groups)
function ofm_lv() {
  if (typeof OFC !== 'undefined' && OFC.info) { const r = OFC.info.rights; return r && r.levels && !r.legacy && r.manager !== 'admin' ? r.levels : null; }
  return (LS.get('ofmLv', {}) || {})[ofm_ws()] || null;
}
// a menu point: an office area = its level is not "none" (Settings stays: "My rights" lives there); else as before (adm)
const ofm_ok = i => { const lv = ofm_lv(); return lv && i.key in lv ? i.key === 'settings' || lv[i.key] !== 'none' : !i.adm || ofm_adm(); };
// a tab of the office (OFC_TABS: [key, icon, name, admins only, html, group]) without an entry here joins its group
// ([5], else Administration) once the office is loaded, so a new office part is never out of reach
const ofm_all = () => typeof OFC_TABS === 'undefined' ? OFM_ITEMS : [...OFM_ITEMS, ...OFC_TABS.filter(t => !OFM_ITEMS.some(i => i.key === t[0]))
  .map(t => ({key: t[0], go: 'office/' + t[0], icon: t[1], name: t[2], group: OFM_GROUPS.some(g => g[0] === t[5]) ? t[5] : 'admin', on: ofm_ofc, adm: t[3], need: t[6]}))];  // 2.147.0: [6] = need
// 2.98.0 C (#2180): the order inside the groups (a part not named here keeps its place at the end of its group);
// tpl = a tab under Settings, not in the menu
const OFR_ORDER = ['pipeline', 'offers', 'gendocs', 'clients', 'contacts', 'contracts', 'cashflow', 'kpi', 'bank', 'books', 'subs', 'travel', 'meals', 'equipment', 'agreements', 'settings'];
const ofr_rank = i => { const n = OFR_ORDER.indexOf(i.key); return n < 0 ? OFR_ORDER.length : n; };
// 2.147.0 (#2459): need = a function of the country pack ('books.…'); off in this office = no menu point (office.js ofcFeat)
const ofm_need = i => !i.need || typeof ofcFeat !== 'function' || ofcFeat(i.need);
const ofm_items = () => ofm_all().filter(i => !i.tpl && i.on() && ofm_need(i) && ofm_ok(i)).sort((a, b) => ofr_rank(a) - ofr_rank(b));
// the point shown: the office's tab (import sits under Settings; no tab = the start page on a phone, quotations on a computer)
function ofm_cur(mod) {
  if (mod !== 'office') return mod;
  const t = ['import', 'services', 'texts', 'rights'].includes(S.route.tab) ? 'settings' : S.route.tab;  // 2.98.0 C (#2180): + the templates; 2.187.0 A (#2476): + the rights
  if (mod === S.route.mod && t && t !== 'start') ofm_remember(t);
  return t === 'start' || ofm_all().some(i => i.key === t && i.go.startsWith('office/')) ? t : isMobile() ? 'start' : (ofm_entry().key);
}
// 2.161.2 (#2616): the office opens on the point used last on this device (LS ofmLast); nothing kept, or gone / not allowed: the
// Pipeline for admins (a person without an organisation is the admin of the own office), else Quotes & invoices
function ofm_remember(key) { const o = LS.get('ofmLast', null); if (o !== key) LS.set('ofmLast', key); }
function ofm_entry() {
  const its = ofm_items(), last = LS.get('ofmLast', null);
  return its.find(i => i.key === last) || its.find(i => i.key === (ofm_adm() ? 'pipeline' : 'offers')) || its.find(i => i.key === 'offers') || its[0] || {key: 'offers', go: 'office/offers'};
}
const ofm_btn = (i, cur, cls) => `<button type="button" class="${cls} ${i.key === cur ? 'on' : ''}" data-go="${i.go}" data-ofm="${i.key}"${i.key === cur ? ' aria-current="page"' : ''}>${ic(i.icon, 's')}<span>${esc(tr(i.name))}</span></button>`;
// the path of a detail page ("Clients › Example Ltd"), grey text, not a navigation
function ofm_detail(mod) {
  let p = null;
  if (mod === 'clients' && S.route.client && S.route.client !== 'mailhub' && typeof CLV !== 'undefined' && CLV.id === S.route.client && CLV.data?.name) p = [tr('Clients'), CLV.data.name];
  else if (mod === 'contacts' && typeof CT !== 'undefined' && CT.sel && CT.card) p = [tr('Address book'), CT.card.fn || CT.card.org || '?'];
  else if (mod === 'office' && S.route.id && typeof OFD !== 'undefined' && OFD.doc) p = [tr('Quotes & invoices'), OFD.doc.number || tr('Draft')];
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
  const head = crumb || (it ? `<h2 class="ofpt">${esc(tr(it.name))}</h2>` : '');
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
// the tabs of the office's Settings: General | Templates; Templates = services and text blocks (their routes office/services
// and office/texts lead here, the last one used on this device opens)
function ofr_setTabsHtml(tab) {
  const tpl = tab === 'services' || tab === 'texts', last = LS.get('ofrTpl', 'services') === 'texts' ? 'texts' : 'services';
  if (tpl && last !== tab) LS.set('ofrTpl', tab);
  const b = (go, on, n) => `<button type="button" role="tab" data-go="office/${go}" aria-selected="${on}" class="${on ? 'on' : ''}">${esc(tr(n))}</button>`;
  // 2.187.0 A (#2476): + Rights (office/rights); a person ruled by groups sees the tabs of the areas they reach
  const rt = S.route.tab === 'rights', lv = ofm_lv(), see = k => !lv || (lv[k] || 'none') !== 'none', tp = see('services') || see('texts');
  const gen = see('settings') ? b('settings', !tpl && !rt, 'General') : '', tpb = tp ? b(tpl ? tab : last, tpl, 'Templates') : '';
  return `<div class="ofrset"><div class="seg ofrseg" role="tablist" aria-label="${esc(tr('Settings'))}">${gen}${tpb}${b('rights', rt || !gen && !tpl, N_('Rights|office'))}</div>`
    + (tpl ? `<div class="seg ofrseg2" role="tablist" aria-label="${esc(tr('Templates'))}">${b('services', tab === 'services', 'Services')}${b('texts', tab === 'texts', 'Text blocks')}</div>` : '') + '</div>';
}
// the office start page (office/start, a phone's way in): the figures (admins), then per group a small caps heading and a
// card with one row per point (2.98.0 C, #2180: one column, was a tile per group)
function ofm_startHtml() {
  const its = ofm_items();
  const fig = (ofm_lv() ? ofm_lv().kpi && ofm_lv().kpi !== 'none' : ofm_adm()) && typeof kp_tile === 'function' ? kp_tile(c => `<section class="ofmfig">${c}</section>`) : '';
  const row = i => `<button type="button" class="oflr" data-go="${i.go}" data-ofm="${i.key}">${ic(i.icon)}<span>${esc(tr(i.name))}</span>${ic('chev', 's')}</button>`;
  return `<div class="ofmstart">${fig}<div class="ofl">${OFM_GROUPS.map(g => { const gi = its.filter(i => i.group === g[0]); return gi.length ? `<section class="oflg" data-ofmg="${g[0]}"><h3>${esc(tr(g[2]))}</h3><div class="oflc">${gi.map(row).join('')}</div></section>` : ''; }).join('')}</div></div>`;
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
  return `<button class="srow smod ${here ? 'on' : ''}" data-go="${mg_target(id)}" data-mgside="${id}">${ic(a[1])}<span class="n">${esc(tr(mg_nameKey(a)))}</span>${after}</button>`;
}
// [keys, name] for the sidebar editor (one check box per area, for all its parts)
const mg_sideEntry = id => mg_on(id) ? [mg_sideKeys(id).join(','), mg_area(id)[2]] : null;
// ---- the tab bar (phone): one tab per area ("a:<id>"); a tab pinned before 2.44.0 for a part becomes its area's tab
const MG_TAB_OLD = {'m:pomo': 'a:time', time: 'a:time', stats: 'a:review', 'm:family': 'a:life', office: 'a:office'};
const mg_tabIds = ids => ids ? [...new Set(ids.map(x => MG_TAB_OLD[x] || x))] : ids;
function mg_tabItem(id) {
  const a = mg_area(id.slice(2)); if (!a || !mg_on(a[0])) return null;
  return {id, go: mg_target(a[0]), icon: ic(a[1], 'l'), ico: a[1], label: tr(mg_nameKey(a)), mod: a[0], area: a[0]};
}
const mg_tabOpts = opt => MG_IDS.filter(mg_on).map(id => opt('a:' + id, tr(mg_area(id)[2]))).join('');
// ---- Settings > Modules: ONE switch per area; its parts below it (each can still be switched on its own)
const mg_featOn = k => k.startsWith('a:') ? mg_on(k.slice(2)) : feat(k);
const MG_DESC = {office: N_('Office & finance (quotations, services, documents; your own or your organisation\'s), your contacts and the clients'),
  time: N_('Time tracking on tasks with reports, and the focus timer; finished focus sessions can count as time entries'),
  review: N_('Your day and week in review with a private journal, and the statistics'),
  life: N_('Home & life (contracts, devices, staying in touch, health, trips) and family; trips and staying in touch also in each organisation'),  // 2.173.0 A (#2680)
  reading: N_('Read later, feeds and bookmarks: your own in Private, shared ones in each organisation; never visible to agents'),  // 2.172.0 B (#2679)
  ablage: N_('Folders and files of your own and of your organisation, shared with people and agents, with versions')};  // 2.48.0 (#1207)
function mg_modAreaHtml(id, partRow) {
  const a = mg_area(id), on = mg_on(id), all = mg_allOn(id), ks = a[3].flatMap(p => p[4]());
  return `<div class="modrow mgarea ${on ? '' : 'off'} ${on && !all ? 'part' : ''}" data-mgrow="${id}"><label class="mmain"><span class="swc"><input type="checkbox" data-mgarea="${id}" ${all ? 'checked' : ''}><span class="swt" aria-hidden="true"></span></span><span><b>${tr(a[2])}</b><small class="muted">${tr(MG_DESC[id])}</small></span></label>
    <details class="mopt mgparts"><summary>${tr('Parts: {0}', a[3].map(p => tr(p[2])).join(', '))}</summary><div class="modlist">${ks.map(partRow).join('')}</div></details></div>`;
}
function mg_setSync(md) {
  for (const el of $$('[data-mgarea]', md)) if (el.matches('input')) { const id = el.dataset.mgarea; el.checked = mg_allOn(id); el.indeterminate = !el.checked && mg_on(id); }  // 2.171.0 (#2676)
  $$('[data-mgrow]', md).forEach(r => { const id = r.dataset.mgrow; r.classList.toggle('off', !mg_on(id)); r.classList.toggle('part', mg_on(id) && !mg_allOn(id)); });
}
// the area's switch: all its parts on or off, ONE undo step
async function mg_areaSwitch(md, el) {
  const id = el.dataset.mgarea, on = el.checked, n = tr(mg_area(id)[2]);
  const fs = new Set((S.settings.features ?? FEATS.map(x => x[0]).join(',')).split(',').filter(Boolean));
  for (const k of mg_feats(id)) on ? fs.add(k) : fs.delete(k);
  await setApply({features: FEATS.map(x => x[0]).filter(x => fs.has(x)).join(',')}, on ? tr('{0} on', n) : tr('{0} off', n));
  for (const x of $$('[data-feat]', md)) { x.checked = feat(x.dataset.feat); x.closest('[data-modrow]')?.classList.toggle('off', !x.checked); }
  mg_setSync(md); modCountsSync(md);
  if (id === 'time' && on && !$('#s-trnd', md)) { const cur = LS.get('settingsSec'); md._noflush = true; md.remove(); settingsModal(cur); }  // the time options
}
// ---- 2.83.0 (#1845): an organisation's view shows only what belongs to the organisation. Home (home & life, family,
// budget), habits, review (review & journal, statistics) and notes are private -- hidden in the sidebar, the phone's tab
// bar and the search while an organisation is the shown workspace (Time stays); an old link opens them in Private
// 2.173.0 A (#2680): Home is in an organisation's view too while travel or staying in touch is on -- as "Travel & contacts"
// with only these two (contracts, devices, health, budget and family stay private); its view shows the organisation's own
const O3A_PRIV = ['family', 'budget', 'habits', 'review', 'stats', 'notes'];  // 2.85.0 B (#1162): + feeds; 2.172.0 B (#2677): feeds out (Reading is in every workspace)
const O3A_LIFE_ORG = ['travel', 'care'];
const o3a_lifeOrg = () => O3A_LIFE_ORG.some(m => feat(m));
const o3a_privOnly = mod => O3A_PRIV.includes(mod) || (mod === 'life' && !o3a_lifeOrg());
// 2.172.0 B (#2677 #2679): the space a view of Reading shows -- the shown workspace; under "All workspaces" Private (the view
// offers the other spaces in its own picker, rd_pick), never a mixed view
const rd_space = (own = '') => { const w = typeof wsCur === 'function' ? wsCur() : 'all'; return w !== 'all' ? w : own && wsOptions().includes(own) && own !== 'all' ? own : 'private'; };
const rd_pick = (cur, attr) => typeof wsCur === 'function' && wsCur() === 'all' && wsOn() && wsOptions().length > 2 ? `<select ${attr} aria-label="${esc(tr('Workspace'))}">${wsOptions().filter(w => w !== 'all').map(w => `<option value="${w}" ${w === cur ? 'selected' : ''}>${esc(wsName(w))}</option>`).join('')}</select>` : '';
const o3a_orgView = () => typeof wsCur === 'function' && wsCur().startsWith('org:');
// 2.173.0 A (#2680): the parts of an area shown in the current view (an organisation's: without the private ones) and the
// name of Home there (only travel and staying in touch: not "Home")
const mg_partsShown = a => mg_parts(a).filter(p => !o3a_hid(p[0]));
const O3A_LIFE_NAME = N_('Travel & contacts|area');
const mg_nameKey = a => a && a[0] === 'life' && o3a_orgView() ? O3A_LIFE_NAME : a?.[2];
const mg_partName = (m, n) => m === 'life' && o3a_orgView() ? O3A_LIFE_NAME : n;
const o3a_hid = mod => !!mod && o3a_privOnly(mod) && o3a_orgView();
// a tab bar / "More" item ({mod}) or a sidebar row (its data-go route) hidden in an organisation's view
const o3a_hidT = t => !!t && o3a_hid(t.mod);
const o3a_hidRow = h => { const m = /data-go="(\w+)/.exec(h); return !!m && o3a_hid(m[1]); };
// the router: a private module opened in an organisation's view switches quietly to Private (like wsFollow), then opens it
function o3a_toPrivate(mod) {
  if (!o3a_hid(mod)) return;
  S.settings.workspace = 'private'; LS.set('ws', 'private');
  api('PATCH', '/api/settings', {workspace: 'private'}).catch(() => {});
}
// ---- 2.152.2 (#2622): sidebar B on a computer. Left a narrow bar of the areas (icon, small word below), next to it ONE
// panel with the chosen area's content (#side), the page on the right. A click on an icon changes panel and page together:
// the area opens the page used last there on this device (LS sbbLast, the first time its usual way in), like Slack / Teams.
// The panel always follows the page (the page's area), so both always match. Phones keep the drawer and the tab bar.
// [id, icon, name, on(), routes]; an area of MG_AREAS takes its icon, name and parts from there. Tasks is every other route.
// 2.208.0 (#2771): the area 'tasks' is called Projects (its entries stay tasks), icon proj instead of the tick
const SBB_RAIL = [['tasks', 'proj', N_('Projects')], ['cal', 'cal', N_('Calendar'), () => feat('cal'), ['cal']], ['office'], ['time'], ['review'], ['life'], ['reading'], ['ablage'],
  ['wiki', 'book', N_('Knowledge|area'), () => feat('wiki'), ['wiki']], ['sheets', 'sheet', N_('Tables'), () => feat('sheets'), ['sheets']],
  ['habits', 'habit', N_('Habits'), () => feat('habits'), ['habits']], ['agents', 'bot', N_('Agents'), () => agentsTab(), ['agents']]];
const sbb_def = id => { const r = SBB_RAIL.find(x => x[0] === id); if (!r) return null; const a = mg_area(id); return a ? [id, a[1], mg_nameKey(a), () => mg_on(id), a[3].map(p => p[0])] : r; };  // 2.173.0 A (#2680): mg_nameKey
const sbb_on = () => !isMobile() && !S.me?.kid && !document.documentElement.classList.contains('mini') && !document.documentElement.classList.contains('mini-task') && !!$('#srail');
// 2.196.0 A (#2737): the phone's drawer follows sidebar B: the row of the area icons and ONE panel (sbm_*); children and
// mini windows keep their sidebar. sbb_panelOn = the panel logic runs (computer bar or phone drawer)
const sbm_on = () => isMobile() && !S.me?.kid && !document.documentElement.classList.contains('mini') && !document.documentElement.classList.contains('mini-task');
const sbb_panelOn = () => sbb_on() || sbm_on();
const sbb_areaOfMod = mod => (SBB_RAIL.map(r => sbb_def(r[0])).find(d => d[0] !== 'tasks' && (d[4] || []).includes(mod)) || ['tasks'])[0];
const sbb_area = () => sbb_areaOfMod(S.route.mod);
// the area of a kept hash (the router's first word; old links like client/3 or ev/5 belong to their module)
const SBB_HMOD = {client: 'clients', mailhub: 'clients', ev: 'cal', job: 'agents'};
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
    && (mod !== 'office' || (t => !t || ['import', 'services', 'texts', 'settings'].includes(t) || ofm_items().some(i => i.go === 'office/' + t))(h.split('/')[1]));  // an office point no longer shown (role, pack): not kept
  if (ok) return h;
  return id === 'tasks' ? keyToHash(LS.get('lastKey', START_KEY)) : a ? mg_target(id) : id;
}
// one area's icon (the computer's bar and the phone's row, 2.196.0 A #2737)
function sbb_btnHtml(id, cur, hid, aw) {
  const d = sbb_def(id), on = id === cur;
  if (!sbb_shown(id) || (!on && id !== 'tasks' && (a => a ? mg_sideHidden(id, hid) : hid('e:' + id))(mg_area(id)))) return '';  // Settings > Appearance > Sidebar per part
  const req = id === 'life' && famOn() ? (S.kids || []).reduce((n, k) => n + (k.requests || 0), 0) : 0, n = id === 'agents' ? aw : req;
  const dot = id === 'time' && (S.timer || S.pomo) ? '<span class="srbd recdot"></span>' : n ? `<span class="srbd nunread">${n}</span>` : '';
  return `<button type="button" class="srb ${on ? 'on' : ''}" data-go="${esc(sbb_target(id))}" data-sbb="${id}"${on ? ' aria-current="page"' : ''}>${ic(d[1])}<span class="srbn">${esc(tr(d[2]))}</span>${dot}</button>`;
}
const sbb_aw = () => (S.agents || []).reduce((n, x) => n + x.waiting + x.chat_unread + (x.approvals_open || 0), 0);
function sbb_railHtml(hid) {
  const cur = sbb_area(), aw = sbb_aw();
  const btn = id => sbb_btnHtml(id, cur, hid, aw);
  // 2.152.3 A (#2619): the account moved up into the head bar (sbb_barHtml), at the bottom only Settings; with the panel
  // hidden a small button on top of the bar brings it back
  const show = `<button type="button" class="srb srpanel" data-act="sbb-panel" title="${esc(tr('Show the panel'))}" aria-label="${esc(tr('Show the panel'))}">${ic('panelshow')}</button>`;  // shown by app.css only while the panel is hidden (#app.side-rail)
  return `<div class="srbs">${show}${SBB_RAIL.map(r => btn(r[0])).join('')}</div><div class="srfoot"><button type="button" class="srb sset" data-act="settings" title="${esc(kt(tr('Settings'), 'g s'))}">${ic('gear')}<span class="srbn">${esc(tr('Settings'))}</span>${updDot() ? `<span class="srbd nunread" title="${esc(tr('Update available'))}">●</span>` : ''}</button></div>`;
}
// called by renderSide: the bar (or nothing on a phone); the account node stays the same <img> when nothing changed
function sbb_render(hid) {
  const r = $('#srail'), on = sbb_on(); $('#app')?.classList.toggle('sb-b', on); if (!r) return;
  sbb_bar();  // 2.152.3 A (#2619)
  if (!on) { if (r.innerHTML) r.innerHTML = ''; return; }
  r.setAttribute('aria-label', tr('Areas|nav'));
  r.innerHTML = sbb_railHtml(hid);
  sbb_rove();
}
// ---- 2.196.0 A (#2737): the phone's drawer like sidebar B. On top (fixed) search, Today, Inbox and ONE row of the area icons
// (the bar's icons, order and rights; it scrolls sideways, never wraps), below the chosen area's panel, at the bottom Settings
// and the account. An icon opens the page its area kept and the drawer stays open; the first change in an open drawer adds
// one history entry, the next ones replace it, so one Back closes the drawer (route() closes it on that entry)
const SBM = {keep: false, focus: ''};
// the row is one tab stop of its own (a scrolling region reachable by keyboard; its icons rove with the sidebar)
const sbm_rowHtml = hid => { const cur = sbb_area(), aw = sbb_aw(); return `<div class="sbmr" role="group" tabindex="0" aria-label="${esc(tr('Areas|nav'))}">${SBB_RAIL.map(r => sbb_btnHtml(r[0], cur, hid, aw)).join('')}</div>`; };
// route() asks once whether this route came from the row (the drawer stays open)
const sbm_hold = () => { const k = SBM.keep; SBM.keep = false; return k && !!$('#side.open'); };
function sbm_go(b) {
  const h = b.dataset.go; SBM.focus = b.dataset.sbb;
  if (b.classList.contains('on') || !h) { b.focus({preventScroll: true}); return; }
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
// after renderSide: the row keeps its sideways position, the open area's icon in sight; the tapped icon keeps the focus
function sbm_after(x) {
  const r = $('#side .sbmr'); if (!r) return;
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
  return `<button type="button" class="kbsw" data-act="sbb-ws" aria-haspopup="menu" aria-label="${esc(APP_NAME + ' · ' + tr('Workspace') + ': ' + nm)}" title="${esc(tr('Switch to'))}"${wsp_attr(cur)}><span class="kbbrand">${logoSvg(28)}${wordSvg()}</span><span class="kbfirm">${cur === 'all' ? ic('grid', 's') : wsp_dot(cur)}<span class="wsn">${esc(nm)}</span>${ic('chev', 's')}</span></button>`
    + `<button type="button" class="kbsrch" data-act="palette" title="${esc(tr('Search and commands'))} (${kbText('Mod+K')})" aria-label="${esc(tr('Search and commands'))}">${ic('search', 's')}<span>${esc(tr('Search, create, ask …'))}</span>${kb('Mod+K')}</button>`
    + `<span class="kbend">${bellBtn()}${netDotHtml()}${acct}</span>`;
}
// drawn with the sidebar and with the page's header (the bell's number); only when something changed, the account keeps its <img>
function sbb_bar() {
  const k = $('#kbar'); if (!k) return;
  if (!sbb_on()) { if (k.innerHTML) { k.innerHTML = ''; sbb_barLast = ''; } return; }
  const html = sbb_barHtml(); if (html === sbb_barLast && k.firstChild) return;
  sbb_barLast = html; k.setAttribute('aria-label', APP_NAME);
  const old = $('.kbacct', k);
  keepFocus(k, () => setHtml(k, html));
  const nu = $('.kbacct', k); if (old && nu && old !== nu && old.innerHTML === nu.innerHTML && old.title === nu.title) nu.replaceWith(old);
}
// the workspace menu of the bar: "Switch to", each company with its own sign (picture / symbol / initial), Private (house),
// the shown one ticked; then "Add a company" and, while a company is shown, its settings. The switch itself is wsSet.
function sbb_wsMenu(anchor) {
  const cur = wsOn() ? wsCur() : 'private', all = wsOn() ? wsOptions() : ['private'];
  const opts = [...all.filter(w => w.startsWith('org:')), ...all.filter(w => !w.startsWith('org:'))];  // the companies first (sketch)
  const set = cur.startsWith('org:') && typeof lmOrgPaneOn === 'function' && lmOrgPaneOn();
  const p = menu(anchor, [{head: tr('Switch to')}, ...opts.map(ws => ({label: wsName(ws), icon: ws === 'private' ? 'home' : ws === 'all' ? 'grid' : 'brief', on: ws === cur, cls: 'kbwsi', title: wsName(ws), fn: () => { if (ws !== wsCur()) wsSet(ws); }})),
    '-', {label: tr('Add a company'), icon: 'plus', cls: 'kbws-add', fn: sbb_orgAdd},
    ...(set ? [{label: tr('Company settings'), icon: 'building', cls: 'kbws-set', fn: () => settingsModal('org')}] : [])]);
  // each company's own sign in place of the icon: its picture or symbol, else its initial on a tile
  opts.forEach((ws, i) => {
    if (!ws.startsWith('org:')) return;
    const b = p?.querySelector(`[role="menuitem"][data-i="${i + 1}"]`), o = wsOrg(ws.slice(4)), x = b?.querySelector('svg.i');
    if (x) x.outerHTML = `<span class="kbwsic">${orgIconHtml(o, `<span class="kbini" aria-hidden="true">${esc(String(o?.name || '?').trim().charAt(0).toUpperCase())}</span>`)}</span>`;
  });
}
// "Add a company": an admin of the server creates one (the dialog of Administration); anybody else learns how to get one
async function sbb_orgAdd() {
  if (S.me?.is_admin && typeof orgModal !== 'function') await loadModule('settings').catch(() => {});  // 2.152.3: orgModal lives in the lazy settings module
  if (S.me?.is_admin && typeof orgModal === 'function') { orgModal(null, () => load().then(render).catch(() => {})); return; }
  await askConfirm(tr('Add a company'), tr('A company is set up by the admin of this server. A company’s admin can then invite you by e-mail.'), {ok: tr('OK')});
}
// the panel's head: the area's name, "Fold all" / "Unfold all" (only a panel with groups that fold: Tasks, or a panel whose
// html has sbb_head groups or a tree marked data-sbbfold) and "Hide the panel". pan = the panel's html (not Tasks)
const sbb_foldGroups = pan => pan == null ? $$('#side [data-act="sbb-group"]').map(b => b.dataset.g)
  : [...pan.matchAll(/data-act="sbb-group" data-g="([^"]*)"/g)].map(m => m[1].replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&'));
function sbb_foldOpen(id, pan) {
  if (id === 'tasks') return kbSideAnyOpen();
  const f = LS.get('sbbFold', []) || [];
  return sbb_foldGroups(pan).some(g => !f.includes(g)) || sbb_treeShown(pan);
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
  return `<h2 class="sbbpt">${esc(tr(d ? d[2] : 'Projects'))}</h2><span class="spacer"></span><span class="sbtools">${fold}${id === 'tasks' ? fv2_svToolBtn() /* 2.156.0 D (#2186) */ : ''}${hide}</span>`;
}
function sbb_foldAll() {
  const id = sbb_area(), close = sbb_foldOpen(id);
  if (id === 'tasks') { kbSideSetAll(close); return; }
  const x = new Set(LS.get('sbbFold', []) || []);
  for (const g of sbb_foldGroups()) close ? x.add(g) : x.delete(g);
  LS.set('sbbFold', [...x]);
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
  setTimeout(() => (fold ? $('#side .sbbhide') : $('#srail .srpanel'))?.focus({preventScroll: true}), 0);
}
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-act="sbb-ws"], [data-act="sbb-foldall"], [data-act="sbb-panel"]'); if (!b) return;
  e.preventDefault(); e.stopPropagation();
  const a = b.dataset.act;
  if (a === 'sbb-ws') sbb_wsMenu(b); else if (a === 'sbb-foldall') sbb_foldAll(); else sbb_panel();
}, true);
// with the panel hidden by hand a click on the open area's icon brings it back
document.addEventListener('click', e => {
  const b = e.target.closest?.('#srail .srb.on[data-sbb]'); if (!b || !LS.get('sideFold', false) || !sbb_on()) return;
  e.preventDefault(); e.stopPropagation(); sbb_panel();
}, true);
const sbb_railItems = () => $$('#srail .srb').filter(b => !b.classList.contains('srpanel') || !!$('#app')?.classList.contains('side-rail'));  // 2.152.3 A (#2619)
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
const sbb_folded = g => (LS.get('sbbFold', []) || []).includes(g);
const sbb_head = (g, label, n, on) => `<div class="shead sgh sbbg ${sbb_folded(g) ? 'closed' : ''} ${on ? 'sgon' : ''}"><button class="sgt" data-act="sbb-group" data-g="${esc(g)}" aria-expanded="${!sbb_folded(g)}">${ic('chev', 's fcar')}<span>${esc(label)}</span>${sbb_folded(g) && n ? `<span class="c">${n}</span>` : ''}</button></div>`;
function sbb_officeHtml() {
  const its = ofm_items(), here = sbb_area() === 'office', cur = here ? ofm_cur(S.route.mod) : '';
  return OFM_GROUPS.map(g => {
    const gi = its.filter(i => i.group === g[0]), k = 'office:' + g[0], on = gi.some(i => i.key === cur); if (!gi.length) return '';
    return `<div class="sgroup sbbp" data-ofmg="${g[0]}">${sbb_head(k, tr(g[2]), gi.length, on && sbb_folded(k))}${sbb_folded(k) ? '' : gi.map(i => sbb_row(i.go, i.icon, tr(i.name), i.key === cur, `data-ofm="${i.key}"`)).join('')}</div>`;
  }).join('');
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
// 2.152.3: folders on the path to the open folder are open by themselves; closing one by hand (or Fold all) wins until reload
const SBB_SHUT = new Set();
function sbb_treeCloseAll() {
  // 2.198.0 B (#2764): remember what was open (per area prefix, per device in LS sbbMem) so "Unfold all" brings it back
  const pre = {wiki: 'wk:', ablage: 'ab:'}[sbb_area()], keys = $$('#side [data-act="sbb-tree"][data-open="1"]').map(b => b.dataset.k), o = LS.get('sbbOpen', []) || [];
  if (pre) { const m = LS.get('sbbMem', {}) || {}; m[pre] = [...new Set([...keys, ...o.filter(k => k.startsWith(pre))])].slice(-300); LS.set('sbbMem', m); }
  const rest = pre ? o.filter(k => !k.startsWith(pre)) : [];
  if (o.length !== rest.length) LS.set('sbbOpen', rest);
  keys.forEach(k => SBB_SHUT.add(k));
}
// 2.198.0 B (#2764): restore the remembered state; without one open the first level (the level-0 arrows of the drawn panel)
function sbb_treeOpenAll() {
  const pre = {wiki: 'wk:', ablage: 'ab:'}[sbb_area()], m = LS.get('sbbMem', {}) || {};
  let keys = pre && m[pre] || [];
  if (!keys.length) keys = $$('#side .sbbt[style*="--sbbl:0"] [data-act="sbb-tree"]').map(b => b.dataset.k);
  keys.forEach(k => SBB_SHUT.delete(k));
  LS.set('sbbOpen', [...new Set([...(LS.get('sbbOpen', []) || []), ...keys])].slice(-300));
  if (pre && m[pre]) { delete m[pre]; LS.set('sbbMem', m); }
}
function sbb_treeAnyOpen() {
  const pre = {wiki: 'wk:', ablage: 'ab:'}[sbb_area()];
  return !!pre && (LS.get('sbbOpen', []) || []).some(k => k.startsWith(pre));
}
function sbb_treeHtml(nodes, lvl = 0) {
  return nodes.map(n => {
    const open = !!n.kids && (n.open && !SBB_SHUT.has(n.k) || sbb_treeOpen(n.k)), sub = open ? n.sub() : [];
    const arrow = n.kids ? `<button type="button" class="sbbtar" data-act="sbb-tree" data-k="${esc(n.k)}" data-open="${open ? 1 : ''}" aria-expanded="${open}" aria-label="${esc(tr(open ? 'Collapse' : 'Expand') + ': ' + n.name)}">${ic('chev', 's fcar')}</button>` : '<span class="sbbtar" aria-hidden="true"></span>';
    return `<div class="fhead sbbt ${open ? '' : 'closed'} ${n.on ? 'on' : ''}" style="--sbbl:${Math.min(lvl, 8)}" ${n.attrs || ''}>${arrow}<button type="button" class="sbbtn" data-go="${esc(n.go)}"${n.on ? ' aria-current="page"' : ''} ${n.battrs || ''}>${ic(n.icon || 'folder', 's')}<span class="n">${esc(n.name)}</span></button></div>`
      + (!open ? '' : sub === null ? `<div class="sbbtl muted" style="--sbbl:${Math.min(lvl + 1, 8)}">${esc(tr('Loading…'))}</div>` : sbb_treeHtml(sub, lvl + 1));
  }).join('');
}
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-act="sbb-tree"]'); if (!b) return;
  const k = b.dataset.k, x = new Set(LS.get('sbbOpen', []) || []);
  if (b.dataset.open) { x.delete(k); SBB_SHUT.add(k); } else { x.add(k); SBB_SHUT.delete(k); }
  LS.set('sbbOpen', [...x].slice(-300)); renderSide();
  $(`#side [data-act="sbb-tree"][data-k="${CSS.escape(k)}"]`)?.focus({preventScroll: true});
});
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-act="sbb-group"]'); if (!b) return;
  const g = b.dataset.g, x = new Set(LS.get('sbbFold', []) || []);
  x.has(g) ? x.delete(g) : x.add(g); LS.set('sbbFold', [...x]); renderSide();
  $(`#side [data-act="sbb-group"][data-g="${CSS.escape(g)}"]`)?.focus({preventScroll: true});
});
function sbb_panelHtml(id) {
  const d = sbb_def(id); if (!d) return '';
  const title = '';  // 2.152.3 A (#2619): the area's name sits in the panel's head (sbb_headHtml)
  if (id === 'cal') return title + sbb_calHtml();
  if (id === 'office') return title + (sbb_ofcLast = sbb_officeHtml());
  // 2.152.3 B (#2619 #2620): sheets.js / wiki.js come with their page (lazyload.js); their load draws the panel (sbb_sync)
  if (id === 'sheets') return title + (typeof shv_panelHtml === 'function' ? (SBB_LAST.sheets = shv_panelHtml()) : (ld_later('sheets'), ''));
  if (id === 'wiki') return title + (typeof wk_panelHtml === 'function' ? (SBB_LAST.wiki = wk_panelHtml()) : (ld_later('wiki'), ''));
  if (id === 'ablage') return title + (SBB_LAST.ablage = ab_panelHtml());  // 2.152.3 B (#2621): ablage.js
  // 2.152.2 (#2618): time, review, home, file store: their parts as entries (hidden ones per part stay hidden, unless open)
  const a = mg_area(id);
  if (a) return title + `<div class="sgroup sbbp">${mg_partsShown(a).filter(p => p[0] === S.route.mod || !sideHidden('e:' + p[0])).map(p => {
    const after = p[0] === 'time' && S.timer || p[0] === 'pomo' && S.pomo ? '<span class="c"><span class="recdot"></span></span>'
      : p[0] === 'family' ? (n => n ? `<span class="c nunread">${n}</span>` : '')((S.kids || []).reduce((n, k) => n + (k.requests || 0), 0)) : '';
    return sbb_row(p[0], p[1], tr(mg_partName(p[0], p[2])), p[0] === S.route.mod, `data-sbbpart="${p[0]}"`, after);
  }).join('')}</div>`;
  // the agents: their overview, then each agent (its page; the status dot as in the sidebar's conversations)
  if (id === 'agents') return title + `<div class="sgroup sbbp">${sbb_row('agents', 'bot', tr('Agents'), S.route.mod === 'agents' && !S.route.agent)}${(S.agents || []).map(x => `<button type="button" class="srow steam sbbi ${S.route.agent === x.id ? 'on' : ''}" data-go="agents/${x.id}"${S.route.agent === x.id ? ' aria-current="page"' : ''}><span class="sdot">${hdot(agentHst(x))}</span><span class="n">${esc(x.name)}</span>${x.waiting || x.chat_unread ? `<span class="c nunread">${x.waiting + x.chat_unread}</span>` : ''}</button>`).join('')}</div>`;
  return title + `<div class="sgroup sbbp">${sbb_row(sbb_target(id), d[1], tr(d[2]), true)}</div>`;
}
