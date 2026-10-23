// 2.193.0 part C UI tests (#2219), own container (start.sh), Firefox on a phone (390 x 844, touch, the real layout).
// Task rows drag on drag.js (dnd.js): the long press = drag.js hold.
// - held: the row lifts at once (ghost, "Move to project"), the next touchmove is the drag's (prevented) even below the
//   threshold; let go without moving = the selection starts, no ghost, no drag
// - a move during the hold is no drag (a swipe / a scroll): no ghost, the row slides (swipe) and snaps back
// - held and moved down past two rows = the task sorts there (server), the click after the drop is swallowed
// - Esc after the hold cancels (no ghost, nothing moved)
// - a re-render in the middle of the drag: the drag goes on and ends cleanly (drag.js onTarget)
// - the list scrolled to its end, let go in the bottom auto-scroll strip (below the last row) = after the last open row
// - sections: the list scrolled to its end, a section let go in the bottom auto-scroll strip lands at the end (iOS: it
//   jumped back, the drop below the folded sections found no place)
// Screenshots with P2193C_SHOTS=<dir>.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2193_c_ui', check, shots: 'P2193C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return Array.isArray(j) ? j : {...j, status: r.status}; };

// in the page: one finger as synthetic touch events on the element it started on (drag.js follows it there)
const TOUCH = `window.__sl = ms => new Promise(r => setTimeout(r, ms));
window.__tev = (type, el, x, y) => { const t = new Touch({identifier: 1, target: el, clientX: x, clientY: y}); const e = new TouchEvent(type, {bubbles: true, cancelable: true, touches: type === 'touchend' ? [] : [t], targetTouches: type === 'touchend' ? [] : [t], changedTouches: [t]}); el.dispatchEvent(e); return e; };
window.__row = id => document.querySelector('#view .trow[data-id="' + id + '"] .ttl');
window.__at = el => { const r = el.getBoundingClientRect(); return {x: r.left + 20, y: r.top + r.height / 2}; };
window.__ids = () => [...document.querySelectorAll('#view .trow[data-id]:not(.done)')].map(r => +r.dataset.id);
window.__ghosts = () => document.querySelectorAll('.ghost-drag').length + (document.body.classList.contains('tdrag') ? 10 : 0);
window.__strip = () => tdBox(tdScroller(document.querySelector('#view')), {}).bottom - 20;
window.__secs = lid => secIds(lid).map(i => S.sections.find(s => s.id === i).name).join(',');
1`;

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const L = (await call('POST', '/api/lists', {name: 'Long'})).id, L2 = (await call('POST', '/api/lists', {name: 'Elsewhere'})).id;
  check(L > 0 && L2 > 0, 'setup: two lists');
  const T = [];
  for (let i = 0; i < 26; i++) T.push((await call('POST', '/api/tasks', {title: 'Row ' + String(i).padStart(2, '0'), list_id: L})).id);
  // sections: enough that the list scrolls on a phone, two tasks each
  const SL = (await call('POST', '/api/lists', {name: 'Many sections'})).id, SN = [];
  for (let i = 0; i < 9; i++) {
    const n = 'Sec ' + i, s = await call('POST', '/api/sections', {list_id: SL, name: n}); SN.push(n);
    for (let k = 0; k < 2; k++) await call('POST', '/api/tasks', {title: `${n} task ${k}`, list_id: SL, section_id: s.id});
  }
  const sortOf = async () => { const st = await call('GET', '/api/state'); return new Map(st.tasks.filter(t => t.list_id === L && t.status === 0).map(t => [t.id, t.sort])); };

  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, sel, n = 40) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('${sel}')`).catch(() => false)); i++) await sleep(250); await sleep(700); };

  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '390';
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    check(await ffLogin(o) === 200, tag + ': login');
    await o.nav(B + '#l/' + L); await ready(ev, '#view .trow[data-id]');
    await ev(TOUCH);

    // 1) held without moving: lifted at once, the next move is the drag's; let go = the selection starts
    const a = await ev(`(async () => { const id = ${T[1]}, el = __row(id), p = __at(el), out = {};
      __tev('touchstart', el, p.x, p.y); await __sl(200); out.early = __ghosts();
      await __sl(350); out.ghost = __ghosts(); out.move = !!document.querySelector('#tdmove');
      out.prev = __tev('touchmove', el, p.x, p.y + 2).defaultPrevented;
      __tev('touchend', el, p.x, p.y + 2); await __sl(300);
      out.after = __ghosts(); out.multi = !!S.multiMode && S.multi.has(id);
      S.multiMode = false; S.multi.clear(); render(); await __sl(300);
      return out; })()`);
    check(a.early === 0 && a.ghost >= 11 && a.move, `${tag}: no ghost during the hold, after it the row lifts (ghost, "Move to project") ` + JSON.stringify(a));
    check(a.prev, `${tag}: after the hold a touchmove below the threshold is the drag's (the page does not scroll) ` + JSON.stringify(a));
    check(a.after === 0 && a.multi, `${tag}: held and let go without moving = the task is selected, no ghost left ` + JSON.stringify(a));

    // 2) a move during the hold: a swipe, no drag
    const b = await ev(`(async () => { const id = ${T[2]}, el = __row(id), p = __at(el), out = {}, row = el.closest('.trow');
      __tev('touchstart', el, p.x, p.y); await __sl(60);
      for (let i = 1; i <= 4; i++) { __tev('touchmove', el, p.x + 15 * i, p.y); await __sl(30); }
      out.sw = row.style.transform; await __sl(500); out.ghost = __ghosts();
      __tev('touchend', el, p.x + 60, p.y); await __sl(300); out.back = row.style.transform; out.ghost2 = __ghosts();
      return out; })()`);
    check(/translateX/.test(b.sw) && b.ghost === 0 && b.ghost2 === 0 && !b.back, `${tag}: a sideways move during the hold is a swipe (the row slides and snaps back), never a drag ` + JSON.stringify(b));
    check((await call('GET', '/api/state')).tasks.find(t => t.id === T[2]).status === 0, `${tag}: and the short swipe does not complete the task`);

    // 3) held and moved down past two rows: it sorts there; the click after the drop is swallowed
    const c = await ev(`(async () => { const ids = __ids(), id = ids[0], el = __row(id), p = __at(el), out = {id};
      __tev('touchstart', el, p.x, p.y); await __sl(550);
      // measured after the lift (the dragged row may fold); the top edge of a row = before it (its middle = a subtask)
      const tgt = __row(ids[3]), ty = tgt.closest('.trow').getBoundingClientRect().top + 3;
      for (let i = 1; i <= 6; i++) { __tev('touchmove', el, p.x, p.y + (ty - p.y) * i / 6); await __sl(40); }
      out.mark = !!document.querySelector('#view .dropbefore, #view .dropafter');
      __tev('touchend', el, p.x, ty);
      let clicked = 0; const k = () => { clicked++; }; document.addEventListener('click', k);
      const cl = new MouseEvent('click', {bubbles: true, cancelable: true}); tgt.dispatchEvent(cl); document.removeEventListener('click', k);
      out.click = clicked; out.clickPrevented = cl.defaultPrevented;
      await __sl(1500); out.ghost = __ghosts(); out.ids = __ids().slice(0, 5); out.want = ids.slice(1, 3).concat([id]); out.sub = S.tasks.get(id).parent_id;
      return out; })()`);
    check(c.mark && c.ghost === 0, `${tag}: a drag shows the drop mark and leaves no ghost ` + JSON.stringify(c));
    check(c.click === 0 && c.clickPrevented, `${tag}: the click after the drop is swallowed ` + JSON.stringify(c));
    let so = await sortOf();
    check(!c.sub && c.ids.slice(0, 3).join() === c.want.join() && so.get(c.id) > so.get(c.want[1]) && so.get(c.id) < so.get(c.ids[3]), `${tag}: the task sorts where it was let go (server) ` + JSON.stringify(c));

    // 4) Esc after the hold cancels
    const d = await ev(`(async () => { const id = ${T[4]}, el = __row(id), p = __at(el), out = {}, before = __ids().join();
      __tev('touchstart', el, p.x, p.y); await __sl(550); out.lift = __ghosts();
      document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true, cancelable: true})); await __sl(200);
      out.after = __ghosts(); __tev('touchmove', el, p.x, p.y + 80); __tev('touchend', el, p.x, p.y + 80); await __sl(600);
      out.same = __ids().join() === before; out.after2 = __ghosts(); return out; })()`);
    check(d.lift >= 11 && d.after === 0 && d.after2 === 0 && d.same, `${tag}: Esc after the hold cancels, nothing moves ` + JSON.stringify(d));

    // 5) a re-render in the middle of the drag: the touch is still followed and ends cleanly
    const e = await ev(`(async () => { const id = ${T[5]}, el = __row(id), p = __at(el), out = {};
      __tev('touchstart', el, p.x, p.y); await __sl(550);
      __tev('touchmove', el, p.x, p.y + 20); await __sl(60);
      render(); await __sl(100); out.gone = !el.isConnected;
      __tev('touchmove', el, p.x, p.y + 40); await __sl(60); out.ly = lp && lp.ly; out.want = p.y + 40;
      __tev('touchend', el, p.x, p.y + 40); await __sl(800); out.ghost = __ghosts(); out.lp = !!lp; return out; })()`);
    check(Math.abs(e.ly - e.want) < 1 && e.ghost === 0 && !e.lp, `${tag}: a re-render during the drag: the moves still arrive, it ends without a ghost ` + JSON.stringify(e));

    // 6) the list at its end, let go in the bottom auto-scroll strip = after the last open row
    const f = await ev(`(async () => { const v = document.querySelector('#view'); v.scrollTop = v.scrollHeight; await __sl(400);
      const ids = __ids(), id = ids[ids.length - 4], el = __row(id), p = __at(el), y = __strip(), out = {};
      const last = document.querySelector('#view .trow[data-id="' + ids[ids.length - 1] + '"]').getBoundingClientRect();
      out.below = y > last.bottom; out.id = id;
      const u = document.elementFromPoint(p.x, y); out.under = u ? u.tagName + '#' + u.id + '.' + [...u.classList].join('.') + ' in view ' + !!u.closest('#view') : null;
      out.vb = Math.round(v.getBoundingClientRect().bottom); out.y = Math.round(y); out.lastB = Math.round(last.bottom);
      __tev('touchstart', el, p.x, p.y); await __sl(550);
      for (let i = 1; i <= 5; i++) { __tev('touchmove', el, p.x, p.y + (y - p.y) * i / 5); await __sl(40); }
      await __sl(600);
      out.mark = (document.querySelector('#view .dropafter') || {}).dataset?.id;
      __tev('touchend', el, p.x, y); await __sl(1500);
      const now = __ids(); out.lastNow = now[now.length - 1]; out.ghost = __ghosts(); return out; })()`);
    await shot('p2193c-390-strip.png');
    so = await sortOf();
    check(f.ghost === 0 && f.lastNow === f.id && Math.max(...so.values()) === so.get(f.id), `${tag}: let go in the bottom strip with the list at its end = after the last row (below it: ${f.below}) ` + JSON.stringify(f));

    // 7) sections: the list at its end, let go in the bottom strip = the end
    await ev(`(() => { location.hash = '#l/${SL}'; return 1; })()`); await ready(ev, '#view .ghead[data-section]');
    const g = await ev(`(async () => { const LID = ${SL}, sec = n => S.sections.find(s => s.list_id === LID && s.name === n).id, out = {};
      const v = document.querySelector('#view'); out.scrolls = v.scrollHeight > v.clientHeight + 40; v.scrollTop = v.scrollHeight; await __sl(400);
      const hs = [...document.querySelectorAll('#view .ghead[data-section]')].filter(h => h.dataset.section && h.getBoundingClientRect().top > 90 && h.getBoundingClientRect().bottom < innerHeight - 160);
      const h = hs[0], name = S.sections.find(s => s.id === +h.dataset.section).name, r = h.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2, ty = __strip();
      out.name = name;
      __tev('touchstart', h, x, y); await __sl(650); out.fold = !!document.querySelector('#view .sb-secfold');
      for (let i = 1; i <= 6; i++) { __tev('touchmove', h, x, y + (ty - y) * i / 6); await __sl(40); }
      await __sl(700);
      out.mark = (document.querySelector('#view .dropafter, #view .dropbefore') || {}).className || '';
      __tev('touchend', h, x, ty); await __sl(1500);
      out.now = __secs(LID); out.clean = !document.querySelector('.sb-secghost, #view .sb-secfold'); return out; })()`);
    await shot('p2193c-390-secstrip.png');
    const want = SN.filter(n => n !== g.name).concat([g.name]).join();
    check(g.scrolls && g.fold && /dropafter/.test(g.mark) && g.now === want && g.clean, `${tag}: a section let go in the bottom strip with the list at its end lands at the end ` + JSON.stringify(g));
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
