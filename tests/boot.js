// jsdom boot with the built-in login (cookie) against the test container (proxy port, see start.sh).
const {JSDOM, VirtualConsole, requestInterceptor} = require('jsdom');
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
// 2.381.0 (#2713): self-contained (no outer names) - ff.js hands its source to Firefox as a preload script
const shiftedDate = (Real, off) => {  // a Date of Real's realm whose "now" is shifted by off ms
  if (!off || Real.__testClock) return Real;
  const now = () => Real.now() + off;
  function Date(...a) {
    if (!new.target) return new Real(now()).toString();
    return Reflect.construct(Real, a.length ? a : [now()], new.target);
  }
  Object.setPrototypeOf(Date, Real);
  Object.defineProperties(Date, {prototype: {value: Real.prototype}, length: {value: 7}, now: {value: now, writable: true, configurable: true},
    __testClock: {value: true}});
  return Date;
};
const shiftDate = Real => shiftedDate(Real, clockOffset);  // a Date of the same realm whose "now" is shifted by clockOffset
exports.clockOffset = clockOffset;
exports.shiftedDate = shiftedDate;
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
// 2.360.3 (#2916): jsdom 30 has no ResourceLoader class any more: an object with interceptors as option "resources"; the answer
// of Node's fetch is already unpacked, so its content-encoding / length headers do not go along
class PooledLoader {
  constructor() {
    this.interceptors = [requestInterceptor((req, {element}) => element && /^https?:\/\//.test(req.url) ? this.fetch(req.url) : undefined)];
  }
  async fetch(url) {
    const done = await PooledLoader.slot();
    try {
      const r = await fetch(url, {headers: {'Accept-Language': 'en'}});
      const headers = new Headers(r.headers); headers.delete('content-encoding'); headers.delete('content-length');
      return new Response(await r.arrayBuffer(), {status: r.status, headers});
    } finally { done(); }
  }
  static slot() {  // a tiny semaphore: resolves with a release function
    return new Promise(res => { const go = () => { PooledLoader.busy++; res(() => { PooledLoader.busy--; const n = PooledLoader.wait.shift(); if (n) n(); }); }; if (PooledLoader.busy < 6) go(); else PooledLoader.wait.push(go); });
  }
}
PooledLoader.busy = 0; PooledLoader.wait = [];
exports.PooledLoader = PooledLoader;
// 2.360.3 (#2916): after a restart of the container in the middle of a suite: jsdom 30 keeps its connections to the old server
exports.dropConnections = () => { const {Agent, setGlobalDispatcher} = require('undici'); setGlobalDispatcher(new Agent()); };
const B = process.env.BASE || `http://127.0.0.1:${process.env.KALMIDO_TEST_PROXY_PORT || 3041}/`;
exports.B = B; exports.errs = [];
// 2.609.0 (#4512): the test data folder (KALMIDO_TEST_DATA, the same as DATA in tests/kt.py) and the state files a suite writes
// there for the suites after it in its group (ids.json of api_test.py, cal_ids.json of calendars_test.py): not in tests/, so two
// runs in one work tree never overwrite each other's. meId(cookie): the user id of a login, instead of a fixed /api/users/1.
exports.TEST_DATA = process.env.KALMIDO_TEST_DATA || require('path').join(__dirname, '.data');
exports.stateFile = name => require('path').join(exports.TEST_DATA, name);
exports.readState = name => JSON.parse(require('fs').readFileSync(exports.stateFile(name), 'utf8'));
exports.meId = async cookie => {
  const r = await fetch(B + 'api/me', {headers: {'X-Requested-With': 'kalmido', Cookie: cookie}});
  if (!r.ok) throw new Error('/api/me: HTTP ' + r.status);
  return (await r.json()).id;
};
// 2.65.0 (#1824): the app's whole CSS = app.css + the module stylesheets (static/css/, LAZY_CSS of sw.js, in that order: they
// come later in the cascade); the suites that read rules use this, a rule may have moved into a module's stylesheet
const cssList = sw => [...((sw.match(/const LAZY_CSS = \[(.*?)\];/s) || [, ''])[1]).matchAll(/'\/static\/css\/([\w-]+\.css)'/g)].map(m => m[1]);
// 2.168.3 (CI): the server sends CSS without comments since 2.191.0 B (#1824), the suites find rules by their version
// comments, so they read the files themselves (the same bytes before the strip); over HTTP only without a static/ beside tests/
exports.allCss = async () => {
  if (require('fs').existsSync(require('path').join(__dirname, '..', 'static', 'app.css'))) return exports.allCssSync();
  const sw = await (await fetch(B + 'sw.js')).text(), parts = [await (await fetch(B + 'static/app.css')).text()];
  for (const f of cssList(sw)) parts.push(await (await fetch(B + 'static/css/' + f)).text());
  return parts.join('\n');
};
exports.allCssSync = () => {
  const fs = require('fs'), st = require('path').join(__dirname, '..', 'static'), rd = f => fs.readFileSync(require('path').join(st, f), 'utf8');
  // 2.476.0 (#3487): + the start style files (static/css/start-*.css, sorted), which the server sends behind app.css
  const starts = fs.readdirSync(require('path').join(st, 'css')).filter(f => /^start-.*\.css$/.test(f)).sort();
  return [rd('app.css'), ...starts.map(f => rd('css/' + f)), ...cssList(rd('sw.js')).map(f => rd('css/' + f))].join('\n');
};
// 2.20.0 (#646): the web client is static/js/*.js (the order of the script tags in index.html); this is all of it as one text
exports.clientSource = async () => {
  const html = await (await fetch(B)).text();
  // 2.149.0 (#2505): the served page adds ?v=<content hash>
  const mods = [...html.matchAll(/<script src="\/static\/js\/([\w-]+\.js)(?:\?v=\w+)?"(?: defer)?><\/script>/g)].map(m => m[1]);  // 2.191.0 B (#2505): defer
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
exports.lateErrs = 0;  // 2.655.0 (#5045): how many late app errors were ignored (a suite can count them: p2655_d_late_ui)
const lateAppError = e => !!e && closedRealms.some(T => e instanceof T) && /Cannot read propert(y|ies) of (undefined|null)/.test(e.message || '')
  && /\/static\/(js\/)?[\w.-]+\.js/.test(String(e.stack || '').split('\n').slice(0, 2).join('\n'))
  || !!e && closedRealms.length > 0 && /reading '_location'/.test(e.message || '');  // 2.442.0 (#3744): jsdom's own location getter on a closed window; its TypeError is of this realm (p2440_d_ui)
process.on('unhandledRejection', e => {
  if (lateAppError(e)) { exports.lateErrs++; console.log('late app rejection after a window was closed (ignored):', String(e.stack).split('\n').slice(0, 8).join(' | ')); return; }  // 2.655.0 (#5045): 8 stack lines, so the caller of $() shows
  console.error(e); process.exit(1);
});
// 2.504.0 (#4084): jsdom has no CSS object, the app uses it (office.js ost_find, core.js, ...: a ReferenceError when the path gets there).
// escape = CSSOM "serialize an identifier" (UTF-16 code units). supports: nothing in static/js asks; only two vendored files do, and
// each keeps the path it took without a CSS object: pdf.js (backdrop-filter) gets false, mermaid ("color", value) the same test
// on an Option's style as its own fallback. Everything else is false: jsdom cannot tell.
const cssEscape = value => {
  const s = String(value);
  if (s === '-') return '\\-';
  let out = '';
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i), hex = () => '\\' + c.toString(16) + ' ';
    if (c === 0) out += '�';
    else if (c <= 0x1f || c === 0x7f) out += hex();
    else if (c >= 0x30 && c <= 0x39 && (i === 0 || (i === 1 && s[0] === '-'))) out += hex();
    else if (c >= 0x80 || c === 0x2d || c === 0x5f || (c >= 0x30 && c <= 0x39) || (c >= 0x41 && c <= 0x5a) || (c >= 0x61 && c <= 0x7a)) out += s[i];
    else out += '\\' + s[i];
  }
  return out;
};
const cssObject = w => ({escape: cssEscape, supports: (prop, value) => {
  if (prop !== 'color' || value === undefined) return false;
  const st = new w.Option().style; st.color = value; return st.color === value;
}});
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
// 2.364.0 B (#3031): the app opens on Start by default (setting start_page); the suites written before open on the device's
// last task view (start_page 'last', the old way) -- pass startPage: null for the account's own (tests/p2364_b_nav_ui.js)
const rowIconsSet = async (hd, o = {}) => {
  const body = {...(o.rowIcons === null ? {} : {row_icons: o.rowIcons || 'all'}), ...(o.startPage === null ? {} : {start_page: o.startPage || 'last'})};
  if (!Object.keys(body).length) return;
  try { await fetch(B + 'api/settings', {method: 'PATCH', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido', ...hd}, body: JSON.stringify(body)}); } catch { /* best effort */ }
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
// 2.543.0 (#4606): under "All workspaces" with Private and one organisation the office shows the overview of the areas (office.js
// ofc_allOvr); the suites written before open the office the server chose there (that organisation's): officeWs saves that
// workspace for them, only in exactly this case ("All", one organisation). boot does it for a start in the office (hash office...)
// unless allWs: true (the suites of the overview); a suite that walks into the office later calls it itself.
// 2.577.0 (#4638): a tap in the overview opens #office/s/<space> (the workspace stays "All"); a suite can start there too.
exports.officeWs = async hd => {
  const H = {...hd, 'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
  const j = await (await fetch(B + 'api/state', {headers: H})).json().catch(() => ({}));
  const ws = j.me?.workspaces || [], cur = j.settings?.workspace || 'all';
  if (j.workspaces && ws.length === 1 && !/^(private|org:\d+)$/.test(cur)) await fetch(B + 'api/settings', {method: 'PATCH', headers: H, body: JSON.stringify({workspace: 'org:' + ws[0].id})});
};
// 2.609.0 (#4929, CI red p248_d_ui / p2299_d_ui: on a phone the document's sheet was missing in the CI only): every window
// notes its history steps (push / replace / back, popstate, hashchange), the dialogs added to / removed from the page and the
// failed requests with the time since the window began; navTrace(w) gives that log with the hash and the open dialogs, for
// the message of a failed check (cheap: at most NAV_MAX entries)
const NAV_MAX = 200;
function navNote(w, x) { const t = w.__nav; if (t && t.log.length < NAV_MAX) t.log.push(`${Math.round(performance.now() - t.t0)} ${x}`); }
function navWatch(w) {
  w.__nav = {t0: performance.now(), log: []};
  const h = w.history, ps = h.pushState.bind(h), rs = h.replaceState.bind(h), bk = h.back.bind(h);
  h.pushState = (st, t, u) => { navNote(w, `push ${JSON.stringify(st)} ${u ?? ''}`); return ps(st, t, u); };
  h.replaceState = (st, t, u) => { navNote(w, `replace ${JSON.stringify(st)} ${u ?? ''}`); return rs(st, t, u); };
  h.back = () => { navNote(w, 'back'); return bk(); };
  w.addEventListener('popstate', e => navNote(w, `popstate ${JSON.stringify(e.state)} ${w.location.hash}`), true);
  w.addEventListener('hashchange', () => navNote(w, `hashchange ${w.location.hash}`), true);
  w.addEventListener('DOMContentLoaded', () => new w.MutationObserver(ms => { for (const mu of ms) {
    for (const n of mu.addedNodes) if (n.classList?.contains('modal')) navNote(w, `dialog in ${n.className}`);
    for (const n of mu.removedNodes) if (n.classList?.contains('modal')) navNote(w, `dialog out ${n.className}`);
  } }).observe(w.document.body, {childList: true}));
}
exports.navTrace = w => { try { return JSON.stringify({hash: w.location.hash, state: w.history.state, dialogs: [...w.document.querySelectorAll('.modal')].map(m => m.className), log: w.__nav?.log || []}); } catch (e) { return 'navTrace: ' + e.message; } };
exports.boot = async function boot({user = 'alice', mobile = false, hash = '', ls = {}, wait = null, proxy = null, path = '', media = {}, setup = null, lazy = false, rowIcons, startPage, shared = null, allWs = false} = {}) {
  const cookie = proxy || user === null ? '' : await exports.login(user, undefined, {rowIcons, startPage});  // 2.1156.0 (#4550): user null = a visitor without a session
  if (proxy) await rowIconsSet({'Remote-User': proxy}, {rowIcons, startPage});  // 2.56.1 (#1799)
  if (!allWs && /^office(\/|$)/.test(hash)) await exports.officeWs(proxy ? {'Remote-User': proxy} : {Cookie: cookie});  // 2.543.0 (#4606)
  // 1.8.1: the start view is the Inbox; the suites written before start on Today as a device that was there last
  // (pass ls: {'tasks.lastKey': null} for a real first start, p181_ui.js)
  // 2.1052.0 (#5808): News are always bundled per task (the plain list and its device setting newsBundle are gone)
  // 2.1037.0 (#5807): the history of the News (what does not wait for me) is folded by default; the suites written before see
  // it open (that device setting), p21037_b_bell_ui passes ls: {'tasks.newsHist': null} for the folded default
  const store = Object.assign(shared ? shared.store : {}, {'tasks.newsHist': 'true', ...(hash || 'tasks.lastKey' in ls ? {} : {'tasks.lastKey': '"today"'}), ...ls});
  for (const k of Object.keys(store)) if (store[k] === null) delete store[k];
  const vc = new VirtualConsole(); vc.on('jsdomError', e => { if (lateAppError(e.detail)) { exports.lateErrs++; return; }  /* 2.577.0 (#3356): a MutationObserver callback queued before w.close() ends here, not in unhandledRejection (vm_try, p170_ui) */ if (!/navigation|Not implemented/.test(e.message)) { exports.errs.push(e.message); console.log('script error:', String((e.detail && e.detail.stack) || e.stack || '').split('\n').slice(0, 4).join(' | ')); } });
  const dom = await JSDOM.fromURL(B + path + (hash ? '#' + hash : ''), {runScripts: 'dangerously', resources: new PooledLoader(), pretendToBeVisual: true, virtualConsole: vc,
    beforeParse(w) {
      w.matchMedia = q => ({matches: q in media ? media[q] : /max-width/.test(q) ? mobile : false, addEventListener() {}, addListener() {}});  // media: {'(prefers-reduced-motion: reduce)': true}
      const told = k => { for (const o of shared ? shared.wins : []) if (o !== w) { const e = new o.Event('storage'); e.key = k; o.dispatchEvent(e); } };
      Object.defineProperty(w, 'localStorage', {value: {getItem: k => k in store ? store[k] : null, setItem: (k, v) => { store[k] = String(v); told(k); }, removeItem: k => { delete store[k]; told(k); }, key: i => Object.keys(store)[i], get length() { return Object.keys(store).length; }}});
      w.visualViewport = null;  // 2.456.0 (#3837): jsdom has none; a drag's scrollBox (dnd.js tdBox) asks for it
      w.CSS = cssObject(w);  // 2.504.0 (#4084)
      w.__offline = false;
      w.fetch = (u, o = {}) => { if (w.__offline) return Promise.reject(new TypeError('Failed to fetch')); const hd = {...(o.headers || {}), ...(proxy ? {'Remote-User': proxy} : {Cookie: cookie})}; const sg = o.signal && (ac => { if (o.signal.aborted) ac.abort(); else o.signal.addEventListener('abort', () => ac.abort()); return ac.signal; })(new AbortController());  // 2.116.0 (#2065): a jsdom signal -> Node's
        return fetch(new URL(String(u), B), {...o, headers: hd, ...(sg ? {signal: sg} : {})}); };
      { const f0 = w.fetch; w.__net = {n: 0, at: performance.now(), open: new Map()}; let k = 0;  // 2.192.0 B (#2513): for idle(w)
        w.fetch = (u, o) => { const id = ++k, done = () => { w.__net.n--; w.__net.at = performance.now(); w.__net.open.delete(id); };
          w.__net.n++; w.__net.at = performance.now(); w.__net.open.set(id, String(u)); const p = f0(u, o); p.then(done, done);
          p.then(r => { if (r.status >= 400) navNote(w, `${r.status} ${(o && o.method) || 'GET'} ${String(u).replace(B, '/')}`); }, e => navNote(w, `failed ${String(u).replace(B, '/')}: ${e && e.message}`)); return p; }; }
      navWatch(w);  // 2.609.0 (#4929): what the page did with its history and its dialogs (navTrace on a failed check)
      w.Request = Request; w.Response = Response; w.Headers = Headers; w.FormData = FormData; w.File = File; w.Blob = Blob;
      Object.defineProperty(w.navigator, 'serviceWorker', {configurable: true, value: {register: () => Promise.resolve(), addEventListener() {}, controller: null}});
      w.scrollTo = () => {}; w.Element.prototype.scrollIntoView = () => {};
      w.confirm = () => true; w.prompt = () => null;
      exports.dialogBridge(w);
      if (setup) setup(w);  // extra browser APIs for one suite (webpush_ui.js: Notification, PushManager, ...)
    }});
  // 2.312.0 A (#3284): without an own `wait` the first drawing is awaited (the loading screen #boot fades out in bootDone(), main.js),
  // not a fixed 2.5 s: too short on a slow runner. At most 20 s, so an error cannot hang a suite; a page without #boot is done at once.
  if (wait === null) {
    const bd = () => { const b = dom.window.document.getElementById('boot'); return !b || b.classList.contains('out'); };
    for (let i = 0; i < 400 && !bd(); i++) await new Promise(r => setTimeout(r, 50));
    await new Promise(r => setTimeout(r, 150));
  } else await new Promise(r => setTimeout(r, wait));
  // 2.98.0: a slow place may still be loading the start scripts after `wait` (appearance_ui saw calendar.js not yet run): up to 15 s more until all ran
  for (let i = 0; i < 150 && dom.window.document.readyState !== 'complete'; i++) await new Promise(r => setTimeout(r, 100));
  // 2.501.0 (#4296): a module that does not load stops the suite (it used to be a log line nobody sees); only a window started
  // without network on purpose (setup: __offline, p2140_ui, p2238_b) may fail here. No modules wanted: lazy: true
  if (!lazy && typeof dom.window.ld_all === 'function') await dom.window.ld_all().catch(e => { if (!dom.window.__offline) throw new Error('ld_all failed: ' + e.message); console.log('ld_all (offline start):', e.message); });
  dom.window.__cookie = cookie; dom.window.__store = store;
  if (shared) shared.wins.push(dom.window);
  const close = dom.window.close.bind(dom.window), realmTE = dom.window.TypeError;
  dom.window.close = () => { if (!closedRealms.includes(realmTE)) closedRealms.push(realmTE); close(); };
  return dom.window;
};
exports.sleep = ms => new Promise(r => setTimeout(r, ms));
// 2.192.0 B (#2513): wait for a state instead of a fixed sleep (like kt.until): call fn (may be async) until it returns
// something truthy (-> that value) or timeout ms are over (-> fn's last value). A generous timeout costs nothing when green.
// (performance.now: a test clock that shifts Date never stretches or ends the wait)
exports.until = async (fn, {timeout = 15000, step = 100} = {}) => {
  const end = performance.now() + timeout;
  for (;;) {
    const x = await fn();
    if (x || performance.now() >= end) return x;
    await new Promise(r => setTimeout(r, step));
  }
};
// untilEl(w, '.sel'[, ms]) -> the first element; untilEl(w, '.sel', 'text'[, ms]) -> the first whose text contains it (string or RegExp)
exports.untilEl = (w, sel, text = null, timeout = 15000) => { if (typeof text === 'number') [text, timeout] = [null, text];
  return exports.until(() => [...w.document.querySelectorAll(sel)]
  .find(e => text == null || (text instanceof RegExp ? text.test(e.textContent) : e.textContent.includes(text))) || null, {timeout}); };
// 2.551.0 (#4599): test anchors. New UI tests address buttons and menu items by a data-act anchor, not by their visible text (the text
// changes with wording and language). The name comes from the i18n key (= the English text): lower case, every run of characters that
// are not letters or digits becomes one '-', no '-' at the ends: actName('Add to favourites') = 'add-to-favourites'. Text stays part of a
// test only where the text itself is checked. untilAct(w, name[, ms]) waits for the first [data-act="name"] and returns it (null on timeout).
exports.actName = key => String(key).toLowerCase().replace(/[^\p{L}\p{N}]+/gu, '-').replace(/^-+|-+$/g, '');
exports.untilAct = (w, name, timeout = 15000) => exports.until(() => w.document.querySelector(`[data-act="${exports.actName(name)}"]`), {timeout});
// 2.504.0 (#4085): the app records a history step only after the server's answer (often after a reload too), so a suite that sees the
// change on the server and calls histStep at once finds no step yet and undoes nothing. n0 = HIST.undo.length before the action;
// true once the new step is there and no other step is running (histStep drops a call while one runs).
exports.histAdded = (w, n0, o) => exports.until(() => !w.eval('HIST.busy') && w.eval('HIST.undo.length') === n0 + 1, o);
// idle(w): the page's requests are done -- none in flight for `quiet` ms (w.__net, counted by boot()'s fetch). For an action
// that loads (openDetail, load().then(render), a dialog that fetches); not for debounced saves or timers of the page.
// At least `quiet` ms (a request the action starts from a short timer is still seen); at most timeout ms (then it goes on).
exports.idle = async (w, {quiet = 250, timeout = 15000} = {}) => {
  const t0 = performance.now();
  const ok = await exports.until(() => (!w.__net || w.__net.n === 0) && performance.now() - Math.max(t0, w.__net?.at || 0) >= quiet, {timeout, step: 25});
  if (!ok) console.log(`idle: still loading after ${timeout} ms:`, [...(w.__net?.open?.values() || [])].slice(0, 5).join(' '));
  return ok;
};
// 2.37.0: the same for suites with their own jsdom page() (signin_ui.js): a late rejection of a window they closed is the harness
exports.trackClose = w => {
  const close = w.close.bind(w), realmTE = w.TypeError;
  w.close = () => { if (!closedRealms.includes(realmTE)) closedRealms.push(realmTE); close(); };
};
// 2.312.0 A (#3283): the same for the jsdom suites: click the Undo button of the toast with the expected text (string or RegExp). A hidden toast
// keeps its old button in the DOM, so only the text check says it is the own toast. Returns true when it was clicked.
exports.undoToast = async (w, text, {timeout = 15000} = {}) => {
  const re = text instanceof RegExp ? text : new RegExp(String(text).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  const b = await exports.until(() => { const t = w.document.querySelector('#toast'); return t && !t.classList.contains('hidden') && re.test(t.textContent) && t.querySelector('button:not(.tx)'); }, {timeout});
  if (!b) return false;
  b.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
  return true;
};
