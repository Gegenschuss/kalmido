// 2.64.1 part C (#1817): the lock per list -- client data layer (static/js/liste2e.js), own container (start.sh), Firefox (real
// WebCrypto). Without the server routes (part A) the client is driven with a list key set in the page:
// - field crypto: "e2e1:" + {v, g, iv, ct}, padding to 64 bytes (L1), the AAD binds list, generation and field
// - list keys: wrapping between two key pairs (ECDH + HKDF), my own wrap uses my own key (never the server's copy), a changed key of
//   another person is not used until confirmed (H4)
// - incoming ciphers become plain texts in memory (_enc keeps the ciphers), outgoing texts leave encrypted (task, comment)
// - H1: offline outbox and every localStorage entry hold ciphers only (sweep for a marker); lock = wipe
// - moving a task out of a locked list carries its texts, its comments in the target format (le2e_move)
// With part A's routes (after the merge) also end to end: Bob sets up encryption, Alice switches the lock on (le2eStart), the server
// keeps ciphers only, Bob reads with his own key, Alice switches it off again (le2eStop) and the texts are plain on the server.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p264a_c_ui', check, shots: 'P264AC_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.BASE) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, j: await r.json().catch(() => ({}))}; };
const PASS = 'correct horse battery staple', PASS_B = 'another horse battery staple';
const M = 'ZQXmark';  // every plain text of a locked list carries it: no storage may hold it

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const ME = (await call('GET', '/api/state')).j.me.id;
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).j.id;
  const L = (await call('POST', '/api/lists', {name: 'Locked'})).j.id;
  const L2 = (await call('POST', '/api/lists', {name: 'Open'})).j.id;
  const T2 = (await call('POST', '/api/tasks', {title: 'Open task', list_id: L2})).j.id;
  const hasA = (await call('GET', `/api/lists/${L}/e2e`)).status === 200;

  const session = (user, fn) => firefox(async ({cmd, ev, nav, ctx, shot}) => {
    const waitFor = async (expr, n = 80) => { for (let i = 0; i < n; i++) { const v = await ev(expr).catch(() => null); if (v) return v; await sleep(250); } return null; };
    const boot = async hash => { await nav(B + 'static/icon.svg'); await nav(B + hash); await waitFor('!!(window.S && S.booted)'); await sleep(500); };
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${user}', password: 'password123'})}).then(r => r.status)`) === 200, `Firefox: login ${user}`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await boot('#inbox');
    const sweep = () => ev(`Object.keys(localStorage).filter(k => (localStorage.getItem(k) || '').includes('${M}')).join(',')`);
    await fn({ev, waitFor, boot, shot, sweep});
  }, false);

  // ---------------------------------------------------------------- without part A: the data layer with a key set in the page
  await session('alice', async ({ev, waitFor, sweep}) => {
    check(await ev(`e2eCreate(${JSON.stringify(PASS)}).then(c => !!c && e2eUnlocked())`), 'encryption set up and unlocked');
    // a list key of generation 1 for list L, as if the lock were on
    await ev(`(async () => {
      const raw = crypto.getRandomValues(new Uint8Array(32)); window.__raw = raw.slice();
      LE2E.keys[${L}] = {1: await le2eImport(raw)};
      const fix = j => { for (const l of j.lists || []) if (l.id === ${L}) Object.assign(l, {e2e: 'on', e2e_gen: 1, e2e_mine: true}); };
      fix({lists: S.lists}); LE2E.on.add(${L});
      const as0 = applyState; applyState = j => { fix(j); return as0(j); };  // the server of this suite has no lock yet
      return 1; })()`);
    // field crypto
    const c1 = await ev(`le2eEnc(${L}, 'title', '${M} alpha')`);
    const o1 = c1 && c1.startsWith('e2e1:') ? JSON.parse(c1.slice(5)) : {};
    check(Object.keys(o1).join() === 'v,g,iv,ct' && o1.v === 1 && o1.g === 1, 'cipher format e2e1: + {v, g, iv, ct} ' + c1);
    const sizes = await ev(`(async () => { const n = async s => atob(JSON.parse((await le2eEnc(${L}, 'content', s)).slice(5)).ct).length;
      return [await n('a'), await n('x'.repeat(63)), await n('x'.repeat(64))]; })()`);
    check(JSON.stringify(sizes) === JSON.stringify([80, 80, 144]), 'L1: plain text padded to multiples of 64 bytes (+16 tag) ' + JSON.stringify(sizes));
    check(await ev(`(LE2E.memo.clear(), le2eDec(${L}, 'title', ${JSON.stringify(c1)}))`) === `${M} alpha`, 'round trip: the cipher opens with the list key');
    const aad = await ev(`(async () => { LE2E.memo.clear(); const k = LE2E.keys[${L}], c = ${JSON.stringify(c1)};
      const g2 = 'e2e1:' + JSON.stringify({...JSON.parse(c.slice(5)), g: 2});
      return [await le2eTry(${L}, c, ['content'], k), await le2eTry(${L} + 1, c, ['title'], k), await le2eTry(${L}, g2, ['title'], {2: k[1]}), await le2eTry(${L}, c, ['title'], k)]; })()`);
    check(aad[0] == null && aad[1] == null && aad[2] == null && aad[3] === `${M} alpha`, 'AAD: another field, list or generation does not open it ' + JSON.stringify(aad));
    check(await ev(`le2eEnc(${L}, 'title', '').then(c => c === '')`), 'an empty text stays "" (never encrypted)');
    // list keys: wrapping between two key pairs; H4
    const wr = await ev(`(async () => {
      const bob = await crypto.subtle.generateKey({name: 'ECDH', namedCurve: 'P-256'}, true, ['deriveBits']);
      const bj = await crypto.subtle.exportKey('jwk', bob.publicKey), bobPub = {x: bj.x, y: bj.y}, out = {};
      const alicePriv = E2E.priv, raw = window.__raw;
      const w = await le2eWrap(raw, ${L}, 1, ${BOB}, bobPub);  // Alice wraps for Bob
      E2E.priv = bob.privateKey;  // Bob unwraps with his private key and Alice's public key
      const got = await e2eOpen(await le2eKek(E2E.own, ${L}, 1), w, le2eWrapAad(${L}, 1, ${BOB}, ${ME}));
      out.bobGets = e2eB64(got) === e2eB64(raw);
      const wb = await e2eSeal(await le2eKek(E2E.own, ${L}, 1), raw, le2eWrapAad(${L}, 1, ${ME}, ${BOB}));  // Bob wraps for Alice
      E2E.priv = alicePriv;
      LS.set('e2eSeen:${ME}:${BOB}', 'some.otherkey');
      try { await le2eRaw(${L}, {gen: 1, wrapped: wb, wrapped_by: ${BOB}, wrapper_pub: bobPub}); out.changedUsed = true; } catch (e) { out.changedCode = e.code; }
      out.flag = le2eKeyChanged(${BOB});
      le2eAcceptKey(${BOB});
      out.after = e2eB64(await le2eRaw(${L}, {gen: 1, wrapped: wb, wrapped_by: ${BOB}, wrapper_pub: bobPub})) === e2eB64(raw) && !le2eKeyChanged(${BOB});
      const wo = await le2eWrap(raw, ${L}, 1, ${ME}, E2E.own);  // my own wrap: my key from the bundle, a forged server copy is ignored
      out.own = e2eB64(await le2eRaw(${L}, {gen: 1, wrapped: wo, wrapped_by: ${ME}, wrapper_pub: bobPub})) === e2eB64(raw);
      return out; })()`);
    check(wr.bobGets, 'wrap: the member unwraps the list key with ECDH + HKDF ' + JSON.stringify(wr));
    check(!wr.changedUsed && wr.changedCode === 'list_e2e_keychanged' && wr.flag, 'H4: a changed key of another person is not used, le2eKeyChanged says so');
    check(wr.after, 'H4: after le2eAcceptKey the key is used');
    check(wr.own, 'H4: my own wrap opens with my own key (the server copy of wrapper_pub is ignored)');

    // incoming: a cipher in the state becomes the plain text in memory, the cipher stays in _enc
    const cT = await ev(`le2eEnc(${L}, 'title', '${M} task title')`);
    const cC = await ev(`le2eEnc(${L}, 'content', '${M} task notes')`);
    const T = (await call('POST', '/api/tasks', {title: cT, list_id: L, content: cC})).j.id;
    check(await ev(`load().then(() => { const t = S.tasks.get(${T}); return t && t.title === '${M} task title' && t.content === '${M} task notes' && t._enc?.title === ${JSON.stringify(cT)} && !t._le2e; })`),
      'incoming: the state shows the plain text, _enc keeps the cipher');
    check(await ev(`(() => { LE2E.memo.clear(); const o = {id: 1, list_id: ${L}, title: ${JSON.stringify(cT)}}; le2eNorm(o, null); LE2E.q.clear(); return o.title === '' && o._le2e === 'locked' && o._enc.title === ${JSON.stringify(cT)}; })()`), 'not opened yet: "" + _le2e locked');
    await ev(`(LE2E.memo.clear(), load().then(() => 1))`);
    check(await waitFor(`S.tasks.get(${T}).title === '${M} task title' && !S.tasks.get(${T})._le2e`), 'the background decryption fills it in');
    // outgoing: PATCH and POST through api(), a comment through rawFetch
    await ev(`api('PATCH', '/api/tasks/${T}', {title: '${M} renamed'}).then(j => (putTask(j), 1))`);
    let st = (await call('GET', '/api/state')).j;
    let row = (st.tasks || []).find(t => t.id === T);
    check(row && row.title.startsWith('e2e1:') && !row.title.includes(M) && await ev(`S.tasks.get(${T}).title === '${M} renamed'`), 'outgoing: a changed title reaches the server as a cipher');
    const T3 = await ev(`api('POST', '/api/tasks', {title: '${M} new', list_id: ${L}}).then(j => (putTask(j), j.id))`);
    st = (await call('GET', '/api/state')).j;
    check(((st.tasks || []).find(t => t.id === T3)?.title || '').startsWith('e2e1:'), 'outgoing: a new task of the locked list is created encrypted');
    await ev(`rawFetch('POST', '/api/tasks/${T}/comments', {body: '${M} hello <@${BOB}>'}).then(() => 1)`);
    const tl = (await call('GET', `/api/tasks/${T}/timeline`)).j;
    check((tl.comments || []).length === 1 && tl.comments[0].body.startsWith('e2e1:') && !tl.comments[0].body.includes(M), 'outgoing: a comment is encrypted');
    // offline: the outbox holds ciphers only, the screen the plain text; _prev is the cipher the server holds
    await ev(`(window.__f0 = window.fetch, window.fetch = () => Promise.reject(new TypeError('offline')), 1)`);
    await ev(`api('PATCH', '/api/tasks/${T}', {title: '${M} offline'}).then(() => 1, () => 1)`);
    const ob = await ev(`(() => { const q = JSON.parse(localStorage.getItem('tasks.outbox') || '[]'); const e = q.find(x => x.url === '/api/tasks/${T}'); return e ? {t: e.body.title, p: e.body._prev?.title} : null; })()`);
    check(ob && ob.t.startsWith('e2e1:') && ob.p === row.title, 'H1: the outbox holds the cipher, _prev = the cipher on the server ' + JSON.stringify(ob));
    check(await ev(`S.tasks.get(${T}).title === '${M} offline'`), 'offline: the screen shows the plain text');
    await ev(`(LS.set('cache', {tasks: [...S.tasks.values()], lists: S.lists}), LS.set('probe', [{id: -5, list_id: ${L}, title: '${M} unsent', content: ''}]), 1)`);
    const cache = await ev(`localStorage.getItem('tasks.cache') || ''`);
    check(cache.includes('e2e1:') && !cache.includes(M), 'H1: the offline cache holds ciphers only');
    check(!(await sweep()), 'H1: no localStorage entry holds a plain text of the locked list ' + await sweep());
    await ev(`(window.fetch = window.__f0, flush().then(() => 1))`);
    st = (await call('GET', '/api/state')).j;
    check(await waitFor(`!OUT.q.length`) && ((st.tasks || []).find(t => t.id === T)?.title || '').startsWith('e2e1:'), 'offline change sent encrypted once online');
    // search: locked lists are searched in this page
    check(await ev(`le2eSearch('${M} offline', []).some(t => t.id === ${T})`), 'M7: the local search finds the task of the locked list');
    // moving out: texts + comments in plain text (le2e_move); moving in: ciphers
    const mv = await ev(`(async () => { const t = S.tasks.get(${T}); t.comment_count = 1; const b = await le2eOut('PATCH', '/api/tasks/${T}', {list_id: ${L2}});
      return {title: b.title, move: b.le2e_move}; })()`);
    check(mv.title === `${M} offline` && mv.move?.tasks?.[0]?.title === `${M} offline` && (mv.move?.comments || [])[0]?.body === `${M} hello <@${BOB}>`, 'M8: moving out carries the plain texts and comments ' + JSON.stringify(mv).slice(0, 300));
    const mi = await ev(`le2eOut('PATCH', '/api/tasks/${T2}', {list_id: ${L}}).then(b => ({title: b.title, m: b.le2e_move?.tasks?.[0]?.title}))`);
    check(mi.title?.startsWith('e2e1:') && mi.m === mi.title, 'M8: moving in encrypts the texts for the target list');
    // no key: no text leaves
    const lk = await ev(`(async () => { const k = LE2E.keys[${L}]; LE2E.keys[${L}] = {}; LE2E.tried[${L}] = '1'; try { await le2eOut('PATCH', '/api/tasks/${T}', {title: 'x'}); return 'sent'; } catch (e) { return e.code; } finally { LE2E.keys[${L}] = k; } })()`);
    check(lk === 'list_e2e_locked', 'without the list key a text is refused ("unlock first") ' + lk);
    // lock: nothing readable stays in the page
    check(await ev(`(e2eLock(), (() => { const t = S.tasks.get(${T}); return t.title === '' && t._le2e === 'locked' && !LE2E.memo.size && !Object.keys(LE2E.keys).length; })())`), 'lock: plain texts and keys wiped');
  });

  if (!hasA) { console.log('p264a_c_ui: part A routes missing, end-to-end cases skipped'); }
  else {
    // ---------------------------------------------------------------- end to end with part A
    const L3 = (await call('POST', '/api/lists', {name: 'Shared locked'})).j.id;
    await call('PUT', `/api/lists/${L3}/members`, {user_id: BOB, role: 'edit'});
    const TT = (await call('POST', '/api/tasks', {title: `${M} shared task`, list_id: L3, content: `${M} shared notes`})).j.id;
    await session('bob', async ({ev}) => {
      check(await ev(`e2eCreate(${JSON.stringify(PASS_B)}).then(c => !!c)`), 'Bob sets up encryption');
    });
    await session('alice', async ({ev, waitFor, boot, sweep}) => {
      await ev(`(async () => { await e2eLoad(true); await e2eAdopt(await e2eUnwrapPass(E2E.st.bundle_pass, ${JSON.stringify(PASS)})); return 1; })()`);
      const pr = await ev(`(async () => { const p = []; await le2eStart(${L3}, x => p.push(x)); return p; })()`);
      check(Array.isArray(pr) && pr.length && pr[pr.length - 1].done === pr[pr.length - 1].total, 'le2eStart: switched on with progress ' + JSON.stringify(pr));
      const st = (await call('GET', '/api/state')).j, row = (st.tasks || []).find(t => t.id === TT), l = (st.lists || []).find(x => x.id === L3);
      check(l?.e2e === 'on' && row?.title.startsWith('e2e1:') && row?.content.startsWith('e2e1:'), 'the server keeps ciphers only');
      await boot('#l/' + L3);
      check(await waitFor(`S.tasks.get(${TT})?.title === '${M} shared task'`), 'Alice reads the task after a reload');
      check(!(await sweep()), 'H1 end to end: localStorage holds no plain text ' + await sweep());
    });
    await session('bob', async ({ev, waitFor}) => {
      await ev(`(async () => { await e2eLoad(true); await e2eAdopt(await e2eUnwrapPass(E2E.st.bundle_pass, ${JSON.stringify(PASS_B)})); return 1; })()`);
      check(await ev(`le2eUnlock(${L3})`), 'Bob unlocks the list with his own key');
      check(await waitFor(`S.tasks.get(${TT})?.title === '${M} shared task'`), 'Bob reads the task');
    });
    await session('alice', async ({ev}) => {
      await ev(`(async () => { await e2eLoad(true); await e2eAdopt(await e2eUnwrapPass(E2E.st.bundle_pass, ${JSON.stringify(PASS)})); return 1; })()`);
      check(await ev(`le2eStop(${L3}, 'password123', () => {}).then(r => !!r)`), 'le2eStop: switched off');
      const st = (await call('GET', '/api/state')).j, row = (st.tasks || []).find(t => t.id === TT);
      check(row?.title === `${M} shared task` && !(st.lists || []).find(x => x.id === L3)?.e2e, 'the texts are plain on the server again');
    });
  }

  console.log(`p264a_c_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
