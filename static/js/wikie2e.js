/* Kalmido web client: 2.64.3 (#1817) the lock per knowledge space (wiki.js). Path and text of the pages of an encrypted
   space are encrypted in the browser with the space key; search, backlinks and "mentioned in" run here.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md).
   A space = "private" or "org:<id>" (wiki.js); its row on the server (wiki_spaces) has a number, space_id, that the salt and
   the AAD name. Built on e2e.js (the person's keys) and liste2e.js (padding, remembered public keys le2eSeenOk, safety
   numbers); server side kalmido/wiki/wikie2e.py. Decrypted texts live only in this page's memory (H1): the wiki index and
   the open page (WK) and the memo below; wkeWipe drops them when the encryption is locked or the person logs out. */
'use strict';

// ------------------------------------------------------------------ state
// st: space -> {space_id, mode, gen, rotate, reenc, pending, mine, can_manage} (the index's e2e or the e2e route; only spaces
// that are not open); info: space -> answer of GET /api/wiki/e2e; keys: space -> {gen: CryptoKey (AES-GCM, not extractable)};
// memo: cipher -> plain text (this page only); locked: space -> pages of the index that did not open; busy: space -> the
// running switch / re-encryption (Promise); prog: space -> {kind, done, total}; rot: space -> state the automatic key change
// last handled; unread: space -> values no key here opens (re-encryption)
const WKE = {st: {}, info: {}, infoP: {}, keys: {}, tried: {}, memo: new Map(), locked: {}, busy: {}, prog: {}, rot: {}, unread: {}, probe: null};
const WKE_PRE = 'e2e1:';
const WKE_TPL = /^(templates|vorlagen)\//i;
const WKE_ZIP = {files: 2000, file: 1000000, total: 30000000};  // the server's limits of an import (wiki/pages.py WIKI_ZIP_*)
const wkeIs = v => typeof v === 'string' && v.startsWith(WKE_PRE);
function wkeOn(sp) { return !!WKE.st[sp]?.mode; }
function wkeMode(sp) { return WKE.st[sp]?.mode || null; }
function wkeReady(sp) { const s = WKE.st[sp]; return !!(s && s.mode && WKE.keys[sp]?.[s.gen]); }
const wkeChange = sp => document.dispatchEvent(new CustomEvent('wke:change', {detail: {space: sp}}));
function wkeErr(msg, code) { const e = new Error(msg); e.code = code; return e; }
const wkeErrLocked = () => wkeErr(tr('Unlock first: this space is encrypted in the browser.'), 'wiki_e2e_locked');
const wkeName = (sp, uid) => (WKE.info[sp]?.members || []).find(m => m.user_id === uid)?.name || personNameAny?.(uid) || '?';
// the state of a space from the index (e2e: null = open) or from the e2e route
function wkeSet(sp, e) {
  const old = WKE.st[sp];
  if (!e || !e.mode) {
    if (old) { delete WKE.st[sp]; delete WKE.keys[sp]; delete WKE.info[sp]; delete WKE.tried[sp]; delete WKE.locked[sp]; }
    return;
  }
  const n = {...(old || {}), ...e};
  if (old && old.gen !== n.gen) delete WKE.tried[sp];
  WKE.st[sp] = n;
}
function wkeSetInfo(sp, j) {
  if (!j) return;
  wkeSet(sp, j.mode ? {space_id: j.space_id, mode: j.mode, gen: j.gen, rotate: j.rotate || 0, reenc: j.reenc || 0, can_manage: !!j.can_manage,
    pending: (j.pending || []).length, mine: (j.keys || []).some(k => k.gen === j.gen)} : null);
}

// ------------------------------------------------------------------ content crypto
// AES-256-GCM with the space key of generation g; AAD binds space, generation and field ("path" | "body"), no page id (M1:
// templates and copies in the same space stay readable); padded to 64 bytes like the lists (le2ePad, L1)
const wkeAad = (sid, g, f) => `kalmido-wiki:v1:${sid}:${g}:${f}`;
async function wkeEnc(sp, field, text) {
  if (text == null || text === '') return '';
  const s = WKE.st[sp], g = s?.gen, sid = s?.space_id;
  let key = WKE.keys[sp]?.[g];
  if (!key && s?.mode) key = (await wkeKeys(sp))[g];
  if (!key || sid == null) throw wkeErrLocked();
  const b = await e2eSeal(key, le2ePad(e2eTEnc().encode(String(text))), wkeAad(sid, g, field));
  const c = WKE_PRE + JSON.stringify({v: 1, g, iv: b.iv, ct: b.ct});
  WKE.memo.set(c, String(text));
  return c;
}
// one cipher with the keys at hand: the text, null (did not open) or undefined (no key of its generation here)
async function wkeTry(sp, c, field, ks) {
  if (WKE.memo.has(c)) return WKE.memo.get(c);
  const o = le2eParse(c), sid = WKE.st[sp]?.space_id; if (!o || sid == null) return null;
  const key = ks?.[o.g]; if (!key) return undefined;
  try {
    const s = e2eTDec().decode(le2eUnpad(await e2eOpen(key, {v: 1, iv: o.iv, ct: o.ct}, wkeAad(sid, o.g, field))));
    WKE.memo.set(c, s);
    return s;
  } catch { return null; }
}
async function wkeDec(sp, field, c) {
  if (!wkeIs(c)) return c ?? '';
  const s = await wkeTry(sp, c, field, await wkeKeys(sp));
  if (s == null) throw wkeErr(s === undefined ? tr('You do not have the key of this space yet.') : tr('The space key could not be opened.'), 'wiki_e2e_key');
  return s;
}

