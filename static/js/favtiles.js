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
     room of the head bar (#kbar), what does not fit under "+N"; without a head bar (a phone, 2.489.0 #4014) entries in the sidebar's
     section "Favourites" or, with the tab "Favourites" pinned, a page (#favorites). Dividers are keys too (sep:), the own look is the setting fav_meta. */
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
const FV2 = {drag: null, add: '', held: 0, lp: null, res: {}, gone: [], at: 0, busy: false, again: false, last: new Map(), over: []};
// 2.441.0 (#3592): the symbol and the module of the objects the server knows; the symbols a person can give a favourite
const FV2_REF = {office_doc: ['receipt', 'office'], office_letter: ['file', 'office'], office_gendoc: ['file', 'office'], office_receipt: ['receipt', 'office'],
  wiki: ['book', 'wiki'], sheet: ['sheet', 'sheets'], contact: ['user', 'contacts'], address_book: ['book', 'contacts']};
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
  if ((m = /^(ablage|docs)\/(\d+)$/.exec(g))) return `${m[1] === 'docs' ? 'doc' : 'file'}:${m[2]}`;
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
    return {key, name: o.name, place: o.label, ws: o.ws, icon: ic(d[0]), attrs: `data-fv2-go="${esc(o.to)}" data-fv2-ws="${esc(o.ws || '')}"`, on: location.hash.slice(1) === o.to};
  }
  if (p === 'l') {
    const l = listById(+v); if (!l || l.is_inbox || l.archived || (!ctx.allWs && !inWs(l))) return null;
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
  if (p === 'tag') return ctx.c.tags[v] ? {key, name: v, icon: ic('tag'), ...go(keyToHash(key), onTasks && k === key)} : null;
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
function fv2_tiles(lists = S.lists) {
  const ctx = {lists, c: counts(), people: teamPeople(), allWs: true};  // 2.441.0 (#3592): one row for all workspaces
  return fv2_keys().map(x => { try { return fv2_tile(x, ctx); } catch { return null; } }).filter(Boolean);
}
// 2.441.0 (#3592): a favourite on the screen: the name and its place as the hint, the person's own look, the dot of the workspace
const fv2_hint = t => [t.name, t.place, t.ws && wsOn() ? wsName(t.ws) : ''].filter(Boolean).join(' · ');
function fv2_tileHtml(t, page) {
  const drag = isMobile() ? '' : ' draggable="true"';
  if (t.sep) return page ? '' : `<span class="fv2-sep" data-fv2="${esc(t.key)}" role="separator"${drag}></span>`;
  const m = fv2_meta()[t.key] || {}, dot = t.ws && wsOn() ? `<span class="fv2-wsd">${wsp_dot(t.ws)}</span>` : '';
  return `<button type="button" class="fv2-tile ${t.on ? 'on' : ''}" data-fv2="${esc(t.key)}" ${t.attrs} title="${esc(fv2_hint(t))}" aria-label="${esc(fv2_hint(t))}"${t.on ? ' aria-current="page"' : ''}${m.c ? ` style="--fvc:${esc(m.c)}"` : ''}${drag}>${m.i ? ic(m.i) : t.icon}${dot}${page ? `<span class="fv2-pn">${esc(t.name)}</span>${t.place ? `<span class="fv2-pp">${esc(t.place)}</span>` : ''}` : ''}</button>`;
}
// the row: in the head bar (left empty by sbb_barHtml); 2.489.0 (#4014): without one the sidebar shows them (fv2_sideHtml)
const fv2_pagePinned = () => { try { return isMobile() && tabIds().includes('favs'); } catch { return false; } };
function fv2_barDraw() {
  const on = $('#kbar .fv2bar'); if (!on) return;
  fv2_fetch();
  const html = `${fv2_tiles().map(t => fv2_tileHtml(t)).join('')}<button type="button" class="fv2-more" data-fv2-more hidden aria-haspopup="menu"></button>`;
  if (FV2.last.get(on) === html && on.firstChild) { fv2_fit(); return; }
  FV2.last.set(on, html);
  on.setAttribute('aria-label', tr('Favourites'));
  keepFocus(on, () => { on.innerHTML = html; });
  fv2_fit();
}
// "+N": what does not fit stays hidden in the row and is offered by the button at its end; the bar never takes room from the others
function fv2_fit() {
  const h = $('#kbar .fv2bar'), more = h && $('.fv2-more', h); if (!more) return;
  const kids = $$('.fv2-tile, .fv2-sep', h);
  kids.forEach(x => { x.hidden = false; });
  more.hidden = true; FV2.over = [];
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
  if (fv2_sideOn()) renderSide();  // 2.489.0 (#4014)
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
// the section "Favourites" (renderSide via favSideHtml): the heading with "Only favourites" (lists only), the entries below
// 2.489.0 (#4014): with a head bar (a computer, a tablet held across) the favourites are its row; without one (the phone's narrow
// layout) they stand here again as entries (symbol, name, number / unread) instead of a row of their own over the page's header
function fv2_sideHtml(lists, head) {
  const side = fv2_sideOn(), sv = sv_tilesHtml(), ts = side ? fv2_tiles().filter(t => !t.sep) : [];
  if (side) fv2_fetch();  // the names of the objects (quotations, pages, files) come from the server
  if (sbb_on() || (!favAny() && !ts.length)) return sv ? `<div class="sgroup sg-favs sg-svonly">${sv}</div>` : '';  // 2.156.0 D (#2186): + the view tiles
  const only = favOnly(), lab = tr('Only favourites');  // 2.441.0 (#3592): the tiles moved into the head bar
  const acts = favAny() ? `<button type="button" data-fav-only class="${only ? 'on' : ''}" aria-pressed="${only}" title="${esc(lab)}" aria-label="${esc(lab)}">${ic('filter', 's')}</button>` : '';
  const rows = ts.length && sideOpen('favs') ? `<div class="fv2side" role="group" aria-label="${esc(tr('Favourites'))}">${ts.map(fv2_rowHtml).join('')}</div>` : '';
  return `<div class="sgroup sg-favs">${head('favs', tr('Favourites'), acts)}${sv}${rows}</div>`;
}
// 2.489.0 (#4014): no head bar = the favourites are entries of the sidebar (the page "Favourites" pinned as a tab keeps them there)
const fv2_sideOn = () => { try { return !sbb_on() && !S.me?.kid && !fv2_pagePinned(); } catch { return false; } };
// the number of an entry: open tasks as the sidebar's rows count them, what is unread as a marked number
function fv2_sideN(key) {
  const i = key.indexOf(':'), p = key.slice(0, i), v = key.slice(i + 1), c = counts();
  const plain = n => n && rsy_sideCnt() ? `<span class="c">${n}</span>` : '', unread = n => n ? `<span class="c nunread">${n > 99 ? '99+' : n}</span>` : '';
  if (p === 'l') return plain(c.lists[v]);
  if (p === 'v') return v === 'today' && c.over ? `<span class="c over">${c.today || ''}</span>` : plain(typeof c[v] === 'number' ? c[v] : 0);
  if (p === 'f') return plain(c.filters[v]);
  if (p === 'tag') return plain(c.tags[v]);
  if (p === 'a') { const a = (S.agents || []).find(x => x.id === +v); return unread(a ? (a.waiting || 0) + (a.chat_unread || 0) : 0); }
  if (key === 'm:news') return unread(S.news?.unread ? bellCount() : 0);
  if (key === 'm:team') return unread(S.team?.unread || 0);
  if (key === 'm:agents') return unread((S.agents || []).reduce((n, x) => n + (x.waiting || 0) + (x.chat_unread || 0) + (x.approvals_open || 0), 0));
  return '';
}
function fv2_rowHtml(t) {
  const m = fv2_meta()[t.key] || {}, dot = t.ws && wsOn() ? `<span class="fv2-wsd">${wsp_dot(t.ws)}</span>` : '';
  return `<button type="button" class="srow fv2-row ${t.on ? 'on' : ''}" data-fv2="${esc(t.key)}" ${t.attrs} title="${esc(fv2_hint(t))}"${t.on ? ' aria-current="page"' : ''}${m.c ? ` style="--fvc:${esc(m.c)}"` : ''}><span class="fv2-ri" aria-hidden="true">${m.i ? ic(m.i) : t.icon}</span><span class="n">${esc(t.name)}</span>${dot}${fv2_sideN(t.key)}</button>`;
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
function fv2_set(key, on, to, after) {
  if (key.startsWith('l:')) { favSet(+key.slice(2), on); if (on && to) fv2_move(key, to, after); return; }
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
function fv2_drop(t, x) {
  const key = FV2.drag; FV2.drag = null;
  $$('.fv2bar .fv2-before, .fv2bar .fv2-after, .fv2bar .dragging').forEach(b => b.classList.remove('fv2-before', 'fv2-after', 'dragging'));
  if (key && t && t.dataset.fv2 !== key) fv2_move(key, t.dataset.fv2, fv2_after(t, x));
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
  FV2.drag = t.dataset.fv2; e.dataTransfer.effectAllowed = 'move';
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
  fv2_drop(fv2_target(e.clientX, e.clientY), e.clientX);
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

// ---- touch: hold a tile = its menu (let go) or drag it (move after the hold); hold another row = its menu with the star
document.addEventListener('touchstart', e => {
  const t = e.target.closest?.(FV2_TILES), r = !t && !S.listReorder && e.target.closest?.(FV2_ROWS);
  if (!t && !(r && fv2_rowKey(r))) { FV2.lp = null; return; }
  const p = e.touches[0];
  FV2.lp = {el: t || r, tile: !!t, x: p.clientX, y: p.clientY, active: false};
  FV2.lp.timer = setTimeout(() => {
    const lp = FV2.lp; if (!lp) return;
    lp.active = true; FV2.held = Date.now();
    if (navigator.vibrate) navigator.vibrate(12);
    if (!lp.tile) { FV2.lp = null; fv2_rowMenu(lp.el); return; }
    if (lp.el.closest('.fv2-page, .fv2side')) { FV2.lp = null; fv2_tileMenu(lp.el); return; }  // the page's and the sidebar's rows have only the menu
    FV2.drag = lp.el.dataset.fv2; lp.el.classList.add('dragging');
  }, 420);
}, {passive: true});
document.addEventListener('touchmove', e => {
  const lp = FV2.lp; if (!lp) return;
  const p = e.touches[0];
  if (!lp.active) { if (Math.hypot(p.clientX - lp.x, p.clientY - lp.y) > 8) { clearTimeout(lp.timer); FV2.lp = null; } return; }  // scrolling
  e.preventDefault();
  lp.moved = true; lp.lx = p.clientX; lp.ly = p.clientY;
  fv2_mark(fv2_target(p.clientX, p.clientY), p.clientX);
}, {passive: false});
function fv2_touchEnd(e) {
  const lp = FV2.lp; FV2.lp = null; if (!lp) return;
  clearTimeout(lp.timer); if (!lp.active) return;  // a tap: the tile's own click
  if (e && e.cancelable) e.preventDefault();
  FV2.held = Date.now();
  if (lp.moved) { fv2_drop(fv2_target(lp.lx, lp.ly), lp.lx); return; }
  FV2.drag = null; lp.el.classList.remove('dragging');
  fv2_tileMenu(lp.el);
}
document.addEventListener('touchend', fv2_touchEnd, {passive: false});
document.addEventListener('touchcancel', () => { const lp = FV2.lp; FV2.lp = null; if (lp) { clearTimeout(lp.timer); if (lp.active && lp.tile) fv2_drop(null, 0); } });

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
