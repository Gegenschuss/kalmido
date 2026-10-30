// 2.40.0 UI tests, part A (#1432 "Load more" instead of loading everything), own container (start.sh). jsdom:
// - Agents > Jobs > All: 20 ended jobs first (the running one on top as well), "Load more" adds the rest and is gone at the
//   end; a change reloads only the first page, the older pages stay; "Open" has no button
// - Completed: 100 tasks first, "Load more" adds the rest; a change keeps what is loaded; Trash with few tasks: no button
// - News: every unread item + 50 read ones, "Load more" adds the next read ones; a change keeps the length; "Unread only": no button
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const CT = process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test';
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const py = code => execFileSync('docker', ['exec', CT, 'python', '-c', code], {encoding: 'utf8'}).trim();
const sql = (q, rows) => py(`import json
from kalmido.core.db import connect
c = connect()
for r in json.loads(${JSON.stringify(JSON.stringify(rows))}):
    c.execute(${JSON.stringify(q)}, r)
c.commit(); c.close()`);
const FEAT = 'comments,collab,agents';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['agents', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ME = (await call('GET', '/api/state')).me;
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'})).id;
  const AG = (await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write'], username: 'claude', display_name: 'Claude'})).id;
  check(!!AG, 'setup: an agent');
  const INBOX = (await call('GET', '/api/state')).lists.find(l => l.is_inbox)?.id;

  // ================= jobs
  const ts = i => `2026-02-0${1 + (i % 3)}T08:00:00Z`;
  sql('INSERT INTO agent_jobs (agent_id, user_id, title, state, created_at, updated_at) VALUES (?,?,?,?,?,?)',
    [[AG, ME.id, 'Still running', 'running', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'],
      ...Array.from({length: 26}, (_, i) => [AG, ME.id, 'Ended job ' + i, 'done', '2026-01-01T00:00:00Z', ts(i)])]);
  let w = await boot({user: 'alice', hash: 'agents', ls: {'tasks.jobsFilter': JSON.stringify('all')}}), d = w.document;
  await until(() => d.querySelectorAll('#view .jobs .job').length > 0);
  const nJobs = () => d.querySelectorAll('#view .jobs .job').length;
  check(nJobs() === 21, '#1432: 20 ended jobs + the running one first ' + nJobs());
  check(d.querySelector('#view .jobs .job')?.classList.contains('st-running'), '#1432: the running job on top (older than the ended ones)');
  let more = d.querySelector('#view [data-act="jobs-more"]');
  check(!!more && /Load older jobs/.test(more.textContent), '#1432: "Load more" under the jobs');  // 2.165.3 (#2631): Load older jobs
  click(w, more);
  await until(() => nJobs() === 27);
  check(nJobs() === 27 && !d.querySelector('#view [data-act="jobs-more"]'), '#1432: all 27 after "Load more", the button is gone ' + nJobs());
  const ids = [...d.querySelectorAll('#view .jobs .job')].map(e => e.id);
  check(new Set(ids).size === ids.length, '#1432: no job twice');
  sql('INSERT INTO agent_jobs (agent_id, user_id, title, state, created_at, updated_at) VALUES (?,?,?,?,?,?)',
    [[AG, ME.id, 'Brand new', 'done', '2026-03-01T00:00:00Z', '2026-03-01T00:00:00Z']]);
  await w.eval('loadJobs()'); await sleep(200);
  check(nJobs() === 28 && /Brand new/.test(d.querySelector('#view .jobs .job:nth-child(2)')?.textContent || ''), '#1432: a change reloads the first page, the older pages stay ' + nJobs());
  check(w.eval('S.jobs.older.length') === 7 && !d.querySelector('#view [data-act="jobs-more"]'), '#1432: the older page is kept, still no button');
  click(w, d.querySelector('[data-act="jobs-f"][data-f="open"]'));
  await until(() => nJobs() === 1);
  check(nJobs() === 1 && !d.querySelector('#view [data-act="jobs-more"]'), '#1432: Open: only the running job, no button');
  w.close();

  // ================= completed / trash
  const tids = [];
  for (let i = 0; i < 124; i++) tids.push((await call('POST', '/api/tasks', {title: 'Errand ' + i, list_id: INBOX})).id);
  sql('UPDATE tasks SET status=1, completed_at=? WHERE id=?', tids.slice(0, 120).map((id, i) => [`2026-03-0${1 + (i % 2)}T10:00:00Z`, id]));
  sql('UPDATE tasks SET deleted_at=? WHERE id=?', tids.slice(120).map(id => ['2026-03-05T10:00:00Z', id]));
  w = await boot({user: 'alice', hash: 'done'}); d = w.document;
  await until(() => (w.eval('S.extra || []')).length > 0);
  check(w.eval('S.route.key') === 'done' && w.eval('S.extra.length') === 100, '#1432: Completed: 100 first ' + w.eval('(S.extra || []).length'));
  more = await until(() => d.querySelector('#view [data-act="hist-more"]'));
  check(!!more, '#1432: "Load more" under Completed');
  click(w, more);
  await until(() => w.eval('S.extra.length') === 120);
  check(w.eval('S.extra.length') === 120 && w.eval('new Set(S.extra.map(t => t.id)).size') === 120 && !d.querySelector('#view [data-act="hist-more"]'), '#1432: all 120, no doubles, the button is gone');
  await w.eval('loadExtra()'); w.eval('renderView()');
  check(w.eval('S.extra.length') === 120, '#1432: a change keeps what is loaded ' + w.eval('S.extra.length'));
  w.location.hash = '#trash'; await until(() => w.eval('S.route.key') === 'trash' && (w.eval('S.extra || []')).length === 4);
  check(w.eval('S.extra.length') === 4 && !d.querySelector('#view [data-act="hist-more"]'), '#1432: Trash with 4 tasks: no button');
  check(w.eval('S.hist.deletable') === 4, '#1432: the trash knows how many Empty deletes');
  w.close();

  // ================= news
  sql('INSERT INTO notifications (user_id, kind, task_id, actor_id, created_at, read_at) VALUES (?,?,?,?,?,?)',
    Array.from({length: 83}, (_, i) => [ME.id, 'assign', tids[i % 100], BOB, '2026-04-01T10:00:00Z', i % 30 === 29 ? null : '2026-04-02T10:00:00Z']));
  w = await boot({user: 'alice', hash: 'news', ls: {'tasks.newsTab': JSON.stringify('all')}}); d = w.document;
  await until(() => (w.eval('S.nf.items || []')).length > 0);
  check(w.eval('S.nf.items.length') === 52 && w.eval('S.nf.items.filter(x => !x.read).length') === 2, '#1432: News: every unread + 50 read ' + w.eval('(S.nf.items || []).length'));
  more = await until(() => d.querySelector('#view [data-act="news-more"]'));
  check(!!more, '#1432: "Load more" under the news');
  click(w, more);
  await until(() => w.eval('S.nf.items.length') === 83);
  check(w.eval('S.nf.items.length') === 83 && !d.querySelector('#view [data-act="news-more"]'), '#1432: all 83, the button is gone');
  w.eval('S.nf.sig = null'); w.eval('renderView()'); await sleep(300); await until(() => !w.eval('S.nf.loading'));
  check(w.eval('S.nf.items.length') === 83, '#1432: a change reloads as many as are loaded ' + w.eval('S.nf.items.length'));
  w.close();
  w = await boot({user: 'alice', hash: 'news', ls: {'tasks.newsUnread': 'true'}}); d = w.document;
  await until(() => (w.eval('S.nf.items || []')).length > 0); await sleep(200);
  check(!d.querySelector('#view [data-act="news-more"]'), '#1432: Unread only: no "Load more"');
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
