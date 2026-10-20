// 2.125.0 part C UI tests (#2121 #2122; own container, start.sh). jsdom:
// - the app shortcut /?action=timer: starts the timer (on the list of the latest entry, else the first list with time tracking) and opens the time view, the parameter leaves the URL;
//   the same shortcut again stops it; with the module "time" off nothing starts
// - the "Excel (XLSX)" buttons: time view (same query as the CSV button), workload view (weeks / start / org)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2125C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => {
  for (let i = 0; ; i++) {
    const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined});
    if (r.status === 429 && i < 8) { await sleep(500 * (i + 1)); continue; }
    return r.json().catch(() => ({}));
  }
};

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['cal', 'collab']});
  const FEAT = 'cal,collab,time,workload';
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const L = (await call('POST', '/api/lists', {name: 'Billable', time_tracking: true})).id;  // time is a switch of each list
  check(L > 0, 'setup: a list with time tracking');

  // ---- the shortcut starts the timer
  let w = await boot({user: 'alice', path: '?action=timer'}), d = w.document;
  await sleep(1200);
  check(w.location.search === '', 'the parameter is gone from the URL: ' + w.location.search);
  check(w.location.hash === '#time', 'the time view is open: ' + w.location.hash);
  check(!!w.eval('S.timer'), 'the timer runs');
  let run = (await call('GET', '/api/time/entries?scope=mine')).entries || [];
  const st = await call('GET', '/api/state');
  check(!!st.timer || run.some(e => !e.end), 'the server has a running entry');
  w.close();

  // ---- a reload (parameter gone) does not toggle; the shortcut again stops
  w = await boot({user: 'alice', hash: 'time'}); d = w.document; await sleep(800);
  check(!!w.eval('S.timer'), 'a plain reload leaves the timer running');
  w.close();
  w = await boot({user: 'alice', path: '?action=timer'}); d = w.document; await sleep(1200);
  check(!w.eval('S.timer'), 'the shortcut again stops the timer');
  const ents = (await call('GET', '/api/time/entries?scope=mine')).entries || [];
  check(ents.length === 1 && !!ents[0].end, 'one finished entry, none running: ' + JSON.stringify(ents.map(e => e.end)));

  // ---- the XLSX buttons
  w.location.hash = '#time'; await sleep(1000);
  const a1 = d.querySelector('a[href^="/api/time/export.xlsx"]'), c1 = d.querySelector('a[href^="/api/time/export.csv"]');
  check(a1 && c1 && a1.getAttribute('href').split('?')[1] === c1.getAttribute('href').split('?')[1], 'time view: XLSX button with the query of the CSV button');
  check(a1 && /Excel/.test(a1.textContent), 'time view: the label says Excel');
  w.close();
  w = await boot({user: 'alice', hash: 'workload'}); d = w.document;
  for (let i = 0; i < 20 && !d.querySelector('a[href^="/api/workload/export.xlsx"]'); i++) await sleep(300);
  const a2 = d.querySelector('a[href^="/api/workload/export.xlsx"]');
  check(a2 && /weeks=4/.test(a2.getAttribute('href')), 'workload view: XLSX button ' + (a2 ? a2.getAttribute('href') : (d.querySelector('#view') || {}).innerHTML?.slice(0, 700)));
  w.close();

  // ---- module off: nothing starts
  await call('PATCH', '/api/settings', {features: 'cal,collab,workload'});
  w = await boot({user: 'alice', path: '?action=timer'}); await sleep(1200);
  check(w.location.search === '' && !w.eval('S.timer'), 'module off: the shortcut starts nothing');
  const run2 = ((await call('GET', '/api/time/entries?scope=mine')).entries || []).filter(e => !e.end);
  check(run2.length === 0, 'module off: no running entry on the server');
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERR', e); process.exit(1); });
