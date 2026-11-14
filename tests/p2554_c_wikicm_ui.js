// kalmido-suite: fresh
// 2.554.0 C (#4052): knowledge pages have ONE editor on CodeMirror 6 (static/js/wkcm.js), Firefox with real keys and clicks.
// frida = a person WITHOUT an organisation (her private space), rita = a read-only member of an organisation.
// - a page opens ready to type: no Read / Edit switch, no Source / Preview button; typed text is saved
// - round trip: the text in, nothing typed, the same text out (front matter, trailing spaces, tabs, a table, a box), no save
// - ** of bold text only shows while the cursor is inside it, else the word is drawn bold
// - a table is drawn as a table: a click edits that cell only, Tab goes to the next one, the Markdown follows
// - a box ticks with the first click and is saved; a [[link]] opens with the first click
// - "Edit as Markdown" in the "…" menu is the plain field (the way out) and back; "Read-only" locks it on this device
// - without the right to write: the read view, no editor, no "…" menu
// - phone 390 px: the page is read first, the pen opens the same editor, "Done" goes back to reading
// freelancer-matrix: wiki
// Invented texts only. Screenshots: P2554C_SHOTS (desktop + 390 px).
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login, until: waitFor} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2554C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const firefox = require('./ff')({tag: 'p2554_c_wikicm_ui', check, shots: 'P2554C_SHOTS'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const ROUND = '---\ntags: demo\n---\n# Title  \n\nSome **bold** word and `code`.\t\n\n| Name | Count |\n| --- | ---: |\n| apple | 3 |\n|  | 4 |\n\n- [ ] Box one\n- [x] Box two\n\nSee [[Other]] and [web](https://example.com).\n   \n';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const st0 = await call(CA, 'GET', '/api/state');
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'wiki'])].join(',');
  await call(CA, 'PATCH', '/api/settings', {tour: 'done', lang: 'en', features: feats});
  await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CK = await login('frida');
  await call(CK, 'PATCH', '/api/settings', {tour: 'done', lang: 'en', features: feats});
  check(((await call(CK, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'setup: frida has no organisation');
  const other = (await call(CK, 'POST', '/api/wiki/pages', {space: 'private', path: 'Other', body: 'The other page.'})).id;
  const pg = await call(CK, 'POST', '/api/wiki/pages', {space: 'private', path: 'Round', body: ROUND});
  const id = pg.id;
  check(id && other, 'setup: the pages');
  const page = () => call(CK, 'GET', `/api/wiki/pages/${id}`);
  const t0 = (await page()).updated_at;
  // rita: read-only member of Alpha, a page there
  const ORG = (await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: st0.me.id})).id;
  await call(CA, 'POST', '/api/users', {username: 'rita', display_name: 'Rita', password: 'password123', email: 'rita@example.com'});
  const rm = await call(CA, 'PUT', `/api/orgs/${ORG}/members`, {email: 'rita@example.com', role: 'readonly'});
  check(rm.http < 300, 'setup: rita read-only in Alpha ' + rm.http);
  const RK = await login('rita');
  await call(RK, 'POST', `/api/orgs/${ORG}/join`, {});
  await call(RK, 'PATCH', '/api/settings', {tour: 'done', lang: 'en', features: feats});
  const OP = (await call(CA, 'POST', '/api/wiki/pages', {space: 'org:' + ORG, path: 'Rules', body: '# Rules\n\nRead **me**.\n'})).id;

  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    const until = (expr, ms = 15000) => waitFor(() => ev(expr).catch(() => null), {timeout: ms, step: 150});
    const act = actions => cmd('input.performActions', {context: ctx, actions}).then(() => cmd('input.releaseActions', {context: ctx}));
    const keys = vs => act([{type: 'key', id: 'k', actions: vs.flatMap(c => [{type: 'keyDown', value: c}, {type: 'keyUp', value: c}])}]);
    const type = s => keys([...s]);
    const click = async sel => {
      const c = await ev(`(() => { const e = ${sel}; if (!e) return null; e.scrollIntoView({block: 'center'}); const r = e.getBoundingClientRect(); return {x: Math.round(r.left + Math.min(8, r.width / 2)), y: Math.round(r.top + r.height / 2)}; })()`);
      if (!c) return false;
      await act([{type: 'pointer', id: 'p1', parameters: {pointerType: 'mouse'}, actions: [{type: 'pointerMove', x: c.x, y: c.y}, {type: 'pointerDown', button: 0}, {type: 'pointerUp', button: 0}]}]);
      return true;
    };
    const size = (width, height) => cmd('browsingContext.setViewport', {context: ctx, viewport: {width, height}});
    const saved = fn => waitFor(async () => fn((await page()).body || ''), {timeout: 15000, step: 200});
    const signin = u => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
    const cm = `document.querySelector('#wk-cm .cm-content')`;
    const lineOf = t => `[...document.querySelectorAll('#wk-cm .cm-line')].find(l => l.textContent.includes(${JSON.stringify(t)}))`;
    const sel = at => ev(`(() => { WKCM.view.dispatch({selection: {anchor: ${at}}}); WKCM.view.focus(); return 1; })()`);

    await nav(B + 'static/icon.svg');
    await signin('frida');
    await size(1280, 900);
    await nav(B + `#wiki/${id}`);
    check(await until(`!!${cm}`), 'desktop: the editor is there without any switch');
    check(await ev(`!document.querySelector('[data-wk="mode"]') && !document.querySelector('[data-wem="src"]') && !document.querySelector('#wk-body')`), 'desktop: no Read / Edit, no Source / Preview, no plain field');
    check(await ev(`${cm}.getAttribute('aria-label') === 'Text: Round' && ${cm}.contentEditable === 'true'`), 'desktop: the editable text carries the page\'s name ' + await ev(`${cm}?.getAttribute('aria-label')`));

    // ---- round trip: nothing typed, the same text out, no save
    check(await ev(`wk_src(WK.pg).value === ${JSON.stringify(ROUND)}`), 'round trip: the editor gives the page\'s text back unchanged');
    await click(lineOf('Some'));
    await sleep(300);
    await ev(`(() => { document.activeElement?.blur(); return 1; })()`);
    await sleep(1500);
    const pr = await page();
    check(pr.body === ROUND && pr.updated_at === t0, 'round trip: focus and blur without typing save nothing ' + JSON.stringify([pr.body === ROUND, pr.updated_at, t0]));

    // ---- ** only at the cursor
    const boldLine = lineOf('Some');
    await sel(`WKCM.view.state.doc.toString().indexOf('# Title')`);  // the cursor elsewhere
    check(await until(`!${boldLine}.textContent.includes('**') && !!${boldLine}.querySelector('.cm-wkb')`), 'marks: bold drawn, ** hidden while the cursor is elsewhere');
    check(await ev(`${lineOf('Title')}.textContent.includes('# Title')`), 'marks: the heading\'s # shows on its own line (the cursor is there)');
    await sel(`WKCM.view.state.doc.toString().indexOf('bold') + 2`);
    check(await until(`${boldLine}.textContent.includes('**bold**')`), 'marks: ** shows while the cursor is inside the bold word');
    check(await until(`!${lineOf('Title')}.textContent.includes('#')`), 'marks: the # of the heading hides when the cursor left its line');

    // ---- typing (no mode switch), saved
    await sel(`WKCM.view.state.doc.toString().indexOf(' word and')`);
    await type(' fresh');
    check(await saved(b => b.includes('**bold** fresh word')), 'typing: the text is saved');

    // ---- a table: click a cell, type, Tab to the next one
    check(await until(`!!document.querySelector('#wk-cm .cm-wktbl td')`), 'table: drawn as a table');
    check(await ev(`!document.querySelector('#wk-cm .cm-wktbl').textContent.includes('---')`), 'table: no delimiter row in the drawing');
    await click(`[...document.querySelectorAll('#wk-cm .cm-wktbl td')].find(t => t.textContent.trim() === 'apple')`);
    check(await until(`document.activeElement?.classList.contains('cm-wkcell') && document.activeElement.value === 'apple'`), 'table: the click edits that cell');
    await keys(['']);  // End
    await type('s');
    await keys(['']);  // Tab
    check(await until(`document.activeElement?.classList.contains('cm-wkcell') && document.activeElement.value === '3'`), 'table: Tab goes to the next cell');
    await keys(['']);
    check(await until(`document.activeElement?.classList.contains('cm-wkcell') && document.activeElement.value === ''`), 'table: Tab into the empty cell of the next row');
    await type('pear');
    check(await saved(b => b.includes('| apples | 3 |') && b.includes('| pear | 4 |') && b.includes('| --- | ---: |')), 'table: the cells are written back into the Markdown ' + JSON.stringify((await page()).body));
    await ev(`(() => { document.activeElement?.blur(); return 1; })()`);
    await shot('p2554c-desktop.png');

    // ---- a box ticks with the first click
    await click(`${lineOf('Box one')}.querySelector('input[type="checkbox"]')`);
    check(await saved(b => b.includes('- [x] Box one')), 'box: the first click ticks it and it is saved');
    check(await until(`${lineOf('Box one')}.querySelector('input[type="checkbox"]').checked`), 'box: drawn ticked');

    // ---- "Edit as Markdown" (the way out) and back
    await ev(`(() => { document.querySelector('[data-wk="pmenu"]').click(); return 1; })()`);
    check(await until(`!![...document.querySelectorAll('#pop [role="menuitem"]')].find(b => /Edit as Markdown/.test(b.textContent))`) && await click(`[...document.querySelectorAll('#pop [role="menuitem"]')].find(b => /Edit as Markdown/.test(b.textContent))`), 'the menu entry is there and clicked');
    check(await until(`!!document.querySelector('#wk-body') && !document.querySelector('#wk-cm')`), 'markdown: the plain field');
    check(await ev(`document.querySelector('#wk-body').value.includes('- [x] Box one') && document.querySelector('#wk-body').value.includes('| pear | 4 |')`), 'markdown: the field holds the saved text');
    await ev(`(() => { const t = document.querySelector('#wk-body'); t.focus(); t.setSelectionRange(t.value.length, t.value.length); return 1; })()`);
    await type('Plain end');
    check(await saved(b => b.endsWith('Plain end')), 'markdown: typing there saves too');
    await ev(`(() => { document.querySelector('[data-wk="pmenu"]').click(); return 1; })()`);
    check(await until(`!![...document.querySelectorAll('#pop [role="menuitem"]')].find(b => /Back to the editor/.test(b.textContent))`) && await click(`[...document.querySelectorAll('#pop [role="menuitem"]')].find(b => /Back to the editor/.test(b.textContent))`), 'the menu entry is there and clicked');
    check(await until(`!!${cm} && !document.querySelector('#wk-body') && WKCM.view.state.doc.toString().endsWith('Plain end')`), 'markdown: back in the editor with the new text');

    // ---- "Read-only" lock and back
    // 2.658.0 (#5091): a menu entry is clicked only once it is there (click() returned false silently before, CI v2.646)
    await ev(`(() => { document.querySelector('[data-wk="pmenu"]').click(); return 1; })()`);
    check(await until(`!![...document.querySelectorAll('#pop [role="menuitem"]')].find(b => /^Read-only/.test(b.textContent.trim()))`) && await click(`[...document.querySelectorAll('#pop [role="menuitem"]')].find(b => /^Read-only/.test(b.textContent.trim()))`), 'the menu entry is there and clicked');
    check(await until(`!!document.querySelector('#wk-md') && !document.querySelector('#wk-cm')`), 'read only: the read view on this device');
    await ev(`(() => { document.querySelector('[data-wk="pmenu"]').click(); return 1; })()`);
    check(await until(`!![...document.querySelectorAll('#pop [role="menuitem"]')].find(b => /^Read-only/.test(b.textContent.trim()))`) && await click(`[...document.querySelectorAll('#pop [role="menuitem"]')].find(b => /^Read-only/.test(b.textContent.trim()))`), 'the menu entry is there and clicked');
    check(await until(`!!${cm}`), 'read only: off again, the editor');

    // ---- a [[link]] opens with the first click
    await sel(0);
    await ev(`(() => { document.activeElement?.blur(); return 1; })()`);
    check(await until(`!!document.querySelector('#wk-cm [data-wkgo="#wiki/${other}"]')`), 'link: [[Other]] drawn as a link');
    await click(`document.querySelector('#wk-cm [data-wkgo="#wiki/${other}"]')`);
    check(await until(`location.hash === '#wiki/${other}'`), 'link: the first click opens the page');
    check(await until(`!!${cm} && WKCM.view.state.doc.toString() === 'The other page.'`), 'link: the other page opens in the editor');

    // ---- phone 390 px: read first, the pen opens the same editor
    await size(390, 760);
    await nav(B + `#wiki/${id}`);
    check(await until(`!!document.querySelector('#wk-md') && !!document.querySelector('[data-wk="pen"]')`), 'phone: the page is read first, with the pen');
    await shot('p2554c-phone-read.png');
    await click(`document.querySelector('[data-wk="pen"]')`);
    check(await until(`!!${cm} && document.activeElement === ${cm}`), 'phone: the pen opens the editor with the focus');
    await sel(`WKCM.view.state.doc.length`);
    await type(' Phone');  // the letters stay text: no app shortcut (n = new task) takes them (events.js, a contenteditable field)
    check(await saved(b => b.endsWith('Plain end Phone')), 'phone: typing saves');
    check(await ev(`!!${cm} && document.activeElement === ${cm}`), 'phone: the editor stays after the save (#3883)');
    await shot('p2554c-phone-edit.png');
    await click(`document.querySelector('[data-wk="pen"]')`);
    check(await until(`!!document.querySelector('#wk-md') && !document.querySelector('#wk-cm')`), 'phone: Done goes back to reading');
    check(await ev(`!!document.querySelector('#wk-md').textContent.includes('Phone')`), 'phone: the read view shows the new text');

    // ---- without the right to write
    await size(1280, 900);
    await ev(`fetch('/api/auth/logout', {method: 'POST', headers: {'X-Requested-With': 'kalmido'}}).then(r => r.status)`);
    await nav(B + 'static/icon.svg');
    await signin('rita');
    await nav(B + `#wiki/${OP}`);
    check(await until(`!!document.querySelector('#wk-md') && document.querySelector('#wk-md').textContent.includes('Read me')`), 'no right: the page is read');
    // 2.1153.0 (#5525): a reader has the "…" now, it holds only "Present" (nothing that writes)
    check(await ev(`!document.querySelector('#wk-cm') && !document.querySelector('[data-wk="pen"]') && JSON.stringify(wk_pmenuItems(WK.pg).map(x => x.label)) === JSON.stringify(['Present'])`), 'no right: no editor, no pen, the "…" holds only Present');
  }, false);
  console.log(`p2554_c_wikicm_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
