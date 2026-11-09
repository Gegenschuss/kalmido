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
   swn_attach(root, {area(target), can(dir), go(dir), peek(dir)}) -> {recent(ms), prime()}: recent() = a swipe ended just now
   (its tap closes nothing). swn_slideIn(el, dir) = the new content glides in from the side it came from (callers without a swipe).
   2.727.0 (#5202): leafing like turning a page. While the finger swipes, the neighbour lies beside the area as a placeholder
   (o.peek(dir) -> {img} = its picture / small picture, {} = an empty page; null / no peek = an empty page) and glides along over
   the whole width; let go far enough, the neighbour snaps fully into place and only then o.go(dir) loads it (a promise: the
   placeholder stays until it is done); no glide-in afterwards. prefers-reduced-motion: no snapping animation. prime() = fetch the
   neighbours' pictures ahead (attach does it once; a viewer that changes its picture itself calls it again).
   2.736.0 (#5212): no seam after the snap. o.peek(dir) -> {el} = the neighbour made ready by the caller (drawn as it will stand,
   e.g. pdfview.js: its first page drawn ahead), laid in as it is; o.full = the neighbour fills the content box of the area's
   frame (its offsetParent, e.g. the image viewer: the picture where it will stand, not in the box of the picture shown now), and
   the area glides by that width; the pictures fetched ahead are decoded too, so the one turned to stands there at once.
   2.754.0 (#5213): o.inside = the area is a frame that stays (the task panel #detail, its styles hang on it): its children
   glide, the neighbour lies inside it over the part seen now (its scroll position, its inner size); o.edge = the screen edge
   left to the phone's Back (px, default 16); o.busy() = something else owns the finger now (a long press): no swipe. */
'use strict';

const SWN_EDGE = 16, SWN_GAP = 16;
/** @type {Map<string, HTMLImageElement>} the neighbours' pictures fetched ahead (the browser keeps them; at most a few) */
const SWN_PRE = new Map();
/** @param {string} u */
function swn_pre(u) {
  if (!u || SWN_PRE.has(u)) return;
  const im = new Image(); im.decoding = 'async'; im.src = u; SWN_PRE.set(u, im);
  im.decode?.().catch(() => {});  // 2.736.0 (#5212): decoded ahead, drawn in the first frame after the snap
  if (SWN_PRE.size > 6) SWN_PRE.delete(/** @type {string} */ (SWN_PRE.keys().next().value));
}
/** @param {HTMLElement} el the area -> the box the neighbour takes: o.full = the content box of its frame, else its own box */
function swn_box(el, full, inside) {
  if (inside) return {l: el.scrollLeft, t: el.scrollTop, w: el.clientWidth, h: el.clientHeight};  // 2.754.0 (#5213): the part of the frame seen now
  const f = full ? /** @type {HTMLElement|null} */ (el.offsetParent) : null;
  if (!f) return {l: el.offsetLeft, t: el.offsetTop, w: el.offsetWidth, h: el.offsetHeight};
  const cs = getComputedStyle(f), pl = parseFloat(cs.paddingLeft) || 0, pt = parseFloat(cs.paddingTop) || 0;
  return {l: pl, t: pt, w: f.clientWidth - pl - (parseFloat(cs.paddingRight) || 0), h: f.clientHeight - pt - (parseFloat(cs.paddingBottom) || 0)};
}
/** @param {HTMLElement} root @param {{area: (t: any) => HTMLElement|null, can: (dir: number) => boolean, go: (dir: number) => any, peek?: (dir: number) => ({img?: string, el?: HTMLElement}|null), full?: boolean, inside?: boolean, edge?: number, busy?: () => boolean}} o */
function swn_attach(root, o) {
  /** @type {any} */
  let s = null, end = 0, snap = false;
  const EDGE = o.edge ?? SWN_EDGE;
  /** @param {HTMLElement} el -> what glides: the area, or (o.inside, #5213) its children but the neighbours */
  const parts = el => o.inside ? /** @type {HTMLElement[]} */ ([...el.children]).filter(x => !x.classList.contains('swn-nb')) : [el];
  /** @param {HTMLElement} el @param {string} tf */
  const put = (el, tf) => { el.style.transition = 'none'; el.style.transform = tf; };
  /** @param {any} c the swipe: its area and the placeholders follow the finger (dx) */
  const move = (c, dx) => {
    for (const p of parts(c.el)) put(p, `translateX(${dx}px)`);
    for (const nb of c.nb) put(nb, `translateX(${dx + +nb.dataset.dir * (c.w + SWN_GAP)}px)`);
  };
  /** @param {any} c */
  const clear = c => { for (const nb of c?.nb || []) nb.remove(); if (c) c.nb = []; };
  /** @param {any} c */
  const loose = c => {
    for (const el of parts(c.el)) { el.style.transition = 'transform .2s ease-out'; el.style.transform = ''; setTimeout(() => { if (!el.style.transform) el.style.transition = ''; }, 250); }
    for (const nb of c.nb) { nb.style.transition = 'transform .2s ease-out'; nb.style.transform = `translateX(${+nb.dataset.dir * (c.w + SWN_GAP)}px)`; }
    const gone = c.nb; c.nb = []; setTimeout(() => gone.forEach((/** @type {HTMLElement} */ x) => x.remove()), 250);
  };
  const drop = () => { if (s?.lock) loose(s); s = null; };
  /** @param {HTMLElement} el @param {number} dir the neighbour beside the area, in its place and size */
  const lay = (el, dir) => {
    const p = o.peek ? o.peek(dir) : null, nb = document.createElement('div'), b = swn_box(el, o.full, o.inside);
    nb.className = 'swn-nb'; nb.dataset.dir = String(dir); nb.setAttribute('aria-hidden', 'true');
    nb.style.cssText = `position:absolute;left:${b.l}px;top:${b.t}px;width:${b.w}px;height:${b.h}px;box-sizing:border-box;display:flex;align-items:center;justify-content:center;pointer-events:none;overflow:hidden`;
    if (p?.el) nb.appendChild(p.el);  // 2.736.0 (#5212): made ready by the caller, as it will stand
    else if (p?.img) { const im = document.createElement('img'); im.src = p.img; im.alt = ''; im.style.cssText = 'max-width:100%;max-height:100%;object-fit:contain'; nb.appendChild(im); }
    else { const pg = document.createElement('div'); pg.style.cssText = 'height:min(90%,calc(100vw * 297 / 210));aspect-ratio:210 / 297;max-width:94%;background:var(--bg3,#eee);border-radius:4px'; nb.appendChild(pg); }
    if (o.inside) el.appendChild(nb); else el.after(nb);  // 2.754.0 (#5213): inside the frame, after its own children
    return nb;
  };
  const prime = () => { if (o.peek) for (const d of [1, -1]) if (o.can(d)) swn_pre(o.peek(d)?.img || ''); };
  /** @param {any} c @param {number} dir the neighbour snaps fully into place, then it loads */
  const turn = async (c, dir) => {
    const el = c.el, ps = parts(el), ms = matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : Math.round(Math.max(120, Math.min(260, 260 * (1 - Math.abs(c.dx) / (c.w + SWN_GAP)))));
    snap = true;
    const tz = ms ? `transform ${ms}ms ease-out` : 'none';
    for (const p of ps) { p.style.transition = tz; p.style.transform = `translateX(${-dir * (c.w + SWN_GAP)}px)`; }
    for (const nb of c.nb) { nb.style.transition = tz; nb.style.transform = `translateX(${(+nb.dataset.dir - dir) * (c.w + SWN_GAP)}px)`; }
    try {
      if (ms) await new Promise(ok => { setTimeout(ok, ms + 60, null); const p0 = ps[0] || el; p0.addEventListener('transitionend', ev => { if (ev.target === p0) ok(null); }, {once: true}); });  // a promise settles once: the late timer does nothing
      await o.go(dir);
    } catch { /* the caller shows its own error */ } finally {
      snap = false; clear(c);
      for (const p of ps) if (p.isConnected) { p.style.transition = 'none'; p.style.transform = ''; void p.offsetWidth; p.style.transition = ''; }  // drawn anew in place, or not turned after all
    }
  };
  root.addEventListener('touchstart', ev => {
    const e = /** @type {any} */ (ev);
    if (!e.touches) return;  // a plain Event("touchstart") (synthetic taps) has no touch list
    if (snap) { s = null; return; }  // 2.727.0 (#5202): the last one still snaps in
    if (e.touches.length !== 1 || (typeof pz_busy === 'function' && pz_busy())) { drop(); return; }
    const t = e.touches[0], el = o.area(e.target);
    if (!el || t.clientX < EDGE || t.clientX > innerWidth - EDGE || (window.visualViewport?.scale || 1) > 1.05) { s = null; return; }
    s = {el, x0: t.clientX, y0: t.clientY, lx: t.clientX, lt: Date.now(), v: 0, dx: 0, lock: null, edge: null};
  }, {passive: true});
  root.addEventListener('touchmove', ev => {
    const e = /** @type {any} */ (ev);
    if (!s) return;
    if (e.touches.length !== 1 || (typeof pz_busy === 'function' && pz_busy()) || o.busy?.()) { drop(); return; }  // a second finger: the zoom; 2.754.0 (#5213): a long press
    const t = e.touches[0], dx = t.clientX - s.x0, dy = t.clientY - s.y0;
    if (!s.lock) {
      if (Math.hypot(dx, dy) < 10) return;
      if (Math.abs(dx) <= Math.abs(dy) * 1.2) { s = null; return; }  // up / down: scrolling
      s.lock = 'x';
      s.edge = {'1': !o.can(1), '-1': !o.can(-1)};
      s.w = (o.full || o.inside ? swn_box(s.el, !!o.full, o.inside).w : s.el.offsetWidth) || innerWidth;  // 2.736.0 (#5212): o.full glides by the frame's width
      s.nb = [1, -1].filter(d => !s.edge[String(d)]).map(d => lay(s.el, d));  // 2.727.0 (#5202): the neighbours glide along
    }
    if (e.cancelable) e.preventDefault();
    s.v = (t.clientX - s.lx) / Math.max(1, Date.now() - s.lt); s.lx = t.clientX; s.lt = Date.now();
    s.dx = dx;
    move(s, Math.round(s.edge[dx < 0 ? '1' : '-1'] ? dx * .3 : dx));
  }, {passive: false});
  /** @param {Event} e */
  const fin = e => {
    const c = s; s = null;
    if (!c?.lock) return;
    end = Date.now();
    const w = c.el.clientWidth || innerWidth, dir = c.dx < 0 ? 1 : -1;
    const far = Math.abs(c.dx) > Math.min(90, w * .2) || (Math.abs(c.dx) > 30 && Math.abs(c.v) > .35 && Math.sign(c.v) === Math.sign(c.dx));
    if (e.type !== 'touchcancel' && far && !c.edge[String(dir)]) turn(c, dir);  // 2.727.0 (#5202): snap in, then load
    else loose(c);
  };
  root.addEventListener('touchend', fin, {passive: true});
  root.addEventListener('touchcancel', fin, {passive: true});
  prime();
  return {recent: (ms = 700) => Date.now() - end < ms, prime};
}
/** @param {HTMLElement|null|undefined} el @param {number} dir */
function swn_slideIn(el, dir) {
  if (!el || typeof el.animate !== 'function' || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  el.animate([{transform: `translateX(${dir > 0 ? 30 : -30}%)`, opacity: .4}, {transform: 'none', opacity: 1}], {duration: 220, easing: 'ease-out'});
}
