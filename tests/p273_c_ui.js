// 2.73.0 part C UI test, own container (start.sh), Firefox (the real layout).
// #661: several Kalmido servers in one app, the merged view (static/js/msvview.js). The server routes /api/servers… come with
//       part A; here the page's fetch answers them with made-up data (two servers, one of them offline), so only the client
//       is tested: without linked servers nothing changes (no badges, no further requests), the sidebar group per server, a
//       foreign list, Today / Basket merged with badges, the details + complete, the quick add target -> POST to the right
//       server, the search and News sections, the calendar, "Move to another server" -> the move call, a phone width.
// Screenshots with P273C_SHOTS=<dir>.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p273_c_ui', check, shots: 'P273C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return Array.isArray(j) ? j : {...j, status: r.status}; };
const FEAT = 'cal,collab,comments';

// the fake answers of /api/servers… (in the page); __msv.links = how many servers are linked, __msv.calls = what was asked
const MOCK = `(() => {
  if (window.__msv) return 1;
  const t0 = today(), y = addDays(t0, -1);
  const W = {id: 1, name: 'Work', short: 'WK', color: '#3e63dd', base_url: 'https://work.example.com', default_inbox: false, position: 1, remote_me: {id: 7, name: 'A', email: 'a@example.com'}, ok: true, err: null, at: new Date().toISOString()};
  const C = {id: 2, name: 'Club', short: 'CL', color: '#f76b15', base_url: 'https://club.example.com', default_inbox: false, position: 2, remote_me: {id: 3, name: 'A', email: 'a@example.com'}, ok: false, err: 'offline', at: null};
  const T = (id, list_id, title, o = {}) => ({id, list_id, parent_id: null, title, due: null, due_time: null, priority: 0, status: 0, tags: [], updated_at: null, url: 'https://work.example.com/#t/' + id, ...o});
  window.__msv = {links: 0, calls: [], tasks: [T(100, 11, '<img src=x onerror="window.__xss=1">Report', {due: t0, priority: 5}), T(101, 10, 'Inbox item W'), T(102, 11, 'Overdue W', {due: y}), T(103, 11, 'Sub W', {parent_id: 100})]};
  const J = (s, j) => new Response(JSON.stringify(j), {status: s, headers: {'Content-Type': 'application/json'}});
  const OFF = () => J(424, {error: 'Club is not reachable', code: 'offline'});
  const F0 = window.fetch;
  window.fetch = async function (u, o = {}) {
    const url = String(u), m = (o.method || 'GET').toUpperCase();
    if (!/^\\/api\\/servers(\\/|\\?|$)/.test(url)) return F0.call(this, u, o);
    const body = o.body ? JSON.parse(o.body) : null; __msv.calls.push({m, url, body});
    const p = url.split('?')[0].split('/').slice(3);  // ['', ] -> [sid, part, ...]
    if (!p.length) return J(200, {links: [W, C].slice(0, __msv.links), self: {name: 'Base', short: 'BS', color: '#30a46c'}});
    if (p[0] === 'move') return J(200, {ok: true, task: {server: body.to.server, id: 300}, lost: {comments: 1, attachments: 0, subtasks: 2}});  // 2.73.0 (#661) review N3: subtasks
    if (p[0] === '2') return OFF();
    const tid = +p[2];
    if (p[1] === 'data') return J(200, {lists: [{id: 10, name: 'Work inbox', color: '', folder: '', inbox: true, can_write: true}, {id: 11, name: 'Projects', color: '', folder: '', inbox: false, can_write: true}, {id: 12, name: 'Read only', color: '', folder: '', inbox: false, can_write: false}], tasks: __msv.tasks, today: t0, at: new Date().toISOString()});
    if (p[1] === 'tasks' && !tid && m === 'POST') return J(200, T(200 + __msv.calls.length, body.list_id || 10, body.title, {due: body.due || null}));
    if (p[1] === 'tasks' && p[3] === 'complete') return J(200, {...__msv.tasks.find(t => t.id === tid), status: 2});
    if (p[1] === 'tasks' && p[3] === 'reopen') return J(200, {...__msv.tasks.find(t => t.id === tid), status: 0});
    if (p[1] === 'tasks' && m === 'GET') return J(200, {...__msv.tasks.find(t => t.id === tid), notes: 'Note W', subtasks: [{id: 103, title: 'Sub W', status: 0}], comments_count: 2, attachments_count: 1});
    if (p[1] === 'tasks' && m === 'PATCH') return J(200, {...__msv.tasks.find(t => t.id === tid), ...body});
    if (p[1] === 'search') return J(200, {tasks: [T(150, 11, 'Searched W')]});
    if (p[1] === 'news' && p[2] === 'read') return J(200, {ok: true});
    if (p[1] === 'news') return J(200, {items: [{id: 5, kind: 'comment', text: 'News W <b>x</b>', task_id: 100, at: new Date().toISOString(), read: false}], unread: 1});
    if (p[1] === 'events') return J(200, {events: [{id: 1, occ: '', title: 'Meeting W', start: t0 + 'T10:00', end: t0 + 'T11:00', all_day: false, cal_name: 'Team', color: '#3e63dd', url: 'https://work.example.com/#cal'}]});
    return J(404, {error: 'not found', code: 'notfound'});
  };
  return 1;
})()`;

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const OWN = (await call('POST', '/api/tasks', {title: 'Own inbox task'})).id;

  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, sel, n = 40) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('${sel}')`).catch(() => false)); i++) await sleep(250); await sleep(500); };
  const calls = ev => ev(`JSON.stringify(__msv.calls)`).then(JSON.parse);
  const link = async (ev, n) => { await ev(`(async () => { __msv.links = ${n}; await msvvLoad(); return 1; })()`); await sleep(400); };
  const go = async (ev, hash, sel) => { await ev(`(() => { location.hash = '${hash}'; return 1; })()`); await ready(ev, sel, 20); };

  const desk = async o => {
    const {cmd, ev, nav, shot} = o;
    await cmd('browsingContext.setViewport', {context: o.ctx, viewport: {width: 1280, height: 900}});
    check(await ffLogin(o) === 200, 'login');
    await nav(B + '#inbox'); await ready(ev, '#view .trow[data-id]');
    await ev(`(async () => { await api('POST', '/api/tasks', {title: 'Own today', due: today()}); await load(); render(); return 1; })()`); await sleep(500);
    // ---- without linked servers: one quiet GET /api/servers at the start (404 before part A), nothing else, no badges
    await sleep(1500);
    const res0 = await ev(`performance.getEntriesByType('resource').map(e => e.name).filter(n => n.includes('/api/servers'))`);
    check(res0.length <= 1 && res0.every(n => /\/api\/servers$/.test(n)), '#661: without servers at most one GET /api/servers at the start ' + JSON.stringify(res0));
    check(await ev(`!document.querySelector('.msvb, .sg-msv, .msvvqc')`), '#661: without servers no badge, no sidebar group, no target chip');
    await ev(MOCK);
    await link(ev, 0);
    let c = await calls(ev);
    check(c.length === 1 && c[0].url === '/api/servers', '#661: zero linked servers: no /data calls ' + JSON.stringify(c));
    check(await ev(`!document.querySelector('.msvb, .sg-msv')`), '#661: zero linked servers: nothing drawn');
    // ---- two servers linked (Club offline)
    await link(ev, 2);
    c = await calls(ev);
    check(c.some(x => x.url === '/api/servers/1/data') && c.some(x => x.url === '/api/servers/2/data'), '#661: /data per server ' + JSON.stringify(c.map(x => x.url)));
    const side = await ev(`(() => { const g = [...document.querySelectorAll('#side .sg-msv')]; return g.map(x => ({id: x.dataset.msvside, b: x.querySelector('.msvb')?.textContent, rows: [...x.querySelectorAll('.srow')].map(r => r.dataset.go), off: !!x.querySelector('.msvvoff'), err: x.querySelector('.msvverr')?.textContent || ''})); })()`);
    check(side.length === 2 && side[0].b === 'WK' && side[0].rows.includes('srv/1/11') && side[0].rows.length === 3, '#661: sidebar group with badge + lists ' + JSON.stringify(side));
    check(side[1] && side[1].off && /Club/.test(side[1].err), '#661: the offline server shows a quiet error line ' + JSON.stringify(side[1]));
    check(await ev(`!!document.querySelector('#side .sg-lists + .sg-msv, #side .sg-msv')`), '#661: the server groups sit in the sidebar');
    // Basket merged: the foreign inbox task with its badge, the own rows with the own badge, the count includes it
    await go(ev, 'inbox', '#view [data-msv="1:101"]');
    const ib = await ev(`(() => ({far: !!document.querySelector('#view .trow[data-msv="1:101"] .msvb'), farB: document.querySelector('#view .trow[data-msv="1:101"] .msvb')?.textContent, own: document.querySelector('#view .trow[data-id="${OWN}"] .msvb')?.textContent || '', n: parseInt(document.querySelector('#side .srow[data-go="inbox"] .c')?.textContent), want: (counts().lists[inbox().id] || 0) + 1}))()`);
    check(ib.far && ib.farB === 'WK' && ib.own === 'BS', '#661: Basket merged with badges ' + JSON.stringify(ib));
    check(ib.n === ib.want, '#661: the Basket count includes the foreign task ' + JSON.stringify(ib));
    // Today merged: the overdue foreign task in "Overdue", the one due today with the text of its HTML title, no script ran
    await go(ev, 'today', '#view [data-msv="1:100"]');
    const td = await ev(`(() => { const r = document.querySelector('#view .trow[data-msv="1:100"]'), o = document.querySelector('#view .trow[data-msv="1:102"]');
      return {txt: r?.querySelector('.ttl')?.textContent || '', img: !!r?.querySelector('img'), xss: !!window.__xss, over: !!o?.closest('.group')?.querySelector('.ghead.over'), sub: !!document.querySelector('#view .trow.sub[data-msv="1:103"]'), own: !!document.querySelector('#view .trow[data-id] .msvb')}; })()`);
    check(td.txt.includes('<img') && !td.img && !td.xss, '#661: an HTML title is shown as text ' + JSON.stringify(td));
    const hn = await ev(`[document.querySelector('#top .hn')?.textContent, parseInt(document.querySelector('#side .srow[data-go="today"] .c')?.textContent)]`);
    check(+hn[0] === hn[1] && hn[1] >= 3, '#661: the header count and the sidebar count of Today include the foreign tasks ' + JSON.stringify(hn));
    check(td.over && td.sub && td.own, '#661: Today merged (overdue group, subtask below, own badge) ' + JSON.stringify(td));
    await shot('p273c-today-1280.png');
    // a normal own list: no own badge
    const lid = await ev(`S.lists.find(l => l.is_inbox).id`);
    await ev(`(async () => { const l = await api('POST', '/api/lists', {name: 'Plain'}); await api('POST', '/api/tasks', {title: 'In plain', list_id: l.id}); await load(); location.hash = 'l/' + l.id; return 1; })()`);
    await ready(ev, '#view .trow[data-id]');
    check(await ev(`!document.querySelector('#view .msvb')`), '#661: an own list view has no badges');
    // ---- a foreign list: its open tasks, quick add into it
    await go(ev, 'srv/1/11', '#view [data-msv="1:100"]');
    const fl = await ev(`(() => ({rows: [...document.querySelectorAll('#view .trow[data-msv]')].map(r => r.dataset.msv), h1: document.querySelector('#top h1')?.textContent || '', inp: !!document.querySelector('#msvv-in'), on: !!document.querySelector('#side .srow.on[data-go="srv/1/11"]')}))()`);
    check(fl.rows.includes('1:100') && fl.rows.includes('1:102') && fl.rows.includes('1:103') && !fl.rows.includes('1:101'), '#661: the foreign list shows its tasks ' + JSON.stringify(fl));
    check(/Projects/.test(fl.h1) && fl.inp && fl.on, '#661: title, quick add, sidebar row on ' + JSON.stringify(fl));
    await ev(`(() => { const i = document.querySelector('#msvv-in'); i.value = 'From the list'; i.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true})); return 1; })()`); await sleep(600);
    c = await calls(ev);
    const pl = c.find(x => x.m === 'POST' && x.url === '/api/servers/1/tasks');
    check(pl && pl.body.list_id === 11 && pl.body.title === 'From the list', '#661: quick add in a foreign list -> POST to that server + list ' + JSON.stringify(pl));
    // ---- the details of a foreign task + complete
    await ev(`(() => { document.querySelector('#view .trow[data-msv="1:100"] .ttl').click(); return 1; })()`);
    await ready(ev, '.msvvdlg #msvvd-n');
    const dt = await ev(`(() => { const m = document.querySelector('.msvvdlg'); return {b: m?.querySelector('.msvb')?.textContent, srv: m?.querySelector('.msvvdsrv')?.textContent || '', notes: m?.querySelector('#msvvd-n')?.value, sub: m?.querySelector('.msvvsubs')?.textContent || '', cnt: m?.querySelector('.msvvcnt')?.textContent || '', open: m?.querySelector('a[href^="https://work.example.com/"]') ? 1 : 0, mv: !!m?.querySelector('[data-msvd="move"]')}; })()`);
    check(dt.b === 'WK' && /Work/.test(dt.srv) && /Projects/.test(dt.srv) && dt.notes === 'Note W' && /Sub W/.test(dt.sub) && /2 comments/.test(dt.cnt) && dt.open && dt.mv, '#661: foreign details ' + JSON.stringify(dt));
    await shot('p273c-detail-1280.png');
    await ev(`(() => { document.querySelector('.msvvdlg [data-msvd="toggle"]').click(); return 1; })()`); await sleep(600);
    c = await calls(ev);
    check(c.some(x => x.m === 'POST' && x.url === '/api/servers/1/tasks/100/complete'), '#661: complete -> POST …/complete');
    check(await ev(`!document.querySelector('.msvvdlg') && /Undo/.test(document.querySelector('#toast')?.textContent || '')`), '#661: completed: the panel closes, a toast offers Undo');
    // ticking off at the row
    await go(ev, 'srv/1/11', '#view [data-msv="1:102"]');
    await ev(`(() => { document.querySelector('#view .trow[data-msv="1:102"] .chk').click(); return 1; })()`); await sleep(500);
    check((await calls(ev)).some(x => x.m === 'POST' && x.url === '/api/servers/1/tasks/102/complete'), '#661: the circle of a foreign row completes it there');
    // ---- the quick add target: own by default in the Basket, picked: Work · Projects -> POST there
    await go(ev, 'inbox', '#qinput');
    await ev(`(() => { const i = document.querySelector('#qinput'); i.focus(); i.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`); await sleep(300);
    check(/Base/.test(await ev(`document.querySelector('#qdchips .msvvqc')?.textContent || ''`)), '#661: the target chip names the own server in the Basket');
    await ev(`(() => { document.querySelector('#qdchips .msvvqc').click(); return 1; })()`); await sleep(400);
    await ev(`(() => { [...document.querySelectorAll('#pop [role="menuitem"]')].find(b => /Work/.test(b.textContent))?.click(); return 1; })()`); await sleep(500);
    await ev(`(() => { [...document.querySelectorAll('#pop [role="menuitem"]')].find(b => /Projects/.test(b.textContent))?.click(); return 1; })()`); await sleep(400);
    check(/Work · Projects/.test(await ev(`document.querySelector('#qdchips .msvvqc')?.textContent || ''`)), '#661: the picked target shows "→ Work · Projects"');
    const nOwn = await ev(`S.tasks.size`);
    await ev(`(async () => { const i = document.querySelector('#qinput'); i.value = 'Quick far tomorrow'; await submitQuick(i); return 1; })()`); await sleep(500);
    c = await calls(ev);
    const pq = c.filter(x => x.m === 'POST' && x.url === '/api/servers/1/tasks').pop();
    check(pq && pq.body.list_id === 11 && pq.body.title === 'Quick far' && pq.body.due === await ev(`addDays(today(), 1)`), '#661: the quick add goes to the picked server + list with title + date ' + JSON.stringify(pq));
    check(await ev(`S.tasks.size`) === nOwn, '#661: no own task was created');
    // ---- Search: the other servers as sections below
    await go(ev, 'search', '#searchq');
    await ev(`(() => { document.querySelector('#searchq').value = 'Searched'; doSearch('Searched'); return 1; })()`); await sleep(900);
    const se = await ev(`(() => ({hit: !!document.querySelector('#msvvsearch .trow[data-msv="1:150"] .msvb'), off: /Club/.test(document.querySelector('#msvvsearch')?.textContent || '') && !!document.querySelector('#msvvsearch .msvverr'), heads: document.querySelectorAll('#msvvsearch .msvvgh').length}))()`);
    check(se.hit && se.off && se.heads === 2, '#661: search sections per server ' + JSON.stringify(se));
    // ---- News: a section per server, a click reads it and opens the task
    await go(ev, 'news', '.msvvni');
    const nw = await ev(`(() => { const b = document.querySelector('.msvvni[data-msvn="1:5"]'); return {b: !!b?.querySelector('.msvb'), txt: b?.textContent || '', bold: !!b?.querySelector('b')}; })()`);
    check(nw.b && /News W <b>x<\/b>/.test(nw.txt) && !nw.bold, '#661: foreign news with badge, as text ' + JSON.stringify(nw));
    await ev(`(() => { document.querySelector('.msvvni[data-msvn="1:5"]').click(); return 1; })()`); await sleep(700);
    c = await calls(ev);
    const rd = c.find(x => x.url === '/api/servers/1/news/read');
    check(rd && JSON.stringify(rd.body.ids) === '[5]' && await ev(`!!document.querySelector('.msvvdlg')`), '#661: a news click reads it there and opens the task ' + JSON.stringify(rd));
    await ev(`(() => { document.querySelector('.msvvdlg')?.remove(); return 1; })()`);
    // ---- Calendar: the foreign event and the due task in the month
    await go(ev, 'cal', '#view .cal');
    await sleep(800);
    const cl = await ev(`(() => ({ev: [...document.querySelectorAll('#view .cal .ev.msvev')].map(e => e.textContent), day: !!document.querySelector('#view .agenda .msvvcal')}))()`);
    check(cl.ev.some(t => /Meeting W/.test(t)) && cl.ev.some(t => /Report/.test(t)), '#661: calendar shows foreign events + tasks ' + JSON.stringify(cl));
    await ev(`(() => { S.calMode = 'week'; S.calSel = today(); renderView(); return 1; })()`); await sleep(600);
    const wk = await ev(`[...document.querySelectorAll('#view .week .ev.msvev')].map(e => e.textContent)`);
    check(wk.some(t => /Meeting W/.test(t)) && wk.some(t => /Report/.test(t)), '#661: the week view too (all-day row) ' + JSON.stringify(wk));
    await ev(`(() => { S.calMode = 'month'; LS.set('calMode', 'month'); return 1; })()`);
    // ---- Move an own task to another server: the menu entry, the plain question, the call
    await go(ev, 'inbox', `#view .trow[data-id="${OWN}"]`);
    await ev(`(() => { taskMenu(document.querySelector('#view .trow[data-id="${OWN}"] .ttl'), ${OWN}); return 1; })()`); await sleep(400);
    check(await ev(`[...document.querySelectorAll('#pop [role="menuitem"]')].some(b => /Move to another server/.test(b.textContent))`), '#661: the task menu offers "Move to another server…"');
    await ev(`(() => { [...document.querySelectorAll('#pop [role="menuitem"]')].find(b => /Move to another server/.test(b.textContent))?.click(); return 1; })()`); await sleep(500);
    await ev(`(() => { const s = document.querySelector('#msvvmv-s'); s.value = '1'; s.dispatchEvent(new Event('change')); const l = document.querySelector('#msvvmv-l'); l.value = '11'; document.querySelector('.msvvmv button[type="submit"]').click(); return 1; })()`); await sleep(500);
    const q = await ev(`document.querySelector('.cdlg #cdlg-b')?.textContent || ''`);
    check(/created anew on Work/.test(q) && /stay on Base in the trash/.test(q), '#661: the move question in plain words ' + JSON.stringify(q));
    check(!/leaves the organisation/.test(q), '#661 review question 1: a private task says nothing about an organisation');
    await ev(`(() => { window.__toasts = []; const T0 = window.toast; window.toast = (...a) => { __toasts.push(String(a[0])); return T0(...a); }; document.querySelector('.cdlg [data-cd="yes"]').click(); return 1; })()`); await sleep(800);
    const tsts = await ev(`window.__toasts`);
    check(tsts.some(x => /2 subtasks could not be created on Work/.test(x)), '#661 review N3: the toast names the subtasks the other server did not take ' + JSON.stringify(tsts));
    c = await calls(ev);
    const mv = c.find(x => x.url === '/api/servers/move');
    check(mv && mv.body.from.server === 0 && mv.body.from.task === OWN && mv.body.to.server === 1 && mv.body.to.list_id === 11, '#661: the move call ' + JSON.stringify(mv));
    // ---- unlinked again: everything gone
    await link(ev, 0);
    await go(ev, 'inbox', '#view .trow');
    check(await ev(`!document.querySelector('.msvb, .sg-msv, .msvvqc, [data-msv]')`), '#661: after unlinking no badges, groups or foreign rows');
  };
  const phone = async o => {
    const {cmd, ev, nav, shot} = o;
    await cmd('browsingContext.setViewport', {context: o.ctx, viewport: {width: 390, height: 844}});
    check(await ffLogin(o) === 200, 'phone: login');
    await nav(B + '#today'); await ready(ev, '#view');
    await ev(MOCK); await link(ev, 2);
    await go(ev, 'today', '#view [data-msv="1:100"]');
    const b = await ev(`(() => { const e = document.querySelector('#view .trow[data-msv="1:100"] .msvb'), r = e?.getBoundingClientRect(); return r ? {w: r.width, l: r.left, r: r.right, vw: innerWidth, vis: getComputedStyle(e).visibility} : null; })()`);
    check(b && b.w > 8 && b.l >= 0 && b.r <= b.vw && b.vis === 'visible', '#661: phone: the badge stays visible on a narrow row ' + JSON.stringify(b));
    await shot('p273c-today-390.png');
    await ev(`(() => { document.querySelector('#view .trow[data-msv="1:100"] .ttl').click(); return 1; })()`); await ready(ev, '.msvvdlg #msvvd-n');
    const t = await ev(`(() => { const bs = [...document.querySelectorAll('.msvvdlg .foot .btn')].map(x => x.getBoundingClientRect().height); return bs.length ? Math.min(...bs) : 0; })()`);
    check(t >= 40, '#661: phone: the buttons of the details are big targets ' + t);
    await shot('p273c-detail-390.png');
    await ev(`(() => { document.querySelector('.msvvdlg')?.remove(); openQuickSheet(); return 1; })()`); await sleep(500);
    check(/Base/.test(await ev(`document.querySelector('.qadd.sheet .msvvqc')?.textContent || ''`)), '#661: phone: the quick add sheet shows the target');
    await shot('p273c-sheet-390.png');
  };
  await firefox(desk, false);
  await firefox(phone, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
