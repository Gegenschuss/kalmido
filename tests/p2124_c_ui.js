// 2.124.0 part C UI test (#2113, #2114), own container (start.sh): one table shared with a single person.
// The table menu offers "Share…" (who may change it through its workspace), the dialog adds a person with a role (ONE Undo
// step takes it back), the overview marks the table "Shared"; the recipient sees it in the group "Shared with me", read
// only, without Share / Delete; Mod+K finds the table by its title and opens it.
// P2124C_NOSTART=1 = the server already runs.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2124C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const items = d => [...d.querySelectorAll('#pop [role="menuitem"], .menu-list [role="menuitem"]')];
const FEAT = 'collab,comments,sheets';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com', orgs: [ORG]})).id;
  const BK = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, BK);
  const S = await call('POST', '/api/sheets', {title: 'Holiday budget', space: 'private'});
  check(S.status === 201, 'a private table');
  await call('POST', '/api/sheets', {title: 'Not for bob', space: 'private'});

  // ================= alice: the menu item, the dialog, add, Undo, add again
  let w = await boot({user: 'alice', hash: 'sheets/' + S.id}), d = w.document;
  await until(() => d.querySelector('#view [data-shv="menu"]'));
  d.querySelector('#view [data-shv="menu"]')?.click();
  await until(() => items(d).length);
  const it = items(d).find(b => b.textContent.trim() === 'Share…');
  check(it, 'the table menu offers Share… ' + items(d).map(b => b.textContent.trim()).join(' | '));
  it?.click();
  const dlg = await until(() => d.querySelector('.shsdlg'));
  check(dlg && /Holiday budget/.test(dlg.querySelector('h3')?.textContent || ''), 'the dialog names the table');
  check(/Not shared yet/.test(d.querySelector('#shs-list')?.textContent || ''), 'not shared yet');
  const sel = d.querySelector('#shs-t');
  check(sel && [...sel.options].some(o => +o.value === BOB), 'bob is offered');
  if (sel) sel.value = String(BOB);
  d.querySelector('[data-shs="add"]')?.click();
  check(await until(() => /Bob/.test(d.querySelector('#shs-list')?.textContent || '')), 'bob is in the list of shares');
  check(await until(async () => (await call('GET', `/api/sheets/${S.id}/shares`)).shares?.length === 1), 'the server holds the share (read)');
  await w.eval(`histStep('undo')`);
  check(await until(async () => (await call('GET', `/api/sheets/${S.id}/shares`)).shares?.length === 0), 'Undo: the share is gone (one step)');
  await w.eval(`histStep('redo')`);
  check(await until(async () => (await call('GET', `/api/sheets/${S.id}/shares`)).shares?.[0]?.role === 'read'), 'Redo: shared again');
  d.querySelector('.shsdlg [data-m="close"]')?.click();
  w.location.hash = 'sheets'; await sleep(300);
  check(await until(() => d.querySelector(`#view .shvcard[data-id="${S.id}"] .shs-mark`)), 'the overview marks the table "Shared"');
  w.close();

  // ================= bob: "Shared with me", read only, no Share / Delete, Mod+K
  w = await boot({user: 'bob', hash: 'sheets'}); d = w.document;
  const grp = await until(() => [...d.querySelectorAll('#view .shvgrp')].find(g => /Shared with me/.test(g.querySelector('h3')?.textContent || '')));
  check(grp && grp.querySelector(`.shvcard[data-id="${S.id}"]`), 'bob sees the table in "Shared with me"');
  check(!/Not for bob/.test(d.querySelector('#view')?.textContent || ''), 'not alice\'s other table');
  grp?.querySelector(`[data-shv="cmenu"]`)?.click();
  await until(() => items(d).length);
  const cl = items(d).map(b => b.textContent.trim());
  check(cl.includes('Open') && !cl.includes('Delete') && !cl.includes('Rename…'), 'the card menu of a read share: open only ' + cl.join(' | '));
  w.eval('closePop()');
  w.location.hash = 'sheets/' + S.id;
  check(await until(() => /Read only/.test(d.querySelector('#view .shvro')?.textContent || '')), 'bob reads it, read only');
  d.querySelector('#view [data-shv="menu"]')?.click();
  await until(() => items(d).length);
  const ml = items(d).map(b => b.textContent.trim());
  check(!ml.includes('Share…') && !ml.includes('Delete'), 'no Share / Delete for the recipient ' + ml.join(' | '));
  w.eval('closePop()');
  w.location.hash = 'today'; await sleep(200);
  w.eval('openPalette()');
  const hit = await until(() => w.eval(`palAll().find(x => x.id === 'sh:${S.id}')`));
  check(hit && hit.label === 'Holiday budget' && hit.icon === 'sheet', 'Mod+K: the table by its title ' + JSON.stringify(hit || {}).slice(0, 200));
  const inp = d.querySelector('.palette .pqin');
  if (inp) { inp.value = 'holiday'; inp.dispatchEvent(new w.Event('input', {bubbles: true})); }
  await sleep(200);
  const row = await until(() => [...d.querySelectorAll('.palette #plist [role="option"], .palette #plist button')].find(b => /Holiday budget/.test(b.textContent)));
  check(row, 'Mod+K: the hit is listed when typing');
  row?.click();
  check(await until(() => w.location.hash === '#sheets/' + S.id), 'Mod+K: the hit opens the table ' + w.location.hash);
  w.close();

  check(errs.length === 0, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
