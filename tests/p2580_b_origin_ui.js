// kalmido-suite: fresh
// 2.580.0 B (#4821): under "All workspaces" a task row of a mixed view (Today, Next 7 days) names where the task comes from:
// the workspace's dot + "Workspace · Project" (workspace.js ws_originHtml), a text for screen readers, no house mark in the
// row; inside an open project and with only one workspace shown it stays the plain project name as before.
// Phones (<= 480 px, Firefox): only the dot + the workspace's short letters, the full origin in the title.
// freelancer-matrix: lists - frida has no organisation (one workspace: no origin); with her own organisation (Private + her
// studio) her rows carry the origin too.
// Own container (start.sh), jsdom + Firefox. Invented names only.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login, until: waitFor} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2580B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const firefox = require('./ff')({tag: 'p2580_b_origin_ui', check, shots: 'P2580B_SHOTS'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const until = fn => waitFor(fn, {timeout: 15000, step: 150});
const day = n => { const d = new Date(); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
const FEAT = 'cal,comments,collab,kanban,timeline';
const row = (d, id) => d.querySelector(`#view .trow[data-id="${id}"]`);
const org = (d, id) => row(d, id)?.querySelector('.wso');

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  const me = (await call(CA, 'GET', '/api/state')).me;
  const A = (await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha Studio', admin_id: me.id})).id;
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'all'});
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const OL = (await call(CA, 'POST', '/api/lists', {name: 'Shoot', org_id: A})).id;
  const PL = (await call(CA, 'POST', '/api/lists', {name: 'Move house', org_id: null})).id;
  const OT = (await call(CA, 'POST', '/api/tasks', {list_id: OL, title: 'Book the camera', due: day(0)})).id;
  const PT = (await call(CA, 'POST', '/api/tasks', {list_id: PL, title: 'Pack the books', due: day(0)})).id;
  const OW = (await call(CA, 'POST', '/api/tasks', {list_id: OL, title: 'Edit the trailer', due: day(3)})).id;
  check(OT && PT && OW, 'setup: two projects in two workspaces with tasks');

  // (1) alice under "All workspaces", Today: each row names workspace and project
  let w = await boot({user: 'alice', hash: 'today'}), d = w.document;
  check(w.eval('wsCur()') === 'all' && w.eval('wsOn()'), 'alice shows all workspaces');
  const o = await until(() => org(d, OT));
  check(o && o.title === 'Alpha Studio · Shoot', 'Today: the organisation task names "Workspace · Project" ' + (o && o.title));
  check(o && /Alpha Studio/.test(o.querySelector('.wsows')?.textContent || '') && o.querySelector('.wsol')?.textContent === 'Shoot' && o.querySelector('.wsosep'), 'Today: workspace, separator and project are drawn');
  check(o && o.querySelector('.wsp-dot[data-wsc]'), 'Today: the dot in the organisation\'s colour');
  check(o && o.querySelector('.wsoab')?.textContent === 'AS', 'Today: the short letters for phones ' + (o && o.querySelector('.wsoab')?.textContent));
  check(o && o.querySelector('.sr')?.textContent === 'Workspace: Alpha Studio, Project: Shoot' && o.querySelector('.wsov')?.getAttribute('aria-hidden') === 'true', 'Today: one text for screen readers, the drawn part hidden from them');
  const p = org(d, PT);
  check(p && p.title === 'Private · Move house' && p.querySelector('.wsp-dot'), 'Today: the private task names Private ' + (p && p.title));
  check(!row(d, PT)?.querySelector('.wsprv') && !row(d, OT)?.querySelector('.wsprv'), 'Today: no house mark in a row (the origin replaces it)');
  check(row(d, PT)?.querySelectorAll('.wso').length >= 1 && row(d, PT).querySelectorAll('.lst').length === 1, 'Today: one project chip per row, no second one');  // 2.750.0 (#4502): in the meta line or the column "Project"
  // Next 7 days
  w.location.hash = 'week';
  check(await until(() => org(d, OW)?.title === 'Alpha Studio · Shoot'), 'Next 7 days: the origin too');
  // inside the open project: the project name stays as it was (no chip)
  w.location.hash = 'l/' + OL;
  check(await until(() => row(d, OW) && !d.querySelector('#view .wso')), 'open project: no origin');
  // only one workspace shown: as before
  await call(CA, 'PATCH', '/api/settings', {workspace: 'org:' + A});
  w.close();
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  check(await until(() => row(d, OT)) && w.eval('wsCur()') === 'org:' + A && !d.querySelector('#view .wso'), 'one workspace shown: no origin');
  check(/Shoot/.test(row(d, OT)?.querySelector('.meta .lst')?.textContent || '') || !row(d, OT)?.querySelector('.meta .lst'), 'one workspace shown: the plain project name as before');
  await call(CA, 'PATCH', '/api/settings', {workspace: 'all'});
  w.close();

  // (2) frida without an organisation: one workspace, no origin
  const FL = (await call(CF, 'POST', '/api/lists', {name: 'Taxes'})).id;
  const FT = (await call(CF, 'POST', '/api/tasks', {list_id: FL, title: 'File the receipts', due: day(0)})).id;
  w = await boot({user: 'frida', hash: 'today'}); d = w.document;
  check(await until(() => row(d, FT)) && !w.eval('wsOn()') && !d.querySelector('#view .wso'), 'frida alone: no origin');
  w.close();
  // her own organisation (Private + her studio): the origin is there
  const FS = (await call(CA, 'POST', '/api/admin/orgs', {name: 'Frida Films', admin_id: fu.id})).id;
  const FSL = (await call(CF, 'POST', '/api/lists', {name: 'Clients', org_id: FS})).id;
  const FST = (await call(CF, 'POST', '/api/tasks', {list_id: FSL, title: 'Send the offer', due: day(0)})).id;
  await call(CF, 'PATCH', '/api/settings', {workspace: 'all'});
  w = await boot({user: 'frida', hash: 'today'}); d = w.document;
  check(await until(() => org(d, FST)?.title === 'Frida Films · Clients'), 'frida with her studio: the studio task names it ' + org(d, FST)?.title);
  check(org(d, FT)?.title === 'Private · Taxes', 'frida with her studio: her private task names Private ' + org(d, FT)?.title);
  w.close();

  // (3) the real layout: desktop shows names, a phone (390 px) only the dot + the short letters
  await firefox(async ({ev, nav, cmd, ctx, shot}) => {
    const fu2 = ms => waitFor(() => ev(ms).catch(() => null), {timeout: 15000, step: 150});
    await nav(B + 'static/icon.svg');
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    // a part is seen when one of the row's copies (the meta line on a phone, the column on a computer) shows it
    const vis = sel => `[...document.querySelectorAll('#view .trow[data-id="${OT}"] ${sel}')].some(e => getComputedStyle(e).display !== 'none' && e.getBoundingClientRect().width > 0)`;
    for (const [wd, ht, tag] of [[1280, 900, 'desktop'], [390, 760, 'phone']]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: wd, height: ht}});
      await nav(B + '#today');
      check(await fu2(`!!document.querySelector('#view .trow[data-id="${OT}"] .wso')`), tag + ': the origin is there');
      if (tag === 'desktop') check(await ev(vis('.wso .wsows')) && await ev(vis('.wso .wsol')) && !(await ev(vis('.wso .wsoab'))), 'desktop: workspace and project shown, no short letters');
      else check(!(await ev(vis('.wso .wsows'))) && !(await ev(vis('.wso .wsol'))) && await ev(vis('.wso .wsoab')) && await ev(vis('.wso .wsp-dot')), 'phone: only the dot and the short letters');
      await shot(`p2580b-origin-${tag}.png`);
    }
  });

  console.log(`p2580_b_origin_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
