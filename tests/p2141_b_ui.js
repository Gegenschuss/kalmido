// 2.141.0 part B UI test (#2140, #2139), own container (start.sh with the stub mailbox): the HTML view of a filed mail and a
// task / an event made from it.
// - a mail with an HTML part opens in the HTML view: Text / HTML switch, a frame with sandbox WITHOUT allow-scripts /
//   allow-same-origin on the server's own page, a quiet hint "External images are blocked" + "Load images" (the frame then asks
//   with ?images=1, the hint goes); Text shows the plain text; a mail without HTML: no switch, the text as before
// - "Task from it": the dialog (title without Re, a writable list), the task is made, the reading view lists "Task: ...", the task
//   detail shows "E-mail: <subject>" and a tap opens the mail; "Event from it": the event's popover shows the mail too
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
if (process.env.P2141B_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' ' + MAILENV}});
fs.mkdirSync(path.join(DATA, 'mail', 'in'), {recursive: true});
fs.copyFileSync(path.join(__dirname, 'stub_mail.py'), path.join(DATA, 'stub_mail.py'));
execFileSync('docker', ['exec', '-d', CT, 'python', '/data/stub_mail.py']);
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return Array.isArray(j) ? j : {...j, status: r.status}; };
let NO = 0;
const mail = (to, from, subject, text, html) => {
  NO++;
  const head = `From: ${from}\r\nTo: ${to}\r\nSubject: ${subject}\r\nMessage-ID: <ui2141b-${NO}@example.test>\r\nDate: Tue, 20 Oct 2026 10:00:00 +0200\r\nMIME-Version: 1.0\r\n`;
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
  const L = (await call('POST', '/api/lists', {name: 'Mail work'})).id;
  const CAL = (await call('POST', '/api/evcals', {name: 'Mail cal'})).id;
  const IN = (await call('POST', '/api/hubmail/address', {ws: 'private'})).address;
  check(L && CAL && IN, 'setup: list, calendar, filing address');
  mail(IN, 'Shop <news@example.test>', 'Re: Spring offer', 'Spring offer as text', '<p>Spring <b>offer</b> as HTML</p><img src="https://img.example.com/pic.png" alt="pic"><script>alert(1)</script>');
  mail(IN, 'Pat <pat@example.test>', 'Plain note', 'Only plain text here.');
  await call('POST', '/api/admin/mail/poll', {});
  const got = await until(async () => ((await call('GET', '/api/hubmail/inbox')).mails || []).length >= 2);
  check(got, 'setup: the mails were filed');
  const ms = (await call('GET', '/api/hubmail/inbox')).mails || [];
  const HM = ms.find(m => m.subject === 'Re: Spring offer')?.id, TM = ms.find(m => m.subject === 'Plain note')?.id;

  let w = await boot({user: 'alice', hash: 'mailhub'}), d = w.document;
  await until(async () => d.querySelectorAll('.hbmhub .hbmrow').length >= 2, 6000);
  const openMail = async id => { click(w, d.querySelector(`.hbmhub [data-hbmopen="${id}"]`)); return until(async () => d.querySelector('.modal.hbmdlg'), 5000); };

  // ---- #2140 the HTML view
  let md = await openMail(HM);
  const fr = md && md.querySelector('iframe.hbmframe');
  check(fr, 'HTML view: the frame');
  const sb = fr ? (fr.getAttribute('sandbox') || '').split(/\s+/) : ['?'];
  check(fr && fr.hasAttribute('sandbox') && !sb.includes('allow-scripts') && !sb.includes('allow-same-origin'), 'frame sandbox without scripts / same origin: ' + sb.join(' '));
  check(fr && fr.getAttribute('src') === `/api/hubmail/mails/${HM}/html`, 'frame: the server page ' + (fr && fr.getAttribute('src')));
  check(fr && fr.getAttribute('referrerpolicy') === 'no-referrer', 'frame: no referrer');
  check(md && !md.querySelector('.hbmtext'), 'HTML view: no plain text box');
  const seg = md && md.querySelector('.hbmseg');
  check(seg && seg.querySelector('[data-hbmv="html"].on') && seg.querySelector('[data-hbmv="text"]:not(.on)'), 'switch: HTML on by default');
  check(md && md.querySelector('.hbmimg [data-hbmv="img"]') && /External images are blocked/.test(md.querySelector('.hbmimg').textContent), 'hint: external images blocked + Load images');
  click(w, md.querySelector('[data-hbmv="img"]')); await sleep(150);
  check(md.querySelector('iframe.hbmframe')?.getAttribute('src') === `/api/hubmail/mails/${HM}/html?images=1`, 'Load images: the frame asks with ?images=1');
  check(!md.querySelector('.hbmimg'), 'Load images: the hint goes');
  click(w, md.querySelector('[data-hbmv="text"]')); await sleep(150);
  check(!md.querySelector('iframe') && /Spring offer as text/.test(md.querySelector('.hbmtext')?.textContent || ''), 'Text: the plain text instead of the frame');
  click(w, md.querySelector('[data-hbmv="html"]')); await sleep(150);
  check(md.querySelector('iframe.hbmframe'), 'HTML again');
  check(md.querySelector('.hbmactrow [data-hbmmk="task"]') && md.querySelector('.hbmactrow [data-hbmmk="event"]'), 'the actions Task / Event from it');
  click(w, md.querySelector('[data-m="close"]')); await sleep(300);
  md = await openMail(TM);
  check(md && !md.querySelector('.hbmseg') && !md.querySelector('iframe') && /Only plain text here/.test(md.querySelector('.hbmtext')?.textContent || ''), 'a text mail: no switch, the text as before');
  click(w, md.querySelector('[data-m="close"]')); await sleep(300);

  // ---- #2139 Task from it
  md = await openMail(HM);
  click(w, md.querySelector('[data-hbmmk="task"]'));
  const tk = await until(async () => d.querySelector('.modal.hbmmkdlg'), 5000);
  check(tk && tk.querySelector('#hbm-mkt')?.value === 'Spring offer', 'task dialog: the title without Re ' + (tk && tk.querySelector('#hbm-mkt')?.value));
  const sel = tk && tk.querySelector('#hbm-mkp');
  check(sel && [...sel.options].some(o => +o.value === L), 'task dialog: my list to pick');
  if (sel) sel.value = String(L);
  if (tk) click(w, tk.querySelector('[data-m="save"]'));
  const made = await until(async () => ((await call('GET', `/api/hubmail/mails/${HM}`)).made || []).find(x => x.kind === 'task'), 6000);
  check(made && made.title === 'Spring offer', 'the task was made');
  const TID = made?.id;
  md = await until(async () => d.querySelector('.modal.hbmdlg .hbmmade'), 5000);
  check(md && /Task: Spring offer/.test(md.textContent), 'the reading view lists the task');
  // the task detail shows the mail, a tap opens it
  if (md) click(w, md.closest('.modal').querySelector('[data-m="close"]'));
  await sleep(300);
  await until(async () => w.eval(`!!taskById(${TID})`), 6000);
  w.eval(`openDetail(${TID})`);
  const ln = await until(async () => d.querySelector('#detail .hbmlnk [data-hbmopen]'), 6000);
  check(ln && /E-mail: Re: Spring offer/.test(ln.textContent), 'task detail: "E-mail: <subject>" ' + (ln && ln.textContent));
  if (ln) click(w, ln);
  md = await until(async () => d.querySelector('.modal.hbmdlg'), 5000);
  check(md && /Spring offer/.test(md.querySelector('h3')?.textContent || ''), 'a tap opens the mail');
  if (md) click(w, md.querySelector('[data-m="close"]'));
  await sleep(300);

  // ---- Event from it
  w.eval(`go('mailhub')`); await until(async () => d.querySelector(`.hbmhub [data-hbmopen="${HM}"]`), 6000);
  md = await openMail(HM);
  click(w, md.querySelector('[data-hbmmk="event"]'));
  const em = await until(async () => d.querySelector('.modal.hbmmkdlg'), 5000);
  const cs = em && em.querySelector('#hbm-mkp');
  check(cs && [...cs.options].some(o => +o.value === CAL), 'event dialog: my calendar to pick');
  check(em && em.querySelector('#hbm-mkd')?.value, 'event dialog: a date set');
  if (cs) cs.value = String(CAL);
  if (em) click(w, em.querySelector('[data-m="save"]'));
  const mev = await until(async () => ((await call('GET', `/api/hubmail/mails/${HM}`)).made || []).find(x => x.kind === 'event'), 6000);
  check(mev && mev.title === 'Spring offer', 'the event was made');
  await sleep(500);
  const modal = d.querySelector('.modal.hbmdlg'); if (modal) click(w, modal.querySelector('[data-m="close"]'));
  await sleep(300);
  if (mev) {
    w.eval(`evOpen(${mev.id})`);
    const el = await until(async () => d.querySelector('#pop .hbmlnk [data-hbmopen]'), 8000);
    check(el && /E-mail: Re: Spring offer/.test(el.textContent), 'event popover: the mail');
  }

  const real = errs.filter(e => !/iframe|Could not load|resource/i.test(e));
  check(real.length === 0, 'no JS errors: ' + real.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
