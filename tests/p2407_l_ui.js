// kalmido-suite:
// 2.407.0 UI tests of the lead (job), own container (start.sh), Firefox (1440 x 900):
// - #3518: a list in the sidebar with done tasks shows open/total (5/12) and the hint "5 open · 7 done"; a list without done tasks
//   keeps the single number; a folder sums its lists the same way
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2407_l_ui', check, shots: 'P2407L_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const L = (await call(CA, 'POST', '/api/lists', {name: 'Work'})).id, P = (await call(CA, 'POST', '/api/lists', {name: 'Plain'})).id;
  const Q = (await call(CA, 'POST', '/api/lists', {name: 'Filed'})).id;
  for (let i = 0; i < 12; i++) {
    const t = (await call(CA, 'POST', '/api/tasks', {title: 'Work ' + i, list_id: L})).id;
    if (i < 7) await call(CA, 'POST', `/api/tasks/${t}/complete`);
  }
  for (let i = 0; i < 3; i++) await call(CA, 'POST', '/api/tasks', {title: 'Plain ' + i, list_id: P});
  for (let i = 0; i < 2; i++) {
    const t = (await call(CA, 'POST', '/api/tasks', {title: 'Filed ' + i, list_id: Q})).id;
    if (i < 1) await call(CA, 'POST', `/api/tasks/${t}/complete`);
  }
  await call(CA, 'PATCH', `/api/lists/${Q}`, {folder: 'Box'});

  await firefox(async o => {
    const {ev, nav, cmd, ctx} = o;
    const ready = async (expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(() => 1)`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await nav(B + '#l/' + L);
    const cnt = id => `document.querySelector('#side .srow[data-list="${id}"] .c')`;
    check(await ready(`${cnt(L)}?.textContent === '5/12'`), `#3518: the list with 7 done of 12 shows 5/12 (${await ev(`${cnt(L)}?.textContent`).catch(() => '?')})`);
    check(await ev(`${cnt(L)}?.title === '5 open · 7 done'`), '#3518: the hint names open and done');
    check(await ev(`${cnt(P)}?.textContent === '3' && !${cnt(P)}?.title`), '#3518: a list without done tasks keeps the single number');
    const fc = `document.querySelector('#side .fhead[data-folder="Box"] .c')`;
    check(await ready(`${fc}?.textContent === '1/2'`), `#3518: the folder sums its lists (1/2) (${await ev(`${fc}?.textContent`).catch(() => '?')})`);
    check(await ev(`${fc}?.title === '1 open · 1 done'`), '#3518: the folder hint');
  }, false);

  console.log(`p2407_l_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
