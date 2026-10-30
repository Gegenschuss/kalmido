// 2.114.2 part A UI test (#2263), own container (start.sh): the "More" menu of a finalised quotation that was never sent
// offers "Undo finalising" and "Delete" (the confirmation names the gap in the office log); a sent one offers neither; the
// row menu of the list follows the server's can_delete. 2.417.0 C (#2604, #2574): the test phase of 2.144.8 is gone - a sent
// one offers neither again (the server keeps it: 409). Invented names only. P21142A_NOSTART=1 = the server already runs.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21142A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const items = d => [...d.querySelectorAll('#pop [role="menuitem"], .menu-list [role="menuitem"]')];
const names = d => items(d).map(b => b.textContent.trim());
const FEAT = 'clients,office';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Example Studio', lang: 'en', collab_all: true, modules: ['comments']});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'org:' + ORG});
  const C = await call('POST', '/api/clients', {name: 'Example Client AG', org_id: ORG});
  const mk = async title => {
    const q = await call('POST', '/api/office/docs', {project_title: title, client_id: C.id});
    await call('PUT', '/api/office/docs/' + q.id + '/items', {items: [{title: 'Shoot', qty: 1, rate: 900}]});
    const f = await call('POST', '/api/office/docs/' + q.id + '/finalize');
    check(f.locked === true, 'finalised ' + title + ' ' + JSON.stringify(f).slice(0, 200));
    return f;
  };
  const Q = await mk('Image film'), S = await mk('Sent film'), R = await mk('Row film');
  await call('POST', '/api/office/docs/' + S.id + '/status', {status: 'sent'});
  const open = async (w, d) => { const more = await until(() => d.querySelector('#view [data-ofd="more"]')); more?.click(); await until(() => items(d).length); return more; };
  const asked = [];

  // ================= never sent: "Undo finalising" brings back the draft with its number
  let w = await boot({user: 'alice', hash: 'office/offers/' + Q.id}), d = w.document;
  w.confirm = m => { asked.push(String(m)); return true; };
  check(await open(w, d), 'the quotation menu button');
  check(names(d).includes('Undo finalising') && names(d).includes('Delete'), 'never sent: undo finalising + delete ' + names(d).join(' | '));
  items(d).find(b => b.textContent.trim() === 'Undo finalising')?.click();
  const back = await until(async () => { const x = await call('GET', '/api/office/docs/' + Q.id); return x.locked === false && x; });
  check(back && back.number === Q.number, 'back to a draft with the same number ' + JSON.stringify(back).slice(0, 160));
  check(await until(() => d.querySelector('#view .ofdfin')), 'the editor offers "Finalise" again');
  w.close();

  // ================= finalised again, then deleted (the confirmation names the gap)
  await call('POST', '/api/office/docs/' + Q.id + '/finalize');
  w = await boot({user: 'alice', hash: 'office/offers/' + Q.id}); d = w.document;
  w.confirm = m => { asked.push(String(m)); return true; };
  await open(w, d);
  items(d).find(b => b.textContent.trim() === 'Delete')?.click();
  check(await until(async () => (await fetch(B + 'api/office/docs/' + Q.id, {headers: {...H, Cookie: CK}})).status === 404), 'deleted');
  check(asked.some(m => /gap in the office log/.test(m)), 'the confirmation names the gap ' + asked.join(' || '));
  w.close();

  // ================= sent: no undo finalising, no delete (2.417.0 C, #2604)
  w = await boot({user: 'alice', hash: 'office/offers/' + S.id}); d = w.document;
  await open(w, d);
  check(names(d).length && !names(d).includes('Delete') && !names(d).includes('Undo finalising'), 'sent: neither delete nor undo finalising ' + names(d).join(' | '));
  w.close();

  // ================= the list's row menu
  w = await boot({user: 'alice', hash: 'office/offers'}); d = w.document;
  const row = id => d.querySelector('.ofdrow[data-id="' + id + '"]');
  check(await until(() => row(R.id) && row(S.id), 60), 'the list rows');
  row(R.id)?.dispatchEvent(new w.MouseEvent('contextmenu', {bubbles: true, cancelable: true}));
  await until(() => items(d).length);
  check(names(d).includes('Delete') && names(d).includes('Undo finalising'), 'row menu, never sent: delete + undo ' + names(d).join(' | '));
  d.body.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
  await sleep(300);
  row(S.id)?.dispatchEvent(new w.MouseEvent('contextmenu', {bubbles: true, cancelable: true}));
  await until(() => items(d).some(b => b.textContent.trim() === 'Open'));
  check(!names(d).includes('Delete') && !names(d).includes('Undo finalising'), 'row menu, sent: neither (2.417.0, #2604) ' + names(d).join(' | '));
  w.close();

  // ================= 2.417.0 C (#2604, #2574): the server keeps the sent one
  check((await call('DELETE', '/api/office/docs/' + S.id)).status === 409, 'the sent quotation stays (409)');

  check(errs.length === 0, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
