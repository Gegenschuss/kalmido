// 2.147.2 UI tests (part A, #2500), own container (start.sh). A member with the organisation role read-only:
//   jsdom: an organisation-wide list offers no "Join" (joining would bring no writing), a member still gets it; in that list
//   there is no + button (noFab) and a typed task says "you can only read" instead of silently doing nothing (no task made).
//   Firefox at phone size (412 x 783, touch): the office opens for read-only like for its admin (direct start #office and
//   #office/offers, the settings module not loaded) -- no page left on "Loading…".
// P21472A_NOSTART=1 = the server already runs.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
// lazy: the app loads its modules itself (the settings module that held the role words is not there on a direct start)
const firefox = require('./ff')({tag: 'p21472_a_ui', check, shots: 'P21472A_SHOTS', lazy: true});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21472A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const FEAT = 'comments,collab,office,clients';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'org:' + ORG});
  await call('PUT', '/api/office/settings', {company: {name: 'Studio Alpha'}, lang: 'en'});
  const uid = {};
  for (const [u, role] of [['bob', 'member'], ['rita', 'readonly']]) uid[u] = (await call('POST', '/api/users', {username: u, display_name: u[0].toUpperCase() + u.slice(1), password: 'password123', email: `${u}@example.com`, orgs: [{id: ORG, role}]})).id;
  for (const u of ['bob', 'rita']) await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'org:' + ORG}, await login(u));
  const L1 = (await call('POST', '/api/lists', {name: 'Team board', org_id: ORG})).id;
  await call('PATCH', `/api/lists/${L1}`, {org_visibility: 'org', org_edit: 1});
  const L2 = (await call('POST', '/api/lists', {name: 'Handbook', org_id: ORG})).id;
  await call('PATCH', `/api/lists/${L2}`, {org_visibility: 'org'});
  await call('POST', '/api/tasks', {list_id: L1, title: 'Plan the spring'});

  // ================= jsdom: read-only on a phone
  let w = await boot({user: 'rita', mobile: true, hash: 'l/' + L1}), d = w.document;
  await until(() => w.eval(`!!listById(${L1}) && S.route.key === 'l:${L1}'`));
  for (const L of [L1, L2]) {
    w.eval(`go('l/${L}')`); await sleep(300);
    const bar = d.querySelector('#view .ovbar');
    check(bar && !bar.querySelector('[data-ovjoin]'), `#2500: read-only: no Join in list ${L} (${bar?.textContent || 'no bar'})`);
    check(bar && /read-only/.test(bar.textContent), '#2500: read-only: the bar says why');
  }
  w.eval(`go('l/${L1}')`); await sleep(300);
  check(w.eval('noFab()') === true && w.eval('fabOff()') === true, '#2500: read-only: no + button in the organisation list');
  check(w.eval(`$('#fab').classList.contains('gone')`), '#2500: the + button is hidden');
  check(!d.querySelector('#view .qdock'), 'no add bar either (as before)');
  const n0 = (await call('GET', '/api/state', null, await login('alice'))).tasks.filter(t => t.list_id === L1).length;
  w.eval(`submitQuick({id: 'qinput', value: 'Sneaky task'}, {list_id: ${L1}})`);
  check(await until(() => /only read/.test(d.querySelector('#toast')?.textContent || d.body.textContent)), '#2500: a typed task says "only read"');
  await sleep(500);
  check((await call('GET', '/api/state', null, await login('alice'))).tasks.filter(t => t.list_id === L1).length === n0, '#2500: no task made');
  w.eval(`go('inbox')`); await sleep(300);
  check(w.eval('noFab()') === false, '#2500: the own basket keeps its + button');
  w.close();
  // ================= a member still gets Join
  w = await boot({user: 'bob', mobile: true, hash: 'l/' + L2}); d = w.document;
  await until(() => w.eval(`!!listById(${L2})`));
  w.eval(`go('l/${L2}')`); await sleep(300);
  check(d.querySelector('#view .ovbar [data-ovjoin]'), '#2500: a member is offered Join');
  w.close();

  // ================= Firefox, phone: the office for read-only like for the admin
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 412, height: 783}});
    const loaded = `(() => { const o = document.querySelector('#view .dash.office'); return !!o && !!o.querySelector('.ofcbody') && ![...o.querySelectorAll('p.lempty')].some(p => /Loading/.test(p.textContent)); })()`;
    for (const u of ['rita', 'alice']) {
      for (const h of ['#office', '#office/offers']) {
        await nav(B + 'static/icon.svg');
        await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
        await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
        await nav(B + h);
        let done = false;
        for (let i = 0; i < 32 && !done; i++) { done = await ev(loaded).catch(() => false); if (!done) await sleep(250); }
        if (!done) { console.log(`${u} ${h}:`, await ev(`(document.querySelector('#view')?.innerText || '').slice(0, 300)`).catch(e => e.message)); await shot(`office-${u}-${h.replace(/\W/g, '')}.png`); }
        check(done, `#2500: ${u} ${h}: the office is drawn within 8 s (no "Loading…")`);
        if (u === 'rita') check(await ev(`document.querySelector('#view .dash.office')?.dataset.ofcro === '1'`), `#2500: rita ${h}: read-only office (no create buttons)`);
      }
    }
  }, true);

  check(!errs.length, 'no script errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
