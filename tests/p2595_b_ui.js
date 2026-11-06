// kalmido-suite: fresh
// 2.595.0 part B (#4906): "Send by e-mail" right after typing the recipient's address: the unsaved draft (LT.pend, saved 1.5 s
// after the last key) is saved first, so the dialog's Recipient is filled; the server has the address afterwards too.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2595B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const until = (fn) => require('./boot').until(fn, {timeout: 30000, step: 200});

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: 'clients,office,docs', workspace: 'private'});
  const L = await call('POST', '/api/office/letters', {rcpt_name: 'Example GmbH', subject: 'Test'});
  check(L.http === 201, 'setup: a draft letter ' + L.http);
  const w = await boot({user: 'alice', hash: 'office/letters/' + L.id}), d = w.document;
  check(await until(() => d.querySelector('#lt-rcpt_email')), 'the letter editor shows the E-mail field');
  const inp = d.querySelector('#lt-rcpt_email');
  inp.value = 'kunde@example.com';
  inp.dispatchEvent(new w.Event('input', {bubbles: true}));
  w.eval(`ltmMailModal(${L.id})`);  // at once: well inside the 1.5 s delay of ltSaveSoon
  check(await until(() => d.querySelector('.modal #ltm-to')), 'the mail dialog opens');
  check(await until(() => d.querySelector('.modal #ltm-to').value === 'kunde@example.com'), 'the recipient is filled from the new address: ' + d.querySelector('.modal #ltm-to')?.value);
  const srv = await call('GET', '/api/office/letters/' + L.id + '/mail-draft');
  check(srv.to === 'kunde@example.com', 'the server has the address already (saved before the dialog): ' + srv.to);
  console.log(`p2595_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERROR', e); process.exit(1); });
