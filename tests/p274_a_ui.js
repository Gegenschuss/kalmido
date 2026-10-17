// 2.74.0 UI tests of part A (#338; own container, start.sh). jsdom:
// - Settings > Help: "Support Kalmido" under About (explanation, the https payment link, the key field)
// - entering a personal key: the badge in About and in Settings > Account; Remove takes it away, Undo brings it back
// - the yearly hint: a member never sees it; an admin sees it once (hidden with the x, not again on the next start);
//   the switch "Remind me once a year" turns it off
// A test key pair (tools/supporter_key.py, temp folder) is trusted through KALMIDO_SUPPORTER_EXTRA_PUBKEYS.
const {execFileSync} = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const PY = process.env.PYTHON || 'python3', TOOL = path.join(__dirname, '..', 'tools', 'supporter_key.py');
const TMP = fs.mkdtempSync(path.join(os.tmpdir(), 'p274aui-')), KF = path.join(TMP, 'k.key');
const PUB = execFileSync(PY, [TOOL, 'genkey', '--out', KF]).toString().trim();
const PER = execFileSync(PY, [TOOL, 'sign', '--key', KF, '--type', 'person', '--id', 'ui-1', '--date', '2026-10-03']).toString().trim();
const EXTRA = `${process.env.EXTRA || ''} -e KALMIDO_SUPPORTER_EXTRA_PUBKEYS=${PUB} -e KALMIDO_SUPPORT_URL=https://pay.example.com/kalmido`;
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA}});
const [DBC, DBN] = fs.readFileSync(path.join(DATA, '.kalmido-db'), 'utf8').trim().split(/\s+/);
const sql = q => execFileSync('docker', ['exec', DBC, 'psql', '-U', 'kalmido', '-d', DBN, '-Atqc', q]).toString();
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(200); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'});
  await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  const CB = await login('bob');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'}, CB);
  sql("UPDATE users SET created_at='2025-01-01T00:00:00Z'");  // the server is older than 30 days

  // ================= the yearly hint
  let w = await boot({user: 'bob'}), d = w.document;
  await sleep(300);
  check(!d.querySelector('#supbar'), 'a member never sees the hint');
  w.close();
  w = await boot({user: 'alice'}); d = w.document;
  const bar = await until(() => d.querySelector('#supbar'));
  check(bar && /supporter licence/.test(bar.textContent), 'the admin sees the quiet hint');
  check(bar?.querySelector('[data-sup="more"]'), 'the hint links to About');
  click(w, bar.querySelector('[data-sup="hide"]'));
  await sleep(200);
  check(!d.querySelector('#supbar'), 'x hides it');
  w.close();
  await sleep(300);
  w = await boot({user: 'alice'}); d = w.document;
  await sleep(300);
  check(!d.querySelector('#supbar'), 'not again on the next start (a year quiet)');
  w.close();
  sql("UPDATE user_settings SET value='2024-01-01' WHERE key='sup_nudge_at'");
  w = await boot({user: 'alice'}); d = w.document;
  check(await until(() => d.querySelector('#supbar')), 'a year later: again');
  w.eval(`settingsModal('help')`); await sleep(400);
  let md = d.querySelector('.smodal');
  const sw = md?.querySelector('#s-supnudge');
  check(sw && sw.checked, 'the switch "Remind me once a year" is on');
  sw.checked = false; sw.dispatchEvent(new w.Event('change', {bubbles: true}));
  await until(async () => (await call('GET', '/api/about')).sup_nudge_on === false);
  check((await call('GET', '/api/about')).sup_nudge_on === false, 'the switch turns the hint off');
  w.close();
  sql("UPDATE user_settings SET value='2024-01-01' WHERE key='sup_nudge_at'");
  w = await boot({user: 'alice'}); d = w.document;
  await sleep(300);
  check(!d.querySelector('#supbar'), 'switched off: no hint even after a year');
  w.close();

  // ================= Support Kalmido under About
  w = await boot({user: 'bob'}); d = w.document;
  w.eval(`settingsModal('help')`); await sleep(400);
  md = d.querySelector('.smodal');
  const sec = md?.querySelector('#s-sup');
  check(sec && md.querySelector('#s-about-h') && /Support Kalmido/.test(sec.textContent), 'the section under About');
  check(/unlocks nothing/.test(sec?.textContent || ''), 'the explanation');
  const a = sec?.querySelector('a[href="https://pay.example.com/kalmido"]');
  check(a && a.target === '_blank', 'the payment link opens in a new tab');
  check(!sec?.querySelector('#s-supnudge'), 'a member has no hint switch');
  check(!sec?.querySelector('[data-sup="del"][data-kind="server"]'), 'a member cannot remove a server licence');
  const inp = sec.querySelector('#s-supkey');
  inp.value = PER;
  click(w, sec.querySelector('[data-sup="add"]'));
  const badge = await until(() => d.querySelector('#s-sup .supbadge'));
  check(badge && /Supporter/.test(badge.textContent) && /Personal licence/.test(badge.textContent), 'the badge in About');
  check(!d.querySelector('#s-sup').innerHTML.includes(PER.split('.')[2]) && !d.querySelector('#s-supkey').value, 'the key is not shown again');
  d.querySelector('.smodal')?.remove(); await sleep(100);
  w.eval(`settingsModal('account')`); await sleep(400);
  check(/Personal licence/.test(d.querySelector('.smodal #a-sup')?.textContent || ''), 'the badge in Settings > Account');
  d.querySelector('.smodal')?.remove();
  w.eval(`settingsModal('help')`); await sleep(400);
  click(w, d.querySelector('.smodal [data-sup="del"][data-kind="person"]'));
  await until(() => !d.querySelector('#s-sup .supbadge'));
  check(!d.querySelector('#s-sup .supbadge'), 'Remove takes the badge away');
  w.eval(`histStep('undo')`);
  check(await until(() => d.querySelector('#s-sup .supbadge')), 'Undo brings it back (one step)');
  check((await call('GET', '/api/about', null, CB)).supporter_me?.id === 'ui-1', 'the server has it again');
  w.close();

  fs.rmSync(TMP, {recursive: true, force: true});
  console.log(`p274_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
