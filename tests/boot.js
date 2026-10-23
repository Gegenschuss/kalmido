// jsdom boot with the built-in login (cookie) against the test container (proxy port, see start.sh).
const {JSDOM, VirtualConsole, ResourceLoader} = require('jsdom');
// 2.192.0 A (#2512): the test clock for the JS side. KALMIDO_TEST_NOW (ISO instant; without an offset it is Berlin time, like
// testclock.py) + KALMIDO_TEST_NOW_AT (Unix seconds; default: when this file loads) - run_all.sh `now <when>; fresh` sets both -
// shift Date by the same offset as the server (core/db.py) and the Python suites (testclock.py): in Node (the suite) as soon as
// boot.js is required, and in every jsdom window opened with JSDOM.fromURL (before the app's scripts). Only "now" moves
// (Date.now(), new Date(), Date()); dates with arguments, Date.UTC / parse, instanceof, the time zone and the timers stay as
// they are. Without the variable nothing changes.
const berlinMs = s => {  // a wall time without an offset, read as Europe/Berlin
  const u = Date.parse(s + 'Z'), at = new Date(u);
  const p = Object.fromEntries(new Intl.DateTimeFormat('en-US', {timeZone: 'Europe/Berlin', hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit'}).formatToParts(at).map(x => [x.type, x.value]));
  const off = Date.UTC(+p.year, p.month - 1, +p.day, +p.hour, +p.minute, +p.second) - Math.floor(u / 1000) * 1000;
  return u - off;
};
const clockOffset = (() => {
  const v = (process.env.KALMIDO_TEST_NOW || '').trim();
  if (!v) return 0;
  const t = /(Z|[+-]\d\d:?\d\d)$/i.test(v) ? Date.parse(v) : berlinMs(v);
  if (Number.isNaN(t)) throw new Error('KALMIDO_TEST_NOW is not an ISO time: ' + v);
  const at = Number(process.env.KALMIDO_TEST_NOW_AT) * 1000 || Date.now();
  return t - at;
})();
const shiftDate = Real => {  // a Date of the same realm whose "now" is shifted by clockOffset
  if (!clockOffset || Real.__testClock) return Real;
  const now = () => Real.now() + clockOffset;
  function Date(...a) {
    if (!new.target) return new Real(now()).toString();
    return Reflect.construct(Real, a.length ? a : [now()], new.target);
  }
  Object.setPrototypeOf(Date, Real);
  Object.defineProperties(Date, {prototype: {value: Real.prototype}, length: {value: 7}, now: {value: now, writable: true, configurable: true},
    __testClock: {value: true}});
  return Date;
};
exports.testClock = w => { if (clockOffset && w) w.Date = shiftDate(w.Date); return w; };  // own windows (new JSDOM without fromURL)
exports.testNow = () => new Date();  // the suite's "now" (the test time when KALMIDO_TEST_NOW is set)
if (clockOffset) {
  globalThis.Date = shiftDate(globalThis.Date);
  const fromURL = JSDOM.fromURL;
  JSDOM.fromURL = (url, o = {}) => {
    const bp = o.beforeParse;
    return fromURL.call(JSDOM, url, {...o, beforeParse(w) { exports.testClock(w); if (bp) bp(w); }});
  };
}
// 2.20.0 (#646): the web client is ~30 script files. jsdom's own loader opens a NEW keep-alive connection for every
// resource and never closes it, so a few windows reach the server's connection limit (waitress: 100) and the scripts of
// the next window stall. Browsers share a few connections per host; this loader does the same for the page's scripts and
// stylesheets: Node's fetch (one pooled agent, idle connections are reused), at most 6 requests at a time.
class PooledLoader extends ResourceLoader {
  fetch(url, opts = {}) {
    if (!opts.element || !/^https?:\/\//.test(url)) return super.fetch(url, opts);
    const ac = new AbortController();
    const p = PooledLoader.slot().then(async done => {
      try {
        const r = await fetch(url, {signal: ac.signal, headers: {'Accept-Language': 'en'}});
        p.response = {statusCode: r.status, headers: Object.fromEntries(r.headers)};
        if (r.status < 200 || r.status > 299) throw new Error(`Resource was not loaded. Status: ${r.status}`);
        return Buffer.from(await r.arrayBuffer());
      } finally { done(); }
    });
    p.abort = () => ac.abort(); p.href = url; p.getHeader = () => undefined;
    return p;
  }
  static slot() {  // a tiny semaphore: resolves with a release function
    return new Promise(res => { const go = () => { PooledLoader.busy++; res(() => { PooledLoader.busy--; const n = PooledLoader.wait.shift(); if (n) n(); }); }; if (PooledLoader.busy < 6) go(); else PooledLoader.wait.push(go); });
  }
}
PooledLoader.busy = 0; PooledLoader.wait = [];
exports.PooledLoader = PooledLoader;
const B = process.env.BASE || `http://127.0.0.1:${process.env.KALMIDO_TEST_PROXY_PORT || 3041}/`;
exports.B = B; exports.errs = [];
// 2.65.0 (#1824): the app's whole CSS = app.css + the module stylesheets (static/css/, LAZY_CSS of sw.js, in that order: they
// come later in the cascade); the suites that read rules use this, a rule may have moved into a module's stylesheet
const cssList = sw => [...((sw.match(/const LAZY_CSS = \[(.*?)\];/s) || [, ''])[1]).matchAll(/'\/static\/css\/([\w-]+\.css)'/g)].map(m => m[1]);
exports.allCss = async () => {
  const sw = await (await fetch(B + 'sw.js')).text(), parts = [await (await fetch(B + 'static/app.css')).text()];
  for (const f of cssList(sw)) parts.push(await (await fetch(B + 'static/css/' + f)).text());
  return parts.join('\n');
};
exports.allCssSync = () => {
  const fs = require('fs'), st = require('path').join(__dirname, '..', 'static'), rd = f => fs.readFileSync(require('path').join(st, f), 'utf8');
  return [rd('app.css'), ...cssList(rd('sw.js')).map(f => rd('css/' + f))].join('\n');
};
// 2.20.0 (#646): the web client is static/js/*.js (the order of the script tags in index.html); this is all of it as one text
exports.clientSource = async () => {
  const html = await (await fetch(B)).text();
  // 2.149.0 (#2505): the served page adds ?v=<content hash>
  const mods = [...html.matchAll(/<script src="\/static\/js\/([\w-]+\.js)(?:\?v=\w+)?"><\/script>/g)].map(m => m[1]);
  if (!mods.length) throw new Error('index.html loads no static/js/ modules');
  // 2.53.0 (#1410): + the modules loaded on demand (LAZY in sw.js)
  const lazy = ((await (await fetch(B + 'sw.js')).text()).match(/const LAZY = \[(.*?)\];/s) || [, ''])[1];
  mods.push(...[...lazy.matchAll(/'\/static\/js\/([\w-]+\.js)'/g)].map(m => m[1]));
  return (await Promise.all(mods.map(async f => (await fetch(B + 'static/js/' + f)).text()))).join('\n');
};
// 2.0.5 / 2.0.6: app code that is still running when a suite closes its window (an awaited fetch returning after
// w.close(), e.g. loadJobs() -> renderView() in p200_ui.js on CI: "Cannot read properties of undefined (reading
// 'querySelector')" at $() because the closed window has no document) rejects; that is the harness, not the app.
// Only exactly that is ignored: a TypeError created in the realm of a window this suite closed, about a missing
// object, thrown in the app's own scripts. Anything else (open windows, the suite's own code) still fails the run.
const closedRealms = [];
const lateAppError = e => !!e && closedRealms.some(T => e instanceof T) && /Cannot read propert(y|ies) of (undefined|null)/.test(e.message || '')
  && /\/static\/(js\/)?[\w.-]+\.js/.test(String(e.stack || '').split('\n').slice(0, 2).join('\n'));
process.on('unhandledRejection', e => {
  if (lateAppError(e)) { console.log('late app rejection after a window was closed (ignored):', String(e.stack).split('\n').slice(0, 2).join(' | ')); return; }
  console.error(e); process.exit(1);
});
// 1.5: the app asks with its own dialog (askConfirm / askPrompt, .modal.cdlg) instead of window.confirm / prompt. This
// bridge answers it with the suite's w.confirm / w.prompt stubs (title + text as the message), so older suites keep
// working; w.__dialogs = 'manual' leaves the dialogs alone (tests/ux1_ui.js drives them itself).
exports.dialogBridge = w => {
  const hook = () => new w.MutationObserver(() => {
    if (!w.document) return;  // window closed
    for (const md of w.document.querySelectorAll('.modal.cdlg:not([data-bridged])')) {
      md.dataset.bridged = '1';
      if (w.__dialogs === 'manual') continue;
      setTimeout(() => {
        if (!w.document || !md.isConnected) return;
        const t = [md.querySelector('#cdlg-t')?.textContent, md.querySelector('#cdlg-b')?.textContent].filter(Boolean).join(' ');
        const inp = md.querySelector('#cdlg-in');
        if (inp) { const v = w.prompt(md.querySelector('#cdlg-t')?.textContent || '', inp.value); if (v === null || v === undefined) md.querySelector('[data-cd="no"]').click(); else { inp.value = v; md.querySelector('[data-cd="yes"]').click(); } }
        else md.querySelector(w.confirm(t) ? '[data-cd="yes"]' : '[data-cd="no"]').click();
      }, 0);
    }
  }).observe(w.document.documentElement, {childList: true, subtree: true});
  if (w.document.readyState === 'loading') w.addEventListener('DOMContentLoaded', hook); else hook();
};
// 2.56.1 (#1799): legacy suites check every row symbol; the default level "Important" hides some, so every login of a
// suite sets row_icons=all for that person (o.rowIcons: another level, null = leave the default; p2561_b_ui.js)
const rowIconsSet = async (hd, o = {}) => {
  if (o.rowIcons === null) return;
  try { await fetch(B + 'api/settings', {method: 'PATCH', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido', ...hd}, body: JSON.stringify({row_icons: o.rowIcons || 'all'})}); } catch { /* best effort */ }
};
exports.login = async (user, pw = 'password123', o = {}) => {
  const r = await fetch(B + 'api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: user, password: pw})});
  if (!r.ok) throw new Error('login ' + user + ' ' + r.status);
  const ck = r.headers.get('set-cookie').split(';')[0];
  await rowIconsSet({Cookie: ck}, o);
  return ck;
};
// 2.53.0 (#1410): lazy = false (the default) loads the modules the app loads on demand (settings, contacts, office) right after
// the start, so suites can call their functions directly; lazy: true leaves them to the app (tests/p253_a_ui.js)
// 2.126.0 D (#1989): shared = {store: {}, wins: []}: windows of one browser -- one localStorage, a write fires "storage" in the others
exports.boot = async function boot({user = 'alice', mobile = false, hash = '', ls = {}, wait = 2500, proxy = null, path = '', media = {}, setup = null, lazy = false, rowIcons, shared = null} = {}) {
  const cookie = proxy ? '' : await exports.login(user, undefined, {rowIcons});
  if (proxy) await rowIconsSet({'Remote-User': proxy}, {rowIcons});  // 2.56.1 (#1799)
  // 1.8.1: the start view is the Inbox; the suites written before start on Today as a device that was there last
  // (pass ls: {'tasks.lastKey': null} for a real first start, p181_ui.js)
  // 2.17.0 (#452): News are bundled per task by default; the suites written before test the plain list (that device
  // setting), p2170_ui passes ls: {'tasks.newsBundle': null} for the bundled default
  const store = Object.assign(shared ? shared.store : {}, {'tasks.newsBundle': 'false', ...(hash || 'tasks.lastKey' in ls ? {} : {'tasks.lastKey': '"today"'}), ...ls});
  for (const k of Object.keys(store)) if (store[k] === null) delete store[k];
  const vc = new VirtualConsole(); vc.on('jsdomError', e => { if (!/navigation|Not implemented/.test(e.message)) { exports.errs.push(e.message); console.log('script error:', String((e.detail && e.detail.stack) || e.stack || '').split('\n').slice(0, 4).join(' | ')); } });
  const dom = await JSDOM.fromURL(B + path + (hash ? '#' + hash : ''), {runScripts: 'dangerously', resources: new PooledLoader(), pretendToBeVisual: true, virtualConsole: vc,
    beforeParse(w) {
      w.matchMedia = q => ({matches: q in media ? media[q] : /max-width/.test(q) ? mobile : false, addEventListener() {}, addListener() {}});  // media: {'(prefers-reduced-motion: reduce)': true}
      const told = k => { for (const o of shared ? shared.wins : []) if (o !== w) { const e = new o.Event('storage'); e.key = k; o.dispatchEvent(e); } };
      Object.defineProperty(w, 'localStorage', {value: {getItem: k => k in store ? store[k] : null, setItem: (k, v) => { store[k] = String(v); told(k); }, removeItem: k => { delete store[k]; told(k); }, key: i => Object.keys(store)[i], get length() { return Object.keys(store).length; }}});
      w.__offline = false;
      w.fetch = (u, o = {}) => { if (w.__offline) return Promise.reject(new TypeError('Failed to fetch')); const hd = {...(o.headers || {}), ...(proxy ? {'Remote-User': proxy} : {Cookie: cookie})}; const sg = o.signal && (ac => { if (o.signal.aborted) ac.abort(); else o.signal.addEventListener('abort', () => ac.abort()); return ac.signal; })(new AbortController());  // 2.116.0 (#2065): a jsdom signal -> Node's
        return fetch(new URL(String(u), B), {...o, headers: hd, ...(sg ? {signal: sg} : {})}); };
      w.Request = Request; w.Response = Response; w.Headers = Headers; w.FormData = FormData; w.File = File; w.Blob = Blob;
      Object.defineProperty(w.navigator, 'serviceWorker', {configurable: true, value: {register: () => Promise.resolve(), addEventListener() {}, controller: null}});
      w.scrollTo = () => {}; w.Element.prototype.scrollIntoView = () => {};
      w.confirm = () => true; w.prompt = () => null;
      exports.dialogBridge(w);
      if (setup) setup(w);  // extra browser APIs for one suite (webpush_ui.js: Notification, PushManager, ...)
    }});
  await new Promise(r => setTimeout(r, wait));
  // 2.98.0: a slow place may still be loading the start scripts after `wait` (appearance_ui saw calendar.js not yet run): up to 15 s more until all ran
  for (let i = 0; i < 150 && dom.window.document.readyState !== 'complete'; i++) await new Promise(r => setTimeout(r, 100));
  if (!lazy && typeof dom.window.ld_all === 'function') await dom.window.ld_all().catch(e => console.log('ld_all:', e.message));
  dom.window.__cookie = cookie; dom.window.__store = store;
  if (shared) shared.wins.push(dom.window);
  const close = dom.window.close.bind(dom.window), realmTE = dom.window.TypeError;
  dom.window.close = () => { if (!closedRealms.includes(realmTE)) closedRealms.push(realmTE); close(); };
  return dom.window;
};
exports.sleep = ms => new Promise(r => setTimeout(r, ms));
// 2.37.0: the same for suites with their own jsdom page() (signin_ui.js): a late rejection of a window they closed is the harness
exports.trackClose = w => {
  const close = w.close.bind(w), realmTE = w.TypeError;
  w.close = () => { if (!closedRealms.includes(realmTE)) closedRealms.push(realmTE); close(); };
};
