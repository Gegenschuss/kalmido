// 2.64.2 parts C + D (#1817): the list channel of a list with the lock in the web app, own container (start.sh), Firefox (real
// WebCrypto). Bob and Alice set up encryption, Alice locks a list (le2eStart), then:
// - Alice writes in the channel (#team/<id>): the server keeps only {v, g, iv, ct}, localStorage never holds the text (H1)
// - the head of the channel says "Encrypted in the browser" with the button Safety numbers (part D, le2uChanHead)
// - Bob opens the channel: a placeholder until he unlocks, then the text; Bob answers, Alice reads it; an edit is encrypted again
// - a mention of Bob is named to the server (mentions) without the text
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p264b_c_ui', check, shots: 'P264BC_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.BASE) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, j: await r.json().catch(() => ({}))}; };
const PASS = 'correct horse battery staple', PASS_B = 'another horse battery staple';
const M = 'ZQXchan';  // every plain text of the channel carries it: no storage and no server row may hold it

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).j.id;
  const L = (await call('POST', '/api/lists', {name: 'Locked chat'})).j.id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: BOB, role: 'edit'});
  const BCK = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'}, BCK);
  const RID = ((await call('GET', '/api/team')).j.rooms || []).find(x => x.list_id === L)?.id;
  check(!!RID, 'the channel of the shared list');
  const rows = async () => (await call('GET', `/api/team/rooms/${RID}/messages`)).j.messages || [];

  const session = (user, fn) => firefox(async ({cmd, ev, nav, ctx, shot}) => {
    const waitFor = async (expr, n = 80) => { for (let i = 0; i < n; i++) { const v = await ev(expr).catch(() => null); if (v) return v; await sleep(250); } return null; };
    const boot = async hash => { await nav(B + 'static/icon.svg'); await nav(B + hash); await waitFor('!!(window.S && S.booted)'); await sleep(500); };
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${user}', password: 'password123'})}).then(r => r.status)`) === 200, `Firefox: login ${user}`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await boot('#inbox');
    const sweep = () => ev(`Object.keys(localStorage).filter(k => (localStorage.getItem(k) || '').includes('${M}')).join(',')`);
    const unlock = pass => ev(`(async () => { await e2eLoad(true); await e2eAdopt(await e2eUnwrapPass(E2E.st.bundle_pass, ${JSON.stringify(pass)})); return 1; })()`);
    await fn({ev, waitFor, boot, shot, sweep, unlock});
  }, false);

  await session('bob', async ({ev}) => {
    check(await ev(`e2eCreate(${JSON.stringify(PASS_B)}).then(c => !!c)`), 'Bob sets up encryption');
  });
  await session('alice', async ({ev, waitFor, boot, sweep}) => {
    check(await ev(`e2eCreate(${JSON.stringify(PASS)}).then(c => !!c && e2eUnlocked())`), 'Alice sets up encryption');
    check(await ev(`le2eStart(${L}, () => {}).then(r => !!r && listById(${L})?.e2e === 'on')`), 'le2eStart: the list is locked');
    await boot('#team/' + RID);
    check(await waitFor(`S.tc.room?.id === ${RID} && le2eChanOn(S.tc.room)`), 'the channel knows the lock of its list');
    check(await waitFor(`!!document.querySelector('.tcroom .le2uhd [data-le2uhd="safety"]')`), 'part D: the head line with Safety numbers');
    await ev(`(async () => { await le2eKeys(${L}, true); return 1; })()`);
    await ev(`(() => { const ta = document.querySelector('#tc-in'); ta.value = '${M} hello @Bob'; return 1; })()`);
    await ev(`tcSend().then(() => 1)`);
    const mine = await waitFor(`(S.tc.msgs || []).find(m => m.body && m.body.includes('${M} hello')) ? 1 : 0`);
    check(mine, 'Alice sees her message as text');
    const srv = (await rows()).find(m => m.user_id !== BOB && m.enc);
    check(srv && srv.body === '' && srv.enc.g === 1 && !JSON.stringify(await rows()).includes(M), 'the server keeps only the ciphertext with its generation');
    check(!(await sweep()), 'H1: localStorage holds no plain text of the channel ' + await sweep());
    const sh = await ev(`(le2uSafetyList(${L}), 1)`);
    check(sh && await waitFor(`/Safety numbers/.test(document.querySelector('.modal')?.textContent || '') && document.querySelectorAll('.modal .le2usl').length === 1`), 'part D: the safety numbers of the members (Bob)');
    await ev(`(document.querySelectorAll('.modal').forEach(m => m.remove()), 1)`);
  });
  await session('bob', async ({ev, waitFor, boot, unlock}) => {
    await boot('#team/' + RID);
    check(await waitFor(`!!document.querySelector('#tc-msgs [data-le2c="unlock"], #tc-msgs [data-e2e="dm-unlock"]')`), 'Bob: a placeholder until he unlocks');
    await unlock(PASS_B);
    await ev(`(async () => { await le2eUnlock(${L}); await le2eChanDecrypt(${RID}); return 1; })()`);
    check(await waitFor(`(S.tc.msgs || []).some(m => m._dec && m.body.includes('${M} hello'))`), 'Bob reads Alice\'s message with his own key');
    await ev(`(() => { const ta = document.querySelector('#tc-in'); ta.value = '${M} answer'; return 1; })()`);
    await ev(`tcSend().then(() => 1)`);
    check(await waitFor(`(S.tc.msgs || []).some(m => m.user_id === ${BOB} && m.body === '${M} answer')`), 'Bob writes in the channel');
    const mid = await ev(`(S.tc.msgs || []).find(m => m.user_id === ${BOB} && m.body === '${M} answer')?.id`);
    await ev(`(() => { S.tc.edit = ${mid}; tcPatch(); return 1; })()`);
    await waitFor(`!!document.querySelector('#tc-msgs .tc-edit')`);
    await ev(`(() => { document.querySelector('#tc-msgs .tc-edit').value = '${M} answer changed'; return tcEditSave(${mid}).then(() => 1); })()`);
    const ed = (await rows()).find(m => m.id === mid);
    check(ed && ed.edited_at && ed.enc && ed.enc.g === 1 && ed.body === '', 'an edit is encrypted again ' + JSON.stringify(ed || {}).slice(0, 200));
  });
  await session('alice', async ({ev, waitFor, boot, unlock}) => {
    await boot('#team/' + RID);
    await unlock(PASS);
    await ev(`(async () => { await le2eUnlock(${L}); await le2eChanDecrypt(${RID}); return 1; })()`);
    check(await waitFor(`(S.tc.msgs || []).some(m => m._dec && m.body === '${M} answer changed')`), 'Alice reads Bob\'s changed answer');
    check(!JSON.stringify(await rows()).includes(M), 'no plain text of the channel on the server');
  });

  console.log(`p264b_c_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
