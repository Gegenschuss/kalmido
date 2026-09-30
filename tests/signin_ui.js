// Sign-in + backups UI (package A, jsdom): Settings > Account > Two-factor (TOTP setup with the QR code, recovery codes
// dialog, passkey added through a fake navigator.credentials that signs like a real authenticator), the login screen
// (OIDC button, error text after a refused OIDC login, second step with a code, recovery code, passwordless passkey
// login, forced enrolment), Settings > Users > Whole server (sign-in switches, OIDC block, backups: save, back up now,
// the list, restore dialog with the confirmation word), German labels. The page runs on http://localhost (a secure
// context for WebAuthn; RP ID "localhost"). Starts its own container (start.sh).
process.env.BASE = process.env.BASE || `http://localhost:${process.env.KALMIDO_TEST_PROXY_PORT || 3041}/`;
const path = require('path');
const crypto = require('crypto');
const {execFileSync} = require('child_process');
const {JSDOM, VirtualConsole} = require('jsdom');
const {B, login, sleep} = require('./boot');
const DATA = process.argv[2] || path.join(__dirname, '.data');
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const F = []; let ok = 0; const errs = [];
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const submit = (w, form) => form.dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true}));
const input = (w, el, v) => { el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); };
const b64u = b => Buffer.from(b).toString('base64url');
function totp(secret, step) {
  const s = secret.replace(/\s/g, ''), al = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  let bits = ''; for (const ch of s) bits += al.indexOf(ch).toString(2).padStart(5, '0');
  const key = Buffer.from(bits.match(/.{8}/g).map(x => parseInt(x, 2)));
  const msg = Buffer.alloc(8); msg.writeBigUInt64BE(BigInt(step ?? Math.floor(Date.now() / 30000)));
  const mac = crypto.createHmac('sha1', key).update(msg).digest(), o = mac[19] & 15;
  return String((mac.readUInt32BE(o) & 0x7fffffff) % 1e6).padStart(6, '0');
}
// ---- CBOR (maps, ints, bytes, text) + a software authenticator (ES256, attestation none)
function head(major, n) { if (n < 24) return Buffer.from([major << 5 | n]); if (n < 256) return Buffer.from([major << 5 | 24, n]); const b = Buffer.alloc(3); b[0] = major << 5 | 25; b.writeUInt16BE(n, 1); return b; }
function cbor(v) {
  if (typeof v === 'number') return v >= 0 ? head(0, v) : head(1, -1 - v);
  if (Buffer.isBuffer(v)) return Buffer.concat([head(2, v.length), v]);
  if (typeof v === 'string') { const e = Buffer.from(v); return Buffer.concat([head(3, e.length), e]); }
  const ents = v instanceof Map ? [...v.entries()] : Object.entries(v);
  return Buffer.concat([head(5, ents.length), ...ents.map(([k, x]) => Buffer.concat([cbor(k), cbor(x)]))]);
}
const AUTH = {creds: []};  // shared by all windows: the "device"
const ab = buf => { const u = new Uint8Array(buf.length); u.set(buf); return u.buffer; };
function fakeCredentials(w) {
  return {
    async create({publicKey: o}) {
      const {privateKey, publicKey} = crypto.generateKeyPairSync('ec', {namedCurve: 'P-256'});
      const jwk = publicKey.export({format: 'jwk'});
      const id = crypto.randomBytes(32);
      const cose = cbor(new Map([[1, 2], [3, -7], [-1, 1], [-2, Buffer.from(jwk.x, 'base64url')], [-3, Buffer.from(jwk.y, 'base64url')]]));
      const len = Buffer.alloc(2); len.writeUInt16BE(id.length);
      const authData = Buffer.concat([crypto.createHash('sha256').update(o.rp.id).digest(), Buffer.from([0x45, 0, 0, 0, 0]), Buffer.alloc(16), len, id, cose]);
      const cd = Buffer.from(JSON.stringify({type: 'webauthn.create', challenge: b64u(Buffer.from(o.challenge)), origin: w.location.origin, crossOrigin: false}));
      AUTH.creds.push({id, privateKey, handle: Buffer.from(o.user.id), rp: o.rp.id, count: 0});
      return {id: b64u(id), rawId: ab(id), type: 'public-key', authenticatorAttachment: 'platform',
        response: {clientDataJSON: ab(cd), attestationObject: ab(cbor({fmt: 'none', attStmt: {}, authData})), getTransports: () => ['internal']},
        getClientExtensionResults: () => ({credProps: {rk: true}})};
    },
    async get({publicKey: o}) {
      const allow = (o.allowCredentials || []).map(c => Buffer.from(c.id).toString('hex'));
      const c = AUTH.creds.find(x => !allow.length || allow.includes(x.id.toString('hex')));
      if (!c) { const e = new Error('no credential'); e.name = 'NotAllowedError'; throw e; }
      c.count++;
      const cnt = Buffer.alloc(4); cnt.writeUInt32BE(c.count);
      const authData = Buffer.concat([crypto.createHash('sha256').update(o.rpId).digest(), Buffer.from([0x05]), cnt]);
      const cd = Buffer.from(JSON.stringify({type: 'webauthn.get', challenge: b64u(Buffer.from(o.challenge)), origin: w.location.origin, crossOrigin: false}));
      const sig = crypto.sign('sha256', Buffer.concat([authData, crypto.createHash('sha256').update(cd).digest()]), {key: c.privateKey, dsaEncoding: 'der'});
      return {id: b64u(c.id), rawId: ab(c.id), type: 'public-key', response: {clientDataJSON: ab(cd), authenticatorData: ab(authData), signature: ab(sig), userHandle: ab(c.handle)}};
    },
  };
}
// jsdom page with its own cookie jar (the login flows set / change cookies)
async function page({cookie = '', hash = '', lang = null, wait = 2000, passkeys = true} = {}) {
  const jar = new Map(cookie ? [cookie.split('=')] : []);
  const store = lang ? {lang: JSON.stringify(lang)} : {};
  const vc = new VirtualConsole(); vc.on('jsdomError', e => { if (!/navigation|Not implemented/.test(e.message)) errs.push(e.message); });
  const dom = await JSDOM.fromURL(B + (hash ? '#' + hash : ''), {runScripts: 'dangerously', resources: 'usable', pretendToBeVisual: true, virtualConsole: vc,
    beforeParse(w) {
      w.matchMedia = () => ({matches: false, addEventListener() {}, addListener() {}});
      Object.defineProperty(w, 'localStorage', {value: {getItem: k => k in store ? store[k] : null, setItem: (k, v) => { store[k] = String(v); }, removeItem: k => { delete store[k]; }, key: i => Object.keys(store)[i], get length() { return Object.keys(store).length; }}});
      w.fetch = async (u, o = {}) => {
        const hd = {...(o.headers || {}), Cookie: [...jar].map(([k, v]) => `${k}=${v}`).join('; ')};
        const body = o.body && o.body.constructor && o.body.constructor.name === 'File' ? Buffer.from(await o.body.arrayBuffer()) : o.body;
        const r = await fetch(new URL(String(u), B), {...o, body, headers: hd, redirect: o.redirect === 'manual' ? 'manual' : 'follow'});
        for (const sc of r.headers.getSetCookie()) { const [kv, ...attrs] = sc.split(';'); const [k, v] = kv.split('='); if (/max-age=0|expires=thu, 01 jan 1970/i.test(attrs.join(';')) || v === '') jar.delete(k.trim()); else jar.set(k.trim(), v); }
        return r;
      };
      w.Request = Request; w.Response = Response; w.Headers = Headers; w.FormData = FormData; w.File = File; w.Blob = Blob;
      Object.defineProperty(w.navigator, 'serviceWorker', {configurable: true, value: {register: () => Promise.resolve(), addEventListener() {}, controller: null}});
      Object.defineProperty(w, 'isSecureContext', {configurable: true, value: true});
      if (passkeys) { w.PublicKeyCredential = function () {}; Object.defineProperty(w.navigator, 'credentials', {configurable: true, value: fakeCredentials(w)}); }
      Object.defineProperty(w.navigator, 'clipboard', {configurable: true, value: {writeText: async t => { w.__clip = t; }}});
      w.URL.createObjectURL = () => 'blob:x'; w.URL.revokeObjectURL = () => {};
      w.scrollTo = () => {}; w.Element.prototype.scrollIntoView = () => {};
      w.confirm = () => true; w.prompt = (q, d) => /passkey/i.test(q) ? 'Laptop' : d;
      require('./boot').dialogBridge(w);
    }});
  await sleep(wait);
  dom.window.__jar = jar;
  return dom.window;
}
const api = async (w, m, u, b) => (await w.fetch(u, {method: m, headers: H, body: b ? JSON.stringify(b) : undefined})).json();
const until = async (fn, t = 5000) => { const t0 = Date.now(); while (Date.now() - t0 < t) { const x = fn(); if (x) return x; await sleep(100); } return fn(); };

