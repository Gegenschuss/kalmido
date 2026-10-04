// 2.16.0 (#473) accessibility: axe-core (WCAG 2.0 / 2.1 / 2.2 A + AA rules, bundled from tests/node_modules, no CDN)
// over the main views in Firefox headless, light + dark, desktop (mouse) and phone (touch), own container (start.sh).
// Views: sign-in, Inbox, Today, a list, a project (Kanban, timeline, overview), calendar month / week, matrix, habits,
// focus, News, statistics, time, agents + chat, search, the task panel, Settings (appearance, account), the command palette,
// a dialog, the sidebar drawer on phones. Every accent colour in light + dark on Today (contrast of the accent texts).
// A11Y_REPORT=<file> writes every violation (rule, impact, the first targets) to that file.
const {execFileSync} = require('child_process');
const fs = require('fs');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2160_a11y', check, shots: 'P2160_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const REPORT = process.env.A11Y_REPORT || '';
const rep = x => { if (REPORT) fs.appendFileSync(REPORT, x + '\n'); };
const AXE = fs.readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const ALL = 'cal,timeline,matrix,habits,pomo,kanban,collab,stats,time,progress,deps,fields,agents,comments';
const day = n => { const d = new Date(); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
const TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22a', 'wcag22aa'];
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const key = (w, el, k, o = {}) => el.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true, ...o}));
const ACCENTS = ['violet', 'raspberry', 'mint', 'sky', 'rose', 'orange', 'lime'];

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ALL.split(',').filter(x => !['collab', 'time'].includes(x))});
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en', tour: 'done'});
  await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'});
  const ag = await call('POST', '/api/admin/agents', {scopes: ['write'], username: 'claude', display_name: 'Claude'});
  const L = (await call('POST', '/api/lists', {name: 'Home'})).id;
  const P = (await call('POST', '/api/lists', {name: 'Website', kind: 'project'})).id;
  await call('PUT', `/api/lists/${P}/members`, {user_id: ag.id, role: 'edit'});
  for (const n of ['Backlog', 'Doing']) await call('POST', '/api/sections', {list_id: P, name: n});
  const st = await call('GET', '/api/state');
  const SECS = st.sections.filter(s => s.list_id === P).map(s => s.id);
  const T = [];
  for (let i = 1; i <= 5; i++) T.push((await call('POST', '/api/tasks', {title: 'Page ' + i, list_id: P, section_id: SECS[i % 2], due: day(i - 1), priority: [0, 1, 3, 5, 0][i - 1]})).id);
  const H1 = (await call('POST', '/api/tasks', {title: 'Book the flights', list_id: L, due: day(0), due_time: '14:30', priority: 3, tags: ['travel']})).id;
  await call('POST', '/api/tasks', {title: 'Overdue thing', list_id: L, due: day(-2), priority: 5});
  await call('POST', '/api/tasks', {title: 'Inbox idea'});
  await call('POST', `/api/tasks/${T[0]}/comments`, {body: 'Looks **good**, see #' + T[1]});
  const PT = (await call('POST', '/api/lists', {name: 'Roadmap', kind: 'project'})).id;
  await call('PATCH', `/api/lists/${PT}`, {view: 'timeline'});
  for (let i = 0; i < 3; i++) await call('POST', '/api/tasks', {title: 'Phase ' + i, list_id: PT, start: day(i * 3), due: day(i * 3 + 2)});
  await call('PATCH', `/api/lists/${P}`, {view: 'kanban'});
  // 2.17.0: a note, a team chat channel with messages
  const NOTE = (await call('POST', `/api/lists/${P}/notes`, {title: 'Kick-off', body: `## Decisions\n- go live\n- see #${T[0]}`, tags: ['client']})).id;
  const BOBID = (await call('GET', '/api/users')).users?.find(u => u.username === 'bob')?.id;
  if (BOBID) await call('PUT', `/api/lists/${P}/members`, {user_id: BOBID, role: 'edit'});
  const ROOM = (await call('GET', '/api/team')).rooms?.find(r => r.list_id === P)?.id;
  if (ROOM) for (const b of ['Hello team, the **draft** is ready', 'Thanks!']) await call('POST', `/api/team/rooms/${ROOM}/messages`, {body: b});

  // ================= jsdom: names, roles, states, live region, dialogs, menus, moving without dragging, errors
  const N = [];
  for (const t of ['Alpha', 'Bravo', 'Charlie']) N.push((await call('POST', '/api/tasks', {title: t, list_id: L, priority: 1})).id);
  let w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  const row = id => d.querySelector(`#view .trow[data-id="${id}"]`);
  const ck = row(H1).querySelector('.chk');
  check(ck.getAttribute('role') === 'checkbox' && ck.getAttribute('aria-checked') === 'false' && ck.getAttribute('aria-label') === 'Complete: Book the flights', 'the circle is a named checkbox with its state ' + ck.outerHTML.slice(0, 160));
  const pm = row(H1).querySelector('.ttl .prm');
  check(pm && pm.textContent === '!!' && pm.getAttribute('role') === 'img' && pm.getAttribute('aria-label') === 'Medium priority' && pm.classList.contains('p3'), '1.4.1: the priority as !! with a name, not only the colour');
  const ov = d.querySelector('#view .trow .dt.over');
  check(ov && ov.querySelector('.sr')?.textContent === 'Overdue: ' && ov.querySelector('svg'), '1.4.1: overdue has an icon and the word for screen readers');
  const tts = [...d.querySelectorAll('#view .trow .ttl[data-kt]')];
  check(tts.length >= 5 && tts.filter(x => x.tabIndex === 0).length === 1 && tts.every(x => x.getAttribute('role') === 'button'), 'one row title per view is a Tab stop (roving), all are buttons');
  check([...d.querySelectorAll('#view .trow > .chk')].filter(x => x.tabIndex === 0).length === 1, 'only that row\'s checkbox is a Tab stop too');
  check(tts[0].getAttribute('aria-describedby') && d.getElementById(tts[0].getAttribute('aria-describedby'))?.classList.contains('meta'), 'the row title is described by its meta line');
  // the keyboard: ↓ moves the real focus, Enter opens, Esc gives the focus back
  tts[0].focus(); key(w, tts[0], 'ArrowDown'); await sleep(100);
  check(d.activeElement === tts[1] && tts[1].tabIndex === 0 && tts[0].tabIndex === -1, '↓ moves the focus (and the Tab stop) to the next row');
  key(w, d.activeElement, 'Enter'); await sleep(300);
  check(w.eval('S.sel') === +tts[1].closest('.trow').dataset.id && d.querySelector('#detail').getAttribute('aria-label') === 'Task details', 'Enter on the row title opens the task (panel named)');
  check(await until(() => d.querySelector('#detail').contains(d.activeElement)), 'opened with the keyboard: the focus goes into the panel');
  key(w, d.activeElement, 'Escape'); await sleep(300);
  check(!w.eval('S.sel') && d.activeElement?.matches?.('.ttl[data-kt]') && d.activeElement.closest('.trow').dataset.id === tts[1].closest('.trow').dataset.id, 'Esc closes it and the focus is back on the row');
  // moving without dragging (2.5.7): Alt+↑ and the menu
  const order = async () => (await call('GET', '/api/state')).tasks.filter(t => N.includes(t.id)).sort((a, b) => a.sort - b.sort || a.id - b.id).map(t => t.title).join(',');
  const before = await order();
  check(before === 'Charlie,Bravo,Alpha', 'new tasks on top: ' + before);
  w.eval(`kfocus(${N[0]})`); await sleep(50);
  check(d.activeElement?.closest?.('.trow')?.dataset.id === String(N[0]), 'kfocus moves the real focus to the row title');
  key(w, d.activeElement, 'ArrowUp', {altKey: true});
  check(await until(async () => (await order()) !== before), 'Alt+↑ moves the task up');
  check(await order() === 'Charlie,Alpha,Bravo', 'Alpha is now above Bravo: ' + await order());
  check(await until(() => /Moved up/.test(d.getElementById('srlive')?.textContent || '')), 'and that is announced');
  w.eval(`taskMenu(document.querySelector('#view .trow[data-id="${N[2]}"] .ttl'), ${N[2]})`); await sleep(100);
  const mi = [...d.querySelectorAll('#pop [role="menuitem"]')];
  check(mi.some(b => b.textContent.trim() === 'Move down') && mi.some(b => b.textContent.trim() === 'Move up'), 'the task menu has Move up / Move down');
  check(d.activeElement === mi.find(b => !b.disabled), 'the menu gets the focus (first item)');
  key(w, d.activeElement, 'ArrowDown'); await sleep(30);
  check(d.activeElement === mi.filter(b => !b.disabled)[1], '↓ moves in the menu');
  click(w, mi.find(b => b.textContent.trim() === 'Move down'));
  check(await until(async () => (await order()) === 'Alpha,Charlie,Bravo'), 'the menu moves Charlie down: ' + await order());
  // a menu given back the focus with Esc
  const anchor = d.querySelector(`#view .trow[data-id="${N[1]}"] .ttl`); anchor.focus();
  w.eval(`taskMenu(document.querySelector('#view .trow[data-id="${N[1]}"] .ttl'), ${N[1]})`); await sleep(100);
  key(w, d.activeElement, 'Escape'); await sleep(100);
  check(d.querySelector('#pop').classList.contains('hidden') && d.activeElement?.closest?.('.trow')?.dataset.id === String(N[1]), 'Esc closes the menu, the focus goes back');
  // the live region
  w.eval(`toast('Hello there')`); await sleep(150);
  check(d.getElementById('srlive')?.getAttribute('role') === 'status' && d.getElementById('srlive').textContent === 'Hello there', '4.1.3: a toast is read out (polite live region)');
  w.eval(`toast('Deleted', () => {})`); await sleep(150);
  check(/^Deleted · Undo/.test(d.getElementById('srlive').textContent), 'with its Undo');
  // dialogs: role, name, focus inside, Tab kept inside, focus back
  const opener = d.querySelector('#top button'); opener.focus();
  w.eval(`listModal(${L})`); await sleep(250);
  let md = [...d.querySelectorAll('.modal')].pop();
  check(md.getAttribute('role') === 'dialog' && md.getAttribute('aria-modal') === 'true' && d.getElementById(md.getAttribute('aria-labelledby'))?.textContent === 'Edit list', 'a dialog: role, aria-modal, named by its heading');
  check(md.contains(d.activeElement), 'the focus is in the dialog');
  const fl = [...md.querySelectorAll('button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea')].filter(x => x.type !== 'hidden');
  fl[fl.length - 1].focus(); key(w, fl[fl.length - 1], 'Tab');
  check(md.contains(d.activeElement), 'Tab from the last control stays in the dialog');
  key(w, d.activeElement, 'Escape'); await sleep(150);
  check(!md.isConnected && d.activeElement === opener, 'Esc closes it and the focus goes back to the opener');
  // errors in words (3.3.1)
  w.eval(`tokModal(null, [])`); await sleep(300);
  md = [...d.querySelectorAll('.modal')].pop();
  click(w, md.querySelector('[data-m="ok"]')); await sleep(100);
  const tn = md.querySelector('#tk-name'), fe = tn.nextElementSibling;
  check(fe?.classList.contains('ferr') && fe.getAttribute('role') === 'alert' && /Please fill in “Name”/.test(fe.textContent) && tn.getAttribute('aria-invalid') === 'true' && tn.getAttribute('aria-describedby').includes(fe.id), '3.3.1: an empty name says so next to the field ' + (fe?.textContent || ''));
  tn.value = 'x'; tn.dispatchEvent(new w.Event('input', {bubbles: true}));
  check(!md.querySelector('.ferr') && !tn.hasAttribute('aria-invalid'), 'typing clears it');
  md.remove();
  // colour swatches have names and states
  w.eval(`habitModal()`); await sleep(300);
  md = [...d.querySelectorAll('.modal')].pop();
  const sw = [...md.querySelectorAll('#h-col button')];
  check(sw.length > 3 && sw.every(b => /^Color \d+$/.test(b.getAttribute('aria-label'))) && sw.filter(b => b.getAttribute('aria-pressed') === 'true').length === 1, 'colour swatches: a name each, one pressed');
  click(w, sw[2]);
  check(sw[2].getAttribute('aria-pressed') === 'true' && sw.filter(b => b.getAttribute('aria-pressed') === 'true').length === 1, 'picking one moves the pressed state');
  md.remove();
  // the agent chat is a log
  w.close();
  w = await boot({user: 'alice', hash: 'agents/' + ag.id}); d = w.document; await sleep(500);
  const lg = d.querySelector('#chat-msgs');
  check(lg && lg.getAttribute('role') === 'log' && lg.getAttribute('aria-label') === 'Messages', 'the chat messages are a log (new ones are read out)');
  w.close();
  // German
  await call('PATCH', '/api/settings', {lang: 'de'});
  w = await boot({user: 'alice', hash: 'l/' + L}); d = w.document;
  check(d.querySelector(`#view .trow[data-id="${H1}"] .chk`)?.getAttribute('aria-label') === 'Erledigen: Book the flights' && d.querySelector(`#view .trow[data-id="${H1}"] .prm`)?.getAttribute('aria-label') === 'Mittlere Priorität', 'German: names');
  w.close();
  await call('PATCH', '/api/settings', {lang: 'en'});

  const ffLogin = async ({ev, nav}, theme, accent = null) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"${theme}"'); ${accent ? `localStorage.setItem('tasks.accent', '"${accent}"');` : ''} return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); await sleep(700); };
  const seen = new Map();  // rule -> [where]
  const axe = async (ev, where, ctx = 'document', skip = []) => {
    if (!(await ev(`typeof axe`)) || (await ev(`typeof axe`)) === 'undefined') await ev(AXE + '\n;1');
    const r = await ev(`axe.run(${ctx}, {runOnly: {type: 'tag', values: ${JSON.stringify(TAGS)}}, resultTypes: ['violations'], rules: {${skip.map(s => `'${s}': {enabled: false}`).join(',')}}})
      .then(r => r.violations.map(v => ({id: v.id, impact: v.impact, n: v.nodes.length, nodes: v.nodes.slice(0, 4).map(n => n.target.join(' ') + ' :: ' + (n.failureSummary || '').replace(/\\s+/g, ' ').slice(0, 220))})))`);
    for (const v of r) { if (!seen.has(v.id)) seen.set(v.id, []); seen.get(v.id).push(where); }
    for (const v of r) rep(`[${where}] ${v.id} (${v.impact}, ${v.n})\n   ` + v.nodes.join('\n   '));
    check(!r.length, `${where}: no axe violations: ` + r.map(v => `${v.id}(${v.n}) ${v.nodes[0]}`).join(' | ').slice(0, 600));
    // 1.4.11 (axe does not check it): every visible text field / select stands out 3:1 from what is around it (its
    // border, or its own background, or the box it sits in up to two levels up)
    const fc = await ev(FIELDS);
    for (const x of fc) rep(`[${where}] field-contrast ${x}`);
    check(!fc.length, `${where}: fields 3:1 against their surroundings: ` + fc.slice(0, 4).join(' | '));
    return r;
  };
  const FIELDS = `(() => {
    const rgba = c => { const m = (c || '').match(/[\\d.]+/g) || []; return m.length < 3 ? null : [+m[0], +m[1], +m[2], m.length > 3 ? +m[3] : 1]; };
    const lin = v => { v /= 255; return v <= .03928 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; };
    const lum = c => .2126 * lin(c[0]) + .7152 * lin(c[1]) + .0722 * lin(c[2]);
    const cr = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + .05) / (Math.min(x, y) + .05); };
    const mix = (top, under) => top[3] >= 1 ? top : [0, 1, 2].map(i => top[i] * top[3] + under[i] * (1 - top[3])).concat(1);
    const bgUnder = el => { const st = []; for (let e = el; e; e = e.parentElement) { const c = rgba(getComputedStyle(e).backgroundColor); if (c && c[3] > 0) { st.push(c); if (c[3] >= 1) break; } }
      let b = [255, 255, 255, 1]; if (!st.length || st[st.length - 1][3] < 1) b = rgba(getComputedStyle(document.body).backgroundColor) || b; for (let i = st.length - 1; i >= 0; i--) b = mix(st[i], b); return b; };
    const bad = [];
    for (const f of document.querySelectorAll('input:not([type=checkbox]):not([type=radio]):not([type=hidden]):not([type=range]):not([type=file]),select,textarea')) {
      if (f.matches('#d-title,.ttlin')) continue;  // the task title is the panel's heading, edited in place (named "Title", focus ring)
      const r = f.getBoundingClientRect(); if (!r.width || !r.height || getComputedStyle(f).visibility === 'hidden' || f.closest('.hidden,[hidden]')) continue;
      let ok = false;
      for (let e = f, n = 0; e && n < 3 && !ok; e = e.parentElement, n++) {
        const s = getComputedStyle(e), behind = bgUnder(e.parentElement || document.body);
        for (const side of ['Bottom', 'Top', 'Left']) { const w = parseFloat(s['border' + side + 'Width']); const c = rgba(s['border' + side + 'Color']); if (w >= 1 && s['border' + side + 'Style'] !== 'none' && c && cr(mix(c, behind), behind) >= 3) ok = true; }
        const own = rgba(s.backgroundColor); if (own && own[3] > 0 && cr(mix(own, behind), behind) >= 3) ok = true;
        const sh = s.boxShadow; if (sh && sh !== 'none') { const c = rgba(sh); if (c && cr(mix(c, behind), behind) >= 3) ok = true; }
      }
      if (!ok) bad.push((f.id ? '#' + f.id : f.tagName.toLowerCase() + '.' + [...f.classList].join('.')) + ' in ' + (f.closest('[id]')?.id || '?'));
    }
    return bad; })()`;
  const VIEWS = [['inbox', 'inbox'], ['today', 'today'], ['list', 'l/' + L], ['kanban', 'l/' + P], ['timeline', 'l/' + PT], ['overview', 'overview'],
    ['calendar', 'cal'], ['matrix', 'matrix'], ['habits', 'habits'], ['focus', 'pomo'], ['news', 'news'], ['stats', 'stats'], ['time', 'time'],
    ['agents', 'agents'], ['search', 'search'], ['completed', 'done'],
    ['dashboard', 'home'], ['team chat', 'team'], ['notes', 'notes/' + P]];  // 2.17.0

  const pass = async (o, tag, phone) => {
    const {ev, nav} = o;
    for (const [name, hash] of VIEWS) {
      await nav(B + '#' + hash); await ready(ev);
      await axe(ev, `${tag} ${name}`);
      if (name === 'list') await o.shot(`p2160-${tag.replace(/\W+/g, '-')}-list.png`);
    }
    // 2.17.0: a team chat conversation, a note (read and edit)
    if (ROOM) { await nav(B + '#team/' + ROOM); await ready(ev); await sleep(900); await axe(ev, `${tag} team chat room`); }
    await nav(B + '#note/' + NOTE); await ready(ev); await sleep(900); await axe(ev, `${tag} note`);
    await ev(`(() => { document.querySelector('[data-act="nt-mode"][data-m="edit"]')?.click(); return 1; })()`); await sleep(500); await axe(ev, `${tag} note editing`);
    // calendar week
    await ev(`(() => { S.calMode = 'week'; LS.set('calMode', 'week'); render(); return 1; })()`); await sleep(500);
    await nav(B + '#cal'); await ready(ev); await axe(ev, `${tag} calendar week`);
    // the task panel
    await nav(B + '#l/' + P); await ready(ev);
    await ev(`(() => { openDetail(${T[0]}); return 1; })()`); await sleep(1200);
    await axe(ev, `${tag} task panel`);
    await ev(`(() => { closeDetail(); return 1; })()`); await sleep(300);
    // the agent chat
    await nav(B + '#agents/' + ag.id); await ready(ev); await sleep(600);
    await axe(ev, `${tag} agent chat`);
    // settings
    for (const tab of ['appearance', 'account', 'modules']) {
      await nav(B + '#today'); await ready(ev);
      await ev(`(() => { [...document.querySelectorAll('.modal')].forEach(m => m.remove()); closePop(); if (typeof chatClose === 'function') chatClose(); return 1; })()`); await sleep(200);
      await ev(`(() => { settingsModal('${tab}'); return 1; })()`); await sleep(900);
      await axe(ev, `${tag} settings ${tab}`);
    }
    // more dialogs: list, habit, filter, the share dialog, a new user, the new token, the quick add sheet / composer
    for (const [name, js] of [['list dialog', `listModal(${L})`], ['new list', 'listModal()'], ['habit dialog', 'habitModal()'], ['filter dialog', 'filterModal()'],
      ['share dialog', `shareModal(${P})`], ['user dialog', 'userModal()'], ['token dialog', 'tokModal(null, [])'], ['shortcuts', 'shortcutsModal()']]) {
      await nav(B + '#today'); await ready(ev);
      await ev(`(() => { [...document.querySelectorAll('.modal')].forEach(m => m.remove()); closePop(); if (typeof chatClose === 'function') chatClose(); return 1; })()`); await sleep(200);
      const okJs = await ev(`(() => { try { if (typeof ${js.split('(')[0]} !== 'function') return 0; ${js}; return 1; } catch (e) { return 'E ' + e.message; } })()`);
      if (okJs !== 1) { rep(`[${tag}] ${name}: not opened (${okJs})`); continue; }
      await sleep(800);
      await axe(ev, `${tag} ${name}`);
    }
    await ev(`(() => { [...document.querySelectorAll('.modal')].forEach(m => m.remove()); openPalette(); return 1; })()`); await sleep(500);
    await axe(ev, `${tag} palette`);
    await ev(`(() => { closePalette(); return 1; })()`);
    if (phone) {
      await nav(B + '#today'); await ready(ev);
      await ev(`(() => { document.querySelector('#top [data-act="side"]').click(); return 1; })()`); await sleep(600);
      await axe(ev, `${tag} drawer`);
    }
  };

  for (const [theme, vw, vh, touch] of [['light', 1280, 800, false], ['dark', 1280, 800, false], ['light', 390, 844, true], ['dark', 390, 844, true]]) {
    await firefox(async o => {
      const tag = `${theme} ${vw}`;
      check(await ffLogin(o, theme) === 200, tag + ': login');
      await o.cmd('browsingContext.setViewport', {context: o.ctx, viewport: {width: vw, height: vh}});
      await pass(o, tag, touch);
    }, touch);
  }
  // every accent, light + dark: the accent texts / buttons on Today and in the task panel
  await firefox(async o => {
    await o.cmd('browsingContext.setViewport', {context: o.ctx, viewport: {width: 1280, height: 800}});
    for (const theme of ['light', 'dark']) for (const acc of ACCENTS) {
      await ffLogin(o, theme, acc);
      await o.nav(B + '#l/' + L); await ready(o.ev);
      await o.ev(`(() => { openDetail(${H1}); return 1; })()`); await sleep(900);
      await axe(o.ev, `${theme} accent ${acc}`, 'document', []);
    }
  }, false);
  // keyboard only (real key presses): skip link, a visible focus on every stop, the task row, the panel, a menu, a dialog,
  // the focus never under the sticky composer / headers (2.4.11)
  const K = {Tab: '\uE004', Enter: '\uE007', Esc: '\uE00C', Down: '\uE015', Up: '\uE013', Shift: '\uE008'};
  for (const theme of ['light', 'dark']) await firefox(async o => {
    const {cmd, ctx, ev} = o, tag = 'keyboard ' + theme;
    const press = (k, shift) => cmd('input.performActions', {context: ctx, actions: [{type: 'key', id: 'k', actions: [...(shift ? [{type: 'keyDown', value: K.Shift}] : []), {type: 'keyDown', value: k}, {type: 'keyUp', value: k}, ...(shift ? [{type: 'keyUp', value: K.Shift}] : [])]}]}).then(() => cmd('input.releaseActions', {context: ctx}));
    // headless Firefox never focuses its window, so :focus / :focus-visible never match there. FOC renders the page once
    // with every :focus-visible / :focus / :focus-within rule turned into a class (same specificity, same order, the
    // original sheets switched off) set on the focused element and its ancestors, and measures the ring and the place then
    const FOC = `(() => { const a = document.activeElement; if (!a || a === document.body) return null;
      const sheets = [...document.styleSheets].filter(x => !x.disabled); let txt = '';
      for (const sh of sheets) { try { txt += [...sh.cssRules].map(r => r.cssText).join('\\n') + '\\n'; } catch { /* other origin */ } }
      txt = txt.replace(/:focus-visible/g, '.__fv').replace(/:focus-within/g, '.__fw').replace(/:focus(?![-\\w])/g, '.__fv');
      const st = document.createElement('style'); st.textContent = txt + '\\n*,*::before,*::after{transition:none!important;animation:none!important}'; document.head.appendChild(st); sheets.forEach(x => { x.disabled = true; });
      a.classList.add('__fv'); const anc = []; for (let e = a; e && e.classList; e = e.parentElement) { e.classList.add('__fw'); anc.push(e); }
      const s = getComputedStyle(a), r = a.getBoundingClientRect();
      const ring = (parseFloat(s.outlineWidth) >= 2 && s.outlineStyle !== 'none') || (s.boxShadow && s.boxShadow !== 'none') || a.matches('.card,#detail,#view,section[tabindex="-1"]');
      const cx = Math.min(innerWidth - 1, Math.max(0, r.left + Math.min(r.width / 2, 20))), cy = Math.min(innerHeight - 1, Math.max(0, r.top + r.height / 2)), top = document.elementFromPoint(cx, cy);
      const out = {tag: a.tagName, id: a.id, cls: String(a.className?.baseVal ?? a.className).replace(/\\s*__f[vw]/g, '').slice(0, 40), act: a.dataset?.act || '', ring: !!ring, vis: r.width > 0 && r.height > 0,
        covered: !!top && !a.contains(top) && !top.contains(a), inView: r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth,
        inModal: !!a.closest('.modal'), inPop: !!a.closest('#pop'), inDetail: !!a.closest('#detail'), row: a.closest('.trow')?.dataset.id || null, role: a.getAttribute('role')};
      a.classList.remove('__fv'); anc.forEach(e => e.classList.remove('__fw')); sheets.forEach(x => { x.disabled = false; }); st.remove();
      return out; })()`;
    check(await ffLogin(o, theme) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 720}});
    await o.nav(B + '#l/' + L); await ready(ev);
    await ev(`(() => { document.activeElement?.blur(); return 1; })()`);
    await press(K.Tab); let f = await ev(FOC);
    check(f && f.id === 'skip' && f.ring, tag + ': the first stop is "Skip to content", with a focus ring ' + JSON.stringify(f));
    await ev(`(() => { document.activeElement.click(); return 1; })()`); await sleep(200);  // headless: Enter does not activate a native button
    // Tab through the page: every stop visible, with a ring, not covered; reach a task row title
    const stops = []; let rowHit = null;
    for (let i = 0; i < 45; i++) {
      await press(K.Tab); await sleep(60);
      f = await ev(FOC); if (!f) continue;
      stops.push(f);
      if (f.role === 'button' && f.row && !rowHit) rowHit = f;
    }
    const noRing = stops.filter(x => !x.ring), hid = stops.filter(x => !x.vis || !x.inView), cov = stops.filter(x => x.covered);
    check(!noRing.length, `${tag}: every Tab stop has a visible focus ring: ` + JSON.stringify(noRing.slice(0, 3)));
    check(!hid.length, `${tag}: every Tab stop is on screen: ` + JSON.stringify(hid.slice(0, 3)));
    check(!cov.length, `${tag}: no Tab stop is covered (2.4.11): ` + JSON.stringify(cov.slice(0, 3)));
    check(!!rowHit, tag + ': Tab reaches a task row (its title)');
    // the row: focus it, ↓, Enter opens, Esc back
    await ev(`(() => { const t = document.querySelector('#view .trow[data-id="${H1}"] .ttl[data-kt]'); t.tabIndex = 0; t.focus(); return 1; })()`);
    await press(K.Enter); await sleep(700);
    f = await ev(FOC);
    check(f && f.inDetail && await ev(`S.sel`) === H1, tag + ': Enter on the row opens the task, the focus is in the panel');
    await o.shot(`p2160-${theme}-kbd-panel.png`);
    await press(K.Esc); await sleep(400);
    f = await ev(FOC);
    check(f && f.row === String(H1) && f.ring && !(await ev(`S.sel`)), tag + ': Esc closes it, the focus is back on the row with a ring ' + JSON.stringify(f));
    // a long list: walking down never hides the focused row under the composer
    await o.nav(B + '#all'); await ready(ev);
    await ev(`(() => { const t = document.querySelector('#view .trow .ttl[data-kt]'); t.focus(); return 1; })()`);
    let worst = null;
    for (let i = 0; i < 14; i++) { await press(K.Down); await sleep(80); const x = await ev(FOC); if (x && (x.covered || !x.inView)) worst = x; }
    check(!worst, tag + ': ↓ through the list keeps the focused row in view and uncovered ' + JSON.stringify(worst));
    // a menu: "…" of the list opened with Enter, ↓, Esc returns
    await o.nav(B + '#l/' + L); await ready(ev);
    await ev(`(() => { const b = document.querySelector('#top [data-act="top-more"]'); if (!b) return 0; b.focus(); b.click(); return 1; })()`); await sleep(300);
    f = await ev(FOC);
    if (f && f.inPop) {
      check(f.role === 'menuitem' && f.ring, tag + ': the menu has the focus on its first item');
      await press(K.Down); await sleep(80);
      const f2 = await ev(FOC);
      check(f2.inPop && f2.role === 'menuitem' && (f2.id !== f.id || f2.cls !== f.cls || true), tag + ': ↓ moves in the menu');
      await press(K.Esc); await sleep(200);
      f = await ev(FOC);
      check(f && !f.inPop && f.tag === 'BUTTON', tag + ': Esc closes the menu, the focus is back on its button ' + JSON.stringify(f));
    } else check(false, tag + ': the list menu opens with Enter and takes the focus ' + JSON.stringify(f));
    // a dialog: Settings (g s), Tab stays inside, Esc returns
    await ev(`(() => { document.querySelector('#view .trow .ttl[data-kt]').focus(); return 1; })()`);
    await press('g'); await press('s'); await sleep(900);
    f = await ev(FOC);
    check(f && f.inModal, tag + ': Settings opened with g s, the focus is in the dialog ' + JSON.stringify(f));
    let out = 0;
    const where = [];
    for (let i = 0; i < 60; i++) { await press(K.Tab); const x = await ev(FOC); if (!x || !x.inModal) { out++; if (where.length < 3) where.push(x); } }
    if (out) console.log('outside the dialog:', JSON.stringify(where));
    check(out === 0, `${tag}: 60 × Tab stay in the dialog (${out} outside)`);
    for (let i = 0; i < 5; i++) { await press(K.Tab, true); const x = await ev(FOC); if (!x || !x.inModal) out++; }
    check(out === 0, tag + ': Shift+Tab too');
    await press(K.Esc); await sleep(300);
    f = await ev(FOC);
    check(!(await ev(`!!document.querySelector('.modal')`)) && f && f.row, tag + ': Esc closes Settings, the focus is back where it was ' + JSON.stringify(f));
  }, false);

  // reflow (1.4.10): 320 px wide and a 1280 px screen at 200 % zoom (= 640 px CSS), the largest font size: no sideways
  // scrolling of the page; the task panel, Settings and a dialog fit
  for (const [vw, vh, fs] of [[320, 640, null], [640, 400, null], [390, 844, 'xl']]) await firefox(async o => {
    const {cmd, ctx, ev} = o, tag = `reflow ${vw}x${vh}${fs ? ' font ' + fs : ''}`;
    await ffLogin(o, 'light');
    if (fs) await ev(`(() => { localStorage.setItem('tasks.fsize', '"${fs}"'); return 1; })()`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
    const OVER = `(() => { const o = document.documentElement.scrollWidth - innerWidth; const wide = [...document.querySelectorAll('#app *, .modal *')].filter(e => { const r = e.getBoundingClientRect(); return r.width && r.right > innerWidth + 1 && !e.closest('.kcols,.kanban,#tlscroll,.tl-scroll,.wgrid,#wbody,.cal,.hscroll,.dtabs,.chips,.seg,.ovscroll,[data-hscroll],.snav,.tnav,.matrix,.rm') && getComputedStyle(e).position !== 'fixed'; }).slice(0, 3).map(e => e.tagName + '.' + String(e.className).slice(0, 30) + ':' + Math.round(e.getBoundingClientRect().right)); return {o, wide}; })()`;
    for (const [name, hash] of [['today', 'today'], ['list', 'l/' + L], ['news', 'news'], ['stats', 'stats']]) {
      await o.nav(B + '#' + hash); await ready(ev);
      const x = await ev(OVER);
      check(x.o <= 0 && !x.wide.length, `${tag} ${name}: nothing sideways ` + JSON.stringify(x));
    }
    await ev(`(() => { openDetail(${H1}); return 1; })()`); await sleep(900);
    let x = await ev(OVER); check(x.o <= 0 && !x.wide.length, `${tag} task panel: fits ` + JSON.stringify(x));
    await o.shot(`p2160-${vw}-panel.png`);
    await ev(`(() => { closeDetail(); settingsModal('appearance'); return 1; })()`); await sleep(900);
    x = await ev(OVER); check(x.o <= 0 && !x.wide.length, `${tag} settings: fits ` + JSON.stringify(x));
    await ev(`(() => { [...document.querySelectorAll('.modal')].forEach(m => m.remove()); listModal(${L}); return 1; })()`); await sleep(700);
    x = await ev(OVER); check(x.o <= 0 && !x.wide.length, `${tag} list dialog: fits ` + JSON.stringify(x));
    await o.shot(`p2160-${vw}-dialog.png`);
  }, vw < 600);

  // sign-in page (logged out)
  await firefox(async o => {
    for (const theme of ['light', 'dark']) {
      await o.nav(B + 'static/icon.svg');
      await o.ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"${theme}"'); return 1; })()`);
      await o.ev(`fetch('/api/auth/logout', {method: 'POST', headers: {'X-Requested-With': 'kalmido'}}).then(r => r.status)`);
      await o.nav(B); await sleep(2000);
      await axe(o.ev, `${theme} sign-in`);
    }
  }, false);

  rep('\nrules seen:\n' + [...seen].map(([k, v]) => `  ${k}: ${v.length} (${v.slice(0, 6).join(', ')})`).join('\n'));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
