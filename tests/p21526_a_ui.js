// 2.152.6 (#2709) UI tests: the subtask arrow on a phone. Own container (start.sh), Firefox. Invented people only.
// freelancer-matrix: tasks (the person, carol, has no organisation)
// - phone (390 px, touch): the circle of a task with subtasks lines up with the circle of a plain task (no extra space
//   on the left), the arrow sits right of the circle and before the title, away from the screen edge; the subtasks stay
//   indented; a tap on the circle hits the circle, a tap on the arrow folds the subtasks
// - computer (1280 px, mouse): unchanged, the arrow stays left of the circle, the circles line up
// P21526A_NOSTART=1 = the server already runs. Screenshots: P21526A_SHOTS (kalmido-mactest.sh shot p21526_a_ui).
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21526_a_ui', check, shots: 'P21526A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21526A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => {
  for (let i = 0; ; i++) {
    const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined});
    if (r.status === 429 && i < 8) { await sleep(500 * (i + 1)); continue; }
    const j = await r.json().catch(() => ({})); return {...j, http: r.status};
  }
};

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call(CA, 'POST', '/api/users', {username: 'carol', display_name: 'Carol Solo', password: 'password123', email: 'carol@example.com'});
  const CC = await login('carol');
  await call(CC, 'PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  check(!((await call(CC, 'GET', '/api/state')).me.workspaces || []).length, 'P4: carol has no organisation');
  const L = (await call(CC, 'POST', '/api/lists', {name: 'Groceries'})).id;
  const P = (await call(CC, 'POST', '/api/tasks', {title: 'Weekly shop', list_id: L})).id;
  await call(CC, 'POST', '/api/tasks', {title: 'Milk', list_id: L, parent_id: P});
  await call(CC, 'POST', '/api/tasks', {title: 'Bread', list_id: L, parent_id: P});
  const T = (await call(CC, 'POST', '/api/tasks', {title: 'Return the bottles', list_id: L})).id;
  check(L > 0 && P > 0 && T > 0, 'a list with a parent task, two subtasks and a plain task');

  const ready = async (ev, expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = ev => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'carol', password: 'password123'})}).then(r => r.status)`);
  // the boxes of a row: circle, arrow, title
  const geo = ev => ev(`(() => { const box = (id, sel) => { const e = document.querySelector('#view .trow[data-id="' + id + '"] > ' + sel); if (!e) return null; const b = e.getBoundingClientRect(); return {l: b.left, r: b.right, t: b.top, b: b.bottom}; };
    const sub = [...document.querySelectorAll('#view .trow.sub')][0];
    return {pc: box(${P}, '.chk'), pa: box(${P}, '.caret'), pt: box(${P}, '.tmain'), tc: box(${T}, '.chk'), sc: sub ? (b => ({l: b.left}))(sub.querySelector('.chk').getBoundingClientRect()) : null}; })()`);
  const view = async (ev, nav, w, h) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await signIn(ev) === 200, `${w} px: carol signs in`);
    await nav(B + '#l/' + L);
    return ready(ev, `!!document.querySelector('#view .trow[data-id="${P}"] > .caret') && document.querySelectorAll('#view .trow.sub').length === 2`);
  };

  // ================= phone: 390 px, touch
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    check(await view(ev, nav, 390), '390 px: the list shows the parent with its arrow and both subtasks');
    const g = await geo(ev);
    check(g.pc && g.tc && Math.abs(g.pc.l - g.tc.l) < 1, '390 px: the circle of the parent lines up with the plain task ' + JSON.stringify([g.pc, g.tc]));
    check(g.pa && g.pa.l >= g.pc.r && g.pa.r <= g.pt.l + 1, '390 px: the arrow sits right of the circle, before the title ' + JSON.stringify([g.pc, g.pa, g.pt]));
    check(g.pa && g.pa.l >= 16, '390 px: the arrow keeps clear of the screen edge ' + JSON.stringify(g.pa));
    check(g.sc && g.sc.l > g.pc.l + 8, '390 px: the subtasks stay indented ' + JSON.stringify([g.sc, g.pc]));
    const hit = await ev(`(() => { const row = document.querySelector('#view .trow[data-id="${P}"]'), c = row.querySelector(':scope > .chk').getBoundingClientRect(), a = row.querySelector(':scope > .caret').getBoundingClientRect();
      const at = (x, y) => document.elementFromPoint(x, y); return {chk: !!at(c.left + c.width / 2, c.top + c.height / 2)?.closest('.chk'), chkR: !!at(c.right - 1, c.top + c.height / 2)?.closest('.chk'), caret: !!at(a.left + a.width / 2, a.top + a.height / 2)?.closest('.caret')}; })()`);
    check(hit.chk && hit.chkR, '390 px: a tap on the circle (also its right edge) hits the circle ' + JSON.stringify(hit));
    check(hit.caret, '390 px: a tap on the arrow hits the arrow ' + JSON.stringify(hit));
    await shot('phone-390');
    await ev(`(() => { const a = document.querySelector('#view .trow[data-id="${P}"] > .caret').getBoundingClientRect(); document.elementFromPoint(a.left + a.width / 2, a.top + a.height / 2).closest('.caret').click(); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('#view .trow.sub').length === 0 && document.querySelector('#view .trow[data-id="${P}"] > .caret')?.getAttribute('aria-expanded') === 'false'`, 20), '390 px: the arrow folds the subtasks');
  }, true);

  // ================= computer: 1280 px, mouse - unchanged
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    check(await view(ev, nav, 1280), '1280 px: the list shows the parent with its arrow and both subtasks');
    const g = await geo(ev);
    check(g.pc && g.tc && Math.abs(g.pc.l - g.tc.l) < 1, '1280 px: the circles line up ' + JSON.stringify([g.pc, g.tc]));
    check(g.pa && g.pa.r <= g.pc.l + 1, '1280 px: the arrow stays left of the circle ' + JSON.stringify([g.pa, g.pc]));
    await shot('computer-1280');
  }, false);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
