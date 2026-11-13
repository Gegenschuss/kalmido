// 2.1120.0 UI test (#6036): an IndexedDB connection the browser closes under the page (a reload on Android: "The database
// connection is closing", InvalidStateError on transaction()) no longer ends up on window.onerror; the next access opens the
// database again and nothing is lost. Firefox (real IndexedDB), fresh DB, invented names only.
// kalmido-suite: fresh
// alice has no organisation here (her private workspace): no new route, the held connections of the page are client-side only
// - the four held connections (core.js idbHeld): offline start state (offcache.js, kalmido-start), outbox (core.js,
//   kalmido-outbox), offline files of a quick add (attachments.js, kalmido-qfiles), wiki copy (wiki.js, kalmido-wiki): the
//   connection is closed right before the next transaction() -> the access works on a fresh connection, no error event, the
//   offline start state does not fall back to localStorage
// - sign-out in another tab deletes a database (versionchange): the held connection lets go (deleteDatabase is not blocked) and
//   the next access opens it again
// - a real reload while writes are on their way: no IndexedDB error on window.onerror / unhandledrejection (kept in sessionStorage)
const {B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p6036_a_idbheal_ui', check, shots: 'P6036A_SHOTS', lazy: true});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };

// in every new document before the app: errors and rejections of the page into sessionStorage t6036e (they outlive a reload)
const CATCH = `() => { const keep = m => { try { const a = JSON.parse(sessionStorage.getItem('t6036e') || '[]'); a.push(String(m).slice(0, 300)); sessionStorage.setItem('t6036e', JSON.stringify(a)); } catch { /* none */ } };
  window.addEventListener('error', e => keep('error: ' + (e.message || '')));
  window.addEventListener('unhandledrejection', e => keep('rejection: ' + (e.reason && (e.reason.name + ' ' + e.reason.message) || e.reason))); }`;
// the next transaction() on the database `name` finds its connection closed - what the browser does under the page on a reload
const CLOSE_NEXT = `globalThis.t6036close = name => { const t0 = IDBDatabase.prototype.transaction; let hit = 0;
  IDBDatabase.prototype.transaction = function () { if (!hit && this.name === name) { hit = 1; IDBDatabase.prototype.transaction = t0; this.close(); } return t0.apply(this, arguments); };
  return () => { IDBDatabase.prototype.transaction = t0; return hit; }; }; 1`;
const ERRS = `JSON.parse(sessionStorage.getItem('t6036e') || '[]').filter(m => /IndexedDB|IDB|database|connection|InvalidState|offline start state/i.test(m))`;

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const L = (await call('POST', '/api/lists', {name: 'Seed shelf'})).id;
  const T = (await call('POST', '/api/tasks', {title: 'Sort the tomato seeds', list_id: L})).id;
  check(L > 0 && T > 0, 'setup: a list with a task');

  await firefox(async ({cmd, ev, nav, ctx, until, shot}) => {
    const pu = (expr, ms = 15000) => until(expr, {timeout: ms, step: 150});
    await cmd('script.addPreloadScript', {functionDeclaration: CATCH});
    await nav(B + 'static/icon.svg');
    await ev(`(async () => { localStorage.clear(); sessionStorage.clear(); for (const n of ['kalmido-start', 'kalmido-outbox', 'kalmido-qfiles', 'kalmido-wiki'])
      await new Promise(r => { const q = indexedDB.deleteDatabase(n); q.onsuccess = q.onerror = q.onblocked = () => r(1); }); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: sign-in');
    await nav(B + `#l/${L}`);
    check(await pu(`typeof S !== 'undefined' && S.booted && !!document.querySelector('#view .trow[data-id="${T}"]')`), 'the list shows the task');
    check(await pu(`typeof OC !== 'undefined' && OC.wrote > 0 && !OC.off`), 'the offline start state is in IndexedDB');
    await ev(CLOSE_NEXT);

    // ---- offline start state: the connection closed under it, the next write goes to a fresh one
    const oc = await ev(`(async () => { const undo = t6036close('kalmido-start'), w0 = OC.wrote; S.lpCache.tasks.find(t => t.id === ${T}).title = 'Sort the bean seeds';
      OC.t = 0; await oc_write(); const hit = undo(); const c = await oc_get(); return {hit, off: OC.off, wrote: OC.wrote - w0, ls: localStorage.getItem('tasks.cache') !== null, title: c?.tasks.find(t => t.id === ${T})?.title}; })()`);
    check(oc.hit === 1, 'offline start state: the connection was closed before the write ' + JSON.stringify(oc));
    check(!oc.off && oc.wrote === 1 && !oc.ls, 'offline start state: written to IndexedDB on a fresh connection, no fallback to localStorage ' + JSON.stringify(oc));
    check(oc.title === 'Sort the bean seeds', 'offline start state: the new state is read back ' + JSON.stringify(oc));

    // ---- outbox: the same for its store
    const ob = await ev(`(async () => { await outOpen(); if (!OBX.on) return {on: false}; const undo = t6036close('kalmido-outbox');
      try { await OBX.st.setMeta('t6036', 'kept'); return {on: true, hit: undo(), v: await OBX.st.meta('t6036')}; } catch (e) { undo(); return {on: true, err: e.name + ' ' + e.message}; } })()`);
    check(ob.on && ob.hit === 1 && ob.v === 'kept', 'outbox: a write after the connection was closed lands, read back ' + JSON.stringify(ob));
    await ev(`OBX.st.setMeta('t6036', undefined).then(() => 1)`);

    // ---- offline files of a quick add
    const qf = await ev(`(async () => { const st = qfStore(); await st.all(); const undo = t6036close('kalmido-qfiles');
      try { await st.put({tmp: -6036, uid: S.me.id, title: 'Seed photo', files: []}); return {hit: undo(), n: (await st.all()).filter(r => r.tmp === -6036).length}; }
      catch (e) { undo(); return {err: e.name + ' ' + e.message}; } })()`);
    check(qf.hit === 1 && qf.n === 1, 'quick add files: a write after the connection was closed lands ' + JSON.stringify(qf));
    // sign-out in another tab deletes the database: the held connection lets go, the next access opens it again
    const del = await ev(`new Promise(r => { const q = indexedDB.deleteDatabase('kalmido-qfiles'); q.onsuccess = () => r('deleted'); q.onblocked = () => r('blocked'); q.onerror = () => r('error'); })`);
    check(del === 'deleted', 'quick add files: deleting the database (sign-out in another tab) is not blocked by the held connection: ' + del);
    check(await ev(`qfStore().all().then(a => a.length === 0, e => 'err ' + e.name)`) === true, 'quick add files: opened again after the delete, empty');

    // ---- the wiki's offline copy
    await ev(`loadModule('wiki').then(() => 1)`);
    const wk = await ev(`(async () => { const st = wko_st(); await st.all(); const undo = t6036close('kalmido-wiki');
      try { await st.put({k: 't6036', v: 'kept'}); return {hit: undo(), v: (await st.get('t6036'))?.v}; } catch (e) { undo(); return {err: e.name + ' ' + e.message}; } })()`);
    check(wk.hit === 1 && wk.v === 'kept', 'wiki copy: a write after the connection was closed lands ' + JSON.stringify(wk));
    await ev(`wko_st().del('t6036').then(() => 1)`);

    check(JSON.stringify(await ev(ERRS)) === '[]', 'no IndexedDB error on window.onerror / unhandledrejection so far ' + JSON.stringify(await ev(ERRS)));

    // ---- a real reload while writes are on their way
    await ev(`(OC.t = 0, oc_write(), OBX.st.setMeta('t6036r', Date.now()), qfStore().all(), 1)`);
    await cmd('browsingContext.reload', {context: ctx, wait: 'complete'});
    check(await pu(`typeof S !== 'undefined' && S.booted && !!document.querySelector('#view .trow[data-id="${T}"]')`), 'after the reload: the app is up with the task');
    check(await pu(`typeof OC !== 'undefined' && OC.wrote > 0 && !OC.off`), 'after the reload: the offline start state is written again');
    await ev(`(OC.t = 0, oc_write(), OBX.st.setMeta('t6036r', undefined), 1)`);
    await cmd('browsingContext.reload', {context: ctx, wait: 'complete'});
    check(await pu(`typeof S !== 'undefined' && S.booted && typeof OC !== 'undefined' && OC.wrote > 0`), 'after a second reload: the app is up again');
    const e = await ev(ERRS);
    check(Array.isArray(e) && e.length === 0, 'reloads: no IndexedDB error on window.onerror / unhandledrejection ' + JSON.stringify(e));
    check(await pu(`!!document.querySelector('#view .trow[data-id="${T}"]')?.textContent.includes('Sort the tomato seeds')`), 'after the reloads: the task shows the server\'s title');
    await shot('p6036a-after-reload.png');
  });

  console.log(`p6036_a_idbheal_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e.stack || e); console.log(`p6036_a_idbheal_ui: ${ok} ok, ${F.length + 1} failed`); process.exit(1); });
