// 2.190.0 part A (#2496): the client side of sessions and sign-in, own container (start.sh), jsdom.
// - a sign-in link opened while another account is signed in asks first (the app's own dialog, not window.confirm): "no" leaves
//   the link unused and the session as it was; "yes" signs in with the link
// - another account than last time in this browser (applyState): the Cache Storage is emptied like at the logout
// - sw.js in a sandbox: the app page and the quick capture page are kept without their query (no captured title / address as key)
// freelancer-matrix: account (the link question for a person without an organisation)
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, j: await r.json().catch(() => ({}))}; };

// ================= sw.js in a sandbox: cache keys of the app page / the capture page
async function swKeys() {
  const SRC = fs.readFileSync(path.join(__dirname, '..', 'static', 'sw.js'), 'utf8');
  const ORIGIN = 'https://kalmido.example', put = [];
  const norm = k => String((k && k.url) || k).replace(ORIGIN, '');
  const resp = u => ({ok: true, status: 200, redirected: false, type: 'basic', url: u, headers: new Headers({'content-type': 'text/html', 'cache-control': 'no-cache'}), clone() { return this; }});
  const cache = {put: async k => { put.push(norm(k)); }, match: async () => undefined, keys: async () => []};
  const caches = {open: async () => cache, keys: async () => [], match: async () => undefined, delete: async () => true};
  const handlers = {};
  const self = {addEventListener: (k, f) => { handlers[k] = f; }, skipWaiting: async () => {}, clients: {claim: async () => {}, matchAll: async () => []}, location: {origin: ORIGIN}, navigator: {}};
  vm.runInContext(SRC, vm.createContext({self, caches, fetch: async u => resp(norm(u)), URL, Headers, console, setTimeout, Promise, TypeError, Response: function () {}}), {filename: 'sw.js'});
  for (const u of ['/capture?title=Secret%20page&url=https%3A%2F%2Fintranet.example%2Fx', '/?share=1', '/static/app.css']) {
    let p = null; handlers.fetch({request: {url: ORIGIN + u, method: 'GET'}, respondWith: x => { p = x; }}); await p; await sleep(20);
  }
  check(put.includes('/capture') && !put.some(k => /Secret|intranet/.test(k)), `sw: the capture page is kept without its query ${JSON.stringify(put)}`);
  check(put.includes('/') && !put.includes('/?share=1'), 'sw: the app page is kept without its query');
  check(put.some(k => k.startsWith('/static/app.css')), 'sw: static files as before');
}

(async () => {
  await swKeys();
  execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', lang: 'en'})});
  const AC = await login('alice');
  await call(AC, 'POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  const ORG = (await call(AC, 'GET', '/api/state')).j.me.workspaces[0].id;
  const id = {};
  for (const u of ['carol', 'erin']) id[u] = (await call(AC, 'POST', '/api/users', {username: u, display_name: u[0].toUpperCase() + u.slice(1), password: 'password123', orgs: [ORG], email: `${u}@example.com`})).j.id;
  id.frida = (await call(AC, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', orgs: [], email: 'frida@example.com'})).j.id;
  for (const u of ['carol', 'frida']) await call(await login(u), 'PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const linkTok = async uid => (await call(AC, 'POST', `/api/users/${uid}/signin-link`, {})).j.link.split('/').pop();

  // ---- a sign-in link with someone else signed in: "no"
  let tok = await linkTok(id.erin), asked = [];
  let w = await boot({user: 'carol', hash: 'signin/' + tok, setup: x => { x.confirm = t => { asked.push(t); return false; }; }});
  for (let i = 0; i < 40 && !asked.length; i++) await sleep(100);
  check(asked.length === 1 && /Erin/.test(asked[0]) && /Carol/.test(asked[0]), 'the app asks before another account signs in: ' + asked[0]);
  check(!w.document.querySelector('.modal.cdlg'), 'the dialog closed');
  w.close();
  let r = await call(w.__cookie, 'GET', '/api/state');
  check(r.status === 200 && r.j.me.id === id.carol, '"no": the session stays as it was');
  r = await call('', 'POST', '/api/auth/link', {token: tok, switch: true});
  check(r.status === 200 && r.j.ok, '"no": the link stays unused (it still signs in)');

  // ---- "yes"
  tok = await linkTok(id.erin); asked = [];
  w = await boot({user: 'carol', hash: 'signin/' + tok, setup: x => { x.confirm = t => { asked.push(t); return true; }; }});
  for (let i = 0; i < 40 && !asked.length; i++) await sleep(100);
  await sleep(500);
  w.close();
  r = await call('', 'POST', '/api/auth/link', {token: tok});
  check(asked.length === 1 && r.status === 404, '"yes": the link was used to sign in ' + r.status);

  // ---- freelancer-matrix: account -- a person without an organisation gets the same question
  tok = await linkTok(id.erin); asked = [];
  w = await boot({user: 'frida', hash: 'signin/' + tok, setup: x => { x.confirm = t => { asked.push(t); return false; }; }});
  for (let i = 0; i < 40 && !asked.length; i++) await sleep(100);
  w.close();
  check(asked.length === 1 && /Frida/.test(asked[0]), 'freelancer: the question as well');

  // ---- another account than last time: the Cache Storage goes
  const deleted = [];
  w = await boot({user: 'carol', ls: {'tasks.uid': '999999'}, setup: x => {
    x.caches = {keys: async () => ['tasks-shell-v1', 'tasks-share'], delete: async k => { deleted.push(k); return true; }, open: async () => ({}), match: async () => undefined};
  }});
  for (let i = 0; i < 40 && deleted.length < 2; i++) await sleep(100);
  w.close();
  check(deleted.includes('tasks-share') && deleted.includes('tasks-shell-v1'), 'account switch: the Cache Storage is emptied ' + JSON.stringify(deleted));
  const kept = [];
  w = await boot({user: 'carol', ls: {'tasks.uid': String(id.carol)}, setup: x => {
    x.caches = {keys: async () => ['tasks-shell-v1'], delete: async k => { kept.push(k); return true; }, open: async () => ({}), match: async () => undefined};
  }});
  await sleep(500);
  w.close();
  check(!kept.length, 'the same account: the caches stay');

  console.log(`\np2190_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
