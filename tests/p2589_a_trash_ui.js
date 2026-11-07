// 2.589.0 part A UI test (#4875): the trash of the file store
// kalmido-suite: fresh
// Own container (start.sh; P2589A_NOSTART=1: the container runs already), jsdom. Invented names only.
// - a row of the trash offers "Delete permanently" next to "Restore"; it asks first, then the row is gone for good
// - Select works in the trash: the bar offers Restore and "Delete permanently" (each asks / ONE undo step for Restore)
// - "Empty trash" on top asks with the number of files and folders and "cannot be undone"; No keeps everything, Yes
//   empties the trash
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2589A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const upload = async (ck, name, text, form) => {
  const fd = new FormData(); fd.append('file', new Blob([text]), name);
  for (const [k, v] of Object.entries(form || {space: 'private'})) fd.append(k, v);
  const r = await fetch(B + 'api/files/upload', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: ck}, body: fd});
  return (await r.json()).items[0].id;
};
const trashIds = async () => ((await call('GET', '/api/files?space=trash')).items || []).map(x => x.id);
const gone = async id => (await call('GET', `/api/files/nodes/${id}`)).status === 404 && !(await trashIds()).includes(id);

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const st = await call('GET', '/api/state');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: [...new Set([...(st.settings?.features || '').split(','), 'files', 'docs'])].filter(Boolean).join(',')});
  const KISTE = (await call('POST', '/api/files/folders', {name: 'Kiste', space: 'private'})).id;
  const INNER = await upload(CK, 'innen.txt', 'innen', {parent_id: String(KISTE)});
  const F1 = await upload(CK, 'eins.txt', 'eins'), F2 = await upload(CK, 'zwei.txt', 'zwei'), F3 = await upload(CK, 'drei.txt', 'drei'), F4 = await upload(CK, 'vier.txt', 'vier');
  for (const id of [KISTE, F1, F2, F3, F4]) await call('DELETE', `/api/files/nodes/${id}`);
  check((await trashIds()).length === 5, 'setup: five rows in the trash');

  const w = await boot({user: 'alice', hash: 'ablage'}), d = w.document;
  const asked = []; let answer = true;
  w.confirm = m => { asked.push(m); return answer; };
  await until(() => d.querySelector('.abview'));
  w.eval(`ab_pick('trash'); AB.key = ''; ab_load()`);  // what a click on the trash in the spaces / the panel does
  check(await until(() => d.querySelector(`.abrow[data-abid="${F1}"]`)), 'the trash shows its rows ' + (d.querySelector('#view')?.textContent || '').replace(/\s+/g, ' ').slice(0, 300));

  // ================= one row for good
  const row = d.querySelector(`.abrow[data-abid="${F1}"]`);
  check(row?.querySelector('[data-ab="restore"]') && row?.querySelector('[data-ab="purge"]'), 'the row offers Restore and "Delete permanently"');
  check(d.querySelector('[data-ab="trash-empty"]'), 'the trash offers "Empty trash" on top');
  row?.querySelector('[data-ab="purge"]').click();
  check(await until(() => asked.length === 1), 'it asks first');
  check(/eins\.txt/.test(asked[0] || '') && /cannot be undone/.test(asked[0] || ''), 'the question names the file and "cannot be undone" ' + asked[0]);
  check(await until(async () => await gone(F1), 60), 'the file is deleted for good');
  check(await until(() => !d.querySelector(`.abrow[data-abid="${F1}"]`)), 'the row is gone');

  // ================= Select in the trash: Restore (ONE undo step) and "Delete permanently"
  const mode = d.querySelector('[data-absel="mode"]');
  check(mode, 'the trash offers Select');
  mode?.click();
  const tick = id => { const b = d.querySelector(`[data-absel="one"][data-id="${id}"]`); if (b) { b.checked = true; b.dispatchEvent(new w.Event('change', {bubbles: true})); } return !!b; };
  check(await until(() => d.querySelector(`[data-absel="one"][data-id="${F2}"]`)), 'the rows of the trash have boxes');
  tick(F2);
  let bar = await until(() => /1 selected/.test(d.querySelector('#ab-sbar')?.textContent || '') && d.querySelector('#ab-sbar'));
  check(bar && bar.querySelector('[data-absel="restore"]') && bar.querySelector('[data-absel="purge"]') && !bar.querySelector('[data-absel="move"]'),
    'the bar offers Restore and "Delete permanently" (no Move) ' + (bar?.textContent || '').replace(/\s+/g, ' '));
  const h0 = w.eval('HIST.undo.length');
  bar?.querySelector('[data-absel="restore"]').click();
  check(await until(async () => !(await trashIds()).includes(F2) && (await call('GET', `/api/files/nodes/${F2}`)).in_trash === false, 60), 'the chosen file is restored');
  check(await until(() => w.eval(`HIST.undo.length === ${h0 + 1}`)), 'ONE undo step');
  check(await until(() => !d.querySelector(`.abrow[data-abid="${F2}"]`) && !d.querySelector('#ab-sbar')), 'the row left the trash, the selection ends');

  d.querySelector('[data-absel="mode"]')?.click();
  await until(() => tick(F3));
  bar = await until(() => /1 selected/.test(d.querySelector('#ab-sbar')?.textContent || '') && d.querySelector('#ab-sbar'));
  bar?.querySelector('[data-absel="purge"]').click();
  check(await until(() => asked.length === 2), 'the bar asks before deleting for good');
  check(/Delete 1 item permanently\?/.test(asked[1] || '') && /1 file/.test(asked[1] || ''), 'the question counts the file ' + asked[1]);
  check(await until(async () => await gone(F3), 60), 'the chosen file is deleted for good');

  // ================= Empty trash: No keeps everything, Yes empties it
  answer = false;
  await until(() => !d.querySelector(`.abrow[data-abid="${F3}"]`));
  d.querySelector('[data-ab="trash-empty"]')?.click();
  check(await until(() => asked.length === 3), '"Empty trash" asks first');
  check(/1 file, 1 folder/.test(asked[2] || '') && /cannot be undone/.test(asked[2] || ''), 'the question counts files and folders, "cannot be undone" ' + asked[2]);
  check(await until(() => !d.querySelector('.modal.cdlg')), 'the question closes');  // a No sends nothing: the trash keeps both
  check((await trashIds()).length === 2, 'No: both rows stay in the trash');
  answer = true;
  d.querySelector('[data-ab="trash-empty"]')?.click();
  check(await until(() => asked.length === 4), 'asked again');
  check(await until(async () => (await trashIds()).length === 0 && await gone(KISTE) && await gone(F4), 60), 'Yes: the trash is empty, the folder went for good');
  check((await call('GET', `/api/files/nodes/${INNER}`)).status === 404, 'the file in the folder went with it');
  check(await until(() => /The trash is empty/.test(d.querySelector('.abempty')?.textContent || '')), 'the view shows the empty trash');
  check(!d.querySelector('[data-ab="trash-empty"]'), 'no "Empty trash" in an empty trash');
  check((await call('GET', `/api/files/nodes/${F2}`)).status === 200, 'the restored file stays');
  w.close();

  console.log(`p2589_a_trash_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
