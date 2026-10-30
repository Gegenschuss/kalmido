// 2.238.0 B (#2872) UI tests (jsdom, own container via start.sh): the offline copies belong to one sign-in. jsdom has no
// IndexedDB: the knowledge pages' copy is the stand-in store of p2169_a_ui.js (window.__wkoStore), the outbox runs on
// localStorage (its fallback). One "browser" = one store + one localStorage, shared by its windows.
// - the copy carries the sign-in mark (me.sgen); a start in the same session keeps it
// - a start with another sign-in (new session) empties it before anything is read; the records then carry the new mark
// - 14 days without an online sync: an offline start empties it; a fresh copy is read offline as before
// - the session gone (401 at /api/state): the copy is emptied, nothing waiting is sent (2.306.0 B, #2889: the outbox itself stays
//   for the next sign-in of the same account)
// - the outbox: kept at a new sign-in of the same account (then sent), dropped when an organisation of the account is gone
// - the service worker answers (and keeps) only the app shell: /, /capture, /manifest.json, /static/ (allow list)
// freelancer-matrix: wiki (the pages are in the private space of a person without an organisation)
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2238B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const clone = v => v === undefined ? v : JSON.parse(JSON.stringify(v));
const DAY = 864e5;

// ================= the service worker: an allow list (no server)
async function swCheck() {
  const SRC = fs.readFileSync(path.join(__dirname, '..', 'static', 'sw.js'), 'utf8');
  const ORIGIN = 'https://kalmido.example.com';
  const handlers = {}, cache = {put: async () => {}, match: async () => undefined, addAll: async () => {}, keys: async () => [], delete: async () => true};
  const self = {location: {origin: ORIGIN}, addEventListener: (k, f) => { handlers[k] = f; }, skipWaiting: () => {}, clients: {claim: async () => {}}};
  const ctx = {self, caches: {open: async () => cache, match: async () => undefined, keys: async () => []}, URL, Headers, Response, console, setTimeout, Promise,
    fetch: async () => ({ok: true, redirected: false, type: 'basic', status: 200, headers: new Headers({'content-type': 'text/html'}), clone() { return this; }})};
  vm.createContext(ctx);
  vm.runInContext(SRC, ctx, {filename: 'sw.js'});
  const answered = (p, method = 'GET') => { let r = null; handlers.fetch({request: {url: ORIGIN + p, method}, respondWith: x => { r = x; }}); if (r) r.catch(() => {}); return r !== null; };
  for (const p of ['/', '/?share=1', '/capture', '/capture?title=x', '/manifest.json', '/static/app.css', '/static/js/wiki.js?v=abc'])
    check(answered(p), 'service worker: the shell address is answered ' + p);
  for (const p of ['/api/state', '/s/abc', '/portal', '/ical/x.ics', '/agent-setup.sh', '/login', '/oidc/callback', '/share-inbox/meta', '/anything'])
    check(!answered(p), 'service worker: not on the allow list = left to the browser ' + p);
  check(!answered('/static/app.css', 'POST'), 'service worker: only GET');
}

// one browser: the copy's store (counting clears) and localStorage, shared by its windows
function browser() {
  const db = new Map();
  const store = {get: async k => clone(db.get(k)), put: async v => { db.set(v.k, clone(v)); }, del: async k => { db.delete(k); },
    all: async () => [...db.values()].map(clone), pre: async x => [...db.values()].filter(r => r.k.startsWith(x)).map(clone), nClear: 0,
    clear: async () => { store.nClear++; db.clear(); }, close: async () => {}};
  return {db, store, shared: {store: {}, wins: []}};
}
// a window of the browser; ck = this session's cookie (else boot's own new sign-in), offline = started without network
function win(br, user, {ck = null, offline = false, hash = 'wiki'} = {}) {
  const setup = w => {
    w.__wkoStore = br.store;
    if (ck) w.fetch = (u, o = {}) => {
      if (w.__offline) return Promise.reject(new TypeError('Failed to fetch'));
      const sg = o.signal && (ac => { if (o.signal.aborted) ac.abort(); else o.signal.addEventListener('abort', () => ac.abort()); return ac.signal; })(new AbortController());
      return fetch(new URL(String(u), B), {...o, headers: {...(o.headers || {}), Cookie: ck}, ...(sg ? {signal: sg} : {})});
    };
    if (offline) w.__offline = true;
  };
  return boot({user, hash, shared: br.shared, setup, ls: {'tasks.wkSpace': JSON.stringify('private')}});
}
const lsj = (br, k) => { const v = br.shared.store['tasks.' + k]; return v == null ? null : JSON.parse(v); };

