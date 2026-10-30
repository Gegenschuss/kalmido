// kalmido-suite:
// 2.411.0 UI test (#3517: a list with many completed tasks in its sections is slow with "Show completed"), own container
// (start.sh), Firefox 1440 (mouse) and 390 (touch). A list with 40 sections, 50 open and 1000 completed tasks (they stay in
// their sections), written straight into the test database (like p265_d_ui.js); invented data only.
// - with "Show completed" on: opening and a render stay under the budget, the view is windowed (vlist.js), no "Show more"
// - scrolling to the very end: every step stays small, the number of drawn rows stays small (no growing DOM), the end
//   shows the last section's last task
// PERF lines name the numbers (start, render, scroll frames, drawn rows)
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2411_done_perf_ui', check, shots: 'P2411P_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const SECS = 40, OPEN = 50, DONE = 1000;
const perf = (k, v) => console.log(`PERF p2411_done ${k} = ${typeof v === 'number' ? Math.round(v * 10) / 10 : JSON.stringify(v)}`);

(async () => {
  if (!process.env.P2411P_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CK = await login('alice');
  const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
  await call('POST', '/api/admin/setup', {lang: 'en', modules: ['kanban']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'kanban'});
  const BUILT = (await call('POST', '/api/lists', {name: 'Built'})).id;
  check(BUILT, 'setup: the list');
  execFileSync('docker', ['exec', '-w', '/app', process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test', 'python', '-c', `
import datetime
from kalmido.core.db import connect
from kalmido.core.pg import insert_id
c = connect()
t0 = datetime.datetime.now(datetime.timezone.utc)
now = t0.isoformat()
secs = [insert_id(c, "INSERT INTO sections(list_id, name, sort) VALUES(?,?,?)", (${BUILT}, f"Version 2.{400 - k}", k)) for k in range(${SECS})]
for i in range(${OPEN}):
    c.execute("INSERT INTO tasks(list_id, section_id, title, priority, sort, created_at, updated_at, created_by) VALUES(?,?,?,0,?,?,?,1)",
              (${BUILT}, secs[i % ${SECS}], f"Open {i:04d}", i, now, now))
for i in range(${DONE}):
    done = (t0 - datetime.timedelta(minutes=i)).isoformat()
    c.execute("INSERT INTO tasks(list_id, section_id, title, priority, sort, status, completed_at, created_at, updated_at, created_by) VALUES(?,?,?,0,?,1,?,?,?,1)",
              (${BUILT}, secs[i * ${SECS} // ${DONE}], f"Done {i:04d}", 1000 + i, done, now, now))
c.execute("UPDATE settings SET value=CAST(CAST(value AS BIGINT)+1 AS TEXT) WHERE key='version'")
c.commit()
c.close()
`], {stdio: 'ignore'});

  for (const [vw, vh] of [[1440, 900], [390, 844]]) await firefox(async ({cmd, ev, ctx, nav}) => {
    const tag = String(vw), frame = `await new Promise(r => requestAnimationFrame(() => setTimeout(r, 0)))`;
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
    await nav(B + '#l/' + BUILT);
    for (let i = 0; i < 300 && !(await ev(`!!document.querySelector('#view .trow')`).catch(() => false)); i++) await sleep(50);
    // "Show completed" on (the list's own choice), timed until the completed rows are drawn
    const on = await ev(`(async () => { const t = performance.now(); await setShowDone(true); render(); ${frame};
      return {ms: performance.now() - t, done: S.tasks.size, dsx: !!viewTasks().dsx, vl: VL.on, rows: document.querySelectorAll('#view .trow').length, more: !!document.querySelector('#view [data-act="rows-more"]')}; })()`);
    perf(`${tag} show completed ms`, on.ms); perf(`${tag} drawn rows`, on.rows);
    check(on.dsx && on.done >= OPEN + DONE, `${tag}: completed tasks stay in their sections, all loaded ` + JSON.stringify(on));
    check(on.vl && !on.more && on.rows < 300, `${tag}: the view is windowed, no "Show more" ` + JSON.stringify(on));
    check(on.ms < 1500, `${tag}: "Show completed" draws in ${Math.round(on.ms)} ms`);
    const rt = await ev(`(async () => { const t = performance.now(); render(); ${frame}; return performance.now() - t; })()`);
    perf(`${tag} render ms`, rt); check(rt < 600, `${tag}: a render with completed tasks in ${Math.round(rt)} ms`);
    // scrolling down to the end
    const sc = await ev(`(async () => {
      const v = document.getElementById('view'), fr = []; let maxRows = 0, steps = 0;
      const t0 = performance.now();
      while (v.scrollTop + v.clientHeight < v.scrollHeight - 2 && steps < 400) {
        const t = performance.now(); v.scrollTop += v.clientHeight * .9; if (typeof vl_sync === 'function') vl_sync(); ${frame}; fr.push(performance.now() - t); steps++;
        maxRows = Math.max(maxRows, document.querySelectorAll('#view .trow').length);
        if (document.querySelector('#view [data-act="rows-more"]')) await new Promise(r => setTimeout(r, 50));
      }
      fr.sort((a, b) => a - b);
      const last = [...document.querySelectorAll('#view .trow[data-id]')].pop(), vr = v.getBoundingClientRect();
      return {all: performance.now() - t0, steps, avg: fr.reduce((a, b) => a + b, 0) / (fr.length || 1), p95: fr[Math.floor(fr.length * .95)] || 0, max: fr[fr.length - 1] || 0, maxRows,
        last: last && S.tasks.get(+last.dataset.id)?.title, vis: !!last && last.getBoundingClientRect().top < vr.bottom};
    })()`);
    perf(`${tag} scroll to end ms`, sc.all); perf(`${tag} scroll steps`, sc.steps); perf(`${tag} scroll frame ms p95`, sc.p95); perf(`${tag} scroll frame ms max`, sc.max); perf(`${tag} scroll max drawn rows`, sc.maxRows);
    check(sc.maxRows < 300, `${tag}: the drawn rows stay few while scrolling (${sc.maxRows})`);
    check(sc.p95 < 80, `${tag}: a scroll step takes ${Math.round(sc.p95)} ms (p95)`);
    check(sc.vis && /^Done 0*999$|^Open/.test(sc.last || ''), `${tag}: the end shows the last task ` + JSON.stringify({last: sc.last, vis: sc.vis}));
  }, vw < 600);

  console.log(`p2411_done_perf_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
