// kalmido-suite: fresh
// 2.655.0 D (#5045) tests: an answer of the server that arrives after the page's window was closed draws nothing.
// Own container (start.sh), jsdom, invented names only. The suite holds the answers of a window back, closes the window,
// then lets them through: before the fix the app went on with them (rel_load -> rel_draw -> $(), load() -> ld_go ->
// applyState) and threw at the missing document; tests/boot.js ignored that as "late app rejection" (exports.lateErrs counts it).
// - the relations of the open task (related.js rel_load), an answer held back past the close: no late error
// - a whole state load (core.js load), the same
// - control: the held answers really reached the closed window (else the check above proves nothing)
const {execFileSync} = require('child_process');
const path = require('path');
const boot = require('./boot');
const {B, login, sleep} = boot;
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (method, url, body, ck) => {
  const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined});
  return {...(await r.json().catch(() => ({}))), http: r.status};
};
const until = (fn, ms = 15000) => boot.until(fn, {timeout: ms, step: 50});
// the window's answers wait while w.__hold is set; w.__sent counts the requests sent meanwhile, w.__got the held answers that were let through
const hold = w => {
  const f = w.fetch; w.__got = 0; w.__sent = 0;
  w.fetch = (u, o) => { const p = f(u, o); const h = w.__hold; if (h) w.__sent++; return h ? p.then(r => h.then(() => { w.__got++; return r; })) : p; };
};
// starts `js` in a fresh window with its answers held back, closes the window, lets the answers through and waits until
// they arrived; then (bounded) for a late error. Returns {got, late}: the answers that arrived and the late errors seen.
const lateAfterClose = async (hash, js) => {
  const w = await boot.boot({user: 'alice', hash, setup: hold});
  let go; w.__hold = new Promise(r => { go = r; });
  w.eval(js);
  await until(() => w.__sent > 0, 5000);  // the request is on its way
  const n0 = boot.lateErrs;
  w.close();
  go();
  await until(() => w.__got > 0, 10000);
  await until(() => boot.lateErrs > n0, 2000);  // without the fix the error comes right after the answer; with it nothing comes
  return {got: w.__got, late: boot.lateErrs - n0};
};

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const A = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'}, A);
  const T = await call('POST', '/api/tasks', {title: 'Late answer probe'}, A);
  check(T.id > 0, `a task to open ${JSON.stringify(T)}`);

  // the relations of the open task: rel_load(id) draws into #d-rels when its answer arrives
  let r = await lateAfterClose('today', `S.sel = ${T.id}; rel_load(${T.id})`);
  check(r.got > 0, `relations: the held answer reached the closed window (${r.got})`);
  check(r.late === 0, `relations: no late app error after the window was closed (${r.late})`);

  // a whole state load: ld_go -> applyState reads document.documentElement
  r = await lateAfterClose('today', 'load()');
  check(r.got > 0, `state load: the held answer reached the closed window (${r.got})`);
  check(r.late === 0, `state load: no late app error after the window was closed (${r.late})`);

  console.log(`p2655_d_late: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
