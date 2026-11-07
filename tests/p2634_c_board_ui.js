// 2.634.0 (#4797) UI: on the board the other cards make room for the dragged one (computer / tablet, mouse).
// kalmido-suite: fresh
// dnd.js kph_* + app.css block "2.634.0 (#4797)": while a card is dragged (HTML5 drag events with a real DataTransfer, laid
// out for real at 1280 px) a placeholder (.kph) stands where it will land, no insert line; the neighbour that makes room slides
// with a transform (FLIP, class kflip, 0.18 s) and is still again afterwards; the spot is measured against the resting places,
// so a small mouse move around a boundary keeps it (no switch before / after); the drop lands at the placeholder (order from
// the server after a reload), an empty column takes the card too; the spot right next to the dragged card shows nothing.
// Reduced motion: the placeholder alone, no transition, no transform. Waits for states, never a fixed time.
// alice (organisation) and frida (no organisation) run every check.
// freelancer-matrix: tasks (frida without an organisation drags on her own board)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const ffmod = require('./ff');
const moving = ffmod({tag: 'p2634_c_board_ui', check, shots: 'P2634C_SHOTS', prefs: [['ui.prefersReducedMotion', 0]]});
const still = ffmod({tag: 'p2634_c_still_ui', check, shots: 'P2634C_SHOTS'});  // the ff.js default: reduced motion
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2634C_NOSTART !== '1' && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };

