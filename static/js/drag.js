// @ts-check
/* Kalmido web client: the shared core of dragging (2.102.0, #1998). One way to follow a finger, a mouse or a pen: the
   threshold before a drag starts, the long press on touch, a ghost that slides by transform, auto-scroll at the edge of the
   scroller, Esc cancels, the click after a drag is swallowed. The callers keep what is theirs (where something may go, what
   a drop does): onStart / onMove / onDrop / onCancel / onTap. Sections (secdrag.js) and bottom sheets (sheetdrag.js) use it;
   caldrag, roadmap, timeline, dnd / dragmulti and mindmap are next (docs/ARCHITECTURE.md "Dragging").
   Touch uses touch events, not pointer events: the browser cancels a pointer as soon as it starts to pan the page, a touch
   whose touchmove is prevented stays ours. Mouse and pen use pointer events with pointer capture.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

/**
 * @typedef {Object} DrgOpts
 * @property {(t: HTMLElement, x: number, y: number, kind: string, ev: Event) => any} [start]  drg_attach: the drag's data for
 *   a press on t, or a falsy value (no drag here; the press stays the browser's)
 * @property {boolean} [touch]  drg_attach: follow touches (default true)
 * @property {boolean} [mouse]  drg_attach: follow mouse / pen (default true)
 * @property {boolean} [onTarget]  drg_attach, touch: follow the touch on the element it started on, not on document (a
 *   redraw that takes it out of the page would cut the events off from document; 2.193.0 B, #2219)
 * @property {number} [hold]  drg_attach, touch: long press in ms before a move may drag (default 0 = at once); moving more
 *   than holdMove px before it ends the press (it was a scroll)
 * @property {number} [holdMove]  default 8
 * @property {number} [threshold]  px of movement before onStart (default 6)
 * @property {(d: any, dx: number, dy: number) => (boolean|null)} [accept]  instead of the threshold: true = start, false =
 *   give up (the gesture stays the browser's, onCancel follows), null = not yet
 * @property {boolean} [raf]  onMove, the ghost and auto-scroll at most once per frame
 * @property {HTMLElement|(() => HTMLElement)} [scroll]  auto-scroll this scroller while the pointer is near its top / bottom
 * @property {number} [edge]  the edge zone in px (default 56)
 * @property {number} [step]  px per frame at the very edge (default 14)
 * @property {HTMLElement|(() => HTMLElement)} [scrollX]  auto-scroll this scroller sideways near its left / right edge
 *   (2.193.0 B, #2219; same edge / step, together with scroll)
 * @property {number|(() => number)} [scrollXInset]  px at the scroller's left that are not content (a sticky name column):
 *   the left edge zone starts right of them
 * @property {{el: HTMLElement, cls?: string}} [ghost]  a copy of el follows the pointer (fixed, by transform)
 * @property {(d: any, x: number, y: number) => void} [onStart]
 * @property {(d: any, x: number, y: number, dx: number, dy: number) => void} [onMove]
 * @property {(d: any, x: number, y: number) => void} [onDrop]
 * @property {(d: any) => void} [onCancel]  Esc, a second finger, touchcancel / pointercancel, a gesture given up
 * @property {(d: any) => void} [onTap]  let go before the drag started (a tap or a long press without moving)
 * @property {(d: any, x: number, y: number) => void} [onHold]  2.193.0 C (#2219): the long press (hold) ended with the
 *   finger still down: the ghost shows at once, from now on the page does not scroll under the finger, Esc cancels and
 *   letting go without moving (onTap) brings no click. With onHold, hold may be a function (d) => ms (0 = lifted at once,
 *   e.g. on a grip) and ghost.el a function (d) => the element to copy. onCancel gets (d, up): up = let go (a quick tap).
 * @property {(sc: HTMLElement) => {top: number, bottom: number}} [scrollBox]  2.193.0 C (#2219): the part of the scroller
 *   whose top / bottom edge auto-scrolls (default its box; e.g. without the fixed bars that cover it)
 */

/** @type {any} the running drag (one at a time) */
let drg_cur = null;
const drg_reduced = () => !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

/**
 * Lets presses inside root start drags: touchstart / pointerdown ask opts.start whether this press drags.
 * @param {HTMLElement|Document} root @param {DrgOpts} o
 */
