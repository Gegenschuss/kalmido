// 2.220.0 B (#2807) UI tests: the sidebar gives a project's name the whole row: the number sits at the right edge, the
// room of the progress ring / share columns only while the row is hovered or focused, the full name as a tooltip; a project
// in a folder ("Großprojekt Tausend") stays readable; the words of the area bar wrap instead of "Gewohnh…".
// Computer (1280 / 1440 / 1920, mouse) and phone (390, touch drawer). Own container (start.sh), Firefox.
// freelancer-matrix: n/a (no new route; frida without an organisation is checked with the same rows)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2220_b_side_ui', check, shots: 'P2220B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2220B_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return Array.isArray(j) ? j : {...j, http: r.status}; };
const MODS = 'cal,comments,office,contacts,wiki,time,pomo,review,stats,agents,habits';
const LONG = 'Großprojekt Tausend';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'de', collab_all: true, time_all: true, modules: MODS.split(',')});
  await call(CA, 'PATCH', '/api/settings', {lang: 'de', tour: 'done', features: MODS + ',collab'});
  const BOB = (await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'})).id;
  const fr = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com'});
  check(fr.http < 300, 'P4: frida (no organisation) ' + fr.http);
  const L = {};
  // 2 levels of folders, a long name in each, a shared project (the share columns), done tasks (the progress ring)
  for (const [n, f] of [['Ideen', ''], ['Erste Schritte', ''], [LONG, 'Arbeit'], ['Haushalt', 'Arbeit'], ['Website-Relaunch Herbst', 'Arbeit/Kunden']]) {
    L[n] = (await call(CA, 'POST', '/api/lists', {name: n})).id;
    if (f) await call(CA, 'PATCH', `/api/lists/${L[n]}`, {folder: f});
    for (let i = 0; i < 3; i++) {
      const t = await call(CA, 'POST', '/api/tasks', {title: `${n} ${i}`, list_id: L[n]});
      if (i === 0) await call(CA, 'POST', `/api/tasks/${t.id}/complete`, {});
    }
  }
  await call(CA, 'PATCH', '/api/settings', {folders: JSON.stringify(['Arbeit', 'Arbeit/Kunden'])});
  await call(CA, 'PUT', `/api/lists/${L['Erste Schritte']}/members`, {user_id: BOB, role: 'edit'});

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = async (o, u) => {
    await o.nav(B + 'static/icon.svg');
    await o.ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"dark"'); return 1; })()`);
    return o.ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  };
  // the project rows: the name's room, whether it is cut, the tooltip, the gap to the row's right edge
  const ROWS = `(() => { const R = el => el.getBoundingClientRect();
    return [...document.querySelectorAll('#side .srow[data-list], #side .srow[data-drop="week"], #side .srow[data-drop="doable"], #side .srow[data-drop="today"]')].filter(r => r.offsetParent).map(r => { const n = r.querySelector('.n'), c = r.querySelector('.c'), rr = R(r);
      const ends = [...r.children].filter(x => x !== n && x.offsetParent && getComputedStyle(x).visibility !== 'hidden' && +getComputedStyle(x).opacity > 0).map(x => R(x).right);
      r.dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
      return {name: n.textContent, shk: !!r.querySelector('.shk svg'), cut: n.scrollWidth > n.clientWidth + 1, nw: Math.round(n.clientWidth), sw: n.scrollWidth, row: Math.round(rr.width),
        cRight: c && c.textContent ? Math.round(rr.right - R(c).right) : null, gap: Math.round(rr.right - Math.max(R(n).right, ...ends)), tip: r.title || n.title || ''}; }); })()`;
  const RAIL = `[...document.querySelectorAll('#srail .srb .srbn')].filter(x => x.offsetParent).map(x => ({t: x.textContent, cut: x.scrollWidth > x.clientWidth + 1 || x.scrollHeight > x.clientHeight + 1, h: Math.round(x.getBoundingClientRect().height)}))`;

  await firefox(async o => {
    const {cmd, ev, ctx, nav, shot} = o;
    check(await signIn(o, 'alice') === 200, 'alice: login');
    for (const w of [1280, 1440, 1920]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: w, height: 900}});
      await nav(B + '#today');
      await ready(ev, `!!S.booted && !!document.querySelector('#side .srow[data-list]')`, 80);
      await ev(`(() => { document.querySelectorAll('#side .fhead.closed').forEach(h => h.click()); return 1; })()`);
      await sleep(500);
      const rows = (await ev(ROWS)) || [];
      console.log(`rows ${w}:`, JSON.stringify(rows));
      const rail = (await ev(RAIL)) || [];
      console.log(`rail ${w}:`, JSON.stringify(rail));
      await shot(`p2220b-side-${w}.png`);
      const big = rows.find(r => r.name === LONG);
      check(big && !big.cut, `${w}: "${LONG}" in its folder is not cut ` + JSON.stringify(big));
      for (const r of rows.filter(x => x.cut)) check(r.tip.includes(r.name), `${w}: a cut name has its full name as tooltip ` + JSON.stringify(r));
      check(rows.filter(r => r.cRight != null && !r.shk).every(r => r.cRight <= 12), `${w}: the number sits at the right edge ` + JSON.stringify(rows.map(r => [r.name, r.cRight])));
      check(rows.filter(r => !r.shk).every(r => r.gap <= 12), `${w}: no empty room at the end of a row without a share symbol ` + JSON.stringify(rows.map(r => [r.name, r.gap])));
      check(rows.some(r => r.shk && r.gap <= 12), `${w}: a shared project keeps its share symbol at the end (#1797) ` + JSON.stringify(rows.map(r => [r.name, r.shk, r.gap])));
      // the ring: hidden at rest, there while the mouse is over the row
      const RING = `(() => { const r = [...document.querySelectorAll('#side .srow[data-list]')].find(x => x.querySelector('.o3c-ring')); if (!r) return null; const b = r.getBoundingClientRect();
        return {vis: !!r.querySelector('.o3c-ring').getClientRects().length, x: Math.round(b.left + 20), y: Math.round(b.top + b.height / 2)}; })()`;
      const r0 = (await ev(RING)) || {};
      if (r0.x) await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'm', parameters: {pointerType: 'mouse'}, actions: [{type: 'pointerMove', x: r0.x, y: r0.y}]}]});
      await sleep(200);
      const r1 = (await ev(RING)) || {};
      if (w === 1280) await shot('p2220b-side-hover-1280.png');
      await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'm', parameters: {pointerType: 'mouse'}, actions: [{type: 'pointerMove', x: w - 40, y: 600}]}]});
      await cmd('input.releaseActions', {context: ctx});
      check(r0.x && !r0.vis && r1.vis, `${w}: the progress ring takes room only while the mouse is over the row ` + JSON.stringify([r0, r1]));
      check(rail.length > 3 && rail.every(x => !x.cut), `${w}: the words of the area bar are whole ` + JSON.stringify(rail.filter(x => x.cut)));
    }
    // #2809 with real keys (1280): the button opens "New project" / "More actions" with the focus on the first entry, Tab closes the
    // menu and the focus moves on from its button (not to the page's end), Shift+Tab goes back to it
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + '#l/' + L.Ideen); await ready(ev, `!!S.booted && !!document.querySelector('[data-act="top-more"]') && !!document.querySelector('#side [data-act="list-new"]')?.getClientRects().length`, 80); await sleep(400);  // the sidebar drawn too (a busy runner: its button was not there yet)
    const press = (...ks) => cmd('input.performActions', {context: ctx, actions: [{type: 'key', id: 'kb', actions: ks.flatMap(k => Array.isArray(k) ? [{type: 'keyDown', value: k[0]}, {type: 'keyDown', value: k[1]}, {type: 'keyUp', value: k[1]}, {type: 'keyUp', value: k[0]}] : [{type: 'keyDown', value: k}, {type: 'keyUp', value: k}])}]});
    const AE = `(() => { const a = document.activeElement; return {tag: a?.tagName, act: a?.dataset?.act || '', item: a?.getAttribute('role') === 'menuitem', txt: (a?.textContent || '').trim().slice(0, 30), side: !!a?.closest('#side'), pop: !document.querySelector('#pop').classList.contains('hidden'), name: document.querySelector('#pop [role="menu"]')?.getAttribute('aria-label') || '', body: a === document.body, next: !!a && (a === window.__trg || a === window.__nxt), nxt: (window.__nxt?.textContent || '').trim().slice(0, 20), rs: !!a?.closest('.pgrip')}; })()`;
    for (const [sel, nm] of [['#side [data-act="list-new"]', 'New project'], ['[data-act="top-more"]', 'More actions']]) {
      // the button activated like a keyboard does (focus on it, a click without a pointer; a synthetic Enter does not activate
      // buttons in headless Firefox), the keys after that are real
      // the visible copy of the button, once no menu is open; the sidebar is one tab stop (#453: roving tabindex, the button is
      // tabindex -1 until it gets the focus). Nachrücken #1179: headless Firefox on a busy runner sometimes fires no focusin for
      // b.focus() when its window lost the focus - then the button stayed -1, out of the tab order, and Tab had nothing to go on
      // from; the window gets the focus first, a focusin like a focused window's is the fallback
      await cmd('browsingContext.activate', {context: ctx}).catch(() => null);
      const VIS = `[...document.querySelectorAll('${sel}')].find(e => e.getClientRects().length && !e.disabled && !e.closest('#pop'))`;
      check(await ready(ev, `!!(${VIS}) && document.querySelector('#pop').classList.contains('hidden')`, 80), `#2809 ${nm}: the button is there`);
      await ev(`(() => { const b = ${VIS}; window.__trg = b; b.focus();
        if (document.activeElement === b && b.tabIndex < 0) b.dispatchEvent(new FocusEvent('focusin', {bubbles: true}));
        return 1; })()`);
      check(await ready(ev, `document.activeElement === window.__trg && window.__trg.tabIndex === 0`, 20), `#2809 ${nm}: the button has the focus and is the sidebar's tab stop`);
      await ev(`(() => { const b = window.__trg;
        const tb = [...document.querySelectorAll('a[href], button, input, select, textarea, [tabindex]')].filter(e => e.tabIndex >= 0 && !e.disabled && e.getClientRects().length && !e.closest('#pop'));
        window.__nxt = tb[tb.indexOf(b) + 1] || tb[0]; b.click(); return 1; })()`);
      await ready(ev, `!document.querySelector('#pop').classList.contains('hidden') && document.activeElement?.getAttribute('role') === 'menuitem'`, 40);
      const o = (await ev(AE)) || {};
      check(o.pop && o.item && o.name, `#2809 ${nm}: the menu opens, the first entry has the focus, the menu a name ` + JSON.stringify(o));
      await press('\uE004'); await ready(ev, `document.querySelector('#pop').classList.contains('hidden') && document.activeElement !== document.body`, 20);
      const t = (await ev(AE)) || {};
      // not to the page's end (the panel grips .pgrip at the end of the body, then the body) as in audit C
      check(!t.pop && !t.body && !t.rs && !t.item, `#2809 ${nm}: Tab closes the menu, the focus goes on from its button ` + JSON.stringify(t));
      await press(['\uE008', '\uE004']); await sleep(200);
      const b = (await ev(AE)) || {};
      console.log(nm, 'after Tab:', JSON.stringify(t), 'Shift+Tab:', JSON.stringify(b));
    }
    // #2809 News: the window gets the focus (a real click on the bell)
    const bell = await ev(`(() => { const b = document.querySelector('#kbar .bell, #top .bell'); if (!b) return null; const r = b.getBoundingClientRect(); return {x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2)}; })()`);
    if (bell) {
      await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'm', parameters: {pointerType: 'mouse'}, actions: [{type: 'pointerMove', x: bell.x, y: bell.y}, {type: 'pointerDown', button: 0}, {type: 'pointerUp', button: 0}]}]});
      await cmd('input.releaseActions', {context: ctx});
      await sleep(1200);
      const n = await ev(`(() => ({in: !!document.activeElement?.closest('#pop .bpop'), what: document.activeElement?.outerHTML?.slice(0, 60)}))()`);
      check(n && n.in, '#2809 News: the focus is in the window ' + JSON.stringify(n));
      await shot('p2220b-news-1280.png');
    }
  }, false);

  await firefox(async o => {
    const {cmd, ev, ctx, nav, shot} = o;
    check(await signIn(o, 'alice') === 200, 'alice: login (phone)');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + '#today');
    await ready(ev, `!!S.booted && !!document.querySelector('#top .menu')`, 80);
    await ev(`(() => { if (!document.querySelector('#side.open')) document.querySelector('#top .menu')?.click(); return 1; })()`);
    await ready(ev, `!!document.querySelector('#side.open')`, 20);
    await ev(`(() => { document.querySelectorAll('#side .fhead.closed').forEach(h => h.click()); return 1; })()`);
    await sleep(800);
    const rows = (await ev(ROWS)) || [];
    console.log('rows 390:', JSON.stringify(rows));
    await shot('p2220b-side-390.png');
    const big = rows.find(r => r.name === LONG);
    check(big && !big.cut, `390: "${LONG}" in its folder is not cut ` + JSON.stringify(big));
  }, true);

  console.log(`p2220_b_side_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
