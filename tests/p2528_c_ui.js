// kalmido-suite: fresh
// 2.528.0 C (#4306 B22) UI: the trash of tables (static/js/sheets.js shxTrashDlg / shxSheetTrashDlg), own container (start.sh),
// jsdom. A person without an organisation (frida) - invented names only.
// - the overview's menu offers "Trash": the deleted table with when it went there and the trash period; Restore brings it back
//   (it is in the overview again), "Delete permanently…" asks first and then it is gone for good
// - a table's menu offers "Deleted rows and columns": the deleted row with its input, the deleted column with its title;
//   Restore puts each back into the table
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2528C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j._status = r.status; return j; };
const until = fn => require('./boot').until(async () => { try { return await fn(); } catch { return false; } }, {timeout: 15000, step: 150});
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const item = (d, re) => [...d.querySelectorAll('[role="menuitem"]')].find(b => re.test(b.textContent));
const dlg = d => d.querySelector('.modal.shx-dlg');
const rowOf = (d, id, k) => dlg(d)?.querySelector(`${k ? `[data-shxk="${k}"]` : ''}[data-shxid="${id}"]`);  // a row and a column may share an id

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true}, CA);
  const fr = await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []}, CA);
  check(fr._status < 300, 'setup: frida without an organisation ' + fr._status);
  CK = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'collab,comments,sheets'});
  const S1 = await call('POST', '/api/sheets', {title: 'Budget', space: 'private'});
  const d1 = await call('GET', `/api/sheets/${S1.id}`);
  const RB = d1.rows[1].id, CB = d1.columns[1].id;
  await call('PUT', `/api/sheets/${S1.id}/cells`, {cells: [{row_id: RB, col_id: d1.columns[0].id, raw: 'Rent'}]});
  await call('PATCH', `/api/sheets/${S1.id}/columns/${CB}`, {title: 'Amount'});
  check((await call('DELETE', `/api/sheets/${S1.id}/rows/${RB}`))._status === 200 && (await call('DELETE', `/api/sheets/${S1.id}/columns/${CB}`))._status === 200,
    'setup: a row and a column in the trash');
  const S2 = await call('POST', '/api/sheets', {title: 'Old plan', space: 'private'});
  check((await call('DELETE', `/api/sheets/${S2.id}`))._status === 200, 'setup: a table in the trash');

  // ---- the overview: Trash
  let w = await boot({user: 'frida', hash: 'sheets'}), d = w.document;
  check(await until(() => d.querySelector('[data-shv="omenu"]')), 'the overview has its menu');
  click(w, d.querySelector('[data-shv="omenu"]'));
  check(await until(() => item(d, /^\s*Trash\s*$/)), 'the overview menu offers Trash');
  click(w, item(d, /^\s*Trash\s*$/));
  check(await until(() => rowOf(d, S2.id)), 'the trash shows the deleted table');
  const t = rowOf(d, S2.id);
  check(/Old plan/.test(t?.textContent) && /Moved to the trash on/.test(t?.textContent), 'with its name and when it went there: ' + t?.textContent);
  check(/deleted permanently after 30 days|stay in the trash until/.test(dlg(d)?.textContent || ''), 'the trash period is named');
  click(w, t.querySelector('[data-shx="restore"]'));
  check(await until(async () => (await call('GET', `/api/sheets/${S2.id}`))._status === 200 && !rowOf(d, S2.id)), 'Restore brings the table back and it leaves the trash');
  check(await until(() => /Trash is empty/.test(dlg(d)?.textContent || '')), 'the trash is empty then');
  click(w, dlg(d).querySelector('[data-shx="close"]'));
  check(await until(() => !dlg(d) && [...d.querySelectorAll('.shvcard')].some(c => /Old plan/.test(c.textContent))), 'the table is in the overview again');
  await call('DELETE', `/api/sheets/${S2.id}`);
  click(w, d.querySelector('[data-shv="omenu"]'));
  await until(() => item(d, /^\s*Trash\s*$/));
  click(w, item(d, /^\s*Trash\s*$/));
  check(await until(() => rowOf(d, S2.id)?.querySelector('[data-shx="purge"]')), 'the table is in the trash again, with Delete permanently');
  click(w, rowOf(d, S2.id).querySelector('[data-shx="purge"]'));
  const cd = await until(() => d.querySelector('.modal.cdlg [data-cd="yes"]') && d.querySelector('.modal.cdlg'));
  check(cd && /permanently/.test(cd.textContent) && /cannot be undone/.test(cd.textContent), 'Delete permanently asks first');
  click(w, cd?.querySelector('[data-cd="yes"]'));
  check(await until(() => !rowOf(d, S2.id)), 'it leaves the trash');
  check((await call('POST', `/api/sheets/${S2.id}/restore`))._status === 404, '... and is gone for good');
  w.close();

  // ---- a table: Deleted rows and columns
  w = await boot({user: 'frida', hash: 'sheets/' + S1.id}); d = w.document;
  check(await until(() => d.querySelector('[data-shv="menu"]')), 'the table is open');
  click(w, d.querySelector('[data-shv="menu"]'));
  check(await until(() => item(d, /Deleted rows and columns/)), "the table's menu offers Deleted rows and columns");
  click(w, item(d, /Deleted rows and columns/));
  check(await until(() => rowOf(d, RB, 'row') && rowOf(d, CB, 'col')), 'the deleted row and column are listed');
  check(/Rent/.test(rowOf(d, RB, 'row')?.textContent) && /Amount/.test(rowOf(d, CB, 'col')?.textContent), 'the row with its input, the column with its title');
  click(w, rowOf(d, RB, 'row').querySelector('[data-shx="restore"]'));
  check(await until(async () => (await call('GET', `/api/sheets/${S1.id}`)).rows.some(r => r.id === RB) && !rowOf(d, RB, 'row')), 'Restore puts the row back');
  click(w, rowOf(d, CB, 'col').querySelector('[data-shx="restore"]'));
  check(await until(async () => (await call('GET', `/api/sheets/${S1.id}`)).columns.some(c => c.id === CB)), 'Restore puts the column back');
  check(await until(() => /Nothing of this table is in the trash/.test(dlg(d)?.textContent || '')), 'nothing of the table left in the trash');
  w.close();

  console.log(`p2528_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error('Error', e); process.exit(1); });
