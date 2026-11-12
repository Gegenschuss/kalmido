// kalmido-suite: fresh
// 2.1045.0 B (#5823) UI test, jsdom, own container (start.sh). Invented names only. The whole private knowledge area shared with
// her own agent: the space's menu "…" has "Share whole knowledge area…", the one Share dialog opens on "Knowledge" and offers
// only her agent, Can edit, the question before the share names "2 folders / 2 pages visible, 0 folders excluded", the share
// is on the server; below it "Exclude folders…" picks "Private", the agent's data lock holds it, the folder row says
// "not for <agent>" and its menu offers "Include again" (one click: back in).
// freelancer-matrix: wiki (alice's private workspace is the private case; the routes run in p21045_b_wikiarea_test.py)
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
  const me = (await call('GET', '/api/state')).me;
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'wiki:read', 'wiki:write'], username: 'alibot', display_name: 'Alibot', org_id: null, owner_id: me.id});
  const P1 = (await call('POST', '/api/wiki/pages', {space: 'private', path: 'One/Alpha', body: 'a'})).id;
  const P2 = (await call('POST', '/api/wiki/pages', {space: 'private', path: 'Private/Secret', body: 's'})).id;
  const idx = await call('GET', '/api/wiki?space=private');
  const root = idx.root, priv = (idx.folders || []).find(f => f.path === 'Private')?.id;
  check(ag.http === 201 && P1 > 0 && P2 > 0 && root && priv, 'setup: agent, pages, tree');

  const w = await boot({user: 'alice', hash: 'wiki/s/private'}), d = w.document;
  w.__dialogs = 'manual';  // the questions are answered by this test itself (tests/boot.js dialogBridge)
  const pick = t => [...d.querySelectorAll('#pop:not(.hidden) [role="menuitem"]')].find(b => b.textContent.trim().startsWith(t));
  const yes = () => [...d.querySelectorAll('.cdlg [data-cd="yes"]')].pop();
  (await until(() => d.querySelector('#view [data-wk="amenu"]')))?.click();
  const item = await until(() => pick('Share whole knowledge area…'));
  check(!!item, 'the space menu offers "Share whole knowledge area…"');
  item?.click();
  const dlg = await until(() => d.querySelector('.abshdlg #ab-sht') && d.querySelector('.abshdlg'));
  check(!!dlg && /Knowledge/.test(dlg.querySelector('h3')?.textContent || ''), 'the Share dialog opens on "Knowledge"');
  const opts = [...(dlg?.querySelectorAll('#ab-sht option[value]') || [])].map(o => o.value).filter(Boolean);
  check(JSON.stringify(opts) === JSON.stringify([`agent_id:${ag.id}`]), 'only her own agent is offered ' + JSON.stringify(opts));
  check(await until(() => /No agent sees the whole knowledge area yet/.test(dlg.querySelector('.fsextra')?.textContent || '')), 'the section: no agent yet');
  dlg.querySelector('#ab-sht').value = `agent_id:${ag.id}`;
  dlg.querySelector('#ab-shr').value = 'edit';
  dlg.querySelector('[data-abs="add"]').click();
  const q = await until(() => [...d.querySelectorAll('.cdlg')].find(m => /visible/.test(m.textContent)));
  check(/2 folders \/ 2 pages visible, 0 folders excluded\./.test(q?.textContent || '') && /can change these pages/.test(q?.textContent || ''),
    'the question names what becomes visible: ' + [...d.querySelectorAll('.modal, .cdlg')].map(m => m.className + ': ' + m.textContent.trim().slice(0, 200)).join(' | '));
  yes()?.click();
  check(await until(async () => ((await call('GET', `/api/files/nodes/${root}`)).shares || []).some(s => s.agent_id === ag.id && s.role === 'edit')),
    'the share is on the server (edit)');
  const pickBtn = await until(() => dlg.querySelector(`.fsextra [data-wka-pick="${ag.id}"]`));
  check(!!pickBtn && /Alibot/.test(dlg.querySelector('.fsextra')?.textContent || ''), 'below the agent: "Exclude folders…"');
  pickBtn?.click();
  const box = await until(() => d.querySelector(`.wkapick input[value="${priv}"]`));
  check(!!box, 'the folder list to pick from');
  if (box) box.checked = true;
  yes()?.click();
  check(await until(async () => JSON.stringify(((await call('GET', `/api/agents/${ag.id}/data-lock`)).data_lock?.wiki_folders || []).map(x => x.id)) === `[${priv}]`),
    'Private excluded in the agent\'s data lock');
  check(await until(() => /Excluded:\s*Private/.test(dlg.querySelector('.fsextra')?.textContent || '')), 'the dialog lists "Excluded: Private"');
  dlg.querySelector('[data-m="close"]')?.click();
  check(await until(() => [...d.querySelectorAll('#view .wkdrow')].some(a => /Private/.test(a.textContent) && /not for Alibot/.test(a.textContent))),
    'the folder row says "not for Alibot"');
  check(await until(() => !/not for/.test([...d.querySelectorAll('#view .wkdrow')].find(a => /One/.test(a.textContent))?.textContent || 'x')), 'the other folder has no mark');
  // the folder's menu: Include again
  const items = w.eval(`JSON.stringify(wk_nodeItems(${priv}).filter(x => x && x.label).map(x => x.label))`);
  check(/Include again/.test(items), 'the folder menu offers "Include again" ' + items);
  w.eval(`wk_nodeItems(${priv}).find(x => x && x.label === 'Include again').fn()`);
  check(await until(async () => ((await call('GET', `/api/agents/${ag.id}/data-lock`)).data_lock?.wiki_folders || []).length === 0), 'Include again: off the data lock');
  check(await until(() => ![...d.querySelectorAll('#view .wkdrow')].some(a => /not for/.test(a.textContent))), 'the mark is gone');
  w.close();
  console.log(`p21045_b_wikiarea_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
