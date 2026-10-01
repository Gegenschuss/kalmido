// 2.4.2 UI tests, own container (start.sh): comment order (#386), the Code section only where it helps + "Link code…" (#387),
// clickable @mentions with a card (#389), the folder's List / Matrix switch (#390), per-agent "Share all existing lists" and
// "Share new lists automatically" with warnings, no "Share a list with an agent…" button (#391), the setup guide (#392).
// #386: the toggle next to "With activity" (Oldest / Newest first), saved per user (server), newest first = the list reversed and the
// comment box above the newest comment (not in the sticky bottom), back again. #387: without a repository no section and no menu
// item; with one: a plain task has no section but "Link code…" in its "…" menu (copies the branch name), a bug / feature, an agent
// assignee or linked pull requests show the section (and the menu item goes). #389: <@id> in a comment and @Name / @username in a
// description are buttons (not inside code, unknown names stay text, a click does not start editing the description); the card
// shows avatar, name, role, the person's open tasks in the list, Assign this task / Mention; for an agent its state, Open chat, Jobs.
// #390: a folder has List | Matrix in the header; the matrix shows the tasks of all its lists (subfolders too) with the list chip,
// "Show as list" in "…" and the switch lead back. #391: the share block per agent (counts), both actions ask first, declining changes
// nothing. #392: Settings > AI colleague > Setup guide: the prompt with this server, the owner and the editable token file / Linux
// user, copy; the steps; links to docs/AGENT-SETUP.md. German texts, SW v68. Then Firefox headless (WebDriver BiDi, skipped without
// firefox) at 390 x 844 and 1280 x 800: comments newest first with the box on top, the mention card, the share block and the
// setup guide fit (no horizontal overflow, inside the viewport).
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
  try { execFileSync('firefox', ['--version'], {stdio: 'ignore'}); } catch { console.log('p242_ui: Firefox part skipped (no firefox on PATH)'); return; }
  const PORT = 9300 + Math.floor(Math.random() * 600);
  const prof = fs.mkdtempSync(path.join(process.env.TMPDIR || os.tmpdir(), 'kalmido-p242-'));
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
    const shot = async name => { const dir = process.env.P242_SHOTS; if (!dir) return; const r = await cmd('browsingContext.captureScreenshot', {context: ctx}); fs.writeFileSync(path.join(dir, name), Buffer.from(r.data, 'base64')); };
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
  check(/const CACHE = 'tasks-shell-v((68|69)|7[0-3])'/.test(SW), 'service worker cache v68 (2.5.0: v69, 2.5.1: v70, 2.5.2: v71, 2.6.0: v72, 2.6.1: v73)');
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en'});
  const me = (await call('GET', '/api/state')).me.id;
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const CKB = await login('bob');
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en'}, CKB);
  const ag = await call('POST', '/api/admin/agents', {username: 'claude', display_name: 'Claude'});
  const L = (await call('POST', '/api/lists', {name: 'Website'})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: BOB, role: 'edit'});
  await call('PUT', `/api/lists/${L}/members`, {user_id: ag.id, role: 'edit'});
  const T = (await call('POST', '/api/tasks', {title: 'Launch page', list_id: L, content: 'Ask @Bob and @claude about it, not `@Bob` in code, @Nobody stays text.'})).id;
  const TB = (await call('POST', '/api/tasks', {title: 'Bob\'s other task', list_id: L, assignee_id: BOB})).id;
  for (const [b, ck] of [['First from Alice', CK], [`Second from Bob, ping <@${me}>`, CKB], [`Third from Alice for <@${BOB}> and <@${ag.id}>`, CK]]) {
    await call('POST', `/api/tasks/${T}/comments`, {body: b}, ck); await sleep(1100);
  }
  const bodies = d => [...d.querySelectorAll('#d-tl-items .cm .cbody')].map(x => x.textContent.slice(0, 5));

  // ================= #386 comment order
  let w = await boot({user: 'alice', hash: 't/' + T}), d = w.document;
  await until(() => d.querySelectorAll('#d-tl-items .cm').length === 3);
  let tg = d.querySelector('#d-tl [data-act="tl-order"]');
  check(tg && /Oldest first/.test(tg.textContent) && d.querySelector('#d-tl [data-act="tl-act"]'), 'toggle "Oldest first" next to "With activity"');
  check(bodies(d).join() === 'First,Secon,Third', 'oldest first: ' + bodies(d));
  check(d.querySelector('#detail .dbot .dcomp #c-input') && !d.querySelector('#d-tl .dcomp'), 'oldest first: the box in the sticky bottom');
  click(w, tg); await sleep(900);
  tg = d.querySelector('#d-tl [data-act="tl-order"]');
  check(/Newest first/.test(tg?.textContent || ''), 'toggled: "Newest first"');
  check(bodies(d).join() === 'Third,Secon,First', 'newest first: ' + bodies(d));
  const top = d.querySelector('#d-tl .dcomp.dctop');
  check(top && top.querySelector('#c-input') && !d.querySelector('#detail .dbot .dcomp') && top.compareDocumentPosition(d.querySelector('#d-tl-items')) & w.Node.DOCUMENT_POSITION_FOLLOWING, 'newest first: the box above the newest comment, not at the bottom');
  check((await call('GET', '/api/state')).settings.comment_order === 'new', 'saved for the user (server)');
  check((await call('GET', '/api/state', null, CKB)).settings.comment_order === 'old', 'bob keeps oldest first');
  w.close();
  w = await boot({user: 'alice', hash: 't/' + T}); d = w.document;
  await until(() => d.querySelectorAll('#d-tl-items .cm').length === 3);
  check(bodies(d).join() === 'Third,Secon,First' && d.querySelector('#d-tl .dctop'), 'another device: newest first too');
  // send in newest-first mode: the new comment is on top
  const ta = d.querySelector('#c-input'); ta.value = 'Fourth'; ta.dispatchEvent(new w.Event('input', {bubbles: true}));
  click(w, d.querySelector('[data-act="c-send"]')); await until(() => d.querySelectorAll('#d-tl-items .cm').length === 4);
  check(bodies(d)[0] === 'Fourt' && d.querySelector('#d-tl .dctop #c-input')?.value === '', 'sent: the new comment on top, the box empty and still on top');
  click(w, d.querySelector('#d-tl [data-act="tl-order"]')); await sleep(900);
  check(bodies(d).join() === 'First,Secon,Third,Fourt' && d.querySelector('#detail .dbot .dcomp'), 'back to oldest first');
  w.close();

  // ================= #389 mentions
  w = await boot({user: 'alice', hash: 't/' + T}); d = w.document;
  await until(() => d.querySelectorAll('#d-tl-items .cm').length === 4);
  const mb = [...d.querySelectorAll('#d-tl-items button.mention[data-mcard]')];
  check(mb.some(b => b.textContent === '@Bob' && +b.dataset.mcard === BOB) && mb.some(b => b.textContent === '@Claude') && mb.some(b => b.classList.contains('me')), 'comment mentions are buttons: ' + mb.map(b => b.textContent));
  click(w, mb.find(b => b.textContent === '@Bob')); await sleep(300);
  let card = d.querySelector('#pop .mcard');
  check(card && /Bob/.test(card.querySelector('.mchead').textContent) && /Member/.test(card.textContent) && card.querySelector('.avatar'), 'card: avatar, name, role');
  check(card && [...card.querySelectorAll('[data-mc="task"]')].some(b => /Bob's other task/.test(b.textContent)) && /Assigned in Website/.test(card.textContent), 'card: Bob\'s open tasks in this list');
  check(card && card.querySelector('[data-mc="mention"]') && card.querySelector('[data-mc="assign"]') && !card.querySelector('[data-mc="chat"]'), 'card (person): Assign + Mention, no chat');
  click(w, card.querySelector('[data-mc="mention"]')); await sleep(200);
  check(/@Bob $/.test(d.querySelector('#c-input').value), 'Mention: "@Bob " in the comment box');
  click(w, [...d.querySelectorAll('#d-tl-items button.mention')].find(b => b.textContent === '@Bob')); await sleep(300);
  click(w, d.querySelector('#pop [data-mc="assign"]')); await sleep(1200);
  check((await call('GET', '/api/state')).tasks.find(t => t.id === T)?.assignee_id === BOB, 'Assign this task: assigned to Bob');
  click(w, [...d.querySelectorAll('#d-tl-items button.mention')].find(b => b.textContent === '@Claude')); await sleep(300);
  card = d.querySelector('#pop .mcard');
  check(card && card.querySelector('.abadge') && card.querySelector('.mcst') && card.querySelector('[data-mc="chat"]') && card.querySelector('[data-mc="jobs"]'), 'card (agent): badge, state, Open chat, Jobs');
  w.eval('closePop()');
  // description
  const dm = [...d.querySelectorAll('#d-md button.mention[data-mcard]')];
  check(dm.length === 2 && dm.some(b => +b.dataset.mcard === BOB) && dm.some(b => +b.dataset.mcard === ag.id && b.textContent === '@claude'), 'description: @Bob and @claude (username) are buttons: ' + dm.map(b => b.textContent));
  check(/@Nobody/.test(d.querySelector('#d-md').textContent) && d.querySelector('#d-md code')?.textContent === '@Bob' && !d.querySelector('#d-md code button'), 'unknown names and code stay text');
  click(w, dm[0]); await sleep(300);
  check(d.querySelector('#pop .mcard') && d.querySelector('#d-content').classList.contains('hidden'), 'a click opens the card, not the editor');
  w.eval('closePop()');
  w.close();

  // ================= #387 the Code section
  w = await boot({user: 'alice', hash: 't/' + TB}); d = w.document; await sleep(400);
  const menuLabels = async () => { w.eval(`taskMenu(document.querySelector('#top h1'), ${TB})`); await sleep(150); const l = [...d.querySelectorAll('#pop .menu-list button')].map(b => b.textContent); w.eval('closePop()'); return l; };
  check(!d.querySelector('#d-code') && !(await menuLabels()).some(x => /Link code/.test(x)), 'no repository: no Code section, no "Link code…"');
  w.eval(`listById(${L}).repos = [{id: 1, full_name: 'acme/app', provider: 'github'}]; taskById(${TB}).assignee_id = ${BOB}; renderDetail()`);
  check(!d.querySelector('#d-code'), 'repository + plain task: no Code section');
  let ml = await menuLabels();
  check(ml.some(x => /Link code/.test(x)), 'repository + plain task: "Link code…" in the task menu: ' + ml.join('|'));
  let copied = null; Object.defineProperty(w.navigator, 'clipboard', {configurable: true, value: {writeText: async x => { copied = x; }}});
  w.eval(`taskMenu(document.querySelector('#top h1'), ${TB})`); await sleep(150);
  click(w, [...d.querySelectorAll('#pop .menu-list button')].find(b => /Link code/.test(b.textContent))); await sleep(200);
  check(new RegExp(`^kalmido-${TB}$`).test(copied || ''), 'Link code…: copies the branch name kalmido-<id> (2.5.1, #396) ' + copied);
  for (const [set, lab] of [[`taskById(${TB}).ttype = 'bug'`, 'bug'], [`taskById(${TB}).ttype = 'feature'`, 'feature'], [`taskById(${TB}).assignee_id = ${ag.id}`, 'agent assignee'], [`taskById(${TB}).code = {prs: [{n: 3, state: 'open', title: 'x', url: 'https://example.com/p/3'}], commits: []}`, 'linked pull request']]) {
    w.eval(`taskById(${TB}).ttype = ''; taskById(${TB}).assignee_id = ${BOB}; taskById(${TB}).code = {prs: [], commits: []}; ${set}; renderDetail()`);
    ml = await menuLabels();
    check(d.querySelector('#d-code') && /acme\/app/.test(d.querySelector('#d-code h5').textContent) && !ml.some(x => /Link code/.test(x)), `repository + ${lab}: the Code section, no menu item`);
  }
  w.eval(`taskById(${TB}).ttype = 'task'; taskById(${TB}).assignee_id = ${BOB}; taskById(${TB}).code = {prs: [], commits: []}; renderDetail()`);
  check(!d.querySelector('#d-code'), 'ticket type "task": no Code section');
  w.close();

  // ================= #390 folder: List | Matrix
  const F1 = (await call('POST', '/api/lists', {name: 'Client A', folder: 'Clients'})).id;
  const F2 = (await call('POST', '/api/lists', {name: 'Client B', folder: 'Clients/Big'})).id;
  const FA = (await call('POST', '/api/tasks', {title: 'Quote for A', list_id: F1, priority: 5})).id;
  const FB = (await call('POST', '/api/tasks', {title: 'Invoice for B', list_id: F2, priority: 3})).id;
  w = await boot({user: 'alice', hash: 'folder/Clients'}); d = w.document; await sleep(300);
  let seg = d.querySelector('#top .fseg');
  check(seg && seg.querySelector('[data-k="list"]').classList.contains('on') && seg.querySelector('[data-k="matrix"]'), 'folder view: List | Matrix in the header');
  click(w, seg.querySelector('[data-k="matrix"]')); await sleep(900);
  check(w.eval('S.route.mod') === 'matrix' && w.eval('mxGet().scope') === 'folder:Clients', 'Matrix: the folder as scope');
  const qa = d.querySelector('.quad.q5 .task, .quad.q5 [data-id="' + FA + '"]'), qb = d.querySelector('.quad.q3 [data-id="' + FB + '"]');
  check(d.querySelector(`.quad.q5 [data-id="${FA}"]`) && qb, 'matrix: the tasks of the folder and its subfolder');
  check(/Client A/.test(d.querySelector(`.quad.q5 [data-id="${FA}"]`)?.textContent || '') && /Client B/.test(qb?.textContent || ''), 'matrix: with the list chip');
  check(d.querySelector('#top .fseg [data-k="matrix"]')?.classList.contains('on'), 'matrix: the switch shows Matrix');
  check(w.eval('topMoreItems().some(x => x.label === "Show as list")'), 'matrix: "Show as list" in "…"');
  click(w, d.querySelector('#top .fseg [data-k="list"]')); await sleep(900);
  check(w.eval('S.route.key') === 'folder:Clients', 'List: back to the folder view');
  w.close();
  w = await boot({user: 'alice', hash: 'folder/Clients', mobile: true}); d = w.document; await sleep(300);
  check(!d.querySelector('#top .fseg') && w.eval('topMoreItems().some(x => x.label === "Show as matrix")'), 'phone: the matrix via "…"');
  w.close();

  // ================= #391 share block
  const ag2 = await call('POST', '/api/admin/agents', {username: 'helper', display_name: 'Helper'});
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  w.eval(`settingsModal('ai')`); await sleep(500);
  click(w, d.querySelector('.modal.smodal [data-aisub="lists"]')); await sleep(1200);  // 2.5.1 (#393): the sub-tab Lists
  let pane = d.querySelector('.modal.smodal [data-pane="ai"]');
  check(pane && !pane.querySelector('[data-m="ai-share"]') && !/Share a list with an agent/.test(pane.textContent), 'no "Share a list with an agent…" button');
  let rows = [...pane.querySelectorAll('#s-ai-share [data-aisag]')];
  check(rows.length === 2 && rows.every(r => r.querySelector('[data-aisall]') && r.querySelector('[data-aisauto]')), 'a row per agent with both actions');
  const hr = () => pane.querySelector(`#s-ai-share [data-aisag="${ag2.id}"]`);
  check(/sees 0 of your 3 lists/.test(hr()?.textContent || ''), 'helper: sees 0 of 3 (2.5.1): ' + hr()?.textContent);
  let asked = []; w.confirm = m => { asked.push(m); return false; };
  click(w, hr().querySelector('[data-aisall]')); await sleep(600);
  check(asked.length === 1 && /private ones too/.test(asked[0]) && /Never the inbox/.test(asked[0]), 'Share all: a warning first');
  check(!(await call('GET', '/api/state')).lists.find(l => l.id === F1).members.some(m => m.user_id === ag2.id), 'declined: nothing shared');
  w.confirm = m => { asked.push(m); return true; };
  click(w, hr().querySelector('[data-aisall]')); await sleep(1500);
  const st = await call('GET', '/api/state');
  check([L, F1, F2].every(id => st.lists.find(l => l.id === id).members.some(m => m.user_id === ag2.id && m.role === 'edit')), 'accepted: all own lists shared (role edit)');
  check(/sees 3 of your 3 lists/.test(hr()?.textContent || '') && hr().querySelector('[data-aisall]').disabled, 'row: sees all, button off');
  const sw = hr().querySelector('[data-aisauto]');
  w.confirm = m => { asked.push(m); return false; };
  sw.checked = true; sw.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(600);
  check(!sw.checked && /from now on/.test(asked[asked.length - 1]) && !JSON.parse((await call('GET', '/api/state')).settings.agent_share || '{}').auto?.includes(ag2.id), 'automatic sharing: warning, declined = off');
  w.confirm = () => true;
  const sw2 = hr().querySelector('[data-aisauto]'); sw2.checked = true; sw2.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(1500);
  check(JSON.parse((await call('GET', '/api/state')).settings.agent_share).auto.includes(ag2.id) && hr().querySelector('[data-aisauto]').checked, 'automatic sharing on');
  const NL = (await call('POST', '/api/lists', {name: 'Fresh'})).id;
  check((await call('GET', '/api/state')).lists.find(l => l.id === NL).members.some(m => m.user_id === ag2.id), 'a new list is shared with it');

  // ================= #392 setup guide
  pane = d.querySelector('.modal.smodal [data-pane="ai"]');
  click(w, pane.querySelector('[data-m="ag-guide"]')); await sleep(400);
  const gm = d.querySelector('.modal.agguide');
  const pr = gm?.querySelector('#agg-prompt')?.textContent || '';
  check(gm && pr.includes(B.replace(/\/$/, '')) && pr.includes('Alice, Kalmido account id ' + me) && pr.includes('kalmido-agent') && !/<KALMIDO_URL>|<OWNER_NAME>|<OWNER_ID>/.test(pr), 'prompt: this server, Alice + her id, the Linux user');
  const env = gm.querySelector('#agg-env'); env.value = '/etc/kalmido/agent.env'; env.dispatchEvent(new w.Event('input', {bubbles: true}));
  check(gm.querySelector('#agg-prompt').textContent.includes('/etc/kalmido/agent.env'), 'the token file is filled in');
  copied = null; Object.defineProperty(w.navigator, 'clipboard', {configurable: true, value: {writeText: async x => { copied = x; }}});
  click(w, gm.querySelector('[data-m="agg-copy"]')); await sleep(200);
  check(copied && copied.includes('/etc/kalmido/agent.env') && /docs\/AGENT-SECURITY\.md/.test(copied), 'Copy prompt');
  click(w, gm.querySelector('[data-agt="b"]')); await sleep(100);
  check(!gm.querySelector('[data-agp="b"]').hidden && gm.querySelector('[data-agp="a"]').hidden && gm.querySelectorAll('.agsteps.agb li').length === 11, 'Do it yourself: 11 steps');
  check(gm.querySelector('a[href$="docs/AGENT-SETUP.md"]') && gm.querySelector('a[href$="docs/AGENT-SECURITY.md"]'), 'links to AGENT-SETUP.md and AGENT-SECURITY.md');
  [...d.querySelectorAll('.modal')].forEach(m => m.remove());
  w.close();

  // ================= German
  await call('PATCH', '/api/settings', {lang: 'de'});
  w = await boot({user: 'alice', hash: 't/' + T}); d = w.document;
  await until(() => d.querySelector('#d-tl [data-act="tl-order"]'));
  check(/Älteste zuerst/.test(d.querySelector('#d-tl [data-act="tl-order"]').textContent), 'German: "Älteste zuerst"');
  w.eval(`settingsModal('ai')`); await sleep(500);
  click(w, d.querySelector('.modal.smodal [data-aisub="lists"]')); await sleep(1200);
  pane = d.querySelector('.modal.smodal [data-pane="ai"]');
  check(/Installationshilfe/.test(pane.textContent) && /Alle teilen/.test(pane.querySelector('#s-ai-share').textContent) && /Neue Listen automatisch/.test(pane.textContent) && /sieht \d von deinen \d Listen/.test(pane.textContent), 'German: Installationshilfe, share block');
  click(w, pane.querySelector('[data-m="ag-guide"]')); await sleep(400);
  check(/Agent einrichten/.test(d.querySelector('.modal.agguide')?.textContent || '') && /Selbst einrichten/.test(d.querySelector('.modal.agguide').textContent), 'German: setup guide');
  [...d.querySelectorAll('.modal')].forEach(m => m.remove());
  w.close();
  await call('PATCH', '/api/settings', {lang: 'en', comment_order: 'new'});

  // ================= Firefox: layouts at 390 and 1280
  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    await nav(B + 'static/icon.svg');
    const lgi = await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    check(lgi === 200, 'Firefox: login');
    const fit = sel => ev(`(() => { const c = document.querySelector('${sel}'); if (!c) return null; const r = c.getBoundingClientRect();
      const over = [...c.querySelectorAll('*')].filter(e => e.getBoundingClientRect().right > r.right + 1 && getComputedStyle(e).position !== 'fixed' && !e.closest('select') && !e.closest('pre') && e.getBoundingClientRect().width).length;
      return {doc: document.documentElement.scrollWidth - innerWidth, left: r.left, right: r.right, vw: innerWidth, bottom: r.bottom, vh: innerHeight, over}; })()`);
    const good = (m, bottom = true) => m && m.doc <= 0 && m.left >= 0 && m.right <= m.vw + 1 && (!bottom || m.bottom <= m.vh + 1) && m.over === 0;
    for (const [W, Hh] of [[390, 844], [1280, 800]]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: W, height: Hh}});
      await nav(B + '#l/' + L); await sleep(2500);
      await ev(`openDetail(${T})`); await sleep(1500);
      if (W < 900) await ev(`document.querySelector('[data-act="d-tab"][data-tab="comments"]')?.click()`);
      await sleep(300);
      const m1 = await fit('#detail');
      const onTop = await ev(`!!document.querySelector('#d-tl .dctop #c-input') && !document.querySelector('#detail .dbot .dcomp')`);
      check(good(m1, false) && onTop, `${W}px: task panel, newest first with the box on top ${JSON.stringify(m1)} ${onTop}`);
      await shot(`p242-comments-${W}.png`);
      await ev(`(() => { const b = document.querySelector('#d-tl-items button.mention[data-mcard]'); b.scrollIntoView({block: 'center'}); b.click(); })()`); await sleep(400);
      const m2 = await fit('#pop');
      check(good(m2) && await ev(`!!document.querySelector('#pop .mcard')`), `${W}px: the mention card fits ${JSON.stringify(m2)}`);
      await shot(`p242-card-${W}.png`);
      await ev(`closePop(); closeDetail(); settingsModal('ai'); document.querySelector('.smodal [data-aisub="lists"]').click()`); await sleep(1500);
      await ev(`document.querySelector('#s-ai-share').scrollIntoView()`); await sleep(200);
      const m3 = await fit('#s-ai-share');
      check(good(m3, false), `${W}px: the share block fits ${JSON.stringify(m3)}`);
      await shot(`p242-share-${W}.png`);
      await ev(`document.querySelector('[data-m="ag-guide"]').click()`); await sleep(600);
      const m4 = await fit('.modal.agguide .card');
      check(good(m4, false), `${W}px: the setup guide fits ${JSON.stringify(m4)}`);
      await shot(`p242-guide-${W}.png`);
      await ev(`document.querySelector('.modal.agguide [data-agt="b"]').click()`); await sleep(200);
      const m5 = await fit('.modal.agguide .card');
      check(good(m5, false), `${W}px: the steps fit ${JSON.stringify(m5)}`);
      await shot(`p242-steps-${W}.png`);
      await ev(`document.querySelectorAll('.modal').forEach(m => m.remove())`);
    }
  });

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  console.log(`p242_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
