// 2.152.5 (#2699) UI tests (own container, start.sh). jsdom, phone width:
// - a folder opened by hand in the knowledge tree (more than 30 pages = all closed by themselves) stays open after
//   opening a page and going Back; closing it by hand keeps it closed after the next page and Back
// - the keys are the ones of the computer panel (LS sbbOpen 'wk:<space>:<path>')
// freelancer-matrix: wiki (the pages are in the private space of a person without an organisation)
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21525A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  CK = await login('frida');
  const st0 = await call('GET', '/api/state');
  check(!(st0.me.workspaces || []).length, 'setup: frida has no organisation');
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'wiki'])].join(',');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: feats});
  const ids = [];
  for (let i = 0; i < 16; i++) ids.push((await call('POST', '/api/wiki/pages', {space: 'private', path: 'Alpha/A' + i, body: 'x'})).id);
  for (let i = 0; i < 16; i++) ids.push((await call('POST', '/api/wiki/pages', {space: 'private', path: 'Beta/B' + i, body: 'y'})).id);
  check(ids.filter(Boolean).length === 32, 'setup: 32 pages in two folders');

  const w = await boot({user: 'frida', mobile: true, hash: 'wiki', ls: {'tasks.wkSpace': JSON.stringify('private')}}), d = w.document;
  await until(() => typeof w.wk_loadPage === 'function' && w.eval(`(WK.idx.private?.pages || []).length`) === 32, 60);
  const det = name => [...d.querySelectorAll('#wk-res details')].find(x => x.querySelector(':scope > summary')?.textContent.trim() === name);
  check(await until(() => det('Alpha') && !det('Alpha').open && !det('Beta').open), 'more than 30 pages: the folders start closed');
  check(det('Alpha')?.dataset.wkk === 'wk:private:alpha', 'the folder carries the key of the computer panel');
  // open "Alpha" and "Beta" by hand, open a page of "Alpha", go Back
  det('Alpha').querySelector('summary').click();
  det('Beta').querySelector('summary').click();
  check(['wk:private:alpha', 'wk:private:beta'].every(k => JSON.parse(w.localStorage.getItem('tasks.sbbOpen') || '[]').includes(k)), 'opening by hand is kept (LS sbbOpen)');
  const toPage = async id => { w.location.hash = '#wiki/' + id; return until(() => !d.querySelector('#wk-res') && d.querySelector('#view .wkpage'), 60); };
  check(await toPage(ids[0]), 'a page opens without the tree (phone)');
  w.location.hash = '#wiki';
  check(await until(() => det('Beta')?.open), 'after Back the folder opened by hand is still open');
  check(det('Alpha')?.open, 'the folder of the page just seen is still open too');
  // close "Alpha" by hand: it stays closed after the next page of it and Back
  det('Alpha').querySelector('summary').click();
  check(!JSON.parse(w.localStorage.getItem('tasks.sbbOpen') || '[]').includes('wk:private:alpha'), 'closing by hand drops the key');
  check(await toPage(ids[1]), 'the next page opens');
  w.location.hash = '#wiki';
  check(await until(() => det('Alpha') && !det('Alpha').open && det('Beta').open), 'after Back the closed folder stays closed, the other stays open');
  // the list remembers its place for Back (the bookkeeping; jsdom has no layout to scroll)
  w.eval(`WK.listTop = null; WK.pgTop = false`);
  det('Beta').querySelector('a[href^="#wiki/"]').click();
  check(w.eval(`WK.listTop === 0 && WK.pgTop === true`), 'a page link of the list takes the list place');
  check(await until(() => d.querySelector('#view .wkpage') && w.eval(`WK.pgTop === false`), 60), 'the page takes the "start at the top" once');
  w.location.hash = '#wiki';
  check(await until(() => d.querySelector('#wk-res') && w.eval(`WK.listTop === null`), 60), 'Back puts the list place back once');
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
