// 2.484.0 C UI test (#3950), own container (start.sh, mode workspaces). jsdom, invented data only.
// - a deliberate switch (wsSet) from a private-only page (Habits) into an organisation is completed: the organisation's start
//   page, the workspace stays the organisation, no note; also when the organisation's kept view is itself a private page
// - Kalmido switching by itself (a link to a private module in an organisation, wsFollow): a note "Switched to ..." with
//   "Back", which brings the workspace before back (on its start page, the private page does not exist there)
// kalmido-suite: fresh
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, undoToast} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const toastText = w => { const t = w.document.querySelector('#toast'); return t && !t.classList.contains('hidden') ? t.textContent : ''; };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments', 'habits', 'review', 'stats', 'time']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,habits,review,stats,time,pomo,contracts,family'});
  const me = (await call('GET', '/api/state')).me.id;
  const ORG = (await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me})).id, OW = 'org:' + ORG;

  // ---- a deliberate switch from Habits in Private into the organisation
  await call('PATCH', '/api/settings', {workspace: 'private'});
  let w = await boot({user: 'alice', hash: 'habits', ls: {'tasks.ws': '"private"'}});
  await until(() => w.eval('S.route.mod') === 'habits' && w.eval('S.booted'));
  await w.eval(`wsSet('${OW}')`);
  await until(() => w.eval('S.route.mod') !== 'habits');
  await sleep(300);
  check(w.eval('wsCur()') === OW, '#3950: the workspace is the organisation ' + w.eval('wsCur()'));
  // 2.497.0 (#4048): the area does not exist in the organisation -> Start (the page called Start, was the inbox)
  check(w.eval('S.route.mod') === 'home', '#3950: its start page is shown ' + w.eval('S.route.mod + "/" + S.route.key'));
  check(!/Switched to/.test(toastText(w)), '#3950: a deliberate switch gives no note');
  await until(async () => ((await call('GET', '/api/state')).settings || {}).workspace === OW);
  check(((await call('GET', '/api/state')).settings || {}).workspace === OW, '#3950: the server knows the organisation');
  w.close();

  // ---- the organisation's kept view is a private page itself
  await call('PATCH', '/api/settings', {workspace: 'private'});
  w = await boot({user: 'alice', hash: 'today', ls: {'tasks.ws': '"private"', 'tasks.wsView': JSON.stringify({[OW]: {hash: 'habits', ls: {}}})}});
  await until(() => w.eval('S.booted') && w.eval('S.route.key') === 'today');
  await w.eval(`wsSet('${OW}')`);
  await until(() => w.eval('wsCur()') === OW);
  await sleep(400);
  check(w.eval('wsCur()') === OW && w.eval('S.route.mod') !== 'habits', '#3950: a kept private page is not restored in the organisation ' + w.eval('wsCur() + " " + S.route.mod'));
  w.close();

  // ---- Kalmido switches by itself: a link to a private module while the organisation is shown
  await call('PATCH', '/api/settings', {workspace: OW});
  w = await boot({user: 'alice', hash: 'today', ls: {'tasks.ws': JSON.stringify(OW)}});
  await until(() => w.eval('S.booted') && w.eval('wsCur()') === OW && w.eval('S.route.key') === 'today');
  w.eval(`go('habits')`);
  await until(() => w.eval('S.route.mod') === 'habits');
  check(w.eval('wsCur()') === 'private', '#3950: the link opens the page in Private');
  check(/Switched to Private/.test(await until(() => toastText(w)) || ''), '#3950: a note says where Kalmido went ' + toastText(w));
  check(await undoToast(w, /Switched to/), '#3950: the note has a Back button');
  await until(() => w.eval('wsCur()') === OW);
  await until(() => w.eval('S.route.mod') !== 'habits');
  check(w.eval('wsCur()') === OW && w.eval('S.route.mod') !== 'habits', '#3950: Back = the organisation, on a page it has ' + w.eval('wsCur() + " " + S.route.mod'));
  w.close();

  console.log(`p2484_c_ws_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERR', e); process.exit(1); });
