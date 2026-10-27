// 2.151.0 UI tests, part A (#2558): a task knows its build state. Own container (start.sh) with the fake GitHub of
// fake_git.py inside, jsdom. freelancer-matrix: lists
// - the task panel's Code section: the status line on top ("In version 1.1.0" / "In main, not released yet" / "Built, not in
//   main yet" with the branch row "2 commits ahead"), the hint "Package 1.1 is already released, but the task is still
//   open.", commit marks (version / branch); also shown for a task that only has the package hint
// - the task rows: a quiet hint only for a stale task and for work only on a branch (none for "in main"), German texts
// - list dialog > Repository: "Version field" (Automatic (Paket) / Off / the fields), saving it; a member sees no select
// - phone width: the status line and the hint in the panel
// - a person without an organisation: the same status line in the own project list
const {execFileSync} = require('child_process');
const fs = require('fs'), path = require('path');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const CT = process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test';
const GH = 'http://127.0.0.1:8090';
if (!process.env.P2151A_NOSTART && !process.env.KMT_NOSTART) {
  execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env,
    EXTRA: '-e KALMIDO_CALENDAR_ALLOW_HOSTS=127.0.0.1 -e KALMIDO_GIT_POLL=2 -e KALMIDO_GIT_TICK=1'}});
}
const STATE = {'8090': {}, '8091': {}, '8092': {}, '8093': {}};
const putState = () => { fs.writeFileSync(path.join(DATA, 'git.json.tmp'), JSON.stringify(STATE)); fs.renameSync(path.join(DATA, 'git.json.tmp'), path.join(DATA, 'git.json')); };
putState();
if (!process.env.P2151A_NOSTART && !process.env.KMT_NOSTART) {
  fs.copyFileSync(path.join(__dirname, 'fake_git.py'), path.join(DATA, 'fake_git.py'));
  execFileSync('docker', ['exec', '-d', CT, 'python', '/data/fake_git.py']);
}
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 80) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(250); } return fn(); };
const ALL = 'cal,timeline,matrix,habits,pomo,kanban,collab,stats,time,progress,deps,fields,comments,agents';
const iso = d => d.toISOString().replace(/\.\d+Z$/, 'Z');
const cm = (sha, message, days, repo = 'acme/app') => { const at = iso(new Date(Date.now() - days * 86400000));
  return {sha, html_url: `${GH}/${repo}/commit/${sha}`, author: {login: 'dev'}, commit: {message, author: {name: 'Dev', date: at}, committer: {date: at}}}; };
