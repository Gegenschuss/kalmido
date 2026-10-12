// 2.39.1 UI tests, part R, own container (start.sh), Firefox (desktop, mouse, motion allowed):
// - #1220: the dialog "Add service" covers the whole window, also after the window got bigger or smaller (its class no
//   longer picks up the 40vh rule of a list); the card sits in the middle; the empty state links to the Services tab
// - #1213: the loading screen (#boot) is gone once the app is drawn; a reload in the same session skips it
// - #1292: the celebration: the heron about a quarter of the width in the middle, a big check, colourful confetti to all
//   sides, three levels (today < list < project: size and amount), a tap ends it at once
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2391_r_ui', check, shots: 'P2391R_SHOTS', prefs: [['ui.prefersReducedMotion', 0]]});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const offer = await call(CA, 'POST', '/api/office/docs', {project_title: 'Imagefilm'});
  check(offer.http === 201, 'a quotation ' + offer.http);

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    const vp = (width, height) => cmd('browsingContext.setViewport', {context: ctx, viewport: {width, height}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await vp(1280, 900);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);

    // ================= #1213 the loading screen
    await nav(B + '#office/offers/' + offer.id);
    check(await ready(ev, `!!document.querySelector('.ofdeditor') && !document.getElementById('boot')`, 60), '#1213: the loading screen is gone once the app is drawn');
    check(await ev(`sessionStorage.getItem('kalmido.booted') === '1'`), '#1213: the session remembers the first start');
    await ev(`(() => { setTimeout(() => location.reload(), 50); return 1; })()`); await sleep(1500);
    check(await ready(ev, `!!document.querySelector('.ofdeditor')`, 60) && await ev(`document.documentElement.classList.contains('rebooting') && getComputedStyle(document.getElementById('boot') || document.body).display !== 'flex'`), '#1213: a reload in the same session skips the loading screen');

    // ================= #1220 the service picker covers the whole window, before and after a resize
    await vp(900, 560);
    await sleep(300);
    await ev(`(() => { document.querySelector('[data-ofd="it-svc"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal.ofdpick .card')`), '#1220: the service picker opens');
    const geo = `(() => { const m = document.querySelector('.modal.ofdpick'), r = m.getBoundingClientRect(), c = m.querySelector('.card').getBoundingClientRect();
      return {w: Math.round(r.width), h: Math.round(r.height), top: Math.round(r.top), iw: innerWidth, ih: innerHeight, cmid: Math.round(c.top + c.height / 2), cx: Math.round(c.left + c.width / 2)}; })()`;
    const g0 = await ev(geo);
    check(g0.w === g0.iw && g0.h === g0.ih && g0.top === 0, '#1220: the backdrop covers the small window ' + JSON.stringify(g0));
    await vp(1400, 1000); await sleep(400);
    const g1 = await ev(geo);
    check(g1.w === g1.iw && g1.h === g1.ih && Math.abs(g1.cmid - g1.ih / 2) < 40 && Math.abs(g1.cx - g1.iw / 2) < 4, '#1220: after the window got bigger: still the whole window, the card in the middle ' + JSON.stringify(g1));
    await shot('p2391-r-picker-1400.png');
    await vp(700, 480); await sleep(400);
    const g2 = await ev(geo);
    check(g2.w === g2.iw && g2.h === g2.ih, '#1220: after the window got smaller: still the whole window ' + JSON.stringify(g2));
    check(await ev(`!!document.querySelector('.modal.ofdpick .lempty a[href="#office/services"]')`), '#1220: the empty state names the Services tab as a link');
    await ev(`(() => { document.querySelector('.modal.ofdpick .lempty a').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.modal.ofdpick') && location.hash === '#office/services'`), '#1220: the link closes the picker and opens the tab');
    // every dialog keeps the full backdrop (same modal())
    await vp(1280, 900); await sleep(300);
    const all = await ev(`(() => { const m = modal('<h3>x</h3>'); m.classList.add('ofdpick', 'cdlg'); const r = m.getBoundingClientRect(); m.remove(); return {w: Math.round(r.width), h: Math.round(r.height), iw: innerWidth, ih: innerHeight}; })()`);
    check(all.w === all.iw && all.h === all.ih, '#1220: an extra class never shrinks a dialog backdrop ' + JSON.stringify(all));

    // ================= #1292 the celebration
    const frame = kind => ev(`(() => { document.querySelectorAll('.cele,.cele-quip').forEach(x => x.remove()); celebrate('${kind}', {frame: 0.5, force: true, name: 'Demo'});
      const el = document.querySelector('.cele'), b = el.querySelector('.cbird').getBoundingClientRect(), k = el.querySelector('.ccheck'), cs = [...el.querySelectorAll('.cconf')];
      const pos = cs.map(c => c.getBoundingClientRect()).filter((r, i) => +getComputedStyle(cs[i]).opacity > 0).map(r => [r.left + r.width / 2, r.top + r.height / 2]);
      return {bw: Math.round(b.width), bx: Math.round(b.left + b.width / 2), by: Math.round(b.top + b.height / 2), n: cs.length, vis: pos.length,
        colors: new Set(cs.map(c => c.style.getPropertyValue('--cc'))).size, kop: +getComputedStyle(k).opacity, kw: Math.round(k.getBoundingClientRect().width),
        left: pos.filter(p => p[0] < innerWidth / 2 - 60).length, right: pos.filter(p => p[0] > innerWidth / 2 + 60).length, up: pos.filter(p => p[1] < innerHeight * 0.4 - 60).length,
        vw: innerWidth, vh: innerHeight, kind: el.dataset.kind}; })()`);
    const t = await frame('today'), l = await frame('list'), p = await frame('project');
    await shot('p2391-r-celebration-project.png');
    check(Math.abs(l.bw - l.vw * 0.25) < 8 && Math.abs(l.bx - l.vw / 2) < 4 && l.by < l.vh / 2, '#1292: the heron about a quarter of the width, in the middle ' + JSON.stringify(l));
    check(t.bw < l.bw && l.bw < p.bw && t.n < l.n && l.n < p.n, '#1292: three levels today < list < project (size, amount) ' + JSON.stringify([t.bw, l.bw, p.bw, t.n, l.n, p.n]));
    check(p.kop > 0.9 && p.kw > p.bw * 0.3, '#1292: a big check has popped up ' + JSON.stringify([p.kop, p.kw]));
    check(p.colors >= 5, '#1292: colourful confetti ' + p.colors);
    check(p.vis > 20 && p.left > 5 && p.right > 5 && p.up > 3, '#1292: the confetti bursts to all sides ' + JSON.stringify([p.vis, p.left, p.right, p.up]));
    const fl = await ev(`(() => { const xs = [0.1, 0.5, 0.9].map(f => { document.querySelectorAll('.cele,.cele-quip').forEach(x => x.remove()); celebrate('today', {frame: f, force: true}); const r = document.querySelector('.cele .cbird').getBoundingClientRect(); return Math.round(r.left); }); return xs; })()`);
    check(fl[0] < fl[1] && fl[1] < fl[2], '#1292: in from the left, off to the right ' + fl);
    // a tap ends the running celebration at once
    await ev(`(() => { document.querySelectorAll('.cele,.cele-quip').forEach(x => x.remove()); celebrate('list', {force: true, name: 'Demo'}); return 1; })()`);
    await sleep(500);
    check(await ev(`!!document.querySelector('.cele') && !!document.querySelector('.cele-quip')`), '#1292: the celebration runs');
    await ev(`(() => { document.querySelector('.cele').dispatchEvent(new PointerEvent('pointerdown', {bubbles: true})); return 1; })()`);
    await sleep(100);
    check(await ev(`!document.querySelector('.cele') && !document.querySelector('.cele-quip')`), '#1292: a tap ends it at once');
  }, false);

  console.log(`p2391_r_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
