// @ts-check
/* Kalmido web client: swiping a row sideways (2.876.0, #5559), one shared helper for the three swipes on a row: the task row
   (dnd.js: right = completed, it glides out; left = the short menu), the news (collab.js: either side removes the item) and the
   swipe to reply on a message (collab.js: only to the right, the arrow). Before, each had a mechanism of its own; the user sees
   the same gestures, now alike everywhere. Classic script sharing the global scope with the others, loaded at the start before
   collab.js and dnd.js. Leafing (swipenav.js) and the calendar (calgest.js) are gestures of their own and stay outside.
   rsw_attach({at(e), can(dir, el), min(el), max?, go(el, dir), out?(el, dir), look?(el, dx, on), lock?(el, dir), done?(el),
   busy?(), edge?, hold?}):
   - at(e) on touchstart -> the row the finger is on, or null (the caller decides what counts: not a checkbox, a field ...)
   - one rule for all: the finger has to move 10 px, and clearly sideways (more than 1.6 times as far as up / down) before it
     is a swipe; else up / down stays scrolling for the rest of the touch. A start within `edge` px (24) of the screen's edge
     stays the phone's own Back gesture; a finger held still for `hold` ms (500) before it moves belongs to the long press
     (the row menu, the drag), and o.busy() = something else owns the finger now (a drag under way): no swipe.
   - dir: 1 = to the right, -1 = to the left; can(dir, el) false = that side does nothing (the row stays at 0)
   - min(el) = the threshold in px; past it a light vibration (once per crossing) and look(el, dx, true); o.max = a rubber band
     past the threshold (a third of the rest, at most max), without it the row follows the finger
   - let go past the threshold: out(el, dir) true = the row glides out to that side, else it springs back; then go(el, dir).
     Not far enough or a touchcancel (the system took the gesture): it springs back and nothing happens. done(el) once it
     stands again (the caller clears its marks; lock(el, dir) put them on when the swipe began)
   - the click the browser sends right after a swipe opens nothing (the swiped row swallows it for 400 ms)
   - prefers-reduced-motion: no gliding, the row is in place / out at once
   - a live redraw that comes while a finger is on such a row would replace the touched node (the swipe dies on the phone, no
     touchend reaches the document): rsw_busy() is true then (liveparts.js lpHold holds the view), rsw_later(key, fn, box) keeps
     fn (the last one per key) for the moment the finger is up -> true; what was held (also S.viewStale) is drawn after it.
   rsw_back(el) = a row that glided out slides back (the action did not take it away: cancelled, an error). */
'use strict';

