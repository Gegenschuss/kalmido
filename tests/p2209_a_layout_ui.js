// 2.209.0 A (#2772) UI tests, own container (start.sh, isolated test database): short of room the chat, the task panel and
// the list get narrower first (list down to 320 px), the chat steps aside next, the sidebar floats last.
// jsdom: the order itself (lay2209 with plain numbers), a 1440 px window with a 44 rem chat + an open task keeps the sidebar
// (the stored widths stay, only the widths in use shrink and come back on a wide window), a very narrow window still floats
// the sidebar, a phone is unchanged. Firefox: the 1440 x 900 window measured (sidebar fixed, list >= 320 px, no overflow)
// and ~900 px (drawer). Screenshots with P2209A_SHOTS=<dir>.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2209_a_layout_ui', check, shots: 'P2209A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const width = (w, px) => Object.defineProperty(w, 'innerWidth', {configurable: true, value: px});

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['agents', 'comments']});
  await call('PATCH', '/api/settings', {features: 'agents,comments', lang: 'en', tour: 'done'});
  const ag = await call('POST', '/api/admin/agents', {scopes: ['write'], username: 'claude', display_name: 'Claude'});
  const AG = ag.id;
  const L = (await call('POST', '/api/lists', {name: 'Website', kind: 'project'})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: AG, role: 'edit'});
  const T = (await call('POST', '/api/tasks', {title: 'Landing page', list_id: L})).id;

  // ================= jsdom: the order with plain numbers (px; sidebar 240, bar of sidebar B 72, task 408, mins 320)
  let w = await boot({user: 'alice', hash: 'l/' + L, setup: x => width(x, 1440)}), d = w.document;
  const lay = o => w.eval(`lay2209(${JSON.stringify({bar: 72, barRail: 72, side: 240, det: 408, detMin: 320, chat: 0, chatMin: 320, fold: false, ...o})})`);
  let r = lay({W: 1440, chat: 576});
  const list = (W, x, fixed) => W - fixed - x.det - x.chat;
  check(!r.rail && !r.yieldC && r.sq && r.chat < 576 && r.det < 408 && list(1440, r, 312) >= 319.5 && list(1440, r, 312) < 420, '1440 + chat 44 rem + task: everything narrower, the sidebar stays ' + JSON.stringify(r));
  r = lay({W: 1920, chat: 704});
  check(!r.rail && !r.yieldC && !r.sq && r.chat === 704 && r.det === 408, '1920: nothing shrinks ' + JSON.stringify(r));
  r = lay({W: 1100, chat: 416, barRail: 0});
  check(!r.rail && r.yieldC && r.chat === 0, '1100: the minimums do not fit, the chat steps aside before the sidebar floats ' + JSON.stringify(r));
  r = lay({W: 904, barRail: 0});
  check(r.rail && !r.yieldC && r.det === 408, '904 + task: the sidebar floats (last step), the task keeps its width ' + JSON.stringify(r));
  r = lay({W: 1440, fold: true});
  check(r.rail && !r.sq, 'sidebar hidden by hand (#2607): stays a drawer ' + JSON.stringify(r));

  // ================= jsdom: 1440 px, chat 44 rem + open task
  w.close();
  w = await boot({user: 'alice', hash: 'l/' + L, setup: x => width(x, 1440), ls: {'tasks.pw.chat': '44'}}); d = w.document;
  w.eval(`chatOpen(${AG})`); await sleep(400);
  w.eval(`openDetail(${T})`); await sleep(300);
  const vars = () => ({det: d.documentElement.style.getPropertyValue('--detW'), chat: d.documentElement.style.getPropertyValue('--chatW'), rail: d.querySelector('#app').classList.contains('side-rail'), yld: d.body.classList.contains('chat-yield')});
  let v = vars();
  check(!v.rail && !v.yld && parseFloat(v.det) < 25.5 && parseFloat(v.det) >= 20 && parseFloat(v.chat) < 36 && parseFloat(v.chat) >= 20, '1440: sidebar fixed, chat + task narrower ' + JSON.stringify(v));
  check(w.__store['tasks.pw.chat'] === '44' && !('tasks.pw.det' in w.__store), '1440: the stored widths stay');
  width(w, 1920); w.eval('fitLayout()');
  v = vars();
  check(!v.rail && v.det === '25.5rem' && v.chat === '44rem', '1920: the stored widths come back ' + JSON.stringify(v));
  // dragging while shrunk: the edge stays where it was let go (the stored width is worked out back)
  width(w, 1440); w.eval('fitLayout()');
  const e0 = parseFloat(vars().det);
  w.eval(`panelSet('det', ${e0 + 2})`);
  check(Math.abs(parseFloat(vars().det) - (e0 + 2)) <= .3 && +w.__store['tasks.pw.det'] > 25.5, `1440: 2 rem wider while shrunk shows 2 rem wider (${e0} -> ${vars().det}, stored ${w.__store['tasks.pw.det']})`);
  w.eval(`panelSet('det', null)`);
  width(w, 904); w.eval('fitLayout()');
  v = vars();
  check(v.rail && d.querySelector('#top .menu'), '904: no room even at the minimums: the sidebar floats, menu button ' + JSON.stringify(v));
  w.close();

  // ================= jsdom: phone unchanged
  w = await boot({user: 'alice', hash: 'l/' + L, mobile: true}); d = w.document;
  w.eval(`openDetail(${T})`); await sleep(300);
  check(!d.querySelector('#app').classList.contains('side-rail') && d.documentElement.style.getPropertyValue('--detW') === '25.5rem' && !d.body.classList.contains('chat-yield'), 'phone: no drawer class, no shrinking');
  w.close();

  // ================= Firefox: 1440 x 900 with chat 44 rem + task, then ~900 px
  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); localStorage.setItem('tasks.pw.chat', '44'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); await sleep(700); };
  const LAY = `(() => { const r = s => { const e = document.querySelector(s); if (!e || !e.offsetWidth || getComputedStyle(e).display === 'none') return null; const b = e.getBoundingClientRect(); return {l: Math.round(b.left), r: Math.round(b.right), w: Math.round(b.width)}; };
    return {main: r('#main'), det: r('#detail'), chat: r('#achat:not(.hidden)'), side: r('#side'), over: document.documentElement.scrollWidth - innerWidth, rail: document.querySelector('#app').classList.contains('side-rail'), yld: document.body.classList.contains('chat-yield')}; })()`;
  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    check(await ffLogin({ev, nav}) === 200, 'Firefox: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await nav(B + '#l/' + L); await ready(ev);
    await ev(`(() => { chatOpen(${AG}); return 1; })()`); await sleep(1200);
    await ev(`(() => { openDetail(${T}); return 1; })()`); await sleep(1000);
    const a = await ev(LAY);
    check(a.side && a.main && a.det && a.chat && !a.rail && !a.yld && a.main.w >= 318 && a.over <= 0 && a.det.r <= a.chat.l + 1 && a.side.r <= a.main.l + 1, '1440: sidebar | list | task | chat side by side, list >= 320 px ' + JSON.stringify(a));
    await shot('p2209a-1440-chat-task.png');
    await ev(`(() => { chatClose(); return 1; })()`); await sleep(400);  // below 1000 px the chat is a full page of its own
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 904, height: 900}}); await sleep(900);
    await ev(`(() => { openDetail(${T}); return 1; })()`); await sleep(900);
    const b = await ev(LAY);
    check(b.rail && b.det && b.over <= 0, '904: the sidebar floats as the drawer ' + JSON.stringify(b));
    await shot('p2209a-904-drawer.png');
  });

  console.log(`p2209_a_layout_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
