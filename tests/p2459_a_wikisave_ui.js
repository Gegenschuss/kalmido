// kalmido-suite: fresh
// 2.459.0 (#3883): saving a knowledge page never moves the view (Firefox, phone window 412x640 with a touch screen, the
// keyboard taken as a lower window). frida, a person WITHOUT an organisation. Long page, a tall block in the middle:
// - 2.554.0 (#4052): the one editor (wkcm.js, CodeMirror; the phone opens it with the pen): typing in the middle of the long
//   part and the autosave leave #view.scrollTop, the editor and the cursor as they are (before: the block preview #3147,
//   whose wklv_fit collapsed the page); the file answers (wkcm_redraw) keep the editor's lines
// - plain text editor ("Edit as Markdown" in the "…" menu): the same; ntbFit (run by the "Saved" hint) does not grow the
//   field by what is scrolled away
// freelancer-matrix: wiki
// Invented texts only. Screenshots: P2459A_SHOTS.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login, until: waitFor} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2459A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const firefox = require('./ff')({tag: 'p2459_a_wikisave_ui', check, shots: 'P2459A_SHOTS'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const BODY = [...Array.from({length: 12}, (_, i) => `Before ${i}\n`), Array.from({length: 90}, (_, i) => `Long line ${i}`).join('\n'), '', 'After one', '', 'After two'].join('\n');
// 2.554.0 (#4052): the editor's field is CodeMirror's content (its selection in WKCM.view), else the focused <textarea>
const STATE = `(() => { const v = document.querySelector('#view'), t = document.activeElement, cm = typeof WKCM !== 'undefined' && WKCM.view?.contentDOM === t, m = cm ? WKCM.view.state.selection.main : null;
  return {top: Math.round(v.scrollTop), left: Math.round(v.scrollHeight - v.clientHeight - v.scrollTop), id: cm ? 'cm' : t?.id, s: cm ? m.from : t?.selectionStart, e: cm ? m.to : t?.selectionEnd, fh: Math.round(t?.getBoundingClientRect().height || 0), fy: Math.round(t?.getBoundingClientRect().top || 0), ts: Math.round(t?.scrollTop || 0)}; })()`;

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
  const id = (await call(CK, 'POST', '/api/wiki/pages', {space: 'private', path: 'Long', body: BODY})).id;
  check(id, 'setup: the long page');

  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    const until = expr => waitFor(() => ev(expr).catch(() => null), {timeout: 15000, step: 150});
    const act = actions => cmd('input.performActions', {context: ctx, actions}).then(() => cmd('input.releaseActions', {context: ctx}));
    const type = s => act([{type: 'key', id: 'k', actions: [...s].flatMap(c => [{type: 'keyDown', value: c}, {type: 'keyUp', value: c}])}]);
    const size = height => cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 412, height}});
    const body = () => call(CK, 'GET', `/api/wiki/pages/${id}`).then(p => p.body || '');
    const saved = want => waitFor(async () => (await body()).includes(want), {timeout: 15000, step: 200});
    const same = (a, b, L, n) => {
      check(Math.abs(a.top - b.top) <= 2, `${L}: the view stays where it is (${a.top} -> ${b.top}, ${b.left} px left to the end)`);
      check(b.id === a.id && b.s === a.s + n && b.e === a.e + n, `${L}: field and cursor stay: ${JSON.stringify([a, b])}`);
      check(Math.abs(a.fh - b.fh) <= 2 && Math.abs(a.fy - b.fy) <= 2 && Math.abs(a.ts - b.ts) <= 2, `${L}: the field neither moves nor changes its height: ${JSON.stringify([a, b])}`);
    };
    // types a word at the cursor and waits for the save and for its hint to come and go
    const save = async (word, L) => {
      await type(' ');  // the first key: the browser's own reveal of the cursor (#view's scroll padding) is not ours
      await sleep(150);
      const a = await ev(STATE);
      await type(word);
      check(await saved(word), `${L}: autosaved`);
      check(await until(`document.querySelector('#wk-saved')?.textContent === 'Saved'`), `${L}: the hint shows`);
      await until(`document.querySelector('#wk-saved')?.textContent === ''`);
      return {a, b: await ev(STATE)};
    };

    await nav(B + 'static/icon.svg');
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'frida', password: 'password123'})}).then(r => r.status)`);
    await size(640);
    await nav(B + `#wiki/${id}`);
    await until(`!!document.querySelector('[data-wk="pen"]')`);  // 2.554.0 (#4052): a phone reads first, the pen opens the editor
    await ev(`(() => { document.querySelector('[data-wk="pen"]').click(); return 1; })()`);
    await until(`!!document.querySelector('#wk-cm .cm-content') && !!WKCM.view`);
    // CodeMirror draws only the lines near the screen: the long part is brought into view first
    await ev(`(() => { const v = WKCM.view; v.dispatch({effects: CM6.EditorView.scrollIntoView(v.state.doc.toString().indexOf('Long line 45'), {y: 'center'})}); return 1; })()`);
    await until(`[...document.querySelectorAll('#wk-cm .cm-line')].some(x => x.textContent === 'Long line 45')`);

    // the file answers: the editor keeps its lines (its pictures keep their height)
    const redraw = await ev(`(() => { const l = [...document.querySelectorAll('#wk-cm .cm-line')].find(x => x.textContent.includes('Long line 4')); wkcm_redraw(); return !!l && l.isConnected; })()`);
    check(redraw, 'live: the answers leave the editor\'s lines as they are');

    // a real click into the middle of the long part, the keyboard comes, the cursor in the visible part
    const c = await ev(`(() => { const e = [...document.querySelectorAll('#wk-cm .cm-line')].find(x => x.textContent === 'Long line 45'); e.scrollIntoView({block: 'center'}); const r = e.getBoundingClientRect(); return {x: Math.round(r.left + 30), y: Math.round(r.top + r.height / 2)}; })()`);
    await act([{type: 'pointer', id: 'p1', parameters: {pointerType: 'mouse'}, actions: [{type: 'pointerMove', x: c.x, y: c.y}, {type: 'pointerDown', button: 0}, {type: 'pointerUp', button: 0}]}]);
    check(await until(`document.activeElement === WKCM.view?.contentDOM && WKCM.view.state.doc.lineAt(WKCM.view.state.selection.main.head).text === 'Long line 45'`), 'live: the click puts the cursor into that line');
    await size(380);
    const put = `(() => { const v = WKCM.view, at = v.state.doc.toString().indexOf('Long line 45'), x = document.querySelector('#view'); v.dispatch({selection: {anchor: at}}); const r = v.coordsAtPos(at); x.scrollTop += r.top - 130; return 1; })()`;
    await ev(put); await sleep(100);
    const live = await save('Zed', 'live');
    check(live.b.left > 300, `live: not at the end of the page (${live.b.left} px left)`);
    same(live.a, live.b, 'live', 3);
    await shot('p2459a-live.png');

    // the plain text editor, scrolled a little (the keyboard leaves little room), the cursor in the part of the field in view
    await ev(`(() => { wk_modeItems(WK.pg).find(x => x.label === 'Edit as Markdown').fn(); return 1; })()`);  // 2.554.0 (#4052): the "…" entry
    check(await until(`!!document.querySelector('#wk-body') && !document.querySelector('#wk-cm')`), 'text: the plain text field');
    await sleep(100);  // ntbFit after the redraw
    await ev(`(() => { const t = document.querySelector('#wk-body'), v = document.querySelector('#view'), at = t.value.indexOf('Long line 45'); t.focus({preventScroll: true}); t.setSelectionRange(at, at); v.scrollTop = 120; return v.scrollTop; })()`);
    await sleep(100);
    const text = await save('Yon', 'text');
    check(text.a.top > 50, `text: the view is scrolled (${text.a.top})`);
    same(text.a, text.b, 'text', 3);
    await shot('p2459a-text.png');
    await ev(`(() => { wk_modeItems(WK.pg).find(x => x.label === 'Back to the editor').fn(); return 1; })()`);
    check(await until(`!!document.querySelector('#wk-cm .cm-content')`), 'text: back in the editor');
  }, true);
  console.log(`p2459_a_wikisave_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
