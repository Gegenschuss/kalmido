// 2.141.0 part A UI test (#2141, #2138), own container (start.sh with the stub mail server inside: IMAP 1143, SMTP 1025),
// jsdom. The server has no mailbox of its own: alice's private space has its own (IMAP + SMTP of the stub).
// - #mailhub: the section "Mailbox" with the private space; its dialog shows the stored servers, the passwords only as
//   "unchanged"; "Check connection" shows both logins as working (2.166.0, #2633: fields save themselves)
// - the client's card: "New e-mail" (also when hubmailbox.js is loaded on demand); suggested recipients from the client
// - the reading view: "Reply" opens the writing dialog with the sender, "Re: ..." and the quote; Send = a toast, the sent
//   mail is filed in the list ("Sent"), the stub SMTP got it
// - an SMTP that fails: the dialog stays open with the error, the list shows "Not sent"
// freelancer-matrix: hub  (the person here is the instance admin in the own private space; the freelancer case of the same
// routes is p2141_a_api_test.py)
const fs = require('fs');
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const CT = process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test';
const ENV = '-e KALMIDO_IMAP_INTERVAL=600 -e KALMIDO_CALENDAR_ALLOW_HOSTS=127.0.0.1:1143,127.0.0.1:1025,127.0.0.1:1027';
if (!process.env.P2141A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' ' + ENV}});
fs.mkdirSync(path.join(DATA, 'mail', 'in'), {recursive: true});
fs.copyFileSync(path.join(__dirname, 'stub_mail.py'), path.join(DATA, 'stub_mail.py'));
execFileSync('docker', ['exec', '-d', CT, 'python', '/data/stub_mail.py']);
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return Array.isArray(j) ? j : {...j, status: r.status}; };
let NO = 0;
const mail = (from, subject, text) => {
  NO++;
  fs.writeFileSync(path.join(DATA, 'mail', 'in', `${NO}.eml`), `From: ${from}\r\nTo: office@example.test\r\nSubject: ${subject}\r\nMessage-ID: <p2141aui-${NO}@example.org>\r\n`
    + `Date: Tue, 20 Oct 2026 10:00:00 +0200\r\nMIME-Version: 1.0\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n${text}\r\n`);
};
const outbox = () => { try { return fs.readFileSync(path.join(DATA, 'mail', 'out.jsonl'), 'utf8').split('\n').filter(Boolean).map(x => JSON.parse(x)); } catch { return []; } };
const until = (fn, ms) => require('./boot').until(fn, {timeout: ms || 20000, step: 300});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
// 2.358.0 B (#3302): every wait of this suite up to 20 s (CI: 2 cores, many suites at once; a green run waits no longer)
const FEAT = 'collab,comments,clients,contacts';

