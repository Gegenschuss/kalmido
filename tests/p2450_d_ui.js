// 2.45.0 UI tests, part D (#1504 the start page as in the approved draft), own container (start.sh). jsdom:
// - one sentence on top with the numbers ("4 tasks for today, 1 overdue, 1 agent working."), nothing open = a calm sentence
// - Today: the box adds a task for today (one undo step), the list as a label, overdue in red
// - News compact: at most 5 lines, one per bundle, "All news"; only active projects, at most 5, "Active projects"
// - empty cards are one slim line ("Pinned: nothing"); the agents card lists both running jobs with "since HH:MM"
// - Search hidden by default; the default arrangement is two columns (Today + News wide, the rest narrow)
// - an own arrangement keeps its order and visible cards (Search too) and gets the compact cards
// Firefox: 1280 dark + light: two columns that stack on their own, the app font, links without underline; 390: one column
// in the order sentence, Today, Agents, News, Projects. Screenshots into $P2450D_SHOTS.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2450_d_ui', check, shots: 'P2450D_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK, hd = {}) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {}), ...hd}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const FEAT = 'cal,comments,collab,time,progress,agents,team';
// 2.180.0 B (#2693): calendar days in Berlin - "now - 24 h" was today again on the 25-hour day in October (23-24 o'clock)
const TC = require('./testclock');
const T0 = TC.today(), Y = TC.day(-1);
const txt = (d, s) => (d.querySelector(s)?.textContent || '').replace(/\s+/g, ' ').trim();

