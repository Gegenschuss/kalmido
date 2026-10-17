// 2.64.2 part A (#1817): the lock per list, stage 2 -- key change after someone leaves and the background re-encryption, end to
// end in Firefox (real WebCrypto), own container (start.sh):
// - Alice switches the lock on for a list shared with Bob and Carol, then Carol is removed: the list shows "rotation pending"
// - Alice's browser (owner, unlocked) changes the key on its own (generation 2) and re-encrypts every older text in the
//   background (event le2e:progress kind 'reenc'); afterwards the server holds ciphertexts of generation 2 only, new texts too
// - Bob (stayed) reads everything; Dave (new member after the key change) gets every generation and reads an old text of
//   generation 1 and the new ones
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p264b_a_ui', check, shots: 'P264BA_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.BASE) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, j: await r.json().catch(() => ({}))}; };
const PASS = {alice: 'correct horse battery staple', bob: 'another horse battery staple', carol: 'third horse battery staple', dave: 'fourth horse battery staple'};
const M = 'ZQXmark';
const gen = v => typeof v === 'string' && v.startsWith('e2e1:') ? JSON.parse(v.slice(5)).g : null;

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const U = {};
  for (const n of ['bob', 'carol', 'dave']) U[n] = (await call('POST', '/api/users', {username: n, display_name: n[0].toUpperCase() + n.slice(1), password: 'password123'})).j.id;
  const L = (await call('POST', '/api/lists', {name: 'Shared locked'})).j.id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: U.bob, role: 'edit'});
  await call('PUT', `/api/lists/${L}/members`, {user_id: U.carol, role: 'edit'});
  const T = (await call('POST', '/api/tasks', {title: `${M} first task`, list_id: L, content: `${M} first notes`})).j.id;
  const TO = (await call('POST', '/api/tasks', {title: `${M} other task`, list_id: L})).j.id;
  await call('POST', `/api/tasks/${T}/comments`, {body: `${M} a comment`});

  const session = (user, fn) => firefox(async ({cmd, ev, nav, ctx, shot}) => {
    const waitFor = async (expr, n = 80) => { for (let i = 0; i < n; i++) { const v = await ev(expr).catch(() => null); if (v) return v; await sleep(250); } return null; };
    const boot = async hash => { await nav(B + 'static/icon.svg'); await nav(B + hash); await waitFor('!!(window.S && S.booted)'); await sleep(500); };
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${user}', password: 'password123'})}).then(r => r.status)`) === 200, `Firefox: login ${user}`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await boot('#l/' + L);
    const unlock = () => ev(`(async () => { await e2eLoad(true); await e2eAdopt(await e2eUnwrapPass(E2E.st.bundle_pass, ${JSON.stringify(PASS[user])})); return 1; })()`);
    await fn({ev, waitFor, boot, shot, unlock});
  }, false);
  const waitSrv = async (fn, n = 120) => { for (let i = 0; i < n; i++) { const v = await fn(); if (v) return v; await sleep(500); } return null; };

  for (const u of ['bob', 'carol', 'dave']) await session(u, async ({ev}) => { check(await ev(`e2eCreate(${JSON.stringify(PASS[u])}).then(c => !!c)`), `${u} sets up encryption`); });
  let OLD = '';
  await session('alice', async ({ev}) => {
    check(await ev(`e2eCreate(${JSON.stringify(PASS.alice)}).then(c => !!c && e2eUnlocked())`), 'alice sets up encryption');
    check(await ev(`le2eStart(${L}, () => {}).then(r => !!r && listById(${L})?.e2e === 'on' && listById(${L}).e2e_gen === 1)`), 'le2eStart: generation 1');
    OLD = await ev(`le2eEnc(${L}, 'title', '${M} old title')`);  // a cipher of generation 1, written again after the key change
    check(gen(OLD) === 1, 'a cipher of generation 1');
  });
  // Carol is removed: rotation pending
  check((await call('DELETE', `/api/lists/${L}/members/${U.carol}`)).status === 200, 'carol removed');
  check((await call('GET', `/api/lists/${L}/e2e`)).j.rotate === 1, 'rotation pending after carol left');

  await session('alice', async ({ev, unlock}) => {
    await ev(`(window.__prog = [], document.addEventListener('le2e:progress', e => window.__prog.push(e.detail)), 1)`);
    await unlock();
    await ev(`le2eUnlock(${L}).then(() => 1)`);  // the automatic key change starts here (owner, unlocked)
    const info = await waitSrv(async () => { const j = (await call('GET', `/api/lists/${L}/e2e`)).j; return j.gen === 2 && j.rotate === 0 && j.reenc === 0 ? j : null; });
    check(!!info, 'the key changed on its own (generation 2) and the re-encryption finished');
    const prog = await ev(`window.__prog`);
    check(prog.length && prog.every(p => p.lid === L && p.kind === 'reenc') && prog[prog.length - 1].done === prog[prog.length - 1].total, 'le2e:progress kind reenc up to done ' + JSON.stringify(prog).slice(0, 300));
    const st = (await call('GET', '/api/state')).j;
    const rows = (st.tasks || []).filter(t => t.list_id === L);
    check(rows.length === 2 && rows.every(t => gen(t.title) === 2) && gen(rows.find(t => t.id === T).content) === 2, 'the server holds titles and notes of generation 2 only ' + JSON.stringify(rows.map(t => [gen(t.title), gen(t.content)])));
    const tl = (await call('GET', `/api/tasks/${T}/timeline`)).j;
    check((tl.comments || []).length === 1 && gen(tl.comments[0].body) === 2, 'the comment is of generation 2');
    check(await ev(`S.tasks.get(${T})?.title === '${M} first task' && listById(${L}).e2e_gen === 2`), 'alice still reads the task');
    await ev(`api('PATCH', '/api/tasks/${T}', {title: '${M} renamed'}).then(j => (putTask(j), 1))`);
    const row = ((await call('GET', '/api/state')).j.tasks || []).find(t => t.id === T);
    check(gen(row?.title) === 2, 'a new text uses generation 2');
    // the button "Change the key now" (nobody left): generation 3, the re-encryption follows on its own
    check(await ev(`le2eRotate(${L}, true).then(r => r, e => e.code || e.message)`) === true, 'a manual key change');
    check(!!await waitSrv(async () => { const j = (await call('GET', `/api/lists/${L}/e2e`)).j; return j.gen === 3 && j.reenc === 0 && j.rotate === 0; }),
      'manual key change: generation 3, re-encrypted');
  });
  const G = (await call('GET', `/api/lists/${L}/e2e`)).j.gen;
  // an old text of generation 1 (as a backup or an unconverted row would hold it), written by Alice's session
  check((await call('PATCH', `/api/tasks/${TO}`, {title: OLD})).status === 200, 'an old cipher of generation 1 in the list');

  await session('bob', async ({ev, unlock, waitFor}) => {
    await unlock();
    check(await ev(`le2eUnlock(${L})`), 'bob unlocks the list after the key change');
    check(await waitFor(`S.tasks.get(${T})?.title === '${M} renamed' && S.tasks.get(${TO})?.title === '${M} old title'`), 'bob reads the new text and the old one');
  });
  // Dave joins after the key change: alice releases every generation
  await call('PUT', `/api/lists/${L}/members`, {user_id: U.dave, role: 'edit'});
  await session('alice', async ({ev, unlock}) => {
    await unlock();
    const j = await ev(`le2eRelease(${L}, [${U.dave}]).then(j => j, e => ({err: e.message}))`);
    check(j && (j.released || []).includes(U.dave), 'release to dave ' + JSON.stringify(j));
  });
  await session('dave', async ({ev, unlock, waitFor}) => {
    await unlock();
    const gens = (await ev(`le2eInfo(${L}, true).then(j => j.keys.map(k => k.gen))`)) || [];
    check(JSON.stringify(gens) === JSON.stringify([...Array(G).keys()].map(i => i + 1)), 'dave holds every generation ' + JSON.stringify(gens));
    check(await ev(`le2eUnlock(${L})`), 'dave unlocks the list');
    check(await waitFor(`S.tasks.get(${T})?.title === '${M} renamed' && S.tasks.get(${TO})?.title === '${M} old title'`), 'dave reads the new text and the old one of generation 1');
  });

  console.log(`p264b_a_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
