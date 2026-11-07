// 2.631.0 A (#4993) UI test (Firefox, phone with touch), fresh DB: a bottom sheet grows on a drag at the grip only up to the
// height of its content (dialog "New for you" with a short list; the bell with a stored height far above its list)
// kalmido-suite: fresh
const {boot, errs, B, login} = require('./boot');
const fs = require('fs');
const path = require('path');
const DATA = process.argv[2];
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2631_a_sheet_ui', check, shots: 'P2631A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const dbx = (sql, args = []) => require('child_process').execFileSync('python3', [path.join(__dirname, 'dbx.py'), DATA, sql, JSON.stringify(args)]);
const WN = path.join(DATA, 'whatsnew-test.json');

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', whatsnew_on: '1'});
  const ME = (await call('GET', '/api/state')).me.id;
  const CUR = (await call('GET', '/api/about')).version;
  const [MA, MI] = CUR.split('.').map(Number);
  fs.writeFileSync(WN, JSON.stringify({versions: [{version: CUR, date: '2026-11-05', items: [{en: 'Newest sentence'}, {en: 'Second sentence'}]}]}));
  dbx("INSERT INTO user_settings(user_id, key, value) VALUES(?, 'whatsnew_seen', ?) ON CONFLICT(user_id, key) DO UPDATE SET value=excluded.value", [ME, `${MA}.${MI - 3}.0`]);

  await firefox(async ({cmd, ev, nav, ctx, drag, until}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + '#today');
    check(await until(`!!document.querySelector('.wnmd > .card')`), 'the dialog is open');
    // natural height of the card (height auto), read from the page
    const NAT = `(() => { const c = document.querySelector('.wnmd > .card'), h = c.style.height, m = c.style.maxHeight; c.style.height = 'auto'; c.style.maxHeight = 'none'; const n = c.getBoundingClientRect().height; c.style.height = h; c.style.maxHeight = m; return n; })()`;
    const H0 = await ev(`document.querySelector('.wnmd > .card').getBoundingClientRect().height`), nat = await ev(NAT);
    check(nat < 844 * 0.6, 'setup: the content is short ' + nat);
    const top = await ev(`document.querySelector('.wnmd > .card').getBoundingClientRect().top`);
    await drag(195, top + 12, 0, -500, 'touch');
    await until(`!document.querySelector('.wnmd > .card').classList.contains('sd-drag')`);
    const H1 = await ev(`document.querySelector('.wnmd > .card').getBoundingClientRect().height`);
    check(H1 <= nat + 2, `dialog: the grip does not pull it above its content (${H1} <= ${nat})`);
    check(await ev(`!!document.querySelector('.wnmd')`), 'dialog: still open');

    // the bell with a stored height far above its list
    await ev(`(() => { document.querySelector('.wnmd .btn.pri, .wnmd [data-close], .wnmd .btn')?.click(); localStorage.setItem('tasks.bellSheetH', '200'); return 1; })()`);
    await nav(B + '#today'); await cmd('browsingContext.reload', {context: ctx, wait: 'complete'});
    await until(`!!document.querySelector('#kbar .bell, #top .bell')`);
    await ev(`document.querySelector('.wnmd')?.remove(); document.querySelector('#kbar .bell, #top .bell').click(); 1`);
    check(await until(`!!document.querySelector('#pop .bpop')`), 'the bell is open');
    const bell = await ev(`(() => { const p = document.querySelector('.bpop'), h = p.style.height, m = p.style.maxHeight; const now = p.getBoundingClientRect().height; p.style.height = 'auto'; p.style.maxHeight = 'none'; const n = p.getBoundingClientRect().height; p.style.height = h; p.style.maxHeight = m; return {now, n, ih: innerHeight}; })()`);
    check(bell.now <= bell.n + 2, 'bell: a stored height above the list is capped on opening ' + JSON.stringify(bell));
    const bt = await ev(`document.querySelector('#pop').getBoundingClientRect().top`);
    await drag(195, await ev(`document.querySelector('[data-bpgrab]').getBoundingClientRect().top + 8`), 0, -500, 'touch');
    await until(`true`, {timeout: 300});
    const b2 = await ev(`document.querySelector('.bpop').getBoundingClientRect().height`);
    check(b2 <= bell.n + 2, `bell: dragging the handle up stays within the list (${b2} <= ${bell.n})`);
    check(bt >= 0, 'bell: sheet measured');
  }, true);

  check(!errs.length, 'no script errors: ' + errs.join(' | '));
  console.log(`p2631_a_sheet_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e.stack || e); console.log(`p2631_a_sheet_ui: ${ok} ok, ${F.length + 1} failed`); process.exit(1); });
