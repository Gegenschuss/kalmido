/* Kalmido web client: the lock per list -- data layer (2.64.1, #1817). Classic script sharing the global scope (load order:
   index.html). List keys (fetch, unwrap, wrap for members), encrypting / decrypting the texts of a locked list, the hooks
   where tasks enter and leave the client state (state, delta, answers, cache, outbox), switching on / off (migration).
   Built on e2e.js (2.42.0): the person's keys E2E.priv / E2E.ckey; server side kalmido/collab/liste2e.py. */
'use strict';

// ------------------------------------------------------------------ state
// on: ids of the lists that are not open (mode encrypting | on | decrypting); keys: list id -> {gen: CryptoKey (AES-GCM, not
// extractable)}; info: list id -> the answer of GET /api/lists/<id>/e2e; memo: cipher -> plain text (this page only, never stored);
// rev: "<lid>|<field>|<plain>" -> its newest cipher (the _prev of an edit); q: ciphers waiting for their decryption -> {lid, cands};
// bad: ciphers that did not open; changed: user id -> the new key id of a person whose key differs from the remembered one;
// objs: WeakRefs of every object that carries ciphers (_enc), to fill in after a decryption and to wipe on lock
const LE2E = {on: new Set(), sig: {}, keys: {}, info: {}, infoP: {}, tried: {}, memo: new Map(), rev: new Map(), q: new Map(), bad: new Set(),
  changed: {}, objs: new Set(), kickT: 0, draining: false, again: false, busy: {}, got: new Map(), badL: new Map()};
const LE2E_PRE = 'e2e1:';
// the props that carry a cipher -> the field names of their AAD (tried in order: a task title and a note title share "title")
const LE2E_CANDS = {title: ['title', 'note_title'], content: ['content'], url: ['url'], snippets: ['snippets'], body: ['comment', 'note_body'], name: ['section', 'file_name'], value: ['field']};  // 2.64.2 B (#1817): + the names of list files
const LE2E_PROPS = Object.keys(LE2E_CANDS);
const LE2E_TASK = ['title', 'content', 'url', 'snippets'];
// the names of the protocol are function declarations (window properties): other parts and tests can wrap or stub them
function le2eIs(v) { return typeof v === 'string' && v.startsWith(LE2E_PRE); }
function le2eMode(lid) { return listById(lid)?.e2e || null; }
function le2eOn(lid) { return !!le2eMode(lid); }
function le2eReady(lid) { const l = listById(lid); return !!(l && l.e2e && LE2E.keys[lid]?.[l.e2e_gen]); }
function le2eLocked(t) { return !!t && t._le2e === 'locked'; }
const le2eChange = lid => document.dispatchEvent(new CustomEvent('le2e:change', {detail: {lid}}));
function le2eErr(msg, code) { const e = new Error(msg); e.code = code; return e; }
const le2eErrLocked = () => le2eErr(tr('Unlock first: this list is encrypted in the browser.'), 'list_e2e_locked');

// ------------------------------------------------------------------ content crypto
// AES-256-GCM with the list key of generation g; AAD binds list, generation and field; the plain text is padded to a multiple of
// 64 bytes (L1: 0x80, then zeros) so the length of a cipher tells little about the text
const le2eAad = (lid, g, f) => `kalmido-list:v1:${lid}:${g}:${f}`;
function le2ePad(u) {
  const out = new Uint8Array(Math.ceil((u.length + 1) / 64) * 64);
  out.set(u); out[u.length] = 0x80;
  return out;
}
function le2eUnpad(u) {
  let i = u.length - 1;
  while (i >= 0 && u[i] === 0) i--;
  if (i < 0 || u[i] !== 0x80) throw new Error('pad');
  return u.subarray(0, i);
}
function le2eParse(c) {
  if (!le2eIs(c)) return null;
  try { const o = JSON.parse(c.slice(LE2E_PRE.length)); return o && o.v === 1 && Number.isInteger(o.g) && typeof o.iv === 'string' && typeof o.ct === 'string' ? o : null; } catch { return null; }
}
function le2eRemember(lid, field, plain, cipher) {
  LE2E.memo.set(cipher, plain);
  LE2E.rev.set(`${lid}|${field}|${plain}`, cipher);
}
// text -> "e2e1:{v,g,iv,ct}" with the list's current generation ("" stays ""; a cipher stays as it is)
async function le2eEnc(lid, field, text, asText) {
  if (text == null || text === '') return '';
  const s = String(text); if (!asText && le2eParse(s)) return s;  // review 2 (L5): a typed "e2e1:..." is a text
  const l = listById(lid), g = l?.e2e_gen;
  let key = LE2E.keys[lid]?.[g];
  if (!key && l?.e2e) key = (await le2eKeys(lid))[g];
  if (!key) throw le2eErrLocked();
  const b = await e2eSeal(key, le2ePad(e2eTEnc().encode(s)), le2eAad(lid, g, field));
  const c = LE2E_PRE + JSON.stringify({v: 1, g, iv: b.iv, ct: b.ct});
  le2eRemember(lid, field, s, c);
  return c;
}
// one cipher with the keys at hand: the text, null (did not open) or undefined (no key of its generation here)
async function le2eTry(lid, c, cands, ks) {
  if (LE2E.memo.has(c)) return LE2E.memo.get(c);
  const o = le2eParse(c); if (!o) return null;
  const key = ks?.[o.g]; if (!key) return undefined;
  for (const f of cands) {
    try {
      const s = e2eTDec().decode(le2eUnpad(await e2eOpen(key, {v: 1, iv: o.iv, ct: o.ct}, le2eAad(lid, o.g, f))));
      le2eRemember(lid, f, s, c);
      return s;
    } catch { /* another field, or not this list */ }
  }
  return null;
}
// cipher -> text (the generation from the cipher); throws when it cannot be opened
async function le2eDec(lid, field, cipher) {
  if (!le2eIs(cipher)) return cipher ?? '';
  if (LE2E.memo.has(cipher)) return LE2E.memo.get(cipher);
  const s = await le2eTry(lid, cipher, Array.isArray(field) ? field : [field], await le2eKeys(lid));
  if (s == null) throw le2eErr(s === undefined ? tr('You do not have the key of this list yet.') : tr('The list key could not be opened.'), 'list_e2e_key');
  return s;
}
// the plain text of a cipher known on this page (render code: synchronous, no flicker); else ''
function le2eShow(v) { return le2eIs(v) ? LE2E.memo.get(v) ?? '' : v ?? ''; }

