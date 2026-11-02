// @ts-check
/* Kalmido web client: the editor of the areas' menus (2.418.0, #3560). One editor for every area (the office's points one
   by one, the parts of Home, Reading, Time, Review and the file store) and the phone's tab bar: the points in the menu with
   a Minus (hide) and a grip (drag; up / down arrows on the grip), below them "Hidden" with a Plus (bring back), then
   "Done". It opens in place of the menu (the panel of a computer via "Customize", a phone's menu via the pen) and for every
   area at once under Settings > Navigation. Hidden = only not in the menu; the arrangement is the person's (user setting
   nav_menus, areas.js nav_write) and the same on every device. An organisation's admins switch points off for its members
   (Settings > Workspaces, nav_orgDraw). Loaded on demand (lazyload.js module navmenu).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

/** @typedef {{key: string, icon: string, name: string, group?: string, hid: boolean, iconHtml?: string}} NavPoint */
// an area of MG_AREAS ([id, icon, name, parts]) or null; any: its parts are tuples of mixed kinds
const nav_area = id => /** @type {any} */ (mg_area(id));
/** @param {EventTarget|null} t @param {string} sel @returns {HTMLElement|null} */
const nav_up = (t, sel) => /** @type {HTMLElement|null} */ (/** @type {HTMLElement} */ (t)?.closest?.(sel) || null);
/** @param {Element|null|undefined} el */
const nav_focus = el => /** @type {HTMLElement|null} */ (el || null)?.focus({preventScroll: true});

