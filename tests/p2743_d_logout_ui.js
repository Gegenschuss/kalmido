// 2.743.0 D (#4284) UI tests (jsdom), fresh DB: logout() itself, the user boundary of a shared device
// kalmido-suite: fresh
// - nothing waits: no question, the session ends on the server, the app's cached files (Cache Storage) and the account's
//   local keys are gone, the device's own look stays
// - a change waits: asked first with the number; "Cancel" keeps the session, the cache and the change
// - without network, "Sign out": the cache and the local data are gone at once; the session that the server could not be told
//   about is ended by the next load before anything else (#4284 fix: before it the account opened again once online)
const {boot, B, login, until} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const alive = async ck => (await fetch(B + 'api/state', {headers: {...H, Cookie: ck}})).status === 200;

// Cache Storage of one browser (jsdom has none): two caches of the app
function cacheStore() {
  const m = new Map([['kalmido-a', 1], ['kalmido-b', 1]]);
  return {m, api: {keys: async () => [...m.keys()], delete: async k => m.delete(k), open: async () => ({match: async () => undefined, put: async () => {}, keys: async () => []}), match: async () => undefined}};
}
const start = async (hash, asked, answer) => {
  const cs = cacheStore();
  const w = await boot({user: 'alice', hash, setup: x => { x.caches = cs.api; }});
  w.confirm = t => { asked.push(t); return answer(); };
  return {w, cs};
};

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const P = (await call('POST', '/api/lists', {name: 'Shared device'})).id;
  const T = (await call('POST', '/api/tasks', {title: 'Water the plants', list_id: P})).id;

  // ================= nothing waits
  {
    const asked = [];
    const {w, cs} = await start('l/' + P, asked, () => true);
    w.localStorage.setItem('tasks.theme', 'dark');
    check(await alive(w.__cookie), 'the session lives before');
    check(w.eval('OUT.q.length') === 0, 'nothing waits');
    await w.eval('logout()');
    check(!asked.length, 'nothing waits: no question ' + JSON.stringify(asked));
    check(cs.m.size === 0, `the app's cached files are gone (${[...cs.m.keys()]})`);
    check(!(await alive(w.__cookie)), 'the session is ended on the server');
    // the device's own keys (LS_KEEP) stay; jsdom does not leave the page, so its view writes lastKey / viewMem back afterwards
    const keep = new Set([...w.eval('[...LS_KEEP]'), 'tasks.lastKey', 'tasks.viewMem']);
    const left = Object.keys(w.__store).filter(k => k.startsWith('tasks.') && !keep.has(k));
    check(!('tasks.uid' in w.__store), 'the account mark of the device is gone');
    check(!left.length, 'the account\'s local keys are gone ' + JSON.stringify(left));
    check(w.__store['tasks.theme'] === 'dark', 'the device\'s own look stays');
    check(!('kalmido.logoutPending' in w.__store), 'online: no sign-out left to do');
    w.close();
  }

  // ================= a change waits: "Cancel", then without network "Sign out"
  {
    const asked = []; let answer = false;
    const {w, cs} = await start('l/' + P, asked, () => answer);
    w.__offline = true;
    await w.eval(`api('PATCH', '/api/tasks/${T}', {title: 'Renamed offline'})`).catch(() => {});
    check(await until(() => w.eval('OUT.q.length') === 1), 'the change waits in the queue');
    await w.eval('logout()');
    check(asked.length === 1 && /1 change is not synced yet/.test(asked[0]), 'asked first, with the number ' + JSON.stringify(asked));
    check(cs.m.size === 2 && w.eval('OUT.q.length') === 1 && w.eval('!!S.me'), '"Cancel": cache, change and account stay');
    check(await alive(w.__cookie), '"Cancel": the session lives on');
    check(!('kalmido.logoutPending' in w.__store), '"Cancel": no sign-out noted');

    answer = true;
    await w.eval('logout()');
    check(asked.length === 2, 'asked again without network ' + JSON.stringify(asked));
    check(cs.m.size === 0, 'without network: the cache is gone all the same');
    check(!('tasks.outbox' in w.__store) && !('tasks.uid' in w.__store), 'without network: the queue and the account mark are gone ' + JSON.stringify(Object.keys(w.__store).filter(k => k.startsWith('tasks.'))));
    check(w.__store['kalmido.logoutPending'] === '1', 'the sign-out the server did not hear is noted');
    check(await alive(w.__cookie), '(the server could not be told yet)');
    // online again: the next load ends the session before it asks for the state
    w.__offline = false;
    await w.eval('load()').catch(() => {});
    check(await until(async () => !(await alive(w.__cookie))), 'online again: the old session is ended first (rollback test of the fix)');
    check(await until(() => !('kalmido.logoutPending' in w.__store)), 'the note is gone after it');
    check(await until(() => w.document.querySelector('.authscreen #auth-form')), 'the sign-in screen shows, not the account');
    check((await call('GET', '/api/tasks/' + T)).title === 'Water the plants', 'the waiting change was not sent after the sign-out');
    w.close();
  }

  console.log(`p2743_d_logout_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
