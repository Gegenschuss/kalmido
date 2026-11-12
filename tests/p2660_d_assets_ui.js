// 2.660.0 UI test, part D (#4197): modules on demand with their content hash, no settings in the idle chain, a version per language part.
// kalmido-suite: fresh
// Own container (start.sh), jsdom; the service worker in a sandbox (no server).
// freelancer-matrix: public
// - the page names every module file loaded on demand with the hash of its served bytes (meta kalmido-ldjs / kalmido-ldcss);
//   that address is immutable; ld_url / loadCss / the loaded script use it and never the version of the code (two versions
//   with the same module = the same address); a file without a hash falls back to the version of the code
// - the idle chain no longer loads the settings (nor their dependencies); with the data saver it loads nothing
// - the page names a version per language part (meta kalmido-i18nv) = the hash of the served part, immutable under it; the
//   start fetches the core and a module's part with their own version; a changed part is the only one fetched again (the
//   others keep their cached address); the copy in localStorage is written only when its version changes
// - sw-manifest.json: the precached German core with its own version, "i18n" = every current part version; the worker keeps
//   every unchanged part of an old cache over an update and answers a confirmed versioned part without the network
// - a person without an organisation gets the same
// KMT_NOSTART=1 = the container is running.
const fs = require('fs'), path = require('path'), vm = require('vm'), crypto = require('crypto');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const sha12 = buf => crypto.createHash('sha256').update(buf).digest('hex').slice(0, 12);
const metaOf = (html, name) => (html.match(new RegExp(`<meta name="${name}" content="([^"]*)">`)) || [])[1];
const pairs = s => Object.fromEntries((s || '').split(' ').filter(Boolean).map(p => p.split('=')));
// meta kalmido-i18nv: "core,<module>,…;<code>=<12 hex per part>;…" -> {code: {part: hash}}
function i18nTable(s) {
  const [n, ...rows] = (s || '').split(';'), ns = (n || '').split(','), out = {};
  for (const r of rows) { const [c, hx] = r.split('='); out[c] = Object.fromEntries(ns.map((m, i) => [m, hx.slice(i * 12, i * 12 + 12)])); }
  return out;
}

