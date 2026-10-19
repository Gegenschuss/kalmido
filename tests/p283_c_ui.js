// 2.83.0 part C UI test (#1427), own container (start.sh): jsdom for the behaviour, Firefox for the real look.
// - a list's header strip (dots / grid / picture) sits between the header and the view, decorative (aria-hidden); the list
//   dialog sets it (owner), one undo step; a reader gets no row; "Show header pictures" off (this device) hides it
// - a folder's strip (sidebar folder menu, per owner) in the folder view
// - progress rings in the sidebar (done / all of the state's numbers), switchable per device
// - ticking off: the circle gets the pop (transform / opacity only, none with reduced motion)
// - empty list / empty Today: the K line drawing (no heron), its dot in the accent (2.136.0, #2193: now the bot figure)
// - Firefox: Paper and Night with a header strip (desktop + phone); screenshots with P283C_SHOTS=<dir>
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, errs, sleep, B, login, allCss} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p283_c_ui', check, shots: 'P283C_SHOTS'});
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return Array.isArray(j) ? j : {...j, status: r.status}; };
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==', 'base64');
const FEAT = 'collab,comments,progress';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'})).id;
  const CB = await login('bob'); await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, CB);
  const L = (await call('POST', '/api/lists', {name: 'Garden'})).id, E = (await call('POST', '/api/lists', {name: 'Empty one'})).id;
  const PIC = (await call('POST', '/api/lists', {name: 'Holiday'})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: BOB, role: 'view'});
  const T1 = (await call('POST', '/api/tasks', {title: 'Cut the hedge', list_id: L})).id;
  const T2 = (await call('POST', '/api/tasks', {title: 'Water the roses', list_id: L})).id;
  await call('POST', `/api/tasks/${T2}/complete`, {});
  await call('PUT', `/api/lists/${L}/header`, {style: 'dots'});
  const fd = new FormData(); fd.append('file', new Blob([PNG], {type: 'image/png'}), 'h.png');
  const up = await fetch(B + `api/lists/${PIC}/header`, {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
  check(up.ok, 'setup: picture uploaded ' + up.status);
  await call('PATCH', `/api/lists/${E}`, {folder: 'Home'});
  await call('PATCH', '/api/settings', {folders: JSON.stringify(['Home'])});
  await call('PUT', '/api/folder-heads', {folder: 'Home', style: 'lines'});

  // ---- static: the animation only moves transform / opacity and stops with reduced motion
  const css = await allCss();
  const kf = (css.match(/@keyframes o3c-pop\{([\s\S]*?)\}\}/) || [])[1] || '';
  check(kf && [...kf.matchAll(/([a-z-]+):/g)].every(m => m[1] === 'transform' || m[1] === 'opacity'), 'tick animation: only transform / opacity ' + kf);
  check(/\.chk\.o3c-pop\{animation:o3c-pop \.35s/.test(css) && /@media \(prefers-reduced-motion: reduce\)\{ \.chk\.o3c-pop\{animation:none\} \}/.test(css), 'tick animation: 350 ms, none with reduced motion');  // 2.98.0 D (#2163): was 200 ms

  // ---- the list: strip, ring, dialog, undo
  let w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  let hd = d.querySelector('#main > #o3c-head');
  check(hd && hd.classList.contains('o3c-h-dots') && hd.getAttribute('aria-hidden') === 'true' && hd.nextElementSibling?.id === 'view' && hd.previousElementSibling?.id === 'top', 'list: the dots strip between header and view, decorative');
  const ring = d.querySelector(`#side [data-list="${L}"] .o3c-ring`);
  check(ring && /--p:\s*50/.test(ring.getAttribute('style')) && /1 of 2 done/.test(ring.getAttribute('aria-label')), 'sidebar: progress ring 1 of 2 (50 %) ' + JSON.stringify({ring: ring?.outerHTML, prog: w.eval(`JSON.stringify(listById(${L}).progress)`)}));
  check(!d.querySelector(`#side [data-list="${E}"] .o3c-ring`), 'an empty list has no ring');
  w.eval(`listModal(${L})`); await sleep(300);
  let md = d.querySelector('.modal.lmodal');
  const row = md?.querySelector('#l-o3c');
  check(row && row.querySelectorAll('[data-o3ch]').length === 5 && row.querySelector('[data-o3ch="dots"]').getAttribute('aria-pressed') === 'true' && row.querySelector('[data-o3cup]'), 'list dialog: none / gradient / dots / lines / grid + picture, current one pressed');
  click(w, row.querySelector('[data-o3ch="grid"]')); await sleep(500);
  check(d.querySelector('#o3c-head.o3c-h-grid') && w.eval(`listById(${L}).header_style`) === 'grid', 'dialog: grid applied at once');
  check((await call('GET', '/api/state')).lists.find(l => l.id === L).header_style === 'grid', 'dialog: grid saved for the list');
  check(md.querySelector('#l-o3c [data-o3ch="grid"]')?.classList.contains('on'), 'dialog: the row shows the new choice');
  md.remove();
  await w.eval(`histStep('undo')`); await sleep(500);
  check((await call('GET', '/api/state')).lists.find(l => l.id === L).header_style === 'dots' && d.querySelector('#o3c-head.o3c-h-dots'), 'undo: one step back to dots');
  // ticking off: the pop on the circle
  const chk = d.querySelector(`#view .trow[data-id="${T1}"] .chk`);
  click(w, chk);
  check(chk.classList.contains('o3c-pop') || d.querySelector(`#view .trow[data-id="${T1}"] .chk.o3c-pop`), 'ticking off: the circle pops');
  await sleep(400);
  // the picture strip
  w.eval(`go('l/${PIC}')`); await sleep(400);
  hd = d.querySelector('#o3c-head');
  check(hd && hd.classList.contains('o3c-h-image') && new RegExp(`/api/list-header/${PIC}/[A-Za-z0-9_-]+\\.jpg`).test(hd.style.backgroundImage), 'picture strip: the list picture as background ' + hd?.style.backgroundImage);
  // the folder view
  w.eval(`go('folder/Home')`); await sleep(600);
  check(d.querySelector('#o3c-head.o3c-h-lines'), 'folder view: the folder strip (lines)');
  // empty pages: 2.136.0 (#2193): the calm bot figure instead of the K, no heron
  w.eval(`go('l/${E}')`); await sleep(400);
  const em = d.querySelector('#view .empty.o3c-empty');
  check(em && em.querySelector('svg.bot.b-ruhig[aria-hidden="true"] .b-ant') && !d.querySelector('#view svg.heron, #view svg.o3c-k') && /No tasks/.test(em.textContent), 'empty list: the bot figure + hint, no heron, no K');
  // this device: no header pictures, no rings
  w.eval(`go('l/${L}')`); await sleep(300);
  w.eval(`settingsModal('look')`); await sleep(400);
  md = d.querySelector('.modal.smodal');
  const pane = md.querySelector('[data-pane="look"]');
  check(pane.querySelector('#s-pack') && pane.querySelector('#s-o3c-head')?.checked && !pane.querySelector('#s-o3c-rings'), 'Appearance: themes, header pictures (on); the rings switch moved to the account (2.118.0, #2297)');
  const sw = async (id, on) => { const c = pane.querySelector('#' + id); c.checked = on; c.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(200); };
  await sw('s-o3c-head', false);
  check(!d.querySelector('#o3c-head') && w.__store['tasks.headShow'] === 'false', 'header pictures off: no strip on this device, stored');
  // 2.118.0 (#2297): rings follow the account setting side_progress (see p2118_b_ui)
  await sw('s-o3c-head', true);
  check(d.querySelector('#o3c-head') && d.querySelector('#side .o3c-ring') && !('tasks.headShow' in w.__store), 'header pictures on again (nothing stored)');
  md.remove();
  w.close();
  // a reader: the strip yes, the dialog row no
  w = await boot({user: 'bob', hash: 'l/' + L}); d = w.document;
  check(d.querySelector('#o3c-head.o3c-h-dots'), 'a reader sees the strip of the list');
  w.eval(`listModal(${L})`); await sleep(300);
  check(!d.querySelector('#l-o3c'), 'a reader gets no header row in the list dialog');
  w.close();
  // Today without tasks: the K
  await call('POST', '/api/users', {username: 'dora', display_name: 'Dora', password: 'password123'});
  const CD = await login('dora'); await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, CD);
  w = await boot({user: 'dora', hash: 'today'}); d = w.document;
  check(/Nothing left for today/.test(d.querySelector('#view .o3c-empty')?.textContent || '') && d.querySelector('#view .o3c-empty svg.bot'), 'Today without tasks: the K');
  w.close();

  // ---- Firefox: Paper (desktop) and Night (phone) with a strip
  const ffLogin = async ({ev, nav}, pack, theme) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.pack', '"${pack}"'); localStorage.setItem('tasks.theme', '"${theme}"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  await call('PUT', `/api/lists/${L}/header`, {style: 'gradient'});
  const look = async (o, vw, vh, pack, theme) => {
    const {cmd, ev, nav, shot} = o, tag = `${vw} ${pack}`;
    await cmd('browsingContext.setViewport', {context: o.ctx, viewport: {width: vw, height: vh}});
    check(await ffLogin(o, pack, theme) === 200, tag + ': login');
    await nav(B + '#l/' + L);
    for (let i = 0; i < 40 && !(await ev(`!!document.querySelector('#o3c-head')`).catch(() => false)); i++) await sleep(250);
    await sleep(600);
    const x = await ev(`(() => { const h = document.querySelector('#o3c-head'), v = document.querySelector('#view'), t = document.querySelector('#top'); if (!h) return null;
      const r = h.getBoundingClientRect(), bg = getComputedStyle(document.documentElement).getPropertyValue('--bg').trim();
      return {h: Math.round(r.height), top: Math.round(r.top), topB: Math.round(t.getBoundingClientRect().bottom), viewT: Math.round(v.getBoundingClientRect().top), left: r.left, right: r.right, vw: innerWidth, bg, img: getComputedStyle(h).backgroundImage.slice(0, 30)}; })()`);
    check(x && x.top >= x.topB - 1 && x.viewT >= x.top + x.h - 1 && x.left >= 0 && x.right <= x.vw, `${tag}: the strip below the header, above the list, inside the screen ` + JSON.stringify(x));
    check(x && (vw < 900 ? x.h >= 48 && x.h <= 64 : x.h >= 80 && x.h <= 96) && /gradient/.test(x.img), `${tag}: low on a phone, higher on a desktop, a gradient ` + JSON.stringify(x));
    check(x && x.bg === (pack === 'paper' ? '#fbf8f2' : '#0b1020'), `${tag}: the theme's background ` + x?.bg);
    await shot(`p283c-${vw}-${pack}.png`);
  };
  await firefox(async o => { await look(o, 1280, 800, 'paper', 'light'); }, false);
  await firefox(async o => { await look(o, 390, 844, 'night', 'dark'); }, true);

  check(errs.length === 0, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
