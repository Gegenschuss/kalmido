// 2.574.0 (#4692): the service worker sends a rebased outbox entry with its own key e.ik, like core.js outFlush (e.ik || e.k)
// kalmido-suite: nodata
// No browser, no server: static/sw.js runs in a vm with a fake IndexedDB and fetch.
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
    fetch: async (u, o = {}) => { if (u === '/api/me') return jres(200, {id: me}); sent.push({m: o.method, u, key: (o.headers || {})['Idempotency-Key']}); return jres(200, {ok: true}); },
    Response, URL, setTimeout, console, atob, Uint8Array, JSON,
  });
  vm.runInContext(SW, ctx);
  idb.ops.set('a', {k: 'a', n: 1, method: 'PATCH', url: '/api/tasks/5', body: {title: 'rebased'}, uid: me, ik: 'a-rebased'});
  idb.ops.set('b', {k: 'b', n: 2, method: 'PATCH', url: '/api/tasks/6', body: {title: 'plain'}, uid: me});
  await vm.runInContext('swOutboxSend()', ctx);
  check(sent.length === 2, 'both entries are sent ' + JSON.stringify(sent));
  check(sent[0] && sent[0].key === 'a-rebased', 'an entry with ik sends ik as the Idempotency-Key ' + JSON.stringify(sent[0]));
  check(sent[1] && sent[1].key === 'b', 'an entry without ik still sends k ' + JSON.stringify(sent[1]));
  check(!idb.ops.has('a') && !idb.ops.has('b'), 'both are deleted by their storage key k');
  check(posted.some(m => (m.del || []).includes('a')), 'the tabs are told k "a" is gone');
  console.log(F.length ? `FAILED ${F.length} of ${ok + F.length}` : `OK ${ok}`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
