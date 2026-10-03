// 2.13.3 UI tests (follow-up of #478, reported on a Galaxy Z Fold), own container (start.sh, isolated test database): one
// search entry per layout (the command-bar field at the top of the sidebar / drawer, no extra "Search" row; the header's
// command bar only while the sidebar is folded away), the + button gone in the tablet / Fold-portrait layout also after a
// rotation, and "No date" in the date popover removing date, time, start, reminders, repeat and the repeat reminder in one
// step and closing the popover (undo in the toast). jsdom + Firefox at 380 touch (drawer), Fold 904 x 904 / 904 x 680 /
// 680 x 904 touch, 1440 mouse. Screenshots with P2133_SHOTS=<dir>.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2133_ui', check, shots: 'P2133_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const ALL = 'cal,timeline,matrix,habits,pomo,kanban,collab,stats,time,progress,deps,fields,agents,comments';
const day = n => { const d = new Date(); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };

(async () => {
  await sleep(600);
  const SW = await (await fetch(B + 'sw.js')).text();
  check(/const CACHE = 'tasks-shell-v(?:8[6-9]|9[0-9])'/.test(SW), 'service worker cache v86');
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en', tour: 'done'});
  const L = (await call('POST', '/api/lists', {name: 'Home'})).id;
  const T = (await call('POST', '/api/tasks', {title: 'Dentist', list_id: L, due: day(2), due_time: '10:00', reminders: '0,60', nag: '15'})).id;
  const t0 = (await call('GET', '/api/state')).tasks.find(x => x.id === T);
  check(t0.due === day(2) && t0.due_time === '10:00' && t0.reminders && t0.nag, 'a task with date, time, reminders and a repeat reminder ' + JSON.stringify({due: t0.due, rem: t0.reminders, nag: t0.nag}));

  // ================= the sidebar has one search entry: the command-bar field
  let w = await boot({user: 'alice', hash: 'today'}), d = w.document;
  check(d.querySelectorAll('#side .scmd[data-act="palette"]').length === 1 && !d.querySelector('#side [data-go="search"]'), 'sidebar: the command-bar field is the only search entry (no extra "Search" row)');
  w.eval('openPalette()'); await sleep(200);
  w.document.querySelector('.palette .pqin').value = 'search'; w.document.querySelector('.palette .pqin').dispatchEvent(new w.Event('input', {bubbles: true})); await sleep(200);
  check([...d.querySelectorAll('.palette .pitem')].some(b => /^Search$/.test(b.querySelector('.plt')?.textContent || '')), 'the field still reaches the Search view (palette)');
  w.eval('closePalette()');

  // ================= "No date": everything date-related goes in one step, the popover closes, undo brings it back
  await w.eval(`go('l/${L}')`); await sleep(500);
  w.eval(`datePop(document.querySelector('#view .trow[data-id="${T}"]') || document.querySelector('#top h1'), ${T})`); await sleep(400);
  const nd = d.querySelector('#pop [data-q="x"]');
  check(nd && /No date/.test(nd.textContent), 'the date popover has "No date"');
  click(w, nd);
  check(await until(() => d.querySelector('#pop').classList.contains('hidden')), '"No date" closes the popover');
  const t1 = await until(async () => { const t = (await call('GET', '/api/state')).tasks.find(x => x.id === T); return !t.due && t; }, 60);
  check(t1 && !t1.due && !t1.due_time && !t1.reminders && !t1.nag && !t1.start, '"No date": date, time, reminders and repeat reminder removed in one step ' + JSON.stringify(t1 && {due: t1.due, time: t1.due_time, rem: t1.reminders, nag: t1.nag}));
  const tb = await until(() => /Undo/.test(d.querySelector('#toast button')?.textContent || '') && d.querySelector('#toast'), 40);
  check(tb && /Date removed/.test(tb.textContent), 'the toast says so and offers Undo: ' + (tb?.textContent || ''));
  if (tb) { d.querySelector('#toast button').click(); await sleep(900); }
  const t2 = (await call('GET', '/api/state')).tasks.find(x => x.id === T);
  check(t2.due === day(2) && t2.due_time === '10:00' && t2.reminders === t0.reminders && t2.nag === t0.nag, 'Undo brings date, time, reminders and the repeat reminder back ' + JSON.stringify({due: t2.due, rem: t2.reminders, nag: t2.nag}));
  w.close();
  check(!errs.length, 'jsdom: no JS errors ' + errs.join(' | '));

  // ================= Firefox: exactly one visible search entry per layout; the + button in the tablet / Fold portrait layout
  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); await sleep(700); };
  const SRCH = `(() => { const vis = e => { const r = e.getBoundingClientRect(), cs = getComputedStyle(e); return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && r.right > 1 && r.left < innerWidth - 1; };
    const el = [...document.querySelectorAll('[data-act="palette"], [data-go="search"]')].filter(vis);
    return {n: el.length, where: el.map(e => (e.closest('#side') ? 'side' : e.closest('#top') ? 'top' : e.closest('#tabs') ? 'tabs' : '?') + ':' + e.className.split(' ')[0])}; })()`;
  const fab = `(() => { const f = document.querySelector('#fab'); return !!f && getComputedStyle(f).display !== 'none' && !f.classList.contains('gone') && f.getBoundingClientRect().width > 0; })()`;
  for (const [vw, vh, touch, drawer] of [[380, 800, true, true], [904, 904, true, false], [904, 680, true, false], [680, 904, true, true], [1440, 900, false, false]]) await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    check(await ffLogin({ev, nav}) === 200, `${vw}x${vh}: login`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
    await nav(B + '#today'); await ready(ev);
    if (drawer) { await ev(`(() => { document.querySelector('#top .menu').click(); return 1; })()`); await sleep(700); }
    const s = await ev(SRCH);
    check(s.n === 1 && s.where[0] === 'side:scmd', `${vw}x${vh}${drawer ? ' (drawer open)' : ''}: exactly one search entry, the command-bar field in the sidebar ` + JSON.stringify(s));
    await shot(`p2133-${vw}x${vh}-search.png`);
    if (drawer) { await ev(`(() => { closeSide(); return 1; })()`); await sleep(400); }
    if (vw === 680) {
      check(!(await ev(fab)), '680 x 904 (Fold portrait, add bar): no + button');
      // rotate: landscape and back to portrait without a full render in between
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 904, height: 680}}); await sleep(700);
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 680, height: 904}}); await sleep(700);
      check(!(await ev(fab)), 'Fold portrait after rotating: still no + button');
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 380, height: 800}}); await sleep(900);
      check(await ev(fab), 'folded to a phone (380): the + button is back');
    }
  }, touch);

  console.log(`p2133_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
