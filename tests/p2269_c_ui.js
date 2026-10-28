// 2.269.0 C (#3017) UI tests, own container (start.sh), jsdom, invented data only:
// - the client dialog: saved elsewhere meanwhile -> the save shows "Changed in the meantime" with "Reload" (nothing is
//   overwritten, the dialog stays open); "Reload" opens it with the saved state; a contact person removed in the dialog
//   is deleted (contacts_removed), one added in another tab meanwhile stays
// - the letter editor: typed text is saved when the editor is left before the pause is over (another view at once)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return Object.assign(j, {http: r.status}); };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const FEAT = 'cal,comments,collab,office,clients';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const c1 = await call('POST', '/api/clients', {name: 'Example Media GmbH', contacts: [{name: 'Erika Example', is_default: true}, {name: 'Max Sample', email: 'max@example.com'}]});
  check(c1.http === 201 && c1.contacts?.length === 2, 'a client with two contact persons');
  const CL = c1.id, K_MAX = c1.contacts.find(k => k.name === 'Max Sample')?.id;

  // ================= the client dialog
  let w = await boot({hash: `client/${CL}`}); let d = w.document;
  await until(() => d.querySelector('#view .cldetail'), 60);
  click(w, d.querySelector('[data-act="client-edit"]'));
  await until(() => d.querySelector('.modal.cldlg .clkc'), 30);
  let md = d.querySelector('.modal.cldlg');
  // another tab saves meanwhile: a note and a third contact person
  const other = await call('PATCH', `/api/clients/${CL}`, {note: 'other tab', contacts: [...c1.contacts.map(k => ({id: k.id, name: k.name})), {name: 'Ida New'}]});
  check(other.http === 200, 'the other tab saved');
  md.querySelector('#cl-note').value = 'this tab';
  click(w, md.querySelector('[data-m="save"]'));
  await until(() => md.querySelector('[data-cl-reload]'), 40);
  check(md.isConnected && /Changed in the meantime/.test(md.querySelector('.aerr')?.textContent || '') && md.querySelector('[data-cl-reload]'),
    'conflict: the dialog stays open with "Changed in the meantime" and "Reload": ' + (md.querySelector('.aerr')?.textContent || ''));
  let cj = await call('GET', `/api/clients/${CL}`);
  check(cj.note === 'other tab' && cj.contacts.length === 3, 'conflict: nothing was overwritten');
  click(w, md.querySelector('[data-cl-reload]'));
  await until(() => d.querySelector('.modal.cldlg') && d.querySelector('.modal.cldlg') !== md, 30);
  md = d.querySelector('.modal.cldlg');
  check(md && md.querySelector('#cl-note').value === 'other tab' && md.querySelectorAll('.clkc').length === 3, 'reload: the dialog shows the saved state');
  // remove "Max Sample" in the dialog, save: deleted, the others stay
  const i = [...md.querySelectorAll('[data-clk="name"]')].findIndex(el => el.value === 'Max Sample');
  click(w, md.querySelectorAll('[data-clk-rm]')[i]);
  check(md.querySelectorAll('.clkc').length === 2, 'dialog: a contact card removed');
  click(w, md.querySelector('[data-m="save"]'));
  await until(async () => (await call('GET', `/api/clients/${CL}`)).contacts.length === 2, 40);
  cj = await call('GET', `/api/clients/${CL}`);
  check(cj.contacts.length === 2 && !cj.contacts.some(k => k.id === K_MAX) && cj.contacts.some(k => k.name === 'Ida New'), 'saved: the removed one is gone, the one of the other tab stays: ' + cj.contacts.map(k => k.name));
  w.close();

  // ================= the letter editor: left before the pause -> saved anyway
  const L = await call('POST', '/api/office/letters', {});
  check(L.http === 201, 'a letter draft ' + L.http);
  w = await boot({hash: `office/letters/${L.id}`}); d = w.document;
  await until(() => d.querySelector('#lt-subject'), 60);
  const subj = d.querySelector('#lt-subject');
  check(!!subj, 'the letter editor is open');
  if (subj) {
    subj.value = 'Typed and left at once';
    subj.dispatchEvent(new w.Event('input', {bubbles: true}));
    w.location.hash = '#office/letters';
    const got = await until(async () => (await call('GET', `/api/office/letters/${L.id}`)).subject === 'Typed and left at once', 40);
    check(got, 'leaving the editor saves the typed subject');
  }
  w.close();

  console.log(`p2269_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
