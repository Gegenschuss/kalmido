// kalmido-suite:
// 2.473.0 UI test (#3378: the box "With a bug inbox" in the dialog New project), own container (start.sh), jsdom. Invented data only.
// - the box shows only with the card Software, also when the folder's type preselects it; the sent body has bug_inbox only when ticked
// - ticked: both projects exist, the rule shows in the bug project's rule list with the sentence "the field Release is filled"
// - the rule dialog offers "Filled" for a text field and keeps it when opened again
// P4: a person without an organisation gets the same (freelancer-matrix: lists)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.PR2473B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(200); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', modules: ['kanban']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  check(!((await call(CF, 'GET', '/api/state')).me.workspaces || []).length, 'frida: no organisation');

  for (const [u, ck] of [['alice', CA], ['frida', CF]]) {
    await call(ck, 'PUT', '/api/folders/props', {folder: 'Typed', props: {ptype: 'software'}, apply: 'new'});
    const w = await boot({user: u, hash: 'today'}), d = w.document;
    const md = () => [...d.querySelectorAll('.modal')].pop();
    await until(() => w.eval(`typeof folderPtype === 'function' && (S.folderProps || {})['Typed']?.ptype === 'software'`), 20);
    const open = async f => { w.eval(`document.querySelectorAll('.modal').forEach(m => m.remove()); listModal(0, ${JSON.stringify(f)})`); await until(() => md()?.querySelector('#l-name')); };

    await open('');
    check(md().querySelector('.ptbug').hidden, `${u}: a blank project has no box`);
    click(w, md().querySelector('.ptcard[data-pt="agency"]'));
    check(md().querySelector('.ptbug').hidden, `${u}: Agency has no box`);
    click(w, md().querySelector('.ptcard[data-pt="software"]'));
    check(!md().querySelector('.ptbug').hidden && !md().querySelector('#l-ptbug').checked, `${u}: Software shows the box, not ticked`);
    await open('Typed');
    check(md().querySelector('.ptcard.on')?.dataset.pt === 'software' && !md().querySelector('.ptbug').hidden, `${u}: a folder of type Software shows it too`);

    // not ticked: one project
    await open('');
    click(w, md().querySelector('.ptcard[data-pt="software"]'));
    md().querySelector('#l-name').value = 'One only';
    click(w, md().querySelector('[data-m="save"]'));
    await until(async () => ((await call(ck, 'GET', '/api/state')).lists || []).find(l => l.name === 'One only'));
    check(!((await call(ck, 'GET', '/api/state')).lists || []).some(l => l.name === 'One only – Bugs'), `${u}: not ticked = no bug project`);

    // ticked, then another card: not sent
    await open('');
    click(w, md().querySelector('.ptcard[data-pt="software"]'));
    md().querySelector('#l-ptbug').checked = true;
    click(w, md().querySelector('.ptcard[data-pt="agency"]'));
    md().querySelector('#l-name').value = 'Changed mind';
    click(w, md().querySelector('[data-m="save"]'));
    await until(async () => ((await call(ck, 'GET', '/api/state')).lists || []).find(l => l.name === 'Changed mind'));
    check(!((await call(ck, 'GET', '/api/state')).lists || []).some(l => l.name === 'Changed mind – Bugs'), `${u}: another card chosen after ticking = no bug project`);

    // ticked: both
    await open('');
    click(w, md().querySelector('.ptcard[data-pt="software"]'));
    md().querySelector('#l-name').value = 'Shop';
    md().querySelector('#l-ptbug').checked = true;
    click(w, md().querySelector('[data-m="save"]'));
    const bug = await until(async () => ((await call(ck, 'GET', '/api/state')).lists || []).find(l => l.name === 'Shop – Bugs'));
    check(bug && bug.ptype === 'software', `${u}: ticked = the bug project exists`);
    const rs = bug ? (await call(ck, 'GET', `/api/lists/${bug.id}/rules`)).rules || [] : [];
    check(rs.length === 1 && rs[0].active && rs[0].trigger.value === '*', `${u}: its rule ` + JSON.stringify(rs));

    // the rule's sentence and dialog
    await until(() => w.eval(`!!listById(${bug?.id})`));
    const txt = w.eval(`rxTrigField(${JSON.stringify(rs[0]?.trigger)}, ${JSON.stringify(rs[0]?.names)})`);
    check(/the field .*Release.* is filled/.test(txt), `${u}: the sentence: ` + txt);
    const fid = rs[0]?.trigger.field_id;
    const opts = w.eval(`(() => { const x = document.createElement('div'); x.innerHTML = rxTrigValHtml(${bug?.id}, ${fid}, '*'); const s = x.querySelector('select'); return {val: s?.value, all: [...(s?.options || [])].map(o => o.textContent)}; })()`);
    check(opts.val === '*' && opts.all.join() === 'Any change,Filled', `${u}: a text field offers Filled and keeps it ` + JSON.stringify(opts));
    w.close();
  }

  console.log(`pr2473_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERR', e); process.exit(1); });