function drg_attach(root, o) {
  if (o.touch !== false) {
    root.addEventListener('touchstart', ev => {
      const e = /** @type {TouchEvent} */ (ev), t = e.touches || [];
      if (t.length !== 1) { if (drg_cur) drg_end(drg_cur, false); return; }  // a second finger: pinch / zoom, not a drag
      const d = o.start && o.start(/** @type {HTMLElement} */ (e.target), t[0].clientX, t[0].clientY, 'touch', e);
      if (!d) return;
      if (drg_cur) drg_end(drg_cur, false);
      drg_open(o, d, 'touch', t[0].clientX, t[0].clientY, o.onTarget ? /** @type {HTMLElement} */ (e.target) : document, false);
    }, {passive: true});
  }
  if (o.mouse !== false) {
    root.addEventListener('pointerdown', ev => {
      const e = /** @type {PointerEvent} */ (ev);
      if (e.pointerType === 'touch' || e.button !== 0) return;
      const d = o.start && o.start(/** @type {HTMLElement} */ (e.target), e.clientX, e.clientY, e.pointerType || 'mouse', e);
      if (!d) return;
      if (drg_cur) drg_end(drg_cur, false);
      const s = drg_open(o, d, 'mouse', e.clientX, e.clientY, document, false);
      s.pid = e.pointerId;
      try { /** @type {HTMLElement} */ (e.target).setPointerCapture?.(e.pointerId); } catch { /* not capturable */ }
    });
  }
}

/**
 * Starts a drag at once (a long press the caller detected, e.g. dnd.js on a section header): the ghost shows now, the
 * touch is followed on el (it keeps getting the events even if a redraw takes it out of the page).
 * @param {HTMLElement} el @param {number} x @param {number} y @param {DrgOpts} o @param {any} [d]
 */
function drg_begin(el, x, y, o, d) {
  if (drg_cur) drg_end(drg_cur, false);
  const s = drg_open(o, d === undefined ? {} : d, 'touch', x, y, el, true);
  if (o.ghost) drg_ghost(s);
  return s;
}

/** Cancels the running drag (onCancel). */
function drg_cancel() { if (drg_cur) drg_end(drg_cur, false); }

/** @param {DrgOpts} o @param {any} d @param {string} kind @param {number} x @param {number} y @param {EventTarget} on @param {boolean} begun */
function drg_open(o, d, kind, x, y, on, begun) {
  const s = {o, d, kind, x0: x, y0: y, x, y, on: false, begun, at: on, pid: null, held: !(o.hold > 0 && kind === 'touch' && !begun),
    timer: 0, ghost: null, raf: 0, sraf: 0, sxraf: 0, l: {}};
  if (!s.held) s.timer = setTimeout(() => { s.held = true; }, o.hold);
  const L = s.l;
  if (o.onHold && kind === 'touch' && !begun) {  // 2.193.0 C (#2219): the end of the hold lifts the drag
    const h = typeof o.hold === 'function' ? /** @type {any} */ (o.hold)(d) : o.hold;
    clearTimeout(s.timer); s.held = !(h > 0);
    if (!s.held) s.timer = setTimeout(() => { s.held = true; drg_lift(s); }, h);
  }
  if (kind === 'touch') {
    L.touchmove = e => { const t = e.touches && e.touches[0]; if (t) drg_move(s, t.clientX, t.clientY, e); };
    L.touchend = e => drg_end(s, true, e);
    L.touchcancel = () => drg_end(s, false);
  } else {
    L.pointermove = e => { if (s.pid == null || e.pointerId === s.pid) drg_move(s, e.clientX, e.clientY, e); };
    L.pointerup = e => { if (s.pid == null || e.pointerId === s.pid) drg_end(s, true, e); };
    L.pointercancel = () => drg_end(s, false);
  }
  for (const k in L) on.addEventListener(k, L[k], k === 'touchmove' ? {passive: false} : undefined);
  L.keydown = e => { if (e.key === 'Escape' && (s.on || s.lifted)) { e.preventDefault(); e.stopPropagation(); drg_end(s, false); } };
  document.addEventListener('keydown', L.keydown, true);
  drg_cur = s;
  if (s.held) drg_lift(s);  // 2.193.0 C (#2219): no hold (a grip): lifted at once
  return s;
}

/** 2.193.0 C (#2219): the hold ended, the finger is still down: the ghost shows, onHold (only drags with onHold). */
function drg_lift(s) {
  if (drg_cur !== s || !s.o.onHold || s.lifted || s.kind !== 'touch' || s.begun) return;
  s.lifted = true;
  if (s.o.ghost && !s.ghost) drg_ghost(s);
  s.o.onHold(s.d, s.x, s.y);
}

