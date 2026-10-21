// @ts-check
/* Kalmido web client: saved views of the sidebar (2.156.0 D, #2186), e.g. "On the road" or "Planning".
   Classic script sharing the global scope with the others; loaded on demand (lazyload.js LD_MODS sideviews): favtiles.js has
   the stand-ins and loads it at the first draw of a person who has views (or opens the tool menu / the settings).
   - a view remembers which groups of the sidebar are open, which folders are closed, which entries it hides and optionally a
     start page; per person in the user settings side_views / side_view (accounts/sideviews.py), the same on every device,
     the active one too
   - its tile sits apart in the favourites' head (a pill with icon + name, accent frame while active); the fixed tile
     "Everything" is the sidebar as before; a second tap on the active tile goes back to "Everything"
   - what a view hides waits under "Others (N)" at the end of the sidebar (folded), nothing is lost
   - folding inside a view is only for now (until the next switch): "Update view" in the menu keeps it */
'use strict';

const SV = {cache: '', views: /** @type {any[]} */ ([]), tmp: /** @type {any} */ (null), held: 0, lp: /** @type {any} */ (null)};
const SV_MAX = 20;
const SV_ICONS = ['panel', 'sun', 'week', 'cal', 'list', 'kanban', 'target', 'flag', 'star', 'zap', 'home', 'brief', 'building', 'laptop',
  'phone', 'car', 'train', 'plane', 'bike', 'run', 'coffee', 'book', 'note', 'bulb', 'rocket', 'moon', 'mountain', 'map', 'compass',
  'money', 'receipt', 'shop', 'family', 'users', 'comment', 'timer', 'sprout', 'heart'];
const SV_MORE_V = ['all', 'done', 'trash', 'archived'];

// ---- reading
function sv_views() {
  const raw = S.settings?.side_views || '[]';
  if (raw !== SV.cache) {
    SV.cache = raw;
    let a = []; try { a = JSON.parse(raw); } catch { a = []; }
    SV.views = Array.isArray(a) ? a.filter(v => v && typeof v.id === 'string') : [];
  }
  return SV.views;
}
// the active view (or null = "Everything") with its state for now (tmp: the open groups / closed folders since the switch)
function sv_cur() {
  const id = S.settings?.side_view || '', v = id ? sv_views().find(x => x.id === id) : null;
  if (!v) { SV.tmp = null; return null; }
  const sig = JSON.stringify(v);
  if (!SV.tmp || SV.tmp.id !== v.id || SV.tmp.sig !== sig) SV.tmp = {id: v.id, sig, open: new Set(v.open || []), fclosed: new Set(v.fclosed || []), more: false};
  return v;
}
const sv_name = v => v ? v.name : tr('Everything');

// ---- the hooks of the sidebar (render.js sideOpen / sideGroupToggle / renderSide, sidebar.js foldClosed / foldSet, basket.js)
function sv_open(g) { return !sv_cur() || g === 'favs' ? null : SV.tmp.open.has(g); }
function sv_toggle(g) {
  if (!sv_cur() || g === 'favs') return false;
  if (SV.tmp.open.has(g)) SV.tmp.open.delete(g); else SV.tmp.open.add(g);
  renderSide();
  return true;
}
function sv_fold(p) { return sv_cur() ? SV.tmp.fclosed.has(p) : null; }
function sv_foldSet(p, closed) {
  if (!sv_cur()) return false;
  if (closed) SV.tmp.fclosed.add(p); else SV.tmp.fclosed.delete(p);
  return true;
}
function sv_setAll(closed) {
  if (!sv_cur()) return false;
  SV.tmp.open = new Set(closed ? [] : SIDE_GROUPS);
  SV.tmp.fclosed = new Set(closed ? folderNames() : []);
  renderSide();
  return true;
}
// the state for now differs from the saved view ("Update view")
function sv_changed() {
  const v = sv_cur(); if (!v) return false;
  const same = (a, b) => a.size === b.size && [...a].every(x => b.has(x));
  return !same(SV.tmp.open, new Set(v.open || [])) || !same(SV.tmp.fclosed, new Set(v.fclosed || []));
}

