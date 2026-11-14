// @ts-check
/* Kalmido web client: 2.637.0 (#4745) -- "Offline available" per knowledge space: the device keeps every file of a space
   next to the texts (the texts are offline already, wiki.js wko_*, #2671). Off = as before: files only online.
   - The switch is in the space's menu (wiki.js w299_areaItems). Before it goes on: the files' total and the device's free
     space (navigator.storage.estimate); not enough = a hint, nothing is loaded. navigator.storage.persist() is asked for.
   - The files come in the background, one after the other (GET /api/wiki/files/<id>), with the progress in the space's bar
     (wkoffBar: x of y files, MB), Cancel pauses, Continue goes on; a reload or a lost connection goes on by itself where it
     stopped (the state is in the copy: record o:<space>, "have" = the files kept here with their content's sha256).
   - Where: IndexedDB "kalmido-wiki" (wiki.js wko_idb), store "f" next to the texts' store "c": one record f:<file id> =
     {blob, sp, v, mime, name, uid, g} -- only this sign-in's records are read (uid + sign-in mark me.sgen, as wko_get). NOT the
     service worker's cache (sw.js keeps only the app shell, #2872). Logout / another sign-in / 14 days without a sync empty
     the whole database (icons.js clearLocal, core.js wkoDrop -> wko_wipe / wko_reset).
   - The sync (wiki.js wko_sync, at every online opening of the space, at most once a minute; and when the connection is
     back): GET /api/wiki/space-files lists what the space has now -- new / changed files are fetched, files in the trash,
     of pages in the trash or no longer listed go; 403 / 404 (no right any more) removes the whole copy of the space.
   - Offline (or the server cannot give the file): a click on a file link opens the device's copy (blob address in a new
     tab; an SVG is downloaded, never opened as a page of the app); a picture that fails to load takes it as data: address.
   - A locked space (wikie2e.js) has no files (the server takes none there): no switch.
   - The browser may still clear its storage (no persist): the space then is honestly "not offline" again and says so once
     (LS "wkoff" remembers which spaces were on).
   Classic script sharing the global scope with wiki.js (lazyload.js: module "wiki"). */
'use strict';

