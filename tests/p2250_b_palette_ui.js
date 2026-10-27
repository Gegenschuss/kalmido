// 2.250.0 B (#2993 #2996) UI test, own container (start.sh): the command palette.
//  - the empty palette lists every target once (no two entries with the same route); the old names still find the merged entry
//  - the office bar's points are "Go to" targets (Cash book) -- for the admin, not for a member without the bookkeeping; a person
//    without an organisation finds the pages of the own office
//  - "vacation" (and sick, day off ...) finds "Enter an absence", Enter opens the sheet; the page is called "Workload & absences"
//  - settings sections ("Language", "API tokens") only while typing
// freelancer-matrix: office -- the same checks once as the admin of the org, once as a person without an organisation.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2250B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const FEAT = 'cal,comments,collab,clients,contacts,office,workload';
const call = async (method, url, body, ck) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const input = (w, el, v) => { el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const ACK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Example Studio', lang: 'en', collab_all: true, modules: ['cal', 'comments']}, ACK);
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, ACK);
  await call('POST', '/api/users', {orgs: [1], username: 'mia', display_name: 'Mia', password: 'password123', email: 'mia@example.com'}, ACK);
  await call('POST', '/api/users', {orgs: [], username: 'fiona', display_name: 'Fiona', password: 'password123', email: 'fiona@example.com'}, ACK);
  for (const u of ['mia', 'fiona']) { const ck = await login(u); await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, ck); }

  const run = async (user, tag, o) => {
    const w = await boot({user, hash: 'inbox'}), d = w.document;
    await until(() => w.eval('!!S.booted && typeof palAll === "function"'));
    if (o.cashbook) await until(() => w.eval('ofm_adm() === true'));  // the role is read quietly once
    else await sleep(900);
    const all = w.eval('palAll().map(x => ({id: x.id, route: x.route || "", label: x.label, kind: x.kind, qonly: !!x.qonly}))');
    const routes = all.filter(x => x.route).map(x => x.route);
    check(routes.length > 0 && new Set(routes).size === routes.length, tag + 'every target once: ' + routes.filter((r, i) => routes.indexOf(r) !== i));
    const labels = all.filter(x => x.kind === 'view' && !x.qonly).map(x => x.label);
    check(new Set(labels).size === labels.length, tag + 'no view name twice: ' + labels.filter((r, i) => labels.indexOf(r) !== i));
    check(!all.some(x => /^Settings: (Language|API tokens)$/.test(x.label) && !x.qonly), tag + 'setting sections only while typing');
    w.eval('openPalette()'); await sleep(200);
    const inp = d.querySelector('.palette .pqin');
    const items = () => [...d.querySelectorAll('.palette .pitem .plt')].map(x => x.textContent);
    const find = async (q, what) => { input(w, inp, q); await sleep(150); return items().some(t => what.test(t)); };
    check(await find('cash book', /^Cash book$/) === !!o.cashbook, tag + '"cash book" ' + (o.cashbook ? 'found' : 'not offered'));
    check(await find('bank', /^Bank$/) === !!o.cashbook, tag + '"bank" follows the office rights');
    check(await find('language', /^Settings: Language$/), tag + 'settings section "Language" found');
    check(await find('sick', /^Enter an absence$/), tag + '"sick" finds "Enter an absence"');
    check(await find('vacation', /^Enter an absence$/), tag + '"vacation" finds "Enter an absence"');
    check(await find('workload', /^Workload & absences$/), tag + 'the page is called "Workload & absences"');
    check(await find('invoice', /^Add invoice$/), tag + '"Add invoice" is offered (quotes & invoices are open to every member)');
    check(await find('open items', /^Quotes & invoices$/), tag + '"open items" finds Quotes & invoices (no page of its own)');
    check(await find('client', /^Add client$/), tag + '"Add client" is offered');
    input(w, inp, 'vacation'); await sleep(150);
    const at = [...d.querySelectorAll('.palette .pitem')].findIndex(b => b.querySelector('.plt')?.textContent === 'Enter an absence');
    w.eval(`PAL.i = ${at}`);
    inp.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Enter', bubbles: true, cancelable: true}));
    check(await until(() => [...d.querySelectorAll('.modal h3, .modal-card h3, h3')].some(h => h.textContent === 'Enter an absence'), 80), tag + 'Enter opens the absence sheet');
    check(!errs.length, tag + 'no JS errors ' + errs.join(' | '));
    w.close();
  };
  await run('alice', 'admin: ', {office: true, cashbook: true});
  await run('mia', 'member: ', {office: true, cashbook: false});
  await run('fiona', 'no organisation: ', {office: true, cashbook: true});
  console.log(F.length ? `FAILED ${F.length}` : 'ALL OK', ok, 'checks');
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
