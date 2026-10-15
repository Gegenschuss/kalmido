/* Kalmido web client: end-to-end encryption (2.42.0, #828 task notes + files, #909 direct messages).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md).
   Only WebCrypto (crypto.subtle), no library. The server (kalmido/collab/e2e.py) stores the public key and the key bundle
   wrapped twice (passphrase: PBKDF2-SHA256 600 000 rounds; recovery code: 160 random bits, HKDF-SHA256), never a secret. */
'use strict';

// ------------------------------------------------------------------ state + primitives
// st: null = not loaded, {set: false} | {set: true, pub, bundle_pass, bundle_rec}; priv / ckey: the unlocked keys (CryptoKey,
// not extractable) while unlocked; dm: room id -> AES key; dec: "<msg id>:<edited_at>" -> plain text (this session only)
// own: my public key {x, y} taken from my unlocked bundle (not from the server); badPub: the server's copy differs
const E2E = {st: null, loading: null, priv: null, ckey: null, own: null, badPub: false, dm: {}, peers: {}, dec: {}, notes: {}, warn: {}, down: {}, saveT: null};
const E2E_V = 1, E2E_ITER = 600000, E2E_MIN = 10;
const E2E_B32 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
// created on first use: older test browsers (jsdom) have no TextEncoder at load time
let e2eTE0 = null, e2eTD0 = null;
const e2eTEnc = () => e2eTE0 || (e2eTE0 = new TextEncoder()), e2eTDec = () => e2eTD0 || (e2eTD0 = new TextDecoder());
const e2eRand = n => crypto.getRandomValues(new Uint8Array(n));
function e2eB64(buf) {
  const u = buf instanceof Uint8Array ? buf : new Uint8Array(buf); let s = '';
  for (let i = 0; i < u.length; i += 0x8000) s += String.fromCharCode.apply(null, u.subarray(i, i + 0x8000));
  return btoa(s);
}
const e2eUnb64 = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
const e2eUnlocked = () => !!(E2E.ckey && E2E.priv);
const e2eReady = () => !!E2E.st?.set;
// the recovery code: 20 random bytes as Base32 (32 characters), shown in 8 groups of 4
function e2eCodeMake() {
  const b = e2eRand(20); let bits = '', out = '';
  for (const x of b) bits += x.toString(2).padStart(8, '0');
  for (let i = 0; i < bits.length; i += 5) out += E2E_B32[parseInt(bits.slice(i, i + 5), 2)];
  return {bytes: b, text: out.match(/.{4}/g).join('-')};
}
function e2eCodeParse(t) {
  const s = String(t || '').toUpperCase().replace(/[^A-Z2-7]/g, '');
  if (s.length !== 32) return null;
  let bits = ''; for (const ch of s) bits += E2E_B32.indexOf(ch).toString(2).padStart(5, '0');
  return Uint8Array.from(bits.match(/.{8}/g), x => parseInt(x, 2));
}
async function e2eSeal(key, bytes, aad) {
  const iv = e2eRand(12);
  const ct = await crypto.subtle.encrypt({name: 'AES-GCM', iv, additionalData: e2eTEnc().encode(aad)}, key, bytes);
  return {v: E2E_V, iv: e2eB64(iv), ct: e2eB64(ct)};
}
async function e2eOpen(key, b, aad) {
  if (!b || b.v !== E2E_V) throw new Error('version');
  return new Uint8Array(await crypto.subtle.decrypt({name: 'AES-GCM', iv: e2eUnb64(b.iv), additionalData: e2eTEnc().encode(aad)}, key, e2eUnb64(b.ct)));
}
// the two key-encryption keys of the bundle
async function e2eKekPass(pass, salt, iter) {
  const base = await crypto.subtle.importKey('raw', e2eTEnc().encode(pass.normalize('NFC')), 'PBKDF2', false, ['deriveKey']);
  return crypto.subtle.deriveKey({name: 'PBKDF2', hash: 'SHA-256', salt, iterations: iter}, base, {name: 'AES-GCM', length: 256}, false, ['encrypt', 'decrypt']);
}
async function e2eKekCode(bytes, salt) {
  const base = await crypto.subtle.importKey('raw', bytes, 'HKDF', false, ['deriveKey']);
  return crypto.subtle.deriveKey({name: 'HKDF', hash: 'SHA-256', salt, info: e2eTEnc().encode('kalmido-e2e-rec:v1')}, base, {name: 'AES-GCM', length: 256}, false, ['encrypt', 'decrypt']);
}
const e2eAad = (uid, kind) => `kalmido-e2e:v1:${uid}:${kind}`;
async function e2eWrapPass(bundle, pass) {
  const salt = e2eRand(16), b = await e2eSeal(await e2eKekPass(pass, salt, E2E_ITER), e2eTEnc().encode(JSON.stringify(bundle)), e2eAad(S.me.id, 'pass'));
  return {v: E2E_V, kdf: 'pbkdf2-sha256', iter: E2E_ITER, salt: e2eB64(salt), iv: b.iv, ct: b.ct};
}
async function e2eWrapCode(bundle, code) {
  const salt = e2eRand(16), b = await e2eSeal(await e2eKekCode(code, salt), e2eTEnc().encode(JSON.stringify(bundle)), e2eAad(S.me.id, 'rec'));
  return {v: E2E_V, kdf: 'hkdf-sha256', salt: e2eB64(salt), iv: b.iv, ct: b.ct};
}
async function e2eUnwrapPass(w, pass) {
  const kek = await e2eKekPass(pass, e2eUnb64(w.salt), w.iter);
  return JSON.parse(e2eTDec().decode(await e2eOpen(kek, w, e2eAad(S.me.id, 'pass'))));
}
async function e2eUnwrapCode(w, code) {
  return JSON.parse(e2eTDec().decode(await e2eOpen(await e2eKekCode(code, e2eUnb64(w.salt)), w, e2eAad(S.me.id, 'rec'))));
}
// the unwrapped bundle becomes two keys that cannot be exported again (only used inside this page)
// 2.42.0 (#909): my public key from the bundle; the server's copy must match (else a server could swap it unnoticed)
const e2eBundlePub = bundle => ({kty: 'EC', crv: 'P-256', x: bundle.priv.x, y: bundle.priv.y});
function e2eOwnSet(own) {
  E2E.own = own ? {x: own.x, y: own.y} : null;
  const sp = E2E.st?.pub;
  E2E.badPub = !!(E2E.own && sp && (sp.x !== E2E.own.x || sp.y !== E2E.own.y));
}
async function e2eAdopt(bundle) {
  E2E.priv = await crypto.subtle.importKey('jwk', bundle.priv, {name: 'ECDH', namedCurve: 'P-256'}, false, ['deriveBits']);
  E2E.ckey = await crypto.subtle.importKey('raw', e2eUnb64(bundle.ck), {name: 'AES-GCM'}, false, ['encrypt', 'decrypt']);
  E2E.dm = {};
  e2eOwnSet(bundle.priv);
}

