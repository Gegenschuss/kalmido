// kalmido-suite: fresh
// 2.380 G UI tests (security part of the 2.380 rest package), own container (start.sh), jsdom. Invented names only.
// - #2289: list settings > Inbound webhook: "Add" shows the token for the header X-Kalmido-Hook-Token first (with a copy
//   button), the path URL below it, the curl example sends the header to /api/hooks/in (no token in its URL)
// - #3391: Settings > Access > Webhooks: a personal webhook that reaches an organisation's list says so; the organisation's
//   admin gets "Set up as organisation webhook", a member does not; a person without an organisation sees no such hint
// - #3389: Settings > Administration > Advanced: one field per service (13), the old list in each
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login, idle, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2380RG_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const HOOK = 'https://hooks.example.invalid/hook';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Example Org', lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  const bob = await call('POST', '/api/users', {orgs: [ORG], username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  await call('POST', '/api/users', {orgs: [], username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com'});
  const CB = await login('bob'), CF = await login('frida');
  for (const ck of [CB, CF]) await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'}, ck);
  const W = (await call('POST', '/api/lists', {name: 'Home', org_id: null})).id;
  const OL = (await call('POST', '/api/lists', {name: 'Org board', org_id: ORG})).id;
  await call('PUT', `/api/lists/${OL}/members`, {user_id: bob.id, role: 'edit'});
  await call('PATCH', '/api/admin/settings', {cal_allow_hosts: 'nextcloud.home.arpa'});

  // ================= #2289: the header variant first
  let w = await boot({user: 'alice'}), d = w.document;
  w.__dialogs = 'manual';
  w.eval(`listModal(${W})`);
  await until(() => d.querySelector('#l-whi [data-whi-add]'));
  const box = () => d.querySelector('#l-whi');
  click(w, box().querySelector('[data-whi-add]'));
  await until(() => d.querySelector('.cdlg #cdlg-in'));
  d.querySelector('.cdlg #cdlg-in').value = 'Home Assistant';
  d.querySelector('.cdlg form').dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true}));
  await until(() => box()?.querySelector('.whi-url code.whi-tok'));
  const tok = box()?.querySelector('.whi-tok')?.textContent || '', url = box()?.querySelector('.whi-u')?.textContent || '';
  const curl = box()?.querySelector('.whi-ex code')?.textContent || '', txt = box()?.querySelector('.whi-url')?.textContent || '';
  check(/^khi_/.test(tok) && /X-Kalmido-Hook-Token/.test(txt) && txt.indexOf(tok) < txt.indexOf(url), '#2289: the token for the header shows first: ' + txt.slice(0, 160));
  check(url.endsWith('/api/hooks/in/' + tok), '#2289: the path URL still shows (tools without headers): ' + url.slice(0, 80));
  check(curl.includes(`-H 'X-Kalmido-Hook-Token: ${tok}'`) && /\/api\/hooks\/in'$/.test(curl) && !curl.includes('/api/hooks/in/'), '#2289: curl sends the header, no token in its URL: ' + curl.slice(0, 160));
  check(!!box()?.querySelector('[data-whi-copy="token"]') && !!box()?.querySelector('[data-whi-copy="url"]'), '#2289: copy buttons for the token and the URL');
  const p = await fetch(B + 'api/hooks/in', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Kalmido-Hook-Token': tok}, body: JSON.stringify({title: 'From the header'})});
  check(p.status === 201, '#2289: the shown token works in the header: ' + p.status);
  d.querySelectorAll('.modal').forEach(m => m.remove());

  // ================= #3389: one field per service
  w.eval(`settingsModal('users')`);
  await until(() => d.querySelector('[data-allowp="calendar"]'));
  const fs = [...d.querySelectorAll('[data-allowp]')];
  check(fs.length === 13 && fs.every(x => x.value === 'nextcloud.home.arpa'), '#3389: 13 fields, the old list in each: ' + fs.map(x => x.dataset.allowp + '=' + x.value).join(' '));
  w.close();

  // ================= #3391: the hint at personal webhooks
  await call('POST', '/api/me/webhooks', {name: 'mine', url: HOOK + '/alice', events: ['task.created']});
  await call('POST', '/api/me/webhooks', {name: 'bobs', url: HOOK + '/bob', events: ['task.created']}, CB);
  await call('POST', '/api/me/webhooks', {name: 'fridas', url: HOOK + '/frida', events: ['task.created']}, CF);
  for (const [user, admin] of [['alice', true], ['bob', false]]) {
    w = await boot({user}); d = w.document;
    w.eval(`settingsModal('webhooks')`);
    await until(() => d.querySelector('#s-whs .whrow'));
    await idle(w);
    const hint = d.querySelector('#s-whs .whorg');
    check(!!hint && /Events of the organisation Example Org are not delivered here/.test(hint.textContent), `#3391 ${user}: the hint names the organisation: ${hint?.textContent}`);
    check(!!hint?.querySelector('[data-wh="toorg"]') === admin, `#3391 ${user}: "Set up as organisation webhook" only for its admin`);
    w.close();
  }
  w = await boot({user: 'frida'}); d = w.document;
  w.eval(`settingsModal('webhooks')`);
  await until(() => d.querySelector('#s-whs .whrow'));
  check(!d.querySelector('#s-whs .whorg'), '#3391 frida (no organisation): no hint');
  w.close();

  check(!errs.length, 'no script errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`p2380r_g_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
