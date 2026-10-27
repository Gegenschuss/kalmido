// 2.118.0 part B UI test (#2297): ONE sidebar switch "Progress in the sidebar" (account, side_progress) for the thin line
// and the progress rings; the old device switch for rings is gone; a device with rings=false hands it to the account once.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2118B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { if (await fn()) return true; await sleep(150); } return !!(await fn()); };
const settings = async () => (await call('GET', '/api/state')).settings;

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'progress'});
  const L = (await call('POST', '/api/lists', {name: 'Garden'})).id;
  const T1 = (await call('POST', '/api/tasks', {title: 'Cut the hedge', list_id: L})).id;
  const T2 = (await call('POST', '/api/tasks', {title: 'Water the roses', list_id: L})).id;
  await call('POST', `/api/tasks/${T2}/complete`, {});
  const rings = d => d.querySelectorAll('#side .o3c-ring').length;

  // on (default): ring there
  let w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  check(rings(d) === 1, 'default: ring in the sidebar');
  // settings: no device switch, one account switch; off -> no line, no ring at once
  w.eval(`settingsModal('look')`); await sleep(400);
  check(!d.querySelector('#s-o3c-rings'), 'no device switch for the rings any more');
  const c = d.querySelector('.smodal #s-sideprog');
  check(c && c.checked, 'account switch is on');
  c.checked = false; c.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(async () => (await settings()).side_progress === '0'), 'switch off is saved in the account');
  await sleep(300);
  check(rings(d) === 0 && !d.querySelector('#side .sprog'), 'off: neither ring nor line in the sidebar');
  c.checked = true; c.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(async () => (await settings()).side_progress === '1'), 'switch on is saved');
  await sleep(300);
  check(rings(d) === 1, 'on again: ring is back');
  w.close();

  // migration: old device value rings=false -> account "0", key removed; rings=true/missing changes nothing
  w = await boot({user: 'alice', hash: 'l/' + L, ls: {'tasks.rings': 'true'}}); d = w.document;
  check((await settings()).side_progress === '1' && rings(d) === 1, 'rings=true changes nothing');
  w.close();
  w = await boot({user: 'alice', hash: 'l/' + L, ls: {'tasks.rings': 'false'}}); d = w.document;
  check(await until(async () => (await settings()).side_progress === '0'), 'rings=false is taken over into the account once');
  check(!('tasks.rings' in w.__store) && rings(d) === 0, 'old key removed, no ring');
  w.close();
  await call('PATCH', '/api/settings', {side_progress: '1'});

  // phone width, short
  w = await boot({user: 'alice', mobile: true, hash: 'l/' + L}); d = w.document;
  check(rings(d) <= 1 && d.querySelector('#view'), '390 px: loads');
  w.close();

  check(errs.length === 0, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})();
