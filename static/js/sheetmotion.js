/* Kalmido web client: bottom sheets, dialogs and the dimming layer move in and out on phones (2.46.1, #1558 / #1559).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// Opening is plain CSS (app.css block "2.46.1 E (#1558)": a keyframe on the element that appears). Closing is the part that
// needs code, because the element is gone (or hidden) the moment the close path runs: the app's state is finished at once
// (selection done, focus back, hooks run), only the picture waits ~200 ms.
//  - #pop (menus, choice sheets, the bell) and #scrim only toggle `hidden`: a MutationObserver puts the leaving look back
//    (class an-out, which CSS draws although `hidden` stays) and drops it after the timeout or when the element opens again
//  - dialogs (modal()), the date / time picker (dpClose) and quick add: an_remove(el) instead of el.remove() keeps the node
//    for the exit and removes it afterwards; opening anything new (an_flush) removes leaving nodes first so no stale twin
//    answers a query
// Phones only (isMobile), never with "reduce motion"; a drag that already carried the sheet off screen skips the exit
// (an_skipNext from sheetdrag.js).
const AN_MS = 200;
const AN = {skip: 0};
const an_on = () => { try { return isMobile() && !matchMedia('(prefers-reduced-motion: reduce)').matches; } catch { return false; } };
const an_skipNext = () => { AN.skip = performance.now() + 60; };
const an_skipped = () => { const s = AN.skip > performance.now(); AN.skip = 0; return s; };
function an_kill(el) { clearTimeout(el._anT); el._anOut = false; el.classList.remove('an-out'); Element.prototype.remove.call(el); }
// remove el after its exit; a second call (double tap) is a no-op
function an_remove(el) {
  if (!el || el._anOut) return;
  if (an_skipped() || !an_on() || !el.isConnected || el.matches('.smodal, .authscreen, .shopmode, .palette') || getComputedStyle(el).display === 'none') { an_kill(el); return; }  // the full-screen ones have no exit
  el._anOut = true; el.classList.add('an-out'); el.setAttribute('inert', '');
  el._anT = setTimeout(() => an_kill(el), AN_MS);
}
// something new opens: leaving nodes go now
function an_flush() { document.querySelectorAll('.an-out').forEach(e => { if (e._anOut) an_kill(e); }); }

// layers that are switched by a class (`hidden`; the + button uses `gone`): #pop (sheet), #scrim, #mbar, #fab. keep = classes
// the close path removes at once but the exit picture still needs; need = a class the element must have had to be a sheet
function an_watch(el, hide = 'hidden', keep = [], need = '') {
  if (!el || el._anW || typeof MutationObserver === 'undefined') return;
  el._anW = true;
  const has = (str, c) => new RegExp('(^| )' + c + '( |$)').test(str);
  const done = () => { clearTimeout(el._anT); if (el.classList.contains('an-out')) { el.classList.remove('an-out'); if (el.classList.contains(hide)) keep.forEach(c => el.classList.remove(c)); } };
  const mo = new MutationObserver(recs => {
    for (const r of recs) {
      const old = r.oldValue || '', wasHid = has(old, hide), isHid = el.classList.contains(hide), out = el.classList.contains('an-out');
      if (out && !isHid) { clearTimeout(el._anT); el.classList.remove('an-out'); continue; }  // shown again while leaving
      if (!wasHid && isHid && !out && an_on() && (typeof S === 'undefined' || S.booted) && !has(old, 'clear') && (!need || has(old, need))) {
        if (an_skipped()) continue;
        keep.forEach(c => { if (has(old, c)) el.classList.add(c); });
        el.classList.add('an-out'); clearTimeout(el._anT); el._anT = setTimeout(done, AN_MS);
      }
    }
    mo.takeRecords();
  });
  mo.observe(el, {attributes: true, attributeFilter: ['class'], attributeOldValue: true});
}
function an_init() {
  an_watch(document.getElementById('pop'), 'hidden', ['sheet', 'overmodal'], 'sheet'); an_watch(document.getElementById('scrim'), 'hidden', ['overmodal']);
  an_watch(document.getElementById('fab'), 'gone'); an_watch(document.getElementById('mbar'), 'hidden');
}
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', an_init); else an_init();

// ---- #1559: rows that leave a list (done, reopened, won't do, deleted) fade out before the list redraws without them. The
// caller's request runs meanwhile; the redraw waits for the returned promise (a request that fails brings the row back)
function an_rowOut(ids) {
  if (!an_on()) return Promise.resolve();
  const rows = ids.flatMap(id => [...document.querySelectorAll(`#view .trow[data-id="${id}"]`)]);
  if (!rows.length) return Promise.resolve();
  rows.forEach(r => r.classList.add('an-rowout'));
  return new Promise(res => setTimeout(res, AN_MS - 20));
}
const an_rowsBack = ids => ids.forEach(id => document.querySelectorAll(`#view .trow[data-id="${id}"].an-rowout`).forEach(r => r.classList.remove('an-rowout')));

// ---- #1559: a redraw that opens a group / subtasks / the done section: the rows that were not there before fade in
function an_rowsIn(fn) {
  if (!an_on()) return fn();
  const had = new Set([...document.querySelectorAll('#view .trow[data-id]')].map(r => r.dataset.id));
  const x = fn();
  document.querySelectorAll('#view .trow[data-id]').forEach(r => { if (!had.has(r.dataset.id)) r.classList.add('an-rowin'); });
  return x;
}

// ---- #1560: view changes. A redraw that comes with another route (list, view, tab) fades the view in; a redraw that newly
// shows an empty-state hint fades the hint in; the calendar's previous / next glides the page in from its side. Never a second
// render: the animation is a class on the finished DOM (alternating names restart it without forcing a layout).
const an_sig = () => [S.route.mod, S.route.key, S.route.tab, S.route.agent].join('|');
function an_view(fn) {
  const el = document.getElementById('view');
  if (!el || !an_on()) { const r = fn(); AN.sig = an_sig(); return r; }
  const hadEmpty = !!el.querySelector('.empty, .lempty'), r = fn(), sig = an_sig();
  if (AN.sig !== undefined && sig !== AN.sig) { el.classList.remove('an-v' + AN.vn); AN.vn = AN.vn === 1 ? 2 : 1; el.classList.add('an-v' + AN.vn); }
  else if (!hadEmpty) el.querySelector('.empty, .lempty')?.classList.add('an-hintin');
  AN.sig = sig;
  return r;
}
AN.vn = 1;
// dir: 1 = next (the page comes from the right), -1 = previous, 0 = no side (Today, Month / Week)
function an_calSlide(dir) {
  const el = document.getElementById('view'); if (!el || !an_on()) return;
  el.classList.remove('an-cs1', 'an-cs2', 'an-cn1', 'an-cn2', 'an-cp1', 'an-cp2', 'an-v1', 'an-v2');
  AN.cn = AN.cn === 1 ? 2 : 1;
  el.classList.add((dir > 0 ? 'an-cn' : dir < 0 ? 'an-cp' : 'an-cs') + AN.cn);
}
function an_tabs() {
  const b = document.querySelector('#tabs button.on'), k = b ? (b.dataset.go || b.dataset.act || '') : '';
  if (b && AN.tab !== undefined && k !== AN.tab && an_on()) b.classList.add('an-tabin');
  AN.tab = k;
}

// the box of a bottom sheet at rest: while its entry / exit animation runs getBoundingClientRect sits in the middle of the slide
function an_rect(el) {
  const r = el.getBoundingClientRect();
  try {
    if (el.getAnimations && el.getAnimations().some(a => a.playState === 'running') && getComputedStyle(el).position === 'fixed') {
      const b = parseFloat(getComputedStyle(el).bottom), h = el.offsetHeight;
      if (isFinite(b)) return {left: r.left, right: r.right, width: r.width, height: h, top: innerHeight - b - h, bottom: innerHeight - b};
    }
  } catch { /* measured as it is */ }
  return r;
}
