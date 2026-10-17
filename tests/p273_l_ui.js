// 2.73.0 UI test of the release (#661), own container (start.sh with the app's own address allowed + a server key), Firefox:
// part A's real server routes together with part C's merged view. The test server connects to itself as "the other server"
// (Bob's account), Alice sees Bob's tasks in Today and the sidebar with the badge, completes one there (done on Bob's side),
// adds one through the quick add target (lands in Bob's list), finds Bob's task in the search and moves an own task over
// (Bob has it, hers is in the trash). No token in the page.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p273_l_ui', check, shots: 'P273L_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const EXTRA = (process.env.EXTRA || '') + ' -e KALMIDO_CALENDAR_ALLOW_HOSTS=127.0.0.1 -e KALMIDO_SECRET_KEY=AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=';
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA}});
let CK, CB;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return Array.isArray(j) ? j : {...j, _status: r.status}; };
const recode = (code, u) => { const j = JSON.parse(Buffer.from(code.slice('kalmido-link:'.length), 'base64url').toString()); return {t: j.t, code: 'kalmido-link:' + Buffer.from(JSON.stringify({u, t: j.t})).toString('base64url')}; };
const day = (n = 0) => { const d = new Date(Date.now() + n * 864e5); return d.toISOString().slice(0, 10); };
const bobTasks = async () => { const j = await call('GET', '/api/state', null, CB); return j.tasks || []; };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  CB = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'}, CB);
  const BL = await call('POST', '/api/lists', {name: 'Bob project'}, CB);
  check(BL.id, 'bob has a list ' + JSON.stringify(BL));
  const BT = await call('POST', '/api/tasks', {title: 'Bob due today', list_id: BL.id, due: day()}, CB);
  await call('POST', '/api/tasks', {title: 'Bob searchable zebra', list_id: BL.id}, CB);
  const bc = await call('POST', '/api/servers/code', {name: 'Alice'}, CB);
  check(bc._status === 201 && bc.code, 'bob makes a connection code');
  const {code, t: TOK} = recode(bc.code, 'http://127.0.0.1:3040');
  const ln = await call('POST', '/api/servers', {code, name: 'Remote', short: 'RM'});
  check(ln.id && ln.short === 'RM', 'alice links bob\'s account ' + JSON.stringify(ln));
  const SID = ln.id;
  const OWN = (await call('POST', '/api/tasks', {title: 'Alice moves this', notes: 'carry me'})).id;

  const ready = async (ev, sel, n = 60) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('${sel}')`).catch(() => false)); i++) await sleep(250); await sleep(400); };
  const desk = async o => {
    const {cmd, ev, nav, shot} = o;
    await cmd('browsingContext.setViewport', {context: o.ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'login');
    await nav(B + '#today');
    await ready(ev, `#view .trow[data-msv="${SID}:${BT.id}"]`);
    const td = await ev(`(() => { const r = document.querySelector('#view .trow[data-msv="${SID}:${BT.id}"]'); return {b: r?.querySelector('.msvb')?.textContent, t: r?.textContent || ''}; })()`);
    check(td.b === 'RM' && /Bob due today/.test(td.t), '#661: Today shows bob\'s task with the badge ' + JSON.stringify(td));
    const sg = await ev(`(() => { const g = document.querySelector('#side .sg-msv'); return {b: g?.querySelector('.msvb')?.textContent, t: g?.textContent || ''}; })()`);
    check(sg.b === 'RM' && /Bob project/.test(sg.t), '#661: the sidebar group lists bob\'s lists ' + JSON.stringify(sg));
    check(await ev(`!document.documentElement.innerHTML.includes(${JSON.stringify(TOK)})`), '#661: no token in the page');
    await shot('p273l-today.png');
    // complete it through the details -> done on bob's side
    await ev(`(() => { document.querySelector('#view .trow[data-msv="${SID}:${BT.id}"] .ttl').click(); return 1; })()`);
    await ready(ev, '.msvvdlg [data-msvd="toggle"]');
    await ev(`(() => { document.querySelector('.msvvdlg [data-msvd="toggle"]').click(); return 1; })()`); await sleep(1500);
    const bt = (await bobTasks()).find(t => t.id === BT.id);
    check(!bt || bt.status === 2, '#661: completed in the merged view = done on bob\'s server ' + JSON.stringify(bt));
    // quick add into bob's list through the target chip
    await nav(B + '#inbox'); await ready(ev, '#qinput');
    await ev(`(() => { const i = document.querySelector('#qinput'); i.focus(); i.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`); await sleep(400);
    await ev(`(() => { document.querySelector('#qdchips .msvvqc')?.click(); return 1; })()`); await sleep(500);
    await ev(`(() => { [...document.querySelectorAll('#pop [role="menuitem"]')].find(b => /Remote/.test(b.textContent))?.click(); return 1; })()`); await sleep(500);
    await ev(`(() => { [...document.querySelectorAll('#pop [role="menuitem"]')].find(b => /Bob project/.test(b.textContent))?.click(); return 1; })()`); await sleep(400);
    check(/Remote · Bob project/.test(await ev(`document.querySelector('#qdchips .msvvqc')?.textContent || ''`)), '#661: the target chip shows bob\'s list');
    await ev(`(async () => { const i = document.querySelector('#qinput'); i.value = 'Typed for Bob'; await submitQuick(i); return 1; })()`); await sleep(1500);
    const qa = (await bobTasks()).find(t => t.title === 'Typed for Bob');
    check(qa && qa.list_id === BL.id, '#661: the quick add landed in bob\'s list ' + JSON.stringify(qa));
    check(!(await call('GET', '/api/state')).tasks.some(t => t.title === 'Typed for Bob'), '#661: ... and not on alice\'s side');
    // search finds bob's task in his section
    await ev(`(() => { location.hash = 'search'; return 1; })()`); await sleep(600);
    await ev(`(() => { const q = document.querySelector('#searchq'); if (q) q.value = 'zebra'; doSearch('zebra'); return 1; })()`);
    await ready(ev, '#msvvsearch .trow[data-msv]');
    check(/Bob searchable zebra/.test(await ev(`document.querySelector('#msvvsearch')?.textContent || ''`)), '#661: the search shows bob\'s hit');
    // move an own task over
    await nav(B + '#inbox'); await ready(ev, `#view .trow[data-id="${OWN}"]`);
    await ev(`(() => { taskMenu(document.querySelector('#view .trow[data-id="${OWN}"] .ttl'), ${OWN}); return 1; })()`); await sleep(500);
    await ev(`(() => { [...document.querySelectorAll('#pop [role="menuitem"]')].find(b => /Move to another server/.test(b.textContent))?.click(); return 1; })()`); await sleep(800);
    await ev(`(() => { const s = document.querySelector('#msvvmv-s'); s.value = '${SID}'; s.dispatchEvent(new Event('change')); return 1; })()`); await sleep(1200);
    await ev(`(() => { const l = document.querySelector('#msvvmv-l'); l.value = '${BL.id}'; document.querySelector('.msvvmv button[type="submit"]').click(); return 1; })()`); await sleep(800);
    check(/created anew on Remote/.test(await ev(`document.querySelector('.cdlg #cdlg-b')?.textContent || ''`)), '#661: the move question names the target');
    await ev(`(() => { document.querySelector('.cdlg [data-cd="yes"]')?.click(); return 1; })()`); await sleep(2000);
    const mv = (await bobTasks()).find(t => t.title === 'Alice moves this');
    check(mv && mv.list_id === BL.id, '#661: the moved task is on bob\'s server ' + JSON.stringify(mv));
    const own = (await call('GET', '/api/state')).tasks.find(t => t.id === OWN);
    check(!own, '#661: ... and alice\'s copy left her open tasks (trash)');
    await shot('p273l-moved.png');
  };
  await firefox(desk, false);
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
