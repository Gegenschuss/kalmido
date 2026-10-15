// 2.47.3 UI tests, part B (office: travel expenses #1022, cash flow #1652), own container (start.sh, mode workspaces), Firefox
// (desktop + phone width). Invented companies, people and figures only.
// - #1022: the admin has the tab "Travel expenses": the trips with their sum and the count not in DATEV, a trip with its
//   receipts, ticking "in DATEV" saves and the filter "Not in DATEV" follows; a new receipt through the dialog; the
//   evaluation as a table with a CSV link; on a phone nothing sticks out to the side
// - #1652: the tab "Cash flow": one card per month (3, switched to 6), actual and planned apart, a tap on a value lists the
//   entries behind it; a new fixed cost through the dialog shows up in every month
// - a member sees neither tab
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2473_b_ui', check, shots: 'P2473B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients';
const today = new Date().toISOString().slice(0, 10);

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
  const cl = await call(CA, 'POST', '/api/clients', {name: 'Kunde Eins GmbH'});
  const trip = await call(CA, 'POST', '/api/office/trips', {date_from: today, dest: 'Hamburg - Berlin', people: [{id: me.id}, {name: 'Externe Person'}], client_id: cl.id, project: 'Imagefilm',
    items: [{date: today, category: 'train', amount: 129.9, text: 'ICE'}, {date: today, category: 'hotel', amount: 220}]});
  check(trip.http === 201 && trip.missing === 2, 'a trip with two receipts ' + trip.http);

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const noSide = `(() => { const W = document.documentElement.clientWidth; return [...document.querySelectorAll('.office .ofcbody *')].filter(e => e.getClientRects().length && !e.closest('.seg')).every(e => e.getBoundingClientRect().right <= W + 1); })()`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    // ================= #1022
    await nav(B + '#office/travel');
    check(await ready(ev, `document.querySelectorAll('.rklist .ofcrow').length === 1`, 80), '#1022: the travel tab lists the trip');
    check(await ev(`!!document.querySelector('.ofctabs [data-go="office/travel"]') && !!document.querySelector('.ofctabs [data-go="office/cashflow"]')`), '#1022 #1652: both tabs for the admin');
    check(await ev(`/2 not in DATEV/.test(document.querySelector('.rklist .ofcrow').textContent) && /349\\.90/.test(document.querySelector('.rklist .rksum').textContent)`),
      '#1022: the trip row shows the sum and the receipts not in DATEV ' + await ev(`document.querySelector('.rklist .ofcrow')?.textContent`));
    await ev(`(() => { document.querySelector('.rklist .ofcrow').click(); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('.rkits .rkit').length === 2`), '#1022: the trip with its receipts');
    await shot('p2473-b-trip.png');
    await ev(`(() => { document.querySelector('.rkits [data-rk="datev"]').click(); return 1; })()`);
    check(await ready(ev, `fetch('/api/office/trips', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => j.missing === 1)`), '#1022: the tick "in DATEV" is saved');
    await ready(ev, `document.querySelector('.rkits [data-rk="datev"]')?.checked`);
    // a new receipt through the dialog
    await ev(`(() => { document.querySelector('[data-rk="add"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal #rk-amt')`), '#1022: the receipt dialog');
    await ev(`(() => { const m = document.querySelector('.modal'); m.querySelector('#rk-cat').value = 'taxi'; m.querySelector('#rk-amt').value = '18,50'; m.querySelector('#rk-text').value = 'Taxi Bahnhof'; m.querySelector('[data-m="save"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.modal') && document.querySelectorAll('.rkits .rkit').length === 3`), '#1022: the new receipt is in the list');
    check(await ev(`fetch('/api/office/trips', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => j.trips[0].total === '368.40' && j.trips[0].items.some(i => i.category === 'taxi' && i.amount === '18.50'))`),
      '#1022: saved with category and amount (comma accepted)');
    // phone width
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await sleep(400);
    check(await ev(noSide), '#1022: on a phone the receipts stay inside the screen');
    check(await ev(`[...document.querySelectorAll('.rkits [data-rk="datev"], .rkits [data-rk="sel"]')].every(x => x.closest('label').getBoundingClientRect().height >= 43)`), '#1022: large tap targets for the ticks');
    await shot('p2473-b-trip-phone.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    // the filter "Not in DATEV" + the evaluation
    await ev(`(() => { document.querySelector('[data-rk="back"]').click(); return 1; })()`);
    await ready(ev, `!!document.querySelector('[data-rk="filter"][data-v="missing"]')`);
    await ev(`(() => { document.querySelector('[data-rk="view"][data-v="report"]').click(); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('.rktab tbody tr').length === 1 && /368\\.40/.test(document.querySelector('.rktab tfoot').textContent)`), '#1022: the evaluation by month');
    await ev(`(() => { document.querySelector('[data-rk="by"][data-v="category"]').click(); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('.rktab tbody tr').length === 3 && /Hotel/.test(document.querySelector('.rktab tbody').textContent)`), '#1022: the evaluation by category');
    check(await ev(`/by=category.*format=csv/.test(document.querySelector('a[href*="format=csv"]')?.getAttribute('href') || '')`), '#1022: the CSV link follows the grouping');
    await shot('p2473-b-report.png');
    // ================= #1652
    await nav(B + '#office/cashflow');
    check(await ready(ev, `document.querySelectorAll('.rkcfms .rkcfm').length === 3`, 80), '#1652: three months by default');
    check(await ev(`document.querySelector('.rkcfm.cur') === document.querySelector('.rkcfms .rkcfm') && /368\\.40/.test(document.querySelector('.rkcfm.cur').textContent)`), '#1652: this month first, with the travel receipts as out');
    await ev(`(() => { document.querySelector('.rkcfm.cur .rkcfv[data-k$="|out|actual"]').click(); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('.rkcfm.cur .rkcfents li').length === 3 && /Travel expenses/.test(document.querySelector('.rkcfm.cur .rkcfents').textContent)`), '#1652: a tap on a value lists the entries behind it');
    await ev(`(() => { document.querySelector('[data-rkf="months"][data-v="6"]').click(); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('.rkcfms .rkcfm').length === 6`), '#1652: switched to six months');
    await ev(`(() => { document.querySelector('[data-rkf="fnew"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal #cf-amount')`), '#1652: the fixed cost dialog');
    await ev(`(() => { const m = document.querySelector('.modal'); m.querySelector('#cf-label').value = 'Miete'; m.querySelector('#cf-amount').value = '1200'; m.querySelector('[data-m="save"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.modal') && [...document.querySelectorAll('.rkcfms .rkcfm')].slice(1).every(c => /1,200\\.00/.test(c.textContent))`), '#1652: the monthly fixed cost is in every month');
    await shot('p2473-b-cashflow.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await sleep(400);
    check(await ev(noSide), '#1652: on a phone the months stay inside the screen');
    await shot('p2473-b-cashflow-phone.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    // ================= member
    await signIn(ev, 'bob');
    await nav(B + 'static/icon.svg');
    await nav(B + '#office/offers');
    check(await ready(ev, `!!document.querySelector('.ofctabs [data-go="office/offers"]')`, 80), 'the office (member)');
    check(await ev(`!document.querySelector('.ofctabs [data-go="office/travel"]') && !document.querySelector('.ofctabs [data-go="office/cashflow"]')`), '#1022 #1652: a member sees neither tab');
  }, false);

  console.log(`p2473_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
