// kalmido-suite:
// 2.417.0 A UI test (#3559: the area buttons all work alike), own container (start.sh), jsdom + Firefox. Invented data only.
// - the tab "Projects" (phone) opens the page kept in Projects in full view, not the drawer; the bar's icons (computer) and
//   the tabs keep the last page of each area
// - tapping the button of the area already open = the area's start page: Projects = the new start page #projects, the
//   office = the office overview (phone tab and computer bar)
// - the start page of Projects shows the projects grouped by the folders of the sidebar, in the sidebar's order (one source)
// - Firefox at 390 x 844 and 1280 x 860: the start page fits (no sideways overflow), screenshots (P2417A_SHOTS)
// P4: a person without an organisation gets the same (freelancer-matrix: navigation)
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2417_a_ui', check, shots: 'P2417A_SHOTS'});
const FEAT = 'cal,office,contacts,kanban';  // the areas the test walks through
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2417A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', modules: ['cal', 'office', 'contacts']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(!((await call(CF, 'GET', '/api/state')).me.workspaces || []).length, 'frida: no organisation');

  const ids = {};
  for (const [u, ck] of [['alice', CA], ['frida', CF]]) {
    const mk = async (name, folder) => (await call(ck, 'POST', '/api/lists', {name, ...(folder ? {folder} : {})})).id;
    ids[u] = {loose: await mk('Loose one'), a1: await mk('Alpha task list', 'Alpha'), b1: await mk('Beta list', 'Alpha/Beta'), g1: await mk('Gamma list', 'Gamma')};
    const I = ids[u];

    // ================= the phone: the tab bar
    let w = await boot({user: u, mobile: true, hash: 'l/' + I.a1}), d = w.document;
    await until(() => d.querySelector('#tabs button'));
    check(!d.querySelector('#tabs [data-act="side"]'), `${u} phone: the tab Projects no longer opens the drawer`);
    check(w.eval(`tabItem('lists').go`) === 'l/' + I.a1, `${u} phone: the tab Projects leads to the page kept in Projects ` + w.eval(`tabItem('lists').go`));
    // in Projects already: the tab leads to the start page
    const pt = () => [...d.querySelectorAll('#tabs button')].find(b => /Projects/.test(b.textContent));
    check(pt()?.dataset.go === 'projects', `${u} phone: tapping Projects again = its start page ` + pt()?.dataset.go);
    click(w, pt());
    check(await until(() => w.location.hash === '#projects' && d.querySelector('#view .pstart')), `${u} phone: the start page of Projects opens in full view`);
    check(!d.querySelector('#side.open'), `${u} phone: the drawer stays closed`);
    check(/Projects/.test(d.querySelector('#top h1')?.textContent || ''), `${u} phone: the page head says Projects ` + d.querySelector('#top h1')?.textContent);
    // another area, then Projects: the page kept there (the start page now), not the drawer
    w.eval(`go('l/${I.b1}')`); await until(() => w.eval('S.route.key') === 'l:' + I.b1);
    w.eval(`go('cal')`); await until(() => w.eval('S.route.mod') === 'cal');
    check(w.eval(`tabItem('lists').go`) === 'l/' + I.b1, `${u} phone: from the calendar Projects leads back to the last project ` + w.eval(`tabItem('lists').go`));
    check(!w.eval(`tabItem('lists').act`), `${u} phone: Projects (also in "More") is a page, not the drawer`);
    // the office tab (area): kept page, tapping it again in the office = the office overview
    w.eval(`go('contacts')`); await until(() => w.eval('S.route.mod') === 'contacts');
    check(w.eval(`sbb_area()`) === 'office' && w.eval(`sbb_home('office')`) === 'office', `${u} phone: the office's start page is the office overview`);
    const ofm = w.eval(`(tabAreaItems().find(t => t.area === 'office') || {}).go`);
    check(ofm === 'contacts', `${u} phone: the office's entry keeps its last page ` + ofm);
    w.close();

    // ================= the computer: the bar of the areas
    w = await boot({user: u, hash: 'l/' + I.a1}); d = w.document;
    const rb = id => d.querySelector(`#srail .srb[data-sbb="${id}"]`);
    await until(() => rb('tasks'));
    check(rb('tasks')?.dataset.go === 'projects', `${u} computer: the Projects icon of the open area leads to the start page ` + rb('tasks')?.dataset.go);
    // the start page: the projects grouped by the sidebar's folders, in its order
    click(w, rb('tasks'));
    check(await until(() => w.location.hash === '#projects' && d.querySelector('#view .pstart')), `${u} computer: the start page opens`);
    await until(() => d.querySelector('#side .sg-lists [data-list]'));
    const page = [...d.querySelectorAll('#view .pstart [data-go^="l/"]')].map(b => b.dataset.go.slice(2));
    const side = [...d.querySelectorAll('#side .sg-lists .srow[data-list]')].map(b => b.dataset.list);
    check(page.length === 4 && page.join() === side.join(), `${u} computer: the start page lists the projects in the sidebar's order ` + JSON.stringify({page, side}));
    const heads = [...d.querySelectorAll('#view .pstart .ps-folder .psfold span')].map(x => x.textContent);
    check(heads.join('|') === 'Alpha|Alpha / Beta|Gamma', `${u} computer: grouped by the sidebar's folders ` + JSON.stringify(heads));
    const inF = (f, id) => [...d.querySelectorAll('#view .pstart .ps-folder')].find(s => s.querySelector('.psfold span')?.textContent === f)?.querySelector(`[data-go="l/${id}"]`);
    check(inF('Alpha', I.a1) && inF('Alpha / Beta', I.b1) && inF('Gamma', I.g1) && d.querySelector(`#view .pstart .ps-lists [data-go="l/${I.loose}"]`), `${u} computer: each project under its folder`);
    // a row opens its project; the bar keeps it for Projects (from another area)
    click(w, d.querySelector(`#view .pstart [data-go="l/${I.g1}"]`));
    check(await until(() => w.eval('S.route.key') === 'l:' + I.g1), `${u} computer: a row opens its project`);
    w.eval(`go('cal')`); await until(() => w.eval('S.route.mod') === 'cal' && rb('cal')?.classList.contains('on'));
    check(rb('tasks')?.dataset.go === 'l/' + I.g1, `${u} computer: from the calendar the Projects icon leads to the last project ` + rb('tasks')?.dataset.go);
    check(rb('cal')?.dataset.go === 'cal', `${u} computer: the open calendar's icon = its start`);
    // the office twice: first its kept page, then the office overview
    w.eval(`go('contacts')`); await until(() => w.eval('S.route.mod') === 'contacts');
    w.eval(`go('cal')`); await until(() => w.eval('S.route.mod') === 'cal' && rb('office'));
    check(rb('office')?.dataset.go === 'contacts', `${u} computer: the office icon leads to its last page ` + rb('office')?.dataset.go);
    click(w, rb('office'));
    await until(() => w.eval('S.route.mod') === 'contacts' && rb('office')?.classList.contains('on'));
    check(rb('office')?.dataset.go === 'office', `${u} computer: in the office its icon leads to the office overview ` + rb('office')?.dataset.go);
    click(w, rb('office'));
    check(await until(() => w.location.hash === '#office' && w.eval('S.route.mod') === 'office'), `${u} computer: tapping the office again = the office overview ` + w.location.hash);
    // the sidebar stays reachable over the menu button (phones: #top) and search / settings stay as they were
    check(w.eval(`tabItem('search').act`) === 'palette' && w.eval(`tabItem('settings').act`) === 'settings', `${u}: search and settings unchanged`);
    w.close();
  }

  // ================= an empty start page: a way to a new project
  await call(CA, 'POST', '/api/users', {username: 'nina', display_name: 'Nina', password: 'password123', email: 'nina@example.com', orgs: []});
  await call(await login('nina'), 'PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  {
    const w = await boot({user: 'nina', hash: 'projects'}), d = w.document;
    check(await until(() => d.querySelector('#view .pstart .empty [data-act="list-new"]')), 'nina: no projects: the empty start page offers "New project"');
    w.close();
  }

  // ================= Firefox: the start page at phone and computer width
  const ready = async (ev, expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  await firefox(async o => {
    const {cmd, ev, ctx, nav, shot} = o;
    await nav(B + 'static/icon.svg');
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'ff: login');
    for (const [vw, vh, tag] of [[390, 844, 'phone'], [1280, 860, 'computer']]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
      await nav(B + '#l/' + ids.alice.a1);
      await ready(ev, `!!S.booted && S.route.key === 'l:${ids.alice.a1}'`);
      // the Projects button of the open area: the start page
      const sel = tag === 'phone' ? `[...document.querySelectorAll('#tabs button')].find(b => /Projects/.test(b.textContent))` : `document.querySelector('#srail .srb[data-sbb="tasks"]')`;
      await ev(`(() => { const b = ${sel}; if (b) b.click(); return !!b; })()`);
      check(await ready(ev, `location.hash === '#projects' && !!document.querySelector('#view .pstart .psrow')`), `ff ${tag}: the Projects button opens the start page`);
      check(await ev(`!document.querySelector('#side.open')`), `ff ${tag}: the drawer stays closed`);
      const m = await ev(`(() => { const v = document.querySelector('#view'), rows = [...document.querySelectorAll('#view .psrow')]; return {over: v.scrollWidth - v.clientWidth, out: rows.filter(r => r.getBoundingClientRect().right > innerWidth + 1).length, h: Math.min(...rows.map(r => r.getBoundingClientRect().height))}; })()`);
      check(m && m.over <= 1 && m.out === 0 && m.h >= 43, `ff ${tag}: the start page fits, rows big enough to tap ` + JSON.stringify(m));
      await sleep(300);
      await shot(`p2417a-projects-${tag}.png`);
    }
  }, undefined);

  console.log(`p2417_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERR', e); process.exit(1); });
