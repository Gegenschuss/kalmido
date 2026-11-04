// kalmido-suite: fresh
// 2.394.0 UI tests, part A (#3377): Settings > Data > Import from Linear, own container (start.sh) with the fake Linear of
// fake_linear.py inside (KALMIDO_LINEAR_API), jsdom. freelancer-matrix: tasks
// - the source Linear: help text, CSV as the file type, a password field for the API key only for this source
// - key > Preview: the preview of the fake's issues (type, points and sprint in the sample rows), the import, the field emptied
// - the key never stays in the page after the import; another source hides the field and forgets the key
const {execFileSync} = require('child_process');
const fs = require('fs'), path = require('path');
const {boot, errs, sleep, B, login, idle} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const set = (w, el, v) => { el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const CT = process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test';
const KEY = 'lin_api_UIKEY0123456789';
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env,
  EXTRA: ((process.env.EXTRA || '') + ' -e KALMIDO_LINEAR_API=http://127.0.0.1:8085/graphql').trim()}});
const issue = (identifier, title, k = {}) => ({identifier, title, description: 'Text of ' + title, priority: 2, estimate: null, dueDate: null,
  createdAt: '2026-10-01T09:00:00.000Z', completedAt: null, canceledAt: null, url: null, state: {name: 'Todo', type: 'unstarted'},
  team: {name: 'Mobile', key: 'MOB'}, project: null, labels: {nodes: []}, assignee: null, cycle: null, parent: null, comments: {nodes: []}, ...k});
fs.writeFileSync(path.join(DATA, 'linear.json'), JSON.stringify({key: KEY, page: 50, mode: '', issues: [
  issue('MOB-1', 'Crash on start', {labels: {nodes: [{name: 'Bug'}]}, estimate: 5, cycle: {name: 'Cycle Blue', number: 7}}),
  issue('MOB-2', 'Dark mode')]}));
fs.copyFileSync(path.join(__dirname, 'fake_linear.py'), path.join(DATA, 'fake_linear.py'));
execFileSync('docker', ['exec', '-d', CT, 'python', '/data/fake_linear.py']);
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 250 : 20000, step: 250});

(async () => {
  await until(() => fs.existsSync(path.join(DATA, 'linear.log')));  // the fake is up
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  check(r.ok, 'setup');
  const ck = await login('alice');
  await fetch(B + 'api/settings', {method: 'PATCH', headers: {...H, Cookie: ck}, body: JSON.stringify({lang: 'en', tour: 'done'})});
  const w = await boot({user: 'alice'}), d = w.document;
  w.eval(`settingsModal()`); await idle(w);
  const md = d.querySelector('.smodal');
  click(w, md.querySelector('.snav [data-sec="data"]')); await sleep(300);
  const src = md.querySelector('#s-imp-src'), inp = md.querySelector('#s-import'), row = md.querySelector('#s-imp-keyrow'), key = md.querySelector('#s-imp-key');
  const out = () => md.querySelector('#s-imp-out');
  check(row && row.hidden && key && key.type === 'password' && key.autocomplete === 'off', 'the key field: a password field, hidden for Todoist');
  set(w, src, 'linear'); await sleep(50);
  check(!row.hidden && inp.accept === '.csv,text/csv', 'Linear: key field shown, CSV as the file');
  check(/Personal API keys/.test(md.querySelector('#s-imp-help').textContent) && /never stored/.test(md.querySelector('#s-imp-help').textContent),
    'Linear help: where the key comes from, never stored');
  // the preview with the key (the fake answers only to it)
  key.value = KEY;
  click(w, row.querySelector('[data-imp="key"]'));
  const box = await until(() => out().querySelector('.impbox [data-imp="go"]') && out().querySelector('.impbox'));
  check(box && /Preview: 2 tasks will be created/.test(box.textContent) && /Mobile/.test(box.textContent), 'preview of the issues: ' + (box?.textContent || '').slice(0, 120));
  const crash = [...(box?.querySelectorAll('.impr') || [])].find(x => /Crash on start/.test(x.textContent));
  check(crash && /Bug/.test(crash.textContent) && /Story points: 5/.test(crash.textContent) && /Sprint: Cycle Blue/.test(crash.textContent),
    'sample row: type, story points, sprint ' + (crash?.textContent || ''));
  check(!out().innerHTML.includes(KEY), 'the key is not shown in the preview');
  click(w, box.querySelector('[data-imp="go"]'));
  await until(() => /Imported: 2 tasks/.test(out().textContent));
  check(/Imported: 2 tasks/.test(out().textContent) && out().querySelector('[data-imp="undo"]'), 'import report with Undo');
  check(key.value === '' && !md.innerHTML.includes(KEY), 'the key field is empty after the import');
  check(await until(() => w.eval(`S.lists.some(l => l.name === 'Mobile') && [...S.tasks.values()].some(t => t.title === 'Crash on start')`)), 'the tasks are in the app (after the reload)');
  const log = fs.readFileSync(path.join(DATA, 'linear.log'), 'utf8').trim().split('\n').map(x => JSON.parse(x));
  check(log.length === 2 && log.every(x => x.good), 'preview and import each asked Linear with the key: ' + log.length);
  // another source: the field goes, the key is forgotten
  key.value = 'typed but not sent';
  set(w, src, 'jira'); await sleep(50);
  check(row.hidden && key.value === '', 'another source hides the field and empties it');
  w.close();
  if (errs.length) console.log('JS ERRORS', [...new Set(errs)]);
  console.log(`\n${ok} ok, ${F.length} failed`);
  process.exit(F.length || errs.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
