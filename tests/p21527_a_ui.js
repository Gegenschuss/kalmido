// 2.152.7 (#2710) UI tests: picking a priority in a task's panel on a phone. Own container (start.sh), Firefox. Invented people only.
// freelancer-matrix: tasks (the person, carol, has no organisation)
// - phone (390 px, touch): a tap on the priority button opens the choice sheet, a tap on "High" saves it and the task panel
//   stays open (like the date), opened from a project, as a subtask, from Today and in a project shared by someone else
// - a Back step that lands on the open task's own history entry keeps the task open (the guard in detail.js), Back closes it
// - computer (1280 px, mouse): unchanged, the panel stays open and the priority is saved
// P21527A_NOSTART=1 = the server already runs. Screenshots: P21527A_SHOTS (a screenshot run of the UI test runner).
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21527_a_ui', check, shots: 'P21527A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21527A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => {
  for (let i = 0; ; i++) {
    const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined});
    if (r.status === 429 && i < 8) { await sleep(500 * (i + 1)); continue; }
    const j = await r.json().catch(() => ({})); return {...j, http: r.status};
  }
};

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call(CA, 'POST', '/api/users', {username: 'carol', display_name: 'Carol Solo', password: 'password123', email: 'carol@example.com'});
  const CC = await login('carol');
  await call(CC, 'PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  check(!((await call(CC, 'GET', '/api/state')).me.workspaces || []).length, 'P4: carol has no organisation');
  const L = (await call(CC, 'POST', '/api/lists', {name: 'Groceries'})).id;
  const T = (await call(CC, 'POST', '/api/tasks', {title: 'Return the bottles', list_id: L})).id;
  await call(CC, 'POST', '/api/tasks', {title: 'Buy milk', list_id: L});
  check(L > 0 && T > 0, 'a list with two tasks');
  const prio = async () => ((await call(CC, 'GET', '/api/state')).tasks || []).find(t => t.id === T)?.priority;

  const ready = async (ev, expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = ev => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'carol', password: 'password123'})}).then(r => r.status)`);
  const view = async (ev, nav, w) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await signIn(ev) === 200, `${w} px: carol signs in`);
    await nav(B + '#l/' + L);
    return ready(ev, `!!document.querySelector('#view .trow[data-id="${T}"]')`);
  };
  // the middle of the first element that matches (null = not there / not visible)
  const mid = (ev, sel) => ev(`(() => { const e = [...document.querySelectorAll(${JSON.stringify(sel)})].find(x => x.getClientRects().length); if (!e) return null; const b = e.getBoundingClientRect(); return {x: b.left + b.width / 2, y: b.top + b.height / 2}; })()`);
  // diagnosis: who closes the panel (stack), the Back steps
  const trace = ev => ev(`(() => { window.__p21527 = []; const cd = window.closeDetail; window.closeDetail = function (...a) { window.__p21527.push('closeDetail ' + (new Error().stack || '').split('\\n').slice(1, 6).join(' < ')); return cd.apply(this, a); };
    addEventListener('popstate', e => window.__p21527.push('popstate ' + JSON.stringify(e.state)), true); return 1; })()`);
  const open = (ev, mobile) => ev(`(() => { const s = document.getElementById('detail'); return !!S.sel && S.sel === ${T} && !!s && s.classList.contains('open') && !s.classList.contains('hidden')${mobile ? '' : ''}; })()`);

  // more places the task opens from: a subtask, the Today view, a project shared by alice, the start page
  const S1 = (await call(CC, 'POST', '/api/tasks', {title: 'Rinse the crates', list_id: L, parent_id: T})).id;
  const D = (await call(CC, 'POST', '/api/tasks', {title: 'Water the plants', list_id: L, due: new Date().toISOString().slice(0, 10)})).id;
  const LA = (await call(CA, 'POST', '/api/lists', {name: 'Shared errands'})).id;
  const carolId = (await call(CC, 'GET', '/api/state')).me.id;
  const shr = await call(CA, 'PUT', `/api/lists/${LA}/members`, {user_id: carolId, role: 'edit'});
  const A1 = (await call(CA, 'POST', '/api/tasks', {title: 'Post the letters', list_id: LA})).id;
  const prioOf = async id => ((await call(CC, 'GET', '/api/state')).tasks || []).find(t => t.id === id)?.priority;
  const CASES = [
    {name: 'list', hash: '#l/' + L, id: T, row: `#view .trow[data-id="${T}"] .ttl`, p: 5},
    {name: 'subtask', hash: '#l/' + L, id: S1, open: `#view .trow[data-id="${T}"] .ttl`, row: `#detail .subs .trow[data-id="${S1}"] .ttl`, p: 3},
    {name: 'today', hash: '#today', id: D, row: `#view .trow[data-id="${D}"] .ttl`, p: 5},
    {name: 'shared', hash: '#l/' + LA, id: A1, row: `#view .trow[data-id="${A1}"] .ttl`, p: 1},
  ];
  for (const c of CASES) {
    await firefox(async ({cmd, ev, ctx, nav, shot}) => {
      const tap = (x, y, hold = 60) => cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 't1', parameters: {pointerType: 'touch'}, actions: [{type: 'pointerMove', x: Math.round(x), y: Math.round(y)}, {type: 'pointerDown', button: 0}, {type: 'pause', duration: hold}, {type: 'pointerUp', button: 0}]}]}).then(() => cmd('input.releaseActions', {context: ctx}));
      const tapOn = async (sel, what) => { const m = await mid(ev, sel); check(!!m, `390 px ${c.name}: ${what} is there`); if (m) await tap(m.x, m.y); return !!m; };
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
      await nav(B + 'static/icon.svg');
      await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
      check(await signIn(ev) === 200, `390 px ${c.name}: carol signs in`);
      await nav(B + c.hash);
      check(await ready(ev, `!!document.querySelector(${JSON.stringify(c.open || c.row)})`), `390 px ${c.name}: the view shows the task`);
      await trace(ev);
      if (c.open) { await tapOn(c.open, 'the parent task'); await ready(ev, `!!document.querySelector(${JSON.stringify(c.row)})`, 20); await sleep(400); }
      // CI of 2.223.1: the view may still draw again right after it shows the task (Today on CI and under load; a tap during
      // that draw hits the old row): let it settle first
      await sleep(600);
      await tapOn(c.row, 'the task title');
      check(await ready(ev, `S.sel === ${c.id} && document.getElementById('detail').classList.contains('open')`, 20), `390 px ${c.name}: a tap on the task opens its panel`);
      await sleep(500);
      await tapOn(`#detail [data-act="prio"]`, 'the priority button');
      check(await ready(ev, `!document.getElementById('pop').classList.contains('hidden') && !!document.querySelector('#pop [role="menuitem"]')`, 20), `390 px ${c.name}: the priority sheet opens`);
      await sleep(400);
      await tapOn(`#pop [role="menuitem"].flag-${c.p}`, 'the priority in the sheet');
      await sleep(1500);
      const st = await ev(`JSON.stringify({log: window.__p21527, sel: S.sel, hist: history.length, state: history.state, open: document.getElementById('detail').className})`);
      check(await ev(`S.sel === ${c.id} && document.getElementById('detail').classList.contains('open')`), `390 px ${c.name}: the task panel stays open after picking a priority ` + st);
      check(await prioOf(c.id) === c.p, `390 px ${c.name}: the priority is saved`);
      check(await ev(`document.getElementById('pop').classList.contains('hidden')`), `390 px ${c.name}: the sheet is closed`);
      await shot(`phone-${c.name}`);
      if (c.name !== 'list') return;
      // a Back step that lands on the task's own entry (an overlay entry of the sheet taken away without backclose.js) keeps the
      // task open; the next Back closes it as before
      await ev(`(history.pushState({f8d: 1}, '', location.href), history.back(), 1)`);
      await sleep(600);
      check(await ev(`S.sel === ${c.id} && document.getElementById('detail').classList.contains('open')`), '390 px: a Back step onto the task\'s own entry keeps it open');
      await ev('(history.back(), 1)');
      check(await ready(ev, `!S.sel && !document.getElementById('detail').classList.contains('open')`, 20), '390 px: Back closes the task as before');
    }, true);
  }
  check(shr.ok, 'alice shares her project with carol');

  // ================= computer: 1280 px, mouse - unchanged
  await call(CC, 'PATCH', '/api/tasks/' + T, {priority: 0});
  await firefox(async ({cmd, ev, ctx, nav}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    check(await view(ev, nav, 1280), '1280 px: the list shows the task');
    await ev(`(document.querySelector('#view .trow[data-id="${T}"] .ttl').click(), 1)`);
    check(await ready(ev, `S.sel === ${T}`, 20), '1280 px: a click opens the task panel');
    await ev(`(document.querySelector('#detail [data-act="prio"]').click(), 1)`);
    check(await ready(ev, `!!document.querySelector('#pop:not(.hidden) [role="menuitem"].flag-3')`, 20), '1280 px: the priority menu opens');
    await ev(`(document.querySelector('#pop [role="menuitem"].flag-3').click(), 1)`);
    await sleep(1000);
    check(await open(ev, false), '1280 px: the task panel stays open');
    check(await prio() === 3, '1280 px: the priority "Medium" is saved');
  }, false);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
