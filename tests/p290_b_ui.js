// 2.90.0 UI tests, part B (#1921, office: bank reconciliation), own container (start.sh, mode workspaces), Firefox (desktop +
// phone width). Invented companies, people, accounts and figures only. tenant-matrix: office
// - the admin has the tab "Bank": the open bookings of an imported CSV with the best suggestion; one tap "Match" pays the
//   invoice, the filter "Matched" shows it, "Undo match" opens it again; "Private" marks a booking
// - the import dialog: a CAMT file goes straight to the preview and is taken over; a CSV first asks for the columns
// - on a phone nothing sticks out to the side; a member sees no tab "Bank"
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const TC = require('./testclock');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p290_b_ui', check, shots: 'P290B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P290B_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients';
const day = n => { const d = new Date(TC.today() + 'T12:00:00'); d.setDate(d.getDate() - n); return d.toISOString().slice(0, 10); };
const de = iso => `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(0, 4)}`;

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
  await call(CA, 'PUT', '/api/office/settings', {company_fields: {name: 'Beispiel Film GmbH', street: 'Musterweg 1', zip: '12345', city: 'Musterstadt', country: 'DE', vat_id: 'DE123456789', iban: 'DE02120300000000202051', bic: 'BYLADEM1001', bank_name: 'Beispielbank'}});
  const cl = await call(CA, 'POST', '/api/clients', {name: 'Kunde Eins GmbH', street: 'Weg 2', zip: '10115', city: 'Berlin', country: 'DE'});
  const inv = await call(CA, 'POST', '/api/office/docs', {kind: 'invoice', client_id: cl.id, service_from: day(20), items: [{title: 'Schnitt', qty: 1, rate: 1000}]});
  const fin = await call(CA, 'POST', `/api/office/docs/${inv.id}/finalize`);
  check(fin.http === 200 && fin.number, 'a finalised invoice ' + fin.http);
  const csv = `Buchungstag;Auftraggeber/Empfänger;Verwendungszweck;Betrag\n${de(day(3))};Kunde Eins GmbH;Rechnung ${fin.number};1.190,00\n${de(day(2))};Bäckerei Beispiel;Brötchen;-4,50\n${de(day(1))};Software Beispiel GmbH;Abo;-119,00\n`;
  const pv = await call(CA, 'POST', '/api/office/bank/import/preview', {text: csv});
  const mapping = {}; for (const k of ['date', 'amount', 'amount_in', 'amount_out', 'title', 'counterpart', 'decimal', 'date_format']) mapping[k] = pv.guess?.[k] ?? null;
  const imp = await call(CA, 'POST', '/api/office/bank/import', {text: csv, filename: 'konto.csv', mapping});
  check(imp.http === 201 && imp.count === 3, 'three bookings imported ' + imp.http);

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const noSide = `(() => { const W = document.documentElement.clientWidth; return [...document.querySelectorAll('.office .ofcbody *')].filter(e => e.getClientRects().length && !e.closest('.seg')).every(e => e.getBoundingClientRect().right <= W + 1); })()`;
  const api = (m, u) => `fetch('${u}', {method: '${m}', headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json())`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    await nav(B + '#office/bank');
    check(await ready(ev, `document.querySelectorAll('.bnklist .bnkrow').length === 3`, 80), 'the bank tab lists three open bookings');
    check(await ev(`!!document.querySelector('#view .ofmenu [data-ofm="bank"]')`), 'the tab "Bank" for the admin');
    const row = `[...document.querySelectorAll('.bnkrow')].find(e => /Kunde Eins/.test(e.textContent))`;
    check(await ev(`(() => { const r = ${row}; return !!r && /\\+/.test(r.querySelector('.bnkamt').textContent) && r.querySelector('.bnkamt').classList.contains('in') && /${fin.number}/.test(r.querySelector('.bnksug')?.textContent || ''); })()`),
      'money in shows a plus and the invoice as suggestion ' + await ev(`${row}?.textContent`));
    check(await ev(`/−/.test([...document.querySelectorAll('.bnkrow')].find(e => /Bäckerei/.test(e.textContent)).querySelector('.bnkamt').textContent)`), 'money out shows a minus');
    await shot('p290-b-bank.png');
    await ev(`(() => { ${row}.querySelector('.bnksug [data-bnk="match"]').click(); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('.bnklist .bnkrow').length === 2`), 'after "Match" the booking leaves the open list');
    check(await ready(ev, `${api('GET', `/api/office/docs/${inv.id}`)}.then(j => j.status === 'paid')`), 'the invoice is paid');
    await ev(`(() => { document.querySelector('[data-bnk="state"][data-v="matched"]').click(); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('.bnklist .bnkrow.done').length === 1 && /${fin.number}/.test(document.querySelector('.bnkrow.done .bnkm').textContent)`), 'the filter "Matched" shows it with the invoice');
    await ev(`(() => { document.querySelector('.bnkrow.done [data-bnk="unmatch"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.bnklist .bnkrow.done')`), '"Undo match" opens it again');
    check(await ready(ev, `${api('GET', `/api/office/docs/${inv.id}`)}.then(j => j.status !== 'paid' && j.open !== '0.00')`), 'the payment is gone');
    await ev(`(() => { document.querySelector('[data-bnk="state"][data-v="open"]').click(); return 1; })()`);
    await ready(ev, `document.querySelectorAll('.bnklist .bnkrow').length === 3`);
    await ev(`(() => { [...document.querySelectorAll('.bnkrow')].find(e => /Bäckerei/.test(e.textContent)).querySelector('[data-bnk="match"][data-kind="private"]').click(); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('.bnklist .bnkrow').length === 2`), '"Private" marks a booking');
    // "Other invoice…" lists the open invoice
    await ev(`(() => { ${row}.querySelector('[data-bnk="other"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.bnkother .ofcrow[data-kind="invoice"]')`), '"Other invoice…" lists the open invoice');
    // the import dialog: CAMT straight to the preview
    const camt = `<?xml version="1.0" encoding="UTF-8"?><Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt><Stmt><Ntry><Amt Ccy="EUR">80.00</Amt><CdtDbtInd>DBIT</CdtDbtInd><BookgDt><Dt>${day(4)}</Dt></BookgDt><NtryDtls><TxDtls><RltdPties><Cdtr><Pty><Nm>Druckerei Beispiel</Nm></Pty></Cdtr></RltdPties><RmtInf><Ustrd>Flyer</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry></Stmt></BkToCstmrStmt></Document>`;
    await ev(`(() => { bnkImpModal(${JSON.stringify(camt)}, 'auszug.xml'); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('.bnkdlg .bnkprev .ofcrow').length === 1 && !!document.querySelector('.bnkdlg [data-bi="next"]')`), 'CAMT: the preview without a column step');
    await ev(`(() => { document.querySelector('.bnkdlg [data-bi="next"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.bnkdlg') && [...document.querySelectorAll('.bnkrow')].some(e => /Druckerei/.test(e.textContent))`), 'CAMT: taken over, the booking is in the list');
    // a CSV first asks for the columns
    await ev(`(() => { bnkImpModal(${JSON.stringify('Buchungstag;Name;Verwendungszweck;Betrag\n' + de(day(5)) + ';Kino Beispiel;Miete;-300,00\n')}, 'zwei.csv'); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.bnkdlg #bi-date') && document.querySelector('.bnkdlg #bi-amt').value === '3'`), 'CSV: the column step with the guess');
    await shot('p290-b-import.png');
    await ev(`(() => { document.querySelector('.bnkdlg [data-bi="next"]').click(); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('.bnkdlg .bnkprev .ofcrow').length === 1`), 'CSV: the preview');
    await ev(`(() => { document.querySelector('.bnkdlg [data-bi="next"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.bnkdlg') && [...document.querySelectorAll('.bnkrow')].some(e => /Kino/.test(e.textContent))`), 'CSV: taken over');
    // the import list with "Take back"
    await ev(`(() => { document.querySelector('[data-bnk="imps"]').click(); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('.bnkimps .ofcrow').length === 3`), 'the imports are listed');
    await ev(`(() => { document.querySelector('.bnkimps [data-bnk="impundo"]').click(); return 1; })()`);
    check(await ready(ev, `![...document.querySelectorAll('.bnkrow')].some(e => /Kino/.test(e.textContent))`), '"Take back" removes the bookings of the newest import');
    // phone width
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await sleep(300);
    check(await ev(noSide), 'on a phone the bookings stay inside the screen');
    await shot('p290-b-bank-phone.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    // member
    await signIn(ev, 'bob');
    await nav(B + 'static/icon.svg');
    await nav(B + '#office/offers');
    check(await ready(ev, `!!document.querySelector('#view .ofmenu [data-ofm="offers"]')`, 80), 'the office (member)');
    check(await ev(`!document.querySelector('#view .ofmenu [data-ofm="bank"]')`), 'a member sees no tab "Bank"');
  }, false);

  console.log(`p290_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
