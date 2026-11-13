/* Kalmido web client: bottom sheets on phones can be dragged taller / shorter and swiped down to close (2.39.1, #1181).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// The sheets: menus / choice sheets / the bell (#pop.sheet), the date and time picker (.dpop.sheet), quick add (.qadd.sheet)
// and the dialogs, which are bottom sheets below 768 px. The grip / head (top 44 px) drags the sheet; in a dialog a swipe in
// the content always scrolls (2.652.0, #5078: before, a pull down in the content scrolled to the top dragged, shrank, snapped
// or closed the sheet, and the snap on release made a scrolled dialog jump back up). 2.1126.0 (#6049): a menu sheet (#pop)
// also follows a pull down in its content once the content stands at its top (like a map app's sheet); a dialog with a
// form keeps the head-only rule. Up = taller (up to almost the full screen), down = the sheet slides down with the finger.
// The finger is followed by transform only: a sheet that may grow gets its tallest height ONCE when the drag starts (moved
// down by the difference, so nothing visible jumps), every move after that is a translateY - no height, no layout per frame
// (before, a pull down shrank the height frame by frame down to 40 %, which stuttered). On release: a quick flick down closes
// it from any height, a flick up opens it full; a slow release past the threshold closes it, otherwise it settles on half or
// full (or springs back). Closing goes through the sheet's normal close path (closePop / dpClose / the dialog's own close with
// its draft guard). Only transform is animated; "reduce motion" settles at once. Horizontal moves are left alone (iOS back swipe).
const SD_SEL = '#pop.sheet, .dpop.sheet, .qadd.sheet, .modal:not(.smodal):not(.authscreen):not(.shopmode):not(.palette):not(.dc-md) > .card';  // not: sign-in, shopping mode, palette
// 2.652.0 (#5072): nor the open document (.dc-md): it is a whole page, a pull down on its preview shrank it to half a window with the list below
const SD = {el: null};
const SD_FLICK = 0.5;  // px/ms down over the last ~100 ms: a flick that closes from any height (2.1126.0, #6049)
const sd_vh = () => (window.visualViewport?.height || innerHeight);
function sd_sheet(t) {
  const el = t?.closest?.(SD_SEL);
  // 2.652.0 (#5078): phone width, or a touch screen where the element is laid out as a sheet (.sheet: the tablet quick add) -
  // the touch switch, not the width (a dialog of 768 px and up is a centred card, no sheet)
  if (!el || !(isMobile() || (el.classList.contains('sheet') && isTouch()))) return null;
  return el;
}
// 2.631.0 (#4993): the height the content needs (measured with height auto, so a stretched sheet does not raise its own ceiling)
function sd_natural(el) {
  const h = el.style.height, m = el.style.maxHeight, tr = el.style.transition, st = el.scrollTop;
  el.style.transition = 'none'; el.style.height = 'auto'; el.style.maxHeight = 'none';
  const n = Math.max(el.scrollHeight, el.getBoundingClientRect().height);
  el.style.height = h; el.style.maxHeight = m; el.style.transition = tr;
  if (el.scrollTop !== st) el.scrollTop = st;  // 2.649.0 (#5062): height auto let a scrolled dialog jump to its top, a tap then hit another row
  return n > 0 ? Math.ceil(n) : 1e9;  // no layout (jsdom): no ceiling
}
function sd_resizable(el) { return el.id === 'pop' || el.classList.contains('card'); }
// 2.1126.0 (#6049): the content between the touch and the sheet stands at its top (nothing above to scroll back to)
function sd_atTop(t, el) {
  for (let n = t; n && n !== el.parentElement; n = n.parentElement) if (n.scrollTop > 0) return false;
  return true;
}
function sd_start(t, x, y) {
  if (SD.el) return false;
  const el = sd_sheet(t); if (!el) return false;
  if (t.closest('input,textarea,select,[contenteditable="true"],.qhcs')) return false;  // typing / horizontal chip rows stay theirs
  if (t.closest('[data-bpgrab],[data-bpgrip]')) return false;  // the bell's own handle keeps its own drag (up to the full height, stored)
  if (t.closest('[data-rowd]')) return false;  // 2.456.0 (#3837): the grip of a row drags the row (drag.js rowd_attach), not the sheet
  sd_finish(el);  // 2.1126.0 (#6049): a settle still running (released a moment ago) ends where it was going
  const r = el.getBoundingClientRect(), head = y - r.top <= 44;
  // 2.652.0 (#5078): only the grip / head drags a dialog, the content scrolls; 2.1126.0 (#6049): in a menu sheet a pull down
  // in the content drags too while the content stands at its top (sd_accept decides on the first move: down only)
  const body = !head && el.id === 'pop' && sd_atTop(t, el);
  if (!head && !body) return false;
  const b = getComputedStyle(el).transform;  // the sheet's own transform (quick add on a tablet is centred with translateX)
  Object.assign(SD, {el, t, head, body: !head, base: b && b !== 'none' ? b + ' ' : '', x0: x, y0: y, h0: r.height, top: 0, ty: 0, on: false,
    pts: [[performance.now(), y]], v: 0, sized: false, oh: el.style.height, om: el.style.maxHeight});
  return true;
}
// 2.102.0 (#1998): drag.js asks whether a move starts the drag: 8 px in either direction, then only a vertical move (at the
// head only, 2.652.0 #5078). 2.1126.0 (#6049): a pull in a menu's content decides at 6 px: down = the sheet's, up = a scroll
function sd_accept(dx, dy) {
  const el = SD.el; if (!el) return false;
  const min = SD.body ? 6 : 8;
  if (Math.abs(dy) < min && Math.abs(dx) < min) return null;
  if (Math.abs(dx) > Math.abs(dy) || SD.body && (dy < 0 || !sd_atTop(SD.t, el))) { SD.el = null; return false; }
  SD.on = true;
  el.style.transition = 'none'; el.classList.add('sd-drag');
  // 2.649.0 (#5062): measured once a drag really starts, not on every tap. 2.1126.0 (#6049): the tallest height is set ONCE
  // now and the sheet moved down by the difference (looks the same); from here on only transform follows the finger
  const nat = sd_resizable(el) ? sd_natural(el) : 0, vh = sd_vh();
  const maxH = nat ? Math.max(SD.h0, Math.min(Math.round(vh * 0.94), nat)) : SD.h0;
  if (maxH > SD.h0 + 1) {
    const st = el.scrollTop;
    el.style.maxHeight = 'none'; el.style.height = maxH + 'px'; SD.sized = true;
    if (el.scrollTop !== st) el.scrollTop = st;  // sprung-ok: keeps the scroll where it was when the drag sets the height
  }
  SD.maxH = SD.sized ? maxH : SD.h0; SD.top = SD.maxH - SD.h0;  // translateY that shows the sheet at its height before the drag
  sd_place(el, SD.top);
  return true;
}
// the transform for translateY ty on top of the sheet's own (0: the stylesheet's own again)
const sd_tf = (base, ty) => ty ? `${base}translateY(${Math.round(ty)}px)` : '';
function sd_place(el, ty) { SD.ty = ty; el.style.transform = sd_tf(SD.base, ty); }
function sd_move(x, y) {
  const el = SD.el; if (!el || !SD.on) return false;
  const now = performance.now();
  SD.pts.push([now, y]); while (SD.pts.length > 2 && now - SD.pts[0][0] > 100) SD.pts.shift();
  // up to the tallest height (a little give past it), down without a limit; translateY only (2.1126.0, #6049)
  let ty = SD.top + (y - SD.y0);
  if (ty < 0) ty = -Math.min(24, Math.sqrt(-ty) * 2);
  sd_place(el, Math.round(ty));
  return true;
}
// px/ms over the last ~100 ms (+ = down)
function sd_speed() {
  const p = SD.pts, a = p[0], z = p[p.length - 1], dt = z[0] - a[0];
  if (performance.now() - z[0] > 80) return 0;  // the finger rested before letting go: no flick
  return dt > 0 ? (z[1] - a[1]) / dt : 0;
}
function sd_closer(el) {
  if (el.id === 'pop') return () => closePop();
  if (el.id === 'dpop') return () => dpClose();
  if (el.classList.contains('qadd')) return () => tch_overlaysClose();
  if (el.classList.contains('card')) return () => modalClose(el.parentElement);
  return () => {};
}
function sd_end(cancel) {
  const el = SD.el; SD.el = null; if (!el || !SD.on) return false;
  el.classList.remove('sd-drag');
  const v = sd_speed(), moved = SD.ty - SD.top, vis = SD.maxH - SD.ty;  // vis: the height of the sheet that is on screen
  const vh = sd_vh(), half = Math.round(vh * 0.5), low = Math.min(SD.h0, half), full = SD.maxH;
  // 2.1126.0 (#6049): a flick down closes from any height (before it only shrank a tall sheet); a slow release closes once the
  // sheet is lower than its lowest stop by min(120 px, 30 %)
  const close = !cancel && moved > 12 && (v > SD_FLICK || vis < low - Math.min(120, low * 0.3));
  if (close) {
    const go = SD.maxH + 40, g = sd_geo();
    sd_anim(el, g.base, go, Math.max(120, Math.min(220, (go - SD.ty) / Math.max(1.2, v))), () => {
      an_skipNext(); sd_closer(el)();
      if (el.isConnected && !el.classList.contains('hidden')) sd_settle(el, g, g.h0, false);  // a draft guard kept it open: back in place
      else sd_back(el, g);
    });
    return true;  // drag.js swallows the click that follows the drag
  }
  let to = SD.h0;
  if (!cancel && SD.sized) {  // snap: half or almost full (a quick move up / down picks the side)
    to = v < -0.4 ? full : v > 0.4 ? low : (Math.abs(vis - low) <= Math.abs(vis - full) ? low : full);
    to = Math.max(Math.min(to, full), low);  // 2.161.0: a sheet that opens taller than 94 % never shrinks on a drag up
  }
  sd_settle(el, sd_geo(), to, true);
  return true;
}
// what a settle needs after the drag (SD belongs to the next drag by then)
const sd_geo = () => ({base: SD.base, h0: SD.h0, maxH: SD.maxH, sized: SD.sized, oh: SD.oh, om: SD.om});
// 2.1126.0 (#6049): slide (transform) to translateY ty, then run done; "reduce motion" at once
function sd_anim(el, base, ty, ms, done) {
  const red = drg_reduced();
  el.style.transition = red ? 'none' : `transform ${Math.round(ms)}ms cubic-bezier(.2,.8,.2,1)`;
  el.style.transform = `${base}translateY(${Math.round(ty)}px)`;  // also at 0: openPop clearing it tells fin the sheet opened anew
  const tf = el.style.transform;
  const fin = () => { if (el.style.transform === tf) done(); };  // opened anew meanwhile: leave it
  el._sdD?.cancel();
  if (red) { fin(); return; }
  el._sdD = debounce(fin, ms + 20); el._sdD();  // core.js debounce: one timer, flush / cancel (no hand-made clearTimeout pair)
}
// a settle still running ends now (a new touch on the sheet)
function sd_finish(el) { el._sdD?.flush(); }
// settle the sheet at the visible height h: slide there by transform, then set the height once and drop the transform
function sd_settle(el, g, h, keep) {
  sd_anim(el, g.base, Math.max(0, g.maxH - h), 220, () => {
    el.style.transition = 'none';
    if (Math.abs(h - g.h0) <= 1 || !keep) { el.style.height = g.oh; el.style.maxHeight = g.om; }  // back to what it had
    else if (g.sized) { el.style.maxHeight = 'none'; el.style.height = Math.round(h) + 'px'; }
    el.style.transform = ''; void el.offsetHeight; el.style.transition = '';
  });
}
// closed: the inline height of the drag goes (openPop clears it too)
function sd_back(el, g) { el.style.transition = ''; el.style.transform = ''; el.style.height = g.oh; el.style.maxHeight = g.om; }
// 2.102.0 (#1998): touch (touch events: a pointer would be cancelled as soon as the browser starts to pan the sheet's content;
// a second finger cancels) and mouse / pen (a narrow desktop window, tests; at the head, with pointer capture) through drag.js
drg_attach(document, {
  start: (t, x, y) => sd_start(t, x, y),
  accept: (d, dx, dy) => sd_accept(dx, dy),
  onMove: (d, x, y) => { sd_move(x, y); },
  onDrop: () => { sd_end(false); },
  onTap: () => { sd_end(false); },
  onCancel: () => { sd_end(true); },
});
