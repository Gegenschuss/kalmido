// 2.143.0 UI tests, part C (jsdom), fresh DB. jsdom has no IndexedDB: the outbox's small store is handed in as a stand-in
// (window.__obxStore, the same five calls as the IndexedDB one in core.js) and kept per "browser" in this file.
// - #2153 a queue of the earlier version in localStorage is taken over once into the store (nothing lost), then sent, and
//   localStorage holds no queue any more
// - #2153 offline: a manual time entry waits in the store (not in localStorage), Background Sync is asked for; the answer
//   gets lost on the way back -> sent again = one entry
// - #2153 notes offline: a change of an open note waits (a newer text replaces the waiting one), a new note made offline
//   shows at once and is changed again offline; online = one new note with the last text, the changed note has its text
// - #2153 two windows of one browser share the queue over the channel: both know the waiting change
// - #2153 the install hint: shown once, "Not now" closes it and it does not come back; "Don't show again" is kept; never in
//   the installed app; on an iPhone the steps instead of the button
// - #2154 the share sheet offers "Add to contacts" / "Add to calendar" for shared .vcf / .ics files
// - 2.143.0 C2 review: the service worker sends only the app's own write routes again (no API v1, no GET, no other
//   origin) and stops at anything else; a shared file above the upload limit or beyond 20 files is kept out and named;
//   logging out awaits the cleared store; two shared calendar files ask one after another (never two dialogs at once)
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, ms = 8000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (await fn()) return true; await sleep(100); } return false; };

