// 2.84.0 part A UI test (#1198), own container (start.sh with the stub mailbox): e-mail as an input of the hub.
// - the client's card has the section "E-mails" (date, sender, subject, paper clip with the count), the search narrows it,
//   a tap opens the reading view (headers, plain text, the attachments)
// - the project page has the same section
// - the e-mail inbox (#mailhub, from Office > Clients): the own filing address, "Not assigned" with Assign (one undo step)
//   and Delete (one undo step)
const fs = require('fs');
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const CT = process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test';
const MAILENV = '-e KALMIDO_MAIL_ADDRESS=tasks@example.test -e KALMIDO_IMAP_HOST=127.0.0.1 -e KALMIDO_IMAP_PORT=1143 -e KALMIDO_IMAP_SSL=0 '
  + '-e KALMIDO_IMAP_USER=kalmido -e KALMIDO_IMAP_PASSWORD=secret -e KALMIDO_IMAP_INTERVAL=600';
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' ' + MAILENV}});
fs.mkdirSync(path.join(DATA, 'mail', 'in'), {recursive: true});
fs.copyFileSync(path.join(__dirname, 'stub_mail.py'), path.join(DATA, 'stub_mail.py'));
execFileSync('docker', ['exec', '-d', CT, 'python', '/data/stub_mail.py']);
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return Array.isArray(j) ? j : {...j, status: r.status}; };
let NO = 0;
const mail = (to, from, subject, text, att) => {
  NO++;
  const head = `From: ${from}\r\nTo: ${to}\r\nSubject: ${subject}\r\nMessage-ID: <ui-${NO}@example.com>\r\nDate: Fri, 16 Oct 2026 10:00:00 +0200\r\nMIME-Version: 1.0\r\n`;
  const raw = att ? head + `Content-Type: multipart/mixed; boundary="b1"\r\n\r\n--b1\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n${text}\r\n--b1\r\n`
    + `Content-Type: text/plain; name="${att}"\r\nContent-Disposition: attachment; filename="${att}"\r\n\r\nattached\r\n--b1--\r\n`
    : head + `Content-Type: text/plain; charset=utf-8\r\n\r\n${text}\r\n`;
  fs.writeFileSync(path.join(DATA, 'mail', 'in', `${NO}.eml`), raw);
};
const until = async (fn, ms = 20000) => { const t = Date.now(); while (Date.now() - t < ms) { const x = await fn(); if (x) return x; await sleep(400); } return fn(); };
const FEAT = 'collab,comments,clients,contacts';

