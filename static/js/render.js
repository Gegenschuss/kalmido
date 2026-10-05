/* Kalmido web client: Rendering: the shell (sidebar, header, tabs) and task rows.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ------------------------------------------------------------------ render: shell
function render() {
  _kidsIx = null;  // 2.17.0 (#649): one children index per render, built after any change made before it
  const sk = $('#skip'); if (sk && sk.textContent !== tr('Skip to content')) sk.textContent = tr('Skip to content');  // 2.13.0 (#453 A9)
  document.body.classList.toggle('in-chat', chatFull() && S.route.mod === 'agents' && !!S.route.agent);  // 2.13.0 (#453 P11)
  document.body.classList.toggle('in-team', S.route.mod === 'team');  // 2.17.0 (#419): the conversation fills the view, only its messages scroll
  document.body.classList.toggle('kidmode', !!S.me?.kid);  // 2.19.0 (#653): a kid's simple view (no sidebar, tab bar, + button)
  sideSearchSync(); badgeSync();
  if (S.shop) shopDraw();  // 2.19.0: shopping mode follows every reload (the app's own poll included)
  fitLayout(true); renderSide(); renderTop(); renderView(); renderTabs();
  $('#fab').innerHTML = ic('plus'); $('#fab').setAttribute('aria-label', tr('New task')); $('#fab').title = kt(tr('New task'), 'n');
  fabSync();
  if (S.sel && S.tasks.has(S.sel) && !$('#detail').contains(document.activeElement)) renderDetail();
  if (S.sel && !S.tasks.has(S.sel) && !(S.extra || []).some(t => t.id === S.sel)) closeDetail();
  agentLive();
}
// 2.13.3: the + button follows rotations / folding too (not only a full render): hidden where the add bar or the header's
// "New task" is there (tablets, an unfolded Fold in portrait)
function fabSync() { const f = $('#fab'); if (f) f.classList.toggle('gone', fabOff() || S.multi.size > 0 || (!!$('#view .qdock') && (tabletDock() || !isMobile()))); }
window.addEventListener('resize', () => { if (S.booted) requestAnimationFrame(fabSync); });
const MODS = [['tasks', 'done', N_('Tasks')], ['cal', 'cal', N_('Calendar')], ['matrix', 'grid', N_('Matrix')], ['habits', 'habit', N_('Habits')], ['pomo', 'timer', N_('Focus')], ['family', 'family', N_('Family')]];
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
const SMART_TABS = ['inbox', 'today', 'tomorrow', 'week', 'doable', 'pinned', 'waiting', 'assigned', 'all', 'done', 'trash'];
const leadEmoji = n => (String(n ?? '').match(/^((?:\p{Extended_Pictographic}|\p{Emoji_Modifier}|\uFE0F|\u200D)+)/u) || [])[1];
const tabDefault = () => mods().map(([m]) => 'm:' + m);
const tabIds = () => LS.get('tabbar', null) || tabDefault();
function tabItem(id) {
  const [kind, ...rest] = id.split(':'), v = rest.join(':');
  if (kind === 'm') {
    const md = MODS.find(x => x[0] === v);
    if (!md || (v !== 'tasks' && !feat(v))) return null;
    return {id, go: modHash(v), icon: ic(md[1], 'l'), label: tr(md[2]), mod: v};
  }
  if (kind === 's' && v === 'assigned' && !collab()) return null;
  if (kind === 's' && SMART[v]) return {id, go: v, icon: ic(SMART[v].icon, 'l'), label: v === 'week' ? tr('7 days') : tr(SMART[v].name), key: v};
  if (kind === 'l') {
    const l = listById(+v); if (!l || l.is_inbox) return null;
    const em = leadEmoji(l.name), name = em ? l.name.slice(em.length).trim() : l.name;
    return {id, go: 'l/' + v, icon: l.icon ? `<span class="temoji">${licon(l, 'licon t')}</span>` : em ? `<span class="temoji">${em}</span>` : `<span class="tsw" style="${cssColor(l.color) ? 'background:' + cssColor(l.color) : ''}"></span>`, label: name, key: 'l:' + v};
  }
  if (kind === 'f') { const f = S.filters.find(x => x.id === +v); return f ? {id, go: 'f/' + v, icon: ic('filter', 'l'), label: f.name, key: 'f:' + v} : null; }
  if (kind === 'tag' && v) return {id, go: 'tag/' + encodeURIComponent(v), icon: ic('tag', 'l'), label: v, key: 'tag:' + v};
  if (kind === 'folder' && v) return {id, go: 'folder/' + encodeURIComponent(v), icon: ic('folder', 'l'), label: fName(v), key: 'folder:' + v};
  if (id === 'news') return collab() ? {id, go: 'news', icon: ic('bell', 'l'), label: tr('News'), mod: 'news'} : null;
  if (id === 'agents') return agentsTab() ? {id, go: 'agents', icon: ic('bot', 'l'), label: tr('Agents'), mod: 'agents'} : null;
  if (id === 'stats') return feat('stats') ? {id, go: 'stats', icon: ic('chart', 'l'), label: tr('Statistics'), mod: 'stats'} : null;
  if (id === 'time') return timeOn() ? {id, go: 'time', icon: ic('clock', 'l'), label: tr('Time tracking'), mod: 'time'} : null;  // 2.7.0 (#405 S5): one name
  if (id === 'overview') return overviewOn() ? {id, go: 'overview', icon: ic('pulse', 'l'), label: tr('Overview'), mod: 'overview'} : null;
  if (id === 'team') return teamOn() ? {id, go: 'team', icon: ic('comment', 'l'), label: tr('Team chat'), mod: 'team', n: S.team?.unread || 0} : null;  // 2.17.0 (#419)
  if (id === 'home') return {id, go: 'home', icon: ic('home', 'l'), label: tr('Dashboard'), mod: 'home'};  // 2.17.0 (#475)
  if (id === 'search') return {id, go: 'search', icon: ic('search', 'l'), label: tr('Search'), key: 'search'};
  if (id === 'settings') return {id, act: 'settings', icon: ic('gear', 'l'), label: tr('Settings'), upd: updDot()};
  return null;
}
const tabItems = () => tabIds().map(tabItem).filter(Boolean);
// which pinned item is "on": exact key match first, else the module (Aufgaben = any task view)
function tabOn(items) {
  const r = S.route, exact = items.find(t => t.key && r.mod === 'tasks' && t.key === r.key);
  if (exact) return exact.id;
  const m = items.find(t => t.mod && t.mod === r.mod && !(r.mod === 'tasks' && r.key === 'search'));
  return m ? m.id : null;
}
// 1.5.3: the "g …" shortcuts in the tooltips of what they open
const GO_KEY = {today: 'g t', tomorrow: 'g m', week: 'g w', doable: 'g d', inbox: 'g i', all: 'g a', cal: 'g c', habits: 'g h', pomo: 'g f', settings: 'g s'};
function tabBtn(t, on, cls = '') {
  const tgt = t.go != null ? `data-go="${esc(t.go)}"` : `data-act="${t.act}"`;
  const nb = t.id === 'news' && S.news?.unread ? `<span class="nbadge">${S.news.unread > 99 ? '99+' : S.news.unread}</span>` : t.id === 'team' && t.n ? `<span class="nbadge">${t.n > 99 ? '99+' : t.n}</span>` : '';
  return `<button class="${cls} ${on ? 'on' : ''}" ${tgt} title="${esc(GO_KEY[t.mod || t.key || t.id] ? kt(t.label, GO_KEY[t.mod || t.key || t.id]) : t.label)}"><span class="tico">${t.icon}</span><span>${esc(t.label)}</span>${t.mod === 'pomo' && S.pomo ? '<span class="dot"></span>' : ''}${t.mod === 'time' && S.timer ? '<span class="dot rec"></span>' : ''}${t.upd ? `<span class="dot" title="${esc(tr('Update available'))}"></span>` : ''}${nb}</button>`;
}
// 2.8.0 (#434): no icon rail any more. The desktop has one sidebar with grouped text navigation (renderSide) and the
// command bar in the header; the tab bar setting is for phones only.
// what "Mehr" offers: overflow tabs + enabled modules that are not pinned + search/settings if not pinned
function tabOverflow() {
  const items = tabItems(), shown = items.length > TAB_MAX ? items.slice(0, TAB_MAX - 1) : items;
  const rest = items.slice(shown.length);
  const mods2 = mods().filter(([m]) => !items.some(t => t.mod === m)).map(([m]) => tabItem('m:' + m));
  const misc = ['home', 'team', 'news', 'agents', 'overview', 'stats', 'time', 'search', 'settings'].filter(k => !items.some(t => t.id === k)).map(tabItem).filter(Boolean);
  // search + settings are also in the side menu: they alone do not justify a "Mehr" tab
  return {shown, more: rest.length || mods2.length ? [...rest, ...mods2, ...misc] : []};
}
function renderTabs() {
  const {shown, more} = tabOverflow(), all = tabItems(), on = tabOn(all);
  // highlight "Mehr" when the current view is only reachable through it (overflow tab, unpinned module, search)
  const moreOn = more.length > 0 && (on ? !shown.some(t => t.id === on) : (S.route.mod !== 'tasks' && S.route.mod !== 'news') || S.route.key === 'search');
  $('#tabs').innerHTML = shown.map(t => tabBtn(t, t.id === on)).join('') +
    (more.length ? `<button class="${moreOn ? 'on' : ''}" data-act="tabs-more"><span class="tico">${ic('dots', 'l')}</span><span>${tr('More')}</span></button>` : '');
}
function tabsMore(anchor) {
  const {more} = tabOverflow();
  menu(anchor, [...more.map(t => ({label: t.id === 'news' && S.news?.unread ? `${t.label} (${S.news.unread})` : t.label, icon: t.id === 'settings' ? 'gear' : t.id === 'search' ? 'search' : t.id === 'news' ? 'bell' : t.id === 'stats' ? 'chart' : t.id === 'time' ? 'clock' : t.id === 'overview' ? 'pulse' : t.id === 'agents' ? 'bot' : t.mod ? MODS.find(x => x[0] === t.mod)?.[1] || ({team: 'comment', home: 'home', notes: 'file'}[t.mod]) || 'dots' : t.id.startsWith('f:') ? 'filter' : t.id.startsWith('tag:') ? 'tag' : t.id.startsWith('s:') ? SMART[t.key].icon : 'list',
    fn: () => t.act ? settingsModal() : go(t.go)})), '-', {label: tr('Customize tab bar'), icon: 'edit', fn: () => settingsModal('tabbar')}]);
}
function counts() {
  const t0 = today(), c = {today: 0, tomorrow: 0, week: 0, doable: 0, over: 0, all: 0, assigned: 0, waiting: 0, pinned: 0, lists: {}, tags: {}, filters: {}};
  for (const f of S.filters) c.filters[f.id] = openTasks().filter(t => !t.parent_id && filterMatch(t, f.rules)).length;
  for (const t of openTasks()) {
    // "Now doable" counts what its view shows at the top level: a subtask only when its parent is not doable itself
    if (doable(t, t0) && !(t.parent_id && S.tasks.get(t.parent_id) && doable(S.tasks.get(t.parent_id), t0))) c.doable++;
    if (t.waiting_at && !(t.parent_id && S.tasks.get(t.parent_id)?.waiting_at)) c.waiting++;  // 2.1.0 (#335)
    if (t.pinned && !t.context && !(t.parent_id && S.tasks.get(t.parent_id)?.pinned)) c.pinned++;  // 2.16.0 (#648)
    if (t.parent_id) continue;
    c.all++;
    if (mineAssigned(t)) c.assigned++;
    c.lists[t.list_id] = (c.lists[t.list_id] || 0) + 1;
    for (const g of new Set([...t.tags, ...(t.ltags || [])])) c.tags[g] = (c.tags[g] || 0) + 1;
    if ((t.due && t.due <= t0 || dlToday(t) || planToday(t, t0)) && !(t.blocked && hideBlockedToday())) c.today++;  // 2.11.0: + planned for today
    else if (todayInbox() && isTodayInbox(t, t0)) c.today++;  // 2.22.0 (#681): the inbox counts in Today when it is shown there
    if (!t.due) continue;
    if (t.due < t0) c.over++;
    if (t.due === addDays(t0, 1)) c.tomorrow++;
    if (t.due <= addDays(t0, 6)) c.week++;
  }
  return c;
}
// 2.8.0 (#434) "Leitstand": one sidebar, grouped text navigation. Focus (smart lists, with icons), Views (the modules),
// Lists (folders + lists: a dot, the label, the count right after it, the progress of a project on the right), Filters,
// Tags, Team (people + agents with their status dot), then All / Completed / Trash / Archived, Search, Settings and the
// account. Switched-off modules are left out. Each group folds (per device, LS sideGroups).
const sideOpen = g => !(LS.get('sideGroups', []) || []).includes(g);
function sideGroupToggle(g) { const x = new Set(LS.get('sideGroups', []) || []); x.has(g) ? x.delete(g) : x.add(g); LS.set('sideGroups', [...x]); renderSide(); }
function teamPeople() {
  if (!collab()) return [];
  const seen = new Map();
  for (const l of S.lists) for (const p of listPeople(l)) if (p.user_id && (!S.me || p.user_id !== S.me.id) && !agentById(p.user_id) && !seen.has(p.user_id)) seen.set(p.user_id, p.name || personNameAny(p.user_id));
  return [...seen.entries()].map(([id, name]) => ({id, name})).sort((a, b) => a.name.localeCompare(b.name));
}
function renderSide() {
  const c = counts(), k = S.route.key, onTasks = S.route.mod === 'tasks';
  const row = (key, icon, name, n, extra = '', after = '') =>
    `<button class="srow ${onTasks && k === key && !(key === 'all' && isRoadmap()) ? 'on' : ''}" data-go="${esc(keyToHash(key))}" data-drop="${esc(key)}" ${GO_KEY[key] && !isTouch() ? `title="${esc(kt(name, GO_KEY[key]))}"` : ''} ${extra}>${icon}<span class="n">${esc(name)}</span><span class="c ${key === 'today' && c.over ? 'over' : ''}">${n || ''}</span>${after}</button>`;
  const mrow = (mod, icon, name, after = '', attrs = '') => `<button class="srow smod ${S.route.mod === mod ? 'on' : ''}" data-go="${mod}" ${GO_KEY[mod] && !isTouch() ? `title="${esc(kt(name, GO_KEY[mod]))}"` : ''} ${attrs}>${ic(icon)}<span class="n">${esc(name)}</span>${after}</button>`;
  const head = (g, label, acts = '', n = '', tip = '') => `<div class="shead sgh ${g === 'lists' ? 'lroot' : ''} ${sideOpen(g) ? '' : 'closed'}" ${tip ? `title="${esc(tip)}"` : ''}><button class="sgt" data-act="side-group" data-g="${g}" aria-expanded="${sideOpen(g)}">${ic('chev', 's fcar')}<span>${esc(label)}</span>${!sideOpen(g) && n ? `<span class="c">${n}</span>` : ''}</button><span class="spacer"></span>${acts}</div>`;
  const lists = S.lists.filter(l => !l.is_inbox && !l.archived);
  const listRow = l => {
    const sw = l.icon ? licon(l, 'licon') : l.color || /^\p{L}/u.test(l.name) ? `<span class="sw" style="${cssColor(l.color) ? 'background:' + cssColor(l.color) : ''}"></span>` : '';
    const pg = progressFor(l) && l.progress?.total ? `<span class="spct" title="${esc(tr('{0} of {1} done ({2}%)', l.progress.done, l.progress.total, pct(l.progress)))}">${pct(l.progress)} %</span>` : '';
    const shr = (l.status && statusFor(l) ? `<span class="stdot st-${esc(l.status)}" title="${esc(statusLabel(l.status))}"></span>` : '') +
      (l.shared && collab() && l.bell === 'mute' ? `<span class="shr bellm" title="${esc(tr('Notifications: {0}', bellLabel('mute')))}">${ic('belloff', 's')}</span>` : '') +
      (l.shared && collab() ? `<span class="shr" title="${esc(isOwner(l) ? tr('Shared by you') : tr('Shared by {0}', l.owner_name))}">${ic('users', 's')}</span>` : '');
    // 2.22.0 (#692): sort mode: a grip on the left, the name shortens with …, the buttons in a fixed column on the right
    if (S.listReorder) { const nm = listName(l.name); return `<div class="srow reorder" data-list="${l.id}"><span class="sgrip" aria-hidden="true">${ic('grip', 's')}</span>${sw}<span class="n" title="${esc(nm)}">${esc(nm)}</span>${shr}<span class="rctl"><button class="iconbtn" data-lfolder="${l.id}" aria-haspopup="menu" title="${tr('Move to…')}" aria-label="${esc(tr('Move {0} to…', nm))}">${ic('folder', 's')}</button><button class="iconbtn" data-lmove="-1" data-id="${l.id}" title="${tr('move up')}" aria-label="${esc(tr('Move {0} up', nm))}">${ic('chev', 's up')}</button><button class="iconbtn" data-lmove="1" data-id="${l.id}" title="${tr('move down')}" aria-label="${esc(tr('Move {0} down', nm))}">${ic('chev', 's')}</button></span></div>`; }
    return row('l:' + l.id, sw, listName(l.name), c.lists[l.id], `data-list="${l.id}" ${isMobile() ? '' : 'draggable="true"'}`, shr + pg);
  };
  let lh = lists.filter(l => !l.folder).map(listRow).join('');
  // 2.4.0 (#361): a tree: top folder, its own lists, then its subfolders (header + lists, one level deeper)
  const fhead = f => {
    const sub = !!fParent(f), fl = lists.filter(l => fUnder(l.folder, f)), closed = foldClosed(f) && !S.listReorder;
    const n = fl.reduce((a, l) => a + (c.lists[l.id] || 0), 0);
    const active = fl.some(l => onTasks && k === 'l:' + l.id);
    const fon = onTasks && k === 'folder:' + f;  // 1.5.2: the name opens the folder view, the rest of the row folds
    return {closed, html: `<div class="fhead ${sub ? 'fsub' : ''} ${closed ? 'closed' : ''} ${(active && closed) || fon ? 'on' : ''}" data-act="folder-toggle" data-folder="${esc(f)}" ${isMobile() || S.listReorder ? '' : 'draggable="true"'}>${ic('chev', 's fcar')}${ic('folder', 's')}<span class="n ${S.listReorder ? '' : 'fgo'}" ${S.listReorder ? '' : `data-go="${esc(keyToHash('folder:' + f))}" title="${esc(tr('Open {0}', fDisp(f)))}"`}>${esc(fName(f))}</span><span class="sr">${esc(closed ? tr('folded') : tr('unfolded'))}</span>${S.listReorder
      ? `<button class="iconbtn" data-fmove="-1" data-folder="${esc(f)}" title="${tr('move up')}">${ic('chev', 's up')}</button><button class="iconbtn" data-fmove="1" data-folder="${esc(f)}" title="${tr('move down')}">${ic('chev', 's')}</button>`
      : `<span class="c" ${n ? `aria-label="${esc(trn('{0} open task', '{0} open tasks', n))}"` : ''}>${n || ''}</span><button class="iconbtn fmenu" data-act="folder-menu" data-folder="${esc(f)}" title="${tr('Folder')}" aria-label="${esc(tr('Folder') + ' ' + fDisp(f))}">${ic('dots', 's')}</button>`}</div>`};
  };
  const fempty = () => `<div class="fempty">${isMobile() ? tr('empty: assign lists in sort mode') : tr('empty: drag a list here')}</div>`;
  for (const f of folderNames().filter(x => !fParent(x))) {
    const top = fhead(f), subs = folderSubs(f);
    lh += top.html;
    if (top.closed) continue;
    let body = lists.filter(l => l.folder === f).map(listRow).join('');
    for (const sf of subs) {
      const sh = fhead(sf);
      body += `<div class="fsubw">${sh.html}${sh.closed ? '' : `<div class="fbody" data-folder="${esc(sf)}">${lists.filter(l => l.folder === sf).map(listRow).join('') || fempty()}</div>`}</div>`;
    }
    lh += `<div class="fbody" data-folder="${esc(f)}">${body || fempty()}</div>`;
  }
  const archived = S.lists.filter(l => l.archived);
  const tags = Object.keys(c.tags).sort((a, b) => a.localeCompare(b, 'de'));
  const tagsOpen = S.collapsed.has('side:tags-open') || tags.some(t => onTasks && k === 'tag:' + t);
  // Focus: the smart lists
  const focus = [row('inbox', ic('inbox'), tr('Inbox'), c.lists[inbox()?.id]), row('today', ic('sun'), tr('Today'), c.today), row('tomorrow', ic('sunrise'), tr('Tomorrow'), c.tomorrow),
    row('week', ic('week'), tr('Next 7 days'), c.week), row('doable', ic('zap'), tr('Now doable'), c.doable),
    c.pinned || (onTasks && k === 'pinned') ? row('pinned', ic('pin'), tr('Pinned|view'), c.pinned) : '',  // 2.16.0 (#648): only while something is pinned
    c.waiting || (onTasks && k === 'waiting') ? row('waiting', ic('hourglass'), tr('Waiting on external'), c.waiting) : '',
    collab() && (hasSharing() || c.assigned) ? row('assigned', ic('user'), tr('Assigned to me'), c.assigned) : '',
    teamOn() && (hasSharing() || S.team?.unread) ? `<button class="srow ${S.route.mod === 'team' ? 'on' : ''}" data-go="team">${ic('comment')}<span class="n">${tr('Team chat')}</span><span class="c ${S.team?.unread ? 'nunread' : ''}">${S.team?.unread ? `${S.team.unread}<span class="sr"> ${esc(tr('unread'))}</span>` : ''}</span></button>` : '',  // 2.17.0 (#419)
    collab() && (hasSharing() || S.news?.unread) ? `<button class="srow ${S.route.mod === 'news' ? 'on' : ''}" data-go="news">${ic('bell')}<span class="n">${tr('News')}</span><span class="c ${S.news?.unread ? 'nunread' : ''}">${S.news?.unread || ''}</span></button>` : ''].join('');
  // Views: every switched-on module (the rail's old job)
  const aw = (S.agents || []).reduce((n, x) => n + x.waiting + x.chat_unread, 0);
  const views = [feat('cal') ? mrow('cal', 'cal', tr('Calendar')) : '',
    feat('timeline') ? `<button class="srow smod ${isRoadmap() ? 'on' : ''}" data-act="side-timeline">${ic('timeline')}<span class="n">${tr('Timeline')}</span></button>` : '',
    feat('matrix') ? mrow('matrix', 'grid', tr('Matrix')) : '', feat('habits') ? mrow('habits', 'habit', tr('Habits')) : '',
    feat('pomo') ? mrow('pomo', 'timer', tr('Focus (Pomodoro)'), S.pomo ? '<span class="c"><span class="recdot"></span></span>' : '') : '',
    timeOn() ? mrow('time', 'clock', tr('Time tracking'), S.timer ? '<span class="c"><span class="recdot"></span></span>' : '') : '',
    feat('stats') ? mrow('stats', 'chart', tr('Statistics')) : '',
    feat('contacts') ? mrow('contacts', 'users', tr('Contacts')) : '',  // 2.21.0 (#658)
    lifeOn() ? mrow('life', 'home', tr('Home & life')) : '',  // 2.22.0 (#663)
    feat('review') ? mrow('review', 'journal', tr('Review & journal')) : '',
    famOn() ? mrow('family', 'family', tr('Family'), (S.kids || []).some(k => (k.requests || 0) > 0) ? `<span class="c nunread">${(S.kids || []).reduce((n, k) => n + (k.requests || 0), 0)}</span>` : '') : '',
    overviewOn() ? mrow('overview', 'pulse', tr('Overview'), `<span class="c ${ovProblems() ? 'over' : ''}">${ovProblems() || ''}</span>`, `title="${esc(tr('Where is it stuck?'))}"`) : '',
    agentsTab() ? mrow('agents', 'bot', tr('Agents'), `<span class="c ${aw ? 'nunread' : ''}">${aw || ''}</span>`) : ''].join('');
  // Team: the people I share lists with (their tasks) and the agents (status dot; a click opens the chat)
  const ags = shownAgents(), ppl = teamPeople().slice(0, 12);
  // 2.10.0 (#441): my groups (admins: every group with a task); a click shows the tasks assigned to the group
  const grps = collab() ? (S.groups || []).filter(gr => myGroup(gr.id) || [...S.tasks.values()].some(t => t.status === 0 && t.assignee_group_id === gr.id)) : [];
  const gcount = gid => [...S.tasks.values()].filter(t => t.status === 0 && !t.deleted_at && t.assignee_group_id === gid).length;
  const team = [...grps.map(gr => `<button class="srow steam sgrp ${onTasks && k === 'grp:' + gr.id ? 'on' : ''}" data-go="grp/${gr.id}" title="${esc(tr('Tasks of the group {0}', gr.name))}">${ic('users')}<span class="n">${esc(gr.name)}</span><span class="sk">${tr('Group')}</span>${gcount(gr.id) ? `<span class="c">${gcount(gr.id)}</span>` : ''}</button>`),
    ...ppl.map(p => `<button class="srow steam ${onTasks && k === 'who:' + p.id ? 'on' : ''}" data-go="who/${p.id}" title="${esc(tr('Tasks of {0}', p.name))}"><span class="sdot"><i class="pdot"></i></span><span class="n">${esc(p.name)}</span><span class="sk">${tr('Person')}</span></button>`),
    ...ags.map(a => `<button class="srow steam" data-act="team-agent" data-aid="${a.id}" title="${esc(agentHstLine(a))}"><span class="sdot">${hdot(agentHst(a))}</span><span class="n">${esc(a.name)}</span><span class="sk">${tr('Agent')}</span>${a.waiting || a.chat_unread ? `<span class="c nunread">${a.waiting + a.chat_unread}</span>` : ''}</button>`)].join('');
  const grp = (g, label, body, acts = '', n = '', tip = '') => `<div class="sgroup sg-${g}">${head(g, label, acts, n, tip)}${sideOpen(g) ? body : ''}</div>`;
  // 2.13.3 (#478 follow-up, Fold): one search entry in the sidebar / drawer: the command-bar field (search, commands and the
  // "Search" view inside); no separate "Search" row any more (it doubled the field in the drawer, the field was missing on
  // an unfolded Fold)
  $('#side').innerHTML = `
    <div class="sbrand"><button type="button" class="sbhome ${S.route.mod === 'home' ? 'on' : ''}" data-go="home" title="${esc(tr('Dashboard'))}" aria-label="${esc(APP_NAME + ': ' + tr('Dashboard'))}" ${S.route.mod === 'home' ? 'aria-current="page"' : ''}>${logoSvg(20)}<span>${esc(APP_NAME)}</span>${S.me?.orgs?.[0] ? `<small class="sborg">${esc(S.me.orgs[0])}</small>` : ''}</button><span class="spacer"></span>${!isMobile() && innerWidth < 1100 ? `<button class="iconbtn sfold" data-act="side-fold" aria-pressed="${!!LS.get('sideFold', false)}" title="${esc(LS.get('sideFold', false) ? tr('Keep the sidebar open') : tr('Fold the sidebar away'))}" aria-label="${esc(LS.get('sideFold', false) ? tr('Keep the sidebar open') : tr('Fold the sidebar away'))}">${ic('chev', 's')}</button>` : ''}${S.me ? `<button type="button" class="sbacct" data-act="user-menu" aria-haspopup="menu" title="${esc(tr('Account') + ': ' + S.me.display_name)}" aria-label="${esc(tr('Account') + ': ' + S.me.display_name)}">${av(S.me.id, S.me.display_name)}${updDot() ? `<span class="dot" title="${esc(tr('Update available'))}"></span>` : ''}</button>` : ''}</div>
    <button class="scmd" data-act="palette" title="${esc(tr('Search and commands'))}">${ic('search', 's')}<span>${tr('Jump, create, ask an agent…')}</span></button>
    ${grp('focus', tr('Focus|nav'), focus)}
    ${views ? grp('views', tr('Views'), views) : ''}
    <div class="sgroup sg-lists">${head('lists', tr('Lists'), `<button data-act="lists-reorder" class="${S.listReorder ? 'on' : ''}" title="${tr('Sort lists')}">${ic('sort', 's')}</button><button data-act="list-new" title="${tr('New list')}">${ic('plus', 's')}</button>`, lists.length)}${sideOpen('lists') ? lh || `<div class="folder">${tr('No lists yet')}</div>` : ''}</div>
    ${grp('filters', tr('Filters'), S.filters.map(f => row('f:' + f.id, ic('filter'), f.name, c.filters[f.id])).join(''), `<button data-act="filter-new" title="${esc(tr('New filter') + ' · ' + tr('Combine lists, dates, priorities, tags'))}" aria-label="${tr('New filter')}">${ic('plus', 's')}</button>`, S.filters.length, tr('Combine lists, dates, priorities, tags'))}
    ${tags.length ? `<div class="sgroup"><button class="shead stoggle ${tagsOpen ? '' : 'closed'}" data-act="side-tags" aria-expanded="${tagsOpen}">${ic('chev', 's fcar')}<span class="spacer">${tr('Tags')}</span><span class="c">${tagsOpen ? '' : tags.length}</span></button>${tagsOpen ? tags.map(t => row('tag:' + t, ic('tag'), t, c.tags[t])).join('') : ''}</div>` : ''}
    ${team ? grp('team', tr('Team'), team, '', ppl.length + ags.length + grps.length) : ''}
    <div class="sgroup sfoot">
      ${row('all', ic('all'), tr('All'), c.all)}
      ${row('done', ic('done'), tr('Completed'), '')}
      ${row('trash', ic('trash'), tr('Trash'), S.counts.trash || '')}
      ${archived.length ? (() => {  // 1.6.1: one plain row like Trash; opens the "Archived" view (lit while an archived list is open too)
        const on = onTasks && (k === 'archived' || archived.some(l => k === 'l:' + l.id));
        return `<button class="srow sarch ${on ? 'on' : ''}" data-go="archived">${ic('archive')}<span class="n">${tr('Archived')}</span><span class="c">${archived.length}</span></button>`;
      })() : ''}
      <button class="srow sset" data-act="settings" title="${esc(kt(tr('Settings'), 'g s'))}">${ic('gear')}<span class="n">${tr('Settings')}</span>${updDot() ? `<span class="c nunread" title="${esc(tr('Update available'))}">●</span>` : ''}</button>
    </div>`;
  sideRove();
}
// 2.13.0 (#453 A9): the sidebar is ONE tab stop (roving tabindex): Tab lands on the open view's row (or the first one),
// ↑ / ↓ / Home / End walk through every row, folder and group header, Enter / Space open it, Tab goes on to the content.
// Before, 30+ stops stood between the top of the page and the content.
const sideItems = () => $$('#side button, #side [data-act="folder-toggle"], #side a[href]').filter(b => !b.disabled && b.offsetParent !== null && !b.closest('.hidden'));
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
  const MT = {cal: N_('Calendar'), matrix: N_('Eisenhower matrix'), habits: N_('Habits'), pomo: N_('Focus'), news: N_('News'), stats: N_('Statistics'), time: N_('Time tracking'), overview: N_('Where is it stuck?'), agents: N_('Agents'), team: N_('Team chat'), home: N_('Dashboard'), family: N_('Family'), contacts: N_('Contacts'), life: N_('Home & life'), review: N_('Review & journal')};
  let title = m === 'tasks' ? titleFor(k) : m === 'notes' ? tr('Notes') + ' · ' + (lname(listById(S.nt.lid)) || '') : m === 'family' && S.me?.kid ? tr('My day') : MT[m] ? tr(MT[m]) : '';
  if (m === 'matrix' && mxTitle()) title = `${tr('Matrix')} · ${mxTitle()}`;
  let acts = '';
  if (m === 'tasks' && (k.startsWith('l:') || k === 'inbox')) {
    const l = k === 'inbox' ? inbox() : listById(+k.slice(2));
    if (l) {
      const v = curView(l), vc = viewChoices(l);  // 2.7.1 (#410): + "Project overview" in project lists
      // 2.8.0 (#434): the view switch as text tabs (List / Kanban / Timeline / Project overview)
      if (vc.length > 1 && !isMobile()) acts += `<div class="seg vseg ttabs tf" role="group" aria-label="${esc(tr('View'))}">${vc.map(([k, n, i]) => `<button class="${v === k ? 'on' : ''}" data-act="view-${k}" data-ico="${i}" title="${esc(tr(n))}" aria-pressed="${v === k}">${esc(tr(n))}</button>`).join('')}</div>`;
      // 2.14.0 (#425): "Columns…" (the list's columns for every member) replaces the per-device field-column switch
      if (!isMobile() && v === 'list' && !l.archived) acts += `<button class="iconbtn tf ${listCols(l) ? 'on' : ''}" data-act="cols" data-ico="columns" data-id="${l.id}" title="${esc(tr('Columns…'))}" aria-label="${esc(tr('Columns…'))}" aria-haspopup="dialog">${ic('columns')}</button>`;
      // 2.6.0 (K12): Share next to the title (desktop / tablets; phones: in "…")
      if (!l.is_inbox && !l.archived && collab() && !isMobile()) acts += `<button class="iconbtn tf shbtn" data-act="share-list" data-ico="users" data-id="${l.id}" title="${esc(tr('Share…'))}" aria-label="${esc(tr('Share…'))}">${ic('users', 's')}<span class="bl">${tr('Share')}</span></button>`;
    }
  }
  // 2.4.2 (#390): a folder switches between its list view and the matrix of all its lists (subfolders included), like a list
  const fk = m === 'tasks' && k.startsWith('folder:') ? k.slice(7) : m === 'matrix' && mxGet().scope.startsWith('folder:') ? mxGet().scope.slice(7) : '';
  if (fk && feat('matrix') && !isMobile()) acts += `<div class="seg vseg fseg tf" role="group" aria-label="${esc(tr('View'))}"><button class="${m === 'tasks' ? 'on' : ''}" data-act="fview" data-k="list" data-ico="list" data-f="${esc(fk)}" title="${esc(tr('List'))}" aria-pressed="${m === 'tasks'}">${ic('list', 's')}</button><button class="${m === 'matrix' ? 'on' : ''}" data-act="fview" data-k="matrix" data-ico="grid" data-f="${esc(fk)}" title="${esc(tr('Matrix'))}" aria-pressed="${m === 'matrix'}">${ic('grid', 's')}</button></div>`;
  if (m === 'tasks' && k === 'all' && feat('timeline')) { const v = isRoadmap() ? 'timeline' : 'list'; acts += `<div class="seg tf" role="group" aria-label="${tr('View')}"><button class="${v === 'list' ? 'on' : ''}" data-act="rm-view" data-k="list" data-ico="list" title="${tr('List')}" aria-pressed="${v === 'list'}">${ic('list', 's')}</button><button class="${v === 'timeline' ? 'on' : ''}" data-act="rm-view" data-k="timeline" data-ico="timeline" title="${tr('Timeline')}" aria-pressed="${v === 'timeline'}">${ic('timeline', 's')}</button></div>`; }
  if (m === 'tasks' && k === 'trash' && (S.extra || []).some(t => !t.keep)) acts += `<button class="btn sm danger" data-act="trash-empty">${tr('Empty')}</button>`;
  if (m === 'tasks' && k === 'done' && (S.extra || []).length) acts += `<button class="btn sm" data-act="done-clean" title="${esc(tr('Move completed tasks to the trash'))}">${ic('trash', 's')}<span class="bl">${tr('Delete completed…')}</span></button>`;
  if (m === 'tasks' && S.multiMode) acts += `<button class="iconbtn on" data-act="multi" title="${tr('End selection')}" aria-label="${tr('End selection')}">${ic('select')}</button>`;
  // everything rarer sits in "…" (phones: undo / redo there too); the title keeps its room
  acts += `<button class="iconbtn tmore" data-act="top-more" aria-haspopup="menu" title="${tr('More actions')}" aria-label="${tr('More actions')}">${ic('dots')}${isMobile() && HIST.undo.length && histPending(HIST.undo[HIST.undo.length - 1]) ? '<span class="pdot"></span>' : ''}</button>`;
  const pm = '';  // focus / stopwatch are part of the running indicator (timerPill) now
  const oflab = OUT.online ? tr('sync|pending changes') : OUT.down ? tr('server not reachable') : tr('offline'), ofn = OUT.q.length ? trn('{0} change waiting', '{0} changes waiting', OUT.q.length) : '';
  const off = !OUT.online || OUT.q.length ? `<span class="offline" role="status" title="${esc([oflab, ofn, tr('Changes are sent as soon as the server is reachable')].filter(Boolean).join(' · '))}" aria-label="${esc([oflab, ofn].filter(Boolean).join(' · '))}">${ic(OUT.online ? 'sync' : 'cloudoff', 's')}<span class="ofl">${oflab}</span>${OUT.q.length ? `<span class="ofn">${OUT.q.length}</span>` : ''}</span>` : '';
  const cf = S.conflicts?.length ? `<button class="cfpill" data-act="conflicts" title="${tr('Review conflicts')}">${ic('alert', 's')}${S.conflicts.length}</button>` : '';
  // open tasks of the view next to the title (Geist Mono), task views only
  const nOpen = m === 'tasks' && !NOLIST_KEYS.includes(k) ? viewTasks().open.length : 0;
  // 2.8.0 (#434): the command bar (search + commands + the agents' chat) and "New task" (mouse screens; touch has the + button)
  // 2.18.0 (#651, owner decision: the magnifier is always visible): Search never folds into "…" (no .tf4); the title gets cut instead (fitTop)
  const pal = `<button class="kbtn cmdbar" data-act="palette" data-ico="search" title="${esc(tr('Search and commands'))} (${kbText('Mod+K')})" aria-label="${esc(tr('Search and commands'))}">${ic('search', 's')}<span>${tr('Jump, create, ask an agent…')}</span>${kb('Mod+K')}</button>`;
  const tnew = (!isTouch() || ((!isMobile() || tabletDock()) && !dockView())) && (m === 'tasks' || (m === 'cal' && isTouch())) && !noFab() && !S.multiMode ? `<button class="btn pri tnew tf4" data-act="new-task" data-ico="plus" title="${esc(kt(tr('New task'), 'n'))}" aria-label="${esc(tr('New task'))}">${ic('plus', 's')}<span>${tr('New task')}</span></button>` : '';
  const ms = (() => {  // the next open milestone of a project list
    const l = m === 'tasks' && k.startsWith('l:') ? listById(+k.slice(2)) : null;
    const x = l?.kind === 'project' ? (l.milestones || []).filter(y => !y.done).sort((a, b) => a.day.localeCompare(b.day))[0] : null;
    return x ? `<span class="hms ${x.day < today() ? 'over' : ''}" title="${esc(tr('Milestone') + ': ' + x.name + ', ' + fmtDateLoc(x.day))}">◆ ${esc(x.name)} · ${esc(dayLabel(x.day))}</span>` : '';
  })();
  const kl = m === 'tasks' && k.startsWith('l:') ? listById(+k.slice(2)) : null;
  const badge = kl?.kind === 'project' ? `<span class="kbadge" title="${esc(projectParts().join(', '))}">${tr('Project')}</span>` : '';
  S.bandOn = bandAgents().length > 0;  // 2.8.0 (#434): the band shows the agents' dots, the header pill keeps only the robot
  setHtml($('#top'), `<button class="iconbtn menu" data-act="side" aria-label="${tr('Menu')}">${ic('menu')}</button><h1 title="${esc(title)}">${kl?.icon ? licon(kl, 'licon h') : ''}<span class="ht">${esc(title)}</span>${badge}${nOpen ? `<span class="hn" aria-label="${esc(trn('{0} open task', '{0} open tasks', nOpen))}">${nOpen}</span>` : ''}${ms}</h1>${cf}${off}${timerPill()}${pm}${acts}${isMobile() ? '' : histBtns()}${pal}${tnew}${stChip()}${agentChip()}${bellBtn()}`);  // 2.7.2 (#417): the agents' robot + dots directly before the bell  // 2.7.0 (#405): touch tablets / an unfolded Fold have the room for ← →
  fitTop();
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
// jsdom has no layout (every width is 0), so there everything fits at level 0.
const TOP_LVLS = 4;
let topW = 0;
function topLevel() { const t = $('#top'); const m = t && /\btl(\d)\b/.exec(t.className); return m ? +m[1] : 0; }
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
    for (let i = 1; i <= TOP_LVLS; i++) t.classList.toggle('tl' + i, i === l);
    if (more) more.hidden = !topMoreItems().length;
    // the title never gets less than its first 12 characters (plus its icon / badge / count): the rest has to make room
    if (h1 && nd) {
      const kids = [...h1.children].filter(e => e !== ht && e.offsetWidth), gap = parseFloat(getComputedStyle(h1).columnGap) || 0;
      const nn = cut || nd;
      h1.style.minWidth = Math.ceil(kids.reduce((n, e) => n + e.getBoundingClientRect().width, 0) + gap * kids.length + Math.min(nn.need, nn.full) + 1) + 'px';
    }
  };
  set(0);
  if (!t.clientWidth) return;  // no layout (hidden, jsdom)
  // the lowest level that shows the whole title; otherwise the one that gives the title the most room
  // 2.18.0 (review R3, owner rule: frequently used one-tap actions stay visible, the title shortens instead): the folding
  // levels (tl3 / tl4: view switch, undo / redo, Share, New task into "…") are only taken when nothing fits with the title
  // cut to its minimum at a non-folding level (tl0 - tl2 only make the pills more compact)
  let best = -1, wide = -1, ww = -1;
  for (let l = 0; l <= TOP_LVLS; l++) {
    if (l >= 3 && wide >= 0) break;  // the title is already cut to >= 12 characters without folding anything
    if (l) set(l);
    const f = topFits(t, ht, nd);
    if (f === 2) { best = l; break; }
    const w = f ? ht.getBoundingClientRect().width : -1;
    if (f && l >= 3) { wide = l; break; }  // the first folding level that fits wins (fold as little as possible)
    if (f && w > ww + 4) { wide = l; ww = w; }
  }
  if (best < 0 && wide < 0 && nd) {
    for (const k of [6, 4, 2]) { cut = topNeed(ht, k); set(TOP_LVLS); if (topFits(t, null, null)) return; }
  }
  set(best >= 0 ? best : wide >= 0 ? wide : TOP_LVLS);
}
if (document.fonts?.ready) document.fonts.ready.then(() => fitTop()).catch(() => {});
if (typeof ResizeObserver !== 'undefined') {
  let topRO = null;
  const topWatch = () => { const t = $('#top'); if (!t || topRO) return; topRO = new ResizeObserver(() => { if (t.clientWidth !== topW) fitTop(); }); topRO.observe(t); };
  if (document.readyState === 'loading') addEventListener('DOMContentLoaded', topWatch); else topWatch();
} else addEventListener('resize', () => fitTop());
// the header items that moved into "…" (tl3 / tl4), as menu items that click the hidden button
function topFolded() {
  const l = topLevel(); if (l < 3) return [];
  const els = $$('#top .tf [data-act], #top [data-act].tf' + (l >= 4 ? ', #top [data-act].tf4' : ''));
  return els.filter(b => !b.disabled || b.closest('.hist')).map(b => ({label: (b.getAttribute('aria-label') || b.title || b.textContent || '').replace(/\s*\([^)]*\)\s*$/, '').trim(), icon: b.dataset.ico || (/hist-undo/.test(b.dataset.act) ? 'undo' : /hist-redo/.test(b.dataset.act) ? 'redo' : ''),
    on: b.classList.contains('on'), dis: b.disabled, fn: () => b.click()}));
}
// UX1 (U01, owner decision 4): the header's "…" menu. Phones: "Undo: …" / "Redo: …" first (no ← → there), then the rarer
// view actions (select, sort), then the list's own menu or the filter
function topMoreItems() {
  if (S.me?.kid) return [{label: tr('Account'), icon: 'user', fn: () => settingsModal('account')}, {label: tr('Settings'), icon: 'gear', fn: () => settingsModal()},
    ...(S.me?.auth === 'session' ? ['-', {label: tr('Log out'), icon: 'logout', fn: logout}] : [])];  // 2.19.0: a child's "…": its account only
  const m = S.route.mod, k = S.route.key, fold = topFolded(), out = [], sec = [];
  if (isMobile()) for (const dir of ['undo', 'redo']) { const b = histBtn(dir); out.push({label: b.lab, icon: dir, dis: b.off, cls: 'hmi' + (b.p ? ' pend' : ''), title: b.p ? tr('waiting for the connection') : '', fn: () => histStep(dir)}); }
  if (m === 'tasks' && !NOLIST_KEYS.includes(k) && !isKanban() && !isTimeline() && !isRoadmap() && !isOverview())
    sec.push({label: S.multiMode ? tr('End selection') : tr('Select multiple'), icon: 'select', on: S.multiMode, fn: () => { S.multiMode = !S.multiMode; if (!S.multiMode) S.multi.clear(); render(); }},
      {label: tr('Sort…'), icon: 'sort', fn: () => sortMenu($('#top [data-act="top-more"]') || $('#top h1'))});
  { const cl = m === 'tasks' ? routeList() : null; if (cl && !cl.archived && listView(cl) === 'list' && !isOverview()) sec.push(colItem(cl.id)); }  // 2.14.0 (#425)
  if (doneToggleView()) sec.push(doneItem());
  { const rl = m === 'tasks' ? routeList() : null; if (rl && isOwner(rl) && !rl.is_inbox && listView(rl) === 'list' && !isOverview()) sec.push(dabItem(rl)); }  // 2.7.2 (#414)
  sec.push(...collapseItems());
  const mxk = m === 'tasks' ? (k === 'inbox' ? 'l:' + inbox()?.id : k.startsWith('l:') || k.startsWith('f:') || k.startsWith('folder:') ? k : '') : '';
  if (mxk && feat('matrix')) sec.push({label: tr('Show as matrix'), icon: 'grid', fn: () => { mxSet({scope: mxk}); go('matrix'); }});
  const mxs = m === 'matrix' ? mxGet().scope : '';  // 2.4.2 (#390): back from the matrix to the folder / list it shows
  if (mxs.startsWith('folder:') || mxs.startsWith('l:') || mxs.startsWith('f:')) sec.push({label: tr('Show as list'), icon: 'list', fn: () => go(keyToHash(mxs))});
  if (m === 'tasks' && k.startsWith('f:')) sec.push({label: tr('Edit filter'), icon: 'edit', fn: () => filterModal(+k.slice(2))});
  const l = m === 'tasks' && (k.startsWith('l:') || k === 'inbox') ? (k === 'inbox' ? inbox() : listById(+k.slice(2))) : null;
  // 2.13.0 (#453 A7): phones switch the view with the segmented control under the title (vsegHtml), no longer here
  if (l) { if (sec.length && sec[sec.length - 1] !== '-') sec.push('-'); sec.push(...listMenuItems(l.id, () => $('#top [data-act="top-more"]') || $('#top h1')).filter(x => !(x.cls === 'mcols' && sec.some(y => y.cls === 'mcols')))); }
  if (m === 'tasks' && k.startsWith('tag:')) { if (sec.length) sec.push('-'); sec.push(tagDeleteItem(k.slice(4))); }
  if (S.route.mod === 'tasks' && sharedRoute()) sec.unshift({label: tr('Refresh'), icon: 'sync', fn: () => refreshNow()});  // 2.7.2 (#433): no header button any more
  const rest = [...out, ...(out.length && sec.length ? ['-'] : []), ...sec];
  // 2.6.0 (K01): "…" is there on every view; where a view has nothing of its own it offers search (+ the shortcuts)
  if (!rest.length && !fold.some(x => x.icon === 'search')) rest.push({label: tr('Search and commands'), icon: 'search', keys: 'Mod+K', fn: () => openPalette()}, ...(isTouch() ? [] : [{label: tr('Keyboard shortcuts'), icon: 'help', keys: '?', fn: shortcutsModal}]));
  // 2.13.0 (#453 A7): an entry that is already there (a folded header button, e.g. "Share…") comes only once
  const seen = new Set(fold.map(x => x.label)), rest2 = rest.filter(x => x === '-' || x.row || !seen.has(x.label));
  return [...fold, ...(fold.length && rest2.length ? ['-'] : []), ...rest2].filter((x, i, a) => x !== '-' || (i > 0 && a[i - 1] !== '-' && i < a.length - 1));
}
// ---- 1.9.0: delete a tag completely (sidebar: right-click / long-press on the tag, or "…" in the tag view). Tags are
// personal: only my tag goes, from every task that has it (the tasks stay); one step in the undo history.
const tagDeleteItem = tag => ({label: tr('Delete tag…'), icon: 'trash', cls: 'danger', fn: () => tagDelete(tag)});
function tagMenu(anchor, tag) {
  menu(anchor, [{label: tr('Open'), icon: 'tag', fn: () => go('tag/' + encodeURIComponent(tag))}, '-', tagDeleteItem(tag)]);
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
  try { await flushSaves(); await load(); render(); if (S.sel && (cmtOn() || collab())) loadTimeline(S.sel); S.syncOk = Date.now(); toast(tr('Up to date')); }
  catch (e) { if (e instanceof Offline) toast(tr('You are offline')); }
  finally { refreshing = false; $$('[data-act="refresh"]').forEach(b => b.classList.remove('spin')); }
}
function routeList() {
  const k = S.route.key;
  if (S.route.mod !== 'tasks') return null;
  return k === 'inbox' ? inbox() : k.startsWith('l:') ? listById(+k.slice(2)) : null;
}
const listView = l => ((l.view === 'kanban' && feat('kanban')) || (l.view === 'timeline' && feat('timeline'))) ? l.view : 'list';
function isKanban() { const l = routeList(); return !!l && !povOn(l) && listView(l) === 'kanban'; }
function isTimeline() { const l = routeList(); return !!l && !povOn(l) && listView(l) === 'timeline'; }
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
window.addEventListener('resize', () => { if (S.route?.mod === 'cal') calFit(); });
// 2.13.2 (#478 N2): a re-render (live updates of agents, comments, jobs) never takes the keyboard focus away: a focused
// button / link / cell of the rebuilt area gets its focus back on its new copy (same tag + data-* / id, same position
// among equal ones), so Tab goes on from there instead of falling back to the start (the "tab ping-pong")
function focusSig(el) {
  if (el.id) return '#' + CSS.escape(el.id);
  const a = [...el.attributes].filter(x => /^data-/.test(x.name) && x.name !== 'data-k').map(x => `[${x.name}="${CSS.escape(x.value)}"]`).join('');
  return el.tagName.toLowerCase() + a + (a ? '' : el.getAttribute('aria-label') ? `[aria-label="${CSS.escape(el.getAttribute('aria-label'))}"]` : '');
}
// While such an element has the focus the area is not rebuilt but morphed (setHtml -> morphKids: same nodes where tag and
// key match, only attributes / text change), so the focused node itself stays in place: browsers keep their Tab position
// only on the same node (Firefox went back to the previous element after a refocus on a new copy).
let morphRoot = null;
function setHtml(el, html) {
  if (morphRoot !== el) { el.innerHTML = html; return; }
  const t = document.createElement('template'); t.innerHTML = html; morphKids(el, t.content);
}
const mkey = n => n.nodeType !== 1 ? null : ['data-k', 'data-id', 'data-cid', 'data-aid', 'data-jid', 'data-mid', 'data-key', 'data-section'].map(k => n.getAttribute(k)).find(v => v != null) ?? null;
function morphKids(a, b) {
  const an = [...a.childNodes], bn = [...b.childNodes];
  bn.forEach((n, i) => {
    const o = an[i];
    if (!o) { a.appendChild(n); return; }
    if (o.nodeType !== n.nodeType || o.nodeName !== n.nodeName || (o.nodeType === 1 && (o.id !== n.id || mkey(o) !== mkey(n)))) { a.replaceChild(n, o); return; }
    if (o.nodeType !== 1) { if (o.data !== n.data) o.data = n.data; return; }
    for (const x of [...o.attributes]) if (!n.hasAttribute(x.name)) o.removeAttribute(x.name);
    for (const x of [...n.attributes]) if (o.getAttribute(x.name) !== x.value) o.setAttribute(x.name, x.value);
    if (!o.isEqualNode(n)) morphKids(o, n);
    if (/^(INPUT|SELECT|TEXTAREA)$/.test(o.nodeName) && o !== document.activeElement) { if (o.type === 'checkbox' || o.type === 'radio') o.checked = n.checked; else if (o.type !== 'file' && o.value !== n.value) o.value = n.value; }
  });
  for (let i = an.length - 1; i >= bn.length; i--) an[i].remove();
}
function keepFocus(root, fn) {
  const a = document.activeElement;
  if (!root || !a || a === document.body || !root.contains(a) || editFocused()) return fn();
  let sig = null, i = 0;
  try { sig = focusSig(a); i = [...root.querySelectorAll(sig)].indexOf(a); } catch { sig = null; }
  // views that wire their DOM after rendering (calendar, timeline, roadmap) are always rebuilt
  const prev = morphRoot; morphRoot = root.id === 'view' && /^(cal)$/.test(S.route.mod) || $('#tlscroll', root) ? null : root;
  let r; try { r = fn(); } finally { morphRoot = prev; }
  if (!sig || (a.isConnected && document.activeElement === a)) return r;
  const cur = document.activeElement;
  if (cur && cur !== document.body && cur !== a) return r;  // the render moved the focus on purpose
  let n = null; try { const all = root.querySelectorAll(sig); n = all[Math.max(0, Math.min(i, all.length - 1))]; } catch { /* odd selector */ }
  if (n && n.offsetParent !== null && !n.disabled) n.focus({preventScroll: true});
  return r;
}
function renderView() { const r = keepFocus($('#view'), renderView0); rowRove(); rowMoreWatch(); return r; }
function renderView0() {
  const m = S.route.mod, el = $('#view');
  // 2.12.2 (#451): the open phone chat is never rebuilt (that took the focus, closed the keyboard and jumped to the top):
  // it is patched in place
  if (m === 'agents' && S.route.agent && chatFull() && S.chat.aid === +S.route.agent && $('#view .chview')?.dataset.aid === String(S.chat.aid) && $('#chat-in')) { chatPatch(); agentLive(); renderMultiBar(); return; }
  const scroll = el.scrollTop;
  const wbs = $('#wbody')?.scrollTop, tls = $('#tlscroll')?.scrollLeft, tlt = $('#tlscroll')?.scrollTop, wasRm = !!$('.tl.rm');
  const qi = $('#qinput'), qf = !!qi && document.activeElement === qi, qv = qi ? qi.value : '';  // the composer survives a re-render
  const tin = $('#view .ttlin'), tinF = !!tin && document.activeElement === tin;  // 2.0.2: inline title edit + section input too
  if (tin && S.ie) { S.ie.v = tin.value; S.ie.s = tin.selectionStart; S.ie.e = tin.selectionEnd; }
  const sai = $('#view .secadd-in'), saiF = !!sai && document.activeElement === sai;
  // 2.12.2 (#453 B2): any other focused field of the view (Kanban "+ Task", search, …) comes back with its text, caret and focus
  const fa = document.activeElement, fk = fa && el.contains(fa) && editFocused() && fa !== qi && fa !== tin && fa !== sai
    ? (fa.id ? () => document.getElementById(fa.id) : 'kadd' in fa.dataset ? () => [...el.querySelectorAll('[data-kadd]')].find(x => x.dataset.kadd === fa.dataset.kadd) : null) : null;
  const fv = fk && fa.value, fs = fk && [fa.selectionStart, fa.selectionEnd];
  if (sai && S.secAdd) S.secAdd.v = sai.value;
  if (m !== 'cal') el.classList.remove('calfit');
  if (m === 'cal') { setHtml(el, viewCal()); requestAnimationFrame(calFit); }
  else if (m === 'matrix') setHtml(el, viewMatrix());
  else if (m === 'habits') setHtml(el, viewHabits());
  else if (m === 'pomo') { setHtml(el, viewPomo()); loadPomoStats(); }
  else if (m === 'news') setHtml(el, viewNews());
  else if (m === 'stats') setHtml(el, viewStats());
  else if (m === 'time') setHtml(el, viewTime());
  else if (m === 'overview') setHtml(el, viewOverview());
  else if (m === 'agents') setHtml(el, viewAgents());
  else if (m === 'team') { setHtml(el, viewTeam()); if (S.tc.fitUntil > Date.now()) teamFit(true); }  // 2.17.0 (#419); 2.17.2: a room opened by its address ends at the newest message
  else if (m === 'notes') setHtml(el, viewNotes());  // 2.17.0 (#442)
  else if (m === 'home') setHtml(el, viewHome());  // 2.17.0 (#475)
  else if (m === 'family') setHtml(el, viewFamily());  // 2.19.0 (#653)
  else if (m === 'contacts') setHtml(el, viewContacts());  // 2.21.0 (#658)
  else if (m === 'life') setHtml(el, viewLife());  // 2.22.0 (#663)
  else if (m === 'review') setHtml(el, viewReview());
  else if (S.route.key === 'search') setHtml(el, viewSearch());
  else if (S.route.key === 'done' || S.route.key === 'trash') setHtml(el, viewHistory());
  else if (S.route.key === 'archived') setHtml(el, viewArchived());
  else if (isRoadmap()) setHtml(el, viewRoadmap());
  else if (isOverview()) setHtml(el, viewProjOv());  // 2.7.1 (#410)
  else if (isKanban()) setHtml(el, viewKanban());
  else if (isTimeline()) setHtml(el, vsegHtml(routeList()) + viewTimeline(routeList().id));  // 2.13.0 (#453 A7)
  else setHtml(el, viewList());
  el.scrollTop = scroll;
  if (m === 'agents' && $('#view .chview')) { chatFit(); chatPatch({bottom: true}); } else document.body.classList.remove('kb-open');  // 2.12.2 (#451): a chat opens at its newest message
  if (S.ie) inlineEditMount(tinF);
  const sa2 = $('#view .secadd-in'); if (sa2 && S.secAdd) { sa2.value = S.secAdd.v || ''; if (saiF) sa2.focus(); }
  const q2 = $('#qinput'); if (q2 && qi && q2 !== qi) { q2.value = qv; if (qf) { q2.focus(); updateChips(q2); } }
  const wb = $('#wbody'); if (wb) wb.scrollTop = wbs ?? 7 * weekH() - 12;  // 2.15.1 (#633): the 07:00 label in full, not cut at the top
  const tl = $('#tlscroll');
  if (tl && isRoadmap()) { const keep = wasRm && !S.rmScrollReset; S.rmScrollReset = false; rmAfterRender(tl, keep ? tls : undefined, keep ? tlt : undefined); }
  else if (tl) { tl.scrollLeft = tls ?? Math.max(0, diffDays(S.tlStart, today()) - 2) * tlDW(); tlAfterRender(tl); }
  else if (S.tlPick) S.tlPick = null;  // left the timeline: "Connect to…" ends
  renderMultiBar();
  const f2 = fk && fk();
  if (f2 && f2 !== fa && document.activeElement !== f2) { if (fv != null && 'value' in f2) f2.value = fv; f2.focus({preventScroll: true}); try { if (fs[0] != null) f2.setSelectionRange(fs[0], fs[1]); } catch { /* no caret */ } }
  if (S.route.key === 'search') { const i = $('#searchq'); if (i && document.activeElement !== i) { i.value = S.searchQ || ''; if (!isMobile() || S.searchFocus) i.focus(); } S.searchFocus = false; }
}

