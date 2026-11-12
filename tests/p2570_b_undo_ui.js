// 2.570.0 B (#4770) UI tests, own container (start.sh), jsdom, invented data only:
// kalmido-suite: fresh
// The rest of #4704: the undo of a bookmark and of a document is a second write against the version of the own save
// (core.js undoStep), never over what another session saved meanwhile. Two sessions of the same person: the page (A) and
// the API (B), for a member of an organisation and for a person without an organisation (freelancer parity).
// - a bookmark marked read on its card (the toast's Undo): B adds a note, A presses Undo -> "Changed elsewhere, not
//   undone", the bookmark stays read, B's note stays; without a change elsewhere the Undo takes it back as before (the
//   preview fetch leaving the version: p2570_b_undo_test.py). 2.1005.0 (#5637): the toast takes back exactly its own server
//   step (POST /api/undo/<group>/undo), never a newer step of the same person on another bookmark with it
// - a document's due date set through the details (dc_patch, the history step): B renames it, A undoes -> said, the due date
//   stays; a recognition run after the save is no change: the undo goes through
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login, until: until0} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const until = fn => until0(fn, {timeout: 20000, step: 100});
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const FEAT = 'cal,collab,docs,files,reading';

async function upload(ck, name, text) {
  const fd = new FormData(); fd.append('ws', 'private'); fd.append('files', new Blob([text], {type: 'text/plain'}), name);
  const r = await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: ck}, body: fd});
  return (await r.json()).ids?.[0];
}

async function round(who, ck) {
  // ================= a bookmark: the toast's Undo
  const bm = await call(ck, 'POST', '/api/bookmarks', {url: `http://10.1.2.3/${who}`, title: `Link of ${who}`});
  check(bm.http === 201 && bm.bookmark?.id, `${who}: a bookmark ${bm.http}`);
  const id = bm.bookmark?.id, getB = () => call(ck, 'GET', `/api/bookmarks/${id}`);
  check(await until(async () => (await getB()).preview === 'failed'), `${who}: its preview fetch is over (a refused address)`);
  let w = await boot({user: who, hash: 'bookmarks'}); let d = w.document;
  const toastText = () => d.querySelector('#toast')?.textContent || '';
  const undoBtn = () => d.querySelector('#toast:not(.hidden) button:not(.tx)');
  const readBtn = () => d.querySelector(`[data-bm="read"][data-id="${id}"]`);
  check(await until(() => readBtn()), `${who}: the card with its read button`);
  click(w, readBtn());
  check(await until(async () => (await getB()).state === 'read'), `${who}: A marked it read`);
  check(await until(() => undoBtn()), `${who}: a toast with Undo: ${toastText()}`);
  const b1 = await call(ck, 'PATCH', `/api/bookmarks/${id}`, {note: 'Note of B'});
  check(b1.http === 200 && b1.note === 'Note of B', `${who}: B added a note`);
  click(w, undoBtn());
  check(await until(() => /Changed elsewhere, not undone|Changed by someone else in the meantime/.test(toastText())), `${who}: the Undo says it was changed elsewhere: ${toastText()}`);  // 2.1005.0 (#5637): or the server's conflict text of the single group
  let now = await getB();
  check(now.state === 'read' && now.note === 'Note of B', `${who}: still read, B's note stays ${now.state} ${now.note}`);
  // without a change elsewhere (a preview fetch in between is none): the Undo works as before
  check(await until(() => readBtn()), `${who}: the card again`);
  click(w, readBtn());
  check(await until(async () => (await getB()).state === 'unread'), `${who}: A marked it unread`);
  check(await until(() => undoBtn()), `${who}: a toast with Undo again`);
  // 2.1005.0 (#5637): a newer step of the same person on ANOTHER bookmark (another device) stays when the toast's Undo goes
  const bm2 = await call(ck, 'POST', '/api/bookmarks', {url: `http://10.1.2.4/${who}`, title: `Second of ${who}`});
  const id2 = bm2.bookmark?.id, b2 = await call(ck, 'PATCH', `/api/bookmarks/${id2}`, {note: 'Newer of B'});
  check(b2.http === 200 && b2.note === 'Newer of B', `${who}: B changed a second bookmark after A's step`);
  click(w, undoBtn());
  check(await until(async () => (await getB()).state === 'read'), `${who}: Undo without a change elsewhere takes it back`);
  check(await until(() => readBtn()?.title === 'Mark unread'), `${who}: the card shows it read again (its button: ${readBtn()?.title})`);
  const n2 = await call(ck, 'GET', `/api/bookmarks/${id2}`);
  check(n2.note === 'Newer of B', `${who}: the newer step on the second bookmark stays (#5637: it went back with it) ${n2.note}`);
  now = await getB();
  check(now.note === 'Note of B', `${who}: ... and leaves the note ` + now.note);
  w.close();

  // ================= a document: the history step of the details
  const nid = await upload(ck, `bill-${who}.txt`, 'Invoice 12.03.2026 total 10.00 EUR');
  check(nid > 0, `${who}: a document`);
  const getD = () => call(ck, 'GET', `/api/docs/${nid}`);
  check(await until(async () => ['done', 'failed'].includes((await getD()).state)), `${who}: its recognition run is over`);
  w = await boot({user: who, hash: 'docs'}); d = w.document;
  const msg = () => d.querySelector('#toast')?.textContent || '';
  const setDue = async v => { await w.eval(`(async () => { DC.doc = await api('GET', '/api/docs/${nid}'); await dc_patch(${nid}, {due: ${JSON.stringify(v)}}, 'Due of the bill'); })()`); };
  check(await until(() => typeof w.dc_patch === 'function'), `${who}: the documents module is there`);
  await setDue('2027-01-15');
  check(await until(async () => (await getD()).due === '2027-01-15'), `${who}: A set the due date`);
  const r1 = await call(ck, 'PATCH', `/api/docs/${nid}`, {name: `renamed-${who}.txt`});
  check(r1.http === 200, `${who}: B renamed the document`);
  await w.eval(`histStep('undo')`);
  check(await until(() => /Changed elsewhere, not undone/.test(msg())), `${who}: the undo says it was changed elsewhere: ${msg()}`);
  let dd = await getD();
  check(dd.due === '2027-01-15' && dd.name === `renamed-${who}.txt`, `${who}: the due date is not undone, B's name stays ${dd.due} ${dd.name}`);
  await setDue('2027-02-01');
  check(await until(async () => (await getD()).due === '2027-02-01'), `${who}: A set the due date again`);
  await call(ck, 'POST', `/api/docs/${nid}/redo`);  // a run of the recognition after the save (hand values stay): no change
  check(await until(async () => (await getD()).state === 'done'), `${who}: the recognition ran again`);
  await w.eval(`histStep('undo')`);
  check(await until(async () => (await getD()).due === '2027-01-15'), `${who}: the undo after the run takes the due date back ` + (await getD()).due);
  w.close();
}

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  check(org.id > 0, 'an organisation');
  // the bookmark and the document are private: the page shows the private space (an organisation of her own moves her into it)
  await call(CA, 'PATCH', '/api/settings', {workspace: 'private'});
  await round('alice', CA);

  // ================= a person without an organisation: the same
  await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'private'});
  check(((await call(CF, 'GET', '/api/state')).me.workspaces || []).length === 0, 'frida has no organisation');
  await round('frida', CF);

  console.log(`p2570_b_undo_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
