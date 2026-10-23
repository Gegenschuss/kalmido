// 2.199.0 A (#2742) UI tests: the shared folder tree (areas.js sbb_treeHtml) moves and sorts by dragging and has a menu,
// the ONE Share dialog (fsshare.js fs_shareDialog) opens from the file store. Own container (start.sh), jsdom.
// - a computer: the file store's folders in the panel carry ns / id / parent, are draggable, take drops, have a menu;
//   dragged onto the upper edge of another folder = sorted before it (server order follows), onto its middle = moved into
//   it; a right-click opens the node's menu (Share…, New folder…, Move down), "Move down" sorts; the context key works
//   the same (contextmenu event without a pointer)
// - an automatic group (auto: true): other look, no drag, no drop, no menu; an existing caller without the new fields
//   draws exactly as before (2.198 knowledge / file store unchanged)
// - the Share dialog: ab_share opens fs_shareDialog (loaded on first use); with {office: true} the hint that folders rule
//   documents, not office actions; fs_keptText names what stayed after a folder went into the trash
// - a phone: the drawer's nodes are not draggable by the mouse (data-sbbdrag), a long press opens the menu
// freelancer-matrix: n/a (no new route here; alice's private space is the freelancer case, the routes run in p2199_a_fsref_test.py)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2199A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const rowOf = (d, txt) => [...d.querySelectorAll('#side .sbbt')].find(r => r.querySelector('.sbbtn .n')?.textContent === txt);
const menuItems = d => [...d.querySelectorAll('#pop:not(.hidden) [role="menuitem"] .ml')].map(x => x.textContent);
const topNames = async () => ((await call('GET', '/api/files?space=private')).items || []).map(x => x.name);
function dnd(w, from, to, y) {  // a mouse drag of node from onto node to at height y (0..1) of it
  to.getBoundingClientRect = () => ({top: 100, height: 20, left: 0, width: 200, right: 200, bottom: 120});
  const ev = (type, el) => { const e = new w.MouseEvent(type, {bubbles: true, cancelable: true, clientY: 100 + y * 20}); Object.defineProperty(e, 'dataTransfer', {value: {setData() {}, types: [], effectAllowed: '', dropEffect: ''}}); el.dispatchEvent(e); return e; };
  ev('dragstart', from); const over = ev('dragover', to); const mark = to.className; ev('drop', to); ev('dragend', from);
  return {accepted: over.defaultPrevented, mark};
}

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const st0 = await call('GET', '/api/state');
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'files'])].join(',');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: feats});
  const id = {};
  for (const n of ['Alpha', 'Beta', 'Gamma']) id[n] = (await call('POST', '/api/files/folders', {space: 'private', name: n})).id;
  id.Inner = (await call('POST', '/api/files/folders', {parent_id: id.Alpha, name: 'Inner'})).id;
  check(Object.values(id).every(Boolean), 'setup: folders ' + JSON.stringify(id));

  // ================= a computer
  let w = await boot({user: 'alice', hash: 'ablage'}), d = w.document;
  check(await until(() => rowOf(d, 'Alpha') && rowOf(d, 'Beta') && rowOf(d, 'Gamma')), 'the panel: the top folders');
  const A = rowOf(d, 'Alpha');
  check(A.dataset.sbbns === 'ab' && A.dataset.sbbid === String(id.Alpha) && A.dataset.sbbpar === 'top:p', `node fields ns / id / par ${A.dataset.sbbns} ${A.dataset.sbbid} ${A.dataset.sbbpar}`);
  check(A.getAttribute('draggable') === 'true' && A.dataset.sbbdrop === '1' && A.dataset.sbbmenu === '1', 'draggable, takes drops, has a menu');
  check(A.hasAttribute('data-abdrop'), 'the file rows still drop onto it (data-abdrop as before)');
  let r = dnd(w, rowOf(d, 'Gamma'), rowOf(d, 'Alpha'), 0.1);
  check(r.accepted && /sbbdbef/.test(r.mark), 'dragged onto the upper edge: marked "before" ' + r.mark);
  check(await until(async () => (await topNames()).join() === 'Gamma,Alpha,Beta'), 'sorted before Alpha (server order) ' + (await topNames()).join());
  check(await until(() => [...d.querySelectorAll('#side .sbbt[data-sbbpar="top:p"] .n')].map(x => x.textContent).join() === 'Gamma,Alpha,Beta'), 'the panel shows the new order');
  check(await until(() => /moved/.test(d.querySelector('#toast')?.textContent || '')), 'a toast with undo');
  r = dnd(w, rowOf(d, 'Beta'), rowOf(d, 'Alpha'), 0.5);
  check(r.accepted && /sbbdin/.test(r.mark), 'dragged onto the middle: marked "into"');
  check(await until(async () => (await call('GET', `/api/files/nodes/${id.Beta}`)).parent_id === id.Alpha), 'moved into Alpha');
  check(dnd(w, rowOf(d, 'Gamma'), rowOf(d, 'Gamma'), 0.5).accepted === false, 'no drop onto itself');
  // the menu: right-click
  await until(() => !rowOf(d, 'Beta') || rowOf(d, 'Beta').dataset.sbbpar !== 'top:p');
  rowOf(d, 'Gamma').querySelector('.sbbtn').dispatchEvent(new w.MouseEvent('contextmenu', {bubbles: true, cancelable: true}));
  let mi = await until(() => menuItems(d).length && menuItems(d));
  check(mi && mi.includes('Share…') && mi.includes('New folder…') && mi.includes('Move down') && !mi.includes('Move up'), 'right-click: the node\'s menu ' + JSON.stringify(mi));
  [...d.querySelectorAll('#pop:not(.hidden) [role="menuitem"]')].find(b => b.textContent.includes('Move down'))?.click();
  check(await until(async () => (await topNames()).join() === 'Alpha,Gamma'), 'Move down sorts ' + (await topNames()).join());
  // the context key: a contextmenu event from the keyboard on the focused node
  await until(() => rowOf(d, 'Alpha') && [...d.querySelectorAll('#side .sbbt[data-sbbpar="top:p"] .n')][0]?.textContent === 'Alpha');
  w.eval('closePop?.()');
  rowOf(d, 'Alpha').querySelector('.sbbtn').focus();
  rowOf(d, 'Alpha').querySelector('.sbbtn').dispatchEvent(new w.Event('contextmenu', {bubbles: true, cancelable: true}));
  mi = await until(() => menuItems(d).includes('Move down') && menuItems(d));
  check(mi && mi.includes('Move down') && !mi.includes('Move up'), 'the context key opens the menu ' + JSON.stringify(mi));
  w.eval('closePop?.()');
  // automatic group + an old caller
  const auto = w.eval(`(() => { const x = document.createElement('div'); x.id = 'tauto'; x.innerHTML = sbb_treeHtml([{k: 't:a', name: 'Client X', go: 'ablage', auto: true, ns: 'ab', id: 1, drag: true, menu: true, drop: true}]); document.querySelector('#side').appendChild(x); return x.innerHTML; })()`);
  const ar = d.querySelector('#tauto .sbbt');
  check(ar.classList.contains('sbbauto') && !ar.hasAttribute('draggable') && !ar.dataset.sbbmenu && !ar.dataset.sbbdrop && !ar.dataset.sbbns, 'automatic group: no drag, no drop, no menu ' + auto.slice(0, 200));
  check(ar.querySelector('.sbbtn').getAttribute('title') === 'Automatic group', 'automatic group: named as such');
  ar.querySelector('.sbbtn').dispatchEvent(new w.MouseEvent('contextmenu', {bubbles: true, cancelable: true}));
  await sleep(300);
  check(!menuItems(d).length, 'automatic group: a right-click opens no menu');
  const old = w.eval(`sbb_treeHtml([{k: 't:o', name: 'Old', go: 'x', kids: false}])`);
  check(old === '<div class="fhead sbbt closed " style="--sbbl:0" ><span class="sbbtar" aria-hidden="true"></span><button type="button" class="sbbtn" data-go="x" >' + w.eval(`ic('folder', 's')`) + '<span class="n">Old</span></button></div>', 'a node without the new fields draws as before ' + old);
  d.querySelector('#tauto').remove();
  // the Share dialog
  w.eval(`ab_share(${id.Gamma})`);
  const md = await until(() => d.querySelector('.abshdlg'));
  check(md && /Share “Gamma”/.test(md.textContent) && md.querySelector('#ab-sht') && !md.querySelector('.fsoffice'), 'ab_share opens the shared dialog (fsshare.js)');
  check(w.eval(`typeof fs_shareDialog === 'function' && LD_MODS.fsshare.includes('fsshare') && LD_CALL.fsshare.includes('fs_shareDialog')`), 'fsshare: a module on demand with its stand-in');
  md?.querySelector('[data-m="close"]')?.click();
  w.eval(`fs_shareDialog(${id.Gamma}, {office: true})`);
  check(await until(() => d.querySelector('.abshdlg .fsoffice') && /not to office actions/.test(d.querySelector('.abshdlg .fsoffice').textContent)), 'office: the hint that folders rule documents');
  d.querySelector('.abshdlg [data-m="close"]')?.click();
  check(w.eval(`fs_keptText([{id: 1, name: 'R-1', reason: 'Locked invoice'}, {id: 2, name: 'R-2', reason: 'Locked invoice'}])`) === '2 entries stay, one level up: Locked invoice', 'fs_keptText names what stayed');
  check(w.eval(`fs_keptText([])`) === '', 'fs_keptText: nothing kept = no text');
  w.close();

  // ================= a phone: no mouse drag, a long press opens the menu
  w = await boot({user: 'alice', hash: 'ablage', mobile: true}); d = w.document;
  w.eval('renderSide()');
  const P = await until(() => rowOf(d, 'Alpha'));
  check(P && !P.hasAttribute('draggable') && P.dataset.sbbdrag === '1' && P.dataset.sbbmenu === '1', 'phone: drag by holding (data-sbbdrag), a menu');
  if (P) {
    const te = (type, el) => { const e = new w.Event(type, {bubbles: true, cancelable: true}); Object.defineProperty(e, 'touches', {value: [{clientX: 10, clientY: 10}]}); el.dispatchEvent(e); };
    te('touchstart', P.querySelector('.sbbtn')); await sleep(500); te('touchend', P.querySelector('.sbbtn'));
    mi = await until(() => menuItems(d).length && menuItems(d));
    check(mi && mi.includes('Share…') && mi.includes('Move down'), 'phone: a long press opens the menu ' + JSON.stringify(mi));
  }
  w.close();

  console.log(`p2199_a_tree_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