(async () => {
  execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env,
    EXTRA: '-e KALMIDO_OIDC_ISSUER=https://id.example -e KALMIDO_OIDC_CLIENT_ID=kalmido -e KALMIDO_OIDC_CLIENT_SECRET=x -e KALMIDO_OIDC_BUTTON_LABEL=Authentik -e KALMIDO_BACKUP_TICK=1'}});
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const ac = await login('alice');
  for (const u of ['bob', 'erin', 'gwen']) await fetch(B + 'api/users', {method: 'POST', headers: {...H, Cookie: ac}, body: JSON.stringify({username: u, password: 'password123'})});

  // ---- Settings > Account > Two-factor: TOTP
  let w = await page({cookie: await login('bob')}), d = w.document;
  w.eval(`settingsModal('account')`); await sleep(700);
  let md = d.querySelector('.smodal');
  check(md.querySelector('#s-2fa-h')?.textContent === 'Two-factor authentication' && /Authenticator app\s*Off/.test(md.querySelector('#s-2fa').textContent), 'account: 2FA section, app off');
  check(!!md.querySelector('[data-tfa="pk-add"]') && !md.querySelector('[data-tfa="pk-add"]').disabled, 'passkey button enabled on localhost with WebAuthn');
  click(w, md.querySelector('[data-tfa="totp-on"]')); await sleep(200);
  let pp = d.querySelector('.pwprompt');
  check(!!pp, 'asks for the password first');
  pp.querySelector('#pp-pw').value = 'password123'; submit(w, pp.querySelector('form')); await sleep(600);
  let tm = d.querySelector('.totpmodal');
  const qr = tm?.querySelector('.totpqr img')?.getAttribute('src') || '';
  const secret = tm?.querySelector('#totp-secret')?.textContent || '';
  check(qr.startsWith('data:image/svg+xml') && /^[A-Z2-7 ]{35,}$/.test(secret), 'setup dialog: QR code (SVG data URI) + key in groups');
  tm.querySelector('#totp-code').value = '000000'; submit(w, tm.querySelector('form')); await sleep(500);
  check(/Wrong code/.test(tm.querySelector('#totp-err').textContent), 'wrong code shown in the dialog');
  tm.querySelector('#totp-code').value = totp(secret); submit(w, tm.querySelector('form')); await sleep(700);
  const rc = d.querySelector('.rcmodal');
  const codes = [...(rc?.querySelectorAll('.rcodes code') || [])].map(x => x.textContent);
  check(codes.length === 10 && codes.every(c => /^[a-z2-9]{5}-[a-z2-9]{5}$/.test(c)), 'recovery codes dialog with 10 codes');
  click(w, rc.querySelector('[data-rc="copy"]')); await sleep(100);
  check((w.__clip || '').includes(codes[0]) && (w.__clip || '').includes(codes[9]), 'copy puts every code on the clipboard');
  click(w, rc.querySelector('[data-m="ok"]')); await sleep(500);
  check(/Authenticator app\s*On/.test(md.querySelector('#s-2fa').textContent) && /10 left/.test(md.querySelector('#s-2fa').textContent), 'section: app on, 10 codes left');
  // passkey via the fake authenticator
  click(w, md.querySelector('[data-tfa="pk-add"]')); await sleep(200);
  pp = d.querySelector('.pwprompt'); pp.querySelector('#pp-pw').value = 'password123'; submit(w, pp.querySelector('form')); await sleep(1000);
  check(md.querySelectorAll('.pklist [data-pk]').length === 1 && /Laptop/.test(md.querySelector('.pklist').textContent), 'passkey added and listed');
  w.close();

  // ---- login screen: OIDC button, error after a refused OIDC login, second step with a code / recovery code
  w = await page({hash: 'login-error=no_account'}); d = w.document;
  const scr = d.querySelector('.authscreen');
  check(!!scr?.querySelector('[data-au="oidc"]') && /Log in with Authentik/.test(scr.querySelector('[data-au="oidc"]').textContent), 'login screen: "Log in with Authentik"');
  check(!!scr.querySelector('[data-au="passkey"]'), 'login screen: "Log in with a passkey"');
  check(/no account for this login/.test(scr.querySelector('#au-err').textContent) && !/login-error/.test(w.location.hash), 'OIDC error shown, hash removed');
  scr.querySelector('#au-user').value = 'bob'; scr.querySelector('#au-pw').value = 'password123';
  submit(w, scr.querySelector('#auth-form')); await sleep(700);
  check(!!scr.querySelector('#tfa-form') && /authenticator app/.test(scr.textContent) && !w.__jar.has('kalmido_session') && w.__jar.has('kalmido_2fa'), 'second step shown, no session yet');
  check(!!scr.querySelector('[data-tfa="pk"]') && !!scr.querySelector('[data-tfa="rc"]'), 'offers the passkey and a recovery code');
  scr.querySelector('#tfa-code').value = '000000'; submit(w, scr.querySelector('#tfa-form')); await sleep(500);
  check(/Wrong code/.test(scr.querySelector('#tfa-err').textContent), 'wrong code shown');
  click(w, scr.querySelector('[data-tfa="rc"]')); await sleep(100);
  scr.querySelector('#tfa-code').value = codes[0]; submit(w, scr.querySelector('#tfa-form')); await sleep(700);
  check(w.__jar.has('kalmido_session') && (await api(w, 'GET', '/api/me')).username === 'bob', 'logged in with a recovery code');
  w.close();
  // second step with the passkey
  w = await page(); d = w.document;
  d.querySelector('#au-user').value = 'bob'; d.querySelector('#au-pw').value = 'password123';
  submit(w, d.querySelector('#auth-form')); await sleep(700);
  click(w, d.querySelector('[data-tfa="pk"]')); await sleep(900);
  check(w.__jar.has('kalmido_session') && (await api(w, 'GET', '/api/me')).via === '2fa', 'second step with the passkey');
  w.close();
  // passwordless
  w = await page(); d = w.document;
  click(w, d.querySelector('[data-au="passkey"]')); await sleep(900);
  const me = await api(w, 'GET', '/api/me');
  check(w.__jar.has('kalmido_session') && me.username === 'bob' && me.via === 'passkey', 'passwordless login with the passkey: ' + JSON.stringify(me).slice(0, 80));
  w.close();
  // no WebAuthn: no passkey button, hint in the settings
  w = await page({passkeys: false}); d = w.document;
  check(!d.querySelector('[data-au="passkey"]') && !!d.querySelector('[data-au="oidc"]'), 'without WebAuthn: no passkey button');
  w.close();

  // ---- forced enrolment
  await fetch(B + 'api/admin/settings', {method: 'PATCH', headers: {...H, Cookie: ac}, body: JSON.stringify({twofa_required: true})});
  w = await page(); d = w.document;
  d.querySelector('#au-user').value = 'gwen'; d.querySelector('#au-pw').value = 'password123';
  submit(w, d.querySelector('#auth-form')); await sleep(700);
  check(/required on this server/.test(d.querySelector('.authscreen').textContent) && !!d.querySelector('[data-en="totp"]') && !!d.querySelector('[data-en="pk"]'), 'enrolment screen');
  click(w, d.querySelector('[data-en="totp"]')); await sleep(600);
  const gsec = d.querySelector('#totp-secret').textContent;
  d.querySelector('#totp-code').value = totp(gsec); submit(w, d.querySelector('#en-totp')); await sleep(700);
  check(d.querySelectorAll('.authscreen .rcodes code').length === 10 && w.__jar.has('kalmido_session'), 'enrolled: recovery codes + session');
  w.close();
  await fetch(B + 'api/admin/settings', {method: 'PATCH', headers: {...H, Cookie: ac}, body: JSON.stringify({twofa_required: false})});

  // ---- Settings > Users > Whole server: sign-in + backups
  w = await page({cookie: ac}); d = w.document;
  w.eval(`settingsModal('users')`); await sleep(900);
  md = d.querySelector('.smodal');
  check(!!md.querySelector('#s-2fareq') && !md.querySelector('#s-2fareq').checked && md.querySelector('#s-pklogin').checked, 'sign-in switches (2FA off, passkey login on)');
  check(md.querySelector('#s-oidcredir')?.textContent === 'https://kalmido.example/api/auth/oidc/callback' && /id\.example/.test(md.querySelector('#sp-users').textContent), 'OIDC block: provider + redirect URI');
  const cb = md.querySelector('#s-2fareq'); cb.checked = true; cb.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(700);
  check((await api(w, 'GET', '/api/about')).twofa_required === true, 'switch applied at once');
  cb.checked = false; cb.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(700);
  check(md.querySelector('#s-bk-h')?.textContent === 'Backups' && !md.querySelector('#bk-on').checked && md.querySelector('#bk-time').value === '03:30', 'backups section: off, 03:30');
  check(/No backups yet/.test(md.querySelector('#s-bk').textContent), 'no backups yet');
  const bon = md.querySelector('#bk-on'); bon.checked = true; bon.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(700);
  const bd = md.querySelector('#bk-daily'); bd.value = '7'; bd.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(700);
  let bj = await api(w, 'GET', '/api/admin/backups');
  check(bj.on && bj.keep_daily === 7, 'backup settings saved at once (1.5)');
  check(!md.querySelector('[data-bk="save"]') && /Backups/.test(w.eval('HIST.undo[HIST.undo.length - 1].label')), 'no Save button; history step');
  click(w, md.querySelector('[data-bk="now"]'));
  await until(() => md.querySelectorAll('.bkrow').length === 1, 8000);
  check(md.querySelectorAll('.bkrow').length === 1 && /manual/.test(md.querySelector('.bkrow').textContent), 'back up now: the list shows it');
  const dl = md.querySelector('.bkrow a[download]');
  check(dl && /^\/api\/admin\/backups\/kalmido-backup-\d{8}-\d{6}-manual\.zip\/download$/.test(dl.getAttribute('href')), 'download link');
  await api(w, 'POST', '/api/tasks', {title: 'made after the backup'});
  click(w, md.querySelector('.bkrow [data-bk="restore"]')); await sleep(300);
  const rm = d.querySelector('.bkrestore');
  check(!!rm && rm.querySelector('#bkr-go').disabled && /all data on this server/.test(rm.textContent), 'restore dialog: warning, button disabled');
  input(w, rm.querySelector('#bkr-word'), 'restore');
  check(rm.querySelector('#bkr-go').disabled, 'wrong word keeps it disabled');
  input(w, rm.querySelector('#bkr-word'), 'RESTORE');
  check(!rm.querySelector('#bkr-go').disabled, 'RESTORE enables it');
  submit(w, rm.querySelector('form')); await sleep(2500);
  const st = await api(w, 'GET', '/api/state');
  check(st.tasks && !st.tasks.some(t => t.title === 'made after the backup'), 'restored (the task made afterwards is gone), admin still logged in');
  w.close();

  // ---- German
  const cc = await login('alice');
  await fetch(B + 'api/settings', {method: 'PATCH', headers: {...H, Cookie: cc}, body: JSON.stringify({lang: 'de'})});
  w = await page({cookie: cc, lang: 'de'}); d = w.document;
  w.eval(`settingsModal('users')`); await sleep(900);
  md = d.querySelector('.smodal');
  check(md.querySelector('#s-bk-h')?.textContent === 'Backups' && /Automatische Backups/.test(md.querySelector('#s-bk').textContent)
    && /Zwei-Faktor-Anmeldung für die eingebaute Anmeldung vorschreiben/.test(md.textContent), 'German labels (users pane)');
  md.remove();
  w.eval(`settingsModal('account')`); await sleep(700);
  check(/Zwei-Faktor-Anmeldung/.test(d.querySelector('.smodal #s-2fa-h').textContent), 'German labels (account)');
  w.close();

  if (errs.length) console.log('JS ERRORS', [...new Set(errs)]);
  console.log(`\n${ok} ok, ${F.length} failed`);
  process.exit(F.length || errs.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