(async () => {
  await sleep(600);
  let r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  // a calm start: nothing due, no agent
  let w = await boot({user: 'alice', hash: 'home'}), d = w.document;
  await until(() => d.querySelector('#view .hpsum'));
  check(txt(d, '.hpsum') === 'Nothing due today.', '#1504: nothing open = a calm sentence: ' + txt(d, '.hpsum'));
  w.close();

  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Baker', password: 'password123'})).id;
  const BCK = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, BCK);
  // seven active projects, one complete, one on hold
  const P = [];
  for (const n of ['Spring shoot', 'Image film', 'Website new', 'Brochure', 'Trade fair', 'Podcast', 'Newsletter']) P.push((await call('POST', '/api/lists', {name: n, kind: 'project'})).id);
  for (const [n, st] of [['Old catalogue', 'complete'], ['Paused idea', 'on_hold']]) { const id = (await call('POST', '/api/lists', {name: n, kind: 'project'})).id; await call('POST', `/api/lists/${id}/status`, {status: st, note: ''}); }
  const done = (await call('POST', '/api/tasks', {title: 'Pick the location', list_id: P[0]})).id;
  await call('POST', `/api/tasks/${done}/complete`);
  // four tasks for today: one overdue, one with a time in a project, two in the basket
  await call('POST', '/api/tasks', {title: 'Follow up the sample offer', due: Y});
  await call('POST', '/api/tasks', {title: 'Agree the shooting plan', list_id: P[0], due: T0, due_time: '10:00'});
  await call('POST', '/api/tasks', {title: 'Upload the receipts', due: T0});
  await call('POST', '/api/tasks', {title: 'Look at the rough cut', list_id: P[1], due: T0});
  // seven tasks bob comments on (seven news bundles)
  const SH = (await call('POST', '/api/lists', {name: 'Shared work'})).id;
  await call('PUT', `/api/lists/${SH}/members`, {user_id: BOB, role: 'edit'});
  for (let i = 1; i <= 7; i++) { const t = (await call('POST', '/api/tasks', {title: 'Shared task ' + i, list_id: SH})).id; await call('POST', `/api/tasks/${t}/comments`, {body: 'Looks good ' + i}, BCK); }
  // an agent with two running jobs
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write'], username: 'claude', display_name: 'Claude'});
  const AGH = {Authorization: 'Bearer ' + ag.token};
  await call('PUT', `/api/lists/${P[0]}/members`, {user_id: ag.id, role: 'edit'});
  for (const t of ['Release build part A', 'Check the receipts']) await call('POST', '/api/v1/agent/jobs', {title: t}, null, AGH);

  // ================= jsdom: the default start page
  w = await boot({user: 'alice', hash: 'home'}); d = w.document;
  await until(() => d.querySelectorAll('.dc-agents .djob').length >= 2 && d.querySelector('.dc-news .hpnl'));
  // 2.144.0 (#2418): the sentence names the running jobs of the working agents too
  check(txt(d, '.hpsum') === '4 tasks for today, 1 overdue, 1 agent working (2 jobs).' && d.querySelectorAll('.hpsum b').length === 4, '#1504: the sentence with the numbers: ' + txt(d, '.hpsum'));
  const grid = d.querySelector('.dgrid.lysix[data-ly="home"]');
  check(grid?.classList.contains('hpcols') && d.querySelector('.hpcol.hpl .dc-today') && d.querySelector('.hpcol.hpl .dc-news') && d.querySelector('.hpcol.hpr .dc-agents') && d.querySelector('.hpcol.hpr .dc-projects'), '#1504: two columns: Today + News wide, Agents + Projects narrow');
  check(!d.querySelector('.dc-search'), '#1504: Search hidden by default');
  const order = [...d.querySelectorAll('.lyb[data-lyk]')].sort((a, b) => +a.style.order - +b.style.order).map(b => b.dataset.lyk);
  check(order.slice(0, 4).join() === 'today,agents,news,projects', '#1504: the order (the phone shows it like this) ' + order.join());
  // Today
  const today = d.querySelector('.dc-today');
  check(today.querySelectorAll('.dtl li').length === 4 && /Spring shoot/.test(today.querySelector('.dtl').textContent) && today.querySelector('.dt.over')?.textContent === 'Yesterday', '#1504: Today: 4 tasks, the list as a label, overdue in red');
  check([...today.querySelectorAll('.dtl li')].some(li => li.querySelector('.dt')?.textContent === w.eval(`fmtTimeLoc('10:00')`)), '#1504: a time shows as the time');
  const inp = d.querySelector('#hp-add');
  check(inp && inp.getAttribute('aria-label') === 'New task for today', '#1504: the box to add a task for today');
  inp.value = 'Call the printer'; inp.closest('form').dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true}));
  let nt = await until(async () => (await call('GET', '/api/state')).tasks.find(t => t.title === 'Call the printer' && !t.deleted_at));
  check(nt && nt.due === T0, '#1504: the box creates a task due today ' + JSON.stringify(nt && {due: nt.due, list: nt.list_id}));
  await until(() => d.querySelectorAll('.dc-today .dtl li').length === 5);
  check(d.querySelectorAll('.dc-today .dtl li').length === 5 && txt(d, '.hpsum').startsWith('5 tasks for today'), '#1504: ... and shows it in Today and in the sentence');
  await w.eval(`histStep('undo')`);
  const gone = await until(async () => !(await call('GET', '/api/state')).tasks.some(t => t.title === 'Call the printer'));
  check(gone, '#1504: one undo step takes the new task away');
  // News compact
  const nl = [...d.querySelectorAll('.dc-news .hpnl li')];
  check(nl.length === 5 && d.querySelector('.dc-news a.hpall[href="#news"]')?.textContent === 'All news' && !d.querySelector('.dc-news .ngroup'), '#1504: News: at most 5 lines and "All news" ' + nl.length);
  check(nl.every(li => li.querySelector('time.hpt')) && /Shared task/.test(nl[0].textContent), '#1504: one line per bundle with its time');
  // projects
  const pl = [...d.querySelectorAll('.dc-projects .dpl li')].map(li => li.textContent);
  check(pl.length === 5 && !pl.some(x => /Old catalogue|Paused idea/.test(x)) && /Active projects/.test(txt(d, '.dc-projects h3')), '#1504: only active projects, at most 5 ' + JSON.stringify(pl));
  check(d.querySelector('.dc-projects .dpb[role="img"]') && pl.some(x => /Spring shoot.*50 %/.test(x)), '#1504: with their progress');
  // slim cards
  check(d.querySelector('.dc-pinned.dempty') && txt(d, '.dc-pinned') === 'Pinned: nothing' && d.querySelector('.dc-wait.dempty') && txt(d, '.dc-wait') === 'Waiting for you: nothing', '#1504: empty cards are one slim line');
  check([...d.querySelectorAll('.dcard')].every(c => c.getAttribute('aria-labelledby') && c.querySelector('h3')), '#1504: every card still a named section');
  // agents
  const jobs = [...d.querySelectorAll('.dc-agents .djob')];
  check(jobs.length === 2 && jobs.every(j => /^since \d{1,2}:\d\d(\s?[AP]M)?$/i.test(j.querySelector('.hpt')?.textContent || '')), '#1504: the agents card: both running jobs, "since HH:MM" ' + jobs.map(j => j.textContent).join(' | '));  // 2.368.0 (#2982): the time as the app shows times (12 h in an en-US browser)
  w.close();

  // ================= an own arrangement keeps its order and cards, the cards are compact
  await call('PATCH', '/api/settings', {dashboard: JSON.stringify({order: ['wait', 'today', 'news', 'chat', 'projects', 'pinned', 'notes', 'agents', 'stats', 'search'], hidden: ['stats']})});
  w = await boot({user: 'alice', hash: 'home'}); d = w.document;
  await until(() => d.querySelector('.dc-news .hpnl'));
  const own = [...d.querySelectorAll('.dgrid .lyb[data-lyk]')].map(b => b.dataset.lyk);
  check(own[0] === 'wait' && own.includes('search') && !own.includes('stats') && !d.querySelector('.hpcols'), '#1504: the own arrangement stays (order, Search shown, Statistics hidden) ' + own.join());
  check(d.querySelector('.dc-news .hpnl') && d.querySelector('.dc-pinned.dempty') && d.querySelector('#hp-add'), '#1504: ... with the compact cards');
  w.close();
  await call('PATCH', '/api/settings', {dashboard: ''});

  // ================= Firefox
  const ffLogin = async ({ev, nav}, theme) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); ${theme ? `localStorage.setItem('tasks.theme', '"${theme}"');` : ''} return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async ev => { for (let i = 0; i < 30 && !(await ev(`document.querySelectorAll('.dc-agents .djob').length >= 2 && !!document.querySelector('.dc-news .hpnl')`).catch(() => false)); i++) await sleep(300); await sleep(900); };
  const BOX = `(() => { const r = s => { const e = document.querySelector(s); if (!e) return null; const b = e.getBoundingClientRect(); return {l: Math.round(b.left), t: Math.round(b.top), b: Math.round(b.bottom), w: Math.round(b.width)}; };
    const tm = document.querySelector('.dc-news time'), a = document.querySelector('.dc-news a.hpall'), dt = document.querySelector('.dc-today .dt');
    return {sum: r('.hpsum'), today: r('.dc-today'), agents: r('.dc-agents'), news: r('.dc-news'), projects: r('.dc-projects'), sw: document.documentElement.scrollWidth,
      font: [tm, dt].map(e => e && getComputedStyle(e).fontFamily).join('|'), ul: a && getComputedStyle(a).textDecorationLine}; })()`;
  for (const th of ['dark', 'light']) {
    if (process.env.NOFF) break;
    await firefox(async o => {
      const {cmd, ev, ctx, shot} = o, tag = '1280 ' + th;
      check(await ffLogin(o, th) === 200, tag + ': login');
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 800}});
      await o.nav(B + '#home'); await ready(ev);
      const m = await ev(BOX);
      check(m.today && m.agents && m.agents.l > m.today.l + m.today.w - 5 && Math.abs(m.agents.t - m.today.t) < 4 && m.today.w > m.agents.w * 1.6, `${tag}: #1504 two columns, Today wide, Agents narrow beside it ${JSON.stringify(m)}`);
      check(m.projects && m.projects.t - m.agents.b < 30 && m.news.l === m.today.l, `${tag}: #1504 each column stacks on its own (Projects right under Agents)`);
      check(!/mono/i.test(m.font) && m.ul === 'none' && m.sw <= 1280, `${tag}: #1504 the app font, no underline, nothing sideways ${m.font} ${m.ul}`);
      await shot(`p2450d-1280-${th}.png`);
    }, false);
  }
  if (!process.env.NOFF) await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '390';
    check(await ffLogin(o) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + '#home'); await ready(ev);
    const m = await ev(BOX);
    check(m.today && m.agents && m.today.l === m.agents.l && m.agents.l === m.news.l && m.sum.t < m.today.t && m.today.t < m.agents.t && m.agents.t < m.news.t && m.news.t < m.projects.t && m.sw <= 390,
      `${tag}: #1504 one column: sentence, Today, Agents, News, Projects ${JSON.stringify(m)}`);
    await shot('p2450d-390.png');
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
