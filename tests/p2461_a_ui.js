// 2.46.1 UI tests, part A (the sidebar and dragging), own container (start.sh), Firefox (the real layout).
// - #1607: the folder row reads like a list row: the arrow before the folder icon, the number right after the name, the share
//   icon in the column of the lists' share icon, the "…" takes its place on hover (the row does not move); phone: the arrow
//   and the folder icon are a big target that folds
// - #1643: a folder row has the height of a list row, no extra room between folders (open or folded)
// - #1612: a list dragged below the last row lands at the very end; dropped on its own folder's header / on "Lists" = the end there
// - #1635: a section / board column dropped past the last one = the end (mark "after"); on a phone a long press drags a section,
//   held without moving = the menu up / down
// - #1636: a shopping list shows the cart (sidebar, list header) unless it has an own icon / an emoji in its name
// Screenshots with P2461A_SHOTS=<dir>.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2461_a_ui', check, shots: 'P2461A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return Array.isArray(j) ? j : {...j, status: r.status}; };
const ALL = 'cal,timeline,matrix,habits,pomo,collab,stats,time,progress,agents,comments,kanban,family';

// in the page: synthetic HTML5 drag events at a point (Firefox lays them out for real)
const DRAG = `window.__fire = (type, el, x, y, dt) => { const e = new DragEvent(type, {bubbles: true, cancelable: true, clientX: x, clientY: y, dataTransfer: dt}); el.dispatchEvent(e); return e.defaultPrevented; };
window.__sideDrag = async (id, x, y) => { const dt = new DataTransfer(), r = document.querySelector('#side .srow[data-list="' + id + '"]'); __fire('dragstart', r, 0, 0, dt);
  const t = document.elementFromPoint(x, y) || document.body, ok = __fire('dragover', t, x, y, dt), mark = (document.querySelector('#side .dropafter, #side .dropbefore, #side .drop') || {}).className || '';
  __fire('drop', t, x, y, dt); __fire('dragend', r, 0, 0, dt); await new Promise(r => setTimeout(r, 900)); return {ok, mark}; };
window.__order = () => sideOrder().map(l => l.name + (l.folder ? '@' + l.folder : '')).join(',');
window.__secs = lid => secIds(lid).map(i => S.sections.find(s => s.id === i).name).join(',');
1`;

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ALL.split(',').filter(x => !['collab', 'time'].includes(x))});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: ALL});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const L = {};
  for (const [n, f] of [['Todo', ''], ['Groceries', ''], ['Gifts', 'Family'], ['Trips', 'Family'], ['Taxes', 'Private'], ['Car', 'Private'], ['Bills', 'Private/Office'], ['Ideas', 'Home']]) {
    L[n] = (await call('POST', '/api/lists', {name: n})).id;
    if (f) await call('PATCH', `/api/lists/${L[n]}`, {folder: f});
    await call('POST', '/api/tasks', {title: n + ' task', list_id: L[n]});
  }
  await call('PATCH', '/api/settings', {folders: JSON.stringify(['Family', 'Private', 'Private/Office', 'Home'])});
  check((await call('PUT', '/api/folders/people', {folder: 'Family', user_id: BOB, role: 'edit'})).shared === 2, 'setup: the folder Family is shared');
  await call('PUT', `/api/lists/${L.Groceries}/members`, {user_id: BOB, role: 'edit'});
  await call('PATCH', `/api/lists/${L.Groceries}`, {family: 'shopping'});
  const MARKET = (await call('POST', '/api/lists', {name: '🧺 Market'})).id;
  await call('PATCH', `/api/lists/${MARKET}`, {family: 'shopping'});
  // sections: a list and a board with three each
  const SEC = {};
  for (const [k, view] of [['list', 'list'], ['board', 'kanban']]) {
    SEC[k] = (await call('POST', '/api/lists', {name: 'Sections ' + k})).id;
    await call('PATCH', `/api/lists/${SEC[k]}`, {view});
    for (const n of ['Alpha', 'Beta', 'Gamma']) {
      const s = await call('POST', '/api/sections', {list_id: SEC[k], name: n});
      for (let i = 0; i < 2; i++) await call('POST', '/api/tasks', {title: `${n} ${i}`, list_id: SEC[k], section_id: s.id});
    }
  }

  const ffLogin = async ({ev, nav}, theme) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"${theme}"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, sel, n = 40) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('${sel}')`).catch(() => false)); i++) await sleep(250); await sleep(700); };
  const RECTS = `(() => { const R = el => el && el.getBoundingClientRect(), fh = f => document.querySelector('#side .fhead[data-folder="' + f + '"]'), lr = id => document.querySelector('#side .srow[data-list="' + id + '"]');
    const f = fh('Family'), g = lr(${L.Gifts}), t = lr(${L.Todo}), gr = lr(${L.Groceries});
    return {fcar: R(f.querySelector('.fcar')).left, sic: R(f.querySelector('.sic')).left, nR: R(f.querySelector('.n')).right, cL: R(f.querySelector('.c')).left, cR: R(f.querySelector('.c')).right,
      fshrR: R(f.querySelector('.fshr')).right, shrR: R(gr.querySelector('.shr')).right, kidShrR: R(g.querySelector('.shr')).right, hF: R(f).height, hL: R(t).height,
      kidSic: R(g.querySelector('.sic')).left, nL: R(f.querySelector('.n')).left, fL: R(f).left,
      fshrOp: +getComputedStyle(f.querySelector('.fshr')).opacity, menuOp: +getComputedStyle(f.querySelector('.fmenu')).opacity, fTop: R(f).top};
  })()`;

  // ================= desktop (mouse)
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '1440 light';
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 1000}});
    check(await ffLogin(o, 'light') === 200, tag + ': login');
    await o.nav(B + '#inbox'); await ready(ev, '#side .fhead[data-folder="Family"]');
    await ev(DRAG);
    // #1607 / #1643: the folder row
    const a = await ev(RECTS);
    check(a.fcar < a.sic && a.cL >= a.nR && a.cL - a.nR < 16, `${tag}: #1607: arrow before the folder icon, the number right after the name ` + JSON.stringify(a));
    check(Math.abs(a.fshrR - a.shrR) <= 1 && Math.abs(a.fshrR - a.kidShrR) <= 1, `${tag}: #1607: the folder's share icon in the column of the lists' share icon ` + JSON.stringify(a));
    check(Math.abs(a.hF - a.hL) <= 1, `${tag}: #1643: a folder row as high as a list row ` + JSON.stringify(a));
    check(a.kidSic > a.sic, `${tag}: #1607: the lists inside start further in than the folder icon (a tree) ` + JSON.stringify(a));
    // hover: the "…" in the share icon's place, nothing moves
    const fp = await ev(`(() => { const r = document.querySelector('#side .fhead[data-folder="Family"]').getBoundingClientRect(); return {x: Math.round(r.left + 30), y: Math.round(r.top + r.height / 2)}; })()`);
    await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'm', parameters: {pointerType: 'mouse'}, actions: [{type: 'pointerMove', x: fp.x, y: fp.y}]}]}); await sleep(400);
    const b = await ev(RECTS), mr = await ev(`(() => { const m = document.querySelector('#side .fhead[data-folder="Family"] .fmenu').getBoundingClientRect(), s = document.querySelector('#side .fhead[data-folder="Family"] .fshr').getBoundingClientRect(); return {mL: m.left, mR: m.right, sL: s.left, sR: s.right}; })()`);
    check(b.menuOp === 1 && b.fshrOp === 0 && mr.mL < mr.sR && mr.mR > mr.sL, `${tag}: #1607: on hover the "…" shows where the share icon was ` + JSON.stringify({b, mr}));
    check(Math.abs(b.cL - a.cL) < .5 && Math.abs(b.hF - a.hF) < .5 && Math.abs(b.fTop - a.fTop) < .5, `${tag}: #1607: the row does not move on hover ` + JSON.stringify({a: [a.cL, a.hF, a.fTop], b: [b.cL, b.hF, b.fTop]}));
    await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'm', parameters: {pointerType: 'mouse'}, actions: [{type: 'pointerMove', x: 900, y: 500}]}]});
    await shot('p2461a-1440-side.png');
    // #1643: folded folders follow each other like list rows, the same height open or folded
    const fold = await ev(`(async () => { ['Family', 'Private', 'Home'].forEach(f => foldSet(f, true)); renderSide(); await new Promise(r => setTimeout(r, 300));
      const hs = ['Family', 'Private', 'Home'].map(f => document.querySelector('#side .fhead[data-folder="' + f + '"]').getBoundingClientRect());
      const out = {gaps: [Math.round(hs[1].top - hs[0].bottom), Math.round(hs[2].top - hs[1].bottom)], h: hs.map(r => Math.round(r.height))};
      ['Family', 'Private', 'Home'].forEach(f => foldSet(f, false)); renderSide(); return out; })()`);
    check(fold.gaps.every(g => g === 0) && fold.h.every(h => Math.abs(h - a.hF) <= 1), `${tag}: #1643: folded folders without room between them, the same height ` + JSON.stringify(fold));
    // #1636: the cart
    const cart = await ev(`(() => { const c = ic('cart'), s = el => el ? el.outerHTML.replace(/ class="[^"]*"/g, '') : ''; const want = s(new DOMParser().parseFromString(c, 'text/html').body.firstChild);
      return {side: s(document.querySelector('#side .srow[data-list="${L.Groceries}"] .sic svg')) === want, todo: s(document.querySelector('#side .srow[data-list="${L.Todo}"] .sic svg')) === want,
        market: s(document.querySelector('#side .srow[data-list="${MARKET}"] .sic svg')) === want}; })()`);
    check(cart.side && !cart.todo && !cart.market, `${tag}: #1636: the shopping list shows the cart, a plain list not, an emoji in the name stays ` + JSON.stringify(cart));
    await ev(`(() => { location.hash = '#l/${L.Groceries}'; return 1; })()`); await ready(ev, '#top h1 .lic');
    check(await ev(`(() => { const s = el => el ? el.outerHTML.replace(/ class="[^"]*"/g, '') : ''; return s(document.querySelector('#top h1 .lic svg')) === s(new DOMParser().parseFromString(ic('cart'), 'text/html').body.firstChild); })()`), `${tag}: #1636: the list header shows the cart`);
    await ev(`(() => { const l = listById(${L.Groceries}); l.icon = liconSrc(LICON_PRESETS[0][0]); renderSide(); return 1; })()`); await sleep(200);
    check(await ev(`!!document.querySelector('#side .srow[data-list="${L.Groceries}"] .sic img, #side .srow[data-list="${L.Groceries}"] .sic .licon')`), `${tag}: #1636: an own icon stays`);
    await ev(`(() => { listById(${L.Groceries}).icon = ''; location.hash = '#inbox'; renderSide(); return 1; })()`); await sleep(400);

    // #1612: below the last row = the very end (into the last folder, after its last list)
    const last = await ev(`(() => { const r = [...document.querySelectorAll('#side .sg-lists .srow[data-list]')].pop().getBoundingClientRect(); return {x: Math.round(r.left + 40), y: Math.round(r.bottom + 8)}; })()`);
    const d1 = await ev(`__sideDrag(${L.Todo}, ${last.x}, ${last.y})`);
    const o1 = await ev(`__order()`);
    check(d1.ok && /dropafter/.test(d1.mark) && /Ideas@Home,Todo@Home$/.test(o1), `${tag}: #1612: dropped below the last list = at the very end ` + JSON.stringify(d1) + ' ' + o1);
    // on its own folder's header = the end of that folder
    const fh = await ev(`(() => { const r = document.querySelector('#side .fhead[data-folder="Family"] .sic').getBoundingClientRect(); return {x: Math.round(r.left + 4), y: Math.round(r.top + r.height / 2)}; })()`);
    const d2 = await ev(`__sideDrag(${L.Gifts}, ${fh.x}, ${fh.y})`);
    check(d2.ok && /Trips@Family,Gifts@Family/.test(await ev(`__order()`)), `${tag}: #1612: dropped on its own folder's header = the end of the folder ` + await ev(`__order()`));
    // on "Lists" while it has no folder = the end of the lists without a folder
    const lr = await ev(`(() => { const r = document.querySelector('#side .shead.lroot .sgt').getBoundingClientRect(); return {x: Math.round(r.left + 6), y: Math.round(r.top + r.height / 2)}; })()`);
    const firstLoose = await ev(`sideOrder().find(l => !l.folder).id`);
    const d3 = await ev(`__sideDrag(${firstLoose}, ${lr.x}, ${lr.y})`), o3 = await ev(`__order()`), loose = o3.split(',').filter(x => !x.includes('@'));
    check(d3.ok && loose[loose.length - 1] === (await ev(`listById(${firstLoose}).name`)), `${tag}: #1612: dropped on "Lists" = the end of the lists without a folder ` + o3);
    // the lower half of the last list of a subfolder = after it (#991 still works)
    const sub = await ev(`(() => { const r = document.querySelector('#side .srow[data-list="${L.Bills}"]').getBoundingClientRect(); return {x: Math.round(r.left + 40), y: Math.round(r.bottom - 3)}; })()`);
    await ev(`__sideDrag(${L.Car}, ${sub.x}, ${sub.y})`);
    check(/Bills@Private\/Office,Car@Private\/Office/.test(await ev(`__order()`)), `${tag}: #1612: the end of a subfolder ` + await ev(`__order()`));

    // #1635: sections (list) and board columns: to the end and back to the start
    for (const k of ['list', 'board']) {
      await ev(`(() => { location.hash = '#l/${SEC[k]}'; return 1; })()`); await ready(ev, k === 'list' ? '#view .ghead[data-section]' : '#view .kcol[data-kcol]');
      const go = async (name, where) => ev(`(async () => { const LID = ${SEC[k]}, kan = ${k === 'board'}, where = '${where}', sid = S.sections.find(s => s.list_id === LID && s.name === '${name}').id;
        const dt = new DataTransfer(), h = document.querySelector('[data-sdrag="' + sid + '"]'); __fire('dragstart', h, 0, 0, dt); await new Promise(r => setTimeout(r, 120));
        for (let i = 0; !kan && i < 30 && !document.querySelector('#view .sb-secfold'); i++) await new Promise(r => setTimeout(r, 50));  // 2.56.1: the fold comes in a frame (slow CI runner)
        const els = sb_secEls().filter(e => kan ? e.dataset.kcol : e.querySelector('.ghead').dataset.section), r = (where === 'end' ? els[els.length - 1] : els[0]).getBoundingClientRect();
        const x = kan ? (where === 'end' ? r.right + 8 : r.left + 6) : r.left + 60, y = kan ? r.top + 30 : (where === 'end' ? r.bottom + 8 : r.top + 3), t = document.elementFromPoint(x, y) || document.body;
        const ok = __fire('dragover', t, x, y, dt), mark = (document.querySelector('#view .dropafter, #view .dropbefore') || {}).className || '', fold = !!document.querySelector('#view .sb-secfold');
        __fire('drop', t, x, y, dt); __fire('dragend', h, 0, 0, dt); await new Promise(r => setTimeout(r, 900)); return {ok, mark, fold, now: __secs(LID)}; })()`);
      const e1 = await go('Alpha', 'end');
      check(e1.ok && /dropafter/.test(e1.mark) && e1.now === 'Beta,Gamma,Alpha' && (k === 'board' || e1.fold), `${tag}: #1635 ${k}: past the last one = the end, mark after${k === 'list' ? ', the section folds' : ''} ` + JSON.stringify(e1));
      const e2 = await go('Alpha', 'start');
      check(e2.ok && /dropbefore/.test(e2.mark) && e2.now === 'Alpha,Beta,Gamma', `${tag}: #1635 ${k}: back to the start ` + JSON.stringify(e2));
      const e3 = await go('Gamma', 'start');
      check(e3.now === 'Gamma,Alpha,Beta' && !(await ev(`!!document.querySelector('#view .sb-secfold, #view .dropafter, #view .dropbefore')`)), `${tag}: #1635 ${k}: the last one to the start, no marks left ` + JSON.stringify(e3));
      await ev(`saveSectionOrder(${SEC[k]}, ['Alpha', 'Beta', 'Gamma'].map(n => S.sections.find(s => s.list_id === ${SEC[k]} && s.name === n).id))`); await sleep(500);
    }
  }, false);

  // ================= phone (touch)
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '390 dark';
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    check(await ffLogin(o, 'dark') === 200, tag + ': login');
    await o.nav(B + '#inbox'); await ready(ev, '#side .fhead[data-folder="Family"]');
    await ev(`(() => { document.querySelector('[data-act="side"]').click(); return 1; })()`); await sleep(600);
    const a = await ev(RECTS);
    check(Math.abs(a.hF - a.hL) <= 1 && a.hF >= 43, `${tag}: #1643: folder row as high as a list row (44 px) ` + JSON.stringify(a));
    check(a.fcar < a.sic && a.nL - a.fL >= 40, `${tag}: #1607: the arrow first, at least 40 px to tap left of the name ` + JSON.stringify(a));
    // a tap on the arrow folds, a tap on the name opens the folder
    const hit = await ev(`(() => { const r = document.querySelector('#side .fhead[data-folder="Family"] .fcar').getBoundingClientRect(), el = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return !!el.closest('[data-act="folder-toggle"]') && !el.closest('.fgo, .iconbtn'); })()`);
    check(hit, `${tag}: #1607: the arrow belongs to the folding part of the row`);
    await shot('p2461a-390-side.png');
    await ev(`(() => { closeSide(); location.hash = '#l/${SEC.list}'; return 1; })()`); await ready(ev, '#view .ghead[data-section]');
    await ev(DRAG);
    // #1635: a long press drags a section to the end; held without moving = the menu
    const t = await ev(`(async () => { const sl = ms => new Promise(r => setTimeout(r, ms)), LID = ${SEC.list}, sec = n => S.sections.find(s => s.list_id === LID && s.name === n).id;
      const tev = (type, el, x, y) => { const t = new Touch({identifier: 1, target: el, clientX: x, clientY: y}); el.dispatchEvent(new TouchEvent(type, {bubbles: true, cancelable: true, touches: type === 'touchend' ? [] : [t], targetTouches: type === 'touchend' ? [] : [t], changedTouches: [t]})); };
      const out = {};
      const h = document.querySelector('#view .ghead[data-section="' + sec('Alpha') + '"]'), r = h.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2;
      tev('touchstart', h, x, y); await sl(650);
      out.ghost = !!document.querySelector('.sb-secghost'); out.fold = !!document.querySelector('#view .sb-secfold');
      const els = sb_secEls(), lr = els[els.length - 1].getBoundingClientRect(), ty = Math.min(lr.bottom + 8, innerHeight - 90);
      for (let i = 1; i <= 6; i++) { tev('touchmove', h, x, y + (ty - y) * i / 6); await sl(40); }
      out.mark = (document.querySelector('#view .dropafter, #view .dropbefore') || {}).className || '';
      tev('touchend', h, x, ty); await sl(1500);
      out.now = __secs(LID); out.clean = !document.querySelector('.sb-secghost, #view .sb-secfold');
      const h2 = document.querySelector('#view .ghead[data-section="' + sec('Gamma') + '"]'), r2 = h2.getBoundingClientRect();
      tev('touchstart', h2, r2.left + 60, r2.top + 6); await sl(650); tev('touchend', h2, r2.left + 60, r2.top + 6); await sl(300);
      out.menu = [...document.querySelectorAll('#pop button, .menu button')].map(b => b.textContent.trim()).filter(Boolean);
      out.same = __secs(LID);
      return out; })()`);
    check(t.ghost && t.fold && /dropafter/.test(t.mark) && t.now === 'Beta,Gamma,Alpha' && t.clean, `${tag}: #1635: a long press drags the section to the end (it folds while dragged) ` + JSON.stringify(t));
    check(t.menu.includes('Move section up') && t.menu.includes('Move section down') && t.same === t.now, `${tag}: #1635: held without moving = the menu up / down, nothing moved ` + JSON.stringify(t));
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
