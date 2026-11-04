// 2.124.0 part E UI test (#2116), own container (start.sh): several sheets in one table.
// A table with one sheet shows only a quiet "+" under the grid (the view as before); "+" adds a sheet and opens it, the bar
// then shows both sheets (the open one marked), a tap on the other sheet opens it, a tap on the open one gives its menu
// (rename, duplicate, move, delete; the first sheet has no delete), Undo takes a new sheet back in ONE step, the
// overview names the number of sheets; a reader sees the bar without "+" and without the menu.
// P2124E_NOSTART=1 = the server already runs.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2124E_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
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
  const S = await call('POST', '/api/sheets', {title: 'Shoot plan', space: 'private'});
  check(S.status === 201, 'a private table');

  // ================= one sheet: only "+"
  let w = await boot({user: 'alice', hash: 'sheets/' + S.id}), d = w.document;
  await until(() => d.querySelector('#view .shvgrid'));
  const bar = await until(() => d.querySelector('#view .shbbar'));
  check(bar && bar.classList.contains('one') && !bar.querySelector('.shbtab') && bar.querySelector('[data-shb="add"]'), 'one sheet: only the "+" ' + (bar?.outerHTML || '').slice(0, 200));
  // ================= "+": a new sheet, opened
  d.querySelector('#view [data-shb="add"]')?.click();
  const t2 = await until(async () => { const x = await call('GET', `/api/sheets/${S.id}/tabs`); return x.tabs?.length === 2 && x.tabs[1].id; });
  check(t2, 'the "+" added a sheet');
  check(await until(() => w.location.hash === '#sheets/' + t2), 'the new sheet is open ' + w.location.hash);
  check(await until(() => d.querySelectorAll('#view .shbtab').length === 2), 'the bar shows both sheets');
  check(await until(() => d.querySelector('#view .shbtab.on')?.textContent.trim() === 'Sheet 2'), 'the open sheet is marked ' + d.querySelector('#view .shbtab.on')?.textContent);
  check(/Shoot plan/.test(d.querySelector('#view .shvtitle')?.textContent || ''), 'the title is the table\'s');
  // the menu of the open sheet
  d.querySelector('#view .shbtab.on')?.click();
  await until(() => items(d).length);
  const ml = items(d).map(b => b.textContent.trim());
  check(ml.includes('Rename…') && ml.includes('Duplicate') && ml.includes('Move left') && ml.includes('Delete sheet'), 'the sheet menu ' + ml.join(' | '));
  w.eval('closePop()');
  // another sheet: a tap opens it
  [...d.querySelectorAll('#view .shbtab')].find(b => !b.classList.contains('on'))?.click();
  check(await until(() => w.location.hash === '#sheets/' + S.id), 'a tap opens the first sheet ' + w.location.hash);
  await until(() => d.querySelector('#view .shbtab.on')?.textContent.trim() === 'Sheet 1');
  d.querySelector('#view .shbtab.on')?.click();
  await until(() => items(d).length);
  const m1 = items(d).map(b => b.textContent.trim());
  check(!m1.includes('Delete sheet') && m1.includes('Move right'), 'the first sheet: no delete ' + m1.join(' | '));
  w.eval('closePop()');
  // Undo of the new sheet: one step
  // 2.517.0 (#3714): Undo waits for the step of the new sheet (was a fixed 300 ms pause)
  let h0 = await w.eval('HIST.undo.length');
  d.querySelector('#view [data-shb="add"]')?.click();
  check(await until(async () => (await call('GET', `/api/sheets/${S.id}/tabs`)).tabs?.length === 3), 'a third sheet');
  check(await until(() => w.eval('HIST.undo.length') > h0), 'the new sheet is an Undo step');
  await w.eval(`histStep('undo')`);
  check(await until(async () => (await call('GET', `/api/sheets/${S.id}/tabs`)).tabs?.length === 2), 'Undo: the third sheet is gone (one step)');
  check(await until(() => d.querySelectorAll('#view .shbtab').length === 2), 'the bar shows two sheets again');
  // 2.517.0 (#3714): the flake under load - Undo came while the new sheet still loaded; the view stayed on the deleted sheet.
  // Its load is held on purpose until the Undo is through.
  check(await until(() => w.location.hash === '#sheets/' + S.id && d.querySelector('#view .shbtab.on')?.textContent.trim() === 'Sheet 1'), 'Undo opens the first sheet again ' + w.location.hash);
  await w.eval(`window.__rf1 = rawFetch; window.__held = []; window.__hold = true; rawFetch = (m, u, b) => (window.__hold && m === 'GET' && /^[/]api[/]sheets[/][0-9]+$/.test(u) && u !== '/api/sheets/${S.id}') ? new Promise(r => window.__held.push(r)).then(() => __rf1(m, u, b)) : __rf1(m, u, b)`);
  h0 = await w.eval('HIST.undo.length');
  d.querySelector('#view [data-shb="add"]')?.click();
  const t4 = await until(async () => { const x = await call('GET', `/api/sheets/${S.id}/tabs`); return x.tabs?.length === 3 && x.tabs.find(t => t.id !== S.id && t.id !== t2)?.id; });
  check(t4 && await until(() => w.location.hash === '#sheets/' + t4 && w.eval('window.__held.length') > 0 && w.eval('HIST.undo.length') > h0), '#3714: the new sheet is open and its load is held');
  await w.eval(`histStep('undo')`);
  check(await until(async () => (await call('GET', `/api/sheets/${S.id}/tabs`)).tabs?.length === 2), '#3714: Undo while loading: the sheet is gone');
  await w.eval(`window.__hold = false; window.__held.splice(0).forEach(r => r())`);
  check(await until(() => w.location.hash === '#sheets/' + S.id && d.querySelectorAll('#view .shbtab').length === 2 && d.querySelector('#view .shbtab.on')?.textContent.trim() === 'Sheet 1'), '#3714: Undo while loading goes back to the first sheet with two sheets ' + w.location.hash);
  await w.eval(`rawFetch = __rf1`);
  // the overview
  w.location.hash = 'sheets'; await sleep(300);
  check(await until(() => /2 sheets/.test(d.querySelector(`#view .shvcard[data-id="${S.id}"]`)?.textContent || '')), 'the overview: 2 sheets');
  check(!d.querySelector(`#view .shvcard[data-id="${t2}"]`), 'the further sheet is no card of its own');
  w.close();

  // ================= a reader: the bar without "+" and menu
  await call('POST', `/api/sheets/${S.id}/shares`, {user_id: BOB, role: 'read'});
  w = await boot({user: 'bob', hash: 'sheets/' + t2}); d = w.document;
  check(await until(() => d.querySelectorAll('#view .shbtab').length === 2), 'bob sees both sheets');
  check(!d.querySelector('#view [data-shb="add"]'), 'a reader: no "+"');
  d.querySelector('#view .shbtab.on')?.click();
  await sleep(200);
  check(!items(d).length, 'a reader: no sheet menu');
  w.close();

  check(errs.length === 0, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
