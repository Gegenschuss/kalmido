// 2.556.0 B (#4685) UI tests (jsdom), fresh DB: the dialog "New for you" after an update (static/js/whatsnew.js)
// - an example file (<data dir>/whatsnew-test.json, read by test containers only) with two versions since the seen one and
//   an older one: ONE dialog, two version lines, the newest on top, the sentences below; no "Older changes" (the file reaches)
// - closing it = seen (on the server); the next start shows no dialog
// - the switch off (Settings > Help): no dialog, the seen version follows; the switch in the settings stores it
// - no file at all: no dialog and no script error
// kalmido-suite: fresh
const {boot, errs, B, login, until} = require('./boot');
const fs = require('fs');
const path = require('path');
const {execFileSync} = require('child_process');
const DATA = process.argv[2];
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const dbx = (sql, args = []) => JSON.parse(execFileSync('python3', [path.join(__dirname, 'dbx.py'), DATA, sql, JSON.stringify(args)]).toString() || '[]');
const WN = path.join(DATA, 'whatsnew-test.json');
const seen = uid => (dbx("SELECT value FROM user_settings WHERE user_id=? AND key='whatsnew_seen'", [uid])[0] || [])[0];
const setSeen = (uid, v) => dbx("INSERT INTO user_settings(user_id, key, value) VALUES(?, 'whatsnew_seen', ?) ON CONFLICT(user_id, key) DO UPDATE SET value=excluded.value", [uid, v]);

(async () => {
  if (fs.existsSync(WN)) fs.unlinkSync(WN);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});  // no first-run setup left (main.js stops there)
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const ME = (await call('GET', '/api/state')).me.id;
  const CUR = (await call('GET', '/api/about')).version;
  const [MA, MI] = CUR.split('.').map(Number), V = m => `${MA}.${m}.0`;
  fs.writeFileSync(WN, JSON.stringify({versions: [
    {version: CUR, date: '2026-11-05', items: [{en: 'Newest sentence', de: 'Neuester Satz'}, {en: 'Second sentence'}]},
    {version: V(MI - 1), date: '2026-11-04', items: [{en: 'Middle sentence'}]},
    {version: V(MI - 9), date: '2026-10-20', items: [{en: 'Old sentence'}]}]}));
  setSeen(ME, V(MI - 3));

  // ================= two versions since the seen one: one dialog, newest on top
  let w = await boot({user: 'alice', hash: 'today'}), d = w.document;
  check(await until(() => d.querySelector('.wnmd')), 'the dialog "New for you" opens after the start');
  check(d.querySelectorAll('.wnmd').length === 1, 'one dialog');
  const heads = [...d.querySelectorAll('.wnmd .wnhead')].map(h => h.textContent);
  const lab = v => 'v' + v.split('.').filter((p, i) => i < 2 || +p).join('.');
  check(heads.length === 2 && heads[0].startsWith(lab(CUR) + ' · ') && heads[1].startsWith(lab(V(MI - 1)) + ' · '), 'two version lines, the newest on top: ' + heads.join(' | '));
  check(/05.?11/.test(heads[0]) && /04.?11/.test(heads[1]), 'each line names its date (day and month): ' + heads.join(' | '));
  const items = [...d.querySelectorAll('.wnmd .wnver')].map(s => [...s.querySelectorAll('li')].map(l => l.textContent));
  check(JSON.stringify(items) === JSON.stringify([['Newest sentence', 'Second sentence'], ['Middle sentence']]), 'the sentences under their version: ' + JSON.stringify(items));
  check(!d.querySelector('.wnmd .wnolder') && !d.body.textContent.includes('Old sentence'), 'no "Older changes" and no older version: the file reaches the seen one');
  check(d.querySelector('.wnmd h3')?.textContent.includes('New for you'), 'the title');
  d.querySelector('.wnmd [data-m="close"]').click();
  check(await until(() => !d.querySelector('.wnmd')), 'Got it closes the dialog');
  check(await until(() => seen(ME) === CUR), 'closed = the running version is seen on the server: ' + seen(ME));
  w.close();

  // ================= the next start: no dialog
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  check(w.eval('S.settings.whatsnew_seen') === CUR, 'the next start knows the seen version');
  w.eval('wn_boot()');  // what the start runs (setTimeout in main.js): nothing to ask for the seen version
  check(!d.querySelector('.wnmd') && !w.eval("typeof wn_open === 'function' && !!document.querySelector('.wnmd')"), 'no second dialog after reloading');
  w.close();

  // ================= the switch off: no dialog, the seen version follows
  check((await call('PATCH', '/api/settings', {whatsnew_on: '0'})).status === 200, 'setup: switch off');
  setSeen(ME, V(MI - 3));
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  check(await until(() => seen(ME) === CUR), 'switch off: the start moves the seen version along: ' + seen(ME));
  check(!d.querySelector('.wnmd'), 'switch off: no dialog');
  // the switch in Settings > Help
  w.eval("settingsModal('help')");
  check(await until(() => d.querySelector('#s-wnew')), 'Settings > Help has the switch');
  const sw = d.querySelector('#s-wnew');
  check(sw && !sw.checked, 'the switch shows off');
  sw.checked = true; sw.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(async () => (await call('GET', '/api/state')).settings?.whatsnew_on === '1'), 'ticking it stores the switch on');
  w.close();

  // ================= no file: no dialog, no error
  fs.unlinkSync(WN);
  setSeen(ME, V(MI - 3));
  const e0 = errs.length;
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  check(await until(() => seen(ME) === CUR), 'no file: the seen version follows: ' + seen(ME));
  check(!d.querySelector('.wnmd'), 'no file: no dialog');
  check(errs.length === e0, 'no file: no script error ' + errs.slice(e0).join(' | '));
  w.close();

  check(!errs.length, 'no script errors: ' + errs.join(' | '));
  console.log(`p2556_b_whatsnew_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e.stack || e); console.log(`p2556_b_whatsnew_ui: ${ok} ok, ${F.length + 1} failed`); process.exit(1); });
