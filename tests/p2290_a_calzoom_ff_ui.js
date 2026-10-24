// 2.290.0 A UI tests (#3144 the number of days in the week grid, real layout): own container (start.sh), Firefox (phone +
// desktop width). Invented tasks only.
// - 4 kept days on a phone: 4 equally wide columns, head / all-day row / hours line up, nothing sticks out to the side
// - while the fingers move (3.5 days live): each column is 1/3.5 of the width, the 4th one cut at the grid's edge
// - 10 days on a computer: 10 columns, the title names the range
// freelancer-matrix: n/a (no route; the grid is drawn in the client only, tested as alice without an organisation)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2290_a_calzoom_ff_ui', check, shots: 'P2290A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', lang: 'en'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,events'});
  const day = i => { const d = new Date(); d.setDate(d.getDate() + i); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
  for (const [i, t, title] of [[0, '09:00', 'Pitch deck review'], [1, '11:30', 'Call with the studio'], [2, '14:00', 'Edit rough cut'], [3, null, 'Send invoices'], [5, '10:00', 'Location scout']]) {
    const r = await call(CA, 'POST', '/api/tasks', {title, due: day(i), ...(t ? {due_time: t, duration: 60} : {})});
    check(r.http === 200 || r.http === 201, 'task ' + title + ' ' + r.http);
  }
  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = ev => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  // the columns of the head, the all-day row and the hours: [left, width] each, and the grid's right edge
  const geo = `(() => { const r = s => [...document.querySelectorAll(s)].map(e => { const b = e.getBoundingClientRect(); return [Math.round(b.left), Math.round(b.width)]; });
    return {wh: r('#view .whead .wh'), wad: r('#view .wad'), wcol: r('#view .wcol'), edge: Math.round(document.querySelector('#view .week').getBoundingClientRect().right), W: document.documentElement.clientWidth, title: document.querySelector('#view .calbar h2').textContent}; })()`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); localStorage.setItem('tasks.calMode', '"week"'); localStorage.setItem('tasks.calDays', '4'); return 1; })()`);
    await signIn(ev);
    await nav(B + '#cal');
    check(await ready(ev, `document.querySelectorAll('#view .wcol').length === 4`, 80), 'phone: 4 kept days drawn');
    await ev(`(() => { S.calSel = '${day(0)}'; renderView(); document.querySelector('#wbody').scrollTop = 8 * weekH(); return 1; })()`);
    await sleep(300);
    let g = await ev(geo);
    const same = (a, b) => a.length === b.length && a.every((x, i) => Math.abs(x[0] - b[i][0]) <= 1 && Math.abs(x[1] - b[i][1]) <= 1);
    check(g.wcol.length === 4 && g.wcol.every(c => Math.abs(c[1] - g.wcol[0][1]) <= 1) && same(g.wh, g.wad), 'phone: 4 equally wide columns, head and all-day row line up ' + JSON.stringify(g.wcol));
    check(g.wcol.every(c => Math.abs(c[1] - g.wh[0][1]) <= 16) && g.edge <= g.W + 1, 'phone: the hours under the head, nothing sticks out to the side');
    await shot('p2290-a-4days-phone.png');
    // the fingers between 3 and 4 days: drawn as calgest.js does while they move
    await ev(`(() => { CAL_LIVE = {nf: 3.5, from: '${day(0)}'}; renderView(); return 1; })()`);
    await sleep(200);
    g = await ev(geo);
    const lw = (g.wh[1][0] - g.wh[0][0]), area = g.edge - g.wh[0][0];
    check(g.wh.length === 4 && Math.abs(lw - area / 3.5) <= 3 && g.wh[3][0] + g.wh[3][1] > g.edge, 'live 3.5 days: each column 1/3.5 wide, the 4th cut at the edge ' + lw + ' ' + area);
    check(await ev(`getComputedStyle(document.querySelector('#wbody')).overflowX === 'hidden'`), 'live: the cut column does not make the hours scroll sideways');
    await shot('p2290-a-live-phone.png');
    await ev(`(() => { CAL_LIVE = null; return 1; })()`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await ev(`(() => { LS.set('calDays', 10); renderView(); return 1; })()`);
    await sleep(300);
    g = await ev(geo);
    check(g.wcol.length === 10 && same(g.wh, g.wad) && g.edge <= g.W + 1 && / – /.test(g.title), 'desktop: 10 days, lined up, the title names the range ' + g.title);
    await shot('p2290-a-10days-desktop.png');
  }, true);

  console.log(`p2290_a_calzoom_ff_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
