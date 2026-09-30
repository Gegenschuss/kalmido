// 1.7.1 scroll regression suite (real browser, fresh DB): on a phone (360 x 780 and 390 x 844, touch, the folded Galaxy
// Fold's cover screen) every view must scroll far enough that its last line clears the fixed tab bar and the + button,
// its scroll box must really scroll (overflow auto, no touch-action: none up the tree) and a vertical finger drag must
// not be cancelled by a touch handler (preventDefault on touchmove). Bug in 1.7.0: the docked composer (1.5.3) set the
// list column's bottom padding to 0, also on phones where the composer is hidden, so the last rows sat under the tab bar
// and a list only a little longer than the screen (the user's "Tomorrow") could not be scrolled at all.
// jsdom has no layout, so this suite drives Firefox headless over WebDriver BiDi. No Firefox on PATH = skipped (exit 0).
const {spawn, execFileSync} = require('child_process');
const fs = require('fs'), os = require('os'), path = require('path');
const {B, login, sleep} = require('./boot');
const WS = globalThis.WebSocket || require('ws');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); if (!r.ok) throw new Error(`${method} ${url} ${r.status} ${JSON.stringify(j)}`); return j; };
const ymd = n => { const x = new Date(); x.setDate(x.getDate() + n); return `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}`; };

try { execFileSync('firefox', ['--version'], {stdio: 'ignore'}); } catch { console.log('scroll_ui: skipped (no firefox on PATH)\n0 ok, 0 failed'); process.exit(0); }

async function seed() {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const BK = await login('bob');
  const me = (await call('GET', '/api/state')).me.id;
  await call('PATCH', '/api/settings', {lang: 'en', features: 'cal,timeline,matrix,habits,pomo,kanban,paperless,collab,stats,time,progress,deps,fields',
    show_done_views: JSON.stringify({tomorrow: 1, today: 1})});
  const L = async (name, extra = {}) => (await call('POST', '/api/lists', {name, ...extra})).id;
  const home = await L('Home', {folder: 'Private'}), garden = await L('Garden', {folder: 'Private'});
  const shop = await L('Shopping', {kind: 'checklist'}), team = await L('Team', {kind: 'project'});
  const board = await L('Board', {view: 'kanban'}), plan = await L('Plan', {view: 'timeline'});
  await call('PUT', `/api/lists/${team}/members`, {user_id: BOB, role: 'edit'});
  const T = async (title, list_id, extra = {}) => (await call('POST', '/api/tasks', {title, list_id, ...extra})).id;
  // the user's "Tomorrow": a few tasks, one with subtasks, a pinned daily one with time and duration, a project task,
  // completed ones due tomorrow ("Completed" group) -- a little longer than the visible part of the screen
  const tm = await T('Prepare the workshop', home, {due: ymd(1)});
  for (let i = 1; i <= 4; i++) await T(`Workshop step ${i}`, home, {parent_id: tm});
  await T('Evening routine', home, {due: ymd(1), due_time: '21:00', repeat: 'FREQ=DAILY', pinned: 1, duration: 30});
  await T('Call the insurance about the letter from last week', home, {due: ymd(1)});
  await T('Project kickoff', team, {due: ymd(1)});
  await T('Dentist', home, {due: ymd(1), due_time: '15:00'});
  for (let i = 0; i < 2; i++) { const id = await T(`Done tomorrow ${i}`, home, {due: ymd(1)}); await call('PATCH', `/api/tasks/${id}`, {status: 2}); }
  for (let i = 0; i < 26; i++) {
    await T(`Task ${i} for the long lists`, i % 2 ? home : garden, {due: ymd(i % 9 - 2), tags: ['errand'], priority: [0, 1, 3, 5][i % 4], assignee_id: i % 3 ? null : me});
  }
  for (let i = 0; i < 24; i++) await T(`Item ${i}`, shop);
  const secs = [];
  for (const n of ['Backlog', 'Doing', 'Review']) secs.push((await call('POST', '/api/sections', {name: n, list_id: team})).id);
  let tfirst = 0;
  for (let i = 0; i < 24; i++) { const id = await T(`Team task ${i}`, team, {section_id: secs[i % 3], due: ymd(i % 5)}); tfirst = tfirst || id; }
  const ks = [];
  for (const n of ['Todo', 'Next']) ks.push((await call('POST', '/api/sections', {name: n, list_id: board})).id);
  for (let i = 0; i < 22; i++) await T(`Card ${i}`, board, {section_id: ks[i % 2]});
  for (let i = 0; i < 20; i++) await T(`Bar ${i}`, plan, {start: ymd(i % 4), due: ymd(i % 4 + 3)});
  for (let i = 0; i < 16; i++) { const id = await T(`Finished ${i}`, home, {due: ymd(-1)}); await call('PATCH', `/api/tasks/${id}`, {status: 2}); }
  for (let i = 0; i < 16; i++) { const id = await T(`Thrown away ${i}`, home); await call('DELETE', `/api/tasks/${id}`); }
  for (let i = 0; i < 14; i++) { const id = await L(`Old list ${i}`); await call('PATCH', `/api/lists/${id}`, {archived: 1}); }
  const long = await T('Task with a long description', home, {due: ymd(0), content: Array.from({length: 60}, (_, i) => `- [ ] line ${i} of a long note`).join('\n')});
  for (let i = 0; i < 14; i++) await call('POST', '/api/habits', {name: `Habit ${i}`});
  for (let i = 0; i < 18; i++) await call('POST', '/api/time/entries', {task_id: tfirst, minutes: 30 + i, start: `${ymd(-(i % 6))}T0${i % 9}:00:00`});
  await call('POST', '/api/time/start', {task_id: tfirst});
  const filt = (await call('POST', '/api/filters', {name: 'Soon', rules: {dates: ['7d']}})).id;
  // news for alice: bob comments on the shared list's tasks
  const st = await call('GET', '/api/state');
  const teamTasks = st.tasks.filter(t => t.list_id === team).slice(0, 14);
  for (const t of teamTasks) await call('POST', `/api/tasks/${t.id}/comments`, {body: `Looked at this <@${me}>`}, BK);
  return {home, shop, team, board, plan, long, filt};
}

