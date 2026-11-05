// 2.565.0 UI test, part A (#4705): the contact and the event dialog after someone else saved meanwhile, jsdom, invented names only:
// kalmido-suite: fresh
// - contact: the dialog sends only the field changed in it (+ the version); another device changed another field meanwhile ->
//   the dialog comes back with the current contact, the own input over it and the other's field marked; saving again keeps both
// - contact: an open dialog shows the bar "Changed by someone else in the meantime" after the change poll; "Take over" draws the
//   current state with the own input over it; saving keeps both
// - event (a single one): the same conflict way; "Only this date" of a series whose other date was moved meanwhile: the
//   second save keeps both dates
// - the phone width once: the bar sits inside the dialog's card, the marked field is there
// freelancer-matrix: contacts, events (alice has no organisation: her private workspace)
// Every wait is on a real state (the server's contact / event, the dialog's fields), never on a fixed time.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, until: until0} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK, CK2;  // two devices of alice
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, t = 15000) => until0(fn, {timeout: t, step: 100});
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const pad = n => String(n).padStart(2, '0');
const dstr = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const D0 = dstr(new Date()), D1 = dstr(new Date(Date.now() + 86400000)), D2 = dstr(new Date(Date.now() + 2 * 86400000));
const lastModal = d => [...d.querySelectorAll('.modal')].pop();
// the bodies of the page's PATCH requests (to see that only the changed fields go)
const spy = w => {
  w.__sent = []; const f1 = w.__f1 || (w.__f1 = w.fetch);
  w.fetch = (u, o = {}) => { if ((o.method || 'GET') === 'PATCH') { try { w.__sent.push({u: String(u), b: JSON.parse(o.body)}); } catch { w.__sent.push({u: String(u), b: null}); } } return f1(u, o); };
};
const marked = (md, sel) => !!md.querySelector(sel)?.closest('.obj-theirs, .row.obj-theirs') || !!md.querySelector(sel)?.classList.contains('obj-theirs');

