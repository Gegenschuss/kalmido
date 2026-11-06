// 2.609.0 B UI test, own container (start.sh), jsdom, invented data only:
// kalmido-suite: fresh
// #4613 the lists an area keeps its entries in (Read later, a contract's list, a trip) are no projects:
// - not in the sidebar, not in the list picker ("Move to project", sideOrder: filters, roadmap, ...), not in the palette
// - #l/<id> of the Read later list opens Read later, of the contracts' list Home & life; a trip's list stays the trip view
// - Read later has no "Show as project" any more; their tasks stay in Today
// #4509 the sidebar is drawn anew only when what it shows changed:
// - render() without a change keeps the nodes (identity), another view only moves the marks "on" / aria-current in place
// - a renamed project and a new count draw it anew
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login, until: until0} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const until = fn => until0(fn, {timeout: 15000, step: 100});
const today = require('./boot').testNow().toLocaleDateString('sv-SE', {timeZone: 'Europe/Berlin'});  // the server's day (Berlin)

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,reading,contracts,travel,stats,review'});
  const P = (await call('POST', '/api/lists', {name: 'Garden shed'})).id;
  const P2 = (await call('POST', '/api/lists', {name: 'Bike repair'})).id;
  const rd = await call('POST', '/api/reading', {url: 'https://example.com/pelicans', title: 'All about pelicans'});
  const ct = await call('POST', '/api/life/contracts', {name: 'Walrus insurance', cost: 10, per: 'month', ends: today});
  const tp = await call('POST', '/api/life/trips', {name: 'Summer on the lake', from: today, to: today, packing: ''});
  const RL = rd.list_id, CL = ct.list_id, TL = tp.list_id;
  check(P && P2 && RL && CL && TL, 'setup: two projects, Read later, a contract, a trip ' + JSON.stringify([P, P2, RL, CL, TL]));
  await call('POST', '/api/tasks', {title: 'Pay the walrus', list_id: CL, due: today});

  let w = await boot({user: 'alice', hash: 'today'}), d = w.document;
  await until(() => d.querySelector(`#side [data-list="${P}"]`));
  check([RL, CL, TL].every(id => !d.querySelector(`#side [data-list="${id}"]`)), '#4613: no store list of an area in the sidebar');
  const ord = w.eval('sideOrder().map(l => l.id)');
  check(ord.includes(P) && ![RL, CL, TL].some(id => ord.includes(id)), '#4613: sideOrder (filters, roadmap, pickers) without them ' + JSON.stringify(ord));
  w.eval(`tch_listPicker(document.body, {pick: () => {}})`);
  const labels = await until(() => { const m = [...d.querySelectorAll('#pop .tch-l')].map(b => b.textContent.trim()); return m.length && m; });
  check(labels && labels.some(x => /Garden shed/.test(x)) && !labels.some(x => /Read later|Walrus|Summer on the lake/.test(x)), '#4613: "Move to project" without them ' + JSON.stringify(labels));
  w.eval('closePop()');
  check(w.eval(`[...S.tasks.values()].some(t => t.title === 'Pay the walrus')`) && /Pay the walrus/.test(d.querySelector('#view')?.textContent || ''), '#4613: their tasks stay in Today');

  w.location.hash = '#l/' + RL;
  check(await until(() => w.eval('S.route.mod') === 'reading') && w.location.hash === '#reading', '#4613: #l/<Read later> opens Read later');
  await until(() => d.querySelector('#view .rlview .bmbar'));
  check(!d.querySelector('#view .rlview a[href^="#l/"]') && !/Show as project/.test(d.querySelector('#view').textContent), '#4613: no "Show as project"');
  w.location.hash = '#l/' + CL;
  check(await until(() => w.eval('S.route.mod') === 'life') && w.location.hash === '#life', '#4613: #l/<contracts> opens Home & life');
  w.location.hash = '#l/' + TL;
  check(await until(() => w.eval('S.route.key') === 'l:' + TL), '#4613: a trip list stays its trip view');

  // ---- #4509
  w.location.hash = '#today';
  await until(() => w.eval('S.route.key') === 'today' && d.querySelector('#side .srow.on[data-go="today"]'));
  const row0 = d.querySelector(`#side [data-list="${P}"]`), first0 = d.querySelector('#side').firstElementChild;
  w.eval('render()'); w.eval('render()');
  check(d.querySelector(`#side [data-list="${P}"]`) === row0 && d.querySelector('#side').firstElementChild === first0, '#4509: render() without a change keeps the nodes');
  w.location.hash = '#tomorrow';
  await until(() => w.eval('S.route.key') === 'tomorrow');
  check(d.querySelector(`#side [data-list="${P}"]`) === row0 && d.querySelector('#side .srow.on[data-go="tomorrow"]') && !d.querySelector('#side .srow.on[data-go="today"]'), '#4509: another view moves the mark in place');
  w.location.hash = '#l/' + P2;
  await until(() => w.eval('S.route.key') === 'l:' + P2);
  check(d.querySelector(`#side [data-list="${P}"]`) === row0 && d.querySelector(`#side .srow.on[data-list="${P2}"]`) && !d.querySelector('#side .srow.on[data-go="tomorrow"]'), '#4509: a project opened: the same nodes, its row lit');
  w.eval(`listById(${P}).name = 'Garden house'; render()`);
  const row1 = d.querySelector(`#side [data-list="${P}"]`);
  check(row1 && row1 !== row0 && /Garden house/.test(row1.textContent), '#4509: a renamed project draws the sidebar anew');
  await w.eval(`api('POST', '/api/tasks', {title: 'Oil the hinges', list_id: ${P}}).then(t => { putTask(t); render(); })`);
  const row2 = await until(() => { const x = d.querySelector(`#side [data-list="${P}"]`); return x && x !== row1 && x; });
  check(row2 && /1/.test(row2.querySelector('.c')?.textContent || ''), '#4509: a new count draws it anew ' + (row2?.querySelector('.c')?.textContent || ''));
  w.close();

  console.log(F.length ? 'FAILED ' + F.length : 'OK ' + ok); process.exit(F.length ? 1 : 0);
})();