(async () => {
  await sleep(800);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'all'});
  const ACME = (await call('POST', '/api/clients', {name: 'Acme', org_id: null, email: 'acme@example.com'})).id;
  const P = (await call('POST', '/api/lists', {name: 'Launch', kind: 'project'})).id;
  await call('PATCH', `/api/lists/${P}`, {client_id: ACME});
  const IN = (await call('POST', '/api/hubmail/address', {ws: 'private'})).address;
  const CA = (await call('POST', '/api/hubmail/address', {client_id: ACME})).address;
  const PA = (await call('POST', '/api/hubmail/address', {list_id: P})).address;
  check(IN && CA && PA, 'setup: the addresses ' + [IN, CA, PA].join(' '));
  mail(IN, 'Acme <acme@example.com>', 'Quarterly report', 'The numbers of the quarter.', 'numbers.txt');
  mail(IN, 'someone@example.org', 'Unsorted note', 'Nobody knows this sender.');
  mail(CA, 'boss@example.org', 'Kickoff agenda', 'Agenda for Monday.');
  mail(PA, 'boss@example.org', 'Launch plan', 'The plan of the launch.');
  await call('POST', '/api/admin/mail/poll', {});
  const got = await until(async () => ((await call('GET', `/api/hubmail/mails?client_id=${ACME}`)).mails || []).length >= 3);
  check(got, 'setup: the mails were filed');
  const un = (await call('GET', '/api/hubmail/inbox')).mails || [];
  check(un.length === 1 && un[0].subject === 'Unsorted note', 'setup: one mail not assigned ' + JSON.stringify(un.map(m => m.subject)));
  const UN = un[0]?.id;

  // ---- the client's card: list, paper clip, search, reading view
  let w = await boot({user: 'alice', hash: 'client/' + ACME}), d = w.document;
  await until(async () => d.querySelectorAll('.hbmsec .hbmrow').length >= 3, 6000);
  let rows = [...d.querySelectorAll('.hbmsec .hbmrow')];
  check(rows.length === 3, 'client card: three e-mails ' + rows.length);
  const rep = rows.find(r => /Quarterly report/.test(r.textContent));
  check(rep && rep.querySelector('.hbmclip') && /1/.test(rep.querySelector('.hbmclip').textContent) && /Acme/.test(rep.querySelector('.hbmfrom').textContent), 'row: sender, subject, paper clip with 1');
  check(rows.some(r => /Launch plan/.test(r.textContent) && /Launch/.test(r.querySelector('.hbmproj')?.textContent || '')), 'the project mail names its project');
  check(d.querySelector('.hbmsec [data-hbma="copy"]'), 'Copy address on the card');
  const q = d.querySelector('.hbmsec input[data-hbmq]');
  q.value = 'Kickoff'; q.dispatchEvent(new w.Event('input', {bubbles: true}));
  await until(async () => d.querySelectorAll('.hbmsec .hbmrow').length === 1, 5000);
  rows = [...d.querySelectorAll('.hbmsec .hbmrow')];
  check(rows.length === 1 && /Kickoff agenda/.test(rows[0].textContent), 'search: one hit');
  check(d.activeElement === q || d.querySelector('.hbmsec input[data-hbmq]') === q, 'search: the field stays (not drawn again)');
  q.value = ''; q.dispatchEvent(new w.Event('input', {bubbles: true}));
  await until(async () => d.querySelectorAll('.hbmsec .hbmrow').length === 3, 5000);
  click(w, [...d.querySelectorAll('.hbmsec .hbmopen')].find(b => /Quarterly report/.test(b.textContent)));
  const md = await until(async () => d.querySelector('.modal.hbmdlg'), 5000);
  check(md && /Quarterly report/.test(md.querySelector('h3').textContent) && /The numbers of the quarter/.test(md.querySelector('.hbmtext').textContent), 'reading view: subject and plain text');
  check(md && /acme@example\.com/.test(md.querySelector('.hbmhdr').textContent), 'reading view: the sender');
  check(md && [...md.querySelectorAll('.hbmatt a')].some(a => /numbers\.txt/.test(a.textContent) && /\/api\/hubmail\/mails\/\d+\/files\/\d+/.test(a.getAttribute('href'))), 'reading view: the attachment');
  check(md && md.querySelector('a[href^="#ablage/"]'), 'reading view: "Attachments in the file store"');
  if (md) click(w, md.querySelector('[data-m="close"]'));
  await sleep(300);

  // ---- the project page
  w.eval(`go('l/${P}')`); await sleep(300);
  w.eval(`povSet(listById(${P}), true); render()`);
  await until(async () => d.querySelector('#pov-mails .hbmrow'), 6000);
  const pr = [...d.querySelectorAll('#pov-mails .hbmrow')];
  check(pr.length === 1 && /Launch plan/.test(pr[0].textContent), 'project page: its e-mail ' + pr.length);

  // ---- the e-mail inbox: assign + undo, delete + undo
  w.eval(`go('clients')`); await sleep(500);
  check(d.querySelector('#view a[href="#mailhub"]'), 'Office > Clients: the entry "E-mail filing"');
  w.eval(`go('mailhub')`);
  await until(async () => d.querySelector('.hbmhub .hbmrow'), 6000);
  check(d.querySelector('.hbmhub .hbmsp') && d.querySelector('.hbmhub .hbmsp').textContent.includes(IN), 'inbox: my filing address');
  check(d.querySelectorAll('.hbmhub .hbmrow').length === 1, 'inbox: one mail not assigned');
  click(w, d.querySelector('.hbmhub [data-hbmasg]'));
  const am = await until(async () => d.querySelector('.modal.hbmadlg'), 5000);
  const pick = am && [...am.querySelectorAll('[data-hbmt]')].find(b => b.dataset.hbmt === `client:${ACME}`);
  check(pick, 'assign: Acme to pick');
  if (pick) click(w, pick);
  await until(async () => (await call('GET', `/api/hubmail/mails/${UN}`)).client_id === ACME, 5000);
  check((await call('GET', `/api/hubmail/mails/${UN}`)).client_id === ACME, 'assign: filed with Acme');
  await until(async () => !d.querySelector('.hbmhub .hbmrow'), 5000);
  check(!d.querySelector('.hbmhub .hbmrow'), 'inbox: empty after assigning');
  await w.eval(`histStep('undo')`);
  await until(async () => (await call('GET', `/api/hubmail/mails/${UN}`)).client_id === null, 15000);  // 2.308.0 (#3259)
  check((await call('GET', `/api/hubmail/mails/${UN}`)).client_id === null, 'undo: back to Not assigned (one step)');
  await until(async () => d.querySelector('.hbmhub .hbmrow'), 5000);
  check(d.querySelectorAll('.hbmhub .hbmrow').length === 1, 'inbox: the mail is back');
  click(w, d.querySelector('.hbmhub [data-hbmdel]'));
  await until(async () => (await call('GET', `/api/hubmail/mails/${UN}`)).status === 404, 5000);
  check((await call('GET', `/api/hubmail/mails/${UN}`)).status === 404, 'delete: gone');
  await w.eval(`histStep('undo')`);
  // 2.308.0 (#3259): wait for the restored mail instead of a fixed 800 ms
  await until(async () => (await call('GET', `/api/hubmail/mails/${UN}`)).subject === 'Unsorted note', 15000);
  check((await call('GET', `/api/hubmail/mails/${UN}`)).subject === 'Unsorted note', 'undo: restored (one step)');

  check(errs.length === 0, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
