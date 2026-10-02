// 2.5.2 UI tests (hotfix from UX audit 2), own container (start.sh). jsdom: the review dialog of a "break down" and a
// "tasks from notes" proposal without stray commas between the entries (K03), one compact line per entry (title + date
// side by side), the count next to Apply in the sticky footer; the tour card placed with its measured height (K05);
// Settings > Notifications: the neutral push hint (K04, not red); Settings > Administration > Admin alerts: "Admin
// alerts", the real destination per admin (K04); the task panel's date chip in its own shrinking span (K06); the own
// file buttons in Data > Import and Backups with the file name (K15); German plurals "1 Tag" / "2 Tage" and the axis
// labels of a narrow chart without overlaps (K16); a proposal of someone else opened via its link: a readable message
// instead of "unknown" (K19); "Ready to start" as one label (K20); SW v71. Then Firefox headless (WebDriver BiDi, skipped
// without firefox) while an agent is working and a timer runs: at 360 x 780, 390 x 844 and 1280 x 800 the header's "…"
// and the bell are inside the viewport (K01; the agent pill is the bot + a number on the phones), at 360 / 390 / 904 /
// 1280 the task panel has no sideways scroll and the checkbox does not overlap the date chip (K06, K22), the review
// dialog's Apply is visible without scrolling (K03), and every tour card incl. step 5 (settings) at 1280 x 800 is fully
// inside the window (K05) (screenshots with P252_SHOTS=<dir>).
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
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const ALL = 'cal,timeline,matrix,habits,pomo,kanban,paperless,collab,stats,time,progress,deps,fields,agents,comments';

