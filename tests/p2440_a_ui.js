// 2.440.0 UI tests, part A (#3609), jsdom, invented data only: the office switches single menu points off
// - Settings > Functions > Menu points: one switch per point, saved in the office setting menu_off; an unknown or a point that
//   cannot be switched off is refused; Money's points with a function of their own stand there with that switch
// - off = gone from the panel, the start page and the palette's "Go to"; a link opens the start page and the data stays;
//   on again = back
// - for everybody of the office (a member too, who may not change it), not for another office
// - a person without an organisation is the admin of their own office
// freelancer-matrix: office (alice has no organisation until the org part, P4)
// kalmido-suite: fresh
const {boot, errs, B, login, until} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
const FEAT = 'cal,comments,collab,contacts,office,clients,time';
const items = w => JSON.parse(w.eval('JSON.stringify(ofm_items().map(i => i.key))'));
const hash = w => w.location.hash;

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments', 'contacts']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check((await call('GET', '/api/office/settings')).settings.menu_off.length === 0, 'nothing is off to begin with');
  check((await call('PUT', '/api/office/settings', {menu_off: ['nope']})).http === 400, 'an unknown point is refused');
  check((await call('PUT', '/api/office/settings', {menu_off: ['offers']})).http === 400, 'a point that cannot be switched off is refused');
  check((await call('PUT', '/api/office/settings', {menu_off: 'bank'})).http === 400, 'no list is refused');
  await call('POST', '/api/office/equipment', {name: 'Camera A'});
  const eq0 = (await call('GET', '/api/office/equipment'));

  // ================= the switch in the settings: a person without an organisation
  let w = await boot({user: 'alice', hash: 'office/settings'}), d = w.document;
  check(await until(() => w.eval('!!OFC.info')), 'setup: the office is loaded');
  const s0 = items(w);
  check(s0.includes('pipeline') && s0.includes('cashbook') && s0.includes('equipment'), 'before: the points are in the menu ' + s0);
  check(await until(() => !!d.querySelector('#ocm-cashbook')), 'the switch of the cash book is there');
  for (const k of ['pipeline', 'gendocs', 'letters', 'time', 'contracts', 'cashbook', 'bank', 'equipment', 'agreements']) check(d.querySelector('#ocm-' + k)?.checked === true, 'a switch, on: ' + k);
  for (const k of ['cashflow', 'kpi', 'meals', 'subs', 'travel']) check(!!d.querySelector(`.ocf-list #ocf-money-${k}`) && !d.querySelector('#ocm-' + k), 'one switch, the function\'s: ' + k);
  for (const k of ['offers', 'invoices', 'clients', 'contacts', 'books', 'receipts', 'settings']) check(!d.querySelector('#ocm-' + k), 'no switch: ' + k);
  const cb = d.querySelector('#ocm-cashbook'); cb.checked = false; cb.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(async () => ((await call('GET', '/api/office/settings')).settings.menu_off || []).join() === 'cashbook'), 'the switch saves menu_off');
  check(await until(() => !items(w).includes('cashbook')), 'the menu follows at once');
  await call('PUT', '/api/office/settings', {menu_off: ['pipeline', 'cashbook', 'equipment', 'bank']});
  w.close();

  // ================= off: gone everywhere, a link opens the start page
  w = await boot({user: 'alice', hash: 'office/equipment'}); d = w.document;
  check(await until(() => hash(w) === '#office/start'), 'a link to a point switched off opens the start page: ' + hash(w));
  check(await until(() => !!d.querySelector('.ofmstart [data-ofm="offers"]')), 'the start page is drawn');
  for (const k of ['pipeline', 'cashbook', 'equipment', 'bank']) {
    check(!items(w).includes(k), 'not in the menu: ' + k);
    check(!d.querySelector(`.ofmstart [data-ofm="${k}"]`), 'no tile: ' + k);
    check(!w.eval(`ofm_hidden().some(i => i.key === '${k}')`), 'not under Hidden of the menu editor: ' + k);
  }
  check(items(w).includes('offers') && items(w).includes('books'), 'the other points stay');
  w.eval("location.hash = '#office/offers'");
  check(await until(() => hash(w) === '#office/offers' && w.eval('S.route.tab') === 'offers'), 'a point still on opens');
  w.eval("location.hash = '#office/cashbook'");
  check(await until(() => hash(w) === '#office/start'), 'also while the app runs');
  check((await call('GET', '/api/office/equipment')).items?.length === eq0.items?.length, 'the data stays, the route answers');
  w.close();

  // ================= on again
  await call('PUT', '/api/office/settings', {menu_off: []});
  w = await boot({user: 'alice', hash: 'office/equipment'});
  check(await until(() => w.eval('S.route.tab') === 'equipment' && hash(w) === '#office/equipment' && items(w).includes('equipment')), 'on again: the link opens the point, the menu has it');
  w.close();

  // ================= an organisation: for all members, not for the private office
  await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Member', password: 'password123', email: 'bob@example.com'});
  const CB = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, CB);
  const me = (await call('GET', '/api/state')).me.id;
  const ORG = (await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me})).id;
  await call('PUT', `/api/orgs/${ORG}/members`, {email: 'bob@example.com', role: 'member'});
  for (const ck of [CK, CB]) await call('PATCH', '/api/settings', {workspace: `org:${ORG}`}, ck);
  check((await call('PUT', '/api/office/settings', {menu_off: ['contracts']})).http === 200, 'the admin of the organisation switches a point off');
  check((await call('PUT', '/api/office/settings', {menu_off: []}, CB)).http === 403, 'a member may not change it');
  const m = await call('GET', '/api/office/settings', null, CB);
  check((m.settings.menu_off || []).join() === 'contracts', 'the member reads the list ' + JSON.stringify(m.settings.menu_off));
  w = await boot({user: 'bob', hash: 'office/contracts'});
  check(await until(() => hash(w) === '#office/start'), 'the member: the link opens the start page');
  check(!items(w).includes('contracts') && items(w).includes('offers'), 'the member: not in the menu ' + items(w));
  w.close();
  await call('PATCH', '/api/settings', {workspace: 'private'});
  check(!((await call('GET', '/api/office/settings')).settings.menu_off || []).includes('contracts'), 'the private office has its own list');

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  console.log(`p2440_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
