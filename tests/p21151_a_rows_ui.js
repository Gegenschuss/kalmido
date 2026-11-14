// 2.1151.0 part A UI tests (#3835 stage 1): the phone rows of files, knowledge and tables without symbols, a long press = the menu.
// kalmido-suite: fresh
// Own container (start.sh), Firefox (real layout and a real finger): 390 px touch, then 1280 px mouse. Invented data only.
// freelancer-matrix: files - frida has no organisation: everything in her private workspace.
// - phone: the row's symbols are hidden (1 px, still in the page for screen readers), the name is fully visible
// - a long press opens the row's menu with the expected entries ("Select" on top where rows can be chosen); the click that
//   ends the press opens nothing; one entry works (Select / Open)
// - the files "From Knowledge" (no menu before) and a page's files get a menu too
// - computer: the symbols stay as they were
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21151_a_rows_ui', check, shots: 'P21151A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,files,wiki,sheets';
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==', 'base64');
const J = JSON.stringify;

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: J({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(fu.http < 300 && ((await call(CF, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'frida is in no organisation');
  // files: a folder and a file in My files
  const DIR = (await call(CF, 'POST', '/api/files/folders', {space: 'private', name: 'Contracts and offers'})).id;
  const fd0 = new FormData(); fd0.append('file', new Blob(['plain text']), 'Tax statement 2026.txt'); fd0.append('space', 'private');
  const FILE = (await (await fetch(B + 'api/files/upload', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CF}, body: fd0})).json()).items?.[0]?.id;
  check(DIR && FILE, 'setup: a folder and a file');
  // knowledge: a folder, a page in it with a file (the file store's "From Knowledge" too)
  check((await call(CF, 'POST', '/api/wiki/folders', {space: 'private', name: 'Handbook for the team'})).http === 201, 'setup: a knowledge folder');
  const pg = await call(CF, 'POST', '/api/wiki/pages', {space: 'private', path: 'Handbook for the team/Start here', body: 'Welcome'});
  check(pg.http === 201 && pg.id, 'setup: a page');
  const fd = new FormData(); fd.append('file', new Blob([PNG], {type: 'image/png'}), 'plan.png');
  check((await fetch(B + `api/wiki/pages/${pg.id}/files`, {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CF}, body: fd})).ok, 'setup: a file on the page');
  // tables: a folder and a table
  check((await call(CF, 'POST', '/api/sheets/folders', {space: 'private', name: 'Customers'})).http === 201, 'setup: a folder of the tables');
  const SH = (await call(CF, 'POST', '/api/sheets', {title: 'Budget overview 2026', space: 'private'})).id;
  check(SH, 'setup: a table');

  const login2 = ev => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'frida', password: 'password123'})}).then(r => r.status)`);
  // the width of an element (0 = missing), and whether a name is fully visible (not cut, inside the screen)
  const W = (ev, sel) => ev(`(() => { const e = document.querySelector(${J(sel)}); return e ? Math.round(e.getBoundingClientRect().width) : 0; })()`);
  const full = (ev, sel) => ev(`(() => { const e = document.querySelector(${J(sel)}); if (!e) return 'missing'; const r = e.getBoundingClientRect();
    return e.scrollWidth <= e.clientWidth + 1 && r.right <= innerWidth + 1 && r.width > 20 ? true : JSON.stringify({sw: e.scrollWidth, cw: e.clientWidth, right: r.right, vw: innerWidth}); })()`);
  const items = ev => ev(`[...document.querySelectorAll('#pop:not(.hidden) [role="menuitem"]')].map(b => b.textContent.trim())`);
  const pick = (ev, label) => ev(`(() => { const b = [...document.querySelectorAll('#pop:not(.hidden) [role="menuitem"]')].find(b => b.textContent.trim() === ${J(label)}); b?.click(); return !!b; })()`);

  // ================= phone, a finger
  await firefox(async ({cmd, ev, ctx, nav, shot, drag, until}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await login2(ev) === 200, 'phone: login');
    // another view of the same page by its address; a phone's menu sheet closes by a step back in the history (backclose.js),
    // which would undo a new address set before it lands: close it, wait for that step, then set the address
    const go = async h => {
      await ev(`(() => { if (typeof closePop === 'function') closePop(); return 1; })()`);
      const calm = `document.querySelector('#pop')?.classList.contains('hidden') !== false && (typeof f8d_bk !== 'object' || !f8d_bk.skip && !f8d_bk.queued && !f8d_bk.pushed)`;  // backclose.js: no Back of ours on its way
      for (let k = 0; k < 3; k++) {
        await until(calm, {timeout: 3000});
        await ev(`(() => { location.hash = ${J(h)}; return 1; })()`);
        if (await until(`location.hash === ${J(h)} && ${calm}`, {timeout: 3000})) return true;
      }
      return false;
    };
    const dbg = () => ev(`JSON.stringify({h: location.hash, cls: [...document.querySelectorAll('#view [class]')].slice(0, 12).map(e => e.className).join('|'), t: (document.querySelector('#view')?.innerText || '').slice(0, 300)})`);  // what the view showed (a failure's message)
    // a real long press (800 ms, no move) on the middle of sel; the menu's entries
    const hold = async sel => {
      await ev(`(() => { if (typeof closePop === 'function') closePop(); return 1; })()`);
      const p = await ev(`(() => { const e = document.querySelector(${J(sel)}); if (!e) return null; e.scrollIntoView({block: 'center'}); const r = e.getBoundingClientRect(); return [r.left + Math.min(r.width / 2, 80), r.top + r.height / 2]; })()`);
      if (!p) return [];
      await drag(p[0], p[1], 0, 0, 'touch', 800);
      await until(`document.querySelectorAll('#pop:not(.hidden) [role="menuitem"]').length > 0`, {timeout: 5000});
      return items(ev);
    };

    // ---- files
    await nav(B + '#ablage/s/private');
    check(await until(`!!document.querySelector('#view .abrow[data-abid="${FILE}"] .abname')`, {timeout: 20000}), 'phone files: the file row');
    check(await W(ev, `#view .abrow[data-abid="${FILE}"] [data-ab="menu"]`) <= 1 && await ev(`!!document.querySelector('#view .abrow[data-abid="${FILE}"] [data-ab="menu"]')`), 'phone files: the "…" is hidden, still in the page');
    const fn = await full(ev, `#view .abrow[data-abid="${FILE}"] .abname`);
    check(fn === true, 'phone files: the name is fully visible ' + fn);
    await shot('p21151a-files-phone.png');
    let m = await hold(`#view .abrow[data-abid="${FILE}"] .abname`);
    check(['Select', 'Open', 'Download', 'Rename…', 'Move to the trash'].every(t => m.includes(t)) && m.indexOf('Select') < m.indexOf('Open'), 'phone files: a long press opens the menu, Select on top ' + J(m));
    check(!(await ev(`!!document.querySelector('.docview, .lightbox, .pvwrap')`)), 'phone files: the press opened no file');
    check(await pick(ev, 'Select') && await until(`!!document.querySelector('.mselbar') && /1 selected/.test(document.querySelector('.mselbar').textContent)`, {timeout: 5000}), 'phone files: Select starts choosing with the row');
    await ev(`(() => { document.querySelector('.mselbar [data-ab$="close"], .mselbar .mbx')?.click(); return 1; })()`);
    // ---- files "From Knowledge"
    await go('#ablage/aus-wiki');
    check(await until(`!!document.querySelector('#view .abcollg .abrow .abname')`, {timeout: 20000}), 'phone From Knowledge: the file row');
    check(await W(ev, '#view .abcollg .abrow a.iconbtn[download]') <= 1, 'phone From Knowledge: the download symbol is hidden');
    m = await hold('#view .abcollg .abrow .abname');
    check(m[0] === 'Open' && m.some(t => /^Download/.test(t)), 'phone From Knowledge: a long press offers Open and Download ' + J(m));
    await ev(`(() => { closePop(); return 1; })()`);

    // ---- knowledge: the folder list
    await go('#wiki');
    check(await until(`!!document.querySelector('#view .wkrow .wkmore')`, {timeout: 20000}), 'phone knowledge: the rows with their "…" ' + await dbg());
    check(await W(ev, '#view .wkrow .wkmore') <= 1, 'phone knowledge: the "…" is hidden');
    const wn = await full(ev, '#view .wkrow .wkitem > span');
    check(wn === true, 'phone knowledge: the name is fully visible ' + wn);
    await shot('p21151a-wiki-phone.png');
    const h0 = await ev('location.hash');
    m = await hold('#view .wkrow .wkitem > span');
    check(['Select', 'Rename…', 'Move to…', 'Move to the trash'].every(t => m.includes(t)), 'phone knowledge: a long press opens the row menu ' + J(m));
    check(await ev('location.hash') === h0, 'phone knowledge: the press opened nothing');
    await ev(`(() => { closePop(); return 1; })()`);
    // ---- knowledge: a page's files
    await go('#wiki/' + pg.id);
    check(await until(`!!document.querySelector('#view .wkfiles a.wkfile')`, {timeout: 20000}), 'phone page: its file');
    check(await W(ev, '#view .wkfiles li > .iconbtn') <= 1, 'phone page: the file\'s symbols are hidden');
    m = await hold('#view .wkfiles a.wkfile .an');
    check(m[0] === 'Open' && m.includes('Copy link'), 'phone page: a long press on a file: Open, Copy link ' + J(m));
    await ev(`(() => { closePop(); return 1; })()`);

    // ---- tables
    await go('#sheets');
    check(await until(`!!document.querySelector('#view .shvcard[data-id="${SH}"] .shvct b')`, {timeout: 20000}), 'phone tables: the table ' + SH + ' ' + await dbg());
    check(await W(ev, `#view .shvcard[data-id="${SH}"] [data-shv="cmenu"]`) <= 1 && await W(ev, '#view .shfcard [data-shf="fmenu"]') <= 1, 'phone tables: the "…" of tables and folders are hidden');
    const tn = await full(ev, `#view .shvcard[data-id="${SH}"] .shvct b`);
    check(tn === true, 'phone tables: the name is fully visible ' + tn);
    await shot('p21151a-sheets-phone.png');
    m = await hold(`#view .shvcard[data-id="${SH}"] .shvct b`);
    check(['Open', 'Rename…', 'Delete'].every(t => m.includes(t)), 'phone tables: a long press opens the menu ' + J(m));
    check(await ev(`location.hash`) === '#sheets', 'phone tables: the press opened nothing');
    check(await pick(ev, 'Open') && await until(`location.hash === '#sheets/${SH}'`, {timeout: 5000}), 'phone tables: Open opens the table');
    m = await (async () => { await go('#sheets'); await until(`!!document.querySelector('#view .shfcard .shvct b')`, {timeout: 20000}); return hold('#view .shfcard .shvct b'); })();
    check(m.includes('Rename…'), 'phone tables: a long press on a folder opens its menu ' + J(m));
  }, true);

  // ================= computer, a mouse: nothing changes
  await firefox(async ({cmd, ev, ctx, nav, until}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 860}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    check(await login2(ev) === 200, 'computer: login');
    const go = h => ev(`(() => { location.hash = ${J(h)}; return 1; })()`);
    await nav(B + '#ablage/s/private');
    check(await until(`!!document.querySelector('#view .abrow[data-abid="${FILE}"] [data-ab="menu"]')`, {timeout: 20000}) && await W(ev, `#view .abrow[data-abid="${FILE}"] [data-ab="menu"]`) >= 24, 'computer files: the "…" stays');
    await go('#wiki/' + pg.id);
    check(await until(`!!document.querySelector('#view .wkfiles li > .iconbtn')`, {timeout: 20000}) && await W(ev, '#view .wkfiles li > .iconbtn') >= 24, 'computer page: the file\'s symbols stay');
    await go('#sheets');
    check(await until(`!!document.querySelector('#view .shvcard[data-id="${SH}"] [data-shv="cmenu"]')`, {timeout: 20000}) && await W(ev, `#view .shvcard[data-id="${SH}"] [data-shv="cmenu"]`) >= 24, 'computer tables: the "…" stays');
  }, false);

  console.log(`\np21151_a_rows_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
