// 2.591.0 UI tests, part A (#4908 #4889: office lists and cash flow). Own container (start.sh), Firefox, invented data only,
// a person without organisation (the same client code for everyone).
// kalmido-suite: fresh
// freelancer-matrix: office
// - #4908 arrows: a row that opens a view (letters list) ends in the arrow to the right (icon right); a row that unfolds in place
//   (aria-expanded) keeps the arrow down, turning when open
// - #4889 cash flow: a month with a bank balance folds "Real balance (by hand)" behind the link "Enter balance by hand" (with the
//   hint); a value by hand keeps the row open; a month without a bank balance as before; "Use as real balance" only for a
//   balance of the last day of the month; the link opens the row
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2591_a_ui', check, shots: 'P2591A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients,docs,files';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fu.http < 300, 'a person without organisation ' + fu.http);
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(((await call(CF, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'frida is in no organisation');
  const lt = await call(CF, 'POST', '/api/office/letters', {rcpt_name: 'Amt Beispielstadt', subject: 'Anfrage', body: 'Guten Tag'});
  check(lt.http === 201, 'a letter draft ' + lt.http);
  const fx = await call(CF, 'POST', '/api/office/fixed-costs', {label: 'Miete Büro', amount: '100', vat_rate: 0, repeat: 'monthly', start: `${new Date().toISOString().slice(0, 7)}-01`});
  check(fx.http === 201, 'a fixed cost ' + fx.http);

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  // the path of the arrow icon at the end of a node: chev = down, right = to the right
  const arrow = sel => `(() => { const s = document.querySelector('${sel}')?.querySelector(':scope > svg:last-child path'); return s ? s.getAttribute('d') : ''; })()`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'frida');
    // ================= #4908: arrows
    await nav(B + '#office/letters');
    check(await ready(ev, `!!document.querySelector('.lt-list [data-lt="open"]')`, 80), 'the letters list shows the letter');
    check(await ev(`${arrow('.lt-list [data-lt="open"]')} === P.right.match(/d="([^"]+)"/)[1]`), '#4908: a row that opens a view ends in the arrow to the right');
    // a row that unfolds in place (aria-expanded): the arrow down, turning when open
    const mk = `(() => { document.querySelectorAll('.t4908').forEach(x => x.remove()); const d = document.createElement('div'); d.className = 't4908';
      d.innerHTML = '<button type="button" class="ofcrow" id="t4908a" aria-expanded="false"><span class="ofcn"><b>Auf</b></span>' + ic('chev', 's') + '</button><button type="button" class="ofcrow" id="t4908b" aria-expanded="true"><span class="ofcn"><b>Offen</b></span>' + ic('chev', 's') + '</button>';
      document.querySelector('#view').appendChild(d); return 1; })()`;
    await ev(mk);
    const chevD = `P.chev.match(/d="([^"]+)"/)[1]`;
    check(await ev(`${arrow('#t4908a')} === ${chevD} && getComputedStyle(document.querySelector('#t4908a > svg')).transform === 'none'`), '#4908: an unfolding row keeps the arrow down');
    check(await ev(`getComputedStyle(document.querySelector('#t4908b > svg')).transform !== 'none'`), '#4908: it turns when open');
    check(await ev(`!document.querySelector('.lt-list .ofcrow[aria-expanded]') && ![...document.querySelectorAll('.lt-list .ofcrow > svg:last-child path')].some(p => p.getAttribute('d') === ${chevD})`), '#4908: no opening row of the list keeps a down arrow');
    await shot('p2591-a-arrows.png');
    // ================= #4889: the real balance row
    await nav(B + '#office/cashflow');
    check(await ready(ev, `typeof cfs_accRows === 'function' && !!document.querySelector('.rkcfm.cur')`, 80), 'the cash flow is shown');
    const rows = r => `(() => { const t = document.createElement('table'); t.innerHTML = '<tbody>' + cfs_accRows(${JSON.stringify(r)}) + '</tbody>'; return t; })()`;
    const base = {month: '2026-05', account: 100, real: null, diff: null, bank: {amount: 1234, day: '2026-05-31', diff: 0}};
    check(await ev(`(() => { const t = ${rows(base)}; return !t.querySelector('.cfs-real') && !t.querySelector('#cfs-real-2026-05') && /Enter balance by hand/.test(t.querySelector('[data-cfs="hand"]')?.textContent || '') && /Only needed for the month end without a bank statement/.test(t.textContent); })()`),
      '#4889: with a bank balance the by-hand row is folded behind the link, with the hint');
    check(await ev(`(() => { const t = ${rows({...base, real: 1200, diff: 5})}; return !!t.querySelector('.cfs-real input') && !t.querySelector('[data-cfs="hand"]'); })()`), '#4889: a value by hand keeps the row open');
    check(await ev(`(() => { const t = ${rows({...base, bank: null})}; return !!t.querySelector('.cfs-real input') && !t.querySelector('[data-cfs="hand"]'); })()`), '#4889: without a bank balance everything as before');
    check(await ev(`(() => { const r = ${JSON.stringify(base)}; return cfb_realBar(r).includes('data-cfb="real"') && cfb_realBar({...r, bank: {...r.bank, day: '2026-05-05'}}) === ''; })()`), '#4889: "Use as real balance" only for the last day of the month');
    // the live page: the link in a card opens the row (a month of the page with a bank balance is set by the data)
    await ev(`(() => { const m = RKF.data.rows[0]; m.bank = {amount: 500, day: m.month + '-28', diff: 0}; if (m.account == null) m.account = 0; m.real = null; CFS.hand.clear(); ofcDraw(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('[data-cfs="hand"]') && !document.querySelector('.cfs-real')`, 40), '#4889: the card shows the link, not the row');
    await ev(`(() => { document.querySelector('[data-cfs="hand"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.cfs-real input') && !document.querySelector('[data-cfs="hand"]')`, 40), '#4889: the link opens the row');
    await shot('p2591-a-cashflow.png');
  }, false);

  console.log(`p2591_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
