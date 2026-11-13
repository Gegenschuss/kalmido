/* Kalmido web client: Rendering: the shell (sidebar, header, tabs) and task rows.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ------------------------------------------------------------------ render: shell
function render() { if (typeof bootDone !== 'function') return; return td_rcRun(render0); }  // 2.40.0 (#1430): one lookup cache per render (td_rc); 2.312.0 A (#3285): not before main.js ran (slow load: a late script still missing)
function render0() {
  if (td_rsT) { clearTimeout(td_rsT); td_rsT = 0; }  // 2.40.0 (#1430): a bundled live render that waits is done by this one
  _kidsIx = null;  // 2.17.0 (#649): one children index per render, built after any change made before it
  const sk = $('#skip'); if (sk && sk.textContent !== tr('Skip to content')) sk.textContent = tr('Skip to content');  // 2.13.0 (#453 A9)
  document.body.classList.toggle('in-chat', chatFull() && S.route.mod === 'agents' && !!S.route.agent);  // 2.13.0 (#453 P11)
  document.body.classList.toggle('in-team', S.route.mod === 'team');  // 2.17.0 (#419): the conversation fills the view, only its messages scroll
  document.body.classList.toggle('kidmode', !!S.me?.kid);  // 2.19.0 (#653): a kid's simple view (no sidebar, tab bar, + button)
  for (const k of ['soft', 'strong']) document.body.classList.toggle('prbg-' + k, S.settings?.prio_bg === k);  // 2.40.0 (#1416)
  lp_sync();  // 2.53.0 (#1426): the open list's colour as the accent of the list view (listcolor.js)
  wsc_sync();  // 2.53.0 (#1474): its workspace's colour as the header stripe and the frame of the input fields (wscolor.js)
  sideSearchSync(); badgeSync();
  if (S.shop) shopDraw();  // 2.19.0: shopping mode follows every reload (the app's own poll included); lazy-ok: only shopModeOpen (family.js) sets S.shop
  fitLayout(true); renderSide(); annSync(); ntfAskSync(); if (typeof le2u_barSync === 'function') le2u_barSync(); renderTop(); renderView(); renderTabs(); quotaNudge(); sup_barSync();  // 2.64.1 (#1817): le2u = the bar of a locked list; 2.74.0 (#338): + the yearly supporter hint
  $('#fab').innerHTML = ic('plus'); $('#fab').setAttribute('aria-label', tr('New task')); $('#fab').title = kt(tr('New task'), 'n');
  fabSync();
  o3c_sync();  // 2.83.0 C (#1427): the header strip of a list / folder (listhead.js)
  if (S.sel && S.tasks.has(S.sel) && !$('#detail').contains(document.activeElement)) renderDetail();
  if (S.sel && !S.tasks.has(S.sel) && !(S.extra || []).some(t => t.id === S.sel) && !lzSel(S.sel)) closeDetail();  // 2.369.2 (#3136): lzSel = its list is on the way
  agentLive();
}
// ---- 2.24.0 (#907): the server's notice (maintenance / announcement) as a slim bar above the header. Hidden per device until
// the notice changes (its id); a notice that starts later is not shown yet.
function annSync() {
  const a = S.announce, main = $('#main'); if (!main) return;
  let bar = $('#annbar');
  const on = !!a && a.active !== false && !(LS.get('annHidden', '') === a.id) && !S.me?.kid;
  if (!on) { if (bar) barKeep(() => bar.remove()); return; }  // 2.940.0 (#5226): barKeep
  const until = a.ends_at ? tr('until {0}', ((d) => `${WD[d.getDay()]} ${fmtTimeAt(d)}`)(new Date(a.ends_at))) : '';
  const html = `${ic(a.level === 'maintenance' ? 'alert' : 'bell', 's')}<span class="annt"><b>${esc(a.level === 'maintenance' ? tr('Maintenance') : tr('Notice'))}:</b> ${esc(a.text)}${until ? ` <span class="muted">· ${esc(until)}</span>` : ''}</span><button type="button" class="iconbtn" data-act="ann-hide" aria-label="${esc(tr('Hide this notice'))}" title="${esc(tr('Hide this notice'))}">${ic('x', 's')}</button>`;
  const cls = 'annbar ' + (a.level === 'maintenance' ? 'maint' : '');
  if (!bar || bar.innerHTML !== html || bar.className !== cls) barKeep(() => { if (!bar) { bar = document.createElement('div'); bar.id = 'annbar'; bar.setAttribute('role', 'status'); main.prepend(bar); } bar.className = cls; bar.innerHTML = html; });  // its class too: the padding counts
}
// ---- 2.940.0 (#5226): a bar above the view (notice, notifications question, encrypted list, supporter hint) that comes,
// goes or changes its height on its own does not move what is read: #view.scrollTop takes the difference (rule 08.11.2026
// "a calm view without jumps"). Not while the app loads and not on a change of the view (that view starts anew anyway).
// #view is the scrolling box on the phone too (html, body overflow hidden). Hiding a bar by hand goes through here as well:
// the content stays where it is, at the very top it moves up.
function barKeep(fn) {
  const v = $('#view');
  if (!v || !S.booted || FL.vsig !== fl_sig() || !v.isConnected) return fn();
  const t0 = v.getBoundingClientRect().top;
  try { return fn(); } finally { const d = v.getBoundingClientRect().top - t0; if (Math.abs(d) >= 0.5) v.scrollTop += d; }  // sprung-ok: the height of a bar that came / went on its own (#5226)
}
document.addEventListener('click', e => { if (e.target.closest?.('[data-act="ann-hide"]') && S.announce) { LS.set('annHidden', S.announce.id); annSync(); } });
// ---- 2.24.0 (#910): storage. From 80 % (and again from 95 %) a one-time hint per level and day; full: the dialog with
// "Contact support" (also when an upload is refused).
function quotaNudge() {
  const q = S.storage; if (!q || !q.limit || q.level === 'ok' || !S.booted) return;
  const k = q.level + ':' + today(); if (LS.get('quotaSeen', '') === k) return;
  LS.set('quotaSeen', k);
  if (q.level === 'full') { setTimeout(() => quotaDialog(q), 600); return; }
  setTimeout(() => toast(tr('Your storage is {0} % full ({1} of {2}).', Math.floor(q.pct), fmtSize(q.used), fmtSize(q.limit)), () => settingsModal('account'), 8000, tr('Details')), 800);
}
function quotaMail(q) {
  const sub = tr('{0}: more storage', APP_NAME), body = [tr('Hello,'), '', tr('my storage at {0} is full. Could I get more space?', location.host), '',
    tr('Account: {0}', `${S.me?.display_name || ''} (${S.me?.username || ''})`), tr('Used: {0} of {1}', fmtSize(q.used || 0), fmtSize(q.limit || 0)) + (q.pool === 'org' ? ' · ' + tr('shared by the organisation') : ''), tr('Server: {0}', location.host)].join('\n');
  return `mailto:${encodeURIComponent(q.support || '')}?subject=${encodeURIComponent(sub)}&body=${encodeURIComponent(body)}`;
}
async function quotaDialog(j) {
  const q = {...(S.storage || {}), ...(j || {})};
  const html = `<p>${esc(tr('Your storage is full: {0} of {1}. New files cannot be uploaded until there is space again. Nothing has been deleted.', fmtSize(q.used || 0), fmtSize(q.limit || 0)))}</p>
    <p class="muted">${esc(tr('Delete files you no longer need (attachments in tasks, comments and projects) or ask for more space.'))}</p>`;
  const ok = await askDialog({title: tr('Storage full'), html, ok: tr('Contact support'), cancel: tr('Close')});
  if (ok) { if (q.support) location.href = quotaMail(q); else toast(tr('No support address is set on this server.')); }
}
// 2.13.3: the + button follows rotations / folding too (not only a full render): hidden where the add bar or the header's
// "New task" is there (tablets, an unfolded Fold in portrait)
function fabSync() { const f = $('#fab'); if (f) f.classList.toggle('gone', fabOff() || S.multi.size > 0 || (!!$('#view .qdock') && (tabletDock() || !isMobile())));
  if (f) { const ev = typeof calFabEv === 'function' && calFabEv(), l = ev ? tr('New event') : tr('New task'); if (f.getAttribute('aria-label') !== l) { f.setAttribute('aria-label', l); f.title = ev ? l : kt(l, 'n'); } } }  // 2.855.0 (#5462): in a phone's calendar the + adds an event
window.addEventListener('resize', () => { if (S.booted) requestAnimationFrame(fabSync); });
// 2.44.0 (#1187): the focus timer and family are tabs of their areas (Time, Home) now: areas.js, tab ids "a:<area>"
// 2.208.0 (#2771): the module tasks shows as the area Projects (tab bar, Add tab)
const MODS = [['tasks', 'proj', N_('Projects')], ['cal', 'cal', N_('Calendar')], ['matrix', 'grid', N_('Matrix')], ['habits', 'habit', N_('Habits')]];
// tab bar / rail order is a server setting (same on every device), editable in the settings
function navOrder() {
  const keys = MODS.map(m => m[0]);
  const o = (S.settings.nav_order || '').split(',').filter(k => keys.includes(k));
  return [...new Set([...o, ...keys])];
}
const mods = () => navOrder().map(k => MODS.find(m => m[0] === k)).filter(([m]) => m === 'tasks' || feat(m));
function modHash(m) { return m === 'tasks' ? keyToHash(LS.get('lastKey', START_KEY)) : m; }
// ---- tab bar / rail per device (LS 'tabbar'): pinned modules, smart lists, lists, filters, tags,
// search, settings. null = default = the modules in the server-wide order (settings "Module").
const TAB_MAX = 5;  // phone: more than this -> first TAB_MAX-1 + "Mehr"
// 2.477.0 (#3938): the number of tabs follows the width: below 600 CSS px TAB_MAX, from 600 px 7, from 900 px 9 (the last one
// is "More" when something is left); turning the device draws the bar again
const TAB_MQ = typeof matchMedia === 'function' ? [matchMedia('(min-width: 900px)'), matchMedia('(min-width: 600px)')] : [];
const tabMax = () => TAB_MQ[0]?.matches ? 9 : TAB_MQ[1]?.matches ? 7 : TAB_MAX;
TAB_MQ.forEach(q => q.addEventListener?.('change', () => { if ($('#tabs')) renderTabs(); }));
const SMART_TABS = ['inbox', 'today', 'tomorrow', 'week', 'doable', 'pinned', 'waiting', 'mine_wait', 'stale', 'assigned', 'byme', 'all', 'done', 'trash'];
const leadEmoji = n => (String(n ?? '').match(/^((?:\p{Extended_Pictographic}|\p{Emoji_Modifier}|\uFE0F|\u200D)+)/u) || [])[1];
// 2.24.0 (UX-36): the default bar is what one hand needs every day: Inbox, Today, Search and the lists (the drawer); modules
// come in only when someone pins them (Settings > Appearance > Tab bar, or "Customize tab bar" under "More")
const tabDefault = () => ['s:inbox', 's:today', 'search', 'lists'];
// 2.418.0 (#3560): the order of the person (setting nav_menus "tabbar", the same on every phone); before the first change
// there the device's own (LS tabbar)
const tabIds = () => { const o = nav_pref('tabbar').order; return mg_tabIds(o.length ? o.filter(x => x !== 'none') : LS.get('tabbar', null)) || tabDefault(); };  // 2.44.0 (#1187): old module tabs -> their area
// 2.883.0 (#5560): every item carries the name of its icon (ico) - "More" shows the real icon, never the three dots
function tabItem(id) {
  const [kind, ...rest] = id.split(':'), v = rest.join(':');
  if (kind === 'a') return mg_tabItem(id);  // 2.44.0 (#1187)
  if (kind === 'm') {
    const md = MODS.find(x => x[0] === v);
    if (!md || (v !== 'tasks' && !feat(v))) return null;
    return {id, go: modHash(v), icon: ic(md[1], 'l'), ico: md[1], label: tr(md[2]), mod: v};
  }
  if (kind === 's' && v === 'assigned' && !collab()) return null;
  if (kind === 's' && SMART[v]) return {id, go: v, icon: ic(SMART[v].icon, 'l'), ico: SMART[v].icon, label: v === 'week' ? tr('7 days') : tr(SMART[v].name), key: v};
  if (kind === 'l') {
    const l = listById(+v); if (!l || l.is_inbox) return null;
    const em = leadEmoji(l.name), name = sbiMode() !== 'emoji' ? lname(l) : em ? l.name.slice(em.length).trim() : l.name;
    return {id, go: 'l/' + v, icon: `<span class="temoji">${listIconHtml(l, {emoji: true})}</span>`, label: name, key: 'l:' + v, lic: l};  // 2.38.0 (#1174); 2.883.0 (#5560): lic = the list's own icon in "More"
  }
  if (kind === 'f') { const f = S.filters.find(x => x.id === +v); return f ? {id, go: 'f/' + v, icon: ic('filter', 'l'), ico: 'filter', label: f.name, key: 'f:' + v} : null; }
  if (kind === 'tag' && v) return {id, go: 'tag/' + encodeURIComponent(v), icon: ic('tag', 'l'), ico: 'tag', label: v, key: 'tag:' + v};
  if (kind === 'folder' && v) return {id, go: 'folder/' + encodeURIComponent(v), icon: ic('folder', 'l'), ico: 'folder', label: fName(v), key: 'folder:' + v};
  if (id === 'news') return collab() ? {id, go: 'news', icon: ic('bell', 'l'), ico: 'bell', label: tr('News'), mod: 'news'} : null;
  if (id === 'agents') return agentsTab() ? {id, go: 'agents', icon: ic('bot', 'l'), ico: 'bot', label: tr('Agents'), mod: 'agents'} : null;
  if (id === 'stats') return feat('stats') ? {id, go: 'stats', icon: ic('chart', 'l'), ico: 'chart', label: tr('Statistics'), mod: 'stats'} : null;
  if (id === 'time') return timeOn() ? {id, go: 'time', icon: ic('clock', 'l'), ico: 'clock', label: tr('Time tracking'), mod: 'time'} : null;  // 2.7.0 (#405 S5): one name
  if (id === 'overview') return overviewOn() ? {id, go: 'overview', icon: ic('pulse', 'l'), ico: 'pulse', label: tr('Project status'), mod: 'overview'} : null;
  if (id === 'team') return teamOn() ? {id, go: 'team', icon: ic('comment', 'l'), ico: 'comment', label: tr('Team chat'), mod: 'team', n: S.team?.unread || 0} : null;  // 2.17.0 (#419)
  if (id === 'office') return officeOn() ? {id, go: 'office', icon: ic('receipt', 'l'), ico: 'receipt', label: tr('Office & finance'), mod: 'office'} : null;  // 2.36.2 (#1146): in "More" like the other modules
  if (id === 'wiki') return feat('wiki') ? {id, go: 'wiki', icon: ic('book', 'l'), ico: 'book', label: tr('Knowledge pages'), mod: 'wiki'} : null;  // 2.49.0 (#1199)
  if (id === 'sheets') return feat('sheets') ? {id, go: 'sheets', icon: ic('sheet', 'l'), ico: 'sheet', label: tr('Tables'), mod: 'sheets'} : null;  // 2.89.0 (#1916)
  if (id === 'qnotes') { const l = qn_list(); return l && !S.me?.kid ? {id, go: 'notes/' + l.id, icon: ic('edit', 'l'), ico: 'edit', label: lname(l), mod: 'notes'} : null; }  // 2.477.0 (#3881): the list Notes
  if (id === 'favs') return {id, go: 'favorites', icon: ic('star', 'l'), ico: 'star', label: tr('Favourites'), key: 'favorites'};  // 2.441.0 (#3592)
  if (id === 'home') return {id, go: 'home', icon: ic('start', 'l'), ico: 'start',  /* 2.364.0 B (#3031) */ label: tr('Start|home'), mod: 'home'};  // 2.17.0 (#475)
  if (id === 'search') return {id, act: 'palette', icon: ic('search', 'l'), ico: 'search', label: tr('Search'), key: 'search'};  // 2.31.0 (#1057): opens the search at once (with the keyboard)
  if (id === 'lists') return {id, go: sbb_target('tasks'), icon: ic('list', 'l'), ico: 'list', label: tr('Projects'), mod: 'tasks', area: 'tasks'};  // 2.417.0 A (#3559): the page kept in Projects, like the other areas (was: the drawer)
  if (id === 'settings') return {id, act: 'settings', icon: ic('gear', 'l'), ico: 'gear', label: tr('Settings'), upd: updDot()};
  return null;
}
const tabItems = () => tabIds().map(tabItem).filter(t => t && !o3a_hidT(t));  // 2.83.0 (#1845): private modules not in an organisation's view
// which pinned item is "on": exact key match first, else the module (Aufgaben = any task view)
function tabOn(items) {
  const r = S.route, exact = items.find(t => t.key && r.mod === 'tasks' && t.key === r.key);
  if (exact) return exact.id;
  const m = items.find(t => t.mod && (t.mod === r.mod || (t.area && mg_areaOf(r.mod)?.[0] === t.area)) && !(r.mod === 'tasks' && r.key === 'search'));
  return m ? m.id : null;
}
// 1.5.3: the "g …" shortcuts in the tooltips of what they open
const GO_KEY = {team: 'g n', today: 'g t', tomorrow: 'g m', week: 'g w', doable: 'g d', inbox: 'g i', all: 'g a', cal: 'g c', habits: 'g h', pomo: 'g f', settings: 'g s'};
function tabBtn(t, on, cls = '') {
  const tgt = t.go != null ? `data-go="${esc(t.go)}"` : `data-act="${t.act}"`;
  const nb = t.id === 'news' && bellCount() ? `<span class="nbadge">${bellCount() > 99 ? '99+' : bellCount()}</span>` : t.id === 'team' && t.n ? `<span class="nbadge">${t.n > 99 ? '99+' : t.n}</span>` : '';
  return `<button class="${cls} ${on ? 'on' : ''}" ${tgt} title="${esc(GO_KEY[t.mod || t.key || t.id] ? kt(t.label, GO_KEY[t.mod || t.key || t.id]) : t.label)}"><span class="tico">${t.icon}</span><span>${esc(t.label)}</span>${t.mod === 'pomo' && S.pomo ? '<span class="dot"></span>' : ''}${t.mod === 'time' && S.timer ? '<span class="dot rec"></span>' : ''}${t.upd ? `<span class="dot" title="${esc(tr('Update available'))}"></span>` : ''}${nb}</button>`;
}
// 2.8.0 (#434): no icon rail any more. The desktop has one sidebar with grouped text navigation (renderSide) and the
// command bar in the header; the tab bar setting is for phones only.
// what "Mehr" offers: overflow tabs + enabled modules that are not pinned + search/settings if not pinned
// 2.364.0 B (#3040): "More" = the drawer's list of areas, the same entries in the same order (sbb_btnHtml decides: switched on,
// not hidden in the sidebar settings, not private in an organisation's view; pinned ones too), then the conversations not
// pinned, Search and Settings last. Overflowing pinned tabs stay on top. rest = those, for the groups of tabsMore
const tabAreaItems = () => { const cur = sbb_area(); return sbb_ids().filter(id => sbb_btnHtml(id, cur, sideHidden, 0)).map(id => { const d = sbb_def(id), a = !!mg_area(id); return {id: a ? 'a:' + id : id, go: sbb_target(id), icon: ic(d[1], 'l'), ico: d[1], label: tr(d[2]), mod: id, rail: 1, ...(a ? {area: id} : {})}; }); };  // 2.479.0 (#2814): rail = an area (Chat is one now)
function tabOverflow() {
  const items = tabItems(), mx = tabMax(), shown = items.length > mx ? items.slice(0, mx - 1) : items;  // 2.477.0 (#3938)
  const areas = tabAreaItems(), over = items.slice(shown.length), pinned = k => items.some(t => t.id === k);
  // 2.883.0 (#5560): an overflowing pinned tab whose place is also an area (Calendar, Reading) stands once, in the group Areas
  const rest = over.filter(t => !areas.some(a => a.id === t.id || (t.mod && a.mod === t.mod)));  // by place, not by go: a list tab can be Projects' kept page
  const conv = ['team', 'news'].filter(k => !pinned(k) && !areas.some(t => t.id === k) /* 2.479.0 (#2814): the team chat is an area */).map(tabItem).filter(t => t && !o3a_hidT(t));
  const end = ['search', 'settings'].filter(k => !pinned(k)).map(tabItem).filter(Boolean);
  // search + settings are also in the side menu: they alone do not justify a "Mehr" tab
  return {shown, rest, more: over.length || areas.some(t => !pinned(t.id)) ? [...rest, ...areas, ...conv, ...end] : []};
}
function renderTabs() {
  const {shown, more} = tabOverflow(), all = tabItems(), on = tabOn(all);
  // highlight "Mehr" when the current view is only reachable through it (overflow tab, unpinned module, search)
  const moreOn = more.length > 0 && !(S.viaDrawer && '#' + S.viaDrawer === location.hash) && (on ? !shown.some(t => t.id === on) : (S.route.mod !== 'tasks' && S.route.mod !== 'news') || S.route.key === 'search');
  // 2.31.0 (#1057): with "Search" in the tab bar the phone has ONE search: no magnifier in the header, no search field in the
  // drawer and no search button next to it (CSS body.tab-search); without the tab they stay, so search is always reachable
  document.body.classList.toggle('tab-search', shown.some(t => t.id === 'search'));
  // 2.417.0 A (#3559): the tab of the area open now leads to the area's start page (tapping it again)
  $('#tabs').innerHTML = shown.map(t => tabBtn(t.area && t.area === sbb_area() ? {...t, go: sbb_home(t.area)} : t, t.id === on)).join('') +
    (more.length ? `<button class="${moreOn ? 'on' : ''}" data-act="tabs-more"><span class="tico">${ic('dots', 'l')}</span><span>${tr('More')}</span></button>` : '');
  an_tabs();  // 2.46.1 (#1560): the underline of the tab that became active slides in
}
const sideOpenDrawer = () => { S.sideToLists = true; $('#top [data-act="side"]')?.click(); };  // 2.24.0 (UX-36): "Lists" in "More"; 2.417.0 A (#3559): the tab opens the page now, this stays for the drawer at Lists
// 2.31.0 (#1057, audit N5): the drawer opened by the tab "Lists" starts at the group Lists (Plan and Views stay above it)
function sideToLists() {
  const sd = $('#side'), g = $('#side .sg-lists'); if (!sd || !g) return;
  if (typeof sbm_on === 'function' && sbm_on()) { sd.scrollTop = 0; return; }  // 2.353.0 B (#2776): the phone's drawer has a fixed top: start at the head of the project list
  sd.scrollTop = Math.max(0, sd.scrollTop + g.getBoundingClientRect().top - sd.getBoundingClientRect().top - 8);
}
function tabsMore(anchor) {
  const {more, rest} = tabOverflow();
  // 2.23.0 (#824): who is working, on top of the "More" menu (when the agents are in it)
  const wk = more.some(t => t.id === 'agents') ? (S.agents || []).filter(a => a.enabled && !agentOffline(a) && a.status === 'working') : [];
  // 2.31.0 (#1056): three groups: places to go (Views), the conversations (team chat, news, agents), then search / settings /
  // the tab bar, set apart
  // 2.364.0 B (#3040): overflowing pinned tabs (Views), the areas (as in the drawer), the conversations, then Search, the tab
  // bar and Settings fixed at the end
  const grp = t => rest.includes(t) ? 0 : ['team', 'news'].includes(t.id) && !t.rail ? 2 : t.id === 'search' ? 3 : t.id === 'settings' ? 4 : 1;
  // 2.489.0 (#2664, decision #2636): no heading "Conversations" any more (the team chat is the area Chat, #2814): News after a line
  const head = [{head: tr('Views')}, {head: tr('Areas|nav')}, '-', '-', null];
  const ord = [0, 1, 2, 3, 4].flatMap(g => { const ts = more.filter(t => grp(t) === g); return ts.length || g === 3 ? [...(head[g] ? [head[g]] : []), ...ts, ...(g === 3 ? [{label: tr('Customise tab bar'), icon: 'edit', fn: () => settingsModal('tabbar')}] : [])] : []; });
  menu(anchor, [...wk.map(a => ({label: tr('{0} is working', a.name) + (a.status_text ? ' · ' + a.status_text : ''), dot: 'working', fn: () => go('agents')})), ...(wk.length ? ['-'] : []), ...ord.map(t => t === '-' || t.head || t.fn ? t : ({label: t.id === 'news' && bellCount() ? `${t.label} (${bellCount()})` : t.label, icon: t.ico || 'list', lic: t.lic,  // 2.883.0 (#5560): the item's own icon (was a guess by module, 'dots' for Knowledge, Tables, Office)
    fn: () => t.act === 'side' ? sideOpenDrawer() : t.act === 'palette' ? openPalette() : t.act ? settingsModal() : go(t.area && t.area === sbb_area() ? sbb_home(t.area) : t.go)}))]).querySelector('.tch-sh')?.classList.add('tch-sh0');  // 2.417.0 A (#3559)
  // 2.883.0 (#5560): "More" has no title: no empty head line, its X sits in the grip's line
}
// 2.579.0 (#4199): once per draw (td_rc: the sidebar, the top bar, the tiles and the tabs read the same), the open tasks once per call
function counts() { return td_rc('counts', counts0); }
function counts0() {
  const t0 = today(), open = openTasks(), c = {today: 0, tomorrow: 0, week: 0, doable: 0, over: 0, all: 0, assigned: 0, byme: 0, waiting: 0, pinned: 0, lists: {}, tags: {}, filters: {}};
  for (const f of S.filters) c.filters[f.id] = open.filter(t => !t.parent_id && filterMatch(t, f.rules)).length;
  for (const t of open) {
    // "Now doable" counts what its view shows at the top level: a subtask only when its parent is not doable itself
    if (doable(t, t0) && !(t.parent_id && S.tasks.get(t.parent_id) && doable(S.tasks.get(t.parent_id), t0))) c.doable++;
    if (t.waiting_at && !(t.parent_id && S.tasks.get(t.parent_id)?.waiting_at)) c.waiting++;  // 2.1.0 (#335)
    if (t.pinned && !t.context && !(t.parent_id && S.tasks.get(t.parent_id)?.pinned)) c.pinned++;  // 2.16.0 (#648)
    if (t.parent_id) continue;
    const lzc = lzCounted(t.list_id);  // 2.369.2 (#3136): a list not loaded is counted by the server (lzCounts)
    if (!lzc) c.all++;
    if (mineAssigned(t) && mtCounts(t, t0)) c.assigned++;  // 2.41.0 (#1365): not the hidden lists (except due today / overdue)
    if (dsxByMe(t)) c.byme++;  // 2.36.2 (#1138)
    if (!lzc) c.lists[t.list_id] = (c.lists[t.list_id] || 0) + 1;
    for (const x of t.also || []) if (!lzCounted(x.list_id)) c.lists[x.list_id] = (c.lists[x.list_id] || 0) + 1;  // 2.71.0 B (#1459): a further list counts it too (everything else once)
    if (!lzc) for (const g of new Set([...t.tags, ...(t.ltags || [])])) c.tags[g] = (c.tags[g] || 0) + 1;
    if ((t.due && t.due <= t0 || dlToday(t) || planToday(t, t0)) && !(t.blocked && hideBlockedToday())) c.today++;  // 2.11.0: + planned for today
    else if (todayInbox() && isTodayInbox(t, t0)) c.today++;  // 2.22.0 (#681): the inbox counts in Today when it is shown there
    if (!t.due) continue;
    if (t.due < t0) c.over++;
    if (t.due === addDays(t0, 1)) c.tomorrow++;
    if (t.due <= addDays(t0, 6)) c.week++;
  }
  lzCounts(c);  // 2.369.2 (#3136)
  return c;
}
// 2.8.0 (#434) "Leitstand": one sidebar, grouped text navigation. Focus (smart lists, with icons), Views (the modules),
// Lists (folders + lists: a dot, the label, the count right after it, the progress of a project on the right), Filters,
// Tags, Team (people + agents with their status dot), then All / Completed / Trash / Archived, Search, Settings and the
// account. Switched-off modules are left out. Each group folds (per device, LS sideGroups).
// 2.24.0 (UX-01): "Views" starts folded and sits below the lists, so a person's own lists come right after Focus; groups
// folded by default remember being opened (LS sideOpenG), the others being folded (LS sideGroups)
const SIDE_FOLDED = ['views', 'areas', 'tags', 'more'];  // 2.39.1 (#1185): "Areas" folds like "Views"
// 2.45.0 (#1502): "Tags" (was its own toggle, S.collapsed side:tags-open) and "More" (All, Completed, Trash, Archived) too
// 2.25.0 (UX-03): the order of the groups and what is hidden is the person's (user setting "sidebar": json {order, hidden};
// hidden: "g:<group>" or "e:<entry>"; the same on every device). "Lists" can be moved but not hidden.
// 2.27.0 (#984): "Views" by default above the lists again (right below Plan, still folded); an own arrangement stays
// 2.39.1 (#1185): "Views" (calendar-like ways to look at tasks) and "Areas" (the modules) instead of one grown list
// 2.44.0 (#1187): the clients are a tab of the area Office (no own group any more)
// 2.45.0 (#1503): the lists right below Plan again (they are what a person opens most; #984 had put Views above them)
// 2.45.0 (#1502): "More" (All, Completed, Trash, Archived) is a group like the others, at the end; Settings stays alone below
const SIDE_GROUPS = ['focus', 'lists', 'views', 'areas', 'filters', 'tags', 'team', 'more'];
const SIDE_NAMES = {focus: N_('Plan|nav'), clients: N_('Clients'), lists: N_('Projects'), filters: N_('Filters'), tags: N_('Tags'), views: N_('Views'), areas: N_('Areas|nav'), team: N_('People'), more: N_('More')};  // 2.489.0 (#2664, decision #2636): the group "Conversations" is gone; what stays (groups, people, agents, News) = People
const SIDE_VIEW_KEYS = ['cal', 'timeline', 'matrix', 'overview', 'workload'];  // 2.45.0 (#1516): + the notes of all lists; 2.398.0 (#3405): notes out (an area of their own)
const SIDE_AREA_KEYS = ['notes', 'office', 'ablage', 'wiki', 'sheets', 'time', 'habits', 'review', 'life', 'reading', 'agents'];  // 2.398.0 (#3405): + notes  // 2.172.0 B (#2679): + Reading  // 2.48.0 (#1207): + the file store  // 2.44.0 (#1187): office, time, review, life = areas (areas.js)
const SIDE_PLAN = [['tomorrow', N_('Tomorrow')], ['week', N_('Next 7 days')], ['doable', N_('Now doable')], ['pinned', N_('Pinned|view')], ['waiting', N_('Waiting on someone')], ['mine_wait', N_('Waiting for me')], ['stale', N_('Lying idle')], ['assigned', N_('My tasks')], ['byme', N_('Assigned by me')]];
const sideModEntries = () => [['cal', N_('Calendar'), feat('cal')], ['timeline', N_('Timeline'), feat('timeline')], ['matrix', N_('Matrix'), feat('matrix')], ['habits', N_('Habits'), feat('habits')],
  ['pomo', N_('Focus timer'), feat('pomo')], ['time', N_('Time tracking'), timeOn()], ['stats', N_('Statistics'), feat('stats')], ['contacts', N_('Contacts'), feat('contacts')], ['life', N_('Home & life'), lifeOn()],
  ['workload', N_('Workload & absences'), wlShown() /* 2.380.2 (#3407) */], ['office', N_('Office & finance'), officeOn()], ['wiki', N_('Knowledge pages'), feat('wiki')], ['sheets', N_('Tables'), feat('sheets')], ['review', N_('Review & journal'), feat('review')], ['family', N_('Family'), famOn()], ['overview', N_('Project status'), overviewOn()], ['agents', N_('Agents'), agentsTab()], ['notes', N_('Notes'), sb_notesShown()]].filter(x => x[2]);
