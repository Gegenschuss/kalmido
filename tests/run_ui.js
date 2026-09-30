// Package D2 UI tests (jsdom), fresh DB: the running indicator in the top bar. One chip per kind (time tracking,
// focus session, stopwatch) with its own icon, time and task; "2 running" when a timer and a focus session run at
// once; the popover with the task and Pause / Stop per kind; the marker in the task details; the chip in the
// Settings header; the start buttons' labels; German.
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json(); };
const until = async (fn, ms = 4000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (await fn()) return true; await sleep(100); } return false; };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  const P = (await call('POST', '/api/lists', {name: 'Client work', kind: 'project'})).id;
  const t = (await call('POST', '/api/tasks', {title: 'Write the offer', list_id: P})).id;
  await call('POST', '/api/time/start', {task_id: t});
  let w = await boot({user: 'alice', hash: 'l/' + P}); let d = w.document;
  let chip = d.querySelector('#top .tmini.run');
  check(chip && chip.classList.contains('k-time') && /Write the offer/.test(chip.textContent) && chip.querySelector('[data-timer-mini]'), 'time tracking: chip with clock, time and task');
  check(/Time tracking: Write the offer/.test(chip.title), 'chip tooltip names the kind');
  await call('POST', '/api/pomo/start', {kind: 'focus', minutes: 25, task_id: t});
  await w.eval('load()'); w.eval('render()');
  chip = d.querySelector('#top .tmini.run');
  check(chip && chip.classList.contains('multi') && /2 running/.test(chip.textContent) && chip.querySelectorAll('.rk').length === 2, 'timer + focus: one "2 running" chip with both icons');
  click(w, chip); await sleep(100);
  let pop = d.querySelector('#pop:not(.hidden)');
  check(pop && pop.querySelectorAll('.runrow').length === 2 && /Time tracking/.test(pop.textContent) && /Focus session/.test(pop.textContent) && /Write the offer/.test(pop.textContent), 'popover: both, with the task');
  check([...pop.querySelectorAll('button')].some(b => /Pause/.test(b.textContent)) && [...pop.querySelectorAll('button')].some(b => /Stop timer/.test(b.textContent)), 'popover: Pause + Stop per kind');
  [...pop.querySelectorAll('button')].find(b => /Stop focus session/.test(b.textContent)).click();
  check(await until(async () => (await call('GET', '/api/state')).pomo === null), 'Stop focus session: ended on the server');
  check(await until(() => d.querySelector('#top .tmini.run.k-time')), 'back to the single time chip');
  w.eval(`openDetail(${t})`); await sleep(300);
  // 2.4.1 (#385): the footer has no timer button any more; the running timer shows as its pill there, Stop is in the Time section
  check(d.querySelector('#detail .dfoot .drun.k-time [data-timer-mini]') && !d.querySelector('#detail .dfoot [data-act="timer-toggle"]'), 'task details: the footer shows the running time as a pill');
  check(d.querySelector('#d-time [data-act="timer-toggle"].recon [data-timer-live]'), 'the Time section: Stop with the running time');
  w.eval('closeDetail()');
  w.eval(`settingsModal()`); await sleep(300);
  check(!d.querySelector('.smodal .shdr .tmini'), 'Settings header: no second chip (1.5)');
  d.querySelectorAll('.modal').forEach(m => m.remove());
  click(w, d.querySelector('#top .tmini.run')); await sleep(100);
  [...d.querySelectorAll('#pop button')].find(b => /Stop timer/.test(b.textContent)).click();
  check(await until(() => !d.querySelector('#top .tmini')), 'Stop timer: chip gone');
  // stopwatch: own icon, pause from the popover
  await call('POST', '/api/pomo/start', {kind: 'stopwatch', minutes: 0});
  await w.eval('load()'); w.eval('render()');
  chip = d.querySelector('#top .tmini.run');
  check(chip && chip.classList.contains('k-stopwatch') && chip.querySelector('[data-pomo-mini]'), 'stopwatch: its own chip');
  click(w, chip); await sleep(100);
  [...d.querySelectorAll('#pop button')].find(b => /Pause/.test(b.textContent)).click();
  check(await until(async () => !!(await call('GET', '/api/state')).pomo?.paused_at), 'Pause from the popover');
  check(await until(() => d.querySelector('#top .tmini.run.paused')), 'paused chip');
  click(w, d.querySelector('#top .tmini.run')); await sleep(100);
  [...d.querySelectorAll('#pop button')].find(b => /Stop stopwatch/.test(b.textContent)).click();
  check(await until(() => !d.querySelector('#top .tmini')), 'Stop stopwatch: gone');
  w.eval("go('pomo')"); await sleep(200);
  check(d.querySelector('[data-act="pomo-start"]').getAttribute('aria-label') === 'Start focus session', 'focus start button labelled');
  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  w.close();
  // German
  await call('PATCH', '/api/settings', {lang: 'de'});
  await call('POST', '/api/pomo/start', {kind: 'focus', minutes: 25, task_id: t});
  w = await boot({user: 'alice', hash: 'l/' + P}); d = w.document;
  chip = d.querySelector('#top .tmini.run');
  check(chip && /Fokus-Sitzung/.test(chip.title), 'German: Fokus-Sitzung');
  click(w, chip); await sleep(100);
  check(/Fokus-Sitzung beenden/.test(d.querySelector('#pop').textContent), 'German popover');
  w.close();
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
