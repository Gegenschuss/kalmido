// 2.46.4 UI tests, part A (#1732), own container (start.sh). jsdom, invented data only:
// - #1732 an address book deleted in the "Address books" dialog: its contacts leave the list at once - without a filter, with the
//   filter on that book (the filter falls back to all books), an open card of it closes, selected ids of it are dropped
// - the same when the book is deleted elsewhere (another device) and the state is loaded again (live update)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const change = (w, el, v) => { el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const items = d => [...d.querySelectorAll('#pop [role="menuitem"]')];
const item = (d, t) => items(d).find(x => (x.querySelector('.ml')?.firstChild?.textContent || x.textContent).trim() === t || x.getAttribute('title') === t);
const rows = d => [...d.querySelectorAll('#view .ctrow')].map(x => x.querySelector('b')?.textContent);

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', modules: ['cal']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,events,contacts'});
  const mk = async (name, people) => {
    const id = (await call('POST', '/api/books', {name})).id;
    for (const fn of people) await call('POST', '/api/contacts', {fn, book_id: id});
    return id;
  };
  const BK = await mk('Keep', ['Kim Keeper']);
  const B1 = await mk('Club', ['Clara Club', 'Carl Club']);
  const B2 = await mk('Choir', ['Hanna Choir']);
  const B3 = await mk('Team', ['Tom Team']);
  check(BK && B1 && B2 && B3, 'four address books');

  // ================= delete in the dialog, no filter, the card of a contact of it open, one of it selected
  const CC = (await call('GET', '/api/contacts?q=clara')).items[0].id;
  let w = await boot({user: 'alice', hash: 'contacts/' + CC}), d = w.document;
  w.confirm = () => true;
  await until(() => d.querySelectorAll('#view .ctrow').length === 5 && w.eval('CT.card') && w.eval('CT.card.id') === CC);
  check(rows(d).length === 5 && w.eval('CT.card?.id') === CC, 'five contacts, the card of Clara is open');
  w.eval(`CT.pick = new Set([${CC}])`);
  click(w, d.querySelector('#view [data-ct="menu"]')); await until(() => item(d, 'Address books…'));
  click(w, item(d, 'Address books…')); await until(() => d.querySelector(`.modal [data-cbmenu="${B1}"]`));
  click(w, d.querySelector(`.modal [data-cbmenu="${B1}"]`)); await until(() => item(d, 'Delete…'));
  click(w, item(d, 'Delete…'));
  check(await until(() => rows(d).length === 3), '#1732: deleted in the dialog: its two contacts leave the list at once ' + rows(d));
  check(!rows(d).some(x => /Club/.test(x)), '#1732: no contact of the deleted book is shown');
  check(!w.eval('CT.card') && !w.eval('CT.sel'), '#1732: the open card of a contact of it is closed');
  check(!w.eval(`CT.pick && CT.pick.has(${CC})`), '#1732: a selected contact of it is no longer selected');
  check(!(await call('GET', '/api/books')).items.some(b => b.id === B1), 'the book is gone on the server');
  w.eval('CT.pick = null');

  // ================= delete in the dialog while the list is filtered on that book
  d.querySelector('.modal [data-cb="close"]')?.click();
  await until(() => !d.querySelector('.modal'));
  await until(() => d.querySelector('#ct-book'));
  change(w, d.querySelector('#ct-book'), String(B2));
  check(await until(() => rows(d).length === 1 && rows(d)[0] === 'Hanna Choir'), 'filtered on Choir: one contact');
  click(w, d.querySelector('#view [data-ct="menu"]')); await until(() => item(d, 'Address books…'));
  click(w, item(d, 'Address books…')); await until(() => d.querySelector(`.modal [data-cbmenu="${B2}"]`));
  click(w, d.querySelector(`.modal [data-cbmenu="${B2}"]`)); await until(() => item(d, 'Delete…'));
  click(w, item(d, 'Delete…'));
  check(await until(() => rows(d).length === 2 && !rows(d).includes('Hanna Choir')), '#1732: filtered on the deleted book: the filter falls back, the other books show ' + rows(d));
  check(w.eval('CT.book') === '', '#1732: the filter on the deleted book is reset');
  d.querySelector('.modal [data-cb="close"]')?.click();
  w.close();

  // ================= deleted elsewhere (another device): the next load of the state clears the list
  w = await boot({user: 'alice', hash: 'contacts'}); d = w.document;
  await until(() => rows(d).length === 2);
  check(rows(d).includes('Tom Team'), 'Tom shown');
  check((await call('DELETE', `/api/books/${B3}`)).http < 300, 'Team deleted over the API');
  await w.eval('load().then(render)');
  check(await until(() => rows(d).length === 1 && rows(d)[0] === 'Kim Keeper'), '#1732: after the live update the contacts of the deleted book are gone ' + rows(d));
  w.close();

  console.log(`p246d_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
