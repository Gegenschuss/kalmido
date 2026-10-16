/* 2.58.0 (#1757, #1730): on a touch device the Back key / swipe closes the topmost dialog, sheet, menu or the search palette
   instead of changing the route. While an overlay is open one history entry is pushed; Back pops it and closes the overlay,
   closing the overlay another way takes the entry away again. The popstate listener runs first (capture) and keeps the
   other popstate handlers (detail panel, shopping mode) from also reacting to that Back. */
const f8d_bk = {pushed: false, skip: false, queued: false};
const f8d_open = () => {
  if ($('.palette')) return 'palette';
  if ($('.lightbox')) return 'lightbox';
  const pop = $('#pop');
  if ((pop && !pop.classList.contains('hidden')) || $('.qadd.sheet')) return 'pop';
  if ($('.modal:not(.authscreen):not(.an-out)')) return 'modal';
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
window.addEventListener('popstate', e => {
  if (f8d_bk.skip) { f8d_bk.skip = false; e.stopImmediatePropagation(); f8d_queue(); return; }
  if (f8d_bk.pushed && !history.state?.f8d) { f8d_bk.pushed = false; e.stopImmediatePropagation(); f8d_closeTop(); f8d_queue(); }
}, true);
if (typeof isTouch === 'function' && isTouch()) {
  new MutationObserver(f8d_queue).observe(document.body, {childList: true, subtree: true});
  const pop = document.getElementById('pop'); if (pop) new MutationObserver(f8d_queue).observe(pop, {attributes: true, attributeFilter: ['class']});
}
