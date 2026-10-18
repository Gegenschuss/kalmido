// 2.89.0 part C UI test (#1916): tables to and from files (static/js/sheetsio.js hooked into sheets.js), own container
// (start.sh), jsdom. Invented names only.
// - the table's menu offers "Export as CSV" / "Export as Excel (.xlsx)": the download link points at the export, the file
//   has the values (CSV) / is an .xlsx
// - the overview's menu offers "Import CSV or Excel…": a chosen CSV becomes a new table in the overview's space, opened at
//   once, the toast says what was imported; Undo moves it to the trash, Redo brings it back
// - the overview of a list's tables imports attached to that list
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P289C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j._status = r.status; return j; };
const FEAT = 'collab,comments,sheets';
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { try { if (await fn()) return true; } catch { /* not yet */ } await sleep(150); } return false; };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const item = (d, re) => [...d.querySelectorAll('[role="menuitem"]')].find(b => re.test(b.textContent));

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  const L = (await call('POST', '/api/lists', {name: 'Shoot Hamburg', org_id: ORG})).id;
  const S = await call('POST', '/api/sheets', {title: 'Gear list', space: `org:${ORG}`});
  check(S._status === 201, 'setup: a table ' + S._status);
  await call('PUT', `/api/sheets/${S.id}/cells`, {cells: [{cell: 'A1', raw: 'Camera'}, {cell: 'B1', raw: '1200'}, {cell: 'C1', raw: '=B1*2'}]});

  let w = await boot({user: 'alice', hash: 'sheets/' + S.id}), d = w.document;
  check(typeof w.shxUiExport === 'function' && typeof w.shxUiImport === 'function', 'sheetsio.js is loaded with the tables view');
  const dl = [];
  w.HTMLAnchorElement.prototype.click = function () { dl.push(this.getAttribute('href')); };  // no navigation in jsdom
  check(await until(() => d.querySelector('[data-shv="menu"]')), 'the table is open');
  click(w, d.querySelector('[data-shv="menu"]'));
  check(await until(() => item(d, /Export as CSV/) && item(d, /Export as Excel/)), "the table's menu: export CSV and Excel");
  click(w, item(d, /Export as CSV/));
  check(dl[0] === `/api/sheets/${S.id}/export.csv`, 'CSV: the download link ' + dl[0]);
  const csv = await (await fetch(B + dl[0].slice(1), {headers: {Cookie: CK}})).text();
  check(/Camera/.test(csv) && /2400/.test(csv), 'CSV: values, formulas as their result ' + csv.slice(0, 120));
  click(w, d.querySelector('[data-shv="menu"]')); await until(() => item(d, /Export as Excel/));
  click(w, item(d, /Export as Excel/));
  check(dl[1] === `/api/sheets/${S.id}/export.xlsx`, 'xlsx: the download link ' + dl[1]);
  const xl = Buffer.from(await (await fetch(B + dl[1].slice(1), {headers: {Cookie: CK}})).arrayBuffer());
  check(xl.slice(0, 2).toString() === 'PK', 'xlsx: a zip file');
  w.close();

  // ---- import from the overview
  w = await boot({user: 'alice', hash: 'sheets'}); d = w.document;
  const picked = [];
  w.HTMLInputElement.prototype.click = function () { picked.push(this); };
  check(await until(() => d.querySelector('[data-shv="omenu"]')), 'the overview has a menu for the import');
  click(w, d.querySelector('[data-shv="omenu"]'));
  check(await until(() => item(d, /Import CSV or Excel/)), 'the overview menu: import');
  click(w, item(d, /Import CSV or Excel/));
  const inp = picked[0];
  check(inp && inp.type === 'file' && /\.xlsx/.test(inp.accept) && /\.csv/.test(inp.accept), 'a file chooser for CSV and xlsx');
  Object.defineProperty(inp, 'files', {configurable: true, value: [new w.File(['Item;Price\r\nTripod;80,50\r\nLight;120\r\n'], 'Rental.csv')]});
  inp.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(() => /^#sheets\/\d+$/.test(w.location.hash) && +w.location.hash.split('/')[1] !== S.id), 'the new table opens ' + w.location.hash);
  const NID = +w.location.hash.split('/')[1];
  const nt = await call('GET', `/api/sheets/${NID}`);
  check(nt.title === 'Rental' && nt.space === `org:${ORG}` && nt.columns.map(c => c.title).join() === 'Item,Price', 'imported: title, space, columns ' + JSON.stringify([nt.title, nt.space]));
  check((nt.cells || []).some(c => c.addr === 'B1' && c.value === 80.5), 'imported: the decimal comma read');
  check(/2 rows and 2 columns imported/.test(d.querySelector('#toast')?.textContent || ''), 'the toast says what was imported ' + (d.querySelector('#toast')?.textContent || ''));
  w.eval(`histStep('undo')`);
  check(await until(async () => (await call('GET', `/api/sheets/${NID}`))._status === 404), 'Undo: the imported table is in the trash');
  await sleep(300); w.eval(`histStep('redo')`);
  check(await until(async () => (await call('GET', `/api/sheets/${NID}`))._status === 200), 'Redo: it is back');
  w.close();

  // ---- the tables of a list: the import is attached to it
  w = await boot({user: 'alice', hash: 'sheets/l/' + L}); d = w.document;
  const picked2 = [];
  w.HTMLInputElement.prototype.click = function () { picked2.push(this); };
  check(await until(() => d.querySelector('[data-shv="omenu"]')), "a list's tables: the menu");
  click(w, d.querySelector('[data-shv="omenu"]')); await until(() => item(d, /Import CSV or Excel/));
  click(w, item(d, /Import CSV or Excel/));
  Object.defineProperty(picked2[0], 'files', {configurable: true, value: [new w.File(['Day,Place\r\n1,Harbour\r\n'], 'Plan.csv')]});
  picked2[0].dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(() => /^#sheets\/\d+$/.test(w.location.hash)), 'opened');
  const pt = await call('GET', `/api/sheets/${+w.location.hash.split('/')[1]}`);
  check(pt.list_id === L && pt.title === 'Plan', 'imported into the list ' + JSON.stringify([pt.list_id, pt.title]));
  w.close();

  check(!errs().length, 'no script errors ' + errs().slice(0, 3).join(' | '));
  console.log(`p289_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
