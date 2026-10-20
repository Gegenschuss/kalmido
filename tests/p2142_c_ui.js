// 2.142.0 UI tests, part C, own container (start.sh, mail address set). Invented names only.
// #2148: Settings > Data: next to "Download JSON" the links "Todoist CSV" and "Markdown" (the two ZIP routes, as downloads) + a hint.
// #2149: Settings > Integrations > Tasks by e-mail: an admin sees "Fetch mails now", a click locks it while it runs and shows a short
//        result; a member does not see the button.
// #2150: Settings > Notifications: "Share inbox (ntfy)": off by default; the switch gives a long topic, copy + "New topic" (asks first,
//        a different topic), "Own ntfy server" with server + read token (token field empty and hidden after saving: "set (hidden)",
//        removable); off hides the topic again. Nothing of the token on the page.
// P2142C_NOSTART=1 = the server already runs.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2142C_NOSTART !== '1') {
  const extra = '-e KALMIDO_MAIL_ADDRESS=tasks@example.test -e KALMIDO_IMAP_HOST=127.0.0.1 -e KALMIDO_IMAP_PORT=1143 -e KALMIDO_IMAP_SSL=0 -e KALMIDO_IMAP_USER=kalmido -e KALMIDO_IMAP_PASSWORD=secret -e KALMIDO_IMAP_INTERVAL=600';
  execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: `${process.env.EXTRA || ''} ${extra}`}});
}
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 60, ms = 150) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(ms); } return fn(); };

(async () => {
  await sleep(600);
  const r0 = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r0.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const ub = await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.test'});
  check(ub.status === 200, 'bob created');

  // ================= #2148 export links
  let w = await boot({user: 'alice'}), d = w.document;
  w.eval(`settingsModal('data')`);
  const js = await until(() => d.querySelector('a[href="/api/export.json"]'));
  check(js, 'Download JSON link');
  const td = d.querySelector('a[href="/api/export/todoist.zip"]'), mdl = d.querySelector('a[href="/api/export/markdown.zip"]');
  check(td && td.hasAttribute('download') && /Todoist CSV/.test(td.textContent), 'Todoist CSV link (download)');
  check(mdl && mdl.hasAttribute('download') && /Markdown/.test(mdl.textContent), 'Markdown link (download)');
  check(js && td && js.parentElement === td.parentElement, 'the three buttons share one row');
  w.close();

  // ================= #2149 admin button
  w = await boot({user: 'alice'}); d = w.document;
  w.eval(`settingsModal('integr')`);
  const pb = await until(() => d.querySelector('#s-mailpoll'));
  check(pb && /Fetch mails now/.test(pb.textContent), 'admin: the button is there');
  pb?.click();
  const res = await until(() => { const x = (d.querySelector('#s-mailpoll-r')?.textContent || '').trim(); return x && x !== 'Fetching…' ? x : ''; });
  check(/Started|fetched/.test(res || ''), 'admin: a short result: ' + res);
  check(await until(() => !d.querySelector('#s-mailpoll')?.disabled), 'admin: unlocked again after the answer');
  w.close();
  const CKB = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'}, CKB);
  w = await boot({user: 'bob'}); d = w.document;
  w.eval(`settingsModal('integr')`);
  await until(() => d.querySelector('#s-mail .row'));
  check(!d.querySelector('#s-mailpoll'), 'member: no button');
  w.close();

  // ================= #2150 share inbox
  w = await boot({user: 'bob'}); d = w.document;
  w.eval(`settingsModal('notify')`);
  const sw = await until(() => d.querySelector('#s-ntfyin #s-nion'));
  check(sw && !sw.checked && !d.querySelector('#s-nitopic'), 'off by default, no topic shown');
  sw.checked = true; sw.dispatchEvent(new w.Event('change', {bubbles: true}));
  const tp = await until(() => d.querySelector('#s-nitopic'));
  const t1 = tp?.textContent || '';
  check(t1.length >= 16 && /^[\w-]+$/.test(t1), 'on: a long topic ' + t1);
  check(d.querySelector('#s-ntfyin [data-ni="copy"]') && d.querySelector('#s-ntfyin [data-ni="dice"]'), 'copy + new topic buttons');
  check(/Android/.test(d.querySelector('#s-ntfyin')?.textContent || ''), 'short instructions');
  d.querySelector('#s-ntfyin [data-ni="dice"]').click();
  (await until(() => d.querySelector('[data-cd="yes"]')))?.click();
  const t2 = await until(() => { const x = d.querySelector('#s-nitopic')?.textContent; return x && x !== t1 ? x : ''; });
  check(t2 && t2.length >= 16, 'new topic is a different one');
  const det = d.querySelector('#s-ntfyin details');
  check(det && d.querySelector('#s-niurl') && d.querySelector('#s-nitok')?.type === 'password', 'own server: url + password field');
  d.querySelector('#s-niurl').value = 'http://127.0.0.1:8099';
  d.querySelector('#s-nitok').value = 'tk_ui_secret_token';
  d.querySelector('#s-ntfyin [data-ni="save"]').click();
  await until(() => /set \(hidden\)/.test(d.querySelector('#s-nitok')?.getAttribute('placeholder') || ''));
  check(d.querySelector('#s-nitok').value === '' && d.querySelector('#s-niurl').value === 'http://127.0.0.1:8099', 'token field empty after saving, server kept');
  check(!(d.querySelector('#s-ntfyin')?.innerHTML || '').includes('tk_ui_secret_token'), 'no token on the page');
  d.querySelector('#s-ntfyin [data-ni="rmtok"]').click();
  await until(() => !d.querySelector('#s-ntfyin [data-ni="rmtok"]'));
  check(!d.querySelector('#s-ntfyin [data-ni="rmtok"]'), 'token removed');
  const sw2 = d.querySelector('#s-nion'); sw2.checked = false; sw2.dispatchEvent(new w.Event('change', {bubbles: true}));
  await until(() => !d.querySelector('#s-nitopic'));
  check(!d.querySelector('#s-nitopic'), 'off: topic hidden again');
  check(!errs.length, 'no script errors ' + JSON.stringify(errs).slice(0, 200));
  w.close();

  console.log(`p2142_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
