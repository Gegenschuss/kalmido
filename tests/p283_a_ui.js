// 2.83.0 UI tests (part A, #1845), own container (start.sh, mode workspaces). jsdom, invented data only:
// - #1845 an organisation's view shows only what belongs to the organisation: Home, habits, review (+ statistics) and
//   notes are not in the sidebar, the phone's tab bar ("More" too) and the search; Time stays; Private shows them again;
//   an old link (#review, #habits) in an organisation's view switches quietly to Private and opens the page
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});  // KMT_NOSTART=1: a running app
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments', 'habits', 'review', 'stats', 'time']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,habits,review,stats,time,pomo,contracts,family'});
  const me = (await call('GET', '/api/state')).me.id;
  const ORG = (await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me})).id;
  check(!!ORG, 'organisation Alpha');
  const side = d => ({habits: !!d.querySelector('#side [data-go="habits"]'), review: !!d.querySelector('#side [data-mgside="review"]'),
    life: !!d.querySelector('#side [data-mgside="life"]'), time: !!d.querySelector('#side [data-mgside="time"]')});
  const pal = w => w.eval('palAll().map(x => x.id)');

  // ================= the organisation's view
  check((await call('PATCH', '/api/settings', {workspace: 'org:' + ORG})).http === 200, 'workspace = Alpha');
  let w = await boot({user: 'alice', hash: 'today', ls: {'tasks.ws': `"org:${ORG}"`}}); let d = w.document;
  await until(() => d.querySelector('#side .srow'), 40);
  check(w.eval('wsCur()') === 'org:' + ORG, '#1845: the organisation is shown: ' + w.eval('wsCur()'));
  let s = side(d);
  check(!s.habits && !s.review && !s.life, '#1845: no habits, review, home in the sidebar of the organisation: ' + JSON.stringify(s));
  check(s.time, '#1845: Time stays in the organisation\'s sidebar');
  check(!d.querySelector('#side [data-go="notes"]') && !d.querySelector('#side [data-go="stats"]'), '#1845: no notes / statistics row in the organisation');
  let ids = pal(w);
  check(!['v:habits', 'v:review', 'v:stats', 'v:life', 'v:family', 'v:a-review', 'v:a-life', 'a:newhabit'].some(x => ids.includes(x)), '#1845: the search offers no private modules: ' + ids.filter(x => x.startsWith('v:')).join(','));
  check(ids.includes('v:a-time') || ids.includes('v:time'), '#1845: the search still offers Time');
  // Private: all of it again
  await w.eval('wsSet("private")'); await sleep(200);
  s = side(d);
  check(s.habits && s.review && s.time, '#1845: Private shows habits, review, time again: ' + JSON.stringify(s));
  ids = pal(w);
  check(ids.includes('v:habits') && ids.includes('a:newhabit') && ids.includes('v:a-review'), '#1845: the search offers them in Private');
  w.close();

  // ================= the phone: tab bar and "More"
  await call('PATCH', '/api/settings', {workspace: 'org:' + ORG});
  w = await boot({user: 'alice', hash: 'today', mobile: true, ls: {'tasks.ws': `"org:${ORG}"`, 'tasks.tabbar': JSON.stringify(['s:today', 'm:habits', 'a:review', 'a:time'])}}); d = w.document;
  await until(() => d.querySelector('#tabs button'), 40);
  const tabs = () => [...d.querySelectorAll('#tabs [data-go]')].map(x => x.dataset.go);
  check(!tabs().includes('habits') && !tabs().some(g => g === 'review' || g === 'stats'), '#1845: no habits / review tab in the organisation: ' + tabs());
  check(tabs().some(g => g === 'time' || g === 'pomo'), '#1845: the Time tab stays: ' + tabs());
  const more = w.eval('tabOverflow().more.map(t => t.mod || t.id)');
  check(!more.some(m => ['habits', 'review', 'stats', 'life'].includes(m)), '#1845: "More" offers no private modules: ' + more);
  check(JSON.parse(w.localStorage.getItem('tasks.tabbar')).includes('m:habits'), '#1845: the pinned tabs stay pinned (only hidden)');
  await w.eval('wsSet("private")'); await sleep(200);
  check(tabs().includes('habits') && tabs().some(g => g === 'review' || g === 'stats'), '#1845: Private shows the habits / review tabs again: ' + tabs());
  w.close();

  // ================= an old link in the organisation's view: quietly to Private, then the page
  for (const h of ['review', 'habits']) {
    await call('PATCH', '/api/settings', {workspace: 'org:' + ORG});
    w = await boot({user: 'alice', hash: h, ls: {'tasks.ws': `"org:${ORG}"`}}); d = w.document;
    await until(() => w.eval('S.route && S.route.mod') === h, 40);
    check(w.eval('S.route.mod') === h && w.eval('wsCur()') === 'private', `#1845: #${h} in the organisation opens in Private: ${w.eval('S.route.mod')} / ${w.eval('wsCur()')}`);
    check(!!d.querySelector('#view') && d.querySelector('#view').textContent.trim().length > 0, `#1845: #${h} is not an empty page`);
    check(!d.querySelector('#toast.err, .toast.err'), `#1845: #${h} shows no error`);
    await until(async () => ((await call('GET', '/api/state')).settings || {}).workspace === 'private', 30);
    check(((await call('GET', '/api/state')).settings || {}).workspace === 'private', `#1845: #${h}: the server knows Private`);
    w.close();
  }

  console.log(`p283_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
