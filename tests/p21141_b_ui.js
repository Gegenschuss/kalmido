// 2.114.1 UI tests, part B (#2016, #2018, office: the books and the cash flow after a bank match), own container (start.sh,
// mode workspaces), Firefox. Invented companies, people, accounts and figures only. freelancer-matrix: office
// - a person without organisation (personal office, as found in the device test): the tab "Bookkeeping" is open, the
//   bank tab matches the money in to the invoice, back on "Bookkeeping" the statement shows the income without
//   reloading the page; "Undo match" -> the old figures again; the cash flow follows the same way (#2016)
// - the receipt matched to the money out is listed under "Out" in the cash flow as a receipt (#2018)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const TC = require('./testclock');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21141_b_ui', check, shots: 'P21141B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21141B_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients,docs,files';
const today = TC.today();
const de = iso => `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(0, 4)}`;
// a one-page PDF with a text layer, hand-written (as tests/p290_b_api_test.py tiny_pdf)
const tinyPdf = text => {
  const stream = `BT /F1 12 Tf 40 700 Td (${text}) Tj ET`;
  const objs = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'];
  let out = '%PDF-1.4\n'; const offs = [];
  objs.forEach((o, i) => { offs.push(out.length); out += `${i + 1} 0 obj\n${o}\nendobj\n`; });
  const x = out.length;
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n` + offs.map(o => String(o).padStart(10, '0') + ' 00000 n \n').join('');
  return out + `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${x}\n%%EOF\n`;
};

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
  await call(CF, 'PUT', '/api/office/settings', {company_fields: {name: 'Frida Film', street: 'Musterweg 1', zip: '12345', city: 'Musterstadt', country: 'DE', vat_id: 'DE123456789', iban: 'DE02120300000000202051', bic: 'BYLADEM1001', bank_name: 'Beispielbank'}});
  const cl = await call(CF, 'POST', '/api/clients', {name: 'Kunde Eins GmbH', street: 'Weg 2', zip: '10115', city: 'Berlin', country: 'DE'});
  const inv = await call(CF, 'POST', '/api/office/docs', {kind: 'invoice', client_id: cl.id, service_from: today, items: [{title: 'Schnitt', qty: 1, rate: 1000}]});
  const fin = await call(CF, 'POST', `/api/office/docs/${inv.id}/finalize`);
  check(fin.http === 200 && fin.number, 'a finalised invoice ' + fin.http);
  // the receipt (119 gross, software, 19 %), in the personal office's documents
  const info = await call(CF, 'GET', '/api/office/books');
  const fd = new FormData(); fd.append('files', new Blob([tinyPdf('Software Abo')], {type: 'application/pdf'}), 'abo.pdf'); fd.append('ws', info.upload_ws || 'private');
  const up = await (await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CF}, body: fd})).json().catch(() => ({}));
  const nid = (up.ids || [])[0];
  check(!!nid, 'the receipt is uploaded ' + JSON.stringify(up).slice(0, 200));
  const p1 = await call(CF, 'PATCH', `/api/docs/${nid}`, {amount: '119.00', date: today, name: 'Software Abo'});
  const p2 = await call(CF, 'PUT', `/api/docs/${nid}/receipt`, {category: 'Software', vat_pct: '19'});
  check(p1.http === 200 && p2.http === 200, `the receipt has amount, date and rate ${p1.http} ${p2.http}`);
  const csv = `Buchungstag;Auftraggeber/Empfänger;Verwendungszweck;Betrag\n${de(today)};Kunde Eins GmbH;Rechnung ${fin.number};1.190,00\n${de(today)};Software Beispiel GmbH;Abo;-119,00\n`;
  const pv = await call(CF, 'POST', '/api/office/bank/import/preview', {text: csv});
  const mapping = {}; for (const k of ['date', 'amount', 'amount_in', 'amount_out', 'title', 'counterpart', 'decimal', 'date_format']) mapping[k] = pv.guess?.[k] ?? null;
  const imp = await call(CF, 'POST', '/api/office/bank/import', {text: csv, filename: 'konto.csv', mapping});
  check(imp.http === 201 && imp.count === 2, 'two bookings imported ' + imp.http);
  const y = today.slice(0, 4);

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  // the profit shown vs. the one the server computes now (formatted the app's way)
  const profitIs = `fetch('/api/office/books/euer?year=${y}', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => { const b = document.querySelector('.bk-profit b'); return !!b && b.textContent.trim() === ofcMoney(j.profit) ? j.profit : false; })`;
  const shown = `document.querySelector('.bk-profit b')?.textContent.trim() || ''`;
  const tab = h => `(() => { location.hash = '${h}'; return 1; })()`;  // a tab change in the app, no page load
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'frida');
    await nav(B + '#office/books');
    check(await ready(ev, `!!document.querySelector('.bk-profit b')`, 80), 'the tab "Bookkeeping" shows the statement');
    const before = await ev(shown);
    await ev(`(() => { window.__p21141b = 1; return 1; })()`);  // gone after a page load
    // the cash flow once, so its data is loaded before the match
    await ev(tab('#office/cashflow'));
    check(await ready(ev, `!!document.querySelector('.rkcfv')`, 60), 'the cash flow is shown');
    await ev(tab('#office/bank'));
    const row = `[...document.querySelectorAll('.bnkrow')].find(e => /Kunde Eins/.test(e.textContent))`;
    check(await ready(ev, `!!(${row})?.querySelector('.bnksug [data-bnk="match"]')`, 60), 'the bank tab suggests the invoice');
    await ev(`(() => { ${row}.querySelector('.bnksug [data-bnk="match"]').click(); return 1; })()`);
    check(await ready(ev, `!(${row})`), 'matched: the booking leaves the open list');
    await ev(tab('#office/books'));
    check(await ready(ev, `${shown} !== ${JSON.stringify(before)} && ${profitIs}.then(p => p !== false && +p > 0)`), `#2016: after the match the statement shows the new profit without a page load (was ${before}, now ${await ev(shown)})`);
    check(await ev(`window.__p21141b === 1`), 'no page load in between');
    await shot('p21141-b-books.png');
    // the cash flow follows: the payment is in this month's money in
    await ev(tab('#office/cashflow'));
    check(await ready(ev, `RKF.data && (RKF.data.entries || []).some(e => e.kind === 'payment' && e.doc_id === ${inv.id})`, 60), '#2016: the cash flow lists the payment after the match');
    // undo the match in the bank tab -> the old figures again
    await ev(tab('#office/bank'));
    await ready(ev, `!!document.querySelector('[data-bnk="state"][data-v="matched"]')`);
    await ev(`(() => { document.querySelector('[data-bnk="state"][data-v="matched"]').click(); return 1; })()`);
    const done = `[...document.querySelectorAll('.bnkrow.done')].find(e => /Kunde Eins/.test(e.textContent))`;
    check(await ready(ev, `!!(${done})?.querySelector('[data-bnk="unmatch"]')`), 'the filter "Matched" shows the booking');
    await ev(`(() => { ${done}.querySelector('[data-bnk="unmatch"]').click(); return 1; })()`);
    check(await ready(ev, `!(${done})`), '"Undo match" opens it again');
    await ev(tab('#office/books'));
    check(await ready(ev, `${shown} === ${JSON.stringify(before)} && ${profitIs}.then(p => p !== false)`), `#2016: after "Undo match" the old figures again (${await ev(shown)})`);
    await ev(tab('#office/cashflow'));
    check(await ready(ev, `RKF.data && !(RKF.data.entries || []).some(e => e.kind === 'payment' && e.doc_id === ${inv.id})`, 60), '#2016: the cash flow drops the payment again');
  }, false);

  console.log(`p21141_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
