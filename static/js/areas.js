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
    ['budget', 'wallet', N_('Budget'), () => feat('budget'), () => ['budget']],  // 2.72.0 (#1333): the household budget (budget.js)
    ['feeds', 'news', N_('Feeds'), () => feat('feeds'), () => ['feeds']]]],  // 2.85.0 B (#1162): feeds (feeds.js)
  // 2.48.0 (#1207, #1111): the file store with its parts files (ablage.js) and documents (docs.js)
  ['ablage', 'folder', N_('File store|area'), [['ablage', 'folder', N_('Files'), () => ab_on(), () => ['files']],
    ['docs', 'file', N_('Documents'), () => typeof viewDocs === 'function' && feat('docs'), () => ['docs']]]]];
const MG_IDS = MG_AREAS.map(a => a[0]);
const mg_area = id => MG_AREAS.find(a => a[0] === id) || null;
const mg_areaOf = mod => MG_AREAS.find(a => a[3].some(p => p[0] === mod)) || null;
const mg_parts = a => a ? a[3].filter(p => p[3]()) : [];
const mg_on = id => mg_parts(mg_area(id)).length > 0;
const mg_feats = id => (mg_area(id)?.[3] || []).flatMap(p => p[4]());
// the tab the area opens with: the one last used on this device (LS mgTab), else its first switched-on part
function mg_target(id) {
  const ps = mg_parts(mg_area(id)), last = (LS.get('mgTab', {}) || {})[id];
  return (ps.find(p => p[0] === last) || ps[0] || [id])[0];
}
function mg_seen(mod) {
  const a = mg_areaOf(mod); if (!a) return;
  const o = LS.get('mgTab', {}) || {}; if (o[a[0]] !== mod) { o[a[0]] = mod; LS.set('mgTab', o); }
}
// an old link to a part that is off now opens the area on another tab (null: nothing of the area is on)
function mg_alt(mod) { const a = mg_areaOf(mod); return a && !a[3].find(p => p[0] === mod)[3]() && mg_parts(a).length ? mg_target(a[0]) : null; }
// the header: the area's name above its tabs; with one part on (no tabs) that part's own name stays
const mg_title = mod => { const a = mg_areaOf(mod); return a && mg_parts(a).length > 1 ? tr(a[2]) : ''; };
// the tabs on top of an area's page (only with two parts or more on); the route of a part = data-go
function mg_tabsHtml(mod) {
  const a = mg_areaOf(mod); if (!a || S.me?.kid) return '';
  mg_seen(mod);
  if (a[0] === 'office') return ofm_menuHtml(mod);  // 2.87.9 (#1917): the office menu with its four groups
  const ps = mg_parts(a); if (ps.length < 2) return '';
  return `<div class="seg mgtabs" role="tablist" aria-label="${esc(tr(a[2]))}" data-mgtabs="${a[0]}">${ps.map(([m, i, n]) => `<button type="button" role="tab" data-go="${m}" aria-selected="${m === mod}" class="${m === mod ? 'on' : ''}">${ic(i, 's')}<span>${esc(tr(n))}</span>${m === 'time' && S.timer || m === 'pomo' && S.pomo ? '<span class="recdot"></span>' : ''}</button>`).join('')}</div>`;
}
const mg_wrap = (mod, html) => mg_tabsHtml(mod) + html;
// ---- 2.87.9 (#1917): the office menu. The area Office is four groups (Sell, Money, On the road, Administration) instead of
// two tab rows; a part joins its group with an entry {key, go, icon, name, group, on, adm} (adm = admins of the office only).
// Empty groups and points without rights stay hidden. Computer: the groups side by side on top (sticky); phone: the start
// page office/start with four tiles and the figures, on every other page the path "Office › group" (back to the tiles) and
// the group's points. The old routes stay (#office/offers, #clients, #contacts …); the path on detail pages is text only.
const OFM_GROUPS = [['sell', 'tag', N_('Sell|office')], ['money', 'wallet', N_('Money|office')], ['road', 'car', N_('On the road|office')], ['admin', 'sliders', N_('Administration|office')]];
const ofm_ofc = () => officeOn();
const OFM_ITEMS = [
  {key: 'pipeline', go: 'office/pipeline', icon: 'target', name: N_('Pipeline'), group: 'sell', on: ofm_ofc, adm: 1},
  {key: 'offers', go: 'office/offers', icon: 'receipt', name: N_('Quotes & invoices'), group: 'sell', on: ofm_ofc},
  {key: 'clients', go: 'clients', icon: 'brief', name: N_('Clients'), group: 'sell', on: () => clientsOn()},
  {key: 'contacts', go: 'contacts', icon: 'users', name: N_('Contacts'), group: 'sell', on: () => feat('contacts')},
  {key: 'cashflow', go: 'office/cashflow', icon: 'trend', name: N_('Cash flow'), group: 'money', on: ofm_ofc, adm: 1},
  {key: 'kpi', go: 'office/kpi', icon: 'chart', name: N_('Figures'), group: 'money', on: ofm_ofc, adm: 1},
  {key: 'travel', go: 'office/travel', icon: 'plane', name: N_('Travel expenses'), group: 'road', on: ofm_ofc, adm: 1},
  {key: 'services', go: 'office/services', icon: 'list', name: N_('Services'), group: 'admin', on: ofm_ofc},
  {key: 'equipment', go: 'office/equipment', icon: 'camera', name: N_('Equipment'), group: 'admin', on: ofm_ofc},
  {key: 'contracts', go: 'office/contracts', icon: 'file', name: N_('Framework contracts'), group: 'admin', on: ofm_ofc},
  {key: 'texts', go: 'office/texts', icon: 'note', name: N_('Text blocks'), group: 'admin', on: ofm_ofc},
  {key: 'settings', go: 'office/settings', icon: 'gear', name: N_('Settings'), group: 'admin', on: ofm_ofc}];
