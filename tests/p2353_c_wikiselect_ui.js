// kalmido-suite: fresh
// 2.353.0 C (#2829, audit B 2) UI tests: "Select" in the knowledge lists (wiki.js wk_sel*): the file store's selection bar
// next to "New folder". Own container (start.sh), jsdom, invented names only.
// - a computer (the folder's list): Select shows a box per folder / page row and the bar (count, Select all, Move to…, Move
//   to the trash); a page and a folder chosen -> Move to… offers the folders (not the chosen one) -> both lie in the target
//   (the server writes the paths), ONE undo step brings them back
// - a page and a folder into the trash at once (its page with it; ONE undo step restores all), the selection ends after each action
// - a phone (the tree list): Select shows the boxes too, a page chosen moves into a folder
// freelancer-matrix: wiki (a person without an organisation: their private knowledge; the routes are the file store's
// order / trash / restore, run with organisations in p2200_a_wiki_folder_test.py)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2353C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const menuItems = d => [...d.querySelectorAll('#pop:not(.hidden) [role="menuitem"]')];
const idx = async () => call('GET', '/api/wiki?space=private');
const pathOf = async id => (await call('GET', '/api/wiki/pages/' + id)).path;
const boxOf = (d, txt) => [...d.querySelectorAll('#view .wkrow')].find(r => r.querySelector(':scope > .wkitem, :scope > details > summary > .wkitem')?.textContent.trim() === txt)?.querySelector(':scope > .absel input[data-wksel="one"]');
const tick = (w, el) => { el.checked = true; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const barText = d => d.querySelector('#view #wk-sbar .mcount')?.textContent || '';  // 2.428.0 (#3581): the shared bar

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const st0 = await call('GET', '/api/state');
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'wiki', 'files'])].join(',');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: feats});
  const id = {};
  for (const [k, p] of [['one', 'Alpha/One'], ['loose', 'Loose'], ['g1', 'Gone one'], ['g2', 'Bin/Inner'], ['ph', 'Phone page']]) id[k] = (await call('POST', '/api/wiki/pages', {space: 'private', path: p, body: 'Text of ' + p})).id;
  const ft = await call('POST', '/api/wiki/folders', {space: 'private', name: 'Target'});
  check(ft.http === 201 && Object.values(id).every(Boolean), 'setup: pages and an empty folder ' + ft.http);

  // ================= a computer: the folder's list
  let w = await boot({user: 'alice', hash: 'wiki'}), d = w.document;
  const sb = await until(() => d.querySelector('#view [data-wksel="mode"]'));
  check(!!sb && sb.previousElementSibling?.dataset.wk === 'newfolder' && /Select/.test(sb.textContent), '"Select" stands next to "New folder"');
  check(!d.querySelector('#view .wkselrow'), 'no shown boxes before Select');  // 2.428.0 (#3581): they wait hidden for the hover
  sb?.click();
  check(await until(() => boxOf(d, 'Alpha') && boxOf(d, 'Loose') && boxOf(d, 'Target')), 'Select: a box per folder and page row');
  check(/Tap pages/.test(barText(d)) && d.querySelector('#view #wk-sbar [data-wksel="move"]')?.disabled, 'the bar: nothing chosen, Move off');
  tick(w, boxOf(d, 'Loose'));
  await until(() => /1 selected/.test(barText(d)));
  tick(w, boxOf(d, 'Alpha'));
  check(await until(() => /2 selected/.test(barText(d)) && !d.querySelector('#view #wk-sbar [data-wksel="move"]').disabled), 'two chosen, Move to… on');
  check(boxOf(d, 'Loose')?.checked && boxOf(d, 'Alpha')?.checked, 'the boxes stay ticked after the redraw');
  d.querySelector('#view #wk-sbar [data-wksel="move"]').click();
  let mi = await until(() => menuItems(d).length && menuItems(d));
  const names = (mi || []).map(x => x.textContent.trim());
  check(names.some(x => /Target/.test(x)) && !names.some(x => /^Alpha$/.test(x)), 'Move to… offers the folders, not a chosen one ' + JSON.stringify(names));
  (mi || []).find(x => /Target/.test(x.textContent))?.click();
  check(await until(async () => (await pathOf(id.loose)) === 'Target/Loose' && (await pathOf(id.one)) === 'Target/Alpha/One', 60), 'the page and the folder (with its page) lie in Target');
  check(await until(() => !d.querySelector('#view #wk-sbar') && !d.querySelector('#view .wkselrow')), 'the selection ends after moving');
  check(w.eval(`/Move to/.test(HIST.undo[HIST.undo.length - 1]?.label || '')`), 'moving = one undo step');
  await w.eval(`histStep('undo')`);
  check(await until(async () => (await pathOf(id.loose)) === 'Loose' && (await pathOf(id.one)) === 'Alpha/One', 60), 'Undo brings both back');
  // two pages into the trash
  (await until(() => d.querySelector('#view [data-wksel="mode"]')))?.click();
  await until(() => boxOf(d, 'Gone one') && boxOf(d, 'Bin'));
  tick(w, boxOf(d, 'Gone one'));
  await until(() => /1 selected/.test(barText(d)));
  tick(w, boxOf(d, 'Bin'));
  await until(() => /2 selected/.test(barText(d)));
  const n0 = w.eval('HIST.undo.length');
  d.querySelector('#view #wk-sbar [data-wksel="trash"]').click();
  check(await until(async () => { const p = (await idx()).pages || []; return !p.some(x => x.id === id.g1 || x.id === id.g2) && p.some(x => x.id === id.loose); }, 60),
    'the page and the folder (with its page) are in the trash, the others stay');
  check(await until(() => w.eval('HIST.undo.length') === n0 + 1), 'the trash = one undo step');
  await w.eval(`histStep('undo')`);
  check(await until(async () => { const p = (await idx()).pages || []; return p.some(x => x.id === id.g1) && p.some(x => x.id === id.g2); }, 60), 'Undo restores the page and the folder with its page');
  // "Select all" ticks every row of the list
  (await until(() => d.querySelector('#view [data-wksel="mode"]')))?.click();
  (await until(() => d.querySelector('#view #wk-sbar [data-wksel="all"]')))?.click();
  check(await until(() => [...d.querySelectorAll('#view [data-wksel="one"]')].every(x => x.checked) && /Select none/.test(d.querySelector('#view [data-wksel="all"]')?.textContent || '')),
    'Select all ticks every row');
  d.querySelector('#view #wk-sbar [data-wksel="close"]').click();
  check(await until(() => !d.querySelector('#view .wkselrow')), 'X ends the selection');
  w.close();

  // ================= a phone: the tree list
  w = await boot({user: 'alice', hash: 'wiki', mobile: true}); d = w.document;
  (await until(() => d.querySelector('#view [data-wksel="mode"]')))?.click();
  check(await until(() => boxOf(d, 'Phone page') && boxOf(d, 'Target')), 'a phone: Select shows the boxes in the list');
  tick(w, boxOf(d, 'Phone page'));
  await until(() => /1 selected/.test(barText(d)));
  d.querySelector('#view #wk-sbar [data-wksel="move"]').click();
  mi = await until(() => menuItems(d).length && menuItems(d));
  (mi || []).find(x => /Target/.test(x.textContent))?.click();
  check(await until(async () => (await pathOf(id.ph)) === 'Target/Phone page', 60), 'a phone: the page moved into the folder');
  w.close();

  console.log(`p2353_c_wikiselect_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
