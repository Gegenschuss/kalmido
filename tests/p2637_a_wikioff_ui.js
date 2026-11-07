// 2.637.0 (#4745) UI tests (jsdom, own container via start.sh): "Offline available" per knowledge space (static/js/wikioff.js).
// kalmido-suite: fresh
// jsdom has no IndexedDB: the copy is a stand-in store like p2238_b_wikioffline_ui.js (window.__wkoStore) with the files' part
// (fget / fput / fdel / fkeys / fclear: the blobs kept as they are); navigator.storage, URL.createObjectURL and window.open are
// stand-ins too. Invented names only.
// - the switch in the space's menu: the size and the free space asked first; too little space = a hint, nothing loaded
// - loading with its progress in the bar (x of y files), Cancel pauses, Continue finishes; a reload goes on where it stopped
// - offline: the page lists the files of the copy, a file link opens the copy (blob address), a picture takes it as data: address
// - the sync: a file in the trash leaves the copy, a new one comes; no right any more (404) removes the space's copy
// - the browser cleared the copy: the mark goes honestly; switched off: the files go; logout / another sign-in empty the store
// freelancer-matrix: wiki (the pages are in the private workspace of a person without an organisation)
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2637A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, 'Content-Type': 'application/json', Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = (fn, ms = 20000) => require('./boot').until(fn, {timeout: ms, step: 100});
const clone = v => v === undefined ? v : JSON.parse(JSON.stringify(v));
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==', 'base64');
const PDF = Buffer.from('%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj 3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n');
async function attach(pid, name, data, mime) {
  const fd = new FormData(); fd.append('file', new Blob([data], {type: mime}), name);
  const j = await (await fetch(B + `api/wiki/pages/${pid}/files`, {method: 'POST', headers: {...H, Cookie: CK}, body: fd})).json();
  return j.files?.[0]?.id;
}
// one browser: the copy's store (texts cloned, files kept as they are) and localStorage, shared by its windows
function browser() {
  const db = new Map(), fs = new Map();
  const store = {get: async k => clone(db.get(k)), put: async v => { db.set(v.k, clone(v)); }, del: async k => { db.delete(k); },
    all: async () => [...db.values()].map(clone), pre: async x => [...db.values()].filter(r => r.k.startsWith(x)).map(clone),
    clear: async () => { db.clear(); }, close: async () => {},
    fget: async k => fs.get(k), fput: async v => { fs.set(v.k, v); }, fdel: async k => { fs.delete(k); }, fkeys: async () => [...fs.keys()], fclear: async () => { fs.clear(); }};
  return {db, fs, store, shared: {store: {}, wins: []}};
}
// a window: est = what navigator.storage.estimate answers; gate(url) = a promise a file's download waits for (null = at once)
// every window of the browser uses the same session (CKW): another sign-in would empty the copy (#2872, p2238_b)
let CKW;
function win(br, {est = {quota: 5e9, usage: 1e6}} = {}) {
  const ck = CKW;
  const setup = w => {
    w.__wkoStore = br.store;
    w.fetch = (u, o = {}) => {
      if (w.__offline) return Promise.reject(new TypeError('Failed to fetch'));
      const sg = o.signal && (ac => { if (o.signal.aborted) ac.abort(); else o.signal.addEventListener('abort', () => ac.abort()); return ac.signal; })(new AbortController());
      return fetch(new URL(String(u), B), {...o, headers: {...(o.headers || {}), Cookie: ck}, ...(sg ? {signal: sg} : {})});
    };
    w.__est = est; w.__persist = 0; w.__gate = null; w.__opened = []; w.__blobs = [];
    Object.defineProperty(w.navigator, 'storage', {configurable: true, value: {estimate: async () => w.__est, persist: async () => { w.__persist++; return true; }}});
    w.URL.createObjectURL = b => { w.__blobs.push(b); return 'blob:kalmido/' + w.__blobs.length; };
    w.URL.revokeObjectURL = () => {};
    w.open = () => { const x = {location: {href: ''}, opener: {}, closed: false, close() { x.closed = true; }}; w.__opened.push(x); return x; };
    const f0 = w.fetch;
    w.fetch = async (u, o) => { if (w.__gate && /\/api\/wiki\/files\//.test(String(u))) await w.__gate(String(u)); return f0(u, o); };
  };
  return boot({user: 'frida', hash: 'wiki', shared: br.shared, setup, ls: {'tasks.wkSpace': JSON.stringify('private')}});
}
const bar = w => w.document.querySelector('#view .wkofbar')?.textContent || '';
const meta = br => br.db.get('o:private');
async function menuPick(w) {
  const d = w.document, a = await until(() => d.querySelector('#view [data-wk="amenu"]'));
  if (!a) return false;
  a.click();
  const it = await until(() => d.querySelector('[data-act="offline-available"]'), 5000);
  if (!it) return false;
  const on = it.classList.contains('on');
  it.click();
  return on ? 'was-on' : 'was-off';
}

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: {...H, 'Content-Type': 'application/json'}, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  CK = await login('frida');
  const st0 = await call('GET', '/api/state');
  check(!(st0.me.workspaces || []).length, 'setup: frida has no organisation');
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'wiki'])].join(',');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: feats});
  const P1 = (await call('POST', '/api/wiki/pages', {space: 'private', path: 'Docs/Handbook', body: 'The handbook'})).id;
  const P2 = (await call('POST', '/api/wiki/pages', {space: 'private', path: 'Docs/Archive', body: 'Old things'})).id;
  const F1 = await attach(P1, 'plan.png', PNG, 'image/png');
  const F2 = await attach(P1, 'manual.pdf', PDF, 'application/pdf');
  const F3 = await attach(P2, 'old.pdf', Buffer.concat([PDF, Buffer.from('%old\n')]), 'application/pdf');
  CKW = await login('frida');
  const ME = (await (await fetch(B + 'api/state', {headers: {...H, Cookie: CKW}})).json()).me;
  check(P1 && P2 && F1 && F2 && F3, `setup: two pages with three files ${P1} ${P2} ${F1} ${F2} ${F3}`);

  // ================= too little space: a hint, nothing loaded
  const br = browser();
  let w = await win(br, {est: {quota: 1000, usage: 900}});
  let d = w.document;
  await until(() => w.eval(`(WK.idx.private?.pages || []).length > 0`));
  let asked = [];
  w.confirm = t => { asked.push(t); return true; };
  check(await menuPick(w) === 'was-off', 'the space menu has "Offline available", off');
  check(await until(() => asked.length), 'a dialog comes');
  check(/Not enough space/.test(asked[0] || '') && /only 100 B are free/.test(asked[0] || ''), 'too little space: the hint with the need and the free space ' + asked[0]);
  await sleep(300);
  check(!meta(br) && br.fs.size === 0 && !bar(w), 'too little space: nothing is loaded, no mark');

  // ================= on: the size first, then loading with progress; Cancel pauses
  w.__est = {quota: 5e9, usage: 1e6};
  asked = [];
  let release = null;
  w.__gate = () => new Promise(r => { release = r; });  // every file waits until the test lets it go
  await menuPick(w);
  check(await until(() => asked.length), 'the confirm dialog comes');
  check(/Keep this workspace offline/.test(asked[0] || '') && /3 files/.test(asked[0] || '') && /Free on this device/.test(asked[0] || ''), 'the dialog names the files, their size and the free space ' + asked[0]);
  check(await until(() => /Offline copy: 0 of 3 files/.test(bar(w))), 'the bar shows the progress (0 of 3 files) ' + bar(w));
  check(w.__persist === 1, 'navigator.storage.persist() is asked for');
  check(meta(br)?.on && meta(br)?.st === 'load' && meta(br)?.uid === ME.id && meta(br)?.g === (ME.sgen || ''), 'the state is in the copy with the sign-in mark');
  await until(() => release); release(); release = null;
  check(await until(() => br.fs.size === 1 && /Offline copy: 1 of 3 files/.test(bar(w))), 'one file in: 1 of 3 ' + bar(w));
  check([...br.fs.values()][0]?.blob && [...br.fs.values()][0]?.uid === ME.id, 'the file is kept as a blob with the account');
  await until(() => release);
  d.querySelector('#view .wkofbar [data-wkof="stop"]')?.click();
  release(); release = null;  // the download that waited ends cut off
  check(await until(() => /Offline copy paused: 1 of 3 files/.test(bar(w))), 'Cancel pauses the loading ' + bar(w));
  check(meta(br)?.st === 'pause' && br.fs.size === 1, 'paused: kept in the copy, nothing more loaded');

  // ================= Continue, a reload in between: it goes on where it stopped
  d.querySelector('#view .wkofbar [data-wkof="go"]')?.click();
  await until(() => release); release(); release = null;
  check(await until(() => br.fs.size === 2), 'Continue: the second file comes');
  w.close();
  w = await win(br);  // a reload: the third file without anybody asking
  d = w.document;
  check(await until(() => br.fs.size === 3 && meta(br)?.st === 'ok', 25000), 'after a reload the loading goes on and finishes ' + JSON.stringify({n: br.fs.size, st: meta(br)?.st}));
  check(await until(() => /Offline available: .* · as of/.test(bar(w))), 'the bar: offline with size and date ' + bar(w));
  asked = [];
  w.confirm = t => { asked.push(t); return false; };
  check(await menuPick(w) === 'was-on', 'the menu shows the switch on');
  check(await until(() => asked.length) && /Remove the offline files/.test(asked[0] || '') && /Frees /.test(asked[0] || ''), 'switching off asks first and names the space it frees ' + asked[0]);
  await sleep(200);
  check(meta(br)?.on && br.fs.size === 3, 'the switch-off dialog cancelled: stays on');

  // ================= offline: the page's files and links from the copy
  const offF = await w.eval(`wkoffPageFiles('private', ${P1}).then(x => x.map(f => f.id).sort((a, b) => a - b))`);
  check(JSON.stringify(offF) === JSON.stringify([F1, F2].sort((a, b) => a - b)), 'the page lists the two files of the copy ' + JSON.stringify(offF));
  w.__offline = true; w.eval('setOnline(false)');
  const pg = await w.eval(`wko_page(${P1})`);
  check(pg && (pg.files || []).length === 2, 'a page opened offline lists its files from the copy ' + (pg?.files || []).length);
  const a = d.createElement('a'); a.href = `/api/wiki/files/${F2}/manual.pdf`; a.target = '_blank'; a.textContent = 'manual'; d.querySelector('#view').appendChild(a);
  a.click();
  check(await until(() => w.__opened[0]?.location.href.startsWith('blob:')), 'offline a file link opens the copy (blob address) ' + w.__opened[0]?.location.href);
  check(w.__blobs[0]?.type === 'application/pdf', 'the blob carries the file type ' + w.__blobs[0]?.type);
  const img = d.createElement('img'); img.setAttribute('src', `/api/wiki/files/${F1}/plan.png`); d.querySelector('#view').appendChild(img);
  img.dispatchEvent(new w.Event('error'));
  check(await until(() => (img.getAttribute('src') || '').startsWith('data:image/png;base64,')), 'a picture that does not load takes the copy as data: address');
  a.remove(); img.remove();
  w.__offline = false; w.eval('setOnline(true)');

  // ================= the sync: the trash leaves, new comes
  check((await call('DELETE', `/api/wiki/files/${F2}`)).http < 300, 'setup: manual.pdf into the trash');
  const F4 = await attach(P2, 'new.png', Buffer.concat([PNG, Buffer.from([0])]), 'image/png');
  await w.eval(`wkoffSync('private', true)`);
  check(await until(() => br.fs.has('f:' + F4) && !br.fs.has('f:' + F2) && meta(br)?.st === 'ok'), 'the sync: the file in the trash leaves the copy, the new one comes ' + [...br.fs.keys()].join(','));
  check((await call('DELETE', `/api/wiki/pages/${P2}`)).http < 300, 'setup: the page Archive into the trash');
  await w.eval(`wkoffSync('private', true)`);
  check(await until(() => !br.fs.has('f:' + F3) && !br.fs.has('f:' + F4) && br.fs.has('f:' + F1)), 'the files of a page in the trash leave the copy');

  // ================= no right any more: 404 removes the space's copy
  br.db.set('o:org:999999', {k: 'o:org:999999', sp: 'org:999999', on: true, st: 'ok', list: [{id: 9999, v: 'x', size: 1, name: 'x.pdf', mime: 'application/pdf', page_id: 1}], have: {9999: 'x'}, uid: ME.id, g: ME.sgen || ''});
  br.fs.set('f:9999', {k: 'f:9999', blob: new Blob(['x']), uid: ME.id, g: ME.sgen || ''});
  await w.eval(`wkoffSync('org:999999', true)`);
  check(await until(() => !br.db.has('o:org:999999') && !br.fs.has('f:9999')), 'a space without access (404): its copy is removed');

  // ================= the browser cleared the copy: the mark goes honestly
  const saved = {o: br.db.get('o:private'), f: new Map(br.fs)};
  br.db.delete('o:private'); br.fs.clear();
  await w.eval(`(delete WKOF.m.private, wkof_meta('private'))`);
  check(await until(() => !w.eval(`LS.get('wkoff', null)`) && !w.eval('WKOF.m.private')), 'cleared by the browser: the space is not offline any more (the mark goes)');
  check(await until(() => /The browser removed the offline files/.test(d.querySelector('#toast')?.textContent || '')), 'and it says so once');
  br.db.set('o:private', saved.o); for (const [k, v] of saved.f) br.fs.set(k, v);
  w.close();

  // ================= switched off: the files go, the texts stay
  w = await win(br);
  d = w.document;
  await until(() => /Offline available/.test(bar(w)));
  w.confirm = () => true;
  check(await menuPick(w) === 'was-on', 'the switch is on');
  check(await until(() => br.fs.size === 0 && !br.db.has('o:private') && !bar(w)), 'switched off: the files and the mark are gone ' + br.fs.size);
  check(br.db.has('s:private'), 'switched off: the page texts stay offline');

  // ================= logout and another sign-in empty the files
  await menuPick(w);
  check(await until(() => meta(br)?.st === 'ok' && br.fs.size === 1), 'on again: loaded ' + br.fs.size);
  await w.eval('wko_reset()');
  check(br.fs.size === 0 && br.db.size === 0, 'another sign-in (wko_reset): texts and files gone');
  await w.eval(`(WKO.dead = false, WKOF.m = {}, wko_put({k: 'o:private', sp: 'private', on: true, st: 'ok', list: [], have: {}}))`);
  br.fs.set('f:1', {k: 'f:1', blob: new Blob(['x']), uid: ME.id, g: ME.sgen || ''});
  await w.eval('clearLocal()');
  check(await until(() => br.fs.size === 0 && br.db.size === 0), 'logout (clearLocal): texts and files gone');
  w.close();

  console.log(`\n${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