// ------------------------------------------------------------------ "remember on this device" (IndexedDB, keys stay non-extractable)
function e2eIdb() {
  return new Promise((res, rej) => {
    if (typeof indexedDB === 'undefined') { rej(new Error('no idb')); return; }
    const r = indexedDB.open('kalmido-e2e', 1);
    r.onupgradeneeded = () => r.result.createObjectStore('keys');
    r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error);
  });
}
async function e2eIdbDo(mode, fn) {
  const db = await e2eIdb();
  try {
    return await new Promise((res, rej) => { const tx = db.transaction('keys', mode), q = fn(tx.objectStore('keys')); tx.oncomplete = () => res(q?.result); tx.onerror = () => rej(tx.error); });
  } finally { db.close(); }
}
const e2eIdbPut = () => e2eIdbDo('readwrite', s => s.put({priv: E2E.priv, ckey: E2E.ckey, pub: E2E.own.x, own: E2E.own}, 'u' + S.me.id));
const e2eIdbGet = () => e2eIdbDo('readonly', s => s.get('u' + S.me.id));
const e2eIdbDel = () => e2eIdbDo('readwrite', s => s.delete('u' + S.me.id)).catch(() => {});
// logout (account.js): every remembered key of this browser goes
async function e2eForget() {
  E2E.priv = E2E.ckey = E2E.own = null; E2E.badPub = false; E2E.dm = {}; E2E.dec = {}; E2E.notes = {};
  try { await new Promise(res => { const r = indexedDB.deleteDatabase('kalmido-e2e'); r.onsuccess = r.onerror = r.onblocked = () => res(); }); } catch { /* none */ }
}

// ------------------------------------------------------------------ loading, unlocking, locking
async function e2eLoad(force) {
  if (!S.me || S.me.kind === 'agent') return E2E.st;
  if (E2E.st && !force) return E2E.st;
  if (!E2E.loading) E2E.loading = (async () => {
    try { E2E.st = await rawFetch('GET', '/api/e2e/keys'); } catch { E2E.loading = null; return E2E.st; }
    if (!E2E.st.set) { E2E.priv = E2E.ckey = E2E.own = null; E2E.badPub = false; }
    else if (!e2eUnlocked()) {
      // the remembered keys carry their own public key (from the bundle); another key on the server (set up anew elsewhere, or
      // swapped) -> not used: the passphrase unwraps the server's bundle, and e2eAdopt compares its key with the server's copy
      try {
        const k = await e2eIdbGet(), sp = E2E.st.pub;
        if (k && k.own && k.priv && k.ckey && k.own.x === sp.x && k.own.y === sp.y) { E2E.priv = k.priv; E2E.ckey = k.ckey; e2eOwnSet(k.own); }
      } catch { /* no IndexedDB */ }
    } else e2eOwnSet(E2E.own);
    E2E.loading = null;
    return E2E.st;
  })();
  return E2E.loading;
}
function e2eLock() {
  E2E.priv = E2E.ckey = E2E.own = null; E2E.badPub = false; E2E.dm = {}; E2E.dec = {}; E2E.notes = {};
  e2eIdbDel();
  e2eRefresh(); toast(tr('Encryption locked'));
}
// re-draw what shows encrypted content (detail, team chat, settings)
function e2eRefresh() {
  if (S.sel && typeof renderDetail === 'function') renderDetail();
  if (S.route?.mod === 'team' && S.tc?.rid) { for (const m of S.tc.msgs || []) if (m.enc && !m.enc.sys) { m._dec = false; m.body = ''; } renderView(); e2eRoomDecrypt(S.tc.rid); }
  const md = $('#s-e2e')?.closest('.modal'); if (md) e2eDraw(md);
}
// unlocked? else ask (passphrase; or set it up first). -> true when the keys are ready
async function e2eEnsure() {
  await e2eLoad();
  if (e2eUnlocked()) return true;
  if (!e2eReady()) {
    if (await askConfirm(tr('End-to-end encryption is not set up'), tr('Set it up once in Settings > Account: a passphrase and a recovery code protect your keys.'), {ok: tr('Set up')})) settingsModal('account');
    return false;
  }
  return e2eUnlockDlg();
}
function e2eUnlockDlg() {
  return new Promise(done => {
    const md = modal(`<h3>${ic('lock', 's')} ${tr('Unlock encryption')}</h3><form class="e2eform" novalidate>
      <input type="password" id="e2e-pw" placeholder="${esc(tr('Passphrase'))}" aria-label="${esc(tr('Passphrase'))}" autocomplete="off" data-1p-ignore data-lpignore="true" data-bwignore required>
      <label class="chkl"><input type="checkbox" id="e2e-rem"> ${tr('Remember on this device')}</label>
      <div class="aerr" role="alert" id="e2e-err"></div>
      <button type="button" class="linkbtn" data-m="code">${tr('Forgot the passphrase? Use the recovery code')}</button>
      <div class="foot"><span class="spacer"></span><button type="button" class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" type="submit">${tr('Unlock')}</button></div></form>`);
    md.classList.add('e2edlg');
    const close = v => { md.remove(); done(v); };
    md.addEventListener('click', e => {
      if (e.target.closest('[data-m="close"]')) close(false);
      if (e.target.closest('[data-m="code"]')) { md.remove(); e2eResetDlg().then(done); }
    });
    md.querySelector('form').addEventListener('submit', async e => {
      e.preventDefault();
      const b = md.querySelector('button[type=submit]'); b.disabled = true; $('#e2e-err', md).textContent = tr('Unlocking…');
      try { await e2eAdopt(await e2eUnwrapPass(E2E.st.bundle_pass, $('#e2e-pw', md).value)); }
      catch { $('#e2e-err', md).textContent = tr('Wrong passphrase'); b.disabled = false; $('#e2e-pw', md).select(); return; }
      if ($('#e2e-rem', md).checked) { try { await e2eIdbPut(); } catch { /* private mode: only this session */ } }
      close(true); e2eRefresh();
    });
    setTimeout(() => $('#e2e-pw', md)?.focus(), 50);
  });
}
const e2eWarnHtml = () => `<p class="shint keep">${tr('Passphrase and recovery code lost = your encrypted notes, files and messages are lost. Nobody can restore them, not even the administrator.')}</p>`;
// a new passphrase twice (at least E2E_MIN characters) -> the passphrase or null
function e2ePassFields(md) {
  const a = $('#e2e-p1', md).value, b = $('#e2e-p2', md).value;
  if (a.length < E2E_MIN) return [null, tr('At least {0} characters', E2E_MIN)];
  if (a !== b) return [null, tr('The two passphrases differ')];
  return [a, ''];
}
const e2ePassHtml = () => `<input type="password" id="e2e-p1" placeholder="${esc(tr('New passphrase'))}" aria-label="${esc(tr('New passphrase'))}" autocomplete="new-password" minlength="${E2E_MIN}" required>
  <input type="password" id="e2e-p2" placeholder="${esc(tr('Repeat the passphrase'))}" aria-label="${esc(tr('Repeat the passphrase'))}" autocomplete="new-password" required>`;
