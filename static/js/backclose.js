/* 2.58.0 (#1757, #1730): on a touch device the Back key / swipe closes the topmost dialog, sheet, menu or the search palette
   instead of changing the route. While an overlay is open one history entry is pushed; Back pops it and closes the overlay,
   closing the overlay another way takes the entry away again. The popstate listener runs first (capture) and keeps the
   other popstate handlers (detail panel, shopping mode) from also reacting to that Back. */
const f8d_bk = {pushed: false, skip: false, queued: false, after: /** @type {Array<() => void>} */ ([]), t: 0};  // after / t: f8d_defer
const f8d_open = () => {
  if ($('.palette:not(.an-out)')) return 'palette';
  if ($('.lightbox')) return 'lightbox';
  const pop = $('#pop');
  if ((pop && !pop.classList.contains('hidden')) || $('.qadd.sheet')) return 'pop';
  // 2.497.0 (#4040): shopping mode has its own history entry (family.js): a second one here stayed behind after closing it (a dead Back)
  if ($('.modal:not(.authscreen):not(.an-out):not(.shopmode)')) return 'modal';
  if ($('.tsheet')) return 'tsheet';
  return '';
};
function f8d_closeTop() {
  const k = f8d_open();
  if (k === 'palette') closePalette();
  else if (k === 'lightbox') $('.lightbox').remove();
  else if (k === 'pop') closePop();
  else if (k === 'modal') modalClose($$('.modal:not(.authscreen):not(.an-out)').pop());
  else if (k === 'tsheet') $('[data-ts="close"]', $('.tsheet'))?.click();
}
function f8d_sync() {
  f8d_bk.queued = false;
  if (f8d_bk.skip) return;  // our own history.back() is still on its way
  const has = !!f8d_open();
  if (has && !f8d_bk.pushed) { history.pushState({f8d: 1}, '', location.href); f8d_bk.pushed = true; }
  else if (!has && f8d_bk.pushed) {
    f8d_bk.pushed = false;
    if (history.state?.f8d) { f8d_bk.skip = true; history.back(); }  // only our own entry; after a route change the current one is not ours
  }
}
const f8d_queue = () => { if (!f8d_bk.queued) { f8d_bk.queued = true; setTimeout(f8d_sync, 0); } };
// #3506 (CI red of 2.560.0 - 2.563.1, p2441_favs_ui): a route change while our own history.back() is still on its way
// (a tile tapped right after its menu closed) was taken back by that Back when it landed: the app stayed on the old page.
// go() waits for the Back (f8d_defer) and then changes the route; at most F8D_WAIT ms, should the Back never arrive.
const F8D_WAIT = 600;
function f8d_flush() { clearTimeout(f8d_bk.t); f8d_bk.t = 0; for (const f of f8d_bk.after.splice(0)) f(); }
function f8d_defer(fn) {
  if (!f8d_bk.skip) return false;
  f8d_bk.after.push(fn); if (!f8d_bk.t) f8d_bk.t = setTimeout(f8d_flush, F8D_WAIT);
  return true;
}
window.addEventListener('popstate', e => {
  if (f8d_bk.skip) { f8d_bk.skip = false; e.stopImmediatePropagation(); f8d_queue(); if (f8d_bk.after.length) setTimeout(f8d_flush, 0); return; }
  if (f8d_bk.pushed && !history.state?.f8d) { f8d_bk.pushed = false; e.stopImmediatePropagation(); f8d_closeTop(); f8d_queue(); }
}, true);
if (typeof isTouch === 'function' && isTouch()) {
  new MutationObserver(f8d_queue).observe(document.body, {childList: true, subtree: true});
  const pop = document.getElementById('pop'); if (pop) new MutationObserver(f8d_queue).observe(pop, {attributes: true, attributeFilter: ['class']});
}