// ------------------------------------------------------------------ render: task rows
function taskRow(t, opts = {}) {
  const kids = S.tasks.size ? children(t.id) : [];
  const openKids = kids.filter(k => k.status === 0).length;
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
  if (t.ttype && !opts.trash && ticketsOn(t.list_id)) meta.push(ttChip(t));  // 2.4.0 (#340)
  if (isMs(t)) meta.push(`<span class="msm${t.due ? ' sr' : ''}">${t.due ? esc(tr('Milestone')) : `<i class="msd" aria-hidden="true"></i>${esc(tr('Milestone without a date'))}`}</span>`);  // 2.18.0 (#430)
  else if (t.milestone_id && !opts.trash && !opts.subRow) meta.push(msChip(t));
  if (isOcc(t) && famOn() && t.status === 0 && occWhat(t)) meta.push(`<span class="occm">${ic('cake', 's')}${esc(occWhat(t))}</span>`);  // 2.19.0 (#653)
  if (t.rotation?.who?.length > 1 && famOn() && t.status === 0 && !opts.trash) meta.push(`<span class="rotm" title="${esc(tr('Takes turns'))}">${ic('turns', 's')}<span class="sr">${esc(tr('Takes turns'))}</span></span>`);
  if (t.context) meta.push(`<span class="ctxm" title="${esc(tr('The main task of a subtask assigned to you: read-only, without notes, files and comments'))}">${ic('sub', 's')}${tr('Context')}</span>`);
  // 2.0.4 (#308): "Ready to start" only when the view has dependencies at all (see renderList); a button: tap / click
  // explains where it comes from (toast), without opening the task
  if (opts.next && !opts.depth) meta.push(`<button type="button" class="nxt" data-act="flow-why" title="${esc(tr(FLOW_WHY))}" aria-label="${esc(tr('Ready to start|flow') + ': ' + tr(FLOW_WHY))}">${ic('arrow', 's')}<span class="nxl">${tr('Ready to start|flow')}</span></button>`);
  if (!lc && t.blocked && t.status === 0 && !opts.trash && dFor(t)) meta.push(`<span class="blk" title="${esc(blockedTitle(t))}">${ic('lock', 's')}${tr('waiting')}</span>`);
  if (t.waiting_at && t.status === 0 && !opts.trash) meta.push(waitChip(t));  // 2.1.0 (#335)
  if (t.pinned && !opts.trash) meta.push(`<span class="pinm">${ic('pin', 's')}</span>`);
  if (lst) meta.push(`<span class="lst${mc}" title="${esc(lst)}">${esc(lst)}</span>`);
  // 2.16.0 (#473): overdue is not only red: the alert icon + a word for screen readers
  if (t.due && !opts.checklist && !lc) meta.push(`<span class="dt ${dueClass(t)}${mc}">${dueClass(t) === 'over' ? ic('alert', 's') + `<span class="sr">${tr('Overdue')}: </span>` : ic('cal', 's')}${due}</span>`);
  if (t.repeat && !opts.checklist) meta.push(`<span>${ic('repeat', 's')}</span>`);
  if (t.reminders && t.due && !opts.checklist) meta.push(`<span${nagOf(t) ? ` class="nagm" title="${esc(tr('Repeat reminder') + ': ' + nagLabel(nagOf(t)))}"` : ''}>${ic('bell', 's')}${nagOf(t) ? ic('repeat', 's') : ''}</span>`);
  if (t.deadline && t.due && !opts.checklist && !opts.trash) meta.push(dlChip(t));  // 2.7.0 (#412)
  if (kids.length && !lc) meta.push(`<span class="subc">${ic('sub', 's')}${kids.length - openKids}/${kids.length}</span>`);
  if (t.content && !opts.compact) meta.push(`<span>${ic('edit', 's')}</span>`);
  if (t.attachments?.length) meta.push(`<span>${ic('clip', 's')}${t.attachments.length}</span>`);
  if (t.paperless?.length && plOn()) meta.push(`<span>${ic('archive', 's')}${t.paperless.length}</span>`);
  if (t.url) meta.push(`<a class="lnk" href="${esc(t.url)}" target="_blank" rel="noopener noreferrer" title="${esc(t.url)}">${ic('link', 's')}${esc(urlHost(t.url))}</a>`);
  if (tFor(t) && t.id > 0) {
    const [ta, tm] = taskTime(t.id), live = S.timer && S.timer.task_id === t.id;
    if (ta >= 60 || live) {
      const tip = esc(live ? tr('Timer running') : ta - tm >= 60 ? tr('{0} in total, {1} by you', fmtDur(ta), fmtDur(tm)) : tr('Tracked: {0}', fmtDur(ta)));
      if (!lc) meta.push(`<span class="tchip ${live ? 'live' : ''}${mc}" data-tt="${t.id}" title="${tip}">${ic('clock', 's')}<b>${fmtDur(ta)}</b></span>`);
      time = {live, tip, txt: fmtDur(ta)};
    }
  }
  if (planOf(t) && !opts.trash) meta.push(`<span class="pchip" title="${esc(tr('Planned: {0}', planLabel(t)))}">${ic('clock', 's')}<b>${esc(planLabel(t, true))}</b></span>`);  // 2.11.0
  if (t.code?.prs?.length && !opts.trash) meta.push(codeChip(t));  // 2.2.0 (#271)
  if (t.comment_count && cmtOn()) meta.push(`<span class="cmc ${t.unread ? 'unread' : ''}" title="${esc(t.unread ? trn('{0} new comment', '{0} new comments', t.unread) : trn('{0} comment', '{0} comments', t.comment_count))}">${ic('comment', 's')}${t.comment_count}</span>`);
  const ac = !lc && !opts.trash && t.id > 0 && acolOn(t.list_id);  // 1.10.0: assignee column (own cell, click = assign)
  if (ac) who = whoCell(t);
  else if (lc) { /* 2.14.0: the assignee is a column or not shown */ }
  else if (t.assignee_group_id && collab()) {  // 2.10.0 (#441): assigned to a group
    const gc = grpChip(t);
    meta.push(gc);
    if (tc) who = gc;
  } else if (t.assignee_id && collab()) {
    const name = personName(t.list_id, t.assignee_id), cls = `who ${S.me && t.assignee_id === S.me.id ? 'me' : ''}`, tip = esc(tr('Assigned to {0}', name || '?'));
    const pv = isTouch() ? av : avBtn;  // 2.7.2 (#418): the picture opens the person card (touch: the row opens the task)
    meta.push(pv(t.assignee_id, name, cls + mc, `title="${tip}"`));
    if (tc) who = pv(t.assignee_id, name, cls, `title="${tip}"`);
  }
  if (!opts.cols && !opts.trash && !lc) for (const f of fieldsOf(t.list_id).filter(x => x.pinned)) { const c = fieldChip(f, t.fields?.[f.id], t.list_id); if (c) meta.push(c); }
  if (!lc) for (const g of t.ltags || []) meta.push(ltagChip(g, t.list_id));
  if (!lc) for (const g of t.tags) meta.push(ptagChip(g, t.list_id));
  // 2.0.8 (#319): sorted by "Created": a small creation date on the row
  if (!lc && !opts.trash && !opts.checklist && t.created_at && opts.crd) meta.push(`<span class="crd" title="${esc(tr('Created {0}', fmtWhen(t.created_at)))}">${ic('plus', 's')}${dayLabel(ds(new Date(t.created_at)))}</span>`);
  if (opts.trash) meta.push(`<span>${tr('deleted {0}', dayLabel(t.deleted_at.slice(0, 10)))}</span>`);
  if (opts.trash && t.keep) meta.push(`<span class="tkeep" title="${esc(tr('Only the list owner can delete it for good'))}">${ic('lock', 's')}${tr('stays')}</span>`);  // 2.0.5
  // 2.8.0 (#434): the status glyph (circle; priority = its colour; an agent working on it = an open arc + dot) and, in
  // lists with tickets, the ticket number in a mono gutter
  const work = t.status === 0 && t.id > 0 && (S.agents || []).some(a => a.enabled && a.status === 'working' && a.status_task === t.id);
  const chk = (t.status === 2 ? 'on' : t.status === -1 ? 'wont' : 'p' + (opts.checklist ? 0 : t.priority)) + (work ? ' work' : '') + (isMs(t) ? ' ms' : '');
  let lcH = '';
  if (lc) {  // 2.14.0 (#425): the cells in the list's order; a cell the width has no room for shows in the second line
    const cells = lc.filter(k => k !== 'id').map(k => [k, lcCell(k, t, {kids, openKids, time, checklist: opts.checklist})]);
    lcH = `<div class="lcols" id="tc-${t.id}" data-act="open">${cells.map(([k, c], i) => `<span class="lc ${lcCls(k)} ${lcOvf(i)}" data-k="${esc(k)}">${c}</span>`).join('')}</div>`;
    cells.forEach(([k, c], i) => { if (c && i >= 2) meta.push(`<span class="mlc ${lcOvf(i)}" data-lc="${esc(k)}">${c}</span>`); });
  }
  const gut = !opts.checklist && t.id > 0 && (lc ? lc.includes('id') : ticketsOn(t.list_id) || idsOn(t.list_id)) ? `<span class="tgut" aria-label="${esc(tr('Ticket {0}', '#' + t.id))}">#${t.id}</span>` : '';
  const collapsed = S.collapsed.has('t' + t.id);
  const ro = !opts.trash && !canEdit(t);
  const caret = opts.tree && openKids ? `<button class="caret ${collapsed ? 'closed' : ''}" data-act="collapse" data-key="t${t.id}" aria-expanded="${!collapsed}" aria-label="${esc(trn('{0} subtask', '{0} subtasks', openKids))}">${ic('chev', 's')}</button>` : '';
  const cols = tc ? `<div class="tcols" data-act="open">${timeOn() && (opts.tcols.list || isProject(t.list_id)) ? `<span class="c-time ${time?.live ? 'live' : ''}" title="${time ? time.tip : ''}">${time ? time.txt : ''}</span>` : ''}${collab() ? `<span class="c-who">${who}</span>` : ''}${opts.tcols.list ? `<span class="c-list" title="${esc(lst)}"><span>${esc(lst)}</span></span>` : ''}<span class="c-date ${dueClass(t)}" title="${esc(due)}">${t.start && t.start < t.due ? ic('timeline', 's rngi') : ''}<span class="cdt">${esc(dueLabel(t, false))}</span></span></div>` : '';
  let h = `<div class="trow ${t.priority && !opts.checklist ? 'pr' + t.priority : ''} ${opts.checklist ? 'ck' : ''} ${tc || lc ? 'hascols' : ''} ${lc ? 'haslc' : ''} ${t.status ? 'done' : ''} ${opts.depth ? 'sub d' + opts.depth : ''} ${opts.subRow ? 'subrow' : ''} ${S.sel === t.id ? 'sel' : ''} ${gut ? 'hasgut' : ''} ${S.kf === t.id && !opts.subRow ? 'kfocus' : ''} ${S.multi.has(t.id) ? 'msel' : ''} ${ro ? 'ro' : ''} ${opts.next && !opts.depth ? 'flownext' : ''}" data-id="${t.id}" ${opts.drag !== false && !opts.trash && !ro && !isMobile() ? 'draggable="true"' : ''}>
    ${caret}
    ${opts.trash ? `<span class="chk ${chk}">${t.status === 2 ? ic('check') : ''}</span>` : `<button class="chk ${chk}" data-act="toggle" role="checkbox" aria-checked="${t.status === 2}" aria-label="${esc(isMs(t) ? tr('Complete milestone: {0}', t.title) : tr('Complete: {0}', t.title))}" ${ro ? 'disabled' : ''}>${t.status === 2 ? ic('check') : t.status === -1 ? ic('x') : ''}</button>`}${gut}
    <div class="tmain" data-act="${opts.trash ? '' : 'open'}"><div class="ttl"${opts.trash ? '' : ` data-kt role="button" tabindex="-1" aria-describedby="${lc ? `tc-${t.id} ` : ''}tm-${t.id}"`}>${esc(t.title)}${t.priority && !opts.checklist && !opts.trash && t.status === 0 && !(lc && lc.includes('prio')) ? prioMark(t.priority) : ''}</div><div class="meta" id="tm-${t.id}">${meta.join('')}</div></div>
    ${opts.cols ? `<div class="fcols" data-act="open">${opts.cols.map(f => `<span class="fcell t-${esc(f.type)}">${fieldCell(f, t.fields?.[f.id], t.list_id)}</span>`).join('')}</div>` : ''}
    ${cols}${lcH}
    ${ac ? `<span class="wcell">${who}</span>` : ''}
    ${opts.ckback && !ro ? `<button class="iconbtn ckback" data-act="toggle" title="${tr('Put back on the list')}" aria-label="${tr('Put back on the list')}">${ic('undo', 's')}</button>` : ''}
    ${opts.trash ? `<button class="iconbtn" data-act="restore" title="${tr('Restore')}">${ic('undo')}</button>${listById(t.list_id)?.role === 'owner' ? `<button class="iconbtn danger" data-act="purge" title="${tr('Delete permanently')}">${ic('x')}</button>` : ''}` : ''}
  </div>`;
  if (opts.tree && openKids && !collapsed) h += kids.filter(k => k.status === 0).map(k => taskRow(k, {...opts, depth: (opts.depth || 0) + 1, showList: false})).join('');
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
  return canAssign(t) || mine ? `<button type="button" class="gchip ${mine ? 'me' : ''}" data-act="assign" title="${tip}" aria-label="${tip}" aria-haspopup="menu">${ic('users', 's')}<span>${esc(n)}</span></button>`
    : `<span class="gchip" title="${tip}">${ic('users', 's')}<span>${esc(n)}</span></span>`;
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
  const tip = t.assignee_id ? tr('Assigned to {0}', name || '?') : tr('Nobody assigned');
  // 2.6.0 (K11): nobody assigned = no icon in checklists and on subtasks; elsewhere the dashed circle only shows on hover /
  // keyboard focus (desktop) and not at all on touch screens (assign from the task panel or the task's menu there)
  if (!t.assignee_id && (listById(t.list_id)?.checklist || t.parent_id)) return '';  // 2.7.2: lists with completed at the bottom (shopping) too
  const inner = t.assignee_id ? av(t.assignee_id, name, `who ${me ? 'me' : ''}`) : `<span class="who none">${ic('user', 's')}</span>`;
  return canAssign(t) ? `<button type="button" class="whob${t.assignee_id ? '' : ' wnone'}" data-act="assign" title="${esc(tip + ' · ' + tr('Assign…'))}" aria-label="${esc(tip + ' · ' + tr('Assign…'))}" aria-haspopup="menu">${inner}</button>`
    : t.assignee_id ? `<span class="whob ro" title="${esc(tip)}">${avBtn(t.assignee_id, name, `who ${me ? 'me' : ''}`)}</span>` : '';  // 2.7.2 (#418)
}
function assignMenu(anchor, id) {
  const t = taskById(id); if (!t) return;
  const take = myGroup(t.assignee_group_id) ? [{label: tr('Take it'), icon: 'check', cls: 'mtake', fn: () => takeTask(id)}] : [];  // 2.10.0 (#441)
  if (!canAssign(t)) { if (take.length) menu(anchor, take); else roToast(); return; }
  const set = uid => { if ((t.assignee_id || null) !== uid || t.assignee_group_id) patchTask(id, {assignee_id: uid, ...(t.assignee_group_id ? {assignee_group_id: null} : {})}); };
  const setG = gid => { if (t.assignee_group_id !== gid) patchTask(id, {assignee_group_id: gid, ...(t.assignee_id ? {assignee_id: null} : {})}); };
  const cur = t.assignee_id ? personName(t.list_id, t.assignee_id) || personNameAny(t.assignee_id) : '';
  const gs = listGroups(t.list_id);
  menu(anchor, [...take, ...(take.length ? ['-'] : []), ...(t.assignee_id ? [{label: tr('Show {0}', cur || '?'), icon: 'user', cls: 'mshow', fn: () => personCard(anchor, t.assignee_id)}, '-'] : []),  // 2.7.2 (#418)
    {label: tr('Nobody'), icon: 'x', on: !t.assignee_id && !t.assignee_group_id, fn: () => set(null)}, '-',
    ...listPeople(listById(t.list_id)).map(p => ({label: p.name + (S.me && p.user_id === S.me.id ? ' ' + tr('(me)') : '') + (p.role === 'participant' ? ' · ' + tr('Participant') : p.role === 'view' ? ' · ' + tr('Viewer') : ''),
      icon: 'user', on: p.user_id === t.assignee_id, fn: () => set(p.user_id)})),
    ...(gs.length ? ['-', ...gs.map(g => ({label: g.name + ' · ' + tr('Group'), icon: 'users', on: g.group_id === t.assignee_group_id, fn: () => setG(g.group_id)}))] : [])]);
}
// the assignee select of the task panel: people, then the list's groups (value "g:<id>")
const assigneeOpts = (t, l) => listPeople(l).map(p => `<option value="${p.user_id}" ${p.user_id === t.assignee_id ? 'selected' : ''}>${esc(p.name)}${S.me && p.user_id === S.me.id ? ' ' + tr('(me)') : ''}</option>`).join('')
  + (listGroups(l?.id).length ? `<optgroup label="${esc(tr('Groups'))}">${listGroups(l.id).map(g => `<option value="g:${g.group_id}" ${g.group_id === t.assignee_group_id ? 'selected' : ''}>${esc(g.name)}</option>`).join('')}</optgroup>` : '');