const sideViewEntries = () => SIDE_VIEW_KEYS.map(k => sideModEntries().find(x => x[0] === k)).filter(Boolean);
const sideAreaEntries = () => SIDE_AREA_KEYS.map(k => MG_IDS.includes(k) ? mg_sideEntry(k) : sideModEntries().find(x => x[0] === k)).filter(Boolean);
function sidePref() {
  let o = {}; try { o = JSON.parse(S.settings?.sidebar || '{}') || {}; } catch { o = {}; }
  const order = Array.isArray(o.order) ? o.order : [], hidden = Array.isArray(o.hidden) ? o.hidden : [];
  // 2.39.1 (#1185): an arrangement from before "Areas": the modules were in "Views", so a hidden "Views" hides "Areas" too
  if (!order.includes('areas') && hidden.includes('g:views') && !hidden.includes('g:areas')) hidden.push('g:areas');
  return {order, hidden};
}
const sideHidden = x => sidePref().hidden.includes(x);
const sideGroupOrder = () => {  // an own order stays; unknown groups go to the end, "Areas" (2.39.1) right after "Views"
  const o = sidePref().order.filter(g => SIDE_GROUPS.includes(g));
  if (o.length && !o.includes('areas')) o.splice(o.includes('views') ? o.indexOf('views') + 1 : o.length, 0, 'areas');
  // 2.152.2 (#2622): sidebar B (sketch of 21.10.): "Views" sits between Plan and the projects; an own order stays
  return [...new Set([...o, ...(typeof sbb_panelOn === 'function' && sbb_panelOn() ? ['focus', 'views', ...SIDE_GROUPS] : SIDE_GROUPS)])];
};
const sideOpen = g => sv_open(g) ?? (SIDE_FOLDED.includes(g) ? (LS.get('sideOpenG', []) || []).includes(g) : !(LS.get('sideGroups', []) || []).includes(g));  // 2.156.0 D (#2186): an active sidebar view decides (sideviews.js)
function sideGroupToggle(g) { if (sv_toggle(g)) return; const key = SIDE_FOLDED.includes(g) ? 'sideOpenG' : 'sideGroups', x = new Set(LS.get(key, []) || []); x.has(g) ? x.delete(g) : x.add(g); LS.set(key, [...x]); renderSide(); }
function teamPeople() {
  if (!collab()) return [];
  const seen = new Map();
  for (const l of S.lists) for (const p of listPeople(l)) if (p.user_id && (!S.me || p.user_id !== S.me.id) && !agentById(p.user_id) && !seen.has(p.user_id)) seen.set(p.user_id, p.name || personNameAny(p.user_id));
  return [...seen.entries()].map(([id, name]) => ({id, name})).sort((a, b) => cmpText(a.name, b.name));
}
// 2.36.0 (#1117): the sidebar's list icons (line | emoji | dot) and its progress bars, per person on every device
const sbiMode = () => ['line', 'emoji', 'dot'].includes(S.settings?.side_icons) ? S.settings.side_icons : 'line';
const sbiProg = () => S.settings?.side_progress !== '0';
// 2.36.2 (#1135): the sidebar's way of showing a list, everywhere else too (header, chips, menus, search, groups, archive):
// with "Line" / "Dot" the name's leading emoji is not shown (the name itself stays as it is), a grey line icon with the dot
// in the list colour (or a round dot) stands for it; with "Emoji" everything stays as before 2.36.0
function licName(l) {
  const n0 = l?._live ?? l?.name;  // 2.46.2 (#1659): the name being typed in the list dialog
  const nm = listName(n0), em = l && !l.icon && sbiMode() !== 'emoji' ? leadEmoji(n0) : '';
  return em ? nm.slice(em.length).trim() || nm : nm;
}
function licMark(l, cls = '', full = false) {  // full: a list without an emoji gets its icon too (header, archive, menus)
  if (!l || l.is_inbox || l.icon || sbiMode() === 'emoji') return '';
  return listIconHtml(l, {cls, full});
}
// 2.38.0 (#1174): ONE way to draw a list's icon everywhere (sidebar, header, menus, search, archive, agents): the line icon
// itself takes the list colour (no extra dot); a list without a matching icon gets the plain list icon; an emoji or a picture
// cannot be recoloured and sits on a lightly tinted tile instead; no colour = grey as before; the "Dot" setting keeps its dot.
// opts: cls (extra class), full (also lists without an emoji, default true), emoji (show the name's emoji as a tile - only where
// the name is shown without it), pic (the list's own picture, default true). '' for none (the caller falls back).
function licDim(hex) {  // the list colour 40 % towards the light theme's text colour: about 3:1 on a light background
  const h = hex.slice(1), x = h.length < 6 ? [...h.slice(0, 3)].map(c => c + c) : [h.slice(0, 2), h.slice(2, 4), h.slice(4, 6)];
  return '#' + x.map((v, i) => Math.round(parseInt(v, 16) * .6 + [19, 20, 24][i] * .4).toString(16).padStart(2, '0')).join('');
}
// 2.46.1 (#1636): a shopping list without its own icon (or an emoji in its name) shows the cart -- only shown, nothing stored
const sb_kindIcon = l => l.family === 'shopping' ? 'cart' : '';
function listIconHtml(l, opts = {}) {
  const {cls = '', full = true, emoji = false, pic = true} = opts;
  if (!l || l.is_inbox) return '';
  const sm = sbiMode(), col = cssColor(lp_col(l)), st = col ? ` style="--lc:${col};--lcl:${licDim(col)}"` : '', cc = col ? ' lcol' : '';  // 2.53.0 (#1426): lp_col = the nearest palette tone
  if (l.icon) return pic && sm !== 'dot' ? `<span class="lic lict${cc} ${cls}" aria-hidden="true"${st}>${licon(l, 'licon')}</span>` : '';
  const em = leadEmoji(l.name), kic = !em && sb_kindIcon(l);
  if (sm === 'emoji') return em ? (emoji ? `<span class="lic lict lemo${cc} ${cls}" aria-hidden="true"${st}>${esc(em)}</span>` : '')
    : full || kic ? `<span class="lic${cc} ${cls}" aria-hidden="true"${st}>${ic(kic || 'list')}</span>` : '';
  if (!em && !full && !kic) return '';
  const lk = em && sm === 'line' ? sbiIconFor(em) : '';
  if (sm === 'dot') return `<span class="lic ${cls}" aria-hidden="true"><span class="licd" style="${col ? 'background:' + col : ''}"></span></span>`;
  return `<span class="lic${cc} ${cls}" aria-hidden="true"${st}>${ic(lk || kic || 'list')}</span>`;
}
// 2.36.2 (#1139): an agent gets a small robot in a calm blue (--bot) wherever it writes or sends; people get no symbol
const licBot = () => ic('bot', 's lbot');
function licShareTip(l) {  // "Shared with 2 people and agent X" / "Shared by <name>"
  const n = l.shared_people || 0, ags = l.shared_agents || [];
  const ap = ags.length ? trn('agent {1}', 'agents {1}', ags.length, ags.join(', ')) : '';
  if (!isOwner(l)) return tr('Shared by {0}', l.owner_name) + (ap ? ' · ' + tr('with {0}', ap) : '');
  return n && ap ? tr('Shared with {0} and {1}', trn('{0} person', '{0} people', n), ap) : ap ? tr('Shared with {0}', ap) : n ? trn('Shared with {0} person', 'Shared with {0} people', n) : tr('Shared by you');
}
function licShareHtml(l) {  // people: grey, agents: the robot in blue, both: side by side; always shown
  const hasAg = (l.shared_agents || []).length > 0, hasP = (l.shared_people || 0) > 0 || !hasAg;
  const tip = licShareTip(l);
  return sbc_slots('shr shk', tip, hasAg ? licBot() : '', hasP ? ic('users', 's') : '');
}
// 2.56.0 (#1797): the share symbols sit in two fixed columns at the row's right edge: agent | person (an empty slot keeps its room)
let sb_moreOpen = false;  // 2.250.0 C (#2995): the unfolded "+ N more views" survives a redraw
let sbc_res = false;  // set by renderSide: some row shows a symbol, so every row keeps the two columns
const sbc_slots = (cls, tip, ag, pe) => `<span class="${cls} sbc-sl" ${tip ? `role="img" aria-label="${esc(tip)}" title="${esc(tip)}"` : 'aria-hidden="true"'}><span class="sbc-ag">${ag}</span><span class="sbc-pe">${pe}</span></span>`;
const sbc_ph = () => sbc_res ? sbc_slots('shr sbc-ph', '', '', '') : '';
// 2.308.0 (#3273): a redraw of the sidebar (a live update, the office's folders that load later) dropped the keyboard focus on
// the page: the same button gets it back, like the head bar and the view (keepFocus); a closed phone drawer is left alone
// 2.417.0 A (#3559): what the sidebar's Projects panel and the start page of Projects (viewProjStart) both show, from one place:
// the projects of the shown workspace, the folders shown, the Plan rows ([key, html], '' = not shown now)
const sideLists = () => S.lists.filter(l => !l.is_inbox && !l.archived && !l.quicknote && !life_store(l) && inWs(l));  // 2.609.0 (#4613): an area's store list only through its area  // 2.28.0 (#935): the shown workspace; 2.477.0 (#3881): the list Notes has its own row
// 2.45.0 (#1532): + a folder set to this workspace (a new, still empty one)
const sideFolderShown = (lists, x) => wsCur() === 'all' || lists.some(l => fUnder(l.folder, x)) || sb_folderInWs(x);  // 2.28.0: folders with lists here
const sidePlan = (row, c, onTasks, k) => [['inbox', kbInboxRowTip(row('inbox', ic('inbox'), tr('Basket'), msvvCount(c.lists[inbox()?.id], 'inbox')))],
  ['assigned', row('assigned', ic('user'), tr('My tasks'), c.assigned)],  // 2.40.0 (#1344): right under the basket; 2.569.0 (#4395): always, also alone (2.364.0 D: only while something was assigned)
  ['today', row('today', ic('sun'), tr('Today'), msvvCount(c.today, 'today'))], ['tomorrow', row('tomorrow', ic('sunrise'), tr('Tomorrow'), c.tomorrow)],
  ['week', row('week', ic('week'), tr('Next 7 days'), c.week)], ['doable', row('doable', ic('zap'), tr('Now doable'), c.doable)],
  ['pinned', c.pinned || (onTasks && k === 'pinned') ? row('pinned', ic('pin'), tr('Pinned|view'), c.pinned) : ''],  // 2.16.0 (#648): only while something is pinned
  ['waiting', c.waiting || (onTasks && k === 'waiting') ? row('waiting', ic('hourglass'), tr('Waiting on someone'), c.waiting) : ''],
  ['mine_wait', (n => n || (onTasks && k === 'mine_wait') ? row('mine_wait', ic('flag'), tr('Waiting for me'), n) : '')(mwCount())],  // 2.392.0 D (#3369): only while something waits
  ['stale', (n => n || (onTasks && k === 'stale') ? row('stale', ic('clock'), tr('Lying idle'), n) : '')(staleCount())],  // 2.34.0 (#266): only while something lies idle
  ['byme', collab() && (hasSharing() || c.byme) ? row('byme', ic('send'), tr('Assigned by me'), c.byme) : '']];  // 2.36.2 (#1138)
