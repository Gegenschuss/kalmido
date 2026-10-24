// 2.298.0 B (#3185): less text in tasks, projects, views, calendar, sidebar. Own container (start.sh). Firefox 390 x 844 touch:
// project status and timeline (screenshots with P2298B_SHOTS) and the reduced texts / icon labels / hidden hints.
// freelancer-matrix: tasks
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2298_b_lesstext_ui', check, shots: 'P2298B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2298B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const ds = n => { const d = new Date(Date.now() + n * 864e5); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
const wait = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const P1 = (await call('POST', '/api/lists', {name: 'Relaunch', view: 'timeline', kind: 'project'})).id;
  const P2 = (await call('POST', '/api/lists', {name: 'Website', kind: 'project'})).id;
  for (const [t, l, due, start] of [['Design', P1, ds(3), ds(-2)], ['Build', P1, ds(9), ds(4)], ['Launch', P1, null, null], ['Copy', P2, ds(-1), null], ['Photos', P2, ds(5), null]])
    await call('POST', '/api/tasks', {title: t, list_id: l, due, ...(start ? {start} : {})});
  await firefox(async o => {
    const {cmd, ev, ctx, shot, nav} = o;
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + '#overview');
    check(await wait(ev, `!!document.querySelector('.ovw .sttiles')`), '390: the project status page shows');
    await sleep(500);
    await shot('p2298b-390-status.png');
    await nav(B + '#l/' + P1);
    check(await wait(ev, `!!document.querySelector('.tl-foot')`), '390: the timeline shows');
    await sleep(500);
    await shot('p2298b-390-timeline.png');
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
