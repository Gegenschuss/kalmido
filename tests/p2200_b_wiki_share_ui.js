// 2.200.0 B (#2747) UI tests: sharing in the knowledge pages opens the ONE Share dialog of the file store (fsshare.js) on the
// page's / folder's node, with the links and earlier shares as its own section; the Share button next to the page's title; an
// organisation: the hint instead of "Whole organisation"; a space encrypted in the browser: no dialog, the lock hint; a guest
// finds a shared folder under "Shared with me" (its pages, New page / New folder with 'edit') and edits a page in the reading
// dialog. Own container (start.sh), jsdom. Invented names only.
// freelancer-matrix: wiki (alice's private space is the private case; the routes run in p2200_b_wiki_share_test.py)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2200B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const FEAT = 'cal,comments,collab,wiki,files';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['cal', 'comments', 'collab']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const st = await call('GET', '/api/state');
  const ORG = st.me.workspaces[0].id, SP = 'org:' + ORG;
  const g = await call('POST', '/api/users', {orgs: [{id: ORG, role: 'guest'}], username: 'gina', display_name: 'Gina', password: 'password123', email: 'gina@example.com'});
  const GK = await login('gina');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, GK);
  const PG = (await call('POST', '/api/wiki/pages', {space: 'private', path: 'Docs/Guide', body: 'Read this.'})).id;
  const OP = (await call('POST', '/api/wiki/pages', {space: SP, path: 'Team/Handbook/Start', body: 'Welcome.'})).id;
  check(PG > 0 && OP > 0 && g.id > 0, 'setup: pages and the guest');
  await call('GET', '/api/wiki?space=private'); await call('GET', '/api/wiki?space=' + SP);  // the tree check files them

  // ================= the private page: the button, the dialog with its section
  let w = await boot({user: 'alice', hash: 'wiki/' + PG}), d = w.document;
  const btn = await until(() => d.querySelector(`[data-wsh-share="${PG}"]`));
  check(!!btn, 'the Share button next to the page title');
  btn?.click();
  check(await until(() => d.querySelector('.abshdlg #ab-sht') && d.querySelector('.abshdlg .fsextra [data-wsh="link"]')), 'the one Share dialog with people / groups / agents and the links section');
  const secs = [...d.querySelectorAll('.abshdlg .fsextra h4')].map(x => x.textContent.trim());
  check(secs.includes('Links and earlier shares') && secs.includes('Public link'), 'the section Links and earlier shares ' + JSON.stringify(secs));
  check(/Guide/.test(d.querySelector('.abshdlg h3')?.textContent || ''), 'the dialog names the page');
  d.querySelector('.abshdlg [data-m="close"]')?.click();
  // the page's "…" menu: Share… / Share folder… open the same dialog (on the folder's node)
  d.querySelector('.wkpage [data-wk="pmenu"]')?.click();
  const pick = t => [...d.querySelectorAll('#pop:not(.hidden) [role="menuitem"]')].find(b => b.textContent.trim().startsWith(t));
  await until(() => pick('Share folder…'));
  pick('Share folder…')?.click();
  check(await until(() => /Docs/.test(d.querySelector('.abshdlg h3')?.textContent || '') && d.querySelector('.abshdlg #ab-sht')), 'Share folder… opens the dialog on the folder');
  check(await until(() => /folder/.test(d.querySelector('.abshdlg .shint')?.textContent || '')), 'the folder hint: also what is added later');
  d.querySelector('.abshdlg [data-m="close"]')?.click();
  // a space encrypted in the browser: no dialog, the hint (simulated: the lock mark of the space)
  w.eval(`wkeLockHtml = () => 'locked'; WK.idx.private = WK.idx.private || {}; WK.idx.private.pages = WK.idx.private.pages || []`);
  w.eval(`wsh_sharePage({id: ${PG}, space: 'private', path: 'Docs/Guide', node_id: 1})`);
  check(await until(() => /encrypted in the browser/.test(d.querySelector('#toast')?.textContent || '')), 'locked: the hint instead of the dialog');
  check(!d.querySelector('.abshdlg'), 'locked: no dialog');
  check(w.eval(`wkeLockHtml = () => 'locked'; WK.idx.private = WK.idx.private || {}; WK.idx.private.pages = WK.idx.private.pages || []; wsh_btnHtml({id: 1, space: 'private'}).includes(ic('lock'))`), 'locked: the button shows the lock');
  w.close();

  // ================= an organisation's page: the hint, no "Whole organisation"
  w = await boot({user: 'alice', hash: 'wiki/' + OP}); d = w.document;
  (await until(() => d.querySelector(`[data-wsh-share="${OP}"]`)))?.click();
  check(await until(() => d.querySelector('.abshdlg #ab-sht')), 'organisation: the dialog');
  check(!!d.querySelector('.abshdlg .fshint') && !d.querySelector('.abshdlg #ab-sho'), 'organisation: the members hint, no "Whole organisation" (every member reads anyway)');
  const ppl = [...d.querySelectorAll('.abshdlg #ab-sht option')].map(o => o.textContent);
  check(ppl.includes('Gina'), 'organisation: the guest can get a share ' + JSON.stringify(ppl));
  w.close();
  const fid = (await call('GET', '/api/wiki?space=' + SP)).folders.find(f => f.path === 'Team/Handbook')?.id;
  const sh = await call('POST', `/api/files/nodes/${fid}/shares`, {user_id: g.id, role: 'edit'});
  check(sh.http === 201, 'setup: the folder shared with the guest (edit)');

  // ================= the guest: Shared with me
  w = await boot({user: 'gina', hash: 'wiki'}); d = w.document;
  check(await until(() => d.querySelector('.wshside .wshfh') && d.querySelector(`.wshside [data-wsh-open="${OP}"]`)), 'Shared with me: the shared folder with its page');
  const side = d.querySelector('.wshside')?.textContent || '';
  check(/Handbook/.test(side) && !/Team/.test(side), 'from the shared folder on, no folder above it');
  check(!!d.querySelector(`.wshside [data-wsh-new="${fid}"]`) && !!d.querySelector(`.wshside [data-wsh-newf="${fid}"]`), 'edit: New page and New folder at the folder');
  d.querySelector(`.wshside [data-wsh-open="${OP}"]`).click();
  check(await until(() => d.querySelector('.wshread [data-wsh-edit]')), 'the reading dialog offers Edit');
  d.querySelector('.wshread [data-wsh-edit]').click();
  const ta = await until(() => d.querySelector('.wshread #wsh-ed'));
  check(ta && ta.value === 'Welcome.', 'the text to edit');
  if (ta) { ta.value = 'Welcome, Gina.'; d.querySelector('.wshread [data-wsh-save]').click(); }
  check(await until(async () => (await call('GET', '/api/wiki/pages/' + OP)).body === 'Welcome, Gina.'), 'saved on the server');
  check(await until(() => /Welcome, Gina/.test(d.querySelector('.wshread .wshmd')?.textContent || '')), 'the dialog shows the new text');
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
