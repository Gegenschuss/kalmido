// kalmido-suite: fresh
// 2.1160.0 (#5862) UI test, jsdom, own container (start.sh). Invented names only. The whole private knowledge area shared with a
// PERSON: the space's menu "…" -> "Share whole knowledge area…", the Share dialog on "Knowledge" offers Bob, the question names
// "2 folders / 2 pages visible, 0 folders excluded" and "The person can read these pages.", the share is on the server; the
// section "Who sees the whole knowledge area" names Bob, "Exclude folders…" picks "Private" (the share's own exclusions), the
// folder row says "not for Bob". Bob then opens Knowledge and sees under "Shared with me" the folder "Knowledge" with Alice's
// name and the page "Alpha" -- not "Secret" -- and opens it.
// freelancer-matrix: wiki (alice's private workspace is the private case; the routes run in p21160_wikiarea_person_test.py)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const FEAT = 'cal,comments,collab,wiki,files';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['cal', 'comments', 'collab']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const org = (await call('GET', '/api/state')).me.workspaces[0].id;
  const bob = await call('POST', '/api/users', {orgs: [{id: org, role: 'member'}], username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  const CB = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, CB);
  const P1 = (await call('POST', '/api/wiki/pages', {space: 'private', path: 'One/Alpha', body: 'alpha words'})).id;
  const P2 = (await call('POST', '/api/wiki/pages', {space: 'private', path: 'Private/Secret', body: 's'})).id;
  const idx = await call('GET', '/api/wiki?space=private');
  const root = idx.root, priv = (idx.folders || []).find(f => f.path === 'Private')?.id;
  check(bob.http < 300 && P1 > 0 && P2 > 0 && root && priv, 'setup: Bob, pages, tree');

  // ---- Alice shares her whole area with Bob
  const w = await boot({user: 'alice', hash: 'wiki/s/private'}), d = w.document;
  w.__dialogs = 'manual';  // the questions are answered by this test itself (tests/boot.js dialogBridge)
  const pick = t => [...d.querySelectorAll('#pop:not(.hidden) [role="menuitem"]')].find(b => b.textContent.trim().startsWith(t));
  const yes = () => [...d.querySelectorAll('.cdlg [data-cd="yes"]')].pop();
  (await until(() => d.querySelector('#view [data-wk="amenu"]')))?.click();
  const item = await until(() => pick('Share whole knowledge area…'));
  check(!!item, 'the space menu offers "Share whole knowledge area…"');
  item?.click();
  const dlg = await until(() => d.querySelector('.abshdlg #ab-sht') && d.querySelector('.abshdlg'));
  check(!!dlg && /person or an agent/.test(dlg.textContent || ''), 'the dialog says: with a person or an agent');
  const opts = [...(dlg?.querySelectorAll('#ab-sht option[value]') || [])].map(o => o.value).filter(Boolean);
  check(opts.includes(`user_id:${bob.id}`), 'Bob is offered ' + JSON.stringify(opts));
  check(await until(() => /Nobody sees the whole knowledge area yet/.test(dlg.querySelector('.fsextra')?.textContent || '')), 'the section: nobody yet');
  dlg.querySelector('#ab-sht').value = `user_id:${bob.id}`;
  dlg.querySelector('#ab-shr').value = 'view';
  dlg.querySelector('[data-abs="add"]').click();
  const q = await until(() => [...d.querySelectorAll('.cdlg')].find(m => /visible/.test(m.textContent)));
  check(/2 folders \/ 2 pages visible, 0 folders excluded\./.test(q?.textContent || '') && /The person can read these pages/.test(q?.textContent || ''),
    'the question names what Bob will see: ' + (q?.textContent || '').trim().slice(0, 200));
  yes()?.click();
  check(await until(async () => ((await call('GET', `/api/files/nodes/${root}`)).shares || []).some(s => s.user_id === bob.id && s.role === 'view')),
    'the share is on the server (view)');
  check(await until(() => /Who sees the whole knowledge area/.test(dlg.querySelector('.fsextra')?.textContent || '') && /Bob/.test(dlg.querySelector('.fsextra')?.textContent || '')),
    'the section names Bob');
  const pickBtn = await until(() => dlg.querySelector('.fsextra [data-wka-pick]'));
  check(!!pickBtn, 'below Bob: "Exclude folders…"');
  pickBtn?.click();
  const pq = await until(() => [...d.querySelectorAll('.cdlg, .modal')].find(m => /Bob no longer sees these folders/.test(m.textContent)));
  check(!!pq, 'the picker says what Bob will no longer see');
  const box = await until(() => d.querySelector(`.wkapick input[value="${priv}"]`));
  if (box) box.checked = true;
  yes()?.click();
  check(await until(async () => JSON.stringify(((await call('GET', '/api/wiki/area-share?space=private')).shares || [])[0]?.excluded) === `[${priv}]`),
    'Private excluded on Bob\'s share');
  check(await until(() => /Excluded:\s*Private/.test(dlg.querySelector('.fsextra')?.textContent || '')), 'the dialog lists "Excluded: Private"');
  dlg.querySelector('[data-m="close"]')?.click();
  check(await until(() => [...d.querySelectorAll('#view .wkdrow')].some(a => /Private/.test(a.textContent) && /not for Bob/.test(a.textContent))),
    'the folder row says "not for Bob"');
  w.close();

  // ---- Bob sees it under "Shared with me"
  const wb = await boot({user: 'bob', hash: 'wiki'}), db = wb.document;
  const side = await until(() => [...db.querySelectorAll('.wshside')].find(x => /Alpha/.test(x.textContent)), 60);
  check(!!side, 'Bob: "Shared with me" lists the page Alpha');
  const head = [...(side?.querySelectorAll('.wshfh') || [])].find(x => /Knowledge/.test(x.textContent));
  check(!!head && /Alice/.test(head.textContent), 'Bob: the folder "Knowledge" with Alice\'s name ' + (side?.textContent || '').trim().slice(0, 200));
  check(!/Secret/.test(side?.textContent || '') && !/Private/.test(side?.textContent || ''), 'Bob: nothing of the excluded folder');
  [...(side?.querySelectorAll('[data-wsh-open]') || [])].find(a => /Alpha/.test(a.textContent))?.click();
  check(await until(() => /alpha words/.test(db.body.textContent || '')), 'Bob: the page opens with its text');
  wb.close();
  console.log(`p21160_wikiarea_person_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
