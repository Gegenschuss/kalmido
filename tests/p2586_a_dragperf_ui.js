// 2.586.0 A (#4860) UI tests: dragging a panel's grip stays live (the content reflows every frame) but each frame is cheaper.
// kalmido-suite: fresh
// Real Firefox (WebDriver BiDi), real pointer input on the grip, a big (2560 px) and a small (1280 px) window:
// - a list with 300 rows (the most that is still drawn without the virtual list) and the task panel open: its grip dragged
//   for about one second, back and forth
// - the documents with many tiles: the sidebar's grip dragged the same way
// Measured per drag (printed as DRAGPERF lines, the numbers of the report): frames, median / p95 time between frames, the
// style + layout time of one width step (forced right after the step sets the width), and the ResizeObserver callbacks
// that ran during the drag (count + time, by the file that made the observer).
// Checks (fall-back test): the width follows live (the content of #view is narrower / wider during the drag, not only on
// release); the body carries the "dragging" class during the drag and not after; the watchers that fit the bars (fitTop,
// fitDtop, lsd_sync) rest during the drag (at most a few callbacks instead of one per frame) and run once after release, so
// the bars and the list/detail pair fit the final width; the inline title field keeps the height of its text after release.
// freelancer-matrix: n/a (no route; the layout is the same without an organisation)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2586_a_dragperf_ui', check, shots: 'P2586A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2586A_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return Array.isArray(j) ? j : {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,docs,files';
const WORDS = 'offer invoice follow up with the client about the draft and the meeting notes from last week before Friday'.split(' ');

// in every page before the app's scripts: each ResizeObserver callback is counted and timed, by the file that made it
const RO_WRAP = `() => { const RO = window.ResizeObserver; if (!RO || window.__ro) return;
  const st = window.__ro = {on: false, n: 0, ms: 0, by: {}};
  window.ResizeObserver = class extends RO { constructor(cb) {
    const at = String(new Error().stack || '').split('\\n').find(l => /static\\/js\\//.test(l) && !/constructor/.test(l)) || '?';
    const name = (at.match(/static\\/js\\/([^?:]+)[^:]*:(\\d+)/) || [0, '?', 0]).slice(1, 3).join(':');
    super((es, o) => { const t = performance.now(); try { return cb(es, o); } finally { if (st.on) { const d = performance.now() - t; st.n++; st.ms += d; const b = st.by[name] || (st.by[name] = {n: 0, ms: 0}); b.n++; b.ms += d; } } });
  } };
}`;
// in the page: the width steps of the drag timed (rafThrottle is wrapped while the grip is pressed: each step's own work +
// the style / layout it causes, forced at once), the frames counted
const PROBE = `(() => {
  const P = window.__dp = {steps: [], sty: [], lay: [], frames: [], cls: [], vw: [], at: [], fitDrag: {}, fitAfter: {}};
  // the fitting functions of the bars and modes: how often they ran during the drag and after release
  for (const n of ['fitTop', 'fitDtop', 'lsd_sync', 'agb_fit', 'ttlinFit', 'ttlinFitAll']) {
    if (typeof window[n] !== 'function' || window[n].__w) continue;
    const f0 = window[n], f = window[n] = function () { const P = window.__dp; if (P && !P.done) { const b = document.body.classList.contains('pgdrag') ? P.fitDrag : P.fitAfter; b[n] = (b[n] || 0) + 1; } return f0.apply(this, arguments); };
    f.__w = 1;
  }
  // 2.1102.0 (#5516): which resting watchers still waited when the drag ended (core.js dragRestFlush runs them): the first flush
  if (!dragRestFlush.__w) { const f0 = dragRestFlush; dragRestFlush = function () { const P = window.__dp; if (P && !P.done && !P.pend) P.pend = [...DRAGREST.fns.keys()]; return f0.apply(this, arguments); }; dragRestFlush.__w = 1; }
  if (!window.__rt0) { window.__rt0 = rafThrottle;
    rafThrottle = fn => window.__rt0((...a) => { const t = performance.now(); fn(...a); const v = document.getElementById('view');
      const t1 = performance.now(); void getComputedStyle(document.body).color; const t2 = performance.now();  // style first (the whole document), then layout
      void document.documentElement.getBoundingClientRect(); void (v && v.scrollHeight);
      const P = window.__dp; if (P) { P.steps.push(performance.now() - t); P.sty.push(t2 - t1); P.lay.push(performance.now() - t2); P.cls.push(document.body.classList.contains('pgdrag')); P.vw.push(v ? v.clientWidth : 0); P.at.push(performance.now()); if (P.cv == null) P.cv = [...document.querySelectorAll('#view .trow, #view .dc-card')].filter(x => getComputedStyle(x).contentVisibility === 'auto').length; } }); }
  window.__ro.on = true; window.__ro.n = 0; window.__ro.ms = 0; window.__ro.by = {};
  let last = performance.now(); const tick = t => { if (!window.__dp || window.__dp !== P || P.done) return; P.frames.push(t - last); last = t; requestAnimationFrame(tick); };
  requestAnimationFrame(tick); return 1; })()`;
