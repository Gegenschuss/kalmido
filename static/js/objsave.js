// @ts-check
// 2.558.0 (#4709): the browser side of the shared core's write path (kalmido/core/writes.py, docs/dev/kern.md), loaded on
// demand (lazyload.js LD_MODS objsave). One way for every dialog that saves an object of an area built on the core:
//   objOpen(md, url, open, key)  the dialog md opened with object `open`: unsaved input comes back (formguard fdDialog, base =
//                                its updated_at), an undo session starts for url (header X-Kalmido-Undo, core.js rawFetch0
//                                asks obj_hdr) and dlgStale watches the version: someone else saved meanwhile -> a calm bar
//   saveDialog(url, open, now)   sends ONLY the fields that differ from `open`, with expect_updated_at = open.updated_at ->
//                                the saved object; 409 -> {conflict: {cur, theirs, both}} (objMerge draws the bar: the fields
//                                someone else changed are marked, the next save goes against cur)
//   undoWrite(url, old, seenAt)  an undo as a second write: the old values against the version seen (409 = changed since)
//   objUndo(url, op)             the server's session undo of the dialog (POST <url>/undo, op undo | redo | all | redoall)
//   objClose(url)                the dialog is gone: its session ends
const OBS = {s: {}};
const objTok = () => [...crypto.getRandomValues(new Uint8Array(16))].map(b => b.toString(16).padStart(2, '0')).join('');
const objSame = (a, b) => (a ?? '') === (b ?? '') || JSON.stringify(a) === JSON.stringify(b);
/** @param {any} open @param {any} now */
function objDiff(open, now) {
  /** @type {Record<string, any>} */ const d = {};
  for (const k of Object.keys(now || {})) if (!objSame(open?.[k], now[k])) d[k] = now[k];
  return d;
}
/** @param {string} method @param {string} url */
function obj_hdr(method, url) {
  return method === 'PATCH' ? OBS.s[String(url).split('?')[0]]?.tok || '' : '';
}
/** @param {string} url @param {any} open @param {any} now */
async function saveDialog(url, open, now) {
  const d = objDiff(open, now);
  if (!Object.keys(d).length) return open;
  try {
    const j = await rawFetch('PATCH', url, {...d, expect_updated_at: open.updated_at});
    const s = OBS.s[url]; if (s) s.seen = j.updated_at;
    return j;
  } catch (e) {
    if (e.status !== 409 || !e.data?.current) throw e;
    const cur = e.data.current, theirs = Object.keys(now).filter(k => !objSame(open[k], cur[k]));
    return {conflict: {cur, theirs, both: theirs.filter(k => k in d && !objSame(d[k], cur[k]))}};
  }
}
// the merge bar of a 409: the fields someone else changed get .obj-theirs and an outline (title = their value), "Take theirs" fills them in,
// "Keep mine" leaves the input; both make cur the base of the next save (onBase(cur))
/** @param {HTMLElement} md @param {{cur: any, theirs: string[], both: string[]}} cf @param {(cur: any) => void} onBase */
function objMerge(md, cf, onBase) {
  md.querySelector('.obj-merge')?.remove();
  const b = document.createElement('div'); b.className = 'cfbar obj-merge'; b.setAttribute('role', 'alert');
  b.innerHTML = `<span>${esc(tr('Changed by someone else in the meantime'))}</span><button type="button" class="btn sm" data-om="mine">${tr('Keep mine')}</button><button type="button" class="btn sm" data-om="theirs">${tr('Take theirs')}</button>`;
  (md.querySelector('form, .mbody') || md).prepend(b);
  const fs = cf.theirs.map(k => /** @type {HTMLInputElement|null} */ (md.querySelector(`[name="${CSS.escape(k)}"]`)));
  fs.forEach((f, i) => { if (f) { f.classList.add('obj-theirs'); f.style.outline = '2px solid var(--st-wait)'; f.title = tr('Now: {0}', String(cf.cur[cf.theirs[i]] ?? '')); } });
  onBase(cf.cur);
  b.addEventListener('click', e => {
    const a = /** @type {HTMLElement} */ (e.target).closest('[data-om]')?.getAttribute('data-om'); if (!a) return;
    if (a === 'theirs') fs.forEach((f, i) => { if (!f) return; const v = cf.cur[cf.theirs[i]]; if (f.type === 'checkbox') f.checked = !!v; else f.value = v ?? ''; f.dispatchEvent(new Event('input', {bubbles: true})); });
    fs.forEach(f => { if (f) { f.classList.remove('obj-theirs'); f.style.outline = ''; } }); b.remove();
  });
}
// the version watch of an open dialog: when the counter of the app moved (S.v), the object is read again; another updated_at
// than the one the dialog works on = the calm bar "Changed by someone else in the meantime" (saving then shows the merge)
/** @param {HTMLElement} md @param {string} url @param {() => string} base */
function dlgStale(md, url, base) {
  let v = S.v, busy = false;
  const t = setInterval(async () => {
    if (!md.isConnected) { clearInterval(t); return; }
    if (busy || S.v === v) return;
    v = S.v; busy = true;
    try {
      const j = await rawFetch('GET', url);
      if (j.updated_at !== base() && !md.querySelector('.obj-stale')) {
        const b = document.createElement('div'); b.className = 'cfbar obj-stale'; b.setAttribute('role', 'status');
        b.textContent = tr('Changed by someone else in the meantime'); (md.querySelector('form, .mbody') || md).prepend(b);
      }
    } catch { /* gone or no right any more: the save will say it */ } finally { busy = false; }
  }, 4000);
  return () => clearInterval(t);
}
/** @param {HTMLElement} md @param {string} url @param {any} open @param {string} [key] */
function objOpen(md, url, open, key) {
  OBS.s[url] = {tok: objTok(), seen: open.updated_at};
  if (typeof fdDialog === 'function') fdDialog(md, key || url, open.updated_at || '');
  const stop = dlgStale(md, url, () => OBS.s[url]?.seen || open.updated_at);
  if (typeof onRemove === 'function') onRemove(md, () => { stop(); objClose(url); });
}
/** @param {string} url */
function objClose(url) { delete OBS.s[url]; }
/** @param {string} url @param {any} old @param {string} seenAt */
async function undoWrite(url, old, seenAt) {
  return rawFetch('PATCH', url, {...old, expect_updated_at: seenAt});
}
/** @param {string} url @param {string} [op] */
async function objUndo(url, op = 'undo') {
  const s = OBS.s[url]; if (!s) throw new Error(tr('Nothing to undo'));
  const j = await rawFetch('POST', url + '/undo', {sess: s.tok, op});
  s.seen = j.updated_at;
  return j;
}
