// 2.576.0 (#4794) UI tests, own container (start.sh), jsdom, invented data only: the office dialogs save through objsave.js
// kalmido-suite: fresh
// (only the changed fields + expect_updated_at) and a conflict shows the shared merge bar instead of the own "Reload" line
// - a trip (the dialog closes at once): another tab changed the note meanwhile -> the dialog opens again on the saved trip with
//   this tab's destination and the merge bar; "Keep mine" + save = this destination AND the other tab's note (only the
//   changed field went); a second conflict: "Take theirs" opens the saved trip
// - a letter (autosave in the editor): another tab changed the reference meanwhile -> the merge bar, the reference field marked
//   as theirs, nothing overwritten; "Take theirs" shows the saved letter
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login, until: until0} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return Object.assign(j, {http: r.status}); };
const until = fn => until0(fn, {timeout: 15000, step: 100});
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const FEAT = 'cal,comments,collab,office,clients,docs';
const DAY = new Date().toISOString().slice(0, 10);

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});

  // ================= a trip
  const T = await call('POST', '/api/office/trips', {date_from: DAY, dest: 'Kiel', note: 'first note', people: []});
  check(T.http === 201 && T.updated_at, 'a trip ' + T.http);
  const trip = async () => (await call('GET', `/api/office/trips?year=${DAY.slice(0, 4)}`)).trips.find(t => t.id === T.id);
  let w = await boot({hash: 'office/travel'}); let d = w.document;
  const dlg = () => d.querySelector('.modal.ofcdlg');
  const head = () => d.querySelector('.rkhead h3')?.textContent || '';
  const openEdit = async () => {
    if (!d.querySelector('[data-rk="edit"]')) { click(w, [...d.querySelectorAll('.rklist [data-rk="open"]')].find(b => /Kiel|Hafen/.test(b.textContent))); await until(() => d.querySelector('[data-rk="edit"]')); }
    for (const m of d.querySelectorAll('.modal.ofcdlg')) m.remove();
    click(w, d.querySelector('[data-rk="edit"]'));
    return until(() => dlg()?.querySelector('#rk-dest'));
  };
  check(await until(() => [...d.querySelectorAll('.rklist [data-rk="open"]')].some(b => /Kiel/.test(b.textContent))), 'the travel tab lists the trip');
  check(await openEdit(), 'the trip dialog opens');
  const o1 = await call('PATCH', `/api/office/trips/${T.id}`, {note: 'their note'});  // another tab, after this dialog opened
  check(o1.http === 200 && o1.note === 'their note', 'the other tab saved the note');
  dlg().querySelector('#rk-dest').value = 'Kiel Hafen'; click(w, dlg().querySelector('[data-m="save"]'));
  check(await until(() => dlg()?.querySelector('.obj-merge [data-om="mine"]')), 'conflict: the dialog opens again with the merge bar');
  check(/Changed by someone else in the meantime/.test(dlg()?.querySelector('.obj-merge')?.textContent || ''), 'the bar says why');
  check(dlg()?.querySelector('#rk-dest')?.value === 'Kiel Hafen' && dlg()?.querySelector('#rk-note')?.value === 'their note',
    'opened on the saved trip with this tab\'s destination: ' + dlg()?.querySelector('#rk-dest')?.value + ' / ' + dlg()?.querySelector('#rk-note')?.value);
  check((await trip()).dest === 'Kiel' && (await trip()).note === 'their note', 'conflict: nothing was overwritten');
  click(w, dlg().querySelector('.obj-merge [data-om="mine"]'));
  check(!dlg()?.querySelector('.obj-merge'), 'Keep mine: the bar goes');
  click(w, dlg().querySelector('[data-m="save"]'));
  check(await until(async () => (await trip()).dest === 'Kiel Hafen'), 'Keep mine + save: this destination is saved');
  check((await trip()).note === 'their note', 'and the other tab\'s note stays (only the changed field went)');
  check(await until(() => head() === 'Kiel Hafen' && !dlg()), 'the trip shows the saved destination');
  // a second conflict: Take theirs
  check(await openEdit(), 'the trip dialog opens again');
  const o2 = await call('PATCH', `/api/office/trips/${T.id}`, {dest: 'Kiel Nord'});
  check(o2.http === 200, 'the other tab renamed the destination');
  dlg().querySelector('#rk-note').value = 'my note'; click(w, dlg().querySelector('[data-m="save"]'));
  check(await until(() => dlg()?.querySelector('.obj-merge [data-om="theirs"]')), 'conflict 2: the merge bar');
  const m1 = dlg();
  click(w, m1.querySelector('.obj-merge [data-om="theirs"]'));
  check(await until(() => dlg() && dlg() !== m1 && dlg().querySelector('#rk-dest')?.value === 'Kiel Nord' && dlg().querySelector('#rk-note')?.value === 'their note'),
    'Take theirs: the dialog shows the saved trip ' + dlg()?.querySelector('#rk-dest')?.value + ' / ' + dlg()?.querySelector('#rk-note')?.value);
  check((await trip()).note === 'their note', 'conflict 2: nothing was overwritten');
  w.close();

  // ================= a letter (autosave)
  const L = await call('POST', '/api/office/letters', {subject: 'First subject'});
  check(L.http === 201 && L.updated_at, 'a letter draft ' + L.http);
  w = await boot({hash: `office/letters/${L.id}`}); d = w.document;
  check(await until(() => d.querySelector('#lt-subject')), 'the letter editor is open');
  const o3 = await call('PATCH', `/api/office/letters/${L.id}`, {ref_line: 'Their reference'});
  check(o3.http === 200, 'the other tab saved the reference');
  const subj = d.querySelector('#lt-subject');
  if (subj) {
    subj.value = 'My subject'; subj.dispatchEvent(new w.Event('input', {bubbles: true}));
    check(await until(() => d.querySelector('.obj-merge [data-om="theirs"]')), 'conflict: the editor shows the merge bar');
    check(/Changed by someone else in the meantime/.test(d.querySelector('.obj-merge')?.textContent || ''), 'the bar says why');
    check(d.querySelector('[name="ref_line"]')?.classList.contains('obj-theirs'), 'the reference is marked as changed by someone else');
    const lj = await call('GET', `/api/office/letters/${L.id}`);
    check(lj.subject === 'First subject' && lj.ref_line === 'Their reference', 'conflict: nothing was overwritten ' + lj.subject);
    click(w, d.querySelector('.obj-merge [data-om="theirs"]'));
    check(await until(() => d.querySelector('#lt-ref_line')?.value === 'Their reference' && d.querySelector('#lt-subject')?.value === 'First subject' && !d.querySelector('.obj-merge')),
      'Take theirs: the editor shows the saved letter ' + d.querySelector('#lt-subject')?.value);
  }
  w.close();

  console.log(`p2570_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
