// 2.627.0 C UI test (jsdom, #4503): the tracked time stands next to the task's duration (= the estimate, no field of its own)
// kalmido-suite: fresh
// in the row's time chip / column and in the task's time area ("1:30 h / 2:00 h"); the budget bar of the project's time sum
// and of the "Tracked time" window turns yellow from 80 % (warn) and red from 100 % (over). Alice owns no organisation
// (a person without an organisation, the freelancer case); no route changed.
const {boot, errs, B, login, until} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CK = await login('alice');
  await call(CK, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['comments']});
  await call(CK, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'collab,time,fields,comments'});
  const P = (await call(CK, 'POST', '/api/lists', {name: 'Car spot', time_tracking: true})).id;
  await call(CK, 'POST', `/api/lists/${P}/fields`, {name: 'Budget h', type: 'number'});
  const fb = (await call(CK, 'GET', '/api/state')).fields.find(f => f.list_id === P && f.name === 'Budget h');
  const TD = new Date().toISOString().slice(0, 10);
  const ep = (await call(CK, 'POST', '/api/tasks', {title: 'Episode', list_id: P, due: TD, due_time: '10:00', duration: 120, fields: {[fb.id]: '10'}})).id;
  const e2 = (await call(CK, 'POST', '/api/tasks', {title: 'Trailer', list_id: P, due: TD, due_time: '14:00', duration: 60})).id;
  const plain = (await call(CK, 'POST', '/api/tasks', {title: 'Poster', list_id: P})).id;
  const track = async (tid, minutes) => check((await call(CK, 'POST', '/api/time/entries', {task_id: tid, start: '2026-10-20T09:00', minutes})).status === 200, 'setup: time entry');
  await track(ep, 90);
  await track(plain, 30);

  const w = await boot({user: 'alice', hash: 'l/' + P}), d = w.document;
  check(await until(() => w.eval(`!!taskById(${ep}) && taskById(${ep}).duration === 120`)), 'setup: the project is loaded, the duration is 2 h');
  // the row: tracked / estimate
  const cell = id => d.querySelector(`#view .trow[data-id="${id}"] .tchip b`) || d.querySelector(`#view .trow[data-id="${id}"] .c-time`);
  let c = await until(() => cell(ep)?.textContent ? cell(ep) : null);
  check(c && /1:30 h \/ 2:00 h/.test(c.textContent), 'row: tracked 1:30 next to the estimate 2:00: ' + c?.textContent);
  const tip = (c?.closest('[title]') || c)?.getAttribute('title') || '';
  check(/Estimate: 2:00 h/.test(tip), 'row: the tip names the estimate: ' + tip);
  c = cell(plain);
  check(c && /30 min/.test(c.textContent) && !/\//.test(c.textContent), 'row without a duration: only the tracked time: ' + c?.textContent);
  check(w.eval(`tIstEst(0, taskById(${e2}))`) === '0 min / 1:00 h' && w.eval(`tIstEst(5400, taskById(${plain}))`) === '1:30 h', 'tIstEst: estimate only with a duration');
  // the task's time area
  w.eval(`openDetail(${ep})`);
  let n = await until(() => d.querySelector(`#d-time [data-ist-est="${ep}"]`));
  check(n && /1:30 h \/ 2:00 h/.test(n.textContent), 'panel: tracked next to the estimate: ' + n?.textContent);
  w.eval('closeDetail()');
  w.eval(`openDetail(${e2})`);
  n = await until(() => d.querySelector(`#d-time [data-ist-est="${e2}"]`));
  check(n && /0 min \/ 1:00 h/.test(n.textContent), 'panel: the estimate shows before the first minute: ' + n?.textContent);
  w.eval('closeDetail()');

  // the budget levels (like the server's: rounded percent, 80 warn, 100 over)
  check(w.eval(`[pbw_level(7.9, 10), pbw_level(8, 10), pbw_level(9.9, 10), pbw_level(10.1, 10), pbw_level(5, 0)].join(',')`) === ',warn,warn,over,', 'pbw_level: below 80 % none, from 80 % warn, over 100 % over');
  await track(ep, 450);  // 1.5 h + 7.5 h = 9 h (+ 0.5 h on Poster without a budget = 9.5 of 10 h: 95 %)
  w.eval('load().then(() => { render(); })');
  w.eval(`setListView(listById(${P}), 'overview')`);
  let el = await until(() => d.querySelector('#pov-time .tsum.warn'));
  check(el && !el.classList.contains('over'), 'project: 95 % of the budget = yellow (warn)');
  el.click();
  let tz = await until(() => d.querySelector('.tzmodal .tzsum.warn'));
  check(!!tz, 'the "Tracked time" window: the bar is yellow from 80 % too (before only red over 100 %)');
  w.eval(`document.querySelector('.tzmodal')?.remove()`);
  await until(() => !d.querySelector('.tzmodal'));
  await track(ep, 60);  // 10.5 h of 10 h
  w.eval('load().then(() => { render(); })');
  el = await until(() => d.querySelector('#pov-time .tsum.over'));
  check(el && !el.classList.contains('warn'), 'project: over 100 % = red (over)');
  el.click();
  tz = await until(() => d.querySelector('.tzmodal .tzsum.over'));
  check(!!tz, 'the "Tracked time" window: red over 100 %');
  w.close();

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  console.log(`p2627_c_istest_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
