// 2.299.0 C (#3192) UI tests: bank bookings without a receipt, own container (start.sh, mode workspaces), Firefox (desktop +
// phone width). Invented companies, people, accounts and figures only; the receipt file is made here. tenant-matrix: office
// - the link #office/bank/norc opens the view "Without receipt" of the tab Bank: the payments without a receipt, income as
//   the second filter; "No receipt needed" takes a row away (undo brings it back); an uploaded receipt is matched at once
// - the office start page counts the bookings without a receipt and opens the view; the settings (area Data) switch the
//   reminder on and it saves itself
// - phone: nothing sticks out to the side, the buttons are 44 px; a member sees no counter
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const TC = require('./testclock');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2299_c_norc_ui', check, shots: 'P2299C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients,docs';
const day = n => { const d = new Date(TC.today() + 'T12:00:00'); d.setDate(d.getDate() - n); return d.toISOString().slice(0, 10); };
const ntry = (amt, ind, d, ref, name) => `<Ntry><Amt Ccy="EUR">${amt}</Amt><CdtDbtInd>${ind}</CdtDbtInd><Sts><Cd>BOOK</Cd></Sts><BookgDt><Dt>${d}</Dt></BookgDt><AcctSvcrRef>${ref}</AcctSvcrRef><NtryDtls><TxDtls><RltdPties><${ind === 'DBIT' ? 'Cdtr' : 'Dbtr'}><Pty><Nm>${name}</Nm></Pty></${ind === 'DBIT' ? 'Cdtr' : 'Dbtr'}></RltdPties><RmtInf><Ustrd>Buchung ${ref}</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>`;
// a one-page PDF with a text layer (hand-written, no library; the same as tiny_pdf of the API suites)
function tinyPdf(text) {
  const stream = `BT /F1 12 Tf 40 700 Td (${text}) Tj ET`;
  const objs = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'];
  let out = '%PDF-1.4\n'; const offs = [];
  objs.forEach((o, i) => { offs.push(out.length); out += `${i + 1} 0 obj\n${o}\nendobj\n`; });
  const x = out.length;
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n` + offs.map(o => String(o).padStart(10, '0') + ' 00000 n \n').join('');
  return out + `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${x}\n%%EOF\n`;
}
const camt = es => `<?xml version="1.0" encoding="UTF-8"?><Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt><Stmt><Acct><Id><IBAN>DE02120300000000202051</IBAN></Id><Ccy>EUR</Ccy></Acct>${es.join('')}</Stmt></BkToCstmrStmt></Document>`;

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
  await call(CA, 'PUT', '/api/office/settings', {company_fields: {name: 'Beispiel Film GmbH', street: 'Musterweg 1', zip: '12345', city: 'Musterstadt', country: 'DE'}});
  const imp = await call(CA, 'POST', '/api/office/bank/import', {text: camt([ntry('119.00', 'DBIT', day(3), 'U-1', 'Software Beispiel GmbH'), ntry('9.90', 'DBIT', day(2), 'U-2', 'Beispielbank Entgelt'),
    ntry('60.00', 'DBIT', day(4), 'U-3', 'Druckerei Beispiel'), ntry('500.00', 'CRDT', day(1), 'U-4', 'Kunde Eins GmbH')]), filename: 'konto.xml'});
  check(imp.http === 201 && imp.count === 4, 'four bookings imported ' + imp.http);

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const noSide = `(() => { const W = document.documentElement.clientWidth; return [...document.querySelectorAll('.office .ofcbody *')].filter(e => e.getClientRects().length && !e.closest('.seg')).every(e => e.getBoundingClientRect().right <= W + 1); })()`;
  const rows = `document.querySelectorAll('.bnklist .bnkrow').length`;
  const rowOf = name => `[...document.querySelectorAll('.bnkrow')].find(e => /${name}/.test(e.textContent))`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    // the start page counter opens the view
    await nav(B + '#office/start');
    check(await ready(ev, `/3 bookings without a receipt/.test(document.querySelector('.bnrcnt')?.textContent || '')`, 80), 'start page: "3 bookings without a receipt"');
    await ev(`(() => { document.querySelector('.bnrcnt').click(); return 1; })()`);
    check(await ready(ev, `${rows} === 3 && !!document.querySelector('[data-bnk="state"][data-v="norc"].on') && !document.querySelector('.bnrbar [data-bnr="dir"][data-v="in"].on')`, 80),
      'the view "Without receipt": three payments ' + await ev(`location.hash + ' ' + ${rows}`));
    check(await ev(`!/Kunde Eins/.test(document.querySelector('.bnklist').textContent)`), 'income is not in the payments');
    await shot('p2299-c-norc.png');
    // "No receipt needed" + undo
    await ev(`(() => { ${rowOf('Beispielbank')}.querySelector('[data-bnr="noreceipt"]').click(); return 1; })()`);
    check(await ready(ev, `${rows} === 2 && !${rowOf('Beispielbank')}`), '"No receipt needed" takes the row away ' + await ev(`[location.hash, ${rows}, typeof bnr_upload, typeof BNR, document.querySelector('#toast')?.textContent, document.querySelector('.bnklist')?.textContent.slice(0, 200)].join(' | ')`));
    await ev(`(() => { histStep('undo'); return 1; })()`);  // the toast's Undo (the step of the history)
    check(await ready(ev, `${rows} === 3`), 'undo brings it back ' + await ev(`[location.hash, ${rows}, typeof bnr_upload, typeof BNR, document.querySelector('#toast')?.textContent, document.querySelector('.bnklist')?.textContent.slice(0, 200)].join(' | ')`));
    // upload a receipt for a row (the file made here)
    const tid = await ev(`+(${rowOf('Druckerei')}?.dataset.tx || 0)`);
    check(tid > 0 && await ev('typeof bnr_upload === "function"'), 'the row and the upload are there ' + await ev(`[location.hash, typeof bnr_upload].join(' ')`));
    if (tid) await ev(`(() => { bnr_upload(${tid}, new File([${JSON.stringify(tinyPdf('Rechnung Druckerei Beispiel 60,00 EUR'))}], 'druckerei.pdf', {type: 'application/pdf'})); return 1; })()`);
    check(await ready(ev, `${rows} === 2 && !${rowOf('Druckerei')}`, 60), 'an uploaded receipt is matched at once ' + await ev(`[${rows}, document.querySelector('#toast')?.textContent].join(' | ')`));
    check(await ready(ev, `fetch('/api/office/bank/tx?state=matched', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => j.items.some(t => t.id === ${tid} && t.match.kind === 'receipt'))`), 'the booking is matched with the receipt');
    // income as the second filter
    await ev(`(() => { document.querySelector('[data-bnr="dir"][data-v="in"]').click(); return 1; })()`);
    check(await ready(ev, `${rows} === 1 && /Kunde Eins/.test(document.querySelector('.bnklist').textContent) && !!document.querySelector('[data-bnr="pick"]')`), 'income without an invoice');
    await ev(`(() => { document.querySelector('[data-bnr="dir"][data-v="out"]').click(); return 1; })()`);
    await ready(ev, `${rows} === 2`);
    // the reminder in the settings (area Data)
    await nav(B + '#office/settings');
    await ready(ev, `!!document.querySelector('[data-ostsub="data"]')`, 80);
    await ev(`(() => { document.querySelector('[data-ostsub="data"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('#bnr-every') && document.querySelector('#bnr-every').value === 'off'`, 60), 'settings: the reminder, off');
    await ev(`(() => { const s = document.querySelector('#bnr-every'); s.value = 'week'; s.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    check(await ready(ev, `fetch('/api/office/bank/noreceipt/reminder', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => j.every === 'week' && !!j.task)`), 'settings: weekly saves itself, the task is there');
    // phone width
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + '#office/bank/norc');
    check(await ready(ev, `${rows} === 2`, 80), 'phone: the view');
    check(await ev(noSide), 'phone: nothing sticks out to the side');
    check(await ev(`(() => { const b = [...document.querySelectorAll('.bnkrow .bnkacts .btn')]; return b.length > 0 && b.every(x => x.getBoundingClientRect().height >= 43.5); })()`), 'phone: the buttons are 44 px');
    check(await ev(`!document.querySelector('.bnrrc')`), 'phone: no drag column, "Choose receipt…" instead');
    await shot('p2299-c-norc-phone.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    // member: no counter
    await signIn(ev, 'bob');
    await nav(B + 'static/icon.svg');
    await nav(B + '#office/start');
    await ready(ev, `!!document.querySelector('.ofmstart') && typeof BNR === 'object' && BNR.cntAt > 0`, 80);  // the counter's answer came (403)
    check(await ev(`!document.querySelector('.bnrcnt')`), 'a member sees no counter');
  }, false);

  console.log(`p2299_c_norc_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
