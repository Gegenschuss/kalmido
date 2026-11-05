// 2.564.0 UI tests, part D (#4701): a comment edited on another device meanwhile is not overwritten by the edit box, jsdom:
// kalmido-suite: fresh
// - the edit box opens with the comment's version; another device saves first; Save here -> the server's 409: the toast says
//   "Changed in the meantime", the box shows the other device's text, the server keeps it
// - a second Save in the same box (now against the current version) goes through
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
const setupAlice = async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', modules: ['comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  return CA;
};
const setupFrida = async CA => {
  await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(((await call(CF, 'GET', '/api/state')).me.workspaces || []).length === 0, 'frida has no organisation');
  return CF;
};
const bodyOf = async (ck, T, cid) => ((await call(ck, 'GET', `/api/tasks/${T}/timeline`)).comments || []).find(x => x.id === cid)?.body;

const run = async (ck, user, who) => {
  const L = (await call(ck, 'POST', '/api/lists', {name: 'Notes ' + who})).id;
  const T = (await call(ck, 'POST', '/api/tasks', {title: 'Call the bank', list_id: L})).id;
  const cm = await call(ck, 'POST', `/api/tasks/${T}/comments`, {body: 'First words'});
  check(cm.id > 0, who + ': a comment');
  const w = await boot({user, hash: 't/' + T}), d = w.document;
  const edit = () => d.querySelector(`#d-tl [data-act="c-edit"][data-cid="${cm.id}"]`);
  check(await until(() => edit()), who + ': the comment shows its edit button');
  click(w, edit());
  const box = () => d.querySelector(`.c-edit-input[data-cid="${cm.id}"]`);
  check(await until(() => box()), who + ': the edit box opens');
  // another device saves first (the version this box opened with is old now)
  const other = await call(ck, 'PATCH', `/api/comments/${cm.id}`, {body: 'Text of the other device'});
  check(other.http === 200, who + ': the other device saved');
  box().value = 'My text here';
  click(w, d.querySelector(`[data-act="c-edit-save"][data-cid="${cm.id}"]`));
  check(await until(() => /Changed in the meantime/.test(d.querySelector('#toast')?.textContent || '')), who + ': the toast says why: ' + (d.querySelector('#toast')?.textContent || ''));
  check(await until(() => box()?.value === 'Text of the other device'), who + ': the box shows the current text: ' + box()?.value);
  check(await bodyOf(ck, T, cm.id) === 'Text of the other device', who + ': the server kept the other device\'s text');
  // the same box again: now against the current version
  box().value = 'My second try';
  click(w, d.querySelector(`[data-act="c-edit-save"][data-cid="${cm.id}"]`));
  check(await until(async () => await bodyOf(ck, T, cm.id) === 'My second try'), who + ': the second save goes through');
  check(await until(() => !box()), who + ': the box closes after saving');
  w.close();
};

(async () => {
  const CA = await setupAlice();
  await run(CA, 'alice', 'alice');
  const CF = await setupFrida(CA);
  await run(CF, 'frida', 'freelancer');
  console.log(`p2564_d_versions_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
