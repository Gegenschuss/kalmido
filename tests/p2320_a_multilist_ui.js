// 2.320.0 UI tests (#3289 "several projects easier to use"), own container (start.sh). jsdom:
// kalmido-suite:
// - the task panel's field "Projects": its own project fixed (no x), the further ones with x, + opens the project picker with
//   the rules of ml_okTarget (same workspace only, not its own); picking adds it, x removes it (one undo step); a subtask
//   has no field; at 10 further projects the + is gone; the same field on a phone
// - Alt (Option) held while dropping onto a project in the sidebar = show also there (the task stays in its own project);
//   while dragging the project says "Also show in Marketing", without Alt "Alt: also show here", a project of another
//   workspace "Not possible for this project" (no drop); a selection dragged with Alt counts the tasks that may; without Alt
//   the sidebar still moves
// - a selection: "Show also in project…" in the multi panel (desktop) and the phone's More menu; the main tasks that may are
//   added in one undo step, the others skipped and counted (subtask, other workspace, already 10 further, already there)
// Firefox 1440 mouse / 390 touch: the field fits, the x is a real target (>= 24 px); screenshots with P2320A_SHOTS=<dir>.
// kalmido-suite: fresh
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2320_a_multilist_ui', check, shots: 'P2320A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const toastText = d => d.querySelector('#toast:not(.hidden)')?.textContent || '';
const items = d => [...d.querySelectorAll('#pop [role="menuitem"]')];
const also = async id => ((await call('GET', `/api/tasks/${id}`)).also || []).map(a => a.list_id).sort((a, b) => a - b);
// a synthetic drag event (jsdom has no DataTransfer); o: altKey
const dnd = (w, el, type, o = {}) => { const e = new w.Event(type, {bubbles: true, cancelable: true}); e.dataTransfer = {setData() {}, getData: () => '', effectAllowed: '', dropEffect: '', setDragImage() {}}; e.clientY = 10; e.altKey = !!o.altKey; el.dispatchEvent(e); return e; };
const FEAT = 'cal,comments,collab';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Example', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  const SALES = (await call('POST', '/api/lists', {name: 'Sales', org_id: ORG})).id;
  const MKT = (await call('POST', '/api/lists', {name: 'Marketing', org_id: ORG})).id;
  const OPS = (await call('POST', '/api/lists', {name: 'Ops', org_id: ORG})).id;
  const PRIV = (await call('POST', '/api/lists', {name: 'Private notes', org_id: null})).id;
  const MORE = [];
  for (let i = 1; i <= 10; i++) MORE.push((await call('POST', '/api/lists', {name: 'Area ' + i, org_id: ORG})).id);
  const mk = async (title, list_id, extra = {}) => (await call('POST', '/api/tasks', {title, list_id, ...extra})).id;
  const T = await mk('Launch flyer', SALES), T2 = await mk('Trade fair', SALES), FULL = await mk('Everywhere', SALES), T4 = await mk('Move me', SALES);
  const SUB = await mk('Print it', SALES, {parent_id: T}), PT = await mk('Own idea', PRIV);
  for (const l of MORE) await call('POST', `/api/tasks/${FULL}/links`, {list_id: l});
  check((await also(FULL)).length === 10, 'setup: Everywhere is in 10 further projects');
  const HINTS = {hintsSeen: ['dgalt', 'dgmulti']};

  // ================= the field "Projects" in the task panel
  let w = await boot({user: 'alice', hash: 'l/' + SALES, ls: HINTS}), d = w.document;
  await until(() => d.querySelector(`.trow[data-id="${T}"]`));
  w.eval(`openDetail(${T})`); await sleep(200);
  let f = await until(() => d.querySelector('#detail .dmlp'));
  check(f, '#3289: the task panel has the field Projects');
  check(/Projects/.test(f?.querySelector('.dmlpk')?.textContent || ''), '#3289: labelled "Projects"');
  check(/Sales/.test(f?.querySelector('.mlp.own')?.textContent || '') && !f?.querySelector('.mlp.own .mlpx'), '#3289: its own project, fixed (no x)');
  check(/Also in…/.test(f?.querySelector('.mlpadd')?.textContent || ''), '#3289: + "Also in…" while there is no further project');
  click(w, f.querySelector('.mlpadd')); await sleep(150);
  const offered = items(d).map(x => x.textContent.trim());
  check(offered.includes('Marketing') && offered.includes('Ops') && !offered.includes('Private notes') && !offered.includes('Sales'),
    '#3289: + offers the projects of the same workspace, not its own, not the private one ' + JSON.stringify(offered));
  click(w, items(d).find(x => x.textContent.trim() === 'Marketing'));
  check(await until(async () => (await also(T)).join() === String(MKT)), '#3289: picking Marketing shows the task also there');
  check((await call('GET', `/api/tasks/${T}`)).list_id === SALES, '#3289: its own project stays Sales');
  f = await until(() => { const x = d.querySelector('#detail .dmlp'); return x && x.querySelector('.mlpx') && x; });
  check(/Marketing/.test(f?.textContent || '') && f?.querySelector(`.mlpx[data-lid="${MKT}"]`), '#3289: the field lists Marketing with an x');
  check(f && !/Also in…/.test(f.querySelector('.mlpadd')?.textContent || 'x'), '#3289: the + is only the sign once there is a further project');
  click(w, f.querySelector(`.mlpx[data-lid="${MKT}"]`));
  check(await until(async () => !(await also(T)).length), '#3289: x removes Marketing (the task stays)');
  check(await until(() => /Removed from Marketing/.test(toastText(d))), '#3289: the message offers Undo: ' + toastText(d));
  await w.eval(`histStep('undo')`);
  check(await until(async () => (await also(T)).join() === String(MKT)), '#3289: undo brings Marketing back');
  // a subtask: no field; 10 further projects: no +
  w.eval(`openDetail(${SUB})`); await sleep(200);
  check(!d.querySelector('#detail .dmlp'), '#3289: a subtask has no field Projects');
  w.eval(`openDetail(${FULL})`); await sleep(200);
  f = await until(() => d.querySelector('#detail .dmlp'));
  check(f && f.querySelectorAll('.mlp').length === 11 && !f.querySelector('.mlpadd'), '#3289: 10 further projects: all listed, no + ' + f?.querySelectorAll('.mlp').length);
  check(w.eval(`ml_why(taskById(${FULL}), listById(${MKT}))`) === 'Already in 10 further projects', '#3289: the reason names the limit');
  w.eval('closeDetail()'); await sleep(100);

  // ================= Alt onto a project in the sidebar
  const row = id => d.querySelector(`#view .trow[data-id="${id}"]`), side = lid => d.querySelector(`.srow[data-drop="l:${lid}"]`);
  check(side(MKT) && side(PRIV), 'the sidebar lists Marketing and Private notes');
  dnd(w, row(T2), 'dragstart'); await sleep(50);
  let ov = dnd(w, side(MKT), 'dragover');
  check(side(MKT).classList.contains('mlhint') && /Alt: also show here/.test(side(MKT).dataset.ml || ''), '#3289: without Alt the project says "Alt: also show here"');
  ov = dnd(w, side(MKT), 'dragover', {altKey: true});
  check(ov.defaultPrevented && side(MKT).classList.contains('mlalt') && side(MKT).dataset.ml === 'Also show in Marketing' && !side(MKT).classList.contains('drop'),
    '#3289: with Alt: "Also show in Marketing" ' + side(MKT).dataset.ml);
  ov = dnd(w, side(PRIV), 'dragover', {altKey: true});
  check(!ov.defaultPrevented && side(PRIV).classList.contains('mlno') && /Not possible for this project/.test(side(PRIV).dataset.ml || '') && !side(MKT).classList.contains('mlalt'),
    '#3289: another workspace: "Not possible for this project", no drop ' + side(PRIV).dataset.ml);
  dnd(w, side(MKT), 'dragover', {altKey: true});
  dnd(w, side(MKT), 'drop', {altKey: true}); dnd(w, row(T2), 'dragend');
  check(await until(async () => (await also(T2)).join() === String(MKT)), '#3289: Alt-drop: Trade fair is also in Marketing');
  check((await call('GET', `/api/tasks/${T2}`)).list_id === SALES, '#3289: Alt-drop does not move it');
  check(await until(() => /Trade fair.*is now also in Marketing/.test(toastText(d))), '#3289: the message: ' + toastText(d));
  check(!d.querySelector('.mlalt,.mlno,.mlhint,.dragging'), '#3289: no mark left after the drop');
  await w.eval(`histStep('undo')`);
  check(await until(async () => !(await also(T2)).length), '#3289: one undo takes it out of Marketing again');
  // without Alt the sidebar still moves
  dnd(w, row(T4), 'dragstart'); await sleep(50);
  dnd(w, side(OPS), 'dragover'); dnd(w, side(OPS), 'drop'); dnd(w, row(T4), 'dragend');
  check(await until(async () => (await call('GET', `/api/tasks/${T4}`)).list_id === OPS), '#3289: a drop without Alt still moves the task');
  // a selection dragged with Alt: the main tasks that may are counted
  await w.eval('load().then(render)'); await sleep(300);
  w.eval(`S.multi.clear(); [${T2}, ${SUB}, ${FULL}].forEach(i => S.multi.add(i)); render()`); await sleep(150);
  dnd(w, row(T2), 'dragstart'); await sleep(50);
  dnd(w, side(OPS), 'dragover', {altKey: true});
  check(side(OPS).dataset.ml === '1 task also in Ops', '#3289: a selection: "1 task also in Ops" (subtask and the full one do not count) ' + side(OPS).dataset.ml);
  dnd(w, row(T2), 'dragend');
  check(!d.querySelector('.mlalt'), '#3289: dragend clears the mark');
  w.eval('S.multi.clear(); render()');
  w.close();

  // ================= a selection: "Show also in project…" (desktop multi panel)
  w = await boot({user: 'alice', hash: 'l/' + SALES, ls: HINTS}); d = w.document;
  await until(() => d.querySelector(`.trow[data-id="${T}"]`));
  w.eval(`[${T}, ${T2}, ${SUB}, ${FULL}, ${PT}].forEach(i => S.multi.add(i)); render()`); await sleep(200);
  const mb = await until(() => d.querySelector('#detail [data-act="ml-multi"]'));
  check(mb && /Show also in project…/.test(mb.textContent), '#3289: the multi panel offers "Show also in project…"');
  click(w, mb); await sleep(150);
  const offered2 = items(d).map(x => x.textContent.trim());
  check(offered2.includes('Marketing') && offered2.includes('Area 1') && !offered2.includes('Private notes') && !offered2.includes('Sales'),
    '#3289: the picker offers the projects at least one selected task may go to ' + JSON.stringify(offered2));
  click(w, items(d).find(x => x.textContent.trim() === 'Marketing'));
  check(await until(async () => (await also(T2)).join() === String(MKT)), '#3289: Trade fair is now also in Marketing');
  check((await also(SUB)).length === 0 && (await also(PT)).length === 0 && (await also(FULL)).length === 10, '#3289: subtask, other workspace and the full one are skipped');
  check(await until(() => /1 task is now also in Marketing · 1 already there · 3 skipped \(not possible there\)/.test(toastText(d))), '#3289: counted in the message: ' + toastText(d));
  await w.eval(`histStep('undo')`);
  check(await until(async () => !(await also(T2)).length), '#3289: one undo for the selection');
  check((await also(T)).join() === String(MKT), '#3289: the undo leaves the link that was there before');
  w.close();

  // ================= phone: the field and the selection's More menu
  w = await boot({user: 'alice', mobile: true, hash: 'l/' + SALES, ls: HINTS}); d = w.document;
  await until(() => d.querySelector(`.trow[data-id="${T}"]`));
  w.eval(`openDetail(${T})`); await sleep(300);
  f = await until(() => d.querySelector('#detail .dmlp'));
  check(f && /Sales/.test(f.querySelector('.mlp.own')?.textContent || '') && f.querySelector(`.mlpx[data-lid="${MKT}"]`) && f.querySelector('.mlpadd'), '#3289: phone: the same field');
  w.eval('closeDetail()'); await sleep(100);
  w.eval(`S.multiMode = true; [${T2}, ${SUB}].forEach(i => S.multi.add(i)); render(); multiMoreMenu(document.querySelector('#mbar [data-act="mb-menu"]') || document.body)`); await sleep(150);
  check(items(d).some(x => /Show also in project…/.test(x.textContent)), '#3289: phone: More offers "Show also in project…" ' + JSON.stringify(items(d).map(x => x.textContent.trim())));
  w.eval(`closePop(); S.multi.clear(); S.multi.add(${SUB}); render()`);
  check(w.eval('ml_multiItems([...S.multi], document.body).length') === 0, '#3289: only subtasks selected: no entry');
  w.close();

  // ================= Firefox: the field on a desktop and a phone
  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1, .agview')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  const geo = `(() => { const f = document.querySelector('#detail .dmlp'); if (!f) return null; const x = f.querySelector('.mlpx').getBoundingClientRect(), r = f.getBoundingClientRect(), d = document.querySelector('#detail').getBoundingClientRect();
    return {fits: r.right <= d.right + 1 && r.left >= d.left - 1, xw: x.width, xh: x.height, wide: document.documentElement.scrollWidth <= innerWidth}; })()`;
  for (const [W, H2, touch] of [[1440, 900, false], [390, 844, true]]) {
    await firefox(async o => {
      const {cmd, ev, ctx, shot} = o, tag = String(W);
      check(await ffLogin(o) === 200, tag + ': login');
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: W, height: H2}});
      await o.nav(B + '#l/' + SALES); await ready(ev);
      await ev(`openDetail(${T})`); await sleep(800);
      const g = await ev(geo);
      check(g && g.fits && g.wide && g.xw >= 24 && g.xh >= 24, `${tag}: #3289 the field fits the panel, the x is >= 24 px ` + JSON.stringify(g));
      await shot(`p2320a-${tag}-projects.png`);
    }, touch);
  }

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
