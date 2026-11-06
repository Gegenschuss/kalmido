// 2.142.0 UI tests, part C, own container (start.sh, mail address set). Invented names only.
// #2148: Settings > Data: next to "Download JSON" the links "Todoist CSV" and "Markdown" (the two ZIP routes, as downloads) + a hint.
// #2149: Settings > Integrations > Tasks by e-mail: an admin sees "Fetch e-mails now", a click locks it while it runs and shows a short
//        result; a member does not see the button.
// #2150: Settings > Notifications: "Share inbox (ntfy)" - 2.574.0 (#3779): taken out; the ntfy notifications stay, no inbox block,
//        Integrations has no ntfy app hint any more.
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
const until = (fn, n, ms = 150) => require('./boot').until(fn, {timeout: n ? n * ms : 15000, step: ms});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window

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
  check(pb && /Fetch e-mails now/.test(pb.textContent), 'admin: the button is there');
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
  // 2.574.0 (#3779): sharing through the ntfy app is gone: Settings > Notifications keeps the ntfy notifications (topic, test)
  // without the block "Share inbox (ntfy)"; Settings > Integrations points to the upload way, not to the ntfy app
  w = await boot({user: 'bob'}); d = w.document;
  w.eval(`settingsModal('notify')`);
  await until(() => d.querySelector('#s-ntfy .topic'));
  check(d.querySelector('#s-ntfy .topic') && !d.querySelector('#s-ntfyin, #s-nion'), '#3779: ntfy notifications stay, no share inbox block');
  check(!/Share inbox/.test(d.querySelector('.smodal')?.textContent || ''), '#3779: no "Share inbox" text in the notifications');
  w.eval(`settingsModal('integr')`);
  await until(() => d.querySelector('#s-share-h'));
  check(d.querySelector('#s-share-h') && !/ntfy app/.test(d.querySelector('#s-share-h').closest('[data-pane]')?.textContent || ''), '#3779: Integrations: sharing from the phone without the ntfy app');
  check(!errs.length, 'no script errors ' + JSON.stringify(errs).slice(0, 200));
  w.close();

  console.log(`p2142_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
