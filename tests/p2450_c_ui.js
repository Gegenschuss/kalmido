// 2.45.0 part C (#1529) reload safety. No server needed:
// - sw.js runs in a vm with fake caches / fetch: a 5xx is never cached and falls back to a cached copy, an incomplete new
//   cache keeps the old ones, a complete one removes them
// - reloadguard.js in jsdom: no styling -> reload again (3 times at most, sessionStorage counter), then a notice with a button
//   that reads without app.css; styled page -> counter reset; rl_waitServer waits until / and app.css answer 200
// By hand: update the live container and watch an open desktop app (it must come back styled, no bare logo).
const fs = require('fs'), path = require('path'), vm = require('vm');
const {JSDOM} = require('jsdom');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const sleep = ms => new Promise(r => setTimeout(r, ms));
const SRC = process.env.KMT_SRC || path.join(__dirname, '..');
const read = f => fs.readFileSync(path.join(SRC, 'static', f), 'utf8');
const CUR = read('sw.js').match(/const CACHE = '([^']+)'/)[1];  // the cache name of this version (not a fixed one)

class FakeCache {
  constructor() { this.m = new Map(); }
  async match(req) { const k = typeof req === 'string' ? req : req.url; return this.m.get(k.replace(/^https?:\/\/[^/]+/, '').split('?')[0]) || this.m.get(k.replace(/^https?:\/\/[^/]+/, '')); }
  async put(req, res) { this.m.set((typeof req === 'string' ? req : req.url).replace(/^https?:\/\/[^/]+/, '').split('?')[0], res); }
  async addAll() { if (this.fail) throw new Error('bad status'); for (const u of this.urls || []) this.m.set(u, {status: 200, tag: 'new'}); }
}
function swEnv() {
  const store = new Map(), listeners = {};
  const caches = {
    async open(n) { if (!store.has(n)) store.set(n, new FakeCache()); return store.get(n); },
    async keys() { return [...store.keys()]; },
    async delete(n) { return store.delete(n); },
    async match(req, o) { for (const c of store.values()) { const r = await c.match(req, o); if (r) return r; } },
  };
  const env = {fetchImpl: null, store, listeners, caches};
  const self = {addEventListener: (t, f) => { listeners[t] = f; }, location: {origin: 'http://x'}, clients: {claim: async () => {}}, skipWaiting: async () => {}};
  const ctx = vm.createContext({self, caches, URL, Response: class { constructor(b, o) { this.status = (o || {}).status || 200; } }, console,
    fetch: (...a) => env.fetchImpl(...a), TypeError, Promise, Headers, atob, Uint8Array});
  vm.runInContext(read('sw.js'), ctx);
  env.ctx = ctx;
  return env;
}
const fetchEvent = (env, url) => new Promise((res, rej) => {
  let p; env.listeners.fetch({request: {method: 'GET', url: 'http://x' + url}, respondWith: x => { p = x; }});
  if (!p) return res('passthrough');
  Promise.resolve(p).then(res, e => res('error:' + e.message));
});
const lifecycle = (env, t) => new Promise(res => { let p; env.listeners[t]({waitUntil: x => { p = x; }}); Promise.resolve(p).then(() => res('ok'), () => res('failed')); });

