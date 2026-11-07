// 2.638.0 (#5013) UI test (jsdom), fresh DB: Undo after a list tile was dragged out of the favourites bar puts the list back
// in its place even when the DELETE of the star is slow (the CI): the star requests go out one after the other (favSet's queue)
// and the place is set only after the answer of the star (fv2_set). The page's fetch holds the DELETE until the Undo ran;
// a PUT already sent (without the queue) reaches the server first, then the DELETE takes the list out again (the old red).
// kalmido-suite: fresh
const {boot, errs, B, login, until, idle, undoToast} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const state = async () => (await call('GET', '/api/state')).settings || {};
const items = async () => JSON.parse((await state()).fav_items || '[]');

// the DELETE of a star waits for __fq.go(); then every PUT of a star already sent is answered first, then the DELETE goes out
const HOOK = `(() => {
  const f = window.fetch, q = window.__fq = {puts: [], dels: 0, sent: 0};
  let go; const gate = new Promise(r => { go = r; }); q.go = () => go();
  window.fetch = (u, o = {}) => {
    const m = String(o.method || 'GET').toUpperCase();
    if (!/\\/api\\/lists\\/\\d+\\/favorite$/.test(String(u))) return f(u, o);
    if (m === 'PUT') { const p = f(u, o); q.puts.push(p.catch(() => {})); return p; }
    if (m === 'DELETE') { q.dels++; return gate.then(() => Promise.all(q.puts)).then(() => { q.sent++; return f(u, o); }); }
    return f(u, o);
  };
  return 1; })()`;

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const L = (await call('POST', '/api/lists', {name: 'Garden'})).id, key = `l:${L}`;
  await call('PUT', `/api/lists/${L}/favorite`, {on: true});
  check((await call('PATCH', '/api/settings', {fav_items: ['v:today', key, 'v:tomorrow']})).status === 200, 'setup: three favourites');
  check((await items()).join() === `v:today,${key},v:tomorrow`, 'setup: stored ' + (await items()));

  const w = await boot({user: 'alice', hash: 'today'}), d = w.document;
  const tile = k => d.querySelector(`#kbar .fv2bar [data-fv2="${k}"]`);
  const order = () => [...d.querySelectorAll('#kbar .fv2bar [data-fv2]')].map(t => t.dataset.fv2).join();
  check(await until(() => tile('v:today') && tile(key) && tile('v:tomorrow')), 'the bar shows the three tiles');
  await idle(w);
  w.eval(HOOK);

  w.eval(`fv2_dragOut(${JSON.stringify(key)})`);  // what letting go outside the bar calls (the gesture: p2551_c_favout_ui)
  check(await until(() => !tile(key)), 'dragged out: the list tile is gone');
  check(await until(() => w.__fq.dels === 1), 'the DELETE of the star is on its way (held)');
  check(await undoToast(w, /Removed from favourites/), 'the hint has Undo');
  check(await until(() => String(w.eval('S.settings.fav_lists')).split(',').includes(String(L))), 'Undo: a favourite again at once');
  await idle(w);  // what the Undo sends without waiting for the DELETE is answered now
  w.__fq.go();
  check(await until(() => w.__fq.sent === 1), 'the held DELETE went out');
  check(await until(async () => { const s = await state(); return String(s.fav_lists || '').split(',').includes(String(L)) && JSON.parse(s.fav_items || '[]').join() === `v:today,${key},v:tomorrow`; }),
    'Undo: on the server the list is a favourite again, back in its place ' + (await items()) + ' / ' + (await state()).fav_lists);
  check(await until(() => order() === `v:today,${key},v:tomorrow`), 'Undo: the bar shows the list in its place ' + order());
  await idle(w);
  check(order() === `v:today,${key},v:tomorrow` && w.__fq.puts.length === 1, 'still in its place once all answers are in ' + order());

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  w.close();
  console.log(`p2638_a_favqueue_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
