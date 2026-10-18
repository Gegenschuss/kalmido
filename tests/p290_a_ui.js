// 2.90.0 UI tests, part A (#1921, bookkeeping light), own container (start.sh, mode workspaces), Firefox (desktop + phone
// width). Invented companies, people and figures only.
// - the admin has the tab "Bookkeeping"; #office/books/ustva opens it at the VAT return figures
// - the big button "Photograph receipt" is a file field with capture (camera on a phone); a file through it opens the
//   receipt sheet, saving it puts the receipt with category and VAT rate into the list of the month
// - the income/expense statement (income from the paid invoice, the receipt as an expense) with CSV / PDF links, the
//   note "no tax advice"; the switch cash / accrual basis is saved
// - with a tax reserve the cash flow shows the rows "Tax reserve" and "Freely available"
// - on a phone nothing sticks out to the side; a member does not see the tab
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const TC = require('./testclock');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p290_a_ui', check, shots: 'P290A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P290A_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients,docs';
const today = TC.today();

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob Member', password: 'password123', email: 'bob@example.com'});
  const CB = await login('bob');
  for (const ck of [CA, CB]) await call(ck, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CA, 'PUT', `/api/orgs/${org.id}/members`, {email: 'bob@example.com', role: 'member'});
  for (const ck of [CA, CB]) await call(ck, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  await call(CA, 'PUT', '/api/office/settings', {company_fields: {name: 'Studio Beispiel GmbH', street: 'Teststraße 1', zip: '20000', city: 'Hamburg', country: 'DE',
    tax_number: '12/345/67890', iban: 'DE02120300000000202051', bic: 'BYLADEM1001', bank_name: 'Beispielbank'}});
  const cl = await call(CA, 'POST', '/api/clients', {name: 'Kunde Eins GmbH', street: 'Weg 1', zip: '10000', city: 'Berlin', country: 'DE'});
  const inv = await call(CA, 'POST', '/api/office/docs', {kind: 'invoice', client_id: cl.id, service_from: today, service_to: today, items: [{title: 'Schnitt', qty: 1, rate: 1000}]});
  check(inv.http === 201, 'an invoice ' + inv.http);
  check((await call(CA, 'POST', `/api/office/docs/${inv.id}/finalize`)).http < 300, 'finalised');
  check((await call(CA, 'POST', `/api/office/docs/${inv.id}/payments`, {date: today, amount: 1190})).http === 201, 'paid today');
  check((await call(CA, 'PUT', '/api/office/settings', {tax_reserve_pct: 20})).http === 200, 'tax reserve 20 %');
  const year = today.slice(0, 4), quarter = 'q' + (Math.floor((+today.slice(5, 7) - 1) / 3) + 1);

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const noSide = `(() => { const W = document.documentElement.clientWidth; return [...document.querySelectorAll('.office .ofcbody *')].filter(e => e.getClientRects().length && !e.closest('.seg')).every(e => e.getBoundingClientRect().right <= W + 1); })()`;
  const api = (m, u, b) => `fetch('${u}', {method: '${m}', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}${b ? `, body: JSON.stringify(${JSON.stringify(b)})` : ''}}).then(r => r.json())`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    await nav(B + '#office/books/ustva');
    check(await ready(ev, `!!document.querySelector('#bk-ustva .bk-kz')`, 80), 'the tab opens at the VAT return figures');
    check(await ev(`document.querySelector('#bk-period').value === BK.period && /^q[1-4]$/.test(BK.period)`), 'quarters by default (no tax dates set)');
    await ev(`(() => { const p = document.querySelector('#bk-pyear'); p.value = '${year}'; p.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    await sleep(300);
    await ev(`(() => { const p = document.querySelector('#bk-period'); p.value = '${quarter}'; p.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    await ready(ev, `BK.ustva && BK.ustva.period === '${quarter}' && BK.ustva.year === ${+year}`);
    check(await ev(`!!document.querySelector('.ofctabs [data-go="office/books"][aria-selected="true"]')`), 'the tab "Bookkeeping" is selected');
    check(await ev(`(() => { const i = document.querySelector('#bk-file'); return !!i && i.getAttribute('capture') === 'environment' && /image\\/\\*/.test(i.accept) && /pdf/.test(i.accept); })()`),
      'the photo button: a file field with capture=environment, images and PDF');
    check(await ev(`/No tax advice/.test(document.querySelector('#bk-ustva').textContent)`), 'the note "no tax advice"');
    check(await ready(ev, `/1,000/.test(document.querySelector('#bk-ustva .bk-kz').textContent) && /Field 81/.test(document.querySelector('#bk-ustva .bk-kz').textContent)`),
      'field 81 with the paid invoice ' + await ev(`document.querySelector('#bk-ustva .bk-kz')?.textContent`));
    // the EUeR
    check(await ev(`document.querySelectorAll('.bk-tab').length === 2 && /1,000\\.00/.test(document.querySelector('.bk-tab').textContent)`), 'the EUeR: income from the payment');
    check(await ev(`!!document.querySelector('a[href="/api/office/books/euer.csv?year=${year}"]') && !!document.querySelector('a[href="/api/office/books/euer.pdf?year=${year}"]')`), 'the EUeR: CSV + PDF links');
    check(await ev(`/200\\.00/.test(document.querySelector('.bk-res')?.textContent || '')`), 'the EUeR: tax reserve of the year (20 % of 1,000)');
    await shot('p290-a-books.png');
    // a receipt through the photo button (a generated PDF)
    await ev(`(() => { const s = 'BT /F1 12 Tf 40 700 Td (Beleg) Tj ET';
      const o = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>', '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
        '<< /Length ' + s.length + ' >>\\nstream\\n' + s + '\\nendstream', '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'];
      let out = '%PDF-1.4\\n'; const offs = [];
      o.forEach((x, i) => { offs.push(out.length); out += (i + 1) + ' 0 obj\\n' + x + '\\nendobj\\n'; });
      const xr = out.length; out += 'xref\\n0 ' + (o.length + 1) + '\\n0000000000 65535 f \\n' + offs.map(n => String(n).padStart(10, '0') + ' 00000 n \\n').join('');
      out += 'trailer\\n<< /Size ' + (o.length + 1) + ' /Root 1 0 R >>\\nstartxref\\n' + xr + '\\n%%EOF\\n';
      const dt = new DataTransfer(); dt.items.add(new File([out], 'beleg.pdf', {type: 'application/pdf'}));
      const i = document.querySelector('#bk-file'); i.files = dt.files; i.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal.bk-sheet #bk-vat') || !!document.querySelector('.bk-sheet #bk-vat')`, 60), 'the receipt sheet opens after the upload');
    await ev(`(() => { const m = document.querySelector('.bk-sheet'); m.querySelector('#bk-cat').value = 'Software'; m.querySelector('#bk-vat').value = '19'; m.querySelector('#bk-amount').value = '119.00';
      const d = m.querySelector('#bk-date'); d.value = '${today}'; m.querySelector('[data-m="save"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.bk-sheet') && [...document.querySelectorAll('[data-bk="rc"]')].some(b => /Software/.test(b.textContent) && /119\\.00/.test(b.textContent))`, 60),
      'the receipt is in the list of the month with category and amount');
    check(await ev(`${api('GET', `/api/office/books/euer?year=${year}`)}.then(j => j.expenses.some(x => x.label === 'Software' && x.vat === '19.00'))`), 'the receipt counts in the EUeR with 19 % input tax');
    // the basis switch
    await ev(`(() => { document.querySelector('[data-bk="basis"][data-v="soll"]').click(); return 1; })()`);
    check(await ready(ev, `${api('GET', '/api/office/settings')}.then(j => j.settings.vat_basis === 'soll')`), 'accrual basis saved');
    check(await ready(ev, `document.querySelector('[data-bk="basis"][data-v="soll"]')?.getAttribute('aria-pressed') === 'true'`), 'the switch shows it');
    // phone width
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await sleep(400);
    check(await ev(noSide), 'on a phone nothing sticks out to the side');
    check(await ev(`document.querySelector('.bk-shot').getBoundingClientRect().height >= 44`), 'on a phone the photo button is large');
    await shot('p290-a-books-phone.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    // the cash flow with the reserve
    await nav(B + '#office/cashflow');
    check(await ready(ev, `!!document.querySelector('.rkcfm.cur .bk-cfres') && !!document.querySelector('.rkcfm.cur .bk-cffree')`, 80), 'the cash flow: rows tax reserve + freely available');
    check(await ev(`/200\\.00/.test(document.querySelector('.rkcfm.cur .bk-cfres').textContent)`), 'the cash flow: 20 % of 1,000 net received');
    await shot('p290-a-cashflow.png');
    // member
    await signIn(ev, 'bob');
    await nav(B + 'static/icon.svg');
    await nav(B + '#office/offers');
    check(await ready(ev, `!!document.querySelector('.ofctabs [data-go="office/offers"]')`, 80), 'the office (member)');
    check(await ev(`!document.querySelector('.ofctabs [data-go="office/books"]')`), 'a member does not see the tab');
  }, false);

  console.log(`p290_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
