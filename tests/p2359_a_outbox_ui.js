// 2.359.0 A (#3023) UI tests (jsdom), fresh DB: the offline queue never throws a change away on a server error
// - a create made offline that the server refuses (403): its text and the change of it made afterwards (on its temporary id)
//   wait in the conflicts dialog; the change is never sent as PATCH /api/tasks/-123; no reload
// - a server error (JSON 500, the maintenance 503, 429) keeps the change first in the queue: it goes again later and reaches the
//   server exactly once more; an HTML 500 page = "server not reachable" (waits, no reload)
// - an HTML 404 page is an error like any other (no "session expired" reload): a queued change with it waits in the dialog
// - the conflicts dialog shows the whole change also for a batch (tags) and a completion, not only a count
// - a save of typed text on a temporary id: with the real id known -> sent to it; with its create failed -> into the dialog
// - images pasted into the quick add offline: kept (IndexedDB) and uploaded after the create; a refused create names them
// - the service worker never sends an entry with a temporary id and leaves a server error to a later sync (entry kept)
// - another account signs in while changes of the previous one wait: asked first; "Cancel" keeps them
// kalmido-suite: fresh
const vm = require('vm');
const {boot, errs, B, login, until} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const jres = (st, j) => new Response(JSON.stringify(j), {status: st, headers: {'content-type': 'application/json'}});
const hres = st => new Response('<!doctype html><title>Error</title><h1>Error</h1>', {status: st, headers: {'content-type': 'text/html; charset=utf-8'}});
// every request that leaves the window [method, path]; fake(m, p, o) may answer instead of the server (a Response) or let it pass
const stub = (w, fake) => { const calls = [], of = w.fetch; w.fetch = (u, o = {}) => { const m = (o.method || 'GET').toUpperCase(), p = new URL(String(u), B).pathname; if (w.__offline) return of(u, o); calls.push([m, p]); const r = fake && fake(m, p, o); return r ? Promise.resolve(r) : of(u, o); }; return calls; };
const online = w => { w.__offline = false; w.eval('OUT.retryAt = 0'); w.dispatchEvent(new w.Event('online')); };
const rejected = w => w.eval('S.conflicts').filter(c => c.field === 'rejected');

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const P = (await call('POST', '/api/lists', {name: 'Flyers'})).id;
  const mk = async title => (await call('POST', '/api/tasks', {title, list_id: P})).id;
  const T1 = await mk('Print the flyer'), T2 = await mk('Book the hall'), T3 = await mk('Order paper');
  const qf = new Map();  // the stand-in for IndexedDB "kalmido-qfiles" (jsdom has none)
  const w = await boot({user: 'alice', hash: 'l/' + P, setup: x => { x.__qfStore = {put: async v => { qf.set(v.tmp, v); }, all: async () => [...qf.values()], del: async k => { qf.delete(k); }}; }});
  check(await until(() => w.eval('OUT.me === S.me.id')), 'setup: the server said who is logged in');

  // ================= a refused create: the change on its temporary id waits too, never sent
  let fake = null;
  const calls = stub(w, (m, p, o) => fake && fake(m, p, o));
  fake = (m, p) => m === 'POST' && p === '/api/tasks' ? jres(403, {error: 'no permission'}) : null;
  w.__offline = true;
  const tmp = (await w.eval(`api('POST', '/api/tasks', {title: 'Made on the train', list_id: ${P}})`)).id;
  await w.eval(`api('PATCH', '/api/tasks/${tmp}', {content: 'Notes typed on the train'})`);
  check(tmp < 0 && w.eval('OUT.q.length') === 2, `two changes wait (${tmp}, ${w.eval('OUT.q.length')})`);
  online(w);
  check(await until(() => w.eval('OUT.q.length') === 0 && !w.eval('OUT.flushing')), 'the queue went through');
  check(!calls.some(([, p]) => /\/-\d+/.test(p)), 'nothing was sent to a temporary id ' + JSON.stringify(calls.filter(([, p]) => /\/-\d+/.test(p))));
  let rj = rejected(w);
  check(rj.some(c => c.mine.includes('Made on the train') && /permission/.test(c.server)), 'the refused create waits in the dialog with its reason ' + JSON.stringify(rj));
  check(rj.some(c => c.mine.includes('Notes typed on the train')), 'the change of the new task waits there too ' + JSON.stringify(rj));
  w.eval('conflictModal()');
  const md = await until(() => [...w.document.querySelectorAll('.modal')].find(x => /Offline change not saved/.test(x.textContent)));
  check(!!md && /Notes typed on the train/.test(md.textContent) && !!md.querySelector('[data-cf="copy"]'), 'the dialog shows both texts with Copy');
  md?.querySelector('[data-m="all-server"]')?.click(); md?.remove();
  w.eval("S.conflicts = []; LS.set('conflicts', [])");

  // ================= a server error keeps the change: JSON 500, 503 (maintenance), 429
  for (const [st, j] of [[500, {error: 'Server error'}], [503, {error: 'Maintenance', code: 'maintenance'}], [429, {error: 'Too many requests'}]]) {
    let n = 1; calls.length = 0;
    fake = (m, p) => m === 'PATCH' && p === '/api/tasks/' + T1 && n-- > 0 ? jres(st, j) : null;
    w.__offline = true;
    await w.eval(`api('PATCH', '/api/tasks/${T1}', {title: 'Print the flyer ${st}'})`);
    online(w);
    check(await until(() => calls.filter(([m, p]) => m === 'PATCH' && p === '/api/tasks/' + T1).length >= 1 && !w.eval('OUT.flushing')), `${st}: the first try went out`);
    check(w.eval('OUT.q.length') === 1 && w.eval('OUT.q[0].tries') === 1 && !rejected(w).length, `${st}: the change is still first in the queue (${w.eval('OUT.q.length')})`);
    check(await until(() => w.eval('OUT.q.length') === 0, {timeout: 20000}), `${st}: it went again later`);
    check((await call('GET', '/api/tasks/' + T1)).title === `Print the flyer ${st}`, `${st}: the server has it`);
    check(calls.filter(([m, p]) => m === 'PATCH' && p === '/api/tasks/' + T1).length === 2 && !rejected(w).length, `${st}: sent exactly once more, nothing in the dialog`);
  }
  // an HTML 500 page (no JSON: the database restarts): server not reachable, the change waits
  {
    let n = 1; calls.length = 0;
    fake = (m, p) => m === 'PATCH' && p === '/api/tasks/' + T2 && n-- > 0 ? hres(500) : null;
    w.__offline = true;
    await w.eval(`api('PATCH', '/api/tasks/${T2}', {title: 'Book the big hall'})`);
    online(w);
    check(await until(() => w.eval('OUT.q.length') === 0, {timeout: 20000}), 'HTML 500: the change went again later');
    check((await call('GET', '/api/tasks/' + T2)).title === 'Book the big hall' && !rejected(w).length, 'HTML 500: the server has it');
  }

  // ================= an HTML 404 page: an error, not "session expired"
  fake = (m, p) => m === 'PATCH' && p === '/api/tasks/' + T3 ? hres(404) : null;
  const e404 = await w.eval(`rawFetch('PATCH', '/api/tasks/${T3}', {title: 'x'}).then(() => null, e => ({m: e.message, st: e.status}))`);
  check(e404 && e404.m !== 'auth' && e404.st === 404, 'HTML 404: an error with its status, no reload ' + JSON.stringify(e404));
  w.__offline = true;
  await w.eval(`api('PATCH', '/api/tasks/${T3}', {title: 'Order the good paper'})`);
  online(w);
  check(await until(() => w.eval('OUT.q.length') === 0 && !w.eval('OUT.flushing')), 'HTML 404: the queue did not stay stuck');
  check(rejected(w).some(c => c.mine.includes('Order the good paper') && c.tid === T3), 'HTML 404: the change waits in the dialog');
  w.eval("S.conflicts = []; LS.set('conflicts', [])");

  // ================= the whole change in the dialog: a batch (tags), a completion
  fake = (m, p) => m === 'POST' && (p === '/api/tasks/batch' || p === `/api/tasks/${T3}/complete`) ? jres(403, {error: 'no permission'}) : null;
  w.__offline = true;
  await w.eval(`api('POST', '/api/tasks/batch', {ids: [${T3}], action: 'patch', data: {add_tags: ['urgent']}})`);
  await w.eval(`api('POST', '/api/tasks/${T3}/complete', {})`);
  online(w);
  check(await until(() => w.eval('OUT.q.length') === 0 && !w.eval('OUT.flushing')), 'batch + completion: the queue went through');
  rj = rejected(w);
  check(rj.some(c => /urgent/.test(c.mine) && /patch/.test(c.mine)), 'the batch with its tags waits in the dialog ' + JSON.stringify(rj));
  check(rj.some(c => /complete/.test(c.mine) && c.tid === T3), 'the completion waits in the dialog ' + JSON.stringify(rj));
  w.eval("S.conflicts = []; LS.set('conflicts', [])");
  fake = null;

  // ================= typed text on a temporary id (doSave)
  calls.length = 0;
  w.eval(`HIST.ids['-424242'] = ${T2}`);
  w.eval(`S.tasks.set(-424242, {...S.tasks.get(${T2}), id: -424242}); queueSave(-424242, 'title', 'Book the hall early')`);
  await w.eval('flushSaves()');
  check(await until(async () => (await call('GET', '/api/tasks/' + T2)).title === 'Book the hall early'), 'temporary id with its real id: the text went to the real task');
  w.eval(`S.tasks.set(-535353, {...S.tasks.get(${T2}), id: -535353, title: 'Lost create'}); queueSave(-535353, 'title', 'Words that must not get lost')`);
  await w.eval('flushSaves()');
  check(!calls.some(([, p]) => /\/-\d+/.test(p)), 'no save went to a temporary id ' + JSON.stringify(calls));
  check(rejected(w).some(c => c.mine.includes('Words that must not get lost')), 'its create failed: the typed text waits in the dialog');
  w.eval("S.conflicts = []; LS.set('conflicts', [])");

  // ================= the quick add's files made offline: kept, uploaded once the task went out; a refused create names them
  const qin = () => w.document.querySelector('#qinput');
  for (const [title, refuse] of [['Flyer with a picture', false], ['Refused with a picture', true]]) {
    fake = refuse ? (m, p) => m === 'POST' && p === '/api/tasks' ? jres(403, {error: 'no permission'}) : null : null;
    w.__offline = true;
    w.__qf = new w.File(['fake png bytes'], refuse ? 'refused.png' : 'shot.png', {type: 'image/png'});
    w.eval('S.qfiles.qinput = [window.__qf]');
    check(!!qin(), 'the quick add box is there');
    qin().value = title;
    await w.eval(`submitQuick(document.querySelector('#qinput'))`);
    check(await until(() => qf.size === 1), `${title}: the file is kept while offline (${qf.size})`);
    online(w);
    check(await until(() => qf.size === 0 && w.eval('OUT.q.length') === 0, {timeout: 20000}), `${title}: sent, the kept file is gone (${qf.size})`);
    if (!refuse) {
      const t = (await call('GET', '/api/state')).tasks.find(x => x.title === title);
      const full = t && await call('GET', '/api/tasks/' + t.id);
      check(!!full && (full.attachments || []).some(a => a.name === 'shot.png'), `${title}: the file is attached to the new task ` + JSON.stringify((full || {}).attachments));
    } else check(rejected(w).some(c => /refused\.png/.test(c.mine)), `${title}: the dialog names the file ` + JSON.stringify(rejected(w)));
  }
  w.eval("S.conflicts = []; LS.set('conflicts', [])");
  fake = null;

  // ================= the service worker
  const SW = await (await fetch(B + 'sw.js')).text();
  const me = w.eval('S.me.id'), swFetch = [];
  let swAnswer = () => jres(200, {ok: true});
  const idb = {ops: new Map(), meta: new Map([['uid', {k: 'uid', v: me}]])};
  const req = fn => { const r = {}; setTimeout(() => { try { r.result = fn(); r.onsuccess && r.onsuccess(); } catch (e) { r.error = e; r.onerror && r.onerror(); } }, 0); return r; };
  const fakeDb = {objectStoreNames: {contains: () => true}, transaction: () => ({objectStore: n => ({
    get: k => req(() => idb[n].get(k)), getAll: () => req(() => [...idb[n].values()]), put: v => req(() => idb[n].set(v.k, v)), delete: k => req(() => idb[n].delete(k))})})};
  const swCtx = vm.createContext({
    self: {addEventListener() {}, location: {origin: 'https://kalmido.example'}, clients: {matchAll: async () => []}, navigator: {}},
    caches: {open: async () => ({keys: async () => [], delete: async () => true, put: async () => {}}), match: async () => undefined},
    indexedDB: {open: () => req(() => fakeDb)},
    fetch: async (u, o = {}) => { if (u === '/api/me') return jres(200, {id: me}); swFetch.push((o.method || 'GET') + ' ' + u); return swAnswer(u); },
    Response, URL, setTimeout, console, atob, Uint8Array, JSON,
  });
  vm.runInContext(SW, swCtx);
  idb.ops.set('a', {k: 'a', n: 1, method: 'PATCH', url: '/api/tasks/-777', body: {title: 'one'}, uid: me});
  idb.ops.set('b', {k: 'b', n: 2, method: 'PATCH', url: `/api/tasks/${T1}`, body: {title: 'two'}, uid: me});
  await vm.runInContext('swOutboxSend()', swCtx);
  check(!swFetch.length && idb.ops.has('a') && idb.ops.has('b'), 'service worker: a temporary id is not sent, the rest waits for the app ' + JSON.stringify(swFetch));
  idb.ops.clear();
  idb.ops.set('c', {k: 'c', n: 1, method: 'POST', url: '/api/tasks', body: {title: 'three', parent_id: -778}, uid: me});
  await vm.runInContext('swOutboxSend()', swCtx);
  check(!swFetch.length && idb.ops.has('c'), 'service worker: a temporary parent id is not sent either');
  idb.ops.clear();
  swAnswer = () => jres(500, {error: 'Server error'});
  idb.ops.set('d', {k: 'd', n: 1, method: 'PATCH', url: `/api/tasks/${T1}`, body: {title: 'four'}, uid: me});
  const thrown = await vm.runInContext('swOutboxSend()', swCtx).then(() => false, () => true);
  check(thrown && idb.ops.has('d') && swFetch.length === 1, 'service worker: a server error keeps the entry and asks for a later sync');
  w.close();

  // ================= another account signs in while the previous one's changes wait
  const bob = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'})).id;
  const asked = [], outs = [];
  const ent = [{method: 'PATCH', url: `/api/tasks/${T1}`, body: {title: 'Changed by the one before'}, uid: bob, k: 'bobk1'}];
  const wb = await boot({user: 'alice', hash: 'l/' + P, ls: {'tasks.uid': String(bob), 'tasks.outbox': JSON.stringify(ent)},
    setup: x => { x.confirm = t => { asked.push(t); return false; }; const of = x.fetch; x.fetch = (u, o = {}) => { if (/auth\/logout/.test(String(u))) outs.push(1); return of(u, o); }; }});
  check(await until(() => asked.length > 0), 'another account: asked first');
  check(/previous account/.test(asked[0] || '') && !/Changed by the one before/.test(asked[0] || ''), 'the question names the number only, not the content: ' + asked[0]);
  check(await until(() => outs.length > 0), 'Cancel: signed out again (the previous account can sign in)');
  check(/Changed by the one before/.test(wb.__store['tasks.outbox'] || ''), 'Cancel: the previous account\'s change is kept');
  check((await call('GET', '/api/tasks/' + T1)).title !== 'Changed by the one before', 'and was not sent as the new account');
  wb.close();

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  console.log(`p2359_a_outbox_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
