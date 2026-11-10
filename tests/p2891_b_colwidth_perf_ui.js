// 2.891.0 B (#5360) UI test: dragging a column's width grip in a big list stays fluid and the rows take the new width at once.
// kalmido-suite: fresh
// Real Firefox (WebDriver BiDi), real mouse input on the grip of a field column, a desktop window (1440 x 900):
// - a list with 300 rows (the most that is drawn without the virtual list) and five columns (due, priority, three fields)
// - a list with 1000 rows (the virtual list draws only the rows near the visible part), the same columns
// Measured per drag (DRAGPERF lines, the numbers of the report): frames per second while the grip moves (about one second, back
// and forth), the longest frame, and the time from the release until the rows stand in their new width (the release's own
// script, the style and layout it causes, and the frame after it), the rows that had to be laid out again.
// Each drag runs as the drawing before 2.806 ("old": the rows out of view skip their drawing from the press - #4860, meant for
// the panel grips - and all are laid out again on release) and as now (the rows stay as they are while a column width is
// dragged), alternating in the same run on the same machine (a fair comparison), each from the same start width (8 rem).
// Measured in Firefox only (the Mac runner drives Firefox); Chrome and Safari are a point of the device test.
// Checks: the targets (decision of 09.11.2026: at least 50 frames/s while dragging, under 100 ms from the release until the rows
// stand), now not slower than before (fall-back test: the old way costs clearly more on release), the visible rows take the
// new width (row cell = column title), the content stays (titles readable, no row lost), and no redraw of the whole list after
// release - not by the release itself and not by the echo of the stored width (the next change check; the row nodes stay).
// freelancer-matrix: n/a (no route; PATCH /api/settings only, covered by p2742_b_colwidth_ui for a person without organisation)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2891_b_colwidth_perf_ui', check, shots: 'P2891B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return Array.isArray(j) ? j : {...j, http: r.status}; };
const WORDS = 'offer invoice follow up with the client about the draft and the meeting notes from last week before Friday'.split(' ');

// in the page, while the grip is pressed: the frames; on release (window, capture: before the app's own handler) the time the
// release's script takes, the time until the next frame (Firefox already lays out here: it finds the target of the mouse release
// and the click), in that frame the style and layout still open (forced and timed) and the end of that frame and of the next
const PROBE = `(() => {
  const P = window.__cw = {frames: [], t0: 0, done: false, renders: 0, rows0: null};
  for (const n of ['render', 'renderView']) { if (typeof window[n] !== 'function' || window[n].__cw) continue;
    const f0 = window[n], f = window[n] = function () { const P = window.__cw; if (P && P.t0) P.renders++; return f0.apply(this, arguments); }; f.__cw = 1; }
  if (!window.__cwApi) { window.__cwApi = api; api = function (m, u) { const p = window.__cwApi.apply(this, arguments);
    if (m === 'PATCH' && u === '/api/settings') { const P = window.__cw; if (P) P.patch = 1; p.then(() => { if (window.__cw) window.__cw.patchAt = Date.now(); }, () => {}); } return p; }; }
  P.rows0 = [...document.querySelectorAll('#view .trow[data-id]')].slice(0, 40); P.rows0.forEach(r => { r.__cw = 1; });
  let last = performance.now(); const tick = t => { if (window.__cw !== P || P.t0) return; P.frames.push(t - last); last = t; requestAnimationFrame(tick); };
  requestAnimationFrame(tick);
  const v = document.getElementById('view');
  window.addEventListener('pointerup', () => { P.t0 = performance.now();
    requestAnimationFrame(() => { const a = performance.now(); const c = v.querySelector('.trow[data-id] .lc.lc-f'); void (c && getComputedStyle(c).width);
      const b = performance.now(); void v.scrollHeight; void (c && c.getBoundingClientRect().width); const e = performance.now();
      P.sty = b - a; P.lay = e - b; P.ta = a;
      setTimeout(() => { P.t2 = performance.now(); requestAnimationFrame(() => { P.tb = performance.now(); setTimeout(() => { P.t3 = performance.now(); P.done = true; }, 0); }); }, 0); }); }, {capture: true, once: true});
  window.addEventListener('pointerup', () => { P.t1 = performance.now(); }, {once: true});
  return 1; })()`;