// ---- custom fields: display (chips on the rows, columns, detail panel)
const numFmt = v => { const x = +v; return Number.isFinite(x) ? x.toLocaleString(LOCALE(), {maximumFractionDigits: 6}) : String(v); };
const selOpt = (f, v) => (f.options?.options || []).find(o => o.id === v);
function fieldText(f, v, lid) {
  if (v == null || v === '') return '';
  switch (f.type) {
    case 'number': return numFmt(v) + (f.options?.unit ? ' ' + f.options.unit : '');
    case 'select': return selOpt(f, v)?.name || '';
    case 'date': return dayLabel(v);
    case 'checkbox': return v === '1' ? tr('yes') : '';
    case 'person': return personName(lid, +v) || '?';
    case 'url': return urlHost(v);
  }
  return String(v);
}
function fieldChip(f, v, lid) {
  const txt = fieldText(f, v, lid); if (!txt) return '';
  const tip = esc(f.name + ': ' + (f.type === 'url' ? v : f.type === 'date' ? fmtDate(v) : txt));
  if (f.type === 'select') { const o = selOpt(f, v); return `<span class="fchip sel" style="${cssColor(o.color) ? '--fc:' + cssColor(o.color) : ''}" title="${tip}">${esc(o.name)}</span>`; }
  if (f.type === 'checkbox') return `<span class="fchip" title="${tip}">${ic('check', 's')}${esc(f.name)}</span>`;
  if (f.type === 'person') return (isTouch() ? av : avBtn)(+v, txt, 'who', `title="${tip}"`);
  if (f.type === 'url') return `<a class="lnk" href="${esc(v)}" target="_blank" rel="noopener noreferrer" title="${tip}">${ic('link', 's')}${esc(txt)}</a>`;
  if (f.type === 'date') return `<span class="fchip ${v < today() ? 'over' : ''}" title="${tip}">${ic('cal', 's')}${esc(txt)}</span>`;
  return `<span class="fchip" title="${tip}">${f.type === 'number' ? `<i>${esc(f.name)}</i> ` : ''}${esc(txt.length > 40 ? txt.slice(0, 39) + '…' : txt)}</span>`;
}
function fieldCell(f, v, lid) {  // column view (desktop)
  if (v == null || v === '') return '';
  if (f.type === 'select') { const o = selOpt(f, v); return o ? `<span class="fchip sel" style="${cssColor(o.color) ? '--fc:' + cssColor(o.color) : ''}">${esc(o.name)}</span>` : ''; }
  if (f.type === 'checkbox') return v === '1' ? ic('check', 's') : '';
  if (f.type === 'url') return `<a class="lnk" href="${esc(v)}" target="_blank" rel="noopener noreferrer" title="${esc(v)}">${esc(urlHost(v))}</a>`;
  return `<span title="${esc(fieldText(f, v, lid))}">${esc(fieldText(f, v, lid))}</span>`;
}
// ---- 2.14.0: the heron (empty states, welcome, offline, errors). A line drawing in the text colour; its sun (the dot) is
// the accent and follows theme and accent colour (CSS .heron .hr-sun); 2.16.0 (#447): standing / welcome / offline: a half sun on
// the horizon (the dot above the beak read as a balanced stone). Decorative: hidden from screen readers, the text
// next to it says what it means.
const HERON = {
  agent: ['0 0 120 120', '<circle class="hr-sun" cx="96" cy="97" r="3.4"/><g transform="translate(-14 0)"><path d="M34 64L24 70"/><path d="M34 64C46 55 68 57 80 67C72 75 54 77 42 72"/><path d="M70 62C66 52 62 44 64 36C66 30 72 29 75 33"/><path d="M75 33L92 41"/><circle class="hr-eye" cx="69" cy="34" r="1.8" /><path d="M60 76V106"/><path d="M60 88L52 84L57 79"/><path d="M42 108H78M50 113H70"/></g><path d="M86 106V96A10 10 0 0 1 106 96V106"/><path d="M96 86V81"/><path d="M111 90A6 6 0 0 1 111 100"/><path d="M82 108H112"/>'],
  done: ['0 0 120 120', '<circle class="hr-sun" cx="95" cy="99" r="6.5"/><path d="M34 64L24 70"/><path d="M34 64C46 55 68 57 80 67C72 75 54 77 42 72"/><path d="M70 62C66 52 62 44 64 36C66 30 72 29 75 33"/><path d="M75 33L93 40"/><path d="M66.8 33.6Q69 35.4 71.2 33.6"/><path d="M60 76V106"/><path d="M60 88L52 84L57 79"/><path d="M42 108H104M50 113H70"/>'],
  error: ['0 0 120 120', '<circle class="hr-sun" cx="77" cy="108" r="2.6"/><path d="M34 64L24 70"/><path d="M34 64C46 55 68 57 80 67C72 75 54 77 42 72"/><path d="M72 63C73 53 79 46 85 48C88 49 89 53 87 57"/><circle class="hr-eye" cx="84.5" cy="51.5" r="1.6" /><path d="M87.5 56L95 74"/><path d="M60 76V106"/><path d="M60 88L52 84L57 79"/><path d="M30 108H71M83 108L100 104.5M48 113H66"/>'],
  empty: ['0 0 120 120', '<circle class="hr-sun" cx="92" cy="104" r="3.2"/><path d="M34 64L24 70"/><path d="M34 64C46 55 68 57 80 67C72 75 54 77 42 72"/><path d="M72 63C76 55 83 51 87 55C90 58 90 63 88 67"/><circle class="hr-eye" cx="86.2" cy="59.5" r="1.6" /><path d="M88.5 66L92 86"/><path d="M60 76V102"/><path d="M60 88L52 84L57 79"/><path d="M36 104H84M100 104H108M48 110H66"/><path d="M84 109Q92 112 100 109"/>'],
  stand: ['0 0 120 120', '<path class="hr-sun" d="M89 108A9 9 0 0 1 107 108Z"/><path d="M34 64L24 70"/><path d="M34 64C46 55 68 57 80 67C72 75 54 77 42 72"/><path d="M70 62C66 52 62 44 64 36C66 30 72 29 75 33"/><path d="M75 33L94 38"/><circle class="hr-eye" cx="69" cy="34" r="1.8" /><path d="M60 76V106"/><path d="M60 88L52 84L57 79"/><path d="M42 108H112M50 113H70"/>'],
  offline: ['0 0 120 120', '<path class="hr-sun dim" d="M89 108A9 9 0 0 1 107 108Z"/><path d="M34 64L24 70"/><path d="M34 64C46 55 68 57 80 67C72 75 54 77 42 72"/><path d="M72 63C75 56 71 50 65 51C60 52 59 57 62 60"/><path d="M64 54.5Q66 56 68 54.5"/><path d="M61 53L47 58"/><path d="M60 76V106"/><path d="M60 88L52 84L57 79"/><path d="M42 108H112M50 113H70"/>'],
  welcome: ['0 0 120 120', '<path class="hr-sun" d="M89 108A9 9 0 0 1 107 108Z"/><path d="M34 64L24 70"/><path d="M34 64C46 55 68 57 80 67C72 75 54 77 42 72"/><path d="M46 61C40 52 40 42 47 35"/><path d="M52 60C48 53 48 47 52 42"/><path d="M70 62C66 52 62 44 64 36C66 30 72 29 75 33"/><path d="M75 33L94 38"/><circle class="hr-eye" cx="69" cy="34" r="1.8" /><path d="M60 76V106"/><path d="M60 88L52 84L57 79"/><path d="M42 108H112M50 113H70"/>'],
};
const heron = (pose, cls = '') => { const [vb, inner] = HERON[pose] || HERON.empty; return `<svg class="heron ${cls}" viewBox="${vb}" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${inner}</svg>`; };
const heronEmpty = (pose, title, sub = '') => `<div class="empty hempty">${heron(pose)}<b>${esc(title)}</b>${sub ? `<span>${esc(sub)}</span>` : ''}</div>`;
const fieldCols = lid => !isMobile() && !!LS.get('fcols.' + lid, false) && fieldsOf(lid).length > 0;
// ---- 2.14.0 (#425): list columns. One setting per list, the same for every member (owner / list admins change it in
// "Columns…"): which columns the rows show and in which order, custom fields and the task number included. null = the
// default layout (date, assignee, time as before; fields as chips). Narrow widths show the first two columns, the rest
// moves into the second line (classes o2 … o10: the cell's index needs at least that many columns of room).
const PRIO_NAMES = {1: N_('Low'), 3: N_('Medium'), 5: N_('High')};
const COLS = [['due', N_('Date')], ['prio', N_('Priority')], ['who', N_('Assignee')], ['tags', N_('Tags')], ['time', N_('Tracked time')],
  ['progress', N_('Subtasks')], ['deps', N_('Waiting on')], ['created', N_('Created')]];
