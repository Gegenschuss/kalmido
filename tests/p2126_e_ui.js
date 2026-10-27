// 2.126.0 UI tests, part E (jsdom), fresh DB: #1993 ESLint in CI -- the client still runs after the lint fixes.
// A short smoke run through the views whose files changed: a list (add a task, complete it), the task detail, the
// timeline's "today", the share dialog, the start page, settings, the office -- no script error anywhere.
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, ms = 6000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (await fn()) return true; await sleep(100); } return false; };

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const P = (await call('POST', '/api/lists', {name: 'Flyers'})).id;
  const T = (await call('POST', '/api/tasks', {title: 'Print the flyer', list_id: P})).id;
  const tasks = async () => (await call('GET', '/api/state')).tasks || [];

  // a list: add a task over the quick add, complete it
  let w = await boot({user: 'alice', hash: 'l/' + P}), d = w.document;
  check(!!d.querySelector('#qinput'), 'the list shows the quick add');
  d.querySelector('#qinput').value = 'Fold the flyers';
  await w.eval(`submitQuick(document.querySelector('#qinput'))`);
  check(await until(async () => (await tasks()).some(t => t.title === 'Fold the flyers')), 'the new task is on the server');
  const N = (await tasks()).find(t => t.title === 'Fold the flyers')?.id;
  await w.eval(`toggleTask(${N})`);
  check(await until(async () => (await call('GET', '/api/tasks/' + N)).status === 2), 'the task is completed');
  // the list views (projects.js setListView) and the timeline's "today" (events.js)
  await w.eval(`setListView(listById(${P}), 'timeline')`); await sleep(600);
  d.querySelector('[data-act="tl-today"]')?.click(); await sleep(300);
  await w.eval(`setListView(listById(${P}), 'list')`); await sleep(600);
  check(!!d.querySelector('#view'), 'the list view is back');
  // the share dialog (dialogs.js)
  await w.eval(`shareModal(${P})`); await sleep(400);
  check(!!d.querySelector('.modal'), 'the share dialog opens');
  d.querySelector('.modal [data-m="close"]')?.click(); await sleep(200);
  // settings
  await w.eval('settingsModal()'); await sleep(600);
  check(!!d.querySelector('.modal'), 'the settings open');
  w.close();

  // the task detail (detail.js)
  w = await boot({user: 'alice', hash: 't/' + T}); d = w.document;
  check(await until(() => /Print the flyer/.test(d.querySelector('#detail')?.textContent || '') || /Print the flyer/.test(d.querySelector('#detail input, #detail textarea')?.value || '')), 'the task detail opens');
  w.close();

  // the start page (dashboard.js) and the office (office.js, office_docs.js)
  w = await boot({user: 'alice', hash: 'home'}); d = w.document;
  check(!!d.querySelector('#view') && d.querySelector('#view').textContent.trim().length > 0, 'the start page shows');
  w.close();
  w = await boot({user: 'alice', hash: 'office/offers'}); d = w.document;
  check(await until(() => (d.querySelector('#view')?.textContent || '').trim().length > 0), 'the office shows');
  w.close();

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  console.log(`p2126_e_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
