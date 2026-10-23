// 2.199.0 C (#2742) UI tests: tables in folders (sheetfold.js). Own container (start.sh), jsdom. Invented names only.
// - a computer: the tables' panel has one entry per workspace (Private, the organisation) of the shared tree; below it the
//   folders (ns 'sh', draggable, take drops, a menu: New folder…, New table, Share…, Rename…, Move to the trash), the
//   tables in no folder, and a project as an automatic group (other look, no drag / drop / menu); a table dragged onto a
//   folder lands in it (server); one workspace chosen: only its entry
// - the overview: the folders as cards, a table in a folder only there; #sheets/f/<id> lists the folder's subfolders and
//   tables; "New table" there makes it in that folder
// - a phone: the overview shows the folder cards, a tap opens the folder
// freelancer-matrix: n/a (the routes run in p2199_c_sheets_test.py, also for a person without an organisation)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2199C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const rowOf = (d, txt) => [...d.querySelectorAll('#side .sbbt')].find(r => r.querySelector('.sbbtn .n')?.textContent === txt);
const menuItems = d => [...d.querySelectorAll('#pop:not(.hidden) [role="menuitem"] .ml')].map(x => x.textContent);
function dnd(w, from, to, y) {  // a mouse drag of node from onto node to at height y (0..1) of it
  to.getBoundingClientRect = () => ({top: 100, height: 20, left: 0, width: 200, right: 200, bottom: 120});
  const ev = (type, el) => { const e = new w.MouseEvent(type, {bubbles: true, cancelable: true, clientY: 100 + y * 20}); Object.defineProperty(e, 'dataTransfer', {value: {setData() {}, types: [], effectAllowed: '', dropEffect: ''}}); el.dispatchEvent(e); return e; };
  ev('dragstart', from); const over = ev('dragover', to); ev('drop', to); ev('dragend', from);
  return over.defaultPrevented;
}
const openRow = async (d, name) => { const a = rowOf(d, name)?.querySelector('[data-act="sbb-tree"]'); if (a && !a.dataset.open) a.click(); await sleep(150); };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Example Studio', lang: 'en', collab_all: true});
  const st0 = await call('GET', '/api/state');
  const ORG = (st0.me.workspaces || [])[0]?.id;
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'files', 'sheets'])].join(',');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: feats});
  const P = (await call('POST', '/api/lists', {name: 'Launch'})).id;
  const fold = async (name, b) => (await call('POST', '/api/sheets/folders', {name, space: 'private', ...b})).folder?.id;
  const FB = await fold('Budgets'), FQ = await fold('Quarter one', {parent_id: FB}), FO = await fold('Studio plans', {space: 'org:' + ORG});
  const tbl = async (title, b) => (await call('POST', '/api/sheets', {title, space: 'private', ...b})).id;
  const T1 = await tbl('Travel', {folder_id: FB}), T2 = await tbl('Loose ends'), T3 = await tbl('Crew', {list_id: P}), T4 = await tbl('Org budget', {space: 'org:' + ORG, folder_id: FO});
  check(ORG && FB && FQ && FO && T1 && T2 && T3 && T4, 'setup ' + JSON.stringify({ORG, FB, FQ, FO, T1, T2, T3, T4}));

  // ================= a computer: the panel
  let w = await boot({user: 'alice', hash: 'sheets'}), d = w.document;
  const roots = await until(() => { const r = [...d.querySelectorAll('#side .sbbt[data-sbbns="sh"][data-sbbid^="r:"]')]; return r.length === 2 && r; });
  check(roots && roots.map(r => r.dataset.sbbid).join() === `r:private,r:org:${ORG}`, 'one entry per workspace ' + (roots || []).map(r => r.dataset.sbbid).join());
  const B1 = await until(() => rowOf(d, 'Budgets'));
  check(B1 && B1.dataset.sbbid === 'f' + FB && B1.dataset.sbbpar === 'r:private' && B1.getAttribute('draggable') === 'true' && B1.dataset.sbbdrop === '1' && B1.dataset.sbbmenu === '1',
    'a folder: ns / id / par, draggable, takes drops, has a menu');
  check(rowOf(d, 'Loose ends')?.dataset.sbbid === 't' + T2 && !rowOf(d, 'Travel'), 'a table in no folder under the workspace, the filed one inside its (closed) folder');
  const auto = rowOf(d, 'Launch');
  check(auto && auto.classList.contains('sbbauto') && !auto.dataset.sbbns && !auto.hasAttribute('draggable'), 'the project: an automatic group without drag / menu');
  await openRow(d, 'Budgets');
  check(await until(() => rowOf(d, 'Travel') && rowOf(d, 'Quarter one')), 'the folder opens: its subfolder and its table');
  check(rowOf(d, 'Quarter one').dataset.sbbpar === 'f' + FB && rowOf(d, 'Travel').dataset.sbbpar === 'f' + FB, 'their parent is the folder');
  check(rowOf(d, 'Studio plans')?.dataset.sbbpar === `r:org:${ORG}`, 'the organisation\'s folder under its entry');
  // drag a table onto a folder
  check(dnd(w, rowOf(d, 'Loose ends'), rowOf(d, 'Budgets'), 0.5), 'a folder takes the dragged table');
  check(await until(async () => ((await call('GET', '/api/sheets?space=all')).sheets || []).find(x => x.id === T2)?.folder_id === FB), 'the table is now in Budgets (server)');
  // the menu of a folder (right-click) and of the automatic group (none)
  rowOf(d, 'Budgets').querySelector('.sbbtn').dispatchEvent(new w.MouseEvent('contextmenu', {bubbles: true, cancelable: true}));
  let mi = await until(() => menuItems(d).length && menuItems(d));
  check(mi && ['New folder…', 'New table', 'Share…', 'Rename…', 'Move to the trash'].every(x => mi.includes(x)), 'the folder\'s menu ' + JSON.stringify(mi));
  w.eval('typeof closePop === "function" && closePop()');
  d.body.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
  await sleep(150);
  rowOf(d, 'Launch').querySelector('.sbbtn').dispatchEvent(new w.MouseEvent('contextmenu', {bubbles: true, cancelable: true}));
  await sleep(300);
  check(!menuItems(d).includes('Share…') && !menuItems(d).includes('Rename…'), 'the automatic group has no menu');
  w.close();

  // one workspace chosen: only its entry
  await call('PATCH', '/api/settings', {workspace: 'private'});
  w = await boot({user: 'alice', hash: 'sheets'}); d = w.document;
  const one = await until(() => d.querySelector('#side .sbbt[data-sbbid="r:private"]'));
  check(one && !d.querySelector(`#side .sbbt[data-sbbid="r:org:${ORG}"]`), 'only the chosen workspace\'s entry');
  w.close();
  await call('PATCH', '/api/settings', {workspace: 'all'});

  // ================= the overview: folder cards, one folder, a new table in it
  w = await boot({user: 'alice', hash: 'sheets'}); d = w.document;
  check(await until(() => d.querySelector(`#view .shfcard[data-fid="${FB}"]`)), 'the overview: the folder as a card');
  check(!d.querySelector(`#view .shvcard[data-id="${T1}"]`) && d.querySelector(`#view .shvcard[data-id="${T3}"]`), 'a filed table only in its folder, the others as before');
  w.location.hash = '#sheets/f/' + FB;
  check(await until(() => d.querySelector(`#view .shvcard[data-id="${T1}"]`) && d.querySelector(`#view .shfcard[data-fid="${FQ}"]`)), 'the folder: its table and its subfolder');
  check(/Budgets/.test(d.querySelector('#view .shvh')?.textContent || ''), 'the folder\'s name as the title');
  d.querySelector(`#view [data-shf="new"][data-id="${FB}"]`)?.click();
  const inp = await until(() => d.querySelector('.modal input:not([type="checkbox"])'));
  if (inp) {
    inp.value = 'Made in Budgets';
    (d.querySelector('.modal .btn.pri') || d.querySelector('.modal [data-m="ok"]'))?.click();
  }
  check(await until(async () => ((await call('GET', '/api/sheets?space=all')).sheets || []).find(x => x.title === 'Made in Budgets')?.folder_id === FB), 'New table in the folder lands in it');
  w.close();

  // ================= a phone: the folder cards, a tap opens the folder
  w = await boot({user: 'alice', hash: 'sheets', mobile: true}); d = w.document;
  const card = await until(() => d.querySelector(`#view .shfcard[data-fid="${FB}"] a`));
  check(card, 'phone: the folder as a card');
  card?.click();
  check(await until(() => w.location.hash === '#sheets/f/' + FB && d.querySelector(`#view .shvcard[data-id="${T1}"]`)), 'phone: a tap opens the folder ' + w.location.hash);
  w.close();

  console.log(`p2199_c_sheets_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
