// 2.152.0 UI tests, part B (#2165 the trash period in the file store, #2172 the backup limits), own container (start.sh;
// P2103B_NOSTART=1: a running server). jsdom:
// - the file store's Trash names the period from the server ("deleted for good after 30 days"), the other spaces do not
// - Settings > Users > Backups: weekly at most 52 (input limit + the data protection note), the note that backups are not
//   encrypted while encryption is off, gone once it is on
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2103B_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'});

  // ================= #2165 the file store's trash names the period
  let w = await boot({user: 'alice', hash: 'ablage'}), d = w.document;
  await until(() => d.querySelector('#view .abview'));
  check(!d.querySelector('#view .abtrashdays'), 'My files: no trash note');
  (await until(() => d.querySelector('#side [data-absp="trash"]'))).click();  // 2.152.3 (#2621): a computer: the trash is in the panel
  const note = await until(() => d.querySelector('#view .abtrashdays'));
  check(note && /deleted for good after 30 days/.test(note.textContent), 'Trash: "deleted for good after 30 days" ' + (note?.textContent || ''));
  w.close();

  // ================= #2172 Settings > Users > Backups
  w = await boot({user: 'alice', hash: 'inbox'}); d = w.document;
  await w.eval(`settingsModal('users')`);
  let md = await until(() => d.querySelector('.smodal #bk-weekly') && d.querySelector('.smodal'), 60);
  check(md && md.querySelector('#bk-weekly').getAttribute('max') === '52', 'weekly: input limited to 52 ' + md?.querySelector('#bk-weekly')?.getAttribute('max'));
  check(md && /kept for at most 52 weeks \(data protection\)/.test(md.querySelector('#s-bk').textContent), 'the data protection note for weekly backups');
  check(md && md.querySelector('.bkencnote') && /not encrypted/.test(md.querySelector('.bkencnote').textContent), 'encryption off: the note that backups are not encrypted');
  w.close();
  await call('PATCH', '/api/admin/backups', {encrypt: true, passphrase: 'an invented passphrase'});
  w = await boot({user: 'alice', hash: 'inbox'}); d = w.document;
  await w.eval(`settingsModal('users')`);
  md = await until(() => d.querySelector('.smodal #bk-enc') && d.querySelector('.smodal'), 60);
  check(md && md.querySelector('#bk-enc').checked && !md.querySelector('.bkencnote'), 'encryption on: no note');
  w.close();

  console.log(`p2103_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