const COL_ICON = {due: 'cal', prio: 'flag', who: 'user', tags: 'tag', time: 'clock', progress: 'sub', deps: 'deps', created: 'plus'};
function colChoices(l) {  // [key, name] of the columns this list can show (the task number separately)
  const ok = k => k === 'who' ? collab() && !!l.shared : k === 'time' ? timeOn() && isProject(l.id) : k === 'deps' ? depsOn() && isProject(l.id) : true;
  return [...COLS.filter(([k]) => ok(k)).map(([k, n]) => [k, tr(n)]), ...fieldsOf(l.id).map(f => ['f:' + f.id, f.name])];
}
const colCfg = lid => { const l = listById(lid); return l && Array.isArray(l.columns) ? l.columns : null; };
function listCols(l) {  // the list's own columns that apply right now, or null (default layout)
  const c = l && colCfg(l.id); if (!c) return null;
  const av = new Set(['id', ...colChoices(l).map(x => x[0])]);
  return c.filter(k => av.has(k));
}
function colDefault(l) {  // what the default layout shows: the starting point of "Columns…"
  const fs = fieldsOf(l.id), all = LS.get('fcols.' + l.id, false);
  return [...(ticketsOn(l.id) || idsOn(l.id) ? ['id'] : []), 'due', ...(acolOn(l.id) ? ['who'] : []), ...(timeOn() && isProject(l.id) ? ['time'] : []),
    ...(all ? fs : fs.filter(f => f.pinned)).map(f => 'f:' + f.id), 'progress', ...(depsOn() && isProject(l.id) ? ['deps'] : []), 'tags'];
}
const lcCls = k => 'lc-' + (k.startsWith('f:') ? 'f t-' + ((S.fields || []).find(f => f.id === +k.slice(2))?.type || 'text') : k);
const lcOvf = i => [2, 3, 5, 7, 10].filter(n => i >= n).map(n => 'o' + n).join(' ');
const colName = (l, k) => k === 'id' ? tr('Task number') : (colChoices(l).find(x => x[0] === k) || [0, ''])[1];
const colShort = (l, k) => k === 'time' ? tr('Time') : colName(l, k);  // the title row's label (narrow columns)
function lcCell(k, t, x) {
  switch (k) {
    case 'due': return t.due && !x.checklist ? `<span class="dt ${dueClass(t)}" title="${esc(dueLabel(t))}">${dueClass(t) === 'over' ? ic('alert', 's') + `<span class="sr">${tr('Overdue')}: </span>` : ''}${t.start && t.start < t.due ? ic('timeline', 's rngi') : ''}<span class="cdt">${esc(dueLabel(t, false))}</span></span>` : '';
    case 'prio': return t.priority && !x.checklist && PRIO_NAMES[t.priority] ? `<span class="lcp flag-${t.priority}" title="${esc(tr(PRIO_NAMES[t.priority]))}">${ic('flag', 's')}<span class="lbl">${esc(tr(PRIO_NAMES[t.priority]))}</span></span>` : '';
    case 'who': return t.id > 0 && collab() ? whoCell(t) : '';
    case 'tags': return [...(t.ltags || []).map(g => ltagChip(g, t.list_id)), ...t.tags.map(g => ptagChip(g, t.list_id))].join('');
    case 'time': return x.time ? `<span class="tchip ${x.time.live ? 'live' : ''}" data-tt="${t.id}" title="${x.time.tip}">${ic('clock', 's')}<b>${x.time.txt}</b></span>` : '';
    case 'progress': return x.kids.length ? `<span class="subc" title="${esc(tr('{0} of {1} subtasks done', x.kids.length - x.openKids, x.kids.length))}">${ic('sub', 's')}${x.kids.length - x.openKids}/${x.kids.length}</span>` : '';
    case 'deps': return t.blocked && t.status === 0 && dFor(t) ? `<span class="blk" title="${esc(blockedTitle(t))}">${ic('lock', 's')}<span class="lbl">${tr('waiting')}</span></span>` : '';
    case 'created': return t.created_at ? `<span class="crd" title="${esc(tr('Created {0}', fmtWhen(t.created_at)))}">${ic('plus', 's')}${dayLabel(ds(new Date(t.created_at)))}</span>` : '';
  }
  if (k.startsWith('f:')) { const f = fieldsOf(t.list_id).find(y => y.id === +k.slice(2)); return f ? fieldCell(f, t.fields?.[f.id], t.list_id) : ''; }
  return '';
}
// "Columns…": tick what the rows show, order by dragging the handle or with the arrows (Alt+↑/↓ on the keyboard). Saved for
// the whole list (everyone sees the same); owner and list admins change it, everyone else sees it read-only.
function colModal(id) {
  const l = listById(id); if (!l) return;
  const may = canManage(l), ch = colChoices(l), names = Object.fromEntries(ch);
  const start = listCols(l) || colDefault(l).filter(k => k === 'id' || names[k]);
  let num = start.includes('id');
  const on = new Set(start.filter(k => k !== 'id'));
  let order = [...start.filter(k => k !== 'id'), ...ch.map(x => x[0]).filter(k => !on.has(k))];
  const dis = may ? '' : 'disabled';
  const rowH = (k, i) => `<li class="colr ${on.has(k) ? 'on' : ''}" data-k="${esc(k)}">${may ? `<span class="colh" data-colh title="${esc(tr('Drag to reorder'))}" aria-hidden="true">${ic('grip', 's')}</span>` : ''}<label class="chkl"><input type="checkbox" data-colk="${esc(k)}" ${on.has(k) ? 'checked' : ''} ${dis}><span class="coln">${k.startsWith('f:') ? ic('sliders', 's') : ic(COL_ICON[k], 's')}<span>${esc(names[k])}</span></span></label>${may ? `<button type="button" class="iconbtn colmv" data-colmv="-1" ${i ? '' : 'disabled'} title="${esc(tr('Move up'))}" aria-label="${esc(tr('Move up') + ': ' + names[k])}">${ic('chev', 's cup')}</button><button type="button" class="iconbtn colmv" data-colmv="1" ${i < order.length - 1 ? '' : 'disabled'} title="${esc(tr('Move down'))}" aria-label="${esc(tr('Move down') + ': ' + names[k])}">${ic('chev', 's')}</button>` : ''}</li>`;
  const md = modal(`<h3 id="col-t">${ic('columns', 's')}${tr('Columns')}</h3>
    <p class="muted coldesc">${esc(tr('The same for everyone in this list. Phones show the first two columns, the rest in the second line.'))}</p>
    ${may ? '' : `<p class="rohint">${ic('lock', 's')}${esc(tr('Only the owner and list admins can change the columns.'))}</p>`}
    <label class="chkl colnum"><input type="checkbox" id="col-num" ${num ? 'checked' : ''} ${dis}><span class="coln">${ic('hash', 's')}<span>${tr('Task number in front of the title')}</span></span></label>
    <ul class="colls" id="col-ls" aria-labelledby="col-t" tabindex="-1">${order.map(rowH).join('')}</ul>
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
  md.addEventListener('click', async e => {
    const mv = e.target.closest('[data-colmv]');
    if (mv) { move(mv.closest('.colr').dataset.k, +mv.dataset.colmv); return; }
    const b = e.target.closest('[data-colact]'); if (!b) return;
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
  try { await api('PATCH', '/api/lists/' + id, {columns: next}); } catch { return; }
  l.columns = next; render();
  if (quiet) return;
  const go = v => async () => { await colSave(id, v, true); return {}; };
  const e = histAdd({label: tr('Columns of {0}', qn(lname(l))), undo: go(prev), redo: go(next), lids: [id]});
  histToast(next ? tr('Columns saved for everyone in the list') : tr('Default columns'), e);
}
function lcHead(l, lc) {  // the column titles above the rows (wide layouts)
  const ks = lc.filter(k => k !== 'id');
  if (!ks.length) return '';
  lcwApply(l.id);
  // 2.16.0 (#634): a grip at the right edge of each column title: drag = the column's width on this device (per list),
  // double-click = its standard width; for the keyboard a separator (← → 0.5 rem, Enter = standard)
  return `<div class="lchead" data-lid="${l.id}"><span class="spacer"></span>${ks.map((k, i) => { const n = colName(l, k); return `<span class="lc ${lcCls(k)} ${lcOvf(i)}" data-k="${esc(k)}" title="${esc(n)}"><span class="lcn" aria-hidden="true">${k === 'who' || k === 'prio' ? ic(COL_ICON[k], 's') : `<span>${esc(colShort(l, k))}</span>`}</span>${isTouch() ? '' : `<i class="lcg" data-lcg="${esc(k)}" role="separator" aria-orientation="vertical" tabindex="0" aria-label="${esc(tr('Width of the column {0}', n))}" ${lcwGet(l.id)[k] ? `aria-valuenow="${lcwGet(l.id)[k]}" aria-valuetext="${esc(tr('{0} rem', String(lcwGet(l.id)[k])))}"` : `aria-valuetext="${esc(tr('Standard width'))}"`} aria-valuemin="${LCW_MIN}" aria-valuemax="${LCW_MAX}"></i>`}</span>`; }).join('')}</div>`;
}
// ---- 2.16.0 (#634): column widths per device and list (localStorage lcw.<list>: {key: rem}), applied as one style sheet
const LCW_MIN = 2.5, LCW_MAX = 24;
const lcwGet = lid => LS.get('lcw.' + lid, {}) || {};
function lcwApply(lid) {
  let st = $('#lcw-style'); if (!st) { st = document.createElement('style'); st.id = 'lcw-style'; document.head.appendChild(st); }
  const w = lcwGet(lid);
  st.textContent = Object.entries(w).filter(([, v]) => v > 0).map(([k, v]) => `#view .lc[data-k="${window.CSS?.escape ? CSS.escape(k) : k.replace(/["\\]/g, '')}"]{width:${+v}rem;max-width:none}`).join('\n');
}
function lcwSet(lid, k, v) {
  const w = lcwGet(lid);
  if (v == null) delete w[k]; else w[k] = Math.round(Math.max(LCW_MIN, Math.min(LCW_MAX, v)) * 4) / 4;
  Object.keys(w).length ? LS.set('lcw.' + lid, w) : LS.del('lcw.' + lid);
  lcwApply(lid);
}
document.addEventListener('pointerdown', e => {
  const g = e.target.closest?.('.lchead .lcg'); if (!g || e.button !== 0) return;
  e.preventDefault(); e.stopPropagation();
  const lid = +g.closest('.lchead').dataset.lid, k = g.dataset.lcg, cell = g.closest('.lc');
  const rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16, x0 = e.clientX, w0 = cell.getBoundingClientRect().width / rem;
  g.setPointerCapture?.(e.pointerId); document.body.classList.add('pgdrag');
  const mv = ev => lcwSet(lid, k, w0 + (ev.clientX - x0) / rem);
  const up = () => { g.removeEventListener('pointermove', mv); document.body.classList.remove('pgdrag'); };
  g.addEventListener('pointermove', mv); g.addEventListener('pointerup', up, {once: true}); g.addEventListener('pointercancel', up, {once: true});
}, true);
document.addEventListener('dblclick', e => { const g = e.target.closest?.('.lchead .lcg'); if (g) lcwSet(+g.closest('.lchead').dataset.lid, g.dataset.lcg, null); });
document.addEventListener('keydown', e => {
  const g = e.target.closest?.('.lchead .lcg'); if (!g) return;
  const lid = +g.closest('.lchead').dataset.lid, k = g.dataset.lcg, rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
  const cur = g.closest('.lc').getBoundingClientRect().width / rem || lcwGet(lid)[k] || parseFloat(getComputedStyle(g.closest('.lc')).width) / rem || 7;
  const to = {ArrowRight: cur + (e.shiftKey ? 2 : .5), ArrowLeft: cur - (e.shiftKey ? 2 : .5)}[e.key];
  if (to != null) { e.preventDefault(); e.stopPropagation(); lcwSet(lid, k, to); }
  else if (e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); lcwSet(lid, k, null); }
}, true);
// ---- dependencies: "waiting on" (blocked by open tasks)
function blockedTitle(t) {
  const names = (t.blockers || []).map(id => S.tasks.get(id)?.title).filter(Boolean), hidden = Math.max(0, (t.blocked || 0) - names.length);
  return tr('Waiting on: {0}', [...names.map(n => tr('“{0}”|quoted', n)), ...(hidden ? [trn('{0} task you cannot see', '{0} tasks you cannot see', hidden)] : [])].join(', '));
}
const hideBlockedToday = () => depsOn() && S.settings.hide_blocked_today === '1';
// 2.22.0 (#681): Today can show the inbox too (Settings > General > Today, off by default): the inbox's tasks without a
// date in their own foldable section under today's tasks, with quick buttons to sort them; they count in Today's number
const todayInbox = () => S.settings.today_inbox === '1';
const isTodayInbox = (t, t0 = today()) => !t.parent_id && !t.context && !t.due && t.status === 0 && !t.deleted_at && t.list_id === inbox()?.id && !planToday(t, t0) && !dlToday(t);
const todayInboxTasks = () => openTasks().filter(t => isTodayInbox(t)).sort((a, b) => (a.sort ?? 0) - (b.sort ?? 0) || a.id - b.id);
function todayInboxHtml(ts) {
  const k = 'today-inbox', closed = S.collapsed.has(k);
  const acts = t => `<span class="tinacts"><button type="button" class="iconbtn" data-act="tin-due" data-d="0" data-id="${t.id}" title="${esc(tr('Today'))}" aria-label="${esc(tr('{0}: today', t.title))}">${ic('sun', 's')}</button><button type="button" class="iconbtn" data-act="tin-due" data-d="1" data-id="${t.id}" title="${esc(tr('Tomorrow'))}" aria-label="${esc(tr('{0}: tomorrow', t.title))}">${ic('sunrise', 's')}</button><button type="button" class="iconbtn" data-act="tin-move" data-id="${t.id}" aria-haspopup="menu" title="${esc(tr('Move to list'))}" aria-label="${esc(tr('Move {0} to a list', t.title))}">${ic('list', 's')}</button></span>`;
  return `<div class="group tinbox"><div class="ghead ${closed ? 'closed' : ''}" data-act="collapse" data-key="${k}">${ic('chev', 's')}${ic('inbox', 's')}${tr('Inbox')} <span class="c">${ts.length}</span></div>
    ${closed ? '' : ts.map(t => `<div class="tinrow">${taskRow(t, {drag: false, tree: false})}${acts(t)}</div>`).join('')}</div>`;
}
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-act="tin-due"], [data-act="tin-move"]'); if (!b) return;
  e.preventDefault(); e.stopPropagation();
  const id = +b.dataset.id, t = taskById(id); if (!t) return;
  if (b.dataset.act === 'tin-due') { const d = addDays(today(), +b.dataset.d); patchUndoable(id, {due: d}, tr('Due: {0}', dayLabel(d))); return; }
  menu(b, S.lists.filter(l => !l.archived && !l.is_inbox && canAddTo(l.id)).map(l => ({label: lname(l), icon: 'list', fn: () => patchUndoable(id, {list_id: l.id}, tr('Moved to {0}', lname(l)))})));
});
function qaddBox(extraCls = '') {
  return `<div class="qadd inline ${extraCls}"><div class="box">${ic('plus')}<input id="qinput" aria-label="${esc(tr('Add task…'))}" placeholder="${tr('Add task: “Dentist tomorrow 3pm !high #private ~list”')}" autocomplete="off" enterkeyhint="done">${tplBtn()}${qExtraBtns('qinput')}</div><div class="chips" id="qchips"></div></div>`;
}
// 2.14.0 (#484): next to Send: "Add and open" (creates the task and opens its details at once, for notes and files) and the
// paper clip (pick files: the task is created with them as attachments, the first file's name is the title when none
// is typed; then its details open). Phones, Fold and desktop; 44 px targets on touch screens.
function qExtraBtns(inp) {
  return `<button type="button" class="iconbtn qbtn" data-act="q-clip" data-q="${inp}" title="${esc(tr('Add with a file…'))}" aria-label="${esc(tr('Add with a file…'))}">${ic('qclip', 's')}</button>`
    + `<button type="button" class="iconbtn qbtn" data-act="q-open" data-q="${inp}" title="${esc(tr('Add and open details'))}" aria-label="${esc(tr('Add and open details'))}">${ic('qopen', 's')}</button>`;
}
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
function tplBtn() {
  return tplOf('task').length ? `<button class="iconbtn qtpl" data-act="tpl-use" title="${tr('New from template')}" aria-label="${tr('New from template')}">${ic('copy', 's')}</button>` : '';
}
// 1.5.3: desktop / tablet quick add = a composer docked at the bottom of the list column (sticky): a card with an accent
// "+", a short placeholder, the key badge and the template button. Focused, it grows: chips for date, list and
// priority (effective values: typed ones, else the view's defaults; a click changes them) and the parsed tokens. Enter
// adds and keeps the focus, Esc leaves it. Phones keep the + button (FAB).
const QEX = N_('Type the way you think: “Dentist tomorrow 3pm !high #private ~list”');
function qdockHtml() {
  return `<div class="qdock"><div class="qadd dock"><div class="box"><span class="qplus" aria-hidden="true">${ic('plus', 's')}</span><input id="qinput" aria-label="${esc(tr('Add task…'))}" placeholder="${tr('Add task…')}" title="${esc(tr(QEX))}" autocomplete="off" enterkeyhint="done">${tplBtn()}${qExtraBtns('qinput')}${isTouch() ? '' : `<span class="qkey" title="${esc(kt(tr('New task'), 'n'))}">${kb('n')}</span>`}</div>
    <div class="qdmore"><div class="qdchips" id="qdchips"></div><div class="chips" id="qchips"></div>${hintSeen('qsyntax') ? '' : `<div class="qhint">${tr(QEX)}</div>`}</div></div></div>`;
}
// the chips of the docked composer: what the task will get (a chip set here wins over the text)
function qdockChips() {
  const box = $('#qdchips'), inp = $('#qinput'); if (!box || !inp) return;
  if (S.qov?.key !== S.route.key) S.qov = {key: S.route.key};
  const d = quickDefaults(), r = parseQuick(inp.value, S.quick.ignore), o = S.qov;
  const due = 'due' in o ? o.due : r.due || d.due, lid = o.list_id || r.list_id || d.list_id || inbox()?.id, pr = 'priority' in o ? o.priority : r.priority ?? d.priority ?? 0;
  const PRN = {0: N_('No priority'), 1: N_('Low'), 3: N_('Medium'), 5: N_('High')};
  box.innerHTML = `<button type="button" class="qdc ${due ? 'set' : ''} ${'due' in o ? 'ov' : ''}" data-act="qd-date">${ic('cal', 's')}${esc(due ? dayLabel(due) : tr('No date'))}</button>` +
    `<button type="button" class="qdc set ${o.list_id ? 'ov' : ''}" data-act="qd-list">${ic('list', 's')}${esc(lname(listById(lid)) || tr('Inbox'))}</button>` +
    `<button type="button" class="qdc ${pr ? 'set flag-' + pr : ''} ${'priority' in o ? 'ov' : ''}" data-act="qd-prio">${ic('flag', 's')}${esc(tr(PRN[pr] || PRN[0]))}</button>`;
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
function viewListBody() {
  const v = viewTasks();
  FLOW.cyc = false;
  const groups = groupTasks(v), flow = sortMode() === 'flow', crd = sortMode().startsWith('created');
  const showList = !v.list;
  const rl = v.list && listById(v.list), ro = rl && !canEditList(rl.id), ck = !!(rl && rl.checklist);
  const lc = rl ? listCols(rl) : null;  // 2.14.0 (#425)
  const cols = rl && !lc && fieldCols(rl.id) ? fieldsOf(rl.id).slice(0, 6) : null;
  let h = (rl ? listHead(rl) : v.folder ? folderHead(v.folder) : agBandHtml()) + (ro ? `<div class="rohint">${ic(isPart(rl.id) ? 'user' : 'eye', 's')}${esc(isPart(rl.id) ? tr('Participant: you see only the tasks assigned to you, shared by {0}', rl.owner_name) : tr('View only, shared by {0}', rl.owner_name))}</div>` : '');
  if (S.route.key === 'today') h += waitCard() + reviewCard() + dayplanBar() + overdueBanner() + cevTodayBlock();  // 2.10.0 (#440): review + planner
  if (flow && FLOW.cyc) h += `<div class="flowhint">${ic('deps', 's')}${esc(tr('Some tasks wait on each other in a circle; they are ordered by date.'))}</div>`;
  if (lc && total0(groups)) h += lcHead(rl, lc);
  if (cols) h += `<div class="fcolhead"><span class="spacer"></span>${cols.map(f => `<span class="fcell t-${esc(f.type)}" title="${esc(f.name)}">${esc(f.name)}</span>`).join('')}</div>`;
  const total = groups.reduce((n, g) => n + g.tasks.length, 0);
  const flowDeps = flow && depsOn() && (() => {
    const shown = groups.flatMap(g => g.tasks), ids = new Set(shown.map(t => t.id));
    return shown.some(t => t.status === 0 && dFor(t) && (t.blocked || (t.blockers || []).some(b => ids.has(b))));
  })();
  const tin = S.route.key === 'today' && todayInbox() ? todayInboxTasks() : [];  // 2.22.0 (#681)
  if (!total && !tin.length) {
    // 2.14.0: the heron: Today with something done = the sun sets ("all done"), otherwise it looks into the water
    h += S.route.key === 'today' ? (v.done.length ? heronEmpty('done', tr('All done for today.'), tr('Enjoy the rest of the day.')) : heronEmpty('empty', tr('Nothing left for today.')))
      : heronEmpty('empty', tr('No tasks.'), rl && !ro ? tr('Add the first one with the field below.') : '');
  }
  let lastSub = '';
  // 2.17.0 (#649): a very long view renders its first ROW_CAP rows, then "Show more" (also by itself when it scrolls into
  // view); thousands of rows took seconds to build on every change
  let budget = rowCap(), cut = 0;
  for (const g of groups) {
    if (g.sub && g.sub !== lastSub) h += `<div class="fsubhd" data-go="${esc(keyToHash('folder:' + g.sub))}" role="link" tabindex="0">${ic('folder', 's')}<span>${esc(fName(g.sub))}</span></div>`;
    lastSub = g.sub || lastSub;
    if (rl?.family === 'shopping' && famOn() && g.section && !g.tasks.length) continue;  // 2.19.0 (#653): only areas with items
    const closed = S.collapsed.has(g.id);
    const sadd = g.section !== undefined && !ro && v.list && canAddTo(v.list);
    if (g.name) h += `<div class="group"><div class="ghead ${g.cls || ''} ${closed ? 'closed' : ''}" data-act="collapse" data-key="${g.id}" ${g.section !== undefined ? `data-section="${g.section ?? ''}"` : ''}>${g.section && !ro ? secHandle(g.section) : ''}${ic('chev', 's')}${g.img ? `<img class="gicon" src="${esc(g.img)}" alt="">` : g.color ? `<span class="gsw" style="background:${cssColor(g.color)}"></span>` : ''}${esc(g.name)} <span class="c">${g.tasks.length}</span>${sadd ? `<button class="iconbtn gact gadd" data-act="sec-add" data-sec="${g.section || 0}" title="${esc(tr('Add a task to {0}', g.name))}" aria-label="${esc(tr('Add a task to {0}', g.name))}">${ic('plus', 's')}</button>` : ''}${g.section && !ro ? `<button class="iconbtn gact" data-act="section-menu" data-id="${g.section}" title="${esc(tr('More') + ': ' + g.name)}" aria-label="${esc(tr('More') + ': ' + g.name)}">${ic('dots', 's')}</button>` : ''}</div>`;
    if (g.name && !closed && sadd) h += secAddHtml(g);
    // 1.7.0 Flow: the first task of each group that waits on nothing is marked "Next" (2.0.4: "Ready to start", and only
    // when some open task shown here waits on something; without dependencies the badge would say nothing)
    const nx = flow && flowDeps ? g.tasks.find(t => t.status === 0 && !t.context && !(t.blocked && dFor(t)))?.id : 0;
    if (!closed) { const n = Math.max(0, Math.min(g.tasks.length, budget)); h += g.tasks.slice(0, n).map(t => taskRow(t, {showList, tree: true, cols, lc, tcols: {list: showList}, next: t.id === nx, crd})).join(''); budget -= n; cut += g.tasks.length - n; }
    if (!closed && g.section !== undefined && !g.tasks.length && !ro) h += `<div class="sdrop" data-section="${g.section ?? ''}">${tr('Drop tasks here')}</div>`;  // shown while a task is dragged
    if (g.name) h += '</div>';
  }
  if (tin.length) h += todayInboxHtml(tin);
  // 2.19.0 (#667): the end of a list takes a dragged task into a new section
  if (rl && !ro && !rl.is_inbox && total && canEditList(rl.id)) h += `<div class="sdrop snew" data-newsec="1">${ic('plus', 's')}<span>${tr('New section')}</span></div>`;
  if (cut) h += `<div class="rowmore"><button type="button" class="btn" data-act="rows-more">${ic('down', 's')}${esc(trn('Show {0} more task', 'Show {0} more tasks', Math.min(cut, ROW_CAP)))}</button><span class="muted">${esc(trn('{0} task not shown yet', '{0} tasks not shown yet', cut))}</span></div>`;
  if (v.list && !ro) h += `<button class="iconbtn" data-act="section-new" style="margin:.375rem 0 0 -.25rem">${ic('plus', 's')} ${tr('Section')}</button>`;
  if (ck) {  // 2.7.2 (#414) "Show completed at the bottom" (was the checklist type): done items stay below in "Done" (open by
    // default), one tap puts them back on the list
    const k = 'ckdone:' + rl.id, closed = S.collapsed.has(k), done = v.done.slice().sort((a, b) => a.title.localeCompare(b.title, LOCALE()));
    h += `<div class="group ckdone"><div class="ghead ${closed ? 'closed' : ''}" data-act="collapse" data-key="${k}" title="${esc(tr('Ticked-off items land here and can be put back on the list with one tap.'))}">${ic('chev', 's')}${tr('Done|checklist')} <span class="c">${done.length}</span>${done.length && !ro ? `<button class="btn sm gact" data-act="ck-uncheck" data-id="${rl.id}">${ic('undo', 's')} ${tr('Uncheck all')}</button><button class="btn sm gact" data-act="ck-clear" data-id="${rl.id}">${ic('trash', 's')} ${tr('Clear done')}</button>` : ''}</div>`;
    if (done.length) hintDone('ckdone');  // used once: the hint has done its job
    if (!closed) h += done.length ? done.map(t => taskRow(t, {drag: false, cols, lc, ckback: true})).join('') : hintOnce('ckdone', tr('Ticked-off items land here and can be put back on the list with one tap.'), 'ckempty');
    return h + '</div>';
  }
  if (v.done.length && showDone()) {
    const closed = !S.collapsed.has('done-open');
    h += `<div class="group"><div class="ghead ${closed ? 'closed' : ''}" data-act="collapse" data-key="done-open">${ic('chev', 's')}${tr('Completed')} <span class="c">${v.done.length}</span></div>`;
    if (!closed) h += v.done.sort((a, b) => (b.completed_at || '').localeCompare(a.completed_at || '')).map(t => taskRow(t, {showList, drag: false, cols, lc, tcols: {list: showList}})).join('');
    h += '</div>';
  }
  return h;
}
// 1.5.2: "Delete completed…" on the Completed view: all, or those completed more than 30 / 90 days ago, go to the
// trash (restorable, one undo step). Only what the user may change; items of checklists stay (the reusable part of such
// a list). Completions of recurring tasks are done copies of their own, so the open series is never touched.
async function doneCleanup() {
  let all;
  try { all = (await api('GET', '/api/tasks?scope=done&limit=2000')).tasks || []; } catch { return; }
  const isCk = t => !!listById(t.list_id)?.checklist;  // 2.7.2 (#414): lists with "Show completed at the bottom"
  const cand = all.filter(t => !isCk(t));
  const pick = days => { const c = days ? new Date(Date.now() - days * 864e5).toISOString() : null; return cand.filter(t => !c || (t.completed_at || '') < c); };
  const may = arr => arr.filter(t => canEdit(t)), ro = arr => arr.length - may(arr).length;
  const opts = [[0, tr('All')], [30, tr('Completed more than 30 days ago')], [90, tr('Completed more than 90 days ago')]];
  let age = 0;
  const okLabel = () => trn('Move {0} task to the trash', 'Move {0} tasks to the trash', may(pick(age)).length);
  const html = `<div class="dcopts" role="radiogroup">${opts.map(([d, n]) => `<label class="chkl"><input type="radio" name="dc-age" value="${d}" ${d === age ? 'checked' : ''}> ${esc(n)} <span class="muted">(${may(pick(d)).length})</span></label>`).join('')}</div>
    <p class="muted" id="dc-note">${[tr('They can be restored from the trash.'), ro(pick(age)) ? trn('{0} task in a list you may only view stays.', '{0} tasks in lists you may only view stay.', ro(pick(age))) : '', all.length > cand.length ? tr('Items of lists that show completed tasks at the bottom stay.') : ''].filter(Boolean).map(esc).join(' ')}</p>`;
  const onCh = e => {
    if (e.target.name !== 'dc-age') return;
    age = +e.target.value;
    const yes = $('.cdlg [data-cd="yes"]'); if (yes) { yes.textContent = okLabel(); yes.disabled = !may(pick(age)).length; }
  };
  document.addEventListener('change', onCh);
  const pr = askConfirm(tr('Delete completed tasks'), '', {html, ok: okLabel(), danger: true});
  setTimeout(() => { const yes = $('.cdlg [data-cd="yes"]'); if (yes) yes.disabled = !may(pick(age)).length; }, 0);
  const ok = await pr;
  document.removeEventListener('change', onCh);
  const sel = may(pick(age)), skipped = ro(pick(age));
  if (!ok || !sel.length) return;
  const ids = sel.map(t => t.id), snaps = sel.map(snapTask);
  let j;
  try { j = await api('POST', '/api/tasks/batch', {ids, action: 'delete'}); } catch { return; }
  await load(); render();
  const n = ids.length - (j.errors?.length || 0);
  const msg = trn('{0} completed task moved to the trash', '{0} completed tasks moved to the trash', n) + (skipped + (j.errors?.length || 0) ? ' · ' + trn('{0} task skipped', '{0} tasks skipped', skipped + (j.errors?.length || 0)) : '');
  offerUndo(msg, histTrash(trn('Deleted {0} completed task', 'Deleted {0} completed tasks', n), ids, snaps, j));
}
// 1.6.1: "Archived" = the archived lists as rows (colour / emoji, name, folder, open / done tasks, archived on, owner of a
// shared list): Open, Restore (owner, undoable) and Delete permanently (owner, the own dialog names what is lost)
function viewArchived() {
  const ls = S.lists.filter(l => l.archived).sort((a, b) => (b.archived_at || '').localeCompare(a.archived_at || '') || lname(a).localeCompare(lname(b)));
  if (!ls.length) return `<div class="empty">${ic('archive')}${tr('No archived lists.')}<br><span class="muted">${tr('Archive a list from its “…” menu; it disappears from the sidebar and its tasks from Today and the calendar.')}</span></div>`;
  return `<div class="archv">${ls.map(l => {
    const p = l.progress || {done: 0, total: 0}, own = isOwner(l), em = leadEmoji(l.name), name = em ? l.name.slice(em.length).trim() : listName(l.name);
    const mark = em ? `<span class="aemo">${em}</span>` : `<span class="sw" style="${cssColor(l.color) ? 'background:' + cssColor(l.color) : ''}"></span>`;
    const meta = [l.folder && `${ic('folder', 's')}${esc(fDisp(l.folder))}`, `${esc(tr('{0} open', p.total - p.done))} · ${esc(tr('{0} done', p.done))}`,
      l.archived_at && esc(tr('archived {0}', fmtDateLoc(ds(new Date(l.archived_at))))), !own && `${ic('users', 's')}${esc(tr('Shared by {0}', l.owner_name || '?'))}`].filter(Boolean);
    return `<div class="arow" data-list="${l.id}"><button class="aname" data-go="l/${l.id}" title="${esc(tr('Open {0}', name))}">${mark}<span class="n">${esc(name)}</span></button>
      <div class="ameta">${meta.map(x => `<span>${x}</span>`).join('')}</div>
      <div class="aacts"><button class="btn sm" data-go="l/${l.id}">${tr('Open')}</button>${own ? `<button class="btn sm" data-act="arch-restore" data-id="${l.id}">${ic('undo', 's')}<span>${tr('Restore')}</span></button><button class="btn sm danger" data-act="arch-del" data-id="${l.id}">${ic('trash', 's')}<span>${tr('Delete permanently…')}</span></button>` : ''}</div></div>`;
  }).join('')}</div>`;
}
function viewHistory() {
  const trash = S.route.key === 'trash';
  const arr = S.extra || [];
  if (!arr.length) return `<div class="empty">${ic(trash ? 'trash' : 'done')}${trash ? tr('Trash is empty.') : tr('Nothing completed yet.')}</div>`;
  if (trash) {  // 2.0.5: what "Empty" leaves behind (shared lists of other owners) is said up front and marked per row
    const kept = arr.filter(t => t.keep).length;
    return (kept ? `<div class="shint trkeep">${ic('lock', 's')} ${esc(trn('{0} item stays when you empty the trash: it is in a list of another owner, only they can delete it for good.', '{0} items stay when you empty the trash: they are in lists of other owners, only they can delete them for good.', kept))}</div>` : '')
      + arr.map(t => taskRow(t, {trash: true, showList: true})).join('');
  }
  const g = new Map();
  for (const t of arr) { const d = (t.completed_at ? new Date(t.completed_at) : new Date()); const k = ds(d); if (!g.has(k)) g.set(k, []); g.get(k).push(t); }
  return [...g.entries()].map(([k, ts]) => `<div class="group"><div class="ghead">${dayLabel(k, true)} <span class="c">${ts.length}</span></div>${ts.map(t => taskRow(t, {showList: true, drag: false, tcols: {list: true}})).join('')}</div>`).join('');
}
function viewSearch() {
  return `<div class="search"><input id="searchq" type="search" aria-label="${esc(tr('Search'))}" placeholder="${tr('Search titles and notes')}" autocomplete="off" enterkeyhint="search"></div><div id="sresults">${S.searchRes ? renderSearchRes() : ''}</div>`;
}
function renderSearchRes() {
  if (!S.searchRes.length) return heronEmpty('empty', tr('No results.'), tr('Try fewer or other words.'));
  return S.searchRes.map(t => taskRow(t, {showList: true, drag: false, tcols: {list: true}})).join('');
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
    if (!q.trim()) { S.searchRes = null; $('#sresults').innerHTML = ''; return; }
    const j = await api('GET', '/api/tasks?scope=search&q=' + encodeURIComponent(q));
    // 2.13.0: "#447" / "447" puts that task (one this person sees) first
    const nm = q.trim().match(/^#?(\d{1,9})$/), hit = nm && taskById(+nm[1]);
    if (hit) j.tasks = [hit, ...j.tasks.filter(t => t.id !== hit.id)];
    S.searchRes = j.tasks; S.extra = j.tasks; S.searchResQ = q;
    $('#sresults').innerHTML = renderSearchRes();
    if (S.searchEnter === q) { S.searchEnter = null; searchEnterOpen(q); }
  }, 200);
}
// 2.13.2 (#478 F4): Enter in the search opens the task of an exact "#id" / "id", or the only hit (the results of what was
// typed may still be on their way: then it opens once they are there)
function searchEnterOpen(q) {
  const nm = q.trim().match(/^#?(\d{1,9})$/), r = S.searchResQ === q ? S.searchRes || [] : [];
  const t = nm ? (r.find(x => x.id === +nm[1]) || taskById(+nm[1])) : r.length === 1 ? r[0] : null;
  if (!t) return false;
  if (isMobile()) $('#searchq')?.blur();
  openDetail(t.id); return true;
}
document.addEventListener('keydown', e => {
  if (e.target.id !== 'searchq' || e.key !== 'Enter' || e.isComposing) return;
  const q = e.target.value; e.preventDefault();
  if (q.trim() && !searchEnterOpen(q)) S.searchEnter = q;
  if (S.searchQ !== q) doSearch(q);
});
