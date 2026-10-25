// 2.144.1 UI tests, part A (#2445, office: the office side bar stays put on tablets while the page scrolls), own container
// (start.sh), Firefox. Invented data only. freelancer-matrix: office
// - a person without organisation (personal office): at 820x1180 and 1180x820 (touch) and on a mouse desktop the office
//   menu (#side office points / .ofpb) keeps its place while the page scrolls, the content moves; the desktop has one scroll bar only
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21441_a_ui', check, shots: 'P21441A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21441A_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fu.http < 300, 'a person without organisation ' + fu.http);
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,office,clients,docs,files'});

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  // top of the menu and of the page's first block after scrolling the page (whatever scrolls: #view or the document) by 500 px
  // 2.152.2 (#2617): a computer (>= 900 px) has the office points in the panel #side (no .ofrail), a phone keeps .ofpb
  const probe = `(() => { const nav = document.querySelector('#view .ofpb, #side [data-ofm]'); const body = document.querySelector('#view .ofbody, #view .dash'); if (!nav || !body) return null;
    const pad = document.createElement('div'); pad.id = 'fill2445'; pad.style.height = '3000px'; body.appendChild(pad);
    const v = document.querySelector('#view'); const t0 = nav.getBoundingClientRect().top, b0 = pad.getBoundingClientRect().top;  // the filler at the end of the page moves up when the page scrolls
    const ob = document.querySelector('#view .ofbody'); const can = e => e && /auto|scroll/.test(getComputedStyle(e).overflowY); if (can(v)) v.scrollTop = 500; if (can(ob)) ob.scrollTop = 500;  // a finger scrolls these only
    const t1 = nav.getBoundingClientRect().top, b1 = pad.getBoundingClientRect().top;
    const se = document.scrollingElement; return {kind: nav.className, t0, t1, b0, b1, doc: se.scrollHeight > se.clientHeight + 1, view: v.scrollTop > 0 || !!(ob && ob.scrollTop > 0)}; })()`;
  const TABS = ['offers', 'cashflow', 'bank', 'settings'];
  const sizes = [['tablet portrait', 820, 1180, true], ['tablet landscape', 1180, 820, true], ['desktop', 1440, 900, false]];
  for (const [name, w, h, touch] of sizes) {
    await firefox(async ({cmd, ev, ctx, nav, shot}) => {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: w, height: h}});
      await nav(B + 'static/icon.svg');
      await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.ofmAll', 'true'); localStorage.setItem('tasks.sbbUnfold', '["office:money"]'); /* 2.276.0 (#3039): every office point shown, Money open by hand (the first-day menu: p2276_a_ui.js) */ sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
      await signIn(ev, 'frida');
      await nav(B + '#office/offers');
      for (const t of TABS) {
        await ev(`(() => { document.getElementById('fill2445')?.remove(); location.hash = '#office/${t}'; return 1; })()`);
        check(await ready(ev, `!!document.querySelector('#view .ofpb, #side [data-ofm]') && location.hash === '#office/${t}'`, 80), name + ' ' + t + ': the office menu is shown');  // 2.152.2 (#2617): the points in the panel #side
        await sleep(700);
        const p = await ev(probe); await sleep(300);
        check(p && p.view, name + ' ' + t + ': the page scrolls (#view or .ofbody) ' + JSON.stringify(p));
        check(p && Math.abs(p.t1 - p.t0) < 1.5, name + ' ' + t + ': the menu keeps its place ' + JSON.stringify(p));
        check(p && p.b1 < p.b0 - 100, name + ' ' + t + ': the content moved ' + JSON.stringify(p));
        check(p && !p.doc, name + ' ' + t + ': no second scroll bar (the document does not scroll) ' + JSON.stringify(p));
        await ev(`(() => { document.querySelector('#view').scrollTop = 0; return 1; })()`);
      }
      await shot('p21441-a-' + name.replace(' ', '-') + '.png');
    }, touch);
  }
  console.log(`p21441_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
