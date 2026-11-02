// kalmido-suite: fresh
// 2.392.0 UI tests, part B (#3364): own container (start.sh) with the fake GitHub of fake_git.py inside, jsdom. freelancer-matrix: lists
// - list dialog > Repository: the switch "Complete tasks when their package or code is released" (off, saved), only for who manages it
// - the task menu has "Partly, rest in …" with a version field, not without one; the question, the rest task afterwards
// - the history of a completed task: "Released in 1.1.0" with Undo; German texts
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
  EXTRA: '-e KALMIDO_CALENDAR_ALLOW_HOSTS=127.0.0.1 -e KALMIDO_GIT_POLL=2 -e KALMIDO_GIT_TICK=1'}});
const STATE = {'8090': {}, '8091': {}, '8092': {}, '8093': {}};
const putState = () => { fs.writeFileSync(path.join(DATA, 'git.json.tmp'), JSON.stringify(STATE)); fs.renameSync(path.join(DATA, 'git.json.tmp'), path.join(DATA, 'git.json')); };
putState();
fs.copyFileSync(path.join(__dirname, 'fake_git.py'), path.join(DATA, 'fake_git.py'));
execFileSync('docker', ['exec', '-d', CT, 'python', '/data/fake_git.py']);
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 250 : 20000, step: 250});
const taskOf = async id => (await call('GET', '/api/state')).tasks.find(t => t.id === id);
const txt = el => (el?.textContent || '').replace(/\s+/g, ' ').trim();
const cm = (sha, msg) => ({sha, html_url: `${GH}/acme/app/commit/${sha}`, author: {login: 'dev'}, commit: {message: msg, author: {name: 'Dev', date: new Date(Date.now() + 5000).toISOString()}, committer: {date: new Date().toISOString()}}});

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,fields,deps'});
  const P = (await call('POST', '/api/lists', {name: 'App', kind: 'project'})).id, N = (await call('POST', '/api/lists', {name: 'Plain', kind: 'project'})).id;
  const fid = (await call('POST', `/api/lists/${P}/fields`, {name: 'Paket', type: 'text'})).id;
  const t1 = (await call('POST', '/api/tasks', {title: 'Task one', list_id: P})).id, t2 = (await call('POST', '/api/tasks', {title: 'Task two', list_id: P})).id;
  const tn = (await call('POST', '/api/tasks', {title: 'Task plain', list_id: N})).id;
  STATE['8090']['acme/app'] = {default_branch: 'main', pulls: [], commits: {main: [cm('a1', `Feature #${t1}`)]}, tags: [{name: 'v1.1.0'}, {name: 'v1.0.0'}],
    compare: {'v1.0.0...v1.1.0': [cm('a1', `Feature #${t1}`)], 'v1.1.0...main': []}, branches: [{name: 'main', commit: {sha: 'a1'}}]};
  putState();
  await call('POST', `/api/lists/${P}/repos`, {provider: 'github', base_url: GH, repo: 'acme/app'});
  await until(async () => (await taskOf(t1))?.code?.build?.stale, 120);

  let w = await boot({user: 'alice', hash: 'l/' + P}), d = w.document; await sleep(500);
  w.eval(`listModal(${P})`);
  const box = await until(() => d.querySelector('.lmodal #l-repos #rp-close'));
  check(box && !box.checked && !box.disabled, 'the switch: off for a new connection');
  check(/Complete tasks when their package or code is released/.test(txt(d.querySelector('.lmodal .rpclose'))), 'its label');
  box.checked = true; box.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(async () => (await call('GET', `/api/lists/${P}/repos`)).close_release === true), 'saved');
  check(await until(async () => (await taskOf(t1))?.status === 2, 120), 'the poll completed the task');
  w.close();

  w = await boot({user: 'alice', hash: 't/' + t1}); d = w.document; await sleep(600);
  await until(() => /Released in 1\.1\.0/.test(txt(d.body)));
  check(/Released in 1\.1\.0: acme\/app/.test(txt(d.body)), 'the history: released in');
  check(d.querySelector('[data-act="git-undo"]'), 'the history: Undo');
  w.close();

  w = await boot({user: 'alice', hash: 'l/' + P}); d = w.document; await sleep(500);
  const labels = async id => { w.eval(`taskMenu(document.body, ${id})`); await sleep(200); d.querySelector('#pop .mtmore')?.click(); await sleep(100); const a = [...d.querySelectorAll('#pop [role="menuitem"]')].map(txt); w.eval('closePop?.()'); return a; };
  check((await labels(t2)).some(x => /Partly, rest in/.test(x)), 'the menu with a version field');
  check(!(await labels(tn)).some(x => /Partly, rest in/.test(x)), 'not without one');
  w.prompt = () => '1.2';  // the question (boot.js dialogBridge)
  w.eval(`gitPartial(${t2})`);
  check(await until(async () => (await taskOf(t2))?.partial_until === '1.2'), 'saved: partial_until');
  check(await until(async () => (await call('GET', '/api/state')).tasks.some(t => t.title === 'Rest: Task two' && String(t.fields?.[fid]) === '1.2')), 'the rest task with its version');
  w.close();
  check(!errs.length, 'no script errors: ' + errs.slice(0, 2).join(' | '));
  console.log(`p2392_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e); console.log(`p2392_b_ui: ${ok} ok, ${F.length + 1} failed`); process.exit(1); });
