// kalmido-suite:
// 2.352.0 E (#2748) UI tests: the projects tree of the sidebar on the sidebar tree (areas.js sbb_treeHtml / sbb_treeReg 'lf').
// Own container (start.sh), jsdom, invented names only.
// - folders of any depth: "New folder…" / "New subfolder…" three levels deep, each a node of the tree (ns 'lf', drag, drop,
//   menu) right in its parent's body, made as a folder node of the file store at once (GET /api/lists/tree has its path);
//   the root "Projects" is no level of its own
// - a project dragged onto a folder three levels deep goes into it (its path, its row in that body)
// - "Share folder…" opens the one Share dialog of the file store on the folder's node: the hint that it applies at runtime,
//   a list role per share, no "Whole organisation"; shared with a person -> she sees the project, the project's members
//   name "via the folder"; the project dragged out of the folder -> she no longer sees it; in her sidebar the owner's folder
//   offers no drag, drop, Rename, Move or Dissolve (only its owner may, 403)
// - a folder moved by the tree (into another folder / to the top level) takes its project along
// - a person WITHOUT an organisation (as tests/freelancer_fixture.py; freelancer-matrix: lists): the same three levels in her
//   private tree, a project dragged in, the Share dialog with list roles on her own folder node
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2352E_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (method, url, body, ck) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const until = async (fn, n = 50) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const dnd = (w, el, type, y) => { const e = new w.Event(type, {bubbles: true, cancelable: true}); e.dataTransfer = {setData() {}, getData: () => '', effectAllowed: '', dropEffect: ''}; e.clientY = y ?? 0; el.dispatchEvent(e); return e; };
const listOf = async (ck, id) => ((await call('GET', '/api/state', null, ck)).lists || []).find(l => l.id === id) || null;
const treeOf = async ck => (await call('GET', '/api/lists/tree', null, ck)).spaces || [];
const menuTexts = d => [...d.querySelectorAll('#pop:not(.hidden) [role="menuitem"] .ml')].map(x => x.textContent);