(async () => {
  const S = await seed();
  const PORT = 9300 + Math.floor(Math.random() * 600);
  const prof = fs.mkdtempSync(path.join(process.env.TMPDIR || os.tmpdir(), 'kalmido-scroll-'));
  fs.writeFileSync(path.join(prof, 'user.js'), [['browser.shell.checkDefaultBrowser', false], ['datareporting.policy.dataSubmissionEnabled', false],
    ['ui.prefersReducedMotion', 1], ['dom.w3c_touch_events.enabled', 1], ['dom.w3c_touch_events.legacy_apis.enabled', true],
    ['ui.primarypointercapabilities', 1], ['ui.allpointercapabilities', 1]].map(([k, v]) => `user_pref("${k}", ${JSON.stringify(v)});`).join('\n') + '\n');
  const ff = spawn('firefox', ['--headless', '--no-remote', '--profile', prof, `--remote-debugging-port=${PORT}`, 'about:blank'], {stdio: 'ignore'});
  const done = code => { try { ff.kill(); } catch { /* gone */ } setTimeout(() => { fs.rmSync(prof, {recursive: true, force: true}); process.exit(code); }, 500); };
  let ws, seq = 0; const pend = new Map();
  for (let i = 0; i < 90 && !ws; i++) {
    try { const w = new WS(`ws://127.0.0.1:${PORT}/session`); await new Promise((res, rej) => { w.onopen = res; w.onerror = rej; }); ws = w; } catch { await sleep(500); }
  }
  if (!ws) { console.log('FAIL: no WebDriver BiDi connection to Firefox'); return done(1); }
  ws.onmessage = m => { const j = JSON.parse(m.data); if (j.id && pend.has(j.id)) { const p = pend.get(j.id); pend.delete(j.id); j.type === 'error' ? p.rej(new Error(p.method + ': ' + j.error + ' ' + j.message)) : p.res(j.result); } };
  const cmd = (method, params = {}) => new Promise((res, rej) => { const id = ++seq; pend.set(id, {res, rej, method}); ws.send(JSON.stringify({id, method, params})); });
  const unwrap = v => !v ? v : v.type === 'array' ? v.value.map(unwrap) : v.type === 'object' ? Object.fromEntries(v.value.map(([k, x]) => [typeof k === 'string' ? k : unwrap(k), unwrap(x)])) : v.value;
  await cmd('session.new', {capabilities: {}});
  const ctx = (await cmd('browsingContext.getTree', {})).contexts[0].context;
  const ev = async expr => { const r = await cmd('script.evaluate', {expression: expr, target: {context: ctx}, awaitPromise: true, resultOwnership: 'none', serializationOptions: {maxObjectDepth: 5}}); if (r.type === 'exception') throw new Error('JS: ' + r.exceptionDetails.text); return unwrap(r.result); };
  const nav = url => cmd('browsingContext.navigate', {context: ctx, url, wait: 'complete'});
  await nav(B + 'static/icon.svg');
  const lg = await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  check(lg === 200, 'browser login');

  // measured in the page: the scroll box, what covers the bottom of the screen, and whether the last line can be
  // scrolled above it. Leaves inside nested scroll boxes count as that box (it scrolls itself).
  const PROBE = String.raw`(sel) => {
    const v = document.querySelector(sel);
    if (!v) return {missing: true};
    const cs = e => getComputedStyle(e), shown = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && cs(e).visibility !== 'hidden'; };
    const probs = [];
    if (!/(auto|scroll)/.test(cs(v).overflowY)) probs.push('overflow-y ' + cs(v).overflowY);
    for (let p = v; p; p = p.parentElement) { const ta = cs(p).touchAction; if (!/auto|manipulation|pan-y/.test(ta)) probs.push('touch-action ' + ta + ' on ' + (p.id || p.className)); }
    const tabs = document.querySelector('#tabs');
    const tabsTop = tabs && shown(tabs) && cs(tabs).position === 'fixed' ? tabs.getBoundingClientRect().top : innerHeight;
    const vr = v.getBoundingClientRect(), limitBase = Math.min(tabsTop, vr.bottom, innerHeight);
    v.scrollTop = v.scrollHeight;
    const scrolled = v.scrollTop;
    const nested = e => { for (let p = e.parentElement; p && p !== v; p = p.parentElement) { const s = cs(p); if (/(auto|scroll|hidden|clip)/.test(s.overflowY) && p.scrollHeight > p.clientHeight + 1) return true; } return false; };
    let worst = null;
    for (const e of v.querySelectorAll('*')) {
      if (!shown(e) || cs(e).position === 'fixed' || e.closest('.hidden') || (e.closest('details:not([open])') && !e.closest('summary'))) continue;
      const leaf = !e.firstElementChild || (/(auto|scroll)/.test(cs(e).overflowY) && e.scrollHeight > e.clientHeight + 1);
      if (!leaf || nested(e)) continue;
      const r = e.getBoundingClientRect();
      if (r.bottom <= vr.top + vr.height / 2 || r.top >= vr.bottom) continue;  // the lower half is where the bottom bars sit
      // hit test near its bottom edge: what the finger would touch there must be this box, not the tab bar / + / a sheet
      const x = Math.round(Math.max(vr.left + 1, Math.min(vr.right - 1, (r.left + r.right) / 2))), y = Math.round(Math.min(r.bottom - Math.min(4, r.height / 2), vr.bottom - 1));
      const hit = y >= innerHeight ? null : document.elementFromPoint(x, y);
      if (hit && v.contains(hit) && r.bottom <= vr.bottom + 1) continue;
      const cover = hit ? hit.closest('#tabs, #fab, .modal, #detail, #side, .toast, .mbar') || hit : null;
      const over = r.bottom - (cover ? cover.getBoundingClientRect().top : Math.min(vr.bottom, innerHeight));
      if (!worst || over > worst.over) worst = {over: Math.round(over), el: e.tagName + (e.id ? '#' + e.id : '') + '.' + [...e.classList].join('.'), text: (e.textContent || '').trim().slice(0, 30),
        by: cover ? (cover.id ? '#' + cover.id : cover.tagName + '.' + [...cover.classList].join('.')) : 'off screen'};
    }
    if (worst) probs.push('cannot scroll into view (' + worst.over + 'px under ' + worst.by + '): ' + worst.el + ' "' + worst.text + '"');
    // a vertical finger drag on the middle of the box must not be cancelled (the browser scrolls it)
    let prevented = null;
    if (typeof Touch === 'function' && typeof TouchEvent === 'function') {
      v.scrollTop = 0;
      const x = Math.round((vr.left + vr.right) / 2), y = Math.round(vr.top + Math.min(vr.height, limitBase - vr.top) * 0.6);
      const tgt = document.elementFromPoint(x, y) || v;
      const mk = (type, yy) => { const t = new Touch({identifier: 7, target: tgt, clientX: x, clientY: yy, pageX: x, pageY: yy}); return new TouchEvent(type, {bubbles: true, cancelable: true, composed: true, touches: type === 'touchend' ? [] : [t], targetTouches: type === 'touchend' ? [] : [t], changedTouches: [t]}); };
      tgt.dispatchEvent(mk('touchstart', y));
      prevented = false;
      for (const dy of [12, 30, 60, 90]) { const e2 = mk('touchmove', y - dy); tgt.dispatchEvent(e2); if (e2.defaultPrevented) prevented = true; }
      tgt.dispatchEvent(mk('touchend', y - 90));
      if (prevented) probs.push('touchmove cancelled by a handler (target ' + tgt.tagName + '.' + [...tgt.classList].join('.') + ')');
    }
    return {sh: v.scrollHeight, ch: v.clientHeight, scrolled, tabsTop: Math.round(tabsTop), touchTested: prevented !== null, probs};
  }`;
  const views = [
    ['today', 'today'], ['tomorrow', 'tomorrow'], ['next 7 days', 'week'], ['now doable', 'doable'], ['inbox', 'inbox'], ['assigned', 'assigned'],
    ['all', 'all'], ['completed', 'done'], ['trash', 'trash'], ['archived lists', 'archived'], ['list', 'l/' + S.home], ['checklist', 'l/' + S.shop],
    ['project with sections', 'l/' + S.team], ['kanban', 'l/' + S.board], ['timeline list', 'l/' + S.plan], ['folder', 'folder/Private'],
    ['filter', 'f/' + S.filt], ['tag', 'tag/errand'],
    ['search results', 'search', `const i = document.querySelector('#searchq'); i.value = 'Task'; i.dispatchEvent(new Event('input', {bubbles: true}));`],
    ['calendar month', 'cal', `S.calMode = 'month'; render();`], ['calendar week', 'cal', `S.calMode = 'week'; render();`],
    ['calendar day', 'cal', `S.calMode = 'day'; render();`], ['calendar timeline', 'cal', `S.calMode = 'timeline'; render();`],
    ['matrix', 'matrix'], ['habits', 'habits'], ['focus', 'pomo'], ['statistics', 'stats'], ['time tracking (timer running)', 'time'],
    ['news', 'news'], ['overview', 'overview'],
    ['task panel, long description', 'today', `openDetail(${S.long});`, '#detail'],
    ['drawer', 'today', `document.querySelector('[data-act="side"]').click();`, '#side'],
  ];
  const secs = ['account', 'general', 'look', 'modules', 'notify', 'integr', 'data', 'users', 'help'];
  for (const s of secs) views.push(['settings: ' + s, 'today', `settingsModal('${s}');`, '.smodal .spanes']);
  let touchTested = false;
  for (const [w, h] of [[360, 780], [390, 844]]) {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: w, height: h}});
    for (const [name, hash, js, sel] of views) {
      const tag = `${w}x${h} ${name}`;
      try {
        await nav(B + 'static/icon.svg');
        await nav(B + '#' + hash);
        await ev(`new Promise(r => { const t0 = Date.now(); (function wait() { if (document.querySelector('#view')?.children.length || Date.now() - t0 > 8000) r(1); else setTimeout(wait, 100); })(); })`);
        await sleep(600);
        if (js) { await ev(`(async () => { ${js} })()`); await sleep(900); }
        const r = await ev(`(${PROBE})(${JSON.stringify(sel || '#view')})`);
        if (r.missing) { check(false, `${tag}: no scroll box ${sel || '#view'}`); continue; }
        touchTested = touchTested || r.touchTested;
        check(!r.probs.length, `${tag}: ${r.probs.join('; ') || 'ok'} (scrollHeight ${r.sh}, box ${r.ch})`);
      } catch (e) { check(false, `${tag}: ${e.message}`); }
    }
  }
  check(touchTested, 'Firefox created touch events (the touchmove check ran)');
  // the regression itself, spelled out: the user's Tomorrow list overflows the visible part and does scroll
  await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 360, height: 780}});
  await nav(B + 'static/icon.svg'); await nav(B + '#tomorrow'); await sleep(1500);
  await ev(`(document.querySelector('#view .ghead[data-key="done-open"].closed')?.click(), 1)`); await sleep(400);
  const tmr = await ev(`(() => { const v = document.querySelector('#view'); return {sh: v.scrollHeight, ch: v.clientHeight, pb: parseFloat(getComputedStyle(v).paddingBottom)}; })()`);
  check(tmr.pb > 60 && tmr.sh > tmr.ch, `Tomorrow (phone): room below the last row for the tab bar and + (${tmr.pb}px) and it scrolls (${tmr.sh} > ${tmr.ch})`);
  console.log(`${ok} ok, ${F.length} failed`);
  done(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
