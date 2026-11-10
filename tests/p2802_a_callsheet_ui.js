// 2.855.0 A UI test (#1956): the call sheet of a shoot day in the app. Own container (start.sh). Invented names only.
// kalmido-suite: fresh
// - with Film & Video the booking sheet of the disposition has the button "Call sheet"; it loads callsheet.js on demand
//   (lazyload.js) and opens the dialog of that shoot day: the crew of the booking is listed with the contact's phone
// - the day details typed in (location, a call time, important, a cast line) are saved, the dialog opened again shows them
//   (the content, not only the fields); "PDF" is there; the address gets the link "Open in maps"
// - without Film & Video the booking sheet has no "Call sheet" button
// P2802AUI_NOSTART=1 = the server already runs.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2802AUI_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
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

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ind = await call('PUT', '/api/industry', {industry: 'film'});
  const bk = await call('POST', '/api/books', {name: 'Crew', org_id: null});
  const ct = await call('POST', '/api/contacts', {book_id: bk.id, fn: 'Carla Kamera', phones: [{value: '0170 3333333', type: ['cell']}]});
  const t = new Date(), D = dstr(new Date(t.getFullYear(), t.getMonth(), t.getDate() + 3));
  const b = await call('POST', '/api/team/dispo/bookings', {title: 'Imagefilm Kueche', start: D + 'T07:00', end: D + 'T19:00', status: 'firm', resources: [{kind: 'contact', id: ct.id}]});
  check(ind.status === 200 && ct.id && b.status === 201, 'setup: Film & Video, a contact, a shoot day ' + JSON.stringify(b).slice(0, 160));
  const job = b.bookings?.[0]?.job, org = (await call('GET', `/api/team/dispo?start=${D}&days=1`)).org_id;

  // ================= the button, the dialog, what comes from the app
  let [w, d, sh] = await sheetOf(D);
  const btn = sh?.querySelector('[data-m="callsheet"]');
  check(btn && /Call sheet/.test(btn.textContent), 'the booking sheet has the button "Call sheet"');
  btn?.click();
  let md = await until(() => d.querySelector('.modal.csmd #cs-loc_name') && d.querySelector('.modal.csmd'));
  check(md && /Call sheet: Imagefilm Kueche/.test(md.querySelector('h3')?.textContent || '') && !d.querySelector('.dpmd'), 'the dialog of the shoot day, the booking sheet closed');
  check(w.eval("typeof cs_formHtml === 'function'"), 'callsheet.js was loaded on demand');
  const crew = md?.querySelector('.cscrew')?.textContent || '';
  check(/Carla Kamera/.test(crew) && /0170 3333333/.test(crew), 'the crew of the booking with the contact\'s mobile number: ' + crew.replace(/\s+/g, ' '));
  check(md?.querySelector('[data-cs="pdf"]') && md?.querySelector('[data-cs="save"]'), 'the buttons PDF and Save');
  // ================= type in, save
  md.querySelector('#cs-loc_name').value = 'Studio Nord';
  const addr = md.querySelector('#cs-loc_address');
  addr.value = 'Musterweg 7, 12345 Musterstadt'; addr.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(/Open in maps/.test(md.querySelector('.csmap')?.textContent || '') && /Musterweg%207/.test(md.querySelector('.csmap a')?.getAttribute('href') || ''),
    'the address gets the link "Open in maps"');
  const call0 = md.querySelector('.csrow[data-k="calls"] input[data-c="time"]');
  if (call0) call0.value = '06:30';
  md.querySelector('#cs-important').value = 'Bitte leise am Set';
  md.querySelector('[data-cs="rowadd"][data-k="cast"]')?.click();
  const castIn = await until(() => md.querySelector('.csrow[data-k="cast"] input[data-c="name"]'));
  if (castIn) castIn.value = 'Max Beispiel';
  md.querySelector('[data-cs="save"]')?.click();
  const saved = await until(async () => { const j = await call('GET', `/api/team/dispo/callsheet/${job}?org=${org}`); return j.callsheet?.data?.loc_name === 'Studio Nord' && j.callsheet; });
  check(saved && saved.data.important === 'Bitte leise am Set' && saved.data.calls?.[0]?.time === '06:30' && saved.data.cast?.[0]?.name === 'Max Beispiel',
    'saved: location, the first call time, important, the cast line ' + JSON.stringify(saved?.data || {}).slice(0, 200));
  md.querySelector('[data-cs="close"]')?.click();
  await until(() => !d.querySelector('.modal.csmd'));
  w.close();

  // ================= opened again: the content is there
  [w, d, sh] = await sheetOf(D);
  sh?.querySelector('[data-m="callsheet"]')?.click();
  md = await until(() => d.querySelector('.modal.csmd #cs-loc_name') && d.querySelector('.modal.csmd'));
  check(md?.querySelector('#cs-loc_name')?.value === 'Studio Nord' && md?.querySelector('#cs-important')?.value === 'Bitte leise am Set', 'opened again: location and important are shown');
  check(md?.querySelector('.csrow[data-k="cast"] input[data-c="name"]')?.value === 'Max Beispiel', 'opened again: the cast line');
  check(md?.querySelector('.csrow[data-k="calls"] input[data-c="time"]')?.value === '06:30', 'opened again: the call time');
  w.close();

  // ================= without Film & Video: no button
  await call('PUT', '/api/industry', {industry: ''});
  [w, d, sh] = await sheetOf(D);
  check(sh && !sh.querySelector('[data-m="callsheet"]'), 'without Film & Video: no "Call sheet" in the booking sheet');
  w.close();

  console.log(`p2802_a_callsheet_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
