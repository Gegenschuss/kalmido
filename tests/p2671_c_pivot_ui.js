// 2.671.0 part C UI test (#3463 b), own container (start.sh): the pivot sheet of a table.
// kalmido-suite: fresh
// The sheet menu of an ordinary sheet offers "New pivot sheet…": the dialog (loaded on demand) proposes rows / values from
// the source, "Create" adds the pivot sheet and opens it: a read-only table with its header, one row per client and the
// totals bold; the tab carries its mark. A change of the source shows in the open pivot by itself (the live way). "Edit
// pivot…" changes the calculation (average), Undo brings the sum back in one step. A pivot sheet draws no grid, no editor.
// 2.693.0 (#5148): its menu offers "Print / PDF…"; the dialog has no cell choice and no browser print, the PDF holds the table.
// P2671C_NOSTART=1 = the server already runs.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2671C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const items = d => [...d.querySelectorAll('#pop [role="menuitem"], .menu-list [role="menuitem"]')];
const FEAT = 'collab,comments,sheets';
const cells = d => [...d.querySelectorAll('#view .spv-grid tbody tr')].map(tr => [...tr.children].map(x => x.textContent.trim()).join('|'));

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const S = await call('POST', '/api/sheets', {title: 'Sales', space: 'private'});
  check(S.status === 201, 'a private table');
  const [CA, CB] = S.columns.map(c => c.id);
  await call('PATCH', `/api/sheets/${S.id}/columns/${CA}`, {title: 'Client'});
  await call('PATCH', `/api/sheets/${S.id}/columns/${CB}`, {title: 'Amount', kind: 'number'});
  const put = (cell, raw) => call('PUT', `/api/sheets/${S.id}/cells`, {cells: [{cell, raw}]});
  for (const [c, v] of [['A1', 'Acme'], ['B1', '10'], ['A2', 'Beta'], ['B2', '5'], ['A3', 'Acme'], ['B3', '7']]) await put(c, v);

  // ================= the sheet menu: "New pivot sheet…", the dialog proposes Client / sum of Amount
  const T2 = await call('POST', `/api/sheets/${S.id}/tabs`, {name: 'Notes'});  // two sheets: the bar shows tabs (and the menu)
  check(T2.status === 201, 'a second sheet');
  const w = await boot({user: 'alice', hash: 'sheets/' + S.id}), d = w.document;
  await until(() => d.querySelector('#view .shvgrid') && d.querySelector('#view .shbtab.on')?.textContent.trim() === 'Sheet 1');
  d.querySelector('#view .shbtab.on')?.click();
  await until(() => items(d).length);
  const pv = items(d).find(b => b.textContent.trim() === 'New pivot sheet…');
  check(pv, 'the sheet menu offers a pivot sheet ' + items(d).map(b => b.textContent.trim()).join(' | '));
  pv?.click();
  const md = await until(() => d.querySelector('.modal .spv-dlg h3'));
  check(md && md.textContent === 'New pivot sheet', 'the pivot dialog');
  check(d.querySelector('.modal [data-spv-row="0"]')?.value === String(CA) && d.querySelector('.modal [data-spv-vcol="0"]')?.value === String(CB)
    && d.querySelector('.modal [data-spv-vagg="0"]')?.value === 'sum', 'it proposes rows Client, the sum of Amount');
  d.querySelector('.modal [data-m="save"]')?.click();
  const P = await until(async () => { const x = await call('GET', `/api/sheets/${S.id}/tabs`); const t = (x.tabs || []).find(t => t.kind === 'pivot'); return t && t.id; });
  check(P, 'a pivot sheet was made');
  check(await until(() => w.location.hash === '#sheets/' + P), 'and opened ' + w.location.hash);
  // ================= the view: read-only table, totals, the tab's mark, no grid
  await until(() => d.querySelector('#view .spv-grid'));
  check(JSON.stringify(cells(d)) === JSON.stringify(['Acme|17', 'Beta|5']), 'one row per client ' + JSON.stringify(cells(d)));
  check([...d.querySelectorAll('#view .spv-grid thead th')].map(x => x.textContent.trim()).join('|') === 'Client|Sum of Amount', 'the header');
  check([...d.querySelectorAll('#view .spv-grid tfoot > tr > *')].map(x => x.textContent.trim()).join('|') === 'Total|22', 'the total row');
  check(!d.querySelector('#view .shvgrid') && !d.querySelector('#view #shv-in'), 'no grid, no formula bar');
  check(d.querySelector('#view .shbtab.on svg') && d.querySelector('#view .shbtab.on')?.textContent.trim() === 'Pivot', 'the tab: Pivot, with its mark');
  // ================= live: a change in the source shows by itself
  await put('B2', '8');
  check(await until(() => JSON.stringify(cells(d)) === JSON.stringify(['Acme|17', 'Beta|8'])), 'a change in the source shows ' + JSON.stringify(cells(d)));
  // ================= edit: average, Undo = the sum again
  const h0 = await w.eval('HIST.undo.length');
  d.querySelector('#view [data-spv="edit"]')?.click();
  const ag = await until(() => d.querySelector('.modal [data-spv-vagg="0"]'));
  ag.value = 'avg'; ag.dispatchEvent(new w.Event('change', {bubbles: true}));
  d.querySelector('.modal [data-m="save"]')?.click();
  check(await until(() => JSON.stringify(cells(d)) === JSON.stringify(['Acme|8.5', 'Beta|8'])), 'the average per client ' + JSON.stringify(cells(d)));
  check(await until(() => w.eval('HIST.undo.length') > h0), 'the change is an Undo step');
  await w.eval(`histStep('undo')`);
  check(await until(() => JSON.stringify(cells(d)) === JSON.stringify(['Acme|17', 'Beta|8'])), 'Undo: the sum again ' + JSON.stringify(cells(d)));
  // ================= 2.693.0 (#5148): print / PDF of the pivot sheet (was: an empty sheet)
  w.eval(`window.__pv = []; pdfView = o => { window.__pv.push(o); }; loadModule = () => Promise.resolve();`);
  d.querySelector('#view [data-spv="menu"]')?.click();
  const pr = await until(() => items(d).find(b => /Print \/ PDF/.test(b.textContent)));
  check(pr, 'the pivot menu offers "Print / PDF…" ' + items(d).map(b => b.textContent.trim()).join(' | '));
  pr?.click();
  const pm = await until(() => d.querySelector('.modal.shpmd'));
  check(pm && !pm.querySelector('input[name="shp-w"]') && !pm.querySelector('button[data-m="quick"]'), 'the print dialog: no cell choice, no browser print');
  pm?.querySelector('button[data-m="pdf"]')?.click();
  check(await until(() => w.eval('window.__pv.length') === 1), 'Show PDF opens the PDF view');
  const pdf = w.eval('window.__pv[0]');
  check(pdf && pdf.data && pdf.data.length > 1000 && !d.querySelector('.modal.shpmd'), 'the PDF of the pivot sheet ' + JSON.stringify({n: pdf?.name, l: pdf?.data?.length}));
  w.close();

  check(errs.length === 0, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
