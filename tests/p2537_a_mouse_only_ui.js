// kalmido-suite: fresh
// 2.537.0 (#4574): buttons that open a new tab or a window of its own exist only with a mouse (mw_desk()); pictures open in
// the app's preview (lightbox), never in a new tab. Own container (start.sh), Firefox.
// - touch phone (390): the PDF preview has no "open in new tab" link, a picture of the file search opens the lightbox and
//   window.open is never called, the table window button is missing
// - desktop (mouse): the PDF preview has the new-tab link
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2537_a_mouse_only_ui', check, shots: 'P2537A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.BASE) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CK = await login('alice');
  await fetch(B + 'api/settings', {method: 'PATCH', headers: {...H, Cookie: CK}, body: JSON.stringify({lang: 'en', tour: 'done'})});

  const run = async (touch, w, fn) => firefox(async o => {
    const {cmd, ev, nav, ctx} = o;
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: w, height: 800}});
    await nav(B);
    for (let i = 0; i < 40 && !(await ev(`typeof pdfView === 'function' && typeof ftxtOpenLf === 'function' && typeof mw_desk === 'function'`).catch(() => false)); i++) await sleep(300);
    await fn(o);
  }, touch);

  await run(true, 390, async ({ev}) => {
    check(await ev(`mw_desk() === false`), 'touch: mw_desk() is false');
    await ev(`(window.__opened = 0, window.open = () => { window.__opened++; return null; }, pdfView({url: '/static/icon.svg', name: 'a.pdf', size: 10}), 1)`);
    await sleep(500);
    check(await ev(`!!document.querySelector('.pview') && !document.querySelector('.pview a[target="_blank"]')`), 'touch: no new-tab link in the PDF preview');
    await ev(`(document.querySelector('.pview [data-pv="x"]')?.click(), 1)`);
    await ev(`(ftxtOpenLf({id: 1, name: 'p.png', size: 5, mime: 'image/png'}), 1)`);
    await sleep(300);
    check(await ev(`!!document.querySelector('.lightbox img[src^="/api/list-files/1"]') && window.__opened === 0`), 'touch: a picture opens the lightbox, no window.open');
    await ev(`(document.querySelector('.lightbox')?.remove(), 1)`);
    check(await ev(`typeof shz_btnsHtml === 'function' ? !/data-shz="win"/.test(shz_btnsHtml({id: 1})) : true`), 'touch: no table window button');
    check(await ev(`typeof shz_win === 'function' ? shz_win(1) === null && window.__opened === 0 : true`), 'touch: shz_win opens nothing');
  });

  await run(false, 1280, async ({ev}) => {
    check(await ev(`mw_desk() === true`), 'mouse: mw_desk() is true');
    await ev(`(pdfView({url: '/static/icon.svg', name: 'a.pdf', size: 10}), 1)`);
    await sleep(500);
    check(await ev(`!!document.querySelector('.pview a[target="_blank"]')`), 'mouse: the PDF preview has the new-tab link');
    check(await ev(`typeof shz_btnsHtml === 'function' ? /data-shz="win"/.test(shz_btnsHtml({id: 1})) : true`), 'mouse: table window button present');
  });

  console.log(`p2537_a_mouse_only_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
