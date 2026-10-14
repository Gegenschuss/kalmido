// 2.40.0 (#1430) measurement, own container (start.sh), Firefox on a desktop (1440 x 900, mouse): a list in the table layout
// with 300 tasks and two custom fields (text + choice) as columns. Prints (lines "PERF ..."):
// - the time of one full render() and of one renderView() (median and maximum of 10 runs, performance.now around the call),
//   first with 225 rows (the form of the first measurement before #1430: priorities none / low / medium), then with all 300
// - 50 quick changes through the API one after the other while the list is shown: how many renders the page made until it
//   had them all, and the time spent in them
// Only the setup and that the page catches up are checked; the numbers are for the release notes (they depend on the machine).
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2400_t_perf', check, shots: 'P2400T_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body, h = {}) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...h, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const N = 300, BURST = 50;

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'fields'});
  const L = (await call(CA, 'POST', '/api/lists', {name: 'Inventory'})).id;
  const FT = (await call(CA, 'POST', `/api/lists/${L}/fields`, {name: 'Package', type: 'text'})).id;
  const FS = await call(CA, 'POST', `/api/lists/${L}/fields`, {name: 'State', type: 'select', options: {options: [{name: 'Open', color: '#e5484d'}, {name: 'Doing', color: '#3e63dd'}, {name: 'Done', color: '#30a46c'}]}});
  const OPTS = (FS.options?.options || []).map(o => o.id);
  check(FT && FS.id && OPTS.length === 3, 'two fields (setup)');
  await call(CA, 'PATCH', `/api/lists/${L}`, {columns: ['due', `f:${FT}`, `f:${FS.id}`]});
  const ids = [];
  const mk = async i => { const t = await call(CA, 'POST', '/api/tasks', {title: `Item ${i + 1}`, list_id: L, priority: [0, 1, 5, 3][i % 4], due: i % 3 ? `2026-11-${String(1 + i % 28).padStart(2, '0')}` : null,
    fields: {[FT]: `pkg-${i % 17}`, [FS.id]: OPTS[i % 3]}}); ids[i] = t.id; };
  for (let i = 0; i < N; i++) if (i % 4 !== 2) await mk(i);
  check(ids.filter(Boolean).length === N * 3 / 4, `${N * 3 / 4} tasks (setup)`);

  await firefox(async o => {
    const {cmd, ev, ctx, nav, shot} = o;
    const ready = async (expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await nav(B + '#l/' + L);
    check(await ready(`!!document.querySelector('#view .lchead') && document.querySelectorAll('#view .trow').length >= ${N * 3 / 4}`), 'Firefox: the list with columns and all rows');
    await sleep(800);
    // the counters: every render() and every renderView0() (the view part), with their time
    await ev(`(() => { const P = window.__perf = {r: 0, rt: 0, v: 0, vt: 0};
      const wrap = (name, n, t) => { const f = window[name]; window[name] = function (...a) { const s = performance.now(); try { return f.apply(this, a); } finally { P[n]++; P[t] += performance.now() - s; } }; };
      wrap('render', 'r', 'rt'); wrap('renderView0', 'v', 'vt'); return 1; })()`);
    const one = async fn => ev(`(() => { const s = performance.now(); ${fn}(); return performance.now() - s; })()`);
    const stat = a => { const s = [...a].sort((x, y) => x - y); return {median: +s[Math.floor(s.length / 2)].toFixed(1), max: +s[s.length - 1].toFixed(1)}; };
    const measure = async n => {
      const rs = [], vs = [];
      for (let i = 0; i < 10; i++) { rs.push(await one('render')); await sleep(100); }
      for (let i = 0; i < 10; i++) { vs.push(await one('renderView')); await sleep(100); }
      const R = stat(rs), V = stat(vs);
      console.log(`PERF render() ${n} rows, 2 fields: median ${R.median} ms, max ${R.max} ms`);
      console.log(`PERF renderView() ${n} rows, 2 fields: median ${V.median} ms, max ${V.max} ms`);
      check(R.median > 0 && V.median > 0, 'the renders were measured');
    };
    await measure(N * 3 / 4);
    for (let i = 2; i < N; i += 4) await mk(i);
    check(ids.filter(Boolean).length === N, `${N} tasks (setup)`);
    check(await ready(`document.querySelectorAll('#view .trow').length >= ${N}`), 'the page shows all 300 rows');
    await sleep(800);
    await measure(N);
    await shot('p2400t-perf.png');
    // 50 quick changes from elsewhere (the API), the page follows by itself
    await ev(`(() => { Object.assign(window.__perf, {r: 0, rt: 0, v: 0, vt: 0}); return 1; })()`);
    const t0 = Date.now();
    for (let i = 0; i < BURST; i++) await call(CA, 'PATCH', `/api/tasks/${ids[i * 5]}`, {title: `Item ${i * 5 + 1} changed`, fields: {[FS.id]: OPTS[(i + 1) % 3]}});
    const sent = Date.now() - t0;
    const caught = await ready(`document.querySelectorAll('#view .trow').length >= ${N} && [...document.querySelectorAll('#view .trow')].filter(r => /changed/.test(r.textContent)).length === ${BURST}`, 80);
    check(caught, 'the page shows all 50 changes');
    await sleep(4500);  // one more poll: nothing changed any more
    const P = await ev(`window.__perf`);
    console.log(`PERF ${BURST} changes through the API in ${sent} ms: ${P.r} render() (${P.rt.toFixed(1)} ms in total), ${P.v} renderView (${P.vt.toFixed(1)} ms in total)`);
  }, false);

  console.log(`p2400_t_perf: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