const RESULT = `(() => { const P = window.__cw;
  const q = (a, f) => { const s = [...a].sort((x, y) => x - y); return s.length ? Math.round(s[Math.min(s.length - 1, Math.floor(s.length * f))] * 10) / 10 : 0; };
  const fr = P.frames.slice(1), ms = fr.reduce((n, x) => n + x, 0), r1 = x => Math.round(x * 10) / 10;
  return {frames: fr.length, fps: ms ? r1(fr.length * 1000 / ms) : 0, med: q(fr, 0.5), p95: q(fr, 0.95), max: r1(Math.max(0, ...fr)),
    upJs: r1(P.t1 - P.t0), toRaf: r1(P.ta - P.t1), frame1: r1(P.t2 - P.ta), frame2: r1(P.t3 - P.tb), sty: r1(P.sty), lay: r1(P.lay), release: r1(P.t2 - P.t0), renders: P.renders,
    rows: document.querySelectorAll('#view .trow[data-id]').length}; })()`;
// the drawing before 2.806 (#5360), switched on in the page for the comparison
// (the rows skip their drawing while any grip is dragged, all take the new width at once on release)
const OLD = `(() => { if (!document.getElementById('cwold')) document.head.appendChild(Object.assign(document.createElement('style'), {id: 'cwold',
  textContent: 'body.pgdrag.lcwdrag .trow:not(:has(> .caret)):not(.iedit){content-visibility:auto}'})); return 1; })()`;
const NEW = `(() => { document.getElementById('cwold')?.remove(); return 1; })()`;
// every drag starts from the same state: no row waits for a width of the drag before, all laid out, two frames drawn
const RESET = `(async () => {
  void document.getElementById('view').scrollHeight; await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))); return 1; })()`;
