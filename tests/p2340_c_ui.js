// 2.34.0 UI tests (agent C), own container (start.sh). jsdom:
// #272 planned agent jobs: the agent card has "Plans"; the dialog lists my plans (empty hint); "New plan" with the
//      templates (Weekly project status fills title, text with read_project_status, Monday 09:00 and the agent's list);
//      saved -> the row shows the rhythm, the list and the next run; pause (switch) / Run now / Edit / Delete; the form
//      checks title, text and weekdays; German: rhythm and the next run in the German formats; an admin sees bob's plan
//      marked "by Bob"
// Firefox 390 touch: the dialog with a plan and the form fit the phone (nothing sticks out, tap targets >= 44 px), screenshots.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2340_c_ui', check, shots: 'P2340C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el, o = {}) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const FEAT = 'cal,comments,collab,agents';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const bob = await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  const AG = ag.id;
  const L = (await call('POST', '/api/lists', {name: 'Software'})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: AG, role: 'edit'});
  await call('PUT', `/api/lists/${L}/members`, {user_id: bob.id, role: 'edit'});
  await call('PATCH', `/api/lists/${L}`, {agent_members: true});
  const md = d => d.querySelector('.modal.schedmd');
  const rows = d => [...d.querySelectorAll('.schedmd .schedrow')];

  // ================= the dialog
  let w = await boot({user: 'alice', hash: 'agents'}), d = w.document;
  await until(() => d.querySelector(`[data-act="sched-open"][data-aid="${AG}"]`));
  const pb = d.querySelector(`[data-act="sched-open"][data-aid="${AG}"]`);
  check(pb && /Plans/.test(pb.textContent), '#272: the agent card has "Plans"');
  click(w, pb); await until(() => md(d));
  check(md(d) && /Planned jobs: Claude/.test(md(d).textContent) && /No plans yet/.test(md(d).textContent), '#272: the dialog opens, no plans yet');
  click(w, md(d).querySelector('[data-sm="new"]')); await until(() => d.getElementById('sc-title'));
  const tpls = [...md(d).querySelectorAll('[data-tpl]')].map(x => x.textContent);
  check(['Morning briefing', 'Weekly project status', 'Follow up on stale tasks', 'Check time tracking', 'Own plan'].every(t => tpls.includes(t)), '#272: the templates ' + tpls.join(', '));
  // the form checks its fields
  click(w, md(d).querySelector('[data-sf="save"]')); await sleep(100);
  check(!d.getElementById('sc-err').hidden && /title/.test(d.getElementById('sc-err').textContent), '#272: a title is needed');
  click(w, md(d).querySelector('[data-tpl="status"]')); await sleep(50);
  check(d.getElementById('sc-title').value === 'Weekly project status' && /read_project_status/.test(d.getElementById('sc-prompt').value)
    && d.getElementById('sc-freq').value === 'weekly' && d.querySelector('[data-wd="1"]').checked && !d.querySelector('[data-wd="2"]').checked
    && d.getElementById('sc-time').value === '09:00' && d.getElementById('sc-list').value === String(L), '#272: the template fills the form (Monday 09:00, the list)');
  check(!d.getElementById('sc-wd').hidden && d.getElementById('sc-dom').hidden, '#272: weekly shows the weekdays, not the day of the month');
  d.getElementById('sc-freq').value = 'monthly'; d.getElementById('sc-freq').dispatchEvent(new w.Event('change', {bubbles: true}));
  check(d.getElementById('sc-wd').hidden && !d.getElementById('sc-dom').hidden, '#272: monthly shows the day of the month');
  d.getElementById('sc-freq').value = 'weekly'; d.getElementById('sc-freq').dispatchEvent(new w.Event('change', {bubbles: true}));
  d.querySelector('[data-wd="1"]').checked = false;
  click(w, md(d).querySelector('[data-sf="save"]')); await sleep(100);
  check(/weekday/.test(d.getElementById('sc-err').textContent), '#272: weekly needs a weekday');
  d.querySelector('[data-wd="1"]').checked = true; d.querySelector('[data-wd="3"]').checked = true;
  click(w, md(d).querySelector('[data-sf="save"]'));
  await until(() => rows(d).length === 1);
  let row = rows(d)[0];
  check(row && /Weekly project status/.test(row.textContent) && /Every week on Mon, Wed, \S/.test(row.textContent) && /Software/.test(row.textContent) && /next: /.test(row.textContent),
    '#272: saved, the row shows rhythm, list and next run: ' + row?.textContent.replace(/\s+/g, ' '));
  const P = (await call('GET', `/api/agents/${AG}/schedules`)).data[0];
  check(P && P.days.join() === '1,3' && P.list_id === L && P.tz, '#272: stored with days, list and the browser time zone ' + JSON.stringify(P).slice(0, 200));
  // pause and on again
  const sw = row.querySelector('[data-sm="toggle"]'); sw.checked = false; sw.dispatchEvent(new w.Event('change', {bubbles: true}));
  await until(() => rows(d)[0]?.classList.contains('off'));
  check(rows(d)[0].classList.contains('off') && /paused/.test(rows(d)[0].textContent) && rows(d)[0].querySelector('[data-sm="run"]').disabled, '#272: paused (switch), Run now off');
  const sw2 = rows(d)[0].querySelector('[data-sm="toggle"]'); sw2.checked = true; sw2.dispatchEvent(new w.Event('change', {bubbles: true}));
  await until(() => !rows(d)[0]?.classList.contains('off'));
  click(w, rows(d)[0].querySelector('[data-sm="run"]'));
  await until(() => /run by hand/.test(rows(d)[0]?.textContent || ''));
  check(/last: run by hand/.test(rows(d)[0].textContent), '#272: Run now -> "last: run by hand"');
  // edit
  click(w, rows(d)[0].querySelector('[data-sm="edit"]')); await until(() => d.getElementById('sc-title'));
  check(d.getElementById('sc-title').value === 'Weekly project status' && !md(d).querySelector('[data-tpl]') && d.querySelector('[data-wd="3"]').checked, '#272: edit keeps the values, no templates');
  d.getElementById('sc-time').value = '07:45';
  click(w, md(d).querySelector('[data-sf="save"]'));
  await until(() => rows(d).length === 1 && /7:45|07:45/.test(rows(d)[0].textContent));
  check(/7:45|07:45/.test(rows(d)[0].textContent), '#272: the new time shows');
  w.close();

  // ================= German + a plan of bob (the admin sees it as his)
  const CB = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, CB);
  await call('POST', `/api/agents/${AG}/schedules`, {title: 'Bobs Plan', prompt: 'Do it', freq: 'monthly', days: [15], time: '18:00', tz: 'Europe/Berlin'}, CB);
  await call('PATCH', '/api/settings', {lang: 'de'});
  w = await boot({user: 'alice', hash: 'agents'}); d = w.document;
  await until(() => d.querySelector(`[data-act="sched-open"][data-aid="${AG}"]`));
  click(w, d.querySelector(`[data-act="sched-open"][data-aid="${AG}"]`)); await until(() => rows(d).length === 2);
  const t = rows(d).map(x => x.textContent.replace(/\s+/g, ' '));
  check(/Jede Woche am Mo, Mi, 07:45/.test(t[0]) && /nächste: /.test(t[0]), '#272: German rhythm + next run: ' + t[0]);
  check(/Jeden Monat am Tag 15, 18:00/.test(t[1]) && /von Bob/.test(t[1]), '#272: bob\'s plan for the admin, "von Bob": ' + t[1]);
  check(!/[A-Z][a-z]{2} \d{1,2}, \d{4}/.test(t.join(' ')), '#272: no English date in German');
  // delete (asks first)
  click(w, rows(d)[1].querySelector('[data-sm="del"]')); await until(() => d.querySelector('.cdlg [data-cd="yes"]'));
  click(w, d.querySelector('.cdlg [data-cd="yes"]'));
  await until(() => rows(d).length === 1);
  check(rows(d).length === 1 && (await call('GET', `/api/agents/${AG}/schedules`, null, CB)).data.length === 0, '#272: the admin deleted bob\'s plan');
  await call('PATCH', '/api/settings', {lang: 'en'});
  w.close();

  // ================= Firefox: the phone (390, touch)
  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1, .agview')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '390';
    check(await ffLogin(o) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + '#agents'); await ready(ev);
    await ev(`(() => { document.querySelector('[data-act="sched-open"]').click(); return 1; })()`); await sleep(900);
    const g = await ev(`(() => { const c = document.querySelector('.schedmd .card'); if (!c) return null; const r = c.getBoundingClientRect();
      const bs = [...document.querySelectorAll('.schedmd .schedb .btn, .schedmd .schedon')].map(b => b.getBoundingClientRect()).map(x => Math.min(x.width, x.height));
      return {left: r.left, right: r.right, min: Math.min(...bs), n: bs.length, wide: document.documentElement.scrollWidth <= 390}; })()`);
    check(g && g.left >= 0 && g.right <= 390 && g.wide, `${tag}: #272 the dialog fits the phone ` + JSON.stringify(g));
    check(g && g.n >= 4 && g.min >= 44, `${tag}: #272 tap targets of a plan >= 44 px ` + JSON.stringify(g));
    await shot('p2340c-390-plans.png');
    await ev(`(() => { document.querySelector('.schedmd [data-sm="new"]').click(); return 1; })()`); await sleep(500);
    await ev(`(() => { document.querySelector('.schedmd [data-tpl="brief"]').click(); return 1; })()`); await sleep(300);
    const f = await ev(`(() => { const c = document.querySelector('.schedmd .card').getBoundingClientRect(); const ch = [...document.querySelectorAll('.schedmd .schedtpl .chip')].map(b => b.getBoundingClientRect().height);
      return {right: c.right, chip: Math.min(...ch), wide: document.documentElement.scrollWidth <= 390, title: document.getElementById('sc-title').value}; })()`);
    check(f && f.right <= 390 && f.wide && f.chip >= 44 && f.title === 'Morning briefing', `${tag}: #272 the form with the templates fits, chips >= 44 px ` + JSON.stringify(f));
    await shot('p2340c-390-plan-form.png');
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
