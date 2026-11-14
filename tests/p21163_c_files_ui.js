// Release 2.1163.0 part C (#6111, #6112) UI tests: Files on a phone and its words.
// kalmido-suite: fresh
// Own container (start.sh), jsdom for setup and the words, Firefox for the widths (360 phone with a finger, 1280 computer).
// Invented names and files only.
// - #6111 phone (360 x 740): above the files ONE tool row (Upload + "…"); the first file stands in the visible area; its name
//   is readable (no "Text recognised" mark in the row, the full name as title); the path is one line ("…" for the folders
//   further up, the parent), the open folder's name is the heading; "…" opens the other tools and they work (New folder asks
//   for a name, Select starts choosing); the path's "…" goes to a folder further up; the documents' bar: search, Filter,
//   Sorting, "+", "…" in one row, no second funnel
// - #6111 computer (1280): the tools as before in their row, no "…" of the phone, the whole path, no heading below it
// - #6112 words (German): the area is "Dateien", Move to the trash, the tab "Zugriff", malware "Blockiert", no server words in
//   the trash note, plurals (1 Blatt / 1 Tag / 1 Seite), "Dateien wählen"
// freelancer-matrix: files (alice has no organisation: her private workspace)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21163_c_files_ui', check, shots: 'P21163C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21163C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); let j = {}; try { j = await r.json(); } catch { /* no body */ } return {http: r.status, ...j}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const upFile = async (parent, name, text) => {
  const fd = new FormData(); fd.append('parent_id', String(parent)); fd.append('file', new Blob([text], {type: 'text/plain'}), name);
  return ((await (await fetch(B + 'api/files/upload', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd})).json().catch(() => ({}))).items || [])[0]?.id;
};

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const st0 = await call('GET', '/api/state');
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'files', 'docs'])].join(',');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: feats, workspace: 'private'});
  check(!(st0.me.workspaces || []).length, 'setup: alice has no organisation (a person on her own)');
  // a path three folders deep: Summer film / Raw footage / Shoot day 1, with files in the deepest
  const TOP = (await call('POST', '/api/files/folders', {space: 'private', name: 'Summer film'})).id;
  const MID = (await call('POST', '/api/files/folders', {name: 'Raw footage', parent_id: TOP})).id;
  const DEEP = (await call('POST', '/api/files/folders', {name: 'Shoot day 1', parent_id: MID})).id;
  const NAME = 'Still 01 sunset.txt';
  const F1 = await upFile(DEEP, NAME, 'An invented still, a sunset over the sea');
  const F2 = await upFile(DEEP, 'Call sheet day one with a rather long name for narrow phones.txt', 'An invented call sheet');
  check(TOP && MID && DEEP && F1 && F2, `setup: three folders deep, two files ${[TOP, MID, DEEP, F1, F2]}`);
  // the text recognition runs in the background: wait for its state (the mark a row no longer shows)
  const txt = await until(async () => ((await call('GET', `/api/files?parent=${DEEP}`)).items || []).find(x => x.id === F1)?.up?.text, 200);
  check(!!txt, 'setup: the text recognition has a state for the file ' + txt);

  // ================= jsdom: the row, the path, the tools' markup (computer)
  let w = await boot({user: 'alice', hash: 'ablage/' + DEEP}), d = w.document;
  check(await until(() => d.querySelector(`.abview .ablist .abrow[data-abid="${F1}"]`)), 'the folder lists its files');
  const row = d.querySelector(`.abrow[data-abid="${F1}"]`);
  check(row && !row.querySelector('.ftxtmark') && row.querySelector('.abname')?.getAttribute('title') === NAME, '#6111: no text mark in the row, the name has its title ' + (row?.innerHTML || '').slice(0, 300));
  check(w.eval(`ab_rowHtml({id: 9, kind: 'file', name: 'x.pdf', role: 'owner', up: {text: 'found'}}, false)`).indexOf('ftxtmark') < 0
    && w.eval(`ab_rowHtml({id: 9, kind: 'file', name: 'x.pdf', role: 'owner', up: {scan: 'infected', sig: 'X'}}, false)`).includes('scnbad'), '#6111: a row never shows "Text recognised", the malware mark stays');
  check(d.querySelector('.abcrumbs .abcell[data-ab="crumbs"]') && d.querySelector('.abcrumbs .abcfar') && /Shoot day 1/.test(d.querySelector('.abcurh')?.textContent || ''), '#6111: the path has "…" for the far folders and the heading of the open folder');
  check(d.querySelector('.abtools [data-abmore]') && d.querySelector('.abtools .abwide [data-ab="new-folder"]') && !d.querySelector('.abtools .abwide [data-ab="upload"]'), '#6111: Upload stays out of "…", New folder is a wrapped tool');
  w.close();

  // ================= #6112: the words (German)
  await call('PATCH', '/api/settings', {lang: 'de'});
  w = await boot({user: 'alice', hash: 'ablage/' + DEEP}); d = w.document;
  check(await until(() => d.querySelector(`.abview .abrow[data-abid="${F1}"]`)), 'German: the folder');
  const de = k => w.eval(k);
  check(de(`tr('File store')`) === 'Dateien' && de(`tr('Files')`) === 'Dateien', '#6112: the area is "Dateien" ' + de(`tr('File store')`));
  check(de(`tr('Show in the file store')`) === 'In Dateien anzeigen', '#6112: "In Dateien anzeigen" ' + de(`tr('Show in the file store')`));
  check(!/Lösch-Läufe|Server/.test(de(`trashNote('x', true)`).replace('diesem Server', '')) && /Papierkorb/.test(de(`trashNote('x', true)`)), '#6112: the trash note without server words ' + de(`trashNote('x', true)`));
  check(de(`trn('+{0} more sheet', '+{0} more sheets', 1)`) === '+1 weiteres Blatt' && de(`trn('+{0} more sheet', '+{0} more sheets', 3)`) === '+3 weitere Blätter', '#6112: one sheet, three sheets');
  check(de(`trn('{0} day after {1}', '{0} days after {1}', 1, 'X')`) === '1 Tag nach X' && de(`trn('{0} page', '{0} pages', 1)`) === '1 Seite', '#6112: 1 Tag, 1 Seite');
  check(de(`tr('Shares')`) === 'Zugriff', '#6112: the tab of the file view is "Zugriff" ' + de(`tr('Shares')`));
  check(/Blockiert/.test(de(`upMarkHtml({scan: 'infected', sig: 'X'})`)) && !/Gesperrt/.test(de(`upMarkHtml({scan: 'infected', sig: 'X'})`)), '#6112: malware is "Blockiert"');
  check(de(`tr('Move to the trash')`) === 'In den Papierkorb' && de(`tr('Move “{0}” to the trash', 'a')`) === '„a“ in den Papierkorb', '#6112: "In den Papierkorb"');
  w.eval('AB.selOn = true; ab_draw()');
  check(await until(() => /Dateien wählen/.test(d.querySelector('#ab-sbar .mcount')?.textContent || '')), '#6112: the selection bar says "Dateien wählen" ' + (d.querySelector('#ab-sbar')?.textContent || ''));
  check(d.querySelector('#ab-sbar [data-absel="trash"]')?.getAttribute('aria-label') === 'In den Papierkorb', '#6112: the bar\'s Trash = "In den Papierkorb"');
  w.eval('AB.selOn = false; ab_draw()');
  check(d.querySelector('.abview .abspaces')?.getAttribute('aria-label') === 'Dateien', '#6112: the spaces are named "Dateien"');
  w.close();
  await call('PATCH', '/api/settings', {lang: 'en'});

  // ================= Firefox: phone 360 (finger) and computer 1280 (mouse)
  const login2 = `fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`;
  const vis = `const vis = e => !!e && getComputedStyle(e).display !== 'none' && getComputedStyle(e).visibility !== 'hidden' && e.getBoundingClientRect().width > 0;`;
  await firefox(async o => {
    const {cmd, ev, ctx, shot, nav, idle} = o;
    const wait = async (js, n = 80) => { for (let i = 0; i < n; i++) { if (await ev(js).catch(() => false)) return true; await sleep(150); } return false; };
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 360, height: 740}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await ev(login2) === 200, 'Firefox: login');
    await nav(B + '#ablage/' + DEEP);
    check(await wait(`!!document.querySelector('.abview .abrow[data-abid="${F1}"]')`), 'phone: the folder with its files');
    await idle();
    const m = await ev(`(() => { ${vis}
      const t = document.querySelector('.abview .abtools'), its = t ? [...t.querySelectorAll('button, label, .seg')].filter(vis) : [];
      const rs = its.map(e => e.getBoundingClientRect()), first = document.querySelector('.abview .ablist .abrow')?.getBoundingClientRect();
      const nm = document.querySelector('.abrow[data-abid="${F1}"] .abname'), cr = document.querySelector('.abcrumbs'), h = document.querySelector('.abcurh');
      return {n: its.length, what: its.map(e => e.dataset.ab || e.dataset.abmore && 'more' || e.className).join(','),
        oneRow: !rs.length || Math.max(...rs.map(x => x.top)) < Math.min(...rs.map(x => x.bottom)),
        first: first ? Math.round(first.bottom) : -1, vh: innerHeight, nameFull: !!nm && nm.scrollWidth <= nm.clientWidth + 1, name: nm?.textContent,
        crH: Math.round(cr?.getBoundingClientRect().height || 0), crOver: cr ? cr.scrollWidth > cr.clientWidth + 1 : true, cell: vis(document.querySelector('.abcell')),
        far: [...document.querySelectorAll('.abcrumbs .abcfar')].some(vis), head: vis(h) ? h.textContent : '', sw: document.documentElement.scrollWidth, vw: innerWidth}; })()`);
    check(m.n === 2 && /upload/.test(m.what) && /more/.test(m.what) && m.oneRow, `#6111 phone: ONE tool row - Upload and "…" ${JSON.stringify(m)}`);
    check(m.first > 0 && m.first <= m.vh, `#6111 phone: the first file stands in the visible area ${m.first} / ${m.vh}`);
    check(m.nameFull && m.name === NAME, `#6111 phone: the name is readable in full ${JSON.stringify(m)}`);
    check(m.crH > 0 && m.crH <= 48 && !m.crOver && m.cell && !m.far, `#6111 phone: the path is one line with "…" ${JSON.stringify(m)}`);
    check(m.head === 'Shoot day 1', `#6111 phone: the open folder is the heading ${JSON.stringify(m)}`);
    check(m.sw <= m.vw, `#6111 phone: nothing runs over the side ${m.sw} / ${m.vw}`);
    await shot('p21163c-360-folder.png');
    // "…" of the tools: the rest of the tools, then the folder's own menu; New folder asks for a name, Select starts choosing
    const items = async () => ev(`[...document.querySelectorAll('#pop:not(.hidden) [role="menuitem"]')].map(b => b.textContent.trim()).join('|')`);
    await ev(`(document.querySelector('.abtools [data-abmore]').click(), 1)`);
    check(await wait(`!!document.querySelector('#pop:not(.hidden) [role="menuitem"]')`), '#6111 phone: "…" opens a menu');
    const mi = await items();
    check(/New folder/.test(mi) && /Scan/.test(mi) && /Select/.test(mi) && /Rename/.test(mi), `#6111 phone: the menu has New folder, Scan, Select and the folder's own entries: ${mi}`);
    await shot('p21163c-360-more.png');
    await ev(`([...document.querySelectorAll('#pop:not(.hidden) [role="menuitem"]')].find(b => /New folder/.test(b.textContent)).click(), 1)`);
    check(await wait(`!!document.querySelector('.modal input')`), '#6111 phone: New folder from "…" asks for the name');
    await ev(`(() => { const i = document.querySelector('.modal input'); i.value = 'Takes'; i.dispatchEvent(new Event('input', {bubbles: true})); document.querySelector('.modal [data-cd="yes"]').click(); return 1; })()`);
    check(await wait(`[...document.querySelectorAll('.abview .abrow .abname')].some(e => e.textContent === 'Takes')`), '#6111 phone: ... and the folder is there');
    await ev(`(document.querySelector('.abtools [data-abmore]').click(), 1)`);
    await wait(`!!document.querySelector('#pop:not(.hidden) [role="menuitem"]')`);
    await ev(`([...document.querySelectorAll('#pop:not(.hidden) [role="menuitem"]')].find(b => /^Select/.test(b.textContent.trim())).click(), 1)`);
    check(await wait(`AB.selOn && !!document.querySelector('#ab-sbar')`), '#6111 phone: Select from "…" starts choosing');
    await ev(`(document.querySelector('#ab-sbar [data-absel="close"]').click(), 1)`);
    await wait(`!AB.selOn`);
    // the path's "…": the folders further up
    await ev(`(document.querySelector('.abcrumbs .abcell').click(), 1)`);
    check(await wait(`!!document.querySelector('#pop:not(.hidden) [role="menuitem"]')`), '#6111 phone: the path\'s "…" opens the folders further up');
    const pi = await items();
    check(/Summer film/.test(pi) && !/Raw footage/.test(pi), `#6111 phone: ... the far folder, not the parent shown beside it: ${pi}`);
    await ev(`([...document.querySelectorAll('#pop:not(.hidden) [role="menuitem"]')].find(b => /Summer film/.test(b.textContent)).click(), 1)`);
    check(await wait(`location.hash === '#ablage/${TOP}'`), '#6111 phone: ... and opens it');
    // the documents' bar: search, Filter, Sorting, "+", "…" - one row after the search; one funnel
    await nav(B + '#ablage/docs');
    check(await wait(`!!document.querySelector('.dc-view .dc-bar [data-dc="more"]')`), 'phone: the documents\' bar');
    await idle();
    const b = await ev(`(() => { ${vis}
      const bar = document.querySelector('.dc-bar'), all = [...bar.querySelectorAll('button, label.btn, .ts-bar')].filter(vis).filter(e => !e.closest('.dc-seg'));
      const rs = all.map(e => e.getBoundingClientRect());
      const funnels = [...bar.querySelectorAll('svg')].filter(vis).filter(s => s.innerHTML === document.querySelector('.dc-bar [data-dc="more"] svg')?.innerHTML).length;
      return {n: all.length, what: all.map(e => e.dataset.dc || (e.dataset.abmore && 'more') || e.className).join(','), oneRow: Math.max(...rs.map(x => x.top)) < Math.min(...rs.map(x => x.bottom)), funnels,
        sw: document.documentElement.scrollWidth, vw: innerWidth}; })()`);
    check(b.n === 4 && /more/.test(b.what) && /sort/.test(b.what) && /dc-up/.test(b.what) && b.oneRow, `#6111 phone: the documents' bar - Filter, Sorting, "+", "…" in one row ${JSON.stringify(b)}`);
    check(b.funnels === 1 && b.sw <= b.vw, `#6111 phone: one funnel, nothing over the side ${JSON.stringify(b)}`);
    await ev(`(document.querySelector('.dc-bar [data-abmore]').click(), 1)`);
    check(await wait(`!!document.querySelector('#pop:not(.hidden) [role="menuitem"]')`), '#6111 phone: the documents\' "…" opens');
    const di = await items();
    check(/Save view/.test(di) && /Settings of the documents/.test(di) && /Scan/.test(di), `#6111 phone: ... with the saved view, the settings, Scan: ${di}`);
    await shot('p21163c-360-docs-more.png');
    await ev(`([...document.querySelectorAll('#pop:not(.hidden) [role="menuitem"]')].find(b => /Settings of the documents/.test(b.textContent)).click(), 1)`);
    check(await wait(`!!document.querySelector('.modal, #settings, .smodal')`), '#6111 phone: ... and the settings open from it');
  }, true);

  // ================= computer 1280 (mouse): as before
  await firefox(async o => {
    const {cmd, ev, ctx, shot, nav, idle} = o;
    const wait = async (js, n = 80) => { for (let i = 0; i < n; i++) { if (await ev(js).catch(() => false)) return true; await sleep(150); } return false; };
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 860}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await ev(login2) === 200, 'Firefox (mouse): login');
    await nav(B + '#ablage/' + DEEP);
    check(await wait(`!!document.querySelector('.abview .abrow[data-abid="${F1}"]')`), 'computer: the folder');
    await idle();
    const c = await ev(`(() => { ${vis}
      return {nf: vis(document.querySelector('.abtools [data-ab="new-folder"]')), scan: vis(document.querySelector('.abtools [data-ab="scan"]')), sel: vis(document.querySelector('.abtools [data-absel="mode"]')),
        more: vis(document.querySelector('.abtools [data-abmore]')), far: [...document.querySelectorAll('.abcrumbs .abcfar')].every(vis), cur: vis(document.querySelector('.abcrumbs .abccur')),
        cell: vis(document.querySelector('.abcell')), head: vis(document.querySelector('.abcurh'))}; })()`);
    check(c.nf && c.scan && c.sel && !c.more, `#6111 computer: the tools in their row, no "…" of the phone ${JSON.stringify(c)}`);
    check(c.far && c.cur && !c.cell && !c.head, `#6111 computer: the whole path, no heading below it ${JSON.stringify(c)}`);
    await shot('p21163c-1280-folder.png');
    await nav(B + '#ablage/docs');
    check(await wait(`!!document.querySelector('.dc-view .dc-bar [data-dc="more"]')`), 'computer: the documents');
    await idle();
    const e = await ev(`(() => { ${vis} const f = document.querySelector('.dc-bar [data-dc="more"] svg')?.innerHTML, s = document.querySelector('.dc-bar .dcv-save svg')?.innerHTML;
      return {save: vis(document.querySelector('.dc-bar .dcv-save')), same: !!f && f === s, more: vis(document.querySelector('.dc-bar [data-abmore]'))}; })()`);
    check(e.save && !e.same && !e.more, `#6111 computer: Save view has its own symbol (no second funnel), no "…" ${JSON.stringify(e)}`);
    await shot('p21163c-1280-docs.png');
  });

  console.log(`p21163_c_files_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