// ------------------------------------------------------------------ space keys
// wrapping for member R by W: ECDH(priv W, pub R) -> HKDF-SHA256(salt "wiki:<space_id>:<gen>", info kalmido-wikikey:v1) ->
// AES-GCM over the 32 raw bytes, AAD names space, generation, R and W (the list variant le2eKek has the list id in its salt)
const wkeWrapAad = (sid, gen, r, w) => `kalmido-wikikey:v1:${sid}:${gen}:${r}:${w}`;
async function wkeKek(pub, sid, gen) {
  const pk = await crypto.subtle.importKey('jwk', {kty: 'EC', crv: 'P-256', x: pub.x, y: pub.y}, {name: 'ECDH', namedCurve: 'P-256'}, false, []);
  const bits = await crypto.subtle.deriveBits({name: 'ECDH', public: pk}, E2E.priv, 256);
  let hk; try { hk = await crypto.subtle.importKey('raw', bits, 'HKDF', false, ['deriveKey']); } finally { new Uint8Array(bits).fill(0); }
  return crypto.subtle.deriveKey({name: 'HKDF', hash: 'SHA-256', salt: e2eTEnc().encode(`wiki:${sid}:${gen}`), info: e2eTEnc().encode('kalmido-wikikey:v1')}, hk, {name: 'AES-GCM', length: 256}, false, ['encrypt', 'decrypt']);
}
async function wkeWrap(raw, sid, gen, uid, pub) {
  return e2eSeal(await wkeKek(pub, sid, gen), raw, wkeWrapAad(sid, gen, uid, S.me.id));
}
// the raw bytes of my key of a generation (H4: wrapped by me = my own key from the bundle, never the server's copy; by someone
// else = the key this browser remembered for them); the caller wipes them
async function wkeRaw(sp, sid, k) {
  const w = k.wrapped_by, me = S.me.id;
  let pub;
  if (w === me) pub = E2E.own;
  else { pub = k.wrapper_pub; if (!le2eSeenOk(w, pub)) throw wkeErr(tr('The key of {0} has changed. Compare the safety number before you continue.', wkeName(sp, w)), 'wiki_e2e_keychanged'); }
  if (!pub) throw wkeErr(tr('The space key could not be opened.'), 'wiki_e2e_key');
  const wr = typeof k.wrapped === 'string' ? JSON.parse(k.wrapped) : k.wrapped;
  return e2eOpen(await wkeKek(pub, sid, k.gen), wr, wkeWrapAad(sid, k.gen, me, w));
}
async function wkeInfo(sp, force) {
  if (!force && WKE.info[sp]) return WKE.info[sp];
  if (WKE.infoP[sp]) return WKE.infoP[sp];
  const p = rawFetch('GET', '/api/wiki/e2e?space=' + encodeURIComponent(sp)).then(j => {
    WKE.info[sp] = j;
    wkeSetInfo(sp, j);
    for (const m of j.members || []) if (m.pub && m.user_id !== S.me?.id) le2eSeenOk(m.user_id, m.pub);
    return j;
  }).finally(() => { delete WKE.infoP[sp]; });
  WKE.infoP[sp] = p;
  return p;
}
// every generation of this space I hold a key for, unwrapped (only while the encryption is unlocked)
async function wkeKeys(sp, force) {
  const have = WKE.keys[sp] || (WKE.keys[sp] = {});
  if (typeof e2eUnlocked !== 'function' || !e2eUnlocked() || !S.me) return have;
  const want = WKE.st[sp]?.gen || 0, tag = String(want);
  if (!force && (have[want] || WKE.tried[sp] === tag)) return have;
  WKE.tried[sp] = tag;
  let info;
  try { info = await wkeInfo(sp, true); } catch { return have; }
  WKE.tried[sp] = String(info.gen || 0);
  for (const k of info.keys || []) {
    if (have[k.gen]) continue;
    try { have[k.gen] = await le2eImport(await wkeRaw(sp, info.space_id, k)); } catch { /* a changed key (le2eKeyChanged) or a broken wrap */ }
  }
  return have;
}
// a member's public key for wrapping: fetched again, checked against the remembered one (H4)
async function wkePubFor(sp, uid) {
  if (uid === S.me.id) return E2E.own;
  delete E2E.peers[uid];
  let pub;
  // before the first switch the server may not hand out a member's key by this route: the space's member list carries it too
  try { pub = await e2ePeer(uid); } catch (e) { if (e instanceof Offline) throw e; pub = (WKE.info[sp]?.members || []).find(m => m.user_id === uid)?.pub || null; }
  if (!pub) throw wkeErr(tr('{0} has not set up encryption yet', wkeName(sp, uid)), 'wiki_e2e_nokey');
  if (!le2eSeenOk(uid, pub)) throw wkeErr(tr('The key of {0} has changed. Compare the safety number before you continue.', wkeName(sp, uid)), 'wiki_e2e_keychanged');
  return pub;
}
const wkeBadPub = () => { if (E2E.badPub) throw wkeErr(tr('Your public key on the server does not match your keys. Encrypted messages are blocked.'), 'wiki_e2e_badpub'); };
// waiting members get the key: every generation I hold (older texts not re-encrypted yet), the current one is required
async function wkeRelease(sp, userIds) {
  if (!await e2eEnsure()) return false;
  wkeBadPub();
  const info = await wkeInfo(sp, true), gen = info.gen, sid = info.space_id;
  const held = (info.keys || []).filter(k => k.gen <= gen);
  if (!held.some(k => k.gen === gen)) throw wkeErr(tr('You do not have the key of this space yet.'), 'wiki_e2e_key');
  const raws = [], keys = [];
  try {
    for (const k of held) { try { raws.push([k.gen, await wkeRaw(sp, sid, k)]); } catch (e) { if (k.gen === gen) throw e; } }
    const pubs = {};
    for (const uid of userIds) pubs[uid] = await wkePubFor(sp, uid);
    for (const [g, raw] of raws) for (const uid of userIds) keys.push({user_id: uid, gen: g, wrapped: await wkeWrap(raw, sid, g, uid, pubs[uid])});
  } finally { for (const [, raw] of raws) raw.fill(0); }
  let j = null;
  for (let i = 0; i < keys.length; i += 200) {
    const r = await rawFetch('POST', '/api/wiki/e2e/keys', {space: sp, keys: keys.slice(i, i + 200)});
    j = j ? {...j, ...r, released: [...new Set([...(j.released || []), ...(r.released || [])])], skipped: [...new Set([...(j.skipped || []), ...(r.skipped || [])])]} : r;
  }
  delete WKE.info[sp];
  wkeChange(sp);
  return j;
}
// a new space key of generation gen+1 for everyone holding the current one whose public key matches the remembered one (the
// others wait for a release); 409 wiki_e2e_gen = someone else was faster. Then the background re-encryption (wkeReenc).
async function wkeRotate(sp, byHand) {
  if (!await e2eEnsure()) return false;
  wkeBadPub();
  const info = await wkeInfo(sp, true);
  if (info.mode !== 'on' || !info.can_manage) return false;
  const cur = info.gen, gen = cur + 1, sid = info.space_id;
  if (!(info.keys || []).some(k => k.gen === cur)) throw wkeErr(tr('You do not have the key of this space yet.'), 'wiki_e2e_key');
  await wkeKeys(sp, true);
  const people = (info.members || []).filter(m => m.has_keys && (m.key_gens || []).includes(cur));
  // like the lists (2.64.2 review M1): the automatic change does not wrap for a key this device sees for the first time
  if (!byHand && people.some(m => m.user_id !== S.me.id && LE2E.fresh.has(m.user_id))) return false;
  const raw = e2eRand(32), keys = [];
  try {
    if (!people.some(m => m.user_id === S.me.id)) people.unshift({user_id: S.me.id});
    for (const m of people) {
      let pub;
      try { pub = await wkePubFor(sp, m.user_id); } catch (e) { if (m.user_id === S.me.id) throw e; continue; }  // -> waiting list
      keys.push({user_id: m.user_id, wrapped: await wkeWrap(raw, sid, gen, m.user_id, pub)});
    }
    let j;
    try { j = await rawFetch('POST', '/api/wiki/e2e/rotate', {space: sp, gen, keys}); }
    catch (e) { if (!['wiki_e2e_gen', 'wiki_e2e_members'].includes(e?.data?.code)) throw e; delete WKE.info[sp]; wkeAfter(sp); return false; }
    WKE.info[sp] = j; wkeSetInfo(sp, j);
    (WKE.keys[sp] || (WKE.keys[sp] = {}))[j.gen ?? gen] = await crypto.subtle.importKey('raw', raw, {name: 'AES-GCM'}, false, ['encrypt', 'decrypt']);
    WKE.tried[sp] = String(j.gen ?? gen);
  } finally { raw.fill(0); }
  wkeChange(sp);
  return true;
}

