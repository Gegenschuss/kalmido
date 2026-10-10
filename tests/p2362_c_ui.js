// 2.36.2 UI tests, part C (#1135 #1139 #1130 #1146), own container (start.sh). jsdom:
// - list marks (#1135): with "Line" (default) the open list's header shows the line icon and the name without its leading
//   emoji, the list chip of a task row the same; the move menu and search show the mark; with "Emoji" all as before
// - the sidebar's right-click menu of a list starts with the colour row (9 colours + none); a tap sets the colour
// - shared (#1139): person icon / robot / both, with a label; not shared = nothing; the agents' typing line has the robot
// - "More" on the phone offers Office & finance when the module is on (#1146)
// Firefox (mouse, 1440 then 390): share symbols visible without hover; the icon grid of the list dialog, the calendar
// window's switches and "Per list" and the calendar lines of "Plan the day" are 44 px on the phone; screenshots
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2362_c_ui', check, shots: 'P2362C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const FEAT = 'cal,events,comments,collab,office,agents';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const AG = (await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write'], username: 'claude', display_name: 'Claude'})).id;
  check(BOB && AG, 'a person and an agent');
  const L_HOME = (await call('POST', '/api/lists', {name: '\u{1F3E0} Home'})).id;
  const L_AG = (await call('POST', '/api/lists', {name: 'Agent work'})).id;
  const L_BOTH = (await call('POST', '/api/lists', {name: 'Team'})).id;
  const L_NONE = (await call('POST', '/api/lists', {name: 'Private'})).id;
  await call('PUT', `/api/lists/${L_HOME}/members`, {user_id: BOB, role: 'edit'});
  await call('PUT', `/api/lists/${L_AG}/members`, {user_id: AG, role: 'edit'});
  await call('PUT', `/api/lists/${L_BOTH}/members`, {user_id: BOB, role: 'edit'});
  await call('PUT', `/api/lists/${L_BOTH}/members`, {user_id: AG, role: 'edit'});
  const today = new Date().toISOString().slice(0, 10);
  await call('POST', '/api/tasks', {title: 'Water the plants', list_id: L_HOME, due: today});
  await call('POST', '/api/evcals', {name: 'Mine', color: '#60a5fa'});

  // ================= jsdom: the open list with "Line" (default)
  let w = await boot({hash: 'l/' + L_HOME}); let d = w.document;
  await until(() => d.querySelector('#top h1 .ht'));
  check(d.querySelector('#top h1 .ht')?.textContent === 'Home', 'line mode: the header shows the name without the emoji: ' + d.querySelector('#top h1 .ht')?.textContent);
  check(!!d.querySelector('#top h1 .lic.h svg.i'), 'line mode: the header shows the line icon');
  check(!/\u{1F3E0}/u.test(d.querySelector('#top h1')?.textContent || ''), 'line mode: no emoji in the header');
  w.location.hash = '#today'; await sleep(600);
  const lst = await until(() => d.querySelector('#view .trow .meta .lst'));
  check(!!lst && lst.textContent === 'Home' && !!lst.querySelector('.lic'), 'line mode: the list chip in the task row: mark + name without emoji: ' + lst?.outerHTML?.slice(0, 200));
  check(w.eval(`lname(listById(${L_HOME}))`) === 'Home' && w.eval(`listById(${L_HOME}).name`) === '\u{1F3E0} Home', 'the stored name keeps its emoji, only the display drops it');
  // the move menu of a task: the lists with their marks
  w.eval(`menu(document.body, S.lists.filter(l => !l.archived).map(l => ({label: lname(l), icon: 'list', lic: l, fn() {}})))`);
  await sleep(100);
  const mv = [...d.querySelectorAll('.menu-list button')].find(b => /^Home$/.test(b.textContent.trim()));
  check(!!mv && !!mv.querySelector('.lic.mlic') && !/\u{1F3E0}/u.test(mv.textContent), 'menus with lic: mark instead of the emoji');
  w.eval('closePop()');
  // sidebar: shared symbols by kind
  const shr = id => d.querySelector(`#side .srow[data-list="${id}"] .shr.shk`);
  await until(() => shr(L_HOME));
  check(!!shr(L_HOME)?.querySelector('svg.i:not(.lbot)') && !shr(L_HOME)?.querySelector('.lbot'), 'shared with a person: the person icon only');
  check(!!shr(L_AG)?.querySelector('.lbot') && shr(L_AG)?.querySelectorAll('svg.i').length === 1, 'shared with an agent: the robot only');
  check(shr(L_BOTH)?.querySelectorAll('svg.i').length === 2 && !!shr(L_BOTH)?.querySelector('.lbot'), 'shared with both: both symbols');
  check(!shr(L_NONE), 'not shared: no symbol');
  check(/1 person/.test(shr(L_BOTH)?.getAttribute('aria-label') || '') && /Claude/.test(shr(L_BOTH)?.getAttribute('aria-label') || ''), 'the label names people and agent: ' + shr(L_BOTH)?.getAttribute('aria-label'));
  check(/Claude/.test(shr(L_AG)?.getAttribute('title') || ''), 'tooltip of the agent list: ' + shr(L_AG)?.getAttribute('title'));
  // the colour row of the sidebar menu (right-click)
  const row = d.querySelector(`#side .srow[data-list="${L_NONE}"]`);
  row.dispatchEvent(new w.MouseEvent('contextmenu', {bubbles: true, cancelable: true}));
  await until(() => d.querySelector('.menu-list .mquick.mcols'));
  const cols = [...d.querySelectorAll('.menu-list .mquick.mcols button.mcol')];
  check(cols.length === 10 && cols[0].classList.contains('on'), 'right-click: the colour row with 9 colours + none (none is on): ' + cols.length);
  check(!!d.querySelector('.menu-list [role="menuitem"]:not(.mcol)'), 'the rest of the list menu stays below');
  cols[3].click();
  const col = await until(async () => (await call('GET', '/api/state')).lists.find(l => l.id === L_NONE)?.color);
  check(col === w.eval('LCOLORS[3]'), 'a tap sets the list colour: ' + col);
  // the typing line of an agent
  check(!!new w.DOMParser().parseFromString(w.typingHtml([{name: 'Claude', typing: 0, busy: false}], 'chat-typing'), 'text/html').querySelector('.ttx svg.lbot'), 'typing line: robot before the agent');
  // "More" on the phone: Office & finance
  check(w.tabOverflow().more.some(t => t.id === 'office') || w.tabOverflow().shown.some(t => t.id === 'office'), 'More offers Office & finance: ' + w.tabOverflow().more.map(t => t.id).join(','));
  // "Emoji": as before
  await call('PATCH', '/api/settings', {side_icons: 'emoji'});
  w.close();
  w = await boot({hash: 'l/' + L_HOME}); d = w.document;
  await until(() => d.querySelector('#top h1 .ht'));
  check(/\u{1F3E0}/u.test(d.querySelector('#top h1 .ht')?.textContent || '') && !d.querySelector('#top h1 .lic'), 'emoji mode: the header as before (emoji in the name, no line icon): ' + d.querySelector('#top h1 .ht')?.textContent);
  w.close();
  await call('PATCH', '/api/settings', {side_icons: 'line'});

  // ================= Firefox: mouse, 1440 then 390
  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"dark"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#side .srow[data-list]')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  // layout sizes (offsetWidth / offsetHeight): a dialog's opening animation scales its box for a moment
const sz = sel => `[...document.querySelectorAll(${JSON.stringify(sel)})].filter(e => e.offsetWidth).map(e => [e.offsetWidth, e.offsetHeight])`;
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o;
    check(await ffLogin(o) === 200, 'firefox: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await o.nav(B + '#l/' + L_HOME); await ready(ev);
    const vis = await ev(`[${L_HOME}, ${L_AG}, ${L_BOTH}].map(id => { const e = document.querySelector('#side .srow[data-list="' + id + '"] .shr.shk'); return e ? +getComputedStyle(e).opacity : -1; })`);
    check(vis.every(x => x >= 0.99), '1440: share symbols visible without hover ' + JSON.stringify(vis));
    const blue = await ev(`getComputedStyle(document.querySelector('#side .shr.shk .lbot')).color`);
    check(/143, 168, 232/.test(blue), '1440 dark: the robot in the calm blue ' + blue);
    await shot('p2362c-1440-sidebar.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await sleep(800);
    // the icon grid of the list dialog
    await ev(`(() => { listModal(${L_HOME}); return 1; })()`); await sleep(1500);
    await ev(`(() => { document.querySelector('#l-emogrid')?.classList.remove('hidden'); return 1; })()`); await sleep(300);
    const g = await ev(sz('#l-emogrid button'));
    const gcs = await ev(`(() => { const b = document.querySelector('#l-emogrid button'); if (!b) return null; const c = getComputedStyle(b); return [c.height, c.minHeight, c.maxHeight, c.boxSizing, getComputedStyle(b.parentElement).gridTemplateColumns.slice(0, 40)]; })()`);
    check(g.length > 10 && g.every(([x, y]) => x >= 44 && y >= 44), '390: icon grid cells >= 44 px ' + JSON.stringify(g.filter(([x, y]) => x < 44 || y < 44).slice(0, 6)) + ' n=' + g.length + ' ' + JSON.stringify(gcs));
    await ev(`(() => { document.querySelectorAll('.modal').forEach(m => m.remove()); return 1; })()`);
    // the calendar window
    await ev(`(async () => { await evCalsModal(); return 1; })()`); await sleep(900);
    await ev(`(() => { document.querySelector('.cvxfold')?.click(); return 1; })()`); await sleep(600);
    const sw = await ev(sz('.cvxrow .swc')), fold = await ev(sz('.cvxrow .cvxfold'));
    check(sw.length >= 2 && sw.every(([x, y]) => x >= 44 && y >= 44), '390: calendar switches 44 px ' + JSON.stringify(sw));
    check(fold.length === 1 && fold[0][0] >= 44 && fold[0][1] >= 44, '390: "Per list" 44 px ' + JSON.stringify(fold));
    await shot('p2362c-390-calendars.png');
    await ev(`(() => { document.querySelectorAll('.modal').forEach(m => m.remove()); return 1; })()`);
    // "Plan the day": the calendar lines
    const dp = await ev(`(async () => { await cvxCals(); document.body.insertAdjacentHTML('beforeend', '<div id="p2362c" style="position:fixed;top:0;left:0;width:360px;background:var(--bg)">' + cvxPlanRow(true) + '</div>'); return 1; })()`);
    await sleep(300);
    const dr = await ev(sz('#p2362c .cvxdpr'));
    check(dp === 1 && dr.length >= 1 && dr.every(([, y]) => y >= 44), '390: calendar lines of "Plan the day" 44 px ' + JSON.stringify(dr));
    await ev(`(() => { document.querySelector('#p2362c')?.remove(); return 1; })()`);
    // the sidebar drawer on the phone
    await ev(`(() => { document.querySelector('#top [data-act="side"]')?.click(); return 1; })()`); await sleep(800);
    await shot('p2362c-390-sidebar.png');
  }, false);

  console.log(`p2362_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
