// 2.60.0 part A UI test, own container (start.sh), Firefox (the real layout).
// #343 sprints: no sprint header while sprints are off; switched on in the list dialog the header appears above the list and
// the Kanban (name, dates, progress, burndown); the filter Current sprint / Backlog; a task into the sprint by its menu (one
// undo step); the multi-selection's Sprint field; closing with the review and "back to the backlog"; the phone folds it.
// Screenshots with P260A_SHOTS=<dir>.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p260_a_ui', check, shots: 'P260A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return Array.isArray(j) ? j : {...j, status: r.status}; };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,collab,agents,comments,progress,kanban'});
  const P = (await call('POST', '/api/lists', {name: 'Product', kind: 'project'})).id;
  const T = [];
  for (const t of ['Login page', 'Password reset', 'Signup mail', 'Profile']) T.push((await call('POST', '/api/tasks', {title: t, list_id: P})).id);

  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, sel, n = 40) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('${sel}')`).catch(() => false)); i++) await sleep(250); await sleep(500); };
  const rows = ev => ev(`[...document.querySelectorAll('#view .trow .ttl, #view .trow .title')].map(x => x.textContent.trim()).filter(Boolean)`);

  await firefox(async o => {
    const {ev, nav, cmd, shot} = o;
    await cmd('browsingContext.setViewport', {context: o.ctx, viewport: {width: 1280, height: 900}});
    check(await ffLogin(o) === 200, 'login');
    await nav(B + '#l/' + P); await ready(ev, '#view .trow');
    check(!(await ev(`!!document.querySelector('#view .sprh')`)), 'sprints off: no sprint header');
    // the list dialog: the Sprints row in the project area, switching on
    await ev(`(() => { listModal(${P}); return 1; })()`); await sleep(600);
    check(await ev(`!!document.querySelector('.modal #l-spr')`), 'the list dialog offers "Plan in sprints"');
    await ev(`(() => { const x = document.querySelector('.modal #l-spr'); x.checked = true; x.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    await sleep(1500);
    await ev(`(() => { document.querySelectorAll('.modal').forEach(m => m.remove()); return 1; })()`);
    const st = await call('GET', `/api/lists/${P}/sprints`);
    check(st.settings?.on === true && st.active_id, 'switched on in the dialog: sprint 1 runs ' + JSON.stringify(st).slice(0, 160));
    const S1 = st.active_id;
    await nav(B + '#l/' + P); await ready(ev, '#view .sprh');
    check(await ev(`!!document.querySelector('#view .sprh[data-sprdrop="${S1}"]') && document.querySelector('#view .sprh .sprtg b').textContent === 'Sprint 1'`), 'the sprint header shows Sprint 1');
    // a task into the sprint by its menu, one undo step
    await ev(`(() => { taskMenu(document.querySelector('#view .trow[data-id="${T[0]}"]'), ${T[0]}); return 1; })()`); await sleep(400);
    const hasItem = await ev(`[...document.querySelectorAll('[role="menuitem"]')].some(b => b.textContent.includes('Sprint…'))`);
    check(hasItem, 'the task menu has "Sprint…"');
    await ev(`(() => { [...document.querySelectorAll('[role="menuitem"]')].find(b => b.textContent.includes('Sprint…'))?.click(); return 1; })()`); await sleep(400);
    await ev(`(() => { [...document.querySelectorAll('[role="menuitem"]')].find(b => b.textContent.includes('Sprint 1'))?.click(); return 1; })()`); await sleep(1500);
    let t0 = await call('GET', `/api/tasks/${T[0]}`);
    check(t0.sprint_id === S1, 'the menu put the task into the sprint ' + JSON.stringify(t0).slice(0, 120));
    await ev(`(() => { histStep('undo'); return 1; })()`); await sleep(1500);
    t0 = await call('GET', `/api/tasks/${T[0]}`);
    check(!t0.sprint_id, 'one undo takes it back out');
    // two more through the multi-selection's field (the panel's own apply)
    await ev(`(async () => { S.multi = new Set([${T[0]}, ${T[1]}]); await meApply('sprint', t => t.sprint_id !== ${S1} ? {sprint_id: ${S1}} : null, 'Sprint'); return 1; })()`); await sleep(1500);
    check((await call('GET', `/api/tasks/${T[1]}`)).sprint_id === S1, 'the multi-selection puts tasks into the sprint');
    await ev(`(() => { S.multi = new Set(); S.multiMode = false; render(); return 1; })()`); await sleep(500);
    // the filter
    await ev(`(() => { document.querySelector('#view .sprseg [data-v="cur"]').click(); return 1; })()`); await sleep(700);
    let r = await rows(ev);
    check(r.includes('Login page') && r.includes('Password reset') && !r.includes('Profile'), 'filter Current sprint: only the sprint tasks ' + r);
    await ev(`(() => { document.querySelector('#view .sprseg [data-v="back"]').click(); return 1; })()`); await sleep(700);
    r = await rows(ev);
    check(!r.includes('Login page') && r.includes('Profile') && r.includes('Signup mail'), 'filter Backlog: only tasks without a sprint ' + r);
    await ev(`(() => { document.querySelector('#view .sprseg [data-v=""]').click(); return 1; })()`); await sleep(700);
    // progress + burndown open on the desktop
    await call('POST', `/api/tasks/${T[0]}/complete`);  // as from another device: the app's next state reload brings it
    await ev(`(async () => { await load(); render(); return 1; })()`); await ready(ev, '#view .sprh'); await sleep(1500);
    const pg = await ev(`document.querySelector('#view .sprh .sprp')?.textContent || ''`);
    check(/1 of 2 done/.test(pg), 'progress 1 of 2 done: ' + pg);
    check(await ev(`!!document.querySelector('#view .sprh .sprbody')`), 'desktop: the header is open (goal / burndown)');
    await shot('p260a-list-1280.png');
    // the Kanban has the header too
    await ev(`(async () => { await setListView(listById(${P}), 'kanban'); render(); return 1; })()`); await ready(ev, '#view .kanban');
    check(await ev(`!!document.querySelector('#view .sprh') && !!document.querySelector('#view .kanban')`), 'the Kanban shows the sprint header');
    await shot('p260a-kanban-1280.png');
    await ev(`(async () => { await setListView(listById(${P}), 'list'); render(); return 1; })()`); await sleep(500);
    // closing with the review, open tasks back to the backlog
    await nav(B + '#l/' + P); await ready(ev, '#view .sprh');
    await ev(`(() => { document.querySelector('#view .sprh [data-spr="close"]').click(); return 1; })()`); await sleep(600);
    const rv = await ev(`document.querySelector('.modal .sprrv')?.textContent || ''`);
    check(/1\s*done/.test(rv) && /1\s*still open/.test(rv), 'the close dialog shows the review ' + rv);
    await shot('p260a-close-1280.png');
    await ev(`(() => { document.querySelector('.modal input[name="sp-to"][value="backlog"]').checked = true; document.querySelector('.modal [data-m="ok"]').click(); return 1; })()`); await sleep(1500);
    const after = await call('GET', `/api/lists/${P}/sprints`);
    const s1 = (after.sprints || []).find(s => s.id === S1);
    check(s1?.state === 'closed' && s1.review?.moved?.includes(T[1]), 'closed with the review ' + JSON.stringify(s1?.review || {}).slice(0, 160));
    check(!(await call('GET', `/api/tasks/${T[1]}`)).sprint_id, 'the open task went back to the backlog');
    check(await ev(`document.querySelector('#view .sprh .sprtg b')?.textContent === 'Sprint 2'`), 'the header shows the next sprint');
  }, false);

  // the phone: the header folds away (no burndown until tapped), the filter stays reachable
  await firefox(async o => {
    const {ev, nav, cmd, shot} = o;
    await cmd('browsingContext.setViewport', {context: o.ctx, viewport: {width: 390, height: 844}});
    check(await ffLogin(o) === 200, 'phone: login');
    await nav(B + '#l/' + P); await ready(ev, '#view .sprh');
    check(!(await ev(`!!document.querySelector('#view .sprh .sprbody')`)), 'phone: the header starts folded');
    const w = await ev(`(() => { const r = document.querySelector('#view .sprseg').getBoundingClientRect(); return r.right <= window.innerWidth + 1 && r.height >= 30; })()`);
    check(w, 'phone: the filter fits and has big targets');
    const one = await ev(`[...document.querySelectorAll('#view .sprseg button')].every(b => b.getBoundingClientRect().height < 44)`);
    check(one, 'phone: the filter labels stay on one line');
    await ev(`(() => { document.querySelector('#view .sprh [data-spr="tog"]').click(); return 1; })()`); await sleep(700);
    check(await ev(`!!document.querySelector('#view .sprh .sprbody')`), 'phone: a tap on the name opens it');
    await shot('p260a-phone-390.png');
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
