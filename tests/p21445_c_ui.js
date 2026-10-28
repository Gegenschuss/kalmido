// 2.144.5 UI tests, part C (#2021): series names without placeholders, a missed notice period of a subscription. Own container
// (start.sh), Firefox (desktop + phone width). Invented companies and figures only.
// - a series without own title shows in the invoice list as the template's project title without "{month}"; the sheet
//   "Repeat as series" proposes the name without placeholders
// - Subscriptions & tools: a subscription whose last day to cancel has passed says "Notice period missed, next chance <date>"
//   (not the past date), a reachable one still "cancel by"; on a phone nothing sticks out to the side
// (P21445C_NOSTART=1: a running server, no start.sh)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const TC = require('./testclock');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21445_c_ui', check, shots: 'P21445C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P21445C_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients';
const today = TC.today();
const addDays = (iso, n) => { const d = new Date(iso + 'T12:00:00Z'); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
const yearBack = iso => `${+iso.slice(0, 4) - 1}${iso.slice(4, 8)}${iso.slice(5) === '02-29' ? '28' : iso.slice(8)}`;

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
  const cl = await call(CA, 'POST', '/api/clients', {name: 'Kunde Eins GmbH', street: 'Marktstraße 5', zip: '50667', city: 'Köln', country: 'DE'});
  const inv = await call(CA, 'POST', '/api/office/docs', {kind: 'invoice', lang: 'de', client_id: cl.id, project_title: 'Wartung {month}', service_from: '2026-01-01',
    items: [{title: 'Betreuung', qty: 1, rate: 500}]});
  check(inv.http === 201, 'a template invoice ' + inv.http);
  const ser = await call(CA, 'POST', '/api/office/series', {template_id: inv.id, every: 'monthly', start: '2027-01-31'});
  check(ser.http === 201 && ser.title === 'Wartung', 'a series without own title ' + ser.http + ' ' + ser.title);
  const inv2 = await call(CA, 'POST', '/api/office/docs', {kind: 'invoice', lang: 'de', client_id: cl.id, project_title: 'Pflege {quarter}', service_from: '2026-01-01',
    items: [{title: 'Pflege', qty: 1, rate: 100}]});
  const fx = b => call(CA, 'POST', '/api/office/fixed-costs', {start: today, repeat: 'yearly', vat_rate: 0, sub: 1, ...b});
  const ren = addDays(today, 10);
  const m = await fx({label: 'Domain Missed', amount: 120, start: yearBack(ren), notice_days: 30});
  check(m.http === 201 && m.cancel_missed === 1 && m.cancel_next, 'a subscription with a missed notice ' + JSON.stringify([m.http, m.cancel_missed, m.cancel_next]));
  await fx({label: 'Tool Reachable', amount: 10, start: yearBack(addDays(today, 60)), notice_days: 30});

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const noSide = `(() => { const W = document.documentElement.clientWidth; return [...document.querySelectorAll('.office .ofcbody *')].filter(e => e.getClientRects().length && !e.closest('.seg')).every(e => e.getBoundingClientRect().right <= W + 1); })()`;
  const rowText = label => `([...document.querySelectorAll('.abo-list .abo-row')].find(r => /${label}/.test(r.textContent))?.textContent || '').replace(/\\s+/g, ' ')`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    // ================= #2021 (a) the sheet proposes the name without placeholders
    await nav(B + `#office/offers/${inv2.id}`);
    check(await ready(ev, `!!document.querySelector('[data-rin="new"]')`, 80), 'the editor offers "Repeat as series"');
    await ev(`(() => { document.querySelector('[data-rin="new"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal #ofd-rin-title')`), 'the series sheet');
    const prop = await ev(`document.querySelector('.modal #ofd-rin-title').value`);
    check(prop === 'Pflege', 'the proposed name has no placeholder ' + JSON.stringify(prop));
    await ev(`(() => { const m = document.querySelector('.modal'); (m.querySelector('[data-m="cancel"]') || m.querySelector('.mclose') || {click() {}}).click(); return 1; })()`);
    await ev(`(() => { document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); return 1; })()`);
    // ================= #2021 (a) the invoice list's series section
    await nav(B + '#office/invoices');  // 2.380.0 (#3409): the invoices' own area
    await ready(ev, `!!document.querySelector('[data-ofd="kind"][data-kind="invoice"]')`, 80);
    await ev(`(() => { document.querySelector('[data-ofd="kind"][data-kind="invoice"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.rin-sec .rin-it')`, 60), 'the invoice list shows the series');
    await ev(`(() => { const d = document.querySelector('.rin-sec'); if (d) d.open = true; return 1; })()`);
    const t = await ev(`document.querySelector('.rin-sec .rin-it b')?.textContent || ''`);
    check(/^Wartung\b/.test(t) && !/\{month\}/.test(t), 'the series row is named without the placeholder ' + JSON.stringify(t));
    // ================= #2021 (b) a missed notice period
    await nav(B + '#office/subs');
    check(await ready(ev, `document.querySelectorAll('.abo-list .abo-row').length === 2`, 80), 'the tab lists both subscriptions');
    const mt = await ev(rowText('Domain Missed'));
    check(/Notice period missed, next chance/.test(mt) && !/cancel by/.test(mt), 'the missed one shows the next chance ' + JSON.stringify(mt));
    check(await ev(`!!document.querySelector('.abo-list .abo-cancel.missed')`), 'the missed one is marked');
    check(/cancel by/.test(await ev(rowText('Tool Reachable'))), 'a reachable one still says "cancel by"');
    const order = await ev(`[...document.querySelectorAll('.abo-list .abo-row b')].map(b => b.textContent.trim())`);
    check(/Tool Reachable/.test(order[0] || '') && /Domain Missed/.test(order[1] || ''), 'the missed one sorts by its next chance ' + JSON.stringify(order));
    await shot('p21445-c-subs.png');
    // phone
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + 'static/icon.svg');
    await nav(B + '#office/subs');
    check(await ready(ev, `document.querySelectorAll('.abo-list .abo-row').length === 2`, 80), 'phone: the list');
    check(await ev(noSide), 'phone: nothing sticks out to the side');
    await shot('p21445-c-subs-phone.png');
  }, false);

  console.log(`p21445_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
