// 2.16.0 UI tests (the small things next to #473), own container (start.sh, isolated test database).
// jsdom: the account picture at the right of the Kalmido row (#641: menu Account / Settings / Log out, the old account rows
// gone), Today = a sun with rays, Tomorrow = a half sun (#645), the grips between list | task | chat (#639: separator,
// keys, remembered per device, double-click / Enter = standard), column widths (#634: grip in the column title, keys,
// per device and list, double-click = standard), density "Custom" for the sidebar and the task rows (#642), a visible
// smiley for reactions on every chat message, mine too (#643), the command field: what it can do when empty, "Ask
// <agent>: …" sends to the chat, "Create as task: …" (#644), the heron's sun on the horizon (#447).
// Firefox: dragging the grips with the mouse at 1440 (the list keeps its room), a column grip; DeX-like 2560 x 1440 and
// 1920 x 1080 with sidebar + list + task + chat; phones with real touch taps (390 / 412): the account picture (44 px) and
// its menu, the reaction smiley on agent and own messages, compact sidebar rows stay 44 px but the drawer gets shorter.
// Screenshots with P2160_SHOTS=<dir>.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2160_ui', check, shots: 'P2160_SHOTS', prefs: [['widget.gtk.overlay-scrollbars.enabled', true], ['ui.useOverlayScrollbars', 1]]});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const tcall = async (method, url, tok, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + tok}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const innerWidthPx = vw => vw;
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const key = (w, el, k, o = {}) => el.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true, ...o}));
const ALL = 'cal,timeline,matrix,habits,pomo,kanban,collab,stats,time,progress,deps,fields,agents,comments';
const day = n => { const d = new Date(); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ALL.split(',').filter(x => !['collab', 'time'].includes(x))});
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en', tour: 'done'});
  const ME = (await call('GET', '/api/state')).me.id;
  const ag = await call('POST', '/api/admin/agents', {scopes: ['write'], username: 'claude', display_name: 'Claude'});
  const AG = ag.id, TOK = ag.token;
  const L = (await call('POST', '/api/lists', {name: 'Home'})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: AG, role: 'edit'});
  const T = [];
  for (let i = 1; i <= 6; i++) T.push((await call('POST', '/api/tasks', {title: 'Task ' + i, list_id: L, due: day(i), priority: i % 2 ? 3 : 0})).id);
  await call('PATCH', `/api/lists/${L}`, {columns: ['prio', 'due', 'who']});
  await tcall('GET', '/agent/events?since=0', TOK);
  await tcall('POST', `/agent/chats/${ME}`, TOK, {body: 'Hello Alice, I sorted your inbox.'});

  // ================= jsdom: #641 the account picture in the Kalmido row
  let w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  const acct = d.querySelector('#side .sbrand .sbacct');
  check(acct && acct.querySelector('.avatar') && acct.getAttribute('aria-haspopup') === 'menu' && acct.getAttribute('aria-label') === 'Account: Alice', '#641: the account picture at the right of the Kalmido row, named');
  check(!d.querySelector('#side .suser') && !d.querySelector('#side .sdtop'), '#641: the old account rows (drawer top, sidebar bottom) are gone');
  check(d.querySelector('#side .sbrand .sbhome') && d.querySelector('#side .sfoot .sset'), 'the logo and the Settings row stay');
  click(w, acct); await sleep(150);
  let mi = [...d.querySelectorAll('#pop [role="menuitem"]')].map(b => (b.querySelector('.ml') || b).textContent.trim());
  check(mi[0] === 'Alice · alice' && mi.includes('Account') && mi.includes('Settings') && mi.includes('Log out'), '#641: the menu: who, Account, Settings, Log out ' + mi.join('|'));
  click(w, [...d.querySelectorAll('#pop [role="menuitem"]')].find(b => /^Settings/.test(b.textContent.trim()))); await sleep(400);
  check(d.querySelector('.modal .smodal, .modal [data-pane]') || d.querySelector('.modal'), '#641: Settings opens from it');
  [...d.querySelectorAll('.modal')].forEach(m => m.remove());

  // #645: Today = a sun with rays, Tomorrow = a half sun on the horizon (no arrow)
  w.eval(`openDetail(${T[0]})`); await sleep(400);
  const sun = d.querySelector('#detail [data-act="due-q"][data-d="0"] svg')?.innerHTML || '', rise = d.querySelector('#detail [data-act="due-q"][data-d="1"] svg')?.innerHTML || '';
  check(/M10 2\.5V4\.3/.test(sun) && /A3\.5 3\.5/.test(sun), '#645: Today is a sun with rays (not the open arc that read as "reload")');
  check(/M2\.5 15\.5H17\.5/.test(rise) && !/L10 4/.test(rise), '#645: Tomorrow is a half sun on the horizon, no arrow');

  // #639: the grip between list and task panel
  await sleep(200); w.eval('placeGrips()');
  let g = d.getElementById('pgrip-det');
  check(g && g.getAttribute('role') === 'separator' && g.getAttribute('aria-orientation') === 'vertical' && g.tabIndex === 0 && g.getAttribute('aria-label') === 'Width of the task panel' && g.getAttribute('aria-valuenow') === '25.5', '#639: a grip (separator) at the task panel, 25.5 rem');
  key(w, g, 'ArrowLeft'); await sleep(50);
  check(w.__store['tasks.pw.det'] === '26.5' && d.documentElement.style.getPropertyValue('--detW') === '26.5rem', '#639: ← makes the panel 1 rem wider, remembered on the device ' + w.__store['tasks.pw.det']);
  key(w, g, 'ArrowLeft', {shiftKey: true}); await sleep(50);
  check(w.__store['tasks.pw.det'] === '30.5', '#639: Shift+← 4 rem');
  key(w, g, 'Home'); await sleep(50);
  check(w.__store['tasks.pw.det'] === '20', '#639: Home = the narrowest (20 rem)');
  key(w, g, 'Enter'); await sleep(50);
  check(!('tasks.pw.det' in w.__store) && d.documentElement.style.getPropertyValue('--detW') === '25.5rem', '#639: Enter = the standard width');
  key(w, g, 'ArrowLeft'); g.dispatchEvent(new w.MouseEvent('dblclick', {bubbles: true}));
  check(!('tasks.pw.det' in w.__store), '#639: a double-click = the standard width');
  key(w, g, 'ArrowLeft'); key(w, g, 'ArrowLeft');
  const st1 = {...w.__store}; w.eval('closeDetail()'); w.close();
  w = await boot({user: 'alice', hash: 'l/' + L, ls: st1}); d = w.document;
  check(d.documentElement.style.getPropertyValue('--detW') === '27.5rem', '#639: the width comes back after a reload');
  // #634: column widths
  const lg = d.querySelector('.lchead .lcg[data-lcg="due"]');
  check(lg && lg.getAttribute('role') === 'separator' && lg.tabIndex === 0 && lg.getAttribute('aria-label') === 'Width of the column Date', '#634: a grip in the column title ' + (lg && lg.getAttribute('aria-label')));
  check(!d.querySelector('.lchead[aria-hidden="true"]') && d.querySelector('.lchead .lc .lcn[aria-hidden="true"]'), 'the titles stay hidden from screen readers, the grips are reachable');
  check(d.querySelector(`#view .trow .lc[data-k="due"]`), 'the cells carry their column key');
  key(w, lg, 'ArrowRight', {shiftKey: true}); await sleep(50);
  const lw = JSON.parse(w.__store['tasks.lcw.' + L] || '{}');
  check(lw.due > 0 && /\.lc\[data-k="due"\]\{width:[\d.]+rem/.test(d.getElementById('lcw-style')?.textContent || ''), '#634: Shift+→ widens the column (per device and list) ' + JSON.stringify(lw));
  lg.dispatchEvent(new w.MouseEvent('dblclick', {bubbles: true}));
  check(!('tasks.lcw.' + L in w.__store) && !d.getElementById('lcw-style').textContent, '#634: a double-click = the standard width');
  w.close();

  // #642: density "Custom"
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  check(d.documentElement.dataset.density === 'compact' && d.documentElement.dataset.sdensity === 'compact', 'desktop default: compact rows and sidebar');
  w.eval(`settingsModal('appearance')`); await sleep(500);
  click(w, d.querySelector('[data-look="density"][data-v="custom"]')); await sleep(200);
  // 2.18.0 (#642): Custom = two sliders (sidebar / task rows spacing), starting from what was shown (compact)
  const dS = d.querySelector('#s-dens-side'), dR = d.querySelector('#s-dens-rows');
  check(dS && dR && dS.type === 'range' && +dS.value === 20 && +dR.value === 33 && d.documentElement.dataset.density === 'custom', '#642: Custom shows two sliders, starting from compact');
  check(d.querySelector('label[for="s-dens-side"]')?.textContent === 'Sidebar row spacing' && d.querySelector('label[for="s-dens-rows"]')?.textContent === 'Task row spacing', 'the two sliders are labelled');
  dS.value = 80; dS.dispatchEvent(new w.Event('input', {bubbles: true})); await sleep(100);
  const sh = parseFloat(d.documentElement.style.getPropertyValue('--srow-h'));
  check(sh > 2.4 && w.__store['tasks.densSideV'] === '80' || sh > 2.4 && JSON.parse(w.__store['tasks.densSideV'] || 'null') === 80, `#642: the sidebar slider applies live and is stored per device (${sh}rem)`);
  check(d.getElementById('s-dens-side-v').textContent === '80 %' && dS.getAttribute('aria-valuetext') === '80 %', 'the value is shown and read out');
  dR.value = 0; dR.dispatchEvent(new w.Event('input', {bubbles: true})); await sleep(100);
  check(parseFloat(d.documentElement.style.getPropertyValue('--row-h')) >= 1.5, '#642: with a mouse the task rows may get tight, never below 24 px');
  click(w, d.querySelector('[data-look="density"][data-v="compact"]')); await sleep(150);
  check(d.documentElement.dataset.sdensity === 'compact' && !d.querySelector('#s-dens-side') && !d.documentElement.style.getPropertyValue('--srow-h'), '#642: Compact sets both again');
  [...d.querySelectorAll('.modal')].forEach(m => m.remove()); w.close();

  // #643: reactions on every chat message
  await call('POST', `/api/agents/${AG}/chat`, {body: 'Thanks!'});
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  w.eval(`chatOpen(${AG})`); await until(() => d.querySelectorAll('#chat-msgs .cmsg').length >= 2, 60);
  const msgs = [...d.querySelectorAll('#chat-msgs .cmsg')];
  // 2.18.0 (#651, intended change): 👍 👎 ❤️ sit visibly on every message, no smiley button / hidden bar any more
  check(msgs.length >= 2 && msgs.every(m => m.querySelectorAll('.rxrow .rx[data-e]').length === 3 && !m.querySelector('.rxtog')), '#643 / #651: 👍 👎 ❤️ on every message (agent + mine), no smiley');
  const mine = msgs.find(m => m.classList.contains('me'));
  click(w, mine.querySelector('.rxrow [data-e="heart"]'));
  check(await until(() => d.querySelector(`#chat-msgs .cmsg.me .chrx .rx.on[data-e="heart"]`)), '#643: ❤️ on my own message');
  click(w, d.querySelector('#chat-msgs .cmsg.me .rxrow [data-e="heart"]'));
  check(await until(() => d.querySelector(`#chat-msgs .cmsg.me .rxrow .rx.add[data-e="heart"][aria-pressed="false"]`)), '#651: a second tap takes it back');
  w.eval('chatClose()'); w.close();

  // #644: the command field
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  w.eval('openPalette()'); await sleep(150);
  let hints = [...d.querySelectorAll('.palette .phints .phint')].map(x => x.textContent);
  check(hints.length === 4 && /#123 jumps to task 123/.test(hints[1]) && /Text \+ Enter creates a task/.test(hints[2]) && /Ask Claude/.test(hints[3]), '#644: empty: what it can do ' + hints.join(' | '));
  const inp = d.querySelector('.palette .pqin');
  const type = v => { inp.value = v; inp.dispatchEvent(new w.Event('input', {bubbles: true})); };
  type('Task'); await sleep(50);
  let pl = [...d.querySelectorAll('.palette .pitem .plt')].map(x => x.textContent);
  check(pl.findIndex(x => /^Task \d/.test(x)) >= 0 && pl.findIndex(x => /^Task \d/.test(x)) < pl.indexOf('Ask Claude: Task') && pl[pl.length - 1] === 'Create as task: Task' && pl.indexOf('Ask Claude: Task') === pl.length - 2, '#644: real matches first, then "Ask Claude", then "Create as task" ' + pl.slice(-3).join(' | '));
  type('Water the plants tomorrow'); await sleep(50);
  pl = [...d.querySelectorAll('.palette .pitem')];
  check(pl[0].querySelector('.plt').textContent === 'Create as task: Water the plants' && pl[0].classList.contains('on') && /Inbox · Tomorrow/.test(pl[0].querySelector('.pls')?.textContent || ''), '#644: nothing found: "Create as task" on top (with list and date) ' + pl[0].textContent.trim().slice(0, 80));
  type('Which tasks are due this week?'); await sleep(50);
  click(w, [...d.querySelectorAll('.palette .pitem')].find(b => /^Ask Claude:/.test(b.textContent.trim())));
  check(await until(async () => (await call('GET', `/api/agents/${AG}/chat`)).messages?.some?.(m => m.body === 'Which tasks are due this week?')), '#644: "Ask Claude" sends the text to the chat');
  check(await until(() => w.eval('S.chat.aid') === AG), '#644: … and opens it');
  w.eval('chatClose()'); w.close();
  w = await boot({user: 'alice', hash: 'today', mobile: true}); d = w.document;
  w.eval('openPalette()'); await sleep(150);
  check(d.querySelector('.palette .phints') && !d.querySelector('.palette .phints kbd'), '#644: phone: the hints without key symbols');
  w.eval('closePalette()');
  // #447: the heron's sun on the horizon
  const hs = w.eval(`heron('stand')`), hw = w.eval(`heron('welcome')`), ho = w.eval(`heron('offline')`);
  check([hs, hw, ho].every(x => /class="hr-sun[^"]*" d="M89 108A9 9 0 0 1 107 108Z"/.test(x) && !/cx="88" cy="28"/.test(x) && /M42 108H112/.test(x)), '#447: standing / welcome / offline: a half sun on the horizon, away from the beak');
  w.close();

  // #648: "Pinned" across all lists, the pin button next to Priority, the API filter
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  check(!d.querySelector('#side [data-go="pinned"]'), '#648: no "Pinned" row while nothing is pinned');
  w.close();
  const L2 = (await call('POST', '/api/lists', {name: 'Work'})).id;
  const P2 = (await call('POST', '/api/tasks', {title: 'Pinned at work', list_id: L2})).id;
  await call('PATCH', `/api/tasks/${T[2]}`, {pinned: 1}); await call('PATCH', `/api/tasks/${P2}`, {pinned: 1});
  w = await boot({user: 'alice', hash: 'pinned'}); d = w.document;
  const pr = d.querySelector('#side .srow[data-go="pinned"]');
  check(pr && pr.querySelector('.c')?.textContent === '2' && pr.classList.contains('on'), '#648: "Pinned" in the smart lists with its count');
  check(d.querySelector('#top h1')?.textContent.includes('Pinned') && [...d.querySelectorAll('#view .trow')].map(r => +r.dataset.id).sort().join() === [T[2], P2].sort().join(), '#648: the view shows the pinned tasks of every list');
  check(d.querySelectorAll('#view .group, #view .ghead').length >= 2, '#648: grouped by list');
  w.close();
  w = await boot({user: 'alice', hash: 'l/' + L, mobile: true}); d = w.document;
  w.eval(`openDetail(${T[2]})`); await sleep(400);
  const pb = d.querySelector('#detail .dtop [data-act="pin"]'), fb = d.querySelector('#detail .dtop [data-act="prio"]');
  check(pb && pb.getAttribute('aria-pressed') === 'true' && pb.nextElementSibling === fb, '#648: the pin button sits right next to Priority on a phone too, pressed');
  w.close();
  const tp = await tcall('GET', '/tasks?pinned=true', TOK);
  check(tp.status === 200 && tp.data.map(x => x.id).includes(T[2]) && tp.data.every(x => x.pinned), '#648: API v1 ?pinned=true ' + JSON.stringify(tp).slice(0, 120));
  check((await tcall('GET', '/tasks?pinned=maybe', TOK)).status === 400, '#648: ?pinned=maybe is refused');

  // ================= Firefox: dragging the grips at 1440 (mouse), DeX-like widths
  const ffLogin = async ({ev, nav}, theme = 'dark', ls = {}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"${theme}"'); ${Object.entries(ls).map(([k, v]) => `localStorage.setItem(${JSON.stringify(k)}, ${JSON.stringify(v)});`).join(' ')} return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); await sleep(700); };
  const LAY = `(() => { const r = s => { const e = document.querySelector(s); if (!e || !e.offsetWidth) return null; const b = e.getBoundingClientRect(); return {l: Math.round(b.left), r: Math.round(b.right), w: Math.round(b.width)}; };
    return {view: r('#view'), det: r('#detail'), chat: r('#achat:not(.hidden)'), side: r('#side'), over: document.documentElement.scrollWidth - innerWidth, gd: r('#pgrip-det'), gc: r('#pgrip-chat'), yield: document.body.classList.contains('chat-yield'), rail: document.querySelector('#app').classList.contains('side-rail')}; })()`;
  await firefox(async o => {
    const {cmd, ev, ctx, shot, drag} = o;
    check(await ffLogin(o, 'dark') === 200, '1440: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await o.nav(B + '#l/' + L); await ready(ev);
    await ev(`(() => { openDetail(${T[0]}); return 1; })()`); await sleep(900);
    let a = await ev(LAY);
    check(a.det && a.gd && Math.abs(a.gd.l + 5 - a.det.l) <= 2, '1440: the grip sits on the panel edge ' + JSON.stringify(a));
    const w0 = a.det.w;
    await drag(a.gd.l + 5, 400, -120, 0, 'mouse'); await sleep(500);
    a = await ev(LAY);
    check(a.det.w >= w0 + 100 && a.det.w <= w0 + 140 && a.view.w >= 420 && a.over <= 0, `1440: dragging the grip 120 px left widens the panel (${w0} -> ${a.det.w}), the list keeps its room`);
    check(Math.abs(a.gd.l + 5 - a.det.l) <= 2, '1440: the grip moved with the edge');
    await drag(a.gd.l + 5, 400, -(a.gd.l - 20), 0, 'mouse'); await sleep(500);
    a = await ev(LAY);
    check(a.view.w >= 418 && a.over <= 0, '1440: dragging far left stops where the list keeps 420 px ' + JSON.stringify(a.view));
    await shot('p2160-1440-wide-panel.png');
    await ev(`(() => { document.getElementById('pgrip-det').dispatchEvent(new MouseEvent('dblclick', {bubbles: true})); return 1; })()`); await sleep(400);
    a = await ev(LAY);
    check(Math.abs(a.det.w - w0) <= 2, '1440: a double-click brings the standard width back');
    // the chat grip
    await ev(`(() => { closeDetail(); chatOpen(${AG}); return 1; })()`); await sleep(1200);
    a = await ev(LAY);
    check(a.chat && a.gc, '1440: the chat has its grip ' + JSON.stringify(a));
    const c0 = a.chat.w;
    await drag(a.gc.l + 5, 500, -80, 0, 'mouse'); await sleep(500);
    a = await ev(LAY);
    check(a.chat.w >= c0 + 60 && a.chat.w <= Math.round(1440 * .4) + 2 && a.over <= 0, `1440: the chat gets wider (${c0} -> ${a.chat.w}), at most 40 %`);
    check(await ev(`+localStorage.getItem('tasks.pw.chat') > 26`), '1440: remembered on this device');
    // the column grip
    await ev(`(() => { chatClose(); return 1; })()`); await sleep(400);
    const cg = await ev(`(() => { const g = document.querySelector('.lchead .lcg[data-lcg="due"]'), c = g.closest('.lc').getBoundingClientRect(), b = g.getBoundingClientRect(); return {x: b.left + b.width / 2, y: b.top + b.height / 2, w: c.width}; })()`);
    await drag(cg.x, cg.y, 60, 0, 'mouse'); await sleep(400);
    const cw = await ev(`(() => ({head: document.querySelector('.lchead .lc[data-k="due"]').getBoundingClientRect().width, cell: document.querySelector('#view .trow .lc[data-k="due"]').getBoundingClientRect().width, over: document.documentElement.scrollWidth - innerWidth}))()`);
    check(cw.head >= cg.w + 45 && Math.abs(cw.head - cw.cell) <= 1 && cw.over <= 0, `1440: dragging the column grip widens the column, title and cells alike (${Math.round(cg.w)} -> ${Math.round(cw.head)})`);
    await shot('p2160-1440-columns.png');
  }, false);
  for (const [vw, vh] of [[2560, 1440], [1920, 1080]]) await firefox(async o => {
    const {cmd, ev, ctx, shot} = o;
    await ffLogin(o, 'dark');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
    await o.nav(B + '#l/' + L); await ready(ev);
    await ev(`(() => { chatOpen(${AG}); openDetail(${T[1]}); return 1; })()`); await sleep(1400);
    const a = await ev(LAY);
    check(a.side && a.view && a.det && a.chat && !a.yield && a.view.w >= 420 && a.over <= 0, `${vw}x${vh}: sidebar + list + task + chat side by side ` + JSON.stringify(a));
    check(a.gd && a.gc, `${vw}x${vh}: both grips`);
    const hd = await ev(`(() => { const d = document.querySelector('#detail .dtop'); return {sw: d.scrollWidth - d.clientWidth, h: Math.round(d.getBoundingClientRect().height)}; })()`);
    check(hd.sw <= 0, `${vw}x${vh}: the task header fits (${hd.h} px)`);
    await shot(`p2160-${vw}-four.png`);
  }, false);

  // ================= Firefox: phones with real touch taps
  const tapper = ({cmd, ctx}) => async (x, y) => {
    await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 't1', parameters: {pointerType: 'touch'}, actions: [{type: 'pointerMove', x: Math.round(x), y: Math.round(y)}, {type: 'pointerDown', button: 0}, {type: 'pause', duration: 60}, {type: 'pointerUp', button: 0}]}]});
    await cmd('input.releaseActions', {context: ctx});
  };
  const center = sel => `(() => { const e = document.querySelector(${JSON.stringify(sel)}); if (!e) return null; const r = e.getBoundingClientRect(); if (r.top < 0 || r.bottom > innerHeight) { e.scrollIntoView({block: 'center'}); } const q = e.getBoundingClientRect(); return {x: q.left + q.width / 2, y: q.top + q.height / 2, w: q.width, h: q.height}; })()`;
  for (const [vw, vh, th] of [[390, 844, 'light'], [412, 915, 'dark']]) await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tap = tapper(o), tag = String(vw);
    check(await ffLogin(o, th) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
    await o.nav(B + '#today'); await ready(ev);
    let p = await ev(center('#top [data-act="side"]')); await tap(p.x, p.y); await sleep(700);
    p = await ev(center('#side .sbrand .sbacct'));
    check(p && p.w >= 44 && p.h >= 44, `${tag}: the account picture in the drawer's Kalmido row, a 44 px target ` + JSON.stringify(p));
    await tap(p.x, p.y); await sleep(600);
    const m = await ev(`[...document.querySelectorAll('#pop:not(.hidden) [role="menuitem"]')].map(b => (b.querySelector('.ml') || b).textContent.trim())`);
    check(m.includes('Account') && m.includes('Settings') && m.includes('Log out'), `${tag}: a tap opens Account / Settings / Log out ` + m.join('|'));
    await shot(`p2160-${tag}-account.png`);
    // #648: the pin button in the task header, a real tap
    await ev(`(() => { closePop(); closeSide(); openDetail(${T[3]}); return 1; })()`); await sleep(900);
    p = await ev(center('#detail .dtop [data-act="pin"]'));
    check(p && p.w >= 44 && p.h >= 44 && p.x < innerWidthPx(vw), `${tag}: Pin in the task header, a 44 px target`);
    await tap(p.x, p.y);
    check(await until(async () => (await call('GET', '/api/state')).tasks.find(t => t.id === T[3])?.pinned), `${tag}: a tap pins the task`);
    await call('PATCH', `/api/tasks/${T[3]}`, {pinned: 0});
    await ev(`(() => { closeDetail(); return 1; })()`); await sleep(300);
    await ev(`(() => { closePop(); closeSide(); return 1; })()`); await sleep(300);
    // the drawer: compact is shorter than comfortable, the rows stay 44 px
    const drawerH = async dens => {
      await ev(`(() => { localStorage.setItem('tasks.density', '"${dens}"'); applyDensity(); render(); return 1; })()`); await sleep(300);
      return ev(`(() => { const s = document.querySelector('#side'); const rows = [...s.querySelectorAll('.srow')].filter(r => r.offsetWidth); return {h: s.scrollHeight, min: Math.round(Math.min(...rows.map(r => r.getBoundingClientRect().height)))}; })()`);
    };
    const comf = await drawerH('comfortable'), comp = await drawerH('compact');
    check(comp.h < comf.h && comp.min >= 44 && comf.min >= 44, `${tag}: compact makes the drawer shorter (${comf.h} -> ${comp.h} px), rows stay 44 px (${comp.min})`);
    // the chat: the reactions on an agent message and on mine, visible, real taps (2.18.0 #651: no smiley step any more)
    await o.nav(B + '#agents/' + AG); await ready(ev); await sleep(900);
    const rx = await ev(`[...document.querySelectorAll('#chat-msgs .cmsg')].map(m => { const bs = [...m.querySelectorAll('.rxrow .rx')]; if (bs.length < 3) return null; const r = bs.map(b => b.getBoundingClientRect()); return {me: m.classList.contains('me'), w: Math.round(Math.min(...r.map(x => x.width))), h: Math.round(Math.min(...r.map(x => x.height))), l: Math.round(Math.min(...r.map(x => x.left))), r: Math.round(Math.max(...r.map(x => x.right))), op: Math.min(...bs.map(b => +getComputedStyle(b).opacity))}; })`);
    check(rx.length >= 2 && rx.every(x => x && x.w >= 44 && x.h >= 44 && x.op >= .6 && x.l >= 0 && x.r <= vw), `${tag}: every message shows 👍 👎 ❤️ (44 px, inside the screen, no long press) ` + JSON.stringify(rx));
    const em = await ev(`[...document.querySelectorAll('#chat-msgs .cmsg.ag .rxrow .rx.add[data-e]')].pop()?.dataset.e`);
    p = await ev(`(() => { const e = [...document.querySelectorAll('#chat-msgs .cmsg.ag .rxrow [data-e="${em}"]')].pop(); e.scrollIntoView({block: 'center'}); const q = e.getBoundingClientRect(); return {x: q.left + q.width / 2, y: q.top + q.height / 2}; })()`); await tap(p.x, p.y);
    check(await until(() => ev(`!!document.querySelector('#chat-msgs .cmsg.ag .chrx .rx.on[data-e="${em}"]')`)), `${tag}: a tap on ${em} reacts`);
    await shot(`p2160-${tag}-chat-reactions.png`);
    await ev(`(() => { localStorage.removeItem('tasks.density'); return 1; })()`);
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
