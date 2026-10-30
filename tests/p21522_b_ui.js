// 2.152.2 part B UI tests (#2624): every list is called a project; the old type "Simple list | Project" is the switch
// "Progress and status" in the project dialog. Own container (start.sh), jsdom, a person WITHOUT an organisation
// (as tests/freelancer_fixture.py; freelancer-matrix: tasks).
// - the dialog of a new project: title "New project", the switch #l-kindp "Progress and status", off; no type segment
// - switching it on sets kind project (the Start from cards show), off again kind list
// - an existing kind=project project shows the switch on; switching it off saves kind list (autosave), on again project
// - "New project" in the command palette, the second entry with the switch on
// - the German dialog says "Fortschritt und Status" and "Neues Projekt"
// 2.352.0 C (#2751 / #2752): the switch is gone (status instead); the checks of the switch now check that it is gone
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21522B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const lastModal = d => [...d.querySelectorAll('.modal')].pop();
// 2.396.0 (#3385): the switch is the choice List | Project (radios): "off" picks List
const flip = (w, el, on) => { const t = el.type === 'radio' && !on ? el.closest('.lkseg').querySelector('#l-kindl') : el; t.checked = el.type === 'radio' ? true : on; t.dispatchEvent(new w.Event('change', {bubbles: true})); };
const kindOf = async id => ((await call('GET', '/api/state')).lists || []).find(l => l.id === id)?.kind || 'list';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const AK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']}, AK);
  await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: (await call('GET', '/api/state', null, AK)).me.id}, AK);  // a server with organisations
  // the person without an organisation (as tests/freelancer_fixture.py)
  const fu = await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []}, AK);
  check(fu.http < 300, 'a person without an organisation ' + fu.http);
  CK = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  check(((await call('GET', '/api/state')).me.workspaces || []).length === 0, 'frida is in no organisation');
  const P = (await call('POST', '/api/lists', {name: 'Launch', kind: 'project'})).id;
  const L = (await call('POST', '/api/lists', {name: 'Errands'})).id;
  check(P && L && await kindOf(P) === 'project', 'a project with kind project and a plain one');

  let w = await boot({user: 'frida', hash: 'today'}); let d = w.document;
  // ================= the dialog of a new project
  w.eval('listModal()'); await sleep(250);
  let md = lastModal(d);
  check(/^New project$/.test(md.querySelector('h3')?.textContent.trim() || ''), 'new: the title says New project ' + md.querySelector('h3')?.textContent);
  // 2.352.0 C (#2751 / #2752): the switch "Progress and status" is gone; the Start from cards sit in the folding part
  // "Project features" (closed for a plain new project, open for "New project with progress and status…")
  check(!md.querySelector('#l-kindp') && !md.querySelector('.lkrow'), 'new: no switch Progress and status (2.352.0)');
  check(!md.querySelector('#l-kindl') && !md.querySelector('.lkseg') && !/Simple list/.test(md.textContent), 'the type segment Simple list | Project is gone');
  check(md.querySelector('#l-kind').value === 'list' && md.querySelector('#lm-sec-proj:not([open]) .lptype'), 'plain new project: the Start from cards folded');
  check(!/Used for/.test(md.textContent) && !md.querySelector('#l-fam'), 'no "Used for" any more (2.396.0, #3385)');
  md.remove();
  w.eval(`listModal(null, '', {kind: 'project'})`); await sleep(250);
  md = lastModal(d);
  check(md.querySelector('#l-kind').value === 'project' && md.querySelector('#lm-sec-proj[open] .lptype'), 'with progress and status: kind project, the Start from cards open');
  md.remove();

  // ================= an existing project: no switch, the status instead (kind stays as stored)
  await until(() => w.eval(`!!listById(${P}) && !!listById(${L})`), 60);
  w.eval(`listModal(${P})`); await sleep(250);
  md = lastModal(d);
  check(/Edit project/.test(md.querySelector('h3')?.textContent || ''), 'existing: the title says Edit project');
  check(!md.querySelector('#l-kindp') && !md.querySelector('#l-kind'), 'existing: no switch any more (2.352.0)');
  md.remove();
  check(await kindOf(P) === 'project', 'opening the dialog leaves kind as it was');

  // ================= New project in the command palette
  const pal = w.eval('palAll()').filter(x => x.kind === 'action').map(x => x.label);
  // 2.352.0 B (#2752): no switch any more, so only "New project"
  check(pal.includes('New project') && !pal.includes('New project with progress and status…') && !pal.includes('New list'), 'palette: only New project ' + pal.filter(x => /project|list/i.test(x)).join(' | '));
  w.close();

  // ================= German
  await call('PATCH', '/api/settings', {lang: 'de'});
  w = await boot({user: 'frida', hash: 'today'}); d = w.document;
  await until(() => w.eval('typeof tr') === 'function' && w.eval("tr('New project')") === 'Neues Projekt', 40);
  w.eval('listModal()'); await sleep(250);
  md = lastModal(d);
  check(/Neues Projekt/.test(md.querySelector('h3')?.textContent || '') && /Projekt-Funktionen/.test(md.querySelector('#lm-sec-proj summary')?.textContent || ''), 'de: Neues Projekt, Projekt-Funktionen (2.352.0)');
  check(!/Einfache Liste|Neue Liste/.test(md.textContent), 'de: no Einfache Liste / Neue Liste left in the dialog');
  w.close();

  console.log(`\n${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
