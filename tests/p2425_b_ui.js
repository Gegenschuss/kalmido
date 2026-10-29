// kalmido-suite: fresh
// 2.425.0 B (#3451) UI tests: recurring providers in Bank > Without receipt, own container (start.sh, mode workspaces), Firefox
// (desktop + phone width). Invented companies, accounts and figures only. tenant-matrix: office
// - above the list "Missing invoices of recurring providers": "Invoice <provider> <month> missing" with the portal link and an
//   upload field on the booking (drop target too)
// - below the list "Recurring providers": a provider with its rhythm; "No receipt needed" ticked takes its bookings off the list
//   (undo brings them back); the days field saves itself; the portal field saves an https link
// - phone: nothing sticks out to the side
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const TC = require('./testclock');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2425_b_ui', check, shots: 'P2425B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients,docs';
const day = n => { const d = new Date(TC.today() + 'T12:00:00'); d.setDate(d.getDate() - n); return d.toISOString().slice(0, 10); };
const ntry = (amt, d, ref, name) => `<Ntry><Amt Ccy="EUR">${amt}</Amt><CdtDbtInd>DBIT</CdtDbtInd><Sts><Cd>BOOK</Cd></Sts><BookgDt><Dt>${d}</Dt></BookgDt><AcctSvcrRef>${ref}</AcctSvcrRef><NtryDtls><TxDtls><RltdPties><Cdtr><Pty><Nm>${name}</Nm></Pty></Cdtr></RltdPties><RmtInf><Ustrd>Buchung ${ref}</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>`;
const camt = es => `<?xml version="1.0" encoding="UTF-8"?><Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt><Stmt><Acct><Id><IBAN>DE02120300000000202051</IBAN></Id><Ccy>EUR</Ccy></Acct>${es.join('')}</Stmt></BkToCstmrStmt></Document>`;

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
  await call(CA, 'PUT', '/api/office/settings', {company_fields: {name: 'Beispiel Film GmbH', street: 'Musterweg 1', zip: '12345', city: 'Musterstadt', country: 'DE'}});
  const imp = await call(CA, 'POST', '/api/office/bank/import', {text: camt([
    ntry('29.99', day(68), 'S-1', 'Speicherdienst Beispiel'), ntry('29.99', day(38), 'S-2', 'Speicherdienst Beispiel'), ntry('29.99', day(8), 'S-3', 'Speicherdienst Beispiel'),
    ntry('5.00', day(61), 'F-1', 'Kontoentgelt Beispielbank'), ntry('5.00', day(31), 'F-2', 'Kontoentgelt Beispielbank'), ntry('5.00', day(1), 'F-3', 'Kontoentgelt Beispielbank'),
    ntry('77.00', day(4), 'E-1', 'Einmal Haendler Beispiel')]), filename: 'konto.xml'});
  check(imp.http === 201 && imp.count === 7, 'seven bookings imported ' + imp.http);
  const monthOf = d => new Intl.DateTimeFormat('en', {month: 'long', year: 'numeric'}).format(new Date(d + 'T12:00:00'));

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const noSide = `(() => { const W = document.documentElement.clientWidth; return [...document.querySelectorAll('.office .ofcbody *')].filter(e => e.getClientRects().length && !e.closest('.seg')).every(e => e.getBoundingClientRect().right <= W + 1); })()`;
  const rows = `document.querySelectorAll('.bnrcols > div > .bnklist > .bnkrow').length`;
  const hints = `[...document.querySelectorAll('.bnvmiss .bnvhint')]`;
  const prov = name => `[...document.querySelectorAll('.bnvrow')].find(e => /${name}/.test(e.textContent))`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    await nav(B + '#office/bank/norc');
    // the hints above the list
    check(await ready(ev, `${hints}.length === 5`, 80), 'five hints (three of the storage service, the fee older than 5 days twice) ' + await ev(`${hints}.length`));
    const t3 = `Invoice Speicherdienst Beispiel ${monthOf(day(8))} missing`;
    check(await ev(`${hints}.some(e => e.textContent.includes(${JSON.stringify(t3)}) && !!e.querySelector('input[type=file][data-bnr-up]') && e.hasAttribute('data-bnr-drop'))`),
      'hint text with the month, an upload field, a drop target');
    check(await ev(`!${hints}.some(e => /Einmal/.test(e.textContent))`), 'a single booking gets no hint');
    // the providers' list below
    check(await ready(ev, `!!document.querySelector('.bnvlist > summary')`, 80), 'the providers section below the list');  // loads after the list
    await ev(`(() => { document.querySelector('.bnvlist > summary').click(); return 1; })()`);
    check(await ready(ev, `document.querySelector('.bnvlist').open && !!${prov('Speicherdienst')} && /Monthly/.test(${prov('Speicherdienst')}.textContent) && !!${prov('Kontoentgelt')}`),
      'the providers: monthly, two of them');
    await shot('p2425-b-providers.png');
    // the portal field saves itself, the hint shows the link
    await ev(`(() => { const i = ${prov('Speicherdienst')}.querySelector('[data-bnv-portal]'); i.value = 'https://portal.example.com/rechnungen'; i.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    check(await ready(ev, `${hints}.some(e => e.querySelector('a[href="https://portal.example.com/rechnungen"][target=_blank]'))`), 'portal saved: the hint links to it');
    // "No receipt needed" for the fee: its bookings leave the list; undo brings them back
    const before = await ev(rows);
    await ev(`(() => { ${prov('Kontoentgelt')}.querySelector('[data-bnv="noreceipt"]').click(); return 1; })()`);
    check(before === 7 && await ready(ev, `${rows} === 4 && ${hints}.length === 3 && ![...document.querySelectorAll('.bnrcols .bnkrow')].some(e => /Kontoentgelt/.test(e.textContent))`),
      'no receipt needed: the fee leaves the list and the hints ' + await ev(`${rows} + ' ' + ${hints}.length`));
    await ev(`(() => { histStep('undo'); return 1; })()`);
    check(await ready(ev, `${rows} === 7 && ${hints}.length === 5`), 'undo brings them back ' + await ev(`${rows}`));
    // the days
    await ev(`(() => { const i = document.querySelector('#bnv-days'); i.value = '9'; i.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    check(await ready(ev, `fetch('/api/office/bank/vendors', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => j.days === 9)`), 'days saved');
    check(await ready(ev, `${hints}.length === 4 && !${hints}.some(e => e.textContent.includes(${JSON.stringify(t3)}))`), 'days 9: the hint of eight days ago goes ' + await ev(`${hints}.length`));
    // phone width
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + '#office/bank/norc');
    check(await ready(ev, `${hints}.length === 4 && !!document.querySelector('.bnvlist')`, 80), 'phone: the view');
    await ev(`(() => { const d = document.querySelector('.bnvlist'); if (!d.open) d.querySelector('summary').click(); return 1; })()`);
    await ready(ev, `document.querySelector('.bnvlist').open`);
    check(await ev(noSide), 'phone: nothing sticks out to the side');
    await shot('p2425-b-phone.png');
  }, false);

  console.log(`p2425_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
