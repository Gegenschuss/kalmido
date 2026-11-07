// kalmido-suite: fresh
// 2.593.0 UI test of part D (#4590): Settings > Account > "Reset settings…". Own container (start.sh), jsdom, invented data only.
// - the button is in the account section; the dialog lists what differs (an account setting by its readable name, the
//   values this device keeps as "This device"), never the language
// - Reset puts the account's settings and this device's own values back; after the reload (a second window on the same
//   localStorage) the message offers "Undo", which brings both back
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, untilAct} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.BASE) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = (fn, ms) => require('./boot').until(fn, {timeout: ms || 15000, step: 150});
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const sett = async () => (await call('GET', '/api/state')).settings || {};

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', side_icons: 'emoji', week_start: 'sun'});
  const shared = {store: {'tasks.sideFold': '["side:lists"]'}, wins: []};

  // ================= the dialog with the preview
  let w = await boot({user: 'alice', shared}), d = w.document;
  w.settingsModal('account');
  const open = await untilAct(w, 'Reset settings…');
  check(!!open, 'the button "Reset settings…" is in Settings > Account');
  if (open) click(w, open);
  const list = await until(() => d.querySelector('#rs-list'));
  const txt = list ? list.textContent : '';
  check(/List icons in the sidebar/.test(txt), 'the preview names a changed account setting by its readable name: ' + txt.slice(0, 200));
  check(/This device/.test(txt), 'the preview names the values this device keeps');
  check(!/Language|First day of the week/.test(txt), 'the language and the formats are never in the preview');
  const go = d.querySelector('[data-act="reset"]');
  check(go && !go.disabled, 'Reset can be pressed');
  if (go) click(w, go);
  await until(async () => (await sett()).side_icons === 'line' && shared.store['tasks.rsToast']);
  const s1 = await sett();
  check(s1.side_icons === 'line', 'the account setting is back to the standard: ' + s1.side_icons);
  check(s1.week_start === 'sun' && s1.lang === 'en', 'formats and language stay');
  check(!('tasks.sideFold' in shared.store), 'this device\'s own value went back too');
  check(!!shared.store['tasks.rsUndoLocal'], 'this device keeps its old values for the undo');
  w.close();

  // ================= after the reload: the message with Undo
  w = await boot({user: 'alice', shared}); d = w.document;
  const tb = await until(() => { const t = d.querySelector('#toast:not(.hidden)'); return t && /Settings reset to the standard/.test(t.textContent) && t.querySelector('button:not(.tx)'); });
  check(!!tb, 'after the reload the message offers Undo');
  if (tb) click(w, tb);
  await until(async () => (await sett()).side_icons === 'emoji' && shared.store['tasks.sideFold']);
  check((await sett()).side_icons === 'emoji', 'Undo: the account setting is back');
  check(shared.store['tasks.sideFold'] === '["side:lists"]', 'Undo: this device\'s own value is back: ' + shared.store['tasks.sideFold']);
  check((await call('POST', '/api/settings/reset', {undo: true})).http === 404, 'the undo is used up');
  w.close();

  console.log(`p2593_d_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); console.log(`p2593_d_ui: ${ok} ok, ${F.length + 1} failed`); process.exit(1); });
