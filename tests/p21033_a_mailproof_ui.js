// kalmido-suite:
// 2.1033.0 UI test (#5790), own container (start.sh with the SMTP stub of tests/stub_mail.py), Firefox 1280 px. Invented people only.
// - Settings > Account: the row "E-mail address" shows the own address, "not confirmed", the button "Confirm address" and why
// - the button sends the proof mail (the SMTP stub gets it) and the hint says where to open the link
// - the link opened while signed out: the token leaves the address bar, the sign-in page shows; after the sign-in the app
//   confirms the address (message "Address confirmed"), the account row then says "confirmed" without a button
// freelancer-matrix: own (frida has no organisation, P4)
// P21033A_NOSTART=1 = the server already runs. Screenshots: P21033A_SHOTS.
const fs = require('fs');
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21033_a_mailproof_ui', check, shots: 'P21033A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const CT = process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test';
const ENV = '-e KALMIDO_SMTP_HOST=127.0.0.1 -e KALMIDO_SMTP_PORT=1025 -e KALMIDO_SMTP_TLS=none -e KALMIDO_MAIL_FROM=kalmido@example.test';
if (!process.env.P21033A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: ((process.env.EXTRA || '') + ' ' + ENV).trim()}});
const call = async (ck, method, url, body) => {
  for (let i = 0; ; i++) {
    const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined});
    if (r.status === 429 && i < 8) { await sleep(500 * (i + 1)); continue; }
    const j = await r.json().catch(() => ({})); return {...j, http: r.status};
  }
};
const db = (sql, args) => JSON.parse(execFileSync('python3', [path.join(__dirname, 'dbx.py'), DATA, sql, JSON.stringify(args || [])]).toString() || '[]');
// the links of the proof mails to frida (the mail is MIME: the standard library decodes it)
const PROOFS = `import email, email.policy, json, re, sys
out = []
for ln in open(sys.argv[1]):
    if ln.strip():
        m = email.message_from_string(json.loads(ln)["raw"], policy=email.policy.default)
        if "frida@example.com" in str(m["To"]) and "Confirm your e-mail address" in str(m["Subject"]):
            x = re.search(r"#mailproof/([A-Za-z0-9_-]{20,100})", m.get_body(("plain",)).get_content())
            out.append(x.group(1) if x else "")
print(json.dumps(out))`;
const proofs = () => { try { return JSON.parse(execFileSync('python3', ['-I', '-c', PROOFS, path.join(DATA, 'mail', 'out.jsonl')]).toString()); } catch { return []; } };

(async () => {
  fs.mkdirSync(path.join(DATA, 'mail', 'in'), {recursive: true});
  fs.copyFileSync(path.join(__dirname, 'stub_mail.py'), path.join(DATA, 'stub_mail.py'));
  execFileSync('docker', ['exec', '-d', CT, 'python', '/data/stub_mail.py']);
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida Solo', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  check(!((await call(CF, 'GET', '/api/state')).me.workspaces || []).length, 'P4: frida has no organisation');
  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = ev => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'frida', password: 'password123'})}).then(r => r.status)`);

  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await signIn(ev) === 200, 'frida signs in');
    await nav(B);
    check(await ready(ev, `typeof S !== 'undefined' && S.booted === true`, 80), 'the app is there');
    // ---- Settings > Account: the address, not confirmed, the button and why
    await ev(`(settingsModal('account'), 1)`);
    check(await ready(ev, `document.querySelector('#a-epv')?.textContent.includes('frida@example.com')`, 80), 'Account shows the own address');
    check(await ev(`document.querySelector('#a-epv').textContent.includes('E-mail address') && document.querySelector('#a-epv').textContent.includes('not confirmed')`), 'labelled, "not confirmed"');
    check(await ev(`!!document.querySelector('#a-epv [data-epv="send"]') && document.querySelector('#a-epv [data-epv="send"]').textContent.includes('Confirm address')`), 'the button "Confirm address"');
    check(await ev(`(document.querySelector('#a-epv-h')?.textContent || '').includes('invitations of organisations')`), 'the hint says why');
    await shot('p21033a-account.png');
    // ---- the button sends the mail
    await ev(`(document.querySelector('#a-epv [data-epv="send"]').click(), 1)`);
    let toks = [];
    for (let i = 0; i < 80 && !toks.length; i++) { toks = proofs(); if (!toks.length) await sleep(250); }
    check(toks.length === 1 && toks[0], 'the proof mail went to frida@example.com');
    check(await ready(ev, `(document.querySelector('#a-epv-h')?.textContent || '').includes('Open the link in the e-mail')`, 40), 'the hint says where to open the link');
    // ---- the link while signed out: the sign-in first, then the app confirms
    await ev(`fetch('/api/auth/logout', {method: 'POST', headers: {'X-Requested-With': 'kalmido'}}).then(r => r.status)`);
    await nav(B + 'static/icon.svg');
    await nav(B + '#mailproof/' + (toks[0] || 'x'));
    check(await ready(ev, `!!document.querySelector('#au-user')`, 80), 'signed out: the sign-in page');
    check(await ev(`location.hash === '' && sessionStorage.getItem('kalmido.epv') === ${JSON.stringify(toks[0] || 'x')}`), 'the token left the address bar and waits in the tab');
    check(db('SELECT email_proved FROM users WHERE username=?', ['frida'])[0]?.email_proved === '', 'not confirmed before the sign-in');
    check(await signIn(ev) === 200, 'frida signs in again');
    await nav(B);  // the sign-in page reloads the app the same way (location.replace)
    check(await ready(ev, `(document.querySelector('#toast')?.textContent || '').includes('Address confirmed')`, 80), 'the message "Address confirmed"');
    check(db('SELECT email_proved FROM users WHERE username=?', ['frida'])[0]?.email_proved === 'frida@example.com', 'the address is confirmed');
    check(await ev(`sessionStorage.getItem('kalmido.epv') === null`), 'the token is used up in the tab');
    await ev(`(settingsModal('account'), 1)`);
    check(await ready(ev, `!!document.querySelector('#a-epv .epvok') && document.querySelector('#a-epv .epvok').textContent.includes('confirmed') && !document.querySelector('#a-epv').textContent.includes('not confirmed')`, 80), 'Account says "confirmed"');
    check(await ev(`!document.querySelector('#a-epv [data-epv="send"]') && !document.querySelector('#a-epv-h')`), 'no button, no hint any more');
    await shot('p21033a-confirmed.png');
  });
  console.log(`p21033_a_mailproof_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e && e.stack || e); console.log(`p21033_a_mailproof_ui: ${ok} ok, ${F.length + 1} failed`); process.exit(1); });
