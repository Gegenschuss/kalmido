// 2.44.0 UI tests, part D (#1187): the areas, own container (start.sh), jsdom.
// - the sidebar: Views = Calendar, Timeline, Matrix, Project status, Workload; Areas = Office, Time, Habits, Review, Home, Agents
//   (one row per area, no own group for the clients, the old rows Focus timer / Statistics / Contacts / Family are gone)
// - an area's page has tabs for its switched-on parts; a tab opens the part, the area row stays lit, the area remembers its tab
// - old links (#pomo, #stats, #family, #contacts, #clients) open the area on that tab; a part that is off opens another tab
// - Settings > Modules: ONE switch per area (on while one part is on), its parts below it; the area switch turns all parts on /
//   off in one step with one Undo; the old module keys stay what is stored (2.43.1 reads them)
// - an arrangement from before: the tab bar (m:pomo, stats, time) becomes the area tabs, hidden sidebar entries of both parts
//   hide the area; the first-run setup offers the areas
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const change = (w, el) => el.dispatchEvent(new w.Event('change', {bubbles: true}));
const ALL = 'cal,timeline,matrix,habits,pomo,collab,stats,time,progress,agents,comments,contacts,clients,workload,review,family,contracts,home';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: ALL});
  // two projects: the project status shows (Views)
  for (const n of ['Harbour', 'Bridge']) await call('POST', '/api/lists', {name: n, kind: 'project'});

  // ================= the sidebar
  let w = await boot({user: 'alice', hash: 'inbox', ls: {'tasks.sideOpenG': JSON.stringify(['views', 'areas'])}}), d = w.document;
  await sleep(500);
  const keys = sel => [...d.querySelectorAll(`#side ${sel} .srow.smod`)].map(b => b.dataset.mgside || b.dataset.go || (b.dataset.act || '').replace('side-', ''));
  const rk = () => [...d.querySelectorAll('#srail .srbs [data-sbb]')].map(b => b.dataset.sbb);  // 2.152.2 (#2622): the areas are icons of the bar
  check(w.eval('SIDE_VIEW_KEYS.join()') === 'cal,timeline,matrix,overview,workload,notes' /* 2.45.0 (#1516): + Notes */ && /^timeline,matrix/.test(keys('.sg-views').join()), 'Views: timeline, matrix, all projects, workload ' + keys('.sg-views').join());  // 2.152.2 (#2622): the calendar is an icon of the bar
  // 2.48.0 (#1207): + the file store after Office (off here: "files" is not in ALL)
  check(w.eval('SIDE_AREA_KEYS.join()') === 'office,ablage,wiki,sheets,time,habits,review,life,reading,agents' /* 2.49.0 (#1199): + knowledge pages; 2.89.0 (#1916): + tables; 2.172.0 (#2679): + Reading */ && !d.querySelector('#side .sg-areas') && /^home,tasks,cal,office,time,review,life,.*habits/.test(rk().join()), 'Areas: the icons of the bar ' + rk().join());  // 2.364.0 (#3031): Start first  // 2.152.2 (#2622): no group Areas in #side, one icon per area in #srail
  const names = [...d.querySelectorAll('#srail [data-sbb] .srbn')].map(x => x.textContent).join();  // 2.152.2 (#2622)
  check(/^Start,Projects,Calendar,Contacts,Time,Review,Home/.test(names) /* 2.208.0 (#2771): the area Tasks is called Projects; 2.364.0 (#3031): Start first, (#3018): Office & finance off (not in ALL) = Contacts */ && /Areas/.test(d.querySelector('#srail').getAttribute('aria-label') || ''), 'the area names ' + names);  // 2.152.2 (#2622): the bar is called Areas
  check(!d.querySelector('#side .sg-clients') && !d.querySelector('#side [data-go="pomo"]') && !d.querySelector('#side [data-go="family"]'), 'no clients group, no own rows for the parts');

  // ================= an area page with tabs
  click(w, d.querySelector('#srail [data-sbb="time"]'));  // 2.152.2 (#2622): the area icon in the bar
  await until(() => w.eval('S.route.mod') === 'time' && d.querySelector('#view .mgtabs [data-go]'));  // 2.224.0 (#2817): Time has no panel any more, its parts are tabs on top again
  const tabs = () => [...d.querySelectorAll('#view .mgtabs [data-go]')].map(b => b.dataset.go + (b.getAttribute('aria-selected') === 'true' ? '*' : '')).join();  // 2.224.0 (#2817): tabs instead of panel entries
  const sideTabs = () => [...d.querySelectorAll('#side [data-sbbpart]')].map(b => b.dataset.sbbpart + (b.getAttribute('aria-current') === 'page' ? '*' : '')).join();  // 2.152.2 (#2618): areas with a panel
  check(tabs() === 'time*,pomo' && !d.querySelector('#side [data-sbbpart]'), 'Time: the tabs Time tracking (on) and Focus timer, no panel entries ' + tabs());  // 2.224.0 (#2817)
  check(/Time tracking/.test(d.querySelector('#top h1')?.textContent || '') && d.querySelector('#app').classList.contains('sbb-nopan'), 'the header shows the part, no panel');  // 2.224.0 (#2817)
  click(w, d.querySelector('#view .mgtabs [data-go="pomo"]'));  // 2.224.0 (#2817)
  await until(() => w.eval('S.route.mod') === 'pomo');
  check(tabs() === 'time,pomo*' && d.querySelector('#srail [data-sbb="time"].on'), 'the focus timer entry: the area icon stays lit');  // 2.152.2 (#2622)
  // 2.417 (#3559): the area keeps its last page (sbb_target); the button of the OPEN area leads to its start page
  check(w.eval(`sbb_target('time')`) === 'pomo' && d.querySelector('#srail [data-sbb="time"]').dataset.go === 'time', 'the area remembers its last page');  // 2.152.2 (#2622)
  w.eval(`go('review')`); await until(() => w.eval('S.route.mod') === 'review');
  check(tabs() === 'review*,stats', 'Review: Review & journal and Statistics ' + tabs());
  check(d.querySelector('#srail [data-sbb="time"]').dataset.go === 'pomo', 'another area open: the Time button leads back to its last page');  // 2.417 (#3559)
  w.eval(`go('life')`); await until(() => w.eval('S.route.mod') === 'life');
  check(sideTabs() === 'life*,family', 'Home: Home & life and Family ' + sideTabs());  // 2.224.0 (#2817): Home keeps its panel
  w.eval(`go('contacts')`); await until(() => w.eval('S.route.mod') === 'contacts');
  // 2.87.9 (#1917): the area Office has its menu with four groups; without the office module: Clients and Contacts under Sell
  const ofm = () => [...d.querySelectorAll('#side [data-ofm]')].map(b => b.dataset.go + (b.getAttribute('aria-current') === 'page' ? '*' : '')).join();
  check(ofm() === 'clients,contacts*' && /Sell/.test(d.querySelector('#side [data-ofmg] .sgt > span')?.textContent || '') && !d.querySelector('#view .ofrail'), 'Office (office module off): Clients and Contacts in the group Sell ' + ofm());  // 2.98.0 (#2180): the office rail; 2.152.2 (#2617): the points in the panel
  // ================= old links
  for (const [h, mod, area] of [['stats', 'stats', 'review'], ['family', 'family', 'life'], ['clients', 'clients', 'office'], ['pomo', 'pomo', 'time']]) {
    w.eval(`location.hash = '#${h}'`); await until(() => w.eval('S.route.mod') === mod);
    check(w.eval('S.route.mod') === mod && d.querySelector(`#srail [data-sbb="${area}"].on`) && d.querySelector(area === 'office' ? `#side [data-ofm][data-go="${mod}"][aria-current="page"]` : ['review', 'time'].includes(area) ? `#view .mgtabs [data-go="${mod}"][aria-selected="true"]` /* 2.224.0 (#2817) */ : `#side [data-sbbpart="${mod}"][aria-current="page"]`), `#${h}: the area ${area} on its entry`);  // 2.87.9 (#1917): the office menu; 2.98.0 (#2180): the office rail; 2.152.2 (#2617 #2618 #2622): bar icon + panel entry
  }
  check(!errs.length, 'no script errors ' + errs.join(' | ')); errs.splice(0);
  w.close();

  // a part that is off: its old link opens the other tab; one part on = no tabs
  await call('PATCH', '/api/settings', {features: ALL.split(',').filter(f => f !== 'pomo').join(',')});
  w = await boot({user: 'alice', hash: 'pomo'}); d = w.document; await sleep(500);
  check(w.eval('S.route.mod') === 'time' && !d.querySelector('#view .mgtabs') && !d.querySelector('#side [data-sbbpart]'), '#pomo with the focus timer off: time tracking, no tabs, no panel');  // 2.224.0 (#2817): no panel  // 2.152.2 (#2618): the panel lists the one part
  w.close();

  // ================= Settings > Modules: one switch per area
  await call('PATCH', '/api/settings', {features: ALL});
  w = await boot({user: 'alice', hash: 'inbox'}); d = w.document; await sleep(500);
  w.eval(`settingsModal('modules')`); await until(() => d.querySelector('.smodal [data-mgarea="review"]'));
  let md = d.querySelector('.smodal');
  // 2.171.0 (#2676): an area's switch is on only with every part on - ALL has no office / budget / feeds ..., so Office and Home are half (was: four on)
  check(['time', 'review'].every(k => md.querySelector(`input[data-mgarea="${k}"]`)?.checked) && ['office', 'life'].every(k => { const x = md.querySelector(`input[data-mgarea="${k}"]`); return x && !x.checked && x.indeterminate; }), 'four area switches: two on, two half');
  check(md.querySelector('[data-mgrow="review"] [data-feat="stats"]') && md.querySelector('[data-mgrow="review"] [data-feat="review"]') && md.querySelector('[data-mgrow="time"] [data-feat="pomo"]') && md.querySelector('[data-mgrow="office"] [data-feat="contacts"]') && md.querySelector('[data-mgrow="life"] [data-feat="family"]'), 'the parts below their area');
  const sw = md.querySelector('input[data-mgarea="review"]'); sw.checked = false; change(w, sw);
  let st = await until(async () => { const x = await call('GET', '/api/state'); return !x.settings.features.split(',').includes('stats') && x; });
  st = st || await call('GET', '/api/state'); await sleep(600);
  md = d.querySelector('.smodal') || md;
  check(!st.settings.features.split(',').includes('stats') && !st.settings.features.split(',').includes('review'), 'off: both modules off on the server (the old keys)');
  check(!md.querySelector('[data-feat="stats"]').checked && md.querySelector('[data-mgrow="review"]').classList.contains('off'), 'the part switches follow');
  w.eval('render()'); await sleep(200);
  check(!d.querySelector('#srail [data-sbb="review"]'), 'the area is gone from the bar');  // 2.152.2 (#2622)
  w.eval(`histStep('undo')`); await until(() => w.eval(`feat('stats') && feat('review')`));
  check(w.eval(`feat('stats') && feat('review')`), 'one Undo brings both back');
  // one part on again = the area on
  const ps = md.querySelector('[data-feat="stats"]');
  if (!ps.checked) { ps.checked = true; change(w, ps); }
  md.remove(); w.eval(`settingsModal('modules')`); await until(() => d.querySelector('.smodal [data-mgarea="review"]')); md = d.querySelector('.smodal');
  const fp = md.querySelector('[data-feat="family"]'); fp.checked = false; change(w, fp); await until(() => !w.eval(`feat('family')`));
  // 2.171.0 (#2676): Home stays on (not dimmed) but its switch shows "partly" - on only with every part on (was: on)
  { const l = md.querySelector('input[data-mgarea="life"]'); check(!l.checked && l.indeterminate && !l.closest('.modrow').classList.contains('off'), 'Home stays on while Home & life is on (Family off), its switch half'); }
  // 2.80.3: the module switch reloads the state and routes again behind the screen - let it finish before the window closes (slow CI)
  await until(async () => { const f = ((await call('GET', '/api/state')).settings?.features || '').split(','); return !f.includes('family') && f.includes('stats'); });
  await sleep(2000); d.querySelector('.smodal')?.remove();
  check(!errs.length, 'no script errors (settings) ' + errs.join(' | ')); errs.splice(0);
  w.close();

  // ================= an arrangement from before 2.44.0
  await call('PATCH', '/api/settings', {features: ALL, sidebar: JSON.stringify({order: [], hidden: ['e:time', 'e:pomo', 'e:stats']})});
  w = await boot({user: 'alice', hash: 'inbox', mobile: true, ls: {'tasks.tabbar': JSON.stringify(['s:inbox', 'm:pomo', 'time', 'stats', 'm:family'])}}); d = w.document; await sleep(500);
  check(JSON.stringify(w.eval('tabIds()')) === JSON.stringify(['s:inbox', 'a:time', 'a:review', 'a:life']), 'tab bar: the old tabs become the areas, no doubles ' + JSON.stringify(w.eval('tabIds()')));
  check([...d.querySelectorAll('#tabs button')].map(b => b.textContent).join().includes('Time'), 'the tab "Time" in the bar');
  check(!d.querySelector('#side .sbmr [data-sbb="time"]') && d.querySelector('#side .sbmr [data-sbb="review"]'), 'sidebar: both parts of Time hidden = Time hidden; Review (only Statistics hidden) stays');  // 2.196.0 (#2737): on the phone the areas are the drawer's row of icons (was: rows data-mgside)
  w.close();
  await call('PATCH', '/api/settings', {sidebar: ''});

  // ================= the first-run setup offers the areas; the server keeps the journal and Home & life of the admin
  w = await boot({user: 'alice', hash: 'inbox'}); d = w.document; await sleep(300);
  const su = w.eval('[...SETUP_MAIN, ...SETUP_MODS].map(x => x[0]).join()');
  check(['a:time', 'a:review', 'a:life', 'a:office'].every(k => su.split(',').includes(k)) && !['pomo', 'stats', 'family', 'contacts', 'time'].some(k => su.split(',').includes(k)), 'setup: the areas instead of their modules ' + su);
  check(w.eval(`SETUP_PRESETS.team.off.includes('a:life') && !SETUP_PRESETS.team.off.includes('a:time') && !SETUP_PRESETS.home.off.includes('a:life')`), 'setup: the purposes pick their areas');
  w.close();
  const r = await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['cal', 'time', 'pomo', 'review', 'stats', 'family', 'contracts']});
  st = await call('GET', '/api/state');
  const fs = st.settings.features.split(',');
  check(r.status === 200 && ['review', 'stats', 'family', 'contracts', 'pomo'].every(k => fs.includes(k)) && !fs.includes('health'), 'setup: Review and Home with their modules for the admin ' + st.settings.features);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
