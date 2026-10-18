// 2.89.0 part D UI test (#1916): tables step 2 (static/js/sheets2.js), own container (start.sh), jsdom. Invented names only.
// - the sheet's "…" menu offers "Create tasks from rows…", "Take over as a quotation…" (office on) and "List as rows…"
// - two chosen rows -> tasks: the dialog (list of the space, title column, "only the 2 chosen rows"), the tasks in the list,
//   the mark in the row head, the panel "Carried over"; one undo step takes the tasks back
// - "List as rows": the rows with live task values, then "Fetch new tasks of <list>" in the menu
// - the task's history: "carried over the task from a table" with a link to the table
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P289D_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j._status = r.status; return j; };
const FEAT = 'collab,comments,sheets,office,clients';
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { try { if (await fn()) return true; } catch { /* not yet */ } await sleep(150); } return false; };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const items = d => [...d.querySelectorAll('#pop:not(.hidden) [role="menuitem"]')];

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  await call('PATCH', '/api/settings', {workspace: `org:${ORG}`});
  const L = (await call('POST', '/api/lists', {name: 'Shoot Berlin', org_id: ORG})).id;
  const L2 = (await call('POST', '/api/lists', {name: 'Crew', org_id: ORG})).id;
  for (const t of ['Book the van', 'Call the crew']) await call('POST', '/api/tasks', {title: t, list_id: L2});
  const sh = await call('POST', '/api/sheets', {title: 'Shot list', space: `org:${ORG}`});
  const C = sh.columns.map(c => c.id), R = sh.rows.map(r => r.id);
  await call('PUT', `/api/sheets/${sh.id}/cells`, {cells: [['Opening scene', 'Day 1'], ['Interview', 'Day 2'], ['B-roll', 'Day 3']]
    .flatMap((v, i) => v.map((x, j) => ({row_id: R[i], col_id: C[j], raw: x})))});

  let w = await boot({user: 'alice', hash: 'sheets/' + sh.id}), d = w.document;
  check(await until(() => w.eval('!!SHV.sh') && d.querySelector('#shv-scroll td.shvc')), 'the sheet is open');
  check(w.eval('typeof sh2ToTasks === "function"'), 'sheets2.js is loaded with the tables module');
  const openMenu = async () => { click(w, d.querySelector('[data-shv="menu"]')); return until(() => items(d).length > 2); };
  // the menu entries load the sheet's marks first (office on, lists)
  await openMenu(); w.eval(`closePop && closePop()`); await sleep(300);
  check(await openMenu(), 'the sheet menu opens');
  const labels = items(d).map(b => b.textContent.trim());
  check(labels.some(t => t.includes('Create tasks from rows')), 'menu: Create tasks from rows… ' + labels.join(' | '));
  check(labels.some(t => t.includes('Take over as a quotation')), 'menu: Take over as a quotation… (office on)');
  check(labels.some(t => t.includes('List as rows')), 'menu: List as rows…');
  w.eval(`closePop && closePop()`); await sleep(100);

  // ---- two chosen rows -> tasks
  w.eval(`shvSelect(${R[0]}, ${C[0]}); shvSelect(${R[1]}, ${C[0]}, true)`);
  await openMenu();
  click(w, items(d).find(b => b.textContent.includes('Create tasks from rows')));
  check(await until(() => d.querySelector('.cdlg #sh2-list')), 'the dialog opens');
  const md = d.querySelector('.cdlg');
  check([...md.querySelectorAll('#sh2-list option')].some(o => +o.value === L), 'the dialog offers the list of the space');
  check(/Only the 2 chosen rows/.test(md.textContent), 'only the 2 chosen rows ' + md.textContent.slice(0, 200));
  md.querySelector('#sh2-list').value = String(L);
  click(w, md.querySelector('[data-cd="yes"]'));
  let tl = [];
  check(await until(async () => { tl = (await call('GET', '/api/state')).tasks.filter(t => t.list_id === L); return tl.length === 2; }), 'two tasks in the list ' + tl.map(t => t.title));
  check(tl.map(t => t.title).sort().join() === 'Interview,Opening scene', 'the titles of the chosen rows');
  check(await until(() => d.querySelectorAll('.shvrh .sh2mark').length === 2), 'the two rows carry the mark');
  w.eval(`shvSelect(${R[0]}, ${C[0]})`); await sleep(100);
  check(await until(() => /Carried over/.test(d.querySelector('#shv-side')?.textContent || '')), 'the panel: Carried over (with the task)');
  // the task's history
  const tid = tl.find(t => t.title === 'Opening scene').id;
  const tm = await call('GET', `/api/tasks/${tid}/timeline`);
  const a = (tm.activity || []).find(x => x.kind === 'created');
  const txt = a ? w.eval(`actText(${JSON.stringify(a)}, {})`) : '';
  check(/from a table/.test(txt) && txt.includes(`#sheets/${sh.id}`) && !txt.includes('Shot list'), 'history: carried over from a table, a link, no name ' + txt);
  // one undo step
  await w.eval(`histStep('undo')`);
  check(await until(async () => (await call('GET', '/api/state')).tasks.filter(t => t.list_id === L).length === 0), 'undo: the tasks are gone');
  check(await until(() => !d.querySelector('.shvrh .sh2mark')), 'undo: the marks are gone');

  // ---- list as rows + fetch new tasks
  w.eval(`closePop && closePop()`);
  await openMenu();
  click(w, items(d).find(b => b.textContent.includes('List as rows')));
  check(await until(() => d.querySelector('.cdlg #sh2-src')), 'the list dialog opens');
  d.querySelector('.cdlg #sh2-src').value = String(L2);
  click(w, d.querySelector('.cdlg [data-cd="yes"]'));
  check(await until(() => w.eval(`(SHV.sh.cells || []).filter(c => /^=aufgabe\\.\\d+\\.titel$/.test(c.raw)).length === 2`)), 'two rows with live task titles');
  check(w.eval(`SHV.sh.cells.some(c => c.display === 'Book the van' && c.origin === 'kalmido')`), 'the value comes from Kalmido');
  await call('POST', '/api/tasks', {title: 'Rent lights', list_id: L2});
  await openMenu();
  const fetchItem = items(d).find(b => b.textContent.includes('Fetch new tasks of Crew'));
  check(fetchItem, 'menu: Fetch new tasks of Crew ' + items(d).map(b => b.textContent.trim()).join(' | '));
  click(w, fetchItem);
  check(await until(() => w.eval(`SHV.sh.cells.some(c => c.display === 'Rent lights')`)), 'the new task arrives as a row');

  check(errs.length === 0, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
