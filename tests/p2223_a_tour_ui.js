// 2.223.0 A (#2821) the welcome tour and links: the automatic start (tour still pending) runs at most once per session and
// only in Projects - a link with a target (#cal, #office) opens that target and the tour waits until one comes back to
// Projects; leaving Projects while it runs pauses it (hidden, keys free), coming back goes on at the same step;
// "Restart the welcome tour" still starts at once. Own container (start.sh, KALMIDO_ONBOARDING=1), jsdom.
// P4: frida and gina have no organisation and run every check.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, KALMIDO_ONBOARDING: '1'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const until = (f, ms) => require('./boot').until(f, {timeout: ms || 15000, step: 100}).then(x => !!x);  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit ms keeps its window
const hashTo = async (w, h) => { w.location.hash = h; await sleep(500); };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fu.http < 300, 'P4: frida (no organisation) ' + fu.http);
  const CF = await login('frida');
  // 2.364.0 (#3032): accounts an admin made first answer "What do you use Kalmido for?" (p2364_a_tour_ui); answered here, this suite is about the tour
  const paskDone = () => execFileSync('python3', [path.join(__dirname, 'dbx.py'), DATA, "UPDATE user_settings SET value='done' WHERE key='purpose_ask'"]);
  paskDone();
  // new accounts start with the tour pending (KALMIDO_ONBOARDING=1); the client can only finish it
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', features: 'cal'});
  check(((await call(CF, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'frida is in no organisation');
  const L = (await call(CF, 'POST', '/api/lists', {name: 'Film'})).id;
  for (let i = 0; i < 3; i++) await call(CF, 'POST', '/api/tasks', {title: `Shoot ${i}`, list_id: L});
  const tour = d => d.querySelector('.tour');
  const shown = d => !!tour(d) && tour(d).style.display !== 'none' && !!d.querySelector('.tour .tcard h3');

  // (1) a link to the calendar: the calendar opens, no tour; back in Projects the tour starts
  let w = await boot({user: 'frida', hash: 'cal'}), d = w.document;
  await sleep(800);
  check(w.eval('S.route.mod') === 'cal' && !tour(d), 'a link to #cal opens the calendar, the tour waits ' + w.eval('S.route.mod'));
  await hashTo(w, 'today');
  check(await until(() => shown(d)), 'back in Projects the tour starts');
  check(d.querySelector('.tour').dataset.step === 'side' && w.eval('TOUR.i') === 0, 'at the first step');
  // (2) leaving Projects pauses it, keys free; coming back goes on at the same step
  w.eval('tourGo(2)');
  await hashTo(w, 'cal');
  check(w.eval('S.route.mod') === 'cal' && !shown(d) && w.eval('TOUR.on && TOUR.paused'), 'in the calendar the tour pauses (hidden) ' + w.eval(`JSON.stringify({m: S.route.mod, on: TOUR.on, p: TOUR.paused, h: location.hash, disp: document.querySelector('.tour')?.style.display})`));
  const ev = new w.KeyboardEvent('keydown', {key: 'ArrowRight', bubbles: true, cancelable: true});
  d.body.dispatchEvent(ev);
  check(w.eval('TOUR.i') === 2, 'while paused the arrow keys do not move the tour');
  await hashTo(w, 'today');
  check(await until(() => shown(d)) && w.eval('TOUR.i') === 2 && !w.eval('TOUR.paused'), 'back in Projects: the same step again');
  check(d.querySelector('.tour').dataset.sel === '#view .trow', 'the step points at a task row ' + d.querySelector('.tour').dataset.sel);
  w.close();

  // (3) a reload in the same session does not start it again (and does not jump to Today)
  const fid = fu.id;
  w = await boot({user: 'frida', hash: 'l/' + L, setup: x => x.sessionStorage.setItem('kalmido-tour-' + fid, '1')}); d = w.document;
  await sleep(800);
  check(!tour(d) && w.eval('S.route.mod') === 'tasks' && w.eval('S.route.key') !== 'today', 'reload in the same session: no tour, the list stays ' + w.eval('S.route.key'));
  // the palette entry still starts it at once
  w.eval('tourStart()');
  check(await until(() => shown(d)), '"Restart the welcome tour" starts at once');
  w.eval('tourEnd(true)'); await sleep(1500);
  w.close();

  // (4) another new account (no organisation either) in Projects: starts once, the key is set
  const gu = await call(CA, 'POST', '/api/users', {username: 'gina', display_name: 'Gina', password: 'password123', email: 'gina@example.com', orgs: []});
  await call(await login('gina'), 'PATCH', '/api/settings', {lang: 'en'});
  paskDone();  // 2.364.0 (#3032)
  w = await boot({user: 'gina', hash: 'today'}); d = w.document;
  check(await until(() => shown(d)), 'a new session in Projects: the tour starts ' + w.eval(`JSON.stringify({t: S.settings.tour, m: S.route.mod, wait: TOUR.wait, on: TOUR.on, ss: sessionStorage.length})`));
  check(w.sessionStorage.getItem('kalmido-tour-' + gu.id) === '1', 'once per session (sessionStorage)');
  w.close();

  console.log(`p2223_a_tour_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
