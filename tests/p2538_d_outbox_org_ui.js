// kalmido-suite: fresh
// 2.538.0 part D (#4369, jsdom, mode workspaces): leaving an organisation clears its entries from the offline queue.
// A member makes changes offline in a project of the organisation (a new task, a rename, a follow-up change of the task created
// offline), in a private project and a private task; the leave dialog line counts only the organisation's entries; after leaving
// (the real route) the organisation's entries are gone from the queue and from the device's store, the private ones stay and are
// still sent. Entries of another organisation stay too.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2538D_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: `${process.env.EXTRA || ''} -e KALMIDO_INSTANCE_MODE=workspaces`}});
const ck = {};
const call = async (who, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck[who]}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, j: await r.json().catch(() => ({}))}; };
const until = fn => require('./boot').until(fn, {timeout: 15000, step: 150});

(async () => {
  check((await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', lang: 'en'})})).ok, 'setup');
  ck.alice = await login('alice');
  await call('alice', 'POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const ids = {};
  const mkUser = async (u, orgs) => (await call('alice', 'POST', '/api/users', {username: u, display_name: u[0].toUpperCase() + u.slice(1), password: 'password123', email: `${u}@example.com`, orgs})).j.id;
  ids.bob = await mkUser('bob', []);
  const alpha = (await call('alice', 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: ids.bob})).j.id;
  const beta = (await call('alice', 'POST', '/api/admin/orgs', {name: 'Beta', admin_id: ids.bob})).j.id;
  ck.bob = await login('bob');
  ids.carol = await mkUser('carol', [alpha, beta]);  // the instance admin places her in both
  ck.carol = await login('carol');
  await call('carol', 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'collab,comments'});
  const orgsOf = async () => ((await call('carol', 'GET', '/api/state')).j.me?.workspaces || []).map(x => x.id);
  check((await orgsOf()).includes(alpha) && (await orgsOf()).includes(beta), 'setup: carol is a member of both organisations');
  const LA = (await call('carol', 'POST', '/api/lists', {name: 'Alpha plan', org_id: alpha})).j.id;
  const LB = (await call('carol', 'POST', '/api/lists', {name: 'Beta plan', org_id: beta})).j.id;
  const LP = (await call('carol', 'POST', '/api/lists', {name: 'Mine'})).j.id;
  const TA = (await call('carol', 'POST', '/api/tasks', {title: 'Alpha task', list_id: LA})).j.id;
  const TP = (await call('carol', 'POST', '/api/tasks', {title: 'Private task', list_id: LP})).j.id;
  check(!!LA && !!LB && !!LP && !!TA && !!TP, 'setup: projects and tasks');

  const w = await boot({user: 'carol', hash: 'l/' + LP});
  w.__offline = true;
  const q = () => w.eval('OUT.q.length');
  await w.eval(`api('POST', '/api/tasks', {title: 'New in Alpha', list_id: ${LA}})`);
  await w.eval(`api('PATCH', '/api/tasks/${TA}', {title: 'Renamed in Alpha'})`);
  await w.eval(`api('POST', '/api/tasks', {title: 'New in Beta', list_id: ${LB}})`);
  await w.eval(`api('PATCH', '/api/tasks/${TP}', {title: 'Renamed private'})`);
  await w.eval(`api('POST', '/api/tasks', {title: 'New private', list_id: ${LP}})`);
  check(await q() === 5, `five changes wait on the device ${await q()}`);
  check(w.eval(`outOrgEntries(${alpha}).length`) === 2 && w.eval(`outOrgEntries(${beta}).length`) === 1, `Alpha has 2, Beta 1 ${w.eval(`outOrgEntries(${alpha}).length`)} ${w.eval(`outOrgEntries(${beta}).length`)}`);
  const html = w.eval(`outOrgWarnHtml(outOrgEntries(${alpha}).length)`);
  check(/olvrow warn/.test(html) && /2 changes of this organisation have not been sent yet/.test(html) && w.eval('outOrgWarnHtml(0)') === '', 'the leave dialog line: the count, nothing for 0');

  // leaving: the real route, then what the dialog does afterwards
  check((await call('carol', 'DELETE', `/api/orgs/${alpha}/members/${ids.carol}`)).status === 200, 'carol leaves Alpha');
  check(w.eval(`outOrgDrop(${alpha})`) === 2, 'two entries of Alpha dropped');
  check(await q() === 3, `three left ${await q()}`);
  const titles = () => w.eval('OUT.q').map(x => x.body?.title).sort().join('|');
  check(titles() === 'New in Beta|New private|Renamed private', `Beta and the private ones stay: ${titles()}`);
  const store = () => { try { return JSON.parse(w.localStorage.getItem('tasks.outbox') || '[]').length; } catch { return -1; } };
  check(await until(() => store() === 3 || store() === -1 || w.eval('OBX.on')), 'the device store follows');
  check(w.eval(`outOrgDrop(${alpha})`) === 0, 'a second drop finds nothing');

  // the rest still goes out
  w.__offline = false;
  w.dispatchEvent(new w.Event('online'));
  check(await until(() => w.eval('OUT.q.length') === 0 && !w.eval('OUT.flushing')), 'the remaining entries are sent');
  const all = JSON.stringify((await call('carol', 'GET', '/api/state')).j.tasks || []);
  check(/Renamed private/.test(all) && /New private/.test(all), 'the private changes reached the server');
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
