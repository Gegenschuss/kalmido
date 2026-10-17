// 2.64.1 part C (#1817): the lock per list -- client data layer (static/js/liste2e.js), own container (start.sh), Firefox (real
// WebCrypto). Without the server routes (part A) the client is driven with a list key set in the page:
// - field crypto: "e2e1:" + {v, g, iv, ct}, padding to 64 bytes (L1), the AAD binds list, generation and field
// - list keys: wrapping between two key pairs (ECDH + HKDF), my own wrap uses my own key (never the server's copy), a changed key of
//   another person is not used until confirmed (H4)
// - incoming ciphers become plain texts in memory (_enc keeps the ciphers), outgoing texts leave encrypted (task, comment)
// - H1: offline outbox and every localStorage entry hold ciphers only (sweep for a marker); lock = wipe
// - moving a task out of a locked list carries its texts, its comments in the target format (le2e_move)
// With part A's routes also end to end: Bob sets up encryption, Alice switches the lock on (le2eStart), the server
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
    // list L locked with a key of generation 1: with part A switched on for real (le2eStart), else a key set in the page
    await ev(`(window.__raw = crypto.getRandomValues(new Uint8Array(32)), 1)`);  // the raw key of the wrapping cases
    if (hasA) check(await ev(`le2eStart(${L}, () => {}).then(r => !!r && listById(${L})?.e2e === 'on' && le2eReady(${L}) && listById(${L}).e2e_gen === 1)`), 'le2eStart on an own list (part A)');
    else await ev(`(async () => {
      LE2E.keys[${L}] = {1: await le2eImport(window.__raw.slice())};
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

    await ev(`(histFields('t', [[{id: 1, list_id: ${L}, title: '${M} undo'}, {id: 1, list_id: ${L}, title: 'x'}]], {fields: ['title']}), 1)`);  // an undo step of the locked list
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
    // sections, notes (note_title / note_body), text fields
    const FID = (await call('POST', `/api/lists/${L}/fields`, {name: 'Memo', type: 'text'})).j.id;
    await ev(`api('POST', '/api/sections', {list_id: ${L}, name: '${M} section'}).then(() => load()).then(() => 1, e => e.message)`);
    const secs = ((await call('GET', '/api/state')).j.sections || []).filter(x => x.list_id === L);
    check(secs.length === 1 && secs[0].name.startsWith('e2e1:') && await waitFor(`(S.sections || []).some(x => x.list_id === ${L} && x.name === '${M} section')`), 'a section name is encrypted on the server, plain in the page ' + JSON.stringify(secs).slice(0, 120));
    await ev(`rawFetch('POST', '/api/lists/${L}/notes', {title: '${M} note', body: '${M} note body'}).then(() => 1)`);
    const ns = (await call('GET', `/api/lists/${L}/notes`)).j.notes || [];
    check(ns.length === 1 && ns[0].title.startsWith('e2e1:') && ns[0].body.startsWith('e2e1:'), 'a note: title and body encrypted');
    const NN = await ev(`(LE2E.memo.clear(), rawFetch('GET', '/api/lists/${L}/notes')).then(async j => { for (let i = 0; i < 40 && j.notes[0]._le2e; i++) await new Promise(r => setTimeout(r, 100)); return j.notes[0].title + '|' + j.notes[0].body; })`);
    check(NN === `${M} note|${M} note body`, 'a note opens in the page (its own AAD fields) ' + NN);
    await ev(`load().then(() => api('PATCH', '/api/tasks/${T}', {fields: {${FID}: '${M} field'}})).then(j => (putTask(j), 1))`);
    const fv = (((await call('GET', '/api/state')).j.tasks || []).find(t => t.id === T)?.fields || {})[FID];
    check(String(fv || '').startsWith('e2e1:') && await waitFor(`S.tasks.get(${T}).fields[${FID}] === '${M} field'`), 'a text field value is encrypted, plain in the page ' + String(fv).slice(0, 40));
    // offline: the outbox holds ciphers only, the screen the plain text; _prev is the cipher the server holds
    await ev(`(window.__f0 = window.fetch, window.fetch = () => Promise.reject(new TypeError('offline')), 1)`);
    await ev(`api('PATCH', '/api/tasks/${T}', {title: '${M} offline'}).then(() => 1, () => 1)`);
    const ob = await ev(`(() => { const q = JSON.parse(localStorage.getItem('tasks.outbox') || '[]'); const e = q.find(x => x.url === '/api/tasks/${T}'); return e ? {t: e.body.title, p: e.body._prev?.title} : null; })()`);
    check(ob && ob.t.startsWith('e2e1:') && ob.p === row.title, 'H1: the outbox holds the cipher, _prev = the cipher on the server ' + JSON.stringify(ob));
    check(await ev(`S.tasks.get(${T}).title === '${M} offline'`), 'offline: the screen shows the plain text');
    await ev(`(S.tasks.get(${T3}).content = '${M} typed', 1)`);  // typed here, no cipher yet
    await ev(`(LS.set('cache', {tasks: [...S.tasks.values()], lists: S.lists, sections: S.sections}), LS.set('probe', [{id: -5, list_id: ${L}, title: '${M} unsent', content: ''}]), 1)`);
    const cache = await ev(`localStorage.getItem('tasks.cache') || ''`);
    check(cache.includes('e2e1:') && !cache.includes(M), 'H1: the offline cache holds ciphers only');
    check(!(await sweep()), 'H1: no localStorage entry holds a plain text of the locked list ' + await sweep());
    await ev(`(window.fetch = window.__f0, flush().then(() => 1))`);
    st = (await call('GET', '/api/state')).j;
    check(await waitFor(`!OUT.q.length`) && ((st.tasks || []).find(t => t.id === T)?.title || '').startsWith('e2e1:'), 'offline change sent encrypted once online');
    // search: locked lists are searched in this page
    check(await ev(`le2eSearch('${M} offline', []).some(t => t.id === ${T})`), 'M7: the local search finds the task of the locked list');
    // 2.64.1 review 2 (M1): a task outside S.tasks (done / trash view, search result) or not on the page at all: its texts leave encrypted
    const m1 = await ev(`(async () => { const t = S.tasks.get(${T3}), out = {}; S.tasks.delete(${T3}); S.extra = [t];
      try {
        out.extra = (await le2eOut('PATCH', '/api/tasks/${T3}', {title: '${M} done view'})).title;
        out.cmt = (await le2eOut('POST', '/api/tasks/${T3}/comments', {body: '${M} c'})).body;
        S.extra = null; LE2E.got.clear();
        out.fetched = (await le2eOut('PATCH', '/api/tasks/${T3}', {title: '${M} unknown'})).title;
        LE2E.got.clear();
        out.batch = (await le2eOut('POST', '/api/tasks/batch', {action: 'patch', ids: [${T3}], data: {title: '${M} b'}})).data.title;
      } catch (e) { out.err = e.message; } finally { S.tasks.set(${T3}, t); S.extra = null; LE2E.got.clear(); }
      return out; })()`);
    check(['extra', 'cmt', 'fetched', 'batch'].every(k => String(m1[k] || '').startsWith('e2e1:')), 'review 2 (M1): done view / unknown task / batch: texts leave encrypted ' + JSON.stringify(m1).slice(0, 200));
    // moving out: texts + comments in plain text (le2e_move); moving in: ciphers
    const mv = await ev(`(async () => { const t = S.tasks.get(${T}); t.comment_count = 1; const b = await le2eOut('PATCH', '/api/tasks/${T}', {list_id: ${L2}});
      return {title: b.title, move: b.le2e_move}; })()`);
    check(mv.title === `${M} offline` && mv.move?.tasks?.[0]?.title === `${M} offline` && (mv.move?.comments || [])[0]?.body === `${M} hello <@${BOB}>`, 'M8: moving out carries the plain texts and comments ' + JSON.stringify(mv).slice(0, 300));
    const mi = await ev(`le2eOut('PATCH', '/api/tasks/${T2}', {list_id: ${L}}).then(b => ({title: b.title, m: b.le2e_move?.tasks?.[0]?.title}))`);
    check(mi.title?.startsWith('e2e1:') && mi.m === mi.title, 'M8: moving in encrypts the texts for the target list');
    // a subtask in the trash is not in the page: the server names it (need), le2eFix fetches and converts it
    const cS = await ev(`le2eEnc(${L}, 'title', '${M} trashed sub')`);
    const TS = (await call('POST', '/api/tasks', {title: cS, list_id: L, parent_id: T})).j.id;
    await call('DELETE', `/api/tasks/${TS}`);
    const fx = await ev(`le2eFix('/api/tasks/${T}', {list_id: ${L2}, le2e_move: {tasks: [], comments: [], fields: []}}, {tasks: [${TS}], comments: [], fields: []}).then(b => b && b.le2e_move.tasks.find(x => x.id === ${TS})?.title, e => 'ERR ' + e.message)`);
    check(fx === `${M} trashed sub`, 'M8: a missing subtask (trash) is fetched and sent in the target format ' + fx);
    // 2.64.1 review 2 (M2): a text that does not open with the list key held here is counted (the UI says so), not silently kept
    const m2 = await ev(`(async () => { const k = await crypto.subtle.generateKey({name: 'AES-GCM', length: 256}, false, ['encrypt', 'decrypt']);
      const b = await e2eSeal(k, le2ePad(e2eTEnc().encode('x')), le2eAad(${L}, listById(${L}).e2e_gen, 'title')), c = 'e2e1:' + JSON.stringify({v: 1, g: listById(${L}).e2e_gen, iv: b.iv, ct: b.ct});
      le2eWait(c, ${L}, ['title']); await le2eDrain(); return le2eUnreadable(${L}); })()`);
    check(m2 === 1, 'review 2 (M2): a swapped / foreign cipher is counted as unreadable ' + m2);
    // 2.64.1 review 2 (L5): a typed "e2e1:..." is a text: encrypted in a locked list, a clear message in an open one (never sent)
    const l5 = await ev(`(async () => { const c = await le2eEnc(${L}, 'title', 'e2e1: not a cipher'); let msg = '';
      try { await le2eOut('PATCH', '/api/tasks/${T2}', {title: 'e2e1: typed'}); } catch (e) { msg = e.code; }
      return {enc: c !== 'e2e1: not a cipher' && !!le2eParse(c), msg}; })()`);
    check(l5.enc && l5.msg === 'list_e2e_prefix', 'review 2 (L5): "e2e1:" typed by a person ' + JSON.stringify(l5));
    // no key: no text leaves
    const lk = await ev(`(async () => { const k = LE2E.keys[${L}]; LE2E.keys[${L}] = {}; LE2E.tried[${L}] = '1'; try { await le2eOut('PATCH', '/api/tasks/${T}', {title: 'x'}); return 'sent'; } catch (e) { return e.code; } finally { LE2E.keys[${L}] = k; } })()`);
    check(lk === 'list_e2e_locked', 'without the list key a text is refused ("unlock first") ' + lk);
    // lock: nothing readable stays in the page
    check(await ev(`(e2eLock(), (() => { const t = S.tasks.get(${T}); return t.title === '' && t._le2e === 'locked' && !LE2E.memo.size && !Object.keys(LE2E.keys).length && !JSON.stringify(HIST.undo).includes('${M}') && !JSON.stringify(HIST.redo).includes('${M}'); })())`), 'lock: plain texts, keys and undo steps of the list wiped');
  });

  check(hasA, 'the server has the lock routes (part A)');
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
      await ev(`(async () => { await e2eLoad(true); await e2eAdopt(await e2eUnwrapPass(E2E.st.bundle_pass, ${JSON.stringify(PASS)})); await le2eUnlock(${L3}); return 1; })()`);  // keys not remembered on this device
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
