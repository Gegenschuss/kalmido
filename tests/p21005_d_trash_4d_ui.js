// 2.1005.0 (#5415, stage 4d of the core's trash) UI: a trip deleted in the travel expenses lies in the office trash and
// kalmido-suite: fresh
// comes back (jsdom, invented data only). The way a person goes, by clicks:
// - travel tab: the trip's row menu, Delete, confirm -> the toast "Moved to the trash", the row is gone from the list
// - the office trash (Offers, trash button): the trip is listed as "Trip" with its destination -> Restore -> "Restored"
// - back on the travel tab: the row is there again, it opens with its receipt
// - the toast's undo of a second delete takes it back as well (POST /api/office/trips/<id>/restore)
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, B, login, until: until0, idle} = require('./boot');
const TC = require('./testclock');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = (fn, o) => until0(fn, {timeout: 30000, ...(o || {})});
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const DEST = 'Example Harbour Town';
const DAY = TC.today();

(async () => {
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'comments,collab,office,clients'});
  { const me = (await call('GET', '/api/state')).me; const org = await call('POST', '/api/admin/orgs', {name: 'Example Studio', admin_id: me.id});
    await call('PATCH', '/api/settings', {workspace: `org:${org.id}`}); }
  const tp = await call('POST', '/api/office/trips', {date_from: DAY, date_to: DAY, dest: DEST, items: [{date: DAY, category: 'train', amount: '42.00', currency: 'EUR'}]});
  check(tp.http === 201 && tp.id && tp.items?.length === 1, 'a trip with a receipt ' + tp.http);

  const w = await boot({hash: 'office/travel'}), d = w.document;
  const row = () => [...d.querySelectorAll('.rklist [data-rk="open"]')].find(b => b.textContent.includes(DEST));
  const toastHas = re => { const t = d.querySelector('#toast'); return t && !t.classList.contains('hidden') && re.test(t.textContent) ? t : null; };
  const del = async () => {
    click(w, row().closest('li').querySelector('[data-rk="rowmore"]'));
    const b = await until(() => [...d.querySelectorAll('#pop .menu-list button')].find(x => x.textContent.trim() === 'Delete'));
    click(w, b);
    await until(() => d.querySelector('[data-cd="yes"]')); click(w, d.querySelector('[data-cd="yes"]'));
  };
  check(!!await until(() => row()), 'travel tab: the trip is listed');

  // ---- delete it from the row menu
  await del();
  const t1 = await until(() => toastHas(/Moved to the trash/));
  check(!!t1, 'toast: moved to the trash ' + (d.querySelector('#toast')?.textContent || ''));
  check(!!await until(() => !row()), 'the row is gone from the list');
  const gone = await call('GET', `/api/office/trips?year=${DAY.slice(0, 4)}`);
  check(!(gone.trips || []).some(t => t.id === tp.id), 'the server lists it no more');

  // ---- the office trash lists it with its destination, Restore brings it back
  w.location.hash = 'office/offers';
  check(!!await until(() => d.querySelector('[data-ofd="trash"]')), 'offers: the trash button');
  click(w, d.querySelector('[data-ofd="trash"]'));
  const li = await until(() => [...d.querySelectorAll('.otblist li')].find(x => x.textContent.includes(DEST)));
  check(li && li.dataset.core === 'otrip' && /Trip/.test(li.textContent), 'the office trash lists the trip with its destination ' + (li?.textContent || '').trim().slice(0, 120));
  click(w, li?.querySelector('[data-m="restore"]'));
  check(!!await until(() => toastHas(/Restored/)), 'toast: Restored');
  check(!!await until(() => !d.querySelector('.otblist')), 'the trash dialog closes');

  // ---- back on the travel tab: the row is there again and opens with its receipt
  w.location.hash = 'office/travel';
  check(!!await until(() => row()), 'the trip is back in the list');
  click(w, row());
  const head = await until(() => d.querySelector('.rkhead h3'));
  check(head && head.textContent.includes(DEST), 'it opens: ' + (head?.textContent || ''));
  check(!!await until(() => [...d.querySelectorAll('.rkit')].length === 1), 'with its receipt');
  click(w, d.querySelector('[data-rk="back"]'));
  check(!!await until(() => row()), 'back to the list');

  // ---- the toast's undo of a second delete
  await del();
  const t2 = await until(() => { const t = toastHas(/Moved to the trash/); return t && t.querySelector('button') ? t : null; });
  check(!!t2, 'second delete: the toast offers Undo');
  check(!!await until(() => !row()), 'the row is gone again');
  click(w, t2?.querySelector('button'));
  check(!!await until(() => row()), 'the toast\'s undo: the trip is back in the list');
  const back = await call('GET', `/api/office/trips?year=${DAY.slice(0, 4)}`);
  const t = (back.trips || []).find(x => x.id === tp.id);
  check(t && t.items.length === 1 && t.items[0].id === tp.items[0].id, 'the server has it again with its receipt (same ids)');
  await idle(w);
  w.close();

  console.log(`p21005_d_trash_4d_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
