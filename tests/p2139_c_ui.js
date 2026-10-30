// 2.139.0 C (#2386) UI tests (own container, start.sh). jsdom:
// - a page whose text cannot be read (409 wiki_unreadable) shows the server's message with its way out and a "Delete page"
//   button instead of a bare error; the button deletes the page; another error keeps the plain hint without the button
// - the browser lock names the pages it skipped (wkeLostNames: the base name, a name that does not open = its number)
// freelancer-matrix: wiki (the pages are in the private space of a person without an organisation)
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2139C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const MSG = 'This page cannot be read: the key of its encryption is missing. It opens again once the server key of this installation is restored; otherwise it can only be deleted.';
// the GET of page id answers like an unreadable page (409 wiki_unreadable) or another error; everything else goes to the server
const stub = (w, id, code, status = 409) => w.eval(`(() => { const real = rawFetch; window.rawFetch = async (m, u, b) => {
  if (m === 'GET' && u === '/api/wiki/pages/${id}') { const e = new Error(${JSON.stringify(MSG)}); e.status = ${status}; e.data = {code: ${JSON.stringify(code)}, error: e.message}; throw e; }
  return real(m, u, b); }; return 1; })()`);

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
  const P1 = (await call('POST', '/api/wiki/pages', {space: 'private', path: 'Old/Lost', body: 'x'})).id;
  const P2 = (await call('POST', '/api/wiki/pages', {space: 'private', path: 'Other', body: 'y'})).id;
  check(P1 && P2, 'setup: two pages');

  // ================= the unreadable page: message + delete
  let w = await boot({user: 'frida', hash: 'wiki', ls: {'tasks.wkSpace': JSON.stringify('private')}}), d = w.document;
  await until(() => typeof w.wk_loadPage === 'function' && w.eval(`(WK.idx.private?.pages || []).length`) === 2, 60);
  stub(w, P1, 'wiki_unreadable');
  w.location.hash = '#wiki/' + P1;
  const box = await until(() => d.querySelector('#view .wklost'), 60);
  check(box && box.textContent.includes('otherwise it can only be deleted') && box.getAttribute('role') === 'alert', 'the page shows the message with its way out');
  const del = box?.querySelector('[data-wk="lostdel"]');
  check(del && /Delete page/.test(del.textContent), 'a "Delete page" button beside the message');
  del?.click();
  const gone = await until(async () => (await call('GET', '/api/wiki?space=private')).pages?.every(p => p.id !== P1), 40);
  check(gone, 'the button deletes the unreadable page');
  check(await until(() => !d.querySelector('#view .wklost')), 'after deleting the message is gone');
  w.close();

  // another error: the plain hint, no delete button
  w = await boot({user: 'frida', hash: 'wiki', ls: {'tasks.wkSpace': JSON.stringify('private')}}); d = w.document;
  await until(() => typeof w.wk_loadPage === 'function' && w.eval(`(WK.idx.private?.pages || []).length`) === 1, 60);
  stub(w, P2, 'other', 500);
  w.location.hash = '#wiki/' + P2;
  const hint = await until(() => [...d.querySelectorAll('#view .wkpage .mhint')].find(x => x.textContent.includes('cannot be read')), 60);
  check(hint && !d.querySelector('#view .wklost') && !d.querySelector('[data-wk="lostdel"]'), 'another error keeps the plain hint without the button');

  // ================= the browser lock names the skipped pages
  await until(() => typeof w.wkeLostNames === 'function', 40);
  const names = await w.eval(`wkeLostNames('private', new Map([[5, 'Folder/Name'], [6, 'e2e1:{"v":1,"g":1,"iv":"AAAA","ct":"AAAA"}']]))`).catch(e => 'ERR ' + e);
  check(Array.isArray(names) && names[0] === 'Name' && names[1] === 'Unreadable page 6', 'skipped pages: the base name, a name that does not open = its number ' + JSON.stringify(names));
  check(w.eval(`trn('{0} page skipped: {1} (not readable)', '{0} pages skipped: {1} (not readable)', 1, 'Name')`) === '1 page skipped: Name (not readable)', 'the toast text');
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
