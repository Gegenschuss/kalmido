// 2.124.0 part B UI test (#2110 #2111 #2112): column kinds checkbox / person / link / file, rows / columns kept in view,
// print and the history (static/js/sheetkinds.js), own container (start.sh), jsdom. Invented names only.
// - checkbox: a click on the box ticks it at once (one undo step), Space on the chosen cell too; a second tap on the phone
// - person: Enter opens the people who may see the table, the pick shows picture + name
// - link: typed like text, www. gets https://, the arrow opens in a new tab (noopener noreferrer)
// - file: uploaded into the cell (the name shows, the arrow opens it), Undo empties the cell again
// - column / row menu "Keep … in view up to here": saved, sticky rules for those rows / columns, released again
// - the panel: "History of the cell" (who, before -> after), "Recent changes"; "Print / PDF…" builds the print view
const path = require('path');
const fs = require('fs');
const {execFileSync} = require('child_process');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2124B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j._status = r.status; return j; };
const FEAT = 'collab,comments,sheets';
const until = (fn, n) => require('./boot').until(async () => { try { return await fn(); } catch { return false; } }, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const key = (w, el, k, o = {}) => el && el.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true, ...o}));
const items = d => [...d.querySelectorAll('#pop [role="menuitem"]')];

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  const BOB = (await call('POST', '/api/users', {orgs: [ORG], username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'})).id;
  const CB = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, CB);

  // ---- static: the new rules in rem, transitions only opacity / transform
  const css = fs.readFileSync(path.join(__dirname, '..', 'static', 'css', 'sheets.css'), 'utf8');
  const mine = css.slice(css.indexOf('2.124.0 B (#2110)')).replace(/\/\*[\s\S]*?\*\//g, '');
  check(mine.length > 100 && !(mine.replace(/@media[^{]*\{/g, '').match(/(\d+(\.\d+)?)px/g) || []).some(x => parseFloat(x) > 2), 'sheets.css (2.124.0 B): rem sizes');
  check([...mine.matchAll(/transition:([^;}]+)/g)].every(m => m[1] === 'none' || m[1].split(',').every(p => /^\s*(transform|opacity)\s/.test(p))), 'sheets.css (2.124.0 B): transitions only opacity');

  const S0 = await call('POST', '/api/sheets', {title: 'Kit', space: `org:${ORG}`});
  const SID = S0.id, R = S0.rows.map(r => r.id);
  const col = {};
  for (const k of ['checkbox', 'person', 'link', 'file']) col[k] = (await call('POST', `/api/sheets/${SID}/columns`, {title: k, kind: k})).column.id;
  const get = async () => call('GET', `/api/sheets/${SID}`);
  const cellOf = (sh, r, c) => (sh.cells || []).find(x => x.row_id === r && x.col_id === c);

  let w = await boot({user: 'alice', hash: 'sheets/' + SID}), d = w.document;
  check(await until(() => w.eval('!!SHV.sh') && d.querySelector('#shv-scroll td.shvc')), 'the table opens');
  const td = (r, c) => d.getElementById(`shv-c-${r}-${c}`);
  const sc = () => d.getElementById('shv-scroll');
  check(w.eval(`SHV_KINDS.map(k => k[0]).join()`).endsWith('checkbox,person,link,file'), 'the column dialog offers the new kinds');

  // ---- checkbox
  const box = () => td(R[0], col.checkbox)?.querySelector('[data-shkbox]');
  check(box() && box().getAttribute('role') === 'checkbox' && box().getAttribute('aria-checked') === 'false', 'an empty checkbox cell shows an empty box');
  click(w, box());
  check(await until(async () => cellOf(await get(), R[0], col.checkbox)?.raw === '1'), 'a click on the box ticks it');
  check(await until(() => box()?.classList.contains('on') && box()?.getAttribute('aria-checked') === 'true'), 'the box shows the tick');
  await w.eval(`histStep('undo')`);
  check(await until(async () => !(cellOf(await get(), R[0], col.checkbox)?.raw)), 'undo: the tick is gone (one step)');
  w.eval(`shvSelect(${R[1]}, ${col.checkbox})`); sc().focus();
  key(w, sc(), ' ');
  check(await until(async () => cellOf(await get(), R[1], col.checkbox)?.raw === '1'), 'Space on the chosen checkbox ticks it');
  check(!d.getElementById('shv-ed'), 'no text editor for a checkbox');

  // ---- person
  w.eval(`shvSelect(${R[0]}, ${col.person})`); sc().focus();
  key(w, sc(), 'Enter');
  check(await until(() => items(d).some(b => b.textContent.includes('Bob'))), 'Enter on a person cell: the people as a menu');
  check(items(d).some(b => b.textContent.includes('Alice')), 'the menu has the members of the organisation');
  click(w, items(d).find(b => b.textContent.includes('Bob')));
  check(await until(async () => cellOf(await get(), R[0], col.person)?.raw === String(BOB)), 'the pick is stored as the account id');
  check(await until(() => td(R[0], col.person)?.querySelector('.shkav') && /Bob/.test(td(R[0], col.person).textContent)), 'the cell shows picture + name');

  // ---- link
  w.eval(`shvSelect(${R[0]}, ${col.link})`); sc().focus();
  key(w, sc(), 'w');
  const ed = d.getElementById('shv-ed');
  check(ed, 'a link cell is typed like text');
  ed.value = 'www.example.com/kit'; key(w, ed, 'Enter');
  check(await until(async () => cellOf(await get(), R[0], col.link)?.raw === 'https://www.example.com/kit'), 'www. gets https://');
  const a = await until(() => td(R[0], col.link)?.querySelector('a.shklnk')) && td(R[0], col.link).querySelector('a.shklnk');
  check(a && a.getAttribute('href') === 'https://www.example.com/kit' && a.target === '_blank' && a.rel === 'noopener noreferrer', 'the arrow opens the link in a new tab (noopener noreferrer)');
  check(/example\.com\/kit/.test(td(R[0], col.link).textContent) && !/https:/.test(td(R[0], col.link).querySelector('.shvv').textContent), 'the address shortened');
  w.eval(`shvSelect(${R[1]}, ${col.link})`); sc().focus();
  key(w, sc(), 'j'); const ed2 = d.getElementById('shv-ed'); ed2.value = 'javascript:alert(1)'; key(w, ed2, 'Enter');
  await sleep(600);
  check(!cellOf(await get(), R[1], col.link), 'javascript: is refused');

  // ---- file
  await w.eval(`shk_upload(${R[0]}, ${col.file}, new File(['%PDF-1.4 kit'], 'kit.pdf', {type: 'application/pdf'}))`);
  check(await until(async () => /^file:\d+$/.test(cellOf(await get(), R[0], col.file)?.raw || '')), 'a file uploaded into the cell');
  check(await until(() => /kit\.pdf/.test(td(R[0], col.file)?.textContent || '') && td(R[0], col.file).querySelector('a.shklnk[href^="/api/sheets/"]')), 'the cell shows the name and opens the file');
  w.eval(`shvSelect(${R[0]}, ${col.file})`); sc().focus(); key(w, sc(), 'Enter');
  check(await until(() => items(d).some(b => b.textContent.includes('Remove file'))), 'Enter on a file cell: replace / open / download / remove');
  w.eval('closePop()');
  await w.eval(`histStep('undo')`);
  check(await until(async () => !(cellOf(await get(), R[0], col.file)?.raw)), 'undo: the cell is empty again');
  await w.eval(`histStep('redo')`);
  check(await until(async () => /^file:\d+$/.test(cellOf(await get(), R[0], col.file)?.raw || '')), 'redo: the file is back');

  // ---- rows / columns kept in view
  const head = d.querySelector(`#shv-scroll th[data-c="${S0.columns[1].id}"] .shvchb`);
  w.eval(`shvColMenu(${S0.columns[1].id}, document.querySelector('#shv-scroll th[data-c="${S0.columns[1].id}"] .shvchb'))`);
  check(head && items(d).some(b => b.textContent.includes('Keep columns in view up to here')), 'the column menu: keep columns in view');
  click(w, items(d).find(b => b.textContent.includes('Keep columns in view up to here')));
  check(await until(async () => (await get()).freeze_cols === 2), 'two columns kept (saved)');
  const st = () => d.getElementById('shk-fix')?.textContent || '';
  check(await until(() => st().includes(`th[data-c="${S0.columns[1].id}"]{position:sticky;left:`)), 'the kept columns are sticky ' + st().slice(0, 160));
  w.eval(`shvRowMenu(${R[0]}, document.querySelector('#shv-scroll th.shvrh[data-r="${R[0]}"] button'))`);
  click(w, items(d).find(b => b.textContent.includes('Keep rows in view up to here')));
  check(await until(async () => (await get()).freeze_rows === 1), 'the first row kept');
  check(await until(() => st().includes(`tr[data-id="${R[0]}"]>*{position:sticky;top:`)), 'the kept row is sticky');
  w.eval('shvRender()'); await sleep(300);
  check(st().includes('position:sticky'), 'still sticky after a redraw');
  await w.eval(`histStep('undo')`);
  check(await until(async () => (await get()).freeze_rows === 0), 'undo: the row released');
  check(await until(() => !st().includes(`tr[data-id="${R[0]}"]`)), 'and no longer sticky');

  // ---- history + recent changes
  w.eval(`shvSelect(${R[1]}, ${col.checkbox})`); w.eval('shvSideSync()');
  check(await until(() => d.querySelector('#shv-side [data-shh="cell"]')), 'the panel offers the history of the cell');
  click(w, d.querySelector('#shv-side [data-shh="cell"]'));
  check(await until(() => d.querySelector('.modal.shhmd .shhlist li')), 'the history dialog');
  const li = d.querySelector('.modal.shhmd .shhlist li');
  check(li && /Alice/.test(li.textContent) && /Yes/.test(li.querySelector('.shhchg').textContent), 'who and before -> after ' + (li && li.textContent));
  click(w, d.querySelector('.modal.shhmd [data-m="close"]'));
  await sleep(300);
  await w.eval(`shh_open(null)`);
  check(await until(() => d.querySelectorAll('.modal.shhmd .shhlist li').length >= 4), 'recent changes of the table');
  check(d.querySelector('.modal.shhmd [data-shh-go]'), 'an entry leads to its cell');
  click(w, d.querySelector('.modal.shhmd [data-shh-go]'));
  check(!d.querySelector('.modal.shhmd') && w.eval('!!SHV.cur'), 'the cell chosen, the dialog closed');

  // ---- print
  let printed = 0; w.print = () => { printed++; };
  w.eval('shk_print()');
  check(d.body.classList.contains('shkprint') && d.querySelectorAll('#shk-print tbody tr').length === R.length, 'the print view: every shown row');
  check(await until(() => printed === 1), 'the print dialog opens');
  check(/Kit/.test(d.querySelector('#shk-print h1')?.textContent || '') && /Bob/.test(d.querySelector('#shk-print tbody').textContent), 'title and values in the print view');
  await sleep(600);  // 2.138.4 (#2370): an afterprint right after print() is the early Android one and keeps the view; a desktop one comes later
  w.dispatchEvent(new w.Event('afterprint'));
  check(!d.getElementById('shk-print') && !d.body.classList.contains('shkprint'), 'after printing: the view is gone');
  w.close();

  // ---- phone: a tap on the box ticks it at once; a reader cannot tick
  w = await boot({user: 'bob', hash: 'sheets/' + SID, mobile: true}); d = w.document;
  check(await until(() => w.eval('!!SHV.sh') && d.getElementById(`shv-c-${R[2]}-${col.checkbox}`)?.querySelector('[data-shkbox]')), 'phone: the box is there');
  click(w, d.getElementById(`shv-c-${R[2]}-${col.checkbox}`).querySelector('[data-shkbox]'));
  check(await until(async () => cellOf(await get(), R[2], col.checkbox)?.raw === '1'), 'phone: one tap on the box ticks it');
  w.close();

  check(errs.length === 0, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
