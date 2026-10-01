// 2.4.1 UI tests, own container (start.sh): agent runtime settings (#377), one tidy agent per list (#379), the agent's state
// in the chat header (#375), no "Wake agent" button (#376).
// The admin's agent dialog: section "Runtime" (model with suggestions, auto-compact on / off + percentage, nightly fresh restart
// with the own time picker, "Reset now" with a confirm), saving sends runtime, a bad percentage is refused in the dialog. The list
// dialog's "Tidy up by" (only agents with edit rights, disabled while tidy is off) and the same choice in Settings > AI colleague's
// list table. The chat header: dot + ready, typing dots from the agent's typing signal (and gone once it runs out), working on #id
// (a link to the task), waiting for you, limit reached, paused, offline (no poll for 5 minutes), the typing line under the
// messages; no Wake button in the task panel, the Agents view or the chat. #385: the task panel's footer has no Delete / Track
// time (they are in the task's "…" menu, Delete with undo); nothing destructive near the comment box's Send. German texts, SW v67. Then Firefox headless (WebDriver
// BiDi, skipped without firefox) at 390 x 844 and 1280 x 800: the runtime section, the list dialog's tidy select, the chat header
// and the task panel (#385: no destructive button near Send) fit (no horizontal overflow, inside the viewport).
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
  try { execFileSync('firefox', ['--version'], {stdio: 'ignore'}); } catch { console.log('p241_ui: Firefox part skipped (no firefox on PATH)'); return; }
  const PORT = 9300 + Math.floor(Math.random() * 600);
  const prof = fs.mkdtempSync(path.join(process.env.TMPDIR || os.tmpdir(), 'kalmido-p241-'));
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
    const shot = async name => { const dir = process.env.P241_SHOTS; if (!dir) return; const r = await cmd('browsingContext.captureScreenshot', {context: ctx}); fs.writeFileSync(path.join(dir, name), Buffer.from(r.data, 'base64')); };
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
  check(/const CACHE = 'tasks-shell-v(6[7-9]|70)'/.test(SW), 'service worker cache v67 (2.4.2: v68, 2.5.0: v69, 2.5.1: v70)');
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en'});
  const me = (await call('GET', '/api/state')).me.id;
  const ag = await call('POST', '/api/admin/agents', {username: 'claude', display_name: 'Claude'});
  const ag2 = await call('POST', '/api/admin/agents', {username: 'helper', display_name: 'Helper'});
  const ag3 = await call('POST', '/api/admin/agents', {username: 'robo', display_name: 'Robo'});
  const L = (await call('POST', '/api/lists', {name: 'Household'})).id;
  for (const [id, role] of [[ag3.id, 'participant'], [ag.id, 'edit'], [ag2.id, 'edit']]) await call('PUT', `/api/lists/${L}/members`, {user_id: id, role});
  const T = (await call('POST', '/api/tasks', {title: 'Fix the dripping tap', list_id: L})).id;
  const adm = async id => (await call('GET', '/api/admin/agents')).agents.find(a => a.id === id);

  // ================= #377 the Runtime section of the agent dialog
  let w = await boot({user: 'alice', hash: 'today'}), d = w.document;
  w.eval(`agModal(${JSON.stringify(await adm(ag.id))}, null)`);
  let md = await until(() => d.querySelector('#ag-model')?.closest('.modal'));
  check(md && /Runtime/.test(md.querySelector('#ag-rt-h')?.textContent || ''), 'agent dialog: section Runtime');
  check([...d.querySelectorAll('#ag-models option')].map(o => o.value).join() === 'opus,sonnet,haiku' && md.querySelector('#ag-model').getAttribute('list') === 'ag-models', 'model suggestions opus, sonnet, haiku');
  check(md.querySelector('#ag-model').value === '' && /Agent default/.test(md.querySelector('#ag-model').placeholder), 'model empty = agent default');
  check(md.querySelector('#ag-ac').checked && !md.querySelector('#ag-acp').disabled && md.querySelector('#ag-acp').value === '', 'auto-compact on, no percentage');
  check(md.querySelector('#ag-nr')?.type === 'hidden' && md.querySelector('[data-dpfor="ag-nr"]') && !md.querySelector('input[type="time"],input[type="date"]'), 'nightly restart: own time picker, no native input');
  check(/Off/.test(md.querySelector('[data-dpfor="ag-nr"]').textContent), 'nightly restart: Off');
  check(md.querySelector('[data-m="reset"]') && /Reset now/.test(md.querySelector('[data-m="reset"]').textContent), 'Reset now button');
  md.querySelector('#ag-ac').checked = false; change(w, md.querySelector('#ag-ac'));
  check(md.querySelector('#ag-acp').disabled, 'auto-compact off: the percentage is disabled');
  md.querySelector('#ag-ac').checked = true; change(w, md.querySelector('#ag-ac'));
  md.querySelector('#ag-acp').value = '5';
  click(w, md.querySelector('[data-m="ok"]')); await sleep(500);
  check(d.querySelector('#ag-model') && !md.querySelector('#ag-err').hidden && /10 to 100/.test(md.querySelector('#ag-err').textContent), 'percentage 5: refused in the dialog');
  md.querySelector('#ag-model').value = 'sonnet'; md.querySelector('#ag-acp').value = '70';
  w.eval(`dpSet(document.querySelector('#ag-nr'), '04:00')`);
  click(w, md.querySelector('[data-m="ok"]'));
  await until(() => !d.querySelector('#ag-model'));
  let a = await adm(ag.id);
  const srt = o => JSON.stringify(Object.keys(o || {}).sort().map(k => [k, o[k]]));
  check(srt(a.runtime) === srt({model: 'sonnet', autocompact: true, autocompact_pct: 70, nightly_reset: '04:00', reset_seq: 0}), 'saved: ' + JSON.stringify(a.runtime));
  check((await v1(ag.token, 'GET', '/agent')).runtime?.model === 'sonnet', 'the agent reads it');
  // reopen: values shown, Reset now
  w.eval(`agModal(${JSON.stringify(a)}, null)`);
  md = await until(() => d.querySelector('#ag-model')?.closest('.modal'));
  check(md.querySelector('#ag-model').value === 'sonnet' && md.querySelector('#ag-acp').value === '70' && md.querySelector('#ag-nr').value === '04:00', 'reopened: the values');
  let asked = ''; w.confirm = m => { asked = m; return true; };
  click(w, md.querySelector('[data-m="reset"]')); await sleep(900);
  check(/Reset Claude now\?/.test(asked) && (await adm(ag.id)).runtime.reset_seq === 1, 'Reset now after a confirm: reset_seq 1');
  check((await v1(ag.token, 'GET', '/agent/events?since=0')).data.some(e => e.event === 'reset'), 'event reset');
  check(/Claude gets a fresh session/.test(d.querySelector('#toast')?.textContent || ''), 'toast');
  click(w, md.querySelector('[data-m="close"]'));
  w.close();

  // ================= #379 Tidy up by: list dialog + AI colleague table
  w = await boot({user: 'alice', hash: 'l/' + L}); d = w.document;
  w.eval(`listModal(${L})`); await sleep(600);
  let sel = d.querySelector('#l-tidyag');
  check(sel && [...sel.options].map(o => o.textContent).join() === 'Claude,Helper' && sel.disabled, 'list dialog: Tidy up by (Claude, Helper; not the participant Robo), disabled while off');
  change(w, d.querySelector('#l-tidy'), 'suggest'); await sleep(1000);
  sel = d.querySelector('#l-tidyag');
  check(sel && !sel.disabled && sel.value === String(ag.id), 'tidy on: the select is live, Claude by default');
  change(w, sel, String(ag2.id)); await sleep(1000);
  check((await call('GET', '/api/state')).lists.find(l => l.id === L).tidy_agent_id === ag2.id, 'saved: Helper tidies up');
  check(/Helper turns long/.test(d.querySelector('#l-tidyrow .lhint')?.textContent || ''), 'hint names the tidy agent');
  w.close();
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  w.eval(`settingsModal('ai')`); await sleep(500);
  click(w, d.querySelector('.smodal [data-aisub="lists"]')); await sleep(1000);  // 2.5.1 (#393): the sub-tab Lists
  const row = d.querySelector(`#s-ai-tbl .airow[data-lid="${L}"]`);
  sel = row?.querySelector('select[data-aitidyag]');
  check(sel && sel.value === String(ag2.id) && [...sel.options].length === 2, 'AI colleague table: Tidy up by select');
  change(w, sel, String(ag.id)); await sleep(1200);
  check((await call('GET', '/api/state')).lists.find(l => l.id === L).tidy_agent_id === ag.id, 'table: saved');
  w.close();

  // ================= #375 the chat header, #376 no Wake button
  const L2 = (await call('POST', '/api/lists', {name: 'Chat'})).id;
  await call('PUT', `/api/lists/${L2}/members`, {user_id: ag.id, role: 'edit'});
  const T2 = (await call('POST', '/api/tasks', {title: 'Write the offer', list_id: L2})).id;
  await v1(ag.token, 'GET', '/agent/events?since=0');  // online
  w = await boot({user: 'alice', hash: 'agents'}); d = w.document;
  check(d.querySelector('.agcard') && !d.querySelector('[data-act="agent-wake"]') && !/Wake/.test(d.querySelector('#view').textContent), 'Agents view: no Wake button');
  w.eval(`chatOpen(${ag.id})`); await sleep(900);
  const hd = () => d.querySelector('#achat .chath');
  const st = () => d.querySelector('#chat-st');
  check(hd() && !hd().querySelector('[data-act="agent-wake"]') && hd().querySelectorAll('button').length === 1, 'chat header: no Wake button (only close)');
  check(st() && /ready/.test(st().textContent) && st().querySelector('.adot.st-idle') && !st().querySelector('.atdots'), 'ready: green dot, no typing dots');
  await v1(ag.token, 'POST', '/agent/typing', {chat_user_id: me});
  w.eval('load().then(render)'); await sleep(800);
  check(st().querySelector('.atdots') && /writing …/.test(st().textContent) && !d.querySelector('#chat-typing').classList.contains('hidden'), 'typing signal: dots in the header + the line under the messages');
  w.eval('S.agentsAt -= 11000; agentLive()');
  check(!st().querySelector('.atdots') && d.querySelector('#chat-typing').classList.contains('hidden'), 'after 10 s: the dots are gone (no server round trip)');
  await v1(ag.token, 'POST', `/agent/chats/${me}`, {body: 'Hi Alice'});  // the answer ends the typing signal
  await v1(ag.token, 'PUT', '/agent/status', {status: 'working', task_id: T2, text: 'Drafting'});
  w.eval('load().then(render)'); await sleep(800);
  const lk = st().querySelector(`button[data-act="open-id"][data-id="${T2}"]`);
  check(lk && lk.textContent === '#' + T2 && /working on #\d+ · Drafting/.test(st().textContent), 'working on #id (a link) + status text: ' + st().textContent);
  check(!st().querySelector('.atdots'), 'working on a task this chat is not about: no dots');
  await v1(ag.token, 'POST', `/agent/chats/${me}`, {body: 'About this one', task_id: T2});
  w.eval('load().then(render)'); await sleep(1000);
  check(st().querySelector('.atdots'), 'working on a task of this chat: dots');
  click(w, st().querySelector('[data-act="open-id"]')); await sleep(800);
  check(w.eval('S.sel') === T2, 'the #id opens the task');
  await v1(ag.token, 'PUT', '/agent/status', {status: 'waiting'});
  w.eval('load().then(render)'); await sleep(800);
  check(/waiting for you/.test(st().textContent) && st().querySelector('.adot.st-waiting'), 'waiting for you');
  w.eval(`agentById(${ag.id}).online = true; agentById(${ag.id}).poll_age = 290; S.agentsAt = Date.now() - 20000; agentLive()`);
  check(/offline/.test(st().textContent) && st().querySelector('.adot.st-offline'), 'offline: 5 minutes without a poll (counted on the client)');
  await call('PATCH', `/api/admin/agents/${ag.id}`, {limits: {period: 'day', metric: 'tokens', hard: 10}});
  await v1(ag.token, 'POST', '/agent/usage', {model: 'x', input_tokens: 100, output_tokens: 1});
  await v1(ag.token, 'GET', '/agent/events?since=0');
  w.eval('load().then(render)'); await sleep(800);
  check(/limit reached/.test(st().textContent) && st().classList.contains('st-limit'), 'limit reached: ' + st().textContent);
  await call('PATCH', `/api/admin/agents/${ag.id}`, {limits: null, enabled: false});
  w.eval('load().then(render)'); await sleep(800);
  check(/paused/.test(st().textContent), 'paused');
  await call('PATCH', `/api/admin/agents/${ag.id}`, {enabled: true});
  await v1(ag.token, 'PUT', '/agent/status', {status: 'idle'});
  w.eval('chatClose()');
  w.eval(`openDetail(${T2})`); await sleep(900);
  check(d.querySelector('#detail') && !d.querySelector('[data-act="agent-wake"]') && !/Wake Claude/.test(d.querySelector('#detail').textContent), 'task panel: no Wake button');
  // ================= #385 nothing destructive next to Send: Delete / Track time moved from the footer into "…"
  await call('PATCH', `/api/lists/${L2}`, {kind: 'project'});
  const T3 = (await call('POST', '/api/tasks', {title: 'Delete me from the menu', list_id: L2})).id;
  w.eval('load().then(render)'); await sleep(700);
  w.eval(`openDetail(${T3})`); await sleep(900);
  const foot = d.querySelector('#detail .dfoot');
  check(foot && !foot.querySelector('[data-act="delete"], [data-act="timer-toggle"], .danger') && d.querySelector('#detail [data-act="c-send"]'), 'task panel footer: no Delete / Track time (Send is there)');
  click(w, d.querySelector('#detail [data-act="task-menu"]')); await sleep(200);
  const items = [...d.querySelectorAll('#pop .menu-list button')].map(b => b.textContent.trim());
  check(items.includes('Delete') && items.includes('Start time tracking'), '"…" menu: Delete + Start time tracking: ' + items.join('|'));
  click(w, [...d.querySelectorAll('#pop .menu-list button')].find(b => b.textContent.trim() === 'Delete')); await sleep(900);
  check((await call('GET', `/api/tasks/${T3}`)).deleted_at || (await call('GET', '/api/state')).tasks.every(t => t.id !== T3), 'Delete from the menu: in the trash');
  check(/Undo/.test(d.querySelector('#toast button')?.textContent || ''), 'with Undo in the toast');
  w.close();
  // phone: the chat view has the same header
  w = await boot({user: 'alice', hash: 'agents/' + ag.id, mobile: true}); d = w.document; await sleep(600);
  check(d.querySelector('#view .chview #chat-st') && /ready/.test(d.querySelector('#chat-st').textContent), 'phone chat view: state line');
  w.close();

  // ================= German
  await call('PATCH', '/api/settings', {lang: 'de'});
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  w.eval(`agModal(${JSON.stringify(await adm(ag.id))}, null)`);
  md = await until(() => d.querySelector('#ag-model')?.closest('.modal'));
  check(/Laufzeit/.test(md.querySelector('#ag-rt-h').textContent) && /Jetzt zurücksetzen/.test(md.textContent) && /Nächtlicher Neustart/.test(md.textContent) && /Auto-Kompaktieren/.test(md.textContent), 'German: Laufzeit, Jetzt zurücksetzen');
  click(w, md.querySelector('[data-m="close"]'));
  w.eval(`listModal(${L})`); await sleep(600);
  check(/Aufräumen durch/.test(d.querySelector('#l-tidyrow')?.textContent || ''), 'German: Aufräumen durch');
  d.querySelector('.modal [data-m="close"]')?.click();
  await v1(ag.token, 'PUT', '/agent/status', {status: 'working', task_id: T2});
  w.eval('load().then(() => { render(); chatOpen(' + ag.id + '); })'); await sleep(1200);
  check(/arbeitet an #\d+/.test(d.querySelector('#chat-st')?.textContent || ''), 'German: arbeitet an #id: ' + d.querySelector('#chat-st')?.textContent);
  w.eval('chatClose()');
  w.close();
  await call('PATCH', '/api/settings', {lang: 'en'});

  // ================= Firefox: the new parts fit at phone and desktop width
  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    await nav(B + 'static/icon.svg');
    const lgi = await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    check(lgi === 200, 'Firefox: login');
    const fit = sel => ev(`(() => { const c = document.querySelector('${sel}'); if (!c) return null; const r = c.getBoundingClientRect();
      const over = [...c.querySelectorAll('*')].filter(e => e.getBoundingClientRect().right > r.right + 1 && getComputedStyle(e).position !== 'fixed' && !e.closest('select') && e.getBoundingClientRect().width).length;
      return {doc: document.documentElement.scrollWidth - innerWidth, left: r.left, right: r.right, vw: innerWidth, bottom: r.bottom, vh: innerHeight, over}; })()`);
    const good = (m, bottom = true) => m && m.doc <= 0 && m.left >= 0 && m.right <= m.vw + 1 && (!bottom || m.bottom <= m.vh + 1) && m.over === 0;
    for (const [W, Hh] of [[390, 844], [1280, 800]]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: W, height: Hh}});
      await nav(B + '#today'); await sleep(2500);
      await ev(`fetch('/api/admin/agents').then(r => r.json()).then(j => agModal(j.agents.find(a => a.id === ${ag.id}), null))`); await sleep(700);
      await ev(`document.querySelector('#ag-rt-h').scrollIntoView()`); await sleep(200);
      const m1 = await fit('.modal .card');
      check(good(m1, false), `${W}px: agent dialog with Runtime fits ${JSON.stringify(m1)}`);
      const rows = await ev(`(() => { const md = document.querySelector('#ag-model').closest('.card').getBoundingClientRect(); return ['#ag-model', '#ag-acp', '[data-dpfor="ag-nr"]', '[data-m="reset"]'].map(s => { const r = document.querySelector(s).getBoundingClientRect(); return r.left >= md.left - 1 && r.right <= md.right + 1 && r.width > 20; }); })()`);
      check(rows.every(Boolean), `${W}px: runtime fields inside the dialog ${JSON.stringify(rows)}`);
      await shot(`p241-runtime-${W}.png`);
      await ev(`document.querySelector('.modal [data-m="close"]').click()`); await sleep(300);
      await ev(`listModal(${L})`); await sleep(700);
      await ev(`document.querySelector('#l-tidyag').scrollIntoView()`); await sleep(200);
      const m2 = await fit('.modal .card');
      check(good(m2, false), `${W}px: list dialog with Tidy up by fits ${JSON.stringify(m2)}`);
      await shot(`p241-tidyagent-${W}.png`);
      await ev(`document.querySelector('.modal').remove()`);
      if (W < 900) { await nav(B + '#agents/' + ag.id); await sleep(2500); }
      else { await ev(`chatOpen(${ag.id})`); await sleep(1200); }
      const m3 = await fit(W < 900 ? '#view .chath' : '#achat .chath');
      check(good(m3), `${W}px: chat header with "working on #id" fits ${JSON.stringify(m3)}`);
      const one = await ev(`(() => { const s = document.querySelector('#chat-st').getBoundingClientRect(); return s.height < 40 && /working on #/.test(document.querySelector('#chat-st').textContent); })()`);
      check(one, `${W}px: the state is one line`);
      await shot(`p241-chat-${W}.png`);
      if (W >= 900) await ev(`chatClose()`);
      // #385: the task panel at this width: no destructive button near the comment box's Send
      await nav(B + '#l/' + L2); await sleep(2500);
      await ev(`openDetail(${T2})`); await sleep(1200);
      const near = await ev(`(() => { const s = document.querySelector('#detail [data-act="c-send"]'); if (!s) return null; const r = s.getBoundingClientRect();
        return [...document.querySelectorAll('#detail button')].filter(b => (b.classList.contains('danger') || b.dataset.act === 'delete') && b.getBoundingClientRect().width).map(b => { const q = b.getBoundingClientRect(); return Math.hypot(Math.max(0, q.left - r.right, r.left - q.right), Math.max(0, q.top - r.bottom, r.top - q.bottom)); }); })()`);
      check(Array.isArray(near) && near.every(x => x > 96), `${W}px: nothing destructive within 6rem of Send ${JSON.stringify(near)}`);
      await shot(`p241-taskpanel-${W}.png`);
      await ev(`closeDetail()`);
    }
  });
  await v1(ag.token, 'PUT', '/agent/status', {status: 'idle'});

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
