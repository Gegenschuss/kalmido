// 2.149.0 UI test, part B (#2505 #2506): the start with hashed files and the service worker's hash manifest.
// freelancer-matrix: public
// - no server (sw.js in a sandbox, like p2138_a_ui.js): an update with the manifest copies every unchanged file from the old
//   cache and loads only the changed one (+ the two dynamic pages); old caches go on activate; without the manifest (an older
//   server, a sign-in page) everything is loaded as before; a failing start file drops the install, a failing module does
//   not; ?v=<hash> is answered from the cache without the network; a hashed answer the server did not confirm (no
//   immutable) is never kept under that address; offline any copy of the file still answers
// - own container (start.sh), Firefox: a fresh start signed in: every start script carries ?v=<hash>, the app starts, a list
//   opens; the service worker keeps the files under their hashed address (the manifest's hash); a second start is served by
//   the worker and works; an update of the worker next to an old cache (one file missing there) fills the new cache
//   completely, removes the old one, and the app starts again
// P2149B_NOSTART=1 / KMT_NOSTART=1 = the container is running.
const fs = require('fs'), path = require('path'), vm = require('vm');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2149_b_ui', check, shots: 'P2149B_SHOTS', lazy: true});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };

// ================= the service worker in a sandbox (no server)
const SRC = fs.readFileSync(path.join(__dirname, '..', 'static', 'sw.js'), 'utf8');
const CACHE = (SRC.match(/const CACHE = '([^']+)'/) || [])[1];
const LISTS = [...SRC.matchAll(/const (SHELL|LAZY|LAZY_CSS) = \[(.*?)\];/gs)].reduce((o, m) => ({...o, [m[1]]: [...m[2].matchAll(/'([^']+)'/g)].map(x => x[1])}), {});
const ORIGIN = 'https://kalmido.example';
const hex = i => (i + 1).toString(16).padStart(12, '0');
const FILES = {};
[...LISTS.SHELL, ...LISTS.LAZY, ...LISTS.LAZY_CSS].filter(u => u.startsWith('/static/')).forEach((u, i) => { FILES[u] = hex(i); });

function sandbox({files = FILES, old = {}, noManifest = false, fail = [], offline = false} = {}) {
  const store = new Map(Object.entries(old).map(([n, m]) => [n, new Map(Object.entries(m))]));
  const fetched = [];
  const norm = k => String((k && k.url) || k).replace(ORIGIN, '');
  const resp = (url, body, cc, type = 'text/plain', status = 200) => ({ok: status < 400, status, redirected: false, type: 'basic', url, body,
    headers: new Headers({'content-type': type, ...(cc ? {'cache-control': cc} : {})}), clone() { return this; }, json: async () => JSON.parse(body)});
  const fetchF = async u => {
    u = norm(u); fetched.push(u);
    if (offline) throw new TypeError('offline');
    if (u === '/sw-manifest.json') return noManifest ? resp(u, '<html>sign in</html>', '', 'text/html') : resp(u, JSON.stringify({v: 1, files}), 'no-cache', 'application/json');
    if (fail.some(f => u.startsWith(f))) return resp(u, 'boom', '', 'text/plain', 500);
    const [p, q] = u.split('?v=');
    return resp(u, 'body of ' + u, q && files[p] === q ? 'public, max-age=31536000, immutable' : 'no-cache');
  };
  const cache = name => {
    if (!store.has(name)) store.set(name, new Map());
    const m = store.get(name);
    return {put: async (k, r) => { m.set(norm(k), r); }, delete: async k => m.delete(norm(k)), keys: async () => [...m.keys()],
      add: async u => { const r = await fetchF(u); if (!r.ok) throw new TypeError('add ' + u); m.set(norm(u), r); },
      addAll: async us => { const rs = await Promise.all(us.map(fetchF)); if (rs.some(r => !r.ok)) throw new TypeError('addAll'); us.forEach((u, i) => m.set(norm(u), rs[i])); },
      match: async (k, o) => { k = norm(k); if (m.has(k)) return m.get(k); if (o && o.ignoreSearch) for (const [kk, v] of m) if (kk.split('?')[0] === k.split('?')[0]) return v; return undefined; }};
  };
  const caches = {open: async n => cache(n), keys: async () => [...store.keys()], delete: async n => store.delete(n),
    match: async (k, o) => { for (const n of store.keys()) { const r = await cache(n).match(k, o); if (r) return r; } return undefined; }};
  const handlers = {};
  const self = {addEventListener: (k, f) => { handlers[k] = f; }, skipWaiting: async () => {}, clients: {claim: async () => {}, matchAll: async () => []}, location: {origin: ORIGIN}, navigator: {}};
  vm.runInContext(SRC, vm.createContext({self, caches, fetch: fetchF, URL, Headers, console, setTimeout, Promise, TypeError, Response: function () {}}), {filename: 'sw.js'});
  const life = async kind => { let p; handlers[kind]({waitUntil: x => { p = x; }}); return p; };
  const get = async url => { let p = null; handlers.fetch({request: {url: ORIGIN + url, method: 'GET'}, respondWith: x => { p = x; }}); return p; };
  // 2.209.0 E (#1627): a finished install also writes its marker (SW_DONE), not counted as a file here
  return {store, fetched, life, get, keys: n => [...(store.get(n) || new Map()).keys()].filter(k => k !== '/sw-install-done')};
}

async function swCheck() {
  check(CACHE && LISTS.SHELL.length > 100 && LISTS.LAZY.length > 30 && LISTS.LAZY_CSS.length > 5, `sandbox: sw.js read (${CACHE}, ${LISTS.SHELL.length}/${LISTS.LAZY.length}/${LISTS.LAZY_CSS.length})`);
  const all = Object.keys(FILES).length + 2;  // + '/' and '/manifest.json'
  // an update: the old cache holds every file of the old version under its hash; core.js changed since
  const oldFiles = {...FILES, '/static/js/core.js': 'aaaaaaaaaaaa'};
  const oldCache = Object.fromEntries(Object.entries(oldFiles).map(([u, h]) => [`${u}?v=${h}`, {ok: true, old: true}]).concat([['/', {ok: true, old: true}]]));
  let s = sandbox({old: {'tasks-shell-v1': oldCache}});
  await s.life('install');
  const net = s.fetched.filter(u => u !== '/sw-manifest.json').sort();
  check(JSON.stringify(net) === JSON.stringify(['/', '/manifest.json', `/static/js/core.js?v=${FILES['/static/js/core.js']}`].sort()),
    '#2506: an update loads only the changed file and the two dynamic pages ' + JSON.stringify(net.slice(0, 6)));
  const nk = s.keys(CACHE);
  check(nk.length === all && Object.entries(FILES).every(([u, h]) => nk.includes(`${u}?v=${h}`)), `#2506: the new cache holds every file under its hash (${nk.length}/${all})`);
  const copied = s.store.get(CACHE).get(`/static/js/main.js?v=${FILES['/static/js/main.js']}`);
  check(copied && copied.old === true, '#2506: an unchanged file is the old copy (not loaded again)');
  await s.life('activate');
  check(JSON.stringify([...s.store.keys()]) === JSON.stringify([CACHE]), '#2506: the old cache is gone after activate ' + JSON.stringify([...s.store.keys()]));
  // a first install (no old cache): everything from the network, each once
  s = sandbox();
  await s.life('install');
  check(s.fetched.length === all + 1 && new Set(s.fetched).size === s.fetched.length, `#2506: a first install loads every file once (${s.fetched.length} of ${all + 1})`);
  // no manifest (an older server, a sign-in page in between): as before
  s = sandbox({noManifest: true});
  await s.life('install');
  check(s.keys(CACHE).includes('/static/js/core.js') && s.keys(CACHE).length === all, `#2506: without the manifest everything is loaded as before (${s.keys(CACHE).length})`);
  // a start file fails: the install is dropped (the old worker stays); a module on demand fails: the install goes on
  s = sandbox({fail: ['/static/js/core.js']});
  check(await s.life('install').then(() => false, () => true), '#2506: a failing start file drops the install');
  s = sandbox({fail: ['/static/js/office.js']});
  check(await s.life('install').then(() => true, () => false) && s.keys(CACHE).length === all - 1, '#2506: a failing module on demand does not');
  // the fetch handler
  s = sandbox({old: {[CACHE]: {[`/static/js/core.js?v=${FILES['/static/js/core.js']}`]: {ok: true, tag: 'kept'}}}});
  let r = await s.get(`/static/js/core.js?v=${FILES['/static/js/core.js']}`);
  check(r && r.tag === 'kept' && !s.fetched.length, '#2506: ?v=<hash> comes from the cache without the network');
  r = await s.get('/static/js/core.js?v=bbbbbbbbbbbb');
  await sleep(10);
  check(r && r.ok && s.fetched.includes('/static/js/core.js?v=bbbbbbbbbbbb') && !s.keys(CACHE).includes('/static/js/core.js?v=bbbbbbbbbbbb'),
    '#2506: an unconfirmed hash (no immutable answer) is fetched and never kept under that address');
  r = await s.get('/static/js/core.js?v=2.149.0');
  await sleep(10);
  check(r && r.ok && s.fetched.includes('/static/js/core.js?v=2.149.0'), '#2506: a module asked for with the code version stays network-first');
  s = sandbox({offline: true, old: {[CACHE]: {[`/static/js/core.js?v=${FILES['/static/js/core.js']}`]: {ok: true, tag: 'kept'}, [`/static/app.css?v=${FILES['/static/app.css']}`]: {ok: true, tag: 'css'}}}});
  r = await s.get('/static/js/core.js?v=cccccccccccc');
  check(r && r.tag === 'kept', '#2506: offline, another hash of the file still gets the kept copy');
  r = await s.get('/static/app.css');
  check(r && r.tag === 'css', '#2505: offline, a stylesheet without ?v= gets the copy kept under its hash');
}

(async () => {
  await swCheck();
  if (!process.env.P2149B_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env}});
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const L = (await call(CA, 'POST', '/api/lists', {name: 'Garden'})).id;
  const T = (await call(CA, 'POST', '/api/tasks', {title: 'Cut the hedge', list_id: L})).id;
  check(L > 0 && T > 0, 'a list with a task');
  const man = await (await fetch(B + 'sw-manifest.json')).json();
  const until = (ev, expr, n) => require('./boot').until(() => ev(expr).catch(() => false), {timeout: n ? n * 250 : 15000, step: 250});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window

  await firefox(async ({ev, nav, shot}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'login');
    // a fresh start
    await nav(B + `#l/${L}`);
    check(await until(ev, `typeof S !== 'undefined' && S.booted`), 'Firefox: the app starts with the hashed files');
    const tags = await ev(`JSON.stringify([...document.querySelectorAll('script[src^="/static/"], link[rel="stylesheet"][href^="/static/"]')].map(x => x.getAttribute('src') || x.getAttribute('href')))`);
    const list = JSON.parse(tags);
    check(list.length > 100 && list.every(u => /\?v=[0-9a-f]{12}$/.test(u)), `#2505: every start script / stylesheet with ?v=<hash> (${list.length}) ${list.filter(u => !/\?v=/.test(u)).slice(0, 3)}`);
    check(list.filter(u => u.startsWith('/static/js/') || u === '/static/i18n.js' || u === '/static/app.css').every(u => man.files[u.split('?')[0]] === u.split('?v=')[1]),
      '#2505 #2506: the page and the manifest name the same hashes');
    check(await until(ev, `!!document.querySelector('#view .trow[data-id="${T}"]')`), 'Firefox: the list opens');
    check(await ev(`typeof main === 'function' || typeof boot === 'function' || (typeof S === 'object' && S.booted)`), 'Firefox: the last start file ran');
    // the service worker keeps the files under their hashed address
    const core = '/static/js/core.js?v=' + man.files['/static/js/core.js'];
    const sw1 = await ev(`(async () => { const reg = await navigator.serviceWorker.ready; for (let i = 0; i < 80; i++) { const ks = (await caches.keys()).filter(k => k.startsWith('tasks-shell'));
        if (ks.length) { const c = await caches.open(ks.pop()); if (await c.match('${core}') && await c.match('/static/js/office.js', {ignoreSearch: true})) return {ok: true, sw: !!reg.active, n: (await c.keys()).length}; }
        await new Promise(r => setTimeout(r, 250)); } return {ok: false, keys: await caches.keys()}; })()`);
    check(sw1.ok && sw1.sw && sw1.n >= Object.keys(man.files).length, '#2506: the worker keeps the files under <url>?v=<hash> ' + JSON.stringify(sw1));
    // a second start, served by the worker
    await nav(B + `#l/${L}`);
    check(await until(ev, `typeof S !== 'undefined' && S.booted && !!navigator.serviceWorker.controller`), 'Firefox: a second start with the worker in control');
    check(await until(ev, `!!document.querySelector('#view .trow[data-id="${T}"]')`), 'Firefox: the list opens again');
    await shot('p2149b-start.png');
    // an update next to the cache of an "older version": everything but core.js copied there, the current cache removed;
    // a new script address makes the browser install the worker again
    const up = await ev(`(async () => {
      const name = (await caches.keys()).filter(k => k.startsWith('tasks-shell')).pop(), cur = await caches.open(name), old = await caches.open('tasks-shell-v1');
      for (const k of await cur.keys()) if (!k.url.includes('/static/js/core.js')) await old.put(k, await cur.match(k));
      await caches.delete(name);
      const reg = await navigator.serviceWorker.register('/sw.js?u=' + Date.now());
      for (let i = 0; i < 120; i++) { const ks = await caches.keys(); if (!ks.includes('tasks-shell-v1') && ks.includes(name)) break; await new Promise(r => setTimeout(r, 250)); }
      const ks = await caches.keys(), c = await caches.open(name);
      return {keys: ks, core: !!(await c.match('${core}')), n: (await c.keys()).length, active: !!reg.active}; })()`);
    check(up.core && up.n >= Object.keys(man.files).length && !up.keys.includes('tasks-shell-v1') && up.active,
      '#2506: the update fills the new cache (the missing file loaded) and removes the old one ' + JSON.stringify(up));
    await nav(B + `#l/${L}`);
    check(await until(ev, `typeof S !== 'undefined' && S.booted && !!document.querySelector('#view .trow[data-id="${T}"]')`), 'Firefox: the app starts after the update');
  }, false);

  console.log(`p2149_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
