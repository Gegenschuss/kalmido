// @ts-check
/* Kalmido web client: leafing with a swipe (2.652.0, #5071 #5073), one helper for the full screen of a document (pdfview.js)
   and the image viewer (attachments.js attLightbox). Classic script sharing the global scope with the others; loaded on
   demand (module swipenav in lazyload.js; the module pdf needs it, attLightbox loads it on a touch screen).
   The gesture is the one of the document preview (docs.js DCW, not changed): one finger sideways on the area, the content
   glides with it; far enough (a fifth of the width, at most 90 px) or a quick flick = the next / previous one, else it springs
   back. Nothing there (the end of the list): it follows only a little and springs back. A start within 16 px of the screen's
   edge stays the phone's own Back gesture, a page enlarged by the browser and two fingers (the zoom) are no swipe; up / down
   stays scrolling. The caller decides where it counts: o.area(target) -> the element that glides, or null (e.g. while the
   picture is enlarged: one finger moves the picture then).
   swn_attach(root, {area(target), can(dir), go(dir)}) -> {recent(ms)}: recent() = a swipe ended just now (its tap closes
   nothing). swn_slideIn(el, dir) = the new content glides in from the side it came from. */
'use strict';

const SWN_EDGE = 16;
/** @param {HTMLElement} root @param {{area: (t: any) => HTMLElement|null, can: (dir: number) => boolean, go: (dir: number) => void}} o */
function swn_attach(root, o) {
  /** @type {any} */
  let s = null, end = 0;
  /** @param {HTMLElement} el */
  const loose = el => { el.style.transition = 'transform .2s ease-out'; el.style.transform = ''; setTimeout(() => { if (!el.style.transform) el.style.transition = ''; }, 250); };
  const drop = () => { if (s?.lock) loose(s.el); s = null; };
  root.addEventListener('touchstart', ev => {
    const e = /** @type {any} */ (ev);
    if (!e.touches) return;  // a plain Event("touchstart") (synthetic taps) has no touch list
    if (e.touches.length !== 1 || (typeof pz_busy === 'function' && pz_busy())) { drop(); return; }
    const t = e.touches[0], el = o.area(e.target);
    if (!el || t.clientX < SWN_EDGE || t.clientX > innerWidth - SWN_EDGE || (window.visualViewport?.scale || 1) > 1.05) { s = null; return; }
    s = {el, x0: t.clientX, y0: t.clientY, lx: t.clientX, lt: Date.now(), v: 0, dx: 0, lock: null, edge: null};
  }, {passive: true});
  root.addEventListener('touchmove', ev => {
    const e = /** @type {any} */ (ev);
    if (!s) return;
    if (e.touches.length !== 1 || (typeof pz_busy === 'function' && pz_busy())) { drop(); return; }  // a second finger: the zoom
    const t = e.touches[0], dx = t.clientX - s.x0, dy = t.clientY - s.y0;
    if (!s.lock) {
      if (Math.hypot(dx, dy) < 10) return;
      if (Math.abs(dx) <= Math.abs(dy) * 1.2) { s = null; return; }  // up / down: scrolling
      s.lock = 'x';
      s.edge = {'1': !o.can(1), '-1': !o.can(-1)};
    }
    if (e.cancelable) e.preventDefault();
    s.v = (t.clientX - s.lx) / Math.max(1, Date.now() - s.lt); s.lx = t.clientX; s.lt = Date.now();
    s.dx = dx;
    s.el.style.transition = 'none';
    s.el.style.transform = `translateX(${Math.round(s.edge[dx < 0 ? '1' : '-1'] ? dx * .3 : dx)}px)`;
  }, {passive: false});
  /** @param {Event} e */
  const fin = e => {
    const c = s; s = null;
    if (!c?.lock) return;
    end = Date.now();
    const w = c.el.clientWidth || innerWidth, dir = c.dx < 0 ? 1 : -1;
    const far = Math.abs(c.dx) > Math.min(90, w * .2) || (Math.abs(c.dx) > 30 && Math.abs(c.v) > .35 && Math.sign(c.v) === Math.sign(c.dx));
    if (e.type !== 'touchcancel' && far && !c.edge[String(dir)]) { c.el.style.transition = ''; c.el.style.transform = ''; o.go(dir); }
    else loose(c.el);
  };
  root.addEventListener('touchend', fin, {passive: true});
  root.addEventListener('touchcancel', fin, {passive: true});
  return {recent: (ms = 700) => Date.now() - end < ms};
}
/** @param {HTMLElement|null|undefined} el @param {number} dir */
function swn_slideIn(el, dir) {
  if (!el || typeof el.animate !== 'function' || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  el.animate([{transform: `translateX(${dir > 0 ? 30 : -30}%)`, opacity: .4}, {transform: 'none', opacity: 1}], {duration: 220, easing: 'ease-out'});
}
