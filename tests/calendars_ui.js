// Calendar subscriptions UI (jsdom): events in month / week / day / timeline, "Events today", the popover (escaping,
// links), "Create task from event", offline copy, Settings > Integrations > Calendars (list, colour, show / hide,
// refresh, edit, add ICS + CalDAV, errors, remove), the admin allow-list, German labels.
// Runs after calendars_test.py on its container (stub calendar server inside; ids in cal_ids.json).
process.env.TZ = 'Europe/Berlin';
const fs = require('fs');
const path = require('path');
const {boot, errs, sleep} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const ids = JSON.parse(fs.readFileSync(path.join(__dirname, 'cal_ids.json'), 'utf8'));
const api = async (w, m, u, b) => (await w.fetch(u, {method: m, headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: b ? JSON.stringify(b) : undefined})).json();
const until = async (fn, ms = 4000) => { for (let t = 0; t < ms; t += 100) { if (fn()) return true; await sleep(100); } return false; };
const STUB = 'http://127.0.0.1:8095';
(async () => {
  let w = await boot({user: 'alice'}), d = w.document;
  await api(w, 'PATCH', `/api/calendars/${ids.daily}`, {visible: false});  // the daily calendar would push the others into "+N"
  w.close();
  w = await boot({user: 'alice', hash: 'cal', ls: {'tasks.calMode': '"month"'}}); d = w.document;
  // ---- month
  await until(() => d.querySelector('.cal .cev'));
  const chips = [...d.querySelectorAll('.cal .cev')];
  check(chips.length > 5, 'month: event chips ' + chips.length);
  // on some weekdays (Mondays: "Ancient weekly", "Weekly planning") today's cell is full ("+3"): then the agenda row of the day
  const inCell = chips.find(c => /Lunch with Sam/.test(c.textContent));
  const lunch = inCell || [...d.querySelectorAll('.agenda .cevrow')].find(c => /Lunch with Sam/.test(c.textContent));
  check(lunch && (inCell ? inCell.closest('.cell')?.dataset.day === w.eval('today()') : /\+\d/.test(d.querySelector(`.cal .cell[data-day="${w.eval('today()')}"] .more`)?.textContent || '')) && /13:00/.test(lunch.textContent), 'month: event on its day with the time');
  check(lunch && lunch.style.getPropertyValue('--cc') === '#2dd4bf', 'month: chip in the calendar colour');
  check(!d.querySelector('.cal .cev[draggable]') && !d.querySelector('.cal .cev.ev'), 'events are not task chips (no drag, no task class)');
  check(w.__xss === undefined && !d.querySelector('#view img') && [...d.querySelectorAll('.agenda .cevrow')].some(c => c.textContent.includes('<img src=x')),
    'month: HTML in a title stays text');
  check(d.querySelectorAll('.agenda .cevrow').length >= 2, 'agenda of the selected day lists its events');
  // ---- popover
  click(w, lunch); await sleep(200);
  let pop = d.querySelector('#pop');
  check(!pop.classList.contains('hidden') && pop.querySelector('.cevpop'), 'popover opens');
  check(/Cafe Central/.test(pop.textContent) && /Team/.test(pop.textContent) && /13:00–14:00/.test(pop.textContent) && /read-only/.test(pop.textContent), 'popover: place, calendar, time');
  const a = pop.querySelector('.cevdesc a');
  check(a && a.getAttribute('href') === 'https://example.org/agenda?x=1' && a.target === '_blank' && /noopener/.test(a.rel), 'popover: http(s) URL linked');
  check(!pop.querySelector('a[href^="javascript"]') && /javascript:alert\(1\)/.test(pop.textContent), 'popover: javascript: stays plain text');
  click(w, pop.querySelector('[data-cevtask]')); await sleep(1200);
  let t = [...w.eval('S.tasks').values()].filter(x => x.title === 'Lunch with Sam').pop();
  check(t && t.due === w.eval('today()') && t.due_time === '13:00' && t.duration === 60 && t.list_id === w.eval('inbox().id'), 'task from event: title, date, time, duration, inbox ' + JSON.stringify(t && [t.due, t.due_time, t.duration]));
  check(t && /From calendar: Team/.test(t.content) && /Location: Cafe Central/.test(t.content), 'task from event: note with calendar + place');
  check(w.eval('S.sel') === t?.id, 'task panel opened to edit it');
  w.eval('closeDetail()');
  const evil = [...d.querySelectorAll('.agenda .cevrow')].find(c => c.textContent.includes('<img'));
  click(w, evil); await sleep(200); pop = d.querySelector('#pop');
  check(!pop.querySelector('img,script') && /<script>window.__xss=2<\/script>/.test(pop.textContent) && pop.querySelector('.cevdesc a')?.getAttribute('href') === 'https://ok.example/path',
    'popover of the HTML event: everything escaped, only the https URL linked');
  check(w.__xss === undefined, 'no script ran');
  w.eval('closePop()');
  // ---- week + day
  w.eval(`S.calMode = 'week'; S.calSel = today(); renderView()`);
  await until(() => d.querySelector('.wcev'));
  const wl = [...d.querySelectorAll('.wcev')].find(x => /Lunch with Sam/.test(x.textContent));
  const H = w.eval('weekH()');
  check(wl && wl.closest('.wcol')?.dataset.day === w.eval('today()') && Math.abs(parseFloat(wl.style.top) - 13 * H) < 1 && Math.abs(parseFloat(wl.style.height) - H) < 1,
    'week: timed event as a block at 13:00, one hour high');
  const wad = d.querySelector(`.wad[data-day="${w.eval('today()')}"]`);
  check(wad && /Never repeats/.test(wad.textContent) && /Gym week/.test(wad.textContent), 'week: all-day events in the all-day row');
  click(w, wl); await sleep(150);
  check(d.querySelector('#pop .cevpop') && !d.querySelector('.qadd.sheet'), 'week: a click opens the popover, not the quick add');
  w.eval('closePop()');
  w.eval(`S.calMode = 'day'; renderView()`); await sleep(300);
  check(d.querySelector('.week.oneday .wcev') && d.querySelectorAll('.whead .wh').length === 1, 'day view shows events');
  // ---- timeline
  w.eval(`S.calMode = 'timeline'; S.tlStart = addDays(mondayOf(today()), -7); renderView()`);
  await until(() => [...d.querySelectorAll('.tl-cev')].some(x => /Conference trip/.test(x.textContent)));
  check(d.querySelector('.tl-grp .tl-name')?.textContent === 'Calendars' && d.querySelectorAll('.tl-cal').length >= 3, 'timeline: a calendars group with rows per calendar');
  const conf = [...d.querySelectorAll('.tl-cev')].find(x => /Conference trip/.test(x.textContent));
  check(conf && Math.abs(parseFloat(conf.style.width) - (3 * w.eval('tlDW()') - 4)) < 1, 'timeline: 3-day all-day event spans 3 days');
  click(w, conf); await sleep(150);
  check(/Conference trip/.test(d.querySelector('#pop .cevpop')?.textContent || ''), 'timeline: popover');
  w.eval('closePop()');
  // ---- Today
  w.location.hash = 'today'; await sleep(300);
  await until(() => d.querySelector('.cevtoday'));
  const rows = [...d.querySelectorAll('.cevtoday .cevrow')];
  check(rows.length >= 4 && /Events today/.test(d.querySelector('.cevtoday .ghead').textContent), 'Today: "Events today" block ' + rows.length);
  check(/all day/.test(rows[0].textContent) && rows.some(r => /13:00–14:00.*Lunch with Sam.*Cafe Central/.test(r.textContent)), 'Today: all-day first, then by time, with place');
  check(d.querySelector('.cevtoday').compareDocumentPosition(d.querySelector('#view .trow')) & 4, 'Today: the block sits above the tasks');
  click(w, d.querySelector('.cevtoday .ghead')); await sleep(100);
  check(!d.querySelector('.cevtoday .cevrow'), 'Today: block collapses');
  click(w, d.querySelector('.cevtoday .ghead')); await sleep(100);
  // offline: the last copy of the range
  w.__offline = true;
  w.eval(`calInvalidate(); S.cal.items = []; renderView()`); await sleep(500);
  check(d.querySelectorAll('.cevtoday .cevrow').length === rows.length, 'offline: events from the local copy');
  w.__offline = false; await sleep(100);
  await api(w, 'PATCH', '/api/settings', {cal_today: '0'});
  w.close();
  w = await boot({user: 'alice', hash: 'today'}); d = w.document; await sleep(500);
  check(!d.querySelector('.cevtoday'), 'Today: block off by the setting');
  await api(w, 'PATCH', '/api/settings', {cal_today: '1'});
  await w.eval('load()');
  // ---- settings
  w.eval(`settingsModal('calendars')`); await sleep(900);
  let md = d.querySelector('.smodal');
  check(!md.querySelector('#sp-integr').classList.contains('hidden') && md.querySelector('#s-cals-h')?.textContent === 'Calendars', 'settings: Integrations > Calendars');
  let subs = [...md.querySelectorAll('#s-cals .calsub')];
  check(subs.length === 4 && subs.some(r => /CalDAV · alice/.test(r.textContent)) && subs.some(r => /synced/.test(r.textContent)), 'settings: the four calendars with status');
  check(!/secret-pw|good\.ics|google\.ics/.test(md.innerHTML), 'settings: no link / password in the page');
  check(md.querySelector('#s-caltoday')?.checked === true, 'settings: Today switch');
  const dailyRow = () => md.querySelector(`#s-cals [data-cal="${ids.daily}"]`);
  check(dailyRow().classList.contains('off') && !dailyRow().querySelector('[data-calact="vis"]').checked, 'settings: hidden calendar greyed out');
  const vis = dailyRow().querySelector('[data-calact="vis"]'); vis.checked = true; vis.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(700);
  let j = await api(w, 'GET', '/api/calendars');
  check(j.subs.find(x => x.id === ids.daily).visible === true && !dailyRow().classList.contains('off'), 'settings: show a calendar again');
  check(w.eval('S.calendars.subs') === 4, 'settings: visible count updated');
  click(w, dailyRow().querySelector('[data-calact="color"]')); await sleep(150);
  click(w, d.querySelector('#pop .cpal [data-c="#c084fc"]')); await sleep(700);
  j = await api(w, 'GET', '/api/calendars');
  check(j.subs.find(x => x.id === ids.daily).color === '#c084fc', 'settings: colour from the palette');
  click(w, md.querySelector(`#s-cals [data-cal="${ids.good}"] [data-calact="refresh"]`)); await sleep(1200);
  check(/Calendar updated/.test(d.querySelector('#toast').textContent), 'settings: refresh now');
  click(w, md.querySelector(`#s-cals [data-cal="${ids.dav}"] [data-calact="edit"]`)); await sleep(200);
  let em = [...d.querySelectorAll('.modal')].pop();
  check(em.querySelector('#ce-pw') && em.querySelector('#ce-pw').value === '' && /saved/.test(em.querySelector('#ce-pw').placeholder), 'edit: password field empty, "saved"');
  em.querySelector('#ce-name').value = 'Work (DAV)';
  click(w, em.querySelector('[data-m="save"]')); await sleep(900);
  j = await api(w, 'GET', '/api/calendars');
  check(j.subs.find(x => x.id === ids.dav).name === 'Work (DAV)' && j.subs.find(x => x.id === ids.dav).status === 'ok', 'edit: renamed, password kept');
  // add: blocked address -> error in the dialog
  click(w, md.querySelector('[data-m="cal-add"]')); await sleep(200);
  let am = [...d.querySelectorAll('.modal')].pop();
  am.querySelector('#ca-url').value = 'http://ten.test/private.ics';
  click(w, am.querySelector('[data-m="ok"]')); await sleep(900);
  check(d.body.contains(am) && !am.querySelector('#ca-err').hidden && /private network/.test(am.querySelector('#ca-err').textContent), 'add: private address refused in the dialog');
  am.querySelector('#ca-url').value = STUB + '/google.ics'; am.querySelector('#ca-name').value = 'Added in UI';
  click(w, am.querySelector('[data-m="ok"]')); await sleep(1500);
  check(!d.body.contains(am) && [...md.querySelectorAll('#s-cals .calsub')].some(r => /Added in UI/.test(r.textContent)), 'add: ICS link added, list redrawn');
  // add: CalDAV (find calendars, choose, add)
  click(w, md.querySelector('[data-m="cal-add"]')); await sleep(200);
  am = [...d.querySelectorAll('.modal')].pop();
  click(w, am.querySelector('#ca-kind [data-k="caldav"]'));
  check(!am.querySelector('#ca-dav').hidden && am.querySelector('#ca-ics').hidden && am.querySelector('[data-m="ok"]').textContent === 'Find calendars', 'CalDAV form');
  am.querySelector('#ca-srv').value = STUB + '/'; am.querySelector('#ca-user').value = 'alice'; am.querySelector('#ca-pw').value = 'wrong';
  click(w, am.querySelector('[data-m="ok"]')); await sleep(900);
  check(/wrong username or password/.test(am.querySelector('#ca-err').textContent), 'CalDAV: wrong password shown');
  am.querySelector('#ca-pw').value = 'secret-pw'; am.querySelector('#ca-pw').dispatchEvent(new w.Event('input', {bubbles: true}));
  click(w, am.querySelector('[data-m="ok"]')); await sleep(1000);
  check(am.querySelectorAll('#ca-cals [data-ci]').length === 1 && /Work/.test(am.querySelector('#ca-cals').textContent) && am.querySelector('[data-m="ok"]').textContent === 'Add', 'CalDAV: calendars found');
  click(w, am.querySelector('[data-m="ok"]')); await sleep(1500);
  j = await api(w, 'GET', '/api/calendars');
  check(!d.body.contains(am) && j.subs.filter(x => x.kind === 'caldav').length === 2, 'CalDAV: added');
  // remove
  const added = j.subs.find(x => x.name === 'Added in UI');
  click(w, md.querySelector(`#s-cals [data-cal="${added.id}"] [data-calact="del"]`)); await sleep(900);
  j = await api(w, 'GET', '/api/calendars');
  check(!j.subs.some(x => x.id === added.id) && !md.querySelector(`#s-cals [data-cal="${added.id}"]`), 'remove');
  // admin allow-list
  click(w, md.querySelector('[data-sec="users"]')); await sleep(600);
  const ta = md.querySelector('#s-calhosts');
  check(ta && ta.value === 'evil.test:8095, other.lan' && /127\.0\.0\.1:8095/.test(md.querySelector('#sp-users').textContent), 'admin: allow-list with the env note');
  ta.value = 'evil.test:8095 other.lan nextcloud.home.arpa';
  ta.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(700);  // 1.5: saved when leaving the field
  check(ta.value === 'evil.test:8095, other.lan, nextcloud.home.arpa', 'admin: allow-list saved + normalized');
  ta.value = 'http://nope/';
  ta.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(700);
  check(/Not a host name/.test(d.querySelector('#toast').textContent), 'admin: invalid entry refused');
  md.remove(); w.close();
  // ---- carol: no admin section; German labels
  w = await boot({user: 'carol'}); d = w.document;
  await api(w, 'PATCH', '/api/settings', {lang: 'de'}); w.close();
  w = await boot({user: 'carol', hash: 'today'}); d = w.document;
  await until(() => d.querySelector('.cevtoday'));
  check(/Termine heute/.test(d.querySelector('.cevtoday .ghead')?.textContent || ''), 'German: "Termine heute"');
  w.eval(`settingsModal('calendars')`); await sleep(900);
  md = d.querySelector('.smodal');
  check(md.querySelector('#s-cals-h')?.textContent === 'Kalender' && md.querySelectorAll('#s-cals .calsub').length === 20 && /Kalender hinzufügen/.test(md.textContent), 'German settings, carol\'s 20 calendars');
  check(!md.querySelector('#s-calhosts'), 'non-admin: no allow-list');
  md.remove(); w.close();
  check(!errs.length, 'no script errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
