// 2.1067.0 (#5789, stage 4e of the core's trash) UI: the start balance of the cash flow, removed in the office settings, lies
// kalmido-suite: fresh
// in the core's trash and comes back (jsdom, invented data only). The way a person goes, by clicks:
// - office settings, section "Cash flow": the start balance is shown; the amount emptied -> the toast "Saved" with Undo, the
//   start balance is gone; Undo -> amount and day are back in the field (POST .../trash/core/ocfstart/<id>/restore?undo=1)
// - emptied again -> the office trash (Offers, trash button) lists "Starting balance" with its day -> Restore -> the toast
//   "Restored"; back in the office settings the field shows the amount again
// freelancer-matrix: office (the person without an organisation: p21067_b_cfstart_trash_test.py; the settings section is the same)
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, B, login, until, idle} = require('./boot');
const TC = require('./testclock');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const DAY = `${TC.today().slice(0, 7)}-01`;
const start = async () => (await call('GET', '/api/office/cashflow/start')).start;
const field = d => d.querySelector('.cfsset #cfs-amount-set');
const shown = d => { const x = field(d); return x && /750/.test(x.value) ? x : null; };
const toastWith = (d, re) => { const t = d.querySelector('#toast'); return t && !t.classList.contains('hidden') && re.test(t.textContent) ? t : null; };
const empty = (w, d) => { const x = field(d); x.value = ''; x.dispatchEvent(new w.Event('change', {bubbles: true})); };

(async () => {
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'comments,collab,office,clients'});
  { const me = (await call('GET', '/api/state')).me; const org = await call('POST', '/api/admin/orgs', {name: 'Example Studio', admin_id: me.id});
    await call('PATCH', '/api/settings', {workspace: `org:${org.id}`}); }
  const put = await call('PUT', '/api/office/cashflow/start', {amount: '750', day: DAY});
  check(put.http === 200 && put.start?.amount === '750.00', 'a start balance ' + put.http);

  const w = await boot({hash: 'office/settings'}), d = w.document;
  w.confirm = () => true;
  check(!!await until(() => shown(d), {timeout: 30000}), 'office settings: the start balance is shown ' + (field(d)?.value || ''));
  check(d.querySelector('#cfs-day')?.value === DAY, 'with its reference date ' + d.querySelector('#cfs-day')?.value);

  // ---- emptied: into the trash, the toast's Undo brings it back
  empty(w, d);
  const t1 = await until(() => { const t = toastWith(d, /Saved/); return t && t.querySelector('button') ? t : null; });
  check(!!t1, 'the toast "Saved" offers Undo');
  check(!!await until(async () => (await start()) === null), 'the start balance is gone');
  const tr1 = (await call('GET', '/api/office/trash')).items || [];
  check(tr1.some(x => x.core === 'ocfstart' && x.kind === 'cf_start' && x.label === DAY), 'it lies in the office trash with its day');
  check(!!await until(() => field(d) && !field(d).value), 'the field is empty');
  t1?.querySelector('button')?.click();
  check(!!await until(async () => (await start())?.amount === '750.00'), 'Undo: the start balance is back');
  check(!!await until(() => shown(d)), 'Undo: the field shows the amount again ' + (field(d)?.value || ''));
  check(d.querySelector('#cfs-day')?.value === DAY, 'and its reference date');

  // ---- emptied again: the office trash lists it, Restore brings it back
  empty(w, d);
  check(!!await until(async () => (await start()) === null), 'emptied again: gone');
  await idle(w);
  w.location.hash = 'office/offers';
  check(!!await until(() => d.querySelector('[data-ofd="trash"]'), {timeout: 30000}), 'offers: the trash button');
  d.querySelector('[data-ofd="trash"]').click();
  const li = await until(() => [...d.querySelectorAll('.otblist li')].find(x => x.dataset.core === 'ocfstart'));
  check(li && /Starting balance/.test(li.textContent) && li.textContent.includes(DAY), 'the office trash lists "Starting balance" with its day ' + (li?.textContent || '').trim().slice(0, 120));
  li?.querySelector('[data-m="restore"]')?.click();
  check(!!await until(() => toastWith(d, /Restored/)), 'toast: Restored');
  check(!!await until(() => !d.querySelector('.otblist')), 'the trash dialog closes');
  check((await start())?.amount === '750.00', 'the start balance is back');
  w.location.hash = 'office/settings';
  check(!!await until(() => shown(d), {timeout: 30000}), 'back in the office settings: the field shows the amount ' + (field(d)?.value || ''));
  await idle(w);
  w.close();

  console.log(`p21067_b_cfstart_trash_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