// write the person's arrangement of one menu (fn changes {order, hidden, shown}); one undo step
/** @param {string} area @param {(m: {order: string[], hidden: Set<string>, shown: Set<string>}) => void} fn @param {string} label */
function nav_write(area, fn, label) {
  nav_pref(area);
  const o0 = JSON.parse(JSON.stringify(NAV.o)), o1 = JSON.parse(JSON.stringify(NAV.o)), p = nav_pref(area);
  const m = {order: [...p.order], hidden: new Set(p.hidden), shown: new Set(p.shown)}; fn(m);
  o1[area] = {order: m.order, hidden: [...m.hidden], shown: [...m.shown]};
  for (const k of ['order', 'hidden', 'shown']) if (!o1[area][k].length) delete o1[area][k];
  if (!Object.keys(o1[area]).length) delete o1[area];
  const put = o => async () => { const v = JSON.stringify(o); S.settings.nav_menus = v; render(); await api('PATCH', '/api/settings', {nav_menus: v}); return {}; };
  const from = JSON.stringify(o0), to = JSON.stringify(o1); if (from === to) return Promise.resolve();
  return put(o1)().then(() => offerUndo(label, histAdd({label, undo: put(o0), redo: put(o1)})), () => { S.settings.nav_menus = from; render(); });
}
// hide / bring back one point (Minus / Plus of the editor, the menu of a row); a part hidden in the old sidebar settings
// is shown again there too
/** @param {string} area @param {string} key @param {boolean} hide @param {string} name */
function nav_setHid(area, key, hide, name) {
  if (!hide && area !== 'office' && sideHidden('e:' + key)) { const p = sidePref(); api('PATCH', '/api/settings', {sidebar: JSON.stringify({order: p.order, hidden: p.hidden.filter(x => x !== 'e:' + key)})}).then(() => load().then(render), () => {}); }
  return nav_write(area, m => { if (hide) { m.hidden.add(key); m.shown.delete(key); } else { m.hidden.delete(key); m.shown.add(key); } }, hide ? tr('{0} hidden', name) : tr('{0} shown', name));
}
// the menu of a point of a panel (right-click on a computer)
/** @param {Element} b */
function nav_rowMenu(b) {
  const [area, key] = (b.dataset.navk || '').split(':'), name = b.querySelector('.n')?.textContent || key;
  menu(b, [{label: tr('Hide from menu'), icon: 'eyeoff', fn: () => nav_setHid(area, key, true, name)}, {label: tr('Customise'), icon: 'edit', fn: () => nav_edit(area)}]);
}
// the names of the menus (the areas' names; the tab bar)
const nav_title = id => id === 'tabbar' ? tr('Tab bar') : tr(mg_nameKey(nav_area(id)));
// every point of a menu that may show here, in the person's order
/** @param {string} id @returns {NavPoint[]} */
function nav_list(id) {
  if (id === 'office') return ofm_avail().map(i => ({key: i.key, icon: i.icon, name: tr(i.name), group: i.group, hid: nav_hid('office', i.key)}));
  if (id === 'tabbar') {
    const ids = tabIds(), pin = /** @type {any[]} */ (ids.map(tabItem).filter(t => t && !o3a_hidT(t)));
    // what can be pinned with a Plus: the areas, the usual places, the conversations, search and settings (lists, filters
    // and tags: "+ Add tab …" under Settings > Appearance)
    const more = [...tabDefault(), ...tabAreaItems().map(t => t.id), 's:inbox', 's:today', 's:week', 'home', 'cal', 'news', 'team', 'agents', 'wiki', 'sheets', 'habits', 'favs', 'qnotes', 'settings']  // 2.477.0 (#3881): qnotes
      .filter((x, i, a) => a.indexOf(x) === i && !ids.includes(x)).map(x => /** @type {any} */ (tabItem(x))).filter(t => t && !o3a_hidT(t) && !pin.some(p => p.id === t.id));
    return [...pin.map(t => ({key: t.id, icon: t.ico || '', iconHtml: t.icon, name: t.label, hid: false})), ...more.map(t => ({key: t.id, icon: t.ico || '', iconHtml: t.icon, name: t.label, hid: true}))];
  }
  const a = nav_area(id); if (!a) return [];
  const ps = id === 'ablage' ? mg_parts(a).filter(p => !o3a_hid(p[0]) && !nav_orgOff(id, p[0])) : mg_partsShown(a);
  return nav_sort(id, ps, p => p[0]).map(p => ({key: p[0], icon: p[1], name: tr(mg_partName(p[0], p[2])), hid: nav_hid(id, p[0])}));
}
const nav_row = (id, x, i, n) => `<li class="navr" data-k="${esc(x.key)}"><button type="button" class="iconbtn navmin" data-act="nav-hide" aria-label="${esc(tr('Hide {0}', x.name))}" title="${esc(tr('Hide'))}">${ic('minus', 's')}</button>`
  + `<span class="navi">${x.iconHtml || ic(x.icon, 's')}</span><span class="navn">${esc(x.name)}</span>`
  + `<button type="button" class="iconbtn navgrip" data-act="nav-grip" aria-label="${esc(tr('Move {0}', x.name))}" aria-describedby="navhint-${id}" title="${esc(tr('Drag, or use the arrow keys'))}" data-i="${i}" data-n="${n}">${ic('grip', 's')}</button></li>`;
const nav_hidRow = x => `<li class="navr navoff" data-k="${esc(x.key)}"><button type="button" class="iconbtn navplus" data-act="nav-show" aria-label="${esc(tr('Show {0}', x.name))}" title="${esc(tr('Show'))}">${ic('plus', 's')}</button>`
  + `<span class="navi">${x.iconHtml || ic(x.icon, 's')}</span><span class="navn">${esc(x.name)}</span></li>`;
