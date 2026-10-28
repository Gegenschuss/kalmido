// kalmido-suite: fresh
// 2.331.0 B (#3304) measurement, own container (start.sh), Firefox on a desktop (1440 x 900, mouse): a list in the table layout
// with 300 tasks and four columns (due, priority, a text field, a choice field). Prints (lines "PERF ..."):
// - dragging a column width (about 60 pointer steps there and back), moving a column (about 60 steps, then the drop),
//   typing into a text cell + Enter (the save and the redraws)
// - per action: frames per second (a requestAnimationFrame counter in the page), long frames (> 50 ms between two frames),
//   the median / largest frame gap, the work per frame (from the frame's start until its rendering is done: a message posted
//   from the first frame callback arrives after style, layout and paint) and the time in the pointer handlers per step
// Only the setup and that the actions worked are checked; the numbers depend on the machine.
// freelancer-matrix: lists (no route touched; the person has no organisation)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2331_b_lcperf', check, shots: 'P2331B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const N = 300, STEPS = 60;

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', modules: ['fields']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'fields'});
  const L = (await call(CA, 'POST', '/api/lists', {name: 'Inventory'})).id;
  const FT = (await call(CA, 'POST', `/api/lists/${L}/fields`, {name: 'Package', type: 'text'})).id;
  const FS = await call(CA, 'POST', `/api/lists/${L}/fields`, {name: 'State', type: 'select', options: {options: [{name: 'Open', color: '#e5484d'}, {name: 'Doing', color: '#3e63dd'}, {name: 'Done', color: '#30a46c'}]}});
  const OPTS = (FS.options?.options || []).map(o => o.id);
  check(FT && FS.id && OPTS.length === 3, 'two fields (setup)');
  await call(CA, 'PATCH', `/api/lists/${L}`, {columns: ['due', 'prio', `f:${FT}`, `f:${FS.id}`]});
  const ids = [];
  for (let i = 0; i < N; i++) {
    const t = await call(CA, 'POST', '/api/tasks', {title: `Item ${i + 1}`, list_id: L, priority: [0, 1, 5, 3][i % 4], due: i % 3 ? `2026-11-${String(1 + i % 28).padStart(2, '0')}` : null,
      fields: {[FT]: `pkg-${i % 17}`, [FS.id]: OPTS[i % 3]}});
    ids[i] = t.id;
  }
  check(ids.filter(Boolean).length === N, `${N} tasks (setup)`);

  await firefox(async o => {
    const {cmd, ev, ctx, nav, shot} = o;
    const ready = async (expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
    const act = actions => cmd('input.performActions', {context: ctx, actions}).then(() => cmd('input.releaseActions', {context: ctx}));
    const mid = sel => ev(`(() => { const e = document.querySelector('${sel}'); if (!e) return null; const b = e.getBoundingClientRect(); return {x: b.left + b.width / 2, y: b.top + b.height / 2, w: b.width, l: b.left}; })()`);
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await nav(B + '#l/' + L);
    check(await ready(`typeof tcEdit === 'function' && !!document.querySelector('#view .lchead') && document.querySelectorAll('#view .trow').length >= ${N}`), 'Firefox: the list with columns and all rows');
    await sleep(800);
    // the meter: frame gaps, work per frame, time in the pointer handlers (window capture -> document bubble), render() calls
    await ev(`(() => {
      const M = window.__m = {on: false, d: [], w: [], h: [], r: 0, rt: 0};
      const f = window.render; window.render = function (...a) { const s = performance.now(); try { return f.apply(this, a); } finally { if (M.on) { M.r++; M.rt += performance.now() - s; } } };
      let hs = 0;
      window.addEventListener('pointermove', () => { hs = performance.now(); }, true);
      document.addEventListener('pointermove', () => { if (M.on && hs) M.h.push(performance.now() - hs); hs = 0; });
      const ch = new MessageChannel(); let f0 = 0;
      ch.port1.onmessage = () => { if (M.on && f0) M.w.push(performance.now() - f0); f0 = 0; };
      let last = 0;
      const loop = () => { if (!M.on) return; const n = performance.now(); if (last) M.d.push(n - last); last = n; f0 = n; ch.port2.postMessage(0); requestAnimationFrame(loop); };
      M.start = () => { Object.assign(M, {on: true, d: [], w: [], h: [], r: 0, rt: 0, t0: performance.now()}); last = 0; requestAnimationFrame(loop); return 1; };
      M.stop = () => { M.on = false; return {d: M.d, w: M.w, h: M.h, r: M.r, rt: M.rt, ms: performance.now() - M.t0}; };
      return 1; })()`);
    const q = (a, p) => { if (!a.length) return 0; const s = [...a].sort((x, y) => x - y); return s[Math.min(s.length - 1, Math.floor(s.length * p))]; };
    const report = (name, m) => {
      const fps = m.d.length ? 1000 / (m.d.reduce((x, y) => x + y, 0) / m.d.length) : 0;
      console.log(`PERF ${name}: ${fps.toFixed(1)} frames/s over ${(m.ms / 1000).toFixed(2)} s (${m.d.length} frames), long frames > 50 ms: ${m.d.filter(x => x > 50).length},` +
        ` frame gap median ${q(m.d, .5).toFixed(1)} ms / max ${q(m.d, 1).toFixed(1)} ms, work per frame median ${q(m.w, .5).toFixed(1)} ms / p95 ${q(m.w, .95).toFixed(1)} ms / max ${q(m.w, 1).toFixed(1)} ms,` +
        ` pointer handler per step median ${q(m.h, .5).toFixed(2)} ms / max ${q(m.h, 1).toFixed(2)} ms (${m.h.length} steps), render() ${m.r}x ${m.rt.toFixed(1)} ms`);
      return m;
    };
    // steps of 16 ms (one frame each) between the points xs, pointer down at the first one, up at the last one
    const steps = (x0, y0, xs) => [{type: 'pointerMove', x: Math.round(x0), y: Math.round(y0)}, {type: 'pointerDown', button: 0},
      ...xs.map(x => ({type: 'pointerMove', x: Math.round(x), y: Math.round(y0), duration: 16})), {type: 'pointerUp', button: 0}];
    const full = await ev(`(() => { const a = []; for (let i = 0; i < 5; i++) { const s = performance.now(); render(); document.body.offsetHeight; a.push(performance.now() - s); } return a.sort((x, y) => x - y)[2]; })()`);
    console.log(`PERF one render() + layout, ${N} rows, 4 columns: median ${full.toFixed(1)} ms`);

    // 1) the width of the text column: 30 steps of 4 px to the left (wider), 30 back
    for (let run = 1; run <= 2; run++) {
      const g = await mid(`.lchead .lcg[data-lcg="f:${FT}"]`), c0 = await mid(`.lchead .lc[data-k="f:${FT}"]`);
      check(!!g, 'the width grip is there');
      if (!g) break;
      const xs = []; for (let i = 1; i <= STEPS / 2; i++) xs.push(g.x - 4 * i); for (let i = STEPS / 2 - 1; i >= 0; i--) xs.push(g.x - 4 * i - 40);
      await ev('__m.start()');
      await act([{type: 'pointer', id: 'p1', parameters: {pointerType: 'mouse'}, actions: steps(g.x, g.y, xs)}]);
      await sleep(300);
      report(`width drag run ${run} (${STEPS} steps)`, await ev('__m.stop()'));
      const c1 = await mid(`.lchead .lc[data-k="f:${FT}"]`), w = await ev(`(JSON.parse(localStorage.getItem('tasks.lcw.${L}') || '{}'))['f:${FT}'] || 0`);
      check(c1 && Math.abs(c1.w - (c0.w + 40)) <= 3 && w > 0, `the width drag worked (${c0.w} -> ${c1 && c1.w} px, stored ${w} rem)`);
      await ev(`(() => { lcwSet(${L}, 'f:${FT}', null); return 1; })()`); await sleep(300);
    }
    await shot('p2331b-lcperf.png');
    // the release: the rows take the new width (the style sheet as lcwSet writes it) + layout, median of 7
    const rel = await ev(`(() => { const a = []; for (let i = 0; i < 7; i++) { const s = performance.now(); lcwApply(${L}, {'f:${FT}': 8 + i % 2}); document.body.offsetHeight; a.push(performance.now() - s); }
      lcwApply(${L}); document.body.offsetHeight; return a.sort((x, y) => x - y)[3]; })()`);
    console.log(`PERF release: the rows take the width + layout, ${N} rows: median ${rel.toFixed(1)} ms`);

    // the start + end of a drag (what the grip / the column title put on the page and take off again), median of 7
    const tm = code => ev(`(() => { const a = []; for (let i = 0; i < 7; i++) { document.body.offsetHeight; const s = performance.now(); ${code}; document.body.offsetHeight; a.push(performance.now() - s); } return a.sort((x, y) => x - y)[3]; })()`);
    const cov = c => `const d = document.body.appendChild(Object.assign(document.createElement('div'), {className: '${c}'}))`;
    console.log(`PERF start + end of a width drag (body.pgdrag + cover): ${(await tm(`document.body.classList.add('pgdrag', 'lcwdrag'); ${cov('lccover')}; document.body.offsetHeight; document.body.classList.remove('pgdrag', 'lcwdrag'); d.remove()`)).toFixed(1)} ms`);
    console.log(`PERF start + end of a column move (body.lcmoving + cover): ${(await tm(`document.body.classList.add('lcmoving'); ${cov('lccover mv')}; document.body.offsetHeight; document.body.classList.remove('lcmoving'); d.remove()`)).toFixed(1)} ms`);

    // 2) move the choice column in front of the due date: 60 steps to the left, then the drop (saved, redrawn)
    const hs = await mid(`.lchead .lc[data-k="f:${FS.id}"] .lcs`), hd = await mid(`.lchead .lc[data-k="due"]`);
    const to = hd.l + 4, xs = []; for (let i = 1; i <= STEPS; i++) xs.push(hs.x + (to - hs.x) * i / STEPS);
    await ev('__m.start()');
    await act([{type: 'pointer', id: 'p1', parameters: {pointerType: 'mouse'}, actions: steps(hs.x, hs.y, xs)}]);
    check(await ready(`(() => { const k = [...document.querySelectorAll('#view .lchead .lc[data-k]')].map(c => c.dataset.k); return k.indexOf('f:${FS.id}') >= 0 && k.indexOf('f:${FS.id}') < k.indexOf('due'); })()`), 'the column moved in front of the due date');
    await sleep(500);
    report(`column move (${STEPS} steps + drop)`, await ev('__m.stop()'));

    // 3) type into a text cell and press Enter (the optimistic redraw and the server's answer)
    for (let run = 1; run <= 2; run++) {
      const tid = ids[10 + run], val = `typed-${run}`;
      await ev(`(() => { document.querySelector('#tc-${tid} .lc[data-k="f:${FT}"]').scrollIntoView({block: 'center'}); return 1; })()`); await sleep(300);
      await ev(`(() => { tcEdit(document.querySelector('#tc-${tid} .lc[data-k="f:${FT}"]')); return 1; })()`);
      check(await ready(`!!document.querySelector('#tc-${tid} .tcin')`), 'the cell editor opened');
      await ev('__m.start()');
      await act([{type: 'key', id: 'k', actions: [...[...val].flatMap(c => [{type: 'keyDown', value: c}, {type: 'keyUp', value: c}]), {type: 'keyDown', value: ''}, {type: 'keyUp', value: ''}]}]);
      check(await ready(`!document.querySelector('#tc-${tid} .tcin') && /${val}/.test(document.querySelector('#tc-${tid} .lc[data-k="f:${FT}"]')?.textContent || '')`), `the typed value is shown (${run})`);
      check(await ready('__m.r >= 2'), `the save and the server's answer redrew the list (${run})`);  // the redraw at once + the one with the answer
      check((await call(CA, 'GET', '/api/state')).tasks.find(t => t.id === tid)?.fields?.[FT] === val, `the value is saved (${run})`);
      await sleep(600);
      report(`type ${val.length} keys + Enter run ${run}`, await ev('__m.stop()'));
    }
  }, false);

  console.log(`p2331_b_lcperf: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
