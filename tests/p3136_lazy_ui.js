// kalmido-suite: fresh
// 2.369.2 (#3136) UI: the start set of a big account in the browser, own container (start.sh with KALMIDO_STATE_LAZY_MIN=20,
// so a few tasks make the account "big"). jsdom. Invented texts only.
// freelancer-matrix: tasks
// - the start (Today) loads only the start set: the due tasks are there, the undated ones of the other lists not; the
//   sidebar counts them anyway (the server's lz.counts)
// - opening a list loads its tasks (one GET /api/state/lists), the view shows all of them; opening it again loads nothing
// - a task opened by its address whose list is not loaded: the list comes, the panel shows the task
// - a change in a list not loaded (another window / device): the count follows with the live update (delta lzc)
// - a view not known to need less (the calendar) loads every list; the next /api/state asks for all (lzl=all)
// - a new window keeps the lists opened last whole (LS lzOpen)
// - a person without an organisation (alice: the first account, no organisation)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, B, login, until: until0} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P3136UI_NOSTART && !process.env.KMT_NOSTART) {
  execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: `${process.env.EXTRA || ''} -e KALMIDO_STATE_LAZY_MIN=20`.trim()}});
}
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = (fn, ms = 20000) => until0(fn, {timeout: ms, step: 150});
// the window's GET /api/state/lists requests (their ids)
function net(w) {
  const f0 = w.fetch; w.__lz = [];
  w.fetch = (u, o = {}) => { const s = String(u); if (/\/api\/state\/lists\?/.test(s)) w.__lz.push(s.split('ids=')[1]); return f0(u, o); };
}
const rows = w => w.document.querySelectorAll('#view .trow[data-id]').length;
const pend = (w, id) => w.eval(`!!S.lz && S.lz.pending.has(${id})`);

(async () => {
  await until(async () => (await fetch(B + 'sw.js').catch(() => null))?.ok);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const st0 = await call('GET', '/api/state');
  check(!(st0.me.workspaces || []).length, 'alice works without an organisation');
  const L = {};
  for (const n of ['Garten', 'Keller', 'Dachboden']) L[n] = (await call('POST', '/api/lists', {name: n})).id;
  const today = new Date().toLocaleDateString('sv-SE', {timeZone: 'Europe/Berlin'});  // the server's day (TZ of start.sh)
  const T = {};
  for (const n of Object.keys(L)) for (let i = 1; i <= 12; i++) T[`${n}${i}`] = (await call('POST', '/api/tasks', {title: `${n} Schritt ${i}`, list_id: L[n]})).id;
  const due1 = (await call('POST', '/api/tasks', {title: 'Keller heute fegen', list_id: L.Keller, due: today})).id;
  const due2 = (await call('POST', '/api/tasks', {title: 'Keller heute lueften', list_id: L.Keller, due: today})).id;
  check(due1 > 0 && due2 > 0, 'setup: 38 tasks in three lists');

  // ================= start on Today: the start set
  let w = await boot({user: 'alice', hash: 'today', ls: {'tasks.lzOpen': null}});
  net(w);
  check(await until(() => w.eval('!!S.lz')), 'the start answer is the start set (S.lz)');
  check(pend(w, L.Garten) && pend(w, L.Keller) && pend(w, L.Dachboden), 'the three lists are pending');
  check(w.eval(`S.tasks.has(${due1}) && S.tasks.has(${due2})`), 'the tasks due today are there');
  check(!w.eval(`S.tasks.has(${T.Garten1})`), 'an undated task of another list is not loaded');
  check(await until(() => rows(w) >= 2), 'Today shows the two due tasks: ' + rows(w));
  check(w.eval(`counts().lists[${L.Garten}]`) === 12 && w.eval(`counts().lists[${L.Keller}]`) === 14, 'the sidebar counts the lists not loaded (server counts): ' + w.eval(`JSON.stringify([counts().lists[${L.Garten}], counts().lists[${L.Keller}]])`));
  check(w.eval(`counts().all`) === 38, 'All counts every open task: ' + w.eval('counts().all'));
  check(w.__lz.length === 0, 'Today loads no list: ' + JSON.stringify(w.__lz));

  // ================= opening a list loads it, once
  w.location.hash = '#l/' + L.Garten;
  check(await until(() => !pend(w, L.Garten) && rows(w) === 12), 'the list Garten shows its 12 tasks after loading: ' + rows(w));
  check(w.__lz.length === 1 && w.__lz[0] === String(L.Garten), 'one GET /api/state/lists for it: ' + JSON.stringify(w.__lz));
  check(w.eval(`counts().lists[${L.Garten}]`) === 12, 'its count stays 12 (now counted locally)');
  check(JSON.parse(w.localStorage.getItem('tasks.lzOpen') || '[]').includes(L.Garten), 'the device remembers the list (lzOpen)');
  w.location.hash = '#today';
  await until(() => w.eval("S.route.key === 'today'"));
  w.location.hash = '#l/' + L.Garten;
  await until(() => w.eval(`S.route.key === 'l:${L.Garten}'`) && rows(w) === 12);
  check(w.__lz.length === 1, 'opened again: nothing loaded again: ' + JSON.stringify(w.__lz));

  // ================= a task opened by its address, its list not loaded
  w.location.hash = '#t/' + T.Dachboden3;
  check(await until(() => w.eval(`S.sel === ${T.Dachboden3} && S.tasks.has(${T.Dachboden3})`) && !w.document.querySelector('#detail').classList.contains('hidden')
    && /Dachboden Schritt 3/.test(w.document.querySelector('#detail').textContent)), 'the task panel shows a task of a list not loaded');
  check(!pend(w, L.Dachboden), 'its list was loaded with it');

  // ================= a change in a list not loaded: the count follows
  check(pend(w, L.Keller), 'Keller still pending');
  await call('POST', '/api/tasks', {title: 'Keller neu', list_id: L.Keller});
  check(await until(() => w.eval(`counts().lists[${L.Keller}]`) === 15), 'the live update brings the new count of Keller: ' + w.eval(`counts().lists[${L.Keller}]`));

  // ================= the calendar: every list
  w.location.hash = '#cal';
  check(await until(() => w.eval('!!S.lz && S.lz.pending.size === 0')), 'the calendar loads every list');
  check(w.eval('lzQuery()') === 'lz=1&lzl=all', 'the next /api/state asks for all: ' + w.eval('lzQuery()'));
  check(w.eval(`counts().lists[${L.Keller}]`) === 15 && w.eval('counts().all') === 39, 'the counts after loading all: ' + w.eval('counts().all'));
  w.close();

  // ================= a new window keeps the lists opened last whole
  const w2 = await boot({user: 'alice', hash: 'today', ls: {'tasks.lzOpen': JSON.stringify([L.Dachboden])}});
  check(await until(() => w2.eval('!!S.lz')), 'second window: the start set');
  check(!pend(w2, L.Dachboden) && w2.eval(`S.tasks.has(${T.Dachboden7})`), 'the list opened last on this device is loaded whole at the start');
  check(pend(w2, L.Garten), 'the other lists stay pending');
  w2.close();

  console.log(F.length ? `FAILED ${F.length}` : `all ok (${ok} checks)`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e.stack); process.exit(1); });
