// @ts-check
/* Kalmido web client: the split view on a wide screen (2.742.0, #4858). Loaded on demand (lazyload.js) only while the
   split view is on (miniwin.js spl_check / spl_open); off = this file, its stylesheet and the second copy are not loaded.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// Left the app as always (body, narrowed by --splW), right a second copy of the app in an iframe (/?split=1#<route>,
// miniwin.js MW_SPLIT: 2.891.0 (#5358) the normal app with its navigation, any route, writes no UI state of this window). The pane hangs on <html>, outside body: body gets
// "contain: layout" (splitview.css), so the fixed parts of the left app (dialogs, toasts, the buttons in the corner) stay in the
// left half. innerWidth of this window answers the left half while the pane is up, so the app's own layout (detail.js
// layNow / panelMax, the popovers) measures the room it really has. The grip in between: drag (applied on release, the view
// does not jump while dragging), arrow keys (Shift: 4 rem), Home / End, Enter or a double click = half and half; each side
// keeps only its minimum (rule #4830). The width (rem) and the right route are the person's (LOOK_KEYS splW / splR).
const SPL = {el: null, fr: null, px: 0, iw: null, drag: false, dr: ''};
const SPL_MIN_L = 40, SPL_MIN_R = 26;  // rem: the left app (bar, sidebar, list) / the right copy keep at least this
const spl_vw = () => document.documentElement.clientWidth;
const spl_std = () => Math.round(spl_vw() / spl_rem() / 2 * 4) / 4;  // half and half
const spl_max = () => Math.max(SPL_MIN_R, Math.floor((spl_vw() / spl_rem() - SPL_MIN_L) * 4) / 4);
function spl_w() {  // the width of the right half in use (rem)
  const v = +LS.get('splW', 0);
  return Math.max(SPL_MIN_R, Math.min(spl_max(), v > 0 ? v : spl_std()));
}
const spl_route = r => typeof r === 'string' && /^#[\w/:.,%-]{0,39}$/.test(r) ? r : '';  // the same check as the server's (settings.py clean_look_pref)
// innerWidth of this window = the left half while the pane is up (the own property shadows the browser's; put back on unmount)
function spl_iw(on) {
  if (on && !SPL.iw) {
    const own = Object.getOwnPropertyDescriptor(window, 'innerWidth'), d = own || Object.getOwnPropertyDescriptor(Object.getPrototypeOf(window), 'innerWidth');
    if (!d?.get || (own && !own.configurable)) return;
    SPL.iw = {own, d};
    try { Object.defineProperty(window, 'innerWidth', {configurable: true, enumerable: d.enumerable, get() { const w = d.get.call(window); return SPL.el ? Math.max(0, w - SPL.px) : w; }, set: d.set}); } catch { SPL.iw = null; }
  } else if (!on && SPL.iw) {
    try { if (SPL.iw.own) Object.defineProperty(window, 'innerWidth', SPL.iw.own); else Reflect.deleteProperty(window, 'innerWidth'); } catch { /* stays shadowed: it answers the whole width without the pane */ }
    SPL.iw = null;
  }
}
function spl_apply(w) {  // sets the width (rem); the left app lays out anew only when it changed
  const px = Math.round(w * spl_rem());
  document.documentElement.style.setProperty('--splW', px + 'px');
  const g = SPL.el?.querySelector('.splgrip');
  if (g) { g.setAttribute('aria-valuenow', String(w)); g.setAttribute('aria-valuemin', String(SPL_MIN_R)); g.setAttribute('aria-valuemax', String(spl_max())); g.setAttribute('aria-valuetext', tr('{0} rem', String(w))); }
  if (px === SPL.px) return;
  SPL.px = px;
  window.dispatchEvent(new Event('resize'));  // detail.js fitLayout and the others measure the left half
}
function spl_set(w) {  // a width chosen by hand (null = half and half)
  if (w == null) LS.del('splW'); else LS.set('splW', Math.round(Math.max(SPL_MIN_R, Math.min(spl_max(), w)) * 4) / 4);
  spl_apply(spl_w());
}
function spl_mount(route) {
  if (SPL.el) return;
  const r = spl_route(route) || spl_route(LS.get('splR', '')) || '#today';
  const el = document.createElement('div'); el.id = 'splitpane'; el.className = 'splitpane';
  el.innerHTML = `<div class="splgrip" role="separator" tabindex="0" aria-orientation="vertical" aria-label="${esc(tr('Width of the right half'))}" title="${esc(tr('Width of the right half') + ' · ' + tr('drag; double-click = default width'))}"></div>`
    + `<iframe class="splitfr" title="${esc(tr('Right half'))}"></iframe>`;
  SPL.el = el; SPL.fr = el.querySelector('iframe');
  document.documentElement.appendChild(el);  // outside body (see above)
  document.documentElement.classList.add('split-on');
  spl_iw(true);
  spl_grip(el.querySelector('.splgrip'));
  SPL.fr.addEventListener('load', spl_watch);
  SPL.fr.src = '/?split=1' + r;
  spl_apply(spl_w());
}
function spl_unmount() {
  if (!SPL.el) return;
  spl_save.cancel();
  SPL.el.remove(); SPL.el = SPL.fr = null; SPL.px = 0;
  document.documentElement.classList.remove('split-on');
  document.documentElement.style.removeProperty('--splW');
  spl_iw(false);
  window.dispatchEvent(new Event('resize'));
}
// the right route follows the person: the copy's address after each change of it (a short pause, LS.set sends it with the look)
function spl_watch() {
  let w = null; try { w = SPL.fr?.contentWindow; w?.location.hash; } catch { return; /* not the app (another origin) */ }
  if (!w) return;
  w.addEventListener('hashchange', spl_save); spl_save();
}
const spl_save = debounce(() => { let h = ''; try { h = spl_route(SPL.fr?.contentWindow?.location.hash || ''); } catch { return; } if (h && h !== LS.get('splR', '')) LS.set('splR', h); }, 400);  // core.js debounce
// miniwin.js spl_check: the switch / the window's width decide
function spl_sync() {
  if (!spl_on()) { spl_unmount(); return; }
  if (!SPL.el) spl_mount(); else spl_apply(spl_w());
}
// "Open on the right" (miniwin.js spl_item): the route in the right half (a copy already up goes there without loading again)
function spl_show(route) {
  const r = spl_route(route); if (!r || !spl_on()) return;
  LS.set('splR', r);
  if (!SPL.el) { spl_mount(r); return; }
  let w = null; try { w = SPL.fr.contentWindow; } catch { w = null; }
  // 2.760.0 (#4859): a copy still starting holds the iframe's first document (about:blank): its address is no app address
  // (location.replace built "blank#…" from it and the right half stayed empty) - then load the copy with the route instead
  try { if (w && !(w.location.pathname === '/' && /[?&]split=1(?:&|$)/.test(w.location.search))) w = null; } catch { w = null; }
  // replace, no new entry: the iframe shares the tab's history, Back in the left app should not first step through the right one
  try { if (w) { if (w.location.hash !== r) w.location.replace(w.location.pathname + w.location.search + r); w.focus(); return; } } catch { /* reload below */ }  // the copy routes on hashchange (a copy still starting reads it at its start)
  SPL.fr.src = '/?split=1' + r;
}
function spl_grip(g) {
  g.addEventListener('dblclick', () => { spl_set(null); announce(tr('Default width')); });
  g.addEventListener('keydown', e => {
    const v = spl_w(), step = e.shiftKey ? 4 : 1;
    const to = {ArrowLeft: v + step, ArrowRight: v - step, Home: SPL_MIN_R, End: spl_max()}[e.key];
    if (to != null) { e.preventDefault(); e.stopPropagation(); spl_set(to); announce(tr('{0} rem', String(spl_w()))); }
    else if (e.key === 'Enter') { e.preventDefault(); spl_set(null); announce(tr('Default width')); }
  });
  g.addEventListener('pointerdown', e => {
    if (e.button !== 0) return;
    e.preventDefault(); g.setPointerCapture?.(e.pointerId);
    const rem = spl_rem(), vw = spl_vw(), x0 = e.clientX, w0 = spl_w();
    let w = w0, moved = false;
    SPL.drag = true; document.documentElement.classList.add('spl-drag');  // the iframe takes no pointer while the grip moves
    const mv = rafThrottle(x => {
      w = Math.round(Math.max(SPL_MIN_R, Math.min(spl_max(), (vw - x) / rem)) * 4) / 4;
      g.style.transform = `translateX(${Math.round((w0 - w) * rem)}px)`;  // only the grip moves; the halves follow on release
    });
    const mv2 = ev => { if (Math.abs(ev.clientX - x0) > 3) moved = true; if (moved) mv(ev.clientX); };
    const up = () => {
      g.removeEventListener('pointermove', mv2); mv.flush(); g.style.transform = '';
      SPL.drag = false; document.documentElement.classList.remove('spl-drag');
      if (moved) spl_set(w);
    };
    g.addEventListener('pointermove', mv2); g.addEventListener('pointerup', up, {once: true}); g.addEventListener('pointercancel', up, {once: true});
  });
}