// the group a key stands in (an entry of a hidden group is not listed twice under "Others")
function sv_groupOf(key) {
  const i = key.indexOf(':'), p = key.slice(0, i), v = key.slice(i + 1);
  if (p === 'v') return SV_MORE_V.includes(v) ? 'more' : 'focus';
  if (p === 'm') return SIDE_VIEW_KEYS.includes(v) ? 'views' : 'areas';
  return {l: 'lists', folder: 'lists', f: 'filters', tag: 'tags', p: 'team', g: 'team', a: 'team'}[p] || '';
}
// after renderSide: the hidden groups and entries go under "Others (N)" at the end
function sv_after() {
  const v = sv_cur(), side = $('#side'); if (!v || !side) return;
  const hide = new Set(v.hide || []), groups = [];
  for (const k of hide) {
    if (!k.startsWith('g:') || k === 'g:favs') continue;
    const el = side.querySelector(':scope > .sgroup.sg-' + k.slice(2)); if (el) groups.push(el);
  }
  for (const el of $$('#side .srow, #side .fhead')) {
    if (el.closest('.sbfix, .sfoot, .sg-svmore') || el.classList.contains('reorder')) continue;
    const k = fv2_rowKey(el); if (!k || !hide.has(k) || hide.has('g:' + sv_groupOf(k))) continue;
    if (el.classList.contains('fhead')) {
      const w = el.parentElement?.classList.contains('fsubw') ? el.parentElement : null;
      if (w) w.remove(); else { const b = el.nextElementSibling; if (b?.classList.contains('fbody')) b.remove(); el.remove(); }
    } else el.remove();
  }
  const ctx = {lists: S.lists.filter(l => !l.is_inbox && !l.archived && inWs(l)), c: counts(), people: teamPeople()};
  const tiles = [...hide].filter(k => !k.startsWith('g:') && !hide.has('g:' + sv_groupOf(k))).map(k => { try { return fv2_tile(k, ctx); } catch { return null; } }).filter(Boolean);
  const n = groups.length + tiles.length; if (!n) return;
  const open = SV.tmp.more, on = tiles.some(t => t.on) || groups.some(g => g.querySelector('.srow.on'));
  const wrap = document.createElement('div');
  wrap.className = 'sgroup sg-svmore';
  wrap.innerHTML = `<div class="shead sgh ${open ? '' : 'closed'} ${on && !open ? 'sgon' : ''}"><button class="sgt" data-sv="more" aria-expanded="${open}">${ic('chev', 's fcar')}<span>${esc(tr('Others ({0})', n))}</span></button></div>`
    + `<div class="svm-body"${open ? '' : ' hidden'}>${tiles.map(t => `<button type="button" class="srow svm ${t.on ? 'on' : ''}" ${t.attrs}>${t.key.startsWith('l:') ? `<span class="sic" aria-hidden="true">${t.icon}</span>` : t.icon}<span class="n">${esc(t.name)}</span></button>`).join('')}</div>`;
  const body = /** @type {HTMLElement} */ (wrap.querySelector('.svm-body'));
  for (const g of groups) body.appendChild(g);
  side.insertBefore(wrap, side.querySelector(':scope > .sfoot'));
}

// ---- the tiles (favtiles.js fv2_sideHtml): "Everything" + one per view, apart from the favourites
function sv_tilesHtml() {
  const vs = sv_views(); if (!vs.length) return '';
  const act = sv_cur()?.id || '';
  const tile = (id, name, icon) => `<button type="button" class="sv-tile ${act === id ? 'on' : ''}" data-sv="tile" data-svid="${esc(id)}" aria-pressed="${act === id}" title="${esc(tr('View: {0}', name))}">${ic(icon, 's')}<span class="svt-n">${esc(name)}</span></button>`;
  return `<div class="sv-row" role="group" aria-label="${esc(tr('Sidebar views'))}">${tile('', tr('Everything'), 'all')}${vs.map(v => tile(v.id, v.name, SV_ICONS.includes(v.icon) ? v.icon : 'panel')).join('')}</div>`;
}

