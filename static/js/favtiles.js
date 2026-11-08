/* Kalmido web client: favourites of every kind as a row of symbols in the head bar (2.57.0, #1798; 2.441.0, #3592).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md).
   - anything in the sidebar can be a favourite: lists, projects, folders, Plan views, views and areas, filters, tags, people,
     groups, agents; a star in the row's menu (right-click / long press) adds or removes it
   - the favourites are icon tiles (the name as hint, no counts) in ONE order the person arranges (drag, or the tile's menu
     "Move left" / "Move right"); stored in the user setting fav_items (json list of keys), so every device shows the same
   - lists keep their star in fav_lists (favorites.js; pushes, agents and "Only favourites" read it): an "l:<id>" in fav_items
     only holds the place; a starred list missing there goes to the end, an "l:" without a star is left out
   - a favourite the person cannot see now (archived, module off, person gone) is left out silently and stays stored, so it
     comes back with its target; Settings count them
   - 2.441.0 (#3592): everything with an address of its own (a quotation, a page, a table, a contact, a file, a saved view):
     fv2_hashKey turns an address into a key, GET /api/favorites/targets checks those on the server each time (names, routes,
     workspaces of what the person may read). ONE row for all workspaces, a dot shows the workspace; a computer: in the free
     room of the head bar (#kbar), what does not fit under "+N"; a phone (2.552.0 #4618, no sidebar section any more): a row over the tab bar (2.572.0 #4747: swipe up on the tab bar, #favup) or, with the tab
     "Favourites" pinned, a page (#favorites). Dividers are keys too (sep:), the own look is the setting fav_meta. */
'use strict';

// [icon, name] of the Plan views and the rows of "More"
const FV2_VIEWS = {inbox: ['inbox', N_('Basket')], assigned: ['user', N_('My tasks')], today: ['sun', N_('Today')], tomorrow: ['sunrise', N_('Tomorrow')],
  week: ['week', N_('Next 7 days')], doable: ['zap', N_('Now doable')], pinned: ['pin', N_('Pinned|view')], waiting: ['hourglass', N_('Waiting on someone')], mine_wait: ['flag', N_('Waiting for me')],
  stale: ['clock', N_('Lying idle')], byme: ['send', N_('Assigned by me')], all: ['all', N_('All')], done: ['done', N_('Completed')], trash: ['trash', N_('Trash')],
  archived: ['archive', N_('Archived')]};
// [icon, name] of the views and modules (an area of areas.js wins for its id: its row stands for all its parts)
const FV2_MODS = {cal: ['cal', N_('Calendar')], timeline: ['timeline', N_('Timeline')], matrix: ['grid', N_('Matrix')], habits: ['habit', N_('Habits')],
  pomo: ['timer', N_('Focus timer')], time: ['clock', N_('Time tracking')], stats: ['chart', N_('Statistics')], contacts: ['users', N_('Contacts')],
  life: ['home', N_('Home & life')], workload: ['chart', N_('Workload & absences')], office: ['receipt', N_('Office & finance')], wiki: ['book', N_('Knowledge pages')], sheets: ['sheet', N_('Tables')],
  review: ['journal', N_('Review & journal')], family: ['family', N_('Family')], overview: ['pulse', N_('Project status')], agents: ['bot', N_('Agents')],
  notes: ['note', N_('Notes')], news: ['bell', N_('News')], team: ['comment', N_('Team chat')]};  // 2.364.0 B (#3040): one name for the team chat
const FV2 = {drag: null, out: null, add: '', held: 0, lp: null, res: {}, gone: [], at: 0, busy: false, again: false, last: new Map(), over: []};
// 2.441.0 (#3592): the symbol and the module of the objects the server knows; the symbols a person can give a favourite
const FV2_REF = {office_doc: ['receipt', 'office'], office_letter: ['file', 'office'], office_gendoc: ['file', 'office'], office_receipt: ['receipt', 'office'],
  wiki: ['book', 'wiki'], sheet: ['sheet', 'sheets'], contact: ['user', 'contacts'], address_book: ['book', 'contacts'],
  docview: ['filter', 'docs']};  // 2.579.0 (#4802): a saved view of the documents search (docviews.js)
const FV2_ICONS = [['star', N_('Star')], ['flag', N_('Flag')], ['pin', N_('Pin')], ['zap', N_('Flash')], ['tag', N_('Tag')], ['book', N_('Book')], ['folder', N_('Folder')], ['file', N_('Document')],
  ['receipt', N_('Receipt')], ['sheet', N_('Table')], ['user', N_('Person')], ['home', N_('Home')], ['brief', N_('Briefcase')], ['cal', N_('Calendar')], ['chart', N_('Chart')], ['note', N_('Note')]];
const fv2_isObj = key => /^(?:r|file|doc):/.test(key);
const fv2_meta = () => { try { const d = JSON.parse(S.settings?.fav_meta || '{}'); return d && typeof d === 'object' ? d : {}; } catch { return {}; } };

