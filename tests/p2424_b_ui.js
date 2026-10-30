// kalmido-suite: fresh
// 2.424.0 B (#3450) UI test, jsdom: receipts by e-mail in the office settings (area Data) of a person without an organisation.
// - the section "Receipts by e-mail" shows a button "Create address" while there is none; a press shows the address
// - the copy button puts exactly that address on the clipboard; the Gmail filter guide (three steps) sits folded below
// - 2.424.0 B2 (#3450, review): the guide filters by sender (from:), a new address says first that the documents address
//   and the letters' reply address of the area change too (cancel keeps it)
// - without the mail input on the server (no IMAP set up) the section is not there at all (separate container start)
// Own container (start.sh with the mail address of the server set).
// freelancer-matrix: office
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const FEATURES = 'cal,collab,comments,contacts,files,docs,clients,office';
const MAILENV = ' -e KALMIDO_MAIL_ADDRESS=tasks@example.test -e KALMIDO_IMAP_HOST=127.0.0.1 -e KALMIDO_IMAP_PORT=1143 -e KALMIDO_IMAP_SSL=0'
  + ' -e KALMIDO_IMAP_USER=kalmido -e KALMIDO_IMAP_PASSWORD=secret -e KALMIDO_IMAP_INTERVAL=600';
const start = extra => execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + extra}});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(200); } return fn(); };

async function setup() {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: 1});
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const FK = await login('frida');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: FEATURES}, FK);
  return FK;
}
async function openData() {
  const w = await boot({user: 'frida', hash: 'office/settings'}), d = w.document;
  await until(() => d.querySelector('#ofc-set [data-ostp="data"]'));
  w.eval(`ost_show('data')`);
  return [w, d];
}

(async () => {
  start(MAILENV);
  const FK = await setup();
  let [w, d] = await openData();
  const h = await until(() => d.querySelector('#rcm-h'));
  check(h && h.textContent === 'Receipts by e-mail', 'the section "Receipts by e-mail" in the area Data');
  check(h && h.closest('[data-ostp]')?.dataset.ostp === 'data', 'it sits in the area Data');
  const mk = d.querySelector('[data-rcm="make"]');
  check(mk && !d.querySelector('#rcm-addr'), 'no address yet: a button "Create address"');
  mk?.click();
  const code = await until(() => d.querySelector('#rcm-addr'));
  const addr = code ? code.textContent : '';
  check(/^tasks\+d[\w-]+@example\.test$/.test(addr), 'the address shows after the press: ' + addr);
  const api = await call('GET', '/api/office/receipt-mail', null, FK);
  check(api.address === addr && api.ws === 'private', 'the same address as the server says (personal office = private)');
  let copied = null;
  Object.defineProperty(w.navigator, 'clipboard', {configurable: true, value: {writeText: async t => { copied = t; }}});
  d.querySelector('[data-rcm="copy"]')?.click();
  await until(() => copied !== null);
  check(copied === addr, 'the copy button copies the address: ' + copied);
  const g = d.querySelector('details.rcm-gmail');
  check(g && !g.open && g.querySelectorAll('li').length === 3 && /Gmail/.test(g.querySelector('summary').textContent),
    'the Gmail guide: folded, three steps');
  check(d.querySelector('[data-rcm="renew"]'), 'a link for a new address');
  // 2.424.0 B2 (#3450, review): the guide filters by the invoice senders, not by subject words (spam says "Invoice" too)
  check(g && /from:\(stripe\.com/.test(g.textContent) && !/subject:/.test(g.textContent), 'the Gmail guide: a filter by sender (from:), not by subject');
  // 2.424.0 B2 (#3450, review): a new address asks first and says that the documents and the letters' reply address change too
  d.querySelector('[data-rcm="renew"]')?.click();
  const cb = await until(() => d.querySelector('#cdlg-b'));
  check(cb && /documents address and the reply address of letters/.test(cb.textContent), 'renew: the question says the documents and letter reply address change too: ' + (cb && cb.textContent));
  d.querySelector('[data-cd="no"]')?.click();
  await until(() => !d.querySelector('#cdlg-b'));
  check((await call('GET', '/api/office/receipt-mail', null, FK)).address === addr, 'cancelled: the address stays');
  w.close();
  check(!errs.length, 'no script errors: ' + errs.slice(0, 3).join(' | '));

  // ================= no mail input on the server: no section
  start('');
  await setup();
  [w, d] = await openData();
  await until(() => d.querySelector('#ofc-set [data-ostp="data"]:not([hidden])'));
  const r2 = await call('GET', '/api/office/receipt-mail', null, await login('frida'));
  check(r2.enabled === false && r2.address === '', 'the server without mail input: enabled false');
  check(await until(() => w.eval('!!(RCM.d && !RCM.loading)')), 'the section asked the server');
  check(!d.querySelector('#rcm-h'), 'and the office settings show no section');
  w.close();
  check(!errs.length, 'no script errors (2): ' + errs.slice(0, 3).join(' | '));
  console.log(`p2424_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
