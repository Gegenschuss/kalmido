// 2.149.0 part F (#2518, #2519): start files that belong to one module load on demand. Own container (start.sh).
// - layout: the moved files have no script tag, stand in LD_MODS (lazyload.js) and LAZY (sw.js); the helpers the start needs
//   stayed at start (milestone texts, CSV export, the "Tracked" click, Today's day plan timeline, the code chip)
// - jsdom (boot lazy: true = a fresh device, nothing loaded): a cold start loads none of them and throws nothing; each area
//   opens through its normal way in (route, dialog, menu action) and loads its module: budget (with life), Settings (other
//   servers), a list's print view, the event editor (invitations), a project's tracked time, environments, "Plan my day",
//   the list dialog's repository editor; no script error (window.onerror) on the way
// - language: German set -> the dialogs of the moved modules speak German
// - Firefox (skipped without firefox): the cold start fetches none of the moved files
// #2519: tools/check_lazy_calls.py (CI lint) is run here too, so a call into a lazy module without a guard fails this suite
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2149_f_ui', check: (c, w) => check(c, w), shots: 'P2149F_SHOTS', lazy: true});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2149F_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => {
  const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined});
  const t = await r.text(); let j = null; try { j = JSON.parse(t); } catch { j = t; }
  if (!r.ok) console.log('  ', method, url, r.status, String(t).slice(0, 200));
  return j;
};
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { let x; try { x = await fn(); } catch { x = false; } if (x) return x; await sleep(100); } try { return await fn(); } catch { return false; } };
const get = async u => (await fetch(B + u)).text();
// module -> its files (LD_MODS) that were start files before 2.149.0
const MOVED = {life: ['budget'], settings: ['servers'], listprint: ['listprint'], evinvite: ['evinvite'], projtime: ['projtime'],
  envs: ['envs'], dayplan: ['dpmodal'], gitrepo: ['gitrepo'], timesheet: ['timesheet'], team: ['absence', 'leave', 'dispo'], hubmail: ['hubmail'], msvview: ['msvview']};
const FILES = Object.values(MOVED).flat();

