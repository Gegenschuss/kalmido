// 2.397.0 (#3404) UI tests (jsdom), fresh DB: every workspace keeps its state on this device (LS wsView, workspace.js)
// 2.497.0 (#4048): the page is no longer part of it: a switch stays in the area shown (tests/p2497_b_wsswitch_ui.js has the
// target rules); what is kept per workspace are the sidebar's groups and folders and the choices of its areas
// - a person without an organisation: the switch changes nothing and keeps nothing (no workspaces)
// - organisation (a list, its task open) -> Private (the list is not there -> the inbox, the task closes) -> a private list, a
//   sidebar group folded -> organisation: the inbox (no page and no task come back), its sidebar group
//   -> All (keeps the page; changes there are not written back) -> Private: its sidebar group
// - a link into the other workspace (wsFollow): the target wins, the filter follows
// - a reload (same device) keeps the state of both
// kalmido-suite: fresh
// Without an organisation (P4): no route is new; the switch needs an organisation, the first block checks it does nothing
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const P = (await call('POST', '/api/lists', {name: 'Garden', org_id: null})).id;

  // without an organisation: nothing to switch, nothing kept
  {
    const w = await boot({user: 'alice', hash: 'l/' + P});
    await until(() => w.eval('S.route.key') === 'l:' + P);
    check(w.eval('wsOn()') === false, 'freelancer: no workspaces');
    await w.eval(`wsSet('private')`); await sleep(300);
    check(w.eval('S.route.key') === 'l:' + P, 'freelancer: the switch keeps the page ' + w.eval('S.route.key'));
    check(w.eval(`LS.get('wsView', null)`) === null, 'freelancer: no view kept');
    w.close();
  }

  await call('POST', '/api/admin/setup', {org_name: 'Example Org', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id, OW = 'org:' + ORG;
  const W = (await call('POST', '/api/lists', {name: 'Website', org_id: ORG})).id;
  const WT = (await call('POST', '/api/tasks', {title: 'Deploy', list_id: W})).id;
  const shared = {store: {}, wins: []};

  let w = await boot({user: 'alice', hash: 'l/' + W, shared});
  await until(() => w.eval('S.route.key') === 'l:' + W);
  await w.eval(`wsSet('${OW}')`);
  await until(() => w.eval('S.route.key') === 'l:' + W && w.eval('wsCur()') === OW);
  w.eval(`LS.set('sideOpenG', ['more'])`);
  w.eval(`openDetail(${WT})`);
  check(w.eval('S.sel') === WT, 'organisation: its task is open');

  // Private: the organisation's list is not part of it -> the inbox, the task closes
  await w.eval(`wsSet('private')`);
  await until(() => w.eval('S.route.key') === 'inbox');
  check(w.eval('S.route.key') === 'inbox', 'Private: the inbox ' + w.eval('S.route.key'));
  check(w.eval('S.sel') === null, 'Private: the organisation task closed ' + w.eval('S.sel'));
  // a private list, the group "More" folded
  w.location.hash = '#l/' + P; await until(() => w.eval('S.route.key') === 'l:' + P);
  w.eval(`LS.set('sideOpenG', [])`);

  // 2.497.0 (#4048): back to the organisation: the private list is not there -> the inbox; its list and its task do not come back, its open group does
  await w.eval(`wsSet('${OW}')`);
  await until(() => w.eval('S.route.key') === 'inbox');
  check(w.eval('S.route.key') === 'inbox', 'organisation again: the inbox, not the page left there ' + w.eval('S.route.key'));
  check(w.eval('S.sel') === null, 'organisation again: the task left open there does not come back ' + w.eval('S.sel'));
  check(w.eval(`JSON.stringify(LS.get('sideOpenG'))`) === '["more"]', 'organisation again: its sidebar group open ' + w.eval(`JSON.stringify(LS.get('sideOpenG'))`));

  // All: the page stays; what is done there does not change Private's state
  w.location.hash = '#l/' + W; await until(() => w.eval('S.route.key') === 'l:' + W);
  w.eval(`openDetail(${WT})`);
  await w.eval(`wsSet('all')`); await sleep(300);
  check(w.eval('S.route.key') === 'l:' + W && w.eval('S.sel') === WT, 'All keeps the page shown ' + w.eval('S.route.key'));
  w.eval('closeDetail()');
  w.eval(`LS.set('sideOpenG', ['more', 'tags'])`);

  // 2.497.0 (#4048): Private: the list of the organisation is not there -> the inbox; its own sidebar state, All wrote nothing back
  await w.eval(`wsSet('private')`);
  await until(() => w.eval('S.route.key') === 'inbox');
  check(w.eval('S.route.key') === 'inbox', 'Private again: the inbox ' + w.eval('S.route.key'));
  check(w.eval(`JSON.stringify(LS.get('sideOpenG'))`) === '[]', 'Private again: its sidebar group folded, All wrote nothing back ' + w.eval(`JSON.stringify(LS.get('sideOpenG'))`));
  check(w.eval(`LS.get('wsView', {}).all`) == null, 'All keeps no state of its own');
  check(w.eval(`Object.values(LS.get('wsView', {})).every(v => !('hash' in v))`), '2.497.0 (#4048): no page is kept per workspace');

  // a link into the organisation: the target wins and the filter follows
  w.location.hash = '#l/' + W; await until(() => w.eval('wsCur()') === OW && w.eval('S.route.key') === 'l:' + W);
  check(w.eval('wsCur()') === OW, 'a link into the organisation switches along');
  // a link (wsFollow) changes only the filter, it brings no kept state back: the sidebar groups shown now become the organisation's on the next save
  w.eval(`LS.set('sideOpenG', ['more'])`);
  await w.eval(`wsSet('private')`);
  await until(() => w.eval('S.route.key') === 'inbox' && w.eval('wsCur()') === 'private');
  w.eval(`LS.set('sideOpenG', ['tags'])`);
  w.dispatchEvent(new w.Event('pagehide'));
  w.close();

  // a reload on the same device keeps the state of both, not their pages
  await until(async () => (await call('GET', '/api/state')).settings.workspace === 'private');
  w = await boot({user: 'alice', hash: 'inbox', shared});
  await until(() => w.eval('S.route.key') === 'inbox' && w.eval('wsCur()') === 'private');
  await w.eval(`wsSet('${OW}')`);
  await until(() => w.eval('wsCur()') === OW);
  check(w.eval('S.route.key') === 'inbox', 'after a reload: the page stays ' + w.eval('S.route.key'));
  check(w.eval(`JSON.stringify(LS.get('sideOpenG'))`) === '["more"]', 'after a reload: the organisation\'s sidebar group ' + w.eval(`JSON.stringify(LS.get('sideOpenG'))`));
  await w.eval(`wsSet('private')`);
  check(w.eval(`JSON.stringify(LS.get('sideOpenG'))`) === '["tags"]', 'after a reload: Private\'s sidebar group ' + w.eval(`JSON.stringify(LS.get('sideOpenG'))`));

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