// one browser: the store (ops by key, meta), a channel between its windows, Web Locks, the sync registrations
function browser() {
  const db = {ops: new Map(), meta: new Map()}, writes = [], syncs = [], chans = [], held = new Set();
  const clone = v => v === undefined ? v : JSON.parse(JSON.stringify(v));
  const store = {
    all: async () => [...db.ops.values()].map(clone),
    write: async (put, del) => { writes.push({put: put.map(r => r.k), del: [...del]}); for (const r of put) db.ops.set(r.k, clone(r)); for (const k of del) db.ops.delete(k); },
    meta: async k => clone(db.meta.get(k)),
    setMeta: async (k, v) => { if (v === undefined) db.meta.delete(k); else db.meta.set(k, clone(v)); },
    clear: async () => { db.ops.clear(); db.meta.clear(); },
  };
  const locks = {async request(name, opt, fn) {
    if (typeof opt === 'function') { fn = opt; opt = {}; }
    if (held.has(name)) { if (opt.ifAvailable) return fn(null); while (held.has(name)) await sleep(20); }
    held.add(name);
    try { return await fn({name}); } finally { held.delete(name); }
  }};
  const setup = w => {
    w.__obxStore = store;
    Object.defineProperty(w.navigator, 'locks', {configurable: true, value: locks});
    Object.defineProperty(w.navigator, 'serviceWorker', {configurable: true, value: {register: () => Promise.resolve(), addEventListener() {}, controller: null,
      ready: Promise.resolve({sync: {register: async t => { syncs.push(t); }}})}});
    w.BroadcastChannel = class { constructor(n) { this.n = n; this.w = w; chans.push(this); } postMessage(d) { for (const c of chans) if (c !== this && c.n === this.n && c.onmessage) setTimeout(() => { if (c.w.document) c.onmessage({data: clone(d)}); }, 0); } close() {} };  // a closed window hears nothing
  };
  return {db, writes, syncs, store, setup, shared: {store: {}, wins: []}};
}
const spy = w => { const calls = []; const of = w.fetch; w.fetch = (u, o = {}) => { if (!w.__offline) calls.push([(o.method || 'GET').toUpperCase(), new URL(String(u), B).pathname]); return of(u, o); }; return calls; };

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'time,contacts,events,collab'});
  const me = (await call('GET', '/api/state')).me.id;
  const P = (await call('POST', '/api/lists', {name: 'Flyers'})).id;
  const T0 = (await call('POST', '/api/tasks', {title: 'Draft the flyer', list_id: P})).id;
  await call('PATCH', `/api/lists/${P}`, {time_tracking: true});

  // ================= the queue of the earlier version is taken over
  const br = browser();
  const old = [{method: 'PATCH', url: `/api/tasks/${T0}`, body: {title: 'Renamed before the update'}, uid: me, k: 'oldk1'}];
  const w1 = await boot({user: 'alice', hash: 'l/' + P, shared: br.shared, setup: br.setup, ls: {'tasks.outbox': JSON.stringify(old)}});
  check(w1.eval('OBX.on') === true, 'the store is used (no localStorage queue)');
  check(br.writes.some(x => x.put.includes('oldk1')), 'the old entry went into the store first');
  check(await until(async () => (await call('GET', '/api/tasks/' + T0)).title === 'Renamed before the update'), 'and was sent: nothing lost');
  check(await until(() => !('tasks.outbox' in br.shared.store) && br.db.ops.size === 0), `localStorage holds no queue, the store is empty (${br.db.ops.size})`);

  // ================= a time entry offline, the answer lost once
  const c1 = spy(w1);
  w1.__offline = true;
  await w1.eval(`api('POST', '/api/time/entries', {list_id: ${P}, start: new Date(Date.now() - 5400e3).toISOString(), end: new Date(Date.now() - 1800e3).toISOString(), note: 'Offline hour', client_id: 'p2143-ui-te'})`);
  check(w1.eval('OUT.q.length') === 1 && w1.eval("OUT.q[0].url") === '/api/time/entries', 'the time entry waits in the queue');
  check(await until(() => br.db.ops.size === 1), 'it is kept in the store');
  check(!('tasks.outbox' in br.shared.store), '… not in localStorage');
  check(await until(() => br.syncs.includes('kalmido-outbox')), 'Background Sync is asked for');
  check(/offline|change/i.test(w1.document.querySelector('#top .offline, .offline')?.textContent || ''), 'the top bar says a change waits');
  let lose = 1;
  const of = w1.fetch;
  w1.fetch = (u, o = {}) => {
    if (lose && (o.method || '') === 'POST' && new URL(String(u), B).pathname === '/api/time/entries') { lose--; return of(u, o).then(() => { throw new TypeError('Failed to fetch'); }); }
    return of(u, o);
  };
  w1.__offline = false;
  w1.dispatchEvent(new w1.Event('online'));
  check(await until(() => w1.eval('OUT.q.length') === 0 && br.db.ops.size === 0, 12000), 'sent (again)');
  const te = (await call('GET', '/api/time/entries')).entries || [];
  check(te.filter(e => e.note === 'Offline hour').length === 1, `one time entry, not two (${te.filter(e => e.note === 'Offline hour').length})`);
  check(c1.filter(([m, p]) => m === 'POST' && p === '/api/time/entries').length === 2, 'it really went twice');
  w1.fetch = of;

  // ================= notes offline
  const N1 = await call('POST', `/api/lists/${P}/notes`, {title: 'Briefing', body: 'Start'});
  await w1.eval('load()');
  w1.location.hash = '#note/' + N1.id;
  check(await until(() => w1.eval(`!!(S.nt.notes || []).find(n => n.id === ${N1.id})`)), 'the note is open');
  w1.__offline = true;
  let r = await w1.eval(`(() => { const n = S.nt.notes.find(x => x.id === ${N1.id}); return ntWrite(n, {body: 'First offline text', expect_updated_at: n.updated_at}); })()`);
  check(r && r.queued, 'offline: the change waits');
  r = await w1.eval(`(() => { const n = S.nt.notes.find(x => x.id === ${N1.id}); return ntWrite(n, {body: 'Second offline text', expect_updated_at: n.updated_at}); })()`);
  check(w1.eval('OUT.q.length') === 1 && w1.eval('OUT.q[0].body.body') === 'Second offline text', 'the newer text replaces the waiting one');
  check(w1.eval(`S.nt.notes.find(x => x.id === ${N1.id}).body`) === 'Second offline text', 'drawn at once');
  await w1.eval('noteNew()');
  await sleep(200);
  const tmp = w1.eval('S.nt.id');
  check(tmp < 0 && w1.eval(`!!S.nt.notes.find(x => x.id === ${tmp})`) && w1.location.hash === '#note/' + tmp, `the new note shows at once (${tmp}, ${w1.location.hash})`);
  await w1.eval(`ntWrite(S.nt.notes.find(x => x.id === ${tmp}), {title: 'Written offline', body: 'On the train'})`);
  check(w1.eval('OUT.q.length') === 3, `three changes wait (${w1.eval('OUT.q.length')})`);
  check(await until(() => br.db.ops.size === 3), 'all three in the store');
  w1.__offline = false;
  w1.dispatchEvent(new w1.Event('online'));
  check(await until(() => w1.eval('OUT.q.length') === 0, 12000), 'the notes went out');
  const ns = (await call('GET', `/api/lists/${P}/notes`)).notes || [];
  check(ns.find(n => n.id === N1.id)?.body === 'Second offline text', 'the changed note has the last text');
  check(ns.filter(n => n.title === 'Written offline').length === 1 && ns.find(n => n.title === 'Written offline')?.body === 'On the train', 'one new note with its text');
  check(w1.eval('S.nt.id') > 0 && w1.location.hash === '#note/' + w1.eval('S.nt.id'), `the open note has its real id (${w1.location.hash})`);

  // ================= two windows share the queue
  const w2 = await boot({user: 'alice', hash: 'l/' + P, shared: br.shared, setup: br.setup});
  w1.__offline = w2.__offline = true;
  await w2.eval(`api('PATCH', '/api/tasks/${T0}', {title: 'From window two'})`);
  check(await until(() => w1.eval('OUT.q.length') === 1), 'the other window knows the waiting change');
  w1.__offline = w2.__offline = false;
  w1.dispatchEvent(new w1.Event('online')); w2.dispatchEvent(new w2.Event('online'));
  check(await until(() => w1.eval('OUT.q.length') === 0 && w2.eval('OUT.q.length') === 0 && br.db.ops.size === 0), 'both queues empty');
  check((await call('GET', '/api/tasks/' + T0)).title === 'From window two', 'the change arrived');
  w2.close();

  // ================= the install hint
  const fake = w => { const e = new w.Event('beforeinstallprompt', {cancelable: true}); e.prompt = () => { w.__prompted = (w.__prompted || 0) + 1; }; e.userChoice = Promise.resolve({outcome: 'dismissed'}); return e; };
  w1.dispatchEvent(fake(w1));
  check(w1.eval('!!PWA.ev'), 'the browser\'s install question is kept');
  w1.eval('pwa_hint()');
  const hint = w1.document.querySelector('#pwahint');
  check(!!hint && !!hint.querySelector('[data-pwa="install"]') && !!hint.querySelector('[data-pwa="never"]'), 'the hint shows with Install and Don\'t show again');
  hint.querySelector('[data-pwa="install"]').click();
  await sleep(50);
  check(w1.__prompted === 1 && !w1.document.querySelector('#pwahint'), 'Install opens the browser\'s question, the hint goes');
  w1.eval('pwa_hint()');
  check(!w1.document.querySelector('#pwahint'), 'once per start');
  w1.eval('PWA.shown = false'); w1.dispatchEvent(fake(w1)); w1.eval('pwa_hint()');
  check(!!w1.document.querySelector('#pwahint'), 'the next start shows it again (the question was dismissed)');
  w1.document.querySelector('#pwahint [data-pwa="later"]')?.click();
  check(!!JSON.parse(br.shared.store['tasks.pwaHint'] || '{}').later, '"Not now" is remembered');
  w1.eval('PWA.shown = false'); w1.dispatchEvent(fake(w1)); w1.eval('pwa_hint()');
  check(!w1.document.querySelector('#pwahint'), 'and the hint does not come back soon');
  delete br.shared.store['tasks.pwaHint'];
  w1.eval('PWA.shown = false'); w1.dispatchEvent(fake(w1)); w1.eval('pwa_hint()');
  w1.document.querySelector('#pwahint [data-pwa="never"]')?.click();
  check(JSON.parse(br.shared.store['tasks.pwaHint'] || '{}').never === true, '"Don\'t show again" is kept');
  w1.eval('clearLocal()');
  check(JSON.parse(br.shared.store['tasks.pwaHint'] || '{}').never === true, '… also through a logout (a device preference)');
  delete br.shared.store['tasks.pwaHint'];
  // an iPhone: no install question, the steps instead
  Object.defineProperty(w1.navigator, 'userAgent', {configurable: true, value: 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1'});
  w1.eval('PWA.shown = false; PWA.ev = null; pwa_hint()');
  const ih = w1.document.querySelector('#pwahint');
  check(!!ih && !ih.querySelector('[data-pwa="install"]') && /Add to Home Screen/.test(ih.textContent), 'iPhone: the steps, no button');
  ih?.querySelector('.iconbtn[data-pwa="later"]')?.click();
  check(!w1.document.querySelector('#pwahint'), 'the x closes it');
  w1.close();
  // the installed app: never
  const br3 = browser();
  const w3 = await boot({user: 'alice', hash: 'l/' + P, shared: br3.shared, setup: br3.setup, media: {'(display-mode: standalone)': true}});
  w3.dispatchEvent(fake(w3)); w3.eval('PWA.shown = false; pwa_hint()');
  check(!w3.eval('PWA.ev') && !w3.document.querySelector('#pwahint'), 'never in the installed app');

  // ================= #2154 the share sheet's targets
  await w3.eval("loadModule('agentchat')");
  w3.eval("window.__sd = shareDest([], false, false, {contacts: true, calendar: true})");
  await sleep(100);
  const md = w3.document.querySelector('.shdest');
  check(!!md?.querySelector('[data-sd="contacts"]') && !!md?.querySelector('[data-sd="calendar"]') && !!md?.querySelector('[data-sd="task"]'), 'share: task, contacts and calendar are offered');
  md?.querySelector('[data-sd="contacts"]')?.click();
  check(await w3.eval('window.__sd') === 'contacts', 'the choice comes back');
  w3.eval("window.__sd = shareDest([], false, false, {contacts: false, calendar: false})");
  await sleep(100);
  check(!w3.document.querySelector('.shdest [data-sd="contacts"]'), 'without a card: no contacts button');
  w3.document.querySelector('.shdest [data-sd="task"]')?.click();
  w3.close();

  // ================= 2.143.0 C2 (#2153): logging out empties the store before the page goes
  const br4 = browser();
  const w4 = await boot({user: 'alice', hash: 'l/' + P, shared: br4.shared, setup: br4.setup});
  br4.db.ops.set('left', {k: 'left', n: 1, method: 'PATCH', url: `/api/tasks/${T0}`, body: {title: 'x'}, uid: me});
  const cl = w4.eval('clearLocal()');
  check(cl && typeof cl.then === 'function', 'clearLocal gives a Promise');
  await cl;
  check(br4.db.ops.size === 0, `after it the store is empty (${br4.db.ops.size})`);
  w4.close();

  // ================= 2.143.0 C2 (#2153, #2154): the service worker in a sandbox
  const vm = require('vm');
  const SW = await (await fetch(B + 'sw.js')).text();
  const swCache = new Map(), swFetch = [];
  class R { constructor(b, o = {}) { this.b = b; this.headers = new Map(Object.entries(o.headers || {})); this.ok = o.status ? o.status < 400 : true; }
    static redirect(u, st) { return {redirect: u, status: st}; } async json() { return JSON.parse(this.b); } }
  const idb = {ops: new Map(), meta: new Map([['uid', {k: 'uid', v: me}]])};
  const req = fn => { const r = {}; setTimeout(() => { try { r.result = fn(); r.onsuccess && r.onsuccess(); } catch (e) { r.error = e; r.onerror && r.onerror(); } }, 0); return r; };
  const fakeDb = {objectStoreNames: {contains: () => true}, transaction: () => ({objectStore: n => ({
    get: k => req(() => idb[n].get(k)), getAll: () => req(() => [...idb[n].values()]), put: v => req(() => idb[n].set(v.k, v)), delete: k => req(() => idb[n].delete(k))})})};
  const swCtx = vm.createContext({
    self: {addEventListener() {}, location: {origin: 'https://kalmido.example'}, clients: {matchAll: async () => []}, navigator: {}},
    caches: {open: async () => ({keys: async () => [...swCache.keys()], delete: async k => swCache.delete(k), put: async (k, v) => { swCache.set(k, v); }}),
      match: async k => k === '/manifest.json' ? new R(JSON.stringify({kalmido_max_file_mb: 1})) : undefined},
    indexedDB: {open: () => req(() => fakeDb)},
    fetch: async (u, o = {}) => { swFetch.push([(o.method || 'GET'), u]); const r = new R(JSON.stringify(u === '/api/me' ? {id: me} : {ok: true}));
      r.headers = {get: () => 'application/json'}; return r; },
    Response: R, URL, setTimeout, console, atob, Uint8Array, JSON,
  });
  vm.runInContext(SW, swCtx);
  const okUrl = u => vm.runInContext(`SW_OBX_URL.test(${JSON.stringify(u)})`, swCtx);
  check(okUrl('/api/tasks/-12') && okUrl('/api/lists/3/notes') && okUrl('/api/tasks/4?force=1'), 'service worker: the app\'s routes are sent');
  check(!okUrl('/api/v1/tasks') && !okUrl('https://evil.example/api/tasks') && !okUrl('//evil.example/api/tasks') && !okUrl('/share') && !okUrl('/api/../x'),
    'service worker: API v1, other origins and other paths are not');
  idb.ops.set('a', {k: 'a', n: 1, method: 'PATCH', url: '/api/tasks/5', body: {title: 'one'}, uid: me});
  idb.ops.set('b', {k: 'b', n: 2, method: 'POST', url: '/api/v1/tasks', body: {title: 'two'}, uid: me});
  idb.ops.set('c', {k: 'c', n: 3, method: 'PATCH', url: '/api/tasks/6', body: {title: 'three'}, uid: me});
  await vm.runInContext('swOutboxSend()', swCtx);
  const sent = swFetch.filter(([, u]) => u !== '/api/me').map(([m, u]) => m + ' ' + u);
  check(sent.join() === 'PATCH /api/tasks/5', `service worker: sent up to the foreign entry, then stopped ${JSON.stringify(sent)}`);
  check(!idb.ops.has('a') && idb.ops.has('b') && idb.ops.has('c'), 'the foreign entry stays for the app, nothing after it went');
  idb.ops.clear(); swFetch.length = 0;
  idb.ops.set('g', {k: 'g', n: 1, method: 'GET', url: '/api/tasks/5', uid: me});
  await vm.runInContext('swOutboxSend()', swCtx);
  check(!swFetch.some(([m, u]) => u !== '/api/me'), 'a GET entry is not sent');
  // the share target: limit 1 MB (from the manifest), at most 20 files
  const fd = new FormData();
  fd.append('title', 'Holiday');
  fd.append('files', new Blob([new Uint8Array(1048577)], {type: 'video/mp4'}), 'big.mp4');
  for (let i = 0; i < 21; i++) fd.append('files', new Blob(['BEGIN:VCALENDAR'], {type: 'text/calendar'}), `e${i}.ics`);
  const red = await vm.runInContext('handleShare', swCtx)({headers: {get: () => 'none'}, referrer: '', formData: async () => fd});
  const meta = JSON.parse(swCache.get('/share-inbox/meta').b);
  check(red.redirect === '/?share=1', `share: the app opens (${red.redirect})`);
  check(meta.files.length === 20 && meta.files[0].name === 'e0.ics' && swCache.has('/share-inbox/19') && !swCache.has('/share-inbox/20'), `share: 20 files kept (${meta.files.length})`);
  check(meta.refused.map(f => f.name).join() === 'big.mp4,e20.ics' && meta.max_mb === 1 && meta.max_files === 20, `share: the too large one and the 21st are named ${JSON.stringify(meta.refused)}`);

  // ================= 2.143.0 C2 (#2154): two shared calendar files = one question after the other, the refused one is named
  await call('POST', '/api/evcals', {name: 'Shared here'});
  const ics = n => `BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:p2143c2-${n}@example.com\r\nDTSTART:20261101T090000Z\r\nDTEND:20261101T100000Z\r\nSUMMARY:Shared ${n}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n`;
  const shareSetup = w => {
    const m = {title: '', text: '', url: '', files: [{name: 'a.ics', type: 'text/calendar', size: 9}, {name: 'b.ics', type: 'text/calendar', size: 9}], refused: [{name: 'clip.mov', size: 9e9}], max_mb: 50, max_files: 20};
    const items = {'/share-inbox/meta': {json: async () => m}, '/share-inbox/0': {blob: async () => new w.Blob([ics('a')], {type: 'text/calendar'})},
      '/share-inbox/1': {blob: async () => new w.Blob([ics('b')], {type: 'text/calendar'})}};
    w.caches = {open: async () => ({match: async k => items[k]}), delete: async () => true, keys: async () => []};
    w.__dialogs = 'manual';  // boot.js would answer the questions itself
  };
  const w5 = await boot({user: 'alice', path: '?share=1', setup: shareSetup});
  check(await until(() => /clip\.mov/.test(w5.document.querySelector('#toast')?.textContent || '')), 'share: the refused file is named');
  check(await until(() => !!w5.document.querySelector('.shdest [data-sd="calendar"]')), 'share: "Add to calendar" is offered');
  w5.document.querySelector('.shdest [data-sd="calendar"]')?.click();
  const dlgUp = await until(() => w5.document.querySelectorAll('.itc-dlg').length === 1);
  check(dlgUp, 'the first calendar file asks ' + (dlgUp ? '' : JSON.stringify({modals: [...w5.document.querySelectorAll('.modal')].map(m => m.className + ':' + m.textContent.slice(0, 80)),
    toast: w5.document.querySelector('#toast')?.textContent, cals: w5.eval('(S.evcals || []).map(c => [c.id, c.org_id, c.role])'), hash: w5.location.hash})));
  await sleep(300);
  check(w5.document.querySelectorAll('.itc-dlg').length === 1, `only one question at a time (${w5.document.querySelectorAll('.itc-dlg').length})`);
  const d1 = w5.document.querySelector('.itc-dlg');
  d1?.querySelector('form')?.requestSubmit();
  check(await until(() => w5.document.querySelectorAll('.itc-dlg').length === 1 && w5.document.querySelector('.itc-dlg') !== d1), 'then the second one asks');
  w5.document.querySelector('.itc-dlg form')?.requestSubmit();
  check(await until(() => !w5.document.querySelector('.itc-dlg')), 'and no question is left');
  check(await until(async () => ((await call('GET', '/api/events?from=2026-10-25&to=2026-11-05')).items || []).filter(e => /^Shared [ab]$/.test(e.title)).length === 2),
    'both events arrived');
  w5.close();

  check(!errs.length, 'no script errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e.stack); process.exit(1); });