// ================= the service worker in a sandbox: an update keeps the unchanged language parts, a confirmed part needs no network
const SRC = fs.readFileSync(path.join(__dirname, '..', 'static', 'sw.js'), 'utf8');
const CACHE = (SRC.match(/const CACHE = '([^']+)'/) || [])[1];
const ORIGIN = 'https://kalmido.example';
function sandbox({manifest, old = {}, offline = false}) {
  const store = new Map(Object.entries(old).map(([n, m]) => [n, new Map(Object.entries(m))]));
  const fetched = [];
  const norm = k => String((k && k.url) || k).replace(ORIGIN, '');
  const resp = (url, body, cc, type = 'application/json') => ({ok: true, status: 200, redirected: false, type: 'basic', url, body,
    headers: new Headers({'content-type': type, ...(cc ? {'cache-control': cc} : {})}), clone() { return this; }, json: async () => JSON.parse(body)});
  const fetchF = async u => {
    u = norm(u); fetched.push(u);
    if (offline) throw new TypeError('offline');
    if (u === '/sw-manifest.json') return resp(u, JSON.stringify(manifest), 'no-cache');
    const [p, q] = u.split('?v=');
    return resp(u, 'body of ' + u, q && (manifest.files[p] === q || (manifest.i18n || []).includes(q)) ? 'public, max-age=31536000, immutable' : 'no-cache');
  };
  const cache = name => {
    if (!store.has(name)) store.set(name, new Map());
    const m = store.get(name);
    return {put: async (k, r) => { m.set(norm(k), r); }, delete: async k => m.delete(norm(k)), keys: async () => [...m.keys()].map(k => ({url: ORIGIN + k})),
      add: async u => { m.set(norm(u), await fetchF(u)); }, addAll: async us => { for (const u of us) m.set(norm(u), await fetchF(u)); },
      match: async (k, o) => { k = norm(k); if (m.has(k)) return m.get(k); if (o && o.ignoreSearch) for (const [kk, v] of m) if (kk.split('?')[0] === k.split('?')[0]) return v; return undefined; }};
  };
  const caches = {open: async n => cache(n), keys: async () => [...store.keys()], delete: async n => store.delete(n),
    match: async (k, o) => { for (const n of store.keys()) { const r = await cache(n).match(k, o); if (r) return r; } return undefined; }};
  const handlers = {};
  const self = {addEventListener: (k, f) => { handlers[k] = f; }, skipWaiting: async () => {}, clients: {claim: async () => {}, matchAll: async () => []}, location: {origin: ORIGIN}, navigator: {}};
  vm.runInContext(SRC, vm.createContext({self, caches, fetch: fetchF, URL, Headers, console, setTimeout, Promise, TypeError, Response: function () {}}), {filename: 'sw.js'});
  const life = async kind => { let p; handlers[kind]({waitUntil: x => { p = x; }}); return p; };
  const get = async url => { let p = null; handlers.fetch({request: {url: ORIGIN + url, method: 'GET', headers: new Headers()}, respondWith: x => { p = x; }}); return p; };
  return {store, fetched, life, get, keys: n => [...(store.get(n) || new Map()).keys()]};
}
async function swCheck() {
  const files = {};
  for (const m of SRC.matchAll(/const (?:SHELL|LAZY|LAZY_CSS) = \[(.*?)\];/gs)) for (const x of m[1].matchAll(/'(\/static\/[^']+)'/g)) files[x[1]] = 'f00000000000';
  files['/static/i18n/de.core.json'] = 'c00000000001';
  const same = '/static/i18n/fr.mod-office.json?v=a00000000001', changed = '/static/i18n/fr.mod-wiki.json?v=b00000000001', core = '/static/i18n/fr.core.json?v=c00000000002';
  const imm = {ok: true, headers: new Headers({'content-type': 'application/json', 'cache-control': 'public, max-age=31536000, immutable'})};
  const s = sandbox({manifest: {v: 1, files, i18n: ['a00000000001', 'c00000000001', 'c00000000002', 'b00000000002']},
    old: {'tasks-shell-v1': {[same]: imm, [changed]: imm, [core]: imm}}});
  await s.life('install');
  const k = s.keys(CACHE);
  check(k.includes(same) && k.includes(core), 'sw: an update keeps the unchanged parts of an old cache (a module part and a core of another language)');
  check(!k.includes(changed), 'sw: a part whose version changed is not kept');
  // 2.1060.0 (#5877): only the language parts (/static/i18n/fr.*); since #5785 (552e0c109) the precached module
  // /static/js/quotes_dada_fr.js also has "fr." in its name and is rightly fetched on install
  check(!s.fetched.some(u => /^\/static\/i18n\/fr\./.test(u)), 'sw: the kept parts are not fetched again');
  s.fetched.length = 0;
  const hit = await s.get(same);
  check(hit === imm && !s.fetched.length, 'sw: a part asked for with its confirmed version comes from the cache without the network');
  await s.get('/static/i18n/fr.mod-office.json?v=2.660.0');
  check(s.fetched.includes('/static/i18n/fr.mod-office.json?v=2.660.0'), 'sw: a part asked for with another version stays network-first');
}

