// 2.655.0 A (#5080 #5082 #5083 #5084) UI test, own container (start.sh). Firefox as a tablet (touch, 840 x 1180), then with a mouse.
// kalmido-suite: fresh
// - #5080 swiping the open task sideways opens the next / previous one also over 767 px (drawer); with a mouse nothing swipes
// - #5082 a wiki page opens read-first with the pen on a touch tablet (the pen opens the editor); with a mouse it opens for writing
// - #5083 the menu editor carries navtouch on touch, the column arrow of a list head is visible without hover (hover:none)
// - #5084 touch: no shortcut button / text in Settings > Help, no shortcut chips in menus, the back tooltip without the keys;
//   with a mouse all of it as before
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2655_a', check, shots: 'P2655A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const FEAT = 'cal,comments,collab,time,progress,wiki';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, time_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  const L = (await call('POST', '/api/lists', {name: 'Swipe list', org_id: ORG})).id;
  for (let i = 1; i <= 6; i++) await call('POST', '/api/tasks', {title: `Task ${i}`, list_id: L, content: 'Some text'});
  const PG = (await call('POST', '/api/wiki/pages', {space: 'private', path: 'Guide', body: '# Start\n\nRead this first.'})).id;

  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  const until = async (ev, js, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(js).catch(() => false)) return true; await sleep(200); } return false; };

  // one pass: tablet = touch screen with 840 px, else a mouse on a desktop
  const pass = tablet => async o => {
    const {cmd, ev, ctx, nav} = o, tag = tablet ? 'tablet' : 'mouse';
    await cmd('browsingContext.setViewport', {context: ctx, viewport: tablet ? {width: 840, height: 1180} : {width: 1280, height: 900}});
    check(await ffLogin(o) === 200, tag + ': login');
    const touch = acts => cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'f' + Math.random(), parameters: {pointerType: 'touch'}, actions: acts}]}).then(() => cmd('input.releaseActions', {context: ctx}));
    const swipe = (x1, x2, y) => touch([{type: 'pointerMove', x: x1, y}, {type: 'pointerDown', button: 0}, {type: 'pointerMove', x: Math.round((x1 + x2) / 2), y, duration: 120}, {type: 'pointerMove', x: x2, y, duration: 120}, {type: 'pointerUp', button: 0}]);

    // ================= #5080 swipe
    await nav(B + '#l/' + L); await ready(ev);
    const order = JSON.parse(await ev(`JSON.stringify([...document.querySelectorAll('#view .trow')].map(r => +r.dataset.id))`));
    check(order.length >= 5, tag + ': the list rows ' + order.length);
    await ev(`(() => { openDetail(${order[4]}); return 1; })()`); await sleep(1000);
    const g = JSON.parse(await ev(`(() => { const r = document.querySelector('#d-title').getBoundingClientRect(), d = document.querySelector('#detail').getBoundingClientRect(); return JSON.stringify({y: Math.round(r.top + r.height / 2), x1: Math.round(d.left + d.width * .8), x2: Math.round(d.left + d.width * .25)}); })()`));
    await swipe(g.x1, g.x2, g.y); await sleep(1000);
    const want = tablet ? order[5] : order[4];  // a swipe to the left = the next task (order index 5)
    check(await ev('S.sel') === want, `${tag}: a swipe to the left ${tablet ? 'opens the next task' : 'does nothing with a mouse'} (${await ev('S.sel')})`);
    if (tablet) {
      await swipe(g.x2, g.x1, g.y); await sleep(1000);
      check(await ev('S.sel') === order[4], tag + ': a swipe to the right goes back (5)');
      await swipe(g.x2, g.x1, g.y); await sleep(1000);
      check(await ev('S.sel') === order[3], tag + ': and once more to 4 (' + await ev('S.sel') + ')');
    }
    await ev(`(() => { closeDetail(); return 1; })()`); await sleep(500);

    // ================= #5082 wiki
    await nav(B + '#wiki/' + PG); await ready(ev); await sleep(900);
    await until(ev, `!!document.querySelector('#wk-cm, #wk-body, [data-wk="pen"]')`);
    const wk = JSON.parse(await ev(`JSON.stringify({pen: !!document.querySelector('[data-wk="pen"]'), ed: !!document.querySelector('#wk-cm, #wk-body'), md: !!document.querySelector('#wk-md')})`));
    if (tablet) {
      check(wk.pen && !wk.ed && wk.md, tag + ': the page is read first, with the pen ' + JSON.stringify(wk));
      await ev(`(() => { document.querySelector('[data-wk="pen"]').click(); return 1; })()`);
      check(await until(ev, `!!document.querySelector('#wk-cm, #wk-body')`), tag + ': the pen opens the editor');
    } else check(!wk.pen && wk.ed, tag + ': a mouse opens the page for writing, no pen ' + JSON.stringify(wk));

    // ================= #5083 menu editor, column arrow
    await nav(B + '#l/' + L); await ready(ev);
    const nt = await ev(`loadModule('navmenu').then(() => nav_edHtml('life').includes('navtouch'))`);
    check(nt === tablet, `${tag}: the menu editor ${tablet ? 'has' : 'has no'} navtouch (${nt})`);
    const arrow = await ev(`(() => { const h = document.createElement('div'); h.className = 'lchead'; h.innerHTML = '<div class="lc"><button class="lcmb" type="button"></button></div>'; document.body.appendChild(h); const d = getComputedStyle(h.querySelector('.lcmb')).display; h.remove(); return d; })()`);
    check(tablet ? arrow !== 'none' : arrow === 'none', `${tag}: the column arrow ${tablet ? 'is visible without hover' : 'waits for the hover'} (${arrow})`);
    // the sidebar point: the long press opens the menu (a mouse has the right click)
    const sp = await ev(`(() => { const b = document.querySelector('#side [data-navk]'); if (!b || !b.offsetParent) return null; const r = b.getBoundingClientRect(); return {x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2)}; })()`);
    if (tablet) {
      if (!sp) await ev(`(() => { document.querySelector('[data-act="side"], #menubtn, .menubtn')?.click(); return 1; })()`).catch(() => {});
      const sp2 = sp || await ev(`(() => { const b = document.querySelector('#side [data-navk]'); if (!b || !b.offsetParent) return null; const r = b.getBoundingClientRect(); return {x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2)}; })()`);
      check(!!sp2, tag + ': a sidebar point is on screen');
      if (sp2) {
        await touch([{type: 'pointerMove', x: sp2.x, y: sp2.y}, {type: 'pointerDown', button: 0}, {type: 'pause', duration: 800}, {type: 'pointerUp', button: 0}]);
        check(await until(ev, `[...document.querySelectorAll('#pop [role="menuitem"]')].some(b => /Hide from menu/.test(b.textContent))`), tag + ': the long press on a sidebar point opens "Hide from menu"');
      }
      await ev(`(() => { closePop?.(); return 1; })()`).catch(() => {});
    }

    // ================= #5084 keyboard hints
    await ev(`(() => { settingsModal('help'); return 1; })()`);
    await until(ev, `!!document.querySelector('.smodal [data-m="tour"]')`);
    const kh = JSON.parse(await ev(`JSON.stringify({btn: !!document.querySelector('.smodal [data-m="keys"]'), txt: [...document.querySelectorAll('.smodal .shelp')].some(e => /j \\/ k move/.test(e.textContent))})`));
    check(tablet ? !kh.btn && !kh.txt : kh.btn && kh.txt, `${tag}: Help ${tablet ? 'without' : 'with'} the shortcut button and text ${JSON.stringify(kh)}`);
    await ev(`(() => { document.querySelector('.smodal [data-m="close"], .smodal .sclose')?.click(); document.querySelector('.modal-bg, .smodal')?.remove(); return 1; })()`);
    await ev(`(() => { menu(document.body, [{label: 'Probe', icon: 'edit', keys: 'Mod+K', fn() {}}]); return 1; })()`); await sleep(300);
    const chips = await ev(`document.querySelectorAll('#pop [role="menuitem"] .kbs').length`);
    check(tablet ? chips === 0 : chips === 1, `${tag}: menu rows ${tablet ? 'without' : 'with'} shortcut chips (${chips})`);
    const tip = await ev(`bnTip()`);
    check(tablet ? tip === 'Back' : /Back \(.+\)/.test(tip), `${tag}: the back tooltip (${tip})`);
  };
  await firefox(pass(true), true);
  await firefox(pass(false), false);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
