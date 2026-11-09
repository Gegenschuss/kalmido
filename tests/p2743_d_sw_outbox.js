// 2.743.0 D (#4284) the user boundary of the service worker's Background Sync (static/sw.js swOutboxSend) in a vm sandbox
// kalmido-suite: after=p2743_d_logout_ui
// sw.js is read from the working copy (no server needed). The sandbox stands in for IndexedDB, fetch and the window list.
// - another account's entry (uid) is never sent and stays for the app; the signed-in account's entries go around it
// - /api/me names someone else, or no one (signed out, a sign-in page): nothing is sent, everything stays
// - no account remembered on this device (meta uid): not even /api/me is asked
// - the entries go in their order (n), not in the order the store hands them out
// - a temporary id: the create's real id replaces it in the next URL and in parent_id, and is kept for the app (meta swmap)
// - every write carries the app's request header and the Idempotency-Key (the entry's own key, ik before k), same origin
// - an entry without an owner (made before the sign-in was known) stops the queue (kept, noted for the app)
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const jres = (st, j) => new Response(JSON.stringify(j), {status: st, headers: {'content-type': 'application/json'}});

const SW = fs.readFileSync(path.join(__dirname, '..', 'static', 'sw.js'), 'utf8');
const ME = 7, OTHER = 8;

function sandbox({meUid = ME, uidMeta = ME, answer = () => jres(200, {ok: true})} = {}) {
  const idb = {ops: new Map(), meta: new Map(uidMeta ? [['uid', {k: 'uid', v: uidMeta}]] : [])}, sent = [];
  const req = fn => { const r = {}; setTimeout(() => { try { r.result = fn(); if (r.onsuccess) r.onsuccess(); } catch (e) { r.error = e; if (r.onerror) r.onerror(); } }, 0); return r; };
  const fakeDb = {objectStoreNames: {contains: () => true}, transaction: () => ({objectStore: n => ({
    get: k => req(() => idb[n].get(k)), getAll: () => req(() => [...idb[n].values()]), put: v => req(() => idb[n].set(v.k, v)), delete: k => req(() => idb[n].delete(k))})})};
  let meAsked = 0;
  const ctx = vm.createContext({
    self: {addEventListener() {}, location: {origin: 'https://kalmido.example'}, clients: {matchAll: async () => []}, navigator: {}},
    caches: {open: async () => ({keys: async () => [], delete: async () => true, put: async () => {}}), match: async () => undefined},
    indexedDB: {open: () => req(() => fakeDb)},
    fetch: async (u, o = {}) => {
      if (u === '/api/me') { meAsked++; return typeof meUid === 'function' ? meUid() : jres(200, {id: meUid}); }
      const body = o.body ? JSON.parse(o.body) : undefined;
      sent.push({method: o.method || 'GET', url: u, body, headers: {...(o.headers || {})}, credentials: o.credentials});
      return answer(u, o, body);
    },
    Response, URL, setTimeout, console, atob, Uint8Array, JSON,
  });
  vm.runInContext(SW, ctx);
  const add = (...es) => { for (const e of es) idb.ops.set(e.k, e); };
  return {idb, sent, add, run: () => vm.runInContext('swOutboxSend()', ctx), meAsked: () => meAsked};
}