/** @param {any} s @param {number} x @param {number} y @param {Event} e */
function drg_move(s, x, y, e) {
  if (drg_cur !== s) return;
  s.x = x; s.y = y;
  const dx = x - s.x0, dy = y - s.y0;
  if (s.lifted && e.cancelable) e.preventDefault();  // 2.193.0 C (#2219): held: the finger is the drag's, also below the threshold
  if (!s.on) {
    if (!s.held) { if (Math.hypot(dx, dy) > (s.o.holdMove || 8)) drg_end(s, false); return; }  // moved during the long press: a scroll
    const ok = s.o.accept ? s.o.accept(s.d, dx, dy) : Math.hypot(dx, dy) >= (s.o.threshold ?? 6) ? true : null;
    if (ok === null) return;
    if (!ok) { drg_end(s, false); return; }
    s.on = true;
    if (s.o.ghost && !s.ghost) drg_ghost(s);
    s.o.onStart?.(s.d, x, y);
    if (drg_cur !== s) return;  // onStart may have ended it
  }
  if (e.cancelable && s.kind === 'touch') e.preventDefault();  // the page does not scroll under a drag
  if (!s.o.raf) drg_frame(s);
  else if (!s.raf) s.raf = requestAnimationFrame(() => { s.raf = 0; if (drg_cur === s) drg_frame(s); });
}

function drg_frame(s) {
  if (s.ghost) s.ghost.style.transform = `translate(${s.x - s.x0}px, ${s.y - s.y0}px)`;
  s.o.onMove?.(s.d, s.x, s.y, s.x - s.x0, s.y - s.y0);
  if (s.o.scroll && !s.sraf) drg_scroll(s);
  if (s.o.scrollX && !s.sxraf) drg_scrollX(s);
}

/** Auto-scroll: near the scroller's top / bottom edge it scrolls every frame (faster deeper in the zone), also while the
 * pointer stays still, until it leaves the zone or the drag ends. */
function drg_scroll(s) {
  s.sraf = 0;
  if (drg_cur !== s || !s.on) return;
  const sc = typeof s.o.scroll === 'function' ? s.o.scroll() : s.o.scroll; if (!sc) return;
  const doc = sc === document.scrollingElement || sc === document.documentElement;
  const r = s.o.scrollBox ? s.o.scrollBox(sc) : doc ? {top: 0, bottom: innerHeight} : sc.getBoundingClientRect(), edge = s.o.edge || 56, step = s.o.step || 14;
  const top = r.top + edge - s.y, bot = s.y - (Math.min(r.bottom, innerHeight) - edge);
  const v = top > 0 ? -Math.ceil(step * Math.min(1, top / edge)) : bot > 0 ? Math.ceil(step * Math.min(1, bot / edge)) : 0;
  if (!v) return;
  const before = sc.scrollTop;
  if (!sc.scrollBy) return;  // 2.193.0: no scrolling API (jsdom): no auto-scroll
  sc.scrollBy(0, v);
  if (sc.scrollTop === before) return;  // at the end: nothing more to scroll
  s.o.onMove?.(s.d, s.x, s.y, s.x - s.x0, s.y - s.y0);  // the content moved under the pointer
  s.sraf = requestAnimationFrame(() => drg_scroll(s));
}

/** Sideways auto-scroll (2.193.0 B, #2219): like drg_scroll at the scroller's left / right edge, every frame while the
 * pointer stays in the zone. It scrolls towards an edge only once the pointer has moved that way (a press that starts
 * inside the zone, e.g. on the first visible day, does not shift the content under the finger). */
function drg_scrollX(s) {
  s.sxraf = 0;
  if (drg_cur !== s || !s.on) return;
  const sc = typeof s.o.scrollX === 'function' ? s.o.scrollX() : s.o.scrollX; if (!sc) return;
  const doc = sc === document.scrollingElement || sc === document.documentElement;
  const r = doc ? {left: 0, right: innerWidth} : sc.getBoundingClientRect(), edge = s.o.edge || 56, step = s.o.step || 14;
  if (!doc && !r.width) return;  // not laid out (hidden)
  const ins = +(typeof s.o.scrollXInset === 'function' ? s.o.scrollXInset() : s.o.scrollXInset) || 0, mv = s.x - s.x0;
  const lft = mv < -16 ? r.left + ins + edge - s.x : 0, rgt = mv > 16 ? s.x - (Math.min(r.right, innerWidth) - edge) : 0;
  const v = lft > 0 ? -Math.ceil(step * Math.min(1, lft / edge)) : rgt > 0 ? Math.ceil(step * Math.min(1, rgt / edge)) : 0;
  if (!v) return;
  const before = sc.scrollLeft;
  if (!sc.scrollBy) return;
  sc.scrollBy(v, 0);
  if (sc.scrollLeft === before) return;  // at the end
  s.o.onMove?.(s.d, s.x, s.y, s.x - s.x0, s.y - s.y0);  // the content moved under the pointer
  s.sxraf = requestAnimationFrame(() => drg_scrollX(s));
}