// admin of the office shown: from the office's settings once loaded, before that the last answer for this workspace (LS),
// so the contacts / clients pages need not load the office. The server checks every admin route on its own.
const ofm_ws = () => `${S.me?.id || ''}:${typeof wsCur === 'function' ? wsCur() : 'all'}`;  // per person and workspace
const OFM_ASKED = new Set();  // workspaces whose role was read in this session
function ofm_adm() {
  if (typeof OFC !== 'undefined' && OFC.info) return OFC.info.role === 'admin';
  const ws = ofm_ws();
  // the contacts / clients pages without the office loaded: its role once per workspace and session, quietly (a 4xx
  // leaves the menu as it is); the office itself reads it with its settings (ofcInfo)
  if (typeof OFC === 'undefined' && officeOn() && !OFM_ASKED.has(ws)) {
    OFM_ASKED.add(ws);
    rawFetch('GET', '/api/office/settings').then(j => {
      if (!j || ofm_ws() !== ws) return;
      const was = ofm_adm(); ofm_admSeen(j.role === 'admin');
      if (was !== ofm_adm() && mg_areaOf(S.route.mod)?.[0] === 'office') renderView();
    }, () => {});
  }
  return !!(LS.get('ofmAdm', {}) || {})[ws];
}
function ofm_admSeen(adm) { const o = LS.get('ofmAdm', {}) || {}; if (!!o[ofm_ws()] !== adm) { o[ofm_ws()] = adm; LS.set('ofmAdm', o); } }
// a tab of the office (OFC_TABS: [key, icon, name, admins only, html, group]) without an entry here joins its group
// ([5], else Administration) once the office is loaded, so a new office part is never out of reach
const ofm_all = () => typeof OFC_TABS === 'undefined' ? OFM_ITEMS : [...OFM_ITEMS, ...OFC_TABS.filter(t => !OFM_ITEMS.some(i => i.key === t[0]))
  .map(t => ({key: t[0], go: 'office/' + t[0], icon: t[1], name: t[2], group: OFM_GROUPS.some(g => g[0] === t[5]) ? t[5] : 'admin', on: ofm_ofc, adm: t[3]}))];
