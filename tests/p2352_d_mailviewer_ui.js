// 2.352.0 D UI test (#2754), own container (start.sh with the stub mailbox): the reading view of a filed mail is shortened by default
// - a forwarded mail opens SHORT: the frame asks with ?short=1, the switch "Whole mail" is there and off; Text shows the one-line
//   header + content only (no signature); "Whole mail" on = the frame without ?short and the whole text; off again = short
// - a plain mail: no "Whole mail" switch (nothing to shorten), the frame without ?short
// - the window is large: the stylesheet gives the card min(56rem, 80vw) of the full height (jsdom has no layout, so the rule is read)
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
if (process.env.P2352D_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' ' + MAILENV}});
fs.mkdirSync(path.join(DATA, 'mail', 'in'), {recursive: true});
fs.copyFileSync(path.join(__dirname, 'stub_mail.py'), path.join(DATA, 'stub_mail.py'));
execFileSync('docker', ['exec', '-d', CT, 'python', '/data/stub_mail.py']);
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return Array.isArray(j) ? j : {...j, status: r.status}; };
let NO = 0;
const mail = (to, from, subject, text, html) => {
  NO++;
  const head = `From: ${from}\r\nTo: ${to}\r\nSubject: ${subject}\r\nMessage-ID: <ui2352d-${NO}@example.test>\r\nDate: Tue, 20 Oct 2026 10:00:00 +0200\r\nMIME-Version: 1.0\r\n`;
  const raw = html ? head + `Content-Type: multipart/alternative; boundary="b1"\r\n\r\n--b1\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n${text}\r\n--b1\r\n`
    + `Content-Type: text/html; charset=utf-8\r\n\r\n${html}\r\n--b1--\r\n`
    : head + `Content-Type: text/plain; charset=utf-8\r\n\r\n${text}\r\n`;
  fs.writeFileSync(path.join(DATA, 'mail', 'in', `${NO}.eml`), raw);
};
const until = async (fn, ms = 20000) => { const t = Date.now(); while (Date.now() - t < ms) { const x = await fn(); if (x) return x; await sleep(400); } return fn(); };
const FEAT = 'cal,collab,comments,clients,contacts,events';

(async () => {
  await sleep(800);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'all'});
  const IN = (await call('POST', '/api/hubmail/address', {ws: 'private'})).address;
  check(IN, 'setup: filing address');
  const HTML = '<html><body><div>Hi team, see below.</div><div><br><blockquote type="cite"><div>Begin forwarded message:</div><br><div><span><b>From: </b></span><span>Erika Muster &lt;erika@example.com&gt;</span></div><div><span><b>Subject: </b></span><span>Offer</span></div><div><span><b>Date: </b></span><span>12 October 2026</span></div><br><div>The real content of the offer.</div><div class="gmail_signature">Signature of Erika</div></blockquote></div></body></html>';
  mail(IN, 'Moe <moe@example.test>', 'Fwd: Offer', 'Hi team, see below.\n\nBegin forwarded message:\n\nFrom: Erika Muster <erika@example.com>\nSubject: Offer\nDate: 12 October 2026\n\nThe real content of the offer.\n\nKind regards\nErika', HTML);
  mail(IN, 'Pat <pat@example.test>', 'Plain note', 'Only plain text here.', '<p>Only plain text here.</p>');
  await call('POST', '/api/admin/mail/poll', {});
  const got = await until(async () => ((await call('GET', '/api/hubmail/inbox')).mails || []).length >= 2);
  check(got, 'setup: the mails were filed');
  const ms = (await call('GET', '/api/hubmail/inbox')).mails || [];
  const FW = ms.find(m => m.subject === 'Fwd: Offer')?.id, PL = ms.find(m => m.subject === 'Plain note')?.id;

  let w = await boot({user: 'alice', hash: 'mailhub'}), d = w.document;
  await until(async () => d.querySelectorAll('.hbmhub .hbmrow').length >= 2, 6000);
  const openMail = async id => { click(w, d.querySelector(`.hbmhub [data-hbmopen="${id}"]`)); return until(async () => d.querySelector('.modal.hbmdlg'), 5000); };

  let md = await openMail(FW);
  const fr = md && md.querySelector('iframe.hbmframe');
  check(fr && fr.getAttribute('src') === `/api/hubmail/mails/${FW}/html?short=1`, 'forwarded mail: the frame asks short ' + (fr && fr.getAttribute('src')));
  const wh = md && md.querySelector('input[data-hbmv="whole"]');
  check(wh && !wh.checked && /Whole mail/.test(md.querySelector('.hbmwhole')?.textContent || ''), 'the switch Whole mail, off');
  click(w, md.querySelector('[data-hbmv="text"]')); await sleep(150);
  const tx = md.querySelector('.hbmtext')?.textContent || '';
  check(/From Erika Muster, 12 October 2026/.test(tx) && /The real content of the offer\./.test(tx) && !/Kind regards/.test(tx) && !/Begin forwarded/.test(tx), 'short text: one line + content only ' + tx.slice(0, 80));
  click(w, md.querySelector('input[data-hbmv="whole"]')); await sleep(150);
  check(/Kind regards/.test(md.querySelector('.hbmtext')?.textContent || '') && md.querySelector('input[data-hbmv="whole"]')?.checked, 'Whole mail on: the whole text');
  click(w, md.querySelector('[data-hbmv="html"]')); await sleep(150);
  check(md.querySelector('iframe.hbmframe')?.getAttribute('src') === `/api/hubmail/mails/${FW}/html`, 'Whole mail on: the frame without ?short');
  click(w, md.querySelector('input[data-hbmv="whole"]')); await sleep(150);
  check(md.querySelector('iframe.hbmframe')?.getAttribute('src') === `/api/hubmail/mails/${FW}/html?short=1`, 'Whole mail off: short again');
  click(w, md.querySelector('[data-m="close"]')); await sleep(300);
  md = await openMail(PL);
  check(md && !md.querySelector('input[data-hbmv="whole"]') && md.querySelector('iframe.hbmframe')?.getAttribute('src') === `/api/hubmail/mails/${PL}/html`, 'a plain mail: no switch, nothing shortened');
  click(w, md.querySelector('[data-m="close"]')); await sleep(300);
  const css = fs.readFileSync(path.join(__dirname, '..', 'static', 'app.css'), 'utf8');
  check(/\.hbmdlg \.card\{width:min\(56rem,80vw\)/.test(css) && /@media \(max-width:40rem\)\{\.hbmdlg\{padding:0\}/.test(css), 'large window on the desktop, full screen on the phone (stylesheet)');
  const real = errs.filter(e => !/iframe|Could not load|resource/i.test(e));
  check(real.length === 0, 'no JS errors: ' + real.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
