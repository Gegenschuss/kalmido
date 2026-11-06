// kalmido-suite: fresh
// 2.571.0 UI test, part A (#4790): phone 320 px, in the office the row of the areas in the drawer (#side .sbmr) keeps its height
// (at least one row of tiles) however long the office tree is; a tile is tappable and changes the area. Own container, Firefox,
// invented names only.
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2571_a_ui', check, shots: 'P2571A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  await firefox(async ({cmd, ev, nav, ctx, until}) => {
    const wait = s => until(() => ev(s));
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 320, height: 640}});
    await nav(B + 'static/icon.svg');
    const st = await ev(`fetch('/api/auth/login', {method: 'POST', headers: ${JSON.stringify(H)}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    check(st === 200, 'login ' + st);
    await ev(`fetch('/api/admin/setup', {method: 'POST', headers: ${JSON.stringify(H)}, body: JSON.stringify({lang: 'en', collab_all: true, time_all: true, modules: ['office', 'agents', 'comments']})}).then(() => 1)`);
    await nav(B + '#office/start'); await wait(`!!S.booted`);
    await ev(`(() => { sideDrawerOpen(); renderSide(); return 1; })()`);
    await wait(`!!document.querySelector('#side.open .sbmr .srb[data-sbb]')`);
    const H1 = await ev(`Math.round(document.querySelector('#side .sbmr').getBoundingClientRect().height)`);
    check(H1 >= 44, '#4790: the row of the areas in the office is at least one tile high, is ' + H1);
    // the same with a content that is much taller than the drawer (the long office tree)
    await ev(`(() => { const s = document.querySelector('#side'); const d = document.createElement('div'); d.id = 'p2571pad'; d.style.cssText = 'height:3000px;flex:0 1 auto'; s.appendChild(d); return 1; })()`);
    const H2 = await ev(`Math.round(document.querySelector('#side .sbmr').getBoundingClientRect().height)`);
    check(H2 >= 44, '#4790: still one tile high with a tall drawer content, is ' + H2);
    const cur = await ev(`location.hash`);
    const sel = await ev(`(() => { const b = [...document.querySelectorAll('#side .sbmr .srb[data-sbb]')].find(x => !x.classList.contains('on') && x.dataset.sbb !== 'office'); if (!b) return ''; b.id = 'p2571t'; return b.dataset.sbb; })()`);
    check(!!sel, '#4790: another area tile exists');
    await ev(`document.querySelector('#p2571t')?.scrollIntoView({block: 'center'}); document.querySelector('#p2571t')?.click(); 1`);
    await until(async () => (await ev(`location.hash`)) !== cur);
    check((await ev(`location.hash`)) !== cur, '#4790: a tile in the office changes the area, was ' + cur + ' now ' + await ev('location.hash'));
  }, true);
  console.log(`p2571_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
