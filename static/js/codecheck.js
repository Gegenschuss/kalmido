// @ts-check
/* Kalmido web client: Settings > Help > Check code (2.766.0, #5220, code integrity stage 3). Loaded on demand (lazyload.js
   LD_MODS codecheck) when the section's button is pressed or the hint of the service worker leads here (upbar.js).

   ONE hash recipe with the release: the browser takes the web manifest of the server (GET /api/code-manifest, stage 1,
   kalmido/core/codemanifest.py), hashes every file of it that lies in its own shell cache (the bytes it was given, crypto.subtle)
   and puts ITS hash in place of the server's. The result is written exactly as cm_json does (ckvJson) and hashed once more:
   that SHA-256 is the line web-manifest-X.Y.Z.json in SHA256SUMS of the GitHub release of that version, as long as every
   file this browser holds is the published one. A file not in the cache keeps the server's value and is named "not checked".
   Nothing is fetched from GitHub (CSP connect-src stays 'self'); the release is only a link.
   Honest limit: the page and this check come from the same server as the code. They catch mistakes and slips, not an operator
   who means to deceive (docs/CODE-VERIFY.md: the manual way and the check from outside). */
'use strict';

const CKV_REPO = 'https://github.com/Gegenschuss/kalmido';
const ckvHex = (/** @type {ArrayBuffer} */ b) => [...new Uint8Array(b)].map(x => x.toString(16).padStart(2, '0')).join('');
const ckvSha = async (/** @type {BufferSource} */ d) => ckvHex(await crypto.subtle.digest('SHA-256', d));
// the manifest as bytes, the recipe of kalmido/core/codemanifest.py cm_json (json.dumps indent=0, ensure_ascii=False, sorted
// files, one entry per line, a newline at the end)
function ckvJson(/** @type {number} */ v, /** @type {string} */ version, /** @type {Record<string, string>} */ files) {
  const q = (/** @type {string} */ s) => JSON.stringify(String(s)), ks = Object.keys(files).sort((a, b) => a < b ? -1 : a > b ? 1 : 0);
  return `{\n"v": ${v},\n"version": ${q(version)},\n"algo": "sha256",\n"files": {\n${ks.map(k => `${q(k)}: ${q(files[k])}`).join(',\n')}\n}\n}\n`;
}
// the newest shell cache of the service worker whose install finished (sw.js SW_DONE), else the newest one, else null
async function ckvCache() {
  if (!globalThis.caches) return null;
  const ks = (await caches.keys()).map(k => ({k, n: +(/^tasks-shell-v(\d+)$/.exec(k) || [])[1]})).filter(x => x.n >= 0).sort((a, b) => b.n - a.n);
  for (const {k} of ks) { const c = await caches.open(k); if (await c.match('/sw-install-done')) return c; }
  return ks.length ? caches.open(ks[0].k) : null;
}
// {url: sha256 of the bytes this browser holds} for every file of the manifest in the cache. A copy kept under another
// ?v= (another version's file) does not count; a copy without ?v= (the app page) does.
async function ckvLocal(/** @type {Cache | null} */ c, /** @type {Record<string, string>} */ files) {
  /** @type {Record<string, string>} */ const got = {};
  if (!c) return got;
  for (const req of await c.keys()) {
    const u = new URL(req.url), want = files[u.pathname], v = u.searchParams.get('v') || '';
    if (u.origin !== location.origin || !want || (v && !want.startsWith(v))) continue;
    if (got[u.pathname] && !v) continue;  // a copy named by its hash beats one without
    const r = await c.match(req);
    if (r) got[u.pathname] = await ckvSha(await r.arrayBuffer());
  }
  return got;
}
// -> {version, v, hash, server, same, checked, bad: [urls], unchecked, total}; throws when the server has no manifest
async function ckvRun() {
  const r = await fetch('/api/code-manifest', {cache: 'no-store', credentials: 'same-origin'});
  if (!r.ok || !/json/.test(r.headers.get('content-type') || '')) throw new Error(tr('This server has no code manifest (before 2.742.0).'));
  const raw = await r.arrayBuffer(), man = JSON.parse(new TextDecoder().decode(raw)), files = man.files || {};
  const got = await ckvLocal(await ckvCache(), files), mine = {...files, ...got};
  const body = new TextEncoder().encode(ckvJson(man.v, man.version, mine));
  const bad = Object.keys(got).filter(u => got[u] !== files[u]).sort();
  const hash = await ckvSha(body), server = await ckvSha(raw);
  // nothing differs, yet the bytes do: the recipe here and the server's are not the same (a fault of this check, not of the code)
  return {version: String(man.version || ''), v: man.v, hash, server, same: !bad.length ? hash === server : true, checked: Object.keys(got).length,
    bad, unchecked: Object.keys(files).length - Object.keys(got).length, total: Object.keys(files).length};
}
function ckvHtml(/** @type {any} */ x) {
  const rel = `${CKV_REPO}/releases/tag/v${encodeURIComponent(x.version)}`, old = typeof APP_VER === 'string' && APP_VER && APP_VER !== x.version;
  const ok = !x.bad.length && x.same;
  return `<div class="row"><label>${tr('Version')}</label><span>v${esc(x.version)}${old ? ` · <b>${esc(tr('This window runs v{0}: reload first', APP_VER))}</b>` : ''}</span></div>
    <div class="row"><label>${tr('Hash of the code')}</label><span class="cchash"><code id="s-cc-hash" translate="no">${esc(x.hash)}</code> <button type="button" class="btn sm" data-ccv="copy">${ic('copy', 's')} ${tr('Copy hash')}</button></span></div>
    <div class="row"><label>${tr('Result')}</label><span id="s-cc-sum" data-ok="${ok ? 1 : 0}">${ok ? esc(trn("{0} file in this browser checked: it matches the server's list.", "{0} files in this browser checked: all match the server's list.", x.checked))
      : x.bad.length ? `<b>${esc(trn("{0} file in this browser differs from the server's list:", "{0} files in this browser differ from the server's list:", x.bad.length))}</b> <span translate="no">${x.bad.slice(0, 12).map(esc).join(', ')}${x.bad.length > 12 ? ' …' : ''}</span>`
      : `<b>${esc(tr("The hash here and the server's manifest differ although every checked file matches: please report it."))}</b>`}
      ${x.unchecked ? ` <span class="muted">${esc(trn("{0} file is not in this browser and was not checked (the server's value is used).", "{0} files are not in this browser and were not checked (the server's values are used).", x.unchecked))}</span>` : ''}</span></div>
    <div class="row"><label></label><span><a class="btn sm" id="s-cc-rel" href="${esc(rel)}" target="_blank" rel="noopener noreferrer">${ic('link', 's')} ${esc(tr('Release v{0} on GitHub', x.version))}</a> <a class="btn sm" href="${CKV_REPO}/blob/main/docs/CODE-VERIFY.md" target="_blank" rel="noopener noreferrer">${ic('help', 's')} ${tr('Guide')}</a></span></div>
    <div class="shint">${esc(tr('How to compare: open the release of this version, download SHA256SUMS and find the line web-manifest-{0}.json. Its hash and the one above are the same when this browser holds the published code. Only the version of each week has a release; for the others, build the manifest from the tagged source (guide).', x.version))}</div>`;
}
// the button "Check code" of Settings > Help (settings.js): fills #s-cc-res
async function ckvCheck(/** @type {ParentNode} */ md) {
  const box = /** @type {HTMLElement | null} */ (md.querySelector('#s-cc-res')), btn = /** @type {HTMLButtonElement | null} */ (md.querySelector('[data-ccv="run"]'));
  if (!box) return null;
  if (btn) btn.disabled = true;
  box.innerHTML = `<div class="muted">${tr('Checking…')}</div>`;
  try {
    const x = await ckvRun();
    box.innerHTML = ckvHtml(x); box.dataset.hash = x.hash;
    return x;
  } catch (e) {
    box.innerHTML = `<div class="muted">${esc(/** @type {any} */ (e)?.message || tr('Not possible right now'))}</div>`;
    return null;
  } finally { if (btn) btn.disabled = false; }
}
async function ckvCopy(/** @type {ParentNode} */ md) {
  const h = /** @type {HTMLElement | null} */ (md.querySelector('#s-cc-res'))?.dataset.hash || '';
  if (h) toast(await clipCopy(h) ? tr('Hash copied') : h);
}
