// 2.43.0 UI tests, part D, own container (start.sh), Firefox (desktop, mouse):
// - #1434 a click on "Tracked" in the project header opens "Tracked time · name" with the sum, the split by person / task and
//   the latest entries; "Delete all times of this project" needs the typed project name, one Undo brings the entries back
// - #1500 a task in its own window: the task menu has "Open in its own window", the panel has the button, a middle click on the row
//   calls window.open with kalmido-task-<id>; the window shows only the task panel; a deleted task shows a note
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2430_d_ui', check, shots: 'P2430D_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const FEAT = 'comments,collab,time,progress';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['cal', 'comments', 'time']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const L = (await call(CA, 'POST', '/api/lists', {name: 'Harbour site', kind: 'project', time_tracking: true})).id;
  const T = (await call(CA, 'POST', '/api/tasks', {title: 'Survey the quay', list_id: L})).id;
  const T2 = (await call(CA, 'POST', '/api/tasks', {title: 'Soon gone', list_id: L})).id;
  for (const [d, m] of [[1, 60], [2, 90]]) await call(CA, 'POST', '/api/time/entries', {task_id: T, start: `2026-09-0${d}T08:00:00Z`, end: `2026-09-0${d}T${9 + (m > 60 ? 1 : 0)}:${m > 60 ? '30' : '00'}:00Z`});

  await firefox(async o => {
    const {cmd, ev, ctx, nav, shot} = o;
    const until = async (expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 800}});
    await nav(B + '#l/' + L);
    check(await until(`!!document.querySelector('#view .lhead .tsum[data-tsum]')`, 60), '#1434: the header shows Tracked (clickable)');
    await ev(`document.querySelector('#view .lhead .tsum').click()`);
    check(await until(`!!document.querySelector('.tzmodal') && /2\\.5 h/.test(document.querySelector('.tzmodal .tzsum')?.textContent || '')`, 40), '#1434: the window opens with the sum (2.5 h)');
    const txt = await ev(`document.querySelector('.tzmodal')?.textContent || ''`);
    check(/Alice/.test(txt) && /Survey the quay/.test(txt) && /Tracked time/.test(txt), '#1434: by person, by task, title ' + txt.slice(0, 200));
    check(await ev(`/export\\.csv/.test(document.querySelector('#tz-csv')?.getAttribute('href') || '')`), '#1434: CSV link');
    await shot('p2430d-tracked.png');
    // delete all: the button stays disabled until the name is typed
    await ev(`document.querySelector('.tzmodal [data-m=tz-wipe]').click()`);
    check(await until(`!!document.querySelector('#tz-conf')`), '#1434: the delete dialog opens');
    check(await ev(`document.querySelector('.modal [data-m=go]').disabled === true`), '#1434: Delete is off before the name is typed');
    await ev(`(() => { const i = document.querySelector('#tz-conf'); i.value = 'Harbour site'; i.dispatchEvent(new Event('input')); return 1; })()`);
    check(await ev(`document.querySelector('.modal [data-m=go]').disabled === false`), '#1434: Delete is on after the name');
    await ev(`document.querySelector('.modal [data-m=go]').click()`);
    check(await until(`(async () => (await fetch('/api/time/entries?scope=all&lists=${L}').then(r => r.json())).entries.length === 0)()`), '#1434: the entries are gone');
    // Undo
    check(await until(`!![...document.querySelectorAll('#toast button, .toast button')].find(b => /Undo/i.test(b.textContent))`, 20), '#1434: an Undo offer');
    await ev(`[...document.querySelectorAll('#toast button, .toast button')].find(b => /Undo/i.test(b.textContent)).click()`);
    check(await until(`(async () => (await fetch('/api/time/entries?scope=all&lists=${L}').then(r => r.json())).entries.length === 2)()`), '#1434: Undo brings both entries back');

    // ================= #1500
    await nav(B + '#l/' + L);
    check(await until(`!!document.querySelector('#view .trow[data-id="${T}"]')`, 40), '#1500: the list');
    await ev(`(() => { window._wo = []; window.open = (u, n, f) => { window._wo.push([u, n, f]); return {focus() {}}; }; return 1; })()`);
    await ev(`(() => { taskMenu(document.querySelector('#view .trow[data-id="${T}"]'), ${T}); return 1; })()`); await sleep(400);
    check(await ev(`(() => { const b = [...document.querySelectorAll('#pop .mi, #pop button')].find(x => /Open in its own window/.test(x.textContent)); if (!b) return false; b.click(); return window._wo.length === 1; })()`), '#1500: the task menu has "Open in its own window"');
    const wo = await ev(`window._wo`);
    check(wo[0] && wo[0][0] === `/?mini=1#t/${T}` && wo[0][1] === `kalmido-task-${T}`, '#1500: window.open with the task address and name ' + JSON.stringify(wo));
    // a middle click on the row
    const rc = await ev(`(() => { const r = document.querySelector('#view .trow[data-id="${T}"] .ttl, #view .trow[data-id="${T}"]').getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2}; })()`);
    await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'pm', parameters: {pointerType: 'mouse'}, actions: [{type: 'pointerMove', x: Math.round(rc.x), y: Math.round(rc.y)}, {type: 'pointerDown', button: 1}, {type: 'pointerUp', button: 1}]}]});
    await cmd('input.releaseActions', {context: ctx}); await sleep(500);
    check(await ev(`window._wo.length`) === 2, '#1500: a middle click on the row opens the window');
    // the button in the panel
    await ev(`openDetail(${T})`); await sleep(500);
    check(await ev(`!!document.querySelector('#detail [data-mwtask="${T}"]')`), '#1500: the panel has the button');
    await ev(`document.querySelector('#detail [data-mwtask="${T}"]').click()`); await sleep(300);
    check(await ev(`window._wo.length`) === 3, '#1500: the button opens the window');

    // the task window
    await ev(`(() => { localStorage.setItem('tasks.lastKey', '"today"'); return 1; })()`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1000, height: 700}});
    await nav(B + `?mini=1#t/${T}`);
    check(await until(`!!document.querySelector('#detail:not(.hidden) #d-title')`, 60), '#1500: the task window shows the panel');
    const mv = await ev(`(() => ({mini: document.documentElement.classList.contains('mini-task'), side: getComputedStyle(document.getElementById('side')).display, main: getComputedStyle(document.getElementById('main')).display,
      title: document.getElementById('d-title').value, wt: document.title, btn: !!document.querySelector('#detail [data-mwtask]') && getComputedStyle(document.querySelector('#detail [data-mwtask]')).display !== 'none'}))()`);
    check(mv.mini && mv.side === 'none' && mv.main === 'none' && mv.title === 'Survey the quay' && /Survey the quay/.test(mv.wt) && !mv.btn, '#1500: only the task, its title ' + JSON.stringify(mv));
    check(await ev(`localStorage.getItem('tasks.lastKey')`) === '"today"', '#1500: the window does not write the main window\'s last view');
    // live: a rename elsewhere arrives
    await call(CA, 'PATCH', `/api/tasks/${T}`, {title: 'Survey the quay (new)'});
    check(await until(`document.getElementById('d-title')?.value === 'Survey the quay (new)'`, 60), '#1500: live update');
    await shot('p2430d-taskwin.png');
    // a deleted task: a note
    await nav(B + `?mini=1#t/${T2}`);
    check(await until(`!!document.querySelector('#detail #d-title')`, 60), '#1500: second task shows');
    await call(CA, 'DELETE', `/api/tasks/${T2}`);
    check(await until(`!!document.querySelector('#detail .mwgone')`, 80), '#1500: a deleted task shows a note');
    await shot('p2430d-taskgone.png');
  }, false);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
