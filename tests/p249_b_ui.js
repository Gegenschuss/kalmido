// 2.49.0 UI tests, part B: child accounts, own container (start.sh), jsdom.
//  #1537: a child's first start sends no write the server refuses (no 403, no error toast); "My day" shows a section per
//         shared list (its name as the heading, an empty one says so), a newly shared list shows up by itself; Settings
//         has no Modules / Integrations / Agents / Data / Administration / Help for a child
//  #1533: a child's first start shows its own tour (3 cards, no sample project); finishing it saves tour=done; a grown-up's
//         tour stays the same
//  #1551: a parent sets the PIN in the Family view; the child then gets the PIN field for Settings and Log out (wrong PIN:
//         a calm message, right PIN: Settings open); ticking off needs no PIN
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P249_B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, KALMIDO_ONBOARDING: '1'}});  // onboard / tour pending
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
// every write of the page with its status (the child's start must not get a 403)
const spy = log => w => { const f = w.fetch; w.fetch = async (u, o = {}) => { const r = await f(u, o); if ((o.method || 'GET') !== 'GET') log.push(`${o.method} ${u} ${r.status}`); return r; }; };
const kidBoot = async log => {
  const w = await boot({user: 'lina', ls: {'tasks.lastKey': null}, setup: spy(log)});
  await until(() => { try { return w.eval('S.booted') && w.document.querySelector('#view .kidv'); } catch { return false; } }, 200);
  return w;
};

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,family'});
  const LINA = (await call('POST', '/api/users', {username: 'lina', display_name: 'Lina', password: 'password123', kid: true, parents: [1]})).id;
  const L1 = (await call('POST', '/api/lists', {name: 'Chores'})).id, L2 = (await call('POST', '/api/lists', {name: 'Trip'})).id;
  for (const l of [L1, L2]) await call('PUT', `/api/lists/${l}/members`, {user_id: LINA, role: 'edit'});
  const KT = await call('POST', '/api/tasks', {title: 'Feed the cat', list_id: L1, assignee_id: LINA});

  // ================= #1537 + #1533: the child's first start
  let log = [];
  let w = await kidBoot(log), d = w.document;
  await until(() => w.eval('TOUR.on'), 60);
  await sleep(1500);  // the onboarding and other start writes
  check(!log.some(x => / 403$/.test(x)), 'start: no write refused ' + JSON.stringify(log));
  check(log.some(x => /^POST \/api\/onboarding 200$/.test(x)), 'start: the onboarding answers 200 ' + JSON.stringify(log));
  check(!/child account|not possible/i.test(d.querySelector('#toast')?.textContent || ''), 'start: no error toast: ' + (d.querySelector('#toast')?.textContent || ''));
  const secs = [...d.querySelectorAll('#view .kd_list .kidsec')].map(e => e.textContent);
  check(JSON.stringify(secs) === '["Chores","Trip"]', 'a section per shared list ' + JSON.stringify(secs));
  check(/Feed the cat/.test(d.querySelector(`#view [data-kd-list="${L1}"]`)?.textContent || '') && d.querySelector(`#view [data-kd-list="${L1}"] [data-act="kid-tick"][data-id="${KT.id}"]`), 'its task under Chores, with the big tick');
  check(/Nothing here for you right now/.test(d.querySelector(`#view [data-kd-list="${L2}"]`)?.textContent || ''), 'the empty list says so');
  // the tour
  check(w.eval('TOUR.on') && JSON.stringify(w.eval('TOUR.steps.map(s => s.id)')) === '["kd-tasks","kd-tick","kd-parents"]', 'the child tour: 3 cards ' + JSON.stringify(w.eval('TOUR.steps.map(s => s.id)')));
  check(/Your tasks/.test(d.querySelector('.tour .tcard')?.textContent || '') && !d.querySelector('.tour #t-sample'), 'first card "Your tasks", no sample project');
  for (let i = 0; i < 3; i++) { click(w, d.querySelector('.tour [data-tour="next"]')); await sleep(150); }
  check(!d.querySelector('.tour') && await until(async () => (await call('GET', '/api/state', null, w.__cookie)).settings.tour === 'done'), 'the tour ends and saves done');
  check(!log.some(x => / 403$/.test(x)), 'the tour end: no 403 ' + JSON.stringify(log));
  // a list shared now shows up by itself
  const L3 = (await call('POST', '/api/lists', {name: 'Garden'})).id;
  await call('PUT', `/api/lists/${L3}/members`, {user_id: LINA, role: 'edit'});
  check(await until(() => d.querySelector(`#view [data-kd-list="${L3}"]`), 120), 'a newly shared list shows up without a reload');
  // Settings for a child: opens without errors; the areas a child cannot use are hidden by app.css (jsdom has no layout)
  w.eval('settingsModal()'); await sleep(200);
  const css = await require('./boot').allCss(); // 2.65.0 (#1824): + the module stylesheets
  check(d.querySelector('.smodal #sp-account') && ['org', 'modules', 'integr', 'ai', 'data', 'users', 'help'].every(k => css.includes(`body.kidmode .smodal .snav [data-sec="${k}"]`))
    && !['account', 'general', 'look', 'notify'].some(k => css.includes(`.snav [data-sec="${k}"]`)), 'Settings of a child: account, general, appearance, notifications stay; the rest is hidden');
  w.close();

  // ================= a grown-up's tour stays
  w = await boot({user: 'alice', hash: 'family'}); d = w.document;
  await until(() => d.querySelector(`#view [data-act="fam-pin"][data-kid="${LINA}"]`), 100);
  const ids = w.eval('tourSteps().map(s => s.id)');
  check(ids.includes('side') && ids.includes('add') && !ids.some(x => /^kd-/.test(x)), 'the grown-up tour is unchanged ' + JSON.stringify(ids));
  // ================= #1551: the parent sets the PIN
  click(w, d.querySelector(`#view [data-act="fam-pin"][data-kid="${LINA}"]`)); await sleep(150);
  const pin = d.querySelector('#kd-new');
  check(pin && pin.getAttribute('inputmode') === 'numeric', 'the PIN dialog: a number field');
  pin.value = '12'; click(w, d.querySelector('.modal [data-m="save"]')); await sleep(200);
  check(/4 to 6 digits/.test(d.querySelector('#kd-err')?.textContent || ''), 'too short: says so');
  pin.value = '2468'; click(w, d.querySelector('.modal [data-m="save"]'));
  check(await until(() => !d.querySelector('#kd-new') && /PIN saved for Lina/.test(d.querySelector('#toast')?.textContent || '')), 'saved: ' + (d.querySelector('#toast')?.textContent || ''));
  check(await until(() => /PIN on/.test(d.querySelector(`#view [data-act="fam-pin"][data-kid="${LINA}"]`)?.textContent || '')), 'the card says "PIN on"');
  w.close();

  // ================= #1551: the child with a PIN
  log = [];
  w = await kidBoot(log); d = w.document;
  check(w.eval('S.kids[0].pin') === true && !w.eval('S.kids[0].pin_open'), 'the child knows: PIN on, closed');
  const kt = d.querySelector(`#view [data-act="kid-tick"][data-id="${KT.id}"]`);
  click(w, kt);
  check(await until(async () => (await call('GET', '/api/state', null, w.__cookie)).tasks.find(t => t.id === KT.id)?.status === 2) && !d.querySelector('.kdpin'), 'ticking off needs no PIN');
  w.eval("topMoreItems().find(x => x.label === 'Settings').fn()"); await sleep(200);
  check(d.querySelector('.kdpin #kd-pin')?.getAttribute('inputmode') === 'numeric' && !d.querySelector('.smodal'), 'Settings: the PIN field first');
  d.querySelector('#kd-pin').value = '1111'; click(w, d.querySelector('.kdpin [data-m="ok"]'));
  check(await until(() => /Wrong PIN\. 4 tries left/.test(d.querySelector('#kd-pinmsg')?.textContent || '')), 'a wrong PIN: a calm message ' + (d.querySelector('#kd-pinmsg')?.textContent || ''));
  d.querySelector('#kd-pin').value = '2468'; click(w, d.querySelector('.kdpin [data-m="ok"]'));
  check(await until(() => !d.querySelector('.kdpin') && d.querySelector('.smodal')), 'the right PIN opens Settings');
  w.eval('$$(".modal").forEach(m => m.remove())');
  w.eval('S.kids[0].pin_open = null'); w.eval('logout()'); await sleep(200);
  check(d.querySelector('.kdpin') && w.eval('S.me') && w.eval('S.me.kid'), 'Log out: the PIN field first');
  check(!log.some(x => / 403$/.test(x) && !/pin\/unlock/.test(x)), 'no other write refused ' + JSON.stringify(log));
  w.close();

  console.log(`p249_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
