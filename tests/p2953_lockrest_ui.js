// kalmido-suite: fresh
// 2.953 (#3348): the rest of the locked folders in the browser -- own container (start.sh), Firefox (real WebCrypto), as a person
// uses it:
// - the name search of a locked folder finds a file in a subfolder; its row shows the folder it lies in
// - a folder WITH content moves into the locked folder (one question): every id stays, the server keeps ciphers only, the helper
//   folder is gone, the view shows the plain names; and out again: plain names and the plain bytes on the server
// - a person whose share is taken back: the owner's browser changes the folder key on opening it (a new generation, the file
//   encrypted again with it) and the file still opens
// bob's key pair is made here in Node (a real P-256 point: alice's browser wraps the folder key for it)
const path = require('path');
const {execFileSync} = require('child_process');
const {webcrypto} = require('crypto');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2953_lockrest_ui', check, shots: 'P2953_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2953_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, j: await r.json().catch(() => ({}))}; };
const PASS = 'a long passphrase for alice';
const b64 = n => Buffer.from(webcrypto.getRandomValues(new Uint8Array(n))).toString('base64');
const upload = async (parent, name, text) => {
  const fd = new FormData(); fd.append('parent_id', String(parent)); fd.append('file', new Blob([text], {type: 'text/plain'}), name);
  const r = await fetch(B + 'api/files/upload', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
  return (await r.json()).items?.[0]?.id;
};
const folder = async (name, parent, space) => (await call('POST', '/api/files/folders', parent ? {name, parent_id: parent} : {name, space: space || 'private'})).j.id;
const kids = async id => ((await call('GET', `/api/files?parent=${id}`)).j.items || []);
const raw = async id => Buffer.from(await (await fetch(B + `api/files/nodes/${id}/content`, {headers: {Cookie: CK, 'X-Requested-With': 'kalmido'}})).arrayBuffer());

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Studio Example', lang: 'en', collab_all: true, modules: ['comments', 'collab']});
  const st = (await call('GET', '/api/state')).j;
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: [...new Set([...(st.settings?.features || '').split(','), 'files', 'collab'])].filter(Boolean).join(',')});
  const ORG = (await call('GET', '/api/state')).j.me.workspaces[0].id;  // the workspaces show with the feature collab
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com', orgs: [ORG]})).j.id;
  const CKB = await login('bob');
  const kp = await webcrypto.subtle.generateKey({name: 'ECDH', namedCurve: 'P-256'}, true, ['deriveBits']);
  const jwk = await webcrypto.subtle.exportKey('jwk', kp.publicKey);
  const put = await call('PUT', '/api/e2e/keys', {pub: {kty: 'EC', crv: 'P-256', x: jwk.x, y: jwk.y, ext: true, key_ops: []},
    bundle_pass: {v: 1, kdf: 'pbkdf2-sha256', iter: 600000, salt: b64(16), iv: b64(12), ct: b64(200)},
    bundle_rec: {v: 1, kdf: 'hkdf-sha256', salt: b64(16), iv: b64(12), ct: b64(200)}}, CKB);
  check(put.status < 300, 'setup: bob has a key pair ' + put.status);

  const BOX = await folder('Strongbox'), SUB = await folder('Deeper', BOX);
  await upload(SUB, 'deepnote.txt', 'ZQWdeep words');
  const OUT = await folder('Outside'), IN = await folder('Inside', OUT);
  const INF = await upload(IN, 'inner.txt', 'ZQWinner words'), TOPF = await upload(OUT, 'top.txt', 'ZQWtop words');
  const TEAM = await folder('Team box', null, `org:${ORG}`);
  const sh = await call('POST', `/api/files/nodes/${TEAM}/shares`, {user_id: BOB, role: 'view'});
  check(sh.status === 201 && sh.j.id, 'setup: the team box shared with bob');
  const kidsOf = async id => (await kids(id)).map(x => x.name);

  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    const waitFor = async (expr, n = 80) => { for (let i = 0; i < n; i++) { const v = await ev(expr).catch(() => null); if (v) return v; await sleep(250); } return null; };
    const boot = async hash => { await nav(B + 'static/icon.svg'); await nav(B + hash); await waitFor('!!(window.S && S.booted)'); };
    const unlock = () => ev(`(async () => { await e2eLoad(true); if (!e2eUnlocked()) await e2eAdopt(await e2eUnwrapPass(E2E.st.bundle_pass, ${JSON.stringify(PASS)})); return e2eUnlocked(); })()`);
    await nav(B + 'static/icon.svg');
    await ev('(() => { localStorage.clear(); return 1; })()');
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await boot('#ablage');
    check(await ev(`(async () => { await e2eLoad(true); return !!(await e2eCreate(${JSON.stringify(PASS)})) && e2eUnlocked(); })()`), 'alice sets up her encryption');
    await boot(`#ablage/${BOX}`);
    check(await unlock(), 'unlocked after the page load');
    await waitFor(`typeof fslStart === 'function'`);
    const r1 = await ev(`fslStart(${BOX}).then(x => ({x}), e => ({err: e.message}))`);
    check(r1 && r1.x === true, 'the strongbox is locked ' + JSON.stringify(r1));

    // ---- the name search covers the subfolders
    await boot(`#ablage/${BOX}`); await unlock(); await ev('ab_reload(), 1');
    check(await waitFor(`[...document.querySelectorAll('.abrow .abname')].map(x => x.textContent).includes('Deeper')`), 'the locked folder shows its subfolder by name');
    await ev(`(() => { const q = document.querySelector('#fsl-q'); q.value = 'deep'; q.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
    check(await waitFor(`(() => { const r = [...document.querySelectorAll('.abrow')].find(x => x.querySelector('.abname')?.textContent === 'deepnote.txt'); return !!r && r.textContent.includes('Deeper'); })()`),
      'the search finds the file in the subfolder, its row names the folder');
    await shot('p2953-search.png');
    await ev(`(() => { const q = document.querySelector('#fsl-q'); q.value = ''; q.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);

    // ---- a folder with content moves in (one question) and out again, every id kept
    // the one question is answered with its button (as a person does), the move runs on
    await ev(`(window.__mv = null, rawFetch('GET', '/api/files/nodes/${OUT}').then(n => fsl_moveHook(n, ${BOX})).then(x => { window.__mv = x; }, e => { window.__mv = 'err ' + e.message; }), 1)`);
    check(await waitFor(`!!document.querySelector('[data-cd="yes"]')`), 'one question before the move');
    await ev(`(document.querySelector('[data-cd="yes"]').click(), 1)`);
    const mv = await waitFor(`window.__mv`, 240);
    check(mv === true, 'the folder with content moved into the locked folder ' + mv);
    const inBox = await kids(BOX);
    check(inBox.length === 2 && inBox.some(x => x.id === OUT) && inBox.every(x => x.name.startsWith('e2e1:')), 'Outside lies in the box with its own id, no helper folder is left, ciphers only ' + inBox.map(x => x.name.slice(0, 8)).join(','));
    const inOut = await kids(OUT), inIn = await kids(IN);
    check(inOut.some(x => x.id === IN) && inOut.some(x => x.id === TOPF) && inIn.some(x => x.id === INF) && [...inOut, ...inIn].every(x => x.name.startsWith('e2e1:')),
      'the subfolder and the files kept their ids and have cipher names');
    const head = await raw(INF);
    check(head.subarray(0, 4).toString() === 'KENC' && !head.includes(Buffer.from('ZQWinner')), 'the file in the subfolder is stored encrypted');
    await boot(`#ablage/${BOX}`); await unlock(); await ev('ab_reload(), 1');
    check(await waitFor(`[...document.querySelectorAll('.abrow .abname')].map(x => x.textContent).includes('Outside')`), 'the view shows the moved folder by its name');
    await shot('p2953-moved-in.png');
    await ev(`(window.__mv = null, fsl_moveHook(AB.data.items.find(x => x.name === 'Outside'), null).then(x => { window.__mv = x; }, e => { window.__mv = 'err ' + e.message; }), 1)`);
    check(await waitFor(`!!document.querySelector('[data-cd="yes"]')`), 'one question before moving out');
    await ev(`(document.querySelector('[data-cd="yes"]').click(), 1)`);
    const back = await waitFor(`window.__mv`, 240);
    check(back === true, 'and out again to the top ' + back);
    check((await kidsOf(OUT)).sort().join() === 'Inside,top.txt' && (await kidsOf(IN)).join() === 'inner.txt', 'plain names on the server again, ids kept');
    check((await raw(INF)).toString() === 'ZQWinner words', 'the plain bytes on the server again');
    check((await kids(BOX)).length === 1, 'nothing left in the box but its subfolder');

    // ---- the key change after a share was taken back
    await boot(`#ablage/${TEAM}`); await unlock();
    const r2 = await ev(`fslStart(${TEAM}).then(x => ({x}), e => ({err: e.message}))`);
    check(r2 && r2.x === true, 'the team box is locked, the key wrapped for bob too ' + JSON.stringify(r2));
    check(((await call('GET', `/api/files/lock/${TEAM}`)).j.members || []).find(m => m.user_id === BOB)?.key_gens?.includes(1), 'bob holds generation 1');
    await ev(`(async () => { await fsl_upload([new File(['ZQWteam words'], 'team.txt', {type: 'text/plain'})], ${TEAM}, ${TEAM}); ab_reload(); return 1; })()`);  // the view of before the lock: the lock given
    check(await waitFor(`(AB.data?.items || []).some(x => x.name === 'team.txt')`), 'an encrypted file in the team box');
    check((await call('DELETE', `/api/files/shares/${sh.j.id}`)).status === 200, 'the share of bob taken back');
    check((await call('GET', `/api/files/lock/${TEAM}`)).j.rotate === 1, 'the folder asks its owner for a new key');
    await boot(`#ablage/${TEAM}`); await unlock();
    await ev('(FSL.auto = {}, ab_reload(), 1)');  // the owner opens the folder with her encryption unlocked (fsl_auto)
    const rk = await waitFor(`rawFetch('GET', '/api/files/lock/${TEAM}').then(j => j.gen === 2 && j.reenc === 0)`, 160);
    check(rk === true, 'opening the folder runs the key change and the encryption with the new key');
    const info = (await call('GET', `/api/files/lock/${TEAM}`)).j;
    check(info.gen === 2 && info.reenc === 0 && info.rotate === 0, 'a new generation, the files encrypted again ' + JSON.stringify({gen: info.gen, reenc: info.reenc, rotate: info.rotate}));
    const tf = (await kids(TEAM))[0];
    check(tf && JSON.parse(tf.name.slice(5)).g === 2 && (await raw(tf.id)).readUInt32BE(5) === 2, 'name and file of the new generation');
    await ev('ab_reload(), 1');
    check(await waitFor(`(AB.data?.items || []).some(x => x.name === 'team.txt')`), 'the view still shows the plain name');
    const txt = await ev(`(async () => { const n = AB.data.items.find(x => x.name === 'team.txt'); const f = await fslDec(n); return new TextDecoder().decode(f.data); })().catch(e => 'err ' + e.message)`);
    check(txt === 'ZQWteam words', 'the file still opens with the new key ' + txt);
    await shot('p2953-rekeyed.png');
  }, false);

  console.log(`p2953_lockrest_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
