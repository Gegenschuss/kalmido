// 2.209.0 UI test, part E (#1627): the service worker's fallback reads only a completely filled cache.
// freelancer-matrix: public  (no route, no server: sw.js runs in a small stub of its scope, like p2149_b_ui.js)
// - a finished install writes its marker (also without the hash manifest); a broken-off install leaves none
// - offline (or a 5xx) a request is answered from this worker's cache first, then from an older cache (it was the active one
//   once) or a newer one whose install finished; the half-filled cache of a newer install that broke off never answers,
//   nor does the share cache
const fs = require('fs'), path = require('path'), vm = require('vm');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };

const SRC = fs.readFileSync(path.join(__dirname, '..', 'static', 'sw.js'), 'utf8');
const CACHE = (SRC.match(/const CACHE = '([^']+)'/) || [])[1];
const DONE = (SRC.match(/const SW_DONE = '([^']+)'/) || [])[1];
const N = +((CACHE || '').match(/-v(\d+)$/) || [])[1];
const OLDER = `tasks-shell-v${N - 1}`, NEWER = `tasks-shell-v${N + 1}`;
const ORIGIN = 'https://kalmido.example';

function sandbox({old = {}, offline = false, status = 200, fail = [], noManifest = true} = {}) {
  const store = new Map(Object.entries(old).map(([n, m]) => [n, new Map(Object.entries(m))]));
  const norm = k => String((k && k.url) || k).replace(ORIGIN, '');
  const resp = (url, body, type = 'text/plain', st = status) => ({ok: st < 400, status: st, redirected: false, type: 'basic', url, body,
    headers: new Headers({'content-type': type}), clone() { return this; }, json: async () => JSON.parse(body)});
  const fetchF = async u => {
    u = norm(u);
    if (offline) throw new TypeError('offline');
    if (u === '/sw-manifest.json') return noManifest ? resp(u, '<html>sign in</html>', 'text/html', 200) : resp(u, '{}', 'application/json', 200);
    if (fail.some(f => u.startsWith(f))) return resp(u, 'boom', 'text/plain', 500);
    return resp(u, 'body of ' + u);
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
  vm.runInContext(SRC, vm.createContext({self, caches, fetch: fetchF, URL, Headers, console, setTimeout, Promise, TypeError, Response: function (b) { this.body = b; }}), {filename: 'sw.js'});
  const life = async kind => { let p; handlers[kind]({waitUntil: x => { p = x; }}); return p; };
  const get = async url => { let p = null; handlers.fetch({request: {url: ORIGIN + url, method: 'GET'}, respondWith: x => { p = x; }}); return p; };
  return {store, life, get, has: (n, k) => !!(store.get(n) && store.get(n).has(k))};
}
const tag = t => ({ok: true, status: 200, tag: t});

(async () => {
  check(CACHE && DONE && N > 1, `sw.js read (${CACHE}, marker ${DONE})`);
  // the marker: written by a finished install, missing after a broken-off one
  let s = sandbox();
  await s.life('install');
  check(s.has(CACHE, DONE), 'a finished install (without the hash manifest) writes the marker');
  s = sandbox({fail: ['/static/js/core.js']});
  check(await s.life('install').then(() => false, () => true) && !s.has(CACHE, DONE), 'a broken-off install leaves no marker');

  // offline: a newer cache without the marker (half filled) never answers, the older one does
  const css = '/static/app.css';
  s = sandbox({offline: true, old: {[OLDER]: {[css]: tag('older')}, [NEWER]: {[css]: tag('half')}}});
  let r = await s.get(css);
  check(r && r.tag === 'older', `offline: the older cache answers, not the half-filled newer one (${r && r.tag})`);
  // a newer cache whose install finished may answer (the newest first)
  s = sandbox({offline: true, old: {[OLDER]: {[css]: tag('older')}, [NEWER]: {[css]: tag('newer'), [DONE]: tag('1')}}});
  r = await s.get(css);
  check(r && r.tag === 'newer', `offline: a finished newer cache answers (${r && r.tag})`);
  // this worker's cache first, also when it was created after the others
  s = sandbox({offline: true, old: {[NEWER]: {[css]: tag('newer'), [DONE]: tag('1')}, [OLDER]: {[css]: tag('older')}, [CACHE]: {[css]: tag('own')}}});
  r = await s.get(css);
  check(r && r.tag === 'own', `offline: this worker's cache comes first (${r && r.tag})`);
  // a server error (5xx) falls back the same way
  s = sandbox({status: 503, old: {[NEWER]: {[css]: tag('half')}, [OLDER]: {[css]: tag('older')}}});
  r = await s.get(css);
  check(r && r.tag === 'older', `5xx: the older cache answers, not the half-filled newer one (${r && r.tag})`);
  // only the half-filled cache or the share cache hold it: no answer from there
  s = sandbox({offline: true, old: {[NEWER]: {[css]: tag('half')}, 'tasks-share': {[css]: tag('share')}}});
  r = await s.get(css).then(x => x, () => 'err');
  check(r === 'err', `offline: neither the half-filled cache nor the share cache answer (${r && r.tag || r})`);
  // the quick capture page falls back to the app page, by the same rule
  s = sandbox({offline: true, old: {[NEWER]: {'/': tag('half')}, [OLDER]: {'/': tag('older')}}});
  r = await s.get('/capture?title=x');
  check(r && r.tag === 'older', `offline: /capture gets the app page of a complete cache (${r && r.tag})`);

  console.log(`p2209_e_sw_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
