// 2.6.0 UI tests (UX audit 2, package "UX2"), own container (start.sh). jsdom: the header's fold levels (what moves into "…"
// at tl3 / tl4) and the merged status chip (K01 / K02); agents that never polled or stopped polling are "not connected" and
// their running jobs do not keep the header busy (K08); one term "Agents" (Settings tab, sub-tab "Overview", no module switch
// outside Modules, German "Agenten") (K09); the assignee circle only where it means something (K11); one date format, the
// date column with its own text span and a range icon (K07); plain words instead of environment variables (K23); the usage
// card as a table and one short number format in both languages (K24); the week title from the week's own dates (K25); the
// Share dialog (people + roles + invite, agents + stop sharing + the tidy agent, the public link, ownership), the list
// dialog's "Sharing" summary, "Share…" in the list menu and next to the title (K12); SW v72.
// Then Firefox headless (WebDriver BiDi, skipped without firefox), touch emulation at 360 x 780, 390 x 844 and 904 x 1080,
// a mouse at 1280 x 800 and 1920 x 1080, dark and light, while an agent is working and a timer runs: the title readable
// (all of it, or at least its first 12 characters; all of it on the desktop, also with the task panel open), "…" and the
// bell inside the viewport and nothing in the header sticking out (K01 / K02); the toast above the composer / tab bar
// (K18); the week title on one line on the Fold cover screen (K25); the date column never cut on the left (K07); text
// contrast >= 4.5:1 (3:1 for large text) in the views the audit measured (K17); and at 390 px with touch every interactive
// element of the main views >= 44 x 44 px, apart from the listed exceptions (K10) (screenshots with P260_SHOTS=<dir>).
const {spawn, execFileSync} = require('child_process');
const fs = require('fs'), os = require('os'), path = require('path');
const {boot, errs, sleep, B, login} = require('./boot');
const WS = globalThis.WebSocket || require('ws');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const {shareAny} = require('./legacy');  // 2.26.0: one agent per list
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const v1 = async (tok, method, url, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + tok}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true}));
const ALL = 'cal,timeline,matrix,habits,pomo,kanban,paperless,collab,stats,time,progress,deps,fields,agents,comments';
const day = n => { const d = new Date(); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };

// K10: justified exceptions of the 44 px rule (pattern on "tag.class[act] in parent")
const TOUCH_OK = [
  [/^div\.tmain\[open\]/, 'the text part of a task row; the whole row (and its swipe area) is the target'],
  [/^div\.tl-bar\b/, 'timeline bars: their width is the task’s duration (drag to move); the name column opens the task'],
  [/^button\.nxt\[flow-why\] in \.meta/, 'a chip inside a task row; the row opens the task with the same explanation'],
  [/^a\.lnk in \.meta/, 'the task’s link chip inside a row'],
  [/^input in \.cb\b/, 'Markdown checkboxes inside a task’s notes (text content)'],
  [/^button(\.on)? in #l-col\b/, 'the colour swatches of the list dialog (1.x; a mis-tap picks the neighbour colour, undoable)'],
  [/^div\.ghead\[collapse\] in \.group .*x(3[6-9]|4[0-3])$/, 'section headers: full-width rows, 36-43 px high'],
];

async function firefox(fn, touch) {
  try { execFileSync('firefox', ['--version'], {stdio: 'ignore'}); } catch { console.log('p260_ui: Firefox part skipped (no firefox on PATH)'); return; }
  const PORT = 9300 + Math.floor(Math.random() * 600);
  const prof = fs.mkdtempSync(path.join(process.env.TMPDIR || os.tmpdir(), 'kalmido-p260-'));
  const prefs = [['browser.shell.checkDefaultBrowser', false], ['datareporting.policy.dataSubmissionEnabled', false], ['ui.prefersReducedMotion', 1],
    ...(touch ? [['ui.primaryPointerCapabilities', 1], ['ui.allPointerCapabilities', 1], ['dom.w3c_touch_events.enabled', 1]] : [['ui.primaryPointerCapabilities', 6], ['ui.allPointerCapabilities', 6]])];
  fs.writeFileSync(path.join(prof, 'user.js'), prefs.map(([k, v]) => `user_pref("${k}", ${JSON.stringify(v)});`).join('\n') + '\n');
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
    const ev = async expr => { const r = await cmd('script.evaluate', {expression: expr, target: {context: ctx}, awaitPromise: true, resultOwnership: 'none', serializationOptions: {maxObjectDepth: 6}}); if (r.type === 'exception') throw new Error('JS: ' + r.exceptionDetails.text); return unwrap(r.result); };
    const nav = url => cmd('browsingContext.navigate', {context: ctx, url, wait: 'complete'});
    const shot = async name => { const dir = process.env.P260_SHOTS; if (!dir) return; const r = await cmd('browsingContext.captureScreenshot', {context: ctx}); fs.writeFileSync(path.join(dir, name), Buffer.from(r.data, 'base64')); };
    await fn({cmd, ev, nav, ctx, shot});
  } catch (e) { check(false, 'Firefox: ' + e.message); } finally {
    try { ws && ws.close(); } catch { /* gone */ }
    try { ff.kill(); } catch { /* gone */ }
    await sleep(500); fs.rmSync(prof, {recursive: true, force: true});
  }
}

