/* 2.58.0 (#1757, #1730): on a touch device the Back key / swipe closes the topmost dialog, sheet, menu or the search palette
   instead of changing the route. While an overlay is open one history entry is pushed; Back pops it and closes the overlay,
   closing the overlay another way takes the entry away again. The popstate listener runs first (capture) and keeps the
   other popstate handlers (detail panel, shopping mode) from also reacting to that Back.
   2.652.0 (#5070): one entry per open overlay level (pushed = how many, state.f8d = the level of the entry), pushed when the level
   opens. Back closes exactly the topmost level and pushes nothing anew: an entry pushed in the popstate handler (without a tap)
   is skipped by Chrome's Back, so the second Back of document preview -> full view left the app instead of closing the preview. */
const f8d_bk = {pushed: 0, skip: false, queued: false, url: '', after: /** @type {Array<() => void>} */ ([]), t: 0};  // after / t: f8d_defer
const f8d_open = () => {
  if ($('.palette:not(.an-out)')) return 'palette';
  if ($('.lightbox')) return 'lightbox';
  const pop = $('#pop');
  if (pop && !pop.classList.contains('hidden')) return 'pop';
  // 2.497.0 (#4040): shopping mode has its own history entry (family.js): a second one here stayed behind after closing it (a dead Back)
  if ($('.modal:not(.authscreen):not(.an-out):not(.shopmode)')) return 'modal';
  // 2.619.0 (#4943): the quick add sheet on its own (was 'pop': closePop only closed it through popOnClose, which a menu opened
  // in the sheet (list, template) had taken over: Back then closed nothing); a sheet still folding away (an-out) is closed already
  if ($('.qadd.sheet:not(.an-out)')) return 'qsheet';
  if ($('.tsheet')) return 'tsheet';
  return '';
};
function f8d_closeTop() {
  const k = f8d_open();
  if (k === 'palette') closePalette();
  else if (k === 'lightbox') $('.lightbox').remove();
  else if (k === 'pop') closePop();
  else if (k === 'qsheet') { closePop(); tch_overlaysClose(); }  // 2.619.0 (#4943): the scrim + whoever holds popOnClose, then the sheet (popovers.js)
  else if (k === 'modal') modalClose($$('.modal:not(.authscreen):not(.an-out)').pop());
  else if (k === 'tsheet') $('[data-ts="close"]', $('.tsheet'))?.click();
}
// 2.652.0 (#5070): how many overlay levels are open (a dialog under a lightbox under a menu = 3); one history entry each
const f8d_depth = () => {
  const pop = $('#pop');
  return ($('.palette:not(.an-out)') ? 1 : 0) + $$('.lightbox').length + (pop && !pop.classList.contains('hidden') ? 1 : 0)
    + $$('.modal:not(.authscreen):not(.an-out):not(.shopmode)').length + ($('.qadd.sheet:not(.an-out)') ? 1 : 0) + ($('.tsheet') ? 1 : 0);
};
const f8d_lvl = () => { const v = history.state?.f8d; return typeof v === 'number' ? v : 0; };
function f8d_sync() {
  f8d_bk.queued = false;
  if (f8d_bk.skip) return;  // our own history.back() is still on its way
  const n = f8d_depth();
  if (n > f8d_bk.pushed) { while (f8d_bk.pushed < n) history.pushState({f8d: ++f8d_bk.pushed}, '', location.href); }
  else if (n < f8d_bk.pushed) {
    f8d_bk.pushed = n;
    // only our own entries above the open levels; after a route change (or a replaced entry) the current one is not ours
    const over = f8d_lvl() - n;
    // 2.652.0 (#5070): the address the view has now (the closed overlay set it, e.g. docs.js '#docs') also on the entry Back
    // lands on: that entry still had the overlay's address ('#docs/15'), its hashchange opened the document again
    if (over > 0) { f8d_bk.skip = true; f8d_bk.url = location.href; if (over === 1) history.back(); else history.go(-over); }
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
  if (f8d_bk.skip) {
    if (f8d_bk.url && location.href !== f8d_bk.url) history.replaceState(history.state, '', f8d_bk.url);
    f8d_bk.url = ''; f8d_bk.skip = false; e.stopImmediatePropagation(); f8d_queue(); if (f8d_bk.after.length) setTimeout(f8d_flush, 0); return; }
  if (!f8d_bk.pushed) return;
  // 2.652.0 (#5070): landed below our top entry: close as many levels as were stepped back over (one per Back; an entry
  // whose state another module replaced counts as one step), nothing is pushed again; forward onto an entry is left alone
  const v = history.state?.f8d, close = typeof v === 'number' ? f8d_bk.pushed - v : 1;
  if (close <= 0) return;
  f8d_bk.pushed -= close; e.stopImmediatePropagation();
  for (let i = 0; i < close && f8d_open(); i++) f8d_closeTop();
  f8d_queue();
}, true);
if (typeof isTouch === 'function' && isTouch()) {
  new MutationObserver(f8d_queue).observe(document.body, {childList: true, subtree: true});
  const pop = document.getElementById('pop'); if (pop) new MutationObserver(f8d_queue).observe(pop, {attributes: true, attributeFilter: ['class']});
}
