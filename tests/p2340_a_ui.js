// 2.34.0 UI tests, part A, own container. Firefox, 390 x 844 touch:
// #264 the briefing as the first block of Today: the numbers, "New since yesterday" (another person's comment), "Blocked";
//      "Read" folds it for the day (stored on the server: a reload keeps it folded), the folded line opens it again;
//      a person with a saved Today arrangement gets the new block on top too; Settings > Notifications "Morning briefing at"
// #265 the project page: "Status report" opens the dialog with the preview (Markdown), 7 / 14 / 30 days, from / to, Copy;
//      buttons >= 44 px on the phone
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2340_a_ui', check, shots: 'P2340A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const FEAT = 'cal,comments,collab,time,progress,agents,kanban,timeline,fields,deps';
const day = n => new Date(Date.now() + n * 86400000).toLocaleDateString('sv', {timeZone: 'Europe/Berlin'});  // the app's day (TZ of the container), also between 0 and 2 o'clock

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Baker', password: 'password123'})).id;
  const BCK = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, BCK);
  const P = (await call('POST', '/api/lists', {name: 'Website', kind: 'project'})).id;
  await call('PUT', `/api/lists/${P}/members`, {user_id: BOB, role: 'edit'});
  const t1 = (await call('POST', '/api/tasks', {title: 'Call the printer', list_id: P, due: day(0)})).id;
  await call('POST', '/api/tasks', {title: 'Send the offer', list_id: P, due: day(-1)});
  const tw = (await call('POST', '/api/tasks', {title: 'Texts from the client', list_id: P})).id;
  await call('PUT', `/api/tasks/${tw}/waiting`, {note: 'Client Miller'});
  const tc = (await call('POST', '/api/tasks', {title: 'Logo variants', list_id: P})).id;
  await call('POST', `/api/tasks/${tc}/comments`, {body: 'First drafts are in'}, BCK);
  const td = (await call('POST', '/api/tasks', {title: 'Domain', list_id: P})).id;
  await call('POST', `/api/tasks/${td}/complete`, undefined, BCK);
  await call('POST', '/api/tasks', {title: 'Launch', list_id: P, due: day(4), ms: true});

  const ffLogin = async ({ev, nav}, user = 'alice') => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${user}', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  const brief = ev => ev(`(() => { const c = document.querySelector('.bfcard'); if (!c) return null; const lyb = c.closest('.lyb');
    return {fold: c.classList.contains('fold'), nums: c.querySelector('.rvnums')?.textContent || c.querySelector('.rvfn')?.textContent || '',
      first: !!lyb && lyb === document.querySelector('[data-ly="today"] > .lyb'), heads: [...c.querySelectorAll('h4')].map(x => x.textContent).join('|'),
      items: [...c.querySelectorAll('.bfl a')].map(x => x.textContent).join('|'), readH: c.querySelector('[data-brief="read"]')?.getBoundingClientRect().height || 0,
      openH: c.querySelector('[data-brief="open"]')?.getBoundingClientRect().height || 0}; })()`);
  await firefox(async o => {
    const {cmd, ev, ctx, shot, nav} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    check(await ffLogin(o) === 200, 'login alice');
    await nav(B + '#today'); await ready(ev); await sleep(1200);
    let b = await brief(ev);
    check(b && !b.fold && b.first, '#264: the briefing is the first block of Today ' + JSON.stringify(b));
    check(b && /1 due today/.test(b.nums) && /1 overdue/.test(b.nums) && /1 blocked/.test(b.nums) && /2 new since yesterday/.test(b.nums), '#264: the numbers ' + JSON.stringify(b && b.nums));
    check(b && b.heads === 'New since yesterday|Blocked' && /Logo variants/.test(b.items) && /Domain/.test(b.items) && /Texts from the client/.test(b.items), '#264: the short lists ' + JSON.stringify(b));
    check(b && !/Call the printer/.test(b.items), '#264: today\'s tasks are not repeated (Today lists them)');
    check(b && b.readH >= 44, '#264: "Read" >= 44 px on the phone ' + (b && b.readH));
    const txt = await ev(`document.querySelector('.bfcard').textContent`);
    check(/Bob Baker/.test(txt) && /new comment/.test(txt) && /waiting on: Client Miller/.test(txt), '#264: who and what ' + txt.slice(0, 300));
    await shot('p2340a-390-briefing.png');
    await ev(`(() => { document.querySelector('[data-brief="read"]').click(); return 1; })()`); await sleep(1200);
    b = await brief(ev);
    check(b && b.fold && /1 due today/.test(b.nums) && b.openH >= 44, '#264: Read folds it to one line ' + JSON.stringify(b));
    const st = await call('GET', '/api/briefing');
    check(st.read === true, '#264: read is stored on the server');
    await nav(B + '#today'); await ready(ev); await sleep(1200);
    b = await brief(ev);
    check(b && b.fold, '#264: after a reload it stays folded (server state) ' + JSON.stringify(b));
    await ev(`(() => { document.querySelector('[data-brief="open"]').click(); return 1; })()`); await sleep(600);
    b = await brief(ev);
    check(b && !b.fold && b.readH === 0 && await ev(`document.activeElement?.dataset?.brief === 'close'`), '#264: the folded line opens it again (focus on the fold button) ' + JSON.stringify(b));
    // a saved Today arrangement from before 2.34: the new block still comes first
    await call('PATCH', '/api/settings', {view_today: JSON.stringify({order: ['wait', 'review', 'overdue', 'events', 'tasks', 'inbox'], hidden: []})});
    await call('POST', '/api/briefing/read', {read: false});
    await nav(B + '#today'); await ready(ev); await sleep(1200);
    b = await brief(ev);
    check(b && b.first, '#264: a saved arrangement gets the new block on top ' + JSON.stringify(b));
    // Settings > Notifications
    await ev(`(() => { settingsModal('notify'); return 1; })()`); await sleep(1200);
    const s = await ev(`(() => { const i = document.querySelector('#s-brief'); return i ? {lab: document.querySelector('label[for="s-brief"]')?.textContent, v: i.value} : null; })()`);
    check(s && s.lab === 'Morning briefing at' && s.v === '', '#264: the push time in the notification settings, off by default ' + JSON.stringify(s));
    await ev(`(() => { document.querySelectorAll('.modal, .mwrap').forEach(m => m.remove()); return 1; })()`);

    // ================= #265 the status report on the project page
    await nav(B + '#l/' + P); await ready(ev);
    await ev(`(() => { setListView(listById(${P}), 'overview'); return 1; })()`); await sleep(1800);
    const btn = await ev(`(() => { const b = document.querySelector('[data-rpt="open"]'); return b ? {t: b.textContent.trim(), h: b.getBoundingClientRect().height} : null; })()`);
    check(btn && btn.t === 'Status report', '#265: the button on the project page ' + JSON.stringify(btn));
    await ev(`(() => { document.querySelector('[data-rpt="open"]').click(); return 1; })()`); await sleep(1800);
    const m = await ev(`(() => { const md = document.querySelector('.rptmodal'); if (!md) return null; const p = md.querySelector('#rpt-prev');
      return {h1: p.querySelector('h4')?.textContent, h2: [...p.querySelectorAll('h5')].map(x => x.textContent).join('|'), on: md.querySelector('[data-rpt="days"].on')?.textContent,
        from: md.querySelector('#rpt-from').value, to: md.querySelector('#rpt-to').value, copyH: md.querySelector('[data-rpt="copy"]').getBoundingClientRect().height,
        segH: Math.min(...[...md.querySelectorAll('[data-rpt="days"]')].map(x => x.getBoundingClientRect().height)), txt: p.textContent}; })()`);
    check(m && m.h1 === 'Status report: Website' && /Completed \(1\)/.test(m.h2) && /Blocked \(1\)/.test(m.h2) && /Next dates/.test(m.h2), '#265: the preview ' + JSON.stringify(m));
    check(m && m.on === '7 days' && m.from === day(-6) && m.to === day(0), '#265: the last 7 days by default ' + JSON.stringify(m && [m.on, m.from, m.to]));
    check(m && m.copyH >= 44 && m.segH >= 44, '#265: buttons >= 44 px ' + JSON.stringify(m && [m.copyH, m.segH]));
    check(m && !/First drafts|Bob/.test(m.txt), '#265: no comments or names in the text');
    await shot('p2340a-390-report.png');
    await ev(`(() => { document.querySelector('[data-rpt="days"][data-n="30"]').click(); return 1; })()`); await sleep(1500);
    const m2 = await ev(`({from: document.querySelector('#rpt-from').value, on: document.querySelector('[data-rpt="days"].on')?.textContent})`);
    check(m2.from === day(-29) && m2.on === '30 days', '#265: 30 days ' + JSON.stringify(m2));
    await ev(`(() => { const f = document.querySelector('#rpt-from'); f.value = '${day(-60)}'; f.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`); await sleep(1500);
    const m3 = await ev(`({from: document.querySelector('#rpt-from').value, on: !!document.querySelector('[data-rpt="days"].on')})`);
    check(m3.from === day(-60) && !m3.on, '#265: an own period ' + JSON.stringify(m3));
    await ev(`(() => { window.__copied = null; try { Object.defineProperty(navigator, 'clipboard', {value: {writeText: t => { window.__copied = t; return Promise.resolve(); }}, configurable: true}); } catch (e) {} document.querySelector('[data-rpt="copy"]').click(); return 1; })()`); await sleep(600);
    const cp = await ev(`window.__copied`);
    check(typeof cp === 'string' && cp.startsWith('# Status report: Website'), '#265: Copy puts the Markdown on the clipboard ' + String(cp).slice(0, 80));
    await ev(`(() => { document.querySelector('.rptmodal [data-m="close"]').click(); return 1; })()`); await sleep(400);
    check(!(await ev(`!!document.querySelector('.rptmodal')`)), '#265: Close closes it');
  });
  console.log(`p2340_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
