// 2.97.0 part C UI test (#2049), own container (start.sh): a client of the office to the other workspace. The client card's
// menu offers "Move to another workspace…" (only with an organisation: a person without one never sees it), the shared
// dialog shows the dry run and the tick box for read-only copies of issued documents, "Move" moves the client with its
// draft, Undo brings both back (ONE step). The quotation's menu offers the same for a draft.
// P297C_NOSTART=1 = the server already runs.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P297C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const items = d => [...d.querySelectorAll('#pop [role="menuitem"], .menu-list [role="menuitem"]')];
const FEAT = 'clients,office';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'private'});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  await call('POST', '/api/users', {username: 'dave', display_name: 'Dave', password: 'password123', email: 'dave@example.com', orgs: []});
  const DK = await login('dave');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, DK);
  const C = await call('POST', '/api/clients', {name: 'Nordwind GmbH', org_id: null, contacts: [{name: 'Erika Beispiel', is_default: 1}]});
  check(C.status === 201 && C.org_id == null, 'a private client');
  const Q = await call('POST', '/api/office/docs', {project_title: 'Imagefilm', client_id: C.id});
  check(Q.id > 0 && Q.number !== undefined, 'a draft quotation for it ' + JSON.stringify(Q).slice(0, 200));

  // ================= the client card: the item, the dialog with the tick box, Move, Undo
  let w = await boot({user: 'alice', hash: 'client/' + C.id}), d = w.document;
  const cm = await until(() => d.querySelector('#view [data-mscl="cmenu"]'));
  check(cm, 'the client card menu button');
  cm?.click();
  await until(() => items(d).length);
  const it = items(d).find(b => b.textContent.trim() === 'Move to another workspace…');
  check(it, 'the card menu offers the move ' + items(d).map(b => b.textContent.trim()).join(' | '));
  it?.click();
  const dlg = await until(() => d.querySelector('.smv-dlg'));
  check(dlg && /Nordwind/.test(dlg.querySelector('.smv-what')?.textContent || '') && dlg.querySelector('#smv-opt'), 'the dialog names the client and has the tick box');
  const yes = await until(() => { const b = d.querySelector('.smv-dlg [data-smv="yes"]'); return b && !b.disabled && b; });
  const notes = d.querySelector('.smv-dlg .smv-notes')?.textContent || '';
  check(yes && /1 client moves/.test(notes) && /1 draft moves/.test(notes), 'the dry run names the client and its draft, Move unlocked ' + notes);
  yes?.click();
  check(await until(async () => (await call('GET', '/api/clients/' + C.id)).org_id === ORG), 'the client moved into the organisation');
  await w.eval(`histStep('undo')`);
  check(await until(async () => (await call('GET', '/api/clients/' + C.id)).org_id == null), 'Undo: the client is private again');
  check(await until(async () => (await call('GET', '/api/office/docs/' + Q.id)).id === Q.id), 'Undo: the draft is back in the personal office');
  w.close();

  // ================= the quotation's menu: a draft alone
  w = await boot({user: 'alice', hash: 'office/offers/' + Q.id}); d = w.document;
  const more = await until(() => d.querySelector('#view [data-ofd="more"]'));
  check(more, 'the quotation menu button');
  more?.click();
  await until(() => items(d).length);
  check(items(d).some(b => b.textContent.trim() === 'Move to another workspace…'), 'the quotation menu offers the move ' + items(d).map(b => b.textContent.trim()).join(' | '));
  w.close();

  // ================= without an organisation: the item is not there
  const DC = await call('POST', '/api/clients', {name: 'Solo Kunde'}, DK);
  w = await boot({user: 'dave', hash: 'client/' + DC.id}); d = w.document;
  const dm = await until(() => d.querySelector('#view [data-mscl="cmenu"]'));
  dm?.click();
  await until(() => items(d).length);
  check(items(d).length && !items(d).some(b => /another workspace/.test(b.textContent)), 'a person without an organisation: no move item');
  w.close();

  check(errs.length === 0, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
