// 2.46.2 UI tests, part A (#1718 no flicker: the view is morphed when it is drawn again for the same route), own container
// (start.sh), jsdom. The flicker test: a MutationObserver on #view counts the element nodes a redraw inserts; the same data
// drawn again inserts none, a small change only a few (before 2.46.2 every redraw rebuilt the whole view).
// - agents page with four jobs: same data = 0 new nodes, one job's history changes = the job card stays the same node,
//   the agent card too; ten job steps in a row are drawn at most twice (gathered, one per 400 ms)
// - a list: same data = 0, a new task on top = the other rows keep their nodes
// - start page, calendar (month), timeline: same data = 0
// - a hand-opened <details> stays open through a redraw, an input keeps its typed value
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK, hd = {}) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {}), ...hd}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const FEAT = 'cal,comments,collab,time,progress,agents,kanban,timeline,team,notes';
// in the page: how many element nodes a redraw inserts into #view (each inserted subtree counts once)
const CNT = `window.__cnt = async fn => { let n = 0; const add = ms => { for (const m of ms) for (const x of m.addedNodes) if (x.nodeType === 1) n++; };
  const mo = new MutationObserver(add); mo.observe(document.getElementById('view'), {childList: true, subtree: true});
  try { await fn(); } finally { add(mo.takeRecords()); mo.disconnect(); } return n; }; 1`;
