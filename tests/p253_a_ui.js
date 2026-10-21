// 2.53.0 part A (#1410): modules loaded on demand (static/js/lazyload.js). Own container (start.sh).
// - layout: index.html has no script tag for the on-demand modules, sw.js precaches them (LAZY = LD_MODS of lazyload.js)
// - sw.js in a vm: the install caches the shell, then LAZY (a failing LAZY keeps the install); offline, a module with ?v=
//   comes from the cache copy without the query
// - jsdom (boot lazy: true): a cold start loads none of them; opening Settings / the contacts view / a deep link loads them and
//   works; the task panel shows "People and dates" without contacts.js; a module that cannot load -> toast with "Try again"
// - Firefox (real browser, skipped without firefox): the start fetches no on-demand module, the gear opens the settings, the
//   service worker's cache holds every LAZY file
const fs = require('fs'), path = require('path'), vm = require('vm');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p253_a_ui', check: (c, w) => check(c, w), shots: 'P253A_SHOTS', lazy: true});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P253A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const t = await r.text(); let j = {}; try { j = JSON.parse(t); } catch { /* not json */ } return {status: r.status, ...j}; };
const until = async (fn, n = 50) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(100); } return fn(); };
const get = async u => (await fetch(B + u)).text();

// ---- the service worker in a vm: fake caches that know ignoreSearch
function swRun(src, {failLazy = false} = {}) {
  const store = new Map(), listeners = {}, added = [];
  const key = r => (typeof r === 'string' ? r : r.url).replace(/^https?:\/\/[^/]+/, '');
  class C {
    constructor() { this.m = new Map(); }
    async match(r, o = {}) { const k = key(r); if (this.m.has(k)) return this.m.get(k); if (o.ignoreSearch) return this.m.get(k.split('?')[0]); return undefined; }
    async put(r, res) { this.m.set(key(r), res); }
    async addAll(urls) { added.push(urls); if (failLazy && urls.some(u => /office_docs/.test(u))) throw new Error('bad status'); for (const u of urls) this.m.set(u, {status: 200, ok: true, body: 'cached ' + u}); }
  }
  const caches = {async open(n) { if (!store.has(n)) store.set(n, new C()); return store.get(n); }, async keys() { return [...store.keys()]; }, async delete(n) { return store.delete(n); },
    async match(r, o) { for (const c of store.values()) { const x = await c.match(r, o); if (x) return x; } }};
  const self = {addEventListener: (t, f) => { listeners[t] = f; }, location: {origin: 'http://x'}, clients: {claim: async () => {}}, skipWaiting: async () => {}};
  const env = {fetchImpl: () => Promise.reject(new TypeError('offline'))};
  const ctx = vm.createContext({self, caches, URL, Response: class { constructor(b, o) { this.status = (o || {}).status || 200; } }, console,
    fetch: (...a) => env.fetchImpl(...a), TypeError, Promise, Headers, atob, Uint8Array});
  vm.runInContext(src, ctx);
  return {listeners, added, caches, store, env};
}

