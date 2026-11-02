// kalmido-suite: fresh
// 2.466.0 (#3314) UI test (jsdom), own container (start.sh, KALMIDO_ONBOARDING=1): the areas' short introductions
//  - the welcome tour goes first; its last card has "Show more introductions" (ticked)
//  - the first opening of an area shows its introduction once, per account (tours_seen); a second opening nothing
//  - unticking on the last card = no more introductions; Settings > Help turns them on again and restarts one
//  - tours_seen rejects anything but a list of ids
// freelancer-matrix: onboarding (frida has no organisation)
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, KALMIDO_ONBOARDING: '1'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {http: r.status, ...j}; };
const until = (f, ms) => require('./boot').until(f, {timeout: ms || 15000, step: 100}).then(x => !!x);
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const toLast = async (w, d) => { for (let i = 0; i < 12 && /Next/.test(d.querySelector('[data-tour="next"]')?.textContent || ''); i++) { click(w, d.querySelector('[data-tour="next"]')); await sleep(60); } };
const step = d => d.querySelector('.tour')?.dataset.step || '';

(async () => {
  await sleep(600);
  check((await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', lang: 'en'})})).ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  check((await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []})).http < 300, 'P4: frida without organisation');
  execFileSync('python3', [path.join(__dirname, 'dbx.py'), DATA, "UPDATE user_settings SET value='done' WHERE key='purpose_ask'"]);
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', features: 'cal,habits'});
  const set = async () => (await call(CF, 'GET', '/api/state')).settings;

  // the server's check of the list
  check((await call(CF, 'PATCH', '/api/settings', {tours_seen: 'cal;<x>'})).http === 400, 'tours_seen: only a list of ids');

  // welcome tour first: Calendar opened by a link stays without its introduction while the tour is pending
  const w = await boot({user: 'frida', hash: 'cal'}), d = w.document;
  await sleep(1200);
  check(!d.querySelector('.tour') && !(await set()).tours_seen, 'the welcome tour is still pending: no introduction of the area');
  w.location.hash = 'today';
  check(await until(() => d.querySelector('.tour .tcard h3')), 'back in Projects: the welcome tour');
  await toLast(w, d);
  check(d.querySelector('.tour #t-more')?.checked === true, 'its last card: "Show more introductions", ticked');
  click(w, d.querySelector('[data-tour="next"]'));
  check(await until(async () => (await set()).tour === 'done'), 'the welcome tour is done');

  // first opening of an area: its introduction, once
  w.location.hash = 'cal';
  check(await until(() => step(d) === 'cal1'), 'the Calendar opens with its introduction');
  check(w.eval('TOUR.steps.length') >= 2 && w.eval('TOUR.steps.length') <= 4, '2-4 steps');
  check(await until(async () => (await set()).tours_seen === 'cal'), 'remembered in tours_seen');
  await toLast(w, d);
  check(d.querySelector('.tour #t-more')?.checked === true, 'the last card of an area has the tick too');
  click(w, d.querySelector('[data-tour="next"]'));
  await until(() => !d.querySelector('.tour'));
  w.location.hash = 'today'; await sleep(300);
  w.location.hash = 'cal'; await sleep(1100);
  check(!d.querySelector('.tour'), 'a second opening shows nothing');

  // unticked: no more introductions
  w.location.hash = 'habits';
  check(await until(() => step(d) === 'habits1'), 'Habits: its own introduction');
  await toLast(w, d);
  const box = d.querySelector('.tour #t-more'); box.checked = false; box.dispatchEvent(new w.Event('change', {bubbles: true}));
  click(w, d.querySelector('[data-tour="next"]'));
  check(await until(async () => (await set()).tours_more === '0'), 'unticked: tours_more 0');

  // Settings > Help: one introduction again; on again by the switch
  w.eval(`settingsModal('help')`);
  check(await until(() => d.querySelector('.smodal [data-m="tour-mod"][data-v="cal"]')), 'Settings > Help lists the areas that are on');
  check(!d.querySelector('.smodal [data-m="tour-mod"][data-v="office"]'), 'an area that is off is not listed');
  check(d.querySelector('.smodal #s-tmore')?.checked === false, 'the switch shows the unticked state');
  click(w, d.querySelector('.smodal [data-m="tour-mod"][data-v="cal"]'));
  check(await until(() => step(d) === 'cal1'), 'Settings > Help restarts one area');
  w.eval('tourEnd(true)'); await until(() => !d.querySelector('.tour'));
  w.eval(`S.settings.tours_seen = ''`); w.location.hash = 'today'; await sleep(200); w.location.hash = 'cal'; await sleep(1100);
  check(!d.querySelector('.tour'), 'tours_more 0: nothing starts by itself');
  w.close();

  const fails = F.length; console.log(`p2466_tour_ui: ${ok} ok, ${fails} failed`); process.exit(fails ? 1 : 0);
})().catch(e => { console.log('FAIL:', e); process.exit(1); });
