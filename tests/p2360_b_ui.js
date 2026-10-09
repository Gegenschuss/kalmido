// 2.36.0 UI tests (agent B), own container (start.sh). jsdom:
// #1118 the lock: a task an agent created shows a small lock in its row and the pressed lock button in the task header;
//      title and description are read-only, Today / Tomorrow are gone; a click in the description, typing into the title,
//      the date and priority pickers, moving to another list and a direct write show the hint with "Unlock" and change
//      nothing; a checkbox in the description still ticks, a comment still posts, the task still completes; "Unlock"
//      in the hint unlocks it (history step "Unlocked …", undo locks again); a view-only member sees no lock button;
//      multi-select skips the locked task with a note; part 1: a click that selected text, a double click or a moved
//      pointer never opens the editor, a plain click does (after the double-click pause), clicks in code / tables /
//      links never
// #1110 the agent's suggestion buttons come after the time / reactions line; permission questions keep theirs inside
// Firefox 1280 x 800 (mouse): part 1 for real: dragging across the description selects text and keeps the view, a double
//      click selects a word and keeps the view, a plain click opens the editor
// Firefox 390 x 844 touch: screenshots of a locked task and of the suggestion under the reactions
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2360_b_ui', check, shots: 'P2360B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const FEAT = 'cal,comments,collab,agents';
const V = B + 'api/v1';
const NOTES = 'Intro text for the plan.\n\n- [ ] first step\n- [ ] second step\n\n```bash\nmake test\n```\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\nSee [the docs](https://example.com/docs).';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const CAROL = (await call('POST', '/api/users', {username: 'carol', display_name: 'Carol', password: 'password123'})).id;
  const CCK = await login('carol');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, CCK);
  const ME = (await call('GET', '/api/state')).me;
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  const AG = ag.id, AGH = {Authorization: 'Bearer ' + ag.token, 'Content-Type': 'application/json'};
  const L = (await call('POST', '/api/lists', {name: 'Team list'})).id;
  const L2 = (await call('POST', '/api/lists', {name: 'Elsewhere'})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: CAROL, role: 'view'});
  await call('PUT', `/api/lists/${L}/members`, {user_id: AG, role: 'edit'});
  const v1 = async (method, url, body) => { const x = await fetch(V + url, {method, headers: AGH, body: body ? JSON.stringify(body) : undefined}); return {...(await x.json().catch(() => ({}))), status: x.status}; };
  const T = (await v1('POST', '/tasks', {title: 'Release plan by the agent', list_id: L, notes: NOTES})).id;
  const O = (await call('POST', '/api/tasks', {title: 'My own task', list_id: L, content: 'Plain words to read and select.'})).id;
  const srv = async id => (await call('GET', `/api/tasks/${id}`));
  check((await srv(T)).locked === 1 && (await srv(O)).locked === 0, 'the agent task is locked, mine is open');

  // ================= jsdom: the locked task
  let w = await boot({hash: 'l/' + L}); let d = w.document;
  await until(() => d.querySelector(`#view .trow[data-id="${T}"]`));
  check(d.querySelector(`#view .trow[data-id="${T}"] .ttl .tlkr`) && !d.querySelector(`#view .trow[data-id="${O}"] .tlkr`), '#1118: a small lock in the row of the locked task only');
  w.eval(`openDetail(${T})`); await until(() => d.querySelector('#d-md'));
  const lb = d.querySelector('#detail [data-act="tlk-toggle"]');
  check(lb && lb.classList.contains('on') && lb.getAttribute('aria-pressed') === 'true' && /Locked/.test(lb.textContent), '#1118: the lock button in the header is pressed ' + (lb?.outerHTML || '').slice(0, 200));
  check(d.querySelector('#d-title').readOnly && d.querySelector('#d-content').readOnly && !d.querySelector('#detail .dq'), '#1118: title + description read-only, no Today / Tomorrow');
  const toastTxt = () => d.querySelector('#toast:not(.hidden)')?.textContent || '';
  const hideToast = () => d.querySelector('#toast')?.classList.add('hidden');
  const mdClick = (el, o = {}) => {  // a mouse click: press and release at the same spot (detail 1) unless o says otherwise
    const x = o.x ?? 10, y = o.y ?? 10;
    el.dispatchEvent(new w.MouseEvent('pointerdown', {bubbles: true, clientX: x, clientY: y}));
    el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, detail: o.detail ?? 1, clientX: o.x2 ?? x, clientY: o.y2 ?? y}));
  };
  hideToast();
  mdClick(d.querySelector('#d-md p') || d.querySelector('#d-md')); await sleep(500);
  check(d.querySelector('#d-content').classList.contains('hidden') && /locked/i.test(toastTxt()) && /Unlock/.test(toastTxt()), '#1118: a click in the locked description: the hint with Unlock, no editor ' + toastTxt());
  hideToast();
  d.querySelector('#d-title').dispatchEvent(new w.KeyboardEvent('keydown', {key: 'a', bubbles: true, cancelable: true}));
  check(/locked/i.test(toastTxt()), '#1118: typing into the title shows the hint');
  hideToast();
  w.eval(`datePop(document.querySelector('#detail [data-act="date"]'), ${T})`); await sleep(200);
  check(/locked/i.test(toastTxt()) && !d.querySelector('#pop:not(.hidden) .dpop, #pop:not(.hidden) .cal'), '#1118: the date picker does not open, the hint shows');
  hideToast();
  w.eval(`prioMenu(document.querySelector('#detail [data-act="prio"]'), ${T})`); await sleep(200);
  check(/locked/i.test(toastTxt()), '#1118: the priority menu: the hint');
  hideToast();
  await w.eval(`patchTask(${T}, {list_id: ${L2}}).catch(e => { window.__lk = e.locked; })`); await sleep(200);
  check(w.__lk === true && /locked/i.test(toastTxt()) && (await srv(T)).list_id === L, '#1118: a direct move is not sent');
  await w.eval(`patchTask(${T}, {pinned: 1}).catch(() => {})`); await sleep(300);
  check((await srv(T)).pinned === 1, '#1118: pinning stays free');
  // free: a checkbox, a comment, completing
  const cb = d.querySelector('#d-md input[data-mdline]');
  cb.click(); await sleep(300); await w.eval('flushSaves()'); await sleep(500);
  check(/- \[x\] first step/.test((await srv(T)).content), '#1118: a checkbox in the locked description ticks (saved) ' + (await srv(T)).content.slice(0, 80));
  const cm = await call('POST', `/api/tasks/${T}/comments`, {body: 'Fine by me'});
  check(cm.status === 201 || cm.status === 200, '#1118: a comment on the locked task');
  // multi-select: the locked one is skipped
  hideToast();
  await w.eval(`batch('patch', {priority: 5}, false, [${T}, ${O}])`); await sleep(600);
  check((await srv(T)).priority === 0 && (await srv(O)).priority === 5 && /1 locked task skipped/.test(toastTxt()), '#1118: multi-select skips the locked task with a note ' + toastTxt());
  // unlock from the hint
  w.eval(`openDetail(${T})`); await sleep(300); hideToast();
  w.eval(`tlkToast(taskById(${T}))`); await sleep(100);
  d.querySelector('#toast button')?.click();
  await until(async () => (await srv(T)).locked === 0);
  check((await srv(T)).locked === 0, '#1118: "Unlock" in the hint unlocks the task');
  await until(() => d.querySelector('#detail [data-act="tlk-toggle"]:not(.on)'));
  check(d.querySelector('#detail [data-act="tlk-toggle"]:not(.on)') && !d.querySelector('#d-title').readOnly, '#1118: unlocked: the button is no longer pressed, the title editable');
  check(/Unlocked/.test(w.eval('HIST.undo.at(-1)?.label || ""')), '#1118: the history step "Unlocked …" ' + w.eval('HIST.undo.at(-1)?.label || ""'));
  await w.eval(`histStep('undo')`); await until(async () => (await srv(T)).locked === 1);
  check((await srv(T)).locked === 1, '#1118: undo locks it again ' + toastTxt() + ' / ' + w.eval('HIST.undo.length + "/" + HIST.redo.length'));

  // ================= part 1: selecting never opens the editor (an open task)
  w.eval(`openDetail(${O})`); await until(() => d.querySelector('#d-md p'));
  const p = d.querySelector('#d-md p');
  hideToast();
  mdClick(p, {x: 10, y: 10, x2: 60, y2: 10}); await sleep(500);
  check(d.querySelector('#d-content').classList.contains('hidden'), 'part 1: a moved pointer (selecting) does not open the editor');
  mdClick(p, {detail: 2}); await sleep(500);
  check(d.querySelector('#d-content').classList.contains('hidden'), 'part 1: a double click does not open the editor');
  const rg = d.createRange(); rg.selectNodeContents(p); w.getSelection().removeAllRanges(); w.getSelection().addRange(rg);
  mdClick(p); await sleep(500);
  check(d.querySelector('#d-content').classList.contains('hidden'), 'part 1: a click that leaves text selected does not open the editor');
  w.getSelection().removeAllRanges();
  mdClick(p); mdClick(p, {detail: 2}); await sleep(500);
  check(d.querySelector('#d-content').classList.contains('hidden'), 'part 1: the first click of a double click waits and is dropped');
  mdClick(p); await sleep(100);
  check(d.querySelector('#d-content').classList.contains('hidden'), 'part 1: a plain click waits for a possible second click ...');
  await sleep(400);
  check(!d.querySelector('#d-content').classList.contains('hidden'), '... then opens the editor');
  w.eval(`S.editContent = false; openDetail(${T}); S.tasks.get(${T}).locked = 0; renderDetail()`); await until(() => d.querySelector('#d-md pre'));
  for (const sel of ['#d-md pre', '#d-md table td', '#d-md a']) {
    const el = d.querySelector(sel); if (!el) { check(false, 'part 1: no ' + sel); continue; }
    if (sel === '#d-md a') el.addEventListener('click', e => e.preventDefault(), {once: true});
    mdClick(el); await sleep(450);
    check(d.querySelector('#d-content').classList.contains('hidden'), 'part 1: a click in ' + sel + ' never opens the editor');
  }
  w.eval(`S.tasks.get(${T}).locked = 1; renderDetail()`);
  w.close();

  // ================= jsdom: a view-only member has no lock button
  w = await boot({user: 'carol', hash: 'l/' + L}); d = w.document;
  await until(() => d.querySelector(`#view .trow[data-id="${T}"]`));
  w.eval(`openDetail(${T})`); await until(() => d.querySelector('#d-title'));
  check(!d.querySelector('#detail [data-act="tlk-toggle"]') && d.querySelector(`#view .trow[data-id="${T}"] .tlkr`), '#1118: view only: no lock button, the row still shows the lock '
    + JSON.stringify({btn: !!d.querySelector('#detail [data-act="tlk-toggle"]'), row: !!d.querySelector(`#view .trow[data-id="${T}"]`), lk: w.eval(`taskById(${T})?.locked`), ro: w.eval(`canEdit(taskById(${T}))`)}));
  w.close();

  // ================= #1110: the suggestion after the time / reactions line
  const sg = await v1('POST', `/agent/chats/${ME.id}`, {body: 'The plan is ready.', choices: [{id: 'go', label: 'Start the build', style: 'primary'}]});
  const pq = await v1('POST', `/agent/chats/${ME.id}`, {body: 'May I run the tests?', permission: true});
  check(sg.status === 201 && pq.status === 201, '#1110: a suggestion and a permission question');
  w = await boot({hash: 'today'}); d = w.document;
  w.eval(`chatOpen(${AG})`);
  await until(() => d.querySelector(`#chat-msgs .cmsg[data-mid="a:${pq.id}"]`));
  await sleep(300);
  const ms = d.querySelector(`#chat-msgs .cmsg[data-mid="a:${sg.id}"]`), mp = d.querySelector(`#chat-msgs .cmsg[data-mid="a:${pq.id}"]`);
  // the newer permission question expires the older suggestion: check the suggestion on its own first (agent sends it last below)
  check(mp && mp.querySelector('.cchoices, .cperm') && mp.querySelector('.cmeta') && (mp.querySelector('.cchoices, .cperm').compareDocumentPosition(mp.querySelector('.cmeta')) & 4),
    '#1110: a permission question keeps its buttons above the time line');
  void ms;
  w.close();
  const sg2 = await v1('POST', `/agent/chats/${ME.id}`, {body: 'Next I would start the build.', choices: [{id: 'go', label: 'Start the build', style: 'primary'}]});
  w = await boot({hash: 'today'}); d = w.document;
  w.eval(`chatOpen(${AG})`);
  await until(() => d.querySelector(`#chat-msgs .cmsg[data-mid="a:${sg2.id}"] .cchoices`));
  const m2 = d.querySelector(`#chat-msgs .cmsg[data-mid="a:${sg2.id}"]`);
  check(m2 && m2.querySelector(':scope > .cmeta + .cchoices'), '#1110: the suggestion comes right after the time / reactions line ' + (m2 ? [...m2.children].map(c => c.className.split(' ')[0]).join(',') : ''));
  w.close();

  // ================= Firefox 1280 mouse: part 1 for real
  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); localStorage.setItem('tasks.chatFloat', '"0"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1, .chview, #chat-msgs')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  await call('PATCH', `/api/tasks/${O}`, {content: 'Plain words to read and select here.\n\nA second paragraph with more words.'});
  await firefox(async o => {
    const {cmd, ev, ctx, drag} = o;
    check(await ffLogin(o) === 200, '1280: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 800}});
    await o.nav(B + '#l/' + L); await ready(ev);
    await ev(`(() => { openDetail(${O}); return 1; })()`); await sleep(800);
    const pos = await ev(`(() => { const p = document.querySelector('#d-md p'); if (!p) return null; const r = p.getBoundingClientRect(); return {x: r.left + 4, y: r.top + r.height / 2, w: r.width}; })()`);
    check(!!pos, '1280: the description shows');
    if (pos) {
      await drag(pos.x, pos.y, Math.min(140, pos.w - 10), 0); await sleep(600);
      const s1 = await ev(`({sel: String(getSelection()).length, ed: !document.querySelector('#d-content').classList.contains('hidden')})`);
      check(s1.sel > 3 && !s1.ed, '1280: part 1: dragging selects text and keeps the view ' + JSON.stringify(s1));
      await ev(`(() => { getSelection().removeAllRanges(); return 1; })()`);
      const at = {type: 'pointerMove', x: Math.round(pos.x + 20), y: Math.round(pos.y)};
      await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'm', parameters: {pointerType: 'mouse'}, actions: [at, {type: 'pointerDown', button: 0}, {type: 'pointerUp', button: 0}, {type: 'pointerDown', button: 0}, {type: 'pointerUp', button: 0}]}]});
      await cmd('input.releaseActions', {context: ctx}); await sleep(700);
      const s2 = await ev(`({sel: String(getSelection()).trim().length, ed: !document.querySelector('#d-content').classList.contains('hidden')})`);
      check(s2.sel > 0 && !s2.ed, '1280: part 1: a double click selects a word and keeps the view ' + JSON.stringify(s2));
      await ev(`(() => { getSelection().removeAllRanges(); return 1; })()`);
      await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'm', parameters: {pointerType: 'mouse'}, actions: [at, {type: 'pointerDown', button: 0}, {type: 'pointerUp', button: 0}]}]});
      await cmd('input.releaseActions', {context: ctx}); await sleep(800);
      check(await ev(`!document.querySelector('#d-content').classList.contains('hidden')`), '1280: part 1: a plain click opens the editor');
    }
  }, false);

  // ================= Firefox 390 touch: screenshots
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o;
    check(await ffLogin(o) === 200, '390: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + '#l/' + L); await ready(ev);
    await ev(`(() => { openDetail(${T}); return 1; })()`); await sleep(1200);
    const g = await ev(`(() => { const b = document.querySelector('#detail [data-act="tlk-toggle"]'); if (!b) return null; const r = b.getBoundingClientRect(); return {w: Math.round(r.width), h: Math.round(r.height), on: b.classList.contains('on')}; })()`);
    check(g && g.on && g.w >= 24 && g.h >= 24, '390: the lock button is there, pressed, >= 24 px ' + JSON.stringify(g));
    await shot('p2360b-390-locked.png');
    await ev(`(() => { closeDetail(); return 1; })()`); await sleep(800);
    await shot('p2360b-390-row.png');
    await o.nav(B + '#agents/' + AG); await ready(ev); await sleep(1500);
    const sgp = await ev(`(() => { const m = [...document.querySelectorAll('#chat-msgs .cmsg.ag')].pop(); return m ? [...m.children].map(c => c.className.split(' ')[0]).join(',') : null; })()`);
    check(sgp && /cmeta,cchoices$/.test(sgp), '390: #1110 the suggestion is the last part of the message, after the time line ' + sgp);
    await shot('p2360b-390-suggestion.png');
  }, true);

  console.log(`p2360_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
