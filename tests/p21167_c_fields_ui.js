// 2.1167.0 UI test, part C (#6083): the fields window of the project settings: on a phone ONE "…" per row instead of pin / up / edit
// kalmido-suite: fresh
// Own container (start.sh; P21167C_NOSTART=1 / KMT_NOSTART=1: a running server), jsdom. Invented names only.
// freelancer-matrix: alice works without an organisation (her private workspace)
// - phone: each field row has its three buttons marked .ms-phsr and one "…"; the menu shows the three actions, "Pin" works on the server,
//   "Edit" opens the field dialog with its name
// - computer: the three symbols as before (the "…" is in the row but hidden by CSS on a computer)
const path = require('path');
const fs = require('fs');
const {execFileSync} = require('child_process');
const {boot, B, login, until} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } return !!c; };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21167C_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
const menuOpen = w => { const p = w.document.querySelector('#pop'); return p && !p.classList.contains('hidden') && p.querySelector('[role="menu"]') ? p : null; };
const items = w => [...(menuOpen(w)?.querySelectorAll('[role="menuitem"]') || [])];
const labels = w => items(w).map(b => b.textContent.trim()).filter(Boolean);

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en'});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'fields'});
  check(!((await call('GET', '/api/state')).orgs || []).length, 'a person without an organisation');
  const P = (await call('POST', '/api/lists', {name: 'Studio', kind: 'project'})).id;
  const A = (await call('POST', `/api/lists/${P}/fields`, {name: 'Budget', type: 'number'})).id;
  const Bf = (await call('POST', `/api/lists/${P}/fields`, {name: 'Stage', type: 'text'})).id;
  check(P && A && Bf, 'setup ' + JSON.stringify([P, A, Bf]));
  const css = fs.readFileSync(path.join(__dirname, '..', 'static', 'css', 'start-phrows-3835.css'), 'utf8');
  check(/\.ms-phsr\{position:absolute!important/.test(css), 'the phone CSS hides .ms-phsr buttons');

  for (const mobile of [true, false]) {
    const tag = mobile ? 'phone' : 'computer';
    const w = await boot({user: 'alice', hash: 'l/' + P, mobile}), d = w.document;
    await until(() => w.eval(`fieldsAll(${P}).length === 2`), {timeout: 20000});
    w.eval(`listModal(${P})`);
    const box = await until(() => d.querySelector('#l-fields .mrow[data-fid]') && d.querySelector('#l-fields'), {timeout: 20000});
    if (!check(box, tag + ': the fields window is shown')) { w.close(); continue; }
    const rows = [...box.querySelectorAll('.mrow[data-fid]')];
    check(rows.length === 2 && /Budget/.test(rows[0].textContent), tag + ': both fields are listed with their names');
    for (const r of rows) {
      const three = ['[data-fpin]', '[data-fup]', '[data-fedit]'].every(s => r.querySelector(s));
      check(three, tag + ': the row keeps its three buttons');
      check(['[data-fpin]', '[data-fup]', '[data-fedit]'].every(s => r.querySelector(s)?.classList.contains('ms-phsr')), tag + ': the three buttons are marked for the phone');
      check(r.querySelectorAll('.ms-phdots').length === 1, tag + ': one "…" in the row');
    }
    if (mobile) {
      rows[1].querySelector('.ms-phdots').click();
      const got = await until(() => menuOpen(w) && labels(w).length >= 3 ? labels(w) : null, {timeout: 5000}) || [];
      check(['Show in the task rows', 'move up', 'Edit'].every(t => got.includes(t)), 'phone: the "…" menu lists the three actions: ' + got);
      const pin = items(w).find(b => b.textContent.trim() === 'Show in the task rows'); pin?.click();
      check(await until(async () => (await call('GET', '/api/state')).fields?.find(f => f.id === Bf)?.pinned, {timeout: 8000}), 'phone: "Show in the task rows" pins the field on the server');
      await until(() => d.querySelector(`#l-fields [data-fid="${Bf}"] [data-fpin].on`), {timeout: 5000});
      d.querySelector(`#l-fields [data-fid="${Bf}"] .ms-phdots`)?.click();  // the row was redrawn by the pin
      await until(() => menuOpen(w) && labels(w).length >= 3, {timeout: 5000});
      items(w).find(b => b.textContent.trim() === 'Edit')?.click();
      check(await until(() => [...d.querySelectorAll('.modal #fd-name')].some(x => x.value === 'Stage'), {timeout: 5000}), 'phone: "Edit" in the menu opens the field dialog with its name');
    }
    w.close();
  }
  console.log(`p21167_c_fields_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
