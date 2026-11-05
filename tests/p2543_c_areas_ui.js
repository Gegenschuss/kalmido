// 2.543.0 UI tests of part B (#4606): Team (Workload, Absences, Disposition) and the office under "All workspaces" show the
// kalmido-suite: fresh
// overview of the areas (areas.js spo_html, like Knowledge / the file store #4575) instead of a picker or silently one area.
// Own container (start.sh), jsdom, invented data only. freelancer-matrix: office, workload
// - Team under "All" with two organisations: the overview (no picker); a tap opens #workload/s/org:<id> with that area's
//   data, the three tabs keep the area, the path "All workspaces / <name>" leads back to the overview
// - the office under "All" (Private + two organisations): the overview; a tap switches the workspace to that area and opens
//   its office on the same page, "All workspaces /" in its head switches back to the overview
// - a workspace chosen above: as before (no overview, its area); a person without an organisation: no overview anywhere
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const FEAT = 'cal,comments,collab,office,clients,workload,dispo';
const rows = d => [...d.querySelectorAll('#view .spov [data-spov]')].map(a => a.dataset.spov).join();

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call('GET', '/api/state')).me;
  const A = (await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id})).id;
  const Bo = (await call('POST', '/api/admin/orgs', {name: 'Bravo', admin_id: me.id})).id;
  check(A > 0 && Bo > 0, 'organisations Alpha and Bravo');
  const WA = 'org:' + A, WB = 'org:' + Bo;
  await call('PATCH', '/api/settings', {workspace: 'all'});
  const fu = await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fu.http < 300, 'a person without an organisation ' + fu.http);

  // ================= Team under "All"
  let w = await boot({hash: 'workload'}); let d = w.document;
  check(await until(() => rows(d) === `${WA},${WB}`), 'Workload under "All": one row per organisation ' + rows(d));
  check(!d.querySelector('#wl-org') && d.querySelector('#view .ab2tabs'), 'Workload: no picker, the tabs stay above the overview');
  d.querySelector(`#view .spov [data-spov="${WA}"]`).click();
  check(await until(() => w.location.hash === '#workload/s/' + WA && w.eval('WLV.data && WLV.data.org_id') === A && d.querySelector('#view .wltable')), 'a tap opens Alpha, the address carries it ' + w.location.hash);
  check(d.querySelector('#view .spovc [data-spovup]') && /Alpha/.test(d.querySelector('#view .spovc').textContent) && !rows(d) && !d.querySelector('#wl-org'), 'the path "All workspaces / Alpha" above it, no picker');
  d.querySelector('#view [data-act="ab2-tab"][data-v="abs"]').click();
  check(await until(() => w.eval('AB2.data && AB2.data.org_id') === A && d.querySelector('#view .ab2table') && d.querySelector('#view .spovc')), 'Absences keep Alpha');
  check(!d.querySelector('#ab2-org'), 'Absences in an open area: no picker');
  d.querySelector('#view [data-act="ab2-tab"][data-v="dispo"]').click();
  check(await until(() => w.eval('DPV.data && DPV.data.org_id') === A && d.querySelector('#view .dptable') && d.querySelector('#view .spovc')), 'Disposition keeps Alpha');
  check(!d.querySelector('#dp-org'), 'Disposition in an open area: no picker');
  d.querySelector('#view .spovc [data-spovup]').click();
  check(await until(() => w.location.hash === '#workload' && rows(d) === `${WA},${WB}` && !d.querySelector('#dp-org')), 'the path leads back to the overview (Disposition) ' + w.location.hash + ' ' + rows(d));
  d.querySelector(`#view .spov [data-spov="${WB}"]`).click();
  check(await until(() => w.location.hash === '#workload/s/' + WB && w.eval('DPV.data && DPV.data.org_id') === Bo), 'Bravo opens with its own data');
  d.querySelector('#view [data-act="ab2-tab"][data-v="abs"]').click();
  check(await until(() => w.eval('AB2.data && AB2.data.org_id') === Bo && /Bravo/.test(d.querySelector('#view .spovc')?.textContent || '')), 'Absences of Bravo');
  w.close();
  // the address opened directly
  w = await boot({hash: 'workload/s/' + WB}); d = w.document;
  check(await until(() => w.eval('WLV.data && WLV.data.org_id') === Bo && d.querySelector('#view .spovc') && !rows(d)), 'the address of Bravo opened directly');
  w.close();

  // ================= a workspace chosen: as before
  await call('PATCH', '/api/settings', {workspace: WA});
  w = await boot({hash: 'workload'}); d = w.document;
  check(await until(() => w.eval('WLV.data && WLV.data.org_id') === A && d.querySelector('#view .wltable')), 'Alpha chosen: its workload as before');
  check(!rows(d) && !d.querySelector('#view .spovc'), 'Alpha chosen: no overview, no path back');
  d.querySelector('#view [data-act="ab2-tab"][data-v="abs"]').click();
  check(await until(() => w.eval('AB2.data && AB2.data.org_id') === A && d.querySelector('#view .ab2table')) && !rows(d), 'Alpha chosen: its absences, no overview');
  w.close();

  // ================= the office under "All"
  await call('PATCH', '/api/settings', {workspace: 'all'});
  w = await boot({hash: 'office/offers', allWs: true}); d = w.document;
  check(await until(() => rows(d) === `private,${WA},${WB}`), 'office under "All": Private, Alpha, Bravo ' + rows(d));
  check(!d.querySelector('#view .ofdlist') && !/Choose a workspace/.test(d.querySelector('#view').textContent), 'office under "All": no list, no "Choose a workspace"');
  d.querySelector(`#view .spov [data-spov="${WA}"]`).click();
  check(await until(() => w.eval('S.settings.workspace') === WA && w.eval('OFC.info && OFC.info.org_id') === A && d.querySelector('#view .ofchead [data-ofcall="up"]')), 'a tap opens the office of Alpha (the workspace follows) ' + w.eval('S.settings.workspace'));
  check(/^#office\/offers/.test(w.location.hash) && !rows(d), 'the same office page, no overview ' + w.location.hash);
  let saved = ''; for (let i = 0; i < 40 && saved !== WA; i++) { saved = (await call('GET', '/api/state')).settings?.workspace; if (saved !== WA) await sleep(150); }
  check(saved === WA, 'the server saved Alpha as the workspace ' + saved);
  d.querySelector('#view [data-ofcall="up"]').click();
  check(await until(() => w.eval('S.settings.workspace') === 'all' && rows(d) === `private,${WA},${WB}`), '"All workspaces" in the head: back to the overview');
  for (let i = 0; i < 40 && (await call('GET', '/api/state')).settings?.workspace !== 'all'; i++) await sleep(150);  // the switch back is saved (two quick switches may cross)
  d.querySelector('#view .spov [data-spov="private"]').click();
  check(await until(() => w.eval('S.settings.workspace') === 'private' && w.eval('OFC.info && OFC.info.personal'), 60), 'Private opens the personal office ' + w.eval('JSON.stringify([S.settings.workspace, OFC.info && OFC.info.org_id, OFC.info && OFC.info.personal, OFC.infoErr, OFC.pbWait, location.hash])'));
  w.close();
  await call('PATCH', '/api/settings', {workspace: WB});
  w = await boot({hash: 'office/offers'}); d = w.document;
  check(await until(() => w.eval('OFC.info && OFC.info.org_id') === Bo) && !rows(d) && !d.querySelector('[data-ofcall="up"]'), 'Bravo chosen: its office as before, no overview, no path back');
  w.close();

  // ================= a person without an organisation
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, CK = await login('frida'));
  w = await boot({user: 'frida', hash: 'office/offers', allWs: true}); d = w.document;
  check(await until(() => w.eval('OFC.info && OFC.info.personal') && d.querySelector('#view .office .ofcbody')), 'without an organisation: the own office');
  check(!rows(d) && !d.querySelector('[data-ofcall="up"]'), 'without an organisation: no overview');
  w.close();

  console.log(`p2543_c_areas_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