const cnt = (w, code) => w.eval(`__cnt(async () => { ${code} })`);

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['cal', 'comments', 'timeline', 'kanban', 'agents']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const L = (await call('POST', '/api/lists', {name: 'Shoot'})).id;
  const day = n => { const d = new Date(); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10); };
  for (let i = 0; i < 8; i++) await call('POST', '/api/tasks', {title: 'Step ' + i, list_id: L, due: day(i % 5), start: day(i % 5 - 1)});
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write'], username: 'claude', display_name: 'Claude'});
  const AGH = {Authorization: 'Bearer ' + ag.token};
  await call('PUT', `/api/lists/${L}/members`, {user_id: ag.id, role: 'edit'});
  for (const t of ['Build the sitemap', 'Check the links', 'Resize the images', 'Write the texts']) await call('POST', '/api/v1/agent/jobs', {title: t}, null, AGH);

  // ================= agents page
  let w = await boot({user: 'alice', hash: 'agents'}), d = w.document;
  w.eval(CNT);
  await until(() => d.querySelectorAll('#view .job[id^="job-"]').length >= 4);
  check(d.querySelectorAll('#view .job[id^="job-"]').length >= 4, '#1718 agents: four jobs shown');
  await sleep(600);
  let n = await cnt(w, 'renderView();');
  check(n === 0, '#1718 agents: the same data drawn again inserts no node (' + n + ')');
  const job = d.querySelector('#view .job[id^="job-"]'), jid = +job.id.slice(4), card = d.querySelector('#view .agcard');
  n = await cnt(w, `const j = S.jobs.items.find(x => x.id === ${jid}); j.log = 'Reading the pages'; renderView();`);
  check(n <= 2, '#1718 agents: a new history line inserts at most its block (' + n + ')');
  n = await cnt(w, `const j = S.jobs.items.find(x => x.id === ${jid}); j.log += '\\nChecking the links'; j.updated_at = new Date().toISOString(); renderView();`);
  check(n === 0, '#1718 agents: one more history line inserts no node (' + n + ')');
  check(d.getElementById('job-' + jid) === job && job.isConnected, '#1718 agents: the job card is the same node');
  check(d.querySelector('#view .agcard') === card, '#1718 agents: the agent card is the same node (avatar not reloaded)');
  check(d.querySelector(`#job-${jid} .joblog pre`)?.textContent.includes('Checking the links'), '#1718 agents: ... and shows the new line');
  // a hand-opened history stays open, the job order changing keeps the cards
  const lg = d.querySelector(`#job-${jid} .joblog`);
  lg.open = true; lg.dispatchEvent(new w.Event('toggle'));
  await sleep(50);
  w.eval('delete S.jobLogOpen[' + jid + ']; renderView();');
  check(d.querySelector(`#job-${jid} .joblog`)?.open === true, '#1718 agents: an opened history stays open through a redraw');
  const nodes = [...d.querySelectorAll('#view .job[id^="job-"]')];
  n = await cnt(w, 'S.jobs.items.reverse(); renderView();');
  // a move is reported as an insert by the observer: at most one per card, and no card is a new node
  check(n <= nodes.length && [...d.querySelectorAll('#view .job[id^="job-"]')].every(x => nodes.includes(x)), '#1718 agents: jobs in another order keep their nodes (' + n + ' moved)');
  // gathered: ten steps in a row
  w.eval('window.__rv = 0; { const o = renderView; window.renderView = function () { __rv++; return o.apply(this, arguments); }; } 1');
  await sleep(450);
  w.eval('for (let i = 0; i < 10; i++) jobStepsRedraw(); 1');
  await sleep(900);
  const rv = w.eval('__rv');
  check(rv >= 1 && rv <= 2, '#1718 agents: ten job steps are drawn at most twice (' + rv + ')');
  w.eval('__rv = 0; renderView(); fl_viewSoon(true, "agents"); 1');
  await sleep(150);
  check(w.eval('__rv') === 1, '#1718 agents: right after a redraw the next live one waits (400 ms)');
  await sleep(600);
  check(w.eval('__rv') === 2, '#1718 agents: ... and comes then');
  w.close();

  // ================= a list
  w = await boot({user: 'alice', hash: 'l/' + L}); d = w.document; w.eval(CNT);
  await until(() => d.querySelectorAll('#view .trow[data-id]').length >= 8);
  await sleep(400);
  n = await cnt(w, 'renderView();');
  check(n === 0, '#1718 list: the same data drawn again inserts no node (' + n + ')');
  const rows = [...d.querySelectorAll('#view .trow[data-id]')];
  await call('POST', '/api/tasks', {title: 'Step new', list_id: L, due: day(0)});
  n = await cnt(w, 'await load(); render();');
  const rows2 = [...d.querySelectorAll('#view .trow[data-id]')];
  check(rows2.length === rows.length + 1, '#1718 list: the new task is there');
  check(rows.every(x => rows2.includes(x)), '#1718 list: the other rows keep their nodes');
  check(n <= 4, '#1718 list: a new task inserts only a few nodes (' + n + ')');
  // a typed, unsaved value in the quick add field survives a live redraw
  const qi = d.querySelector('#qinput');
  if (qi) { qi.value = 'Half typed'; w.eval('renderView();'); check(d.querySelector('#qinput').value === 'Half typed', '#1718 list: the quick add keeps its text'); }
  w.close();

  // ================= start page, calendar, timeline
  for (const [what, hash, sel, ls] of [['start page', 'home', '#view .dash, #view .home, #view > *', {}], ['calendar', 'cal', '#view .cal, #view .month, #view [data-day]', {'tasks.calMode': '"month"'}]]) {
    w = await boot({user: 'alice', hash, ls}); d = w.document; w.eval(CNT);
    await until(() => d.querySelector(sel)); await sleep(500);
    n = await cnt(w, 'renderView();');
    check(n === 0, `#1718 ${what}: the same data drawn again inserts no node (${n})`);
    n = await cnt(w, 'renderView(); renderView();');
    check(n === 0, `#1718 ${what}: twice, still none (${n})`);
    w.close();
  }
  await call('PATCH', `/api/lists/${L}`, {view: 'timeline'});
  w = await boot({user: 'alice', hash: 'l/' + L}); d = w.document; w.eval(CNT);
  await until(() => d.querySelector('#tlscroll .tl-bar[data-id]')); await sleep(500);
  check(!!d.querySelector('#tlscroll .tl-bar[data-id]'), '#1718 timeline: bars shown');
  const bar = d.querySelector('#tlscroll .tl-bar[data-id]');
  n = await cnt(w, 'renderView();');
  check(n === 0, '#1718 timeline: the same data drawn again inserts no node (' + n + ')');
  check(bar.isConnected, '#1718 timeline: a bar is the same node');
  w.close();

  console.log(`p2462_a_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
