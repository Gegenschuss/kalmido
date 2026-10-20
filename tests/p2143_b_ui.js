// 2.143.0 part B UI test (#2152, #2211), own container (start.sh).
//  - Settings > Users > Whole server: the section "Off-site backup" below the backups: the target type switches the fields
//    (S3 / WebDAV / SFTP), credential fields stay empty and only say "set (unchanged)" (the value is never in the page), a typed
//    password is saved on change and the field is empty again, SFTP shows the public key with a copy button and "New key pair"
//  - knowledge pages: the space menu offers "Trash"; the dialog lists the trashed page with its file count, "Restore" brings a
//    page back, "Delete permanently…" (after the confirmation) removes it on the server, "Empty trash" shows only with pages
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2143B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const change = (w, el, v) => { if (v !== undefined) el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const SECRET = 'ui-test-secret-value-42', DAVPW = 'ui-test-dav-password-17';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments', 'collab']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,wiki'});
  check((await call('PATCH', '/api/admin/backups', {encrypt: true, passphrase: 'a long backup passphrase'})).status === 200, 'setup: encrypted backups');
  const s3 = await call('PATCH', '/api/admin/backups/offsite', {type: 's3', s3: {endpoint: 'https://s3.example.com', bucket: 'kbk', key: 'AKUITEST', secret: SECRET}});
  check(s3.status === 200 && s3.s3?.secret_set, 'setup: an S3 target with credentials');

  // ---- the off-site section
  let w = await boot({user: 'alice', hash: 'today'}), d = w.document;
  w.eval(`settingsModal('users')`); await sleep(900);
  const md = d.querySelector('.smodal');
  const box = await until(() => md?.querySelector('#s-bko #bko-type') && md.querySelector('#s-bko'));
  check(md?.querySelector('#s-bko-h')?.textContent === 'Off-site backup', 'the heading "Off-site backup" below the backups');
  check(box && box.querySelector('#bko-type').value === 's3' && box.querySelector('#bko-s3-endpoint')?.value === 'https://s3.example.com', 'S3 chosen, its endpoint shown');
  const sk = box?.querySelector('#bko-s3-secret');
  check(sk && sk.type === 'password' && sk.value === '' && sk.placeholder === 'set (unchanged)', 'the secret field is empty, it only says "set (unchanged)"');
  check(!md.innerHTML.includes(SECRET) && !md.innerHTML.includes('AKUITEST'), 'no credential anywhere in the page');
  check(!box.querySelector('#bko-on').disabled, 'the switch is usable with encrypted backups');
  check(!!box.querySelector('[data-bko="test"]') && !!box.querySelector('#bko-keep'), 'Test connection and the count to keep');
  change(w, box.querySelector('#bko-type'), 'webdav');
  check(await until(async () => (await call('GET', '/api/admin/backups/offsite')).type === 'webdav'), 'the type change is saved at once');
  await until(() => md.querySelector('#bko-webdav-url'));
  check(!!md.querySelector('#bko-webdav-url') && !md.querySelector('#bko-s3-endpoint'), 'WebDAV fields replace the S3 fields');
  change(w, md.querySelector('#bko-webdav-url'), 'https://dav.example.com/backups');
  await sleep(400);
  change(w, md.querySelector('#bko-webdav-password'), DAVPW);
  const st = await until(async () => { const j = await call('GET', '/api/admin/backups/offsite'); return j.webdav?.password_set && j.webdav.url === 'https://dav.example.com/backups' && j; });
  check(!!st, 'address and password saved on change');
  const pw = await until(() => md.querySelector('#bko-webdav-password')?.placeholder === 'set (unchanged)' && md.querySelector('#bko-webdav-password'));
  check(pw && pw.value === '' && !md.innerHTML.includes(DAVPW), 'after saving the password field is empty again, "set (unchanged)"');
  change(w, md.querySelector('#bko-type'), 'sftp');
  const pub = await until(() => md.querySelector('#bko-pub')?.value?.startsWith('ssh-ed25519 ') && md.querySelector('#bko-pub'));
  check(!!pub && pub.readOnly, 'SFTP: the public key (read only) to copy');
  check(!!md.querySelector('[data-bko="copy"]') && !!md.querySelector('[data-bko="newkey"]') && !!md.querySelector('#bko-sftp-host'), 'SFTP: copy, new key pair, server field');
  check(!/PRIVATE KEY/.test(md.innerHTML), 'SFTP: the private key is never in the page');
  check(!!md.querySelector('[data-bko="remove"]'), 'review: "Remove target" offered');  // 2.143.0 B (#2152, review)
  w.close();

  // ---- knowledge pages: the trash
  const P1 = await call('POST', '/api/wiki/pages', {space: 'private', path: 'Old notes', body: 'x'});
  const P2 = await call('POST', '/api/wiki/pages', {space: 'private', path: 'Keep notes', body: 'y'});
  await call('DELETE', `/api/wiki/pages/${P1.id}`); await call('DELETE', `/api/wiki/pages/${P2.id}`);
  w = await boot({user: 'alice', hash: 'wiki'}); d = w.document; await sleep(500);
  w.confirm = () => true;
  check(w.eval(`w299_areaItems().some(x => x.label === 'Trash')`), 'the space menu offers "Trash"');
  w.eval(`wk_trashDlg('private')`);
  const dlg = await until(() => d.querySelectorAll('.wktrashdlg .wktrow').length === 2 && d.querySelector('.wktrashdlg'));
  check(!!dlg, 'the dialog lists both trashed pages');
  check(dlg && /Old notes/.test(dlg.textContent) && /deleted for good after 30 days/.test(dlg.textContent), 'page name and the period');
  check(dlg && !dlg.querySelector('[data-wkt="empty"]').classList.contains('hidden'), '"Empty trash" shows with pages');
  click(w, dlg.querySelector(`[data-wktid="${P2.id}"] [data-wkt="restore"]`));
  check(await until(() => d.querySelectorAll('.wktrashdlg .wktrow').length === 1), 'Restore: the row leaves the list');
  check((await call('GET', `/api/wiki/pages/${P2.id}`)).status === 200, 'Restore: the page is back');
  click(w, dlg.querySelector(`[data-wktid="${P1.id}"] [data-wkt="purge"]`));
  check(await until(() => d.querySelectorAll('.wktrashdlg .wktrow').length === 0), 'Delete permanently: the row leaves the list');
  check(((await call('GET', '/api/wiki/trash?space=private')).pages || []).length === 0, 'Delete permanently: gone on the server');
  check(dlg.querySelector('[data-wkt="empty"]').classList.contains('hidden') && /Trash is empty/.test(dlg.textContent), 'empty: the button hides, "Trash is empty."');
  check(!errs.length, 'jsdom: no JS errors ' + errs.join(' | '));
  w.close();
  console.log(`p2143_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
