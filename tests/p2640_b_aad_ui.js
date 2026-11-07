// 2.640.0 part B (#3388): E2E record binding (AAD v2) of the knowledge pages and the list channel, own container (start.sh),
// kalmido-suite: fresh
// Firefox (real WebCrypto). Alice alone in her private knowledge space and in the channel of a locked list (Bob is a member
// without encryption, so no safety number dialog comes up):
// - written is v 2: switching the lock on, a new page (id reserved first), a new / edited channel message, the conversion
// - an old v 1 page / message (an app from before 2.640) still opens
// - a cipher the server puts under another page / message does not open there (nor a v 2 cipher relabelled as v 1)
// - another message arriving between reservation and send: the browser encrypts once more with a new id (409 chan_resv_stale)
// - the key change lifts every page / message (also the v 1 ones) to v 2 in the new generation
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2640_b_aad_ui', check, shots: 'P2640B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.BASE) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, j: await r.json().catch(() => ({}))}; };
const PASS = 'correct horse battery staple';
const M = 'ZQYaad';  // every plain text carries it: no server row may hold it
const SP = 'private';
const cip = v => (typeof v === 'string' && v.startsWith('e2e1:')) ? JSON.parse(v.slice(5)) : null;

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const st = (await call('GET', '/api/state')).j;
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: [...(st.settings?.features || '').split(',').filter(Boolean), 'wiki', 'collab'].join(',')});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).j.id;
  const L = (await call('POST', '/api/lists', {name: 'Bound chat'})).j.id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: BOB, role: 'edit'});
  const RID = ((await call('GET', '/api/team')).j.rooms || []).find(x => x.list_id === L)?.id;
  check(!!RID, 'setup: the channel of the shared list');
  const P0 = (await call('POST', '/api/wiki/pages', {space: SP, path: 'Plain before', body: `${M} plain before the lock`})).j.id;
  check(P0 > 0, 'setup: a plain page before the lock');
  const rows = async () => (await call('GET', `/api/team/rooms/${RID}/messages`)).j.messages || [];
  const pages = async () => (await call('GET', '/api/wiki?space=' + SP + '&bodies=1')).j.pages || [];

  await firefox(async ({cmd, ev, nav, ctx}) => {
    const waitFor = async (expr, n = 80) => { for (let i = 0; i < n; i++) { const v = await ev(expr).catch(() => null); if (v) return v; await sleep(250); } return null; };
    const boot = async hash => { await nav(B + 'static/icon.svg'); await nav(B + hash); await waitFor('!!(window.S && S.booted)'); await sleep(500); };
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.wkSpace', ${JSON.stringify(JSON.stringify(SP))}); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await boot('#inbox');
    const unlock = () => ev(`(async () => { await e2eLoad(true); await e2eAdopt(await e2eUnwrapPass(E2E.st.bundle_pass, ${JSON.stringify(PASS)})); return e2eUnlocked(); })()`);
    check(await ev(`e2eCreate(${JSON.stringify(PASS)}).then(c => !!c && e2eUnlocked())`), 'Alice sets up encryption');

    // ================================================================ knowledge pages
    const on = await ev(`wkeStart(${JSON.stringify(SP)}, () => {}).then(r => ({r, mode: wkeMode(${JSON.stringify(SP)})}), e => ({err: e.message}))`);
    check(on.r === true && on.mode === 'on', 'wiki: the private space is locked ' + JSON.stringify(on));
    let ps = await pages(), p0 = ps.find(x => x.id === P0);
    check(cip(p0?.path)?.v === 2 && cip(p0?.body)?.v === 2 && !JSON.stringify(ps).includes(M), 'wiki: switching on writes v 2 (path and text)');
    // a page of an app from before 2.640: v 1 ciphers, no reservation
    const P1 = await ev(`(async () => { const sp = ${JSON.stringify(SP)}, s = WKE.st[sp], key = WKE.keys[sp][s.gen];
      const seal = async (f, t) => { const b = await e2eSeal(key, le2ePad(e2eTEnc().encode(t)), wkeAad(s.space_id, s.gen, f)); return 'e2e1:' + JSON.stringify({v: 1, g: s.gen, iv: b.iv, ct: b.ct}); };
      return (await rawFetch('POST', '/api/wiki/pages', {space: sp, path: await seal('path', 'Old app'), body: await seal('body', '${M} old app text')})).id; })().catch(e => 'ERR ' + e.message)`);
    check(P1 > 0, 'wiki: a v 1 page of an older app is still taken ' + P1);
    const mk = await ev(`(async () => { const sp = ${JSON.stringify(SP)}; await wk_load(sp, true);
      const a = await wkeCreate(sp, 'Bound A', 0, '${M} text A'); await wk_load(sp, true); const b = await wkeCreate(sp, 'Bound B', 0, '${M} text B');
      return {a: a.id, b: b.id, ab: a.body}; })().catch(e => ({err: e.message}))`);
    check(mk.a > 0 && mk.b > 0 && mk.ab === `${M} text A`, 'wiki: two new pages ' + JSON.stringify(mk));
    ps = await pages();
    const pa = ps.find(x => x.id === mk.a), pb = ps.find(x => x.id === mk.b);
    check(cip(pa?.path)?.v === 2 && cip(pa?.body)?.v === 2 && cip(pb?.body)?.v === 2, 'wiki: a new page is written as v 2 (under its reserved id)');
    const rd = await ev(`(async () => { const sp = ${JSON.stringify(SP)}; WKE.memo.clear(); await wk_load(sp, true);
      const one = async id => (await wkePage(await rawFetch('GET', '/api/wiki/pages/' + id))).body;
      return {paths: wk_pages(sp).map(x => x.path).sort(), old: await one(${P1}), a: await one(${mk.a}), p0: await one(${P0})}; })().catch(e => ({err: e.message}))`);
    check(rd.old === `${M} old app text` && rd.a === `${M} text A` && rd.p0 === `${M} plain before the lock` && ['Bound A', 'Bound B', 'Old app', 'Plain before'].every(x => (rd.paths || []).includes(x)),
      'wiki: v 2 pages and the v 1 page open ' + JSON.stringify(rd).slice(0, 300));
    // the server puts the cipher of page A under page B (the server takes the shape only): B does not open, A's text never shows there
    check((await call('PATCH', `/api/wiki/pages/${mk.b}`, {body: pa.body})).status === 200, 'setup: the server stores A\'s cipher at page B');
    const sw = await ev(`(async () => { const p = await wkePage(await rawFetch('GET', '/api/wiki/pages/${mk.b}')); return {wke: p._wke || null, body: p.body}; })().catch(e => ({err: e.message}))`);
    check(sw.wke === 'locked' && !String(sw.body || '').includes('text A'), 'wiki: a cipher moved to another page does not open (even with A opened in this page before) ' + JSON.stringify(sw));
    // a v 2 cipher relabelled as v 1 (no page id in the AAD): does not open either - no way down
    const down = 'e2e1:' + JSON.stringify({...cip(pa.body), v: 1});
    check((await call('PATCH', `/api/wiki/pages/${mk.b}`, {body: down})).status === 200, 'setup: the cipher relabelled as v 1 at page B');
    const dn = await ev(`(async () => { const p = await wkePage(await rawFetch('GET', '/api/wiki/pages/${mk.b}')); return {wke: p._wke || null, body: p.body}; })().catch(e => ({err: e.message}))`);
    check(dn.wke === 'locked' && !String(dn.body || '').includes('text A'), 'wiki: a v 2 cipher relabelled as v 1 does not open ' + JSON.stringify(dn));
    // B gets a proper text again (an edit is v 2 with its own id)
    const fx = await ev(`wkeApi('PATCH', '/api/wiki/pages/${mk.b}', {body: '${M} text B again'}, ${JSON.stringify(SP)}).then(r => r.body, e => 'ERR ' + e.message)`);
    ps = await pages();
    check(fx === `${M} text B again` && cip(ps.find(x => x.id === mk.b)?.body)?.v === 2, 'wiki: an edit writes v 2 ' + fx);
    // the key change: every page in generation 2 and v 2 (also the old v 1 page)
    const rot = await ev(`(async () => { const sp = ${JSON.stringify(SP)}; const r = await wkeRotate(sp, true); const e = await wkeReenc(sp); WKE.memo.clear(); await wk_load(sp, true);
      return {r, e, old: (await wkePage(await rawFetch('GET', '/api/wiki/pages/${P1}'))).body, n: wk_pages(sp).length}; })().catch(e => ({err: e.message}))`);
    ps = await pages();
    const cs = ps.flatMap(x => [x.path, x.body]).map(cip).filter(Boolean);
    check(rot.r === true && rot.e === true && rot.old === `${M} old app text` && rot.n >= 4, 'wiki: key change and re-encryption, the old page opens ' + JSON.stringify(rot).slice(0, 300));
    check(cs.length >= 8 && cs.every(x => x.v === 2 && x.g === 2), 'wiki: after the key change every cipher is v 2 of generation 2 ' + JSON.stringify(cs.map(x => [x.v, x.g])));

    // ================================================================ the list channel
    check(await ev(`le2eStart(${L}, () => {}).then(r => !!r && listById(${L})?.e2e === 'on')`), 'channel: the list is locked');
    await boot('#team/' + RID);
    check(await waitFor(`S.tc.room?.id === ${RID} && le2eChanOn(S.tc.room)`), 'channel: the room knows the lock of its list');
    await unlock();
    await ev(`(async () => { await le2eKeys(${L}, true); return 1; })()`);
    // a message of an app from before 2.640: v 1, no reservation
    const V1 = await ev(`(async () => { const room = S.tc.room, g = listById(${L}).e2e_gen, key = await le2eChanKey(${L}, g);
      const b = await e2eSeal(key, le2ePad(e2eTEnc().encode('${M} old message')), le2eChanAad(room.id, g, S.me.id));
      return (await rawFetch('POST', '/api/team/rooms/${RID}/messages', {enc: {v: 1, g, iv: b.iv, ct: b.ct}})).id; })().catch(e => 'ERR ' + e.message)`);
    check(V1 > 0, 'channel: a v 1 message of an older app is still taken ' + V1);
    const send = async t => { await ev(`(() => { const ta = document.querySelector('#tc-in'); ta.value = '${M} ${t}'; return 1; })()`); await ev(`tcSend().then(() => 1)`);
      return waitFor(`(S.tc.msgs || []).find(m => m.body === '${M} ${t}')?.id || 0`); };
    const MA = await send('message A'), MB = await send('message B');
    let ms = await rows();
    const ma = ms.find(x => x.id === MA), mb = ms.find(x => x.id === MB);
    check(MA > V1 && MB > MA && ma?.enc?.v === 2 && mb?.enc?.v === 2 && !JSON.stringify(ms).includes(M), 'channel: tcSend writes v 2 under the reserved id ' + JSON.stringify([MA, MB, ma?.enc?.v]));
    const dec = async () => ev(`(async () => { await loadRoom(${RID}); S.tc.msgs.forEach(m => { delete m._dec; delete m._fail; }); for (const k in E2E.dec) delete E2E.dec[k];
      await le2eChanDecrypt(${RID}); return Object.fromEntries(S.tc.msgs.map(m => [m.id, m._fail ? 'FAIL' : m._dec ? m.body : '?'])); })().catch(e => ({err: e.message}))`);
    let d = await dec();
    check(d[V1] === `${M} old message` && d[MA] === `${M} message A` && d[MB] === `${M} message B`, 'channel: v 2 messages and the v 1 message open ' + JSON.stringify(d));
    // the server puts the cipher of A under B (same sender, same room): B does not open
    check((await call('PATCH', `/api/team/messages/${MB}`, {enc: ma.enc})).status === 200, 'setup: the server stores A\'s cipher at message B');
    d = await dec();
    check(d[MB] === 'FAIL' && d[MA] === `${M} message A`, 'channel: a cipher moved to another message does not open ' + JSON.stringify(d));
    check((await call('PATCH', `/api/team/messages/${MB}`, {enc: {...ma.enc, v: 1}})).status === 200, 'setup: A\'s cipher relabelled as v 1 at message B');
    d = await dec();
    check(d[MB] === 'FAIL', 'channel: a v 2 cipher relabelled as v 1 does not open ' + JSON.stringify(d));
    // an edit (chat.js tcEditSave: le2eChanEnc with the message id) is v 2 with its own id
    const ed = await ev(`(async () => { const enc = await le2eChanEnc(S.tc.room, '${M} message B edited', ${MB}); return {extra: Object.keys(enc).join(','), r: (await rawFetch('PATCH', '/api/team/messages/${MB}', {enc})).enc?.v}; })().catch(e => ({err: e.message}))`);
    d = await dec();
    check(ed.r === 2 && ed.extra === 'v,g,iv,ct' && d[MB] === `${M} message B edited`, 'channel: an edit writes v 2 and opens ' + JSON.stringify([ed, d[MB]]));
    // another message arrives between the reservation and the send: one more encryption with a new id, the room keeps its order
    const race = await ev(`(async () => { const room = S.tc.room, real = rawFetch, g = listById(${L}).e2e_gen, key = await le2eChanKey(${L}, g); let between = 0, posts = 0;
      window.rawFetch = async (m, u, b) => {
        if (m === 'POST' && u.endsWith('/messages') && b?.msg_id) {
          posts++;
          if (!between) { const x = await e2eSeal(key, le2ePad(e2eTEnc().encode('${M} between')), le2eChanAad(room.id, g, S.me.id)); between = (await real('POST', u, {enc: {v: 1, g, iv: x.iv, ct: x.ct}})).id; }
        }
        return real(m, u, b);
      };
      try { const t = '${M} after the race'; const r = await le2eChanPost(room, t)('POST', '/api/team/rooms/${RID}/messages', {enc: await le2eChanEnc(room, t), client_id: 'race-1'}); return {id: r.id, v: r.enc?.v, between, posts}; }
      finally { window.rawFetch = real; } })().catch(e => ({err: e.message, code: e.data?.code}))`);
    d = await dec();
    check(race.posts === 2 && race.id > race.between && race.v === 2 && d[race.id] === `${M} after the race`, 'channel: 409 chan_resv_stale -> encrypted again with a new id ' + JSON.stringify(race));
    // the conversion after a key change: every message (also the v 1 ones) v 2 of the new generation
    const lr = await ev(`(async () => { const r = await le2eRotate(${L}, true); const e = await le2eReenc(${L}); return {r, e, gen: listById(${L})?.e2e_gen}; })().catch(e => ({err: e.message}))`);
    ms = (await rows()).filter(x => x.enc && !x.enc.sys && !x.deleted);
    check(lr.r === true && lr.gen === 2 && ms.length >= 5 && ms.every(x => x.enc.v === 2 && x.enc.g === 2), 'channel: after the key change every message is v 2 of generation 2 ' + JSON.stringify([lr, ms.map(x => [x.id, x.enc.v, x.enc.g])]).slice(0, 400));
    d = await dec();
    check(d[V1] === `${M} old message` && d[MA] === `${M} message A` && d[MB] === `${M} message B edited`, 'channel: after the key change the messages open ' + JSON.stringify(d));
  }, false);

  console.log(`p2640_b_aad_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
