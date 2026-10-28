// 2.42.0 UI tests, part A (end-to-end encryption in the browser), own container (start.sh), jsdom with Node's WebCrypto:
// - set up (passphrase twice, at least 10 characters; the recovery code dialog closes only after "I have written it
//   down"); the server gets the public key and two wrapped bundles, never the passphrase / code / private key
// - #828 the encrypted note: written in the task detail -> the server holds only ciphertext -> a new page is locked ->
//   a wrong passphrase is refused -> the right one shows the text again
// - #828 an encrypted file: encrypted in the browser (KENC), the server blob holds nothing of the file, the uploader
//   decrypts it to the original name and bytes
// - reset with the recovery code (new passphrase), the note stays readable
// - #909 an encrypted DM between two people: on through the lock in the DM head, the message travels as ciphertext and is
//   read on the other side, the answer back too; both see the same safety number
const path = require('path');
const {webcrypto} = require('crypto');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2420A_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = (fn, n, ms = 150) => require('./boot').until(fn, {timeout: n ? n * ms : 15000, step: ms});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const FEAT = 'comments,collab';
const PASS = 'correct horse battery', PASS2 = 'another long passphrase';
const setup = w => {
  Object.defineProperty(w, 'crypto', {configurable: true, value: webcrypto});
  w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  w.__blobs = [];
  w.URL.createObjectURL = b => { w.__blobs.push(b); return 'blob:test'; }; w.URL.revokeObjectURL = () => {};
};
const type = (w, el, v) => { el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Baker', password: 'password123'})).id;
  const CKB = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, CKB);
  const L = (await call('POST', '/api/lists', {name: 'Office'})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: BOB, role: 'edit'});
  const T = (await call('POST', '/api/tasks', {title: 'Lease contract', list_id: L})).id;

  // ================= set up
  let w = await boot({setup}), d = w.document;
  check(!!w.crypto?.subtle && typeof w.eval('e2eSetupDlg') === 'function', 'set-up: WebCrypto + e2e.js loaded');
  w.eval('window.__setup = e2eSetupDlg()');
  let md = await until(() => d.querySelector('.e2edlg #e2e-p1') && d.querySelector('.e2edlg'));
  type(w, d.querySelector('#e2e-p1'), 'short'); type(w, d.querySelector('#e2e-p2'), 'short');
  md.querySelector('form').dispatchEvent(new w.Event('submit', {cancelable: true}));
  await sleep(50);
  check(/At least 10/.test(d.querySelector('#e2e-err').textContent), 'set-up: at least 10 characters ' + d.querySelector('#e2e-err').textContent);
  type(w, d.querySelector('#e2e-p1'), PASS); type(w, d.querySelector('#e2e-p2'), PASS + 'x');
  md.querySelector('form').dispatchEvent(new w.Event('submit', {cancelable: true}));
  await sleep(50);
  check(/differ/.test(d.querySelector('#e2e-err').textContent), 'set-up: both passphrases must match');
  type(w, d.querySelector('#e2e-p2'), PASS);
  md.querySelector('form').dispatchEvent(new w.Event('submit', {cancelable: true}));
  const cd = await until(() => d.querySelector('#e2e-code'), 100);
  const CODE = cd?.textContent || '';
  check(/^([A-Z2-7]{4}-){7}[A-Z2-7]{4}$/.test(CODE), 'set-up: a recovery code in 8 groups ' + CODE);
  const done = d.querySelector('.e2edlg [data-m="done"]');
  check(done?.disabled, 'set-up: Done only after the tick');
  const nb = d.querySelector('#e2e-noted'); nb.checked = true; nb.dispatchEvent(new w.Event('change', {bubbles: true})); done.click();
  await until(() => !d.querySelector('#e2e-code'));
  check(await w.eval('window.__setup') === true && w.eval('e2eUnlocked()'), 'set-up: done and unlocked');
  const keys = await call('GET', '/api/e2e/keys');
  const kj = JSON.stringify(keys);
  check(keys.set && keys.pub.kty === 'EC' && !('d' in keys.pub) && keys.bundle_pass.iter === 600000 && keys.bundle_rec.kdf === 'hkdf-sha256', 'set-up: public key + two wrapped bundles on the server');
  check(!kj.includes(PASS) && !kj.includes(CODE.replace(/-/g, '')) && !kj.includes('"d"'), 'set-up: no passphrase, code or private key on the server');

  // ================= #828 the encrypted note
  w.eval(`openDetail(${T})`);
  let b = await until(() => d.querySelector('#d-enc [data-e2e="note-new"]'));
  check(!!b, 'note: "Encrypted note" in the task detail');
  b.click();
  const ta = await until(() => d.querySelector('#d-enc-in'));
  const SECRET = 'Key safe code 4711, behind the painting';
  type(w, ta, SECRET);
  ta.dispatchEvent(new w.FocusEvent('focusout', {bubbles: true}));
  const srv = await until(async () => { const x = await call('GET', `/api/tasks/${T}/enc-note`); return x.status === 200 && x; });
  check(srv && srv.body.v === 1 && srv.body.ct && !JSON.stringify(srv).includes('4711'), 'note: the server holds only the ciphertext');
  const st = await call('GET', '/api/state');
  check(st.tasks.find(t => t.id === T)?.encrypted_note_mine === true && !JSON.stringify(st).includes('4711'), 'note: the state says encrypted_note, no text');
  const stB = await call('GET', '/api/state', null, CKB);
  check(stB.tasks.find(t => t.id === T)?.encrypted_note === true && !stB.tasks.find(t => t.id === T)?.encrypted_note_mine, 'note: Bob only learns that there is one');
  w.close();
  // a new page: locked
  w = await boot({setup}); d = w.document;
  w.eval(`openDetail(${T})`);
  b = await until(() => d.querySelector('#d-enc [data-e2e="note-unlock"]'));
  check(!!b && !d.querySelector('#d-enc-in'), 'note: locked after a reload (Unlock instead of the text)');
  b.click();
  md = await until(() => d.querySelector('#e2e-pw') && d.querySelector('.e2edlg'));
  type(w, d.querySelector('#e2e-pw'), 'wrong passphrase!');
  md.querySelector('form').dispatchEvent(new w.Event('submit', {cancelable: true}));
  await until(() => /Wrong passphrase/.test(d.querySelector('#e2e-err')?.textContent || ''), 80);
  check(/Wrong passphrase/.test(d.querySelector('#e2e-err')?.textContent || '') && !w.eval('e2eUnlocked()'), 'note: a wrong passphrase is refused');
  type(w, d.querySelector('#e2e-pw'), PASS);
  md.querySelector('form').dispatchEvent(new w.Event('submit', {cancelable: true}));
  const ta2 = await until(() => d.querySelector('#d-enc-in')?.value === SECRET && d.querySelector('#d-enc-in'), 100);
  check(!!ta2, 'note: unlocked, the text is back ' + (d.querySelector('#d-enc')?.textContent || '').slice(0, 120));

  // ================= #828 an encrypted file
  const PDF = '%PDF-1.4 rental agreement of Max Mustermann, IBAN DE89370400440532013000';
  w.__f = new w.File([PDF], 'agreement.pdf', {type: 'application/pdf'});
  await w.eval(`e2eUpload(${T}, [window.__f])`);
  const att = await until(() => (w.eval(`taskById(${T})`)?.attachments || []).find(a => a.enc));
  check(att && att.enc_mine && !/agreement/.test(att.name), 'file: an encrypted file in the task ' + JSON.stringify(att));
  const tile = await until(() => d.querySelector(`#detail .e2eatt [data-att="${att?.id}"]`));
  check(!!tile, 'file: a lock tile in the attachments');
  const blob = Buffer.from(await (await fetch(B + `api/attachments/${att.id}`, {headers: {Cookie: CK}})).arrayBuffer());
  check(blob.slice(0, 5).toString('latin1') === 'KENC\x01' && !blob.includes('Mustermann') && !blob.includes('agreement'), 'file: the server blob is opaque');
  tile.click();
  const got = await until(() => w.__blobs.length && w.__blobs[0]);
  const txt = got ? Buffer.from(await got.arrayBuffer()).toString() : '';
  check(txt === PDF && got.type === 'application/pdf', 'file: decrypted to the original bytes and type');
  w.__enc = blob;
  const dec = await w.eval(`e2eFileDecrypt(new Uint8Array(window.__enc).buffer, ${T}).then(f => f.name)`);
  check(dec === 'agreement.pdf', 'file: the original name from the encrypted header');
  const r2 = await fetch(B + `api/attachments/${att.id}`, {headers: {Cookie: CKB}});
  check(r2.status === 404, 'file: Bob cannot download it');
  w.close();

  // ================= reset with the recovery code
  w = await boot({setup}); d = w.document;
  await w.eval('e2eLoad()');
  w.eval('window.__r = e2eResetDlg()');
  md = await until(() => d.querySelector('#e2e-code-in') && d.querySelector('.e2edlg'));
  type(w, d.querySelector('#e2e-code-in'), CODE.toLowerCase().replace(/-/g, ' '));
  type(w, d.querySelector('#e2e-p1'), PASS2); type(w, d.querySelector('#e2e-p2'), PASS2);
  md.querySelector('form').dispatchEvent(new w.Event('submit', {cancelable: true}));
  // 2.42.0 (#828 review): replacing the stored bundle asks for the account password
  const pp = await until(() => d.querySelector('.pwprompt'), 80);
  check(!!pp, 'reset: the account password is asked before the keys are replaced');
  if (pp) { pp.querySelector('#pp-pw').value = 'password123'; pp.querySelector('form').dispatchEvent(new w.Event('submit', {cancelable: true})); }
  check(await w.eval('window.__r') === true && w.eval('e2eUnlocked()'), 'reset: the recovery code sets a new passphrase');
  const k2 = await call('GET', '/api/e2e/keys');
  check(k2.pub.x === keys.pub.x && k2.bundle_pass.ct !== keys.bundle_pass.ct && k2.bundle_rec.ct === keys.bundle_rec.ct, 'reset: same key pair, new passphrase bundle');
  w.close();
  w = await boot({setup}); d = w.document;
  await w.eval('e2eLoad()');
  const okOld = await w.eval(`e2eUnwrapPass(E2E.st.bundle_pass, ${JSON.stringify(PASS)}).then(() => true, () => false)`);
  const okNew = await w.eval(`e2eUnwrapPass(E2E.st.bundle_pass, ${JSON.stringify(PASS2)}).then(async b => { await e2eAdopt(b); return true; }, () => false)`);
  check(!okOld && okNew, 'reset: the old passphrase no longer works, the new one does');
  w.eval(`openDetail(${T})`);
  check(!!await until(() => d.querySelector('#d-enc-in')?.value === SECRET), 'reset: the note is still readable');
  w.close();

  // ================= #909 encrypted DM
  const wb = await boot({user: 'bob', setup}), db = wb.document;
  const codeB = await wb.eval(`e2eCreate(${JSON.stringify('bob has a long passphrase')})`);
  check(/-/.test(codeB) && wb.eval('e2eUnlocked()'), 'dm: Bob set up');
  w = await boot({setup}); d = w.document;
  await w.eval(`e2eLoad().then(() => e2eUnwrapPass(E2E.st.bundle_pass, ${JSON.stringify(PASS2)})).then(e2eAdopt)`);
  const room = await call('POST', '/api/team/dm', {user_id: BOB});
  w.eval(`loadTeam().then(() => go('team/${room.id}'))`);
  b = await until(() => d.querySelector('.tcrhead [data-e2e="dm-toggle"]'));
  check(!!b && b.getAttribute('aria-pressed') === 'false', 'dm: a lock in the DM head');
  b.click();
  await until(() => d.querySelector('.tcrhead [data-e2e="dm-toggle"][aria-pressed="true"]'), 80);
  const rm = await call('GET', `/api/team/rooms/${room.id}/messages`);
  check(rm.room.e2e === true && rm.messages.some(m => m.enc?.sys === 'on'), 'dm: switched on (with a notice)');
  check(!!d.querySelector('#tc-msgs .cmsg.sys .e2esys'), 'dm: the notice in the conversation');
  const MSG = 'The door code is 2468';
  const inp = d.querySelector('#tc-in'); inp.value = MSG;
  await w.eval('tcSend()');
  const sent = await until(async () => { const x = await call('GET', `/api/team/rooms/${room.id}/messages`); return x.messages.find(m => m.enc && !m.enc.sys) && x; });
  const em = sent && sent.messages.find(m => m.enc && !m.enc.sys);
  check(em && em.body === '' && !JSON.stringify(sent).includes('2468'), 'dm: the server has only ciphertext');
  check([...d.querySelectorAll('#tc-msgs .cbub')].some(x => x.textContent.includes(MSG)), 'dm: my message shows in plain text for me');
  wb.eval(`loadTeam().then(() => go('team/${room.id}'))`);
  const seen = await until(() => [...db.querySelectorAll('#tc-msgs .cbub')].some(x => x.textContent.includes(MSG)), 100);
  check(seen, 'dm: Bob reads it decrypted ' + (db.querySelector('#tc-msgs')?.textContent || '').slice(0, 200));
  db.querySelector('#tc-in').value = 'Thanks, noted';
  await wb.eval('tcSend()');
  w.eval(`loadRoom(${room.id}).then(() => tcPatch())`);
  check(await until(() => [...d.querySelectorAll('#tc-msgs .cbub')].some(x => x.textContent.includes('Thanks, noted')), 100), 'dm: the answer back, decrypted for Alice');
  const pubA = JSON.stringify((await call('GET', '/api/e2e/keys')).pub), pubB = JSON.stringify((await call('GET', '/api/e2e/keys', null, CKB)).pub);
  const sa = await w.eval(`e2eSafety(${pubA}, ${pubB})`), sb = await wb.eval(`e2eSafety(${pubB}, ${pubA})`);
  check(/^(\d{5} ){7}\d{5}$/.test(sa) && sa === sb, 'dm: the same safety number on both sides ' + sa + ' / ' + sb);
  // a plain message is refused by the server in this room
  const pl = await call('POST', `/api/team/rooms/${room.id}/messages`, {body: 'plain'});
  check(pl.status === 409, 'dm: plain text refused in the encrypted DM');
  // 2.42.0 (#909 review): my own key in the safety number comes from my unlocked bundle; a swapped copy on the server is noticed
  const pA = JSON.parse(pubA);
  check(w.eval('E2E.own && E2E.own.x') === pA.x && w.eval('E2E.own.y') === pA.y && w.eval('E2E.badPub') === false, 'dm: own key from the bundle = the server copy');
  w.eval(`E2E.st.pub = ${pubB}; e2eOwnSet(E2E.own)`);
  check(w.eval('E2E.badPub') === true, 'dm: a swapped own key on the server is noticed');
  check(await w.eval(`e2eDmEncrypt(${room.id}, 'x').then(() => false, e => /does not match/.test(e.message))`), 'dm: no encryption with a swapped own key');
  w.eval('renderView()');
  check(!!d.querySelector('.e2ewarn'), 'dm: a clear warning in the conversation');
  w.eval(`E2E.st.pub = ${pubA}; e2eOwnSet(E2E.own); renderView()`);
  check(w.eval('E2E.badPub') === false, 'dm: matching again');
  // 2.42.0 (#909 review): the server reports the DM as plain without a "switched off" notice -> warning, plain only after a yes
  check(w.eval(`LS.get('e2eOn:' + S.me.id + ':${room.id}', null)`) !== null, 'dm: this browser remembers the encrypted DM');
  // CI of 2.318.0: the change poll held - a poll's loadRoom took e2e back from the server, the text went out encrypted unasked
  await until(() => w.eval('td_polling ? false : (td_polling = true)'), 80);
  await sleep(1500);  // a room load of the last poll lands first
  w.eval(`S.tc.room.e2e = false; e2eRoomDecrypt(${room.id}); renderView()`);
  check(w.eval(`!!E2E.down[${room.id}]`) && !!d.querySelector('.e2ewarn [data-e2e="dm-down-ok"]'), 'dm: a silent downgrade shows a warning');
  const n0 = (await call('GET', `/api/team/rooms/${room.id}/messages`)).messages.length;
  d.querySelector('#tc-in').value = 'would be plain';
  w.eval('window.__snd = tcSend()');
  const ask = await until(() => [...d.querySelectorAll('.modal')].find(x => /Send without encryption/.test(x.textContent)), 60);
  if (ask) ask.querySelector('[data-cd="no"]').click();
  await w.eval('window.__snd');
  const n1 = (await call('GET', `/api/team/rooms/${room.id}/messages`)).messages.length;
  check(!!ask && n1 === n0, 'dm: asked first, nothing sent without the confirmation');
  w.eval('td_polling = false');
  // switched off by a person (notice in the conversation): no warning, the marker goes
  const off = await call('POST', `/api/team/rooms/${room.id}/e2e`, {on: false}, CKB);
  await w.eval(`loadRoom(${room.id})`);
  check(off.status < 300 && w.eval(`!E2E.down[${room.id}]`) && w.eval(`LS.get('e2eOn:' + S.me.id + ':${room.id}', null)`) === null, 'dm: switched off by Bob -> no warning');
  w.close(); wb.close();

  console.log(`p2420_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e && e.stack); process.exit(1); });
