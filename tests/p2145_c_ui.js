// 2.145.0 UI tests (part C, #2432), own container (start.sh). jsdom + Firefox (screenshot):
//   "Print" on a project starts with a head: the description (Markdown rendered), the status with its note and who set it,
//   the period of the tasks + progress, the members with their role, the milestones with date and state; empty parts are left
//   out (a project without status / milestones); a list without kind prints like a project (2.352.0); a person without an organisation
//   (freelancer-matrix: lists) gets the head of the own project. Screenshot: p2145-c-print.png (P2145C_SHOTS).
// P2145C_NOSTART=1 = the server already runs.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2145_c_ui', check, shots: 'P2145C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const FEAT = 'collab,progress,comments,fields,time,kanban,timeline';
if (!process.env.P2145C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  const bob = (await call('POST', '/api/users', {orgs: [ORG], username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'})).id;
  const fri = (await call('POST', '/api/users', {orgs: [], username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com'})).id;
  check(bob && fri, 'people created');

  const P = (await call('POST', '/api/lists', {name: 'Shop fit', kind: 'project', org_id: ORG})).id;
  await call('PUT', `/api/lists/${P}/members`, {user_id: bob, role: 'edit'});
  await call('PATCH', `/api/lists/${P}/overview`, {description: 'Goal: **new shop** by summer\n\n- walls\n- floor'});
  await call('POST', `/api/lists/${P}/status`, {status: 'at_risk', note: 'Tiles arrive late'});
  await call('POST', '/api/tasks', {title: 'Opening', list_id: P, ms: 1, due: '2031-06-30'});
  const T1 = (await call('POST', '/api/tasks', {title: 'Paint walls', list_id: P, due: '2031-05-10'})).id;
  await call('PATCH', `/api/tasks/${T1}`, {start: '2031-05-01'});
  const T2 = (await call('POST', '/api/tasks', {title: 'Order lamps', list_id: P, due: '2031-05-20'})).id;
  await call('POST', `/api/tasks/${T2}/complete`, {});
  const Q = (await call('POST', '/api/lists', {name: 'Bare project', kind: 'project', org_id: ORG})).id;
  await call('POST', '/api/tasks', {title: 'Loose task', list_id: Q});
  const N = (await call('POST', '/api/lists', {name: 'Groceries', org_id: ORG})).id;
  await call('POST', '/api/tasks', {title: 'Milk', list_id: N});

  // ================= a project with everything
  let w = await boot({user: 'alice', hash: 'l/' + P}), d = w.document;
  await until(() => w.eval(`!!taskById(${T1})`));
  w.eval(`lexPrint(${P})`);
  const hd = await until(() => d.querySelector('.tsheet .lexpage .lxhead .lxfacts'));
  check(hd, 'the project head shows');
  const head = () => d.querySelector('.lexpage .lxhead')?.textContent || '';
  check(d.querySelector('.lexpage .lxhead .lxdesc b')?.textContent === 'new shop' && d.querySelectorAll('.lexpage .lxdesc li').length === 2, 'the description is rendered Markdown');
  check(/At risk/i.test(head()) && /Tiles arrive late/.test(head()) && /Alice/.test(head()), 'status, its note and who set it ' + head());
  check(/2031/.test(head()) && /1 of 3 done|1 of 2 done/.test(head()), 'the period of the tasks and the progress ' + head());
  check(/Alice \(Owner\)/.test(head()) && /Bob \(/.test(head()), 'members with their role');
  check(/Opening/.test(head()) && d.querySelectorAll('.lexpage .lxms li').length === 1 && /Open/.test(d.querySelector('.lexpage .lxms li').textContent), 'the milestone with date and state');
  check(d.querySelector('.lexpage h1') && d.querySelector('.lexpage h1').compareDocumentPosition(d.querySelector('.lexpage .lxhead')) & 4
    && d.querySelector('.lexpage .lxhead').compareDocumentPosition(d.querySelector('.lexpage .lxl')) & 4, 'name, then the head, then the tasks');
  d.querySelector('.tsheet [data-ts="close"]').click();

  // ================= a project without status / milestones: those parts are left out
  w.eval(`lexPrint(${Q})`);
  await until(() => d.querySelector('.tsheet .lexpage .lxr'));
  await sleep(600);
  const qh = d.querySelector('.lexpage .lxhead')?.textContent || '';
  check(!/Status/.test(qh) && !d.querySelector('.lexpage .lxms') && !d.querySelector('.lexpage .lxdesc'), 'empty parts are left out ' + qh);
  check(/Alice \(Owner\)/.test(qh), 'the members still show');
  d.querySelector('.tsheet [data-ts="close"]').click();

  // ================= a list without kind (2.352.0, #2752: every list but the inbox is a project): its name, a head only with
  // what it has (no status, no milestones, no description)
  w.eval(`lexPrint(${N})`);
  await until(() => d.querySelector('.tsheet .lexpage .lxr'));
  await sleep(600);
  const nh = d.querySelector('.lexpage .lxhead')?.textContent || '';
  check(/Groceries/.test(d.querySelector('.lexpage h1')?.textContent || '') && !/Status/.test(nh) && !d.querySelector('.lexpage .lxms') && !d.querySelector('.lexpage .lxdesc'),
    'a list without kind: name, the head without empty parts ' + nh);
  d.querySelector('.tsheet [data-ts="close"]').click();
  w.close();

  // ================= a person without an organisation (freelancer-matrix: lists)
  const FK = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, FK);
  const FP = (await call('POST', '/api/lists', {name: 'Own project', kind: 'project', org_id: null}, FK)).id;
  await call('PATCH', `/api/lists/${FP}/overview`, {description: 'My own *goal*'}, FK);
  await call('POST', '/api/tasks', {title: 'Own task', list_id: FP, ms: 1, due: '2031-07-01'}, FK);
  w = await boot({user: 'frida', hash: 'l/' + FP}); d = w.document;
  await until(() => w.eval(`!!listById(${FP})`));
  w.eval(`lexPrint(${FP})`);
  await until(() => d.querySelector('.tsheet .lexpage .lxhead .lxdesc'));
  check(d.querySelector('.lexpage .lxdesc i')?.textContent === 'goal' && d.querySelectorAll('.lexpage .lxms li').length === 1, 'freelancer: description and milestone in the head');
  w.close();

  // ================= screenshot of the printed page (light)
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1100, height: 1000}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    await nav(B + '#l/' + P);
    for (let i = 0; i < 40 && !(await ev(`typeof listById === 'function' && !!listById(${P})`).catch(() => false)); i++) await sleep(250);
    await ev(`(() => { lexPrint(${P}); return 1; })()`);
    for (let i = 0; i < 40 && !(await ev(`!!document.querySelector('.lexpage .lxhead .lxfacts')`).catch(() => false)); i++) await sleep(250);
    check(await ev(`getComputedStyle(document.querySelector('.lexpage .lxhead')).breakInside === 'avoid'`), 'Firefox: no page break inside the head');
    await shot('p2145-c-print.png');
  });

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
