// 2.574.0 B (#4681): the knowledge page editor (static/js/wkcm.js) on a long page: what one typed letter costs
// kalmido-suite: fresh
// - a page of 2000 lines (headings, bold / code / links, lists with boxes, $$ formulas, tables, quotes) opens in the editor
// - one letter typed in the middle (line 1003, a text line; a CodeMirror transaction like a key press, the decorations built again): the time is
//   printed (median / 90 % / max over 40 letters, desktop and the 390 px phone view), and the time of the decorations alone
//   (wkcm_build, for the part around the screen and for the whole text); 2.574.0 (#4681): a page that long gets its decorations only
//   around the part on screen (the measure: 15-17 ms per letter before, over 16 ms). No fixed upper limit is checked (a timing check on a shared machine would wobble), the numbers go into the log
// - the typed letters are in the text, a $$ formula far below the visible part is still drawn as a formula once scrolled to
// Invented texts only.
const path = require('path'), fs = require('fs');
const {execFileSync} = require('child_process');
const {sleep, B, login, until: waitFor} = require('./boot');
const F = []; let ok = 0;
// the numbers: in the log, and with P2574B_SHOTS also as a file there (a green run of run_all.sh keeps no suite output)
const said = [];
const say = t => { console.log(t); said.push(t); if (process.env.P2574B_SHOTS) { try { fs.mkdirSync(process.env.P2574B_SHOTS, {recursive: true}); fs.writeFileSync(path.join(process.env.P2574B_SHOTS, 'p2574b-measure.txt'), said.join('\n') + '\n'); } catch { /* no folder */ } } };
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2574B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const firefox = require('./ff')({tag: 'p2574_b_wkcm_ui', check, shots: 'P2574B_SHOTS'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
// 20 lines per part, 100 parts = 2000 lines
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
  const CK = await login('frida');  // a person without an organisation (her private space)
  await call(CK, 'PATCH', '/api/settings', {tour: 'done', lang: 'en', features: feats});
  const pg = await call(CK, 'POST', '/api/wiki/pages', {space: 'private', path: 'Long', body: BODY});
  check(pg.id && BODY.split('\n').length === 2000, 'setup: a page of 2000 lines ' + BODY.split('\n').length);
  const id = pg.id;

  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    const until = (expr, ms = 20000) => waitFor(() => ev(expr).catch(() => null), {timeout: ms, step: 150});
    const size = (width, height) => cmd('browsingContext.setViewport', {context: ctx, viewport: {width, height}});
    const signin = u => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
    const cm = `document.querySelector('#wk-cm .cm-content')`;
    // 40 letters typed one by one at the end of line 1003 (a text line, not a $$ line) (each its own transaction, as a key press), then the decorations alone
    // (the cursor put there with the screen scrolled to it, as a click would; the decorations follow the screen first)
    const measure = async () => {
      // 2.640.0 (#5019): the cursor is put there WITHOUT CodeMirror's own scrollIntoView: that scroll is done in CodeMirror's next
      // measure (a frame later) and lands at the end of this page (#4800); on a slow CI runner it came after the test's own
      // scroll below and moved the screen away again (seen with delayed frames on the Mac: the test at 75 ms to line 1003,
      // CodeMirror at 85 ms to the page end). The test's one scroll below is the only one.
      await ev(`(() => { const v = WKCM.view; v.focus(); v.dispatch({selection: {anchor: v.state.doc.line(1003).to}}); return 1; })()`);
      // the page scrolls in #view (the editor has no scroller of its own): its line brought on screen there (CodeMirror's own
      // scrollIntoView lands at the end of this page, with the decorations of the whole text as well - seen 06.11.2026)
      // 2.627.0 (#4977): the scroll is set ONCE, then only waited for (it was moved again in every poll: on a slow CI run it
      // kept moving while the decorations were still following the last one); a second scroll only when the first one did
      // not bring the line on screen (the line heights below were estimates until drawn)
      // 2.783.0 (#5376): on a computer the page's text scrolls inside the card (.wkcm), on the phone #view: the nearest box
      // around the editor that really scrolls
      const wkcm_sc = `const wkcm_sc = v => { for (let e = v.dom; e && e.id !== 'view'; e = e.parentElement) { const o = getComputedStyle(e).overflowY;
        if ((o === 'auto' || o === 'scroll') && e.scrollHeight > e.clientHeight + 1) return e; } return document.querySelector('#view'); };`;
      const to1003 = `(() => { ${wkcm_sc} const v = WKCM.view, at = v.state.doc.line(1003).from, sc = wkcm_sc(v);
        sc.scrollTop += v.documentTop + v.lineBlockAt(at).top - sc.getBoundingClientRect().top - 200; return 1; })()`;
      const on1003 = `(() => { ${wkcm_sc} const v = WKCM.view, at = v.state.doc.line(1003).from; return v.visibleRanges.some(x => x.from <= at && x.to >= at); })()`;
      // 2.640.0 (#5019): after each scroll the test waits until CodeMirror has drawn the place the screen shows (its viewport holds
      // the line at the top of #view: the scroll is measured, the line heights there are real) - never a fixed time; only then, and
      // only when line 1003 is still not on screen (the first scroll used estimated heights: on the phone it landed near line 1450,
      // seen 07.11.2026), it is scrolled once more with the heights CodeMirror knows now; at most four times
      const drawn = `(() => { ${wkcm_sc} const v = WKCM.view, sc = wkcm_sc(v), at = v.lineBlockAtHeight(sc.getBoundingClientRect().top - v.documentTop + 1).from;
        return v.viewport.from <= at && v.viewport.to >= at; })()`;
      let seen = false;
      for (let i = 0; i < 4 && !seen; i++) { await ev(to1003); await until(drawn, 10000); seen = !!(await until(on1003, 2000)); }
      // 2.640.0 (#5019): a red check says where screen, CodeMirror's viewport and the decorated part stood (the CI log keeps only FAIL lines)
      const where = `(() => { ${wkcm_sc} const v = WKCM.view, f = v.state.field(WKCM_FIELD), ln = p => v.state.doc.lineAt(Math.min(p, v.state.doc.length)).number;
        return JSON.stringify({top: Math.round(wkcm_sc(v).scrollTop), viewport: [ln(v.viewport.from), ln(v.viewport.to)], told: [ln(f.vp.from), ln(f.vp.to)], part: f.r ? [ln(f.r.from), ln(f.r.to)] : null}); })()`;
      check(seen, 'line 1003 is on screen' + (seen ? '' : ' ' + await ev(where)));
      const fol = await until(`(() => { const v = WKCM.view, r = v.state.field(WKCM_FIELD).r, at = v.state.doc.line(1003).from; return !!r && r.from <= at && r.to >= at; })()`);
      check(fol, 'the decorations followed the screen to line 1003' + (fol ? '' : ' ' + await ev(where)));
      return ev(`(() => {
      const v = WKCM.view, ts = [];
      for (let i = 0; i < 40; i++) { const h = v.state.selection.main.head, t = performance.now();
        v.dispatch({changes: {from: h, insert: 'q'}, selection: {anchor: h + 1}, userEvent: 'input.type'}); ts.push(performance.now() - t); }
      const r = v.state.field(WKCM_FIELD).r, bs = [], ba = [];
      for (let i = 0; i < 10; i++) { let t = performance.now(); wkcm_build(v.state, true, r); bs.push(performance.now() - t); t = performance.now(); wkcm_build(v.state, true, null); ba.push(performance.now() - t); }
      const q = (a, p) => { const s = [...a].sort((x, y) => x - y); return Math.round(s[Math.min(s.length - 1, Math.floor(p * s.length))] * 10) / 10; };
      return {med: q(ts, .5), p90: q(ts, .9), max: q(ts, 1), build: q(bs, .5), all: q(ba, .5), part: r ? v.state.doc.lineAt(r.to).number - v.state.doc.lineAt(r.from).number + 1 : 0, typed: v.state.doc.line(1003).text.endsWith('q'.repeat(40))};
    })()`);
    };

    await nav(B + 'static/icon.svg');
    await signin('frida');
    await size(1280, 900);
    await nav(B + `#wiki/${id}`);
    check(await until(`!!${cm} && WKCM.view.state.doc.lines === 2000`), 'desktop: the long page is in the editor');
    const d = await measure();
    say(`p2574_b_wkcm_ui: MEASURE desktop 1280 px, 2000 lines: one letter median ${d.med} ms, 90 % ${d.p90} ms, max ${d.max} ms; decorations alone (wkcm_build) ${d.build} ms for ${d.part} lines (the whole text: ${d.all} ms)`);
    // 2.574.0 (#4681): a long page: the decorations cover the part around the screen, not all 2000 lines
    check(d.part > 0 && d.part < 1000, 'desktop: the decorations are built for a part of the long page (' + d.part + ' lines)');
    check(d.typed, 'desktop: the 40 letters are in the text');
    // a formula far below the visible part (lines 1990 and 1998-2000) is drawn as one once scrolled to, its $$ source hidden
    await ev(`(() => { WKCM.view.contentDOM.blur(); return 1; })()`);
    // 2.627.0 (#4977): scrolled to line 1999 once, then only waited for (no new scroll in every poll)
    await ev(`(() => { const v = WKCM.view; v.dispatch({effects: CM6.EditorView.scrollIntoView(v.state.doc.line(1999).from, {y: 'center'})}); return 1; })()`);
    const far = `(() => { const v = WKCM.view;
      const ws = [...document.querySelectorAll('#wk-cm .cm-wkwb')].filter(w => /x_99|a_99/.test(w.textContent) || (w.querySelector('.wkdgmath') && /99/.test(w.textContent)));
      const r = v.state.field(WKCM_FIELD).r;  // 2.574.0 (#4681): the part followed the scroll to the end
      return ws.length >= 1 && !!r && r.to === v.state.doc.length && r.from > 0 && ![...document.querySelectorAll('#wk-cm .cm-line')].some(l => /\\$\\$/.test(l.textContent) && /99/.test(l.textContent)); })()`;
    check(await until(far), 'desktop: a formula near the end is drawn as a formula once scrolled to');
    await shot('p2574b-far.png');

    // the phone view: the pen opens the same editor
    await size(390, 760);
    await nav(B + 'static/icon.svg');
    await nav(B + `#wiki/${id}`);
    check(await until(`!!document.querySelector('[data-wk="pen"]')`), 'phone: the page is read first, with the pen');
    await ev(`(() => { document.querySelector('[data-wk="pen"]').click(); return 1; })()`);
    check(await until(`!!${cm} && WKCM.view.state.doc.lines === 2000`), 'phone: the pen opens the long page in the editor');
    const m = await measure();
    say(`p2574_b_wkcm_ui: MEASURE phone 390 px, 2000 lines: one letter median ${m.med} ms, 90 % ${m.p90} ms, max ${m.max} ms; decorations alone (wkcm_build) ${m.build} ms for ${m.part} lines (the whole text: ${m.all} ms)`);
    check(m.typed, 'phone: the 40 letters are in the text');
  }, false);
  console.log(`p2574_b_wkcm_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
