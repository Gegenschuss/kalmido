// 2.663.0 UI test, part C (#4200): the offline start state in IndexedDB (static/js/offcache.js) and the open table's poll with
// its etag (static/js/sheets.js shvLoad). Firefox (real IndexedDB), fresh DB, invented names only.
// kalmido-suite: fresh
// alice has no organisation here (her private workspace, her own list and table)
// - online: the state is written to IndexedDB "kalmido-start" when idle (module offcache loaded on demand), as a structured
//   clone ({o}: no locked list), and no copy stays in localStorage
// - the old localStorage copy (a browser of before 2.663) with the network gone: a new start shows it, takes it over into
//   IndexedDB and removes it; a second start without network shows the same state from IndexedDB
// - IndexedDB refusing a write (quota): localStorage as before, logged (console.warn), never silent
// - sign-out (clearLocal): the record goes
// - an open table polled with nothing changed: {unchanged}, the same sheet object, nothing drawn again; a cell changed on the
//   server: the poll loads it and draws
// The network is cut for the app's requests (/api/) by a preload script (the page and its scripts still load).
const {B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2663_c_offcache_ui', check, shots: 'P2663C_SHOTS', lazy: true});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };

// the record in IndexedDB, read with an own open() of the database: 'o' (structured clone), 's' (JSON) or null (undefined
// after ff.js: a null comes back as undefined, hence == null)
const REC = `new Promise(res => { const r = indexedDB.open('kalmido-start'); r.onupgradeneeded = () => r.result.createObjectStore('s');
  r.onsuccess = () => { const d = r.result; const g = d.transaction('s').objectStore('s').get('state'); g.onsuccess = () => { const x = g.result; d.close();
    res(x ? {kind: x.o ? 'o' : 's', tasks: (x.o || JSON.parse(x.s)).tasks.map(t => t.title)} : null); }; g.onerror = () => { d.close(); res('err'); }; };
  r.onerror = () => res('err'); })`;
// in every new document before the app: the app's requests fail like a lost network while localStorage t2663off = 1
const OFF = `() => { try { if (localStorage.getItem('t2663off') !== '1') return; } catch { return; }
  const f0 = window.fetch; window.fetch = function (u, o) { if (/\\/api\\//.test(String(u && u.url || u))) return Promise.reject(new TypeError('NetworkError when attempting to fetch resource.')); return f0.apply(this, arguments); }; }`;

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'sheets,collab,comments'});
  const L = (await call('POST', '/api/lists', {name: 'Greenhouse'})).id;
  const T = (await call('POST', '/api/tasks', {title: 'Water the ferns', list_id: L})).id;
  check(L > 0 && T > 0, 'setup: a list with a task');
  const sh = await call('POST', '/api/sheets', {title: 'Plant log', space: 'private'});
  check(sh.status === 201, 'setup: a private table');
  const SID = sh.id;

  await firefox(async ({cmd, ev, nav, ctx, until, shot}) => {
    const pu = (expr, ms = 15000) => until(expr, {timeout: ms, step: 150});
    await cmd('script.addPreloadScript', {functionDeclaration: OFF});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return new Promise(r => { const q = indexedDB.deleteDatabase('kalmido-start'); q.onsuccess = q.onerror = q.onblocked = () => r(1); }); })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: sign-in');

    // ---- online: written to IndexedDB when idle, nothing in localStorage
    await nav(B + `#l/${L}`);
    check(await pu(`typeof S !== 'undefined' && S.booted && !!document.querySelector('#view .trow[data-id="${T}"]')`), 'online: the list shows the task');
    check(await pu(`typeof OC !== 'undefined' && OC.wrote > 0 && !OC.off`), 'online: the state was written to IndexedDB (module offcache loaded on demand, no fallback)');
    const r1 = await ev(REC);
    check(r1 && r1.kind === 'o' && r1.tasks.includes('Water the ferns'), 'online: the record is a structured clone with the task ' + JSON.stringify(r1));
    check(await ev(`localStorage.getItem('tasks.cache') === null`), 'online: no copy of the state in localStorage');

    // ---- a browser of before 2.663: only the old localStorage copy (a title only it has), then a start without network
    await ev(`(async () => { const c = JSON.parse(JSON.stringify(S.lpCache)); S.lpCache = null; await oc_drop(); c.tasks = c.tasks.map(t => t.id === ${T} ? {...t, title: 'From the old copy'} : t);
      localStorage.setItem('tasks.cache', JSON.stringify(c)); localStorage.setItem('t2663off', '1'); return 1; })()`);
    const r0 = await ev(REC);
    check(r0 == null, 'setup: no record in IndexedDB, only the old localStorage copy ' + JSON.stringify(r0) + ' ' + JSON.stringify(await ev(`({gen: OC.gen, t: OC.t, off: OC.off, wrote: OC.wrote})`)));
    await nav(B + `#l/${L}`); await cmd('browsingContext.reload', {context: ctx, wait: 'complete'});
    check(await pu(`typeof S !== 'undefined' && S.booted && OUT.online === false`), 'offline start: the app started and knows it is offline');
    check(await pu(`document.querySelector('#view .trow[data-id="${T}"]')?.textContent.includes('From the old copy')`), 'offline start: the old localStorage copy is shown');
    check(await pu(`localStorage.getItem('tasks.cache') === null`), 'offline start: the old copy is removed from localStorage once taken over');
    const r2 = await ev(REC);
    check(r2 && r2.tasks.includes('From the old copy'), 'offline start: the old copy is in IndexedDB now ' + JSON.stringify(r2));
    await shot('p2663c-offline-old.png');
    // a second start without network: from IndexedDB
    await cmd('browsingContext.reload', {context: ctx, wait: 'complete'});
    check(await pu(`typeof S !== 'undefined' && S.booted && OUT.online === false && document.querySelector('#view .trow[data-id="${T}"]')?.textContent.includes('From the old copy')`),
      'second offline start: the state comes from IndexedDB');

    // ---- online again: the server's state, written as a structured clone
    await ev(`(localStorage.removeItem('t2663off'), 1)`);
    await cmd('browsingContext.reload', {context: ctx, wait: 'complete'});
    check(await pu(`typeof S !== 'undefined' && S.booted && OUT.online && document.querySelector('#view .trow[data-id="${T}"]')?.textContent.includes('Water the ferns')`), 'online again: the server\'s title');
    check(await pu(`typeof OC !== 'undefined' && OC.wrote > 0`), 'online again: written');
    let r3 = null; await until(async () => { r3 = await ev(REC); return r3 && r3.tasks.includes('Water the ferns'); }, {timeout: 15000, step: 200});
    check(r3 && r3.kind === 'o' && !r3.tasks.includes('From the old copy'), 'online again: the record holds the server\'s state ' + JSON.stringify(r3));

    // ---- IndexedDB refuses (quota): localStorage as before, logged
    const fb = await ev(`(async () => {
      const put0 = IDBObjectStore.prototype.put, w0 = console.warn, said = [];
      IDBObjectStore.prototype.put = function () { throw new DOMException('quota (test)', 'QuotaExceededError'); };
      console.warn = (...a) => { said.push(a.join(' ')); };
      try { OC.t = 0; await oc_write(); } finally { IDBObjectStore.prototype.put = put0; console.warn = w0; }
      return {off: OC.off, ls: !!localStorage.getItem('tasks.cache'), said};
    })()`);
    check(fb.off === true && fb.ls === true, 'quota: the state goes to localStorage as before ' + JSON.stringify(fb));
    check(fb.said.some(s => /offline start state/.test(s) && /QuotaExceededError/.test(s)), 'quota: the reason is logged, not swallowed ' + JSON.stringify(fb.said));
    check(await ev(`oc_get().then(c => !!c && Array.isArray(c.tasks))`), 'quota: the next start reads the localStorage copy');

    // ---- sign-out: the record goes
    await ev(`(async () => { OC.off = false; OC.t = 0; await oc_write(); return 1; })()`);
    // a write planned before the sign-out (idle) must not bring the record back afterwards
    await ev(`(oc_soon(), 1)`);
    check(!!(await ev(REC)), 'setup: a record before the sign-out');
    await ev(`clearLocal().then(() => 1)`);
    await ev(`new Promise(r => (globalThis.requestIdleCallback || setTimeout)(() => setTimeout(() => r(1), 50), {timeout: 2000}))`);  // the idle callback planned above has run (a state of the page)
    const r4 = await ev(REC);
    check(r4 == null && (await ev(`S.lpCache === null`)), 'sign-out (clearLocal): the record is gone and stays gone (a planned write is void) ' + JSON.stringify(r4));

    // ---- the open table: polled unchanged = nothing drawn again; changed = loaded and drawn
    await nav(B + `#sheets/${SID}`);
    check(await pu(`typeof SHV !== 'undefined' && SHV.sh?.id === ${SID} && !!SHV.sh.etag && !!document.querySelector('#shv-scroll')`), 'the table is open with its etag');
    const u = await ev(`(async () => {
      const r0 = shvRender, sh0 = SHV.sh, n0 = SHV.n304 || 0; let drawn = 0;
      shvRender = function () { drawn++; return r0.apply(this, arguments); };
      try { await shvLoad(${SID}, true); await shvLoad(${SID}, true); } finally { shvRender = r0; }
      return {same: SHV.sh === sh0, n: (SHV.n304 || 0) - n0, drawn};
    })()`);
    check(u.same && u.n === 2 && u.drawn === 0, 'polled twice unchanged: {unchanged}, the same sheet, nothing drawn ' + JSON.stringify(u));
    const d = await call('GET', `/api/sheets/${SID}`);
    const row = d.rows.sort((a, b) => a.pos - b.pos)[0].id, col = d.columns.sort((a, b) => a.pos - b.pos)[0].id;
    check((await call('PUT', `/api/sheets/${SID}/cells`, {cells: [{row_id: row, col_id: col, raw: 'Repotted'}]})).status === 200, 'a cell changed on the server (another tab)');
    const c = await ev(`(async () => {
      const r0 = shvRender, sh0 = SHV.sh, n0 = SHV.n304 || 0; let drawn = 0;
      shvRender = function () { drawn++; return r0.apply(this, arguments); };
      try { await shvLoad(${SID}, true); } finally { shvRender = r0; }
      return {other: SHV.sh !== sh0, n: (SHV.n304 || 0) - n0, drawn, raw: SHV.sh.cells.map(x => x.raw)};
    })()`);
    check(c.other && c.n === 0 && c.drawn === 1 && c.raw.includes('Repotted'), 'polled after the change: the whole sheet loaded and drawn ' + JSON.stringify(c));
    check(await pu(`!!document.querySelector('#shv-scroll')?.textContent.includes('Repotted')`), 'the new value shows in the grid');
  });

  console.log(`p2663_c_offcache_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e.stack || e); console.log(`p2663_c_offcache_ui: ${ok} ok, ${F.length + 1} failed`); process.exit(1); });
