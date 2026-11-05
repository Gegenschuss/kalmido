// 2.563.0 A UI test (#4742, start care): Office > Clients (clientpage.js) left the start and loads when it is needed. Own
// kalmido-suite: fresh
// container (start.sh), jsdom, invented data only, a person without an organisation (the same client code for everyone; no
// server route changed).
// - a cold start runs no clientpage.js; the start part of the e-mail filing it held (the mail link of a task, the stand-ins of
//   the client's card and the project page) is at start in lazyload.js and works without it
// - the view Office > Clients loads the module, draws the list and a client's card
// - the modules that use its globals (office, contacts, trash dialogs) load it first
// - before it is loaded, a reload / live change of the clients does nothing (no error)
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.ok ? r.json() : {status: r.status}; };
const until = fn => require('./boot').until(fn, {timeout: 15000, step: 50});
const ran = (w, f) => !!w.document.querySelector(`script[data-ld="${f}"]`);
const fn = (w, n) => w.eval(`typeof ${n}`) === 'function';

(async () => {
  if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  check(r.ok, 'setup');
  const CK = await login('alice');
  await call(CK, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'clients,office,contacts,time,events'});
  const C = await call(CK, 'POST', '/api/clients', {name: 'Example Client 4742', org_id: null});
  check(C.id > 0, 'setup: a client of the private workspace');
  const L = await call(CK, 'POST', '/api/lists', {name: 'Work 4742', kind: 'project', org_id: null});
  const T = await call(CK, 'POST', '/api/tasks', {list_id: L.id, title: 'Task 4742'});
  check(L.id > 0 && T.id > 0, 'setup: a project and a task');

  // ---- a cold start
  let w = await boot({user: 'alice', lazy: true});
  const tags = w.eval(`[...document.querySelectorAll('script[src]')].map(s => s.getAttribute('src'))`);
  check(!tags.some(s => /\/clientpage\.js/.test(s)), 'a cold start runs no clientpage.js');
  check(w.eval(`LD_MODS.clientpage.join()`) === 'clientpage', 'the module names its file');
  check(w.eval(`typeof MSC`) === 'undefined' && !fn(w, 'ms_clCard'), 'its globals are not there yet');
  check(/data-hbmlnk="task:/.test(w.eval(`hbm_taskLinkHtml(taskById(${T.id}) || {id: ${T.id}})`)), 'the mail link of a task draws without the client page');
  check(w.eval(`hbm_linkHtml('event', 0)`) === '' && w.eval(`hbm_projHtml(null)`) === '', 'the e-mail filing stand-ins are at start');
  w.eval(`clReload(); ms_clLive(); 0`);
  await sleep(200);
  check(!ran(w, 'clientpage') && errs.length === 0, 'a reload of the clients before the module does nothing: ' + errs.slice(0, 2).join(' | '));

  // ---- the view loads it
  w.eval(`go('clients')`);
  await until(() => w.document.querySelector('#view .msclients') && /Example Client 4742/.test(w.document.querySelector('#view').textContent));
  check(ran(w, 'clientpage') && w.eval(`typeof MSC`) === 'object', 'Office > Clients loads the module');
  check(/Example Client 4742/.test(w.document.querySelector('#view')?.textContent || ''), 'the list shows the client');
  w.eval(`go('client/${C.id}')`);
  await until(() => w.document.querySelector('#view .ctcard:not(.ctnone)'));
  check(w.document.querySelector('#view .ctcard:not(.ctnone)'), "the client's card is drawn");
  check(w.eval(`hbm_taskLinkHtml(taskById(${T.id}) || {id: ${T.id}})`).includes('data-hbmlnk'), 'the mail link still draws after the module came');
  w.close();

  // ---- the modules that use its globals load it first
  for (const [m, probe] of [['office', 'oim_link'], ['contacts', 'ctk_mapLink'], ['trashui', 'ms_clAct']]) {
    w = await boot({user: 'alice', lazy: true});
    const res = await w.eval(`loadModule('${m}').then(() => 'loaded', e => String(e))`);
    check(res === 'loaded' && ran(w, 'clientpage') && fn(w, probe), `module ${m} loads the client page first (${probe}): ${res}`);
    w.close();
  }

  check(errs.length === 0, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
