// kalmido-suite: fresh
// 2.484.0 (#3945) UI test: a date of a series that was changed on its own already (an override, RECURRENCE-ID) is a single
// event to the user. jsdom only, invented names.
//  - dragging it (cg_end) asks nothing and moves only it; the series' times stay (no shift by the override's offset)
//  - a date of the series without an own change still asks "Only this date / All dates"
//  - the editor of the changed date: no switch "Only this date / All dates", no repeat row, its own title and time; saving
//    changes only it
//  - changing the series (title, time, place) leaves the changed date as it is (server)
//  - deleting the changed date: the plain question of a single event, only that date goes
// freelancer-matrix: events (alice has no organisation: her private workspace)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P3945_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); let j = {}; try { j = await r.json(); } catch { /* no body */ } return {http: r.status, ...j}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const pad = n => String(n).padStart(2, '0');
const dstr = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const TZ = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
const base = (() => { const d = new Date(); d.setDate(d.getDate() + 7); return d; })();
const day = n => { const d = new Date(base); d.setDate(d.getDate() + n); return dstr(d); };
const D0 = day(0), D1 = day(1), D2 = day(2);

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,events'});
  const W = await call('POST', '/api/evcals', {name: 'Work', color: '#2dd4bf'});
  const SU = await call('POST', '/api/events', {title: 'Standup', cal_id: W.id, start: `${D0}T08:00`, end: `${D0}T08:30`, tz: TZ, reminders: [], rrule: 'FREQ=DAILY;COUNT=5', location: 'Room A'});
  check(SU.id, 'a daily series ' + JSON.stringify(SU));
  const occ = `${D1}T08:00`;
  // the date of the second day was moved on its own to 9:00 ("Only this date")
  let r = await call('PATCH', `/api/events/${SU.id}?occ=${encodeURIComponent(occ)}`, {start: `${D1}T09:00`, end: `${D1}T09:30`});
  check(r.http === 200, 'the second day moved on its own ' + r.http);
  const get = () => call('GET', `/api/events/${SU.id}`);
  const ovOf = x => (x.overrides || []).find(o => o.rid === occ);

  const w = await boot({user: 'alice', hash: 'cal'}), d = w.document;
  await until(() => w.eval(`typeof cg_end === 'function' && typeof evEditor === 'function'`));
  await w.eval(`ensureCalEv('${D0}', '${D2}')`);
  const item = k => `S.cal.items.find(x => x.eid === ${SU.id} && x.occ === '${k}')`;
  await until(() => w.eval(`!!${item(occ)} && !!${item(`${D2}T08:00`)}`));
  check(w.eval(`${item(occ)}.changed === true && ${item(`${D2}T08:00`)}.changed === false`), 'the grid knows which date has its own change (changed)');

  // ---- 1. dragging the changed date one hour later: no question, only it moves, the series stays at 8:00
  const drag = (k, mins) => w.eval(`(() => { const ev = ${item(k)}; CG.st = {kind: 'move', ev, active: true, on: true, dd: 0, dm: ${mins}, ghost: document.createElement('i')}; cg_end(); return 1; })()`);
  drag(occ, 60);
  let x = await until(async () => { const y = await get(); return ovOf(y)?.start === `${D1}T10:00` ? y : null; });
  check(x && ovOf(x).end === `${D1}T10:30` && x.start === `${D0}T08:00` && x.end === `${D0}T08:30`,
    'dragging the changed date moved only it to 10:00, the series stays 8:00 ' + JSON.stringify(x && [x.start, x.end, x.overrides]));
  check(!d.querySelector('.modal [data-sc]'), 'dragging the changed date asked nothing');

  // ---- 2. a date without own change still asks
  await w.eval(`(() => { calInvalidate(); return ensureCalEv('${D0}', '${D2}'); })()`);
  await until(() => w.eval(`!!${item(`${D2}T08:00`)}`));
  drag(`${D2}T08:00`, 60);
  check(await until(() => d.querySelector('.modal [data-sc="one"]') && d.querySelector('.modal [data-sc="all"]')), 'a date without own change still asks "Only this date / All dates"');
  const sc = d.querySelector('.modal [data-sc=""]'); if (sc) click(w, sc);
  await until(() => !d.querySelector('.modal [data-sc]'));

  // ---- 3. the editor of the changed date: no switch, no repeat, its own title and time; saving changes only it
  let full = await get();
  w.eval(`evEditor({ev: ${JSON.stringify(full)}, occ: ${JSON.stringify(occ)}})`);
  let md = await until(() => d.querySelector('.modal.evmodal'));
  check(md && !md.querySelector('[data-evsc]'), 'the editor of the changed date has no switch "Only this date / All dates"');
  check(md && md.querySelector('.evrep').hidden, 'the editor of the changed date shows no repeat setting');
  check(md && md.querySelector('#ev-sd').value === D1 && md.querySelector('#ev-stm').value === '10:00' && md.querySelector('#ev-etm').value === '10:30',
    'the editor shows the date\'s own time ' + (md && [md.querySelector('#ev-sd').value, md.querySelector('#ev-stm').value, md.querySelector('#ev-etm').value]));
  md.querySelector('#ev-title').value = 'Standup (moved)';
  click(w, md.querySelector('[data-evm="save"]'));
  x = await until(async () => { const y = await get(); return ovOf(y)?.title === 'Standup (moved)' ? y : null; });
  check(x && x.title === 'Standup' && x.start === `${D0}T08:00` && ovOf(x).start === `${D1}T10:00`, 'saving in the editor changed only the date ' + JSON.stringify(x && [x.title, x.start, ovOf(x)]));
  await until(() => !d.querySelector('.modal.evmodal'));
  // a date without own change: the editor keeps its switch
  w.eval(`evEditor({ev: ${JSON.stringify(x)}, occ: '${D2}T08:00'})`);
  md = await until(() => d.querySelector('.modal.evmodal [data-evsc="all"].on') && d.querySelector('.modal.evmodal'));
  check(md && !md.querySelector('.evrep').hidden, 'a date without own change: the editor keeps "Only this date / All dates" and the repeat row');
  if (md) click(w, md.querySelector('[data-evm="close"]'));

  // ---- 4. changing the series (title, time, place) leaves the changed date as it is
  full = await get();
  r = await call('PATCH', `/api/events/${SU.id}`, {title: 'Daily', start: `${D0}T07:30`, end: `${D0}T08:00`, location: 'Room B', expect: full.updated_at});
  check(r.http === 200, 'the series changed ' + r.http);
  x = await get();
  const ov = (x.overrides || [])[0];
  check(x.overrides?.length === 1 && ov.title === 'Standup (moved)' && ov.start === `${D1}T10:00` && ov.end === `${D1}T10:30` && ov.location === 'Room A',
    'the changed date keeps its title, time and place after the series changed ' + JSON.stringify(x.overrides));
  const occ2 = ov.rid;  // the key moves with the series (RECURRENCE-ID of the new start)

  // ---- 5. deleting the changed date: the plain question, only it goes
  w.eval(`evDelete(${JSON.stringify(x)}, ${JSON.stringify(occ2)})`);
  const q = await until(() => d.querySelector('.modal [data-cd="yes"]') && d.querySelector('.modal'));
  check(q && !d.querySelector('.modal [data-sc]'), 'deleting the changed date does not ask "Only this date / All dates"');
  if (q) click(w, q.querySelector('[data-cd="yes"]'));
  x = await until(async () => { const y = await get(); return (y.exdates || '').includes(occ2) ? y : null; });
  check(x && x.title === 'Daily' && !(x.overrides || []).length, 'only the changed date went, the series stays ' + JSON.stringify(x && [x.title, x.exdates, x.overrides]));

  w.close();
  console.log(`p3945_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
