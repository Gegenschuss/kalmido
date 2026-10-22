// 2.53.0 UI tests, part C (#1424 the bell of one task), own container (start.sh). jsdom:
// - the task menu "…" has "Notifications for this task…" (a header button only while it is not "As the list"); the bell menu offers As the list / Muted / Urgent until completed / Urgent until a
//   date, with the honest hint (Android / ntfy comes through, the iPhone web app cannot break through Focus)
// - "Urgent until completed" saves, the button shows "Urgent"; ONE undo step puts it back
// - the list's owner gets "Urgent for others…": ticking Bob marks him (server), Bob sees "Urgent, set by Alice";
//   a member has no "for others"
// - the history line and the News text (counts only), Settings > Notifications: "Accept urgent markings from others" saves
// - phone: the menu is a sheet with its head
// - Firefox (real layout): the task header with the urgent bell has no sideways overflow at 360 / 390 / 1280 px, the menu
//   with its hint fits the screen
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p253_c_ui', check, shots: 'P253C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P253C_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const items = d => [...d.querySelectorAll('#pop [role="menuitem"]')];
const item = (d, re) => items(d).find(b => re.test(b.textContent));

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'})).id;
  const CB = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'}, CB);
  const L = (await call('POST', '/api/lists', {name: 'Launch'})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: BOB, role: 'edit'});
  const T = (await call('POST', '/api/tasks', {title: 'Press release', list_id: L})).id;

  // ---- desktop, the owner
  const booted = w => until(() => w.eval(`typeof S !== 'undefined' && !!S.booted && typeof meEnd === 'function' && typeof tbl_btnHtml === 'function'`), 80);
  let w = await boot({user: 'alice', hash: `l/${L}`}), d = w.document;
  await booted(w);
  w.eval(`openDetail(${T})`);
  await until(() => d.querySelector(`#detail [data-tblph="${T}"]`) && w.eval(`!!S.tbl && !!S.tbl[${T}]`));
  check(!d.querySelector(`#detail [data-tblb="${T}"]`), 'as the list: no extra button in the crowded task header');
  w.eval(`taskMenu(document.querySelector('#detail .dtop [data-act="task-menu"]'), ${T})`);
  const mi = await until(() => item(d, /Notifications for this task…/));
  check(!!mi, 'the task menu "…" has "Notifications for this task…"');
  click(w, mi);
  check(await until(() => items(d).length >= 5 && item(d, /^Muted$/)), 'it opens the bell menu');
  // 2.152.2 (#2624): project instead of list
  check(item(d, /^As the project$/) && item(d, /^Muted$/) && item(d, /Urgent until completed/) && item(d, /Urgent until a date/), 'menu: the four choices ' + items(d).map(b => b.textContent.trim()).join(' | '));
  const hint = items(d).find(b => b.classList.contains('tbl-hint'));
  check(hint && /Android \(ntfy\)/.test(hint.textContent) && /iPhone/.test(hint.textContent) && /not an alarm/.test(hint.textContent), 'menu: the honest hint about Android / iPhone');
  check(!!item(d, /Urgent for others/), 'owner: "Urgent for others…"');
  click(w, item(d, /Urgent until completed/));
  check(await until(async () => (await call('GET', `/api/tasks/${T}/bell`)).mine?.level === 'urgent'), 'urgent saved on the server');
  check(await until(() => d.querySelector(`[data-tblb="${T}"].lv-urgent`)), 'the button shows urgent');
  check(/Urgent/.test(d.querySelector(`[data-tblb="${T}"]`)?.textContent || ''), 'the button says "Urgent"');
  await w.eval(`histStep('undo')`);
  check(await until(async () => (await call('GET', `/api/tasks/${T}/bell`)).mine?.level === 'list'), 'one undo step: back to as the list');
  check(await until(() => !d.querySelector(`[data-tblb="${T}"]`) && d.querySelector(`[data-tblph="${T}"]`)), 'undo: the button goes again');

  // ---- for others: tick Bob in the dialog
  w.confirm = () => { const x = d.querySelector(`.cdlg [data-tblp="${BOB}"]`); if (x) x.checked = true; return true; };
  w.eval(`tbl_menu(document.querySelector('#detail .dtop'), ${T})`);
  await until(() => item(d, /Urgent for others/));
  click(w, item(d, /Urgent for others/));
  check(await until(async () => (await call('GET', `/api/tasks/${T}/bell`, null, CB)).mine?.level === 'urgent', 60), 'for others: Bob is marked urgent');
  const jb = await call('GET', `/api/tasks/${T}/bell`, null, CB);
  check(jb.mine?.by_name === 'Alice' && !jb.people && !jb.can_others, 'Bob: set by Alice, no people, no "for others"');
  const line = w.eval(`tbl_actText({level: 'urgent', n: 1}, '<b>Alice</b>')`);
  check(/Alice<\/b> marked the task urgent for 1 person/.test(line), 'history line: count only ' + line);
  check(/marked a task urgent for you/.test(w.eval(`tbl_newsText({data: {}}, '<b>Alice</b>')`)), 'News text');
  // Settings > Notifications
  w.eval(`settingsModal('notify')`);
  const acc = await until(() => d.querySelector('.smodal #s-tblacc'));
  check(acc && acc.checked, 'Settings: "Accept urgent markings from others" on by default');
  if (acc) { acc.checked = false; acc.dispatchEvent(new w.Event('change', {bubbles: true})); }
  check(await until(async () => (await call('GET', '/api/state')).settings?.tbl_accept === '0'), 'the switch saves tbl_accept');
  w.close();

  // ---- Bob: sees the marking; phone sheet
  w = await boot({user: 'bob', hash: `l/${L}`, mobile: true}); d = w.document;
  await booted(w);
  w.eval(`openDetail(${T})`);
  const bb = await until(() => d.querySelector(`#detail [data-tblb="${T}"].lv-urgent`));
  check(bb && /Urgent, set by Alice/.test(bb.getAttribute('aria-label') || ''), 'Bob: the button says "Urgent, set by Alice"');
  click(w, bb);
  check(await until(() => d.querySelector('#pop.sheet .tch-sh') && items(d).length), 'phone: the menu is a sheet with its head');
  check(items(d).some(b => /Urgent, set by Alice/.test(b.textContent)) && !item(d, /Urgent for others/), 'Bob: the state line, no "for others"');
  click(w, item(d, /^As the project$/));  // 2.152.2 (#2624): project instead of list
  check(await until(async () => (await call('GET', `/api/tasks/${T}/bell`, null, CB)).mine?.level === 'list'), 'Bob switches it off for himself');
  w.close();

  // ---- Firefox: the real layout of the header with the urgent bell (Bob is urgent again)
  await call('PUT', `/api/tasks/${T}/bell`, {level: 'urgent', users: [BOB]});
  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const over = `(() => { const d = document.getElementById('detail'); const W = document.documentElement.clientWidth; return {sw: d.scrollWidth, cw: d.clientWidth, out: [...d.querySelectorAll('.dtop > *')].filter(e => e.offsetWidth && e.getBoundingClientRect().right > Math.min(W, d.getBoundingClientRect().right) + 0.5).length}; })()`;
  for (const [W, touch] of [[360, true], [390, true], [1280, false]]) {
    await firefox(async ({cmd, ev, ctx, nav, shot}) => {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: W, height: W < 500 ? 800 : 900}});
      await nav(B + 'static/icon.svg');
      await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
      await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'bob', password: 'password123'})}).then(r => r.status)`);
      await nav(B + `#l/${L}`);
      await ready(ev, `typeof S !== 'undefined' && !!S.booted && typeof tbl_btnHtml === 'function'`, 80);
      await ev(`(() => { openDetail(${T}); return 1; })()`);
      check(await ready(ev, `!!document.querySelector('#detail [data-tblb="${T}"].lv-urgent')`), `${W}px: the urgent bell in the header`);
      await sleep(400);
      const o = await ev(over);
      check(o.sw <= o.cw && o.out === 0, `${W}px: the header has no sideways overflow ${JSON.stringify(o)}`);
      await shot(`p253-c-head-${W}.png`);
      await ev(`(() => { document.querySelector('#detail [data-tblb="${T}"]').click(); return 1; })()`);
      check(await ready(ev, `!!document.querySelector('#pop .tbl-hint')`), `${W}px: the menu opens with the hint`);
      const m = await ev(`(() => { const p = document.querySelector('#pop').getBoundingClientRect(), h = document.querySelector('#pop .tbl-hint').getBoundingClientRect(); return {l: p.left, r: p.right, hr: h.right, vw: document.documentElement.clientWidth}; })()`);
      check(m.l >= 0 && m.r <= m.vw + 1 && m.hr <= m.vw + 1, `${W}px: the menu and its hint fit the screen ${JSON.stringify(m)}`);
      await shot(`p253-c-menu-${W}.png`);
    }, touch);
  }
  console.log(`p253_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
