// 2.93.0 UI tests, part B (#1928): the logbook in the office, own container (start.sh, mode workspaces), Firefox (desktop +
// phone width). Invented companies, people and figures only.
// - the tab "Travel expenses" has the third view "Logbook": no vehicle yet -> add one through the dialog
// - a drive by odometer: the start is prefilled with the vehicle's odometer, km follows the end; saved in the list
// - its history (created), "take over into travel expenses" opens the new trip; the drive is marked
// - the year report with the mileage allowance and the CSV / PDF links; on a phone nothing sticks out to the side
// - a member does not see the travel expenses tab (and so no logbook)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p293_b_ui', check, shots: 'P293B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P293B_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob Member', password: 'password123', email: 'bob@example.com'});
  const CB = await login('bob');
  for (const ck of [CA, CB]) await call(ck, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CA, 'PUT', `/api/orgs/${org.id}/members`, {email: 'bob@example.com', role: 'member'});
  for (const ck of [CA, CB]) await call(ck, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  await call(CA, 'POST', '/api/clients', {name: 'Kunde Eins GmbH'});
  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const noSide = `(() => { const W = document.documentElement.clientWidth; return [...document.querySelectorAll('.office .ofcbody *')].filter(e => e.getClientRects().length && !e.closest('.seg')).every(e => e.getBoundingClientRect().right <= W + 1); })()`;
  const api = (u) => `fetch('${u}', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json())`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    await nav(B + '#office/travel');
    check(await ready(ev, `!!document.querySelector('[data-rk="view"][data-v="logbook"]')`, 80), 'the travel tab has the view "Logbook"');
    await ev(`(() => { document.querySelector('[data-rk="view"][data-v="logbook"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.ofcbody [data-lgb="vnew"]') && !!document.querySelector('.lgb-note')`), 'no vehicle yet: the empty state with "Add vehicle" and the note');
    // a vehicle through the dialog
    await ev(`(() => { document.querySelector('.ofcbody [data-lgb="vnew"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal #lgb-vname')`), 'the vehicle dialog');
    await ev(`(() => { const m = document.querySelector('.modal'); m.querySelector('#lgb-vname').value = 'Kombi'; m.querySelector('#lgb-vplate').value = 'HH-AB 123'; m.querySelector('#lgb-vodo').value = '10000'; m.querySelector('[data-m="save"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.modal') && /Kombi/.test(document.querySelector('#lgb-veh')?.textContent || '') && !!document.querySelector('[data-lgb="new"]')`), 'the vehicle is selected');
    // a drive by odometer
    await ev(`(() => { document.querySelector('[data-lgb="new"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal #lgb-o1')`), 'the drive dialog');
    check(await ev(`/^10[,.]?000$/.test(document.querySelector('.modal #lgb-o0').value)`), 'the odometer at the start is prefilled ' + await ev(`document.querySelector('.modal #lgb-o0').value`));
    await ev(`(() => { const m = document.querySelector('.modal'); m.querySelector('#lgb-start').value = 'Hamburg'; m.querySelector('#lgb-dest').value = 'Lübeck'; m.querySelector('#lgb-purpose').value = 'Dreh';
      const e = m.querySelector('#lgb-o1'); e.value = '10120'; e.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
    check(await ev(`document.querySelector('.modal #lgb-km').value === '120'`), 'km follows the odometer ' + await ev(`document.querySelector('.modal #lgb-km').value`));
    await ev(`(() => { const e = document.querySelector('.modal #lgb-o1'); e.value = '9000'; e.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
    check(await ev(`/below the start/.test(document.querySelector('.modal #lgb-w').textContent)`), 'the end below the start is shown at once');
    await ev(`(() => { const e = document.querySelector('.modal #lgb-o1'); e.value = '10120'; e.dispatchEvent(new Event('input', {bubbles: true})); document.querySelector('.modal [data-m="save"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.modal') && document.querySelectorAll('.lgb-list .lgb-row').length === 1 && /120 km/.test(document.querySelector('.lgb-list .lgb-km').textContent)`), 'the drive is in the list with 120 km');
    check(await ev(`${api('/api/office/drives?year=' + new Date().getFullYear())}.then(j => j.drives.length === 1 && j.drives[0].odo_end === '10120.0' && j.drives[0].km === '120.0' && j.drives[0].dest === 'Lübeck')`), 'saved with odometer and km');
    await shot('p293-b-logbook.png');
    // history + take over into the travel expenses
    await ev(`(() => { document.querySelector('.lgb-list .lgb-row').click(); return 1; })()`);
    await ready(ev, `!!document.querySelector('.modal [data-m="log"]')`);
    await ev(`(() => { document.querySelector('.modal [data-m="log"]').click(); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('.lgb-log li').length === 1 && /Created/.test(document.querySelector('.lgb-log').textContent)`), 'the history of the drive');
    await ev(`(() => { const ms = document.querySelectorAll('.modal'); ms[ms.length - 1].querySelector('[data-m="close"]').click(); return 1; })()`);
    await ready(ev, `document.querySelectorAll('.modal').length === 1`);
    await ev(`(() => { document.querySelector('.modal [data-m="trip"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.modal') && /Lübeck/.test(document.querySelector('.rkhead h3')?.textContent || '')`, 60), 'take over: the new trip opens');
    check(await ev(`${api('/api/office/trips')}.then(j => j.trips.length === 1 && j.trips[0].km === '120.00' && j.trips[0].items.length === 0)`), 'one trip with the km, no receipt');
    await ev(`(() => { document.querySelector('[data-rk="back"]').click(); return 1; })()`);
    await ready(ev, `!!document.querySelector('[data-rk="view"][data-v="logbook"]')`);
    await ev(`(() => { document.querySelector('[data-rk="view"][data-v="logbook"]').click(); return 1; })()`);
    check(await ready(ev, `/In travel expenses/.test(document.querySelector('.lgb-list .lgb-row')?.textContent || '')`), 'the drive is marked as taken over');
    // the year report
    await ev(`(() => { document.querySelector('[data-lgb="view"][data-v="report"]').click(); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('.lgb-card').length === 1 && /36\\.00/.test(document.querySelector('.lgb-card').textContent) && /100 %/.test(document.querySelector('.lgb-card').textContent)`),
      'the year report: 120 business km x 0.30 = 36.00, share 100 % ' + await ev(`document.querySelector('.lgb-card')?.textContent`));
    check(await ev(`!!document.querySelector('a[href^="/api/office/logbook.csv"]') && !!document.querySelector('a[href^="/api/office/logbook.pdf"]')`), 'CSV and PDF links');
    await ev(`(() => { document.querySelector('#lgb-rate').value = '0.35'; document.querySelector('[data-lgb="rate"]').click(); return 1; })()`);
    check(await ready(ev, `/42\\.00/.test(document.querySelector('.lgb-card')?.textContent || '')`), 'a new rate: 120 x 0.35 = 42.00');
    await shot('p293-b-report.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await sleep(400);
    check(await ev(noSide), 'on a phone the report stays inside the screen');
    await shot('p293-b-report-phone.png');
    await ev(`(() => { document.querySelector('[data-lgb="view"][data-v="drives"]').click(); return 1; })()`);
    await ready(ev, `!!document.querySelector('.lgb-list')`);
    check(await ev(noSide), 'on a phone the drives stay inside the screen');
    check(await ev(`document.querySelector('.lgb-list .lgb-row').getBoundingClientRect().height >= 43`), 'large tap targets for the drives');
    await shot('p293-b-logbook-phone.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    // member
    await signIn(ev, 'bob');
    await nav(B + 'static/icon.svg');
    await nav(B + '#office/offers');
    // 2.93.0 (#1928): the office menu of 2.92.2 (#1917) replaces the tab row .ofctabs
    check(await ready(ev, `!!document.querySelector('#view .ofrail [data-ofm="offers"]')`, 80), 'the office (member)');  // 2.98.0 (#2180): the office rail
    check(await ev(`!document.querySelector('#view .ofrail [data-ofm="travel"]')`), 'a member does not see the travel expenses / logbook');  // 2.98.0 (#2180): the office rail
  }, false);

  console.log(`p293_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
