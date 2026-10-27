// 2.125.0 part B UI test (#2119, #2120), own container (start.sh): monthly timesheets and the time zone of time tracking.
// The time page on "Last month" shows the month's card with "Close month"; closed, the entries show a lock instead of edit /
// delete and the card offers "Reopen"; ONE Undo step opens it again, Redo closes it. The organisation's admin sees the
// closed month of the member in "Timesheets of your team" and approves it there. Settings > Modules > Time tracking: the
// time zone (with the device's zone as a suggestion) and "Entries over midnight" are saved at once.
// P2125B_NOSTART=1 = the server already runs.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2125B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const FEAT = 'time,collab,comments';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments', 'time']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com', orgs: [ORG]});
  const BK = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, BK);
  const L = (await call('POST', '/api/lists', {name: 'Harbour site', time_tracking: true}, BK)).id;
  const n = new Date(), prev = new Date(n.getFullYear(), n.getMonth() - 1, 15, 10, 0);
  const M = `${prev.getFullYear()}-${String(prev.getMonth() + 1).padStart(2, '0')}`;
  const E = await call('POST', '/api/time/entries', {list_id: L, start: prev.toISOString(), minutes: 60, note: 'survey'}, BK);
  check(E.status === 200 && E.id, 'an entry last month');
  const sheet = async (ck = BK) => (await call('GET', '/api/time/sheets?month=' + M, null, ck)).sheet?.state;

  // ================= bob: close the month, the lock, Undo / Redo
  let w = await boot({user: 'bob', hash: 'time'}), d = w.document;
  await until(() => d.querySelector('[data-act="tv-period"][data-k="lastmonth"]'));
  d.querySelector('[data-act="tv-period"][data-k="lastmonth"]').click();
  const card = await until(() => d.querySelector('.tslcard:not(.tslrev)'));
  check(card && /Timesheet/.test(card.textContent) && /Open/.test(card.textContent), 'the month card: open ' + (card?.textContent || '').slice(0, 120));
  card?.querySelector('[data-tsl="close"]')?.click();
  check(await until(async () => (await sheet()) === 'closed'), 'Close month: the server holds it closed');
  check(await until(() => d.querySelector('.tslcard [data-tsl="reopen"]')), 'the card offers Reopen');
  if (!d.querySelector('.timev .terow')) d.querySelector('[data-act="tv-entries"]')?.click();
  const row = await until(() => [...d.querySelectorAll('.timev .terow')].find(r => /survey/.test(r.textContent)));
  check(row && row.querySelector('.tslock') && !row.querySelector('[data-act="te-edit"]') && !row.querySelector('[data-act="te-del"]'),
    'the entry shows a lock, no edit / delete');
  await w.eval(`histStep('undo')`);
  check(await until(async () => (await sheet()) === 'open'), 'Undo: open again (one step)');
  await w.eval(`histStep('redo')`);
  check(await until(async () => (await sheet()) === 'closed'), 'Redo: closed again');
  w.close();

  // ================= alice: the team card, approve
  w = await boot({user: 'alice', hash: 'time'}); d = w.document;
  const rev = await until(() => d.querySelector('.tslrev'));
  check(rev && /Bob/.test(rev.textContent) && /1:00|1 h/.test(rev.textContent), 'the admin sees bob\'s closed month with its hours ' + (rev?.textContent || '').slice(0, 160));
  rev?.querySelector('[data-tsl="approve"]')?.click();
  check(await until(async () => (await sheet()) === 'approved'), 'approved from the card');
  w.close();

  // ================= bob: the approved month, the settings of time tracking
  w = await boot({user: 'bob', hash: 'time'}); d = w.document;
  await until(() => d.querySelector('[data-act="tv-period"][data-k="lastmonth"]'));
  d.querySelector('[data-act="tv-period"][data-k="lastmonth"]').click();
  const c2 = await until(() => [...d.querySelectorAll('.tslcard')].find(x => /Approved by Alice/.test(x.textContent)));
  check(c2 && !c2.querySelector('[data-tsl="reopen"]'), 'approved: no Reopen for bob');
  w.eval(`settingsModal('time')`); await sleep(400);
  const md = d.querySelector('.smodal');
  const tz = md?.querySelector('#s-ttz'), sp = md?.querySelector('#s-tsplit');
  check(tz && [...tz.options].some(o => o.value === 'America/New_York') && tz.value === '', 'the time zone: the server\'s by default, IANA names offered');
  check(sp && sp.checked, 'entries over midnight: split by default');
  if (tz) { tz.value = 'America/New_York'; tz.dispatchEvent(new w.Event('change', {bubbles: true})); }
  await sleep(500);
  if (sp) { sp.checked = false; sp.dispatchEvent(new w.Event('change', {bubbles: true})); }
  const st = await until(async () => { const s = (await call('GET', '/api/state', null, BK)).settings; return s.tz === 'America/New_York' && s.time_split_midnight === '0' ? s : null; });
  check(st, 'both settings saved');
  md?.remove();
  w.close();

  check(errs.length === 0, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
