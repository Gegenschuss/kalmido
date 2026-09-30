// 1.8.1 UI tests (jsdom), fresh DB: the Inbox first and as the start view (sidebar, phone drawer, tab choices, palette,
// the Tasks tab, no hash / unknown hash, the last view of the device still wins, a closed list falls back to the Inbox,
// the tour text); "Show completed" without the global switch (a view without its own choice shows) and the calendar's
// own toggle is in p151_ui.js; the centered sign-in / setup screens in setup_ui.js.
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const ALL = 'cal,timeline,matrix,habits,pomo,kanban,paperless,collab,stats,time,progress,deps,fields';
const START = {'tasks.lastKey': null};  // boot.js seeds "today" for the older suites; null = a first start on this device

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {features: ALL});
  const WORK = (await call('POST', '/api/lists', {name: 'Work'})).id;
  await call('POST', '/api/tasks', {title: 'In the inbox'});

  // desktop, first start on this device: the Inbox
  let w = await boot({user: 'alice', ls: START}), d = w.document;
  check(w.eval('S.route.key') === 'inbox' && w.location.hash === '', 'no hash, first start: the Inbox (' + w.eval('S.route.key') + ')');
  check(/In the inbox/.test(d.querySelector('#view').textContent), 'the Inbox view is shown');
  const side = [...d.querySelectorAll('#side > .srow')].map(r => r.dataset.go);
  check(side[0] === 'inbox' && side.slice(1, 5).join() === 'today,tomorrow,week,doable', 'sidebar: Inbox first, then Today ... Now doable: ' + side);
  check(d.querySelector('#side > .srow[data-go="inbox"]').classList.contains('on'), 'sidebar: Inbox is the open view');
  check(w.eval('SMART_TABS[0]') === 'inbox' && w.eval('Object.keys(SMART)[0]') === 'inbox', 'tab choices + smart list order start with the Inbox');
  w.eval('openPalette()'); await sleep(100);
  const views = w.eval(`palAll().filter(x => x.id.startsWith('v:')).map(x => x.id)`);
  check(views.indexOf('v:inbox') === 0 && views.indexOf('v:inbox') < views.indexOf('v:today'), 'palette: Inbox is the first view: ' + views.slice(0, 4));
  w.eval('closePalette()');
  check(w.eval(`modHash('tasks')`) === 'inbox', 'the Tasks tab / rail entry opens the Inbox');
  // the last view of the device still wins
  w.eval(`go('week')`); await sleep(300);
  check(w.eval(`LS.get('lastKey')`) === 'week' && w.eval(`modHash('tasks')`) === 'week', 'last task view remembered');
  // a list that goes away -> the Inbox (was Today)
  await w.eval('load()'); w.eval(`go('l/${WORK}')`); await sleep(300);
  await w.eval(`listArchive(${WORK}, true)`); await sleep(600);
  check(w.eval('S.route.key') === 'inbox', 'open list archived: back to the Inbox (' + w.eval('S.route.key') + ')');
  // unknown hash -> the Inbox
  w.location.hash = 'nonsense'; await sleep(300);
  check(w.eval('S.route.key') === 'inbox', 'unknown hash: the Inbox');
  // tour text
  check(/Inbox comes first/.test(w.eval(`tourSteps()[0].d`)), 'tour: the first card names the Inbox');
  w.close();

  // a device that was on a view before keeps it
  w = await boot({user: 'alice', ls: {'tasks.lastKey': '"tomorrow"'}}); d = w.document;
  check(w.eval('S.route.key') === 'tomorrow', 'lastKey of the device wins over the default');
  w.close();

  // phone: drawer + default tab bar
  w = await boot({user: 'alice', mobile: true, ls: START}); d = w.document;
  check(w.eval('S.route.key') === 'inbox', 'phone: starts on the Inbox');
  check(d.querySelector('#side > .srow')?.dataset.go === 'inbox', 'phone drawer: Inbox first');
  const tasksTab = d.querySelector('#tabs [data-go]');
  check(tasksTab && tasksTab.dataset.go === 'inbox' && tasksTab.classList.contains('on'), 'default tab bar: Tasks opens the Inbox: ' + tasksTab?.dataset.go);
  w.close();

  // German
  await call('PATCH', '/api/settings', {lang: 'de'});
  w = await boot({user: 'alice', ls: START}); d = w.document;
  check(/Eingang steht oben/.test(w.eval(`tr(tourSteps()[0].d)`)) && d.querySelector('#side > .srow .n')?.textContent === 'Eingang', 'German: tour text + sidebar');
  w.close();

  const bad = errs.filter(e => !/Could not parse CSS/.test(e));
  check(!bad.length, 'no script errors: ' + bad.slice(0, 3).join(' | '));
  console.log(`\np181_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