// the header, measured in the page: title (all of it / at least 12 characters), "…", the bell, anything sticking out
const HEAD = `(() => {
  const t = document.querySelector('#top'); if (!t || !t.querySelector('h1')) return {none: location.href + ' ' + (document.body ? document.body.textContent.slice(0, 120) : document.documentElement.tagName)};
  const ht = t.querySelector('h1 .ht'), vw = document.documentElement.clientWidth;
  const R = e => { if (!e || !e.offsetWidth) return null; const b = e.getBoundingClientRect(); return [b.left, b.right, b.top, b.bottom]; };
  let full = true, w12 = 0, w6 = 0, txt = ht ? ht.textContent : '';
  if (ht && ht.firstChild) { const n = ht.firstChild, rg = document.createRange(); rg.setStart(n, 0); rg.setEnd(n, n.length); const all = rg.getBoundingClientRect().width;
    rg.setEnd(n, Math.min(6, n.length)); w6 = rg.getBoundingClientRect().width; rg.setEnd(n, Math.min(12, n.length)); w12 = rg.getBoundingClientRect().width; full = ht.getBoundingClientRect().width + 0.1 >= all; }
  const out = [...t.children].filter(e => e.offsetWidth && e.getBoundingClientRect().right > vw + 0.5).map(e => e.className || e.tagName);
  return {lvl: (t.className.match(/tl\\d/) || [''])[0], txt, full, w12, w6, htw: ht ? ht.getBoundingClientRect().width : 0, vw, more: R(t.querySelector('[data-act="top-more"]')), bell: R(t.querySelector('.bell')), out,
    st: R(t.querySelector('.stchip')), ach: R(t.querySelector('.achip')), tm: R(t.querySelector('.tmini.run'))};
})()`;
// contrast of every visible text (only inside the top dialog when one is open)
const CONTRAST = `(() => {
  const parse = c => { const m = c.match(/rgba?\\(([^)]+)\\)/); if (!m) return null; const p = m[1].split(/[ ,\\/]+/).filter(Boolean).map(Number); return {r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1}; };
  const lum = ({r, g, b}) => { const f = v => { v /= 255; return v <= .03928 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; }; return .2126 * f(r) + .7152 * f(g) + .0722 * f(b); };
  const blend = (fg, bg) => ({r: fg.r * fg.a + bg.r * (1 - fg.a), g: fg.g * fg.a + bg.g * (1 - fg.a), b: fg.b * fg.a + bg.b * (1 - fg.a), a: 1});
  const bgOf = e => { const st = []; while (e) { const c = parse(getComputedStyle(e).backgroundColor); if (c && c.a > 0) { st.push(c); if (c.a >= 1) break; } e = e.parentElement; } let b = parse(getComputedStyle(document.body).backgroundColor) || {r: 255, g: 255, b: 255, a: 1}; for (let i = st.length - 1; i >= 0; i--) b = blend(st[i], b); return b; };
  const top = document.querySelector('.modal:last-of-type, #pop:not(.hidden)'), bad = [];
  for (const e of document.querySelectorAll('body *')) {
    if (![...e.childNodes].some(x => x.nodeType === 3 && x.textContent.trim())) continue;
    const r = e.getBoundingClientRect(); if (!r.width || !r.height || r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) continue;
    const s = getComputedStyle(e); if (s.visibility === 'hidden' || +s.opacity < .99 || e.closest('[inert],.lookpv,[aria-hidden="true"],.trow.done,.off,[disabled],.ckdone')) continue;
    if (top && !top.contains(e)) continue;
    let fg = parse(s.color); if (!fg) continue; const bg = bgOf(e); fg = blend(fg, bg);
    const L1 = lum(fg), L2 = lum(bg), cr = (Math.max(L1, L2) + .05) / (Math.min(L1, L2) + .05);
    const big = parseFloat(s.fontSize) >= 24 || (parseFloat(s.fontSize) >= 18.66 && +s.fontWeight >= 700);
    if (cr < (big ? 3 : 4.5)) bad.push((typeof e.className === 'string' && e.className ? e.className.split(' ')[0] : e.tagName) + ' "' + e.textContent.trim().slice(0, 20) + '" ' + cr.toFixed(2));
  }
  return bad;
})()`;
// interactive elements below 44 x 44 px (with their ::before / ::after hit area and their label)
const TOUCH = `(() => {
  const out = [], top = document.querySelector('.modal:last-of-type, .tour, #pop:not(.hidden)');
  for (const e of document.querySelectorAll('button, a[href], [role=button], input:not([type=hidden]), select, [data-act], .chk, summary')) {
    const r = e.getBoundingClientRect(), st = getComputedStyle(e);
    if (!r.width || !r.height || st.visibility === 'hidden' || r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth || e.disabled) continue;
    if (top && !top.contains(e)) continue;
    if (e.tagName === 'A' && e.closest('p, .md, .cmbody, .shint, small, .muted, li')) continue;
    if (e.tagName === 'INPUT' && /text|search|email|password|number|url|date|time|range/.test(e.type)) continue;
    let w = r.width, h = r.height;
    for (const p of ['::before', '::after']) { const ps = getComputedStyle(e, p); if (ps.content !== 'none' && ps.position === 'absolute' && ps.pointerEvents !== 'none') { w = Math.max(w, parseFloat(ps.width) || 0); h = Math.max(h, parseFloat(ps.height) || 0); } }
    const lab = e.closest('label'); if (lab) { const lr = lab.getBoundingClientRect(); w = Math.max(w, lr.width); h = Math.max(h, lr.height); }
    // 2.16.0 (#473): a task's title is a keyboard / screen-reader stop; on touch the whole row is the target that opens it
    const row = e.matches('.ttl[data-kt]') && e.closest('.trow'); if (row) { const rr = row.getBoundingClientRect(); w = Math.max(w, rr.width); h = Math.max(h, rr.height); }
    if (w >= 43.5 && h >= 43.5) continue;
    // 2.31.0 (#1053, decided): the view tabs of a list header (.vsegm) are a compact segmented control, 36 px high, 44 wide
    if (e.closest('.vsegm') && w >= 43.5 && h >= 35.5) continue;
    const cls = typeof e.className === 'string' ? e.className.trim().split(/\\s+/)[0] : '', pe = e.parentElement;
    const par = pe && (pe.id ? '#' + pe.id : typeof pe.className === 'string' && pe.className.trim() ? '.' + pe.className.trim().split(/\\s+/)[0] : '');
    out.push(e.tagName.toLowerCase() + (cls ? '.' + cls : '') + (e.dataset.act ? '[' + e.dataset.act + ']' : '') + (par ? ' in ' + par : '') + ' ' + Math.round(w) + 'x' + Math.round(h));
  }
  return out;
})()`;

