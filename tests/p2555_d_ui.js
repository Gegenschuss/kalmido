// 2.555.0 D UI test (jsdom, #4570): the budget warning on the project page and in the task. A project with "Budget h" 10 h:
// 8.5 h tracked = the project's time sum carries "80 % of the budget used" (class warn), the task's time area too (lv-warn);
// 11 h = "over budget" (class over / lv-over); the News text of the notice (kind budgetwarn) names the task and the hours.
// kalmido-suite: fresh
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
  const ep = (await call(CK, 'POST', '/api/tasks', {title: 'Episode', list_id: P, fields: {[fb.id]: '10'}})).id;
  const track = async minutes => check((await call(CK, 'POST', '/api/time/entries', {task_id: ep, start: '2026-10-20T09:00', minutes})).status === 200, 'setup: time entry');
  await track(510);  // 8.5 h
  const ov = (await call(CK, 'GET', `/api/lists/${P}/overview`)).time || {};
  check(ov.budget_level === 'warn' && ov.budget_pct === 85, 'the server says warn, 85 %: ' + JSON.stringify(ov));

  const w = await boot({user: 'alice', hash: 'l/' + P}), d = w.document;
  check(await until(() => w.eval(`!!taskById(${ep})`)), 'setup: the project is loaded');
  w.eval(`setListView(listById(${P}), 'overview')`);
  let el = await until(() => d.querySelector('.tsum.warn .tbw'));
  check(el && /80 % of the budget used/.test(el.textContent), 'project: 8.5 of 10 h = "80 % of the budget used": ' + el?.textContent);
  check(el && /80 % of the budget used/.test(el.closest('.tsum').getAttribute('aria-label') || ''), 'project: the warning is in the label too');
  check(!!(await until(() => d.querySelector('#pov-time .tsum.warn .tbw'))), 'project page: the section "Tracked time" shows the warning');
  w.eval(`openDetail(${ep})`);
  let tb = await until(() => d.querySelector(`#d-time [data-tebud="${ep}"].lv-warn`));
  check(tb && /80 % of the budget used/.test(tb.textContent), 'task: the time area warns: ' + tb?.textContent);
  w.eval('closeDetail()');

  await track(150);  // 11 h
  w.eval('load().then(() => { render(); })');
  el = await until(() => d.querySelector('#pov-time .tsum.over .tbw'));
  check(el && /over budget/.test(el.textContent) && !d.querySelector('.tsum.warn'), 'project: 11 of 10 h = "over budget": ' + el?.textContent);
  w.eval(`openDetail(${ep})`);
  tb = await until(() => d.querySelector(`#d-time [data-tebud="${ep}"].lv-over`));
  check(tb && /over budget/.test(tb.textContent), 'task: the time area says over budget: ' + tb?.textContent);

  const t80 = w.eval(`newsText({kind: 'budgetwarn', data: {scope: 'task', level: 80, pct: 80, h: 10, tracked_h: 8}, task_title: 'Episode', list_id: ${P}}, {})`);
  check(/Episode/.test(t80) && /80 % of its budget/.test(t80) && /8 of 10 h/.test(t80), 'News text at 80 %: ' + t80);
  const t100 = w.eval(`newsText({kind: 'budgetwarn', data: {scope: 'project', level: 100, pct: 110, h: 10, tracked_h: 11}, list_id: ${P}}, {})`);
  check(/Car spot/.test(t100) && /over its budget/.test(t100) && /11 of 10 h/.test(t100), 'News text at 100 % (project): ' + t100);
  const row = w.eval(`NOTIF_ROWS.some(r => r[0] === 'timebudget') && notifMatrix(S.settings).timebudget.news === true && notifMatrix(S.settings).timebudget.push === true`);
  check(row, 'the notification settings have the row "Budget warnings", News + push on');
  w.close();

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  console.log(`p2555_d_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
