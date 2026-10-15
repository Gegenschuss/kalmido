// 2.47.0 UI tests, part A (#1648 fill instead of skip, #1649 masters Freelancer-Rollen / Drehpersonal), own container
// (start.sh). jsdom, invented data only:
// - the services tab shows the sections "Freelancer roles" (with the purchase price for the admin) and "Crew" below the services
// - the service dialog has the choice "Freelancer role", the unit "Percent" and the kind "Shoot"
// - the import preview (state set directly): areas roles / crew, an existing service with empty fields = "Fill empty
//   fields" with the list of fields, a full one says "Nothing to fill"; the choice switches to skip; the button counts
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
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
  const ro = await call('POST', '/api/office/roles', {name_de: 'Cutter', cost_day: 500});
  check(ro.http === 201, 'role ' + ro.http);
  check((await call('POST', '/api/office/crew', {name_de: 'Beleuchter', name_en: 'Gaffer', rate_day: 350, intext: 'extern'})).http === 201, 'crew');
  check((await call('POST', '/api/office/services', {name_de: 'Kamera', daily_rate: 650, role_id: ro.id})).http === 201, 'service');

  // ================= the services tab: the two masters below the services
  let w = await boot({hash: 'office/services'}); let d = w.document;
  await until(() => d.querySelectorAll('.office .srhead').length === 2 && d.querySelector('[data-ofc="open"][data-kind="crew"]'), 60);
  const heads = [...d.querySelectorAll('.office .srhead')].map(h => h.textContent);
  check(heads.length === 2 && /Freelancer roles/.test(heads[0]) && /Crew/.test(heads[1]), 'services tab: sections Freelancer roles and Crew ' + JSON.stringify(heads));
  const role = d.querySelector('[data-ofc="open"][data-kind="roles"]');
  check(role && /Cutter/.test(role.textContent) && /Purchase/.test(role.textContent) && /500/.test(role.textContent), 'roles: the admin sees the purchase price: ' + (role?.textContent || ''));
  check(/Gaffer/.test(d.querySelector('[data-ofc="open"][data-kind="crew"]')?.textContent || ''), 'crew: the row with its English name');
  check(!!d.querySelector('.srhead [data-ofc="new"][data-kind="roles"]') && !!d.querySelector('.srhead [data-ofc="new"][data-kind="crew"]'), 'the admin can add roles / crew');
  d.querySelector('[data-ofc="open"][data-kind="services"]').click();
  await until(() => d.querySelector('.ofcdlg #of-role_id'), 30);
  const sel = d.querySelector('.ofcdlg #of-role_id');
  check(sel && sel.value === String(ro.id) && /Cutter/.test(sel.selectedOptions[0]?.textContent || ''), 'service dialog: the freelancer role is chosen');
  check(!!d.querySelector('.ofcdlg #of-unit option[value="percent"]') && !!d.querySelector('.ofcdlg #of-intext option[value="shooting"]'), 'service dialog: unit percent, kind shoot');
  check(!d.querySelector('.ofcdlg #of-role:not([type="hidden"])'), 'service dialog: the old text role stays hidden while it is empty');
  d.querySelector('.ofcdlg [data-m="close"]').click();
  d.querySelector('[data-ofc="open"][data-kind="roles"]').click();
  await until(() => d.querySelector('.ofcdlg #of-cost_day'), 30);
  check(/^500([.,]0+)?$/.test(d.querySelector('.ofcdlg #of-cost_day')?.value || ''), 'role dialog: the purchase per day for the admin: ' + d.querySelector('.ofcdlg #of-cost_day')?.value);
  w.close();

  // ================= the import preview: roles / crew areas, fill
  w = await boot({hash: 'office/import'}); d = w.document;
  await until(() => d.querySelector('.oim'), 60);
  w.eval(`OIM.pv = {clients: [], roles: [{row: 2, name_de: 'Motion Designer', cost_day: 600, cost_hour: 75, action: 'new', dup: false, fill: {}}],
    crew: [{row: 2, name_de: 'Beleuchter', name_en: 'Gaffer', rate_day: 350, intext: 'extern', action: 'skip', dup: true, fill: {}}],
    services: [{row: 3, name_de: 'Kamera', name_en: 'Camera', category: 'Video', daily_rate: 650, unit: 'day', action: 'fill', dup: true, fill: {name_en: 'Camera', raw_fee: 1}},
      {row: 4, name_de: 'Künstlersozialkasse', unit: 'percent', daily_rate: 5, action: 'new', dup: false, fill: {}}], equipment: []}; ofcDraw();`);
  await until(() => d.querySelectorAll('.oimpv .oimcard').length === 4, 30);
  const txt = d.querySelector('.oimpv')?.textContent || '';
  check(/Freelancer roles/.test(txt) && /Crew/.test(txt) && /Motion Designer/.test(txt), 'preview: the areas Freelancer roles and Crew');
  const cards = [...d.querySelectorAll('.oimpv .oimcard')];
  const kam = cards.find(c => /Kamera/.test(c.textContent)), bel = cards.find(c => /Beleuchter/.test(c.textContent));
  const fs = kam?.querySelector('select[data-oim-sact="services"]');
  check(fs && fs.value === 'fill' && /Fills: Name \(English\): Camera · raw data/.test(kam.textContent), 'preview: fill with the list of fields: ' + (kam?.textContent || '').slice(0, 160));
  check(bel && /Nothing to fill/.test(bel.textContent) && bel.classList.contains('off'), 'preview: a full entry says nothing to fill');
  check(/(^|[^0-9])5([.,]00)? %/.test(cards.find(c => /Künstlersozialkasse/.test(c.textContent))?.textContent || ''), 'preview: the Künstlersozialkasse as percent');
  check(/Import 3 entries/.test(d.querySelector('[data-oim="import"]')?.textContent || ''), 'import button: new + fill rows: ' + (d.querySelector('[data-oim="import"]')?.textContent || ''));
  fs.value = 'skip'; fs.dispatchEvent(new w.Event('change', {bubbles: true}));
  await sleep(100);
  check(w.eval('OIM.pv.services[0].action') === 'skip' && /Import 2 entries/.test(d.querySelector('[data-oim="import"]')?.textContent || ''), 'the choice skips the row');
  const cb = [...d.querySelectorAll('.oimpv .oimcard')].find(c => /Kamera/.test(c.textContent))?.querySelector('input[type="checkbox"]');
  cb.checked = true; cb.dispatchEvent(new w.Event('change', {bubbles: true}));
  await sleep(100);
  check(w.eval('OIM.pv.services[0].action') === 'fill', 'ticking an existing entry again = fill, not a second entry');
  w.close();

  console.log(`p2470_a_roles_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
