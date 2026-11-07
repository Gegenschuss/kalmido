// 2.623.0 part D UI test (#4765), own container (start.sh): the approval (video sign-offs) belongs to the agency and has a
// kalmido-suite: fresh
// module switch of its own.
// - the task panel, the project overview (vdr_projHtml) and the client card (vdr_clientHtml) offer "Add video link" in an
//   agency project and a project without a type, not in a software or a private project; the section is called "Approval"
// - an existing review in a software project still shows (read, open), without "Add"
// - Settings > Modules has the switch "Approval" (group Projects and team); off: no "Add" at the task, the project, the
//   client, the project's properties do not offer it, the setting "Videos" is gone; the existing reviews still show
// P2623D_NOSTART=1 = the server already runs.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2623D_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const URL1 = 'https://vimeo.com/123456789';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  const FEAT = 'collab,comments,clients,videos';
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const P = {};
  for (const [k, b] of [['ag', {ptype: 'agency'}], ['nt', {kind: 'project'}], ['sw', {ptype: 'software'}], ['pr', {ptype: 'private'}]]) {
    const l = await call('POST', '/api/lists', {name: 'Projekt ' + k, ...b});
    const t = await call('POST', '/api/tasks', {title: 'Aufgabe ' + k, list_id: l.id});
    P[k] = {l: l.id, t: t.id};
  }
  check(Object.values(P).every(x => x.l && x.t), 'four projects with a task ' + JSON.stringify(P));
  // existing reviews in the software project (the API takes them; the screen only shows them)
  const SW2 = await call('POST', '/api/tasks', {title: 'Alter Schnitt', list_id: P.sw.l});
  const R1 = await call('POST', '/api/videos', {task_id: SW2.id, url: URL1, title: 'Alt Aufgabe'});
  const R2 = await call('POST', '/api/videos', {list_id: P.sw.l, url: URL1, title: 'Alt Projekt'});
  check(R1.id && R2.id, 'existing reviews in the software project');
  const CL = await call('POST', '/api/clients', {name: 'Kunde Zwei GmbH'});
  check(CL.id, 'a client');
  // after the module goes off: one review each at the agency task / project / client already exists
  const AG2 = await call('POST', '/api/tasks', {title: 'Agentur alt', list_id: P.ag.l});
  const R3 = await call('POST', '/api/videos', {task_id: AG2.id, url: URL1, title: 'Agentur Aufgabe alt'});
  check(R3.id, 'an existing review at an agency task');

  let w = await boot({user: 'alice', hash: 't/' + P.ag.t}), d = w.document;
  const loaded = (k, id) => w.eval(`!!VDR.by && Array.isArray(VDR.by[${JSON.stringify(k + ':' + id)}])`);
  // a task's panel: the section answers once its reviews are loaded (a real state, no fixed wait)
  const taskSec = async tid => {
    if (w.location.hash !== '#t/' + tid) w.location.hash = 't/' + tid;
    await until(() => w.eval('S.sel') === tid && d.querySelector('#detail') && w.eval("typeof VDR === 'object'") && loaded('task_id', tid));
    w.eval('renderDetail()');
    return {sec: d.querySelector('#detail #d-vdr'), add: d.querySelector('#detail [data-vdr="new"]'), rows: d.querySelectorAll('#detail #d-vdr [data-vdr="open"]').length};
  };
  let s = await taskSec(P.ag.t);
  check(s.add && /Approval/.test(s.sec?.querySelector('h5')?.textContent || ''), 'agency task: the section "Approval" with "Add video link"');
  s = await taskSec(P.nt.t);
  check(s.add, 'task of a project without a type: "Add video link"');
  s = await taskSec(P.sw.t);
  check(!s.sec && !s.add, 'software task: no approval');
  s = await taskSec(P.pr.t);
  check(!s.sec && !s.add, 'private task: no approval');
  s = await taskSec(SW2.id);
  check(s.sec && s.rows === 1 && !s.add, 'software task with an existing review: it shows, without "Add"');

  // the project overview and the client card (their section functions, rows loaded first)
  const projAdd = async k => {
    w.eval(`vdr_projHtml(listById(${P[k].l}))`);
    await until(() => loaded('list_id', P[k].l));
    return w.eval(`vdr_projHtml(listById(${P[k].l}))`);
  };
  const clientHtml = async () => { w.eval(`vdr_clientHtml({id: ${CL.id}})`); await until(() => loaded('client_id', CL.id)); return w.eval(`vdr_clientHtml({id: ${CL.id}})`); };
  check(/data-vdr="new"/.test(await projAdd('ag')) && /Approvals/.test(await projAdd('ag')), 'agency project overview: "Approvals" with "Add"');
  check(/data-vdr="new"/.test(await projAdd('nt')), 'overview of a project without a type: "Add"');
  const swp = await projAdd('sw');
  check(!/data-vdr="new"/.test(swp) && /Alt Projekt/.test(swp), 'software project overview: the existing review, no "Add" ' + swp.slice(0, 200));
  check(await projAdd('pr') === '', 'private project overview: nothing');
  check(/data-vdr="new"/.test(await clientHtml()), 'client card: "Add" with the module on');
  // Settings > Modules: the switch, in Projects and team; the project's properties offer it; Settings > Data has "Videos"
  w.eval(`settingsModal('data')`);
  check(await until(() => d.querySelector('#s-exp-h') && d.querySelector('#s-vext')), 'module on: the setting "Videos" (load without asking)');
  check(w.eval("MOD_GROUPS.some(([, ks]) => ks.includes('videos'))") && /Approval/.test(w.eval("modRowHtml('videos')")) && /data-feat="videos" checked/.test(w.eval("modRowHtml('videos')")),
    'Settings > Modules: the switch "Approval" (on)');
  check(/data-pz="video"/.test(w.eval(`pz_boxHtml(listById(${P.ag.l}))`)), 'the project properties offer "Approval" with the module on');
  w.close();

  // ================= module off
  await call('PATCH', '/api/settings', {features: 'collab,comments,clients'});
  w = await boot({user: 'alice', hash: 't/' + P.ag.t}); d = w.document;
  check(!w.eval("feat('videos')"), 'the module is off');
  s = await taskSec(P.ag.t);
  check(!s.sec && !s.add, 'module off: agency task without reviews shows nothing');
  s = await taskSec(AG2.id);
  check(s.sec && s.rows === 1 && !s.add, 'module off: the existing review at the agency task shows, without "Add"');
  await until(() => w.eval("typeof vdr_projHtml === 'function'"));
  const agp = await projAdd('ag');
  check(!/data-vdr="new"/.test(agp), 'module off: agency project overview without "Add"');
  const swp2 = await projAdd('sw');
  check(/Alt Projekt/.test(swp2) && !/data-vdr="new"/.test(swp2), 'module off: the existing project review still shows');
  check(await clientHtml() === '', 'module off: client card without reviews shows nothing');
  check(!/data-pz="video"/.test(w.eval(`pz_boxHtml(listById(${P.ag.l}))`)), 'module off: the project properties do not offer it');
  w.eval(`settingsModal('data')`);
  check(await until(() => d.querySelector('#s-exp-h')) && !d.querySelector('#s-vext'), 'module off: no setting "Videos"');
  check(!/data-feat="videos" checked/.test(w.eval("modRowHtml('videos')")) && /data-feat="videos"/.test(w.eval("modRowHtml('videos')")), 'module off: the switch is there and shows off');
  const er = await call('POST', '/api/videos', {task_id: P.ag.t, url: URL1, title: 'Neu'});
  check(er.status === 409, 'module off: the server refuses a new review ' + er.status);
  w.close();

  check(errs.length === 0, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
