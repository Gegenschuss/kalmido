// 2.280.0 C (#3114) UI tests (jsdom, own container via start.sh): the knowledge pages' offline copy no longer loads at the start.
// - after the start (the today view drawn, then 10 s without any request) no /api/wiki?…bodies=1 was asked (before: 6 s after
//   the start every space with every text)
// - opening the knowledge pages asks for the space's texts (in pages: bn=), the copy holds them, offline the space reads from it
// - an earlier visit's copy stays and is read offline without the space being opened online first
// freelancer-matrix: wiki (the pages are in the private space of a person without an organisation)
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2280C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const clone = v => v === undefined ? v : JSON.parse(JSON.stringify(v));

// one browser: the copy's store (jsdom has no IndexedDB) and every request with the time it ended; ck = one session for
// all its windows (bundle 2.305: 2.238.0 B, #2872, drops the copy at another sign-in -- boot's own login is a new one)
function browser(ck = null) {
  const db = new Map(), urls = [], net = {open: 0, last: Date.now()};
  const store = {get: async k => clone(db.get(k)), put: async v => { db.set(v.k, clone(v)); }, del: async k => { db.delete(k); },
    all: async () => [...db.values()].map(clone), pre: async x => [...db.values()].filter(r => r.k.startsWith(x)).map(clone), clear: async () => { db.clear(); }, close: async () => {}};
  const setup = w => {
    w.__wkoStore = store;
    const of = !ck ? w.fetch : (u, o = {}) => {
      if (w.__offline) return Promise.reject(new TypeError('Failed to fetch'));
      const sg = o.signal && (ac => { if (o.signal.aborted) ac.abort(); else o.signal.addEventListener('abort', () => ac.abort()); return ac.signal; })(new AbortController());
      return fetch(new URL(String(u), B), {...o, headers: {...(o.headers || {}), Cookie: ck}, ...(sg ? {signal: sg} : {})});
    };
    w.fetch = (u, o = {}) => {
      if (!w.__offline) urls.push(String(u));
      if (/\/api\/version/.test(String(u))) return of(u, o);  // the version check comes every few seconds: not the start's work
      net.open++; net.last = Date.now();
      const done = () => { net.open--; net.last = Date.now(); };
      return of(u, o).then(r => { done(); return r; }, e => { done(); throw e; });
    };
  };
  return {db, urls, net, setup, shared: {store: {}, wins: []}};
}
// the network is quiet: no request started or ended for ms (a state, polled - not a fixed wait after the start); a request
// that stays open (the live connection) does not count
const quiet = async (net, ms, max = 60000) => { const t0 = Date.now(); while (Date.now() - t0 < max) { if (Date.now() - net.last >= ms) return true; await sleep(250); } return false; };
const bodiesAsked = urls => urls.filter(u => /\/api\/wiki\?/.test(u) && /bodies=1/.test(u));

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  CK = await login('frida');
  const st0 = await call('GET', '/api/state');
  check(!(st0.me.workspaces || []).length, 'setup: frida has no organisation');
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'wiki'])].join(',');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: feats});
  const P1 = (await call('POST', '/api/wiki/pages', {space: 'private', path: 'Docs/Start', body: 'Alpha start text'})).id;
  const P2 = (await call('POST', '/api/wiki/pages', {space: 'private', path: 'Docs/Other', body: 'Beta mango text'})).id;
  check(P1 && P2, 'setup: two pages');

  // ================= the start: no texts of the knowledge pages
  const br = browser(await login('frida'));  // the restart below is the same sign-in (2.238.0 B keeps the copy then)
  const opt = {user: 'frida', shared: br.shared, setup: br.setup, ls: {'tasks.wkSpace': JSON.stringify('private')}};
  let w = await boot(opt), d = w.document;
  check(await until(() => w.eval(`!!S.booted && S.route?.mod !== 'wiki'`) && d.querySelector('#view')?.children.length > 0, 60), 'start: the today view is drawn');
  check(await quiet(br.net, 10000), 'start: the network gets quiet ' + JSON.stringify(br.urls.slice(-8)));
  check(!bodiesAsked(br.urls).length, 'start: no request for the knowledge pages\' texts ' + JSON.stringify(bodiesAsked(br.urls)));
  check(!br.db.has('s:private'), 'start: no copy written');

  // ================= opening the knowledge pages: the texts come (in pages), the copy has them
  w.location.hash = '#wiki';
  const c0 = await until(() => { const r = br.db.get('s:private'); return r && r.pages?.length === 2 ? r : null; }, 60);
  const asked = bodiesAsked(br.urls);
  check(asked.length >= 1 && asked.every(u => /offline=1/.test(u) && /[?&]bn=\d+/.test(u)), 'open: the texts are asked for, in pages ' + JSON.stringify(asked));
  check(c0 && c0.pages.find(p => p.id === P1)?.body === 'Alpha start text' && c0.pages.find(p => p.id === P2)?.body === 'Beta mango text', 'open: the copy holds every text');
  check(await until(() => w.eval(`(WK.idx.private?.pages || []).length === 2 && !!document.querySelector('#view .wkwrap')`), 40), 'open: the knowledge view shows the space');

  // ================= offline: the space reads from the copy
  w.__offline = true;
  w.eval(`WK.idx = {}; WK.pg = null; 1`);
  await w.eval(`wk_load('private', true)`);
  w.eval(`renderView(); 1`);
  const hint = await until(() => d.querySelector('#view .wkoff'), 40);
  check(hint && /Offline · as of/.test(hint.textContent), 'offline: the view says "Offline · as of …" ' + (hint?.textContent || ''));
  w.location.hash = '#wiki/' + P2;
  check(await until(() => /Beta mango text/.test(d.querySelector('#view #wk-md')?.textContent || ''), 40), 'offline: the page opens with its text');
  w.close();

  // ================= the next start (same browser): still no texts; offline the copy of the earlier visit is read
  br.urls.length = 0;
  w = await boot({...opt, ls: {...opt.ls, 'tasks.lastKey': '"today"'}}); d = w.document;
  check(await until(() => w.eval(`!!S.booted`), 60), 'restart: booted');
  check(await quiet(br.net, 10000), 'restart: the network gets quiet ' + JSON.stringify(br.urls.slice(-8)));
  check(!bodiesAsked(br.urls).length, 'restart: no request for the texts ' + JSON.stringify(bodiesAsked(br.urls)));
  check(br.db.get('s:private')?.pages?.length === 2, 'restart: the earlier copy stays');
  await w.eval(`loadModule('wiki')`);  // jsdom has no service worker that keeps the module's files offline
  w.__offline = true;
  await w.eval(`wk_load('private', true)`);
  check(w.eval(`!!WK.idx.private?.off && WK.idx.private.pages.length === 2`), 'restart offline: the space comes from the earlier copy');
  check(await w.eval(`wko_page(${P1}).then(p => p?.body)`) === 'Alpha start text', 'restart offline: a page of the earlier copy has its text');
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
