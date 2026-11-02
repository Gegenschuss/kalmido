// kalmido-suite: fresh
// 2.418.0 (#3560) UI test (jsdom), own container (start.sh): the menus of the areas, arranged per person
//  - computer: the office's panel ends with "Customise"; it opens the editor in place (Minus, grip, Hidden with Plus,
//    Done); 2.448.0 (#3784): every point of Money shows before its first use (#3411), no "More"
//  - Minus hides a point (only the menu: its route still opens), Plus brings one back, the arrow keys on the grip move a
//    point inside its group; everything lands in the setting nav_menus (the same on every device) and can be undone
//  - right-click on a point of the panel: "Hide from menu"
//  - Home: a hidden part leaves the panel; the old sidebar choice ("e:<part>") counts as hidden until shown again
//  - phone: the pen on top of the office's start page opens the same editor; Settings > Navigation shows every menu and
//    the tab bar, whose order is the person's now
//  - an organisation's admins switch a point off: it is in no member's menu there, not even under Hidden
// freelancer-matrix: settings (frida, without an organisation, arranges her own office menu)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const FEATS = 'cal,collab,comments,contacts,files,docs,clients,office,time,pomo,reading,feeds,home,family,budget,contracts';
const menus = async ck => JSON.parse((await call('GET', '/api/state', null, ck)).settings.nav_menus || '{}');