(async () => {
  await sleep(600);
  const SW = await (await fetch(B + 'sw.js')).text();
  check(/const CACHE = 'tasks-shell-v(?:7[2-9]|8[0-9]|9[0-9]|[1-9][0-9]{2})'/.test(SW), 'service worker cache v72 (2.6.1: v73, 2.7.0: v74, 2.7.1: v75, 2.7.2: v76, 2.8.0: v77, 2.9.0: v78, 2.10.0: v79, 2.11.0: v80)');
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en', tour: 'done'});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const CAROL = (await call('POST', '/api/users', {username: 'carol', display_name: 'Carol', password: 'password123'})).id;
  const CKB = await login('bob');
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en', tour: 'done'}, CKB);
  const ag = await call('POST', '/api/admin/agents', {scopes: ['write'], username: 'claude', display_name: 'Claude'});
  const ag2 = await call('POST', '/api/admin/agents', {scopes: ['write'], username: 'helper', display_name: 'Helper'});
  const L = (await call('POST', '/api/lists', {name: 'Website Relaunch Müller GmbH', kind: 'project'})).id;  // a long project name
  for (const id of [BOB, ag.id]) await shareAny(call, DATA, L, id, 'edit');
  const CL = (await call('POST', '/api/lists', {name: 'Shopping', kind: 'checklist'})).id;
  await shareAny(call, DATA, CL, BOB, 'edit');
  const T = (await call('POST', '/api/tasks', {title: 'Go live', list_id: L, due: day(6), start: day(3)})).id;
  const T2 = (await call('POST', '/api/tasks', {title: 'Write the texts', list_id: L, due: day(2), due_time: '10:00', assignee_id: BOB})).id;
  const T3 = (await call('POST', '/api/tasks', {title: 'Nobody yet', list_id: L, due: day(4)})).id;
  const SUB = (await call('POST', '/api/tasks', {title: 'A step', list_id: L, parent_id: T})).id;
  for (const x of ['Milk', 'Bread', 'Coffee']) await call('POST', '/api/tasks', {title: x, list_id: CL});
  for (let i = 0; i < 12; i++) await call('POST', '/api/tasks', {title: `Filler task ${i + 1}`, list_id: L, due: day(i % 5)});

  // ================= K08: never in touch = "not connected"; its running job does not keep the header busy
  check((await call('POST', '/api/proposals', {agent_id: ag.id, kind: 'subtasks', task_id: T})).id, 'a running job for the agent (a proposal asked for)');
  let w = await boot({user: 'alice', hash: 'cal'}), d = w.document;  // 2.8.0: a view without the agent band (header dots)
  check(w.eval(`agentSt(agentById(${ag.id}))`) === 'not connected' && w.eval(`agentById(${ag.id}).webhook`) === false && w.eval(`agentById(${ag.id}).contact_age`) === null, 'never in touch: "not connected"');
  // 2.6.1 (#402): the pill is always there now (its dot), but calm: no "running" text, a grey dot
  check(d.querySelector('#top .achip.calm .hdot.hs-offline') && !d.querySelector('#top .achip .act') && !d.querySelector('#top .stchip'), 'its running job does not make the agent pill busy (2.6.1: grey dot only)');
  check(w.eval(`agentDot(${ag.id})`).includes('st-offline'), 'the grey dot');
  w.close();
  check((await v1(ag.token, 'GET', '/agent/events')).status === 200, 'agent polls once');
  await v1(ag.token, 'PUT', '/agent/status', {status: 'working', task_id: T, text: 'Breaking it down'});
  w = await boot({user: 'alice', hash: 'l/' + L}); d = w.document;
  check(w.eval(`agentSt(agentById(${ag.id}))`) === 'working' && d.querySelector('#top .achip'), 'after a poll: working, the pill shows');
  check(w.eval(`agentById(${ag.id}).contact_age`) <= 5 && w.eval(`(() => { const a = {...agentById(${ag.id}), contact_age: 400}; return agentSt(a); })()`) === 'not connected', 'no contact for more than 5 minutes: "not connected"');
  check(w.eval(`agentSt({enabled: true, online: null, webhook: {id: 1}, contact_age: null, status: 'idle'})`) === 'ready', 'a webhook agent that never polled: its own state');

  // ================= K01 / K02 in jsdom: the status chip and what folds into "…"
  const tst = await call('POST', '/api/time/start', {task_id: T2});
  check(tst.status === 200, 'timer started');
  w.close();
  w = await boot({user: 'alice', hash: 'l/' + L}); d = w.document;
  const top = d.querySelector('#top');
  check(top.querySelector('.achip') && top.querySelector('.tmini.run') && top.querySelector('.stchip [data-timer-mini]') && top.querySelector('.stchip .sta'), 'agent pill + timer pill + the merged status chip (hidden until tl2)');
  check(top.querySelector('[data-act="top-more"]') && top.querySelector('.bell') && top.querySelector('.vseg.tf') && top.querySelector('.hist.tf') && top.querySelector('.kbtn.cmdbar:not(.tf4)') && top.querySelector('.shbtn.tf'), '"…", the bell and the foldable items');
  top.classList.add('tl3');
  const labs = w.eval('topMoreItems()').filter(x => x !== '-').map(x => x.label);
  check(['List', 'Kanban', 'Timeline', 'Share…', 'Nothing to undo'].every(x => labs.includes(x)) && !labs.some(x => /^Search/.test(x)), 'tl3: view, Share and undo in "…": ' + labs.slice(0, 8).join(' | '));
  top.classList.replace('tl3', 'tl4');
  check(!w.eval('topFolded()').some(x => x.icon === 'search'), 'tl4: Search stays in the header (2.18.0 #651, the title is cut instead)');
  top.classList.remove('tl4');
  const l0 = w.eval('topMoreItems()').filter(x => x !== '-').map(x => x.label);
  check(!l0.includes('Kanban') && !l0.includes('Timeline') && !l0.includes('Nothing to undo'), 'tl0: nothing folded: ' + l0.join(' | '));
  w.eval(`go('cal')`); await sleep(400);
  check(w.eval('topMoreItems()').some(x => x.label === 'Search and commands') && !d.querySelector('#top [data-act="top-more"]').hidden, '"…" on a view without own actions: search + shortcuts');
  w.close();

  // ================= K09: one term, the switch only under Modules
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  w.eval(`settingsModal('ai')`); await sleep(700);
  let md = d.querySelector('.smodal');
  check(/Agents/.test(md.querySelector('.snav [data-sec="ai"]').textContent) && !/AI colleague/.test(md.textContent), 'Settings tab "Agents", no "AI colleague"');
  check(md.querySelector('[data-aisub="agents"]').textContent.trim() === 'Status', 'first sub-tab: Status (2.7.0, #405 S5: was Overview)');
  check(!md.querySelector('[data-pane="ai"] [data-feat="agents"]') && !md.querySelector('.aimodoff'), 'module on: no switch, no hint');
  md.remove();
  await call('PATCH', '/api/settings', {features: ALL.replace(',agents', '')});
  w.close(); w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  w.eval(`settingsModal('ai')`); await sleep(700);
  md = d.querySelector('.smodal');
  const off = md.querySelector('.aimodoff');
  check(off && !md.querySelector('[data-pane="ai"] [data-feat="agents"]') && /switched off for you/.test(off.textContent), 'module off: a hint instead of the switch');
  click(w, off.querySelector('[data-m="go-modules"]')); await sleep(300);
  check(md.querySelector('.snav [data-sec="modules"]').classList.contains('on') || md.querySelector('.snav [data-sec="modules"]').getAttribute('aria-selected') === 'true', '"Open Modules" switches to Modules');
  check(md.querySelector('[data-pane="modules"] [data-feat="agents"]'), 'the switch is in Modules');
  md.remove(); w.close();
  await call('PATCH', '/api/settings', {features: ALL, lang: 'de'});
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  w.eval(`settingsModal('ai')`); await sleep(700);
  md = d.querySelector('.smodal');
  check(/Agenten/.test(md.querySelector('.snav [data-sec="ai"]').textContent) && /Status/.test(md.querySelector('[data-aisub="agents"]').textContent) && !/KI-Kollege/.test(md.textContent), 'German: Agenten, Status (2.7.0), no "KI-Kollege"');
  md.remove();
  // ================= K24: one short number format, a table
  check(w.eval('fmtTok(59100)') === '59,1 Tsd.' && w.eval('fmtTok(1250000)') === '1,3 Mio.' && w.eval('fmtTok(940)') === '940', 'German: 59,1 Tsd. / 1,3 Mio.: ' + w.eval('fmtTok(59100)'));
  // ================= K25: the week title (German)
  check(w.eval(`weekTitle('2026-09-28')`) === '28. Sep – 4. Okt · KW 40', 'German week title: ' + w.eval(`weekTitle('2026-09-28')`));
  // ================= K07: one date format (no "05.10." any more)
  const lbl = w.eval(`dayLabel('${day(3)}')`);
  check(/^[A-Z][a-z], \d{1,2}\. [A-ZÄÖÜ][a-zäöü]{2}$/.test(lbl), 'German: a date 3 days ahead like every other: ' + lbl);
  w.close();
  await call('PATCH', '/api/settings', {lang: 'en'});
  w = await boot({user: 'alice', hash: 'l/' + L}); d = w.document;
  check(w.eval('fmtTok(59100)') === '59.1k' && w.eval(`weekTitle('2026-09-28')`) === 'Sep 28 – Oct 4 · Week 40' && w.eval(`weekTitle('2026-12-28')`) === 'Dec 28, 2026 – Jan 3, 2027 · Week 53', 'English: 59.1k, week titles: ' + w.eval(`weekTitle('2026-12-28')`));
  const rowT = d.querySelector(`#view .trow[data-id="${T}"]`), rowT2 = d.querySelector(`#view .trow[data-id="${T2}"]`);
  const cd = rowT.querySelector('.c-date');
  check(cd && cd.querySelector('.cdt') && cd.querySelector('.rngi') && / – /.test(cd.title) && !/ – /.test(cd.querySelector('.cdt').textContent), 'date column: own text span, a range icon, the whole range in the tooltip: ' + cd?.title);
  check(/, 10:00$/.test(rowT2.querySelector('.c-date .cdt').textContent), 'a time after a comma, as in the panel: ' + rowT2.querySelector('.c-date .cdt').textContent);
  w.eval(`openDetail(${T2})`); await sleep(400);
  check(d.querySelector('#detail .dchip .dct').textContent === w.eval(`dueLabel(taskById(${T2}))`), 'the panel uses the same text');
  // ================= K11: the assignee circle only where it means something
  check(rowT2.querySelector('.whob:not(.wnone) .who') && d.querySelector(`#view .trow[data-id="${T3}"] .whob.wnone`), 'shared list: assigned = avatar, unassigned = a quiet circle (.wnone)');
  check(!d.querySelector(`.trow[data-id="${SUB}"] .whob`), 'unassigned subtask: no circle');
  w.close();
  w = await boot({user: 'alice', hash: 'l/' + CL}); d = w.document;
  check(d.querySelectorAll('#view .trow').length >= 3 && !d.querySelector('#view .trow .whob'), 'checklist: no assignee circles');
  w.close();

  // ================= K23: plain words
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  w.eval(`settingsModal('users')`);
  md = await until(() => d.querySelector('.smodal #s-updcheck') && d.querySelector('.smodal'), 60);
  const inst = md.querySelector('#s-updcheck').closest('label');
  check(/Switched off by the server operator\./.test(inst.textContent) && !/KALMIDO_/.test(inst.textContent) && inst.querySelector('[title="KALMIDO_UPDATE_CHECK=0"]'), 'update check: "switched off by the server operator", the variable in the tooltip');
  md.remove();
  // ================= K24: the usage card in the Agents view
  await v1(ag.token, 'POST', '/agent/usage', {model: 'm', input_tokens: 59000, output_tokens: 100, task_id: T});
  w.close(); w = await boot({user: 'alice', hash: 'agents'}); d = w.document;
  const card = await until(() => d.querySelector('.aiucard'));
  check(card && [...card.querySelectorAll('.aiugh [role="columnheader"]')].map(x => x.textContent).join('|') === '|Today|7 days|30 days' && card.querySelectorAll('.aiucr .aiuv').length === 3 && card.querySelector('.aiucr .aiuv').textContent === '59.1k', 'usage card: three labelled columns, 59.1k: ' + card?.textContent);
  w.close();

  // ================= K12: the Share dialog
  w = await boot({user: 'alice', hash: 'l/' + L}); d = w.document;
  check(d.querySelector(`#top [data-act="share-list"][data-id="${L}"]`), 'Share next to the title');
  check(w.eval(`listMenuItems(${L}).some(x => x.label === 'Share…')`), '"Share…" in the list menu');
  w.eval(`listModal(${L})`); await sleep(400);
  md = d.querySelector('.modal.lmodal');
  check(md && !md.querySelector('#l-members') && !md.querySelector('#l-pub') && !md.querySelector('#l-owner') && /Shared with 1 person · 1 agent/.test(md.querySelector('#l-shsum').textContent), 'list dialog: only a summary: ' + md?.querySelector('#l-shsum')?.textContent);
  click(w, md.querySelector('[data-m="share-open"]')); await sleep(600);
  md = await until(() => d.querySelector('.modal.shmodal'));
  check(md && !d.querySelector('.modal.lmodal') && /Share “Website Relaunch Müller GmbH”/.test(md.querySelector('h3').textContent), 'Sharing > Share… opens the Share dialog');
  await until(() => md.querySelector('#l-adduser'));
  const ppl = md.querySelector('#l-members');
  check(ppl.querySelector(`.mrow[data-uid="${BOB}"] [data-mrole="${BOB}"]`) && !ppl.querySelector(`.mrow[data-uid="${ag.id}"]`), 'people: Bob with his role, no agent');
  const inv = [...md.querySelectorAll('#l-adduser option')].map(o => o.textContent);
  check(inv.includes('Carol') && !inv.includes('Helper') && !inv.includes('Claude'), 'invite: people only: ' + inv.join(','));
  const ags = md.querySelector('#sh-agents');
  // 2.26.0: one agent per list -- one select "Agent", the switches who may address it, then the tidy row
  check(ags && ags.querySelector('#sh-agsel')?.value === String(ag.id) && [...ags.querySelectorAll('#sh-agsel option')].map(o => o.textContent).includes('Helper')
        && !ags.querySelector(`.mrow[data-uid="${ag.id}"]`) && md.querySelector('#l-tidyrow #l-tidy') && md.querySelector('#l-agm') && md.querySelector('#l-agp'), 'agents: one select (Claude, Helper to pick), the switches, the tidy agent');
  check(md.querySelector('#l-pub') && md.querySelector('#l-owner') !== null, 'public link + ownership sections');
  await until(() => md.querySelector('#l-owner [data-m="own-xfer"]'));
  check(md.querySelector('#l-owner [data-m="own-xfer"]') && /Transfer ownership/.test(md.querySelector('#l-owner').textContent), 'Transfer ownership…');
  // invite Carol as a viewer
  md.querySelector('#l-adduser').value = String(CAROL); md.querySelector('#l-addrole').value = 'view';
  click(w, md.querySelector('[data-m="share"]')); await sleep(900);
  const members = async () => ((await call('GET', '/api/state')).lists.find(x => x.id === L)?.members || []);
  check((await members()).some(p => p.user_id === CAROL && p.role === 'view') && md.querySelector(`#l-members .mrow[data-uid="${CAROL}"]`), 'Carol invited as a viewer');
  // switch to Helper (Claude leaves in the same step), Undo brings Claude back, then no agent
  const agsel = () => md.querySelector('#sh-agsel');
  agsel().value = String(ag2.id); agsel().dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(1400);
  let mm = await members();
  check(mm.some(p => p.user_id === ag2.id) && !mm.some(p => p.user_id === ag.id) && /Undo/.test(d.querySelector('#toast')?.textContent || ''), 'switched to Helper in one step, with Undo');
  d.querySelector('#toast button')?.click(); await sleep(1400);
  mm = await members();
  check(mm.some(p => p.user_id === ag.id) && !mm.some(p => p.user_id === ag2.id), 'Undo: Claude is back');
  agsel().value = ''; agsel().dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(1400);
  check(!(await members()).some(p => p.user_id === ag.id), 'No agent: Claude no longer sees the list');
  click(w, md.querySelector('[data-m="list-edit"]')); await sleep(400);
  check(d.querySelector('.modal.lmodal') && !d.querySelector('.modal.shmodal'), '"List settings…" goes back to the list dialog');
  d.querySelector('.modal.lmodal').remove();
  w.close();
  // a member: sees the people, cannot manage
  w = await boot({user: 'bob', hash: 'l/' + L}); d = w.document;
  w.eval(`shareModal(${L})`); await sleep(700);
  md = d.querySelector('.modal.shmodal');
  check(md && !md.querySelector('[data-mrole]') && !md.querySelector('#l-adduser') && !md.querySelector('#l-pub') && md.querySelector('.olock'), 'member: read-only people, no public link');
  md.remove(); w.close();
  // put Claude back for the header checks below
  await shareAny(call, DATA, L, ag.id, 'edit');

  // ================= Firefox
  const W5 = [[360, 780, 1], [390, 844, 1], [904, 1080, 1], [1280, 800, 0], [1920, 1080, 0]];
  for (const touch of [1, 0]) {
    await firefox(async ({cmd, ev, nav, ctx, shot}) => {
      await nav(B + 'static/icon.svg');
      const lgi = await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
      check(lgi === 200, 'Firefox: login');
      // a fresh document per view (a distinct URL: a hash-only change after the icon page did not always load the app)
      let nr = 0;
      const open = async hash => { await nav(B + 'static/icon.svg'); await nav(B + '?v=' + (++nr) + '#' + hash); for (let i = 0; i < 30 && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); };
      for (const [Wd, Hh] of W5.filter(x => x[2] === touch)) {
        for (const theme of ['dark', 'light']) {
          await v1(ag.token, 'GET', '/agent/events');  // stays connected
          await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: Wd, height: Hh}});
          await nav(B + 'static/icon.svg');
          await ev(`localStorage.setItem('tasks.theme', ${JSON.stringify(JSON.stringify(theme))}); 1`);
          // K01 / K02: the header on a long project name, Today and the calendar, with and without the task panel
          for (const [hash, name] of [['l/' + L, 'project'], ['today', 'today'], ['cal', 'calendar']]) {
            await open(hash); await sleep(2200);
            for (let i = 0; i < 30 && !(await ev(`!!document.querySelector('#top h1 .ht')`)); i++) await sleep(300);
            for (const panel of [0, 1]) {
              if (panel) { if (name === 'calendar') continue; await ev(`openDetail(${T2})`); await sleep(700); }
              const h = await ev(HEAD);
              const tag = `${Wd}px ${theme} ${name}${panel ? ' + panel' : ''}`;
              if (h.none) { check(false, `${tag}: no header: ${h.none}`); continue; }
              // 2.18.0 (#651, intended change): on a phone the search icon stays in the header, the title gets cut instead:
              // 12 characters where they fit, at least 6 (+ "…") on the narrowest phones
              // 2.26.1 (owner request, intended change): before the view switch folds into "…" the title may shrink to 6
              // characters (+ "…") on wider screens too, as long as nothing folds (level below tl3)
              const readable = h.full || h.htw + 0.5 >= h.w12 || ((Wd < 600 || !/tl[34]/.test(h.lvl)) && h.htw + 0.5 >= h.w6);
              // 2.18.0 (review R3, owner rule, intended change): one-tap actions stay in the header on every width and the
              // title is cut (>= 12 characters) instead; before, wide screens folded them into "…" to show the whole title
              check(readable, `${tag}: title readable (${h.full ? 'all' : Math.round(h.htw) + ' px of ' + Math.round(h.w12) + ' for 12 / ' + Math.round(h.w6) + ' for 6 characters'}) "${h.txt}" ${h.lvl}`);
              check(h.more && h.bell && h.more[0] >= 0 && h.more[1] <= h.vw + 0.5 && h.bell[1] <= h.vw + 0.5 && h.more[1] <= h.bell[0] + 0.5 && !h.out.length, `${tag}: "…" and the bell inside, nothing sticking out ${JSON.stringify({more: h.more, bell: h.bell, vw: h.vw, out: h.out})}`);
              check(h.st || h.ach, `${tag}: the agent shows (pill or status chip)`);
              if (theme === 'dark') await shot(`p260-head-${name}${panel ? '-panel' : ''}-${Wd}.png`);
              // 2.26.1 (#953): closing the task on a touch screen goes back one history step; that traversal must be over before
              // the next navigation (otherwise Firefox's navigate never answers)
              if (panel) { await ev(`typeof closeDetail === 'function' ? closeDetail() : null`).catch(() => {}); await sleep(800); }
            }
          }
          // K18: the toast above the composer, the tab bar and the + button
          await open('l/' + L); await sleep(2000);
          await ev(`toast('Done: Write the texts', () => {})`); await sleep(300);
          const ts = await ev(`(() => { const t = document.querySelector('#toast').getBoundingClientRect(), tops = ['#view .qdock .qadd', '#tabs', '#fab:not(.gone)'].map(s => document.querySelector(s)).filter(e => e && e.offsetWidth).map(e => e.getBoundingClientRect()).filter(r => r.top > innerHeight / 2);
            return {bottom: t.bottom, top: t.top, hit: tops.filter(r => r.top < t.bottom - 0.5 && r.bottom > t.top && r.left < t.right && r.right > t.left).length, n: tops.length}; })()`);
          check(ts.hit === 0 && ts.top >= 0, `${Wd}px ${theme}: the toast covers neither the composer nor the tab bar ${JSON.stringify(ts)}`);
          if (theme === 'dark') await shot(`p260-toast-${Wd}.png`);
          // K07: the date column is never cut on the left (desktop columns)
          if (Wd >= 1280) {
            const cut = await ev(`[...document.querySelectorAll('#view .tcols .c-date')].filter(c => c.offsetWidth && c.querySelector('.cdt')).filter(c => c.querySelector('.cdt').getBoundingClientRect().left < c.getBoundingClientRect().left - 0.5).length`);
            check(cut === 0, `${Wd}px ${theme}: no date cut on the left`);
          }
          // K25: the week title on one line
          await open('cal'); await sleep(1500);
          await ev(`S.calMode = 'week'; renderView(); 1`); await sleep(500);
          const wt = await ev(`(() => { const h = document.querySelector('#view .calbar h2'); if (!h) return null; const s = getComputedStyle(h); return {txt: h.textContent, h: h.getBoundingClientRect().height, lh: parseFloat(s.lineHeight) || parseFloat(s.fontSize) * 1.3}; })()`);
          check(wt && wt.h <= wt.lh * 1.5 + 1, `${Wd}px ${theme}: the week title on one line ${JSON.stringify(wt)}`);
          if (theme === 'dark' && Wd === 360) await shot(`p260-week-${Wd}.png`);
          // K17: contrast (desktop sizes, the views of the audit)
          if (Wd === 1280) {
            for (const [hash, js, nm] of [['all', `document.querySelector('[data-act=rm-view][data-k=timeline]')?.click()`, 'roadmap'], ['today', `openPalette(); setTimeout(() => { const i = document.querySelector('.palette input'); i.value = 'Web'; i.dispatchEvent(new Event('input', {bubbles: true})); }, 200)`, 'palette'],
              ['agents/' + ag.id, '', 'chat'], ['today', `settingsModal('ai')`, 'settings agents'], ['l/' + L, `shareModal(${L})`, 'share dialog']]) {
              await open(hash); await sleep(1800);
              if (js) { await ev(`(() => { ${js}; return 1; })()`); await sleep(900); }
              const bad = await ev(CONTRAST);
              check(!bad.length, `${theme} ${nm}: text contrast >= 4.5:1 ${JSON.stringify(bad.slice(0, 6))}`);
            }
          }
          // K10: touch targets at 390 px
          if (Wd === 390 && theme === 'dark') {
            const views = [['today', ''], ['l/' + L, ''], ['l/' + L, `openDetail(${T})`], ['l/' + CL, ''], ['cal', `S.calMode = 'week'; renderView()`], ['cal', `S.calMode = 'month'; renderView()`],
              ['agents', ''], ['agents/' + ag.id, ''], ['news', ''], ['matrix', ''], ['habits', ''], ['pomo', ''], ['time', ''], ['stats', ''],
              ['today', `settingsModal('ai')`], ['today', `settingsModal('notify')`], ['today', `settingsModal('users')`], ['l/' + L, `shareModal(${L})`], ['l/' + L, `listModal(${L})`]];
            const all = {};
            for (const [hash, js] of views) {
              await open(hash); await sleep(1800);
              if (js) { await ev(`(() => { ${js}; return 1; })()`); await sleep(900); }
              for (const x of await ev(TOUCH)) if (!TOUCH_OK.some(([re]) => re.test(x))) (all[x] = all[x] || []).push(hash + (js ? ' ' + js.slice(0, 24) : ''));
            }
            const keys = Object.keys(all);
            check(!keys.length, `390px touch: interactive elements below 44 x 44 px ${JSON.stringify(keys.slice(0, 12).map(k => k + ' @ ' + all[k][0]))}`);
          }
        }
      }
    }, touch);
  }
  await call('POST', '/api/time/stop', {});

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
