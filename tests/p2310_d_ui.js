// 2.31.0 UI tests, part D ("Handy-Alltag": sort by column title, the connection dot), own container (start.sh). jsdom:
// #354 a click on a column title of a list with its own columns sorts by it (Date: earliest first), a second click the other
//      way round (empty dates stay last), a third back to the list's sort; aria-sort + the arrow on the sorted title; the
//      owner's click is the list's sort (server, survives a reload), a member's stays on the device; the sort menu mirrors
//      a column sort ("Column: Assignee · ascending"); right-click on a title: both directions, Hide column, Shown fields…
// #378 the dot at the own picture (sidebar / drawer): Online (green), Offline · 1 change waiting (grey), Syncing (yellow),
//      always as text too (aria-label, tooltip, the picture's own label); the account menu says the state first and offers
//      "Try again" while offline
// Firefox (1440 light / dark, mouse): real clicks on a column title sort, the title takes the focus; the arrow is visible; the dot sits on the
// picture with a ring. 390 touch: the dot in the drawer. Screenshots with P2310D_SHOTS=<dir>.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2310_d_ui', check, shots: 'P2310D_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el, o = {}) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const FEAT = 'cal,comments,collab,fields';
const AXE = require('fs').readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8');
const TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22a', 'wcag22aa'];
const axe = async (ev, where) => {  // the rules of p2160_a11y over the list with the sortable title row (and the sidebar dot)
  if ((await ev(`typeof axe`)) === 'undefined') await ev(AXE + '\n;1');
  const r = await ev(`axe.run(document, {runOnly: {type: 'tag', values: ${JSON.stringify(TAGS)}}, resultTypes: ['violations']}).then(r => r.violations.map(v => v.id + '(' + v.nodes.length + ') ' + v.nodes[0].target.join(' ')))`);
  check(!r.length, `${where}: no axe violations: ` + r.join(' | ').slice(0, 600));
};

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Baker', password: 'password123'})).id;
  const BCK = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, BCK);
  const L = (await call('POST', '/api/lists', {name: 'Sorted things'})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: BOB, role: 'edit'});
  check((await call('PATCH', `/api/lists/${L}`, {columns: ['due', 'prio', 'who']})).status === 200, 'the list gets its own columns');
  const d0 = new Date(), day = n => { const x = new Date(d0.getTime() + n * 864e5); return x.toISOString().slice(0, 10); };
  const T = {};
  for (const [title, due, priority] of [['Bravo', day(5), 1], ['Alpha', day(2), 5], ['Charlie', null, 3], ['Delta', day(9), 0]]) T[title] = (await call('POST', '/api/tasks', {title, list_id: L, due, priority})).id;
  await call('PATCH', `/api/tasks/${T.Delta}`, {assignee_id: BOB});
  await call('PATCH', `/api/tasks/${T.Alpha}`, {assignee_id: 1});
  // #354: the API takes the new sorts, and only those
  for (const m of ['date_desc', 'prio_asc', 'col:who', 'col:tags_desc', 'cf:12_desc', '']) check((await call('PATCH', `/api/lists/${L}`, {sort_mode: m})).status === 200, `#354: sort_mode ${m || '(default)'} accepted`);
  for (const m of ['col:title', 'date_up', 'col:who_desc_desc']) check((await call('PATCH', `/api/lists/${L}`, {sort_mode: m})).status === 400, `#354: sort_mode ${m} refused`);
  check((await call('PATCH', `/api/lists/${L}`, {sort_mode: 'col:who'}, BCK)).status === 403, '#354: a member cannot set the list sort');

  // ================= #354 jsdom: the owner
  let w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  const order = () => [...d.querySelectorAll('#view .trow .ttl')].map(e => e.textContent.trim());
  const head = k => d.querySelector(`#view .lchead .lc[data-k="${k}"]`);
  const btn = k => d.querySelector(`#view .lchead [data-colsort="${k}"]`);
  await until(() => d.querySelector('#view .lchead'));
  check(d.querySelector('#view .lchead[role="table"] [role="row"] [role="columnheader"]'), 'the title row: a table with one row of column headers');
  check(btn('due') && btn('due').tagName === 'BUTTON' && btn('due').getAttribute('aria-label') === 'Date' && /Sort by Date/.test(btn('due').title), 'every title is a button named after its column');
  check(!head('due').hasAttribute('aria-sort') && head('prio').getAttribute('aria-sort') === 'descending', 'default sort: Priority (highest first) shows on the Priority title');
  click(w, btn('due'));
  await until(() => head('due')?.getAttribute('aria-sort') === 'ascending');
  check(head('due')?.getAttribute('aria-sort') === 'ascending' && head('due').querySelector('.lcsa') && !head('prio')?.hasAttribute('aria-sort'), 'first click: Date ascending, the arrow, only one column sorted');
  check(order().join() === 'Alpha,Bravo,Delta,Charlie', 'rows by date, earliest first, no date last: ' + order().join());
  check(await until(async () => (await call('GET', '/api/state')).lists.find(x => x.id === L)?.sort_mode === 'date'), 'the owner\'s click is the list\'s sort (server)');
  click(w, btn('due'));
  await until(() => head('due')?.getAttribute('aria-sort') === 'descending');
  check(head('due')?.getAttribute('aria-sort') === 'descending', 'second click: descending');
  check(order().join() === 'Delta,Bravo,Alpha,Charlie', 'rows by date, latest first, no date still last: ' + order().join());
  check(/go back to the list sort/.test(btn('due').title), 'the tooltip says what the next click does');
  await until(async () => (await call('GET', '/api/state')).lists.find(x => x.id === L)?.sort_mode === 'date_desc');
  // the sort menu mirrors it: "Date" is not ticked for the reversed order, the column line is
  w.eval(`sortMenu(document.querySelector('#top h1'))`); await sleep(200);
  const mi = [...d.querySelectorAll('#pop [role="menuitem"]')];
  check(mi.some(b => b.classList.contains('sortcol') && b.classList.contains('on') && /Column: Date · descending/.test(b.textContent)), 'the sort menu shows the column sort: ' + mi.map(b => b.textContent.trim()).join('|'));
  w.eval('closePop()');
  w.close();
  // a reload keeps it (the list's sort on the server)
  w = await boot({user: 'alice', hash: 'l/' + L}); d = w.document;
  await until(() => head('due'));
  check(head('due')?.getAttribute('aria-sort') === 'descending' && order().join() === 'Delta,Bravo,Alpha,Charlie', 'after a reload: still Date descending');
  click(w, btn('due'));
  await until(() => !head('due')?.hasAttribute('aria-sort'));
  check(!head('due')?.hasAttribute('aria-sort') && head('prio')?.getAttribute('aria-sort') === 'descending', 'third click: back to the list\'s sort (Priority)');
  check(await until(async () => (await call('GET', '/api/state')).lists.find(x => x.id === L)?.sort_mode === ''), 'third click: the list sort is the default again');
  check(order().join() === 'Alpha,Charlie,Bravo,Delta', 'rows by priority again: ' + order().join());
  // Priority: the first click on the sorted default goes to lowest first, the next back
  click(w, btn('prio'));
  await until(() => head('prio')?.getAttribute('aria-sort') === 'ascending');
  check(head('prio')?.getAttribute('aria-sort') === 'ascending' && order().join() === 'Bravo,Charlie,Alpha,Delta', 'Priority ascending: lowest first, none last: ' + order().join());
  click(w, btn('prio'));
  await until(() => head('prio')?.getAttribute('aria-sort') === 'descending');
  check(head('prio')?.getAttribute('aria-sort') === 'descending', 'Priority: back to highest first');
  check(await until(async () => (await call('GET', '/api/state')).lists.find(x => x.id === L)?.sort_mode === ''), 'Priority: the list sort is the default again');
  // right-click on a title
  head('who').dispatchEvent(new w.MouseEvent('contextmenu', {bubbles: true, cancelable: true}));
  await sleep(200);
  const cm = [...d.querySelectorAll('#pop [role="menuitem"]')].map(b => b.textContent.trim());
  check(cm.includes('Sort ascending') && cm.includes('Sort descending') && cm.includes('Hide column') && cm.some(x => /Shown fields/.test(x)), 'right-click: both directions, Hide column, Shown fields: ' + cm.join('|'));
  w.eval('closePop()');
  w.close();

  // ================= #354 jsdom: a member sorts for herself (this device)
  w = await boot({user: 'bob', hash: 'l/' + L}); d = w.document;
  await until(() => btn('who'));
  click(w, btn('who'));
  await until(() => head('who')?.getAttribute('aria-sort') === 'ascending');
  check(head('who')?.getAttribute('aria-sort') === 'ascending', 'member: Assignee ascending');
  check(order().slice(0, 2).join() === 'Alpha,Delta', 'member: rows by assignee name, nobody last: ' + order().join());
  check(w.eval(`LS.get('sort2.l:${L}')`) === 'col:who', 'member: the sort stays on this device');
  check((await call('GET', '/api/state')).lists.find(x => x.id === L)?.sort_mode === '', 'member: the list sort is untouched ' + JSON.stringify((await call('GET', '/api/state')).lists.find(x => x.id === L)?.sort_mode));
  check(!!d.querySelector('.sortown'), 'member: the view says it is an own sort');
  click(w, btn('who'));
  await until(() => head('who')?.getAttribute('aria-sort') === 'descending');
  check(order().slice(0, 2).join() === 'Delta,Alpha', 'member: assignee descending, nobody still last: ' + order().join());
  click(w, btn('who'));
  await until(() => !head('who')?.hasAttribute('aria-sort'));
  check(!head('who')?.hasAttribute('aria-sort') && w.eval(`LS.get('sort2.l:${L}', null)`) === null, 'member: third click = the shared sort again');
  w.close();

  // ================= #378 jsdom: the connection dot
  w = await boot({user: 'alice', hash: 'l/' + L}); d = w.document;
  const dot = () => d.querySelector('#side .sbacct .netdot');
  await until(() => dot());
  check(dot()?.classList.contains('n-on') && dot().getAttribute('aria-label') === 'Online' && dot().getAttribute('role') === 'img', 'online: a green dot, named Online');
  check(/^Account: Alice · Online$/.test(d.querySelector('#side .sbacct').getAttribute('aria-label')), 'the picture\'s button says the state too');
  w.eval(`OUT.flushing = true; netDotDraw()`);
  check(dot()?.classList.contains('n-sync') && dot().getAttribute('aria-label') === 'Syncing', 'syncing: yellow, named Syncing');
  w.eval(`OUT.flushing = false; netDotDraw()`);
  w.__offline = true;
  await w.eval(`patchTask(${T.Bravo}, {title: 'Bravo offline'})`).catch(() => {});
  await until(() => dot()?.classList.contains('n-off'));
  check(dot()?.classList.contains('n-off') && dot().getAttribute('aria-label') === 'Offline · 1 change waiting', 'offline: grey, named with the waiting changes: ' + dot()?.getAttribute('aria-label'));
  check(/Offline · 1 change waiting/.test(dot().title), 'offline: the tooltip says it');
  check(!!d.querySelector('#top .offline'), 'the header chip stays while offline (it says what the dot cannot: server down / maintenance, sent later)');
  click(w, d.querySelector('#side .sbacct')); await sleep(200);
  let um = [...d.querySelectorAll('#pop [role="menuitem"]')].map(b => b.textContent.trim());
  check(um.some(x => x === 'Offline · 1 change waiting') && um.includes('Try again') && um.includes('Account'), 'the account menu: the state first, Try again: ' + um.join('|'));
  w.eval('closePop()');
  w.__offline = false;
  await w.eval('flush()'); await sleep(600);
  await until(() => dot()?.classList.contains('n-on'));
  check(dot()?.classList.contains('n-on') && dot().getAttribute('aria-label') === 'Online', 'back online: green again');
  click(w, d.querySelector('#side .sbacct')); await sleep(200);
  um = [...d.querySelectorAll('#pop [role="menuitem"]')].map(b => b.textContent.trim());
  check(um.includes('Online · All saved') && !um.includes('Try again'), 'online: "Online · All saved", no Try again: ' + um.join('|'));
  w.eval('closePop()');
  w.close();

  // ================= Firefox: keyboard on the titles, the visible arrow and dot
  const ffLogin = async ({ev, nav}, theme = 'light', user = 'alice') => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"${theme}"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${user}', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  for (const th of ['light', 'dark']) await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '1440 ' + th;
    check(await ffLogin(o, th) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await o.nav(B + '#l/' + L); await ready(ev);
    check(await ev(`(() => { const h = document.querySelector('#view .lchead'); return !!h && h.getBoundingClientRect().height > 0; })()`), `${tag}: the title row is visible`);
    // a real mouse click on the title (Enter / Space: it is a native, focusable button; Firefox's remote key events do not
    // activate buttons here, so the keyboard rests on the native button, see the jsdom part)
    const at = async k => { const p = await ev(`(() => { const b = document.querySelector('#view .lchead [data-colsort="${k}"]').getBoundingClientRect(); return {x: Math.round(b.left + b.width / 2), y: Math.round(b.top + b.height / 2)}; })()`);
      await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'm', parameters: {pointerType: 'mouse'}, actions: [{type: 'pointerMove', x: p.x, y: p.y}, {type: 'pointerDown', button: 0}, {type: 'pointerUp', button: 0}]}]});
      await cmd('input.releaseActions', {context: ctx}); await sleep(700); };
    check(await ev(`(() => { const b = document.querySelector('#view .lchead [data-colsort="due"]'); b.focus(); return document.activeElement === b && b.tabIndex === 0; })()`), `${tag}: the title button takes the keyboard focus`);
    await at('due');
    check(await ev(`document.querySelector('#view .lchead .lc[data-k="due"]')?.getAttribute('aria-sort')`) === 'ascending', `${tag}: a click sorts by the column`);
    check(await ev(`(() => { const a = document.querySelector('#view .lchead .lc[data-k="due"] .lcsa'); return !!a && a.getBoundingClientRect().width > 4; })()`), `${tag}: the arrow is visible`);
    check(await ev(`(() => { const b = document.querySelector('#view .lchead [data-colsort="due"]'); return b.getBoundingClientRect().height >= 24; })()`), `${tag}: the title button is a 24 px target`);
    await at('due');
    check(await ev(`document.querySelector('#view .lchead .lc[data-k="due"]')?.getAttribute('aria-sort')`) === 'descending', `${tag}: a second click reverses`);
    check(await ev(`(() => { const d = document.querySelector('#side .sbacct .netdot'), a = document.querySelector('#side .sbacct .avatar'); if (!d || !a) return false; const r = d.getBoundingClientRect(), q = a.getBoundingClientRect(), cs = getComputedStyle(d); return r.width >= 8 && r.right > q.left + q.width / 2 && r.bottom > q.top + q.height / 2 && cs.boxShadow !== 'none' && cs.backgroundColor !== cs.borderTopColor; })()`), `${tag}: the dot sits at the bottom right of the picture, with a ring and an edge`);
    await axe(ev, `${tag} list sorted by a column`);
    await shot(`p2310d-${th}-1440-sorted.png`);
    await ev(`(() => { document.querySelector('#view .lchead [data-colsort="due"]').click(); return 1; })()`); await sleep(700);  // back to the list's sort
  }, false);
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '390';
    check(await ffLogin(o, 'light') === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + '#l/' + L); await ready(ev);
    check(await ev(`(() => { const h = document.querySelector('#view .lchead'); return !h || h.getBoundingClientRect().height === 0; })()`), `${tag}: no title row on the phone`);
    await ev(`(() => { document.querySelector('#top [data-act="side"]').click(); return 1; })()`); await sleep(800);
    check(await ev(`(() => { const d = document.querySelector('#side .sbacct .netdot'); if (!d) return false; const r = d.getBoundingClientRect(); return r.width >= 8 && r.left < innerWidth && d.getAttribute('aria-label') === 'Online'; })()`), `${tag}: the dot at the picture in the drawer`);
    await shot('p2310d-light-390-drawer.png');
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
