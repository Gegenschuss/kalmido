// 2.46.1 UI tests (part C, #1554), own container (start.sh, mode workspaces). jsdom, invented data only:
// - #1554 contacts: the select button starts the selection (a tick per row, the floating bar with the count); a tap ticks a
//   row; "All" ticks every contact one may change (a view-only one is not ticked); Move (menu of the address books) and
//   Delete (one question with the count) send ONE request each; Esc ends the selection; on the phone a long press starts it
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});  // KMT_NOSTART=1: a running app
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const vcf = (p, n) => Array.from({length: n}, (_, i) => `BEGIN:VCARD\r\nVERSION:3.0\r\nUID:${p}-${i}\r\nFN:${p} Person ${i}\r\nN:Person ${i};${p};;;\r\nEND:VCARD\r\n`).join('');
const importVcf = async (ck, bid, text) => { const fd = new FormData(); fd.append('file', new Blob([text], {type: 'text/vcard'}), 'x.vcf'); return (await fetch(B + `api/books/${bid}/import`, {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: ck}, body: fd})).status; };
const ptr = (w, el, type, extra = {}) => {  // jsdom has no PointerEvent: a MouseEvent with pointerType
  const e = new w.MouseEvent(type, {bubbles: true, cancelable: true, button: 0, clientX: 10, clientY: 10});
  Object.defineProperty(e, 'pointerType', {value: extra.pointerType || 'mouse'}); el.dispatchEvent(e);
};

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments', 'contacts']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,contacts,office,clients'});
  const me = (await call('GET', '/api/state')).me.id;
  const bob = await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.org'});
  const CB = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'}, CB);
  const ORG = (await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me})).id;
  check((await call('PUT', `/api/orgs/${ORG}/members`, {email: 'bob@example.org'})).http === 200, 'Bob joins the organisation (Alice may share with him)');
  // the selection is Bob's (a person without an organisation); Alice (admin) shares a book with him to read
  const BK = (await call('POST', '/api/books', {name: 'Mine'}, CB)).id, BT = (await call('POST', '/api/books', {name: 'Target'}, CB)).id;
  const BV = (await call('POST', '/api/books', {name: 'Alice view'})).id;
  check(await importVcf(CB, BK, vcf('Own', 3)) === 200 && await importVcf(CK, BV, vcf('Alices', 1)) === 200, 'contacts imported');
  check((await call('PUT', `/api/books/${BV}/members`, {user_id: bob.id, role: 'view'})).http === 200, 'Alice shares a book with Bob (view)');

  // ================= #1554: the selection mode
  let w = await boot({user: 'bob', hash: 'contacts'}); let d = w.document;
  await until(() => d.querySelectorAll('#view .ctrow').length === 4, 60);
  check(d.querySelectorAll('#view .ctrow').length === 4, '#1554: four contacts shown');
  check(!d.querySelector('#ct-sbar') && !!d.querySelector('[data-ct="pick"]'), '#1554: a select button, no bar yet');
  d.querySelector('[data-ct="pick"]').click(); await sleep(50);
  check(!!d.querySelector('#ct-sbar') && d.querySelectorAll('#view .ctrow .ctchk').length === 4 && /Tap contacts/.test(d.querySelector('#ct-sbar .mcount').textContent), '#1554: the bar and a tick per row');
  check(d.querySelector('[data-ctb="del"]').disabled && d.querySelector('[data-ctb="move"]').disabled, '#1554: Move / Delete wait for a tick');
  const row = name => [...d.querySelectorAll('#view .ctrow')].find(x => x.textContent.includes(name));
  row('Own Person 0').click(); await sleep(50);
  check(row('Own Person 0').classList.contains('picked') && row('Own Person 0').getAttribute('aria-pressed') === 'true' && /1 selected/.test(d.querySelector('#ct-sbar .mcount').textContent), '#1554: a tap ticks the row');
  check(!d.querySelector('.ctcard:not(.ctnone)'), '#1554: a tap in the selection does not open the card');
  row('Alices Person 0').click(); await sleep(50);
  check(!row('Alices Person 0').classList.contains('picked') && row('Alices Person 0').classList.contains('ctro'), '#1554: a view-only contact cannot be ticked');
  d.querySelector('[data-ctb="all"]').click(); await until(() => w.eval('CT.pick.size') === 3, 20);
  check(w.eval('CT.pick.size') === 3 && /3 selected/.test(d.querySelector('#ct-sbar .mcount').textContent), '#1554: All = every contact one may change');
  check(/Select none/.test(d.querySelector('[data-ctb="all"]').textContent), '#1554: All turns into Select none');
  d.querySelector('[data-ctb="all"]').click(); await sleep(50);
  check(w.eval('CT.pick.size') === 0, '#1554: Select none');
  row('Own Person 1').click(); row('Own Person 2').click(); await sleep(50);
  // move: the menu of the address books one may change (not the view-only one)
  d.querySelector('[data-ctb="move"]').click(); await until(() => d.querySelector('#pop [role="menuitem"]'), 20);
  const items = [...d.querySelectorAll('#pop [role="menuitem"]')];
  check(items.some(x => /Target/.test(x.textContent)) && !items.some(x => /Alice view/.test(x.textContent)), '#1554: Move offers the books one may change: ' + items.map(x => x.textContent.trim()).join('|'));
  items.find(x => /Target/.test(x.textContent)).click();
  await until(async () => ((await call('GET', `/api/contacts?book_id=${BT}`, null, CB)).items || []).length === 2, 40);
  check(((await call('GET', `/api/contacts?book_id=${BT}`, null, CB)).items || []).length === 2, '#1554: two contacts moved to Target');
  check(!d.querySelector('#ct-sbar') && w.eval('CT.pick') === null, '#1554: the selection ends after the move');
  // delete: one question with the count, one request
  let asked = '';
  w.confirm = t => { asked = t; return true; };
  await until(() => d.querySelectorAll('#view .ctrow').length === 4, 40);
  d.querySelector('[data-ct="pick"]').click(); await sleep(50);
  row('Own Person 0').click(); row('Own Person 1').click(); await sleep(50);
  d.querySelector('[data-ctb="del"]').click();
  await until(async () => ((await call('GET', '/api/contacts', null, CB)).items || []).length === 2, 40);
  check(/Delete 2 contacts\?/.test(asked), '#1554: one question with the count: ' + asked);
  const left = ((await call('GET', '/api/contacts', null, CB)).items || []).map(x => x.fn).sort();
  check(JSON.stringify(left) === JSON.stringify(['Alices Person 0', 'Own Person 2']), '#1554: the two are deleted: ' + left);
  d.querySelector('[data-ct="pick"]')?.click(); await sleep(50);
  check(!!d.querySelector('#ct-sbar'), '#1554: selection again');
  d.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); await sleep(50);
  check(!d.querySelector('#ct-sbar') && w.eval('CT.pick') === null, '#1554: Esc ends the selection');
  w.close();
  // the phone: a long press starts the selection with that row
  w = await boot({user: 'bob', hash: 'contacts', mobile: true}); d = w.document;
  await until(() => d.querySelectorAll('#view .ctrow').length === 2, 60);
  const r2 = [...d.querySelectorAll('#view .ctrow')].find(x => x.textContent.includes('Own Person 2'));
  ptr(w, r2, 'pointerdown', {pointerType: 'touch'}); await sleep(650); ptr(w, r2, 'pointerup', {pointerType: 'touch'}); r2.click(); await sleep(50);
  check(!!d.querySelector('#ct-sbar') && w.eval('CT.pick.size') === 1 && !/contacts\/\d/.test(w.location.hash), '#1554: a long press starts the selection with the row (the click after it does not open it)');
  w.close();

  console.log(`p2461_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
