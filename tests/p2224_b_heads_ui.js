// 2.224.0 part B UI tests (#2816), own container (start.sh), Firefox. Invented people only.
// One heading per page: an office page's big heading (#top h1) is the page's name, no small .ofpt below it, "Office" stays
// above the panel; the country card (.ocf-choose) only on the page the office opens with, elsewhere one slim line whose
// button leads there; Tables: one heading, "New table" only in the head (not in the panel); Pipeline: one "New inquiry"
// button in the toolbar. Computer and phone width; the person without an organisation (own admin, P4) is the main person.
// P2224B_NOSTART=1 = the server already runs.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2224_b_heads_ui', check, shots: 'P2224B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2224B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => {
  for (let i = 0; ; i++) {
    const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined});
    if (r.status === 429 && i < 8) { await sleep(500 * (i + 1)); continue; }
    const j = await r.json().catch(() => ({})); return {...j, http: r.status};
  }
};
const FEAT = 'cal,comments,collab,contacts,office,clients,sheets';


(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'POST', '/api/users', {username: 'dora', display_name: 'Dora Solo', password: 'password123', email: 'dora@example.com'});
  const CD = await login('dora');
  await call(CD, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(!((await call(CD, 'GET', '/api/state')).me.workspaces || []).length, 'P4: dora has no organisation');
  const os = await call(CD, 'GET', '/api/office/settings');
  check(os.http === 200 && os.role === 'admin' && os.personal, 'P4: dora is the admin of her own new office');

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const h1 = `(document.querySelector('#top h1')?.textContent || '').trim()`;
  const cur = `(document.querySelector('#side [data-ofm][aria-current="page"] .n, #side [data-ofm][aria-current="page"]')?.textContent || '').trim()`;

  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'dora', password: 'password123'})}).then(r => r.status)`);
    // ---- the page the office opens with: the card, the page's name in the head, one new button
    await nav(B + '#office/pipeline');
    check(await ready(ev, `typeof OFC === 'object' && !!OFC.info && !!document.querySelector('.ocf-choose #ocf-ch')`, 80), '#2816: the country card on the first page of the office');
    check(await ev(`!document.querySelector('.ocf-slim')`), '#2816: no slim line there');
    check(await ev(`${h1} === 'Pipeline' && !document.querySelector('#view .ofpt')`), '#2816: the head names the page, no small heading ' + await ev(h1));
    check(await ev(`document.querySelector('#side h2.sbbpt')?.textContent === 'Office'`), '#2816: "Office" stays above the panel');
    check(await ready(ev, `!!document.querySelector('.ofcbar [data-pp="new"]')`, 60), '#2816: the pipeline loads');
    check(await ev(`document.querySelectorAll('.ofcbar [data-pp="new"]').length === 1 && !document.querySelector('[data-pp="newlead"]') && !!document.querySelector('.ofcbar [data-pp="new"].pri')`), '#2816: one "New inquiry" button in the toolbar, the accent one');
    await shot('p2224-b-pipeline.png');
    // ---- another page: one slim line, the page's name in the head
    await nav(B + '#office/bank');
    check(await ready(ev, `${h1} === 'Bank' && !!document.querySelector('.ocf-slim')`, 80), '#2816: Bank: the head says Bank, the card is a slim line ' + await ev(h1));
    check(await ev(`!document.querySelector('#ocf-ch') && !document.querySelector('#view .ofpt') && ${h1} === ${cur}`), '#2816: no card, no small heading, the head = the marked point');
    await shot('p2224-b-bank.png');
    await ev(`(() => { document.querySelector('.ocf-slim [data-go]').click(); return 1; })()`);
    check(await ready(ev, `location.hash === '#office/pipeline' && !!document.querySelector('.ocf-choose #ocf-ch')`, 60), '#2816: "Choose country" leads to the card');
    await nav(B + '#office/settings');
    check(await ready(ev, `${h1} === 'Settings' && !!document.querySelector('.ocf-slim')`, 80), '#2816: Settings: the name, the slim line');
    // ---- Tables: one heading, one new button
    await nav(B + '#sheets');
    check(await ready(ev, `!!document.querySelector('.shvov [data-shv="new"]')`, 80), '#2816: the tables overview');
    check(await ev(`${h1} === 'Tables' && !document.querySelector('.shvh')`), '#2816: Tables: one heading ' + await ev(h1));
    check(await ev(`document.querySelectorAll('[data-shv="new"]').length === 1 && !document.querySelector('[data-act="sbb-shnew"]')`), '#2816: "New table" only in the head');
    await shot('p2224-b-tables.png');
    // ---- phone: the start list keeps the card, the tables keep one heading
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 402, height: 874}});
    await nav(B + '#office/start');
    check(await ready(ev, `!!document.querySelector('.ocf-choose #ocf-ch') && !document.querySelector('.ocf-slim')`, 80), '#2816 phone: the card on the start list');
    await nav(B + '#sheets');
    check(await ready(ev, `!!document.querySelector('.shvov [data-shv="new"]')`, 80), '#2816 phone: the tables overview');
    check(await ev(`document.querySelectorAll('[data-shv="new"]').length === 1 && !document.querySelector('.shvh') && document.documentElement.scrollWidth <= window.innerWidth + 1`), '#2816 phone: one heading, one button, no sideways scroll');
  }, false);

  console.log(`p2224_b_heads_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
