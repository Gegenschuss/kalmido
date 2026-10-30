// 2.126.0 UI tests, part D (jsdom), fresh DB:
// - #1989 two windows of one browser (one localStorage, Web Locks): both offline, one change each -> each window knows both
//   waiting changes; back online in both at the same moment -> each change reaches the server exactly once, both queues empty
// - #1990 a new task whose answer gets lost on the way back (the request reached the server) and that is sent again from
//   the queue = one task
// - #1992 O8 an offline change the server refuses (the task went to the trash meanwhile) waits in the conflicts dialog
//   with its text and "Copy"; O5 the queue goes out only once the server has said who is logged in on this page
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, ms) => require('./boot').until(fn, {timeout: ms || 15000, step: 100});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const st = async (ck = CK) => call('GET', '/api/state', null, ck);
// Web Locks of one browser (jsdom has none): request(name, {ifAvailable}, fn), shared by the windows
const held = new Set();
const LOCKS = {async request(name, opt, fn) {
  if (typeof opt === 'function') { fn = opt; opt = {}; }
  if (held.has(name)) { if (opt.ifAvailable) return fn(null); while (held.has(name)) await sleep(20); }
  held.add(name);
  try { return await fn({name}); } finally { held.delete(name); }
}};
const withLocks = w => Object.defineProperty(w.navigator, 'locks', {configurable: true, value: LOCKS});
// counts the writes that leave a window: [method, path]
const spy = w => { const calls = []; const of = w.fetch; w.fetch = (u, o = {}) => { if (!w.__offline) calls.push([(o.method || 'GET').toUpperCase(), new URL(String(u), B).pathname]); return of(u, o); }; return calls; };

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const P = (await call('POST', '/api/lists', {name: 'Flyers'})).id;
  const mk = async title => (await call('POST', '/api/tasks', {title, list_id: P})).id;
  const T0 = await mk('Draft the flyer'), TT = await mk('Old idea');

  // ================= #1989 two windows
  const shared = {store: {}, wins: []};
  const w1 = await boot({user: 'alice', hash: 'l/' + P, shared, setup: withLocks});
  const w2 = await boot({user: 'alice', hash: 'l/' + P, shared, setup: withLocks});
  const c1 = spy(w1), c2 = spy(w2);
  check(w1.eval('!!navigator.locks') && w2.eval('OUT.me === S.me.id'), 'setup: locks, the server said who is logged in');
  w1.__offline = w2.__offline = true;
  await w1.eval(`api('POST', '/api/tasks', {title: 'Made in window one', list_id: ${P}})`);
  await w2.eval(`api('PATCH', '/api/tasks/${T0}', {title: 'Renamed in window two'})`);
  check(w1.eval('OUT.q.length') === 2 && w2.eval('OUT.q.length') === 2, `each window knows both waiting changes ${w1.eval('OUT.q.length')} ${w2.eval('OUT.q.length')}`);
  check(JSON.parse(shared.store['tasks.outbox']).length === 2, 'the device keeps both');
  w1.__offline = w2.__offline = false;
  w1.dispatchEvent(new w1.Event('online')); w2.dispatchEvent(new w2.Event('online'));
  check(await until(() => w1.eval('OUT.q.length') === 0 && w2.eval('OUT.q.length') === 0 && !w1.eval('OUT.flushing') && !w2.eval('OUT.flushing')), 'both queues empty');
  let s = await st();
  check(s.tasks.filter(t => t.title === 'Made in window one').length === 1, `the new task exists once (${s.tasks.filter(t => t.title === 'Made in window one').length})`);
  check(s.tasks.find(t => t.id === T0)?.title === 'Renamed in window two', 'the other window\'s change arrived');
  const posts = [...c1, ...c2].filter(([m, p]) => m === 'POST' && p === '/api/tasks').length;
  const patches = [...c1, ...c2].filter(([m, p]) => m === 'PATCH' && p === '/api/tasks/' + T0).length;
  check(posts === 1 && patches === 1, `each change was sent once (POST ${posts}, PATCH ${patches})`);
  check(await until(() => [...w2.eval('S.tasks').values()].some(t => t.title === 'Made in window one' && t.id > 0)), 'the other window gets the real task too');
  w2.close();

  // ================= #1990 the answer got lost: sent again = the same task
  let lose = 1;
  const of = w1.fetch;
  w1.fetch = (u, o = {}) => {
    if (lose && (o.method || '') === 'POST' && new URL(String(u), B).pathname === '/api/tasks') { lose--; return of(u, o).then(() => { throw new TypeError('Failed to fetch'); }); }
    return of(u, o);
  };
  await w1.eval(`api('POST', '/api/tasks', {title: 'Answer lost', list_id: ${P}})`);
  check(w1.eval('OUT.q.length') === 1 && !!w1.eval('OUT.q[0].body.client_ref'), 'the create waits in the queue with its client_ref');
  w1.dispatchEvent(new w1.Event('online'));
  check(await until(() => w1.eval('OUT.q.length') === 0), 'sent again');
  s = await st();
  check(s.tasks.filter(t => t.title === 'Answer lost').length === 1, `one task, not two (${s.tasks.filter(t => t.title === 'Answer lost').length})`);
  w1.fetch = of;

  // ================= O8 a refused change keeps its text
  w1.__offline = true;
  await w1.eval(`api('PATCH', '/api/tasks/${TT}', {content: 'Lost words worth keeping'})`);
  check((await call('DELETE', '/api/tasks/' + TT)).status === 200, 'setup: the task went to the trash elsewhere');
  w1.__offline = false;
  w1.dispatchEvent(new w1.Event('online'));
  check(await until(() => w1.eval('OUT.q.length') === 0), 'the refused change left the queue');
  const cf = w1.eval('S.conflicts').find(c => c.field === 'rejected');
  check(!!cf && /Lost words worth keeping/.test(cf.mine) && cf.tid === TT, 'O8: the refused text waits in the conflicts ' + JSON.stringify(cf));
  check(await until(() => !!w1.document.querySelector('.cfpill')), 'O8: the conflicts button shows');
  w1.eval('conflictModal()'); await sleep(200);
  const md = [...w1.document.querySelectorAll('.modal')].pop();
  check(!!md && /Offline change not saved/.test(md.textContent) && /Lost words worth keeping/.test(md.textContent) && !!md.querySelector('[data-cf="copy"]'),
    'O8: the dialog names it, shows the text and offers Copy');
  md?.querySelector('[data-cf="server"]')?.click(); await sleep(200);
  check(!w1.eval('S.conflicts').some(c => c.field === 'rejected'), 'O8: dismissed');
  md?.querySelector('[data-m="close"]')?.click();

  // ================= O5 the queue waits until the server said who is logged in
  w1.__offline = true;
  await w1.eval(`api('PATCH', '/api/tasks/${T0}', {title: 'After the check'})`);
  w1.eval('OUT.me = null');
  w1.__offline = false;
  w1.dispatchEvent(new w1.Event('online'));
  check(await until(() => w1.eval('OUT.q.length') === 0), 'O5: the queue went out after the check');
  check(w1.eval('OUT.me') === w1.eval('S.me.id'), 'O5: the server said who it is');
  s = await st();
  check(s.tasks.find(t => t.id === T0)?.title === 'After the check', 'O5: the change arrived');

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  w1.close();
  console.log(`p2126_d_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