function e2eSetupDlg() {
  return new Promise(done => {
    const md = modal(`<h3>${ic('lock', 's')} ${tr('Set up end-to-end encryption')}</h3><form class="e2eform" novalidate>
      <p class="muted">${tr('Choose a passphrase you do not use anywhere else. It unlocks your keys in this browser; the server never sees it.')}</p>
      ${e2ePassHtml()}${e2eWarnHtml()}<div class="aerr" role="alert" id="e2e-err"></div>
      <div class="foot"><span class="spacer"></span><button type="button" class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" type="submit">${tr('Continue')}</button></div></form>`);
    md.classList.add('e2edlg');
    md.addEventListener('click', e => { if (e.target.closest('[data-m="close"]')) { md.remove(); done(false); } });
    md.querySelector('form').addEventListener('submit', async e => {
      e.preventDefault();
      const [pass, msg] = e2ePassFields(md); if (!pass) { $('#e2e-err', md).textContent = msg; return; }
      const b = md.querySelector('button[type=submit]'); b.disabled = true; $('#e2e-err', md).textContent = tr('Creating the keys…');
      let code;
      try { code = await e2eCreate(pass); } catch (x) { $('#e2e-err', md).textContent = x.message; b.disabled = false; return; }
      md.remove(); await e2eCodeDlg(code); done(true); e2eRefresh();
    });
    setTimeout(() => $('#e2e-p1', md)?.focus(), 50);
  });
}
async function e2eCreate(pass) {
  const kp = await crypto.subtle.generateKey({name: 'ECDH', namedCurve: 'P-256'}, true, ['deriveBits']);
  const jp = await crypto.subtle.exportKey('jwk', kp.privateKey), ju = await crypto.subtle.exportKey('jwk', kp.publicKey);
  const bundle = {v: E2E_V, priv: jp, ck: e2eB64(e2eRand(32))}, code = e2eCodeMake();
  const pub = {kty: 'EC', crv: 'P-256', x: ju.x, y: ju.y};
  const body = {pub, bundle_pass: await e2eWrapPass(bundle, pass), bundle_rec: await e2eWrapCode(bundle, code.bytes)};
  await rawFetch('PUT', '/api/e2e/keys', body);
  E2E.st = {set: true, ...body};
  await e2eAdopt(bundle);
  return code.text;
}
// the recovery code once; closing needs the tick "I have written it down"
function e2eCodeDlg(code) {
  return new Promise(done => {
    const md = modal(`<h3>${tr('Your recovery code')}</h3><p class="muted">${tr('With this code you can set a new passphrase if you forget it. Write it down or keep it in a password manager. It is shown only now.')}</p>
      <code class="e2ecode" id="e2e-code">${esc(code)}</code>
      <div class="row"><button type="button" class="btn sm" data-m="copy">${ic('copy', 's')} ${tr('Copy')}</button></div>
      <label class="chkl"><input type="checkbox" id="e2e-noted"> ${tr('I have written down the recovery code')}</label>
      <div class="foot"><span class="spacer"></span><button type="button" class="btn pri" data-m="done" disabled>${tr('Done')}</button></div>`);
    md.classList.add('e2edlg');
    md.addEventListener('mousedown', e => { if (e.target === md) e.stopImmediatePropagation(); }, true);  // not by a click beside it
    md.addEventListener('change', e => { if (e.target.id === 'e2e-noted') $('[data-m="done"]', md).disabled = !e.target.checked; });
    md.addEventListener('click', e => {
      if (e.target.closest('[data-m="copy"]')) clipCopy(code);
      if (e.target.closest('[data-m="done"]') && $('#e2e-noted', md).checked) { md.remove(); done(); }
    });
  });
}
// a new passphrase with the recovery code (the code stays the same)
function e2eResetDlg() {
  return new Promise(done => {
    const md = modal(`<h3>${tr('Reset the passphrase with the recovery code')}</h3><form class="e2eform" novalidate>
      <input id="e2e-code-in" placeholder="XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX" aria-label="${esc(tr('Recovery code'))}" autocomplete="off" autocapitalize="characters" spellcheck="false" required>
      ${e2ePassHtml()}<div class="aerr" role="alert" id="e2e-err"></div>
      <div class="foot"><span class="spacer"></span><button type="button" class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" type="submit">${tr('Save')}</button></div></form>`);
    md.classList.add('e2edlg');
    md.addEventListener('click', e => { if (e.target.closest('[data-m="close"]')) { md.remove(); done(false); } });
    md.querySelector('form').addEventListener('submit', async e => {
      e.preventDefault();
      const code = e2eCodeParse($('#e2e-code-in', md).value); if (!code) { $('#e2e-err', md).textContent = tr('The recovery code has 32 letters and digits'); return; }
      const [pass, msg] = e2ePassFields(md); if (!pass) { $('#e2e-err', md).textContent = msg; return; }
      let bundle;
      try { bundle = await e2eUnwrapCode(E2E.st.bundle_rec, code); } catch { $('#e2e-err', md).textContent = tr('Wrong recovery code'); return; }
      try { await e2eRewrap(bundle, pass); } catch (x) { $('#e2e-err', md).textContent = x.message; return; }
      await e2eAdopt(bundle); md.remove(); toast(tr('New passphrase saved')); done(true); e2eRefresh();
    });
    setTimeout(() => $('#e2e-code-in', md)?.focus(), 50);
  });
}
// 2.42.0 (#828): replacing or removing existing keys asks for the account password (accounts without one: no prompt);
// null = cancelled
async function e2eAcctPw() {
  if (E2E.st?.password === false) return '';
  const p = await pwPrompt(tr('Confirm with your password'), {text: esc(tr('Changing or removing your encryption keys needs your account password.'))});
  return p ? p.password : null;
}
async function e2eRewrap(bundle, pass) {
  const body = {pub: e2eBundlePub(bundle), bundle_pass: await e2eWrapPass(bundle, pass), bundle_rec: E2E.st.bundle_rec};
  const password = await e2eAcctPw(); if (password === null) throw new Error(tr('Cancelled'));
  await rawFetch('PUT', '/api/e2e/keys', {...body, password, ...(E2E.badPub ? {repair: true} : {})});
  E2E.st = {...E2E.st, ...body};
}
function e2ePassDlg() {
  return new Promise(done => {
    const md = modal(`<h3>${tr('Change the passphrase')}</h3><form class="e2eform" novalidate>
      <input type="password" id="e2e-old" placeholder="${esc(tr('Current passphrase'))}" aria-label="${esc(tr('Current passphrase'))}" autocomplete="off" data-1p-ignore data-lpignore="true" data-bwignore required>
      ${e2ePassHtml()}<div class="aerr" role="alert" id="e2e-err"></div>
      <div class="foot"><span class="spacer"></span><button type="button" class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" type="submit">${tr('Save')}</button></div></form>`);
    md.classList.add('e2edlg');
    md.addEventListener('click', e => { if (e.target.closest('[data-m="close"]')) { md.remove(); done(false); } });
    md.querySelector('form').addEventListener('submit', async e => {
      e.preventDefault();
      const [pass, msg] = e2ePassFields(md); if (!pass) { $('#e2e-err', md).textContent = msg; return; }
      let bundle;
      try { bundle = await e2eUnwrapPass(E2E.st.bundle_pass, $('#e2e-old', md).value); } catch { $('#e2e-err', md).textContent = tr('Wrong passphrase'); return; }
      try { await e2eRewrap(bundle, pass); } catch (x) { $('#e2e-err', md).textContent = x.message; return; }
      md.remove(); toast(tr('New passphrase saved')); done(true);
    });
    setTimeout(() => $('#e2e-old', md)?.focus(), 50);
  });
}
async function e2eRemove() {
  if (!await askConfirm(tr('Remove your encryption keys?'), tr('Your encrypted notes are deleted, your encrypted files and messages can never be opened again, encrypted conversations are switched off. This cannot be undone.'), {ok: tr('Remove for good'), danger: true})) return false;
  const password = await e2eAcctPw(); if (password === null) return false;
  try { await rawFetch('DELETE', '/api/e2e/keys', {password}); } catch (x) { toast(x.message); return false; }
  await e2eForget(); E2E.st = {set: false}; toast(tr('Encryption keys removed')); e2eRefresh();
  return true;
}