// 2.1035.0 (#5802): drag a list, a task, a document or a knowledge page from the left half onto the right half = open it there,
// the same as "Open on the right" (spl_show). While such a drag runs, a field "Open here" lies over the top of the right half,
// in this window above the iframe (the iframe itself never sees this window's drag: its document gets its own events). Only
// the field takes the drop; anywhere else the drag does what it always did (the sidebar's sorting, a task moved, the
// drops into the other half of refs.js below the field). Never over the grip, never on the left. Keyboard: the menu's entry.
function spl_dragRoute(t) {  // the right half's route of what a drag in the left app starts on, else ''
  if (!t?.closest || t.closest('#splitpane')) return '';
  let r;
  if ((r = t.closest('#side .srow[data-list], .pstart .psrow[data-list]')) && +r.dataset.list > 0) return '#l/' + +r.dataset.list;
  if ((r = t.closest('.trow[data-id], .cal .ev[data-id], .week .ev[data-id], .wev[data-id]')) && +r.dataset.id > 0) return '#t/' + +r.dataset.id;
  if ((r = t.closest('.dc-card')?.querySelector('[data-dco]')) && /^\d+$/.test(r.dataset.dco)) return '#docs/' + r.dataset.dco;  // a document card (docs.js, the file store's fold)
  const go = t.closest('#side .sbbt[data-sbbns="wk"]')?.querySelector(':scope > .sbbtn')?.dataset.go || '';  // a knowledge page in the sidebar's tree (wiki.js)
  return /^wiki\/\d+$/.test(go) ? '#' + go : '';
}
function spl_dropOff() {
  SPL.dr = ''; SPL.el?.querySelector('.spldrop')?.remove();
}
// the drop effect the source allows (a list / task drag allows only "move"; a mismatch would refuse the drop)
const spl_eff = ea => { const a = String(ea || '').toLowerCase(); return a === 'all' || a === 'uninitialized' || a.includes('link') ? 'link' : a.includes('copy') ? 'copy' : 'move'; };
window.addEventListener('dragstart', e => {
  spl_dropOff();
  const r = spl_route(spl_dragRoute(e.target)); if (!r || !SPL.el || !spl_on()) return;
  SPL.dr = r;
  // after dragstart: a layout change inside it can end the drag (dnd.js does the same)
  setTimeout(() => {
    if (SPL.dr !== r || !SPL.el || SPL.el.querySelector('.spldrop')) return;
    const z = document.createElement('div'); z.className = 'spldrop';
    z.innerHTML = `<span class="spldropt">${ic('panel')}${esc(tr('Open here'))}</span>`;
    SPL.el.appendChild(z);
  }, 0);
}, true);
// over and onto the field: on the window in the capture phase, before the page's own handlers on the document (sidebar.js
// takes every drop of a dragged list there with stopImmediatePropagation); the field's drop stops here, so they never see it
const spl_atField = e => SPL.dr ? /** @type {Element} */ (e.target)?.closest?.('#splitpane .spldrop') || null : null;
const spl_over = e => {
  if (!SPL.dr) return;
  const z = spl_atField(e);
  if (!z) { SPL.el?.querySelector('.spldrop.on')?.classList.remove('on'); return; }
  e.preventDefault(); e.stopPropagation();
  if (e.dataTransfer) e.dataTransfer.dropEffect = spl_eff(e.dataTransfer.effectAllowed);
  z.classList.add('on');
};
window.addEventListener('dragenter', spl_over, true);
window.addEventListener('dragover', spl_over, true);
window.addEventListener('dragleave', e => { const z = spl_atField(e); if (z && !z.contains(/** @type {Node} */ (e.relatedTarget))) z.classList.remove('on'); }, true);
window.addEventListener('drop', e => {
  const to = spl_atField(e) ? SPL.dr : '';
  spl_dropOff();
  if (!to) return;
  e.preventDefault(); e.stopPropagation();
  spl_show(to);
}, true);
window.addEventListener('dragend', () => spl_dropOff(), true);
