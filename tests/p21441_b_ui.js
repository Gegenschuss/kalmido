// 2.144.1 UI tests, part B (#2446, #2450, office: the bank import dialog), own container (start.sh, mode workspaces), Firefox,
// English interface. Invented companies, accounts and figures only. freelancer-matrix: office
// - a person without organisation (personal office): "Import bank statement" opens the dialog with the format hint (CAMT.053
//   recommended, CSV, not pending / MT940) and "Choose files"; 360 px wide without sideways scrolling; two CAMT files handed
//   over at once -> one preview naming the two files and their rows; import -> the undo offer in the toast, the undo takes
//   the import back; an MT940 file -> the clear message in the dialog; the cash flow has a button that opens the same dialog
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const TC = require('./testclock');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21441_b_ui', check, shots: 'P21441B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21441B_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients,docs,files';
const T = TC.today();
const P0 = (() => { const [y, m] = T.slice(0, 7).split('-').map(Number); const py = m === 1 ? y - 1 : y, pm = m === 1 ? 12 : m - 1; return `${py}-${String(pm).padStart(2, '0')}`; })();
const IBAN = 'DE02120300000000202051';
const ntry = (amt, ind, day, ref, name) => `<Ntry><Amt Ccy="EUR">${amt}</Amt><CdtDbtInd>${ind}</CdtDbtInd><Sts><Cd>BOOK</Cd></Sts><BookgDt><Dt>${day}</Dt></BookgDt><AcctSvcrRef>${ref}</AcctSvcrRef><NtryDtls><TxDtls><RltdPties><Dbtr><Pty><Nm>${name}</Nm></Pty></Dbtr></RltdPties><RmtInf><Ustrd>Zahlung ${ref}</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>`;
const camt = (ents, bal) => `<?xml version="1.0" encoding="UTF-8"?>\n<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt><Stmt><Id>S1</Id><Acct><Id><IBAN>${IBAN}</IBAN></Id><Ccy>EUR</Ccy></Acct>${bal ? `<Bal><Tp><CdOrPrtry><Cd>CLBD</Cd></CdOrPrtry></Tp><Amt Ccy="EUR">${bal[0]}</Amt><CdtDbtInd>CRDT</CdtDbtInd><Dt><Dt>${bal[1]}</Dt></Dt></Bal>` : ''}${ents.join('')}</Stmt></BkToCstmrStmt></Document>`;
const C1 = camt([ntry('120.00', 'CRDT', `${P0}-05`, 'R-5', 'Kunde Fuenf')]);
const C2 = camt([ntry('80.00', 'CRDT', `${P0}-03`, 'R-3', 'Kunde Drei'), ntry('3.50', 'DBIT', `${P0}-03`, 'K-3', 'Cafe Beispiel')], ['1500.00', `${P0}-03`]);
const MT = ':20:STARTUMS\n:25:12030000/0000202051\n:28C:1/1\n:60F:C261001EUR100,00\n:61:2610011001CR10,00NTRFNONREF\n:62F:C261001EUR110,00\n';

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

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const tab = h => `(() => { location.hash = '${h}'; return 1; })()`;
  const give = files => `(() => { document.querySelector('.modal.bnkdlg').bnkTake([${files.map(([n, t]) => `new File([${JSON.stringify(t)}], ${JSON.stringify(n)})`).join(', ')}]); return 1; })()`;
  const noSide = `(() => { const c = document.querySelector('.modal.bnkdlg .card'); return document.documentElement.scrollWidth <= innerWidth + 1 && c.scrollWidth <= c.clientWidth + 1; })()`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 360, height: 780}});  // the narrowest phone
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'frida');
    await nav(B + '#office/bank');
    check(await ready(ev, `typeof bnkImpModal === 'function' && !!document.querySelector('[data-bnk="imp"]')`, 80), 'the bank tab');
    // #2446: the dialog first, with the hint and "Choose files"
    await ev(`(() => { document.querySelector('[data-bnk="imp"]').click(); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('.modal.bnkdlg .bnk-hint li').length === 3 && !!document.querySelector('.modal.bnkdlg [data-bi="pick"]')`, 40), 'the dialog opens with the hint and "Choose files"');
    const hint = await ev(`document.querySelector('.modal.bnkdlg .bnk-hint')?.textContent || ''`);
    check(/CAMT\.053/.test(hint) && /V2 or V8/.test(hint) && /balance column/.test(hint) && /MT940/.test(hint) && /pending/.test(hint), 'the hint names CAMT.053, CSV and what not to take ' + hint.slice(0, 200));
    check(await ev(`document.querySelector('.modal.bnkdlg .bnk-hint').querySelectorAll('svg.i').length === 3 && !/[\\u{1F300}-\\u{1FAFF}]/u.test(document.querySelector('.modal.bnkdlg .bnk-hint').textContent)`), 'app icons, no emoji');
    check(await ev(noSide), '360 px: no sideways scrolling in the start step');
    await shot('p21441-b-start.png');
    // #2450: two files at once -> one preview
    await ev(give([['tag5.xml', C1], ['tag3.xml', C2]]));
    check(await ready(ev, `document.querySelectorAll('.modal.bnkdlg .bnkprev li').length === 3`, 60), 'one preview with the rows of both files');
    const head = await ev(`document.querySelector('.modal.bnkdlg .card > p.muted')?.textContent || ''`);
    check(/2 files/.test(head) && /3 new/.test(head), 'the preview names the files and the rows: ' + head);
    check(await ev(`[...document.querySelectorAll('.modal.bnkdlg .bnkprev li')].map(l => l.textContent).join('|').includes('tag3.xml')`), 'each row names its file');
    check(await ev(`!!document.querySelector('.modal.bnkdlg .cfb-prev')`), 'the balance of the statement is named');
    check(await ev(noSide), '360 px: no sideways scrolling in the preview');
    await shot('p21441-b-preview.png');
    await ev(`(() => { document.querySelector('.modal.bnkdlg [data-bi="next"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.modal.bnkdlg') && !!document.querySelector('#toast button')`, 60), 'imported: the dialog closes, the toast offers the undo');
    const imps = await call(CF, 'GET', '/api/office/bank/imports');
    check((imps.items || []).length === 1 && imps.items[0].count === 3 && /2 files/.test(imps.items[0].filename), 'one import of two files ' + JSON.stringify(imps.items));
    await ev(`(() => { document.querySelector('#toast button').click(); return 1; })()`);
    let back = false;
    for (let i = 0; i < 40 && !back; i++) { back = !!(await call(CF, 'GET', '/api/office/bank/imports')).items?.[0]?.undone_at; if (!back) await sleep(250); }
    check(back, 'the undo takes the import back');
    // MT940: a clear message instead of the columns
    await ev(`(() => { document.querySelector('[data-bnk="imp"]').click(); return 1; })()`);
    await ready(ev, `!!document.querySelector('.modal.bnkdlg [data-bi="pick"]')`);
    await ev(give([['konto.sta', MT]]));
    check(await ready(ev, `/MT940/.test(document.querySelector('.modal.bnkdlg .aerr')?.textContent || '') && !document.querySelector('.modal.bnkdlg #bi-date')`, 40), 'MT940: the message in the dialog, no column step');
    await ev(`(() => { document.querySelector('.modal.bnkdlg [data-bi="close"]').click(); return 1; })()`);
    // the cash flow opens the same dialog
    await ev(tab('#office/cashflow'));
    check(await ready(ev, `!!document.querySelector('[data-cfb-imp]')`, 80), 'the cash flow offers "Import bank statement"');
    await ev(`(() => { document.querySelector('[data-cfb-imp]').click(); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('.modal.bnkdlg .bnk-hint li').length === 3`, 40), 'the same dialog with the hint');
    await ev(give([['tag3.xml', C2]]));
    check(await ready(ev, `!!document.querySelector('.modal.bnkdlg [data-bi="next"]')`, 60), 'the preview from the cash flow');
    await ev(`(() => { document.querySelector('.modal.bnkdlg [data-bi="next"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.modal.bnkdlg') && /Account balance according to the bank/.test(document.querySelector('.cfb-box')?.textContent || '')`, 80), 'imported from the cash flow: it loads again with the bank balance');
    check(await ev(`!!document.querySelector('.cfb-box [data-cfb-imp]')`), 'the bank box keeps the import button');
  }, false);

  console.log(`p21441_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
