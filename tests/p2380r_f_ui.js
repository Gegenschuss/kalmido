// kalmido-suite:
// 2.380 F UI test, own container (start.sh), Firefox 1280 px and 390 px. Invented people only.
// - #3411: the office sidebar has no "Show more": Money opened shows every point (figures, travel ... before anything is
//   used); Settings > Functions has a switch per point of Money; off = the point leaves the sidebar, a link opens another
//   tab; on again = back
// - #3381: the agent chat keeps its place: first open at the newest message; scrolled up, away and back = the same place;
//   new agent messages while away (tab hidden or another page) = it opens at the first new one with the line
//   "New messages" and "New message ↓"; at the bottom and nothing new = the bottom; own sending = the bottom, line gone
// - #3436: the subtasks of the task view move by dragging the row (mouse: its own drag), saved in the list's sort field;
//   completed ones are no neighbours
// - #3435: a section of the task view folds by its heading; one account setting for all tasks (server), a short line in
//   the folded head ("2 open"); "Unfold all sections" in the task's "…" menu
// freelancer-matrix: office (frida has no organisation, P4)
// P2380RF_NOSTART=1 = the server already runs. Screenshots: P2380RF_SHOTS.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2380r_f_ui', check, shots: 'P2380RF_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2380RF_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => {
  for (let i = 0; ; i++) {
    const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined});
    if (r.status === 429 && i < 8) { await sleep(500 * (i + 1)); continue; }
    const j = await r.json().catch(() => ({})); return {...j, http: r.status};
  }
};
const tcall = async (method, url, tok, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + tok}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const FEAT = 'cal,comments,collab,contacts,office,clients,docs,agents,fields,deps,time';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida Solo', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(!((await call(CF, 'GET', '/api/state')).me.workspaces || []).length, 'P4: frida has no organisation');
  await call(CF, 'PUT', '/api/office/settings', {company: {name: 'Studio Example'}, lang: 'en'});
  // the agent and its chat with frida: 24 messages, tall enough to scroll
  await call(CA, 'PUT', '/api/admin/agent-policy', {user_agents: true});
  const ag = await call(CF, 'POST', '/api/my/agents', {username: 'helper', display_name: 'Helper', scopes: ['read', 'write']});
  check(ag.http < 300 && ag.id && ag.token, 'frida\'s agent ' + ag.http);
  const AG = ag.id, TOK = ag.token, ME = (await call(CF, 'GET', '/api/state')).me.id;
  const say = body => tcall('POST', `/agent/chats/${ME}`, TOK, {body});
  const P = (await call(CF, 'POST', '/api/lists', {name: 'Website', kind: 'project'})).id;  // the agent answers people it shares a list with
  await call(CF, 'PUT', `/api/lists/${P}/members`, {user_id: AG, role: 'edit'});
  check((await say('Hello')).status < 300, 'the agent answers in the chat');
  for (let i = 1; i <= 24; i++) {
    if (i % 2) await call(CF, 'POST', `/api/agents/${AG}/chat`, {body: `Question ${i}`});
    else await say(`Answer ${i}\n\nwith a second paragraph so the list is tall enough to scroll`);
  }

  // a task with three subtasks (the middle one done) and a second one with a subtask
  const PT = (await call(CF, 'POST', '/api/tasks', {title: 'Episode two', list_id: P})).id;
  const SA = (await call(CF, 'POST', '/api/tasks', {title: 'Sub A', list_id: P, parent_id: PT})).id;
  const SB = (await call(CF, 'POST', '/api/tasks', {title: 'Sub B', list_id: P, parent_id: PT})).id;
  const SC = (await call(CF, 'POST', '/api/tasks', {title: 'Sub C', list_id: P, parent_id: PT})).id;
  await call(CF, 'POST', `/api/tasks/${SB}/complete`, {});
  const PT2 = (await call(CF, 'POST', '/api/tasks', {title: 'Episode three', list_id: P})).id;
  await call(CF, 'POST', '/api/tasks', {title: 'Sub D', list_id: P, parent_id: PT2});
  const sortOf = async () => { const ts = (await call(CF, 'GET', '/api/state')).tasks; const g = i => ts.find(t => t.id === i)?.sort; return {a: g(SA), b: g(SB), c: g(SC)}; };
  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const click = (ev, sel) => ev(`(() => { const b = document.querySelector(${JSON.stringify(sel)}); if (!b) return 0; b.click(); return 1; })()`);
  const signIn = async (ev, nav, u) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`) === 200, `${u} signs in`);
  };

  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    // ================= #3411 the office sidebar (computer)
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await signIn(ev, nav, 'frida');
    await nav(B + '#office/offers');
    check(await ready(ev, `typeof OFC === 'object' && !!OFC.info && !!document.querySelector('#side [data-g="office:money"]')`, 80), '#3411: the office with its sidebar');
    if (await ev(`document.querySelector('#side [data-g="office:money"]').getAttribute('aria-expanded') === 'false'`)) await click(ev, '#side [data-act="sbb-group"][data-g="office:money"]');
    const side = `[...document.querySelectorAll('#side [data-ofmg="money"] [data-ofm]')].map(b => b.dataset.ofm).join()`;
    check(await ready(ev, `!!document.querySelector('#side [data-ofmg="money"] [data-ofm="kpi"]')`, 20), '#3411: Money open');
    const pts = await ev(side);
    check(['cashflow', 'kpi', 'travel', 'meals', 'subs'].every(k => pts.split(',').includes(k)) && await ev(`!document.querySelector('[data-act="ofm-more"]')`),
      '#3411: every point of Money at once, no "Show more", although nothing is used yet ' + pts);
    await shot('p2380rf-money.png');
    // the switches under Settings > Functions
    await nav(B + '#office/settings');
    check(await ready(ev, `!!document.querySelector('#ofc-set [data-ostsub="functions"]')`, 80), '#3411: the office settings');
    await click(ev, '#ofc-set [data-ostsub="functions"]');
    check(await ready(ev, `['money.cashflow', 'money.kpi', 'money.travel', 'money.meals', 'money.subs'].every(k => document.querySelector('#ofc-set [data-feat="' + k + '"]')?.checked)`, 20),
      '#3411: Functions has the five switches of Money, all on');
    await shot('p2380rf-functions.png');
    await click(ev, '#ofc-set [data-feat="money.kpi"]');
    const off = async () => { for (let i = 0; i < 40; i++) { const j = await call(CF, 'GET', '/api/office/settings'); if ((j.settings?.features_off || []).includes('money.kpi')) return j; await sleep(250); } return null; };
    check(!!(await off()), '#3411: the switch saves itself');
    check(await ready(ev, `!document.querySelector('#side [data-ofm="kpi"]') && !!document.querySelector('#side [data-ofm="cashflow"]')`, 40), '#3411: Figures off = no menu point, the others stay ' + await ev(side));
    await nav(B + '#office/kpi');
    check(await ready(ev, `typeof OFC === 'object' && !!OFC.info && !!document.querySelector('.office[data-ofctab]') && document.querySelector('.office').dataset.ofctab !== 'kpi'`, 80),
      '#3411: a link to the figures opens another page ' + await ev(`document.querySelector('.office')?.dataset.ofctab`));
    await nav(B + '#office/settings');
    await ready(ev, `!!document.querySelector('#ofc-set [data-ostsub="functions"]')`, 80);
    await click(ev, '#ofc-set [data-ostsub="functions"]');
    await ready(ev, `!!document.querySelector('#ofc-set [data-feat="money.kpi"]')`, 20);
    check(await ev(`document.querySelector('#ofc-set [data-feat="money.kpi"]').checked === false`), '#3411: the switch shows off');
    await click(ev, '#ofc-set [data-feat="money.kpi"]');
    check(await ready(ev, `!!document.querySelector('#side [data-ofm="kpi"]')`, 40), '#3411: on again = the point is back');

    // ================= #3381 the chat keeps its place (phone page and computer panel)
    for (const [phone, vw, vh] of [[true, 390, 844], [false, 1280, 800]]) {
      const tag = phone ? 'phone' : 'computer';
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
      await signIn(ev, nav, 'frida');
      // phone: the chat page and back (#today, a hash change); computer: the side panel closed and opened again
      await nav(B + '?v=' + vw + '#today'); await ready(ev, `!!document.querySelector('#top h1')`, 60);
      const open = async () => {
        if (phone) await ev(`(() => { go('agents/${AG}'); return 1; })()`); else await ev(`(() => { chatOpen(${AG}); return 1; })()`);
        return ready(ev, `document.querySelectorAll('#chat-msgs .cmsg').length >= 20`, 60);
      };
      const away = async () => {
        if (phone) { await ev(`(() => { go('today'); return 1; })()`); await ready(ev, `!document.querySelector('#chat-msgs')`, 20); }
        else { await click(ev, '[data-act="chat-close"]'); await ready(ev, `document.querySelector('#achat')?.classList.contains('hidden')`, 20); }
      };
      const ST = `(() => { const b = document.querySelector('#chat-msgs'); if (!b) return {}; const u = b.querySelector('.chunread'), br = b.getBoundingClientRect();
        return {gap: Math.round(b.scrollHeight - b.scrollTop - b.clientHeight), top: Math.round(b.scrollTop), line: !!u, lineAt: u ? Math.round(u.getBoundingClientRect().top - br.top) : null,
          lineNext: u?.nextElementSibling?.dataset.mid || '', pill: !document.querySelector('#chat-new').classList.contains('hidden'), n: b.querySelectorAll('.cmsg').length}; })()`;
      check(await open(), `${tag}: the chat`);
      await sleep(400);
      let s = await ev(ST);
      check(s.gap <= 2 && !s.line, `${tag}: first open at the newest message ${JSON.stringify(s)}`);
      // scrolled up, away and back: the same place
      await ev(`(() => { const b = document.querySelector('#chat-msgs'); b.scrollTop = 150; b.dispatchEvent(new Event('scroll')); return 1; })()`);
      await ready(ev, `JSON.parse(localStorage.getItem('tasks.chatSeen') || '{}')['${AG}']?.top === 150`, 20);
      await away(); await open(); await sleep(300);
      s = await ev(ST);
      check(Math.abs(s.top - 150) <= 2 && !s.line && !s.pill, `${tag}: #3381 away and back, nothing new: the place kept (150) ${JSON.stringify(s)}`);
      // at the bottom, away and back without anything new: the bottom
      await ev(`(() => { const b = document.querySelector('#chat-msgs'); b.scrollTop = b.scrollHeight; b.dispatchEvent(new Event('scroll')); return 1; })()`);
      await ready(ev, `JSON.parse(localStorage.getItem('tasks.chatSeen') || '{}')['${AG}']?.bot === true`, 20);
      await away(); await open(); await sleep(300);
      s = await ev(ST);
      check(s.gap <= 2 && !s.line, `${tag}: #3381 was at the bottom, nothing new: at the bottom ${JSON.stringify(s)}`);
      // the tab hidden (another app) while two answers come: back = at the first new one with the line + the button
      await ev(`(() => { Object.defineProperty(document, 'hidden', {configurable: true, get: () => true}); document.dispatchEvent(new Event('visibilitychange')); return 1; })()`);
      // more than a screen of new answers (a long one would fold), so the first new one can sit on top
      const a1 = await say(`Away answer one ${tag}\n\nwith a second paragraph`);
      let a2; for (let k = 2; k <= 9; k++) a2 = await say(`Away answer ${k} ${tag}\n\nsecond paragraph\n\nthird paragraph\n\nfourth paragraph`);
      await ev(`chatLoad().then(() => 1)`);
      await ready(ev, `!!document.querySelector('#chat-msgs [data-mid="a:${a2.id}"]')`, 40);
      await ev(`(() => { delete document.hidden; document.dispatchEvent(new Event('visibilitychange')); return 1; })()`);
      check(await ready(ev, `!!document.querySelector('#chat-msgs .chunread')`, 40), `${tag}: #3381 back: the line "New messages"`);
      await sleep(400);
      s = await ev(ST);
      check(s.line && s.lineNext === 'a:' + a1.id && s.lineAt !== null && s.lineAt >= -2 && s.lineAt < 60 && s.gap > 2 && s.pill,
        `${tag}: #3381 opens at the first new answer (line on top, "New message ↓", not the bottom) ${JSON.stringify(s)}`);
      await shot(`p2380rf-unread-${tag}.png`);
      // another page while the agent answers, scrolled up: back at the first new one
      await ev(`(() => { const b = document.querySelector('#chat-msgs'); b.scrollTop = b.scrollHeight; b.dispatchEvent(new Event('scroll')); return 1; })()`);
      await ready(ev, `JSON.parse(localStorage.getItem('tasks.chatSeen') || '{}')['${AG}']?.id >= ${a2.id}`, 20);
      await away();
      const a3 = await say(`While on another page ${tag}`);
      await open(); await ready(ev, `!!document.querySelector('#chat-msgs [data-mid="a:${a3.id}"]')`, 40); await sleep(400);
      s = await ev(ST);
      check(s.line && s.lineNext === 'a:' + a3.id, `${tag}: #3381 another page meanwhile: the line above the new answer ${JSON.stringify(s)}`);
      // own sending: the bottom, the line gone
      await ev(`(() => { const t = document.querySelector('#chat-in'); t.value = 'Thanks ${tag}'; t.dispatchEvent(new Event('input', {bubbles: true})); document.querySelector('[data-act="chat-send"]').click(); return 1; })()`);
      check(await ready(ev, `(() => { const b = document.querySelector('#chat-msgs'); return !b.querySelector('.chunread') && b.scrollHeight - b.scrollTop - b.clientHeight <= 3; })()`, 40),
        `${tag}: #3381 own message: at the bottom, line gone ${JSON.stringify(await ev(ST))}`);
    }

    // ================= #3436 subtasks by dragging in the task view (computer, mouse)
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await signIn(ev, nav, 'frida');
    await nav(B + '#l/' + P);
    await ready(ev, `S.tasks?.has(${PT})`, 60);
    await ev(`(() => { openDetail(${PT}); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('#detail .subs .trow[data-id]').length === 3`, 40), '#3436: the task view with its three subtasks');
    const drag = (from, to, after) => ev(`(() => { const f = document.querySelector('#detail .subs .trow[data-id="${from}"]'), t = document.querySelector('#detail .subs .trow[data-id="${to}"]');
      if (!f || !t) return 'missing'; const dt = new DataTransfer(); f.dispatchEvent(new DragEvent('dragstart', {bubbles: true, cancelable: true, dataTransfer: dt}));
      const r = t.getBoundingClientRect(), o = {bubbles: true, cancelable: true, clientX: r.left + 30, clientY: ${after} ? r.bottom - 3 : r.top + 3, dataTransfer: dt};
      const over = new DragEvent('dragover', o); t.dispatchEvent(over); const mark = t.classList.contains(${after} ? 'dropafter' : 'dropbefore') && over.defaultPrevented;
      t.dispatchEvent(new DragEvent('drop', o)); f.dispatchEvent(new DragEvent('dragend', {bubbles: true, dataTransfer: dt})); return mark; })()`);
    const s0 = await sortOf();
    check(await drag(SC, SA, false) === true, '#3436: dragged over Sub A: the line before it');
    const moved = async f => { for (let i = 0; i < 40; i++) { const x = await sortOf(); if (f(x)) return x; await sleep(250); } return sortOf(); };
    let so = await moved(x => x.c < x.a);
    check(so.c < so.a && so.a === s0.a && so.b === s0.b, '#3436: Sub C saved before Sub A, the others unchanged ' + JSON.stringify({s0, so}));
    check(await ready(ev, `[...document.querySelectorAll('#detail .subs .trow[data-id]')].map(r => +r.dataset.id)[0] === ${SC}`, 20), '#3436: the view shows Sub C first');
    // after Sub A: the completed Sub B is no neighbour (one step beyond Sub A)
    check(await drag(SC, SA, true) === true, '#3436: the lower half of Sub A: the line after it');
    so = await moved(x => x.c > x.a);
    check(so.c > so.a, '#3436: Sub C after Sub A ' + JSON.stringify(so));
    check(await ev(`!document.querySelector('#detail .dropbefore, #detail .dropafter')`), '#3436: no line left behind');
    await shot('p2380rf-subs.png');

    // ================= #3435 sections fold, one setting for all tasks
    const sec = `document.querySelector('#detail [data-dfold="subtasks"]')`;
    check(await ready(ev, `!!${sec} && !${sec}.classList.contains('dfolded') && !!${sec}.querySelector('.dfbtn[aria-expanded="true"]')`, 20), '#3435: the subtasks have the fold button, open');
    check(await ev(`!document.querySelector('#detail .dmd [data-dfold], #detail #d-md[data-dfold]')`), '#3435: the description does not fold');
    await click(ev, '#detail [data-dfold="subtasks"] .dfbtn');
    check(await ready(ev, `${sec}?.classList.contains('dfolded') && !document.querySelector('#detail .subs')?.offsetHeight && /2 open/.test(${sec}.querySelector('.dfsum')?.textContent || '')`, 20),
      '#3435: folded: the rows gone, the head says "2 open" ' + await ev(`${sec}?.querySelector('h5')?.textContent`));
    const srvFold = async f => { for (let i = 0; i < 40; i++) { const v = (await call(CF, 'GET', '/api/state')).settings?.detail_fold; if (f(v || '')) return v; await sleep(250); } return null; };
    check((await srvFold(v => v.split(',').includes('subtasks'))) !== null, '#3435: saved at the account');
    await shot('p2380rf-folded.png');
    await nav(B + 'static/icon.svg'); await nav(B + '#l/' + P);
    await ready(ev, `S.tasks?.has(${PT2})`, 60);
    await ev(`(() => { openDetail(${PT2}); return 1; })()`);
    check(await ready(ev, `${sec}?.classList.contains('dfolded') && /1 open/.test(${sec}.querySelector('.dfsum')?.textContent || '')`, 40), '#3435: another task after reloading: folded too ("1 open")');
    await click(ev, '#detail .dtop [data-act="task-menu"]');
    const item = `[...document.querySelectorAll('button, [role="menuitem"]')].find(b => /Unfold all sections/.test(b.textContent))`;
    check(await ready(ev, `!!${item}`, 20), '#3435: "Unfold all sections" in the task\'s menu');
    await ev(`(() => { ${item}?.click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('#detail .dfolded')`, 20) && (await srvFold(v => v === '')) !== null, '#3435: everything open again, saved');
  }, false);

  console.log(`p2380r_f_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
