// 2.52.0 UI tests, part B (#1128 writing into subscribed CalDAV calendars), own container (start.sh) with the fake calendar
// server inside (stub_calendar.py), Firefox (desktop + phone width). Invented events only.
// - the subscription's edit window has "Allow writing" (CalDAV only), on after the API switched it
// - an event of the writable calendar: the popover offers Edit / Delete; Edit opens the event window with only that
//   calendar and without repeat / reminders / people; Save changes the resource on the server
// - a new event: the "Calendar" field lists the subscription as its own group; saving writes it there
// - dvw_commit (dragging, part A) moves the event, one undo step moves it back
// - phone width: the event window of a subscription fits the screen
const fs = require('fs');
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p252_b_ui', check, shots: 'P252B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const CT = process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test';
fs.rmSync(DATA, {recursive: true, force: true}); fs.mkdirSync(DATA, {recursive: true});
fs.copyFileSync(path.join(__dirname, 'stub_calendar.py'), path.join(DATA, 'stub_calendar.py'));
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, KEEP: '1', EXTRA: '-e KALMIDO_CALENDAR_ALLOW_HOSTS=127.0.0.1:8095 -e KALMIDO_CALENDAR_REFRESH_GAP=0'}});
execFileSync('docker', ['exec', '-d', CT, 'python', '/data/stub_calendar.py']);
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const store = () => { try { return JSON.parse(fs.readFileSync(path.join(DATA, 'rwstore.json'), 'utf8')).rw || {}; } catch { return {}; } };
const ymd = n => { const d = new Date(); d.setDate(d.getDate() + n); return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}${String(d.getDate()).padStart(2, '0')}`; };

(async () => {
  await sleep(900);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', modules: ['cal']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,events'});
  const sub = await call(CA, 'POST', '/api/calendars', {kind: 'caldav', url: 'http://127.0.0.1:8095/dav/', username: 'alice', password: 'secret-pw',
    calendars: [{url: 'http://127.0.0.1:8095/dav/calendars/alice/rw/', name: 'Studio calendar'}]});
  check(sub.http === 200 && sub.created?.length === 1, 'subscription ' + sub.http);
  const RW = sub.created?.[0];
  const sw = await call(CA, 'POST', `/api/calendars/${RW}/write`, {on: true});
  check(sw.http === 200 && sw.write === true, 'allow writing ' + sw.http);

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const fits = `(() => { const c = document.querySelector('.evmodal'); const W = document.documentElement.clientWidth; return !!c && [...c.querySelectorAll('*')].filter(e => e.getClientRects().length && !e.closest('[hidden]')).every(e => e.getBoundingClientRect().right <= W + 1); })()`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    await nav(B + '#cal');
    await ready(ev, `typeof dvw_commit === 'function' && typeof S !== 'undefined' && !!S.booted`, 80);
    // 2.56.4 (#1863): the week of the stub event's day (today + 2) -- the week of today misses it on Fridays / Saturdays
    // (en: the week starts on Sunday)
    await ev(`(() => { S.calMode = 'week'; S.calSel = '${ymd(2).replace(/(\d{4})(\d\d)(\d\d)/, '$1-$2-$3')}'; renderView(); return 1; })()`);
    check(await ready(ev, `S.cal.items.some(e => e.uid === 'rw-1@stub' && e.dvw_write)`, 80), 'the writable event is loaded and marked');
    // ---- the subscription's edit window: "Allow writing"
    await ev(`(async () => { const j = await api('GET', '/api/calendars'); calEditModal(j.subs.find(s => s.id === ${RW}), j.colors, () => {}); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('#ce-dvw') && document.querySelector('#ce-dvw').checked`), 'edit window: "Allow writing" switched on');
    await shot('p252-b-allow-writing.png');
    await ev(`(() => { document.querySelector('#ce-dvw').closest('.modal').remove(); return 1; })()`);
    // ---- popover + Edit
    await ev(`(() => { const e = S.cal.items.find(x => x.uid === 'rw-1@stub'); S.calSel = e.d0; renderView(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('[data-cev="' + S.cal.items.find(x => x.uid === 'rw-1@stub').id + '"]')`, 40), 'the event shows in the week');
    await ev(`(() => { const id = S.cal.items.find(x => x.uid === 'rw-1@stub').id; cevPop(document.querySelector('[data-cev="' + id + '"]'), id); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.cevpop [data-dvw="edit"]') && !!document.querySelector('.cevpop [data-dvw="del"]')`), 'popover: Edit + Delete');
    await ev(`(() => { document.querySelector('.cevpop [data-dvw="edit"]').click(); return 1; })()`);
    check(await ready(ev, `document.querySelector('#ev-cal')?.value === 's${RW}' && document.querySelectorAll('#ev-cal option').length === 1`), 'edit: only the subscription in the Calendar field');
    check(await ev(`document.querySelector('.evrep').hidden && document.querySelector('.evrems').hidden && document.querySelector('.evatts').hidden && document.querySelector('#ev-title').value === 'Writable one'`),
      'edit: repeat / reminders / people hidden, the title filled in');
    await ev(`(() => { document.querySelector('#ev-title').value = 'Writable one (edited)'; document.querySelector('[data-evm="save"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.evmodal')`, 40), 'edit: saved, window closed');
    check(/SUMMARY:Writable one \(edited\)/.test(store()['one.ics']?.[1] || '') && /X-STUB-KEEP:yes/.test(store()['one.ics']?.[1] || ''), 'edit: the server got the new title, unknown properties kept');
    // ---- new event into the subscription
    await ev(`(() => { evEditor({start: '${ymd(6).replace(/(\d{4})(\d\d)(\d\d)/, '$1-$2-$3')}T15:00'}); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('#ev-cal optgroup option[value="s${RW}"]')`), 'new event: the subscription is offered as its own group');
    await ev(`(() => { const s = document.querySelector('#ev-cal'); s.value = 's${RW}'; s.dispatchEvent(new Event('change', {bubbles: true})); document.querySelector('#ev-title').value = 'Rehearsal'; return 1; })()`);
    check(await ev(`document.querySelector('.evrep').hidden && document.querySelector('.evmore').hidden`), 'new event: fields the subscription does not take are hidden');
    await ev(`(() => { document.querySelector('[data-evm="save"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.evmodal')`, 40), 'new event: saved');
    const neu = Object.values(store()).find(v => /SUMMARY:Rehearsal/.test(v[1]));
    check(!!neu && new RegExp(`DTSTART;TZID=[^:]+:${ymd(6)}T150000`).test(neu[1]), 'new event: written into the CalDAV calendar');
    // ---- dvw_commit (dragging) + undo
    await ready(ev, `S.cal.items.some(e => e.uid === 'rw-1@stub')`, 40);
    const moved = await ev(`(async () => { const e = S.cal.items.find(x => x.uid === 'rw-1@stub'); const d = addDays(e.d0, 1); return await dvw_commit(e, {start: d + 'T07:15', end: d + 'T08:15', all_day: false}, 'all'); })()`);
    check(moved === true && new RegExp(`DTSTART;TZID=Europe/Berlin:${ymd(3)}T071500`).test(store()['one.ics']?.[1] || ''), 'dvw_commit moves the event on the server ' + moved);
    await ready(ev, `S.cal.items.some(e => e.uid === 'rw-rec@stub')`, 40);
    const rec = await ev(`(async () => { const e = S.cal.items.find(x => x.uid === 'rw-rec@stub'); return await dvw_commit(e, {start: e.d0 + 'T10:00', end: e.d0 + 'T10:30', all_day: false}, 'one'); })()`);
    check(rec === false, 'dvw_commit: "only this date" of a series refused ' + rec);
    await ev(`(async () => { await histStep('undo'); return 1; })()`);
    let back = false;
    for (let i = 0; i < 40 && !back; i++) { back = new RegExp(`DTSTART;TZID=Europe/Berlin:${ymd(2)}T090000`).test(store()['one.ics']?.[1] || ''); if (!back) await sleep(250); }
    check(back, 'undo moves it back');
    // ---- phone
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await ev(`(() => { dvw_edit(S.cal.items.find(x => x.uid === 'rw-1@stub')); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.evmodal')`), 'phone: the event window opens');
    check(await ev(fits), 'phone: the event window fits the width');
    await shot('p252-b-edit-phone.png');
  }, false);
  console.log(`p252_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
