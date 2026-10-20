// 2.47.3 UI tests, part A (#1360 Office & finance without an organisation), own container (start.sh). jsdom, invented data:
// - a freelancer (no organisation) opens the office: the personal office ("Private"), the switch "small business (section
//   19 UStG)" is saved, the instance admin sees "Move into an organisation"
// - a member of one organisation in the workspace "Private": the empty personal office names the organisation's office with
//   a button; the button switches the workspace and the office follows (the organisation's office), back to "Private" again
// - 2.56.3 (#1842): in the organisation's office a document's client field offers the organisation's clients
// - 2.80.0 (#1842): without clients the field still shows with a hint and "Add client" (creates in the office's
//   organisation, stays on the document); a client created while the document is open shows once it opens again
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});  // no organisation
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,office,clients'});

  // ================= a freelancer: the personal office
  let w = await boot({hash: 'office/settings'}); let d = w.document;
  await until(() => d.querySelector('#os-small'), 60);
  check(/Private/.test(d.querySelector('.office .ofchead')?.textContent || ''), 'freelancer: the office is the personal one: ' + (d.querySelector('.office .ofchead')?.textContent || ''));
  check(/section 19/.test(d.querySelector('#os-small')?.closest('.row')?.textContent || ''), 'freelancer: the switch small business (section 19 UStG)');
  check(!!d.querySelector('[data-ofc="pb-move"]'), 'freelancer: the instance admin may move the office into an organisation');
  check(!d.querySelector('.pbhint'), 'freelancer: no hint without an organisation');
  d.querySelector('#os-small').checked = true;
  d.querySelector('#os-small').dispatchEvent(new w.Event('change', {bubbles: true}));  // 2.113.0 (#2247): the box saves itself
  check(await until(async () => (await call('GET', '/api/office/settings')).settings?.small_business === 1, 40), 'section 19: saved from the settings');
  w.close();

  // ================= a member of one organisation: Private shows the hint, the button switches, the office follows
  const me = (await call('GET', '/api/state')).me;
  const org = await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  check(org.http === 201, 'organisation Alpha');
  const u = await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com', orgs: [org.id]});
  check(u.http === 201 || u.http === 200, 'bob ' + u.http);
  const CB = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,office,clients', workspace: 'private'}, CB);
  w = await boot({user: 'bob', hash: 'office/offers'}); d = w.document;
  await until(() => d.querySelector('.office .pbhint'), 60);
  const hint = d.querySelector('.office .pbhint');
  check(hint && /Alpha/.test(hint.textContent) && !!hint.querySelector('[data-ofc="pb-ws"]'), 'hint: the organisation\'s office with a button: ' + (hint?.textContent || '').slice(0, 160));
  check(!d.querySelector('[data-ofc="pb-move"]'), 'bob (no instance admin) has no move');
  hint.querySelector('[data-ofc="pb-ws"]').click();
  check(await until(() => w.eval('OFC.info && OFC.info.org_id') === org.id, 60), 'the button switches to the organisation\'s office');
  check(w.eval('S.settings.workspace') === 'org:' + org.id && !d.querySelector('.office .pbhint'), 'the workspace follows, no hint there');
  check(await until(async () => (await call('GET', '/api/office/settings', null, CB)).org_id === org.id, 30), 'the workspace is saved (the server opens the organisation\'s office)');
  w.eval("wsSet('private')");
  check(await until(() => w.eval('OFC.info && OFC.info.personal') === 1, 60), 'back in Private: the office follows the switch (the personal office)');
  check(await until(() => d.querySelector('.office .pbhint'), 30), '... with the hint again');
  w.close();

  // ================= 2.80.0 (#1842): no clients yet = the field with a hint and "Add client"; a client created meanwhile
  // shows when the document opens again, without a reload of the app
  await call('PATCH', '/api/settings', {workspace: 'org:' + org.id});
  const edoc = await call('POST', '/api/office/docs', {project_title: 'Leer-Beleg'});
  check(edoc.http === 201, '#1842: a quotation without clients ' + edoc.http);
  w = await boot({hash: `office/offers/${edoc.id}`}); d = w.document;
  const nocl = await until(() => d.querySelector('.fx8a_nocl'), 60);
  check(nocl && /No clients in this area yet/.test(nocl.textContent) && !!nocl.querySelector('[data-ofd="client-new"]') && !d.querySelector('#ofd-client_id'), '#1842: empty client list = hint + "Add client"');
  nocl?.querySelector('[data-ofd="client-new"]').click();
  const nm = await until(() => d.querySelector('#cl-name'), 30);
  check(!!nm, '#1842: "Add client" opens the client dialog');
  if (nm) { nm.value = 'Hafenwerk KG'; d.querySelector('[data-m="save"]').click(); }
  const made = await until(async () => ((await call('GET', '/api/clients')).clients || []).find(c => c.name === 'Hafenwerk KG'), 40);
  check(made && made.org_id === org.id, '#1842: the new client belongs to the office\'s organisation ' + JSON.stringify(made && made.org_id));
  check(await until(() => /#office\/offers\//.test(w.location.hash) && d.querySelector('#ofd-client_id') && [...d.querySelector('#ofd-client_id').options].some(o => o.textContent === 'Hafenwerk KG'), 40),
    '#1842: back on the document, the client field offers the new client at once: ' + w.location.hash);
  const late = await call('POST', '/api/clients', {name: 'Spaet AG', org_id: org.id});
  w.eval(`ofdLoadDoc(${edoc.id}, true)`);
  check(await until(() => [...(d.querySelector('#ofd-client_id')?.options || [])].some(o => o.textContent === 'Spaet AG'), 40), '#1842: a client created elsewhere shows when the document opens again');
  w.close();
  for (const c of [made, late]) if (c?.id) await call('PATCH', `/api/clients/${c.id}`, {archived: true});  // the next block counts the organisation's clients

  // ================= 2.56.3 (#1842): in the organisation's office a document's client field offers the organisation's
  // clients (/api/state names their org_id), never the private ones
  const pcl = await call('POST', '/api/clients', {name: 'Alice privat', org_id: null});
  await call('PATCH', '/api/settings', {workspace: 'org:' + org.id});
  const ocl = await call('POST', '/api/clients', {name: 'Org-Kunde GmbH', org_id: org.id});
  check([pcl.http, ocl.http].every(h => h === 200 || h === 201) && pcl.org_id == null && ocl.org_id === org.id, `a private and an organisation client ${pcl.http} ${ocl.http}`);
  const odoc = await call('POST', '/api/office/docs', {project_title: 'Org-Beleg'});
  check(odoc.http === 201, 'a quotation in the organisation\'s office ' + odoc.http + ' ' + (odoc.error || ''));
  w = await boot({hash: `office/offers/${odoc.id}`}); d = w.document;
  check(await until(() => w.eval(`(S.clients || []).some(c => c.id === ${ocl.id} && c.org_id === ${org.id})`), 60), 'state: the organisation client carries its org_id');
  const sel = await until(() => d.querySelector('#ofd-client_id'), 60);
  const opts = sel ? [...sel.options].map(o => o.textContent) : [];
  check(opts.includes('Org-Kunde GmbH') && !opts.includes('Alice privat'), 'document: the client field offers the organisation\'s client, not the private one: ' + JSON.stringify(opts));
  check(JSON.stringify(w.eval('ofdClientOpts()').map(x => x[1])) === '["Org-Kunde GmbH"]', 'new document dialog: only the organisation\'s client: ' + JSON.stringify(w.eval('ofdClientOpts()')));
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
