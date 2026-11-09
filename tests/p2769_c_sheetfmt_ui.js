// 2.769.0 part C UI test (#5351: decimal places and an own currency per table column)
// kalmido-suite: fresh
// Own container (start.sh; P2769CU_NOSTART=1: the server already runs), jsdom. Invented names only. As a person without an
// organisation (frida) in her private table with a number and a currency column:
// - the column dialog of a number column offers "Decimal places" (Automatic, 0-4), no currency; a text column neither
// - 2 places chosen there and saved: the cell shows 1,234.57 (the value stays 1234.5678)
// - a currency column offers its own currency (first entry: the table's); USD chosen: the cell shows $1,234.56
// - the group subtotal of the columns (sheetgroup.js shg_fmt) follows them; no script errors
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2769CU_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j._status = r.status; return j; };
const until = (fn, n) => require('./boot').until(async () => { try { return await fn(); } catch { return false; } }, {timeout: n ? n * 150 : 15000, step: 150});
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const pick = (w, el, v) => { if (!el) return; el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const AK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true}, AK);
  const fr = await call('POST', '/api/users', {orgs: [], username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com'}, AK);
  check(fr.id, 'a person without an organisation');
  CK = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'collab,comments,sheets'});
  const S = await call('POST', '/api/sheets', {title: 'Fees', space: 'private'});
  check(S._status === 201, 'a private table ' + JSON.stringify(S).slice(0, 120));
  const SID = S.id, [CA, CB, CC] = S.columns.map(c => c.id), R1 = S.rows[0].id;
  await call('PATCH', `/api/sheets/${SID}/columns/${CA}`, {title: 'Hours', kind: 'number'});
  await call('PATCH', `/api/sheets/${SID}/columns/${CB}`, {title: 'Fee', kind: 'currency'});
  const m = await call('PUT', `/api/sheets/${SID}/cells`, {cells: [{cell: 'A1', raw: '1234.5678'}, {cell: 'B1', raw: '1234.56'}]});
  check(m._status === 200, 'two numbers ' + JSON.stringify(m).slice(0, 160));

  const w = await boot({user: 'frida', hash: 'sheets/' + SID}), d = w.document;
  const shown = cid => d.querySelector(`#shv-c-${R1}-${cid} .shvv`)?.textContent || '';
  check(await until(() => shown(CA) === '1,234.5678' && shown(CB) === '€1,234.56'), 'automatic as before ' + shown(CA) + ' / ' + shown(CB));

  // a text column: no number settings
  w.eval(`shvColModal(SHV.sh._col.get(${CC}))`);
  let md = await until(() => d.querySelector('.modal.shvcmd'));
  check(md && !md.querySelector('#shv-cd') && !md.querySelector('#shv-cc'), 'a text column has no decimal places / currency');
  click(w, md?.querySelector('[data-m="close"]'));
  await until(() => !d.querySelector('.modal.shvcmd'));

  // the number column: decimal places, no currency; 2 chosen
  w.eval(`shvColModal(SHV.sh._col.get(${CA}))`);
  md = await until(() => d.querySelector('.modal.shvcmd'));
  const opts = [...(md?.querySelectorAll('#shv-cd option') || [])].map(o => o.textContent);
  check(JSON.stringify(opts) === JSON.stringify(['Automatic', '0', '1', '2', '3', '4']) && md.querySelector('#shv-cd').value === '', 'decimal places: Automatic, 0-4 ' + JSON.stringify(opts));
  check(!md?.querySelector('#shv-cc'), 'a number column has no currency');
  pick(w, md?.querySelector('#shv-cd'), '2');
  click(w, md?.querySelector('[data-m="save"]'));
  check(await until(() => shown(CA) === '1,234.57'), 'saved: the cell shows 2 places ' + shown(CA));
  const sv = await call('GET', `/api/sheets/${SID}`);
  check(sv.columns.find(c => c.id === CA)?.dec === 2 && sv.cells.find(c => c.addr === 'A1')?.value === 1234.5678, 'stored: dec 2, the value full');

  // the currency column: places and its own currency, the first entry is the table's
  w.eval(`shvColModal(SHV.sh._col.get(${CB}))`);
  md = await until(() => d.querySelector('.modal.shvcmd') && d.querySelector('.modal.shvcmd #shv-cc') && d.querySelector('.modal.shvcmd'));
  const curs = [...(md?.querySelectorAll('#shv-cc option') || [])];
  check(curs[0]?.textContent === 'Table currency (EUR)' && curs[0]?.value === '' && curs.some(o => o.value === 'USD'), 'currency: the table\'s first, USD to choose ' + curs.slice(0, 3).map(o => o.textContent).join(', '));
  pick(w, md?.querySelector('#shv-cc'), 'USD');
  click(w, md?.querySelector('[data-m="save"]'));
  check(await until(() => shown(CB) === '$1,234.56'), 'saved: the cell shows dollars ' + shown(CB));
  check(shown(CA) === '1,234.57', 'the other column keeps its places');

  // the group subtotals follow the column
  const fmt = (cid, v) => w.eval(`shg_fmt(SHV.sh, SHV.sh._col.get(${cid}), ${v}, 'sum')`);
  check(await until(() => w.eval(`SHV.sh._col.get(${CB})?.cur === 'USD'`)), 'the client knows the column\'s currency');
  check(fmt(CA, 2469.1356) === '2,469.14', 'subtotal of Hours with 2 places ' + fmt(CA, 2469.1356));
  check(/^(US)?\$10\.00$/.test(fmt(CB, 10)), 'subtotal of Fee in dollars (the locale may write US$) ' + fmt(CB, 10));
  check(!errs.length, 'no script errors ' + JSON.stringify(errs).slice(0, 300));
  w.close();

  console.log(`p2769_c_sheetfmt_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
