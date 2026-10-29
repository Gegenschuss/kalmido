// kalmido-suite: fresh
// 2.380 part E UI tests (#3416 sticky column head of the list view, #3331 figure line above the undo message, #3449 keyboard switch in the chat
// menus, #3465 "Attached tables" wording). Own container, Firefox with a touch screen (1280 px, then 390 px).
// freelancer-matrix: tasks (alice has no organisation). P2380RE_NOSTART=1 = the server runs.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2380r_e_ui', check, shots: 'P2380RE_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2380RE_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', modules: ['cal', 'comments', 'sheets']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const P = (await call('POST', '/api/lists', {name: 'Releases', kind: 'project'})).id;
  const fd = await call('POST', `/api/lists/${P}/fields`, {name: 'Package', type: 'text'});
  check(fd.http < 300, 'a field ' + fd.http);
  for (let i = 1; i <= 40; i++) await call('POST', '/api/tasks', {title: 'Task ' + i, list_id: P});
  const ready = async (ev, expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 800}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.fcols.${P}', 'true'); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    // ---- #3416: the column head stays at the top of the scroll box
    await nav(B + '#l/' + P);
    check(await ready(ev, `!!document.querySelector('.fcolhead') && document.querySelectorAll('#view .fcols').length > 10`), '#3416: list with columns shown');
    check(await ev(`getComputedStyle(document.querySelector('.fcolhead')).position === 'sticky'`), '#3416: the head is sticky');
    await ev(`(() => { document.querySelector('#view').scrollTop = 600; return 1; })()`);
    await sleep(300);
    const g = await ev(`(() => { const h = document.querySelector('.fcolhead').getBoundingClientRect(), v = document.querySelector('#view').getBoundingClientRect(); return [Math.round(h.top - v.top), document.querySelector('#view').scrollTop, getComputedStyle(document.querySelector('.fcolhead')).backgroundColor]; })()`);
    check(g[1] > 100 && g[0] >= 0 && g[0] <= 4, '#3416: after scrolling the head is still at the top ' + JSON.stringify(g));
    check(!/rgba\(0, 0, 0, 0\)|transparent/.test(g[2]), '#3416: the head has its own background ' + g[2]);
    await shot('p2380r-e-colhead.png');
    await ev(`localStorage.setItem('tasks.theme', '"dark"'); 1`);
    await nav(B + '#l/' + P);
    await ready(ev, `!!document.querySelector('.fcolhead')`);
    await ev(`(() => { document.querySelector('#view').scrollTop = 600; return 1; })()`);
    await sleep(300);
    check(await ev(`(() => { const h = document.querySelector('.fcolhead').getBoundingClientRect(), v = document.querySelector('#view').getBoundingClientRect(); return h.top - v.top <= 4; })()`), '#3416: dark: the head stays too');
    await ev(`localStorage.setItem('tasks.theme', '"light"'); 1`);

    // ---- #3465: wording
    await nav(B + '#l/' + P);
    await ready(ev, `typeof listMenuItems === 'function' && !!document.querySelector('#view')`);
    check(await ev(`listMenuItems(${P}).some(x => x.label === 'Attached tables')`), '#3465: list menu entry "Attached tables"');
    await nav(B + '#sheets/l/' + P);
    check(await ready(ev, `/Attached to Releases/.test(document.querySelector('.shvh')?.textContent || '')`), '#3465: heading "Attached to Releases"');
    check(await ev(`[...document.querySelectorAll('.shvtop a')].some(a => a.textContent === 'All tables' && a.getAttribute('href') === '#sheets')`), '#3465: link "All tables"');
    check(await ev(`/Tables are independent/.test(document.querySelector('#view').textContent) && /Attach a new table/.test(document.querySelector('[data-shv="new"]').textContent)`), '#3465: empty state explains, button "Attach a new table"');

    // ---- #3449: the keyboard switch (same setting as Settings > Chat)
    await nav(B + '#today');
    await ready(ev, `typeof kbd_item === 'function'`);
    check(await ev(`matchMedia('(pointer:coarse)').matches && kbd_item('agent').length === 1 && kbd_item('team').length === 1`), '#3449: touch device: both menus carry the entry');
    check(await ev(`kbd_item('agent')[0].on === true`), '#3449: default on');
    await ev(`kbd_item('agent')[0].fn(); 1`);
    await sleep(500);
    const st = await ev(`fetch('/api/state').then(r => r.json()).then(j => j.me && j.settings ? j.settings.chat_kbd_agent : (j.me || {}).chat_kbd_agent)`);
    check(await ev(`S.settings.chat_kbd_agent === '0' && kbd_item('agent')[0].on === false`) && (st === '0' || st === undefined), '#3449: switched off and saved ' + st);
    check(await ev(`S.settings.chat_kbd_team !== '0'`), '#3449: the team chat switch is separate');
    check(await ev(`(() => { kbd_toggle('team'); return S.settings.chat_kbd_team === '0'; })()`), '#3449: team switch toggles');
    check(await ev(`kbd_close('agent') === false`), '#3449: switch off: the keyboard stays');

    // ---- #3331: both messages at 390 px
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 800}});
    await nav(B + '#today');
    await ready(ev, `typeof celebrate === 'function' && typeof toast === 'function'`);
    await ev(`(() => { toast('Task with a rather long title that is undone', () => {}, 20000); celebrate('today', {force: true}); return 1; })()`);
    await sleep(900);
    const rc = await ev(`(() => { const a = document.querySelector('#toast').getBoundingClientRect(), b = document.querySelector('.cele-quip').getBoundingClientRect(); return [a.top, a.bottom, b.top, b.bottom, b.left, b.right, innerWidth]; })()`);
    check(rc[3] <= rc[0] + 0.5, '#3331: the figure line sits above the undo message ' + JSON.stringify(rc));
    check(rc[4] >= 0 && rc[5] <= rc[6], '#3331: inside the screen at 390 px');
    await shot('p2380r-e-toasts.png');
    await ev(`(() => { document.querySelector('#toast').classList.add('hidden'); celebrate('today', {force: true}); return 1; })()`);
    await sleep(900);
    check(await ev(`document.querySelector('.cele-quip').style.bottom === ''`), '#3331: without the undo message it stays at the bottom');
  }, true);
  console.log(`p2380r_e_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
