// 2.312.0 A (#3285) UI test, own container (start.sh): render() while a late start script (listcolor.js) is still loading.
// A slow connection delivers listcolor.js after render.js ran; a render() in that gap (a fast answer) used to throw
// "lp_sync is not defined". The page here gets listcolor.js 2.5 s late; the test asks for a render() in the gap, expects no
// error, then expects the app to start and draw the list normally.
// freelancer-matrix: client start (no route touched; the person has no organisation)
const path = require('path');
const {execFileSync} = require('child_process');
const {JSDOM, VirtualConsole} = require('jsdom');
const {sleep, B, login, PooledLoader, until} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});

// a loader that holds one script back (the others come at once)
class SlowLoader extends PooledLoader {
  fetch(url, opts = {}) {
    const p = super.fetch(url, opts);
    if (!/\/static\/js\/listcolor\.js/.test(String(url))) return p;
    const q = new Promise(r => setTimeout(r, 2500)).then(() => p).then(b => { q.response = p.response; return b; });
    q.abort = () => p.abort && p.abort(); q.href = p.href; q.getHeader = () => undefined;
    return q;
  }
}

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CK = await login('alice');
  const call = async (method, url, body) => { const x = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return x.json().catch(() => ({})); };
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const L = (await call('POST', '/api/lists', {name: 'Slow list'})).id;
  await call('POST', '/api/tasks', {title: 'Drawn despite the slow start', list_id: L});

  const errs = [];
  const vc = new VirtualConsole(); vc.on('jsdomError', e => { if (!/navigation|Not implemented/.test(e.message)) errs.push(e.message); });
  const dom = await JSDOM.fromURL(B + '#l/' + L, {runScripts: 'dangerously', resources: new SlowLoader(), pretendToBeVisual: true, virtualConsole: vc,
    beforeParse(w) {
      w.matchMedia = () => ({matches: false, addEventListener() {}, addListener() {}});
      w.fetch = (u, o = {}) => fetch(new URL(String(u), B), {...o, headers: {...(o.headers || {}), Cookie: CK}});
      Object.defineProperty(w.navigator, 'serviceWorker', {configurable: true, value: {register: () => Promise.resolve(), addEventListener() {}, controller: null}});
      w.scrollTo = () => {}; w.Element.prototype.scrollIntoView = () => {};
    }});
  const w = dom.window, d = w.document;
  // the gap: render.js has run, listcolor.js has not
  const gap = await until(() => typeof w.render === 'function' && typeof w.lp_sync !== 'function', {timeout: 20000, step: 20});
  check(gap, 'set-up: render.js ran while listcolor.js is still missing');
  let thrown = null;
  try { w.render(); w.render(); } catch (e) { thrown = e; }
  check(!thrown, 'render() in the gap throws nothing: ' + (thrown && thrown.message));
  // the app goes on: the late script arrives, the start draws the list
  check(await until(() => typeof w.lp_sync === 'function', {timeout: 20000}), 'the late script arrives');
  check(await until(() => /Drawn despite the slow start/.test(d.querySelector('#view')?.textContent || ''), {timeout: 30000}), 'the list is drawn after the slow start');
  check(!errs.length, 'no script errors: ' + errs.slice(0, 2).join(' | '));
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