(async () => {
  await swCheck();
  if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'de'})});
  check(r.ok, 'setup');
  const CK = await login('alice');
  await call(CK, 'POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'de', collab_all: true, modules: ['cal', 'comments']});
  await call(CK, 'PATCH', '/api/settings', {lang: 'de', tour: 'done', features: 'cal,comments,office,wiki'});
  const html = await (await fetch(B, {headers: {Cookie: CK}})).text();
  const APPV = metaOf(html, 'kalmido-version');

  // ================= the page names the module files with their content hash
  const JS = pairs(metaOf(html, 'kalmido-ldjs')), CSS = pairs(metaOf(html, 'kalmido-ldcss'));
  const sw = await (await fetch(B + 'sw.js')).text();
  const lazy = [...((sw.match(/const LAZY = \[(.*?)\];/s) || [])[1] || '').matchAll(/'\/static\/js\/([\w-]+)\.js'/g)].map(m => m[1]);
  const lazyCss = [...((sw.match(/const LAZY_CSS = \[(.*?)\];/s) || [])[1] || '').matchAll(/'\/static\/css\/([\w-]+)\.css'/g)].map(m => m[1]);
  check(lazy.length > 100 && lazy.every(f => /^[0-9a-f]{12}$/.test(JS[f] || '')), `every module script has a hash (${Object.keys(JS).length} of ${lazy.length}) ${lazy.filter(f => !JS[f]).slice(0, 3)}`);
  check(lazyCss.length > 10 && lazyCss.every(f => /^[0-9a-f]{12}$/.test(CSS[f] || '')), `every module stylesheet has a hash (${Object.keys(CSS).length} of ${lazyCss.length})`);
  for (const [u, h] of [['js/settings.js', JS.settings], ['js/office.js', JS.office], ['css/settings.css', CSS.settings]]) {
    const plain = await fetch(B + 'static/' + u, {headers: {'Accept-Encoding': 'identity'}});
    check(h === sha12(Buffer.from(await plain.arrayBuffer())), `${u}: the hash is the served bytes'`);
    const rh = await fetch(B + `static/${u}?v=${h}`);
    check(rh.ok && /immutable/.test(rh.headers.get('cache-control') || ''), `${u}?v=<hash>: immutable ${rh.headers.get('cache-control')}`);
  }

  // ================= the version per language part
  const T = i18nTable(metaOf(html, 'kalmido-i18nv')), V = metaOf(html, 'kalmido-i18n');
  check(['de', 'fr', 'es', 'it', 'nl'].every(c => T[c] && /^[0-9a-f]{12}$/.test(T[c].core || '') && /^[0-9a-f]{12}$/.test(T[c].settings || '')), 'the page names a version for every part of every language ' + Object.keys(T));
  const coreDe = await (await fetch(B + `static/i18n/de.core.json?v=${T.de.core}`)).json();
  check(Array.isArray(coreDe._mods) && coreDe._mods.every(m => /^[0-9a-f]{12}$/.test(T.de[m] || '')), 'every module of the core has a version');
  for (const [code, m] of [['de', 'core'], ['de', 'settings'], ['fr', 'office']]) {
    const u = `static/i18n/${code}.${m === 'core' ? 'core' : 'mod-' + m}.json`;
    const rp = await fetch(B + `${u}?v=${T[code][m]}`);
    const body = Buffer.from(await rp.arrayBuffer());
    check(rp.ok && /immutable/.test(rp.headers.get('cache-control') || '') && sha12(body) === T[code][m], `${u}: the version is the hash of the part, immutable under it`);
    const rg = await fetch(B + `${u}?v=${V}`);  // the version of all split texts still counts (a page from before)
    check(rg.ok && /immutable/.test(rg.headers.get('cache-control') || ''), `${u}?v=<version of all>: still immutable`);
  }
  check(new Set(Object.values(T.de)).size > Object.keys(T.de).length / 2, 'the parts have their own versions (not one for all)');
  const man = await (await fetch(B + 'sw-manifest.json')).json();
  check(man.files['/static/i18n/de.core.json'] === T.de.core, 'sw-manifest: the German core with its own version');
  check(Array.isArray(man.i18n) && Object.values(T).every(t => Object.values(t).every(h => man.i18n.includes(h))), `sw-manifest: "i18n" names every current part version (${(man.i18n || []).length})`);

  // ================= jsdom: ld_url / loadCss / the loaded script
  const seen = [];
  const rec = x => { const f0 = x.fetch; x.fetch = (u, o) => { seen.push(String(u)); return f0(u, o); }; };
  let w = await boot({user: 'alice', lazy: true, ls: {'tasks.lang': '"de"'}, setup: rec}), d = w.document;
  check(w.eval(`ld_url('settings')`) === `/static/js/settings.js?v=${JS.settings}`, 'ld_url: the content hash ' + w.eval(`ld_url('settings')`));
  check(!w.eval(`ld_url('settings')`).includes(APPV), 'ld_url: never the version of the code (two versions with the same module = one address)');
  await w.eval(`loadModule('settings')`);
  check(d.querySelector('script[data-ld="settings"]')?.getAttribute('src') === `/static/js/settings.js?v=${JS.settings}`, 'the loaded script carries the hash');
  const cssHref = [...d.querySelectorAll('link[rel="stylesheet"]')].map(l => l.getAttribute('href')).filter(h => /^\/static\/css\/settings\.css/.test(h || ''));
  check(cssHref.length === 1 && cssHref[0] === `/static/css/settings.css?v=${CSS.settings}`, 'loadCss: the stylesheet carries the hash ' + cssHref);
  check(w.eval(`(delete LD_HASH.js.settings, ld_url('settings'))`) === `/static/js/settings.js?v=${encodeURIComponent(APPV)}`, 'a file without a hash: the version of the code');
  // the language parts with their own version
  const i18n = seen.filter(u => /\/static\/i18n\//.test(u));
  check(i18n.some(u => u.includes(`de.core.json?v=${T.de.core}`)) && i18n.some(u => u.includes(`de.mod-settings.json?v=${T.de.settings}`)), 'the core and the settings part with their own version ' + i18n.slice(0, 2));
  // the idle chain: no settings
  check(!w.eval(`LD_IDLE.some(m => m[0] === 'settings')`), 'LD_IDLE names no settings');
  w.close();

  // ================= the idle chain on a fresh page: the areas switched on, never the settings; the data saver: nothing
  const asked = [];
  const recLoad = x => { x.addEventListener('DOMContentLoaded', () => { const lm = x.loadModule; x.loadModule = (n, a) => { asked.push(n); return lm(n, a); }; }); };
  w = await boot({user: 'alice', lazy: true, ls: {'tasks.lang': '"de"'}, setup: recLoad});
  w.eval('ld_idle(0)');
  await until(() => w.eval('LD_RAN.has("wiki") && LD_RAN.has("calview")'), 100);
  await new Promise(res => w.setTimeout(res, 0));  // after the last step of the chain (docs / life are off)
  check(asked.includes('calendar') && asked.includes('wiki') && !asked.includes('settings') && !w.eval('LD_P.settings') && !w.eval('LD_P.agentchat'),
    'the idle chain: calendar and wiki, no settings, none of their dependencies ' + [...new Set(asked)].join(' '));
  w.close();
  w = await boot({user: 'alice', lazy: true, ls: {'tasks.lang': '"de"'}, setup: x => {
    Object.defineProperty(x.navigator, 'connection', {configurable: true, value: {saveData: true, effectiveType: '4g'}});
  }});
  const p0 = Object.keys(w.eval('LD_P'));
  w.eval('ld_idle(0)');
  await new Promise(res => w.setTimeout(res, 0)); await new Promise(res => w.setTimeout(res, 0));  // the idle step queued before ran
  check(!w.eval('LD_P.calendar') && Object.keys(w.eval('LD_P')).length === p0.length, 'data saver: the idle chain loads nothing ' + Object.keys(w.eval('LD_P')));
  w.close();

  // ================= the copy in localStorage: written only when its version changes; a changed part alone is fetched again
  const writes = [];
  // the core's copy (i18nLoad) holds no "parts"; the copy with the parts of the modules (i18nMirror, no service worker) is counted apart
  const wrapLs = x => { const ls = x.localStorage, s0 = ls.setItem; ls.setItem = (k, v) => { if (/^tasks\.i18n/.test(k)) writes.push(k + (String(v).includes('"parts":[') ? ':parts' : '')); return s0(k, v); }; };
  w = await boot({user: 'alice', lazy: true, ls: {'tasks.lang': '"de"'}, setup: wrapLs});
  check(writes.includes('tasks.i18n') && w.__store['tasks.i18n.v'] === 'de@' + T.de.core, 'first start: the copy is written with its version ' + w.__store['tasks.i18n.v']);
  let store = {...w.__store};
  w.close();
  writes.length = 0;
  w = await boot({user: 'alice', lazy: true, ls: {...store, 'tasks.lang': '"de"'}, setup: wrapLs});
  check(w.eval('I18N.code') === 'de' && w.eval('tr("Basket")') === 'Eingang' && !writes.includes('tasks.i18n'), 'second start, same version: German, the copy is not written again ' + writes);
  w.close();
  writes.length = 0;
  w = await boot({user: 'alice', lazy: true, ls: {...store, 'tasks.lang': '"de"', 'tasks.i18n.v': 'de@000000000000'}, setup: wrapLs});
  check(writes.includes('tasks.i18n'), 'another version: the copy is written again');
  w.close();
  // a changed part: with a kept copy of each part (the service worker's cache), only that one is fetched again
  const kept = new Set(), got = [];
  const swLike = x => {
    const f0 = x.fetch;
    x.fetch = (u, o) => { u = String(u); if (/\/static\/i18n\/de\.mod-/.test(u)) got.push(u); return f0(u, o).then(rr => { if (rr.ok) kept.add(u.replace(B, '/')); return rr; }); };
    Object.defineProperty(x.navigator, 'serviceWorker', {configurable: true, value: {register: () => Promise.resolve(), controller: {}, ready: Promise.resolve({}), addEventListener() {}}});
    x.caches = {match: async u => (kept.has(String(u).replace(B, '/')) ? {} : undefined)};
    x.requestIdleCallback = f => setTimeout(f, 0);
  };
  w = await boot({user: 'alice', lazy: true, ls: {'tasks.lang': '"de"'}, setup: swLike});
  w.ld_idle = () => {};
  await w.eval('clearTimeout(I18N_WT), I18N_WARMED.clear(), i18nWarm()');  // not the warming of the start (8 s) in between
  const n1 = new Set(got).size;
  check(n1 === coreDe._mods.length, `warmed: every part once (${n1} of ${coreDe._mods.length})`);
  got.length = 0;
  // the next version: only the part of the office changed
  await w.eval(`I18N_PV.de['mod-office'] = 'ffffffffffff', I18N_WARMED.clear(), i18nWarm()`);
  check(got.length === 1 && got[0].includes('de.mod-office.json?v=ffffffffffff'), 'a changed part: only that one is fetched again ' + got.slice(0, 3));
  w.close();

  // ================= a person without an organisation
  await call(CK, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida').catch(() => null);
  if (CF) {
    await call(CF, 'PATCH', '/api/settings', {lang: 'de', tour: 'done'});
    const fh = await (await fetch(B, {headers: {Cookie: CF}})).text();
    check(metaOf(fh, 'kalmido-ldjs') === metaOf(html, 'kalmido-ldjs') && metaOf(fh, 'kalmido-i18nv') === metaOf(html, 'kalmido-i18nv'), 'without an organisation: the same tables');
    w = await boot({user: 'frida', lazy: true, ls: {'tasks.lang': '"de"'}});
    await w.eval(`loadModule('settings')`);
    check(w.document.querySelector('script[data-ld="settings"]')?.getAttribute('src') === `/static/js/settings.js?v=${JS.settings}` && w.eval('tr("Basket")') === 'Eingang', 'without an organisation: the settings with their hash, German');
    w.close();
  } else check(false, 'a person without an organisation signs in');

  console.log(`\np2660_d_assets_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
