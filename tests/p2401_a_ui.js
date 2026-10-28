// kalmido-suite: fresh
// 2.401.0 (#2924): the Workspace field of the project dialog runs the server's dry run first. A project with a client of the
// organisation going private: the move dialog names the client before anything moves, Cancel puts the field back and moves
// nothing, Move moves it. A private project shared with somebody outside the organisation: the dialog blocks the move there.
// Nothing to say (an empty private project into the organisation of its admin): it moves at once, as before. Own container.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const change = (w, el, v) => { el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const orgOf = async id => (await call('GET', '/api/state')).lists.find(l => l.id === id)?.org_id ?? null;

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Example Org', lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'collab,comments,clients'});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  const W = (await call('POST', '/api/lists', {name: 'Website', org_id: ORG})).id;
  const CL = (await call('POST', '/api/clients', {name: 'Northwind Example GmbH', org_id: ORG})).id;
  await call('PATCH', `/api/lists/${W}`, {client_id: CL});
  const P = (await call('POST', '/api/lists', {name: 'Garden party', org_id: null})).id;
  await call('PUT', `/api/lists/${P}/members`, {email: 'bob@example.com', role: 'edit'});
  const E = (await call('POST', '/api/lists', {name: 'Empty', org_id: null})).id;
  check(CL && W && P && E, 'setup');
  const w = await boot({user: 'alice', hash: 'l/' + W}), d = w.document;

  // the client of the organisation: named first; Cancel = the field back, nothing moved
  w.eval(`listModal(${W})`);
  let md = await until(() => d.querySelector('.modal.lmodal #l-ws') && d.querySelector('.modal.lmodal'));
  change(w, md.querySelector('#l-ws'), '');
  let dlg = await until(() => { const x = d.querySelector('.smv-dlg'); return x && /client of the project/.test(x.textContent) ? x : null; });
  check(!!dlg, '#2924: going private, the move dialog names the client before anything moves');
  check(await orgOf(W) === ORG, '#2924: nothing moved while the dialog is open');
  click(w, dlg.querySelector('[data-smv="no"]'));
  check(await until(() => !d.querySelector('.smv-dlg') && md.querySelector('#l-ws').value === String(ORG)), '#2924: Cancel puts the field back');
  check(await orgOf(W) === ORG, '#2924: Cancel moves nothing');
  // Move = moved (and the toast keeps the Undo that brings the client back)
  change(w, md.querySelector('#l-ws'), '');
  dlg = await until(() => { const x = d.querySelector('.smv-dlg'); const b = x?.querySelector('[data-smv="yes"]'); return b && !b.disabled ? x : null; });
  check(!!dlg, '#2924: the dialog again, Move enabled');
  if (dlg) dlg.querySelector('form').dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true}));
  check(await until(async () => await orgOf(W) === null), '#2924: Move moves the project into the private space');
  d.querySelectorAll('.modal').forEach(x => x.remove());

  // a member outside the organisation: the dialog blocks
  w.eval(`listModal(${P})`);
  md = await until(() => d.querySelector('.modal.lmodal #l-ws') && d.querySelector('.modal.lmodal'));
  change(w, md.querySelector('#l-ws'), String(ORG));
  dlg = await until(() => { const x = d.querySelector('.smv-dlg'); return x?.querySelector('.smv-block') ? x : null; });
  check(dlg && /Bob/.test(dlg.querySelector('.smv-block').textContent) && dlg.querySelector('[data-smv="yes"]').disabled,
    '#2924: a member outside the organisation blocks the move (named, Move disabled)');
  if (dlg) click(w, dlg.querySelector('[data-smv="no"]'));
  check(await until(() => md.querySelector('#l-ws').value === ''), '#2924: the field goes back to Private');
  check(await orgOf(P) === null, '#2924: the blocked project stays private');
  d.querySelectorAll('.modal').forEach(x => x.remove());

  // nothing to say: moved at once, no dialog (as before)
  w.eval(`listModal(${E})`);
  md = await until(() => d.querySelector('.modal.lmodal #l-ws') && d.querySelector('.modal.lmodal'));
  change(w, md.querySelector('#l-ws'), String(ORG));
  check(await until(async () => await orgOf(E) === ORG), '#2924: without notes the project moves at once');
  check(!d.querySelector('.smv-dlg'), '#2924: and no move dialog shows');
  w.close();
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
