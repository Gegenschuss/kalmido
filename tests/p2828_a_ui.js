// 2.828.0 part A UI test (#5511), own container (start.sh): several industries at once in Settings > General.
// kalmido-suite: fresh
// - the field Industry is one box per industry (as Office > Packs), none ticked for a new person
// - Film & Video ticked, then Agency & services ticked: both stay ticked and both are saved (before: Film fell away)
// - after a reload both boxes are still ticked; Office > Packs shows both industry packs switched on
// - two quick unticks one after the other: both arrive (no false 409), none ticked = no industry
// freelancer-matrix: industry (frida has no organisation: she chooses for her own area)
// P2828A_NOSTART=1 = the server already runs.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2828A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const FEAT = 'cal,comments,office,clients';
const codes = async ck => ((await call('GET', '/api/industry', null, ck)).industry?.codes || []).slice().sort().join(',');
const box = (d, c) => d.querySelector(`.smodal #s-industry input[data-ind="${c}"]`);

async function openSettings() {
  const w = await boot({user: 'frida', hash: 'inbox'}), d = w.document;
  await w.eval(`settingsModal()`);
  check(await until(() => box(d, 'film') && box(d, 'agency')), 'Settings > General: one box per industry');
  return [w, d];
}

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: FEAT.split(',')});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const fu = await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fu.status < 300, 'a person without an organisation ' + fu.status);
  const CF = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, CF);

  // ================= two boxes, ticked one after the other: both stay on
  let [w, d] = await openSettings();
  check(/Industry/.test(d.querySelector('.smodal #s-industry-h')?.textContent || '') && !d.querySelector('.smodal #s-industry input:checked'),
    'a new person: the heading Industry, no box ticked');
  check(/Film & Video/.test(box(d, 'film').closest('label').textContent) && /Agency/.test(box(d, 'agency').closest('label').textContent), 'the boxes carry the industry names');
  click(w, box(d, 'film'));
  check(await until(async () => await codes(CF) === 'film'), 'Film & Video ticked: saved');
  click(w, box(d, 'agency'));
  check(await until(async () => await codes(CF) === 'agency,film'), 'Agency & services ticked: both saved (#5511: Film stays) ' + await codes(CF));
  check(box(d, 'film').checked && box(d, 'agency').checked, 'both boxes stay ticked on the page');
  check(w.eval(`indOn('film') && indOn('agency')`), 'the app knows both industries (S.industry.codes)');
  w.close();

  // ================= reload: both ticked; Office > Packs: both switched on
  [w, d] = await openSettings();
  check(box(d, 'film').checked && box(d, 'agency').checked, 'after a reload: both boxes ticked');
  w.close();
  w = await boot({user: 'frida', hash: 'office/settings'}); d = w.document;
  const sw = c => d.querySelector(`#pkc [data-pkc-item="industry/${c}"] [data-pkc-on="${c}"]`);
  check(await until(() => sw('film') && sw('agency')), 'Office > Packs: the cards of both industry packs with their switch');
  check(sw('film')?.checked && sw('agency')?.checked, 'Office > Packs: Film & Video and Agency & services both switched on');
  w.close();

  // ================= two quick unticks: both arrive one after the other (no false 409)
  [w, d] = await openSettings();
  click(w, box(d, 'film')); click(w, box(d, 'agency'));
  check(await until(async () => await codes(CF) === ''), 'both unticked quickly: no industry ' + await codes(CF));
  check(await until(() => !box(d, 'film').checked && !box(d, 'agency').checked), 'the page shows none ticked');
  check(!/changed meanwhile|conflict/i.test(d.querySelector('#toast')?.textContent || ''), 'no conflict message');
  w.close();

  check(errs.length === 0, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
