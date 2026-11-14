// 2.1162.0 part A UI test (#6107, #6108): the file store on phones and tablets and its writing buttons by the person's rights
// kalmido-suite: fresh
// Own container (start.sh; P21162A_NOSTART=1 / KMT_NOSTART=1: a running server), jsdom for the rights, Firefox for the layout
// (phone 360 px touch, tablet 820 px touch). Invented names and files only.
// freelancer-matrix: files of a person without an organisation (frida: her private space)
// #6108 - rita (read-only in the organisation Alpha) sees at its top no New folder / Upload / Scan, no "+" at the head of the
//         tree, no drop sentence, no drop frame; a file dragged onto it says "You can only read here"; the documents of Alpha
//         offer her no "Add documents" / "Scan"; in a folder shared with her for reading, the selection bar has Download but no
//         Move / Trash. mona (member) and frida (no organisation) see the buttons and the drop sentence.
// #6107 - at 360 and 820 px a row of the trash shows its name (wider than 80 px) and Restore / Delete permanently as two
//         buttons that overlap neither each other nor the name nor the marks, inside the screen; Restore brings the file back.
//         The selection bar at 360 px: every button inside the screen, no cut word (only symbols, the word in aria-label);
//         at 820 px the words are whole. While choosing, the names stay readable (wider than 80 px).
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21162_a_dateien_ui', check, shots: 'P21162A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21162A_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const upload = async (ck, name, text, form) => {
  const fd = new FormData(); fd.append('file', new Blob([text]), name);
  for (const [k, v] of Object.entries(form || {space: 'private'})) fd.append(k, v);
  const r = await fetch(B + 'api/files/upload', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: ck}, body: fd});
  return ((await r.json()).items || [])[0]?.id;
};
const FEATS = 'files,docs,collab,comments';
const person = async (CA, name, orgs) => {
  const u = await call(CA, 'POST', '/api/users', {username: name, display_name: name[0].toUpperCase() + name.slice(1), password: 'password123', email: `${name}@example.com`, ...(orgs ? {} : {orgs: []})});
  check(u.http < 300, `setup: ${name} ${u.http}`);
  return u.id;
};
const WRITE = ['[data-ab="new-folder"]', '[data-ab="upload"]', '[data-ab="scan"]'];
const has = (d, sel) => !!d.querySelector('#view ' + sel);
// a dragover of files from the computer onto el (jsdom has no DataTransfer: the event carries a plain stand-in)
const dragFiles = (w, el, type = 'dragover') => { const e = new w.Event(type, {bubbles: true, cancelable: true}); Object.defineProperty(e, 'dataTransfer', {value: {types: ['Files'], files: [], dropEffect: 'none', getData: () => ''}}); el.dispatchEvent(e); return e; };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const st0 = await call(CA, 'GET', '/api/state');
  const feats = [...new Set([...(st0.settings?.features || '').split(','), ...FEATS.split(',')])].filter(Boolean).join(',');
  await call(CA, 'PATCH', '/api/settings', {tour: 'done', lang: 'en', features: feats, workspace: 'private'});
  const ORG = (await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: st0.me.id})).id;
  check(ORG, 'setup: the organisation Alpha');
  const RITA = await person(CA, 'rita', true), MONA = await person(CA, 'mona', true);
  await person(CA, 'frida', false);
  check((await call(CA, 'PUT', `/api/orgs/${ORG}/members`, {email: 'rita@example.com', role: 'readonly'})).http < 300, 'setup: rita read-only in Alpha');
  check((await call(CA, 'PUT', `/api/orgs/${ORG}/members`, {email: 'mona@example.com', role: 'member'})).http < 300, 'setup: mona member of Alpha');
  const RK = await login('rita'), MK = await login('mona'), FK = await login('frida');
  for (const ck of [RK, MK]) await call(ck, 'POST', `/api/orgs/${ORG}/join`, {});
  for (const ck of [RK, MK]) await call(ck, 'PATCH', '/api/settings', {tour: 'done', lang: 'en', features: feats, workspace: 'org:' + ORG});
  await call(FK, 'PATCH', '/api/settings', {tour: 'done', lang: 'en', features: feats, workspace: 'private'});
  check(((await call(RK, 'GET', '/api/state')).me?.workspaces || []).some(o => o.id === ORG && o.role === 'readonly'), 'setup: rita\'s workspace carries the role read-only');
  check(((await call(FK, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'setup: frida has no organisation');
  // a folder of alice shared with rita for reading, with a file
  const BOX = (await call(CA, 'POST', '/api/files/folders', {name: 'Kiste', space: 'private'})).id;
  const BF = await upload(CA, 'drehplan.txt', 'Drehplan', {parent_id: String(BOX)});
  check((await call(CA, 'POST', `/api/files/nodes/${BOX}/shares`, {user_id: RITA, role: 'view'})).http < 300, 'setup: Kiste shared with rita for reading');
  let w, d;

  // ================= #6108 rita (read-only): no writing buttons, no drop sentence / frame, a hint on a drop
  w = await boot({user: 'rita', hash: 'ablage'}); d = w.document;
  check(await until(() => d.querySelector('#view .abview') && !/Loading/.test(d.querySelector('#view .abmain')?.textContent || '')), 'rita: the file store is drawn');
  check(await until(() => w.eval('ab_curSpace()') === 'org:' + ORG), 'rita: the space shown is Alpha ' + w.eval('ab_curSpace()'));
  check(WRITE.every(s => !has(d, s)), 'rita: no New folder / Upload / Scan at the top of Alpha');
  check(!/Drop files here/.test(d.querySelector('#view')?.textContent || ''), 'rita: no drop sentence ' + (d.querySelector('#view .abempty')?.textContent || '').replace(/\s+/g, ' ').slice(0, 160));
  check(!d.querySelector('#view .abview').classList.contains('abdropok'), 'rita: no drop frame (abdropok)');
  check(!d.querySelector('#side [data-abtadd]'), 'rita: no "+" at the head of the tree');
  const ev1 = dragFiles(w, d.querySelector('#view .abview .abmain'));
  check(!ev1.defaultPrevented, 'rita: the view does not take the dragged files');
  check(await until(() => /You can only read here/.test(d.querySelector('#toast')?.textContent || '')), 'rita: a drag of files says "You can only read here" ' + (d.querySelector('#toast')?.textContent || ''));
  w.close();
  // the documents of Alpha
  w = await boot({user: 'rita', hash: 'docs'}); d = w.document;
  check(await until(() => d.querySelector('.dc-view .dc-bar'), 80), 'rita: the documents are drawn');
  check(!d.querySelector('.dc-bar .dc-up') && !d.querySelector('.dc-bar [data-dc="scan"]'), 'rita: no "Add documents" / "Scan" in Alpha\'s documents');
  check(!/Drop PDFs or photos/.test(d.querySelector('.dc-view')?.textContent || ''), 'rita: no drop sentence in the documents');
  w.close();
  // a folder shared with her for reading: the bar without Move / Trash
  w = await boot({user: 'rita', hash: 'ablage/' + BOX}); d = w.document;
  check(await until(() => d.querySelector(`.abrow[data-abid="${BF}"]`)), 'rita: the shared folder shows its file');
  check(WRITE.every(s => !has(d, s)), 'rita: no writing buttons in a folder she only reads');
  w.eval(`ab_selPick(${BF})`);
  const bar = await until(() => d.querySelector('#ab-sbar'));
  check(bar && /1 selected/.test(bar.textContent), 'rita: the bar counts one');
  check(bar && bar.querySelector('[data-absel="dl"]') && !bar.querySelector('[data-absel="move"]') && !bar.querySelector('[data-absel="trash"]'), 'rita: the bar offers Download, no Move / Trash ' + [...(bar?.querySelectorAll('.mbb') || [])].map(b => b.dataset.absel).join());
  w.close();

  // ================= #6108 mona (member) and frida (no organisation): the buttons and the drop sentence
  for (const [u, sp] of [['mona', 'org:' + ORG], ['frida', 'private']]) {
    w = await boot({user: u, hash: 'ablage'}); d = w.document;
    check(await until(() => d.querySelector('#view .abview') && w.eval('ab_curSpace()') === sp && WRITE.every(s => has(d, s))), `${u}: New folder / Upload / Scan at the top of ${sp}`);
    check(await until(() => /Drop files here/.test(d.querySelector('#view .abempty')?.textContent || '')), `${u}: the drop sentence in the empty space`);
    check(d.querySelector('#view .abview').classList.contains('abdropok'), `${u}: the drop frame (abdropok)`);
    check(await until(() => d.querySelector('#side [data-abtadd]')), `${u}: "+" at the head of the tree`);
    const e = dragFiles(w, d.querySelector('#view .abview .abmain'));
    check(e.defaultPrevented, `${u}: the view takes dragged files`);
    w.close();
    w = await boot({user: u, hash: 'docs'}); d = w.document;
    check(await until(() => d.querySelector('.dc-bar .dc-up'), 80) && d.querySelector('.dc-bar [data-dc="scan"]'), `${u}: "Add documents" and "Scan" in the documents`);
    w.close();
  }

  // ================= #6107 the layout: phone 360 px, tablet 820 px (alice, her private space)
  const LONG = 'Entwurf Drehbuch Sommerfilm Fassung drei.txt';
  const T1 = await upload(CA, LONG, 'Entwurf'), T2 = (await call(CA, 'POST', '/api/files/folders', {name: 'Alte Fassungen vom Fruehjahr', space: 'private'})).id;
  const S1 = await upload(CA, 'Drehplan Stadtwerke Musterstadt Juni.txt', 'Plan'), S2 = await upload(CA, 'Lageplan Hafen Nord mit Zufahrt.txt', 'Plan');
  const inTrash = async id => ((await call(CA, 'GET', '/api/files?space=trash')).items || []).some(x => x.id === id);
  const toTrash = async () => { for (const id of [T1, T2]) await call(CA, 'DELETE', `/api/files/nodes/${id}`); return (await inTrash(T1)) && (await inTrash(T2)); };
  check(await toTrash(), 'setup: two rows in the trash');
  // rectangles of the trash rows: name, the two buttons, the marks
  const TRASH = `(() => { const R = e => { if (!e) return null; const r = e.getBoundingClientRect(); return {l: r.left, r: r.right, t: r.top, b: r.bottom, w: r.width, h: r.height}; };
    return JSON.stringify([...document.querySelectorAll('#view .ablist .abrow[data-abid]')].map(x => ({id: +x.dataset.abid, name: R(x.querySelector('.abname')), res: R(x.querySelector('[data-ab="restore"]')), pur: R(x.querySelector('[data-ab="purge"]')),
      badges: R(x.querySelector('.abbadges')), resLab: x.querySelector('[data-ab="restore"]')?.getAttribute('aria-label') || '', vw: innerWidth}))); })()`;
  const over = (a, b) => !!a && !!b && a.w > 0 && b.w > 0 && a.l < b.r - .5 && b.l < a.r - .5 && a.t < b.b - .5 && b.t < a.b - .5;
  const BAR = `(() => { const b = document.querySelector('#ab-sbar'); if (!b) return null; return JSON.stringify({vw: innerWidth, btn: [...b.querySelectorAll('.mbb')].map(x => { const r = x.getBoundingClientRect(), l = x.querySelector('.mbl'), ls = l && getComputedStyle(l);
      return {k: x.dataset.absel, l: r.left, r: r.right, aria: x.getAttribute('aria-label') || '', shown: !!l && ls.display !== 'none' && l.getBoundingClientRect().width > 0, cut: !!l && ls.display !== 'none' && l.scrollWidth > l.clientWidth + 1}; }),
      names: [...document.querySelectorAll('#view .ablist .abrow[data-abid] .abname')].map(n => ({w: n.getBoundingClientRect().width, whole: n.scrollWidth <= n.clientWidth + 1}))}); })()`;
  for (const [wd, ht, tag] of [[360, 740, 'p360'], [820, 1180, 't820']]) {
    await firefox(async o => {
      const {cmd, ev, ctx, shot} = o;
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: wd, height: ht}});
      await o.nav(B + 'static/icon.svg');
      await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
      check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, `${tag}: login`);
      const wait = async (js, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(js).catch(() => false)) return true; await sleep(250); } return false; };
      await o.nav(B + '#ablage');
      check(await wait(`!!document.querySelector('#view .abview') && typeof ab_pick === 'function'`), `${tag}: the file store is drawn`);
      await ev(`(() => { ab_pick('trash'); AB.key = ''; ab_load(); return 1; })()`);
      check(await wait(`!!document.querySelector('#view .abrow[data-abid="${T1}"]') && !!document.querySelector('#view .abrow[data-abid="${T2}"]')`), `${tag}: the trash shows both rows`);
      await sleep(300);
      const rows = JSON.parse(await ev(TRASH));
      for (const x of rows.filter(x => [T1, T2].includes(x.id))) {
        check(x.name && x.name.w > 80, `${tag}: row ${x.id}: the name is readable (${x.name && Math.round(x.name.w)} px)`);
        check(x.res && x.pur, `${tag}: row ${x.id}: Restore and Delete permanently are there`);
        check(!over(x.res, x.pur), `${tag}: row ${x.id}: Restore and Delete permanently do not overlap ${JSON.stringify([x.res, x.pur])}`);
        check(!over(x.name, x.res) && !over(x.name, x.pur) && !over(x.name, x.badges), `${tag}: row ${x.id}: no button or mark lies over the name`);
        check(x.res && x.pur && x.res.w >= 40 && x.pur.w >= 40 && x.pur.r <= x.vw + .5 && x.res.l >= 0, `${tag}: row ${x.id}: both buttons whole and inside the screen`);
        check(/^Restore: /.test(x.resLab), `${tag}: row ${x.id}: Restore says its word and the name to a screen reader (${x.resLab})`);
      }
      await shot(`p21162a-${tag}-trash.png`);
      // the selection of the private space: the bar and the names
      await ev(`(() => { ab_pick('private'); AB.key = ''; ab_load(); return 1; })()`);
      check(await wait(`!!document.querySelector('#view .abrow[data-abid="${S1}"]')`), `${tag}: the private space shows its files`);
      await ev(`(() => { ab_selPick(${S1}); ab_selPick(${S2}); return 1; })()`);
      check(await wait(`/2 selected/.test(document.querySelector('#ab-sbar')?.textContent || '')`), `${tag}: two chosen, the bar is there`);
      await sleep(300);
      const b = JSON.parse(await ev(BAR) || 'null');
      check(b && b.btn.length >= 4, `${tag}: the bar has its buttons ${b && b.btn.map(x => x.k).join()}`);
      for (const x of b?.btn || []) {
        check(x.l >= -.5 && x.r <= b.vw + .5, `${tag}: bar button ${x.k} inside the screen (${Math.round(x.l)}-${Math.round(x.r)} of ${b.vw})`);
        check(!x.cut, `${tag}: bar button ${x.k}: no cut word`);
        check(x.aria.length > 1, `${tag}: bar button ${x.k} has its word as aria-label`);
      }
      if (tag === 't820') check(b && b.btn.every(x => x.shown), `${tag}: on the tablet the bar shows the words`);
      check(b && b.names.length >= 2 && b.names.every(n => n.whole || n.w > 80), `${tag}: while choosing the names stay readable: whole, or cut only after 80 px (${b && b.names.map(n => Math.round(n.w) + (n.whole ? '' : '…')).join()})`);
      await shot(`p21162a-${tag}-select.png`);
      if (tag === 'p360') {  // Restore works from the symbol button (after the pictures: its message would cover the bar)
        await ev(`(() => { ab_selEnd(); ab_pick('trash'); AB.key = ''; ab_load(); return 1; })()`);
        check(await wait(`!!document.querySelector('#view .abrow[data-abid="${T1}"] [data-ab="restore"]')`), `${tag}: back in the trash`);
        await ev(`(() => { document.querySelector('#view .abrow[data-abid="${T1}"] [data-ab="restore"]').click(); return 1; })()`);
        check(await until(async () => !(await inTrash(T1)), 60), `${tag}: Restore brings the file back`);
        check(await wait(`!document.querySelector('#view .abrow[data-abid="${T1}"]')`), `${tag}: its row leaves the trash`);
      }
    }, true);
    if (tag === 'p360') check(await toTrash(), 'setup: both rows in the trash again for the tablet');
  }

  console.log(`p21162_a_dateien_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: exception', e); process.exit(1); });
