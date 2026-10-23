// 2.156.0 UI tests, part C (#2071 calendar view per list, #2072 My tasks as a board, #2073 folded sections on every device +
// section templates), own container (start.sh), Firefox (desktop + phone). Invented names only.
// P2156C_NOSTART=1 = the container is running.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2156_c_ui', check, shots: 'P2156C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2156C_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return Object.assign(j, {http: r.status}); };
const FEAT = 'cal,kanban,timeline,collab,comments,events';
const pad = n => String(n).padStart(2, '0');
const day = (d, add = 0) => { const x = new Date(d); x.setDate(x.getDate() + add); return `${x.getFullYear()}-${pad(x.getMonth() + 1)}-${pad(x.getDate())}`; };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const now = new Date(), T0 = day(now), MID = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-15`;
  // a list in the calendar view with two dated tasks, another list with a task on the same day (must not show)
  const L = await call(CA, 'POST', '/api/lists', {name: 'Redaktionsplan'});
  await call(CA, 'PATCH', `/api/lists/${L.id}`, {view: 'calendar'});
  const L2 = await call(CA, 'POST', '/api/lists', {name: 'Andere Liste'});
  const T1 = await call(CA, 'POST', '/api/tasks', {title: 'Artikel Herbst', list_id: L.id, due: MID, assignee_id: me.id, priority: 1});
  await call(CA, 'POST', '/api/tasks', {title: 'Newsletter', list_id: L.id, due: T0, assignee_id: me.id});
  await call(CA, 'POST', '/api/tasks', {title: 'Fremde Aufgabe', list_id: L2.id, due: MID});
  const T4 = await call(CA, 'POST', '/api/tasks', {title: 'Ohne Datum', list_id: L2.id, assignee_id: me.id});
  // a list with sections (#2073)
  const L3 = await call(CA, 'POST', '/api/lists', {name: 'Projekt Abschnitte'});
  const S1 = await call(CA, 'POST', '/api/sections', {list_id: L3.id, name: 'Planung'});
  await call(CA, 'POST', '/api/sections', {list_id: L3.id, name: 'Umsetzung'});
  await call(CA, 'POST', '/api/tasks', {title: 'Konzept', list_id: L3.id, section_id: S1.id});
  const L4 = await call(CA, 'POST', '/api/lists', {name: 'Leere Liste'});

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = ev => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.ok)`);

  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev);
    // ===== #2071: the list's calendar
    await nav(B + '#l/' + L.id);
    check(await ready(ev, `!!document.querySelector('#view .lcal .cal')`, 80), '#2071: the list opens in its calendar view (month)');
    check(await ev(`!!document.querySelector('#top .vseg [data-act="view-calendar"].on')`), '#2071: the view switch has Calendar, active');
    const txt = await ev(`document.querySelector('#view .lcal .cal').textContent`);
    check(/Artikel Herbst/.test(txt) && /Newsletter/.test(txt) && !/Fremde Aufgabe/.test(txt), '#2071: only this list\'s tasks: ' + txt.slice(0, 200));
    check(await ev(`!document.querySelector('#view .lcal [data-act="ev-new"], #view .lcal [data-act="ev-cals"]')`), '#2071: no event / calendars buttons in a list\'s calendar');
    check(await ev(`[...document.querySelectorAll('#view .lcal .calbar [data-act="cal-mode"]')].map(b => b.dataset.k).join()`) === 'month,week,day,agenda', '#2071: month / week / day / agenda');
    await shot('p2156-c-listcal-desktop.png');
    // drag a task onto another day: dnd.js sets the date
    const D2 = `${MID.slice(0, 8)}20`;
    await ev(`(async () => { await dropTask(${T1.id}, document.querySelector('#view .lcal .cal .cell[data-day="${D2}"]'), 10); return 1; })()`);
    check(await ready(ev, `taskById(${T1.id})?.due === '${D2}'`, 40), '#2071: dropped on a day = its date');
    check((await call(CA, 'GET', `/api/tasks/${T1.id}`)).due === D2, '#2071: saved on the server');
    // a tap on a day picks it; the add box creates the task in this list on that day
    await ev(`(() => { document.querySelector('#view .lcal .cal .cell[data-day="${D2}"]').click(); return 1; })()`);
    await sleep(300);
    const qd = await ev(`JSON.stringify(quickDefaults())`);
    check(qd.includes(`"list_id":${L.id}`) && qd.includes(`"due":"${D2}"`), '#2071: new task = in this list on the picked day ' + qd);
    await ev(`(() => { document.querySelector('#view .lcal [data-act="cal-mode"][data-k="week"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('#view .lcal .week .wcol')`), '#2071: the week view of the list');
    await ev(`(() => { document.querySelector('#view .lcal [data-act="cal-mode"][data-k="month"]').click(); return 1; })()`);

    // ===== #2072: My tasks as a board
    await ev(`(() => { location.hash = keyToHash('assigned'); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('#view .mobar [data-act="mo-view"][data-k="board"]')`, 60), '#2072: My tasks has the switch List / Board');
    await ev(`(() => { document.querySelector('#view .mobar [data-act="mo-view"][data-k="board"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('#view .mboard .mbcol')`, 60), '#2072: the board');
    const cols = await ev(`[...document.querySelectorAll('#view .mboard .mbcol')].map(c => c.dataset.mbcol).join()`);
    check(/today/.test(cols) && /later|week/.test(cols) && /none/.test(cols), '#2072: columns by due date: ' + cols);
    check(await ev(`!!document.querySelector('#view .mboard .mbcol[data-mbcol="none"] .trow[data-id="${T4.id}"]')`), '#2072: the undated task in "No date"');
    await shot('p2156-c-board-desktop.png');
    await ev(`(async () => { await dropTask(${T4.id}, document.querySelector('#view .mboard .mbcol[data-mbcol="today"]'), 10); return 1; })()`);
    check(await ready(ev, `taskById(${T4.id})?.due === today()`, 40), '#2072: dropped on Today = due today');
    await ev(`(() => { document.querySelector('#view .mobar [data-act="mo-by"][data-k="prio"]').click(); return 1; })()`);
    check(await ready(ev, `[...document.querySelectorAll('#view .mboard .mbcol')].map(c => c.dataset.mbcol).join() === 'p5,p3,p1,p0'`), '#2072: columns by priority');
    await ev(`(async () => { await dropTask(${T1.id}, document.querySelector('#view .mboard .mbcol[data-mbcol="p5"]'), 10); return 1; })()`);
    check(await ready(ev, `taskById(${T1.id})?.priority === 5`, 40), '#2072: dropped on High = high priority');
    await sleep(800);
    const st = (await call(CA, 'GET', '/api/state')).settings;
    check(st.mine_board === '1' && st.mine_board_by === 'prio', '#2072: the choice is kept for the person ' + st.mine_board + ' ' + st.mine_board_by);

    // ===== #2073: a section folded stays folded after a reload (also on a fresh device)
    await nav(B + '#l/' + L3.id);
    check(await ready(ev, `!!document.querySelector('#view .ghead[data-key="s:${S1.id}"]')`, 60), '#2073: the list with its sections');
    await ev(`(() => { document.querySelector('#view .ghead[data-key="s:${S1.id}"]').click(); return 1; })()`);
    check(await ready(ev, `document.querySelector('#view .ghead[data-key="s:${S1.id}"]')?.classList.contains('closed')`), '#2073: folded');
    // CI of 2.168.4: the save is debounced, a slow runner needs longer than a fixed 1.2 s -> wait for it (up to 12 s)
    let sc = '';
    for (let i = 0; i < 40 && sc !== `[${S1.id}]`; i++) { await sleep(300); sc = (await call(CA, 'GET', '/api/state')).settings.sections_closed; }
    check(sc === `[${S1.id}]`, '#2073: saved for the person ' + sc);
    await ev(`(() => { localStorage.removeItem('tasks.collapsed'); localStorage.removeItem('collapsed'); return 1; })()`);
    await nav(B + '#l/' + L3.id);
    check(await ready(ev, `document.querySelector('#view .ghead[data-key="s:${S1.id}"]')?.classList.contains('closed')`, 60), '#2073: still folded after a reload without the device copy');
    // section templates: save this list's sections, add them to the empty list
    await ev(`(() => { sct_open(${L3.id}); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.sctmodal #sct-name')`), '#2073: the dialog');
    await ev(`(() => { document.querySelector('.sctmodal #sct-name').value = 'Ablauf'; document.querySelector('.sctmodal [data-m="save"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.sctmodal .sctt [data-m="apply"]')`), '#2073: saved, in the list of templates');
    await shot('p2156-c-sectpl-desktop.png');
    await ev(`(() => { document.querySelector('.sctmodal [data-m="close"]').click(); sct_open(${L4.id}); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.sctmodal .sctt [data-m="apply"]')`), '#2073: the dialog of the empty list shows the template');
    await ev(`(() => { document.querySelector('.sctmodal .sctt [data-m="apply"]').click(); return 1; })()`);
    check(await ready(ev, `S.sections.filter(s => s.list_id === ${L4.id}).map(s => s.name).join() === 'Planung,Umsetzung'`, 40), '#2073: the sections added to the empty list');
  }, false);

  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev);
    await nav(B + '#l/' + L.id);
    check(await ready(ev, `!!document.querySelector('#view .lcal .cal')`, 80), 'phone #2071: the list\'s calendar');
    // the view switch under the title: six views fit (inactive ones as icons)
    const vs = await ev(`(() => { const s = document.querySelector('#view .vsegm'); if (!s) return null; const r = s.getBoundingClientRect(); return {n: s.querySelectorAll('button').length, right: r.right, vw: document.documentElement.clientWidth, on: !!s.querySelector('[data-act="view-calendar"].on')}; })()`);
    check(vs && vs.n >= 5 && vs.on && vs.right <= vs.vw + .5, 'phone #2071: the view switch fits the screen ' + JSON.stringify(vs));
    const over = await ev(`(() => { const vw = document.documentElement.clientWidth; return [...document.querySelectorAll('#view .lcal *')].filter(e => { const r = e.getBoundingClientRect(); return r.width && r.right > vw + 1; }).length; })()`);
    check(over === 0, 'phone #2071: nothing sticks out of the screen: ' + over);
    await shot('p2156-c-listcal-phone.png');
    await ev(`(() => { location.hash = keyToHash('assigned'); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('#view .mboard .mbcol')`, 60), 'phone #2072: the board (the choice came along from the desktop)');
    const sw = await ev(`(() => { const k = document.querySelector('#view .mboard'); const b = [...document.querySelectorAll('#view .mobar button')].map(x => x.getBoundingClientRect().height); return {scroll: k.scrollWidth > k.clientWidth, minH: Math.min(...b)}; })()`);
    check(sw.scroll && sw.minH >= 43.5, 'phone #2072: the columns swipe sideways, the switches are 44 px high ' + JSON.stringify(sw));
    await shot('p2156-c-board-phone.png');
  }, true);

  console.log(`p2156_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
