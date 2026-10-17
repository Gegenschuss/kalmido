// 2.64.2 part B (#1817 stage 2): files of a list with the lock in the web app (static/js/liste2efile.js), own container (start.sh),
// Firefox (real WebCrypto):
// - switching the lock on encrypts an existing file (with part A's flow: le2eStart; alone: le2eFileConvert 'on'), the server keeps
//   KENC\x02 + a name cipher only, the browser opens the same bytes again
// - a file added in the detail (uploadFiles) and a comment file (sendComment) leave encrypted with the list key; the tile shows the
//   decrypted name; the per-person button of 2.42 is not offered; the head line (le2uAttHead) is there
// - a second member opens the file with his own key
// - the way back turns the list files into plain files with their names and types again
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p264b_b_ui', check, shots: 'P264BB_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.BASE) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, j: await r.json().catch(() => ({}))}; };
const PASS = 'correct horse battery staple', PASS_B = 'another horse battery staple';
const M = 'ZQXfile';  // every plain file text carries it: the server and localStorage must never hold it

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).j.id;
  const L = (await call('POST', '/api/lists', {name: 'Locked files'})).j.id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: BOB, role: 'edit'});
  const T = (await call('POST', '/api/tasks', {title: 'Papers', list_id: L})).j.id;
  const stateAtts = async () => ((await call('GET', '/api/state')).j.tasks || []).find(t => t.id === T)?.attachments || [];

  const session = (user, fn) => firefox(async ({cmd, ev, nav, ctx, shot}) => {
    const waitFor = async (expr, n = 80) => { for (let i = 0; i < n; i++) { const v = await ev(expr).catch(() => null); if (v) return v; await sleep(250); } return null; };
    const boot = async hash => { await nav(B + 'static/icon.svg'); await nav(B + hash); await waitFor('!!(window.S && S.booted)'); await sleep(500); };
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${user}', password: 'password123'})}).then(r => r.status)`) === 200, `Firefox: login ${user}`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await boot('#l/' + L);
    const sweep = () => ev(`Object.keys(localStorage).filter(k => (localStorage.getItem(k) || '').includes('${M}')).join(',')`);
    const unlock = pass => ev(`(async () => { await e2eLoad(true); await e2eAdopt(await e2eUnwrapPass(E2E.st.bundle_pass, ${JSON.stringify(pass)})); return 1; })()`);
    // the bytes of a file as the server keeps them, and opened with the list key
    const raw = aid => ev(`fetch('/api/attachments/${aid}?dl=1', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.arrayBuffer()).then(b => { const u = new Uint8Array(b); return String.fromCharCode(...u.subarray(0, 5)) + '|' + new TextDecoder('latin1').decode(u).includes('${M}'); })`);
    const open = aid => ev(`fetch('/api/attachments/${aid}?dl=1', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.arrayBuffer()).then(b => le2eFileDec(${L}, b)).then(f => f.name + '|' + f.type + '|' + new TextDecoder().decode(f.data), e => 'ERR ' + e.message)`);
    await fn({ev, waitFor, boot, shot, sweep, unlock, raw, open});
  }, false);

  await session('bob', async ({ev}) => {
    check(await ev(`e2eCreate(${JSON.stringify(PASS_B)}).then(c => !!c)`), 'Bob sets up encryption');
  });

  let P1, F1;
  await session('alice', async ({ev, waitFor, boot, shot, sweep, raw, open}) => {
    check(await ev(`e2eCreate(${JSON.stringify(PASS)}).then(c => !!c && e2eUnlocked())`), 'Alice sets up encryption');
    // a plain file before the lock
    P1 = await ev(`(async () => { const fd = new FormData(); fd.append('file', new File(['${M} before'], 'before.txt', {type: 'text/plain'}));
      const t = await rawFetch('POST', '/api/tasks/${T}/attachments', fd); return t.attachments[0].id; })()`);
    check(P1 > 0, 'a plain file before the lock ' + P1);
    const withA = 'reenc' in (await call('GET', `/api/lists/${L}/e2e`)).j;  // part A of stage 2 (the switch converts the files)
    check(await ev(`le2eStart(${L}, () => {}).then(r => !!r && listById(${L})?.e2e === 'on')`), 'le2eStart: the lock is on');
    let a = (await stateAtts()).find(x => x.id === P1);
    if (withA) check(a?.enc === 2, 'ZUSAMMENSPIEL: le2eStart encrypted the existing file ' + JSON.stringify(a));
    else if (a && a.enc !== 2) {  // without part A's flow: the conversion function itself (the background run of a list that is on)
      const cv = await ev(`le2eFileConvert(${L}, {id: ${P1}, task_id: ${T}, comment_id: null, enc: 0, gen: 0, size: ${a.size}, name: 'before.txt', mime: 'text/plain'}, 'on').then(j => j.enc, e => 'ERR ' + e.message)`);
      check(cv === 2, 'le2eFileConvert on: the plain file becomes a list file ' + cv);
    }
    a = (await stateAtts()).find(x => x.id === P1);
    check(a?.enc === 2 && a.e2e_gen === 1 && String(a.name).startsWith('e2e1:'), 'the server shows enc 2, generation and a name cipher ' + JSON.stringify(a));
    check(await raw(P1) === 'KENC\x02|false', 'the server keeps KENC\\x02 bytes without the text ' + JSON.stringify(await raw(P1)));
    check(await open(P1) === `before.txt|text/plain|${M} before`, 'the browser opens the same file again ' + await open(P1));

    // a new file in the detail (uploadFiles -> le2eFileUpload)
    await ev(`(async () => { await uploadFiles(${T}, [new File(['${M} hello'], 'notes.txt', {type: 'text/plain'})]); return 1; })()`);
    F1 = ((await stateAtts()).find(x => x.id !== P1) || {}).id;
    check(F1 > 0 && (await stateAtts()).find(x => x.id === F1).enc === 2, 'uploadFiles in a locked list: a list file ' + F1);
    check(await raw(F1) === 'KENC\x02|false', 'the new file left encrypted');
    check(await open(F1) === `notes.txt|text/plain|${M} hello`, 'the new file opens with the list key');
    await ev(`(openDetail(${T}), 1)`);
    check(await waitFor(`[...document.querySelectorAll('.attsec .le2fatt .an')].map(x => x.textContent).sort().join() === 'before.txt,notes.txt'`), 'the tiles show the decrypted names '
      + await ev(`[...document.querySelectorAll('.attsec .le2fatt .an')].map(x => x.textContent).join()`));
    check(await ev(`!!document.querySelector('.attsec .le2uhd') && !document.querySelector('#d-efile')`), 'the head line is there, the per-person upload of 2.42 is not offered');
    await shot('attachments');

    // a comment with a file (sendComment)
    await ev(`(async () => { S.cfiles[${T}] = [new File(['${M} photo'], 'photo.txt', {type: 'text/plain'})]; renderDetail(); await new Promise(r => setTimeout(r, 300));
      const i = document.querySelector('#c-input'); if (i) i.value = '${M} look'; await sendComment(); return 1; })()`).catch(() => 0);
    const tl = (await call('GET', `/api/tasks/${T}/timeline`)).j;
    const cm = (tl.comments || []).find(c => (c.attachments || []).length);
    check(cm && cm.body.startsWith('e2e1:') && cm.attachments[0].enc === 2, 'a comment with a file: body and file encrypted ' + JSON.stringify(cm || tl).slice(0, 200));
    if (cm) check(await open(cm.attachments[0].id) === `photo.txt|text/plain|${M} photo`, 'the comment file opens with the list key');
    check(!(await sweep()), 'H1: localStorage holds no file text ' + await sweep());
  });

  await session('bob', async ({ev, unlock, open, waitFor}) => {
    await unlock(PASS_B);
    check(await ev(`le2eUnlock(${L})`), 'Bob unlocks the list with his own key');
    check(await open(F1) === `notes.txt|text/plain|${M} hello`, 'Bob opens the file with his key');
    await ev(`(openDetail(${T}), 1)`);
    check(await waitFor(`[...document.querySelectorAll('.attsec .le2fatt .an')].some(x => x.textContent === 'notes.txt')`), 'Bob sees the decrypted name');
  });

  await session('alice', async ({ev, unlock}) => {
    await unlock(PASS);
    await ev(`le2eUnlock(${L})`);
    // the way back: stop, the files (le2eFileConvert 'decrypting'; with part A also inside le2eResume), then the texts
    check(await ev(`rawFetch('POST', '/api/lists/${L}/e2e/stop', {password: 'password123'}).then(() => load()).then(() => listById(${L})?.e2e)`) === 'decrypting', 'stop: decrypting');
    const rows = (await stateAtts()).filter(x => x.enc === 2);
    for (const x of rows) {
      const cv = await ev(`le2eFileConvert(${L}, {id: ${x.id}, task_id: ${T}, comment_id: null, enc: 2, gen: 1, size: ${x.size}}, 'decrypting').then(j => j.enc, e => 'ERR ' + e.message)`);
      check(cv === 0, 'le2eFileConvert decrypting ' + cv);
    }
    for (const c of ((await call('GET', `/api/tasks/${T}/timeline`)).j.comments || [])) for (const x of c.attachments || []) if (x.enc === 2)
      await ev(`le2eFileConvert(${L}, {id: ${x.id}, task_id: ${T}, comment_id: ${c.id}, enc: 2, gen: 1, size: ${x.size}}, 'decrypting').then(j => j.enc)`);
    check(await ev(`le2eResume(${L}, () => {}).then(r => !!r, e => 'ERR ' + e.message)`) === true, 'the way back finishes');
    const as = await stateAtts();
    check(as.length === 2 && as.every(x => !x.enc) && as.map(x => x.name).sort().join() === 'before.txt,notes.txt' && as.every(x => x.mime === 'text/plain'),
      'the files are plain again with their names and types ' + JSON.stringify(as));
    check(await ev(`fetch('/api/attachments/${F1}?dl=1').then(r => r.text())`) === `${M} hello`, 'download in plain after the way back');
  });

  console.log(`p264b_b_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
