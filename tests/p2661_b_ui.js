// 2.66.1 UI tests, part B (#1945): the workspace switch reloads every open view with a workspace link. jsdom, invented data.
// The guard: WS_VIEWS below is the ONE list of the client files that read the shown workspace (wsCur, dc_ws, the setting,
// the helpers that filter by it, p61b_wsOn) and of the server files that pick an area from the saved setting. A new file with
// such a link and no entry here makes this suite red (like tenant_coverage): add it with how it follows the switch and,
// for a view that keeps data, a check below. For each checked view: data in the organisation and in Private (titles that
// tell them apart), the view is opened, wsSet() switches WITHOUT opening it again, the new workspace's data shows and the
// old one's is gone -- both ways (Private -> organisation -> Private).
const {execFileSync} = require('child_process');
const fs = require('fs');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const pad = n => String(n).padStart(2, '0');
const dstr = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

// ---- the central list: file -> how it follows the workspace switch
// 'check:<name>' = keeps data of one workspace, checked below; 'draw' = filters what is in memory while drawing (render()
// after wsSet is enough); 'helper' = no view of its own (decides, names or colours only)
const WS_VIEWS = {
  'static/js/docs.js': 'check:docs',          // documents: list, "To review", filters, the open document (viewDocs compares DC.ws)
  'static/js/ablage.js': 'check:files',       // files: the space follows (ab_curSpace -> AB.key)
  'static/js/wiki.js': 'check:wiki',          // wiki: the space's pages; an open page of the old space closes (p61b_wsOn)
  'static/js/office.js': 'check:office',      // office: pb_wsChanged (its tabs compare OFC.info.org_id)
  'static/js/clientpage.js': 'check:office',  // clients: MSC.ws, part of the office check (same area)
  'static/js/calendar.js': 'check:calendar',  // appointments: own calendars filtered by wsObjIn while drawing
                                              // 2.161.0: + the hook 'calteam' (the colleagues' absences, see abscal.py)
  'static/js/calevents.js': 'draw',           // the calendars one may write into (dialogs)
  'static/js/contacts.js': 'check:contacts',  // contacts: address books filtered by wsObjIn while drawing
  'static/js/render.js': 'draw',              // lists, tasks, News (checked in p2280_ui)
  'static/js/sidebar.js': 'draw',             // the sidebar's lists and folders (p2280_ui)
  'static/js/sbnav.js': 'draw',
  'static/js/core.js': 'draw',                // also: the new state reloads the workload tabs (absences, disposition)
  'static/js/chat.js': 'draw',                // team chats of the workspace
  'static/js/collab.js': 'draw',              // 2.145.0 (#2444): the news list's hint rows for the OTHER workspaces (newsElseHtml), drawn with the list
  'static/js/agents.js': 'draw',              // agents of the workspace (p2280_ui)
  'static/js/bookmarks.js': 'draw',           // 2.97.0 (#1950): bookmarks load the shown workspace (bm_sp) unless one is picked in the view
  'static/js/agentchat.js': 'helper',         // the default workspace of a new agent
  'static/js/polls.js': 'helper',             // 2.98.1: the default workspace of a new poll (the dialog shows all polls, with their workspace)
  'static/js/palette.js': 'draw',
  'static/js/areas.js': 'draw',               // 2.87.0: private areas hidden in an organisation's view (o3a_hid while drawing, #1845)
  'static/js/tagsview.js': 'draw',
  'static/js/sheets.js': 'draw',              // 2.89.1 (#1916): the tables overview filtered by the workspace while drawing
  'static/js/favtiles.js': 'draw',
  'static/js/dupprop.js': 'helper',
  'static/js/newsletter.js': 'helper',        // a dialog with its own workspace choice
  'static/js/workspace.js': 'helper',         // the switch itself
  'static/js/wscolor.js': 'helper',
  // 2.87.9: files that read the shown workspace since 2.85 / 2.87.9
  'static/js/areas.js': 'draw',               // private-only modules hidden in an organisation's view, the office menu per workspace (#1917)
  'static/js/paperless.js': 'draw',           // Settings > Integrations: the Paperless section takes the shown workspace when drawn (#1936)
  'static/js/settings.js': 'helper',          // the task import's default target (#1940, confirmed in the dialog)
  'static/js/listadmin.js': 'draw',           // 2.102.0 A (#1988): the deleted lists of the trash filtered by wsObjIn while drawing
  'static/js/dashboard.js': 'draw',           // 2.144.0 C (#2418): the start page names overdue tasks of other workspaces (wsCur / wsHidden while drawing)
  'static/js/collab.js': 'draw',              // 2.145.0 A (#2444): News names unread items of the other workspaces (wsCur while drawing)
  'static/js/devlink.js': 'helper',           // 2.140.1 (#2136): "open the equipment" switches to the office's workspace first (no view)
  'kalmido/hub/absence.py': 'check:absences', // abs_org: the area of the saved setting; absences and disposition load again
                                              // with the state that follows the saved setting (core.js)
  'kalmido/office/model.py': 'check:office',  // office_org: the saved setting
  'kalmido/hub/abscal.py': 'check:calteam',   // 2.155.0 B (#2076): the colleagues' absences in the calendar for the saved
                                              // workspace (abc_team_orgs); calendar.js reloads the range once the server knows it
  'static/js/sideviews.js': 'draw',           // #2186 (bundle C): the sidebar views' editor lists the lists of the shown workspace (inWs while drawing)
  'kalmido/personal/timesheet.py': 'helper',  // 2.125.0 (#2119): tsl_org - which organisation a closed month goes to (no view)
  'kalmido/accounts/orgs.py': 'helper',       // 2.148.1 (#2480): ws_chosen_org - the default workspace of a new list (no view)
};
const ROOT = path.join(__dirname, '..');
const CLIENT_RE = /\bwsCur\(|\bdc_ws\(|settings\.workspace|\bp61b_wsOn\(|\bwsObjIn\(|\binWs\(|\bwsHidden\(|\bwsAgentIn\(/;
const SERVER_RE = /get\("workspace"\)/;
function scan() {
  const out = [];
  for (const f of fs.readdirSync(path.join(ROOT, 'static/js'))) if (f.endsWith('.js') && CLIENT_RE.test(fs.readFileSync(path.join(ROOT, 'static/js', f), 'utf8'))) out.push('static/js/' + f);
  const walk = d => { for (const e of fs.readdirSync(path.join(ROOT, d), {withFileTypes: true})) {
    const p = d + '/' + e.name;
    if (e.isDirectory()) walk(p); else if (e.name.endsWith('.py') && SERVER_RE.test(fs.readFileSync(path.join(ROOT, p), 'utf8'))) out.push(p);
  } };
  walk('kalmido');
  return out.sort();
}

(async () => {
  // ================= the guard: every file with a workspace link has an entry
  const found = scan();
  const missing = found.filter(f => !(f in WS_VIEWS));
  check(found.length > 10 && !missing.length, 'guard: views with a workspace link without an entry in WS_VIEWS (add them with a check): ' + missing.join(', '));
  const stale = Object.keys(WS_VIEWS).filter(f => !found.includes(f));
  check(!stale.length, 'guard: entries whose file has no workspace link any more (remove them): ' + stale.join(', '));
  const CHECKED = new Set();

  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  const FEAT = 'cal,comments,collab,files,docs,wiki,office,clients,workload,dispo,events,contacts';
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'private'});
  const me = (await call('GET', '/api/state')).me;
  const A = (await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id})).id;
  const Bo = (await call('POST', '/api/admin/orgs', {name: 'Bravo', admin_id: me.id})).id;
  check(A > 0 && Bo > 0, 'organisations Alpha and Bravo');
  const WA = 'org:' + A, WB = 'org:' + Bo;

  // data in both workspaces
  const up = async (name, text, ws) => {
    const fd = new FormData(); fd.append('files', new Blob([text], {type: 'text/plain'}), name); fd.append('ws', ws);
    const j = await (await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd})).json().catch(() => ({}));
    return (j.ids || [])[0];
  };
  const DP = await up('private-letter.txt', 'Letter one, private', 'private');
  const DA1 = await up('alpha-letter.txt', 'Letter two, Alpha', WA), DA2 = await up('alpha-bill.txt', 'Letter three, Alpha', WA);
  check(DP && DA1 && DA2, 'three documents ' + [DP, DA1, DA2]);
  for (const id of [DP, DA1, DA2]) await call('POST', `/api/docs/${id}/review`, {done: false});  // "To review": Private 1, Alpha 2
  const rv = async ws => (await call('GET', `/api/docs?ws=${ws}`)).review;
  check(await rv('private') === 1 && await rv(WA) === 2, 'to review on the server: Private 1, Alpha 2');
  await call('POST', '/api/files/folders', {name: 'Private folder', space: 'private'});
  await call('POST', '/api/files/folders', {name: 'Alpha folder', space: WA});
  const WP = (await call('POST', '/api/wiki/pages', {space: 'private', path: 'Private page', body: 'mine'})).id;
  await call('POST', '/api/wiki/pages', {space: WA, path: 'Alpha page', body: 'ours'});
  const t = dstr(new Date());
  const CP = await call('POST', '/api/evcals', {name: 'Home', org_id: null}), CA = await call('POST', '/api/evcals', {name: 'Alpha calendar', org_id: A});
  await call('POST', '/api/events', {title: 'Private dentist', cal_id: CP.id, start: `${t}T15:00`, end: `${t}T16:00`});
  await call('POST', '/api/events', {title: 'Alpha standup', cal_id: CA.id, start: `${t}T09:00`, end: `${t}T09:15`});
  const BP = await call('POST', '/api/books', {name: 'Home book', org_id: null}), BA = await call('POST', '/api/books', {name: 'Alpha book', org_id: A});
  await call('POST', '/api/contacts', {fn: 'Private Plumber', book_id: BP.id});
  await call('POST', '/api/contacts', {fn: 'Alpha Supplier', book_id: BA.id});
  const in2 = dstr(new Date(Date.now() + 2 * 864e5));
  await call('POST', '/api/team/absences', {kind: 'vacation', start_date: in2, end_date: in2, note: 'Away for Alpha', org: A});
  await call('POST', '/api/team/absences', {kind: 'vacation', start_date: in2, end_date: in2, note: 'Away for Bravo', org: Bo});
  // 2.161.0 (#2076): a colleague in each organisation, an absence each that alice (their admin) enters; alice shows the team's
  const mate = async (name, oid) => {
    const u = await call('POST', '/api/users', {username: name, display_name: name[0].toUpperCase() + name.slice(1), password: 'password123', email: name + '@example.com'});
    const m = await call('PUT', `/api/orgs/${oid}/members`, {email: name + '@example.com'});  // an invitation, accepted below
    const ck = await login(name); const j = await call('POST', `/api/orgs/${oid}/join`, null, ck);
    const ab = await call('POST', '/api/team/absences', {user_id: u.id, kind: 'vacation', start_date: t, end_date: t, org: oid});
    return u.id > 0 && ab.http === 201 ? '' : `${name}: user ${u.http} member ${m.http} join ${j.http} absence ${ab.http} ${JSON.stringify(ab).slice(0, 160)}`;
  };
  const mt = (await mate('cleo', A)) + (await mate('dirk', Bo));
  check(!mt, 'a colleague with an absence in Alpha and one in Bravo ' + mt);
  await call('PATCH', '/api/settings', {cal_abs_team: '1'});

  const w = await boot({user: 'alice', hash: 'docs'}); const d = w.document;
  const view = () => d.querySelector('#view')?.textContent || '';
  const sw = async ws => { w.eval(`wsSet(${JSON.stringify(ws)})`); await sleep(50); };
  const has = (yes, no) => () => { const v = view(); return yes.every(x => v.includes(x)) && no.every(x => !v.includes(x)); };

  // ================= documents
  check(await until(has(['private-letter'], ['alpha-letter']), 60), 'docs: Private shows its document');
  w.eval("DC.f.tag = '999'; DC.more = true");  // a filter of the old workspace
  await sleep(300);
  await sw(WA);
  check(await until(has(['alpha-letter', 'alpha-bill'], ['private-letter']), 60), 'docs: Private -> Alpha without opening again shows Alpha\'s documents: ' + view().slice(0, 200));
  check(w.eval('DC.f.tag') === '', 'docs: the filter of the old workspace is reset');
  check(await until(() => /\b2\b/.test(d.querySelector('#view [data-dc="review"] .dc-count')?.textContent || '')), 'docs: "To review" counts Alpha\'s (2)');
  w.eval(`dc_open(${DA1})`);
  check(await until(() => d.querySelector('.dc-md')), 'docs: a document of Alpha is open');
  await sw('private');
  check(await until(() => !d.querySelector('.dc-md'), 30), 'docs: switching to Private closes the open document of Alpha');
  check(await until(has(['private-letter'], ['alpha-letter', 'alpha-bill']), 60), 'docs: Alpha -> Private shows Private\'s documents again: ' + view().slice(0, 200));
  check(await until(() => /\b1\b/.test(d.querySelector('#view [data-dc="review"] .dc-count')?.textContent || '')), 'docs: "To review" counts Private\'s (1)');
  // a late answer for the old workspace is dropped: start a load, switch before it returns
  w.eval('dc_load()'); await sw(WA);
  check(await until(has(['alpha-letter'], ['private-letter']), 60) && w.eval('DC.atWs') === WA, 'docs: a load started in Private and answered after the switch does not show Private\'s list');
  await sw('private'); await until(has(['private-letter'], ['alpha-letter']), 60);
  CHECKED.add('docs');

  // ================= files
  w.eval(`go('ablage')`);
  check(await until(has(['Private folder'], ['Alpha folder']), 60), 'files: Private shows its folder: ' + view().slice(0, 200));
  await sw(WA);
  check(await until(has(['Alpha folder'], ['Private folder']), 60), 'files: Private -> Alpha shows Alpha\'s folder');
  await sw('private');
  check(await until(has(['Private folder'], ['Alpha folder']), 60), 'files: Alpha -> Private shows Private\'s folder');
  CHECKED.add('files');

  // ================= wiki (an open page of Private, then the switch)
  w.eval(`go('wiki/${WP}')`);
  check(await until(has(['Private page'], ['Alpha page']), 60), 'wiki: Private\'s page and tree: ' + view().slice(0, 200));
  await sw(WA);
  check(await until(has(['Alpha page'], ['Private page']), 60), 'wiki: Private -> Alpha leaves the page of Private, Alpha\'s pages show: ' + view().slice(0, 200));
  await sw('private');
  check(await until(has(['Private page'], ['Alpha page']), 60), 'wiki: Alpha -> Private shows Private\'s pages');
  CHECKED.add('wiki');

  // ================= appointments
  w.eval("LS.set('calMode', 'month')");
  w.eval(`go('cal')`);
  check(await until(has(['Private dentist'], ['Alpha standup']), 60), 'calendar: Private shows its appointment: ' + view().slice(0, 200));
  await sw(WA);
  check(await until(has(['Alpha standup'], ['Private dentist']), 60), 'calendar: Private -> Alpha shows Alpha\'s appointment');
  await sw('private');
  check(await until(has(['Private dentist'], ['Alpha standup']), 60), 'calendar: Alpha -> Private shows Private\'s appointment');
  CHECKED.add('calendar');
  // 2.161.0 (#2076): the colleagues' absences follow the switch without opening the calendar again
  await sw(WA);
  check(await until(has(['Cleo: away'], ['Dirk: away']), 60), 'calendar: -> Alpha shows the absence of Alpha\'s colleague: ' + view().slice(0, 300));
  await sw(WB);
  check(await until(has(['Dirk: away'], ['Cleo: away']), 60), 'calendar: Alpha -> Bravo shows the absence of Bravo\'s colleague');
  await sw('private');
  check(await until(has([], ['Cleo: away', 'Dirk: away']), 60), 'calendar: Bravo -> Private shows no colleague\'s absence');
  CHECKED.add('calteam');

  // ================= contacts
  w.eval(`go('contacts')`);
  check(await until(has(['Private Plumber'], ['Alpha Supplier']), 60), 'contacts: Private shows its contact: ' + view().slice(0, 200));
  await sw(WA);
  check(await until(has(['Alpha Supplier'], ['Private Plumber']), 60), 'contacts: Private -> Alpha shows Alpha\'s contact');
  await sw('private');
  check(await until(has(['Private Plumber'], ['Alpha Supplier']), 60), 'contacts: Alpha -> Private shows Private\'s contact');
  CHECKED.add('contacts');

  // ================= office (+ clients: the same area)
  w.eval(`go('office/offers')`);
  check(await until(() => w.eval('OFC.info && OFC.info.personal') === 1, 60), 'office: Private = the personal office');
  await sw(WA);
  check(await until(() => w.eval('OFC.info && OFC.info.org_id') === A, 60), 'office: Private -> Alpha = Alpha\'s office');
  await sw('private');
  check(await until(() => w.eval('OFC.info && OFC.info.personal') === 1, 60), 'office: Alpha -> Private = the personal office');
  CHECKED.add('office');

  // ================= absences + disposition (the area of the saved workspace; Private = the first organisation)
  await sw(WA);
  w.eval(`go('workload')`);
  await until(() => d.querySelector('#view .ab2tabs [data-v="abs"]'), 60);
  d.querySelector('#view .ab2tabs [data-v="abs"]').click();
  w.eval(`AB2.start = ${JSON.stringify(in2.slice(0, 7) + '-01')}; ab2_reload()`);
  check(await until(has(['Away for Alpha'], ['Away for Bravo']), 60), 'absences: Alpha shows its absence: ' + view().slice(0, 200));
  await sw(WB);
  check(await until(has(['Away for Bravo'], ['Away for Alpha']), 60) && w.eval('AB2.data && AB2.data.org_id') === Bo, 'absences: Alpha -> Bravo shows Bravo\'s absence without opening again');
  await sw(WA);
  check(await until(has(['Away for Alpha'], ['Away for Bravo']), 60) && w.eval('AB2.data && AB2.data.org_id') === A, 'absences: Bravo -> Alpha shows Alpha\'s absence');
  CHECKED.add('absences');
  d.querySelector('#view .ab2tabs [data-v="dispo"]')?.click();
  check(await until(() => w.eval('DPV.data && DPV.data.org_id') === A, 60), 'dispo: Alpha\'s area');
  await sw(WB);
  check(await until(() => w.eval('DPV.data && DPV.data.org_id') === Bo, 60), 'dispo: Alpha -> Bravo loads Bravo\'s area without opening again');
  await sw(WA);
  check(await until(() => w.eval('DPV.data && DPV.data.org_id') === A, 60), 'dispo: Bravo -> Alpha loads Alpha\'s area');
  CHECKED.add('absences');  // the disposition: the same area (abs_org)

  // ================= the guard, part 2: every listed check ran, every switch hook of the client is listed
  const want = [...new Set(Object.values(WS_VIEWS).filter(v => v.startsWith('check:')).map(v => v.slice(6)))];
  const notRun = want.filter(x => !CHECKED.has(x));
  check(!notRun.length, 'guard: listed views without a check in this suite: ' + notRun.join(', '));
  const hooks = JSON.parse(w.eval('JSON.stringify(Object.keys(p61b_WS))'));
  check(hooks.every(h => want.includes(h)), 'guard: switch hooks (p61b_wsOn) not in WS_VIEWS: ' + hooks.filter(h => !want.includes(h)).join(', '));
  w.close();

  console.log(`\n${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