// the sidebar of window w: folder head / body by path, a project row
const side = d => ({
  fh: f => d.querySelector(`#side .fhead[data-folder="${f}"]`),
  fb: f => d.querySelector(`#side .fbody[data-folder="${f}"]`),
  row: id => d.querySelector(`#side .srow[data-list="${id}"]`),
});
// three folder levels through the sidebar's own "New folder…" / "New subfolder…" (askPrompt answered by w.prompt, boot.js)
async function threeLevels(w, names) {
  const d = w.document, s = side(d);
  let par = '';
  for (const n of names) {
    w.prompt = () => n;
    await w.eval(`newFolder(null, ${JSON.stringify(par)})`);
    par = par ? par + '/' + n : n;
    await until(() => s.fh(par));
  }
  return par;
}
// a project row dragged onto target el (the list keeps its own drag: sidebar.js)
async function dragList(w, id, el) {
  const s = side(w.document);
  dnd(w, s.row(id), 'dragstart');
  const ov = dnd(w, el, 'dragover');
  dnd(w, el, 'drop');
  return ov.defaultPrevented;
}

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const AK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Example Studio', lang: 'en', collab_all: true, modules: ['cal', 'comments', 'collab']}, AK);
  const me = (await call('GET', '/api/state', null, AK)).me, ORG = me.workspaces?.[0]?.id;
  check(ORG, 'setup: an organisation');
  const bob = await call('POST', '/api/users', {orgs: [{id: ORG, role: 'member'}], username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'}, AK);
  const fr = await call('POST', '/api/users', {orgs: [], username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com'}, AK);
  check(bob.id && fr.id, 'setup: Bob in the organisation, Frida without one');
  const BK = await login('bob'), FK = await login('frida');
  const feats = 'collab,files,comments,progress';
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: feats, workspace: 'org:' + ORG}, AK);
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: feats}, BK);
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: feats}, FK);
  check(!((await call('GET', '/api/state', null, FK)).me.workspaces || []).length, 'setup: Frida has no organisation');
  const WEB = (await call('POST', '/api/lists', {name: 'Website relaunch', org_id: ORG}, AK)).id;
  const OTHER = (await call('POST', '/api/lists', {name: 'Office move', org_id: ORG}, AK)).id;
  check(WEB && OTHER, 'setup: two projects of the organisation');

  // ================= a computer: three levels, a project dragged in
  let w = await boot({user: 'alice', hash: 'l/' + OTHER}), d = w.document, s = side(d);
  const deep = await threeLevels(w, ['Clients', 'Acme', '2026']);
  const h3 = s.fh(deep);
  check(h3 && h3.classList.contains('sbbt') && h3.dataset.sbbns === 'lf' && h3.dataset.sbbid === deep && h3.dataset.sbbpar === 'Clients/Acme' && h3.dataset.sbbdrop === '1' && h3.dataset.sbbmenu === '1',
    'level 3: a node of the sidebar tree (drag, drop, menu)');
  check(h3?.parentElement === s.fb('Clients/Acme') && s.fh('Clients/Acme')?.parentElement === s.fb('Clients'), 'each level sits in its parent folder\'s body');
  check(h3?.querySelector('.sbbtn .n')?.textContent === '2026' && (h3.querySelector('.sbbtn')?.dataset.go || '').startsWith('folder/'),
    'level 3: its own name, the name opens the folder view');
  check(!d.querySelector('#side .lfh[data-folder="Projects"]') && ![...d.querySelectorAll('#side .lfh .sbbtn .n')].some(n => n.textContent === 'Projects'), 'the root "Projects" is no level of its own');
  const sp = await until(async () => (await treeOf(AK)).find(x => x.org_id === ORG && x.folders.some(f => f.path === deep)));
  check(sp, 'the folder three levels deep is a folder node of the organisation\'s projects tree');
  check(await dragList(w, WEB, h3), 'a project dragged over the folder: a valid target');
  check(await until(async () => (await listOf(AK, WEB))?.folder === deep), 'dropped: the project is in the folder three levels deep');
  await w.eval('load().then(() => render())');
  check(await until(() => s.row(WEB)?.parentElement === s.fb(deep)), 'its row sits in that folder\'s body');
  check(await until(async () => (await treeOf(AK)).find(x => x.org_id === ORG)?.lists.some(l => l.list_id === WEB && l.parent_id === sp.folders.find(f => f.path === deep).id)),
    'the project\'s node lies in the folder node');

  // the folder's menu (the tree's: right click / hold) offers a subfolder at any depth and the Share dialog
  w.eval(`sbb_tmenu(document.querySelector('#side .fhead[data-folder="${deep}"]'))`);
  const mt = menuTexts(d);
  check(mt.includes('New subfolder…') && mt.includes('Share folder…') && mt.includes('Move to the top level'), 'the folder\'s menu: New subfolder…, Share folder…, Move to the top level ' + mt.join('|'));
  w.eval('closePop()');

  // ================= the one Share dialog on the folder's node, a list role, Bob sees the project
  check(!(await listOf(BK, WEB)), 'before: Bob does not see the project');
  await w.eval(`lf_share('Clients')`);
  const md = await until(() => d.querySelector('.abshdlg'));
  check(md && /at runtime/.test(md.textContent) && !md.querySelector('#ab-sho'), 'Share dialog: the runtime hint, no "Whole organisation"');
  const roles = [...(md?.querySelectorAll('#ab-shr option') || [])].map(o => o.value).join(',');
  check(roles === 'admin,edit,participant,view', 'Share dialog: a list role per share ' + roles);
  check(md?.querySelector(`#ab-sht option[value="user_id:${bob.id}"]`), 'Share dialog: Bob is a target');
  check(md?.querySelector('[data-m="lf-more"]'), 'Share dialog: the projects\' own parts one link away');
  md.querySelector('#ab-sht').value = 'user_id:' + bob.id;
  md.querySelector('#ab-shr').value = 'view';
  md.querySelector('[data-abs="add"]').click();
  check(await until(() => md.querySelector('#ab-shl .mrow[data-sid]')), 'Share dialog: the share is listed');
  check(md.querySelector('#ab-shl [data-absr]')?.value === 'view', 'Share dialog: with its list role');
  check(await until(async () => !!(await listOf(BK, WEB))), 'shared on a folder two levels above: Bob sees the project');
  check(!(await listOf(BK, OTHER)), 'a project outside the folder stays hidden from Bob');
  const m = (await listOf(AK, WEB))?.members?.find(x => x.user_id === bob.id);
  check(m && m.via_folder && m.role === 'view', 'Bob is a member through the folder (via_folder, view)');
  md.querySelector('[data-m="close"]')?.click();
  await w.eval('load().then(() => render())');
  w.eval(`shareModal(${WEB})`);
  check(await until(() => /via the folder Clients \/ Acme \/ 2026/.test(d.querySelector(`#l-members .mrow[data-uid="${bob.id}"]`)?.textContent || '')), 'the project\'s members: Bob "via the folder"');
  [...d.querySelectorAll('.modal')].forEach(x => x.remove());

  // a folder moved by the tree takes its project (and the share above it) along
  await w.eval(`SBB_TREE.lf.move('Clients/Acme/2026', 'Clients')`);
  check(await until(async () => (await listOf(AK, WEB))?.folder === 'Clients/2026'), 'folder moved one level up by the tree: the project follows');
  check(!!(await listOf(BK, WEB)), 'still below the shared folder: Bob keeps it');
  // Bob's sidebar: Alice's folder (its owner arranges it, #988): no drag, no drop, no Rename / Move / Dissolve (the server says 403)
  { const bw = await boot({user: 'bob', hash: 'l/' + WEB}), bd = bw.document;
    const bf = (await listOf(BK, WEB))?.folder || '', bh = await until(() => bf && side(bd).fh(bf));
    check(bh && bh.getAttribute('draggable') !== 'true' && !bh.dataset.sbbdrop, 'Bob: Alice\'s folder is no drag source and no drop target ' + bf);
    bw.eval(`sbb_tmenu(document.querySelector('#side .fhead[data-folder="${bf}"]'))`);
    const bm = menuTexts(bd);
    check(!bm.includes('Rename') && !bm.includes('Move to the top level') && !bm.some(x => /^Dissolve/.test(x)) && !bm.includes('New subfolder…'), 'Bob: no Rename / Move / Dissolve / New subfolder in Alice\'s folder ' + bm.join('|'));
    bw.close(); }
  await w.eval('load().then(() => render())');
  await until(() => s.row(WEB));
  // the project dragged out of the folder (onto the "Projects" header): Bob no longer sees it
  const root = d.querySelector('#side .shead.lroot');
  check(root && await dragList(w, WEB, root), 'a project dragged onto "Projects": a valid target');
  check(await until(async () => (await listOf(AK, WEB))?.folder === ''), 'dragged out: no folder');
  check(await until(async () => !(await listOf(BK, WEB))), 'dragged out of the shared folder: Bob no longer sees it');
  w.close();

  // ================= a person without an organisation (freelancer-matrix: lists)
  const PL = (await call('POST', '/api/lists', {name: 'Own work'}, FK)).id;
  check(PL, 'Frida: a project of her own');
  w = await boot({user: 'frida', hash: 'l/' + PL}); d = w.document; s = side(d);
  const fdeep = await threeLevels(w, ['Jobs', '2026', 'Spring']);
  check(s.fh(fdeep)?.dataset.sbbpar === 'Jobs/2026' && s.fh(fdeep).parentElement === s.fb('Jobs/2026'), 'Frida: three levels in her sidebar');
  check(await until(async () => (await treeOf(FK)).find(x => x.org_id == null)?.folders.some(f => f.path === fdeep && f.mine)), 'Frida: the folder is a node of her private projects tree');
  check(await dragList(w, PL, s.fh(fdeep)), 'Frida: a project dragged over the folder: a valid target');
  check(await until(async () => (await listOf(FK, PL))?.folder === fdeep), 'Frida: the project is in the folder three levels deep');
  await w.eval(`lf_share('Jobs')`);
  const fmd = await until(() => d.querySelector('.abshdlg'));
  check(fmd && [...fmd.querySelectorAll('#ab-shr option')].map(o => o.value).join(',') === 'admin,edit,participant,view' && /at runtime/.test(fmd.textContent),
    'Frida: the Share dialog on her own folder node with list roles');
  w.close();

  console.log(`p2352_e_listtree_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERROR', e); process.exit(1); });