// ---- saving: one PATCH per change, shown at once; a failure loads the server's state again
async function sv_put(vals) {
  Object.assign(S.settings, Object.fromEntries(Object.entries(vals).map(([k, x]) => [k, typeof x === 'string' ? x : JSON.stringify(x)])));
  renderSide(); sv_setFill();
  try { await api('PATCH', '/api/settings', vals); } catch { toast(tr('Could not save')); try { await load(); } catch { /* offline */ } render(); sv_setFill(); }
}
// switch: id '' = "Everything"; a view with a start page opens it (only when switched here, never on the other devices)
function sv_activate(id, nav = true) {
  const v = sv_views().find(x => x.id === id) || null;
  SV.tmp = null;
  sv_put({side_view: v ? v.id : ''});
  if (nav && v?.start) go(v.start);
}
function sv_saveViews(arr, extra = {}) { return sv_put({side_views: arr, ...extra}); }
function sv_update() {  // "Update view": the open groups / closed folders for now become the view's
  const v = sv_cur(); if (!v) return;
  const nv = {...v, open: SIDE_GROUPS.filter(g => SV.tmp.open.has(g)), fclosed: [...SV.tmp.fclosed]};
  sv_saveViews(sv_views().map(x => x.id === v.id ? nv : x));
  toast(tr('View updated'));
}
function sv_delete(id) {
  const before = sv_views(), was = S.settings.side_view || '', v = before.find(x => x.id === id); if (!v) return;
  const arr = before.filter(x => x.id !== id), act = was === id ? '' : was;
  sv_saveViews(arr, {side_view: act});
  offerUndo(tr('View deleted'), histAdd({label: tr('View deleted'), undo: () => sv_saveViews(before, {side_view: was}), redo: () => sv_saveViews(arr, {side_view: act})}));
}
function sv_move(id, d) {
  const arr = [...sv_views()], i = arr.findIndex(x => x.id === id), j = i + d; if (i < 0 || j < 0 || j >= arr.length) return;
  [arr[i], arr[j]] = [arr[j], arr[i]];
  sv_saveViews(arr);
}

// ---- the entries a view can show or hide, by group (the editor), from the data (a folded group draws no rows)
function sv_entries() {
  const out = [], hid = x => sideHidden(x);
  const lists = S.lists.filter(l => !l.is_inbox && !l.archived && inWs(l));
  const it = (key, name, depth = 0) => ({key, name, depth});
  const per = {
    focus: () => ['inbox', 'assigned', 'today', 'tomorrow', 'week', 'doable', 'pinned', 'waiting', 'stale', 'byme'].filter(k => FV2_VIEWS[k] && (k !== 'byme' || collab()) && !hid('e:' + k)).map(k => it('v:' + k, tr(FV2_VIEWS[k][1]))),
    lists: () => {
      const a = lists.filter(l => !l.folder).map(l => it('l:' + l.id, lname(l)));
      const fold = (f, d) => {
        a.push(it('folder:' + f, fName(f), d));
        lists.filter(l => l.folder === f).forEach(l => a.push(it('l:' + l.id, lname(l), d + 1)));
        folderSubs(f).forEach(sf => fold(sf, d + 1));
      };
      folderNames().filter(f => !fParent(f)).forEach(f => fold(f, 0));
      return a;
    },
    views: () => sideViewEntries().filter(x => !hid('e:' + x[0])).map(x => it('m:' + x[0], tr(x[1]))),
    areas: () => SIDE_AREA_KEYS.map(k => MG_IDS.includes(k) ? (mg_on(k) ? it('m:' + k, tr(/** @type {any} */ (mg_area(k))[2])) : null) : (x => x ? it('m:' + k, tr(x[1])) : null)(sideModEntries().find(x => x[0] === k))).filter(Boolean),
    filters: () => S.filters.map(f => it('f:' + f.id, f.name)),
    tags: () => Object.keys(counts().tags).sort((a, b) => a.localeCompare(b, 'de')).map(t => it('tag:' + t, t)),
    team: () => [...(collab() ? (S.groups || []).filter(gr => myGroup(gr.id)).map(gr => it('g:' + gr.id, gr.name)) : []),
      ...sbp_people().map(p => it('p:' + p.id, p.name)), ...sbp_agents().map(a => it('a:' + a.id, a.name))],
    more: () => SV_MORE_V.filter(k => k !== 'archived' || S.lists.some(l => l.archived && inWs(l))).map(k => it('v:' + k, tr(FV2_VIEWS[k][1])))};
  for (const g of sideGroupOrder()) {
    if (hid('g:' + g) && g !== 'lists') continue;
    let items = []; try { items = per[g] ? per[g]() : []; } catch { items = []; }
    out.push({g, name: tr(SIDE_NAMES[g] || g), items});
  }
  return out;
}
// the routes a view can start on: every entry that opens a page
function sv_starts(ents) {
  const ctx = {lists: S.lists.filter(l => !l.is_inbox && !l.archived && inWs(l)), c: counts(), people: teamPeople()}, out = [];
  for (const g of ents) for (const x of g.items) {
    let t = null; try { t = fv2_tile(x.key, ctx); } catch { t = null; }
    const m = t && /data-go="([^"]*)"/.exec(t.attrs);
    if (m) out.push([m[1].replace(/&amp;/g, '&').replace(/&quot;/g, '"'), x.name]);
  }
  return out;
}

