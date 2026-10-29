// kalmido-suite: fresh
// 2.406.0 A (#3504, #3492) UI tests, own container (start.sh, isolated test database), invented names only:
// #3504 usable minimums: the sidebar at least 14 rem, the list at least 18 rem (288 px); a stored narrower sidebar is lifted
//       on load, Home on the grip = 14 rem, dragging the grip far left stops at 14 rem; a window too narrow for a wide sidebar
//       and an 18 rem list folds the sidebar into the drawer (side-rail) instead of squeezing the list
// #3492 one row rule: a tree row (office menu) and a project folder head have the plain row's font size, a 1 rem symbol at
//       the same left edge; the fold arrow sits at the row's end; a child's symbol stands under its parent's name
// freelancer-matrix: n/a (no route changed; alice has no organisation here = the freelancer case)
// Screenshots with P2406A_SHOTS=<dir>.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2406_a_ui', check, shots: 'P2406A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), _s: r.status}; };
const width = (w, px) => Object.defineProperty(w, 'innerWidth', {configurable: true, value: px});
const key = (w, el, k, o = {}) => el.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true, ...o}));

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const st0 = await call('GET', '/api/state');
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'files', 'docs', 'office', 'clients'])].join(',');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: feats, workspace: 'private'});
  const L = (await call('POST', '/api/lists', {name: 'Website', kind: 'project'})).id;
  const LJ = (await call('POST', '/api/lists', {name: 'Side gig', folder: 'Jobs'})).id;
  check(L && LJ, 'setup: a project and a project in the folder Jobs');
  const Q = await call('POST', '/api/office/docs', {kind: 'offer', project_title: 'Harbour film', items: [{title: 'Edit day', qty: 1, rate: 800}]});
  check(Q._s === 201, 'setup: a quotation in the personal office ' + JSON.stringify(Q).slice(0, 160));

  // ================= jsdom #3504: the numbers, storage and keyboard
  let w = await boot({user: 'alice', hash: 'l/' + L, setup: x => width(x, 1440), ls: {'tasks.pw.side': '12'}}), d = w.document;
  check(w.eval('PW.side[1]') === 14 && w.eval('LIST_FLOOR_PX') === 288, '#3504: minimums 14 rem (sidebar) / 288 px (list) ' + w.eval('JSON.stringify([PW.side, LIST_FLOOR_PX])'));
  check(w.eval(`panelRem('side')`) === 14 && d.documentElement.style.getPropertyValue('--sideW') === '14rem', '#3504: a stored 12 rem sidebar shows 14 rem on load ' + d.documentElement.style.getPropertyValue('--sideW'));
  w.eval('placeGrips()');
  const g = d.querySelector('#pgrip-side');
  check(g && g.getAttribute('aria-valuemin') === '14', '#3504: the grip names 14 rem as its minimum ' + g?.getAttribute('aria-valuemin'));
  key(w, g, 'ArrowRight'); key(w, g, 'Home'); await sleep(50);
  check(+JSON.parse(w.__store['tasks.pw.side'] || '0') === 14, '#3504: Home = the narrowest = 14 rem ' + w.__store['tasks.pw.side']);
  key(w, g, 'ArrowLeft', {shiftKey: true}); await sleep(50);
  check(+JSON.parse(w.__store['tasks.pw.side'] || '0') === 14, '#3504: narrower than 14 rem is not possible ' + w.__store['tasks.pw.side']);
  // a wide sidebar (above the former 26 rem) may squeeze the list only down to 288 px; less room = the drawer
  const lay = o => w.eval(`lay2209(${JSON.stringify({bar: 0, barRail: 0, det: 0, detMin: 320, chat: 0, chatMin: 320, fold: false, floor: 288, ...o})})`);
  check(!lay({W: 1040, side: 720}).rail, '#3504: 720 px sidebar + 320 px list fit side by side');
  check(lay({W: 960, side: 720}).rail, '#3504: 720 px sidebar + 240 px list: the sidebar folds into the drawer (12 rem list no more)');
  w.__store['tasks.pw.side'] = '45'; width(w, 1000); w.eval('fitLayout()');
  check(d.querySelector('#app').classList.contains('side-rail'), '#3504: 1000 px window, 45 rem sidebar: drawer instead of a list under 18 rem');
  width(w, 1600); w.eval('fitLayout()');
  check(!d.querySelector('#app').classList.contains('side-rail'), '#3504: 1600 px window: the 45 rem sidebar is back');
  w.__store['tasks.pw.side'] = '15'; w.eval('panelVars()');
  w.close();

  // ================= jsdom #3492: the tree row's markup
  w = await boot({user: 'alice', hash: 'l/' + L}); d = w.document;
  const html = w.eval(`sbb_treeHtml([{k: 't:p', name: 'Parent', go: 'x', kids: true, open: true, sub: () => [{k: 't:c', name: 'Child', go: 'y', kids: false}]}])`);
  const box = d.createElement('div'); box.innerHTML = html;
  const [pr, cr] = box.querySelectorAll('.sbbt');
  check(pr && pr.lastElementChild?.classList.contains('sbbtar') && pr.firstElementChild?.classList.contains('sbbtn'), '#3492: the fold arrow comes after the name (row end) ' + html.slice(0, 300));
  check(pr?.querySelector('.sbbtar')?.getAttribute('aria-expanded') === 'true' && /Collapse: Parent/.test(pr.querySelector('.sbbtar').getAttribute('aria-label') || ''), '#3492: the arrow stays its own button with aria-expanded');
  check(cr && !cr.querySelector('.sbbtar') && cr.style.getPropertyValue('--sbbl') === '1', '#3492: a leaf has no arrow placeholder, one level deeper');
  check(!pr?.querySelector('.sbbtn svg.i')?.classList.contains('s'), '#3492: the symbol has the plain rows\' size (no small icon class)');
  w.close();

  // ================= Firefox: measured
  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); await sleep(700); };
  const wait = async (ev, js, n = 30) => { for (let i = 0; i < n; i++) { if (await ev(js).catch(() => false)) return true; await sleep(300); } return false; };
  // left / right / width of an element and its font size
  const MEAS = `const r = e => { if (!e) return null; const b = e.getBoundingClientRect(); return {l: Math.round(b.left * 10) / 10, r: Math.round(b.right * 10) / 10, w: Math.round(b.width * 10) / 10, t: Math.round(b.top), fs: getComputedStyle(e).fontSize, mt: getComputedStyle(e).marginTop}; };`;
  await firefox(async ({cmd, ev, nav, ctx, shot, drag}) => {
    check(await ffLogin({ev, nav}) === 200, 'Firefox: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    // ---- #3504: drag the sidebar's grip far left
    await nav(B + '#l/' + L); await ready(ev);
    const g0 = await ev(`(() => { const g = document.querySelector('#pgrip-side'); if (!g || g.hidden) return null; const b = g.getBoundingClientRect(); return {x: Math.round(b.left + b.width / 2), y: Math.round(b.top + 200)}; })()`);
    check(!!g0, 'Firefox: the sidebar grip is there');
    if (g0) {
      await drag(g0.x, g0.y, 20 - g0.x, 0);
      await sleep(700);
      const s = await ev(`(() => { ${MEAS} return {side: r(document.querySelector('#side')), st: localStorage.getItem('tasks.pw.side')}; })()`);
      check(s && Math.abs(s.side.w - 224) <= 1 && +s.st === 14, '#3504: the grip dragged far left stops at 14 rem (224 px) ' + JSON.stringify(s));
    }
    await ev(`(() => { panelSet('side', 999); return 1; })()`); await sleep(600);
    const m = await ev(`(() => { ${MEAS} return r(document.querySelector('#main')); })()`);
    check(m && m.w >= 287, '#3504: a sidebar dragged as wide as possible leaves the list 18 rem ' + JSON.stringify(m));
    await ev(`(() => { panelSet('side', null); return 1; })()`); await sleep(400);

    // ---- #3492: the project folder head vs a plain project row
    await nav(B + '#l/' + L); await ready(ev);
    await shot('p2406a-folders.png');
    const f = await ev(`(() => { ${MEAS} const h = document.querySelector('#side .fhead[data-folder="Jobs"]'), p = document.querySelector('#side .srow[data-list="${L}"]'), c = document.querySelector('#side .fbody .srow[data-list="${LJ}"]');
      if (!h || !p) return null;
      return {hn: r(h.querySelector('.n')), hi: r(h.querySelector('.sic svg') || h.querySelector('.sic')), ha: r(h.querySelector('.fcar')), hm: r(h.querySelector('.fmenu')), pn: r(p.querySelector('.n')), pi: r(p.querySelector('.sic')), ci: c ? r(c.querySelector('.sic')) : null}; })()`);
    check(f && f.hn.fs === f.pn.fs, '#3492: a folder head has the font size of a project row ' + JSON.stringify(f && [f.hn.fs, f.pn.fs]));
    check(f && f.hi.w === 16 && Math.abs(f.hi.l - f.pi.l) <= 1, '#3492: the folder symbol is 1 rem at the project rows\' left edge ' + JSON.stringify(f && [f.hi, f.pi]));
    check(f && f.ha && f.ha.l >= f.hn.r, '#3492: the folder arrow sits after the name ' + JSON.stringify(f && [f.ha, f.hn]));
    check(f && f.hm && f.hm.l >= f.ha.r - 1, '#3492: the folder\'s "…" stays the last thing in the row ' + JSON.stringify(f && [f.ha, f.hm]));
    check(f && f.ci && Math.abs(f.ci.l - f.hn.l) <= 2, '#3492: a project in the folder: its symbol under the folder\'s name ' + JSON.stringify(f && [f.ci, f.hn]));

    // ---- #3492: the office menu: a tree row vs a plain row
    await nav(B + '#office/offers'); await ready(ev);
    check(await wait(ev, `!!document.querySelector('#side .sbbt[data-sbbid="a:offers"]')`), 'Firefox: the office menu shows Quotes & invoices as a tree row');
    await ev(`(() => { const a = document.querySelector('#side [data-act="sbb-tree"][data-k="of:a:offers"]'); if (a && !a.dataset.open) a.click(); return 1; })()`);
    await wait(ev, `!!document.querySelector('#side .sbbt[data-sbbpar="a:offers"]')`);
    await sleep(300);
    await shot('p2406a-office.png');
    const o = await ev(`(() => { ${MEAS} const t = document.querySelector('#side .sbbt[data-sbbid="a:offers"]'), k = document.querySelector('#side .sbbt[data-sbbpar="a:offers"]');
      const p = [...document.querySelectorAll('#side .srow')].find(x => x.offsetParent && x.querySelector(':scope > svg.i') && x.querySelector('.n'));
      if (!t || !p) return null;
      return {tn: r(t.querySelector('.sbbtn .n')), ti: r(t.querySelector('.sbbtn svg.i')), ta: r(t.querySelector('.sbbtar')), tr: r(t), pn: r(p.querySelector('.n')), pi: r(p.querySelector(':scope > svg.i')), ki: k ? r(k.querySelector('.sbbtn svg.i')) : null, kn: k ? r(k.querySelector('.n')) : null}; })()`);
    check(o && o.tn.fs === o.pn.fs, '#3492: office menu: a tree row has the plain row\'s font size ' + JSON.stringify(o && [o.tn.fs, o.pn.fs]));
    check(o && o.ti.w === o.pi.w && Math.abs(o.ti.l - o.pi.l) <= 1 && Math.abs(o.tn.l - o.pn.l) <= 1, '#3492: office menu: same symbol size, same left edge for symbol and name ' + JSON.stringify(o && [o.ti, o.pi, o.tn.l, o.pn.l]));
    check(o && o.ta && o.ta.l >= o.tn.r && o.tr.r - o.ta.r <= 8, '#3492: office menu: the arrow at the row\'s end ' + JSON.stringify(o && [o.ta, o.tn, o.tr]));
    check(o && o.tr.mt === '0px', '#3492: office menu: no extra gap above a tree row ' + JSON.stringify(o && o.tr.mt));
    check(o && o.ki && Math.abs(o.ki.l - o.tn.l) <= 1, '#3492: office menu: the child\'s symbol stands under the parent\'s name ' + JSON.stringify(o && [o.ki, o.tn]));
    // the arrow folds, the row opens
    await ev(`(() => { document.querySelector('#side [data-act="sbb-tree"][data-k="of:a:offers"]').click(); return 1; })()`);
    check(await wait(ev, `!document.querySelector('#side .sbbt[data-sbbpar="a:offers"]') && document.querySelector('#side .sbbt[data-sbbid="a:offers"]').classList.contains('closed')`), '#3492: a click on the arrow folds the row');
  });

  console.log(`p2406_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
