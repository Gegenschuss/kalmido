// 2.155.0 UI tests, part B (#2076 holidays + absences in the calendar, #2077 the availability bar), own container
// (start.sh, mode workspaces), Firefox (desktop + phone width). Invented names, addresses @example.com only.
// - the month view shows the holidays of the organisation's state as a quiet outlined all-day chip; a click opens the
//   read-only popover without "Create task from event"
// - the "Calendars" window has the group "Holidays and absences": holidays + my absences on, the team's off, the state
//   picker (Austria offered), the subscription link; switching the team's absences on shows a colleague as "away"
// - the event editor shows the availability bar for me and an invited colleague: the colleague away on that day, the
//   event's time marked; on a phone the bar stays inside the screen
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2155_b_ui', check, shots: 'P2155B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2155B_NOSTART) {
  execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
}
const pad = n => String(n).padStart(2, '0');
const iso = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

(async () => {
  await sleep(900);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice Beispiel', password: 'password123'})});
  check(r.ok, 'setup');
  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const call = (ev, method, url, body) => ev(`fetch('${url}', {method: '${method}', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}${body ? `, body: JSON.stringify(${JSON.stringify(body)})` : ''}}).then(r => r.text()).then(t => { try { return JSON.parse(t); } catch { return null; } })`);
  const noSide = sel => `(() => { const W = document.documentElement.clientWidth; return [...document.querySelectorAll('${sel} *')].filter(e => e.getClientRects().length).every(e => e.getBoundingClientRect().right <= W + 1); })()`;
  let d = new Date(); d.setDate(d.getDate() + 14); while (d.getDay() === 0 || d.getDay() === 6) d.setDate(d.getDate() + 1);
  const D = iso(d);
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    await call(ev, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true});
    await call(ev, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,events,contacts,workload'});
    const me = (await call(ev, 'GET', '/api/state')).me.id;
    const bob = await call(ev, 'POST', '/api/users', {username: 'bob', display_name: 'Bob Beispiel', password: 'password123', email: 'bob@example.com'});
    const org = await call(ev, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me});
    check(!!(bob && bob.id && org && org.id), 'setup: bob + organisation Alpha');
    await call(ev, 'PUT', `/api/orgs/${org.id}/members`, {email: 'bob@example.com'});
    execFileSync('python3', [path.join(__dirname, 'dbx.py'), DATA, `DELETE FROM org_members WHERE org_id<>${org.id}`]);
    const st = await call(ev, 'PUT', '/api/team/absences/holidays', {state: 'BY', org: org.id});
    check(st && st.state === 'BY', 'Alpha: Bavaria ' + JSON.stringify(st));
    const ab = await call(ev, 'POST', '/api/team/absences', {kind: 'sick', start_date: D, end_date: D, user_id: bob.id, note: 'vertraulich', org: org.id});
    check(ab && ab.id, 'bob is away on ' + D + ' ' + JSON.stringify(ab));
    const cal = await call(ev, 'POST', '/api/evcals', {name: 'Alice Termine'});
    await nav(B + '#cal');
    check(await ready(ev, `!!document.querySelector('#view .calbar [data-act="ev-cals"]')`, 80), 'the calendar view');

    // ---- #2076: the holiday in the month view
    await ev(`(() => { S.calSel = '2027-01-01'; S.calMonth = '2027-01'; S.calMode = 'month'; renderView(); return 1; })()`);
    const ny = await ready(ev, `[...document.querySelectorAll('#view .cal .cev.cevx')].some(x => x.textContent.includes('Neujahr'))`, 60);
    check(ny, 'New Year as a quiet chip in January');
    if (!ny) console.log('debug:', JSON.stringify(await call(ev, 'GET', '/api/calendars/events?from=2027-01-01&to=2027-01-07')).slice(0, 400),
      await ev(`JSON.stringify({key: S.cal.key, n: S.cal.items.length, on: calEvOn(), set: [S.settings.cal_holidays, S.settings.cal_abs], cells: document.querySelectorAll('#view .cal .cell').length, cev: document.querySelectorAll('#view .cal .cev').length})`));
    check(await ev(`[...document.querySelectorAll('#view .cal .cev.cevx')].some(x => x.textContent.includes('Heilige Drei'))`), 'Epiphany too (Bavaria)');
    check(await ev(`getComputedStyle(document.querySelector('#view .cal .cev.cevx')).borderTopStyle === 'dashed'`), 'the chip is outlined, not filled');
    await shot('p2155-b-month.png');
    await ev(`(() => { [...document.querySelectorAll('#view .cal .cev.cevx')].find(x => x.textContent.includes('Neujahr'))?.click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.cevpop')`), 'a click opens the popover');
    check(await ev(`/Public holidays/.test(document.querySelector('.cevpop').textContent) && !document.querySelector('.cevpop [data-cevtask]')`),
      'the popover names "Public holidays", no "Create task from event"');
    await ev(`(() => { closePop(); return 1; })()`);

    // ---- #2076: the "Calendars" window
    await ev(`(() => { document.querySelector('[data-act="ev-cals"]').click(); return 1; })()`);
    check(await ready(ev, `[...document.querySelectorAll('.evcmodal .cvxgrp')].some(x => /Holidays and absences/.test(x.textContent))`, 60), 'the group "Holidays and absences"');
    check(await ev(`document.querySelector('.evcmodal [data-key="x:hol"]').checked && document.querySelector('.evcmodal [data-key="x:abs"]').checked && !document.querySelector('.evcmodal [data-key="x:team"]').checked`),
      'holidays + my absences on, the team off');
    check(await ready(ev, `!!document.querySelector('#abc-state option[value="AT"]') && /Bayern/.test(document.querySelector('#abc-state option[value=""]').textContent)`),
      'the state picker: "As my organisation (Bayern)", Austria offered');
    check(!!(await ev(`document.querySelector('.evcmodal [data-abc="feed"]')`)), 'the subscription link button');
    await shot('p2155-b-calendars.png');
    await ev(`(() => { document.querySelector('.evcmodal [data-key="x:team"]').click(); return 1; })()`);
    check(await ready(ev, `S.settings.cal_abs_team === '1'`), 'the team switch is saved');
    await ev(`(() => { document.querySelector('.evcmodal [data-evc="close"]').click(); S.calSel = '${D}'; S.calMonth = '${D}'.slice(0, 7); S.calMode = 'agenda'; renderView(); return 1; })()`);
    check(await ready(ev, `[...document.querySelectorAll('#view .cevrow')].some(x => /Bob Beispiel: away/.test(x.textContent))`, 60), 'the agenda shows bob away');
    check(!(await ev(`/Sick|vertraulich/.test(document.querySelector('#view').textContent)`)), 'never the kind or the note');

    // ---- #2077: the availability bar
    await call(ev, 'POST', '/api/events', {cal_id: cal.id, title: 'Vorher', start: `${D}T09:00`, end: `${D}T10:00`, tz: 'Europe/Berlin'});
    await ev(`(() => { evEditor({start: '${D}T09:30', end: '${D}T10:30', cal_id: ${cal.id}}); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.evmodal #ev-attin')`), 'the event editor');
    check(await ready(ev, `document.querySelectorAll('#ev-fb .efbr').length === 1`), 'the bar shows me alone first');
    check(await ready(ev, `document.querySelector('#ev-fb .efbr')?.classList.contains('busy')`), 'my earlier event collides: busy');
    await ev(`(() => { const m = document.querySelector('.evmodal'); const i = m.querySelector('#ev-attin'); i.value = 'Bob Beispiel'; m.querySelector('[data-evm="attadd"]').click(); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('#ev-fb .efbr').length === 2`), 'inviting bob adds his line');
    check(await ready(ev, `[...document.querySelectorAll('#ev-fb .efbr')].some(x => x.classList.contains('away') && /Bob/.test(x.textContent) && /away/.test(x.textContent))`), 'bob is away that day');
    check(await ev(`!!document.querySelector('#ev-fb .efbsel') && !!document.querySelector('#ev-fb .efbb.busy')`), 'the event\'s time marked, my busy span grey');
    check(!(await ev(`/Vorher/.test(document.querySelector('#ev-fb').textContent)`)), 'no titles in the bar');
    await shot('p2155-b-bar.png');
    await ev(`(() => { const m = document.querySelector('.evmodal'); dpSet(m.querySelector('#ev-stm'), '12:00'); dpSet(m.querySelector('#ev-etm'), '13:00'); m.querySelector('#ev-stm').dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    check(await ready(ev, `document.querySelector('#ev-fb .efbr')?.classList.contains('free')`), 'a later time: I am free');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await sleep(500);
    check(await ev(noSide('.evmodal #ev-fb')), 'on a phone the bar stays inside the screen');
    await shot('p2155-b-bar-phone.png');
  }, false);

  console.log(`p2155_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
