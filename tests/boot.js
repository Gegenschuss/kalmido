// jsdom boot with the built-in login (cookie) against the test container (proxy port, see start.sh).
const {JSDOM, VirtualConsole} = require('jsdom');
const B = process.env.BASE || `http://127.0.0.1:${process.env.KALMIDO_TEST_PROXY_PORT || 3041}/`;
exports.B = B; exports.errs = [];
// 2.0.5 / 2.0.6: app code that is still running when a suite closes its window (an awaited fetch returning after
// w.close(), e.g. loadJobs() -> renderView() in p200_ui.js on CI: "Cannot read properties of undefined (reading
// 'querySelector')" at $() because the closed window has no document) rejects; that is the harness, not the app.
// Only exactly that is ignored: a TypeError created in the realm of a window this suite closed, about a missing
// object, thrown in the app's own scripts. Anything else (open windows, the suite's own code) still fails the run.
const closedRealms = [];
const lateAppError = e => !!e && closedRealms.some(T => e instanceof T) && /Cannot read propert(y|ies) of (undefined|null)/.test(e.message || '')
  && /\/static\/[\w.-]+\.js/.test(String(e.stack || '').split('\n').slice(0, 2).join('\n'));
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
exports.login = async (user, pw = 'password123') => {
  const r = await fetch(B + 'api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: user, password: pw})});
  if (!r.ok) throw new Error('login ' + user + ' ' + r.status);
  return r.headers.get('set-cookie').split(';')[0];
};
exports.boot = async function boot({user = 'alice', mobile = false, hash = '', ls = {}, wait = 2500, proxy = null, path = '', media = {}, setup = null} = {}) {
  const cookie = proxy ? '' : await exports.login(user);
  // 1.8.1: the start view is the Inbox; the suites written before start on Today as a device that was there last
  // (pass ls: {'tasks.lastKey': null} for a real first start, p181_ui.js)
  // 2.17.0 (#452): News are bundled per task by default; the suites written before test the plain list (that device
  // setting), p2170_ui passes ls: {'tasks.newsBundle': null} for the bundled default
  const store = {'tasks.newsBundle': 'false', ...(hash || 'tasks.lastKey' in ls ? {} : {'tasks.lastKey': '"today"'}), ...ls};
  for (const k of Object.keys(store)) if (store[k] === null) delete store[k];
  const vc = new VirtualConsole(); vc.on('jsdomError', e => { if (!/navigation|Not implemented/.test(e.message)) exports.errs.push(e.message); });
  const dom = await JSDOM.fromURL(B + path + (hash ? '#' + hash : ''), {runScripts: 'dangerously', resources: 'usable', pretendToBeVisual: true, virtualConsole: vc,
    beforeParse(w) {
      w.matchMedia = q => ({matches: q in media ? media[q] : /max-width/.test(q) ? mobile : false, addEventListener() {}, addListener() {}});  // media: {'(prefers-reduced-motion: reduce)': true}
      Object.defineProperty(w, 'localStorage', {value: {getItem: k => k in store ? store[k] : null, setItem: (k, v) => { store[k] = String(v); }, removeItem: k => { delete store[k]; }, key: i => Object.keys(store)[i], get length() { return Object.keys(store).length; }}});
      w.__offline = false;
      w.fetch = (u, o = {}) => { if (w.__offline) return Promise.reject(new TypeError('Failed to fetch')); const hd = {...(o.headers || {}), ...(proxy ? {'Remote-User': proxy} : {Cookie: cookie})}; return fetch(new URL(String(u), B), {...o, headers: hd}); };
      w.Request = Request; w.Response = Response; w.Headers = Headers; w.FormData = FormData; w.File = File; w.Blob = Blob;
      Object.defineProperty(w.navigator, 'serviceWorker', {configurable: true, value: {register: () => Promise.resolve(), addEventListener() {}, controller: null}});
      w.scrollTo = () => {}; w.Element.prototype.scrollIntoView = () => {};
      w.confirm = () => true; w.prompt = () => null;
      exports.dialogBridge(w);
      if (setup) setup(w);  // extra browser APIs for one suite (webpush_ui.js: Notification, PushManager, ...)
    }});
  await new Promise(r => setTimeout(r, wait));
  dom.window.__cookie = cookie; dom.window.__store = store;
  const close = dom.window.close.bind(dom.window), realmTE = dom.window.TypeError;
  dom.window.close = () => { if (!closedRealms.includes(realmTE)) closedRealms.push(realmTE); close(); };
  return dom.window;
};
exports.sleep = ms => new Promise(r => setTimeout(r, ms));
