/* Kalmido web client: favourites of every kind as tiles in the sidebar's fixed head (2.57.0, #1798).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md).
   - anything in the sidebar can be a favourite: lists, projects, folders, Plan views, views and areas, filters, tags, people,
     groups, agents; a star in the row's menu (right-click / long press) adds or removes it
   - the favourites are icon tiles (the name as hint, no counts) in ONE order the person arranges (drag, or the tile's menu
     "Move left" / "Move right"); stored in the user setting fav_items (json list of keys), so every device shows the same
   - lists keep their star in fav_lists (favorites.js; pushes, agents and "Only favourites" read it): an "l:<id>" in fav_items
     only holds the place; a starred list missing there goes to the end, an "l:" without a star is left out
   - a favourite the person cannot see now (archived, another workspace, module off, person gone) is left out silently and
     stays stored, so it comes back with its target */
'use strict';

// [icon, name] of the Plan views and the rows of "More"
const FV2_VIEWS = {inbox: ['inbox', N_('Basket')], assigned: ['user', N_('My tasks')], today: ['sun', N_('Today')], tomorrow: ['sunrise', N_('Tomorrow')],
  week: ['week', N_('Next 7 days')], doable: ['zap', N_('Now doable')], pinned: ['pin', N_('Pinned|view')], waiting: ['hourglass', N_('Waiting on someone')],
  stale: ['clock', N_('Lying idle')], byme: ['send', N_('Assigned by me')], all: ['all', N_('All')], done: ['done', N_('Completed')], trash: ['trash', N_('Trash')],
  archived: ['archive', N_('Archived')]};
// [icon, name] of the views and modules (an area of areas.js wins for its id: its row stands for all its parts)
const FV2_MODS = {cal: ['cal', N_('Calendar')], timeline: ['timeline', N_('Timeline')], matrix: ['grid', N_('Matrix')], habits: ['habit', N_('Habits')],
  pomo: ['timer', N_('Focus timer')], time: ['clock', N_('Time tracking')], stats: ['chart', N_('Statistics')], contacts: ['users', N_('Contacts')],
  life: ['home', N_('Home & life')], workload: ['chart', N_('Workload')], office: ['receipt', N_('Office & finance')], wiki: ['book', N_('Knowledge pages')], sheets: ['sheet', N_('Tables')],
  review: ['journal', N_('Review & journal')], family: ['family', N_('Family')], overview: ['pulse', N_('Project status')], agents: ['bot', N_('Agents')],
  notes: ['note', N_('Notes')], news: ['bell', N_('News')], team: ['comment', N_('Messages')]};
