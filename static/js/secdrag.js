// 2.46.1 (#1635): sections (list view) and board columns: where a dragged section goes -- before the one under the pointer,
// or past the middle of the last one (or below / right of it) = the very end. Shared by the mouse (dnd.js) and the long press
// on a phone (below, like a task: a buzz, the section folds while it is dragged). Held and let go without moving: the menu
// with up / down as before (the way without dragging).
const sb_secKan = () => !!$('#view .kcol[data-kcol]');
const sb_secEls = () => sb_secKan() ? $$('#view .kcol[data-kcol]') : $$('#view .ghead[data-section]').map(h => h.closest('.group') || h);
const sb_secHead = el => el.classList.contains('group') ? el.querySelector('.ghead[data-section]') || el : el;
// -> {el: the head / column to go before, end: after the last one} or null; el = the element under the pointer, used when
// nothing is laid out (no sizes)
function sb_secSpot(x, y, el) {
  const kan = sb_secKan(), els = sb_secEls(), n = sb_dropNear(els, kan ? x : y, kan ? 'x' : 'y', 48);
  if (!n) { const t = el?.closest?.('#view .ghead[data-section], #view .kcol[data-kcol]'); return t ? {el: t, end: false} : null; }
  const i = els.indexOf(n.el);
  return n.after && i < els.length - 1 ? {el: sb_secHead(els[i + 1]), end: false} : {el: sb_secHead(n.el), end: n.after};
}
// the list's new section order with sid moved to spot; null = nothing changes
function sb_secOrder(sid, spot) {
  const s = S.sections.find(x => x.id === sid); if (!s || !spot) return null;
  const now = secIds(s.list_id), ids = now.filter(x => x !== sid), tid = secOf(spot.el) ? +secOf(spot.el) : null;
  if (!spot.end && tid === sid) return null;
  const at = spot.end ? ids.length : tid ? ids.indexOf(tid) : 0; if (at < 0) return null;
  ids.splice(at, 0, sid);
  return ids.join() === now.join() ? null : {lid: s.list_id, ids};
}
function sb_secMark(spot) {
  $$('#view .dropbefore, #view .dropafter').forEach(x => x.classList.remove('dropbefore', 'dropafter'));
  if (!spot) return;
  if (spot.end) (spot.el.classList.contains('kcol') ? spot.el : spot.el.closest('.group') || spot.el).classList.add('dropafter');
  else spot.el.classList.add('dropbefore');
}
const sb_secFold = (h, on) => { const g = h?.closest('.group, .kcol'); if (!g) return; g.classList.toggle('dragging', on); if (g.classList.contains('group')) g.classList.toggle('sb-secfold', on); };
// touch: dnd.js calls this after the long press on a section header. 2.102.0 (#1998): the drag itself is drag.js (ghost,
// threshold, auto-scroll, Esc); here only where the section goes
let sb_sd = null;
function sb_secHoldStart(h, sid, x, y) {
  sb_secTouchStop();
  const st = sb_sd = {h, sid, moved: false};
  drg_begin(h, x, y, {
    ghost: {el: h, cls: 'ghost-drag sb-secghost'}, threshold: 6, raf: true, scroll: tdScroller(h),
    onStart: () => { st.moved = true; },
    onMove: (d, mx, my) => { if (sb_sd !== st) return; const sp = sb_secSpot(mx, my); sb_secMark(sp && sb_secOrder(st.sid, sp) ? sp : null); },
    onDrop: (d, mx, my) => {
      const o = sb_secOrder(st.sid, sb_secSpot(mx, my));  // measured while the section is still folded
      sb_secTouchStop();
      if (o) saveSectionOrder(o.lid, o.ids);
    },
    // held without moving: up / down as before (on the header now shown: a live update may have drawn it anew)
    onTap: () => {
      sb_secTouchStop();
      const hh = st.h.isConnected ? st.h : $(`#view .ghead[data-section="${st.sid}"], #view .khead[data-ksec="${st.sid}"]`); if (hh) secHeadMenu(hh, st.sid);
    },
    onCancel: () => sb_secTouchStop(),
  }, st);
  sb_secFold(h, true);
  if (navigator.vibrate) navigator.vibrate(12);
}
function sb_secTouchStop() {
  const st = sb_sd; sb_sd = null;
  if (st && drg_cur && drg_cur.d === st) drg_cancel();
  $$('.sb-secghost').forEach(x => x.remove());
  $$('#view .dropbefore, #view .dropafter').forEach(x => x.classList.remove('dropbefore', 'dropafter'));
  if (st) sb_secFold(st.h, false);
}
