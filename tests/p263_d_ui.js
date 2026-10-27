// 2.63.0 UI tests of part D (own container, start.sh). jsdom:
// - #1857 knowledge pages: with one workspace shown above there is no second space list; with "All" the list is there
// - #1482 the job card: "Conversation" unfolds the job's messages (mine to it + its answers), a new answer refreshes the
//   open section, the link opens the job's own history
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P263D_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK, TOK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const v1 = async (method, url, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + TOK}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(200); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  const st = await call('GET', '/api/state'), feats = new Set(((st.settings || {}).features || '').split(',').filter(Boolean)); feats.add('agents'); feats.add('wiki');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: [...feats].join(',')});
  const me = (await call('GET', '/api/state')).me, ORG = me.workspaces[0].id;
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  const CL = ag.id; TOK = ag.token;
  await call('PATCH', `/api/admin/agents/${CL}`, {org_id: ORG});
  const W = (await call('POST', '/api/lists', {name: 'Work', org_id: ORG})).id;
  await call('PUT', `/api/lists/${W}/members`, {user_id: CL, role: 'edit'});
  const JA = (await v1('POST', '/agent/jobs', {title: 'Clara: Release 1.0', user_id: me.id})).id;
  const say = (body, kw = {}) => v1('POST', `/agent/chats/${me.id}`, {body, ...kw});
  await say('Clara: halfway there', {job_id: JA});

  // ================= #1857 the space list of the knowledge pages
  await call('PATCH', '/api/settings', {workspace: `org:${ORG}`});
  let w = await boot({user: 'alice', hash: 'wiki'}), d = w.document;
  await until(() => d.querySelector('.wkside, .wkbar'));  // 2.152.3 (#2620): a computer: the bar on top instead of the tree column
  check(!d.querySelector('[data-wk="space"]'), '#1857: one workspace shown: no second space list');
  w.close();
  await call('PATCH', '/api/settings', {workspace: 'all'});
  w = await boot({user: 'alice', hash: 'wiki'}); d = w.document;
  await until(() => d.querySelector('.wkside, .wkbar'));  // 2.152.3 (#2620): a computer: the bar on top instead of the tree column
  // 2.198.0 A (#2743): "All" has no space switch any more, an entry "All pages <space>" per space instead
  check(!d.querySelector('[data-wk="space"]') && await until(() => d.querySelector('#side [data-wksp="private"], #view [data-wksp="private"]')), '#1857 / #2743: "All": no space list, an entry per space');
  w.close();

  // ================= #1482 the conversation on the job card
  w = await boot({user: 'alice', hash: 'agents'}); d = w.document;
  const card = await until(() => d.querySelector(`#job-${JA}`));
  const det = card?.querySelector('details.jobth');
  check(det && !det.open, '#1482: the card has a closed "Conversation"');
  det.open = true; det.dispatchEvent(new w.Event('toggle'));
  await until(() => /halfway there/.test(d.querySelector(`#job-${JA} .jobth`)?.textContent || ''));
  check(/halfway there/.test(d.querySelector(`#job-${JA} .jobth`)?.textContent || ''), '#1482: unfolded: the job\'s message is shown');
  await say('Clara: and now done', {job_id: JA});
  await until(() => /now done/.test(d.querySelector(`#job-${JA} .jobth`)?.textContent || ''), 80);
  check(/now done/.test(d.querySelector(`#job-${JA} .jobth`)?.textContent || ''), '#1482: a new answer refreshes the open section');
  const lk = d.querySelector(`#job-${JA} .jobth [data-act="jc-open"]`);
  check(lk, '#1482: link to the whole conversation');
  if (lk) { click(w, lk); await until(() => d.querySelector('#jc-bar')); check(d.querySelector('#jc-bar'), '#1482: the link opens the job\'s history'); }
  w.close();

  console.log(`p263_d_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
