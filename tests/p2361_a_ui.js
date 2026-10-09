// 2.36.1 UI tests (agent A), own container (start.sh). #1126 timeline titles, #1127 + #956 calendar switches. jsdom:
//   the timeline has one row per calendar (own calendars AND subscriptions), every bar keeps its title inside the element
//   (no outside label, the bar width in --bw), overlapping events in extra lanes; a tap on a row name hides the calendar
//   (the subscription's "visible" = the same field as in the settings) and the toast takes it back, "…" offers "Only this
//   calendar" / "Show all"; the "Calendars" window from the calendar bar: "Tasks" (switch + per list), own calendars,
//   subscriptions, each with the three switches (calendar / Today / planning) stored on the server and redrawing at once
//   (no reload); Today's "Events today" block with its "…" menu (a calendar off there only); the day plan dialog's
//   "Calendars" line (plan_cals_off, the plan is fetched again)
// Firefox 390 touch: a timeline row with 3 events: every title inside its bar's element (getBoundingClientRect), no two
//   bars of a lane overlap, 44 px rows; the Calendars window as a sheet from below; screenshots with P2361A_SHOTS=<dir>
process.env.TZ = 'Europe/Berlin';
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2361_a_ui', check, shots: 'P2361A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const CT = process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test';
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const change = (w, el, v) => { if (v !== undefined) el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const day = n => { const d = new Date(); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
const settings = async () => (await call('GET', '/api/state')).settings;
const FEAT = 'cal,timeline,events,comments';
// a synced subscription with its events, written like the sync does (sqlite inside the container)
const py = code => execFileSync('docker', ['exec', CT, 'python', '-c', code], {encoding: 'utf8'}).trim();
const addSub = (name, color, events) => +py(`import sqlite3, json
c = sqlite3.connect('/data/tasks.db', timeout=10)
c.execute("INSERT INTO cal_subs(user_id,kind,name,color,visible,url,status,created_at) VALUES(1,'ics',?,?,1,'x','ok','2026-01-01T00:00:00Z')", (${JSON.stringify(name)}, ${JSON.stringify(color)}))
sid = c.execute('SELECT MAX(id) FROM cal_subs').fetchone()[0]
for t, d0, d1, allday, st, en in json.loads(${JSON.stringify(JSON.stringify(events))}):
    c.execute('INSERT INTO cal_events(sub_id,uid,title,all_day,start,end,d0,d1) VALUES(?,?,?,?,?,?,?,?)', (sid, t, t, allday, st, en, d0, d1))
c.commit(); print(sid)`);
const utc = (d, h) => { const x = new Date(`${d}T${String(h).padStart(2, '0')}:00:00`); return x.toISOString().replace(/\.\d+Z$/, 'Z'); };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, work_start: '08:00', work_end: '18:00'});
  const t0 = day(0), t1 = day(1), t2 = day(2), t3 = day(3);
  const WORK = (await call('POST', '/api/lists', {name: 'Work'})).id;
  const HOME = (await call('POST', '/api/lists', {name: 'Home'})).id;
  await call('POST', '/api/tasks', {title: 'Write the report', list_id: WORK, due: t1});
  await call('POST', '/api/tasks', {title: 'Water the plants', list_id: HOME, due: t1});
  await call('POST', '/api/tasks', {title: 'Call the bank', list_id: WORK, due: t0, due_time: '15:00', duration: 30});
  const W = await call('POST', '/api/evcals', {name: 'Mine', color: '#60a5fa'});
  const P = await call('POST', '/api/evcals', {name: 'Private', color: '#f87171'});
  await call('POST', '/api/events', {title: 'Dentist appointment downtown', cal_id: W.id, start: `${t1}T10:00`, end: `${t1}T11:00`});
  await call('POST', '/api/events', {title: 'Lunch today', cal_id: P.id, start: `${t0}T12:00`, end: `${t0}T13:00`});
  // the subscription "Team feed": three one-day events in a row (long titles) + one that overlaps the second (extra lane)
  const TEAM = addSub('Team feed', '#2dd4bf', [
    ['SCHOOL BOARD MEETING with the parents council', t1, t1, 1, t1, t2], ['PRESENTATION day for the whole department', t2, t2, 1, t2, t3],
    ['Philipp birthday party at home', t3, t3, 1, t3, day(4)], ['Zz overlapping all day', t2, t2, 1, t2, t3],
    ['Standup today', t0, t0, 0, utc(t0, 9), utc(t0, 10)]]);
  const FAM = addSub('Family feed', '#f59e0b', [['Grandma visits', t0, t0, 0, utc(t0, 16), utc(t0, 17)]]);

  // ================= timeline (jsdom): rows per calendar, titles inside the bars, lanes
  let w = await boot({user: 'alice', hash: 'cal', ls: {'tasks.calMode': '"timeline"'}}), d = w.document;
  await until(() => [...d.querySelectorAll('.tl-cev')].some(x => /SCHOOL BOARD/.test(x.textContent)));
  const rows = [...d.querySelectorAll('.tl-cal')];
  const names = rows.map(r => r.querySelector('.cvxtln .tln')?.textContent).filter(Boolean);
  check(names.length === 4 && names.includes('Team feed') && names.includes('Family feed') && names.includes('Mine') && names.includes('Private'),
    'timeline: one named row per calendar with events in range, own calendars too ' + JSON.stringify(names));
  const ti = rows.findIndex(r => r.querySelector('.cvxtln .tln')?.textContent === 'Team feed'), teamRows = [rows[ti], rows[ti + 1]];
  check(ti >= 0 && rows.length === 5 && !teamRows[1].querySelector('.cvxtln') && !teamRows[1].querySelector('.tln') && teamRows[1].style.getPropertyValue('--cc') === teamRows[0].style.getPropertyValue('--cc'),
    'timeline: the overlapping event got a second lane of the same colour (no name there) ' + rows.length);
  const bars = [...d.querySelectorAll('.tl-cev')];
  check(bars.length >= 6 && bars.every(b => !b.classList.contains('short') && b.querySelector('.cvxbar') && b.querySelector('span') && b.style.getPropertyValue('--bw')),
    'timeline: every bar has its coloured part (--bw) and the title inside, no outside label');
  const DW = w.eval('tlDW()');
  const school = bars.find(b => /SCHOOL BOARD/.test(b.textContent)), pres = bars.find(b => /PRESENTATION/.test(b.textContent));
  check(school && Math.abs(parseFloat(school.style.getPropertyValue('--bw')) - (DW - 4)) < 1 && Math.abs(parseFloat(school.style.width) - (DW - 4)) < 1,
    'timeline: a one-day bar followed by a bar on the next day stays one day wide (the title is cut there) ' + school?.getAttribute('style'));
  const bday = bars.find(b => /Philipp birthday/.test(b.textContent));
  check(bday && parseFloat(bday.style.width) > 5 * DW, 'timeline: the last bar of a lane may run its title over the free days');
  check(pres && Math.abs(parseFloat(pres.style.width) - (DW - 4)) < 1, 'timeline: a bar before another one is cut at that one');
  check(school.getAttribute('title').startsWith('SCHOOL BOARD') && !school.querySelector('.tl-name'), 'timeline: the full title in the tooltip');
  click(w, school); await sleep(150);
  check(/SCHOOL BOARD MEETING with the parents council/.test(d.querySelector('#pop .cevpop')?.textContent || ''), 'timeline: a tap shows the full title (popover)');
  w.eval('closePop()');
  // a tap on the name hides the subscription (same field as the settings switch), the toast takes it back
  click(w, teamRows[0].querySelector('.cvxtln')); await sleep(400);
  check((await call('GET', '/api/calendars')).subs.find(s => s.id === TEAM).visible === false, 'name tap: the subscription is hidden (visible = false)');
  await until(() => !d.querySelector('.tl-cal .cvxtln .tln')?.textContent.includes('Team feed') && ![...d.querySelectorAll('.tl-cal .tln')].some(x => x.textContent === 'Team feed'));
  check(![...d.querySelectorAll('.tl-cal .tln')].some(x => x.textContent === 'Team feed') && [...d.querySelectorAll('.tl-cal .tln')].some(x => x.textContent === 'Family feed'),
    'name tap: the row is gone at once, the others stay (no reload)');
  const tb = d.querySelector('#toast button');
  check(/Team feed/.test(d.querySelector('#toast')?.textContent || '') && tb && /Undo/.test(tb.textContent), 'name tap: toast with Undo');
  click(w, tb); await sleep(400);
  check((await call('GET', '/api/calendars')).subs.find(s => s.id === TEAM).visible === true, 'Undo: the subscription shows again');
  await until(() => [...d.querySelectorAll('.tl-cal .tln')].some(x => x.textContent === 'Team feed'));
  check([...d.querySelectorAll('.tl-cal .tln')].some(x => x.textContent === 'Team feed'), 'Undo: the row is back');
  // "…" on a row: "Only this calendar" / "Show all calendars"
  const mb = [...d.querySelectorAll('.tl-cal .cvxtlm')].find(b => b.dataset.name === 'Family feed');
  click(w, mb); await sleep(150);
  const items = [...d.querySelectorAll('#pop [role="menuitem"]')].map(b => b.textContent.trim());
  check(items.some(x => /Hide this calendar/.test(x)) && items.some(x => /Only this calendar/.test(x)) && items.some(x => /Show all calendars/.test(x)) && items.some(x => /Calendars…/.test(x)),
    'row menu: hide / only this / show all / Calendars… ' + JSON.stringify(items));
  click(w, [...d.querySelectorAll('#pop [role="menuitem"]')].find(b => /Only this calendar/.test(b.textContent))); await sleep(900);
  let subs = (await call('GET', '/api/calendars')).subs, cals = (await call('GET', '/api/evcals')).items;
  check(subs.find(s => s.id === FAM).visible === true && subs.find(s => s.id === TEAM).visible === false && cals.every(c => c.hidden === true),
    'Only this: every other calendar (subscriptions and own) hidden ' + JSON.stringify([subs.map(s => [s.name, s.visible]), cals.map(c => [c.name, c.hidden])]));
  await until(() => d.querySelectorAll('.tl-cal').length === 1);
  check(d.querySelectorAll('.tl-cal').length === 1 && d.querySelector('.tl-cal .tln')?.textContent === 'Family feed', 'Only this: one row left');
  click(w, d.querySelector('#toast button')); await sleep(900);  // "Show all"
  subs = (await call('GET', '/api/calendars')).subs; cals = (await call('GET', '/api/evcals')).items;
  check(subs.every(s => s.visible) && cals.every(c => !c.hidden), 'Show all: everything visible again');
  await until(() => [...d.querySelectorAll('.tl-cal .tln')].some(x => x.textContent === 'Team feed'));

  // ================= the Calendars window: tasks, own calendars, subscriptions, three switches each
  check(d.querySelector('#view .calbar [data-act="ev-cals"]'), 'the calendar bar has "Calendars"');
  click(w, d.querySelector('#view .calbar [data-act="ev-cals"]'));
  await until(() => d.querySelector('.modal.evcmodal .cvxrow'));
  let md = d.querySelector('.modal.evcmodal');
  check(md.querySelector('[data-cvx="tasks"]')?.checked === true && md.querySelectorAll('.evcrow').length === 2 && md.querySelectorAll('.cvxrow:not(.sub) [data-cvx="show"]').length === 2,
    'window: Tasks (on), two own calendars, two subscriptions with a "show" switch');
  check(md.querySelectorAll('[data-cvx="today"]').length === 4 && md.querySelectorAll('[data-cvx="plan"]').length === 4 && [...md.querySelectorAll('[data-cvx="today"],[data-cvx="plan"]')].every(x => x.checked && !x.disabled),
    'window: Today + planning switches on every calendar row, all on');
  check(md.querySelectorAll('.evcrow [data-evcshow]').length === 2 && [...md.querySelectorAll('.swc')].every(l => l.querySelector('.sr')?.textContent), 'window: every switch has an accessible name');
  // tasks per list: fold out, switch Home off
  check(!md.querySelector('.cvxrow.sub'), 'the lists are folded');
  click(w, md.querySelector('[data-evc="lists"]')); await sleep(100);
  const lrows = [...md.querySelectorAll('.cvxrow.sub')];
  check(lrows.length === 3 && lrows.map(r => r.querySelector('.evcn').textContent).includes('Home') && lrows.at(-1).querySelector('.evcn').textContent === 'Inbox', 'per list: Work, Home, Inbox last ' + lrows.map(r => r.querySelector('.evcn').textContent));
  const hsw = lrows.find(r => r.querySelector('.evcn').textContent === 'Home').querySelector('input'); hsw.checked = false; change(w, hsw); await sleep(400);
  check(JSON.parse((await settings()).cal_lists_hidden).includes(HOME), 'list switch: stored (cal_lists_hidden)');
  check(/1 list hidden/.test(md.querySelector('.cvxrow:not(.sub) .evcn').textContent), 'the Tasks row counts the hidden lists');
  click(w, md.querySelector('[data-evc="close"]'));
  w.eval(`S.calMode = 'month'; S.calSel = '${t1}'; renderView()`); await sleep(300);
  let chips = [...d.querySelectorAll('#view .cal .ev')].map(x => x.textContent.trim());
  check(chips.some(x => /Write the report/.test(x)) && !chips.some(x => /Water the plants/.test(x)) && !/Water the plants/.test(d.querySelector('#view .agenda')?.textContent || ''), 'month: the tasks of the hidden list are gone, the others stay ' + JSON.stringify(chips));
  check(w.eval(`S.tasks.size`) === 3, 'the tasks themselves are untouched (only the calendar leaves them out)');
  // all tasks off
  click(w, d.querySelector('#view .calbar [data-act="ev-cals"]')); await until(() => d.querySelector('.modal.evcmodal .cvxrow'));
  md = d.querySelector('.modal.evcmodal');
  const tsw = md.querySelector('[data-cvx="tasks"]'); tsw.checked = false; change(w, tsw); await sleep(400);
  check((await settings()).cal_tasks === '0', 'Tasks switch: stored (cal_tasks = 0)');
  click(w, md.querySelector('[data-evc="lists"]')); await sleep(100);
  check([...md.querySelectorAll('.cvxrow.sub input')].every(x => x.disabled), 'tasks off: the list switches are greyed');
  click(w, md.querySelector('[data-evc="close"]')); await sleep(300);
  check(!d.querySelector('#view .cal .ev') && [...d.querySelectorAll('#view .cal .cev')].some(x => /Dentist/.test(x.textContent)), 'month: no task chips, the events stay');
  w.eval(`S.calMode = 'week'; renderView()`); await sleep(300);
  check(!d.querySelector('#view .week .wev, #view .week .ev') && d.querySelector('#view .week .wcev'), 'week: no tasks, events stay');
  w.eval(`S.calMode = 'timeline'; renderView()`); await sleep(300);
  check(!d.querySelector('#view .tl-bar') && d.querySelector('#view .tl-cev'), 'timeline (in the calendar): no task bars, the calendar rows stay');
  await call('PATCH', '/api/settings', {cal_tasks: '1', cal_lists_hidden: []});
  w.eval(`S.settings.cal_tasks = '1'; S.settings.cal_lists_hidden = '[]'; S.calMode = 'month'; renderView()`); await sleep(200);
  // (the day cell shows 3 chips, the events first: the list below the month has every task of the selected day)
  check([...d.querySelectorAll('#view .cal .ev')].some(x => /Write the report/.test(x.textContent)) && /Water the plants/.test(d.querySelector('#view .agenda')?.textContent || ''), 'tasks on again: the chips are back');
  // a subscription's "show" switch in the window: off -> row gone from the timeline without a reload, on again
  click(w, d.querySelector('#view .calbar [data-act="ev-cals"]')); await until(() => d.querySelector('.modal.evcmodal .cvxrow'));
  md = d.querySelector('.modal.evcmodal');
  const ssw = md.querySelector(`[data-cvx="show"][data-key="s:${TEAM}"]`); ssw.checked = false; change(w, ssw); await sleep(500);
  check((await call('GET', '/api/calendars')).subs.find(s => s.id === TEAM).visible === false, 'window: subscription off (visible = false)');
  check(md.querySelector(`[data-cvx="today"][data-key="s:${TEAM}"]`)?.disabled && md.querySelector(`[data-cvx="plan"][data-key="s:${TEAM}"]`)?.disabled, 'window: Today + planning greyed while the calendar is hidden');
  // Today + planning switches on an own calendar
  const tdw = md.querySelector(`[data-cvx="today"][data-key="e:${P.id}"]`); tdw.checked = false; change(w, tdw); await sleep(400);
  const plw = md.querySelector(`[data-cvx="plan"][data-key="s:${FAM}"]`); plw.checked = false; change(w, plw); await sleep(400);
  let s = await settings();
  check(JSON.parse(s.today_cals_hidden).includes(`e:${P.id}`) && JSON.parse(s.plan_cals_off).includes(`s:${FAM}`) && JSON.parse(s.plan_cals_off).length === 1,
    'window: Today / planning switches stored ' + s.today_cals_hidden + ' ' + s.plan_cals_off);
  const ssw2 = md.querySelector(`[data-cvx="show"][data-key="s:${TEAM}"]`); ssw2.checked = true; change(w, ssw2); await sleep(500);
  check((await call('GET', '/api/calendars')).subs.find(s => s.id === TEAM).visible === true, 'window: subscription on again');
  click(w, md.querySelector('[data-evc="close"]'));
  w.close();

  // ================= Today: "Events today" with its menu (a calendar off there only)
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  await until(() => d.querySelector('.cevtoday .cevrow'));
  let rowsT = [...d.querySelectorAll('.cevtoday .cevrow')].map(r => r.querySelector('.cevn').textContent);
  check(rowsT.includes('Standup today') && rowsT.includes('Grandma visits') && !rowsT.includes('Lunch today'), 'Today: the events of the day, Private (switched off for Today) left out ' + JSON.stringify(rowsT));
  check(d.querySelector('.cevtoday .ghead .c')?.textContent === '2' && d.querySelector('.cevtoday [data-act="cvx-today-menu"]'), 'Today: the count follows, the head has "…"');
  click(w, d.querySelector('.cevtoday [data-act="cvx-today-menu"]')); await sleep(150);
  const mi = [...d.querySelectorAll('#pop [role="menuitem"]')];
  check(mi.length >= 5 && mi.filter(b => b.classList.contains('on')).map(b => b.textContent.trim()).sort().join() === ['Family feed', 'Mine', 'Team feed'].join() && mi.some(b => /Private/.test(b.textContent) && !b.classList.contains('on')),
    'Today menu: every calendar with a check where it shows ' + JSON.stringify(mi.map(b => [b.textContent.trim(), b.classList.contains('on')])));
  click(w, mi.find(b => /Team feed/.test(b.textContent))); await sleep(500);
  rowsT = [...d.querySelectorAll('.cevtoday .cevrow')].map(r => r.querySelector('.cevn').textContent);
  check(!rowsT.includes('Standup today') && rowsT.includes('Grandma visits'), 'Today menu: the team feed is off here ' + JSON.stringify(rowsT));
  s = await settings();
  check(JSON.parse(s.today_cals_hidden).sort().join() === [`e:${P.id}`, `s:${TEAM}`].sort().join(), 'Today menu: stored (today_cals_hidden)');
  check((await call('GET', `/api/calendars`)).subs.find(x => x.id === TEAM).visible === true, 'Today menu: the calendar itself stays visible (Today only)');
  click(w, d.querySelector('.cevtoday [data-act="cvx-today-menu"]')); await sleep(150);
  click(w, [...d.querySelectorAll('#pop [role="menuitem"]')].find(b => /Show all calendars/.test(b.textContent))); await sleep(500);
  rowsT = [...d.querySelectorAll('.cevtoday .cevrow')].map(r => r.querySelector('.cevn').textContent);
  check(rowsT.length === 3 && (await settings()).today_cals_hidden === '[]', 'Today menu: "Show all" ' + JSON.stringify(rowsT));

  // ================= the day plan dialog: the "Calendars" line
  w.eval('dayplanModal("day")'); await until(() => d.querySelector('.modal.dpm .cvxdp'));
  md = d.querySelector('.modal.dpm');
  const pcs = [...md.querySelectorAll('[data-cvxplan]')];
  check(pcs.length === 4 && pcs.filter(x => x.checked).length === 3 && pcs.find(x => x.dataset.cvxplan === `s:${FAM}`)?.checked === false && /3 of 4 considered/.test(md.querySelector('.cvxdp summary').textContent),
    'day plan: a line "Calendars", the family feed unchecked (from the window), "3 of 4 considered"');
  check(!md.querySelector('.cvxdp').open, 'day plan: the line is folded');
  let evT = [...md.querySelectorAll('.dprow.event .dpn')].map(x => x.textContent);
  check(evT.includes('Standup today') && evT.includes('Lunch today') && !evT.includes('Grandma visits'), 'day plan: the events that count (not the family feed) ' + JSON.stringify(evT));
  const pc = pcs.find(x => x.dataset.cvxplan === `s:${TEAM}`); pc.checked = false; change(w, pc); await sleep(900);
  check(JSON.parse((await settings()).plan_cals_off).sort().join() === [`s:${FAM}`, `s:${TEAM}`].sort().join(), 'day plan: the switch stores plan_cals_off');
  md = d.querySelector('.modal.dpm');
  evT = [...md.querySelectorAll('.dprow.event .dpn')].map(x => x.textContent);
  check(!evT.includes('Standup today') && evT.includes('Lunch today') && /2 of 4 considered/.test(md.querySelector('.cvxdp summary').textContent), 'day plan: planned again without the team feed ' + JSON.stringify(evT));
  w.eval(`document.querySelector('.modal.dpm')?.remove()`);
  w.close();

  // ================= German
  await call('PATCH', '/api/settings', {lang: 'de'});
  w = await boot({user: 'alice', hash: 'cal', ls: {'tasks.calMode': '"timeline"'}}); d = w.document;
  await until(() => d.querySelector('.tl-cal .cvxtln'));
  click(w, d.querySelector('#view .calbar [data-act="ev-cals"]')); await until(() => d.querySelector('.modal.evcmodal .cvxrow'));
  md = d.querySelector('.modal.evcmodal');
  check(/Aufgaben mit Datum/.test(md.textContent) && /Meine Kalender/.test(md.textContent) && /Abos/.test(md.textContent) && /Beim Planen|Planen/.test(md.textContent), 'German: the window');
  check(d.querySelector('.tl-cal .cvxtln')?.getAttribute('title') === 'Diesen Kalender ausblenden', 'German: the row name tooltip');
  w.close();
  await call('PATCH', '/api/settings', {lang: 'en', plan_cals_off: [], today_cals_hidden: []});

  // ================= Firefox 390 (touch): titles inside the bars, no overlap, a sheet from below
  const ffLogin = async o => {
    await o.nav(B + 'static/icon.svg'); await sleep(300);  // not the app: B#cal afterwards is a real load with the session
    await o.ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.calMode', '"timeline"'); localStorage.setItem('tasks.tour', '"done"'); return 1; })()`);
    return o.ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '390';
    check(await ffLogin(o) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + '#cal'); await ready(ev);
    await ev(`(() => { S.calMode = 'timeline'; LS.set('calMode', 'timeline'); renderView(); return 1; })()`); await sleep(500);
    for (let i = 0; i < 40 && !(await ev(`[...document.querySelectorAll('.tl-cev')].some(x => /SCHOOL BOARD/.test(x.textContent))`)); i++) await sleep(300);
    console.log(tag + ': state ' + await ev(`JSON.stringify({mode: S.calMode, route: S.route, feats: S.settings?.features, evcals: (S.evcals || []).length, cals: S.calendars, items: S.cal.items.length, key: S.cal.key, loading: S.cal.loading, h1: document.querySelector('#top h1')?.textContent, bars: document.querySelectorAll('.tl-cev').length, view: (document.querySelector('#view')?.textContent || '').slice(0, 120)})`));
    const m = await ev(`(() => {
      const rows = [...document.querySelectorAll('.tl-row.tl-cal')], out = {rows: rows.length, inside: 0, outside: [], overlap: [], rowH: [], nameH: 0, side: document.documentElement.scrollWidth <= innerWidth + 1};
      for (const r of rows) {
        const rr = r.getBoundingClientRect(); out.rowH.push(Math.round(rr.height));
        const bars = [...r.querySelectorAll('.tl-cev')].map(b => ({b, r: b.getBoundingClientRect(), s: b.querySelector('span').getBoundingClientRect(), t: b.textContent.slice(0, 18)}));
        for (const x of bars) {
          if (x.s.left >= x.r.left - 0.5 && x.s.right <= x.r.right + 0.5 && x.s.top >= rr.top - 0.5 && x.s.bottom <= rr.bottom + 0.5) out.inside++; else out.outside.push([x.t, Math.round(x.s.right - x.r.right)]);
        }
        bars.sort((a, b) => a.r.left - b.r.left);
        for (let i = 1; i < bars.length; i++) if (bars[i].r.left < bars[i - 1].r.right - 0.5) out.overlap.push([bars[i - 1].t, bars[i].t]);
      }
      const n = document.querySelector('.tl-cal .cvxtln'); out.nameH = n ? Math.round(n.getBoundingClientRect().height) : 0;
      const sc = document.querySelector('.tl-scroll'); out.scroll = sc ? sc.scrollLeft : -1;
      return out;
    })()`);
    check(m.rows >= 4 && m.inside >= 6 && m.outside.length === 0, `${tag}: every title inside its bar's element ` + JSON.stringify(m));
    check(m.overlap.length === 0, `${tag}: no two bars of a lane overlap ` + JSON.stringify(m.overlap));
    check(m.rowH.every(h => h >= 32) && m.nameH >= 24, `${tag}: rows >= 32 px, the name target >= 24 px ` + JSON.stringify([m.rowH, m.nameH]));
    check(m.side, `${tag}: nothing sideways`);
    await shot('p2361a-390-timeline.png');
    // the Calendars window: a sheet from below with 44 px rows
    await ev(`(() => { document.querySelector('#view .calbar [data-act="ev-cals"]').click(); return 1; })()`);
    for (let i = 0; i < 20 && !(await ev(`!!document.querySelector('.modal.evcmodal .cvxrow')`)); i++) await sleep(300);
    console.log(tag + ': window ' + await ev(`(document.querySelector('#evc-body')?.textContent || '').slice(0, 200)`));
    const s2 = await ev(`(() => { const c = document.querySelector('.modal.evcmodal .card'), r = c.getBoundingClientRect();
      const rows = [...c.querySelectorAll('.cvxrow:not(.sub), .evcrow')].map(x => Math.round(x.getBoundingClientRect().height));
      const sw = [...c.querySelectorAll('.swc input')].map(x => { const b = x.getBoundingClientRect(); return [Math.round(b.width), Math.round(b.height)]; });
      return {bottom: Math.round(innerHeight - r.bottom), width: Math.round(r.width), rows, sw, fits: c.scrollWidth <= c.clientWidth + 1}; })()`);
    check(s2.bottom <= 2 && s2.width >= 380, `${tag}: the window is a sheet from below ` + JSON.stringify([s2.bottom, s2.width]));
    check(s2.rows.length >= 5 && s2.rows.every(h => h >= 44) && s2.sw.every(([ww, h]) => ww >= 24 && h >= 24) && s2.fits, `${tag}: rows >= 44 px, switch targets >= 24 px, nothing cut ` + JSON.stringify(s2));
    await shot('p2361a-390-calendars.png');
  }, true);
  // desktop: the same bars, nothing outside
  await firefox(async o => {
    const {cmd, ev, ctx} = o, tag = '1280';
    check(await ffLogin(o) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 800}});
    await o.nav(B + '#cal'); await ready(ev);
    await ev(`(() => { S.calMode = 'timeline'; LS.set('calMode', 'timeline'); renderView(); return 1; })()`); await sleep(500);
    for (let i = 0; i < 40 && !(await ev(`[...document.querySelectorAll('.tl-cev')].some(x => /SCHOOL BOARD/.test(x.textContent))`)); i++) await sleep(300);
    console.log(tag + ': state ' + await ev(`JSON.stringify({mode: S.calMode, route: S.route, feats: S.settings?.features, evcals: (S.evcals || []).length, cals: S.calendars, items: S.cal.items.length, key: S.cal.key, loading: S.cal.loading, h1: document.querySelector('#top h1')?.textContent, bars: document.querySelectorAll('.tl-cev').length, view: (document.querySelector('#view')?.textContent || '').slice(0, 120)})`));
    const m = await ev(`(() => { let inside = 0, outside = 0; for (const b of document.querySelectorAll('.tl-cev')) { const r = b.getBoundingClientRect(), s = b.querySelector('span').getBoundingClientRect(); if (s.right <= r.right + 0.5 && s.left >= r.left - 0.5) inside++; else outside++; } return {inside, outside}; })()`);
    check(m.inside >= 6 && m.outside === 0, `${tag}: titles inside on a desktop too ` + JSON.stringify(m));
  }, false);

  console.log(`p2361_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
