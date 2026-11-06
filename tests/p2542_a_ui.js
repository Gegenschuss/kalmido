// kalmido-suite: fresh
// 2.542.0 A UI tests, own container (start.sh). jsdom + Firefox (tablet width):
// #4579 Start: a tap on a task of Start opens its panel over Start (the view stays Start, no empty project view, the
//      sidebar does not jump to Projects); a Start row shows its subtasks done / all (like taskRow); ticking a task with
//      open subtasks (all levels) asks first "N open subtasks left. Complete them all?" (Complete all / Cancel; a
//      recurring task has its own text), Cancel changes nothing, Complete all ticks it with its subtasks; the multi-select
//      asks once for all selected tasks
// #4609 a locked task: tick / x / multi-select do not complete it and do not reopen it - the hint names the lock and
//      offers "Unlock" (before the subtask question); after unlocking it completes; the selection skips it with a note
// freelancer-matrix: tasks - frida has no organisation: the lock hint and the subtask question work there too.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2542_a_ui', check, shots: 'P2542A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const until = async (f, ms = 8000) => { for (let t = 0; t < ms; t += 100) { const v = await f(); if (v) return v; await sleep(100); } return f(); };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const srv = async (ck, id) => (await call(ck, 'GET', `/api/tasks/${id}`));
  const dlg = d => d.querySelector('.modal.cdlg');
  const dlgText = d => dlg(d)?.querySelector('#cdlg-t')?.textContent || '';
  const toastTxt = d => d.querySelector('#toast:not(.hidden)')?.textContent || '';

  let w = await boot({user: 'alice', hash: 'home'}), d = w.document;
  await until(() => d.querySelector('#view .dc-today'));
  const t0 = w.eval('today()');
  const L = (await call(CA, 'POST', '/api/lists', {name: 'Garden'})).id;
  const mk = async (ck, title, extra = {}) => (await call(ck, 'POST', '/api/tasks', {title, list_id: L, ...extra})).id;
  const P = await mk(CA, 'Plant the beds', {due: t0});
  const K1 = await mk(CA, 'Buy seeds', {parent_id: P});
  const K2 = await mk(CA, 'Dig', {parent_id: P});
  const K3 = await mk(CA, 'Rake the soil', {parent_id: K2});  // a second level
  await call(CA, 'POST', `/api/tasks/${K1}/complete`, {});
  const RP = await mk(CA, 'Water the plants', {due: t0, repeat: 'FREQ=WEEKLY'});
  await mk(CA, 'Fill the can', {parent_id: RP});
  const TL = await mk(CA, 'Release notes', {due: t0});
  await call(CA, 'PATCH', `/api/tasks/${TL}`, {locked: 1});
  await mk(CA, 'Locked kid', {parent_id: TL});
  const M1 = await mk(CA, 'Mow', {due: t0}), M2 = await mk(CA, 'Trim', {due: t0});
  await mk(CA, 'Oil the mower', {parent_id: M1}); await mk(CA, 'Sharpen', {parent_id: M2}); await mk(CA, 'Clean', {parent_id: M2});
  await w.eval('load()'); w.eval('renderView()');
  await until(() => d.querySelector(`#view .dc-today [data-id="${P}"]`));

  // ---- #4579 (2): the counter in the Start row
  const rowOf = id => d.querySelector(`#view .dc-today [data-id="${id}"]`)?.closest('li');
  check(rowOf(P)?.querySelector('.subc')?.textContent.startsWith('1/2'), '#4579: the Start row shows subtasks done / all (1/2) ' + rowOf(P)?.querySelector('.subc')?.textContent);
  check(!rowOf(M1)?.querySelector('.subc') || rowOf(M1).querySelector('.subc').textContent.startsWith('0/1'), '#4579: 0/1 for a task with one open subtask');

  // ---- #4579 (1): a tap on the title opens the panel over Start
  w.location.hash = '#t/' + P;
  await until(() => w.eval('S.sel') === P);
  await sleep(200);
  check(w.eval('S.sel') === P && !d.querySelector('#detail').classList.contains('hidden'), '#4579: the task panel opens');
  check(w.eval('S.route.mod') === 'home' && d.querySelector('#view .dc-today') && !/No tasks\./.test(d.querySelector('#view').textContent),
    '#4579: the view stays Start (no empty project view) ' + w.eval('JSON.stringify(S.route)'));
  check(w.location.hash === '#home', '#4579: the address goes back to #home ' + w.location.hash);
  w.eval('closeDetail()'); await sleep(200);

  // ---- #4579 (3): the question before ticking a task with open subtasks
  rowOf(P).querySelector('[data-act="toggle"]').click();
  await until(() => dlg(d));
  check(/^2 open subtasks left\. Complete them all\?$/.test(dlgText(d)), '#4579: "2 open subtasks left. Complete them all?" (all levels) ' + dlgText(d));
  check(dlg(d)?.querySelector('[data-cd="yes"]')?.textContent === 'Complete all' && dlg(d)?.querySelector('[data-cd="no"]')?.textContent === 'Cancel', '#4579: Complete all / Cancel');
  dlg(d).querySelector('[data-cd="no"]').click();
  await sleep(500);
  check((await srv(CA, P)).status === 0, '#4579: Cancel: the task stays open');
  check(!d.querySelector(`.trow[data-id="${P}"] .chk.on`) && !rowOf(P)?.querySelector('.chk.on'), '#4579: Cancel: the tick is not shown');
  w.eval(`toggleTask(${P})`);
  await until(() => dlg(d));
  dlg(d).querySelector('[data-cd="yes"]').click();
  await until(async () => (await srv(CA, K3)).status === 2);
  check((await srv(CA, P)).status === 2 && (await srv(CA, K2)).status === 2 && (await srv(CA, K3)).status === 2, '#4579: Complete all: the task and its subtasks (all levels) are done');
  // a recurring task: its own text
  w.eval(`toggleTask(${RP})`);
  await until(() => dlg(d));
  check(/^1 open subtask left\. It will be open again at the next occurrence; here it counts as not done\. Complete anyway\?$/.test(dlgText(d)), '#4579: the recurring text ' + dlgText(d));
  check(dlg(d)?.querySelector('[data-cd="yes"]')?.textContent === 'Complete anyway', '#4579: recurring: "Complete anyway"');
  dlg(d).querySelector('[data-cd="no"]').click(); await sleep(300);
  // the selection: one question for all
  w.eval(`batch('complete', {}, true, [${M1}, ${M2}])`);
  await until(() => dlg(d));
  check(/^3 open subtasks left\./.test(dlgText(d)) && d.querySelectorAll('.modal.cdlg').length === 1, '#4579: multi-select: one question with all open subtasks ' + dlgText(d));
  dlg(d).querySelector('[data-cd="yes"]').click();
  await until(async () => (await srv(CA, M2)).status === 2);
  check((await srv(CA, M1)).status === 2 && (await srv(CA, M2)).status === 2, '#4579: multi-select: both completed after the yes');

  // ---- #4609: the lock
  await w.eval('load()'); w.eval('renderView()'); await sleep(200);
  w.eval(`toggleTask(${TL})`); await sleep(400);
  check(!dlg(d), '#4609: a locked task: no subtask question (the lock comes first)');
  check(/This task is locked\. Unlock it to complete or reopen it\./.test(toastTxt(d)) && /Unlock/.test(d.querySelector('#toast button')?.textContent || ''),
    '#4609: the hint names the lock and offers Unlock ' + toastTxt(d));
  check((await srv(CA, TL)).status === 0, '#4609: the locked task stays open');
  // the selection skips it
  const O = await mk(CA, 'Sweep the path', {due: t0});
  await w.eval('load()');
  w.eval(`batch('complete', {}, true, [${TL}, ${O}])`);
  await until(async () => (await srv(CA, O)).status === 2);
  await sleep(300);
  check((await srv(CA, TL)).status === 0 && (await srv(CA, O)).status === 2 && /1 locked task skipped/.test(toastTxt(d)), '#4609: multi-select skips the locked task with a note ' + toastTxt(d));
  w.eval(`batch('complete', {}, true, [${TL}])`); await sleep(400);
  check(/locked/.test(toastTxt(d)) && (await srv(CA, TL)).status === 0, '#4609: a selection of only locked tasks: the hint, nothing sent');
  // Unlock from the hint, then it completes
  w.eval(`toggleTask(${TL})`); await until(() => /locked/.test(toastTxt(d)));
  d.querySelector('#toast button')?.click();
  await until(async () => (await srv(CA, TL)).locked === 0);
  check((await srv(CA, TL)).locked === 0, '#4609: "Unlock" in the hint unlocks it');
  await until(() => w.eval(`taskById(${TL})?.locked`) === 0);
  w.eval(`toggleTask(${TL})`);
  await until(() => dlg(d));
  check(/^1 open subtask left\. Complete it too\?$/.test(dlgText(d)), '#4579 after #4609: unlocked, the subtask question comes ' + dlgText(d));
  dlg(d).querySelector('[data-cd="yes"]').click();
  await until(async () => (await srv(CA, TL)).status === 2);
  check((await srv(CA, TL)).status === 2, '#4609: unlocked: it completes');
  // reopening a done locked task: the hint, it stays done
  await call(CA, 'PATCH', `/api/tasks/${TL}`, {locked: 1});
  await w.eval('load()'); await until(() => w.eval(`taskById(${TL})?.locked`) === 1);
  w.eval(`toggleTask(${TL})`); await sleep(500);
  check(/locked/.test(toastTxt(d)) && (await srv(CA, TL)).status === 2, '#4609: a done locked task is not reopened (hint)');
  w.close();

  // ---- a person without an organisation
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  check(fu.http < 300 && ((await call(CF, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'frida: no organisation');
  const FL = (await call(CF, 'POST', '/api/lists', {name: 'Solo'})).id;
  const FT = (await call(CF, 'POST', '/api/tasks', {title: 'Invoice the client', list_id: FL})).id;
  await call(CF, 'POST', '/api/tasks', {title: 'Check the hours', parent_id: FT});
  const FK = (await call(CF, 'POST', '/api/tasks', {title: 'Tax return', list_id: FL})).id;
  await call(CF, 'PATCH', `/api/tasks/${FK}`, {locked: 1});
  w = await boot({user: 'frida', hash: 'l/' + FL}); d = w.document;
  await until(() => d.querySelector(`#view .trow[data-id="${FT}"]`));
  d.querySelector(`#view .trow[data-id="${FT}"] .chk`)?.click();
  await until(() => dlg(d));
  check(/^1 open subtask left\./.test(dlgText(d)), 'frida: the subtask question on the row tick ' + dlgText(d));
  dlg(d).querySelector('[data-cd="no"]').click(); await sleep(300);
  w.eval(`toggleTask(${FK})`); await sleep(400);
  check(/locked/.test(toastTxt(d)) && (await srv(CF, FK)).status === 0, 'frida: the lock hint, the task stays open');
  w.close();

  // ================= Firefox, tablet width (1024 x 768, touch): the panel over Start
  const S2 = await mk(CA, 'Order the compost', {due: t0});
  await mk(CA, 'Compare prices', {parent_id: S2});
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o;
    await o.nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); localStorage.setItem('tasks.chatFloat', '"0"'); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'tablet: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1024, height: 768}});
    await o.nav(B + '#home');
    await o.until(`!!document.querySelector('#view .dc-today [data-id="${S2}"]')`);
    check(await ev(`(document.querySelector('#view .dc-today [data-id="${S2}"]')?.closest('li')?.querySelector('.subc')?.textContent || '').startsWith('0/1')`), 'tablet: the Start row shows 0/1');
    await shot('p2542a-tablet-start.png');
    const sideAt = () => ev(`[...document.querySelectorAll('#side [aria-current="page"]')].map(b => b.dataset.sbb || b.dataset.go || '').join(',')`);
    const side0 = await sideAt();
    await ev(`(() => { document.querySelector('#view .dc-today [data-id="${S2}"]').closest('li').querySelector('a.dtt').click(); return 1; })()`);
    await o.until(`S.sel === ${S2} && document.querySelector('#detail.open') !== null`);
    const st = await ev(`({mod: S.route.mod, start: !!document.querySelector('#view .dc-today'), empty: /No tasks\\./.test(document.querySelector('#view').textContent),
      hash: location.hash, det: !!document.querySelector('#detail.open')})`);
    check(st.mod === 'home' && st.start && !st.empty && st.det && st.hash === '#home', 'tablet: the panel opens beside / over Start, Start stays ' + JSON.stringify(st));
    const side1 = await sideAt();
    check(side1 === side0, 'tablet: the sidebar does not jump (to Projects) ' + side0 + ' -> ' + side1);
    await shot('p2542a-tablet-detail.png');
  }, true);

  console.log(`p2542_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
