// 2.192.0 A (#2512): the test clock on the JS side (tests/boot.js). run_all.sh runs this group at `now sun 23:50` (the Berlin
// midnight and the week start on purpose): the suite's Date (Node) and the app's Date (jsdom window) follow KALMIDO_TEST_NOW like
// the server, the clock runs on, dates with arguments stay as they are; server and client agree about "today"; a Node process
// without the variable keeps the real time.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, testNow} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const berlinDay = ms => new Intl.DateTimeFormat('en-CA', {timeZone: 'Europe/Berlin'}).format(new Date(ms));
(async () => {
  const TN = process.env.KALMIDO_TEST_NOW, AT = Number(process.env.KALMIDO_TEST_NOW_AT);
  check(!!TN && AT > 0, 'run_all.sh sets KALMIDO_TEST_NOW + _AT for this group: ' + TN + ' / ' + AT);
  const off = Date.parse(TN) - AT * 1000;  // what boot.js shifts by
  // Node: now = test instant + the real time since _AT (a few seconds), not the real time
  const real = Number(execFileSync(process.execPath, ['-e', 'console.log(Date.now())'], {env: {...process.env, KALMIDO_TEST_NOW: '', KALMIDO_TEST_NOW_AT: ''}}).toString());
  const n0 = Date.now();
  check(Math.abs(n0 - (real + off)) < 5000, `Node Date.now() = real time + test offset (${n0 - real - off} ms)`);
  check(Math.abs(new Date().getTime() - n0) < 1000 && Math.abs(Date.parse(Date()) - n0) < 2000 && Math.abs(testNow().getTime() - n0) < 1000,
    'new Date(), Date() and testNow() follow it');
  check(n0 - Date.parse(TN) >= 0 && n0 - Date.parse(TN) < 600000, 'the clock started at the test instant ' + TN);
  check(new Date(2026, 0, 15, 12).getDate() === 15 && new Date(0).getTime() === 0 && Date.UTC(2026, 0, 1) === 1767225600000
    && Date.parse('2026-01-01T00:00:00Z') === 1767225600000 && new Date() instanceof Date, 'dates with arguments, UTC, parse, instanceof unchanged');
  // a Node process with boot.js but without the variable: real time
  const plain = Number(execFileSync(process.execPath, ['-e', "require('./boot'); console.log(Date.now())"], {cwd: __dirname,
    env: {...process.env, KALMIDO_TEST_NOW: '', KALMIDO_TEST_NOW_AT: ''}}).toString());
  check(Math.abs(plain - (Date.now() - off)) < 10000, 'without KALMIDO_TEST_NOW boot.js keeps the real time');
  await sleep(1100);
  check(Date.now() - n0 >= 1000, 'the clock runs on');

  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CK = await login('alice');
  const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
  const w = await boot({user: 'alice', hash: 'today'}), d = w.document;
  // the window: the app's own Date follows the same clock
  const wn = w.eval('Date.now()');
  check(Math.abs(wn - Date.now()) < 2000 && Math.abs(w.eval('new Date().getTime()') - Date.now()) < 2000, `window Date follows the test clock (${wn - Date.now()} ms)`);
  check(w.eval('new Date(2026, 0, 15).getDate() === 15 && new Date() instanceof Date && typeof Date() === "string"'), 'window: dates with arguments, instanceof, Date()');
  const day = w.eval('today()');
  check(day === berlinDay(Date.now()), `the app's today() is the test day in Berlin (${day})`);
  // server and client agree: the server stamps a new task with its (shifted) clock
  const t1 = await call('POST', '/api/tasks', {title: 'Due on the test day', due: day});
  const st = await call('GET', '/api/state'), row = (st.tasks || []).find(t => t.id === t1.id) || {};
  const cat = Date.parse(String(row.created_at || t1.created_at));  // core/db.py iso(): UTC with +00:00
  check(Math.abs(cat - Date.now()) < 120000, `the server's clock = the test clock (created_at ${row.created_at || t1.created_at})`);
  check(berlinDay(cat) === day, 'server and client agree about today');
  const tomorrow = w.eval('ds(new Date(pd(today()).getTime() + 36e5 * 30))');
  await call('POST', '/api/tasks', {title: 'Due on the day after', due: tomorrow});
  await w.eval('load()'); w.eval(`go('today')`); await sleep(400);
  const txt = d.body.textContent;
  check(txt.includes('Due on the test day'), 'a task due on the test day is in Today');
  check(!txt.includes('Due on the day after'), 'a task due the day after is not in Today');
  w.close();
  console.log(F.length ? 'FAILED ' + F.length : 'OK ' + ok); process.exit(F.length ? 1 : 0);
})();
