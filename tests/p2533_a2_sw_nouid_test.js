// 2.533.0 A2 (#4318 A15): the service worker keeps an outbox entry without uid (stashed before the sign-in was known).
// kalmido-suite: after=p2359_a_outbox_ui nodata
// No browser, no server: static/sw.js runs in a vm with a fake IndexedDB and fetch.
// - an entry of nobody is never sent by the service worker (#2875 stays) and is no more deleted: it stays in the queue
// - the queue stops there (order: the entries after it wait for the app too) and the app is told once (swres nouid)
// - the app (core.js obxDrain) shows a hint for it
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const SRC = process.env.KALMIDO_SRC || path.join(__dirname, '..');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const jres = (st, j) => new Response(JSON.stringify(j), {status: st, headers: {'content-type': 'application/json'}});

(async () => {
  const SW = fs.readFileSync(path.join(SRC, 'static', 'sw.js'), 'utf8');
  const me = 7, sent = [], posted = [];
  const idb = {ops: new Map(), meta: new Map([['uid', {k: 'uid', v: me}]])};
  const req = fn => { const r = {}; setTimeout(() => { try { r.result = fn(); r.onsuccess && r.onsuccess(); } catch (e) { r.error = e; r.onerror && r.onerror(); } }, 0); return r; };
  const fakeDb = {objectStoreNames: {contains: () => true}, transaction: () => ({objectStore: n => ({
    get: k => req(() => idb[n].get(k)), getAll: () => req(() => [...idb[n].values()]), put: v => req(() => idb[n].set(v.k, v)), delete: k => req(() => idb[n].delete(k))})})};
  class BC { postMessage(m) { posted.push(m); } close() {} }
  const ctx = vm.createContext({
    self: {addEventListener() {}, location: {origin: 'https://kalmido.example'}, clients: {matchAll: async () => []}, navigator: {}},
    caches: {open: async () => ({keys: async () => [], delete: async () => true, put: async () => {}}), match: async () => undefined},
    indexedDB: {open: () => req(() => fakeDb)}, BroadcastChannel: BC,
    fetch: async (u, o = {}) => { if (u === '/api/me') return jres(200, {id: me}); sent.push((o.method || 'GET') + ' ' + u); return jres(200, {ok: true}); },
    Response, URL, setTimeout, console, atob, Uint8Array, JSON,
  });
  vm.runInContext(SW, ctx);
  idb.ops.set('a', {k: 'a', n: 1, method: 'PATCH', url: '/api/tasks/5', body: {title: 'mine'}, uid: me});
  idb.ops.set('b', {k: 'b', n: 2, method: 'PATCH', url: '/api/tasks/5', body: {title: 'nobody'}});
  idb.ops.set('c', {k: 'c', n: 3, method: 'PATCH', url: '/api/tasks/6', body: {title: 'after'}, uid: me});
  await vm.runInContext('swOutboxSend()', ctx);
  check(sent.length === 1 && sent[0] === 'PATCH /api/tasks/5' && !idb.ops.has('a'), 'the own entry before goes out ' + JSON.stringify(sent));
  check(idb.ops.has('b'), 'the entry without uid is kept (not deleted)');
  check(!posted.some(m => (m.del || []).includes('b')), 'no tab is told it is gone');
  check(idb.ops.has('c') && sent.length === 1, 'the entry after it waits for the app (order)');
  const res = (idb.meta.get('swres') || {}).v || [];
  check(res.filter(x => x.nouid).length === 1, 'the app is told once ' + JSON.stringify(res));
  await vm.runInContext('swOutboxSend()', ctx);
  check(sent.length === 1 && idb.ops.has('b'), 'a second sync sends nothing either (never sent, #2875)');
  check(((idb.meta.get('swres') || {}).v || []).filter(x => x.nouid).length === 1, 'still one note after the second sync');
  const core = fs.readFileSync(path.join(SRC, 'static', 'js', 'core.js'), 'utf8');
  const key = 'Offline changes made before the sign-in were kept and are sent from here';
  check(/function obxDrain[\s\S]{0,1500}j\.nouid[\s\S]{0,200}tr\('Offline changes made before the sign-in/.test(core), 'the app shows the hint (obxDrain)');
  for (const f of fs.readdirSync(path.join(SRC, 'static', 'i18n')).filter(f => f.endsWith('.json')))
    check(JSON.parse(fs.readFileSync(path.join(SRC, 'static', 'i18n', f), 'utf8'))[key], 'hint translated: ' + f);
  console.log(F.length ? `FAILED ${F.length} of ${ok + F.length}` : `OK ${ok}`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
