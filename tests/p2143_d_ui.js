// 2.143.0 D UI tests (#2155 #2156): own container (start.sh). jsdom:
// - #2155 the appearance of the account is applied when the app loads (a second "device"), Settings > Appearance has the switch
//   "Only on this device" (default off); on = changes stay on the device, off = they go to the account; a first device uploads its
//   own appearance when the account has none; a device with the switch on keeps its own
// - #2156 Administration > Organisation shows the table "Activity per organisation" (organisations + the row without one)
// Invented names only.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2143D_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK = {};
const call = async (who, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK[who]}, body: body ? JSON.stringify(body) : undefined}); let j = {}; try { j = await r.json(); } catch { /* no body */ } return {http: r.status, ...j}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const look = async who => { const s = (await call(who, 'GET', '/api/state')).settings || {}; try { return JSON.parse(s.look || 'null'); } catch { return null; } };
const change = (w, el, on) => { el.checked = on; el.dispatchEvent(new w.Event('change', {bubbles: true})); };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK.alice = await login('alice');
  await call('alice', 'POST', '/api/admin/setup', {org_name: 'Alpha Studio', lang: 'en', collab_all: true});
  await call('alice', 'PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const mk = await call('alice', 'POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  check(mk.http === 200 || mk.http === 201, 'bob created ' + mk.http);
  CK.bob = await login('bob');
  await call('bob', 'PATCH', '/api/settings', {lang: 'en', tour: 'done'});

  // ================= #2155: the account's appearance is applied on a device that has none of its own
  await call('alice', 'PATCH', '/api/settings', {look: JSON.stringify({theme: 'light', accent: 'teal'})});
  let w = await boot({user: 'alice'}); let d = w.document;
  await until(() => d.documentElement.dataset.accent === 'teal', 40);
  check(d.documentElement.dataset.theme === 'light' && d.documentElement.dataset.accent === 'teal', `the account's appearance is applied: ${d.documentElement.dataset.theme} / ${d.documentElement.dataset.accent}`);

  w.eval(`settingsModal('look')`); await sleep(300);
  const pane = () => d.querySelector('.smodal [data-pane="look"]');
  const sw = pane().querySelector('#s-look-local');
  check(sw && sw.type === 'checkbox' && !sw.checked && /Only on this device/.test(sw.closest('label').textContent), 'the switch "Only on this device" is there and off');
  // on: a change stays on the device
  change(w, sw, true); await sleep(100);
  check(w.localStorage.getItem('tasks.lookLocal') === 'true', 'switch on: remembered on the device');
  w.eval(`lookSet('theme', 'dark')`); await sleep(1500);
  check(d.documentElement.dataset.theme === 'dark' && (await look('alice')).theme === 'light', 'switch on: the device changes, the account keeps its own');
  // off: it goes to the account
  change(w, pane().querySelector('#s-look-local'), false); await sleep(1500);
  check(w.localStorage.getItem('tasks.lookLocal') === null && (await look('alice')).theme === 'dark', 'switch off: this device appearance goes to the account');
  w.eval(`lookSet('accent', 'pink')`); await sleep(1500);
  check((await look('alice')).accent === 'pink', 'a change is saved to the account');
  w.eval(`for (const k of LOOK_KEYS) LS.del(k); applyTheme(); applyLook();`); await sleep(1500);
  check(JSON.stringify(await look('alice')) === '{}', 'reset: the account appearance is reset too');
  w.close();

  // a second device takes over what the first saved
  await call('alice', 'PATCH', '/api/settings', {look: JSON.stringify({theme: 'dark', accent: 'orange', font: 'atkinson'})});
  w = await boot({user: 'alice'}); d = w.document;
  await until(() => d.documentElement.dataset.accent === 'orange', 40);
  check(d.documentElement.dataset.theme === 'dark' && d.documentElement.dataset.accent === 'orange', 'a second device takes over the account appearance');
  w.close();
  // a device with the switch on keeps its own
  w = await boot({user: 'alice', ls: {'tasks.lookLocal': 'true', 'tasks.accent': '"lime"'}}); d = w.document;
  await sleep(1500);
  check(d.documentElement.dataset.accent === 'lime' && (await look('alice')).accent === 'orange', 'switch on: the device keeps its own appearance and sends nothing');
  w.close();
  // the account has none yet: the device's own is uploaded once
  check((await look('bob')) === null, 'bob: no appearance saved yet');
  w = await boot({user: 'bob', ls: {'tasks.theme': '"light"', 'tasks.accent': '"teal"'}}); d = w.document;
  await until(async () => (await look('bob')), 30);
  const up = await look('bob');
  check(up && up.theme === 'light' && up.accent === 'teal', 'first load: the local appearance goes to the account ' + JSON.stringify(up));
  w.close();

  // ================= #2156: the activity table (Administration > Organisation)
  w = await boot({user: 'alice'}); d = w.document;
  w.eval(`settingsModal('users')`); await sleep(300);
  w.eval(`admSubShow(document.querySelector('.smodal'), 'org')`);
  await until(() => d.querySelector('#s-act .acttbl'), 60);
  const rows = [...d.querySelectorAll('#s-act .acttbl tbody tr')];
  check(rows.length >= 1 && /Without organisation/.test(rows[rows.length - 1].textContent), 'the table has the row "Without organisation": ' + rows.length);
  check(rows.length >= 2 || (await call('alice', 'GET', '/api/admin/orgs/activity')).orgs.length === 0, 'the table lists the organisations');
  const head = [...d.querySelectorAll('#s-act .acttbl thead th')].map(x => x.textContent);
  check(head.length === 6 && /Last sign-in/.test(head.join('|')) && /Storage/.test(head.join('|')), 'the columns: ' + head.join('|'));
  check(!/@|Alice|Bob/.test(d.querySelector('#s-act').textContent), 'no people in the table');
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERROR', e); process.exit(1); });
