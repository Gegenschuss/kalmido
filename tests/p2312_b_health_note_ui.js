// 2.312.0 B (#3264) UI test (jsdom), own container (start.sh): the note on health data (Art. 9 GDPR, 2.306.0 B #2887: in the
// module rows Health and Review & journal) also where these modules are switched on together with others:
//  - Settings > Modules: the area rows Home (health) and Review (journal), not the other areas
//  - the first-run setup: below the purposes while Home (or Review) is picked, also when ticked under "Customize…"
// freelancer-matrix: settings (the person has no organisation)
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
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const HEALTH = 'Health data is specially protected', JOURNAL = 'Journal and mood entries can be health data';

(async () => {
  await sleep(800);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  check((await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []})).id, 'a person without organisation');
  const CF = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal'}, CF);
  check(((await call('GET', '/api/state', null, CF)).me.workspaces || []).length === 0, 'frida is in no organisation');

  // ================= Settings > Modules: the area rows
  const w = await boot({user: 'frida'}), d = w.document;
  w.eval(`settingsModal('modules')`);
  await until(() => d.querySelector('.smodal [data-mgrow="life"]'));
  const areaNote = id => [...(d.querySelector(`.smodal [data-mgrow="${id}"] > label.mmain`)?.querySelectorAll('small.modpriv') || [])].map(x => x.textContent).join(' | ');
  check(areaNote('life').includes(HEALTH) && !areaNote('life').includes(JOURNAL), 'area Home: the health note next to its switch ' + areaNote('life'));
  check(areaNote('review').includes(JOURNAL) && !areaNote('review').includes(HEALTH), 'area Review: the journal note next to its switch ' + areaNote('review'));
  check(areaNote('office') === '' && areaNote('time') === '', 'other areas: no note');
  check(!d.querySelector('.smodal input[data-mgarea="life"]').checked, '(setup) Home is off: the note shows before switching it on');
  check(d.querySelector('.smodal [data-modrow="health"] small.modpriv')?.textContent.includes(HEALTH), 'the module row Health keeps its note (2.306.0)');
  d.querySelector('.smodal').remove();

  // ================= the first-run setup ("What do you use Kalmido for?")
  w.eval(`{ const el = document.createElement('div'); el.id = 'su-test'; document.body.append(el); setupChoices(el, ''); }`);
  const el = await until(() => d.querySelector('#su-test .setupcard') && d.querySelector('#su-test'));
  check(el, 'the setup card is drawn');
  const suNote = () => [...el.querySelectorAll('#su-priv small.modpriv')].map(x => x.textContent).join(' | ');
  check(suNote() === '', 'without Home and Review: no note ' + suNote());
  click(w, el.querySelector('[data-su-preset="home"]'));
  await until(() => suNote());
  check(suNote().includes(HEALTH) && suNote().includes(JOURNAL), 'purpose Home (health, journal): both notes below the purposes ' + suNote());
  click(w, el.querySelector('[data-su-preset="team"]'));
  await until(() => suNote() === '');
  check(suNote() === '', 'purpose Team: no note');
  const life = el.querySelector('[data-use="a:life"]');
  check(life && !life.checked, '(setup) Home unticked under Customize');
  life.checked = true; life.dispatchEvent(new w.Event('change', {bubbles: true}));
  await until(() => suNote());
  check(suNote().includes(HEALTH) && !suNote().includes(JOURNAL), 'Home ticked under Customize: the health note ' + suNote());
  life.checked = false; life.dispatchEvent(new w.Event('change', {bubbles: true}));
  await until(() => suNote() === '');
  check(suNote() === '', 'Home unticked again: the note goes');

  console.log(`p2312_b_health_note_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
