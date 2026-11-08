// 2.350.0 B (#3147, #3149): the knowledge editor with live preview and slash commands (Firefox, real clicks and keys),
// computer 1280x800 (alice) and tablet 820x1180 (frida, a person WITHOUT an organisation: freelancer-matrix: knowledge).
// 2.554.0 (#4052): the block preview (#3147) and the Source / Preview switch (#3128) are replaced by the one editor (wkcm.js,
// CodeMirror 6); this suite now drives it (the editor's own checks: p2554_c_wikicm_ui):
// - the page opens drawn (heading, bold, list) with the bar, no raw field; a click into the bold word shows its ** there
// - typing saves the ONE Markdown string of the page (read back over the API), Ctrl+B
// - "/" at the start of a line opens the commands, typing filters, Enter on "Checkbox" writes "- [ ] "; Ctrl+K a link,
//   Ctrl+Shift+7 a numbered list; drawn again when the cursor left: the numbered line and the box
// - the page's "…" entry "Edit as Markdown" opens the plain text field (#wk-body); "/" works there too; "Back to the editor"
// Invented texts only. Screenshots: P2350B_SHOTS.
// kalmido-suite: fresh
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2350B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const firefox = require('./ff')({tag: 'p2350_b_wikilive_ui', check, shots: 'P2350B_SHOTS'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const BODY = '# Plan\n\nIntro **bold** text\n\n- one\n- two\n\nEnd';
const WANT = '# Plan\n\nIntro **bold** text **more**\n\n- one\n- two\n\n1. End\n- [ ] [Call](https://)';
const K = {Enter: '', Escape: '', ArrowUp: '', ArrowDown: '', Control: '', Shift: ''};

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const st0 = await call(CA, 'GET', '/api/state');
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'wiki'])].join(',');
  await call(CA, 'PATCH', '/api/settings', {tour: 'done', lang: 'en', features: feats});
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {tour: 'done', lang: 'en', features: feats});
  check(fu.id && ((await call(CF, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'setup: frida has no organisation');
  const runs = [];
  for (const [who, ck] of [['alice', CA], ['frida', CF]]) {
    const id = (await call(ck, 'POST', '/api/wiki/pages', {space: 'private', path: 'Live', body: BODY})).id;
    check(id, `setup: ${who}'s private page`); runs.push({who, ck, id});
  }

  for (const [[vw, vh], run] of [[[1280, 800], runs[0]], [[820, 1180], runs[1]]]) await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    const tag = `${vw} ${run.who}`;
    const until = (expr, n) => require('./boot').until(() => ev(expr).catch(() => null), {timeout: n ? n * 250 : 15000, step: 250});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
    const saved = async want => { let b = ''; for (let i = 0; i < 60 && b !== want; i++) { await sleep(250); b = (await call(run.ck, 'GET', `/api/wiki/pages/${run.id}`)).body; } return b; };
    const act = actions => cmd('input.performActions', {context: ctx, actions}).then(() => cmd('input.releaseActions', {context: ctx}));
    const type = s => act([{type: 'key', id: 'k', actions: [...s].flatMap(c => [{type: 'keyDown', value: c}, {type: 'keyUp', value: c}])}]);
    const press = (key, mods = []) => act([{type: 'key', id: 'k', actions: [...mods.map(m => ({type: 'keyDown', value: K[m]})), {type: 'keyDown', value: K[key] || key}, {type: 'keyUp', value: K[key] || key}, ...mods.reverse().map(m => ({type: 'keyUp', value: K[m]}))]}]);
    const clickAt = async sel => {
      const r = await ev(`(() => { const e = ${sel}; if (!e) return null; e.scrollIntoView({block: 'center'}); const r = e.getBoundingClientRect(); return {x: r.left + Math.min(r.width / 2, 40), y: r.top + r.height / 2}; })()`);
      if (!r) return false;
      await act([{type: 'pointer', id: 'p1', parameters: {pointerType: 'mouse'}, actions: [{type: 'pointerMove', x: Math.round(r.x), y: Math.round(r.y)}, {type: 'pointerDown', button: 0}, {type: 'pointerUp', button: 0}]}]);
      return true;
    };
    const doc = () => ev(`WKCM.view?.state.doc.toString() ?? null`);
    const line = t => `[...document.querySelectorAll('#wk-cm .cm-line')].find(l => l.textContent.includes(${JSON.stringify(t)}))`;
    const put = (a, z = a) => ev(`(() => { const v = WKCM.view; v.focus(); v.dispatch({selection: {anchor: ${a}, head: ${z}}}); return 1; })()`);
    await nav(B + 'static/icon.svg');
    const lg = await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${run.who}', password: 'password123'})}).then(r => r.status)`);
    check(lg === 200, `${tag}: login`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
    await nav(B + `#wiki/${run.id}`);
    // drawn at once, no raw field, no switch
    const r0 = await until(`(() => { const l = document.querySelector('#wk-cm .cm-content'); if (!l || !l.querySelector('.cm-wkh1')) return null;
      return {h1: l.querySelector('.cm-wkh1')?.textContent, b: l.querySelector('.cm-wkb')?.textContent, li: l.querySelectorAll('.cm-wkbul').length, raw: l.textContent.includes('**') || l.textContent.includes('# '),
        body: !!document.querySelector('#wk-body'), mode: !!document.querySelector('[data-wk="mode"], [data-wem="src"]'), bar: !!document.querySelector('.wkedwrap .wembar')}; })()`);
    check(r0 && r0.h1 === 'Plan' && r0.b === 'bold' && r0.li === 2 && !r0.raw && !r0.body && !r0.mode && r0.bar, `${tag}: the page opens drawn (heading, bold, list), the bar, no raw field, no switch: ${JSON.stringify(r0)}`);
    if (vw > 1000) await shot(`p2350_b_${vw}_drawn.png`);  // at most four pictures
    // a click into the bold word: its ** show there, the rest stays drawn
    await clickAt(`document.querySelector('#wk-cm .cm-wkb')`);
    const c1 = await until(`(() => { const v = WKCM.view; if (document.activeElement !== v.contentDOM) return null; const h = v.state.selection.main.head; return {l: ${line('Intro')}.textContent, h, h1: ${line('Plan')}.textContent}; })()`);
    check(c1 && c1.l === 'Intro **bold** text' && c1.h1 === 'Plan', `${tag}: the clicked bold word shows its Markdown, the heading stays drawn: ${JSON.stringify(c1)}`);
    check(c1 && c1.h >= 14 && c1.h <= 22, `${tag}: the cursor stands near the click (${c1 && c1.h})`);
    // typing + autosave: the page's one Markdown string
    await put(`WKCM.view.state.doc.line(3).to`);
    await type(' more');
    await ev(`(() => { const v = WKCM.view, i = v.state.doc.toString().indexOf('more'); v.dispatch({selection: {anchor: i, head: i + 4}}); return 1; })()`);
    await press('b', ['Control']);
    check((await doc()).includes('Intro **bold** text **more**'), `${tag}: Ctrl+B makes the selection bold (${JSON.stringify(await doc())})`);
    const w1 = BODY.replace('text', 'text **more**');
    check(await saved(w1) === w1, `${tag}: autosave writes the whole page as one Markdown string`);
    // #3149: below the last line = its end; Enter, "/check" filters the commands, Enter writes the checkbox
    const lv = await ev(`(() => { const l = document.querySelector('#wk-cm .cm-content'); l.scrollIntoView({block: 'end'}); const r = l.getBoundingClientRect(); return {x: r.left + 20, y: Math.min(r.bottom, innerHeight) - 8}; })()`);
    await act([{type: 'pointer', id: 'p1', parameters: {pointerType: 'mouse'}, actions: [{type: 'pointerMove', x: Math.round(lv.x), y: Math.round(lv.y)}, {type: 'pointerDown', button: 0}, {type: 'pointerUp', button: 0}]}]);
    check(await until(`WKCM.view.state.selection.main.head === WKCM.view.state.doc.length`), `${tag}: a click below the last line puts the cursor at the end`);
    await press('Enter'); await type('/check');
    const m1 = await until(`(() => { const a = document.querySelector('#wk-ac'); return a && !a.classList.contains('hidden') && a.querySelector('button') ? [...a.querySelectorAll('button')].map(b => b.textContent.trim()) : null; })()`);
    check(m1 && m1[0] === 'Checkbox', `${tag}: "/" at the start of a line opens the commands, typing filters them: ${JSON.stringify(m1)}`);
    if (vw > 1000) await shot(`p2350_b_${vw}_slash.png`);
    await press('Enter');
    check((await doc()).endsWith('End\n- [ ] '), `${tag}: Enter on "Checkbox" writes "- [ ] " (${JSON.stringify(await doc())})`);
    await type('Call');
    await ev(`(() => { const v = WKCM.view, i = v.state.doc.toString().lastIndexOf('Call'); v.dispatch({selection: {anchor: i, head: i + 4}}); return 1; })()`);
    await press('k', ['Control']);
    check((await doc()).endsWith('End\n- [ ] [Call](https://)') && !(await ev(`!!document.querySelector('.palette')`)), `${tag}: Ctrl+K in the editor makes a link, the command field stays shut (${JSON.stringify(await doc())})`);
    await put(`WKCM.view.state.doc.toString().lastIndexOf('End') + 1`);
    await press('7', ['Control', 'Shift']);
    check((await doc()).endsWith('\n1. End\n- [ ] [Call](https://)'), `${tag}: Ctrl+Shift+7 numbers the line (${JSON.stringify(await doc())})`);
    await put(0);  // the cursor elsewhere: drawn
    check(await until(`!!${line('End')} && !!document.querySelector('#wk-cm input[type="checkbox"]') && !${line('Call')}?.textContent.includes('https')`), `${tag}: drawn: numbered line, checkbox, the link without its address`);
    check(await saved(WANT) === WANT, `${tag}: the saved page is the expected Markdown: ${JSON.stringify(await saved(WANT))}`);
    await shot(`p2350_b_${vw}_after.png`);
    // the plain text field (the page's "…": "Edit as Markdown") and back
    const menuPick = async re => {
      await ev(`(() => { document.querySelector('[data-wk="pmenu"]').click(); return 1; })()`);
      await until(`!!document.querySelector('#pop:not(.hidden) [role="menuitem"]')`);
      return ev(`(() => { const b = [...document.querySelectorAll('#pop [role="menuitem"]')].find(x => ${re}.test(x.textContent.trim())); if (!b) return null; const t = b.textContent.trim(); b.click(); return {t}; })()`);
    };
    const all = await ev(`(() => { document.querySelector('[data-wk="pmenu"]').click(); const t = [...document.querySelectorAll('#pop [role="menuitem"]')].map(x => x.textContent.trim()); closePop(); return t; })()`);
    check(all && !all.some(x => /^(Source|Preview)$/.test(x)), `${tag}: no "Source" / "Preview" any more (${JSON.stringify(all)})`);
    const p1 = await menuPick('/^Edit as Markdown$/');
    check(p1, `${tag}: the page's "…" has "Edit as Markdown"`);
    check(await until(`document.querySelector('#wk-body')?.value === ${JSON.stringify(WANT)} && !document.querySelector('#wk-cm')`), `${tag}: the plain text field with the whole page`);
    await ev(`(() => { const t = document.querySelector('#wk-body'); t.focus(); t.setSelectionRange(t.value.length, t.value.length); return 1; })()`);
    await press('Enter'); await type('/head');
    const m2 = await until(`(() => { const a = document.querySelector('#wk-ac'); return a && !a.classList.contains('hidden') && a.querySelector('button') ? a.querySelector('button').textContent.trim() : null; })()`);
    check(m2 === 'Heading', `${tag}: the plain text field has the commands too (${m2})`);
    await press('Enter'); await type('Next');
    check(await saved(WANT + '\n## Next') === WANT + '\n## Next', `${tag}: "/head" + Enter writes a heading, saved`);
    const p2 = await menuPick('/^Back to the editor$/');
    check(p2 && await until(`!!document.querySelector('#wk-cm .cm-wkh2') && ${line('Next')}?.textContent === 'Next'`), `${tag}: "Back to the editor": drawn, the new heading too`);
  }, false);  // 2.680.0 (#5141): a mouse on purpose - headless Firefox reports hover: none without a pointer setting (CI and the Mac's VM), and since #5082 / #5085 the app then runs in finger mode
  console.log(`p2350_b_wikilive_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
