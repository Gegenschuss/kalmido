// 2.576.0 (#4764) UI tests, own container (start.sh), jsdom, invented data only: the dialogs of clients, office master data
// kalmido-suite: fresh
// and letters save through objsave.js (only the changed fields + expect_updated_at) and a 409 shows the shared merge bar, never
// the old "Reload" line that dropped the input; contacts keep the input on other errors than 409
// - office master data (a service): another tab changed the English name meanwhile -> the open dialog shows the calm bar, the
//   save shows the merge bar, the English name is marked, the typed rate stays; "Keep mine" + save = this rate AND the
//   other tab's name (only the changed field went)
// - a client: another tab changed the phone -> merge bar, the phone marked, the typed note stays; "Keep mine" + save keeps both
// - a letter at 390 px: another tab changed the reference -> the merge bar inside the editor, the reference marked
// - a contact: the save fails without a connection (edit and new) -> the dialog comes back with what was typed; online again
//   the save goes through
// Every wait is on a real state (the server's object, the dialog's fields), never on a fixed time.
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
const until = (fn, t = 15000) => until0(fn, {timeout: t, step: 100});
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const FEAT = 'cal,comments,collab,office,clients,docs,contacts';
// the bodies of the page's PATCH requests (only the changed fields go)
const spy = w => {
  w.__sent = []; const f1 = w.fetch;
  w.fetch = (u, o = {}) => { if ((o.method || 'GET') === 'PATCH') { try { w.__sent.push({u: String(u), b: JSON.parse(o.body)}); } catch { w.__sent.push({u: String(u), b: null}); } } return f1(u, o); };
};

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});

  // ================= office master data: a service
  const SV = await call('POST', '/api/office/services', {name_de: 'Dreh', name_en: 'Shoot', daily_rate: 1000});
  check(SV.http === 201 && SV.id, 'a service ' + SV.http);
  const svc = async () => (await call('GET', `/api/office/services/${SV.id}`));
  check((await svc()).updated_at, 'the service has a version');
  let w = await boot({hash: 'office/services'}); let d = w.document;
  check(await until(() => { try { return w.eval(`!!ofcRow('services', ${SV.id})`); } catch { return false; } }), 'the services are loaded');
  w.eval(`ofcModal('services', ofcRow('services', ${SV.id}))`);
  let md = await until(() => d.querySelector('.modal.ofcdlg #of-daily_rate') && d.querySelector('.modal.ofcdlg'));
  check(md, 'the service dialog opens');
  const o1 = await call('PATCH', `/api/office/services/${SV.id}`, {name_en: 'Filming'});  // another tab, after the dialog opened
  check(o1.http === 200, 'the other tab renamed the service');
  check(await until(() => md.querySelector('.obj-stale'), 20000), 'the open dialog shows the calm bar "Changed by someone else in the meantime"');
  spy(w);
  md.querySelector('#of-daily_rate').value = '1200';
  click(w, md.querySelector('[data-m="save"]'));
  check(await until(() => md.querySelector('.obj-merge [data-om="mine"]')), 'conflict: the merge bar on the dialog');
  check(!/Reload/.test(md.querySelector('.aerr')?.textContent || ''), 'no "Reload" line any more');
  check(md.isConnected && md.querySelector('#of-daily_rate').value === '1200', 'the typed rate stays');
  check(md.querySelector('#of-name_en')?.classList.contains('obj-theirs'), 'the English name is marked as changed by someone else');
  const s1 = w.__sent.find(x => x.u.includes(`/api/office/services/${SV.id}`));
  check(s1 && s1.b.daily_rate === 1200 && !('name_de' in s1.b) && s1.b.expect_updated_at, 'only the changed field + the version went ' + JSON.stringify(s1?.b || {}).slice(0, 200));
  let sj = await svc();
  check(sj.daily_rate === 1000 && sj.name_en === 'Filming', 'conflict: nothing was overwritten');
  click(w, md.querySelector('.obj-merge [data-om="mine"]'));
  check(!md.querySelector('.obj-merge'), 'Keep mine: the bar goes');
  md.querySelector('#of-name_en').value = 'Filming';  // the other tab's value as it stands (Keep mine keeps the input of this dialog)
  click(w, md.querySelector('[data-m="save"]'));
  check(await until(async () => (await svc()).daily_rate === 1200), 'Keep mine + save: this rate is saved');
  sj = await svc();
  check(sj.name_en === 'Filming', 'and the other tab\'s name stays');
  check(await until(() => !d.querySelector('.modal.ofcdlg')), 'the dialog closes after the save');
  w.close();

  // ================= a client
  const C = await call('POST', '/api/clients', {name: 'Example Media GmbH', phone: '+49 30 1', note: ''});
  check(C.http === 201 && C.updated_at, 'a client ' + C.http);
  w = await boot({hash: `client/${C.id}`}); d = w.document;
  await until(() => d.querySelector('#view .cldetail'));
  click(w, d.querySelector('[data-act="client-edit"]'));
  md = await until(() => d.querySelector('.modal.cldlg #cl-note') && d.querySelector('.modal.cldlg'));
  check(md, 'the client dialog opens');
  check((await call('PATCH', `/api/clients/${C.id}`, {phone: '+49 30 2'})).http === 200, 'the other tab changed the phone');
  md.querySelector('#cl-note').value = 'this tab';
  click(w, md.querySelector('[data-m="save"]'));
  check(await until(() => md.querySelector('.obj-merge [data-om="mine"]')), 'conflict: the merge bar on the client dialog');
  check(md.querySelector('#cl-note').value === 'this tab', 'the typed note stays');
  check(md.querySelector('#cl-phone')?.classList.contains('obj-theirs'), 'the phone is marked as changed by someone else');
  click(w, md.querySelector('.obj-merge [data-om="mine"]'));
  md.querySelector('#cl-phone').value = '+49 30 2';
  click(w, md.querySelector('[data-m="save"]'));
  check(await until(async () => (await call('GET', `/api/clients/${C.id}`)).note === 'this tab'), 'Keep mine + save: the note is saved');
  check((await call('GET', `/api/clients/${C.id}`)).phone === '+49 30 2', 'and the other tab\'s phone stays');
  w.close();

  // ================= a letter at 390 px
  const L = await call('POST', '/api/office/letters', {subject: 'First subject'});
  check(L.http === 201 && L.updated_at, 'a letter draft ' + L.http);
  w = await boot({hash: `office/letters/${L.id}`, mobile: true}); d = w.document;
  check(await until(() => d.querySelector('#lt-subject')), 'the letter editor is open on the phone');
  check((await call('PATCH', `/api/office/letters/${L.id}`, {ref_line: 'Their reference'})).http === 200, 'the other tab saved the reference');
  const subj = d.querySelector('#lt-subject');
  if (subj) {
    subj.value = 'My subject'; subj.dispatchEvent(new w.Event('input', {bubbles: true}));
    check(await until(() => d.querySelector('.obj-merge [data-om="theirs"]')), '390 px: the editor shows the merge bar');
    check(!/Reload/.test(d.querySelector('#lt-err')?.textContent || ''), '390 px: no "Reload" line');
    check(d.querySelector('[name="ref_line"]')?.classList.contains('obj-theirs'), '390 px: the reference is marked');
    const lj = await call('GET', `/api/office/letters/${L.id}`);
    check(lj.subject === 'First subject' && lj.ref_line === 'Their reference', '390 px: nothing was overwritten ' + lj.subject);
  }
  w.close();

  // ================= a contact: no connection -> the input comes back
  const BK = await call('POST', '/api/books', {name: 'People', org_id: null});
  const K = await call('POST', '/api/contacts', {book_id: BK.id, given: 'Ada', family: 'Lovelace', org: 'Acme', title: '', note: ''});
  check(K.id, 'a contact ' + JSON.stringify(K).slice(0, 160));
  w = await boot({hash: 'contacts'}); d = w.document;
  await until(() => typeof w.ctEditor === 'function');
  w.eval(`(async () => { CT.card = await api('GET', '/api/contacts/${K.id}'); ctEditor(CT.card); })()`);
  md = await until(() => typeof w.saveDialog === 'function' && d.querySelector('.modal.ctmodal #ct-title') && d.querySelector('.modal.ctmodal'));
  check(md, 'the contact dialog opens');
  md.querySelector('#ct-title').value = 'Engineer';
  w.__offline = true;
  click(w, md.querySelector('[data-ctm2="save"]'));
  md = await until(() => { const m = d.querySelector('.modal.ctmodal'); return m && m !== md && m; });
  check(md && md.querySelector('#ct-title')?.value === 'Engineer', 'edit without a connection: the dialog comes back with the typed title ' + md?.querySelector('#ct-title')?.value);
  check(!md?.querySelector('.obj-merge'), 'and no merge bar (it was no conflict)');
  w.__offline = false;
  if (md) click(w, md.querySelector('[data-ctm2="save"]'));
  check(await until(async () => (await call('GET', `/api/contacts/${K.id}`)).title === 'Engineer'), 'online again: the second save goes through');
  // a new contact
  await until(() => !d.querySelector('.modal.ctmodal'));
  w.eval('ctEditor(null)');
  md = await until(() => d.querySelector('.modal.ctmodal #ct-given') && d.querySelector('.modal.ctmodal'));
  md.querySelector('#ct-given').value = 'Grace'; md.querySelector('#ct-family').value = 'Hopper';
  w.__offline = true;
  click(w, md.querySelector('[data-ctm2="save"]'));
  const m2 = await until(() => { const m = d.querySelector('.modal.ctmodal'); return m && m !== md && m; });
  check(m2 && m2.querySelector('#ct-given')?.value === 'Grace' && m2.querySelector('#ct-family')?.value === 'Hopper', 'new without a connection: the dialog comes back with the typed name');
  w.__offline = false;
  w.close();

  console.log(`p2576_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
