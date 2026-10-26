// 2.117.0 UI tests, part A (#2290 #2287 #2291 #2292): travel expenses, own container (start.sh), Firefox (desktop + phone
// width), an organisation's admin and a person without an organisation. Invented companies, people and figures only.
// - #2290 the "To" picker of a trip opens at the start day (in the past), the start day marked, days before it disabled; a
//   later start moves an earlier end along
// - #2292 the purpose choice ends with "Add another purpose…": a field right below, Enter stores the own purpose and chooses
//   it, the trip saves it, the list shows it; the office settings list it (rename in place, remove + undo)
// - #2287 the arrow of a trip row opens the row menu (44 px on a phone): duplicate, delete with undo
// - #2291 the person filter next to All / Not in DATEV: filters the list, stays in the evaluation (report + per diem links),
//   hidden for a person without an organisation who travels alone -- freelancer-matrix: office
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2117_a_ui', check, shots: 'P2117A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2117A_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
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
  const fr = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fr.http < 300, 'a person without an organisation');
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  await call(CF, 'POST', '/api/office/trips', {date_from: '2025-04-07', dest: 'Potsdam', people: [{id: fr.id}], items: [{date: '2025-04-07', category: 'car', amount: 20}]});
  const t1 = await call(CA, 'POST', '/api/office/trips', {date_from: '2025-03-10', date_to: '2025-03-11', overnight: 1, dest: 'Hamburg', people: [{id: me.id}],
    items: [{date: '2025-03-10', category: 'train', amount: 100}]});
  const t2 = await call(CA, 'POST', '/api/office/trips', {date_from: '2025-03-20', dest: 'Kiel', people: [{name: 'Externe Person'}], items: [{date: '2025-03-20', category: 'taxi', amount: 30}]});
  check(t1.http === 201 && t2.http === 201, 'two trips');

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const getJ = url => `fetch('${url}', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json())`;
  const noSide = `(() => { const W = document.documentElement.clientWidth; return [...document.querySelectorAll('.office .ofcbody *')].filter(e => e.getClientRects().length && !e.closest('.seg')).every(e => e.getBoundingClientRect().right <= W + 1); })()`;
  const setv = (sel, v) => `(() => { const x = document.querySelector('${sel}'); x.value = ${JSON.stringify(v)}; x.dispatchEvent(new Event('input', {bubbles: true})); x.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`;
  const clk = sel => `(() => { const x = document.querySelector('${sel}'); if (!x) return 0; x.click(); return 1; })()`;
  const year = async ev => { await ev(setv('#rk-year', '2025')); };
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    await nav(B + '#office/travel');
    check(await ready(ev, `!!document.querySelector('#rk-year')`, 80), 'the travel tab');
    await year(ev);
    check(await ready(ev, `document.querySelectorAll('.rklist .ofcrow').length === 2`, 80), 'the two trips of 2025');

    // ---- #2290: the "To" picker opens at the start day
    await ev(clk('[data-rk="new"]'));
    check(await ready(ev, `!!document.querySelector('.modal #rk-to')`), 'the trip dialog');
    await ev(setv('.modal #rk-from', '2025-12-05'));
    await ev(clk('.modal [data-dpfor="rk-to"]'));
    check(await ready(ev, `!!document.querySelector('#dpop .dpg')`), 'the "To" picker opens');
    check(await ev(`(() => { const p = document.querySelector('#dpop'); return p.querySelector('.dpy').value === '2025' && !!p.querySelector('.dpd.ref[data-d="2025-12-05"]') && p.querySelector('.dpd[data-d="2025-12-04"]')?.disabled && !p.querySelector('.dpd[data-d="2025-12-06"]').disabled; })()`),
      '#2290: December 2025, the start day marked, the days before disabled ' + await ev(`document.querySelector('#dpop .dph')?.textContent`));
    await shot('p2117-a-to-picker.png');
    await ev(clk('#dpop .dpd[data-d="2025-12-08"]'));
    check(await ready(ev, `document.querySelector('.modal #rk-to').value === '2025-12-08'`), 'a day picked');
    await ev(setv('.modal #rk-from', '2025-12-10'));
    check(await ready(ev, `document.querySelector('.modal #rk-to').value === '2025-12-10'`), '#2290: a later start moves the earlier end along');

    // ---- #2292: an own purpose from the choice
    await ev(setv('.modal #rk-dest', 'Hannover'));
    check(await ev(`[...document.querySelector('.modal #rk-purpose').options].at(-1).value === '__add'`), '#2292: the last entry adds a purpose');
    await ev(setv('.modal #rk-purpose', '__add'));
    check(await ready(ev, `!document.querySelector('.modal .rkpnew').hidden && document.activeElement?.id === 'rk-pnew'`), 'the field right below, focused');
    await ev(`(() => { const x = document.querySelector('.modal #rk-pnew'); x.value = 'Messe'; x.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true, cancelable: true})); return 1; })()`);
    check(await ready(ev, `document.querySelector('.modal #rk-purpose').value === 'Messe' && document.querySelector('.modal .rkpnew').hidden && !!document.querySelector('.modal')`), 'Enter takes it over and chooses it (the dialog stays)');
    check(await ready(ev, `${getJ('/api/office/trips/purposes')}.then(j => j.purposes.some(p => p.name === 'Messe'))`), 'stored as an own purpose');
    await ev(`(() => { document.querySelector('.modal [data-pid]').click(); return 1; })()`);
    await ev(clk('.modal [data-m="save"]'));
    check(await ready(ev, `${getJ('/api/office/trips?year=2025')}.then(j => j.trips.some(t => t.dest === 'Hannover' && t.purpose === 'Messe' && t.date_to === '2025-12-10'))`), 'the trip saved with the own purpose');
    await ready(ev, `!document.querySelector('.modal') && !!document.querySelector('[data-rk="back"]')`);
    check(await ev(`/Messe/.test(document.querySelector('.rkhead').textContent)`), 'the trip head shows the own purpose');
    await ev(clk('[data-rk="back"]'));
    check(await ready(ev, `[...document.querySelectorAll('.rklist .ofcrow')].some(b => /Hannover/.test(b.textContent) && /Messe/.test(b.textContent))`), 'the list shows the own purpose');

    // ---- #2287: the arrow opens the row menu
    const nTrips = async () => (await ev(`${getJ('/api/office/trips?year=2025')}.then(j => j.trips.length)`));
    check(await nTrips() === 3, 'three trips');
    await ev(`(() => { [...document.querySelectorAll('.rklist li')].find(l => /Kiel/.test(l.textContent)).querySelector('[data-rk="rowmore"]').click(); return 1; })()`);
    check(await ready(ev, `[...document.querySelectorAll('#pop .menu-list button')].map(b => b.textContent.trim()).join('|').includes('Delete')`),
      '#2287: the arrow opens the row menu with Delete ' + await ev(`[...document.querySelectorAll('#pop .menu-list button')].map(b => b.textContent.trim()).join('|')`));
    check(await ev(`!!document.querySelector('.rklist li > [data-rk="rowmore"] svg') && !document.querySelector('.rklist .ofcrow [data-rk="rowmore"]')`), 'the arrow is its own button, not inside the row');
    await shot('p2117-a-rowmenu.png');
    await ev(`(() => { [...document.querySelectorAll('#pop .menu-list button')].find(b => b.textContent.trim() === 'Duplicate').click(); return 1; })()`);
    check(await ready(ev, `${getJ('/api/office/trips?year=2025')}.then(j => j.trips.filter(t => t.dest === 'Kiel').length === 2 && j.trips.filter(t => t.dest === 'Kiel').some(t => !t.items.length))`), 'Duplicate: a copy without receipts');
    check(await ready(ev, `!!document.querySelector('.rkhead') && /Kiel/.test(document.querySelector('.rkhead').textContent)`), 'the copy opens');
    await ev(clk('[data-rk="back"]'));
    await ready(ev, `document.querySelectorAll('.rklist .ofcrow').length === 4`);
    await ev(`(() => { [...document.querySelectorAll('.rklist li')].find(l => /Kiel/.test(l.textContent) && !/30/.test(l.textContent)).querySelector('[data-rk="rowmore"]').click(); return 1; })()`);
    await ready(ev, `!!document.querySelector('#pop .menu-list button.danger')`);
    await ev(clk('#pop .menu-list button.danger'));
    check(await ready(ev, `!!document.querySelector('[data-cd="yes"]')`), 'Delete asks first');
    await ev(clk('[data-cd="yes"]'));
    check(await ready(ev, `${getJ('/api/office/trips?year=2025')}.then(j => j.trips.length === 3)`), 'the copy is deleted');
    // CI of 2.307.7: the own toast before its button (an older toast and its Undo can still be there on a slow runner)
    check(await ready(ev, `!document.querySelector('#toast').classList.contains('hidden') && /Deleted/.test(document.querySelector('#toast').textContent) && !!document.querySelector('#toast button:not(.tx)')`), 'the delete toast with undo');
    await ev(clk('#toast button'));
    check(await ready(ev, `${getJ('/api/office/trips?year=2025')}.then(j => j.trips.length === 4)`), 'one undo step brings it back');

    // ---- #2291: the person filter
    check(await ready(ev, `!!document.querySelector('#rk-person')`), '#2291: the person choice (two people travel)');
    check(await ev(`[...document.querySelector('#rk-person').options].map(o => o.textContent).join('|') === 'All people|Alice|Externe Person'`),
      'the people of the office + the free names ' + await ev(`[...document.querySelector('#rk-person').options].map(o => o.textContent).join('|')`));
    await ev(setv('#rk-person', `u${me.id}`));
    check(await ready(ev, `document.querySelectorAll('.rklist .ofcrow').length === 2 && ![...document.querySelectorAll('.rklist .ofcrow')].some(b => /Kiel/.test(b.textContent))`), 'the list: only her trips');
    await ev(clk('[data-rk="view"][data-v="report"]'));
    check(await ready(ev, `document.querySelector('#rk-person')?.value === 'u${me.id}' && !!document.querySelector('.rktab')`, 60), 'the choice stays in the evaluation');
    check(await ev(`/person=u${me.id}/.test(document.querySelector('.ofcbar a[href*="/trips/report"]').getAttribute('href')) && [...document.querySelectorAll('.rkv-rep a[href*="/vma."]')].every(a => /person=u${me.id}/.test(a.getAttribute('href')))`),
      'the CSV and the per diem exports take the person');
    check(await ev(`/100[.,]00/.test(document.querySelector('.rktab tfoot').textContent)`), 'the report sums only her receipts ' + await ev(`document.querySelector('.rktab tfoot')?.textContent`));
    await ev(clk('[data-rk="by"][data-v="purpose"]'));
    check(await ready(ev, `[...document.querySelectorAll('.rktab tbody td:first-child')].map(x => x.textContent).join('|') === 'Job for a client / project'`), '#2292: the evaluation by purpose');
    await ev(setv('#rk-person', ''));
    check(await ready(ev, `[...document.querySelectorAll('.rktab tbody td:first-child')].map(x => x.textContent).sort().join('|') === 'Job for a client / project'`), 'all people again');
    await shot('p2117-a-report.png');
    // the phone
    await ev(clk('[data-rk="view"][data-v="trips"]'));
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await sleep(500);
    check(await ready(ev, `document.querySelectorAll('.rklist [data-rk="rowmore"]').length === 4`), 'the list on a phone');
    check(await ev(`[...document.querySelectorAll('.rklist [data-rk="rowmore"]')].every(b => { const r = b.getBoundingClientRect(); return r.width >= 43 && r.height >= 43; })`), '#2287: the arrow is a 44 px target on a phone');
    check(await ev(noSide), 'nothing sticks out to the side on a phone');
    await shot('p2117-a-phone.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});

    // ---- #2292: the office settings
    await nav(B + '#office/settings');
    check(await ready(ev, `!!document.querySelector('.rkpset input[data-rkp="name"]')`, 80), '#2292: the settings list the own purposes');
    await ev(`(() => { const x = document.querySelector('.rkpset input[data-rkp="name"]'); x.value = 'Fachmesse'; x.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    check(await ready(ev, `${getJ('/api/office/trips/purposes')}.then(j => j.purposes.map(p => p.name).join() === 'Fachmesse')`), 'renamed in place');
    check(await ev(`${getJ('/api/office/trips?year=2025')}.then(j => j.trips.some(t => t.purpose === 'Messe'))`), 'the trip keeps its text');
    await ev(clk('.rkpset [data-rkp="del"]'));
    check(await ready(ev, `${getJ('/api/office/trips/purposes')}.then(j => !j.purposes.length) && !document.querySelector('.rkpset [data-rkp="del"]')`), 'removed');
    check(await ready(ev, `!document.querySelector('#toast').classList.contains('hidden') && /Removed/.test(document.querySelector('#toast').textContent) && !!document.querySelector('#toast button:not(.tx)')`), 'the remove toast with undo');  // CI of 2.307.7: not the rename's Saved toast
    await ev(clk('#toast button'));
    check(await ready(ev, `${getJ('/api/office/trips/purposes')}.then(j => j.purposes.length === 1) && !!document.querySelector('.rkpset [data-rkp="del"]')`), 'one undo step brings it back');
    await ev(`(() => { const x = document.querySelector('#rkp-new'); x.value = 'Workshop'; x.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true, cancelable: true})); return 1; })()`);
    check(await ready(ev, `${getJ('/api/office/trips/purposes')}.then(j => j.purposes.length === 2)`), 'Enter adds one (no submit of the settings form)');
    check(await ev(`location.hash === '#office/settings' && !!document.querySelector('#ofc-set')`), 'still the settings');
    await shot('p2117-a-settings.png');

    // ---- a person without an organisation, travelling alone
    await signIn(ev, 'frida');
    await nav(B + 'static/icon.svg');
    await nav(B + '#office/travel');
    check(await ready(ev, `!!document.querySelector('#rk-year')`, 80), 'freelancer: the travel tab of the personal office');
    await year(ev);
    check(await ready(ev, `document.querySelectorAll('.rklist .ofcrow').length === 1`, 80), 'freelancer: her trip');
    check(await ev(`!document.querySelector('#rk-person')`), '#2291: no person choice when only one person travels');
    check(await ev(`!!document.querySelector('.rklist [data-rk="rowmore"]')`), '#2287: the row menu in the personal office');
    await ev(clk('[data-rk="new"]'));
    await ready(ev, `!!document.querySelector('.modal #rk-purpose')`);
    check(await ev(`[...document.querySelector('.modal #rk-purpose').options].map(o => o.value).join('|') === 'job|acquisition|__add'`), '#2292: the personal office has its own (empty) list');
    await ev(clk('.modal [data-m="close"]'));
  }, false);

  console.log(`p2117_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
