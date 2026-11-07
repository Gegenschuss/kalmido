// kalmido-suite: fresh
// 2.625.0 UI test, part A (#4489): phone 320 px, Settings > Integrations as folded rows: nothing wider than the screen, every
// row a 44 px touch target, the closed list is short (it was 8.5 screens of open forms), a card opens its row. Own container,
// Firefox, invented names only. P2625A_SHOTS=<dir> saves the screenshots (closed list, one open row).
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2625_a_integr320_ui', check, shots: 'P2625A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  await firefox(async ({cmd, ev, nav, ctx, until, shot}) => {
    const wait = s => until(() => ev(s));
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 320, height: 640}});
    await nav(B + 'static/icon.svg');
    const st = await ev(`fetch('/api/auth/login', {method: 'POST', headers: ${JSON.stringify(H)}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    check(st === 200, 'login ' + st);
    await ev(`fetch('/api/admin/setup', {method: 'POST', headers: ${JSON.stringify(H)}, body: JSON.stringify({lang: 'en', collab_all: true, modules: ['cal', 'events', 'contacts', 'family', 'reading', 'docs']})}).then(() => 1)`);
    await ev(`fetch('/api/settings', {method: 'PATCH', headers: ${JSON.stringify(H)}, body: JSON.stringify({tour: 'done', lang: 'en'})}).then(() => 1)`);
    await nav(B + '#today'); await wait(`!!S.booted`);
    await ev(`(() => { settingsModal('integr'); return 1; })()`);
    await wait(`document.querySelectorAll('.smodal [data-pane="integr"] details.introw').length >= 8 && !document.querySelector('.smodal [data-pane="integr"]').classList.contains('hidden')`);
    await wait(`/connected/.test(document.querySelector('[data-intrst="ical"]')?.textContent || '')`);
    const m = await ev(`(() => { const p = document.querySelector('.smodal [data-pane="integr"]'), sc = p.closest('.spanes') || p;
      const rows = [...p.querySelectorAll('details.introw')];
      return JSON.stringify({n: rows.length, wide: rows.filter(r => r.getBoundingClientRect().right > innerWidth + 1).length,
        low: rows.map(r => Math.round(r.querySelector('summary').getBoundingClientRect().height)).filter(h => h < 44),
        over: sc.scrollWidth - sc.clientWidth, tall: Math.round(sc.scrollHeight), vh: innerHeight}); })()`);
    const j = JSON.parse(m || '{}');
    check(j.n >= 8, `${j.n} rows`);
    check(j.wide === 0 && j.over <= 1, `nothing wider than 320 px (rows over the edge ${j.wide}, scroll width over ${j.over})`);
    check(j.low && !j.low.length, `every row is a 44 px touch target (lower: ${JSON.stringify(j.low)})`);
    check(j.tall < 3 * j.vh, `the closed list is short: ${j.tall} px for a ${j.vh} px screen`);
    await shot('p2625-a-integr-320.png');
    await ev(`(() => { document.querySelector('.smodal .icard[data-jump="#s-share-h"]').click(); return 1; })()`);
    check(await wait(`!!document.querySelector('details.introw[data-intr="share"]')?.open`), 'the card opens its row');
    const o = await ev(`(() => { const r = document.querySelector('details.introw[data-intr="share"]'), b = r.getBoundingClientRect(); return JSON.stringify({right: Math.round(b.right), top: Math.round(b.top), vh: innerHeight}); })()`);
    const oj = JSON.parse(o || '{}');
    check(oj.right <= 321 && oj.top < oj.vh, `the open row fits and is in view (${o})`);
    await shot('p2625-a-integr-320-open.png');
  }, true);
  console.log(`p2625_a_integr320_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
