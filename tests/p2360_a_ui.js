// 2.36.0 UI tests (agent A), own container (start.sh). #1117 a calmer sidebar. jsdom:
//   the icon set (about 200 line icons, each with exactly one dot of class d, no two alike), the emoji -> line icon map;
//   the settings side_icons (line | emoji | dot, default line) and side_progress (default on): stored on the server, bad
//   values refused; the sidebar column per mode (line icon with --dot = the list colour, the emoji, a round dot; a list
//   without a matching icon gets the round dot; the emoji never in the name), the progress bar off by the switch and by the
//   per-list "Hide progress"; Settings > Appearance > Sidebar (select + switch save at once); the list dialog suggests a line
//   icon (the emoji stays its accessible name) and its grid offers one button per line icon
// Firefox 1280 (mouse, light + dark): grey icons >= 3:1 against the sidebar, the dot in the list colour, the open list's
//   icon in the text colour, the share icon hidden until hover / focus, the bar 1 px, the folder head smaller and grey;
//   390 touch: the share icon visible, the rows >= 44 px; screenshots
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2360_a_ui', check, shots: 'P2360A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const FEAT = 'collab,progress,comments';
const settings = async () => (await call('GET', '/api/state')).settings;

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Baker', password: 'password123'})).id;
  const CART = (await call('POST', '/api/lists', {name: '🛒 Shopping', color: '#e8590c'})).id;
  await call('PUT', `/api/lists/${CART}/members`, {user_id: BOB, role: 'edit'});
  const RED = (await call('POST', '/api/lists', {name: '🔴 Red things', color: '#1c7ed6'})).id;
  const PLAIN = (await call('POST', '/api/lists', {name: 'Plain', color: '#2f9e44'})).id;
  const PRJ = (await call('POST', '/api/lists', {name: '🚀 Releases', kind: 'project', color: '#7048e8', folder: 'Work'})).id;
  await call('POST', '/api/lists', {name: '🐞 Bugs', folder: 'Work'});
  const T1 = (await call('POST', '/api/tasks', {title: 'Ship it', list_id: PRJ})).id;
  await call('POST', '/api/tasks', {title: 'Write notes', list_id: PRJ});
  await call('POST', `/api/tasks/${T1}/complete`);

  // ================= the settings on the server
  let s = await settings();
  check(s.side_icons === 'line' && s.side_progress === '1', 'defaults: line icons, progress on ' + JSON.stringify([s.side_icons, s.side_progress]));
  check((await call('PATCH', '/api/settings', {side_icons: 'rainbow'})).status === 400 && (await settings()).side_icons === 'line', 'side_icons: a bad value is refused (400), nothing stored');
  check((await call('PATCH', '/api/settings', {side_progress: 'maybe'})).status === 400, 'side_progress: a bad value is refused');
  await call('PATCH', '/api/settings', {side_progress: 'false'});
  check((await settings()).side_progress === '0', 'side_progress: false -> 0');
  await call('PATCH', '/api/settings', {side_progress: '1'});

  // ================= the icon set + the map
  let w = await boot({user: 'alice', hash: 'l/' + CART}), d = w.document;
  await until(() => d.querySelector(`#side .srow[data-list="${CART}"]`));
  const set = w.eval(`(() => { const ks = Object.keys(P), draw = new Set(ks.map(k => P[k])), nw = ks.slice(ks.indexOf('flame'));
    return {n: ks.length, uniq: draw.size, newN: nw.length, oneDot: nw.filter(k => (P[k].match(/class="d"/g) || []).length !== 1),
      missing: Object.keys(SBI_EMO).filter(k => !P[k]), unused: nw.filter(k => ![...SBI_MAP.values()].includes(k))}; })()`);
  check(set.n >= 195 && set.n <= 210, '#1117: about 200 icons ' + set.n);
  check(set.uniq >= set.n - 1, '#1117: no two new icons alike (left = back is old) ' + JSON.stringify([set.n, set.uniq]));
  check(!set.oneDot.length, '#1117: every new icon has exactly one dot of class d ' + set.oneDot);
  check(!set.missing.length && !set.unused.length, '#1117: the map only names existing icons, every new icon is reachable ' + JSON.stringify(set));
  const mp = w.eval(`['🛒', '🛒️', '🏖️', '👨‍👩‍👧', '🧑🏽‍💻', '❤️', '🔴', '🏃‍♀️', 'x'].map(sbiIconFor).join()`);
  check(mp === 'cart,cart,beach,family,laptop,heart,,run,', '#1117: emoji -> line icon (variation selector, skin tone, sequences; none for a coloured circle) ' + mp);

  // ================= the sidebar: line (default)
  const row = id => d.querySelector(`#side .srow[data-list="${id}"]`);
  const col = id => { const x = row(id); return {svg: !!x?.querySelector('.sic.sln svg'), emo: x?.querySelector('.sic.semo')?.textContent || '', rd: !!x?.querySelector('.sic .sw.rd'),
    sq: !!x?.querySelector('.sic .sw:not(.rd)'), dot: x?.querySelector('.sic')?.getAttribute('style') || '', bg: x?.querySelector('.sic .sw')?.getAttribute('style') || '', name: x?.querySelector('.n')?.textContent,
    prog: !!x?.querySelector('.sprog'), shr: !!x?.querySelector('.shr')}; };
  let c = col(CART);
  check(c.svg && /--dot:#e8590c/.test(c.dot) && !c.emo && c.name === 'Shopping', 'line: the cart as a line icon, its dot in the list colour, the name without the emoji ' + JSON.stringify(c));
  check(c.shr, 'line: the shared list keeps its share icon in the markup');
  c = col(RED);
  check(!c.svg && c.rd && /#1c7ed6/.test(c.bg) && c.name === 'Red things', 'line: no matching icon -> a round dot in the list colour ' + JSON.stringify(c));
  c = col(PLAIN);
  check(!c.svg && c.rd && /#2f9e44/.test(c.bg), 'line: no emoji -> a round dot ' + JSON.stringify(c));
  c = col(PRJ);
  check(c.svg && c.prog && c.name === 'Releases', 'line: the project in its folder with a line icon and its progress bar ' + JSON.stringify(c));
  check(!/\p{Extended_Pictographic}/u.test([...d.querySelectorAll('#side .srow[data-list]')].map(x => x.textContent).join('')), 'line: no emoji anywhere in the list rows');
  w.close();

  // ================= emoji + dot (set on the server, so every device follows)
  await call('PATCH', '/api/settings', {side_icons: 'emoji'});
  w = await boot({user: 'alice', hash: 'l/' + CART}); d = w.document;
  await until(() => row(CART));
  c = col(CART);
  check(!c.svg && c.emo === '🛒' && c.name === 'Shopping', 'emoji: the emoji in the column (as before) ' + JSON.stringify(c));
  c = col(PLAIN);
  check(c.sq && !c.rd, 'emoji: a list without an emoji keeps the square dot (as before) ' + JSON.stringify(c));
  w.close();
  await call('PATCH', '/api/settings', {side_icons: 'dot'});
  w = await boot({user: 'alice', hash: 'l/' + CART}); d = w.document;
  await until(() => row(CART));
  c = col(CART);
  check(!c.svg && !c.emo && c.rd && /#e8590c/.test(c.bg) && c.name === 'Shopping', 'dot: only the round dot in the list colour ' + JSON.stringify(c));

  // ================= progress: the switch and the per-list hiding
  await call('PATCH', '/api/settings', {side_progress: '0'});
  w.close();
  w = await boot({user: 'alice', hash: 'l/' + CART}); d = w.document;
  await until(() => row(PRJ));
  check(!col(PRJ).prog, 'progress off: no bar in the sidebar');
  check(!!d.querySelector('#view, #main'), 'progress off: the app still renders');
  w.close();
  await call('PATCH', '/api/settings', {side_progress: '1', hide_progress: String(PRJ)});
  w = await boot({user: 'alice', hash: 'l/' + CART}); d = w.document;
  await until(() => row(PRJ));
  check(!col(PRJ).prog, 'per-list "Hide progress" also hides the sidebar bar');
  await call('PATCH', '/api/settings', {hide_progress: ''});
  w.close();

  // ================= Settings > Appearance > Sidebar
  await call('PATCH', '/api/settings', {side_icons: 'line'});
  w = await boot({user: 'alice', hash: 'l/' + CART}); d = w.document;
  await until(() => row(CART));
  w.eval(`settingsModal('look')`); await sleep(400);
  const sel = d.querySelector('.smodal #s-sideic'), chk = d.querySelector('.smodal #s-sideprog');
  check(sel && sel.value === 'line' && [...sel.options].map(o => o.value).join() === 'line,emoji,dot' && /List icons/.test(d.querySelector('.smodal label[for="s-sideic"]')?.textContent || ''), 'Settings: "List icons" Lines / Emoji / Dot, Lines chosen');
  check(chk && chk.checked && /Progress in the sidebar/.test(chk.closest('label').textContent), 'Settings: "Progress in the sidebar", on');
  sel.value = 'dot'; sel.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(async () => (await settings()).side_icons === 'dot'), 'Settings: choosing Dot saves at once on the server');
  check(await until(() => row(CART)?.querySelector('.sic .sw.rd') && !row(CART)?.querySelector('.sic svg')), 'Settings: the sidebar follows at once');
  chk.click();
  check(await until(async () => (await settings()).side_progress === '0'), 'Settings: the progress switch saves');
  check(await until(() => !row(PRJ)?.querySelector('.sprog')), 'Settings: the bar goes at once');
  [...d.querySelectorAll('.modal')].forEach(m => m.remove());
  w.close();
  await call('PATCH', '/api/settings', {side_icons: 'line', side_progress: '1'});

  // ================= the list dialog
  w = await boot({user: 'alice', hash: 'inbox'}); d = w.document;
  w.eval('listModal()'); await sleep(300);
  let md = [...d.querySelectorAll('.modal')].pop();
  const inp = md.querySelector('#l-name'); inp.value = 'Shopping list'; inp.dispatchEvent(new w.Event('input', {bubbles: true})); await sleep(200);
  const eb = md.querySelector('#l-emo');
  check(eb.classList.contains('sugg') && eb.querySelector('svg.i.l') && eb.textContent.includes('🛒') && eb.querySelector('.sr'), 'list dialog: "Shopping list" suggests the cart as a line icon (the emoji stays its name)');
  const grid = [...md.querySelectorAll('#l-emogrid [data-emo]:not(.none)')];
  const gk = grid.map(b => w.eval(`sbiIconFor(${JSON.stringify(b.dataset.emo)})`));
  check(grid.length >= 120 && grid.every(b => b.querySelector('svg.i.l')) && new Set(gk).size === gk.length, 'list dialog: the grid offers one button per line icon ' + JSON.stringify([grid.length, new Set(gk).size]));
  md.querySelector('#l-emogrid [data-emo="🚀"]').click(); await sleep(100);
  inp.value = 'Launch'; inp.dispatchEvent(new w.Event('input', {bubbles: true}));
  md.querySelector('[data-m="save"]').click();
  check(await until(async () => (await call('GET', '/api/state')).lists.some(l => l.name === '🚀Launch' || l.name === '🚀 Launch')), 'list dialog: a picked line icon saves its emoji in the name');
  md.remove(); w.close();

  // ================= Firefox
  const ffLogin = async ({ev, nav}, theme = 'light') => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"${theme}"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  // contrast of an element's colour against the sidebar background (WCAG relative luminance)
  const MEASURE = `(async () => {
    const rgb = s => (s.match(/[\\d.]+/g) || []).slice(0, 3).map(Number), lum = c => { const v = c.map(x => { x /= 255; return x <= .03928 ? x / 12.92 : ((x + .055) / 1.055) ** 2.4; }); return .2126 * v[0] + .7152 * v[1] + .0722 * v[2]; };
    const cr = (a, b) => { const x = lum(rgb(a)), y = lum(rgb(b)); return (Math.max(x, y) + .05) / (Math.min(x, y) + .05); };
    const side = getComputedStyle(document.querySelector('#side')).backgroundColor, R = id => document.querySelector('#side .srow[data-list="' + id + '"]');
    const cart = R(${CART}), prj = R(${PRJ}), svg = prj.querySelector('.sic svg'), on = cart.querySelector('.sic svg');
    const fh = [...document.querySelectorAll('#side .fhead')].find(x => /Work/.test(x.textContent)), rowFs = parseFloat(getComputedStyle(prj.querySelector('.n')).fontSize);
    const shr = cart.querySelector('.shr:not(.bellm)'), op0 = +getComputedStyle(shr).opacity, cr0 = cart.getBoundingClientRect(); window.__hov = {x: Math.round(cr0.left + cr0.width / 2), y: Math.round(cr0.top + cr0.height / 2)};
    return {grey: +cr(getComputedStyle(svg).color, side).toFixed(2), dot: getComputedStyle(prj.querySelector('.sic svg .d')).fill, active: getComputedStyle(on).color, text: getComputedStyle(document.body).color,
      onRow: cart.classList.contains('on'), bar: prj.querySelector('.sprog')?.getBoundingClientRect().height, fhFs: parseFloat(getComputedStyle(fh.querySelector('.n')).fontSize), rowFs,
      fhGrey: +cr(getComputedStyle(fh.querySelector('.n')).color, side).toFixed(2), fhText: getComputedStyle(fh.querySelector('.n')).color, op0, hov: window.__hov,
      minH: Math.min(...[...document.querySelectorAll('#side .srow[data-list]')].map(x => x.getBoundingClientRect().height))};
  })()`;
  for (const theme of ['light', 'dark']) {
    await firefox(async o => {
      const {cmd, ev, ctx, shot} = o, tag = '1280 ' + theme;
      check(await ffLogin(o, theme) === 200, tag + ': login');
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 800}});
      await o.nav(B + '#l/' + CART); await ready(ev);
      const m = await ev(MEASURE);
      check(m.grey >= 3, `${tag}: grey line icon >= 3:1 against the sidebar (WCAG 1.4.11) ` + JSON.stringify(m));
      check(m.dot === 'rgb(112, 72, 232)', `${tag}: the icon's dot in the list colour ` + m.dot);
      check(m.onRow && m.active === m.text, `${tag}: the open list's icon in the text colour ` + JSON.stringify([m.active, m.text]));
      check(m.bar > 0 && m.bar <= 1.01, `${tag}: the progress bar is 1 px ` + m.bar);
      check(m.fhFs < m.rowFs && m.fhGrey >= 4.5 && m.fhText !== m.text, `${tag}: the folder head is smaller and grey (still >= 4.5:1) ` + JSON.stringify([m.fhFs, m.rowFs, m.fhGrey]));
      // a real mouse over the row (WebDriver BiDi pointer), then the keyboard: Tab focus inside the sidebar
      await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'm', parameters: {pointerType: 'mouse'}, actions: [{type: 'pointerMove', x: m.hov.x, y: m.hov.y, duration: 0}]}]}); await sleep(400);
      const op1 = await ev(`+getComputedStyle(document.querySelector('#side .srow[data-list="${CART}"] .shr:not(.bellm)')).opacity`);
      await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'm', parameters: {pointerType: 'mouse'}, actions: [{type: 'pointerMove', x: 900, y: 600, duration: 0}]}]}); await sleep(400);
      const op2 = await ev(`+getComputedStyle(document.querySelector('#side .srow[data-list="${CART}"] .shr:not(.bellm)')).opacity`);
      check(m.op0 >= 0.99 && op1 >= 0.99 && op2 >= 0.99, `${tag}: the share icon is always shown (2.36.2, #1139) ` + JSON.stringify([m.op0, op1, op2]));
      const kf = await ev(`(async () => { const r = document.querySelector('#side .srow[data-list="${CART}"]'); r.focus(); await new Promise(x => setTimeout(x, 400)); const on = document.activeElement === r && r.matches(':focus'), op = +getComputedStyle(r.querySelector('.shr:not(.bellm)')).opacity; r.blur(); return {on, op}; })()`);
      if (kf.on) check(kf.op > 0.5, `${tag}: keyboard focus on the row shows its share icon ` + JSON.stringify(kf));
      else console.log(`${tag}: keyboard focus check skipped (the headless window is not active, :focus does not match)`);
      if (theme === 'light') await shot('p2360a-1280-sidebar.png');
    }, false);
  }
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '390';
    check(await ffLogin(o) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + '#l/' + CART); await ready(ev);
    await ev(`(() => { document.querySelector('[data-act="side"]')?.click(); return 1; })()`); await sleep(700);
    const m = await ev(`(() => { const cart = document.querySelector('#side .srow[data-list="${CART}"]'), shr = cart.querySelector('.shr:not(.bellm)');
      return {op: +getComputedStyle(shr).opacity, minH: Math.min(...[...document.querySelectorAll('#side .srow[data-list]')].map(x => x.getBoundingClientRect().height)), svg: !!cart.querySelector('.sic.sln svg'),
        fits: document.querySelector('#side').scrollWidth <= document.querySelector('#side').clientWidth + 1}; })()`);
    check(m.op > 0.5, `${tag}: touch: the share icon stays visible ` + m.op);
    check(m.minH >= 44 && m.svg && m.fits, `${tag}: rows >= 44 px, line icons, nothing sideways ` + JSON.stringify(m));
    await shot('p2360a-390-sidebar.png'); console.log(`${tag}: sidebar shot taken (${process.env.P2360A_SHOTS ? 'dir set' : 'no dir'})`);
  }, true);
  console.log(`p2360_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
