// Time tracking UI tests (jsdom), fresh DB on the test container: timer pill / chips / detail section,
// cross-device, offline start/stop, manual entry modal, delete + undo, reports view, timesheet, settings,
// list rate, statistics card, German texts, module off.
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json(); };
const until = async (fn, ms = 4000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (await fn()) return true; await sleep(100); } return false; };

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'});
  const BK = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'de'}, BK);
  const WORK = (await call('POST', '/api/lists', {name: 'Work', kind: 'project'})).id;
  const SH = (await call('POST', '/api/lists', {name: 'Shared', kind: 'project'}, BK)).id;
  await call('PUT', `/api/lists/${SH}/members`, {user_id: 1, role: 'edit'}, BK);
  const t1 = (await call('POST', '/api/tasks', {title: 'Write report', list_id: WORK})).id;
  const t2 = (await call('POST', '/api/tasks', {title: 'Review', list_id: WORK})).id;
  const ts = (await call('POST', '/api/tasks', {title: 'Shared job', list_id: SH}, BK)).id;
  // inside today (the report shows this week: right after midnight on a Monday, 3 h ago would be last week)
  const mid = new Date(); mid.setHours(0, 0, 0, 0); const since = Math.floor((Date.now() - mid) / 6e4);
  const BOBM = since >= 185 ? 45 : Math.max(1, Math.min(45, since - 1));  // 2.7.2: shorter right after midnight (the check below follows)
  await call('POST', '/api/time/entries', {task_id: ts, start: new Date(since >= 185 ? Date.now() - 3 * 36e5 : +mid).toISOString(), minutes: BOBM, note: 'bob work'}, BK);

  // ================= timer from the detail panel, pill, chips
  let w = await boot({user: 'alice', hash: 'l/' + WORK}); let d = w.document;
  check(d.querySelector('#side [data-go="time"]'), 'sidebar: Time tracking row');
  check(d.querySelector('#side [data-go="time"]'), 'sidebar: time row');
  w.eval(`openDetail(${t1})`); await sleep(700);
  check(d.querySelector('#d-time h5')?.textContent.startsWith('Time'), 'detail: Time section');
  d.querySelector('#d-time [data-act="timer-toggle"]').click();
  check(await until(() => d.querySelector('#top .tmini')), 'pill appears after start');
  check(/Write report/.test(d.querySelector('#top .tmini').textContent), 'pill shows the task');
  check(d.querySelector(`#view .trow[data-id="${t1}"] .tchip.live`), 'row chip: live');
  check(d.querySelector('#side [data-go="time"] .recdot'), 'sidebar: red dot while running');
  check(d.querySelector('#d-time .recon [data-timer-live]'), 'detail: stop button with live time');
  await sleep(2200);
  check(/^00:0[1-9]$/.test(d.querySelector('[data-timer-mini]').textContent), 'pill ticks: ' + d.querySelector('[data-timer-mini]').textContent);
  // second device sees it
  let w2 = await boot({user: 'alice', hash: 'today'});
  check(w2.document.querySelector('#top .tmini'), 'second device: pill');
  // stop from the pill menu on device 2
  w2.document.querySelector('#top .tmini').click(); await sleep(100);
  const stopBtn = [...w2.document.querySelectorAll('#pop .menu-list button')].find(b => /Stop timer/.test(b.textContent));
  check(stopBtn, 'pill menu: Stop timer'); stopBtn.click();
  check(await until(() => !w2.document.querySelector('#top .tmini')), 'device 2: pill gone after stop');
  check(/Timer stopped: 0:00/.test(w2.document.querySelector('#toast').textContent), 'stop toast');
  await w.eval('load().then(render)'); await sleep(300);
  check(!d.querySelector('#top .tmini'), 'device 1: pill gone after reload');
  let st = await call('GET', '/api/state');
  check(st.timer === null && st.time_totals[t1] && st.time_totals[t1][0] >= 2, 'server: timer stopped, total recorded');

  // ================= offline start / stop
  w.__offline = true;
  await w.eval(`timerStart({task_id: ${t2}})`); await sleep(200);
  check(w.eval('OUT.q.length') === 1 && d.querySelector('#top .tmini'), 'offline start: queued, pill shown');
  await sleep(2100);
  await w.eval('timerStop()'); await sleep(200);
  check(w.eval('OUT.q.length') === 2 && !d.querySelector('#top .tmini'), 'offline stop: queued, pill gone');
  // task created offline + timer on it (temp id mapped on replay)
  const tmp = (await w.eval(`api('POST', '/api/tasks', {title: 'Made offline', list_id: ${WORK}})`)).id;
  await w.eval(`timerStart({task_id: ${tmp}})`); await sleep(1100); await w.eval('timerStop()');
  w.__offline = false; await w.eval('flush()'); await sleep(1200);
  check(w.eval('OUT.q.length') === 0, 'outbox flushed');
  const e2 = (await call('GET', `/api/time/entries?task_id=${t2}`)).entries;
  check(e2.length === 1 && e2[0].seconds >= 2 && e2[0].seconds <= 4, 'offline entry: duration from device times ' + (e2[0] && e2[0].seconds));
  st = await call('GET', '/api/state');
  const mo = st.tasks.find(t => t.title === 'Made offline');
  check(mo && st.time_totals[mo.id], 'timer on a task created offline: mapped to the real id');

  // ================= manual entry modal, edit, delete + undo
  w.eval(`openDetail(${t2})`); await sleep(700);
  d.querySelector('#d-time [data-act="te-add"]').click(); await sleep(100);
  let md = [...d.querySelectorAll('.modal')].pop();
  check(md && md.querySelector('#te-target').value === 't:' + t2, 'add modal preselects the task');
  md.querySelector('#te-dur').value = '1:30'; md.querySelector('#te-note').value = 'manual one';
  md.querySelector('[data-m="save"]').click();
  check(await until(() => (d.querySelector('#d-time')?.textContent || '').includes('manual one')), 'manual entry listed in the detail');
  let ents = (await call('GET', `/api/time/entries?task_id=${t2}`)).entries;
  const man = ents.find(e => e.note === 'manual one');
  check(man && man.seconds === 5400 && man.source === 'manual', 'manual entry 1:30 on the server');
  w.eval(`entryModal(findEntry(${man.id}))`); await sleep(100);
  md = [...d.querySelectorAll('.modal')].pop();
  md.querySelector('#te-note').value = 'renamed note'; md.querySelector('[data-m="save"]').click();
  check(await until(async () => (await call('GET', `/api/time/entries?task_id=${t2}`)).entries.some(e => e.note === 'renamed note' && e.seconds === 5400)), 'edit note keeps the duration');
  await sleep(300);
  // explicit from-to crossing midnight
  w.eval(`entryModal(null, {task_id: ${t2}})`); await sleep(100);
  md = [...d.querySelectorAll('.modal')].pop();
  const y = w.eval(`addDays(today(), -2)`);
  md.querySelector('#te-date').value = y; md.querySelector('#te-from').value = '23:00'; md.querySelector('#te-to').value = '01:15';
  md.querySelector('[data-m="save"]').click(); await sleep(600);
  ents = (await call('GET', `/api/time/entries?task_id=${t2}`)).entries;
  check(ents.some(e => e.seconds === 8100), 'from 23:00 to 01:15 = next day, 2:15');
  // delete + undo
  await w.eval('load().then(render)'); await sleep(200); w.eval(`openDetail(${t2})`); await sleep(700);
  const n0 = ents.length;
  const del = d.querySelector('#d-time [data-act="te-del"]'); del.click();
  check(await until(async () => (await call('GET', `/api/time/entries?task_id=${t2}`)).entries.length === n0 - 1), 'delete');
  await until(async () => d.querySelector('#toast:not(.hidden) button') && /Time entry deleted/.test(d.querySelector('#toast').textContent));  // toast follows the server answer
  const ub = d.querySelector('#toast:not(.hidden) button');
  check(ub && /Time entry deleted/.test(d.querySelector('#toast').textContent), 'undo toast');
  ub?.click();
  check(await until(async () => (await call('GET', `/api/time/entries?task_id=${t2}`)).entries.length === n0), 'undo restores the entry');
  // others' entries: read-only
  w.eval(`openDetail(${ts})`); await sleep(800);
  const rows = d.querySelectorAll('#d-time .terow');
  check(rows.length === 1 && !rows[0].querySelector('[data-act="te-edit"]') && rows[0].querySelector('.who'), "bob's entry: shown with avatar, no edit buttons");
  check(new RegExp(`0:${String(BOBM).padStart(2, '0')} in total|\\b${BOBM}m in total`).test(d.querySelector('#d-time h5').textContent), 'section total: ' + d.querySelector('#d-time h5').textContent);
  w.eval('closeDetail()');
  // task menu
  w.eval(`taskMenu($('#top h1'), ${t1})`); await sleep(100);
  check([...d.querySelectorAll('#pop button')].some(b => b.textContent === 'Start time tracking') && [...d.querySelectorAll('#pop button')].some(b => /Add time/.test(b.textContent)), 'task menu: Start timer + Add time');
  w.eval('closePop()');

  // ================= reports view
  await call('PATCH', `/api/lists/${WORK}`, {rate: 60});
  w.location.hash = 'time'; await sleep(1200);
  check(d.querySelector('#top h1').textContent === 'Time tracking', 'time view title');
  check(d.querySelectorAll('.timev .sttiles > div').length === 3, 'tiles: range (time + decimal hours), today, amount');
  check(d.querySelector('.ttable .tvl') && [...d.querySelectorAll('.ttable .tvt')].some(r => /Review/.test(r.textContent)), 'table: list and task rows');
  check(!d.querySelector('[data-act="tv-scope"]') === false, 'scope toggle shown (shared list)');
  const csv = d.querySelector('.timev a[href^="/api/time/export.csv"]').getAttribute('href');
  check(/from=\d{4}-\d\d-\d\d&to=\d{4}-\d\d-\d\d&scope=mine/.test(csv), 'CSV link carries the filters ' + csv);
  d.querySelector('[data-act="tv-scope"][data-k="all"]').click(); await sleep(900);
  check([...d.querySelectorAll('.ttable .tvl')].some(r => /Shared/.test(r.textContent) && /Bob/.test(r.textContent)), 'scope all: shared list with Bob');
  d.querySelector('[data-act="tv-period"][data-k="custom"]').click(); await sleep(900);
  check(d.querySelector('#tv-from') && d.querySelector('#tv-to'), 'custom range inputs');
  d.querySelector('[data-act="tv-period"][data-k="week"]').click(); await sleep(900);
  d.querySelector('[data-act="tv-lists"]').click(); await sleep(100);
  const cb = d.querySelector(`#pop [data-l="${WORK}"]`); cb.checked = true; cb.dispatchEvent(new w.Event('change', {bubbles: true})); w.eval('closePop()'); await sleep(900);
  check(d.querySelectorAll('.ttable .tvl').length === 1 && /Work/.test(d.querySelector('[data-act="tv-lists"]').textContent), 'list filter');
  d.querySelector('[data-act="tv-entries"]').click(); await sleep(100);
  check(d.querySelectorAll('.timev .terow').length >= 3, 'entries section expands');
  // timesheet
  d.querySelector('[data-act="tv-sheet"]').click(); await sleep(100);
  const sh = d.querySelector('.tsheet');
  check(sh && sh.querySelector('h1').textContent === 'Timesheet' && /Alice|All members/.test(sh.querySelector('.tssub').textContent), 'timesheet: title and subtitle');
  check(sh.querySelectorAll('.tskpi > div').length === 4 && sh.querySelector('tr.g') && sh.querySelector('.tsdays') && sh.querySelector('.tsentries table'), 'timesheet: KPIs, totals, per day, entries');
  check(d.body.classList.contains('tsprint'), 'print mode class');
  const css = await (await fetch(B + 'static/app.css')).text();
  check(/@media print\{\s*body\.tsprint>\*:not\(\.tsheet\)\{display:none!important\}/.test(css), 'print stylesheet hides the app');
  sh.querySelector('#ts-entries').checked = false; sh.querySelector('#ts-entries').dispatchEvent(new w.Event('change', {bubbles: true}));
  check(sh.querySelector('.tspage').classList.contains('noentries'), 'hide individual entries');
  d.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
  check(!d.querySelector('.tsheet') && !d.body.classList.contains('tsprint'), 'Esc closes the timesheet');
  w.eval(`S.tv.lists=[]; LS.set('timeLists', [])`);
  // stats card
  w.location.hash = 'stats'; await sleep(1200);
  check([...d.querySelectorAll('.stcard h3')].some(h => h.textContent === 'Tracked time'), 'statistics: Tracked time card');
  // settings pane + list rate
  w.eval(`settingsModal('time')`); await sleep(300);
  md = d.querySelector('.smodal');
  check(md.querySelector('#s-trnd') && md.querySelector('#s-tstop') && md.querySelector('.snav .on').dataset.sec === 'modules', 'settings: time tracking options (under Modules)');
  for (const [id, v] of [['#s-trnd', '15'], ['#s-ttarget', '6']]) { const e = md.querySelector(id); e.value = v; e.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(500); }
  md.remove();
  st = await call('GET', '/api/state');
  check(st.settings.time_rounding === '15' && st.settings.time_target === '6', 'settings saved');
  w.eval(`listModal(${WORK})`); await sleep(200);
  md = [...d.querySelectorAll('.modal')].pop();
  check(md.querySelector('#l-rate').value === '60', 'list dialog: hourly rate');
  md.querySelector('#l-rate').value = '72.5'; md.querySelector('[data-m="close"]').click(); await sleep(700);  // 1.5.1: saves itself (on close too)
  st = await call('GET', '/api/state');
  check(st.lists.find(l => l.id === WORK).rate === 72.5, 'rate saved from the dialog');
  w.location.hash = 'time'; await sleep(1200);
  check(/rounded/.test(d.querySelector('.timev .sttiles').textContent) && /of the daily target/.test(d.querySelector('.timev .sttiles').textContent), 'tiles: rounded + daily target');

  // ================= German (bob)
  const wb = await boot({user: 'bob', hash: 'time'}); const db2 = wb.document; await sleep(900);
  check(db2.querySelector('#top h1').textContent === 'Zeiterfassung', 'German title');
  check(/Stundennachweis/.test(db2.querySelector('[data-act="tv-sheet"]').textContent) && /Diese Woche/.test(db2.querySelector('.tvseg').textContent), 'German buttons');
  db2.querySelector('[data-act="tv-sheet"]').click(); await sleep(100);
  check(db2.querySelector('.tsheet h1').textContent === 'Stundennachweis' && /Summe/.test(db2.querySelector('.tsheet').textContent), 'German timesheet');
  const EN = /\b(Timer running|Total|Entries|Rounded|Timesheet|hours|tracked|Amount|Print|Individual|List \/ task|No task|Per day|Only mine|All members|Custom|This week)\b/;
  check(!EN.test(db2.querySelector('.tsheet').textContent + db2.querySelector('#view').textContent), 'no English leftovers (German view + timesheet)');

  // ================= module off
  await call('PATCH', '/api/settings', {features: 'cal,habits,pomo,stats,collab'});
  await call('POST', '/api/time/start', {task_id: t1});
  w = await boot({user: 'alice', hash: 'l/' + WORK}); d = w.document;
  check(!d.querySelector('#top .tmini') && !d.querySelector('.tchip') && !d.querySelector('[data-go="time"]'), 'module off: no pill, chips or nav entries');
  w.eval(`openDetail(${t1})`); await sleep(500);
  check(!d.querySelector('#d-time') && !d.querySelector('[data-act="timer-toggle"]'), 'module off: no time section in the detail');
  w.eval(`settingsModal()`); await sleep(200);
  check(!d.querySelector('.snav [data-sec="time"]'), 'module off: no settings pane');
  d.querySelector('.smodal')?.remove();
  w.location.hash = 'time'; await sleep(400);
  check(w.eval('S.route.mod') === 'tasks' && /Time tracking is off/.test(d.querySelector('#toast').textContent), 'module off: #time redirects with a hint');
  check((await call('GET', '/api/time/report')).entries.length > 0, 'module off: data kept');
  await call('POST', '/api/time/stop', {});
  await call('PATCH', '/api/settings', {features: 'cal,timeline,matrix,habits,pomo,kanban,paperless,collab,stats,time'});

  console.log(`${ok} ok, ${F.length} failed, js errors: ${errs.length}`); errs.forEach(e => console.log('JSERR', e));
  process.exit(F.length || errs.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
