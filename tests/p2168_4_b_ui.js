// 2.210 part B UI tests (#2757): a right click (computer) / a long press (phone) on a folder = that folder's "…" menu, one
// building block (cm_bind in multisel.js) for the file store and the knowledge folders. Own container (start.sh), jsdom, a
// person WITHOUT an organisation (as tests/freelancer_fixture.py; freelancer-matrix: wiki, files); Firefox for the screenshot.
// - file store: a folder of the panel and a row of the list open ab_menu (Share…, Move to the trash); a space row of the
//   panel keeps the browser's menu
// - knowledge (bundle 2.305: the 2.200 folder menu, wk_nodeItems): a folder of the panel, of the folder list and of the
//   phone's tree open the folder menu (New page, New folder…, Rename…, Move to…, Share…, Move to the trash); the open folder
//   has the same menu behind its "…" (wk_rowMore); "All pages" keeps its own menu, a page row gets the page menu (2.200);
//   a long press opens the menu and the click ending it opens nothing
// - the folder menu works: New page starts in the folder, rename (the open folder follows), to the trash (2.200: no
//   question, Undo), Undo brings it back with its pages
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2168_4_b_ui', check, shots: 'P21684B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21684B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const rowOf = (d, txt) => [...d.querySelectorAll('#side .sbbt')].find(r => r.querySelector('.sbbtn .n')?.textContent === txt);
const ctx = (w, el) => { const e = new w.MouseEvent('contextmenu', {bubbles: true, cancelable: true, button: 2}); el.dispatchEvent(e); return e; };
const items = d => d.querySelector('#pop:not(.hidden)') ? [...d.querySelectorAll('#pop [role="menuitem"] .ml')].map(x => x.textContent) : [];
const pick = (d, re) => { const b = [...d.querySelectorAll('#pop:not(.hidden) [role="menuitem"]')].find(x => re.test(x.textContent)); b?.click(); return !!b; };
const shut = w => { w.eval('closePop()'); };
const paths = async () => ((await call('GET', '/api/wiki?space=private')).pages || []).map(p => p.path).sort();

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const AK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true}, AK);
  await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: (await call('GET', '/api/state', null, AK)).me.id}, AK);  // a server with organisations
  const fu = await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []}, AK);
  check(fu.http < 300, 'a person without an organisation ' + fu.http);
  CK = await login('frida');
  const st0 = await call('GET', '/api/state');
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'wiki', 'files'])].join(',');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: feats});
  check(((await call('GET', '/api/state')).me.workspaces || []).length === 0, 'frida is in no organisation');
  for (const p of ['Docs/Guide', 'Docs/Deep/Inner', 'Top page']) await call('POST', '/api/wiki/pages', {space: 'private', path: p, body: 'Text of ' + p});
  const INV = (await call('POST', '/api/files/folders', {name: 'Invoices', space: 'private'})).id;
  check(INV, 'a folder Invoices');

  // ================= the file store
  let w = await boot({user: 'frida', hash: 'ablage'}); let d = w.document;
  check(await until(() => rowOf(d, 'Invoices')), 'the panel shows the folder Invoices');
  let e = ctx(w, rowOf(d, 'Invoices').querySelector('.sbbtn'));
  check(e.defaultPrevented && await until(() => items(d).includes('Share…') && items(d).includes('Move to the trash')), 'right click on a folder of the panel: its "…" menu ' + items(d));
  shut(w);
  const lr = await until(() => d.querySelector(`#view .abrow[data-abid="${INV}"]`));
  e = ctx(w, lr.querySelector('.abopen'));
  check(e.defaultPrevented && await until(() => items(d).includes('Share…') && items(d).includes('Move to the trash')), 'right click on a row of the list: the same menu ' + items(d));
  d.querySelector(`#view .abrow[data-abid="${INV}"] [data-ab="menu"]`).click();
  const viaDots = items(d); shut(w);
  e = ctx(w, lr.querySelector('.abopen'));
  check(await until(() => items(d).length) && items(d).join('|') === viaDots.join('|'), 'right click and "…" show exactly the same entries');
  shut(w);
  const sp = d.querySelector('#side [data-absp="private"]');
  check(sp && !ctx(w, sp).defaultPrevented && !items(d).length, 'a space row of the panel keeps the browser\'s menu');
  w.close();

  // ================= knowledge: the panel, the folder list, the open folder's "…"
  w = await boot({user: 'frida', hash: 'wiki', ls: {'tasks.wkSpace': JSON.stringify('private')}}); d = w.document;
  w.__dialogs = 'manual';  // the dialogs are answered here (boot.js dialogBridge)
  check(await until(() => rowOf(d, 'Docs')), 'the panel shows the folder Docs');
  e = ctx(w, rowOf(d, 'Docs').querySelector('.sbbtn'));
  const FM = ['New page', 'New folder…', 'Rename…', 'Move to…', 'Share…', 'Move to the trash'];  // 2.200.0 (#2747) wk_nodeItems
  check(e.defaultPrevented && FM.every(x => items(d).includes(x)), 'right click on a folder of the panel: the folder menu ' + items(d));
  shut(w);
  const all = d.querySelector('#side .sbbi[data-go="wiki"]');
  check(all && (ctx(w, all), !items(d).includes('New folder…')), '"All pages" does not get the folder menu (it keeps its own favourites menu)');
  shut(w);
  const pg = await until(() => [...d.querySelectorAll('#view .wkitem')].find(a => /Top page/.test(a.textContent)));
  e = pg && ctx(w, pg);
  check(e?.defaultPrevented && items(d).includes('Open') && items(d).includes('Rename…') && !items(d).includes('New folder…'), 'a page row opens the page menu (2.200) ' + items(d));
  shut(w);
  w.location.hash = 'wiki/d/Docs';
  const dots = await until(() => w.eval(`S.route.wdir`) === 'Docs' && d.querySelector('#view .wkfolder .nthead [data-wk="rmenu"]'));
  check(dots && /More/.test(dots.getAttribute('aria-label') || ''), 'the open folder has a "…" in its head');
  dots?.click();
  const viaW = items(d); shut(w);
  check(FM.every(x => viaW.includes(x)), 'its "…" = the folder menu ' + viaW);
  const deep = await until(() => [...d.querySelectorAll('#view .wkdrow')].find(a => /Deep/.test(a.textContent)));
  e = ctx(w, deep);
  check(e.defaultPrevented && items(d).join('|') === viaW.join('|'), 'right click on a folder of the list: the same menu');
  shut(w);
  // the phone: a long press (pointer events of a finger) opens it, the click ending the press opens nothing
  const pe = (type, el) => { const x = new w.MouseEvent(type, {bubbles: true, cancelable: true, clientX: 10, clientY: 10}); Object.defineProperty(x, 'pointerType', {value: 'touch'}); el.dispatchEvent(x); return x; };
  pe('pointerdown', deep); await sleep(700); pe('pointerup', deep);
  // 2.428.0 (#3581): a long press selects the folder like everywhere; the menu stays on the right click and the "…"
  check(await until(() => w.eval('WK.selOn && WK.sel.size === 1')) && !items(d).includes('Rename…'), 'a long press selects the folder, no menu ' + items(d));
  const h0 = w.location.hash, cl = new w.MouseEvent('click', {bubbles: true, cancelable: true}); deep.dispatchEvent(cl);
  check(cl.defaultPrevented && w.location.hash === h0, 'the click ending the long press does not open the folder');
  w.eval('wk_selEnd()'); shut(w); await sleep(700);  // a menu event right after a long press belongs to it (Android sends one more)
  // New page here: the dialog starts in the folder
  ctx(w, deep); pick(d, /^New page$/);
  check(await until(() => d.querySelector('#cdlg-in')?.value === 'Docs/Deep/'), '"New page here…" starts in the folder ' + d.querySelector('#cdlg-in')?.value);
  d.querySelector('.cdlg [data-cd="no"]')?.click();
  // rename: the open folder follows
  ctx(w, rowOf(d, 'Docs').querySelector('.sbbtn')); pick(d, /^Rename…$/);
  const inp = await until(() => d.querySelector('#cdlg-in'));
  if (inp) { inp.value = 'Manuals'; inp.closest('form').dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true})); }
  check(await until(async () => (await paths()).join('|') === 'Manuals/Deep/Inner|Manuals/Guide|Top page'), 'the folder is renamed with its pages ' + await paths());
  check(await until(() => w.location.hash === '#wiki/d/Manuals'), 'the open folder follows the new name ' + w.location.hash);
  // to the trash (2.200 menu: no question, Undo), Undo brings it back
  const mr = await until(() => rowOf(d, 'Manuals'));
  mr && ctx(w, mr.querySelector('.sbbtn'));
  check(pick(d, /Move to the trash/), 'the folder menu has "Move to the trash"');
  check(await until(async () => (await paths()).join('|') === 'Top page'), 'the folder with its pages is in the trash ' + await paths());
  check(await until(() => w.location.hash === '#wiki'), 'the view goes up to the space ' + w.location.hash);
  const tr = (await call('GET', '/api/wiki/trash?space=private')).pages || [];
  check(tr.length === 2, 'both pages are in the trash of the space ' + tr.length);
  w.eval(`histStep('undo')`);
  check(await until(async () => (await paths()).length === 3), 'Undo brings the folder back ' + await paths());
  w.close();

  // ================= the phone's tree (no panel): a folder row opens the same menu
  w = await boot({user: 'frida', hash: 'wiki', mobile: true, ls: {'tasks.wkSpace': JSON.stringify('private')}}); d = w.document;
  const sm = await until(() => d.querySelector('#view .wktree details[data-wkk="wk:private:manuals"] > summary'));
  e = sm && ctx(w, sm);
  check(e?.defaultPrevented && items(d).includes('Rename…') && items(d).includes('New folder…'), 'a folder of the phone\'s tree opens the folder menu ' + items(d));
  w.close();

  // ================= Firefox: the menu at a folder of the panel (screenshot)
  await firefox(async ({cmd, ev, ctx: c, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: c, viewport: {width: 1280, height: 800}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); localStorage.setItem('tasks.wkSpace', '"private"'); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'frida', password: 'password123'})}).then(r => r.status)`);
    await nav(B + '#wiki');
    let ready = false;
    const row = `[...document.querySelectorAll('#side .sbbt[data-sbbns="wk"]')].find(r => r.querySelector('.sbbtn .n')?.textContent === 'Manuals')`;
    for (let i = 0; i < 60 && !ready; i++) { ready = await ev(`!!${row}`).catch(() => false); if (!ready) await sleep(250); }
    check(ready, 'Firefox: the folder in the panel');
    const r = ready ? await ev(`(() => { const b = ${row}.querySelector('.sbbtn').getBoundingClientRect(); return [b.left + 30, b.top + b.height / 2]; })()`) : [10, 10];
    await cmd('input.performActions', {context: c, actions: [{type: 'pointer', id: 'm', parameters: {pointerType: 'mouse'}, actions: [{type: 'pointerMove', x: Math.round(r[0]), y: Math.round(r[1])}, {type: 'pointerDown', button: 2}, {type: 'pointerUp', button: 2}]}]});
    let open = false;
    for (let i = 0; i < 20 && !open; i++) { open = await ev(`!document.querySelector('#pop').classList.contains('hidden') && /New folder/.test(document.querySelector('#pop').textContent)`); if (!open) await sleep(150); }
    check(open, 'Firefox: a real right click opens the folder menu');
    await shot('p2168-4-b-wiki-ctx.png');
  }, false);

  console.log(`\n${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
