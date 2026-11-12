// kalmido-suite: fresh
// 2.1012.0 (#5690): the "..." menus of the budget, the bookmarks and the feeds are the shared menu() (popovers.js), no <details>
// of their own: role="menu", an anchor button with aria-haspopup, an entry focused, Escape closes, the phone shows a sheet with
// a title and an X. Used like a person: open, see the entries, pick one -> its effect (a window opens / the hidden file field is
// clicked / the download starts).
const {boot, sleep, errs, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = (fn, ms) => require('./boot').until(fn, {timeout: ms || 15000, step: 100});
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const FEAT = 'collab,contracts,budget,reading,feeds,bookmarks';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const LID = (await call('POST', '/api/budget/lists', {})).list_id;
  check(LID, 'a budget is there');

  const items = d => [...d.querySelectorAll('#pop:not(.hidden) [role="menuitem"]')];
  const labels = d => items(d).map(b => b.textContent.trim());
  const key = (w, el, k) => el.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true}));
  // opens the menu of an anchor and checks the shared form: role=menu, the anchor says haspopup, an entry has the focus
  const open = async (w, sel, what) => {
    const d = w.document, a = await until(() => d.querySelector(sel));
    check(a && a.getAttribute('aria-haspopup') === 'menu' && !a.closest('details'), `${what}: the anchor button says aria-haspopup=menu (no <details>)`);
    click(w, a); await until(() => items(d).length);
    check(items(d).length > 0 && d.querySelector('#pop [role="menu"]'), `${what}: the menu opens as role=menu`);
    await until(() => d.activeElement && d.activeElement.closest('#pop'));
    check(d.activeElement?.closest('#pop'), `${what}: an entry has the focus`);
    return a;
  };
  const escCloses = async (w, what) => { const d = w.document; key(w, d.activeElement, 'Escape'); check(await until(() => d.querySelector('#pop.hidden') || !d.querySelector('#pop [role="menu"]')), `${what}: Escape closes the menu`); };

  // ================= budget
  let w = await boot({user: 'alice', hash: 'budget/' + LID}); let d = w.document;
  await open(w, '.bgview [data-bg="more"]', 'budget');
  const bl = labels(d);
  check(['Categories', 'Recurring entries', 'Import a CSV file', 'New budget'].every(x => bl.includes(x)), 'budget: the entries are visible ' + bl.join('|'));
  await escCloses(w, 'budget');
  await open(w, '.bgview [data-bg="more"]', 'budget (again)');
  click(w, items(d).find(b => b.textContent.trim() === 'Categories'));
  check(await until(() => d.querySelector('.modal #bg-cnew')), 'budget: "Categories" opens its window');
  w.close();

  // ================= bookmarks
  w = await boot({user: 'alice', hash: 'bookmarks'}); d = w.document;
  await open(w, '.bmview [data-bm="more"]', 'bookmarks');
  const kl = labels(d);
  check(kl.includes('Save button for the browser') && kl.includes('Karakeep…'), 'bookmarks: both entries visible ' + kl.join('|'));
  await escCloses(w, 'bookmarks');
  await open(w, '.bmview [data-bm="more"]', 'bookmarks (again)');
  click(w, items(d).find(b => /Save button/.test(b.textContent)));
  check(await until(() => d.querySelector('.modal')), 'bookmarks: "Save button for the browser" opens its window');
  w.close();

  // ================= feeds: import clicks the hidden file field, export downloads (no link / label in the menu)
  w = await boot({user: 'alice', hash: 'feeds'}); d = w.document;
  await open(w, '.rssview [data-rss="omenu"]', 'feeds');
  check(labels(d).includes('Import OPML file') && !labels(d).includes('Export OPML file') && !d.querySelector('#pop a, #pop label'), 'feeds: Import is a button entry, no export without feeds ' + labels(d).join('|'));
  let fileClicked = 0; d.querySelector('[data-rss-opml]')?.addEventListener('click', () => fileClicked++);
  click(w, items(d).find(b => /Import OPML/.test(b.textContent)));
  check(await until(() => fileClicked === 1), 'feeds: "Import OPML file" clicks the hidden file field');
  if (d.querySelector('#pop:not(.hidden)')) w.eval('closePop()');
  w.eval(`RSS.feeds = [{id: 1, title: 'Example', unread: 0}]`);  // the menu reads the feeds when it opens: no fetch of a real feed needed
  await open(w, '.rssview [data-rss="omenu"]', 'feeds (with a feed)');
  let dl = '';
  const ac = w.HTMLAnchorElement.prototype.click; w.HTMLAnchorElement.prototype.click = function () { dl = this.getAttribute('href') + '|' + this.getAttribute('download'); };
  click(w, items(d).find(b => /Export OPML/.test(b.textContent)));
  check(await until(() => /^\/api\/feeds\/opml\?space=.*\|kalmido-feeds\.opml$/.test(dl)), 'feeds: "Export OPML file" starts the download ' + dl);
  w.HTMLAnchorElement.prototype.click = ac;
  w.close();

  // ================= phone: a sheet with a title and an X
  w = await boot({user: 'alice', mobile: true, hash: 'budget/' + LID}); d = w.document;
  await open(w, '.bgview [data-bg="more"]', 'budget on the phone');
  check(d.querySelector('#pop .tch-sh .tch-sht') && d.querySelector('#pop .tch-shx'), 'phone: the menu is a sheet with a title and an X');
  click(w, d.querySelector('#pop .tch-shx'));
  check(await until(() => d.querySelector('#pop.hidden')), 'phone: the X closes the sheet');
  w.close();

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
