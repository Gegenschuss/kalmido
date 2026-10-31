// kalmido-suite: fresh
// 2.421.0 UI test, own container (start.sh), Firefox (real layout):
// #3471 a phone 360 px wide (touch): the action buttons of a comment (Reply, Copy, Save as task, Edit, Delete) wrap into an own
//       right-aligned row under name and time instead of reaching 16 px over the edge of the task detail; all buttons stay
const {execFileSync} = require('child_process');
const path = require('path');
const {B, login, until} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2421_ui', check, shots: 'P2421_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };

(async () => {
  const r = await until(() => fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice Longername', password: 'password123', wizard: true, lang: 'en'})}).catch(() => null));
  check(r && r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab'});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  const L = (await call('POST', '/api/lists', {name: 'Shared work', org_id: ORG})).id;
  const T = (await call('POST', '/api/tasks', {title: 'Phone task', list_id: L})).id;
  const cm = await call('POST', `/api/tasks/${T}/comments`, {body: 'A comment of mine'});
  check(cm.id > 0, 'a comment ' + cm.status);

  // static: the rule is in the style sheet
  const css = require('./boot').allCssSync();
  check(/@media \(max-width:400px\)\{[^}]*\.chead\{flex-wrap:wrap/.test(css), '#3471: the comment head may wrap on narrow screens (CSS)');

  await firefox(async o => {
    const {cmd, ev, ctx, shot, nav} = o;
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 360, height: 800}});
    await nav(B + '#l/' + L);
    check(await until(() => ev(`!!document.querySelector('#top h1')`).catch(() => false)), 'the list is drawn');
    await ev(`(() => { openDetail(${T}); return 1; })()`);
    check(await until(() => ev(`!!document.querySelector('#d-tl-items .cm[data-cid="${cm.id}"] .cacts .iconbtn')`).catch(() => false)), 'the comment with its buttons');
    const g = await ev(`(() => {
      const d = document.querySelector('#detail'), dr = d.getBoundingClientRect(), c = document.querySelector('#d-tl-items .cm[data-cid="${cm.id}"]');
      const h = c.querySelector('.chead'), a = c.querySelector('.cacts'), ar = a.getBoundingClientRect(), nr = h.querySelector('b').getBoundingClientRect();
      return {wide: d.scrollWidth - d.clientWidth, head: h.scrollWidth - h.clientWidth, right: Math.round(ar.right - dr.right),
        below: ar.top >= nr.bottom - 1, n: a.querySelectorAll('.iconbtn').length, page: document.documentElement.scrollWidth <= innerWidth}; })()`);
    check(g && g.wide <= 0 && g.head <= 0 && g.right <= 0 && g.page, '#3471: nothing of the comment reaches over the edge at 360 px ' + JSON.stringify(g));
    check(g && g.below, '#3471: the buttons are an own row under name and time ' + JSON.stringify(g));
    check(g && g.n >= 4, '#3471: no button left out (Reply, Copy, Save as task, Edit, Delete) ' + JSON.stringify(g));
    await shot('p2421-360-comment.png');
  }, true);

  console.log(`p2421_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
