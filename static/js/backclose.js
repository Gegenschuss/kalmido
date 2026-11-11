/* 2.58.0 (#1757, #1730): on a touch device the Back key / swipe closes the topmost dialog, sheet, menu or the search palette
   instead of changing the route. While an overlay is open one history entry is pushed; Back pops it and closes the overlay,
   closing the overlay another way takes the entry away again. The popstate listener runs first (capture) and keeps the
   other popstate handlers (detail panel, shopping mode) from also reacting to that Back.
   2.652.0 (#5070): one entry per open overlay level (pushed = how many, state.f8d = the level of the entry), pushed when the level
   opens. Back closes exactly the topmost level and pushes nothing anew: an entry pushed in the popstate handler (without a tap)
   is skipped by Chrome's Back, so the second Back of document preview -> full view left the app instead of closing the preview. */
const f8d_bk = {pushed: 0, skip: false, queued: false, url: '', at: '', after: /** @type {Array<() => void>} */ ([]), t: 0};  // after / t: f8d_defer; at: the address our entries were pushed on (#5322)
// 2.956.0 (#5230): one mechanism for every level, from the top down: [kind, its open elements (bottom to top), close one].
// Each level element may carry views of its own (el._stk = the views before the shown one, el._back() shows the last of them;
// f8d_step below): every view is one step of Back, only the last Back closes the level (#5214 had this for dialogs only).
// The page itself is the lowest level ('view', #view): its _stk holds views of a page without an address of their own, it never
// closes, a route change empties it (f8d_viewNav). New since #5230: the tour (it sits on top; paused it is below everything
// else), the date picker (#dpop) and the sidebar as a drawer (#side.open).
const f8d_one = (/** @type {any} */ el) => el ? [el] : [];
const f8d_tourEls = (/** @type {boolean} */ paused) => typeof TOUR === 'object' && TOUR.on && !!TOUR.paused === paused ? f8d_one($('.tour')) : [];
/** @type {Array<[string, () => any[], (el: any) => void]>} */
const F8D_LV = [
  ['tour', () => f8d_tourEls(false), () => tourEnd(true)],
  ['palette', () => f8d_one($('.palette:not(.an-out)')), () => closePalette()],
  ['dpop', () => typeof DP === 'object' && DP.el ? [DP.el] : [], () => dpClose(true)],
  ['lightbox', () => $$('.lightbox'), el => el.remove()],
  ['pop', () => { const pop = $('#pop'); return pop && !pop.classList.contains('hidden') ? [pop] : []; }, () => closePop()],
  // 2.497.0 (#4040): shopping mode has its own history entry (family.js): a second one here stayed behind after closing it (a dead Back)
  ['modal', () => $$('.modal:not(.authscreen):not(.an-out):not(.shopmode)'), el => modalClose(el)],
  // 2.619.0 (#4943): the quick add sheet on its own (was 'pop': closePop only closed it through popOnClose, which a menu opened
  // in the sheet (list, template) had taken over: Back then closed nothing); a sheet still folding away (an-out) is closed already;
  // closing: the scrim + whoever holds popOnClose, then the sheet (popovers.js)
  ['qsheet', () => f8d_one($('.qadd.sheet:not(.an-out)')), () => { closePop(); tch_overlaysClose(); }],
  ['tsheet', () => f8d_one($('.tsheet')), el => $('[data-ts="close"]', el)?.click()],
  ['tourp', () => f8d_tourEls(true), () => tourEnd(true)],
  // the sidebar as a drawer (phone, rail): Back closes it instead of leaving the page (it went one page back before #5230)
  ['side', () => f8d_one($('#side.open')), () => closeSide()],
  ['view', () => { const v = $('#view'); return v?._stk?.length ? [v] : []; }, el => f8d_stepsClear(el)],
];
const f8d_top = () => { for (const [k, els, close] of F8D_LV) { const e = els(); if (e.length) return {k, el: e[e.length - 1], close}; } return null; };
const f8d_open = () => f8d_top()?.k || '';
// 2.766.0 (#5322): nav = a new view (another address), not a Back: a level with views of its own closes whole, it does not step back
function f8d_closeTop(nav = false) {
  const t = f8d_top(); if (!t) return;
  if (!nav && t.el._stk?.length && t.el._back?.()) { f8d_queue(); return; }  // 2.736.0 (#5214), all levels since #5230: a view inside the level first
  t.close(t.el);
}
// 2.736.0 (#5214): a level with views of its own counts one step per view: Back steps back through them, only the last Back closes
// it. The level calls f8d_queue() itself when it adds a view (no node is added or removed then); see settings.js stp_nav, f8d_step.
// 2.652.0 (#5070): how many overlay levels are open (a dialog under a lightbox under a menu = 3); one history entry each
const f8d_depth = () => F8D_LV.reduce((n, [k, els]) => n + els().reduce((m, el) => m + (k === 'view' ? 0 : 1) + (el._stk?.length || 0), 0), 0);
// 2.956.0 (#5230): the helpers for a level (or the page, $('#view')) with views of its own.
// f8d_step(el, back) = one view more: back() shows the view before it again (Back on a touch screen, the level's ‹ through f8d_stepBack)
function f8d_step(/** @type {any} */ el, /** @type {() => void} */ back) {
  if (!el) return;
  (el._stk ||= []).push(back);
  if (el.id === 'view') el._stkAt = location.hash;
  el._back ||= () => { const f = el._stk?.pop(); if (!f) return false; f(); return true; };
  if (typeof isTouch === 'function' && isTouch()) f8d_queue();
}
// a visible ‹ of the level: on a touch screen through its history entry (the entry goes too), else the view before directly
function f8d_stepBack(/** @type {any} */ el) {
  if (!el?._stk?.length) return false;
  if (typeof isTouch === 'function' && isTouch() && f8d_bk.pushed) history.back(); else el._back();
  return true;
}
// the level's views are gone (it was drawn anew, the page changed): their history entries go with the next sync
function f8d_stepsClear(/** @type {any} */ el) { if (!el?._stk?.length) return; el._stk = []; f8d_queue(); }
// route() (core.js): another page empties the views of the page before it
function f8d_viewNav() { const v = $('#view'); if (v?._stk?.length && v._stkAt !== location.hash) f8d_stepsClear(v); }
const f8d_lvl = () => { const v = history.state?.f8d; return typeof v === 'number' ? v : 0; };
function f8d_sync() {
  f8d_bk.queued = false;
  if (f8d_bk.skip) return;  // our own history.back() is still on its way
  const n = f8d_depth();
  // 2.956.0 (#5230): Back landed on one of our entries while nothing was open (the drawer reopened by Back, core.js; an overlay
  // that a new address had closed): the levels opening now take that entry over instead of pushing one more above it (that
  // second entry made the next Back a dead one: it landed on our old entry and closed nothing)
  if (n > f8d_bk.pushed && !f8d_bk.pushed && f8d_lvl() > 0 && f8d_lvl() <= n) { f8d_bk.pushed = f8d_lvl(); f8d_bk.at = location.href; }
  if (n > f8d_bk.pushed) { f8d_bk.at = location.href; while (f8d_bk.pushed < n) history.pushState({f8d: ++f8d_bk.pushed}, '', location.href); }
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
  // 2.766.0 (#5322, CI red p2123_d_ui since #5214): an entry not ours with another address = a new view (location.hash = ...,
  // a link): the settings opened into an area closed before #5214 and stayed open on their overview after it
  const nav = typeof v !== 'number' && !!f8d_bk.at && location.href !== f8d_bk.at;
  f8d_bk.pushed -= close; e.stopImmediatePropagation();
  for (let i = 0; i < close && f8d_open(); i++) f8d_closeTop(nav);
  f8d_queue();
}, true);
if (typeof isTouch === 'function' && isTouch()) {
  new MutationObserver(f8d_queue).observe(document.body, {childList: true, subtree: true});
  const pop = document.getElementById('pop'); if (pop) new MutationObserver(f8d_queue).observe(pop, {attributes: true, attributeFilter: ['class']});
  const side = document.getElementById('side'); if (side) new MutationObserver(f8d_queue).observe(side, {attributes: true, attributeFilter: ['class']});  // 2.956.0 (#5230): the drawer
}
