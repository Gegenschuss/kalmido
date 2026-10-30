// 2.52.0 UI tests of part A (#1016 the calendar like macOS; own container, start.sh). jsdom:
// - which events may be dragged (own / shared with edit right yes; read-only shared, invitations, bookings no), the rule of a
//   repeating series moves along with its days
// Firefox, desktop (mouse): a drag over free time leaves a block "New event" with the title field in focus, Enter saves
// (undo removes it again), Esc cancels a drag and drops an empty block, an event is moved into another day and made longer
// at its lower edge (one undo step), a click without moving still opens the popover, a repeating event asks "Only this
// date / All dates", a draft stays a draft, a read-only event does not move; the all-day row and the month make all-day
// events over several days, an event there is dragged into other days. Firefox, phone (390, touch): hold 0.4 s and drag = a block "New event", a quick swipe scrolls
// and makes nothing, hold an event and drag = moved. Screenshots with P252A_SHOTS=<dir>.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p252_a_ui', check, shots: 'P252A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const pad = n => String(n).padStart(2, '0');
const dstr = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const TZ = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
// a Wednesday at least a week ahead: Wednesday to Friday share one week (weeks starting Sunday or Monday) and one month row
const base = (() => { const d = new Date(); d.setDate(d.getDate() + 7); while (d.getDay() !== 3) d.setDate(d.getDate() + 1); return d; })();
const day = n => { const d = new Date(base); d.setDate(d.getDate() + n); return dstr(d); };
const W1 = day(0), W2 = day(1), W3 = day(2);
const ALL = 'cal,events,comments';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: ALL});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.org'})).id;
  const ALICE = (await call('GET', '/api/me')).id || 1;
  const CB = await login('bob');
  await call('PATCH', '/api/settings', {features: ALL, tour: 'done', lang: 'en'}, CB);
  const Wk = await call('POST', '/api/evcals', {name: 'Work', color: '#2dd4bf'});
  const BC = await call('POST', '/api/evcals', {name: 'Bob only', color: '#f87171'}, CB);
  await call('PUT', `/api/evcals/${BC.id}/members`, {user_id: ALICE, role: 'view'}, CB);
  const ev = (title, start, end, more = {}) => call('POST', '/api/events', {title, cal_id: Wk.id, start, end, tz: TZ, reminders: [], ...more});
  const RV = await ev('Review', `${W1}T10:00`, `${W1}T11:00`);
  const SU = await ev('Standup', `${W1}T08:00`, `${W1}T08:30`, {rrule: 'FREQ=DAILY;COUNT=5'});
  const DR = await ev('Draft plan', `${W2}T14:00`, `${W2}T15:00`, {status: 'tentative'});
  const RO = await call('POST', '/api/events', {title: 'Read only', cal_id: BC.id, start: `${W2}T10:00`, end: `${W2}T11:00`, tz: TZ, reminders: []}, CB);
  check(RV.id && SU.id && DR.id && RO.id, 'events set up ' + JSON.stringify([RV.status, SU.status, DR.status, RO.status]));
  const get = async id => (await fetch(B + `api/events/${id}`, {headers: {...H, Cookie: CK}})).json();  // the event's own status field
  const find = async title => (await call('GET', `/api/events?from=${day(-3)}&to=${day(10)}`)).items?.find(x => x.title === title);

  // ================= jsdom: what may be dragged, the rule of a series
  const w = await boot({user: 'alice', hash: 'cal'}), d = w.document;
  await until(() => d.querySelector('#view .calbar'));
  check(w.eval(`cg_canDrag({own: true, cal: 1, role: 'owner'}) && cg_canDrag({own: true, cal: 1, role: 'edit'}) && !cg_canDrag({own: true, cal: 1, role: 'view'})
    && !cg_canDrag({own: true, cal: null, role: 'attendee'}) && !cg_canDrag({own: true, booking: true, cal: 1, role: 'owner'}) && !cg_canDrag({sub: 3}) && !cg_canDrag({sub: 3, dvw_write: false})`),
    'draggable: own and edit right; not read-only, invitations, bookings, subscriptions');
  check(w.eval(`typeof dvw_commit === 'function'`) === w.eval(`cg_canDrag({sub: 3, dvw_write: true})`), 'a writable subscription only with dvw_commit (part B)');
  check(w.eval(`cg_shiftRule('FREQ=WEEKLY;BYDAY=MO,WE', 1)`) === 'FREQ=WEEKLY;BYDAY=TU,TH' && w.eval(`cg_shiftRule('FREQ=WEEKLY;BYDAY=SU', 1)`) === 'FREQ=WEEKLY;BYDAY=MO'
    && w.eval(`cg_shiftRule('FREQ=MONTHLY;BYDAY=1FR', -1)`) === 'FREQ=MONTHLY;BYDAY=1TH' && w.eval(`cg_shiftRule('FREQ=MONTHLY;BYMONTHDAY=28', 1)`) === null
    && w.eval(`cg_shiftRule('FREQ=DAILY;COUNT=5', 2)`) === 'FREQ=DAILY;COUNT=5', 'a series moved by days: its weekdays move along');
  check(w.eval(`cg_wallAdd('2026-03-28T23:30', 90)`) === '2026-03-29T01:00' && w.eval(`cg_wallMin('2026-10-25T01:00', '2026-10-25T04:00')`) === 180, 'wall-clock arithmetic without daylight-saving jumps');
  w.close();

  // ================= Firefox, desktop (mouse)
  const ffLogin = async ({ev: e, nav}, user) => {
    await nav(B + 'static/icon.svg');
    await e(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    return e(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${user}', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (e, sel, n = 40) => { for (let i = 0; i < n && !(await e(`!!document.querySelector('${sel}')`).catch(() => false)); i++) await sleep(250); await sleep(500); };
  const week = (e, sel, mode = 'week') => e(`(() => { S.calMode = '${mode}'; S.calSel = '${sel}'; calInvalidate(); renderView(); return 1; })()`);
  // the place of a minute of a day in the grid (scrolled into view first)
  const at = (e, dd, min, xf = 0.5) => e(`(() => { const wb = document.querySelector('#wbody'), H = weekH(); wb.scrollTop = Math.max(0, ${min} / 60 * H - wb.clientHeight / 2);
    const c = document.querySelector('#view .wcol[data-day="${dd}"]'), b = c.getBoundingClientRect(); return {x: b.left + b.width * ${xf}, y: b.top + ${min} / 60 * H, H}; })()`);
  const block = (e, title) => e(`(() => { const x = [...document.querySelectorAll('#view .wcev')].find(x => x.textContent.includes(${JSON.stringify(title)})); if (!x) return null; const r = x.getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + Math.min(8, r.height / 3), bottom: r.bottom, ok: x.classList.contains('cgok'), day: x.closest('.wcol').dataset.day}; })()`);
  const blocks = e => until(() => e(`document.querySelectorAll('#view .wcev').length >= 3`));
  const typeKeys = (cmd, ctx, text) => cmd('input.performActions', {context: ctx, actions: [{type: 'key', id: 'kb', actions: [...text].flatMap(c => [{type: 'keyDown', value: c}, {type: 'keyUp', value: c}])}]}).then(() => cmd('input.releaseActions', {context: ctx}));
  const ENTER = '', ESC = '';

  await firefox(async o => {
    const {cmd, ev: e, ctx, shot, drag} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    check(await ffLogin(o, 'alice') === 200, 'desktop: login');
    await o.nav(B + '#cal'); await ready(e, '#view .calbar');
    await week(e, W1); await blocks(e); await sleep(1000);  // the events and the repeats of tasks arrive: the grid is drawn again
    // 1. a drag over free time: the block "New event", Enter saves
    let p = await at(e, W2, 16 * 60 + 7);
    await drag(p.x, p.y, 0, p.H);
    await sleep(300);
    const nb = await e(`(() => { const b = document.querySelector('#view .wcol[data-day="${W2}"] .cgnew'); return b ? [document.activeElement === b.querySelector('.cgin'), b.textContent, !document.querySelector('.modal.evmodal'), fmtTimeLoc('16:00') + '–' + fmtTimeLoc('17:00')] : null; })()`);
    check(nb && nb[0] && nb[1].includes(nb[3]) && nb[2],  // 2.368.0 (#2982): the times as the app shows them (12 h in an en-US browser)
      'desktop: the drag leaves a block "New event" (16:00-17:00) with the title in focus, no editor ' + JSON.stringify(nb));
    await shot('p252a-1440-new.png');
    await typeKeys(cmd, ctx, 'Planning' + ENTER);
    const PL = await until(() => find('Planning'));
    const pl = PL && await get(PL.eid);
    check(pl && pl.start === `${W2}T16:00` && pl.end === `${W2}T17:00` && pl.cal_id === Wk.id && !pl.all_day, 'desktop: Enter saved it at 16:00-17:00 in the calendar ' + JSON.stringify(pl && [pl.start, pl.end, pl.cal_id]));
    await until(() => e(`!document.querySelector('#view .cgnew') && [...document.querySelectorAll('#view .wcev')].some(x => x.textContent.includes('Planning'))`));
    check(await e(`!document.querySelector('#view .cgnew')`), 'desktop: the block is gone, the event is drawn');
    await e(`histStep('undo').then(() => 1)`);
    check(await until(async () => !(await find('Planning'))), 'desktop: Undo removes the new event');
    // 2. Esc during a drag: nothing; an empty block goes with Esc
    p = await at(e, W3, 18 * 60 + 7);
    await cmd('input.performActions', {context: ctx, actions: [
      {type: 'pointer', id: 'p1', parameters: {pointerType: 'mouse'}, actions: [{type: 'pointerMove', x: Math.round(p.x), y: Math.round(p.y)}, {type: 'pointerDown', button: 0},
        {type: 'pointerMove', x: Math.round(p.x), y: Math.round(p.y + p.H / 2), duration: 100}, {type: 'pointerMove', x: Math.round(p.x), y: Math.round(p.y + p.H), duration: 100}, {type: 'pause'}, {type: 'pause'}, {type: 'pointerUp', button: 0}]},
      {type: 'key', id: 'kb', actions: [{type: 'pause'}, {type: 'pause'}, {type: 'pause'}, {type: 'pause'}, {type: 'keyDown', value: ESC}, {type: 'keyUp', value: ESC}, {type: 'pause'}]}]});
    await cmd('input.releaseActions', {context: ctx}); await sleep(300);
    check(await e(`!document.querySelector('#view .cgnew, #view .evghost') && !document.querySelector('.modal.evmodal')`), 'desktop: Esc cancels a drag (no block, no ghost)');
    await drag(p.x, p.y, 0, p.H); await sleep(250);
    check(await e(`!!document.querySelector('#view .cgnew')`), 'desktop: a second drag: the block');
    await typeKeys(cmd, ctx, ESC); await sleep(200);
    check(await e(`!document.querySelector('#view .cgnew')`) && !(await find('New event')), 'desktop: Esc drops the empty block, nothing saved');
    // 3. move "Review" from Wednesday 10:00 to Thursday 11:30; a click without moving opens the popover
    await week(e, W1); await blocks(e);
    let b = await block(e, 'Review');
    check(b && b.ok && b.day === W1, 'desktop: an own event may be dragged (cgok)');
    await e(`(() => { const x = [...document.querySelectorAll('#view .wcev')].find(x => x.textContent.includes('Review')); x.dispatchEvent(new PointerEvent('pointerdown', {bubbles: true, clientX: 1, clientY: 1, pointerType: 'mouse', button: 0, pointerId: 1})); document.dispatchEvent(new PointerEvent('pointerup', {bubbles: true, pointerType: 'mouse', pointerId: 1})); x.click(); return 1; })()`);
    check(await until(() => e(`!!document.querySelector('#pop .evpop')`)), 'desktop: a click without moving opens the popover');
    await e(`(() => { closePop(); return 1; })()`);
    p = await at(e, W1, 10 * 60 + 8);
    const q = await at(e, W2, 10 * 60 + 8);
    b = await block(e, 'Review');
    await drag(b.x, b.y, q.x - b.x, p.H * 1.5);
    let rv = await until(async () => { const x = await get(RV.id); return x.start !== `${W1}T10:00` ? x : null; });
    check(rv && rv.start === `${W2}T11:30` && rv.end === `${W2}T12:30`, 'desktop: moved into Thursday 11:30 (length kept) ' + JSON.stringify(rv && [rv.start, rv.end]));
    // 4. longer at the lower edge: the end 12:30 -> 13:30
    await week(e, W1); await blocks(e);
    b = await block(e, 'Review');
    await drag(b.x, b.bottom - 2, 0, p.H);
    rv = await until(async () => { const x = await get(RV.id); return x.end !== `${W2}T12:30` ? x : null; });
    check(rv && rv.start === `${W2}T11:30` && rv.end === `${W2}T13:30`, 'desktop: the lower edge made it an hour longer ' + JSON.stringify(rv && [rv.start, rv.end]));
    await e(`histStep('undo').then(() => 1)`);
    check(await until(async () => (await get(RV.id)).end === `${W2}T12:30`), 'desktop: Undo takes the length back (one step)');
    // 5. a repeating event: "Only this date"
    await week(e, W1); await blocks(e);
    b = await e(`(() => { const x = [...document.querySelectorAll('#view .wcol[data-day="${W1}"] .wcev')].find(x => x.textContent.includes('Standup')); const r = x.getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + 4}; })()`);
    await drag(b.x, b.y, 0, p.H);
    await until(() => e(`!!document.querySelector('.modal [data-sc="one"]')`));
    check(await e(`!!document.querySelector('.modal [data-sc="one"]') && !!document.querySelector('.modal [data-sc="all"]')`), 'desktop: a repeating event asks "Only this date / All dates"');
    await e(`(() => { document.querySelector('.modal [data-sc="one"]').click(); return 1; })()`);
    const su = await until(async () => { const x = await get(SU.id); return x.overrides?.length ? x : null; });
    check(su && su.overrides[0].rid === `${W1}T08:00` && su.overrides[0].start === `${W1}T09:00` && su.overrides[0].end === `${W1}T09:30` && su.start === `${W1}T08:00`,
      'desktop: only this date moved to 9:00, the series stays ' + JSON.stringify(su && su.overrides));
    // 6. a draft stays a draft; a read-only event does not move
    await week(e, W1); await blocks(e);
    b = await block(e, 'Draft plan');
    await drag(b.x, b.y, 0, p.H);
    const dr = await until(async () => { const x = await get(DR.id); return x.start !== `${W2}T14:00` ? x : null; });
    check(dr && dr.start === `${W2}T15:00` && dr.status === 'tentative', 'desktop: a draft moved stays a draft ' + JSON.stringify(dr && [dr.start, dr.status]));
    await week(e, W1); await blocks(e);
    b = await block(e, 'Read only');
    check(b && !b.ok, 'desktop: a read-only event is not marked draggable');
    if (b) { await drag(b.x, b.y, 0, p.H); await sleep(500); }
    check((await get(RO.id)).start === `${W2}T10:00` && await e(`!document.querySelector('.modal')`), 'desktop: a read-only event does not move');
    await e(`(() => { closePop(); return 1; })()`);
    // 7. the all-day row: Wednesday to Friday; "Details" opens the editor with all day
    await week(e, W1); await blocks(e);
    const ad = await e(`(() => { const r = d => document.querySelector('#view .wad[data-day="' + d + '"]').getBoundingClientRect(); const a = r('${W1}'), z = r('${W3}'); return {x: a.left + a.width / 2, y: a.top + a.height - 4, dx: z.left - a.left}; })()`);
    await drag(ad.x, ad.y, ad.dx, 0);
    await sleep(300);
    check(await e(`(() => { const b = document.querySelector('#view .wallday .cgnew.cgday'); return !!b && document.activeElement === b.querySelector('.cgin') && document.querySelectorAll('#view .wad.cgsel').length === 3; })()`), 'desktop: the all-day row: a block over three days');
    await e(`(() => { document.querySelector('#view .cgnew .cgdet').click(); return 1; })()`);
    await until(() => e(`!!document.querySelector('.modal.evmodal')`));
    check(await e(`(() => { const m = document.querySelector('.modal.evmodal'); return m && m.querySelector('#ev-allday').checked && m.querySelector('#ev-sd').value === '${W1}' && m.querySelector('#ev-ed').value === '${W3}'; })()`), 'desktop: its "Details": the editor, all day, Wednesday to Friday');
    await e(`(() => { document.querySelectorAll('.modal').forEach(m => m.remove()); return 1; })()`);
    // 8. the month: Wednesday to Friday, a title, Enter
    await e(`(() => { S.calMode = 'month'; S.calMonth = '${W1.slice(0, 7)}'; S.calSel = '${W1}'; calInvalidate(); renderView(); return 1; })()`); await sleep(500);
    const mc = await e(`(() => { const r = d => document.querySelector('#view .cal .cell[data-day="' + d + '"]').getBoundingClientRect(); const a = r('${W1}'), z = r('${W3}'); return {x: a.left + a.width - 8, y: a.top + a.height - 8, dx: z.left - a.left}; })()`);
    await drag(mc.x, mc.y, mc.dx, 0); await sleep(300);
    check(await e(`!!document.querySelector('#view .cal .cgnew') && document.querySelectorAll('#view .cal .cell.cgsel').length === 3`), 'desktop: the month: a block over three days');
    await shot('p252a-1440-month.png');
    await typeKeys(cmd, ctx, 'Trip' + ENTER);
    const TR = await until(() => find('Trip'));
    const tr = TR && await get(TR.eid);
    check(tr && tr.all_day && tr.start === W1 && tr.end === day(3), 'desktop: the month: an all-day event Wednesday to Friday ' + JSON.stringify(tr && [tr.start, tr.end]));
    // the event in the month dragged one day later (all days move, the length stays)
    await until(() => e(`[...document.querySelectorAll('#view .cal .cell[data-day="${W1}"] .cev')].some(x => x.textContent.includes('Trip'))`));
    const tc = await e(`(() => { const x = [...document.querySelectorAll('#view .cal .cell[data-day="${W1}"] .cev')].find(x => x.textContent.includes('Trip')), r = x.getBoundingClientRect(), z = document.querySelector('#view .cal .cell[data-day="${W2}"]').getBoundingClientRect(); return {x: r.left + 10, y: r.top + r.height / 2, dx: z.left - r.left + 10, ok: x.classList.contains('cgok')}; })()`);
    check(tc.ok, 'desktop: the month: an own event is marked draggable');
    await drag(tc.x, tc.y, tc.dx, 0);
    const tr2 = await until(async () => { const x = await get(TR.eid); return x.start !== W1 ? x : null; });
    check(tr2 && tr2.start === W2 && tr2.end === day(4), 'desktop: the month: dragged one day later ' + JSON.stringify(tr2 && [tr2.start, tr2.end]));
    // a plain click on a day still picks the day (its quick add makes a task on that day)
    await e(`(() => { document.querySelector('#view .cal .cell[data-day="${W2}"] .dn').click(); return 1; })()`); await sleep(300);
    check(await e(`S.calSel === '${W2}' && !document.querySelector('#view .cgnew')`), 'desktop: the month: a click picks the day');
  }, false);

  // ================= Firefox, phone (touch)
  await firefox(async o => {
    const {cmd, ev: e, ctx, shot} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    check(await ffLogin(o, 'alice') === 200, 'phone: login');
    await o.nav(B + '#cal'); await ready(e, '#view .calbar');
    await week(e, W3, 'day'); await sleep(600);
    const touch = (x, y, hold, dy) => cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 't1', parameters: {pointerType: 'touch'}, actions: [
      {type: 'pointerMove', x: Math.round(x), y: Math.round(y)}, {type: 'pointerDown', button: 0}, ...(hold ? [{type: 'pause', duration: hold}] : []),
      {type: 'pointerMove', x: Math.round(x), y: Math.round(y + dy / 2), duration: 150}, {type: 'pointerMove', x: Math.round(x), y: Math.round(y + dy), duration: 150}, {type: 'pointerUp', button: 0}]}]})
      .then(() => cmd('input.releaseActions', {context: ctx}));
    // a quick swipe: no block
    let p = await at(e, W3, 13 * 60 + 7);
    await touch(p.x, p.y, 0, -p.H * 2); await sleep(400);
    check(await e(`!document.querySelector('#view .cgnew, #view .evghost')`), 'phone: a quick swipe makes nothing');
    await e(`(() => { closePop(); return 1; })()`);
    // hold 0.4 s, then drag: the block
    p = await at(e, W3, 13 * 60 + 7);
    await touch(p.x, p.y, 600, p.H * 1.5); await sleep(400);
    check(await e(`(() => { const b = document.querySelector('#view .wcol .cgnew'); return !!b && b.textContent.includes(fmtTimeLoc('13:00') + '–' + fmtTimeLoc('14:30')); })()`), 'phone: hold and drag: a block "New event" 13:00-14:30');
    check(await e(`(() => { const b = document.querySelector('#view .cgnew'); if (!b) return false; const r = b.getBoundingClientRect(), d = b.querySelector('.cgdet').getBoundingClientRect(); return r.left >= 0 && r.right <= innerWidth + .5 && d.height >= 43.5; })()`), 'phone: the block fits, "Details" is a 44 px target');
    await shot('p252a-390-new.png');
    await e(`(() => { const i = document.querySelector('#view .cgnew .cgin'); i.value = 'Call'; i.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true})); return 1; })()`);
    const CA = await until(() => find('Call'));
    check(CA && (await get(CA.eid)).start === `${W3}T13:00`, 'phone: saved at 13:00');
    // hold an event and drag it: moved by an hour
    await week(e, W3, 'day'); await until(() => e(`[...document.querySelectorAll('#view .wcev')].some(x => x.textContent.includes('Call'))`));
    const b = await e(`(() => { const wb = document.querySelector('#wbody'); wb.scrollTop = 12 * weekH(); const x = [...document.querySelectorAll('#view .wcev')].find(x => x.textContent.includes('Call')), r = x.getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + 6, H: weekH()}; })()`);
    await touch(b.x, b.y, 600, b.H);
    const ca = await until(async () => { const x = await get(CA.eid); return x.start !== `${W3}T13:00` ? x : null; });
    check(ca && ca.start === `${W3}T14:00` && ca.end === `${W3}T15:30`, 'phone: hold and drag an event: moved by an hour ' + JSON.stringify(ca && [ca.start, ca.end]));
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