(async () => {
  await swCheck();
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  const AK = CK;
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  CK = await login('frida');
  const st0 = await call('GET', '/api/state');
  check(!(st0.me.workspaces || []).length && /^[0-9a-f]{24}$/.test(st0.me.sgen || ''), 'setup: frida has no organisation, a sign-in mark ' + st0.me.sgen);
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'wiki'])].join(',');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: feats});
  const P1 = (await call('POST', '/api/wiki/pages', {space: 'private', path: 'Docs/Start', body: 'Alpha start text'})).id;
  check(P1, 'setup: a page');
  const T1 = (await call('POST', '/api/tasks', {title: 'Queued task'})).id;

  // ================= the copy carries the mark; the same session keeps it
  const br = browser();
  let w = await win(br, 'frida', {ck: CK});
  const c0 = await until(() => { const r = br.db.get('s:private'); return r && r.pages?.length ? r : null; });
  check(c0 && c0.g === st0.me.sgen && c0.uid === st0.me.id, 'the copy carries the sign-in mark ' + JSON.stringify(c0 && {g: c0.g, uid: c0.uid}));
  check(lsj(br, 'wko')?.g === st0.me.sgen && Date.now() - Date.parse(lsj(br, 'wko')?.at) < 60e3, 'the mark and the last online sync are kept ' + JSON.stringify(lsj(br, 'wko')));
  w.close();
  const n0 = br.store.nClear;
  w = await win(br, 'frida', {ck: CK});
  await until(() => w.eval(`!!S.me && (WK.idx.private?.pages || []).length > 0`));
  check(br.store.nClear === n0 && br.db.has('s:private'), `a start in the same session keeps the copy (clears ${br.store.nClear - n0})`);
  check(await w.eval(`wko_get('s:private').then(r => !!r)`), 'the same session reads the copy');
  w.close();

  // ================= another sign-in: the copy goes before anything is read
  br.db.set('x:999', {k: 'x:999', id: 999, sp: 'private', mine: 'old conflict', uid: st0.me.id, g: st0.me.sgen});
  w = await win(br, 'frida');
  const g2 = w.eval('S.me.sgen');
  check(g2 && g2 !== st0.me.sgen, 'setup: the new window has its own sign-in');
  check(br.store.nClear > n0 && !br.db.has('x:999'), `another sign-in empties the copy (clears ${br.store.nClear - n0})`);
  await until(() => br.db.get('s:private')?.g === g2);
  check([...br.db.values()].every(r => r.g === g2), 'the new copy carries the new mark');
  // a record of the previous sign-in is never read (also if it came back)
  br.db.set('s:old', {k: 's:old', sp: 'private', uid: st0.me.id, g: st0.me.sgen, pages: []});
  check(await w.eval(`wko_get('s:old').then(r => r === null)`), 'a record with another mark is not read');
  br.db.delete('s:old');
  w.close();

  // ================= 14 days without an online sync: an offline start empties the copy; a fresh one stays
  const CK2 = await login('frida');
  w = await win(br, 'frida', {ck: CK2});
  await until(() => br.db.get('s:private')?.g === w.eval('S.me.sgen'));
  w.close();
  let n1 = br.store.nClear;
  w = await win(br, 'frida', {ck: CK2, offline: true});
  await until(() => w.eval(`!!S.me && S.lists.length > 0`));
  check(br.store.nClear === n1 && br.db.has('s:private'), 'offline start, synced lately: the copy stays');
  await w.eval(`loadModule('wiki').then(() => { WK.idx = {}; return wk_load('private', true); })`).catch(() => {});
  check(w.eval(`!!WK.idx.private?.off && WK.idx.private.pages.length > 0`), 'offline start, synced lately: the pages come from the copy');
  w.close();
  br.shared.store['tasks.wko'] = JSON.stringify({...lsj(br, 'wko'), at: new Date(Date.now() - 15 * DAY).toISOString()});
  n1 = br.store.nClear;
  w = await win(br, 'frida', {ck: CK2, offline: true});
  await until(() => w.eval(`!!S.me && S.lists.length > 0`));
  check(await until(() => br.store.nClear > n1 && br.db.size === 0), `offline start after 15 days without a sync: the copy is gone (${br.db.size} records)`);
  w.close();
  // online after 15 days (same session): emptied too, then a fresh copy
  w = await win(br, 'frida', {ck: CK2});
  await until(() => br.db.get('s:private'));
  w.close();
  br.shared.store['tasks.wko'] = JSON.stringify({...lsj(br, 'wko'), at: new Date(Date.now() - 15 * DAY).toISOString()});
  n1 = br.store.nClear;
  w = await win(br, 'frida', {ck: CK2});
  check(await until(() => br.store.nClear > n1), 'online start after 15 days without a sync: the copy is emptied first');
  check(await until(() => Date.now() - Date.parse(lsj(br, 'wko')?.at) < 60e3), 'online: the last sync is today again');
  w.close();

  // ================= the outbox: a new sign-in of the same account keeps it (then sent)
  const q = [{method: 'PATCH', url: `/api/tasks/${T1}`, body: {title: 'Sent after a new sign-in'}, uid: st0.me.id, k: 'k2238a'}];
  br.shared.store['tasks.outbox'] = JSON.stringify(q);
  w = await win(br, 'frida', {hash: ''});
  check(await until(async () => (await call('GET', `/api/tasks/${T1}`)).title === 'Sent after a new sign-in'), 'a new sign-in of the same account: the waiting change is sent');
  w.close();

  // ================= the session gone (401): the copy goes, nothing is sent (the outbox stays: 2.306.0 B, #2889)
  const CK3 = await login('frida');
  w = await win(br, 'frida', {ck: CK3});
  await until(() => br.db.get('s:private')?.g === w.eval('S.me.sgen'));
  w.close();
  await fetch(B + 'api/auth/logout', {method: 'POST', headers: {...H, Cookie: CK3}});
  br.shared.store['tasks.outbox'] = JSON.stringify([{method: 'PATCH', url: `/api/tasks/${T1}`, body: {title: 'Never sent'}, uid: st0.me.id, k: 'k2238b'}]);
  check(br.db.size > 0, 'setup: a copy before the session ends');
  w = await win(br, 'frida', {ck: CK3});
  check(await until(() => br.db.size === 0), `401 at /api/state: the copy is gone (${br.db.size} records)`);
  check(await until(() => w.eval('OUT.q.length') === 1), '401 at /api/state: the waiting change stays in the outbox (2.306.0 B)');
  await sleep(300);
  check((await call('GET', `/api/tasks/${T1}`)).title === 'Sent after a new sign-in', '401: nothing waiting was sent');
  w.close();

  // ================= the outbox goes when an organisation of the account is gone
  CK = AK;
  await call('POST', '/api/users', {username: 'olga', display_name: 'Olga', password: 'password123', email: 'olga@example.com', orgs: []});
  const aid = (await call('GET', '/api/state')).me.id;
  const org = await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: aid});
  const oid = org.id || ((await call('GET', '/api/admin/orgs')).orgs || []).find(x => x.name === 'Alpha')?.id;
  const add = await call('PUT', `/api/orgs/${oid}/members`, {email: 'olga@example.com', role: 'member'});
  check(add.http < 300, 'setup: olga joins Alpha ' + add.http);
  const OK = await login('olga');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'}, OK);
  const so = await call('GET', '/api/state', null, OK);
  const T2 = (await call('POST', '/api/tasks', {title: 'Olga task'}, OK)).id;
  const bo = browser();
  w = await win(bo, 'olga', {ck: OK, hash: ''});
  await until(() => lsj(bo, 'orgIds'));
  check(JSON.stringify(lsj(bo, 'orgIds')) === JSON.stringify([oid]), 'the organisations are kept ' + JSON.stringify(lsj(bo, 'orgIds')));
  w.close();
  // a new sign-in while still a member: the waiting change is sent
  bo.shared.store['tasks.outbox'] = JSON.stringify([{method: 'PATCH', url: `/api/tasks/${T2}`, body: {title: 'Olga sent'}, uid: so.me.id, k: 'k2238c'}]);
  w = await win(bo, 'olga', {hash: ''});
  check(await until(async () => (await call('GET', `/api/tasks/${T2}`, null, OK)).title === 'Olga sent'), 'member, new sign-in: the waiting change is sent');
  w.close();
  const del = await call('DELETE', `/api/orgs/${oid}/members/${so.me.id}`);
  check(del.http < 300, 'setup: olga leaves Alpha ' + del.http);
  bo.shared.store['tasks.outbox'] = JSON.stringify([{method: 'PATCH', url: `/api/tasks/${T2}`, body: {title: 'Olga dropped'}, uid: so.me.id, k: 'k2238d'}]);
  w = await win(bo, 'olga', {ck: OK, hash: ''});
  check(await until(() => !bo.shared.store['tasks.outbox'] && w.eval('OUT.q.length') === 0), 'removed from an organisation: the outbox is empty');
  await sleep(300);
  check((await call('GET', `/api/tasks/${T2}`, null, OK)).title === 'Olga sent', 'removed from an organisation: nothing waiting was sent');
  check(JSON.stringify(lsj(bo, 'orgIds')) === '[]', 'the organisations kept now: none');
  w.close();

  console.log(`\n${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
