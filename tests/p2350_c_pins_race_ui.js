// kalmido-suite:
// 2.350.0 C (#2806) UI tests: pinning people to the sidebar while a reload of the state crosses the save. Own container
// (start.sh), jsdom. A person WITHOUT an organisation (freelancer-matrix: sidebar) shares a list with three people.
// - a page state that predates the last pin (an overlapping reload) no longer sends an older whole list: the next pin
//   keeps the earlier one on the server (the pin goes as a single entry, set_delta)
// - a reload whose answers are crossed by a write three times in a row keeps the own pins (it used to put the older
//   settings back after the third try)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, idle} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2350C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 30000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const ALL = 'cal,timeline,matrix,habits,pomo,collab,stats,time,progress,agents,comments';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const AK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true}, AK);
  // the freelancer and three people, none of them in an organisation
  const mk = async u => (await call('POST', '/api/users', {username: u, display_name: u[0].toUpperCase() + u.slice(1), password: 'password123', email: u + '@example.com', orgs: []}, AK)).id;
  const FR = await mk('frida'), P = [await mk('pia'), await mk('paul'), await mk('pete')];
  CK = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: ALL});
  const st = await call('GET', '/api/state');
  check(st.me.id === FR && !(st.me.workspaces || []).length, 'frida has no organisation');
  const L = (await call('POST', '/api/lists', {name: 'Shared'})).id;
  for (const id of P) { const r = await call('PUT', `/api/lists/${L}/members`, {user_id: id, role: 'edit'}); check(r.http < 300, 'share the list with ' + id + ' ' + r.http); }
  const server = async () => String((await call('GET', '/api/state')).settings.side_people || '').split(',').filter(Boolean).map(Number).sort((a, b) => a - b).join(',');
  const want = ids => [...ids].sort((a, b) => a - b).join(',');

  const w = await boot({user: 'frida', hash: 'inbox'});
  check(await until(() => w.eval('teamPeople().length') === 3), 'the page knows the three people ' + w.eval('teamPeople().length'));

  // ================= a page state that predates the last pin
  w.__old = null;
  w.eval(`api('GET', '/api/state').then(j => { window.__old = j; })`);  // a reload on the way before the pin ...
  check(await until(() => w.__old), 'the older state is fetched');
  check(await w.eval(`sbp_pin('side_people', ${P[0]}, true, 'Pia')`), 'pin Pia');
  check(await until(async () => await server() === want([P[0]])), 'the server holds Pia');
  w.eval('applyState(window.__old)');  // ... arrives after the save (what an overlapping load puts in)
  check(w.eval(`sbp_ids('side_people').length`) === 0, 'the page state is the older one (no pins)');
  check(await w.eval(`sbp_pin('side_people', ${P[1]}, true, 'Paul')`), 'pin Paul');
  check(await until(async () => await server() === want([P[0], P[1]])), 'the server keeps Pia and adds Paul ' + await server());
  await w.eval('load()');
  check(await until(() => want(w.eval(`sbp_ids('side_people')`)) === want([P[0], P[1]])), 'after a reload the page shows both');
  await idle(w);

  // ================= a reload crossed by a write three times in a row
  const old = JSON.stringify(await w.eval(`api('GET', '/api/state')`));  // the state before pinning Pete
  check(await w.eval(`sbp_pin('side_people', ${P[2]}, true, 'Pete')`), 'pin Pete');
  check(await until(async () => await server() === want(P)), 'the server holds all three');
  const f0 = w.fetch; let n = 0, dots = 0;
  w.fetch = async (u, o = {}) => {
    if ((o.method || 'GET') !== 'GET' || !/\/api\/state(\?|$)/.test(String(u))) return f0(u, o);
    n++;
    await (await f0(u, o)).text();
    await w.eval(`rawFetch('PATCH', '/api/settings', {side_dots: '${dots++ % 2}'})`);  // a write ends while this answer is on the way
    return new Response(old, {status: 200, headers: {'Content-Type': 'application/json'}});  // an answer from before Pete's pin
  };
  await w.eval('load()');
  w.fetch = f0;
  check(n === 3, 'the reload tried three times ' + n);
  check(want(w.eval(`sbp_ids('side_people')`)) === want(P), 'the own pins win over an answer that predates them ' + w.eval(`S.settings.side_people`));
  check(await server() === want(P), 'the server still holds all three');
  await w.eval('load()');
  check(want(w.eval(`sbp_ids('side_people')`)) === want(P), 'the next reload agrees');
  await idle(w);
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
