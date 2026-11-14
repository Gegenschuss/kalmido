// 2.1158.0 A UI test (#4566 A): the packing list of a shoot day in the call sheet dialog. Own container (start.sh). Invented names only.
// kalmido-suite: fresh
// - a shoot day with two devices and a contact booked: the call sheet shows the packing list with device name, quantity and
//   category ("0 of 2 packed"), the crew list not mixed with it
// - ticking a line updates the count; "Save" keeps it: opened again (a new page load) the line is still ticked and the other not
// P21158AUI_NOSTART=1 = the server already runs.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21158AUI_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const FEAT = 'collab,comments,contacts,office,clients,workload,dispo';
const dstr = x => `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}`;

// opens the disposition at day D, then the booking sheet of the first booking; -> [window, document, sheet]
async function sheetOf(D) {
  const w = await boot({user: 'alice', hash: 'workload'}), d = w.document;
  (await until(() => d.querySelector('#view .ab2tabs [data-v="dispo"]')))?.click();
  await until(() => d.querySelector('#view [data-act="dp-new"]'));
  w.eval(`DPV.start = '${D}'; dp_reload()`);
  await until(() => d.querySelector('#view .dptable') && w.eval('DPV.data && DPV.data.start') === D);
  (await until(() => d.querySelector('#view .dpbk')))?.click();
  return [w, d, await until(() => d.querySelector('.dpmd'))];
}
async function packOf(D) {
  const [w, d, sh] = await sheetOf(D);  // the booking sheet: its button "Call sheet"
  sh?.querySelector('[data-m="callsheet"]')?.click();
  const md = await until(() => d.querySelector('.modal.csmd .cspacksec') && d.querySelector('.modal.csmd'));
  return [w, d, md];
}
const line = (md, name) => [...(md?.querySelectorAll('.cspack li') || [])].find(li => li.querySelector('.cspn')?.textContent === name);

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ind = await call('PUT', '/api/industry', {industry: 'film'});
  const bk = await call('POST', '/api/books', {name: 'Crew', org_id: null});
  const ct = await call('POST', '/api/contacts', {book_id: bk.id, fn: 'Carla Kamera', phones: [{value: '0170 3333333', type: ['cell']}]});
  const e1 = await call('POST', '/api/office/equipment', {name: 'Kamera Alpha', category: 'Camera body', daily_rate: 120});
  const e2 = await call('POST', '/api/office/equipment', {name: 'Stativ Beta', category: 'Grip', daily_rate: 20});
  const t = new Date(), D = dstr(new Date(t.getFullYear(), t.getMonth(), t.getDate() + 4));
  const b = await call('POST', '/api/team/dispo/bookings', {title: 'Imagefilm Werkstatt', start: D, end: D, status: 'option',
    resources: [{kind: 'contact', id: ct.id}, {kind: 'equipment', id: e1.id}, {kind: 'equipment', id: e2.id}]});
  check(ind.status === 200 && e1.id && e2.id && b.status === 201, 'setup: Film & Video, two devices, a shoot day ' + JSON.stringify(b).slice(0, 160));
  const job = b.bookings?.[0]?.job, org = (await call('GET', `/api/team/dispo?start=${D}&days=1`)).org_id;

  // ================= the packing list in the dialog
  let [w, d, md] = await packOf(D);
  const sec = md?.querySelector('.cspacksec');
  check(sec && /Packing list/.test(sec.querySelector('summary')?.textContent || '') && /0 of 2 packed/.test(sec.querySelector('.cspcount')?.textContent || ''),
    'the section "Packing list" with its count: ' + (sec?.querySelector('summary')?.textContent || '').replace(/\s+/g, ' '));
  const l1 = line(md, 'Kamera Alpha'), l2 = line(md, 'Stativ Beta');
  check(l1 && /1 ×/.test(l1.querySelector('.cspq')?.textContent || '') && /Camera body/.test(l1.textContent) && l2 && /Grip/.test(l2.textContent),
    'each device with quantity and category: ' + [l1, l2].map(x => x?.textContent.replace(/\s+/g, ' ')).join(' | '));
  check(!/Kamera Alpha/.test(md?.querySelector('.cscrew')?.textContent || ''), 'the devices are not in the crew list');
  const cb = l2?.querySelector('input[type="checkbox"]');
  check(cb && !cb.checked && !cb.disabled, 'a line can be ticked');
  cb?.click();
  check(cb?.checked && /1 of 2 packed/.test(md?.querySelector('.cspcount')?.textContent || ''), 'ticked: the count follows');
  md?.querySelector('[data-cs="save"]')?.click();
  const saved = await until(async () => { const j = await call('GET', `/api/team/dispo/callsheet/${job}?org=${org}`); return (j.callsheet?.data?.pack || []).length && j.callsheet; });
  check(saved && JSON.stringify(saved.data.pack) === JSON.stringify([`e:${e2.id}`]), 'saved: the ticked line ' + JSON.stringify(saved?.data || {}).slice(0, 160));
  md?.querySelector('[data-cs="close"]')?.click();
  await until(() => !d.querySelector('.modal.csmd'));
  w.close();

  // ================= opened again: the tick stays
  [w, d, md] = await packOf(D);
  check(line(md, 'Stativ Beta')?.querySelector('input')?.checked === true && line(md, 'Kamera Alpha')?.querySelector('input')?.checked === false
    && /1 of 2 packed/.test(md?.querySelector('.cspcount')?.textContent || ''), 'opened again: the stand is ticked, the camera not');
  w.close();

  console.log(`p21158_a_packliste_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
