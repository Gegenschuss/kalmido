// 2.46.1 UI tests (part C, #1557), own container (start.sh, mode workspaces). jsdom, invented data only:
// - #1557 legacy import: every area of the preview has a switch "Take over" and "Skip all"; an area switched off folds away,
//   the import button counts only the areas switched on and the import sends only them; the import runs show
//   "Only undo the equipment" per area and an undone area as a tag
// - 2.80.0 (#1836): a client created while the app is open shows in the import's client choice on the next visit of the page
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});  // KMT_NOSTART=1: a running app
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,office,clients'});
  const me = (await call('GET', '/api/state')).me.id;
  const ORG = (await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me})).id;
  let w, d;
  // ================= #1557: the legacy import, a switch per area
  await call('PATCH', '/api/settings', {workspace: `org:${ORG}`});
  const imp = await call('POST', '/api/office/legacy/import', {services: [{name_de: 'Kamera', daily_rate: 500, action: 'new'}], equipment: [{name: 'Stativ', action: 'new'}, {name: 'Licht', action: 'new'}]});
  check(imp.http === 201 && imp.counts.services === 1 && imp.counts.equipment === 2, '#1557: a data run with services + equipment ' + imp.http);
  w = await boot({hash: 'office/import'}); d = w.document;
  await until(() => d.querySelector('.oim .oimrun'), 60);
  const run = d.querySelector('.oim .oimrun');
  check(!!run.querySelector('[data-oim="undo"]:not([data-kind])') && !!run.querySelector('[data-oim="undo"][data-kind="equipment"]') && !!run.querySelector('[data-oim="undo"][data-kind="services"]'),
    '#1557: the run has Undo and one button per area');
  check(/Only undo the equipment/.test(run.querySelector('[data-kind="equipment"]').textContent), '#1557: "Only undo the equipment"');
  w.confirm = () => true;
  run.querySelector('[data-oim="undo"][data-kind="equipment"]').click();
  await until(() => /Equipment undone/.test(d.querySelector('.oim .oimrun')?.textContent || ''), 40);
  const run2 = d.querySelector('.oim .oimrun');
  check(/Equipment undone/.test(run2.textContent) && !run2.querySelector('[data-kind="equipment"]') && !!run2.querySelector('[data-oim="undo"]:not([data-kind])'), '#1557: the undone area shows as a tag, the run can still be undone');
  const eq = await call('GET', '/api/office/equipment'), sv = await call('GET', '/api/office/services');
  check((eq.items || []).length === 0 && (sv.items || []).length === 1, '#1557: only the equipment went');
  // the preview: switches per area
  w.eval(`OIM.pv = {clients: [{row: 2, name: 'Bergtal Studios', contact: '', street: 'Hauptweg 9', zip: '12345', city: 'Musterstadt', country: 'DE', address: 'x', flags: [], reasons: [], dup: null, action: 'new'}],
    services: [{row: 2, name_de: 'Schnitt', category: '', daily_rate: 400, action: 'new', dup: false}],
    equipment: [{row: 2, name: 'Kran', name_en: '', category: '', daily_rate: 100, action: 'new', dup: false}, {row: 3, name: 'Dolly', name_en: '', category: '', daily_rate: 50, action: 'new', dup: false}], other: {}}; ofcDraw();`);
  await until(() => d.querySelectorAll('.oimpv .oimarea').length === 3, 30);
  const btn = () => d.querySelector('[data-oim="import"]')?.textContent || '';
  check(d.querySelectorAll('.oimpv .oimarea input[data-oim-area]').length === 3 && /Import 4 entries/.test(btn()), '#1557: three areas with a switch, 4 entries: ' + btn());
  const sw = k => d.querySelector(`.oimpv input[data-oim-area="${k}"]`);
  sw('clients').checked = false; sw('clients').dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(50);
  check(/Import 3 entries/.test(btn()) && !d.querySelector('.oimpv [data-oim-c]') && /not taken over/.test(d.querySelector('.oimpv .oimarea.off')?.textContent || ''), '#1557: the clients switched off fold away: ' + btn());
  d.querySelector('.oimpv [data-oim="area-skip"][data-area="equipment"]').click(); await sleep(50);
  check(/Import 1 entry/.test(btn()) && w.eval(`OIM.pv.equipment.every(x => x.action === 'skip')`), '#1557: Skip all of the equipment: ' + btn());
  check(/Take over all/.test(d.querySelector('.oimpv [data-oim="area-skip"][data-area="equipment"]')?.textContent || ''), '#1557: Skip all turns into Take over all');
  d.querySelector('.oimpv [data-oim="area-skip"][data-area="equipment"]').click(); await sleep(50);
  check(/Import 3 entries/.test(btn()), '#1557: Take over all brings them back: ' + btn());
  d.querySelector('[data-oim="import"]').click();
  await until(async () => ((await call('GET', '/api/office/equipment')).items || []).length === 2, 40);
  const cl = await call('GET', '/api/clients');
  check(((await call('GET', '/api/office/equipment')).items || []).length === 2 && !(cl.clients || []).some(c => c.name === 'Bergtal Studios'), '#1557: the import wrote services + equipment, no client');
  const runs = (await call('GET', '/api/office/legacy/runs')).runs || [];
  check(runs[0] && Object.keys(runs[0].areas || {}).sort().join(',') === 'equipment,services', '#1557: the new run has the two areas: ' + JSON.stringify(runs[0]?.areas));
  // 2.80.0 (#1836): a client created meanwhile is in the client choice after leaving and opening the import page again
  const ncl = await call('POST', '/api/clients', {name: 'Nordlicht Medien', org_id: ORG});
  check(ncl.http === 201 || !!ncl.id, '#1836: client created ' + ncl.http);
  w.location.hash = '#office/settings'; await sleep(200);
  w.location.hash = '#office/import';
  const seen = await until(() => w.eval(`(OIM.clients || []).some(c => c.name === 'Nordlicht Medien')`), 40);
  check(seen && /Nordlicht Medien/.test(w.eval(`oimClientOpts('')`)), '#1836: the new client is in the import client choice without a reload');
  w.close();

  console.log(`p2461_c_import_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
