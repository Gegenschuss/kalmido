// 2.537.0 C2 UI test (jsdom, #3433 decision 5): the task detail of a task with "Budget h" shows "Tracked X of Y h" with the
// bar of the client's budget: 6 of 10 h = within budget, 8.5 of 10 h = warn (yellow), 11 of 10 h = over (red); the subtask's
// time counts along; a task without a value shows no bar. Hours only, no prices. Fresh DB.
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
  const P = (await call(CK, 'POST', '/api/lists', {name: 'Car spot', ptype: 'agency', time_tracking: true})).id;
  const fb = (await call(CK, 'GET', '/api/state')).fields.find(f => f.list_id === P && f.name === 'Budget h');
  const ep = (await call(CK, 'POST', '/api/tasks', {title: 'Episode', list_id: P, fields: {[fb.id]: '10'}})).id;
  const sub = (await call(CK, 'POST', '/api/tasks', {title: 'Cut', list_id: P, parent_id: ep})).id;
  const plain = (await call(CK, 'POST', '/api/tasks', {title: 'Plain', list_id: P})).id;
  const track = async (tid, minutes) => check((await call(CK, 'POST', '/api/time/entries', {task_id: tid, start: '2026-10-20T09:00', minutes})).status === 200, 'setup: time entry');
  await track(ep, 120); await track(sub, 240);

  for (const mobile of [true, false]) {  // the phone first (it only reads), then the desktop adds time
    const who = mobile ? 'phone' : 'desktop';
    const w = await boot({user: 'alice', hash: 'l/' + P, mobile}), d = w.document;
    check(await until(() => w.eval(`!!taskById(${ep}) && !!taskById(${sub})`)), `${who}: setup: the project is loaded`);
    const open = async (id, txt) => { w.eval(`openDetail(${id})`); return until(() => { const x = d.querySelector(`#d-time [data-tebud="${id}"]`); return x && (!txt || txt.test(x.textContent)) ? x : null; }); };
    let el = await open(ep);
    check(el && /Tracked/.test(el.textContent) && /6 of 10 h/.test(el.textContent) && /within budget/.test(el.textContent) && el.classList.contains('lv-ok'),
      `${who}: 6 of 10 h (task + subtask), within budget: ` + el?.textContent + ' ' + el?.className);
    check(el && el.querySelector('[role="meter"]')?.getAttribute('aria-valuenow') === '60', `${who}: the meter at 60 %`);
    check(el && !/€|EUR/.test(el.textContent), `${who}: hours only, no prices`);
    if (!mobile) {
      await track(sub, 150);  // 8.5 h
      w.eval('load().then(() => { render(); if (S.sel) renderDetail(); })');
      el = await open(ep, /8[.,]5 of 10 h/);
      check(el && el.classList.contains('lv-warn') && /80 % of the budget used/.test(el.textContent), `${who}: 8.5 of 10 h = warn (yellow): ` + el?.textContent + ' ' + el?.className);
      await track(ep, 150);  // 11 h
      w.eval('load().then(() => { render(); if (S.sel) renderDetail(); })');
      el = await open(ep, /11 of 10 h/);
      check(el && el.classList.contains('lv-over') && /over budget/.test(el.textContent), `${who}: 11 of 10 h = over (red): ` + el?.textContent + ' ' + el?.className);
    }
    w.eval(`openDetail(${plain})`);
    check(await until(() => w.eval(`S.te.tid === ${plain} && S.te.items !== null`)) && !d.querySelector('#d-time [data-tebud]'), `${who}: a task without a value: no bar`);
    w.close();
  }

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  console.log(`p3433_c2_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
