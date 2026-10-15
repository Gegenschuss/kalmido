/* Kalmido web client: bottom sheets on phones can be dragged taller / shorter and swiped down to close (2.39.1, #1181).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// The sheets: menus / choice sheets / the bell (#pop.sheet), the date and time picker (.dpop.sheet), quick add (.qadd.sheet)
// and the dialogs, which are bottom sheets below 900 px. Dragging at the grip / head (top 44 px) moves the sheet; in the
// content only a pull down while the content is scrolled to the very top does (scrolling stays scrolling). Up = taller (up to
// almost the full screen), down = shorter (down to 40 %), then it follows the finger; past a threshold or with a quick flick
// it closes through the sheet's normal close path (closePop / dpClose / the dialog's own close with its draft guard).
// On release the height snaps to half or full. Only transform is animated. Horizontal moves are left alone (iOS back swipe).
const SD_SEL = '#pop.sheet, .dpop.sheet, .qadd.sheet, .modal:not(.smodal):not(.authscreen):not(.shopmode):not(.palette) > .card';  // not: sign-in, shopping mode, palette
const SD = {el: null};
const sd_vh = () => (window.visualViewport?.height || innerHeight);
function sd_sheet(t) {
  const el = t?.closest?.(SD_SEL);
  if (!el || !(isMobile() || (el.classList.contains('qadd') && matchMedia('(pointer:coarse)').matches))) return null;  // + the tablet quick-add sheet
  return el;
}
// the content above the target that is scrolled away from its top (then a pull down scrolls, it does not drag)
function sd_scrolled(t, el) {
  for (let n = t; n && n !== el.parentElement; n = n.parentElement) if (n.scrollTop > 0) return true;
  return false;
}
function sd_resizable(el) { return el.id === 'pop' || el.classList.contains('card'); }
function sd_start(t, x, y, touch) {
  if (SD.el) return false;
  const el = sd_sheet(t); if (!el) return false;
  if (t.closest('input,textarea,select,[contenteditable="true"],.qhcs')) return false;  // typing / horizontal chip rows stay theirs
  if (t.closest('[data-bpgrab],[data-bpgrip]')) return false;  // the bell's own handle keeps its own drag (up to the full height, stored)
  const r = el.getBoundingClientRect(), head = y - r.top <= 44;
  if (!head && !touch) return false;  // a mouse drags only at the head (text selection in the content stays)
  const b = getComputedStyle(el).transform;  // the sheet's own transform (quick add on a tablet is centred with translateX)
  Object.assign(SD, {el, head, base: b && b !== 'none' ? b + ' ' : '', x0: x, y0: y, h0: r.height, on: false, ty: 0, lastY: y, lastT: performance.now(), v: 0, sized: false, t});
  return true;
}
function sd_move(x, y) {
  const el = SD.el; if (!el) return false;
  const dx = x - SD.x0, dy = y - SD.y0;
  if (!SD.on) {
    if (Math.abs(dy) < 8 && Math.abs(dx) < 8) return false;
    if (Math.abs(dx) > Math.abs(dy) || (!SD.head && (dy < 0 || sd_scrolled(SD.t, el)))) { SD.el = null; return false; }
    SD.on = true; el.style.transition = 'none'; el.classList.add('sd-drag');
  }
  const now = performance.now(), dt = Math.max(1, now - SD.lastT);
  SD.v = 0.6 * SD.v + 0.4 * ((y - SD.lastY) / dt); SD.lastY = y; SD.lastT = now;
  const vh = sd_vh(), maxH = Math.round(vh * 0.94), minH = Math.min(SD.h0, Math.round(vh * 0.4));
  let h = SD.h0, ty = 0;
  if (sd_resizable(el)) {
    h = Math.max(minH, Math.min(maxH, SD.h0 - dy));
    ty = Math.max(0, dy - (SD.h0 - h));
    if (h !== SD.h0 || SD.sized) { el.style.maxHeight = 'none'; el.style.height = h + 'px'; SD.sized = true; }
  } else ty = Math.max(0, dy);
  SD.ty = ty;
  el.style.transform = ty ? `${SD.base}translateY(${ty}px)` : '';
  return true;
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
  const h = el.getBoundingClientRect().height + SD.ty, flick = SD.v > 0.6 && SD.ty > 12;
  el.style.transition = 'transform .18s ease-out';
  if (!cancel && (SD.ty > Math.min(120, h * 0.3) || flick)) {
    el.style.transform = `${SD.base}translateY(${Math.round(h + 40)}px)`;
    setTimeout(() => {
      an_skipNext(); sd_closer(el)();
      if (el.isConnected) sd_reset(el, !el.classList.contains('hidden'));  // a draft guard kept it open: back in place
    }, 180);
  } else {
    if (SD.sized) {  // snap: half or almost full (a quick move up / down picks the side)
      const vh = sd_vh(), cur = h - SD.ty, half = Math.round(vh * 0.5), full = Math.round(vh * 0.94);
      const to = SD.v < -0.4 ? full : SD.v > 0.4 ? half : (Math.abs(cur - half) <= Math.abs(cur - full) ? half : full);
      el.style.height = Math.max(Math.min(to, full), Math.min(SD.h0, half)) + 'px';
    }
    el.style.transform = '';
  }
  // the drag is not a tap: the click that follows it does not press the button under the finger
  const stop = e => { e.stopPropagation(); e.preventDefault(); };
  document.addEventListener('click', stop, {capture: true, once: true});
  setTimeout(() => document.removeEventListener('click', stop, {capture: true}), 350);
  return true;
}
function sd_reset(el, keepSize) {
  el.style.transition = ''; el.style.transform = '';
  if (!keepSize) { el.style.height = ''; el.style.maxHeight = ''; }
}
// touch: touch events (a pointer would be cancelled as soon as the browser starts to pan the sheet's content)
// 2.39.1 (#1181): a synthetic touch event may come without a touches list
document.addEventListener('touchstart', e => { const t = e.touches || []; if (t.length === 1) sd_start(e.target, t[0].clientX, t[0].clientY, true); else if (SD.el) sd_end(true); }, {passive: true});
document.addEventListener('touchmove', e => { const t = e.touches || []; if (SD.el && t.length === 1 && sd_move(t[0].clientX, t[0].clientY) && e.cancelable) e.preventDefault(); }, {passive: false});
document.addEventListener('touchend', () => sd_end(false), {passive: true});
document.addEventListener('touchcancel', () => sd_end(true), {passive: true});
// mouse / pen (a narrow desktop window, tests): the same at the head, with pointer capture
document.addEventListener('pointerdown', e => {
  if (e.pointerType === 'touch' || e.button !== 0) return;
  if (sd_start(e.target, e.clientX, e.clientY, false)) { try { e.target.setPointerCapture?.(e.pointerId); } catch {} }
});
document.addEventListener('pointermove', e => { if (e.pointerType !== 'touch' && SD.el) sd_move(e.clientX, e.clientY); });
document.addEventListener('pointerup', e => { if (e.pointerType !== 'touch') sd_end(false); });
document.addEventListener('pointercancel', e => { if (e.pointerType !== 'touch') sd_end(true); });