// the editor of one menu; o.page = under Settings > Navigation (no "Done", the menu stays as it is meanwhile)
/** @param {string} id @param {{page?: boolean}} [o] */
function nav_edHtml(id, o = {}) {
  const xs = nav_list(id), on = xs.filter(x => !x.hid), off = xs.filter(x => x.hid);
  const ul = (rows, g) => `<ul class="navl" role="list" data-navg="${g || ''}">${rows.map((x, i) => nav_row(id, x, i, rows.length)).join('')}</ul>`;
  const body = id === 'office' ? OFM_GROUPS.map(g => { const r = on.filter(x => x.group === g[0]); return r.length ? `${g[3] ? '' /* 2.489.0 (#2664): the address book, an entry of its own */ : `<h5 class="navgh">${esc(tr(g[2]))}</h5>`}${ul(r, g[0])}` : ''; }).join('') : ul(on);
  const tip = id === 'tabbar' ? tr('This device fits {0} tabs, the rest goes under “More”.', tabMax()) : tr('Hidden points stay where they are: the search still finds them, nothing is deleted.');
  const head = o.page ? '' : `<div class="navedh"><b>${esc(tr('Edit menu'))}</b><span class="muted">${esc(nav_title(id))}</span><span class="spacer"></span><button type="button" class="btn sm pri" data-act="nav-done">${esc(tr('Done'))}</button></div>`;
  return `<div class="naved${isMobile() ? ' navtouch' : ''}" data-naved="${id}" role="group" aria-label="${esc(tr('Edit menu') + ': ' + nav_title(id))}">${head}${on.length ? body : `<p class="muted">${esc(tr('Nothing in the menu'))}</p>`}`
    + `<h5 class="navgh navhh">${esc(tr('Hidden'))}</h5>${off.length ? `<ul class="navl navoffl" role="list">${off.map(nav_hidRow).join('')}</ul>` : `<p class="muted navnone">${esc(tr('Nothing hidden'))}</p>`}`
    + `<p class="muted navhint" id="navhint-${id}">${esc(tip)}</p><button type="button" class="linkbtn" data-act="nav-reset">${esc(tr('Reset to defaults'))}</button></div>`;
}
// the tab bar keeps its order in the same setting (the old one of the device, LS tabbar, until the first change here)
function nav_tabWrite(ids, label) {
  return nav_write('tabbar', m => { m.order = ids.length ? ids : ['none']; m.hidden.clear(); m.shown.clear(); }, label);
}
// a new order of the points in the menu; the hidden ones keep their place behind them
function nav_order(id, keys) {
  if (id === 'tabbar') return nav_tabWrite(keys, tr('Tab bar'));
  const rest = nav_list(id).map(x => x.key).filter(k => !keys.includes(k));
  return nav_write(id, m => { m.order = [...keys, ...rest]; }, tr('Menu order changed'));
}
// the keys in the order shown by an editor (all groups)
/** @param {Element} ed @returns {string[]} */
const nav_keys = ed => [...ed.querySelectorAll('.navl:not(.navoffl) .navr')].map(li => li.dataset.k || '');
// draws an editor again after a change, keeping the focus on the same point / button
/** @param {Element} ed @param {string} k @param {string} sel */
function nav_redraw(ed, k, sel) {
  const id = ed.dataset.naved || '', page = !ed.querySelector('.navedh');
  if (!page) { renderSide(); if (S.route.mod === 'office') renderView(); } else { const tmp = document.createElement('div'); tmp.innerHTML = nav_edHtml(id, {page}); ed.replaceWith(tmp.firstChild); }
  setTimeout(() => {
    const ne = $(`.naved[data-naved="${id}"]`); if (!ne) return;
    const li = k && [...ne.querySelectorAll('.navr')].find(x => x.dataset.k === k);  // keys of the tab bar may hold any character (tag names)
    nav_focus(li && li.querySelector(sel) || ne.querySelector(sel === '.navgrip' ? '.navgrip' : '[data-act="nav-done"], .navr button'));
  }, 0);
}
document.addEventListener('click', e => {
  const b = nav_up(e.target, '.naved [data-act^="nav-"]'); if (!b) return;
  const ed = b.closest('.naved'), id = ed.dataset.naved || '', li = b.closest('.navr'), k = li?.dataset.k || '', name = li ? li.querySelector('.navn')?.textContent || k : '';
  const a = b.dataset.act; if (a === 'nav-grip') return;
  e.preventDefault(); e.stopPropagation();
  if (a === 'nav-done') { nav_edit(id, false); return; }
  if (a === 'nav-reset') {
    const p = id !== 'tabbar' && sidePref();
    const own = x => (nav_area(id)?.[3] || []).some(q => 'e:' + q[0] === x);
    if (p && p.hidden.some(own)) api('PATCH', '/api/settings', {sidebar: JSON.stringify({order: p.order, hidden: p.hidden.filter(x => !own(x))})}).then(() => load().then(render), () => {});
    nav_write(id, m => { m.order = []; m.hidden.clear(); m.shown.clear(); }, tr('Reset')).then(() => nav_redraw(ed, '', '.navgrip'));
    if (id === 'tabbar') LS.set('tabbar', null);
    return;
  }
  const after = () => nav_redraw(ed, k, a === 'nav-hide' ? '.navplus' : '.navmin');
  if (id === 'tabbar') { const ks = nav_keys(ed); nav_tabWrite(a === 'nav-hide' ? ks.filter(x => x !== k) : [...ks, k], a === 'nav-hide' ? tr('{0} hidden', name) : tr('{0} shown', name)).then(after); return; }
  nav_setHid(id, k, a === 'nav-hide', name).then(after);
}, true);
// the grip: up / down arrows move the point inside its group (Home / End to its ends)
document.addEventListener('keydown', e => {
  const g = nav_up(e.target, '.naved .navgrip'); if (!g || e.ctrlKey || e.metaKey) return;
  const li = g.closest('.navr'), ul = li.parentElement, all = [...ul.querySelectorAll('.navr')], i = all.indexOf(li);
  const j = {ArrowUp: i - 1, ArrowDown: i + 1, Home: 0, End: all.length - 1}[e.key];
  if (j === undefined) return;
  e.preventDefault(); e.stopPropagation();
  if (j < 0 || j >= all.length || j === i) return;
  ul.insertBefore(li, j > i ? all[j].nextSibling : all[j]);
  const ed = li.closest('.naved'); nav_order(ed.dataset.naved || '', nav_keys(ed)).then(() => nav_redraw(ed, li.dataset.k || '', '.navgrip'));
}, true);
// drag: the grip (touch and mouse) or a row itself with the mouse; the row moves inside its group while the pointer moves,
// the order is written once on letting go
const NAVD = {li: /** @type {HTMLElement|null} */ (null), id: 0, moved: false};
document.addEventListener('pointerdown', e => {
  const li = nav_up(e.target, '.naved .navl:not(.navoffl) .navr'); if (!li || e.button) return;
  const grip = nav_up(e.target, '.navgrip');
  if (!grip && (e.pointerType !== 'mouse' || nav_up(e.target, 'button'))) return;
  e.preventDefault();
  NAVD.li = li; NAVD.id = e.pointerId; NAVD.moved = false; li.classList.add('navdrag');
  try { li.setPointerCapture(e.pointerId); } catch { /* old browser */ }
}, true);
document.addEventListener('pointermove', e => {
  const li = NAVD.li; if (!li || e.pointerId !== NAVD.id) return;
  e.preventDefault();
  const ul = li.parentElement, over = [...ul.querySelectorAll('.navr')].find(x => { const r = x.getBoundingClientRect(); return x !== li && e.clientY >= r.top && e.clientY <= r.bottom; });
  if (!over) return;
  const r = over.getBoundingClientRect(), before = e.clientY < r.top + r.height / 2;
  const to = before ? over : over.nextSibling; if (to === li || to === li.nextSibling) return;
  ul.insertBefore(li, to); NAVD.moved = true;
}, true);
/** @param {PointerEvent} e */
function nav_drop(e) {
  const li = NAVD.li; if (!li || e.pointerId !== NAVD.id) return;
  NAVD.li = null; li.classList.remove('navdrag');
  if (!NAVD.moved) return;
  const ed = li.closest('.naved'); nav_order(ed.dataset.naved || '', nav_keys(ed)).then(() => nav_redraw(ed, li.dataset.k || '', '.navgrip'));
}
document.addEventListener('pointerup', nav_drop, true);
document.addEventListener('pointercancel', nav_drop, true);
// ---- Settings > Navigation: the editor of every menu at once (each one folds), the tab bar last
const nav_pageIds = () => [...NAV_AREAS.filter(id => mg_on(id) && !o3a_hid(id) && nav_list(id).length > 1), 'tabbar'];
/** @param {Element|null} box */
function nav_pageDraw(box) {
  if (!box) return;
  const open = [...box.querySelectorAll('details.navsec[open]')].map(d => d.dataset.navsec), first = !box.querySelector('details.navsec');
  box.innerHTML = nav_pageIds().map(id => `<details class="navsec" data-navsec="${id}" ${first ? id === 'office' ? 'open' : '' : open.includes(id) ? 'open' : ''}><summary>${ic(id === 'tabbar' ? 'phone' : mg_icon(nav_area(id)), 's')}<span>${esc(nav_title(id))}</span>${ic('chev', 's fcar')}</summary>${nav_edHtml(id, {page: true})}</details>`).join('');
}
// ---- Settings > Workspaces: the points an organisation's members see in its menus (its admins decide; areas.js
// wsa_orgPaneDraw calls it below the areas). Off = not in the menu of any member there, not even under Hidden.
/** @param {string} id @returns {string[][]} */
const nav_orgPoints = id => id === 'office' ? OFM_ITEMS.filter(i => !i.tpl).sort((a, b) => ofr_rank(a) - ofr_rank(b)).map(i => [i.key, i.name]) : (nav_area(id)?.[3] || []).filter(p => !MG_NONAV.has(p[0]) || id === 'ablage').map(p => [p[0], p[2]]);
/** @param {Element} sec @param {any} o */
function nav_orgDraw(sec, o) {
  if (!sec || sec.parentElement?.querySelector('.nav-org')) return;
  const adm = o.role === 'admin', off = new Set(o.nav_off || []), ws = 'org:' + o.id;
  const areas = WSA_ORG.filter(id => NAV_AREAS.includes(id) && !(o.areas_off || []).includes(id) && nav_orgPoints(id).length > 1);
  if (!areas.length) return;
  const box = document.createElement('div'); box.className = 'nav-org';
  box.innerHTML = `<h4>${tr('Menu points in this organisation')}</h4><div class="shint keep">${esc(tr('Switched off, a point is in no member’s menu in this organisation, not even under Hidden; each member arranges the others.') + (adm ? '' : ' ' + tr('Only an admin of the organisation can change this.')))}</div>`
    + areas.map(id => `<details class="navorg"><summary>${esc(tr(/** @type {string} */ (wsa_name(id, ws))))}</summary><div class="wsa-orgrows">${nav_orgPoints(id).map(([k, n]) => `<label class="chkl"><input type="checkbox" data-navorg="${id}:${k}" ${off.has(id + ':' + k) ? '' : 'checked'} ${adm ? '' : 'disabled'}> ${esc(tr(n))}</label>`).join('')}</div></details>`).join('');
  sec.after(box);
  if (!adm) return;
  box.addEventListener('change', async e => {
    const cb = /** @type {HTMLInputElement|null} */ (nav_up(e.target, 'input[data-navorg]')); if (!cb) return;
    e.stopPropagation();
    const k = cb.dataset.navorg, on = cb.checked;
    const put = v => async () => {
      const s = new Set(o.nav_off || []); v ? s.delete(k) : s.add(k);
      const j = await api('PATCH', `/api/orgs/${o.id}`, {nav_off: [...s]});
      o.nav_off = j?.nav_off || [...s];
      const w = wsOrg(o.id); if (w) w.nav_off = o.nav_off;
      const x = /** @type {HTMLInputElement|null} */ ([...box.querySelectorAll('input[data-navorg]')].find(y => y.dataset.navorg === k) || null); if (x) x.checked = v;
      render(); return {};
    };
    try { await put(on)(); } catch { cb.checked = !on; return; }
    const label = `${cb.parentElement?.textContent?.trim() || k} · ${o.name}`;
    offerUndo(on ? tr('{0} on', label) : tr('{0} off', label), histAdd({label, undo: put(!on), redo: put(on)}));
  });
}