/** A copy of the ghost's element, fixed where the element is; it slides by transform. */
function drg_ghost(s) {
  const el = /** @type {any} */ (s.o.ghost.el), src = typeof el === 'function' ? el(s.d) : el; if (!src || !src.isConnected) return;
  const r = src.getBoundingClientRect(), g = /** @type {HTMLElement} */ (src.cloneNode(true));
  if (s.o.ghost.cls) g.classList.add(...s.o.ghost.cls.split(' ').filter(Boolean));
  g.removeAttribute('id');
  g.setAttribute('aria-hidden', 'true');
  g.style.cssText = `position:fixed;left:${r.left}px;top:${r.top}px;width:${r.width}px;z-index:95;pointer-events:none`;
  document.body.appendChild(g);
  s.ghost = g;
}

/** @param {any} s @param {boolean} drop @param {Event} [e] */
function drg_end(s, drop, e) {
  if (drg_cur === s) drg_cur = null; else if (s.done) return;
  s.done = true;
  clearTimeout(s.timer);
  if (s.raf) cancelAnimationFrame(s.raf);
  if (s.sraf) cancelAnimationFrame(s.sraf);
  if (s.sxraf) cancelAnimationFrame(s.sxraf);
  for (const k in s.l) (k === 'keydown' ? document : s.at).removeEventListener(k, s.l[k], k === 'keydown' ? true : undefined);
  // a touch the caller started (long press) ends without the click that would follow it
  if ((s.begun || s.lifted) && e && e.cancelable && e.type === 'touchend') e.preventDefault();
  try {
    if (s.on && drop) s.o.onDrop?.(s.d, s.x, s.y);
    else if (!s.on && drop && s.held) s.o.onTap?.(s.d);
    else /** @type {any} */ (s.o.onCancel)?.(s.d, drop);
  } finally {
    s.ghost?.remove();
    if (s.on) drg_noClick();
  }
}

/** The drag is not a tap: the click that follows it does not press the button under the pointer. */
function drg_noClick() {
  const stop = e => { e.stopPropagation(); e.preventDefault(); };
  document.addEventListener('click', stop, {capture: true, once: true});
  setTimeout(() => document.removeEventListener('click', stop, {capture: true}), 350);
}

// ---- 2.331.0 E (#3311): a surface with its own zoom (the timelines, the picture view). Two fingers, Ctrl + wheel (a
// trackpad pinch arrives so in Chrome, Edge, Firefox) and Safari's gesture events zoom only that surface, never the page;
// everywhere else the browser's page zoom stays (#2810). The calendar keeps its own richer gestures (calgest.js).
/**
 * @typedef {Object} PzOpts
 * @property {(t: Element) => Element|null} area  the zoom surface the target is in, or null (the gesture stays the browser's)
 * @property {(a: Element, x: number, y: number, src: string) => any} start  the session's data, or a falsy value (no zoom now)
 * @property {(d: any, k: number, x: number, y: number) => void} move  k = the factor since the start, (x, y) = the point
 *   between the fingers / under the pointer; at most once per frame
 * @property {(d: any) => void} end
 */
