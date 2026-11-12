// 2.1037.0 C (#5800) UI test, own container (start.sh), jsdom: an @mention in the team chat stands in "For you" of the bell.
// kalmido-suite: fresh
// - alice mentions bob in the channel "Studio": bob's bell counts it; the bell's panel shows the row "Alice mentioned you in
//   Studio" with the message's words in "For you"; a click opens the channel at that message (it is on screen), the entry is
//   read (the bell's number goes down), Back leads to where bob started
// - a group conversation: its unread message shows as a row "1 new message in <group>" in "For you" (like a direct message);
//   a click opens the group
// P21037C_UI_NOSTART=1 = the container is running.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login, errs, idle} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21037C_UI_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const FEAT = 'cal,comments,collab';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  let A = await login('alice');
  await call(A, 'POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['cal', 'comments', 'collab']});
  A = await login('alice');
  await call(A, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ORG = (await call(A, 'GET', '/api/state')).me.workspaces[0].id;
  const ids = {};
  for (const u of ['bob', 'nora']) ids[u] = (await call(A, 'POST', '/api/users', {orgs: [{id: ORG, role: 'member'}], username: u, display_name: u[0].toUpperCase() + u.slice(1), password: 'password123', email: `${u}@example.com`})).id;
  const Bk = await login('bob');
  await call(Bk, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const L = (await call(A, 'POST', '/api/lists', {name: 'Spring campaign', org_id: ORG, kind: 'project'})).id;
  for (const u of ['bob', 'nora']) await call(A, 'PUT', `/api/lists/${L}/members`, {user_id: ids[u], role: 'edit'});
  const CH = (await call(A, 'POST', '/api/team/channels', {name: 'Studio', org_id: ORG, open: false, members: [ids.bob, ids.nora]})).id;
  const GR = (await call(A, 'POST', '/api/team/groups', {members: [ids.bob, ids.nora], name: 'Lunch'})).id;
  check(L && CH && GR, `setup: project, channel, group ${L} ${CH} ${GR}`);
  for (let i = 0; i < 12; i++) await call(A, 'POST', `/api/team/rooms/${CH}/messages`, {body: `Plan step ${i + 1}`});
  const M = (await call(A, 'POST', `/api/team/rooms/${CH}/messages`, {body: `<@${ids.bob}> please bring the lights`})).id;
  for (let i = 0; i < 3; i++) await call(A, 'POST', `/api/team/rooms/${CH}/messages`, {body: `Later note ${i + 1}`});
  await call(A, 'POST', `/api/team/rooms/${GR}/messages`, {body: 'Noon at the corner?'});
  check(M, 'setup: the mention');
  const nb = await call(Bk, 'GET', '/api/news');
  check((nb.items || []).some(x => x.kind === 'chatmention' && x.data.room === CH && !x.read), 'setup: bob has the mention item');

  // ---- the bell
  const w = await boot({user: 'bob', hash: 'today'}), d = w.document;
  await idle(w);
  const start = w.location.hash;
  const bell = () => d.querySelector('#kbar .bell');
  const badge = () => +(bell()?.querySelector('.nbadge')?.textContent || 0);
  check(await until(() => badge() >= 2), `the bell counts the mention and the group's message (${badge()})`);
  const n0 = badge();
  click(w, bell()); await idle(w);
  // 2.1052.0 (#5808): News show only bundled: the room's mention is a bundle of its own (one entry, the head opens it)
  const row = await until(() => [...d.querySelectorAll('#pop:not(.hidden) .bpop .ngroup .ngmain[data-bp="open"]')].find(m => /mentioned you in Studio/.test(m.textContent)));
  check(row && /Alice mentioned you in Studio/.test(row.querySelector('.ngt')?.textContent || '') && /1 mention/.test(row.querySelector('.ngs')?.textContent || ''), 'the bell shows "Alice mentioned you in Studio" ' + (row?.textContent || '').trim().slice(0, 120));
  check(row && /please bring the lights/.test(row.querySelector('.ngex')?.textContent || ''), 'the row carries the message\'s words');
  const secOf = el => el ? (el.closest('section.nsect.me') ? 'me' : el.closest('.nhist') ? 'other' : null) : null;  // 2.1052.0 (#5808): the sections, no .nsec heads
  check(secOf(row) === 'me' && row.closest('.ngroup.needs.unread'), 'the row stands in the section "For you" ' + secOf(row));
  const grow = d.querySelector('#pop .bpop .nitem.k-group');
  check(grow && secOf(grow) === 'me' && /1 new message in/.test(grow.textContent) && /Lunch/.test(grow.textContent), 'the group conversation has its row in "For you" ' + (grow?.textContent || '').trim().slice(0, 120));

  // ---- a click opens the channel at the message
  click(w, row);
  const sel = `[data-mid="t:${M}"]`;
  const hit = await until(() => w.eval(`S.route.mod === 'team' && S.tc.rid === ${CH}`) && d.querySelector('#view ' + sel));
  check(hit && hit.textContent.includes('please bring the lights'), `the click opens the channel at the message (${w.location.hash})`);
  check(hit && !hit.closest('.hidden,[hidden]'), 'the message is on screen');
  check(await until(async () => (await call(Bk, 'GET', '/api/news')).items.filter(x => x.kind === 'chatmention' && !x.read).length === 0), 'the entry is read (no second tick)');
  check(await until(() => badge() < n0), `the bell's number goes down (${n0} -> ${badge()})`);
  w.history.back();
  check(await until(() => w.location.hash === start), `Back leads to where bob started (${w.location.hash})`);
  await idle(w);

  // ---- the group's row opens the group
  click(w, bell()); await idle(w);
  const g2 = await until(() => d.querySelector('#pop:not(.hidden) .bpop .nitem.k-group'));
  check(g2, 'the group row is still there (not read yet)');
  if (g2) {
    click(w, g2);
    check(await until(() => w.eval(`S.route.mod === 'team' && S.tc.rid === ${GR}`) && (d.querySelector('#view')?.textContent || '').includes('Noon at the corner?')), `the group row opens the group (${w.location.hash})`);
  }

  check(!errs.length, 'jsdom: no JS errors ' + errs.join(' | '));
  w.close();
  console.log(`p21037_c_chat_mention_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