// ------------------------------------------------------------------ the pages: opening, local search, backlinks, mentions
// the frontmatter of a text (wiki/pages.py wiki_frontmatter): simple YAML, scalars and [a, b] lists
function wkeFront(text) {
  const m = /^---[ \t]*\r?\n([\s\S]*?)\r?\n---[ \t]*(?:\r?\n|$)/.exec(text || ''), out = {};
  if (!m) return out;
  for (const ln of m[1].split(/\r?\n/).slice(0, 50)) {
    const mm = /^([A-Za-z0-9_][\w .-]{0,40}):\s*(.*)$/.exec(ln); if (!mm) continue;
    const k = mm[1].trim(); let v = mm[2].trim();
    if (v.length >= 2 && v[0] === v[v.length - 1] && `"'`.includes(v[0])) v = v.slice(1, -1);
    else if (v.startsWith('[') && v.endsWith(']')) v = v.slice(1, -1).split(',').map(x => x.trim()).filter(Boolean).map(x => x.replace(/^["']+|["']+$/g, '')).slice(0, 30);
    out[k] = Array.isArray(v) ? v : v.slice(0, 300);
  }
  return out;
}
// the cleaned path (wiki/pages.py wiki_clean_path): the server cannot clean a cipher, so the browser does it with the same rules
const WKE_BAD = /[\x00-\x1f\x7f\[\]|#^\\]/g;
function wkeClean(v) {
  v = String(v ?? '').normalize('NFC').trim();
  if (v.toLowerCase().endsWith('.md')) v = v.slice(0, -3);
  const parts = v.replace(/\\/g, '/').split('/').map(p => p.replace(WKE_BAD, '').replace(/\s+/g, ' ').trim()).filter(Boolean);
  if (!parts.length || parts.some(p => p === '.' || p === '..' || p.startsWith('.'))) throw wkeErr(tr('Please give the page a name'), 'bad');
  if (parts.length > 12) throw wkeErr(tr('Too many folder levels (at most {0})', 12), 'bad');
  const out = parts.join('/');
  if (out.length > 200) throw wkeErr(tr('The name is too long (at most {0} characters)', 200), 'bad');
  return out;
}
const wkeKey = p => { try { return wkeClean(p).toLowerCase(); } catch { return ''; } };
const WKE_LINK = /\[\[([^\[\]|#\n]{1,250})(?:#[^\[\]|\n]*)?(?:\|[^\[\]\n]*)?\]\]/g;
const wkeLinks = text => new Set([...String(text || '').matchAll(WKE_LINK)].map(m => wkeKey(m[1])).filter(Boolean));
const wkeTasks = text => new Set([...String(text || '').matchAll(/(^|[^\w&/#])#(\d{1,12})\b/g)].map(m => +m[2]));
// a page object of an encrypted space: path / body opened in place (the ciphers kept in _enc), attrs and the template flag from
// the plain text (the server sends {} / false); false when a cipher did not open (the page stays "locked")
async function wkeOpen(sp, p, ks) {
  if (!p || typeof p !== 'object') return true;
  const enc = {};
  let ok = true;
  for (const f of ['path', 'body']) {
    const c = p[f]; if (!wkeIs(c)) continue;
    enc[f] = c;
    const s = await wkeTry(sp, c, f, ks);
    if (s == null) { ok = false; p[f] = ''; } else p[f] = s;
  }
  if (Object.keys(enc).length) Object.defineProperty(p, '_enc', {value: enc, writable: true, configurable: true, enumerable: false});
  if (ok) {
    if (typeof p.body === 'string') p.attrs = wkeFront(p.body);
    if (p.path) p.template = WKE_TPL.test(p.path);
    delete p._wke;
  } else p._wke = 'locked';
  return ok;
}
const wkeSort = pages => pages.sort((a, b) => a.path.toLowerCase().localeCompare(b.path.toLowerCase(), LOCALE()));
function wkeBacklinks(sp, p) {
  const k = String(p.path || '').toLowerCase(); if (!k) return [];
  return wk_pages(sp).filter(x => x.id !== p.id && wkeLinks(x.body).has(k)).map(x => ({id: x.id, path: x.path})).sort((a, b) => a.path.localeCompare(b.path, LOCALE())).slice(0, 200);
}
// wiki.js wk_load: the index of an encrypted space (asked with bodies=1): paths and texts opened, pages that do not open left
// out of the tree (counted: the lock box says it), sorted by name (the server sorts by ciphers)
async function wkeIndex(sp, j) {
  wkeSet(sp, j?.e2e);
  if (!j?.e2e) return j;
  const ks = await wkeKeys(sp), pages = [];
  let n = 0;
  for (const p of j.pages || []) { if (await wkeOpen(sp, p, ks)) pages.push(p); else n++; }
  j.pages = wkeSort(pages);
  WKE.locked[sp] = n;
  setTimeout(() => {
    if (WK.pg && WK.pg.space === sp && !WK.pg._wke) WK.pg.backlinks = wkeBacklinks(sp, WK.pg);
    wkeAuto(sp);
  }, 0);
  return j;
}
// wiki.js wk_loadPage: one page (the space's state from the e2e route when its index is not here yet); backlinks local
async function wkePage(p) {
  if (!p || typeof p !== 'object') return p;
  const sp = p.space;
  if (!WKE.st[sp] && (wkeIs(p.path) || wkeIs(p.body))) { try { await wkeInfo(sp); } catch { /* offline */ } }
  if (!wkeOn(sp)) return p;
  await wkeOpen(sp, p, await wkeKeys(sp));
  if (!p._wke) p.backlinks = wkeBacklinks(sp, p);
  return p;
}
// pages of the unlocked encrypted spaces whose name or text has every word (the server's search leaves them out)
function wkeSearch(q) {
  const ws = le2eWords(q), out = [];
  if (!ws.length) return out;
  for (const sp in WKE.st) {
    if (!wkeReady(sp)) continue;
    for (const p of wk_pages(sp)) if (le2eHit(ws, p.path, p.body)) out.push({id: p.id, space: sp, org_id: p.org_id, path: p.path, attrs: p.attrs || {}, template: !!p.template, updated_at: p.updated_at, e2e: true});
  }
  return out.slice(0, 30);
}
// pages of the unlocked encrypted spaces that name task #tid (the server's wiki_links stays empty for them)
async function wkeMentions(tid) {
  const out = [];
  for (const sp in WKE.st) {
    if (!wkeReady(sp)) continue;
    for (const p of wk_pages(sp)) if (wkeTasks(p.body).has(tid)) out.push({id: p.id, path: p.path, space: sp});
  }
  return out.sort((a, b) => a.path.localeCompare(b.path, LOCALE())).slice(0, 50);
}

// ------------------------------------------------------------------ writing (wiki.js): path and text leave encrypted
async function wkeSeal(sp, b) {
  const o = {...b};
  if (o.path != null) o.path = await wkeEnc(sp, 'path', wkeClean(o.path));
  if (o.body != null) o.body = await wkeEnc(sp, 'body', o.body);
  return o;
}
// rawFetch for the page routes of a space: in an encrypted one path / body go out as ciphers and the answer's page (also the
// one of a 409 "changed in the meantime") comes back opened
async function wkeApi(method, url, body, sp) {
  if (!wkeOn(sp)) return rawFetch(method, url, body);
  const b = body && typeof body === 'object' && !(body instanceof FormData) ? await wkeSeal(sp, body) : body;
  try {
    const r = await rawFetch(method, url, b);
    if (r && typeof r === 'object') { await wkeOpen(sp, r, WKE.keys[sp]); r.backlinks = r._wke ? [] : wkeBacklinks(sp, r); }
    return r;
  } catch (e) {
    if (e?.data?.page) await wkeOpen(sp, e.data.page, WKE.keys[sp]).catch(() => {});
    throw e;
  }
}
const wkeTaken = () => wkeErr(tr('A page with this name already exists'), 'wiki_taken');
// a new page: the name checked here (the server cannot compare ciphers), a template's text copied here
async function wkeCreate(sp, path, tplId, text = '') {
  if (!wkeReady(sp)) await wkeKeys(sp, true);
  if (!wkeReady(sp)) throw wkeErrLocked();
  const pth = wkeClean(path);
  if (wk_byPath(sp, pth)) throw wkeTaken();
  if (tplId && !text) {
    const t = wk_pages(sp).find(x => x.id === tplId);
    text = t && typeof t.body === 'string' ? t.body : (await wkePage(await rawFetch('GET', '/api/wiki/pages/' + tplId))).body || '';
  }
  return wkeApi('POST', '/api/wiki/pages', {space: sp, path: pth, body: text}, sp);
}
// [[old]] -> [[new]] in the pages of the space (also [[old|label]] and [[old#part]]), one PATCH per changed page
const wkeReEsc = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
async function wkeRelink(sp, pairs, skip = new Set()) {
  let n = 0;
  const rxs = pairs.map(([o, nw]) => [new RegExp('\\[\\[\\s*' + wkeReEsc(o) + '\\s*(?=[\\]|#])', 'gi'), nw]);
  for (const q of wk_pages(sp)) {
    if (skip.has(q.id) || typeof q.body !== 'string') continue;
    let nb = q.body;
    for (const [rx, nw] of rxs) nb = nb.replace(rx, () => '[[' + nw);
    if (nb === q.body) continue;
    try { await wkeApi('PATCH', '/api/wiki/pages/' + q.id, {body: nb}, sp); q.body = nb; n++; } catch (e) { console.warn('wke: relink', q.id, e?.message); }
  }
  return n;
}
async function wkeRename(p, path) {
  const sp = p.space, np = wkeClean(path), ix = wk_pages(sp).find(x => x.id === p.id), old = ix?.path || p.path;  // the index knows the name now (an undo later)
  const dup = wk_byPath(sp, np); if (dup && dup.id !== p.id) throw wkeTaken();
  const r = await wkeApi('PATCH', '/api/wiki/pages/' + p.id, {path: np}, sp);
  if (ix) ix.path = np;
  r.relinked = np.toLowerCase() === old.toLowerCase() ? 0 : await wkeRelink(sp, [[old, np]], new Set([p.id]));
  return r;
}
// a folder gets another name: every page at or under "from" moves under "to" (one PATCH each), the links follow
async function wkeMove(sp, from, to) {
  const src = wkeClean(from), dst = wkeClean(to), sl = src.toLowerCase();
  if (dst.toLowerCase() === sl || dst.toLowerCase().startsWith(sl + '/')) throw wkeErr(tr('Invalid value: {0}', 'to'), 'bad');
  const rows = wk_pages(sp).filter(x => x.path.toLowerCase() === sl || x.path.toLowerCase().startsWith(sl + '/'));
  if (!rows.length) throw wkeErr(tr('This page does not exist or you cannot see it.'), 'wiki_404');
  const moves = rows.map(r => [r, wkeClean(dst + r.path.slice(src.length))]), mine = new Set(rows.map(r => r.id));
  if (moves.some(([, n]) => { const x = wk_byPath(sp, n); return x && !mine.has(x.id); })) throw wkeTaken();
  const done = [];
  for (const [r, n] of moves) { await wkeApi('PATCH', '/api/wiki/pages/' + r.id, {path: n}, sp); done.push({id: r.id, from: r.path, to: n}); }
  for (const d of done) { const x = wk_pages(sp).find(y => y.id === d.id); if (x) x.path = d.to; }
  const relinked = await wkeRelink(sp, done.map(d => [d.from, d.to]));
  return {ok: true, moved: done, relinked};
}

// ------------------------------------------------------------------ export / import as ZIP, in the browser
// a small ZIP writer (method "stored", CRC32, UTF-8 names) and reader ("stored" and "deflate" via DecompressionStream)
let WKE_CRC = null;
function wkeCrc(u) {
  if (!WKE_CRC) { WKE_CRC = new Uint32Array(256); for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1; WKE_CRC[n] = c >>> 0; } }
  let c = 0xFFFFFFFF;
  for (let i = 0; i < u.length; i++) c = WKE_CRC[(c ^ u[i]) & 0xFF] ^ (c >>> 8);
  return (c ^ 0xFFFFFFFF) >>> 0;
}
function wkeZip(files) {
  const te = e2eTEnc(), parts = [], cen = [], d = new Date();
  const time = (d.getHours() << 11) | (d.getMinutes() << 5) | (d.getSeconds() >> 1), date = ((d.getFullYear() - 1980) << 9) | ((d.getMonth() + 1) << 5) | d.getDate();
  let off = 0;
  for (const f of files) {
    const name = te.encode(f.name), data = f.data, crc = wkeCrc(data);
    const lh = new DataView(new ArrayBuffer(30));
    [[0, 0x04034b50, 4], [4, 20, 2], [6, 0x0800, 2], [8, 0, 2], [10, time, 2], [12, date, 2], [14, crc, 4], [18, data.length, 4], [22, data.length, 4], [26, name.length, 2], [28, 0, 2]]
      .forEach(([o, v, n]) => n === 4 ? lh.setUint32(o, v, true) : lh.setUint16(o, v, true));
    const ch = new DataView(new ArrayBuffer(46));
    [[0, 0x02014b50, 4], [4, 20, 2], [6, 20, 2], [8, 0x0800, 2], [10, 0, 2], [12, time, 2], [14, date, 2], [16, crc, 4], [20, data.length, 4], [24, data.length, 4], [28, name.length, 2],
      [30, 0, 2], [32, 0, 2], [34, 0, 2], [36, 0, 2], [38, 0, 4], [42, off, 4]].forEach(([o, v, n]) => n === 4 ? ch.setUint32(o, v, true) : ch.setUint16(o, v, true));
    parts.push(new Uint8Array(lh.buffer), name, data); cen.push(new Uint8Array(ch.buffer), name);
    off += 30 + name.length + data.length;
  }
  const cs = cen.reduce((a, x) => a + x.length, 0), end = new DataView(new ArrayBuffer(22));
  [[0, 0x06054b50, 4], [4, 0, 2], [6, 0, 2], [8, files.length, 2], [10, files.length, 2], [12, cs, 4], [16, off, 4], [20, 0, 2]].forEach(([o, v, n]) => n === 4 ? end.setUint32(o, v, true) : end.setUint16(o, v, true));
  return new Blob([...parts, ...cen, new Uint8Array(end.buffer)], {type: 'application/zip'});
}
async function wkeInflate(u) {
  const s = new Blob([u]).stream().pipeThrough(new DecompressionStream('deflate-raw'));
  return new Uint8Array(await new Response(s).arrayBuffer());
}
// the entries of a ZIP: [{name, method, flags, csize, usize, data()}]; null when it is not one
function wkeUnzip(buf) {
  const dv = new DataView(buf.buffer, buf.byteOffset, buf.byteLength), n = buf.length;
  let e = -1;
  for (let i = n - 22; i >= Math.max(0, n - 65557); i--) if (dv.getUint32(i, true) === 0x06054b50) { e = i; break; }
  if (e < 0) return null;
  const count = dv.getUint16(e + 10, true), out = [];
  let p = dv.getUint32(e + 16, true);
  const utf8 = new TextDecoder('utf-8');
  for (let k = 0; k < count; k++) {
    if (p + 46 > n || dv.getUint32(p, true) !== 0x02014b50) return null;
    const flags = dv.getUint16(p + 8, true), method = dv.getUint16(p + 10, true), csize = dv.getUint32(p + 20, true), usize = dv.getUint32(p + 24, true);
    const nl = dv.getUint16(p + 28, true), xl = dv.getUint16(p + 30, true), cl = dv.getUint16(p + 32, true), lo = dv.getUint32(p + 42, true);
    const name = utf8.decode(buf.subarray(p + 46, p + 46 + nl));
    out.push({name, flags, method, csize, usize, data: () => {
      if (lo + 30 > n || dv.getUint32(lo, true) !== 0x04034b50) throw new Error('zip');
      const st = lo + 30 + dv.getUint16(lo + 26, true) + dv.getUint16(lo + 28, true);
      if (st + csize > n) throw new Error('zip');
      return buf.subarray(st, st + csize);
    }});
    p += 46 + nl + xl + cl;
  }
  return out;
}
function wkeSave(blob, name) { const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = name; document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 30000); }
// every page of the space, decrypted, as .md files in folders (like the server's export of an open space)
async function wkeExport(sp) {
  if (!wkeReady(sp)) { if (!await e2eEnsure()) return false; await wkeKeys(sp, true); }
  if (!wkeReady(sp)) throw wkeErrLocked();
  await wk_load(sp, true);
  if (WKE.locked[sp]) throw wkeErr(tr('{0} pages of this space cannot be opened with your key.', WKE.locked[sp]), 'wiki_e2e_unreadable');
  const te = e2eTEnc(), pages = wk_pages(sp).filter(p => p.path);
  wkeSave(wkeZip(pages.map(p => ({name: p.path + '.md', data: te.encode(p.body || '')}))), 'wiki.zip');
  return pages.length;
}
// a ZIP of .md files into the space: the server's limits and path cleaning, names taken are skipped, every page created
// encrypted (one call each; a "too many requests" waits and tries again). Answers {created: ids, skipped: names}.
async function wkeImport(sp, file) {
  if (!wkeReady(sp)) { if (!await e2eEnsure()) return {created: [], skipped: []}; await wkeKeys(sp, true); }
  if (!wkeReady(sp)) throw wkeErrLocked();
  if (file.size > WKE_ZIP.total + 1) throw wkeErr(tr('The archive is too large'), 'bad');
  const ents = wkeUnzip(new Uint8Array(await file.arrayBuffer()));
  if (!ents) throw wkeErr(tr('This is not a ZIP file'), 'bad');
  const files = ents.filter(x => !x.name.endsWith('/'));
  if (files.length > WKE_ZIP.files) throw wkeErr(tr('Too many files (at most {0})', WKE_ZIP.files), 'bad');
  if (files.reduce((a, x) => a + x.usize, 0) > WKE_ZIP.total) throw wkeErr(tr('The archive is too large'), 'bad');
  const created = [], skipped = [], seen = new Set(), td = new TextDecoder('utf-8');
  for (const x of files) {
    const nm = x.name.slice(0, 200);
    if (!x.name.toLowerCase().endsWith('.md') || x.usize > WKE_ZIP.file || x.name.includes('__MACOSX') || (x.flags & 1) || ![0, 8].includes(x.method)) { skipped.push(nm); continue; }
    let path, text;
    try {
      path = wkeClean(x.name);
      const raw = x.method === 8 ? await wkeInflate(x.data()) : x.data();
      text = td.decode(raw.subarray(0, WKE_ZIP.file)).replace(/^﻿/, '');
    } catch { skipped.push(nm); continue; }
    if (seen.has(path.toLowerCase()) || wk_byPath(sp, path)) { skipped.push(nm); continue; }
    for (let tries = 0; ; tries++) {
      try {
        const r = await wkeApi('POST', '/api/wiki/pages', {space: sp, path, body: text}, sp);
        created.push(r.id); seen.add(path.toLowerCase());
        break;
      } catch (e) {
        if (e?.status === 429 && tries < 5) { await new Promise(res => setTimeout(res, 1500 * (tries + 1))); continue; }
        if (e instanceof Offline || e?.code === 'wiki_e2e_locked' || e?.status === 403) throw e;
        skipped.push(nm); break;
      }
    }
  }
  return {ok: true, created, updated: [], skipped: skipped.slice(0, 200)};
}

// ------------------------------------------------------------------ switching on / off, re-encryption (todo / bulk / finish)
// one value in the target format of mode: encrypting = a cipher of the current generation, decrypting = the plain text, on
// (re-encryption after a key change) = an older cipher opened with its generation and encrypted with the current one
async function wkeConv(sp, mode, gen, f, v) {
  if (mode === 'decrypting') return wkeIs(v) ? wkeDec(sp, f, v) : v;
  if (le2eParse(v)?.g === gen) return v;
  if (wkeIs(v) && mode === 'on') return wkeEnc(sp, f, await wkeDec(sp, f, v));
  return wkeEnc(sp, f, f === 'path' ? wkeClean(v) : String(v));
}
async function wkeMigrate(sp, onProgress, opts = {}) {
  if (WKE.busy[sp]) return WKE.busy[sp];
  const run = (async () => {
    let total = null, last = -1, blank = false, kind = null, reenc = 0, spins = 0;
    const bad = new Set();
    const prog = (done, tot) => {
      WKE.prog[sp] = {kind, done, total: tot};
      onProgress?.({done, total: tot});
      document.dispatchEvent(new CustomEvent('wke:progress', {detail: {space: sp, done, total: tot, kind}}));
    };
    try {
      for (;;) {
        const todo = await rawFetch('GET', '/api/wiki/e2e/todo?space=' + encodeURIComponent(sp) + '&limit=200');
        const mode = todo.mode || WKE.st[sp]?.mode, gen = todo.gen ?? WKE.st[sp]?.gen;
        kind = mode === 'on' ? 'reenc' : mode; reenc = todo.reenc || 0;
        const left = +todo.left?.pages || 0;
        if (total === null) total = left;
        total = Math.max(total, left);
        prog(total - left, total);
        if (!left) break;
        if (left === last && ++spins > 2) throw wkeErr(tr('Encryption of this space stopped without progress. Try again later.'), 'wiki_e2e_stuck');
        if (mode !== 'decrypting') await wkeKeys(sp, !wkeReady(sp));
        const rows = [];
        for (const r of todo.pages || []) {
          const o = {id: r.id};
          let n = 0;
          for (const f of ['path', 'body']) {
            let v = r[f]; if (v == null) continue;
            try { v = await wkeConv(sp, mode, gen, f, v); }
            catch (e) {
              if (e?.code === 'wiki_e2e_locked') throw e;
              if (mode === 'encrypting' || !blank) { bad.add(r.id + ':' + f); continue; }
              v = f === 'path' ? tr('Unreadable page {0}', r.id) : '';  // taken over as empty (a path is never empty)
            }
            o[f] = v; n++;
          }
          if (n) rows.push(o);
        }
        if (!rows.length) {
          if (mode !== 'encrypting' && bad.size && !blank && (mode === 'decrypting' || opts.ask)) {
            const yes = typeof askConfirm === 'function' && await askConfirm(tr('Texts that cannot be decrypted'),
              tr('{0} texts of this space cannot be decrypted with the keys you hold. Take them over as empty texts? They cannot be restored.', bad.size), {ok: tr('Take over as empty'), danger: true});
            if (yes) { blank = true; last = -1; bad.clear(); continue; }
            if (mode === 'decrypting') throw wkeErr(tr('{0} texts of this space cannot be decrypted. The space stays locked until they are taken over as empty.', bad.size), 'wiki_e2e_unreadable');
          }
          if (mode === 'on' && bad.size) { WKE.unread[sp] = bad.size; wkeChange(sp); }
          throw wkeErr(tr('{0} texts of this space cannot be decrypted with the keys you hold.', bad.size), 'wiki_e2e_unreadable');
        }
        last = left;
        const j = await rawFetch('POST', '/api/wiki/e2e/bulk', {space: sp, pages: rows});
        if (j?.renamed?.length) WKE.renamed = (WKE.renamed || 0) + j.renamed.length;
      }
      if (kind !== 'reenc' || reenc) await rawFetch('POST', '/api/wiki/e2e/finish', {space: sp});
      delete WKE.info[sp]; delete WKE.unread[sp];
      if (kind === 'decrypting') { wkeSet(sp, null); }
      else await wkeInfo(sp, true).catch(() => {});
      return true;
    } finally {
      delete WKE.prog[sp];
      wkeAfter(sp);
    }
  })();
  WKE.busy[sp] = run;
  try { return await run; } finally { delete WKE.busy[sp]; }
}
async function wkeReenc(sp, onProgress, opts) {
  if (wkeMode(sp) !== 'on') return false;
  if (!await e2eEnsure()) return false;
  await wkeKeys(sp, true);
  if (!wkeReady(sp)) throw wkeErrLocked();
  return wkeMigrate(sp, onProgress, opts);
}
// switching on: a new space key, wrapped for every member with their encryption set up (H4 checked), the others wait (E7)
async function wkeStart(sp, onProgress) {
  if (!await e2eEnsure()) return false;
  wkeBadPub();
  const info = await wkeInfo(sp, true);
  if (info.mode) return wkeResume(sp, onProgress);
  if (!info.can_manage) throw wkeErr(tr('Only admins of the organisation can switch this on'), 'wiki_e2e_denied');
  const gen = (info.gen || 0) + 1, raw = e2eRand(32), keys = [];
  try {
    const people = (info.members || []).filter(m => m.has_keys);
    if (!people.some(m => m.user_id === S.me.id)) people.unshift({user_id: S.me.id});
    // the salt / AAD need the space's number: a space switched on for the first time gets its row first (start with
    // prepare: only the row, mode stays open)
    let sid = info.space_id;
    if (sid == null) sid = (await rawFetch('POST', '/api/wiki/e2e/start', {space: sp, prepare: true})).space_id ?? null;
    if (sid == null) throw wkeErr(tr('Not possible right now'), 'wiki_e2e_sid');
    for (const m of people) keys.push({user_id: m.user_id, wrapped: await wkeWrap(raw, sid, gen, m.user_id, await wkePubFor(sp, m.user_id))});
    const j = await rawFetch('POST', '/api/wiki/e2e/start', {space: sp, keys});
    WKE.info[sp] = j; wkeSetInfo(sp, j);
    (WKE.keys[sp] || (WKE.keys[sp] = {}))[j.gen ?? gen] = await crypto.subtle.importKey('raw', raw, {name: 'AES-GCM'}, false, ['encrypt', 'decrypt']);
    WKE.tried[sp] = String(j.gen ?? gen);
  } finally { raw.fill(0); }
  return wkeMigrate(sp, onProgress);
}
async function wkeStop(sp, password, onProgress) {
  if (!await e2eEnsure()) return false;
  await wkeKeys(sp, true);
  await rawFetch('POST', '/api/wiki/e2e/stop', {space: sp, password});
  delete WKE.info[sp];
  if (WKE.st[sp]) WKE.st[sp].mode = 'decrypting';
  return wkeMigrate(sp, onProgress);
}
async function wkeResume(sp, onProgress) {
  const info = await wkeInfo(sp, true);
  if (info.mode === 'on' && info.can_manage && (+info.left?.pages || 0) > 0) return wkeReenc(sp, onProgress);
  if (info.mode !== 'encrypting' && info.mode !== 'decrypting') return false;
  if (!await e2eEnsure()) return false;
  await wkeKeys(sp, true);
  return wkeMigrate(sp, onProgress);
}
// the browser of an unlocked admin / owner continues on its own (once per space and state in this page, never in a loop):
// an interrupted switch (e2e_by or can_manage), a pending key change (not for keys first seen here, M1), a re-encryption
function wkeAuto(sp) {
  const s = WKE.st[sp];
  if (!s || WKE.busy[sp] || typeof e2eUnlocked !== 'function' || !e2eUnlocked()) return;
  const tag = `${s.mode}|${s.gen}|${s.rotate || 0}|${s.reenc || 0}`;
  if (WKE.rot[sp] === tag) return;
  WKE.rot[sp] = tag;
  (async () => {
    try {
      if (s.mode === 'encrypting' || s.mode === 'decrypting') {
        const info = await wkeInfo(sp, true);
        if (info.can_manage || info.by === S.me?.id) await wkeResume(sp);
        return;
      }
      if (s.mode !== 'on' || !s.can_manage) return;
      if (s.rotate > 0 && !await wkeRotate(sp)) return;
      const info = await wkeInfo(sp, true);
      if (info.mode === 'on' && info.can_manage && (+info.left?.pages || 0) > 0) await wkeReenc(sp);
    } catch (e) { console.warn('wke: auto', e?.message); wkeChange(sp); }
  })();
}
// the wiki data of a space is old after a switch / key change: index and page again, redraw
function wkeAfter(sp) {
  if (typeof wk_after === 'function') wk_after(sp);
  wkeChange(sp);
}
// unlock: passphrase if needed, the space's keys, the index and the open page again
async function wkeUnlock(sp) {
  if (!await e2eEnsure()) return false;
  await wkeInfo(sp, true).catch(() => {});
  await wkeKeys(sp, true);
  wkeAfter(sp);
  return wkeReady(sp);
}
// lock / logout (e2e.js): every decrypted path and text of an encrypted space leaves this page's memory
function wkeWipe() {
  const sps = Object.keys(WKE.st);
  WKE.memo.clear(); WKE.keys = {}; WKE.info = {}; WKE.tried = {}; WKE.unread = {}; WKE.rot = {};
  if (typeof WK === 'object') {
    for (const sp of sps) delete WK.idx[sp];
    if (WK.pg && sps.includes(WK.pg.space)) { WK.pg = null; WK.edit = false; WK.dirty = false; }
    WK.men = {};
  }
  // the undo steps of encrypted spaces name pages (labels, old names): they go too
  if (typeof HIST !== 'undefined') for (const k of ['undo', 'redo']) HIST[k] = (HIST[k] || []).filter(e => !(e.wsp && sps.includes(e.wsp)));
  for (const sp of sps) wkeChange(sp);
}

// ------------------------------------------------------------------ the view: lock box, bars, marks (wiki.js viewWiki)
const wkePbar = r => typeof le2u_pbar === 'function' ? le2u_pbar(r) : '';
function wkeMark(sp) { return wkeOn(sp) ? `<span class="wkemark" title="${esc(tr('Encrypted in the browser'))}" aria-label="${esc(tr('Encrypted in the browser'))}">${ic('lock', 's')}</span>` : ''; }
// the box instead of the tree / the page while the space cannot be read here ('' = readable)
function wkeLockHtml(sp, page) {
  const s = WKE.st[sp]; if (!s?.mode) return '';
  if (s.mine === false && s.mode === 'on') return `<div class="wkelock"><div class="lnph">${ic('lock')}<div><b>${esc(tr('Encrypted in the browser'))}</b><span class="muted">${esc(tr('Key pending – an admin of the organisation releases it'))}</span></div></div></div>`;
  if (!wkeReady(sp)) {
    if (s.mode !== 'on' && !page && !WKE.locked[sp]) return '';  // a switch is running: the pages not converted yet stay readable
    return `<div class="wkelock"><button type="button" class="lnph lnopen" data-wke="unlock" data-sp="${esc(sp)}">${ic('lock')}<div><b>${esc(tr('Locked'))}</b><span class="muted">${esc(tr('The pages of this space are encrypted in the browser. Unlock to read them.'))}</span></div></button></div>`;
  }
  if (page) return `<div class="wkelock"><div class="lnph">${ic('lock')}<div><b>${esc(tr('Locked'))}</b><span class="muted">${esc(tr('This page cannot be opened with your key.'))}</span></div></div></div>`;
  return '';
}
// the lines above the tree: a running switch, people waiting for the key, a key change after someone left
function wkeBarHtml(sp, inDlg) {
  const s = WKE.st[sp]; if (!s?.mode) return '';
  const r = WKE.prog[sp], out = [];
  if (s.mode === 'encrypting' || s.mode === 'decrypting' || (r && r.kind !== 'reenc')) {
    const st = s.mode === 'decrypting' ? tr('Being decrypted') : tr('Being encrypted');
    out.push(`<div class="shint lhint keep wkebar" data-sp="${esc(sp)}">${ic('lock', 's')} <span>${esc(st)}</span><span class="wkeprog">${r ? wkePbar(r) : ''}</span>${!r && s.can_manage ? `<button type="button" class="btn sm" data-wke="resume" data-sp="${esc(sp)}">${esc(tr('Continue'))}</button>` : ''}</div>`);
  }
  if (s.mode === 'on' && s.can_manage && s.pending > 0 && !inDlg) out.push(`<div class="shint lhint keep wkebar">${esc(trn('{0} person is waiting for the key', '{0} people are waiting for the key', s.pending))}<button type="button" class="btn sm" data-wke="release" data-sp="${esc(sp)}">${esc(tr('Release'))}</button></div>`);
  if (s.mode === 'on' && (s.rotate > 0 || s.reenc > 0)) {
    const run = r && r.kind === 'reenc';
    const btn = !s.can_manage || run ? '' : s.rotate > 0 ? `<button type="button" class="btn sm" data-wke="rotate" data-sp="${esc(sp)}">${esc(tr('Change the key now'))}</button>` : `<button type="button" class="btn sm" data-wke="reenc" data-sp="${esc(sp)}">${esc(tr('Continue'))}</button>`;
    out.push(`<div class="shint lhint keep wkebar wkerot" data-sp="${esc(sp)}">${ic('alert', 's')} <span>${esc(tr('A member has left the organisation. The key of the knowledge pages is being changed; until everything is encrypted again, former members can still decrypt older pages with their old key.'))}</span>`
      + (run ? `<span class="wkeprog">${wkePbar(r)}</span>` : '') + (!run && WKE.unread[sp] ? `<span class="e2ewarn" role="alert">${esc(tr('{0} texts of this space cannot be decrypted with the keys you hold.', WKE.unread[sp]))}</span>` : '') + btn + '</div>');
  }
  if (wkeReady(sp) && WKE.locked[sp]) out.push(`<div class="e2ewarn wkebar" role="alert">${ic('alert', 's')} ${esc(tr('{0} pages of this space cannot be opened with your key.', WKE.locked[sp]))}</div>`);
  return out.join('');
}
document.addEventListener('wke:progress', e => {
  const d = e.detail || {}; if (!d.space) return;
  $$(`.wkebar[data-sp="${CSS.escape(d.space)}"] .wkeprog, .wkedlg[data-sp="${CSS.escape(d.space)}"] .wkeprog`).forEach(x => { x.innerHTML = wkePbar({done: d.done, total: d.total}); });
});
document.addEventListener('wke:change', e => {
  if (typeof S === 'object' && S.route?.mod === 'wiki' && typeof viewSafeRender === 'function') viewSafeRender();
  const sp = e.detail?.space;
  $$(`.wkedlg[data-sp="${CSS.escape(sp || '')}"]`).forEach(x => x._wkeDraw?.());
});
document.addEventListener('click', async e => {
  const b = e.target.closest?.('[data-wke]'); if (!b) return;
  e.preventDefault(); e.stopPropagation();
  const a = b.dataset.wke, sp = b.dataset.sp;
  try {
    if (a === 'unlock') {
      const ok = await wkeUnlock(sp);
      if (!ok && WKE.st[sp]?.mine !== false && e2eUnlocked()) toast(tr('The space key could not be opened. Compare the safety numbers with the members.'));
    } else if (a === 'resume') wkeRun(sp, 'resume');
    else if (a === 'release') await wkeReleaseAll(sp);
    else if (a === 'rotate' || a === 'reenc') {
      if (!await e2eEnsure()) return;
      b.disabled = true;
      if (a === 'rotate') { if (await wkeRotate(sp, true)) await wkeReenc(sp, null, {ask: true}); }
      else await wkeReenc(sp, null, {ask: true});
      wkeAfter(sp);
    }
  } catch (x) { if (x?.message) toast(x.message); b.disabled = false; }
}, true);
async function wkeReleaseAll(sp) {
  const j = await wkeInfo(sp, true), mem = new Map((j.members || []).map(m => [m.user_id, m]));
  const ids = (j.pending || []).map(p => p.user_id).filter(uid => mem.get(uid)?.has_keys && !le2eKeyChanged(uid));
  if (!ids.length) { toast(tr('Nobody waiting has set up encryption yet')); return 0; }
  const r = await wkeRelease(sp, ids);
  const n = ids.length - (r?.skipped?.length || 0);
  toast(trn('Key released for {0} person', 'Key released for {0} people', n));
  wkeAfter(sp);
  return n;
}
// kind: start | stop | resume, with the progress in the bar and the dialog
async function wkeRun(sp, kind, password) {
  if (WKE.busy[sp]) return false;
  let ok = false;
  try {
    WKE.prog[sp] = {kind: kind === 'resume' ? wkeMode(sp) : kind === 'stop' ? 'decrypting' : 'encrypting', done: 0, total: 0};
    wkeChange(sp);
    await (kind === 'stop' ? wkeStop(sp, password) : kind === 'start' ? wkeStart(sp) : wkeResume(sp));
    ok = true;
    toast(kind === 'stop' || (kind === 'resume' && !wkeOn(sp)) ? tr('The knowledge pages of this space are readable on the server again') : tr('The knowledge pages of this space are encrypted in the browser'));
    if (WKE.renamed) { toast(trn('{0} page got a new name (the name was taken)', '{0} pages got a new name (the names were taken)', WKE.renamed)); WKE.renamed = 0; }
  } catch (x) { if (x?.message) toast(x.message); }
  finally { delete WKE.prog[sp]; wkeAfter(sp); }
  return ok;
}

// ------------------------------------------------------------------ the dialog "Encryption…" of a space (wiki menu)
function wkeMemState(j, m) {
  if ((m.key_gens || []).includes(j.gen) && j.mode) return 'ok';
  if (!m.has_keys) return 'none';
  return j.mode ? 'wait' : 'set';
}
function wkeMembersHtml(j, chg) {
  const lab = {ok: tr('Key present'), wait: tr('Key pending'), none: tr('Has not set up encryption yet'), set: tr('Encryption set up')};
  const icn = {ok: 'key', wait: 'hourglass', none: 'alert', set: 'check'};
  return `<ul class="le2umem wkemem" aria-label="${esc(tr('Members'))}">${(j.members || []).map(m => {
    const st = wkeMemState(j, m), me = S.me && m.user_id === S.me.id, c = chg.has(m.user_id);
    return `<li class="${st === 'none' ? 'no' : 'ok'}"><span>${esc(m.name)}${me ? ' ' + esc(tr('(me)')) : ''}</span><span class="le2ust ${st === 'set' ? 'ok' : st}">${ic(icn[st], 's')}<span>${esc(lab[st])}</span></span>`
      + (c ? `<span class="e2ewarn" role="alert">${esc(tr('The key of {0} has changed.', m.name))} <button type="button" class="btn sm" data-wkd="accept" data-uid="${m.user_id}">${esc(tr('Understood'))}</button></span>` : '')
      + (st === 'wait' && j.can_manage && !me && !c ? `<button type="button" class="btn sm" data-wkd="release" data-uid="${m.user_id}">${esc(tr('Release'))}</button>` : '')
      + (!me && m.pub ? `<button type="button" class="iconbtn" data-wkd="safety" data-uid="${m.user_id}" title="${esc(tr('Safety number'))}" aria-label="${esc(tr('Safety number of {0}', m.name))}">${ic('key', 's')}</button>` : '') + '</li>';
  }).join('')}</ul>`;
}
const wkeRuleHtml = () => `<p class="shint lhint keep le2uexp">${esc(tr('End-to-end in the browser: the server only sees encrypted pages. Limit: a manipulated server could deliver changed app code; members keep what they have seen.'))}</p>`;
function wkeNoteHtml() {
  return `<ol class="le2unote">
    <li>${esc(tr('Title and text of every page of this space are encrypted in the browser. Search, backlinks and “Mentioned in” then only work in the browser.'))}</li>
    <li><b>${esc(tr('Agents have no access to this space.'))}</b></li>
    <li>${esc(tr('The keys hang on your passphrase and your recovery code. Without both the pages are lost; nobody can restore them, not even the operator.'))}</li>
    <li>${esc(tr('Protects against a database leak, backups and the operator. Does not protect against a manipulated server (the app code comes from the server) or against members who have already seen the pages.'))}</li>
    <li>${esc(tr('Exporting and importing a ZIP runs in the browser.'))}</li>
  </ol>`;
}
function wkeDlgHtml(sp, j, chg) {
  const mode = j.mode || null, r = WKE.prog[sp], setup = typeof e2eReady === 'function' && e2eReady();
  const miss = (j.members || []).filter(m => !m.has_keys);
  let head;
  if (r || mode === 'encrypting' || mode === 'decrypting') {
    head = `<div class="row"><span class="tfastate">${esc((r ? r.kind === 'decrypting' : mode === 'decrypting') ? tr('Being decrypted') : tr('Being encrypted'))}</span></div><div class="wkeprog">${r ? wkePbar(r) : ''}</div>`
      + (r ? `<div class="shint lhint">${esc(tr('Keep this window open. If it is closed, it continues as soon as you open the knowledge pages again.'))}</div>`
        : `<div class="shint lhint">${esc(tr('Interrupted. It continues as soon as you open the knowledge pages again.'))}</div>${j.can_manage ? `<div class="row"><span></span><button type="button" class="btn sm pri" data-wkd="resume">${esc(tr('Continue'))}</button></div>` : ''}`);
  } else if (mode === 'on') {
    const mine = (j.keys || []).some(k => k.gen === j.gen);
    head = `<div class="row"><span class="tfastate on">${ic('lock', 's')} ${esc(tr('On'))}</span><span class="muted">${esc(tr('Titles and texts of the pages are encrypted in the browser.'))}</span></div>`
      + (mine ? '' : `<div class="shint lhint keep">${esc(tr('Key pending – an admin of the organisation releases it'))}</div>`)
      + (j.can_manage && (j.pending || []).length ? `<div class="row"><span class="muted">${esc(trn('{0} person is waiting for the key', '{0} people are waiting for the key', j.pending.length))}</span><button type="button" class="btn sm" data-wkd="release-all">${esc(tr('Release'))}</button></div>` : '')
      + wkeBarHtml(sp, true);
  } else {
    const why = !j.can_manage ? tr('Only admins of the organisation can switch this on') : !setup ? tr('Set up your encryption first') : '';
    head = `<div class="row"><span class="tfastate">${esc(tr('Off'))}</span></div>`
      + (why ? `<div class="shint lhint keep">${esc(why)}${j.can_manage && !setup ? ` <button type="button" class="linkbtn" data-wkd="setup">${esc(tr('Set up'))}</button>` : ''}</div>` : '')
      + wkeNoteHtml()
      + (miss.length && sp !== 'private' ? `<p class="shint keep">${esc(tr('{0}: not set up yet. They go on the waiting list and cannot read the pages until they have set it up and the key is released to them.', miss.map(m => m.name).join(', ')))}</p>` : '')
      + (why ? '' : `<label class="chkl le2uack"><input type="checkbox" id="wke-ack"> ${esc(tr('I have read this'))}</label><div class="row"><span></span><button type="button" class="btn sm pri" data-wkd="start" disabled>${esc(tr('Encrypt the knowledge pages'))}</button></div>`);
  }
  const off = !mode && !r;
  return `${head}${off ? '' : wkeRuleHtml()}${(j.members || []).length > 1 || mode ? `<h4>${esc(tr('Members'))}</h4>${wkeMembersHtml(j, chg)}` : ''}`
    + (mode === 'on' && j.can_manage && !r ? `<div class="row le2uacts"><span></span><button type="button" class="btn sm" data-wkd="stop">${esc(tr('Switch off…'))}</button></div>` : '');
}
async function wkeDlg(sp) {
  let j;
  try { j = await wkeInfo(sp, true); } catch (x) { toast(x?.message || tr('Not possible right now')); return; }
  const chg = async () => new Set((j.members || []).filter(m => m.pub && m.user_id !== S.me?.id && le2eKeyChanged(m.user_id)).map(m => m.user_id));
  let changed = await chg();
  await askDialog({title: tr('Encryption of the knowledge pages · {0}', wk_spaceName(sp)), html: `<div class="wkedlg" data-sp="${esc(sp)}"></div>`, ok: tr('Close'), after: md => {
    $('[data-cd="no"]', md)?.remove();
    const box = $('.wkedlg', md);
    const draw = () => { if (box.isConnected) box.innerHTML = wkeDlgHtml(sp, j, changed); };
    box._wkeDraw = async () => { try { j = await wkeInfo(sp, true); changed = await chg(); } catch { /* offline */ } draw(); };
    draw();
    box.addEventListener('change', e => { if (e.target.id === 'wke-ack') { const s = $('[data-wkd="start"]', box); if (s) s.disabled = !e.target.checked; } });
    box.addEventListener('click', async e => {
      const b = e.target.closest('[data-wkd]'); if (!b) return;
      e.preventDefault(); e.stopPropagation();
      const a = b.dataset.wkd, uid = +b.dataset.uid;
      try {
        if (a === 'setup') { if (typeof e2eEnsure === 'function') await e2eEnsure(); box._wkeDraw(); }
        else if (a === 'start') { if (!$('#wke-ack', box)?.checked) return; b.disabled = true; wkeRun(sp, 'start').finally(() => box._wkeDraw()); draw(); }
        else if (a === 'resume') { wkeRun(sp, 'resume').finally(() => box._wkeDraw()); draw(); }
        else if (a === 'stop') { await wkeStopDlg(sp); box._wkeDraw(); }
        else if (a === 'release' || a === 'release-all') {
          b.disabled = true;
          if (a === 'release-all') await wkeReleaseAll(sp);
          else { const r = await wkeRelease(sp, [uid]); toast(trn('Key released for {0} person', 'Key released for {0} people', 1 - (r?.skipped?.length || 0))); wkeAfter(sp); }
          box._wkeDraw();
        } else if (a === 'safety') { if (typeof le2u_safetyDlg === 'function') le2u_safetyDlg(uid, (j.members || []).find(m => m.user_id === uid)?.name || ''); }
        else if (a === 'accept') { le2eAcceptKey(uid); WKE.tried = {}; changed.delete(uid); draw(); }
      } catch (x) { if (x?.message) toast(x.message); b.disabled = false; }
    });
  }});
}
// the way back: only who manages the space, with the account password (like the lists)
async function wkeStopDlg(sp) {
  if (!await askConfirm(tr('Switch off the encryption of the knowledge pages?'), tr('Your browser decrypts every page and stores it readable again. Then the search, backlinks on the server and agents work again. Old backups keep the encrypted pages.'), {ok: tr('Switch off')})) return false;
  if (!await e2eEnsure()) return false;
  let password = '';
  if (E2E.st?.password !== false) {
    const p = await pwPrompt(tr('Confirm with your password'), {text: esc(tr('Switching off the encryption of the knowledge pages needs your account password.'))});
    if (!p) return false;
    password = p.password;
  }
  return wkeRun(sp, 'stop', password);
}

// ------------------------------------------------------------------ Settings > Administration > Encryption (cryptscope.js)
// the encrypted knowledge spaces by name (asked once per opening), with the honest word about agents
function wkeScopeHtml() {
  if (!S.me || S.me.kind === 'agent' || typeof wk_spaces !== 'function') return '';
  if (!WKE.probe) {
    WKE.probe = Promise.all(wk_spaces().map(sp => wkeInfo(sp, true).catch(() => null))).finally(() => {
      setTimeout(() => { WKE.probe = null; }, 60000);
      $$('.wkescope').forEach(x => { x.outerHTML = wkeScopeBox(); });
    });
  }
  return wkeScopeBox();
}
function wkeScopeBox() {
  const sps = Object.keys(WKE.st).filter(sp => WKE.st[sp]?.mode);
  if (!sps.length) return '<div class="wkescope" hidden></div>';
  return `<div class="pmcs br wkescope"><b>${ic('lock', 's')} ${esc(tr('Encrypted in the browser (knowledge pages)'))}</b><ul>${sps.map(sp => `<li>${esc(wk_spaceName(sp))}</li>`).join('')}</ul><small class="muted pmcsn">${esc(tr('Agents have no access to these knowledge pages.'))}</small></div>`;
}

// a news entry "the key of the knowledge pages of <organisation> was released to you" (collab.js newsText)
function wkeNewsText(it, who, q) {
  return tr('{0} released the key for the knowledge pages of {1} to you', who, q(it.data?.name || tr('Organisation')));
}