async function firefox(fn) {
  try { execFileSync('firefox', ['--version'], {stdio: 'ignore'}); } catch { console.log('p252_ui: Firefox part skipped (no firefox on PATH)'); return; }
  const PORT = 9300 + Math.floor(Math.random() * 600);
  const prof = fs.mkdtempSync(path.join(process.env.TMPDIR || os.tmpdir(), 'kalmido-p252-'));
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
    const shot = async name => { const dir = process.env.P252_SHOTS; if (!dir) return; const r = await cmd('browsingContext.captureScreenshot', {context: ctx}); fs.writeFileSync(path.join(dir, name), Buffer.from(r.data, 'base64')); };
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
  check(/const CACHE = 'tasks-shell-v(?:7[1-9]|8[0-9])'/.test(SW), 'service worker cache v71 (2.6.0: v72, 2.6.1: v73, 2.7.0: v74, 2.7.1: v75, 2.7.2: v76, 2.8.0: v77, 2.9.0: v78, 2.10.0: v79, 2.11.0: v80)');
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en', tour: 'done'});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const CKB = await login('bob');
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en', tour: 'done'}, CKB);
  const ag = await call('POST', '/api/admin/agents', {username: 'claude', display_name: 'Claude'});
  const L = (await call('POST', '/api/lists', {name: 'Website', kind: 'project'})).id;  // a project: time tracking
  for (const id of [BOB, ag.id]) await call('PUT', `/api/lists/${L}/members`, {user_id: id, role: 'edit'});
  const T = (await call('POST', '/api/tasks', {title: 'Go live', list_id: L, due: '2031-05-04', start: '2031-05-01', content: '- [ ] check DNS\n- [ ] a rather long checklist line to turn into a subtask'})).id;
  const T2 = (await call('POST', '/api/tasks', {title: 'Follow-up', list_id: L})).id;
  await call('POST', '/api/deps', {task_id: T2, blocker_id: T});
  // a "break down" proposal with 6 entries and a "tasks from notes" one with 2
  const JS = (await call('POST', '/api/proposals', {agent_id: ag.id, kind: 'subtasks', task_id: T})).id;
  check((await v1(ag.token, 'POST', `/agent/jobs/${JS}/proposal`, {summary: 'Six steps', items: ['Switch DNS', 'Check SSL', 'Test redirects', 'Turn on analytics', 'Tell the client', 'Watch the logs'].map(t => ({title: t}))})).status === 201, 'agent: break-down proposal');
  const JX = (await call('POST', '/api/proposals', {agent_id: ag.id, kind: 'extract', list_id: L, text: 'Notes: book the studio, send the invoice'})).id;
  check((await v1(ag.token, 'POST', `/agent/jobs/${JX}/proposal`, {tasks: [{title: 'Book the studio'}, {title: 'Send the invoice'}]})).status === 201, 'agent: tasks-from-notes proposal');

  // ================= K03: the review dialog
  let w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  for (const [jid, n] of [[JS, 6], [JX, 2]]) {
    w.eval(`propOpen(${jid})`);
    const md = await until(() => d.querySelector('.ppm .ppl'));
    const ppl = d.querySelector('.ppm .ppl');
    const stray = [...ppl.childNodes].filter(x => x.nodeType === 3 && /,/.test(x.textContent));
    check(md && ppl.querySelectorAll('.ppi').length === n && stray.length === 0 && !/^\s*,|>\s*,\s*</.test(ppl.innerHTML), `job ${jid}: ${n} entries, no stray commas`);
    const row = ppl.querySelector('.ppi');
    check(row.querySelector('.pprow .ppt') && row.querySelector('.pprow [data-dpfor]'), `job ${jid}: title and date on one line`);
    const foot = d.querySelector('.ppm .foot.ppfoot');
    check(foot && foot.querySelector('.ppcount') && /of \d+ selected/.test(foot.querySelector('.ppcount').textContent) && foot.querySelector('[data-pp="apply"]') && d.querySelectorAll('.ppm .ppcount').length === 1, `job ${jid}: the count next to Apply in the footer`);
    d.querySelector('.ppm').remove(); w.eval('S.prop = null');
  }
  // ================= K06: the date chip
  w.eval(`openDetail(${T})`); await sleep(400);
  const dc = d.querySelector('#detail .dtop .dchip');
  check(dc && dc.querySelector('.dct') && /–/.test(dc.querySelector('.dct').textContent) && /Change date/.test(dc.title) && dc.title.includes(dc.querySelector('.dct').textContent), 'the date chip: text in its own span, the full date in the tooltip');
  // ================= K20: "Ready to start" is one label
  w.close();
  w = await boot({user: 'alice', hash: 'l/' + L}); d = w.document;
  const nx = d.querySelector('#view .nxt');
  check(!nx || (nx.querySelector('.nxl') && /Ready to start/.test(nx.querySelector('.nxl').textContent)), '"Ready to start" in one label span');
  // ================= K05: the tour card uses its real height
  const tp = w.eval(`tourPlace({left: 8, top: 740, right: 52, bottom: 784, width: 44, height: 44}, 1280, 800, 300)`);
  const top = +(/top:(-?[\d.]+)px/.exec(tp.card) || [])[1];
  check(top + 300 <= 800 - 12 && top >= 12, 'tour card with a measured height of 300 px stays inside 800 px: ' + tp.card);
  const tp0 = w.eval(`tourPlace({left: 8, top: 740, right: 52, bottom: 784, width: 44, height: 44}, 1280, 800)`);
  check(/top:578px/.test(tp0.card), 'without a measurement the old 210 px estimate: ' + tp0.card);
  // ================= K04: notifications + admin alerts
  w.eval(`settingsModal('notify')`); await sleep(900);
  let md = d.querySelector('.smodal');
  w.eval(`wpState(document.querySelector('.smodal'), {channel: 'webpush', subs: [], ntfy: true})`);
  const wps = md.querySelector('#s-wpstate');
  check(wps && /No device subscribed for push yet\. Until then, notifications go to your ntfy topic\./.test(wps.textContent) && !wps.classList.contains('warn'), 'notifications: a neutral hint, not red: ' + wps?.textContent);
  w.eval(`wpState(document.querySelector('.smodal'), {channel: 'webpush', subs: [], ntfy: false})`);
  check(/Turn on “Notify on this device”/.test(wps.textContent), 'without ntfy: how to turn it on');
  md.remove();
  w.eval(`settingsModal('users')`);
  md = await until(() => d.querySelector('.smodal #aa-on') && d.querySelector('.smodal'));
  const aa = md.querySelector('#s-aa');
  check(/Admin alerts/.test(aa.textContent) && !/Admin alerts via ntfy/.test(aa.textContent) && /over their own notification channel/.test(aa.textContent) && /alice: ntfy/.test(aa.textContent), 'admin alerts: the real destination per admin: ' + aa.textContent.slice(0, 300));
  // the "nowhere yet" hint for an admin without a device or a chosen topic (drawn from a fake answer)
  const j0 = await call('GET', '/api/admin/alerts');
  await w.eval(`aaDraw(document.querySelector('.smodal'), ${JSON.stringify({...j0, env: true, on: true, admins: [{username: 'alice', topic: '', devices: 0, me: true}]})})`);
  const none = md.querySelector('.aanone');
  check(none && /only listed here/.test(none.textContent) && none.querySelector('[data-aa="notify"]') && /alice: nowhere yet/.test(aa.textContent), 'no destination: the neutral hint with "Subscribe this device"');
  none.querySelector('[data-aa="notify"]').dispatchEvent(new w.MouseEvent('click', {bubbles: true}));
  await sleep(300);
  check(md.querySelector('.snav [data-sec="notify"].on, .snav [data-sec="notify"][aria-selected="true"]') || md.querySelector('#s-wpstate, #s-pushch'), 'the button opens Notifications');
  md.remove();
  // ================= K15: own file buttons
  w.eval(`settingsModal('data')`); await sleep(900);
  md = d.querySelector('.smodal');
  const fi = md.querySelector('#s-import');
  check(fi && fi.hidden && fi.closest('.filebtn') && /Choose a file…/.test(fi.closest('.filebtn').textContent) && md.querySelector('#s-import-name').textContent === 'No file chosen', 'import: an own file button, "No file chosen"');
  Object.defineProperty(fi, 'files', {configurable: true, value: [new w.File(['x'], 'todoist.csv')]});
  fi.dispatchEvent(new w.Event('change', {bubbles: true}));
  await sleep(300);
  check(md.querySelector('#s-import-name').textContent === 'todoist.csv', 'the chosen file name is shown');
  md.remove();
  w.eval(`settingsModal('users')`);
  md = await until(() => d.querySelector('.smodal #bk-file') && d.querySelector('.smodal'), 60);
  check(md && md.querySelector('#bk-file').hidden && md.querySelector('#bk-file').closest('.filebtn'), 'backups: the own file button too');
  md?.remove();
  // ================= K16: German plurals, chart labels
  w.close();
  await call('PATCH', '/api/settings', {lang: 'de'});
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  check(w.eval(`trn('day', 'days', 1)`) === 'Tag' && w.eval(`trn('day', 'days', 2)`) === 'Tage' && w.eval(`trn('week', 'weeks', 1)`) === 'Woche', 'German: 1 Tag / 2 Tage / 1 Woche');
  const svg = w.eval(`barChart([1,2,3,4,5,6,7,8,9,10,11,12], ['13. Juli','20. Juli','27. Juli','3. Aug.','10. Aug.','17. Aug.','24. Aug.','31. Aug.','7. Sept.','14. Sept.','21. Sept.','28. Sept.'], {tip: i => '', label: 'x', w: 320})`);
  const xs = [...svg.matchAll(/<text class="ch-ax" x="([\d.]+)" y="[\d.]+" text-anchor="(\w+)">([^<]+)<\/text>/g)].filter(m => !/^\d+$/.test(m[3])).map(m => ({x: +m[1], a: m[2], s: m[3]}));
  const spans = xs.map(m => { const wd = m.s.length * 6.6; return m.a === 'end' ? [m.x - wd, m.x] : [m.x - wd / 2, m.x + wd / 2]; }).sort((a, b) => a[0] - b[0]);
  check(xs.length >= 2 && xs.length < 12 && spans.every((s, i) => !i || s[0] >= spans[i - 1][1]), 'axis labels thinned out, none overlapping: ' + xs.map(m => m.s).join(' | '));
  w.close();
  await call('PATCH', '/api/settings', {lang: 'en'});
  // ================= K19: someone else's proposal
  w = await boot({user: 'bob', hash: 'today'}); d = w.document;
  w.eval(`propOpen(${JS})`); await sleep(600);
  const toastT = d.querySelector('#toast')?.textContent || '';
  check(/This proposal is not available: only the person who asked for it can open it/.test(toastT) && !/\bunknown\b/.test(toastT) && !d.querySelector('.ppm'), 'K19: a readable message: ' + toastT);
  w.close();

  // ================= Firefox: an agent is working, a timer runs
  await v1(ag.token, 'PUT', '/agent/status', {status: 'working', task_id: T, text: 'Breaking it down'});
  const tst = await call('POST', '/api/time/start', {task_id: T});
  check(tst.status === 200, 'timer started: ' + JSON.stringify(tst).slice(0, 200));
  await call('PATCH', '/api/settings', {tour: 'done'});
  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    await nav(B + 'static/icon.svg');
    const lgi = await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    check(lgi === 200, 'Firefox: login');
    const rect = s => `(() => { const e = document.querySelector('${s}'); if (!e) return null; const r = e.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; })()`;
    for (const [W, Hh] of [[360, 780], [390, 844], [904, 1080], [1280, 800]]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: W, height: Hh}});
      await nav(B + 'static/icon.svg'); await nav(B + '#l/' + L); await sleep(2500);
      // K01: "…" and the bell stay inside the viewport while the agent pill and the timer pill show
      const hd = await ev(`({vw: innerWidth, more: ${rect('#top [data-act="top-more"]')}, bell: ${rect('#top .bell')}, achip: ${rect('#top .achip')}, tmini: ${rect('#top .tmini')}, st: ${rect('#top .stchip')}, acn: (() => { const e = document.querySelector('#top .achip .acn'); return e ? getComputedStyle(e).display : null; })(), doc: document.documentElement.scrollWidth - innerWidth})`);
      if (W !== 904) {
        check((hd.achip && hd.tmini) || hd.st, `${W}px: agent pill and timer pill shown (2.6.0: or merged into the status chip) ${JSON.stringify(hd)}`);
        check(hd.more && hd.bell && hd.more[0] >= 0 && hd.more[2] <= hd.vw && hd.bell[2] <= hd.vw && hd.doc <= 0, `${W}px: "…" and the bell inside the viewport ${JSON.stringify(hd)}`);
      }
      if (W <= 390) check(hd.st || (hd.acn && hd.acn !== 'none'), `${W}px: the agent pill is the bot + a number (2.6.0: or the merged status chip)`);
      await shot(`p252-head-${W}.png`);
      // K06 / K22: the panel
      await ev(`openDetail(${T})`); await sleep(700);
      const dp = await ev(`(() => { const d = document.getElementById('detail'), c = d.querySelector('.dtop .chk').getBoundingClientRect(), x = d.querySelector('.dtop .dchip').getBoundingClientRect(), t = d.querySelector('.dtop .dchip .dct');
        return {sw: d.scrollWidth, cw: d.clientWidth, gap: x.left - c.right, clipped: t.scrollWidth > t.clientWidth + 1, ell: getComputedStyle(t).textOverflow, out: [...d.querySelectorAll('.dtop > *')].filter(e => e.offsetWidth && e.getBoundingClientRect().right > d.getBoundingClientRect().left + d.clientWidth + 0.5).length}; })()`);
      check(dp.sw <= dp.cw && dp.gap >= 0 && dp.out === 0 && (!dp.clipped || dp.ell === 'ellipsis'), `${W}px: panel without sideways scroll, checkbox clear of the date ${JSON.stringify(dp)}`);
      await shot(`p252-panel-${W}.png`);
      await ev(`closeDetail ? closeDetail() : null`).catch(() => {});
      // K03: Apply visible without scrolling
      await ev(`propOpen(${JS})`); await sleep(900);
      const ap = await ev(`(() => { const b = document.querySelector('.ppm [data-pp="apply"]').getBoundingClientRect(), c = document.querySelector('.ppm .card'); return {top: b.top, bottom: b.bottom, vh: innerHeight, st: c.scrollTop, commas: [...document.querySelector('.ppm .ppl').childNodes].filter(n => n.nodeType === 3 && n.textContent.includes(',')).length}; })()`);
      check(ap.bottom <= ap.vh && ap.top >= 0 && ap.st === 0 && ap.commas === 0, `${W}px: Apply visible without scrolling, no commas ${JSON.stringify(ap)}`);
      await shot(`p252-proposal-${W}.png`);
      await ev(`document.querySelector('.ppm').remove(); S.prop = null`);
      // K05: every tour card inside the window
      await ev(`tourStart()`); await sleep(500);
      const cards = await ev(`(async () => { const out = []; for (let i = 0; i < TOUR.steps.length; i++) { tourGo(i); await new Promise(r => setTimeout(r, 250)); const c = document.querySelector('.tour .tcard').getBoundingClientRect(), n = document.querySelector('.tour [data-tour="next"]').getBoundingClientRect(); out.push({id: TOUR.steps[i].id, top: c.top, bottom: c.bottom, nb: n.bottom, vh: innerHeight}); } return out; })()`);
      const bad = cards.filter(c => c.top < 0 || c.bottom > c.vh || c.nb > c.vh);
      check(cards.length >= 5 && !bad.length && (W !== 1280 || cards.some(c => c.id === 'settings')), `${W}px: every tour card inside the window ${JSON.stringify(bad.length ? bad : cards.map(c => c.id))}`);
      await ev(`tourGo(TOUR.steps.findIndex(s => s.id === 'settings'))`); await sleep(300);
      await shot(`p252-tour-settings-${W}.png`);
      await ev(`tourEnd(true)`); await sleep(300);
    }
  });
  await call('PATCH', '/api/settings', {tour: 'done'});

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