// ------------------------------------------------------------------ list keys
// wrapping for member R by W: ECDH(priv W, pub R) -> HKDF-SHA256(salt "<lid>:<gen>", info kalmido-listkey:v1) -> AES-GCM over the
// 32 raw bytes, AAD names list, generation, R and W. Both sides derive the same key (ECDH is symmetric).
const le2eWrapAad = (lid, gen, r, w) => `kalmido-listkey:v1:${lid}:${gen}:${r}:${w}`;
async function le2eKek(pub, lid, gen) {
  const pk = await crypto.subtle.importKey('jwk', {kty: 'EC', crv: 'P-256', x: pub.x, y: pub.y}, {name: 'ECDH', namedCurve: 'P-256'}, false, []);
  const bits = await crypto.subtle.deriveBits({name: 'ECDH', public: pk}, E2E.priv, 256);
  let hk; try { hk = await crypto.subtle.importKey('raw', bits, 'HKDF', false, ['deriveKey']); } finally { new Uint8Array(bits).fill(0); }  // review 2 (L3)
  return crypto.subtle.deriveKey({name: 'HKDF', hash: 'SHA-256', salt: e2eTEnc().encode(`${lid}:${gen}`), info: e2eTEnc().encode('kalmido-listkey:v1')}, hk, {name: 'AES-GCM', length: 256}, false, ['encrypt', 'decrypt']);
}
async function le2eWrap(raw, lid, gen, uid, pub) {
  return e2eSeal(await le2eKek(pub, lid, gen), raw, le2eWrapAad(lid, gen, uid, S.me.id));
}
// H4: a person's public key is the one this browser remembered for them (LS e2eSeen:<me>:<uid>, shared with the direct messages);
// the first one seen is remembered, a different one is not used until the person confirms it (le2eAcceptKey)
const le2eFp = pub => pub ? pub.x + '.' + pub.y : '';
function le2eSeenOk(uid, pub) {
  if (!pub) return false;
  const k = `e2eSeen:${S.me.id}:${uid}`, fp = le2eFp(pub), seen = LS.get(k, '');
  if (!seen) { LS.set(k, fp); return true; }
  if (seen === fp) { delete LE2E.changed[uid]; return true; }
  LE2E.changed[uid] = fp;
  return false;
}
// true when the person's key known here (list infos, fetched public keys) differs from the remembered one
function le2eKeyChanged(uid) {
  if (LE2E.changed[uid]) return true;
  const seen = S.me ? LS.get(`e2eSeen:${S.me.id}:${uid}`, '') : '';
  if (!seen) return false;
  const pubs = [E2E.peers[uid], ...Object.values(LE2E.info).map(j => (j?.members || []).find(m => m.user_id === uid)?.pub)].filter(Boolean);
  const other = pubs.map(le2eFp).find(fp => fp !== seen);
  if (other) LE2E.changed[uid] = other;
  return !!other;
}
function le2eAcceptKey(uid) {
  const fp = LE2E.changed[uid]; if (!fp) return;
  LS.set(`e2eSeen:${S.me.id}:${uid}`, fp);
  delete LE2E.changed[uid]; delete E2E.peers[uid];
  LE2E.tried = {};
  le2eRequeue();
}
// the raw bytes of my key of a generation (only for wrapping it for someone else; the caller wipes them)
async function le2eRaw(lid, k) {
  const w = k.wrapped_by, me = S.me.id;
  let pub;
  if (w === me) pub = E2E.own;  // never the server's copy of my key
  else { pub = k.wrapper_pub; if (!le2eSeenOk(w, pub)) throw le2eErr(tr('The key of {0} has changed. Compare the safety number before you continue.', personName(lid, w) || '?'), 'list_e2e_keychanged'); }
  if (!pub) throw le2eErr(tr('The list key could not be opened.'), 'list_e2e_key');
  const wr = typeof k.wrapped === 'string' ? JSON.parse(k.wrapped) : k.wrapped;
  return e2eOpen(await le2eKek(pub, lid, k.gen), wr, le2eWrapAad(lid, k.gen, me, w));
}
async function le2eImport(raw) {
  try { return await crypto.subtle.importKey('raw', raw, {name: 'AES-GCM'}, false, ['encrypt', 'decrypt']); } finally { raw.fill(0); }
}
// GET /api/lists/<id>/e2e, kept until the list's state changes (le2eState) or force
async function le2eInfo(lid, force) {
  if (!force && LE2E.info[lid]) return LE2E.info[lid];
  if (LE2E.infoP[lid]) return LE2E.infoP[lid];
  const p = rawFetch('GET', `/api/lists/${lid}/e2e`).then(j => {
    LE2E.info[lid] = j;
    for (const m of j.members || []) if (m.pub && m.user_id !== S.me?.id) le2eSeenOk(m.user_id, m.pub);
    return j;
  }).finally(() => { delete LE2E.infoP[lid]; });
  LE2E.infoP[lid] = p;
  return p;
}
// every generation of this list I hold a key for, unwrapped (only while the encryption is unlocked)
async function le2eKeys(lid, force) {
  const have = LE2E.keys[lid] || (LE2E.keys[lid] = {}), l = listById(lid);
  if (!e2eUnlocked() || !S.me) return have;
  const want = l?.e2e_gen || 0, tag = String(want);
  if (!force && (have[want] || LE2E.tried[lid] === tag)) return have;
  LE2E.tried[lid] = tag;
  let info;
  try { info = await le2eInfo(lid, true); } catch { return have; }
  for (const k of info.keys || []) {
    if (have[k.gen]) continue;
    try { have[k.gen] = await le2eImport(await le2eRaw(lid, k)); } catch { /* a changed key (le2eKeyChanged) or a broken wrap */ }
  }
  return have;
}
// a member's public key for wrapping: fetched again, checked against the remembered one (H4)
async function le2ePubFor(lid, uid) {
  if (uid === S.me.id) return E2E.own;
  delete E2E.peers[uid];
  const pub = await e2ePeer(uid);
  if (!pub) throw le2eErr(tr('{0} has not set up encryption yet', personName(lid, uid) || '?'), 'list_e2e_nokey');
  if (!le2eSeenOk(uid, pub)) throw le2eErr(tr('The key of {0} has changed. Compare the safety number before you continue.', personName(lid, uid) || '?'), 'list_e2e_keychanged');
  return pub;
}
// the safety number with a person (both public keys; my own from my bundle, not from the server)
async function le2eSafety(uid) {
  await e2eLoad();
  if (!E2E.own) return null;
  let pub = null;
  try { delete E2E.peers[uid]; pub = await e2ePeer(uid); } catch { return null; }
  return pub ? e2eSafety(E2E.own, pub) : null;
}
// waiting members get the key: unwrap mine of the current generation, wrap it for each, POST keys (M9)
async function le2eRelease(lid, userIds) {
  if (!await e2eEnsure()) return false;
  if (E2E.badPub) throw le2eErr(tr('Your public key on the server does not match your keys. Encrypted messages are blocked.'), 'list_e2e_badpub');  // review 2 (L2)
  const info = await le2eInfo(lid, true), gen = info.gen;
  const mine = (info.keys || []).find(k => k.gen === gen);
  if (!mine) throw le2eErr(tr('You do not have the key of this list yet.'), 'list_e2e_key');
  const raw = await le2eRaw(lid, mine), keys = [];
  try {
    for (const uid of userIds) keys.push({user_id: uid, gen, wrapped: await le2eWrap(raw, lid, gen, uid, await le2ePubFor(lid, uid))});
  } finally { raw.fill(0); }
  const j = await rawFetch('POST', `/api/lists/${lid}/e2e/keys`, {keys});
  delete LE2E.info[lid];
  le2eChange(lid);
  return j;
}

