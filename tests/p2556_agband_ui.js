// 2.556.0 (#4663) UI test: the agent band follows its own width (container query), not the window's. Own container (start.sh), Firefox.
// kalmido-suite: fresh
// - 280 px band, 3 agents: every name is visible and not cut to nothing; state and task only in the title; "+N" for the boxes that
//   do not fit (min 8rem) and it opens the Agents page; 1200 px band: all three boxes with state, no "+N"; 200 px: dots only
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2556_agband_ui', check, shots: 'P2556AB_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2556AB_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: process.env});

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await fetch(B + 'api/settings', {method: 'PATCH', headers: {...H, Cookie: CA}, body: JSON.stringify({lang: 'en', tour: 'done', features: 'cal,comments,collab,agents'})});
  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.ok)`);
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1400, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    await nav(B + '#inbox');
    check(await ready(ev, `typeof S !== 'undefined' && S.booted && typeof bandAgents === 'function' && typeof agb_fit === 'function'`, 80), 'booted');
    // three invented agents (the band's own source is replaced, the rest of the band is the real one)
    await ev(`(() => { const mk = (i, n, st, tx) => ({id: 9000 + i, name: n, enabled: true, online: true, contact_age: 0, status: st, status_text: tx, org_id: null});
      window.__ags = [mk(1, 'Paula Planer', 'working', 'planning'), mk(2, 'Bernd Berichte', 'idle', ''), mk(3, 'Carla Code', 'idle', '')];
      window.bandAgents = () => window.__ags; renderView(); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('#view .agband .agb-a').length === 3`, 40), 'the band shows three agents');
    const probe = (w, hid) => ev(`(async () => { const b = document.querySelector('#view .agband'); b.style.width = '${w}px'; b.style.maxWidth = '${w}px';
      const want = ${hid};  // the number of hidden boxes the width must lead to (the observer answers a little later: wait for the state)
      for (let i = 0; i < 100; i++) { const hd = [...b.querySelectorAll('.agb-a')].filter(c => c.hidden).length; if (hd === want) break; await new Promise(r => setTimeout(r, 50)); }
      const vis = e => !!e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden';
      const cells = [...b.querySelectorAll('.agb-a')].filter(vis), more = b.querySelector('.agb-more');
      return {w: b.clientWidth, n: cells.length, names: cells.map(c => { const e = c.querySelector('b'); return vis(e) && e.clientWidth > 20 && e.scrollWidth <= e.clientWidth + 1 ? e.textContent : '!' + e.textContent + ':' + e.clientWidth + '/' + e.scrollWidth; }),
        state: cells.filter(c => vis(c.querySelector('.agb-h .muted'))).length, task: cells.filter(c => vis(c.querySelector('.agb-t'))).length,
        more: vis(more) ? more.textContent : '', cellW: cells.map(c => Math.round(c.getBoundingClientRect().width)), title: cells[0]?.title || '',
        cellsShown: vis(b.querySelector('.agb-cells')), sum: vis(b.querySelector('.agb-tog .agb-sumn')), side: b.scrollWidth <= b.clientWidth + 1}; })()`);
    // wide: unchanged
    let p = await probe(1200, 0);
    check(p.n === 3 && p.state === 3 && p.task === 3 && !p.more && p.names.every(x => !x.startsWith('!')), 'wide (1200 px): three boxes with state and task, no "+N" ' + JSON.stringify(p));
    if (process.env.P2556AB_SHOTS) await shot('p2556ab-1200');
    // a column of 280 px: names win, boxes at least 8rem, the rest is "+N"
    p = await probe(280, 2);
    check(p.n >= 1 && p.n <= 2 && p.names.every(x => !x.startsWith('!') && x.length > 3) && p.state === 0 && p.task === 0, '280 px: dot + name only, names visible and not cut to nothing ' + JSON.stringify(p));
    check(p.more === '+' + (3 - p.n) && p.cellW.every(x => x >= 125) && p.side, '280 px: the rest is "+N", boxes at least 8rem ' + JSON.stringify(p));
    check(/Paula Planer/.test(p.title) && /working|planning/.test(p.title), '280 px: state in the title ' + p.title);
    if (process.env.P2556AB_SHOTS) await shot('p2556ab-280');
    // 420 px (above 30rem): all fit by minimum width? 3 * 8rem = 384 px + nothing, so three boxes with state
    p = await probe(520, 0);
    check(p.n === 3 && !p.more, '520 px: three boxes, no "+N" ' + JSON.stringify(p));
    // the "+N" opens the Agents page
    await probe(280, 2);
    await ev(`document.querySelector('#view .agband .agb-more').click()`);
    check(await ready(ev, `location.hash === '#agents'`, 20), '"+N" opens the Agents page ' + await ev('location.hash'));
    await nav(B + '#inbox');
    await ready(ev, `!!document.querySelector('#view .agband')`, 40);
    // narrow: only the dots
    p = await probe(200, 0);
    check(!p.cellsShown && p.sum, '200 px: only the dots of the summary ' + JSON.stringify(p));
    if (process.env.P2556AB_SHOTS) await shot('p2556ab-200');
  });
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
