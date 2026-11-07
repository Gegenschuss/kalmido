// @ts-check
/* 2.488.0 (#3988): desktop only - a plain Back arrow at the left of the head bar (#top), plus Alt+Left, Cmd+[ and the mouse's
   Back button. It is history.back() like the swipe on a phone, but only while there is an earlier view *inside* Kalmido
   (own list of the views visited, never a foreign page or the sign-in); otherwise the arrow is greyed out and the keys do
   nothing (the browser's own jump out of the app is swallowed too, so a browser and the desktop shell behave the same).
   An overlay entry (task panel on touch, shopping mode, job chat, dialogs on touch) counts as "something to go back from":
   Back closes it first (backclose.js / detail.js handle that popstate), it is not a view of its own. */
const BN = {i: 0, nt: ''};  // index of the current view; every history entry of Kalmido carries it as state.bn
const bnOverlay = () => { const s = history.state; return !!(s && (s.f8d || s.jc || s.shop || s.detail)); };
const bnCan = () => BN.i > 0 || bnOverlay();
const bnTip = () => isTouch() ? tr('Back') : tr('Back') + ' (' + kbText(IS_MAC ? 'Mod+[' : 'Alt+←') + ')';  // 2.655.0 (#5084)
function bnBtn() {
  const t = esc(bnTip());
  return `<button type="button" class="iconbtn bnback" data-act="nav-back" aria-label="${t}" title="${t}"${bnCan() ? '' : ' disabled'}>${ic('arrowl')}</button>`;
}
function bnSync() {
  const el = $('#top [data-act="nav-back"]'); if (!el) return;
  el.disabled = !bnCan();
}
function bnBack() { if (!isMobile() && bnCan()) history.back(); }
// 2.488.0 (#3988, self-review): push or traverse is read from a mark in the entry's own state (state.bn = the view index), not
// from history.length (it stops growing at 50 entries in Firefox / WebKit, then every new view looked like a step back).
// The other modules' pushState / replaceState keep their state; the mark rides along. An overlay entry keeps the view index,
// a pushState to a new hash (notesall.js) is a new view.
const bnMark = () => { const s = history.state; return s && typeof s === 'object' && Number.isInteger(s.bn) ? s.bn : null; };
const bnKeep = (/** @type {any} */ s, /** @type {number} */ i) => s == null ? {bn: i} : (typeof s === 'object' && !Array.isArray(s) ? {...s, bn: i} : s);
const bnRep = history.replaceState.bind(history);
{
  const push = history.pushState.bind(history);
  history.replaceState = (/** @type {any} */ s, /** @type {string} */ t, /** @type {string | URL | null | undefined} */ u) => bnRep(bnKeep(s, BN.i), t, u);
  history.pushState = (/** @type {any} */ s, /** @type {string} */ t, /** @type {string | URL | null | undefined} */ u) => {
    let h = location.hash; try { h = new URL(u ?? location.href, location.href).hash; } catch { /* keep */ }
    if (h !== location.hash) BN.i++;
    push(bnKeep(s, BN.i), t, u); setTimeout(bnSync, 0);
  };
}
try { bnRep(bnKeep(history.state, 0), '', location.href); } catch { /* old browser */ }  // the first view of this page load
// a location.replace('#x') (chatwin.js, miniwin.js, areas.js) makes no new entry: where the Navigation API says so, the index
// stays (review F15; without that API such a replace counts as a step, these places are own windows / the phone)
/** @type {any} */ (window).navigation?.addEventListener?.('navigate', (/** @type {any} */ e) => { BN.nt = e.navigationType || ''; });
function bnOnNav() {
  const m = bnMark(), rep = BN.nt === 'replace'; BN.nt = '';
  if (m !== null) BN.i = m;  // back / forward to an entry of Kalmido
  else { if (!rep) BN.i++; try { bnRep(bnKeep(history.state, BN.i), '', location.href); } catch { /* old browser */ } }  // a new view (location.hash = ...)
  bnSync();
}
window.addEventListener('popstate', () => { const m = bnMark(); if (m !== null) BN.i = m; setTimeout(bnSync, 0); }, true);
window.addEventListener('hashchange', bnOnNav);
const bnField = (/** @type {any} */ t) => !!(t && t.closest && t.closest('input, textarea, select, [contenteditable=""], [contenteditable="true"], .ProseMirror'));
document.addEventListener('keydown', e => {
  if (isMobile() || e.defaultPrevented || e.shiftKey) return;
  const back = (e.key === 'ArrowLeft' && e.altKey && !e.ctrlKey && !e.metaKey) || (e.key === '[' && e.metaKey && !e.altKey && !e.ctrlKey);
  if (!back || bnField(e.target)) return;
  e.preventDefault(); bnBack();
});
document.addEventListener('mouseup', e => { if (e.button !== 3 || isMobile()) return; e.preventDefault(); bnBack(); });
for (const ev of ['mousedown', 'auxclick']) document.addEventListener(ev, (/** @type {any} */ e) => { if (e.button === 3 && !isMobile()) e.preventDefault(); });