// 2.417.0 A (#3559): the start page of Projects (#projects): the views of Plan and the filters, then every project grouped by
// its folders in the sidebar's order (the same lists, folders and hidden entries as the panel), each row opens its page
function viewProjStart() {
  const c = counts(), lists = sideLists(), hid = x => sideHidden(x), cnt = n => rsy_sideCnt() && n || '';
  const row = (key, icon, name, n, extra = '') => `<button type="button" class="psrow" data-go="${esc(keyToHash(key))}" ${extra}>${icon}<span class="n">${esc(name)}</span><span class="c">${cnt(n)}</span></button>`;
  // 2.482.0 (#3951): the sidebar's sort mode (S.listReorder, one order): a grip on the left drags at once, rows do not open
  const ro = !!S.listReorder;
  const lrow = l => { const em = !l.icon && leadEmoji(l.name), ic0 = `<span class="sic" aria-hidden="true">${listIconHtml(l, {emoji: true})}</span>`, nm = em ? listName(l.name).slice(em.length).trim() : listName(l.name);
    return ro ? `<div class="psrow reorder" data-list="${l.id}" ${isTouch() ? '' : 'draggable="true"' /* 2.655.0 (#5085) */}><span class="sgrip" title="${esc(tr('Drag to reorder'))}" aria-hidden="true">${ic('grip', 's')}</span>${ic0}<span class="n">${esc(nm)}</span><button type="button" class="iconbtn" data-lsort="${l.id}" aria-haspopup="menu" title="${esc(tr('Move…'))}" aria-label="${esc(tr('Move {0}…', nm))}">${ic('dots', 's')}</button></div>`
      : row('l:' + l.id, ic0, nm, c.lists[l.id], `data-pl="${l.id}"`); };  // 2.484.0 (#3949): data-pl = the row's menu (long press / right click, areas.js)
  const grp = (cls, head, body) => body ? `<section class="psg ${cls}"><h2 class="pshead">${head}</h2><div class="psrows">${body}</div></section>` : '';
  const plan = hid('g:focus') ? '' : sidePlan(row, c, false, '').filter(([x, h]) => h && !hid('e:' + x)).map(([, h]) => h).join('');
  const fil = hid('g:filters') ? '' : S.filters.map(f => row('f:' + f.id, ic('filter'), f.name, c.filters[f.id])).join('');
  const walk = f => [f, ...folderSubs(f).filter(x => sideFolderShown(lists, x)).flatMap(walk)];
  const folders = folderNames().filter(x => !fParent(x) && sideFolderShown(lists, x)).flatMap(walk);
  const loose = lists.filter(l => !l.folder).map(lrow).join('');
  const fhead = f => ro ? `<span class="psfold" data-folder="${esc(f)}">${ic('folder', 's')}<span>${esc(fDisp(f))}</span></span>`
    : `<button type="button" class="psfold" data-go="${esc(keyToHash('folder:' + f))}" data-pf="${esc(f)}" title="${esc(tr('Open {0}', fDisp(f)))}">${ic('folder', 's')}<span>${esc(fDisp(f))}</span></button>`;
  const phead = `<span class="psroot">${esc(tr('Projects'))}</span>${lists.length && !ro ? `<button type="button" class="iconbtn pssort" data-act="lists-reorder" title="${esc(tr('Sort projects'))}" aria-label="${esc(tr('Sort projects'))}">${ic('sort', 's')}</button>` : ''}`;
  const pempty = f => ro ? `<div class="muted psempty fempty" data-folder="${esc(f)}">${esc(tr('empty: drag a project here'))}</div>` : `<div class="muted psempty">${esc(tr('empty'))}</div>`;
  const rbar = ro ? `<div class="sreobar psreobar" role="group" aria-label="${esc(tr('Sort projects'))}"><span class="sreot"><b>${tr('Sort projects')}</b><small>${esc(tr('Drag by the handle on the left, or use “…”'))}</small></span><button type="button" class="btn sm pri" data-act="lists-reorder">${tr('Done')}</button></div>` : '';
  const lgrp = grp('ps-lists', phead, loose || (ro ? `<div class="muted psempty fempty" data-folder="">${esc(tr('empty: drag a project here'))}</div>` : '')) || `<section class="psg ps-lists"><h2 class="pshead">${phead}</h2></section>`;  // the head (with "Sort") even when every project sits in a folder
  const proj = lists.length || folders.length ? rbar + lgrp + folders.map(f => grp('ps-folder', fhead(f), lists.filter(l => l.folder === f).map(lrow).join('') || pempty(f))).join('')
    : emptyState({icon: 'list', title: tr('No projects yet'), action: `<button type="button" class="btn pri" data-act="list-new">${ic('plus', 's')}<span>${esc(tr('New project'))}</span></button>`});  // 2.891.0 (#5440): the shared block
  const parts = {focus: grp('ps-plan', esc(tr('Plan|nav')), plan), lists: proj, filters: grp('ps-filters', esc(tr('Filters')), fil)};
  return `<div class="pstart">${sideGroupOrder().filter(g => g in parts).map(g => parts[g]).join('')}</div>`;  // the sidebar's order of the groups
}
function renderSide() { return !isMobile() || $('#side')?.classList.contains('open') ? keepFocus($('#side'), renderSide0) : renderSide0(); }
function renderSide0() {
  const c = counts(), k = S.route.key, onTasks = S.route.mod === 'tasks';
  const sbb = sbb_on(), sbm = !sbb && sbm_on(), sbbArea = sbb || sbm ? sbb_area() : 'tasks', tasksP = sbbArea === 'tasks';  // 2.152.2 (#2622): sidebar B, the panel of the page's area; 2.196.0 A (#2737): sbm = the phone's drawer like it
  const row = (key, icon, name, n, extra = '', after = '') =>
    `<button class="srow ${onTasks && k === key && !(key === 'all' && isRoadmap()) ? 'on' : ''}" data-go="${esc(keyToHash(key))}" data-drop="${esc(key)}" ${GO_KEY[key] && !isTouch() ? `title="${esc(kt(name, GO_KEY[key]))}"` : ''} ${extra}>${icon}<span class="n">${esc(name)}</span><span class="c ${key === 'today' && c.over ? 'over' : ''}"${n?.tip && rsy_sideCnt() ? ` title="${esc(n.tip)}" aria-label="${esc(n.tip)}"` : ''}>${(rsy_sideCnt() || (key === 'today' && c.over)) && (n?.v ?? n) || ''}</span>${after}</button>`;  // 2.56.1 (#1799): counts can be off (red Today stays)
  const mrow = (mod, icon, name, after = '', attrs = '') => `<button class="srow smod ${S.route.mod === mod ? 'on' : ''}" data-go="${mod}" ${GO_KEY[mod] && !isTouch() ? `title="${esc(kt(name, GO_KEY[mod]))}"` : ''} ${attrs}>${ic(icon)}<span class="n">${esc(name)}</span>${after}</button>`;
  // 2.45.0 (#1502): on = a folded group holds the open view (its header shows it, like a folded folder)
  // 2.353.0 B (#2777): with the panel header of sidebar B "Projects" is already said (the phone's drawer has none): the group's own label is read out only (visually hidden)
  // 2.556.0 (#4661): no longer - the group is always visibly called "Lists" (folded it had no name at all)
  const head = (g, label, acts = '', n = '', tip = '', on = false) => `<div class="shead sgh ${g === 'lists' ? 'lroot' : ''} ${sideOpen(g) ? '' : 'closed'} ${on ? 'sgon' : ''}" ${tip ? `title="${esc(tip)}"` : ''}><button class="sgt" data-act="side-group" data-g="${g}" aria-expanded="${sideOpen(g)}">${ic('chev', 's fcar')}<span>${esc(label)}</span>${!sideOpen(g) && n ? `<span class="c">${n}</span>` : ''}${on ? `<span class="sr"> ${esc(tr('contains the open view'))}</span>` : ''}</button><span class="spacer"></span>${acts}</div>`;
  const lists = sideLists();
  // 2.407.0 (#3518): a list / folder shows open/total (5/12) once something in it is done; the hint names both, the open number stays first
  const sideOD = (open, done) => done ? {v: `${open || 0}/${(open || 0) + done}`, tip: tr('{0} open · {1} done', open || 0, done)} : open;
  sbc_res = false; sbc_res = collab() && rsy_sideShr() && (lists.some(l => l.shared) || folderNames().some(f => folderShrHtml(f)));  // 2.56.0 (#1797)
  const listRow = l => {
    // 2.23.0 (#794): ONE fixed icon column for a picture, an emoji (taken from the name) or the dot, so the names line up
    // 2.36.0 (#1117): what the column shows follows Settings > Appearance > Sidebar: a grey line icon for the name's emoji with its
    // dot in the list colour (default), the emoji itself, or only a round dot; a list's own picture stays (not with "Dot")
    const em = !l.icon && leadEmoji(l._live ?? l.name);  // 2.46.2 (#1659): _live = the name being typed
    // 2.38.0 (#1174): the icon itself in the list colour (listIconHtml), no extra dot
    const sw = `<span class="sic" aria-hidden="true">${listIconHtml(l, {emoji: true})}</span>`;
    const nmOf = x => em ? listName(x._live ?? x.name).slice(em.length).trim() : listName(x._live ?? x.name);
    // 2.25.0 (UX-07): one number per row (the open tasks); a project's progress is a thin bar along the row's bottom
    const pg = progressFor(l) && l.progress?.total && sbiProg() && !progHidden(l.id) ? `<span class="sprog" role="img" style="--p:${pct(l.progress)}%" aria-label="${esc(tr('{0} of {1} done ({2}%)', l.progress.done, l.progress.total, pct(l.progress)))}" title="${esc(tr('{0} of {1} done ({2}%)', l.progress.done, l.progress.total, pct(l.progress)))}"></span>` : '';
    const shr = ws_prvMark(l) + (l.status && statusFor(l) && rsy_sideDot() ? `<span class="stdot st-${esc(l.status)}" title="${esc(statusLabel(l.status))}"></span>` : '') +
      (l.shared && collab() && l.bell === 'mute' ? `<span class="shr bellm" title="${esc(tr('Notifications: {0}', bellLabel('mute')))}">${ic('belloff', 's')}</span>` : '') +
      (l.e2e && typeof le2u_sideMark === 'function' ? le2u_sideMark(l) : '') + ovSideMark(l) + (l.shared && collab() && rsy_sideShr() ? licShareHtml(l) : sbc_ph());  // 2.64.1 (#1817): the lock  // 2.56.0 (#1797): the symbol columns come last  // 2.36.2 (#1139): person / robot, always shown; 2.46.0 (#1603): not joined
    // 2.22.0 (#692): sort mode: a grip on the left, the name shortens with …, the buttons in a fixed column on the right
    // 2.25.0 (UX-02): the full name (it wraps), a grip to drag by (touch: at once, no long press) and ONE "…" button with
    // up / down / folder for keyboards and anyone who does not drag (WCAG 2.5.7)
    if (S.listReorder) { const nm = nmOf(l); return `<div class="srow reorder" data-list="${l.id}" ${isTouch() ? '' : 'draggable="true"' /* 2.655.0 (#5085) */}><span class="sgrip" title="${esc(tr('Drag to reorder'))}" aria-hidden="true">${ic('grip', 's')}</span>${sw}<span class="n">${esc(nm)}</span>${shr}<span class="rctl"><button class="iconbtn" data-lsort="${l.id}" aria-haspopup="menu" title="${esc(tr('Move…'))}" aria-label="${esc(tr('Move {0}…', nm))}">${ic('dots', 's')}</button></span></div>`; }
    return row('l:' + l.id, sw, nmOf(l), sideOD(c.lists[l.id], l.progress?.done), `data-list="${l.id}" ${isTouch() ? '' : 'draggable="true"' /* 2.655.0 (#5085) */}${typeof dx_marked === 'function' && dx_marked(l.id) ? ' data-mark="1"' : ''}${wsc_rowAttr(l)}`, o3c_ring(l, !!pg) + shr + pg);  /* 2.53.0 (#1474): workspace stripe; 2.83.0 C (#1427): progress ring (before the symbol columns, they stay last) */  // 2.47.3 (#1727): + marked
  };
  let lh = lists.filter(l => !l.folder).map(listRow).join('');
  // 2.352.0 E (#2748): a tree of any depth on the sidebar tree (areas.js sbb_treeHtml): a folder's head, then its body (its own
  // lists, then its subfolders, one level deeper); dragging a folder, its menu and the touch hold are the tree's (sidebar.js
  // lf_tree*), a list keeps its own drag (into a folder's head or body). Open / closed stays foldSet / foldClosed (all devices).
  const fempty = f => `<div class="fempty" data-folder="${esc(f)}">${isMobile() ? tr('empty: assign projects in sort mode') : tr('empty: drag a project here')}</div>`;
  const fShown = x => sideFolderShown(lists, x);
  const fnode = f => {
    const fl = lists.filter(l => fUnder(l.folder, f)), closed = foldClosed(f) && !S.listReorder;
    const n = fl.reduce((a, l) => a + (c.lists[l.id] || 0), 0);
    const nd = fl.reduce((a, l) => a + (l.progress?.done || 0), 0);  // 2.407.0 (#3518): the folder sums its lists' done tasks too
    const active = fl.some(l => onTasks && k === 'l:' + l.id);
    const fon = onTasks && k === 'folder:' + f;  // 1.5.2: the name opens the folder view, the arrow folds
    const mir = fl.some(l => l.mirrored);  // 2.27.0 (#988): the owner arranges a shared folder
    const after = (S.listReorder ? '' : `<span class="c" ${nd && rsy_sideCnt() ? `title="${esc(tr('{0} open · {1} done', n, nd))}" aria-label="${esc(tr('{0} open · {1} done', n, nd))}"` : n && rsy_sideCnt() ? `aria-label="${esc(trn('{0} open task', '{0} open tasks', n))}"` : ''}>${rsy_sideCnt() && (nd ? `${n}/${n + nd}` : n) || ''}</span>`)
      + (rsy_sideShr() ? folderShrHtml(f) : '')  // 2.41.0 (#1428); 2.56.1 (#1799): can be off
      + `<span class="sr">${esc(closed ? tr('folded') : tr('unfolded'))}</span>`
      + (S.listReorder ? `<button class="iconbtn" data-fsort="${esc(f)}" aria-haspopup="menu" title="${esc(tr('Move…'))}" aria-label="${esc(tr('Move {0}…', fName(f)))}">${ic('dots', 's')}</button>`
        : `<button class="iconbtn fmenu" data-act="folder-menu" data-folder="${esc(f)}" title="${tr('Folder')}" aria-label="${esc(tr('Folder') + ' ' + fDisp(f))}">${ic('dots', 's')}</button>`);
    return {k: 'lf:' + f, name: fName(f), go: keyToHash('folder:' + f), on: (active && closed) || fon, kids: true, cls: 'lfh' + (fParent(f) ? ' fsub' : ''),
      fold: {open: !closed, attrs: `data-act="folder-toggle" data-folder="${esc(f)}"`}, attrs: `data-act="folder-toggle" data-folder="${esc(f)}"`,  // the row folds as before (the name opens the folder)
      battrs: `title="${esc(tr('Open {0}', fDisp(f)))}"`, ichtml: `<span class="sic" aria-hidden="true"${lp_folderSty(f) /* 2.53.0 (#1426) */}>${ic('folder', 's')}</span>`,  // the icon column of the project rows
      ns: 'lf', id: f, par: fParent(f), drag: !mir, drop: !mir, menu: true, after,  // 2.352.0 E (#2748): someone else's folder takes no folder of mine
      sub: () => { const body = lists.filter(l => l.folder === f).map(listRow).join('') + sbb_treeHtml(folderSubs(f).filter(fShown).map(fnode)); return [{raw: `<div class="fbody" data-folder="${esc(f)}">${body || fempty(f)}</div>`}]; }};
  };
  sbb_treeReg('lf', LF_TREE_H);
  lh += sbb_treeHtml(folderNames().filter(x => !fParent(x) && fShown(x)).map(fnode));
  const archived = S.lists.filter(l => l.archived && !life_store(l) && inWs(l));  // 2.609.0 (#4613)
  const tags = Object.keys(c.tags).sort(cmpText);
  // Focus: the smart lists
  // 2.25.0 (UX-03 / UX-49): Plan (the smart lists) as [key, html]: each entry can be hidden in Settings > Appearance > Sidebar;
  // (UX-47) the team chat and News moved to the group "Conversations" with the people and agents
  const hid = x => sideHidden(x);
  const plan = sidePlan(row, c, onTasks, k);
  const planP = plan;  // 2.450.0 (#3817): the phone's drawer lists Today + Inbox in Plan like the computer (was #2737: fixed on top)
  const planHiddenRows = planP.filter(([x, h]) => h && hid('e:' + x) && !(onTasks && k === x));
  const planHidden = planHiddenRows.length;
  // 2.250.0 C (#2995): "+ N more views" unfolds in place: the hidden views with a tick (= show in the sidebar), then a small link to the settings
  const smOpen = planHidden && sb_moreOpen;
  const smName = x => tr((SIDE_PLAN.find(y => y[0] === x) || [x, x])[1]);
  const focus = planP.filter(([x, h]) => h && (!hid('e:' + x) || (onTasks && k === x))).map(([, h]) => h).join('')
    + (planHidden ? `<button class="srow smore" data-act="side-more" aria-expanded="${smOpen ? 'true' : 'false'}">${ic('plus')}<span class="n">${esc(trn('{0} more view', '{0} more views', planHidden))}</span></button>`
      + (smOpen ? `<div class="smorebox">${planHiddenRows.map(([x, h]) => `<div class="smrow"><input type="checkbox" data-side-show="${esc(x)}" aria-label="${esc(tr('Show {0}', smName(x)))}" title="${esc(tr('Show {0}', smName(x)))}">${h}</div>`).join('')}<button type="button" class="smcust" data-act="side-customize" title="${esc(tr('Settings > Appearance > Sidebar'))}">${esc(tr('Customise…'))}</button></div>` : '') : '');
  const convo = [sb_msgRows(),  // 2.45.0 (#1509): "Messages" (always while the team chat is on) + the last conversations (sbnav.js); 2.479.0 (#2814): not with the area bar (sb_msgShown)
    collab() && (hasSharing() || S.news?.unread || bellCount()) ? `<button class="srow ${S.route.mod === 'news' ? 'on' : ''}" data-go="news" title="${esc(tr('Assignments, @mentions, comments and follow-ups for you'))}">${ic('bell')}<span class="n">${tr('News')}</span><span class="c ${bellCount() ? 'nunread' : ''}">${bellCount() || ''}</span></button>` : ''].join('');  // 2.28.0 (#987): the number = "For you"
  // Views: every switched-on module (the rail's old job)
  const aw = (S.agents || []).reduce((n, x) => n + x.waiting + x.chat_unread + (x.approvals_open || 0), 0);  // 2.35.0 (#1103): open approvals
  const modRows = [feat('cal') ? mrow('cal', 'cal', tr('Calendar')) : '',
    feat('timeline') ? `<button class="srow smod ${isRoadmap() ? 'on' : ''}" data-act="side-timeline">${ic('timeline')}<span class="n">${tr('Timeline')}</span></button>` : '',
    feat('matrix') ? mrow('matrix', 'grid', tr('Matrix')) : '', feat('habits') ? mrow('habits', 'habit', tr('Habits')) : '',
    feat('pomo') ? mrow('pomo', 'timer', tr('Focus timer'), S.pomo ? '<span class="c"><span class="recdot"></span></span>' : '') : '',
    timeOn() ? mrow('time', 'clock', tr('Time tracking'), S.timer ? '<span class="c"><span class="recdot"></span></span>' : '') : '',
    feat('stats') ? mrow('stats', 'chart', tr('Statistics')) : '',
    feat('contacts') ? mrow('contacts', 'users', tr('Contacts')) : '',  // 2.21.0 (#658)
    lifeOn() ? mrow('life', 'home', tr('Home & life')) : '',  // 2.22.0 (#663)
    wlShown() ? mrow('workload', 'chart', tr('Workload & absences')) : '',  // 2.23.0 (#463)  // 2.380.2 (#3407): not in Private
    officeOn() ? mrow('office', 'receipt', tr('Office & finance')) : '',  // 2.36.1 (#1021)
    feat('wiki') ? mrow('wiki', 'book', tr('Knowledge pages')) : '',  // 2.49.0 (#1199)
    feat('sheets') ? mrow('sheets', 'sheet', tr('Tables')) : '',  // 2.89.0 (#1916)
    feat('review') ? mrow('review', 'journal', tr('Review & journal')) : '',
    famOn() ? mrow('family', 'family', tr('Family'), (S.kids || []).some(k => (k.requests || 0) > 0) ? `<span class="c nunread">${(S.kids || []).reduce((n, k) => n + (k.requests || 0), 0)}</span>` : '') : '',
    overviewOn() ? mrow('overview', 'pulse', sbb || sbm ? tr('All projects') : tr('Project status'), `<span class="c ${ovProblems() ? 'over' : ''}">${ovProblems() || ''}</span>`, `title="${esc(tr('Where is it stuck?'))}"`) : '',
    agentsTab() ? mrow('agents', 'bot', tr('Agents'), `<span class="c ${aw ? 'nunread' : ''}">${aw || ''}</span>`) : '',
    sb_notesShown() ? mrow('notes', 'note', tr('Notes'), `<span class="c">${sb_noteCount() || ''}</span>`) : ''].filter(h => { const m = /data-go="(\w+)"|data-act="side-(timeline)"/.exec(h); return !m || !hid('e:' + (m[1] || m[2])) || S.route.mod === m[1]; }).filter(h => !o3a_hidRow(h));  // 2.83.0 (#1845): private modules not in an organisation's view
  // 2.39.1 (#1185): split into "Views" and "Areas", each in its fixed order
  const modKey = h => { const m = /data-go="(\w+)"|data-act="side-(timeline)"/.exec(h); return m ? m[1] || m[2] : ''; };
  const modIn = keys => keys.map(x => MG_IDS.includes(x) ? mg_sideRow(x, hid) : modRows.find(h => modKey(h) === x) || '').join('');  // 2.44.0 (#1187): one row per area
  // 2.152.2 (#2622): sidebar B: the calendar and the areas are icons of the bar, "Views" keeps timeline, matrix, All projects …
  const views = modIn(sbb || sbm ? SIDE_VIEW_KEYS.filter(x => x !== 'cal') : SIDE_VIEW_KEYS), areas = sbb || sbm ? '' : modIn(SIDE_AREA_KEYS);  // 2.196.0 A (#2737): + the phone's drawer
  // Team: the people I share lists with (their tasks) and the agents (status dot; a click opens the chat)
  // 2.99.0 E (#2187): people only while pinned, agents only while pinned / unread / working, "All people …" at the end (sbnav.js)
  const ags = sbp_agents(), ppl = sbp_people();
  // 2.10.0 (#441): my groups; 2.99.0 E (#2187): only the ones I am a member of (admins no longer see every group with a task)
  const grps = collab() ? (S.groups || []).filter(gr => myGroup(gr.id)) : [];
  const gcount = gid => [...S.tasks.values()].filter(t => t.status === 0 && !t.deleted_at && t.assignee_group_id === gid).length;
  const team = convo + [...grps.map(gr => `<button class="srow steam sgrp ${onTasks && k === 'grp:' + gr.id ? 'on' : ''}" data-go="grp/${gr.id}" title="${esc(tr('Tasks of the group {0}', gr.name))}">${ic('users')}<span class="n">${esc(gr.name)}</span><span class="sk">${tr('Group')}</span>${gcount(gr.id) ? `<span class="c">${gcount(gr.id)}</span>` : ''}</button>`),
    ...ppl.map(p => sb_personRow(p, onTasks && k === 'who:' + p.id)),  // 2.24.0 (UX-08): no "Person" under every name; 2.45.0 (#1509): + a bubble for a direct message
    ...ags.map(a => `<button class="srow steam" data-act="team-agent" data-aid="${a.id}"${acw_attr(a.org_id)} title="${esc(agentHstLine(a))}"><span class="sdot"${ac_mk(a.id)}>${hdot(agentHst(a))}</span><span class="n">${esc(a.name)}</span><span class="sk">${tr('Agent')}</span>${a.approvals_open ? `<span class="c apvc" title="${esc(apvCount(a.approvals_open))}">${ic('lock', 's')}${a.approvals_open}<span class="sr"> ${esc(apvCount(a.approvals_open))}</span></span>` : ''}${a.waiting || a.chat_unread ? `<span class="c nunread">${a.waiting + a.chat_unread}</span>` : ''}</button>`), sbp_allRow()].join('');
  // a group folded by default (Views) keeps its rows in the page, hidden: what they show (a running timer's dot, a count)
  // stays current and the keyboard / screen readers skip them until it is opened
  const grp = (g, label, body, acts = '', n = '', tip = '') => `<div class="sgroup sg-${g}">${head(g, label, acts, n, tip, !sideOpen(g) && /class="srow[^"]*\bon\b/.test(body))}${sideOpen(g) ? body : SIDE_FOLDED.includes(g) ? `<div class="sgfold" hidden>${body}</div>` : ''}</div>`;
  // 2.13.3 (#478 follow-up, Fold): one search entry in the sidebar / drawer: the command-bar field (search, commands and the
  // "Search" view inside); no separate "Search" row any more (it doubled the field in the drawer, the field was missing on
  // an unfolded Fold)
  // 2.45.0 (#1502): All, Completed, Trash, Archived (was the footer)
  const moreRows = row('all', ic('all'), tr('All'), c.all) + row('done', ic('done'), tr('Completed'), '') + row('trash', ic('trash'), tr('Trash'), S.counts.trash || '') +
    (archived.length ? (() => {  // 1.6.1: one plain row like Trash; opens the "Archived" view (lit while an archived list is open too)
      const on = onTasks && (k === 'archived' || archived.some(l => k === 'l:' + l.id));
      return `<button class="srow sarch ${on ? 'on' : ''}" data-go="archived">${ic('archive')}<span class="n">${tr('Archived')}</span><span class="c">${archived.length}</span></button>`;
    })() : '');
  const SB = {
    focus: `${grp('focus', tr('Plan|nav'), focus)}`,
    lists: `<div class="sgroup sg-lists">${head('lists', tr('Lists'), `<button data-act="lists-reorder" class="${S.listReorder ? 'on' : ''}" title="${esc(tr('Sort lists'))}" aria-label="${esc(tr('Sort lists'))}">${ic('sort', 's')}</button><button data-act="list-new" title="${esc(tr('New list'))}" aria-label="${esc(tr('New list'))}">${ic('plus', 's')}</button>`, lists.length)}${S.listReorder ? `<div class="sreobar" role="group" aria-label="${esc(tr('Sort projects'))}"><span class="sreot"><b>${tr('Sort projects')}</b><small>${esc(tr('Drag by the handle on the left, or use “…”'))}</small></span><button type="button" class="btn sm pri" data-act="lists-reorder">${tr('Done')}</button></div>` : ''}${sideOpen('lists') || S.listReorder ? (lh && favListsHtml(lh, lists)) || `<div class="folder">${tr('No projects yet')}</div>` : ''}</div>`,
    filters: `${grp('filters', tr('Filters'), S.filters.map(f => row('f:' + f.id, ic('filter'), f.name, c.filters[f.id])).join(''), `<button data-act="filter-new" title="${esc(tr('New filter') + ' · ' + tr('Combine projects, dates, priorities, tags'))}" aria-label="${tr('New filter')}">${ic('plus', 's')}</button>`, S.filters.length, tr('Combine projects, dates, priorities, tags'))}`,
    tags: `${tags.length ? grp('tags', tr('Tags'), tags.map(t => row('tag:' + t, ic('tag'), t, c.tags[t])).join(''), `<button data-go="tags" class="${S.route.mod === 'tags' ? 'on' : ''}" title="${esc(tr('Tags overview'))}" aria-label="${esc(tr('Tags overview'))}">${ic('all', 's')}</button>`, tags.length) : ''}`,  // 2.45.0 (#1502): a header like the others
    views: `${views ? grp('views', tr('Views'), views, '', (views.match(/class="srow smod/g) || []).length) : ''}`,
    areas: `${areas ? grp('areas', tr('Areas|nav'), areas, '', (areas.match(/class="srow smod/g) || []).length) : ''}`,
    team: `${team ? grp('team', tr('People'), team, '', ppl.length + ags.length + grps.length + (convo.match(/class="srow/g) || []).length) : ''}`,
    more: grp('more', tr('More'), moreRows, '', (moreRows.match(/class="srow/g) || []).length)};
  const oldAcct = $('#side .sbacct');  // 2.47.0 (#1654): keep the account node (same <img>) when nothing about it changed
  const scmd = `<button class="scmd" data-act="palette" title="${esc(tr('Search and commands'))}" aria-label="${esc(tr('Search and commands'))}">${ic('search', 's')}<span>${tr('Jump, create, ask an agent…')}</span></button>`;  // 2.138.0 B (#2161)
  // 2.152.2 (#2622): sidebar B: Settings at the bottom of the bar (areas.js sbb_railHtml), 2.152.3 A (#2619): the search and the
  // account in the head bar over everything (sbb_barHtml); the panel of another area than Tasks shows that area's entries
  // (sbb_panelHtml) instead of the groups
  // 2.152.2 (#2622, decision of 21.10.): in sidebar B Plan (Inbox, Today …) stays fixed on top with the search, only the middle scrolls
  const planFix = (sbb || sbm) && tasksP && !hid('g:focus') ? SB.focus || '' : '';
  const pan = tasksP ? '' : sbb_panelHtml(sbbArea);  // 2.152.3 A (#2619): first, the panel's head looks whether its groups fold
  // 2.450.0 (#3817): the phone's drawer: the search, the row of the areas (2.442.0 #3739: they scroll along, the search alone stays), then Plan (only in the area Projects, like planFix of sidebar B); #2737 had Today + Inbox fixed on top
  const sbmTop = sbm ? `<div class="sbmtop"><div class="sbmsrch">${scmd}</div></div>${sbm_rowHtml(hid)}` : '';
  const sset = `<button class="srow sset" data-act="settings" title="${esc(kt(tr('Settings'), 'g s'))}">${ic('gear')}<span class="n">${tr('Settings')}</span>${updDot() ? `<span class="c nunread" title="${esc(tr('Update available'))}">●</span>` : ''}</button>`;
  const sbmX = sbm ? $('#side .sbmr')?.scrollLeft : null;
  const sideHtml = `
    <div class="sbfix${sbb ? ' sbfix-flow' : sbm ? ' sbfix-flow sbfix-m' : ''}">${'' /* 2.331.0 A (#3303): in sidebar B the head scrolls along; 2.442.0 (#3739): in the phone's drawer too, only the search stays on top */}${'' /* 2.57.0 (#1798): the fixed head (workspace, favourites) stays while the rest scrolls */}
    <div class="sbhead">${'' /* 2.138.2 C (#2392): the 4 px stripe of #2389 is #side's top border (app.css); fold + fold-all show on hover / focus, the dot only offline or while syncing. 2.161.2 A (#2607): the brand (logo + word mark) is the workspace switch, the small mark at the bottom (2.145.0 A #2437) is gone. 2.152.3 A (#2619): on a computer the brand, the switch and the dot moved into the head bar (#kbar); the panel's head is the area's name, fold all and hide the panel (sbb_headHtml) */}${sbb ? sbb_headHtml(sbbArea, pan) : `${wsBarHtml()}${netDotHtml()}<span class="spacer"></span><span class="sbtools">${tasksP ? kbFoldAllBtn() + fv2_svToolBtn() /* 2.156.0 D (#2186) */ : ''}${!isMobile() && innerWidth < 1100 ? `<button class="iconbtn sfold" data-act="side-fold" aria-pressed="${!!LS.get('sideFold', false)}" title="${esc(LS.get('sideFold', false) ? tr('Keep the sidebar open') : tr('Fold the sidebar away'))}" aria-label="${esc(LS.get('sideFold', false) ? tr('Keep the sidebar open') : tr('Fold the sidebar away'))}">${ic('chev', 's')}</button>` : ''}</span>`}</div>
    ${tasksP && !sbm ? favSideHtml(lists, listRow, head) : ''}${sbm ? sbmTop + planFix : planFix + sbmTop}</div>
    ${tasksP && sbm ? favSideHtml(lists, listRow, head) : ''}${tasksP ? sideGroupOrder().filter(g => (!hid('g:' + g) || g === 'lists') && !(planFix && g === 'focus')).map(g => (SB[g] || '') + (g === 'lists' ? msvvSide() : '')).join('') : pan}
    ${sbb ? '' : `${sbm ? '' : `<div class="sgroup sfoot">
      ${sset}
    </div>`}
    <div class="sbdock${sbm ? ' sbmdock' : ''}">${S.me ? `<button type="button" class="sbacct" data-act="user-menu" aria-haspopup="menu" title="${esc(acctLabel())}" aria-label="${esc(acctLabel())}">${av(S.me.id, S.me.display_name, 'avatar', '', '', true)}</button>` : '' /* 2.138.2 C (#2392): the account picture, without dots, next to the search */}${sbm ? sset : scmd}</div>`}`;
  const sd = $('#side'), keep = side_keep(sd, sideHtml, tasksP);  // 2.609.0 (#4509): the same sidebar: no new nodes (scroll, focus, hover stay)
  if (!keep) {
    const y = sd.scrollTop;
    sd.innerHTML = sideHtml;
    const newAcct = $('#side .sbacct');
    if (oldAcct && newAcct && oldAcct.innerHTML === newAcct.innerHTML && oldAcct.title === newAcct.title) newAcct.replaceWith(oldAcct);
    side_mark(sd, sideHtml);
    if (y && sd.scrollTop !== y) sd.scrollTop = y;
    if (tasksP) sv_after();  // 2.156.0 D (#2186): what the active view hides goes under "Others (N)" (sideviews.js)
  }
  sbb_render(hid);  // 2.152.2 (#2622)
  if (sbm && keep !== 'same') sbm_after(keep ? null : sbmX);  // 2.196.0 A (#2737)
  sideRove();
}
// 2.609.0 (#4509): renderSide0 ran on every render() and replaced the whole sidebar (innerHTML): the scroll position, a hover
// and the nodes went each time. Its signature is the HTML it would draw now -- it holds everything the sidebar shows (route,
// projects, names, colours, folders, counts, filters, fold state, sync / offline dots, language, rights, favourites, areas),
// so nothing can be left out of it. The same HTML: the nodes stay ('same'). Only the open view moved (the classes on / sgon
// and aria-current differ, nothing else): those marks are switched on the nodes in place ('act'). Anything else: drawn anew
// (null). Drawn anew always while a sidebar view hides rows (sideviews.js sv_after changes the nodes after drawing), when
// another script replaced or added nodes, or #side itself is new.
const SIDE_ACT_RE = /\s(class="[^"]*")|\saria-current="[^"]*"/g;
const side_norm = html => html.replace(SIDE_ACT_RE, (m, cls) => cls ? ' ' + cls.replace(/(^class="|\s)(?:on|sgon)(?=[\s"])/g, '$1') : '');
function side_mark(sd, html) {  // what side_keep compares with next time: the drawn HTML and the nodes in their order
  const nodes = [...sd.getElementsByTagName('*')];
  S._sideSig = {sd, html, norm: null, nodes, n: nodes.length};
}
function side_keep(sd, html, tasksP) {
  const p = S._sideSig;
  if (!p || !sd || p.sd !== sd || (tasksP && fv2_svHas() && (typeof sv_cur !== 'function' || sv_cur())) || sd.getElementsByTagName('*').length !== p.n || p.nodes[0]?.parentNode !== sd) return null;
  if (p.html === html) return 'same';
  if (p.norm == null) p.norm = side_norm(p.html);
  if (p.norm !== side_norm(html)) return null;
  const t = document.createElement('template'); t.innerHTML = html;
  const nw = t.content.querySelectorAll('*');
  if (nw.length !== p.n) return null;
  for (let i = 0; i < nw.length; i++) {
    const a = nw[i], b = p.nodes[i];
    for (const c of ['on', 'sgon']) if (a.classList.contains(c) !== b.classList.contains(c)) b.classList.toggle(c);
    const ac = a.getAttribute('aria-current');
    if (ac !== b.getAttribute('aria-current')) { if (ac == null) b.removeAttribute('aria-current'); else b.setAttribute('aria-current', ac); }
  }
  p.html = html; p.norm = null;
  return 'act';
}
// 2.13.0 (#453 A9): the sidebar is ONE tab stop (roving tabindex): Tab lands on the open view's row (or the first one),
// ↑ / ↓ / Home / End walk through every row, folder and group header, Enter / Space open it, Tab goes on to the content.
// Before, 30+ stops stood between the top of the page and the content.
const sideItems = () => $$('#side button, #side [data-act="folder-toggle"], #side a[href]').filter(b => !b.disabled && b.offsetParent !== null && !b.closest('.hidden') && !b.closest('[hidden]'));
function sideRove(cur) {
  const it = sideItems(); if (!it.length) return;
  const keep = cur || it.find(b => b === document.activeElement) || it.find(b => b.classList.contains('srow') && b.classList.contains('on')) || it.find(b => b.classList.contains('srow')) || it[0];
  for (const b of $$('#side button, #side [data-act="folder-toggle"], #side a[href]')) b.tabIndex = b === keep ? 0 : -1;
}
document.addEventListener('focusin', e => { if (e.target.closest?.('#side') && e.target.tabIndex === -1 && sideItems().includes(e.target)) sideRove(e.target); });
document.addEventListener('keydown', e => {
  if (!e.target.closest?.('#side') || e.ctrlKey || e.metaKey || e.altKey || typing(e.target)) return;
  const it = sideItems(), i = it.indexOf(e.target); if (i < 0) return;
  const to = {ArrowDown: i + 1, ArrowUp: i - 1, Home: 0, End: it.length - 1}[e.key];
  if (to === undefined) { if ((e.key === 'Enter' || e.key === ' ') && e.target.dataset.act === 'folder-toggle') { e.preventDefault(); e.target.click(); } return; }
  e.preventDefault(); e.stopPropagation();
  const n = it[Math.max(0, Math.min(it.length - 1, to))]; sideRove(n); n.focus();
}, true);
// the skip link "Skip to content" (first stop of the page): focuses the view's first control
function skipToContent() {
  const v = $('#view'); if (!v) return;
  v.tabIndex = -1; v.focus({preventScroll: true});  // the next Tab goes to the view's first control
}
$('#skip')?.addEventListener('click', skipToContent);
function renderTop() { return keepFocus($('#top'), renderTop0); }
function renderTop0() {
  const m = S.route.mod, k = S.route.key;
  const MT = {cal: N_('Calendar'), matrix: N_('Matrix'), habits: N_('Habits'), pomo: N_('Focus timer'), news: N_('News'), stats: N_('Statistics'), time: N_('Time tracking'), overview: N_('Project status'), agents: N_('Agents'), team: N_('Team chat'), home: N_('Start|home'), family: N_('Family'), contacts: N_('Contacts'), life: N_('Home & life'), review: N_('Review & journal'), clients: N_('Clients'), workload: N_('Workload & absences'), wiki: N_('Knowledge pages'), tags: N_('Tags'), sheets: N_('Tables')};  // 2.49.0 (#1199): + wiki
  let title = m === 'tasks' ? titleFor(k) : m === 'notes' ? (S.nt.lid ? (qn_isList(S.nt.lid) ? lname(listById(S.nt.lid)) : tr('Notes') + ' · ' + (lname(listById(S.nt.lid)) || '')) : tr('Notes')) : m === 'family' && S.me?.kid ? tr('My day') : MT[m] ? tr(MT[m]) : '';
  if (m === 'tasks' && isRoadmap()) title = tr('Timeline');  // 2.445.0 (#3011): the heading = the name in the menu
  if (m === 'matrix' && mxTitle()) title = `${tr('Matrix')} · ${mxTitle()}`;
  if (!title && m === 'budget') title = tr('Budget');  // 2.72.0 (#1333)
  if (!title && m === 'feeds') title = tr('Feeds');  // 2.85.0 B (#1162)
  if (!title && m === 'bookmarks') title = tr('Bookmarks');  // 2.97.0 A (#1950)
  if (!title && m === 'reading') title = tr('Read later');  // 2.172.0 B (#2679)
  if (!title && (m === 'ablage' || m === 'docs')) title = tr('Files');  // 2.48.0 (#1207, #1111); 2.752.0 (#4887): one area "Files"
  if (m === 'msv') title = msvvTitle();  // 2.73.0 C (#661)
  if (mg_title(m) && !S.me?.kid && !(sbb_on() && mg_areaOf(m)?.[0] !== 'office')) title = mg_title(m);  // 2.44.0 (#1187): the area's name, its tabs below; 2.152.2 (#2618): sidebar B has no tabs, the part's own name (the office's page has its own heading)
  if (sbb_on() && mg_areaOf(m)?.[0] === 'office' && !S.me?.kid && typeof ofm_cur === 'function') { const oit = ofm_all().find(i => i.key === ofm_cur(m)); if (oit) title = tr(oit.name); }  // 2.224.0 B (#2816): the big heading of an office page = its name ("Office" stands above the panel)
  if (m === 'office' && !isMobile() && !S.me?.kid && typeof ofd_docTitle === 'function' && ofd_docTitle()) title = ofd_docTitle();  // 2.936.0 (#5448): an open document: its number, not "Quotations"
  const wkPg = m === 'wiki' && typeof wk_phonePage === 'function' && wk_phonePage();  // 2.1108.0 (#5965): a phone with an open knowledge page
  if (wkPg) title = wk_topTitle();  // the page's name instead of the area's (the page's head keeps back + path)
  let acts = '';
  if (m === 'tasks' && k === 'projects') acts += `<button class="btn sm pri tnewp" data-act="list-new" aria-haspopup="menu" title="${esc(tr('New project'))}" aria-label="${esc(tr('New project'))}">${ic('plus', 's')}<span>${tr('New project')}</span></button>`;  // 2.417.0 A (#3559): the start page of Projects; 2.498.0 (#3854): a narrow phone: the symbol
  if (m === 'tasks' && (k.startsWith('l:') || k === 'inbox')) {
    const l = k === 'inbox' ? inbox() : listById(+k.slice(2));
    if (l) {
      const v = curView(l), vc = viewChoices(l);  // 2.7.1 (#410): + "Project overview" in project lists
      // 2.8.0 (#434): the view switch as text tabs (List / Kanban / Timeline / Project overview)
      // 2.32.0 (#1062): no longer folds into "…" (no .tf): on a narrow header (tl3 / tl4, e.g. with the task panel open) the
      // tabs become icons (the name stays as aria-label and tooltip)
      if (vc.length > 1 && !isMobile()) acts += `<div class="seg vseg ttabs" role="group" aria-label="${esc(tr('View'))}">${vc.map(([k, n, i]) => `<button class="${v === k ? 'on' : ''}" data-act="view-${k}" data-ico="${i}" title="${esc(tr(n))}" aria-label="${esc(tr(n))}" aria-pressed="${v === k}">${ic(i, 's')}<span class="vtl">${esc(tr(n))}</span></button>`).join('')}</div>`;
      // 2.14.0 (#425): "Columns…" (the list's columns for every member) replaces the per-device field-column switch
      if (td_colsWide() && v === 'list' && !l.archived) acts += `<button class="iconbtn tf ${listCols(l) ? 'on' : ''}" data-act="cols" data-ico="columns" data-id="${l.id}" title="${esc(tr('Shown fields…'))}" aria-label="${esc(tr('Shown fields…'))}" aria-haspopup="dialog">${ic('columns')}</button>`;
      if (!isMobile()) acts += lv_btn(l);  // 2.577.0 (#3356): the project's shared views (phones: in "…")
      // 2.6.0 (K12): Share next to the title (desktop / tablets; phones: in "…")
      if (!l.is_inbox && !l.archived && collab() && !isMobile()) acts += `<button class="iconbtn tf shbtn" data-act="share-list" data-ico="users" data-id="${l.id}" title="${esc(tr('Share…'))}" aria-label="${esc(tr('Share…'))}">${ic('users', 's')}<span class="bl">${tr('Share')}</span></button>`;
    }
  }
  // 2.4.2 (#390): a folder switches between its list view and the matrix of all its lists (subfolders included), like a list
  const fk = m === 'tasks' && k.startsWith('folder:') ? k.slice(7) : m === 'matrix' && mxGet().scope.startsWith('folder:') ? mxGet().scope.slice(7) : '';
  if (fk && feat('matrix') && !isMobile()) acts += `<div class="seg vseg fseg tf" role="group" aria-label="${esc(tr('View'))}"><button class="${m === 'tasks' ? 'on' : ''}" data-act="fview" data-k="list" data-ico="list" data-f="${esc(fk)}" title="${esc(tr('List'))}" aria-pressed="${m === 'tasks'}">${ic('list', 's')}</button><button class="${m === 'matrix' ? 'on' : ''}" data-act="fview" data-k="matrix" data-ico="grid" data-f="${esc(fk)}" title="${esc(tr('Matrix'))}" aria-pressed="${m === 'matrix'}">${ic('grid', 's')}</button></div>`;
  if (m === 'tasks' && k === 'all' && feat('timeline')) { const v = isRoadmap() ? 'timeline' : 'list'; acts += `<div class="seg tf" role="group" aria-label="${tr('View')}"><button class="${v === 'list' ? 'on' : ''}" data-act="rm-view" data-k="list" data-ico="list" title="${tr('List')}" aria-pressed="${v === 'list'}">${ic('list', 's')}</button><button class="${v === 'timeline' ? 'on' : ''}" data-act="rm-view" data-k="timeline" data-ico="timeline" title="${tr('Timeline')}" aria-pressed="${v === 'timeline'}">${ic('timeline', 's')}</button></div>`; }
  if (m === 'tasks' && k === 'inbox') acts += kbSortBtn();  // 2.39.1 (#1219)
  if (m === 'tasks' && k === 'inbox') acts += asst_inboxBtn();  // 2.75.0 (#1411)
  if (m === 'tasks' && k.startsWith('lists:') && typeof dx_listsActs === 'function') acts += dx_listsActs(k);  // 2.47.3 (#1727)
  if (m === 'tasks' && k === 'trash' && (S.hist?.k === 'trash' && S.hist.deletable != null ? S.hist.deletable > 0 || S.hist.others > 0 : (S.extra || []).some(t => !t.keep))) acts += `<button class="btn sm danger" data-act="trash-empty">${tr('Empty')}</button>`;
  if (m === 'tasks' && k === 'done' && (S.extra || []).length) acts += `<button class="btn sm" data-act="done-clean" title="${esc(tr('Move completed tasks to the trash'))}">${ic('trash', 's')}<span class="bl">${tr('Delete completed…')}</span></button>`;
  // 2.24.0 (#906): "Tasks of …" of another person: write to them
  if (m === 'tasks' && k.startsWith('who:') && S.me && +k.slice(4) !== S.me.id && !agentById(+k.slice(4))) acts += `<button class="btn sm tf" data-act="dm" data-uid="${+k.slice(4)}" data-ico="comment" title="${esc(tr('Message'))}">${ic('comment', 's')}<span class="bl">${tr('Message')}</span></button>`;
  if (m === 'agents' && !S.route.agent && S.me && !S.me.kid && aiPaneOn()) acts += `<button class="btn sm tf4" data-act="ag-setup" data-ico="plus" title="${esc(tr('Add agent…'))}">${ic('plus', 's')}<span class="bl">${tr('Add agent…')}</span></button>`;  // 2.366.0 (#2998)
  if (m === 'tasks' && S.multiMode) acts += `<button class="iconbtn on" data-act="multi" title="${tr('End selection')}" aria-label="${tr('End selection')}">${ic('select')}</button>`;
  // everything rarer sits in "…" (phones: undo / redo there too); the title keeps its room; 2.1108.0 (#5965): not on a phone's open knowledge page (its own "…" carries these)
  if (!wkPg) acts += `<button class="iconbtn tmore" data-act="top-more" aria-haspopup="menu" title="${tr('More actions')}" aria-label="${tr('More actions')}">${ic('dots')}${isMobile() && HIST.undo.length && histPending(HIST.undo[HIST.undo.length - 1]) ? '<span class="pdot"></span>' : ''}</button>`;
  const pm = '';  // focus / stopwatch are part of the running indicator (timerPill) now
  const oflab = OUT.online ? tr('sync|pending changes') : OUT.down ? (OUT.maint ? tr('server in maintenance') : tr('server not reachable')) : tr('offline'), ofn = OUT.q.length ? trn('{0} change waiting', '{0} changes waiting', OUT.q.length) : '';
  const off = !OUT.online || OUT.q.length ? `<span class="offline" role="status" title="${esc([oflab, ofn, tr('Changes are sent as soon as the server is reachable')].filter(Boolean).join(' · '))}" aria-label="${esc([oflab, ofn].filter(Boolean).join(' · '))}">${ic(OUT.online ? 'sync' : 'cloudoff', 's')}<span class="ofl">${oflab}</span>${OUT.q.length ? `<span class="ofn">${OUT.q.length}</span>` : ''}</span>` : '';
  const cf = S.conflicts?.length ? `<button class="cfpill" data-act="conflicts" title="${tr('Review conflicts')}">${ic('alert', 's')}${S.conflicts.length}</button>` : '';
  // open tasks of the view next to the title (Geist Mono), task views only
  const nOpen = m === 'tasks' && !NOLIST_KEYS.includes(k) ? msvvCount(viewTasks().open.length, k) : 0;  // 2.73.0 C (#661): + other servers in Today / Basket
  // 2.8.0 (#434): the command bar (search + commands + the agents' chat) and "New task" (mouse screens; touch has the + button)
  // 2.18.0 (#651, owner decision: the magnifier is always visible): Search never folds into "…" (no .tf4); the title gets cut instead (fitTop)
  const pal = `<button class="kbtn cmdbar" data-act="palette" data-ico="search" title="${esc(tr('Search and commands'))} (${kbText('Mod+K')})" aria-label="${esc(tr('Search and commands'))}">${ic('search', 's')}<span>${tr('Jump, create, ask an agent…')}</span>${kb('Mod+K')}</button>`;
  // 2.25.0 (UX-32): ONE way to add per view: where the add bar sits at the bottom, no second "New task" up here
  const tnew = (!isMobile() || tabletDock()) && !dockView() && (m === 'tasks' || (m === 'cal' && isTouch())) && !noFab() && !S.multiMode ? `<button class="btn pri tnew tf4" data-act="new-task" data-ico="plus" title="${esc(kt(tr('New task'), 'n'))}" aria-label="${esc(tr('New task'))}">${ic('plus', 's')}<span>${tr('New task')}</span></button>` : '';
  const ms = (() => {  // the next open milestone of a project list
    const l = m === 'tasks' && k.startsWith('l:') ? listById(+k.slice(2)) : null;
    const x = l && !l.is_inbox ? (l.milestones || []).filter(y => !y.done).sort((a, b) => a.day.localeCompare(b.day))[0] : null;
    return x ? `<span class="hms ${x.day < today() ? 'over' : ''}" title="${esc(tr('Milestone') + ': ' + x.name + ', ' + fmtDateLoc(x.day))}">◆ ${esc(x.name)} · ${esc(dayLabel(x.day))}</span>` : '';
  })();
  const kl = m === 'tasks' && k.startsWith('l:') ? listById(+k.slice(2)) : null;
  S.bandOn = bandAgents().length > 0;  // 2.8.0 (#434): the band shows the agents' dots, the header pill keeps only the robot
  const bar = sbb_on();  // 2.152.3 A (#2619): on a computer search, workspace and bell sit in the head bar over everything (sbb_bar)
  setHtml($('#top'), `${isMobile() ? '' : bnBtn()}<button class="iconbtn menu" data-act="side" aria-label="${tr('Menu')}">${ic('menu')}</button><h1 title="${esc(title)}">${listIconHtml(kl, {cls: 'h', full: false})}<span class="ht">${esc(title)}</span>${kl?.e2e && typeof le2u_headMark === 'function' ? le2u_headMark(kl) : ''}${wsBadge(kl)}${nOpen ? `<span class="hn" aria-label="${esc(trn('{0} open task', '{0} open tasks', nOpen))}">${nOpen}</span>` : ''}${ms}</h1>${kl ? favTopBtn(kl) : fv2_topBtn() /* 2.441.0 (#3592): a star in every header */}${cf}${off}${timerPill()}${pm}${acts}${isMobile() ? '' : histBtns()}${bar ? '' : pal}${tnew}${bar || (kl && wsBadge(kl)) ? '' : wsChip()}${stChip()}${agentChip()}${/*html-ok*/ bar ? '' : spl_btn() + bellBtn() /* 2.1037.0 (#5803): miniwin.js */}`);  // 2.7.2 (#417): the agents' robot + dots directly before the bell  // 2.7.0 (#405): touch tablets / an unfolded Fold have the room for ← →
  fitTop();
  sbb_bar();  // 2.152.3 A (#2619): the bell's number
  netDotDraw();  // 2.31.0 (#378): the dot at the own picture follows every change of the connection
}
// ---- 2.6.0 (K01 + K02, UX audit 2): the header has a fixed priority on every width. The title comes first: it keeps at
// least ~12 characters (or all of it, when shorter) and is shown in full whenever any level below makes room; "…" and the
// bell are always on screen. Everything else gives way step by step (classes tl1 … tl4 on #top, the lowest level that
// fits wins, measured after every render and on resize):
//   tl1  the agent pill = bot + number, the timer pill = icon + time (no task name), Search = icon, no offline label
//   tl2  the agent pill and the timer pill merge into one status chip (.stchip: bot + number, dot + time)
//   tl3  the view switch, field columns, refresh and undo / redo move into "…" (.tf, as menu items)
//   tl4  New task moves into "…" too (.tf4), the open count goes, the status chip is only its dot + number; Search stays
//        (2.18.0, #651), and when even tl4 does not fit, the title is cut below its 12 characters (ellipsis; the h1 keeps
//        the whole title as its tooltip and for screen readers)
//   tl5  2.498.0 (#3854), phones only (on top of tl4): the workspace sign moves into "…" (.tf5); title and bell come first
//   tl6  phones only: the agents' sign too (.tf6; the status chip keeps its running timer): it says who is working, so it goes last
// jsdom has no layout (every width is 0), so there everything fits at level 0.
const TOP_LVLS = 4;
let topW = 0;
const topMax = () => isMobile() ? 6 : TOP_LVLS;
function topLevel() { const t = $('#top'); const m = t && [...t.className.matchAll(/\btl(\d)\b/g)].pop(); return m ? +m[1] : 0; }
// width the first 12 characters of the title need (with "…"), measured on its text
function topNeed(ht, k = 12) {  // 2.18.0 (#651): k = fewer characters when even the last level does not fit
  const n = ht && ht.firstChild; if (!n || n.nodeType !== 3) return 0;
  const len = n.textContent.length, r = document.createRange();
  r.setStart(n, 0); r.setEnd(n, Math.min(len, k));
  const w = r.getBoundingClientRect().width, all = len > k ? (r.setEnd(n, len), r.getBoundingClientRect().width) : w;
  return {need: w + (len > k ? parseFloat(getComputedStyle(ht).fontSize) * .7 : 0), full: all};
}
function topFits(t, ht, nd) {
  const cr = t.getBoundingClientRect(), right = cr.right - parseFloat(getComputedStyle(t).paddingRight || 0) + .5;
  if (t.scrollWidth > t.clientWidth + 1) return 0;
  for (const e of t.children) if (e.offsetWidth && e.getBoundingClientRect().right > right) return 0;
  // 2.6.1: a pill squeezed so far that its own content is cut (the timer's time, the agents' dots) does not fit either
  for (const e of t.querySelectorAll(':scope > .tmini, :scope > .achip, :scope > .stchip')) if (e.offsetWidth && e.scrollWidth > e.clientWidth + 1) return 0;
  if (!ht || !nd) return 2;
  const w = ht.getBoundingClientRect().width;
  return w + .02 >= nd.full ? 2 : w + 1 >= Math.min(nd.need, nd.full) ? 1 : 0;  // 2 = whole title, 1 = at least 12 characters
}
function fitTop() {
  const t = $('#top'); if (!t || !t.isConnected) return;
  topW = t.clientWidth;
  const ht = $('h1 .ht', t), h1 = $('h1', t), more = $('[data-act="top-more"]', t);
  const nd = t.clientWidth ? topNeed(ht) : 0;
  // 2.18.0 (#651): nothing fits even at the last level (Search no longer folds away): the title keeps fewer characters
  // (6, 4, 2 + "…"), never none
  let cut = null;
  const set = l => {
    for (let i = 1; i <= 6; i++) t.classList.toggle('tl' + i, i === l || (i >= 4 && i < l));
    if (more) more.hidden = !topMoreItems().length;
    // the title never gets less than its first 12 characters (plus its icon / badge / count): the rest has to make room
    if (h1 && nd) {
      const kids = [...h1.children].filter(e => e !== ht && e.offsetWidth), gap = parseFloat(getComputedStyle(h1).columnGap) || 0;
      const nn = cut || nd;
      h1.style.minWidth = Math.ceil(kids.reduce((n, e) => n + e.getBoundingClientRect().width, 0) + gap * kids.length + Math.min(nn.need, nn.full) + 1) + 'px';
    }
  };
  t.classList.remove('tvc');
  set(0);
  if (!t.clientWidth) return;  // no layout (hidden, jsdom)
  // 2.828.0 (#5443): the project name before the symbols: when the whole title fits on none of the levels that only make
  // the pills smaller (tl0 - tl2), the list's view switch shows only the active view first (#top.tvc, a click opens the others)
  if (nd && !isMobile() && $('.vseg.ttabs', t)) {
    let whole = false;
    for (let l = 0; l <= 2 && !whole; l++) { set(l); whole = topFits(t, ht, nd) === 2; }
    if (!whole) t.classList.add('tvc');
    set(0);
  }
  // the lowest level that shows the whole title; otherwise the one that gives the title the most room
  // 2.18.0 (review R3, owner rule: frequently used one-tap actions stay visible, the title shortens instead): the folding
  // levels (tl3 / tl4: view switch, undo / redo, Share, New task into "…") are only taken when nothing fits with the title
  // cut to its minimum at a non-folding level (tl0 - tl2 only make the pills more compact)
  let best = -1, wide = -1, ww = -1;
  const top = topMax();
  for (let l = 0; l <= top; l++) {
    if (l >= 3 && wide >= 0) break;  // the title is already cut to >= 12 characters without folding anything
    // 2.26.x (1280 px, wide sidebar + task panel): before the view switch folds into "…", the title shortens further
    // (6 characters + "…") at the last non-folding level
    // 2.498.0 (#3854): a phone has no view switch up there: the signs give way, not the title
    if (l === 3 && nd && !isMobile()) { cut = topNeed(ht, 6); set(2); if (topFits(t, ht, cut)) return; cut = null; }
    if (l) set(l);
    const f = topFits(t, ht, nd);
    if (f === 2) { best = l; break; }
    const w = f ? ht.getBoundingClientRect().width : -1;
    if (f && l >= 3) { wide = l; break; }  // the first folding level that fits wins (fold as little as possible)
    if (f && w > ww + 4) { wide = l; ww = w; }
  }
  if (best < 0 && wide < 0 && nd) {
    for (const k of [6, 4, 2]) { cut = topNeed(ht, k); set(top); if (topFits(t, null, null)) return; }
  }
  set(best >= 0 ? best : wide >= 0 ? wide : top);
}
if (document.fonts?.ready) document.fonts.ready.then(() => fitTop()).catch(() => {});
if (typeof ResizeObserver !== 'undefined') {
  let topRO = null;
  const topWatch = () => { const t = $('#top'); if (!t || topRO) return; topRO = new ResizeObserver(() => dragRest('top', () => { if (t.clientWidth !== topW) fitTop(); })); topRO.observe(t); };
  domReady(topWatch);  // 2.191.0 B (#2505): defer
} else addEventListener('resize', () => fitTop());
// 2.557.0 A (#4553): list and detail side by side once the content area (#view, not the window) is at least 100rem wide:
// #view gets the class lsdw (app.css / office.css lay the pair out; office_docs.js draws the list beside the open document,
// office_books.js docks a receipt beside its list). Below it everything stays as before (the detail in place of the list).
const LSD_REM = 100;
const lsd_wide = () => !!$('#view')?.classList.contains('lsdw');
function lsd_sync() {
  const v = $('#view'); if (!v) return;
  const rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16, on = v.clientWidth >= LSD_REM * rem - 0.5 && !matchMedia('(max-width:767px)').matches;
  if (on !== v.classList.contains('lsdw')) {
    v.classList.toggle('lsdw', on);
    if (typeof ofdDraw === 'function') ofdDraw();  // a quotation / invoice: with or without its list beside it
  }
  if (typeof rcl_dockSync === 'function') rcl_dockSync();  // a docked receipt follows the size of the area
}
if (typeof ResizeObserver !== 'undefined') domReady(() => { const v = $('#view'); if (v) new ResizeObserver(() => dragRest('lsd', lsd_sync)).observe(v); lsd_sync(); });
else addEventListener('resize', () => lsd_sync());
// 2.583.0 (#4840): the content width of the list as --lw (px) on #view, for the growing text columns (start-breite.css).
// Firefox kept a 100cqw behind var() at the list's width of an earlier layout when the list grew afterwards (the container
// query stayed true, so nothing was styled again): a real variable that changes styles the rows again. The list itself is
// watched (it is drawn anew with each render: a MutationObserver on #view hands the new one over); no list = no
// variable, a list drawn later starts from 100cqw, never from an old width. While a grip is dragged dragRest (#4860, core.js).
let lwRO = null, lwEl = null;
function lw_watch() {  // a new list element: watch it (the observer measures it once right away), none: no variable
  const v = $('#view'), w = v && v.querySelector('.lwrap'); if (!v || w === lwEl) return;
  if (lwEl) lwRO?.unobserve(lwEl);
  lwEl = w; if (w) lwRO?.observe(w); else v.style.removeProperty('--lw');
}
function lw_sync() {
  const v = $('#view'), w = lwEl; if (!v || !w || !w.isConnected) return;
  const cs = getComputedStyle(w), px = Math.round(w.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight));
  if (px > 0 && v.style.getPropertyValue('--lw') !== px + 'px') v.style.setProperty('--lw', px + 'px');
}
if (typeof ResizeObserver !== 'undefined') domReady(() => { const v = $('#view'); if (!v) return; lwRO = new ResizeObserver(() => dragRest('lw', lw_sync)); new MutationObserver(() => lw_watch()).observe(v, {childList: true, subtree: true}); lw_watch(); });
// Esc (events.js, nothing else open) closes the detail of the pair, the list stays
function lsd_esc() {
  if (!lsd_wide() || S.sel) return false;
  const r = S.route || {};
  const back = sel => requestAnimationFrame(() => $(sel)?.focus());  // the row of the closed detail keeps the keyboard
  if (r.mod === 'contacts' && typeof CT !== 'undefined' && CT.card && !CT.pick) { const id = CT.sel; CT.sel = null; CT.card = null; if (location.hash !== '#contacts') go('contacts'); else ctDraw(); back(`#view .ctrow[data-ctopen="${id}"]`); return true; }
  if (r.mod === 'clients' && +r.client && !(typeof MSC !== 'undefined' && MSC.pick)) { const id = r.client; go('clients'); back(`#view .ctrow[data-clopen="${id}"]`); return true; }
  if (r.mod === 'office' && r.id && ['offers', 'invoices'].includes(r.tab) && $('#view .lsd2')) { $('#view .lsd2 [data-ofd="back"]')?.click(); return true; }
  return false;
}
// the header items that moved into "…" (tl3 - tl6), as menu items that click the hidden button
function topFolded() {
  const l = topLevel(); if (l < 3) return [];
  const els = $$('#top .tf [data-act], #top [data-act].tf' + (l >= 4 ? ', #top [data-act].tf4' : '') + (l >= 5 ? ', #top [data-act].tf5' : '') + (l >= 6 ? ', #top [data-act].tf6' : ''));
  return els.filter(b => !b.disabled || b.closest('.hist')).map(b => ({label: (b.getAttribute('aria-label') || b.title || b.textContent || '').replace(/\s*\([^)]*\)\s*$/, '').trim(), icon: b.dataset.ico || (/hist-undo/.test(b.dataset.act) ? 'undo' : /hist-redo/.test(b.dataset.act) ? 'redo' : ''),
    on: b.classList.contains('on'), dis: b.disabled, fn: () => (b.isConnected ? b : $(`#top [data-act="${b.dataset.act}"]`) || b).click()}));  // 2.498.0 (#3854): a live redraw while the menu is open
}
// UX1 (U01, owner decision 4): the header's "…" menu. Phones: "Undo: …" / "Redo: …" first (no ← → there), then the rarer
// view actions (select, sort), then the list's own menu or the filter
function topMoreItems() {  // 2.99.0 B (#2183): + the knowledge pages' "Space" section
  const fv = fv2_topItems(), o0 = topMoreItems0(), out = fv.length ? [...fv, '-', ...o0] : o0;  // 2.441.0 (#3592): a phone: the star of a page (a list: its own menu has it)
  const ha = !S.me?.kid && S.me?.kind !== 'agent' && out.length ? hlp_area() : '';  // 2.1086.0 (#5820): "Help for this area" where the "…" is shown anyway
  // 2.1102.0 (#5956): before the set-apart dangerous tail (archive, delete: #1056 keeps them last), else at the end
  let dz = out.length; while (dz > 0 && out[dz - 1] && out[dz - 1].danger) dz--;
  const hi = {label: tr('Help for this area'), icon: 'help', cls: 'mhlp', fn: () => go('help/area:' + ha)};
  if (ha) { if (dz < out.length && out[dz - 1] === '-') out.splice(dz - 1, 0, '-', hi); else out.push('-', hi); }
  if (S.route.mod !== 'wiki' || S.me?.kid || typeof w299_areaItems !== 'function') return out;
  return [...out, ...(out.length ? ['-'] : []), ...w299_areaItems()];
}
function topMoreItems0() {
  if (S.me?.kid) return [{label: tr('Account'), icon: 'user', fn: () => settingsModal('account')}, {label: tr('Settings'), icon: 'gear', fn: () => settingsModal()},
    ...(S.me?.auth === 'session' ? ['-', {label: tr('Sign out'), icon: 'logout', fn: logout}] : [])];  // 2.19.0: a child's "…": its account only
  const m = S.route.mod, k = S.route.key, fold = topFolded(), out = [], sec = [];
  if (isMobile()) for (const dir of ['undo', 'redo']) { const b = histBtn(dir); if (b.off && !b.p) continue; out.push({label: b.lab, icon: dir, dis: b.off, cls: 'hmi' + (b.p ? ' pend' : ''), title: b.p ? tr('waiting for the connection') : '', fn: () => histStep(dir)}); }
  // 2.24.0 (UX-35): Today's planners live here now (the header keeps its room for the tasks)
  if (m === 'tasks' && k === 'today') out.push({label: tr('Plan my day'), icon: 'cal', fn: () => dayplanModal('day')}, {label: tr('Fill free time'), icon: 'clock', fn: () => dayplanModal('fill')});
  if (m === 'tasks' && k === 'today' && asst_ready()) out.push({label: tr('Assistant plan'), icon: 'sparkle', fn: () => asst_go({kind: 'dayplan', day: today()})});  // 2.75.0 (#1411)
  if (m === 'tasks' && k === 'today') out.push({label: tr('Customise Today…'), icon: 'sliders', fn: () => lyOpen('today', true)});  // 2.32.0 (#1063)
  if (m === 'tasks' && k === 'today' && typeof lyv_viewMenu === 'function') out.push(...lyv_viewMenu('today'));  // 2.55.0 (#1069): Today has no header switch
  if (m === 'time') out.push({label: tr('Customise…'), icon: 'sliders', fn: () => lyOpen('time', true)});
  if (m === 'tasks' && !NOLIST_KEYS.includes(k) && !isKanban() && !isTimeline() && !isRoadmap() && !isOverview())
    sec.push({label: S.multiMode ? tr('End selection') : tr('Select multiple'), icon: 'select', on: S.multiMode, fn: () => { S.multiMode = !S.multiMode; if (!S.multiMode) S.multi.clear(); render(); }},
      {label: tr('Sort…'), icon: 'sort', next: 1, fn: () => sortMenu($('#top [data-act="top-more"]') || $('#top h1'))});
  // 2.445.0 (#3008): what the header shows is not repeated here (a folded header button comes back through fold)
  const inTop = a => !!$(`#top [data-act="${a}"]`);
  { const cl = m === 'tasks' ? routeList() : null; if (cl && !cl.archived && listView(cl) === 'list' && !isOverview() && !inTop('cols')) sec.push(colItem(cl.id)); }  // 2.14.0 (#425)
  sec.push(...(m === 'tasks' ? doneItems(routeList()) : []));  // 2.39.1 (#1214), 2.445.0 (#3008): one switch
  sec.push(...collapseItems());
  sec.push(...kbGroupResetItems());  // 2.39.1 (#1221)
  sec.push(...favViewItems());  // 2.40.0 (#1361)
  { const mo = moViewItems(); if (mo.length) sec.push(...mo); }  // 2.40.0 (#1344): own order / grouped by list
  const mxk = m === 'tasks' ? (k === 'inbox' ? 'l:' + inbox()?.id : k.startsWith('l:') || k.startsWith('f:') || k.startsWith('folder:') ? k : '') : '';
  if (mxk && feat('matrix')) sec.push({label: tr('Show as matrix'), icon: 'grid', fn: () => { mxSet({scope: mxk}); go('matrix'); }});
  const mxs = m === 'matrix' ? mxGet().scope : '';  // 2.4.2 (#390): back from the matrix to the folder / list it shows
  if (mxs.startsWith('folder:') || mxs.startsWith('l:') || mxs.startsWith('f:')) sec.push({label: tr('Show as list'), icon: 'list', fn: () => go(keyToHash(mxs))});
  if (m === 'tasks' && k.startsWith('f:')) sec.push({label: tr('Edit filter'), icon: 'edit', fn: () => filterModal(+k.slice(2))});
  const l = m === 'tasks' && (k.startsWith('l:') || k === 'inbox') ? (k === 'inbox' ? inbox() : listById(+k.slice(2))) : null;
  // 2.13.0 (#453 A7): phones switch the view with the segmented control under the title (vsegHtml), no longer here
  // 2.35.0 (#1105): no "Refresh" in the list menu any more - the app checks every 4 s and the offline hint calls refreshNow()
  // 2.31.0 (#1056): in a list two groups with a small heading each: View (incl. the folded header buttons) and List; then
  // archive / delete, set apart (listMenuSort)
  const li = l ? listMenuItems(l.id, () => $('#top [data-act="top-more"]') || $('#top h1')).filter(x => !(x.cls === 'mcols' && (inTop('cols') || sec.some(y => y.cls === 'mcols'))) && !(x.cls === 'mshare' && inTop('share-list'))) : [];
  if (l) sec.push(...lv_items(l, inTop('lviews')));  // 2.577.0 (#3356)
  const heads = li.length > 0 && (sec.length > 0 || fold.length > 0);
  if (heads) { fold.unshift({head: tr('View')}); sec.push({head: tr('Project')}); }
  else if (l && sec.length && sec[sec.length - 1] !== '-') sec.push('-');
  sec.push(...li);
  if (m === 'tasks' && k.startsWith('tag:')) { if (sec.length) sec.push('-'); sec.push(tagDeleteItem(k.slice(4))); }
  const rest = [...out, ...(out.length && sec.length ? ['-'] : []), ...sec];
  // 2.366.0 (#3002): no stand-in search entry any more - the search sits right next to it, a view without own actions has no "…" (fitTop hides it)
  // 2.13.0 (#453 A7): an entry that is already there (a folded header button, e.g. "Share…") comes only once
  const seen = new Set(fold.map(x => x.label)), rest2 = rest.filter(x => x === '-' || x.row || x.head || !seen.has(x.label));
  if (heads) {  // undo / redo on top, then View: the folded header buttons and the view entries, then List
    const o = rest2.filter(x => x.cls?.startsWith('hmi')), r = rest2.filter(x => !x.cls?.startsWith('hmi'));
    while (r[0] === '-') r.shift();
    return menuTidy([...o, ...(o.length ? ['-'] : []), ...fold, ...r]);
  }
  return [...fold, ...(fold.length && rest2.length ? ['-'] : []), ...rest2].filter((x, i, a) => x !== '-' || (i > 0 && a[i - 1] !== '-' && i < a.length - 1));
}
// ---- 1.9.0: delete a tag completely (sidebar: right-click / long-press on the tag, or "…" in the tag view). Tags are
// personal: only my tag goes, from every task that has it (the tasks stay); one step in the undo history.
const tagDeleteItem = tag => ({label: tr('Delete tag…'), icon: 'trash', cls: 'danger', fn: () => tagDelete(tag)});
function tagMenu(anchor, tag) {
  menu(anchor, [{label: tr('Open'), icon: 'tag', fn: () => go('tag/' + encodeURIComponent(tag))}, ...fv2_menuRow('tag:' + tag) /* 2.57.0 (#1798) */, '-', tagDeleteItem(tag)]);
}
async function tagDelete(tag) {
  let n;
  try { n = await api('GET', '/api/tags/count?tag=' + encodeURIComponent(tag)); } catch { return; }
  const body = n.tasks ? trn('It is removed from {0} task ({1} open). The tasks themselves stay.', 'It is removed from {0} tasks ({1} open). The tasks themselves stay.', n.tasks, n.open)
    : tr('No task has this tag any more.');
  if (!await askConfirm(tr('Delete the tag {0}?', '#' + tag), body + ' ' + tr('Tags are personal: other people’s tags are not touched.'), {ok: tr('Delete tag'), danger: true})) return;
  let j;
  try { j = await api('POST', '/api/tags/delete', {tag}); } catch { return; }
  const strip = () => { for (const t of S.tasks.values()) if (t.tags?.includes(tag)) t.tags = t.tags.filter(g => g !== tag); };
  strip();
  if (S.route.mod === 'tasks' && S.route.key === 'tag:' + tag) go(START_KEY);
  const e = histAdd({label: tr('Tag deleted: {0}', '#' + tag), snaps: [], ids: [], lids: [],
    undo: async () => { await api('POST', '/api/tags/restore', {tag, ids: j.ids}); await load(); return {skipped: []}; },
    redo: async () => { await api('POST', '/api/tags/delete', {tag}); strip(); await load(); return {skipped: []}; }});
  offerUndo(trn('Tag {1} removed from {0} task', 'Tag {1} removed from {0} tasks', j.count, '#' + tag), e);
  try { await load(); } catch { /* offline */ }
  render();
}
// ---- 1.9.0: refresh for shared lists (header button; touch: pull down at the top of the list, or "…" > Refresh).
// The app polls /api/version every 4 s while visible anyway; this is for "is it really up to date?" moments.
function sharedRoute() {
  const k = S.route.key; if (S.route.mod !== 'tasks' || !collab()) return false;
  if (k.startsWith('l:') || k === 'inbox') { const l = routeList(); return !!l?.shared; }
  if (k.startsWith('folder:')) return folderLists(k.slice(7)).some(l => l.shared);
  return false;
}
let refreshing = false;
async function refreshNow() {
  if (refreshing) return;
  refreshing = true; $$('[data-act="refresh"]').forEach(b => b.classList.add('spin'));
  try { await flushSaves(); await load(); render(); msvvLoad();  /* 2.73.0 C (#661) */ if (S.sel && (cmtOn() || collab())) loadTimeline(S.sel); S.syncOk = Date.now(); toast(tr('Up to date')); }
  catch (e) { if (e instanceof Offline) toast(tr('You are offline')); }
  finally { refreshing = false; $$('[data-act="refresh"]').forEach(b => b.classList.remove('spin')); }
}
function routeList() {
  const k = S.route.key;
  if (S.route.mod !== 'tasks') return null;
  return k === 'inbox' ? inbox() : k.startsWith('l:') ? listById(+k.slice(2)) : null;
}
const listView = (l, w = lv_disp(l) || l.view) => !l.is_inbox && ((w === 'kanban' && feat('kanban')) || (w === 'timeline' && feat('timeline')) || w === 'mindmap' || (w === 'calendar' && feat('cal'))) ? w : 'list';  // 2.577.0 (#3356): an open shared view brings its display  // 2.156.0 C (#2071): + calendar  // 2.49.0 (#1201): + mind map  // 2.25.0 (UX-38): the inbox is always a list
function isKanban() { const l = routeList(); return !!l && !povOn(l) && listView(l) === 'kanban'; }
function isTimeline() { const l = routeList(); return !!l && !povOn(l) && listView(l) === 'timeline'; }
function isMindmap() { const l = routeList(); return !!l && !povOn(l) && listView(l) === 'mindmap'; }  // 2.49.0 (#1201)
function isListCal() { const l = routeList(); return !!l && !povOn(l) && listView(l) === 'calendar'; }  // 2.156.0 C (#2071): listcal.js
// 2.13.0 (#453 P15): week / day view: the hour grid fills exactly the room below its header, so only the grid scrolls
// (before, the page scrolled too: two scroll bars nested)
function calFit() {
  const wb = $('#wbody'), v = $('#view');
  v?.classList.toggle('calfit', !!wb);
  if (!wb || !v.clientHeight) return;
  const tabs = $('#tabs'), tb = tabs && getComputedStyle(tabs).display !== 'none' ? tabs.getBoundingClientRect().height : 0;
  const h = Math.max(240, Math.floor(innerHeight - tb - wb.getBoundingClientRect().top - 12));
  wb.style.height = h + 'px';
}
window.addEventListener('resize', () => { if (S.route?.mod === 'cal' || isListCal()) calFit(); });  // 2.156.0 C (#2071): + a list's calendar
// 2.13.2 (#478 N2): a re-render (live updates of agents, comments, jobs) never takes the keyboard focus away: a focused
// button / link / cell of the rebuilt area gets its focus back on its new copy (same tag + data-* / id, same position
// among equal ones), so Tab goes on from there instead of falling back to the start (the "tab ping-pong")
const cssEsc = v => typeof CSS !== 'undefined' && CSS.escape ? CSS.escape(v) : String(v).replace(/["\\]/g, '\\$&');  // 2.46.2: not in every test DOM
function focusSig(el) {
  if (el.id) return `[id="${cssEsc(el.id)}"]`;
  const a = [...el.attributes].filter(x => /^data-/.test(x.name) && x.name !== 'data-k').map(x => `[${x.name}="${cssEsc(x.value)}"]`).join('');
  return el.tagName.toLowerCase() + a + (a ? '' : el.getAttribute('aria-label') ? `[aria-label="${cssEsc(el.getAttribute('aria-label'))}"]` : '');
}
// While such an element has the focus the area is not rebuilt but morphed (setHtml -> morphKids: same nodes where tag and
// key match, only attributes / text change), so the focused node itself stays in place: browsers keep their Tab position
// only on the same node (Firefox went back to the previous element after a refocus on a new copy).
let morphRoot = null;
// 2.46.2 (#1718): what a morph inserted as new nodes (top-level of each inserted subtree), for hooks like the fade-in of new
// chat messages / comments: fl_onAdded(fn) -> fn(root, nodes) after every morph of root (nodes = [] when nothing was new)
const FL = {hooks: [], added: null, vsig: null, ins: 0};
function fl_onAdded(fn) { FL.hooks.push(fn); }
// 2.46.2 (#1718): a part of a view drawn again: morphed when it has content (kept nodes, no flash), built when empty
function fl_set(el, html) { const prev = morphRoot; if (el.firstChild) morphRoot = el; try { if (el.firstChild) keepReading(kr_scroller(el), () => setHtml(el, html)); else setHtml(el, html); } finally { morphRoot = prev; } }  // 2.924.0 (#5224): + keepReading
// 2.46.2 (#1718): live redraws of the view (job steps, the jobs list, agent status, the agent band) are gathered: at most one
// every 400 ms (the first after ~one frame). raw = renderView (else viewSafeRender: a busy field waits); mod = only while that
// module is shown. A redraw in between (a click) restarts the 400 ms.
function fl_viewSoon(raw, mod) {
  FL.vraw = FL.vraw || !!raw; if (mod !== undefined) FL.vmod = FL.vt && FL.vmod !== mod ? null : mod; else if (FL.vt) FL.vmod = null;  // any module
  if (FL.vt) return;
  const run = () => {
    FL.vt = 0; const r = FL.vraw, m = FL.vmod; FL.vraw = false; FL.vmod = undefined;
    if (m && S.route.mod !== m) return;
    if (r) renderView(); else viewSafeRender();
  };
  const wait = Math.max(0, (FL.vlast || 0) + 400 - Date.now());
  FL.vt = setTimeout(run, Math.max(16, wait));  // a timer, not a frame: a page that goes away takes it along
}
// 2.431.0 C (#3598): clients and contacts scroll in their two columns (the list, the card): a redraw keeps the list's scroll on
// the same page and the card's on the same entry; the card of another entry starts at its top (a morph kept the old offset)
function ct_scrollKeep(el) {
  const sc = () => { const v = el.querySelector('.ctview'), c = v?.querySelector('.ctcard'); return v && [v.classList.contains('msclients'), v.querySelector('.ctlistw'), c, c?.dataset.ck]; };
  const a = sc(), ls = a?.[1]?.scrollTop, cs = a?.[2]?.scrollTop;
  return () => { const b = sc(); if (!a || !b || a[0] !== b[0]) return; if (b[1]) b[1].scrollTop = ls || 0; if (b[2]) b[2].scrollTop = a[3] === b[3] ? cs || 0 : 0; };
}
function setHtml(el, html) {
  const fg = typeof fgKeep === 'function' ? fgKeep(el) : null;  // 2.40.0 (#1371): unsaved form input survives the redraw
  if (morphRoot !== el) el.innerHTML = html;
  else {
    const t = document.createElement('template'); t.innerHTML = html;
    const outer = FL.added; FL.added = [];
    try { morphKids(el, t.content); fl_iiTidy(el); if (typeof infoize === 'function') infoize(el); }  // 2.40.0 (#1382): (i) buttons back after a morph
    finally { const add = FL.added; FL.added = outer; if (outer) outer.push(...add); FL.ins += add.length; for (const h of FL.hooks) try { h(el, add); } catch (e) { console.error(e); } }
  }
  if (fg) fg();
}
const mkey = n => n.nodeType !== 1 ? null : ['data-k', 'data-id', 'data-cid', 'data-aid', 'data-jid', 'data-mid', 'data-key', 'data-section'].map(k => n.getAttribute(k)).find(v => v != null) ?? null;
// 2.46.2 (#1718): infoize() adds an (i) button (.ib[data-ii]) next to a hint and gives the hint an id / data-ii / .iisrc; a
// morph keeps these instead of dropping and re-adding them on every redraw
const fl_iiId = o => o.nodeType === 1 && o.hasAttribute('data-ii') && /^ii\d+$/.test(o.id);
const fl_ib = o => o.nodeType === 1 && o.nodeName === 'BUTTON' && o.classList.contains('ib') && o.hasAttribute('data-ii');
const fl_key = n => { if (n.nodeType !== 1) return null; const id = fl_iiId(n) ? '' : n.id; if (id) return '#' + id + ':' + n.nodeName; const k = mkey(n); return k == null ? null : n.nodeName + ':' + k; };
function fl_iiTidy(root) { for (const b of root.querySelectorAll('button.ib[data-ii]')) if (!document.getElementById(b.dataset.ii) && !root.querySelector(`[id="${b.dataset.ii}"]`)) b.remove(); }
// what code sets after the render (calFit / chatFit heights, the phone chat's keyboard fix, a drag, the sheet grid's cells)
// stays on a kept node; the code that set it also takes it away
const FL_RTC = ['vvfix', 'dragging', 'sb-secfold', 'sgact', 'sgsel', 'cfin'];  // CI of 2.223.1: + sb-secfold (a section folded while it is dragged, #1635); 2.547.0 (#4500): + cfin (a morph right after a new message keeps its fade-in)
const fl_rtStyle = o => o.id === 'wbody' || o.classList.contains('chview');
// a <details> the person opened by hand stays open when the view's HTML does not decide it (the views that keep the state
// themselves write "open" from it); _flSet marks a toggle that came from a morph, not from the person
document.addEventListener('toggle', e => { const d = e.target; if (d?.nodeName !== 'DETAILS') return; if (d._flSet) d._flSet = false; else d._flUser = d.open; }, true);
function fl_attrs(o, n) {
  if (o.nodeName === 'DETAILS' && o.open !== n.hasAttribute('open')) { if (o.open && o._flUser === true) n.setAttribute('open', ''); else o._flSet = true; }
  for (const x of [...o.attributes]) if (!n.hasAttribute(x.name) && !(x.name === 'data-ii' || (x.name === 'id' && fl_iiId(o)) || (x.name === 'style' && fl_rtStyle(o)))) o.removeAttribute(x.name);
  const rc = [...FL_RTC, ...(o.hasAttribute('data-ii') ? ['iisrc'] : [])].filter(c => o.classList.contains(c));
  for (const x of [...n.attributes]) if (o.getAttribute(x.name) !== x.value) o.setAttribute(x.name, x.value);
  for (const c of rc) if (!o.classList.contains(c)) o.classList.add(c);
}
// nodes in the middle of an edit are left alone: the row with the inline title field, a table cell with its editor open
function fl_hold(o) {
  if (o.id === 'tc-new' || o.id === 'tth-new' || o.id === 'cm-new') return true;  // 2.46.3 (#1660): a shown "New message" pill stays shown on a redraw
  if (o.classList.contains('iedit') && S.ie && o.dataset.id === String(S.ie.id) && o.querySelector('.ttlin')) return true;
  return o.classList.contains('tcon') && o.contains(document.activeElement);
}
// 2.46.2 (#1718): children are matched by key (id or data-k / data-id / …), so an inserted, removed or moved row keeps all
// other rows' nodes (before, everything after it was replaced); unkeyed nodes match by position among the unkeyed ones
function morphKids(a, b) {
  const an = [...a.childNodes], bn = [...b.childNodes], nk = new Set(), km = new Map();
  for (const n of bn) { const k = fl_key(n); if (k != null) nk.add(k); }
  for (const o of an) { const k = fl_key(o); if (k != null && nk.has(k) && !km.has(k)) km.set(k, o); }
  let cur = a.firstChild;
  const skip = () => {  // stale keyed nodes go at once, (i) buttons stay where they are
    while (cur) {
      if (fl_ib(cur)) { cur = cur.nextSibling; continue; }
      const k = fl_key(cur);
      if (k != null && km.get(k) !== cur) { const x = cur; cur = cur.nextSibling; x.remove(); continue; }
      break;
    }
  };
  for (const n of bn) {
    skip();
    const k = fl_key(n);
    let o = null;
    if (k != null) { o = km.get(k) || null; if (o) km.delete(k); }
    else if (cur && fl_key(cur) == null && cur.nodeType === n.nodeType && cur.nodeName === n.nodeName) o = cur;
    if (!o) {
      if (cur && k == null && fl_key(cur) == null) { const x = cur; cur = cur.nextSibling; a.replaceChild(n, x); }  // same place, other kind of node
      else a.insertBefore(n, cur);
      if (n.nodeType === 1 && FL.added) FL.added.push(n);
      continue;
    }
    if (o === cur) cur = cur.nextSibling; else a.insertBefore(o, cur);
    if (o.nodeType !== 1) { if (o.data !== n.data) o.data = n.data; continue; }
    if (fl_hold(o)) continue;
    // 2.46.2 (#1718): a field with typed, unsaved text keeps it unless its saved value changed (the view's own restore after a
    // rebuild only ran on a new node)
    const tf = (o.nodeName === 'TEXTAREA' || (o.nodeName === 'INPUT' && !/^(checkbox|radio|file)$/.test(o.type))), dv = tf ? o.defaultValue : null, dirty = tf && o.value !== dv;
    const nv = tf || o.nodeName === 'SELECT' ? n.value : null, nc = o.nodeName === 'INPUT' ? n.checked : null;  // before the children move over
    fl_attrs(o, n);
    if (o.hasAttribute('data-fl-fill') && !n.firstChild) continue;  // filled after the render (Office quotations): keeps its content
    if (!o.isEqualNode(n)) morphKids(o, n);
    if (/^(INPUT|SELECT|TEXTAREA)$/.test(o.nodeName) && o !== document.activeElement && !(dirty && o.defaultValue === dv)) { if (o.type === 'checkbox' || o.type === 'radio') o.checked = nc; else if (o.type !== 'file' && o.value !== nv) o.value = nv; }
  }
  while (cur) { const x = cur; cur = cur.nextSibling; if (!fl_ib(x)) x.remove(); }
}
// 2.46.2 (#1718): the view is morphed whenever it is drawn again for the same route (live updates, a job step, a click that
// redraws); only a change of the view (another module / list / tab / view mode) builds it from scratch. Calendar, timeline
// and roadmap morph too (their handlers are delegated, the after-render steps are guarded).
const fl_sig = () => { const l = S.route.mod === 'tasks' ? routeList() : null; return [S.route.mod, S.route.key, S.route.tab, S.route.agent, l ? listView(l) + (isRoadmap() ? 'r' : '') + (isOverview() ? 'o' : '') : ''].join('|'); };
function keepFocus(root, fn) {
  const a = document.activeElement, isView = !!root && root.id === 'view', vs = isView ? fl_sig() : null;
  // 2.46.2 (#1718): the header is morphed on every redraw too, so a dialog's opener there (Menu, …) stays the same node
  const same = (isView ? FL.vsig === vs : root?.id === 'top') && !!root.firstChild;
  if (!root || ((!a || a === document.body || !root.contains(a) || editFocused()) && !same)) { try { return fn(); } finally { if (isView) FL.vsig = vs; } }
  let sig = null, i = 0;
  if (a && a !== document.body && root.contains(a) && !editFocused()) try { sig = focusSig(a); i = [...root.querySelectorAll(sig)].indexOf(a); } catch { sig = null; }
  const ef = a && root.contains(a) && editFocused() ? a : null; let efs = null, efe = null; try { efs = ef?.selectionStart ?? null; efe = ef?.selectionEnd ?? null; } catch { /* no caret on this type */ }
  const prev = morphRoot; morphRoot = root;
  let r; try { r = fn(); } finally { morphRoot = prev; if (isView) FL.vsig = vs; }
  if (ef && (!ef.isConnected || document.activeElement !== ef) && (!document.activeElement || document.activeElement === document.body)) {  // 2.58.0 (#1644): a text field that lost the focus in the redraw (Android keyboard) gets it back with its caret
    try { const n = root.querySelector(focusSig(ef)); if (n && n !== ef && n.offsetParent !== null) { n.focus({preventScroll: true}); if (efs != null && n.setSelectionRange && n.value.length >= efs) n.setSelectionRange(efs, efe ?? efs); } } catch { /* odd selector / type without a caret */ }
  }
  if (!sig || (a.isConnected && document.activeElement === a)) return r;
  const cur = document.activeElement;
  if (cur && cur !== document.body && cur !== a) return r;  // the render moved the focus on purpose
  let n = null; try { const all = root.querySelectorAll(sig); n = all[Math.max(0, Math.min(i, all.length - 1))]; } catch { /* odd selector */ }
  if (n && n.offsetParent !== null && !n.disabled) n.focus({preventScroll: true});
  return r;
}
// 2.758.0 (#5223): the agents page moves only when the person makes it move. A redraw or a box filled later keeps on the screen
// what the person looks at: the row tapped last (while it is in sight), else the first card / row that begins in sight; its
// screen position before = after (the page's pixel offset alone let every height change above it shift the view). At the very
// top nothing is held: a new job appears on top there.
const VW_ANCH = '.agcard, .agjh, .job, .job > .jobh, .job details > summary, .job .runtask';
let vw_tap = null;
document.addEventListener('pointerdown', e => { const t = e.target instanceof Element && e.target.closest?.(VW_ANCH); vw_tap = t && $('#view')?.contains(t) ? t : null; }, true);
function vw_anchor(el) {
  if (!el || el.scrollTop <= 0 || S.route?.mod !== 'agents' || el.querySelector('.chview')) return null;
  const top = el.getBoundingClientRect().top, bot = top + el.clientHeight, inSight = r => r.height > 0 && r.bottom > top && r.top < bot;
  if (vw_tap?.isConnected && el.contains(vw_tap)) { const r = vw_tap.getBoundingClientRect(); if (inSight(r)) return [vw_tap, r.top]; }
  for (const n of el.querySelectorAll(VW_ANCH)) { const r = n.getBoundingClientRect(); if (r.height > 0 && r.top >= top && r.top < bot) return [n, r.top]; }
  return null;
}
// 2.924.0 (#5224): the one way a redraw keeps the reading place (product rule of 08.11.2026: the view moves only when the person makes
// it move). Before: the element with a key (fl_key: id / data-k / data-id / ...) at the top of what is in sight, not sticky
// / fixed, and its screen position; after: exactly that position again (a box that grew above it, a task inserted on top,
// a card that moved no longer push the text away under the finger). The browser's own anchoring (overflow-anchor: auto on
// #view) is not undone by a pixel value: only the difference that is left is corrected. No key in sight = the old pixel
// value; at the very top nothing is held (a new entry appears on top). The agents page prefers the row tapped last
// (vw_anchor). el = the scrolling element (#view, a panel, a chat box); null = nothing to keep.
const KR_POS = /^(sticky|fixed)$/;
const kr_sel = n => n.id ? `[id="${cssEsc(n.id)}"]` : (k => k ? `${n.nodeName.toLowerCase()}[${k}="${cssEsc(n.getAttribute(k))}"]` : null)(['data-k', 'data-id', 'data-cid', 'data-aid', 'data-jid', 'data-mid', 'data-key', 'data-section'].find(k => n.hasAttribute(k)));
function kr_mark(el) {
  if (!el || !(el.scrollTop > 0)) return null;
  const va = vw_anchor(el); if (va) return {n: va[0], top: va[1], sel: null};
  if (typeof document.elementFromPoint !== 'function') return null;
  const r = el.getBoundingClientRect(), h = Math.min(el.clientHeight, innerHeight - r.top);
  for (const fy of [0, 0.15, 0.3, 0.5]) for (const fx of [0.5, 0.15]) {
    const y = r.top + Math.max(2, h * fy), x = r.left + Math.max(8, el.clientWidth * fx);
    let n = document.elementFromPoint(x, y), hit = null;
    if (!n || !el.contains(n) || n === el) continue;
    for (; n && n !== el; n = n.parentElement) { if (KR_POS.test(getComputedStyle(n).position)) { hit = null; break; } if (!hit && fl_key(n) != null) hit = n; }
    if (hit && n === el) { const b = hit.getBoundingClientRect(); if (b.height > 0) return {n: hit, top: b.top, sel: kr_sel(hit)}; }
  }
  return null;
}
function kr_back(el, a, px) {
  if (!el) return;
  if (!(px > 0)) { if (el.scrollTop > 0) el.scrollTop = 0; return; }  // sprung-ok: the very top stays the top
  let n = a?.n;
  if (n && !n.isConnected) { try { n = a?.sel ? el.querySelector(a.sel) : null; } catch { n = null; } }  // the area was built anew (the detail panel)
  if (n && el.contains(n) && n.getClientRects().length) { const d = n.getBoundingClientRect().top - a.top; if (Math.abs(d) >= 0.5) el.scrollTop += d; return; }  // sprung-ok: back to the reading place
  if (Math.abs(el.scrollTop - px) >= 1) el.scrollTop = px;  // sprung-ok: no key in sight: the old pixel offset
}
function keepReading(el, fn) { const a = kr_mark(el), px = el?.scrollTop; try { return fn(); } finally { kr_back(el, a, px); } }
// the scrolling box around n (fl_set: a part drawn again keeps the place in its own box)
function kr_scroller(n) {
  for (; n && n !== document.body && n !== document.documentElement; n = n.parentElement) if (n.scrollHeight > n.clientHeight + 1 && /^(auto|scroll)$/.test(getComputedStyle(n).overflowY)) return n;
  return null;
}
function vw_anchorKeep(fn) { return keepReading($('#view'), fn); }  // 2.924.0 (#5224): the agents page's boxes through keepReading
function renderView() { FL.vlast = Date.now(); return td_rcRun(() => { const r = an_view(() => keepFocus($('#view'), renderView0));  // 2.46.1 (#1560): a view change / a new empty hint fades in
    rowRove(); rowMoreWatch(); agb_after(); vl_after(); vm_after(); td_lcSweep(); topw_sync(); topw_later(); return r; }); }  // 2.65.0 (#1825): vl_after = the window of a long list; 2.413.0 A (#3439): vm_after = a view entered again gets its place back (viewmem.js)  // 2.599.0 (#4814): topw_sync = the page's width for #top
// ---- 2.599.0 (#4814): the page reports its width once to #main: data-w = lesen | form | seite (the widths of :root,
// static/css/start-breite.css), eigen (an element with data-pw: its own centred block, e.g. notes / a knowledge page) or voll;
// --pw = that width in px, --pw-sb = the scrollbar of #view. static/css/start-kopf-4814.css gives #top the same middle and
// width (only from 1700 px: 1440 x 900, tablets and phones stay as they were). Read from the drawn page (its computed
// max-width), so start-breite.css stays the one place that assigns the widths. An element that is not in the middle = voll.
const TOPW_MIN = 1700;
function topw_sync() {
  const m = $('#main'), v = $('#view'); if (!m || !v) return;
  const wide = innerWidth >= TOPW_MIN && !isMobile();
  // below 1700 px nothing is measured: no forced layout on every redraw (the chats redraw often; --pw / --pw-sb only count from 1700 px)
  if (!wide) { if (m.dataset.w !== 'voll' || m.style.getPropertyValue('--pw') || m.style.getPropertyValue('--pw-sb')) { m.dataset.w = 'voll'; $('#top')?.classList.remove('topw'); m.style.removeProperty('--pw'); m.style.removeProperty('--pw-sb'); topw_watch(null); } return; }
  let w = 'voll', px = 0;
  {
    const rs = getComputedStyle(document.documentElement), rem = parseFloat(rs.fontSize) || 16;
    const named = new Map(['lesen', 'form', 'seite'].map(k => [Math.round(parseFloat(rs.getPropertyValue('--w-' + k)) * rem), k]).filter(([n]) => n > 0));  // 2.757.0 (#5309): 'none' was NaN and matched any element
    const seite = named.has(Math.round(parseFloat(rs.getPropertyValue('--w-seite')) * rem)) ? null : topw_seite();  // --w-seite none (#4840): known by its rules
    const vr = v.getBoundingClientRect(), vs = getComputedStyle(v), l0 = vr.left + parseFloat(vs.paddingLeft), r0 = vr.left + v.clientWidth - parseFloat(vs.paddingRight);
    const mid = e => { const r = e.getBoundingClientRect(); return r.width > 0 && Math.abs((r.left - l0) - (r0 - r.right)) < 2; };
    const own = v.querySelector('[data-pw]');
    let hit = null, key = '';
    if (own) { hit = own; key = 'eigen'; }
    else for (let d = 0, lv = [...v.children]; d < 3 && !hit && lv.length; d++) {
      for (const e of lv) { const k = named.get(Math.round(parseFloat(getComputedStyle(e).maxWidth))) || (seite && seite.some(x => topw_is(e, x)) ? 'seite' : ''); if (k) { hit = e; key = k; break; } }
      lv = lv.flatMap(e => [...e.children]).slice(0, 80);
    }
    topw_watch(hit);
    const mw = hit ? parseFloat(getComputedStyle(hit).maxWidth) : NaN;
    if (hit && (mw > 0 || key === 'seite') && mid(hit)) { w = key === 'eigen' ? named.get(Math.round(mw)) || 'eigen' : key; px = mw > 0 ? mw : 0; }  // seite without a limit: no --pw, #top = the padding of #view
  }
  if (m.dataset.w !== w) m.dataset.w = w;
  $('#top')?.classList.toggle('topw', w !== 'voll');  // the class on #top itself: its padding follows at once (no wait for an attribute two levels up)
  const pw = px ? Math.round(px) + 'px' : '', sb = Math.max(0, v.offsetWidth - v.clientWidth) + 'px';
  if (m.style.getPropertyValue('--pw') !== pw) { if (pw) m.style.setProperty('--pw', pw); else m.style.removeProperty('--pw'); }
  if (m.style.getPropertyValue('--pw-sb') !== sb) m.style.setProperty('--pw-sb', sb);
}
// 2.757.0 (#5309): --w-seite is none since 2.583 (#4840, lists full width): a computed max-width 'none' cannot tell a list
// (seite) from a board (voll), so the selectors that give an element max-width var(--w-seite) are read from the style sheets
// (cached until a sheet or rule more arrives; rules of a media query only while it applies)
let topw_selc = [], topw_selk = '';
function topw_seite() {
  const sh = [...document.styleSheets], rules = s => { try { return s.cssRules; } catch { return null; } };
  const k = sh.length + ':' + sh.reduce((a, s) => a + (rules(s)?.length || 0), 0) + ':' + innerWidth;
  if (k === topw_selk) return topw_selc;
  const out = [];
  const walk = list => { for (const r of list || []) {
    if (r.selectorText && /var\(--w-seite\)/.test(r.style?.getPropertyValue('max-width') || '') && topw_is(document.documentElement, r.selectorText) !== null) out.push(r.selectorText);
    if (r.cssRules && (!r.media || matchMedia(r.media.mediaText).matches)) walk(r.cssRules);
  } };
  for (const s of sh) walk(rules(s));
  topw_selk = k; topw_selc = out;
  return topw_selc;
}
const topw_is = (e, sel) => { try { return e.matches(sel); } catch { return null; } };  // null = a selector matches() cannot read (a pseudo-element)
let topw_raf = 0;
// the measured element changes its size later (its width switched, a style that arrives after the render): measure again
let topw_ro = null, topw_el = null;
function topw_watch(el) {
  if (el === topw_el || typeof ResizeObserver !== 'function') return;
  topw_ro ||= new ResizeObserver(() => topw_later());
  if (topw_el) topw_ro.unobserve(topw_el);
  topw_el = el; if (el) topw_ro.observe(el);
}
// once more after the next frame: a part of the page drawn later (a page loaded, a patched view, a menu's choice) counts too
const topw_later = () => { if (!topw_raf) topw_raf = requestAnimationFrame(() => { topw_raf = 0; topw_sync(); }); };
window.addEventListener('resize', () => { if (S.booted) topw_later(); });
function renderView0() {
  const m = S.route.mod, el = $('#view');
  lzGate();  // 2.369.2 (#3136): a view of the start set loads the lists it shows first (liveparts.js)
  // 2.12.2 (#451): the open phone chat is never rebuilt (that took the focus, closed the keyboard and jumped to the top):
  // it is patched in place
  if (m === 'agents' && S.route.agent && chatFull() && S.chat.aid === +S.route.agent && $('#view .chview')?.dataset.aid === String(S.chat.aid) && $('#chat-in')) { chatPatch(); agentLive(); renderMultiBar(); return; }
  const scroll = el.scrollTop, ctk = ct_scrollKeep(el), anc = FL.vsig === fl_sig() ? kr_mark(el) : null;  // 2.431.0 C (#3598); 2.758.0 (#5223): agents page; 2.924.0 (#5224): keepReading's mark, only in the same view
  const wbs = $('#wbody')?.scrollTop, tls = $('#tlscroll')?.scrollLeft, tlt = $('#tlscroll')?.scrollTop, wasRm = !!$('.tl.rm');
  const qi = $('#qinput'), qf = !!qi && document.activeElement === qi, qv = qi ? qi.value : '';  // the composer survives a re-render
  const tin = $('#view .ttlin'), tinF = !!tin && document.activeElement === tin;  // 2.0.2: inline title edit + section input too
  if (tin && S.ie) { S.ie.v = tin.value; S.ie.s = tin.selectionStart; S.ie.e = tin.selectionEnd; }
  const sai = $('#view .secadd-in'), saiF = !!sai && document.activeElement === sai;
  // 2.12.2 (#453 B2): any other focused field of the view (Kanban "+ Task", search, …) comes back with its text, caret and focus
  const fa = document.activeElement, fk = fa && el.contains(fa) && editFocused() && fa !== qi && fa !== tin && fa !== sai
    ? (fa.id ? () => document.getElementById(fa.id) : 'kadd' in fa.dataset ? () => [...el.querySelectorAll('[data-kadd]')].find(x => x.dataset.kadd === fa.dataset.kadd && x.dataset.swl === fa.dataset.swl) : null) : null;
  const fv = fk && fa.value, fs = fk && [fa.selectionStart, fa.selectionEnd];
  if (sai && S.secAdd) S.secAdd.v = sai.value;
  if (m !== 'cal') el.classList.remove('calfit');
  if (m === 'cal') { setHtml(el, viewCal()); requestAnimationFrame(calFit); }
  else if (m === 'matrix') setHtml(el, viewMatrix());
  else if (m === 'habits') setHtml(el, viewHabits());
  else if (m === 'pomo') { setHtml(el, mg_wrap(m, viewPomo())); loadPomoStats(); }
  else if (m === 'news') setHtml(el, viewNews() + msvvNewsHtml());  // 2.73.0 C (#661): + the other servers' news
  else if (m === 'stats') setHtml(el, mg_wrap(m, viewStats()));
  else if (m === 'time') setHtml(el, mg_wrap(m, viewTime()));  // 2.44.0 (#1187): mg_wrap = the area's tabs on top
  else if (m === 'overview') setHtml(el, viewOverview());
  else if (m === 'agents') setHtml(el, viewAgents());
  else if (m === 'team') { setHtml(el, viewTeam()); cf_view(); if (S.tc.fitUntil > Date.now()) teamFit(true); }  // 2.17.0 (#419); 2.17.2: a room opened by its address ends at the newest message
  else if (m === 'notes') setHtml(el, viewNotes());  // 2.17.0 (#442)
  else if (m === 'home') setHtml(el, viewHome());  // 2.17.0 (#475)
  else if (m === 'family') setHtml(el, mg_wrap(m, viewFamily()));  // 2.19.0 (#653)
  else if (m === 'contacts') setHtml(el, mg_wrap(m, viewContacts()));  // 2.21.0 (#658)
  else if (m === 'life') setHtml(el, mg_wrap(m, viewLife()));  // 2.22.0 (#663)
  else if (m === 'budget') setHtml(el, mg_wrap(m, viewBudget()));  // 2.72.0 (#1333)
  else if (m === 'feeds') setHtml(el, mg_wrap(m, viewFeeds()));  // 2.85.0 B (#1162)
  else if (m === 'bookmarks') setHtml(el, mg_wrap(m, viewBookmarks()));  // 2.97.0 A (#1950)
  else if (m === 'reading') setHtml(el, mg_wrap(m, viewReading()));  // 2.172.0 B (#2679)
  else if (m === 'review') setHtml(el, mg_wrap(m, viewReview()));
  else if (m === 'clients') setHtml(el, mg_wrap(m, viewClients()));  // 2.23.0 (#463)
  else if (m === 'workload') setHtml(el, viewWorkload());
  else if (m === 'tags') setHtml(el, viewTags());  // 2.53.0 (#446)
  else if (m === 'office') { if (typeof ofcPaint === 'function') ofcPaint(el); else setHtml(el, mg_wrap(m, viewOffice())); }  // 2.36.1 (#1021); 2.122.2 (#2327): keeps the old content while it reloads (office.js loads lazily: before that the stand-in)
  else if (m === 'wiki') setHtml(el, viewWiki());  // 2.49.0 (#1199)
  else if (m === 'sheets') setHtml(el, viewSheets());  // 2.89.0 (#1916)
  else if (m === 'ablage') setHtml(el, mg_wrap(m, viewAblage()));  // 2.48.0 (#1207)
  else if (m === 'docs') setHtml(el, mg_wrap(m, typeof viewDocs === 'function' ? viewDocs() : ''));  // 2.48.0 (#1111): docs.js
  else if (m === 'msv') setHtml(el, msvvViewList());  // 2.73.0 C (#661): a list on another server
  else if (S.route.key === 'search') setHtml(el, viewSearch());
  else if (S.route.key === 'done' || S.route.key === 'trash') setHtml(el, viewHistory());
  else if (S.route.key === 'archived') setHtml(el, viewArchived());
  else if (S.route.key === 'mine_wait') setHtml(el, viewMineWait());  // 2.392.0 D (#3369)
  else if (S.route.key === 'favorites') setHtml(el, viewFavPage());  // 2.441.0 (#3592)
  else if (S.route.key === 'help') setHtml(el, viewHelp());  // 2.1086.0 (#5820): the page "Help" (helpview.js)
  else if (S.route.key === 'steps') setHtml(el, viewSteps());  // 2.773.0 (#5250): the page "Recent steps" (undolist.js)
  else if (S.route.key === 'projects') setHtml(el, viewProjStart());  // 2.417.0 A (#3559)
  else if (isRoadmap()) setHtml(el, viewRoadmap());
  else if (isOverview()) setHtml(el, pcsOn(routeList()) ? viewProjCs() : viewProjOv());  // 2.7.1 (#410); 2.988.0 (#5651): the call sheets (callsheet.js)
  else if (isMindmap()) setHtml(el, vsegHtml(routeList()) + viewMindmap(routeList()));  // 2.49.0 (#1201)
  else if (isListCal()) { setHtml(el, lcal_view(routeList())); requestAnimationFrame(calFit); }  // 2.156.0 C (#2071): listcal.js (module calendar)
  else if (isKanban()) setHtml(el, viewKanban());
  else if (isTimeline()) setHtml(el, vsegHtml(routeList()) + viewTimeline(routeList().id));  // 2.13.0 (#453 A7)
  else if (moActive() && moBoard()) setHtml(el, mb_view());  // 2.156.0 C (#2072): My tasks as a board (mineboard.js)
  else setHtml(el, viewList());
  kr_back(el, anc, scroll); ctk();  // 2.924.0 (#5224): the reading place, not the pixel offset (keepReading)
  if (m === 'agents' && $('#view .chview')) { chatFit(); chatPatch(); } else { if (m === 'team') chatFit(); /* 2.446.0 (#3334) */ else document.body.classList.remove('kb-open'); if (S.chat && !$('#chat-msgs')) S.chat.seenAt = 0; }  /* the chat left (chs cont) */  // 2.12.2 (#451): a chat opens at its newest message; 2.380 F (#3381): a new box at its place / first new message (chs_restore), an old one stays
  if (S.ie) inlineEditMount(tinF);
  const sa2 = $('#view .secadd-in'); if (sa2 && S.secAdd) { sa2.value = S.secAdd.v || ''; if (saiF) sa2.focus({preventScroll: true}); }
  const q2 = $('#qinput'); if (q2 && qi && q2 !== qi) { q2.value = qv; if (qf) { q2.focus({preventScroll: true}); updateChips(q2); } }
  const wb = $('#wbody'); if (wb) cvw_scroll(wb, wbs);  // lazy-ok: #wbody = calview.js drew it; 2.828.0 (#5463): the first entry or 07:00, a new grid starts there
  const tl = $('#tlscroll');
  if (tl && isRoadmap()) { const keep = wasRm && !S.rmScrollReset; S.rmScrollReset = false; rmAfterRender(tl, keep ? tls : undefined, keep ? tlt : undefined); }
  else if (tl) { tl.scrollLeft = tls ?? Math.max(0, diffDays(S.tlStart, today()) - 2) * tlDW(); tlAfterRender(tl); }  // lazy-ok: 2.149.0 F (#2519): #tlscroll = timeline.js drew it
  else if (S.tlPick) S.tlPick = null;  // left the timeline: "Connect to…" ends
  renderMultiBar();
  const f2 = fk && fk();
  if (f2 && f2 !== fa && document.activeElement !== f2) { if (fv != null && 'value' in f2) f2.value = fv; f2.focus({preventScroll: true}); try { if (fs[0] != null) f2.setSelectionRange(fs[0], fs[1]); } catch { /* no caret */ } }
  if (S.route.key === 'search') { const i = $('#searchq'); if (i && document.activeElement !== i) { i.value = S.searchQ || ''; if (S.searchFocus) i.focus({preventScroll: true}); } S.searchFocus = false; }  // 2.655.0 (#5081); 2.940.0 (#5225): only on opening Search (phone and desktop), never back after a render - a field being typed in comes back above (f2)
}

// ------------------------------------------------------------------ render: task rows
// 2.407.0 A (#3513): an agent works on the task (its running job, t.working from the server): a pulsing dot with the name,
// the time of its last update and its last progress line, in the row / board card and the detail. It fades ttl seconds
// after that update here as on the server: agwArm redraws once the next one is due (no reload)
let agwT = 0, agwAt = 0;
function agwArm(end) {
  if (agwT && agwAt <= end) return;
  clearTimeout(agwT); agwAt = end;
  agwT = setTimeout(() => { agwT = 0; viewSafeRender(); if (S.sel && !$('#detail')?.contains(document.activeElement)) renderDetail(); },
    Math.min(Math.max(end - Date.now(), 0) + 1000, 2 ** 31 - 1));
}
function agwOf(t) {
  const w = t?.working, at = w ? Date.parse(w.at) : NaN, end = at + (w?.ttl || 900) * 1000;
  if (!w || !(end > Date.now())) return null;
  agwArm(end);
  return [w.name || w.agent || tr('Agent'), fmtTimeLoc(fmtHM(new Date(at))), w.text].filter(Boolean).join(' · ');
}
function agwChip(t) {
  const line = agwOf(t);
  return line ? `<span class="agw" title="${esc(line)}"><i class="agwd" aria-hidden="true"></i><span class="sr">${esc(tr('Agent working'))}: </span><span class="agwt">${esc(line)}</span></span>` : '';
}
function taskRow(t, opts = {}) {
  const kids = S.tasks.size ? children(t.id) : [];
  const openKids = kids.filter(k => k.status === 0).length;
  const treeKids = opts.dsx ? kids.length : openKids;  // 2.36.2 (#1136): completed subtasks stay below their parent too
  const meta = [];
  // desktop list views: date / list / assignee / tracked time also as right-aligned columns (.tcols);
  // the same items stay in the meta line with class m-col, which the phone layout shows instead
  // 2.14.0 (#425): a list with its own columns (opts.lc): those values sit in their columns (on narrow widths the first
  // two, the rest in the second line), what is not a column is not shown in the row
  const lc = !opts.trash && opts.lc ? opts.lc : null;
  const tc = !!opts.tcols && !opts.trash && !lc, mc = tc ? ' m-col' : '';
  const due = dueLabel(t);
  const lst = opts.showList && listById(t.list_id) ? lname(listById(t.list_id)) : '';
  let time = null, who = '';
  const rs = opts.trash ? () => true : rsy_on;  // 2.56.1 (#1799): the row's symbol level (rowsym.js RSY_SYMS); the trash shows all
  if (t.ticket_no && !opts.trash) { const kc = tkChip(t); if (kc) meta.push(kc); }  // 2.390.0 (#3353): the ticket key APP-12
  if (t.ttype && !opts.trash && ticketsOn(t.list_id) && rs('ttype')) meta.push(ttChip(t));  // 2.4.0 (#340)
  if (t.points && !opts.trash && spt_on(t.list_id)) meta.push(spt_chip(t));  // 2.60.0 (#1511): story points (own switch per list, not part of the row's symbol level)
  if (isMs(t)) { if (rs('ms')) meta.push(`<span class="msm${t.due ? ' sr' : ''}">${t.due ? esc(tr('Milestone')) : `<i class="msd" aria-hidden="true"></i>${esc(tr('Milestone without a date'))}`}</span>`); }  // 2.18.0 (#430)
  else if (t.milestone_id && !opts.trash && !opts.subRow && rs('ms')) meta.push(msChip(t));
  if (t.sprint_id) { const sc = spr_rowChip(t, opts); if (sc) meta.push(sc); }  // 2.60.0 (#343): only with "Show the sprint in the task row"
  if (isOcc(t) && famOn() && t.status === 0 && occWhat(t) && rs('occ')) meta.push(`<span class="occm">${ic('cake', 's')}${esc(occWhat(t))}</span>`);  // 2.19.0 (#653)
  if (t.fam?.kind === 'shop' && !opts.trash) { const q = famRowQty(t); if (q) meta.unshift(q); }  // 2.140.0 A (#2131): the amount of a shopping item
  if (t.rotation?.who?.length > 1 && famOn() && t.status === 0 && !opts.trash && rs('turns')) meta.push(`<span class="rotm" title="${esc(tr('Takes turns'))}">${ic('turns', 's')}<span class="sr">${esc(tr('Takes turns'))}</span></span>`);
  if (t.context) meta.push(`<span class="ctxm" title="${esc(tr('The main task of a subtask assigned to you: read-only, without notes, files and comments'))}">${ic('sub', 's')}${tr('Context')}</span>`);
  // 2.0.4 (#308): "Ready to start" only when the view has dependencies at all (see renderList); a button: tap / click
  // explains where it comes from (toast), without opening the task
  if (opts.next && !opts.depth && rs('blocked')) meta.push(`<button type="button" class="nxt" data-act="flow-why" title="${esc(tr(FLOW_WHY))}" aria-label="${esc(tr('Ready to start|flow') + ': ' + tr(FLOW_WHY))}">${ic('arrow', 's')}<span class="nxl">${tr('Ready to start|flow')}</span></button>`);
  if (!lc && t.blocked && t.status === 0 && !opts.trash && dFor(t) && rs('blocked')) meta.push(`<span class="blk" title="${esc(blockedTitle(t))}">${ic('lock', 's')}${tr('blocked')}</span>`);
  if (t.waiting_at && t.status === 0 && !opts.trash && rs('wait')) meta.push(waitChip(t));  // 2.1.0 (#335)
  if (opts.dwell && !opts.trash) { const d = dw_chip(t, opts.dwell); if (d) meta.push(d); }  // 2.410.0 B (#3515): time in the board column
  if (S.route.key === 'stale' && !opts.trash && staleOf(t) && rs('stale')) meta.push(staleChipHtml(t));  // 2.34.0 (#266)
  if (t.approval === 'pending' && t.status === 0 && !opts.trash) meta.push(approvalChip(t));  // 2.23.0 (#463)
  if (!opts.trash && t.working) { const w = agwChip(t); if (w) meta.push(w); }  // 2.407.0 A (#3513)
  if (t.pinned && !opts.trash && rs('pin')) meta.push(`<span class="pinm" title="${esc(tr('Pinned'))}">${ic('pin', 's')}<span class="sr">${tr('Pinned')}</span></span>`);
  if (t.also && !opts.trash && !opts.depth) { const m = ml_rowMark(t); if (m) meta.push(m); }  // 2.71.0 B (#1459): also in / from another list
  if (lst && !rs('list') && !(rsyProjToday() && !opts.trash)) { /* 2.56.1 (#1799): the list is switched off */ }
  else if (lst && moOwn() && !opts.depth && !moListCol()) meta.unshift(moSubHtml(t));  // 2.40.0 (#1344): My tasks, own order: "List › Section"; 2.569.0 (#4395): or the column
  else if (lst && lc?.includes('list')) { /* 2.750.0 (#4502): the column "Project" shows it */ }
  else if (lst && ws_isOrigin(listById(t.list_id))) meta.push(ws_originHtml(listById(t.list_id), lst, 'lst' + mc));  // 2.580.0 (#4821): under "All" + Bereich · Liste
  else if (lst) meta.push(`<span class="lst${mc}" title="${esc(lst)}">${licMark(listById(t.list_id), 'lsm')}${esc(lst)}</span>`);  // 2.36.2 (#1135)
  // 2.16.0 (#473): overdue is not only red: the alert icon + a word for screen readers
  // 2.31.0 (#1051): in Today a task due today carries no "Today" chip (the view says it), only its time
  const inDay = opts.inToday && t.due === today() && t.status === 0;
  const dueOn = rs('due') || dueClass(t) === 'over';  // 2.56.1 (#1799): overdue always shows
  if (t.due && !opts.checklist && !lc && !(inDay && !t.due_time) && dueOn) meta.push(`<span class="dt ${dueClass(t)}${mc}">${dueClass(t) === 'over' ? ic('alert', 's') + `<span class="sr">${tr('Overdue')}: </span>` : ic(inDay ? 'clock' : 'cal', 's')}${inDay ? esc(t.due_time) : due}</span>`);
  if (t.repeat && !opts.checklist && rs('repeat')) meta.push(`<span title="${esc(tr('Repeats'))}">${ic('repeat', 's')}<span class="sr">${tr('Repeats')}</span></span>`);
  if (rat_has(t) && !opts.checklist && rs('remind')) { const rtip = nagOf(t) ? tr('Repeat reminder') + ': ' + nagLabel(nagOf(t)) : tr('Reminder'); meta.push(`<span${nagOf(t) ? ' class="nagm"' : ''} title="${esc(rtip)}">${ic('bell', 's')}${nagOf(t) ? ic('repeat', 's') : ''}<span class="sr">${esc(rtip)}</span></span>`); }
  if (t.deadline && t.due && !opts.checklist && !opts.trash && (rs('deadline') || dueClass(t) === 'over')) meta.push(dlChip(t));  // 2.7.0 (#412)
  if (kids.length && !lc && rs('sub')) meta.push(`<span class="subc" title="${esc(tr('{0} of {1} subtasks done', kids.length - openKids, kids.length))}">${ic('sub', 's')}${kids.length - openKids}/${kids.length}<span class="sr"> ${esc(tr('{0} of {1} subtasks done', kids.length - openKids, kids.length))}</span></span>`);
  if ((t.content || (!('content' in t) && t.content_n)) && !opts.compact && rs('note')) meta.push(`<span title="${esc(tr('Has a description'))}">${ic('edit', 's')}<span class="sr">${tr('Has a description')}</span></span>`);  // 2.280.0 A (#3108): content_n = a long note not in the state; F: a note there (also emptied here) counts
  if (t.attachments?.length && rs('attach')) meta.push(`<span title="${esc(trn('{0} attachment', '{0} attachments', t.attachments.length))}">${ic('clip', 's')}${t.attachments.length}<span class="sr"> ${esc(trn('{0} attachment', '{0} attachments', t.attachments.length))}</span></span>`);
  if (t.url && rs('link')) meta.push(flkLink(t.url, 'lnk', `${ic(flkIs(t.url) ? 'folder' : 'link', 's')}${esc(urlHost(t.url))}`, true));  // 2.35.0 (#186): file links
  if (tFor(t) && t.id > 0) {
    const [ta, tm] = taskTime(t.id), live = S.timer && S.timer.task_id === t.id;
    if (ta >= 60 || live) {
      const tip = esc((live ? tr('Timer running') : ta - tm >= 60 ? tr('{0} in total, {1} by you', fmtDur(ta), fmtDur(tm)) : tr('Tracked: {0}', fmtDur(ta))) + tEstTip(t));
      const itx = esc(tIstEst(ta, t));  // 2.627.0 (#4503): "1:30 h / 2:00 h" = tracked / estimate (the duration)
      if (!lc && rs('tracked')) meta.push(`<span class="tchip ${live ? 'live' : ''}${mc}" data-tt="${t.id}" title="${tip}">${ic('clock', 's')}<b>${itx}</b></span>`);
      time = {live, tip, txt: itx};
    } else if (tEstMin(t)) time = {live: false, tip: esc(tr('Estimate') + ': ' + fmtH(tEstMin(t))), txt: esc(tIstEst(0, t))};  // 2.627.0 (#4503): the column shows the estimate before the first minute
  }
  if (planOf(t) && !opts.trash && rs('plan')) meta.push(`<span class="pchip" title="${esc(tr('Planned: {0}', planLabel(t)))}">${ic('clock', 's')}<b>${esc(planLabel(t, true))}</b></span>`);  // 2.11.0
  if (t.code?.prs?.length && !opts.trash && rs('code')) meta.push(codeChip(t));  // 2.2.0 (#271)
  if (t.code?.build && !opts.trash && rs('code')) { const h = buildRowHint(t); if (h) meta.push(h); }  // 2.151.0 A (#2558): stale / only on a branch
  if (!lc && !opts.trash && dv_chip(t)) meta.push(dv_chip(t));  // 2.392.2 (#3365): parked / waiting (a column shows it otherwise)
  if (t.comment_count && cmtOn() && rs('cmt')) meta.push(`<span class="cmc ${t.unread ? 'unread' : ''}" title="${esc(t.unread ? trn('{0} new comment', '{0} new comments', t.unread) : trn('{0} comment', '{0} comments', t.comment_count))}">${ic('comment', 's')}${t.comment_count}</span>`);
  if (t.approvals_open) meta.push(`<span class="apvc" title="${esc(apvCount(t.approvals_open))}">${ic('lock', 's')}${t.approvals_open}<span class="sr"> ${esc(apvCount(t.approvals_open))}</span></span>`);  // 2.41.0 (#1383): open approval cards in its comments
  const lcFb = !!lc && !opts.vc && !colCfg(t.list_id);
  const ac = !lc && !opts.trash && t.id > 0 && acolOn(t.list_id) && pz_on(t.list_id, 'who');  // 1.10.0: assignee column (own cell, click = assign); 2.412.0 (#3552): the property
  if (ac) who = whoCell(t);
  // 2.750.0 (#4502): a list without its own columns (lcFallback) keeps in the second line what its default columns leave out, as before
  // (the hidden assignee column: the picture; sorted by Created: the date)
  else if (lc && !(lcFb && !lc.includes('who'))) { /* 2.14.0: the assignee is a column or not shown */ }
  else if (t.assignee_group_id && collab()) {  // 2.10.0 (#441): assigned to a group
    const gc = grpChip(t);
    if (rs('person')) meta.push(gc);
    if (tc) who = gc;
  } else if (t.assignee_id && collab()) {
    const name = personName(t.list_id, t.assignee_id), cls = `who ${S.me && t.assignee_id === S.me.id ? 'me' : ''}`, tip = esc(tr('Assigned to {0}', name || '?'));
    const pv = isTouch() ? av : avBtn;  // 2.7.2 (#418): the picture opens the person card (touch: the row opens the task)
    if (rs('person')) meta.push(pv(t.assignee_id, name, cls + mc, `title="${tip}"`));
    if (tc) who = pv(t.assignee_id, name, cls, `title="${tip}"`);
  }
  if (!opts.cols && !opts.trash && !lc && rs('fields')) for (const f of fieldsOf(t.list_id).filter(x => x.pinned)) { const c = fieldChip(f, t.fields?.[f.id], t.list_id); if (c) meta.push(c); }
  if (!lc && rs('tags')) for (const g of t.ltags || []) meta.push(ltagChip(g, t.list_id));
  if (!lc && rs('tags')) for (const g of t.tags) meta.push(ptagChip(g, t.list_id));
  // 2.0.8 (#319): sorted by "Created": a small creation date on the row
  if ((!lc || lcFb && !lc.includes('created')) && !opts.trash && !opts.checklist && t.created_at && opts.crd && rs('created')) meta.push(`<span class="crd" title="${esc(tr('Created {0}', fmtWhen(t.created_at)))}">${ic('plus', 's')}${dayLabel(ds(new Date(t.created_at)))}</span>`);
  if (opts.trash) meta.push(`<span>${trh('deleted {0}', dayLabel(t.deleted_at.slice(0, 10)))}</span>`);
  if (opts.trash) { const l = ttpLeft(t); if (l != null) meta.push(`<span class="ttpleft">${esc(l ? trn('{0} day left', '{0} days left', l) : tr('deleted soon'))}</span>`); }  // 2.116.0 A (#2063)
  const msvb = msvvSelfBadge(opts); if (msvb) meta.unshift(msvb);  // 2.73.0 C (#661): merged views, a server linked
  if (opts.trash && t.keep) meta.push(`<span class="tkeep" title="${esc(tr('Only the project owner can delete it permanently'))}">${ic('lock', 's')}${tr('stays')}</span>`);  // 2.0.5
  // 2.8.0 (#434): the status glyph (circle; priority = its colour; an agent working on it = an open arc + dot) and, in
  // lists with tickets, the ticket number in a mono gutter
  const work = t.status === 0 && t.id > 0 && ((S.agents || []).some(a => a.enabled && a.status === 'working' && a.status_task === t.id) || !!agwOf(t));  // 2.407.0 A (#3513): + a working job
  const chk = (t.status === 2 ? 'on' : t.status === -1 ? 'wont' : 'p' + (opts.checklist ? 0 : t.priority)) + (work ? ' work' : '') + (isMs(t) ? ' ms' : '');
  let lcH = '';
  if (lc) {  // 2.14.0 (#425): the cells in the list's order; a cell the width has no room for shows in the second line
    // #3506: in a default layout (lcFallback, the collected views without an own choice) the due cell follows the symbol level too:
    // switched off, only an overdue date shows (as the row did, dueOn)
    const lcDef = opts.vc ? !S.settings?.view_cols : lcFb;
    const cells = lc.filter(k => k !== 'id').map(k => [k, lcCell(k, t, {kids, openKids, time, checklist: opts.checklist, vc: opts.vc, inDay, dueOn: !lcDef || dueOn})]);
    lcH = `<div class="lcols" id="tc-${t.id}" data-act="open"${lcFit(lc)}>${cells.map(([k, c], i) => `<span class="lc ${lcCls(k)} ${lcOvf(i)}" data-k="${esc(k)}"${tcAttr(k, t)}>${c}</span>`).join('')}</div>`;  // 2.39.1 (#1327): tcAttr
    cells.forEach(([k, c], i) => { if (c && i >= 2) meta.push(`<span class="mlc ${lcOvf(i)}" data-lc="${esc(k)}">${c}</span>`); });
    meta.unshift(...cells.slice(0, 2).filter(([, c]) => c).map(([k, c]) => `<span class="mlc o0" data-lc="${esc(k)}">${c}</span>`));  // 2.290.0 C (#3163): the first two cells too, shown only in a narrow list on a computer (app.css), else hidden
  }
  // 2.31.0 (#1051): the number is part of the tap area (opens the task); phones show it in the meta line instead (.mid), so
  // titles with and without a number start at the same x
  // #3506 (CI red of 2.782.0): a collected view's columns (opts.vc) have no number column: the task's own list decides, as before #4502
  const gut = !opts.checklist && t.id > 0 && (lc && !opts.vc ? lc.includes('id') : (ticketsOn(t.list_id) || idsOn(t.list_id)) && rs('num') && pz_on(t.list_id, 'ticket')) ? `<span class="tgut" aria-label="${esc(tr('Ticket {0}', '#' + t.id))}"${opts.trash ? '' : ' data-act="open"'}>#${t.id}</span>` : '';
  if (gut) meta.unshift(`<span class="mid" aria-label="${esc(tr('Ticket {0}', '#' + t.id))}">#${t.id}</span>`);
  const collapsed = S.collapsed.has('t' + t.id);
  const ro = !opts.trash && !canEdit(t);
  const caret = opts.tree && treeKids ? `<button class="caret ${collapsed ? 'closed' : ''}" data-act="collapse" data-key="t${t.id}" aria-expanded="${!collapsed}" aria-label="${esc(trn('{0} subtask', '{0} subtasks', treeKids))}">${ic('chev', 's')}</button>` : '';
  const cols = tc ? `<div class="tcols" data-act="open">${timeOn() && (opts.tcols.list || mtTime(t.list_id)) && rs('tracked') ? `<span class="c-time ${time?.live ? 'live' : ''}" title="${time ? time.tip : ''}">${time ? time.txt : ''}</span>` : ''}${collab() && rs('person') ? `<span class="c-who">${who}</span>` : ''}${opts.tcols.list && rs('list') ? (lst && ws_isOrigin(listById(t.list_id)) ? ws_originHtml(listById(t.list_id), lst, 'c-list') /* 2.580.0 (#4821) */ : `<span class="c-list" title="${esc(lst)}"><span>${esc(lst)}</span></span>`) : ''}<span class="c-date ${dueClass(t)}" title="${esc(due)}">${t.start && t.start < t.due ? ic('timeline', 's rngi') : ''}<span class="cdt">${dueOn ? esc(inDay ? t.due_time || '' : dueLabel(t, false)) : ''}</span></span></div>` : '';
  let h = `<div class="trow ${t.priority && !opts.checklist ? 'pr' + t.priority : ''} ${opts.checklist ? 'ck' : ''} ${tc || lc ? 'hascols' : ''} ${lc ? 'haslc' : ''} ${t.status ? 'done' : ''} ${opts.depth ? 'sub d' + opts.depth : ''} ${opts.subRow ? 'subrow' : ''} ${S.sel === t.id ? 'sel' : ''} ${gut ? 'hasgut' : ''} ${S.kf === t.id && !opts.subRow ? 'kfocus' : ''} ${S.multi.has(t.id) ? 'msel' : ''} ${ro ? 'ro' : ''} ${opts.next && !opts.depth ? 'flownext' : ''}${lp_cls(t)}" data-id="${t.id}"${lp_attr(t) /* 2.53.0 (#1426): the list's colour as the card edge */} ${opts.drag !== false && !opts.trash && !ro && !isTouch() ? 'draggable="true"' : '' /* 2.655.0 (#5085): touch = the app's hold only */}>
    ${opts.trash ? `<span class="chk ${chk}">${t.status === 2 ? ic('check') : ''}</span>` : `<button class="chk ${chk}" data-act="toggle" role="checkbox" aria-checked="${t.status === 2}" aria-label="${esc(isMs(t) ? tr('Complete milestone: {0}', mdPlain(t.title)) : tr('Complete: {0}', mdPlain(t.title)))}" ${ro ? 'disabled' : ''}>${t.status === 2 ? ic('check') : t.status === -1 ? ic('x') : ''}</button>`}${gut}
    ${caret}
    <div class="tmain" data-act="${opts.trash ? '' : 'open'}">${opts.pic || '' /* 2.636.0 (#4565): the picture of a shot (shoot.js) */}<div class="ttl"${opts.trash ? '' : ` data-kt role="button" tabindex="-1" aria-describedby="${lc ? `tc-${t.id} ` : ''}tm-${t.id}"`}>${typeof le2u_locked === 'function' && le2u_locked(t) ? le2u_ttlHtml(t) : mdTitle(t.title) /* 2.64.1 (#1817): locked list, not decrypted */}${tlkIs(t) && !opts.trash && rs('blocked') ? `<span class="tlkr" role="img" title="${esc(tr('Locked'))}" aria-label="${esc(tr('Locked'))}">${ic('lock', 's')}</span>` : ''}${t.priority && !opts.checklist && !opts.trash && t.status === 0 && !(lc && lc.includes('prio')) ? prioMark(t.priority) : ''}</div><div class="meta" id="tm-${t.id}">${meta.join('')}</div></div>
    ${!opts.trash && !ro && t.id > 0 && !isTouch() ? `<button class="iconbtn rpin ${t.pinned ? 'on' : ''}" data-act="pin" title="${esc(t.pinned ? tr('Unpin') : tr('Pin'))}" aria-label="${esc(t.pinned ? tr('Unpin') : tr('Pin'))}" aria-pressed="${!!t.pinned}">${ic(t.pinned ? 'pinf' : 'pin', 's')}</button>` : ''}
    ${opts.cols ? `<div class="fcols" data-act="open">${opts.cols.map(f => `<span class="fcell t-${esc(f.type)}">${fieldCell(f, t.fields?.[f.id], t.list_id, t)}</span>`).join('')}</div>` : ''}
    ${cols}${lcH}
    ${ac ? `<span class="wcell">${who}</span>` : ''}
    ${opts.ckback && !ro ? `<button class="iconbtn ckback" data-act="toggle" title="${tr('Put back on the list')}" aria-label="${tr('Put back on the list')}">${ic('undo', 's')}</button>` : ''}
    ${opts.trash ? `<button class="iconbtn" data-act="restore" title="${tr('Restore')}">${ic('undo')}</button>${listById(t.list_id)?.role === 'owner' ? `<button class="iconbtn danger" data-act="purge" title="${tr('Delete permanently')}">${ic('x')}</button>` : ''}` : ''}
    ${S.multiMode && isTouch() && opts.drag !== false && !opts.trash && !ro && t.id > 0 ? `<span class="tgrip" title="${esc(tr('Drag to reorder'))}" aria-hidden="true">${ic('grip', 's')}</span>` : ''}
  </div>`;
  if (opts.tree && treeKids && !collapsed) h += kids.filter(k => k.status === 0 || opts.dsx).map(k => taskRow(k, {...opts, depth: (opts.depth || 0) + 1, showList: false, ...(k.status ? {drag: false} : {})})).join('');
  return h;
}
// ---- 1.10.0 assignee column: in a shared list every row shows its assignee's picture, or a dashed circle for nobody;
// whoever may change the whole list (owner, admin, member) assigns with a click. Desktop: a column (.tcols .c-who),
// phone: a compact cell at the end of the row (.wcell). Per list it can be hidden (list "…" menu, stored per device).
const acolOn = lid => { const l = listById(lid); return collab() && !!l && !!l.shared && LS.get('acol.' + lid, true) !== false; };
// 2.10.0 (#441): a task assigned to a group: its name with the group glyph (a button for members: "Take it")
const grpById = id => (S.groups || []).find(g => g.id === id);
const myGroup = gid => !!gid && (S.myGroups || []).includes(gid);
const grpName = gid => grpById(gid)?.name || tr('Group');
const listGroups = lid => (listById(lid)?.groups || []);
function grpChip(t) {
  const n = grpName(t.assignee_group_id), mine = myGroup(t.assignee_group_id), tip = esc(tr('Assigned to the group {0}: whoever has time takes it', n));
  return canAssign(t) || mine ? `<button type="button" class="gchip ${mine ? 'me' : ''}" data-act="assign" title="${tip}" aria-label="${tip}" aria-haspopup="menu">${fg_gico(t.assignee_group_id)}<span>${esc(n)}</span></button>`
    : `<span class="gchip" title="${tip}">${fg_gico(t.assignee_group_id)}<span>${esc(n)}</span></span>`;  // 2.46.0 (#1605): + its picture
}
async function takeTask(id) {
  const t = taskById(id); if (!t) return;
  const before = snapTask(t);
  let r; try { r = await api('POST', `/api/tasks/${id}/take`, {}); } catch { return; }
  S.tasks.set(id, {...t, ...r}); render();
  const e = histFields(tr('Took a task'), [[before, {id, assignee_id: r.assignee_id, assignee_group_id: null}, ['assignee_id', 'assignee_group_id']]]);
  histToast(tr('Taken: it is yours now'), e);
}
function whoCell(t) {
  if (t.assignee_group_id) return grpChip(t);
  const name = t.assignee_id ? personName(t.list_id, t.assignee_id) : '', me = !!S.me && t.assignee_id === S.me.id;
  const tip = t.assignee_id ? tr('Assigned to {0}', name || '?') : tr('Unassigned|nobody');
  // 2.6.0 (K11): nobody assigned = no icon in checklists and on subtasks; elsewhere the dashed circle only shows on hover /
  // keyboard focus (desktop) and not at all on touch screens (assign from the task panel or the task's menu there)
  if (!t.assignee_id && (listById(t.list_id)?.checklist || t.parent_id)) return '';  // 2.7.2: lists with completed at the bottom (shopping) too
  const inner = t.assignee_id ? av(t.assignee_id, name, `who ${me ? 'me' : ''}`) : `<span class="who none">${ic('user', 's')}</span>`;
  return canAssign(t) ? `<button type="button" class="whob${t.assignee_id ? '' : ' wnone'}" data-act="assign" title="${esc(tip + ' · ' + tr('Assign…'))}" aria-label="${esc(tip + ' · ' + tr('Assign…'))}" aria-haspopup="menu">${inner}</button>`
    : t.assignee_id ? `<span class="whob ro" title="${esc(tip)}">${avBtn(t.assignee_id, name, `who ${me ? 'me' : ''}`)}</span>` : '';  // 2.7.2 (#418)
}
async function assignMenu(anchor, id) {
  const t = taskById(id); if (!t) return;
  if (o3a_ovAssignable(listById(t.list_id)) && canAssign(t)) await o3a_orgsLoad();  // 2.83.0 (#1725): the organisation's people
  const take = myGroup(t.assignee_group_id) ? [{label: tr('Take it'), icon: 'check', cls: 'mtake', fn: () => takeTask(id)}] : [];  // 2.10.0 (#441)
  if (!canAssign(t)) { if (take.length) menu(anchor, take); else roToast(); return; }
  if (!take.length && tlkStop(t)) return;  // 2.36.0 (#1118): locked
  const set = uid => { if ((t.assignee_id || null) !== uid || t.assignee_group_id) { patchTask(id, {assignee_id: uid, ...(t.assignee_group_id ? {assignee_group_id: null} : {})}); ab2_warnAssign(uid, t); } };  // 2.50.0 (#1195): warn when away
  const setG = gid => { if (t.assignee_group_id !== gid) patchTask(id, {assignee_group_id: gid, ...(t.assignee_id ? {assignee_id: null} : {})}); };
  const cur = t.assignee_id ? personName(t.list_id, t.assignee_id) || personNameAny(t.assignee_id) : '';
  const gs = listGroups(t.list_id);
  menu(anchor, [...take, ...(take.length ? ['-'] : []), ...(t.assignee_id ? [{label: tr('Show {0}', cur || '?'), icon: 'user', cls: 'mshow', fn: () => personCard(anchor, t.assignee_id)}, '-'] : []),  // 2.7.2 (#418)
    {label: tr('Nobody'), icon: 'x', on: !t.assignee_id && !t.assignee_group_id, fn: () => set(null)}, '-',
    ...[...listPeople(listById(t.list_id)), ...o3a_ovPeople(listById(t.list_id))].filter(p => listById(t.list_id)?.agents_open !== false || !(p.agent || agentById(p.user_id)) || p.user_id === t.assignee_id).map(p => ({label: p.name + (S.me && p.user_id === S.me.id ? ' ' + tr('(me)') : '') + (p.role === 'participant' ? ' · ' + tr('Participant') : p.role === 'view' ? ' · ' + tr('Read-only') : p.role === 'reader' ? ' · ' + tr('Not joined') : ''),
      ...ac_mi(p.user_id), on: p.user_id === t.assignee_id, fn: () => set(p.user_id)})),  // 2.47.1 (#1721): + the person's colour
    ...(gs.length ? ['-', ...gs.map(g => ({label: g.name + ' · ' + tr('Group'), icon: 'users', on: g.group_id === t.assignee_group_id, fn: () => setG(g.group_id)}))] : [])], null, null, tr('Assign'));  // 2.354.0 C (#3013): the sheet gets a heading
}
// ---- custom fields: display (chips on the rows, columns, detail panel)
const numFmt = v => { const x = +v; return Number.isFinite(x) ? x.toLocaleString(LOCALE(), {maximumFractionDigits: 6}) : String(v); };
const selOpt = (f, v) => (f.options?.options || []).find(o => o.id === v);
function fieldText(f, v, lid) {
  if (v == null || v === '') return '';
  if (CFK_TYPES.includes(f.type)) return cfkText(f, v) || '';  // 2.156.0 B (#2069): cfkinds.js
  if (f.type === 'formula' && cfkFxErr(v)) return cfkFxErr(v);  // 2.156.0 B (#2070): "Division by 0"
  switch (f.type) {
    case 'number': case 'formula': return numFmt(v) + (f.options?.unit ? ' ' + f.options.unit : '');  // 2.43.0 (#1328): + formula
    case 'select': return selOpt(f, v)?.name || '';
    case 'date': return dayLabel(v);
    case 'checkbox': return v === '1' ? tr('yes') : '';
    case 'person': return personName(lid, +v) || '?';
    case 'url': return urlHost(v);
  }
  return String(v);
}
function fieldChip(f, v, lid) {
  if (CFK_TYPES.includes(f.type)) return cfkChip(f, v);  // 2.156.0 B (#2069)
  if (cfst_on(f)) return cfstChip(f, v, false);  // 2.410.0 A (#3514): a stage bar (cfstage.js)
  const txt = fieldText(f, v, lid); if (!txt) return '';
  const tip = esc(f.name + ': ' + (f.type === 'url' ? v : f.type === 'date' ? fmtDate(v) : txt));
  if (f.type === 'select') { const o = selOpt(f, v); return `<span class="fchip sel${lrSelFill(o)}" ${lrSelStyle(o)} title="${tip}">${esc(o.name)}</span>`; }
  if (f.type === 'checkbox') return `<span class="fchip" title="${tip}">${ic('check', 's')}${esc(f.name)}</span>`;
  if (f.type === 'person') return (isTouch() ? av : avBtn)(+v, txt, 'who', `title="${tip}"`);
  if (f.type === 'url') return flkLink(v, 'lnk', `${ic(flkIs(v) ? 'folder' : 'link', 's')}${esc(txt)}`, true);
  if (f.type === 'date') return `<span class="fchip ${v < today() ? 'over' : ''}" title="${tip}">${ic('cal', 's')}${esc(txt)}</span>`;
  return `<span class="fchip" title="${tip}">${f.type === 'number' ? `<i>${esc(f.name)}</i> ` : ''}${esc(txt.length > 40 ? txt.slice(0, 39) + '…' : txt)}</span>`;
}
function fieldCell(f, v, lid, t) {  // column view (desktop); 2.156.0 B (#2069): t = the task (stars to tap)
  if (CFK_TYPES.includes(f.type)) return cfkCell(f, v, t);
  if (cfst_on(f)) return cfstChip(f, v, true);  // 2.410.0 A (#3514)
  if (v == null || v === '') return '';
  if (f.type === 'select') { const o = selOpt(f, v); return o ? `<span class="fchip sel${lrSelFill(o)}" ${lrSelStyle(o)}>${esc(o.name)}</span>` : ''; }
  if (f.type === 'checkbox') return v === '1' ? ic('check', 's') : '';
  if (f.type === 'url') return flkLink(v, 'lnk', esc(urlHost(v)), true);
  return `<span title="${esc(fieldText(f, v, lid))}">${esc(fieldText(f, v, lid))}</span>`;
}
// ---- 2.156.0 B (#2069): the field types multiselect, currency, rating and task: how their values read (task rows, columns,
// detail panel) and the taps that change them; the pickers and the dialog parts load on demand (cfkinds.js, module cfkinds).
// A task link shows the title only when the person may see the task: from the own state, else asked from the server
// (/api/fields/task-refs), never guessed.
const CFK_TYPES = ['multiselect', 'currency', 'rating', 'task'];
const cfk_ids = v => String(v || '').split(',').filter(Boolean);
const cfk_opts = (f, v) => cfk_ids(v).map(id => selOpt(f, id)).filter(Boolean);
const cfk_max = f => Math.min(10, Math.max(3, +(f.options?.max || 5)));
function cfk_money(v, cur) {
  const x = +v; if (!Number.isFinite(x)) return String(v ?? '');
  return curMoney(x, cur || 'EUR');  // 2.368.0 C (#2983): one money format (i18n.js curMoney: "$1,234.50", not "US$1,234.50")
}
// 2.156.0 B (#2070): the error values of a formula result
const CFK_FX_ERR = {'#div0': N_('Division by 0'), '#type': N_('Not a number')};
const cfkFxErr = v => typeof v === 'string' && v.startsWith('#') ? tr(CFK_FX_ERR[v] || 'Error') : '';

// ---- the linked task: {title, status} | null (not visible to me) | {off: true} (could not ask) | undefined (asking)
/** @type {Object<string, any>} */
const CFK_T = {};
let cfk_q = new Set();
const cfk_later = debounce(() => cfk_fetch(), 30);  // 2.599.0 (#4506): debounce instead of a clearTimeout / setTimeout pair
function cfk_task(id) {
  const t = taskById(+id);
  if (t && t.id > 0) return {title: t.title, status: t.status};
  if (id in CFK_T) return CFK_T[id];
  if (!cfk_q.has(+id)) { cfk_q.add(+id); cfk_later(); }
  return undefined;
}
async function cfk_fetch() {
  const ids = [...cfk_q]; cfk_q = new Set(); if (!ids.length) return;
  try {
    const j = await rawFetch('GET', '/api/fields/task-refs?ids=' + ids.join(','));
    for (const id of ids) CFK_T[id] = null;
    for (const x of j?.tasks || []) CFK_T[x.id] = {title: String(x.title || '').startsWith('e2e') ? '' : x.title, status: x.status};
  } catch { for (const id of ids) CFK_T[id] = {off: true}; }
  render(); if (S.sel) renderDetail();
}
const cfk_tname = (x, id) => x && !x.off && x.title ? x.title : tr('Task') + ' #' + id;
function cfk_taskText(v) {
  const x = cfk_task(v);
  return x === undefined ? '…' : x === null ? tr('Task not visible') : cfk_tname(x, v);
}

// ---- display: undefined = not one of these types (render.js fieldText / fieldChip / fieldCell go on)
function cfkText(f, v) {
  switch (f.type) {
    case 'multiselect': return cfk_opts(f, v).map(o => o.name).join(', ');
    case 'currency': return cfk_money(v, f.options?.currency);
    case 'rating': return tr('{0} of {1}', +v, cfk_max(f));
    case 'task': return cfk_taskText(v);
  }
  return undefined;
}
function cfk_stars(f, v, tid) {  // tid = may set it (tap sets, the same value again clears)
  const n = +v || 0, mx = cfk_max(f), lab = esc(f.name + ': ' + tr('{0} of {1}', n, mx));
  if (!tid) return `<span class="cfkrt" role="img" aria-label="${lab}" title="${lab}">${Array.from({length: mx}, (_, i) => `<i class="${i < n ? 'on' : ''}">${ic('star', 's')}</i>`).join('')}</span>`;
  return `<span class="cfkrt ed" role="group" aria-label="${lab}">${Array.from({length: mx}, (_, i) => `<button type="button" class="${i < n ? 'on' : ''}" data-cfkrt="${f.id}" data-tid="${tid}" data-n="${i + 1}" aria-pressed="${i + 1 === n}" aria-label="${esc(tr('{0} of {1}', i + 1, mx))}">${ic('star', 's')}</button>`).join('')}</span>`;
}
const cfk_selChip = o => `<span class="fchip sel${lrSelFill(o)}" ${lrSelStyle(o)}>${esc(o.name)}</span>`;
function cfk_msChips(f, v, most) {
  const os = cfk_opts(f, v), more = os.length - most;
  return os.slice(0, most).map(cfk_selChip).join('') + (more > 0 ? `<span class="fchip" title="${esc(os.slice(most).map(o => o.name).join(', '))}">+${more}</span>` : '');
}
function cfk_taskLink(v, cls) {
  const x = cfk_task(v), txt = cfk_taskText(v);
  if (!x || x.off) return `<span class="${cls} muted">${ic('link', 's')}${esc(txt)}</span>`;
  return `<button type="button" class="${cls} cfktl${x.status === 2 ? ' done' : ''}" data-cfkopen="${esc(String(v))}" title="${esc(txt)}">${ic('link', 's')}<span>${esc(txt)}</span></button>`;
}
function cfkChip(f, v, t) {  // the task row / card
  if (v == null || v === '') return '';
  const tip = esc(f.name + ': ' + (cfkText(f, v) || ''));
  if (f.type === 'multiselect') return `<span class="cfkms" title="${tip}">${cfk_msChips(f, v, 3)}</span>`;
  if (f.type === 'rating') return `<span class="fchip cfkr" title="${tip}">${cfk_stars(f, v, 0)}</span>`;
  if (f.type === 'task') return cfk_taskLink(v, 'fchip');
  return `<span class="fchip" title="${tip}"><i>${esc(f.name)}</i> ${esc(cfkText(f, v) || '')}</span>`;
}
function cfkCell(f, v, t) {  // a column (desktop); stars can be tapped right there
  if (f.type === 'rating') return cfk_stars(f, v, t && t.id > 0 && canEdit(t) && !isTouch() ? t.id : 0);
  if (v == null || v === '') return '';
  if (f.type === 'multiselect') return cfk_msChips(f, v, 2);
  if (f.type === 'task') return cfk_taskLink(v, 'cfktc');
  const s = cfkText(f, v) || '';
  return `<span title="${esc(s)}">${esc(s)}</span>`;
}

// ---- the detail panel (projects.js fieldEditor)
function cfkEditor(f, t, ro) {
  const v = t.fields?.[f.id] ?? '', id = `cf-${f.id}`, can = !ro && t.id > 0;
  if (f.type === 'currency') return `<span class="cfnum"><input id="${id}" data-cf="${f.id}" inputmode="decimal" value="${esc(v === '' ? '' : (+v).toLocaleString(LOCALE(), {useGrouping: false, maximumFractionDigits: 2}))}" ${ro ? 'readonly' : ''} placeholder="–"><span class="muted">${esc(f.options?.currency || 'EUR')}</span></span>`;
  if (f.type === 'rating') return `<span id="${id}">${cfk_stars(f, v, can ? t.id : 0)}</span>`;
  if (f.type === 'multiselect') {
    const on = new Set(cfk_ids(v));
    return `<span id="${id}" class="cfkmsed" role="group" aria-label="${esc(f.name)}">${(f.options?.options || []).map(o => `<button type="button" class="fchip sel${on.has(o.id) ? lrSelFill(o) + ' on' : ''}" ${on.has(o.id) ? lrSelStyle(o) : ''} data-cfkms="${f.id}" data-o="${esc(o.id)}" data-tid="${t.id}" aria-pressed="${on.has(o.id)}" ${can ? '' : 'disabled'}>${esc(o.name)}</button>`).join('')}</span>`;
  }
  if (f.type === 'task') return `<span id="${id}" class="cfktask">${v ? cfk_taskLink(v, 'cfktc') : '<span class="muted">–</span>'}${can ? `<button type="button" class="iconbtn" data-cfkpick="${f.id}" data-tid="${t.id}" title="${esc(tr('Select a task'))}" aria-label="${esc(tr('Select a task'))}">${ic('search', 's')}</button>${v ? `<button type="button" class="iconbtn" data-cfkclr="${f.id}" data-tid="${t.id}" title="${esc(tr('Empty the field'))}" aria-label="${esc(tr('Empty the field'))}">${ic('x', 's')}</button>` : ''}` : ''}</span>`;
  return '';
}
function cfk_put(tid, fid, v) {
  if (typeof tcSave === 'function') return tcSave(tid, fid, v);  // at once on screen, back on an error, Ctrl+Z
  return patchTask(tid, {fields: {[fid]: v}}).catch(() => {});
}
document.addEventListener('click', e => {
  const tg = /** @type {any} */ (e.target), b = tg.closest?.('[data-cfkrt],[data-cfkms],[data-cfkpick],[data-cfkclr],[data-cfkopen]'); if (!b) return;
  e.preventDefault(); e.stopImmediatePropagation();  // not the row's / cell's own click (tablecells.js listens on document too)
  if (b.dataset.cfkopen) { const id = +b.dataset.cfkopen; if (typeof openTaskById === 'function') openTaskById(id); else openDetail(id); return; }
  const t = taskById(+b.dataset.tid), f = fieldById(+(b.dataset.cfkrt || b.dataset.cfkms || b.dataset.cfkpick || b.dataset.cfkclr)); if (!t || !f) return;
  if (!canEdit(t)) { roToast(); return; }
  const v = t.fields?.[f.id] ?? null;
  if (b.dataset.cfkrt) { const n = +b.dataset.n; cfk_put(t.id, f.id, n === +(v || 0) ? null : String(n)); return; }
  if (b.dataset.cfkms) { const ids = new Set(cfk_ids(v)), o = b.dataset.o; ids.has(o) ? ids.delete(o) : ids.add(o); cfk_put(t.id, f.id, cfk_msVal(f, ids)); return; }
  if (b.dataset.cfkclr) { cfk_put(t.id, f.id, null); return; }
  cfkPick(t, f, x => cfk_put(t.id, f.id, x));
}, true);
const cfk_msVal = (f, ids) => (f.options?.options || []).filter(o => ids.has(o.id)).map(o => o.id).join(',') || null;

function cfkModalOpts(md, type) {
  if (type === 'currency') return {currency: /** @type {HTMLSelectElement} */ ($('#fd-cur', md)).value};
  if (type === 'rating') return {max: +/** @type {HTMLSelectElement} */ ($('#fd-rmax', md)).value};
  return {};
}

// ---- typed / pasted text (sheetgrid.js sgParse): {v} | {err} | undefined = not one of these types
function cfkParse(f, s) {
  if (f.type === 'currency') { const v = numIn(s.replace(/[^\d.,'\s-]/g, '')); return v !== '' && Number.isFinite(+v) ? {v: String(+v)} : {err: tr('Number expected')}; }
  if (f.type === 'rating') { const n = +s; return Number.isInteger(n) && n >= 0 && n <= cfk_max(f) ? {v: n ? String(n) : null} : {err: tr('Number expected')}; }
  if (f.type === 'multiselect') {
    const os = f.options?.options || [], names = s.split(/[,;]/).map(x => x.trim().toLowerCase()).filter(Boolean);
    const hit = names.map(n => os.find(o => o.name.toLowerCase() === n));
    return hit.every(Boolean) ? {v: cfk_msVal(f, new Set(hit.map(o => o.id)))} : {err: tr('Unknown option')};
  }
  if (f.type === 'task') { const m = s.match(/^#?(\d+)$/); return m ? {v: m[1]} : {err: tr('Task not found')}; }
  return undefined;
}
// ---- 2.136.0 (#2193): the bot figure (empty states, search, done, agents, welcome, offline, errors) instead of the heron
// of 2.14.0. The drawing of the design files (100 grid, the plate of the variants hell / dunkel): plate, body and eyes take
// the theme's colours (CSS .bot), the antenna is the accent. States: ruhig (calm), schaut (looks), erledigt (done, happy
// eyes), arbeitet (working, the antenna moves), wartet (waiting, antenna up), offline (calm eyes low, dim antenna).
// Motion is CSS only and gentle (a blink, a glance, a hop; a loop only for the agent states), none with reduced motion.
// Decorative: hidden from screen readers, the text next to it says what it means.
const BOT_EYES = {
  ruhig: ['M41 44V56', 'M59 50V50.1'], schaut: ['M48 42V54', 'M66 48V48.1'], arbeitet: ['M41 50V56', 'M59 53V53.1'],
  wartet: ['M41 39V51', 'M59 45V45.1'], erledigt: ['M36 52L40.5 46.5L45 52', 'M55 52L59.5 46.5L64 52'], offline: ['M41 50V56', 'M59 53V53.1'],
};
const botFig = (st = 'ruhig', cls = '') => {
  const e = BOT_EYES[st] || BOT_EYES.ruhig;
  if (!BOT_EYES[st]) st = 'ruhig';
  return `<svg class="bot b-${st}${cls ? ' ' + cls : ''}" viewBox="0 0 100 100" aria-hidden="true" focusable="false"><rect class="b-plate" width="100" height="100" rx="22.5"/>`
    + '<g transform="translate(50 50) scale(.9) translate(-50 -40)"><g class="b-hop"><path class="b-body" d="M50 22C74 22 78 26 78 50S74 78 50 78 22 74 22 50 26 22 50 22Z"/>'
    + `<g class="b-eyes" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="${e[0]}" stroke-width="6.5"/><path d="${e[1]}" stroke-width="${st === 'erledigt' ? 6.5 : 8.5}"/></g>`
    + `<path class="b-ant" d="${st === 'wartet' ? 'M58 1V15' : 'M58 6V15'}" stroke-width="7" stroke-linecap="round"/></g></g></svg>`;
};
// 2.223.0 B (#2822): the one empty-state pattern (thin symbol, one sentence, hint); the bot figure stays for 'all done' moments
// 2.891.0 (#5440): the one building block for "nothing here" and "loading" of the lists (symEmpty, botEmpty and o3c_empty
// of listhead.js are its short forms). size: 'big' = a page, 'sec' = a part of a page or dialog, 'row' = one line; each size
// keeps a fixed minimum height (app.css .es-*), so a part that goes from "loading" to "nothing" or to its rows does not jump.
// o = {icon | bot, title, sub, action (ready HTML, e.g. a button), size, cls}
function emptyState(o = {}) {
  const sz = ['row', 'sec'].includes(o.size) ? o.size : 'big', fig = o.bot ? botFig(o.bot) : o.icon ? ic(o.icon, sz === 'row' ? 's' : '') : '';
  return `<div class="empty ${o.bot ? 'hempty' : 'nempty'} eact es-${esc(sz)}${esc(o.cls ? ' ' + o.cls : '')}">${/*html-ok*/ fig/* the symbol */}<b>${esc(o.title || '')}</b>${o.sub ? `<span>${esc(o.sub)}</span>` : ''}${/*html-ok*/ o.action || ''/* ready HTML of the caller */}</div>`;
}
// the same place while it loads: a quiet line of the same minimum height (row keeps .mhint for the dialogs' parts)
const loadingHtml = (size = 'row') => `<div class="${size === 'row' ? 'muted mhint' : 'empty'} eload es-${esc(['row', 'sec'].includes(size) ? size : 'big')}" role="status">${esc(tr('Loading…'))}</div>`;
const symEmpty = (icon, title, sub = '') => emptyState({icon, title, sub});
const botEmpty = (st, title, sub = '') => emptyState({bot: st, title, sub});
// 2.891.0 (#5440): the same block when loading failed (says so instead of "nothing here", with "Try again") and when the
// person may not see the thing (lock, no button). For the lists here, the office (#5450) and the calendar (#5461): they
// only call these. o = {title, sub, size, cls, retry: function run by "Try again" (without it no button)}
const ES_RETRY = new Map(); let es_n = 0;
function errorState(o = {}) {
  let act = '';
  if (typeof o.retry === 'function') {
    const k = String(++es_n); ES_RETRY.set(k, o.retry);
    if (ES_RETRY.size > 40) ES_RETRY.delete(ES_RETRY.keys().next().value);  // old screens' buttons are gone long ago
    act = `<div class="eacts"><button type="button" class="btn" data-esretry="${esc(k)}">${ic('sync', 's')} ${esc(tr('Try again'))}</button></div>`;
  }
  return emptyState({icon: 'alert', title: o.title || tr('Could not be loaded'), size: o.size, cls: 'eerr' + (o.cls ? ' ' + o.cls : ''), action: act,
    sub: o.sub ?? (navigator.onLine === false ? tr('You are offline') : tr('Check the connection and try again.'))});
}
const noAccessState = (o = {}) => emptyState({icon: 'lock', title: o.title || tr('No access'), sub: o.sub ?? tr('Ask the owner to share it with you.'), size: o.size, cls: 'enoacc' + (o.cls ? ' ' + o.cls : ''), action: o.action});  // 2.1076.0 (#5450): + action (the office's "Submit receipt")
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-esretry]'), f = b && ES_RETRY.get(b.dataset.esretry);
  if (!f) return;
  ES_RETRY.delete(b.dataset.esretry); b.disabled = true; f();
});
// 2.40.0 (#1191): list columns from 600 px on (tablets, an unfolded Fold); isMobile() (< 900 px) stays for the rest of the app
const td_colsWide = () => td_rc('colw', () => !isMobile() || matchMedia('(min-width:600px)').matches);
const fieldCols = lid => td_colsWide() && !!LS.get('fcols.' + lid, false) && fieldsOf(lid).length > 0;
// ---- 2.14.0 (#425): list columns. One setting per list, the same for every member (owner / list admins change it in
// "Columns…"): which columns the rows show and in which order, custom fields and the task number included. null = the
// default layout (date, assignee, time as before; fields as chips). Narrow widths show the first two columns, the rest
// moves into the second line (classes o2 … o10: the cell's index needs at least that many columns of room).
const PRIO_NAMES = {1: N_('Low'), 3: N_('Medium'), 5: N_('High'), 7: N_('Urgent')};
const COLS = [['due', N_('Due')], ['prio', N_('Priority')], ['who', N_('Assignee')], ['tags', N_('Tags')], ['time', N_('Tracked time')],
  ['progress', N_('Subtasks')], ['deps', N_('Blocked by')], ['created', N_('Created')], ['delivery', N_('Delivery state')],  // 2.392.2 (#3365): delivery
  ['list', N_('Project')]];  // 2.750.0 (#4502): the task's project, only in collected views (vcChoices; a single list has no such column)
const COL_ICON = {due: 'cal', prio: 'flag', who: 'user', tags: 'tag', time: 'clock', progress: 'sub', deps: 'deps', created: 'plus', delivery: 'pause', list: 'list'};
function colChoices(l) {  // [key, name] of the columns this list can show (the task number separately)
  if (l?.virtual) return vcChoices();  // 2.750.0 (#4502): the collected views' own set
  // 2.412.0 (#3552): a property the project switched off (props.js) is no column either
  const ok = k => k === 'list' || !pz_on(l, PZ_COL[k] || '') ? false : k === 'who' ? collab() && !!l.shared : k === 'time' ? timeOn() && mtTime(l.id) : k === 'deps' ? depsOn() && isProject(l.id) : true;
  return [...COLS.filter(([k]) => ok(k)).map(([k, n]) => [k, tr(n)]), ...fieldsOf(l.id).map(f => ['f:' + f.id, f.name])];
}
const colCfg = lid => { const l = listById(lid); return l && Array.isArray(l.columns) ? l.columns : null; };
function listCols(l) {  // the list's own columns that apply right now, or null (default layout)
  const c = l && colCfg(l.id); if (!c) return null;
  const av = new Set([...(pz_on(l, 'ticket') ? ['id'] : []), ...colChoices(l).map(x => x[0])]);
  return c.filter(k => av.has(k));
}
function colDefault(l) {  // what the default layout shows: the starting point of "Columns…"
  const fs = fieldsOf(l.id), all = LS.get('fcols.' + l.id, false);
  const on = new Set(colChoices(l).map(x => x[0]));  // 2.412.0 (#3552): only what the project's properties show
  return [...((ticketsOn(l.id) || idsOn(l.id)) && pz_on(l, 'ticket') ? ['id'] : []), 'due', ...(acolOn(l.id) && on.has('who') ? ['who'] : []), ...(timeOn() && mtTime(l.id) && on.has('time') ? ['time'] : []),  // 2.41.0 (#1471): mtTime
    ...(all ? fs : fs.filter(f => f.pinned)).map(f => 'f:' + f.id), 'progress', ...(depsOn() && isProject(l.id) && on.has('deps') ? ['deps'] : []), ...(on.has('tags') ? ['tags'] : [])];
}
// 2.583.0 (#4840 Teil F): list rows like a table. From a 96rem wide list on (app.css) the text columns (tags, delivery state,
// text-like fields: class lcgw) share what the title leaves above about 40rem, each at most 15rem more than its standard
// width; number and date columns keep their width. lcFit = the standard widths (rem, LC_BASE, the same as app.css) plus the
// gaps of all shown columns and the number of growing ones, as variables for the column titles, the rows and the sum row
const LC_BASE = {due: 7.5, prio: 5.5, who: 2.75, tags: 9, time: 6, progress: 4.5, deps: 5.5, created: 6, delivery: 7, list: 8};  // 2.750.0 (#4502): + list (start-lccols-4502.css)
const LC_GROW_T = ['text', 'select', 'multiselect', 'person', 'url', 'task'];
const lcFtype = k => (S.fields || []).find(f => f.id === +k.slice(2))?.type || 'text';
const lcGrows = k => k === 'tags' || k === 'delivery' || (k.startsWith('f:') && LC_GROW_T.includes(lcFtype(k)));
function lcFit(lc) {
  const ks = (lc || []).filter(k => k !== 'id'), n = ks.filter(lcGrows).length; if (!n) return '';
  const fix = ks.reduce((a, k) => a + (k.startsWith('f:') ? (lcFtype(k) === 'checkbox' ? 3 : 7) : LC_BASE[k] || 7), 0) + .75 * (ks.length - 1);
  return ` style="--lcfix:${Math.round(fix * 100) / 100}rem;--lcn:${n}"`;
}
const lcCls = k => 'lc-' + (k.startsWith('f:') ? 'f t-' + lcFtype(k) : k) + (lcGrows(k) ? ' lcgw' : '');
// 2.583.0 (#4840 Teil F): + o13 / o16: on a very wide list the 11th to 16th column stay in the first line too (app.css)
const lcOvf = i => [2, 3, 5, 7, 10, 13, 16].filter(n => i >= n).map(n => 'o' + n).join(' ');
// ---- 2.750.0 (#4502): the column titles (sort by a click, the column menu) in every list view. A list without its own
// columns shows its default layout as columns (lcFallback = the starting point of "Columns…"; checklists, shopping lists
// and archived lists keep the plain rows). The collected views (Today, My tasks, filters, tags, folders, …) show the
// person's own choice (user setting view_cols: json list of keys, '' = vcDefault; the same in every collected view and on
// every device), with the column "Project"; their title row carries data-lid="v" (VC instead of a list)
// #3506 (CI red of 2.782.0): default columns nobody chose follow the row's symbol level (rowsym.js): "Calm" keeps the due
// date, "Important" its set (+ the project in Today / Tomorrow); a list's own columns and an own view_cols choice stay as chosen
const LC_RSY = {id: 'num', who: 'person', time: 'tracked', list: 'list', progress: 'sub', deps: 'blocked', tags: 'tags', created: 'created'};
const lcRsy = k => { const s = k.startsWith('f:') ? 'fields' : LC_RSY[k]; return !s || rsy_on(s) || (k === 'list' && rsyProjToday()); };
function lcFallback(l) {
  if (!l || l.checklist || l.family === 'shopping' || l.archived) return null;
  const c = colDefault(l).filter(k => (k === 'id' || colChoices(l).some(y => y[0] === k)) && lcRsy(k));
  return c.some(k => k !== 'id') ? c : null;  // nothing but the number: the plain rows
}
const VC = {id: 'v', virtual: true, name: ''};
const lcCtx = lid => lid === 'v' ? VC : listById(+lid);
const vcOk = k => k === 'who' ? collab() : k === 'time' ? timeOn() : k === 'deps' ? depsOn() : true;
const vcChoices = () => COLS.filter(([k]) => vcOk(k)).map(([k, n]) => [k, tr(n)]);
const vcDefault = () => ['due', 'who', 'time', 'list', 'progress', 'deps', 'tags'].filter(vcOk);
function vcCols() {
  let c = null; try { c = JSON.parse(S.settings?.view_cols || 'null'); } catch { c = null; }
  const av = new Set(vcChoices().map(x => x[0])), out = Array.isArray(c) ? c.filter(k => av.has(k)) : [];
  return out.length ? out : vcDefault().filter(lcRsy);  // #3506: the default follows the symbol level
}
async function vcSave(next, quiet) {  // next = the keys in their order, null = the default
  const prev = S.settings.view_cols || '', v = next && next.length ? JSON.stringify(next) : '';
  if (v === prev) return;
  S.settings.view_cols = v; render();
  try { await api('PATCH', '/api/settings', {view_cols: v}); } catch { S.settings.view_cols = prev; render(); return; }
  if (quiet) return;
  const go = x => async () => { await vcSave(x ? JSON.parse(x) : null, true); return {}; };
  offerUndo(tr('Shown columns saved'), histAdd({label: tr('Shown columns'), sett: true, undo: go(prev), redo: go(v)}));
}
function vcItems() {  // the shown columns of the collected views: tick on / off (the last one stays), back to the default
  const cur = vcCols();
  return [...vcChoices().map(([k, n]) => { const on = cur.includes(k); return {label: n, icon: COL_ICON[k], on, dis: on && cur.length < 2, fn: () => vcSave(on ? cur.filter(x => x !== k) : [...cur, k])}; }),
    '-', {label: tr('Default columns'), icon: 'undo', fn: () => vcSave(null)}];
}
document.addEventListener('click', e => { const b = e.target.closest?.('[data-act="vcols"]'); if (!b) return; e.preventDefault(); e.stopPropagation(); menu(b, [{label: tr('Shown columns'), dis: true, cls: 'mhead'}, '-', ...vcItems()]); }, true);
const colName = (l, k) => k === 'id' ? tr('Task number') : (colChoices(l).find(x => x[0] === k) || [0, ''])[1];
const colShort = (l, k) => k === 'time' ? tr('Tracked') : colName(l, k);  // the title row's label (narrow columns)
function lcCell(k, t, x) {
  switch (k) {
    case 'due': if (x.dueOn === false && dueClass(t) !== 'over') return '<span class="lcnil" aria-hidden="true">\u2013</span>';  // #3506: the level switched the due date off
      if (x.inDay) return t.due_time ? `<span class="dt today" title="${esc(dueLabel(t))}">${ic('clock', 's')}<span class="cdt">${esc(t.due_time)}</span></span>` : '<span class="lcnil" aria-hidden="true">\u2013</span>';  // 2.750.0 (#4502): Today shows the time only, like its date column did (#1051)
      return t.due && !x.checklist ? `<span class="dt ${dueClass(t)}" title="${esc(dueLabel(t))}">${dueClass(t) === 'over' ? ic('alert', 's') + `<span class="sr">${tr('Overdue')}: </span>` : ''}${t.start && t.start < t.due ? ic('timeline', 's rngi') : ''}<span class="cdt">${esc(dueLabel(t, false))}</span></span>` : '<span class="lcnil" aria-hidden="true">\u2013</span>';  // 2.87.9 (#1914): dim dash for an empty cell
    case 'prio': return t.priority && !x.checklist && PRIO_NAMES[t.priority] ? `<span class="lcp flag-${t.priority}" title="${esc(tr(PRIO_NAMES[t.priority]))}">${ic('flag', 's')}<span class="lbl">${esc(tr(PRIO_NAMES[t.priority]))}</span></span>` : '';
    case 'who': return t.id > 0 && collab() && (!x.vc || listById(t.list_id)?.shared) ? whoCell(t) : '';  // 2.750.0 (#4502): a collected view: only shared lists have someone to assign
    case 'list': { const l = listById(t.list_id); return !l ? '' : ws_isOrigin(l) ? ws_originHtml(l, lname(l), 'lst') /* 2.580.0 (#4821): under "All" workspace · project */ : `<span class="lst" title="${esc(lname(l))}">${licMark(l, 'lsm')}<span>${esc(lname(l))}</span></span>`; }  // 2.750.0 (#4502): like the project chip (.lst)
    case 'tags': return [...(t.ltags || []).map(g => ltagChip(g, t.list_id)), ...t.tags.map(g => ptagChip(g, t.list_id))].join('');
    case 'time': return x.time ? `<span class="tchip ${x.time.live ? 'live' : ''}" data-tt="${t.id}" title="${x.time.tip}">${ic('clock', 's')}<b>${x.time.txt}</b></span>` : '';
    case 'progress': { if (!x.kids.length) return ''; const n = tr('{0} of {1} subtasks done', x.kids.length - x.openKids, x.kids.length); return `<span class="subc" title="${esc(n)}">${ic('sub', 's')}${x.kids.length - x.openKids}/${x.kids.length}<span class="sr"> ${esc(n)}</span></span>`; }  // #3506: the screen reader hears what it counts, as the row's chip did
    case 'deps': return t.blocked && t.status === 0 && dFor(t) ? `<span class="blk" title="${esc(blockedTitle(t))}">${ic('lock', 's')}<span class="lbl">${tr('blocked')}</span></span>` : '';
    case 'delivery': return dv_cell(t);  // 2.392.2 (#3365)
    case 'created': return t.created_at ? `<span class="crd" title="${esc(tr('Created {0}', fmtWhen(t.created_at)))}">${ic('plus', 's')}${dayLabel(ds(new Date(t.created_at)))}</span>` : '';
  }
  if (k.startsWith('f:')) { const f = fieldsOf(t.list_id).find(y => y.id === +k.slice(2)); return f ? fxBudgetCell(f, t) || fieldCell(f, t.fields?.[f.id], t.list_id, t) : ''; }  // 2.410.0 (#3437): a budget = its subtasks' sum
  return '';
}
// "Columns…": tick what the rows show, order by dragging the handle or with the arrows (Alt+↑/↓ on the keyboard). Saved for
// the whole list (everyone sees the same); owner and list admins change it, everyone else sees it read-only.
function colModal(id) {
  const l = listById(id); if (!l) return;
  const may = canManage(l);
  let ch = colChoices(l), names = Object.fromEntries(ch);
  const start = listCols(l) || colDefault(l).filter(k => k === 'id' || names[k]);
  let num = start.includes('id');
  const on = new Set(start.filter(k => k !== 'id'));
  let order = [...start.filter(k => k !== 'id'), ...ch.map(x => x[0]).filter(k => !on.has(k))];
  const dis = may ? '' : 'disabled';
  const rowH = (k, i) => `<li class="colr ${on.has(k) ? 'on' : ''}" data-k="${esc(k)}">${may ? `<span class="colh" data-colh title="${esc(tr('Drag to reorder'))}" aria-hidden="true">${ic('grip', 's')}</span>` : ''}<label class="chkl"><input type="checkbox" data-colk="${esc(k)}" ${on.has(k) ? 'checked' : ''} ${dis}><span class="coln">${k.startsWith('f:') ? ic('sliders', 's') : ic(COL_ICON[k], 's')}<span>${esc(names[k])}</span></span></label>${may && k.startsWith('f:') ? tcFieldBtns(k, names[k]) : ''}${may ? `<button type="button" class="iconbtn colmv" data-colmv="-1" ${i ? '' : 'disabled'} title="${esc(tr('Move up'))}" aria-label="${esc(tr('Move up') + ': ' + names[k])}">${ic('chev', 's cup')}</button><button type="button" class="iconbtn colmv" data-colmv="1" ${i < order.length - 1 ? '' : 'disabled'} title="${esc(tr('Move down'))}" aria-label="${esc(tr('Move down') + ': ' + names[k])}">${ic('chev', 's')}</button>` : ''}</li>`;
  const md = modal(`<h3 id="col-t">${ic('columns', 's')}${tr('Shown fields')}</h3>
    <p class="muted coldesc">${esc(tr('The same for everyone in this project. Phones show the first two fields, the rest in the second line; tablets show as many columns as fit.'))}</p>
    ${may ? '' : `<p class="rohint">${ic('lock', 's')}${esc(tr('Only the owner and project admins can change the shown fields.'))}</p>`}
    <label class="chkl colnum"><input type="checkbox" id="col-num" ${num ? 'checked' : ''} ${dis}><span class="coln">${ic('hash', 's')}<span>${tr('Task number in front of the title')}</span></span></label>
    <ul class="colls" id="col-ls" aria-labelledby="col-t" tabindex="-1">${order.map(rowH).join('')}</ul>
    ${may ? `<div class="coladd"><button type="button" class="btn sm" data-colact="addfield">${ic('plus', 's')} ${tr('Add custom field')}</button></div>` : ''}
    <div class="foot">${may ? `<button type="button" class="btn" data-colact="reset" ${l.columns ? '' : 'disabled'} title="${esc(tr('Back to the default columns'))}">${tr('Default')}</button>` : ''}<span class="spacer"></span><button type="button" class="btn" data-colact="close">${may ? tr('Cancel') : tr('Close')}</button>${may ? `<button type="button" class="btn pri" data-colact="save">${tr('Save')}</button>` : ''}</div>`);
  md.classList.add('colmd');
  md.setAttribute('role', 'dialog'); md.setAttribute('aria-modal', 'true'); md.setAttribute('aria-labelledby', 'col-t');
  const ls = $('#col-ls', md), rowOf = k => [...ls.querySelectorAll('.colr')].find(r => r.dataset.k === k);
  const draw = focusK => {
    ls.innerHTML = order.map(rowH).join('');
    if (focusK) { const b = rowOf(focusK[0])?.querySelector(`[data-colmv="${focusK[1]}"]`); (b && !b.disabled ? b : rowOf(focusK[0])?.querySelector('input'))?.focus(); }
  };
  const move = (k, d) => { const i = order.indexOf(k), j = i + d; if (i < 0 || j < 0 || j >= order.length) return; order.splice(i, 1); order.splice(j, 0, k); draw([k, d]); };
  md.addEventListener('change', e => {
    const x = e.target;
    if (x.id === 'col-num') num = x.checked;
    else if (x.dataset.colk) { if (x.checked) on.add(x.dataset.colk); else on.delete(x.dataset.colk); x.closest('.colr')?.classList.toggle('on', x.checked); }
  });
  // 2.39.1 (#1327): add, change and delete custom fields right here; a new field is shown at once (saved as a column)
  const resync = (addK, focusK) => {
    ch = colChoices(l); names = Object.fromEntries(ch);
    order = [...order.filter(k => names[k]), ...ch.map(x => x[0]).filter(k => !order.includes(k))];
    for (const k of [...on]) if (!names[k]) on.delete(k);
    if (addK && names[addK]) on.add(addK);
    draw(focusK ? [focusK, 1] : null);
  };
  md.addEventListener('click', async e => {
    const mv = e.target.closest('[data-colmv]');
    if (mv) { move(mv.closest('.colr').dataset.k, +mv.dataset.colmv); return; }
    const fb = e.target.closest('[data-colfe],[data-colfd]');
    if (fb && may) { tcFieldAct(l, fb, resync); return; }
    const b = e.target.closest('[data-colact]'); if (!b) return;
    if (b.dataset.colact === 'addfield') { if (may) tcFieldAdd(l, resync); return; }
    if (b.dataset.colact === 'close') { md.remove(); return; }
    const next = b.dataset.colact === 'reset' ? null : [...(num ? ['id'] : []), ...order.filter(k => on.has(k))];
    md.remove();
    await colSave(id, next);
  });
  md.addEventListener('keydown', e => {  // Alt+↑ / Alt+↓ moves the focused row
    const r = e.target.closest?.('.colr');
    if (r && may && e.altKey && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) { e.preventDefault(); const k = r.dataset.k; move(k, e.key === 'ArrowUp' ? -1 : 1); rowOf(k)?.querySelector('input')?.focus(); }
  });
  // drag the handle (mouse, pen and touch): the row moves where the pointer crosses another row. The rows are only
  // moved in the DOM while dragging (a re-render would drop the handle and with it the pointer), the order is redrawn
  // when the pointer is let go
  ls.addEventListener('pointerdown', e => {
    const h = e.target.closest('[data-colh]'); if (!h || !may) return;
    e.preventDefault();
    const row = h.closest('.colr'), k = row.dataset.k;
    row.classList.add('drag');
    const mvH = ev => {
      const rows = [...ls.querySelectorAll('.colr')];
      const over = rows.find(r => { const b = r.getBoundingClientRect(); return r !== row && ev.clientY >= b.top && ev.clientY < b.bottom; });
      if (!over) return;
      const i = rows.indexOf(row), j = rows.indexOf(over);
      ls.insertBefore(row, j > i ? over.nextSibling : over);
      order = [...ls.querySelectorAll('.colr')].map(r => r.dataset.k);
    };
    const up = () => { document.removeEventListener('pointermove', mvH); document.removeEventListener('pointerup', up); document.removeEventListener('pointercancel', up); draw(); rowOf(k)?.querySelector('input')?.focus({preventScroll: true}); };
    document.addEventListener('pointermove', mvH);
    document.addEventListener('pointerup', up);
    document.addEventListener('pointercancel', up);
  });
  const prevFocus = document.activeElement;  // Esc / Cancel / Save: the focus goes back to where it came from
  onRemove(md, () => { try { if (prevFocus && prevFocus.isConnected) prevFocus.focus({preventScroll: true}); } catch { /* gone */ } });
  setTimeout(() => (may ? $('#col-num', md) : $('[data-colact="close"]', md))?.focus(), 30);
}
async function colSave(id, next, quiet) {
  const l = listById(id); if (!l) return;
  const prev = Array.isArray(l.columns) ? l.columns : null;
  if (JSON.stringify(prev) === JSON.stringify(next)) return;
  let r;  // 2.270.0 A (#3019): _prev: columns another device set meanwhile are not replaced by this (older) choice
  try { r = await optWrite(optSet(() => listById(id), {columns: next}), () => api('PATCH', '/api/lists/' + id, {columns: next, _prev: {columns: prev}})); } catch { return; }  // 2.41.2 (#1501): at once
  if (r?.conflicts?.length) { toast(tr('Changed elsewhere in the meantime')); await load(); render(); return; }
  if (quiet) return;
  const go = v => async () => { await colSave(id, v, true); return {}; };
  const e = histAdd({label: tr('Shown fields of {0}', qn(lname(l))), undo: go(prev), redo: go(next), lids: [id]});
  histToast(next ? tr('Shown fields saved for everyone in the project') : tr('Default columns'), e);
}
function lcHead(l, lc) {  // the column titles above the rows (wide layouts)
  const ks = lc.filter(k => k !== 'id');
  if (!ks.length) return '';
  lcwApply(l.id);
  // 2.16.0 (#634): a grip at the right edge of each column title: drag = the column's width on this device (per list),
  // double-click = its standard width; for the keyboard a separator (← → 0.5 rem, Enter = standard)
  // 2.31.0 (#354): each title is a button: click / Enter / Space sorts by the column, again = the other way round, a third
  // time = back to the list's sort (sortSet ''). The sorted column carries aria-sort and an arrow; a table with one row of
  // column headers for screen readers (the wrapper is display:contents, the layout stays the flex row)
  const cur = sortMode();
  return `<div class="lchead" data-lid="${l.id}"${lcFit(lc)} role="table" aria-label="${esc(tr('Column titles'))}"><div class="lcrow" role="row"><span class="spacer" role="presentation"></span>${ks.map((k, i) => { const n = colName(l, k), p = colSorts(k), on = p.includes(cur), dir = on ? sortDir(cur) : '';
    const tip = on ? (cur === p[0] ? tr('Sorted by {0}. Click again to reverse the direction', n) : tr('Sorted by {0}. Click again to go back to the project sort', n)) : tr('Sort by {0}', n);
    return `<span class="lc ${lcCls(k)} ${lcOvf(i)}${on ? ' sorted' : ''}" data-k="${esc(k)}" role="columnheader"${on ? ` aria-sort="${dir}"` : ''} title="${esc(n)}"><button type="button" class="lcs" data-colsort="${esc(k)}" title="${esc(tip)}" aria-label="${esc(n)}"><span class="lcn" aria-hidden="true">${k === 'who' || k === 'prio' ? ic(COL_ICON[k], 's') : `<span>${esc(colShort(l, k))}</span>`}</span>${on ? `<span class="lcsa" aria-hidden="true">${ic('chev', dir === 'ascending' ? 's cup' : 's')}</span>` : ''}</button>${isTouch() ? '' : `<button type="button" class="lcmb" data-colmenu="${esc(k)}" tabindex="-1" aria-haspopup="menu" title="${esc(tr('Column menu: {0}', n))}" aria-label="${esc(tr('Column menu: {0}', n))}">${ic('chev', 's')}</button>`}${isTouch() ? '' : `<i class="lcg" data-lcg="${esc(k)}" title="${esc(tr('Drag the column width · double-click = default width'))}" role="separator" aria-orientation="vertical" tabindex="0" aria-label="${esc(tr('Width of the column {0}', n))}" ${lcwGet(l.id)[k] ? `aria-valuenow="${lcwGet(l.id)[k]}" aria-valuetext="${esc(tr('{0} rem', String(lcwGet(l.id)[k])))}"` : `aria-valuenow="7" aria-valuetext="${esc(tr('Default width'))}"`} aria-valuemin="${LCW_MIN}" aria-valuemax="${LCW_MAX}"></i>`}</span>`; }).join('')}</div></div>`;
}
// 2.427.0 B (#3551): phones / narrow containers (where .lchead is hidden): the shown fields as a swipeable strip of names
// above the rows (the sorted one with its arrow), a tap opens the column menu (lcMenu) at the name; "Fields" at the end
// opens "Shown fields" (colModal). No widths here; list view only, not in an archived list or the overview
function lcBar(l, lc) {
  const ks = lc.filter(k => k !== 'id');
  if (!ks.length || l.archived || isOverview()) return '';
  const cur = sortMode();
  return `<div class="lcbar" data-lid="${l.id}" role="toolbar" aria-label="${esc(tr('Shown fields'))}"><div class="lcbs" data-hscroll>${ks.map(k => { const n = colName(l, k), on = colSorts(k).includes(cur), dir = on ? sortDir(cur) : '';
    return `<button type="button" class="lcbn${on ? ' sorted' : ''}" data-k="${esc(k)}" aria-haspopup="menu" title="${esc(tr('Column menu: {0}', n))}"><span>${esc(n)}</span>${on ? `<span class="lcsa" aria-hidden="true">${ic('chev', dir === 'ascending' ? 's cup' : 's')}</span>` : ''}</button>`; }).join('')}</div>${l.virtual ? `<button type="button" class="lcbf" data-act="vcols" aria-haspopup="menu" title="${esc(tr('Shown columns'))}">${ic('columns', 's')}<span>${esc(tr('Columns'))}</span></button>` /* 2.750.0 (#4502) */ : `<button type="button" class="lcbf" data-act="cols" data-id="${l.id}" aria-haspopup="dialog" title="${esc(tr('Shown fields…'))}">${ic('columns', 's')}<span>${esc(tr('Fields'))}</span></button>`}</div>`;
}
document.addEventListener('click', e => { const b = e.target.closest?.('.lcbar .lcbn[data-k]'); if (!b) return; e.preventDefault(); lcMenu(b); });
// 2.828.0 (#5443): the strip scrolls sideways; a fade at each edge where more names wait (classes fl / fr on .lcbs), so a
// name the edge cuts reads as "more this way" (a phone at 360 px showed "Un|" without any hint)
function lcbEdge(s) { const m = s.scrollWidth - s.clientWidth; s.classList.toggle('fl', m > 1 && s.scrollLeft > 1); s.classList.toggle('fr', m > 1 && s.scrollLeft < m - 1); }
document.addEventListener('scroll', e => { if (e.target?.classList?.contains('lcbs')) lcbEdge(e.target); }, true);
if (typeof ResizeObserver !== 'undefined') domReady(() => {
  const v = $('#view'); if (!v) return;
  let q = 0; const all = () => { if (!q) q = requestAnimationFrame(() => { q = 0; v.querySelectorAll('.lcbar .lcbs').forEach(lcbEdge); }); };
  new MutationObserver(all).observe(v, {childList: true, subtree: true}); new ResizeObserver(all).observe(v);
});
// 2.31.0 (#354): first click = the column's natural order, second = reversed, third = the list's sort again
document.addEventListener('click', e => {
  const b = e.target.closest?.('.lchead [data-colsort]'); if (!b) return;
  const p = colSorts(b.dataset.colsort), cur = sortMode(), bk = 'sortback.' + S.route.key, l = routeList();
  // the sort before the first click (the stored one, '' = the default) comes back with the third
  if (LS.get(bk, null) == null) LS.set(bk, (l && !l.is_inbox && canManage(l) ? l.sort_mode : LS.get('sort2.' + S.route.key, '')) || '');
  if (cur === p[1]) { const back = LS.get(bk, ''); LS.del(bk); sortSet(back === p[1] ? '' : back); return; }
  sortSet(cur === p[0] ? p[1] : p[0]);
  // review 2.31: a list admin's click changes the shared sort; say so once per session
  if (l && l.shared && !l.is_inbox && canManage(l) && !sortSharedHint) { sortSharedHint = true; toast(tr('Sorted for everyone in this project')); }
});
let sortSharedHint = false;
// 2.31.0 (#354): right-click on a column title: both directions, hide the column (owner / list admins), "Shown fields…"
document.addEventListener('contextmenu', e => {
  const c = e.target.closest?.('.lchead .lc[data-k]'); if (!c || e.shiftKey) return;
  if (!lcCtx(c.closest('.lchead').dataset.lid)) return;  // 2.750.0 (#4502): or a collected view
  e.preventDefault(); lcMenu(c);
});
// 2.39.1 (#1327): the same menu from the small arrow in the column title (hover / focus)
document.addEventListener('click', e => { const b = e.target.closest?.('.lchead [data-colmenu]'); if (!b) return; e.preventDefault(); e.stopPropagation(); lcMenu(b.closest('.lc')); }, true);
function lcMenu(c) {
  const l = lcCtx(c.closest('.lchead,.lcbar').dataset.lid); if (!l) return;  // 2.427.0 B (#3551): + the phone strip; 2.750.0 (#4502): lcCtx
  const k = c.dataset.k, p = colSorts(k), cur = sortMode(), lc = l.virtual ? vcCols() : listCols(l) || lcFallback(l) || [];
  const dirName = m => sortDir(m) === 'ascending' ? tr('Sort ascending') : tr('Sort descending');
  const pick = m => { LS.del('sortback.' + S.route.key); sortSet(m); };
  menu(c, [{label: colName(l, k), dis: true, cls: 'mhead'}, '-',
    ...[p[0], p[1]].map(m => ({label: dirName(m), icon: 'sort', on: cur === m, fn: () => pick(m)})),
    ...(l.virtual ? [] : sgColMenu(l, k, c)),  // 2.43.0 (#1331): filter by a value of the column
    // 2.750.0 (#4502): a collected view: the person's own columns (the last one stays)
    '-', ...(l.virtual ? (lc.length > 1 ? [{label: tr('Hide column'), icon: 'eyeoff', fn: () => vcSave(lc.filter(x => x !== k))}] : []) : canManage(l) ? [{label: tr('Hide column'), icon: 'eyeoff', fn: () => colSave(l.id, lc.filter(x => x !== k))}] : []),
    l.virtual ? {label: tr('Shown columns'), icon: 'columns', more: vcItems()} : {label: tr('Shown fields…'), icon: 'columns', fn: () => colModal(l.id)}]);
}
// 2.31.0: a focusable separator needs a value (axe aria-required-attr): the standard width says 7 rem, read out as "Standard width"
// ---- 2.16.0 (#634): column widths per device and list (localStorage lcw.<list>: {key: rem}), applied as one style sheet
// 2.742.0 (#4857): per person on every device (the user setting col_widths, accounts/colwidths.py; the former localStorage
// lcw.<list> of this device is read until the list's first drag moves it to the account) and without an upper limit (#4830):
// a column gets as wide as the title column's minimum allows (lcwRoom); phones / narrow lists keep their rows (app.css scope)
const LCW_MIN = 2.5, LCW_MAX = 1000;
const LC_TITLE_MIN = 12;  // 2.39.1 (#1217): rem the title column keeps while a column gets wider
// 2.39.1 (#1217): a thin accent line from the column titles down the list (width drag, column move); x = the element's centre
function lcGuide(el, line, x) {
  line = line || document.body.appendChild(Object.assign(document.createElement('div'), {className: 'lcguide'}));
  const h = el.closest('.lchead')?.getBoundingClientRect(), b = el.getBoundingClientRect(), v = $('#view')?.getBoundingClientRect();
  line.style.left = Math.round(x ?? b.left + b.width / 2) + 'px';
  line.style.top = Math.round(h ? h.top : b.top) + 'px';
  line.style.height = Math.max(0, Math.round(Math.min(innerHeight, v ? v.bottom : innerHeight) - (h ? h.top : b.top))) + 'px';
  return line;
}
const lcwAll = () => { try { const o = JSON.parse(S.settings?.col_widths || '{}'); return o && typeof o === 'object' && !Array.isArray(o) ? o : {}; } catch { return {}; } };
const lcwGet = lid => ({...(lcwAll()[lid] || LS.get('lcw.' + lid, {}) || {})});
// 2.742.0 (#4857): the widest column k of list lid may get now (rem): its width plus what the title keeps above LC_TITLE_MIN
function lcwRoom(head, k) {
  const rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16, sp = head?.querySelector('.spacer');
  const cell = head?.querySelector(`.lc[data-k="${window.CSS?.escape ? CSS.escape(k) : k.replace(/["\\]/g, '')}"]`);
  if (!sp || !cell) return LCW_MAX;
  return Math.max(LCW_MIN, cell.getBoundingClientRect().width / rem + Math.max(0, sp.getBoundingClientRect().width / rem - LC_TITLE_MIN));
}
function lcwApply(lid, w = lcwGet(lid)) {  // 2.87.9 (#1965): w = the widths shown while a grip is dragged (stored on release)
  let st = $('#lcw-style'); if (!st) { st = document.createElement('style'); st.id = 'lcw-style'; document.head.appendChild(st); }
  // 2.742.0 (#4857): only where the column titles show (from 768 px and a list wider than 48 rem, app.css); never wider than
  // the list minus the title's minimum, should the window have got narrower since the drag
  const css = Object.entries(w).filter(([, v]) => v > 0).map(([k, v]) => `#view .lc[data-k="${window.CSS?.escape ? CSS.escape(k) : k.replace(/["\\]/g, '')}"]{width:min(${+v}rem,max(${LCW_MIN}rem,var(--lw,100cqw) - ${LC_TITLE_MIN + 2}rem));max-width:none}`).join('\n');
  const txt = css ? `@media (min-width:768px){@container lrows (width > 48rem){\n${css}\n}}` : '';
  if (st.textContent !== txt) st.textContent = txt;  // 2.891.0 B (#5360): every list render calls this; the same sheet again restyled the whole page
}
function lcwSet(lid, k, v) {
  const w = lcwGet(lid);
  if (v == null) delete w[k]; else w[k] = Math.round(Math.max(LCW_MIN, Math.min(LCW_MAX, v)) * 100) / 100;  // 2.39.1 (#1217): no snapping
  // 2.742.0 (#4857): the account keeps it (only this list is sent, merged on the server); this device's old copy goes
  const all = lcwAll(); if (Object.keys(w).length) all[lid] = w; else delete all[lid];
  if (S.settings) S.settings.col_widths = JSON.stringify(all);
  LS.del('lcw.' + lid);
  lcwApply(lid);
  const g = document.querySelector(`#view .lchead[data-lid="${lid}"] .lcg[data-lcg="${window.CSS?.escape ? CSS.escape(k) : k.replace(/["\\]/g, '')}"]`);
  if (g) { g.setAttribute('aria-valuenow', String(w[k] ?? 7)); g.setAttribute('aria-valuetext', w[k] ? tr('{0} rem', String(w[k])) : tr('Default width')); }
  api('PATCH', '/api/settings', {col_widths: {[lid]: Object.keys(w).length ? w : null}}).catch(() => { /* shown; the local choice holds until the next load */ });
}
document.addEventListener('pointerdown', e => {
  const g = e.target.closest?.('.lchead .lcg'); if (!g || e.button !== 0) return;
  e.preventDefault(); e.stopPropagation();
  const lid = g.closest('.lchead').dataset.lid, k = g.dataset.lcg, cell = g.closest('.lc');  // 2.750.0 (#4502): 'v' = a collected view
  const rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16, x0 = e.clientX, w0 = cell.getBoundingClientRect().width / rem;
  // 2.39.1 (#1217): the grip sits on the line left of its column (the columns hang on the right edge, so this line moves
  // with the mouse): dragging left widens the column; the title keeps at least LC_TITLE_MIN; an accent line runs down the list
  const sp = g.closest('.lchead').querySelector('.spacer'), room = sp ? Math.max(0, sp.getBoundingClientRect().width / rem - LC_TITLE_MIN) : LCW_MAX;
  const wMax = w0 + room, guide = lcGuide(g), gb = g.getBoundingClientRect(), gx0 = gb.left + gb.width / 2;
  g.setPointerCapture?.(e.pointerId); document.body.classList.add('pgdrag', 'lcwdrag'); g.classList.add('drag');
  const cover = document.body.appendChild(Object.assign(document.createElement('div'), {className: 'lccover'}));  // 2.331.0 B (#3304): not body::after
  // 2.87.9 (#1965): once per frame and only shown; stored (localStorage) on release
  // 2.331.0 B (#3304): while dragging only the column title and the guide move (the title's own width, the guide's left from the
  // start measure: the column's right edge stays): rewriting #lcw-style per frame laid out all rows (300 rows: ~40 frames/s);
  // the rows take the width once on release
  let cur = null;
  const show = rafThrottle(x => { cur = Math.round(Math.max(LCW_MIN, Math.min(LCW_MAX, wMax, w0 - (x - x0) / rem)) * 100) / 100;
    cell.style.width = cur + 'rem'; cell.style.maxWidth = 'none'; guide.style.left = Math.round(gx0 - (cur - w0) * rem) + 'px'; });
  const mv = ev => show(ev.clientX);
  const up = () => {
    if (td_lcDrag?.g === g) td_lcDrag = null;
    ['pointermove', 'pointerup', 'pointercancel', 'lostpointercapture'].forEach((n, i) => g.removeEventListener(n, i ? up : mv));
    show.flush(); cell.style.width = cell.style.maxWidth = ''; if (cur != null) { lcwSet(lid, k, cur); cur = null; }
    document.body.classList.remove('pgdrag', 'lcwdrag'); dragRestFlush(); g.classList.remove('drag'); guide.remove(); cover.remove();
  };
  // 2.40.0 (#1430): a render that replaces the grip loses the capture: lostpointercapture (and the sweep after a render) ends it
  td_lcDrag = {g, up};
  g.addEventListener('pointermove', mv); ['pointerup', 'pointercancel', 'lostpointercapture'].forEach(n => g.addEventListener(n, up));
}, true);
// 2.40.0 (#1430): after a render: a width drag whose grip is gone ends; guide lines without a running drag go, and so does
// body.pgdrag when nothing is dragged any more (the detail pane's grip keeps its own)
let td_lcDrag = null;
function td_lcSweep() {
  if (td_lcDrag && !td_lcDrag.g.isConnected) td_lcDrag.up();
  if (td_lcDrag || document.body.classList.contains('lcmoving')) return;
  document.querySelectorAll('body > .lcguide, body > .lccover').forEach(x => x.remove());
  if (document.body.classList.contains('pgdrag') && !document.querySelector('.drag')) { document.body.classList.remove('pgdrag', 'lcwdrag'); dragRestFlush(); }
}
document.addEventListener('dblclick', e => { const g = e.target.closest?.('.lchead .lcg'); if (g) lcwSet(g.closest('.lchead').dataset.lid, g.dataset.lcg, null); });
document.addEventListener('keydown', e => {
  const g = e.target.closest?.('.lchead .lcg'); if (!g) return;
  const lid = g.closest('.lchead').dataset.lid, k = g.dataset.lcg, rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
  const cur = g.closest('.lc').getBoundingClientRect().width / rem || lcwGet(lid)[k] || parseFloat(getComputedStyle(g.closest('.lc')).width) / rem || 7;
  const to = {ArrowLeft: cur + (e.shiftKey ? 2 : .5), ArrowRight: cur - (e.shiftKey ? 2 : .5)}[e.key];  // 2.39.1 (#1217): the arrow moves the line
  if (to != null) { e.preventDefault(); e.stopPropagation(); lcwSet(lid, k, Math.min(to, lcwRoom(g.closest('.lchead'), k))); }  // 2.742.0 (#4857)
  else if (e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); lcwSet(lid, k, null); }
}, true);
// ---- dependencies: "waiting on" (blocked by open tasks)
function blockedTitle(t) {
  const names = (t.blockers || []).map(id => S.tasks.get(id)?.title).filter(Boolean), hidden = Math.max(0, (t.blocked || 0) - names.length);
  return tr('Blocked by: {0}', [...names.map(n => tr('“{0}”|quoted', n)), ...(hidden ? [trn('{0} task you cannot see', '{0} tasks you cannot see', hidden)] : [])].join(', '));
}
const hideBlockedToday = () => depsOn() && S.settings.hide_blocked_today === '1';
// 2.22.0 (#681): Today can show the inbox too (Settings > General > Today, off by default): the inbox's tasks without a
// date in their own foldable section under today's tasks, with quick buttons to sort them; they count in Today's number
const todayInbox = () => S.settings.today_inbox === '1';
const isTodayInbox = (t, t0 = today()) => !t.parent_id && !t.context && !t.due && t.status === 0 && !t.deleted_at && t.list_id === inbox()?.id && !planToday(t, t0) && !dlToday(t);
const todayInboxTasks = () => openTasks().filter(t => isTodayInbox(t)).sort((a, b) => (a.sort ?? 0) - (b.sort ?? 0) || a.id - b.id);
function todayInboxHtml(ts) {
  const k = 'today-inbox', closed = S.collapsed.has(k);
  const acts = t => `<span class="tinacts"><button type="button" class="iconbtn" data-act="tin-due" data-d="0" data-id="${t.id}" title="${esc(tr('Today'))}" aria-label="${esc(tr('{0}: today', t.title))}">${ic('sun', 's')}</button><button type="button" class="iconbtn" data-act="tin-due" data-d="1" data-id="${t.id}" title="${esc(tr('Tomorrow'))}" aria-label="${esc(tr('{0}: tomorrow', t.title))}">${ic('sunrise', 's')}</button><button type="button" class="iconbtn" data-act="tin-move" data-id="${t.id}" aria-haspopup="menu" title="${esc(tr('Move to project'))}" aria-label="${esc(tr('Move {0} to a project', t.title))}">${ic('list', 's')}</button></span>`;
  return `<div class="group tinbox"><div class="ghead ${closed ? 'closed' : ''}" data-act="collapse" data-key="${k}">${ic('chev', 's')}${ic('inbox', 's')}${tr('Basket')} <span class="c">${ts.length}</span></div>
    ${closed ? '' : ts.map(t => `<div class="tinrow">${taskRow(t, {drag: false, tree: false})}${acts(t)}</div>`).join('')}</div>`;
}
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-act="tin-due"], [data-act="tin-move"]'); if (!b) return;
  e.preventDefault(); e.stopPropagation();
  const id = +b.dataset.id, t = taskById(id); if (!t) return;
  if (b.dataset.act === 'tin-due') { const d = addDays(today(), +b.dataset.d); patchUndoable(id, {due: d}, tr('Due: {0}', dayLabel(d))); return; }
  mv_picker(b, [id], {filter: l => !l.is_inbox && canAddTo(l.id), pick: l => patchUndoable(id, {list_id: l.id}, tr('Moved to {0}', lname(l)))});  // 2.38.0 (#1177); 2.455.0 (#3848)
});
function qaddBox(extraCls = '') {
  return `<div class="qadd inline ${extraCls}"><div class="box">${ic('plus')}<input id="qinput" type="text" name="kalmido-quick-add" aria-label="${esc(tr('Add task…'))}" placeholder="${tr('Add task…')}" title="${esc(tr(QEX))}" autocomplete="off" data-form-type="other" data-lpignore="true" aria-autocomplete="none" enterkeyhint="done">${tplBtn()}${qExtraBtns('qinput')}</div><div class="chips" id="qchips"></div></div>`;
}
// 2.14.0 (#484): next to Send: "Add and open" (creates the task and opens its details at once, for notes and files) and the
// paper clip (pick files: the task is created with them as attachments, the first file's name is the title when none
// is typed; then its details open). Phones, Fold and desktop; 44 px targets on touch screens.
function qExtraBtns(inp, lab = false) {  // 2.32.0 (#1059): lab = with a short visible label (the phone sheet)
  const b = (act, icn, t, l) => `<button type="button" class="${lab ? 'btn sm qlab' : 'iconbtn'} qbtn" data-act="${act}" data-q="${inp}" title="${esc(t)}" aria-label="${esc(t)}">${ic(icn, 's')}${lab ? `<span aria-hidden="true">${esc(l)}</span>` : ''}</button>`;
  return b('q-clip', 'qclip', tr('Add with a file…'), tr('File|quick add')) + b('q-open', 'qopen', tr('Add and open details'), tr('Details|quick add'));
}
// 2.32.0 (#1059): the quick add syntax as chips; a tap puts the shortcut into the field (# and ~ only the sign, the
// suggestions take over). The words come from the translated example line, so they are the ones the parser knows.
const QH_TXT = N_('tomorrow 3pm · !high · #tag · ~project · every monday'), QH_CAP = N_('Goes to the basket · ~project · tomorrow · !high · #tag');
function qHelpChips(inp, capture = false) {
  const parts = tr(capture ? QH_CAP : QH_TXT).split(' · ');
  const lead = capture ? `<span class="qhlead">${esc(parts.shift())}</span>` : '';
  return `${lead}<span class="qhcs" role="group" aria-label="${esc(tr('Insert a shortcut'))}">${parts.map(p => { const ins = /^[#~]/.test(p) ? p[0] : p;
    return `<button type="button" class="qhc" data-act="q-ins" data-q="${inp}" data-ins="${esc(ins)}" title="${esc(tr('Insert “{0}”', ins))}">${esc(p)}</button>`; }).join('')}</span>`;
}
function qInsert(i, ins) {
  if (!i || !ins) return;
  const v = i.value, a = i.selectionStart ?? v.length, e = i.selectionEnd ?? a;
  const pre = v.slice(0, a), post = v.slice(e);
  const add = (pre && !/\s$/.test(pre) ? ' ' : '') + ins + (/^[#~]$/.test(ins) ? '' : ' ');
  i.value = pre + add + (/^[#~]$/.test(ins) ? post : post.replace(/^\s+/, ''));
  const c = (pre + add).length;
  i.focus({preventScroll: true}); try { i.setSelectionRange(c, c); } catch { /* type without a selection */ }
  i.dispatchEvent(new Event('input', {bubbles: true}));
}
document.addEventListener('mousedown', e => { if (e.target.closest?.('.qhc')) e.preventDefault(); });  // the field keeps the focus (and the phone its keyboard)
function quickFiles(inp) {
  if (!OUT.online) { toast(tr('Offline: only works again with a connection')); return; }
  let f = $('#qfile');
  if (!f) { f = document.createElement('input'); f.type = 'file'; f.multiple = true; f.id = 'qfile'; f.hidden = true; f.tabIndex = -1; f.setAttribute('aria-hidden', 'true'); document.body.appendChild(f); }
  f.value = '';
  f.onchange = () => {
    const files = noEmpty(f.files || []); f.value = '';
    if (!files.length || !inp) return;
    submitQuick(inp, {files});
  };
  f.click();
}
function tplBtn(lab = false) {
  return tplOf('task').length ? `<button class="${lab ? 'btn sm qlab' : 'iconbtn'} qtpl" data-act="tpl-use" title="${tr('New from template')}" aria-label="${tr('New from template')}">${ic('copy', 's')}${lab ? `<span aria-hidden="true">${tr('Template|quick add')}</span>` : ''}</button>` : '';
}
// 1.5.3: desktop / tablet quick add = a composer docked at the bottom of the list column (sticky): a card with an accent
// "+", a short placeholder, the key badge and the template button. Focused, it grows: chips for date, list and
// priority (effective values: typed ones, else the view's defaults; a click changes them) and the parsed tokens. Enter
// adds and keeps the focus, Esc leaves it. Phones keep the + button (FAB).
const QEX = N_('Type the way you think: “Dentist tomorrow 3pm !high #private ~project”');
function qdockHtml() {
  return `<div class="qdock"><div class="qadd dock"><div class="box"><span class="qplus" aria-hidden="true">${ic('plus', 's')}</span><input id="qinput" type="text" name="kalmido-quick-add" aria-label="${esc(tr('Add task…'))}" placeholder="${tr('Add task…')}" title="${esc(tr(QEX))}" autocomplete="off" data-form-type="other" data-lpignore="true" aria-autocomplete="none" enterkeyhint="done">${tplBtn()}${qExtraBtns('qinput')}${isTouch() ? '' : `<span class="qkey" title="${esc(kt(tr('New task'), 'n'))}">${kb('n')}</span>`}</div>
    <div class="qdmore"><div class="qdchips" id="qdchips"></div><div class="chips" id="qchips"></div>${hintSeen('qsyntax') ? '' : `<div class="qhint">${qHelpChips('qinput')}</div>`}</div></div></div>`;
}
// 2.380.2 (#3403): what the text says (!!!, morgen, ~project) wins over a chip picked before; no word in the text = the chip;
// a chip picked while the text already named the same thing wins (o.win, until the task is added; the word still leaves the title)
function qovPick(o, r, d) {
  const w = o.win || {}, txt = (k, v) => v != null && v !== '' && !w[k];
  return {due: txt('date', r.due) ? r.due : 'due' in o ? o.due : d.due, list_id: (txt('list', r.list_id) && r.list_id) || o.list_id || d.list_id,
    priority: txt('prio', r.priority) ? r.priority : 'priority' in o ? o.priority : d.priority ?? 0};
}
// the chips of the docked composer: what the task will get
function qdockChips() {
  const box = $('#qdchips'), inp = $('#qinput'); if (!box || !inp) return;
  if (S.qov?.key !== S.route.key) S.qov = {key: S.route.key};
  const d = quickDefaults(), r = parseQuick(inp.value, S.quick.ignore), o = S.qov;
  const q = qovPick(o, r, d), due = q.due, lid = q.list_id || inbox()?.id, pr = q.priority;
  const PRN = {0: N_('No priority'), 1: N_('Low'), 3: N_('Medium'), 5: N_('High'), 7: N_('Urgent')};
  // 2.910.0 (#5445): a value read from the text shows only here (no second parser chip below); its small x keeps "don't recognise"
  const qdx = k => { const c = !(o.win || {})[k] && r.chips.find(x => x.type === k && !x.off);
    return c ? `<button type="button" class="qchip qdx" data-qtype="${esc(k)}" title="${esc(tr("don't recognise"))}" aria-label="${esc(tr('Don’t recognise “{0}”', c.label))}">${ic('x', 's')}</button>` : ''; };
  box.innerHTML = `<button type="button" class="qdc ${due ? 'set' : ''} ${'due' in o && q.due === o.due ? 'ov' : ''}" data-act="qd-date">${ic('cal', 's')}${esc(due ? dayLabel(due) : tr('No date'))}</button>${/*html-ok*/ qdx('date')}` +
    (d.who ? `<span class="qdc set dsxwho">${ic('user', 's')}${esc(personNameAny(d.who) || '?')}</span>` : '') +  // 2.36.2 (#1138): for that person
    (d.noList && !o.list_id && !r.list_id ? `<span class="qnote dsxwho" role="note">${ic('alert', 's')}${esc(tr('No project with {0} that you can add to: share a project with them first.', personNameAny(d.who) || '?'))}</span>` :
    `<button type="button" class="qdc set ${o.list_id && q.list_id === o.list_id ? 'ov' : ''}" data-act="qd-list">${licMark(listById(lid), 's', true) || ic('list', 's')}${esc(lname(listById(lid)) || tr('Basket'))}</button>${/*html-ok*/ qdx('list')}`) +
    `<button type="button" class="qdc ${pr ? 'set flag-' + pr : ''} ${'priority' in o && q.priority === o.priority ? 'ov' : ''}" data-act="qd-prio">${ic('flag', 's')}${esc(tr(PRN[pr] || PRN[0]))}</button>${/*html-ok*/ qdx('prio')}`;
  msvvQSync(box);  // 2.73.0 C (#661): "→ Server · List" once another server is linked
}
const total0 = groups => groups.some(g => g.tasks.length);
const ROW_CAP = 400;
S.rowCaps = {};
const rowCap = () => S.rowCaps[S.route.key] || ROW_CAP;
function rowsMore() { S.rowCaps[S.route.key] = rowCap() + ROW_CAP; renderView(); }
// "Show more" loads by itself once it scrolls into view (and is still there after the render)
let rowMoreIO = null;
function rowMoreWatch() {
  const b = $('#view [data-act="rows-more"]'); if (!b || typeof IntersectionObserver === 'undefined') return;
  rowMoreIO?.disconnect();
  rowMoreIO = new IntersectionObserver(es => { if (es.some(e => e.isIntersecting)) { rowMoreIO.disconnect(); rowsMore(); } }, {root: $('#view'), rootMargin: '600px'});
  rowMoreIO.observe(b);
}
function viewList() {
  const ro = (() => { const k = S.route.key, l = k === 'inbox' ? inbox() : k.startsWith('l:') ? listById(+k.slice(2)) : null; return !!l && !canAddTo(l.id); })();
  return `<div class="lwrap">${viewListBody()}${ro ? '' : qdockHtml()}</div>`;
}
// 2.218.0 A (#2803): Today / Tomorrow show the project small under the title (in the line of the date) with the standard
// symbol level ("Important"); off with "Calm" or "Custom" without "Project" (Settings > Appearance > Symbols in the row).
// A row grouped by its project (the group's head names it) gets no second one: showList is off there
const rsyProjToday = () => rsy_level() === 'key' && (S.route.key === 'today' || S.route.key === 'tomorrow');
// 2.891.0 (#5440): the filter that hides every task of the view (null = none): its name and the button that leads to it
function lst_emptyFilter(rl) {
  const k = S.route.key, chg = tr('Change filter');
  if (k.startsWith('f:')) { const f = S.filters.find(x => x.id === +k.slice(2)); return f ? {name: f.name, btn: `<button type="button" class="btn" data-act="filter-edit" data-id="${esc(f.id)}">${ic('filter', 's')} ${esc(chg)}</button>`} : null; }
  if (!rl) return null;
  const cur = lv_cur(rl.id);
  if (cur) return {name: cur.name, btn: canEditList(rl.id) ? `<button type="button" class="btn" data-act="filter-edit" data-id="${esc(cur.id)}" data-lid="${esc(rl.id)}">${ic('filter', 's')} ${esc(chg)}</button>` : `<button type="button" class="btn" data-act="lviews" data-id="${esc(rl.id)}" aria-haspopup="menu">${ic('filter', 's')} ${esc(chg)}</button>`};
  const cf = typeof SG !== 'undefined' && SG.cf?.[rl.id];
  if (cf) return {name: sgColName(rl, cf.k), btn: `<button type="button" class="btn" data-sgfoff="${esc(rl.id)}">${ic('filter', 's')} ${esc(tr('Show all'))}</button>`};
  return null;
}
function viewListBody() {
  const v = viewTasks();
  FLOW.cyc = false;
  const groups = msvvMerge(groupTasks(v), v), flow = sortMode() === 'flow', crd = sortMode().startsWith('created');  // 2.73.0 C (#661): + other servers
  const showList = !v.list;
  const rl = v.list && listById(v.list), ro = rl && !canEditList(rl.id), ck = !!(rl && rl.checklist);
  // 2.14.0 (#425); 2.750.0 (#4502): a list without its own columns shows its default ones, a collected view the person's own
  const vc = !rl && !NOLIST_KEYS.includes(S.route.key), lc = rl ? listCols(rl) || lcFallback(rl) : vc ? vcCols() : null;
  const cols = rl && !lc && fieldCols(rl.id) ? fieldsOf(rl.id).slice(0, 6) : null;
  let h = (rl ? listHead(rl) : v.folder ? folderHead(v.folder) : agBandHtml()) + (rl?.org_reader ? ovJoinBar(rl) : ro ? `<div class="rohint">${ic(isPart(rl.id) ? 'user' : 'eye', 's')}${esc(isPart(rl.id) ? tr('Only your tasks · shared by {0}', rl.owner_name) : tr('Read-only, shared by {0}', rl.owner_name))}</div>` : '');
  // 2.25.0 (UX-54): "Now doable" explains itself once
  if (S.route.key === 'stale' && !hintSeen('stale')) h += `<div class="onehint" data-hint="stale">${ic('clock', 's')}<span>${esc(tr('Untouched for {0} days or waiting without a follow-up day. Days can be set per project.', S.staleDays || 7))}</span><button type="button" class="iconbtn hx" data-act="hint-x" data-k="stale" aria-label="${esc(tr('Dismiss'))}" title="${esc(tr('Dismiss'))}">${ic('x', 's')}</button></div>`;  // 2.34.0 (#266)
  if (S.route.key === 'doable' && !hintSeen('doable')) h += `<div class="onehint" data-hint="doable">${ic('zap', 's')}<span>${esc(tr('Not blocked, started, and due today, overdue or without a date.'))}</span><button type="button" class="iconbtn hx" data-act="hint-x" data-k="doable" aria-label="${esc(tr('Dismiss'))}" title="${esc(tr('Dismiss'))}">${ic('x', 's')}</button></div>`;
  // 2.25.0 (UX-28): a shopping or packing list gets the tip "Show completed at the bottom" once (was in the tour)
  // 2.396.0 (#3385): the project dialog has no "Used for" any more: a private list named like a shopping list offers the
  // shopping mode once (aisles, quantities, ticked at the bottom); a packing list keeps the tip below (only ticked at the bottom)
  const shopHint = !!rl && !ro && isOwner(rl) && famOn() && !rl.family && !rl.org_id && !rl.is_inbox && !isTracked(rl) && /einkauf|shopping|groceries|courses|compra|spesa|boodschap/i.test(rl.name) && !hintSeen('shop');
  if (shopHint) loadModule('family').catch(() => {});  // 2.501.0 (#4198): its button is handled in family.js
  if (shopHint) h += `<div class="onehint" data-hint="shop">${ic('cart', 's')}<span>${esc(tr('Use as a shopping list? Shopping mode with aisles and amounts, ticked items stay at the bottom.'))}</span><button type="button" class="btn sm" data-act="shop-on" data-id="${rl.id}">${tr('Use as a shopping list')}</button><button type="button" class="iconbtn hx" data-act="hint-x" data-k="shop" aria-label="${esc(tr('Dismiss'))}" title="${esc(tr('Dismiss'))}">${ic('x', 's')}</button></div>`;
  else if (rl && !ro && isOwner(rl) && !ck && (['shopping', 'packing'].includes(rl.family) || /einkauf|shopping|groceries|pack(liste|ing)|courses|compra|spesa|boodschap|paklijst/i.test(rl.name)) && !hintSeen('dab')) h += `<div class="onehint" data-hint="dab">${ic('cart', 's')}<span>${esc(tr('Shopping or packing list? Ticked items stay at the bottom and come back with a tap.'))}</span><button type="button" class="btn sm" data-act="dab-on" data-id="${rl.id}">${tr('Switch on')}</button><button type="button" class="iconbtn hx" data-act="hint-x" data-k="dab" aria-label="${esc(tr('Dismiss'))}" title="${esc(tr('Dismiss'))}">${ic('x', 's')}</button></div>`;
  // 2.31.0 (#1052): grouped by date, "All to today" / "Another day…" sit in the head of "Overdue" (no card of their own)
  const odHead = S.route.key === 'today' && groups.some(g => g.id === 'd:over' && g.tasks.length);
  // 2.32.0 (#1063): Today is built from blocks (Customize): the cards above, the tasks, the inbox; the rest of h after
  // the marker becomes the block "tasks"
  const tdc = S.route.key === 'today' ? {brief: briefCard(groups), wait: waitCard(), review: reviewCard(), overdue: odHead ? '' : overdueBanner(), events: cevTodayBlock(), ...(S.settings?.dv_today ? (typeof dcv_todayParts === 'function' ? dcv_todayParts() : (ld_later('docviews'), {})) : {})} : null;  // 2.579.0 (#4802): saved document views  // 2.24.0 (UX-35): the planners in "…"  // 2.10.0 (#440): review + planner
  if (tdc) h += '\u0001';
  h += moSegHtml();  // 2.156.0 C (#2072): My tasks: List / Board (mineorder.js)
  h += favViewNote();  // 2.40.0 (#1361): a view filtered to favourites says so
  h += sgFilterNote(rl);  // 2.43.0 (#1331): a column filter of the list says so (sheetgrid.js)
  if (rl && sortOwn()) h += `<div class="onehint sortown">${ic('sort', 's')}<span>${esc(tr('You see your own sort of this shared project.'))}</span><button type="button" class="btn sm" data-act="sort-shared">${tr('Back to the shared sort')}</button></div>`;  // 2.27.0 (#988)
  if (flow && FLOW.cyc) h += `<div class="flowhint">${ic('deps', 's')}${esc(tr('Some tasks block each other in a circle; they are ordered by date.'))}</div>`;
  if (lc && total0(groups)) h += lcHead(rl || VC, lc) + lcBar(rl || VC, lc);  // 2.427.0 B (#3551): + the strip for narrow layouts
  if (cols) h += `<div class="fcolhead"><span class="spacer"></span>${cols.map(f => `<span class="fcell t-${esc(f.type)}" title="${esc(f.name)}">${esc(f.name)}</span>`).join('')}</div>`;
  const total = groups.reduce((n, g) => n + g.tasks.length, 0);
  const flowDeps = flow && depsOn() && (() => {
    const shown = groups.flatMap(g => g.tasks), ids = new Set(shown.map(t => t.id));
    return shown.some(t => t.status === 0 && dFor(t) && (t.blocked || (t.blockers || []).some(b => ids.has(b))));
  })();
  const tin = S.route.key === 'today' && todayInbox() ? todayInboxTasks() : [];  // 2.22.0 (#681)
  // 2.891.0 (#5440): a filter that hides every task says so and leads to it (saved filter, a project's view, a column filter)
  const flt = !total && !tin.length ? lst_emptyFilter(rl) : null;
  const secBtn0 = v.list && !ro && !rl?.is_inbox && (!rl || canEditList(rl.id)), secBtn = !total && !tin.length && !flt && secBtn0 ? `<button type="button" class="btn secnew" data-act="section-new">${ic('plus', 's')} ${tr('Section')}</button>` : '';
  if (!total && !tin.length) {
    // 2.14.0: the heron; 2.83.0 C (#1427): the Kalmido K; 2.136.0 (#2193): the bot figure (o3c_empty, listhead.js), done = erledigt
    h += S.route.key === 'today' ? (v.done.length ? o3c_empty(tr('All done for today.'), tr('Enjoy the rest of the day.'), 'erledigt') : o3c_empty(tr('Nothing left for today.')))
      // CI of 2.223.0 (#2609 #2822): a list whose last open task was just ticked off is an all-done moment = the bot figure
      // (it nods, botNod); a list without tasks gets the symbol pattern
      : v.done.length ? o3c_empty(tr('All done.'), '', 'erledigt')
      : flt ? emptyState({icon: 'filter', title: tr('No tasks match the filter.'), sub: tr('A filter is active: {0}', flt.name), action: `<div class="eacts">${/*html-ok*/ flt.btn/* lst_emptyFilter */}</div>`, cls: 'efilt'})  // 2.891.0 (#5440)
      : emptyState({icon: 'list', title: tr('No tasks.'), sub: rl && !ro ? (isMobile() && !tabletDock() ? tr('Add the first one with the + button.') : tr('Add the first one with the field below.')) : '', action: (secBtn ? `<div class="eacts">${/*html-ok*/ secBtn/* the button above */}</div>` : '') + (rl && !ro ? `<div class="eacts">${/*html-ok*/ hlp_linkHtml('tasks')/* 2.1086.0 (#5820): How it works, a line of its own below "+ Section" */}</div>` : '')});  // 2.25.0 (UX-27): what this device shows; 2.891.0 (#5440): "+ Section" right under the text
  }
  let lastSub = '';
  // 2.17.0 (#649): a very long view renders its first ROW_CAP rows, then "Show more" (also by itself when it scrolls into
  // view); thousands of rows took seconds to build on every change
  // 2.65.0 (#1825): more than VL_MIN rows: every group draws only the rows near the visible part (vlist.js), no "Show more"
  const vl = vl_begin(total + (showDone() && !ck && S.collapsed.has('done-open') ? v.done.length : 0));
  let budget = vl ? Infinity : rowCap(), cut = 0;
  for (const g of groups) {
    if (g.sub && g.sub !== lastSub) h += `<div class="fsubhd" data-go="${esc(keyToHash('folder:' + g.sub))}" role="link" tabindex="0">${ic('folder', 's')}<span>${esc(fName(g.sub))}</span></div>`;
    lastSub = g.sub || lastSub;
    if (rl?.family === 'shopping' && famOn() && g.section && !g.tasks.length) continue;  // 2.19.0 (#653): only areas with items
    const closed = g.folded ? !S.collapsed.has(g.id) : S.collapsed.has(g.id);  // 2.41.0 (#1365): folded = closed until opened
    const sadd = g.section !== undefined && !ro && v.list && canAddTo(v.list);
    if (g.name) h += `<div class="group"${kbGroupAttr(g)}><div class="ghead ${g.cls || ''} ${closed ? 'closed' : ''}" data-act="collapse" data-key="${g.id}" ${g.section !== undefined ? `data-section="${g.section ?? ''}"` : ''}>${g.section && !ro ? secHandle(g.section) : ''}${kbGrip(g)}${ic('chev', 's')}${g.img ? `<img class="gicon" src="${esc(g.img)}" alt="">` : g.lic && licMark(g.lic) ? licMark(g.lic, 'glic') : g.color ? `<span class="gsw" style="background:${cssColor(g.color)}"></span>` : ''}${g.lic && !v.list ? kbCrumbHtml(g) : esc(g.name)} ${dsxCount(g, v)}${g.section ? wip_ghead(g) : ''}${g.mosec ? mseHeadHtml(g) : ''}${sadd ? `<button class="iconbtn gact gadd" data-act="sec-add" data-sec="${g.section || 0}" title="${esc(tr('Add a task to {0}', g.name))}" aria-label="${esc(tr('Add a task to {0}', g.name))}">${ic('plus', 's')}</button>` : ''}${g.section && !ro ? `<button data-rowmenu="ghead" class="iconbtn gact" data-act="section-menu" data-id="${g.section}" title="${esc(tr('More') + ': ' + g.name)}" aria-label="${esc(tr('More') + ': ' + g.name)}">${ic('dots', 's')}</button>` : ''}${odHead && g.id === 'd:over' ? `<span class="odact"><button class="btn sm" data-act="od-move" data-d="0">${tr('All to today')}</button><button class="btn sm" data-act="od-other" aria-haspopup="menu">${tr('Another day…')}</button></span>` : ''}</div>`;
    if (g.name && !closed && sadd) h += secAddHtml(g);
    // 1.7.0 Flow: the first task of each group that waits on nothing is marked "Next" (2.0.4: "Ready to start", and only
    // when some open task shown here waits on something; without dependencies the badge would say nothing)
    const nx = flow && flowDeps ? g.tasks.find(t => t.status === 0 && !t.context && !(t.blocked && dFor(t)))?.id : 0;
    if (!closed) { const n = Math.max(0, Math.min(g.tasks.length, budget)), row = (t, i) => (g.byList && (!i || g.tasks[i - 1].list_id !== t.list_id) ? mtListHead(t.list_id) : '') + (t._msv ? msvvRow(t._msv.sid, t._msv.t, {showList: true}) : taskRow(t, {showList: showList && !g.lic, tree: true, cols, lc, vc, tcols: {list: showList && !g.lic && (!moOwn() || moListCol())}, next: t.id === nx, crd, inToday: S.route.key === 'today', ...(v.dsx ? {dsx: showDone(), ...(t.status ? {drag: false} : {})} : {})}));  /* 2.73.0 C (#661): a task of another server */ h += vl ? vl_seg(g.id ?? '-', g.tasks, row, vl_tree(!!v.dsx && showDone())) : g.tasks.slice(0, n).map(row).join(''); budget -= n; cut += g.tasks.length - n; }
    // 2.46.2 (#1662): no drop field under an empty section any more; the section name takes the drop (.ghead.drop)
    if (g.name) h += '</div>';
  }
  if (lc && rl && total) h += fxSumRow(rl, lc, groups.flatMap(g => g.tasks).filter(t => !t._msv));  // 2.43.0 (#1328): the sum row (formula.js)
  if (tin.length) { if (tdc) tdc.inbox = todayInboxHtml(tin); else h += todayInboxHtml(tin); }
  if (v.mine) h += mseAddHtml();  // 2.569.0 (#4395): My tasks: a new own section
  // 2.19.0 (#667): the end of a list takes a dragged task into a new section
  if (rl && !ro && !rl.is_inbox && total && canEditList(rl.id)) h += `<div class="sdrop snew" data-newsec="1">${ic('plus', 's')}<span>${tr('New section')}</span></div>`;
  if (cut) h += `<div class="rowmore"><button type="button" class="btn" data-act="rows-more">${ic('down', 's')}${esc(trn('Show {0} more task', 'Show {0} more tasks', Math.min(cut, ROW_CAP)))}</button><span class="muted">${esc(trn('{0} task not shown yet', '{0} tasks not shown yet', cut))}</span></div>`;
  // 2.25.0 (UX-27 / UX-38): never in the inbox; 2.27.0 (#990): also in an empty list (a project may start without sections, #972)
  if (secBtn0 && !secBtn) h += `<button class="iconbtn secnew" data-act="section-new" style="margin:.375rem 0 0 -.25rem">${ic('plus', 's')} ${tr('Section')}</button>`;  // 2.891.0 (#5440): an empty list has it in its empty state
  if (ck) {  // 2.7.2 (#414) "Show completed at the bottom" (was the checklist type): done items stay below in "Done" (open by
    // default), one tap puts them back on the list
    const k = 'ckdone:' + rl.id, closed = S.collapsed.has(k), done = v.done.slice().sort((a, b) => mdPlain(a.title).localeCompare(mdPlain(b.title), LOCALE()));
    h += `<div class="group ckdone"><div class="ghead ${closed ? 'closed' : ''}" data-act="collapse" data-key="${k}" title="${esc(tr('Ticked-off items land here and can be put back on the list with one tap.'))}">${ic('chev', 's')}${tr('Done|checklist')} <span class="c">${done.length}</span>${done.length && !ro ? `<button class="btn sm gact" data-act="ck-uncheck" data-id="${rl.id}">${ic('undo', 's')} ${tr('Uncheck all')}</button><button class="btn sm gact" data-act="ck-clear" data-id="${rl.id}">${ic('trash', 's')} ${tr('Clear done')}</button>` : ''}</div>`;
    if (done.length) hintDone('ckdone');  // used once: the hint has done its job
    if (!closed) h += done.length ? done.map(t => taskRow(t, {drag: false, cols, lc, ckback: true})).join('') : hintOnce('ckdone', tr('Ticked-off items land here and can be put back on the list with one tap.'), 'ckempty');
    return h + '</div>';
  }
  if (v.done.length && showDone()) {
    const closed = !S.collapsed.has('done-open');
    h += `<div class="group"><div class="ghead ${closed ? 'closed' : ''}" data-act="collapse" data-key="done-open">${ic('chev', 's')}${tr('Completed')} <span class="c">${v.done.length}</span></div>`;
    if (!closed) { const dn = v.done.sort((a, b) => (b.completed_at || '').localeCompare(a.completed_at || '')), row = t => taskRow(t, {showList, drag: false, cols, lc, vc, tcols: {list: showList}}); h += vl ? vl_seg('done-open', dn, row) : dn.map(row).join(''); }
    h += '</div>';
  }
  if (tdc) { const i = h.indexOf('\u0001'); return h.slice(0, i) + lyHtml('today', {...tdc, tasks: h.slice(i + 1), inbox: tdc.inbox || ''}); }
  return h;
}
// 1.6.1: "Archived" = the archived lists as rows (colour / emoji, name, folder, open / done tasks, archived on, owner of a
// shared list): Open, Restore (owner, undoable) and Delete permanently (owner; 2.39.1 #1188: also list admins and organisation admins)
function viewArchived() {
  const ls = S.lists.filter(l => l.archived && !life_store(l) && inWs(l)).sort((a, b) =>  // 2.380.2 (#3407): the shown workspace; 2.609.0 (#4613): no area's store
    (b.archived_at || '').localeCompare(a.archived_at || '') || cmpText(lname(a), lname(b)));
  if (!ls.length) return `<div class="archv">${/*html-ok*/ emptyState({icon: 'archive', title: tr('No archived projects.'), sub: tr('Archive a project from its “…” menu; it disappears from the sidebar and its tasks from Today and the calendar.')})}</div>`;  // 2.891.0 (#5440)
  return `<div class="archv">${ls.map(l => {
    const p = l.progress || {done: 0, total: 0}, own = isOwner(l), em = leadEmoji(l.name), name = em ? l.name.slice(em.length).trim() : listName(l.name);
    const mark = listIconHtml(l, {cls: 'aemo', emoji: true});  // 2.38.0 (#1174)
    const meta = [l.folder && `${ic('folder', 's')}${esc(fDisp(l.folder))}`, `${esc(tr('{0} open', p.total - p.done))} · ${esc(tr('{0} done', p.done))}`,
      l.archived_at && esc(tr('archived {0}', fmtDateLoc(ds(new Date(l.archived_at))))), !own && `${ic('users', 's')}${esc(tr('Shared by {0}', l.owner_name || '?'))}`].filter(Boolean);
    return `<div class="arow" data-list="${l.id}"><button class="aname" data-go="l/${l.id}" title="${esc(tr('Open {0}', name))}">${mark}<span class="n">${esc(name)}</span></button>
      <div class="ameta">${meta.map(x => `<span>${x}</span>`).join('')}</div>
      <div class="aacts"><button class="btn sm" data-go="l/${l.id}">${tr('Open')}</button>${canManage(l) || lmOrgAdmin(l) ? `<button class="btn sm" data-act="arch-restore" data-id="${l.id}">${ic('undo', 's')}<span>${tr('Restore')}</span></button><button class="btn sm danger" data-act="arch-del" data-id="${l.id}">${ic('trash', 's')}<span>${tr('Delete permanently…')}</span></button>` : ''}</div></div>`;
  }).join('')}</div>`;
}
// 2.116.0 A (#2063): days until a trashed task is deleted for good (null = no period known); 0 = in the next run
const ttpLeft = t => { const d = S.hist?.days; if (!d || !t.deleted_at || S.hist.purge_on === false || trashKeeps()) return null;  // 2.223.3 A (#2877): no countdown while nothing is deleted
   return Math.max(0, Math.ceil((Date.parse(t.deleted_at) + d * 864e5 - Date.now()) / 864e5)); };
// 2.580.0 (#4815): Completed / Trash in the list shell (.hview = --w-seite, start-breite.css)
function viewHistory() { return `<div class="hview">${hist_body()}</div>`; }
function hist_body() {
  const trash = S.route.key === 'trash';
  const arr = S.extra || [];
  const otr = trash ? otr_html() + vtr_html() + ptr_html() : '';  // 2.102.0 A (#1988): "Deleted lists" above the tasks; 2.549.0 (#4536): + video sign-offs (trashui.js); 2.567.0 A (#4707): + the other parts
  // 2.891.0 (#5440): a failed load says so (was "Trash is empty." although nothing was known)
  if (!arr.length && S.extraErr) return otr + errorState({retry: () => loadExtra().then(() => { S.extraErr = 0; }, () => {}).finally(renderView)});
  if (!arr.length) return otr + (otr ? '' : emptyState({icon: trash ? 'trash' : 'done', title: trash ? tr('Trash is empty.') : tr('Nothing completed yet.')}));  // 2.891.0 (#5440)
  if (trash) {  // 2.0.5: what "Empty" leaves behind (shared lists of other owners) is said up front and marked per row
    const kept = S.hist?.k === 'trash' && S.hist.kept != null ? S.hist.kept : arr.filter(t => t.keep).length;  // 2.40.0 (#1432): the whole trash
    const days = S.hist?.k === 'trash' ? S.hist.days : null;  // 2.116.0 A (#2063): the trash period, from the server
    return otr + (days ? `<div class="shint ttphint">${ic('clock', 's')} ${esc(trashNote(trn('Tasks in the trash are deleted permanently after {0} day.', 'Tasks in the trash are deleted permanently after {0} days.', days)))}</div>` : '')
      + (kept ? `<div class="shint trkeep">${ic('lock', 's')} ${esc(trn('{0} item stays when you empty the trash: it is in a project of another owner, only they can delete it permanently.', '{0} items stay when you empty the trash: they are in projects of other owners, only they can delete them permanently.', kept))}</div>` : '')
      + (vl_begin(arr.length) ? vl_seg('trash', arr, t => taskRow(t, {trash: true, showList: true})) : arr.map(t => taskRow(t, {trash: true, showList: true})).join('')) + histMoreHtml();  // 2.65.0 (#1825)
  }
  const g = new Map();
  for (const t of arr) { const d = (t.completed_at ? new Date(t.completed_at) : new Date()); const k = ds(d); if (!g.has(k)) g.set(k, []); g.get(k).push(t); }
  const vl = vl_begin(arr.length), row = t => taskRow(t, {showList: true, drag: false, tcols: {list: true}});  // 2.65.0 (#1825)
  return [...g.entries()].map(([k, ts]) => `<div class="group"><div class="ghead">${dayLabel(k, true)} <span class="c">${ts.length}</span></div>${vl ? vl_seg(k, ts, row) : ts.map(row).join('')}</div>`).join('') + histMoreHtml();
}
// 2.40.0 (#1432): "Load more" under Completed / Trash, only while the server has more
const histMoreHtml = () => S.hist?.next && S.hist.k === S.route.key ? `<div class="audmore"><button type="button" class="btn sm" data-act="hist-more">${tr('Load more')}</button></div>` : '';
function viewSearch() {
  return `<div class="search"><input id="searchq" type="search" aria-label="${esc(tr('Search'))}" placeholder="${tr('Search titles and notes')}" autocomplete="off" enterkeyhint="search"></div>${typeof rt9_searchToggleHtml === 'function' ? rt9_searchToggleHtml() : ''}<div id="sresults">${S.searchRes ? renderSearchRes() : ''}</div><div id="msvvsearch">${msvvSearchHtml()}</div><div id="smsgs">${msgSecHtml()}</div>`;
}
function renderSearchRes() {
  if (!S.searchRes.length) return botEmpty('schaut', tr('No results.'), tr('Try fewer or other words.'));
  const row = (t, i) => (typeof rt9_simHead === 'function' ? rt9_simHead(t, S.searchRes[i - 1]) : '') + taskRow(t, {showList: true, drag: false, tcols: {list: true}})
    + (typeof ftxtHitHtml === 'function' ? ftxtHitHtml(t) : '');  // 2.59.0 B (#1375): + heading of the similar ones, 2.61.0 (#1820): "in file" note
  return vl_begin(S.searchRes.length) ? vl_seg('search', S.searchRes, row) : S.searchRes.map(row).join('');  // 2.65.0 (#1825)
}
let searchTimer;
function snavMore(nav) {
  const b = nav?.parentElement?.querySelector('.snmore'); if (!b) return;
  const more = isMobile() && nav.scrollLeft + nav.clientWidth < nav.scrollWidth - 4;
  if (b.classList.contains('hidden') === more) b.classList.toggle('hidden', !more);
}
async function doSearch(q) {
  S.searchQ = q; if (S.searchEnter !== q) S.searchEnter = null;
  clearTimeout(searchTimer);
  searchTimer = setTimeout(async () => {
    const one = q.trim().length < 2, sq = one ? '' : q;  // 2.281.0 C (#3113): one character asks no server (only "#5" / "5" below)
    if (S.msg.q !== sq) msgSecRun(sq);  // 2.33.0 (#1080): "Messages" below the tasks (chat.js)
    if (S.msvv.search.q !== sq) msvvSearch(sq);  // 2.73.0 C (#661): the other servers, in parallel
    if (!q.trim()) { S.searchRes = null; $('#sresults').innerHTML = ''; return; }
    const j = one ? {tasks: []} : await api('GET', '/api/tasks?scope=search&q=' + encodeURIComponent(q) + (typeof rt9_semQ === 'function' ? rt9_semQ() : ''));  // 2.59.0 B (#1375): + semantic=1
    // 2.13.0: "#447" / "447" puts that task (one this person sees) first
    const nm = q.trim().match(/^#?(\d{1,9})$/), hit = (nm && taskById(+nm[1])) || tkFind(q);  // 2.390.0 (#3353): + "APP-12"
    if (hit) j.tasks = [hit, ...j.tasks.filter(t => t.id !== hit.id)];
    if (one && !hit) { if (S.searchQ === q) { S.searchRes = null; $('#sresults').innerHTML = ''; } return; }
    if (!one && typeof le2eSearch === 'function') j.tasks = le2eSearch(q, j.tasks);  // 2.64.1 (#1817): locked lists, searched here (the server cannot)
    S.searchRes = j.tasks; S.extra = j.tasks; S.searchResQ = q;
    keepReading($('#view'), () => { $('#sresults').innerHTML = renderSearchRes(); vl_after(); });  // 2.924.0 (#5224): results that load again keep the hit read in place
    if (S.searchEnter === q) { S.searchEnter = null; searchEnterOpen(q); }
  }, 200);
}
// 2.13.2 (#478 F4): Enter in the search opens the task of an exact "#id" / "id", or the only hit (the results of what was
// typed may still be on their way: then it opens once they are there)
function searchEnterOpen(q) {
  const nm = q.trim().match(/^#?(\d{1,9})$/), r = S.searchResQ === q ? S.searchRes || [] : [];
  const t = nm ? (r.find(x => x.id === +nm[1]) || taskById(+nm[1])) : tkFind(q) || (r.length === 1 ? r[0] : null);  // 2.390.0 (#3353): + "APP-12"
  if (!t) return false;
  if (isTouch()) $('#searchq')?.blur();  // 2.655.0 (#5081): was isMobile()
  openDetail(t.id); return true;
}
document.addEventListener('keydown', e => {
  if (e.target.id !== 'searchq' || e.key !== 'Enter' || e.isComposing) return;
  const q = e.target.value; e.preventDefault();
  if (q.trim() && !searchEnterOpen(q)) S.searchEnter = q;
  if (S.searchQ !== q) doSearch(q);
});
// ---- 2.149.0 F (#2518): the other servers' view (msvview.js) loads on demand (lazyload.js module msvview), only for someone who
// has linked another server (or opens one of its lists). Its state stays here; before it is loaded the stand-ins answer what it
// answers without a linked server (nothing, the own numbers). The start asks /api/servers once (as msvvBoot did) and loads the
// module only when a server is linked; adding the first one in Settings (servers.js: msv:changed) loads it too
S.msvv = {self: null, links: [], data: {}, news: {}, cal: {key: '', ev: {}}, search: {q: '', res: {}}, loaded: false, at: 0, busy: false};
S.msvvQ = null;  // the quick add target picked by hand: {key, sid, lid}
window.msvvSide = window.msvvNewsHtml = window.msvvSelfBadge = window.msvvRow = window.msvvSearchHtml = window.msvvSearch = window.msvvQSync = window.msvvSheetTarget
  = window.msvvCalEnsure = window.msvvCalDay = () => '';
window.msvvMerge = g => g;
window.msvvCount = n => n;
window.msvvMoveItem = () => [];
window.msvvCalChips = () => [];
window.msvvQuick = async () => false;
window.msvvTitle = () => '?';
// a list of another server opened straight away (a link, a reload): load and boot (its first answer draws the view)
window.msvvViewList = () => { if (!S.msvv.ld) { S.msvv.ld = 1; loadModule('msvview').then(() => msvvBoot(), () => { S.msvv.ld = 0; }); } return loadingHtml('big'); };  // 2.891.0 (#5440)
const msvv_probe = () => fetch('/api/servers', {headers: {'X-Requested-With': 'kalmido'}, redirect: 'manual', credentials: 'same-origin'})
  .then(r => r.ok ? r.json() : null, () => null)
  .then(j => { if ((Array.isArray(j?.links) && j.links.length) || S.route.mod === 'msv') { S.msvv.pre = j && typeof j === 'object' ? j : null; return loadModule('msvview').then(() => msvvBoot()); } })
  .catch(() => {});
window.msvvBoot = () => {
  if (window.msvvBoot.done || S.me?.kid) return; window.msvvBoot.done = 1;
  msvv_probe();
  document.addEventListener('msv:changed', () => loadModule('msvview').then(() => msvvBoot()).catch(() => {}), {once: true});
};
window.msvvLoad = () => msvv_probe();  // "Sync now": a server linked meanwhile (on another device)