/** @type {any} the running zoom (one at a time) */
let pz_cur = null;
const PZ_WHEEL_IDLE = 220;  // ms without a wheel event: the trackpad pinch has ended
/** @param {HTMLElement|Document} root @param {PzOpts} o */
function pz_attach(root, o) {
  const el = t => t instanceof Element ? t : null;
  const draw = rafThrottle(() => { const c = pz_cur; if (c?.o === o) o.move(c.d, c.k, c.x, c.y); });
  const begin = (a, x, y, src) => {
    if (pz_cur) return null;
    const d = o.start(a, x, y, src); if (!d) return null;
    return pz_cur = {o, d, src, k: 1, x, y, d0: 1, tg: [], idle: 0};
  };
  const finish = () => {
    const c = pz_cur; if (c?.o !== o) return;
    draw.flush(); pz_cur = null; clearTimeout(c.idle);
    for (const t of c.tg) { t.removeEventListener('touchmove', tMove); t.removeEventListener('touchend', tEnd); t.removeEventListener('touchcancel', tEnd); }
    o.end(c.d);
  };
  // fingers: followed on their own targets too (a redraw during the zoom takes them out of the page, cutting the events
  // off from root); each event counts once
  const seen = new WeakSet();
  /** @param {any} e */
  function tMove(e) {
    const c = pz_cur; if (c?.o !== o || c.src !== 'touch' || seen.has(e)) return;
    seen.add(e);
    if (e.touches.length < 2) return;
    if (e.cancelable) e.preventDefault();  // no page zoom, no scroll: the fingers zoom the surface
    const [a, b] = e.touches;
    c.k = Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY) / c.d0; c.x = (a.clientX + b.clientX) / 2; c.y = (a.clientY + b.clientY) / 2;
    draw();
  }
  /** @param {any} e */
  function tEnd(e) {
    const c = pz_cur; if (c?.o !== o || c.src !== 'touch' || seen.has(e)) return;
    seen.add(e);
    if (!e.touches || e.touches.length < 2) finish();
  }
  root.addEventListener('touchstart', ev => {
    const e = /** @type {any} */ (ev), t = e.touches;
    if (!t) return;  // a plain Event("touchstart") (tests, synthetic taps)
    if (t.length > 2) { finish(); return; }
    if (t.length !== 2 || pz_cur) return;
    const a = o.area(el(t[0].target)), b = o.area(el(t[1].target));
    if (!a || a !== b) return;
    const c = begin(a, (t[0].clientX + t[1].clientX) / 2, (t[0].clientY + t[1].clientY) / 2, 'touch'); if (!c) return;
    c.d0 = Math.max(1, Math.hypot(t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY));
    c.tg = [...new Set([t[0].target, t[1].target])];
    for (const x of c.tg) { x.addEventListener('touchmove', tMove, {passive: false}); x.addEventListener('touchend', tEnd); x.addEventListener('touchcancel', tEnd); }
  }, {passive: true});
  root.addEventListener('touchmove', tMove, {passive: false});
  root.addEventListener('touchend', tEnd, {passive: true});
  root.addEventListener('touchcancel', tEnd, {passive: true});
  // trackpad / mouse: Ctrl + wheel
  root.addEventListener('wheel', ev => {
    const e = /** @type {WheelEvent} */ (ev);
    if (!e.ctrlKey) return;
    const a = o.area(el(e.target)); if (!a) return;
    e.preventDefault();  // not the browser's page zoom
    if (pz_cur && (pz_cur.o !== o || pz_cur.src !== 'wheel')) return;
    const c = pz_cur || begin(a, e.clientX, e.clientY, 'wheel'); if (!c) return;
    const dy = e.deltaY * (e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 400 : 1);
    c.k *= Math.exp(-Math.max(-25, Math.min(25, dy)) * .01); c.x = e.clientX; c.y = e.clientY;
    draw();
    clearTimeout(c.idle); c.idle = setTimeout(() => { if (pz_cur === c) finish(); }, PZ_WHEEL_IDLE);
  }, {passive: false});
  // Safari (Mac, iPad): a pinch comes as gesture events; on the phone the touch events started the zoom first (the gesture
  // is only stopped then: no page zoom)
  for (const [ev, fn] of /** @type {[string, (e: any) => void][]} */ ([
    ['gesturestart', e => { begin(/** @type {Element} */ (o.area(el(e.target))), e.clientX, e.clientY, 'gesture'); }],
    ['gesturechange', e => { const c = pz_cur; if (c?.o !== o || c.src !== 'gesture') return; c.k = e.scale || 1; draw(); }],
    ['gestureend', () => { if (pz_cur?.src === 'gesture') finish(); }],
  ])) {
    root.addEventListener(ev, e => {
      if (!o.area(el(e.target)) && !(pz_cur?.o === o && ev !== 'gesturestart')) return;
      e.preventDefault();
      fn(e);
    });
  }
}
/** @returns {boolean} a zoom of pz_attach runs (other gestures wait) */
const pz_busy = () => !!pz_cur;
