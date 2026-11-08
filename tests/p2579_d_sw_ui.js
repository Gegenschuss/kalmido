// 2.579.0 UI test, part D (#4283): the real service worker with the network really gone (Firefox).
// kalmido-suite: fresh
// freelancer-matrix: tasks (alice has no organisation: her private workspace, the queue of her own tasks)
// The suites before cut the network only inside the page (tests/boot.js __offline: fetch throws), the service worker and the
// browser's own loads never noticed. Here Firefox reaches the test server only through a small TCP relay of this file (an own
// port on 127.0.0.1); the relay closed = the port refuses every connection and the open ones are cut, so the page, its
// scripts, the modules loaded on demand and the worker see the network gone the way a device does.
// - online: the app starts, the queue lives in IndexedDB (OBX.on, no silent fallback to localStorage), the worker takes over
//   and holds the shell and the modules loaded on demand
// - network gone: a new load of the page starts from the worker's cache (the list with its task), a module that was never
//   loaded (stats) loads from the cache, a new task and a rename wait in the queue (IndexedDB "ops") and nothing reaches the server
// - network back: the queue goes out by itself, the server has the new task exactly once and the new title; the queue is empty;
//   a new start (which reads the queue again) sends nothing twice
// - clearLocal (sign-out / another person) empties "ops" in IndexedDB too (read with an own open() of the database)
// The waits are on states (the relay's port refusing, the page's queue, the server's rows), never on a fixed time.
// P2579D_SHOTS=<dir> = screenshots.
const net = require('net');
const {B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2579_d_sw_ui', check, shots: 'P2579D_SHOTS', lazy: true, allWs: true});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, ms = 15000) => require('./boot').until(fn, {timeout: ms, step: 150});

// the relay: 127.0.0.1:<own port> -> the test server. close() refuses new connections and cuts the open ones (Firefox's
// keep-alive connections too), open() listens on the same port again (the page's origin stays the same)
function relay(target) {
  const to = new URL(target), socks = new Set();
  let srv = null, port = 0;
  const conn = c => {
    const s = net.connect(+to.port || 80, to.hostname);
    const end = () => { c.destroy(); s.destroy(); socks.delete(c); socks.delete(s); };
    socks.add(c); socks.add(s);
    c.on('error', end); s.on('error', end); c.on('close', end); s.on('close', end);
    c.pipe(s); s.pipe(c);
  };
  const listen = () => new Promise(res => {
    const x = net.createServer(conn);
    x.once('error', e => res({e}));
    x.listen(port, '127.0.0.1', () => res({x}));
  });
  return {
    get port() { return port; },
    async open() {
      // the same port again: a moment of EADDRINUSE right after close() is waited out (a state, not a sleep)
      let got = null;
      await until(async () => { got = await listen(); return !!got.x; }, 15000);
      if (!got.x) throw new Error('relay: port ' + port + ' could not be opened again: ' + got.e?.message);
      srv = got.x; port = srv.address().port;
      return port;
    },
    close() {
      return new Promise(res => {
        if (!srv) return res();
        const s = srv; srv = null;
        s.close(() => res());
        for (const x of socks) x.destroy();
        socks.clear();
      });
    },
  };
}
// true = the port refuses a connection (the network is gone for whoever comes over it)
const refused = port => new Promise(res => {
  const s = net.connect(port, '127.0.0.1');
  s.once('connect', () => { s.destroy(); res(false); });
  s.once('error', () => res(true));
});

(async () => {
  check((await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', lang: 'en'})})).ok, 'setup');
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const L = (await call('POST', '/api/lists', {name: 'Shed'})).id;
  const T = (await call('POST', '/api/tasks', {title: 'Oil the hinges', list_id: L})).id;
  check(L > 0 && T > 0, 'a list with a task');
  const state = async () => (await call('GET', '/api/state')).tasks || [];
  const NEW = 'Sweep the floor offline', REN = 'Oil the hinges (renamed offline)', GONE = 'Never sent (cleared)';

  const R = relay(B);
  await R.open();
  const O = `http://127.0.0.1:${R.port}/`;
  check(R.port > 0 && R.port !== +new URL(B).port, `the relay listens on its own port (${R.port})`);

  await firefox(async ({ev, nav, until: pageUntil, shot}) => {
    const pu = (expr, ms = 15000) => pageUntil(expr, {timeout: ms, step: 150});
    await nav(O + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: sign-in over the relay');

    // ---- online: the start, the queue in IndexedDB, the worker in control with a full cache
    await nav(O + `#l/${L}`);
    check(await pu(`typeof S !== 'undefined' && S.booted && !!document.querySelector('#view .trow[data-id="${T}"]')`), 'online: the app starts over the relay, the list opens');
    // #4283 (review of p264a_c_ui): the queue is in IndexedDB here - a silent fallback to localStorage is red, not "either"
    check(await pu(`OBX.on === true && !!OBX.st`), 'online: the offline queue lives in IndexedDB (OBX.on), no silent fallback to localStorage');
    // 2.663.0 (#4200): the last state is kept in IndexedDB "kalmido-start" (offcache.js, written when idle), no longer in localStorage
    check(await pu(`typeof OC !== 'undefined' && OC.wrote > 0 && !OC.off`), 'online: the last state is kept for an offline start (IndexedDB, no fallback to localStorage)');
    check(await ev(`!localStorage.getItem('tasks.cache')`), 'online: no copy of the state in localStorage');
    const sw = await ev(`(async () => {
      await navigator.serviceWorker.ready;
      for (let i = 0; i < 240; i++) {
        const ks = (await caches.keys()).filter(k => k.startsWith('tasks-shell'));
        if (ks.length && navigator.serviceWorker.controller) {
          const c = await caches.open(ks.pop());
          const has = {page: !!(await c.match('/', {ignoreSearch: true})), core: !!(await c.match('/static/js/core.js', {ignoreSearch: true})),
            stats: !!(await c.match('/static/js/stats.js', {ignoreSearch: true}))};
          if (has.page && has.core && has.stats) return {ok: true, ...has};
        }
        await new Promise(r => setTimeout(r, 250));
      }
      return {ok: false, keys: await caches.keys(), ctl: !!navigator.serviceWorker.controller};
    })()`);
    check(sw.ok, 'online: the worker controls the page and holds the page, core.js and the module stats.js ' + JSON.stringify(sw));
    check(await ev(`!LD_RAN.has('stats') && !LD_P.stats && typeof heatmap === 'undefined'`), 'online: the module stats was not loaded yet (it is loaded offline below)');

    // ---- the network gone
    await R.close();
    check(await refused(R.port), 'offline: the relay port refuses connections (the network is really gone)');
    check(await ev(`fetch('/api/state', {headers: {'X-Requested-With': 'kalmido'}}).then(() => 'answered', e => 'failed: ' + e.name)`) === 'failed: TypeError',
      'offline: a request of the page fails (no answer from anywhere, the worker leaves /api alone)');
    await nav(O + `#l/${L}`);
    check(await pu(`typeof S !== 'undefined' && S.booted && !!document.querySelector('#view .trow[data-id="${T}"]')`, 30000), 'offline: a new start comes from the worker\'s cache and shows the list with its task');
    check(await ev(`!!navigator.serviceWorker.controller && location.origin === ${JSON.stringify(O.replace(/\/$/, ''))}`), 'offline: the page is served by the worker');
    check(await pu(`OUT.online === false`), 'offline: the app knows it is offline');
    check(await pu(`OBX.on === true`), 'offline: the queue is in IndexedDB at an offline start too');
    await shot('p2579d-offline-start.png');
    const mod = await ev(`loadModule('stats').then(() => LD_RAN.has('stats') && typeof heatmap === 'function' ? 'ok' : 'stats.js did not run', e => 'failed: ' + e.message)`);
    check(mod === 'ok', 'offline: a module never loaded before (stats) loads from the worker\'s cache ' + mod);
    // a new task and a rename, as the app makes them (api() queues them while offline)
    const made = await ev(`Promise.all([api('POST', '/api/tasks', {title: ${JSON.stringify(NEW)}, list_id: ${L}}), api('PATCH', '/api/tasks/${T}', {title: ${JSON.stringify(REN)}})]).then(() => 'ok', e => 'failed: ' + e.message)`);
    check(made === 'ok', 'offline: the new task and the rename are taken ' + made);
    check(await pu(`OUT.q.length === 2`), 'offline: two changes wait in the queue');
    check(await pu(`OBX.st.all().then(r => r.length === 2 && r.some(x => x.method === 'POST' && x.body.title === ${JSON.stringify(NEW)}) && r.some(x => x.method === 'PATCH' && x.body.title === ${JSON.stringify(REN)}))`),
      'offline: both changes are written to IndexedDB "ops"');
    // api() itself does not redraw (the app's own add paths do): the local copy under its temporary id, drawn by a redraw of the view
    check(await pu(`[...S.tasks.values()].some(t => t.id < 0 && t.title === ${JSON.stringify(NEW)} && t.list_id === ${L}) && (renderView(), [...document.querySelectorAll('#view .trow')].some(r => r.textContent.includes(${JSON.stringify(NEW)})))`),
      'offline: the new task is there at once under a temporary id and shows in the list');
    let tasks = await state();
    check(!tasks.some(t => t.title === NEW) && tasks.find(t => t.id === T)?.title === 'Oil the hinges', 'offline: nothing has reached the server');

    // ---- the network back: the queue goes out by itself, exactly once
    await R.open();
    check(!(await refused(R.port)), 'online again: the relay port answers');
    check(await pu(`OUT.q.length === 0 && OUT.online === true`, 60000), 'online again: the queue is sent by itself and the app is online');
    check(await pu(`OBX.st.all().then(r => r.length === 0)`), 'online again: IndexedDB "ops" is empty after the send');
    check(await until(async () => (await state()).filter(t => t.title === NEW).length === 1), 'online again: the server has the new task');
    tasks = await state();
    check(tasks.filter(t => t.title === NEW).length === 1 && tasks.find(t => t.title === NEW)?.list_id === L, 'online again: the new task arrived exactly once, in its list');
    check(tasks.find(t => t.id === T)?.title === REN, 'online again: the rename arrived');
    check(await pu(`[...document.querySelectorAll('#view .trow')].filter(r => r.textContent.includes(${JSON.stringify(NEW)})).length === 1 && !S.tasks.has(-1) && [...S.tasks.keys()].every(k => k > 0)`),
      'online again: the page shows the task once, under its real id');
    // a new start reads the queue again: nothing goes twice
    await nav(O + `#l/${L}`);
    check(await pu(`typeof S !== 'undefined' && S.booted && OUT.online === true && OUT.q.length === 0 && !!document.querySelector('#view .trow[data-id="${T}"]')`, 30000), 'a new start online: the queue is empty');
    check(await pu(`fetch('/api/state', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.ok)`), 'a new start online: the page reaches the server');
    tasks = await state();
    check(tasks.filter(t => t.title === NEW).length === 1, 'a new start online: still exactly one new task (nothing sent twice)');

    // ---- clearLocal empties the queue in IndexedDB (sign-out / another person on this device)
    await R.close();
    check(await refused(R.port), 'clearLocal: the network gone again');
    const q = await ev(`api('PATCH', '/api/tasks/${T}', {title: ${JSON.stringify(GONE)}}).then(() => 'ok', e => 'failed: ' + e.message)`);
    check(q === 'ok' && await pu(`OBX.st.all().then(r => r.length === 1)`), 'clearLocal: a change waits in IndexedDB "ops" ' + q);
    const cl = await ev(`clearLocal().then(() => new Promise((ok, no) => {
      const r = indexedDB.open('kalmido-outbox');
      r.onsuccess = () => { const d = r.result; if (!d.objectStoreNames.contains('ops')) { d.close(); return ok({ops: 'no store'}); }
        const g = d.transaction('ops').objectStore('ops').count(); g.onsuccess = () => { d.close(); ok({ops: g.result, q: OUT.q.length}); }; g.onerror = () => no(g.error); };
      r.onerror = () => no(r.error);
    })).catch(e => ({err: String(e && e.message || e)}))`);
    check(cl.ops === 0 && cl.q === 0, 'clearLocal: IndexedDB "ops" is empty (read with an own open() of the database), the queue in memory too ' + JSON.stringify(cl));
    await R.open();
    check(await pu(`fetch('/api/state', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.ok)`), 'clearLocal: online again');
    tasks = await state();
    check(tasks.find(t => t.id === T)?.title === REN && !tasks.some(t => t.title === GONE), 'clearLocal: the cleared change never reaches the server');
  }, false);
  await R.close();

  console.log(`p2579_d_sw_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
