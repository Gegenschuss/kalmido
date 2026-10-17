// 2.38.0 UI tests, part U1 (touch, sheets, zoom), own container (start.sh). jsdom:
// #1178 touch: the browser's menu event on a task title (long press) starts the selection and is cancelled; with a mouse the
//       task's own menu opens instead; the CSS keeps titles unselectable on touch screens only (with the -webkit- prefix)
// #1177 "Move to list…": the Inbox first, then the lists in the sidebar's order, folders as headings with their lists below
//       (a subfolder one step deeper), the current list left out; the same picker for a selection; on a phone the sheet has a
//       head with the title and a 44 px X that closes it (every menu sheet, also the <select> sheet); no head on a desktop
// #1173 the installed app (display-mode standalone): the viewport without user scaling + html.nozoom; a picture (lightbox)
//       lifts it while open; in a browser tab the viewport stays as it is; the hint under Font size only in the app
// #1170 touch: a dialog's foot button does not take the focus from the field being typed in (pointerdown cancelled)
// #1155 the quick-add sheet open, then the drawer, then a view from the drawer: no sheet and no scrim stay; a long press in the
//       sidebar brings no browser menu
// Firefox (390 touch / 1280 mouse): the computed user-select of a task title, the X of a sheet is 44 px.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2380_u1_ui', check, shots: 'P2380U1_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el, o = {}) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const TOUCH = {'(hover: none)': true, '(hover:none)': true, '(pointer:coarse)': true, '(pointer: coarse)': true};

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab'});
  const L = {};
  for (const [name, folder] of [['Alpha', ''], ['Beta', ''], ['Homepage', 'Studio'], ['Shopping', 'Studio/Shop'], ['Zlist', 'Zeta']]) L[name] = (await call('POST', '/api/lists', {name, ...(folder ? {folder} : {})})).id;
  check(Object.values(L).every(Boolean), 'lists in folders and a subfolder ' + JSON.stringify(L));
  const T = (await call('POST', '/api/tasks', {title: 'Long press me please', list_id: L.Alpha})).id;
  const T2 = (await call('POST', '/api/tasks', {title: 'Second task', list_id: L.Alpha})).id;

  // ================= #1178: touch (phone): the menu event of a long press on the title selects the task
  let w = await boot({user: 'alice', hash: 'l/' + L.Alpha, mobile: true, media: TOUCH}), d = w.document;
  await until(() => d.querySelector(`#view .trow[data-id="${T}"] .ttl`));
  let ttl = d.querySelector(`#view .trow[data-id="${T}"] .ttl`);
  let ce = new w.MouseEvent('contextmenu', {bubbles: true, cancelable: true});
  ttl.dispatchEvent(ce);
  check(ce.defaultPrevented, '#1178 touch: no browser menu over a task title');
  await until(() => w.eval('S.multiMode'));
  check(w.eval(`S.multiMode && S.multi.has(${T}) && S.multi.size === 1`), '#1178 touch: the long press on the title starts the selection with this task');
  check(d.querySelector('#pop').classList.contains('hidden'), '#1178 touch: no task menu opens on top');
  // the selection bar's Move: the same list picker (#1177)
  w.eval(`multiMoveMenu(document.querySelector('#top h1') || document.body)`); await sleep(150);
  let heads = [...d.querySelectorAll('#pop .menu-list .mgrp.tch-fd > .mgh')].map(x => x.textContent);
  check(heads.join('|') === 'Studio|Shop|Zeta', '#1177 the selection\'s Move: folders as headings ' + heads.join('|'));
  w.eval('closePop(); S.multiMode = false; S.multi.clear(); render()'); await sleep(150);

  // ================= #1177: the task menu's "Move to list…" on a phone
  w.eval(`taskMenu(document.querySelector('#view .trow[data-id="${T}"]'), ${T})`); await sleep(150);
  check(d.querySelector('#pop .tch-sh .tch-shx[aria-label="Close"]'), '#1177 phone: the task menu sheet has a head with an X');
  const mv = [...d.querySelectorAll('#pop [role="menuitem"]')].find(b => /Move to list/.test(b.textContent));
  check(mv, '#1177 the task menu has "Move to list…"');
  click(w, mv); await sleep(150);
  const pop = d.querySelector('#pop');
  check(!pop.classList.contains('hidden') && pop.querySelector('.tch-sh .tch-sht')?.textContent === 'Move to list', '#1177 the picker sheet is titled "Move to list" ' + pop.querySelector('.tch-sht')?.textContent);
  check(pop.querySelector('.menu-list')?.getAttribute('aria-labelledby') === 'tch-sht', '#1177 the menu is named by its title');
  const rows = [...pop.querySelectorAll('.menu-list > button, .menu-list > .mgrp > .mgh, .menu-list > .mgrp > button')].map(x => x.classList.contains('mgh') ? '#' + x.textContent : x.querySelector('.ml')?.textContent);
  check(rows.join('|') === 'Basket|Beta|#Studio|Homepage|#Shop|Shopping|#Zeta|Zlist', '#1177 Inbox first, the sidebar order, folders as headings, the current list left out: ' + rows.join('|'));
  check(w.eval(`sideOrder().map(l => l.name).filter(n => n !== 'Alpha').join('|')`) === rows.filter(x => x !== 'Basket' && !x.startsWith('#')).join('|'), '#1177 the lists in exactly the sidebar order');
  check(pop.querySelector('.mgrp.tch-fd2 > .mgh')?.textContent === 'Shop' && pop.querySelector('.mgrp.tch-fd2 button .ml')?.textContent === 'Shopping', '#1177 the subfolder is one step deeper');
  check(![...pop.querySelectorAll('.mgh')].some(h => h.closest('button')), '#1177 a folder is only a heading, not a choice');
  click(w, pop.querySelector('.tch-shx')); await sleep(100);
  check(pop.classList.contains('hidden') && d.querySelector('#scrim').classList.contains('hidden'), '#1177 the X closes the sheet and its scrim');
  // a choice moves the task
  w.eval(`moveListItem(document.querySelector('#view .trow[data-id="${T2}"]'), ${T2}).fn()`); await sleep(120);
  const hp = [...pop.querySelectorAll('[role="menuitem"]')].find(b => b.querySelector('.ml')?.textContent === 'Homepage');
  click(w, hp);
  check(await until(async () => (await call('GET', `/api/tasks/${T2}`)).list_id === L.Homepage), '#1177 picking a list moves the task there');
  // the <select> sheet has the same head (its label is the title)
  w.eval(`(() => { const s = document.createElement('select'); s.id = 'u1sel'; s.setAttribute('aria-label', 'Colour'); s.innerHTML = '<option>Red</option><option>Blue</option>'; document.body.appendChild(s); selSheet(s); })()`); await sleep(100);
  check(pop.querySelector('.tch-sh #ss-h')?.textContent === 'Colour' && pop.querySelector('.tch-sh .tch-shx'), '#1177 the select sheet: its label as the title and the X');
  click(w, pop.querySelector('.tch-shx')); await sleep(80);
  check(pop.classList.contains('hidden'), '#1177 the X closes the select sheet');

  // ================= #1170: a foot button keeps the focus in the field (touch)
  w.eval(`window.__md = modal('<h3>Save</h3><input id="u1in"><div class="foot"><button class="btn pri" data-m="ok">Save</button></div>'); document.querySelector('#u1in').focus()`);
  let pd = new w.MouseEvent('pointerdown', {bubbles: true, cancelable: true});
  d.querySelector('.modal [data-m="ok"]').dispatchEvent(pd);
  check(pd.defaultPrevented && d.activeElement?.id === 'u1in', '#1170 touch: Save does not take the focus from the field (no keyboard drop before the click)');
  w.eval('window.__md.remove()');

  // ================= #1155: quick add open, then the drawer, then a view from the drawer: nothing stays on top
  w.eval('openQuickSheet()'); await sleep(80);
  check(d.querySelector('.qadd.sheet') && !d.querySelector('#scrim').classList.contains('hidden'), '#1155 set-up: the quick-add sheet with its scrim');
  click(w, d.querySelector('#top [data-act="side"]')); await sleep(150);
  check(d.querySelector('#side.open'), '#1155 set-up: the drawer opens over it');
  const today = d.querySelector('#side [data-go="today"]');
  click(w, today); await until(() => w.eval('S.route.key') === 'today'); await sleep(200);
  check(!d.querySelector('.qadd.sheet') && d.querySelector('#scrim').classList.contains('hidden') && !d.querySelector('#side.open'), '#1155 a view opened from the drawer: no sheet, no scrim left over it');
  // the sidebar: a touch long press brings no browser menu
  const srow = d.querySelector(`#side .srow[data-list="${L.Beta}"]`);
  ce = new w.MouseEvent('contextmenu', {bubbles: true, cancelable: true}); Object.defineProperty(ce, 'pointerType', {value: 'touch'});
  srow.dispatchEvent(ce);
  check(ce.defaultPrevented, '#1155 touch: no browser menu on a sidebar entry (the app\'s long press handles it)');
  w.eval('closePop()');
  w.close();

  // ================= #1178 / #1177 desktop with a mouse: the task's own menu, no sheet head
  w = await boot({user: 'alice', hash: 'l/' + L.Alpha}); d = w.document;
  await until(() => d.querySelector(`#view .trow[data-id="${T}"] .ttl`));
  ce = new w.MouseEvent('contextmenu', {bubbles: true, cancelable: true});
  d.querySelector(`#view .trow[data-id="${T}"] .ttl`).dispatchEvent(ce);
  await sleep(120);
  check(!w.eval('S.multiMode') && !d.querySelector('#pop').classList.contains('hidden') && d.querySelectorAll('#pop [role="menuitem"]').length > 3, '#1178 mouse: right-click on the title opens the task menu, no selection');
  check(!d.querySelector('#pop .tch-sh'), '#1177 desktop: menus have no sheet head');
  w.eval('closePop()');
  w.eval(`window.__md = modal('<h3>Save</h3><input id="u1in"><div class="foot"><button class="btn pri" data-m="ok">Save</button></div>'); document.querySelector('#u1in').focus()`);
  pd = new w.MouseEvent('pointerdown', {bubbles: true, cancelable: true});
  d.querySelector('.modal [data-m="ok"]').dispatchEvent(pd);
  check(!pd.defaultPrevented, '#1170 mouse: the foot buttons behave as before');
  w.eval('window.__md.remove()');
  // #1173: a browser tab: the viewport as it is, no lock
  const vp0 = d.querySelector('meta[name="viewport"]').getAttribute('content');
  check(!/user-scalable|maximum-scale/.test(vp0) && !d.documentElement.classList.contains('nozoom'), '#1173 browser tab: zooming stays allowed ' + vp0);
  w.close();

  // ================= #1173: the installed app
  w = await boot({user: 'alice', hash: 'l/' + L.Alpha, mobile: true, media: {...TOUCH, '(display-mode: standalone)': true}}); d = w.document;
  await until(() => d.querySelector('#view .trow'));
  const vp = () => d.querySelector('meta[name="viewport"]').getAttribute('content');
  check(/maximum-scale=1, user-scalable=no$/.test(vp()) && /^width=device-width/.test(vp()), '#1173 installed app: the viewport without user scaling ' + vp());
  check(d.documentElement.classList.contains('standalone') && d.documentElement.classList.contains('nozoom'), '#1173 installed app: html.standalone + html.nozoom');
  w.eval(`(() => { const m = document.createElement('div'); m.className = 'lightbox'; m.id = 'u1lb'; document.body.appendChild(m); })()`);
  await until(() => !d.documentElement.classList.contains('nozoom'));
  check(!/user-scalable/.test(vp()) && !d.documentElement.classList.contains('nozoom'), '#1173 a picture is open: pinching works again ' + vp());
  w.eval(`document.querySelector('#u1lb').remove()`);
  await until(() => d.documentElement.classList.contains('nozoom'));
  check(/user-scalable=no/.test(vp()), '#1173 the picture closed: locked again');
  w.eval(`settingsModal('look')`); await sleep(400);
  check([...d.querySelectorAll('.smodal .shint')].some(x => /two fingers is off/.test(x.textContent)), '#1173 the hint under Font size in the installed app');
  w.close();

  // ================= CSS (static): the touch rule, the zoom lock, the sheet head
  const css = await require('./boot').allCss(); // 2.65.0 (#1824): + the module stylesheets
  const tb = css.match(/@media \(hover: none\), \(pointer: coarse\)\{([^}]*\}[^}]*\})/);
  check(tb && /\.trow \.ttl/.test(tb[1]) && /-webkit-user-select:none/.test(tb[1]) && /-webkit-touch-callout:none/.test(tb[1]) && /#side/.test(tb[1]), '#1178 / #1155 one touch rule: titles and the sidebar not selectable, with the -webkit- prefix');
  check(/\.trow \.ttl\{-webkit-user-select:text;user-select:text\}/.test(css), '#1178 mouse: the title stays selectable');
  check(/html\.nozoom,html\.nozoom body\{touch-action:pan-x pan-y\}/.test(css), '#1173 html.nozoom: pan only');
  check(/\.tch-shx\{[^}]*width:2\.75rem;height:2\.75rem/.test(css), '#1177 the X is 44 px');

  // ================= Firefox: computed styles on a touch screen and with a mouse
  const ffLogin = async o => { await o.nav(B + 'static/icon.svg'); await o.ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`); return o.ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`); };
  const ready = async ev => { for (let i = 0; i < 40; i++) { if (await ev(`!!document.querySelector('#view .trow .ttl')`).catch(() => false)) return; await sleep(250); } };
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o;
    check(await ffLogin(o) === 200, '390 touch: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + '#l/' + L.Alpha); await ready(ev); await sleep(500);
    check(await ev(`getComputedStyle(document.querySelector('#view .trow .ttl')).userSelect`) === 'none', '#1178 390 touch: the title is not selectable');
    await ev(`(() => { taskMenu(document.querySelector('#view .trow'), +document.querySelector('#view .trow').dataset.id); return 1; })()`); await sleep(400);
    // 2.39.1 (#1181): on touch the X is out of sight (a swipe down closes the sheet); it stays for screen readers and the keyboard
    check(await ev(`(() => { const x = document.querySelector('#pop .tch-shx'), r = x?.getBoundingClientRect(); return !!x && !!x.getAttribute('aria-label') && (r.width >= 44 && r.height >= 44 && r.top >= 0 || getComputedStyle(x).clipPath !== 'none'); })()`), '#1177 390: the X of the sheet is there (44 px, or out of sight on touch since #1181)');
    await ev(`(() => { [...document.querySelectorAll('#pop [role="menuitem"]')].find(b => /Move to list/.test(b.textContent)).click(); return 1; })()`); await sleep(400);
    await shot('p2380u1-390-move-to-list.png');
    await ev(`(() => { document.querySelector('#pop .tch-shx').click(); return 1; })()`);
  }, true);
  await firefox(async o => {
    const {cmd, ev, ctx} = o;
    check(await ffLogin(o) === 200, '1280 mouse: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await o.nav(B + '#l/' + L.Alpha); await ready(ev); await sleep(500);
    check(await ev(`getComputedStyle(document.querySelector('#view .trow .ttl')).userSelect`) === 'text', '#1178 1280 mouse: the title stays selectable');
  }, false);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
