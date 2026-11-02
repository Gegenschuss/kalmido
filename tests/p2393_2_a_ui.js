// kalmido-suite: fresh
// 2.393.2 UI test, part A (#3374 the card "Flow" of a project page). Own container (start.sh), Firefox 1280 px.
// - the card is on the project page: three figures, the cumulative flow as a picture with a label and as a table (one row
//   per day), the bug trend; 30 / 90 days switch (pressed state, the table grows to 90 rows, the choice stays)
// freelancer-matrix: lists (alice has no organisation: her own project). P2393_2_A_UI_NOSTART=1 = the server runs.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2393_2_a_ui', check, shots: 'P2393_2_A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2393_2_A_UI_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const P = (await call('POST', '/api/lists', {name: 'Flow page', kind: 'project'})).id;
  const S1 = (await call('POST', '/api/sections', {list_id: P, name: 'To do'})).id;
  const S2 = (await call('POST', '/api/sections', {list_id: P, name: 'In progress'})).id;
  await call('POST', '/api/tasks', {title: 'Waiting task', list_id: P, section_id: S1});
  await call('POST', '/api/tasks', {title: 'Running task', list_id: P, section_id: S2});
  const T = (await call('POST', '/api/tasks', {title: 'Finished task', list_id: P, section_id: S2})).id;
  check((await call('POST', `/api/tasks/${T}/complete`, {})).http === 200, 'setup: a task completed');
  const j = await call('GET', `/api/lists/${P}/flow`);
  check(j.http === 200 && j.lead_time.n === 1 && j.cycle_time.n === 1, '#3374: setup: the flow answers ' + JSON.stringify(j).slice(0, 200));

  const ready = async (ev, expr, n = 80) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.pov', '[${P}]'); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    await nav(B + '#l/' + P);
    check(await ready(ev, `!!document.querySelector('#pov-flow .fxkpis')`), '#3374: the card "Flow" with its figures is on the project page');
    const k = await ev(`[...document.querySelectorAll('#pov-flow .fxk')].map(x => [x.querySelector('.fxkt').textContent, x.querySelector('.fxkv').textContent])`);
    check(k.length === 3 && k[0][0] === 'Lead time, median' && k[2][0] === 'Cycle time, median' && /days/.test(k[0][1]) && /days/.test(k[2][1]),
      '#3374: lead time median / 85 % and cycle time median, in days ' + JSON.stringify(k));
    const svg = await ev(`(() => { const s = document.querySelector('#pov-flow svg.flwcfd'); return s ? {role: s.getAttribute('role'), label: s.getAttribute('aria-label'), areas: s.querySelectorAll('polygon').length, h: s.getBoundingClientRect().height} : null; })()`);
    check(svg && svg.role === 'img' && /Cumulative flow: 2 open, 1 done/.test(svg.label) && svg.areas === 3 && svg.h > 40,
      '#3374: the cumulative flow is a picture with a label (done + two columns) ' + JSON.stringify(svg));
    const rows = () => ev(`document.querySelectorAll('#pov-flow .msbtab')[0]?.querySelectorAll('tbody tr').length || 0`);
    check(await rows() === 30, '#3374: "Show as table": one row per day (30)');
    const head = await ev(`[...document.querySelectorAll('#pov-flow .msbtab')[0].querySelectorAll('thead th')].map(x => x.textContent)`);
    check(JSON.stringify(head) === JSON.stringify(['Day', 'To do', 'In progress', 'Completed']), '#3374: the table names the columns and done ' + JSON.stringify(head));
    check(await ev(`/No bugs in this period/.test(document.querySelector('#pov-flow').textContent)`), '#3374: bug trend without bugs: a short note');
    check(await ev(`document.querySelector('#pov-flow [data-flw-days="30"]').getAttribute('aria-pressed') === 'true'`), '#3374: 30 days is pressed');
    if (shot) await shot('flow-30.png');
    await ev(`(document.querySelector('#pov-flow [data-flw-days="90"]').click(), 1)`);
    check(await ready(ev, `document.querySelectorAll('#pov-flow .msbtab')[0]?.querySelectorAll('tbody tr').length === 90`), '#3374: 90 days: 90 rows');
    check(await ev(`document.querySelector('#pov-flow [data-flw-days="90"]').getAttribute('aria-pressed') === 'true'`), '#3374: 90 days is pressed');
    await nav(B + '#l/' + P); await nav(B + '#l/' + P);
    check(await ready(ev, `document.querySelectorAll('#pov-flow .msbtab')[0]?.querySelectorAll('tbody tr').length === 90`), '#3374: the period stays after reloading');
  });

  console.log(`p2393_2_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
