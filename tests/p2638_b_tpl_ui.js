// 2.638.0 UI tests, part B (#4775): the template dialog sends the version it opened with, jsdom:
// kalmido-suite: fresh
// - Settings > Data > Templates, edit a template; another device saves it first; Save here -> the server's 409: the toast says
//   "Changed in the meantime", the dialog opens again with the other device's state, the server keeps it
// - a second Save in the new dialog (now against the current version) goes through
// - a person without an organisation (freelancer parity): the same
// Every wait is on a real state (until).
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, until: until0} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
const until = fn => until0(fn, {timeout: 15000, step: 100});
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const FEAT = 'comments,kanban';

const nameOf = async (ck, id) => ((await call(ck, 'GET', '/api/templates')).templates || []).find(x => x.id === id)?.name;

const run = async (ck, user, who) => {
  const L = (await call(ck, 'POST', '/api/lists', {name: 'Kit ' + who})).id;
  const T = (await call(ck, 'POST', '/api/tasks', {title: 'Pack the bag', list_id: L})).id;
  const tp = await call(ck, 'POST', '/api/templates', {task_id: T, name: 'Bag ' + who});
  check(tp.id > 0 && tp.updated_at, who + ': a template with its version ' + JSON.stringify(tp).slice(0, 200));
  const w = await boot({user}), d = w.document;
  w.eval(`settingsModal('templates')`);
  const row = () => d.querySelector(`#s-tpls [data-tpl="${tp.id}"] [data-tpl-edit]`);
  check(await until(() => row()), who + ': Settings > Data lists the template with its edit button');
  click(w, row());
  const nm = () => d.querySelector('.tpmodal #tp-name');
  check(await until(() => nm()), who + ': the template dialog opens');
  // another device saves first (the version this dialog opened with is old now)
  const other = await call(ck, 'PATCH', `/api/templates/${tp.id}`, {name: 'Bag of the other device'});
  check(other.http === 200, who + ': the other device saved');
  nm().value = 'My bag';
  click(w, d.querySelector('.tpmodal [data-m="save"]'));
  check(await until(() => /Changed in the meantime/.test(d.querySelector('#toast')?.textContent || '')), who + ': the toast says why: ' + (d.querySelector('#toast')?.textContent || ''));
  check(await until(() => nm()?.value === 'Bag of the other device'), who + ': the dialog shows the current state: ' + nm()?.value);
  check(await nameOf(ck, tp.id) === 'Bag of the other device', who + ': the server kept the other device\'s name');
  // the new dialog: now against the current version
  nm().value = 'My second try';
  click(w, d.querySelector('.tpmodal [data-m="save"]'));
  check(await until(async () => await nameOf(ck, tp.id) === 'My second try'), who + ': the second save goes through');
  check(await until(() => !d.querySelector('.tpmodal')), who + ': the dialog closes after saving');
  w.close();
};

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', modules: ['comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  await run(CA, 'alice', 'alice');
  await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(((await call(CF, 'GET', '/api/state')).me.workspaces || []).length === 0, 'frida has no organisation');
  await run(CF, 'frida', 'freelancer');
  console.log(`p2638_b_tpl_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