(async () => {
  // ---- service worker
  let env = swEnv();
  const fresh = (st, ok2 = st < 400) => ({status: st, ok: ok2, redirected: false, type: 'basic', clone() { return this; }, tag: 'net' + st});
  env.fetchImpl = async () => fresh(200);
  let r = await fetchEvent(env, '/static/app.css');
  check(r.tag === 'net200', 'sw: online -> the network answer');
  await sleep(20);
  check((await (await env.caches.open(CUR)).match('/static/app.css'))?.tag === 'net200', 'sw: a 200 is cached');
  env.fetchImpl = async () => fresh(502, false);
  r = await fetchEvent(env, '/static/app.css');
  check(r.tag === 'net200', 'sw: 502 -> falls back to the cached copy');
  r = await fetchEvent(env, '/static/other.js');
  check(r.tag === 'net502', 'sw: 502 and nothing cached -> the answer as is');
  await sleep(20);
  check(!(await (await env.caches.open(CUR)).match('/static/other.js')), 'sw: a 502 is never cached');
  env.fetchImpl = async () => { throw new TypeError('offline'); };
  r = await fetchEvent(env, '/static/app.css');
  check(r.tag === 'net200', 'sw: network error -> cached copy');
  r = await fetchEvent(env, '/static/nothing.js');
  check(/^error/.test(r), 'sw: network error and nothing cached -> error');
  // an older cache serves too
  env = swEnv();
  await (await env.caches.open('tasks-shell-v1')).put('/static/app.css', {status: 200, tag: 'old'});
  env.fetchImpl = async () => fresh(503, false);
  r = await fetchEvent(env, '/static/app.css');
  check(r.tag === 'old', 'sw: 503 -> an older cache is used');
  // install / activate
  env = swEnv();
  await (await env.caches.open('tasks-shell-v1')).put('/', {status: 200});
  const cur = await env.caches.open(CUR); cur.fail = true;
  check(await lifecycle(env, 'install') === 'failed', 'sw: install fails when a shell file fails');
  await lifecycle(env, 'activate');
  check((await env.caches.keys()).includes('tasks-shell-v1'), 'sw: incomplete new cache -> the old cache stays');
  cur.fail = false; cur.urls = ['/', '/static/app.css'];
  check(await lifecycle(env, 'install') === 'ok', 'sw: install ok');
  await lifecycle(env, 'activate');
  check(!(await env.caches.keys()).includes('tasks-shell-v1'), 'sw: complete new cache -> the old one is removed');

  // ---- reload guard
  const guardSrc = read('js/reloadguard.js').replace(/^const /gm, 'var ').replace(/^(async )?function (\w+)/gm, (m, a, n) => `${a || ''}function ${n}`);
  const make = async (styled, resp) => {
    const dom = new JSDOM('<!doctype html><body></body>', {url: 'http://x/', runScripts: 'outside-only', pretendToBeVisual: true});
    const w = dom.window; w.__reloads = 0;
    w.getComputedStyle = () => ({getPropertyValue: () => styled ? '#0f1012' : ''});
    Object.defineProperty(w, 'fetch', {value: async u => resp(u)});
    w.eval(guardSrc.replaceAll('location.reload()', 'window.__reloads++'));
    w.eval(`rl_sleep = () => Promise.resolve()`);
    return w;
  };
  const okResp = u => ({status: 200, headers: {get: () => /css/.test(u) ? 'text/css' : 'text/html'}});
  let w = await make(true, okResp);
  w.sessionStorage.setItem('kalmido-rl-n', '2');
  await w.eval('rl_check()');
  check(w.sessionStorage.getItem('kalmido-rl-n') === null && !w.__reloads, 'guard: styled page -> counter reset, no reload');
  w = await make(false, okResp);
  await w.eval('rl_check()');
  check(w.__reloads === 1 && w.sessionStorage.getItem('kalmido-rl-n') === '1', 'guard: no styling -> reload, counter 1');
  w.sessionStorage.setItem('kalmido-rl-n', '3');
  await w.eval('rl_check()');
  const n = w.document.querySelector('#rl-notice');
  check(w.__reloads === 1 && n && n.querySelector('button') && n.style.cssText.includes('position'), 'guard: after 3 tries a notice with a button, inline style');
  w.navigator.__defineGetter__('language', () => 'de');
  w.document.body.innerHTML = ''; w.eval('rl_notice()');
  check(/Neu laden/.test(w.document.querySelector('#rl-notice button').textContent), 'guard: German notice');
  w.document.querySelector('#rl-notice button').click();
  check(w.__reloads === 2 && w.sessionStorage.getItem('kalmido-rl-n') === null, 'guard: the button reloads and resets the counter');
  // rl_waitServer
  let calls = 0;
  w = await make(true, u => { calls++; if (calls < 5) return {status: 502, headers: {get: () => ''}}; return okResp(u); });
  check(await w.eval('rl_waitServer(60000)') === true && calls >= 5, 'guard: waits while / answers 502');
  w = await make(true, u => /css/.test(u) ? {status: 200, headers: {get: () => 'text/html'}} : okResp(u));
  w.eval(`rl_sleep = ms => new Promise(r => setTimeout(r, 1))`);
  check(await w.eval('rl_waitServer(30)') === false, 'guard: a stylesheet answered with a page is not "up"');
  w = await make(true, () => { throw new Error('down'); });
  w.eval(`rl_sleep = ms => new Promise(r => setTimeout(r, 1))`);
  check(await w.eval('rl_waitServer(30)') === false, 'guard: server down -> false after the time');

  console.log(F.length ? `FAILED ${F.length}: ${F.join(' | ')}` : `p2450_c_ui OK (${ok} checks)`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERROR', e); process.exit(1); });
