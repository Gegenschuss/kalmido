// 2.988.0 A UI test (#5651): the tab "Call sheets" of a project, used as a person would. Own container (start.sh). Invented names only.
// kalmido-suite: fresh
// - with Film & Video and the module Disposition the project's view switch has "Call sheets"; a click shows the page (it loads
//   callsheet.js on demand): the heading, the hint "No call sheets yet" and the button "New call sheet"
// - "New call sheet": a day, "Create" -> the call sheet dialog of that day opens (its heading names the project to who sees it; the shoot day's own title is "Shoot day", review F3); closed, the
//   tab shows the row: the day, "Shoot day 1", "No location yet" and a PDF button; a location saved in the dialog shows in the
//   row; a tap on the row opens the call sheet again with what was saved; back to "List" shows the tasks again
// - a read-only member of the organisation sees the row, but no "New call sheet"
// - without Film & Video the view switch has no "Call sheets"
// P2988AUI_NOSTART=1 = the server already runs.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2988AUI_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const FEAT = 'collab,comments,contacts,office,clients,workload,dispo,kanban';
const dstr = x => `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}`;
const txt = el => (el?.textContent || '').replace(/\s+/g, ' ').trim();

/** the project page of list lid as user, switched to "Call sheets" -> [window, document] */
async function tab(user, lid) {
  const w = await boot({user, hash: `l/${lid}`}), d = w.document;
  const t = await until(() => d.querySelector('#top [data-act="view-callsheets"]'));
  t?.click();
  await until(() => d.querySelector('#view .pcs .pcsbar') && !/Loading/.test(txt(d.querySelector('#view .pcs'))));
  return [w, d, t];
}

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const A = await login('alice');
  await call(A, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  const me = (await call(A, 'GET', '/api/state')).me;
  const org = await call(A, 'POST', '/api/admin/orgs', {name: 'Beispiel Studio', admin_id: me.id});
  const rita = await call(A, 'POST', '/api/users', {orgs: [{id: org.id, role: 'readonly'}], username: 'rita', display_name: 'Rita', password: 'password123', email: 'rita@example.com'});
  const R = await login('rita');
  for (const ck of [A, R]) await call(ck, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: `org:${org.id}`});
  const ind = await call(A, 'PUT', '/api/industry', {industries: ['film']});
  const L = await call(A, 'POST', '/api/lists', {name: 'Kinospot Winter', kind: 'project', org_id: org.id});
  await call(A, 'PUT', `/api/lists/${L.id}/members`, {user_id: rita.id, role: 'edit'});  // her read-only role in the organisation decides
  await call(A, 'POST', '/api/tasks', {title: 'Drehbuch fertig', list_id: L.id});
  check(org.id && rita.id && ind.status === 200 && L.id, 'setup: an organisation, rita read-only, Film & Video, a project ' + JSON.stringify(L).slice(0, 120));
  const t = new Date(), D = dstr(new Date(t.getFullYear(), t.getMonth(), t.getDate() + 5));

  // ================= the tab, empty
  let [w, d, tb] = await tab('alice', L.id);
  check(tb && /Call sheets/.test(tb.title || txt(tb)), 'the view switch has "Call sheets"');
  let pg = d.querySelector('#view .pcs');
  check(pg && /Call sheets/.test(txt(pg.querySelector('.pcsbar h3'))) && /No call sheets yet/.test(txt(pg)), 'the page: heading and "No call sheets yet" ' + txt(pg).slice(0, 160));
  check(w.eval("typeof cs_open === 'function' && typeof viewProjCs === 'function'"), 'callsheet.js was loaded on demand');
  check(!d.querySelector('#view .task, #view [data-tid]') || !/Drehbuch fertig/.test(txt(d.querySelector('#view'))), 'no task list under the tab');
  const nb = pg?.querySelector('[data-pcs="new"]');
  check(nb && /New call sheet/.test(txt(nb)), 'the button "New call sheet"');

  // ================= new call sheet: the day, Create -> the call sheet opens
  nb?.click();
  const nm = await until(() => d.querySelector('.modal #pcs-day') && d.querySelector('.modal #pcs-day').closest('.modal'));
  check(nm && /New call sheet/.test(txt(nm.querySelector('h3'))), 'the dialog "New call sheet" with a day');
  if (nm) nm.querySelector('#pcs-day').value = D;
  nm?.querySelector('[data-pcs="make"]')?.click();
  let md = await until(() => d.querySelector('.modal.csmd #cs-loc_name') && d.querySelector('.modal.csmd'));
  check(md && /Call sheet: Kinospot Winter/.test(txt(md.querySelector('h3'))) && !d.querySelector('.modal #pcs-day'), 'the call sheet of the new shoot day opened: ' + txt(md?.querySelector('h3')));
  check(md?.querySelector('#cs-day_no')?.value === '1', 'its shoot day number 1');
  md.querySelector('#cs-loc_name').value = 'Eisstadion Beispiel';
  md.querySelector('[data-cs="save"]')?.click();
  await until(async () => (await call(A, 'GET', `/api/team/dispo/callsheets?list=${L.id}`)).callsheets?.[0]?.location === 'Eisstadion Beispiel');
  md.querySelector('[data-cs="close"]')?.click();
  await until(() => !d.querySelector('.modal.csmd'));

  // ================= the row
  const row = await until(() => { const r = d.querySelector('#view .pcsrow'); return r && /Eisstadion Beispiel/.test(txt(r)) && r; }, 200);
  check(row && /1\. |Shoot day 1|1/.test(txt(row.querySelector('.pcsn'))) && txt(row.querySelector('.pcsd')).length > 3,
    'the row: the day and the shoot day number ' + txt(row));
  check(row && /Eisstadion Beispiel/.test(txt(row.querySelector('.pcsl'))), 'the row shows the location saved in the dialog');
  const pdf = row?.querySelector('a[data-pcs="pdf"]');
  check(pdf && /\/api\/team\/dispo\/callsheet\/[0-9a-f]+\/pdf\?org=\d+/.test(pdf.getAttribute('href') || ''), 'the row has the PDF button ' + pdf?.getAttribute('href'));
  check(!/No call sheets yet/.test(txt(d.querySelector('#view .pcs'))), 'the empty hint is gone');
  // a tap on the row opens the call sheet again with its content
  row?.querySelector('[data-pcs="open"]')?.click();
  md = await until(() => d.querySelector('.modal.csmd #cs-loc_name') && d.querySelector('.modal.csmd'));
  check(md?.querySelector('#cs-loc_name')?.value === 'Eisstadion Beispiel', 'a tap on the row: the call sheet with its location');
  md?.querySelector('[data-cs="close"]')?.click();
  await until(() => !d.querySelector('.modal.csmd'));
  // the disposition knows the shoot day
  const dp = await call(A, 'GET', `/api/team/dispo?start=${D}&days=1&org=${org.id}`);
  check((dp.bookings || []).some(b => b.kind === 'slot' && b.title === 'Shoot day'), 'the disposition has the shoot day (an open place)');
  // back to the list: the tasks again
  d.querySelector('#top [data-act="view-list"]')?.click();
  check(await until(() => /Drehbuch fertig/.test(txt(d.querySelector('#view'))) && !d.querySelector('#view .pcs')), 'back to "List": the tasks, no call sheets page');
  w.close();

  // ================= rita, read-only: the row, no "New call sheet"
  [w, d] = await tab('rita', L.id);
  check(/Eisstadion Beispiel/.test(txt(d.querySelector('#view .pcslist'))) && !d.querySelector('#view [data-pcs="new"]'), 'rita (read-only) sees the row, no "New call sheet"');
  w.close();

  // ================= without Film & Video: no tab
  await call(A, 'PUT', '/api/industry', {industries: []});
  w = await boot({user: 'alice', hash: `l/${L.id}`}); d = w.document;
  await until(() => d.querySelector('#top [data-act="view-list"]'));
  check(d.querySelector('#top [data-act="view-list"]') && !d.querySelector('#top [data-act="view-callsheets"]'), 'without Film & Video: no "Call sheets" in the view switch');
  w.close();

  console.log(`p2988_a_callsheets_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
