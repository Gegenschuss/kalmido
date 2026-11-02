// kalmido-suite: fresh
// 2.398.0 UI tests (#3405 #3406), own container (start.sh, mode workspaces). jsdom, invented data only. freelancer-matrix: personal
// - #3405 Notes are an icon of the main bar in every workspace (no row in Projects > Views any more); an organisation's view
//   shows the notes of its projects plus my private list Notes (with the line that they stay private), never a private
//   project's notes; Private shows the private ones and not the organisation's
// - #3406 Review and statistics in an organisation's view: the review asks for that workspace (?space=org:<id>), has no
//   journal and no History there (a line says the journal stays in Private); the statistics ask for it too and show no
//   habits; Private keeps the journal; a person without an organisation sees notes, review and statistics as before
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2398_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments', 'habits', 'review', 'stats', 'time']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,habits,review,stats,time,pomo'});
  const me = (await call('GET', '/api/state')).me.id;
  const ORG = (await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me})).id;
  check(!!ORG, 'organisation Alpha');
  await call('PATCH', '/api/settings', {workspace: 'private'});  // a new list goes to the chosen workspace (ws_chosen_org)
  const PRV = (await call('POST', '/api/lists', {name: 'Garden'})).id;
  const OL = (await call('POST', '/api/lists', {name: 'Client shoot', org_id: ORG})).id;
  const QL = (await call('POST', '/api/notes/quick-list')).list_id;
  check(PRV && OL && QL, `setup: lists ${PRV} ${OL} ${QL}`);
  const NP = (await call('POST', `/api/lists/${PRV}/notes`, {title: 'Roses to buy', body: 'red ones'})).id;
  const NO = (await call('POST', `/api/lists/${OL}/notes`, {title: 'Shot list', body: 'wide, close'})).id;
  const NQ = (await call('POST', `/api/lists/${QL}/notes`, {title: 'Idea for later', body: 'Idea for later'})).id;
  check(NP && NO && NQ, `setup: three notes ${NP} ${NO} ${NQ}`);
  await call('POST', '/api/habits', {name: 'Stretch'});

  // ================= #3405 the organisation's view
  check((await call('PATCH', '/api/settings', {workspace: 'org:' + ORG})).http === 200, 'workspace = Alpha');
  let w = await boot({user: 'alice', hash: 'notes', ls: {'tasks.ws': `"org:${ORG}"`, 'tasks.sideOpenG': JSON.stringify(['views'])}}); let d = w.document;
  await until(() => d.querySelector('#view .sbnall'), 40);
  check(w.eval('wsCur()') === 'org:' + ORG && w.eval('S.route.mod') === 'notes', '#3405: #notes opens in the organisation (no switch to Private): ' + w.eval('wsCur()'));
  check(!!d.querySelector('#srail [data-sbb="notes"].on'), '#3405: Notes is an icon of the bar, marked as open');
  check(!d.querySelector('#side .sg-views [data-go="notes"]'), '#3405: no Notes row under Projects > Views');
  const hrefs = () => [...d.querySelectorAll('#view .sbncard')].map(a => a.getAttribute('href')).sort();
  check(await until(() => hrefs().length === 2) && hrefs().join() === [`#note/${NO}`, `#note/${NQ}`].sort().join(), '#3405: the organisation shows its project\'s note and my private list Notes, not the private project\'s: ' + hrefs());
  check(!!d.querySelector('#view .sbnpriv'), '#3405: the line that new notes stay private');
  check(w.eval('nt_inWs({list_id: ' + PRV + '})') === false && w.eval('nt_inWs({list_id: ' + QL + '})') === true, '#3405: nt_inWs: a private project no, the list Notes yes');

  // ================= #3406 review and statistics in the organisation
  const urls = [];
  const raw = w.rawFetch; w.rawFetch = (m, u, b) => { urls.push(u); return raw(m, u, b); };
  const api0 = w.api; w.api = (m, u, b, o) => { urls.push(u); return api0(m, u, b, o); };
  w.eval(`go('review')`);
  await until(() => w.eval('S.route.mod') === 'review' && !!d.querySelector('#view .rv-done'), 60);
  check(w.eval('wsCur()') === 'org:' + ORG, '#3406: #review stays in the organisation: ' + w.eval('wsCur()'));
  check(urls.some(u => /\/api\/life\/review\?.*space=org%3A/.test(u)), '#3406: the review asks for the organisation: ' + urls.filter(u => /review/.test(u)).join(' '));
  check(!d.querySelector('#view .rvjournal') && !!d.querySelector('#view .rvorg'), '#3406: no journal in the organisation, the line that it stays in Private');
  check(!d.querySelector('#view [data-act="rv-period"][data-p="hist"]'), '#3406: no History in the organisation');
  w.eval(`go('stats')`);
  await until(() => w.eval('S.route.mod') === 'stats' && !!d.querySelector('#view .sttiles'), 60);
  check(urls.some(u => /\/api\/stats\?.*space=org%3A/.test(u)), '#3406: the statistics ask for the organisation: ' + urls.filter(u => /stats/.test(u)).join(' '));
  check(!d.querySelector('#view .sthabits'), '#3406: no habits in the organisation\'s statistics');

  // ================= Private: the journal and the private notes again
  await w.eval('wsSet("private")'); await sleep(200);
  w.eval(`go('review')`);
  check(await until(() => !!d.querySelector('#view .rvjournal'), 60), '#3406: Private: the journal is there');
  check(!!d.querySelector('#view [data-act="rv-period"][data-p="hist"]'), '#3406: Private: History is there');
  check(urls.some(u => /\/api\/life\/review\?.*space=private/.test(u)), '#3406: Private: the review asks for Private');
  w.eval(`go('notes')`);
  check(await until(() => hrefs().length === 2) && hrefs().join() === [`#note/${NP}`, `#note/${NQ}`].sort().join(), '#3405: Private shows the private project\'s note and the list Notes, not the organisation\'s: ' + hrefs());
  check(!d.querySelector('#view .sbnpriv'), '#3405: Private: no extra privacy line');
  w.close();

  // ================= a person without an organisation: as before
  const fu = await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fu.http < 300, 'a person without organisation ' + fu.http);
  const CF = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,review,stats'}, CF);
  const FL = (await call('POST', '/api/lists', {name: 'Portfolio'}, CF)).id;
  const FN = (await call('POST', `/api/lists/${FL}/notes`, {title: 'Reel cuts', body: 'x'}, CF)).id;
  w = await boot({user: 'frida', hash: 'notes'}); d = w.document;
  await until(() => d.querySelector('#view .sbnall'), 40);
  check(!!d.querySelector('#srail [data-sbb="notes"]') && hrefs().join() === `#note/${FN}`, '#3405 freelancer: the Notes icon and her note: ' + hrefs());
  w.eval(`go('review')`);
  check(await until(() => !!d.querySelector('#view .rvjournal'), 60), '#3406 freelancer: the review with the journal');
  w.close();

  console.log(`p2398_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