// the first row in view and its top: nothing visible may move on release (a quiet view)
const FIRST = `(() => { const v = document.getElementById('view').getBoundingClientRect(); const r = [...document.querySelectorAll('#view .trow[data-id]')].find(x => x.getBoundingClientRect().bottom > v.top + 1); return r ? r.dataset.id + '@' + Math.round(r.getBoundingClientRect().top) : ''; })()`;

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', modules: ['fields']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'fields'});
  const lists = {};
  for (const [name, n] of [['Three hundred', 300], ['A thousand', 1000]]) {
    const L = (await call(CA, 'POST', '/api/lists', {name})).id;
    const f1 = (await call(CA, 'POST', `/api/lists/${L}/fields`, {name: 'Client', type: 'text'})).id;
    const f2 = (await call(CA, 'POST', `/api/lists/${L}/fields`, {name: 'Hours', type: 'number'})).id;
    const f3 = (await call(CA, 'POST', `/api/lists/${L}/fields`, {name: 'Note', type: 'text'})).id;
    await call(CA, 'PATCH', `/api/lists/${L}`, {columns: ['due', 'prio', `f:${f1}`, `f:${f2}`, `f:${f3}`]});
    const T = [];
    for (let i = 0; i < n; i += 25) T.push(...(await Promise.all(Array.from({length: Math.min(25, n - i)}, (_, j) => {
      const k = i + j, title = `Row ${k + 1} ` + Array.from({length: 3 + (k * 7) % 14}, (_, m) => WORDS[(k + m) % WORDS.length]).join(' ');
      return call(CA, 'POST', '/api/tasks', {title, list_id: L, due: `2026-11-${String(1 + k % 28).padStart(2, '0')}`, priority: k % 3 ? 0 : 5,
        fields: {[f1]: `Client ${k % 17}`, [f2]: k % 40, [f3]: WORDS.slice(k % 9, k % 9 + 4).join(' ')}});
    }))).map(t => t.id));
    check(T.filter(Boolean).length === n, `setup: ${n} tasks ` + T.filter(Boolean).length);
    lists[n] = {L, k: `f:${f1}`, T};
  }

  const ready = async (ev, expr, n = 80) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const out = [];
  await firefox(async o => {
    const {cmd, ev, ctx, nav, shot} = o;
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    // one drag of the grip of column k: down, 60 moves of 16 ms back and forth (80 px), up 40 px left of the start (wider)
    const drag = async (n, k, tag, old) => {
      await ev(old ? OLD : NEW);
      await ev(`(() => { lcwSet(${lists[n].L}, '${k}', 8); return 1; })()`);  // the same start width each time: every drag changes it by the same
      await ev(RESET);
      tag += old ? '-old' : '';
      const g = await ev(`(() => { const g = document.querySelector('#view .lchead .lcg[data-lcg="${k}"]'); if (!g) return null; const r = g.getBoundingClientRect(); return {x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2)}; })()`);
      check(!!g, `${tag}: the grip of the field column is there`);
      if (!g) return null;
      const w0 = await ev(`lcwGet(${lists[n].L})['${k}'] || 0`), first0 = await ev(FIRST);
      await ev(PROBE);
      const moves = [];
      for (let i = 1; i <= 60; i++) moves.push({type: 'pointerMove', x: Math.round(g.x - 80 * Math.sin(i / 60 * Math.PI * 2) - (i > 45 ? 40 * (i - 45) / 15 : 0)), y: g.y, duration: 16});
      await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'cw', parameters: {pointerType: 'mouse'},
        actions: [{type: 'pointerMove', x: g.x, y: g.y}, {type: 'pointerDown', button: 0}, ...moves, {type: 'pointerUp', button: 0}]}]});
      await cmd('input.releaseActions', {context: ctx});
      check(await ready(ev, `!!window.__cw?.done`, 40), `${tag}: the release was measured`);
      const r = await ev(RESULT);
      // the echo: the next change check after the stored width came back, and a redraw it may have planned, are over
      const echo = await ready(ev, `(() => { const P = window.__cw; return !!P.patchAt && S.syncOk > P.patchAt && !td_polling && !td_rsT; })()`, 60);
      check(echo, `${tag}: the stored width came back and the next change check ran`);
      Object.assign(r, await ev(`(() => { const P = window.__cw; return {renders: P.renders, kept: P.rows0.filter(x => x.isConnected).length, of: P.rows0.length}; })()`));
      r.w = await ev(`lcwGet(${lists[n].L})['${k}'] || 0`);
      r.first = [first0, await ev(FIRST)];
      check(r.first[0] === r.first[1], `${tag}: nothing in view moves on release (first row ${r.first.join(' -> ')})`);
      r.cells = await ev(`(() => { const h = document.querySelector('#view .lchead .lc[data-k="${k}"]').getBoundingClientRect().width, v = document.getElementById('view').getBoundingClientRect();
        const rows = [...document.querySelectorAll('#view .trow[data-id]')].filter(x => { const b = x.getBoundingClientRect(); return b.bottom > v.top && b.top < v.bottom; });
        return {h: Math.round(h), n: rows.length, off: rows.filter(x => Math.abs(x.querySelector('.lc[data-k="${k}"]').getBoundingClientRect().width - h) > 1).length,
          text: rows.filter(x => /^Row \\d+/.test((x.querySelector('.ttl, .title, [data-ttl]') || x).textContent.trim()) || /Row \\d+/.test(x.textContent)).length}; })()`);
      console.log(`DRAGPERF ${tag}: ` + JSON.stringify(r));
      check(r.w !== w0 && r.w > 0, `${tag}: the dragged width is kept (${w0} -> ${r.w} rem)`);
      check(r.cells.n >= 10 && r.cells.off === 0, `${tag}: the visible rows take the new width of the column title (${r.cells.off} of ${r.cells.n} differ, title ${r.cells.h} px)`);
      check(r.cells.text === r.cells.n, `${tag}: the visible rows still show their titles (${r.cells.text} of ${r.cells.n})`);
      out.push([tag, r]);
      return r;
    };
    for (const n of [300, 1000]) {
      const {L, k} = lists[n];
      await nav(B + `#l/${L}`);
      check(await ready(ev, `document.querySelectorAll('#view .trow[data-id]').length >= 30 && !!document.querySelector('#view .lchead .lcg[data-lcg="${k}"]')`), `${n}: the list shows its rows and the column titles`);
      const drawn = await ev(`document.querySelectorAll('#view .trow[data-id]').length`);
      check(n === 300 ? drawn === 300 : drawn < 300, `${n}: ${n === 300 ? 'all rows drawn (no virtual list)' : 'the virtual list draws only the rows near the visible part'} (${drawn})`);
      // the column titles scroll with the rows: the drag starts at the top, most rows are out of view below
      check(await ev(`(() => { const v = document.getElementById('view'), h = document.querySelector('#view .lchead').getBoundingClientRect(); return h.top >= 0 && h.bottom < innerHeight && v.scrollHeight > 3 * v.clientHeight; })()`), `${n}: the column titles in view, most rows below`);
      const runs = {old: [], now: []};
      for (const old of [true, false, true, false, true, false]) { const r = await drag(n, k, `list${n}`, old); if (r) runs[old ? 'old' : 'now'].push(r); }
      const med = (a, f) => { const s = a.map(f).sort((x, y) => x - y); return s.length ? s[Math.floor(s.length / 2)] : NaN; };
      const m = x => ({fps: med(runs[x], r => r.fps), release: med(runs[x], r => r.release), max: med(runs[x], r => r.max), sty: med(runs[x], r => r.sty), lay: med(runs[x], r => r.lay)});
      const mo = m('old'), mn = m('now');
      console.log(`PERF colwidth list${n} median old ${JSON.stringify(mo)} | now ${JSON.stringify(mn)}`);
      check(mn.fps >= 50, `${n}: at least 50 frames/s while the grip moves (${mn.fps}; before ${mo.fps})`);
      check(mn.release < 100, `${n}: under 100 ms from the release until the rows stand (${mn.release} ms; before ${mo.release} ms)`);
      check(runs.now.every(r => r.renders === 0 && r.kept === r.of), `${n}: no redraw of the list after the release nor by the echo of the stored width (renders ${runs.now.map(r => r.renders)}, row nodes kept ${runs.now.map(r => r.kept + '/' + r.of)})`);
      if (n === 300) check(mo.release > 1.25 * mn.release, `${n}: fall-back: the old drawing costs clearly more on release (${mo.release} vs ${mn.release} ms)`);
      await shot(`p2891b-list${n}.png`);
      // further down: the rows that were out of view show the new width too once they come into view
      await ev(`(() => { const v = document.getElementById('view'); v.scrollTop = v.scrollHeight; return 1; })()`);
      const LOW = `(() => { const h = document.querySelector('#view .lchead .lc[data-k="${k}"]').getBoundingClientRect().width, v = document.getElementById('view').getBoundingClientRect();
        const rows = [...document.querySelectorAll('#view .trow[data-id]')].filter(x => { const b = x.getBoundingClientRect(); return b.bottom > v.top && b.top < v.bottom; });
        return rows.length >= 10 && rows.every(x => Math.abs(x.querySelector('.lc[data-k="${k}"]').getBoundingClientRect().width - h) <= 1 && /Row \\d+/.test(x.textContent)); })()`;
      check(await ready(ev, LOW, 40), `${n}: at the end of the list the rows show the new width and their titles`);
      await shot(`p2891b-list${n}-end.png`);
      await ev(`(() => { document.getElementById('view').scrollTop = 0; return 1; })()`);
    }
    // usable afterwards: a double-click on the grip gives the automatic width back, a click on the title still opens the task
    const {L, k, T} = lists[300];
    await nav(B + `#l/${L}`);
    check(await ready(ev, `!!document.querySelector('#view .lchead .lcg[data-lcg="${k}"]') && !!document.querySelector('#tc-${T[0]}')`), 'back in the list of 300');
    await ev(`(() => { document.querySelector('#view .lchead .lcg[data-lcg="${k}"]').dispatchEvent(new MouseEvent('dblclick', {bubbles: true})); return 1; })()`);
    check(await ready(ev, `!('${k}' in lcwGet(${L}))`), 'a double-click on the grip = the automatic width again');
    await ev(`(() => { openDetail(${T[0]}); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('#detail:not(.hidden) .dtop')`), 'a task still opens from the list');
  }, false);
  console.log('PERF colwidth summary: ' + out.map(([t, r]) => `${t} ${r.fps} fps (max frame ${r.max} ms), release ${r.release} ms (script ${r.upJs}, until the next frame ${r.toRaf}, that frame ${r.frame1}), renders ${r.renders}`).join(' | '));
  if (process.env.P2891B_SHOTS) require('fs').writeFileSync(path.join(process.env.P2806A_SHOTS, 'p2891b-colwidth.json'), JSON.stringify(out, null, 1));
  console.log(`p2891_b_colwidth_perf_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
