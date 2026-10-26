// 2.330 UI tests, part A (small fixes found while filling staging), own container (start.sh, mode workspaces), Firefox.
// Invented companies, people and figures only. freelancer-matrix: office
// - #3296: Office > Cash flow: the balance in a month card's head counts that month's corrections by hand (like the
//   account balance below); without a correction it is the computed balance as before; the dialog of a correction says so
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const TC = require('./testclock');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2330_a_kleine_fehler_ui', check, shots: 'P2330A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2330A_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients,docs,files';
const MONTH = TC.today().slice(0, 7);
const nextMonth = (() => { const [y, m] = MONTH.split('-').map(Number); return m === 12 ? `${y + 1}-01` : `${y}-${String(m + 1).padStart(2, '0')}`; })();

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  // the person without organisation (personal office, its own admin)
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fu.http < 300, 'a person without organisation ' + fu.http);
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  // money out 1,000 a month, this month a correction in 21,500 (money outside Kalmido); next month none
  const fx = await call(CF, 'POST', '/api/office/fixed-costs', {label: 'Miete Studio', amount: '1000', vat_rate: 0, repeat: 'monthly', start: `${MONTH}-01`});
  check(fx.http === 201, 'a fixed cost ' + fx.http);
  const ad = await call(CF, 'POST', '/api/office/cashflow/adjust', {month: MONTH, dir: 'in', amount: '21500', note: 'Sonstige Einnahme'});
  check(ad.http === 201, 'a correction by hand ' + ad.http);
  const ad2 = await call(CF, 'POST', '/api/office/cashflow/adjust', {month: MONTH, dir: 'out', amount: '500', note: 'Bar bezahlt'});
  check(ad2.http === 201, 'a correction out ' + ad2.http);

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const cardOf = mo => `[...document.querySelectorAll('.rkcfm')].find(x => x.querySelector('[data-month="${mo}"]'))`;
  const balOf = mo => `${cardOf(mo)}?.querySelector('.rkcfbal')`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'frida');
    await nav(B + '#office/cashflow');
    check(await ready(ev, `!!${balOf(MONTH)} && !!${balOf(nextMonth)}`, 80), 'the cash flow shows this and next month');
    // this month: -1,000 computed + 21,500 - 500 by hand = 20,000
    check(await ready(ev, `${balOf(MONTH)}.textContent.trim() === 'Balance ' + ofcMoney(20000)`),
      '#3296: the balance in the head counts the corrections by hand ' + await ev(`${balOf(MONTH)}?.textContent || ''`));
    check(await ev(`!${balOf(MONTH)}.classList.contains('neg') && ${balOf(MONTH)}.title === 'Corrections by hand'`), 'not red any more, the title says why');
    // next month: no correction -> the computed balance as before
    check(await ev(`${balOf(nextMonth)}.textContent.trim() === 'Balance ' + ofcMoney(-1000) && ${balOf(nextMonth)}.classList.contains('neg') && !${balOf(nextMonth)}.title`),
      'without a correction: the computed balance as before ' + await ev(`${balOf(nextMonth)}?.textContent || ''`));
    // the server answer stays the computed one (API, key figures)
    check(await ev(`fetch('/api/office/cashflow?from=${MONTH}&months=3', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => +j.rows[0].balance === -1000 && j.rows[0].manual.in === '21500.00')`),
      'the API keeps the computed balance and the corrections apart');
    await shot('p2330-a-cashflow.png');
    // the dialog of a correction says where it counts
    await ev(`(() => { ${cardOf(MONTH)}.querySelector('[data-cfs="new"]').click(); return 1; })()`);
    check(await ready(ev, `/Counts in the balance of the month and in the account balance/.test(document.querySelector('.modal .shint')?.textContent || '')`),
      'the hint of the dialog: counts in the balance of the month and the account balance');
  }, false);

  console.log(`p2330_a_kleine_fehler_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
