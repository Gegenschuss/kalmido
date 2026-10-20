// 2.144.0 UI tests (part C, #2418 #2414), own container (start.sh). jsdom:
//   #2418 the start page: the block Today shows today's events on top (rows of "Events today"), the tasks below; only events
//   and no task = no "Nothing left for today."; the block setting "Show events" off hides them; the summary line names the
//   running jobs ("1 agent working (3 jobs)", none without jobs) and an overdue task of another workspace with its name.
//   #2414 a list grouped by a custom field: select = one group per option in the option order, "No value" last, no section
//   heads; text = by value; a group folds and stays folded (localStorage collapsed); the sort menu has "Group by" (owner);
//   picking "Sections" saves '' and the sections come back.
// P2144C_NOSTART=1 = the server already runs.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2144C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const day = n => { const d = new Date(); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
const heads = d => [...d.querySelectorAll('#view .group > .ghead')].map(h => h.textContent.replace(/\d+\s*$/, '').trim());

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['cal', 'comments', 'fields']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,events,comments,fields,collab,agents'});
  const st = await call('GET', '/api/state'), ORG = st.me.workspaces[0].id;
  const t0 = day(0);

  // ================= #2418 the start page
  const P = await call('POST', '/api/evcals', {name: 'Mine', color: '#60a5fa'});
  await call('POST', '/api/events', {title: 'Lunch with the team', cal_id: P.id, start: `${t0}T12:00`, end: `${t0}T13:00`});
  await call('POST', '/api/events', {title: 'Holiday at the lake', cal_id: P.id, all_day: true, start: t0});
  let w = await boot({user: 'alice', hash: 'home'}), d = w.document;
  const evRows = () => [...d.querySelectorAll('#view .dc-today .dcev .cevrow .cevn')].map(x => x.textContent);
  await until(() => evRows().length === 2);
  check(evRows().length === 2 && evRows().includes('Lunch with the team'), 'Today block: the events of today ' + evRows());
  check(!/Nothing left for today/.test(d.querySelector('#view .dc-today')?.textContent || ''), 'events only: no empty line');
  const OL = (await call('POST', '/api/lists', {name: 'Office', org_id: ORG})).id;
  await call('POST', '/api/tasks', {title: 'Send the offer', list_id: OL, due: t0});
  await until(() => w.eval('S.tasks.size') > 0 && w.eval(`[...S.tasks.values()].some(t => t.title === 'Send the offer')`));
  w.eval('renderView()'); await sleep(100);
  const blk = d.querySelector('#view .dc-today');
  const evAt = blk.innerHTML.indexOf('dcev'), tkAt = blk.innerHTML.indexOf('Send the offer');
  check(evAt > 0 && tkAt > evAt, 'the events above the tasks');
  check(w.eval(`lyo_defs('home', 'today').some(x => x.name === 'ev' && x.default === true)`), 'the block setting "Show events" (on by default)');
  w.eval(`lyo_put('home', 'today', {ev: false}, '')`); await sleep(200); w.eval('renderView()'); await sleep(100);
  check(!d.querySelector('#view .dc-today .dcev') && /Send the offer/.test(d.querySelector('#view .dc-today').textContent), '"Show events" off: no events, the tasks stay');
  w.eval(`lyo_put('home', 'today', {ev: null}, '')`); await sleep(200);
  // the summary line: jobs of the working agents
  w.eval(`S.agents = [{id: 990, name: 'Helper', enabled: true, online: true, webhook: true, status: 'working', running: 3, waiting: 0}]`);
  check(/1 agent working \(3 jobs\)/.test(w.eval('hpSummary()').replace(/<[^>]+>/g, '')), 'summary: "1 agent working (3 jobs)" ' + w.eval('hpSummary()').replace(/<[^>]+>/g, ''));
  w.eval(`S.agents[0].running = 0`);
  check(/1 agent working\./.test(w.eval('hpSummary()').replace(/<[^>]+>/g, '')) && !/job/.test(w.eval('hpSummary()')), 'summary: no job number without running jobs');
  w.eval('S.agents = []');
  // an overdue task of another workspace is named with it
  const PL = (await call('POST', '/api/lists', {name: 'Home stuff', org_id: null})).id;
  await call('POST', '/api/tasks', {title: 'Pay the rent', list_id: PL, due: day(-2)});
  await until(() => w.eval(`[...S.tasks.values()].some(t => t.title === 'Pay the rent')`));
  w.eval(`S.settings.workspace = 'org:${ORG}'`);
  const sum = w.eval('hpSummary()').replace(/<[^>]+>/g, '');
  check(w.eval('wsCur()') === 'org:' + ORG && /1 overdue in Private/.test(sum) && !/, 1 overdue,/.test(sum), 'summary: overdue in another workspace named ' + w.eval('wsCur()') + ' ' + sum);
  w.eval(`S.settings.workspace = 'all'`);

  // ================= #2414 a list grouped by a custom field
  const L = (await call('POST', '/api/lists', {name: 'Releases'})).id;
  const sec = (await call('POST', '/api/sections', {list_id: L, name: 'Phase one'})).id;
  const fs = (await call('POST', `/api/lists/${L}/fields`, {name: 'Package', type: 'select', options: {options: [
    {id: 'p1', name: 'Later', color: 'blue'}, {id: 'p2', name: 'Now', color: 'green'}]}})).id;
  const ft = (await call('POST', `/api/lists/${L}/fields`, {name: 'Client', type: 'text'})).id;
  await call('POST', '/api/tasks', {title: 'Task now', list_id: L, section_id: sec, fields: {[fs]: 'p2', [ft]: 'Zeta'}});
  await call('POST', '/api/tasks', {title: 'Task later', list_id: L, fields: {[fs]: 'p1', [ft]: 'Acme'}});
  await call('POST', '/api/tasks', {title: 'Task loose', list_id: L});
  await call('PATCH', `/api/lists/${L}`, {group_field: `cf:${fs}`});
  w = await boot({user: 'alice', hash: 'l/' + L}); d = w.document;
  await until(() => heads(d).length >= 3);
  check(JSON.stringify(heads(d)) === JSON.stringify(['Later', 'Now', 'No value']), 'select: the option order, "No value" last ' + JSON.stringify(heads(d)));
  check(!heads(d).includes('Phase one') && !d.querySelector('#view .ghead[data-section]'), 'no section heads while grouped');
  const g1 = d.querySelector('#view .ghead[data-key^="gf:"]');
  g1.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true})); await sleep(150);
  check(JSON.parse(w.localStorage.getItem(Object.keys(w.localStorage).find(k => /collapsed$/.test(k)) || 'x') || '[]').includes(g1.dataset.key) || w.eval(`S.collapsed.has(${JSON.stringify(g1.dataset.key)})`), 'a group folds (kept like a section)');
  check(!/Task later/.test(d.querySelector('#view').textContent), 'the folded group hides its tasks');
  const items = w.eval(`lgfItems(listById(${L})).map(x => x.head || x.label)`);
  check(items[0] === 'Group by' && items.includes('Sections') && items.includes('Field: Package') && items.includes('Field: Client'), 'sort menu: "Group by" with the fields ' + items);
  check(!items.some(x => /Hours/.test(x || '')), 'only text / select fields');
  await w.eval(`lgfSet(${L}, 'cf:${ft}')`); await sleep(300);
  check((await call('GET', '/api/state')).lists.find(x => x.id === L).group_field === `cf:${ft}`, 'picking a field saves it');
  w.eval('renderView()'); await sleep(100);
  check(JSON.stringify(heads(d)) === JSON.stringify(['Acme', 'Zeta', 'No value']), 'text: by value ' + JSON.stringify(heads(d)));
  await w.eval(`lgfSet(${L}, '')`); await sleep(300);
  check((await call('GET', '/api/state')).lists.find(x => x.id === L).group_field === '', '"Sections" saves an empty value');
  w.eval('renderView()'); await sleep(100);
  check(heads(d).includes('Phase one'), 'the sections come back ' + JSON.stringify(heads(d)));

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
