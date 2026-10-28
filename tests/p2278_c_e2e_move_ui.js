// 2.278.0 C (#3091): browser-encrypted content after an account move, own container (start.sh), Firefox (real WebCrypto):
// - alice sets up her keys, locks a note and attaches an encrypted file; her account export goes into bob (no keys yet)
// - bob unlocks with alice's passphrase (the bundle's wrap AAD names alice's old user id) and reads the locked note
//   (its AAD names the old task + user id); the encrypted file opens with its old AAD (and not without it)
// - bob changes the note: it is sealed anew with his ids, the old AAD goes; it still opens after a reload
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2278_c_e2e_move_ui', check, shots: 'P2278C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.BASE) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (method, url, body, ck) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, j: await r.json().catch(() => ({}))}; };
const SECRET = 'Moving plan: the spare key is with the neighbour';
const FILETXT = 'Inventory list of the boxes';
const PASS = 'correct horse battery staple';
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 250 : 100000, step: 250});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']}, CA);
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'}, CA);
  check((await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'}, CA)).status < 300, 'bob');
  const CB = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'}, CB);
  const L = (await call('POST', '/api/lists', {name: 'Moving'}, CA)).j.id;
  const T = (await call('POST', '/api/tasks', {title: 'Garden key', list_id: L, content: SECRET}, CA)).j.id;
  const TF = (await call('POST', '/api/tasks', {title: 'Box inventory', list_id: L}, CA)).j.id;

  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    const waitFor = async (expr, n = 80) => { for (let i = 0; i < n; i++) { const v = await ev(expr).catch(() => null); if (v) return v; await sleep(250); } return null; };
    const boot = async hash => { await nav(B + 'static/icon.svg'); await nav(B + hash); await waitFor('!!(window.S && S.booted)'); await sleep(500); };
    const signIn = user => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${user}', password: 'password123'})}).then(r => r.status)`);
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    check(await signIn('alice') === 200, 'Firefox: alice');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await boot('#t/' + T);
    // alice: keys, a locked note, an encrypted file (the app's own functions, as the dialogs call them)
    const made = await ev(`(async () => { await e2eCreate(${JSON.stringify(PASS)});
      await rawFetch('PUT', '/api/tasks/${T}/note-lock', {body: await e2eSeal(E2E.ckey, e2eTEnc().encode(${JSON.stringify(SECRET)}), ln_aad(${T}))});
      await e2eUpload(${TF}, [new File([new TextEncoder().encode(${JSON.stringify(FILETXT)})], 'inventory.txt', {type: 'text/plain'})]);
      await e2eForget(); return 1; })()`);
    check(made === 1, 'alice: keys, locked note, encrypted file');
    // the move: alice's account export into bob (the API, like the settings page)
    check((await call('POST', '/api/account/export', null, CA)).status === 202, 'export started');
    check(await until(async () => (await call('GET', '/api/account/export', null, CA)).j.state === 'done'), 'export done');
    const t = (await (await fetch(B + 'api/account/export/file', {method: 'POST', headers: {...H, Cookie: CA}, body: JSON.stringify({password: 'password123'})})).json()).ticket;  // 2.360.0 (#2496): the step-up
    const zip = Buffer.from(await (await fetch(B + 'api/account/export/file?t=' + encodeURIComponent(t || ''), {headers: {...H, Cookie: CA}})).arrayBuffer());
    const iid = (await call('POST', '/api/account/import', {size: zip.length, name: 'alice.zip'}, CB)).j.id;
    const up = await fetch(B + `api/account/import/${iid}?offset=0`, {method: 'PUT', headers: {'X-Requested-With': 'kalmido', 'Content-Type': 'application/octet-stream', Cookie: CB}, body: zip});
    check(up.ok, 'upload into bob');
    const pv = await until(async () => { const j = (await call('GET', `/api/account/import/${iid}`, null, CB)).j; return j.state === 'preview' ? j : null; });
    check(pv?.preview?.encrypted?.keys === 'take', 'preview: the keys come along ' + JSON.stringify(pv?.preview?.encrypted));
    await call('POST', `/api/account/import/${iid}/run`, {target: 'private', people: {}}, CB);
    const done = await until(async () => { const j = (await call('GET', `/api/account/import/${iid}`, null, CB)).j; return j.state === 'done' ? j : null; });
    check(done, 'import into bob done');
    const st = (await call('GET', '/api/state', null, CB)).j.tasks || [];
    const BT = st.find(t => t.title === 'Garden key')?.id, BTF = st.find(t => t.title === 'Box inventory')?.id;
    check(BT && BTF && BT !== T, 'bob has the tasks with new ids');
    // bob: alice's passphrase unlocks the moved bundle, the note opens
    check(await signIn('bob') === 200, 'Firefox: bob');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    await boot('#t/' + BT);
    check(await waitFor(`!!document.querySelector('#d-ln .lnopen')`), 'bob: the note shows locked');
    await ev(`(document.querySelector('#d-ln .lnopen').click(), 1)`);
    const pw = await waitFor(`!!document.querySelector('#e2e-pw')`);
    if (pw) await ev(`(() => { document.getElementById('e2e-pw').value = ${JSON.stringify(PASS)}; document.querySelector('.e2edlg form').requestSubmit(); return 1; })()`);
    const txt = await waitFor(`document.querySelector('#d-ln-in')?.value || ''`, 160);
    check(pw && txt === SECRET, '#3091: the moved bundle unlocks and the locked note opens after the move ' + JSON.stringify(txt));
    await shot('p2278c-moved-note.png');
    const file = await ev(`(async () => { const a = (S.tasks.get(${BTF})?.attachments || []).find(x => x.enc); if (!a) return 'none';
      const buf = await (await fetch('/api/attachments/' + a.id + '?dl=1', {headers: {'X-Requested-With': 'kalmido'}})).arrayBuffer();
      let plain = 'refused'; try { await e2eFileDecrypt(buf, ${BTF}); plain = 'opened'; } catch { /* the new AAD alone does not fit */ }
      const f = await e2eFileDecrypt(buf, ${BTF}, a.legacy_aad); return plain + '|' + f.name + '|' + new TextDecoder().decode(f.data); })()`);
    check(file === `refused|inventory.txt|${FILETXT}`, '#3091: the encrypted file opens with its old AAD (not without) ' + file);
    // a change seals the note anew
    const lk0 = (await call('GET', `/api/tasks/${BT}/note-lock`, null, CB)).j;
    check(lk0.legacy_aad === `kalmido-locknote:v1:${T}:1`, 'the note carries the old AAD ' + lk0.legacy_aad);
    await ev(`(() => { const a = document.getElementById('d-ln-in'); a.value = a.value + ' (moved)'; a.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
    const lk1 = await until(async () => { const j = (await call('GET', `/api/tasks/${BT}/note-lock`, null, CB)).j; return j.body?.ct && j.body.ct !== lk0.body.ct ? j : null; }, 60);
    check(lk1 && lk1.legacy_aad == null, '#3091: saved again: sealed anew, the old AAD is gone');
    await ev(`(e2eLock(), 1)`); await sleep(300);
    await boot('#t/' + BT);
    await waitFor(`!!document.querySelector('#d-ln .lnopen')`);
    await ev(`(document.querySelector('#d-ln .lnopen').click(), 1)`);
    if (await waitFor(`!!document.querySelector('#e2e-pw')`)) await ev(`(() => { document.getElementById('e2e-pw').value = ${JSON.stringify(PASS)}; document.querySelector('.e2edlg form').requestSubmit(); return 1; })()`);
    check(await waitFor(`(document.querySelector('#d-ln-in')?.value || '') === ${JSON.stringify(SECRET + ' (moved)')}`, 160), '#3091: the resealed note opens with the new ids');
  }, false);

  console.log(`p2278_c_e2e_move_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
