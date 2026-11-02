/* 2.488.0 (#3988): desktop only - a plain Back arrow at the left of the head bar (#top), plus Alt+Left, Cmd+[ and the mouse's
   Back button. It is history.back() like the swipe on a phone, but only while there is an earlier view *inside* Kalmido
   (own list of the views visited, never a foreign page or the sign-in); otherwise the arrow is greyed out and the keys do
   nothing (the browser's own jump out of the app is swallowed too, so a browser and the desktop shell behave the same).
   An overlay entry (task panel on touch, shopping mode, job chat, dialogs on touch) counts as "something to go back from":
   Back closes it first (backclose.js / detail.js handle that popstate), it is not a view of its own. */
const BN = {st: [location.hash], i: 0, type: '', len: history.length};
const bnOverlay = () => { const s = history.state; return !!(s && (s.f8d || s.jc || s.shop || s.detail)); };
const bnCan = () => BN.i > 0 || bnOverlay();
const bnTip = () => tr('Back') + ' (' + kbText(IS_MAC ? 'Mod+[' : 'Alt+←') + ')';
function bnBtn() {
  const t = esc(bnTip());
  return `<button type="button" class="iconbtn bnback" data-act="nav-back" aria-label="${t}" title="${t}"${bnCan() ? '' : ' disabled'}>${ic('arrowl')}</button>`;
}
function bnSync() {
  const el = $('#top [data-act="nav-back"]'); if (!el) return;
  el.disabled = !bnCan();
}
function bnBack() { if (!isMobile() && bnCan()) history.back(); }
// push or traverse? A hash change fires popstate either way, so ask the Navigation API where there is one (it fires first),
// otherwise the length of the history (a new entry makes it longer)
window.navigation?.addEventListener?.('navigate', e => { BN.type = e.navigationType || ''; });
{ const push = history.pushState.bind(history); history.pushState = (...a) => { push(...a); BN.len = history.length; setTimeout(bnSync, 0); }; }  // an overlay entry is no view, but the length moves
window.addEventListener('popstate', () => setTimeout(bnSync, 0), true);
window.addEventListener('hashchange', () => {
  const h = location.hash, n = history.length;
  const trav = BN.type ? BN.type === 'traverse' : n <= BN.len;
  BN.type = ''; BN.len = n;
  if (trav) {  // Back / Forward: the neighbour in our list, an unknown target counts as a step back
    if (BN.st[BN.i - 1] === h) BN.i--;
    else if (BN.st[BN.i + 1] === h) BN.i++;
    else if (BN.st[BN.i] !== h) { BN.i = Math.max(0, BN.i - 1); BN.st[BN.i] = h; }
  } else if (BN.st[BN.i] !== h) { BN.st.length = BN.i + 1; BN.st.push(h); BN.i++; }
  bnSync();
});
const bnField = t => !!(t && t.closest && t.closest('input, textarea, select, [contenteditable=""], [contenteditable="true"], .ProseMirror'));
document.addEventListener('keydown', e => {
  if (isMobile() || e.defaultPrevented || e.shiftKey) return;
  const back = (e.key === 'ArrowLeft' && e.altKey && !e.ctrlKey && !e.metaKey) || (e.key === '[' && e.metaKey && !e.altKey && !e.ctrlKey);
  if (!back || bnField(e.target)) return;
  e.preventDefault(); bnBack();
});
document.addEventListener('mouseup', e => { if (e.button !== 3 || isMobile()) return; e.preventDefault(); bnBack(); });
for (const ev of ['mousedown', 'auxclick']) document.addEventListener(ev, e => { if (e.button === 3 && !isMobile()) e.preventDefault(); });
