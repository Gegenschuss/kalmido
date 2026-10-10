// 2.36.2 UI tests (agent B), own container (start.sh). jsdom:
// #1141 "Job #12" / "job 12" in a chat is a link to the job (#job/12), not to task #12; a job I may not see stays plain
//       text (and is no task link either); #job/<id> opens Agents > Jobs with that job highlighted, its log unfolded (also a
//       finished job outside the "Open" filter); an unknown job: "Job not found", nothing highlighted
// #1123 the sidebar's "N approvals open" goes at once when the approval is answered in the chat
// Firefox 390 touch + 1440 mouse, light + dark: #1140 the permission badge without a frame, small and grey like the model,
//       Auto in the accent, a 44 px touch area that overlaps neither the ring nor the (i) button, some air under the name
//       in the phone's second header line; #1123 the live steps line up with "… is working on it" on the phone too.
//       Screenshots before (the 2.36.2 B rules taken out of the page) and after.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2362_b_ui', check, shots: 'P2362B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const FEAT = 'cal,comments,collab,agents';
const V = B + 'api/v1';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ME = (await call('GET', '/api/state')).me;
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Baker', password: 'password123'})).id;
  const CKB = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, CKB);
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  const AG = ag.id, AGH = {Authorization: 'Bearer ' + ag.token, 'Content-Type': 'application/json'};
  const L = (await call('POST', '/api/lists', {name: 'Software'})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: AG, role: 'edit'});
  const LB = (await call('POST', '/api/lists', {name: 'Bob and the agent'})).id;
  await call('PUT', `/api/lists/${LB}/members`, {user_id: AG, role: 'edit'});
  await call('PUT', `/api/lists/${LB}/members`, {user_id: BOB, role: 'edit'});
  const tids = [];
  for (let i = 0; i < 4; i++) tids.push((await call('POST', '/api/tasks', {title: 'Task ' + i, list_id: L})).id);
  const v1 = async (method, url, body) => (await fetch(V + url, {method, headers: AGH, body: body ? JSON.stringify(body) : undefined})).json();
  const say = (body, uid = ME.id, extra = {}) => v1('POST', `/agent/chats/${uid}`, {body, ...extra});
  const cm = (d, id) => d.querySelector(`#chat-msgs .cmsg[data-mid="a:${id}"]`);
  const job = await v1('POST', '/agent/jobs', {title: 'Release 2.36.2', task_id: tids[0], user_id: ME.id, log: 'started'});
  await v1('PATCH', `/agent/jobs/${job.id}`, {append_log: 'Build green'});
  await v1('PATCH', `/agent/jobs/${job.id}`, {state: 'done'});
  const J = job.id;
  check(J > 0 && tids.includes(J), `a task with the job's number exists (task #${J}) ` + JSON.stringify({J, tids}));

  // ================= #1141 jsdom: links in the chat
  const m1 = await say(`Job #${J} is done. Also job ${J} and JOB#${J}; job 987654 is someone else's. Task #${tids[1]} stays a task.`);
  let w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  w.eval(`chatOpen(${AG})`); await until(() => cm(d, m1.id));
  await until(() => !cm(d, m1.id)?.querySelector('.jrefq'));
  let b = cm(d, m1.id);
  const jl = [...(b?.querySelectorAll('a.jref') || [])];
  check(jl.length === 3 && jl.every(a => a.getAttribute('href') === `#job/${J}`) && jl[0].textContent === `Job #${J}` && jl[1].textContent === `job ${J}`,
    '#1141: three spellings link to the job ' + jl.map(a => a.outerHTML).join(' '));
  check(b && !b.querySelector(`a.tref[data-tref="${J}"]`), '#1141: the job number is no link to task #' + J);
  check(b && b.querySelector(`a.tref[data-tref="${tids[1]}"]`), '#1141: a plain #number still links the task');
  check(b && /job 987654/.test(b.textContent) && !b.querySelector('a[href="#job/987654"]') && !b.querySelector('.jrefq'), '#1141: an unknown job stays plain text');
  // ---- the route
  w.eval(`window.__toasts = []; const __t = toast; toast = (m, ...a) => { window.__toasts.push(String(m)); return __t(m, ...a); }`);
  w.location.hash = `#job/${J}`;
  await until(() => d.querySelector(`#job-${J}.jfocus`));
  const jf = d.querySelector(`#job-${J}.jfocus`);
  check(jf && /Release 2\.36\.2/.test(jf.textContent) && jf.querySelector('details.joblog[open]'), '#1141: #job/<id> opens Agents > Jobs with the job highlighted, its log unfolded ' + (jf?.outerHTML || '').slice(0, 200));
  check(d.querySelectorAll('.jobs .job.jfocus').length === 1, '#1141: exactly one job highlighted');
  w.location.hash = '#job/987654';
  await until(() => w.__toasts.includes('Job not found'));
  check(w.__toasts.includes('Job not found') && !d.querySelector('.job.jfocus'), '#1141: an unknown job: "Job not found", nothing highlighted ' + JSON.stringify(w.__toasts));
  w.close();
  // ---- bob may not see the job: plain text (a comment on a task of a list bob shares, where task #J is not his either)
  const TB = (await call('POST', '/api/tasks', {title: 'Shared with Bob', list_id: LB})).id;
  const cb = await call('POST', `/api/tasks/${TB}/comments`, {body: `Job #${J} belongs to Alice.`});
  check(cb.status < 300, 'comment ' + JSON.stringify(cb).slice(0, 160));
  w = await boot({user: 'bob', hash: 't/' + TB}); d = w.document;
  const cbx = () => [...d.querySelectorAll('#detail .cbody')].find(x => /belongs to Alice/.test(x.textContent));
  await until(() => cbx() && !cbx().querySelector('.jrefq'));
  b = cbx();
  check(b && new RegExp(`Job #${J} belongs`).test(b.textContent) && !b.querySelector('a'), '#1141: a job I may not see is plain text, no task link either ' + (b?.innerHTML || '').slice(0, 200));
  const bj = await call('GET', `/api/agents/jobs?id=${J}`, null, CKB);
  check(bj.status === 200 && Array.isArray(bj.jobs) && !bj.jobs.length, '#1141: the server lists nothing for a job bob may not see');
  const aj = await call('GET', `/api/agents/jobs?id=${J}`);
  check(aj.jobs?.length === 1 && aj.jobs[0].id === J, '#1141: ?id= lists the one job for alice');
  check((await call('GET', '/api/agents/jobs?id=abc')).status === 400, '#1141: ?id= must be a number');
  w.close();

  // ================= #1123 the approvals counter goes at once
  const ap = await v1('POST', `/agent/chats/${ME.id}`, {approval: {title: 'Publish the notes', what: 'They go live'}});
  check(ap.id > 0, 'approval request ' + JSON.stringify(ap).slice(0, 200));
  w = await boot({hash: 'today'}); d = w.document;
  await until(() => d.querySelector(`.srow[data-aid="${AG}"] .apvc`));
  check(/1/.test(d.querySelector(`.srow[data-aid="${AG}"] .apvc`)?.textContent || ''), '#1123: the sidebar counts the open approval');
  w.eval(`chatOpen(${AG})`);
  await until(() => d.querySelector(`#chat-apv [data-mid="${ap.id}"][data-cid="yes"]`));
  d.querySelector(`#chat-apv [data-mid="${ap.id}"][data-cid="yes"]`).click();
  await until(() => !d.querySelector(`.srow[data-aid="${AG}"] .apvc`), 15);
  check(!d.querySelector(`.srow[data-aid="${AG}"] .apvc`) && !d.querySelector('#achat.hidden'), '#1123: the sidebar counter is gone while the chat is still open');
  w.close();

  // ================= Firefox: the chat header (#1140) and the steps (#1123)
  await v1('PUT', '/agent/status', {status: 'working', text: 'Writing the notes', model: 'Opus 5.5', host_permission_mode: 'ask'});
  await call('PUT', `/api/agents/${AG}/permission-mode`, {mode: 'auto'});
  for (const t of ['I collect the merged tasks', 'Twelve tasks, three of them fixes']) await v1('POST', '/agent/progress', {text: t, chat_user_id: ME.id});
  await call('POST', `/api/agents/${AG}/chat`, {body: 'And the release notes?'});
  const ffLogin = async ({ev, nav}, theme) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"${theme}"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1, .chview, #achat')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  // the rules of the 2.36.2 B block taken out of the page = the state before (for the "before" screenshot)
  const BEFORE = `(() => { for (const sh of document.styleSheets) { let r; try { r = sh.cssRules; } catch { continue; }
      const i = [...r].findIndex(x => x.selectorText === '.chmode, button.chmode'); if (i < 0) continue;
      const j = [...r].findIndex((x, k) => k > i && x.selectorText === '.job.jfocus:focus'); for (let k = j; k >= i; k--) sh.deleteRule(k); return j - i + 1; } return 0; })()`;
  const HEAD = `(() => { const m = document.querySelector('.chnm .chmode'), nm = document.querySelector('.chnm b'), rg = document.querySelector('.chnm .chring'), ib = document.querySelector('.chnm .ib:not(.chring)');
      if (!m) return null; const cs = getComputedStyle(m), af = getComputedStyle(m, '::after'), r = m.getBoundingClientRect(), mid = (r.top + r.bottom) / 2, ah = parseFloat(af.height) || 0;
      const hit = {l: r.left, r: r.right, t: mid - ah / 2, b: mid + ah / 2};
      const box = e => { if (!e) return null; const x = e.getBoundingClientRect(), a = getComputedStyle(e, '::after'); return {l: x.left, r: x.right, t: x.top, b: x.bottom}; };
      const over = (p, q) => !!p && !!q && p.l < q.r - 0.5 && q.l < p.r - 0.5 && p.t < q.b - 0.5 && q.t < p.b - 0.5;
      const muted = getComputedStyle(document.documentElement).getPropertyValue('--muted').trim(), acc = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim();
      const probe = c => { const s = document.createElement('span'); s.style.color = c; document.body.appendChild(s); const v = getComputedStyle(s).color; s.remove(); return v; };
      const n = nm.getBoundingClientRect();
      return {bw: cs.borderTopWidth, fs: parseFloat(cs.fontSize), color: cs.color, acc: probe(acc), muted: probe(muted), auto: m.classList.contains('pm-auto'),
        w: Math.round(r.width), ah: Math.round(ah), ringOver: over(hit, box(rg)), ibOver: over(hit, box(ib)), row2: r.top >= n.bottom - 1, gap: Math.round(r.top - n.bottom),
        caret: getComputedStyle(m.querySelector('.pmlong') || m, '::after').content + '|' + getComputedStyle(m, '::before').content, wide: document.documentElement.scrollWidth <= innerWidth}; })()`;
  const STEPS = `(() => { const s = document.querySelector('#chat-steps .chstep'), t = document.querySelector('#chat-typing .ttx'); if (!s || !t) return {s: !!s, t: !!t};
      return {s: Math.round(s.getBoundingClientRect().left), t: Math.round(t.getBoundingClientRect().left)}; })()`;
  for (const theme of ['light', 'dark']) {
    await firefox(async o => {
      const {cmd, ev, ctx, shot} = o, tag = '390 ' + theme;
      check(await ffLogin(o, theme) === 200, tag + ': login');
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
      await o.nav(B + '#agents/' + AG); await ready(ev); await sleep(1200);
      await ev(`(() => { const b = document.querySelector('#chat-msgs'); if (b) b.scrollTop = b.scrollHeight; return 1; })()`); await sleep(300);
      const g = await ev(HEAD);
      check(g && g.bw === '0px' && g.fs <= 12.5 && g.auto && g.color === g.acc, `${tag}: #1140 no frame, small, Auto in the accent ` + JSON.stringify(g));
      check(g && g.w >= 44 && g.ah >= 44 && !g.ringOver && !g.ibOver, `${tag}: #1140 a 44 px touch area overlapping neither ring nor (i) ` + JSON.stringify(g));
      check(g && (!g.row2 || g.gap >= 4), `${tag}: #1123 some air between the name and the badge in the second line ` + JSON.stringify(g));
      check(g && g.wide, `${tag}: nothing sticks out sideways`);
      await v1('POST', '/agent/typing', {chat_user_id: ME.id}); await v1('POST', '/agent/progress', {chat_user_id: ME.id, text: 'I read the tests first'});
      await ev(`(() => { chatLoad(); return 1; })()`); await sleep(1500);
      const st = await ev(STEPS);
      check(st && st.s && st.t && Math.abs(st.s - st.t) <= 2, `${tag}: #1123 the steps line up with the text after the dots ` + JSON.stringify(st));
      await shot(`p2362b-390-${theme}-after.png`);
      await ev(BEFORE); await sleep(200);
      await shot(`p2362b-390-${theme}-before.png`);
    }, true);
    await firefox(async o => {
      const {cmd, ev, ctx, shot} = o, tag = '1440 ' + theme;
      check(await ffLogin(o, theme) === 200, tag + ': login');
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
      await o.nav(B + '#l/' + L); await ready(ev);
      await ev(`(() => { chatOpen(${AG}, {float: false}); return 1; })()`); await sleep(1800);
      const g = await ev(HEAD);
      check(g && g.bw === '0px' && g.fs <= 12.5 && g.color === g.acc && /▾/.test(g.caret) && /·/.test(g.caret), `${tag}: #1140 "· Auto ▾" without a frame ` + JSON.stringify(g));
      check(g && g.ah >= 24 && !g.ringOver && !g.ibOver, `${tag}: #1140 the click area (24 px) overlaps nothing ` + JSON.stringify(g));
      await call('PUT', `/api/agents/${AG}/permission-mode`, {mode: ''});
      await ev('load().then(render).then(() => chatLoad())'); await sleep(1200);
      const g2 = await ev(HEAD);
      check(g2 && !g2.auto && g2.color === g2.muted, `${tag}: #1140 the host default in grey ` + JSON.stringify(g2));
      const fv = await ev(`(() => { for (const sh of document.styleSheets) { let r; try { r = sh.cssRules; } catch { continue; } if ([...r].some(x => x.selectorText === 'button.chmode:focus-visible')) return 1; } return 0; })()`);
      check(fv === 1, `${tag}: #1140 the focus ring only for the keyboard (:focus-visible)`);
      await shot(`p2362b-1440-${theme}-after.png`);
      await ev(BEFORE); await sleep(200);
      await shot(`p2362b-1440-${theme}-before.png`);
      await call('PUT', `/api/agents/${AG}/permission-mode`, {mode: 'auto'});
    }, false);
  }

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
