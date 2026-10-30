// kalmido-suite: fresh
// 2.380.2 UI tests in Firefox (real layout): own container (start.sh). Invented project only.
// - #3399 the project page's description fills a taller widget (edit field and read view) and the field grows with its
//   text: no inner scroll bar while the widget has room
// freelancer-matrix: n/a (no route; the project page is drawn in the client only, tested as alice without an organisation)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p23802_ff_ui', check, shots: 'P23802_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', lang: 'en'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const P = (await call(CA, 'POST', '/api/lists', {name: 'Studio move', kind: 'project'})).id;
  check(!!P, 'project created');
  check((await call(CA, 'PATCH', `/api/lists/${P}/overview`, {description: 'Goal: move the studio.'})).http === 200, 'description saved');
  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = ev => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  // the description widget taller than its content (as a taller widget in the view builder): its block gets a fixed height
  const tall = `(() => { const s = document.querySelector('#pov-desc'); s.style.height = '36rem'; return 1; })()`;
  const geo = `(() => { const s = document.querySelector('#pov-desc'), t = document.querySelector('#pov-desc-in'), m = document.querySelector('#pov-desc .povmd'), bar = document.querySelector('#pov-desc .povbar');
    const h = e => e ? Math.round(e.getBoundingClientRect().height) : 0, b = e => e ? Math.round(e.getBoundingClientRect().bottom) : 0;
    return {sec: h(s), secB: b(s), ta: h(t), taScroll: t ? t.scrollHeight - t.clientHeight : -1, md: h(m), barB: b(bar), mdB: b(m)}; })()`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 1000}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev);
    await nav(B + '#l/' + P);
    check(await ready(ev, `typeof setListView === 'function' && !!routeList()`, 80), 'project open');
    await ev(`(() => { setListView(routeList(), 'overview'); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('#view [data-pov="desc-edit"]')`, 80), 'project page with the description');
    // the read view first
    check(await ready(ev, `!!document.querySelector('#pov-desc .povmd')`), 'the read view');
    await ev(tall); await sleep(100);
    const g0 = await ev(geo);
    check(g0.md > g0.sec * 0.7, '#3399: the read view fills the taller widget ' + JSON.stringify(g0));
    await ev(`(() => { document.querySelector('#view [data-pov="desc-edit"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('#pov-desc-in')`), 'edit field open');
    await ev(tall); await sleep(100);
    let g = await ev(geo);
    // 36rem block: the field takes what the head and the button bar leave (before the fix it stayed at its 10rem / 8 rows)
    check(g.ta > 400 && g.secB - g.barB < 40, '#3399: the edit field fills the taller widget, the buttons at its bottom ' + JSON.stringify(g));
    await shot('p23802-desc-tall.png');
    // a long text: the field grows with it, no inner scroll bar
    await ev(`(() => { const s = document.querySelector('#pov-desc'); s.style.height = ''; const t = document.querySelector('#pov-desc-in'); t.focus();
      t.value = Array.from({length: 60}, (_, i) => 'Line ' + (i + 1) + ': contacts, rooms and keys').join('\\n'); t.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
    await sleep(150);
    g = await ev(geo);
    check(g.ta > 900 && g.taScroll <= 2, '#3399: a long text: the field grows while typing, no inner scroll bar ' + JSON.stringify(g));
    await shot('p23802-desc-long.png');
  }, true);

  console.log(`p23802_ff_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
