// 2.140.0 UI tests, part B, own container (start.sh). jsdom:
// #2134 the budget's month comparison: the button below the trend opens cards per category (actual, the difference to the
//       month before marked better / worse, small bars per month), the period 3 / 6 / 12 switches the bars; the CSV import
//       names a recognised bank layout and takes a CAMT file without the column step
// #2136 a device's task panel offers "Add to the office equipment" (dialog: name with the model, net price), then shows the
//       link; the equipment editor of the office shows the link back and offers "Take over as a private device"
// Firefox 390 touch: the comparison fits the phone (no horizontal scrolling), screenshot. Screenshots with P2140B_SHOTS=<dir>.
// freelancer-matrix: n/a - nur Oberflaeche (die Person ohne Organisation prueft p2140_b_api_test.py)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2140_b_ui', check, shots: 'P2140B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2140B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const FEAT = 'collab,contracts,budget,home,office,clients';
const pad = n => String(n).padStart(2, '0');
const NOW = new Date(), MONTH = `${NOW.getFullYear()}-${pad(NOW.getMonth() + 1)}`;
const PREV = (() => { const d = new Date(NOW.getFullYear(), NOW.getMonth() - 1, 1); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}`; })();

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'private'});
  const LID = (await call('POST', '/api/budget/lists', {})).list_id;
  const cats = (await call('GET', `/api/budget/${LID}?month=${MONTH}`)).cats || [];
  const gro = cats.find(c => c.name === 'Groceries');
  await call('POST', `/api/budget/${LID}/entries`, {day: `${PREV}-05`, amount: '80', kind: 'out', title: 'Market', cat_id: gro.id});
  await call('POST', `/api/budget/${LID}/entries`, {day: `${MONTH}-02`, amount: '100', kind: 'out', title: 'Market', cat_id: gro.id});

  // ================= #2134 the month comparison
  let w = await boot({user: 'alice', hash: `budget/${LID}`}), d = w.document;
  await until(() => d.querySelector('.bgview [data-bg="compare"]'), 60);
  check(d.querySelector('.bgview [data-bg="compare"]'), '#2134: the view offers the month comparison');
  click(w, d.querySelector('[data-bg="compare"]'));
  const card = await until(() => [...d.querySelectorAll('.modal.bgdlg .bgcmpc')].find(c => /Groceries/.test(c.textContent)), 60);
  check(card, '#2134: a card for the category');
  check(card && card.querySelector('.bgcd.worse') && /\+/.test(card.querySelector('.bgcd.worse').textContent), '#2134: spending more than the month before is marked worse ' + (card?.textContent || '').trim().slice(0, 160));
  check(card && card.querySelectorAll('.bgcmpm').length === 6, '#2134: six bars by default');
  check(d.querySelector('.modal.bgdlg [data-cmpn="6"][aria-checked="true"]'), '#2134: 6 months chosen');
  click(w, d.querySelector('.modal.bgdlg [data-cmpn="3"]'));
  await until(() => [...d.querySelectorAll('.modal.bgdlg .bgcmpc')].find(c => /Groceries/.test(c.textContent))?.querySelectorAll('.bgcmpm').length === 3);
  check([...d.querySelectorAll('.modal.bgdlg .bgcmpc')].find(c => /Groceries/.test(c.textContent))?.querySelectorAll('.bgcmpm').length === 3, '#2134: 3 months = three bars');
  check(d.querySelector('.modal.bgdlg .bgcmpt .bgcmpc'), '#2134: the totals on top');
  click(w, d.querySelector('.modal.bgdlg [data-m="close"]'));
  await until(() => !d.querySelector('.modal.bgdlg'));

  // the import: a recognised layout, a CAMT file without the column step
  const SPK = '"Auftragskonto";"Buchungstag";"Valutadatum";"Buchungstext";"Verwendungszweck";"Glaeubiger ID";"Mandatsreferenz";"Beguenstigter/Zahlungspflichtiger";"Kontonummer/IBAN";"BIC (SWIFT-Code)";"Betrag";"Waehrung";"Info"\n'
    + '"DE00123";"01.09.26";"01.09.26";"LASTSCHRIFT";"Strom";"";"";"Stadtwerke Beispiel";"DE89370400440532013000";"X";"-45,00";"EUR";""\n';
  const pick = async (name, text) => {
    click(w, d.querySelector('[data-bg="csv"]'));
    await until(() => d.querySelector('.modal.bgdlg [data-cs-file]'));
    w.__csv = [new w.File([text], name, {type: 'text/plain'})];  // like p272_b_budget_ui.js
    w.eval(`(() => { const f = document.querySelector('.modal.bgdlg [data-cs-file]'); Object.defineProperty(f, 'files', {configurable: true, value: window.__csv}); f.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
  };
  await pick('konto.csv', SPK);
  const hint = await until(() => d.querySelector('.modal.bgdlg .bgpreset'), 60);
  check(hint && /Sparkasse/.test(hint.textContent), '#2134: the import names the recognised bank layout ' + (hint?.textContent || ''));
  check(d.querySelector('#cs-date')?.value === '1' && d.querySelector('#cs-df')?.value === 'DD.MM.YY', '#2134: the layout pre-fills the columns and the date format');
  d.querySelector('.modal.bgdlg')?.remove();
  const CAMT = `<?xml version="1.0" encoding="UTF-8"?><Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt><Stmt><Id>S-1</Id>
<Ntry><Amt Ccy="EUR">12.00</Amt><CdtDbtInd>DBIT</CdtDbtInd><BookgDt><Dt>${MONTH}-03</Dt></BookgDt><NtryDtls><TxDtls><RmtInf><Ustrd>Coffee beans</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>
</Stmt></BkToCstmrStmt></Document>`;
  await pick('auszug.xml', CAMT);
  const prow = await until(() => d.querySelector('.modal.bgdlg .bgprev .bgpr'), 60);
  check(prow && /Coffee beans/.test(prow.textContent) && !d.querySelector('#cs-date'), '#2134: a CAMT file goes straight to the rows');
  d.querySelector('.modal.bgdlg')?.remove();
  w.close();

  // ================= #2136 a device -> the own office, the link on both sides
  const dev = await call('POST', '/api/life/devices', {name: 'Kamera', model: 'X100', serial: 'SN-1', price: '1190'});
  check(dev.status === 201, '#2136: a device');
  w = await boot({user: 'alice', hash: `t/${dev.id}`}); d = w.document;
  const take = await until(() => d.querySelector('.dlbox [data-dl="to-office"]'), 80);
  check(take, '#2136: the task panel offers "Add to the office equipment"');
  check(/SN-1/.test(d.querySelector('.lifesec')?.textContent || ''), '#2136: the panel shows the serial number');
  click(w, take);
  const dlg = await until(() => d.querySelector('.modal.dldlg'));
  check(dlg && dlg.querySelector('#dl-name')?.value === 'Kamera X100' && dlg.querySelector('#dl-net')?.value, '#2136: the dialog has the name with the model and a net price');
  if (dlg) { dlg.querySelector('#dl-net').value = '1000'; click(w, dlg.querySelector('[data-m="save"]')); }
  const linked = await until(() => d.querySelector('.dlbox .dllink'), 60);
  check(linked && /Kamera X100/.test(linked.textContent), '#2136: the panel shows the link ' + (d.querySelector('.dlbox')?.textContent || '').trim().slice(0, 120));
  check(d.querySelector('.dlbox [data-dl="pull"]') && d.querySelector('.dlbox [data-dl="unlink"]') && d.querySelector('.dlbox [data-dl="open-eq"]'), '#2136: open, update from there, remove');
  const lk = await call('GET', `/api/life/devices/${dev.id}/link`);
  const EQ = lk.link?.other?.equipment_id;
  check(EQ > 0, '#2136: the equipment exists');
  w.close();

  // the office side: the editor shows the link; a second piece offers the way back
  const eq2 = await call('POST', '/api/office/equipment', {name: 'Licht', serial_no: 'L-1'});
  w = await boot({user: 'alice', hash: 'office/equipment'}); d = w.document;
  const openBtn = await until(() => d.querySelector(`[data-ofc="open"][data-kind="equipment"][data-id="${EQ}"]`), 80);
  click(w, openBtn);
  const lbox = await until(() => d.querySelector('.modal #ast-link .dllink'), 60);
  check(lbox && /Kamera/.test(lbox.textContent), '#2136: the equipment editor shows the linked private device');
  d.querySelector('.modal #ast-link')?.closest('.modal')?.remove();
  click(w, d.querySelector(`[data-ofc="open"][data-kind="equipment"][data-id="${eq2.id}"]`));
  const back = await until(() => d.querySelector('.modal #ast-link [data-ast="dl-take"]'), 60);
  check(back, '#2136: unlinked equipment offers "Take over as a private device"');
  click(w, back);
  await until(() => d.querySelector('.modal #ast-link .dllink'), 60);
  const l2 = await call('GET', `/api/office/equipment/${eq2.id}/link`);
  check(l2.link?.other?.state === 'ok' && d.querySelector('.modal #ast-link .dllink'), '#2136: taken over, the editor shows the new link');
  w.close();

  // ================= Firefox: the comparison on the phone
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o;
    await o.nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, '390: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + `#budget/${LID}`);
    for (let i = 0; i < 30 && !(await ev(`!!document.querySelector('[data-bg="compare"]')`).catch(() => false)); i++) await sleep(300);
    await ev(`(() => { document.querySelector('[data-bg="compare"]').click(); return 1; })()`);
    for (let i = 0; i < 30 && !(await ev(`!!document.querySelector('.bgdlg .bgcmpc')`).catch(() => false)); i++) await sleep(300);
    await sleep(500);
    const g = await ev(`(() => { const c = document.querySelector('.bgdlg .card'); if (!c) return null; const r = c.getBoundingClientRect();
      return {left: r.left, right: r.right, wide: document.documentElement.scrollWidth <= 390, cards: document.querySelectorAll('.bgdlg .bgcmpc').length}; })()`);
    check(g && g.left >= 0 && g.right <= 390 && g.wide && g.cards >= 3, '390: #2134 the comparison fits the phone ' + JSON.stringify(g));
    await shot('p2140b-390-compare.png');
  }, true);

  console.log(`p2140_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
