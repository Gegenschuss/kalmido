// kalmido-suite: fresh
// 2.501.0 (#4282) UI: every point of the office menu opens its own page by a real mouse click (tests/ff.js realClick) at computer and
// phone width: the address, the page's heading, no dialog of something else, no message. A script click notices none of that when
// a dialog lies in front (622 of 746 UI files click by script), and #4058 (every menu click opened the e-mail signature) stayed unseen.
// Own container (start.sh), Firefox, the modules load on demand as for a person (lazy). Invented accounts only.
// freelancer-matrix: office (frida without an organisation clicks the same menu)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const ffmod = require('./ff');
const firefox = ffmod({tag: 'p2501_c_ofmclick_ui', check, shots: 'P2501C_SHOTS', lazy: true});
const {realClick} = ffmod;
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2501C_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
const MODS = 'cal,comments,office,clients,contacts,wiki,time,pomo,review,stats,agents';
// always in the menu of the admin of an office: without them the loop below would prove nothing
const CORE = ['offers', 'invoices', 'clients', 'contacts', 'bank', 'books', 'receipts', 'settings'];
// what is on the screen after a click: the dialogs, the message, the page's heading (a computer: the h1; a phone: the marked tab of the page's strip or its path line)
const SCREEN = `(() => { const vis = e => !!e && e.getClientRects().length > 0;
  const t = document.querySelector('#toast');
  const heads = [...document.querySelectorAll('#view h1, #view h2, #view [aria-current="page"], #view .on[data-go], #view .ofpback, #top h1')].filter(vis).map(e => e.textContent.trim().replace(/\\s+/g, ' ')).filter(Boolean);
  return {hash: location.hash, modals: [...document.querySelectorAll('.modal')].filter(vis).filter(m => !m.querySelector('.smodal') && !m.classList.contains('smodal')).map(m => (m.querySelector('h1, h2, h3, .mhead')?.textContent || m.className).trim().slice(0, 60)),
    settings: !!document.querySelector('.smodal #s-biz #ofc-set'), toast: t && !t.classList.contains('hidden') ? t.textContent.trim().slice(0, 120) : '', heads: heads.slice(0, 6),
    errs: (window.__errs4282 || []).slice(0, 3)}; })()`;
// the points of the menu as the app itself lists them
const ITEMS = `ofm_items().map(i => ({key: i.key, go: i.go, name: tr(i.name)}))`;

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: MODS.split(',')});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: MODS + ',collab'});
  const fr = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com'});
  check(fr.http < 300, 'setup: frida (no organisation) ' + fr.http);
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: MODS});

  const run = async (o, who, w, h, phone) => {
    const {cmd, ev, ctx, nav, until, idle, shot} = o, tag = `${who} ${w}px`;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: w, height: h}});
    const fresh = async () => {
      await nav(B + 'static/icon.svg');
      await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.sbbUnfold', '["office:money","office:sell","office:book","office:admin"]'); return 1; })()`);
      await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${who}', password: 'password123'})}).then(r => r.status)`);
      await nav(B + '#office/offers');
      await until(`typeof ofm_items === 'function' && S.route.mod === 'office' && !document.querySelector('#boot:not(.out)')`, {timeout: 30000});
      await ev(`(() => { window.__errs4282 = []; addEventListener('error', e => window.__errs4282.push(String(e.message))); addEventListener('unhandledrejection', e => window.__errs4282.push(String(e.reason))); return 1; })()`);
      await idle();
    };
    // on a phone the drawer holds the menu: open it by the real menu button first
    const reveal = async key => {
      const sel = `#side [data-ofm="${key}"]`;
      if (phone && !await ev(`!!document.querySelector('#side.open')`)) {
        const m = await realClick(o, '#top .menu');
        check(m.ok, `${tag}: the menu button takes the click (${m.on})`);
        check(await until(`!!document.querySelector('#side.open')`), `${tag}: the drawer opens`);
      }
      if (!await until(`!!document.querySelector(${JSON.stringify(sel)})`, {timeout: 5000})) {  // another area's panel: to the office first
        await ev(`(() => { document.querySelector('#side [data-sbb="office"]')?.click(); return 1; })()`);
        await until(`!!document.querySelector(${JSON.stringify(sel)})`);
      }
      return sel;
    };
    await fresh();
    const items = await ev(ITEMS);
    const keys = items.map(i => i.key);
    check(CORE.every(k => keys.includes(k)), `${tag}: the menu has the core points: ${keys}`);
    console.log(`${tag}: ${items.length} points: ${keys.join(' ')}`);
    await shot(`${who}-${w}-start.png`);
    for (const it of items) {
      const sel = await reveal(it.key);
      const cl = await realClick(o, sel);
      check(cl.ok, `${tag} ${it.key}: the point itself takes the click, not ${cl.on}`);
      const isSet = it.key === 'settings';
      // the page is there when the app routed to it and its loading is over; a stray dialog comes after a request (#4058), so idle first
      const there = await until(isSet ? `!!document.querySelector('.smodal #s-biz #ofc-set')` : `location.hash === ${JSON.stringify('#' + it.go)}`, {timeout: 15000});
      await idle();
      const s = await ev(SCREEN);
      check(there, `${tag} ${it.key}: opens ${it.go}: ${s.hash} ${isSet ? 'settings ' + s.settings : ''}`);
      check(s.modals.length === 0, `${tag} ${it.key}: no dialog of something else: ${JSON.stringify(s.modals)}`);  // the settings window itself does not count
      check(!s.toast, `${tag} ${it.key}: no message: ${s.toast}`);
      check(!s.errs.length, `${tag} ${it.key}: no script error: ${JSON.stringify(s.errs)}`);
      if (!isSet) check(s.heads.some(t => t.includes(it.name)), `${tag} ${it.key}: the heading names ${it.name}: ${JSON.stringify(s.heads)}`);
      if (phone && !isSet) check(!await ev(`!!document.querySelector('#side.open')`), `${tag} ${it.key}: the drawer closed`);
      await shot(`${who}-${w}-${it.key}.png`);
      if (s.modals.length || isSet) await fresh();
    }
  };

  await firefox(async o => {
    for (const who of ['alice', 'frida']) {
      await run(o, who, 1440, 900, false);
      await run(o, who, 390, 844, true);
    }
  }, false);

  // the helper itself: a dialog in front of the element is what it reports, and the click does not reach the element
  await firefox(async o => {
    const {ev, nav, until} = o;
    await nav('about:blank');
    await ev(`(() => { document.body.innerHTML = '<button id="under" onclick="window.__hit = 1" style="position:fixed;left:50px;top:50px;width:100px;height:50px">x</button><div id="over" style="position:fixed;inset:0"></div>'; return 1; })()`);
    const a = await realClick(o, '#under');
    check(!a.ok && /#over/.test(a.on), `realClick reports what lies in front: ${a.on}`);
    check(!await ev(`!!window.__hit`), 'a covered element gets no click and the cover none either (a script click would have reached it)');
    await ev(`(() => { document.getElementById('over').remove(); return 1; })()`);
    const b = await realClick(o, '#under');
    check(b.ok && await until(`!!window.__hit`), `an open element gets the real click: ${b.on}`);
    check(!(await realClick(o, '#nothing-here')).ok, 'no element: not ok');
  }, false);

  console.log(`p2501_c_ofmclick_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error('Error', e); process.exit(1); });