const FV2 = {drag: null, held: 0, lp: null};

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
  const g = d.go || ''; let m;
  if ((m = /^(who|grp|f|l)\/(\d+)$/.exec(g))) return {who: 'p:', grp: 'g:', f: 'f:', l: 'l:'}[m[1]] + m[2];
  try {
    if (g.startsWith('tag/')) return 'tag:' + decodeURIComponent(g.slice(4));
    if (g.startsWith('folder/')) return 'folder:' + decodeURIComponent(g.slice(7));
  } catch { return ''; }
  return FV2_VIEWS[g] ? 'v:' + g : FV2_MODS[g] ? 'm:' + g : '';
}
// a tile: {key, name, icon, attrs (what a click does, the same as the row), on}; null = not shown now
function fv2_tile(key, ctx) {
  const k = S.route.key, onTasks = S.route.mod === 'tasks', i = key.indexOf(':'), p = key.slice(0, i), v = key.slice(i + 1);
  const go = (h, on) => ({attrs: `data-go="${esc(h)}"`, on});
  if (p === 'l') {
    const l = listById(+v); if (!l || l.is_inbox || l.archived || !inWs(l)) return null;
    return {key, name: lname(l), icon: listIconHtml(l, {emoji: true}) || ic('list'), ...go(keyToHash('l:' + l.id), onTasks && k === 'l:' + l.id)};
  }
  if (p === 'folder') {
    if (!folderNames().includes(v) || !(wsCur() === 'all' || ctx.lists.some(l => fUnder(l.folder, v)) || sb_folderInWs(v))) return null;
    return {key, name: fDisp(v), icon: `<span class="sic"${lp_folderSty(v)}>${ic('folder')}</span>`, ...go(keyToHash(key), onTasks && k === key)};
  }
  if (p === 'v') {
    const x = FV2_VIEWS[v]; if (!x || (v === 'byme' && !collab()) || (v === 'archived' && !S.lists.some(l => l.archived && inWs(l)))) return null;
    return {key, name: tr(x[1]), icon: ic(x[0]), ...go(v, onTasks && (k === v || (v === 'archived' && S.lists.some(l => l.archived && k === 'l:' + l.id))))};
  }
  if (p === 'm') {
    if (MG_IDS.includes(v)) {
      const a = mg_area(v); if (!mg_on(v)) return null;
      return {key, name: tr(a[2]), icon: ic(a[1]), ...go(mg_target(v), mg_areaOf(S.route.mod) === a)};
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
function fv2_tiles(lists) {
  const ctx = {lists, c: counts(), people: teamPeople()};
  return fv2_keys().map(x => { try { return fv2_tile(x, ctx); } catch { return null; } }).filter(Boolean);
}
// the section "Favourites" (renderSide via favSideHtml): the heading with "Only favourites" (lists only), the tiles below
function fv2_sideHtml(lists, head) {
  const ts = fv2_tiles(lists); if (!ts.length) return '';
  const only = favOnly(), lab = tr('Only favourites');
  const acts = favAny() ? `<button type="button" data-fav-only class="${only ? 'on' : ''}" aria-pressed="${only}" title="${esc(lab)}" aria-label="${esc(lab)}">${ic('filter', 's')}</button>` : '';
  const drag = isMobile() ? '' : ' draggable="true"';
  return `<div class="sgroup sg-favs">${head('favs', tr('Favourites'), acts)}${sideOpen('favs') ? `<div class="fv2-grid" role="group" aria-label="${esc(tr('Favourites'))}">${ts.map(t =>
    `<button type="button" class="fv2-tile ${t.on ? 'on' : ''}" data-fv2="${esc(t.key)}" ${t.attrs} title="${esc(t.name)}" aria-label="${esc(t.name)}"${t.on ? ' aria-current="page"' : ''}${drag}>${t.icon}</button>`).join('')}</div>` : ''}</div>`;
}

// ---- saving: one PATCH per change, shown at once; a failure loads the server's state again
async function fv2_save(arr) {
  S.settings.fav_items = JSON.stringify(arr);
  render();
  try { await api('PATCH', '/api/settings', {fav_items: arr}); } catch { try { await load(); } catch { /* offline */ } render(); }
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
function fv2_set(key, on) {
  if (key.startsWith('l:')) { favSet(+key.slice(2), on); return; }
  const arr = fv2_keys().filter(x => x !== key);
  if (on) arr.push(key);
  fv2_change(arr, on ? tr('Added to favourites') : tr('Removed from favourites'));
}
// key moves in front of (after = behind) the key `to`
function fv2_move(key, to, after) {
  const arr = fv2_keys().filter(x => x !== key); if (key === to || !arr.includes(to)) return;
  arr.splice(arr.indexOf(to) + (after ? 1 : 0), 0, key);
  fv2_change(arr, tr('Favourites rearranged'));
}
// the entry for a row's menu
const fv2_menuRow = key => !key ? [] : fv2_is(key) ? [{label: tr('Remove from favourites'), icon: 'star', fn: () => fv2_set(key, false)}]
  : [{label: tr('Add to favourites'), icon: 'star', fn: () => fv2_set(key, true)}];
// a tile's menu: open, move (WCAG 2.5.7: arranging without dragging), remove
function fv2_tileMenu(b) {
  const key = b.dataset.fv2, sh = $$('#side .fv2-tile').map(x => x.dataset.fv2), i = sh.indexOf(key); if (i < 0) return;
  const name = b.getAttribute('aria-label') || '';
  menu(b, [{label: name, dis: true, cls: 'mhead'}, '-',
    {label: tr('Open'), icon: 'right', fn: () => b.click()},
    {label: tr('Move left'), icon: 'left', dis: i === 0, fn: () => fv2_move(key, sh[i - 1], false)},
    {label: tr('Move right'), icon: 'right', dis: i === sh.length - 1, fn: () => fv2_move(key, sh[i + 1], true)},
    '-', {label: tr('Remove from favourites'), icon: 'star', fn: () => fv2_set(key, false)}]);
}
// a row without a menu of its own (Plan, views, areas, filters, tags, people, groups, agents): a small one with the star
function fv2_rowMenu(r) {
  const key = fv2_rowKey(r); if (!key) return false;
  if (key.startsWith('tag:')) { tagMenu(r, key.slice(4)); return true; }  // a tag has its menu (render.js), the star is in it
  const name = r.querySelector('.n')?.textContent || r.getAttribute('aria-label') || '';
  menu(r, [...(name ? [{label: name, dis: true, cls: 'mhead'}, '-'] : []), ...fv2_menuRow(key), ...sbp_menuRow(r)]);  // 2.99.0 E (#2187): + pin a person
  return true;
}
const FV2_ROWS = '#side .srow:not([data-list]):not(.reorder):not(.smore):not(.sfavmore):not(.sset)';

// (capture: a tile's menu is the only one; an agent row that opens a chat and a tag keep their own menus with the star in them:
// chatwins.js, render.js tagMenu)
document.addEventListener('contextmenu', e => {
  if (e.shiftKey) return;
  const t = e.target.closest?.('#side .fv2-tile'), r = !t && e.target.closest?.(FV2_ROWS);
  if (!t && !(r && fv2_rowKey(r) && !cw_target(r) && !r.matches('[data-drop^="tag:"]'))) return;
  if (t) e.stopImmediatePropagation();
  if (e.pointerType === 'touch') { e.preventDefault(); return; }  // the long press below is the app's, no browser menu
  if (isTouch() && !t) return;
  e.preventDefault();
  if (t) fv2_tileMenu(t); else fv2_rowMenu(r);
}, true);
// a click right after a long press is not a click
document.addEventListener('click', e => {
  if (Date.now() - FV2.held < 600 && e.target.closest?.('#side .fv2-tile, ' + FV2_ROWS)) { e.preventDefault(); e.stopImmediatePropagation(); }
}, true);

// ---- dragging a tile with the mouse (desktop, Fold): drop on another tile = in front of it / behind it (right half)
const fv2_after = (t, x) => { const r = t.getBoundingClientRect(); return x > r.left + r.width / 2; };
function fv2_mark(t, x) {
  // 2.87.9 (#1965): the mark changes only when the tile or its half changes
  const cls = t && t.dataset.fv2 !== FV2.drag ? (fv2_after(t, x) ? 'fv2-after' : 'fv2-before') : null;
  if (cls && FV2.mk === t && t.classList.contains(cls)) return;
  $$('#side .fv2-tile.fv2-before, #side .fv2-tile.fv2-after').forEach(b => b.classList.remove('fv2-before', 'fv2-after'));
  FV2.mk = cls ? t : null; if (cls) t.classList.add(cls);
}
// the tile under (or in the grid, nearest to) the pointer
function fv2_target(x, y) {
  const el = document.elementFromPoint(x, y), t = el?.closest?.('#side .fv2-tile'); if (t) return t;
  if (!el?.closest?.('#side .fv2-grid')) return null;
  let best = null, bd = 1e9;
  for (const b of $$('#side .fv2-tile')) { const r = b.getBoundingClientRect(), d = Math.hypot(r.left + r.width / 2 - x, r.top + r.height / 2 - y); if (d < bd) { bd = d; best = b; } }
  return best;
}
function fv2_drop(t, x) {
  const key = FV2.drag; FV2.drag = null;
  $$('#side .fv2-tile.fv2-before, #side .fv2-tile.fv2-after, #side .fv2-tile.dragging').forEach(b => b.classList.remove('fv2-before', 'fv2-after', 'dragging'));
  if (key && t && t.dataset.fv2 !== key) fv2_move(key, t.dataset.fv2, fv2_after(t, x));
}
document.addEventListener('dragstart', e => {
  const t = e.target.closest?.('#side .fv2-tile[draggable="true"]'); if (!t) return;
  FV2.drag = t.dataset.fv2; e.dataTransfer.effectAllowed = 'move';
  try { e.dataTransfer.setData('text/plain', 'fav:' + FV2.drag); } catch { /* old browsers */ }
  requestAnimationFrame(() => t.classList.add('dragging'));
});
document.addEventListener('dragover', e => {
  if (!FV2.drag) return;
  const t = fv2_target(e.clientX, e.clientY); fv2_mark(t, e.clientX);
  if (t) e.preventDefault();
});
document.addEventListener('drop', e => {
  if (!FV2.drag) return;
  e.preventDefault(); e.stopImmediatePropagation();
  fv2_drop(fv2_target(e.clientX, e.clientY), e.clientX);
}, true);
document.addEventListener('dragend', () => { if (FV2.drag) fv2_drop(null, 0); });

// ---- touch: hold a tile = its menu (let go) or drag it (move after the hold); hold another row = its menu with the star
document.addEventListener('touchstart', e => {
  const t = e.target.closest?.('#side .fv2-tile'), r = !t && !S.listReorder && e.target.closest?.(FV2_ROWS);
  if (!t && !(r && fv2_rowKey(r))) { FV2.lp = null; return; }
  const p = e.touches[0];
  FV2.lp = {el: t || r, tile: !!t, x: p.clientX, y: p.clientY, active: false};
  FV2.lp.timer = setTimeout(() => {
    const lp = FV2.lp; if (!lp) return;
    lp.active = true; FV2.held = Date.now();
    if (navigator.vibrate) navigator.vibrate(12);
    if (!lp.tile) { FV2.lp = null; fv2_rowMenu(lp.el); return; }
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