const RESULT = `(() => { const P = window.__dp; P.done = true; window.__ro.on = false;
  const q = (a, f) => { const s = [...a].sort((x, y) => x - y); return s.length ? Math.round(s[Math.min(s.length - 1, Math.floor(s.length * f))] * 10) / 10 : 0; };
  const fr = P.frames.slice(1);
  return {frames: fr.length, med: q(fr, 0.5), p95: q(fr, 0.95), steps: P.steps.length, stepMed: q(P.steps, 0.5), stepP95: q(P.steps, 0.95), styMed: q(P.sty, 0.5), layMed: q(P.lay, 0.5), styP95: q(P.sty, 0.95), layP95: q(P.lay, 0.95),
    ro: window.__ro.n, roMs: Math.round(window.__ro.ms * 10) / 10, by: Object.fromEntries(Object.entries(window.__ro.by).map(([k, v]) => [k, v.n + 'x/' + Math.round(v.ms) + 'ms'])),
    clsDuring: P.cls.length > 0 && P.cls.every(Boolean), vwMin: Math.min(...P.vw), vwMax: Math.max(...P.vw), rows: document.querySelectorAll('#view .trow[data-id]').length,
    tiles: document.querySelectorAll('#view .dc-card').length, fitDrag: P.fitDrag, fitAfter: P.fitAfter, pend: P.pend || [], ms: Math.round(P.at[P.at.length - 1] - P.at[0]), cv: P.cv, st: document.getElementById('view')?.scrollTop}; })()`;

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const L = (await call(CA, 'POST', '/api/lists', {name: 'Many rows'})).id;
  const T = [];
  for (let i = 0; i < 300; i += 20) T.push(...(await Promise.all(Array.from({length: 20}, (_, j) => {
    const n = i + j, title = `Row ${n + 1} ` + Array.from({length: 3 + (n * 7) % 14}, (_, k) => WORDS[(n + k) % WORDS.length]).join(' ');
    return call(CA, 'POST', '/api/tasks', {title, list_id: L, ...(n % 5 === 0 ? {due: '2026-11-20'} : {})});
  }))).map(t => t.id));
  check(T.filter(Boolean).length === 300, 'setup: 300 tasks ' + T.filter(Boolean).length);
  let docs = 0;
  for (let b = 0; b < 6; b++) {
    const fd = new FormData(); fd.append('ws', 'private');
    for (let i = 0; i < 20; i++) fd.append('files', new Blob([`Letter ${b * 20 + i + 1}\nDate: 0${1 + i % 9}.10.2026\nAmount 12,50 EUR\n`], {type: 'text/plain'}), `letter-${b * 20 + i + 1}.txt`);
    const r = await (await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CA}, body: fd})).json().catch(() => ({}));
    docs += (r.ids || []).length;
  }
  check(docs >= 100, 'setup: documents uploaded ' + docs);

  const ready = async (ev, expr, n = 80) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const frame2 = `new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => r(1))))`;
  const out = [];
  await firefox(async o => {
    const {cmd, ev, ctx, nav, shot} = o;
    await cmd('script.addPreloadScript', {functionDeclaration: RO_WRAP});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'login');
    // one drag of grip `k` for about one second: down, 60 moves of 16 ms back and forth over `span` px, up
    // old = the drawing before 2.586 for the same drag in the same run (a fair comparison on a busy machine): the watchers
    // measure every frame (dragRest runs at once), nothing skips (content-visibility visible) and the width is set on the root
    const drag = async (k, span, tag, old = false) => {
      await ev(`(() => { if (!window.__dr0) window.__dr0 = dragRest; dragRest = ${old} ? (k, fn) => fn() : window.__dr0;
        let s = document.getElementById('dpold'); if (${old} && !s) { s = document.createElement('style'); s.id = 'dpold'; s.textContent = '.trow,.dc-card{content-visibility:visible!important}'; document.head.appendChild(s); }
        if (!${old} && s) s.remove();
        const a = document.getElementById('app').style; if (!a.__sp0) a.__sp0 = a.setProperty;
        a.setProperty = ${old} ? function (k, v) { return document.documentElement.style.setProperty(k, v); } : a.__sp0;  // before: the width on the root
        return 1; })()`);
      tag += old ? '-old' : '';
      const g = await ev(`(() => { placeGrips(); const g = document.getElementById('pgrip-${k}'); if (!g || g.hidden) return null; const r = g.getBoundingClientRect(); return {x: Math.round(r.left + r.width / 2), y: Math.round(r.top + Math.min(r.height / 2, 300))}; })()`);
      check(!!g, `${tag}: the grip ${k} is there`);
      if (!g) return null;
      await ev(PROBE);
      const sgn = k === 'side' ? 1 : -1, moves = [];
      for (let i = 1; i <= 60; i++) { const ph = Math.sin(i / 60 * Math.PI * 2); moves.push({type: 'pointerMove', x: Math.round(g.x + sgn * span * ph), y: g.y, duration: 16}); }
      await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'dp', parameters: {pointerType: 'mouse'},
        actions: [{type: 'pointerMove', x: g.x, y: g.y}, {type: 'pointerDown', button: 0}, ...moves, {type: 'pointerUp', button: 0}]}]});
      await cmd('input.releaseActions', {context: ctx});
      await ev(frame2);
      const r = await ev(RESULT);
      r.skipAfter = await ev(`[...document.querySelectorAll('#view .trow, #view .dc-card')].filter(x => getComputedStyle(x).contentVisibility === 'auto').length`).catch(() => -1);
      r.after = await ev(`document.body.classList.contains('pgdrag') || document.body.classList.contains('kdrag')`);
      console.log(`DRAGPERF ${tag}: ` + JSON.stringify(r));
      out.push([tag, r]);
      return r;
    };
    for (const W of [2560, 1280]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: W, height: W > 2000 ? 1440 : 800}});
      // ---- the list with 300 rows, the task panel open, its grip
      await nav(B + `#l/${L}`);
      check(await ready(ev, `document.querySelectorAll('#view .trow[data-id]').length >= 100`), `${W}: the list shows its rows`);
      await ev(`(() => { openDetail(${T[0]}); return 1; })()`);
      check(await ready(ev, `!!document.querySelector('#detail:not(.hidden) .dtop')`), `${W}: the task panel is open`);
      await ev(`(() => { const v = document.getElementById('view'); v.scrollTop = Math.round(v.scrollHeight / 3); return 1; })()`);  // rows out of view above and below
      await sleep(300);
      for (const old of [true, false, true]) await drag('det', W > 2000 ? 400 : 120, `list300-det-${W}`, old);
      const r1 = await drag('det', W > 2000 ? 400 : 120, `list300-det-${W}`);
      if (r1) {
        check(r1.steps >= 20, `${W} list: the width follows the pointer in many steps (${r1.steps})`);
        check(r1.vwMax - r1.vwMin >= 40, `${W} list: the content reflows live during the drag (#view ${r1.vwMin}-${r1.vwMax} px)`);
        check(r1.clsDuring, `${W} list: the body carries the drag class during every step`);
        check(!r1.after, `${W} list: the drag class is gone after release`);
        check(r1.cv > 50 && r1.skipAfter === 0, `${W} list: rows may skip their drawing during the drag (${r1.cv} rows), none after release (${r1.skipAfter})`);
        // 2.586.0 A (#4860): the bar / mode fitting rests during the drag (at most every 200 ms) and runs once after release
        // 2.832.0 (#5516, CI red of 2.819.0): each watcher on its own rests (fewer runs than steps, at most one per 200 ms). The sum
        // of the three against the steps was no measure of the rest: on the slower CI runner the drag took 5.5 s, each watcher ran
        // 20 times (limit 29) and the three together reached the 60 steps although the 200 ms held for every one of them
        const fv = Object.values(r1.fitDrag), fmax = Math.max(0, ...fv);
        check(fv.every(v => v <= Math.ceil(r1.ms / 200) + 1) && fmax < r1.steps, `${W} list: the bar watchers rest during the drag (at most ${fmax} fits of one watcher for ${r1.steps} steps in ${r1.ms} ms, each at most every 200 ms) ` + JSON.stringify(r1.fitDrag));
        // 2.1102.0 (#5516, CI red of 2.1077.0): only when a watcher still waited at release - the release runs only what waits
        // (dragRestFlush); when the last 200 ms run came just before it nothing waits and the sine ends at the start width, so
        // no fit is due. 'lsd' fits always, 'top' / 'dtop' only on a changed width. The result check below (the bars fit) stays
        if (r1.pend.includes('lsd')) check((r1.fitAfter.lsd_sync || 0) >= 1, `${W} list: the bars are fitted after release (a watcher waited: ${r1.pend}) ` + JSON.stringify(r1.fitAfter));
      }
      // after release: the bars fit the final width (the watchers ran once more)
      check(await ready(ev, `(() => { const t = document.getElementById('top'), d = document.querySelector('#detail .dtop'); return !!t && t.scrollWidth <= t.clientWidth + 1 && (!d || d.scrollWidth <= d.clientWidth + 1); })()`, 20), `${W} list: the head bar and the panel's bar fit after release`);
      check(await ev(`(() => { const v = document.getElementById('view'), rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16; return v.classList.contains('lsdw') === (v.clientWidth >= 100 * rem - 0.5); })()`), `${W} list: the list/detail pair matches the final width after release`);
      await shot(`p2586a-list-${W}.png`);
      // the inline title field: after a drag its height still fits its text
      await ev(`(() => { closeDetail?.(); return 1; })()`).catch(() => 0);
      await sleep(200);
      const ie = await ev(`(async () => { const row = document.querySelector('#view .trow[data-id="${T[3]}"]'); if (!row || typeof inlineEditStart !== 'function') return 'none'; inlineEditStart(${T[3]}); await ${frame2}; return !!document.querySelector('.ttlin'); })()`).catch(e => 'err ' + e.message);
      if (ie === true) {
        // the sidebar's grip narrows the list under the open field (a press on a grip keeps the focus: no commit)
        await drag('side', W > 2000 ? 200 : 80, `list300-side-edit-${W}`);
        const fitH = await ev(`(() => { const i = document.querySelector('.ttlin'); if (!i) return null; const h = i.offsetHeight; i.style.height = 'auto'; const s = i.scrollHeight; i.style.height = h + 'px'; return {h, s}; })()`);
        console.log(`${W}: title field after the drag ` + JSON.stringify(fitH));
        check(!fitH || Math.abs(fitH.h - fitH.s) <= 2, `${W}: the title field fits its text after the drag ` + JSON.stringify(fitH));
        await ev(`(() => { inlineEditCancel(); return 1; })()`).catch(() => 0);
      } else console.log(`${W}: inline edit not reachable here (${ie}), the title-field check is left out`);
      // ---- the documents with many tiles, the sidebar's grip
      await nav(B + '#docs');
      check(await ready(ev, `document.querySelectorAll('#view .dc-card').length >= 40`), `${W}: the documents show their tiles ` + await ev(`document.querySelectorAll('#view .dc-card').length`));
      await sleep(300);
      for (const old of [true, false, true]) await drag('side', W > 2000 ? 200 : 80, `docs-side-${W}`, old);
      const r2 = await drag('side', W > 2000 ? 200 : 80, `docs-side-${W}`);
      if (r2) {
        check(r2.vwMax - r2.vwMin >= 40, `${W} docs: the tiles reflow live during the drag (#view ${r2.vwMin}-${r2.vwMax} px)`);
        check(!r2.after, `${W} docs: the drag class is gone after release`);
        check(r2.cv > 20 && r2.skipAfter === 0, `${W} docs: tiles may skip their drawing during the drag (${r2.cv} tiles), none after release (${r2.skipAfter})`);
      }
      await shot(`p2586a-docs-${W}.png`);
    }
  });
  console.log('DRAGPERF summary: ' + out.map(([t, r]) => `${t} frame med ${r.med} / p95 ${r.p95} ms, step med ${r.stepMed} / p95 ${r.stepP95} ms, RO ${r.ro}x ${r.roMs} ms, fits ${JSON.stringify(r.fitDrag)}`).join(' | '));
  if (process.env.P2586A_SHOTS) require('fs').writeFileSync(path.join(process.env.P2586A_SHOTS, 'p2586a-dragperf.json'), JSON.stringify(out, null, 1));  // the numbers next to the pictures (kalmido-mactest.sh shot)
  console.log(`p2586_a_dragperf_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
