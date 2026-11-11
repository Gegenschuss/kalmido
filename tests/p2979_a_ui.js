// 2.979.0 UI test, part A (#5667): an undo / redo the server takes back by its group (undo.js histDo, #5255) no longer runs the
// entry's own undo function, which used to fetch the area again; areas with their own store register how they fetch
// (core.js histReloader, undo.js histRedraw). The bookmarks as the example of such an area.
// kalmido-suite: fresh
// freelancer-matrix: undo (a person without an organisation: her archived bookmark comes back with one undo)
// jsdom, fresh container. Invented names only. alice keeps two bookmarks:
//  - archiving one in the view hides it; one undo (the arrow, histStep) shows it again in the open view, redo hides it again
//  - deleting one; undo brings the card back, the next change on it (archive) works (no stale data)
//  - the list "Recent steps" (undolist.js "Back up to here") runs the same redraw: a registered area is called
//  - a bookmark list not shown is marked old and fetched when the view opens again
//  - fiona (no organisation): archive + undo in her view
// The waits are on states (cards, rows, counters), never on a fixed time.
const {boot, errs, B, login, until: until0} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const until = (fn, ms) => until0(fn, {timeout: ms || 20000, step: 100});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));

async function person(ck, user, tag) {
  const a = await call(ck, 'POST', '/api/bookmarks', {url: `https://example.com/${tag}-eins`, title: `Zebra ${tag}`});
  const b = await call(ck, 'POST', '/api/bookmarks', {url: `https://example.com/${tag}-zwei`, title: `Pelikan ${tag}`});
  a.id = a.bookmark?.id; b.id = b.bookmark?.id;
  check(a.id > 0 && b.id > 0, `${user}: two bookmarks (${a.http} ${b.http})`);
  const w = await boot({user, hash: 'bookmarks'}); const d = w.document;
  const card = id => d.querySelector(`.bmcard[data-id="${id}"]`);
  check(await until(() => card(a.id) && card(b.id)), `${user}: the view shows both cards`);
  return {w, d, card, A: a.id, Bid: b.id};
}

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: []});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', features: 'reading', tour: 'done'});
  const {w, d, card, A, Bid} = await person(CA, 'alice', 'alice');
  const steps = () => w.eval('HIST.undo.length');

  // ---- archive in the view, undo with the arrow: the open view shows the card again
  let n0 = steps();
  click(w, card(A)?.querySelector('[data-bm="arch"]'));
  check(await until(() => !card(A) && steps() > n0), 'archived: the card leaves the default list, one step');
  check(await until(() => w.eval('histGids(HIST.undo[HIST.undo.length - 1]).length') > 0), 'the step is a group of the server');
  await w.eval(`histStep('undo').then(() => 1)`);
  check(await until(() => card(A)), 'undo (server group): the open view shows the card again');
  check(/Zebra alice/.test(card(A)?.textContent || ''), `... with its title (${card(A)?.textContent?.slice(0, 60)})`);
  await w.eval(`histStep('redo').then(() => 1)`);
  check(await until(() => !card(A)), 'redo: archived again, the card goes');
  await w.eval(`histStep('undo').then(() => 1)`);
  check(await until(() => card(A)), 'undo once more: back');

  // ---- delete, undo, then change it again: the page has the new state (no stale card)
  n0 = steps();
  await w.eval(`bm_del(${Bid}).then(() => 1)`);
  check(await until(() => !card(Bid) && steps() > n0), 'deleted: the card is gone');
  await w.eval(`histStep('undo').then(() => 1)`);
  check(await until(() => card(Bid)), 'undo of the delete: the card is back in the view');
  click(w, card(Bid)?.querySelector('[data-bm="arch"]'));
  check(await until(() => !card(Bid)), 'the card brought back can be changed again (archive)');
  const srvB = await call(CA, 'GET', `/api/bookmarks/${Bid}`);
  check(srvB.state === 'archived', `the server has it archived (${srvB.http} ${srvB.state})`);
  await w.eval(`histStep('undo').then(() => 1)`);
  check(await until(() => card(Bid)), 'and back');

  // ---- the list "Recent steps": its "Back up to here" runs the same redraw (a registered area is called)
  await w.eval(`window.__rl = 0; histReloader('p2979test', () => { window.__rl++; })`);
  click(w, card(A)?.querySelector('[data-bm="arch"]'));
  check(await until(() => !card(A)), 'archived once more');
  const g = ((await call(CA, 'GET', '/api/undo')).items || []).find(x => x.state !== 'undone') || {};
  d.querySelector('#top [data-act="hist-undo"]').dispatchEvent(new w.MouseEvent('contextmenu', {bubbles: true, cancelable: true}));
  const row = () => d.querySelector(`#pop:not(.hidden) .ulbody .ulrow[data-ul="s:${g.id}"] [data-ul-go]`);
  check(await until(() => row() && !row().disabled), `the list shows the newest step of the server (${g.id} ${g.label})`);
  click(w, row());
  check(await until(() => w.eval('window.__rl') > 0 && !w.eval('UL.busy')), `Back up to here: the registered areas fetched again (${w.eval('window.__rl')})`);
  check(await until(() => card(A)), '... and the bookmark view shows the card again');
  w.eval(`HIST_RELOAD.delete('p2979test')`);
  w.eval(`$('#pop')?.classList.add('hidden')`);

  // ---- a list not shown is old after the undo; the view fetches it when it opens again
  click(w, card(A)?.querySelector('[data-bm="arch"]'));
  check(await until(() => !card(A)), 'archived before leaving the view');
  w.location.hash = 'home';
  check(await until(() => !d.querySelector('.bmview')), 'another page');
  await w.eval(`histStep('undo').then(() => 1)`);
  check(w.eval('BM.at') === 0, 'the bookmarks not shown are marked old');
  w.location.hash = 'bookmarks';
  check(await until(() => card(A)), 'back in the view: the card is there again');
  w.close();

  // ---- a person without an organisation (freelancer parity)
  await call(CA, 'POST', '/api/users', {username: 'fiona', display_name: 'Fiona', password: 'password123', email: 'fiona@example.com', orgs: []});
  const CF = await login('fiona');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', features: 'reading', tour: 'done', workspace: 'private'});
  const f = await person(CF, 'fiona', 'fiona');
  click(f.w, f.card(f.A)?.querySelector('[data-bm="arch"]'));
  check(await until(() => !f.card(f.A)), 'fiona: archived');
  await f.w.eval(`histStep('undo').then(() => 1)`);
  check(await until(() => f.card(f.A)), 'fiona: one undo shows her card again');
  f.w.close();

  check(!errs.length, 'no script errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`p2979_a_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(err => { console.error(err); process.exit(1); });
