// 2.397.0 (#3404) UI tests (jsdom), fresh DB: every workspace keeps its view on this device (LS wsView, workspace.js)
// - a person without an organisation: the switch changes nothing and keeps nothing (no workspaces)
// - organisation (a list, its task open) -> Private (first visit: the organisation's list is not there -> the inbox, the task
//   closes) -> a private list, scrolled, a sidebar group folded -> organisation: its list and its task again, its sidebar group
//   -> All (keeps the page; changes there are not written back) -> Private: its list at its scroll position
// - a link into the other workspace (wsFollow): the target wins and becomes that workspace's kept view
// - a reload (same device) keeps both views
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
// jsdom draws no layout: the view gets a fixed height so a scroll position can be kept and restored
const tall = w => w.eval(`(() => { const v = document.querySelector('#view'); Object.defineProperty(v, 'scrollHeight', {configurable: true, get: () => 5000}); Object.defineProperty(v, 'clientHeight', {configurable: true, get: () => 500}); })()`);

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const P = (await call('POST', '/api/lists', {name: 'Garden', org_id: null})).id;
  const PT = (await call('POST', '/api/tasks', {title: 'Mow', list_id: P})).id;

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

  // Private for the first time: the organisation's list is not part of it -> the inbox, the task closes
  await w.eval(`wsSet('private')`);
  await until(() => w.eval('S.route.key') === 'inbox');
  check(w.eval('S.route.key') === 'inbox', 'first visit of Private: the inbox ' + w.eval('S.route.key'));
  check(w.eval('S.sel') === null, 'first visit of Private: the organisation task closed ' + w.eval('S.sel'));
  // a private list, scrolled, the group "More" folded
  w.location.hash = '#l/' + P; await until(() => w.eval('S.route.key') === 'l:' + P);
  w.eval(`LS.set('sideOpenG', [])`);
  tall(w); w.eval(`document.querySelector('#view').scrollTop = 1234`);

  // back to the organisation: its list, its task, its open group
  await w.eval(`wsSet('${OW}')`);
  await until(() => w.eval('S.route.key') === 'l:' + W && w.eval('S.sel') === WT);
  check(w.eval('S.route.key') === 'l:' + W, 'organisation again: its list ' + w.eval('S.route.key'));
  check(w.eval('S.sel') === WT, 'organisation again: its task open again ' + w.eval('S.sel'));
  check(w.eval(`JSON.stringify(LS.get('sideOpenG'))`) === '["more"]', 'organisation again: its sidebar group open ' + w.eval(`JSON.stringify(LS.get('sideOpenG'))`));

  // All: the page stays; what is done there does not change Private's view
  await w.eval(`wsSet('all')`); await sleep(300);
  check(w.eval('S.route.key') === 'l:' + W && w.eval('S.sel') === WT, 'All keeps the page shown ' + w.eval('S.route.key'));
  w.eval('closeDetail()');
  w.location.hash = '#inbox'; await until(() => w.eval('S.route.key') === 'inbox');
  w.eval(`LS.set('sideOpenG', ['more', 'tags'])`);
  w.eval(`document.querySelector('#view').scrollTop = 0`);

  // Private exactly as it was left
  await w.eval(`wsSet('private')`);
  await until(() => w.eval('S.route.key') === 'l:' + P && w.eval(`document.querySelector('#view').scrollTop`) === 1234);
  check(w.eval('S.route.key') === 'l:' + P, 'Private again: its list ' + w.eval('S.route.key'));
  check(w.eval(`document.querySelector('#view').scrollTop`) === 1234, 'Private again: its scroll position ' + w.eval(`document.querySelector('#view').scrollTop`));
  check(w.eval(`JSON.stringify(LS.get('sideOpenG'))`) === '[]', 'Private again: its sidebar group folded, All wrote nothing back ' + w.eval(`JSON.stringify(LS.get('sideOpenG'))`));
  check(w.eval('S.sel') === null, 'Private again: the organisation task is not open there');
  check(w.eval(`LS.get('wsView', {}).all`) == null, 'All keeps no view of its own');

  // a link into the organisation: the target wins and is what the organisation shows next time
  w.eval(`openDetail(${PT})`);
  w.location.hash = '#inbox'; await until(() => w.eval('S.route.key') === 'inbox');
  w.location.hash = '#l/' + W; await until(() => w.eval('wsCur()') === OW && w.eval('S.route.key') === 'l:' + W);
  check(w.eval('wsCur()') === OW, 'a link into the organisation switches along');
  w.location.hash = '#inbox'; await until(() => w.eval('S.route.key') === 'inbox');
  await w.eval(`wsSet('private')`);
  await until(() => w.eval('S.route.key') === 'inbox' && w.eval('wsCur()') === 'private');
  check(w.eval('S.route.key') === 'inbox', 'Private: the page it was left on before the link ' + w.eval('S.route.key'));
  await w.eval(`wsSet('${OW}')`);
  await until(() => w.eval('S.route.key') === 'inbox' && w.eval('wsCur()') === OW);
  check(w.eval('S.route.key') === 'inbox', 'organisation: the page seen there last (after the link) ' + w.eval('S.route.key'));
  w.location.hash = '#l/' + W; await until(() => w.eval('S.route.key') === 'l:' + W);
  await w.eval(`wsSet('private')`);
  await until(() => w.eval('S.route.key') === 'inbox' && w.eval('wsCur()') === 'private');
  w.location.hash = '#l/' + P; await until(() => w.eval('S.route.key') === 'l:' + P);
  w.dispatchEvent(new w.Event('pagehide'));
  w.close();

  // a reload on the same device keeps both views
  await until(async () => (await call('GET', '/api/state')).settings.workspace === 'private');
  w = await boot({user: 'alice', hash: 'l/' + P, shared});
  await until(() => w.eval('S.route.key') === 'l:' + P && w.eval('wsCur()') === 'private');
  await w.eval(`wsSet('${OW}')`);
  await until(() => w.eval('S.route.key') === 'l:' + W);
  check(w.eval('S.route.key') === 'l:' + W, 'after a reload: the organisation\'s list ' + w.eval('S.route.key'));
  await w.eval(`wsSet('private')`);
  await until(() => w.eval('S.route.key') === 'l:' + P);
  check(w.eval('S.route.key') === 'l:' + P, 'after a reload: Private\'s list ' + w.eval('S.route.key'));

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
