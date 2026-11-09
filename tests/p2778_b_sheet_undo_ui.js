// 2.778.0 UI test, part B (#5253): a table's step in "Recent steps" (static/js/undolist.js) - seen, taken back, redone.
// kalmido-suite: fresh
// jsdom, fresh container. Invented names only. alice writes a cell of her table "from another device" (straight to the server
// with X-Kalmido-Device-Name: Laptop (Test)):
//  - the account menu's "Recent steps" lists the table's step: label with the table's name, area Tables, the device
//  - "Back up to here" takes it back: the server has the former input, the row says Undone and offers Redo
//  - the table opened afterwards shows the former input; Back from the list returns to the view before
//  - Redo brings the new input again
// The waits are on states (rows, values on the server, the hash), never on a fixed time.
const {boot, errs, B, login, until: until0} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DEV = {'X-Kalmido-Device-Name': 'Laptop (Test)'};
const until = (fn, ms) => until0(fn, {timeout: ms || 20000, step: 100});
const call = async (ck, method, url, body, hd = {}) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...hd, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', features: 'sheets,wiki,comments', tour: 'done', workspace: 'private'});
  const S = await call(CA, 'POST', '/api/sheets', {title: 'Household', space: 'private'});
  check(S.id, `a table (${S.http} ${S.error || ''})`);
  const a1 = async () => ((await call(CA, 'GET', `/api/sheets/${S.id}`)).cells || []).find(c => c.addr === 'A1')?.raw || '';
  await call(CA, 'PUT', `/api/sheets/${S.id}/cells`, {cells: [{cell: 'A1', raw: 'Rent 700'}]}, DEV);
  await call(CA, 'PUT', `/api/sheets/${S.id}/cells`, {cells: [{cell: 'A1', raw: 'Rent 750'}]}, DEV);
  const g = (await call(CA, 'GET', '/api/undo')).items?.[0] || {};
  check(g.area === 'sheets' && g.label === 'Changed: Household' && await a1() === 'Rent 750', `the server lists the table step ${JSON.stringify(g)}`);

  const w = await boot({user: 'alice', hash: 'today'}); const d = w.document;
  const row = () => d.querySelector(`#view .ulbody .ulrow[data-ul="s:${g.id}"]`);
  d.querySelector('[data-act="user-menu"]').click();
  const item = await until(() => [...d.querySelectorAll('#pop:not(.hidden) .menu-list button')].find(b => /Recent steps/.test(b.textContent)));
  check(item, 'the account menu has "Recent steps"');
  item.click();
  check(await until(() => w.location.hash === '#steps' && row()), 'the page lists the table step');
  const t = row()?.textContent || '';
  check(/Changed: Household/.test(t) && /Tables/.test(t) && /Laptop \(Test\)/.test(t), `the row: label with the table's name, area Tables, device: ${t}`);
  row().querySelector('[data-ul-go]').click();
  check(await until(async () => await a1() === 'Rent 700' && !w.eval('UL.busy')), 'Back up to here: the former input on the server');
  check(await until(() => row()?.classList.contains('ulundone') && row().querySelector('[data-ul-redo]')), 'the row says Undone and offers Redo');
  w.history.back();
  check(await until(() => w.location.hash !== '#steps' && !d.querySelector('#view .ulpage')), `Back returns to the view before (${w.location.hash})`);
  w.location.hash = 'sheets/' + S.id;
  check(await until(() => [...d.querySelectorAll('#shv-scroll td.shvc')].some(td => td.textContent.trim() === 'Rent 700')), 'the table shows the former input');
  w.location.hash = 'steps';
  check(await until(() => row()?.querySelector('[data-ul-redo]')), 'the list again, Redo offered');
  row().querySelector('[data-ul-redo]').click();
  check(await until(async () => await a1() === 'Rent 750' && !w.eval('UL.busy')), 'Redo: the new input again');
  w.close();

  check(!errs.length, 'no script errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`p2778_b_sheet_undo_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