// ------------------------------------------------------------------ Settings > Account > End-to-end encryption
const e2eHtml = () => S.me?.kind === 'agent' ? '' : `<h4 id="s-e2e-h">${tr('End-to-end encryption')}</h4><div id="s-e2e"><div class="muted mhint">${tr('Loading…')}</div></div>`;
async function e2eDraw(md) {
  const box = $('#s-e2e', md); if (!box) return;
  if (!globalThis.crypto?.subtle) { box.innerHTML = `<div class="shint">${tr('This browser cannot encrypt here (it needs HTTPS and a current browser).')}</div>`; return; }
  const st = await e2eLoad(true);
  if (!st) { box.innerHTML = `<div class="muted mhint">${tr('Only available online.')}</div>`; return; }
  const limits = `<details class="e2einfo"><summary>${tr('What it protects, and what not')}</summary><p class="muted">${tr('Encrypted notes, files and direct messages are encrypted in your browser. The server, its database and its backups only hold unreadable data: neither the operator nor agents can read them. Titles, dates and reminders stay normal. A web app has a limit: whoever controls the server could deliver a changed script. Encrypted direct messages have no forward secrecy: whoever gets your keys later can read old messages too. Encrypted files have no preview and are not searched.')}</p></details>`;
  if (!st.set) {
    box.innerHTML = `<div class="row"><label>${tr('State')}</label><span class="tfastate">${tr('Not set up')}</span><button class="btn sm pri" data-e2e="setup">${ic('lock', 's')} ${tr('Set up')}</button></div>
      <div class="shint">${tr('For an encrypted note on a task, encrypted files and encrypted direct messages. Only you hold the keys.')}</div>${limits}`;
    return;
  }
  const on = e2eUnlocked();
  box.innerHTML = `<div class="row"><label>${tr('State')}</label><span class="tfastate ${on ? 'on' : ''}">${on ? tr('Unlocked') : tr('Locked')}</span>
      ${on ? `<button class="btn sm" data-e2e="lock">${ic('lock', 's')} ${tr('Lock')}</button>` : `<button class="btn sm pri" data-e2e="unlock">${ic('lock', 's')} ${tr('Unlock')}</button>`}</div>
    ${E2E.badPub ? `<div class="e2ewarn" role="alert">${tr('Your public key on the server does not match your keys. Encrypted messages are blocked.')} ${tr('Change your passphrase in Settings > Account to store your correct key again, then compare the safety number.')}</div>` : ''}
    <div class="row"><label>${tr('Passphrase')}</label><button class="btn sm" data-e2e="pass">${tr('Change')}</button><button class="btn sm" data-e2e="reset">${tr('Reset with the recovery code')}</button></div>
    <div class="row"><label>${tr('Keys')}</label><button class="btn sm danger" data-e2e="remove">${ic('trash', 's')} ${tr('Remove')}</button></div>
    <div class="shint">${tr('Unlocked keys stay in this tab until you lock or log out ("Remember on this device" keeps them in this browser until you log out).')}</div>${limits}`;
}
function e2eWire(md) {
  md.addEventListener('click', async e => {
    const b = e.target.closest('#s-e2e [data-e2e]'); if (!b) return;
    const a = b.dataset.e2e; b.disabled = true;
    try {
      if (a === 'setup') await e2eSetupDlg();
      if (a === 'unlock') await e2eUnlockDlg();
      if (a === 'lock') e2eLock();
      if (a === 'pass') await e2ePassDlg();
      if (a === 'reset') await e2eResetDlg();
      if (a === 'remove') await e2eRemove();
    } finally { b.disabled = false; e2eDraw(md); }
  });
}

