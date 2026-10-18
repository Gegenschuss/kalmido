// 2.95.0 UI tests, part A (#1932): the per diem (Verpflegungsmehraufwand) in the travel expenses, own container (start.sh,
// mode workspaces), Firefox (desktop + phone width). Invented companies, people and figures only; rates from the tables in
// kalmido/office/vma.py (Germany 28 / 14, Greece 2025 36 / 24 with the city Athen).
// - the trip list shows the per diem next to the receipts; the trip view has the card "Per diem" with the breakdown
// - "Edit days": ticking breakfast + lunch on a day cuts the rate (56 -> 39.20), one undo step takes it back
// - the trip dialog: country (+ city when the country has cities), start / end time for a single day, "No per diem";
//   a new single-day trip with times gets 14
// - the evaluation: the block "Per diem allowances 2025" with the sum per person and PDF / Excel / CSV; on a phone nothing
//   sticks out to the side
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p295_a_ui', check, shots: 'P295A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P295A_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CA, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  const trip = await call(CA, 'POST', '/api/office/trips', {date_from: '2025-03-10', date_to: '2025-03-12', overnight: 1, dest: 'Hamburg', people: [{id: me.id}, {name: 'Externe Person'}],
    items: [{date: '2025-03-10', category: 'train', amount: 100}]});
  check(trip.http === 201 && trip.vma.amount === '56.00' && trip.vma.total === '112.00', 'a trip with a per diem ' + JSON.stringify(trip.vma));

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const getTrip = id => `fetch('/api/office/trips?year=2025', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => j.trips.find(t => t.id === ${id}))`;
  const noSide = `(() => { const W = document.documentElement.clientWidth; return [...document.querySelectorAll('.office .ofcbody *')].filter(e => e.getClientRects().length && !e.closest('.seg')).every(e => e.getBoundingClientRect().right <= W + 1); })()`;
  const setv = (sel, v) => `(() => { const x = document.querySelector('.modal ${sel}'); x.value = ${JSON.stringify(v)}; x.dispatchEvent(new Event('input', {bubbles: true})); x.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    await nav(B + '#office/travel');
    check(await ready(ev, `!!document.querySelector('#rk-year')`, 80), 'the travel tab');
    await ev(`(() => { const s = document.querySelector('#rk-year'); s.value = '2025'; s.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('.rklist .ofcrow').length === 1`, 80), 'the trip of 2025 in the list');
    check(await ev(`/112\\.00/.test(document.querySelector('.rklist .rkv-tag')?.textContent || '')`), 'the list shows the per diem of both participants ' + await ev(`document.querySelector('.rklist .ofcrow')?.textContent`));
    // the trip view
    await ev(`(() => { document.querySelector('.rklist .ofcrow').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.rkv-card')`), 'the per diem card');
    check(await ev(`(() => { const c = document.querySelector('.rkv-card').textContent; return /112\\.00/.test(c) && /56\\.00 € per person × 2/.test(c) && /Germany: 2 × 14 € \\+ 1 × 28 € = 56 €/.test(c) && /BMF/.test(c); })()`),
      'the card: total, per person, breakdown, source ' + await ev(`document.querySelector('.rkv-card').textContent`));
    // edit days: breakfast + lunch on the full day
    await ev(`(() => { document.querySelector('[data-rkv="days"]').click(); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('.modal .rkv-day').length === 3`), 'the days dialog lists the three days');
    check(await ev(`[...document.querySelectorAll('.modal .rkv-meal')].every(l => l.getBoundingClientRect().height >= 43)`), 'large tap targets for the meals');
    await ev(`(() => { const d = document.querySelectorAll('.modal .rkv-day')[1]; d.querySelector('[data-meal="b"]').click(); d.querySelector('[data-meal="l"]').click(); document.querySelector('.modal [data-m="save"]').click(); return 1; })()`);
    check(await ready(ev, `${getTrip(trip.id)}.then(t => t.vma.amount === '39.20' && t.vma_days.length === 1 && t.vma_days[0].date === '2025-03-11')`), 'meals provided cut the rate (39.20)');
    check(await ready(ev, `!document.querySelector('.modal') && /78\\.40/.test(document.querySelector('.rkv-card')?.textContent || '')`), 'the card follows (2 × 39.20)');
    await shot('p295-a-trip.png');
    await ev(`(() => { document.querySelector('#toast button').click(); return 1; })()`);
    check(await ready(ev, `${getTrip(trip.id)}.then(t => t.vma.amount === '56.00' && t.vma_days.length === 0)`), 'one undo step takes the meals back');
    // the trip dialog: country + city
    await ready(ev, `!!document.querySelector('[data-rk="edit"]')`);
    await ev(`(() => { document.querySelector('[data-rk="edit"]').click(); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('.modal #rk-cty option').length > 100`), 'the country choice with the countries of the table');
    check(await ev(`document.querySelector('.modal #rk-cty option').value === 'DE' && document.querySelector('.modal .rkv-tm').hidden && document.querySelector('.modal .rkv-pl').hidden`),
      'Germany first; no times for a trip with an overnight stay; no city for Germany');
    await ev(setv('#rk-cty', 'GR'));
    check(await ready(ev, `!document.querySelector('.modal .rkv-pl').hidden && [...document.querySelectorAll('.modal #rk-place option')].some(o => o.value === 'Athen')`), 'Greece offers its city');
    await ev(`(() => { document.querySelector('.modal [data-m="save"]').click(); return 1; })()`);
    check(await ready(ev, `${getTrip(trip.id)}.then(t => t.country === 'GR' && t.place === '' && t.vma.amount === '84.00')`), 'saved: Greece outside Athens 24 + 36 + 24 = 84');
    await ev(`(() => { document.querySelector('#toast button').click(); return 1; })()`);
    check(await ready(ev, `${getTrip(trip.id)}.then(t => t.country === '' && t.vma.amount === '56.00')`), 'the undo of the dialog restores the country');
    // a new single-day trip with times
    await ev(`(() => { document.querySelector('[data-rk="back"]').click(); return 1; })()`);
    await ready(ev, `!!document.querySelector('[data-rk="new"]')`);
    await ev(`(() => { document.querySelector('[data-rk="new"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal #rk-voff') && !document.querySelector('.modal .rkv-tm').hidden`), 'a single day shows start and end time');
    await ev(setv('#rk-from', '2025-06-02'));
    await ev(setv('#rk-dest', 'Lübeck'));
    await ev(`(() => { document.querySelector('.modal [data-pid]').click(); return 1; })()`);
    await ev(setv('#rk-ts', '08:00'));
    await ev(setv('#rk-te', '17:30'));
    await ev(`(() => { document.querySelector('.modal [data-m="save"]').click(); return 1; })()`);
    check(await ready(ev, `fetch('/api/office/trips?year=2025', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => j.trips.some(t => t.dest === 'Lübeck' && t.t_start === '08:00' && t.vma.amount === '14.00'))`),
      'a single day of 9.5 hours gets 14');
    // the evaluation
    await ev(`(() => { document.querySelector('[data-rk="back"]')?.click(); return 1; })()`);
    await ready(ev, `!!document.querySelector('[data-rk="view"][data-v="report"]')`);
    await ev(`(() => { document.querySelector('[data-rk="view"][data-v="report"]').click(); return 1; })()`);
    check(await ready(ev, `/Per diem allowances 2025/.test(document.querySelector('.rkv-rep')?.textContent || '') && document.querySelectorAll('.rkv-people > li').length === 2`, 60),
      'the per diem block of 2025 with two people');
    check(await ev(`/126\\.00/.test(document.querySelector('.rkv-total').textContent) && ['pdf', 'xlsx', 'csv'].every(x => !!document.querySelector('.rkv-rep a[href*="/vma.' + x + '?year=2025"]'))`),
      'the total (56 + 14 + 56) and PDF / Excel / CSV ' + await ev(`document.querySelector('.rkv-rep')?.textContent`));
    await ev(`(() => { document.querySelector('.rkv-people summary').click(); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('.rkv-people details[open] .rkv-trips li').length === 2`), 'a person opens to the trips');
    await shot('p295-a-report.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await sleep(400);
    check(await ev(noSide), 'on a phone the report stays inside the screen');
    await shot('p295-a-report-phone.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
  }, false);

  console.log(`p295_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
