// 2.319.0 B (#3288) UI tests: Settings > Appearance "Show labels in the app bar". Own container (start.sh), jsdom.
// - on by default: the bar's icons carry their words, no extra title / aria-label
// - off: icons only (class rail-nolabel on the page, app.css hides the words and narrows the bar), every icon names its area
//   as title + aria-label, the open area stays marked; saved like the other appearance settings (account, second device)
// - the phone's row of area icons follows the same switch
// - on again: the words come back, the account forgets the key
// Invented names only.
const {execFileSync} = require('child_process');
const fs = require('fs');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2319B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); let j = {}; try { j = await r.json(); } catch { /* no body */ } return {http: r.status, ...j}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const look = async () => { const s = (await call('GET', '/api/state')).settings || {}; try { return JSON.parse(s.look || 'null') || {}; } catch { return {}; } };
const change = (w, el, on) => { el.checked = on; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const icons = d => [...d.querySelectorAll('#srail .srb[data-sbb]')];
const named = b => { const n = b.querySelector('.srbn')?.textContent || ''; return !!n && b.getAttribute('title') === n && b.getAttribute('aria-label') === n; };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});

  const css = fs.readFileSync(path.join(__dirname, '..', 'static', 'app.css'), 'utf8');
  check(css.includes(':root.rail-nolabel .srb .srbn{display:none}') && css.includes(':root.rail-nolabel{--srW:3.25rem}'), 'app.css: off hides the words and narrows the bar');

  // ================= on by default
  let w = await boot({user: 'alice'}), d = w.document;
  check(await until(() => icons(d).length > 2), `the app bar is there (${icons(d).length} icons)`);
  check(!d.documentElement.classList.contains('rail-nolabel'), 'default: the labels are shown');
  check(icons(d).every(b => b.querySelector('.srbn')?.textContent && !b.hasAttribute('aria-label')), 'default: every icon with its word, no extra aria-label');
  w.eval(`settingsModal('look')`); await sleep(300);
  const pane = () => d.querySelector('.smodal [data-pane="look"]');
  let sw = pane()?.querySelector('#s-rail-lbl');
  check(sw && sw.type === 'checkbox' && sw.checked && /Show labels in the app bar/.test(sw.closest('label').textContent), 'Appearance: the switch "Show labels in the app bar" is there and on');

  // ================= off: icons only, the name as title / aria-label
  change(w, sw, false); await sleep(200);
  check(d.documentElement.classList.contains('rail-nolabel'), 'off: the page gets rail-nolabel');
  check(w.localStorage.getItem('tasks.railLabels') === 'false', 'off: kept on the device');
  check(await until(() => icons(d).length > 2 && icons(d).every(named)), 'off: every icon names its area as title and aria-label');
  check(d.querySelector('#srail .srb.sset')?.getAttribute('aria-label') === 'Settings', 'off: Settings keeps its name for screen readers');
  check(d.querySelectorAll('#srail .srb.on[aria-current="page"]').length === 1, 'off: the open area stays marked');
  check(await until(async () => (await look()).railLabels === false), 'off: saved to the account like the other appearance settings');
  w.close();

  // ================= a second device takes it over
  w = await boot({user: 'alice'}); d = w.document;
  check(await until(() => d.documentElement.classList.contains('rail-nolabel') && icons(d).length > 2 && icons(d).every(named)), 'second device: icons only, with their names as tooltip');
  w.close();
  // the phone: the drawer's row of area icons follows the switch
  w = await boot({user: 'alice', mobile: true}); d = w.document;
  check(await until(() => d.documentElement.classList.contains('rail-nolabel')), 'phone: the same switch');
  const row = () => [...d.querySelectorAll('#side .sbmr .srb[data-sbb]')];
  check(await until(() => row().length > 2 && row().every(named)), `phone: the row's icons name their areas (${row().length})`);
  w.close();

  // ================= on again
  w = await boot({user: 'alice'}); d = w.document;
  await until(() => icons(d).length > 2);
  w.eval(`settingsModal('look')`); await sleep(300);
  sw = pane()?.querySelector('#s-rail-lbl');
  check(sw && !sw.checked, 'Appearance: the switch shows off');
  change(w, sw, true); await sleep(200);
  check(!d.documentElement.classList.contains('rail-nolabel') && w.localStorage.getItem('tasks.railLabels') === null, 'on again: the labels are back, the device key is gone');
  check(await until(() => icons(d).length > 2 && icons(d).every(b => !b.hasAttribute('aria-label'))), 'on again: no extra aria-label');
  check(await until(async () => !('railLabels' in await look())), 'on again: the account forgets the key');
  w.close();

  console.log(`p2319_b_rail_labels_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
