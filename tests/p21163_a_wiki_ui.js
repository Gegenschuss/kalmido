// Release 2.1163.0 part A (#6087, #6089) UI tests: knowledge pages for a reader, and a calmer open page.
// kalmido-suite: fresh
// Own container (start.sh), Firefox with a mouse; invented pages only. Screenshots: P21163A_SHOTS (360 / 1280).
// #6087 rita, read-only member of Alpha: the list has no New page / Today / New folder (computer and phone), the open page reads
//   with its text and has a "…" with History (opens), Copy link, Copy as [[link]] - and nothing that writes
// #6089 frida, a person without an organisation (freelancer-matrix: wiki): an open page on a computer has no area bar above it,
//   one head (path from the workspace's name, title, "…"), and scrolls as a whole (no inner box, the footer after the text);
//   the page's "…" in groups Page / Folder / View on this device, Delete last, "Open items as tasks" in it (no big button
//   above the text); the phone's list is one row (Find, New page, "…") and its "…" has Today, New folder, Select
// freelancer-matrix: wiki
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21163_a_wiki_ui', check, shots: 'P21163A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21163A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const st0 = await call(CA, 'GET', '/api/state');
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'wiki'])].join(',');
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: feats});
  // rita: read-only member of Alpha
  const ORG = (await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: st0.me.id})).id;
  check(ORG > 0, 'setup: the organisation Alpha');
  await call(CA, 'POST', '/api/users', {username: 'rita', display_name: 'Rita', password: 'password123', email: 'rita@example.com'});
  const rm = await call(CA, 'PUT', `/api/orgs/${ORG}/members`, {email: 'rita@example.com', role: 'readonly'});
  check(rm.http < 300, 'setup: rita read-only in Alpha ' + rm.http);
  const RK = await login('rita');
  await call(RK, 'POST', `/api/orgs/${ORG}/join`, {});
  await call(RK, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: feats, workspace: 'org:' + ORG});
  const OP = (await call(CA, 'POST', '/api/wiki/pages', {space: 'org:' + ORG, path: 'Handbook/Rules', body: 'Read me before the shoot.\n\n- [ ] Bring the badge\n'})).id;
  check(OP > 0, 'setup: a page in Alpha');
  // frida: no organisation
  await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const FK = await login('frida');
  await call(FK, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: feats});
  check(!((await call(FK, 'GET', '/api/state')).me.workspaces || []).length, 'setup: frida has no organisation');
  const long = Array.from({length: 70}, (_, i) => `Step ${i + 1}: check the light, the sound and the props of the scene.`).join('\n\n');
  const LP = (await call(FK, 'POST', '/api/wiki/pages', {space: 'private', path: 'Notes/Long page', body: `${long}\n\n- [ ] Order paper\n- [ ] Call the studio\n\nThe last line.`})).id;
  check(LP > 0, 'setup: frida\'s long page');

  await firefox(async ({cmd, ev, ctx, nav, shot, until, idle}) => {
    const size = (w, h) => cmd('browsingContext.setViewport', {context: ctx, viewport: {width: w, height: h}});
    const signin = async u => {
      await nav(B + 'static/icon.svg');
      await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
      await ev(`fetch('/api/auth/logout', {method: 'POST', headers: {'X-Requested-With': 'kalmido'}}).then(r => r.status)`);
      check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`) === 200, `ff: login ${u}`);
    };
    const vis = sel => `(() => { const e = document.querySelector(${JSON.stringify(sel)}); return !!e && !!e.offsetWidth; })()`;
    // the page's "…": its group heads and entries in order
    const pmenu = () => ev(`(() => { document.querySelector('#view [data-wk="pmenu"]')?.click(); const p = document.querySelector('#pop:not(.hidden)'); if (!p) return null;
      return [...p.querySelectorAll('.mgh, [role="menuitem"]')].map(x => (x.classList.contains('mgh') ? 'H:' : '') + x.textContent.trim()); })()`);
    const pick = re => ev(`(() => { const b = [...document.querySelectorAll('#pop:not(.hidden) [role="menuitem"]')].find(x => ${re}.test(x.textContent.trim())); if (!b) return 0; b.click(); return 1; })()`);
    const closeAll = () => ev(`(() => { closePop?.(); document.querySelectorAll('.modal').forEach(m => m.remove()); return 1; })()`);

    // ================= #6087: the reader
    await signin('rita');
    for (const [W, Ht] of [[1280, 860], [360, 760]]) {
      await size(W, Ht);
      await nav(B + '?w=' + W + '#wiki/d/Handbook');
      if (W < 768) await nav(B + '?w=' + W + '#wiki');
      check(await until(`/Rules|Handbook/.test(document.querySelector('#view #wk-res')?.textContent || '')`, {timeout: 20000}), `#6087 ${W}: rita sees the pages of Alpha`);
      check(await until(`WK.idx['org:${ORG}']?.mayWrite === false`), `#6087 ${W}: rita may only read`);
      check(await ev(`!document.querySelector('#view [data-wk="new"]') && !document.querySelector('#view [data-wk="today"]') && !document.querySelector('#view [data-wk="newfolder"]')`), `#6087 ${W}: no New page, Today or New folder`);
      check(await ev(vis('#wk-q')), `#6087 ${W}: Find a page stays`);
      await shot(`p21163a-reader-list-${W}.png`);
      await nav(B + '?w=' + W + '#wiki/' + OP);
      check(await until(`/Read me before the shoot/.test(document.querySelector('#wk-md')?.textContent || '')`, {timeout: 20000}), `#6087 ${W}: the page reads with its text`);
      check(await ev(`!document.querySelector('#wk-cm') && !document.querySelector('#view [data-wk="pen"]')`), `#6087 ${W}: no editor, no pen`);
      const m = await pmenu();
      check(m && m.includes('History') && m.includes('Copy link') && m.includes('Copy as [[link]]'), `#6087 ${W}: the "…" has History and the links ${JSON.stringify(m)}`);
      check(m && !m.some(x => /^(Rename…|Delete|Edit as Markdown|Read-only|Share…)$/.test(x)), `#6087 ${W}: nothing that writes in the "…" ${JSON.stringify(m)}`);
      check(await pick('/^History$/') && await until(`!!document.querySelector('.modal:not(.hidden)')`), `#6087 ${W}: History opens`);
      await closeAll();
      check(await until(`/Alpha/.test(document.querySelector('#view .wkcrumbs')?.textContent || '')`), `#6089 ${W}: the path starts at the workspace's name (Alpha)`);
      await shot(`p21163a-reader-page-${W}.png`);
    }

    // ================= #6089: the open page on a computer (frida, no organisation)
    await signin('frida');
    await size(1280, 860);
    await nav(B + '?w=1280#wiki/' + LP);
    check(await until(`!!document.querySelector('#view .wkdesk.wkpgo article.wkpage #wk-cm .cm-content') && /Step 1:/.test(document.querySelector('#wk-cm')?.textContent || '')`, {timeout: 20000}), '#6089 1280: the page opens with its text');
    await idle();
    const pg = await ev(`(() => { const c = document.querySelector('#wk-cm'), v = document.querySelector('#view'), f = document.querySelector('#view article.wkpage .ntfoot');
      return {bar: !!document.querySelector('#view .wkbar'), heads: document.querySelectorAll('#view .wkpage > .nthead').length, h2: document.querySelector('#view .wkpage .nthead h2')?.textContent.trim(),
        crumbs: document.querySelector('#view .wkpage .wkcrumbs')?.textContent.trim(), inner: [c.scrollHeight, c.clientHeight], vsc: v.scrollHeight - v.clientHeight,
        dsc: document.scrollingElement.scrollHeight - innerHeight, foot: Math.round(f.getBoundingClientRect().top), ih: innerHeight, cbbar: !!document.querySelector('.wemcbbar')}; })()`);
    check(pg && !pg.bar && pg.heads === 1 && pg.h2 === 'Long page', '#6089 1280: no area bar above the page, one head with the title ' + JSON.stringify(pg));
    check(pg && /^Private/.test(pg.crumbs || ''), '#6089 1280: the path starts at the workspace\'s name ' + JSON.stringify(pg?.crumbs));
    check(pg && pg.inner[0] <= pg.inner[1] + 1, '#6089 1280: the text has no scroll box of its own ' + JSON.stringify(pg?.inner));
    check(pg && (pg.vsc > 100 || pg.dsc > 100) && pg.foot > pg.ih, '#6089 1280: the page scrolls as a whole, the footer after the text ' + JSON.stringify(pg));
    check(pg && !pg.cbbar, '#6089 1280: no "Open items as tasks" button above the text');
    await shot('p21163a-page-1280.png');
    // scrolled to the end: the last line and the footer in sight
    await ev(`(() => { document.querySelector('#view article.wkpage .ntfoot').scrollIntoView({block: 'end'}); return 1; })()`);
    check(await until(`(() => { const f = document.querySelector('#view article.wkpage .ntfoot').getBoundingClientRect(); return f.bottom <= innerHeight + 1 && f.top >= 0; })()`), '#6089 1280: scrolled down, the footer is in sight');
    await ev(`(() => { document.querySelector('#view .wkpage .nthead').scrollIntoView({block: 'start'}); return 1; })()`);
    // the page's "…" in groups, Delete last
    const m = await pmenu();
    const at = x => (m || []).indexOf(x);
    check(m && at('H:Page') === 0 && at('H:Folder') > at('H:Page') && at('H:View on this device') > at('H:Folder'), '#6089: the "…" in groups Page / Folder / View on this device ' + JSON.stringify(m));
    check(m && at('Rename…') > at('H:Page') && at('Rename…') < at('H:Folder') && at('Rename folder…') > at('H:Folder') && at('Rename folder…') < at('H:View on this device'), '#6089: Rename under Page, Rename folder under Folder ' + JSON.stringify(m));
    check(m && at('Page width…') > at('H:View on this device') && m[m.length - 1] === 'Delete', '#6089: Page width under View, Delete last ' + JSON.stringify(m));
    check(m && at('Open items as tasks · 2') > at('H:Page') && at('Open items as tasks · 2') < at('H:Folder'), '#6089: "Open items as tasks" under Page ' + JSON.stringify(m));
    check(await pick('/^Open items as tasks/') && await until(`!!document.querySelector('.modal.wemdlg')`), '#6089: "Open items as tasks" opens its dialog');
    await closeAll();
    // the list on a computer keeps its bar
    await nav(B + '?w=1280#wiki/d/Notes');
    check(await until(`!!document.querySelector('#view .wkbar [data-wk="new"]') && /Long page/.test(document.querySelector('#view #wk-res')?.textContent || '')`, {timeout: 20000}), '#6089 1280: the list keeps its bar with New page');

    // ================= #6089: the phone (360)
    await size(360, 760);
    await nav(B + '?w=360#wiki');
    check(await until(`/Notes/.test(document.querySelector('#view #wk-res')?.textContent || '')`, {timeout: 20000}), '#6089 360: the list');
    const row = await ev(`(() => { const r = s => document.querySelector(s)?.getBoundingClientRect(); const q = r('#wk-q'), n = r('#view [data-wk="new"]'), d = r('#view [data-wk="lmenu"]');
      return q && n && d ? {q: Math.round(q.top + q.height / 2), n: Math.round(n.top + n.height / 2), d: Math.round(d.top + d.height / 2), dr: Math.round(d.right), vw: innerWidth, sw: document.documentElement.scrollWidth,
        today: !!document.querySelector('#view .wkside [data-wk="today"]'), folder: !!document.querySelector('#view .wkside [data-wk="newfolder"]')} : null; })()`);
    check(row && Math.abs(row.q - row.n) <= 4 && Math.abs(row.n - row.d) <= 4 && row.dr <= row.vw && row.sw <= row.vw, '#6089 360: one row - Find, New page, "…" ' + JSON.stringify(row));
    check(row && !row.today && !row.folder, '#6089 360: Today and New folder are not extra buttons ' + JSON.stringify(row));
    await shot('p21163a-list-360.png');
    await ev(`(() => { document.querySelector('#view [data-wk="lmenu"]').click(); return 1; })()`);
    const lm = await until(`(() => { const t = [...document.querySelectorAll('#pop:not(.hidden) [role="menuitem"]')].map(x => x.textContent.trim()); return t.length ? t : null; })()`);
    check(lm && lm.includes('Today') && lm.includes('New folder…') && lm.includes('Select'), '#6089 360: the list\'s "…" has Today, New folder, Select ' + JSON.stringify(lm));
    check(await pick('/^Today$/'), '#6089 360: Today picked');
    check(await until(`/^#wiki\\/\\d+$/.test(location.hash) && /journal/.test(WK.pg?.path || '')`, {timeout: 20000}), '#6089 360: Today opens the daily note');
    await nav(B + '?w=360#wiki/' + LP);
    check(await until(`/Step 1:/.test(document.querySelector('#view .wkpage')?.textContent || '')`, {timeout: 20000}), '#6089 360: the page opens');
    check(await until(`/Private/.test(document.querySelector('#view .wkpage .wkcrumbs')?.textContent || '')`), '#6089 360: the phone names the workspace in the path');
    check(await ev(`!document.querySelector('.wemcbbar')`), '#6089 360: no "Open items as tasks" button above the text');
    await shot('p21163a-page-360.png');
  });

  console.log(`p21163_a_wiki_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