(async () => {
  await sleep(800);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'all'});
  const ACME = (await call('POST', '/api/clients', {name: 'Acme', org_id: null, email: 'acme@example.com', contacts: [{name: 'Lisa', email: 'lisa@example.com'}]})).id;
  const box = await call('PUT', '/api/hubmail/mailbox', {ws: 'private', imap_host: '127.0.0.1', imap_port: 1143, imap_ssl: false, imap_user: 'kalmido', imap_password: 'secret',
    smtp_host: '127.0.0.1', smtp_port: 1025, smtp_tls: 'none', from_addr: 'office@example.test', from_name: 'Alice Office'});
  check(box.status === 200 && box.box?.imap_password_set, 'setup: the private mailbox ' + box.status);
  mail('Acme <acme@example.com>', 'Quarterly report', 'The numbers of the quarter.');
  await call('POST', '/api/hubmail/mailbox/poll', {ws: 'private'});
  const got = await until(async () => ((await call('GET', `/api/hubmail/mails?client_id=${ACME}`)).mails || []).length >= 1);
  check(got, 'setup: the mail was fetched and filed with Acme');

  // ---- #mailhub: the section "Mailbox" and its dialog
  let w = await boot({user: 'alice', hash: 'mailhub'}), d = w.document;
  const sp = await until(async () => d.querySelector('.hbmhub .hmbsp[data-hmbws="private"]'), 20000);
  check(sp && /office@example\.test/.test(sp.textContent), 'mailhub: the private space shows its mailbox address');
  click(w, sp && sp.querySelector('[data-hmba="edit"]'));
  let md = await until(async () => d.querySelector('.modal.hmbdlg'), 20000);
  check(md && md.querySelector('#hmb-ih').value === '127.0.0.1' && md.querySelector('#hmb-ip').value === '1143' && md.querySelector('#hmb-fa').value === 'office@example.test',
    'mailbox dialog: the stored servers');
  check(md && md.querySelector('#hmb-iw').value === '' && md.querySelector('#hmb-iw').getAttribute('placeholder') === 'unchanged' && md.querySelector('#hmb-iw').type === 'password',
    'mailbox dialog: the password only as "unchanged"');
  // 2.166.0 (#2633): a field saves itself when it is left; "Check connection" instead of "Save and check"
  if (md) { const fn = md.querySelector('#hmb-fn'); fn.value = 'Alice Office GbR'; fn.dispatchEvent(new w.Event('change', {bubbles: true})); }
  const fnOk = await until(async () => ((await call('GET', '/api/hubmail/mailbox?ws=private')).box || {}).from_name === 'Alice Office GbR', 20000);
  check(fnOk && !md.querySelector('[data-hmbd="save"]'), 'mailbox dialog: the sender name saved itself, no Save button');
  if (md) { const ih = md.querySelector('#hmb-iu'); ih.value = ''; ih.dispatchEvent(new w.Event('change', {bubbles: true})); }
  check(await until(async () => /Not saved yet/.test(md.querySelector('.hmb-err').textContent), 4000), 'an incomplete set is not saved, the reason shows');
  if (md) { const ih = md.querySelector('#hmb-iu'); ih.value = 'kalmido'; ih.dispatchEvent(new w.Event('change', {bubbles: true})); }
  await until(async () => !md.querySelector('.hmb-err').textContent, 4000);
  click(w, md && md.querySelector('[data-hmbd="check"]'));
  await until(async () => md.querySelectorAll('.hmbcheck .hmbok').length === 2, 20000);
  check(md && md.querySelectorAll('.hmbcheck .hmbok').length === 2, 'Check connection: receiving and sending work');
  check(outbox().length === 0, 'the check sends nothing');
  if (md) click(w, md.querySelector('[data-m="close"]'));
  await sleep(300);

  // ---- the client's card: New e-mail with suggested recipients
  w.eval(`go('client/${ACME}')`);
  const nb = await until(async () => d.querySelector('.hbmsec [data-hmbnew]'), 20000);
  check(nb, 'client card: "New e-mail"');
  click(w, nb);
  md = await until(async () => d.querySelector('.modal.hmbcdlg'), 20000);
  const sug = md ? [...md.querySelectorAll('[data-hmbto]')].map(b => b.dataset.hmbto) : [];
  check(sug.join() === 'acme@example.com,lisa@example.com', 'new mail: the client\'s addresses as suggestions ' + sug.join());
  click(w, md && md.querySelector('[data-hmbto="lisa@example.com"]'));
  check(md && md.querySelector('#hmb-to').value === 'lisa@example.com' && !md.querySelector('[data-hmbto="lisa@example.com"]'), 'a suggestion fills the recipient');
  if (md) { md.querySelector('#hmb-sub').value = 'Kickoff'; md.querySelector('#hmb-text').value = 'See you on Monday.'; }
  click(w, md && md.querySelector('[data-hmbc="send"]'));
  await until(async () => outbox().length === 1 && !d.querySelector('.modal.hmbcdlg'), 20000);
  check(outbox().length === 1 && outbox()[0].to.join() === 'lisa@example.com' && /Subject: Kickoff/.test(outbox()[0].raw), 'Send: the SMTP got the mail');
  check(!d.querySelector('.modal.hmbcdlg'), 'Send: the dialog closes');
  const sentRow = await until(async () => [...d.querySelectorAll('.hbmsec .hbmrow')].find(r => /Kickoff/.test(r.textContent)), 20000);
  check(sentRow && /Sent/.test(sentRow.querySelector('.hmbtag')?.textContent || '') && /lisa@example\.com/.test(sentRow.querySelector('.hbmfrom').textContent),
    'the sent mail is in the list: "Sent" and its recipient');

  // ---- Reply from the reading view
  click(w, [...d.querySelectorAll('.hbmsec .hbmopen')].find(b => /Quarterly report/.test(b.textContent)));
  md = await until(async () => d.querySelector('.modal.hbmdlg'), 20000);
  const rb = md && md.querySelector('[data-hmbreply]');
  check(rb, 'reading view: "Reply"');
  click(w, rb);
  md = await until(async () => d.querySelector('.modal.hmbcdlg'), 20000);
  check(!d.querySelector('.modal.hbmdlg'), 'Reply closes the reading view');
  check(md && md.querySelector('#hmb-to').value === 'acme@example.com' && md.querySelector('#hmb-sub').value === 'Re: Quarterly report'
    && /> The numbers of the quarter/.test(md.querySelector('#hmb-text').value), 'reply: recipient, Re: and the quote');
  check(md && /Alice Office/.test(md.querySelector('.hbmhdr')?.textContent || '') && /office@example\.test/.test(md.querySelector('.hbmhdr').textContent), 'reply: the sender of the mailbox');
  if (md) md.querySelector('#hmb-text').value = 'Thank you.' + md.querySelector('#hmb-text').value;
  click(w, md && md.querySelector('[data-hmbc="send"]'));
  await until(async () => outbox().length === 2, 20000);
  check(outbox().length === 2 && /In-Reply-To: <p2141aui-1@example\.org>/.test(outbox()[1].raw), 'reply sent with In-Reply-To');

  // ---- an SMTP that fails: the dialog stays with the error, the list shows "Not sent"
  await call('PUT', '/api/hubmail/mailbox', {ws: 'private', smtp_port: 1027});
  // 2.358.0 B (#3302): CI red "md is null" here: the reply's dialog is gone first, then the new one may take its compose
  // request (GET /api/hubmail/compose) longer than 6 s under CI load
  await until(async () => !d.querySelector('.modal.hmbcdlg'), 20000);
  click(w, d.querySelector('.hbmsec [data-hmbnew]'));
  md = await until(async () => d.querySelector('.modal.hmbcdlg'), 30000);
  check(md, 'a new e-mail opens its dialog');
  if (md) { md.querySelector('#hmb-to').value = 'acme@example.com'; md.querySelector('#hmb-sub').value = 'Will fail'; md.querySelector('#hmb-text').value = 'x'; }
  click(w, md && md.querySelector('[data-hmbc="send"]'));
  await until(async () => (md?.querySelector('.hmb-err')?.textContent || '').length > 0, 20000);
  check(md && md.isConnected && md.querySelector('.hmb-err')?.textContent.length > 0 && md.querySelector('#hmb-text').value === 'x', 'failure: the dialog stays with the error and the text');
  if (md) click(w, md.querySelector('[data-m="close"]'));
  const bad = await until(async () => [...d.querySelectorAll('.hbmsec .hbmrow')].find(r => /Will fail/.test(r.textContent) && r.querySelector('.hmbtag.bad')), 20000);
  check(bad && /Not sent/.test(bad.querySelector('.hmbtag.bad').textContent), 'the list shows "Not sent"');
  check(outbox().length === 2, 'nothing more went out');
  w.close();

  // ---- loaded on demand: the client's card draws "New e-mail" once hubmailbox.js arrived
  w = await boot({user: 'alice', hash: 'client/' + ACME, lazy: true}); d = w.document;
  check(await until(async () => d.querySelector('.hbmsec [data-hmbnew]'), 20000), 'on demand: "New e-mail" appears after the module loaded');
  w.close();

  check(errs.length === 0, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
