// 2.140.0 D UI tests (#2137), own container (start.sh) with the fake server fake_carddav_wb.py, invented data, jsdom.
// Family › Birthdays from your contacts: every connected address book has the switch "Write changes back to the address
// book" (off by default). Switching it on asks first: "Cancel" leaves it off, "Switch on" saves it (the server says on, the
// switch stays on after reopening). Switching it off saves at once. A read-only address book (a mirror: privilege set
// without write) shows the hint instead of a switch. The family section of a birthday from an address book has the date
// field (#d-fdate); a birthday made by hand has none.
// P2140D_NOSTART=1: a running server (with the fake server on 127.0.0.1:8097), no start.sh.
const fs = require('fs');
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const NOSTART = !!process.env.P2140D_NOSTART;
const CT = process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test';
const PW = 'wb-secret-2140', URL = 'http://127.0.0.1:8097/';
const CARD = 'BEGIN:VCARD\r\nVERSION:3.0\r\nUID:ui-c1\r\nFN:Erik Beispiel\r\nBDAY:1975-06-01\r\nEND:VCARD\r\n';

(async () => {
  const wb = path.join(DATA, 'wb');
  fs.mkdirSync(wb, {recursive: true});
  if (!NOSTART) {
    const extra = (process.env.EXTRA || '') + ' -e KALMIDO_CALENDAR_ALLOW_HOSTS=127.0.0.1:8097 -e KALMIDO_CALENDAR_TICK=1';
    execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: extra}});
  }
  fs.mkdirSync(wb, {recursive: true}); fs.chmodSync(wb, 0o777);
  for (const acc of ['u', 'm']) {
    fs.mkdirSync(path.join(wb, acc), {recursive: true}); fs.chmodSync(path.join(wb, acc), 0o777);
    fs.writeFileSync(path.join(wb, acc, 'c1.vcf'), CARD); fs.chmodSync(path.join(wb, acc, 'c1.vcf'), 0o666);
  }
  fs.copyFileSync(path.join(__dirname, 'fake_carddav_wb.py'), path.join(DATA, 'fake_carddav_wb.py'));
  if (!NOSTART) execFileSync('docker', ['exec', '-d', CT, 'python', '/data/fake_carddav_wb.py']);
  await sleep(800);
  let CK;
  const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
  const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments', 'family']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,family'});
  const S1 = await call('POST', '/api/family/contacts', {url: URL, username: 'u', password: PW});
  check(S1.http === 201 && S1.writeback === false, 'a writable address book, write-back off ' + JSON.stringify(S1).slice(0, 200));
  const S2 = await call('POST', '/api/family/contacts', {url: URL, username: 'm', password: PW});
  check(S2.http === 201 && S2.writeback_avail === 'no', 'a mirror: read only ' + JSON.stringify(S2).slice(0, 200));

  // ---- the dialog: switch + hint
  let w = await boot({hash: 'family'}); let d = w.document;
  w.eval('contactsModal()');
  const sw = () => d.querySelector(`[data-ctwb="${S1.id}"]`);
  check(!!await until(() => sw(), 60), 'the writable address book has the switch');
  check(sw() && !sw().checked && sw().closest('.swc'), 'off by default, a switch (.swc)');
  check(/Write changes back to the address book/.test(sw()?.closest('.ctwb')?.textContent || ''), 'the switch is labelled');
  check(!d.querySelector(`[data-ctwb="${S2.id}"]`) && /Read only/.test(d.querySelector(`[data-ctwbro="${S2.id}"]`)?.textContent || ''), 'the mirror: a hint instead of the switch');
  // on -> asks; Cancel leaves it off
  sw().checked = true; sw().dispatchEvent(new w.Event('change', {bubbles: true}));
  check(!!await until(() => d.querySelector('.cdlg [data-cd="no"]')), 'switching on asks first');
  d.querySelector('.cdlg [data-cd="no"]').click();
  await until(() => !d.querySelector('.cdlg'));
  check(!sw().checked && (await call('GET', '/api/family/contacts')).sources.find(x => x.id === S1.id).writeback === false, 'Cancel: stays off');
  // on -> Switch on saves
  sw().checked = true; sw().dispatchEvent(new w.Event('change', {bubbles: true}));
  const yes = await until(() => d.querySelector('.cdlg [data-cd="yes"]'));
  check(/Switch on/.test(yes?.textContent || ''), 'the confirm button says "Switch on"');
  yes.click();
  check(await until(async () => (await call('GET', '/api/family/contacts')).sources.find(x => x.id === S1.id).writeback === true), 'Switch on: saved on the server');
  check(await until(() => sw() && sw().checked), 'the switch shows on after the reload of the list');
  d.querySelector('.modal [data-m="close"]')?.click();
  w.eval('contactsModal()');
  check(await until(() => sw() && sw().checked, 60), 'reopened: still on');
  // off saves at once (no question)
  sw().checked = false; sw().dispatchEvent(new w.Event('change', {bubbles: true}));
  check(!d.querySelector('.cdlg') && await until(async () => (await call('GET', '/api/family/contacts')).sources.find(x => x.id === S1.id).writeback === false), 'off: saved at once');
  w.close();

  // ---- the family section: the date field only for a birthday from an address book
  const st = await call('GET', '/api/state');
  const fromBook = st.tasks.find(t => t.fam && t.fam.src === `carddav:${S1.id}`);
  const occ = await call('POST', '/api/family/occasions', {name: 'Hand Made', date: '--08-08'});
  w = await boot({hash: 'family'}); d = w.document;
  await until(() => w.eval('typeof famDetailHtml') === 'function', 40);
  const html = id => w.eval(`(() => { const t = taskById(${id}); return t ? famDetailHtml(t, listById(t.list_id), false) : 'missing'; })()`);
  check(fromBook && /id="d-fdate"/.test(html(fromBook.id)), 'a birthday from the address book: the date field');
  check(occ.id ? !/id="d-fdate"/.test(html(occ.id)) : true, 'a birthday made by hand: no date field ' + JSON.stringify(occ).slice(0, 120));
  w.close();

  console.log(`p2140_d_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
