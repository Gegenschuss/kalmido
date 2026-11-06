// kalmido-suite: fresh
// 2.580.0 B (#4800): the knowledge page editor (static/js/wkcm.js) brings the cursor into sight on a long page without jumping
// to the page's end. The page scrolls in #view (the editor has no scroller of its own); a page of 2000 lines with widgets
// (formulas, tables, boxes), Firefox (desktop), a person WITHOUT an organisation (her private space).
// - the cursor put on line 1000 (wkcm_caret, the way wiki.js wk_caretAt goes): line 1000 is on screen, #view not at its end
// - the stand-in field (wkcm_ta setSelectionRange, used by the slash menu / suggestions) to line 1500: on screen
// - a key press (ArrowDown) there keeps the view at that place; CodeMirror's own scrollIntoView effect (search, jumps) to line 300
// freelancer-matrix: wiki
// Invented texts only.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login, until: waitFor} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2580B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const firefox = require('./ff')({tag: 'p2580_b_wkscroll_ui', check, shots: 'P2580B_SHOTS'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
// 20 lines per part, 100 parts = 2000 lines; line 20 * i + 1 is "## Part i"
const part = i => [
  `## Part ${i}`, '',
  `Some **bold ${i}** words, a bit of *slant*, \`code ${i}\` and a [[Page ${i % 7}]] link.`,
  `A web address https://example.com/${i} and [a link](https://example.com/x${i}) in a line.`, '',
  `- [ ] Box ${i}`, `- [x] Done ${i}`, `- plain item ${i}`, '',
  `$$a_${i} + b^2 = c$$`, '',
  '| Name | Count |', '| --- | ---: |', `| apple ${i} | ${i} |`, '',
  `> A quote in part ${i}`, '',
  '$$', `x_${i} = \\frac{1}{${i + 1}}`, '$$',
].join('\n');
const BODY = Array.from({length: 100}, (_, i) => part(i)).join('\n');

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
  const pg = await call(CK, 'POST', '/api/wiki/pages', {space: 'private', path: 'Long', body: BODY});
  check(pg.id && BODY.split('\n').length === 2000, 'setup: a page of 2000 lines ' + BODY.split('\n').length);
  const id = pg.id;

  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    const until = (expr, ms = 20000) => waitFor(() => ev(expr).catch(() => null), {timeout: ms, step: 150});
    const size = (width, height) => cmd('browsingContext.setViewport', {context: ctx, viewport: {width, height}});
    const act = actions => cmd('input.performActions', {context: ctx, actions}).then(() => cmd('input.releaseActions', {context: ctx}));
    const signin = u => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
    const cm = `document.querySelector('#wk-cm .cm-content')`;
    // line n of the page is drawn and inside #view's visible part, #view is not at its end; after two frames still so
    const seen = n => `(() => { const v = WKCM.view, sc = document.querySelector('#view'); if (!v || !sc) return false;
      const at = v.state.doc.line(${n}).from, c = v.coordsAtPos(at), r = sc.getBoundingClientRect();
      return !!c && c.top >= r.top && c.bottom <= r.bottom && sc.scrollTop < sc.scrollHeight - sc.clientHeight - 4; })()`;
    const frames = () => ev(`new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => r(1))))`);
    const where = n => ev(`(() => { const v = WKCM.view, sc = document.querySelector('#view'), at = v.state.doc.line(${n}).from, c = v.coordsAtPos(at), r = sc.getBoundingClientRect();
      return JSON.stringify({top: sc.scrollTop, max: sc.scrollHeight - sc.clientHeight, view: [Math.round(r.top), Math.round(r.bottom)], line: c ? Math.round(c.top) : null,
        head: v.state.doc.lineAt(v.state.selection.main.head).number, vp: [v.state.doc.lineAt(v.viewport.from).number, v.state.doc.lineAt(v.viewport.to).number],
        trace: (window.__sc || []).slice(-12), hf: [document.hasFocus(), v.hasFocus], set: (window.__st || []).slice(-6), ce: (window.__ce || []).slice(-3), fh: v.state.facet(CM6.EditorView.scrollHandler).length,
 wk: !!document.querySelector('#wk-cm'), md: !!document.querySelector('#wk-md')}); })()`);
    const stays = async (n, what) => {
      const a = await until(seen(n), 8000);
      // 2.580.0 (#4800, B2): then the page is at rest - the formulas there drawn (diagram.js), no measure of CodeMirror
      // pending (heights that change later moved the line away in the merge check) - and two frames later still so
      if (a) await until(`!document.querySelector('#wk-cm pre[data-lang="math"]:not([data-dg]), #wk-cm .wkimath:not([data-dg])') && WKCM.view.measureScheduled < 0`, 8000);
      if (a) await frames();
      const b = a && await ev(seen(n));
      check(b, what + ' ' + (b ? '' : await where(n)));
    };
    // the scroll positions #view took (diagnosis on a failure)
    const trace = () => ev(`(() => { window.__sc = []; window.__st = []; const sc = document.querySelector('#view'); sc.addEventListener('scroll', () => window.__sc.push(Math.round(sc.scrollTop)));
      if (process.env.P2580B_DIAG !== '0' && !sc.__tr) { sc.__tr = 1; const D = Object.getOwnPropertyDescriptor(Element.prototype, 'scrollTop');
        Object.defineProperty(sc, 'scrollTop', {configurable: true, get() { return D.get.call(this); }, set(x) { window.__st.push(Math.round(x) + ' <- ' + String(new Error().stack).split('\\n').slice(1, 5).map(l => l.replace(/@.*\\//, '@')).join(' | ')); D.set.call(this, x); }}); }
      if (!window.__ce) { window.__ce = []; const e0 = console.error; console.error = (...a) => { window.__ce.push(a.map(x => String(x && x.stack || x)).join(' ').slice(0, 300)); e0.apply(console, a); }; }
      return 1; })()`.replace('process.env.P2580B_DIAG', JSON.stringify(process.env.P2580B_DIAG || '1')));
    const top = () => ev(`(() => { const sc = document.querySelector('#view'); sc.scrollTop = 0; return new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => r(sc.scrollTop)))); })()`);

    await nav(B + 'static/icon.svg');
    await signin('frida');
    // desktop only: the phone's read view of this page (2000 lines, 200 formulas) did not get ready within a minute on the test
    // Mac (seen 06.11.2026); #view and the bringing-into-sight are the same at every width
    // 2.580.0 (#4800, B2): twice, each on a freshly loaded page (the heights only estimated): the window with the system's
    // focus, then without it (document.hasFocus() false: another window in front, a busy test Mac with many browsers).
    // Without it CodeMirror does not hold #view's place when heights change after a measure (seen in the merge check: line
    // 1001 9181 px above the screen after ArrowDown); wkcm.js wkcm_hold does it then
    for (const [w, h, tag, nofocus] of [[1280, 900, 'desktop', false], [1280, 900, 'desktop without focus', true]]) {
      await size(w, h);
      await nav(B + 'static/icon.svg');
      await nav(B + `#wiki/${id}`);
      check(await until(`!!${cm} && WKCM.view.state.doc.lines === 2000`, 40000), tag + ': the long page is in the editor ' + await ev(`JSON.stringify({wk: !!document.querySelector('#wk-cm'), cm: !!document.querySelector('#wk-cm .cm-content'), md: !!document.querySelector('#wk-md'), pen: !!document.querySelector('[data-wk="pen"]'), lines: window.WKCM?.view?.state.doc.lines})`));
      if (nofocus) await ev(`(() => { document.hasFocus = () => false; return 1; })()`);
      await trace();
      check(await top() === 0, tag + ': #view at the top');
      // the cursor on line 1000 the way wiki.js puts it (wk_caretAt -> wkcm_caret)
      await ev(`(() => { wkcm_caret(WKCM.view.state.doc.line(1000).from); return 1; })()`);
      await stays(1000, tag + ': the cursor on line 1000 is on screen, not the page\'s end');
      check(await ev(`WKCM.view.state.doc.lineAt(WKCM.view.state.selection.main.head).number === 1000 && document.activeElement === ${cm}`), tag + ': the cursor is on line 1000 with the focus');
      // a key press there keeps the place
      await act([{type: 'key', id: 'k', actions: [{type: 'keyDown', value: '\uE015'}, {type: 'keyUp', value: '\uE015'}]}]);
      check(await until(`WKCM.view.state.doc.lineAt(WKCM.view.state.selection.main.head).number === 1001`), tag + ': ArrowDown moved to line 1001');
      await stays(1001, tag + ': after ArrowDown line 1001 is on screen');
      // 2.580.0 (#4800, B2): a font arriving late (a busy machine) changes every estimated height above the screen at once;
      // the cursor's line stays on screen once CodeMirror measured the new size
      const lh0 = await ev(`WKCM.view.defaultLineHeight`);
      await ev(`(() => { const c = ${cm}; c.style.fontSize = (parseFloat(getComputedStyle(c).fontSize) * 1.25) + 'px'; return 1; })()`);
      check(await until(`Math.abs(WKCM.view.defaultLineHeight - ${lh0}) > 1`), tag + ': CodeMirror measured the larger font');
      await stays(1001, tag + ': after a late font line 1001 is still on screen');
      // the stand-in field of the slash menu / suggestions, from the top
      await top();
      await ev(`(() => { const ta = wkcm_ta(), at = WKCM.view.state.doc.line(1500).from; ta.setSelectionRange(at, at); return 1; })()`);
      await stays(1500, tag + ': setSelectionRange to line 1500 brings it on screen');
      // CodeMirror's own effect (search, jumps), back up to line 300
      await ev(`(() => { const v = WKCM.view; v.dispatch({effects: CM6.EditorView.scrollIntoView(v.state.doc.line(300).from, {y: 'center'})}); return 1; })()`);
      await stays(300, tag + ': the scrollIntoView effect to line 300 brings it on screen');
      await shot(`p2580b-${tag.replace(/ /g, '-')}.png`);
    }
  }, false);
  console.log(`p2580_b_wkscroll_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
