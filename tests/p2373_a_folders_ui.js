// kalmido-suite: fresh
// 2.373.0 (#3337) UI test, jsdom: small things of the folders from the review of 2.351. Own container (start.sh).
// Invented names only. Frida has NO organisation (P4).
// - the address book's folders (ctfold.js) follow another person's change without reloading the page: bob makes a folder
//   and shares it with alice, her live version moves, the panel's next drawing loads the tree again (like office_tree.js;
//   rollback test: before, the tree was loaded once only)
// - "Mark as sent" (office_letters.js ltSentModal) while the folders of Correspondence are still loading: it waits on that
//   load and offers the folder (rollback test: before, the dialog came without the folder choice)
// freelancer-matrix: office
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const FEATURES = 'cal,collab,comments,contacts,files,docs,clients,office';
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const until = async (fn, n = 100) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(200); } return fn(); };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: FEATURES});
  const ALICE = (await call('GET', '/api/state')).me.id;
  const ORG = (await call('POST', '/api/admin/orgs', {name: 'Alpha Example', admin_id: ALICE})).id;
  await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  await call('PUT', `/api/orgs/${ORG}/members`, {email: 'bob@example.com', role: 'member'});
  const BK = await login('bob');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: FEATURES}, BK);
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const FK = await login('frida');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: FEATURES}, FK);

  // ================= the address book's folders follow another person's change
  const a0 = (await call('POST', '/api/contacts/folders', {space: 'org:' + ORG, name: 'Alice clients'})).folder?.id;
  check(a0, 'setup: alice has a folder in the address book');
  let w = await boot({user: 'alice', hash: 'contacts'});
  const ctf = e => w.eval(`typeof CTF === 'object' && CTF.d ? ${e} : null`);
  check(await until(() => ctf(`CTF.d.folders.some(f => f.id === ${a0})`)), 'the address book tree is loaded');
  const v0 = w.eval('S.v');
  const b0 = (await call('POST', '/api/contacts/folders', {space: 'org:' + ORG, name: 'Bob suppliers'}, BK)).folder?.id;
  const sh = b0 && await call('POST', `/api/files/nodes/${b0}/shares`, {user_id: ALICE, role: 'edit'}, BK);
  check(b0 && sh?.id, 'setup: bob makes a folder and shares it with alice ' + JSON.stringify(sh));
  check(await until(() => w.eval('S.v') > v0), 'alice learns of the change (her live version moves)');
  // the panel draws again on the next change of the view; the tree is fetched again then (at most every 4 s)
  check(await until(() => { w.eval('renderSide()'); return ctf(`CTF.d.folders.some(f => f.id === ${b0})`); }),
    '#3337: bob\'s shared folder appears in alice\'s address book without reloading the page');
  w.close();

  // ================= "Mark as sent" waits on the folders that are loading (a person without an organisation)
  const lf = (await call('POST', '/api/office/letters/tree/folders', {name: 'Letters 2026'}, FK)).folder?.id;
  check(lf, 'setup: frida\'s Correspondence folder');
  w = await boot({user: 'frida', hash: 'office/letters'});
  const d = w.document;
  check(await until(() => w.eval(`typeof oft_load === 'function' && typeof ltSentModal === 'function'`)), 'the office is loaded');
  await until(() => !w.eval('OFT.busy.letters'));
  w.eval(`OFT.d.letters = undefined; oft_load('letters'); ltSentModal({id: 0, channel: 'post', followup_days: 14})`);
  const sel = await until(() => d.querySelector('#lt-schan') && d.querySelector('#lt-schan').closest('.ofcdlg'));
  check(sel, 'the dialog "Mark as sent" opens');
  const opt = d.querySelector('#lt-sfold');
  check(opt && [...opt.options].some(o => o.value === String(lf)), '#3337: it waited on the loading folders and offers "Letters 2026" ' + (opt ? opt.outerHTML : 'no folder choice'));
  w.close();

  console.log(`p2373_a_folders_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
