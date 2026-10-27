// 2.49.0 UI tests of part E (#1106 find people by e-mail), own container (start.sh, no SMTP). jsdom:
// - Settings > Account has the row "Find people"; it opens the People dialog; the share dialog links to it
// - search: a findable person shows name + "Connect", a miss the neutral text; Connect sends a request (one undo step:
//   undo withdraws it, redo sends it again)
// - "Findable by e-mail" without e-mail on the server: the error, the switch stays off
// - the other side: the News text, the request with Accept / Decline / Block; Accept connects (the person appears in the
//   people the app knows), Disconnect + undo
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const sql = (q, args = []) => execFileSync('python3', [path.join(__dirname, 'dbx.py'), path.join(DATA, 'tasks.db'), q, JSON.stringify(args)], {encoding: 'utf-8'});

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'});
  const ANN = (await call('POST', '/api/users', {username: 'ann', display_name: 'Ann Example', password: 'password123', email: 'ann@example.com'})).id;
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Example', password: 'password123', email: 'bob@example.com'})).id;
  check((await call('POST', '/api/admin/orgs', {name: 'Alpha'})).id, 'setup: an organisation (people outside it see only their connections)');
  sql("INSERT INTO disc_profiles(user_id,email,confirmed_at,created_at) VALUES(?,?,?,?)", [ANN, 'ann@example.com', '2026-01-01', '2026-01-01']);
  const CKA = await login('ann'), CKB = await login('bob');
  for (const ck of [CKA, CKB]) await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'}, ck);

  // ================= bob: Settings > Account > Find people
  let w = await boot({user: 'bob', hash: 'today'}), d = w.document;
  w.eval(`settingsModal('account')`); await sleep(200);
  const open = d.querySelector('.smodal [data-dsc-open]');
  check(open && d.querySelector('#s-dsc-h'), 'Settings > Account: the row "Find people"');
  open.click();
  const md = await until(() => d.querySelector('.dscmodal'));
  check(md && md.querySelector('#dsc-email') && md.querySelector('#dsc-findable') && !md.querySelector('#dsc-findable').checked,
    'the People dialog: the address field, "Findable by e-mail" off');
  check(!md.querySelector('#dsc-req-h') && !md.querySelector('#dsc-con-h'), 'no requests, no connections yet: their sections are hidden');
  const search = async v => { md.querySelector('#dsc-email').value = v; md.querySelector('[data-dsc-form]').dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true})); await sleep(400); };
  await search('nobody@example.com');
  check(/Not found\. Only people who switched on/.test(md.querySelector('#dsc-found')?.textContent || ''), 'a miss: the neutral text');
  await search('  ANN@example.com ');
  const row = md.querySelector('#dsc-found .dsc-row');
  check(row && /Ann Example/.test(row.textContent) && row.querySelector('[data-dsc="connect"]') && row.querySelector('.avatar'), 'a hit: picture, name and "Connect"');
  check(!/ann@example\.com/i.test(md.querySelector('#dsc-found').textContent), 'the hit does not repeat the address');
  row.querySelector('[data-dsc="connect"]').click();
  await until(() => /Request sent/.test(md.querySelector('#dsc-found')?.textContent || ''));
  check(/Request sent/.test(md.querySelector('#dsc-found').textContent), 'Connect: "Request sent"');
  let inc = (await call('GET', '/api/disc', null, CKA)).incoming || [];
  check(inc.length === 1 && inc[0].person.id === BOB, 'ann got the request');
  check(md.querySelector('#dsc-out-h') && /Ann Example/.test(md.textContent), 'the sent request is listed with "Withdraw"');
  await w.eval(`histStep('undo')`); await sleep(400);
  check(!((await call('GET', '/api/disc', null, CKA)).incoming || []).length, 'undo withdraws the request');
  await w.eval(`histStep('redo')`); await sleep(400);
  check(((await call('GET', '/api/disc', null, CKA)).incoming || []).length === 1, 'redo sends it again');
  // findable without e-mail on this server: the error, the switch goes back
  const sw = md.querySelector('#dsc-findable'); sw.checked = true; sw.dispatchEvent(new w.Event('change', {bubbles: true}));
  await sleep(500);
  check(!md.querySelector('#dsc-findable').checked && /cannot send e-mails/.test(d.querySelector('#toast')?.textContent || ''), 'no e-mail: a clear message, the switch stays off');
  md.querySelector('[data-dsc="close"]').click(); await sleep(250);
  check(!d.querySelector('.dscmodal'), 'the dialog closes');
  // the share dialog links to it
  const L = (await call('POST', '/api/lists', {name: 'Bob list'}, CKB)).id;
  w.eval(`load().then(() => shareModal(${L}))`); await sleep(700);
  check(d.querySelector('.modal .dsc-sharelink[data-dsc-open]'), 'the share dialog: "Find a person …" below the people');
  w.close();

  // ================= ann: the request, accept, disconnect + undo
  w = await boot({user: 'ann', hash: 'today'}); d = w.document;
  const knows = async () => ((await call('GET', '/api/users', null, CKA)).users || []).some(u => u.id === BOB);
  check(/Bob Example<\/b> wants to connect with you/.test(w.eval(`newsText({kind: 'connreq', data: {}, actor_id: ${BOB}}, {${BOB}: 'Bob Example'})`)), 'News: "… wants to connect with you"');
  check(!await knows(), 'before accepting ann does not see bob');
  w.eval('dsc_open()');
  const m2 = await until(() => d.querySelector('.dscmodal #dsc-req-h') && d.querySelector('.dscmodal'));
  const rr = m2 && m2.querySelector('[data-dsc="accept"]')?.closest('.dsc-row');
  check(rr && /Bob Example/.test(rr.textContent) && rr.querySelector('[data-dsc="decline"]') && rr.querySelector('[data-dsc="block"]'), 'the request: Accept, Decline, Block');
  rr.querySelector('[data-dsc="accept"]').click();
  await until(() => m2.querySelector('#dsc-con-h'), 60);
  check(m2.querySelector('#dsc-con-h') && /Bob Example/.test(m2.querySelector('[aria-labelledby="dsc-con-h"]')?.textContent || ''), 'accepted: bob is under Connections');
  check(await knows(), 'after accepting ann sees bob (share, chat)');
  m2.querySelector('[data-dsc="drop"]').click();
  await until(() => !m2.querySelector('#dsc-con-h'), 60);
  check(!m2.querySelector('#dsc-con-h') && !await knows(), 'Disconnect: bob is gone again');
  await w.eval(`histStep('undo')`); await sleep(800);
  check(await knows() && m2.querySelector('#dsc-con-h'), 'undo of Disconnect: connected again');
  w.close();

  console.log(`p249_e_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
