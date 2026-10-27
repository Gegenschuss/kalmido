// 2.350.0 B (#3147, #3149): the knowledge editor with live preview and slash commands (Firefox, real clicks and keys),
// computer 1280x800 (alice) and tablet 820x1180 (frida, a person WITHOUT an organisation: freelancer-matrix: knowledge):
// - Edit shows the page drawn (heading, bold, list), no raw field until one clicks; a click into a block shows its Markdown
// - typing saves the ONE Markdown string of the page (read back over the API), Ctrl+B, arrows move between blocks, Esc
// - "/" at the start of a line opens the commands, typing filters, Enter on "Checkbox" writes "- [ ] "; Ctrl+K a link,
//   Ctrl+Shift+7 a numbered list
// - the page's "…" entry switches to the plain text field (#wk-body, an account setting: look.wkEd) and back; "/" works there too
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
    const blk = () => ev(`document.querySelector('#wk-blk')?.value ?? null`);
    await nav(B + 'static/icon.svg');
    const lg = await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${run.who}', password: 'password123'})}).then(r => r.status)`);
    check(lg === 200, `${tag}: login`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
    await nav(B + `#wiki/${run.id}`);
    await until(`!!document.querySelector('[data-wk="mode"][data-m="edit"]')`);
    await ev(`(() => { document.querySelector('[data-wk="mode"][data-m="edit"]').click(); return 1; })()`);
    // #3147: drawn, no raw field yet
    const r0 = await until(`(() => { const l = document.querySelector('#wk-live'); if (!l || !l.querySelector('h4')) return null;
      return {h4: l.querySelector('.wklb h4')?.textContent, b: l.querySelector('.wklb b')?.textContent, li: l.querySelectorAll('.wklb li').length,
        blk: !!document.querySelector('#wk-blk'), body: !!document.querySelector('#wk-body'), bar: !!document.querySelector('.wkedwrap .wembar')}; })()`);
    check(r0 && r0.h4 === 'Plan' && r0.b === 'bold' && r0.li === 2 && !r0.blk && !r0.body && r0.bar, `${tag}: edit mode shows the page drawn (heading, bold, list), the bar, no raw field: ${JSON.stringify(r0)}`);
    if (vw > 1000) await shot(`p2350_b_${vw}_drawn.png`);  // at most four pictures
    // a click into the paragraph opens it as Markdown, near the click
    await clickAt(`document.querySelector('#wk-live .wklb b')`);
    await until(`!!document.querySelector('#wk-blk')`);
    const c1 = await ev(`(() => { const t = document.querySelector('#wk-blk'); return {v: t.value, s: t.selectionStart, f: document.activeElement === t, h4: !!document.querySelector('#wk-live .wklb h4')}; })()`);
    check(c1.v === 'Intro **bold** text' && c1.f && c1.h4, `${tag}: the clicked block shows its Markdown and has the focus, the rest stays drawn: ${JSON.stringify(c1)}`);
    check(c1.s >= 6 && c1.s <= 14, `${tag}: the cursor stands near the click (${c1.s})`);
    // typing + autosave: the page's one Markdown string
    await ev(`(() => { const t = document.querySelector('#wk-blk'); t.setSelectionRange(t.value.length, t.value.length); return 1; })()`);
    await type(' more');
    await ev(`(() => { const t = document.querySelector('#wk-blk'), i = t.value.indexOf('more'); t.setSelectionRange(i, i + 4); return 1; })()`);
    await press('b', ['Control']);
    check(await blk() === 'Intro **bold** text **more**', `${tag}: Ctrl+B makes the selection bold (${await blk()})`);
    const w1 = BODY.replace('text', 'text **more**');
    check(await saved(w1) === w1, `${tag}: autosave writes the whole page as one Markdown string`);
    // arrows: down skips the blank line into the list, up comes back; Esc draws everything
    await ev(`(() => { const t = document.querySelector('#wk-blk'); t.setSelectionRange(t.value.length, t.value.length); return 1; })()`);
    await press('ArrowDown');
    check(await until(`document.querySelector('#wk-blk')?.value === '- one\\n- two'`), `${tag}: arrow down at the last line opens the next block (${await blk()})`);
    check(await ev(`document.querySelector('#wk-live .wklb b:last-of-type')?.textContent === 'more'`), `${tag}: the left paragraph is drawn again with the new bold word`);
    await ev(`(() => { document.querySelector('#wk-blk').setSelectionRange(0, 0); return 1; })()`);
    await press('ArrowUp');
    check(await until(`document.querySelector('#wk-blk')?.value === 'Intro **bold** text **more**'`), `${tag}: arrow up at the first line goes back (${await blk()})`);
    await press('Escape');
    check(await until(`!document.querySelector('#wk-blk') && document.querySelectorAll('#wk-live .wklb li').length === 2`), `${tag}: Esc shows everything drawn`);
    // #3149: below the last block = its end; Enter, "/check" filters the commands, Enter writes the checkbox
    const lv = await ev(`(() => { const l = document.querySelector('#wk-live'); l.scrollIntoView({block: 'center'}); const r = l.getBoundingClientRect(); return {x: r.left + 20, y: r.bottom - 8}; })()`);
    await act([{type: 'pointer', id: 'p1', parameters: {pointerType: 'mouse'}, actions: [{type: 'pointerMove', x: Math.round(lv.x), y: Math.round(lv.y)}, {type: 'pointerDown', button: 0}, {type: 'pointerUp', button: 0}]}]);
    check(await until(`document.querySelector('#wk-blk')?.value === 'End'`), `${tag}: a click below the last block opens it (${await blk()})`);
    await ev(`(() => { const t = document.querySelector('#wk-blk'); t.setSelectionRange(3, 3); return 1; })()`);
    await press('Enter'); await type('/check');
    const m1 = await until(`(() => { const a = document.querySelector('#wk-ac'); return a && !a.classList.contains('hidden') && a.querySelector('button') ? [...a.querySelectorAll('button')].map(b => b.textContent.trim()) : null; })()`);
    check(m1 && m1[0] === 'Checkbox', `${tag}: "/" at the start of a line opens the commands, typing filters them: ${JSON.stringify(m1)}`);
    if (vw > 1000) await shot(`p2350_b_${vw}_slash.png`);
    await press('Enter');
    check(await blk() === 'End\n- [ ] ', `${tag}: Enter on "Checkbox" writes "- [ ] " (${JSON.stringify(await blk())})`);
    await type('Call');
    await ev(`(() => { const t = document.querySelector('#wk-blk'), i = t.value.indexOf('Call'); t.setSelectionRange(i, i + 4); return 1; })()`);
    await press('k', ['Control']);
    check(await blk() === 'End\n- [ ] [Call](https://)' && !(await ev(`!!document.querySelector('.palette')`)), `${tag}: Ctrl+K in the field makes a link, the command field stays shut (${JSON.stringify(await blk())})`);
    await ev(`(() => { document.querySelector('#wk-blk').setSelectionRange(1, 1); return 1; })()`);
    await press('7', ['Control', 'Shift']);
    check(await blk() === '1. End\n- [ ] [Call](https://)', `${tag}: Ctrl+Shift+7 numbers the line (${JSON.stringify(await blk())})`);
    await press('Escape');
    check(await until(`!document.querySelector('#wk-blk') && !!document.querySelector('#wk-live ol li') && !!document.querySelector('#wk-live input[type="checkbox"]')`), `${tag}: drawn: numbered line and checkbox`);
    check(await saved(WANT) === WANT, `${tag}: the saved page is the expected Markdown: ${JSON.stringify(await saved(WANT))}`);
    await shot(`p2350_b_${vw}_after.png`);
    // the plain text field (account setting) and back
    const menuPick = async () => {
      await ev(`(() => { document.querySelector('[data-wk="pmenu"]').click(); return 1; })()`);
      await until(`!!document.querySelector('#pop:not(.hidden) [role="menuitem"]')`);
      return ev(`(() => { const b = [...document.querySelectorAll('#pop [role="menuitem"]')].find(x => /Live preview while writing/.test(x.textContent)); if (!b) return null; const on = b.classList.contains('on'); b.click(); return {on}; })()`);
    };
    const p1 = await menuPick();
    check(p1 && p1.on, `${tag}: the page's "…" has "Live preview while writing", ticked`);
    check(await until(`document.querySelector('#wk-body')?.value === ${JSON.stringify(WANT)} && !document.querySelector('#wk-live')`), `${tag}: switched off: the plain text field with the whole page`);
    let look = '';
    for (let i = 0; i < 40 && !/"wkEd":"text"/.test(look); i++) { await sleep(250); look = (await call(run.ck, 'GET', '/api/state')).settings?.look || ''; }
    check(/"wkEd":"text"/.test(look), `${tag}: the choice is kept with the account (${look})`);
    await ev(`(() => { const t = document.querySelector('#wk-body'); t.focus(); t.setSelectionRange(t.value.length, t.value.length); return 1; })()`);
    await press('Enter'); await type('/head');
    const m2 = await until(`(() => { const a = document.querySelector('#wk-ac'); return a && !a.classList.contains('hidden') && a.querySelector('button') ? a.querySelector('button').textContent.trim() : null; })()`);
    check(m2 === 'Heading', `${tag}: the plain text field has the commands too (${m2})`);
    await press('Enter'); await type('Next');
    check(await saved(WANT + '\n## Next') === WANT + '\n## Next', `${tag}: "/head" + Enter writes a heading, saved`);
    const p2 = await menuPick();
    check(p2 && !p2.on && await until(`!!document.querySelector('#wk-live .wklb h5')`), `${tag}: switched on again: drawn (the new heading too)`);
  });
  console.log(`p2350_b_wikilive_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
