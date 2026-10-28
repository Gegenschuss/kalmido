// kalmido-suite: fresh
// 2.368.0 B UI tests (#2982 dates and times in one way, the setting "Region and formats"), own container (start.sh), jsdom.
// freelancer-matrix: settings -- alice has no organisation: everything below runs in her private space (the same for everyone)
// - English dates in the order of en-GB ("Mon 26 Oct", "Mon 26 Oct 2026", "Monday 26 October"), the week title without the weekday
// - the settings week_start / time_format / date_order: stored by PATCH /api/settings, a wrong value = 400, '' = automatic
// - a time shown raw before (the due time of a task) follows 12 / 24 h; the time picker's labels too
// - the first day of the week (calendar, date picker) follows the setting; dispatch / habit weeks: Monday when automatic
// - numeric dates follow the chosen order (31.12.2026 / 12/31/2026 / 2026-12-31)
// - Settings > General shows the three choices; a change saves at once
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const sets = async () => (await call('GET', '/api/state')).settings;

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});

  // ================= the settings on the server (a person without an organisation)
  const s0 = await sets();
  check(s0.week_start === '' && s0.time_format === '' && s0.date_order === '', 'defaults: automatic (empty) ' + JSON.stringify([s0.week_start, s0.time_format, s0.date_order]));
  let r = await call('PATCH', '/api/settings', {week_start: 'sun', time_format: '12', date_order: 'ymd'});
  check(r.status === 200, 'PATCH the three formats: 200 ' + r.status);
  const s1 = await sets();
  check(s1.week_start === 'sun' && s1.time_format === '12' && s1.date_order === 'ymd', 'stored ' + JSON.stringify([s1.week_start, s1.time_format, s1.date_order]));
  for (const [k, v] of [['week_start', 'fri'], ['time_format', '13'], ['date_order', 'dd.mm.yyyy']]) {
    r = await call('PATCH', '/api/settings', {[k]: v});
    check(r.status === 400, `a wrong ${k} (${v}): 400 ` + r.status);
  }
  check((await sets()).week_start === 'sun', 'a wrong value changes nothing');
  r = await call('PATCH', '/api/settings', {week_start: '', time_format: '', date_order: ''});
  const s2 = await sets();
  check(r.status === 200 && s2.week_start === '' && s2.time_format === '' && s2.date_order === '', 'back to automatic');

  // ================= English dates (en-GB order)
  let w = await boot({user: 'alice'}), d = w.document;
  const ev = x => w.eval(x);
  check(ev(`LOCALE()`) === 'en-GB', 'English is en-GB ' + ev(`LOCALE()`));
  check(ev(`fmtDay('short', new Date(2026, 9, 26))`) === 'Mon 26 Oct', 'short: "Mon 26 Oct" ' + ev(`fmtDay('short', new Date(2026, 9, 26))`));
  check(ev(`fmtDay('year', new Date(2026, 9, 26))`) === 'Mon 26 Oct 2026', 'year: "Mon 26 Oct 2026" ' + ev(`fmtDay('year', new Date(2026, 9, 26))`));
  check(ev(`fmtDay('long', new Date(2026, 9, 26))`) === 'Monday 26 October', 'long: "Monday 26 October" ' + ev(`fmtDay('long', new Date(2026, 9, 26))`));
  check(ev(`weekTitle('2026-10-26')`).startsWith('26 Oct – 1 Nov'), 'week title without the weekday: ' + ev(`weekTitle('2026-10-26')`));

  // ================= 12 / 24 h: a time that was shown raw (the due time of a task)
  const T = {due: '2026-10-26', due_time: '21:30'};
  ev(`S.settings.time_format = '12'`);
  const l12 = ev(`dueLabel(${JSON.stringify(T)})`);
  check(/9:30\s?PM/i.test(l12) && !l12.includes('21:30'), '12 h: the due time "9:30 PM" ' + l12);
  check(/9:30\s?PM/i.test(ev(`fmtTimeLoc('21:30')`)) && /^0?9:05\s?AM$/i.test(ev(`fmtTimeAt(new Date(2026, 0, 1, 9, 5))`).replace(/ /g, ' ')), '12 h: fmtTimeLoc / fmtTimeAt');
  ev(`S.settings.time_format = '24'`);
  const l24 = ev(`dueLabel(${JSON.stringify(T)})`);
  check(l24.endsWith(', 21:30') && ev(`fmtTimeLoc('09:05')`) === '09:05', '24 h: "…, 21:30" and "09:05" ' + l24);
  check(ev(`hour12()`) === false, '24 h: hour12() false even when the browser region writes 12 h');

  // ================= the first day of the week
  ev(`S.settings.week_start = 'sun'`);
  check(ev(`weekStart()`) === 0 && ev(`weekStartOf('2026-10-28')`) === '2026-10-25' && ev(`wdOrder()[0]`) === 0, 'Sunday: the week of Wed 28 Oct starts on Sun 25 Oct');
  check(ev(`weekOf('2026-10-28')`) === '2026-10-25', 'Sunday: dispatch / habit weeks follow the choice');
  ev(`S.settings.week_start = 'mon'`);
  check(ev(`weekStart()`) === 1 && ev(`weekStartOf('2026-10-25')`) === '2026-10-19' && ev(`weekOf('2026-10-28')`) === '2026-10-26', 'Monday: the week of Sun 25 Oct starts on Mon 19 Oct');
  ev(`S.settings.week_start = ''`);
  check(ev(`weekOf('2026-10-25')`) === '2026-10-19', 'automatic: dispatch / habit weeks keep Monday');

  // ================= numeric dates in the chosen order
  const nums = {};
  for (const o of ['', 'dmy', 'mdy', 'ymd']) { ev(`S.settings.date_order = '${o}'`); nums[o] = [ev(`fmtDate('2026-10-03')`), ev(`fmtDateNum(new Date(2026, 9, 3), false)`), ev(`mdFirst()`)]; }
  check(nums[''][0] === '03/10/2026', 'automatic (en-GB): 03/10/2026 ' + nums[''][0]);
  check(nums.dmy[0] === '03.10.2026' && nums.dmy[1] === '03.10.' && nums.dmy[2] === false, 'dmy: 03.10.2026 / 03.10. ' + JSON.stringify(nums.dmy));
  check(nums.mdy[0] === '10/03/2026' && nums.mdy[1] === '10/03' && nums.mdy[2] === true, 'mdy: 10/03/2026, typed dates month first ' + JSON.stringify(nums.mdy));
  check(nums.ymd[0] === '2026-10-03' && nums.ymd[1] === '10-03', 'ymd: 2026-10-03 ' + JSON.stringify(nums.ymd));
  ev(`S.settings.date_order = ''`);
  w.close();

  // ================= Settings > General: the three choices save at once
  w = await boot({user: 'alice'}); d = w.document;
  w.eval(`settingsModal('general')`);
  const wk = await until(() => d.querySelector('.smodal #s-wkst'));
  check(wk && wk.options.length === 3 && d.querySelector('.smodal #s-tfmt')?.options.length === 3 && d.querySelector('.smodal #s-dord')?.options.length === 4,
    'Region and formats: first day (3), time (3), date (4) choices');
  check(/Region and formats/.test(d.querySelector('.smodal #s-fmt-h')?.textContent || ''), 'the heading "Region and formats"');
  if (wk) { wk.value = 'sun'; wk.dispatchEvent(new w.Event('change', {bubbles: true})); }
  check(await until(async () => (await sets()).week_start === 'sun'), 'choosing Sunday saves week_start = sun');
  check(w.eval(`weekStart()`) === 0, 'the app starts weeks on Sunday at once');
  const tf = d.querySelector('.smodal #s-tfmt');
  if (tf) { tf.value = '12'; tf.dispatchEvent(new w.Event('change', {bubbles: true})); }
  check(await until(async () => (await sets()).time_format === '12'), 'choosing 12 hours saves time_format = 12');
  check(/PM/i.test(w.eval(`fmtTimeLoc('17:00')`)), 'the app writes 5:00 PM at once');
  w.close();
  await call('PATCH', '/api/settings', {week_start: '', time_format: '', date_order: ''});

  console.log(`p2368_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERR', e); process.exit(1); });