(async () => {
  // ================= another account's entry
  {
    const s = sandbox();
    s.add({k: 'a1', n: 1, method: 'PATCH', url: '/api/tasks/11', body: {title: 'mine one'}, uid: ME},
      {k: 'b1', n: 2, method: 'PATCH', url: '/api/tasks/12', body: {title: 'not mine'}, uid: OTHER},
      {k: 'a2', n: 3, method: 'PATCH', url: '/api/tasks/13', body: {title: 'mine two'}, uid: ME});
    await s.run();
    check(!s.sent.some(x => x.url === '/api/tasks/12' || x.body?.title === 'not mine'), 'another account\'s entry is never sent ' + JSON.stringify(s.sent.map(x => x.url)));
    check(s.sent.map(x => x.url).join() === '/api/tasks/11,/api/tasks/13', 'the own entries go, around the foreign one ' + JSON.stringify(s.sent.map(x => x.url)));
    check(s.idb.ops.has('b1') && !s.idb.ops.has('a1') && !s.idb.ops.has('a2'), 'the foreign entry stays in the store for the app, the sent ones are gone');
  }
  // ================= /api/me names someone else / no one
  for (const [what, me] of [['someone else signed in', () => jres(200, {id: OTHER})], ['signed out (401)', () => jres(401, {error: 'Not signed in', auth: 'login'})],
    ['a sign-in page (redirect)', () => new Response('', {status: 302, headers: {location: '/login'}})], ['an HTML page', () => new Response('<html></html>', {status: 200, headers: {'content-type': 'text/html'}})]]) {
    const s = sandbox({meUid: me});
    s.add({k: 'a1', n: 1, method: 'PATCH', url: '/api/tasks/11', body: {title: 'mine'}, uid: ME});
    await s.run();
    check(s.meAsked() === 1 && !s.sent.length && s.idb.ops.has('a1'), `${what}: nothing is sent, the entry stays ${JSON.stringify(s.sent)}`);
  }
  // ================= no account remembered on this device
  {
    const s = sandbox({uidMeta: null});
    s.add({k: 'a1', n: 1, method: 'PATCH', url: '/api/tasks/11', body: {title: 'mine'}, uid: ME});
    await s.run();
    check(s.meAsked() === 0 && !s.sent.length && s.idb.ops.has('a1'), 'no account remembered: not even /api/me is asked, nothing sent');
  }
  // ================= order
  {
    const s = sandbox();
    s.add({k: 'z', n: 30, method: 'PATCH', url: '/api/tasks/3', body: {title: 'third'}, uid: ME},
      {k: 'x', n: 10, method: 'PATCH', url: '/api/tasks/1', body: {title: 'first'}, uid: ME},
      {k: 'y', n: 20, method: 'PATCH', url: '/api/tasks/2', body: {title: 'second'}, uid: ME});
    await s.run();
    check(s.sent.map(x => x.body.title).join() === 'first,second,third', 'the entries go in their order ' + JSON.stringify(s.sent.map(x => x.body.title)));
  }
  // ================= temporary id
  {
    const s = sandbox({answer: (u, o) => u === '/api/tasks' && o.method === 'POST' ? jres(200, {id: 42}) : jres(200, {ok: true})});
    s.idb.meta.set('idmap', {k: 'idmap', v: {'-3': 33}});  // a real id the app already knows
    s.add({k: 'c1', n: 1, method: 'POST', url: '/api/tasks', body: {title: 'made offline'}, uid: ME, tmp: -5},
      {k: 'c2', n: 2, method: 'PATCH', url: '/api/tasks/-5', body: {title: 'renamed offline'}, uid: ME},
      {k: 'c3', n: 3, method: 'POST', url: '/api/tasks', body: {title: 'a sub task', parent_id: -5}, uid: ME},
      {k: 'c4', n: 4, method: 'POST', url: '/api/tasks/batch', body: {action: 'complete', ids: [-3, -5]}, uid: ME});
    await s.run();
    const urls = s.sent.map(x => x.method + ' ' + x.url);
    check(urls.join() === 'POST /api/tasks,PATCH /api/tasks/42,POST /api/tasks,POST /api/tasks/batch', 'the temporary id becomes the real one in the URL ' + JSON.stringify(urls));
    check(s.sent[2]?.body.parent_id === 42, 'and in parent_id ' + JSON.stringify(s.sent[2]?.body));
    check(JSON.stringify(s.sent[3]?.body.ids) === '[33,42]', 'and in the ids of a batch (also one the app knew) ' + JSON.stringify(s.sent[3]?.body));
    check(s.idb.meta.get('swmap')?.v?.[-5] === 42, 'the pair is kept for the app (swmap) ' + JSON.stringify(s.idb.meta.get('swmap')));
    check(!s.sent.some(x => /\/-\d+/.test(x.url)), 'a temporary id never goes to the server');
  }
  // ================= request header and Idempotency-Key
  {
    const s = sandbox();
    s.add({k: 'k-own', n: 1, method: 'PATCH', url: '/api/tasks/1', body: {title: 'one'}, uid: ME},
      {k: 'k-base', ik: 'k-rebased', n: 2, method: 'DELETE', url: '/api/tasks/2', uid: ME});
    await s.run();
    check(s.sent[0]?.headers['Idempotency-Key'] === 'k-own' && s.sent[1]?.headers['Idempotency-Key'] === 'k-rebased', 'Idempotency-Key = the entry\'s key, ik before k ' + JSON.stringify(s.sent.map(x => x.headers)));
    check(s.sent.every(x => x.headers['X-Requested-With'] === 'kalmido' && x.credentials === 'same-origin'), 'every write with the app\'s header, same origin');
    check(s.sent[0]?.headers['Content-Type'] === 'application/json' && s.sent[1] && s.sent[1].body === undefined && !s.sent[1].headers['Content-Type'], 'a body is JSON, a DELETE has none');
  }
  // ================= an entry without an owner
  {
    const s = sandbox();
    s.add({k: 'o1', n: 1, method: 'PATCH', url: '/api/tasks/1', body: {title: 'mine'}, uid: ME},
      {k: 'o2', n: 2, method: 'PATCH', url: '/api/tasks/2', body: {title: 'nobody\'s'}},
      {k: 'o3', n: 3, method: 'PATCH', url: '/api/tasks/3', body: {title: 'mine after'}, uid: ME});
    await s.run();
    check(s.sent.map(x => x.url).join() === '/api/tasks/1' && s.idb.ops.has('o2') && s.idb.ops.has('o3'), 'an entry of nobody stops the queue, it and the rest stay ' + JSON.stringify(s.sent.map(x => x.url)));
    check((s.idb.meta.get('swres')?.v || []).some(x => x.nouid), 'the app is told (swres nouid)');
  }

  console.log(`p2743_d_sw_outbox: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
