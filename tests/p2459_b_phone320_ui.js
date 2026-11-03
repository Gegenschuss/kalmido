// kalmido-suite: fresh
// 2.459.0 B (#3853) UI test, own container (start.sh), Firefox at 320 x 640 (phone, touch). Invented data only.
// P2459B_NOSTART=1 = the container runs. For each place of the audit: no element over the right edge, the page does not scroll
// sideways, buttons of one bar do not overlap. Bars of tabs may scroll themselves (their own scrollWidth), the page not.
// Places: time (+ running timer), calendar, wiki and notes bar, project overview, receipts list, pipeline, selection bar #mbar,
// document title (ellipsis), account servers row, meal dialog. In German: the audit's texts were the long ones.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2459_b_phone320_ui', check, shots: 'P2459B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2459B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };

// the audit in the page: elements (visible, inside `root`) whose right edge is over the viewport (only a bar's own scroll excuses
// them: #view and the dialogs scroll too, but that is the page scrolling sideways), the width of the page and #view, and
// overlapping neighbours among the buttons of one bar (`bars`)
const AUDIT = (root, bars) => `(() => { const vw = innerWidth, R = document.querySelector(${JSON.stringify(root)}) || document.body;
  const over = [...R.querySelectorAll('*')].filter(e => e.offsetParent && getComputedStyle(e).position !== 'fixed' && !e.closest('[data-scrolls]') && e.getBoundingClientRect().width > 0
    && e.getBoundingClientRect().right > vw + 1 && !(() => { for (let p = e.parentElement; p && p !== document.body && p !== R && p.id !== 'view' && !p.matches('.modal, .smodal'); p = p.parentElement) { const ox = getComputedStyle(p).overflowX; if (/auto|scroll|hidden|clip/.test(ox) && p.getBoundingClientRect().right <= vw + 1) return true; } return false; })()).map(e => (e.className || e.tagName) + ':' + Math.round(e.getBoundingClientRect().right)).slice(0, 6);
  const lap = []; for (const b of document.querySelectorAll(${JSON.stringify(bars)})) { const k = [...b.children].filter(e => e.offsetParent && e.getBoundingClientRect().width > 0).map(e => e.getBoundingClientRect());
    for (let i = 0; i < k.length; i++) for (let j = i + 1; j < k.length; j++) { const a = k[i], c = k[j]; if (a.left < c.right - 1 && c.left < a.right - 1 && a.top < c.bottom - 1 && c.top < a.bottom - 1) lap.push(b.className + ' ' + i + '/' + j); } }
  const box = [document.querySelector('#view'), R].filter(Boolean), page = vw + Math.max(document.documentElement.scrollWidth - vw, ...box.map(e => e.scrollWidth - e.clientWidth));
  return {vw, page, over, lap}; })()`;

