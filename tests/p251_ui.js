// 2.5.1 UI tests, own container (start.sh): Settings > AI colleague in sub-tabs (#393): Agents (cards with at most two facts,
// the usage of today / 7 days, a third line only for a reached limit, Add agent + Setup guide in one row, the explanation
// closed once an agent exists, the module switch only while the module is off), Lists (one hint, "sees n of your m lists",
// first only the shared lists + "Show all (n)", a search above 10 lists, shared first, one tidy select with short labels and
// the tidy agent inline only while tidying is on), Usage (one summary card per agent with the limit bar, the charts behind
// "Details", the top 5 tasks), Log (admins: 20 rows + "Load more" (+50), event polling hidden by default with a switch, the
// summary of today whose denied count filters, task titles instead of bare ids, the filters behind a button on phones);
// each sub-tab loads only when shown, the last one is remembered per device, settingsModal('usage' / 'activity') opens its
// sub-tab; a member: Agents / Lists / Usage without actions. #395: the avatars in the comment list open the mention card
// (people, agents, me), the assignee chip keeps assigning. German texts, SW v70. Then Firefox headless (WebDriver BiDi,
// skipped without firefox) at 390 x 844 and 1280 x 800: every sub-tab without horizontal overflow, the agent cards and the
// tidy selects inside the table, the chart's x-axis labels do not overlap, the log's filters behind the button on the
// phone; the height of every sub-tab is printed (screenshots with P251_SHOTS=<dir>).
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
const change = (w, el, v) => { if (!el) return; if (v !== undefined) el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const ALL = 'cal,timeline,matrix,habits,pomo,kanban,paperless,collab,stats,time,progress,deps,fields,agents,comments';

async function firefox(fn) {
  try { execFileSync('firefox', ['--version'], {stdio: 'ignore'}); } catch { console.log('p251_ui: Firefox part skipped (no firefox on PATH)'); return; }
  const PORT = 9300 + Math.floor(Math.random() * 600);
  const prof = fs.mkdtempSync(path.join(process.env.TMPDIR || os.tmpdir(), 'kalmido-p251-'));
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
    const shot = async name => { const dir = process.env.P251_SHOTS; if (!dir) return; const r = await cmd('browsingContext.captureScreenshot', {context: ctx}); fs.writeFileSync(path.join(dir, name), Buffer.from(r.data, 'base64')); };
    await fn({cmd, ev, nav, ctx, shot});
  } catch (e) { check(false, 'Firefox: ' + e.message); } finally {
    try { ws && ws.close(); } catch { /* gone */ }
    try { ff.kill(); } catch { /* gone */ }
    await sleep(500); fs.rmSync(prof, {recursive: true, force: true});
  }
}

// moves usage rows of an agent back by n days (the API stores today only); the data dir is the container's /data
function backdate(agentId, ids) {
  execFileSync('python3', ['-c', `import sqlite3, sys, json
c = sqlite3.connect(sys.argv[1]); m = json.loads(sys.argv[2])
for rid, d in m.items(): c.execute("UPDATE agent_usage SET day=date(day, ?) WHERE id=?", (f"-{d} days", int(rid)))
c.commit()`, path.join(DATA, 'tasks.db'), JSON.stringify(ids)]);
}

