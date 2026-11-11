// 2.925.0 (#5275) UI test, own container (start.sh): project tags and the labels of an organisation are tags of the core -- the
// kalmido-suite: fresh
// app shows them as before (jsdom).
// - a label put on tasks of two projects: the task row of each project shows the chip #Kunde, the task panel its pill
// - the tag view (#tag/Kunde) lists exactly the tasks with the label, from both projects, a task without it is not there; a
//   task opens from there and back again
// - a project tag of a project shows on its task, the project's settings list it next to the label (marked "Organisation")
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, idle} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {features: 'collab,comments,fields', lang: 'en', tour: 'done'});
  let ORG = (await call('GET', '/api/state')).me.workspaces?.[0]?.id;
  if (!ORG) { const me = (await call('GET', '/api/state')).me; const o = await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id}); ORG = o.id || o.org?.id; }
  check(ORG, 'setup: an organisation');
  const L1 = (await call('POST', '/api/lists', {name: 'Support', kind: 'project', org_id: ORG})).id;
  const L2 = (await call('POST', '/api/lists', {name: 'Sales', kind: 'project', org_id: ORG})).id;
  const lb = await call('POST', '/api/org-labels', {org_id: ORG, name: 'Kunde', color: '#f87171'});
  check(lb.status === 201, 'setup: the label Kunde ' + JSON.stringify(lb).slice(0, 200));
  const t1 = await call('POST', '/api/tasks', {title: 'Drucker klemmt', list_id: L1});
  const t2 = await call('POST', '/api/tasks', {title: 'Angebot Messe', list_id: L2});
  const t3 = await call('POST', '/api/tasks', {title: 'Ohne Etikett', list_id: L1});
  await call('PATCH', `/api/tasks/${t1.id}`, {ltags: ['Kunde', 'Bug']});
  await call('PATCH', `/api/tasks/${t2.id}`, {ltags: ['Kunde']});

  const w = await boot({user: 'alice', hash: 'l/' + L1}), d = w.document;
  await idle(w);
  const routed = async k => { await until(() => w.eval('S.route.key') === k); await idle(w); };
  const row = id => d.querySelector(`#view .trow[data-id="${id}"]`);
  const chips = id => [...(row(id)?.querySelectorAll('.ltag') || [])].map(x => x.textContent.trim());

  // ================= the project: the chips on the task rows
  await until(() => row(t1.id));
  check(chips(t1.id).includes('#Kunde') && chips(t1.id).includes('#Bug'), 'Support: the task row shows the label and the project tag ' + chips(t1.id));
  const kc = [...(row(t1.id)?.querySelectorAll('.ltag') || [])].find(x => x.textContent.trim() === '#Kunde');
  check(kc && /organisation/i.test(kc.getAttribute('title') || ''), 'the label chip says it is the organisation\'s');
  check(chips(t3.id).length === 0, 'the task without tags shows none');
  w.eval(`go('l/${L2}')`); await routed(`l:${L2}`);
  await until(() => row(t2.id));
  check(chips(t2.id).includes('#Kunde'), 'Sales: the same label on its task ' + chips(t2.id));

  // ================= the tag view: exactly the tasks with the label, from both projects
  w.eval(`go('tag/Kunde')`); await routed('tag:Kunde');
  await until(() => row(t1.id) && row(t2.id));
  check(row(t1.id) && /Drucker klemmt/.test(row(t1.id).textContent) && row(t2.id) && /Angebot Messe/.test(row(t2.id).textContent),
    'the tag view lists both tasks with their titles');
  check(!row(t3.id), 'a task without the label is not there');
  // into a task and back
  w.eval(`openDetail(${t2.id})`);
  const pill = await until(() => [...d.querySelectorAll('#detail .tagedit .tagpill.ltag')].find(x => /#Kunde/.test(x.textContent)));
  check(pill, 'the task panel shows the label as a pill');
  w.eval('closeDetail()'); await idle(w);
  check(w.eval('S.route.key') === 'tag:Kunde' && row(t1.id) && row(t2.id), 'back in the tag view, both tasks still there');

  // ================= the project's settings: the project tag and the label apart
  w.eval(`go('l/${L1}')`); await routed(`l:${L1}`);
  w.eval(`listModal(${L1})`);
  const box = await until(() => d.querySelector('#l-ltags .mrow'));
  const txt = box ? d.querySelector('#l-ltags').textContent : '';
  check(/#Bug/.test(txt) && /#Kunde/.test(txt) && /Organisation/.test(txt), 'the settings list the project tag and the label (marked) ' + txt.slice(0, 200));

  console.log(`p2925_c_tags_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
