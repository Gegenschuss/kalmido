// 2.905.0 (#5414, stage 4c of the core's trash) UI: a service deleted in the office lies in the office trash and comes back
// kalmido-suite: fresh
// (jsdom, invented data only). The way a person goes, by clicks:
// - services tab: open the service, Delete, confirm -> the toast "moved to the trash", the row is gone from the list
// - the office trash (Offers, trash button): the service is listed with its name -> Restore -> the toast "Restored"
// - back on the services tab: the row is there again, its dialog opens with its name
// - the toast's undo of a second delete takes it back as well (POST .../core/<kind>/<id>/restore?undo=1)
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, B, login, until, idle} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const NAME = 'Example Colour Grading';
const row = d => [...d.querySelectorAll('[data-ofc="open"][data-kind="services"]')].find(b => b.textContent.includes(NAME));

(async () => {
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'comments,collab,office,clients'});
  { const me = (await call('GET', '/api/state')).me; const org = await call('POST', '/api/admin/orgs', {name: 'Example Studio', admin_id: me.id});
    await call('PATCH', '/api/settings', {workspace: `org:${org.id}`}); }
  const sv = await call('POST', '/api/office/services', {name_de: NAME, daily_rate: 400});
  check(sv.http === 201 && sv.id, 'a service ' + sv.http);

  const w = await boot({hash: 'office/services'}), d = w.document;
  w.confirm = () => true;  // the bridge answers the app's own confirm dialog with yes
  check(!!await until(() => row(d), {timeout: 30000}), 'services tab: the service is listed');

  // ---- delete it through its dialog
  row(d).click();
  check(!!await until(() => d.querySelector('.ofcdlg [data-m="del"]')), 'the service dialog has Delete');
  d.querySelector('.ofcdlg [data-m="del"]').click();
  const toast = await until(() => { const t = d.querySelector('#toast'); return t && !t.classList.contains('hidden') && /moved to the trash/.test(t.textContent) ? t : null; });
  check(toast && toast.textContent.includes(NAME), 'toast: moved to the trash ' + (toast?.textContent || ''));
  check(!!await until(() => !d.querySelector('.ofcdlg') && !row(d)), 'the row is gone from the list');
  const db = (await call('GET', `/api/office/services/${sv.id}`)).http;
  check(db === 404, 'the service is gone for the app (404) ' + db);

  // ---- the office trash lists it, Restore brings it back
  w.location.hash = 'office/offers';
  check(!!await until(() => d.querySelector('[data-ofd="trash"]'), {timeout: 30000}), 'offers: the trash button');
  d.querySelector('[data-ofd="trash"]').click();
  const li = await until(() => [...d.querySelectorAll('.otblist li')].find(x => x.textContent.includes(NAME)));
  check(li && li.dataset.core === 'omd_services' && /Master data/.test(li.textContent), 'the office trash lists the service (core kind) ' + (li?.textContent || '').trim().slice(0, 120));
  li.querySelector('[data-m="restore"]').click();
  check(!!await until(() => { const t = d.querySelector('#toast'); return t && !t.classList.contains('hidden') && /Restored/.test(t.textContent); }), 'toast: Restored');
  check(!!await until(() => !d.querySelector('.otblist')), 'the trash dialog closes');

  // ---- back on the services tab: the row is there again and opens
  w.location.hash = 'office/services';
  check(!!await until(() => row(d), {timeout: 30000}), 'the service is back in the list');
  row(d).click();
  const nm = await until(() => d.querySelector('.ofcdlg #of-name_de'));
  check(nm && nm.value === NAME, 'its dialog opens with its name ' + nm?.value);
  d.querySelector('.ofcdlg [data-m="close"]').click();
  await until(() => !d.querySelector('.ofcdlg'));

  // ---- the toast's undo of a second delete
  row(d).click();
  await until(() => d.querySelector('.ofcdlg [data-m="del"]'));
  d.querySelector('.ofcdlg [data-m="del"]').click();
  const t2 = await until(() => { const t = d.querySelector('#toast'); return t && !t.classList.contains('hidden') && /moved to the trash/.test(t.textContent) && t.querySelector('button') ? t : null; });
  check(!!t2, 'second delete: the toast offers Undo');
  await until(() => !row(d));
  t2?.querySelector('button')?.click();
  check(!!await until(() => row(d), {timeout: 30000}), 'the toast\'s undo: the service is back in the list');
  check((await call('GET', `/api/office/services/${sv.id}`)).http === 200, 'and readable again');
  await idle(w);
  w.close();

  console.log(`p2905_d_office_trash_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
