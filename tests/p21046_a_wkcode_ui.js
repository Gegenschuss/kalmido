// kalmido-suite: fresh
// 2.1046.0 (#5828): code blocks in the knowledge editor (static/js/wkcm.js) and "More information" in its bar, Firefox with a mouse.
// frida = a person WITHOUT an organisation (her private space).
// - a ``` block is drawn as a block: its lines carry cm-wkpre, a background other than the sheet's (light and dark design);
//   the fence lines ```sh hide while the cursor is outside and show (muted) while it is inside
// - "Copy code" (the read view's button) at the block: hidden until the mouse is over the block, a click puts exactly the
//   block's text (without the fences) on the clipboard, the cursor and the text stay; reachable with the keyboard (Enter)
// - an indented code block is a block too, its button copies the lines without the indent
// - "More information" stands on one line with the bar's buttons (same middle, the height of a small button); 390 px = the symbol
// - the read view (wk_render) shows the code block with its own "Copy code" button
// freelancer-matrix: wiki
// Invented texts only. Screenshots: P21046A_SHOTS.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login, until: waitFor} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21046A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const firefox = require('./ff')({tag: 'p21046_a_wkcode_ui', check, shots: 'P21046A_SHOTS'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const BODY = 'Intro line.\n\n```sh\necho hi\nls -la\n```\n\nMiddle text with `inline` code.\n\n    indented one\n    indented two\n\nThe end.\n';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const st0 = await call(CA, 'GET', '/api/state');
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'wiki'])].join(',');
  await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CK = await login('frida');
  await call(CK, 'PATCH', '/api/settings', {tour: 'done', lang: 'en', features: feats});
  check(((await call(CK, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'setup: frida has no organisation');
  const id = (await call(CK, 'POST', '/api/wiki/pages', {space: 'private', path: 'Mocha', body: BODY})).id;
  check(!!id, 'setup: the page');

  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    const until = (expr, ms = 15000) => waitFor(() => ev(expr).catch(() => null), {timeout: ms, step: 150});
    const act = actions => cmd('input.performActions', {context: ctx, actions}).then(() => cmd('input.releaseActions', {context: ctx}));
    const keys = vs => act([{type: 'key', id: 'k', actions: vs.flatMap(c => [{type: 'keyDown', value: c}, {type: 'keyUp', value: c}])}]);
    const at = async sel => ev(`(() => { const e = ${sel}; if (!e) return null; e.scrollIntoView({block: 'center'}); const r = e.getBoundingClientRect(); return {x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2)}; })()`);
    const move = async sel => { const c = await at(sel); if (!c) return false; await act([{type: 'pointer', id: 'p1', parameters: {pointerType: 'mouse'}, actions: [{type: 'pointerMove', x: c.x, y: c.y}]}]); return true; };
    const click = async sel => {
      const c = await at(sel); if (!c) return false;
      await act([{type: 'pointer', id: 'p1', parameters: {pointerType: 'mouse'}, actions: [{type: 'pointerMove', x: c.x, y: c.y}, {type: 'pointerDown', button: 0}, {type: 'pointerUp', button: 0}]}]);
      return true;
    };
    const size = (width, height) => cmd('browsingContext.setViewport', {context: ctx, viewport: {width, height}});
    const signin = u => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
    const cm = `document.querySelector('#wk-cm .cm-content')`;
    const lineOf = t => `[...document.querySelectorAll('#wk-cm .cm-line')].find(l => l.textContent.includes(${JSON.stringify(t)}))`;
    const sel = pos => ev(`(() => { WKCM.view.dispatch({selection: {anchor: ${pos}}}); WKCM.view.focus(); return 1; })()`);
    // the button sits in the first line of a block (the hidden ```sh line of a fenced block): 0 = the fenced block, 1 = the indented one
    const btnOf = i => `document.querySelectorAll('#wk-cm .cm-wkpre1')[${i}]?.querySelector('.cm-wkcopy [data-mdcopy]')`;
    const opaOf = i => `+getComputedStyle(document.querySelectorAll('#wk-cm .cm-wkpre1')[${i}].querySelector('.cm-wkcopy')).opacity`;
    // the clipboard of this page: what copyText (git.js) writes lands in window.__cp
    const clip = () => ev(`(() => { window.__cp = null; Object.defineProperty(navigator, 'clipboard', {configurable: true, value: {writeText: t => { window.__cp = t; return Promise.resolve(); }}}); return 1; })()`);
    const bgOf = e => `(() => { let x = ${e}; while (x) { const c = getComputedStyle(x).backgroundColor; if (c && c !== 'transparent' && c !== 'rgba(0, 0, 0, 0)') return c; x = x.parentElement; } return ''; })()`;

    await nav(B + 'static/icon.svg');
    await signin('frida');
    await size(1280, 900);
    await nav(B + `#wiki/${id}`);
    check(await until(`!!${cm} && !!${lineOf('echo hi')}`), 'desktop: the editor shows the page');
    await sel(`WKCM.view.state.doc.length`);  // the cursor at the end, outside the block

    // ---- the block: class, background, fences hidden
    check(await until(`${lineOf('echo hi')}.classList.contains('cm-wkpre') && ${lineOf('ls -la')}.classList.contains('cm-wkpre')`), 'block: the code lines are one block (cm-wkpre)');
    check(await ev(`![...document.querySelectorAll('#wk-cm .cm-line')].some(l => l.textContent.includes('\`\`\`'))`), 'block: the fence lines ```sh are hidden while the cursor is outside');
    check(await ev(`document.querySelectorAll('#wk-cm .cm-wkpre1').length === 2 && document.querySelectorAll('#wk-cm .cm-wkprez').length === 2`), 'block: the fenced and the indented block each have a first and a last line');
    for (const theme of ['light', 'dark']) {
      await ev(`(() => { document.documentElement.dataset.theme = '${theme}'; return 1; })()`);
      const code = await ev(bgOf(lineOf('echo hi'))), sheet = await ev(bgOf(`document.querySelector('#wk-cm').parentElement`));
      check(code && code !== sheet, `block (${theme}): the code has a background other than the sheet ` + JSON.stringify([code, sheet]));
      const round = await ev(`getComputedStyle(document.querySelector('#wk-cm .cm-wkpre1')).borderTopLeftRadius`);
      check(round && round !== '0px', `block (${theme}): round corners at the top ` + round);
    }
    await ev(`(() => { document.documentElement.dataset.theme = 'light'; return 1; })()`);
    check(await ev(`!!${lineOf('inline')}.querySelector('.cm-wkc') && !${lineOf('inline')}.classList.contains('cm-wkpre')`), 'inline code stays inline code');
    await shot('p21046a-desktop.png');

    // ---- the cursor inside: the fences show, muted
    await sel(`WKCM.view.state.doc.toString().indexOf('echo hi') + 2`);
    check(await until(`!!${lineOf('```sh')} && ${lineOf('```sh')}.classList.contains('cm-wkfence')`), 'block: the opening fence ```sh shows while the cursor is inside');
    check(await ev(`[...document.querySelectorAll('#wk-cm .cm-line')].filter(l => l.textContent.trim() === '\`\`\`').length === 1`), 'block: the closing fence shows too');
    await sel(`WKCM.view.state.doc.length`);
    check(await until(`![...document.querySelectorAll('#wk-cm .cm-line')].some(l => l.textContent.includes('\`\`\`'))`), 'block: the fences hide again when the cursor left');

    // ---- "Copy code": hidden, shows over the block, copies exactly the block
    await move(`document.querySelector('.wkedwrap .wembar')`);
    check(await until(`!!${btnOf(0)} && !!${btnOf(1)}`), 'copy: the block has the "Copy code" button');
    check(await until(`${opaOf(0)} === 0`), 'copy: the button is hidden while the mouse is elsewhere ' + await ev(opaOf(0)).catch(() => null));
    await move(lineOf('ls -la'));
    check(await until(`${opaOf(0)} === 1`), 'copy: the button shows while the mouse is over the block (its last line)');
    await clip();
    const before = await ev(`JSON.stringify([WKCM.view.state.selection.main.head, WKCM.view.state.doc.length])`);
    check(await click(btnOf(0)), 'copy: the button is clicked');
    check(await until(`window.__cp === 'echo hi\\nls -la'`), 'copy: the clipboard holds exactly the block, without the fences ' + JSON.stringify(await ev('window.__cp')));
    check(await ev(`JSON.stringify([WKCM.view.state.selection.main.head, WKCM.view.state.doc.length])`) === before, 'copy: the cursor and the text stay as they were');
    check(await until(`!!document.querySelector('#toast, .toast') && /Copied/.test(document.querySelector('#toast, .toast').textContent)`), 'copy: the "Copied" toast of the read view');
    // keyboard: the button takes the focus, Enter copies
    await clip();
    await ev(`(() => { ${btnOf(0)}.focus(); return 1; })()`);
    check(await until(`document.activeElement === ${btnOf(0)} && ${opaOf(0)} === 1`), 'copy: the button can hold the keyboard focus and shows then');
    await keys(['']);  // Enter
    check(await until(`window.__cp === 'echo hi\\nls -la'`), 'copy: Enter on the focused button copies');
    // the indented block
    await clip();
    await move(lineOf('indented two'));
    check(await click(btnOf(1)), 'copy: the indented block\'s button is clicked');
    check(await until(`window.__cp === 'indented one\\nindented two'`), 'copy: the indented block without its indent ' + JSON.stringify(await ev('window.__cp')));
    check(await ev(`WKCM.view.state.doc.toString()`) === BODY, 'copy: the page text is unchanged');

    // ---- "More information" on one line with the bar's buttons
    const bar = await ev(`(() => { const i = document.querySelector('.wkedwrap .wembar .ib.ibl'), b = document.querySelector('.wkedwrap .wembar [data-wem="ins"]'); if (!i || !b) return null;
      const r = i.getBoundingClientRect(), q = b.getBoundingClientRect(); return {mi: r.top + r.height / 2, mb: q.top + q.height / 2, hi: r.height, hb: q.height, fi: getComputedStyle(i).fontSize, fb: getComputedStyle(b).fontSize, txt: i.textContent.trim()}; })()`);
    check(bar && Math.abs(bar.mi - bar.mb) <= 1, '"More information": the same middle as the button beside it ' + JSON.stringify(bar));
    check(bar && Math.abs(bar.hi - bar.hb) <= 1 && bar.fi === bar.fb, '"More information": the height and type of a small button ' + JSON.stringify(bar));
    check(bar && bar.txt === 'More information', '"More information": the word on a wide screen');

    // ---- the read view of the page (wiki.js wk_render, the same drawing as #wk-md) has its own "Copy code" with the block's text
    const rv = await ev(`(() => { const d = document.createElement('div'); d.innerHTML = wk_render(WK.pg); const c = d.querySelector('.mdcode'); return c ? [!!c.querySelector('[data-mdcopy]'), c.querySelector('pre').textContent] : null; })()`);
    check(rv && rv[0] && rv[1] === 'echo hi\nls -la', 'read view: the code block with its "Copy code" button and the block\'s text ' + JSON.stringify(rv));

    // ---- phone 390 px: the bar shows the symbol only
    await size(390, 760);
    await nav(B + `#wiki/${id}`);
    if (await until(`!!document.querySelector('#wk-md') || !!${cm}`) && !await ev(`!!${cm}`)) await click(`document.querySelector('[data-wk="pen"]')`);
    check(await until(`!!${cm} && !!document.querySelector('.wkedwrap .wembar .ib.ibl')`), 'phone: the editor with its bar');
    const sm = await ev(`(() => { const i = document.querySelector('.wkedwrap .wembar .ib.ibl'); if (!i) return null; const r = i.getBoundingClientRect(), s = i.querySelector('span')?.getBoundingClientRect(); return {w: r.width, sw: s ? s.width : 0}; })()`);
    check(sm && sm.w <= 32 && sm.sw <= 1, 'phone: "More information" is the symbol only ' + JSON.stringify(sm));
    await shot('p21046a-phone-edit.png');
  }, false);
  console.log(`p21046_a_wkcode_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
