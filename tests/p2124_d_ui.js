// 2.124.0 UI tests, part D (#2342, office: the account balance from the bank reconciliation), own container (start.sh, mode
// workspaces), Firefox. Invented companies, accounts and figures only. freelancer-matrix: office
// - a person without organisation (personal office): without balances the cash flow has no bank box; the CSV import dialog
//   offers the balance column (guessed) and the account name, its preview names the balance according to the bank; after
//   the import the cash flow shows "Account balance according to the bank on ..." with "Use as starting balance"; a tap
//   takes it over as the start balance (undo in the toast removes it again)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const TC = require('./testclock');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const {undoToast} = require('./ff');
const firefox = require('./ff')({tag: 'p2124_d_ui', check, shots: 'P2124D_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2124D_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients,docs,files';
const T = TC.today();
const P0 = (() => { const [y, m] = T.slice(0, 7).split('-').map(Number); const py = m === 1 ? y - 1 : y, pm = m === 1 ? 12 : m - 1; return `${py}-${String(pm).padStart(2, '0')}`; })();
const DAY = `${P0}-20`, DE = `20.${P0.slice(5, 7)}.${P0.slice(0, 4)}`, DE19 = `19.${P0.slice(5, 7)}.${P0.slice(0, 4)}`;
const CSV = `Buchungstag;Name;Verwendungszweck;Betrag;Saldo\n${DE};Laden Beispiel;Einkauf;-10,00;1.240,00\n${DE19};Kunde Beispiel;Zahlung;250,00;1.250,00\n`;  // newest first

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  // the person without organisation (tests/freelancer_fixture.py does the same in Python)
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fu.http < 300, 'a person without organisation ' + fu.http);
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(((await call(CF, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'frida is in no organisation');

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const tab = h => `(() => { location.hash = '${h}'; return 1; })()`;
  const startIs = cond => `fetch('/api/office/cashflow/start', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => ${cond})`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});  // a phone first
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'frida');
    // before: no bank box
    await nav(B + '#office/cashflow');
    check(await ready(ev, `!!document.querySelector('.rkcfm .rkcftab')`, 80), 'the cash flow is shown');
    check(await ev(`!document.querySelector('.cfb-box, .cfb-row')`), 'without balances: no bank box, no bank rows');
    // the CSV import dialog: balance column guessed, account name, the preview names the balance
    await ev(tab('#office/bank'));
    check(await ready(ev, `typeof bnkImpModal === 'function' && !!document.querySelector('[data-bnk="imp"]')`, 80), 'the bank tab');
    await ev(`(() => { bnkImpModal(${JSON.stringify(CSV)}, 'konto.csv'); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal #bi-bal')`, 60), 'the mapping offers the balance column');
    check(await ev(`document.querySelector('#bi-bal').value === '4' && document.querySelector('#bi-acc').value === '' && document.querySelector('#bi-accname').value === 'Main account'`),
      'balance column guessed, no own account column, the name "Main account" ' + await ev(`[document.querySelector('#bi-bal')?.value, document.querySelector('#bi-acc')?.value, document.querySelector('#bi-accname')?.value].join('|')`));
    await ev(`(() => { document.querySelector('#bi-accname').value = 'Geschäftskonto'; document.querySelector('.modal [data-bi="next"]').click(); return 1; })()`);
    check(await ready(ev, `/Account balance according to the bank on .+: /.test(document.querySelector('.modal .cfb-prev')?.textContent || '')`, 60),
      'the preview names the balance according to the bank ' + await ev(`document.querySelector('.modal .cfb-prev')?.textContent || ''`));
    check(await ev(`(document.querySelector('.modal .cfb-prev').textContent).includes(ofcMoney(1240))`), 'the balance of the last booking (newest first)');
    await shot('p2124-d-preview.png');
    await ev(`(() => { document.querySelector('.modal [data-bi="next"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.itc-dlg [data-cd="yes"]')`, 40), '2.356.0 B (#2934): the import names its target first');
    await ev(`(() => { document.querySelector('.itc-dlg [data-cd="yes"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.modal #bi-bal') && !document.querySelector('.modal .cfb-prev')`, 60), 'imported');
    const imp = await call(CF, 'GET', '/api/office/bank/imports');
    check((imp.items || []).length === 1, 'one import');
    // the cash flow: the balance according to the bank, take it over as the start
    await ev(`(() => { RKF.data = null; location.hash = '#office/cashflow'; return 1; })()`);
    check(await ready(ev, `/Account balance according to the bank on .+: /.test(document.querySelector('.cfb-box')?.textContent || '')`, 80),
      'the cash flow shows the balance according to the bank ' + await ev(`document.querySelector('.cfb-box')?.textContent.replace(/\\s+/g, ' ') || ''`));
    check(await ev(`document.querySelector('.cfb-box').textContent.includes(ofcMoney(1240)) && /from the bank reconciliation/.test(document.querySelector('.cfb-box').textContent)`), 'amount and its mark');
    check(await ev(`!!document.querySelector('.cfb-box [data-cfb="start"]')`), 'no start yet: "Use as starting balance"');
    await shot('p2124-d-cashflow.png');
    await ev(`(() => { document.querySelector('.cfb-box [data-cfb="start"]').click(); return 1; })()`);
    check(await ready(ev, startIs(`j.start && j.start.amount === '1240.00' && j.start.day === '${DAY}'`), 60), 'taken over as the start balance');
    check(await ready(ev, `!!document.querySelector('.cfb-box') && !document.querySelector('.cfb-box [data-cfb="start"]') && /Difference to the computed balance/.test(document.querySelector('.cfb-box').textContent)`, 60),
      'with a start: the difference, no button any more');
    check(await ready(ev, `!!document.querySelector('.rkcfm .cfs-acc')`, 40), 'the account rows of #2341 appear');
    await undoToast(ev, 'Saved');  // 2.312.0 A (#3283)
    check(await ready(ev, startIs('j.start === null'), 60), 'the undo removes the start again');
    check(await ready(ev, `!!document.querySelector('.cfb-box [data-cfb="start"]')`, 60), 'the suggestion is back');
  }, false);

  console.log(`p2124_d_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
