// 2.273.0 D (#3051) UI test (the web client part), own container (start.sh). jsdom:
// - the task upload takes the size limit from the server (state max_file_mb -> S.maxFileMb), not a fixed 50 MB; the message names it
// - five files that are each within the limit but together over four times the limit: one clear message, nothing is sent
// - a second upload while the first is running is not sent (it would attach the files twice); F2: one for another task is sent
// freelancer-matrix: tasks (the person has no organisation)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window

(async () => {
  await sleep(600);
  let r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'frida', display_name: 'Frida', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const L = (await call('POST', '/api/lists', {name: 'Files'})).id;
  const T = (await call('POST', '/api/tasks', {title: 'With files', list_id: L})).id;
  const T2 = (await call('POST', '/api/tasks', {title: 'Other files', list_id: L})).id;  // 2.273.0 F2 (#3051)
  const w = await boot({user: 'frida', hash: 'l/' + L}), d = w.document;
  const toastText = () => d.querySelector('#toast')?.textContent || '';
  check(await until(() => w.eval('S.maxFileMb') > 0), '#3051: the client got the upload limit from the server');
  const sent = []; const of = w.fetch;
  w.fetch = (u, o) => { sent.push(String(u)); return /attachments/.test(String(u)) ? new Promise(() => {}) : of(u, o); };
  const big = (name, mb) => `(() => { const f = new File(['x'], ${JSON.stringify(name)}); Object.defineProperty(f, 'size', {value: ${mb} * 1024 * 1024}); return f; })()`;
  w.eval('S.maxFileMb = 7');
  w.eval(`uploadFiles(${T}, [${big('huge.bin', 8)}])`);
  check(await until(() => /huge\.bin is larger than 7 MB/.test(toastText())), '#3051: the message names the limit the server sent: ' + toastText());
  check(!sent.some(u => /attachments/.test(u)), '#3051: a too big file is not sent');
  w.eval(`uploadFiles(${T}, [${[1, 2, 3, 4, 5].map(i => big('p' + i + '.bin', 6)).join(',')}])`);
  check(await until(() => /together are larger than 28 MB/.test(toastText())), '#3051: five files over the total limit: one message with the total: ' + toastText());
  check(!sent.some(u => /attachments/.test(u)), '#3051: nothing is sent for the total');
  w.eval(`uploadFiles(${T}, [new File(['a'], 'one.txt')])`);
  await until(() => sent.filter(u => /attachments/.test(u)).length === 1);
  w.eval(`uploadFiles(${T}, [new File(['a'], 'one.txt')])`);
  check(await until(() => /Uploading/.test(toastText())), 'toast while uploading');
  await sleep(300);  // the second call has had its chance; the check is that it never reaches the network
  check(sent.filter(u => /attachments/.test(u)).length === 1, '#3051: a second upload while one runs is not sent: ' + sent.filter(u => /attachments/.test(u)).length);
  // 2.273.0 F2 (#3051): another task's upload during the first one is sent (the busy mark is per task)
  w.eval(`uploadFiles(${T2}, [new File(['b'], 'two.txt')])`);
  check(await until(() => sent.filter(u => new RegExp(`tasks/${T2}/attachments`).test(u)).length === 1),
    '2.273.0 F2 (#3051): an upload for another task while one runs is sent: ' + sent.filter(u => /attachments/.test(u)).join(' '));
  w.fetch = of; w.close();
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: exception', e); process.exit(1); });