(async () => {
  await sleep(600);
  const SW = await (await fetch(B + 'sw.js')).text();
  check(/const CACHE = 'tasks-shell-v7[0-6]'/.test(SW), 'service worker cache v70 (2.5.2: v71, 2.6.0: v72, 2.6.1: v73, 2.7.0: v74, 2.7.1: v75, 2.7.2: v76)');
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en'});
  const me = (await call('GET', '/api/state')).me.id;
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const CKB = await login('bob');
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en'}, CKB);
  const ag = await call('POST', '/api/admin/agents', {username: 'claude', display_name: 'Claude'});
  const ag2 = await call('POST', '/api/admin/agents', {username: 'helper', display_name: 'Helper'});
  // 25 lists: 9 shared with Claude (2 of them with Helper too), Bob in the first one
  const L = [];
  for (let i = 1; i <= 25; i++) L.push((await call('POST', '/api/lists', {name: `List ${String(i).padStart(2, '0')}`})).id);
  for (const id of L.slice(0, 9)) await call('PUT', `/api/lists/${id}/members`, {user_id: ag.id, role: 'edit'});
  for (const id of L.slice(0, 2)) await call('PUT', `/api/lists/${id}/members`, {user_id: ag2.id, role: 'edit'});
  await call('PUT', `/api/lists/${L[0]}/members`, {user_id: BOB, role: 'edit'});
  const T = (await call('POST', '/api/tasks', {title: 'Write the release notes', list_id: L[0]})).id;
  const tasks = [T];
  for (let i = 1; i <= 7; i++) tasks.push((await call('POST', '/api/tasks', {title: `Task ${i}`, list_id: L[1 + (i % 8)]})).id);
  // comments for #395: Bob, the agent, me
  await call('POST', `/api/tasks/${T}/comments`, {body: 'From Bob'}, CKB);
  await v1(ag.token, 'POST', `/tasks/${T}/comments`, {body: 'From Claude'});
  await call('POST', `/api/tasks/${T}/comments`, {body: 'From Alice'});
  // usage over 30 days + a limit on Claude
  const back = {};
  for (let i = 0; i < 30; i++) {
    const r = await v1(ag.token, 'POST', '/agent/usage', {model: i % 3 ? 'claude-big' : 'claude-small', input_tokens: 1000 + 37 * i, output_tokens: 300 + i, cost_usd: 0.02 + i / 1000, task_id: tasks[i % tasks.length]});
    if (r.id && i) back[r.id] = i;
  }
  await v1(ag2.token, 'POST', '/agent/usage', {model: 'gpt-x', input_tokens: 700, output_tokens: 300, task_id: tasks[1]});
  backdate(ag.id, back);
  await call('PATCH', `/api/admin/agents/${ag.id}`, {limits: {period: 'day', metric: 'tokens', hard: 1000000, soft: 800000}});
  check(Object.keys(back).length === 29, 'usage reports with ids: ' + Object.keys(back).length);
  // the log: 120 polls, 60 reads, 10 x 404, a denied call
  for (let i = 0; i < 120; i++) await v1(ag.token, 'GET', '/agent/events?since=0');
  for (let i = 0; i < 60; i++) await v1(ag.token, 'GET', `/tasks/${T}`);
  for (let i = 0; i < 10; i++) await v1(ag2.token, 'GET', '/tasks/999999');
  await call('PATCH', `/api/admin/agents/${ag.id}`, {enabled: false});
  check((await v1(ag.token, 'GET', '/lists')).status === 403, 'paused: 403');
  await call('PATCH', `/api/admin/agents/${ag.id}`, {enabled: true});

  // ================= #393 admin, desktop: Agents
  let w = await boot({user: 'alice', hash: 'today'}), d = w.document;
  const seen = []; const f0 = w.fetch; w.fetch = (u, o) => { seen.push(String(u)); return f0(u, o); };
  w.eval(`settingsModal('ai')`);
  await until(() => d.querySelectorAll('#s-ags [data-agid]').length === 2);
  let md = d.querySelector('.modal.smodal'), pane = md.querySelector('[data-pane="ai"]');
  const subs = [...pane.querySelectorAll('.aisub [data-aisub]')];
  check(subs.map(b => b.dataset.aisub).join() === 'agents,lists,usage,log,setup' && subs.map(b => b.textContent.trim()).join() === 'Status,Lists,Usage,Log,Set up', 'sub-tabs Status / Lists / Usage / Log / Set up (2.6.0: Agents -> Overview, 2.7.0: Status, 2.7.2: Set up)');
  check(subs[0].getAttribute('aria-selected') === 'true' && !pane.querySelector('#aisp-agents').hidden && ['lists', 'usage', 'log'].every(k => pane.querySelector('#aisp-' + k).hidden), 'Agents first, the others hidden');
  check(pane.querySelector('details.aiexp') && !pane.querySelector('details.aiexp').open && /team member for an AI assistant/.test(pane.querySelector('details.aiexp').textContent), 'explanation closed once an agent exists');
  check(!pane.querySelector('[data-feat="agents"]'), 'no module switch while the module is on');
  const cards = [...pane.querySelectorAll('#s-ags .agsrow')];
  const cc = cards.find(r => /Claude/.test(r.textContent));
  check(cards.length === 2 && cc && /ready · 9 lists/.test(cc.querySelector('.agfacts').textContent.replace(/\s+/g, ' ')), 'agent card: two facts "ready · 9 lists": ' + cc?.querySelector('.agfacts')?.textContent);
  check(cc && !cc.querySelector('.agwarn') && cc.querySelector('.agu') && /Today/.test(cc.querySelector('.agu').textContent) && /7 days/.test(cc.querySelector('.agu').textContent), 'no third line under the limit; the usage of today / 7 days');
  check(cc.querySelectorAll('[data-ag]').length === 3 && /polling only/.test(cc.querySelector('.n').title), 'Test / Edit / Pause; the details in the tooltip');
  const btns = pane.querySelector('#aisp-agents .aibtns');
  check(btns && btns.querySelector('[data-ag="new"]') && btns.querySelector('[data-m="ag-guide"]'), 'Add agent + Setup guide in one row');
  check(!seen.some(u => /agents\/audit/.test(u)) && /Loading/.test(pane.querySelector('#s-ai-tbl').textContent) && !pane.querySelector('#s-aiu').innerHTML.trim(), 'only the Agents data loaded (no log, no list table, no usage charts): ' + seen.filter(u => /api/.test(u)).join(' '));

  // Lists
  click(w, pane.querySelector('[data-aisub="lists"]'));
  await until(() => pane.querySelector('#s-ai-tbl .airow[data-lid]'));
  check(!pane.querySelector('#aisp-lists').hidden && pane.querySelector('#aisp-agents').hidden, 'Lists shown');
  check(/Which lists they see/.test(pane.querySelector('#s-ai-lists-h').textContent) && pane.querySelectorAll('#aisp-lists .shint').length === 1, 'two agents: "Which lists they see", one hint');
  const sr = pane.querySelector(`#s-ai-share [data-aisag="${ag.id}"]`);
  check(sr && /sees 9 of your 25 lists/.test(sr.textContent) && /Share all/.test(sr.textContent) && /New lists automatically/.test(sr.textContent), 'per agent one line: sees 9 of your 25 lists · Share all · New lists automatically');
  const rows = () => [...pane.querySelectorAll('#s-ai-tbl .airow[data-lid]')];
  check(rows().length === 9 && /Show all \(25\)/.test(pane.querySelector('[data-aiall="1"]')?.textContent || ''), 'first only the 9 shared lists + Show all (25): ' + rows().length);
  const q = pane.querySelector('#ai-q');
  check(q, 'a search above 10 lists');
  q.value = 'List 2'; q.dispatchEvent(new w.Event('input', {bubbles: true})); await sleep(100);
  check(rows().length === 6 && rows().every(r => /List 2/.test(r.textContent)), 'search over all lists: ' + rows().length);
  check(pane.querySelector('#ai-q') === q, 'the search box stays while typing');
  q.value = ''; q.dispatchEvent(new w.Event('input', {bubbles: true})); await sleep(100);
  click(w, pane.querySelector('[data-aiall="1"]')); await sleep(100);
  const ids = rows().map(r => +r.dataset.lid);
  check(ids.length === 25 && ids.slice(0, 9).every(id => L.slice(0, 9).includes(id)), 'Show all: 25 lists, the shared ones first');
  check(pane.querySelector('[data-aiall="0"]'), '"Only shared lists" back');
  const r1 = pane.querySelector(`#s-ai-tbl .airow[data-lid="${L[0]}"]`);
  const ts = r1.querySelector('select[data-aitidy]');
  check(ts && [...ts.options].map(o => o.textContent).join() === 'Off,Suggest,Automatically' && /👍/.test(ts.options[1].title), 'one tidy select with short labels (full text in the title)');
  check(!r1.querySelector('select[data-aitidyag]'), 'no tidy agent while off');
  change(w, ts, 'suggest'); await sleep(1200);
  const r1b = pane.querySelector(`#s-ai-tbl .airow[data-lid="${L[0]}"]`);
  check(r1b.querySelector('.aitd select[data-aitidy]') && r1b.querySelector('.aitd select[data-aitidyag]') && pane.querySelector('#s-ai-tbl').classList.contains('two'), 'tidy on + two agents: the tidy agent inline next to it');
  check((await call('GET', '/api/state')).lists.find(l => l.id === L[0]).agent_tidy === 'suggest', 'tidy saved');

  // Usage
  click(w, pane.querySelector('[data-aisub="usage"]'));
  await until(() => pane.querySelector('#s-aiu .aiusum'));
  const us = [...pane.querySelectorAll('#s-aiu .aiusum[data-aiu-agent]')];
  check(us.length === 2 && us[0].querySelectorAll('.aiuk > span').length === 3, 'a summary card per agent: today / 7 days / 30 days');
  check(us[0].querySelector('.aiulim .aiub i') && /hard limit 1M tokens/i.test(us[0].querySelector('.aiulim').textContent), 'the limit as a bar + line: ' + us[0].textContent.replace(/\s+/g, ' '));
  const det = pane.querySelector('#aiu-det');
  check(det && !det.open && det.querySelector('svg.chart') && det.querySelectorAll('.aiutasks [data-aiu-open]').length === 5, 'Details closed; inside: the chart and the top 5 tasks');
  det.open = true; det.dispatchEvent(new w.Event('toggle')); await sleep(50);
  click(w, pane.querySelector('[data-aiu-m="cost"]')); await sleep(300);
  check(pane.querySelector('#aiu-det')?.open && /\$/.test(pane.querySelector('.aiusum').textContent), 'cost view: Details stays open');
  click(w, pane.querySelector('[data-aiu-m="tokens"]')); await sleep(300);

  // Log
  click(w, pane.querySelector('[data-aisub="log"]'));
  await until(() => pane.querySelector('#s-aud .audr:not(.audh)'));
  let lr = [...pane.querySelectorAll('#s-aud .audr:not(.audh)')];
  check(lr.length === 20 && !lr.some(r => /agent\/events/.test(r.textContent)), 'Log: 20 rows, no event polling: ' + lr.length);
  check(pane.querySelector('#aud-poll')?.checked, 'switch "Hide event polling" on');
  const sum = pane.querySelector('#aud-sum');
  const today0 = w.eval('JSON.stringify(S.aud.today)');
  check(/\d+ requests today/.test(sum.textContent) && /\d+ denied/.test(sum.textContent) && /120 event polls hidden/.test(sum.textContent) && JSON.parse(today0).polls === 120, 'summary: ' + sum.textContent + ' ' + today0);
  const tr1 = lr.find(r => r.querySelector('.audi') && r.querySelector('.audi').textContent.includes('#' + T));
  check(tr1 && /Write the release notes/.test(tr1.querySelector('.audi').textContent), 'task title instead of a bare id: ' + tr1?.querySelector('.audi').textContent);
  click(w, pane.querySelector('[data-aud="more"]'));
  await until(() => pane.querySelectorAll('#s-aud .audr:not(.audh)').length > 20);
  check(pane.querySelectorAll('#s-aud .audr:not(.audh)').length === 70, 'Load more: +50');
  click(w, sum.querySelector('[data-aud="denied"]'));
  await until(() => pane.querySelector('#aud-csv').getAttribute('href').includes('status=denied') && pane.querySelectorAll('#s-aud .audr:not(.audh)').length && [...pane.querySelectorAll('#s-aud .audr:not(.audh)')].every(r => r.classList.contains('den')));
  const dr = [...pane.querySelectorAll('#s-aud .audr:not(.audh)')];
  check(dr.length && dr.every(r => r.classList.contains('den')) && pane.querySelector('#aud-st').value === 'denied', 'the denied count filters: ' + dr.length);
  change(w, pane.querySelector('#aud-st'), ''); w.eval(`S.aud.day = ''; audSetDay(document.querySelector('.modal.smodal'))`);
  const sw = pane.querySelector('#aud-poll'); sw.checked = false; change(w, sw);
  await until(() => !/event polls hidden/.test(pane.querySelector('#aud-sum').textContent));
  check(!/event polls hidden/.test(pane.querySelector('#aud-sum').textContent) && w.eval('audQuery()').indexOf('hide_poll') < 0 && w.localStorage.getItem('tasks.audPoll') === '"0"', 'switch off: the polling counts again (remembered)');
  check(!/hide_poll/.test(pane.querySelector('#aud-csv').getAttribute('href')), 'CSV follows the switch');
  const fb = pane.querySelector('[data-aud="filters"]');
  click(w, fb);
  check(pane.querySelector('#aud-ctl').classList.contains('open') && fb.getAttribute('aria-expanded') === 'true', 'the Filter button opens the filters (phones)');
  // remembered sub-tab + direct entries
  md.remove();
  w.eval(`settingsModal('ai')`); await sleep(400);
  check(d.querySelector('.smodal [data-aisub="log"]').getAttribute('aria-selected') === 'true', 'reopened: the last sub-tab (Log)');
  d.querySelector('.smodal').remove();
  w.eval(`settingsModal('usage')`); await sleep(400);
  check(!d.querySelector('.smodal #aisp-usage').hidden, "settingsModal('usage') opens Usage");
  d.querySelector('.smodal').remove();
  w.eval(`settingsModal('agents')`); await sleep(400);
  check(!d.querySelector('.smodal #aisp-agents').hidden, "settingsModal('agents') opens Agents");
  w.close();

  // module off: an admin with agents keeps the page (2.7.0, #405 S2), with a hint; the switch only in Modules
  await call('PATCH', '/api/settings', {features: ALL.replace(',agents', '')});
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  w.eval(`settingsModal('ai')`); await sleep(800);
  check(!d.querySelector('.smodal [data-pane="ai"] [data-feat="agents"]') && d.querySelector('.smodal [data-pane="ai"] .aimodoff'), 'module off: a hint, the switch only in Modules (2.6.0)');
  w.close();
  await call('PATCH', '/api/settings', {features: ALL});

  // ================= member (phone)
  w = await boot({user: 'bob', mobile: true, hash: 'today'}); d = w.document;
  w.eval(`settingsModal('ai')`);
  await until(() => d.querySelector('#s-myags .agsrow'));
  pane = d.querySelector('.smodal [data-pane="ai"]');
  check([...pane.querySelectorAll('[data-aisub]')].map(b => b.dataset.aisub).join() === 'agents,lists,usage,setup', 'bob: Agents / Lists / Usage / Set up, no Log');
  check(pane.querySelectorAll('#s-myags .agsrow').length === 2 && /Claude/.test(pane.querySelector('#s-myags').textContent) && !pane.querySelector('[data-ag]'), 'bob: the agent card, no actions');
  check(!pane.querySelector('[data-ag="new"]') && pane.querySelector('#aisp-agents [data-m="ag-guide"]'), 'bob: Setup guide, no Add agent');
  check(/Which lists it sees|Which lists they see/.test(pane.textContent) && /You do not manage any list yet/.test(pane.querySelector('#aisp-lists').textContent), 'bob: no own list');
  w.close();

  // ================= #395 avatars in the comment list
  w = await boot({user: 'alice', hash: 't/' + T}); d = w.document;
  await until(() => d.querySelectorAll('#d-tl-items .cm').length === 3);
  const cav = uid => d.querySelector(`#d-tl-items .cm .cmav[data-mcard="${uid}"]`);
  check(cav(BOB) && cav(ag.id) && cav(me) && cav(BOB).querySelector('.avatar'), 'every comment avatar is a button');
  click(w, cav(BOB)); await sleep(300);
  let card = d.querySelector('#pop .mcard');
  check(card && /Bob/.test(card.querySelector('.mcn').textContent) && /Member|Edit/i.test(card.textContent), 'Bob\'s avatar: his card: ' + card?.textContent.replace(/\s+/g, ' ').slice(0, 120));
  check([...card.querySelectorAll('[data-mc]')].some(b => b.dataset.mc === 'assign') && [...card.querySelectorAll('[data-mc]')].some(b => b.dataset.mc === 'mention'), 'card actions: Assign this task, Mention');
  w.eval('closePop()');
  click(w, cav(ag.id)); await sleep(300);
  card = d.querySelector('#pop .mcard');
  check(card && /Claude/.test(card.textContent) && card.querySelector('.abadge') && card.querySelector('.mcst'), 'the agent\'s avatar: its card with the state');
  w.eval('closePop()');
  click(w, cav(me)); await sleep(300);
  check(/\(me\)/.test(d.querySelector('#pop .mcard')?.textContent || ''), 'my own avatar: "(me)"');
  w.eval('closePop()');
  check(!d.querySelector('#d-tl-items .cm .chead [data-mcard]') && !d.querySelector('.dassign [data-mcard], #d-assignee [data-mcard]'), 'only the avatar (no other new card spots, the assignee keeps assigning)');
  w.close();

  // ================= German
  await call('PATCH', '/api/settings', {lang: 'de'});
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  w.eval(`settingsModal('activity')`);
  await until(() => d.querySelector('#s-aud .audr:not(.audh)'));
  pane = d.querySelector('.smodal [data-pane="ai"]');
  check([...pane.querySelectorAll('[data-aisub]')].map(b => b.textContent.trim()).join() === 'Status,Listen,Verbrauch,Protokoll,Einrichten', 'German sub-tabs: ' + [...pane.querySelectorAll('[data-aisub]')].map(b => b.textContent.trim()).join());
  check(/Ereignis-Abfragen ausblenden/.test(pane.textContent) && /Anfragen/.test(pane.querySelector('#aud-sum').textContent) && /Welche Listen sie sehen/.test(pane.textContent) && /Agenten sind KI-Teammitglieder/.test(pane.textContent), 'German texts');
  w.close();
  await call('PATCH', '/api/settings', {lang: 'en'});

  // ================= Firefox: every sub-tab at 390 and 1280
  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    await nav(B + 'static/icon.svg');
    const lgi = await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    check(lgi === 200, 'Firefox: login');
    const heights = {};
    for (const [W, Hh, phone] of [[390, 844, true], [1280, 800, false]]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: W, height: Hh}});
      await nav(B + '#today'); await sleep(2500);
      await ev(`localStorage.setItem('tasks.audPoll', '1'); S.aud.poll = true; settingsModal('ai')`); await sleep(400);
      for (const k of ['agents', 'lists', 'usage', 'log']) {
        await ev(`document.querySelector('.smodal [data-aisub="${k}"]').click()`); await sleep(1800);
        if (k === 'lists') { await ev(`document.querySelector('#s-ai-tbl [data-aiall="1"]')?.click()`); await sleep(300); }
        if (k === 'usage') { await ev(`(() => { const x = document.querySelector('#aiu-det'); x.open = true; })()`); await sleep(300); }
        const m = await ev(`(() => {
          const sp = document.querySelector('#sp-ai'), pane = document.querySelector('#aisp-${k}'), r = pane.getBoundingClientRect();
          const over = [...pane.querySelectorAll('*')].filter(e => { const b = e.getBoundingClientRect(); return b.width && b.right > r.right + 1 && !e.closest('select') && getComputedStyle(e).position !== 'fixed'; }).map(e => e.getAttribute('class') || e.tagName).slice(0, 4);
          const cut = [...pane.querySelectorAll('.agsrow .agnm, .aitd select')].filter(e => e.getBoundingClientRect().right > r.right + 1).length
            + [...pane.querySelectorAll('.agsrow .agfacts, .agsrow .agnm')].filter(e => e.scrollWidth > e.clientWidth + 1).length;  // nothing cut off ("ready · 9 l…")
          const ax = [...(pane.querySelector('svg.chart') ? pane.querySelector('svg.chart').querySelectorAll('text.ch-ax') : [])].map(t => t.getBoundingClientRect()), bot = Math.max(0, ...ax.map(b => b.top));
          const labs = ax.filter(b => b.top >= bot - 2).map(b => [b.left, b.right]).sort((a, b) => a[0] - b[0]);
          const overlap = labs.some((x, i) => i && x[0] < labs[i - 1][1] - 0.5);
          const ctl = document.querySelector('#aud-ctl');
          return {doc: document.documentElement.scrollWidth - innerWidth, paneOver: sp.scrollWidth - sp.clientWidth, over, cut, labs: labs.length, overlap,
            h: Math.round(sp.scrollHeight), ctl: ctl ? getComputedStyle(ctl).display : null, sel: [...pane.querySelectorAll('.aitd select')].map(s => Math.round(s.getBoundingClientRect().width)).slice(0, 2)};
        })()`);
        heights[`${k}@${W}`] = m.h;
        check(m.doc <= 0 && m.paneOver <= 1 && !m.over.length && !m.cut, `${W}px ${k}: no horizontal overflow ${JSON.stringify(m)}`);
        if (k === 'usage') check(m.labs >= 3 && !m.overlap, `${W}px: the chart's x-axis labels do not overlap (${m.labs} labels)`);
        if (k === 'lists') check(m.sel.length && m.sel.every(x => x >= 80), `${W}px: the tidy selects are wide enough ${m.sel}`);
        if (k === 'log') check(phone ? m.ctl === 'none' : m.ctl !== 'none', `${W}px: the filters ${phone ? 'behind the button' : 'in one line'} (${m.ctl})`);
        await shot(`p251-${k}-${W}.png`);
      }
      if (phone) {
        await ev(`document.querySelector('[data-aud="filters"]').click()`); await sleep(200);
        check(await ev(`getComputedStyle(document.querySelector('#aud-ctl')).display !== 'none'`), '390px: Filter opens the filters');
      }
      await ev(`document.querySelectorAll('.modal').forEach(m => m.remove())`);
    }
    console.log('p251_ui: heights of the AI colleague sub-tabs (px): ' + JSON.stringify(heights));
    check(heights['agents@1280'] < 1200 && heights['agents@390'] < 2000, 'the default sub-tab (Agents) is short: ' + heights['agents@1280'] + ' / ' + heights['agents@390']);
  });

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  console.log(`p251_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