const WKOF = {m: {}, ld: {}, run: null, q: [], last: {}, swept: false};  // m: space -> its record o:<space> (or null); run: the space loading now
const WKOF_SYNC_MS = 60e3;
const wkof_store = () => { const st = wko_st(); return st && st.fput ? st : null; };  // a test's stand-in without files = no switch
const wkof_mine = r => !!r && r.uid === S.me?.id && (r.g || '') === (S.me?.sgen || '');
async function wkof_fget(id) { try { const r = await wkof_store()?.fget('f:' + id); return wkof_mine(r) ? r : null; } catch { return null; } }
async function wkof_fdel(id) { try { await wkof_store()?.fdel('f:' + id); } catch { /* gone */ } }
const wkof_sum = (m, done) => (m?.list || []).filter(f => !done || m.have?.[f.id] === f.v).reduce((s, f) => s + (f.size || 0), 0);
const wkof_n = (m, done) => (m?.list || []).filter(f => !done || m.have?.[f.id] === f.v).length;
// the spaces switched on, remembered beside the copy: a copy gone while this still names the space = the browser cleared it
function wkof_flag(sp, on) {
  const f = LS.get('wkoff', null), mine = f && f.u === S.me?.id && f.g === (S.me?.sgen || '') ? f.sps || [] : [];
  const sps = on ? [...new Set([...mine, sp])] : mine.filter(x => x !== sp);
  if (sps.length) LS.set('wkoff', {u: S.me?.id, g: S.me?.sgen || '', sps}); else LS.del('wkoff');
}
const wkof_flagged = sp => { const f = LS.get('wkoff', null); return !!f && f.u === S.me?.id && f.g === (S.me?.sgen || '') && (f.sps || []).includes(sp); };
async function wkof_save(m) { WKOF.m[m.sp] = m; await wko_put(m); }
// the record of a space (once per page load, then from memory); a flagged space without its record: cleared by the browser
async function wkof_meta(sp) {
  if (sp in WKOF.m) return WKOF.m[sp];
  return WKOF.ld[sp] ||= (async () => {
    const m = await wko_get('o:' + sp);
    WKOF.m[sp] = m?.on ? m : null;
    if (!m?.on && wkof_flagged(sp)) { wkof_flag(sp, false); toast(tr('The browser removed the offline files of a knowledge workspace')); }
    delete WKOF.ld[sp];
    return WKOF.m[sp];
  })();
}
// ---- the space's bar and menu
function wkoffBar(sp) {
  if (!wkof_store() || !S.me || S.me.kind === 'agent') return '';
  if (!(sp in WKOF.m)) { wkof_meta(sp).then(m => { if (m) wkof_paint(sp); }); return ''; }
  return wkof_barHtml(sp);
}
function wkof_barHtml(sp) {
  const m = WKOF.m[sp]; if (!m) return '';
  const n = wkof_n(m), d = wkof_n(m, true), run = WKOF.run?.sp === sp;
  let t, btn = '';
  if (d >= n && m.st === 'ok') t = tr('Offline available: {0} · as of {1}', fmtSize(wkof_sum(m, true)), fmtWhen(m.at));
  else if (run) { t = tr('Offline copy: {0} of {1} files · {2} of {3}', d, n, fmtSize(wkof_sum(m, true)), fmtSize(wkof_sum(m))); btn = `<button type="button" class="btn sm" data-wkof="stop">${esc(tr('Cancel'))}</button>`; }
  else if (m.st === 'full') { t = tr('The device storage is full: {0} of {1} files offline', d, n); btn = `<button type="button" class="btn sm" data-wkof="go">${esc(tr('Continue'))}</button>`; }
  else if (m.st === 'pause') { t = tr('Offline copy paused: {0} of {1} files', d, n); btn = `<button type="button" class="btn sm" data-wkof="go">${esc(tr('Continue'))}</button>`; }
  else t = tr('Offline copy waits for a connection: {0} of {1} files', d, n);
  return `<div class="muted mhint wkofbar" role="status" data-sp="${esc(sp)}">${ic(run ? 'sync' : 'download', 's')}<span>${esc(t)}</span>${btn}</div>`;
}
// only the bar is drawn again (the progress comes often); without a bar on screen the whole view once the state changes
function wkof_paint(sp, all) {
  const els = [...document.querySelectorAll('.wkofbar')].filter(e => e.dataset.sp === sp);
  if (els.length && !all) { const h = wkof_barHtml(sp); for (const e of els) e.outerHTML = h; return; }
  if (S.route?.mod === 'wiki' && typeof renderView === 'function') renderView();
}
function wkoffItems(sp) {
  if (!sp || !wkof_store() || !S.me || S.me.kind === 'agent' || wk_e2e(sp)) return [];  // a locked space has no files
  if (!(sp in WKOF.m)) wkof_meta(sp);
  const on = !!WKOF.m[sp];
  return [{label: tr('Offline available'), icon: 'download', on, act: 'offline-available', fn: () => on ? wkof_off(sp) : wkof_on(sp)}];
}
async function wkof_list(sp) { return rawFetch('GET', '/api/wiki/space-files?space=' + encodeURIComponent(sp)); }
async function wkof_on(sp) {
  if (!OUT.online) { toast(tr('Offline: only works again with a connection')); return; }
  let j; try { j = await wkof_list(sp); } catch (e) { toast(e.message); return; }
  if (j.e2e) { toast(tr('This workspace is encrypted: it has no files, its texts are offline already')); return; }
  const est = await navigator.storage?.estimate?.().catch(() => null), free = est && est.quota ? Math.max(0, est.quota - (est.usage || 0)) : null;
  if (free !== null && j.bytes > free * 0.9) {  // a margin: the database stores a bit more than the files
    await wk_info(tr('Not enough space on this device'), esc(tr('The files of this workspace need {0}, only {1} are free on this device.', fmtSize(j.bytes), fmtSize(free))));  // 2.1168.0 (#6092): OK alone
    return;
  }
  const ok = await askConfirm(tr('Keep this workspace offline?'), tr('{0} files, {1}. Free on this device: {2}.', j.files.length, fmtSize(j.bytes), free === null ? tr('unknown') : fmtSize(free)), {ok: tr('Keep offline')});
  if (!ok) return;
  let kept = false; try { kept = !!await navigator.storage?.persist?.(); } catch { /* not offered */ }
  const old = await wko_get('o:' + sp);
  await wkof_save({k: 'o:' + sp, sp, on: true, st: 'load', at: null, list: wkof_slim(j.files), have: old?.have || {}, kept, more: !!j.more});
  wkof_flag(sp, true);
  WKOF.last[sp] = Date.now();
  wkof_paint(sp, true);
  wkof_start(sp);
}
const wkof_slim = fs => fs.filter(f => !f.up?.scan).map(f => ({id: f.id, page_id: f.page_id, name: f.name, mime: f.mime, size: f.size, v: f.v}));  // unchecked / infected: the server gives it to nobody
async function wkof_off(sp) {
  const m = WKOF.m[sp];
  if (!await askConfirm(tr('Remove the offline files?'), tr('Frees {0} on this device. The page texts stay offline as before.', fmtSize(wkof_sum(m, true))), {ok: tr('Remove')})) return;
  await wkof_drop(sp);
  toast(tr('Offline files removed'));
}
// the copy of a space's files goes (switched off, no right any more, the space gone)
async function wkof_drop(sp) {
  if (WKOF.run?.sp === sp) WKOF.run.ac.abort('off');
  WKOF.q = WKOF.q.filter(x => x !== sp);
  const m = WKOF.m[sp] || await wko_get('o:' + sp);
  for (const id of Object.keys(m?.have || {})) await wkof_fdel(id);
  await wko_del('o:' + sp);
  WKOF.m[sp] = null;
  wkof_flag(sp, false);
  wkof_paint(sp, true);
}
// ---- loading: one space at a time, file by file; the state after every file (a reload goes on there)
function wkof_start(sp) {
  if (WKOF.run?.sp === sp || WKOF.q.includes(sp)) return;
  WKOF.q.push(sp);
  if (!WKOF.run) wkof_next();
}
async function wkof_next() {
  const sp = WKOF.q.shift(); if (!sp) return;
  const ac = new AbortController();
  WKOF.run = {sp, ac};
  try { await wkof_load(sp, ac.signal); } catch (e) { console.warn('wiki offline files', e); }
  WKOF.run = null;
  wkof_paint(sp, true);
  wkof_next();
}
async function wkof_load(sp, sig) {
  let m = WKOF.m[sp]; if (!m) return;
  m.st = 'load'; await wkof_save(m); wkof_paint(sp);
  for (const f of [...m.list]) {
    if (sig.aborted || WKO.dead || !S.me) break;
    if (m.have[f.id] === f.v) continue;
    let r;
    try { r = await fetch(f.url || `/api/wiki/files/${f.id}/${encodeURIComponent(f.name)}`, {headers: {'X-Requested-With': 'kalmido'}, signal: sig, credentials: 'same-origin'}); }
    catch (e) { if (sig.aborted) break; m.st = 'wait'; await wkof_save(m); return; }  // the connection went: on again when it is back
    if ([403, 404, 410].includes(r.status)) { m.list = m.list.filter(x => x.id !== f.id); delete m.have[f.id]; await wkof_save(m); continue; }  // gone / no right / locked by the scan
    if (!r.ok || (r.headers.get('content-type') || '').includes('text/html')) { m.st = 'wait'; await wkof_save(m); return; }  // the server is away (or the session: core.js deals with it)
    let blob; try { blob = await r.blob(); } catch { if (sig.aborted) break; m.st = 'wait'; await wkof_save(m); return; }
    m = WKOF.m[sp]; if (!m || sig.aborted) break;  // switched off meanwhile
    try { await wkof_store()?.fput({k: 'f:' + f.id, sp, id: f.id, v: f.v, mime: f.mime, name: f.name, size: blob.size, blob, uid: S.me.id, g: S.me.sgen || ''}); }
    catch (e) { if (e?.name === 'QuotaExceededError') { m.st = 'full'; await wkof_save(m); toast(tr('The device storage is full: the offline copy stopped')); return; } throw e; }
    m.have[f.id] = f.v;
    if (Date.now() - (m._sv || 0) > 1500) { m._sv = Date.now(); await wkof_save(m); }  // the state at most every 1.5 s (a big list is copied each time)
    wkof_paint(sp);
  }
  m = WKOF.m[sp]; if (!m) return;
  await wkof_save(m);
  if (sig.aborted) { if (sig.reason !== 'off') { m.st = 'pause'; await wkof_save(m); } return; }
  if (wkof_n(m, true) >= wkof_n(m)) { m.st = 'ok'; m.at = new Date().toISOString(); await wkof_save(m); }
}
// ---- the sync (wiki.js wko_sync: the space opened online; the connection back)
async function wkoffSync(sp, force) {
  if (!wkof_store() || !OUT.online || !S.me || S.me.kind === 'agent') return;
  const m = await wkof_meta(sp); if (!m) return;
  if (!force && Date.now() - (WKOF.last[sp] || 0) < WKOF_SYNC_MS) return;
  WKOF.last[sp] = Date.now();
  let j;
  try { j = await wkof_list(sp); }
  catch (e) { if ([403, 404].includes(e.status)) { await wkof_drop(sp); toast(tr('The offline files of a knowledge workspace were removed (no access any more)')); } return; }
  if (j.e2e) { await wkof_drop(sp); return; }  // locked meanwhile (it had no files then)
  const cur = WKOF.m[sp]; if (!cur) return;
  const list = wkof_slim(j.files), by = new Map(list.map(f => [f.id, f]));
  for (const id of Object.keys(cur.have)) if (by.get(+id)?.v !== cur.have[id]) { await wkof_fdel(id); delete cur.have[id]; }
  cur.list = list; cur.more = !!j.more;
  const all = wkof_n(cur, true) >= wkof_n(cur);
  if (all) { cur.st = 'ok'; cur.at = new Date().toISOString(); }
  else if (cur.st === 'ok' || cur.st === 'wait') cur.st = 'load';
  await wkof_save(cur);
  if (!all && cur.st === 'load') wkof_start(sp); else wkof_paint(sp);
}
// after a reload / the connection back: every space switched on goes on (a pause by hand waits for Continue)
async function wkof_resume() {
  if (!wkof_store() || !S.me || S.me.kind === 'agent' || !feat('wiki')) return;
  const ms = (await wko_pre('o:')).filter(r => wkof_mine(r) && r.on);
  if (!WKOF.swept && !WKOF.run) {  // once per page load: a file no record of this sign-in keeps (a switch-off cut short, a space gone: wko_sweep)
    WKOF.swept = true;
    const keep = new Set(ms.flatMap(r => Object.keys(r.have || {}).map(id => 'f:' + id)));
    try { for (const k of (await wkof_store()?.fkeys()) || []) if (!keep.has(String(k))) await wkof_store()?.fdel(k); } catch { /* gone */ }
  }
  for (const r of ms) {
    if (!(r.sp in WKOF.m) || WKOF.m[r.sp]) WKOF.m[r.sp] = WKOF.m[r.sp] || r;
    if (!OUT.online) continue;
    if (r.st === 'load' || r.st === 'wait') wkof_start(r.sp); else wkoffSync(r.sp);
  }
  const f = LS.get('wkoff', null);  // remembered as on, the record gone: the browser cleared it
  if (f && f.u === S.me.id && f.g === (S.me.sgen || '')) for (const sp of f.sps || []) await wkof_meta(sp);
}
window.addEventListener('online', () => setTimeout(wkof_resume, 3500));
setTimeout(wkof_resume, 2500);
// ---- offline: the device's copy instead of the server
// the files of a page in the copy (wiki.js wko_page: a page opened offline lists them)
async function wkoffPageFiles(sp, pid) {
  const m = await wkof_meta(sp); if (!m) return [];
  return m.list.filter(f => f.page_id === pid && m.have[f.id] === f.v)
    .map(f => ({id: f.id, page_id: pid, name: f.name, mime: f.mime, size: f.size, url: `/api/wiki/files/${f.id}/${encodeURIComponent(f.name)}`, image: f.mime.startsWith('image/'), _off: true}));
}
const WKOF_RE = /\/api\/wiki\/files\/(\d{1,15})(?:[/?#]|$)/;
const WKOF_MIMES = ['application/pdf', 'image/png', 'image/jpeg', 'image/gif', 'image/webp'];
// a file link: offline (or a page from the copy) opens the device's copy; an SVG is downloaded, never shown as a page here
document.addEventListener('click', e => {
  const a = /** @type {HTMLAnchorElement|null} */ (/** @type {Element} */ (e.target)?.closest?.('a[href*="/api/wiki/files/"]'));
  const id = a && (a.getAttribute('href') || '').match(WKOF_RE)?.[1];
  if (!id || (OUT.online && !WK.pg?._off) || e.defaultPrevented) return;
  e.preventDefault();
  const w = window.open('', '_blank');  // now, in the click (a window opened after the database answered is blocked)
  if (w) try { w.opener = null; } catch { /* closed */ }
  wkof_fget(+id).then(r => {
    if (!r?.blob) { w?.close(); toast(tr('Offline: only works again with a connection')); return; }
    const svg = !WKOF_MIMES.includes(r.mime), url = URL.createObjectURL(new Blob([r.blob], {type: svg ? 'application/octet-stream' : r.mime}));
    if (w && !svg) w.location.href = url;
    else { w?.close(); const d = document.createElement('a'); d.href = url; d.download = r.name || 'file'; document.body.appendChild(d); d.click(); d.remove(); }
    setTimeout(() => URL.revokeObjectURL(url), 60e3);
  });
}, true);
// a picture of a page that did not load (offline, server away): the copy's as a data: address (the app's CSP has no blob: for pictures)
document.addEventListener('error', e => {
  const img = /** @type {HTMLImageElement} */ (e.target);
  if (img?.tagName !== 'IMG' || img.dataset.wkof) return;
  const id = (img.getAttribute('src') || '').match(WKOF_RE)?.[1]; if (!id) return;
  img.dataset.wkof = '1';
  wkof_fget(+id).then(async r => {
    if (!r?.blob) return;
    const b = new Uint8Array(await r.blob.arrayBuffer()); let s = '';
    for (let i = 0; i < b.length; i += 0x8000) s += String.fromCharCode(...b.subarray(i, i + 0x8000));
    img.src = `data:${r.mime && r.mime.startsWith('image/') ? r.mime : 'application/octet-stream'};base64,${btoa(s)}`;
  }).catch(() => {});
}, true);
document.addEventListener('click', e => {
  const b = /** @type {Element} */ (e.target)?.closest?.('[data-wkof]'); if (!b) return;
  const sp = b.closest('.wkofbar')?.getAttribute('data-sp'); if (!sp) return;
  if (b.getAttribute('data-wkof') === 'stop') { if (WKOF.run?.sp === sp) WKOF.run.ac.abort('pause'); else if (WKOF.q.includes(sp)) { WKOF.q = WKOF.q.filter(x => x !== sp); const m = WKOF.m[sp]; if (m) { m.st = 'pause'; wkof_save(m).then(() => wkof_paint(sp)); } } }
  else if (b.getAttribute('data-wkof') === 'go') { if (!OUT.online) { toast(tr('Offline: only works again with a connection')); return; } wkof_start(sp); }
});
