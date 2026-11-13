// kalmido-suite: fresh
// 2.442.0 UI tests (own container, start.sh, Firefox, invented names only):
// - #3739 the phone's drawer: a grid of 4 columns (2.867.0 #5540, was at most two rows) of area icons with every area on (also 360 px, also without labels, light and
//   dark), no name cut, nothing sideways; the search stays on top while Today, Inbox and the areas scroll away, Settings and
//   the account stay at the bottom, the scroll height survives a redraw and a change of area
// - 2.1108.0 #5964: the drawer's head (logo, name, workspace) stays in place and equally wide while the drawer scrolls and on
//   another area; the search sits right under it
// - #2810 a low window (640 x 400): the view switch folds, the head and the tab bar are thinner, the comment box of a task is in
//   the flow; the list ends with room for the plus button; an upright phone with the keyboard open (390 x 400) stays as it
//   was; html counts the browser's default size
const {execFileSync} = require('child_process');
const fs = require('fs');
const path = require('path');
const {sleep, B} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2442_c_ui', check, shots: 'P2442C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const css = fs.readFileSync(path.join(__dirname, '..', 'static', 'app.css'), 'utf8');

(async () => {
  check(/html\{[^}]*font-size:calc\(100% \* var\(--ui\)\)/.test(css) && !/html\{[^}]*font-size:calc\(16px/.test(css), '#2810: html starts from the browser\'s default size');
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  await firefox(async ({cmd, ev, nav, ctx, shot, until}) => {
    const wait = s => until(() => ev(s));
    const size = (width, height) => cmd('browsingContext.setViewport', {context: ctx, viewport: {width, height}});
    await size(360, 740);
    await nav(B + 'static/icon.svg');
    const st = await ev(`fetch('/api/auth/login', {method: 'POST', headers: ${JSON.stringify(H)}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    check(st === 200, 'login ' + st);
    await ev(`fetch('/api/admin/setup', {method: 'POST', headers: ${JSON.stringify(H)}, body: JSON.stringify({lang: 'en', collab_all: true, time_all: true, modules: ['agents', 'comments']})}).then(() => fetch('/api/settings', {method: 'PATCH', headers: ${JSON.stringify(H)}, body: JSON.stringify({lang: 'en', tour: 'done', features: 'cal,wiki,sheets,habits,agents,comments,timeline,clients,contacts,reading,collab,matrix'})})).then(() => 1)`);
    const lid = await ev(`fetch('/api/lists', {method: 'POST', headers: ${JSON.stringify(H)}, body: JSON.stringify({name: 'Website', kind: 'project'})}).then(r => r.json()).then(async l => { for (let i = 0; i < 30; i++) await fetch('/api/tasks', {method: 'POST', headers: ${JSON.stringify(H)}, body: JSON.stringify({title: 'Task ' + i, list_id: l.id})}); for (let i = 0; i < 25; i++) await fetch('/api/lists', {method: 'POST', headers: ${JSON.stringify(H)}, body: JSON.stringify({name: 'List ' + i})}); return l.id; })`);
    const drawer = async () => { await ev(`(() => { sideDrawerOpen(); renderSide(); return 1; })()`); return wait(`!!document.querySelector('#side.open .sbmr .srb[data-sbb]')`); };
    const GRID = `(() => { const r = document.querySelector('#side .sbmr'), bs = [...r.querySelectorAll('.srb[data-sbb]')], R = e => e.getBoundingClientRect(), s = document.querySelector('#side');
      return {n: bs.length, rows: new Set(bs.map(b => Math.round(R(b).top))).size, inside: bs.every(b => R(b).right <= R(r).right + 1), side: s.scrollWidth <= s.clientWidth + 1, minH: Math.min(...bs.map(b => R(b).height)),
        cut: bs.map(b => b.querySelector('.srbn')).filter(n => n && getComputedStyle(n).display !== 'none' && !n.classList.contains('srcut') /* 2.458.0 (#3880): a word too wide ends in "…", never split */ && (n.scrollHeight > n.clientHeight + 1 || n.scrollWidth > n.clientWidth + 1)).map(n => n.textContent)}; })()`;
    await nav(B + '#today'); await wait(`!!S.booted`);
    // many areas: a long name in place of one of them
    for (const w of [360, 320]) {
      await size(w, 740); await drawer(); await sleep(350);
      await ev(`(() => { const n = document.querySelector('#side .sbmr .srb[data-sbb="life"] .srbn, #side .sbmr .srb .srbn'); n.dataset.p2442o ??= n.textContent; n.textContent = 'Reisen & Kontakte'; sbb_fit(); return 1; })()`);  // 2.458.0 (#3880): the app fits a name after each draw; the swapped name too (with Notes, #3405, 11 areas = 6 columns at 320 px)
      const g = await ev(GRID);
      check(g.n >= 8 && g.rows === Math.ceil(g.n / 4) && g.inside && g.side && g.minH >= 43 && !g.cut.length, `#3739 ${w}: the grid of 4 columns, nothing cut ` + JSON.stringify(g));  // 2.867.0 (#5540): 4 per row (was at most two rows)
    }
    // 2.651.0 (#5032): the swapped name back - since #4509 renderSide keeps the nodes when its HTML is the same, so a redraw no longer
    // undid the swap: the two-line name made the row 4 px higher and Today ended 1 px under the top of the search after 400 px
    await ev(`(() => { const n = document.querySelector('#side .sbmr .srbn[data-p2442o]'); if (n) { n.textContent = n.dataset.p2442o; delete n.dataset.p2442o; sbb_fit(); } return 1; })()`);
    // 11 areas (the drawer of the report): two copies, the columns sbm_rowHtml sets for 11
    await size(360, 740); await drawer();
    await ev(`(() => { const r = document.querySelector('#side .sbmr'), bs = r.querySelectorAll('.srb[data-sbb]'); while (r.querySelectorAll('.srb[data-sbb]').length < 11) r.append(bs[2].cloneNode(true)); r.style.setProperty('--sbmc', sbm_cols(11)); sbb_fit(); return 1; })()`);  // 2.867.0 (#5540): 4 columns (was 6)
    const g11 = await ev(GRID);
    check(g11.n === 11 && g11.rows === 3 && g11.inside && !g11.cut.length, '#5540 11 areas: three rows of 4 ' + JSON.stringify(g11));  // 2.867.0 (#5540): was two rows
    check(await ev(`document.querySelector('#side .sbmr').style.getPropertyValue('--sbmc') === '4' && sbm_cols(11) === 4 && sbm_cols(5) === 5 && sbm_cols(3) === 3 &&  /* 2.867.0 (#5540) */ sbm_rowHtml(() => false).includes('--sbmc:')`), '#3739: the row sets its columns');
    await drawer(); await shot('p2442-drawer.png');
    await ev(`(() => { document.documentElement.classList.add('rail-nolabel'); renderSide(); return 1; })()`);
    const g2 = await ev(GRID);
    check(g2.rows === Math.ceil(g2.n / 4) && g2.inside && g2.side, '#3739: without labels too '  /* 2.867.0 (#5540): the grid of 4 */ + JSON.stringify(g2));
    await ev(`(() => { document.documentElement.classList.remove('rail-nolabel'); renderSide(); return 1; })()`);
    // scrolling
    const POS = `(() => { const s = document.querySelector('#side'), R = e => e && e.getBoundingClientRect(), q = x => document.querySelector(x), sr = R(s), se = q('#side .sbmsrch .scmd'), t = q('#side .sg-focus .srow[data-go="today"]'), row = q('#side .sbmr'), d = q('#side .sbdock'), h = q('#side .sbfix-m .sbhead'), wb = q('#side .sbhead .wsbar'), at = se && document.elementFromPoint(R(se).left + 40, R(se).top + R(se).height / 2);
      return {top: s.scrollTop, max: s.scrollHeight - s.clientHeight, se: se && Math.round(R(se).top - sr.top), seH: se && Math.round(R(se).height), onSearch: !!(at && at.closest('.scmd')), today: t && Math.round(R(t).bottom - sr.top), row: row && Math.round(R(row).bottom - sr.top), dock: d && Math.round(sr.bottom - R(d).bottom), set: !!(d && d.querySelector('.sset')), acct: !!(d && d.querySelector('.sbacct')), hd: h && [Math.round(R(h).top - sr.top), Math.round(R(h).bottom - sr.top), Math.round(R(h).width)].join(), hb: h && Math.round(R(h).bottom - sr.top), wb: wb && [Math.round(R(wb).left), Math.round(R(wb).top - sr.top), Math.round(R(wb).width)].join(), cw: s.clientWidth, hcs: h && (c => [c.position, c.height, c.paddingTop, c.display].join())(getComputedStyle(h)), wbIn: !!(h && wb && h.contains(wb)), onHead: !!(h && document.elementFromPoint(R(h).left + 20, R(h).top + R(h).height / 2)?.closest('.sbhead'))}; })()`;  // 2.1108.0 (#5964): the head's place, its workspace button and the drawer's inner width
    const p0 = await ev(POS);
    await ev(`(() => { document.querySelector('#side').scrollTop = 500; return 1; })()`); await sleep(100);  // 2.867.0 (#5540): 500 (was 400) - the grid of 4 has more rows, Today sits lower
    const p1 = await ev(POS);
    check(p0.max > 200 && p1.top === 500, '#3739: the drawer scrolls ' + JSON.stringify(p1));
    // 2.1108.0 (#5964): the head (logo, name, workspace) is pinned on top and the search right under it (was: the search alone on top, < 40 px)
    check(p1.se >= p1.hb - 1 && p1.se < p1.hb + 24 && p1.onSearch, '#3739/#5964: the search stays right under the head, nothing over it ' + JSON.stringify(p1));
    check(p1.hd === p0.hd && p1.wb === p0.wb && p1.cw === p0.cw && p1.onHead, '#5964: the head stands still while the drawer scrolls, same place, same width ' + JSON.stringify({p0, p1}));
    check(p1.today <= p1.se && p1.row <= p1.se, '#3739: Today, Inbox and the areas scrolled away under it ' + JSON.stringify(p1));
    check(p1.dock === 0 && p1.set && p1.acct, '#3739: Settings and the account stay at the bottom ' + JSON.stringify(p1));
    await shot('p2442-drawer-scrolled.png');
    await ev(`(() => { renderSide(); return 1; })()`);
    check((await ev(POS)).top === 500, '#3739: a redraw keeps the scroll height');
    await ev(`(() => { document.querySelector('#side').scrollTop = 60; document.querySelector('#side .sbmr .srb[data-sbb="tasks"]:not(.on), #side .sbmr .srb[data-sbb="agents"]').click(); return 1; })()`);
    await sleep(500);
    const p2 = await ev(POS);
    check(p2.top === 60 || p2.top === p2.max, '#3739: a change of area keeps the scroll height ' + JSON.stringify(p2));
    check(p2.hd === p0.hd && p2.wb === p0.wb && p2.cw === p0.cw, '#5964: another area (other list length) leaves the head where it was ' + JSON.stringify({p0, p2}));
    await ev(`(() => { document.querySelector('#side').scrollTop = 200; return 1; })()`); await sleep(100);
    for (const look of ['dark', 'light']) {
      await ev(`(() => { document.documentElement.setAttribute('data-theme', '${look}'); return 1; })()`); await sleep(100);
      const c = await ev(`(() => { const G = e => getComputedStyle(e).backgroundColor; return {s: G(document.querySelector('#side .sbmsrch')), d: G(document.querySelector('#side'))}; })()`);
      check(c.s === c.d && c.s !== 'rgba(0, 0, 0, 0)', `#3739 ${look}: the search has the drawer's background ` + JSON.stringify(c));
      await shot(`p2442-drawer-${look}.png`);
    }

    // #2810
    const LOW = `(() => { const R = e => e && e.getBoundingClientRect(), q = x => document.querySelector(x), v = q('.vsegm'), t = q('#top'), tb = q('#tabs'), f = q('#fab'), w = q('#view');
      return {seg: v ? Math.round(R(v).height) : 0, words: v ? [...v.querySelectorAll('button>span')].filter(s => getComputedStyle(s).display !== 'none').length : 0, top: Math.round(R(t).height), tabs: tb ? Math.round(R(tb).height) : 0, fab: f ? Math.round(R(f).height) : 0, pad: parseFloat(getComputedStyle(w).paddingBottom), tb: tb ? parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--tabs-h')) : 0}; })()`;
    await ev(`(() => { sideDrawerClose?.(); return 1; })()`).catch(() => 0);
    await size(640, 400); await nav(B + '#l/' + lid); await wait(`!!document.querySelector('.vsegm') && !!document.querySelector('#view .row, #view [data-id]')`);
    const low = await ev(LOW);
    await size(640, 800); await sleep(250);
    const tall = await ev(LOW);
    // 2.828.0 (#5443): the switch has one form on every width (only the active view says its name), so a low window only makes it thinner
    check(low.seg > 0 && low.seg < tall.seg && low.words <= 1 && tall.words === 1, '#2810: the view switch folds ' + JSON.stringify({low, tall}));
    check(low.top < tall.top && low.tabs < tall.tabs, '#2810: head and tab bar are thinner ' + JSON.stringify({low, tall}));
    check(low.pad >= low.tabs + low.fab + 16, '#2810: the list ends with the plus button\'s room ' + JSON.stringify(low));
    await size(390, 400); await sleep(250);
    const up = await ev(LOW);
    check(up.top === tall.top && up.tabs === tall.tabs, '#2810: an upright phone with the keyboard stays as it was ' + JSON.stringify(up));
    const tid = await ev(`fetch('/api/tasks', {method: 'POST', headers: ${JSON.stringify(H)}, body: JSON.stringify({title: 'Open me', list_id: ${lid}})}).then(r => r.json()).then(t => t.id)`);
    await size(640, 400); await nav(B + '#l/' + lid); await wait(`!!S.booted && !!document.querySelector('#view [data-id]')`);
    await wait(`(() => { openDetail(${tid}); return !!document.querySelector('#detail .dbot'); })()`);
    if (await wait(`!!document.querySelector('#detail .dbot')`)) {
      const pos = await ev(`getComputedStyle(document.querySelector('#detail .dbot')).position`);
      check(pos === 'static', '#2810: the comment box is in the flow in a low window: ' + pos);
      await size(640, 800); await sleep(250);
      check(await ev(`getComputedStyle(document.querySelector('#detail .dbot')).position`) === 'sticky', '#2810: docked in a tall window');
    } else check(false, '#2810: the task did not open');
  }, true);
  console.log(`p2442_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