const taskOf = async (id, ck = CK) => (await call('GET', '/api/state', null, ck)).tasks.find(t => t.id === id);
const txt = el => (el?.textContent || '').replace(/\s+/g, ' ').trim();

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en', tour: 'done'});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const CKB = await login('bob');
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en', tour: 'done'}, CKB);
  const P = (await call('POST', '/api/lists', {name: 'App', kind: 'project'})).id;
  await call('PUT', `/api/lists/${P}/members`, {user_id: BOB, role: 'edit'});
  const T = {};
  for (const [k, title] of [[1, 'Released one'], [2, 'On a branch'], [3, 'In main'], [4, 'Only the package']]) T[k] = (await call('POST', '/api/tasks', {title, list_id: P})).id;
  const fid = (await call('POST', `/api/lists/${P}/fields`, {name: 'Paket', type: 'text'})).id;
  await call('PATCH', `/api/tasks/${T[1]}`, {fields: {[fid]: '1.1'}});
  await call('PATCH', `/api/tasks/${T[4]}`, {fields: {[fid]: '1.1'}});
  STATE['8090']['acme/app'] = {default_branch: 'main', pulls: [],
    commits: {main: [cm('c3', `Polish #${T[3]}`, 1), cm('c1', `Feature #${T[1]}`, 3)]},
    tags: [{name: 'v1.1.0'}, {name: 'v1.0.0'}],
    compare: {'v1.0.0...v1.1.0': [cm('c1', `Feature #${T[1]}`, 3)], [`kalmido-${T[2]}`]: [cm('b1', 'first step', 1), cm('b2', 'second step', 0)],
      // 2.151.0 A2 (#2558 review): newest tag...main = in main, not released (without it c3 counts as an earlier version)
      'v1.1.0...main': [cm('c3', `Polish #${T[3]}`, 1)]},
    branches: [{name: 'main', commit: {sha: 'c3'}}, {name: `kalmido-${T[2]}`, commit: {sha: 'b2'}}]};
  putState();
  const r = await call('POST', `/api/lists/${P}/repos`, {provider: 'github', base_url: GH, repo: 'acme/app'});
  check(r.id && r.full_name === 'acme/app', 'connected');
  await until(async () => (await taskOf(T[1]))?.code?.build?.version === '1.1.0' && (await taskOf(T[2]))?.code?.build?.branches?.length, 120);
  check((await taskOf(T[1]))?.code?.build?.stale, 'the server: task 1 stale');

  // ================= the task panel
  for (const [mobile, lab] of [[false, 'desktop'], [true, 'phone']]) {
    let w = await boot({user: 'alice', mobile, hash: 't/' + T[1]}), d = w.document; await sleep(400);
    let sec = await until(() => d.querySelector('#d-code'));
    check(/In version 1\.1\.0/.test(txt(sec?.querySelector('.gbuild'))) && sec.querySelector('.gbuild .i'), `${lab}: status line "In version 1.1.0": ${txt(sec?.querySelector('.gbuild'))}`);
    check(/Package 1\.1 is already released, but the task is still open\./.test(txt(sec?.querySelector('.gstale'))) && sec.querySelector('.gstale').getAttribute('role') === 'status',
      `${lab}: the stale hint: ${txt(sec?.querySelector('.gstale'))}`);
    check(sec && sec.querySelector('.gbuild') === sec.querySelector('h5').nextElementSibling, `${lab}: the status line on top of the section`);
    check(txt(sec?.querySelector('.gitrow .gmark.gm-rel')) === '1.1.0', `${lab}: the commit carries its version`);
    w.close();
    w = await boot({user: 'alice', mobile, hash: 't/' + T[2]}); d = w.document; await sleep(400);
    sec = await until(() => d.querySelector('#d-code'));
    check(/Built, not in main yet/.test(txt(sec?.querySelector('.gbuild'))), `${lab}: "Built, not in main yet": ${txt(sec?.querySelector('.gbuild'))}`);
    const br = sec?.querySelector('a.gitrow.gbr');
    check(br && /kalmido-\d+/.test(txt(br)) && /2 commits ahead/.test(txt(br)) && br.getAttribute('href') === `${GH}/acme/app/tree/kalmido-${T[2]}` && br.rel.includes('noopener'),
      `${lab}: the branch row: ${txt(br)}`);
    check([...sec.querySelectorAll('.gitrow .gmark')].some(x => txt(x) === `kalmido-${T[2]}`), `${lab}: commit marks name the branch`);
    check(!sec.querySelector('.gstale'), `${lab}: no stale hint on a branch`);
    w.close();
    w = await boot({user: 'alice', mobile, hash: 't/' + T[3]}); d = w.document; await sleep(400);
    sec = await until(() => d.querySelector('#d-code'));
    check(/In main, not released yet/.test(txt(sec?.querySelector('.gbuild'))), `${lab}: "In main, not released yet": ${txt(sec?.querySelector('.gbuild'))}`);
    w.close();
    w = await boot({user: 'alice', mobile, hash: 't/' + T[4]}); d = w.document; await sleep(400);
    sec = await until(() => d.querySelector('#d-code'));
    check(sec && /Package 1\.1 is already released/.test(txt(sec.querySelector('.gstale'))), `${lab}: a task with only the package: the section and the hint: ${txt(sec)}`);
    w.close();
  }

  // ================= the task rows
  let w = await boot({user: 'alice', hash: 'l/' + P}), d = w.document; await sleep(600);
  const rowOf = id => d.querySelector(`#view .trow[data-id="${id}"]`);
  await until(() => rowOf(T[1]));
  check(rowOf(T[1])?.querySelector('.gbrow.stale') && /still open/.test(rowOf(T[1]).querySelector('.gbrow').getAttribute('aria-label') || ''), 'row: the stale hint');
  check(rowOf(T[2])?.querySelector('.gbrow:not(.stale)') && /kalmido-/.test(rowOf(T[2]).querySelector('.gbrow').title), 'row: work only on a branch');
  check(rowOf(T[3]) && !rowOf(T[3]).querySelector('.gbrow'), 'row: nothing for "in main" (calm)');
  check(!/chip/i.test([...d.querySelectorAll('.gbrow')].map(x => x.title).join(' ')), 'no "chip" wording');

  // ================= list dialog > Repository > Version field
  w.eval(`listModal(${P})`);
  const sel = await until(() => d.querySelector('.lmodal #l-repos #rp-ver'));
  check(sel && [...sel.options].map(o => o.textContent).join('|') === 'Automatic (Paket)|Off|Paket' && sel.value === 'auto', 'the select: ' + [...(sel?.options || [])].map(o => o.textContent).join('|'));
  check(d.querySelector('.lmodal label[for="rp-ver"]') && /Version field/.test(txt(d.querySelector('.lmodal label[for="rp-ver"]'))), 'the label');
  sel.value = 'off'; sel.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(async () => (await call('GET', `/api/lists/${P}/repos`)).version_field?.setting === 'off'), 'saved: off');
  check(await until(async () => !(await taskOf(T[4]))?.code?.build?.stale), 'off: task 4 has no hint any more');
  await call('PUT', `/api/lists/${P}/repos/version-field`, {field: 'auto'});
  w.close();
  w = await boot({user: 'bob', hash: 'l/' + P}); d = w.document; await sleep(500);
  w.eval(`listModal(${P})`);
  await until(() => d.querySelector('.lmodal #l-repos .rpver'));
  check(d.querySelector('.lmodal .rpver') && !d.querySelector('.lmodal #rp-ver'), 'a member: the field shown, no select');
  w.close();

  // ================= German
  await call('PATCH', '/api/settings', {lang: 'de'});
  w = await boot({user: 'alice', hash: 't/' + T[3]}); d = w.document; await sleep(400);
  const de = txt((await until(() => d.querySelector('#d-code .gbuild'))));
  check(/In main, noch nicht veröffentlicht/.test(de), 'German: ' + de);
  w.close();
  await call('PATCH', '/api/settings', {lang: 'en'});

  // ================= a person without an organisation (freelancer-matrix: lists)
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en', tour: 'done'}, CF);
  const FP = (await call('POST', '/api/lists', {name: 'Site', kind: 'project'}, CF)).id;
  const F1 = (await call('POST', '/api/tasks', {title: 'Page', list_id: FP}, CF)).id;
  STATE['8090']['frida/site'] = {default_branch: 'main', pulls: [], commits: {main: [cm('f1', `Page #${F1}`, 1, 'frida/site')]}, tags: [], branches: []};
  putState();
  await call('POST', `/api/lists/${FP}/repos`, {provider: 'github', base_url: GH, repo: 'frida/site'}, CF);
  await until(async () => (await taskOf(F1, CF))?.code?.build?.state === 'main', 120);
  w = await boot({user: 'frida', mobile: true, hash: 't/' + F1}); d = w.document; await sleep(400);
  check(/In main, not released yet/.test(txt(await until(() => d.querySelector('#d-code .gbuild')))), 'freelancer: the status line');
  w.close();

  check(!errs.length, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`p2151_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