(async () => {
  // ================= layout + service worker (no browser)
  const html = await get(''), sw = await get('sw.js'), ld = await get('static/js/lazyload.js');
  // 2.149.0 (#2505): the served page adds ?v=<content hash>
  const tags = [...html.matchAll(/<script src="\/static\/js\/([\w-]+)\.js(?:\?v=\w+)?"><\/script>/g)].map(m => m[1]);
  const LAZY = [...(sw.match(/const LAZY = \[(.*?)\];/s) || [, ''])[1].matchAll(/'\/static\/js\/([\w-]+)\.js'/g)].map(m => m[1]);
  const mods = [...(ld.match(/const LD_MODS = \{(.*?)\n\};/s) || [, ''])[1].replace(/^\s*\w+:/gm, '').matchAll(/'([\w-]+)'/g)].map(m => m[1]);
  check(LAZY.length >= 13 && JSON.stringify(LAZY) === JSON.stringify(mods), 'sw.js LAZY = the files of LD_MODS: ' + LAZY.join(' '));
  check(['settings', 'contacts', 'office', 'office_docs', 'officeagents'].every(f => LAZY.includes(f) && !tags.includes(f)), 'settings, contacts, office*: no script tag, in LAZY');
  check(['lazyload', 'setcore', 'ctlinks'].every(f => tags.includes(f)) && tags.indexOf('lazyload') === tags.indexOf('core') + 1, 'lazyload.js right after core.js; setcore.js + ctlinks.js load at start');
  {
    const e = swRun(sw);
    let wait; e.listeners.install({waitUntil: p => { wait = p; }}); await wait;
    check(e.added.length === 2 && e.added[0].includes('/static/js/core.js') && e.added[1].includes('/static/js/settings.js') && !e.added[0].includes('/static/js/settings.js'), 'install: the shell first, then LAZY');
    let res; e.listeners.fetch({request: {method: 'GET', url: 'http://x/static/js/contacts.js?v=2.53.0'}, respondWith: p => { res = p; }});
    const r = await res;
    check(r && r.body === 'cached /static/js/contacts.js', 'offline: contacts.js?v= comes from the cached copy without the query');
    const e2 = swRun(sw, {failLazy: true});
    let w2, threw = false; e2.listeners.install({waitUntil: p => { w2 = p; }}); try { await w2; } catch { threw = true; }
    check(!threw && e2.added.length === 2, 'install: a LAZY file that fails does not drop the install');
  }

  // ================= jsdom: the app
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'});
  const st0 = await call('GET', '/api/state');
  const feats = (st0.settings.features || '').split(',').filter(Boolean);
  await call('PATCH', '/api/settings', {features: [...new Set([...feats, 'contacts', 'office'])].join(',')});
  const LID = (st0.lists || []).find(l => !l.archived)?.id || (await call('POST', '/api/lists', {name: 'Lazy'})).id;
  const TID = (await call('POST', '/api/tasks', {list_id: LID, title: 'Lazy task'})).id;
  check(LID > 0 && TID > 0, 'setup: a list and a task');

  const ready = w => until(() => { try { return w.eval('!!(S.me && S.lists && S.lists.length)'); } catch { return false; } }, 100);
  let w = await boot({user: 'alice', lazy: true}), d = w.document;
  await ready(w);
  const lazyTags = () => [...d.querySelectorAll('script[src*="/static/js/"]')].map(s => (s.getAttribute('src').match(/\/static\/js\/([\w-]+)\.js/) || [])[1]).filter(f => LAZY.includes(f));
  check(lazyTags().length === 0 && typeof w.loadModule === 'function', 'cold start: no on-demand module loaded');
  check(typeof w.wpSweep === 'function' && typeof w.badgeSync === 'function' && w.eval('typeof SET_SECS') === 'object' && w.eval('typeof officeOn') === 'function', 'start-up parts (setcore.js, officeOn) are there');
  check(w.eval('typeof CT') === 'undefined' && w.eval('typeof OFC') === 'undefined', 'contacts + office state not there yet');
  // the task panel: "People and dates" with "Link a contact" from ctlinks.js
  w.location.hash = '#t/' + TID; await until(() => d.querySelector('#detail [data-act="ct-link"]'));
  check(!!d.querySelector('#detail [data-act="ct-link"]') && !lazyTags().includes('contacts'), 'task panel: "Link a contact" without contacts.js');
  // Settings: the stand-in loads settings.js, then opens the dialog
  await w.eval(`settingsModal('look')`);
  await until(() => d.querySelector('.smodal'));
  check(!!d.querySelector('.smodal [data-pane="look"]') && lazyTags().includes('settings'), 'settingsModal() loads settings.js and opens Appearance');
  check(w.eval('settingsModal.name') === 'settingsModal' && !/loadModule/.test(w.eval('String(settingsModal)')), 'after loading: the real settingsModal');
  d.querySelector('.smodal')?.remove();
  // the gear in the sidebar works too (already loaded: opens at once)
  d.querySelector('[data-act="settings"]')?.click(); await until(() => d.querySelector('.smodal'));
  check(!!d.querySelector('.smodal'), 'the gear opens the settings');
  d.querySelector('.smodal')?.remove();
  // contacts view
  w.eval(`go('contacts')`);
  await until(() => lazyTags().includes('contacts') && d.querySelector('#view') && !/Loading…/.test(d.querySelector('#view').textContent || ''));
  check(lazyTags().includes('contacts') && w.eval('typeof CT') === 'object' && !/Loading…/.test(d.querySelector('#view').textContent), 'contacts view: contacts.js loaded, the view drawn');
  // a module that cannot load: toast with "Try again"
  w.eval(`LD_MODS.zz = ['no_such_module']`);
  let failed = false; try { await w.eval(`loadModule('zz')`); } catch { failed = true; }
  await sleep(100);
  const tt = d.querySelector('#toast');
  check(failed && /Could not be loaded/.test(tt?.textContent || '') && /Try again/.test(tt?.querySelector('button')?.textContent || ''), 'a module that cannot load: toast with Try again');
  check(!d.querySelector('script[data-ld="no_such_module"]') && !w.eval(`'zz' in LD_P`), 'the failed module can be tried again (no promise, no tag kept)');
  w.close();

  // deep links on a cold start
  w = await boot({user: 'alice', lazy: true, hash: 'contacts'}); d = w.document; await ready(w);
  await until(() => d.querySelector('#view') && w.eval('typeof CT') === 'object' && !/Loading…/.test(d.querySelector('#view').textContent || ''));
  check(w.eval('typeof CT') === 'object' && !/Loading…/.test(d.querySelector('#view').textContent || ''), 'cold start #contacts: the contacts view');
  check(!lazyTags().includes('settings') && !lazyTags().includes('office'), 'cold start #contacts: only contacts loaded');
  w.close();
  w = await boot({user: 'alice', lazy: true, hash: 'office'}); d = w.document; await ready(w);
  await until(() => w.eval('typeof OFC') === 'object' && !/^\s*Loading…\s*$/.test(d.querySelector('#view .lempty')?.textContent || ''), 80);
  check(w.eval('typeof OFC') === 'object' && lazyTags().filter(f => f.startsWith('office')).length === LAZY.filter(f => f.startsWith('office')).length, 'cold start #office: all office files loaded');
  check(w.eval('OFC_TABS.map(t => t[0]).join()').endsWith('settings') && w.eval('typeof pp_html') === 'function', 'office: the tabs of the later files are there (run in order)');
  w.close();

  // ================= Firefox: real browser + service worker
  await firefox(async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev('(() => { localStorage.clear(); return 1; })()');
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: login');
    await nav(B);
    for (let i = 0; i < 40 && !(await ev('!!(window.S && S.me)').catch(() => false)); i++) await sleep(250);
    // settings.js may come later on its own (the idle preload 5 s after the start): only what started before counts
    const fetched = await ev(`JSON.stringify(performance.getEntriesByType('resource').filter(e => /\\/static\\/js\\/(settings|contacts|office[a-z_]*)\\.js/.test(e.name) && (e.startTime < 4500 || !/settings/.test(e.name))).map(e => e.name.split('/').pop() + '@' + Math.round(e.startTime)))`);
    check(fetched === '[]', 'Firefox: the start fetches no on-demand module ' + fetched);
    await ev(`(document.querySelector('[data-act="settings"]').click(), 1)`);
    for (let i = 0; i < 40 && !(await ev('!!document.querySelector(".smodal")')); i++) await sleep(150);
    check(await ev('!!document.querySelector(".smodal")'), 'Firefox: the gear loads + opens the settings');
    const cached = await ev(`(async () => { const reg = await navigator.serviceWorker.ready; for (let i = 0; i < 60; i++) { const n = await caches.keys(); const c = n.length ? await caches.open(n.filter(k => k.startsWith('tasks-shell')).pop()) : null;
      if (c && await c.match('/static/js/officeagents.js', {ignoreSearch: true})) break;  // 2.149.0 (#2506): kept as <url>?v=<hash> await new Promise(r => setTimeout(r, 250)); }
      const ks = await caches.keys(), c = await caches.open(ks.filter(k => k.startsWith('tasks-shell')).pop()); const miss = [];
      for (const f of ${JSON.stringify(LAZY)}) if (!await c.match('/static/js/' + f + '.js', {ignoreSearch: true})) miss.push(f); return {sw: !!reg.active, miss}; })()`);
    check(cached.sw && !cached.miss.length, 'Firefox: the service worker cache holds every LAZY file ' + JSON.stringify(cached));
  }, false);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
