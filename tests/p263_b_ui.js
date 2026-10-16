// 2.63.0 UI tests (part B), own container (start.sh). jsdom:
// #1513 the task panel of a customer report: the box "Customer report" (name, address, Copy the status link, Mails to the
//       customer for people who may change the task; a viewer sees only the name), the composer's switch Internal / To the
//       customer (off by default, back to internal after sending), the marks "to the customer" / "Customer" on the comments,
//       the mail switch is one undo step; a task without a ticket has neither box nor switch
// Firefox 390 touch: the box and the switch fit the phone; the status page /p/<token> fits the phone (screenshots).
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p263_b_ui', check, shots: 'P263B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const CT = process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test';
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el, o = {}) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const FEAT = 'comments,collab,clients';
// a ticket as the form (part A) creates it: team/portal.py pt_create inside the container -> the status-link token
const ticket = (tid, lid, name, mail) => execFileSync('docker', ['exec', CT, 'python', '-c',
  "import sys, app\nfrom kalmido.core.pg import system_ctx\nfrom kalmido.team.portal import pt_create\nc = app.connect()\n" +
  "with system_ctx(c):\n    l = c.execute('SELECT id, org_id, owner_id FROM lists WHERE id=?', (int(sys.argv[2]),)).fetchone()\n" +
  "    t = pt_create(c, int(sys.argv[1]), l, None, sys.argv[3], sys.argv[4])\nc.commit()\nprint(t[1])", String(tid), String(lid), name, mail]).toString().trim().split('\n').pop();

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['comments', 'clients']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const eve = await call('POST', '/api/users', {orgs: [1], username: 'eve', display_name: 'Eve', password: 'password123', email: 'eve@example.com'});
  const CE = await login('eve');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, CE);
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  const L = (await call('POST', '/api/lists', {name: 'Support', org_id: ORG})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: eve.id, role: 'view'});
  const T1 = (await call('POST', '/api/tasks', {title: 'Export button does nothing', list_id: L, content: 'Nothing happens.\n\n— Sent with the form “Bugs” by Jane Example <jane@example.com>'})).id;
  const T4 = (await call('POST', '/api/tasks', {title: 'Plain task', list_id: L})).id;
  const TK = ticket(T1, L, 'Jane Example', 'jane@example.com');
  check(TK.length >= 30, 'setup: a ticket ' + TK.length);

  // ================= the box and the switch (alice may change the task)
  let w = await boot({user: 'alice', hash: 't/' + T1}), d = w.document;
  await until(() => d.querySelector('#d-ptl .ptlbox'));
  const box = () => d.querySelector('#d-ptl .ptlbox');
  check(box() && /Customer report/.test(box().textContent) && /Jane Example/.test(box().textContent), '#1513: the box "Customer report" with the name');
  check(box()?.querySelector('a[href="mailto:jane@example.com"]') && box().querySelector('[data-ptl="copy"]'), '#1513: the address and "Copy the status link"');
  const nt = () => box()?.querySelector('[data-ptl="notify"]');
  check(nt() && nt().checked, '#1513: "Mails to the customer" on');
  const sw = () => d.querySelector('#c-ptl [data-ptl="switch"]');
  check(sw() && sw().getAttribute('aria-pressed') === 'false' && /Internal/.test(sw().textContent), '#1513: the switch starts on Internal');
  click(w, sw()); await sleep(50);
  check(sw().getAttribute('aria-pressed') === 'true' && /To the customer/.test(sw().textContent), '#1513: the switch turns to "To the customer"');
  d.querySelector('#c-input').value = 'We are on it.';
  await w.eval('sendComment()'); await sleep(300);
  let tl = await call('GET', `/api/tasks/${T1}/timeline`);
  const pub = tl.comments.find(c => c.body === 'We are on it.');
  check(pub && pub.portal === true, '#1513: the comment went to the customer');
  await until(() => sw()?.getAttribute('aria-pressed') === 'false');
  check(sw()?.getAttribute('aria-pressed') === 'false', '#1513: after sending the switch is back on Internal');
  await until(() => d.querySelector(`#d-tl-items .cm[data-cid="${pub?.id}"] .ptltag.pub`));
  check(d.querySelector(`#d-tl-items .cm[data-cid="${pub?.id}"] .ptltag.pub`), '#1513: the public answer is marked "to the customer"');
  d.querySelector('#c-input').value = 'Internal note only.';
  await w.eval('sendComment()'); await sleep(300);
  tl = await call('GET', `/api/tasks/${T1}/timeline`);
  const inn = tl.comments.find(c => c.body === 'Internal note only.');
  check(inn && inn.portal === false, '#1513: without the switch a comment stays internal');
  check(!d.querySelector(`#d-tl-items .cm[data-cid="${inn?.id}"] .ptltag`), '#1513: an internal comment has no mark');
  // the customer answers on the status page
  const pg = await (await fetch(B + 'p/' + TK)).text();
  const f = (pg.match(/name="f" value="([0-9a-f]{64})"/) || [])[1];
  await fetch(B + `p/${TK}/comment`, {method: 'POST', headers: {'Content-Type': 'application/x-www-form-urlencoded'}, body: new URLSearchParams({f, text: 'Thank you!'}).toString(), redirect: 'manual'});
  await w.eval(`loadTimeline(${T1})`);
  await until(() => [...d.querySelectorAll('#d-tl-items .cm .ptltag')].some(x => !x.classList.contains('pub')));
  check([...d.querySelectorAll('#d-tl-items .cm .ptltag')].some(x => !x.classList.contains('pub') && /Customer/.test(x.textContent)), '#1513: the customer\'s comment is marked "Customer"');
  // the mail switch: one undo step
  const n0 = w.eval('HIST.undo.length');
  nt().checked = false; nt().dispatchEvent(new w.Event('change', {bubbles: true}));
  await until(async () => (await call('GET', `/api/tasks/${T1}/timeline`)).ticket?.notify === false);
  check((await call('GET', `/api/tasks/${T1}/timeline`)).ticket.notify === false, '#1513: the mails off');
  check(w.eval('HIST.undo.length') === n0 + 1, '#1513: one undo step');
  await w.eval(`histStep('undo')`); await sleep(400);
  check((await call('GET', `/api/tasks/${T1}/timeline`)).ticket.notify === true, '#1513: undo turns them on again');
  w.close();

  // ================= a task without a ticket; a viewer
  w = await boot({user: 'alice', hash: 't/' + T4}); d = w.document;
  await until(() => d.querySelector('#c-input')); await sleep(600);
  check(!d.querySelector('.ptlbox') && !d.querySelector('[data-ptl="switch"]'), '#1513: no box, no switch without a ticket');
  w.close();
  w = await boot({user: 'eve', hash: 't/' + T1}); d = w.document;
  await until(() => d.querySelector('#d-ptl .ptlbox'));
  check(d.querySelector('#d-ptl .ptlbox') && !/jane@example\.com/.test(d.querySelector('#d-ptl').textContent) && !d.querySelector('[data-ptl="copy"]'),
    '#1513: a viewer sees the report, not the address or the link');
  check(!d.querySelector('[data-ptl="switch"]'), '#1513: a viewer has no "To the customer"');
  w.close();

  // ================= Firefox, phone 390
  const ffLogin = async ({ev, nav}) => {
    await nav(B);
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '390';
    check(await ffLogin(o) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + '?p=1#t/' + T1);  // a real load (a hash change alone keeps the login page)
    for (let i = 0; i < 30 && !(await ev(`!!document.querySelector('#d-ptl .ptlbox')`).catch(() => false)); i++) await sleep(300);
    await sleep(600);
    const g = await ev(`(() => { const b = document.querySelector('#d-ptl .ptlbox'); if (!b) return null; const r = b.getBoundingClientRect();
      return {left: r.left, right: r.right, wide: document.documentElement.scrollWidth <= 390}; })()`);
    check(g && g.left >= 0 && g.right <= 390 && g.wide, `${tag}: #1513 the box fits the phone ` + JSON.stringify(g));
    await ev(`(() => { const i = document.querySelector('#c-input'); i && i.focus(); document.querySelector('#d-ptl .ptlbox').scrollIntoView({block: 'center'}); return 1; })()`); await sleep(400);
    await shot('p263b-390-task-box.png');
    await o.nav(B + 'p/' + TK); await sleep(800);
    const p = await ev(`(() => ({wide: document.documentElement.scrollWidth <= 390, h1: (document.querySelector('h1') || {}).textContent || '',
      btn: Math.min(...[...document.querySelectorAll('.fform button')].map(b => b.getBoundingClientRect().height))}))()`);
    check(p && p.wide && /Export button/.test(p.h1), `${tag}: #1513 the status page fits the phone ` + JSON.stringify(p));
    check(p && p.btn >= 44, `${tag}: #1513 the buttons of the status page >= 44 px ` + JSON.stringify(p));
    await shot('p263b-390-status-page.png');
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
