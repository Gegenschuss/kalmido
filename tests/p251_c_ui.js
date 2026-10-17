// 2.51.0 UI tests of part C (#1352 pin board, #1353 time proposals, #1355 shoot planning; own container, start.sh). jsdom:
// - the project page marks a notepad an agent wrote ("From <agent>, updated ..."), a person's stays unmarked
// - the calendar shows a draft (tentative event) pale / dashed; its popover says "Draft" and offers Confirm (status
//   confirmed on the server, Undo makes it a draft again) and Discard
// - the review dialog of a time proposal: one row per entry with start / end; a changed start is applied
// - the review dialog of a shoot proposal: day rows with time / place, crew rows below with the warnings
// - the planned-job templates offer "Status on the pin board" and "Check time tracking and propose entries"
// Firefox (real layout, skipped without firefox): 390 px touch - the shoot review stays inside the screen, the fields are
// at least 40 px high
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const firefox = require('./ff')({tag: 'p251_c_ui', check: (c, w) => check(c, w), shots: 'P251C_SHOTS'});
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P251C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK, hd = {}) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {}), ...hd}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const sql = (q, a = []) => JSON.parse(execFileSync('python3', [path.join(__dirname, 'dbx.py'), DATA, q, JSON.stringify(a)]).toString() || '[]');
const pad = n => String(n).padStart(2, '0');
const dstr = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const FEAT = 'cal,collab,comments,time,events,dispo';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ag = await call('POST', '/api/admin/agents', {username: 'claude', display_name: 'Claude', scopes: ['read', 'tasks:write', 'comments', 'pinboard', 'time', 'calendar']});
  sql('UPDATE agents SET org_id=NULL, owner_id=1 WHERE user_id=?', [ag.id]);  // alice's personal agent
  const AGH = {Authorization: 'Bearer ' + ag.token};
  const P = (await call('POST', '/api/lists', {name: 'Film Alpha', kind: 'project'})).id;
  await call('PUT', `/api/lists/${P}/members`, {user_id: ag.id, role: 'edit'});
  await call('PATCH', `/api/lists/${P}`, {time_tracking: true});
  const T = (await call('POST', '/api/tasks', {list_id: P, title: 'Edit the trailer'})).id;
  await call('POST', `/api/lists/${P}/notepads`, {title: 'Contacts', body: 'call the studio'});
  const sp = await call('PUT', `/api/v1/lists/${P}/status-pad`, {body: '## Status\n- **3** done'}, null, AGH);
  check(sp.http === 201 && sp.agent_id === ag.id, 'setup: the agent writes its status block ' + sp.http);
  const pov = {'tasks.pov': JSON.stringify([P])};

  // ================= #1352 the agent's notepad on the project page
  let w = await boot({user: 'alice', hash: 'l/' + P, ls: pov}), d = w.document;
  await until(() => d.querySelectorAll('#view .wgpad').length >= 2);
  const agp = d.querySelector(`#view #pov-np${sp.id}`);
  check(agp && agp.classList.contains('wgpadagt') && /From Claude, updated/.test(agp.querySelector('.wgpadag')?.textContent || ''), '#1352: the agent\'s block is marked ' + (agp?.textContent || '').slice(0, 80));
  const hp = [...d.querySelectorAll('#view .wgpad')].find(x => /Contacts/.test(x.textContent));
  check(hp && !hp.querySelector('.wgpadag'), '#1352: a person\'s notepad stays unmarked');
  w.close();

  // ================= #1355 a draft in the calendar
  const now = new Date(), t1 = dstr(new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1));
  const ev = await call('POST', '/api/events', {title: 'Shoot day draft', start: `${t1}T09:00`, end: `${t1}T17:00`, status: 'tentative'});
  check(ev.http === 201 && ev.status === 'tentative', 'setup: a tentative event ' + ev.http);
  w = await boot({user: 'alice', hash: 'cal', ls: {'tasks.calMode': '"week"'}}); d = w.document;
  w.eval(`S.calSel = '${t1}'; renderView()`);  // 2.56.4 (#1863): tomorrow's week -- on a Saturday tomorrow is the next week (en: Sunday first)
  const chip = await until(() => [...d.querySelectorAll('#view [data-cev]')].find(x => /Shoot day draft/.test(x.textContent)));
  check(chip && chip.classList.contains('evdraft'), '#1355: the draft is shown as a draft (evdraft) ' + chip?.className);
  click(w, chip);
  const pop = await until(() => d.querySelector('#pop .evpop [data-evp="apok"]') && d.querySelector('#pop'));
  check(pop && /Draft/.test(pop.querySelector('.evdraftb')?.textContent || '') && pop.querySelector('[data-evp="del"]'), '#1355: the popover says Draft, Confirm + Discard');
  click(w, pop?.querySelector('[data-evp="apok"]'));
  check(await until(async () => (await call('GET', `/api/events/${ev.id}`)).status === 'confirmed'), '#1355: Confirm -> confirmed on the server');
  await w.eval("histStep('undo')");
  check(await until(async () => (await call('GET', `/api/events/${ev.id}`)).status === 'tentative'), '#1355: Undo -> a draft again');
  w.close();

  // ================= #1353 the review of a time proposal
  const y = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
  const jt = await call('POST', '/api/v1/agent/proposals/time', {summary: 'From your calendar', items: [
    {date: dstr(y), start: '09:00', end: '12:00', task_id: T, note: 'cut'}, {date: dstr(y), start: '13:00', end: '15:00', list_id: P}]}, null, AGH);
  check(jt.http === 201 && jt.kind === 'time', 'setup: a time proposal ' + jt.http + JSON.stringify(jt.error || ''));
  w = await boot({user: 'alice', hash: 'prop/' + jt.id}); d = w.document;
  const md = await until(() => d.querySelector('.ppm .ppi.apri') && d.querySelector('.ppm'));
  const rows = md ? [...md.querySelectorAll('.ppi.apri')] : [];
  check(rows.length === 2 && rows[0].querySelector('[data-f="start"]').value === '09:00' && /Edit the trailer/.test(rows[0].textContent), '#1353: one row per entry with its times');
  if (rows.length) {
    const s = rows[0].querySelector('[data-f="start"]'); s.value = '08:30'; s.dispatchEvent(new w.Event('input', {bubbles: true}));
    const c = rows[1].querySelector('.ppc'); c.checked = false; c.dispatchEvent(new w.Event('change', {bubbles: true}));
    click(w, md.querySelector('[data-pp="apply"]'));
  }
  const ent = await until(() => sql('SELECT start, seconds, note FROM time_entries WHERE user_id=1 ORDER BY id').length && sql('SELECT start, seconds, note FROM time_entries WHERE user_id=1 ORDER BY id'));
  check(ent && ent.length === 1 && ent[0].seconds === 3.5 * 3600 && ent[0].note === 'cut', '#1353: the edited entry applied, the unticked one not ' + JSON.stringify(ent));
  w.close();

  // ================= #1355 the review of a shoot proposal
  const D = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 14);
  const bk = await call('POST', '/api/team/dispo/bookings', {title: 'Other film', start: dstr(D), end: dstr(D), status: 'firm', resources: [{kind: 'user', id: 1}]});
  check(bk.http === 201, 'setup: alice booked elsewhere ' + bk.http);
  const js = await call('POST', '/api/v1/agent/proposals/shoot', {list_id: P, summary: 'Two days', days: [
    {date: dstr(D), start: '08:00', end: '18:00', title: 'Shoot day 1', location: 'Studio'}, {date: dstr(new Date(D.getTime() + 864e5)), title: 'Shoot day 2'}],
    crew: [{kind: 'user', id: 1, day: 0}]}, null, AGH);
  check(js.http === 201 && js.kind === 'shoot', 'setup: a shoot proposal ' + js.http + JSON.stringify(js.error || ''));
  w = await boot({user: 'alice', hash: 'prop/' + js.id}); d = w.document;
  const m2 = await until(() => d.querySelector('.ppm .ppi.apri') && d.querySelector('.ppm'));
  const r2 = m2 ? [...m2.querySelectorAll('.ppi.apri')] : [];
  check(r2.length === 3 && r2[0].querySelector('[data-f="location"]').value === 'Studio' && !r2[1].querySelector('[data-f="start"]'), '#1355: day rows (time / place; all day without time)');
  check(r2[2] && r2[2].classList.contains('sub') && /Already booked: Other film/.test(r2[2].querySelector('.apwarn')?.textContent || ''), '#1355: the crew row with its warning');
  check(/never firm/.test(m2?.querySelector('.shint')?.textContent || ''), '#1355: the hint says: options, never firm');
  w.close();

  // ================= planned-job templates
  w = await boot({user: 'alice', hash: 'home'}); d = w.document;
  await until(() => w.eval('typeof SCHED_TPL') === 'object');
  const ks = w.eval('SCHED_TPL.map(t => t.k).join()');
  check(/pinstatus/.test(ks) && /timeprop/.test(ks) && ks.endsWith('own'), '#1352 #1353: the templates, "Own plan" stays last ' + ks);
  w.close();

  // ================= Firefox: 390 px
  await firefox(async ({cmd, ev: fev, nav, ctx, shot}) => {
    await nav(B + 'static/icon.svg');
    await fev('(() => { localStorage.clear(); return 1; })()');
    check(await fev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + '#prop/' + js.id);
    for (let i = 0; i < 30 && !(await fev('!!document.querySelector(".ppm .ppi.apri")').catch(() => false)); i++) await sleep(300);
    // 2.51.1 (#1355): times use the app's own picker (hidden input + button): measure the visible fields
    const o = await fev(`(() => { const vw = document.documentElement.clientWidth, card = document.querySelector('.ppm .card').getBoundingClientRect();
      const bad = [...document.querySelectorAll('.ppm .ppi *')].filter(e => { const r = e.getBoundingClientRect(); return r.width && r.right > vw + 1; }).map(e => e.tagName + '.' + e.className).slice(0, 5);
      const hs = [...document.querySelectorAll('.ppm .apf input:not([type=hidden]), .ppm .apf .dpbtn')].map(e => e.getBoundingClientRect().height);
      return {vw, right: card.right, bad, minh: Math.min(...hs)}; })()`);
    check(o.right <= o.vw + 1 && !o.bad.length && o.minh >= 40, '390 px: the shoot review inside the screen, fields >= 40 px ' + JSON.stringify(o));
    await shot('p251c-shoot-390.png');
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
