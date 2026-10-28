// 2.148.0 UI tests, part D (#2458, office: the DATEV import), own container (start.sh, mode workspaces), Firefox. Invented
// companies, accounts and figures only (EXTF files written here). freelancer-matrix: office
// - a person without organisation (personal office): the DATEV settings show "Read DATEV data" and an empty suppliers list;
//   the dialog takes a master data file, shows the preview (2 new, the rows with their kind) and only then allows
//   "Take over"; after it the suppliers list shows the creditor; the undo in the toast takes the import back
// - a wrong file: the preview shows the reason, "Take over" stays off
// - the bookkeeping shows "Opening balances <year>" once a booking batch brought some (nothing before)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const TC = require('./testclock');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const {undoToast} = require('./ff');
const firefox = require('./ff')({tag: 'p2148_d_ui', check, shots: 'P2148D_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2148D_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients,docs,files';
const Y = +TC.today().slice(0, 4);
const head = (cat, name, ver) => { const f = ['"EXTF"', '700', String(cat), `"${name}"`, String(ver), '20260101120000000', '', '"RE"', '""', '""', '1234567', '12345', `${Y}0101`, '4']; while (f.length < 31) f.push(''); return f.join(';'); };
const F16 = [head(16, 'Debitoren/Kreditoren', 5), '"Konto";"Name (Adressatentyp Unternehmen)";"Ort"', '10020;"Kundin Beispiel GmbH";"Leipzig"', '70020;"Papier Muster KG";"Halle"'].join('\r\n') + '\r\n';
const F21 = [head(21, 'Buchungsstapel', 13), '"Umsatz (ohne Soll/Haben-Kz)";"Soll/Haben-Kennzeichen";"Konto";"Gegenkonto (ohne BU-Schlüssel)";"Belegdatum";"Buchungstext"',
  '2500,00;"S";1200;9000;0101;"EB Bank"'].join('\r\n') + '\r\n';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  // the person without organisation (tests/freelancer_fixture.py does the same in Python)
  const fu = await call(CA, 'POST', '/api/users', {username: 'erin', display_name: 'Erin', password: 'password123', email: 'erin@example.com', orgs: []});
  check(fu.http < 300, 'a person without organisation ' + fu.http);
  const CE = await login('erin');
  await call(CE, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(((await call(CE, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'erin is in no organisation');

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const give = (text, name) => `(() => { const i = document.querySelector('.modal #dimp-file'); const dt = new DataTransfer(); dt.items.add(new File([${JSON.stringify(text)}], '${name}', {type: 'text/csv'})); i.files = dt.files; i.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`;
  const sup = cond => `fetch('/api/office/datev/suppliers', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => ${cond})`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});  // a phone first
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'erin');
    // the bookkeeping before: no opening balances
    await nav(B + '#office/books');
    check(await ready(ev, `typeof bkTabHtml === 'function' && !!document.querySelector('.bk-bar')`, 80), 'the bookkeeping is shown');
    await sleep(800);
    check(await ev(`!document.querySelector('.dimpob')`), 'without an import: no opening balances section');
    // the DATEV settings: the button and the empty suppliers list
    await ev(`(() => { location.hash = '#office/settings'; return 1; })()`);
    check(await ready(ev, `!!document.querySelector('details.dxset')`, 80), 'the DATEV settings block');
    await ev(`(() => { const d = document.querySelector('details.dxset'); d.open = true; d.scrollIntoView({block: 'start'}); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.dxset [data-dimp="open"]') && /No suppliers yet/.test(document.querySelector('#dimp-sup')?.textContent || '')`, 60),
      '"Read DATEV data" and the empty suppliers list');
    // a wrong file: the reason, no "Take over"
    await ev(`(() => { document.querySelector('.dxset [data-dimp="open"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal #dimp-file')`, 40), 'the dialog opens');
    check(await ev(`document.querySelector('.modal [data-m="ok"]').disabled`), 'no file: "Take over" is off');
    await ev(give('Konto;Name\r\n1;x\r\n', 'falsch.csv'));
    check(await ready(ev, `/EXTF/.test(document.querySelector('.modal #dimp-pv .aerr')?.textContent || '')`, 60), 'a wrong file: the reason in the dialog');
    check(await ev(`document.querySelector('.modal [data-m="ok"]').disabled`), 'a wrong file: "Take over" stays off');
    // the master data file: preview, then take over
    await ev(give(F16, 'stammdaten.csv'));
    check(await ready(ev, `/2 new/.test(document.querySelector('.modal .dimpsum')?.textContent || '')`, 60),
      'the preview: 2 new ' + await ev(`document.querySelector('.modal #dimp-pv')?.textContent.replace(/\\s+/g, ' ') || ''`));
    check(await ev(`document.querySelectorAll('.modal .dimprows li').length === 2 && /Supplier/.test(document.querySelector('.modal .dimprows').textContent) && /Client/.test(document.querySelector('.modal .dimprows').textContent)`),
      'two rows: a client and a supplier');
    check(await ev(`!document.querySelector('.modal [data-m="ok"]').disabled`), '"Take over" is on');
    check(await ready(ev, sup('j.items.length === 0')), 'the preview wrote nothing');
    await shot('p2148-d-preview.png');
    await ev(`(() => { document.querySelector('.modal [data-m="ok"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.itc-dlg [data-cd="yes"]')`, 40), '2.356.0 B (#2934): the import names its target first');
    await ev(`(() => { document.querySelector('.itc-dlg [data-cd="yes"]').click(); return 1; })()`);
    check(await ready(ev, sup(`j.items.length === 1 && j.items[0].account_no === '70020'`), 60), 'taken over: one supplier');
    check(await ready(ev, `!document.querySelector('.modal #dimp-file') && /Papier Muster KG/.test([...document.querySelectorAll('#dimp-sup input')].map(i => i.value).join('|'))`, 60),
      'the dialog closed, the suppliers list shows the creditor');
    check(await ev(`/1 new|2 new/.test(document.querySelector('#toast')?.textContent || '')`), 'the toast names the result');
    await shot('p2148-d-suppliers.png');
    await undoToast(ev, /(1|2) new/);  // 2.312.0 A (#3283)
    check(await ready(ev, sup('j.items.length === 0'), 60), 'the undo in the toast takes the import back');
    check(await ready(ev, `/No suppliers yet/.test(document.querySelector('#dimp-sup')?.textContent || '')`, 60), 'the list is empty again');
    // a booking batch (over the API) -> the bookkeeping shows the opening balances of the year
    const fd = new FormData(); fd.append('file', new Blob([F21], {type: 'text/csv'}), 'stapel.csv');
    const ck = CE;
    const up = await fetch(B + 'api/office/datev/import', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: ck}, body: fd});
    check(up.status === 201, 'a booking batch imported ' + up.status);
    await ev(`(() => { if (typeof DIMP === 'object') DIMP.ob = {}; location.hash = '#office/books'; return 1; })()`);
    check(await ready(ev, `new RegExp('Opening balances ${Y}').test(document.querySelector('.dimpob')?.textContent || '') && /1200/.test(document.querySelector('.dimpob').textContent)`, 80),
      'the bookkeeping shows the opening balances of the year ' + await ev(`document.querySelector('.dimpob')?.textContent.replace(/\\s+/g, ' ') || ''`));
    await ev(`(() => { document.querySelector('.dimpob')?.scrollIntoView({block: 'start'}); return 1; })()`);
    await shot('p2148-d-opening.png');
  }, false);

  console.log(`p2148_d_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
