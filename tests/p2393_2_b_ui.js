// kalmido-suite:
// 2.393.2 B UI test (#3375), own container (start.sh with the SMTP stub of tests/stub_mail.py), Firefox 1280 px. Invented people only.
// - a task with a reporter by e-mail: the comment field has the switch "Also by e-mail to the reporter" (off by default); a
//   comment sent with it on goes to the reporter by mail (the SMTP stub), the switch is off again afterwards
// - a task without a reporter: no switch
// freelancer-matrix: mail (frida has no organisation, P4)
// P23932B_NOSTART=1 = the server already runs. Screenshots: P23932B_SHOTS.
const fs = require('fs');
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2393_2_b_ui', check, shots: 'P23932B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const CT = process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test';
const ENV = '-e KALMIDO_SMTP_HOST=127.0.0.1 -e KALMIDO_SMTP_PORT=1025 -e KALMIDO_SMTP_TLS=none -e KALMIDO_MAIL_FROM=kalmido@example.test';
if (!process.env.P23932B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: ((process.env.EXTRA || '') + ' ' + ENV).trim()}});
const call = async (ck, method, url, body) => {
  for (let i = 0; ; i++) {
    const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined});
    if (r.status === 429 && i < 8) { await sleep(500 * (i + 1)); continue; }
    const j = await r.json().catch(() => ({})); return {...j, http: r.status};
  }
};
const db = (sql, args) => JSON.parse(execFileSync('python3', [path.join(__dirname, 'dbx.py'), DATA, sql, JSON.stringify(args || [])]).toString() || '[]');
const sent = () => { try { return fs.readFileSync(path.join(DATA, 'mail', 'out.jsonl'), 'utf8').split('\n').filter(Boolean).map(l => JSON.parse(l).raw); } catch { return []; } };
const FEAT = 'cal,comments,collab';

(async () => {
  fs.mkdirSync(path.join(DATA, 'mail', 'in'), {recursive: true});
  fs.copyFileSync(path.join(__dirname, 'stub_mail.py'), path.join(DATA, 'stub_mail.py'));
  execFileSync('docker', ['exec', '-d', CT, 'python', '/data/stub_mail.py']);
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida Solo', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(!((await call(CF, 'GET', '/api/state')).me.workspaces || []).length, 'P4: frida has no organisation');
  const L = (await call(CF, 'POST', '/api/lists', {name: 'Desk'})).id;
  const T = (await call(CF, 'POST', '/api/tasks', {title: 'Printer is broken', list_id: L})).id;
  const T2 = (await call(CF, 'POST', '/api/tasks', {title: 'Order paper', list_id: L})).id;
  // the task as if it came in by mail (the mail path itself: p2393_2_b_api)
  db("INSERT INTO task_mail(task_id,msg_id,sender,kind,created_at) VALUES(?,?,?,?,?)", [T, '<p23932b-ui@example.org>', 'rita@example.com', 'in', '2026-11-02T10:00:00Z']);
  check((await call(CF, 'GET', `/api/tasks/${T}/timeline`)).mail_reporter?.address === 'rita@example.com', 'the timeline names the reporter');
  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };

  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'frida', password: 'password123'})}).then(r => r.status)`) === 200, 'frida signs in');
    // the task without a reporter: no switch
    await nav(B + `#t/${T2}`);
    check(await ready(ev, `!!document.querySelector('#c-input') && S.tl.id === ${T2} && !!S.tl.activity`, 80), 'the task without a reporter is open');
    check(await ev(`!document.querySelector('#c-mrep [data-mrep]')`), 'no reporter: no switch');
    // the task with a reporter: the switch, off by default
    await nav(B + `#t/${T}`);
    check(await ready(ev, `!!document.querySelector('#c-mrep [data-mrep="switch"]')`, 80), 'the switch "Also by e-mail to the reporter"');
    check(await ev(`document.querySelector('#c-mrep [data-mrep="switch"]').checked === false`), 'the switch is off by default');
    check(await ev(`document.querySelector('#c-mrep').textContent.includes('Also by e-mail to the reporter')`), 'its label');
    await ev(`(() => { const i = document.querySelector('#c-input'); i.focus(); i.value = 'We replaced the toner.'; i.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
    await ev(`(() => { document.querySelector('#c-mrep [data-mrep="switch"]').click(); return 1; })()`);
    check(await ev(`document.querySelector('#c-mrep [data-mrep="switch"]').checked === true`), 'the switch is on');
    await shot('p23932b-switch.png');
    const n0 = sent().length;
    await ev(`(() => { document.querySelector('[data-act="c-send"]').click(); return 1; })()`);
    let out = [];
    for (let i = 0; i < 80 && !out.length; i++) { out = sent().slice(n0); if (!out.length) await sleep(250); }
    check(out.length === 1 && /^To: rita@example\.com/m.test(out[0]) && /^Subject: Re: Printer is broken/m.test(out[0]) && out[0].includes('We replaced the toner.'),
      'the comment goes to the reporter by mail ' + (out[0] || '').slice(0, 300));
    check(await ready(ev, `[...document.querySelectorAll('#d-tl-items .cm')].some(c => c.textContent.includes('We replaced the toner.'))`, 40), 'the comment is in the timeline');
    check(await ready(ev, `document.querySelector('#c-mrep [data-mrep="switch"]')?.checked === false`, 40), 'the switch is off again after sending');
    await shot('p23932b-sent.png');
  });
  console.log(`p2393_2_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e && e.stack || e); console.log(`p2393_2_b_ui: ${ok} ok, ${F.length + 1} failed`); process.exit(1); });
