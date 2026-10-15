/* Kalmido web client: dialogs can be moved on the desktop (2.46.2, #1665).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// Every dialog of modal() (dialogs.js: Share, list / folder settings, Settings, askConfirm / askPrompt ...) can be dragged by its
// header (the card's h3, or the header row .lhdr / .shdr around it) with a mouse, to see what lies behind it. transform:
// translate() on the .card; the card stays fully inside the window (also when the window gets smaller); a double click on the
// header puts it back in the middle; a new dialog opens in the middle (nothing is remembered). Buttons and fields in the header
// keep their click. Phones / touch: nothing changes (sheets). The full-screen views (sign-in, shopping mode, command palette)
// are not dialogs of modal() and stay where they are. A drag that ends beside the card does not close the dialog: the backdrop
// closes on a mousedown on itself only, and the drag's mousedown is on the header.
const DW_HEAD = '.card > h3, .card > .lhdr, .card > .shdr, .card > form > h3, .card > form > .lhdr';
const DW_SKIP = 'button, a[href], input, select, textarea, label, summary, [contenteditable="true"], [data-act], [role="button"]';
const dw_desk = () => { try { return !isTouch() && matchMedia('(hover:hover) and (pointer:fine)').matches; } catch { return false; } };
// the dialog's card under a header element, or null (not one of modal()'s, or one of the full-screen ones)
function dw_card(el) {
  const hd = el?.closest?.(DW_HEAD); if (!hd) return null;
  const card = hd.closest('.card'), m = card?.parentElement;
  return m && m.classList.contains('modal') && !m.matches('.authscreen, .shopmode, .palette') && m.firstElementChild === card ? card : null;
}
function dw_set(card, x, y) {
  // clamp: the card's place without the shift (the grid centres it) plus the shift stays inside the window
  const r = card.getBoundingClientRect(), d = card._dw || {x: 0, y: 0}, bx = r.left - d.x, by = r.top - d.y;
  const W = document.documentElement.clientWidth || innerWidth, H = document.documentElement.clientHeight || innerHeight;
  x = Math.min(Math.max(x, -bx), W - (bx + r.width)); y = Math.min(Math.max(y, -by), H - (by + r.height));
  if (!(x > -1e6)) x = 0; if (!(y > -1e6)) y = 0;  // NaN (no layout)
  x = Math.round(x); y = Math.round(y);
  card._dw = {x, y}; card.style.transform = x || y ? `translate(${x}px, ${y}px)` : '';
}
function dw_reset(card) { card._dw = {x: 0, y: 0}; card.style.transform = ''; }
document.addEventListener('pointerdown', e => {
  if (e.button !== 0 || e.pointerType === 'touch' || !dw_desk() || e.target.closest?.(DW_SKIP)) return;
  const card = dw_card(e.target); if (!card) return;
  e.preventDefault();  // no text selection while dragging
  const hd = e.target.closest(DW_HEAD), d = card._dw || {x: 0, y: 0}, sx = e.clientX - d.x, sy = e.clientY - d.y, id = e.pointerId;
  try { hd.setPointerCapture(id); } catch { /* jsdom / gone */ }
  card.classList.add('dwdrag');
  const move = ev => { if (ev.pointerId === id) dw_set(card, ev.clientX - sx, ev.clientY - sy); };
  const end = ev => {
    if (ev.pointerId !== id) return;
    card.classList.remove('dwdrag');
    document.removeEventListener('pointermove', move); document.removeEventListener('pointerup', end); document.removeEventListener('pointercancel', end);
    try { hd.releasePointerCapture(id); } catch { /* released */ }
  };
  document.addEventListener('pointermove', move); document.addEventListener('pointerup', end); document.addEventListener('pointercancel', end);
});
document.addEventListener('dblclick', e => {
  if (!dw_desk() || e.target.closest?.(DW_SKIP)) return;
  const card = dw_card(e.target); if (!card) return;
  e.preventDefault(); window.getSelection?.()?.removeAllRanges?.(); dw_reset(card);
});
// a smaller window keeps every moved dialog inside; a phone width / touch puts it back
let dw_rsT = 0;
window.addEventListener('resize', () => {
  clearTimeout(dw_rsT);
  dw_rsT = setTimeout(() => { for (const card of document.querySelectorAll('.modal > .card')) if (card._dw) { if (dw_desk()) dw_set(card, card._dw.x, card._dw.y); else dw_reset(card); } }, 60);
});
