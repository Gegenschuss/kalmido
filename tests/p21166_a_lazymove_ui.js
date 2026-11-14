// 2.1166.0 A UI test (#4742, start care): Settings > Data > "Move and export everything" (move.js) and "Tasks from notes"
// kalmido-suite: fresh
// (meetprop.js) left the start and load when they are needed; the rules of app.css that only their modules' scripts use moved
// into the module stylesheets (life, office, settings, wiki, contacts, ablage). Own container (start.sh), jsdom, invented data
// only; no server route changed.
// - a cold start runs neither move.js nor meetprop.js; their globals are not there, the stand-in mtg_request is
// - a person without an organisation opens Settings > Data: the section "Move and export everything" is drawn with its
//   export button and its import field (move.js came with the settings module, before settings.js), its rules apply
//   (settings.css holds .umzhow now, not app.css)
// - in an organisation with an agent that takes proposal requests: the list menu's "Tasks from notes…" (propRequest extract)
//   loads meetprop.js through the stand-in and opens the dialog with the list fixed; the agent chat loads it first (LD_NEED)
//   and shows "Turn a meeting into tasks"
const fs = require('fs');
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return r.ok ? r.json() : {status: r.status}; };
const until = fn => require('./boot').until(fn, {timeout: 15000, step: 50});
const ran = (w, f) => !!w.document.querySelector(`script[data-ld="${f}"]`);
const fn = (w, n) => w.eval(`typeof ${n}`) === 'function';
const close = async w => { await until(() => w.eval('ld_n') === 0); w.close(); };

(async () => {
  if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});

  // ---- the files: no script tag, in the modules, rules moved (the stylesheets as the server has them)
  const st = path.join(__dirname, '..', 'static');
  const html = fs.readFileSync(path.join(st, 'index.html'), 'utf8');
  check(!/\/static\/js\/move\.js/.test(html) && !/\/static\/js\/meetprop\.js/.test(html), 'index.html has no tag for move.js / meetprop.js');
  const app = fs.readFileSync(path.join(st, 'app.css'), 'utf8'), setcss = fs.readFileSync(path.join(st, 'css', 'settings.css'), 'utf8');
  check(!/\.umzhow\s*\{/.test(app) && /\.umzhow\s*\{/.test(setcss), 'the rules of the move section are in settings.css, not in app.css');

  // ---- a cold start (a person without an organisation)
  let w = await boot({user: 'alice', lazy: true});
  const tags = w.eval(`[...document.querySelectorAll('script[src]')].map(s => s.getAttribute('src'))`);
  check(!tags.some(s => /\/(move|meetprop)\.js/.test(s)), 'a cold start runs neither move.js nor meetprop.js');
  check(w.eval(`LD_MODS.settings.indexOf('move') >= 0 && LD_MODS.settings.indexOf('move') < LD_MODS.settings.indexOf('settings')`), 'move.js loads with the settings, before settings.js');
  check(w.eval(`LD_MODS.meetprop.join()`) === 'meetprop' && w.eval(`LD_NEED.agentchat.includes('meetprop')`), 'meetprop is a module, the agent chat needs it');
  check(w.eval(`typeof umzHtml`) === 'undefined' && w.eval(`typeof S.mtg`) === 'undefined', 'their globals are not there yet');
  check(fn(w, 'mtg_request'), 'the stand-in mtg_request is there');

  // ---- Settings > Data: the move section, used like a person
  w.eval(`settingsModal('data')`);
  const sec = await until(() => w.document.querySelector('.smodal #s-umz-h'));
  check(sec && /Move and export everything/.test(sec.textContent), 'Settings > Data shows "Move and export everything"');
  check(ran(w, 'move') && ran(w, 'settings'), 'the settings module brought move.js');
  const exp = await until(() => w.document.querySelector('.smodal #s-umz-exp [data-umz="exp"]'));
  check(exp && /Export everything/.test(exp.textContent), 'the export button is drawn (the export state came from the server)');
  check(w.document.querySelector('.smodal #s-umz-file'), 'the import field is there');
  const how = w.document.querySelector('.smodal details.umzhow');
  check(how && /Move to your own server/.test(how.textContent), 'the steps to move are there');
  check(w.eval(`[...document.styleSheets].some(s => /\\/css\\/settings\\.css/.test(s.href || '') && [...s.cssRules].some(r => r.selectorText === '.umzhow summary'))`),
    'the moved rules came with the module (settings.css is in the page with .umzhow summary)');
  await close(w);

  // ---- "Tasks from notes" in an organisation with an agent that takes proposal requests
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  const s0 = await call('GET', '/api/state'), feats = new Set(((s0.settings || {}).features || '').split(',').filter(Boolean)); feats.add('agents');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: [...feats].join(',')});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  await call('PATCH', `/api/admin/agents/${ag.id}`, {org_id: ORG});
  const L = await call('POST', '/api/lists', {name: 'Notes 4742', org_id: ORG});
  await call('PUT', `/api/lists/${L.id}/members`, {user_id: ag.id, role: 'edit'});
  check(ag.id > 0 && L.id > 0, 'setup: an agent and a project of the organisation');

  w = await boot({user: 'alice', lazy: true});
  await until(() => w.eval('(S.proposers || []).length') > 0);
  check(!ran(w, 'meetprop') && w.eval(`typeof S.mtg`) === 'undefined', 'cold start: meetprop.js not loaded');
  w.eval(`propRequest('extract', {lid: ${L.id}}); 0`);
  const md = await until(() => w.document.querySelector('.modal.mtgreq'));
  check(md && /Tasks from notes/.test(md.textContent) && /Notes 4742/.test(md.textContent), 'the list menu\'s "Tasks from notes" loads meetprop.js and opens the dialog for that project');
  check(ran(w, 'meetprop') && w.eval(`typeof S.mtg`) === 'object', 'meetprop.js ran once, its state is there');
  check(md?.querySelector('#pp-text') && md.querySelector('#mtg-file'), 'the notes field and the photo button are there');
  await close(w);

  w = await boot({user: 'alice', lazy: true, hash: `agents/${ag.id}`, mobile: true});
  const btn = await until(() => w.document.querySelector('.chcomp .mtgbtn'));
  check(btn && ran(w, 'meetprop') && /Turn a meeting into tasks/.test(btn.getAttribute('aria-label') || ''), 'the agent chat loads meetprop.js first and offers "Turn a meeting into tasks"');
  await close(w);

  check(errs.length === 0, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`p21166_a_lazymove_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