(async () => {
  // ================= #2519: the static check (no browser)
  let lz = '';
  try { lz = execFileSync('python3', [path.join(__dirname, '..', 'tools', 'check_lazy_calls.py'), '-v'], {encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe']}); } catch (e) { lz = 'FAILED ' + (e.stderr || e.message); }
  check(/0 unguarded; css variables: 0 undefined/.test(lz), 'check_lazy_calls.py: no unguarded call into a lazy module, no undefined CSS variable: ' + lz.trim().slice(0, 400));

  // ================= layout (no browser)
  const html = await get(''), sw = await get('sw.js'), ld = await get('static/js/lazyload.js');
  const tags = [...html.matchAll(/<script[^>]*src="\/static\/js\/([\w-]+)\.js/g)].map(m => m[1]);
  const LAZY = [...(sw.match(/const LAZY = \[(.*?)\];/s) || [, ''])[1].matchAll(/'\/static\/js\/([\w-]+)\.js'/g)].map(m => m[1]);
  const mods = (ld.match(/const LD_MODS = \{(.*?)\n\};/s) || [, ''])[1].replace(/\/\/[^\n]*/g, '');
  for (const [m, fs] of Object.entries(MOVED)) {
    const own = ((mods.match(new RegExp(`\\b${m}: \\[([^\\]]*)\\]`)) || [, ''])[1].match(/'[\w-]+'/g) || []).map(x => x.slice(1, -1));
    check(fs.every(f => own.includes(f) && LAZY.includes(f) && !tags.includes(f)), `module ${m}: ${fs.join(', ')} in LD_MODS + LAZY, no script tag (${own.join(' ')})`);
  }
  check(['quickadd', 'dayplan', 'git', 'projects', 'lazyload', 'calevents', 'time', 'clients', 'clientpage', 'render'].every(f => tags.includes(f)), 'the start parts of the split files stay at start');

  // ================= setup
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'});
  const st0 = await call('GET', '/api/state');
  const feats = (st0.settings.features || '').split(',').filter(Boolean);
  await call('PATCH', '/api/settings', {features: [...new Set([...feats, 'cal', 'budget', 'time', 'contracts', 'workload', 'dispo'])].join(',')});
  const LID = (await call('POST', '/api/lists', {name: 'Lazy project', kind: 'project'})).id;
  const TID = (await call('POST', '/api/tasks', {list_id: LID, title: 'Lazy task'})).id;
  check(LID > 0 && TID > 0, 'setup: a project list and a task');

  // ================= jsdom: a fresh device
  const ready = w => until(() => w.eval('!!(S.me && S.lists && S.lists.length)'), 100);
  const e0 = errs.length;
  let w = await boot({user: 'alice', lazy: true}), d = w.document;
  await ready(w);
  const loaded = () => [...d.querySelectorAll('script[src*="/static/js/"]')].map(s => (s.getAttribute('src').match(/\/static\/js\/([\w-]+)\.js/) || [])[1]).filter(Boolean);
  check(!FILES.some(f => loaded().includes(f)), 'cold start: none of the moved files loaded ' + loaded().filter(f => FILES.includes(f)).join(' '));
  check(['env_chipText', 'env_taskNote', 'lexCsv', 'tz_hit', 'dpTimeline', 'propDayplanHtml', 'codeChip', 'repoBoxHtml', 'tz_open', 'dayplanModal', 'repoWire', 'folderRepoModal', 'lexPrint', 'evf_modal', 'env_ovHtml', 'env_msHtml', 'viewBudget',
    'tsl_newsText', 'tsl_open', 'tsl_lockMark', 'tsl_card', 'tsl_printNote', 'ab2_tabs', 'ab2_dayHint', 'ab2_view', 'dp_view', 'dp_on', 'ab2_warnAssign']
    .every(n => w.eval(`typeof ${n}`) === 'function'), 'the start helpers and the stand-ins are there before the modules');
  check(w.eval(`env_chipText({id: 1, list_id: ${LID}, milestone_id: null})`) === '', 'a task row draws its milestone text without envs.js');
  // a task row and the task panel draw without the modules
  w.location.hash = '#l/' + LID; await until(() => d.querySelector('#view .trow'));
  check(!!d.querySelector('#view .trow'), 'the project list draws its rows');
  w.location.hash = '#t/' + TID; await until(() => d.querySelector('#detail .dtitle, #detail textarea, #detail [contenteditable]'));
  check(!!d.querySelector('#detail'), 'the task panel opens');

  // budget (module life): the route loads life.js + budget.js and draws the budget view
  w.eval(`go('budget')`);
  await until(() => loaded().includes('budget') && d.querySelector('#view .bgview') && !/^\s*Loading…\s*$/.test(d.querySelector('#view').textContent || ''), 100);
  check(['life', 'budget'].every(f => loaded().includes(f)) && loaded().indexOf('life') < loaded().indexOf('budget') && !!d.querySelector('#view .bgview'), 'budget: life.js then budget.js, the budget view drawn');
  w.eval(`go('today')`);

  // other servers (msvview.js): nothing linked -> the stand-ins answer like the module without a link, nothing is loaded
  check(w.eval(`msvvCount(3, 'today')`) === 3 && w.eval(`msvvMoveItem({}).length`) === 0 && w.eval(`msvvCalChips('2026-01-01').length`) === 0 && w.eval(`msvvSide()`) === '' && !loaded().includes('msvview') && w.eval(`!!S.msvv && S.msvv.search.q === ''`),
    'other servers: without a linked server the stand-ins answer, msvview.js is not loaded');
  w.location.hash = '#srv/7/1';
  await until(() => loaded().includes('msvview') && !/^\s*Loading…\s*$/.test(d.querySelector('#view')?.textContent || ''), 80);
  check(loaded().includes('msvview') && w.eval(`typeof msvvLink`) === 'function', 'other servers: a list of another server (route) loads msvview.js');
  w.location.hash = '#today'; await sleep(200);
  // e-mail filing (hubmail.js): the task's mail link is drawn at start, a client's card loads the module
  check(/data-hbmlnk="task:/.test(w.eval(`hbm_taskLinkHtml(taskById(${TID}))`)) && !loaded().includes('hubmail'), 'e-mail filing: the task panel draws its mail link without hubmail.js');
  check(w.eval(`hbm_clientHtml({id: 1})`) === '', 'e-mail filing: the client card stand-in draws nothing');
  await until(() => loaded().includes('hubmail') && w.eval(`typeof HBM`) === 'object');
  check(loaded().includes('hubmail') && w.eval(`typeof hbm_load`) === 'function', 'e-mail filing: hubmail.js loads for the client card');

  // the time page: its timesheet card loads timesheet.js
  w.eval(`go('time')`);
  await until(() => loaded().includes('timesheet') && d.querySelector('#view .timev'), 80);
  check(loaded().includes('timesheet') && !!d.querySelector('#view .timev'), 'time page: timesheet.js loads with it, the page is drawn');
  check(w.eval(`tsl_newsText({}, {act: 'approve', month: '2026-01'}, 'Bob', x => x)`).includes('Bob'), 'News: a timesheet text is there without the module');
  // the workload view: the tabs are there at start, "Absences" / "Disposition" load the team module
  w.eval(`go('workload')`);
  await until(() => d.querySelector('#view .ab2tabs'), 80);
  check(!!d.querySelector('#view .ab2tabs [data-v="abs"]') && !loaded().includes('absence'), 'workload: the tabs are drawn at start, absence.js not loaded yet');
  d.querySelector('#view .ab2tabs [data-v="abs"]')?.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, button: 0}));
  await until(() => ['absence', 'leave', 'dispo'].every(f => loaded().includes(f)) && d.querySelector('#view .ab2') && !/^\s*Loading…\s*$/.test((d.querySelector('#view .ab2')?.textContent || '').replace(/Workload|Absences|Disposition/g, '')), 100);
  check(['absence', 'leave', 'dispo'].every(f => loaded().includes(f)) && !!d.querySelector('#view .dash.ab2 .ab2tabs'), 'workload: the Absences tab loads absence.js, leave.js, dispo.js and draws the absences');
  d.querySelector('#view .ab2tabs [data-v="dispo"]')?.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, button: 0}));
  await until(() => d.querySelector('#view .dash.dp'), 60);
  check(!!d.querySelector('#view .dash.dp'), 'workload: the Disposition tab draws');
  w.eval(`WLV.tab = 'wl'; go('today')`);

  // Settings > Account: servers.js comes with the settings module
  await w.eval(`settingsModal('account')`);
  await until(() => d.querySelector('.smodal') && loaded().includes('servers'));
  check(loaded().includes('servers') && loaded().indexOf('servers') < loaded().indexOf('settings') && w.eval(`typeof msvDraw`) === 'function', 'settings: servers.js loads with the settings module');
  check(['timesheet', 'absence'].every(f => loaded().indexOf(f) >= 0 && loaded().indexOf(f) < loaded().indexOf('settings')) && w.eval(`typeof wt_setHtml`) === 'function', 'settings: the timesheet and team modules load before it (time zone rows, working week)');
  d.querySelectorAll('.smodal, .modal').forEach(m => m.remove());

  // a list's "Print" (listprint.js)
  w.eval(`lexPrint(${LID})`);
  await until(() => d.querySelector('.tsheet'));
  check(loaded().includes('listprint') && !!d.querySelector('.tsheet'), 'print view: listprint.js loads, the page is drawn');
  d.querySelectorAll('.tsheet').forEach(m => m.remove()); d.body.classList.remove('tsprint');

  // the event editor loads evinvite.js together with its people
  w.eval(`evEditor({})`);
  await until(() => loaded().includes('evinvite') && d.querySelector('.modal #ev-atts'));
  check(loaded().includes('evinvite') && !!d.querySelector('.modal #ev-atts'), 'event editor: evinvite.js loads with it, the editor is drawn');
  d.querySelectorAll('.modal').forEach(m => m.remove());

  // a project's tracked time (projtime.js): the click on "Tracked" is handled at start, the dialog loads the module
  w.eval(`tz_open([${LID}], 'Lazy project')`);
  await until(() => d.querySelector('.tzmodal'));
  check(loaded().includes('projtime') && !!d.querySelector('.tzmodal'), 'tracked time: projtime.js loads, the dialog opens');
  d.querySelectorAll('.modal').forEach(m => m.remove());

  // environments: the project page's block shows "Loading…" and loads envs.js
  const eh = w.eval(`env_ovHtml(listById(${LID}), true, true)`);
  check(/envbox/.test(eh), 'environments: the stand-in draws the same "Loading…" box');
  await until(() => loaded().includes('envs') && w.eval(`typeof ENV`) === 'object');
  check(loaded().includes('envs') && !/ld_later/.test(w.eval('String(env_ovHtml)')), 'environments: envs.js loaded, the real env_ovHtml replaced the stand-in');

  // "Plan my day" (dpmodal.js)
  w.eval(`dayplanModal('day')`);
  await until(() => d.querySelector('.modal.dpm'));
  check(loaded().includes('dpmodal') && !!d.querySelector('.modal.dpm'), 'Plan my day: dpmodal.js loads, the dialog opens');
  d.querySelectorAll('.modal').forEach(m => m.remove());

  // the list dialog's repository editor (gitrepo.js)
  w.eval(`listModal(${LID})`);
  await until(() => loaded().includes('gitrepo') && d.querySelector('#l-repos'));
  check(loaded().includes('gitrepo') && !!d.querySelector('#l-repos'), 'list dialog: the repository editor (gitrepo.js) loads');
  await until(() => !/Loading…/.test(d.querySelector('#l-repos')?.textContent || 'Loading…'), 40);
  check(!/Loading…/.test(d.querySelector('#l-repos')?.textContent || 'Loading…'), 'list dialog: the repository box is filled');
  d.querySelectorAll('.modal').forEach(m => m.remove());

  await sleep(300);
  const own = errs.slice(e0).filter(e => !/pdf\.min\.mjs|dynamic import|import\(\)|Could not parse CSS/i.test(e));
  check(!own.length, 'no script errors on the way: ' + own.join(' | '));
  w.close();

  // ================= language: German
  await call('PATCH', '/api/settings', {lang: 'de'});
  const e1 = errs.length;
  w = await boot({user: 'alice', lazy: true}); d = w.document; await ready(w);
  w.eval(`dayplanModal('day')`);
  await until(() => d.querySelector('.modal.dpm h3'));
  const h3 = d.querySelector('.modal.dpm h3')?.textContent || '';
  check(!!h3 && h3 === w.eval(`tr('Plan my day')`) && h3 !== 'Plan my day', 'German: the moved dialog speaks German: ' + h3);
  d.querySelectorAll('.modal').forEach(m => m.remove());
  w.eval(`tz_open([${LID}], 'x')`);
  await until(() => d.querySelector('.tzmodal h3'));
  check(/Erfasste|Zeit/.test(d.querySelector('.tzmodal h3')?.textContent || '') || (d.querySelector('.tzmodal h3')?.textContent || '').startsWith(w.eval(`tr('Tracked time')`)), 'German: the tracked time dialog: ' + (d.querySelector('.tzmodal h3')?.textContent || ''));
  const own2 = errs.slice(e1).filter(e => !/pdf\.min\.mjs|dynamic import|import\(\)|Could not parse CSS/i.test(e));
  check(!own2.length, 'German: no script errors: ' + own2.join(' | '));
  w.close();
  await call('PATCH', '/api/settings', {lang: 'en'});

  // ================= Firefox: a real browser with an empty cache
  await firefox(async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev('(() => { localStorage.clear(); return 1; })()');
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.ok)`), 'Firefox: login');
    await ev(`(window.onerror = null, window.__e = [], window.addEventListener('error', e => window.__e.push(String(e.message))), 1)`).catch(() => 0);
    await nav(B + '#l/' + LID);
    for (let i = 0; i < 40 && !(await ev('!!(window.S && S.me)').catch(() => false)); i++) await sleep(250);
    const fetched = await ev(`JSON.stringify(performance.getEntriesByType('resource').filter(e => /\\/static\\/js\\/(${FILES.join('|')})\\.js/.test(e.name) && e.startTime < 4500).map(e => e.name.replace(/^.*\\/static\\//, '')))`);
    check(fetched === '[]', 'Firefox: the start fetches none of the moved files ' + fetched);
    await ev(`(dayplanModal('day'), 1)`);
    for (let i = 0; i < 60 && !(await ev('!!document.querySelector(".modal.dpm")').catch(() => false)); i++) await sleep(150);
    check(await ev('!!document.querySelector(".modal.dpm")'), 'Firefox: "Plan my day" opens (dpmodal.js loaded on demand)');
  }, false);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
