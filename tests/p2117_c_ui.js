// 2.117.0 UI tests of part C (#2260; own container, start.sh). jsdom, the agent chat with a job in it:
// - wide: the button group (.jcdseg) is there, no filter icon visible by CSS rules; no select.jcdsel any more
// - the header icon (#jcd-fbtn) opens a menu with the three choices; the choice works; a dot shows while the filter is not "All"
// - phone (390 px rules in the CSS): the filter row is hidden, the icon is shown, the icon is >= 2.75rem
const {execFileSync} = require('child_process');
const fs = require('fs');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2117C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK, TOK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const v1 = async (method, url, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + TOK}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(200); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  const st = await call('GET', '/api/state'), feats = new Set(((st.settings || {}).features || '').split(',').filter(Boolean)); feats.add('agents');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: [...feats].join(',')});
  const me = (await call('GET', '/api/state')).me, ORG = me.workspaces[0].id;
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'devbot', display_name: 'Dev Bot'});
  const CL = ag.id; TOK = ag.token;
  await call('PATCH', `/api/admin/agents/${CL}`, {org_id: ORG});
  const W = (await call('POST', '/api/lists', {name: 'Work', org_id: ORG})).id;
  await call('PUT', `/api/lists/${W}/members`, {user_id: CL, role: 'edit'});
  const J = (await v1('POST', '/agent/jobs', {title: 'Knox: Release 2.117 filter', user_id: me.id, state: 'running'})).id;
  check(J, 'setup: a job');
  await call('POST', `/api/agents/${CL}/chat`, {body: 'Please build the release'});
  const say = (body, kw = {}) => v1('POST', `/agent/chats/${me.id}`, {body, ...kw});
  await say('Hello, a plain answer');
  await say('Knox: started the build', {job_id: J, job_msg: 'say'});

  const w = await boot({user: 'alice', hash: `agents/${CL}`, mobile: true}), d = w.document;
  const hd = () => d.querySelector('.chath'), fbtn = () => d.querySelector('#jcd-fbtn'), filt = () => d.querySelector('#jcd-filt');
  await until(() => fbtn() && !fbtn().hidden);
  check(!d.querySelector('select.jcdsel'), 'no select.jcdsel any more');
  check(fbtn() && !fbtn().hidden && hd().contains(fbtn()), 'the filter icon sits in the chat header');
  check(filt() && !filt().hidden && filt().querySelectorAll('.jcdseg button').length === 3, 'wide: the button group is there');
  check(!fbtn().querySelector('.jcdfdot'), 'filter All: no dot');
  click(w, fbtn());
  await until(() => d.querySelector('[role=menuitem]'));
  const items = [...d.querySelectorAll('[role=menuitem]')];
  check(items.length === 3 && /All/.test(items[0].textContent) && /Only me and Dev Bot/.test(items[1].textContent) && /Jobs/.test(items[2].textContent), 'the menu: All / Only me and <agent> / Jobs');
  click(w, items.find(x => /Jobs/.test(x.textContent)));
  await until(() => w.eval(`LS.get('jcdFilt')`) === 'jobs');
  check(w.eval(`LS.get('jcdFilt')`) === 'jobs', 'the choice is kept');
  await until(() => fbtn()?.querySelector('.jcdfdot'));
  check(fbtn().querySelector('.jcdfdot'), 'filter Jobs: the dot shows');
  check(filt().querySelector('[data-f="jobs"]').getAttribute('aria-pressed') === 'true', 'the button group follows the menu');

  // CSS: phone = icon instead of the row; hit area; rem only
  const css = fs.readFileSync(path.join(__dirname, '..', 'static', 'css', 'agentchat.css'), 'utf8');
  const blk = css.slice(css.indexOf('/* 2.96.0 C (#2015)'));
  check(/@media \(max-width:40rem\)\{ \.jcdfilt\{display:none\} \.jcdfbtn\{display:inline-flex\} \}/.test(blk), 'phone: no filter row, the icon instead');
  check(/\.jcdfbtn\{[^}]*min-width:2\.75rem;min-height:2\.75rem/.test(blk) && /\.jcdfdot\{[^}]*background:var\(--accent\)/.test(blk), 'icon >= 2.75rem, dot in the accent colour');
  check(!/\.jcdfbtn\{[^}]*\d+px/.test(blk) && !/\.jcdfdot\{[^}]*\d+px/.test(blk), 'rem sizes');

  console.log(`p2117_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERR', e); process.exit(1); });