function fv2_stored() {
  let a = []; try { a = JSON.parse(S.settings?.fav_items || '[]'); } catch { a = []; }
  return Array.isArray(a) ? a.filter(x => typeof x === 'string') : [];
}
// the whole order: the stored keys (lists only while starred) + starred lists not placed yet (an older app, an agent)
function fv2_keys() {
  const fl = favIds(), st = fv2_stored().filter(x => !x.startsWith('l:') || fl.includes(+x.slice(2)));
  return [...st, ...fl.map(id => 'l:' + id).filter(x => !st.includes(x))];
}
const fv2_is = key => key.startsWith('l:') ? favIs(+key.slice(2)) : fv2_stored().includes(key);
// the key of a sidebar row (list rows: data-list; '' = cannot be a favourite, e.g. a conversation)
function fv2_rowKey(el) {
  if (!el?.dataset) return '';
  const d = el.dataset;
  if (d.list) return 'l:' + d.list;
  if (d.folder && el.classList.contains('fhead')) return 'folder:' + d.folder;
  if (d.mgside) return 'm:' + d.mgside;
  if (d.act === 'team-agent') return 'a:' + d.aid;
  if (d.act === 'side-timeline') return 'm:timeline';
  return fv2_hashKey(d.go || '');
}
// 2.441.0 (#3592): the key of an address ('' = it cannot be a favourite)
function fv2_hashKey(g) {
  let m;
  if ((m = /^(who|grp|f|l)\/(\d+)$/.exec(g))) return {who: 'p:', grp: 'g:', f: 'f:', l: 'l:'}[m[1]] + m[2];
  if ((m = /^office\/(offers|invoices|letters|gendocs)\/(\d+)$/.exec(g))) return `r:office_${{offers: 'doc', invoices: 'doc', letters: 'letter', gendocs: 'gendoc'}[m[1]]}:${m[2]}`;
  if ((m = /^(wiki|sheets|contacts|contacts\/b)\/(\d+)$/.exec(g))) return `r:${{wiki: 'wiki', sheets: 'sheet', contacts: 'contact', 'contacts/b': 'address_book'}[m[1]]}:${m[2]}`;
  if ((m = /^(?:docs|ablage)\/v\/(\d+)$/.exec(g))) return 'r:docview:' + m[1];  // 2.579.0 (#4802); 2.752.0 (#4887): + #ablage/v/<id>
  if ((m = /^(ablage|docs)\/(\d+)$/.exec(g))) return `${m[1] === 'docs' || AB_FILEIDS.has(+m[2]) ? 'doc' : 'file'}:${m[2]}`;  // 2.752.0 (#4887): #ablage/<id> of a file = its document view
  try {
    if (g.startsWith('tag/')) return 'tag:' + decodeURIComponent(g.slice(4));
    if (g.startsWith('folder/')) return 'folder:' + decodeURIComponent(g.slice(7));
  } catch { return ''; }
  return FV2_VIEWS[g] ? 'v:' + g : FV2_MODS[g] ? 'm:' + g : '';
}
// the key of the page shown: the object, else the view, else its area; '' = this page cannot be a favourite
function fv2_routeKey() {
  const r = S.route; if (!r || S.me?.kid) return '';
  if (r.mod === 'tasks') { const k = r.key || ''; return /^who:\d/.test(k) ? 'p:' + k.slice(4) : /^grp:\d/.test(k) ? 'g:' + k.slice(4) : /^(f|tag|folder):/.test(k) ? k : FV2_VIEWS[k] ? 'v:' + k : ''; }
  let key = ''; try { key = fv2_hashKey(decodeURIComponent(location.hash.slice(1))); } catch { key = ''; }
  if (key) return key;
  const a = mg_areaOf(r.mod)?.[0]; return a && MG_IDS.includes(a) ? 'm:' + a : FV2_MODS[r.mod] ? 'm:' + r.mod : '';
}
// a tile: {key, name, icon, attrs (what a click does, the same as the row), on}; null = not shown now
function fv2_tile(key, ctx) {
  const k = S.route.key, onTasks = S.route.mod === 'tasks', i = key.indexOf(':'), p = key.slice(0, i), v = key.slice(i + 1);
  const go = (h, on) => ({attrs: `data-go="${esc(h)}"`, on});
  if (p === 'sep') return {key, sep: true};
  if (p === 'sv') { const x = (() => { try { return JSON.parse(S.settings?.side_views || '[]'); } catch { return []; } })().find(y => y.id === v); return x ? {key, name: x.name, place: tr('Sidebar views'), icon: ic('panel'), attrs: `data-sv="tile" data-svid="${esc(v)}"`, on: false} : null; }
  if (fv2_isObj(key)) {
    const o = FV2.res[key], d = p === 'r' ? FV2_REF[v.split(':')[0]] : [o?.folder ? 'folder' : 'file', p === 'doc' ? 'docs' : 'ablage']; if (!o || !d) return null;
    if (p === 'r' && !feat(d[1])) return null;
    return {key, name: o.name, place: o.label, ws: o.ws, icon: ic(d[0]), attrs: `data-fv2-go="${esc(o.to)}" data-fv2-ws="${esc(o.ws || '')}"`, on: location.hash.slice(1) === String(o.to || '').replace(/^docs\//, 'ablage/') || location.hash.slice(1) === o.to};  // 2.752.0 (#4887): #docs/… is #ablage/… now
  }
  if (p === 'l') {
    const l = listById(+v); if (!l || l.is_inbox || l.archived || life_store(l) || (!ctx.allWs && !inWs(l))) return null;  // 2.609.0 (#4613): an area's store list is no project tile
    return {key, name: lname(l), place: l.folder ? fDisp(l.folder) : '', ws: wsOf(l), icon: listIconHtml(l, {emoji: true}) || ic('list'), ...go(keyToHash('l:' + l.id), onTasks && k === 'l:' + l.id)};
  }
  if (p === 'folder') {
    if (!folderNames().includes(v) || !(ctx.allWs || wsCur() === 'all' || ctx.lists.some(l => fUnder(l.folder, v)) || sb_folderInWs(v))) return null;
    const fl = S.lists.find(l => !l.is_inbox && fUnder(l.folder, v));
    return {key, name: fDisp(v), ws: fl ? wsOf(fl) : '', icon: `<span class="sic"${lp_folderSty(v)}>${ic('folder')}</span>`, attrs: `data-fv2-go="${esc(keyToHash(key))}" data-fv2-ws="${fl ? esc(wsOf(fl)) : ''}"`, on: onTasks && k === key};
  }
  if (p === 'v') {
    const x = FV2_VIEWS[v]; if (!x || (v === 'byme' && !collab()) || (v === 'archived' && !S.lists.some(l => l.archived && inWs(l)))) return null;
    return {key, name: tr(x[1]), icon: ic(x[0]), ...go(v, onTasks && (k === v || (v === 'archived' && S.lists.some(l => l.archived && k === 'l:' + l.id))))};
  }
  if (p === 'm') {
    if (MG_IDS.includes(v)) {
      const a = mg_area(v); if (!mg_on(v)) return null;
      return {key, name: tr(mg_nameKey(a)), icon: ic(mg_icon(a)), ...go(mg_target(v), mg_areaOf(S.route.mod) === a)};
    }
    const x = FV2_MODS[v]; if (!x) return null;
    if (v === 'timeline') return feat('timeline') ? {key, name: tr(x[1]), icon: ic(x[0]), attrs: 'data-act="side-timeline"', on: isRoadmap()} : null;
    if (v === 'news' ? !collab() : !modOn(v)) return null;
    return {key, name: tr(x[1]), icon: ic(x[0]), ...go(v, S.route.mod === v)};
  }
  if (p === 'f') { const f = S.filters.find(x => x.id === +v); return f ? {key, name: f.name, icon: ic('filter'), ...go(keyToHash(key), onTasks && k === key)} : null; }
  if (p === 'tag') return ctx.c.tags[v] ? {key, name: v, icon: ic('tag'), col: fv2_tagColor(v), ...go(keyToHash(key), onTasks && k === key)} : null;
  if (p === 'p') { const pp = ctx.people.find(x => x.id === +v); return pp ? {key, name: pp.name, icon: av(pp.id, pp.name, 'avatar fv2-av'), ...go('who/' + pp.id, onTasks && k === 'who:' + pp.id)} : null; }
  if (p === 'g') {
    const gr = collab() && (S.groups || []).find(x => x.id === +v && myGroup(x.id)); if (!gr) return null;
    return {key, name: gr.name, icon: ic('users'), ...go('grp/' + gr.id, onTasks && k === 'grp:' + gr.id)};
  }
  if (p === 'a') {
    const a = shownAgents().find(x => x.id === +v); if (!a) return null;
    return {key, name: a.name, icon: `${ic('bot')}<span class="fv2-st"${ac_mk(a.id)}>${hdot(agentHst(a))}</span>`, attrs: `data-act="team-agent" data-aid="${a.id}"`, on: S.route.mod === 'agents' && +S.route.agent === a.id};
  }
  return null;
}
// 2.572.0 (#4749): the colour a project tag has in any list ('' = none); the target's own colour tells equal symbols apart
const fv2_tagColor = name => { for (const l of S.lists) { const c = cssColor((l.tags || []).find(x => String(x.name).toLowerCase() === String(name).toLowerCase())?.color); if (c) return c; } return ''; };
function fv2_tiles(lists = S.lists) {
  const ctx = {lists, c: counts(), people: teamPeople(), allWs: true};  // 2.441.0 (#3592): one row for all workspaces
  return fv2_keys().map(x => { try { return fv2_tile(x, ctx); } catch { return null; } }).filter(Boolean);
}
// 2.441.0 (#3592): a favourite on the screen: the name and its place as the hint, the person's own look, the dot of the workspace
const fv2_hint = t => [t.name, t.place, t.ws && wsOn() ? wsName(t.ws) : ''].filter(Boolean).join(' · ');
// 2.572.0 (#4749): equal symbols twice or more in ONE row (the head bar, the phone's row) are told apart on their own: the target's own
// colour when it is unique in the group, else a small badge with the first letter (the first two when letters collide). A look the person
// set (fav_meta) always wins and is left alone. Call it ONCE for the whole row (fv2_barDraw, the phone's row); it sets t.dk = {c} | {b} and returns the tiles.
function fv2_distinct(ts) {
  const meta = fv2_meta(), groups = new Map();
  for (const t of ts) {
    delete t.dk;
    if (t.sep || !t.icon) continue;
    const m = meta[t.key] || {}; if (m.i || m.c) continue;
    (groups.get(t.icon) || groups.set(t.icon, []).get(t.icon)).push(t);
  }
  const ch = (t, n) => Array.from(String(t.name || '').replace(/^[#\s]+/, '')).slice(0, n).join('').toLocaleUpperCase();
  for (const g of groups.values()) {
    if (g.length < 2) continue;
    const cnt = {}; for (const t of g) if (t.col) cnt[t.col.toLowerCase()] = (cnt[t.col.toLowerCase()] || 0) + 1;
    const rest = [];
    for (const t of g) { if (t.col && cnt[t.col.toLowerCase()] === 1) t.dk = {c: t.col}; else rest.push(t); }
    if (rest.length === 1 && g.length > 1) continue;  // all others got their colour: the last one is different already
    const one = {}; for (const t of rest) one[ch(t, 1)] = (one[ch(t, 1)] || 0) + 1;
    for (const t of rest) { const b = one[ch(t, 1)] > 1 ? ch(t, 2) : ch(t, 1); if (b) t.dk = {b}; }
  }
  return ts;
}
function fv2_tileHtml(t, page) {
  const drag = isTouch() ? '' : ' draggable="true"';  // 2.655.0 (#5085): was isMobile(); a finger by drag.js
  if (t.sep) return page ? '' : `<span class="fv2-sep" data-fv2="${esc(t.key)}" role="separator"${drag}></span>`;
  const m = fv2_meta()[t.key] || {}, dot = t.ws && wsOn() ? `<span class="fv2-wsd">${wsp_dot(t.ws)}</span>` : '';
  return `<button type="button" class="fv2-tile ${t.on ? 'on' : ''}" data-fv2="${esc(t.key)}" ${t.attrs} title="${esc(fv2_hint(t))}" aria-label="${esc(fv2_hint(t))}"${t.on ? ' aria-current="page"' : ''}${m.c || (!page && t.dk?.c) ? ` style="--fvc:${esc(m.c || t.dk.c)}"` : ''}${drag}>${m.i ? ic(m.i) : t.icon}${!page && t.dk?.b ? `<span class="fv2-bdg" aria-hidden="true">${esc(t.dk.b)}</span>` : ''}${dot}${page ? `<span class="fv2-pn">${esc(t.name)}</span>${t.place ? `<span class="fv2-pp">${esc(t.place)}</span>` : ''}` : ''}</button>`;
}
// the row: a computer in the head bar (left empty by sbb_barHtml), else above the tab bar (#favup, a phone: swipe up on the
// tab bar or tap the grip, fvd_* below); neither while the page is pinned
// 2.552.0 (#4618): takes back #4014 -- the phone's sidebar shows no section "Favourites" (fv2_sideHtml), only this row or the tab
// 2.572.0 (#4747): the phone's row moved from under the header (#favrow, ~120 px of every page) to a row over the tab bar
const fv2_pagePinned = () => { try { return isMobile() && tabIds().includes('favs'); } catch { return false; } };
function fv2_barDraw() {
  const kb = $('#kbar .fv2bar'), row = $('#favup'), mini = document.documentElement.classList.contains('mini') || document.documentElement.classList.contains('mini-task');
  const on = kb || (row && !mini && !fv2_pagePinned() ? row : null);
  if (row && row !== on && row.firstChild) { row.innerHTML = ''; FV2.last.delete(row); }
  if (on !== row) fvd_sync(0);
  if (!on) return;
  fv2_fetch();
  const ts = fv2_distinct(fv2_tiles()), body = ts.map(t => fv2_tileHtml(t)).join('');
  const html = on === kb ? `${body}<button type="button" class="fv2-more" data-fv2-more hidden aria-haspopup="menu"></button>` : body;
  if (on === row) fvd_sync(ts.filter(t => !t.sep).length);
  if (FV2.last.get(on) === html && on.firstChild) { if (on === kb) fv2_fit(); return; }
  FV2.last.set(on, html);
  on.setAttribute('aria-label', tr('Favourites'));
  keepFocus(on, () => { on.innerHTML = html; });
  if (on === kb) fv2_fit();
}
// "+N": what does not fit stays hidden in the row and is offered by the button at its end; the bar never takes room from the others
function fv2_fit(again) {
  const h = $('#kbar .fv2bar'), more = h && $('.fv2-more', h); if (!more) return;
  const kids = $$('.fv2-tile, .fv2-sep', h), kb = $('#kbar');
  kids.forEach(x => { x.hidden = false; });
  more.hidden = true; FV2.over = [];
  kb?.classList.toggle('kb-mini', false);  // 2.572.0 (#4746): the search shrinks first by CSS (to 7rem); if that is not enough it becomes the loupe, only then "+N"
  if (h.scrollWidth <= h.clientWidth) return;
  kb?.classList.toggle('kb-mini', true);
  if (h.scrollWidth <= h.clientWidth) return;
  more.hidden = false; more.textContent = '+' + kids.length;
  const cs = getComputedStyle(h), gap = parseFloat(cs.columnGap) || 0;
  const room = h.clientWidth - parseFloat(cs.paddingRight) - more.offsetWidth - gap;
  let used = parseFloat(cs.paddingLeft) || 0;
  for (const x of kids) { used += x.offsetWidth + gap; if (used > room) { x.hidden = true; FV2.over.push(x); } }
  for (let i = kids.length - FV2.over.length - 1; i >= 0 && kids[i].classList.contains('fv2-sep'); i--) { kids[i].hidden = true; FV2.over.unshift(kids[i]); }  // no divider at the end
  const n = FV2.over.filter(x => !x.classList.contains('fv2-sep')).length, lab = trn('{0} more favourite', '{0} more favourites', n);
  more.textContent = '+' + n; more.title = lab; more.setAttribute('aria-label', lab);
  more.classList.toggle('on', FV2.over.some(x => x.classList.contains('on')));
  if (!again) requestAnimationFrame(() => fv2_fit(true));  // 2.572.0 (#4746): the loupe changes the room, one more look at the settled layout
}
function fv2_moreMenu(b) {
  menu(b, [...FV2.over.filter(x => x.classList.contains('fv2-tile')).map(x => ({label: x.getAttribute('aria-label'), icon: 'star', on: x.classList.contains('on'), fn: () => x.click()})), ...fv2_onlyItem()], null, null, tr('Favourites'));
}
try { new ResizeObserver(() => fv2_fit()).observe(document.documentElement); } catch { /* an old engine: fitted at each draw */ }
// the page "Favourites" (the tab of a phone; #favorites)
function viewFavPage() {
  const ts = fv2_tiles().filter(t => !t.sep);
  return ts.length ? `<div class="fv2bar fv2-page" role="group" aria-label="${esc(tr('Favourites'))}">${ts.map(t => fv2_tileHtml(t, true)).join('')}</div>`
    : `<div class="empty">${ic('star')}${esc(tr('No favourites yet. Star what you really work with: the star next to a title, or the menu of a row.'))}</div>`;
}
// what the server knows: at the first draw, after a change and every few minutes
async function fv2_fetch(force) {
  if (!force && Date.now() - FV2.at < 300000) return;
  if (FV2.busy) { FV2.again = FV2.again || !!force; return; }
  if (!fv2_stored().some(fv2_isObj)) { FV2.res = {}; FV2.gone = []; FV2.at = Date.now(); return; }
  FV2.busy = true; FV2.at = Date.now();
  try { const j = await rawFetch('GET', '/api/favorites/targets'); FV2.res = j.items || {}; FV2.gone = j.gone || []; } catch { /* offline or an older server: the row stays as it is */ }
  FV2.busy = false;
  if (FV2.again) { FV2.again = false; fv2_fetch(true); return; }
  fv2_barDraw();
  if (S.route.key === 'favorites') render();
}
// 2.441.0 (#3592): the favourites that show nothing now: the target is gone or the access is (Settings); they stay stored
function fv2_goneKeys() {
  const ctx = {lists: S.lists, c: counts(), people: teamPeople(), allWs: true};
  return fv2_keys().filter(k => { if (k.startsWith('sep:')) return false; if (fv2_isObj(k)) return FV2.gone.includes(k); try { return !fv2_tile(k, ctx); } catch { return true; } });
}
// open a favourite that lives in a workspace: the switch follows it (the office answers only for the workspace shown)
async function fv2_open(b) {
  const ws = b.dataset.fv2Ws, cur = wsCur();
  if (ws && wsOn() && ws !== cur && wsOptions().includes(ws) && (cur !== 'all' || b.dataset.fv2.startsWith('r:office'))) await wsSet(ws);
  go(b.dataset.fv2Go);
}
// the sidebar (renderSide via favSideHtml): no section "Favourites" in any layout -- a computer has them in the head bar, a phone in the row
// over the tab bar (#favup, 2.572.0 #4747) or on the tab (2.552.0 #4618, takes back #4014); "Only favourites" is in the menu of a tile (fv2_onlyItem)
// what stays: the view tiles ("Everything" + one per view, sideviews.js)
function fv2_sideHtml() {
  const sv = sv_tilesHtml();
  return sv ? `<div class="sgroup sg-favs sg-svonly">${sv}</div>` : '';  // 2.156.0 D (#2186)
}

// ---- saving: one PATCH per change, shown at once; a failure loads the server's state again
async function fv2_save(arr) {
  S.settings.fav_items = JSON.stringify(arr);
  render();
  try { await api('PATCH', '/api/settings', {fav_items: arr}); fv2_fetch(true); } catch { try { await load(); } catch { /* offline */ } render(); }
}
// one change = one undo step
function fv2_change(arr, msg) {
  const before = fv2_keys();
  fv2_save(arr);
  offerUndo(msg, histAdd({label: msg, undo: () => fv2_save(before), redo: () => fv2_save(arr)}));
}
// favorites.js favSet: a list's place follows its star at once (the server does the same)
function fv2_listFollow(id, on) {
  const key = 'l:' + +id; if (on && fv2_stored().includes(key)) return;  // a star set again keeps its place
  const st = fv2_stored().filter(x => x !== key);
  S.settings.fav_items = JSON.stringify(on ? [...st, key] : st);
}
async function fv2_set(key, on, to, after) {
  // 2.638.0 (#5013): a list's place only after the answer of its star (that answer sets fav_items: the place would be lost)
  if (key.startsWith('l:')) { await favSet(+key.slice(2), on); if (on && to) fv2_move(key, to, after); return; }
  const arr = fv2_keys().filter(x => x !== key);
  if (on) { const i = to ? arr.indexOf(to) : -1; arr.splice(i < 0 ? arr.length : i + (after ? 1 : 0), 0, key); }
  fv2_change(arr, on ? tr('Added to favourites') : tr('Removed from favourites'));
}
// key moves in front of (after = behind) the key `to`
function fv2_move(key, to, after) {
  const arr = fv2_keys().filter(x => x !== key); if (key === to || !arr.includes(to)) return;
  arr.splice(arr.indexOf(to) + (after ? 1 : 0), 0, key);
  fv2_change(arr, tr('Favourites rearranged'));
}
// 2.441.0 (#3592): the own look of one favourite and the divider behind it
async function fv2_metaSet(key, patch) {
  const keep = new Set(fv2_keys()), d = Object.fromEntries(Object.entries(fv2_meta()).filter(([k]) => keep.has(k))), x = {...(d[key] || {}), ...patch};  // what left the row takes its look along
  if (!x.c) delete x.c;
  if (!x.i) delete x.i;
  if (x.c || x.i) d[key] = x; else delete d[key];
  S.settings.fav_meta = JSON.stringify(d);
  render();
  try { await api('PATCH', '/api/settings', {fav_meta: d}); } catch { try { await load(); } catch { /* offline */ } render(); }
}
const fv2_sepAdd = key => fv2_set('sep:' + (Date.now() % 1e9), true, key, true);
// the star in a page's header (render.js renderTop; lists have favTopBtn): the same place on every page
function fv2_topBtn() {
  const key = fv2_routeKey(); if (!key) return '';
  const on = fv2_is(key), lab = on ? tr('Remove from favourites') : tr('Add to favourites');
  return `<button type="button" class="iconbtn hfav tf ${on ? 'on' : ''}" data-fv2-star="${esc(key)}" aria-pressed="${on}" title="${esc(lab)}" aria-label="${esc(lab)}">${ic('star', 's')}</button>`;
}
// the same in "…" (a phone has no room for the star in the header)
const fv2_topItems = () => isMobile() ? fv2_menuRow(fv2_routeKey()) : [];
// the entry for a row's menu
const fv2_menuRow = key => !key ? [] : fv2_is(key) ? [{label: tr('Remove from favourites'), icon: 'star', fn: () => fv2_set(key, false)}]
  : [{label: tr('Add to favourites'), icon: 'star', fn: () => fv2_set(key, true)}];
// 2.521.0 (#4396): "Only favourites" lives in the head bar's menus (the sidebar shows no section "Favourites" then); same setting as [data-fav-only]
const fv2_onlyItem = () => !favAny() ? [] : ['-', {label: tr('Only favourites'), icon: 'filter', on: favOnly(), fn: () => favSetting('fav_only', favOnly() ? '0' : '1')}];
// a tile's menu: open, move (WCAG 2.5.7: arranging without dragging), remove
function fv2_tileMenu(b) {
  const key = b.dataset.fv2, box = b.closest('.fv2bar, .fv2side'), sh = box ? $$('[data-fv2]', box).map(x => x.dataset.fv2) : [], i = sh.indexOf(key), col = !!box?.classList.contains('fv2side'); if (i < 0) return;
  if (key.startsWith('sep:')) { menu(b, [{label: tr('Remove the divider'), icon: 'x', fn: () => fv2_set(key, false)}]); return; }
  const name = b.getAttribute('aria-label') || b.querySelector('.n')?.textContent || '', m = fv2_meta()[key] || {};
  menu(b, [{label: name, dis: true, cls: 'mhead'}, '-',
    {label: tr('Open'), icon: 'right', fn: () => b.click()},
    {label: col ? tr('Move up') : tr('Move left'), icon: col ? 'up' : 'left', dis: i === 0, fn: () => fv2_move(key, sh[i - 1], false)},
    {label: col ? tr('Move down') : tr('Move right'), icon: col ? 'down' : 'right', dis: i === sh.length - 1, fn: () => fv2_move(key, sh[i + 1], true)},
    ...(col ? [] : [{label: tr('Add a divider'), icon: 'minus', fn: () => fv2_sepAdd(key)}]), '-',  // 2.489.0 (#4014): the sidebar's entries show no dividers
    lp_menuRow(m.c || '', c => fv2_metaSet(key, {c})),
    {label: tr('Symbol…'), icon: m.i || 'star', more: [{label: tr('Default'), on: !m.i, fn: () => fv2_metaSet(key, {i: ''})}, ...FV2_ICONS.map(x => ({label: tr(x[1]), icon: x[0], on: m.i === x[0], fn: () => fv2_metaSet(key, {i: x[0]})}))]},
    '-', {label: tr('Remove from favourites'), icon: 'star', fn: () => fv2_set(key, false)},
    ...(col ? [] : fv2_onlyItem())]);
}
// a row without a menu of its own (Plan, views, areas, filters, tags, people, groups, agents): a small one with the star
function fv2_rowMenu(r) {
  const key = fv2_rowKey(r); if (!key) return false;
  if (key.startsWith('tag:')) { tagMenu(r, key.slice(4)); return true; }  // a tag has its menu (render.js), the star is in it
  const name = r.querySelector('.n')?.textContent || r.getAttribute('aria-label') || '';
  menu(r, [...(name ? [{label: name, dis: true, cls: 'mhead'}, '-'] : []), ...fv2_menuRow(key), ...sbp_menuRow(r)]);  // 2.99.0 E (#2187): + pin a person
  return true;
}
const FV2_ROWS = '#side .srow:not([data-list]):not(.reorder):not(.smore):not(.sfavmore):not(.sset):not(.fv2-row)';
const FV2_TILES = '.fv2bar .fv2-tile, .fv2bar .fv2-sep, .fv2side .fv2-row';  // 2.489.0 (#4014): + the sidebar's entries (menu only, no dragging)

// (capture: a tile's menu is the only one; an agent row that opens a chat and a tag keep their own menus with the star in them:
// chatwins.js, render.js tagMenu)
document.addEventListener('contextmenu', e => {
  if (e.shiftKey) return;
  const t = e.target.closest?.(FV2_TILES), r = !t && e.target.closest?.(FV2_ROWS);
  if (!t && !(r && fv2_rowKey(r) && !cw_target(r) && !r.matches('[data-drop^="tag:"]'))) return;
  if (t) e.stopImmediatePropagation();
  if (e.pointerType === 'touch') { e.preventDefault(); return; }  // the long press below is the app's, no browser menu
  if (isTouch() && !t) return;
  e.preventDefault();
  if (t) fv2_tileMenu(t); else fv2_rowMenu(r);
}, true);
// a click right after a long press is not a click
document.addEventListener('click', e => {
  if (Date.now() - FV2.held < 600 && e.target.closest?.(FV2_TILES + ', ' + FV2_ROWS)) { e.preventDefault(); e.stopImmediatePropagation(); }
}, true);

// ---- dragging a tile with the mouse (desktop, Fold): drop on another tile = in front of it / behind it (right half)
const fv2_after = (t, x) => { const r = t.getBoundingClientRect(); return x > r.left + r.width / 2; };
function fv2_mark(t, x) {
  // 2.87.9 (#1965): the mark changes only when the tile or its half changes
  const cls = t && t.dataset.fv2 !== FV2.drag ? (fv2_after(t, x) ? 'fv2-after' : 'fv2-before') : null;
  if (cls && FV2.mk === t && t.classList.contains(cls)) return;
  $$('.fv2bar .fv2-before, .fv2bar .fv2-after').forEach(b => b.classList.remove('fv2-before', 'fv2-after'));
  FV2.mk = cls ? t : null; if (cls) t.classList.add(cls);
}
// the tile under (or in the grid, nearest to) the pointer
function fv2_target(x, y) {
  const el = document.elementFromPoint(x, y), t = el?.closest?.('.fv2bar .fv2-tile, .fv2bar .fv2-sep'); if (t) return t;
  if (!el?.closest?.('.fv2bar')) return null;
  let best = null, bd = 1e9;
  for (const b of $$('.fv2bar [data-fv2]:not([hidden])')) { const r = b.getBoundingClientRect(), d = Math.hypot(r.left + r.width / 2 - x, r.top + r.height / 2 - y); if (d < bd) { bd = d; best = b; } }
  return best;
}
function fv2_drop(t, x, rel) {
  const key = FV2.drag, out = !!rel && !!FV2.out; FV2.drag = null; fv2_outSet(null, false);  // 2.551.0 (#4615): rel = really let go (not Esc / cancelled)
  $$('.fv2bar .fv2-before, .fv2bar .fv2-after, .fv2bar .dragging').forEach(b => b.classList.remove('fv2-before', 'fv2-after', 'dragging'));
  if (out && key) { fv2_dragOut(key); return; }
  if (key && t && t.dataset.fv2 !== key) fv2_move(key, t.dataset.fv2, fv2_after(t, x));
}
// 2.551.0 (#4615): a tile dragged well below the bar (about 1.5 tile heights under it) is out: the tile shows a crossed symbol,
// the bar "Release to remove"; let go there = removed (Undo in the hint), back into the bar = moving again. Touch and mouse alike.
const fv2_dragTile = () => FV2.drag ? $$('.fv2bar [data-fv2]').find(x => x.dataset.fv2 === FV2.drag) || null : null;
function fv2_isOut(t, y) {
  const bar = t?.closest?.('.fv2bar'); if (!bar || bar.classList.contains('fv2-page')) return false;
  const r = bar.getBoundingClientRect(), h = t.getBoundingClientRect().height || t.offsetHeight || 30;
  return y > r.bottom + 1.5 * h;
}
function fv2_outSet(t, on) {
  if (on ? FV2.out === t : !FV2.out) return;
  FV2.out = on ? t : null;
  $$('.fv2bar .fv2-out').forEach(x => x.classList.remove('fv2-out'));
  $$('.fv2bar.fv2-outing').forEach(b => { b.classList.remove('fv2-outing'); b.removeAttribute('data-out'); });
  if (!on || !t) return;
  const bar = t.closest('.fv2bar'); t.classList.add('fv2-out'); fv2_mark(null, 0);
  if (bar) { bar.classList.add('fv2-outing'); bar.dataset.out = tr('Release to remove'); }
  announce(tr('Release to remove'));
}
// removed by dragging it out: the hint with Undo (a list's star too, which favSet keeps without one); Undo puts it back in its place
function fv2_dragOut(key) {
  const ks = fv2_keys(), nx = ks[ks.indexOf(key) + 1];
  if (!key.startsWith('l:')) { fv2_set(key, false); return; }  // fv2_change offers the Undo
  favSet(+key.slice(2), false);
  toast(tr('Removed from favourites'), () => fv2_set(key, true, nx, false));
}
// 2.441.0 (#3592): anything with an address dragged into the row becomes a favourite (a sidebar row, a link)
function fv2_dragKey(e) {
  const el = e.target?.closest?.('[data-list],[data-go],.fhead[data-folder],a[href^="#"]'); if (!el || el.closest('.fv2bar')) return '';
  const h = el.getAttribute('href');
  if (h?.startsWith('#')) { try { return fv2_hashKey(decodeURIComponent(h.slice(1))); } catch { return ''; } }
  return fv2_rowKey(el);
}
function fv2_addEnd() { FV2.add = ''; $$('.fv2bar.fv2-drop').forEach(b => b.classList.remove('fv2-drop')); fv2_mark(null, 0); }
document.addEventListener('dragstart', e => {
  const t = e.target.closest?.('.fv2bar [data-fv2][draggable="true"]');
  if (!t) { FV2.add = fv2_dragKey(e); if (FV2.add) $$('.fv2bar').forEach(b => b.classList.add('fv2-drop')); return; }
  FV2.drag = t.dataset.fv2; FV2.out = null; e.dataTransfer.effectAllowed = 'move';
  try { e.dataTransfer.setData('text/plain', 'fav:' + FV2.drag); } catch { /* old browsers */ }
  requestAnimationFrame(() => t.classList.add('dragging'));
});
// on window, before the sidebar's own drag of a list on document sees the row
window.addEventListener('dragover', e => {
  if (!FV2.add || !e.target.closest?.('.fv2bar')) return;
  e.preventDefault(); e.stopPropagation(); e.dataTransfer.dropEffect = 'copy'; fv2_mark(fv2_target(e.clientX, e.clientY), e.clientX);
}, true);
document.addEventListener('dragover', e => {
  if (!FV2.drag) return;
  const d = fv2_dragTile(), out = fv2_isOut(d, e.clientY); fv2_outSet(d, out);  // 2.551.0 (#4615)
  if (out) { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; return; }
  const t = fv2_target(e.clientX, e.clientY); fv2_mark(t, e.clientX);
  if (t) e.preventDefault();
});
window.addEventListener('drop', e => {
  if (!FV2.add || !e.target.closest?.('.fv2bar')) return;
  e.preventDefault(); e.stopPropagation();
  const key = FV2.add, t = fv2_target(e.clientX, e.clientY), after = t ? fv2_after(t, e.clientX) : false; fv2_addEnd();
  if (!fv2_is(key)) fv2_set(key, true, t?.dataset.fv2, after);
}, true);
document.addEventListener('drop', e => {
  if (!FV2.drag) return;
  e.preventDefault(); e.stopImmediatePropagation();
  fv2_drop(FV2.out ? null : fv2_target(e.clientX, e.clientY), e.clientX, true);
}, true);
document.addEventListener('dragend', () => { if (FV2.drag) fv2_drop(null, 0); if (FV2.add) fv2_addEnd(); });
// the star of a page, a favourite that opens through its workspace, "+N"
document.addEventListener('click', e => {
  const s = e.target.closest?.('[data-fv2-star]'), b = !s && e.target.closest?.('[data-fv2-go]'), m = !s && !b && e.target.closest?.('[data-fv2-more]');
  if (!s && !b && !m) return;
  e.preventDefault(); e.stopPropagation();
  if (s) fv2_set(s.dataset.fv2Star, !fv2_is(s.dataset.fv2Star));
  else if (b) fv2_open(b);
  else fv2_moreMenu(m);
}, true);

// ---- touch: hold a tile = its menu (let go) or drag it (move after the hold); hold another row = its menu with the star.
// 2.627.0 (#4966): by drag.js (was an own touch path): the same hold (420 ms), a scroll before it ends the press, Esc and a
// second finger cancel the drag (the tile goes back). FV2.lp = the running press.
drg_attach(document, {
  mouse: false, onTarget: true, hold: 420, holdMove: 8, threshold: 1,
  start: el => {
    const t = /** @type {any} */ (el).closest?.(FV2_TILES), r = !t && !S.listReorder && /** @type {any} */ (el).closest?.(FV2_ROWS);
    if (!t && !(r && fv2_rowKey(r))) return null;
    // the page's and the sidebar's rows have only the menu; 2.572.0 (#4747): the phone's row too (arranging by dragging stays the computer's)
    return (FV2.lp = {el: t || r, tile: !!t, only: !t || !!t.closest('.fv2-page, .fv2side, #favup')});
  },
  onHold: lp => {
    FV2.held = Date.now();
    if (navigator.vibrate) navigator.vibrate(12);
    if (lp.only) { FV2.lp = null; drg_cancel(); if (lp.tile) fv2_tileMenu(lp.el); else fv2_rowMenu(lp.el); return; }  // the menu at once
    lp.on = true; FV2.drag = lp.el.dataset.fv2; FV2.out = null; lp.el.classList.add('dragging');
  },
  onMove: (lp, x, y) => {
    if (!lp.on) return;
    const out = !!FV2.drag && fv2_isOut(lp.el, y); fv2_outSet(lp.el, out);  // 2.551.0 (#4615)
    if (!out) fv2_mark(fv2_target(x, y), x);
  },
  onDrop: (lp, x, y) => { if (FV2.lp === lp) FV2.lp = null; FV2.held = Date.now(); if (lp.on) fv2_drop(FV2.out ? null : fv2_target(x, y), x, true); },
  onTap: lp => {  // held, let go without moving: the tile's menu
    if (FV2.lp === lp) FV2.lp = null; FV2.held = Date.now();
    FV2.drag = null; lp.el.classList.remove('dragging');
    fv2_tileMenu(lp.el);
  },
  onCancel: lp => { if (FV2.lp === lp) FV2.lp = null; if (lp.on) fv2_drop(null, 0); },  // a quick tap: the tile's own click
});

// ---- the fixed head gets a fine line while the sidebar is scrolled below it
document.addEventListener('scroll', e => { if (e.target?.id === 'side') e.target.classList.toggle('fv2-scrolled', e.target.scrollTop > 2); }, {capture: true, passive: true});

// ---- 2.156.0 D (#2186): saved views of the sidebar (sideviews.js, loaded on demand). Until it is loaded the sidebar is
// "Everything" and these stand-ins answer for it; a person with views (or the tool menu, the settings) loads it, then the
// sidebar draws again. The module's own functions replace the stand-ins on window.
const fv2_svHas = () => { const v = S.settings?.side_views; return !!v && v !== '[]'; };
function fv2_svLoad() {
  if (fv2_svLoad.p) return fv2_svLoad.p;
  fv2_svLoad.p = loadModule('sideviews').then(() => { renderSide(); }, e => { fv2_svLoad.p = null; throw e; });
  return fv2_svLoad.p;
}
window.sv_open = window.sv_fold = () => null;
window.sv_toggle = window.sv_foldSet = window.sv_setAll = () => false;
window.sv_tilesHtml = () => '';
window.sv_after = () => { if (fv2_svHas()) fv2_svLoad().catch(() => {}); };
window.sv_setHtml = () => { fv2_svLoad().then(() => { const b = $('#s-sv-wrap'); if (b) b.outerHTML = sv_setHtml(); }, () => {}); return '<div id="s-sv-wrap"></div>'; };
// the tool button in the sidebar's head: save the sidebar as it is as a view, update / edit the active one, manage them
const fv2_svToolBtn = () => `<button type="button" class="iconbtn svtool" data-svt="1" aria-haspopup="menu" title="${esc(tr('Sidebar views'))}" aria-label="${esc(tr('Sidebar views'))}">${ic('panel', 's')}</button>`;
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-svt]'); if (!b) return;
  e.preventDefault(); e.stopPropagation();
  fv2_svLoad().then(() => sv_toolMenu($('#side [data-svt]') || b), () => {});  // lazy-ok: fv2_svLoad loaded sideviews.js first
}, true);

// ---- 2.572.0 (#4747): a phone's favourites over the tab bar. The row under the header is gone; a swipe up that starts ON the
// tab bar (not at the screen's edge: the system's own gestures live there) or a tap on the small grip over it slides the row
// in above the bar (#favup, the same tiles as the head bar, swiped sideways when they are many). A tile, a swipe down, a tap
// next to it or Escape closes it. No grip and no row while the tab "Favourites" is pinned (fv2_pagePinned), while a field has
// the focus (the keyboard is up: nothing sticks over it) or the tab bar itself is away. Motion: start-favswipe-4747.css (an_up
// in, an_down out via an_watch; "reduce motion" switches both off).
const FVD = {n: 0, g: null, sw: 0};
const FVD_SW = 28;  // px a finger must travel up (and mostly straight) before the row opens: a tap on a tab moves far less
const fvd_isOpen = () => { const r = $('#favup'); return !!r && !r.classList.contains('hidden'); };
function fvd_can() {
  const tb = $('#tabs'), b = document.body.classList;
  return FVD.n > 0 && isMobile() && !fv2_pagePinned() && !editFocused() && !b.contains('kb-open') && !!tb && tb.offsetHeight > 0;
}
// n = the number of tiles in the row (fv2_barDraw), undefined = only check again (focus, keyboard)
function fvd_sync(n) {
  if (n !== undefined) FVD.n = n;
  const g = $('#favgrip'); if (!g) return;
  const can = fvd_can();
  if (!can && fvd_isOpen()) fvd_set(false);
  g.classList.toggle('hidden', !can);
  if (can && g.title !== tr('Favourites')) { g.title = tr('Favourites'); g.setAttribute('aria-label', tr('Favourites')); }
}
function fvd_set(on) {
  const r = $('#favup'), g = $('#favgrip'); if (!r || !g || (on && !fvd_can()) || on === fvd_isOpen()) return;
  r.classList.toggle('hidden', !on);
  g.setAttribute('aria-expanded', String(on));
  document.body.classList.toggle('favup-open', on);
  if (on) { const t = $('.fv2-tile.on', r); if (t) r.scrollLeft = Math.max(0, t.offsetLeft - (r.clientWidth - t.offsetWidth) / 2); }
  else if (r.contains(document.activeElement)) g.focus({preventScroll: true});
}
// the swipe: on the tab bar, the grip and the row; up opens, down closes; a click on a tab right after a swipe is no tap on it
function fvd_touchStart(e) {
  const p = e.touches?.[0];
  FVD.g = p && e.touches.length === 1 ? {x: p.clientX, y: p.clientY, done: false} : null;
}
function fvd_touchMove(e) {
  const g = FVD.g, p = e.touches?.[0]; if (!g || g.done || !p) return;
  const dx = p.clientX - g.x, dy = p.clientY - g.y;
  if (Math.abs(dy) < FVD_SW || Math.abs(dy) < 1.5 * Math.abs(dx)) return;
  const open = fvd_isOpen();
  if (dy < 0 && !open) fvd_set(true); else if (dy > 0 && open) fvd_set(false); else return;
  g.done = true; FVD.sw = Date.now();
  if (e.cancelable) e.preventDefault();
}
domReady(() => {
  for (const el of [$('#tabs'), $('#favgrip'), $('#favup')]) {
    if (!el) continue;
    el.addEventListener('touchstart', fvd_touchStart, {passive: true});
    el.addEventListener('touchmove', fvd_touchMove, {passive: false});
    el.addEventListener('touchend', () => { FVD.g = null; }, {passive: true});
    el.addEventListener('touchcancel', () => { FVD.g = null; }, {passive: true});
  }
  if (typeof an_watch === 'function') an_watch($('#favup'), 'hidden');
});
// the grip toggles; a tile opens its target and closes the row; any other tap closes it (on window, before the app's handlers)
window.addEventListener('click', e => {
  const t = e.target; if (Date.now() - FV2.held < 600) return;  // the click after a long press (the tile's menu) is none
  if (Date.now() - FVD.sw < 350 && t.closest?.('#tabs')) { e.preventDefault(); e.stopPropagation(); return; }
  if (t.closest?.('#favgrip')) { e.preventDefault(); e.stopPropagation(); fvd_set(!fvd_isOpen()); return; }
  if (!fvd_isOpen()) return;
  if (!t.closest?.('#favup') || t.closest('#favup .fv2-tile')) fvd_set(false);
}, true);
document.addEventListener('pointerdown', e => { if (fvd_isOpen() && !e.target.closest?.('#favup, #favgrip, #tabs, #pop')) fvd_set(false); }, true);
domReady(() => kb_on('first', 'Escape', () => {  // 2.655.0 (#4998): key registry (keys.js), before every field and area
  if (!fvd_isOpen() || !$('#pop')?.classList.contains('hidden')) return false;
  fvd_set(false); $('#favgrip')?.focus({preventScroll: true});
}));
// a field takes or leaves the focus (the keyboard comes or goes), the phone turns: the grip follows
document.addEventListener('focusin', () => fvd_sync(), true);
document.addEventListener('focusout', () => setTimeout(() => fvd_sync(), 0), true);
window.addEventListener('resize', () => requestAnimationFrame(() => fvd_sync()));
