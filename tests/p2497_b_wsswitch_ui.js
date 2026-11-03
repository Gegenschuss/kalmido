// 2.497.0 B UI test (#4048), own container (start.sh, mode workspaces). jsdom, invented data only.
// A workspace switch stays in the area shown (#3404's page per workspace is gone):
// - Projects (the overview) private -> organisation stays Projects; a page every workspace has stays (Calendar)
// - a single object not in the target -> the overview of the same area (a project's notes -> Notes, a knowledge page -> Knowledge)
// - a list of Private -> the inbox of the target; a project of Private (kind project) -> Projects of the target
// - an area that is off in the target (ws_areas_off) or a private module (Habits) -> Start
// - an open task stays when the target shows it (inbox task, "All"), else it closes; no page comes back from the last visit
// - the same on a phone's width (mobile: drawer stays open, #3847)
// - o.keep (a link's own target follows) still only follows the filter
// kalmido-suite: fresh
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments', 'habits', 'wiki']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,habits,wiki'});
  const me = (await call('GET', '/api/state')).me.id;
  const ORG = (await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me})).id, OW = 'org:' + ORG;
  const P = (await call('POST', '/api/lists', {name: 'Garden', org_id: null})).id;
  const O = (await call('POST', '/api/lists', {name: 'Website', org_id: ORG})).id;
  const PP = (await call('POST', '/api/lists', {name: 'Renovation', org_id: null, kind: 'project'})).id;
  const PT = (await call('POST', '/api/tasks', {title: 'Mow', list_id: P})).id;
  const OT = (await call('POST', '/api/tasks', {title: 'Deploy', list_id: O})).id;
  const IT = (await call('POST', '/api/tasks', {title: 'Sort', list_id: (await call('GET', '/api/state')).lists.find(l => l.is_inbox).id})).id;

  // boots in Private on the page; the switch is awaited (wsSet ends after its route)
  const start = async (hash, ws = 'private', o = {}) => {
    await call('PATCH', '/api/settings', {workspace: ws});
    const w = await boot({user: 'alice', hash, ls: {'tasks.ws': JSON.stringify(ws)}, ...o});
    await until(() => w.eval('S.booted') && w.eval('wsCur()') === ws);
    return w;
  };
  const at = w => w.eval('S.route.mod + "/" + S.route.key + " " + location.hash');
  const sw = async (w, ws) => { await w.eval(`wsSet(${JSON.stringify(ws)})`); check(w.eval('wsCur()') === ws, 'switched to ' + ws); };

  for (const mobile of [false, true]) {
    const tag = mobile ? '390 px: ' : '';
    // ---- Projects stays Projects, both ways; no page comes back from the visit before
    let w = await start('projects', 'private', {mobile});
    await sw(w, OW);
    check(w.eval('S.route.key') === 'projects', tag + 'Projects private -> organisation: stays Projects ' + at(w));
    w.location.hash = '#cal'; await until(() => w.eval('S.route.mod') === 'cal');
    await sw(w, 'private');
    check(w.eval('S.route.mod') === 'cal', tag + 'Calendar -> Private: stays the calendar, not the page left there ' + at(w));
    await sw(w, OW);
    check(w.eval('S.route.mod') === 'cal', tag + 'Calendar -> organisation: stays the calendar ' + at(w));
    w.close();

    // ---- an open project of Private -> the target's Projects overview, not the inbox and not Start
    w = await start('l/' + PP, 'private', {mobile});
    await until(() => w.eval('S.route.key') === 'l:' + PP);
    await sw(w, OW);
    check(w.eval('S.route.mod') === 'tasks' && w.eval('S.route.key') === 'projects' && w.location.hash === '#projects', tag + 'a private project -> Projects of the organisation ' + at(w));
    w.close();

    // ---- a list of Private -> the target's inbox
    w = await start('l/' + P, 'private', {mobile});
    await until(() => w.eval('S.route.key') === 'l:' + P);
    await sw(w, OW);
    check(w.eval('S.route.mod') === 'tasks' && w.eval('S.route.key') === 'inbox', tag + 'a private list -> the inbox of the organisation ' + at(w));
    check(w.location.hash === '#inbox', tag + 'the address follows ' + w.location.hash);
    w.close();

    // ---- single objects -> the overview of the same area
    w = await start('notes/' + P, 'private', {mobile});
    await until(() => w.eval('S.route.mod') === 'notes');
    await sw(w, OW);
    check(w.eval('S.route.mod') === 'notes' && w.location.hash === '#notes', tag + 'a private project\'s notes -> Notes in the organisation ' + at(w));
    w.close();
    w = await start('wiki/99999', 'private', {mobile});
    await until(() => w.eval('S.route.mod') === 'wiki');
    await sw(w, OW);
    check(w.eval('S.route.mod') === 'wiki' && w.location.hash === '#wiki', tag + 'a knowledge page -> Knowledge in the organisation ' + at(w));
    w.close();

    // ---- the area is not there -> Start: a private module, an area off for the target
    w = await start('habits', 'private', {mobile});
    await until(() => w.eval('S.route.mod') === 'habits');
    await sw(w, OW);
    check(w.eval('S.route.mod') === 'home', tag + 'Habits -> organisation: Start ' + at(w));
    w.close();
    await call('PATCH', '/api/settings', {ws_areas_off: JSON.stringify({[OW]: ['wiki']})});
    w = await start('wiki', 'private', {mobile});
    await until(() => w.eval('S.route.mod') === 'wiki');
    await sw(w, OW);
    check(w.eval('S.route.mod') === 'home', tag + 'Knowledge off in the organisation: Start ' + at(w));
    check(w.eval('S.route.mod') === 'home' && w.eval(`feat('wiki')`) === false, tag + 'the area is really off there');
    w.close();
    await call('PATCH', '/api/settings', {ws_areas_off: '{}'});

    // ---- the open task
    w = await start('inbox', 'private', {mobile});
    await until(() => w.eval('S.route.key') === 'inbox' && w.eval(`!!taskById(${IT})`));
    w.eval(`openDetail(${IT})`);
    await sw(w, OW);
    check(w.eval('S.sel') === IT, tag + 'a task of the inbox stays open (the organisation shows it) ' + w.eval('S.sel'));
    w.eval('closeDetail()');
    w.eval(`openDetail(${PT})`);
    await sw(w, 'private');
    check(w.eval('S.sel') === PT, tag + 'Private shows its own task');
    await sw(w, OW);
    check(w.eval('S.sel') === null, tag + 'a private task closes in the organisation ' + w.eval('S.sel'));
    check(w.eval('S.route.key') === 'inbox', tag + 'and the page stays ' + at(w));
    w.eval(`openDetail(${OT})`);
    await sw(w, 'all');
    check(w.eval('S.sel') === OT, tag + '"All" keeps the task and the page ' + w.eval('S.sel'));
    await sw(w, OW);
    check(w.eval('S.sel') === OT, tag + 'back in its organisation it stays ' + w.eval('S.sel'));
    await sw(w, 'private');
    check(w.eval('S.sel') === null, tag + 'in Private the organisation\'s task closes ' + w.eval('S.sel'));
    w.close();

    // ---- from "All" an object of the target stays, the state per workspace still comes back
    w = await start('l/' + O, 'all', {mobile});
    await until(() => w.eval('S.route.key') === 'l:' + O);
    await sw(w, OW);
    check(w.eval('S.route.key') === 'l:' + O, tag + 'All -> its organisation: the list stays ' + at(w));
    w.eval(`LS.set('sideOpenG', ['more'])`);
    await sw(w, 'private');
    w.eval(`LS.set('sideOpenG', [])`);
    await sw(w, OW);
    check(w.eval(`JSON.stringify(LS.get('sideOpenG'))`) === '["more"]', tag + 'the sidebar\'s open groups stay per workspace ' + w.eval(`JSON.stringify(LS.get('sideOpenG'))`));
    w.close();

    // ---- o.keep: only the filter (the caller opens its own target afterwards)
    w = await start('cal', 'private', {mobile});
    await until(() => w.eval('S.route.mod') === 'cal');
    await w.eval(`wsSet(${JSON.stringify(OW)}, {keep: true})`);
    check(w.eval('wsCur()') === OW && w.eval('S.route.mod') === 'cal', tag + 'o.keep: the page stays ' + at(w));
    w.close();
  }

  console.log(`p2497_b_wsswitch_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERR', e); process.exit(1); });
