// kalmido-suite:
// 2.350.0 C (#3148) UI tests (own container, start.sh), jsdom: checkboxes of a knowledge page tick in read mode.
// - a click writes [x] / [ ] into the line it belongs to (code blocks do not count) and saves it like a typed change;
//   quick clicks one after the other all arrive (no conflict); a change by someone else meanwhile asks (conflict dialog)
// - a line with #123 ticks the task along (done / reopened); a task done elsewhere shows its line ticked (the text stays)
// - right click on a line: "Create as task" (the list dialog), the line then ends with #<id>
// - without the right to write the page (a read-only member of an organisation) the checkboxes stay disabled
// freelancer-matrix: wiki (the private space of a person without an organisation)
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login, idle} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2350C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = async (fn, n = 80) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const AK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true}, AK);
  const st0 = await call('GET', '/api/state', null, AK);
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'wiki'])].join(',');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: feats}, AK);
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []}, AK);
  CK = await login('frida');
  check(!((await call('GET', '/api/state')).me.workspaces || []).length, 'setup: frida has no organisation');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: feats});
  const T1 = (await call('POST', '/api/tasks', {title: 'Beta task'})).id;
  const BODY = `# List\n\n- [ ] Alpha\n- [ ] Beta #${T1}\n\n\`\`\`\n- [ ] not a box\n\`\`\`\n\n- [x] Gamma\n`;
  const PG = (await call('POST', '/api/wiki/pages', {space: 'private', path: 'Checks', body: BODY})).id;
  check(PG > 0, 'setup: the page');
  const body = async () => (await call('GET', '/api/wiki/pages/' + PG)).body || '';

  let w = await boot({user: 'frida', hash: 'wiki/' + PG, ls: {'tasks.wkSpace': JSON.stringify('private')}}), d = w.document;
  const boxes = () => [...d.querySelectorAll('#wk-md input[type="checkbox"]')];
  const box = k => d.querySelector(`#wk-md input[data-wkcb="${k}"]`);
  check(await until(() => boxes().length === 3), 'three checkboxes (the code block does not count) ' + boxes().length);
  check(boxes().every(b => !b.disabled && b.dataset.wkcb), 'with the right to write: all can be clicked');

  // ================= a click writes the line
  box(2).click();
  check(await until(async () => (await body()).includes('- [ ] Gamma')), 'unticking Gamma writes [ ] into its line');
  const b1 = await body();
  check(b1.includes('- [ ] Alpha') && b1.includes('- [ ] not a box') && b1.includes(`- [ ] Beta #${T1}`), 'the other lines and the code block stay');
  check(!box(2).checked && !box(2).closest('li').classList.contains('on'), 'the box shows unticked');
  // quick clicks one after the other: both arrive
  box(0).click(); box(2).click();
  check(await until(async () => { const b = await body(); return b.includes('- [x] Alpha') && b.includes('- [x] Gamma'); }), 'two quick clicks: both saved');
  check(!d.querySelector('.modal'), 'no conflict for my own quick clicks');

  // ================= a line with #123: the task along
  box(1).click();
  check(await until(async () => (await body()).includes(`- [x] Beta #${T1}`)), 'Beta ticked in the text');
  check(await until(async () => (await call('GET', '/api/tasks/' + T1)).status === 2), 'the linked task is done too');
  await idle(w);
  await until(() => box(1));
  box(1).click();
  check(await until(async () => (await body()).includes(`- [ ] Beta #${T1}`)), 'Beta unticked in the text');
  check(await until(async () => (await call('GET', '/api/tasks/' + T1)).status === 0), 'the linked task is open again');
  await idle(w);
  // a task done elsewhere: its line shows ticked, the text stays
  await call('POST', `/api/tasks/${T1}/complete`, {});
  w.close();
  w = await boot({user: 'frida', hash: 'wiki/' + PG, ls: {'tasks.wkSpace': JSON.stringify('private')}}); d = w.document;
  check(await until(() => box(1)?.checked), 'a task done elsewhere: its line shows ticked');
  check((await body()).includes(`- [ ] Beta #${T1}`), '… the text stays as it is');

  // ================= someone changed the page meanwhile: the conflict dialog asks
  const cur = await call('GET', '/api/wiki/pages/' + PG);
  check((await call('PATCH', '/api/wiki/pages/' + PG, {body: cur.body + '\nAdded elsewhere\n', expect_updated_at: cur.updated_at})).http === 200, 'a change from another device');
  // the suite's dialog bridge (boot.js) answers the app's question: "Take theirs"
  let asked = ''; w.confirm = m => { asked = String(m); return false; };
  box(0).click();
  check(await until(() => /Changed in the meantime/.test(asked)), 'a change meanwhile: the conflict dialog asks ' + asked);
  check(await until(() => !d.querySelector('.modal')), 'theirs taken');
  check(await until(async () => (await body()).includes('Added elsewhere')), 'the other change stays');
  await idle(w);
  w.close();

  // ================= right click: "Create as task"
  await call('PATCH', '/api/wiki/pages/' + PG, {body: '- [ ] Order paper\n'});
  w = await boot({user: 'frida', hash: 'wiki/' + PG, ls: {'tasks.wkSpace': JSON.stringify('private')}}); d = w.document;
  const li = await until(() => d.querySelector('#wk-md li[data-wkcbl="0"]'));
  check(li, 'the line is there');
  li.dispatchEvent(new w.MouseEvent('contextmenu', {bubbles: true, cancelable: true}));
  const mi = await until(() => [...d.querySelectorAll('#pop [role="menuitem"]')].find(b => /Create as task/.test(b.textContent)));
  check(mi, 'right click: the menu offers "Create as task"');
  mi?.click();
  const ok1 = await until(() => d.querySelector('.modal.wemdlg [data-m="ok"]'));
  check(ok1, '… the dialog with the list choice');
  ok1?.click();
  check(await until(async () => /^- \[ \] Order paper #\d+/.test(await body())), 'the line ends with the new task\'s #id ' + JSON.stringify(await body()));
  await idle(w);
  w.close();

  // ================= without the right to write: disabled (a read-only member of an organisation)
  const ORG = (await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: st0.me.id}, AK)).id;
  await call('POST', '/api/users', {username: 'rita', display_name: 'Rita', password: 'password123', email: 'rita@example.com'}, AK);
  const rm = await call('PUT', `/api/orgs/${ORG}/members`, {email: 'rita@example.com', role: 'readonly'}, AK);
  check(rm.http < 300, 'rita read-only in Alpha ' + rm.http);
  const RK = await login('rita');
  await call('POST', `/api/orgs/${ORG}/join`, {}, RK);
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: feats}, RK);
  const OP = (await call('POST', '/api/wiki/pages', {space: 'org:' + ORG, path: 'Rules', body: '- [ ] Read me\n- [x] Done\n'}, AK)).id;
  w = await boot({user: 'rita', hash: 'wiki/' + OP, ls: {'tasks.wkSpace': JSON.stringify('org:' + ORG)}}); d = w.document;
  check(await until(() => boxes().length === 2), 'rita sees the page with two checkboxes');
  check(await until(() => w.eval(`WK.idx['org:${ORG}']?.mayWrite`) === false), 'rita may not write there');
  check(await until(() => boxes().every(b => b.disabled && !b.dataset.wkcb)), 'read only: the checkboxes stay disabled');
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
