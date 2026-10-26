// 2.350.0 D (#2750, #2745, #3242) UI tests, own container (start.sh, isolated test database):
// #2750 chat and sidebar can be dragged as wide as wanted (no 44 / 26 rem maximum, no 40 % cap); only the list keeps 12 rem;
//       double click on the grip = standard width; the stored width stays when the window gets smaller
// #2745 the sticky head of the project dialog never covers the first row (computer + phone width)
// #3242 an undo message ends at a page change also when the hash is empty
// freelancer-matrix: Breiten (alice has no organisation here)
// Screenshots with P2350D_SHOTS=<dir>.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2350_d_breiten_ui', check, shots: 'P2350D_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), _s: r.status}; };
const width = (w, px) => Object.defineProperty(w, 'innerWidth', {configurable: true, value: px});

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['agents', 'comments']});
  await call('PATCH', '/api/settings', {features: 'agents,comments', lang: 'en', tour: 'done'});
  const ag = await call('POST', '/api/admin/agents', {scopes: ['write'], username: 'claude', display_name: 'Claude'});
  const AG = ag.id;
  const L = (await call('POST', '/api/lists', {name: 'Website', kind: 'project'})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: AG, role: 'edit'});

  // ================= jsdom: the numbers (#2750)
  let w = await boot({user: 'alice', hash: 'l/' + L, setup: x => width(x, 1440), ls: {'tasks.pw.chat': '60', 'tasks.pw.side': '15'}}), d = w.document;
  check(w.eval(`panelRem('chat')`) === 60 && (w.__store['tasks.pw.side'] = '30', w.eval(`panelRem('side')`)) === 30 && (w.__store['tasks.pw.side'] = '15'), '#2750: stored widths above the former maximums (44 / 26 rem) are kept');
  const lay = o => w.eval(`lay2209(${JSON.stringify({bar: 72, barRail: 72, side: 240, det: 0, detMin: 320, chat: 0, chatMin: 320, fold: false, ...o})})`);
  let r = lay({W: 1440, chat: 960, floor: 192});
  check(!r.rail && !r.yieldC && r.chat > 900 && 1440 - 312 - r.chat >= 191.5, '#2750: a 60 rem chat in 1440 px leaves the list at least 12 rem ' + JSON.stringify(r));
  r = lay({W: 1440, chat: 960});
  check(r.chat < 900, '#2750: without the 12 rem floor the old 320 px list limit still squeezes (other windows unchanged) ' + JSON.stringify(r));
  w.eval(`chatOpen(${AG})`); await sleep(400);
  check(w.eval(`panelMax('chat')`) > 44 && w.eval(`panelMax('chat')`) <= (1440 - 312 - 192) / 16 + 0.01, '#2750: the chat grip reaches past 44 rem, the list keeps 12 rem ' + w.eval(`panelMax('chat')`));
  const cw = parseFloat(d.documentElement.style.getPropertyValue('--chatW'));
  check(cw > 44 && cw <= (1440 - 312 - 192) / 16 + 0.01, '#2750: the width in use is not cut at 44 rem / 40 % ' + cw);
  check(w.__store['tasks.pw.chat'] === '60', '#2750: the stored chat width stays ' + w.__store['tasks.pw.chat']);
  width(w, 1920); w.eval('fitLayout()');
  check(d.documentElement.style.getPropertyValue('--chatW') === '60rem', '#2750: on a wide window the stored 60 rem come back');
  w.close();

  // ================= jsdom: an undo message ends at a page change, also with an empty hash (#3242)
  w = await boot({user: 'alice'}); d = w.document;
  w.eval(`history.replaceState(null, '', location.pathname + location.search)`); w.eval(`toastPage()`);
  w.eval(`toast('Done', () => {})`);
  const el = d.querySelector('#toast');
  check(!el.classList.contains('hidden'), '#3242: the message is shown');
  w.eval(`location.hash = '#l/${L}'`);
  for (let i = 0; i < 20 && !el.classList.contains('hidden'); i++) await sleep(100);
  check(el.classList.contains('hidden'), '#3242: empty hash -> page change closes the undo message');
  w.close();

  // ================= Firefox: dragging wide, double click, the dialog head
  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); await sleep(700); };
  const BOX = s => `(() => { const e = document.querySelector(${JSON.stringify(s)}); if (!e) return null; const b = e.getBoundingClientRect(); return {t: Math.round(b.top), b: Math.round(b.bottom), l: Math.round(b.left), r: Math.round(b.right), w: Math.round(b.width)}; })()`;
  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    check(await ffLogin({ev, nav}) === 200, 'Firefox: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await nav(B + '#l/' + L); await ready(ev);
    await ev(`(() => { chatOpen(${AG}); return 1; })()`); await sleep(1200);
    await ev(`(() => { panelSet('chat', 999); return 1; })()`); await sleep(600);
    const c = await ev(BOX('#achat')), m = await ev(BOX('#main')), over = await ev(`document.documentElement.scrollWidth - innerWidth`);
    check(c && c.w > 704 && m && m.w >= 190 && over <= 0, '1440: the chat is wider than 44 rem, the list keeps >= 12 rem, no sideways scroll ' + JSON.stringify([c, m, over]));
    check(+await ev(`localStorage.getItem('tasks.pw.chat')`) > 44, '1440: the wide width is stored');
    await shot('p2350d-chat-wide.png');
    await ev(`(() => { document.querySelector('#pgrip-chat').dispatchEvent(new MouseEvent('dblclick', {bubbles: true})); return 1; })()`); await sleep(500);
    const c2 = await ev(BOX('#achat'));
    check(c2 && c2.w === 416 && !(await ev(`localStorage.getItem('tasks.pw.chat')`)), '1440: double click on the grip = standard width (26 rem), nothing stored ' + JSON.stringify(c2));
    await ev(`(() => { panelSet('side', 999); return 1; })()`); await sleep(600);
    const s = await ev(BOX('#side')), m2 = await ev(BOX('#main'));
    check(s && s.w > 416 && m2 && m2.w >= 190, '1440: the sidebar is wider than 26 rem, the list keeps >= 12 rem ' + JSON.stringify([s, m2]));
    await ev(`(() => { localStorage.removeItem('tasks.pw.side'); return 1; })()`);
    // #2745: the head of the project dialog sits above the first row, never over it
    for (const [vw, tag] of [[1280, 'computer'], [390, 'phone']]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: 800}}); await sleep(500);
      await nav(B + '#l/' + L); await ready(ev);
      await ev(`(() => { listModal(${L}); return 1; })()`); await sleep(900);
      const h = await ev(BOX('.lmodal .card>.lhdr')), n = await ev(BOX('.lmodal #l-name')), card = await ev(BOX('.lmodal .card'));
      check(h && n && h.b <= n.t && n.t - h.b <= 40 && card && h.t >= card.t - 1, `${tag}: head and name field do not overlap (head bottom <= field top) ` + JSON.stringify([h, n]));
      await shot(`p2350d-listdlg-${tag}.png`);
      await ev(`(() => { document.querySelector('.lmodal .card').scrollTop = 120; return 1; })()`); await sleep(300);
      const h2 = await ev(BOX('.lmodal .card>.lhdr')), card2 = await ev(BOX('.lmodal .card'));
      check(h2 && card2 && Math.abs(h2.t - card2.t) <= 1, `${tag}: scrolled, the head stays on top ` + JSON.stringify([h2, card2]));
      await ev(`(() => { document.querySelector('.lmodal [data-m="close"]').click(); return 1; })()`); await sleep(400);
    }
  });

  console.log(`p2350_d_breiten_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
