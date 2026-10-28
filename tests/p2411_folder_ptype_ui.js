// kalmido-suite:
// 2.411.0 UI test (#3516: a new list in a folder takes the folder's project type), own container (start.sh), jsdom. Invented data only.
// - the folder settings have the select "Project type" (saving it stores the folder default ptype)
// - "New project" in a folder with a software project type starts as that type: "Progress and status" on, the card
//   Software chosen, the standard sections ticked; created, the list is a software project
// - a folder without a type keeps the dialog as before (a simple list); the person picks "Blank" in the typed folder = no type
// P4: a person without an organisation gets the same (freelancer-matrix: lists)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2411U_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
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
    await call(ck, 'POST', '/api/lists', {name: 'Old', folder: 'Plain'});
    await call(ck, 'POST', '/api/lists', {name: 'Seed', folder: 'Kalmido'});
    const w = await boot({user: u, hash: 'today'}), d = w.document;
    // the folder settings: the select Project type saves the folder default
    w.eval(`folderPropsModal('Kalmido')`);
    const sel = await until(() => d.querySelector('#fs-pt'));
    check(sel && [...sel.options].some(o => o.value === 'software'), `${u}: the folder settings have "Project type"`);
    if (sel) { sel.value = 'software'; sel.dispatchEvent(new w.Event('change', {bubbles: true})); }
    const saved = await until(async () => (await call(ck, 'GET', '/api/folders/props?folder=Kalmido')).props?.ptype === 'software');
    check(saved, `${u}: the folder default Project type is saved`);
    await until(() => w.eval(`(S.folderProps || {})['Kalmido']?.ptype === 'software'`));
    w.eval(`document.querySelectorAll('.modal').forEach(m => m.remove())`);
    // New project in the typed folder
    w.eval(`listModal(0, 'Kalmido')`);
    await until(() => d.querySelector('.modal #l-name'));
    const md = () => [...d.querySelectorAll('.modal')].pop();
    const st = w.eval(`(() => { const m = [...document.querySelectorAll('.modal')].pop(); return {card: m.querySelector('.ptcard.on')?.dataset.pt, secs: m.querySelector('#l-ptsecs')?.checked, shown: !m.querySelector('.lptype')?.hidden}; })()`);
    check(st.card === 'software' && st.secs && st.shown, `${u}: New project in the folder starts as Software with its sections ` + JSON.stringify(st));
    md().querySelector('#l-name').value = 'Fresh';
    click(w, md().querySelector('[data-m="save"]'));
    const x = await until(async () => ((await call(ck, 'GET', '/api/state')).lists || []).find(l => l.name === 'Fresh'));
    check(x && x.ptype === 'software' && x.folder === 'Kalmido', `${u}: created as a software project ` + JSON.stringify(x && {ptype: x.ptype, folder: x.folder}));
    // Blank chosen in the typed folder = no type
    w.eval(`listModal(0, 'Kalmido')`);
    await until(() => [...d.querySelectorAll('.modal #l-name')].length);
    md().querySelector('#l-name').value = 'Bare';
    click(w, md().querySelector('.ptcard[data-pt=""]'));
    md().querySelector('#l-name').value = 'Bare';
    click(w, md().querySelector('[data-m="save"]'));
    const y = await until(async () => ((await call(ck, 'GET', '/api/state')).lists || []).find(l => l.name === 'Bare'));
    check(y && !y.ptype, `${u}: Blank chosen in the typed folder = no type ` + JSON.stringify(y && {ptype: y.ptype}));
    // a folder without a type: the dialog as before
    w.eval(`listModal(0, 'Plain')`);
    await until(() => [...d.querySelectorAll('.modal #l-name')].length);
    const pl = w.eval(`(() => { const m = [...document.querySelectorAll('.modal')].pop(); return {card: m.querySelector('.ptcard.on')?.dataset.pt}; })()`);
    check(!pl.card, `${u}: a folder without a type keeps the simple list ` + JSON.stringify(pl));
    w.close();
  }

  console.log(`p2411_folder_ptype_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERR', e); process.exit(1); });
