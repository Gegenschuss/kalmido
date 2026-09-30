// 2.0.4 UI tests (jsdom), fresh DB: #308 the Flow badge "Ready to start" (was "Next") shows only when a task in the view
// waits on something (in the view, or outside it: t.blocked); a tap / click on it explains it (toast) without opening
// or ticking the task, it is a real button (keyboard); German "Startklar". #307 the project status picker: every option
// carries the colour of its pill (the .stopt rule no longer resets --sc to grey).
const {boot, errs, sleep, B, login} = require('./boot');
const fs = require('fs'), path = require('path');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {features: 'kanban,timeline,collab,progress,deps', lang: 'en'});
  const mk = async (title, list_id, extra = {}) => (await call('POST', '/api/tasks', {title, list_id, ...extra})).id;
  const PRJ = (await call('POST', '/api/lists', {name: 'Shoot', kind: 'project'})).id;
  const plan = await mk('Plan', PRJ), shoot = await mk('Shoot day', PRJ), edit = await mk('Edit', PRJ);
  const FREE = (await call('POST', '/api/lists', {name: 'Loose', kind: 'project'})).id;
  const a = await mk('Alpha', FREE), b = await mk('Beta', FREE);
  const OUT = (await call('POST', '/api/lists', {name: 'Outside', kind: 'project'})).id;
  const o1 = await mk('Waits elsewhere', OUT), o2 = await mk('Other', OUT);
  check((await call('POST', '/api/deps', {task_id: shoot, blocker_id: plan})).status < 300, 'setup: Shoot day waits on Plan');
  check((await call('POST', '/api/deps', {task_id: o1, blocker_id: edit})).status < 300, 'setup: a task in "Outside" waits on Edit (other list)');

  // ---- #308 A: with dependencies in the view the badge shows, on the first ready task
  let w = await boot({user: 'alice', hash: 'l/' + PRJ}), d = w.document;
  check(w.eval('sortMode()') === 'flow', 'project list sorts by Flow');
  let nx = d.querySelectorAll('#view .nxt');
  const rows0 = [...d.querySelectorAll('#view .trow')].map(r => +r.dataset.id);
  const first = rows0.find(id => id !== shoot);
  check(rows0.indexOf(plan) < rows0.indexOf(shoot), 'Flow: Plan before Shoot day: ' + rows0);
  check(nx.length === 1 && +nx[0].closest('.trow')?.dataset.id === first && first !== shoot, 'one badge, on the first task that waits on nothing: ' + rows0);
  const btn = nx[0];
  check(btn.tagName === 'BUTTON' && btn.type === 'button' && btn.dataset.act === 'flow-why', 'the badge is a button (keyboard, tap)');
  check(btn.textContent.trim() === 'Ready to start', 'label "Ready to start": ' + btn.textContent.trim());
  check(/Waits on nothing open/.test(btn.getAttribute('aria-label') || '') && /Waits on nothing open/.test(btn.title), 'aria-label / title explain it');
  check(d.querySelector(`#view .trow[data-id="${first}"]`).classList.contains('flownext'), 'row keeps the flow marker line');
  // tap / click: explanation, nothing else happens
  const selBefore = w.eval('S.sel');
  click(w, btn); await sleep(300);
  const toast = d.querySelector('#toast');
  check(toast && !toast.classList.contains('hidden') && /Waits on nothing open: the first task in the flow order \(dependencies, then date, then priority\)\./.test(toast.textContent), 'click shows the explanation: ' + (toast?.textContent || ''));
  check(w.eval('S.sel') === selBefore && d.querySelector('#detail').classList.contains('hidden'), 'click does not open the task');
  check(w.eval(`S.tasks.get(${plan}).status`) === 0, 'click does not tick the task');
  w.close();

  // no dependencies in the view: no badge, order unchanged (flow = date / priority / manual)
  w = await boot({user: 'alice', hash: 'l/' + FREE}); d = w.document;
  check(w.eval('sortMode()') === 'flow', 'dependency-free project list still sorts by Flow');
  check(!d.querySelector('#view .nxt') && !d.querySelector('#view .flownext'), 'no badge without dependencies');
  const fr = [...d.querySelectorAll('#view .trow')].map(r => +r.dataset.id);
  check(fr.length === 2 && JSON.stringify(fr) === JSON.stringify(w.eval(`flowSort([...S.tasks.values()].filter(t => t.list_id === ${FREE} && !t.parent_id)).map(t => t.id)`)), 'order = Flow order as before: ' + fr);
  w.close();

  // a task waiting on something OUTSIDE the view counts too (t.blocked): badge on the first ready one
  w = await boot({user: 'alice', hash: 'l/' + OUT}); d = w.document;
  nx = d.querySelectorAll('#view .nxt');
  check(nx.length === 1 && nx[0].closest('.trow')?.dataset.id == o2, 'blocker outside the view: badge on "Other", not on the waiting task');
  w.close();

  // the dependency goes away -> the badge goes too
  check((await call('DELETE', `/api/deps/${shoot}/${plan}`)).status < 300, 'dependency removed via the API');
  w = await boot({user: 'alice', hash: 'l/' + PRJ}); d = w.document;
  check(!d.querySelector('#view .nxt') && !d.querySelector('#view .flownext'), 'dependency removed: no badge');
  w.close();
  await call('POST', '/api/deps', {task_id: shoot, blocker_id: plan});

  // German
  await call('PATCH', '/api/settings', {lang: 'de'});
  w = await boot({user: 'alice', hash: 'l/' + PRJ}); d = w.document;
  const de = d.querySelector('#view .nxt');
  check(de?.textContent.trim() === 'Startklar', 'German: Startklar: ' + de?.textContent.trim());
  click(w, de); await sleep(300);
  check(/Wartet auf nichts Offenes/.test(d.querySelector('#toast')?.textContent || ''), 'German explanation');
  w.close();
  await call('PATCH', '/api/settings', {lang: 'en'});

  // mobile: the tap works the same (no hover needed)
  w = await boot({user: 'alice', mobile: true, hash: 'l/' + PRJ}); d = w.document;
  const mb = d.querySelector('#view .nxt');
  click(w, mb); await sleep(300);
  check(/Waits on nothing open/.test(d.querySelector('#toast')?.textContent || '') && !w.eval('S.sel'), 'phone: tap explains, task stays closed');
  w.close();

  // ---- #307 status picker: colour dots like the pills
  w = await boot({user: 'alice', hash: 'l/' + PRJ}); d = w.document;
  w.eval(`statusModal(${PRJ})`); await sleep(300);
  const opts = [...d.querySelectorAll('.stmodal .stopt')];
  const want = ['on_track', 'at_risk', 'off_track', 'on_hold', 'complete', ''];
  check(JSON.stringify(opts.map(o => o.dataset.st)) === JSON.stringify(want), 'picker offers every status + none');
  check(opts.every(o => o.classList.contains('st-' + (o.dataset.st || 'none')) && o.querySelector('i')), 'every option carries its st-* class and a dot');
  w.close();
  const css = fs.readFileSync(path.join(__dirname, '..', 'static', 'app.css'), 'utf8');
  const stopt = (css.match(/(^|\n)\.stopt\{[^}]*\}/) || [''])[0];
  check(stopt && !/--sc\s*:/.test(stopt), '.stopt no longer resets --sc (the st-* colour wins)');
  check(/\.stopt i\{[^}]*background:var\(--sc/.test(css), 'the dot uses --sc');
  check(/\.st-on_track\{--sc:var\(--st-on_track\)\}/.test(css), 'st-* classes set --sc');

  const errList = errs.filter(e => !/Could not load|ECONNREFUSED|NetworkError|ResizeObserver/.test(e));
  check(!errList.length, 'no script errors: ' + errList.slice(0, 3).join(' | '));
  console.log(`p204_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e.stack || e); process.exit(1); });
