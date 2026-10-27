// 2.138.2 C UI tests, own container (start.sh). The sidebar's head and the workspace colour:
// #2392 variant A: no logo; the workspace switch (dot + name + arrow) is the first row and the heading; the account picture
//       sits without dots next to the search at the bottom; fold-all / fold the sidebar only show on hover / keyboard focus
//       (always on touch screens); the connection dot only offline / while syncing; the update dot only at Settings;
//       "Start" stays reachable (account menu, Mod+K).
// #2389 the workspace colour is a 4 px stripe on top of the sidebar (my choice > the organisation's colour > the accent for
//       Private), 3 px on top of the header while the sidebar is closed (phone, rail); no tint, no stripe in the list
//       header; the setting is called "Workspace colour".
// freelancer-matrix: n/a - nur Oberfläche (Person ohne Organisation: "Private" + Lila-Strich + eigene Farbe, in der Datei geprüft)
// jsdom (structure, colours, freelancer) + Firefox at 390 / 1000 (rail) / 1280, dark + light. Screenshots with P21381C_SHOTS=<dir>.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21381_c_ui', check, shots: 'P21381C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21381C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Studio', lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', workspace: 'private', ws_colors: '{}'});
  await call('POST', '/api/lists', {name: 'Home'});

  // ================= jsdom: #2392 the head
  let w = await boot({hash: 'inbox'}), d = w.document;
  await until(() => d.querySelector('#kbar .kbsw'), 60);  // 2.152.3 (#2619): the workspace switch moved into the head bar
  const fix = d.querySelector('#side .sbfix');
  check(fix && fix.firstElementChild?.classList.contains('sbhead'), '#2392: the head opens the fixed part (the stripe is #side\'s top border)');
  // 2.145.0 (#2437): the logo + word mark came back at the BOTTOM of the sidebar; 2.161.2 (#2607): they moved into the head,
  // the brand IS the workspace switch (p2152a_ui), no extra brand row / home button
  check(!d.querySelector('#side .sbrand') && d.querySelector('#kbar .kbsw .kbbrand svg.logo') && !d.querySelector('#side svg.logo') && d.querySelectorAll('#kbar svg.logo').length === 1 && !d.querySelector('#side .sbhome'), '#2392 / #2607: the logo only inside the workspace switch on top');  // 2.152.3 (#2619): the brand + switch moved from the panel head into the head bar
  const bar = d.querySelector('#kbar .kbsw');  // 2.152.3 (#2619): the workspace switch moved into the head bar (sbb-ws)
  check(bar && bar === d.querySelector('#kbar button') && bar.dataset.act === 'sbb-ws' && /Private/.test(bar.querySelector('.wsn')?.textContent || '') && bar.querySelector('.wsp-dot') && bar.querySelector('svg.i:last-child'), '#2392: row 1 = the workspace switch: dot + name + arrow');
  check(d.querySelector('#side .sbhead .sbtools .sbbfa') && d.querySelector('#side .sbhead .sbtools .sbbhide') && d.querySelector('#side .sbhead h2.sbbpt'), '#2392: fold-all sits in the head\'s tools (hover / focus)');  // 2.152.3 (#2619): the panel head = area name + Fold all (.sbbfa) + Hide the panel
  const acct = d.querySelector('#kbar .kbend .kbacct');  // 2.152.3 (#2619): the account moved from the bottom of the bar into the head bar
  check(acct && acct.querySelector('.avatar') && !acct.querySelector('.netdot, .dot') && !d.querySelector('#srail .sbacct') && [...d.querySelectorAll('#srail .srfoot > *')].every(x => x.classList.contains('sset')), '#2392: the avatar without dots in the head bar, only Settings at the bottom of the bar');  // 2.152.3 (#2619): the account in the head bar
  const nd = () => d.querySelector('#kbar .netdot');  // 2.152.3 (#2619): the dot moved from the panel head into the head bar
  check(nd()?.classList.contains('n-on') && nd().getAttribute('aria-label') === 'Online', '#2392: online: the dot is there for the state but n-on (hidden by CSS)');
  w.eval(`OUT.flushing = true; netDotDraw()`);
  check(nd()?.classList.contains('n-sync'), '#2392: syncing: the dot shows');
  w.eval(`OUT.flushing = false; netDotDraw()`);
  w.eval(`S.about = Object.assign(S.about || {}, {available: '99.0.0'}); renderSide()`);
  check(d.querySelector('#srail .sset .nunread') && !d.querySelector('#kbar .kbacct .dot'), '#2392: the update dot only at Settings');  // 2.152.3 (#2619): the account in the head bar
  w.eval(`S.about.available = null; renderSide()`);
  click(w, d.querySelector('#kbar .kbacct')); await sleep(200);  // 2.152.3 (#2619): the account in the head bar
  const home = [...d.querySelectorAll('#pop [role="menuitem"]')].find(b => (b.querySelector('.ml') || b).textContent.trim() === 'Start');
  check(!!home, '#2392: the account menu has "Start" (the logo is gone)');
  if (home) { click(w, home); await sleep(500); }
  check(w.location.hash === '#home', '#2392: "Start" opens the start page ' + w.location.hash);

  // ================= jsdom: #2389 the stripe's colour
  const app = () => d.querySelector('#app');
  check(app().classList.contains('wsb-on') && app().style.getPropertyValue('--wbd') === 'var(--accent)' && app().style.getPropertyValue('--wbl') === 'var(--accent)', '#2389: Private without a choice: the accent (Kalmido purple)');
  check(!d.querySelector('#side').classList.contains('wsp-on') && !d.querySelector('#side').style.getPropertyValue('--sbbg'), '#2389: no tint of the sidebar');
  check(d.querySelector('#kbar .kbsw .wsp-dot[data-wsc]')?.getAttribute('style')?.includes('var(--accent)'), '#2389: the dot of the switch in the same colour');  // 2.152.3 (#2619): the switch in the head bar (looked up fresh, the bar redraws)
  const ORG = ((await call('GET', '/api/state')).me.workspaces || [])[0]?.id;
  check(!!ORG, 'the fixture organisation ' + ORG + ' ' + w.eval(`JSON.stringify(S.me.workspaces)`));
  if (!ORG) throw new Error('no organisation in the fixture');
  const orgTone = w.eval(`WSC_TONES[wsc_ix(wsOrg(${ORG}).color, ${ORG})]`);
  w.eval(`wsSet('org:${ORG}')`); await sleep(400);
  check(app().style.getPropertyValue('--wbd') === orgTone[0] && app().style.getPropertyValue('--wbl') === orgTone[1], '#2389: an organisation: the admins\' colour ' + app().getAttribute('style'));
  w.eval(`S.settings.ws_colors = JSON.stringify({'org:${ORG}': 'teal'}); render()`);
  check(app().style.getPropertyValue('--wbd') === '#2dd4bf', '#2389: my own choice wins over the organisation\'s colour');
  w.eval(`S.settings.ws_colors = JSON.stringify({'org:${ORG}': 'none'}); render()`);
  check(!app().classList.contains('wsb-on'), '#2389: "No color": a grey stripe');
  w.eval(`S.settings.ws_colors = JSON.stringify({private: 'blue'}); wsSet('private')`); await sleep(400);
  check(app().style.getPropertyValue('--wbd') === '#6d8cff', '#2389: Private: my own choice wins over purple');
  w.eval(`S.settings.ws_colors = '{}'; wsSet('all')`); await sleep(400);
  check(!app().classList.contains('wsb-on'), '#2389: "All": a grey stripe');
  w.eval(`wsSet('private')`); await sleep(300);
  // the setting: "Workspace colour", Private's default = purple
  w.eval(`settingsModal(lmOrgPaneOn() ? 'org' : 'account')`);
  const pane = await until(() => d.querySelector('.wsp-pane'));
  check(pane && pane.querySelector('h5')?.textContent === 'My colour' && /stripe on top of the sidebar/.test(pane.querySelector('.shint')?.textContent || ''), '#2389: the setting is called "My colour" (#3013), the hint names the stripe');
  const pdef = pane?.querySelector('.wsp-row[data-wsp="private"] [data-wspc=""]');
  check(pdef && /accent/.test(pdef.getAttribute('style')) && pdef.getAttribute('aria-label') === 'Default (Kalmido purple)', '#2389: Private\'s default swatch is the accent');
  d.querySelectorAll('.modal').forEach(x => x.remove());
  // CSS: no stripe in the list header, no tint, 4 px / 3 px
  const css = await (await fetch(B + 'static/app.css')).text();
  check(!/#main\.wsc-on #top\{box-shadow/.test(css) && !/#side\.wsp-on\{--wsc/.test(css), '#2389: the list header stripe and the tint are gone (CSS)');
  check(/#side\{border-top:\.25rem solid var\(--wbc\)\}/.test(css) && /#app\.side-rail #top\{box-shadow:inset 0 \.1875rem 0 var\(--wbc\)\}/.test(css), '#2389: 4 px stripe in the sidebar, 3 px on top of the header (rail / phone)');
  check(/@media \(hover:none\)\{ #side \.sbhead \.sbtools\{opacity:1\} \}/.test(css) && /#side \.sbhead:hover \.sbtools,#side \.sbhead:focus-within \.sbtools\{opacity:1\}/.test(css), '#2392: the tools on hover, keyboard focus and touch screens');
  w.close();

  // ================= jsdom: a person without an organisation (P4)
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const FCK = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'}, FCK);
  w = await boot({user: 'frida', hash: 'inbox'}); d = w.document;
  const fb = await until(() => d.querySelector('#kbar .kbsw'), 60);  // 2.152.3 (#2619): the workspace switch moved into the head bar
  check(fb && /Private/.test(fb.querySelector('.wsn')?.textContent || ''), 'P4: without an organisation the head says "Private"');
  check(d.querySelector('#app').classList.contains('wsb-on') && d.querySelector('#app').style.getPropertyValue('--wbd') === 'var(--accent)', 'P4: the purple stripe without an organisation');
  if (fb) click(w, fb);
  check(await until(() => d.querySelector('#pop [role="menuitem"]')), 'P4: the switch still opens');
  w.eval('closePop()');
  w.eval(`settingsModal('account')`);
  const fpane = await until(() => d.querySelector('.wsp-pane .wsp-row[data-wsp="private"]'));
  check(fpane && d.querySelectorAll('.wsp-pane .wsp-row').length === 1, 'P4: the account page offers the colour of Private');
  if (fpane) click(w, fpane.querySelector('[data-wspc="teal"]'));
  check(await until(async () => (await call('GET', '/api/state', null, FCK)).settings.ws_colors === '{"private":"teal"}'), 'P4: a tap stores the colour');
  check(await until(() => d.querySelector('#app').style.getPropertyValue('--wbd') === '#2dd4bf'), 'P4: the stripe follows');
  await call('PATCH', '/api/settings', {ws_colors: '{}'}, FCK);
  w.close();

  // ================= Firefox: 1280 / 1000 rail / 390, dark + light
  const login2 = async ({ev, nav}, theme) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"${theme}"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async ev => { for (let i = 0; i < 40 && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(250); await sleep(800); };
  const GEO = `(() => { const q = s => document.querySelector(s), r = e => e && e.getBoundingClientRect(), sd = r(q('#side')), h = r(q('#side .sbhead')), ws = r(q('#kbar .kbsw') || q('#side .wsbar')), a = r(q('#kbar .kbacct') || q('#side .sbacct')) /* 2.152.3 (#2619): the head bar on a computer, the drawer on a phone */, s = r(q('#kbar .kbsrch') || q('#side .scmd')), nd = r(q('#kbar .netdot') || q('#side .sbhead .netdot'));
    const acc = (() => { const e = document.createElement('div'); e.style.background = 'var(--accent)'; document.body.append(e); const c = getComputedStyle(e).backgroundColor; e.remove(); return c; })();
    return {sdt: sd && Math.round(sd.top), sdw: sd && Math.round(sd.width), sth: parseFloat(getComputedStyle(q('#side')).borderTopWidth), stc: getComputedStyle(q('#side')).borderTopColor, stw: sd && Math.round(sd.width), acc,
      wy: ws && Math.round(ws.top), hy: h && Math.round(h.top), ay: a && Math.round(a.top), sy: s && Math.round(s.top), ndw: nd && nd.width, tools: getComputedStyle(q('#side .sbtools')).opacity,
      top: getComputedStyle(q('#top')).boxShadow, over: document.documentElement.scrollWidth - innerWidth}; })()`;
  for (const theme of ['dark', 'light']) {
    await firefox(async o => {
      const {cmd, ev, ctx, shot} = o;
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 800}});
      check(await login2(o, theme) === 200, `1280 ${theme}: login`);
      await o.nav(B + '#inbox'); await ready(ev);
      await ev(`(() => { document.querySelectorAll('.authscreen').forEach(e => e.remove()); document.querySelector('#app')?.removeAttribute('inert'); return 1; })()`);
      let g = await ev(GEO);
      check(g.sth === 4 && g.stc === g.acc, `1280 ${theme}: #2389 a 4 px stripe in purple across the top of the sidebar ` + JSON.stringify(g));
      check(g.wy < g.sdt && g.ay < g.sdt && Math.abs(g.ay - g.wy) < 20 && Math.abs(g.sy - g.wy) < 20 && !g.ndw && g.over <= 0, `1280 ${theme}: #2392 workspace, search and avatar in the head bar over the panel, no connection dot online ` + JSON.stringify(g));  // 2.152.3 (#2619): workspace, search and account moved into the head bar
      check(g.top === 'none' && +g.tools === 1, `1280 ${theme}: no header stripe while the sidebar is open; the panel head's tools always visible ` + JSON.stringify(g));  // 2.152.3 (#2619): the panel head's tools (fold all, hide) always show in sidebar B
      await ev(`(() => { document.querySelector('#side .sbbfa').focus(); return 1; })()`); await sleep(350);  // 2.152.3 (#2619): fold all = .sbbfa
      // headless Firefox without window focus may not match :focus-within -- then the CSS rule (checked in jsdom) has to do
      const fw = await ev(`(() => ({fw: document.querySelector('#side .sbhead').matches(':focus-within'), op: +getComputedStyle(document.querySelector('#side .sbtools')).opacity}))()`);
      check(!fw.fw || fw.op === 1, `1280 ${theme}: #2392 keyboard focus shows the tools ` + JSON.stringify(fw));
      await ev(`(() => { document.activeElement?.blur(); return 1; })()`);
      await shot(`p21381c-1280-${theme}.png`);
      // an organisation: its colour
      await ev(`(() => { wsSet('org:' + S.me.workspaces[0].id); return 1; })()`); await sleep(700);
      g = await ev(GEO);
      check(g.stc !== g.acc && g.stc !== 'rgba(0, 0, 0, 0)', `1280 ${theme}: #2389 the organisation's colour ` + g.stc);
      await shot(`p21381c-1280-${theme}-org.png`);
      await ev(`(() => { wsSet('private'); return 1; })()`); await sleep(500);
      // the rail (folded away below 1100 px): 3 px on top of the header
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1000, height: 800}});
      await ev(`(() => { sideFold(true); return 1; })()`); await sleep(700);
      g = await ev(GEO);
      check(await ev(`document.querySelector('#app').classList.contains('side-rail')`) && /inset/.test(g.top) && /0px 3px 0px/.test(g.top), `1000 ${theme}: #2389 folded away: a 3 px stripe on top of the header ` + g.top);
      await ev(`(() => { sideFold(false); return 1; })()`); await sleep(300);
    }, false);
    await firefox(async o => {
      const {cmd, ev, ctx, shot} = o;
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
      check(await login2(o, theme) === 200, `390 ${theme}: login`);
      await o.nav(B + '#inbox'); await ready(ev);
      await ev(`(() => { document.querySelectorAll('.authscreen').forEach(e => e.remove()); document.querySelector('#app')?.removeAttribute('inert'); return 1; })()`);
      let g = await ev(GEO);
      check(/inset/.test(g.top) && /0px 3px 0px/.test(g.top) && g.top.includes(g.acc), `390 ${theme}: #2389 a 3 px purple stripe on top of the header ` + g.top);
      await shot(`p21381c-390-${theme}-list.png`);
      await ev(`(() => { document.querySelector('#top [data-act="side"]').click(); return 1; })()`); await sleep(800);
      g = await ev(GEO);
      check(g.sth === 4 && g.stc === g.acc && g.over <= 0, `390 ${theme}: the drawer has the 4 px stripe ` + JSON.stringify(g));
      check(+g.tools === 1 && g.ay > g.wy, `390 ${theme}: #2392 touch screen: the tools stay visible; the avatar at the bottom ` + JSON.stringify(g));
      await shot(`p21381c-390-${theme}-drawer.png`);
    }, true);
  }
  console.log(`p21381_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
