// 2.572.0 (#4749) UI tests (jsdom), fresh DB: equal symbols in the favourites row are told apart on their own
// - the same symbol twice or more: the target's own colour when it is unique (project tag colour), else a badge with the first letter
//   (the first two when the letters collide); a look the person set (fav_meta) wins; a single symbol stays as it is
// - the badge is aria-hidden, the name stays the aria-label; the page "Favourites" (the name is there) has no badge
// kalmido-suite: fresh
const {boot, errs, B, login, until} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const L = (await call('POST', '/api/lists', {name: 'Garden'})).id;
  for (const [i, g] of ['alpha', 'beta', 'gamma', 'apple'].entries()) await call('POST', '/api/tasks', {title: 'T' + i, list_id: L, tags: [g]});
  const keys = ['tag:alpha', 'tag:beta', 'tag:gamma', 'v:today'];
  check((await call('PATCH', '/api/settings', {fav_items: keys})).status === 200, 'setup: favourites');

  const w = await boot({user: 'alice', hash: 'today'}), d = w.document;
  const tile = k => d.querySelector(`#kbar .fv2bar [data-fv2="${k}"]`), bdg = k => tile(k)?.querySelector('.fv2-bdg');
  const draw = () => { w.eval('FV2.last.clear(); fv2_barDraw()'); };
  const setTags = (tags, meta) => { w.eval(`S.lists.find(l => l.id === ${L}).tags = ${JSON.stringify(tags)}; S.settings.fav_meta = ${JSON.stringify(JSON.stringify(meta || {}))}; S.settings.fav_items = ${JSON.stringify(JSON.stringify(keys))}`); draw(); };
  check(await until(() => tile('tag:alpha') && tile('tag:beta') && tile('tag:gamma')), 'the row shows the three tags');

  // same colour (none): a badge with the first letter
  setTags([]);
  check(['alpha', 'beta', 'gamma'].every(n => bdg('tag:' + n)?.textContent === n[0].toUpperCase()), 'three tags without colour: badges A B G');
  check(!bdg('v:today'), 'a single symbol stays as it is');
  check(bdg('tag:beta').getAttribute('aria-hidden') === 'true' && tile('tag:beta').getAttribute('aria-label') === 'beta', 'badge aria-hidden, the name stays the aria-label');
  setTags([{name: 'alpha', color: '#ff0000'}, {name: 'beta', color: '#ff0000'}, {name: 'gamma', color: '#ff0000'}]);
  check(['alpha', 'beta', 'gamma'].every(n => bdg('tag:' + n)), 'three tags of the SAME colour: badges');

  // different colours: the colour, no badge
  setTags([{name: 'alpha', color: '#ff0000'}, {name: 'beta', color: '#00aa00'}, {name: 'gamma', color: '#0000ff'}]);
  check(!d.querySelector('#kbar .fv2-bdg') && tile('tag:beta').getAttribute('style').includes('#00aa00') && tile('tag:alpha').getAttribute('style').includes('#ff0000'), 'three tags of different colours: the colour, no badge');

  // own look first
  setTags([], {'tag:beta': {c: '#123456'}});
  check(!bdg('tag:beta') && tile('tag:beta').getAttribute('style').includes('#123456') && bdg('tag:alpha') && bdg('tag:gamma'), 'fav_meta wins: no badge on the tile with its own look');

  // equal first letters: two letters
  keys.splice(0, keys.length, 'tag:alpha', 'tag:apple', 'tag:beta', 'tag:gamma');
  w.eval(`S.settings.fav_items = ${JSON.stringify(JSON.stringify(keys))}`);
  await until(() => true); w.eval(`FV2.last.clear()`);
  setTags([]);
  check(tile('tag:apple') && bdg('tag:alpha')?.textContent === 'AL' && bdg('tag:apple')?.textContent === 'AP' && bdg('tag:beta')?.textContent === 'B', 'same first letter: the first two letters');

  // the page: the name stands there, no badge
  check(!w.eval(`fv2_tileHtml(fv2_distinct(fv2_tiles())[0], true)`).includes('fv2-bdg'), 'the page Favourites has no badge');

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  w.close();
  console.log(`p2572_a_favdistinct_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
