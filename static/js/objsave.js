// @ts-check
// 2.558.0 (#4709): the browser side of the shared core's write path (kalmido/core/writes.py, docs/dev/kern.md), loaded on
// demand (lazyload.js LD_MODS objsave). One way for every dialog that saves an object of an area built on the core:
//   objOpen(md, url, open, key)  the dialog md opened with object `open`: unsaved input comes back (formguard fdDialog, base =
//                                its updated_at), an undo session starts for url (header X-Kalmido-Undo, core.js rawFetch0
//                                asks obj_hdr) and dlgStale watches the version: someone else saved meanwhile -> a calm bar
//   saveDialog(url, open, now)   sends ONLY the fields that differ from `open`, with expect_updated_at = open.updated_at ->
//                                the saved object; 409 -> {conflict: {cur, theirs, both}} (objMerge draws the bar: the fields
//                                someone else changed are marked, the next save goes against cur)
//   undoWrite(url, old, seenAt)  an undo as a second write: core.js (2.566.0, #4704: shared by every toast / history undo)
//   objUndo(url, op)             the server's session undo of the dialog (POST <url>/undo, op undo | redo | all | redoall)
//   objSess / objSaved           2.747.0 (#5246): "… saved · Undo" of a dialog that saves once and closes (below)
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
// 2.565.0 (#4705): o (all optional) for the areas not on the core yet (contacts, events; #4712 moves them):
//   o.exp   the body key of the version (default expect_updated_at; contacts / events: expect)
//   o.key   the key of the current state in the 409 answer (default current); missing there -> GET o.get (default url)
//   o.base  what the dialog showed when it opened, in the shape of `now` (its form read once): the diff is taken against it
//           (default `open`); OBJ_MINE in it = a field typed here before a conflict, always sent again
//   o.view  the server's object -> the dialog's shape of `open` (e.g. one date of a series), for the fields someone else changed
//   o.method  the write's method (default PATCH; 2.576.0 (#4794): the bank rules save with PUT)
//   o.send  (body) -> the answer, instead of rawFetch PATCH url (api() with its toasts, an optimistic put)
// the conflict carries `mine` too: the fields typed here, to be put over cur when the dialog is drawn again
const OBJ_MINE = Object.freeze({mine: 1});
// where a bar goes: the dialog's form / body, else its card (a modal() of dialogs.js) under its header line
/** @param {HTMLElement} md @param {HTMLElement} b */
function objBar(md, b) {
  const box = md.querySelector('form, .mbody') || md.querySelector('.card') || md, h = box.querySelector(':scope > .lhdr');
  if (h) h.after(b); else box.prepend(b);
}
/** @param {any} base @param {Record<string, any>} mine */
const objBase = (base, mine) => ({...base, ...Object.fromEntries(Object.keys(mine || {}).map(k => [k, OBJ_MINE]))});
/** @param {string} url @param {any} open @param {any} now @param {any} [o] */
async function saveDialog(url, open, now, o = {}) {
  const d = objDiff(o.base || open, now);
  if (!Object.keys(d).length) return open;
  try {
    const b = {...d, [o.exp || 'expect_updated_at']: open.updated_at};
    const j = await (o.send ? o.send(b) : rawFetch(o.method || 'PATCH', url, b));
    const s = OBS.s[url]; if (s) s.seen = j.updated_at;
    return j;
  } catch (e) {
    const k = o.key || 'current';
    if (e.status !== 409 || (!e.data?.[k] && !o.key)) throw e;
    let raw = e.data?.[k];
    if (!raw) { try { raw = await rawFetch('GET', o.get || url.split('?')[0]); } catch { throw e; } }  // an older server: 409 without the state
    const cur = o.view ? o.view(raw) : raw, theirs = Object.keys(now).filter(x => !objSame(open[x], cur[x]));
    return {conflict: {cur, raw, theirs, mine: d, both: theirs.filter(x => x in d && !objSame(d[x], cur[x]))}};
  }
}
// the merge bar of a 409: the fields someone else changed get .obj-theirs and an outline (title = their value), "Take theirs" fills them in,
// "Keep mine" leaves the input; both make cur the base of the next save (onBase(cur))
// 2.565.0 (#4705): o.field(k) -> the element of field k (default [name=k]; a list of rows: its fieldset); o.take(keys) -> "Take
// theirs" done by the dialog itself (it draws them, e.g. a list of rows) instead of filling the inputs; the bar says in words
// that the marked fields show the current state and what was typed here stays
/** @param {HTMLElement} md @param {{cur: any, theirs: string[], both: string[]}} cf @param {(cur: any) => void} onBase @param {any} [o] */
function objMerge(md, cf, onBase, o = {}) {
  md.querySelector('.obj-merge')?.remove(); md.querySelector('.obj-stale')?.remove();
  const b = document.createElement('div'); b.className = 'cfbar obj-merge'; b.setAttribute('role', 'alert');
  b.innerHTML = `<span>${esc(tr('Changed by someone else in the meantime'))}${o.field ? ` ${esc(tr('The marked fields show the current state; what you typed stays. Check and save again.'))}` : ''}</span><button type="button" class="btn sm" data-om="mine">${tr('Keep mine')}</button><button type="button" class="btn sm" data-om="theirs">${tr('Take theirs')}</button>`;
  objBar(md, b);
  const fs = cf.theirs.map(k => /** @type {HTMLInputElement|null} */ (o.field ? o.field(k) : md.querySelector(`[name="${CSS.escape(k)}"]`)));
  fs.forEach((f, i) => { if (f) { const v = cf.cur[cf.theirs[i]]; f.classList.add('obj-theirs'); f.style.outline = '2px solid var(--st-wait)'; if (v == null || typeof v !== 'object') f.title = tr('Now: {0}', String(v ?? '')); } });
  onBase(cf.cur);
  b.addEventListener('click', e => {
    const a = /** @type {HTMLElement} */ (e.target).closest('[data-om]')?.getAttribute('data-om'); if (!a) return;
    if (a === 'theirs' && o.take) { b.remove(); o.take(cf.theirs); return; }
    if (a === 'theirs') fs.forEach((f, i) => { if (!f) return; const v = cf.cur[cf.theirs[i]]; if (f.type === 'checkbox') f.checked = !!v; else f.value = v ?? ''; f.dispatchEvent(new Event('input', {bubbles: true})); });
    fs.forEach(f => { if (f) { f.classList.remove('obj-theirs'); f.style.outline = ''; } }); b.remove();
  });
}
// 2.576.0 (#4794): the dialogs that save a whole form (the office's rows, the clients): objSaveForm = saveDialog against the
// state the dialog opened (md._objBase / rec._objBase once a conflict reopened it) -> the saved object, null when nothing changed; a conflict
// throws (status 409) and objConflict shows it: the dialog md still open -> the merge bar on it; closed at once (an optimistic
// save) -> again(state) opens it on the current state with the person's changes on top, then the bar. "Keep mine" = the next
// save goes against the current version, "Take theirs" opens it on theirs. -> true when it was such a conflict
/** @param {any} md @param {string} url @param {any} rec @param {any} body @param {string} [method] */
async function objSaveForm(md, url, rec, body, method) {
  const base = md?._objBase || rec?._objBase || rec, j = await saveDialog(url, base, body, {method});
  if (j?.conflict) throw Object.assign(new Error(tr('Changed by someone else in the meantime')), {status: 409, conflict: j.conflict, base, body});
  if (md?._objBase) md._objBase = null;  // saved: the dialog's own state is the base again
  return j === base ? null : j;
}
// 2.576.0 (#4764): field(dialog, k) -> the element of field k, when the dialog's inputs have no name (objMerge o.field)
/** @param {any} md @param {any} x @param {(rec: any) => any} again @param {(m: any, k: string) => any} [field] */
async function objConflict(md, x, again, field) {
  const cf = x?.conflict; if (!cf) return false;
  /** @type {any} */ let m = md?.isConnected ? md : null;
  if (!m) {  // the state to open: theirs with the person's changes; its base (not enumerable: never sent, never spread) = theirs
    const rec = {...cf.cur, ...objDiff(x.base, x.body)}; Object.defineProperty(rec, '_objBase', {value: cf.cur});
    m = await Promise.resolve().then(() => again(rec)).catch(() => null);
  }
  if (!m?.isConnected) { toast(tr('Changed by someone else in the meantime')); return true; }
  objMerge(m, cf, cur => { m._objBase = cur; }, {take: () => { m.remove(); again(cf.cur); }, field: field && (k => field(m, k))});
  return true;
}
// the version watch of an open dialog: when the counter of the app moved (S.v), the object is read again; another updated_at
// than the one the dialog works on = the calm bar "Changed by someone else in the meantime" (saving then shows the merge)
// 2.565.0 (#4705): the server's counter as the poll saw it last (S.vNow, core.js): while one types in the dialog the state is not
// loaded (S.v stays), the bar comes anyway; onTake(cur) given: the bar has "Take over" (the dialog draws the current state with
// what was typed over it, as after a 409)
/** @param {HTMLElement} md @param {string} url @param {() => string} base @param {(cur: any) => void} [onTake] */
function dlgStale(md, url, base, onTake) {
  const vn = () => S.vNow ?? S.v;
  let v = vn(), busy = false;
  const t = setInterval(async () => {
    if (!md.isConnected) { clearInterval(t); return; }
    if (busy || vn() === v) return;
    v = vn(); busy = true;
    try {
      const j = await rawFetch('GET', url);
      if (j.updated_at !== base() && md.isConnected && !md.querySelector('.obj-stale, .obj-merge')) {
        const b = document.createElement('div'); b.className = 'cfbar obj-stale'; b.setAttribute('role', 'status');
        b.innerHTML = `<span>${esc(tr('Changed by someone else in the meantime'))}</span>${onTake ? `<button type="button" class="btn sm" data-os="take">${tr('Apply')}</button>` : ''}`;
        if (onTake) b.querySelector('[data-os]')?.addEventListener('click', () => { b.remove(); onTake(j); });
        objBar(md, b);
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
/** @param {string} url @param {string} [op] @param {string} [tok] */
async function objUndo(url, op = 'undo', tok) {  // 2.747.0 (#5246): tok = the token of a session ended already (objSaved)
  const s = OBS.s[url], t = tok || s?.tok; if (!t) throw new Error(tr('Nothing to undo'));
  const j = await rawFetch('POST', url + '/undo', {sess: t, op});
  if (s) s.seen = j.updated_at;
  return j;
}
// 2.747.0 (#5246): the "… saved · Undo" of a dialog that saves at once and closes (office master data, clients; was
// office_undo.js oun_saved): objSess(url, seen) before the save gives its write the header X-Kalmido-Undo, objSaved(url,
// name, after) after it ends the session and puts ONE entry into the history whose undo / redo is the server's session undo
// (objUndo, op all | redoall); after(j) redraws. false = no session (nothing to show)
/** @param {string} url @param {string} [seen] */
function objSess(url, seen) { OBS.s[url] = {tok: objTok(), seen}; }
/** @param {string} url @param {string} name @param {(j: any) => any} [after] */
function objSaved(url, name, after) {
  const s = OBS.s[url]; if (!s || typeof histAdd !== 'function') return false;
  objClose(url);
  const msg = tr('{0} saved', name || tr('Saved'));
  const run = async (/** @type {string} */ op) => {
    let j; try { j = await objUndo(url, op, s.tok); } catch (x) { toast(/** @type {any} */ (x).message || tr('unknown')); throw x; }
    if (after) await after(j);
    return {skipped: []};
  };
  const e = histAdd({label: msg, ids: [], snaps: [], lids: [], undo: () => run('all'), redo: () => run('redoall')});
  histToast(msg, e, 10000);
  return true;
}
