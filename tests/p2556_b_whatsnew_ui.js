// 2.556.0 B (#4685) UI tests (jsdom), fresh DB: the dialog "New for you" after an update (static/js/whatsnew.js)
// - an example file (<data dir>/whatsnew-test.json, read by test containers only) with two versions since the seen one and
//   an older one: ONE dialog, two version lines, the newest on top, the sentences below; no "Older changes" (the file reaches)
// - closing it = seen (on the server); the next start shows no dialog
// - the switch off (Settings > Help): no dialog, the seen version follows; the switch in the settings stores it
// - no file at all: no dialog and no script error
// kalmido-suite: fresh
const {boot, errs, B, login, until, sleep} = require('./boot');
const fs = require('fs');
const path = require('path');
const {execFileSync} = require('child_process');
const DATA = process.argv[2];
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2556_b_whatsnew_ui', check, shots: 'P2556B_SHOTS'});  // 2.615.0 (#4938)
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const dbx = (sql, args = []) => JSON.parse(execFileSync('python3', [path.join(__dirname, 'dbx.py'), DATA, sql, JSON.stringify(args)]).toString() || '[]');
const WN = path.join(DATA, 'whatsnew-test.json');
const seen = uid => dbx("SELECT value FROM user_settings WHERE user_id=? AND key='whatsnew_seen'", [uid])[0]?.value;
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
  check(/(05\D11|11\D05)\D?$/.test(heads[0]) && /(04\D11|11\D04)\D?$/.test(heads[1]), 'each line names its date (day and month): ' + heads.join(' | '));
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
  // (CI red of 2.562.0 / 2.563.0: the release fills the shipped static/whatsnew.json; a test container reads only its data dir's example file since #4685)
  fs.unlinkSync(WN);
  setSeen(ME, V(MI - 3));
  const e0 = errs.length;
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  check(await until(() => seen(ME) === CUR), 'no file: the seen version follows: ' + seen(ME));
  check(!d.querySelector('.wnmd'), 'no file: no dialog');
  check(errs.length === e0, 'no file: no script error ' + errs.slice(e0).join(' | '));
  w.close();

  // ================= 2.615.0 (#4938) Firefox: the dialog on a phone is a sheet like the others (full width, as high as its content,
  // a gap before the hint) and on a desktop keeps its width
  fs.writeFileSync(WN, JSON.stringify({versions: [{version: CUR, date: '2026-11-05', items: [{en: 'Newest sentence'}, {en: 'Second sentence'}]}]}));
  await call('PATCH', '/api/settings', {whatsnew_on: '1'});
  const MEAS = `(() => { const m = document.querySelector('.wnmd'); if (!m) return null; const c = m.querySelector(':scope > .card').getBoundingClientRect(), h = m.querySelector('.shint').getBoundingClientRect(), l = m.querySelector('.wnlist').getBoundingClientRect();
    return {cw: Math.round(c.width), ch: Math.round(c.height), cl: Math.round(c.left), cb: Math.round(c.bottom), gap: Math.round(h.top - l.bottom), iw: innerWidth, ih: innerHeight, rem: parseFloat(getComputedStyle(document.documentElement).fontSize)}; })()`;
  const wnShow = async ev => { setSeen(ME, V(MI - 3)); await ev(`location.reload()`); for (let i = 0; i < 60 && !(await ev(`!!document.querySelector('.wnmd')`).catch(() => false)); i++) await sleep(300); await sleep(500); };
  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: login');
    await nav(B + '#today');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 700, height: 900}});
    await wnShow(ev);
    const p = await ev(MEAS);
    check(p && p.cw === p.iw && p.cl === 0, 'phone: the dialog has the full width ' + JSON.stringify(p));
    check(p && p.ch < p.ih * 0.6, 'phone: a short list = a sheet only as high as its content, not the full height ' + JSON.stringify(p));
    check(p && p.cb === p.ih, 'phone: the sheet sits at the bottom ' + JSON.stringify(p));
    check(p && p.gap >= p.rem * 0.5, 'phone: a gap before the hint under the list ' + JSON.stringify(p));
    await shot('p2556b-phone-700.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}}); await sleep(600);
    const dk = await ev(MEAS);
    check(dk && Math.abs(dk.cw - 32.5 * dk.rem) < 2, 'desktop: the dialog keeps its width (32.5 rem) ' + JSON.stringify(dk));
    await shot('p2556b-desktop-1280.png');
  });

  check(!errs.length, 'no script errors: ' + errs.join(' | '));
  console.log(`p2556_b_whatsnew_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e.stack || e); console.log(`p2556_b_whatsnew_ui: ${ok} ok, ${F.length + 1} failed`); process.exit(1); });