const RSW_EDGE = 24, RSW_LOCK = 10, RSW_SIDE = 1.6, RSW_HOLD = 500, RSW_MS = 180, RSW_CLICK = 400;
/** @type {any[]} the attached rows (in order: the first whose at() gives a row takes the finger) */
const RSW_REG = [];
/** @type {Map<any, Function>} what waits for the finger to be up (rsw_later) */
const RSW_Q = new Map();
/** @type {any} the touch under way: {o, el, x, y, t, dx, dir, lock, on} */
let rsw_s = null;
/** @type {{el: HTMLElement|null, t: number}} the row swiped last: its click right after is swallowed */
const RSW_LAST = {el: null, t: 0};
const rsw_still = () => { try { return matchMedia('(prefers-reduced-motion: reduce)').matches; } catch { return false; } };
/** @param {HTMLElement} el @param {string} tf @param {string} [tz] */
function rsw_put(el, tf, tz = 'none') { el.style.transition = tz; el.style.transform = tf; }
/** @param {HTMLElement} el a row that glided out comes back (it stayed: the action was cancelled or failed) */
function rsw_back(el) {
  if (!el?.isConnected) return;
  const ms = rsw_still() ? 0 : RSW_MS;
  el.style.transition = ms ? `transform ${ms}ms, opacity ${ms}ms` : 'none'; el.style.transform = ''; el.style.opacity = '';
  setTimeout(() => { el.style.transition = ''; }, ms + 20);
}
/** @param {any} o */
function rsw_attach(o) { RSW_REG.push(o); }
const rsw_busy = () => !!rsw_s;
/** @param {any} key @param {Function} fn @param {string} [box] -> true = kept for the end of the touch */
function rsw_later(key, fn, box) {
  if (!rsw_s || !rsw_s.el.isConnected || (box && !rsw_s.el.closest(box))) return false;
  RSW_Q.set(key, fn); return true;
}
/** @param {any} e */
function rsw_move(e) {
  const s = rsw_s; if (!s) return;
  const t = e.touches?.[0]; if (!t) return;
  if (e.touches.length !== 1 || s.o.busy?.()) { rsw_end(true); return; }  // a second finger, a drag took the row
  const dx = t.clientX - s.x, dy = t.clientY - s.y;
  if (!s.lock) {
    if (Math.hypot(dx, dy) < RSW_LOCK) return;
    const dir = dx > 0 ? 1 : -1;
    if (Math.abs(dx) <= Math.abs(dy) * RSW_SIDE || Date.now() - s.t > (s.o.hold ?? RSW_HOLD) || !s.o.can(dir, s.el)) { rsw_end(true); return; }  // up / down, a long press, a side that does nothing
    s.lock = true; s.min = Math.max(1, +s.o.min(s.el) || 0);
    s.o.lock?.(s.el, dir);
  }
  if (e.cancelable) e.preventDefault();  // the page does not scroll along
  const dir = dx > 0 ? 1 : -1, a = s.o.can(dir, s.el) ? Math.abs(dx) : 0;
  const m = s.o.max ? Math.min(s.o.max, a < s.min ? a : s.min + (a - s.min) / 3) : a;  // the rubber band past the threshold
  s.dx = dx; s.dir = dir; s.far = a >= s.min;
  rsw_put(s.el, `translateX(${Math.round(m * dir)}px)`);
  if (s.far !== s.on) { s.on = s.far; if (s.on) { try { navigator.vibrate?.(8); } catch { /* not allowed */ } } }
  s.o.look?.(s.el, a ? dx : 0, s.on);
}
/** @param {boolean} cancel the system took the gesture (touchcancel) or a second finger came: spring back, nothing happens */
function rsw_end(cancel) {
  const s = rsw_s; rsw_s = null; document.removeEventListener('touchmove', rsw_move);
  if (!s) return;
  // what was held back comes now the finger is up: after a swipe once the row stands again, after a tap once its click has
  // landed on the row it touched (a redraw at once could swap the row before the click reaches it)
  const later = [...RSW_Q.values()]; RSW_Q.clear();
  if (later.length || S.viewStale) setTimeout(() => { if (rsw_s) { for (const f of later) RSW_Q.set(f, f); return; } for (const f of later) f(); if (S.viewStale && typeof viewSafeRender === 'function') viewSafeRender(); }, s.lock ? RSW_MS + 20 : 300);
  if (!s.lock) return;
  const {el, o, dir} = s, go = !cancel && s.far, out = go && !!o.out?.(el, dir), ms = rsw_still() ? 0 : RSW_MS;
  if (!cancel) { RSW_LAST.el = el; RSW_LAST.t = Date.now(); }
  if (out) {
    rsw_put(el, `translateX(${dir > 0 ? '' : '-'}110%)`, ms ? `transform ${ms}ms ease-in, opacity ${ms}ms ease-in` : 'none'); el.style.opacity = '0';
    setTimeout(() => { el.style.transition = ''; o.done?.(el); }, ms + 20);
  } else {
    rsw_put(el, '', ms ? `transform ${ms}ms ease-out` : 'none');
    setTimeout(() => { if (!el.style.transform) el.style.transition = ''; o.done?.(el); }, ms + 20);
    o.look?.(el, 0, false);
  }
  if (go) o.go(el, dir);
}
document.addEventListener('touchstart', ev => {
  const e = /** @type {any} */ (ev);
  if (rsw_s) rsw_end(true);
  if (e.touches?.length !== 1) return;  // a plain Event("touchstart") without a touch list, two fingers (the zoom)
  const t = e.touches[0];
  for (const o of RSW_REG) {
    const el = o.at(e); if (!el) continue;
    const ed = o.edge ?? RSW_EDGE;
    if (t.clientX < ed || t.clientX > innerWidth - ed) return;  // the phone's own Back gesture
    rsw_s = {o, el, x: t.clientX, y: t.clientY, t: Date.now(), dx: 0, dir: 0, lock: false, on: false, far: false};
    document.addEventListener('touchmove', rsw_move, {passive: false});
    return;
  }
}, {passive: true});
document.addEventListener('touchend', () => rsw_end(false), {passive: true});
document.addEventListener('touchcancel', () => rsw_end(true), {passive: true});
// the click a browser sends after the finger is up opens nothing on the row just swiped
document.addEventListener('click', e => {
  if (!RSW_LAST.el || Date.now() - RSW_LAST.t > RSW_CLICK) return;
  if (RSW_LAST.el.contains(/** @type {Node} */ (e.target))) { e.stopImmediatePropagation(); e.preventDefault(); }
}, true);
