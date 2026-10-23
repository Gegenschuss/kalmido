// 2.138.0 B (#2161) UI tests, own container (start.sh). The sidebar: the search field is docked at the bottom (all widths),
// freelancer-matrix: n/a - nur Oberfläche (Person ohne Organisation wird in der Datei geprüft)
// the head is logo + avatar, row 2 = workspace button (name, ellipsis) + fold-all; a person without an organisation sees "Private".
// 2.138.2 (#2392): no logo; the workspace button is the head, the avatar sits next to the search (p21381_c_ui).
// jsdom (structure, freelancer) + Firefox at 390 (drawer open, Search tab in the bar) and 1280. Screenshots with P2138B_SHOTS=<dir>.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2138_b_ui', check, shots: 'P2138B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'A very long organisation name that must be cut with an ellipsis', lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const L = (await call('POST', '/api/lists', {name: 'Home'})).id;

  // ================= jsdom: structure
  let w = await boot({hash: 'inbox'}), d = w.document;
  await until(() => d.querySelector('#kbar .kbsrch'), 60);  // 2.152.3 (#2619): a computer: the search moved from the top of the panel into the head bar
  check(d.querySelector('#kbar .kbsrch[data-act="palette"]') && !d.querySelector('#side .scmd') && !d.querySelector('#side .sbdock'), 'the search field sits in the head bar (no bottom dock on a computer)');  // 2.152.3 (#2619): the search in the head bar, none in the panel
  // 2.138.2 (#2392): head = workspace button (the heading) + fold-all; the avatar sits next to the search in the dock
  check(d.querySelector('#kbar .kbacct') && !d.querySelector('#srail .sbacct') && !d.querySelector('#side .sbacct') && !d.querySelector('#side .sbrand'), 'no logo row; the avatar in the head bar');  // 2.152.3 (#2619): the account moved from the bottom of the bar into the head bar
  const bar = d.querySelector('#kbar .kbsw');  // 2.152.3 (#2619): the workspace switch moved into the head bar, fold all (.sbbfa) stays in the panel head
  check(bar && bar.getAttribute('data-act') === 'sbb-ws' && bar.querySelector('.wsn')?.textContent && d.querySelector('#side .sbhead .sbbfa'), 'head: workspace button with name, fold-all in the panel head');
  w.close();

  // a person without an organisation: "Private"
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const FCK = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'}, FCK);
  w = await boot({user: 'frida', hash: 'inbox'}); d = w.document;
  const fb = await until(() => d.querySelector('#kbar .kbsw'), 60);  // 2.138.2 (#2392) // 2.152.3 (#2619): the switch in the head bar
  check(fb && /Private/.test(fb.querySelector('.wsn')?.textContent || ''), 'without an organisation the button says "Private"');
  w.close();

  const login2 = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async ev => { for (let i = 0; i < 40 && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(250); await sleep(800); };
  const GEO = `(() => { const q = s => document.querySelector(s), r = e => e && e.getBoundingClientRect(), se = q('#kbar .kbsrch') || q('#side .scmd'), s = r(se), sd = r(q('#side')), a = r(q('#kbar .kbacct') || q('#side .sbacct')) /* 2.152.3 (#2619): the head bar on a computer */, ws = r(q('#kbar .kbsw') || q('#side .wsbar'));
    return {sv: !!s && s.width > 0 && getComputedStyle(se).display !== 'none', sdt: sd && Math.round(sd.top), sb: s && Math.round(s.bottom), st: s && Math.round(s.top), sfb: Math.round(r(q('#side .sbfix'))?.bottom || 0) /* 2.152.2 (#2622) */, ih: innerHeight, sdb: sd && Math.round(sd.bottom), sw: s && s.height,
      ay: a && Math.round(a.top), ax: a && Math.round(a.right), wy: ws && Math.round(ws.top), ww: ws && Math.round(ws.width), sdw: sd && Math.round(sd.width), name: (q('#kbar .wsn') || q('#side .wsn'))?.textContent, over: document.documentElement.scrollWidth - innerWidth}; })()`;
  for (const [vw, vh, tag] of [[390, 844, 'phone'], [1280, 800, 'desktop']]) await firefox(async o => {
    const {cmd, ev, ctx, shot} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
    check(await login2(o) === 200, tag + ': login');
    await o.nav(B + '#inbox'); await ready(ev);
    // the fixture's admin still has the first-run setup pending: take its page away (screenshots show the app)
    await ev(`(() => { document.querySelectorAll('.authscreen').forEach(e => e.remove()); document.querySelector('#app')?.removeAttribute('inert'); return 1; })()`);
    if (vw < 900) { await ev(`(() => { document.querySelector('#top [data-act="side"]').click(); return 1; })()`); await sleep(700); }
    const g = await ev(GEO);
    if (vw < 900) check(g.sv && g.sb <= g.sfb && g.st >= g.wy && g.sw >= 43.5, `${tag}: the search field sits in the fixed top under the workspace, 44 px ` + JSON.stringify(g));  // 2.196.0 (#2737): the drawer like sidebar B: search on top, Settings + account at the bottom (was: at the bottom edge)
    else check(g.sv && g.sb <= g.sdt + 1 && g.sw >= 29.5, `${tag}: the search field sits in the head bar over the panel ` + JSON.stringify(g));  // 2.152.3 (#2619): the search moved from the top of the panel into the head bar
    if (vw < 900) check(g.ay > g.wy && g.ww >= 56 && g.ww <= g.sdw && g.over <= 0, `${tag}: workspace button on top, avatar at the bottom (2.138.2 #2392), nothing sideways ` + JSON.stringify(g));
    else check(g.wy < g.sdt && g.ay < g.sdt && g.ww >= 56 && g.ww <= 420 && g.over <= 0, `${tag}: workspace button and avatar in the head bar, the long name cut, nothing sideways ` + JSON.stringify(g));  // 2.152.3 (#2619): workspace + account in the head bar (.kbfirm max 15rem)
    if (vw < 900) check(await ev(`document.body.classList.contains('tab-search')`), `${tag}: the Search tab is in the bar (default)`);
    // Mod+K itself is covered by appearance_ui (jsdom); untouched by #2161
    await ev(`(() => { document.querySelector('#kbar .kbsrch, #side .scmd').click(); return 1; })()`);  // 2.152.3 (#2619): on a computer the search is in the head bar
    check(await until(() => ev(`!!document.querySelector('.palette')`), 30), `${tag}: a click on the docked field opens the palette`);
    await ev(`(() => { closePalette(); return 1; })()`); await until(() => ev(`!document.querySelector('.palette')`), 30); await sleep(300);
    if (vw < 900 && !(await ev(`!!document.querySelector('#side.open')`))) { await ev(`(() => { document.querySelector('#top [data-act="side"]').click(); return 1; })()`); await sleep(700); }
    await shot(`p2138b-${vw}.png`);
  }, vw < 900);
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
