// 2.17.0 (#649) performance: an isolated container with many generated tasks (PERF_N, default 5000; the CI run uses 5000,
// PERF_BIG=1 adds a 20000 round) in ~50 lists with sections, subtasks, tags and comments, written straight into the
// test database. Measured: /api/state (time, size), the list endpoints, search; Firefox at 1440 (mouse) and 390 (touch):
// start until the list is visible, switching lists, "All", the command field (open + type), a re-render after a live
// update, keyboard moving. Generous limits so it only fails when something gets really slow; the numbers are printed
// (PERF_REPORT=<file> appends them as JSON).
const {execFileSync} = require('child_process');
const fs = require('fs');
const path = require('path');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'perf_ui', check, shots: 'PERF_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const PY = process.env.PYTHON || 'python3';
const REP = [];
const rep = (k, v) => { REP.push([k, v]); console.log(`perf: ${k} = ${typeof v === 'number' ? Math.round(v) : v}`); };

async function round(n) {
  execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CK = await login('alice');
  const call = async (method, url, body) => { const t0 = Date.now(); const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); const txt = await r.text(); return {ms: Date.now() - t0, size: txt.length, j: (() => { try { return JSON.parse(txt); } catch { return {}; } })(), status: r.status}; };
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['kanban', 'cal', 'comments']});
  await call('PATCH', '/api/settings', {features: 'kanban,cal,comments,collab', lang: 'en', tour: 'done'});
  // seed straight into the database (the app has it open in WAL mode; one transaction)
  execFileSync(PY, ['-c', `
import sqlite3, random, datetime
c = sqlite3.connect(${JSON.stringify(path.join(DATA, 'tasks.db'))}, timeout=30)
random.seed(7)
now = datetime.datetime.now(datetime.timezone.utc).isoformat()
today = datetime.date.today()
lists = []
for i in range(50):
    lid = c.execute("INSERT INTO lists(name, owner_id, sort, created_at) VALUES(?,?,?,?)", (f"List {i:02d}", 1, i, now)).lastrowid
    secs = [c.execute("INSERT INTO sections(list_id, name, sort) VALUES(?,?,?)", (lid, f"Section {k}", k)).lastrowid for k in range(3)]
    lists.append((lid, secs))
n, made = ${n}, 0
words = "plan call write check order send review fix build test draft update clean book pay".split()
while made < n:
    lid, secs = random.choice(lists)
    due = (today + datetime.timedelta(days=random.randint(-20, 60))).isoformat() if random.random() < .6 else None
    t = c.execute("INSERT INTO tasks(list_id, section_id, title, priority, due, sort, created_at, updated_at, created_by) VALUES(?,?,?,?,?,?,?,?,1)",
                  (lid, random.choice(secs + [None]), " ".join(random.sample(words, 3)).capitalize() + f" {made}", random.choice([0, 0, 1, 3, 5]), due, made, now, now)).lastrowid
    made += 1
    if random.random() < .15 and made < n:
        c.execute("INSERT INTO tasks(list_id, parent_id, title, sort, created_at, updated_at, created_by) VALUES(?,?,?,?,?,?,1)", (lid, t, f"Sub {made}", made, now, now))
        made += 1
    if random.random() < .2:
        c.execute("INSERT OR IGNORE INTO task_tags(task_id, user_id, tag) VALUES(?,1,?)", (t, random.choice(["home", "work", "urgent", "later"])))
    if random.random() < .1:
        c.execute("INSERT INTO comments(task_id, user_id, body, created_at) VALUES(?,1,?,?)", (t, "A comment", now))
c.execute("UPDATE settings SET value=CAST(value AS INTEGER)+1 WHERE key='version'")
c.commit()
print(made)
`], {stdio: 'ignore'});
  const L = (await call('GET', '/api/state')).j.lists.find(l => l.name === 'List 07').id;
  // server
  const st = []; for (let i = 0; i < 3; i++) st.push(await call('GET', '/api/state'));
  const sms = Math.min(...st.map(x => x.ms));
  rep(`${n} /api/state ms`, sms); rep(`${n} /api/state KB`, st[0].size / 1024);
  check(st[0].j.tasks.length > n * .3, `${n}: the state has the tasks (${st[0].j.tasks.length})`);
  check(sms < (n > 10000 ? 6000 : 2500), `${n}: /api/state in ${sms} ms`);
  const sr = await call('GET', '/api/tasks?q=review%20fix'); rep(`${n} search ms`, sr.ms);
  check(sr.ms < 2000, `${n}: search in ${sr.ms} ms`);
  const tok = (await call('POST', '/api/me/tokens', {name: 'p', scopes: ['read']})).j.token;
  const t0 = Date.now(); const v1 = await fetch(B + `api/v1/tasks?list_id=${L}&limit=500`, {headers: {Authorization: 'Bearer ' + tok}}); await v1.text();
  rep(`${n} v1 list ms`, Date.now() - t0); check(Date.now() - t0 < 2000, `${n}: v1 tasks of a list`);
  // browser
  for (const [vw, vh, touch] of [[1440, 900, false], [390, 844, true]]) await firefox(async o => {
    const {cmd, ev, ctx, nav} = o, tag = `${n} ${vw}`;
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
    const s0 = Date.now();
    await nav(B + '#l/' + L);
    for (let i = 0; i < 300 && !(await ev(`!!document.querySelector('#view .trow')`).catch(() => false)); i++) await sleep(50);
    const start = Date.now() - s0; rep(`${tag} start ms`, start);
    check(start < (n > 10000 ? 15000 : 8000), `${tag}: start until the list shows in ${start} ms`);
    const m = async (name, js, lim) => { const r = await ev(`(async () => { const t = performance.now(); ${js}; await new Promise(r => requestAnimationFrame(() => setTimeout(r, 0))); return performance.now() - t; })()`); rep(`${tag} ${name} ms`, r); check(r < lim, `${tag}: ${name} in ${Math.round(r)} ms (limit ${lim})`); return r; };
    await m('switch list', `go('l/${L + 1}')`, 1500);
    await m('today', `go('today')`, 2000);
    await m('all', `go('all')`, n > 10000 ? 8000 : 4000);
    await m('re-render (live update)', `render()`, n > 10000 ? 8000 : 4000);
    const rm = await ev(`(() => ({rows: document.querySelectorAll('#view .trow').length, more: !!document.querySelector('#view [data-act="rows-more"]')}))()`);
    check(rm.rows <= 900 && rm.more, `${tag}: "All" shows the first rows and "Show more" ` + JSON.stringify(rm));
    await ev(`(() => { document.querySelector('#view [data-act="rows-more"]').click(); return 1; })()`); await sleep(400);
    const rm2 = await ev(`document.querySelectorAll('#view .trow').length`);
    check(rm2 > rm.rows, `${tag}: "Show more" adds rows (${rm.rows} -> ${rm2})`);
    await ev(`(() => { go('l/${L}'); return 1; })()`); await sleep(500);
    await m('render list', `render()`, 1500);
    await m('palette open + type', `openPalette(); const i = document.querySelector('.palette .pqin'); i.value = 'review'; i.dispatchEvent(new Event('input', {bubbles: true}))`, 1500);
    await ev(`(() => { closePalette(); return 1; })()`);
    await m('keyboard ↓ x10', `for (let i = 0; i < 10; i++) document.dispatchEvent(new KeyboardEvent('keydown', {key: 'j', bubbles: true}))`, 1500);
    await m('open a task', `openDetail(+document.querySelector('#view .trow').dataset.id)`, 1500);
    const rows = await ev(`document.querySelectorAll('#view .trow').length`); rep(`${tag} rows in list`, rows);
  }, false);
}

(async () => {
  await round(+(process.env.PERF_N || 5000));
  if (process.env.PERF_BIG) await round(20000);
  if (process.env.PERF_REPORT) fs.appendFileSync(process.env.PERF_REPORT, JSON.stringify(Object.fromEntries(REP)) + '\n');
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
