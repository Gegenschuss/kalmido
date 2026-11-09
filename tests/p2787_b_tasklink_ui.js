// kalmido-suite: fresh
// 2.787.0 (#5438) UI test (jsdom), fresh DB: a task opened by its address on a fresh load (#t/<id>, also #reply/<id>) stands over
// its own project (list entry l/<id>, row marked), not over the empty Inbox; Back stays in the project (the address is the
// list's); inside the running app a link keeps the view it comes from.
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const until = (fn, ms) => require('./boot').until(fn, {timeout: ms || 15000, step: 80});

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const L = (await call('POST', '/api/lists', {name: 'Garden project'})).id;
  const T = (await call('POST', '/api/tasks', {list_id: L, title: 'Plant the roses'})).id;
  await call('POST', '/api/tasks', {list_id: L, title: 'Mow the lawn'});
  for (const [hash, what] of [[`t/${T}`, '#t/<id>'], [`reply/${T}`, '#reply/<id>']]) {
    const w = await boot({user: 'alice', hash}), d = w.document;
    check(await until(() => w.eval('S.sel') === T && d.querySelector('#detail.open')), `${what}: the task is open`);
    check(w.eval('S.route.key') === 'l:' + L, `${what}: behind it the own project, not the Inbox: ` + w.eval('S.route.key'));
    check(await until(() => d.querySelector(`.trow.sel[data-id="${T}"]`)), `${what}: its row is marked`);
    check(/Garden project/.test(d.querySelector('#main, #app')?.textContent || '') && !d.querySelector('#main .empty-inbox'), `${what}: the project name stands in the view`);
    check(w.location.hash === '#l/' + L, `${what}: the entry under the task is the project's: ` + w.location.hash);
    w.close();
  }
  // inside the running app the view stays (Today stays Today)
  const w = await boot({user: 'alice', hash: 'today'}), d = w.document;
  await sleep(400);
  w.eval(`go('t/${T}')`);
  check(await until(() => w.eval('S.sel') === T), 'in-app link: the task opens');
  check(w.eval('S.route.key') === 'today', 'in-app link: the view it comes from stays: ' + w.eval('S.route.key'));
  w.close();
  check(!errs.length, 'jsdom: no JS errors ' + errs.join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
