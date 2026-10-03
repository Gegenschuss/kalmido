// 2.3.0 UI tests, own container (start.sh): agent proposals (#260 #261 #262 #263)
// Entry points only while the person may ask an agent: sidebar "Lists > +" and the command palette ("New project from
// briefing…"), the task menu ("Break down with Claude…"), the list menu ("Tasks from notes…", the inbox: "Sort the inbox
// with Claude…"), the selection bar in the inbox (bot button, only for open main inbox tasks). The request dialogs: the
// consent line names the agent and what it gets, the inbox dialog's list ticks ("All my lists" follows), sending creates the
// job with exactly that input. The review dialog (#prop/<id>, the Agents view button, the News item): one row per entry,
// unticking a task unticks its subtasks, inline edits (title, date, section, assignee, list -> its sections), "Apply n
// entries" -> created as the person, one undo step (histStep undo / redo), Discard. Settings: the notification row (only with
// an agent to ask), the admin's "Proposals for" select. German texts, SW v65. Then Firefox headless (WebDriver BiDi,
// skipped without firefox) at 390 x 844 and 1280 x 800: the four request dialogs and the review dialog fit (no horizontal
// overflow, inside the viewport, the Apply button reachable).
const {spawn, execFileSync} = require('child_process');
const fs = require('fs'), os = require('os'), path = require('path');
const {boot, errs, sleep, B, login} = require('./boot');
const WS = globalThis.WebSocket || require('ws');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const v1 = async (tok, method, url, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + tok}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const change = (w, el) => el && el.dispatchEvent(new w.Event('change', {bubbles: true}));
const input = (w, el, v) => { if (!el) return; el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = fn(); if (x) return x; await sleep(150); } return fn(); };
const menuTexts = d => [...d.querySelectorAll('#pop .menu-list button')].map(b => b.textContent.trim());
const menuClick = (w, d, re) => click(w, [...d.querySelectorAll('#pop .menu-list button')].find(b => re.test(b.textContent)));
const ALL = 'cal,timeline,matrix,habits,pomo,kanban,paperless,collab,stats,time,progress,deps,fields,comments,agents';

