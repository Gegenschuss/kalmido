// D3 UI tests (jsdom), fresh DB: no entry point of a switched-off module shows anywhere. With every module on, each
// entry point is there (so the absence checks mean something); then each module is switched off on its own and its
// buttons, menu items, keyboard shortcuts, command palette entries, running indicator, settings section, views and
// links must be gone; the action endpoints of focus, habits and time tracking refuse with 409 (the data stays).
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const ds = n => { const t = new Date(), d = new Date(t.getFullYear(), t.getMonth(), t.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
const ALL = 'cal,timeline,matrix,habits,pomo,kanban,paperless,collab,stats,time,progress,deps,fields,comments';

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  await call('PATCH', '/api/settings', {features: ALL});
  const P = (await call('POST', '/api/lists', {name: 'Launch', kind: 'project'})).id;
  await call('PUT', `/api/lists/${P}/members`, {user_id: BOB, role: 'edit'});
  const T = (await call('POST', '/api/tasks', {title: 'Write brief', list_id: P, due: ds(0), start: ds(-1)})).id;
  const T2 = (await call('POST', '/api/tasks', {title: 'Review', list_id: P, due: ds(2)})).id;
  await call('POST', '/api/deps', {task_id: T2, blocker_id: T});
  await call('POST', '/api/lists/' + P + '/fields', {name: 'Budget', type: 'number'});
  const HB = (await call('POST', '/api/habits', {name: 'Walk'})).id;

  // what each module offers: selector / probe -> must exist with the module on, be gone with it off
  const probes = {
    pomo: [['sidebar link', d => d.querySelector('#side [data-go="pomo"]')],
      ['palette entries', (d, w) => w.eval("palAll().some(x => x.id === 'a:focus' || x.id === 'v:pomo')")], ['shortcut g f', (d, w) => w.eval("JSON.stringify(SHORTCUTS()).includes('g f')")],
      ['settings options', (d, w) => w.eval("(settingsModal('modules'), !!document.querySelector('.smodal [data-modrow=\"pomo\"]:not(.off) #s-pf'))")],
      ['running indicator', (d, w) => w.eval("(() => { const p = S.pomo; S.pomo = {id: 9, kind: 'focus', started_at: new Date().toISOString(), minutes: 25}; const n = runItems().length; S.pomo = p; return n > 0; })()")],
      ['task menu item', (d, w) => { w.eval(`taskMenu(document.querySelector('#top h1'), ${T})`); const x = /Start focus session/.test(d.querySelector('#pop')?.textContent || ''); w.eval('closePop()'); return x; }]],
    habits: [['sidebar link', d => d.querySelector('#side [data-go="habits"]')], ['palette', (d, w) => w.eval("palAll().some(x => x.id === 'a:newhabit' || x.id === 'v:habits')")],
      ['shortcut g h', (d, w) => w.eval("JSON.stringify(SHORTCUTS()).includes('g h')")]],
    time: [['timer button', d => d.querySelector('#detail [data-act="timer-toggle"]')], ['time section', d => d.querySelector('#d-time')], ['sidebar link', d => d.querySelector('#side [data-go="time"]')],
      ['palette', (d, w) => w.eval("palAll().some(x => x.id === 'a:addtime' || x.id === 'v:time')")]],
    stats: [['sidebar link', d => d.querySelector('#side [data-go="stats"]')], ['palette', (d, w) => w.eval("palAll().some(x => x.id === 'v:stats')")]],
    kanban: [['list view switch', d => d.querySelector('#top [data-act="view-kanban"]')]],
    timeline: [['list view switch', d => d.querySelector('#top [data-act="view-timeline"]')], ['calendar mode', (d, w) => w.eval("calBar('x').includes('data-k=\"timeline\"')")],
      ['roadmap switch', (d, w) => w.eval("(() => { const r = S.route; S.route = {mod: 'tasks', key: 'all'}; renderTop(); const x = !!document.querySelector('#top [data-act=\"rm-view\"]'); S.route = r; renderTop(); return x; })()")],
      ['Timeline shortcuts', (d, w) => w.eval("SHORTCUTS().some(([g]) => g === 'Timeline')")]],
    matrix: [['sidebar link', d => d.querySelector('#side [data-go="matrix"]')], ['palette', (d, w) => w.eval("palAll().some(x => x.id === 'v:matrix')")]],
    cal: [['sidebar link', d => d.querySelector('#side [data-go="cal"]')], ['shortcut g c', (d, w) => w.eval("JSON.stringify(SHORTCUTS()).includes('g c')")], ['go key', (d, w) => w.eval("GO_KEYS.c() !== false")]],
    deps: [['dependency section', d => d.querySelector('#d-deps')], ['waiting mark', d => d.querySelector('#view .blk')]],
    fields: [['custom fields', d => d.querySelector('#detail .cfsec')], ['list dialog', (d, w) => { w.eval(`listModal(${P})`); const x = !!d.querySelector('.modal #l-fields'); d.querySelectorAll('.modal').forEach(m => m.remove()); return x; }]],
    progress: [['progress bar', d => d.querySelector('#view .lhead .lprog')]],
    collab: [['bell', d => d.querySelector('#top .bell')], ['activity switch', (d, w) => { d.querySelector('#d-tl [data-act="tl-menu"]')?.click(); const x = !!d.querySelector('#pop .mtlact'); w.eval('closePop()'); return x; }], ['assignee', d => d.querySelector('#detail .dwho')]],  // 2.31.0 (#1054): the switch is in the "…", the assignee the chip
    comments: [['comment section', d => d.querySelector('#d-tl')], ['comment box', d => d.querySelector('#c-input')]],  // 2.0.6 (#315): a module of its own
  };
  const run = async (feats, label, want) => {
    await call('PATCH', '/api/settings', {features: feats});
    const w = await boot({user: 'alice', hash: 'l/' + P}); const d = w.document;
    w.eval(`openDetail(${T})`); await sleep(300);
    for (const [mod, list] of Object.entries(probes)) {
      if (want === 'on' || mod === label) for (const [name, fn] of list) {
        let v; try { v = !!(await fn(d, w)); } catch (e) { v = 'error ' + e.message; }
        if (want === 'on') check(v === true, `all on: ${mod} ${name} is there (${v})`);
        else check(v === false, `${mod} off: ${name} gone (${v})`);
      }
    }
    const e = errs.splice(0); check(!e.length, `no script errors (${label}): ${e.join(' | ')}`);
    w.close();
  };
  await run(ALL, 'all', 'on');
  for (const mod of Object.keys(probes)) await run(ALL.split(',').filter(f => f !== mod).join(','), mod, 'off');

  // the server: action endpoints of a switched-off module refuse (409, with the reason); the data stays
  await call('PATCH', '/api/settings', {features: ALL.split(',').filter(f => !['pomo', 'habits', 'time'].includes(f)).join(',')});
  let r = await call('POST', '/api/pomo/start', {kind: 'focus', minutes: 25});
  check(r.status === 409 && /focus timer is turned off/.test(r.error), `pomo off: start refused (${r.status} ${r.error})`);
  r = await call('POST', '/api/habits', {name: 'Read'});
  check(r.status === 409 && /Habits are turned off/.test(r.error), `habits off: create refused (${r.status})`);
  r = await call('POST', `/api/habits/${HB}/log`, {});
  check(r.status === 409, `habits off: check-in refused (${r.status})`);
  r = await call('POST', '/api/time/start', {task_id: T});
  check(r.status === 409 && /Time tracking is turned off in your settings/.test(r.error), `time off: timer refused (${r.status} ${r.error})`);
  r = await call('POST', '/api/time/entries', {task_id: T, start: new Date(Date.now() - 36e5).toISOString(), minutes: 10});
  check(r.status === 409, `time off: manual entry refused (${r.status})`);
  const s = await call('GET', '/api/state');
  check(s.habits.some(h => h.id === HB), 'the habits stay');
  await call('PATCH', '/api/settings', {features: ALL});
  r = await call('POST', '/api/pomo/start', {kind: 'focus', minutes: 25});
  check(r.status === 200, `pomo on again: start works (${r.status})`);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
