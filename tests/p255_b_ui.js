// 2.55.0 UI tests of part B (#1066 an agent proposes how a view is arranged; own container, start.sh). jsdom:
// - the proposal card: before / after as two schematic grids (block names, widths), changed blocks marked, "Use it right
//   away" ticked, 👍 Accept / 👎 Decline instead of the entry list
// - 👍 switches the view: the person's arrangement of Today is the proposed one (client and server), a saved arrangement
//   from the agent exists; Undo brings the previous arrangement back
// - the planned-job template "Propose a better start page"
// Firefox (real layout, skipped without firefox): 390 px - the card stays inside the screen, the grids stack
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const firefox = require('./ff')({tag: 'p255_b_ui', check: (c, w) => check(c, w), shots: 'P255B_SHOTS'});
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P255B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK, hd = {}) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {}), ...hd}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const sql = (q, a = []) => JSON.parse(execFileSync('python3', [path.join(__dirname, 'dbx.py'), DATA, q, JSON.stringify(a)]).toString() || '[]');
const today = () => JSON.parse(sql("SELECT value FROM user_settings WHERE user_id=1 AND key='view_today'")[0]?.value || '{}');

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', view_today: JSON.stringify({order: ['inbox', 'brief']})});
  const ag = await call('POST', '/api/admin/agents', {username: 'claude', display_name: 'Claude', scopes: ['read', 'comments', 'layouts']});
  sql('UPDATE agents SET org_id=NULL, owner_id=1 WHERE user_id=?', [ag.id]);  // alice's personal agent
  const AGH = {Authorization: 'Bearer ' + ag.token};
  const jp = await call('POST', '/api/v1/layouts/proposals', {view: 'view_today', name: 'Focus', summary: 'Your tasks first',
    layout: {order: ['tasks', 'events', 'brief'], hidden: ['inbox'], widths: {events: 3, brief: 3}}}, null, AGH);
  check(jp.http === 201 && jp.kind === 'layout', 'setup: a layout proposal ' + jp.http + JSON.stringify(jp.error || ''));

  // ================= the card
  let w = await boot({user: 'alice', hash: 'prop/' + jp.id}), d = w.document;
  const md = await until(() => d.querySelector('.ppm .lyp-ba') && d.querySelector('.ppm'));
  const figs = md ? [...md.querySelectorAll('.lyp-f')] : [];
  check(figs.length === 2 && /Before/.test(figs[0].textContent) && /After/.test(figs[1].textContent), '#1066: two grids, before and after');
  const after = figs[1] ? [...figs[1].querySelectorAll('.lyp-c')] : [];
  check(after[0]?.textContent === 'Tasks' && after.some(c => c.textContent === 'Events today' && c.classList.contains('lyp-w3')),
    '#1066: after: Tasks first, Events today half wide ' + after.map(c => c.textContent + ':' + c.className).join(' | '));
  check(after[0]?.classList.contains('lyp-new') && /Hidden: .*Basket/.test(figs[1]?.textContent || ''), '#1066: changed blocks marked, the hidden ones named');
  check([...(figs[0]?.querySelectorAll('.lyp-c') || [])].some(c => c.textContent === 'Basket'), '#1066: before: the basket still shown');
  check(/Proposal by Claude/.test(md?.textContent || '') && /Your tasks first/.test(md?.querySelector('.ppsum')?.textContent || ''), '#1066: who proposes it and why');
  check(md?.querySelector('#lyp-use')?.checked === true && !!md.querySelector('[data-pp="apply"] .thumb svg')  /* 2.139.0 (#2401) */
    && !!md.querySelector('[data-pp="discard"] .thumb svg') && !md.querySelector('.ppi'), '#1066: "Use it right away" ticked, 👍 / 👎, no entry list');
  // 👍 switches the view
  click(w, md?.querySelector('[data-pp="apply"]'));
  const t1 = await until(() => today().order?.[0] === 'tasks' && today());
  check(t1 && (t1.hidden || []).includes('inbox'), '#1066: 👍 -> the arrangement of Today on the server ' + JSON.stringify(t1));
  const vl = sql("SELECT source, name FROM view_layouts WHERE user_id=1 AND view_key='view_today'");
  check(vl.length === 1 && vl[0].source === 'agent' && /Focus \(proposal by Claude\)/.test(vl[0].name), '#1066: a saved arrangement from the agent ' + JSON.stringify(vl));
  check(await until(() => w.eval("lyPref('today').order[0]") === 'tasks'), '#1066: the client shows Today in the new order');
  await until(() => /Arrangement/.test(d.querySelector('#toast, .toast')?.textContent || ''), 20); await sleep(300);  // the undo step is there
  await w.eval("histStep('undo')");
  check(await until(() => today().order?.[0] === 'inbox') && !sql("SELECT 1 FROM view_layouts WHERE user_id=1 AND view_key='view_today'").length,
    '#1066: Undo -> the previous arrangement, the saved one goes');
  check(await until(() => w.eval("JSON.parse(S.settings.view_today || '{}').order?.[0]") === 'inbox'), '#1066: the client follows the undo');
  w.close();

  // ================= the planned-job template
  w = await boot({user: 'alice', hash: 'home'}); d = w.document;
  await until(() => w.eval('typeof SCHED_TPL') === 'object');
  const ks = w.eval('SCHED_TPL.map(t => t.k).join()');
  check(/lyprop/.test(ks) && ks.endsWith('own'), '#1066: the template "Propose a better start page", "Own plan" stays last ' + ks);
  w.close();

  // ================= Firefox: 390 px
  const j2 = await call('POST', '/api/v1/layouts/proposals', {view: 'dashboard', name: 'Morning', layout: {order: ['today', 'projects', 'news'], widths: {today: 6}}}, null, AGH);
  await firefox(async ({cmd, ev: fev, nav, ctx, shot}) => {
    await nav(B + 'static/icon.svg');
    await fev('(() => { localStorage.clear(); return 1; })()');
    check(await fev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + '#prop/' + j2.id);
    for (let i = 0; i < 30 && !(await fev('!!document.querySelector(".ppm .lyp-ba")').catch(() => false)); i++) await sleep(300);
    const o = await fev(`(() => { const vw = document.documentElement.clientWidth, card = document.querySelector('.ppm .card').getBoundingClientRect();
      const f = [...document.querySelectorAll('.ppm .lyp-f')].map(e => e.getBoundingClientRect());
      const bad = [...document.querySelectorAll('.ppm .lyp-ba *')].filter(e => { const r = e.getBoundingClientRect(); return r.width && r.right > vw + 1; }).length;
      const btn = Math.min(...[...document.querySelectorAll('.ppm [data-pp="apply"], .ppm [data-pp="discard"]')].map(e => e.getBoundingClientRect().height));
      return {vw, right: card.right, stacked: f.length === 2 && f[1].top >= f[0].bottom - 1, bad, btn}; })()`);
    check(o.right <= o.vw + 1 && o.stacked && !o.bad && o.btn >= 36, '390 px: the card inside the screen, the grids stacked, buttons large enough ' + JSON.stringify(o));
    await shot('p255b-card-390.png');
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
