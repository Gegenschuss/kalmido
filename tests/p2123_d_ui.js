// 2.123.0 UI tests, part D (#2341, office: the account balance of the cash flow), own container (start.sh, mode workspaces),
// Firefox. Invented companies, people and figures only. freelancer-matrix: office
// - a person without organisation (personal office): before a start balance the month cards have no account rows; the start
//   balance in the office settings (own section, saved on change, undo in the toast); the cash flow then shows the account
//   balance at the end of the month (computed); a correction by hand ("Other money in", marked "by hand") counts in it and
//   the undo takes it out again; the real balance entered in the card shows the difference
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const TC = require('./testclock');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const {undoToast} = require('./ff');
const firefox = require('./ff')({tag: 'p2123_d_ui', check, shots: 'P2123D_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2123D_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients,docs,files';
const MONTH = TC.today().slice(0, 7);

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
  const fx = await call(CF, 'POST', '/api/office/fixed-costs', {label: 'Miete Büro', amount: '100', vat_rate: 0, repeat: 'monthly', start: `${MONTH}-01`});
  check(fx.http === 201, 'a fixed cost ' + fx.http);

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const tab = h => `(() => { location.hash = '${h}'; return 1; })()`;
  const card = `document.querySelector('.rkcfm.cur')`;
  const accIs = n => `(${card}?.querySelector('.cfs-acc td')?.textContent.trim() || '') === ofcMoney(${n})`;
  const setVal = (sel, v) => `(() => { const x = document.querySelector('${sel}'); x.value = ${JSON.stringify(v)}; x.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});  // a phone first
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'frida');
    // before: no account rows
    await nav(B + '#office/cashflow');
    check(await ready(ev, `!!${card}?.querySelector('.rkcftab')`, 80), 'the cash flow is shown');
    check(await ev(`!document.querySelector('.cfs-acc, .cfs-real, .cfs-adj') && !!document.querySelector('[data-cfs="new"]')`), 'without a start balance: no account rows, only "+ Correction"');
    // the start balance in the office settings
    await ev(tab('#office/settings'));
    check(await ready(ev, `!!document.querySelector('.cfsset #cfs-amount-set')`, 80), 'the office settings have the section "Cash flow" with the start balance');
    check(await ev(`!!document.querySelector('.cfsset[data-fg-skip]') && !!document.querySelector('.cfsset #cfs-day')`), 'own section (not part of the settings form), with a reference date');
    check(await ev(`/^\\d{4}-\\d{2}-\\d{2}$/.test(document.querySelector('#cfs-day').value)`), 'the reference date is filled in (today)');
    await ev(setVal('#cfs-day', `${MONTH}-01`));  // without an amount nothing is saved yet
    check(await ev(`fetch('/api/office/cashflow/start', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => j.start === null)`), 'a date alone saves nothing');
    await ev(setVal('#cfs-amount-set', '1000'));
    check(await ready(ev, `fetch('/api/office/cashflow/start', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => j.start && j.start.amount === '1000.00' && j.start.day === '${MONTH}-01')`),
      'saved on change with its reference date');
    check(await ready(ev, `/Undo/.test(document.querySelector('#toast')?.textContent || '')`), 'the toast offers the undo');
    await shot('p2123-d-settings.png');
    // the cash flow: the account at the end of the month (1000 - 100)
    await ev(tab('#office/cashflow'));
    check(await ready(ev, accIs(900), 80), 'the account balance at the end of the month ' + await ev(`${card}?.querySelector('.cfs-acc')?.textContent || ''`));
    check(await ev(`/computed/.test(${card}.querySelector('.cfs-acc').textContent) && !!${card}.querySelector('.cfs-real input')`), 'marked computed, a field for the real balance');
    // a correction by hand, then its undo
    await ev(`(() => { ${card}.querySelector('[data-cfs="new"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal #cfs-amount')`), 'the dialog "New correction"');
    await ev(`(() => { const m = document.querySelector('.modal'); m.querySelector('#cfs-dir').value = 'in'; m.querySelector('#cfs-amount').value = '250'; m.querySelector('#cfs-note').value = 'Barzahlung Markt'; m.querySelector('[data-m="save"]').click(); return 1; })()`);
    check(await ready(ev, `${accIs(1150)} && [...${card}.querySelectorAll('.cfs-adj li')].some(li => /Other money in/.test(li.textContent) && /by hand/.test(li.textContent) && /Barzahlung Markt/.test(li.textContent))`, 60),
      'the correction is listed, marked "by hand", and counts in the account ' + await ev(`${card}?.textContent.replace(/\\s+/g, ' ').slice(0, 300) || ''`));
    check(await ev(`${card}.querySelector('[data-k="${MONTH}|out|actual"]')?.textContent.trim() === ofcMoney(100)`), 'the computed values stay as they are (money out 100)');
    await shot('p2123-d-correction.png');
    await undoToast(ev, 'Added');  // 2.312.0 A (#3283)
    check(await ready(ev, `${accIs(900)} && !${card}.querySelector('.cfs-adj')`, 60), 'the undo takes the correction out again');
    check(await ready(ev, `fetch('/api/office/cashflow?from=${MONTH}&months=3', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => !j.adjust)`), 'the server has no correction any more');
    // the real balance at the end of the month -> the difference
    await ev(setVal(`#cfs-real-${MONTH}`, '880'));
    check(await ready(ev, `!!${card}?.querySelector('.cfs-diff td') && ${card}.querySelector('.cfs-diff td').textContent.trim() === ofcMoney(-20)`, 60),
      'the difference real - computed ' + await ev(`${card}?.querySelector('.cfs-diff')?.textContent || ''`));
    check(await ev(`/by hand/.test(${card}.querySelector('.cfs-real').textContent)`), 'the real balance is marked "by hand"');
    await shot('p2123-d-cashflow.png');
  }, false);

  console.log(`p2123_d_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
