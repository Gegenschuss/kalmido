// 2.70.0 UI tests of part C (#1359 contracts in view: an agent reminds of a notice deadline; own container, start.sh). jsdom:
// - the card of kind notice: who proposes it, the agent's sentence, cancel by / term ends / notice period / cost, the
//   buttons Discard (👎) / Remind me / Take it as a note, no entry list
// - "Remind me": a comment as the person + a reminder 3 days before, the toast; Undo takes both back (one step)
// - a deadline less than 3 days ahead: no "Remind me"
// Firefox (real layout, skipped without firefox): 390 px - the card stays inside the screen, the buttons are large enough
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const firefox = require('./ff')({tag: 'p270_c_ui', check: (c, w) => check(c, w), shots: 'P270C_SHOTS'});
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P270C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK, hd = {}) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {}), ...hd}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const until = async (fn, n = 40, ms = 150) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(ms); } return fn(); };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const sql = (q, a = []) => JSON.parse(execFileSync('python3', [path.join(__dirname, 'dbx.py'), DATA, q, JSON.stringify(a)]).toString() || '[]');
const day = n => { const d = new Date(); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments', 'collab']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,agents,contracts'});
  const ag = await call('POST', '/api/admin/agents', {username: 'claude', display_name: 'Claude', scopes: ['write']});
  sql('UPDATE agents SET org_id=NULL, owner_id=1 WHERE user_id=?', [ag.id]);  // alice's personal agent
  const AGH = {Authorization: 'Bearer ' + ag.token};
  const mob = await call('POST', '/api/life/contracts', {name: 'Mobile phone', provider: 'Telco', ends: day(10), notice: 0, cost: 19.99, per: 'month', lead_days: 14});
  const near = await call('POST', '/api/life/contracts', {name: 'Streaming', ends: day(2), notice: 0, cost: 120, per: 'year', list_id: mob.list_id});
  check(mob.http === 201 && near.http === 201, 'setup: two contracts');
  await call('PUT', `/api/lists/${mob.list_id}/members`, {user_id: ag.id, role: 'edit'});
  const evs = await until(async () => { const r = await call('GET', '/api/v1/agent/events?since=0&limit=200', null, null, AGH); const e = (r.data || []).filter(x => x.event === 'contract_notice'); return e.length >= 2 && e; }, 60, 500);
  check(evs && evs.length === 2, 'setup: contract_notice for both contracts');
  const jp = await call('POST', '/api/v1/agent/proposals', {kind: 'notice', task_id: mob.id, text: 'You can cancel the mobile phone contract until the deadline; it costs 19.99 a month.'}, null, AGH);
  check(jp.http === 201 && jp.kind === 'notice', 'setup: a notice proposal ' + jp.http + JSON.stringify(jp.error || ''));

  // ================= the card
  let w = await boot({user: 'alice', hash: 'prop/' + jp.id}), d = w.document;
  const md = await until(() => d.querySelector('.ppm .ctr-head') && d.querySelector('.ppm'));
  const txt = md?.textContent || '';
  check(/Proposal by Claude/.test(txt) && /Mobile phone/.test(md?.querySelector('.ctr-head')?.textContent || ''), '#1359: who proposes it, the contract');
  check(/cancel the mobile phone contract/.test(md?.querySelector('.ctr-text')?.textContent || ''), "#1359: the agent's sentence");
  const facts = [...(md?.querySelectorAll('.ctr-f') || [])].map(f => f.textContent.replace(/\s+/g, ' ').trim());
  check(facts.some(f => /^Cancel by/.test(f)) && facts.some(f => /^Term ends/.test(f)) && facts.some(f => /^Cost.*19\.99/.test(f)) && facts.some(f => /^Notice period/.test(f)),
    '#1359: cancel by, term ends, notice period, cost ' + JSON.stringify(facts));
  const rem = md?.querySelector('[data-pp="apply"][data-ctr-remind="1"]'), take = [...(md?.querySelectorAll('[data-pp="apply"]') || [])].find(b => !b.dataset.ctrRemind);
  check(rem && /Remind me/.test(rem.textContent) && take && /Take it as a note/.test(take.textContent) && /👎/.test(md?.querySelector('[data-pp="discard"]')?.textContent || '')
    && !md.querySelector('.ppi'), '#1359: Discard / Remind me / Take it as a note, no entry list');
  click(w, rem);
  const cm = await until(() => sql('SELECT id, user_id, body FROM comments WHERE task_id=? AND deleted_at IS NULL', [mob.id])[0]);
  check(cm && cm.user_id === 1 && /cancel the mobile phone/.test(cm.body), '#1359: Remind me -> a comment as the person ' + JSON.stringify(cm));
  check(/4320/.test(sql('SELECT reminders FROM tasks WHERE id=?', [mob.id])[0]?.reminders || ''), '#1359: … and a reminder 3 days before');
  check(await until(() => /reminder 3 days before/.test(d.querySelector('#toast, .toast')?.textContent || ''), 30), '#1359: the toast names the reminder');
  await sleep(300);
  await w.eval("histStep('undo')");
  check(await until(() => !sql('SELECT 1 FROM comments WHERE task_id=? AND deleted_at IS NULL', [mob.id]).length
    && !/4320/.test(sql('SELECT reminders FROM tasks WHERE id=?', [mob.id])[0]?.reminders || '')), '#1359: Undo takes the note and the reminder back');
  w.close();

  // ================= a deadline too near for "Remind me"
  const jn = await call('POST', '/api/v1/agent/proposals', {kind: 'notice', task_id: near.id, text: 'Streaming costs 10 a month; the deadline is the day after tomorrow.'}, null, AGH);
  w = await boot({user: 'alice', hash: 'prop/' + jn.id}); d = w.document;
  const m2 = await until(() => d.querySelector('.ppm .ctr-head') && d.querySelector('.ppm'));
  check(m2 && !m2.querySelector('[data-ctr-remind]') && m2.querySelector('[data-pp="apply"]'), '#1359: 2 days ahead: no Remind me, Take it as a note stays');
  check(/10\.00/.test([...(m2?.querySelectorAll('.ctr-f') || [])].map(f => f.textContent).join(' ')), '#1359: a yearly cost also per month');
  w.close();

  // ================= Firefox: 390 px (a fresh card: the first one was applied)
  const jf = await call('POST', '/api/v1/agent/proposals', {kind: 'notice', task_id: mob.id, text: 'Your mobile phone contract runs on for a year unless you cancel it by the deadline; it costs 19.99 a month.'}, null, AGH);
  await firefox(async ({cmd, ev: fev, nav, ctx, shot}) => {
    await nav(B + 'static/icon.svg');
    await fev('(() => { localStorage.clear(); return 1; })()');
    check(await fev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + '#prop/' + jf.id);
    for (let i = 0; i < 30 && !(await fev('!!document.querySelector(".ppm .ctr-head")').catch(() => false)); i++) await sleep(300);
    const o = await fev(`(() => { const vw = document.documentElement.clientWidth, card = document.querySelector('.ppm .card').getBoundingClientRect();
      const bad = [...document.querySelectorAll('.ppm .card *')].filter(e => { const r = e.getBoundingClientRect(); return r.width && r.right > vw + 1; }).length;
      const btns = [...document.querySelectorAll('.ppm .foot .btn')].map(e => e.getBoundingClientRect());
      return {vw, right: card.right, bad, n: btns.length, btn: Math.min(...btns.map(r => r.height))}; })()`);
    check(o.right <= o.vw + 1 && !o.bad && o.n >= 3 && o.btn >= 40, '390 px: the card inside the screen, buttons large enough ' + JSON.stringify(o));
    await shot('p270c-card-390.png');
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