async function firefox(fn) {
  try { execFileSync('firefox', ['--version'], {stdio: 'ignore'}); } catch { console.log('p230_ui: Firefox part skipped (no firefox on PATH)'); return; }
  const PORT = 9300 + Math.floor(Math.random() * 600);
  const prof = fs.mkdtempSync(path.join(process.env.TMPDIR || os.tmpdir(), 'kalmido-p230-'));
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
    const shot = async name => { const dir = process.env.P230_SHOTS; if (!dir) return; const r = await cmd('browsingContext.captureScreenshot', {context: ctx}); fs.writeFileSync(path.join(dir, name), Buffer.from(r.data, 'base64')); };
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
  check(/const CACHE = 'tasks-shell-v(?:(6[5-9]|7[0-9])|8[0-9]|9[0-9])'/.test(SW), 'service worker cache v65 (2.4.0: v66, 2.4.1: v67, 2.4.2: v68, 2.5.0: v69, 2.5.1: v70, 2.5.2: v71, 2.6.0: v72, 2.6.1: v73, 2.7.0: v74, 2.7.1: v75, 2.7.2: v76, 2.8.0: v77, 2.9.0: v78, 2.10.0: v79, 2.11.0: v80)');
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en'});
  const bob = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  await call('POST', '/api/users', {username: 'carol', display_name: 'Carol', password: 'password123'});
  const CKB = await login('bob'), CKC = await login('carol');
  for (const ck of [CKB, CKC]) await call('PATCH', '/api/settings', {features: ALL, lang: 'en'}, ck);
  const ag = await call('POST', '/api/admin/agents', {scopes: ['write'], username: 'claude', display_name: 'Claude'});
  const TEAM = (await call('POST', '/api/lists', {name: 'Team'})).id;
  const OTHER = (await call('POST', '/api/lists', {name: 'Other'})).id;
  for (const id of [bob, ag.id]) await call('PUT', `/api/lists/${TEAM}/members`, {user_id: id, role: 'edit'});
  const SEC = (await call('POST', '/api/sections', {list_id: TEAM, name: 'Doing'})).id;
  const T = (await call('POST', '/api/tasks', {title: 'Plan the offsite', list_id: TEAM})).id;
  const I1 = (await call('POST', '/api/tasks', {title: 'call the printer'})).id;
  const I2 = (await call('POST', '/api/tasks', {title: 'gift for mum'})).id;
  const INBOX = (await call('GET', '/api/state')).lists.find(l => l.is_inbox).id;
  const jobs = async () => (await call('GET', '/api/agents/jobs')).jobs;

  // ================= no agent to ask: no entry points
  await call('PATCH', `/api/admin/agents/${ag.id}`, {proposals: 'off'});
  let w = await boot({user: 'alice', hash: 'l/' + TEAM}), d = w.document;
  check(w.eval('propOn()') === false, 'mode off: proposals off');
  w.eval(`taskMenu(document.querySelector('#top h1'), ${T})`);
  check(!menuTexts(d).some(x => /Break down/.test(x)), 'mode off: no "Break down" in the task menu');
  w.eval('closePop()');
  w.close();
  await call('PATCH', `/api/admin/agents/${ag.id}`, {proposals: 'shared'});

  // ================= entry points
  w = await boot({user: 'alice', hash: 'l/' + TEAM}); d = w.document;
  check(w.eval('propOn()') === true && w.eval('S.proposers.length') === 1, 'proposers loaded');
  w.eval(`taskMenu(document.querySelector('#top h1'), ${T})`);
  check(menuTexts(d).some(x => x === 'Break down with Claude…'), 'task menu: Break down with Claude… ' + menuTexts(d).join('|'));
  menuClick(w, d, /Break down with Claude/);
  let md = await until(() => d.querySelector('.modal.ppreq'));
  check(md && /Break down with Claude/.test(md.querySelector('h3').textContent) && /Plan the offsite/.test(md.querySelector('.pptask').textContent), 'break down dialog');
  check(/Claude gets the title and notes of this task/.test(md.querySelector('#pp-priv').textContent), 'consent line: what it gets');
  check(md.querySelector('#pp-agent')?.type === 'hidden', 'one agent: no agent select');
  md.querySelector('#pp-hint').value = 'max 5';
  click(w, md.querySelector('[data-m="ok"]'));
  await until(() => !d.querySelector('.modal.ppreq'));
  let js = await jobs();
  const JB = js.find(j => j.kind === 'subtasks');
  check(JB && JB.task_id === T && JB.proposal_state === 'requested', 'break down: job requested');
  check((await v1(ag.token, 'GET', `/agent/jobs/${JB.id}`)).input?.hint === 'max 5', 'the hint was sent');
  check(/Sent to Claude/.test(d.querySelector('#toast')?.textContent || ''), 'toast: sent');
  w.eval(`listMenu(document.querySelector('#top h1'), ${TEAM})`);
  check(menuTexts(d).includes('Tasks from notes…'), 'list menu: Tasks from notes…');
  menuClick(w, d, /Tasks from notes/);
  md = await until(() => d.querySelector('.modal.ppreq'));
  check(md && /the names of the people in Team/.test(md.querySelector('#pp-priv').textContent), 'notes dialog: consent names the list members');
  click(w, md.querySelector('[data-m="ok"]')); await sleep(300);
  check(d.querySelector('.modal.ppreq') && d.activeElement === md.querySelector('#pp-text'), 'empty notes: not sent, focus in the text');
  md.querySelector('#pp-text').value = 'Bob books the studio.';
  click(w, md.querySelector('[data-m="ok"]'));
  await until(() => !d.querySelector('.modal.ppreq'));
  w.eval(`listMenu(document.querySelector('#top h1'), ${INBOX})`);
  check(menuTexts(d).includes('Sort the inbox with Claude…') && !menuTexts(d).includes('Tasks from notes…'), 'inbox menu: Sort the inbox with Claude…');
  w.eval('closePop()');
  click(w, d.querySelector('[data-act="list-new"]')); await sleep(200);
  check(menuTexts(d).includes('New project from briefing…'), 'Lists > +: New project from briefing…');
  menuClick(w, d, /New project from briefing/);
  md = await until(() => d.querySelector('.modal.ppreq'));
  check(md && md.querySelector('#pp-file') && /\.txt/.test(md.querySelector('#pp-file').getAttribute('accept')), 'project dialog: text file picker');
  md.querySelector('#pp-text').value = 'Image film for ACME, shoot in May.';
  md.querySelector('#pp-folder').value = 'Clients';
  click(w, md.querySelector('[data-m="ok"]'));
  await until(() => !d.querySelector('.modal.ppreq'));
  w.eval('openPalette()'); const pin = d.querySelector('.pqin'); pin.value = 'briefing'; pin.dispatchEvent(new w.Event('input', {bubbles: true})); await sleep(150);
  check([...d.querySelectorAll('.pitem .plt')].some(x => x.textContent === 'New project from briefing…'), 'palette: New project from briefing…');
  pin.value = 'notes'; pin.dispatchEvent(new w.Event('input', {bubbles: true})); await sleep(150);
  check([...d.querySelectorAll('.pitem .plt')].some(x => x.textContent === 'Tasks from notes…'), 'palette (in a list): Tasks from notes…');
  w.eval('closePalette()');
  w.close();
  js = await jobs();
  const JP = js.find(j => j.kind === 'project'), JX = js.find(j => j.kind === 'extract');
  check(JP && (await v1(ag.token, 'GET', `/agent/jobs/${JP.id}`)).input?.folder === 'Clients', 'project job with the folder');
  check(JX && (await v1(ag.token, 'GET', `/agent/jobs/${JX.id}`)).input?.text === 'Bob books the studio.', 'notes job with the text');

  // ================= the inbox selection
  w = await boot({user: 'alice', hash: 'inbox'}); d = w.document;
  w.eval(`S.multi.add(${I1}); S.multi.add(${I2}); renderMultiBar()`);
  const mb = d.querySelector('#mbar [data-act="mb-sort"]');
  check(mb && /Sort with Claude/.test(mb.getAttribute('title')), 'selection bar: Sort with Claude…');
  click(w, mb);
  md = await until(() => d.querySelector('.modal.ppreq'));
  check(md && /2 inbox items/.test(md.querySelector('.pptask').textContent) && /titles and notes of these 2 inbox items/.test(md.querySelector('#pp-priv').textContent), 'triage dialog: 2 items, consent');
  const boxes = [...md.querySelectorAll('#pp-lists [data-lid]')];
  check(boxes.length === 2 && boxes.every(b => b.checked) && md.querySelector('#pp-lall').checked, 'all my lists ticked');
  const bo = boxes.find(b => +b.dataset.lid === OTHER); bo.checked = false; change(w, bo);
  check(!md.querySelector('#pp-lall').checked, 'unticking one clears "All my lists"');
  click(w, md.querySelector('[data-m="ok"]'));
  await until(() => !d.querySelector('.modal.ppreq'));
  check(w.eval('S.multi.size') === 0, 'selection cleared after sending');
  w.eval(`S.multi.add(${T}); renderMultiBar()`);
  check(!d.querySelector('#mbar [data-act="mb-sort"]'), 'not for a task outside the inbox');
  w.close();
  const JT = (await jobs()).find(j => j.kind === 'triage');
  const tin = (await v1(ag.token, 'GET', `/agent/jobs/${JT.id}`)).input;
  check(tin.items.map(x => x.task_id).sort().join() === [I1, I2].sort().join() && tin.lists.map(l => l.id).join() === String(TEAM), 'triage input: the 2 items + Team only');

  // ================= the review dialog: project
  const PROP = {name: 'ACME film', sections: ['Pre', 'Shoot'], summary: 'Two **phases**.',
    tasks: [{title: 'Treatment', section: 'Pre', due: '2031-05-01', priority: 'high', subtasks: [{title: 'Research'}, {title: 'Draft'}]},
      {title: 'Shoot day', section: 'Shoot', depends_on: [0]}, {title: 'Deliver', depends_on: [1]}]};
  check((await v1(ag.token, 'POST', `/agent/jobs/${JP.id}/proposal`, PROP)).status === 201, 'agent: project proposal');
  const news = (await call('GET', '/api/news')).items.find(n => n.kind === 'proposal');
  check(news && news.data.job === JP.id, 'News item');
  w = await boot({user: 'alice', hash: 'news'}); d = w.document;
  check(/Claude has a proposal for you: Project from a briefing/.test(d.querySelector('#view').textContent), 'News text');
  w.close();
  w = await boot({user: 'alice', hash: 'prop/' + JP.id}); d = w.document;
  md = await until(() => d.querySelector('.modal.ppm'));
  check(md && /Project from a briefing/.test(md.querySelector('h3').textContent) && /Proposal ready/.test(md.querySelector('.pphead').textContent), '#prop/<id> opens the review dialog');
  check(md.querySelector('.ppsum b')?.textContent === 'phases', 'summary rendered (Markdown)');
  check(md.querySelector('#pp-name').value === 'ACME film' && md.querySelector('#pp-share') && !md.querySelector('#pp-share').checked, 'name + share option (off)');
  let rows = [...md.querySelectorAll('.ppi')];
  check(rows.length === 5 && rows.filter(r => r.classList.contains('sub')).length === 2 && rows.every(r => r.querySelector('.ppc').checked), 'five rows, subtasks indented, all ticked');
  check(/5 of 5 selected/.test(md.querySelector('.ppcount').textContent) && /Apply 5 entries/.test(md.querySelector('[data-pp="apply"]').textContent), 'count + Apply button');
  check(/waits on “Treatment”/.test(rows[3].textContent) && rows[0].querySelector('.flag-5'), 'dependency + priority chips');
  check(rows[0].querySelector('[data-dpfor="ppd-0"]') && rows[0].querySelector('select[data-f="section"]').value === 'Pre', 'own date picker + section select');
  const c0 = rows[0].querySelector('.ppc'); c0.checked = false; change(w, c0);
  rows = [...md.querySelectorAll('.ppi')];
  check(!rows[1].querySelector('.ppc').checked && !rows[2].querySelector('.ppc').checked && rows[1].classList.contains('off'), 'unticking a task unticks its subtasks');
  const c2 = rows[2].querySelector('.ppc'); c2.checked = true; change(w, c2);
  check(rows[0].querySelector('.ppc').checked && /4 of 5/.test(md.querySelector('.ppcount').textContent), 'ticking a subtask ticks its task');
  input(w, rows[0].querySelector('.ppt'), 'Write the treatment');
  w.eval(`dpSet(document.querySelector('#ppd-1'), '2031-05-12')`);
  const s3 = rows[3].querySelector('select[data-f="section"]'); s3.value = 'Pre'; change(w, s3);
  input(w, md.querySelector('#pp-name'), 'ACME image film');
  md.querySelector('#pp-share').checked = true;
  click(w, md.querySelector('[data-pp="apply"]'));
  await until(() => !d.querySelector('.modal.ppm'), 60);
  let st = await call('GET', '/api/state');
  const PL = st.lists.find(l => l.name === 'ACME image film');
  check(PL && PL.kind === 'project' && PL.role === 'owner', 'applied: my new project list');
  const pt = st.tasks.filter(t => PL && t.list_id === PL.id);
  check(pt.map(t => t.title).sort().join('|') === 'Deliver|Draft|Shoot day|Write the treatment', 'applied: the selected entries (edited): ' + pt.map(t => t.title).join('|'));
  check(pt.find(t => t.title === 'Shoot day')?.due === '2031-05-12', 'date edit applied');
  check(/entries created/.test(d.querySelector('#toast')?.textContent || '') && d.querySelector('#toast [data-act], #toast button'), 'toast with Undo');
  check(w.eval('HIST.undo[HIST.undo.length - 1].label') === 'Applied the proposal of Claude', 'one history step');
  await w.eval(`histStep('undo')`); await sleep(400);
  st = await call('GET', '/api/state');
  check(!st.lists.some(l => l.name === 'ACME image film'), 'undo: the project is gone');
  await w.eval(`histStep('redo')`); await sleep(400);
  st = await call('GET', '/api/state');
  check(st.lists.some(l => l.name === 'ACME image film'), 'redo: back');
  w.close();

  // ================= review: triage (list -> sections), extract (assignee), discard; Agents view
  await v1(ag.token, 'POST', `/agent/jobs/${JT.id}/proposal`, {items: [{task_id: I1, list_id: TEAM, section_id: SEC, tags: ['print']}, {task_id: I2, rewrite_title: 'Gift for Mum'}]});
  await v1(ag.token, 'POST', `/agent/jobs/${JX.id}/proposal`, {tasks: [{title: 'Book the studio', assignee_id: bob, section: 'Studio'}]});
  w = await boot({user: 'alice', hash: 'agents'}); d = w.document;
  await until(() => d.querySelector('[data-act="prop-open"]'));
  const rv = [...d.querySelectorAll('[data-act="prop-open"]')];
  check(rv.length >= 3 && rv.some(b => /Review the proposal/.test(b.textContent)) && rv.some(b => /Open/.test(b.textContent)), 'Agents view: Review / Open buttons');
  check(![...d.querySelectorAll('.job')].some(j => /Break down/.test(j.textContent) && j.querySelector('[data-a="approve"]')), 'no Approve on proposal jobs');
  click(w, rv.find(b => +b.dataset.jid === JT.id));
  md = await until(() => d.querySelector('.modal.ppm'));
  rows = [...md.querySelectorAll('.ppi')];
  check(rows.length === 2 && rows[1].querySelector('.ppo')?.textContent === 'gift for mum' && rows[1].querySelector('.ppt').value === 'Gift for Mum', 'triage: old title struck through, new title editable');
  const ls = rows[0].querySelector('select[data-f="list_id"]'), ss = () => rows[0].querySelector('select[data-f="section_id"]');
  check(+ls.value === TEAM && +ss().value === SEC && !ss().hidden, 'triage: list + section preselected');
  ls.value = ''; change(w, ls);
  check(ss().hidden, 'triage: "Stay in the inbox" hides the sections');
  ls.value = String(TEAM); change(w, ls);
  check(!ss().hidden && ss().value === '', 'triage: list changed -> its sections');
  const r1 = rows[1].querySelector('.ppc'); r1.checked = false; change(w, r1);
  click(w, md.querySelector('[data-pp="apply"]'));
  await until(() => !d.querySelector('.modal.ppm'), 60);
  let t1 = await call('GET', `/api/tasks/${I1}`), t2 = await call('GET', `/api/tasks/${I2}`);
  check(t1.list_id === TEAM && t1.section_id === null && t2.title === 'gift for mum', 'triage applied: only the ticked one, section edit (none)');
  check(/inbox item sorted/.test(d.querySelector('#toast')?.textContent || ''), 'toast: sorted');
  await w.eval(`histStep('undo')`); await sleep(400);
  t1 = await call('GET', `/api/tasks/${I1}`);
  check(t1.list_id === INBOX, 'triage undo: back in the inbox');
  w.eval(`propOpen(${JX.id})`);
  md = await until(() => d.querySelector('.modal.ppm'));
  const as = md.querySelector('select[data-f="assignee_id"]'), sx = md.querySelector('.ppi select[data-f="section"]');
  check(as && +as.value === bob && [...as.options].map(o => o.textContent).join('|') === 'Nobody|Alice|Bob', 'extract: assignee select (members)');
  check(sx && /Studio \(new\)/.test(sx.selectedOptions[0].textContent) && [...sx.options].some(o => o.textContent === 'Doing'), 'extract: sections incl. a new one');
  click(w, md.querySelector('[data-pp="discard"]'));
  await until(() => !d.querySelector('.modal.ppm'), 60);
  check((await call('GET', `/api/proposals/${JX.id}`)).state === 'discarded', 'discard (confirmed)');
  w.eval(`propOpen(${JX.id})`);
  md = await until(() => d.querySelector('.modal.ppm'));
  check(/Discarded\. Claude was told\./.test(md.textContent) && !md.querySelector('[data-pp="apply"]'), 'a discarded proposal: read-only');
  w.close();

  // ================= settings: notification row, admin select; others
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  w.eval(`settingsModal('notify')`); await sleep(700);
  check(d.querySelector('[data-nm="proposal"][data-ch="push"]')?.checked && /A proposal I asked an agent for is ready/.test(d.querySelector('#sp-notify').textContent), 'notification row (on)');
  w.close();
  w = await boot({user: 'carol', hash: 'today'}); d = w.document;
  w.eval(`settingsModal('notify')`); await sleep(700);
  check(!d.querySelector('[data-nm="proposal"]') && w.eval('propOn()') === false, 'carol (no agent to ask): no row, no proposals');
  w.close();
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  const ad = (await call('GET', '/api/admin/agents')).agents.find(a => a.id === ag.id);
  w.eval(`agModal(${JSON.stringify(ad)}, null)`);
  const sel = await until(() => d.querySelector('#ag-prop'));
  check(sel && sel.value === 'shared' && [...sel.options].map(o => o.value).join() === 'shared,all,off', 'admin: Proposals for');
  sel.value = 'all'; click(w, sel.closest('.modal').querySelector('[data-m="ok"]'));
  await until(() => !d.querySelector('#ag-prop'));
  check((await call('GET', '/api/admin/agents')).agents.find(a => a.id === ag.id).proposals === 'all', 'admin: saved');
  w.close();
  w = await boot({user: 'carol', hash: 'today'});
  check(w.eval('propOn()') === true, 'mode all: carol may ask now');
  w.close();

  // ================= German
  await call('PATCH', '/api/settings', {lang: 'de'});
  w = await boot({user: 'alice', hash: 'l/' + TEAM}); d = w.document;
  w.eval(`taskMenu(document.querySelector('#top h1'), ${T})`);
  check(menuTexts(d).includes('Mit Claude aufteilen …'), 'German: Mit Claude aufteilen …');
  menuClick(w, d, /Mit Claude aufteilen/);
  md = await until(() => d.querySelector('.modal.ppreq'));
  check(/Claude bekommt Titel und Notizen dieser Aufgabe/.test(md.textContent) && /Vorschlag anfordern/.test(md.textContent), 'German: dialog');
  w.close();
  await call('PATCH', '/api/settings', {lang: 'en'});

  // ================= Firefox: 390 x 844 and 1280 x 800
  const RP = (await call('POST', '/api/proposals', {agent_id: ag.id, kind: 'project', text: 'Layout check'})).id;
  await v1(ag.token, 'POST', `/agent/jobs/${RP}/proposal`, {name: 'A rather long project name for the layout check', sections: ['Pre-production and planning', 'Post'],
    tasks: Array.from({length: 8}, (_, i) => ({title: `Task ${i + 1} with a fairly long title that has to wrap or cut somewhere sensible`, section: i % 2 ? 'Post' : 'Pre-production and planning',
      due: '2031-05-0' + (i + 1), priority: i % 3 ? 'medium' : 'high', notes: 'Some notes '.repeat(20), depends_on: i ? [i - 1] : [], subtasks: i < 2 ? [{title: 'Sub A'}, {title: 'Sub B'}] : []}))});
  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    await nav(B + 'static/icon.svg');
    const lgi = await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    check(lgi === 200, 'Firefox: login');
    const fit = sel => ev(`(() => { const c = document.querySelector('${sel} .card'); if (!c) return null; const r = c.getBoundingClientRect();
      const over = [...c.querySelectorAll('*')].filter(e => e.getBoundingClientRect().right > r.right + 1 && getComputedStyle(e).position !== 'fixed' && !e.closest('select')).length;
      return {doc: document.documentElement.scrollWidth - innerWidth, card: c.scrollWidth - c.clientWidth, left: r.left, right: r.right, vw: innerWidth, top: r.top, bottom: r.bottom, vh: innerHeight, over}; })()`);
    for (const [W, Hh] of [[390, 844], [1280, 800]]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: W, height: Hh}});
      await nav(B + '#l/' + TEAM); await sleep(2500);
      for (const [k, arg] of [['project', '{}'], ['subtasks', `{tid: ${T}}`], ['triage', `{ids: [${I1}, ${I2}]}`], ['extract', `{lid: ${TEAM}}`]]) {
        await ev(`propRequest('${k}', ${arg})`); await sleep(300);
        const m = await fit('.ppreq');
        check(m && m.doc <= 0 && m.card <= 1 && m.left >= 0 && m.right <= m.vw && m.bottom <= m.vh + 1 && m.over === 0, `${W}px: ${k} dialog fits ${JSON.stringify(m)}`);
        await shot(`p230-req-${k}-${W}.png`);
        await ev(`document.querySelector('.ppreq').remove()`);
      }
      await ev(`propOpen(${RP})`); await sleep(900);
      const m = await fit('.ppm');
      check(m && m.doc <= 0 && m.card <= 1 && m.left >= 0 && m.right <= m.vw && m.over === 0, `${W}px: review dialog fits ${JSON.stringify(m)}`);
      const ap = await ev(`(() => { const c = document.querySelector('.ppm .card'); c.scrollTop = c.scrollHeight; const b = document.querySelector('[data-pp="apply"]').getBoundingClientRect(); return {bottom: b.bottom, right: b.right, vh: innerHeight, vw: innerWidth}; })()`);
      check(ap.bottom <= ap.vh && ap.right <= ap.vw, `${W}px: Apply reachable ${JSON.stringify(ap)}`);
      const rw = await ev(`(() => { const r = document.querySelector('.ppi'), t = r.querySelector('.ppt').getBoundingClientRect(), b = r.getBoundingClientRect(); return {t: t.right, b: b.right}; })()`);
      check(rw.t <= rw.b, `${W}px: title field inside its row`);
      await ev(`document.querySelector('.ppm .card').scrollTop = 0`);
      await shot(`p230-review-${W}.png`);
      await ev(`document.querySelector('.ppm').remove()`);
    }
  });

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
