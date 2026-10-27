// 2.177.0 (#2685) UI tests (own container, start.sh). jsdom, phone width -- the progress window of the knowledge ZIP import:
// - a ZIP above the server's limit is refused BEFORE the upload with a message naming the limit in MB (nothing sent)
// - the window shows "Uploading: x of y" and then "Unpacking: x of y files" with a bar; "In the background" closes it
// - an import that ended while the app was closed is reported the next time the knowledge pages open (the pages, one
//   Undo step) and its result is cleared on the server
// freelancer-matrix: wiki (the import runs in the private space of a person without an organisation)
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2177A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
// a small ZIP made here: two pages, one linking an invented PDF
const ZIP = execFileSync('python3', ['-c', `
import io, sys, zipfile
b = io.BytesIO()
with zipfile.ZipFile(b, "w") as z:
    z.writestr("Import/Eins.md", "# Eins\\n\\n[[Blatt.pdf]]\\n")
    z.writestr("Import/Zwei.md", "# Zwei\\n")
    z.writestr("Import/Blatt.pdf", b"%PDF-1.4\\n1 0 obj<</Type/Catalog>>endobj\\ntrailer<</Root 1 0 R>>\\n%%EOF\\n")
sys.stdout.buffer.write(b.getvalue())`]);

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

  // an import that ends while the app is closed (uploaded here like the app does it)
  const j = await call('POST', '/api/wiki/import/upload', {size: ZIP.length, name: 'wiki.zip', space: 'private'});
  check(j.id && j.max_mb > 0 && j.chunk > 0, 'the upload starts ' + JSON.stringify(j));
  const r = await fetch(B + `api/wiki/import/upload/${j.id}?offset=0`, {method: 'PUT', headers: {'X-Requested-With': 'kalmido', 'Content-Type': 'application/octet-stream', Cookie: CK}, body: ZIP});
  check(r.ok, 'the one piece ' + r.status);
  check(await until(async () => (await call('GET', `/api/wiki/import/upload/${j.id}`)).state === 'done', 80), 'the import ends on the server');

  const w = await boot({user: 'frida', mobile: true, hash: 'wiki', ls: {'tasks.wkSpace': JSON.stringify('private')}}), d = w.document;
  await until(() => typeof w.wki_start === 'function', 60);
  // the report of the import that ended meanwhile: the pages are there, the toast names them, one Undo step
  check(await until(() => /2 pages imported/.test(d.body.textContent), 60), 'the finished import is reported when the knowledge pages open');
  check(w.eval(`(WK.idx.private?.pages || []).some(p => p.path === 'Import/Eins')`) || await until(() => w.eval(`(WK.idx.private?.pages || []).some(p => p.path === 'Import/Eins')`), 40), 'the imported page is in the tree');
  check(await until(async () => (await call('GET', '/api/wiki/import/upload')).current === null, 40), 'the result is cleared on the server once reported');

  // too large: refused before anything is sent, with the limit in MB
  w.eval(`WKI.lim = {chunk: 1048576, max_mb: 1, file_mb: 1}`);
  const big = new w.File([new Uint8Array(1048577 + 10)], 'riesig.zip', {type: 'application/zip'});
  await w.wki_start('private', big);
  check(await until(() => [...d.querySelectorAll('.modal')].some(m => /riesig\.zip/.test(m.textContent) && /up to 1 MB/.test(m.textContent))), 'a too large ZIP: the message names the limit before the upload');
  check((await call('GET', '/api/wiki/import/upload')).current === null, 'nothing was uploaded');
  [...d.querySelectorAll('.modal [data-m="close"]')].forEach(b => b.click());

  // the window: upload line, then the unpacking with its count; "In the background" closes it
  w.eval(`wki_sheet(); wki_draw({state: 'upload', received: 3 * 1048576, size: 12 * 1048576})`);
  const box = () => d.querySelector('.modal .wki-box');
  check(box() && /Uploading: 3,0 MB of 12,0 MB/.test(box().textContent) && box().querySelector('progress')?.getAttribute('max') === String(12 * 1048576), 'the upload line and bar ' + box()?.textContent);
  w.eval(`wki_draw({state: 'running', progress: {done: 230, total: 600}})`);
  check(/Unpacking: 230 of 600 files/.test(box()?.textContent || '') && box().querySelector('progress')?.getAttribute('value') === '230', 'the unpacking line and bar ' + box()?.textContent);
  d.querySelector('.modal [data-wki="bg"]').click();
  check(await until(() => !box()), '"In the background" closes the window');
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
