// 2.855.0 A UI test (#1956): the call sheet of a shoot day in the app. Own container (start.sh). Invented names only.
// kalmido-suite: fresh
// - with Film & Video the booking sheet of the disposition has the button "Call sheet"; it loads callsheet.js on demand
//   (lazyload.js) and opens the dialog of that shoot day: the crew of the booking is listed with the contact's phone
// - the day details typed in (location, a call time, important, a cast line) are saved, the dialog opened again shows them
//   (the content, not only the fields); "PDF" is there; the address gets the link "Open in maps"
// - 2.986.0 (#5649): an old free-text agency stays shown; the agency chosen from the contacts shows company, person, phone and
//   e-mail, is saved, and a new call sheet of the same project starts with it
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

  // ================= 2.986.0 (#5649): client and agency from the contacts
  // an older call sheet with the agency as free text keeps it (the select stays on "Free text", the text is shown)
  const cur = (await call('GET', `/api/team/dispo/callsheet/${job}?org=${org}`)).callsheet;
  const old = await call('PUT', `/api/team/dispo/callsheet/${job}?org=${org}`, {data: {...cur.data, agency: 'Agentur Freitext Alt'}, expect_updated_at: cur.updated_at});
  check(old.callsheet?.data?.agency === 'Agentur Freitext Alt', 'setup: an agency as free text');
  [w, d, sh] = await sheetOf(D);
  sh?.querySelector('[data-m="callsheet"]')?.click();
  md = await until(() => d.querySelector('.modal.csmd #cs-agency_contact') && d.querySelector('.modal.csmd'));
  check(md?.querySelector('#cs-agency_contact')?.value === '' && md?.querySelector('.csfree[data-ct="agency"]')?.hidden === false
    && md?.querySelector('#cs-agency')?.value === 'Agentur Freitext Alt', 'the old free text of the agency stays and is shown');
  w.close();
  const anja = await call('POST', '/api/contacts', {book_id: bk.id, fn: 'Anja Agentur', org: 'Werbe Beispiel GmbH', emails: [{value: 'anja@example.com'}], phones: [{value: '0170 1212121', type: ['cell']}]});
  const proj = await call('POST', '/api/lists', {name: 'Kampagne Fruehjahr'});
  const D2 = dstr(new Date(t.getFullYear(), t.getMonth(), t.getDate() + 10)), D3 = dstr(new Date(t.getFullYear(), t.getMonth(), t.getDate() + 20));
  const b2 = await call('POST', '/api/team/dispo/bookings', {title: 'Dreh Tag 1', start: D2, end: D2, status: 'firm', list_id: proj.id, resources: [{kind: 'contact', id: ct.id}]});
  check(anja.id && proj.id && b2.status === 201, 'setup: an agency contact, a project, its shoot day ' + JSON.stringify(b2).slice(0, 160));
  const job2 = b2.bookings?.[0]?.job;
  [w, d, sh] = await sheetOf(D2);
  sh?.querySelector('[data-m="callsheet"]')?.click();
  md = await until(() => d.querySelector('.modal.csmd #cs-agency_contact') && d.querySelector('.modal.csmd'));
  const sel = md?.querySelector('#cs-agency_contact');
  const opt = [...(sel?.options || [])].find(o => /Anja Agentur/.test(o.textContent));
  check(opt && /Werbe Beispiel GmbH/.test(opt.textContent) && sel.value === '', 'the agency can be chosen from the contacts (person and company), nothing chosen yet');
  if (sel && opt) { sel.value = opt.value; sel.dispatchEvent(new w.Event('change', {bubbles: true})); }
  const card = () => md?.querySelector('.csct[data-ct="agency"]');
  check(card() && !card().hidden && /Werbe Beispiel GmbH/.test(card().textContent) && /Anja Agentur/.test(card().textContent) && /0170 1212121/.test(card().textContent)
    && /anja@example\.com/.test(card().textContent) && md.querySelector('.csfree[data-ct="agency"]')?.hidden === true,
    'chosen: company, person, phone and e-mail of the contact are shown, the free text is put away: ' + (card()?.textContent || ''));
  md?.querySelector('[data-cs="save"]')?.click();
  const s2 = await until(async () => { const j = await call('GET', `/api/team/dispo/callsheet/${job2}?org=${org}`); return j.callsheet?.data?.agency_contact === anja.id && j.callsheet; });
  check(s2 && s2.auto?.agency_contact?.company === 'Werbe Beispiel GmbH', 'saved: the agency contact of the call sheet ' + JSON.stringify(s2?.data || {}).slice(0, 160));
  await until(() => md.querySelector('#cs-agency_contact')?.value === String(anja.id));
  check(/Anja Agentur/.test(card()?.textContent || '') && !card()?.hidden, 'after saving the dialog still shows the agency');
  w.close();
  // the next call sheet of the same project starts with the agency
  const b3 = await call('POST', '/api/team/dispo/bookings', {title: 'Dreh Tag 2', start: D3, end: D3, status: 'firm', list_id: proj.id, resources: [{kind: 'contact', id: ct.id}]});
  const job3 = b3.bookings?.[0]?.job;
  [w, d, sh] = await sheetOf(D3);
  sh?.querySelector('[data-m="callsheet"]')?.click();
  md = await until(() => d.querySelector('.modal.csmd #cs-agency_contact') && d.querySelector('.modal.csmd'));
  check(md && /Dreh Tag 2|Kampagne/.test(md.querySelector('h3')?.textContent || '') && md.querySelector('#cs-agency_contact')?.value === String(anja.id)
    && /Werbe Beispiel GmbH/.test(card()?.textContent || ''), 'a new call sheet of the project: the agency is filled in already');
  md?.querySelector('[data-cs="save"]')?.click();
  const s3 = await until(async () => { const j = await call('GET', `/api/team/dispo/callsheet/${job3}?org=${org}`); return j.callsheet?.data?.agency_contact === anja.id && j.callsheet; });
  check(s3, 'saved with the agency filled in');
  w.close();

  // ================= without Film & Video: no button
  await call('PUT', '/api/industry', {industry: ''});
  [w, d, sh] = await sheetOf(D);
  check(sh && !sh.querySelector('[data-m="callsheet"]'), 'without Film & Video: no "Call sheet" in the booking sheet');
  w.close();

  console.log(`p2802_a_callsheet_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