const DIAG = ev => ev(`JSON.stringify({h: location.hash, k: S?.route?.key, n: S?.tasks?.size, pomo: !!S?.pomo, v: (document.querySelector('#view')?.textContent || '').slice(0, 120), c: document.querySelector('#view')?.firstElementChild?.className})`).catch(e => String(e));
(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'de'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'de', collab_all: true, modules: ['cal', 'comments']});
  const st = await call(CA, 'GET', '/api/state'), feats = new Set(((st.settings || {}).features || '').split(',').filter(Boolean));
  ['time', 'events', 'wiki', 'notes', 'office', 'pomo'].forEach(x => feats.add(x));
  await call(CA, 'PATCH', '/api/settings', {tour: 'done', lang: 'de', workspace: 'all', features: [...feats].join(',')});
  const me = (await call(CA, 'GET', '/api/state')).me, ORG = me.workspaces[0].id;
  const L1 = (await call(CA, 'POST', '/api/lists', {name: 'Work', org_id: ORG})).id;
  const T = [];
  for (const n of ['Plan the week', 'Write the offer', 'Call the printer']) T.push((await call(CA, 'POST', '/api/tasks', {title: n, list_id: L1})).id);

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const place = async (o, name, hash, waitExpr, root, bars) => {
    await o.nav(B + hash);
    check(await ready(o.ev, waitExpr, 60), name + ': the place is up ' + await DIAG(o.ev));
    const a = await o.ev(AUDIT(root || '#view', bars || '.tvbar, .calbar, .ntbar, .povh, .ofcbar, .tvr-acts'));
    check(a && a.page <= a.vw, name + ': the page does not scroll sideways ' + JSON.stringify(a));
    check(a && !a.over.length, name + ': nothing over the right edge ' + JSON.stringify(a));
    check(a && !a.lap.length, name + ': buttons of a bar do not overlap ' + JSON.stringify(a));
    await o.shot(`p2459b-${name.replace(/\W+/g, '-')}.png`);
  };

  // a real state instead of a fixed time: the old page's mark is gone and the app has its tasks again
  const reload = async o => { await o.ev(`(() => { window.__old = 1; location.reload(); return 1; })()`).catch(() => 0); check(await ready(o.ev, `!window.__old && typeof S !== 'undefined' && !!S.me && !!document.querySelector('#view')`, 60), 'reloaded ' + await DIAG(o.ev)); };

  await firefox(async o => {
    const {cmd, ev, ctx, nav} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 320, height: 640}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'login');

    await place(o, 'time', '#time', `!!document.querySelector('#view .tvseg')`);
    await place(o, 'calendar', '#cal', `!!document.querySelector('#view .calbar .seg')`);
    await place(o, 'wiki', '#wiki', `!!document.querySelector('#view .ntbar')`);
    await place(o, 'notes', '#notes', `!!document.querySelector('#view .ntbar')`);
    await ev(`localStorage.setItem('tasks.pov', '[${L1}]')`);
    await nav(B + '#l/' + L1);
    await reload(o);
    await place(o, 'projects', '#l/' + L1, `!!document.querySelector('#view .povh')`);
    await place(o, 'receipts', '#office/books/receipts', `!!document.querySelector('#view .rcl-exp, #view .rcl-empty')`);
    await place(o, 'pipeline', '#office/pipeline', `!!document.querySelector('#view .ofcbar, #view .ppseg')`);

    // the two places inside a dialog
    await nav(B + '#office/meals');
    check(await ready(ev, `!!document.querySelector('[data-bw="new"]')`, 60), 'meals: the list is up ' + await DIAG(ev));
    await ev(`(() => { document.querySelector('[data-bw="new"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal.bwdlg, .bwdlg')`), 'meals: the dialog opens');
    const dm = await ev(AUDIT('.bwdlg', '.bwfoot, .bwlines li'));
    check(dm && dm.page <= dm.vw && !dm.over.length && !dm.lap.length, 'meal dialog: inside the screen, no overlap ' + JSON.stringify(dm));
    await o.shot('p2459b-meal-dialog.png');
    await nav(B + '#time');
    await reload(o);
    await ev(`(() => { settingsModal('account'); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.smodal .msvbtns')`, 60), 'servers: the account section is up');
    const sv = await ev(AUDIT('.smodal', '.msvbtns'));
    check(sv && sv.page <= sv.vw && !sv.over.length && !sv.lap.length, 'servers: inside the screen, no overlap ' + JSON.stringify(sv));
    await o.shot('p2459b-servers.png');
    await reload(o);

    // the running timer: Pause / end the focus round do not run into each other
    check((await call(CA, 'POST', '/api/pomo/start', {kind: 'focus', minutes: 25, task_id: T[0]})).http < 300, 'pomo started');
    await reload(o);
    await place(o, 'time-focus', '#time', `!!document.querySelector('#view .tvpomo .tvr-acts')`);

    // the selection bar: "1 selected" does not lie over Move, the X is inside the screen
    await ev(`localStorage.setItem('tasks.pov', '[]')`);
    await nav(B + '#l/' + L1);
    await reload(o);
    if (await ready(ev, `!!S && S.tasks && S.tasks.size >= 3`, 60)) {
      await ev(`(() => { S.multiMode = true; S.multi.add(${T[0]}); render(); renderMultiBar(); return 1; })()`);
      const ok2 = await ready(ev, `!!document.querySelector('#mbar:not(.hidden) .mbx')`);
      check(ok2, 'mbar: the selection bar is up ' + await ev(`(document.querySelector('#mbar')?.outerHTML || 'none').slice(0, 300)`));
      const g = await ev(`(() => { const b = document.querySelector('#mbar'), r = b.getBoundingClientRect(), x = b.querySelector('.mbx').getBoundingClientRect(), c = b.querySelector('.mcount').getBoundingClientRect();
        const bb = [...b.querySelectorAll('.mbb')].map(e => e.getBoundingClientRect()), lap = bb.some(e => e.left < c.right - 1 && c.left < e.right - 1 && e.top < c.bottom - 1 && c.top < e.bottom - 1);
        return {right: Math.round(r.right), left: Math.round(r.left), xr: Math.round(x.right), vw: innerWidth, lap, sw: b.scrollWidth, cw: b.clientWidth}; })()`);
      check(g && g.xr <= g.vw && g.left >= 0 && g.right <= g.vw && !g.lap && g.sw <= g.cw + 1, 'mbar: inside the screen, count does not overlap a button ' + JSON.stringify(g));
      // 2.499.0 (#3899): the buttons' lower bound is 44 px, and four of them with the close button stay in one row at 320 px
      const m = await ev(`(() => { const bs = [...document.querySelectorAll('#mbar .mbb')]; return {n: bs.length, min: Math.min(...bs.map(e => parseFloat(getComputedStyle(e).minWidth))), w: Math.min(...bs.map(e => e.getBoundingClientRect().width)), tops: new Set(bs.map(e => Math.round(e.getBoundingClientRect().top))).size}; })()`);
      check(m && m.n === 4 && m.min >= 44 && m.w >= 44 && m.tops === 1, '#3899: selection bar buttons 44 px wide, one row ' + JSON.stringify(m));
    } else check(false, 'mbar: tasks loaded ' + await DIAG(ev));

    // a document title that is too long ends in an ellipsis instead of running out
    await nav(B + '#docs');
    const long = 'A very long document name that cannot fit on a phone screen of 320 pixels.pdf';
    const dh = await ev(`(() => { const d = document.createElement('div'); d.className = 'lhdr'; d.style.width = '300px'; d.innerHTML = '<button class="iconbtn">x</button><h3 id="dc-h">${long}</h3><span class="spacer"></span><button class="iconbtn">y</button>'; document.body.appendChild(d);
      const h = d.querySelector('h3'), cs = getComputedStyle(h), r = d.getBoundingClientRect(), hr = h.getBoundingClientRect(), last = d.lastElementChild.getBoundingClientRect(); const o = {ell: cs.textOverflow, ws: cs.whiteSpace, inside: last.right <= r.right + 1 && hr.right <= r.right + 1}; d.remove(); return o; })()`);
    check(dh && dh.ell === 'ellipsis' && dh.ws === 'nowrap' && dh.inside, 'document title: ellipsis, buttons stay inside ' + JSON.stringify(dh));
  }, true);

  console.log(`p2459_b_phone320_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
