// 2.60.0 UI tests (part C), own container (start.sh). jsdom:
// #1512 the review step: the list setting (Review step, default reviewer, Done only after approval) saves at once and is
//       one undo step; the task panel shows the reviewer bar (Waiting for the approval of ...); the reviewer sees
//       Approve / Back, the assignee does not; ticking off a waiting task explains it (Waiting for approval by ...) and
//       "Send for review" sends it; Approve -> Approved, one undo step back to pending; the reviewer reads the News item;
//       the notification settings have the row Reviews
// Firefox 390 touch: the reviewer bar fits the phone, Approve >= 36 px, screenshot.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p260_c_ui', check, shots: 'P260C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el, o = {}) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const FEAT = 'cal,comments,collab,agents';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const bob = await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  const carol = await call('POST', '/api/users', {username: 'carol', display_name: 'Carol', password: 'password123', email: 'carol@example.com'});
  const CB = await login('bob'), CC = await login('carol');
  for (const ck of [CB, CC]) await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, ck);
  const P = (await call('POST', '/api/lists', {name: 'App', kind: 'project'})).id;
  for (const u of [bob, carol]) await call('PUT', `/api/lists/${P}/members`, {user_id: u.id, role: 'edit'});
  const S1 = (await call('POST', '/api/sections', {list_id: P, name: 'In progress'})).id;
  const S2 = (await call('POST', '/api/sections', {list_id: P, name: 'Review'})).id;
  const T1 = (await call('POST', '/api/tasks', {title: 'Login form', list_id: P, section_id: S1, assignee_id: bob.id}, CB)).id;
  void S2;

  // ================= the list setting (alice, the owner)
  let w = await boot({user: 'alice'}), d = w.document;
  w.eval(`listModal(${P})`); await until(() => d.querySelector('#l-rvw'));
  check(d.querySelector('#l-rvw') && !d.querySelector('#l-rvw').checked, '#1512: the list dialog has "Review step", off');
  check(d.querySelector('.lrvwx')?.hidden, '#1512: its details are hidden while off');
  d.querySelector('#l-rvw').checked = true; d.querySelector('#l-rvw').dispatchEvent(new w.Event('change', {bubbles: true}));
  await until(async () => (await call('GET', '/api/state')).lists.find(x => x.id === P)?.review_cfg);
  check(!d.querySelector('.lrvwx').hidden, '#1512: on: reviewer, section and gate show');
  const sel = d.querySelector('#l-rvw-who');
  check([...sel.options].some(o => +o.value === carol.id), '#1512: the default reviewer is one of the list people');
  sel.value = String(carol.id); sel.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(300);
  d.querySelector('#l-rvw-gate').checked = true; d.querySelector('#l-rvw-gate').dispatchEvent(new w.Event('change', {bubbles: true}));
  const cfg = await until(async () => { const l = (await call('GET', '/api/state')).lists.find(x => x.id === P); const c = l?.review_cfg ? JSON.parse(l.review_cfg) : {}; return c.gate ? c : null; });
  check(cfg && cfg.reviewer === carol.id && cfg.gate === 1, '#1512: saved at once: reviewer carol, gate on ' + JSON.stringify(cfg));
  await w.eval(`histStep('undo')`); await sleep(400);
  let c2 = JSON.parse((await call('GET', '/api/state')).lists.find(x => x.id === P).review_cfg || '{}');
  check(c2.on && !c2.gate, '#1512: one undo step takes the gate back ' + JSON.stringify(c2));
  await w.eval(`histStep('redo')`); await sleep(400);
  c2 = JSON.parse((await call('GET', '/api/state')).lists.find(x => x.id === P).review_cfg || '{}');
  check(c2.gate === 1, '#1512: redo');
  w.close();

  // ================= bob (assignee): the bar, the tick explains the gate, "Send for review"
  await call('POST', `/api/tasks/${T1}/review`, {action: 'reviewer', reviewer_id: carol.id}, CB);
  w = await boot({user: 'bob'}); d = w.document;
  w.eval(`openDetail(${T1})`); await until(() => d.querySelector('#detail .rvwbar'));
  const bar = () => d.querySelector('#detail .rvwbar');
  check(/Reviewer: Carol/.test(bar()?.textContent || ''), '#1512: the bar names the reviewer ' + (bar()?.textContent || ''));
  check(!bar()?.querySelector('[data-rvw="approve"]'), '#1512: the assignee has no Approve');
  w.eval(`toggleTask(${T1})`); await until(() => d.querySelector('.cdlg'));
  check(/Waiting for approval by Carol/.test(d.querySelector('.cdlg')?.textContent || ''), '#1512: the tick explains the gate');
  check((await call('GET', `/api/tasks/${T1}`, null, CB)).status === 0, '#1512: the task stays open');
  click(w, d.querySelector('.cdlg [data-cd="yes"]'));
  const t1 = await until(async () => { const t = await call('GET', `/api/tasks/${T1}`, null, CB); return t.review === 'pending' ? t : null; });
  check(t1 && t1.section_id === S2, '#1512: Send for review: pending, in the Review section');
  await until(() => /Waiting for the approval of Carol/.test(bar()?.textContent || ''));
  check(/Waiting for the approval of Carol/.test(bar()?.textContent || ''), '#1512: the bar shows pending');
  const st = await call('POST', `/api/tasks/${T1}/complete`, {}, CB);
  check(st.status === 409, '#1512: the server refuses the tick with 409');
  w.close();

  // ================= carol (reviewer): News, Approve, undo
  w = await boot({user: 'carol', hash: 'news'}); d = w.document; await sleep(600);
  check(/Bob asks you to review .*Login form/.test(d.body.textContent), '#1512: carol reads the News item');
  w.eval(`openDetail(${T1})`); await until(() => d.querySelector('#detail .rvwbar [data-rvw="approve"]'));
  check(d.querySelector('#detail .rvwbar [data-rvw="changes"]'), '#1512: the reviewer has Approve and Back');
  check(d.querySelector('#detail .rvwbar [data-rvw="approve"] .thumb'), '#1512: thumbs as with agent pull requests');
  click(w, d.querySelector('#detail .rvwbar [data-rvw="approve"]'));
  await until(async () => (await call('GET', `/api/tasks/${T1}`, null, CC)).review === 'approved');
  check((await call('GET', `/api/tasks/${T1}`, null, CC)).review === 'approved', '#1512: Approve -> approved');
  await until(() => /Approved by you/.test(d.querySelector('#detail .rvwbar')?.textContent || ''));
  check(/Approved by you/.test(d.querySelector('#detail .rvwbar')?.textContent || ''), '#1512: the bar shows the approval');
  await w.eval(`histStep('undo')`); await sleep(500);
  check((await call('GET', `/api/tasks/${T1}`, null, CC)).review === 'pending', '#1512: one undo step: pending again');
  await w.eval(`histStep('redo')`); await sleep(500);
  check((await call('GET', `/api/tasks/${T1}`, null, CC)).review === 'approved', '#1512: redo: approved');
  check(w.eval(`NOTIF_ROWS.some(r => r[0] === 'review')`), '#1512: the notification settings have the row Reviews');
  w.close();
  const done = await call('POST', `/api/tasks/${T1}/complete`, {}, CB);
  check(done.status !== 409 && done.status < 400, '#1512: approved: bob ticks it off');

  // ================= Firefox: the phone (390, touch), the reviewer's bar
  const T2 = (await call('POST', '/api/tasks', {title: 'Export', list_id: P, section_id: S1, assignee_id: bob.id}, CB)).id;
  await call('PATCH', `/api/tasks/${T2}`, {section_id: S2}, CB);
  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'carol', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1, .agview')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '390';
    check(await ffLogin(o) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + '#today'); await ready(ev);
    await ev(`(() => { openDetail(${T2}); return 1; })()`); await sleep(1200);
    const g = await ev(`(() => { const b = document.querySelector('#detail .rvwbar'); if (!b) return null; const r = b.getBoundingClientRect();
      const a = b.querySelector('[data-rvw="approve"]').getBoundingClientRect();
      return {left: r.left, right: r.right, approve: Math.min(a.width, a.height), wide: document.documentElement.scrollWidth <= 390}; })()`);
    check(g && g.left >= 0 && g.right <= 390 && g.wide, `${tag}: #1512 the reviewer bar fits the phone ` + JSON.stringify(g));
    check(g && g.approve >= 36, `${tag}: #1512 Approve is big enough ` + JSON.stringify(g));
    await shot('p260c-390-review.png');
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
