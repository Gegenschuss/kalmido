// 2.34.0 UI tests, part B (#266 tasks lying idle, #269 time-tracking helper), own container (start.sh). Firefox, 390 x 844 touch:
// - the view "Lying idle" (#stale): a sidebar row with the number (only while something lies idle), the tasks with a chip
//   "Idle for N days", a one-time hint; a task changed here leaves the view at once
// - the list dialog: "Lying idle after" (default / days / never) saves stale_days; 30 days empties the view
// - the time page: the card "Maybe forgotten" with the working days without tracked time, "Add time" opens the entry dialog
//   on that day, the X dismisses it; the timesheet has "Copy as text" (date, task, duration, note, sums)
// Screenshots into $P2340B_SHOTS.
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2340_b_ui', check, shots: 'P2340B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const sql = (q, args = []) => execFileSync('python3', ['-c', 'import sqlite3,sys,json; c=sqlite3.connect(sys.argv[1]); c.execute(sys.argv[2], json.loads(sys.argv[3])); c.commit()',
  path.join(DATA, 'tasks.db'), q, JSON.stringify(args)]);
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const FEAT = 'cal,comments,collab,time,progress,agents,kanban,timeline,fields,team';
const ago = d => new Date(Date.now() - d * 86400000).toISOString().slice(0, 19) + '+00:00';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ME = (await call('GET', '/api/state')).me.id;
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  const L = (await call('POST', '/api/lists', {name: 'Client work', kind: 'project'})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: ag.id, role: 'edit'});
  const T1 = (await call('POST', '/api/tasks', {title: 'Offer for the kitchen', list_id: L})).id;
  const T2 = (await call('POST', '/api/tasks', {title: 'Plans from the architect', list_id: L})).id;
  const T3 = (await call('POST', '/api/tasks', {title: 'Fresh idea', list_id: L})).id;
  await call('PUT', `/api/tasks/${T2}/waiting`, {note: 'Architect Huber'});
  sql(`UPDATE tasks SET updated_at=?, created_at=? WHERE id IN (${T1}, ${T2})`, [ago(12), ago(12)]);
  sql(`UPDATE tasks SET waiting_at=? WHERE id=${T2}`, [ago(12)]);
  // a working day before today with a comment of alice but no time entry -> "Maybe forgotten"
  const g0 = await call('GET', '/api/time/gaps');
  let gd = new Date(g0.to + 'T12:00:00Z'); while ([0, 6].includes(gd.getUTCDay())) gd = new Date(gd - 86400000);
  const GD = gd.toISOString().slice(0, 10);
  sql('INSERT INTO comments(task_id, user_id, body, created_at) VALUES(?,?,?,?)', [T3, ME, 'sketched it', GD + 'T10:00:00+00:00']);
  const te = await call('POST', '/api/time/entries', {task_id: T3, minutes: 90, note: 'first draft', start: new Date().toLocaleDateString('sv', {timeZone: 'Europe/Berlin'}) + 'T08:00'});  // today in the app's time zone
  check(te.id || te.status < 300, 'setup: a time entry this week ' + JSON.stringify(te).slice(0, 120));

  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  const until = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  await firefox(async o => {
    const {cmd, ev, ctx, shot, nav} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    check(await ffLogin(o) === 200, 'login');
    await nav(B + '#stale'); await ready(ev);
    // ================= #266 the view
    const got = await until(ev, `document.querySelectorAll('#view .task[data-id]').length >= 2 || document.querySelectorAll('#view .trow[data-id]').length >= 2`);
    const v = await ev(`(() => { const ids = [...document.querySelectorAll('#view .trow[data-id]')].map(x => +x.dataset.id); const chip = document.querySelector('#view .stalem');
      const row = document.querySelector('#side [data-drop="stale"]');
      return {ids: [...new Set(ids)], chip: chip?.textContent || '', h1: document.querySelector('#top h1')?.textContent, hint: !!document.querySelector('.onehint[data-hint="stale"]'),
        side: row ? row.querySelector('.c')?.textContent : null, over: document.documentElement.scrollWidth <= 390}; })()`);
    check(got && v.ids.includes(T1) && v.ids.includes(T2) && !v.ids.includes(T3), '#266: the view shows the idle tasks only ' + JSON.stringify(v));
    check(/Idle for 1[12] days/.test(v.chip) && v.h1 === 'Lying idle' && v.hint && v.side === '2' && v.over, '#266: chip, title, hint, sidebar number ' + JSON.stringify(v));
    await shot('p2340b-390-stale.png');
    // a change here ends "lying idle" at once
    await ev(`(() => { patchUndoable(${T1}, {priority: 5}, 'x'); return 1; })()`);
    const gone = await until(ev, `![...document.querySelectorAll('#view .trow[data-id]')].some(x => +x.dataset.id === ${T1})`);
    check(gone, '#266: a task changed here leaves the view');
    // ================= #266 the list dialog
    await ev(`(() => { listModal(${L}); return 1; })()`);
    const dl = await until(ev, `!!document.querySelector('#l-stale')`);
    const opts = await ev(`[...document.querySelectorAll('#l-stale option')].map(o => o.value + '=' + o.textContent).join('|')`);
    check(dl && /^=Default \(7 days\)\|3=3 days\|5=5 days\|14=14 days\|30=30 days\|0=Never$/.test(opts), '#266: "Lying idle after" with default / days / never ' + opts);
    await ev(`(() => { const s = document.querySelector('#l-stale'); s.value = '30'; s.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    await sleep(1200);
    const lst = (await call('GET', '/api/state')).lists.find(x => x.id === L);
    check(lst && lst.stale_days === 30, '#266: the choice is saved (stale_days 30) ' + (lst && lst.stale_days));
    await ev(`(() => { document.querySelector('.modal [data-m="close"], .modal .mclose, .modal [aria-label="Close"]')?.click(); document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); return 1; })()`);
    await sleep(500);
    const empty = await until(ev, `![...document.querySelectorAll('#view .trow[data-id]')].some(x => +x.dataset.id === ${T2})`);
    check(empty, '#266: after 30 days as the threshold the view is empty');
    await call('PATCH', `/api/lists/${L}`, {stale_days: null});
    // ================= #269 the time page
    await nav(B + '#time'); await ready(ev);
    const card = await until(ev, `!!document.querySelector('.tvgaps li')`);
    const c1 = await ev(`(() => { const li = document.querySelector('.tvgaps li'), b = li?.querySelector('[data-act="tvg-add"]'), r = b?.getBoundingClientRect();
      return {n: document.querySelectorAll('.tvgaps li').length, d: b?.dataset.d, t: li?.querySelector('.tvg-t')?.textContent, h: Math.round(li?.getBoundingClientRect().height || 0), bw: Math.round(r?.width || 0), over: document.documentElement.scrollWidth <= 390}; })()`);
    check(card && c1.n === 1 && c1.d === GD && c1.t === 'Fresh idea' && c1.h >= 44 && c1.over, '#269: "Maybe forgotten" with the day and its task ' + JSON.stringify(c1) + ' ' + GD);
    await shot('p2340b-390-timegaps.png');
    await ev(`(() => { document.querySelector('.tvgaps [data-act="tvg-add"]').click(); return 1; })()`);
    const md = await until(ev, `!!document.querySelector('#te-date')`);
    const dv = await ev(`(() => { const i = document.querySelector('#te-date'); return i?.value || i?.dataset.value || ''; })()`);
    check(md && dv.includes(GD), '#269: "Add time" opens the entry dialog on that day ' + dv);
    await ev(`(() => { document.querySelector('.modal [data-m="close"]')?.click(); return 1; })()`); await sleep(400);
    await ev(`(() => { document.querySelector('.tvgaps [data-act="tvg-x"]').click(); return 1; })()`);
    check(await until(ev, `!document.querySelector('.tvgaps')`), '#269: X dismisses the card');
    // the timesheet as text
    await until(ev, `!document.querySelector('[data-act="tv-sheet"]')?.disabled`);
    await ev(`(() => { document.querySelector('[data-act="tv-sheet"]').click(); return 1; })()`);
    const ts = await until(ev, `!!document.querySelector('.tsheet [data-ts="copy"]')`);
    const txt = await ev(`timesheetText(S.tv.data, 'Alice')`);
    check(ts && /^Timesheet · .+ · Alice/.test(txt) && txt.includes('Client work') && /· Fresh idea · 1:30 · first draft/.test(txt) && /Sum: 1:30 \(1[.,]5/.test(txt) && /Total: 1:30/.test(txt),
      '#269: the timesheet as text (date, task, duration, note, sums) ' + JSON.stringify(txt));
    await ev(`(() => { document.querySelector('.tsheet [data-ts="close"]')?.click(); return 1; })()`);
  }, true);
  console.log(`p2340_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e); process.exit(1); });
