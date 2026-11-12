// 2.1035.0 A UI test (#5802 drag from the left half into the right half = open it there), own container (start.sh, isolated test database).
// kalmido-suite: fresh
// Firefox at 2800 px, the split view on. Invented data only. alice has no organisation (freelancer-matrix: Geteilte Ansicht).
// The drags are synthetic DragEvents with one DataTransfer (as in p2760_a_xdrag_ui.js), the drop goes where a person sees the field:
// - while a list / task / document / knowledge page of the left half is dragged, "Open here" lies over the right half (visible, on
//   top at its place, beside the grip, inside the right half); dropped there, the right half shows that thing's REAL content
//   (the project's tasks, the task's title in its panel, the document's name, the page's title) and the left stays where it was
// - dropped anywhere else the drag does what it did before (a task onto a project of the left sidebar = moved) and the field goes;
//   a drag that ends without a drop takes the field away too
// - with the split view off nothing appears
// the left sidebar's own sorting is not touched by the field (it stops the drop it takes; the rest stays sidebar.js / dnd.js)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21035_a_splitdrop', check, shots: 'P21035A_SHOTS', lazy: true});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CA}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,wiki,files,docs', look: JSON.stringify({split: true})});
  const L1 = (await call('POST', '/api/lists', {name: 'Harbour shoot', kind: 'project'})).id;
  const L2 = (await call('POST', '/api/lists', {name: 'Lighthouse interview', kind: 'project'})).id;
  const T1 = (await call('POST', '/api/tasks', {title: 'Scout the north pier', list_id: L1})).id;
  const T3 = (await call('POST', '/api/tasks', {title: 'Rent the dolly', list_id: L1})).id;
  await call('POST', '/api/tasks', {title: 'Book the keeper for Tuesday', list_id: L2});
  const PG = (await call('POST', '/api/wiki/pages', {space: 'private', path: 'Shoot day checklist', body: 'Bring the spare batteries'})).id;
  const fd = new FormData(); fd.append('space', 'private');
  fd.append('files', new Blob(['Permit for the north pier\n'], {type: 'text/plain'}), 'Pier permit.txt');
  const DOC = ((await (await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CA}, body: fd})).json().catch(() => ({}))).ids || [])[0];
  check(L1 && L2 && T1 && T3 && PG && DOC, 'setup ' + JSON.stringify({L1, L2, T1, T3, PG, DOC}));
  const task = id => call('GET', `/api/tasks/${id}`);
  const poll = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const v = await fn(); if (v) return v; await sleep(250); } return null; };

  await firefox(async ({cmd, ev, ctx, nav, until, shot}) => {
    await nav(B + 'static/icon.svg');
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'ff: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 2800, height: 1100}});
    let nn = 0;
    const FR = `document.querySelector('#splitpane iframe.splitfr')`;
    const FW = `(() => { try { return ${FR}.contentWindow; } catch { return null; } })()`;
    const untilFr = (x, opt = {timeout: 30000}) => until(`(() => { const w = ${FW}, d = w && w.document; if (!w || !d) return null; try { return (${x}); } catch { return null; } })()`, opt);
    const rightUp = () => untilFr(`w.eval('typeof S !== "undefined" && S.booted') && !!d.querySelector('#view')`, {timeout: 40000});
    const load = async h => { await nav(B + '?n=' + (++nn) + h); await until(`typeof S !== 'undefined' && S.booted && !!document.querySelector('#view')`, {timeout: 30000}); };
    // text a person can see (the innermost elements carrying it, laid out, inside the window, not hidden) - as in p2891_a
    const SEEN = `((d, sel, re) => { const vw = d.defaultView.innerWidth, vh = d.defaultView.innerHeight;
      const all = [...d.querySelectorAll(sel)].flatMap(r => [r, ...r.querySelectorAll('*')]).filter(e => re.test(e.textContent || '') && ![...e.children].some(c => re.test(c.textContent || '')));
      return all.some(e => { const r = e.getBoundingClientRect();
        if (r.width < 2 || r.height < 2 || r.right < 0 || r.left > vw || r.bottom < 0 || r.top > vh) return false;
        return !e.checkVisibility || e.checkVisibility({visibilityProperty: true, opacityProperty: true}); }); })`;
    const seenFr = (sel, re) => untilFr(`${SEEN}(d, ${JSON.stringify(sel)}, ${re})`);
    // the drag in steps: start on src (the left app), then the field (it comes after the dragstart), then over + drop on dst, end
    const start = src => ev(`(() => { const s = document.querySelector(${JSON.stringify(src)}); if (!s) return false; window.t21035 = {dt: new DataTransfer(), s};
      s.dispatchEvent(new DragEvent('dragstart', {bubbles: true, cancelable: true, dataTransfer: t21035.dt})); return true; })()`);
    // the field as a person sees it: its text, on top at its middle, inside the right half, right of the grip
    const field = () => until(`(() => { const z = document.querySelector('#splitpane .spldrop'); if (!z) return null; const r = z.getBoundingClientRect(), p = document.querySelector('#splitpane').getBoundingClientRect(), g = document.querySelector('#splitpane .splgrip').getBoundingClientRect();
      const h = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      return {text: z.textContent.trim(), top: !!h && (h === z || z.contains(h)), inside: r.left >= p.left && r.right <= p.right + 1 && r.width > 100 && r.height > 40, grip: r.left >= g.right}; })()`, {timeout: 5000});
    const drop = dst => ev(`(() => { const {dt, s} = window.t21035, de = document.querySelector(${JSON.stringify(dst)}); if (!de) return {err: 'no target'};
      const r = de.getBoundingClientRect(), o = {bubbles: true, cancelable: true, dataTransfer: dt, clientX: r.left + r.width / 2, clientY: r.top + Math.min(r.height / 2, 10)};
      const ov = new DragEvent('dragover', o); de.dispatchEvent(ov); const on = de.classList.contains('on');
      const dr = new DragEvent('drop', o); de.dispatchEvent(dr);
      s.dispatchEvent(new DragEvent('dragend', {bubbles: true, dataTransfer: dt}));
      return {over: ov.defaultPrevented, eff: dt.dropEffect, on, drop: dr.defaultPrevented, gone: !document.querySelector('.spldrop')}; })()`);
    const openByDrag = async (what, src) => {
      check(await start(src), what + ': the drag starts on ' + src);
      const f = await field();
      check(f && f.text === 'Open here' && f.top && f.inside && f.grip, what + ': "Open here" over the right half, on top, beside the grip ' + JSON.stringify(f));
      const d = await drop('#splitpane .spldrop');
      check(d.over && d.on && d.drop && d.gone, what + ': the field takes the drop and goes ' + JSON.stringify(d));
    };

    await load('#l/' + L1);
    check(await rightUp(), 'the split view is on: the right half is up');
    await until(`!!document.querySelector('#view .trow[data-id="${T1}"]') && !!document.querySelector('#side .srow[data-list="${L2}"]')`);

    // ---- a list of the left sidebar: its tasks on the right
    await openByDrag('list', `#side .srow[data-list="${L2}"]`);
    check(await untilFr(`w.location.hash === '#l/${L2}'`) && await seenFr('#view .trow', /Book the keeper for Tuesday/), 'list dropped: the right half shows its tasks');
    await shot('p21035a-list.png');
    check(await ev(`location.hash === '#l/${L1}'`), 'the left stays where it was');

    // ---- a task of the left list: its panel with the title on the right; it stays in its list
    await openByDrag('task', `#view .trow[data-id="${T1}"]`);
    check(await untilFr(`w.location.hash === '#t/${T1}'`) && await seenFr('#detail', /Scout the north pier/), 'task dropped: the right half shows its panel with the title');
    check((await task(T1)).list_id === L1, 'the task stays in its list');

    // ---- dropped elsewhere: a task onto a project of the left sidebar is moved as before, the field goes, the right half stays
    check(await start(`#view .trow[data-id="${T3}"]`) && !!await field(), 'elsewhere: the field shows during the drag');
    const el = await drop(`#side .srow[data-drop="l:${L2}"]`);
    check(el.gone, 'elsewhere: the field went with the drop ' + JSON.stringify(el));
    check(await poll(async () => (await task(T3)).list_id === L2), 'elsewhere: the task was moved onto the project as before');
    check(await untilFr(`w.location.hash === '#t/${T1}'`), 'elsewhere: the right half stayed on the task');
    // a drag that ends without a drop
    check(await start(`#view .trow[data-id="${T1}"]`) && !!await field(), 'cancelled: the field shows');
    await ev(`(window.t21035.s.dispatchEvent(new DragEvent('dragend', {bubbles: true, dataTransfer: window.t21035.dt})), 1)`);
    check(await until(`!document.querySelector('.spldrop')`, {timeout: 3000}), 'cancelled: the field goes with the drag\'s end');

    // ---- a document card of the left half: its name on the right
    await load('#docs');
    check(await rightUp(), 'docs: the right half is up again');
    await until(`!!document.querySelector('#view .dc-card [data-dco="${DOC}"]')`, {timeout: 30000});
    await openByDrag('document', `#view .dc-card [data-dco="${DOC}"]`);
    check(await untilFr(`w.location.hash === '#docs/${DOC}'`) && await seenFr('body', /Pier permit/), 'document dropped: the right half shows it');

    // ---- a knowledge page of the left sidebar's tree: its title and text on the right
    await load('#wiki');
    check(await rightUp(), 'wiki: the right half is up again');
    const wsel = `#side .sbbt[data-sbbns="wk"]:has(> .sbbtn[data-go="wiki/${PG}"])`;
    const has = await until(`!!document.querySelector(${JSON.stringify(wsel)})`, {timeout: 15000});
    check(has, 'wiki: the page is in the sidebar\'s tree ' + JSON.stringify(await ev(`[...document.querySelectorAll('#side .sbbt')].map(t => (t.dataset.sbbns || '') + ':' + (t.querySelector('.sbbtn')?.dataset.go || '')).slice(0, 12)`)));
    if (has) {
      await openByDrag('knowledge page', wsel);
      check(await untilFr(`w.location.hash === '#wiki/${PG}'`) && await seenFr('#view', /Shoot day checklist/) && await seenFr('#view', /Bring the spare batteries/), 'page dropped: the right half shows its title and text');
      await shot('p21035a-wiki.png');
    }

    // ---- the split view off: no field
    await load('#l/' + L1);
    await ev(`(LS.set('split', false), spl_check(), 1)`);
    await until(`!document.querySelector('iframe.splitfr')`);
    await start(`#view .trow[data-id="${T1}"]`);
    await ev(`new Promise(r => setTimeout(() => requestAnimationFrame(() => r(1)), 50))`);
    check(await ev(`!document.querySelector('.spldrop')`), 'off: no field during a drag');
    await ev(`(window.t21035.s.dispatchEvent(new DragEvent('dragend', {bubbles: true, dataTransfer: window.t21035.dt})), 1)`);
  }, false);

  console.log(`p21035_a_splitdrop: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERR', e); process.exit(1); });
