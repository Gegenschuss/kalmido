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
  check(w.eval('SIDE_VIEW_KEYS.join()') === 'cal,timeline,matrix,overview,workload,notes' /* 2.45.0 (#1516): + Notes */ && /^cal,timeline,matrix/.test(keys('.sg-views').join()), 'Views: calendar, timeline, matrix, project status, workload ' + keys('.sg-views').join());
  // 2.48.0 (#1207): + the file store after Office (off here: "files" is not in ALL)
  check(w.eval('SIDE_AREA_KEYS.join()') === 'office,ablage,wiki,time,habits,review,life,agents' /* 2.49.0 (#1199): + knowledge pages */ && /^office,time,habits,review,life/.test(keys('.sg-areas').join()), 'Areas: office, time, habits, review, home, agents ' + keys('.sg-areas').join());
  const names = [...d.querySelectorAll('#side .sg-areas .srow .n')].map(x => x.textContent).join();
  check(/^Office,Time,Habits,Review,Home/.test(names), 'the area names ' + names);
  check(!d.querySelector('#side .sg-clients') && !d.querySelector('#side [data-go="pomo"]') && !d.querySelector('#side [data-go="family"]'), 'no clients group, no own rows for the parts');

  // ================= an area page with tabs
  click(w, d.querySelector('#side [data-mgside="time"]'));
  await until(() => w.eval('S.route.mod') === 'time' && d.querySelector('#view .mgtabs'));
  const tabs = () => [...d.querySelectorAll('#view .mgtabs [role="tab"]')].map(b => b.dataset.go + (b.getAttribute('aria-selected') === 'true' ? '*' : '')).join();
  check(tabs() === 'time*,pomo', 'Time: the tabs Time tracking (on) and Focus timer ' + tabs());
  check(/Time/.test(d.querySelector('#top h1')?.textContent || ''), 'the header shows the area');
  click(w, d.querySelector('#view .mgtabs [data-go="pomo"]'));
  await until(() => w.eval('S.route.mod') === 'pomo');
  check(tabs() === 'time,pomo*' && d.querySelector('#side [data-mgside="time"].on'), 'the focus timer tab: the area row stays lit');
  check(d.querySelector('#side [data-mgside="time"]').dataset.go === 'pomo', 'the area remembers its last tab');
  w.eval(`go('review')`); await until(() => w.eval('S.route.mod') === 'review');
  check(tabs() === 'review*,stats', 'Review: Review & journal and Statistics ' + tabs());
  w.eval(`go('life')`); await until(() => w.eval('S.route.mod') === 'life');
  check(tabs() === 'life*,family', 'Home: Home & life and Family ' + tabs());
  w.eval(`go('contacts')`); await until(() => w.eval('S.route.mod') === 'contacts');
  // 2.87.9 (#1917): the area Office has its menu with four groups; without the office module: Clients and Contacts under Sell
  const ofm = () => [...d.querySelectorAll('#view .ofmenu [data-ofm]')].map(b => b.dataset.go + (b.getAttribute('aria-current') === 'page' ? '*' : '')).join();
  check(ofm() === 'clients,contacts*' && /Sell/.test(d.querySelector('#view .ofmenu .ofmgh')?.textContent || ''), 'Office (office module off): Clients and Contacts in the group Sell ' + ofm());
  // ================= old links
  for (const [h, mod, area] of [['stats', 'stats', 'review'], ['family', 'family', 'life'], ['clients', 'clients', 'office'], ['pomo', 'pomo', 'time']]) {
    w.eval(`location.hash = '#${h}'`); await until(() => w.eval('S.route.mod') === mod);
    check(w.eval('S.route.mod') === mod && d.querySelector(`#side [data-mgside="${area}"].on`) && d.querySelector(area === 'office' ? `#view .ofmenu [data-go="${mod}"][aria-current="page"]` : `#view .mgtabs [data-go="${mod}"][aria-selected="true"]`), `#${h}: the area ${area} on its tab`);  // 2.87.9 (#1917): the office menu
  }
  check(!errs.length, 'no script errors ' + errs.join(' | ')); errs.splice(0);
  w.close();

  // a part that is off: its old link opens the other tab; one part on = no tabs
  await call('PATCH', '/api/settings', {features: ALL.split(',').filter(f => f !== 'pomo').join(',')});
  w = await boot({user: 'alice', hash: 'pomo'}); d = w.document; await sleep(500);
  check(w.eval('S.route.mod') === 'time' && !d.querySelector('#view .mgtabs'), '#pomo with the focus timer off: time tracking, no tabs');
  w.close();

  // ================= Settings > Modules: one switch per area
  await call('PATCH', '/api/settings', {features: ALL});
  w = await boot({user: 'alice', hash: 'inbox'}); d = w.document; await sleep(500);
  w.eval(`settingsModal('modules')`); await until(() => d.querySelector('.smodal [data-mgarea="review"]'));
  let md = d.querySelector('.smodal');
  check(['office', 'time', 'review', 'life'].every(k => md.querySelector(`input[data-mgarea="${k}"]`)?.checked), 'four area switches, on');
  check(md.querySelector('[data-mgrow="review"] [data-feat="stats"]') && md.querySelector('[data-mgrow="review"] [data-feat="review"]') && md.querySelector('[data-mgrow="time"] [data-feat="pomo"]') && md.querySelector('[data-mgrow="office"] [data-feat="contacts"]') && md.querySelector('[data-mgrow="life"] [data-feat="family"]'), 'the parts below their area');
  const sw = md.querySelector('input[data-mgarea="review"]'); sw.checked = false; change(w, sw);
  let st = await until(async () => { const x = await call('GET', '/api/state'); return !x.settings.features.split(',').includes('stats') && x; });
  st = st || await call('GET', '/api/state'); await sleep(600);
  md = d.querySelector('.smodal') || md;
  check(!st.settings.features.split(',').includes('stats') && !st.settings.features.split(',').includes('review'), 'off: both modules off on the server (the old keys)');
  check(!md.querySelector('[data-feat="stats"]').checked && md.querySelector('[data-mgrow="review"]').classList.contains('off'), 'the part switches follow');
  w.eval('render()'); await sleep(200);
  check(!d.querySelector('#side [data-mgside="review"]'), 'the area is gone from the sidebar');
  w.eval(`histStep('undo')`); await until(() => w.eval(`feat('stats') && feat('review')`));
  check(w.eval(`feat('stats') && feat('review')`), 'one Undo brings both back');
  // one part on again = the area on
  const ps = md.querySelector('[data-feat="stats"]');
  if (!ps.checked) { ps.checked = true; change(w, ps); }
  md.remove(); w.eval(`settingsModal('modules')`); await until(() => d.querySelector('.smodal [data-mgarea="review"]')); md = d.querySelector('.smodal');
  const fp = md.querySelector('[data-feat="family"]'); fp.checked = false; change(w, fp); await until(() => !w.eval(`feat('family')`));
  check(md.querySelector('input[data-mgarea="life"]').checked, 'Home stays on while Home & life is on (Family off)');
  await sleep(800); d.querySelector('.smodal')?.remove();
  check(!errs.length, 'no script errors (settings) ' + errs.join(' | ')); errs.splice(0);
  w.close();

  // ================= an arrangement from before 2.44.0
  await call('PATCH', '/api/settings', {features: ALL, sidebar: JSON.stringify({order: [], hidden: ['e:time', 'e:pomo', 'e:stats']})});
  w = await boot({user: 'alice', hash: 'inbox', mobile: true, ls: {'tasks.tabbar': JSON.stringify(['s:inbox', 'm:pomo', 'time', 'stats', 'm:family'])}}); d = w.document; await sleep(500);
  check(JSON.stringify(w.eval('tabIds()')) === JSON.stringify(['s:inbox', 'a:time', 'a:review', 'a:life']), 'tab bar: the old tabs become the areas, no doubles ' + JSON.stringify(w.eval('tabIds()')));
  check([...d.querySelectorAll('#tabs button')].map(b => b.textContent).join().includes('Time'), 'the tab "Time" in the bar');
  check(!d.querySelector('#side [data-mgside="time"]') && d.querySelector('#side [data-mgside="review"]'), 'sidebar: both parts of Time hidden = Time hidden; Review (only Statistics hidden) stays');
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
