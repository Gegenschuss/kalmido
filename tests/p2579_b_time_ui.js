// 2.579.0 UI test, part B (#4184): the delta carries the time totals of the changed tasks only (tt=1, time_ids); the
// kalmido-suite: fresh
// app mixes them into S.timeTotals instead of replacing it, jsdom:
// - a new entry on one task (another device): its total follows through GET /api/state/delta?...&tt=1, no GET /api/state
// - the totals of the other tasks stay in the app (before: replaced by the narrow map, they were gone)
// - a task whose entries are all gone loses its total
// Every wait is on a real state (the app's own change poll).
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, until: until0} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
const until = fn => until0(fn, {timeout: 20000, step: 100});
const iso = d => d.toISOString().slice(0, 19) + 'Z';
const entry = (ck, tid, minAgo, len) => { const a = new Date(Date.now() - minAgo * 60000); return call(ck, 'POST', '/api/time/entries', {task_id: tid, start: iso(a), end: iso(new Date(a.getTime() + len * 60000))}); };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'time,progress'});
  const L = (await call(CA, 'POST', '/api/lists', {name: 'Studio', kind: 'project', time_tracking: true})).id;
  const T = (await call(CA, 'POST', '/api/tasks', {title: 'Edit the trailer', list_id: L})).id;
  const O = (await call(CA, 'POST', '/api/tasks', {title: 'Colour grading', list_id: L})).id;
  check((await entry(CA, T, 300, 30)).id && (await entry(CA, O, 200, 60)).id, 'entries on both tasks');
  const w = await boot({user: 'alice', hash: 'l/' + L});
  check(await until(() => w.eval(`(S.timeTotals[${O}] || [])[0] === 3600 && (S.timeTotals[${T}] || [])[0] === 1800`)), 'the app has both totals');
  // the page is settled: its poll areas are there and it has taken the server's last change (no load of its own pending)
  const caught = () => until(async () => !!w.eval('!!S.lpA && !td_polling') && (await call(CA, 'GET', '/api/version')).v === w.eval('S.v'));
  check(await caught(), 'the page is settled');
  const st0 = w.eval('S.lpN.state'), dl0 = w.eval('S.lpN.delta');
  const f1 = w.fetch, seen = [];
  w.fetch = (u, o = {}) => { seen.push(`${(o.method || 'GET').toUpperCase()} ${u}`); return f1(u, o); };

  // a new entry on T from another device: the delta (tt=1) brings T's total, O's stays
  const e2 = await entry(CA, T, 100, 15);
  check(e2.id, 'a second entry on T');
  check(await until(() => w.eval(`(S.timeTotals[${T}] || [])[0] === 2700`)), 'T\'s total follows (45 minutes)');
  check(w.eval(`(S.timeTotals[${O}] || [])[0] === 3600`), 'O\'s total stays in the app (mixed, not replaced)');
  check(seen.some(k => /^GET \/api\/state\/delta\?.*&tt=1/.test(k)), 'through the delta with tt=1 ' + JSON.stringify(seen.filter(k => /state/.test(k))));
  check(!seen.some(k => /^GET \/api\/state(\?|$)/.test(k)) && w.eval('S.lpN.state') === st0 && w.eval('S.lpN.delta') > dl0,
    'no full GET /api/state for it, a delta ' + JSON.stringify(w.eval('S.lpN')));

  // every entry of T gone: T loses its total, O keeps its own
  const list = await call(CA, 'GET', `/api/time/entries?task_id=${T}`);
  const ids = (list.items || list.entries || []).filter(e => e.task_id === T).map(e => e.id);
  check(ids.length === 2, 'T has two entries ' + JSON.stringify(ids));
  for (const id of ids) await call(CA, 'DELETE', `/api/time/entries/${id}`);
  check(await until(() => w.eval(`!S.timeTotals[${T}]`)), 'T\'s total is gone');
  check(w.eval(`(S.timeTotals[${O}] || [])[0] === 3600`), 'O\'s total still there');
  w.close();

  console.log(`p2579_b_time_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
