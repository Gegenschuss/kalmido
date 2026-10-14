// 2.41.0 UI tests, part A (small fixes), own container (start.sh). jsdom:
// - #1476 calendar / contacts / private have names in the permission limit and the token overview; agents never get private
// - #1477 the hover dot of the status circle is centred by the box (no layout in jsdom: checks the CSS rules)
// - #1479 a job log stays open across live redraws
// - #1439 the second menu level opens at the menu's own place when the anchor is gone
// - #1475 the task's Link row only with a link; Add link / Esc / remove; phone width as well
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const CT = process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test';
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const py = code => execFileSync('docker', ['exec', CT, 'python', '-c', code], {encoding: 'utf8'}).trim();
const sql = (q, rows) => py(`import json
from kalmido.core.db import connect
c = connect()
for r in json.loads(${JSON.stringify(JSON.stringify(rows))}):
    c.execute(${JSON.stringify(q)}, r)
c.commit(); c.close()`);
const FEAT = 'comments,collab,agents';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['agents', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ME = (await call('GET', '/api/state')).me;
  const AG = (await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write'], username: 'claude', display_name: 'Claude'})).id;
  const INBOX = (await call('GET', '/api/state')).lists.find(l => l.is_inbox)?.id;

  // ================= #1476: calendar / contacts / private have names in the limit grid and the token overview
  await call('POST', '/api/me/tokens', {name: 'Cal script', scopes: ['read', 'calendar', 'contacts']});
  let w = await boot({user: 'alice', hash: 'today'}), d = w.document;
  w.eval(`settingsModal('ai')`); await sleep(500);
  await w.eval(`aiSubShow(document.querySelector('.smodal'), 'admin', false)`);
  await until(() => d.querySelector('#s-sclim .sclim'));
  const lim = [...d.querySelectorAll('#s-sclim .sclim')];
  const raw = lim.flatMap(f => [...f.querySelectorAll('.chkl span')]).filter(s => /^[a-z:-]+$/.test(s.textContent.trim()));
  check(lim.length === 2 && raw.length === 0, '#1476: no limit box shows a lowercase key ' + raw.map(s => s.textContent));
  const lbl = (g, k) => lim[g].querySelector(`[data-scope="${k}"]`)?.parentNode.textContent.trim();
  check(lbl(0, 'calendar') === 'Calendar' && lbl(0, 'contacts') === 'Contacts' && lbl(1, 'private') === 'Health & journal', '#1476: Calendar / Contacts / Health & journal ' + [lbl(0, 'calendar'), lbl(0, 'contacts'), lbl(1, 'private')]);
  check(!lim[0].querySelector('[data-scope="private"]') && lim[1].querySelector('[data-scope="private"]'), '#1476: the agents row hides private, the tokens row has it');
  await w.eval(`tokDraw(document.querySelector('.smodal'))`); await sleep(300);
  const trow = [...d.querySelectorAll('#s-toks .tokrow')].find(x => /Cal script/.test(x.textContent));
  check(trow && /Calendar, Contacts/.test(trow.textContent) && !/calendar|contacts/.test(trow.textContent.replace(/Cal script/, '')), '#1476: the token overview names them: ' + trow?.textContent.replace(/\s+/g, ' ').slice(0, 120));
  w.close();

  // ================= #1477: the hover dot is centred by the box (inset:0 + auto margins), no sub-pixel offset (jsdom has no layout: the rules)
  const css = await (await fetch(B + 'static/app.css')).text();
  const rule = sel => (css.split('}').reverse().find(b => b.includes(sel)) || '');
  check(/inset:0/.test(rule('.chk:hover:not(.on):not(.wont)::before')) && /margin:auto/.test(rule('.chk:hover:not(.on):not(.wont)::before')), '#1477: hover dot is centred with inset:0 + margin:auto');
  check(/inset:0/.test(rule('.chk.work::before')) && /margin:auto/.test(rule('.chk.work::before')), '#1477: the working dot too');

  // ================= #1479: a job log stays open when the list redraws
  const ins = (log) => sql('UPDATE agent_jobs SET log=?, updated_at=? WHERE title=?', [[log, '2026-05-01T00:00:00Z', 'Logging job']]);
  sql('INSERT INTO agent_jobs (agent_id, user_id, title, state, log, created_at, updated_at) VALUES (?,?,?,?,?,?,?)', [[AG, ME.id, 'Logging job', 'running', 'step 1', '2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z']]);
  w = await boot({user: 'alice', hash: 'agents'}); d = w.document;
  await until(() => d.querySelector('#view .job details.joblog'));
  const lg = () => d.querySelector('#view .job details.joblog');
  check(lg() && !lg().open, '#1479: the log starts closed');
  lg().open = true; lg().dispatchEvent(new w.Event('toggle')); await sleep(100);
  ins('step 1\nstep 2\nstep 3');
  await w.eval('loadJobs()'); await sleep(400);
  check(lg() && lg().open && /step 3/.test(lg().querySelector('pre').textContent), '#1479: still open after the live redraw, with the new line');
  lg().open = false; lg().dispatchEvent(new w.Event('toggle')); await sleep(100);
  ins('step 1\nstep 2\nstep 3\nstep 4');
  await w.eval('loadJobs()'); await sleep(400);
  check(lg() && !lg().open, '#1479: closed stays closed');
  w.close();

  // ================= #1439: the second menu level opens at the menu's place although the anchor is gone
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  w.eval(`window.__a = {getBoundingClientRect: () => ({left: 300, top: 200, right: 340, bottom: 224, width: 40, height: 24}), closest: () => null}`);
  w.eval(`menu(window.__a, [{label: 'One', fn() {}}, {label: 'More options…', more: [{label: 'Deep', fn() {}}]}])`); await sleep(100);
  const pop = d.querySelector('#pop'), left0 = pop.style.left, top0 = pop.style.top;
  check(left0 === '300px', '#1439: the menu opens at the anchor ' + left0);
  w.eval(`window.__a.getBoundingClientRect = () => ({left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0})`);  // the anchor vanished (live redraw)
  click(w, [...pop.querySelectorAll('[role="menuitem"]')].find(b => /More options/.test(b.textContent))); await sleep(100);
  check(/Deep/.test(pop.textContent) && pop.style.left !== '12px' && pop.style.left !== '0px' && pop.style.left !== '', '#1439: the second level is not at the top left: ' + pop.style.left + '/' + pop.style.top);
  click(w, pop.querySelector('.mback')); await sleep(100);
  check(/More options/.test(pop.textContent) && pop.style.left === left0 && pop.style.top === top0, '#1439: Back returns to the same place ' + pop.style.left + '/' + pop.style.top);
  w.close();

  // ================= #1475: the Link row only with a link
  const t0 = (await call('POST', '/api/tasks', {title: 'No link yet', list_id: INBOX})).id;
  const t1 = (await call('POST', '/api/tasks', {title: 'Has a link', list_id: INBOX, url: 'https://example.org/a'})).id;
  for (const mobile of [false, true]) {
    const tag = mobile ? ' (phone)' : '';
    w = await boot({user: 'alice', hash: 'l/' + INBOX, mobile}); d = w.document;
    const linkRow = () => [...d.querySelectorAll('#detail .fields label')].some(l => l.textContent.trim() === 'Link');
    w.eval(`openDetail(${t0})`); await until(() => d.querySelector('#detail .fields'));
    check(!linkRow() && !d.querySelector('#d-url') && !d.querySelector('#detail .linkf'), '#1475: no link, no Link row' + tag);
    check(!!d.querySelector('#detail [data-act="link-edit"].linkadd'), '#1475: "Add link" under More details' + tag);
    w.eval(`linkAdd(${t0})`); await until(() => d.querySelector('#d-url'));
    check(!!d.querySelector('#d-url') && linkRow(), '#1475: Add link opens the input' + tag);
    const ui = d.querySelector('#d-url');
    ui.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); await sleep(150);
    check(!d.querySelector('#d-url') && !linkRow() && !w.eval(`S.tasks.get(${t0}).url`), '#1475: Esc cancels' + tag);
    w.eval(`linkAdd(${t0})`); await until(() => d.querySelector('#d-url'));
    const u2 = d.querySelector('#d-url'); u2.value = 'example.org/new'; u2.dispatchEvent(new w.Event('change', {bubbles: true}));
    await until(() => w.eval(`S.tasks.get(${t0}).url`)); await until(() => d.querySelector('#detail .linkchip'));
    check(w.eval(`S.tasks.get(${t0}).url`) === 'https://example.org/new' && d.querySelector('#detail .linkchip'), '#1475: adding sets the link' + tag);
    click(w, d.querySelector('#detail [data-act="link-rm"]')); await until(() => !d.querySelector('#detail .linkchip'));
    check(!w.eval(`S.tasks.get(${t0}).url`) && !linkRow() && d.querySelector('#detail .linkadd'), '#1475: removing hides the row again' + tag);
    w.eval(`openDetail(${t1})`); await until(() => d.querySelector('#detail .linkchip'));
    check(linkRow() && !d.querySelector('#detail .linkadd'), '#1475: with a link the row stays' + tag);
    // the task menu offers "Add link" only without a link
    w.eval(`taskMenu(document.querySelector('#detail .dtop') || document.body, ${t0})`); await sleep(100);
    check([...d.querySelectorAll('#pop [role="menuitem"]')].some(b => /Add link/.test(b.textContent)), '#1475: the task menu offers Add link' + tag);
    w.eval('closePop()');
    w.eval(`taskMenu(document.querySelector('#detail .dtop') || document.body, ${t1})`); await sleep(100);
    check(![...d.querySelectorAll('#pop [role="menuitem"]')].some(b => /Add link/.test(b.textContent)), '#1475: no Add link when there is one' + tag);
    w.close();
  }

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