// (ff.js hands a page null back as undefined: compare with == null)
// in the page: the drag helpers (one DataTransfer per drag, events at a given clientY over an element)
const HELP = `(() => { window.__kd = {
  f(type, el, y) { const b = el.getBoundingClientRect(); const e = new DragEvent(type, {bubbles: true, cancelable: true, dataTransfer: this.dt, clientX: b.left + 20, clientY: y == null ? b.top + 5 : y}); el.dispatchEvent(e); return e; },
  col: sid => document.querySelector('#view .kanban .kcol[data-kcol="' + sid + '"]'),
  ids: sid => [...document.querySelectorAll('#view .kanban .kcol[data-kcol="' + sid + '"] .kcards > .trow[data-id]')].map(r => +r.dataset.id),
  spot() { const p = document.querySelector('#view .kcards > .kph'); if (!p) return null; const n = p.nextElementSibling, q = p.previousElementSibling;
    return {col: p.closest('.kcol').dataset.kcol, next: n && n.dataset.id ? +n.dataset.id : null, prev: q && q.dataset.id ? +q.dataset.id : null, h: Math.round(p.getBoundingClientRect().height)}; },
  start(id) { this.dt = new DataTransfer(); this.f('dragstart', document.querySelector('#view .trow[data-id="' + id + '"]')); },
  // the resting middle of a card (before the drag moved anything), relative to the viewport
  mid: id => { const b = document.querySelector('#view .trow[data-id="' + id + '"]').getBoundingClientRect(); return b.top + b.height / 2; },
}; return 1; })()`;
const GONE = cond => `new Promise(res => { const t0 = performance.now(); const f = () => { let c = false; try { c = (${cond})(); } catch { /* not yet */ }
  if (c) res(Math.round(performance.now() - t0)); else if (performance.now() - t0 > 2000) res(-1); else setTimeout(f, 5); }; f(); })`;

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {org_name: 'Nordwind', lang: 'en', modules: ['comments', 'kanban']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const fr = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com'});
  check(fr.http < 300, 'setup: frida (no organisation) ' + fr.http);
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const CK = {alice: CA, frida: CF};
  // one board per user and run (moving / still): the column "Tasks" with four cards, an empty column "Doing"
  const board = async (who, run) => {
    const ck = CK[who], L = (await call(ck, 'POST', '/api/lists', {name: `Board ${who} ${run}`})).id;
    const S1 = (await call(ck, 'POST', '/api/sections', {list_id: L, name: 'Doing'})).id;
    const T = [];
    for (const n of ['One', 'Two', 'Three', 'Four']) T.push((await call(ck, 'POST', '/api/tasks', {title: n, list_id: L})).id);
    const v = await call(ck, 'PATCH', `/api/lists/${L}`, {view: 'kanban'});
    check(L && S1 && T.every(Boolean) && v.http < 300, `${who} ${run}: board, column and four cards ${v.http}`);
    return {L, S1, T};
  };
  const open = async (o, who, b) => {
    const {cmd, ev, ctx, nav, until, idle} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 860}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${who}', password: 'password123'})}).then(r => r.status)`);
    await nav(B);
    await until(`typeof kph_over === 'function' && S.booted && !!keyToHash`, {timeout: 30000});
    // the board module (alice from the setup; frida, created later, switches it on herself if her defaults lack it)
    await ev(`(async () => { if (!feat('kanban')) { await api('PATCH', '/api/settings', {features: [...(S.settings.features || '').split(',').filter(Boolean), 'kanban'].join(',')}); await load(); } return feat('kanban'); })()`);
    check(await ev(`feat('kanban')`), `${who}: the board module is on`);
    await ev(`(() => { location.hash = keyToHash('l:${b.L}'); return 1; })()`);
    await until(`S.route.key === 'l:${b.L}'`, {timeout: 10000});
    await ev(`setListView(listById(${b.L}), 'kanban').then(() => 1)`);  // the board, not the project's overview page
    const shown = await until(`document.querySelectorAll('#view .kanban .kcol[data-kcol=""] .kcards > .trow[data-id]').length === 4 && !!document.querySelector('#view .kanban .kcol[data-kcol="${b.S1}"]')`, {timeout: 20000});
    check(!!shown, `${who}: the board shows four cards and the empty column ` + (shown ? '' : await ev(`JSON.stringify({key: S.route.key, view: (listById(${b.L}) || {}).view, kanban: isKanban(), cols: [...document.querySelectorAll('#view .kcol')].map(c => c.dataset.kcol + ':' + c.querySelectorAll('.trow').length), rows: document.querySelectorAll('#view .trow').length})`)));
    await idle();
    await ev(HELP);
  };
  // drag card id; returns once the drag is under way (tdrag + the card marked)
  const lift = async (o, id) => { await o.ev(`(() => { __kd.start(${id}); return 1; })()`); return o.until(`document.body.classList.contains('tdrag') && !!document.querySelector('#view .trow.dragging[data-id="${id}"]')`, {timeout: 3000}); };
  const drop = (o, sel) => o.ev(`(() => { const t = ${sel}; __kd.f('drop', t); const r = document.querySelector('#view .trow.dragging') || document.body; __kd.f('dragend', r); return 1; })()`);
  const reloaded = (o, sid) => o.ev(`load().then(() => { render(); return __kd.ids('${sid}').join(); })`);

  const run = async (o, who, motion) => {
    const {ev, until, idle} = o, tag = `${who} 1280px ${motion ? 'moving' : 'reduced motion'}`;
    const b = await board(who, motion ? 'moving' : 'still'), [A, Bx, C, D] = b.T;
    await open(o, who, b);
    const order0 = await ev(`__kd.ids('').join()`);
    const [r0, r1, r2, r3] = order0.split(',').map(Number);
    check(new Set([r0, r1, r2, r3]).size === 4 && [A, Bx, C, D].every(x => [r0, r1, r2, r3].includes(x)), `${tag}: the four cards in the first column (${order0})`);
    check(await ev(`an_desk()`) === motion, `${tag}: motion is ${motion ? 'on' : 'off'}`);

    // 1) lift the first card, hover just above the middle of the fourth: the placeholder stands before it
    check(!!await lift(o, r0), `${tag}: the drag is under way`);
    const mid3 = await ev(`__kd.mid(${r3})`), h0 = await ev(`Math.round(document.querySelector('#view .trow[data-id="${r0}"]').getBoundingClientRect().height)`);
    const p1 = await ev(`(() => { const kc = __kd.col('').querySelector('.kcards'), e = __kd.f('dragover', kc, ${mid3} - 3), n = document.querySelector('#view .trow[data-id="${r3}"]'), cs = getComputedStyle(n);
      return {taken: e.defaultPrevented, spot: __kd.spot(), lines: document.querySelectorAll('#view .dropbefore, #view .dropafter').length, drop: __kd.col('').classList.contains('drop'),
        flip: n.classList.contains('kflip'), tf: cs.transform, dur: cs.transitionDuration, anims: n.getAnimations().length, inline: n.style.transform}; })()`);
    check(p1.taken && p1.spot && p1.spot.next === r3 && p1.spot.prev === r2 && p1.spot.col === '', `${tag}: a placeholder stands before the fourth card ${JSON.stringify(p1)}`);
    check(p1.spot && Math.abs(p1.spot.h - h0) <= 2, `${tag}: the placeholder is as high as the dragged card (${p1.spot && p1.spot.h} / ${h0})`);
    check(p1.lines === 0 && p1.drop, `${tag}: no insert line, the column is marked ${JSON.stringify(p1)}`);
    if (motion) {
      check(p1.flip && p1.dur === '0.18s' && (p1.tf !== 'none' || p1.anims > 0), `${tag}: the neighbour slides aside with a transform ${JSON.stringify(p1)}`);
      const tF = await ev(GONE(`() => { const n = document.querySelector('#view .trow[data-id="${r3}"]'); return !n.classList.contains('kflip') && getComputedStyle(n).transform === 'none'; }`));
      check(tF >= 0 && tF <= 400, `${tag}: the neighbour is still again after at most 400 ms (${tF} ms)`);
    } else check(!p1.flip && parseFloat(p1.dur) < 0.001 && p1.tf === 'none' && !p1.inline,  // (the central reduced-motion rule leaves 0.00001s)
      `${tag}: no transition, no transform ${JSON.stringify(p1)}`);

    // 2) small moves around the boundary (the fourth card's resting middle) keep the spot; the card under the mouse moved
    const wob = await ev(`(() => { const kc = __kd.col('').querySelector('.kcards'), out = [];
      for (const d of [3, -2, 4, -3, 5, -1, 2]) { __kd.f('dragover', kc, ${mid3} + d); const s = __kd.spot(); out.push(s ? s.next : 'none'); }
      return out; })()`);
    check(wob.every(x => x === r3), `${tag}: a small mouse move keeps the spot before the fourth card ${JSON.stringify(wob)}`);
    // a clear move past the boundary goes to after it (the end of the column)
    const past = await ev(`(() => { const kc = __kd.col('').querySelector('.kcards'); __kd.f('dragover', kc, ${mid3} + 20); return __kd.spot(); })()`);
    check(past && past.next == null && past.prev === r3, `${tag}: past the boundary the spot is after the fourth card ${JSON.stringify(past)}`);
    const back = await ev(`(() => { __kd.f('dragover', __kd.col('').querySelector('.kcards'), ${mid3} - 12); return __kd.spot(); })()`);
    check(back && back.next === r3, `${tag}: back before the fourth card ${JSON.stringify(back)}`);

    // 3) the drop lands at the placeholder: 2, 3, 1, 4 (from the server after a reload)
    await drop(o, `document.querySelector('#view .kcards > .kph')`);
    const exp = [r1, r2, r0, r3].join();
    check(!!await until(`__kd.ids('').join() === '${exp}'`, {timeout: 8000}), `${tag}: the card lands where the placeholder stood (${await ev(`__kd.ids('').join()`)} / ${exp})`);
    await idle();
    check(await reloaded(o, '') === exp, `${tag}: the order is stored`);
    check(await ev(`!document.querySelector('#view .kph, #view .kcards > .trow.kflip, #view .dropbefore, #view .dropafter') && ![...document.querySelectorAll('#view .kcards > .trow')].some(r => r.style.transform)`), `${tag}: nothing of the drag is left`);

    // 4) right next to the dragged card nothing changes: no placeholder
    await ev(HELP);
    check(!!await lift(o, r2), `${tag}: second drag under way`);
    const self = await ev(`(() => { const kc = __kd.col('').querySelector('.kcards'), out = [];
      for (const id of [${r2}, ${r0}]) { const b = document.querySelector('#view .trow[data-id="' + id + '"]').getBoundingClientRect(); __kd.f('dragover', kc, b.top + (id === ${r2} ? 3 : b.height / 2 - 3)); out.push(__kd.spot()); }
      return out; })()`);
    check(self[0] == null && self[1] == null, `${tag}: on the dragged card and just before the next one no placeholder ${JSON.stringify(self)}`);
    // 5) into the empty column: the placeholder alone there, the first column back without one; the drop moves the card
    const into = await ev(`(() => { const c = __kd.col('${b.S1}'); __kd.f('dragover', c.querySelector('.kcards')); return {spot: __kd.spot(), n: document.querySelectorAll('#view .kph').length}; })()`);
    check(into.spot && into.spot.col === String(b.S1) && into.n === 1 && into.spot.next == null && into.spot.prev == null, `${tag}: the empty column shows the placeholder ${JSON.stringify(into)}`);
    await drop(o, `document.querySelector('#view .kcards > .kph')`);
    check(!!await until(`__kd.ids('${b.S1}').join() === '${r2}'`, {timeout: 8000}), `${tag}: the card moved into the empty column`);
    await idle();
    check(await reloaded(o, b.S1) === String(r2) && (await call(CK[who], 'GET', `/api/tasks/${r2}`)).section_id === b.S1, `${tag}: stored in the column`);
    // 6) Esc / a drag ended elsewhere: the placeholder goes
    await ev(HELP);
    await lift(o, r1);
    await ev(`(() => { __kd.f('dragover', __kd.col('').querySelector('.kcards'), __kd.mid(${r3}) - 3); return 1; })()`);
    const had = await ev(`!!__kd.spot()`);
    await ev(`(() => { __kd.f('dragend', document.querySelector('#view .trow[data-id="${r1}"]')); return 1; })()`);
    check(had && await ev(`!document.querySelector('#view .kph')`) && await ev(`__kd.ids('').join()`) === [r1, r0, r3].join(), `${tag}: a drag without a drop leaves no placeholder and the order as it was`);
  };

  for (const who of ['alice', 'frida']) await moving(o => run(o, who, true), false);
  for (const who of ['alice', 'frida']) await still(o => run(o, who, false), false);

  console.log(`p2634_c_board_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error('Error', e); process.exit(1); });