const ofm_items = () => ofm_all().filter(i => i.on() && (!i.adm || ofm_adm()));
// the point shown: the office's tab (import sits under Settings; no tab = the start page on a phone, quotations on a computer)
function ofm_cur(mod) {
  if (mod !== 'office') return mod;
  const t = S.route.tab === 'import' ? 'settings' : S.route.tab;
  return t === 'start' || ofm_all().some(i => i.key === t && i.go.startsWith('office/')) ? t : isMobile() ? 'start' : 'offers';
}
const ofm_btn = (i, cur, cls) => `<button type="button" class="${cls} ${i.key === cur ? 'on' : ''}" data-go="${i.go}" data-ofm="${i.key}"${i.key === cur ? ' aria-current="page"' : ''}>${ic(i.icon, 's')}<span>${esc(tr(i.name))}</span></button>`;
// the path of a detail page ("Clients › Example Ltd"), grey text, not a navigation
function ofm_detail(mod) {
  let p = null;
  if (mod === 'clients' && S.route.client && S.route.client !== 'mailhub' && typeof CLV !== 'undefined' && CLV.id === S.route.client && CLV.data?.name) p = [tr('Clients'), CLV.data.name];
  else if (mod === 'contacts' && typeof CT !== 'undefined' && CT.sel && CT.card) p = [tr('Contacts'), CT.card.fn || CT.card.org || '?'];
  else if (mod === 'office' && S.route.id && typeof OFD !== 'undefined' && OFD.doc) p = [tr('Quotes & invoices'), OFD.doc.number || tr('Draft')];
  else if (mod === 'office' && S.route.tab === 'travel' && typeof RK !== 'undefined' && RK.open && typeof rk_trip === 'function' && rk_trip(RK.open)) p = [tr('Travel expenses'), rk_trip(RK.open).dest || tr('Trip')];
  return p ? `<nav class="ofmcrumb" aria-label="${esc(tr('Path'))}">${p.map(x => `<span>${esc(x)}</span>`).join('<span aria-hidden="true">›</span>')}</nav>` : '';
}
function ofm_menuHtml(mod) {
  const cur = ofm_cur(mod), its = ofm_items(), crumb = ofm_detail(mod);
  if (its.length < 2) return crumb;
  const grp = g => its.filter(i => i.group === g[0]);
  if (!isMobile()) return `<nav class="ofmenu" aria-label="${esc(tr('Office|area'))}" data-mgtabs="office">${OFM_GROUPS.map(g => grp(g).length ? `<div class="ofmg" data-ofmg="${g[0]}"><span class="ofmgh">${ic(g[1], 's')}<span>${esc(tr(g[2]))}</span></span><div class="ofmgi">${grp(g).map(i => ofm_btn(i, cur, 'ofmi')).join('')}</div></div>` : '').join('')}</nav>${crumb}`;
  if (cur === 'start') return '';  // the tiles are the menu
  const g = OFM_GROUPS.find(x => x[0] === ofm_all().find(i => i.key === cur)?.group); if (!g) return crumb;
  const home = officeOn() ? `<button type="button" class="ofmhome" data-go="office/start">${esc(tr('Office|area'))}</button>` : `<span>${esc(tr('Office|area'))}</span>`;
  return `<nav class="ofmbar" aria-label="${esc(tr('Office|area'))}" data-mgtabs="office"><div class="ofmpath">${home}<span aria-hidden="true">›</span><span>${esc(tr(g[2]))}</span></div>${grp(g).length > 1 ? `<div class="ofmsib">${grp(g).map(i => ofm_btn(i, cur, 'ofmi')).join('')}</div>` : ''}</nav>${crumb}`;
}
// the office start page (office/start, a phone's way in): the figures (admins) and a tile per group with its points
function ofm_startHtml() {
  const its = ofm_items();
  const fig = ofm_adm() && typeof kp_tile === 'function' ? kp_tile(c => `<section class="ofmfig">${c}</section>`) : '';
  return `<div class="ofmstart">${fig}<div class="ofmtiles">${OFM_GROUPS.map(g => { const gi = its.filter(i => i.group === g[0]); return gi.length ? `<section class="ofmtile" data-ofmg="${g[0]}"><h3>${ic(g[1])}<span>${esc(tr(g[2]))}</span></h3><div class="ofmtl">${gi.map(i => ofm_btn(i, '', 'ofmti')).join('')}</div></section>` : ''; }).join('')}</div></div>`;
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
  return `<button class="srow smod ${here ? 'on' : ''}" data-go="${mg_target(id)}" data-mgside="${id}">${ic(a[1])}<span class="n">${esc(tr(a[2]))}</span>${after}</button>`;
}
// [keys, name] for the sidebar editor (one check box per area, for all its parts)
const mg_sideEntry = id => mg_on(id) ? [mg_sideKeys(id).join(','), mg_area(id)[2]] : null;
// ---- the tab bar (phone): one tab per area ("a:<id>"); a tab pinned before 2.44.0 for a part becomes its area's tab
const MG_TAB_OLD = {'m:pomo': 'a:time', time: 'a:time', stats: 'a:review', 'm:family': 'a:life', office: 'a:office'};
const mg_tabIds = ids => ids ? [...new Set(ids.map(x => MG_TAB_OLD[x] || x))] : ids;
function mg_tabItem(id) {
  const a = mg_area(id.slice(2)); if (!a || !mg_on(a[0])) return null;
  return {id, go: mg_target(a[0]), icon: ic(a[1], 'l'), ico: a[1], label: tr(a[2]), mod: a[0], area: a[0]};
}
const mg_tabOpts = opt => MG_IDS.filter(mg_on).map(id => opt('a:' + id, tr(mg_area(id)[2]))).join('');
// ---- Settings > Modules: ONE switch per area; its parts below it (each can still be switched on its own)
const mg_featOn = k => k.startsWith('a:') ? mg_on(k.slice(2)) : feat(k);
const MG_DESC = {office: N_('Office & finance (quotations, services, documents; your own or your organisation\'s), your contacts and the clients'),
  time: N_('Time tracking on tasks with reports, and the focus timer; finished focus sessions can count as time entries'),
  review: N_('Your day and week in review with a private journal, and the statistics'),
  life: N_('Home & life (contracts, devices, staying in touch, health, trips, read later) and family'),
  ablage: N_('Folders and files of your own and of your organisation, shared with people and agents, with versions')};  // 2.48.0 (#1207)
