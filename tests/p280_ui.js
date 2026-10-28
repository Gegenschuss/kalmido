// 2.8.0 UI tests "Leitstand" (#434), own container (start.sh, isolated test database). jsdom: no icon rail, one sidebar with
// groups (Focus / Views / Lists / Filters / Team) that reaches every module (and leaves out switched-off ones), counters right
// after the labels, the command bar (header + drawer) opens the palette, "New task", the milestone in the header, the agent
// band (agents of the list with status, current task, the waiting job with 👍 / ✕ wired to the job actions, folds per
// device, replaces the header dots), rows with the ticket gutter + status glyph (an agent working on it = arc), the icon set
// "Punkt" (20 grid, every key), raspberry as the default accent (mint devices migrate once, other choices stay); SW v77.
// Then Firefox headless (shared helper ff.js): touch 360 x 780 / 390 x 844 (tab bar, drawer, 44 px), touch 904 x 904
// (unfolded Fold: drawer + band), a mouse at 1280 x 800 / 1920 x 1080 (sidebar 240 px, 40 px rows, no rail, no overflow) and
// contrast of text / accent in light and dark; screenshots light + dark at 390 and 1440 with P280_SHOTS=<dir>.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p280_ui', check, shots: 'P280_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const tcall = async (method, url, tok, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + tok}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const ALL = 'cal,timeline,matrix,habits,pomo,kanban,collab,stats,time,progress,deps,fields,agents,comments';
const day = n => { const d = new Date(); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
// elements smaller than 44 px (pseudo-element hit areas count), visible ones only
const SMALL = sel => `(() => [...document.querySelectorAll('${sel}')].filter(e => e.offsetWidth && getComputedStyle(e).visibility !== 'hidden').map(e => {
  const b = e.getBoundingClientRect(); let w = b.width, h = b.height;
  for (const ps of ['::before', '::after']) { const s = getComputedStyle(e, ps); if (s.content && s.content !== 'none' && s.position === 'absolute') { const iw = b.width - parseFloat(s.left || 0) - parseFloat(s.right || 0), ih = b.height - parseFloat(s.top || 0) - parseFloat(s.bottom || 0); if (Number.isFinite(iw)) w = Math.max(w, iw); if (Number.isFinite(ih)) h = Math.max(h, ih); } }
  return [e.className || e.tagName, (e.textContent || '').trim().slice(0, 16), Math.round(w), Math.round(h)]; }).filter(x => x[2] < 43.5 || x[3] < 43.5))()`;
// WCAG contrast of two computed colours (rgb / rgba / color(srgb ...))
const CONTRAST = `(() => {
  const rgb = c => { const m = c.match(/[\\d.]+/g).map(Number); return /color\\(/.test(c) ? m.slice(0, 3).map(x => x * 255) : m.slice(0, 3); };
  const L = c => { const [r, g, b] = rgb(c).map(v => { v /= 255; return v <= .03928 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; }); return .2126 * r + .7152 * g + .0722 * b; };
  const cr = (a, b) => { const x = L(a), y = L(b); return (Math.max(x, y) + .05) / (Math.min(x, y) + .05); };
  const probe = v => { const e = document.createElement('i'); e.style.color = 'var(' + v + ')'; document.body.appendChild(e); const c = getComputedStyle(e).color; e.remove(); return c; };
  const bg = probe('--bg'), bg2 = probe('--bg2'), out = {};
  for (const v of ['--text', '--text2', '--muted', '--accent']) out[v] = Math.min(cr(probe(v), bg), cr(probe(v), bg2)).toFixed(2);
  out.ink = cr(probe('--accent-ink'), probe('--accent')).toFixed(2);
  return out;
})()`;

(async () => {
  await sleep(600);
  const SW = await (await fetch(B + 'sw.js')).text();
  check(/const CACHE = 'tasks-shell-v(?:7[7-9]|8[0-9]|9[0-9]|[1-9][0-9]{2})'/.test(SW), 'service worker cache v77 or newer (2.9.0: v78, 2.10.0: v79, 2.11.0: v80)');
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en', tour: 'done'});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const mkAgent = async (u, n) => { const a = await call('POST', '/api/admin/agents', {scopes: ['write'], username: u, display_name: n}); return {id: a.id, tok: a.token}; };
  const DEV = await mkAgent('devbot', 'DevBot'), KOL = await mkAgent('kollege', 'Kollege'), ARC = await mkAgent('archivar', 'Archivar');
  const L = (await call('POST', '/api/lists', {name: 'Launch', kind: 'project', tickets: true})).id;
  const W = (await call('POST', '/api/lists', {name: 'Website', kind: 'project'})).id;
  await call('PATCH', '/api/settings', {show_progress: String(L)});  // 2.40.0 (#1190): the progress bar of a project is off by default
  const PLAIN = (await call('POST', '/api/lists', {name: 'Groceries'})).id;
  for (const u of [BOB, DEV.id]) await call('PUT', `/api/lists/${L}/members`, {user_id: u, role: 'edit'});
  // 2.26.0: one agent per list -- the other two join as in a list from before the update (kept)
  for (const a of [KOL.id, ARC.id])
    execFileSync('python3', [path.join(__dirname, 'dbx.py'), DATA, "INSERT INTO list_members(list_id,user_id,role,own_role,sort,added_at) VALUES(?,?,'edit','edit',0,'2026-01-01T00:00:00+00:00')", JSON.stringify([L, a])]);
  await call('POST', `/api/lists/${L}/milestones`, {name: 'Beta', day: day(12)});
  const S1 = (await call('POST', '/api/sections', {list_id: L, name: 'In progress'})).id;
  const S2 = (await call('POST', '/api/sections', {list_id: L, name: 'Review'})).id;
  const T = {};
  for (const [k, title, sec, extra] of [['kb', 'Keyboard closes when adding (Fold)', S1, {due: day(0), priority: 5}], ['dots', 'Status dots for agents in the header', S1, {due: day(0), assignee_id: BOB}],
    ['win', 'Guide: set up an agent on Windows', S1, {due: day(4)}], ['ppl', 'People icons clickable everywhere', S2, {due: day(1), priority: 3}], ['date', 'Apply the date at once', S2, {}]])
    T[k] = (await call('POST', '/api/tasks', {title, list_id: L, section_id: sec, ...extra})).id;
  await call('POST', `/api/tasks/${T.date}/complete`);
  await call('POST', '/api/tasks', {title: 'Milk', list_id: PLAIN});
  await call('POST', '/api/tasks', {title: 'Sitemap', list_id: W, due: day(2)});
  await tcall('PUT', '/agent/status', DEV.tok, {status: 'working', text: 'Status dots', task_id: T.dots});
  await tcall('PUT', '/agent/status', KOL.tok, {status: 'idle', text: 'Draft ready'});
  const J = (await tcall('POST', '/agent/jobs', KOL.tok, {title: 'Move #' + T.ppl + ' to Done?', task_id: T.ppl, state: 'waiting', log: 'review ready'})).id;
  check(J > 0, 'a waiting job of Kollege');

  // 2.99.0 (#2187): people and idle / offline agents only stand in the sidebar while pinned
  await call('PATCH', '/api/settings', {side_people: String(BOB), side_agents: String(ARC.id)});
  // ================= desktop (jsdom)
  let w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  check(!d.querySelector('#rail') && !d.querySelector('.rbtn'), 'no icon rail');
  for (const g of ['focus', 'views', 'lists', 'team']) check(d.querySelector(`#side .sg-${g} .sgh`), `sidebar group ${g}`);
  const reach = {cal: '#srail [data-sbb="cal"]', timeline: '#side [data-act="side-timeline"]', matrix: '#side [data-go="matrix"]', habits: '#srail [data-sbb="habits"]', pomo: '#srail [data-sbb="time"]',  // 2.44.0 (#1187): the areas Time + Review  // 2.152.2 (#2622): calendar, areas and Settings in the bar #srail
    time: '#srail [data-sbb="time"]', stats: '#srail [data-sbb="review"]', overview: '#side [data-go="overview"]', agents: '#srail [data-sbb="agents"]', news: '#side [data-go="news"]', search: '#kbar .kbsrch[data-act="palette"]' /* 2.152.3 (#2619): the search moved into the head bar */, settings: '#kbar .kbsw[data-act="sbb-ws"]' /* 2.380.2 (#3400): Settings in the Kalmido menu */};  // 2.152.2 (#2622): full selectors (#side or #srail)
  for (const [k, sel] of Object.entries(reach)) check(d.querySelector(sel), `sidebar reaches ${k}`);  // 2.152.2 (#2622): the selector says where
  check(d.querySelector('#top .ttabs [data-act="view-kanban"]') && d.querySelector('#top .ttabs [data-act="view-timeline"]'), 'kanban + timeline as text tabs in the list header');
  check(/Kanban/.test(d.querySelector('#top .ttabs').textContent), 'the view tabs are text');
  const today = d.querySelector('#side .srow[data-go="today"]');
  check(today && today.querySelector('.n').nextElementSibling?.classList.contains('c') && today.querySelector('.c').textContent.trim() === '2', 'counter right after the label (Today 2)');
  const lrow = d.querySelector(`#side .srow[data-list="${L}"]`);
  check(lrow && lrow.classList.contains('on') && (lrow.querySelector('.sw') || lrow.querySelector('.lic')) /* 2.38.0 (#1174): the icon carries the colour, no dot */ && /--p:\s*\d+%/.test(lrow.querySelector('.sprog')?.getAttribute('style') || '') && /done/.test(lrow.querySelector('.sprog')?.getAttribute('aria-label') || ''), 'list row: dot, on, the project\'s progress as a thin line (2.25.0, UX-07)');
  const team = d.querySelector('#side .sg-team');
  check(team && /Bob/.test(team.textContent) && /DevBot/.test(team.textContent) && team.querySelector('.hdot.hs-working') && team.querySelector('.hdot.hs-offline'), 'team: people + agents with status dots');
  check(d.querySelector('#top .hms') && /Beta/.test(d.querySelector('#top .hms').textContent), 'milestone in the header');
  check(d.querySelector('#kbar .kbsrch[data-act="palette"]') && !d.querySelector('#top .cmdbar') && !d.querySelector('#top .tnew[data-act="new-task"]') && d.querySelector('#view .qdock #qinput'), 'command bar; no second "New task" above the add bar (2.25.0, UX-32)');  // 2.152.3 (#2619): on a computer the command bar is the head bar's search, not in #top
  click(w, d.querySelector('#kbar .kbsrch')); await sleep(200);  // 2.152.3 (#2619): the head bar's search
  check(d.querySelector('.palette'), 'the command bar opens the palette');
  w.eval('closePalette()');
  check(!d.querySelector('#side .scmd'), 'one command bar: none left in the panel');  // 2.152.3 (#2619): the panel's search field is gone on a computer (the head bar's is the one)
  w.eval("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'n', bubbles: true}))"); await sleep(100);
  check(d.activeElement && d.activeElement.id === 'qinput', 'n focuses the add box');
  // agent band
  const band = await until(() => d.querySelector('#view .agband .agb-w'));
  check(band, 'agent band with the waiting job');
  const cells = [...d.querySelectorAll('#view .agband .agb-a')];
  check(cells.length === 3 && cells.some(c => c.classList.contains('hs-working') && c.textContent.includes('#' + T.dots)) && cells.some(c => c.classList.contains('hs-offline')), 'band: 3 agents, working one with its ticket, offline one');
  check(!d.querySelector('#top .hdot') && d.querySelector('#top .achip .abot'), 'no duplicate agent dots in the header while the band shows (the robot stays)');
  check(d.querySelector(`.trow[data-id="${T.dots}"] .chk.work`), 'row of the task an agent works on: working glyph');
  const ap = d.querySelector('#view .agband [data-act="job-do"][data-a="approve"]');
  check(ap && d.querySelector('#view .agband [data-act="job-do"][data-a="reject"]') && ap.querySelector('.thumb svg'), '👍 / ✕ on the waiting job');
  click(w, ap);
  check(await until(async () => (await tcall('GET', '/agent/jobs', KOL.tok)).data.find(j => j.id === J)?.state === 'running'), '👍 approves the job (running)');
  click(w, d.querySelector('#view .agband .agb-tog')); await sleep(200);
  check(d.querySelector('#view .agband.closed') && w.__store['tasks.agband'] === 'false', 'band folds, remembered on the device');
  check(!d.querySelector('#top .hdot'), 'folded band: still no header dots');
  click(w, d.querySelector('#view .agband .agb-tog')); await sleep(200);
  check(d.querySelector('#view .agband:not(.closed) .agb-cells'), 'band opens again');
  // rows: ticket gutter, glyph, selection bar
  const r1 = d.querySelector(`.trow[data-id="${T.kb}"]`);
  check(r1 && r1.querySelector('.chk.p5') && r1.querySelector('.tgut')?.textContent === '#' + T.kb, 'ticket list: gutter with #id + glyph (priority colour)');
  w.eval(`openDetail(${T.kb})`); await sleep(300);
  check(d.querySelector(`.trow.sel[data-id="${T.kb}"]`), 'selected row');
  w.eval('closeDetail()');
  w.close();
  w = await boot({user: 'alice', hash: 'l/' + PLAIN}); d = w.document;
  check(d.querySelector('.trow .chk') && !d.querySelector('.trow .tgut'), 'list without tickets: only the glyph');
  check(!d.querySelector('#view .agband'), 'list without agents: no band');
  // icons
  const icn = JSON.parse(w.eval('JSON.stringify(Object.keys(P).map(k => [k, ic(k)]))'));
  check(icn.length >= 96 && icn.every(([, s]) => /viewBox="0 0 20 20"/.test(s) && /<(path|circle)/.test(s)), 'icon set: every key drawn on the 20 grid');
  check(icn.filter(([, s]) => /class="d"/.test(s)).length >= 50, 'most icons carry the dot');
  const css = await require('./boot').allCss(); // 2.65.0 (#1824): + the module stylesheets
  check(/svg\.i\{[^}]*stroke-width:1\.6/.test(css) && /svg\.i \.d\{fill:var\(--dot,var\(--accent\)\)/.test(css), 'CSS: 1.6 strokes, dot in the accent');
  check(/--acc-l:#be185d/.test(css) && /--acc-d:#f472b6/.test(css), 'raspberry tokens (selectable since 2.11.0)');
  check(d.documentElement.dataset.accent === 'petrol', 'petrol = default accent (2.300.0, #3198; violet 2.11.0, #449)');
  // module gating: switched off -> gone from the sidebar
  await call('PATCH', '/api/settings', {features: 'kanban,collab,agents,comments,progress'});
  w.close();
  w = await boot({user: 'alice', hash: 'l/' + L}); d = w.document;
  for (const k of ['cal', 'matrix', 'habits', 'pomo', 'stats', 'time']) check(!d.querySelector(reach[k]), `module off: ${k} not in the sidebar`);  // 2.152.2 (#2622): full selectors
  check(!d.querySelector('#side [data-act="side-timeline"]') && !d.querySelector('#srail [data-sbb="cal"]'), 'timeline / calendar off: gone');  // 2.152.2 (#2622): the calendar is an icon of the bar
  check(d.querySelector('#srail [data-sbb="agents"]') && d.querySelector('#kbar .kbsw'), 'agents + settings (Kalmido menu) still there'); // 2.380.2 (#3400): Settings moved from the bottom of the bar into the Kalmido menu (#kbar .kbsw)  // 2.152.2 (#2622): agents and Settings in the bar
  w.close();
  await call('PATCH', '/api/settings', {features: ALL});
  // accent migration: mint (the old default) -> the default once (2.11.0: violet, 2.300.0: petrol); another colour stays
  // 2.143.0 (#2155): the appearance follows the account (the first device uploads its own) -> every boot below starts as a
  // never-saved account, so the device's own value is what is checked
  const lookReset = () => call('PATCH', '/api/settings', {look: ''});
  await lookReset();
  w = await boot({user: 'alice', hash: 'today', ls: {'tasks.accent': '"mint"'}}); d = w.document;
  check(d.documentElement.dataset.accent === 'petrol' && !w.__store['tasks.accent'] && w.__store['tasks.accentMig280'] === '1', 'mint device migrates to the default (petrol since 2.300.0)');
  w.close();
  await sleep(900); await lookReset();
  w = await boot({user: 'alice', hash: 'today', ls: {'tasks.accent': '"mint"', 'tasks.accentMig280': '1'}}); d = w.document;
  check(d.documentElement.dataset.accent === 'mint', 'mint picked again after the migration stays');
  w.close();
  await sleep(900); await lookReset();
  w = await boot({user: 'alice', hash: 'today', ls: {'tasks.accent': '"sky"'}}); d = w.document;
  check(d.documentElement.dataset.accent === 'sky', 'own accent choice stays');
  w.close();
  // phone (jsdom): tab bar with the new icons, no band (the header keeps the agent pill there)
  w = await boot({user: 'alice', hash: 'l/' + L, mobile: true}); d = w.document;
  check(d.querySelectorAll('#tabs button svg.i').length >= 3 && d.querySelector('#tabs svg[viewBox="0 0 20 20"]'), 'phone: tab bar with the Punkt icons');
  check(!d.querySelector('#view .agband') && d.querySelector('#top .achip, #top .stchip'), 'phone: no band, the header pill instead');
  check(d.querySelector('#side .scmd'), 'phone drawer: command bar');
  w.close();

  // ================= Firefox: real layout
  for (const touch of [true, false]) {
    await firefox(async ({cmd, ev, nav, ctx, shot}) => {
      await nav(B + 'static/icon.svg');
      const lgi = await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
      check(lgi === 200, 'Firefox: login');
      let nr = 0;
      const open = async (hash, theme) => {
        await nav(B + 'static/icon.svg');
        await ev(`(() => { localStorage.setItem('tasks.theme', '"${theme || 'dark'}"'); return 1; })()`);
        await nav(B + '?v=' + (++nr) + '#' + hash);
        for (let i = 0; i < 30 && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300);
        await sleep(1000);
      };
      const sizes = touch ? [[360, 780], [390, 844], [904, 904]] : [[1280, 800], [1440, 900], [1920, 1080]];
      for (const [vw, vh] of sizes) {
        await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
        for (const theme of ['dark', 'light']) {
          await open('l/' + L, theme);
          const lay = await ev(`(() => { const R = s => { const e = document.querySelector(s); if (!e || !e.offsetWidth) return null; const b = e.getBoundingClientRect(); return [Math.round(b.left), Math.round(b.width), Math.round(b.height)]; };
            return {sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth, side: R('#side'), rail: !!document.querySelector('#rail'), band: R('#view .agband'), menu: R('#top .menu'), tabs: R('#tabs'), row: R('.trow[data-id="${T.win}"]'), sideRail: document.querySelector('#app').classList.contains('side-rail'), srail: R('#srail')}; })()`);  // 2.152.2 (#2622): + the bar of the areas
          check(!lay.rail && lay.sw <= lay.cw + 1, `${vw}px ${theme}: no rail, no horizontal overflow ${JSON.stringify(lay)}`);
          if (vw < 900) check(lay.tabs && lay.menu && !lay.band, `${vw}px: tab bar + menu button, no band`);
          else if (touch) check(!lay.sideRail && lay.srail && lay.srail[0] === 0 && lay.side && Math.abs(lay.side[0] - lay.srail[1]) <= 1 && lay.band && !lay.tabs, `${vw}px Fold: narrow sidebar next to the list + band ${JSON.stringify(lay)}`);  // 2.152.2 (#2622): the bar left, the panel next to it
          else check(lay.srail && lay.srail[0] === 0 && lay.side && Math.abs(lay.side[0] - lay.srail[1]) <= 1 && Math.abs(lay.side[1] - 240) <= 2 && lay.band && !lay.menu && lay.row && Math.abs(lay.row[2] - 40) <= 2, `${vw}px: sidebar 240 px, band, 40 px rows ${JSON.stringify(lay)}`);  // 2.152.2 (#2622): the panel keeps the 240 px of the old sidebar, the bar (72 px) comes on top
          if (touch && lay.row) check(lay.row[2] >= 43.5, `${vw}px: rows >= 44 px on touch (${lay.row[2]})`);
          const cr = await ev(CONTRAST);
          check(+cr['--text'] >= 7 && +cr['--text2'] >= 4.5 && +cr['--muted'] >= 4.5 && +cr['--accent'] >= 4.5 && +cr.ink >= 4.5, `${vw}px ${theme}: contrast ${JSON.stringify(cr)}`);
          if (vw === 390 || vw === 1440) await shot(`p280-${vw}-${theme}.png`);
          if (touch) {
            const small = await ev(SMALL(vw < 900 ? '#tabs button, #top .iconbtn, #fab' : '#top .iconbtn, #top .menu, #view .agband button'));
            check(!small.length, `${vw}px ${theme}: touch targets >= 44 px ${JSON.stringify(small)}`);
          }
        }
        // the drawer (phones): opens and its rows are 44 px; the Fold: sidebar rows 44 px, and with the task panel open the
        // sidebar becomes a drawer behind the menu button
        if (touch && vw >= 900) {
          const small = await ev(SMALL('#side .srow'));
          check(!small.length, `${vw}px: sidebar rows >= 44 px ${JSON.stringify(small.slice(0, 4))}`);
          await ev(`(() => { openDetail(${T.win}); return 1; })()`); await sleep(600);
          const fl = await ev(`(() => ({rail: document.querySelector('#app').classList.contains('side-rail'), menu: !!document.querySelector('#top .menu')?.offsetWidth || !!document.querySelector('#srail .srpanel')?.offsetWidth}))()`);  // 2.152.3 (#2619): sidebar B opens the drawer with the panel button on top of the bar
          check(fl.rail && fl.menu, `${vw}px + task panel: sidebar as drawer with the menu button ${JSON.stringify(fl)}`);
          await ev(`(() => { document.querySelector('#top .menu').click(); return 1; })()`); await sleep(500);
          check(await ev(`document.querySelector('#side').classList.contains('open')`), `${vw}px: the drawer opens`);
          await shot(`p280-${vw}-fold-drawer.png`);
        } else if (touch) {
          await ev(`(() => { document.querySelector('#top .menu').click(); return 1; })()`); await sleep(500);
          const dr = await ev(`(() => { const s = document.querySelector('#side'); const b = s.getBoundingClientRect(); return {open: s.classList.contains('open'), left: Math.round(b.left)}; })()`);
          check(dr.open && dr.left >= -1, `${vw}px: the drawer opens ${JSON.stringify(dr)}`);
          const small = await ev(SMALL('#side .srow, #side .scmd'));
          check(!small.length, `${vw}px: drawer rows >= 44 px ${JSON.stringify(small.slice(0, 4))}`);
          if (vw === 390) await shot(`p280-${vw}-drawer.png`);
        }
      }
    }, touch);
  }

  check(!errs.length, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`p280_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})();
