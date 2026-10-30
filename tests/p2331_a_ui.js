// kalmido-suite: fresh
// 2.331.0 part A UI tests (#3300 news list: p2145_a_ui; #3303 sidebar B head scrolls along, #3306 sticky save bar, #3307 project files, #3310 folded description).
// save bar of the project description, #3310 long description folds, // save bar of the project description, #3307 project files: 8 rows, show all, search). Own container (start.sh), Firefox 1280 px.
// freelancer-matrix: tasks (alice has no organisation: private project, the same page). P2331A_NOSTART=1 = the server runs.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2331_a_ui', check, shots: 'P2331A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2331A_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGP4z8DAwMDAxMDAwMDAAAANHQEDasKb6QAAAABJRU5ErkJggg==', 'base64');
const up = async (url, name) => { const fd = new FormData(); fd.append('file', new Blob([PNG], {type: 'image/png'}), name); fd.append('type', 'file'); return fetch(B + url, {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd}); };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  for (let i = 1; i <= 40; i++) await call('POST', '/api/lists', {name: 'Filler project ' + i, kind: 'project'});
  const P = (await call('POST', '/api/lists', {name: 'Long page', kind: 'project'})).id;
  await call('PATCH', `/api/lists/${P}/overview`, {description: Array.from({length: 60}, (_, i) => 'Line ' + (i + 1)).join('\n\n')});
  for (let i = 1; i <= 12; i++) check((await up(`api/lists/${P}/files`, `plan-${String(i).padStart(2, '0')}.png`)).ok, 'file ' + i);
  const PS = (await call('POST', '/api/lists', {name: 'Short page', kind: 'project'})).id;
  await call('PATCH', `/api/lists/${PS}/overview`, {description: 'Just one line.'});
  const T = (await call('POST', '/api/tasks', {title: 'Task with files', list_id: P})).id;
  for (let i = 1; i <= 10; i++) await up(`api/tasks/${T}/attachments`, `att-${String(i).padStart(2, '0')}.png`);

  const ready = async (ev, expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  await firefox(async ({cmd, ev, ctx, nav}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 800}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.pov', '[${P},${PS}]'); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    // ===== #3303 sidebar B: the head scrolls along (many projects)
    await nav(B + '#l/' + P);
    check(await ready(ev, `!!document.querySelector('#view .pov') && !!document.querySelector('#side .sbfix')`), 'project page and sidebar are up');
    await sleep(1500);  // let the page settle (a late render replaces the sidebar)
    const sc = await ev(`(() => { const s = document.querySelector('#side'), t0 = s.querySelector('.sbfix').getBoundingClientRect().top; s.scrollTop = 400; return new Promise(r => setTimeout(() => { const f = document.querySelector('#side .sbfix'); r({pos: getComputedStyle(f).position, flow: f.classList.contains('sbfix-flow'), moved: document.querySelector('#side').scrollTop > 0, t0, t1: f.getBoundingClientRect().top}); }, 300)); })()`);
    check(sc.flow && sc.pos === 'static' && sc.moved && sc.t1 < sc.t0 && sc.t1 < 0, '#3303: sidebar B head scrolls out of view ' + JSON.stringify(sc));
    // ===== #3307 project files: 8 rows
    // CI of 2.409.0 (#3506): a late redraw of the project page may swap a button out for a moment - click it once it is there
    const tap = async (sel, what) => check(await ready(ev, `(() => { const b = document.querySelector(${JSON.stringify(sel)}); if (!b) return false; b.click(); return true; })()`), what);
    const rows = k => ev(`[...document.querySelectorAll('#pov-files .povfl[data-k="${k}"] .povf')].filter(e => e.offsetParent).length`);
    check(await ready(ev, `!!document.querySelector('#pov-files .povfl[data-k="files"]')`), 'files list is there');
    check(await rows('files') === 8, '#3307: 8 of 12 project files show ' + await rows('files'));
    check(await ev(`document.querySelector('#pov-files [data-pov="fl-more"][data-k="files"]').textContent.trim()`) === 'Show all 12', '#3307: "Show all 12"');
    check(await ev(`!!document.querySelector('#pov-files input.povfq[data-k="files"]')`), '#3307: search field from 9 entries');
    check(await ev(`document.querySelector('#pov-files details.povtf') && !document.querySelector('#pov-files details.povtf').open`) , '#3307: task attachments (10) are closed by default');
    await tap('#pov-files [data-pov="fl-more"][data-k="files"]', '#3307: "Show all" is there');
    check(await ready(ev, `[...document.querySelectorAll('#pov-files .povfl[data-k="files"] .povf')].filter(e => e.offsetParent).length === 12`), '#3307: show all shows 12');
    await nav(B + '#l/' + P); await nav(B + '#l/' + P);
    await ev('location.reload()');
    check(await ready(ev, `[...document.querySelectorAll('#pov-files .povfl[data-k="files"] .povf')].filter(e => e.offsetParent).length === 12`), '#3307: the state stays after reloading');
    await ev(`(() => { const q = document.querySelector('#pov-files input.povfq[data-k="files"]'); q.value = 'plan-11'; q.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
    check(await ready(ev, `[...document.querySelectorAll('#pov-files .povfl[data-k="files"] .povf')].filter(e => e.offsetParent).length === 1`), '#3307: the search filters by file name');
    await ev(`(() => { const q = document.querySelector('#pov-files input.povfq[data-k="files"]'); q.value = ''; q.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
    await ready(ev, `[...document.querySelectorAll('#pov-files .povfl[data-k="files"] .povf')].filter(e => e.offsetParent).length === 12`);
    await tap('#pov-files [data-pov="fl-more"][data-k="files"]', '#3307: "Show less" is there');
    check(await ready(ev, `[...document.querySelectorAll('#pov-files .povfl[data-k="files"] .povf')].filter(e => e.offsetParent).length === 8`), '#3307: show less goes back to 8');
    // ===== #3310 a long description is folded in the view
    // CI of 2.409.0 (#3506): the view may still redraw after "show less" of the files - wait for the description (was a JS crash)
    check(await ready(ev, `!!document.querySelector('#pov-desc .povmd') && document.querySelector('#pov-desc .povmd').classList.contains('clamp') && document.querySelector('#pov-desc [data-pov="md-more"]').textContent.trim() === 'Show more'`), '#3310: a long description is folded with "Show more"');
    await tap('#pov-desc [data-pov="md-more"]', '#3310: "Show more" / "Show less" is there');
    check(await ready(ev, `!document.querySelector('#pov-desc .povmd').classList.contains('clamp') && document.querySelector('#pov-desc [data-pov="md-more"]').textContent.trim() === 'Show less'`), '#3310: Show more unfolds');
    await ev('location.reload()');
    check(await ready(ev, `!!document.querySelector('#pov-desc .povmd') && !document.querySelector('#pov-desc .povmd').classList.contains('clamp')`), '#3310: the state stays after reloading');
    await tap('#pov-desc [data-pov="md-more"]', '#3310: "Show more" / "Show less" is there');
    check(await ready(ev, `document.querySelector('#pov-desc .povmd').classList.contains('clamp')`), '#3310: Show less folds again');
    await nav(B + 'static/icon.svg'); await nav(B + '#l/' + PS);
    check(await ready(ev, `!!document.querySelector('#pov-desc .povmd') && /Just one line/.test(document.querySelector('#pov-desc').textContent)`) && await ev(`!document.querySelector('#pov-desc [data-pov="md-more"]') && !document.querySelector('#pov-desc .povmd.clamp')`), '#3310: a short description has no button ');
    await nav(B + 'static/icon.svg'); await nav(B + '#l/' + P);
    check(await ready(ev, `!!document.querySelector('#pov-desc .povmd.clamp')`), 'back on the long page');
    // ===== #3306 the description's save bar stays in view
    await ev(`(() => { document.querySelector('#pov-desc [data-pov="desc-edit"]')?.click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('#pov-desc-in') && !!document.querySelector('.povbar.povedit')`), 'description editor opened');
    await ev(`(() => { document.querySelector('#view').scrollTop = 0; window.scrollTo(0, 0); document.querySelector('#pov-desc-in').style.height = '3000px'; return 1; })()`);
    const bar = await ev(`(() => { const b = document.querySelector('[data-pov="desc-save"]'), r = b.getBoundingClientRect(), e = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return {top: r.top, bottom: r.bottom, ih: innerHeight, hit: e === b || b.contains(e)}; })()`);
    check(bar.bottom <= bar.ih + 1 && bar.top >= 0 && bar.hit, '#3306: Save is in view and clickable without scrolling ' + JSON.stringify(bar));
    await ev(`(() => { document.querySelector('[data-pov="desc-save"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('#pov-desc-in')`), '#3306: Save closes the editor');
  }, false);
  // ===== #3313 touch, tablet width: the titles of all sidebar group heads start on one line
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 960, height: 800}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    await nav(B + '#l/' + P);
    check(await ready(ev, `document.querySelectorAll('#side .sgh .sgt > span').length >= 2 && !!document.querySelector('#side .sg-lists .sgh')`), '#3313: group heads are there');
    await sleep(1000);
    const L = await ev(`[...document.querySelectorAll('#side .sgh .sgt > span:not(.c):not(.sr)')].filter(e => e.offsetParent).map(e => { const r = document.createRange(); r.selectNodeContents(e); return [e.textContent.trim(), Math.round(r.getBoundingClientRect().left * 10) / 10]; })`);
    check(await ev(`matchMedia('(pointer:coarse)').matches`), '#3313: the touch screen is coarse');
    check(L.length >= 2 && L.every(x => Math.abs(x[1] - L[0][1]) <= 1), '#3313: the titles of all group heads start on one line ' + JSON.stringify(L));
    await shot('p2331-a-sidebar-heads.png');
  }, true);
  console.log(`p2331_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
