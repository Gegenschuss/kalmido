// 2.619.0 UI test, part D (#3890): reload waves. jsdom, own container (start.sh):
// kalmido-suite: fresh
// - a window that just started takes the areas of its state (lva) as those of its first poll: a change right after the start
//   comes as a delta, not as a second whole state (was: every window loaded its whole state once, all at the same time
//   during writes elsewhere)
// - an update of the server: the reload by itself waits a random part of VER_SPREAD_MS (the windows do not all reload in the
//   same poll); the bar shows meanwhile; once the wait is over it reloads
// Every wait is on a real state (the app's own change poll, held where a step needs it).
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

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const L = (await call(CA, 'POST', '/api/lists', {name: 'Garden plan'})).id;
  const T = (await call(CA, 'POST', '/api/tasks', {title: 'Order the seeds', list_id: L})).id;
  check(L && T, 'a list with a task');
  const w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  check(await until(() => d.querySelector(`#view .trow[data-id="${T}"]`)), 'the list shows');
  const caught = () => until(async () => !!w.eval('!!S.lpA && !td_polling') && (await call(CA, 'GET', '/api/version')).v === w.eval('S.v'));
  check(await caught(), 'the page is settled');

  // ================= the first poll after a start
  // held poll; the window as right after its start: no poll areas yet, then its start load
  check(await until(() => w.eval('td_polling ? false : (td_polling = true)')), 'the poll held');
  w.eval('S.lpA = null; S.lpUnk = false; S.lpPend.clear(); window.__ld = 0; load().then(() => { window.__ld = 1; })');
  check(await until(() => w.__ld === 1), 'the start load is done');
  const sv = await call(CA, 'GET', '/api/version');
  check(w.eval('!!S.lpA') && JSON.stringify(w.eval('S.lpA')) === JSON.stringify(sv.a), `#3890: the state brought the areas (lva) ${JSON.stringify(w.eval('S.lpA'))} vs ${JSON.stringify(sv.a)}`);
  const st0 = w.eval('S.lpN.state'), dl0 = w.eval('S.lpN.delta');
  // a write elsewhere before the first poll (another device of alice)
  const T2 = (await call(CA, 'POST', '/api/tasks', {title: 'Build the raised bed', list_id: L})).id;
  check(T2, 'a task from another device');
  w.eval('td_polling = false');
  check(await until(() => d.querySelector(`#view .trow[data-id="${T2}"]`)), '#3890: the new task shows');
  check(w.eval('S.lpN.state') === st0 && w.eval('S.lpN.delta') > dl0,
    `#3890: the first poll took a delta, not the whole state again ${JSON.stringify(w.eval('S.lpN'))} (state was ${st0}, delta ${dl0})`);

  // ================= an update of the server: the reload by itself spread
  check(await until(() => w.eval('td_polling ? false : (td_polling = true)')), 'the poll held again');
  const appVer = d.querySelector('meta[name="kalmido-version"]')?.content;
  w.eval(`verReload = () => { window.__rl = (window.__rl || 0) + 1; }; VER_SPREAD_MS = 600000; document.activeElement?.blur?.(); verIdle = Date.now() - 60000; sessionStorage.removeItem('kalmido-reloaded'); window.__rl = 0`);
  w.eval(`verCheck('99.1.0'); verCheck('99.1.0'); verCheck('99.1.0')`);
  check(!w.__rl && d.querySelector('#newver'), `#3890: quiet, the new version reported three times: no reload yet, the bar shows (reloads ${w.__rl})`);
  check(w.eval('S.verSpread?.v === "99.1.0" && S.verSpread.at > Date.now()'), '#3890: the window waits its own random time');
  w.eval('S.verSpread.at = Date.now() - 1; verCheck("99.1.0")');
  check(w.__rl === 1, `#3890: once its time has come it reloads by itself (${w.__rl})`);
  w.eval(`S.serverVer = '${appVer}'; verCheck('${appVer}'); td_polling = false`);
  w.close();

  console.log(`p2619_d_reload_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