async function contactChecks(w, d, who) {
  const c = await call(CK, 'POST', '/api/contacts', {given: 'Ada', family: 'Lovelace', org: 'Acme', title: '', note: ''});
  check(c.id, `${who}: a contact on the server`);
  const open = async () => {
    w.eval(`(async () => { CT.card = await api('GET', '/api/contacts/${c.id}'); ctEditor(CT.card); })()`);
    return until(() => d.querySelector('.modal.ctmodal #ct-title') && typeof w.saveDialog === 'function' && d.querySelector('.modal.ctmodal'));
  };
  // ---- conflict on save: another field changed elsewhere
  spy(w);
  let md = await open();
  check((await call(CK2, 'PATCH', `/api/contacts/${c.id}`, {org: 'Globex'})).http === 200, `${who}: the other device changes the company`);
  md.querySelector('#ct-title').value = 'Engineer';
  click(w, md.querySelector('[data-ctm2="save"]'));
  md = await until(() => { const m = d.querySelector('.modal.ctmodal'); return m && m.querySelector('.obj-merge') && m; });
  check(!!md, `${who}: the dialog comes back with the merge bar`);
  const first = w.__sent.find(x => /\/api\/contacts\/\d+$/.test(x.u));
  check(first && JSON.stringify(Object.keys(first.b).sort()) === JSON.stringify(['expect', 'title']), `${who}: only the changed field went (+ the version): ${JSON.stringify(first?.b)}`);
  if (md) {
    check(md.querySelector('#ct-org').value === 'Globex' && md.querySelector('#ct-title').value === 'Engineer', `${who}: the current company, the own job title over it`);
    check(md.querySelector('#ct-org').classList.contains('obj-theirs') && !md.querySelector('#ct-title').classList.contains('obj-theirs'), `${who}: the other's field is marked, the own one not`);
    check(/marked fields/.test(md.querySelector('.obj-merge').textContent), `${who}: the bar says what the marks mean`);
    click(w, md.querySelector('[data-ctm2="save"]'));
  }
  check(await until(async () => { const x = await call(CK, 'GET', `/api/contacts/${c.id}`); return x.org === 'Globex' && x.title === 'Engineer'; }), `${who}: the second save keeps both changes`);
  check(await until(() => !d.querySelector('.modal.ctmodal')), `${who}: the dialog closed after the second save`);
  // ---- the bar of an open dialog after the change poll, "Take over"
  md = await open();
  md.querySelector('#ct-family').value = 'King';
  check((await call(CK2, 'PATCH', `/api/contacts/${c.id}`, {note: 'Met at the fair'})).http === 200, `${who}: the other device adds a note`);
  const bar = await until(() => md.querySelector('.obj-stale [data-os="take"]'), 25000);
  check(!!bar, `${who}: the open dialog shows "Changed by someone else" with Take over`);
  if (bar) {
    click(w, bar);
    md = await until(() => { const m = d.querySelector('.modal.ctmodal'); return m && m.querySelector('#ct-note')?.value === 'Met at the fair' && m; });
    check(md && md.querySelector('#ct-family').value === 'King' && md.querySelector('#ct-note').classList.contains('obj-theirs'), `${who}: Take over: the current note (marked), the own last name stays`);
    if (md) click(w, md.querySelector('[data-ctm2="save"]'));
    check(await until(async () => { const x = await call(CK, 'GET', `/api/contacts/${c.id}`); return x.family === 'King' && x.note === 'Met at the fair'; }), `${who}: saved: both changes on the server`);
  }
  d.querySelectorAll('.modal').forEach(m => m.remove());
  return c;
}

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice'); CK2 = await login('alice');
  await call(CK, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,events,contacts'});
  await call(CK, 'POST', '/api/books', {name: 'People', org_id: null});
  const W = await call(CK, 'POST', '/api/evcals', {name: 'Work', color: '#2dd4bf'});

  // ================= contacts (desktop)
  let w = await boot({user: 'alice', hash: 'contacts'}), d = w.document;
  check(await until(() => d.querySelector('#view [data-ct="new"]') && w.eval('Array.isArray(CT.items)')), 'the contacts view shows');
  await contactChecks(w, d, 'desktop');
  w.close();

  // ================= events
  w = await boot({user: 'alice', hash: 'cal', ls: {'tasks.calMode': '"month"'}}); d = w.document;
  await until(() => w.eval(`typeof evEditor === 'function' && Array.isArray(S.cal?.items)`));
  const PL = await call(CK, 'POST', '/api/events', {title: 'Planning', cal_id: W.id, start: `${D0}T11:00`, end: `${D0}T12:00`, reminders: []});
  const openEv = async (id, occ) => {
    const ev = await call(CK, 'GET', `/api/events/${id}`);
    w.eval(`evEditor({ev: ${JSON.stringify(ev)}${occ ? `, occ: ${JSON.stringify(occ)}` : ''}})`);
    return until(() => d.querySelector('.modal.evmodal #ev-title') && typeof w.saveDialog === 'function' && d.querySelector('.modal.evmodal'));
  };
  spy(w);
  let md = await openEv(PL.id);
  check((await call(CK2, 'PATCH', `/api/events/${PL.id}`, {location: 'Room 2'})).http === 200, 'event: the other device sets the place');
  md.querySelector('#ev-title').value = 'Planning Q1';
  click(w, md.querySelector('[data-evm="save"]'));
  md = await until(() => { const m = d.querySelector('.modal.evmodal'); return m && m.querySelector('.obj-merge') && m; });
  check(!!md, 'event: the dialog comes back with the merge bar');
  const first = w.__sent.find(x => new RegExp(`/api/events/${PL.id}$`).test(x.u));
  check(first && JSON.stringify(Object.keys(first.b).sort()) === JSON.stringify(['expect', 'title']), `event: only the changed field went (+ the version): ${JSON.stringify(first?.b)}`);
  if (md) {
    check(md.querySelector('#ev-loc').value === 'Room 2' && md.querySelector('#ev-title').value === 'Planning Q1', 'event: the current place, the own title over it');
    check(marked(md, '#ev-loc') && !marked(md, '#ev-title'), 'event: the place is marked, the title not');
    click(w, md.querySelector('[data-evm="save"]'));
  }
  check(await until(async () => { const x = await call(CK, 'GET', `/api/events/${PL.id}`); return x.title === 'Planning Q1' && x.location === 'Room 2'; }), 'event: the second save keeps both');
  d.querySelectorAll('.modal').forEach(m => m.remove());
  // ---- "Only this date" of a series while another date was moved elsewhere
  const SE = await call(CK, 'POST', '/api/events', {title: 'Standup', cal_id: W.id, start: `${D0}T09:00`, end: `${D0}T09:30`, rrule: 'FREQ=DAILY;COUNT=10', reminders: []});
  md = await openEv(SE.id, `${D1}T09:00`);
  check((await call(CK2, 'PATCH', `/api/events/${SE.id}?occ=${D2}T09:00`, {title: 'Standup late'})).http === 200, 'series: the other device changes another date');
  click(w, md.querySelector('[data-evsc="one"]'));
  md.querySelector('#ev-title').value = 'Standup remote';
  click(w, md.querySelector('[data-evm="save"]'));
  md = await until(() => { const m = d.querySelector('.modal.evmodal'); return m && m.querySelector('#ev-title')?.value === 'Standup remote' && !w.__sent.every(x => !/occ=/.test(x.u)) && m; });
  check(!!md, 'series: after the 409 the dialog comes back with the own title');
  if (md) click(w, md.querySelector('[data-evm="save"]'));
  check(await until(async () => { const x = await call(CK, 'GET', `/api/events/${SE.id}`); const t = Object.fromEntries((x.overrides || []).map(o => [o.rid, o.title])); return t[`${D1}T09:00`] === 'Standup remote' && t[`${D2}T09:00`] === 'Standup late'; }),
    'series: both single dates keep their change');
  w.close();

  // ================= the phone width once
  w = await boot({user: 'alice', hash: 'contacts', mobile: true}); d = w.document;
  check(await until(() => w.eval('Array.isArray(CT.items)')), 'phone: the contacts view shows');
  const c = await call(CK, 'POST', '/api/contacts', {given: 'Grace', family: 'Hopper', org: 'Navy'});
  w.eval(`(async () => { CT.card = await api('GET', '/api/contacts/${c.id}'); ctEditor(CT.card); })()`);
  md = await until(() => d.querySelector('.modal.ctmodal #ct-title') && typeof w.saveDialog === 'function' && d.querySelector('.modal.ctmodal'));
  await call(CK2, 'PATCH', `/api/contacts/${c.id}`, {org: 'Yale'});
  md.querySelector('#ct-title').value = 'Admiral';
  click(w, md.querySelector('[data-ctm2="save"]'));
  md = await until(() => { const m = d.querySelector('.modal.ctmodal'); return m && m.querySelector('.obj-merge') && m; });
  check(md && md.querySelector('.card .obj-merge') && md.querySelector('#ct-org').classList.contains('obj-theirs') && md.querySelector('#ct-org').value === 'Yale',
    'phone: the bar inside the dialog card, the company marked');
  w.close();

  console.log(`p2565_a_dialog_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
