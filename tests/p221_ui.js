// 2.2.1 UI tests, own container (start.sh)
// #358 Settings > AI colleague > Activity log (admins): the rows (time, agent, method + route template, status badge, task /
// list id, duration), denied calls (401 / 403 / 429) marked, filters (agent, status class incl. "Denied", day picker),
// "Load more", the CSV link follows the filters, German texts; nothing of it for a member; Settings > AI colleague opened
// with focus 'activity'. Then the same page in Firefox headless (WebDriver BiDi, skipped without firefox) at 390 x 844 and
// 1280 x 800: no horizontal overflow, the phone layout (route on its own line, no header row), the red mark of a denied row.
// #359 the app itself sends no unknown fields: creating / editing tasks, a new list (with "Move dependent tasks along", now
// taken at creation now) and comments leave no "unknown field(s) ignored" line in the server log. SW v64.
const {execFileSync, spawn} = require('child_process');
const fs = require('fs'), os = require('os'), path = require('path');
const {boot, errs, sleep, B, login} = require('./boot');
const WS = globalThis.WebSocket || require('ws');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const CONTAINER = process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test';
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const v1 = async (tok, method, url, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + tok}, body: body ? JSON.stringify(body) : undefined}); return r.status; };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const change = (w, el) => el && el.dispatchEvent(new w.Event('change', {bubbles: true}));
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = fn(); if (x) return x; await sleep(150); } return fn(); };
const logs = () => { try { return execFileSync('docker', ['logs', CONTAINER], {encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe']}); } catch (e) { return String(e.stdout || '') + String(e.stderr || ''); } };
const logsAll = () => { try { const r = require('child_process').spawnSync('docker', ['logs', CONTAINER], {encoding: 'utf8'}); return (r.stdout || '') + (r.stderr || ''); } catch { return logs(); } };
const ALL = 'cal,timeline,matrix,habits,pomo,kanban,paperless,collab,stats,time,progress,deps,fields,comments,agents';

async function firefox(fn) {
  try { execFileSync('firefox', ['--version'], {stdio: 'ignore'}); } catch { console.log('p221_ui: Firefox part skipped (no firefox on PATH)'); return; }
  const PORT = 9300 + Math.floor(Math.random() * 600);
  const prof = fs.mkdtempSync(path.join(process.env.TMPDIR || os.tmpdir(), 'kalmido-p221-'));
  fs.writeFileSync(path.join(prof, 'user.js'), [['browser.shell.checkDefaultBrowser', false], ['datareporting.policy.dataSubmissionEnabled', false], ['ui.prefersReducedMotion', 1]]
    .map(([k, v]) => `user_pref("${k}", ${JSON.stringify(v)});`).join('\n') + '\n');
  const ff = spawn('firefox', ['--headless', '--no-remote', '--profile', prof, `--remote-debugging-port=${PORT}`, 'about:blank'], {stdio: 'ignore'});
  let ws, seq = 0; const pend = new Map();
  try {
    for (let i = 0; i < 90 && !ws; i++) {
      try { const w = new WS(`ws://127.0.0.1:${PORT}/session`); await new Promise((res, rej) => { w.onopen = res; w.onerror = rej; }); ws = w; } catch { await sleep(500); }
    }
    if (!ws) { check(false, 'no WebDriver BiDi connection to Firefox'); return; }
    ws.onmessage = m => { const j = JSON.parse(m.data); if (j.id && pend.has(j.id)) { const p = pend.get(j.id); pend.delete(j.id); j.type === 'error' ? p.rej(new Error(p.method + ': ' + j.error + ' ' + j.message)) : p.res(j.result); } };
    const cmd = (method, params = {}) => new Promise((res, rej) => { const id = ++seq; pend.set(id, {res, rej, method}); ws.send(JSON.stringify({id, method, params})); });
    const unwrap = v => !v ? v : v.type === 'array' ? v.value.map(unwrap) : v.type === 'object' ? Object.fromEntries(v.value.map(([k, x]) => [typeof k === 'string' ? k : unwrap(k), unwrap(x)])) : v.value;
    await cmd('session.new', {capabilities: {}});
    const ctx = (await cmd('browsingContext.getTree', {})).contexts[0].context;
    const ev = async expr => { const r = await cmd('script.evaluate', {expression: expr, target: {context: ctx}, awaitPromise: true, resultOwnership: 'none', serializationOptions: {maxObjectDepth: 5}}); if (r.type === 'exception') throw new Error('JS: ' + r.exceptionDetails.text); return unwrap(r.result); };
    const nav = url => cmd('browsingContext.navigate', {context: ctx, url, wait: 'complete'});
    const shot = async name => { const dir = process.env.P221_SHOTS; if (!dir) return; const r = await cmd('browsingContext.captureScreenshot', {context: ctx}); fs.writeFileSync(path.join(dir, name), Buffer.from(r.data, 'base64')); };
    await fn({cmd, ev, nav, ctx, shot});
  } catch (e) { check(false, 'Firefox: ' + e.message); } finally {
    try { ws && ws.close(); } catch { /* gone */ }
    try { ff.kill(); } catch { /* gone */ }
    await sleep(500); fs.rmSync(prof, {recursive: true, force: true});
  }
}

(async () => {
  await sleep(600);
  const SW = await (await fetch(B + 'sw.js')).text();
  check(/const CACHE = 'tasks-shell-v6[4-9]'/.test(SW), 'service worker cache v64 (2.3.0: v65, 2.4.0: v66, 2.4.1: v67, 2.4.2: v68, 2.5.0: v69)');
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en'});
  const bob = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const CKB = await login('bob');
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en'}, CKB);
  const ag = await call('POST', '/api/admin/agents', {username: 'claude', display_name: 'Claude'});
  const ag2 = await call('POST', '/api/admin/agents', {username: 'helper', display_name: 'Helper'});
  const TEAM = (await call('POST', '/api/lists', {name: 'Team'})).id;
  for (const id of [bob, ag.id, ag2.id]) await call('PUT', `/api/lists/${TEAM}/members`, {user_id: id, role: 'edit'});
  const T = (await call('POST', '/api/tasks', {title: 'Shared task', list_id: TEAM})).id;
  // traffic: successes, a 404, then paused -> 403 (denied)
  check(await v1(ag.token, 'GET', `/tasks/${T}`) === 200, 'agent reads a task');
  for (let i = 0; i < 118; i++) await v1(ag.token, 'GET', '/me');
  await v1(ag.token, 'GET', '/tasks/999999');
  await v1(ag2.token, 'POST', `/tasks/${T}/comments`, {body: 'on it'});
  await call('PATCH', `/api/admin/agents/${ag.id}`, {enabled: false});
  check(await v1(ag.token, 'GET', '/lists') === 403, 'paused agent: 403');
  await call('PATCH', `/api/admin/agents/${ag.id}`, {enabled: true});

  // ================= admin, desktop
  let w = await boot({user: 'alice', hash: 'today'}), d = w.document;
  w.eval(`settingsModal('activity')`);
  const box = await until(() => d.querySelector('#s-aud .audr:not(.audh)') && d.querySelector('#s-aud'));
  check(box && /Activity log/.test(d.querySelector('#s-aud-h')?.textContent || ''), 'Settings > AI colleague: Activity log section');
  check(d.querySelector('.spane:not(.hidden)')?.dataset.pane === 'ai', 'focus activity opens AI colleague');
  let rs = [...d.querySelectorAll('#s-aud .audr:not(.audh)')];
  check(rs.length === 100, 'first page: 100 rows: ' + rs.length);
  const top = rs[0];
  check(top.classList.contains('den') && top.querySelector('.audc.den')?.textContent === '403' && /Claude/.test(top.textContent) && /GET\/api\/v1\/lists/.test(top.querySelector('.audrt').textContent),
    'newest: the denied 403 marked: ' + top.textContent.replace(/\s+/g, ' '));
  check(d.querySelector('#s-aud .audh') && /Route/.test(d.querySelector('#s-aud .audh').textContent), 'header row');
  check(/Kept for 90 days/.test(d.querySelector('#aud-keep')?.textContent || ''), 'retention shown');
  const opts = [...d.querySelectorAll('#aud-ag option')].map(o => o.textContent);
  check(opts.join('|') === 'All agents|Claude|Helper', 'agent filter: ' + opts.join('|'));
  const more = d.querySelector('#s-aud [data-aud="more"]');
  check(more, 'Load more');
  click(w, more);
  await until(() => d.querySelectorAll('#s-aud .audr:not(.audh)').length > 100);
  rs = [...d.querySelectorAll('#s-aud .audr:not(.audh)')];
  check(rs.length === 122 && !d.querySelector('#s-aud [data-aud="more"]'), 'all rows after Load more: ' + rs.length);
  const t404 = rs.find(r => r.querySelector('.audc')?.textContent === '404');
  check(t404 && /\/api\/v1\/tasks\/\{tid\}/.test(t404.textContent) && /Task #999999/.test(t404.textContent) && !t404.classList.contains('den'), '404 row: route template + task id, not denied');
  check(rs.some(r => /POST\/api\/v1\/tasks\/\{tid\}\/comments/.test(r.textContent) && /Helper/.test(r.textContent) && r.querySelector('.audc.ok')), 'the helper\'s comment (201, ok badge)');
  // filters
  const st = d.querySelector('#aud-st'); st.value = 'denied'; change(w, st);
  await until(() => d.querySelectorAll('#s-aud .audr:not(.audh)').length === 1);
  check(d.querySelectorAll('#s-aud .audr:not(.audh)').length === 1 && /status=denied/.test(d.querySelector('#aud-csv').getAttribute('href')), 'filter Denied: one row, CSV link follows');
  const sa = d.querySelector('#aud-ag'); sa.value = String(ag2.id); change(w, sa);
  await until(() => /No requests match/.test(d.querySelector('#s-aud').textContent));
  check(/No requests match these filters/.test(d.querySelector('#s-aud').textContent), 'no match: the hint');
  st.value = ''; change(w, st);
  await until(() => d.querySelectorAll('#s-aud .audr:not(.audh)').length === 1);
  check(d.querySelectorAll('#s-aud .audr:not(.audh)').length === 1 && /agent_id=/.test(d.querySelector('#aud-csv').getAttribute('href')), 'filter: agent');
  const day = d.querySelector('#aud-day');
  check(day && d.querySelector('[data-dpfor="aud-day"]'), 'day: the app\'s own date picker');
  w.eval(`dpSet(document.querySelector('#aud-day'), '2020-01-01')`);
  await until(() => /No requests match/.test(d.querySelector('#s-aud').textContent));
  check(/day=2020-01-01/.test(d.querySelector('#aud-csv').getAttribute('href')) && /No requests match/.test(d.querySelector('#s-aud').textContent), 'filter: day');
  const csv = await fetch(B + d.querySelector('#aud-csv').getAttribute('href').replace(/^\//, '').replace(/day=[^&]*&?/, ''), {headers: {Cookie: CK}});
  check(csv.ok && (await csv.text()).split('\r\n').filter(Boolean).length === 2, 'CSV link works (header + 1 row)');
  w.close();

  // ================= member: nothing; German
  w = await boot({user: 'bob', hash: 'today'}); d = w.document;
  w.eval(`settingsModal('activity')`); await sleep(1200);
  check(!d.querySelector('#s-aud') && !d.querySelector('#s-aud-h'), 'member: no activity log');
  w.close();
  await call('PATCH', '/api/settings', {lang: 'de'});
  w = await boot({user: 'alice', hash: 'today', mobile: true}); d = w.document;
  w.eval(`settingsModal('activity')`);
  await until(() => d.querySelector('#s-aud .audr:not(.audh)'));
  check(/Aktivitätsprotokoll/.test(d.querySelector('#s-aud-h')?.textContent || '') && /Wird 90 Tage aufbewahrt/.test(d.querySelector('#aud-keep')?.textContent || '')
    && [...d.querySelectorAll('#aud-st option')].some(o => o.textContent === 'Abgelehnt (401 / 403 / 429)'), 'German texts');
  w.close();
  await call('PATCH', '/api/settings', {lang: 'en'});

  // ================= #359: the app sends only known fields
  const before = (logsAll().match(/unknown field\(s\) ignored/g) || []).length;
  w = await boot({user: 'alice', hash: 'l/' + TEAM}); d = w.document;
  await w.eval(`createTask({title: 'From the app', list_id: ${TEAM}, tags: ['x'], due: '${new Date().toISOString().slice(0, 10)}'})`);
  const nt = (await call('GET', '/api/state')).tasks.find(t => t.title === 'From the app');
  check(nt, 'task created in the app');
  w.eval(`openDetail(${nt.id})`); await sleep(800);
  const ti = d.querySelector('#d-title'), co = d.querySelector('#d-content');
  if (ti) { ti.value = 'From the app, renamed'; ti.dispatchEvent(new w.Event('input', {bubbles: true})); }
  if (co) { co.value = 'Notes typed in the app'; co.dispatchEvent(new w.Event('input', {bubbles: true})); }
  await sleep(1400);
  await w.eval(`patchTask(${nt.id}, {priority: 3, pinned: 1})`);
  const ci = d.querySelector('#c-input');
  if (ci) { ci.value = 'A comment from the app'; await w.eval('sendComment()'); }
  await w.eval(`listModal()`); await sleep(400);
  const lm = d.querySelector('#l-name')?.closest('.modal');
  check(lm, 'the new-list dialog');
  if (lm) {
    lm.querySelector('#l-name').value = 'New project';
    const k = lm.querySelector('#l-kind'); if (k) { k.value = 'project'; change(w, k); await sleep(200); }
    const ds = lm.querySelector('#l-depshift'); if (ds) ds.checked = true;
    click(w, lm.querySelector('[data-m="save"]')); await sleep(1200);
  }
  const t2 = (await call('GET', `/api/tasks/${nt.id}`));
  check(t2.title === 'From the app, renamed' && t2.content === 'Notes typed in the app' && t2.priority === 3, 'the edits arrived: ' + JSON.stringify([t2.title, t2.content, t2.priority]));
  const np = (await call('GET', '/api/state')).lists.find(l => l.name === 'New project');
  check(np && np.kind === 'project' && (!lm?.querySelector('#l-depshift') || np.dep_shift === 1), 'new list with "Move dependent tasks along": stored ' + JSON.stringify(np && [np.kind, np.dep_shift]));
  w.close();
  await sleep(300);
  const lg = logsAll(), after = (lg.match(/unknown field\(s\) ignored/g) || []).length;
  check(after === before, 'the app sent no unknown fields: ' + lg.split('\n').filter(x => /unknown field/.test(x)).join(' | '));

  // ================= Firefox: 390 x 844 and 1280 x 800
  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    await nav(B + 'static/icon.svg');
    const lgi = await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    check(lgi === 200, 'Firefox: login');
    for (const [W, Hh, phone] of [[390, 844, true], [1280, 800, false]]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: W, height: Hh}});
      await nav(B + '#today'); await sleep(2500);
      await ev(`settingsModal('activity')`);
      let n = 0;
      for (let i = 0; i < 40 && !n; i++) { n = await ev(`document.querySelectorAll('#s-aud .audr:not(.audh)').length`); if (!n) await sleep(250); }
      check(n > 0, `${W}px: rows`);
      await sleep(600);
      const top0 = await ev(`Math.round(document.querySelector('#s-aud-h').getBoundingClientRect().top - document.querySelector('.spanes').getBoundingClientRect().top)`);
      check(Math.abs(top0) <= 24, `${W}px: opened scrolled to the Activity log (${top0})`);
      const m = await ev(`(() => {
        const t = document.querySelector('#s-aud'), r = t.getBoundingClientRect(), row = t.querySelector('.audr.den') || t.querySelector('.audr:not(.audh)');
        const rt = row.querySelector('.audrt').getBoundingClientRect(), tm = row.querySelector('.audt').getBoundingClientRect(), hd = t.querySelector('.audh');
        const pane = t.closest('.spanes');
        return {overflow: document.documentElement.scrollWidth - innerWidth, tblOver: t.scrollWidth - t.clientWidth, paneOver: pane ? pane.scrollWidth - pane.clientWidth : 0,
          right: r.right, vw: innerWidth, routeBelow: rt.top >= tm.bottom - 1, header: hd ? getComputedStyle(hd).display : 'none',
          den: getComputedStyle(row).boxShadow, ctl: document.querySelector('.audctl').getBoundingClientRect().right};
      })()`);
      check(m.overflow <= 0 && m.tblOver <= 1 && m.paneOver <= 1 && m.right <= m.vw && m.ctl <= m.vw + 1, `${W}px: no horizontal overflow ${JSON.stringify(m)}`);
      check(phone ? m.routeBelow && m.header === 'none' : !m.routeBelow && m.header !== 'none', `${W}px: ${phone ? 'phone: route on its own line, no header' : 'desktop: one line per request, header'} ${JSON.stringify(m)}`);
      check(/inset/.test(m.den || ''), `${W}px: denied row marked (${m.den})`);
      await shot(`p221-audit-${W}.png`);
    }
  });

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
