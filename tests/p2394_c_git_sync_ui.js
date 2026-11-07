// kalmido-suite: fresh
// 2.394.0 UI tests, part C (#3377): the issue sync in the list dialog > Repository, own container (start.sh) with the fake
// GitHub of fake_git.py inside, jsdom. freelancer-matrix: lists
// - per GitHub repository the switch "Sync issues both ways" with its explanation, off; on: saved, the state line says
//   "read-only" for a repository without a token (it cannot write issues), "Create new tasks as issues" is locked then
// - a member who does not manage the repository sees no switches
// - the history: a change made by the sync names the issue, a lost version of a conflict is shown with field and value
const {execFileSync} = require('child_process');
const fs = require('fs'), path = require('path');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const CT = process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test';
const GH = 'http://127.0.0.1:8090';
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env,
  EXTRA: '-e KALMIDO_CALENDAR_ALLOW_HOSTS=127.0.0.1 -e KALMIDO_GIT_POLL=3600 -e KALMIDO_GIT_TICK=1'}});
const STATE = {'8090': {'acme/app': {default_branch: 'main', pulls: [], issues: []}}, '8091': {}, '8092': {}, '8093': {}};
fs.writeFileSync(path.join(DATA, 'git.json'), JSON.stringify(STATE));
fs.copyFileSync(path.join(__dirname, 'fake_git.py'), path.join(DATA, 'fake_git.py'));
execFileSync('docker', ['exec', '-d', CT, 'python', '/data/fake_git.py']);
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 250 : 20000, step: 250});
const txt = el => (el?.textContent || '').replace(/\s+/g, ' ').trim();
const dbx = (sql, args = []) => JSON.parse(execFileSync('python3', [path.join(__dirname, 'dbx.py'), DATA, sql, JSON.stringify(args)]).toString() || '[]');

(async () => {
  await until(() => fs.existsSync(path.join(DATA, 'git.log')));  // the fake is up
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,fields,deps'});
  const bob = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const P = (await call('POST', '/api/lists', {name: 'App', kind: 'project'})).id;
  await call('PUT', `/api/lists/${P}/members`, {user_id: bob, role: 'edit'});
  const t1 = (await call('POST', '/api/tasks', {title: 'Task one', list_id: P})).id;
  const rp = await call('POST', `/api/lists/${P}/repos`, {provider: 'github', base_url: GH, repo: 'acme/app'});
  check(rp.id && rp.issue_sync === false, 'connected, the sync off');

  let w = await boot({user: 'alice', hash: 'l/' + P}), d = w.document; await sleep(500);
  w.eval(`listModal(${P})`);
  let sw = await until(() => d.querySelector(`.lmodal [data-gsy-rid="${rp.id}"] [data-gsy="issue_sync"]`));
  check(sw && !sw.checked && !sw.disabled, 'the switch: off, usable');
  check(/Sync issues both ways/.test(txt(sw?.closest('.gsy'))) && /the newer change wins/.test(txt(sw?.closest('.gsy'))), 'its label and explanation');
  check(!d.querySelector(`.lmodal [data-gsy="issue_create"]`), '"Create new tasks as issues" only once the sync is on');
  sw.checked = true; sw.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(async () => (await call('GET', `/api/lists/${P}/repos`)).repos?.[0]?.issue_sync === true), 'saved');
  const st = await until(() => (x => x && /cannot write issues/.test(txt(x)) && x)(d.querySelector(`.lmodal [data-gsy-rid="${rp.id}"] .gsyst`)));
  check(st, 'the state line: read only (no token, no write access): ' + txt(d.querySelector('.lmodal .gsy')));
  const cr = d.querySelector(`.lmodal [data-gsy="issue_create"]`);
  check(cr && cr.disabled, '"Create new tasks as issues" is locked while it only reads');
  w.close();

  w = await boot({user: 'bob', hash: 'l/' + P}); d = w.document; await sleep(500);
  w.eval(`listModal(${P})`);
  await until(() => d.querySelector('.lmodal #l-repos .reporow'));
  check(d.querySelector('.lmodal #l-repos .reporow') && !d.querySelector('.lmodal [data-gsy]'), 'a member who does not manage it: no switches');
  w.close();

  // the history entries the sync writes (as the sync writes them: no person, data.gsy = the issue)
  const ts = new Date().toISOString();
  dbx("INSERT INTO activity(task_id,user_id,kind,data,created_at) VALUES(?,NULL,'title',?,?)", [t1, JSON.stringify({to: 'Repo B', gsy: 'acme/app#1'}), ts]);
  dbx("INSERT INTO activity(task_id,user_id,kind,data,created_at) VALUES(?,NULL,'git_sync_lost',?,?)",
    [t1, JSON.stringify({field: 'title', value: 'Here A', side: 'here', gsy: 'acme/app#1'}), ts]);
  dbx("INSERT INTO activity(task_id,user_id,kind,data,created_at) VALUES(?,NULL,'git_sync_lost',?,?)",
    [t1, JSON.stringify({field: 'state', value: 'closed', side: 'repo', gsy: 'acme/app#1'}), ts]);
  // lazy: the conflict lines live in gitrepo.js, the task panel loads it and draws again
  w = await boot({user: 'alice', hash: 't/' + t1, lazy: true}); d = w.document; await sleep(600);
  await until(() => /Conflict with/.test(txt(d.body)));
  const b = txt(d.body);
  check(/acme\/app#1 renamed the task to “Repo B”/.test(b), 'a change by the sync names the issue');
  check(/Conflict with acme\/app#1 \(Title\): the change in the repository was newer\. The version here was: Here A/.test(b), 'the lost version here');
  check(/Conflict with acme\/app#1 \(Status\): the change here was newer\. The version in the repository was: closed/.test(b), 'the lost version of the repository');
  w.close();
  check(!errs.length, 'no script errors: ' + errs.slice(0, 2).join(' | '));
  console.log(`p2394_c_git_sync_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e); console.log(`p2394_c_git_sync_ui: ${ok} ok, ${F.length + 1} failed`); process.exit(1); });
