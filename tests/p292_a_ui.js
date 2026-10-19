// 2.92.0 UI tests, part A (#1925: business contracts and insurances in the office), own container (start.sh, mode
// workspaces), Firefox (desktop + phone width). Invented companies, people and figures only.
// - the admin has the tab "Contracts & insurance": grouped by kind, the contribution per month, "Cancel by … · N days left"
//   in red from the lead time on
// - a new contract through the dialog (comma amount, end of term) is saved with its deadline task; editing is one undo step
// - the cash flow's fixed costs show the contributions as read-only rows "From contracts" with a link to the contract
// - on a phone nothing sticks out to the side; a member does not see the tab
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const TC = require('./testclock');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p292_a_ui', check, shots: 'P292A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P292A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients,docs';
const today = TC.today();
const day = n => { const d = new Date(today + 'T12:00:00Z'); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };

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
  const ins = await call(CA, 'POST', '/api/office/agreements', {kind: 'insurance', name: 'Betriebshaftpflicht', provider: 'Beispiel Versicherung AG', cost: 240, per: 'year',
    ends: day(20), notice: 0, renew_months: 12, lead_days: 30});
  check(ins.http === 201 && ins.deadline?.warn, 'an insurance due soon ' + ins.http);

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const api = `(u => fetch(u, {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()))`;
  const noSide = `(() => { const W = document.documentElement.clientWidth; return [...document.querySelectorAll('.office .ofcbody *')].filter(e => e.getClientRects().length && !e.closest('.seg')).every(e => e.getBoundingClientRect().right <= W + 1); })()`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    await nav(B + '#office/agreements');
    check(await ready(ev, `document.querySelectorAll('.agr-li .ofcrow').length === 1`, 80), '#1925: the tab lists the contract');
    check(await ev(`!!document.querySelector('#view .ofrail [data-ofm="agreements"]')`), '#1925: the tab for the admin');  // 2.98.0 (#2180): the office rail
    check(await ev(`(() => { const t = document.querySelector('.agr-li').textContent; return /Betriebshaftpflicht/.test(t) && /20\\.00/.test(t) && /Cancel by/.test(t) && /20 days left/.test(t); })()`),
      '#1925: name, contribution per month, the last day to cancel ' + await ev(`document.querySelector('.agr-li')?.textContent`));
    check(await ev(`!!document.querySelector('.agr-li .agr-late')`), '#1925: within the lead time in red');
    // a new contract through the dialog
    await ev(`(() => { document.querySelector('[data-agr="new"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal #agr-name')`), '#1925: the dialog');
    await ev(`(() => { const m = document.querySelector('.modal'); m.querySelector('#agr-kind').value = 'leasing'; m.querySelector('#agr-name').value = 'Kamera-Leasing';
      m.querySelector('#agr-cost').value = '49,90'; m.querySelector('#agr-per').value = 'month'; m.querySelector('#agr-ends').value = '${day(200)}'; m.querySelector('#agr-notice').value = '1';
      m.querySelector('#agr-renew').value = '0'; m.querySelector('[data-m="save"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.modal') && document.querySelectorAll('.agr-li .ofcrow').length === 2`), '#1925: the new contract is in the list');
    check(await ready(ev, `${api}('/api/office/agreements').then(j => j.items.some(a => a.name === 'Kamera-Leasing' && a.kind === 'leasing' && a.cost === '49.90' && a.renew_months === 0 && a.task && a.ends === '${day(200)}'))`),
      '#1925: saved with comma amount, end of term and its deadline task');
    check(await ev(`[...document.querySelectorAll('.fcicat')].map(h => h.textContent).join('|') === 'Insurances|Leasing'`), '#1925: grouped by kind');
    // edit + undo
    await ev(`(() => { [...document.querySelectorAll('.agr-li .ofcrow')].find(b => /Kamera/.test(b.textContent)).click(); return 1; })()`);
    check(await ready(ev, `document.querySelector('.modal #agr-name')?.value === 'Kamera-Leasing'`), '#1925: the editor with the values');
    await ev(`(() => { const m = document.querySelector('.modal'); m.querySelector('#agr-name').value = 'Licht-Leasing'; m.querySelector('[data-m="save"]').click(); return 1; })()`);
    check(await ready(ev, `${api}('/api/office/agreements').then(j => j.items.some(a => a.name === 'Licht-Leasing'))`), '#1925: renamed');
    await ev(`(() => { histStep('undo'); return 1; })()`);
    check(await ready(ev, `${api}('/api/office/agreements').then(j => j.items.some(a => a.name === 'Kamera-Leasing') && !j.items.some(a => a.name === 'Licht-Leasing'))`), '#1925: the undo takes it back');
    await shot('p292-a-list.png');
    // phone width
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await sleep(400);
    check(await ev(noSide), '#1925: on a phone the list stays inside the screen');
    await ev(`(() => { document.querySelector('.agr-li .ofcrow').click(); return 1; })()`);
    await ready(ev, `!!document.querySelector('.modal #agr-name')`);
    await shot('p292-a-editor-phone.png');
    check(await ev(`(() => { const W = document.documentElement.clientWidth; return [...document.querySelectorAll('.modal .card *')].filter(e => e.getClientRects().length).every(e => e.getBoundingClientRect().right <= W + 1); })()`),
      '#1925: on a phone the editor stays inside the screen');
    await ev(`(() => { document.querySelector('.modal [data-m="close"]').click(); return 1; })()`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    // the fixed costs in the cash flow
    await nav(B + '#office/cashflow');
    check(await ready(ev, `document.querySelectorAll('.agr-fixed li').length === 2`, 80), '#1925: the contributions as rows "From contracts"');
    check(await ev(`[...document.querySelectorAll('.fcicat')].some(h => h.textContent === 'From contracts') && !!document.querySelector('.agr-fixed a[href^="#office/agreements/"]')`), '#1925: read-only, with a link to the contract');
    await shot('p292-a-fixed.png');
    // member
    await signIn(ev, 'bob');
    await nav(B + 'static/icon.svg');
    await nav(B + '#office/offers');
    check(await ready(ev, `!!document.querySelector('#view .ofrail [data-ofm="offers"]')`, 80), 'the office (member)');  // 2.98.0 (#2180): the office rail
    check(await ev(`!document.querySelector('#view .ofrail [data-ofm="agreements"]')`), '#1925: a member does not see the tab');  // 2.98.0 (#2180): the office rail
  }, false);

  console.log(`p292_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
