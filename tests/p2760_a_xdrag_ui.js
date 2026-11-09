// 2.760.0 A UI test (#4859 dragging between the two halves of the split view), own container (start.sh, isolated test database),
// kalmido-suite: fresh
// Firefox with a mouse at 2800 px, the split view on. Invented data only. alice has no organisation (the person without one,
// freelancer parity); bob is a second person whose things alice may not see.
// The drags are synthetic DragEvents with one DataTransfer that go from one document (left app / right iframe) into the other,
// like the browser does between the two same-origin copies; every case checks the server's state and the undo where there is one.
// 1. a document onto a task of the other half = linked with the task (undo); onto its comment box = a reference
// 2. a task onto a row of another list in the right half = moved (undo); a task of the right half onto a project in the left sidebar = moved
// 3. a task onto a day of the calendar = its date; a file onto a day = an all-day appointment (undo removes it)
// 4. a receipt (document card) into the office = "Move to office" (undo = back)
// 5. a file onto the open folder of the file store in the other half = moved there
// refusals: a payload without this origin's token does nothing; a task / file alice may not see = a toast, nothing changes
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2760_a_xdrag', check, shots: 'P2760A_SHOTS', lazy: true});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  const call = async (method, url, body, ck = CA) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
  const FEAT = 'cal,events,comments,files,docs,office';
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, look: JSON.stringify({split: true})});
  const multipart = async (url, fields, name, text, ck = CA) => {
    const fd = new FormData(); fd.append(url.endsWith('/docs') ? 'files' : 'file', new Blob([text]), name);
    for (const [k, v] of Object.entries(fields)) fd.append(k, v);
    const r = await fetch(B + url.replace(/^\//, ''), {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: ck}, body: fd});
    return r.json();
  };
  const L1 = (await call('POST', '/api/lists', {name: 'Harbour shoot', kind: 'project'})).id;
  const L2 = (await call('POST', '/api/lists', {name: 'Studio day', kind: 'project'})).id;
  const T1 = (await call('POST', '/api/tasks', {title: 'Scout the north pier', list_id: L1})).id;
  const T2 = (await call('POST', '/api/tasks', {title: 'Book the studio', list_id: L2})).id;
  const T3 = (await call('POST', '/api/tasks', {title: 'Order the props', list_id: L2})).id;
  const D = (await multipart('/api/docs', {ws: 'private'}, 'lens-rental-note.txt', 'Lens rental for the harbour shoot')).ids?.[0];
  const FA = (await call('POST', '/api/files/folders', {name: 'Scans', space: 'private'})).id;
  const FO = (await call('POST', '/api/files/folders', {name: 'Contracts', space: 'private'})).id;
  const FL = (await multipart('/api/files/upload', {parent_id: String(FA)}, 'call-sheet.txt', 'Call sheet day 1')).items?.[0]?.id;
  const cal = await call('POST', '/api/evcals', {name: 'Shoots'});
  check(L1 && L2 && T1 && T2 && D && FA && FO && FL && cal.id, 'setup ' + JSON.stringify({L1, L2, T1, T2, D, FA, FO, FL, cal: cal.id}));
  // bob: a private task and a file alice may not see
  await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'});
  const CB = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, CB);
  const LB = (await call('POST', '/api/lists', {name: 'Bob private', kind: 'project'}, CB)).id;
  const TB = (await call('POST', '/api/tasks', {title: 'Bob secret', list_id: LB}, CB)).id;
  const FBF = (await call('POST', '/api/files/folders', {name: 'Bob files', space: 'private'}, CB)).id;
  const FB = (await multipart('/api/files/upload', {parent_id: String(FBF)}, 'bob.txt', 'Bob only', CB)).items?.[0]?.id;
  check(TB && FB, 'setup bob ' + JSON.stringify({TB, FB}));
  const task = id => call('GET', `/api/tasks/${id}`);
  const poll = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const v = await fn(); if (v) return v; await sleep(250); } return null; };

  await firefox(async ({cmd, ev, ctx, nav, until, shot}) => {
    await nav(B + 'static/icon.svg');
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'ff: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 2800, height: 1100}});
    let nn = 0;
    const load = async h => { await nav(B + '?n=' + (++nn) + h); await until(`typeof S !== 'undefined' && S.booted && !!document.querySelector('#view')`, {timeout: 30000}); };
    const FR = `document.querySelector('#splitpane iframe.splitfr')`;
    const RD = `(() => { try { return ${FR}.contentDocument; } catch { return null; } })()`;
    // the right half shows route, ready when sel is there
    const right = async (route, sel, pre = route.replace(/\/.*/, '')) => {
      // a right half that is still starting first comes up whole (spl_show swaps the hash of the running copy)
      await until(`(() => { const f = ${FR}; if (!f) return true; const d = ${RD}; return !!(d && d.documentElement.classList.contains('mini') && d.querySelector('#view')); })()`, {timeout: 30000});
      await ev(`(LS.set('split', true), spl_open(${JSON.stringify(route)}).then(() => 1))`);
      return until(`(() => { const d = ${RD}; return !!(d && d.documentElement.classList.contains('mini') && d.defaultView.location.hash.startsWith(${JSON.stringify(pre)}) && d.querySelector(${JSON.stringify(sel)})); })()`, {timeout: 30000});
    };
    // one drag from document "from" (L / R) to document "to": dragstart on src, dragover + drop on dst, dragend on src.
    // pay: no dragstart, the DataTransfer carries this payload (a drag from somewhere else)
    const DRAG = `window.xdDrag = (from, src, to, dst, pay) => {
      const fr = ${FR}, doc = s => s === 'R' ? fr.contentDocument : document;
      const A = doc(from), Z = doc(to), W = Z.defaultView;
      const se = pay ? null : A.querySelector(src), de = Z.querySelector(dst);
      if ((!pay && !se) || !de) return {err: 'missing', se: !!se, de: !!de};
      const dt = new W.DataTransfer();
      if (pay) { dt.setData('application/x-kalmido-ref', JSON.stringify(pay)); dt.setData('application/x-kalmido-kind-' + pay.k[0], '1'); }
      else se.dispatchEvent(new A.defaultView.DragEvent('dragstart', {bubbles: true, cancelable: true, dataTransfer: dt}));
      const r = de.getBoundingClientRect(), o = {bubbles: true, cancelable: true, dataTransfer: dt, clientX: r.left + Math.min(r.width / 2, 40), clientY: r.top + Math.min(r.height / 2, 10)};
      const ov = new W.DragEvent('dragover', o); de.dispatchEvent(ov);
      const hl = de.classList.contains('xdrop');
      const dr = new W.DragEvent('drop', o); de.dispatchEvent(dr);
      if (se) se.dispatchEvent(new A.defaultView.DragEvent('dragend', {bubbles: true, dataTransfer: dt}));
      return {types: [...dt.types], over: ov.defaultPrevented, drop: dr.defaultPrevented, hl};
    }, 1`;
    const drag = async (from, src, to, dst, pay) => { await ev(DRAG); return ev(`xdDrag(${JSON.stringify(from)}, ${JSON.stringify(src)}, ${JSON.stringify(to)}, ${JSON.stringify(dst)}, ${pay ? JSON.stringify(pay) : 'null'})`); };
    const toastIn = (side, re) => until(`(() => { const d = ${side === 'R' ? RD : 'document'}; const t = d && d.querySelector('#toast:not(.hidden)'); return t && ${re}.test(t.textContent) ? t.textContent : null; })()`);
    const undoIn = side => ev(`(() => { const d = ${side === 'R' ? RD : 'document'}; const b = d && d.querySelector('#toast:not(.hidden) button:not(.tx)'); if (!b) return 0; b.click(); return 1; })()`);

    // ---- 2. a task of the left list onto a row of another list in the right half = moved there; undo = back
    await load('#l/' + L1);
    await until(`!!document.querySelector('#view .trow[data-id="${T1}"]')`);
    check(await right('#l/' + L2, `#view .trow[data-id="${T2}"]`), 'the right half shows the second project');
    const d1 = await drag('L', `#view .trow[data-id="${T1}"]`, 'R', `#view .trow[data-id="${T2}"]`);
    check(d1.types?.includes('application/x-kalmido-ref') && d1.types.includes('application/x-kalmido-kind-t'), 'the task carries the data type and its kind ' + JSON.stringify(d1));
    check(d1.over && d1.drop && d1.hl, 'the right half takes the drag (dragover accepted, marked) ' + JSON.stringify(d1));
    check(await poll(async () => (await task(T1)).list_id === L2), '2: the task is now in the right half\'s project');
    check(await toastIn('R', /Moved to/), '2: the right half offers the undo');
    await undoIn('R');
    check(await poll(async () => (await task(T1)).list_id === L1), '2: undo puts it back');
    check(await ev(`!document.body.classList.contains('tdrag') && dragId === null`), 'the left half\'s own drag ended (dragend)');
    // a task of the right half onto a project in the LEFT sidebar (the right copy has no sidebar)
    await until(`!!document.querySelector('#side .srow[data-drop="l:${L1}"]')`);
    await drag('R', `#view .trow[data-id="${T3}"]`, 'L', `#side .srow[data-drop="l:${L1}"]`);
    check(await poll(async () => (await task(T3)).list_id === L1), '2: a task of the right half dropped on a project of the left sidebar is moved there');
    // within ONE half nothing of this runs: the left's own drag onto its own sidebar goes the old way (dnd.js)
    const own = await ev(`(() => { const dt = new DataTransfer(), s = document.querySelector('#view .trow[data-id="${T1}"]'), z = document.querySelector('#side .srow[data-drop="l:${L2}"]');
      s.dispatchEvent(new DragEvent('dragstart', {bubbles: true, cancelable: true, dataTransfer: dt}));
      const ov = new DragEvent('dragover', {bubbles: true, cancelable: true, dataTransfer: dt}); z.dispatchEvent(ov);
      const r = {xd: z.classList.contains('xdrop'), old: z.classList.contains('drop'), id: dragId};
      s.dispatchEvent(new DragEvent('dragend', {bubbles: true, dataTransfer: dt})); return r; })()`);
    check(own.id === T1 && own.old && !own.xd, 'an own drag in one half stays dnd.js\'s (no foreign target) ' + JSON.stringify(own));

    // ---- 3. a task onto a day of the calendar in the right half = its date
    check(await right('#cal', '.cal .cell[data-day], .wad[data-day]'), 'the right half shows the calendar');
    const day = await ev(`(() => { const d = ${RD}; const c = [...d.querySelectorAll('.cal .cell[data-day]:not(.out), .wad[data-day]')]; return c.length ? c[Math.min(3, c.length - 1)].dataset.day : ''; })()`);
    const daySel = `.cal .cell[data-day="${day}"], .wad[data-day="${day}"]`;
    await drag('L', `#view .trow[data-id="${T1}"]`, 'R', daySel);
    check(await poll(async () => (await task(T1)).due === day), '3: the task has the day as its date ' + day);

    // ---- 3. a file of the left file store onto a day = an all-day appointment; undo removes it
    await load('#ablage/' + FA);
    await until(`!!document.querySelector('#view .abrow[data-abid="${FL}"]')`, {timeout: 30000});
    await until(`(() => { const d = ${RD}; return !!(d && d.querySelector(${JSON.stringify(daySel)})); })()`, {timeout: 30000});
    check(await right('#cal', daySel), 'the right half shows the calendar again (after the left reload)');
    const evs = async () => ((await call('GET', `/api/events?from=${day}&to=${day}`)).items || []).filter(x => x.title === 'call-sheet.txt');
    const d3 = await drag('L', `#view .abrow[data-abid="${FL}"]`, 'R', daySel);
    check(d3.over && d3.types?.includes('application/x-kalmido-kind-f'), '3: the calendar takes a file ' + JSON.stringify(d3));
    const made = await poll(async () => { const x = await evs(); return x.length ? x : null; });
    check(made && made.length === 1, '3: the file became an appointment on that day ' + JSON.stringify(made));
    check(await toastIn('R', /Event created/), '3: undo offered');
    await undoIn('R');
    check(await poll(async () => (await evs()).length === 0), '3: undo removes the appointment');

    // ---- 1. a document card of the left half onto a task row of the right half = linked; onto the comment box = a reference
    await load('#docs');
    await until(`!!document.querySelector('.dc-card[data-k="dc${D}"] > button[data-dco]')`, {timeout: 30000});
    check(await right('#l/' + L1, `#view .trow[data-id="${T1}"]`), 'the right half shows the first project again');
    const d4 = await drag('L', `.dc-card[data-k="dc${D}"] > button[data-dco]`, 'R', `#view .trow[data-id="${T1}"]`);
    check(d4.over && d4.hl, '1: a task row of the other half takes a document ' + JSON.stringify(d4));
    check(await poll(async () => (await call('GET', `/api/docs/${D}`)).task?.id === T1), '1: the document is linked with the task');
    check(await toastIn('R', /linked with a task/), '1: undo offered');
    await undoIn('R');
    check(await poll(async () => !(await call('GET', `/api/docs/${D}`)).task), '1: undo unlinks it');
    // the comment box, or the description where there is no comment box (both are text fields of refs.js)
    check(await right('#t/' + T1, '#c-input, #detail #d-md, #detail #d-content', '#'), 'the right half shows the task');
    const box = await ev(`(() => { const d = ${RD}; return d.querySelector('#c-input') ? '#c-input' : d.querySelector('#detail #d-md') ? '#detail #d-md' : '#detail #d-content'; })()`);
    await drag('L', `.dc-card[data-k="dc${D}"] > button[data-dco]`, 'R', box);
    check(await until(`(() => { const d = ${RD}; const v = d?.querySelector(${JSON.stringify(box === '#c-input' ? '#c-input' : '#d-content')})?.value || ''; return v.includes('/#ablage/${D})'); })()`), '1: onto a text field of the task = a reference to the document ' + box);

    // ---- 4. a receipt into the office of the right half = "Move to office"; undo = back
    // 2.760.0: the office turns #office into #office/start on its first draw (location.replace = a hashchange), and an undo
    // message ends with its page (#2801): wait for the office's own page before the drop, not just for #office
    check(await right('#office/start', '#view'), 'the right half shows the office');
    await until(`(() => { const d = ${RD}; return !!(d && d.defaultView.location.hash === '#office/start' && d.querySelector('#view')?.children.length); })()`);
    const d5 = await drag('L', `.dc-card[data-k="dc${D}"] > button[data-dco]`, 'R', '#view');
    check(d5.over, '4: the office takes a document ' + JSON.stringify(d5));
    const area = async () => (await call('GET', `/api/docs/${D}`)).area?.area;
    check(await poll(async () => (await area()) === 'office'), '4: the receipt is in the office ' + await area());
    check(await toastIn('R', /Moved to office/), '4: undo offered ' + JSON.stringify(await ev(`(() => { const d = ${RD}, t = d && d.querySelector('#toast'); return {txt: t?.textContent, cls: t?.className, page: t?.dataset.page, hash: d?.defaultView.location.hash, undo: d?.defaultView.eval('HIST.undo.map(e => e.label)')}; })()`)));
    await undoIn('R');
    check(await poll(async () => (await area()) === 'private'), '4: undo moves it back ' + await area());

    // ---- 5. a file of the left folder onto the open folder of the right half = moved there; undo = back
    await load('#ablage/' + FA);
    await until(`!!document.querySelector('#view .abrow[data-abid="${FL}"]')`, {timeout: 30000});
    check(await right('#ablage/' + FO, `#view .abview[data-abzone="${FO}"]`), 'the right half shows the other folder');
    await drag('L', `#view .abrow[data-abid="${FL}"]`, 'R', `#view .abview[data-abzone="${FO}"]`);
    const parent = async () => (await call('GET', `/api/files/nodes/${FL}`)).parent_id;
    check(await poll(async () => (await parent()) === FO), '5: the file is in the right half\'s folder');
    check(await toastIn('R', /moved/), '5: undo offered');
    await undoIn('R');
    check(await poll(async () => (await parent()) === FA), '5: undo moves it back');
    await shot('p2760a-xdrag.png');

    // ---- refusals (drops in the left half that did not start there): a payload without this origin's token does nothing;
    // things alice may not see end in a toast, nothing changes
    await load('#l/' + L1);
    await until(`!!document.querySelector('#side .srow[data-drop="l:${L2}"]')`);
    const tok = await ev(`localStorage.getItem('kalmido.xd')`);
    check(!!tok, 'the origin token is in localStorage');
    const f1 = await drag(null, null, 'L', `#side .srow[data-drop="l:${L2}"]`, {k: 't:' + T1, o: 'not-this-app', w: 'x'});
    check(f1.over, 'a forged drag is still hovered (the data is read only at the drop) ' + JSON.stringify(f1));
    await drag(null, null, 'L', `#side .srow[data-drop="l:${L2}"]`, {k: 't:' + TB, o: tok, w: 'x'});
    check(await toastIn('L', /Task not found/), 'a task alice may not see: a toast');
    check((await task(T1)).list_id === L1, 'the forged drag (no token of this origin) moved nothing');
    check((await call('GET', `/api/tasks/${TB}`, null, CB)).list_id === LB, 'bob\'s task stays where it is');
    check(await right('#ablage/' + FO, `#view .abview[data-abzone="${FO}"]`), 'the right half shows the folder again');
    await drag(null, null, 'R', `#view .abview[data-abzone="${FO}"]`, {k: 'f:' + FB, o: tok, w: 'x'});
    check(await toastIn('R', /No access/), 'a file alice may not see: a toast "No access"');
    check((await call('GET', `/api/files/nodes/${FB}`, null, CB)).parent_id === FBF, 'bob\'s file stays where it is');
  }, false);

  console.log(`p2760_a_xdrag: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERR', e); process.exit(1); });
