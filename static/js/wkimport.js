// @ts-check
/* Kalmido web client: 2.177.0 (#2685) -- the ZIP import of knowledge pages for large archives (wiki.js wk_import).
   - The size is checked here before anything is sent (the server's limit in MB), then the ZIP goes up in pieces
     (PUT /api/wiki/import/upload/<id>?offset=, server: kalmido/admin/wkimport.py) with a progress bar "x of y MB";
     the server unpacks it in the background ("x of y files"). Cancel stops either; nothing of a stopped import stays.
   - "In the background" closes the window: the upload goes on while Kalmido is open, the unpacking on the server also
     when it is closed. The result (pages, files, skipped with their reason, one Undo step) comes as a message once it is
     done -- or the next time the knowledge pages open.
   - A locked space imports in the browser (wikie2e.js wkeImport) with the same window ("x of y pages").
   Classic script sharing the global scope with wiki.js (lazyload.js: module "wiki"). */
'use strict';

const WKI = {/** @type {any} */ lim: null, /** @type {any} */ cur: null, up: '', t: 0, /** @type {any} */ md: null, seen: ''};
const WKI_MB = 1048576;

async function wki_limits() {
  if (!WKI.lim) { const j = await rawFetch('GET', '/api/wiki/import/upload'); WKI.lim = {chunk: j.chunk, max_mb: j.max_mb, file_mb: j.file_mb}; }
}
// the window: a bar, one line what happens, Cancel + In the background (or OK at the end)
function wki_sheet() {
  if (WKI.md?.isConnected) return WKI.md;
  /** @type {any} */
  const md = modal(`<h3>${esc(tr('Import'))}</h3><div class="wki-box" role="status" aria-live="polite"></div>
    <div class="foot"><button type="button" class="btn" data-wki="stop">${esc(tr('Cancel'))}</button><button type="button" class="btn pri" data-wki="bg">${esc(tr('In the background'))}</button></div>`);
  md.addEventListener('click', async e => {
    const b = /** @type {HTMLElement|null} */ (/** @type {HTMLElement} */ (e.target).closest('[data-wki]')); if (!b) return;
    if (b.dataset.wki === 'bg') modalClose(md);
    else if (b.dataset.wki === 'stop') { md.remove(); await wki_stop(); }
  });
  // 2.350.0 C (#2744): a click next to the window / Esc while the import runs = "In the background" with the note (no silent close)
  md._close = () => {
    md.remove(); if (wki_pct() === null) return;
    toast((WKI.cur?.state === 'upload' ? tr('The import goes on in the background. Keep Kalmido open until the upload is done.') : tr('The import goes on in the background.'))
      + ' ' + tr('Its progress shows at Knowledge in the bar and on top of the knowledge pages.'), null, 6000);
  };
  WKI.md = md;
  return md;
}
// 2.350.0 C (#2744): the running import's share in percent (null: none runs) for the note at Knowledge in the bar and on top
// of the knowledge pages; a click there opens the window again (also after a reload: wki_resume, and for a locked space)
function wki_pct() {
  const c = WKI.cur; if (!c || !['upload', 'running', 'e2e'].includes(c.state)) return null;
  const [d, t] = c.state === 'upload' ? [c.received, c.size] : c.state === 'e2e' ? [c.done, c.total] : [c.progress?.done, c.progress?.total];
  return t ? Math.max(0, Math.min(99, Math.floor(100 * (d || 0) / t))) : 0;
}
const wki_label = () => tr('Import running · {0} %', wki_pct());
function wki_statHtml() {
  return wki_pct() === null ? '' : `<button type="button" class="wki-st" data-wki-open="1" aria-haspopup="dialog">${botBusy(`<span class="wki-stt">${esc(wki_label())}</span>`)}</button>`;
}
const wki_dotHtml = () => wki_pct() === null ? '' : `<span class="srbd wki-dot" data-wki-open="1" title="${esc(wki_label())}">${wki_pct()} %</span>`;
// the note follows the progress in place (a redraw draws it with viewWiki / sbb_btnHtml)
function wki_mark() {
  const on = wki_pct() !== null;
  for (const b of $$('#srail [data-sbb="wiki"], #side [data-sbb="wiki"], #side [data-go="wiki"], #tabs [data-go="wiki"]')) {
    const s = $('.wki-dot', b);
    if (!on) s?.remove();
    else if (s) { s.textContent = wki_pct() + ' %'; s.title = wki_label(); }
    else b.insertAdjacentHTML('beforeend', wki_dotHtml());
  }
  const w = $('#view .wkwrap'), st = w && $('.wki-st', w);
  if (!on) st?.remove();
  else if (st) { const t = $('.wki-stt', st); if (t) t.textContent = wki_label(); }
  else if (w) w.insertAdjacentHTML('afterbegin', wki_statHtml());
}
function wki_open() {
  const c = WKI.cur; if (wki_pct() === null) return;
  wki_sheet();
  if (c.state === 'e2e') wki_show(c.done || 0, c.total || 0, c.total ? tr('{0} of {1} pages', c.done || 0, c.total) : tr('Unpacking…'));
  else wki_draw(c);
}
document.addEventListener('click', e => {
  const b = /** @type {HTMLElement} */ (e.target).closest?.('[data-wki-open]'); if (!b) return;
  e.preventDefault(); e.stopPropagation(); wki_open();
}, true);
// done / total with a line; total 0 = not known yet
function wki_show(done, total, line) {
  const box = WKI.md?.isConnected && $('.wki-box', WKI.md); if (!box) return;
  box.innerHTML = `<div class="umzbar">${botBusy(`<div class="muted">${esc(line)}</div><progress max="${total || 1}" value="${total ? done || 0 : 0}"></progress>`)}</div>`;
}
function wki_line(j) {
  if (j.state === 'upload') return tr('Uploading: {0} of {1}', fmtSize(j.received || 0), fmtSize(j.size || 0));
  const p = j.progress || {};
  return p.total ? tr('Unpacking: {0} of {1} files', p.done || 0, p.total) : tr('Unpacking…');
}
function wki_draw(j) {
  if (!j) return;
  wki_mark();  // 2.350.0 C (#2744)
  if (j.state === 'upload') wki_show(j.received, j.size, wki_line(j));
  else wki_show(j.progress?.done, j.progress?.total, wki_line(j));
}
// non-locked spaces: the size first, then the pieces
async function wki_start(sp, file, replace = false) {
  try { await wki_limits(); } catch (e) { toast(e.message); return; }
  if (WKI.cur && ['upload', 'running'].includes(WKI.cur.state)) { toast(tr('An import is already running')); return; }
  if (file.size > WKI.lim.max_mb * WKI_MB) { wki_tooBig(file, WKI.lim.max_mb); return; }
  let j;
  try { j = await rawFetch('POST', '/api/wiki/import/upload', {size: file.size, name: file.name, space: sp, replace}); }
  catch (e) { if (!e.shown) toast(e.message); return; }
  const id = j.id, chunk = j.chunk; let off = 0, fails = 0;
  const pause = async ms => { await new Promise(res => setTimeout(res, ms)); return WKI.up === id; };
  WKI.up = id; WKI.cur = {id, state: 'upload', size: file.size, received: 0, space: sp};
  wki_sheet(); wki_draw(WKI.cur);
  while (off < file.size) {
    if (WKI.up !== id) return;  // cancelled
    const part = file.slice(off, Math.min(file.size, off + chunk));
    let r;
    try { r = await fetch(`/api/wiki/import/upload/${id}?offset=${off}`, {method: 'PUT', body: part, headers: {'X-Requested-With': 'kalmido', 'Content-Type': 'application/octet-stream'}}); }
    catch { r = null; }
    j = r ? await r.json().catch(() => ({})) : {};
    // a lost connection / a server in a restart: the same piece again, waiting longer each time (review L4: at most ~20 min)
    if (!r || [502, 503, 504].includes(r.status)) {
      if (++fails > 25) { wki_fail(tr('Offline: only works again with a connection')); return; }
      if (fails === 1) toast(tr('Offline: only works again with a connection'));
      if (!await pause(Math.min(60000, 2000 * 2 ** Math.min(fails, 5)))) return;
      continue;
    }
    if (!r.ok) {
      if (r.status === 409 && typeof j.received === 'number') { off = j.received; continue; }
      // review M3: all import places of the server are taken -- the last piece waits and goes again (nothing is lost)
      if (r.status === 429 && fails++ < 60) { wki_show(off, file.size, j.error || httpErrText(r.status)); if (!await pause(30000)) return; continue; }
      wki_fail(j.error || httpErrText(r.status)); return;
    }
    fails = 0;
    off += part.size;
    WKI.cur = j; wki_draw(j);
  }
  WKI.up = '';
  wki_poll();
}
function wki_fail(msg) {
  WKI.up = ''; WKI.cur = null; wki_mark(); if (WKI.md?.isConnected) modalClose(WKI.md);
  toast(msg);
}
function wki_tooBig(file, max) {
  const md = modal(`<h3>${esc(tr('Import'))}</h3><p>${esc(tr('{0} is {1}, the import takes ZIP files up to {2} MB.', file.name, fmtSize(file.size), max))}</p>
    <p class="muted">${esc(tr('Split the archive into several ZIP files and import them one after the other.'))}</p>
    <div class="foot"><button type="button" class="btn" data-m="close">${esc(tr('OK'))}</button></div>`);
  md.addEventListener('click', e => { if (/** @type {HTMLElement} */ (e.target).closest('[data-m="close"]')) modalClose(md); });
}
async function wki_stop() {
  const c = WKI.cur; WKI.up = '';
  if (c?.state === 'e2e') { c.abort = true; return; }  // the browser import stops after its current page
  if (!c?.id) return;
  try { await rawFetch('DELETE', `/api/wiki/import/upload/${c.id}`); } catch { /* gone already */ }
  if (c.state === 'upload') { WKI.cur = null; wki_mark(); toast(tr('Import cancelled')); }
  else wki_poll();  // a running import stops at its next file: its end comes as "stopped"
}
// the server's state every 1.5 s while it runs (also with the window closed and in other views)
function wki_poll() {
  clearTimeout(WKI.t);
  const c = WKI.cur; if (!c?.id) return;
  WKI.t = setTimeout(async () => {
    let j; try { j = await rawFetch('GET', `/api/wiki/import/upload/${c.id}`); } catch (e) { if (e?.status === 404) { WKI.cur = null; wki_mark(); return; } wki_poll(); return; }
    WKI.cur = j;
    if (j.state === 'running') { wki_draw(j); wki_poll(); return; }
    wki_end(j);
  }, 1500);
}
// the end: the report (wiki.js wka_done: pages, files, skipped with reasons, one Undo step), the folder on the server goes
function wki_end(j) {
  if (WKI.seen === j.id) return; WKI.seen = j.id;
  WKI.cur = null; wki_mark(); if (WKI.md?.isConnected) modalClose(WKI.md);
  rawFetch('DELETE', `/api/wiki/import/upload/${j.id}`).catch(() => {});
  if (j.state === 'done' && j.result) wka_done(j.space || 'private', j.result);
  else if (j.state === 'stopped') toast(tr('Import cancelled'));
  else toast(j.error || tr('The import failed.'));
}
// after a reload / the next opening of the knowledge pages: a running import is followed again, a finished one reported
function wki_resume() {
  if (WKI.cur || WKI.up) return;
  rawFetch('GET', '/api/wiki/import/upload').then(j => {
    WKI.lim = {chunk: j.chunk, max_mb: j.max_mb, file_mb: j.file_mb};
    const c = j.current; if (!c || WKI.cur) return;
    if (c.state === 'upload') { rawFetch('DELETE', `/api/wiki/import/upload/${c.id}`).catch(() => {}); return; }  // the file is not here any more
    WKI.cur = c;
    if (c.state === 'running') { wki_mark(); wki_poll(); } else wki_end(c);
  }).catch(() => {});
}
// a locked space: the browser imports (wikie2e.js wkeImport) with the same window
async function wki_e2e(sp, file) {
  if (file.size > WKE_ZIP.zip) { wki_tooBig(file, Math.floor(WKE_ZIP.zip / 1e6)); return null; }
  if (WKI.cur) { toast(tr('An import is already running')); return null; }
  const cur = WKI.cur = {state: 'e2e', abort: false, done: 0, total: 0};
  wki_sheet(); wki_show(0, 0, tr('Unpacking…')); wki_mark();
  try {
    const r = await wkeImport(sp, file, (done, total) => { Object.assign(cur, {done, total}); wki_show(done, total, tr('{0} of {1} pages', done, total)); wki_mark(); return !cur.abort; });  // 2.350.0 C (#2744): + the note
    if (!cur.abort) return r;
    // review L7: a cancelled import leaves nothing behind -- the pages made so far go to the trash
    if (r?.created?.length) await rawFetch('POST', '/api/wiki/trash', {ids: r.created, files: []}).catch(() => {});
    wk_after(sp); toast(tr('Import cancelled'));
    return null;
  } finally { WKI.cur = null; wki_mark(); if (WKI.md?.isConnected) modalClose(WKI.md); }
}
wki_resume();
