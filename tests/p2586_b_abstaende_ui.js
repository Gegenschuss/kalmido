// kalmido-suite: fresh
// 2.586.0 (#4818): one spacing and one title size. The shells of the pages (Home, Calendar, Time, Bookmarks, Feeds, Agents,
// Budget) have no own padding on top and at the sides and no extra one at the bottom (#view gives it); a title in the content
// (h2 of the page heads) is --fs-l / 600, never as big as #top h1; the time bar has its own class (.tmvbar) and does not
// inherit the stroke / left padding of the file view (.tvbar). Checked in the real layout (Firefox).
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2586_b', check, shots: 'P2586B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});

// route hash, shell selector (null = page without a shell of its own: only the title is checked)
const ALL = 'cal,timeline,habits,pomo,collab,stats,time,agents,comments,family,events,contacts,feeds,contracts,home,care,health,review,travel,reading,budget';
const PAGES = [['today', null, null], ['cal', null, '.calbar h2'], ['time', '.timev', null], ['bookmarks', '.bmview', null],
  ['feeds', '.rssview', null], ['agents', '.agview', null], ['budget', '.bgview', null]];
const PROBE = (shell, title) => `(() => {
  const v = document.querySelector('#view'), out = {};
  const s = ${JSON.stringify(shell)} && v.querySelector(${JSON.stringify(shell)});
  if (${JSON.stringify(shell)}) { if (!s) return {missing: 'shell'}; const c = getComputedStyle(s); out.pad = [c.paddingTop, c.paddingLeft, c.paddingRight, c.paddingBottom]; }
  const t = ${JSON.stringify(title)} && v.querySelector(${JSON.stringify(title)});
  if (${JSON.stringify(title)}) { if (!t) return {missing: 'title'}; const c = getComputedStyle(t); out.fs = parseFloat(c.fontSize); out.fw = c.fontWeight;
    out.fsl = parseFloat(getComputedStyle(document.documentElement).fontSize) * 1; }
  return out; })()`;

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o;
    await o.nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'login');
    await ev(`fetch('/api/settings', {method: 'PATCH', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({features: ${JSON.stringify(ALL)}, lang: 'en', tour: 'done'})}).then(r => r.status)`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await o.nav(B);
    for (let i = 0; i < 30 && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300);
    const fsl = await ev(`(() => { const e = document.createElement('i'); e.style.fontSize = 'var(--fs-l)'; document.body.appendChild(e); const x = parseFloat(getComputedStyle(e).fontSize); e.remove(); return x; })()`);
    for (const [hash, shell, title] of PAGES) {
      await ev(`(typeof go === 'function' ? go('${hash}') : (location.hash = '#${hash}')); 1`);
      let p = null;
      for (let i = 0; i < 40; i++) { p = await ev(PROBE(shell, title)).catch(() => null); if (p && !p.missing) break; await sleep(250); }
      if (!p || p.missing) console.log(hash, 'view:', await ev(`location.hash + ' | ' + (document.querySelector('#view')?.innerHTML || '').slice(0, 300)`).catch(() => '?'));
      check(p && !p.missing, `${hash}: page drawn ${JSON.stringify(p)}`);
      if (!p || p.missing) continue;
      if (p.pad) check(p.pad[0] === '0px' && p.pad[1] === '0px' && p.pad[2] === '0px' && p.pad[3] === '0px', `${hash}: shell without own padding ${JSON.stringify(p.pad)}`);
      if (title) check(p.fs === fsl && p.fw === '600', `${hash}: title --fs-l / 600 (${p.fs}px, ${p.fw}, want ${fsl})`);
      if (hash === 'today' || hash === 'cal') await shot(`p2586b-${hash}.png`);
    }
    // the time bar: own class, nothing of the file view (stroke below, left padding 1rem)
    await ev(`location.hash = '#time'; 1`);
    let tb = null;
    for (let i = 0; i < 40 && !(tb && tb.n); i++) { tb = await ev(`(() => { const b = document.querySelector('#view .timev .tmvbar'); if (!b) return {n: 0}; const c = getComputedStyle(b); return {n: 1, old: !!document.querySelector('#view .timev .tvbar'), bw: c.borderBottomWidth, pl: c.paddingLeft}; })()`).catch(() => null); await sleep(250); }
    check(tb && tb.n === 1 && !tb.old && tb.bw === '0px' && tb.pl === '0px', `time bar: .tmvbar, no .tvbar, no stroke / left padding ${JSON.stringify(tb)}`);
  }, false);
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