// ------------------------------------------------------------------ #828 the encrypted note of a task
const e2eNoteAad = tid => `kalmido-note:v1:${tid}:${S.me.id}`;
function e2eNoteHtml(t) {
  if (!S.me || S.me.kind === 'agent' || !(t.id > 0) || t.context || !globalThis.crypto?.subtle) return '';
  if (!E2E.st) { e2eLoad().then(() => { if (E2E.st?.set && S.sel === t.id) renderDetail(); }); return ''; }
  if (!E2E.st.set && !t.encrypted_note_mine) return '';
  const lock = ic('lock', 's'), mine = !!t.encrypted_note_mine, n = E2E.notes[t.id];
  const head = `<h5>${lock} ${tr('Encrypted note')}</h5>`;
  if (!e2eUnlocked()) {
    if (!mine) return ''; // 2.46.2 (#1663): encryption locked and no note of mine: hide the field
    return `<div class="dsec e2enote" id="d-enc">${head}<button type="button" class="btn sm" data-e2e="note-unlock">${lock} ${tr('Unlock')}</button></div>`;
  }
  if (n?.loading) return `<div class="dsec e2enote" id="d-enc">${head}<div class="muted mhint">${tr('Decrypting…')}</div></div>`;
  if (mine && (!n || n.tid !== t.id)) { e2eNoteLoad(t.id); return `<div class="dsec e2enote" id="d-enc">${head}<div class="muted mhint">${tr('Decrypting…')}</div></div>`; }
  if (!mine && !n?.open) return `<div class="dsec e2enote e2eadd" id="d-enc"><button type="button" class="linkbtn" data-e2e="note-new">${lock}<span>${tr('Encrypted note')}</span></button></div>`;
  if (n?.err) return `<div class="dsec e2enote" id="d-enc">${head}<div class="muted">${tr('Cannot be decrypted')}</div><button type="button" class="btn sm danger" data-e2e="note-del">${ic('trash', 's')} ${tr('Delete')}</button></div>`;
  return `<div class="dsec e2enote" id="d-enc">${head}<textarea id="d-enc-in" class="dcontent" rows="3" placeholder="${esc(tr('Only you can read this note'))}" aria-label="${esc(tr('Encrypted note'))}" spellcheck="true">${esc(n?.text || '')}</textarea>
    <div class="e2emeta"><span class="muted" id="d-enc-st" role="status">${esc(n?.state || tr('Encrypted in your browser; only you can read it'))}</span><span class="spacer"></span>${mine ? `<button type="button" class="iconbtn" data-e2e="note-del" title="${esc(tr('Delete the encrypted note'))}" aria-label="${esc(tr('Delete the encrypted note'))}">${ic('trash', 's')}</button>` : ''}</div></div>`;
}
async function e2eNoteLoad(tid) {
  E2E.notes[tid] = {tid, text: '', loading: true};
  let j;
  try { j = await rawFetch('GET', `/api/tasks/${tid}/enc-note`); }
  catch (x) { E2E.notes[tid] = {tid, text: '', open: true, err: x.status !== 404}; if (x.status === 404) E2E.notes[tid].err = false; if (S.sel === tid) renderDetail(); return; }
  try { E2E.notes[tid] = {tid, text: e2eTDec().decode(await e2eOpen(E2E.ckey, j.body, e2eNoteAad(tid))), open: true}; }
  catch { E2E.notes[tid] = {tid, text: '', open: true, err: true}; }
  if (S.sel === tid) renderDetail();
}
async function e2eNoteSave(tid) {
  const n = E2E.notes[tid]; if (!n || !e2eUnlocked()) return;
  const st = () => { const el = $('#d-enc-st'); if (el) el.textContent = n.state; };
  try {
    if (!n.text.trim()) { await rawFetch('DELETE', `/api/tasks/${tid}/enc-note`); e2eTaskFlag(tid, false); n.state = tr('Empty: no encrypted note'); }
    else { await rawFetch('PUT', `/api/tasks/${tid}/enc-note`, {body: await e2eSeal(E2E.ckey, e2eTEnc().encode(n.text), e2eNoteAad(tid))}); e2eTaskFlag(tid, true); n.state = tr('Encrypted and saved'); }
  } catch (x) { n.state = x instanceof Offline ? tr('Offline: the encrypted note is saved when you are online again') : x.message; if (x instanceof Offline) E2E.saveT = setTimeout(() => e2eNoteSave(tid), 15000); }
  st();
}
function e2eTaskFlag(tid, on) {
  const t = taskById(tid); if (!t) return;
  if (on) { t.encrypted_note = true; t.encrypted_note_mine = true; } else { delete t.encrypted_note_mine; }
}
document.addEventListener('input', e => {
  if (e.target.id !== 'd-enc-in' || !S.sel) return;
  const tid = S.sel, n = E2E.notes[tid] || (E2E.notes[tid] = {tid, open: true});
  n.text = e.target.value; n.state = tr('Saving…'); autosize(e.target);
  clearTimeout(E2E.saveT); E2E.saveT = setTimeout(() => e2eNoteSave(tid), 900);
});
document.addEventListener('focusout', e => { if (e.target.id === 'd-enc-in' && S.sel && E2E.saveT) { clearTimeout(E2E.saveT); E2E.saveT = null; e2eNoteSave(S.sel); } });

