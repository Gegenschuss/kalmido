// @ts-check
/* Kalmido web client: locked folders of the file store (2.353.0 A, #2758). Classic script sharing the global scope (load
   order: index.html, after ablage.js and wikie2e.js). Server side kalmido/files/fslock.py (the formats are described there). */
'use strict';

// lock id = the id of the locked folder. info: GET /api/files/lock/<id>; keys: {gen: CryptoKey} once the encryption is unlocked
const FSL = {info: {}, keys: {}, tried: {}, memo: new Map(), busy: {}, auto: {}, q: '', wait: {}, aad: {}, find: /** @type {any} */ (null), rot: {}};  // rot: {lock id: true} = a key change waits for the button (2.953)  // wait: {lock id: [{user_id, name}]} (2.353.0 F); aad: #4300
const FSL_HEAD = 9;
const fslIs = v => typeof v === 'string' && v.startsWith('e2e1:');
// #4300: an imported folder stays bound to its id on the server it was locked on (known from fslInfo, before any key of the folder)
const fslBound = lid => FSL.aad[lid] || lid;
const fslNameAad = (lid, g) => `kalmido-fsname:v1:${fslBound(lid)}:${g}`;
const fslFileAad = (lid, g) => `kalmido-fsfile:v1:${fslBound(lid)}:${g}`;
const fslWrapAad = (lid, gen, r, w) => `kalmido-fslockkey:v1:${fslBound(lid)}:${gen}:${r}:${w}`;
function fslErr(msg, code) { const e = /** @type {any} */ (new Error(msg)); e.code = code; return e; }
const fslErrLocked = () => fslErr(tr('Unlock first: this folder is encrypted in the browser.'), 'fs_lock_locked');
const fslOk = () => !!globalThis.crypto?.subtle && typeof e2eSeal === 'function';

// ------------------------------------------------------------------ folder keys (the protocol of the knowledge spaces, own salt / AAD)
async function fslKek(pub, lid, gen) {
  const pk = await crypto.subtle.importKey('jwk', {kty: 'EC', crv: 'P-256', x: pub.x, y: pub.y}, {name: 'ECDH', namedCurve: 'P-256'}, false, []);
  const bits = await crypto.subtle.deriveBits({name: 'ECDH', public: pk}, E2E.priv, 256);
  let hk; try { hk = await crypto.subtle.importKey('raw', bits, 'HKDF', false, ['deriveKey']); } finally { new Uint8Array(bits).fill(0); }
  return crypto.subtle.deriveKey({name: 'HKDF', hash: 'SHA-256', salt: e2eTEnc().encode(`fslock:${fslBound(lid)}:${gen}`), info: e2eTEnc().encode('kalmido-fslockkey:v1')}, hk, {name: 'AES-GCM', length: 256}, false, ['encrypt', 'decrypt']);
}
const fslWrap = async (raw, lid, gen, uid, pub) => e2eSeal(await fslKek(pub, lid, gen), raw, fslWrapAad(lid, gen, uid, S.me.id));
const fslName = (lid, uid) => (FSL.info[lid]?.members || []).find(m => m.user_id === uid)?.name || personNameAny?.(uid) || '?';
// my key of a generation (wrapped by me: my own public key, never the server's copy; by someone else: the key this browser remembered;
// #4300: wrapped by someone on the old server: no person here, remembered per copy; fslKeys then wraps it for me, so it is pinned to my own key)
async function fslRaw(lid, k) {
  const w = k.wrapped_by, me = S.me.id;
  let pub;
  if (w === me) pub = E2E.own;
  else { pub = k.wrapper_pub; if (!le2eSeenOk(w ?? `fsl:${lid}:${k.gen}:${k.aad_w}`, pub)) throw fslErr(tr('The key of {0} has changed. Compare the safety number before you continue.', fslName(lid, w)), 'fs_lock_keychanged'); }
  const wr = typeof k.wrapped === 'string' ? JSON.parse(k.wrapped) : k.wrapped;
  return e2eOpen(await fslKek(pub, lid, k.gen), wr, fslWrapAad(lid, k.gen, k.aad_r ?? me, k.aad_w ?? w));  // #4300: the ids of an imported copy
}
async function fslInfo(lid, force) {
  if (!force && FSL.info[lid]) return FSL.info[lid];
  const j = await rawFetch('GET', `/api/files/lock/${lid}`);
  FSL.info[lid] = j;
  if (j.aad_id) FSL.aad[lid] = j.aad_id;
  for (const m of j.members || []) if (m.pub && m.user_id !== S.me?.id) le2eSeenOk(m.user_id, m.pub);
  return j;
}
// every generation of this folder I hold, unwrapped (only while the encryption is unlocked); ask: unlock first (passphrase)
async function fslKeys(lid, ask) {
  const have = FSL.keys[lid] || (FSL.keys[lid] = {});
  if (ask && typeof e2eUnlocked === 'function' && !e2eUnlocked() && !await e2eEnsure()) throw fslErrLocked();
  if (typeof e2eUnlocked !== 'function' || !e2eUnlocked() || !S.me) return have;
  let info; try { info = await fslInfo(lid, !have[FSL.info[lid]?.gen]); } catch { return have; }
  for (const k of info.keys || []) {
    if (have[k.gen]) continue;
    try {
      const raw = await fslRaw(lid, k);
      if (k.wrapped_by == null && k.aad_w != null) {  // #4300: a copy from the old server becomes my own (the server cannot swap its wrapper any more)
        try { await rawFetch('POST', `/api/files/lock/${lid}/keys`, {keys: [{user_id: S.me.id, gen: k.gen, wrapped: await fslWrap(raw, lid, k.gen, S.me.id, E2E.own)}]}); } catch { /* the next visit tries again, the pin above holds */ }
      }
      have[k.gen] = await le2eImport(raw);
    } catch { /* a changed key or a broken wrap */ }
  }
  return have;
}
async function fslKey(lid, g, ask = true) {
  let k = FSL.keys[lid]?.[g];
  if (!k) k = (await fslKeys(lid, ask))[g];
  if (!k) throw fslErr(tr('You do not have the key of this folder yet.'), 'fs_lock_key');
  return k;
}
const fslGen = lid => FSL.info[lid]?.gen || 0;

