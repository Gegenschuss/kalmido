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
  // 2.490.0 (#4018): no own row of icons any more: in a narrow column (container < 30rem) the icons take no room (display none) until hover / focus / a tap (.cacton)
  check(/@container cmain \(max-width:30rem\)\{[^}]*\.cacts\{position:absolute[^}]*display:none[^}]*\}[^}]*\.cm\.cacton \.cacts\{display:inline-flex/.test(css), '#3471: in a narrow column the comment icons wait for hover / tap (CSS)');

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
    // 2.1151.0 (#3835): on the phone the comment has no symbols, not at rest and not after a tap (was 2.490.0 #4018: a tap
    // showed them); they stay in the page for screen readers and the menu of the long press holds every one of them
    const hid = `(() => { const a = document.querySelector('#d-tl-items .cm[data-cid="${cm.id}"] .cacts'), r = a.getBoundingClientRect(); return r.width <= 1 && r.height <= 1; })()`;
    check(await ev(hid), '#3835: at rest the icons take no room at 360 px');
    await ev(`(() => { document.querySelector('#d-tl-items .cm[data-cid="${cm.id}"] .chead b').click(); return 1; })()`);
    check(await ev(hid), '#3835: a tap on the comment shows no icons either');
    const g = await ev(`(() => {
      const d = document.querySelector('#detail'), c = document.querySelector('#d-tl-items .cm[data-cid="${cm.id}"]'), h = c.querySelector('.chead');
      return {wide: d.scrollWidth - d.clientWidth, head: h.scrollWidth - h.clientWidth, n: c.querySelectorAll('.cacts .iconbtn').length, page: document.documentElement.scrollWidth <= innerWidth}; })()`);
    check(g && g.wide <= 0 && g.head <= 0 && g.page && g.n >= 4, '#3471: nothing of the comment reaches over the edge at 360 px, the buttons stay in the page ' + JSON.stringify(g));
    await ev(`(() => { const c = document.querySelector('#d-tl-items .cm[data-cid="${cm.id}"]'); cmCopyMenu(c.querySelector('[data-act="cm-copy"]'), c); return 1; })()`);
    const mi = await until(() => ev(`(() => { const l = [...document.querySelectorAll('#pop:not(.hidden) [role="menuitem"]')].map(b => b.textContent.trim()); return l.length ? l : null; })()`).catch(() => null));
    check(mi && ['Copy', 'Reply', 'Save as task', 'Edit', 'Delete'].every(x => mi.includes(x)), '#3835: the comment\'s long press menu holds Copy, Reply, Save as task, Edit, Delete ' + JSON.stringify(mi));
    await shot('p2421-360-comment.png');
  }, true);

  console.log(`p2421_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