// ------------------------------------------------------------------ incoming: ciphers into the client state
// An object with ciphers keeps them in o._enc (props; task field values under _enc.fields) and shows the plain text from the memo;
// a cipher not opened yet leaves "" (snippets: []) and o._le2e = 'locked', and waits in the queue for a decryption in the
// background (bundled; then one render and the event le2e:change).
function le2eTrack(o) {
  if (o._le2eT) return;
  Object.defineProperty(o, '_le2eT', {value: true, configurable: true});
  LE2E.objs.add(typeof WeakRef === 'function' ? new WeakRef(o) : {deref: () => o});
  if (LE2E.objs.size > 20000) for (const r of LE2E.objs) if (!r.deref()) LE2E.objs.delete(r);
}
function le2eLidOf(o, hint) {
  if (typeof o.list_id === 'number') return o.list_id;
  if (o.task_id) { const t = le2eTaskAny(o.task_id); if (t) return t.list_id; }
  return hint || null;
}
const le2eSnip = s => { try { const v = JSON.parse(s); return Array.isArray(v) ? v : []; } catch { return []; } };
function le2eFill(o) {
  const e = o._enc; if (!e) return;
  const lid = o._le2eL;
  let locked = false;
  for (const p in e) {
    if (p === 'fields') continue;
    const c = e[p], cur = o[p], open = cur === '' || cur == null || cur === c || (p === 'snippets' && Array.isArray(cur) && !cur.length);
    if (!open) continue;  // changed here meanwhile (the newer local text stays)
    const s = LE2E.memo.get(c);
    if (s === undefined) { o[p] = p === 'snippets' ? [] : ''; locked = true; le2eWait(c, lid, LE2E_CANDS[p]); }
    else o[p] = p === 'snippets' ? le2eSnip(s) : s;
  }
  if (e.fields && o.fields && typeof o.fields === 'object') {
    for (const k in e.fields) {
      const c = e.fields[k], cur = o.fields[k];
      if (!(cur === '' || cur == null || cur === c)) continue;
      const s = LE2E.memo.get(c);
      if (s === undefined) { o.fields[k] = ''; locked = true; le2eWait(c, lid, ['field']); } else o.fields[k] = s;
    }
  }
  if (locked) o._le2e = 'locked'; else delete o._le2e;
}
function le2eNorm(o, hint) {
  let enc = null;
  for (const p of LE2E_PROPS) if (le2eIs(o[p])) (enc || (enc = {}))[p] = o[p];
  const fs = o.fields;
  if (fs && typeof fs === 'object' && !Array.isArray(fs)) for (const k in fs) if (le2eIs(fs[k])) ((enc || (enc = {})).fields || (enc.fields = {}))[k] = fs[k];
  if (!enc) return false;
  const old = o._enc && typeof o._enc === 'object' ? o._enc : {};
  o._enc = {...old, ...enc, ...(enc.fields || old.fields ? {fields: {...(old.fields || {}), ...(enc.fields || {})}} : {})};
  Object.defineProperty(o, '_le2eL', {value: le2eLidOf(o, hint), writable: true, configurable: true});
  le2eTrack(o);
  le2eFill(o);
  return true;
}
function le2eWalk(x, lid, depth) {
  if (!x || typeof x !== 'object' || depth > 7) return;
  if (Array.isArray(x)) { for (const y of x) if (y && typeof y === 'object') le2eWalk(y, lid, depth + 1); return; }
  const l2 = le2eLidOf(x, lid);
  // an edit conflict of a text (PATCH answer): the ciphers this page knows as their text, so "my own earlier save" is recognised
  if (typeof x.field === 'string') for (const p of ['server', 'mine']) if (le2eIs(x[p]) && LE2E.memo.has(x[p])) x[p] = LE2E.memo.get(x[p]);
  le2eNorm(x, l2);
  for (const k in x) {
    if (k === '_enc' || k === 'fields') continue;
    const v = x[k];
    if (v && typeof v === 'object') le2eWalk(v, l2, depth + 1);
  }
}
// the list an address belongs to (a hint for objects without list_id / task_id)
function le2eUrlLid(url) {
  let m = /^\/api\/tasks\/(\d+)/.exec(url); if (m) return le2eTaskAny(+m[1])?.list_id || null;
  m = /^\/api\/lists\/(\d+)/.exec(url); if (m) return +m[1];
  m = /^\/api\/notes\/(\d+)/.exec(url); if (m) return le2eNoteOf(+m[1])?.list_id || null;
  if (/^\/api\/comments\//.test(url) && S.tl?.id) return le2eTaskAny(S.tl.id)?.list_id || null;
  return null;
}
const le2eAny = j => LE2E.on.size || LE2E.memo.size || (Array.isArray(j?.lists) && j.lists.some(l => l && l.e2e));
// every answer of the server passes here (rawFetch): ciphers are taken into _enc, the plain text shown where known
function le2eIn(j, url) {
  if (!j || typeof j !== 'object' || /\/e2e(\/|$)/.test(url || '') || !le2eAny(j)) return j;
  le2eWalk(j, le2eUrlLid(url || ''), 0);
  return j;
}
function le2eWait(c, lid, cands) {
  if (LE2E.bad.has(c) || LE2E.q.has(c)) return;
  LE2E.q.set(c, {lid, cands});
  le2eKick();
}
function le2eKick() { if (!LE2E.kickT) LE2E.kickT = setTimeout(le2eDrain, 0); }
async function le2eDrain() {
  LE2E.kickT = 0;
  if (LE2E.draining) { LE2E.again = true; return; }
  if (!LE2E.q.size) return;
  LE2E.draining = true;
  const lids = new Set();
  try {
    await e2eLoad();
    if (!e2eUnlocked()) return;  // they wait: le2eUnlock asks for the passphrase and fills in
    const by = new Map();
    for (const [c, x] of LE2E.q) { const k = x.lid || 0; if (!by.has(k)) by.set(k, []); by.get(k).push([c, x]); }
    for (const [lid, arr] of by) {
      const lidsTry = lid ? [lid] : [...LE2E.on];
      for (const [c, x] of arr) {
        let s;
        for (const l of lidsTry) { s = await le2eTry(l, c, x.cands, await le2eKeys(l)); if (s != null) { lids.add(l); break; } }
        LE2E.q.delete(c);
        if (s === null) { LE2E.bad.add(c); LE2E.badL.set(c, x.lid || 0); }
      }
    }
  } catch (e) { console.warn('le2e: decrypt', e?.message); }
  finally { LE2E.draining = false; }
  if (lids.size) le2eRefill(lids);
  if (LE2E.again) { LE2E.again = false; le2eKick(); }
}
// review 2 (M2): how many texts of the list did not open with the keys this browser holds (a wrong / swapped list key: H4)
function le2eUnreadable(lid) { let n = 0; for (const [c, l] of LE2E.badL) if (l === lid && LE2E.bad.has(c)) n++; return n; }
// after decryptions: every tracked object that still shows placeholders takes the plain texts, one redraw
function le2eEach(fn) {
  for (const r of LE2E.objs) { const o = r.deref(); if (!o) { LE2E.objs.delete(r); continue; } fn(o); }
}
function le2eRefill(lids) {
  le2eEach(o => { if (o._le2e) le2eFill(o); });
  le2eRedraw();
  for (const lid of lids || []) le2eChange(lid);
}
function le2eRedraw() {
  if (!S.booted) return;
  if (typeof render === 'function') render();
  if (S.sel && typeof renderDetail === 'function' && !$('#detail')?.contains(document.activeElement)) renderDetail();
  if (S.tl?.comments && typeof drawTimeline === 'function') drawTimeline();
}
// what waited (no key yet, a changed key now confirmed) is queued again
function le2eRequeue() {
  le2eEach(o => { if (o._le2e) { for (const c of Object.values(o._enc || {})) if (typeof c === 'string') LE2E.bad.delete(c); le2eFill(o); } });
}
// the list's texts readable: passphrase if needed, keys, every cipher of the list opened, redraw
async function le2eUnlock(lid) {
  if (!await e2eEnsure()) return false;
  await le2eKeys(lid, true);
  LE2E.bad.clear(); LE2E.badL.clear();
  le2eRequeue();
  await le2eDrain();
  le2eRedraw();
  le2eChange(lid);
  return le2eReady(lid);
}
// after every applied state (core.js applyState): the lists' modes, objects from the offline cache (ciphers), keys in the background
function le2eState() {
  const on = new Set();
  for (const l of S.lists || []) {
    if (!l.e2e) { if (LE2E.sig[l.id]) { delete LE2E.sig[l.id]; delete LE2E.info[l.id]; delete LE2E.keys[l.id]; } continue; }  // review 2 (L1): keys go after the way back
    on.add(l.id);
    const sg = [l.e2e, l.e2e_gen, l.e2e_rotate, l.e2e_pending, l.e2e_mine].join('|');
    if (LE2E.sig[l.id] !== sg) { LE2E.sig[l.id] = sg; delete LE2E.info[l.id]; delete LE2E.tried[l.id]; }
  }
  LE2E.on = on;
  if (!on.size && !LE2E.memo.size) return;
  for (const t of S.tasks?.values?.() || []) le2eNorm(t, null);
  le2eWalk(S.sections, null, 0); le2eWalk(S.notes, null, 0); le2eWalk(S.extra, null, 0);
}
// an offline edit is applied with its wire body (ciphers): the plain texts come back from the memo
{
  const al0 = applyLocal;
  applyLocal = function (e) { const r = al0(e); if (LE2E.on.size) { for (const t of S.tasks.values()) le2eNorm(t, null); if (r && typeof r === 'object' && !Array.isArray(r)) le2eNorm(r, null); } return r; };
}
// lock / logout (e2e.js): no plain text of a locked list stays in this page
function le2eWipe() {
  LE2E.memo.clear(); LE2E.rev.clear(); LE2E.q.clear(); LE2E.bad.clear(); LE2E.badL.clear();
  LE2E.keys = {}; LE2E.info = {}; LE2E.tried = {};
  le2eEach(o => {
    const e = o._enc; if (!e) return;
    for (const p in e) if (p !== 'fields') o[p] = p === 'snippets' ? [] : '';
    if (e.fields && o.fields) for (const k in e.fields) o.fields[k] = '';
    o._le2e = 'locked';
  });
  // the undo steps of locked lists keep plain texts (snapshots): they go too
  const mine = e => (e.lids || []).some(l => LE2E.on.has(l)) || (e.snaps || []).some(x => LE2E.on.has(x?.list_id)) || (e.parts || []).some(mine);
  if (typeof HIST !== 'undefined') for (const k of ['undo', 'redo']) HIST[k] = (HIST[k] || []).filter(e => !mine(e));
  le2eRedraw();
  for (const lid of LE2E.on) le2eChange(lid);
}

// ------------------------------------------------------------------ storage (H1): only ciphers leave the memory
// JSON.stringify replacer of LS.set (icons.js): an object with _enc is stored with its ciphers; an object of a locked list with a
// plain text and no cipher (made here, not sent yet) is stored without it
function le2eRepl() {
  if (!LE2E.on.size && !LE2E.memo.size) return undefined;
  const on = LE2E.on, secs = new Set(S.sections || []);
  // the plain texts of an object of a locked list that have no cipher (typed here, not sent yet) -> ""; "name" only of a section
  // (tags, people and folders keep their names: they are not encrypted)
  const blank = (o, v) => {
    for (const p of LE2E_PROPS) if (typeof o[p] === 'string' && o[p] && !le2eIs(o[p]) && (p !== 'name' || secs.has(v))) o[p] = '';
    if (Array.isArray(o.snippets) && o.snippets.length) o.snippets = [];
    if (o.fields && typeof o.fields === 'object' && !Array.isArray(o.fields)) {
      let f = null;
      for (const k in o.fields) if (typeof o.fields[k] === 'string' && o.fields[k] && !le2eIs(o.fields[k]) && fieldById(+k)?.type === 'text') (f || (f = {...o.fields}))[k] = '';
      if (f) o.fields = f;
    }
    return o;
  };
  return function (k, v) {
    if (!v || typeof v !== 'object' || Array.isArray(v)) return v;
    const e = v._enc;
    if (e) {
      const o = {...v}; delete o._enc; delete o._le2e;
      for (const p in e) if (p === 'fields') o.fields = {...(v.fields || {}), ...e.fields}; else o[p] = e[p];
      return on.has(typeof v.list_id === 'number' ? v.list_id : v._le2eL) ? blank(o, v) : o;
    }
    if (v._le2e) { const o = {...v}; delete o._le2e; return o; }
    if (typeof v.tid === 'number' && typeof v.field === 'string' && on.has(S.tasks?.get(v.tid)?.list_id)) {  // a stored edit conflict (core.js addConflicts)
      const lid = S.tasks.get(v.tid).list_id, c = (f, x) => typeof x !== 'string' || !x || le2eIs(x) ? x : LE2E.rev.get(`${lid}|${f}|${x}`) || '';
      return {...v, title: c('title', v.title), ...(LE2E_TASK.includes(v.field) ? {server: c(v.field, v.server), mine: c(v.field, v.mine)} : {})};
    }
    if (typeof v.list_id === 'number' && on.has(v.list_id)) return blank({...v}, v);
    return v;
  };
}

// ------------------------------------------------------------------ outgoing: plain texts of a locked list leave encrypted
// le2eOut(method, url, body) -> the body as it is (nothing to do: synchronous, so api() keeps applying offline edits at once) or a
// Promise of the wire body. Called by api() before the outbox and by rawFetch() (a body that is already encrypted passes unchanged).
function le2eOut(method, url, body) {
  // review 2 (L5): a typed text that starts like a cipher (the server refuses it in an open list): a clear word, before it is sent
  if (method !== 'GET' && body && typeof body === 'object' && !(body instanceof FormData) && /^\/api\/(tasks|comments|notes|sections|lists\/\d+\/notes)/.test(url) && !/\/e2e(\/|$)/.test(url)
    && ['title', 'content', 'url', 'body', 'name'].some(p => le2eIs(body[p]) && !le2eParse(body[p]))) return Promise.reject(le2eErr(tr('A text cannot begin with "e2e1:" (reserved for encrypted texts).'), 'list_e2e_prefix'));
  if (method === 'GET' || method === 'DELETE' || !body || typeof body !== 'object' || !LE2E.on.size || /\/e2e(\/|$)/.test(url)) return body;
  let m;
  // review 2 (M1): a task of the done / trash view or a search result is found too; one this page does not hold is fetched
  // first (its list may be locked: no plain text leaves before that is known)
  const need = (id, has, go) => { const t = le2eTaskAny(id); return t || !(id > 0) || !has ? go(t) : le2eTaskFetch(id).then(go); };
  if (method === 'POST' && url === '/api/tasks') {
    return need(body.list_id == null ? body.parent_id : null, le2eHasText(body), p => {
      const lid = body.list_id ?? p?.list_id ?? inbox()?.id;
      return le2eOn(lid) && le2eHasText(body) ? le2eTaskBody(body, null, lid) : body;
    });
  }
  if (method === 'PATCH' && (m = /^\/api\/tasks\/(-?\d+)$/.exec(url))) {
    return need(+m[1], le2eHasText(body) || body.list_id != null || !!body._prev, t => {
      const src = t?.list_id, dst = body.list_id ?? src;
      return (le2eOn(src) || le2eOn(dst)) && (le2eHasText(body) || dst !== src || body._prev) ? le2eTaskBody(body, t, dst) : body;
    });
  }
  if (method === 'POST' && url === '/api/tasks/batch') return le2eBatchNeeds(body) ? le2eBatch(body) : body;
  if ((m = /^\/api\/tasks\/(-?\d+)\/comments$/.exec(url)) && method === 'POST') {
    return need(+m[1], true, t => le2eOn(t?.list_id) ? le2eCmt(body, t.list_id) : body);
  }
  if ((m = /^\/api\/comments\/(\d+)$/.exec(url)) && method === 'PATCH') {
    const has = 'body' in (body instanceof FormData ? {body: 1} : body);
    return need(S.tl?.id, has, t => le2eOn(t?.list_id) && has ? le2eCmt(body, t.list_id) : body);
  }
  if (body instanceof FormData) return body;
  if ((m = /^\/api\/lists\/(\d+)\/notes$/.exec(url)) && method === 'POST') return le2eOn(+m[1]) ? le2eNoteBody(body, null, +m[1]) : body;
  if ((m = /^\/api\/notes\/(\d+)$/.exec(url)) && method === 'PATCH') {
    const n = le2eNoteOf(+m[1]), src = n?.list_id, dst = body.list_id ?? src;
    return le2eOn(src) || le2eOn(dst) ? le2eNoteBody(body, n, dst) : body;
  }
  if (url === '/api/sections' && method === 'POST') return le2eOn(body.list_id) && body.name ? le2eEncProps(body, body.list_id, {name: 'section'}) : body;
  if ((m = /^\/api\/sections\/(\d+)$/.exec(url)) && method === 'PATCH') {
    const lid = (S.sections || []).find(s => s.id === +m[1])?.list_id;
    return le2eOn(lid) && body.name ? le2eEncProps(body, lid, {name: 'section'}) : body;
  }
  return body;
}
const le2eHasText = b => LE2E_TASK.some(p => p in b) || !!(b.fields && Object.keys(b.fields).some(k => fieldById(+k)?.type === 'text'));
// review 2 (M1): a task of this page: the loaded ones, the extra views (done, trash, search results) or one fetched for a write
const le2eTaskAny = id => id == null ? null : S.tasks?.get(id) || (Array.isArray(S.extra) && S.extra.find(t => t && t.id === id)) || (Array.isArray(S.searchRes) && S.searchRes.find(t => t && t.id === id)) || LE2E.got.get(id) || null;
// a task this page does not hold: fetched (as stored; a trashed one from the trash list) so its list is known; unknown = no write
async function le2eTaskFetch(id) {
  const t = le2eTaskAny(id); if (t) return t;
  let r = null;
  try { r = await rawFetch('GET', `/api/tasks/${id}`); }
  catch { r = ((await rawFetch('GET', '/api/tasks?scope=trash&limit=2000').catch(() => ({}))).tasks || []).find(x => x && x.id === id) || null; }
  if (!r || typeof r.list_id !== 'number') throw le2eErr(tr('The list of this task is not known on this page. Reload and try again.'), 'list_e2e_unknown');
  if (LE2E.got.size > 200) LE2E.got.clear();
  LE2E.got.set(id, r);
  return r;
}
const le2eNoteOf = id => (S.nt?.notes || []).find(n => n.id === id) || (S.notes || []).find(n => n.id === id) || null;
const le2eSnipStr = v => v == null || v === '' ? '' : typeof v === 'string' ? v : Array.isArray(v) && !v.length ? '' : JSON.stringify(v);
// the plain text of a prop of a local object (a placeholder = not readable now -> throw: never send "" over a real text)
function le2ePlain(o, p) {
  if (o._le2e && o._enc?.[p] !== undefined && !LE2E.memo.has(o._enc[p])) throw le2eErrLocked();
  return o[p];
}
async function le2eEncProps(body, lid, map) {
  const b = {...body};
  for (const p in map) if (p in b && typeof b[p] === 'string') b[p] = await le2eEnc(lid, map[p], b[p]);
  return b;
}
// _prev (offline replay, undo): what the server holds is a cipher; the newest cipher of that plain text, else the field is left out
function le2ePrev(prev, lid, t) {
  const o = {...prev};
  for (const p of LE2E_TASK) {
    if (!(p in o)) continue;
    const v = p === 'snippets' ? le2eSnipStr(o[p]) : o[p];
    if (v === '' || v == null || le2eIs(v)) { o[p] = v ?? null; continue; }
    const c = t?._enc?.[p] && LE2E.memo.get(t._enc[p]) === v ? t._enc[p] : LE2E.rev.get(`${lid}|${p}|${v}`);
    if (c) o[p] = c; else delete o[p];
  }
  return o;
}
async function le2eTaskBody(body, t, dst) {
  const b = {...body}; delete b._enc; delete b._le2e;
  const src = t?.list_id ?? dst, moving = !!t && body.list_id != null && body.list_id !== t.list_id;
  if (moving && (le2eOn(src) || le2eOn(dst))) {
    // M8: moving in / out / between locked lists carries the texts of the task, its subtasks, their comments and text fields
    // in the target format (protocol: le2e_move); the task's own texts go along as normal fields too
    b.le2e_move = await le2eMove([t.id], dst);
    const me = b.le2e_move.tasks.find(x => x.id === t.id) || {};
    for (const p of LE2E_TASK) if (!(p in body) && me[p] != null) b[p] = me[p];
  }
  if (le2eOn(dst)) {
    for (const p of LE2E_TASK) {
      if (!(p in b) || b[p] == null) continue;
      b[p] = await le2eEnc(dst, p, p === 'snippets' ? le2eSnipStr(b[p]) : b[p]);
    }
    if (b.fields && typeof b.fields === 'object') {
      const f = {...b.fields};
      for (const k in f) if (fieldById(+k)?.type === 'text' && typeof f[k] === 'string' && f[k]) f[k] = await le2eEnc(dst, 'field', f[k]);
      b.fields = f;
    }
  } else if (b.snippets !== undefined && le2eIs(b.snippets)) b.snippets = le2eSnip(await le2eDec(src, 'snippets', b.snippets));
  if (b._prev && typeof b._prev === 'object' && le2eOn(src)) b._prev = le2ePrev(b._prev, src, t);
  return b;
}
// the texts of tasks (and their subtasks, comments, text fields) in the format of list dst: ciphers of its current generation, or
// plain text when dst is open
async function le2eMove(ids, dst) {
  const out = {tasks: [], comments: [], fields: []}, seen = new Set(), dOn = le2eOn(dst);
  const all = [];
  const walk = id => { if (seen.has(id)) return; seen.add(id); const x = le2eTaskAny(id); if (x) all.push(x); for (const c of children(id)) walk(c.id); };
  ids.forEach(walk);
  const conv = (field, plain) => !plain ? plain : dOn ? le2eEnc(dst, field, plain) : field === 'snippets' ? le2eSnip(plain) : plain;
  // the plain text of a prop: the local one, or the cipher opened now (a placeholder is never sent as the text)
  const txt = async (x, p) => { const c = x._enc?.[p]; return c && (x[p] === '' || x[p] == null || (p === 'snippets' && Array.isArray(x[p]) && !x[p].length)) ? le2eDec(x.list_id, p, c) : x[p]; };
  for (const x of all) {
    const src = x.list_id, row = {id: x.id};
    for (const p of LE2E_TASK) {
      let v;
      if (p !== 'snippets') v = await txt(x, p);
      else if (x._enc?.snippets) v = await txt(x, p);
      else if (Array.isArray(x.snippets)) v = x.snippets.length ? JSON.stringify(x.snippets) : '';
      else if (snipCount(x) && x.id > 0) {  // an open list's task carries only the number of its snippets
        const sv = (await rawFetch0('GET', `/api/tasks/${x.id}`)).snippets;
        v = Array.isArray(sv) ? (sv.length ? JSON.stringify(sv) : '') : le2eIs(sv) ? await le2eDec(src, 'snippets', sv) : '';
      }
      if (le2eIs(v)) v = await le2eDec(src, p, v);
      if (typeof v !== 'string' && p === 'snippets') v = le2eSnipStr(v);
      if (v) row[p] = await conv(p, v);
    }
    out.tasks.push(row);
    for (const fid in x.fields || {}) {
      if (fieldById(+fid)?.type !== 'text') continue;
      let v = x.fields[fid];
      if (x._enc?.fields?.[fid] && !LE2E.memo.has(x._enc.fields[fid])) v = await le2eDec(src, 'field', x._enc.fields[fid]);
      if (v) out.fields.push({task_id: x.id, field_id: +fid, value: await conv('field', v)});
    }
    if (x.comment_count > 0 && x.id > 0) {
      const tl = await rawFetch0('GET', `/api/tasks/${x.id}/timeline`);  // raw: the ciphers as stored
      for (const c of tl.comments || []) {
        if (c.deleted || !c.body) continue;
        const v = le2eIs(c.body) ? await le2eDec(src, 'comment', c.body) : c.body;
        out.comments.push({id: c.id, body: await conv('comment', v)});
      }
    }
  }
  return out;
}
// 409 list_e2e_move with need (a subtask in the trash, a comment this page did not load): the missing texts fetched as stored,
// converted, and the call sent once more (core.js rawFetch). -> the new body, or null (nothing to add)
async function le2eFix(url, body, need) {
  if (!need || !body || typeof body !== 'object' || body instanceof FormData) return null;
  const pm = /^\/api\/tasks\/(-?\d+)$/.exec(url), d = pm ? body : body.data;
  const mv = d?.le2e_move, dst = d?.list_id;
  if (!mv || dst == null) return null;
  const dOn = le2eOn(dst), raw = {}, got = new Set(), out = {tasks: [...mv.tasks], comments: [...mv.comments], fields: [...mv.fields]};
  const conv = (field, plain) => !plain ? plain : dOn ? le2eEnc(dst, field, plain) : field === 'snippets' ? le2eSnip(plain) : plain;
  const open = async (lid, field, v) => le2eIs(v) ? le2eDec(lid, field, v) : v;
  let trash = null;  // GET /api/tasks/<id> has no task of the trash: the trash list (as stored) instead
  const task = async id => raw[id] || (raw[id] = await rawFetch0('GET', `/api/tasks/${id}`).catch(async e => {
    trash = trash || (await rawFetch0('GET', '/api/tasks?scope=trash&limit=2000')).tasks || [];
    const r = trash.find(x => x.id === id); if (!r) throw e; return r;
  }));
  for (const id of need.tasks || []) {
    const r = await task(id), row = {id};
    for (const p of LE2E_TASK) {
      let v = r[p];
      if (p === 'snippets') v = Array.isArray(v) ? (v.length ? JSON.stringify(v) : '') : v || '';
      v = await open(r.list_id, p, v);
      if (v) row[p] = await conv(p, v);
    }
    out.tasks = [...out.tasks.filter(x => x.id !== id), row];
  }
  for (const [tid, fid] of need.fields || []) {
    const r = await task(tid), v = await open(r.list_id, 'field', (r.fields || {})[fid]);
    out.fields = [...out.fields.filter(x => !(x.task_id === tid && x.field_id === fid)), {task_id: tid, field_id: fid, value: await conv('field', v)}];
  }
  const want = new Set(need.comments || []);
  for (const id of want.size ? new Set([...out.tasks.map(x => x.id), ...(need.tasks || [])]) : []) {
    if (!(id > 0)) continue;
    const lid = (await task(id).catch(() => ({}))).list_id ?? S.tasks.get(id)?.list_id;
    const tl = await rawFetch0('GET', `/api/tasks/${id}/timeline`).catch(() => ({}));
    for (const c of tl.comments || []) {
      if (!want.has(c.id) || !c.body) continue;
      out.comments = [...out.comments.filter(x => x.id !== c.id), {id: c.id, body: await conv('comment', await open(lid, 'comment', c.body))}];
      got.add(c.id);
    }
  }
  if ((need.comments || []).some(id => !got.has(id)) && want.size) return null;  // not readable here: the server's message stays
  return pm ? {...body, le2e_move: out} : {...body, data: {...d, le2e_move: out}};
}
function le2eBatchNeeds(body) {
  const ids = body.ids || [], d = body.data || {};
  if (ids.some(i => i > 0 && !le2eTaskAny(i)) || Object.keys(d.items || {}).some(i => +i > 0 && !le2eTaskAny(+i))) return true;  // M1: fetched first
  const lids = new Set(ids.map(i => le2eTaskAny(i)?.list_id));
  if (body.action === 'patch') return [...lids].some(le2eOn) || (d.list_id != null && le2eOn(d.list_id));
  if (body.action === 'patch_each') return Object.entries(d.items || {}).some(([id, it]) => le2eOn(le2eTaskAny(+id)?.list_id) || (it && le2eOn(it.list_id)));
  return false;
}
async function le2eBatch(body) {
  const d = {...(body.data || {})}, ids = body.ids || [];
  for (const i of [...ids, ...Object.keys(d.items || {}).map(Number)]) if (i > 0 && !le2eTaskAny(i)) await le2eTaskFetch(i);
  if (!ids.some(i => le2eOn(le2eTaskAny(i)?.list_id)) && !(d.list_id != null && le2eOn(d.list_id)) && !Object.entries(d.items || {}).some(([id, it]) => le2eOn(le2eTaskAny(+id)?.list_id) || (it && le2eOn(it.list_id)))) return body;
  if (body.action === 'patch') {
    if (d.list_id != null && ids.some(i => { const s = le2eTaskAny(i)?.list_id; return s !== d.list_id && (le2eOn(s) || le2eOn(d.list_id)); })) d.le2e_move = await le2eMove(ids, d.list_id);
    if (LE2E_TASK.some(p => p in d)) {
      const ls = new Set(ids.map(i => d.list_id ?? le2eTaskAny(i)?.list_id));
      // review 2 (L6): one text for tasks of several lists, one of them locked: each list needs its own cipher
      if (ls.size > 1) throw le2eErr(tr('Texts of tasks from several lists cannot be changed together while one of them is encrypted in the browser.'), 'list_e2e_multi');
      const lid = [...ls][0];
      if (le2eOn(lid)) for (const p of LE2E_TASK) if (p in d && d[p] != null) d[p] = await le2eEnc(lid, p, p === 'snippets' ? le2eSnipStr(d[p]) : d[p]);
    }
  } else if (body.action === 'patch_each') {
    const items = {};
    for (const [id, it] of Object.entries(d.items || {})) {
      const t = le2eTaskAny(+id);
      items[id] = it && t ? await le2eTaskBody(it, t, it.list_id ?? t.list_id) : it;
    }
    d.items = items;
  }
  return {...body, data: d};
}
// a comment of a locked list: the body encrypted, the mentions named beside it (the server cannot read <@id> in a cipher)
async function le2eCmt(body, lid) {
  const ids = s => [...new Set([...String(s || '').matchAll(/<@(\d+)>/g)].map(x => +x[1]))];
  if (body instanceof FormData) {
    const s = body.get('body');
    if (typeof s === 'string' && s && !le2eIs(s)) { body.set('body', await le2eEnc(lid, 'comment', s)); body.set('mentions', ids(s).join(',')); }
    return body;
  }
  const s = body.body;
  if (typeof s !== 'string' || !s || le2eIs(s)) return body;
  return {...body, body: await le2eEnc(lid, 'comment', s), mentions: ids(s)};
}
async function le2eNoteBody(body, n, dst) {
  const b = {...body}; delete b._enc; delete b._le2e;
  const src = n?.list_id ?? dst;
  if (n && body.list_id != null && body.list_id !== src) {
    // a note into / out of a locked list: title and body in the target format (the open note has both)
    for (const p of ['title', 'body']) if (!(p in b)) { let v = le2ePlain(n, p); if (le2eIs(v)) v = await le2eDec(src, p === 'title' ? 'note_title' : 'note_body', v); b[p] = v ?? ''; }
  }
  if (le2eOn(dst)) return le2eEncProps(b, dst, {title: 'note_title', body: 'note_body'});
  for (const [p, f] of [['title', 'note_title'], ['body', 'note_body']]) if (le2eIs(b[p])) b[p] = await le2eDec(src, f, b[p]);
  return b;
}

// ------------------------------------------------------------------ switching on / off (M6): resumable, bundled
// todo -> encrypt / decrypt -> bulk (at most 200 values a call) until nothing is left -> finish. Breaking off (tab closed, offline)
// loses nothing: le2eResume continues from the server's todo.
const LE2E_ROWS = {tasks: [['title', 'title'], ['content', 'content'], ['url', 'url'], ['snippets', 'snippets']], comments: [['body', 'comment']], notes: [['title', 'note_title'], ['body', 'note_body']], sections: [['name', 'section']], fields: [['value', 'field']]};
const le2eLeft = left => Object.values(left || {}).reduce((a, n) => a + (+n || 0), 0);
async function le2eMigrate(lid, onProgress) {
  if (LE2E.busy[lid]) return LE2E.busy[lid];
  const run = (async () => {
    let total = null, last = -1, blank = false, spins = 0;
    const bad = new Set();  // review 2 (M4): values that do not open with any key held here (decrypting)
    for (;;) {
      const todo = await rawFetch('GET', `/api/lists/${lid}/e2e/todo?limit=200`);
      const left = le2eLeft(todo.left);
      if (total === null) total = left;
      total = Math.max(total, left);
      onProgress?.({done: total - left, total});
      if (!left) break;
      if (left === last && (++spins > 2 || !(bad.size && !blank))) throw le2eErr(tr('Encryption of this list stopped without progress. Try again later.'), 'list_e2e_stuck');
      const mode = todo.mode || listById(lid)?.e2e, enc = mode === 'encrypting', out = {};
      if (enc) await le2eKeys(lid, !le2eReady(lid));
      for (const kind in LE2E_ROWS) {
        const rows = [];
        for (const r of todo[kind] || []) {
          const o = kind === 'fields' ? {task_id: r.task_id, field_id: r.field_id} : {id: r.id};
          let n = 0;
          for (const [p, f] of LE2E_ROWS[kind]) {
            let v = r[p]; if (v == null) continue;
            // M4 / L5: an old text that only looks like a cipher (not of this generation) is encrypted as a text: no endless switch
            if (enc) v = le2eParse(v)?.g === (todo.gen ?? listById(lid)?.e2e_gen) ? v : await le2eEnc(lid, f, p === 'snippets' ? le2eSnipStr(v) : String(v), true);
            else if (le2eIs(v)) {
              const k = `${kind}:${o.id ?? o.task_id + '.' + o.field_id}:${p}`;
              try { v = await le2eDec(lid, f, v); if (p === 'snippets') v = le2eSnip(v); }
              catch { if (!blank) { bad.add(k); continue; } v = p === 'snippets' ? [] : ''; }  // M4: kept back, or taken over as empty
            }
            o[p] = v; n++;
          }
          if (n) rows.push(o);
        }
        if (rows.length) out[kind] = rows;
      }
      if (!Object.keys(out).length && bad.size && !blank) {
        // M4: only texts no key here opens are left (a broken or foreign cipher): the owner decides, else the way back stops here
        const yes = typeof askConfirm === 'function' && await askConfirm(tr('Texts that cannot be decrypted'),
          tr('{0} texts of this list cannot be decrypted with the keys you hold. Take them over as empty texts? They cannot be restored.', bad.size), {ok: tr('Take over as empty'), danger: true});
        if (!yes) throw le2eErr(tr('{0} texts of this list cannot be decrypted. The list stays locked until they are taken over as empty.', bad.size), 'list_e2e_unreadable');
        blank = true; last = -1;
        continue;
      }
      last = left;
      await rawFetch('POST', `/api/lists/${lid}/e2e/bulk`, out);
    }
    await rawFetch('POST', `/api/lists/${lid}/e2e/finish`);
    delete LE2E.info[lid];
    await load(); render();
    le2eChange(lid);
    return true;
  })();
  LE2E.busy[lid] = run;
  try { return await run; } finally { delete LE2E.busy[lid]; }
}
async function le2eStart(lid, onProgress) {
  if (!await e2eEnsure()) return false;
  if (E2E.badPub) throw le2eErr(tr('Your public key on the server does not match your keys. Encrypted messages are blocked.'), 'list_e2e_badpub');
  const info = await le2eInfo(lid, true);
  if (info.mode) return le2eResume(lid, onProgress);
  if (info.blockers?.length) throw le2eErr(info.blockers.map(b => b.text).join(' '), 'list_e2e_blocked');
  const gen = (info.gen || 0) + 1, raw = e2eRand(32), keys = [];
  try {
    const people = (info.members || []).filter(m => m.has_keys && m.kind !== 'agent');
    if (!people.some(m => m.user_id === S.me.id)) people.unshift({user_id: S.me.id});
    for (const m of people) keys.push({user_id: m.user_id, wrapped: await le2eWrap(raw, lid, gen, m.user_id, await le2ePubFor(lid, m.user_id))});
    const j = await rawFetch('POST', `/api/lists/${lid}/e2e/start`, {keys});
    LE2E.info[lid] = j;
    (LE2E.keys[lid] || (LE2E.keys[lid] = {}))[j.gen ?? gen] = await crypto.subtle.importKey('raw', raw, {name: 'AES-GCM'}, false, ['encrypt', 'decrypt']);
    const l = listById(lid); if (l) Object.assign(l, {e2e: j.mode || 'encrypting', e2e_gen: j.gen ?? gen, e2e_mine: true});
    LE2E.on.add(lid);
  } finally { raw.fill(0); }
  return le2eMigrate(lid, onProgress);
}
async function le2eStop(lid, password, onProgress) {
  if (!await e2eEnsure()) return false;
  await le2eKeys(lid, true);  // every generation: the texts open before the switch
  await rawFetch('POST', `/api/lists/${lid}/e2e/stop`, {password});
  delete LE2E.info[lid];
  const l = listById(lid); if (l) l.e2e = 'decrypting';
  return le2eMigrate(lid, onProgress);
}
async function le2eResume(lid, onProgress) {
  const info = await le2eInfo(lid, true);
  if (info.mode !== 'encrypting' && info.mode !== 'decrypting') return false;
  if (!await e2eEnsure()) return false;
  await le2eKeys(lid, true);
  return le2eMigrate(lid, onProgress);
}

// ------------------------------------------------------------------ texts the server gives neutral (history, time, news)
// the title of a task of a locked list as far as this page can read it, else the fallback (the server's "🔒 Task")
function le2eTitle(tid, fallback) { const t = le2eTaskAny(tid); return t && le2eOn(t.list_id) && !le2eLocked(t) && t.title ? t.title : fallback; }

// ------------------------------------------------------------------ local search (M7): the server finds nothing in locked lists
const le2eWords = q => String(q || '').toLowerCase().split(/\s+/).filter(Boolean);
const le2eHit = (ws, ...texts) => { const s = texts.map(x => String(x || '')).join('\n').toLowerCase(); return ws.length && ws.every(w => s.includes(w)); };
// the task search (render.js doSearch): the server's hits + the readable tasks of locked lists whose texts hold every word
function le2eSearch(q, tasks) {
  if (!LE2E.on.size) return tasks;
  const ws = le2eWords(q), have = new Set((tasks || []).map(t => t.id)), out = [...(tasks || [])];
  for (const t of S.tasks.values()) {
    if (have.has(t.id) || !LE2E.on.has(t.list_id) || le2eLocked(t) || t.deleted_at) continue;
    if (le2eHit(ws, t.title, t.content, t.url)) out.push(t);
  }
  return out;
}
// the message search (chat.js MSG_SOURCES): comments of locked lists opened on this page
function le2eMsgSearch(q, f = {}) {
  const ws = le2eWords(q), hits = [];
  if (!ws.length || (f.art && f.art !== 'c')) return {hits, total: 0, next: null};
  le2eEach(o => {
    if (!o.task_id || !o._enc?.body || o._le2e || !o.body || (f.task && +f.task !== o.task_id) || (f.sender && +f.sender !== o.user_id)) return;
    if (!le2eHit(ws, o.body)) return;
    const cs = Array.from(o.body), low = o.body.toLowerCase(), at = Array.from(low.slice(0, low.indexOf(ws[0]))).length;
    const from = Math.max(0, at - 40), snip = cs.slice(from, from + 160);
    const marks = [], sl = snip.join('').toLowerCase();
    for (const w of ws) { const i = sl.indexOf(w); if (i >= 0) { const s = Array.from(sl.slice(0, i)).length; marks.push([s, s + Array.from(w).length]); } }
    marks.sort((a, b) => a[0] - b[0]);
    const t = S.tasks.get(o.task_id);
    hits.push({art: 'c', id: o.id, chat_type: 'task', task_id: o.task_id, chat_name: t?.title || '', sender: {id: o.user_id, name: o.user_name || o.name || personNameAny(o.user_id) || ''},
      created_at: o.created_at || '', snippet: snip.join(''), marks, enc: true});
  });
  return {hits, total: hits.length, next: null};
}
if (typeof MSG_SOURCES !== 'undefined') MSG_SOURCES.push({id: 'device-list', search: async (q, f) => le2eMsgSearch(q, f)});
