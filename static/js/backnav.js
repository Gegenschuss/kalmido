// @ts-check
/* 2.488.0 (#3988): desktop only - a plain Back arrow at the left of the head bar (#top), plus Alt+Left, Cmd+[ and the mouse's
   Back button. It is history.back() like the swipe on a phone, but only while there is an earlier view *inside* Kalmido
   (own list of the views visited, never a foreign page or the sign-in); otherwise the arrow is greyed out and the keys do
   nothing (the browser's own jump out of the app is swallowed too, so a browser and the desktop shell behave the same).
   An overlay entry (task panel on touch, shopping mode, job chat, dialogs on touch) counts as "something to go back from":
   Back closes it first (backclose.js / detail.js handle that popstate), it is not a view of its own. */
const BN = {i: 0, nt: '', /** @type {Record<number, string>} */ h: {}};  // index of the current view; every history entry of Kalmido carries it as state.bn
// 2.743.0 (#5235): BN.h = the address of each view index visited in this page load (navUp reads the one before)
const bnHere = () => { BN.h[BN.i] = location.hash.slice(1); };
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
  history.replaceState = (/** @type {any} */ s, /** @type {string} */ t, /** @type {string | URL | null | undefined} */ u) => { bnRep(bnKeep(s, BN.i), t, u); bnHere(); };
  history.pushState = (/** @type {any} */ s, /** @type {string} */ t, /** @type {string | URL | null | undefined} */ u) => {
    let h = location.hash; try { h = new URL(u ?? location.href, location.href).hash; } catch { /* keep */ }
    if (h !== location.hash) BN.i++;
    push(bnKeep(s, BN.i), t, u); bnHere(); setTimeout(bnSync, 0);
  };
}
try { bnRep(bnKeep(history.state, 0), '', location.href); } catch { /* old browser */ }  // the first view of this page load
bnHere();
// a location.replace('#x') (chatwin.js, miniwin.js, areas.js) makes no new entry: where the Navigation API says so, the index
// stays (review F15; without that API such a replace counts as a step, these places are own windows / the phone)
/** @type {any} */ (window).navigation?.addEventListener?.('navigate', (/** @type {any} */ e) => { BN.nt = e.navigationType || ''; });
function bnOnNav() {
  const m = bnMark(), rep = BN.nt === 'replace'; BN.nt = '';
  if (m !== null) BN.i = m;  // back / forward to an entry of Kalmido
  else { if (!rep) BN.i++; try { bnRep(bnKeep(history.state, BN.i), '', location.href); } catch { /* old browser */ } }  // a new view (location.hash = ...)
  bnHere(); bnSync();
}
window.addEventListener('popstate', () => { const m = bnMark(); if (m !== null) { BN.i = m; bnHere(); } setTimeout(bnSync, 0); }, true);
// 2.743.0 (#5235): the visible Back arrow of a detail page (contact, client, letter, document, note, team room, wiki page,
// agent chat) and the "one level up" links (Bookkeeping, Tables, ...) go *up* to their list. Was the view before exactly
// that list, it is history.back() - so the phone's / browser's Back afterwards leaves the list instead of opening the closed
// page again; otherwise (opened by a link, after a reload) the list replaces the detail entry (go(to, true)), no new entry.
const bnNorm = (/** @type {string} */ h) => { let x = String(h || '').replace(/^#/, ''); try { x = decodeURIComponent(x); } catch { /* keep */ } return x; };
function navUp(/** @type {string} */ to) {
  const want = bnNorm(to), prev = BN.i > 0 && !bnOverlay() ? BN.h[BN.i - 1] : undefined;
  // an office link inside an open workspace under "All" has the address office/s/<space>/... (core.js parseHash)
  const p = prev === undefined ? null : bnNorm(prev), same = p !== null && (p === want || (!/^office\/s\//.test(want) && p.replace(/^office\/s\/[^/]+\//, 'office/') === want));
  if (same) history.back(); else go(want, true);
}
// a link marked data-navup (an "up" link of a page) goes the same way; Ctrl / Cmd / Shift / middle click keep the browser's own
document.addEventListener('click', e => {
  const a = /** @type {any} */ (e.target)?.closest?.('a[data-navup]');
  if (!a || e.defaultPrevented || e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
  const h = a.getAttribute('href') || ''; if (!h.startsWith('#')) return;
  e.preventDefault(); navUp(h);
});
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
