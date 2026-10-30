// 2.96.0 part B UI test (#1941), own container (start.sh): a knowledge page / its folder and a table to the other workspace.
// The page menu offers "Move to another workspace…" and "Move folder to another workspace…" (only with an organisation:
// a person without one never sees them), the shared dialog shows the dry run, "Move" moves, the page shows its last move
// and Undo brings it back to the old place (ONE step). Tables: the item in the table menu, the same dialog, Undo.
// P296B_NOSTART=1 = the server already runs.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P296B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const items = d => [...d.querySelectorAll('#pop [role="menuitem"], .menu-list [role="menuitem"]')];

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'collab,comments,sheets,wiki'});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id, SP = 'org:' + ORG;
  await call('POST', '/api/users', {username: 'dave', display_name: 'Dave', password: 'password123', email: 'dave@example.com', orgs: []});
  const DK = await login('dave');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'collab,comments,sheets,wiki'}, DK);
  const P = await call('POST', '/api/wiki/pages', {space: 'private', path: 'Plan/Idea', body: 'An idea'});
  check(P.status === 201, 'a private page in a folder');

  // ================= the page menu: both items, the dialog, Move, the history line, Undo
  let w = await boot({user: 'alice', hash: 'wiki/' + P.id, ls: {'tasks.wkSpace': JSON.stringify('private')}}), d = w.document;
  const pm = await until(() => d.querySelector('#view [data-wk="pmenu"]'));
  check(pm, 'the page menu button');
  pm?.click();
  await until(() => items(d).length);
  const labels = items(d).map(b => b.textContent.trim());
  check(labels.includes('Move to another workspace…') && labels.includes('Move folder to another workspace…'), 'the page menu offers both moves ' + labels.join(' | '));
  items(d).find(b => b.textContent.trim() === 'Move folder to another workspace…')?.click();
  const dlg = await until(() => d.querySelector('.smv-dlg'));
  check(dlg && /Plan/.test(dlg.querySelector('.smv-what')?.textContent || ''), 'the dialog names the folder');
  const yes = await until(() => { const b = d.querySelector('.smv-dlg [data-smv="yes"]'); return b && !b.disabled && b; });
  check(yes && /1 page moves/.test(d.querySelector('.smv-dlg .smv-notes')?.textContent || ''), 'the dry run: 1 page moves, Move unlocked ' + (d.querySelector('.smv-dlg .smv-notes')?.textContent || ''));
  yes?.click();
  const moved = await until(async () => { const g = await call('GET', '/api/wiki/pages/' + P.id); return g.space === SP && g; });
  check(moved && moved.path === 'Plan/Idea', 'the folder moved into the organisation ' + JSON.stringify(moved).slice(0, 200));
  w.location.hash = 'wiki/' + P.id; w.eval('WK.pg = null; renderView()');
  check(await until(() => /Moved out of/.test(d.querySelector('#view .wksmv')?.textContent || '')), 'the page shows its last move');  // 2.97.0 (#2051): "Moved out of <name>"
  await w.eval(`histStep('undo')`);
  const back = await until(async () => { const g = await call('GET', '/api/wiki/pages/' + P.id); return g.space === 'private' && g; });
  check(back && back.path === 'Plan/Idea', 'Undo: back in the private space at the old path ' + JSON.stringify(back).slice(0, 200));
  w.close();

  // ================= tables: the item, the dialog, Undo
  const S = await call('POST', '/api/sheets', {title: 'Budget', space: 'private'});
  w = await boot({user: 'alice', hash: 'sheets/' + S.id}); d = w.document;
  await until(() => d.querySelector('#view [data-shv="menu"]'));
  d.querySelector('#view [data-shv="menu"]')?.click();
  await until(() => items(d).length);
  const it = items(d).find(b => b.textContent.trim() === 'Move to another workspace…');
  check(it, 'the table menu offers the move ' + items(d).map(b => b.textContent.trim()).join(' | '));
  it?.click();
  const ty = await until(() => { const b = d.querySelector('.smv-dlg [data-smv="yes"]'); return b && !b.disabled && b; });
  check(ty && !d.querySelector('.smv-dlg #smv-place'), 'the table dialog: no place to pick, Move unlocked');
  ty?.click();
  check(await until(async () => (await call('GET', '/api/sheets/' + S.id)).space === SP), 'the table moved into the organisation');
  await w.eval(`histStep('undo')`);
  check(await until(async () => (await call('GET', '/api/sheets/' + S.id)).space === 'private'), 'Undo: the table is private again');
  w.close();

  // ================= without an organisation: the items are not there
  const DP = await call('POST', '/api/wiki/pages', {space: 'private', path: 'Notes/Mine', body: 'x'}, DK);
  w = await boot({user: 'dave', hash: 'wiki/' + DP.id}); d = w.document;
  const dm = await until(() => d.querySelector('#view [data-wk="pmenu"]'));
  dm?.click();
  await until(() => items(d).length);
  check(items(d).length && !items(d).some(b => /another workspace/.test(b.textContent)), 'a person without an organisation: no move items');
  check(w.eval(`typeof sh_smvItems !== 'function' || sh_smvItems({id: 1, space: 'private'}).length === 0`), 'tables: no move item either');
  w.close();

  check(errs.length === 0, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