function mg_modAreaHtml(id, partRow) {
  const a = mg_area(id), on = mg_on(id), ks = a[3].flatMap(p => p[4]());
  return `<div class="modrow mgarea ${on ? '' : 'off'}" data-mgrow="${id}"><label class="mmain"><span class="swc"><input type="checkbox" data-mgarea="${id}" ${on ? 'checked' : ''}><span class="swt" aria-hidden="true"></span></span><span><b>${tr(a[2])}</b><small class="muted">${tr(MG_DESC[id])}</small></span></label>
    <details class="mopt mgparts"><summary>${tr('Parts: {0}', a[3].map(p => tr(p[2])).join(', '))}</summary><div class="modlist">${ks.map(partRow).join('')}</div></details></div>`;
}
function mg_setSync(md) {
  for (const el of $$('[data-mgarea]', md)) if (el.matches('input')) el.checked = mg_on(el.dataset.mgarea);
  $$('[data-mgrow]', md).forEach(r => r.classList.toggle('off', !mg_on(r.dataset.mgrow)));
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
const O3A_PRIV = ['life', 'family', 'budget', 'habits', 'review', 'stats', 'notes', 'feeds'];  // 2.85.0 B (#1162): + feeds
const o3a_privOnly = mod => O3A_PRIV.includes(mod);
const o3a_orgView = () => typeof wsCur === 'function' && wsCur().startsWith('org:');
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
