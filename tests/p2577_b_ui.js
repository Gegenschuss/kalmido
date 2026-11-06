// 2.577.0 UI tests of part B (#4638): the office under "All workspaces" opens an area at its own address #office/s/<space>
// kalmido-suite: fresh
// instead of switching the workspace (390 px, a phone). Own container (start.sh), jsdom, invented data only.
// - the overview (Private, Alpha, Bravo); a tap opens #office/s/org:<Alpha>: its office, the workspace on top stays "All"
// - a link inside the area keeps it (#office/s/<space>/<tab>); a change made there lands in that area (the request names it)
// - an outbox entry keeps the area it was made in, even when another area is open by the time it goes out
// - the browser's Back leads to the overview; Private opens the personal office the same way
// - freelancer-matrix: office (a person without an organisation: no overview, office/s/private = her own office)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK, hd = {}) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...hd, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const FEAT = 'cal,comments,collab,office,clients';
const rows = d => [...d.querySelectorAll('#view .spov [data-spov]')].map(a => a.dataset.spov).join();
const svc = async sp => ((await call('GET', '/api/office/services', null, CK, {'X-Kalmido-Office-Space': sp})).items || []).map(x => x.name_de);

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

  let w = await boot({hash: 'office', allWs: true, mobile: true}), d = w.document;
  check(await until(() => rows(d) === `private,${WA},${WB}`), 'phone, office under "All": the overview ' + rows(d));
  d.querySelector(`#view .spov [data-spov="${WA}"]`).click();
  check(await until(() => w.location.hash === '#office/s/' + WA && w.eval('OFC.info && OFC.info.org_id') === A && !rows(d)), 'a tap opens Alpha at its own address ' + w.location.hash);
  check(w.eval('S.settings.workspace') === 'all' && (await call('GET', '/api/state')).settings?.workspace === 'all', 'the workspace stays "All" (here and on the server)');
  check(!!d.querySelector('#view [data-ofcall="up"]'), 'the head shows "All workspaces /"');
  w.eval("go('office/offers')");
  check(await until(() => w.location.hash === `#office/s/${WA}/offers` && w.eval('S.route.wsp') === WA), 'a link inside the area keeps it ' + w.location.hash);
  await w.eval("api('POST', '/api/office/services', {name_de: 'Alpha service'})").catch(e => check(false, 'the change in Alpha ' + e.message));
  const sa = await svc(WA), sb = await svc(WB);
  check(sa.includes('Alpha service') && !sb.includes('Alpha service'), `a change made in Alpha lands in Alpha ${sa} / ${sb}`);
  // an outbox entry: made in Alpha, sent while Bravo is open
  w.eval("enqueue('POST', '/api/office/services', {name_de: 'Queued in Alpha'}); S.route = {...S.route, wsp: 'org:" + Bo + "'};");
  check(await until(async () => (await svc(WA)).includes('Queued in Alpha')), 'the waiting change goes out into Alpha ' + (await svc(WA)));
  check(!(await svc(WB)).includes('Queued in Alpha'), 'never into the area open when it goes out');
  w.history.back();
  check(await until(() => w.location.hash === '#office/s/' + WA), 'Back: the area\'s start ' + w.location.hash);
  w.history.back();
  check(await until(() => w.location.hash === '#office' && rows(d) === `private,${WA},${WB}`), 'Back again leads to the overview ' + w.location.hash);
  d.querySelector('#view .spov [data-spov="private"]')?.click();
  check(await until(() => w.location.hash === '#office/s/private' && w.eval('OFC.info && OFC.info.personal')), 'Private: the personal office at its own address ' + w.location.hash);
  w.close();

  // ================= a person without an organisation
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, CK = await login('frida'));
  w = await boot({user: 'frida', hash: 'office', allWs: true, mobile: true}); d = w.document;
  check(await until(() => w.eval('OFC.info && OFC.info.personal')) && !rows(d), 'freelancer: her own office, no overview');
  w.close();
  w = await boot({user: 'frida', hash: 'office/s/private', allWs: true, mobile: true}); d = w.document;
  check(await until(() => w.eval('OFC.info && OFC.info.personal') && !w.eval('OFC.infoErr')), 'freelancer: office/s/private = her own office');
  w.close();

  console.log(`p2577_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e && e.stack); process.exit(1); });