// ---- the editor: "Save as view…" (id null: from the sidebar as it is now) and "Edit view…"
const sv_newId = () => Date.now().toString(36).slice(-6) + Math.random().toString(36).slice(2, 6);
function sv_edit(id = null) {
  const cur = id ? sv_views().find(x => x.id === id) : null;
  if (!cur && sv_views().length >= SV_MAX) { toast(tr('At most {0} views', SV_MAX)); return; }
  const now = sv_cur();
  const d = cur ? {...cur} : {id: sv_newId(), name: '', icon: 'panel', open: SIDE_GROUPS.filter(g => sideOpen(g)), fclosed: folderNames().filter(f => foldClosed(f)), hide: [...(now?.hide || [])], start: ''};
  const ents = sv_entries(), shown = new Set(ents.flatMap(g => ['g:' + g.g, ...g.items.map(x => x.key)])), hide = new Set(d.hide || []), open = new Set(d.open || []);
  const starts = sv_starts(ents);
  if (d.start && !starts.some(s => s[0] === d.start)) starts.unshift([d.start, d.start]);
  const cb = (key, label, cls = '', depth = 0) => `<label class="${cls}"${depth ? ` style="--svd:${depth}"` : ''}><input type="checkbox" data-svk="${esc(key)}" ${hide.has(key) ? '' : 'checked'}><span>${esc(label)}</span></label>`;
  const md = /** @type {any} */ (modal(`<h3 id="svd-t">${esc(cur ? tr('Edit view') : tr('Save as view'))}</h3>
    <div class="row"><label for="svd-name">${tr('Name')}</label><input id="svd-name" maxlength="60" value="${esc(d.name)}" placeholder="${esc(tr('e.g. On the road or Planning'))}" autocomplete="off"></div>
    <div class="row svd-icrow"><span class="svd-lab" id="svd-ic-l">${tr('Symbol')}</span><div class="svd-ic" role="radiogroup" aria-labelledby="svd-ic-l">${SV_ICONS.map(k => `<button type="button" role="radio" class="svd-ico ${d.icon === k ? 'on' : ''}" data-svi="${k}" aria-checked="${d.icon === k}" aria-label="${esc(k)}">${ic(k)}</button>`).join('')}</div></div>
    <div class="row"><label for="svd-start">${tr('Start page')}</label><select id="svd-start"><option value="">${esc(tr('None (stays where you are)'))}</option>${starts.map(([h, n]) => `<option value="${esc(h)}" ${d.start === h ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select></div>
    <h4>${tr('What the view shows')}</h4>
    <div class="shint">${esc(tr('Unticked entries wait under “Others” in the sidebar. Open = the group is unfolded when you switch to the view.'))}</div>
    <div class="svd-list">${ents.map(g => `<div class="svd-g" data-svg="${esc(g.g)}"><div class="svd-gh">${cb('g:' + g.g, g.name, 'svd-gl')}<button type="button" class="btn sm svd-open ${open.has(g.g) ? 'on' : ''}" data-svo="${esc(g.g)}" aria-pressed="${open.has(g.g)}" aria-label="${esc(g.name + ': ' + tr('open|fold'))}">${ic('chev', 's')}<span>${esc(open.has(g.g) ? tr('open|fold') : tr('closed|fold'))}</span></button></div>${g.items.map(x => cb(x.key, x.name, 'svd-i', x.depth)).join('')}</div>`).join('')}</div>
    <div class="foot"><span class="spacer"></span><button type="button" class="btn" data-svd="cancel">${tr('Cancel')}</button><button type="button" class="btn pri" data-svd="save">${tr('Save')}</button></div>`));
  md.classList.add('svdlg'); md.setAttribute('role', 'dialog'); md.setAttribute('aria-labelledby', 'svd-t');
  const groupSync = gEl => { const on = /** @type {HTMLInputElement} */ (gEl.querySelector('.svd-gl input')).checked; gEl.classList.toggle('off', !on); };
  $$('.svd-g', md).forEach(groupSync);
  md.addEventListener('change', e => { const g = /** @type {any} */ (e.target).closest('.svd-g'); if (g) groupSync(g); });
  md.addEventListener('click', e => {
    const t = /** @type {any} */ (e.target), ico = t.closest('[data-svi]'), o = t.closest('[data-svo]'), a = t.closest('[data-svd]');
    if (ico) { d.icon = ico.dataset.svi; $$('.svd-ico', md).forEach(b => { b.classList.toggle('on', b === ico); b.setAttribute('aria-checked', String(b === ico)); }); return; }
    if (o) { const on = !o.classList.contains('on'); o.classList.toggle('on', on); o.setAttribute('aria-pressed', String(on)); o.querySelector('span').textContent = on ? tr('open|fold') : tr('closed|fold'); return; }
    if (!a) return;
    if (a.dataset.svd === 'cancel') { modalClose(md); return; }
    const name = /** @type {HTMLInputElement} */ ($('#svd-name', md)).value.trim();
    if (!name) { toast(tr('Give the view a name')); $('#svd-name', md).focus(); return; }
    // entries the dialog does not list now (another workspace, an archived list) keep their state
    const nh = [...hide].filter(k => !shown.has(k)).concat($$('[data-svk]', md).filter(x => !/** @type {HTMLInputElement} */ (x).checked).map(x => x.dataset.svk));
    const nv = {...d, name, hide: [...new Set(nh)], open: $$('[data-svo]', md).filter(x => x.classList.contains('on')).map(x => x.dataset.svo),
      start: /** @type {HTMLSelectElement} */ ($('#svd-start', md)).value};
    modalClose(md);
    if (cur) { sv_saveViews(sv_views().map(x => x.id === cur.id ? nv : x)); toast(tr('View saved')); return; }
    SV.tmp = null;
    sv_saveViews([...sv_views(), nv], {side_view: nv.id});  // a new view is the active one at once
    toast(tr('View saved'));
  });
  setTimeout(() => $('#svd-name', md)?.focus(), 30);
}

// ---- menus: the tool button in the sidebar's head and a view tile's own menu
function sv_toolMenu(b) {
  const v = sv_cur();
  menu(b, [{label: tr('Sidebar views'), dis: true, cls: 'mhead'}, '-',
    {label: tr('Save as view…'), icon: 'plus', fn: () => sv_edit(null)},
    ...(v ? [{label: tr('Update view “{0}”', v.name), icon: 'check', dis: !sv_changed(), fn: sv_update},
      {label: tr('Edit view “{0}”…', v.name), icon: 'edit', fn: () => sv_edit(v.id)},
      {label: tr('Back to “Everything”'), icon: 'all', fn: () => sv_activate('', false)}] : []),
    '-', {label: tr('Manage views…'), icon: 'gear', fn: () => { closeSide(); settingsModal('sidebar'); setTimeout(() => $('#s-sv-h')?.scrollIntoView({block: 'start'}), 60); }}]);
}
function sv_tileMenu(b) {
  const id = b.dataset.svid, v = sv_views().find(x => x.id === id);
  if (!v) { sv_toolMenu(b); return; }
  const act = sv_cur()?.id === id;
  menu(b, [{label: v.name, dis: true, cls: 'mhead'}, '-',
    act ? {label: tr('Back to “Everything”'), icon: 'all', fn: () => sv_activate('', false)} : {label: tr('Open'), icon: 'right', fn: () => sv_activate(id)},
    ...(act ? [{label: tr('Update view “{0}”', v.name), icon: 'check', dis: !sv_changed(), fn: sv_update}] : []),
    {label: tr('Edit view “{0}”…', v.name), icon: 'edit', fn: () => sv_edit(id)},
    '-', {label: tr('Delete'), icon: 'trash', fn: () => sv_delete(id)}]);
}

// ---- Settings > Appearance > Sidebar (settings.js): the views, each change saved at once
function sv_setHtml() {
  setTimeout(sv_setFill, 0);
  return `<h4 id="s-sv-h">${tr('Sidebar views')}</h4>
    <div class="shint">${esc(tr('A view remembers which groups of the sidebar are open and which entries it shows; what it hides waits under “Others”. Tap its tile to switch, tap it again for “Everything”. The same on all your devices.'))}</div>
    <div class="svset" id="s-sv" role="list"></div>
    <div class="row"><span class="spacer"></span><button type="button" class="btn sm" data-sv="new">${ic('plus', 's')}<span>${tr('New view…')}</span></button></div>`;
}
function sv_setFill() {
  const box = $('#s-sv'); if (!box) return;
  const vs = sv_views(), act = S.settings.side_view || '', n = vs.length;
  box.innerHTML = n ? vs.map((v, i) => `<div class="svrow" role="listitem" data-svid="${esc(v.id)}"><span class="svr-ic" aria-hidden="true">${ic(SV_ICONS.includes(v.icon) ? v.icon : 'panel', 's')}</span><span class="svr-n">${esc(v.name)}${act === v.id ? ` <small class="muted">${tr('active')}</small>` : ''}</span>
      <button type="button" class="iconbtn" data-sv="up" ${i ? '' : 'disabled'} aria-label="${esc(tr('Move up') + ': ' + v.name)}" title="${esc(tr('Move up'))}">${ic('up', 's')}</button>
      <button type="button" class="iconbtn" data-sv="down" ${i < n - 1 ? '' : 'disabled'} aria-label="${esc(tr('Move down') + ': ' + v.name)}" title="${esc(tr('Move down'))}">${ic('down', 's')}</button>
      <button type="button" class="iconbtn" data-sv="edit" aria-label="${esc(tr('Edit') + ': ' + v.name)}" title="${esc(tr('Edit'))}">${ic('edit', 's')}</button>
      <button type="button" class="iconbtn" data-sv="del" aria-label="${esc(tr('Delete') + ': ' + v.name)}" title="${esc(tr('Delete'))}">${ic('trash', 's')}</button></div>`).join('')
    : `<p class="muted">${esc(tr('No views yet.'))}</p>`;
}

// ---- clicks, the tile's menu (right click / long press)
document.addEventListener('click', e => {
  const b = /** @type {any} */ (e.target).closest?.('[data-sv]'); if (!b) return;
  if (Date.now() - SV.held < 600 && b.dataset.sv === 'tile') { e.preventDefault(); e.stopImmediatePropagation(); return; }
  const w = b.dataset.sv, id = b.dataset.svid || b.closest('[data-svid]')?.dataset.svid || '';
  e.preventDefault(); e.stopPropagation();
  if (w === 'tile') sv_activate(id && sv_cur()?.id === id ? '' : id, !!id);  // the active tile again = "Everything"
  else if (w === 'more') { if (sv_cur()) { SV.tmp.more = !SV.tmp.more; renderSide(); } }
  else if (w === 'new') sv_edit(null);
  else if (w === 'edit') sv_edit(id);
  else if (w === 'del') sv_delete(id);
  else if (w === 'up' || w === 'down') sv_move(id, w === 'up' ? -1 : 1);
}, true);
document.addEventListener('contextmenu', e => {
  const t = /** @type {any} */ (e.target).closest?.('#side .sv-tile'); if (!t) return;
  e.preventDefault(); e.stopImmediatePropagation();
  if (/** @type {any} */ (e).pointerType !== 'touch') sv_tileMenu(t);
}, true);
document.addEventListener('touchstart', e => {
  const t = /** @type {any} */ (e.target).closest?.('#side .sv-tile'); if (!t) { SV.lp = null; return; }
  const p = e.touches[0];
  SV.lp = {el: t, x: p.clientX, y: p.clientY, timer: setTimeout(() => { const lp = SV.lp; SV.lp = null; if (!lp) return; SV.held = Date.now(); if (navigator.vibrate) navigator.vibrate(12); sv_tileMenu(lp.el); }, 420)};
}, {passive: true});
document.addEventListener('touchmove', e => { const lp = SV.lp; if (lp && Math.hypot(e.touches[0].clientX - lp.x, e.touches[0].clientY - lp.y) > 8) { clearTimeout(lp.timer); SV.lp = null; } }, {passive: true});
document.addEventListener('touchend', () => { const lp = SV.lp; SV.lp = null; if (lp) clearTimeout(lp.timer); }, {passive: true});
