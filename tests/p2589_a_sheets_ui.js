// 2.589.0 part A UI test (#4825: the arrow keys and merged cells)
// kalmido-suite: fresh
// Own container (start.sh; P2589AS_NOSTART=1: the server already runs), jsdom. Invented names only. As a person without an
// organisation (frida) in her private table with the block B2:C3 merged:
// - into the block from any side the arrow keys land on its anchor B2, never in a covered cell (C2, B3, C3)
// - from the anchor down / right they jump past the block (B4 / D2); no script errors
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2589AS_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j._status = r.status; return j; };
const until = (fn, n) => require('./boot').until(async () => { try { return await fn(); } catch { return false; } }, {timeout: n ? n * 150 : 15000, step: 150});
const key = (w, el, k, o = {}) => el && el.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true, ...o}));

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const AK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true}, AK);
  const fr = await call('POST', '/api/users', {orgs: [], username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com'}, AK);
  check(fr.id, 'a person without an organisation');
  CK = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'collab,comments,sheets'});
  const S = await call('POST', '/api/sheets', {title: 'Blocks', space: 'private'});
  check(S._status === 201, 'a private table ' + JSON.stringify(S).slice(0, 120));
  const SID = S.id;
  for (let i = S.columns.length; i < 4; i++) await call('POST', `/api/sheets/${SID}/columns`, {title: '', kind: 'text'});
  const S2 = await call('GET', `/api/sheets/${SID}`), R = S2.rows.map(r => r.id), C = S2.columns.map(c => c.id);
  check(R.length >= 5 && C.length >= 4, `at least 5 rows and 4 columns (${R.length} / ${C.length})`);
  const m = await call('PUT', `/api/sheets/${SID}/cells`, {cells: [{cell: 'A1', raw: 'Start'}, {cell: 'B2', raw: 'Block'}, {cell: 'B2', fmt: {merge: [2, 2]}}]});
  check(m._status === 200, 'B2:C3 merged ' + JSON.stringify(m).slice(0, 160));

  const w = await boot({user: 'frida', hash: 'sheets/' + SID}), d = w.document;
  check(await until(() => d.getElementById(`shv-c-${R[1]}-${C[1]}`)?.getAttribute('colspan') === '2'), 'the block is drawn merged');
  const sc = () => d.getElementById('shv-scroll');
  const at = () => { const c = w.eval('SHV.cur'); return c ? `${C.indexOf(c.c)}:${R.indexOf(c.r)}` : ''; };  // column:row indexes
  const go = (ci, ri, k) => { w.eval(`shvSelect(${R[ri]}, ${C[ci]})`); sc().focus(); key(w, sc(), k); return at(); };
  const B2 = '1:1';
  check(go(0, 1, 'ArrowRight') === B2, 'A2 -> right = the anchor B2 ' + at());
  check(go(1, 1, 'ArrowRight') === '3:1', 'B2 -> right jumps past the block to D2 ' + at());
  check(go(1, 0, 'ArrowDown') === B2, 'B1 -> down = B2 ' + at());
  check(go(1, 1, 'ArrowDown') === '1:3', 'B2 -> down jumps past the block to B4 ' + at());
  check(go(2, 0, 'ArrowDown') === B2, 'C1 -> down (into the covered C2) = the anchor B2 ' + at());
  check(go(3, 2, 'ArrowLeft') === B2, 'D3 -> left (into the covered C3) = B2 ' + at());
  check(go(2, 3, 'ArrowUp') === B2, 'C4 -> up (into the covered C3) = B2 ' + at());
  check(go(0, 2, 'ArrowRight') === B2, 'A3 -> right (into the covered B3) = B2 ' + at());
  check(go(1, 1, 'ArrowUp') === '1:0' && go(1, 1, 'ArrowLeft') === '0:1', 'from the anchor up / left as always ' + at());
  check(go(2, 0, 'ArrowDown') === B2 && d.getElementById(`shv-c-${R[1]}-${C[1]}`)?.classList.contains('cur'), 'the chosen cell is a drawn one (marked)');
  check(!errs.length, 'no script errors ' + JSON.stringify(errs).slice(0, 300));
  w.close();

  console.log(`p2589_a_sheets_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