// ------------------------------------------------------------------ #828 encrypted files
// format: "KENC" 0x01 | iv (12) | AES-GCM( u32 header length | header JSON {name, type, size} | the file ), AAD binds task + person
const e2eFileAad = (tid, uid) => `kalmido-file:v1:${tid}:${uid}`;
async function e2eFileEncrypt(file, tid) {
  const head = e2eTEnc().encode(JSON.stringify({name: file.name || 'file', type: file.type || 'application/octet-stream', size: file.size}));
  const data = new Uint8Array(await file.arrayBuffer()), plain = new Uint8Array(4 + head.length + data.length);
  new DataView(plain.buffer).setUint32(0, head.length); plain.set(head, 4); plain.set(data, 4 + head.length);
  const iv = e2eRand(12), ct = new Uint8Array(await crypto.subtle.encrypt({name: 'AES-GCM', iv, additionalData: e2eTEnc().encode(e2eFileAad(tid, S.me.id))}, E2E.ckey, plain));
  const out = new Uint8Array(5 + 12 + ct.length);
  out.set([0x4b, 0x45, 0x4e, 0x43, 0x01]); out.set(iv, 5); out.set(ct, 17);
  return out;
}
async function e2eFileDecrypt(buf, tid) {
  const u = new Uint8Array(buf);
  if (u.length < 17 + 16 || String.fromCharCode(...u.subarray(0, 4)) !== 'KENC' || u[4] !== 1) throw new Error('format');
  const plain = new Uint8Array(await crypto.subtle.decrypt({name: 'AES-GCM', iv: u.subarray(5, 17), additionalData: e2eTEnc().encode(e2eFileAad(tid, S.me.id))}, E2E.ckey, u.subarray(17)));
  const n = new DataView(plain.buffer).getUint32(0), head = JSON.parse(e2eTDec().decode(plain.subarray(4, 4 + n)));
  return {name: String(head.name || 'file'), type: String(head.type || 'application/octet-stream'), data: plain.subarray(4 + n)};
}
async function e2eUpload(tid, files) {
  files = noEmpty(files); if (!files.length) return;
  if (!(tid > 0)) { toast(tr('Task is still syncing, try again in a moment')); return; }
  const max = 50 * 1024 * 1024, big = files.find(f => f.size > max);
  if (big) { toast(tr('{0} is larger than 50 MB', big.name)); return; }
  if (!await e2eEnsure()) return;
  toast(tr('Encrypting…'));
  let t;
  for (const f of files) {
    const fd = new FormData();
    fd.append('file', new Blob([await e2eFileEncrypt(f, tid)], {type: 'application/octet-stream'}), 'encrypted.kenc');
    try { t = await rawFetch('POST', `/api/tasks/${tid}/enc-attachments`, fd); }
    catch (x) { if (!x.shown) toast(x instanceof Offline ? tr('Offline: only works again with a connection') : x.message); return; }
  }
  putTask(t); render(); if (S.sel === tid) renderDetail();
  toast(files.length === 1 ? tr('Encrypted and attached') : tr('{0} files encrypted and attached', files.length));
}
async function e2eAttOpen(aid) {
  const t = taskById(S.sel), a = (t?.attachments || []).find(x => x.id === aid); if (!a) return;
  if (!a.enc_mine) { toast(tr('Only the person who attached this encrypted file can open it')); return; }
  if (!await e2eEnsure()) return;
  let r;
  try { r = await fetch(`/api/attachments/${aid}?dl=1`, {headers: {'X-Requested-With': 'kalmido'}}); } catch { toast(tr('Offline: only works again with a connection')); return; }
  if (!r.ok) { toast(tr('File damaged or missing')); return; }
  let f;
  try { f = await e2eFileDecrypt(await r.arrayBuffer(), t.id); } catch { toast(tr('Cannot be decrypted')); return; }
  const url = URL.createObjectURL(new Blob([f.data], {type: f.type})), el = document.createElement('a');
  el.href = url; el.download = f.name; document.body.appendChild(el); el.click(); el.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30000);
}
function e2eAttHtml(a, del) {
  return `<div class="att file e2eatt"><button type="button" class="attx" data-e2e="att-open" data-att="${a.id}" title="${esc(a.enc_mine ? tr('Decrypt and download') : tr('Only the person who attached it can open it'))}">${ic('lock')}<span class="atxt"><span class="an">${esc(tr('Encrypted file'))}</span><span class="as">${esc(fmtSize(a.size || 0))}${a.enc_mine ? '' : ' · ' + esc(tr('not yours'))}</span></span></button>${del}</div>`;
}
const e2eAttAddHtml = t => !globalThis.crypto?.subtle || !E2E.st?.set || !(t.id > 0) ? '' : `<label class="attadd e2eattadd" title="${esc(tr('Encrypted in your browser; no preview, not searched'))}">${ic('lock', 's')}<span>${tr('Attach encrypted')}</span><input type="file" id="d-efile" multiple hidden></label>`;
document.addEventListener('change', e => { if (e.target.id === 'd-efile' && S.sel) { const fs = [...e.target.files]; e.target.value = ''; e2eUpload(S.sel, fs); } });

// ------------------------------------------------------------------ #909 encrypted direct messages
async function e2ePeer(uid) {
  if (E2E.peers[uid] !== undefined) return E2E.peers[uid];
  const j = await rawFetch('GET', `/api/e2e/pub/${uid}`);
  E2E.peers[uid] = j.pub || null;
  return E2E.peers[uid];
}
// the other person of a DM: the conversation list, else the members of the open room (a new DM is not listed before its first message)
const e2eDmOther = room => (S.tc.rooms || []).find(x => x.id === room.id)?.user_id
  || (S.tc.room?.id === room.id ? (S.tc.room.members || []).find(m => m.id !== S.me?.id)?.id : undefined);
