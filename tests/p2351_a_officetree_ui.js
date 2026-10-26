// kalmido-suite: fresh
// 2.351.0 A (#3312, #2823) UI tests: the office's document areas open as trees in the panel. Own container (start.sh),
// Firefox. Invented people and companies only. Carol has NO organisation (her personal office, P4).
// - a computer: Quotes & invoices is a tree node; opened: its folders (with a subfolder), the 20 newest quotations in no
//   folder and "More…" (opens the full list); a quotation dragged onto a folder (the tree's handler and a list row's
//   drop) is filed there (toast "Filed in …"); the folder's menu: New folder…, Share…, Rename…, Move to the trash; the
//   filters client / year at the top of the list; Documents / Correspondence / Receipts are tree nodes too
// - a phone: the same tree in the drawer; a quotation is moved with "Move…" in its menu (no dragging)
// freelancer-matrix: office
// P2351A_NOSTART=1 = the server already runs; P2351A_SHOTS=<dir> keeps the screenshots.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2351_a_officetree_ui', check, shots: 'P2351A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2351A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => {
  for (let i = 0; ; i++) {
    const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined});
    if (r.status === 429 && i < 8) { await sleep(500 * (i + 1)); continue; }
    const j = await r.json().catch(() => ({})); return {...j, http: r.status};
  }
};
const FEAT = 'cal,comments,collab,contacts,office,clients,files,docs';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'POST', '/api/users', {username: 'carol', display_name: 'Carol Solo', password: 'password123', email: 'carol@example.com'});
  const CC = await login('carol');
  await call(CC, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'private'});
  check(!((await call(CC, 'GET', '/api/state')).me.workspaces || []).length, 'P4: carol has no organisation');
  const cl = await call(CC, 'POST', '/api/clients', {name: 'Example Ltd'});
  const Q = [];
  for (let i = 0; i < 23; i++) Q.push((await call(CC, 'POST', '/api/office/docs', {kind: 'offer', client_id: cl.id, project_title: i < 2 ? 'Harbour film' : '', items: [{title: `Day ${i}`, qty: 1, rate: 100 + i}]})).id);
  check(Q.every(Boolean), 'setup: 23 quotations of carol');
  const F1 = (await call(CC, 'POST', '/api/office/docs/tree/folders', {name: 'Client Alpha'})).folder?.id;
  const F2 = (await call(CC, 'POST', '/api/office/docs/tree/folders', {name: '2026', parent_id: F1})).folder?.id;
  const F3 = (await call(CC, 'POST', '/api/office/docs/tree/folders', {name: 'Archive box'})).folder?.id;
  check(F1 && F2 && F3, 'setup: folders at the area Quotes & invoices');
  check((await call(CC, 'POST', '/api/files/refs', {ref_kind: 'office_doc', ref_id: Q[0], parent_id: F2})).http === 200, 'setup: the oldest quotation in Client Alpha / 2026');
  const refOf = async id => ((await call(CC, 'GET', `/api/files/refs/office_doc/${id}`)).node || {}).parent_id || null;

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = ev => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'carol', password: 'password123'})}).then(r => r.status)`);
  const node = id => `document.querySelector('#side .sbbt[data-sbbid="${id}"]')`;
  const openNode = (ev, id) => ev(`(() => { const a = ${node(id)}?.querySelector('[data-act="sbb-tree"]'); if (!a) return 0; if (!a.dataset.open) a.click(); return 1; })()`);
  const menuLabels = `[...document.querySelectorAll('#pop:not(.hidden) [role="menuitem"] .ml')].map(x => x.textContent)`;
  const pick = (ev, label) => ev(`(() => { const b = [...document.querySelectorAll('#pop:not(.hidden) [role="menuitem"]')].find(x => x.textContent.includes(${JSON.stringify(label)})); if (!b) return 0; b.click(); return 1; })()`);
  const toastHas = t => `(document.querySelector('#toast:not(.hidden)')?.textContent || '').includes(${JSON.stringify(t)})`;

  // ================= a computer
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); return 1; })()`);
    check(await signIn(ev) === 200, 'carol signs in');
    await nav(B + '#office/offers');
    check(await ready(ev, `!!${node('a:offers')} && ${node('a:offers')}.dataset.sbbns === 'oft' && !!document.querySelector('#side [data-ofm="offers"]')`, 80),
      'computer: Quotes & invoices is a tree node (its name keeps the office point)');
    check(await ev(`!!${node('a:gendocs')} && !!${node('a:letters')} && !!${node('a:receipts')} && !document.querySelector('#side [data-offolders]')`),
      'computer: Documents, Correspondence, Receipts are tree nodes too; no group "Folders"');
    await openNode(ev, 'a:offers');
    check(await ready(ev, `!!${node('f:offers:' + F1)} && !!${node('f:offers:' + F3)} && document.querySelectorAll('#side .sbbt[data-sbbpar="a:offers"][data-sbbid^="d:offers:"]').length === 20 && !!document.querySelector('#side [data-oftmore="offers"]')`, 60),
      'computer: opened = its folders, the 20 newest quotations in no folder and More…');
    check(await ev(`!document.querySelector('#side .sbbt[data-sbbid="d:offers:${Q[0]}"]')`), 'computer: the filed quotation is not among the newest');
    await openNode(ev, 'f:offers:' + F1);
    await ready(ev, `!!${node('f:offers:' + F2)}`, 20);
    await openNode(ev, 'f:offers:' + F2);
    check(await ready(ev, `${node('d:offers:' + Q[0])}?.dataset.sbbpar === 'f:offers:${F2}'`, 40), 'computer: the subfolder holds the filed quotation');
    await shot('p2351a-desktop-tree.png');
    // the folder's menu (right click)
    await ev(`(() => { ${node('f:offers:' + F1)}.querySelector('.sbbtn').dispatchEvent(new MouseEvent('contextmenu', {bubbles: true, cancelable: true})); return 1; })()`);
    const ml = await ready(ev, `${menuLabels}.includes('Share…')`, 20) ? JSON.parse(await ev(`JSON.stringify(${menuLabels})`)) : [];
    check(['New folder…', 'Share…', 'Rename…', 'Move to the trash'].every(x => ml.includes(x)), 'computer: the folder\'s menu ' + JSON.stringify(ml));
    await ev(`(() => { document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); return 1; })()`);
    // a quotation dragged onto a folder (the tree's handler, as the drop calls it)
    await ev(`(() => { SBB_TREE.oft.move('d:offers:${Q[22]}', 'f:offers:${F3}'); return 1; })()`);
    check(await ready(ev, toastHas('Filed in'), 40) && await refOf(Q[22]) === F3, 'computer: dragged onto Archive box = filed there (toast)');
    check(await ready(ev, `${node('d:offers:' + Q[22])}?.dataset.sbbpar === 'f:offers:${F3}' || !!${node('f:offers:' + F3)}`, 40), 'computer: the tree follows');
    // a row of the list dropped onto a folder of the panel
    await ready(ev, `!!document.querySelector('#view .ofdli[draggable="true"] .ofdrow[data-id="${Q[21]}"]')`, 60);
    await ev(`(() => { const li = document.querySelector('#view .ofdrow[data-id="${Q[21]}"]').closest('.ofdli'), t = ${node('f:offers:' + F3)}, dt = new DataTransfer();
      li.dispatchEvent(new DragEvent('dragstart', {bubbles: true, cancelable: true, dataTransfer: dt}));
      t.dispatchEvent(new DragEvent('dragover', {bubbles: true, cancelable: true, dataTransfer: dt}));
      t.dispatchEvent(new DragEvent('drop', {bubbles: true, cancelable: true, dataTransfer: dt})); return 1; })()`);
    check(await ready(ev, toastHas('Filed in'), 40) && await refOf(Q[21]) === F3, 'computer: a list row dropped onto a panel folder = filed there');
    // More… opens the full list
    await nav(B + '#office/offers/' + Q[5]);
    await ready(ev, `!!document.querySelector('#side [data-oftmore="offers"]')`, 60);
    await ev(`(() => { document.querySelector('#side [data-oftmore="offers"]').click(); return 1; })()`);
    check(await ready(ev, `location.hash === '#office/offers' && !!document.querySelector('#view .ofdlist')`, 60), 'computer: More… opens the full list');
    // the filters at the top of the list
    check(await ready(ev, `!!document.querySelector('#view #ofd-flt-client_id') && !!document.querySelector('#view #ofd-flt-year') && !!document.querySelector('#view #ofd-flt-project')`, 60),
      'computer: client / project / year are filters at the top of the list');
    await ev(`(() => { const s = document.querySelector('#ofd-flt-project'); s.value = 'Harbour film'; s.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('#view .ofdlist .ofdrow').length === 2`, 60), 'computer: the project filter = its two quotations');
    await shot('p2351a-desktop-filter.png');
  }, false);

  // ================= a phone: the same tree in the drawer, "Move…" instead of dragging
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 402, height: 874}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); return 1; })()`);
    check(await signIn(ev) === 200, 'phone: carol signs in');
    await nav(B + '#office/offers');
    await ready(ev, `typeof OFC === 'object' && !!OFC.info`, 80);
    await ev(`(() => { if (!document.querySelector('#side.open')) document.querySelector('#top .menu')?.click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('#side.open') && !!${node('a:offers')}`, 60), 'phone: the drawer shows Quotes & invoices as a tree node');
    await openNode(ev, 'a:offers');
    check(await ready(ev, `${node('d:offers:' + Q[20])}?.dataset.sbbdrag === '1' && !${node('d:offers:' + Q[20])}.hasAttribute('draggable')`, 60), 'phone: the quotations are held to drag (no mouse drag)');
    await ev(`(() => { sbb_tmenu(${node('d:offers:' + Q[20])}); return 1; })()`);
    check(await ready(ev, `${menuLabels}.includes('Move…')`, 20), 'phone: a quotation\'s menu has Move…');
    await shot('p2351a-phone-menu.png');
    await pick(ev, 'Move…');
    check(await ready(ev, `${menuLabels}.includes('Client Alpha / 2026')`, 20), 'phone: Move… lists the folders with their path');
    await pick(ev, 'Client Alpha / 2026');
    check(await ready(ev, toastHas('Filed in'), 40) && await refOf(Q[20]) === F2, 'phone: moved into Client Alpha / 2026');
    await shot('p2351a-phone-tree.png');
  }, true);

  console.log(`p2351_a_officetree_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
