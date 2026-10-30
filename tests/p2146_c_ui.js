// 2.146.0 UI tests, part C, own container (start.sh). Invented statements only (made here). jsdom:
// #2455 the household import: two CAMT.052 day reports chosen at once -> the hint "better CAMT.053", the pending bookings
//       in their own section (never a checkbox), the duplicate of the second report marked; taken over -> the dialog lists the
//       import under "Last imports" and takes it back after the question; a CSV with an S/H column pre-selects the mark
// #2469 the office's bank import: the day-report hint, a pending row marked "pending – not imported", the start hint no
//       longer says "Do not use" for CAMT.052
// Firefox 390 touch: the household preview with pending bookings fits the phone (no horizontal scrolling), screenshot.
// Screenshots with P2146C_SHOTS=<dir>.
// freelancer-matrix: n/a - nur Oberflaeche (die Person ohne Organisation prueft p2146_c_api_test.py)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2146_c_ui', check, shots: 'P2146C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!(process.env.P2146C_NOSTART || process.env.KMT_NOSTART)) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const FEAT = 'collab,contracts,budget,home,office,clients';
const IBAN1 = 'DE02120300000000202051', IBAN2 = 'DE89370400440532013000';
const ntry = (amt, day, sts, svc, text) => `<Ntry><Amt Ccy="EUR">${amt}</Amt><CdtDbtInd>DBIT</CdtDbtInd><Sts>${sts}</Sts><BookgDt><Dt>${day}</Dt></BookgDt>${svc ? `<AcctSvcrRef>${svc}</AcctSvcrRef>` : ''}<NtryDtls><TxDtls><RltdPties><Cdtr><Nm>Shop Example</Nm></Cdtr><CdtrAcct><Id><IBAN>${IBAN2}</IBAN></Id></CdtrAcct></RltdPties><RmtInf><Ustrd>${text}</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>`;
const c052 = (id, es) => `<?xml version="1.0" encoding="UTF-8"?><Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.052.001.02"><BkToCstmrAcctRpt><Rpt><Id>${id}</Id><Acct><Id><IBAN>${IBAN1}</IBAN></Id></Acct>${es.join('')}</Rpt></BkToCstmrAcctRpt></Document>`;
const D1 = c052('R-1', [ntry('12.50', '2026-09-01', 'BOOK', 'REF-A1', 'Bakery'), ntry('30.00', '2026-09-01', 'PDNG', '', 'Fuel pending')]);
const D2 = c052('R-2', [ntry('12.50', '2026-09-02', 'BOOK', 'REF-A1', 'Bakery again'), ntry('30.00', '2026-09-02', 'BOOK', 'REF-P1', 'Fuel station'), ntry('55.00', '2026-09-02', 'PDNG', '', 'Order pending')]);

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'private'});
  const LID = (await call('POST', '/api/budget/lists', {})).list_id;

  // ================= #2455 #2469 the household import: two day reports
  let w = await boot({user: 'alice', hash: `budget/${LID}`}), d = w.document;
  const dlg = () => d.querySelector('.modal.bgdlg');
  await until(() => d.querySelector('[data-bg="csv"]'), 60);
  click(w, d.querySelector('[data-bg="csv"]'));
  const inp = await until(() => dlg()?.querySelector('[data-cs-file]'));
  check(inp && inp.multiple && /\.zip/.test(inp.accept), '#2455: the file input takes several files and a ZIP');
  dlg().bgTake([new w.File([D1], 'tag1.xml'), new w.File([D2], 'tag2.xml')]);
  await until(() => dlg()?.querySelector('.bgprev .bgpr'), 60);
  check(dlg()?.querySelector('.bnk052') && /CAMT\.053/.test(dlg().querySelector('.bnk052').textContent), '#2469: the day-report hint recommends CAMT.053 ' + (dlg()?.querySelector('.aerr')?.textContent || ''));
  const pend = dlg()?.querySelector('.bgpend');
  check(pend && pend.querySelectorAll('.bgpendl li').length === 2 && !pend.querySelector('input'), '#2469: two pending bookings in their own section, no checkbox');
  const prs = [...(dlg()?.querySelectorAll('.bgprev .bgpr') || [])];
  check(prs.length === 3 && !prs.some(x => /pending/.test(x.textContent)), '#2469: the preview lists the 3 booked rows only ' + prs.length);
  const dup = prs.find(x => x.classList.contains('dup'));
  check(dup && /Bakery again/.test(dup.textContent) && !dup.querySelector('[data-csr]').checked, '#2469: the same bank reference in the second report = a duplicate, not chosen');
  check(prs.some(x => /tag2\.xml/.test(x.textContent)), '#2455: several files: each row names its file');
  check(/Take over 2 entries/.test(dlg().querySelector('[data-cs="next"]')?.textContent || ''), '#2455: "Take over 2 entries"');
  click(w, dlg().querySelector('[data-cs="next"]'));
  check(await until(() => d.querySelector('.itc-dlg [data-cd="yes"]')), 'the import names its target first');
  click(w, d.querySelector('.itc-dlg [data-cd="yes"]')); await until(() => !dlg(), 60);
  const runs = (await call('GET', `/api/budget/${LID}/import/runs`)).items || [];
  check(runs.length === 1 && runs[0].count === 2, '#2455: one import run with 2 entries ' + JSON.stringify(runs));
  // the dialog lists the import and takes it back after the question
  click(w, d.querySelector('[data-bg="csv"]'));
  const undo = await until(() => dlg()?.querySelector('.bgruns [data-csundo]'), 60);
  check(undo && /Take this import back/.test(undo.textContent), '#2455: "Last imports" offers to take the import back');
  let asked = '';
  w.confirm = t => { asked = t; return true; };  // boot.js dialogBridge answers the app's question with w.confirm
  click(w, undo);
  await until(() => asked, 60);
  check(/Take this import back/.test(asked) && /2 entries of this import/.test(asked), '#2455: the question names how many entries go ' + asked.slice(0, 160));
  await until(async () => ((await call('GET', `/api/budget/${LID}/import/runs`)).items || [])[0]?.left === 0, 60);
  check(((await call('GET', `/api/budget/${LID}/import/runs`)).items || [])[0]?.left === 0, '#2455: the import is taken back');
  await until(() => !dlg()?.querySelector('.bgruns [data-csundo]'), 60);
  check(dlg() && !dlg().querySelector('.bgruns [data-csundo]'), '#2455: the list no longer offers it');
  // a CSV with an S/H column: the mark is pre-selected in the column step
  const VB = 'Buchungstag;Valuta;Auftraggeber/Zahlungsempfänger;Empfänger/Zahlungspflichtiger;Konto-Nr.;IBAN;BLZ;BIC;Vorgang/Verwendungszweck;Kundenreferenz;Währung;Umsatz;\n'
    + `03.09.2026;03.09.2026;Ich;Supermarket Example;;${IBAN2};;;Groceries;;EUR;45,20;S\n04.09.2026;04.09.2026;Ich;Employer Example;;;;;Salary;;EUR;2.000,00;H\n`;
  dlg().bgTake([new w.File([VB], 'umsaetze.csv')]);
  await until(() => dlg()?.querySelector('#cs-sign'), 60);
  check(dlg()?.querySelector('#cs-sign')?.value === '12' && /Volksbank/.test(dlg()?.querySelector('.bgpreset')?.textContent || ''), '#2455: the Volksbank layout, the S/H column pre-selected');
  check([...(dlg()?.querySelectorAll('#cs-df option') || [])].some(o => o.value === 'YYYYMMDD'), '#2455: the date format YYYYMMDD offered');
  click(w, dlg().querySelector('[data-cs="next"]'));
  await until(() => dlg()?.querySelectorAll('.bgpr').length === 2, 60);
  const amts = [...(dlg()?.querySelectorAll('.bgpr .bgamt') || [])].map(x => x.className);
  check(amts.length === 2 && /out/.test(amts[0]) && /in/.test(amts[1]), '#2455: S = expense, H = income ' + amts.join(' | '));
  dlg()?.remove();
  w.close();

  // ================= #2469 the office's bank import
  w = await boot({user: 'alice', hash: 'office/bank'}); d = w.document;
  await until(() => typeof w.bnkImpModal === 'function', 80);
  w.bnkImpModal(null, null);
  const md = await until(() => d.querySelector('.modal.bnkdlg'));
  check(md && /Better not: CAMT\.052/.test(md.querySelector('.bnk-hint')?.textContent || '') && /pending/.test(md.querySelector('.bnk-hint')?.textContent || ''), '#2469: the start hint: CAMT.052 better not, pending only shown');
  md.bnkTake([new w.File([D1], 'tag1.xml'), new w.File([D2], 'tag2.xml')]);
  await until(() => md.querySelector('.bnkprev .ofcrow'), 60);
  check(md.querySelector('.bnk052'), '#2469: the day-report hint in the preview');
  const pr = [...md.querySelectorAll('.bnkprev .ofcrow.pend')];
  check(pr.length === 2 && pr.every(x => /pending – not imported/.test(x.textContent)), '#2469: pending rows marked ' + pr.length);
  check(/Import 2 bookings/.test(md.querySelector('[data-bi="next"]')?.textContent || ''), '#2469: 2 bookings to import (the duplicate and the pending ones left out) ' + (md.querySelector('[data-bi="next"]')?.textContent || ''));
  md.remove();
  w.close();

  // ================= Firefox: the household preview with pending bookings on the phone
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o;
    await o.nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, '390: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + `#budget/${LID}`);
    for (let i = 0; i < 30 && !(await ev(`!!document.querySelector('[data-bg="csv"]')`).catch(() => false)); i++) await sleep(300);
    await ev(`(() => { document.querySelector('[data-bg="csv"]').click(); return 1; })()`);
    for (let i = 0; i < 30 && !(await ev(`!!document.querySelector('.bgdlg [data-cs-file]')`).catch(() => false)); i++) await sleep(300);
    await ev(`(() => { document.querySelector('.modal.bgdlg').bgTake([new File([${JSON.stringify(D1)}], 'tag1.xml'), new File([${JSON.stringify(D2)}], 'tag2.xml')]); return 1; })()`);
    for (let i = 0; i < 30 && !(await ev(`!!document.querySelector('.bgdlg .bgpend')`).catch(() => false)); i++) await sleep(300);
    await sleep(400);
    const g = await ev(`(() => { const c = document.querySelector('.bgdlg .card'); if (!c) return null; const r = c.getBoundingClientRect();
      return {left: r.left, right: r.right, wide: document.documentElement.scrollWidth <= 390, inner: c.scrollWidth <= c.clientWidth + 1, pend: document.querySelectorAll('.bgdlg .bgpendl li').length}; })()`);
    check(g && g.left >= 0 && g.right <= 390 && g.wide && g.inner && g.pend === 2, '390: the preview with pending bookings fits the phone ' + JSON.stringify(g));
    await shot('p2146c-390-pending.png');
  }, true);

  console.log(`p2146_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
