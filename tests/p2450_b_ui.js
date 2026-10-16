// 2.45.0 part B (#1515, jsdom): the setup page asks for the one-time setup code from the server log (field + hint
// "docker compose logs kalmido"); without / with a wrong code the server's message shows, the right one leads to step 2.
// With KALMIDO_SETUP_CODE=off (start.sh's default) the field is not there. A server without a key shows the red
// warning under Administration > Server. Starts its own container (start.sh with KALMIDO_SETUP_CODE= empty).
const {execFileSync} = require('child_process');
const path = require('path');
const {JSDOM, VirtualConsole} = require('jsdom');
const {boot, errs: bootErrs, sleep} = require('./boot');
const B = process.env.BASE || `http://127.0.0.1:${process.env.KALMIDO_TEST_PROXY_PORT || 3041}/`;
const CT = process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test';
const F = []; let ok = 0; const errs = [];
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const fresh = code => execFileSync('bash', [path.join(__dirname, 'start.sh')], {stdio: 'ignore', env: {...process.env, KALMIDO_SETUP_CODE: code}});
const logCode = () => { const m = execFileSync('docker', ['logs', CT], {encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe']}).match(/Setup code: *([a-z0-9-]+)/); return m ? m[1] : ''; };

async function open(jar) {  // the setup page with a cookie jar of its own (as setup_ui.js)
  const vc = new VirtualConsole(); vc.on('jsdomError', e => { if (!/navigation|Not implemented/.test(e.message)) errs.push(e.message); });
  const dom = await JSDOM.fromURL(B, {runScripts: 'dangerously', resources: new (require('./boot').PooledLoader)(), pretendToBeVisual: true, virtualConsole: vc,
    beforeParse(w) {
      const store = {};
      w.matchMedia = q => ({matches: false, addEventListener() {}, addListener() {}});
      Object.defineProperty(w, 'localStorage', {value: {getItem: k => k in store ? store[k] : null, setItem: (k, v) => { store[k] = String(v); }, removeItem: k => { delete store[k]; }, key: i => Object.keys(store)[i], get length() { return Object.keys(store).length; }}});
      w.fetch = async (u, o = {}) => {
        const r = await fetch(new URL(String(u), B), {...o, headers: {...(o.headers || {}), ...(jar.c ? {Cookie: jar.c} : {})}});
        const sc = r.headers.get('set-cookie'); if (sc) jar.c = sc.split(';')[0];
        return r;
      };
      w.Request = Request; w.Response = Response; w.Headers = Headers; w.FormData = FormData;
      Object.defineProperty(w.navigator, 'serviceWorker', {value: {register: () => Promise.resolve(), addEventListener() {}, controller: null}});
      w.scrollTo = () => {}; w.Element.prototype.scrollIntoView = () => {};
      w.confirm = () => true; w.prompt = () => null;
      require('./boot').dialogBridge(w);
    }});
  await sleep(1500);
  return dom.window;
}
async function submit(w, code) {
  const d = w.document;
  if (code !== undefined) d.querySelector('#au-code').value = code;
  d.querySelector('#au-user').value = 'alice'; d.querySelector('#au-name').value = 'Alice'; d.querySelector('#au-pw').value = 'password123';
  d.querySelector('#auth-form').dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true}));
  for (let i = 0; i < 30 && !d.querySelector('.setupcard') && !d.querySelector('#au-err').textContent; i++) await sleep(100);
}

(async () => {
  // ---- 1: the code field
  fresh('');
  const code = logCode();
  check(!!code, 'the server log shows a setup code');
  let jar = {}, w = await open(jar), d = w.document;
  const inp = d.querySelector('.authscreen #au-code');
  check(!!inp && inp.required && inp.getAttribute('autocomplete') === 'one-time-code', 'setup page: a required code field');
  check(d.querySelector('.authscreen label[for="au-code"]')?.textContent === 'Setup code', 'the field has a label');
  const hint = d.querySelector('#au-code-h');
  check(hint && /docker compose logs kalmido/.test(hint.textContent) && inp.getAttribute('aria-describedby') === 'au-code-h', 'hint where the code is (log command), linked to the field');
  check(d.activeElement === inp, 'the code field has the focus first');
  await submit(w, 'wrong-code-00');
  check(/setup code/i.test(d.querySelector('#au-err').textContent) && /log/.test(d.querySelector('#au-err').textContent) && !d.querySelector('.setupcard'), 'wrong code: the server message, no account');
  d.querySelector('#au-err').textContent = '';
  await submit(w, code.toUpperCase());
  check(!!d.querySelector('.setupcard'), 'the right code: step 2 of the setup appears');
  w.close();

  // ---- 2: the admin sees the warning about the missing server key (start.sh sets none)
  w = await boot({user: 'alice'}); d = w.document;
  await w.eval(`settingsModal('users')`); await sleep(800);  // 2.53.0 (#1410): settings.js loads on demand (own jsdom page, no boot())
  const warn = d.querySelector('.smodal [data-admp="server"] .shkey');
  check(warn && warn.getAttribute('role') === 'alert' && /server key is missing/.test(warn.textContent) && /KALMIDO_SECRET_KEY/.test(warn.textContent), 'Administration > Server: red warning without a server key');
  w.close();

  // ---- 3: KALMIDO_SETUP_CODE=off: no field (the other suites)
  fresh('off');
  jar = {}; w = await open(jar); d = w.document;
  check(d.querySelector('.authscreen #auth-form') && !d.querySelector('#au-code'), 'KALMIDO_SETUP_CODE=off: no code field');
  w.close();

  const all = errs.concat(bootErrs);
  check(!all.length, 'no script errors: ' + all.slice(0, 3).join(' | '));
  console.log(`p2450_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
