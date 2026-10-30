// 2.319 (#3287) UI tests: a click on a page in the knowledge panel's tree keeps the tree open. Own container (start.sh), jsdom.
// - "All workspaces": the space, the folders above the page and the page's own folder stay open, the page is marked --
//   while the page still loads (the old page is the loaded one) and after it has loaded (the panel is drawn again)
// - one workspace chosen above: the same without the space's root node
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2319A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const root = (d, sp) => d.querySelector(`#side .sbbt[data-wksp="${sp}"]`);
const rowOf = (d, txt) => [...d.querySelectorAll('#side .sbbt')].find(r => r.querySelector('.sbbtn .n')?.textContent === txt);
const isOpen = r => !!r && !r.classList.contains('closed');
const pageName = d => d.querySelector('#view .wkpage')?.getAttribute('aria-label') || '';
// the page loads slowly: the panel is drawn while WK.pg is still the old page
const slow = w => w.eval(`(() => { const o = wk_loadPage; wk_loadPage = async (id, f) => { await new Promise(r => setTimeout(r, 1500)); return o(id, f); }; })()`);

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const st0 = await call('GET', '/api/state');
  const og = await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: st0.me.id});
  check(og.http < 300, 'the organisation Alpha ' + og.http);
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'wiki'])].join(',');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: feats, workspace: 'all'});
  const ORG = (await call('GET', '/api/state')).me.workspaces?.[0]?.id, OS = 'org:' + ORG;
  const id = {};
  for (const [k, p] of [['top', 'Wiki/Top'], ['gear', 'Wiki/Audio/Eurorack/Gear'], ['coll', 'Wiki/Audio/Eurorack/Collection']]) id[k] = (await call('POST', '/api/wiki/pages', {space: 'private', path: p, body: 'Text of ' + p})).id;
  for (const [k, p] of [['proc', 'Team/Process'], ['inner', 'Team/Deep/Inner']]) id[k] = (await call('POST', '/api/wiki/pages', {space: OS, path: p, body: 'Text of ' + p})).id;
  check(Object.values(id).every(Boolean), 'setup: the pages');

  // ================= "All workspaces": from the folder's list, then from another page
  let w = await boot({user: 'alice', hash: 'wiki/s/private/d/Wiki/Audio/Eurorack'}), d = w.document;
  check(await until(() => rowOf(d, 'Eurorack')), 'the folder Eurorack open: the path down to it in the panel');
  rowOf(d, 'Eurorack').querySelector('[data-act="sbb-tree"]').click();
  check(await until(() => rowOf(d, 'Gear')), 'the arrow of Eurorack shows Gear');
  rowOf(d, 'Collection').querySelector('.sbbtn').click();
  check(await until(() => pageName(d) === 'Collection'), 'Collection is the loaded page');
  w.eval(`LS.set('sbbOpen', [])`);  // only the automatic opening keeps the tree open now
  slow(w);
  rowOf(d, 'Gear').querySelector('.sbbtn').click();
  check(await until(() => w.location.hash === '#wiki/' + id.gear), 'the click opens Gear ' + w.location.hash);
  await sleep(300);
  check(w.eval('WK.pg && WK.pg.id') === id.coll, 'while loading: the old page is still the loaded one');
  const tree = () => isOpen(root(d, 'private')) && isOpen(rowOf(d, 'Wiki')) && isOpen(rowOf(d, 'Audio')) && isOpen(rowOf(d, 'Eurorack')) && rowOf(d, 'Gear')?.classList.contains('on');
  check(tree(), 'while loading: the space, Wiki, Audio and Eurorack stay open, Gear is marked');
  check(await until(() => pageName(d) === 'Gear'), 'Gear has loaded');
  await sleep(200);
  check(tree() && rowOf(d, 'Eurorack')?.classList.contains('on'), 'loaded: the tree stays open, the page\'s folder and the page marked');
  check(!rowOf(d, 'Collection')?.classList.contains('on'), 'loaded: only the open page is marked');
  w.close();
  // a reload of the page's address: the panel opens down to it once the page is there
  w = await boot({user: 'alice', hash: 'wiki/' + id.gear}); d = w.document;
  check(await until(() => pageName(d) === 'Gear' && isOpen(root(d, 'private')) && isOpen(rowOf(d, 'Eurorack')) && rowOf(d, 'Gear')?.classList.contains('on')), 'reload of a page: the panel open down to it');
  check(!isOpen(root(d, OS)), 'reload of a page: the other space stays closed');
  w.close();

  // ================= one workspace chosen above
  await call('PATCH', '/api/settings', {workspace: OS});
  w = await boot({user: 'alice', hash: 'wiki/' + id.proc}); d = w.document;
  check(await until(() => pageName(d) === 'Process' && isOpen(rowOf(d, 'Team')) && rowOf(d, 'Process')?.classList.contains('on')), 'one workspace: the page\'s folder open, the page marked');
  rowOf(d, 'Deep').querySelector('[data-act="sbb-tree"]').click();
  check(await until(() => rowOf(d, 'Inner')), 'one workspace: the arrow of Deep shows Inner');
  w.eval(`LS.set('sbbOpen', [])`);  // only the automatic opening keeps the tree open now
  slow(w);
  rowOf(d, 'Inner').querySelector('.sbbtn').click();
  check(await until(() => w.location.hash === '#wiki/' + id.inner), 'one workspace: the click opens Inner');
  await sleep(300);
  check(w.eval('WK.pg && WK.pg.id') === id.proc && isOpen(rowOf(d, 'Team')) && isOpen(rowOf(d, 'Deep')) && rowOf(d, 'Inner')?.classList.contains('on'), 'one workspace, while loading: Team and Deep open, Inner marked');
  check(await until(() => pageName(d) === 'Inner'), 'one workspace: Inner has loaded');
  await sleep(200);
  check(isOpen(rowOf(d, 'Team')) && isOpen(rowOf(d, 'Deep')) && rowOf(d, 'Inner')?.classList.contains('on'), 'one workspace, loaded: the tree stays open');
  w.close();
  await call('PATCH', '/api/settings', {workspace: 'all'});

  console.log(`p2319_a_wiki_tree_open_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
