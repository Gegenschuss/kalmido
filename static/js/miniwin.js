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

// ---- 2.43.0 (#1500): a task in its own small window. Desktop: a middle click on the task row, "Open in its own window" in the task
// menu or the button in the properties panel opens /?mini=1#t/<id> (window name kalmido-task-<id>: the same task comes back to its
// window). The window shows only this task's panel (no sidebar / tabs / chat), live like any tab; a deleted task or one that is no
// longer shared shows a note. UI state is not written back (the MW_ON guards above).
let MW_TASK = MW_ON ? +(/^#t\/(\d+)/.exec(location.hash) || [])[1] || 0 : 0;
function mw_taskOpen(id) {
  if (!taskById(id)) return null;
  const w = Math.min(520, screen.availWidth || 520), h = Math.min(760, screen.availHeight || 760);
  const x = Math.max(0, (window.screenX || 0) + (window.outerWidth || 0) - w - 40), y = Math.max(0, (window.screenY || 0) + 60);
  const win = window.open(`/?mini=1#t/${id}`, 'kalmido-task-' + id, `popup,width=${w},height=${h},left=${x},top=${y}`);
  if (!win) { toast(tr('The browser blocked the window. Allow pop-ups for this page.')); return null; }
  try { win.focus(); } catch { /* another origin / closed */ }
  return win;
}
const mw_rowOf = e => { const r = e.target.closest?.('#view .trow[data-id]'); return r && !e.target.closest('a[href]') ? r : null; };  // a real link in the row keeps its own click
document.addEventListener('mousedown', e => { if (e.button === 1 && mw_ok() && mw_rowOf(e)) e.preventDefault(); });  // no auto-scroll
document.addEventListener('auxclick', e => {
  const r = e.button === 1 && mw_ok() && mw_rowOf(e); if (!r || !(+r.dataset.id > 0)) return;
  e.preventDefault(); mw_taskOpen(+r.dataset.id);
});
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-mwtask]'); if (!b || !mw_ok()) return;
  e.preventDefault(); e.stopPropagation(); mw_taskOpen(+b.dataset.mwtask);
}, true);
if (MW_ON && MW_TASK) {
  document.documentElement.classList.add('mini-task');
  let busy = false, checked = 0;
  const gone = () => {
    const d = $('#detail'); if (!d || d.querySelector('.mwgone')) return;
    S.sel = null; document.title = APP_NAME;
    d.classList.remove('hidden'); d.classList.add('open'); $('#app').classList.add('detail-open');
    d.innerHTML = `<div class="mwgone" role="status">${ic('eye', 'l')}<p>${tr('This task no longer exists, or it is no longer shared with you.')}</p></div>`;
  };
  // the panel stays open: a closed or replaced panel comes back, the task window follows the task opened in it (a subtask)
  const sync = async () => {
    if (!S.booted || busy) return; busy = true;
    try {
      if (S.sel > 0) MW_TASK = S.sel;
      const d = $('#detail'), now = Date.now();
      if (!taskById(MW_TASK)) {
        if (d?.querySelector('.mwgone') && now - checked < 15000) return;
        checked = now;
        try { putTask(await rawFetch('GET', '/api/tasks/' + MW_TASK)); } catch (e) { if (!(e instanceof Offline)) gone(); return; }
        if (d?.querySelector('.mwgone')) S.sel = null;
      }
      if (S.sel !== MW_TASK) openDetail(MW_TASK);
      const t = taskById(MW_TASK); if (t) document.title = `${t.title} · ${APP_NAME}`;
    } finally { busy = false; }
  };
  setTimeout(sync, 300); setInterval(sync, 1000);
}

// ---- 2.145.0 B (#2424): an own window starts from the state the app already has open. The start scripts run ~0.6 s; the full state
// request (all lists and tasks) came on top of that. Now the window asks the open app windows of this browser (BroadcastChannel, same
// origin, same person: the uid of this browser's storage) for their state while its scripts still run, draws from it at once and fetches
// the state behind it (the usual full load, then a redraw that waits for unsaved input like the poll's). The answer is serialised like
// the offline cache (LS.set: le2eRepl, the ciphers of encrypted lists only, never a key), so nothing the window could not read from
// this browser anyway. No answer within 200 ms after the scripts ran (no app window open, a busy one), a change still waiting to be
// sent, another person: the normal start.
const MW_SNAP_CH = 'kalmido-mini-state';
// 2.306.0 D4 (#2875): the channel answers only a window that knows the nonce of this browser tab family: a window opened with window.open copies
// the opener's sessionStorage, any other same-origin context has none (it starts the normal way)
function mw_nonce(make) {
  try {
    let n = sessionStorage.getItem('kalmido-mwn') || '';
    if (!n && make) { n = Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, '0')).join(''); sessionStorage.setItem('kalmido-mwn', n); }
    return n;
  } catch { return ''; /* private mode: no shared start */ }
}
const mw_snapP = MW_ON && typeof BroadcastChannel === 'function' && LS.get('uid', null) != null && mw_nonce(false) ? new Promise(res => {
  const uid = LS.get('uid', null), ask = Math.random().toString(36).slice(2), ch = new BroadcastChannel(MW_SNAP_CH), nonce = mw_nonce(false);
  const done = j => { ch.onmessage = null; ch.close(); res(j); };
  ch.onmessage = e => {
    const m = e.data; if (!m || m.re !== ask || m.uid !== uid || typeof m.state !== 'string') return;
    let j = null; try { j = JSON.parse(m.state); } catch { /* broken: wait for another answer or the time-out */ }
    if (j?.me?.id === uid && Array.isArray(j.lists) && Array.isArray(j.tasks)) done(j);
  };
  setTimeout(() => done(null), 8000);  // the channel does not stay open
  ch.postMessage({ask, uid, nonce});
}) : null;
let mw_snapUsed = false;
async function mw_bootLoad() {  // main.js: instead of load() in an own window
  const j = mw_snapP ? await Promise.race([mw_snapP, new Promise(r => setTimeout(() => r(null), 200))]) : null;
  if (!j || OUT.q.length || S.tasks.size) return load();
  OUT.me = j.me.id; applyState(j); S.lpCache = j; mw_snapUsed = true;
  try { performance.mark('kalmido:snap'); } catch { /* old browser */ }
}
async function mw_bootSync() {  // main.js, after the first picture: the real state behind it
  if (!mw_snapUsed) return;
  try { await load(); } catch { return; /* offline / signed out: the poll and api() take it from here */ }
  td_renderSoon();
}
// a booted main window answers (own windows do not: they would serialise the same state once more): its current state, like the offline cache
if (!MW_ON && typeof BroadcastChannel === 'function' && mw_nonce(true)) {
  try {
    const ch = new BroadcastChannel(MW_SNAP_CH), nonce = mw_nonce(true);
    ch.onmessage = e => {
      const m = e.data; if (!m || typeof m.ask !== 'string' || m.nonce !== nonce || !S.booted || !S.me || m.uid !== S.me.id || !S.lpCache || OUT.q.length) return;
      let state;
      try { state = JSON.stringify({...S.lpCache, v: S.v, tasks: [...S.tasks.values()], lists: S.lists, counts: S.counts}, typeof le2eRepl === 'function' ? le2eRepl() : undefined); } catch { return; }
      ch.postMessage({re: m.ask, uid: S.me.id, state});
    };
  } catch { /* no channel: every window starts on its own */ }
}
