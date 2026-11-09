// 2.766.0 UI test, part A (#5220): code integrity stage 3 - Settings > Help > Check code and the warning of the service worker.
// kalmido-suite: fresh
// freelancer-matrix: public (bob has no organisation and is no admin: the check is his as well)
// - sandbox (static/sw.js in a vm, no server, like p2149_b_ui.js): an install keeps version + hashes (/sw-code-state); a page's
//   code-check with the same version and the same hashes says nothing; the same version with another hash leaves the mark and
//   tells the asking page {type: 'code-changed', version, files}; a new version says nothing and leaves the state to the update;
//   code-ack removes the mark; an install next to an older cache with the same version and another hash tells every window
// - own container, Firefox, signed in as bob (no organisation, no admin): the worker holds the shell; Settings > Help >
//   Check code shows the version and ONE hash, and that hash is the SHA-256 of the bytes of GET /api/code-manifest (the
//   recipe of kalmido/core/codemanifest.py cm_json, so the same value as web-manifest-X.Y.Z.json of the release) while every
//   file in the browser matches; "Copy hash" puts it into the clipboard; the link leads to the GitHub release of that version
//   (a link only, nothing fetched); a cached file with other bytes under its right ?v= is named and changes the hash (the
//   browser hashes what it holds, it does not take the server's word); the worker's mark (same version, another hash)
//   shows the hint, whose button opens the check and confirms the mark
// The waits are on states (the page, the cache, the clipboard stub), never on a fixed time. P2766A_SHOTS=<dir> = screenshots.
const fs = require('fs'), path = require('path'), vm = require('vm'), crypto = require('crypto');
const {B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2766_a_codecheck_ui', check, shots: 'P2766A_SHOTS', lazy: true, allWs: true});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
const sha = b => crypto.createHash('sha256').update(b).digest('hex');

// ================= the service worker in a sandbox (no server)
const SRC = fs.readFileSync(path.join(__dirname, '..', 'static', 'sw.js'), 'utf8');
const CACHE = (SRC.match(/const CACHE = '([^']+)'/) || [])[1];
const LISTS = [...SRC.matchAll(/const (SHELL|LAZY|LAZY_CSS) = \[(.*?)\];/gs)].reduce((o, m) => ({...o, [m[1]]: [...m[2].matchAll(/'([^']+)'/g)].map(x => x[1])}), {});
const ORIGIN = 'https://kalmido.example';
const FILES = {};
[...LISTS.SHELL, ...LISTS.LAZY, ...LISTS.LAZY_CSS].filter(u => u.startsWith('/static/')).forEach((u, i) => { FILES[u] = (i + 1).toString(16).padStart(12, '0'); });
const CORE = '/static/js/core.js';

function sandbox({man, old = {}}) {
  const store = new Map(Object.entries(old).map(([n, m]) => [n, new Map(Object.entries(m))]));
  const norm = k => String((k && k.url) || k).replace(ORIGIN, '');
  const resp = (u, body, type, cc) => new Response(body, {status: 200, headers: {'content-type': type, ...(cc ? {'cache-control': cc} : {})}});
  const net = {man};
  const fetchF = async u => {
    u = norm(u);
    if (u === '/sw-manifest.json') return resp(u, JSON.stringify(net.man), 'application/json', 'no-cache');
    const [p, q] = u.split('?v='), files = net.man.files || {};
    return resp(u, 'body of ' + u, 'text/plain', q && files[p] === q ? 'public, max-age=31536000, immutable' : 'no-cache');
  };
  const cache = name => {
    if (!store.has(name)) store.set(name, new Map());
    const m = store.get(name);
    return {put: async (k, r) => { m.set(norm(k), r); }, delete: async k => m.delete(norm(k)), keys: async () => [...m.keys()],
      add: async u => { m.set(norm(u), await fetchF(u)); }, addAll: async us => { for (const u of us) m.set(norm(u), await fetchF(u)); },
      match: async (k, o) => { k = norm(k); const r = m.get(k) || (o && o.ignoreSearch ? [...m].find(([kk]) => kk.split('?')[0] === k.split('?')[0])?.[1] : undefined); return r && r.clone ? r.clone() : r; }};
  };
  const caches = {open: async n => cache(n), keys: async () => [...store.keys()], delete: async n => store.delete(n),
    match: async (k, o) => { for (const n of store.keys()) { const r = await cache(n).match(k, o); if (r) return r; } return undefined; }};
  const handlers = {}, sent = [], wins = [{id: 'w1', postMessage: d => sent.push({to: 'w1', d})}, {id: 'w2', postMessage: d => sent.push({to: 'w2', d})}];
  const self = {addEventListener: (k, f) => { handlers[k] = f; }, skipWaiting: async () => {}, location: {origin: ORIGIN}, navigator: {},
    clients: {claim: async () => {}, matchAll: async o => (o && o.includeUncontrolled ? wins : [])}};
  vm.runInContext(SRC, vm.createContext({self, caches, fetch: fetchF, URL, Headers, Response, console, setTimeout, Promise, TypeError, JSON, Date}), {filename: 'sw.js'});
  const wait = async (kind, ev) => { let p; handlers[kind]({...ev, waitUntil: x => { p = x; }}); return p; };
  const read = async (n, k) => { const r = (store.get(n) || new Map()).get(k); return r ? JSON.parse(await r.clone().text()) : null; };
  return {store, net, sent, wins, read,
    install: () => wait('install', {}),
    msg: (type, src = wins[0]) => wait('message', {data: {type}, source: src})};
}

async function swCheck() {
  check(CACHE && LISTS.LAZY.includes('/static/js/codecheck.js'), `sandbox: sw.js read (${CACHE}), codecheck.js is precached (LAZY)`);
  const man = {v: 1, version: '9.9.9', files: FILES, i18n: []};
  let s = sandbox({man});
  await s.install();
  const st = await s.read(CACHE, '/sw-code-state');
  check(st && st.version === '9.9.9' && st.files[CORE] === FILES[CORE], 'install: the worker keeps the version and the hashes (/sw-code-state)');
  check(!s.sent.length && !(await s.read(CACHE, '/sw-code-changed')), 'install: a first install has nothing to report');
  // the same version, the same hashes: quiet
  await s.msg('code-check');
  check(!s.sent.length, 'code-check: same version, same hashes - no message');
  // the same version, another hash of core.js: the mark + the message to the asking page only
  s.net.man = {...man, files: {...FILES, [CORE]: 'abcdefabcdef'}};
  await s.msg('code-check');
  const m1 = s.sent.find(x => x.d.type === 'code-changed');
  check(m1 && m1.to === 'w1' && m1.d.version === '9.9.9' && JSON.stringify(m1.d.files) === JSON.stringify([CORE]) && s.sent.length === 1,
    'code-check: same version, another hash - {type: code-changed, version, files: [core.js]} to the asking page ' + JSON.stringify(s.sent));
  const mark = await s.read(CACHE, '/sw-code-changed');
  check(mark && mark.version === '9.9.9' && mark.n === 1, 'code-check: the mark stays in the cache (/sw-code-changed)');
  check((await s.read(CACHE, '/sw-code-state')).files[CORE] === 'abcdefabcdef', 'code-check: the new hashes are kept (the next change is a new one)');
  // a page opened later learns the unconfirmed mark
  s.sent.length = 0;
  await s.msg('code-check', s.wins[1]);
  check(s.sent.length === 1 && s.sent[0].to === 'w2' && s.sent[0].d.type === 'code-changed', 'code-check: a later page gets the unconfirmed mark too');
  // confirmed: gone
  await s.msg('code-ack');
  s.sent.length = 0;
  await s.msg('code-check');
  check(!(await s.read(CACHE, '/sw-code-changed')) && !s.sent.length, 'code-ack: the mark is gone, nothing is reported again');
  // a new version (an update on its way): quiet, the state is left to the install of the new worker
  s.net.man = {...man, version: '9.9.10', files: {...FILES, [CORE]: '111111111111'}};
  await s.msg('code-check');
  check(!s.sent.length && (await s.read(CACHE, '/sw-code-state')).version === '9.9.9', 'code-check: another version - no message, the state stays');
  // an older server without the version: nothing to compare
  s.net.man = {v: 1, files: {...FILES, [CORE]: '222222222222'}};
  await s.msg('code-check');
  check(!s.sent.length, 'code-check: a server without the version in sw-manifest.json - no message');
  // an install (a changed sw.js) next to an older cache of the same version with another hash: every window learns it
  const oldState = new Response(JSON.stringify({version: '9.9.9', files: {...FILES, [CORE]: 'ffffffffffff'}}), {headers: {'content-type': 'application/json'}});
  s = sandbox({man, old: {'tasks-shell-v1': {'/sw-code-state': oldState}}});
  await s.install();
  check(s.sent.length === 2 && s.sent.every(x => x.d.type === 'code-changed' && x.d.files[0] === CORE), 'install: same version, another hash than the old cache - every window gets code-changed ' + JSON.stringify(s.sent.map(x => x.to)));
  // a new version in the old cache: quiet
  const oldV = new Response(JSON.stringify({version: '9.9.8', files: {...FILES, [CORE]: 'ffffffffffff'}}), {headers: {'content-type': 'application/json'}});
  s = sandbox({man, old: {'tasks-shell-v1': {'/sw-code-state': oldV}}});
  await s.install();
  check(!s.sent.length, 'install: a new version with new hashes - no message');
}

(async () => {
  await swCheck();
  check((await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'ada', display_name: 'Ada', password: 'password123', lang: 'en'})})).ok, 'setup');
  const CA = await login('ada');
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  // bob: a person without an organisation and without admin rights (tests/freelancer_fixture.py)
  const bob = await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com', orgs: []});
  check(bob.http === 200 && bob.id > 0, 'bob: a person without an organisation ' + bob.http);
  const CB = await login('bob');
  await call(CB, 'PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const me = await call(CB, 'GET', '/api/state');
  check(!(me.me?.workspaces || []).length && !me.me?.is_admin, 'bob: no organisation, no admin');
  const raw = Buffer.from(await (await fetch(B + 'api/code-manifest', {cache: 'no-store'})).arrayBuffer());
  const MAN = JSON.parse(raw.toString('utf8')), SRV = sha(raw);
  const swm = await (await fetch(B + 'sw-manifest.json')).json();
  check(MAN.version && swm.version === MAN.version, `/sw-manifest.json names the version (${swm.version})`);

  await firefox(async ({ev, nav, until: pu0, shot}) => {
    const pu = (expr, ms = 20000) => pu0(expr, {timeout: ms, step: 200});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'bob', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: bob signs in');
    await nav(B + '#today');
    check(await pu(`typeof S !== 'undefined' && S.booted`), 'Firefox: the app starts');
    // the worker in control with a finished cache that holds the start files and the state it keeps
    check(await pu(`(async () => { if (!navigator.serviceWorker.controller) return false; const ks = (await caches.keys()).filter(k => /^tasks-shell-v\\d+$/.test(k)); if (!ks.length) return false;
      const c = await caches.open(ks.sort((a, b) => +b.slice(13) - +a.slice(13))[0]); return !!(await c.match('/sw-install-done')) && !!(await c.match('/sw-code-state')) && !!(await c.match('/static/js/core.js', {ignoreSearch: true})); })()`, 40000),
      'Firefox: the worker controls the page, its cache is finished and keeps the code state');

    // ---- Settings > Help > Check code (bob: no organisation, no admin)
    await ev(`(async () => { await loadModule('settings'); settingsModal('help'); return 1; })()`);
    check(await pu(`!!document.querySelector('.smodal #sp-help:not(.hidden) #s-cc-h') && !!document.querySelector('[data-ccv="run"]')`), 'Settings > Help: the section "Check code" with its button, for a person without an organisation');
    check(await ev(`!LD_RAN.has('codecheck')`), 'codecheck.js is not loaded before the button (a module on demand)');
    await ev(`document.querySelector('[data-ccv="run"]').click(), 1`);
    check(await pu(`!!document.querySelector('#s-cc-res #s-cc-hash')`), 'Check code: the result is drawn');
    const res = JSON.parse(await ev(`JSON.stringify({hash: document.querySelector('#s-cc-hash').textContent, sum: document.querySelector('#s-cc-sum').textContent, ok: document.querySelector('#s-cc-sum').dataset.ok,
      ver: document.querySelector('#s-cc-res .row span').textContent, rel: document.querySelector('#s-cc-rel').getAttribute('href'), tgt: document.querySelector('#s-cc-rel').target, ran: LD_RAN.has('codecheck')})`));
    const x = JSON.parse(await ev(`ckvRun().then(x => JSON.stringify(x))`));
    check(res.ran, 'the button loaded codecheck.js');
    check(res.ver.includes('v' + MAN.version), `the version of the code is shown (${res.ver})`);
    check(x.checked > 50 && !x.bad.length, `the browser hashed what its cache holds: ${x.checked} files, none differs (${x.bad.slice(0, 3)})`);
    check(x.unchecked > 0 && /not in this browser/.test(res.sum), `files not in the cache are named "not checked" (${x.unchecked})`);
    check(res.ok === '1' && res.hash === SRV && x.hash === SRV, `ONE recipe: the hash shown is the SHA-256 of /api/code-manifest (cm_json) ${res.hash.slice(0, 16)} vs ${SRV.slice(0, 16)}`);
    check(res.rel === `https://github.com/Gegenschuss/kalmido/releases/tag/v${MAN.version}` && res.tgt === '_blank', 'the link leads to the GitHub release of that version ' + res.rel);
    await shot('codecheck');
    // Copy hash (the clipboard stubbed)
    await ev(`(() => { window.__copied = []; Object.defineProperty(navigator, 'clipboard', {value: {writeText: async t => { window.__copied.push(t); }}, configurable: true}); return 1; })()`);
    await ev(`document.querySelector('[data-ccv="copy"]').click(), 1`);
    check(await pu(`window.__copied.includes(${JSON.stringify(SRV)})`), '"Copy hash" puts the hash into the clipboard');

    // ---- the browser hashes what it holds: core.js with other bytes under its right ?v=
    const bad = JSON.parse(await ev(`(async () => {
      const ks = (await caches.keys()).filter(k => /^tasks-shell-v\\d+$/.test(k)).sort((a, b) => +b.slice(13) - +a.slice(13)), c = await caches.open(ks[0]);
      const req = (await c.keys()).find(r => new URL(r.url).pathname === '/static/js/core.js' && new URL(r.url).searchParams.get('v'));
      await c.put(req, new Response('/* not the published core.js */', {headers: {'content-type': 'text/javascript'}}));
      document.querySelector('[data-ccv="run"]').click();
      for (let i = 0; i < 200 && document.querySelector('#s-cc-sum')?.dataset.ok !== '0'; i++) await new Promise(r => setTimeout(r, 100));
      return JSON.stringify({x: await ckvRun(), sum: document.querySelector('#s-cc-sum').textContent, hash: document.querySelector('#s-cc-hash').textContent});
    })()`));
    check(bad.x.bad.includes('/static/js/core.js') && bad.sum.includes('/static/js/core.js') && /differs/.test(bad.sum), 'a changed cached file is named ' + bad.sum.slice(0, 120));
    check(bad.hash !== SRV && bad.x.hash !== SRV && bad.x.server === SRV, 'and the hash shown is no longer the server\'s (the browser does not take its word)');
    await ev(`document.querySelector('.modal .mclose, .modal [data-m="close"]')?.click(), 1`);

    // ---- the worker's mark: the same version, another hash -> the hint, its button opens the check and confirms
    await ev(`(async () => { const ks = (await caches.keys()).filter(k => /^tasks-shell-v\\d+$/.test(k)).sort((a, b) => +b.slice(13) - +a.slice(13)), c = await caches.open(ks[0]);
      const st = await (await c.match('/sw-code-state')).json(); st.files['/static/js/core.js'] = 'abcdefabcdef';
      await c.put('/sw-code-state', new Response(JSON.stringify(st), {headers: {'content-type': 'application/json'}}));
      document.querySelectorAll('.modal').forEach(m => m.remove());
      (await navigator.serviceWorker.ready).active.postMessage({type: 'code-check'}); return 1; })()`);
    check(await pu(`!!document.querySelector('#codechg') && /changed without a new version/.test(document.querySelector('#codechg').textContent)`), 'the hint "The app\'s code changed without a new version" shows');
    check(await ev(`(async () => { const ks = (await caches.keys()).filter(k => /^tasks-shell-v\\d+$/.test(k)).sort((a, b) => +b.slice(13) - +a.slice(13)); return !!(await (await caches.open(ks[0])).match('/sw-code-changed')); })()`), 'the worker kept the mark');
    await shot('codechg');
    await ev(`document.querySelector('#codechg [data-ccgo]').click(), 1`);
    check(await pu(`!document.querySelector('#codechg') && !!document.querySelector('.smodal #sp-help:not(.hidden) #s-cc-res #s-cc-hash')`), 'its button opens Settings > Help > Check code and runs the check');
    check(await pu(`(async () => { const ks = (await caches.keys()).filter(k => /^tasks-shell-v\\d+$/.test(k)).sort((a, b) => +b.slice(13) - +a.slice(13)); return !(await (await caches.open(ks[0])).match('/sw-code-changed')); })()`), 'opening the check confirmed the mark (code-ack)');
  }, false);

  console.log(`p2766_a_codecheck_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