(async () => {
  await sleep(800);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const me = await call('GET', '/api/state');
  const org = await call('POST', '/api/admin/orgs', {name: 'Nordwind', admin_id: me.me.id});
  check(org.id, 'an organisation');
  check((await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com', orgs: [org.id]})).id, 'bob, a member');
  check((await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com'})).id, 'frida, without an organisation');
  const CF = await login('frida'), CB = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEATS}, CF);
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEATS, workspace: `org:${org.id}`}, CB);
  check(!((await call('GET', '/api/state', null, CF)).me.workspaces || []).length, 'P4: frida has no organisation');

  // ================= computer: frida's office (her own admin)
  let w = await boot({user: 'frida', hash: 'office/offers', ls: {'tasks.sbbUnfold': JSON.stringify(['office:money'])}}), d = w.document;
  const ev = s => w.eval(s);
  check(await until(() => ev(`typeof OFC === 'object' && !!OFC.info`) && d.querySelector('#side [data-ofm="offers"]')), 'computer: the office panel');
  const side = () => [...d.querySelectorAll('#side [data-ofm]')].map(b => b.dataset.ofm);
  // 2.448.0 (#3784): points of Money not used yet show at once, nothing starts hidden
  check(['cashflow', 'kpi', 'travel', 'meals', 'subs', 'receipts'].every(k => side().includes(k)), '#3784: the unused points are in the menu ' + side());
  check(!d.querySelector('#side [data-act="ofm-more"]'), '#3560: no "Show more" any more');
  const cust = d.querySelector('#side [data-act="nav-edit"][data-area="office"]');
  check(cust && /Customise/.test(cust.textContent), '#3560: "Customise" ends the panel');
  cust.click();
  const ed = () => d.querySelector('#side .naved[data-naved="office"]');
  check(await until(() => ed()), '#3560: Customize opens the editor in place (navmenu.js loads)');
  const hidKeys = () => [...(ed()?.querySelectorAll('.navoffl .navr') || [])].map(li => li.dataset.k);
  check(!hidKeys().length, '#3784: nothing starts under Hidden ' + hidKeys());
  check(ed().querySelector('.navl[data-navg="sell"] .navr[data-k="offers"] [data-act="nav-hide"]') && ed().querySelector('.navr[data-k="offers"] .navgrip') && ed().querySelector('[data-act="nav-done"]'), '#3560: a row: Minus, grip; Done on top');
  // Minus hides the figures, Plus brings them back
  ed().querySelector('.navr[data-k="kpi"] [data-act="nav-hide"]').click();
  check(await until(() => hidKeys().includes('kpi')), '#3560: Minus: the figures are under Hidden');
  ed().querySelector('.navoffl [data-k="kpi"] [data-act="nav-show"]').click();
  check(await until(async () => !((await menus(CF)).office?.hidden || []).includes('kpi')), '#3560: Plus takes the figures out of hidden');
  check(await until(() => ed()?.querySelector('.navl[data-navg="money"] .navr[data-k="kpi"]')), '#3560: the figures move into the menu (group Money)');
  // Minus hides the contacts (address book)
  ed().querySelector('.navr[data-k="contacts"] [data-act="nav-hide"]').click();
  check(await until(async () => ((await menus(CF)).office?.hidden || []).includes('contacts')), '#3560: Minus saves hidden: contacts');
  check(await until(() => hidKeys().includes('contacts')), '#3560: the address book is under Hidden now');
  // the arrow keys on the grip: Quotations one down
  const sell = () => [...ed().querySelectorAll('.navl[data-navg="sell"] .navr')].map(li => li.dataset.k);
  const s0 = sell(), i0 = s0.indexOf('offers');
  ed().querySelector('.navr[data-k="offers"] .navgrip').dispatchEvent(new w.KeyboardEvent('keydown', {key: 'ArrowDown', bubbles: true}));
  check(await until(() => sell().indexOf('offers') === i0 + 1), '#3560: ArrowDown on the grip moves Quotations one down ' + sell());
  const ord = await until(async () => { const o = (await menus(CF)).office?.order || []; return o.indexOf('offers') > o.indexOf(s0[i0 + 1]) && o.indexOf(s0[i0 + 1]) >= 0 && o; });
  check(ord, '#3560: the order is saved ' + JSON.stringify(ord));
  // Done: the panel shows the result
  ed().querySelector('[data-act="nav-done"]').click();
  check(await until(() => !ed() && side().includes('kpi') && !side().includes('contacts')), '#3560: Done: figures in the menu, address book not ' + side());
  check(side().indexOf('offers') > side().indexOf(s0[i0 + 1]), '#3560: ... in the new order');
  // hidden = only the menu: the route opens, and while open the point shows
  ev(`go('contacts')`);
  check(await until(() => ev('S.route.mod') === 'contacts' && d.querySelector('#side [data-ofm="contacts"]')), '#3560: a hidden point still opens (and shows while open)');
  ev(`go('office/offers')`);
  check(await until(() => !d.querySelector('#side [data-ofm="contacts"]')), '#3560: ... and leaves the menu again');
  // undo brings the address book back
  ev(`histStep('undo')`);
  check(await until(async () => !((await menus(CF)).office?.hidden || []).includes('contacts') || (await menus(CF)).office?.order?.indexOf('offers') !== ord.indexOf('offers')), '#3560: undo steps back');
  await call('PATCH', '/api/settings', {nav_menus: JSON.stringify({office: {shown: ['kpi']}})}, CF);
  // right-click on a point: "Hide from menu"
  await w.eval(`load().then(render)`);
  const bank = await until(() => d.querySelector('#side [data-navk="office:bank"]'));
  check(bank, '#3560: a panel row carries its menu key');
  bank.dispatchEvent(new w.MouseEvent('contextmenu', {bubbles: true, cancelable: true}));
  const mi = await until(() => [...d.querySelectorAll('[role="menuitem"]')].find(x => /Hide from menu/.test(x.textContent)));
  check(mi, '#3560: right-click offers "Hide from menu"');
  mi?.click();
  check(await until(async () => ((await menus(CF)).office?.hidden || []).includes('bank')), '#3560: ... and hides Bank');
  check(await until(() => !d.querySelector('#side [data-ofm="bank"]')), '#3560: Bank leaves the panel');

  // ================= Home: parts; the old sidebar choice counts as hidden
  await call('PATCH', '/api/settings', {sidebar: JSON.stringify({order: [], hidden: ['e:budget']})}, CF);
  await w.eval(`load().then(render)`);
  ev(`go('life')`);
  check(await until(() => d.querySelector('#side [data-sbbpart="life"]')), 'Home: its panel');
  check(!d.querySelector('#side [data-sbbpart="budget"]'), '#3560: the budget hidden in the old sidebar settings stays hidden');
  d.querySelector('#side [data-act="nav-edit"][data-area="life"]').click();
  const led = () => d.querySelector('#side .naved[data-naved="life"]');
  check(await until(() => led()?.querySelector('.navoffl [data-k="budget"]')), '#3560: ... it is under Hidden of the editor');
  led().querySelector('.navoffl [data-k="budget"] [data-act="nav-show"]').click();
  check(await until(async () => ((await menus(CF)).life?.shown || []).includes('budget') && !JSON.parse((await call('GET', '/api/state', null, CF)).settings.sidebar || '{}').hidden?.includes('e:budget')), '#3560: Plus shows it and clears the old choice');
  led().querySelector('.navr[data-k="family"] [data-act="nav-hide"]').click();
  check(await until(async () => ((await menus(CF)).life?.hidden || []).includes('family')), '#3560: Minus hides Family');
  led().querySelector('[data-act="nav-done"]').click();
  check(await until(() => !led() && d.querySelector('#side [data-sbbpart="budget"]') && !d.querySelector('#side [data-sbbpart="family"]')), '#3560: Home panel: budget back, family gone');

  // ================= Settings > Navigation
  ev(`settingsModal('nav')`);
  check(await until(() => d.querySelector('.smodal #s-navmenus .naved[data-naved="office"]')), '#3560: Settings > Navigation: the office editor');
  check(d.querySelector('.smodal #s-navmenus [data-navsec="life"]') && d.querySelector('.smodal #s-navmenus [data-navsec="tabbar"]'), '#3560: ... Home and the tab bar too');
  const tb = d.querySelector('.smodal .naved[data-naved="tabbar"]');
  check(tb && tb.querySelector('.navoffl [data-k="a:office"] [data-act="nav-show"]'), '#3560: the tab bar: the office can be pinned with Plus');
  tb.querySelector('.navoffl [data-k="a:office"] [data-act="nav-show"]').click();
  check(await until(async () => ((await menus(CF)).tabbar?.order || []).includes('a:office')), '#3560: the tab bar order is the person\'s (nav_menus.tabbar)');
  check(await until(() => ev('tabIds()').includes('a:office')), '#3560: tabIds follows');
  d.querySelector('.smodal')?.remove();
  w.close();

  // ================= phone: the pen on top of the office's start page
  w = await boot({user: 'frida', mobile: true, hash: 'office/start'}); d = w.document;
  const ep = s => w.eval(s);
  check(await until(() => d.querySelector('#view .ofmstart [data-act="nav-edit"][data-area="office"]')), '#3560 phone: a pen on top of the office menu');
  check(!d.querySelector('#view [data-act="ofm-more"]'), '#3560 phone: no "Show more"');
  d.querySelector('#view .ofmstart [data-act="nav-edit"]').click();
  check(await until(() => d.querySelector('#view .naved.navtouch[data-naved="office"] [data-act="nav-done"]')), '#3560 phone: the editor (touch: Minus always shown)');
  check(d.querySelector('#view .naved .navoffl [data-k="bank"]'), '#3560 phone: Bank hidden on the computer is hidden here too (one setting)');
  d.querySelector('#view .naved [data-act="nav-done"]').click();
  check(await until(() => !d.querySelector('#view .naved') && d.querySelector('#view .ofmstart')), '#3560 phone: Done');
  check(await until(() => ep(`[...document.querySelectorAll('#tabs button')].some(b => b.dataset.go && /office/.test(b.dataset.go))`)), '#3560 phone: the office tab pinned on the computer is in the phone\'s bar');
  w.close();

  // ================= an organisation's admins switch a point off
  check((await call('PATCH', `/api/orgs/${org.id}`, {nav_off: ['office:travel']})).status === 200, 'the admin switches Travel expenses off for the members');
  await call('PATCH', '/api/settings', {nav_menus: JSON.stringify({office: {shown: ['travel', 'kpi']}})}, CB);
  w = await boot({user: 'bob', hash: 'office/offers'}); d = w.document;
  check(await until(() => w.eval(`typeof OFC === 'object' && !!OFC.info`) && d.querySelector('#side [data-ofm]')), 'bob: the organisation\'s office');
  check(!d.querySelector('#side [data-ofm="travel"]'), '#3560: a point off in the organisation is not in the menu (although bob showed it)');
  d.querySelector('#side [data-act="nav-edit"][data-area="office"]')?.click();
  check(await until(() => d.querySelector('#side .naved[data-naved="office"]')), 'bob: the editor');
  check(!d.querySelector('#side .naved [data-k="travel"]'), '#3560: ... not even under Hidden');
  w.close();

  console.log(`p2418_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
