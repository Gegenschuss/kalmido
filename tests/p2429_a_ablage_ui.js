// kalmido-suite: fresh
// 2.429.0 (#3580) the file store shows only its own folders: no root folder of the knowledge pages / tables in the list,
// the read-only collection "From Knowledge" after the folders (lock badge, no menu, not draggable); opened (#ablage/aus-wiki)
// it lists the page's file under the page's title (a link to the page), with a download link and no delete. The space's
// name in the path goes back to the top. Own container (start.sh), jsdom.
// freelancer-matrix: files - frida has no organisation: everything in her private workspace.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const until = async (f, ms = 6000) => { for (let t = 0; t < ms; t += 100) { if (f()) return true; await sleep(100); } return !!f(); };
const FEAT = 'cal,comments,collab,files,wiki,sheets';
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==', 'base64');

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  const me = (await call(CA, 'GET', '/api/state')).me;
  await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(fu.http < 300 && ((await call(CF, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'P4: frida is in no organisation');

  await call(CF, 'POST', '/api/files/folders', {space: 'private', name: 'Taxes'});
  check((await call(CF, 'POST', '/api/wiki/folders', {space: 'private', name: 'Handbook'})).http === 201, 'setup: a knowledge folder');
  const pg = await call(CF, 'POST', '/api/wiki/pages', {space: 'private', path: 'Handbook/Start', body: 'Welcome'});
  check(pg.http === 201 && pg.id, 'setup: a page');
  const fd = new FormData(); fd.append('file', new Blob([PNG], {type: 'image/png'}), 'plan.png');
  const up = await fetch(B + `api/wiki/pages/${pg.id}/files`, {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CF}, body: fd});
  check(up.ok, 'setup: a file on the page ' + up.status);
  check((await call(CF, 'POST', '/api/sheets/folders', {space: 'private', name: 'Customers'})).http === 201, 'setup: a folder of the tables');

  // (1) the top of "My files": the own folder, no area roots, the collection after it
  let w = await boot({user: 'frida', hash: 'ablage'}), d = w.document;
  const names = () => [...d.querySelectorAll('#view .ablist .abrow .abname')].map(e => e.textContent);
  check(await until(() => names().includes('Taxes') && names().includes('From Knowledge')), 'frida: Taxes and From Knowledge in the list ' + JSON.stringify(names()));
  check(!names().includes('Knowledge') && !names().includes('Tables'), 'frida: no root folder of the knowledge pages / tables ' + JSON.stringify(names()));
  const row = d.querySelector('#view .abrow.abcoll[data-abcoll="wiki"]');
  check(!!row && !row.querySelector('[data-ab="menu"]') && row.getAttribute('draggable') !== 'true' && !!row.querySelector('.abbadge'), 'the collection: read-only (no menu, not draggable, lock badge)');
  check(names().indexOf('From Knowledge') > names().indexOf('Taxes'), 'the collection after the folders');

  // (2) opened: grouped by the page, a link to it, a download, no delete
  row.querySelector('.abopen').click();
  check(await until(() => w.eval('S.route.aus') === 'wiki' && !!d.querySelector('#view .abcollg')), 'the collection opens (#ablage/aus-wiki) ' + w.location.hash);
  const h = d.querySelector('#view .abcollh [data-go]');
  check(h?.textContent === 'Start' && h?.dataset.go === `wiki/${pg.id}`, 'the group: the page title, a link to the page');
  const f = d.querySelector('#view .abcollg .abrow');
  check(f?.querySelector('.abname')?.textContent === 'plan.png', 'the page\'s file');
  check((f?.querySelector('a[download]')?.getAttribute('href') || '').includes('/api/wiki/files/'), 'a download link of the knowledge route');
  check(!d.querySelector('#view .abcollg [data-ab="menu"], #view .abcollg [data-ab="delete"]'), 'no menu, no delete in the collection');
  check((d.querySelector('#view .abcollnote')?.textContent || '').includes('Delete them on the page itself'), 'the note: deleting stays on the page');
  check(!d.querySelector('#view [data-ab="upload"], #view [data-ab="new-folder"]'), 'no upload / new folder in the collection');

  // (3) the space's name in the path: back to the top
  d.querySelector('#view .abcrumbs [data-ab="space"]').click();
  check(await until(() => !w.eval('S.route.aus') && names().includes('Taxes')), 'back at the top of My files');
  w.close();

  console.log(`p2429_a_ablage_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
