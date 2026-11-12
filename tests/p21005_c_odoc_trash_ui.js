// 2.1005.0 (#5415, stage 4d of the core's trash, part 1) UI: a quotation draft deleted in the office lies in the office trash
// kalmido-suite: fresh
// with its title and comes back (jsdom, invented data only). The way a person goes, by clicks:
// - the draft's page: More -> Delete, confirm -> the toast "moved to the trash", the draft is gone (404) and not in the list
// - the office trash (Offers, trash button): the draft is listed as a quotation with its title -> Restore -> it opens again
// - back in the list: the row is there again
// - the toast's undo of a second delete brings it back as well (POST .../core/odoc/<id>/restore?undo=1)
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
const TITLE = 'Example Spring Campaign';
const items = d => [...d.querySelectorAll('#pop [role="menuitem"], .menu-list [role="menuitem"]')];
const row = (d, id) => d.querySelector('.ofdrow[data-id="' + id + '"]');
const toastOf = (d, re) => { const t = d.querySelector('#toast'); return t && !t.classList.contains('hidden') && re.test(t.textContent) ? t : null; };

(async () => {
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'comments,collab,office,clients'});
  { const me = (await call('GET', '/api/state')).me; const org = await call('POST', '/api/admin/orgs', {name: 'Example Studio', admin_id: me.id});
    await call('PATCH', '/api/settings', {workspace: `org:${org.id}`}); }
  const q = await call('POST', '/api/office/docs', {project_title: TITLE, items: [{title: 'Concept', qty: 1, rate: 800}]});
  check(q.http === 201 && q.id, 'a quotation draft ' + q.http);

  // ---- delete it on its page
  let w = await boot({hash: 'office/offers/' + q.id}), d = w.document;
  w.confirm = () => true;  // the bridge answers the app's own confirm dialog with yes
  const more = await until(() => d.querySelector('#view [data-ofd="more"]'), {timeout: 30000});
  check(!!more, 'the draft page has its menu');
  more?.click();
  await until(() => items(d).length);
  items(d).find(b => b.textContent.trim() === 'Delete')?.click();
  const toast = await until(() => toastOf(d, /moved to the trash/));
  check(!!toast, 'toast: moved to the trash ' + (toast?.textContent || ''));
  check(await until(async () => (await call('GET', '/api/office/docs/' + q.id)).http === 404), 'the draft is gone for the app (404)');
  await idle(w);
  w.close();

  // ---- the list does not show it; the office trash lists it with its title, Restore brings it back
  w = await boot({hash: 'office/offers'}); d = w.document;
  w.confirm = () => true;
  check(!!await until(() => d.querySelector('[data-ofd="trash"]'), {timeout: 30000}), 'offers: the trash button');
  check(!row(d, q.id), 'the list does not show the draft in the trash');
  d.querySelector('[data-ofd="trash"]').click();
  const li = await until(() => [...d.querySelectorAll('.otblist li')].find(x => x.textContent.includes(TITLE)));
  check(li && li.dataset.core === 'odoc' && /Quotation/.test(li.textContent), 'the office trash lists the draft as a quotation with its title ' + (li?.textContent || '').trim().slice(0, 120));
  li?.querySelector('[data-m="restore"]')?.click();
  check(!!await until(() => toastOf(d, /Restored/)), 'toast: Restored');
  check(!!await until(() => (w.location.hash || '').includes('office/offers/' + q.id), {timeout: 30000}), 'the draft opens after the restore ' + w.location.hash);
  const back = await call('GET', '/api/office/docs/' + q.id);
  check(back.http === 200 && back.project_title === TITLE && (back.items || []).map(x => x.title).join() === 'Concept', 'back with its title and position');

  // ---- back in the list
  w.location.hash = 'office/offers';
  check(!!await until(() => row(d, q.id), {timeout: 30000}), 'the draft is back in the list');
  await idle(w);
  w.close();

  // ---- the toast's undo of a second delete
  w = await boot({hash: 'office/offers/' + q.id}); d = w.document;
  w.confirm = () => true;
  (await until(() => d.querySelector('#view [data-ofd="more"]'), {timeout: 30000}))?.click();
  await until(() => items(d).length);
  items(d).find(b => b.textContent.trim() === 'Delete')?.click();
  const t2 = await until(() => { const t = toastOf(d, /moved to the trash/); return t && t.querySelector('button') ? t : null; });
  check(!!t2, 'second delete: the toast offers Undo');
  await until(async () => (await call('GET', '/api/office/docs/' + q.id)).http === 404);
  t2?.querySelector('button')?.click();
  check(await until(async () => (await call('GET', '/api/office/docs/' + q.id)).http === 200, {timeout: 30000}), 'the toast\'s undo: the draft is readable again');
  await idle(w);
  w.close();

  console.log(`p21005_c_odoc_trash_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
