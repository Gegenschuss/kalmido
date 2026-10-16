// 2.38.0 UI tests, part U2 (#1174 #1132 #1171), own container (start.sh). jsdom:
// - list icons (#1174): listIconHtml draws the line icon in the list colour (no extra dot), the plain list icon for a list
//   without an emoji, emoji / picture on a tile tinted in the list colour, grey without a colour, the round dot with the
//   setting "Dot"; the same in the sidebar, the header and the menus; the light theme's darker colour (licDim) keeps >= 3:1
// - multi-edit (#1132): a change over a locked and a free task changes the free one and says how many locked were skipped
// - chat (#1171): the part mark "_(Part 2/2)_" of a split answer in italics, other underscores untouched; the command palette
//   folds like the message search ("aerger" finds "Ärger", "strasse" "Straße")
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
// WCAG contrast of two #rrggbb colours
const lum = h => { const v = [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16) / 255).map(x => x <= .03928 ? x / 12.92 : ((x + .055) / 1.055) ** 2.4); return .2126 * v[0] + .7152 * v[1] + .0722 * v[2]; };
const cr = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + .05) / (Math.min(x, y) + .05); };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const CART = (await call('POST', '/api/lists', {name: '\u{1F6D2} Shopping', color: '#e8590c'})).id;
  const PLAIN = (await call('POST', '/api/lists', {name: 'Plain', color: '#2f9e44'})).id;
  const GREY = (await call('POST', '/api/lists', {name: 'Grey'})).id;
  const T1 = (await call('POST', '/api/tasks', {title: 'Locked task', list_id: PLAIN})).id;
  const T2 = (await call('POST', '/api/tasks', {title: 'Free task', list_id: PLAIN})).id;
  const T3 = (await call('POST', '/api/tasks', {title: 'Ärger mit dem Amt', list_id: PLAIN})).id;
  await call('PATCH', `/api/tasks/${T1}`, {locked: 1});
  check(CART && PLAIN && GREY && T1 && T2 && T3, 'setup: lists and tasks');

  // ================= #1174 list icons
  let w = await boot({hash: 'l/' + CART}); let d = w.document;
  await until(() => d.querySelector(`#side .srow[data-list="${CART}"] .sic .lic`));
  const sic = id => d.querySelector(`#side .srow[data-list="${id}"] .sic`);
  const LIST = (() => { const t = d.createElement('div'); t.innerHTML = w.eval(`ic('list')`); return t.querySelector('svg').innerHTML; })();
  let x = sic(CART);
  check(x.querySelector('.lic.lcol svg.i') && /--lc:#e8590c/.test(x.querySelector('.lic').getAttribute('style') || '') && !x.querySelector('.licd, .sw') && x.querySelector('svg').innerHTML !== LIST,
    'sidebar: the cart line icon carries the list colour, no dot ' + x.innerHTML.slice(0, 160));
  x = sic(PLAIN);
  check(x.querySelector('.lic.lcol svg') && x.querySelector('svg').innerHTML === LIST && /--lc:#2f9e44/.test(x.querySelector('.lic').getAttribute('style') || ''), 'sidebar: no emoji -> the list icon in the list colour');
  x = sic(GREY);
  check(x.querySelector('.lic svg') && !x.querySelector('.lic.lcol') && !x.querySelector('.lic').getAttribute('style'), 'sidebar: no colour -> grey icon as before (no --lc)');
  check(!!d.querySelector('#top h1 .lic.h.lcol svg'), 'header: the open list\'s icon in its colour');
  check(/--lcl:#[0-9a-f]{6}/.test(sic(CART).querySelector('.lic').getAttribute('style')), 'the darker light-theme colour travels along (--lcl)');
  // the light theme's colour: >= 3:1 on the light sidebar for every list colour of the picker
  // 2.53.0 (#1426): the list colours of the picker = the 12 tones
  const pal = w.eval('LP_TONES.map(t => t[2])'), dim = pal.map(c => [c, w.eval(`licDim(${JSON.stringify(c)})`)]);
  const low = dim.filter(([, c]) => cr(c, '#f8f8f9') < 3);
  check(dim.every(([, c]) => /^#[0-9a-f]{6}$/.test(c)) && !low.length, 'licDim: every picker colour >= 3:1 on the light sidebar ' + JSON.stringify(low));
  check(w.eval(`licDim('#abc')`) === w.eval(`licDim('#aabbcc')`), 'licDim: short hex works');
  // pictures and emoji: a tinted tile
  const frag = h => { const t = d.createElement('div'); t.innerHTML = h; return t.firstElementChild; };
  let e = frag(w.eval(`listIconHtml({id: 9001, name: 'Pic', icon: '/static/icon.svg', color: '#c084fc'})`));
  check(e && e.matches('.lic.lict.lcol') && e.querySelector('img.licon') && /--lc:#c084fc/.test(e.getAttribute('style')), 'a picture sits on a tile tinted in the list colour');
  e = frag(w.eval(`listIconHtml({id: 9002, name: 'Pic', icon: '/static/icon.svg'})`));
  check(e && e.matches('.lic.lict') && !e.matches('.lcol') && !e.getAttribute('style'), 'a picture without colour: no tint');
  check(w.eval(`listIconHtml({id: 1, is_inbox: 1, name: 'Inbox'})`) === '' && w.eval('listIconHtml(null)') === '', 'inbox / none -> empty (the caller falls back)');
  check(w.eval(`listIconHtml(listById(${PLAIN}), {full: false})`) === '', 'full: false -> nothing for a list without an emoji (header)');
  // menus with lic (move to list)
  w.eval(`menu(document.body, S.lists.filter(l => !l.archived && !l.is_inbox).map(l => ({label: lname(l), icon: 'list', lic: l, fn() {}})))`);
  await sleep(100);
  const mi = [...d.querySelectorAll('.menu-list button')].find(b => b.textContent.trim() === 'Shopping');
  check(!!mi?.querySelector('.lic.mlic.lcol svg') && !mi.querySelector('.licd'), 'menus: the list icon in its colour');
  w.eval('closePop()');
  // emoji / dot settings (per person): the emoji on a tinted tile; "Dot" keeps its round dot
  w.eval(`S.settings.side_icons = 'emoji'`);
  e = frag(w.eval(`listIconHtml(listById(${CART}), {emoji: true})`));
  check(e && e.matches('.lic.lict.lemo.lcol') && e.textContent === '\u{1F6D2}' && /--lc:#e8590c/.test(e.getAttribute('style')), 'emoji mode: the emoji on a tinted tile');
  check(w.eval(`listIconHtml(listById(${CART}))`) === '', 'emoji mode without emoji: true -> nothing (the name keeps its emoji)');
  w.eval(`S.settings.side_icons = 'dot'`);
  e = frag(w.eval(`listIconHtml(listById(${CART}))`));
  check(e && e.querySelector('.licd') && /#e8590c/.test(e.querySelector('.licd').getAttribute('style')), 'dot mode: the round dot stays');
  w.eval(`S.settings.side_icons = 'line'`);
  w.close();

  // ================= #1132 multi-edit skips locked tasks
  w = await boot({hash: 'l/' + PLAIN}); d = w.document;
  await until(() => w.eval(`!!taskById(${T1}) && !!taskById(${T2})`));
  w.eval(`S.multi = new Set([${T1}, ${T2}]); S.multiMode = true`);
  await w.eval(`meApply('priority', t => ({priority: 3}), 'Priority')`);
  await sleep(300);
  const st = await call('GET', '/api/state');
  const pr = Object.fromEntries(st.tasks.filter(t => [T1, T2].includes(t.id)).map(t => [t.id, t.priority]));
  check(pr[T1] === 0 && pr[T2] === 3, '#1132: the free task changed, the locked one kept its priority ' + JSON.stringify(pr));
  check(/1 locked task skipped/.test(d.body.textContent), '#1132: the hint names the skipped locked task');
  w.close();

  // ================= #1171 chat part mark + palette folding
  w = await boot({hash: 'l/' + PLAIN}); d = w.document;
  await until(() => w.eval(`!!taskById(${T3})`));
  const md = s => w.eval(`renderMd(${JSON.stringify(s)}, true)`);
  let h = md('The rest of the answer.\n\n_(Part 2/2)_');
  check(/<i class="mdpart">\(Part 2\/2\)<\/i>/.test(h) && !/_\(Part/.test(h), '#1171: the part mark in italics ' + h);
  h = md('Zweiter Teil _(Teil 1/3)_');
  check(/<i class="mdpart">\(Teil 1\/3\)<\/i>/.test(h), '#1171: any word, also at the end of a line ' + h);
  h = md('Files my_file_name.txt and __init__.py stay, also _(not a mark)_ and a_(Part 1/2)_b');
  check(!/<i/.test(h) && /my_file_name\.txt/.test(h) && /__init__\.py/.test(h), '#1171: other underscores untouched ' + h);
  const fz = (q, s) => w.eval(`fuzzy(${JSON.stringify(q)}, ${JSON.stringify(s)})`);
  check(fz('aerger', 'Ärger') > 0 && fz('arger', 'Ärger') > 0 && fz('ärger', 'Ärger') > 0, '#1171: aerger / arger / ärger find Ärger');
  check(fz('müller', 'Mueller') > 0 && fz('strasse', 'Straße') > 0 && fz('cafe', 'Café') > 0, '#1171: müller finds Mueller, strasse Straße, cafe Café');
  check(fz('xyz', 'Ärger') === 0 && fz('aerger', 'Anger') === 0, '#1171: no false hits');
  w.eval(`PAL.mode = null; PAL.q = 'aerger'`);
  const its = w.eval(`palItems().map(x => x.label)`);
  check(its.some(l => /rger mit dem Amt/.test(l)), '#1171: the palette finds the task by "aerger" ' + JSON.stringify(its.slice(0, 5)));
  w.close();

  console.log(`p2380_u2_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