async function e2eDmKey(rid, other) {
  if (E2E.dm[rid]) return E2E.dm[rid];
  const pub = await e2ePeer(other); if (!pub) throw new Error('nopeer');
  const pk = await crypto.subtle.importKey('jwk', {kty: 'EC', crv: 'P-256', x: pub.x, y: pub.y}, {name: 'ECDH', namedCurve: 'P-256'}, false, []);
  const bits = await crypto.subtle.deriveBits({name: 'ECDH', public: pk}, E2E.priv, 256);
  const hk = await crypto.subtle.importKey('raw', bits, 'HKDF', false, ['deriveKey']);
  E2E.dm[rid] = await crypto.subtle.deriveKey({name: 'HKDF', hash: 'SHA-256', salt: e2eTEnc().encode(String(rid)), info: e2eTEnc().encode('kalmido-dm:v1')}, hk, {name: 'AES-GCM', length: 256}, false, ['encrypt', 'decrypt']);
  return E2E.dm[rid];
}
const e2eDmAad = (rid, sender) => `kalmido-dm:v1:${rid}:${sender}`;
async function e2eDmEncrypt(rid, text) {
  const other = e2eDmOther({id: rid}); if (!other) throw new Error(tr('Error {0}', 'room'));
  if (!await e2eEnsure()) return null;
  if (E2E.badPub) throw new Error(tr('Your public key on the server does not match your keys. Encrypted messages are blocked.'));
  let key;
  try { key = await e2eDmKey(rid, other); } catch { throw new Error(tr('{0} has not set up encryption yet', uname(other, S.tc.users))); }
  return e2eSeal(key, e2eTEnc().encode(text), e2eDmAad(rid, S.me.id));
}
// the plain texts known from this session first (no flicker), the rest decrypted in the background
function e2eFromCache(msgs) {
  for (const m of msgs || []) {
    if (!m.enc || m.enc.sys) continue;
    const k = m.id + ':' + (m.edited_at || ''), p = E2E.dec[k];
    if (p !== undefined) { m.body = p; m._dec = true; }
  }
  e2eQuotes(msgs);
}
function e2eQuotes(msgs) {
  for (const m of msgs || []) {
    if (!m.reply?.enc) continue;
    const o = msgs.find(x => x.id === m.reply.id);
    m.reply.text = o?._dec ? mdBrief(o.body).slice(0, 120) : tr('Encrypted message');
  }
}
// 2.42.0 (#909): this browser remembers that a DM was encrypted (LS e2eOn:<me>:<rid> = the newest message id seen while on).
// The server reports it off without a newer "switched off" notice -> a warning, and plain text only after a confirmation.
function e2eDownCheck(room) {
  const k = `e2eOn:${S.me.id}:${room.id}`, mark = LS.get(k, null), msgs = S.tc.msgs || [];
  const top = msgs.reduce((a, m) => Math.max(a, m.id || 0), 0);
  if (room.e2e) { LS.set(k, Math.max(mark || 0, top)); delete E2E.down[room.id]; return; }
  if (mark === null) return;
  if (msgs.some(m => m.enc?.sys === 'off' && m.id > mark)) { LS.del(k); delete E2E.down[room.id]; return; }
  if (!E2E.down[room.id]) { E2E.down[room.id] = true; if (S.tc.rid === room.id) renderView(); }
}
// before a plain message: true = send (no warning, or confirmed once)
async function e2eDownOk(rid) {
  if (!E2E.down[rid]) return true;
  if (!await askConfirm(tr('Send without encryption?'), tr('Encryption of this conversation was switched off outside the conversation (no notice from either of you). The message would not be encrypted.'), {ok: tr('Send unencrypted'), danger: true})) return false;
  e2eDownAccept(rid);
  return true;
}
function e2eDownAccept(rid) { LS.del(`e2eOn:${S.me.id}:${rid}`); delete E2E.down[rid]; }
async function e2eRoomDecrypt(rid) {
  const room = S.tc.room; if (!room || room.id !== rid || room.kind !== 'dm') return;
  e2eDownCheck(room);
  const other = e2eDmOther(room), need = (S.tc.msgs || []).filter(m => m.enc && !m.enc.sys && !m._dec && !m.deleted);
  if (other && (room.e2e || need.length)) e2eCheckPeer(rid, other);
  if (!need.length) { e2eQuotes(S.tc.msgs); return; }
  await e2eLoad();
  if (!e2eUnlocked() || !other) return;
  let key = null;
  try { key = await e2eDmKey(rid, other); } catch { /* the other person has no key (any more) */ }
  for (const m of need) {
    try { m.body = e2eTDec().decode(await e2eOpen(key, m.enc, e2eDmAad(rid, m.user_id))); m._dec = true; E2E.dec[m.id + ':' + (m.edited_at || '')] = m.body; }
    catch { m._fail = true; }
  }
  e2eQuotes(S.tc.msgs);
  if (S.tc.rid === rid) tcPatch();
}
// the safety number: SHA-256 over both public keys (sorted), 8 groups of 5 digits; the same on both sides
async function e2eSafety(a, b) {
  const ks = [a, b].map(k => k.x + '.' + k.y).sort();
  const h = new Uint8Array(await crypto.subtle.digest('SHA-256', e2eTEnc().encode('kalmido-safety:v1|' + ks.join('|'))));
  const out = [];
  for (let i = 0; i < 32; i += 4) out.push(String(new DataView(h.buffer).getUint32(i) % 100000).padStart(5, '0'));
  return out.join(' ');
}
// the other person's key changed since this browser last saw it -> a clear notice in the conversation
async function e2eCheckPeer(rid, other) {
  let pub; try { pub = await e2ePeer(other); } catch { return; }
  if (!pub) return;
  const k = `e2eSeen:${S.me.id}:${other}`, fp = pub.x + '.' + pub.y, seen = LS.get(k, '');
  if (!seen) LS.set(k, fp);
  else if (seen !== fp && !E2E.warn[rid]) { E2E.warn[rid] = fp; if (S.tc.rid === rid) renderView(); }
}
function e2eRoomBtns(room) {
  if (!room || room.kind !== 'dm' || !globalThis.crypto?.subtle) return '';
  const on = !!room.e2e;
  return `<button type="button" class="iconbtn ${on ? 'on' : ''}" data-e2e="dm-toggle" aria-pressed="${on}" title="${esc(on ? tr('Encrypted conversation: tap to switch off') : tr('Encrypted conversation'))}" aria-label="${esc(tr('Encrypted conversation'))}">${ic('lock')}</button>
    ${on ? `<button type="button" class="iconbtn" data-e2e="dm-safety" title="${esc(tr('Safety number'))}" aria-label="${esc(tr('Safety number'))}">${ic('key')}</button>` : ''}`;
}
function e2eRoomNotice(room) {
  if (!room || room.kind !== 'dm') return '';
  const w = E2E.warn[room.id];
  return (E2E.down[room.id] && !room.e2e ? `<div class="e2ewarn" role="alert">${ic('lock', 's')}<span>${tr('Encryption of this conversation was switched off outside the conversation (no notice from either of you). The message would not be encrypted.')}</span><button type="button" class="btn sm pri" data-e2e="dm-toggle">${tr('Encrypt again')}</button><button type="button" class="btn sm" data-e2e="dm-down-ok">${tr('Send unencrypted')}</button></div>` : '')
    + (E2E.badPub ? `<div class="e2ewarn" role="alert">${ic('lock', 's')}<span>${tr('Your public key on the server does not match your keys. Encrypted messages are blocked.')} ${tr('Change your passphrase in Settings > Account to store your correct key again, then compare the safety number.')}</span></div>` : '')
    + (w ? `<div class="e2ewarn" role="alert">${ic('lock', 's')}<span>${tr('The key of {0} has changed. Compare the safety number with them before you write anything confidential.', esc(uname(e2eDmOther(room), S.tc.users)))}</span><button type="button" class="btn sm" data-e2e="dm-safety">${tr('Safety number')}</button><button type="button" class="btn sm" data-e2e="dm-seen">${tr('Understood')}</button></div>` : '')
    + (room.e2e && !e2eUnlocked() ? `<div class="e2ehint">${ic('lock', 's')}<span>${tr('Encrypted conversation: unlock to read and write.')}</span><button type="button" class="btn sm pri" data-e2e="dm-unlock">${tr('Unlock')}</button></div>` : '');
}
// the body of an encrypted message (or a notice) in the conversation; null = not encrypted
function e2eMsgBody(m) {
  if (!m.enc) return null;
  if (m.enc.sys) return `<div class="e2esys muted">${ic('lock', 's')}<span>${esc((w => m.enc.sys === 'on' ? tr('{0} switched encryption on', w) : tr('{0} switched encryption off', w))(m.user_id === S.me?.id ? tr('You') : uname(m.user_id, S.tc.users)))}</span></div>`;
  if (m._dec) return null;
  if (m._fail) return `<div class="cbub e2emsg"><span class="muted">${ic('lock', 's')} ${tr('Cannot be decrypted')}</span></div>`;
  return `<div class="cbub e2emsg"><button type="button" class="linkbtn" data-e2e="dm-unlock">${ic('lock', 's')} ${tr('Encrypted message')}</button></div>`;
}
const e2eBriefText = last => last?.enc === 'msg' ? tr('Encrypted message') : last?.enc === 'on' ? tr('Encryption switched on') : last?.enc === 'off' ? tr('Encryption switched off') : null;
async function e2eDmToggle() {
  const room = S.tc.room; if (!room || room.kind !== 'dm') return;
  const on = !room.e2e;
  if (on) {
    if (!await e2eEnsure()) return;
    if (E2E.badPub) { toast(tr('Your public key on the server does not match your keys. Encrypted messages are blocked.')); return; }
    const other = e2eDmOther(room);
    let pub = null; try { E2E.peers[other] = undefined; pub = await e2ePeer(other); } catch { /* offline */ }
    if (!pub) { toast(tr('{0} has not set up encryption yet', uname(other, S.tc.users))); return; }
    if (!await askConfirm(tr('Encrypt this conversation?'), tr('New messages are encrypted in the browser: only you two can read them, the server and agents cannot. Messages are not searched and cannot be saved as tasks. Compare the safety number to be sure.'), {ok: tr('Encrypt')})) return;
  } else if (!await askConfirm(tr('Switch encryption off?'), tr('New messages are no longer encrypted. Earlier encrypted messages stay encrypted.'), {ok: tr('Switch off')})) return;
  try { await rawFetch('POST', `/api/team/rooms/${room.id}/e2e`, {on}); } catch (x) { toast(x.message); return; }
  room.e2e = on; const r = (S.tc.rooms || []).find(x => x.id === room.id); if (r) r.e2e = on;
  if (!on) e2eDownAccept(room.id);
  await loadRoom(room.id); renderView();
}
async function e2eSafetyDlg() {
  const room = S.tc.room, other = room && e2eDmOther(room); if (!other) return;
  await e2eLoad();
  let num = '';
  // my own key from my unlocked bundle, never the server's copy (that one could be swapped together with the other person's)
  if (!await e2eEnsure()) return;
  try { E2E.peers[other] = undefined; const p = await e2ePeer(other); if (p && E2E.own && !E2E.badPub) num = await e2eSafety(E2E.own, p); } catch { /* offline */ }
  await askDialog({title: tr('Safety number'), html: E2E.badPub ? `<p class="e2ewarn">${tr('Your public key on the server does not match your keys. Encrypted messages are blocked.')} ${tr('Change your passphrase in Settings > Account to store your correct key again, then compare the safety number.')}</p>` : num ? `<p>${tr('Compare this number with {0} (in person or by phone). If it is the same on both devices, nobody sits in between.', esc(uname(other, S.tc.users)))}</p><code class="e2ecode">${esc(num)}</code>` : `<p>${tr('{0} has not set up encryption yet', esc(uname(other, S.tc.users)))}</p>`, ok: tr('OK'), cancel: tr('Close')});
}
document.addEventListener('click', async e => {
  const b = e.target.closest('[data-e2e]'); if (!b || b.closest('#s-e2e')) return;
  const a = b.dataset.e2e;
  if (a === 'note-unlock' || a === 'dm-unlock') { await e2eEnsure(); return; }
  if (a === 'note-new') { if (!await e2eEnsure()) return; E2E.notes[S.sel] = {tid: S.sel, text: '', open: true}; renderDetail(); setTimeout(() => $('#d-enc-in')?.focus(), 30); return; }
  if (a === 'note-del') {
    const tid = S.sel; if (!await askConfirm(tr('Delete the encrypted note?'), '', {ok: tr('Delete'), danger: true})) return;
    try { await rawFetch('DELETE', `/api/tasks/${tid}/enc-note`); } catch (x) { toast(x.message); return; }
    delete E2E.notes[tid]; e2eTaskFlag(tid, false); const t = taskById(tid); if (t && !t.encrypted_note_mine) delete t.encrypted_note; renderDetail(); return;
  }
  if (a === 'att-open') { e2eAttOpen(+b.dataset.att); return; }
  if (a === 'dm-toggle') { e2eDmToggle(); return; }
  if (a === 'dm-safety') { e2eSafetyDlg(); return; }
  if (a === 'dm-down-ok') { e2eDownAccept(S.tc.rid); renderView(); return; }
  if (a === 'dm-seen') { const rid = S.tc.rid, other = e2eDmOther(S.tc.room || {}); if (other && E2E.warn[rid]) LS.set(`e2eSeen:${S.me.id}:${other}`, E2E.warn[rid]); delete E2E.warn[rid]; renderView(); }
});