// ------------------------------------------------------------------ names and files
async function fslNameEnc(lid, name, gen) {
  const g = gen || fslGen(lid) || (await fslInfo(lid, true)).gen, key = await fslKey(lid, g);
  const b = await e2eSeal(key, le2ePad(e2eTEnc().encode(String(name).slice(0, 150))), fslNameAad(lid, g));
  const c = 'e2e1:' + JSON.stringify({v: 1, g, iv: b.iv, ct: b.ct});
  FSL.memo.set(c, String(name).slice(0, 150));
  return c;
}
async function fslNameDec(lid, c, ask) {
  if (!fslIs(c)) return c;
  if (FSL.memo.has(c)) return FSL.memo.get(c);
  const o = le2eParse(c); if (!o) throw fslErr(tr('Cannot be decrypted'), 'fs_lock_bad');
  const key = await fslKey(lid, o.g, ask);
  const s = e2eTDec().decode(le2eUnpad(await e2eOpen(key, {v: 1, iv: o.iv, ct: o.ct}, fslNameAad(lid, o.g))));
  FSL.memo.set(c, s);
  return s;
}
async function fslFileEnc(lid, f, gen) {
  const g = gen || fslGen(lid) || (await fslInfo(lid, true)).gen, key = await fslKey(lid, g);
  const data = f.data || new Uint8Array(await f.arrayBuffer());
  const head = e2eTEnc().encode(JSON.stringify({name: f.name || 'file', type: f.type || 'application/octet-stream', size: data.length}));
  const plain = new Uint8Array(4 + head.length + data.length);
  new DataView(plain.buffer).setUint32(0, head.length); plain.set(head, 4); plain.set(data, 4 + head.length);
  const iv = e2eRand(12), ct = new Uint8Array(await crypto.subtle.encrypt({name: 'AES-GCM', iv, additionalData: e2eTEnc().encode(fslFileAad(lid, g))}, key, plain));
  const out = new Uint8Array(FSL_HEAD + 12 + ct.length);
  out.set([0x4b, 0x45, 0x4e, 0x43, 0x02]); new DataView(out.buffer).setUint32(5, g); out.set(iv, FSL_HEAD); out.set(ct, FSL_HEAD + 12);
  return out;
}
async function fslFileDec(lid, buf) {
  const u = new Uint8Array(buf);
  if (u.length < FSL_HEAD + 28 || String.fromCharCode(...u.subarray(0, 4)) !== 'KENC' || u[4] !== 2) throw fslErr(tr('Cannot be decrypted'), 'fs_lock_bad');
  const g = new DataView(u.buffer, u.byteOffset).getUint32(5), key = await fslKey(lid, g);
  const plain = new Uint8Array(await crypto.subtle.decrypt({name: 'AES-GCM', iv: u.subarray(FSL_HEAD, FSL_HEAD + 12), additionalData: e2eTEnc().encode(fslFileAad(lid, g))}, key, u.subarray(FSL_HEAD + 12)));
  const n = new DataView(plain.buffer).getUint32(0), head = JSON.parse(e2eTDec().decode(plain.subarray(4, 4 + n)));
  return {name: String(head.name || 'file'), type: String(head.type || 'application/octet-stream'), data: plain.subarray(4 + n)};
}
const FSL_TYPES = {pdf: 'application/pdf', png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', gif: 'image/gif', webp: 'image/webp', avif: 'image/avif', txt: 'text/plain', md: 'text/markdown', csv: 'text/csv'};
const fslTypeOf = name => FSL_TYPES[(/\.([a-z0-9]{1,5})$/i.exec(name || '') || [])[1]?.toLowerCase()] || 'application/octet-stream';

// a node of a listing: its plain name (the server sends the cipher; without the key a placeholder, _sealed)
async function fslPrepNode(n, ask) {
  if (!n || !n.locked || !fslIs(n.name)) return n;
  n._cname = n.name; n._enc = true;
  try { n.name = await fslNameDec(n.lock_id, n.name, ask); if (n.kind === 'file') n.mime = fslTypeOf(n.name); delete n._sealed; }
  catch { n.name = tr('Encrypted'); n._sealed = true; }
  return n;
}
// an answer of GET /api/files (items, node, crumbs): names decrypted in place, no passphrase asked (the banner offers it)
async function fsl_prep(j) {
  if (!j || !fslOk()) return j;
  const all = [...(j.items || []), j.node, ...(j.crumbs || []).map(c => ({...c, _crumb: c}))].filter(Boolean);
  const lock = j.node?.locked ? j.node.lock_id : null;
  for (const n of all) {
    if (n._crumb) { if (lock && fslIs(n.name)) { n.locked = true; n.lock_id = lock; await fslPrepNode(n); n._crumb.name = n.name; } continue; }
    await fslPrepNode(n);
  }
  if (FSL.qFor !== j.node?.id) FSL.q = '';  // the name search belongs to the folder it was typed in
  if (j.node?.locked && FSL.q) j.items = await fslFind(j, FSL.q);
  return j;
}
// 2.953 (#3348): the name search of a locked folder covers its subfolders too -- the server cannot search
// ciphers, so the browser walks the folders below (GET /api/files per folder: only what the person sees) and matches the names it
// decrypted; a hit below carries its path from the open folder (the row shows it). At most FSL_FIND_DIRS folders, remembered for
// FSL_FIND_MS while the same folder is searched (one walk per search, not per letter).
const FSL_FIND_DIRS = 300, FSL_FIND_MS = 30000;
async function fslFind(j, q) {
  const id = j.node.id, low = q.toLowerCase();
  let t = FSL.find;
  if (!t || t.id !== id || Date.now() - t.at > FSL_FIND_MS) {
    const all = (j.items || []).map(n => ({n, path: ''})), dirs = all.filter(x => x.n.kind === 'folder');
    let seen = 0;
    while (dirs.length && seen < FSL_FIND_DIRS) {
      const d = dirs.shift(); seen++;
      let kids; try { kids = (await rawFetch('GET', `/api/files?parent=${d.n.id}`)).items || []; } catch { continue; }
      const path = d.path ? d.path + ' / ' + d.n.name : d.n.name;
      for (const k of kids) { await fslPrepNode(k); const x = {n: k, path}; all.push(x); if (k.kind === 'folder') dirs.push(x); }
    }
    t = FSL.find = {id, at: Date.now(), all};
    if (dirs.length) toast(tr('Only the first {0} folders were searched.', FSL_FIND_DIRS));
  }
  const hits = t.all.filter(x => !x.n._sealed && x.n.name.toLowerCase().includes(low)).map(x => (x.path ? {...x.n, path: x.path} : x.n));
  return hits;
}
const fsl_prep1 = n => fslPrepNode(n);

// ------------------------------------------------------------------ the folder view: banner, filter, open, upload
function fsl_bannerHtml(d) {
  const n = d?.node; if (!n?.locked) return '';
  const sealed = (d.items || []).some(x => x._sealed) || n._sealed;
  const busy = n.lock_mode && n.lock_mode !== 'on', wait = FSL.wait[n.lock_id] || [], names = wait.map(p => p.name).join(', ');
  // 2.353.0 F (#2758, review M1): waiting people get the key only by this button (with their names), never silently
  return `<div class="fslbar" role="note">${ic('lock', 's')}<span>${esc(busy ? tr('This folder is being encrypted. Try again in a moment.') : tr('Locked folder: names and files are encrypted in your browser. The server, agents and API tokens cannot read them.') + ' ' + tr('No camera scan here: the server would see the pages.'))}</span>
    ${sealed ? `<button type="button" class="btn sm" data-fsl="unlock">${ic('lock', 's')} ${tr('Unlock')}</button>` : ''}
    ${FSL.rot[n.lock_id] ? `<span class="e2ewarn" role="alert">${esc(tr('Someone no longer has access to this folder. Change its key so that they cannot read what is added from now on.'))}</span><button type="button" class="btn sm" data-fsl="rotate">${ic('key', 's')} ${esc(tr('Change the key now'))}</button>` : ''}
    ${wait.length ? `<span class="muted">${esc(trn('{0} person waits for the key', '{0} people wait for the key', wait.length))}</span><button type="button" class="btn sm" data-fsl="release" title="${esc(names)}">${ic('key', 's')} ${esc(tr('Hand over the key to {0}', names))}</button>` : ''}
    <input type="search" class="fslq" id="fsl-q" data-fsl="q" value="${esc(FSL.q)}" placeholder="${esc(tr('Search names'))}" aria-label="${esc(tr('Search names in this folder and its subfolders'))}"></div>`;
}
document.addEventListener('input', (/** @type {any} */ e) => {
  const q = e.target.closest?.('[data-fsl="q"]'); if (!q) return;
  if (!q.value) FSL.find = null;  // 2.953 (#3348): a new search walks the subfolders again
  FSL.q = q.value; FSL.qFor = S.route.nid; clearTimeout(FSL.qT); FSL.qT = setTimeout(() => { AB.key = ''; ab_load(); }, 250);
});
document.addEventListener('click', async (/** @type {any} */ e) => {
  const b = e.target.closest?.('[data-fsl]'); if (!b || b.dataset.fsl === 'q') return;
  if (b.dataset.fsl === 'unlock') { if (await e2eEnsure()) { FSL.keys = {}; ab_reload(); } }
  if (b.dataset.fsl === 'rotate') {  // 2.953 (#3348): the key change by hand (keys first seen on this device included)
    const lid = AB.data?.node?.lock_id; if (!lid) return;
    b.disabled = true;
    try { if (await fslRekey(lid, true, fslProgToast(tr('Encrypting')))) toast(tr('The key of the folder was changed.')); } catch (x) { if (!x.shown) fslToast(x); }
    ab_reload();
  }
  if (b.dataset.fsl === 'release') {
    const lid = AB.data?.node?.lock_id, wait = FSL.wait[lid] || []; if (!lid || !wait.length) return;
    b.disabled = true;
    try { const j = await fslRelease(lid, wait.map(p => p.user_id)); fslReleased(lid, j); } catch (x) { if (!x.shown) fslToast(x); b.disabled = false; return; }
    ab_reload();
  }
});
// the toast after handing the key over: the names of who got it (2.353.0 F, #2758 review M1)
function fslReleased(lid, j, people) {
  const got = new Set(j?.released || []), all = [...(FSL.wait[lid] || []), ...(people || [])];
  const names = [...new Set(all.filter(p => got.has(p.user_id)).map(p => p.name))];
  FSL.wait[lid] = (FSL.wait[lid] || []).filter(p => !got.has(p.user_id));
  toast(names.length ? tr('Key handed over to {0}', names.join(', ')) : trn('Key handed over to {0} person', 'Key handed over to {0} people', got.size));
}
const fslLockOf = id => { const d = AB.data; if (!id) return null; const n = d?.node?.id === +id ? d.node : ab_ptItem?.(id) || ab_item(id); return n?.locked ? n.lock_id : null; };
async function fslFetch(n, v) {
  let r;
  try { r = await fetch(`/api/files/lock/${n.lock_id}/raw/${n.id}${v ? '?v=' + v : ''}`, {headers: {'X-Requested-With': 'kalmido'}, credentials: 'same-origin'}); } catch { throw new Offline('net'); }
  if (!r.ok) throw fslErr(tr('File damaged or missing'), 'file');
  return r.arrayBuffer();
}
const fslToast = x => toast(x instanceof Offline ? tr('Offline: only works again with a connection') : x?.message || tr('Cannot be decrypted'));
async function fslDec(n, v) { await fslKeys(n.lock_id, true); return fslFileDec(n.lock_id, await fslFetch(n, v)); }
// a picture as a data: URL (the CSP allows img-src 'self' data:); '' = unreadable
const fslDataUrl = blob => new Promise(res => { const fr = new FileReader(); fr.onload = () => res(String(fr.result)); fr.onerror = () => res(''); fr.readAsDataURL(blob); });
const fslBlobUrl = blob => { const u = URL.createObjectURL(blob); setTimeout(() => URL.revokeObjectURL(u), 120000); return u; };
// 2.683.0 (#5150): the files of the locked folder in the order shown that the viewers leaf through, like an open folder
// (ablage.js: the pictures in the image viewer, ab_pvOpts: PDFs and pictures in the PDF view); sealed names (no key) stay out
const fslLeaf = ok => (AB.data?.items || []).filter(x => x.kind === 'file' && x._enc && !x._sealed && !upLocked(x) && ok(x));
// the PDF view's options of a decrypted file; o.step decrypts the next / previous one only when it is turned to
async function fsl_pvOpts(n, f) {
  const blob = new Blob([f.data], {type: f.type}), o = {name: f.name, size: f.data.length};
  if (ab_isImg({mime: f.type})) { o.img = await fslDataUrl(blob); o.kind = 'img'; o.url = o.dlUrl = o.img; }
  else { o.url = o.dlUrl = fslBlobUrl(blob); o.data = new Uint8Array(f.data); }
  const list = fslLeaf(x => ab_isPdf(x) || ab_isImg(x)), i = list.findIndex(x => x.id === n.id);
  if (i < 0 || list.length < 2) return o;
  return Object.assign(o, {pos: tr('{0} of {1}', i + 1, list.length), first: i <= 0, last: i >= list.length - 1, prevT: tr('Previous document'), nextT: tr('Next document'),
    step: async dir => { const x = list[i + dir]; if (!x) return null; try { return await fsl_pvOpts(x, await fslDec(x)); } catch (e) { fslToast(e); return null; } }});
}
// open (dl: download) a file of a locked folder: decrypted here; images in the viewer, PDFs in the PDF view, else a download
async function fsl_open(n, dl, v) {
  let f;
  try { f = await fslDec(n, v); } catch (x) { fslToast(x); return; }
  const blob = new Blob([f.data], {type: f.type}), a = {id: n.id, name: f.name, size: f.data.length, mime: f.type};
  if (!dl && ab_isImg(a) && typeof attLightbox === 'function') {
    const du = await fslDataUrl(blob);
    if (du) {
      // 2.683.0 (#5150): all pictures of the folder (an older version: only it); each one decrypted when it is turned to
      // (review) one decryption per picture also when it is turned to again while it still runs: `wip` holds the running one
      const imgs = v ? [] : fslLeaf(ab_isImg), got = new Map([[n.id, du]]), wip = new Map();
      const prep = x => {
        if (got.has(x.id)) return Promise.resolve();
        if (!wip.has(x.id)) wip.set(x.id, fslDec(x).then(async g => { got.set(x.id, await fslDataUrl(new Blob([g.data], {type: g.type}))); }).catch(e => { fslToast(e); throw e; }).finally(() => wip.delete(x.id)));
        return wip.get(x.id);
      };
      if (imgs.some(x => x.id === n.id)) attLightbox(n.id, imgs, x => got.get(x.id) || '', prep);
      else attLightbox(n.id, [a], () => du);
      return;
    }
  }
  if (!dl && !v && ab_isPdf(a) && typeof pdfView === 'function') { pdfView(await fsl_pvOpts(n, f)); return; }  // 2.683.0 (#5150): leafs like the documents
  const url = fslBlobUrl(blob);
  if (!dl && ab_isPdf(a) && typeof pdfView === 'function') { pdfView({url, dlUrl: url, name: f.name, size: a.size, data: new Uint8Array(f.data)}); return; }
  const el = document.createElement('a'); el.href = url; el.download = f.name; document.body.appendChild(el); el.click(); el.remove();
}
async function fsl_upload(files, target, lid0) {
  const lid = lid0 || fslLockOf(target); files = [...(files || [])].filter(f => f.size > 0); if (!lid || !files.length) return;
  const lim = upLimit(files); if (lim) { toast(lim); return; }  // 2.363.3 (#3134)
  const fd = new FormData();
  try {
    await fslKeys(lid, true); const g = (await fslInfo(lid, true)).gen;
    toast(tr('Encrypting…'));
    for (const f of files) { fd.append('file', new Blob([await fslFileEnc(lid, f, g)], {type: 'application/octet-stream'}), 'encrypted.kenc'); fd.append('name', await fslNameEnc(lid, f.name, g)); }
  } catch (x) { fslToast(x); return; }
  fd.append('parent_id', String(target));
  let j; try { j = await api('POST', '/api/files/lock/upload', fd); } catch { return; }
  ab_reload();
  const ids = (j.items || []).map(x => x.id);
  offerUndo(trn('{0} file encrypted and uploaded', '{0} files encrypted and uploaded', ids.length), histAdd({label: tr('Upload'),
    undo: () => ab_req('POST', '/api/files/trash', {ids}), redo: () => ab_req('POST', '/api/files/restore', {ids})}));
}
async function fsl_newFolder(pid, name, lid0) {
  const lid = lid0 || fslLockOf(pid);
  let n; try { await fslKeys(lid, true); n = await api('POST', '/api/files/lock/folder', {parent_id: pid, name: await fslNameEnc(lid, name.trim())}); } catch (x) { if (!x.shown) fslToast(x); return; }
  ab_reload();
  offerUndo(tr('Folder “{0}” created', name.trim()), histAdd({label: tr('New folder “{0}”', name.trim()), undo: () => ab_req('DELETE', `/api/files/nodes/${n.id}`), redo: () => ab_req('POST', `/api/files/nodes/${n.id}/restore`)}));
}
async function fsl_rename(n) {
  const name = await askPrompt(tr('Rename'), n.name, {ok: tr('Save'), input: {max: 150}});
  if (!name || !name.trim() || name === n.name) return;
  try { await api('POST', `/api/files/lock/rename/${n.id}`, {name: await fslNameEnc(n.lock_id, name.trim())}); } catch (x) { if (!x.shown) fslToast(x); return; }
  ab_reload(); toast(tr('Renamed to “{0}”', name.trim()));
}
function fsl_newVersion(n) {
  const inp = document.createElement('input'); inp.type = 'file';
  inp.addEventListener('change', () => { const f = inp.files?.[0]; if (f) fsl_newVersionFile(n, f); });
  inp.click();
}
// 2.633.0 (#4920): the chosen / dropped file (the details dialog's fixed input, ab_newVersionFile) encrypted as a new version
/** @param {any} n @param {File} f */
async function fsl_newVersionFile(n, f) {
  const fd = new FormData();
  try { fd.append('file', new Blob([await fslFileEnc(n.lock_id, {name: n.name, type: f.type, data: new Uint8Array(await f.arrayBuffer())})]), 'encrypted.kenc'); } catch (x) { fslToast(x); return; }
  if (n.version) fd.append('expect_version', n.version);  // 2.577.0 (#4708 3)
  try { await api('POST', `/api/files/lock/version/${n.id}`, fd); } catch { return; }
  ab_reload(); toast(tr('New version of “{0}” saved', n.name));
}
// moving across the border of a locked folder: re-encrypted here (true = handled, false = an ordinary move)
async function fsl_moveHook(n, target) {
  let to;
  try { to = await fslLockAt(target); } catch { return false; }
  const from = fslFrom(n);
  if (from === to) return false;
  if (n.kind === 'folder' && n.lock_id === n.id) return false;  // the locked folder itself (the server refuses nesting)
  let block; try { block = await fslMoveCheck(n, target); } catch (x) { if (!x.shown) fslToast(x); return true; }
  if (block) { toast(block); return true; }
  if (!await fslAskMove(to, n.name, 1)) return true;
  try { await fslMoveNode(n, from, to, target); } catch (x) { if (!x.shown) fslToast(x); ab_reload(); return true; }
  ab_reload(); toast(tr('“{0}” moved', n.name));
  return true;
}
// 2.953 (#3348, review N16): the paths of "Move to…" (GET /api/files/folders: parts + lock_id below a locked folder) decrypted here
async function fsl_paths(fs) {
  for (const f of fs) {
    if (!f.lock_id || !Array.isArray(f.parts)) continue;
    const out = [];
    for (const p of f.parts) { try { out.push(await fslNameDec(f.lock_id, p, false)); } catch { out.push(tr('Encrypted')); } }
    f.path = out.join(' / '); f.name = out[out.length - 1];
  }
  return fs;
}
// 2.953 (#3348): the locked folder a target folder lies in (null: open, the top of a space too)
async function fslLockAt(target) {
  if (!target) return null;
  const t = await rawFetch('GET', `/api/files/nodes/${target}`);
  return t?.locked ? t.lock_id : null;
}
const fslFrom = n => n.locked && n.lock_id !== n.id ? n.lock_id : null;
// one question for one or several nodes crossing the border (to: the target's lock, null = out of the locked folder)
function fslAskMove(to, name, k) {
  return askConfirm(to ? tr('Move into a locked folder?') : tr('Move out of the locked folder?'),
    k === 1 && name ? (to ? tr('“{0}” is encrypted in your browser and moved. Its earlier versions are removed; the server and agents can no longer read it.', name)
      : tr('“{0}” is decrypted in your browser and stored readable for the server again. Its earlier encrypted versions are removed.', name))
      : (to ? trn('{0} item is encrypted in your browser and moved, folders with their content. Earlier versions are removed; the server and agents can no longer read them.', '{0} items are encrypted in your browser and moved, folders with their content. Earlier versions are removed; the server and agents can no longer read them.', k)
        : trn('{0} item is decrypted in your browser and stored readable for the server again, folders with their content. Earlier encrypted versions are removed.', '{0} items are decrypted in your browser and stored readable for the server again, folders with their content. Earlier encrypted versions are removed.', k)),
    {ok: tr('Move')});
}
// one file / an empty folder across the border: re-encrypted here (POST /api/files/lock/move)
async function fslMoveOne(n, from, to, target) {
  const fd = new FormData();
  let f = null;
  if (n.kind === 'file') {
    if (from) { await fslKeys(from, true); f = await fslFileDec(from, await fslFetch({id: n.id, lock_id: from})); }
    else { const r = await fetch(ab_url(n, true), {credentials: 'same-origin'}); if (!r.ok) throw fslErr(tr('File damaged or missing'), 'file'); f = {name: n.name, type: n.mime, data: new Uint8Array(await r.arrayBuffer())}; }
  }
  if (to) {
    await fslKeys(to, true); const g = (await fslInfo(to, true)).gen;
    fd.append('name', await fslNameEnc(to, n.name, g));
    if (f) fd.append('file', new Blob([await fslFileEnc(to, {...f, name: n.name}, g)]), 'encrypted.kenc');
  } else {
    fd.append('name', n.name);
    if (f) { fd.append('file', new Blob([f.data]), 'file'); fd.append('type', f.type); }
  }
  if (target) fd.append('parent_id', String(target));
  await api('POST', `/api/files/lock/move/${n.id}`, fd);
}
// the nodes in folder id (outside the trash), names decrypted here (a sealed one stops the move: no key, nothing to write)
async function fslKids(id) {
  const j = await rawFetch('GET', `/api/files?parent=${id}`);
  for (const k of j.items || []) { await fslPrepNode(k, true); if (k._sealed) throw fslErr(tr('You do not have the key of this folder yet.'), 'fs_lock_key'); }
  return j.items || [];
}
async function fslNewFolder(to, target, name, n) {
  if (to) return api('POST', '/api/files/lock/folder', {parent_id: target, name: await fslNameEnc(to, name)});
  return api('POST', '/api/files/folders', target ? {parent_id: target, name} : {space: n.org_id ? 'org:' + n.org_id : 'private', name});
}
// 2.953 (#3348): a folder WITH its content across the border, every id kept (shares, links of the nodes stay):
// a folder of the same name on the other side takes the content (each file re-encrypted, subfolders the same way), then the folder
// itself crosses empty, then the content moves back into it and the helper folder goes. A step that fails stops: what moved stays
// whole on its new side, the rest on the old one (both readable), the helper folder named "<name> (moving)".
async function fslMoveNode(n, from, to, target, prog) {
  if (n.kind !== 'folder') { await fslMoveOne(n, from, to, target); prog?.(); return; }
  const kids = await fslKids(n.id);
  if (!kids.length) { await fslMoveOne(n, from, to, target); prog?.(); return; }
  const tmp = await fslNewFolder(to, target, tr('{0} (moving)', n.name), n);
  for (const k of kids) await fslMoveNode(k, from, to, tmp.id, prog);
  await fslMoveOne(n, from, to, target); prog?.();
  for (const k of await rawFetch('GET', `/api/files?parent=${tmp.id}`).then(j => j.items || [])) await api('PATCH', `/api/files/nodes/${k.id}`, {parent_id: n.id});
  try { await rawFetch('DELETE', `/api/files/nodes/${tmp.id}`); await rawFetch('DELETE', `/api/files/nodes/${tmp.id}?purge=1`); } catch { /* an empty folder in the trash */ }
}
// what the server refuses for a whole subtree, asked before the first step (fsl_movecheck)
async function fslMoveCheck(n, target) {
  if (n.kind !== 'folder') return null;
  const j = await rawFetch('GET', `/api/files/lock/movecheck/${n.id}${target ? '?to=' + target : ''}`);
  return j.block || null;
}
// 2.953 (#3348, review N16): the bar's Move / a drop of several nodes -- the ones crossing a locked folder's border go re-encrypted
// here after ONE question; -> null (none crosses) | {cancel} | {rest: the nodes for the plain way, moved, skip}
async function fsl_moveMany(xs, target) {
  const to = await fslLockAt(target);
  const cross = xs.filter(x => !(x.kind === 'folder' && x.lock_id === x.id) && fslFrom(x) !== to && (x.parent_id ?? null) !== (target || null));
  if (!cross.length) return null;
  if (!await fslAskMove(to, cross[0].name, cross.length)) return {cancel: true};
  let moved = 0, skip = 0, done = 0;
  const prog = () => { if (++done % 10 === 0) toast(tr('{0}: {1} done', tr('Moving'), done)); };
  for (const x of cross) {
    try {
      const block = await fslMoveCheck(x, target);
      if (block) { skip++; toast(block); continue; }
      await fslMoveNode(x, fslFrom(x), to, target, prog); moved++;
    } catch (e) { if (e instanceof Offline) { fslToast(e); break; } if (!e.shown) fslToast(e); skip++; }
  }
  return {rest: xs.filter(x => !cross.includes(x)), moved, skip};
}

// ------------------------------------------------------------------ locking and unlocking a folder (owner / organisation admins)
async function fslPubFor(lid, uid) {
  if (uid === S.me.id) return E2E.own;
  delete E2E.peers[uid];
  let pub = (FSL.info[lid]?.members || []).find(m => m.user_id === uid)?.pub || null;
  try { pub = await e2ePeer(uid) || pub; } catch (e) { if (e instanceof Offline) throw e; }
  if (!pub) throw fslErr(tr('{0} has not set up encryption yet', fslName(lid, uid)), 'fs_lock_nokey');
  if (!le2eSeenOk(uid, pub)) throw fslErr(tr('The key of {0} has changed. Compare the safety number before you continue.', fslName(lid, uid)), 'fs_lock_keychanged');
  return pub;
}
// 2.456.0 (#3851): a 409 without a code = the switch is over: another tab or browser finished it meanwhile
const fslDone = x => x.status === 409 && !x.data?.code;
// the switch: the todo of the server, converted here, until nothing is left; then finish. onProg(done, total)
async function fslMigrate(lid, onProg) {
  let total = null, last = -1, spins = 0;
  for (;;) {
    let t;
    try { t = await rawFetch('GET', `/api/files/lock/${lid}/todo`); }
    catch (x) { if (!fslDone(x)) throw x; delete FSL.info[lid]; return; }
    const left = +t.left || 0, dec = t.mode === 'decrypting';
    if (total === null) total = left;
    onProg?.(Math.max(0, total - left), total);
    if (!left) break;
    if (left === last && ++spins > 2) throw fslErr(tr('Encryption of this folder stopped without progress. Try again later.'), 'fs_lock_stuck');
    last = left;
    for (const r of t.items || []) {
      const fd = new FormData();
      const name = dec ? await fslNameDec(lid, r.name, true) : r.gen ? await fslNameEnc(lid, await fslNameDec(lid, r.name, true), t.gen) : await fslNameEnc(lid, r.name, t.gen);
      fd.append('name', name);
      if (r.kind === 'file') {
        const buf = await fslFetch({id: r.id, lock_id: lid});
        if (dec || r.gen) {
          const f = await fslFileDec(lid, buf);
          if (dec) { fd.append('file', new Blob([f.data]), 'file'); fd.append('type', f.type); }
          else fd.append('file', new Blob([await fslFileEnc(lid, {name: f.name, type: f.type, data: f.data}, t.gen)]), 'encrypted.kenc');
        } else fd.append('file', new Blob([await fslFileEnc(lid, {name: r.name, type: r.mime, data: new Uint8Array(buf)}, t.gen)]), 'encrypted.kenc');
      }
      try { await rawFetch('POST', `/api/files/lock/${lid}/convert/${r.id}`, fd); }
      catch (x) { if (!fslDone(x)) throw x; }  // converted meanwhile by another browser
    }
  }
  try { await rawFetch('POST', `/api/files/lock/${lid}/finish`, {}); }
  catch (x) { if (!fslDone(x)) throw x; }
  delete FSL.info[lid];
}
async function fslStart(lid, onProg) {
  if (!await e2eEnsure()) return false;
  if (E2E.badPub) throw fslErr(tr('Your public key on the server does not match your keys. Encrypted messages are blocked.'), 'fs_lock_badpub');
  const info = await fslInfo(lid, true);
  if (info.mode) return fslResume(lid, onProg);
  const gen = (info.gen || 0) + 1, raw = e2eRand(32), keys = [];
  try {
    const people = (info.members || []).filter(m => m.has_keys);
    if (!people.some(m => m.user_id === S.me.id)) people.unshift({user_id: S.me.id});
    for (const m of people) keys.push({user_id: m.user_id, wrapped: await fslWrap(raw, lid, gen, m.user_id, await fslPubFor(lid, m.user_id))});
    const j = await rawFetch('POST', `/api/files/lock/${lid}/start`, {keys});
    FSL.info[lid] = j;
    (FSL.keys[lid] = {})[j.gen] = await crypto.subtle.importKey('raw', raw, {name: 'AES-GCM'}, false, ['encrypt', 'decrypt']);
  } finally { raw.fill(0); }
  try { await fslMigrate(lid, onProg); }
  catch (x) {  // no half state: what was converted goes back, the folder stays open
    try { await rawFetch('POST', `/api/files/lock/${lid}/stop`, {abort: true}); await fslMigrate(lid); } catch { /* the next visit of an owner continues */ }
    throw x;
  }
  return true;
}
async function fslResume(lid, onProg) {
  const info = await fslInfo(lid, true);
  if (info.mode !== 'encrypting' && info.mode !== 'decrypting') return false;
  await fslKeys(lid, true);
  await fslMigrate(lid, onProg);
  return true;
}
async function fslStop(lid, password, onProg) {
  if (!await e2eEnsure()) return false;
  await fslKeys(lid, true);
  FSL.busy[lid] = 1;  // 2.456.0 (#3851): the reload after the stop must not start a second run beside this one (fsl_auto)
  try {
    await rawFetch('POST', `/api/files/lock/${lid}/stop`, {password});
    delete FSL.info[lid];
    await fslMigrate(lid, onProg);
  } finally { delete FSL.busy[lid]; }
  delete FSL.keys[lid];
  return true;
}
// people waiting for the key get it (every generation I hold)
async function fslRelease(lid, uids) {
  if (!await e2eEnsure()) return false;
  const info = await fslInfo(lid, true), keys = [];
  for (const k of info.keys || []) {
    let raw; try { raw = await fslRaw(lid, k); } catch { continue; }  // #4300: a copy that does not open stops only itself
    try { for (const u of uids) keys.push({user_id: u, gen: k.gen, wrapped: await fslWrap(raw, lid, k.gen, u, await fslPubFor(lid, u))}); } finally { raw.fill(0); }
  }
  if (!keys.length) return false;
  const j = await rawFetch('POST', `/api/files/lock/${lid}/keys`, {keys: keys.slice(0, 500)});
  delete FSL.info[lid];
  return j;
}
// 2.953 (#3348, like the knowledge spaces' wkeRotate): a new folder key (generation + 1) after someone lost
// access, wrapped for everyone keeping the current one whose public key this browser knows (the others wait for the banner's
// button); the automatic change does not wrap for a key this device sees for the first time (byHand: the button does). Then the
// files and names are encrypted again with it (fslMigrate: todo / convert / finish in 'on').
async function fslRotate(lid, byHand) {
  if (!await e2eEnsure()) return false;
  const info = await fslInfo(lid, true);
  if (info.mode !== 'on' || !info.can_manage || !info.rotate) return false;
  const cur = info.gen, gen = cur + 1;
  if (!(info.keys || []).some(k => k.gen === cur)) throw fslErr(tr('You do not have the key of this folder yet.'), 'fs_lock_key');
  await fslKeys(lid, true);
  const people = (info.members || []).filter(m => m.has_keys && (m.key_gens || []).includes(cur));
  if (!byHand && people.some(m => m.user_id !== S.me.id && LE2E.fresh.has(m.user_id))) return false;
  const raw = e2eRand(32), keys = [];
  try {
    if (!people.some(m => m.user_id === S.me.id)) people.unshift({user_id: S.me.id});
    for (const m of people) {
      let pub;
      try { pub = await fslPubFor(lid, m.user_id); } catch (e) { if (m.user_id === S.me.id || e instanceof Offline) throw e; continue; }  // -> waits for the key
      keys.push({user_id: m.user_id, wrapped: await fslWrap(raw, lid, gen, m.user_id, pub)});
    }
    let j;
    try { j = await rawFetch('POST', `/api/files/lock/${lid}/rotate`, {gen, keys}); }
    catch (e) { if (e?.data?.code !== 'fs_lock_gen') throw e; delete FSL.info[lid]; return false; }  // another browser was faster
    FSL.info[lid] = j;
    (FSL.keys[lid] || (FSL.keys[lid] = {}))[j.gen] = await crypto.subtle.importKey('raw', raw, {name: 'AES-GCM'}, false, ['encrypt', 'decrypt']);
  } finally { raw.fill(0); }
  return true;
}
// the key change and the encryption with the new key, once (FSL.busy); -> true when something ran
async function fslRekey(lid, byHand, onProg) {
  if (FSL.busy[lid]) return false;
  FSL.busy[lid] = 1;
  try {
    let info = await fslInfo(lid, true);
    if (info.rotate && !await fslRotate(lid, byHand)) {
      info = await fslInfo(lid, true);  // another browser changed it meanwhile, or a key seen here for the first time: the button
      if (info.rotate) { FSL.rot[lid] = true; return false; }
    }
    delete FSL.rot[lid];
    info = await fslInfo(lid, true);
    if (info.reenc) { await fslKeys(lid, true); await fslMigrate(lid, onProg); }
    return true;
  } finally { delete FSL.busy[lid]; }
}
const fslProgToast = (what) => (done, total) => { if (total) toast(tr('{0}: {1} of {2}', what, done, total)); };
async function fsl_lockDlg(n) {
  if (!fslOk()) { toast(tr('This browser cannot encrypt')); return; }
  let info; try { info = await fslInfo(n.id, true); } catch { return; }
  if (info.mode) return fsl_infoDlg(n, info);
  if (info.block) { toast(info.block); return; }
  const without = (info.members || []).filter(m => !m.has_keys && m.user_id !== S.me.id);
  const get = (info.members || []).filter(m => m.has_keys && m.user_id !== S.me.id);  // 2.353.0 F (#2758, review M1): named before the lock
  const yes = await askConfirm(tr('Lock “{0}”?', n.name), '', {ok: tr('Lock folder'), danger: true, html:
    [tr('Names and files of this folder are encrypted in your browser. The server, the operator, agents and API tokens cannot read them any more: no preview, no text recognition, no search on the server.'),
      `<b>${esc(tr('Warning: if you and everyone holding the key lose passphrase and recovery code, the content is lost permanently. Nobody can restore it, not even the operator.'))}</b>`,
      get.length ? tr('These people get the key with the lock: {0}', get.map(m => m.name).join(', ')) : '',
      // 2.953 (#3348): tags are plain words the server reads -- they are removed with the lock
      info.tagged ? trn('The tags of {0} file or folder in it are removed (the server could read them).', 'The tags of {0} files or folders in it are removed (the server could read them).', info.tagged) : '',
      without.length ? tr('Waiting for the key until they set up encryption: {0}', without.map(m => m.name).join(', ')) : ''].filter(Boolean).map(x => `<p>${x.startsWith('<b>') ? x : esc(x)}</p>`).join('')});
  if (!yes) return;
  try { await fslStart(n.id, fslProgToast(tr('Encrypting'))); } catch (x) { if (!x.shown) toast(tr('The folder stays open: {0}', x.message || '?')); ab_reload(); return; }
  ab_reload(); toast(tr('“{0}” is locked', n.name));
}
async function fsl_infoDlg(n, info) {
  const pend = info.pending || [];
  const md = modal(`<div class="lhdr"><h3>${ic('lock', 's')} ${esc(tr('Locked folder “{0}”', n.name))}</h3><span class="spacer"></span><button class="iconbtn" data-m="close" aria-label="${tr('Close')}" title="${tr('Close')}">${ic('x')}</button></div>
    <p class="shint lhint keep">${esc(tr('Names and files are encrypted in the browser. Only people get access; agents and API tokens are excluded.'))}</p>
    <h4>${tr('People with the key')}</h4><ul class="fslppl">${(info.members || []).map(m => `<li>${esc(m.name)} <span class="muted">${(m.key_gens || []).includes(info.gen) ? tr('has the key') : m.has_keys ? tr('waits for the key') : tr('no encryption set up yet')}</span></li>`).join('') || `<li class="muted">${tr('Only you')}</li>`}</ul>
    <div class="lfoot">${info.can_manage && pend.some(p => p.has_keys) ? `<button type="button" class="btn pri" data-fsld="release">${tr('Hand over the key')}</button>` : ''}
    ${info.can_manage && info.mode === 'on' ? `<button type="button" class="btn danger" data-fsld="stop">${tr('Unlock folder…')}</button>` : ''}
    ${info.can_manage && info.mode !== 'on' ? `<button type="button" class="btn" data-fsld="resume">${tr('Continue')}</button>` : ''}</div>`);
  md.classList.add('fsldlg');
  md.addEventListener('click', async (/** @type {any} */ e) => {
    const b = e.target.closest('[data-fsld]'); if (!b) return;
    b.disabled = true;
    try {
      if (b.dataset.fsld === 'release') { const j = await fslRelease(n.id, pend.filter(p => p.has_keys).map(p => p.user_id)); fslReleased(n.id, j, pend); }
      if (b.dataset.fsld === 'resume') await fslResume(n.id, fslProgToast(tr('Encrypting')));
      if (b.dataset.fsld === 'stop') {
        const pw = await askPrompt(tr('Unlock “{0}”?', n.name), '', {ok: tr('Unlock folder'), danger: true, input: {type: 'password', placeholder: tr('Your account password')},
          body: tr('Names and files are decrypted in your browser and stored readable for the server again (preview, search and recognition work again).')});
        if (pw == null) { b.disabled = false; return; }
        await fslStop(n.id, pw, fslProgToast(tr('Decrypting')));
        toast(tr('“{0}” is unlocked', n.name));
      }
      modalClose(md); ab_reload();
    } catch (x) { if (!x.shown) fslToast(x); b.disabled = false; }
  });
}
// the menu entry of a folder (the row's "…", the tree)
function fsl_menuItem(n) {
  if (n.kind !== 'folder' || !fslOk() || S.me?.kind === 'agent') return null;
  if (n.locked && n.lock_id === n.id) return {label: tr('Locked folder…'), icon: 'lock', fn: () => fsl_lockDlg(n)};
  if (n.locked || n.role !== 'owner' || n.agent_id) return null;
  return {label: tr('Lock folder…'), icon: 'lock', fn: () => fsl_lockDlg(n)};
}
// an owner opening a locked folder: an interrupted switch continues; people waiting with encryption set up are shown in the banner
// (2.353.0 F, #2758 review M1: like the knowledge spaces and lists, the key goes only by the button -- never silently)
async function fsl_auto(d) {
  const n = d?.node; if (!n?.locked || typeof e2eUnlocked !== 'function' || !e2eUnlocked()) return;
  const lid = n.lock_id, tag = lid + ':' + (n.lock_mode || '');
  if (FSL.auto[tag] || FSL.busy[lid]) return;
  FSL.auto[tag] = 1; FSL.busy[lid] = 1;
  try {
    const info = await fslInfo(lid, true);
    if (!info.can_manage) return;
    if (info.mode !== 'on') { await fslResume(lid); ab_reload(); return; }
    if (info.rotate || info.reenc) {  // 2.953 (#3348): someone lost access -- a new key, then the files with it
      delete FSL.busy[lid];
      const had = !!FSL.rot[lid];
      if (await fslRekey(lid, false)) { toast(tr('The key of the folder was changed.')); ab_reload(); return; }
      if (!had && FSL.rot[lid]) ab_draw();
    }
    const w = (info.pending || []).filter(p => p.has_keys).map(p => ({user_id: p.user_id, name: p.name}));
    const was = (FSL.wait[lid] || []).map(p => p.user_id).join();
    FSL.wait[lid] = w;
    if (w.map(p => p.user_id).join() !== was) ab_draw();
  } catch (x) { console.warn('fsl: auto', x?.message); } finally { delete FSL.busy[lid]; }
}
// a version in the details of an encrypted file: decrypted here
document.addEventListener('click', (/** @type {any} */ e) => {
  const a = e.target.closest?.('[data-fslv]'); if (!a) return;
  e.preventDefault();
  fsl_open({id: +a.dataset.fslid, lock_id: +a.dataset.fsllk}, true, +a.dataset.fslv);
});
