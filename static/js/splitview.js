// @ts-check
/* Kalmido web client: the split view on a wide screen (2.742.0, #4858). Loaded on demand (lazyload.js) only while the
   split view is on (miniwin.js spl_check / spl_open); off = this file, its stylesheet and the second copy are not loaded.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// Left the app as always (body, narrowed by --splW), right a second copy of the app in an iframe (/?mini=1&split=1#<route>,
// miniwin.js MW_SPLIT: any route, writes no UI state of this window). The pane hangs on <html>, outside body: body gets
// "contain: layout" (splitview.css), so the fixed parts of the left app (dialogs, toasts, the buttons in the corner) stay in the
// left half. innerWidth of this window answers the left half while the pane is up, so the app's own layout (detail.js
// layNow / panelMax, the popovers) measures the room it really has. The grip in between: drag (applied on release, the view
// does not jump while dragging), arrow keys (Shift: 4 rem), Home / End, Enter or a double click = half and half; each side
// keeps only its minimum (rule #4830). The width (rem) and the right route are the person's (LOOK_KEYS splW / splR).
const SPL = {el: null, fr: null, px: 0, iw: null, saveT: 0, drag: false};
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
    const own = Object.getOwnPropertyDescriptor(window, 'innerWidth'), d = own || Object.getOwnPropertyDescriptor(Window.prototype, 'innerWidth');
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
  SPL.fr.src = '/?mini=1&split=1' + r;
  spl_apply(spl_w());
}
function spl_unmount() {
  if (!SPL.el) return;
  clearTimeout(SPL.saveT);
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
  const save = () => { clearTimeout(SPL.saveT); SPL.saveT = setTimeout(() => { let h = ''; try { h = spl_route(SPL.fr?.contentWindow?.location.hash || ''); } catch { return; } if (h && h !== LS.get('splR', '')) LS.set('splR', h); }, 400); };
  w.addEventListener('hashchange', save); save();
}
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
  // replace, no new entry: the iframe shares the tab's history, Back in the left app should not first step through the right one
  try { if (w) { if (w.location.hash !== r) w.location.replace(w.location.pathname + w.location.search + r); w.focus(); return; } } catch { /* reload below */ }  // the copy routes on hashchange (a copy still starting reads it at its start)
  SPL.fr.src = '/?mini=1&split=1' + r;
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
