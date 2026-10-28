// 2.410.0 UI tests (jsdom, leader L), fresh DB
// - #3437 a budget counts once per branch in the column sum too: the sum row over the top-level rows counts the subtasks'
//   budgets of a task that has some (86, not 57 = top level only, not 140 = everything); a parent's budget cell shows the sum
//   of its subtasks (grey) with its own different value as a hint; a task without valued subtasks shows its own value
// - #3440 "Show completed at the bottom" in the view menu: the icon donedown (not the cart), also for a list admin
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
  await call(CK, 'PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const bob = await call(CK, 'POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  const CB = await login('bob');
  await call(CB, 'PATCH', '/api/settings', {lang: 'en', tour: 'done'});

  // ================= #3437 the project of the task
  const P = (await call(CK, 'POST', '/api/lists', {name: 'Car spot', ptype: 'agency', time_tracking: true})).id;
  const fb = (await call(CK, 'GET', '/api/state')).fields.find(f => f.list_id === P && f.name === 'Budget h');
  const mk = async (title, v, parent) => (await call(CK, 'POST', '/api/tasks', {title, list_id: P, fields: {[fb.id]: String(v)}, ...(parent ? {parent_id: parent} : {})})).id;
  await mk('Brief', 3);
  const eps = [];
  for (const [own, subs] of [[10, [11, 4]], [10, [11, 4]], [10, [11, 4, 2]], [24, [24, 12]]]) {
    const p = await mk('Episode ' + own, own); eps.push(p);
    for (const x of subs) await mk('Part ' + x, x, p);
  }
  await call(CK, 'PATCH', '/api/lists/' + P, {columns: ['f:' + fb.id]});
  const w = await boot({user: 'alice', hash: 'l/' + P});
  check(await until(() => w.eval(`S.tasks.size >= 14 && !!fieldById(${fb.id})`)), 'setup: the project is loaded');
  check(w.eval(`fxIsBudget(fieldById(${fb.id}))`), '#3437: the field "Budget h" is a budget field');
  const top = w.eval(`JSON.stringify([...S.tasks.values()].filter(t => t.list_id === ${P} && !t.parent_id).map(t => t.id))`);
  const sum = w.eval(`fxBranchSum(fieldById(${fb.id}), ${top}.map(taskById)).reduce((a, x) => a + x, 0)`);
  check(sum === 86, `#3437: the column sum over the top-level rows = 86 (once per branch): ${sum}`);
  const all = w.eval(`fxBranchSum(fieldById(${fb.id}), [...S.tasks.values()].filter(t => t.list_id === ${P})).reduce((a, x) => a + x, 0)`);
  check(all === 86, `#3437: with the subtasks among the shown rows (a flat filter) still 86, not counted twice: ${all}`);
  const cell = w.eval(`lcCell('f:${fb.id}', taskById(${eps[3]}), {kids: []})`);
  check(/fxbr/.test(cell) && /36/.test(cell) && /own value 24/.test(cell), '#3437: the parent cell shows 36 (its subtasks) with "own value 24": ' + cell);
  const plain = w.eval(`lcCell('f:${fb.id}', [...S.tasks.values()].find(t => t.title === 'Brief'), {kids: []})`);
  check(!/fxbr/.test(plain) && />3</.test(plain), '#3437: a task without subtasks shows its own value: ' + plain);
  if (!w.eval('isMobile()')) {
    const row = await until(() => w.document.querySelector('.fxsum'));
    check(row && /86/.test(row.textContent) && !/\b57\b/.test(row.textContent), '#3437: the sum row on screen says 86: ' + (row && row.textContent));
  }

  // ================= #3440 the icon, for the owner and a list admin
  const items = w.eval(`JSON.stringify(topMoreItems().filter(x => x && x.label === 'Show completed at the bottom').map(x => x.icon))`);
  check(items === '["donedown"]', '#3440: the owner sees the entry with the icon donedown: ' + items);
  check(w.eval(`!!P.donedown && /<svg/.test(ic('donedown')) && ic('donedown') !== ic('cart')`), '#3440: the icon exists');
  w.close();
  const L = (await call(CK, 'POST', '/api/lists', {name: 'Team project'})).id;
  let r = await call(CK, 'PUT', `/api/lists/${L}/members`, {user_id: bob.id, role: 'admin'});
  if (r.status === 409) r = await call(CK, 'PUT', `/api/lists/${L}/members`, {user_id: bob.id, role: 'admin', bridge_ok: true});
  check(r.status === 200, 'setup: bob is a list admin ' + r.status);
  const wb = await boot({user: 'bob', hash: 'l/' + L});
  check(await until(() => wb.eval(`!!listById(${L}) && routeList()?.id === ${L}`)), 'setup: bob is in the shared project');
  const bi = wb.eval(`JSON.stringify(topMoreItems().filter(x => x && x.label === 'Show completed at the bottom').map(x => x.icon))`);
  check(bi === '["donedown"]', '#3440: a list admin sees the entry too: ' + bi);
  wb.close();

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  console.log(`p24100_l_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
