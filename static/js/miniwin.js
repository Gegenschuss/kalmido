/* Kalmido web client: a list in its own small browser window (2.39.1, #1294).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// Desktop: a double click or a middle click on a list in the sidebar, or "Open in its own window" in the list menu, opens
// the list (in addition) in a narrow window of its own (window.open, about 420 x 700, one window name per list, so the same
// list comes back to its window and different lists get windows of their own). The window loads /?mini=1#l/<id>: only this
// list, no sidebar / tab bar / agent chat; the title bar with the list's name, the composer to add, tick off, a task opens
// in the same window. Live updates come like in any tab. The window does not write the main window's UI state: local
// preferences (last view, folded groups, widths ...) and settings PATCHes stay in this window.
const MW_ON = new URLSearchParams(location.search).get('mini') === '1';
const mw_lid = () => +(/^#l\/(\d+)/.exec(location.hash) || [])[1] || 0;
let MW_ID = MW_ON ? mw_lid() : 0;
const mw_desk = () => { try { return matchMedia('(hover:hover) and (pointer:fine)').matches; } catch { return false; } };
const mw_ok = () => !MW_ON && mw_desk();  // touch devices: nothing changes
function mw_open(id) {
  const l = listById(id); if (!l) return null;
  const w = Math.min(420, screen.availWidth || 420), h = Math.min(700, screen.availHeight || 700);
  const x = Math.max(0, (window.screenX || 0) + (window.outerWidth || 0) - w - 40), y = Math.max(0, (window.screenY || 0) + 60);
  const win = window.open(`/?mini=1#l/${id}`, 'kalmido-mini-' + id, `popup,width=${w},height=${h},left=${x},top=${y}`);
  if (!win) { toast(tr('The browser blocked the window. Allow pop-ups for this page.')); return null; }
  try { win.focus(); } catch { /* another origin / closed */ }
  return win;
}
// the sidebar: double click (the first click has opened the list in the main view as always) and middle click
let mwLast = {id: 0, t: 0};
document.addEventListener('click', e => {
  const r = e.target.closest?.('#side .srow[data-list]'); if (!r || !mw_ok() || e.button !== 0) return;
  const id = +r.dataset.list, now = Date.now();
  if (mwLast.id === id && now - mwLast.t < 450) { mwLast = {id: 0, t: 0}; mw_open(id); return; }
  mwLast = {id, t: now};
}, true);
document.addEventListener('mousedown', e => { if (e.button === 1 && mw_ok() && e.target.closest?.('#side .srow[data-list]')) e.preventDefault(); });  // no auto-scroll
document.addEventListener('auxclick', e => {
  const r = e.button === 1 && e.target.closest?.('#side .srow[data-list]'); if (!r || !mw_ok()) return;
  e.preventDefault(); mw_open(+r.dataset.list);
});
if (MW_ON) {
  document.documentElement.classList.add('mini');
  // nothing of this window's UI state goes back: only the offline queue and its id map (shared data) are written locally
  const MW_LS = new Set(['outbox', 'idmap', 'conflicts', 'uid']), lsSet = LS.set.bind(LS);
  LS.set = (k, v) => { if (MW_LS.has(k)) lsSet(k, v); };
  const api0 = api;
  api = (method, url, body) => method === 'PATCH' && /^\/api\/settings\b/.test(url) ? Promise.resolve({}) : api0(method, url, body);
  // only this list (a task of it opens in the panel): another view's address goes back to the list
  window.addEventListener('hashchange', () => {
    const id = mw_lid(); if (id) { MW_ID = id; return; }
    if (MW_ID && !/^#t\//.test(location.hash)) location.replace('#l/' + MW_ID);
  });
  // the window's title: the list's name
  const title = () => { const l = MW_ID && listById(MW_ID); if (l) document.title = `${lname(l)} · ${APP_NAME}`; };
  const mwTop = $('#top'); if (mwTop) new MutationObserver(title).observe(mwTop, {childList: true});
}
