// 2.87.9 part C UI tests (#1917, the office menu with four groups; 2.98.0 (#2180): the office rail on the left with three
// groups, a phone's start list and its row of tabs - the details of the new layout are in p298_c_ui.js), own container (start.sh), Firefox (computer + phone
// width). Invented people and companies only.
// - a person without an organisation (her own admin, P4): on a computer the menu with the groups Sell, Money,
//   Administration (2.98.0: On the road is gone) and their points, no old tab row, sticky, the point shown in the accent; a point opens its page (also
//   Clients / Contacts), the menu stays; the path "Clients › Example Ltd" only on a client's page, grey text, no links
// - phone: #office = the start page with four tiles; a point opens its page with the path "Office › group" and the group's
//   points; the path leads back to the tiles; large tap targets, nothing sticks out to the side
// - a member of an organisation: no admin points, empty groups (Money) are hidden
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p287b_c_ui', check, shots: 'P287BC_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => {
  for (let i = 0; ; i++) {
    const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined});
    if (r.status === 429 && i < 8) { await sleep(500 * (i + 1)); continue; }
    const j = await r.json().catch(() => ({})); return {...j, http: r.status};
  }
};
const FEAT = 'cal,comments,collab,contacts,office,clients';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob Member', password: 'password123', email: 'bob@example.com'});
  await call(CA, 'POST', '/api/users', {username: 'carol', display_name: 'Carol Solo', password: 'password123', email: 'carol@example.com'});
  const CB = await login('bob'), CC = await login('carol');
  for (const ck of [CA, CB, CC]) await call(ck, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CA, 'PUT', `/api/orgs/${org.id}/members`, {email: 'bob@example.com', role: 'member'});
  await call(CB, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  const cst = (await call(CC, 'GET', '/api/state')).me;
  check(!(cst.workspaces || []).length, 'P4: carol has no organisation');
  const os = await call(CC, 'GET', '/api/office/settings');
  check(os.http === 200 && os.role === 'admin' && os.personal, 'P4: carol is the admin of her own (personal) office ' + JSON.stringify({http: os.http, role: os.role, personal: os.personal}));
  const cl = await call(CC, 'POST', '/api/clients', {name: 'Example Ltd'});
  check(cl.id > 0, 'a client of carol');

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const click = (ev, sel) => ev(`(() => { const b = document.querySelector(${JSON.stringify(sel)}); if (!b) return 0; b.click(); return 1; })()`);
  const noSide = `document.documentElement.scrollWidth <= window.innerWidth + 1`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await signIn(ev, 'carol') === 200, 'carol signs in');
    // ================= computer
    await nav(B + '#office/offers');
    check(await ready(ev, `!!document.querySelector('#view .ofrail') && typeof OFC === 'object' && !!OFC.info`, 80), '#1917: the office menu');  // 2.98.0 (#2180): the office rail
    check(await ev(`[...document.querySelectorAll('#view .ofrail .ofrg')].map(g => g.dataset.ofmg).join() === 'sell,money,admin'`), '#1917: three groups in order (P4: all of them for a person without an organisation)');  // 2.98.0 (#2180): On the road is gone
    check(await ev(`[...document.querySelectorAll('#view .ofrail .ofrh')].map(g => g.textContent.trim()).join('|') === 'Sell|Money|Administration'`), '#1917: the group names');  // 2.98.0 (#2180)
    const pts = await ev(`[...document.querySelectorAll('#view .ofrail [data-ofmg]')].map(g => g.dataset.ofmg + ':' + [...g.querySelectorAll('[data-ofm]')].map(b => b.dataset.ofm).join('+')).join(' ')`);
    check(pts === 'sell:pipeline+offers+clients+contacts+gendocs+contracts+letters money:cashflow+kpi+bank+books+subs+travel+meals+cashbook admin:equipment+agreements+settings', '#1917: the points of each group ' + pts);  // 2.153.0 (#2028): + letters (correspondence) under Sell  // 2.121.0 (#2095): + cashbook under Money  // 2.119.0 (#2288): + meals (entertainment receipts) under Money  // 2.98.0 (#2180): contracts -> Sell, travel -> Money, services + text blocks under Settings  // 2.92.1: + the tabs of 2.90-2.92; 2.93.0 (#1927): + Documents (gendocs) under Sell
    check(await ev(`!document.querySelector('.ofctabs') && !document.querySelector('#view .mgtabs')`), '#1917: no old tab rows');
    check(await ev(`getComputedStyle(document.querySelector('#view .ofrail')).position === 'sticky'`), '#1917: the menu stays on top (sticky)');  // 2.98.0 (#2180)
    check(await ev(`(() => { const on = document.querySelector('#view .ofrail [aria-current="page"]'), off = document.querySelector('#view .ofrail [data-ofm="equipment"]'); return on?.dataset.ofm === 'offers' && on.classList.contains('on') && getComputedStyle(on).color !== getComputedStyle(off).color; })()`), '#1917: the point shown in the accent');  // 2.98.0 (#2180): the rail
    check(await ev(`!document.querySelector('#view .ofmcrumb')`), '#1917: no path on a list page');
    await shot('p287b-c-menu-desktop.png');
    await click(ev, '#view .ofrail [data-ofm="equipment"]');  // 2.98.0 (#2180): services are a tab under Settings now (p298_c_ui)
    check(await ready(ev, `location.hash === '#office/equipment' && !!document.querySelector('.office[data-ofctab="equipment"]') && document.querySelector('#view .ofrail [aria-current="page"]')?.dataset.ofm === 'equipment'`, 60), '#1917: a point opens its page');
    await click(ev, '#view .ofrail [data-ofm="clients"]');
    check(await ready(ev, `location.hash === '#clients' && !!document.querySelector('#view .msclients') && document.querySelector('#view .ofrail [aria-current="page"]')?.dataset.ofm === 'clients'`, 60), '#1917: Clients opens in the menu');
    check(await ev(`!document.querySelector('#view .msclh')`), '#1917: no heading "Office › Clients" any more');
    await nav(B + '#client/' + cl.id);
    check(await ready(ev, `!!document.querySelector('#view .ofmcrumb')`, 60), '#1917: the path on a client');
    check(await ev(`(() => { const c = document.querySelector('#view .ofmcrumb'); return /Clients\\s*›\\s*Example Ltd/.test(c.textContent) && !c.querySelector('a,button'); })()`), '#1917: path "Clients › Example Ltd", text only ' + await ev(`document.querySelector('#view .ofmcrumb')?.textContent`));
    await shot('p287b-c-client-desktop.png');
    // ================= phone
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + 'static/icon.svg');
    await nav(B + '#office');
    // 2.98.0 (#2180): the start page lists the three groups (one card each) instead of four tiles
    check(await ready(ev, `document.querySelectorAll('#view .ofmstart .oflg').length === 3`, 80), '#1917 phone: the start page with the groups');
    check(await ev(`!document.querySelector('#view .ofrail') && !document.querySelector('#view .ofpb')`), '#1917 phone: the list is the menu');
    check(await ready(ev, `!!document.querySelector('#view .ofmstart .ofmfig .kptl')`, 40), '#1917 phone: the figures above the groups (admin)');
    check(await ev(`[...document.querySelectorAll('#view .oflc .oflr')].every(b => b.getBoundingClientRect().height >= 43)`), '#1917 phone: large tap targets');  // 2.98.0 (#2180)
    check(await ev(noSide), '#1917 phone: nothing sticks out to the side (start page)');
    await shot('p287b-c-start-phone.png');
    await click(ev, '#view .oflc [data-ofm="cashflow"]');  // 2.98.0 (#2180): the bar .ofpb with the back button and the tab row
    check(await ready(ev, `location.hash === '#office/cashflow' && !!document.querySelector('#view .ofpb')`, 60), '#1917 phone: a tile point opens its page');
    check(await ev(`/Office\\s*·\\s*Money/.test(document.querySelector('#view .ofpb .ofpback').textContent) && [...document.querySelectorAll('#view .ofpb [data-ofm]')].map(b => b.dataset.ofm).join() === 'cashflow,kpi,bank,books,subs,travel,meals,cashbook'`), '#1917 phone: path Office · Money and the points of the group');  // 2.121.0 (#2095): + cashbook  // 2.98.0 (#2180)  // 2.119.0 (#2288): + meals (entertainment receipts) under Money
    check(await ev(`getComputedStyle(document.querySelector('#view .ofpb')).position === 'sticky' && document.querySelector('#view .ofpb .ofpback').getBoundingClientRect().height >= 43`), '#1917 phone: the bar stays on top, the way back is large enough');  // 2.98.0 (#2180)
    check(await ev(noSide), '#1917 phone: nothing sticks out to the side (cash flow)');
    await shot('p287b-c-cashflow-phone.png');
    await click(ev, '#view .ofpb .ofpback');  // 2.98.0 (#2180)
    check(await ready(ev, `location.hash === '#office/start' && document.querySelectorAll('#view .oflg').length === 3`, 60), '#1917 phone: the path leads back to the tiles');
    await click(ev, '#view .oflc [data-ofm="contacts"]');
    check(await ready(ev, `location.hash === '#contacts' && /Office\\s*·\\s*Sell/.test(document.querySelector('#view .ofpb .ofpback')?.textContent || '')`, 60), '#1917 phone: Contacts under Office · Sell');
    // ================= member of an organisation
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await signIn(ev, 'bob');
    await nav(B + 'static/icon.svg');
    await nav(B + '#office/offers');
    check(await ready(ev, `!!document.querySelector('#view .ofrail [data-ofm="offers"]') && typeof OFC === 'object' && !!OFC.info && OFC.info.role !== 'admin'`, 80), 'the office (member)');  // 2.98.0 (#2180)
    check(await ev(`!document.querySelector('#view .ofrail [data-ofm="pipeline"],#view .ofrail [data-ofm="cashflow"],#view .ofrail [data-ofm="kpi"],#view .ofrail [data-ofm="travel"]')`), '#1917: a member sees no admin points');  // 2.98.0 (#2180)
    check(await ev(`[...document.querySelectorAll('#view .ofrail .ofrg')].map(g => g.dataset.ofmg).join() === 'sell,admin'`), '#1917: empty groups are hidden for a member');  // 2.98.0 (#2180)
  }, false);

  console.log(`p287b_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
