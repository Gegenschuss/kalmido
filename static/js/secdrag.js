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
// touch: dnd.js calls this after the long press on a section header
let sb_sd = null;
function sb_secHoldStart(h, sid, x, y) {
  sb_secTouchStop();
  const r = h.getBoundingClientRect(), g = h.cloneNode(true);
  g.classList.add('ghost-drag', 'sb-secghost');
  g.style.cssText = `position:fixed;left:${r.left}px;top:${r.top}px;width:${r.width}px;z-index:95;pointer-events:none`;
  document.body.appendChild(g);
  sb_sd = {h, sid, g, x, y, dx: x - r.left, dy: y - r.top, moved: false, sc: tdScroller(h)};
  // the events stay with the touched element: listen on the header (it still gets them if a live update takes it out)
  h.addEventListener('touchmove', sb_secTouchMove, {passive: false});
  h.addEventListener('touchend', sb_secTouchEnd);
  h.addEventListener('touchcancel', sb_secTouchStop);
  sb_secFold(h, true);
  if (navigator.vibrate) navigator.vibrate(12);
}
function sb_secTouchMove(e) {
  const st = sb_sd, p = e.touches[0]; if (!st || !p) return;
  if (!st.moved && Math.hypot(p.clientX - st.x, p.clientY - st.y) < 6) return;
  e.preventDefault(); st.moved = true; st.lx = p.clientX; st.ly = p.clientY;
  sb_secFrame(p.clientX, p.clientY);
}
// 2.87.9 (#1965): once per frame; the ghost slides by transform
const sb_secFrame = rafThrottle((x, y) => {
  const st = sb_sd; if (!st) return;
  st.g.style.transform = `translate(${x - st.x}px, ${y - st.y}px)`;
  const sp = sb_secSpot(x, y);
  sb_secMark(sp && sb_secOrder(st.sid, sp) ? sp : null);
  const sc = st.sc, r = sc === document.scrollingElement || sc === document.documentElement ? {top: 0, bottom: innerHeight} : sc.getBoundingClientRect();
  if (y < r.top + 56) sc.scrollBy(0, -14); else if (y > Math.min(r.bottom, innerHeight) - 56) sc.scrollBy(0, 14);
});
function sb_secTouchEnd(e) {
  const st = sb_sd; if (!st) return;
  const o = st.moved && sb_secOrder(st.sid, sb_secSpot(st.lx, st.ly));  // measured while the section is still folded
  sb_secTouchStop();
  if (e?.cancelable) e.preventDefault();
  // held without moving: up / down as before (on the header now shown: a live update may have drawn it anew)
  if (!st.moved) { const h = st.h.isConnected ? st.h : $(`#view .ghead[data-section="${st.sid}"], #view .khead[data-ksec="${st.sid}"]`); if (h) secHeadMenu(h, st.sid); return; }
  if (o) saveSectionOrder(o.lid, o.ids);
}
function sb_secTouchStop() {
  sb_secFrame.cancel();
  const st = sb_sd; sb_sd = null;
  $$('.sb-secghost').forEach(x => x.remove());
  $$('#view .dropbefore, #view .dropafter').forEach(x => x.classList.remove('dropbefore', 'dropafter'));
  if (!st) return;
  st.h.removeEventListener('touchmove', sb_secTouchMove); st.h.removeEventListener('touchend', sb_secTouchEnd); st.h.removeEventListener('touchcancel', sb_secTouchStop);
  sb_secFold(st.h, false);
}
