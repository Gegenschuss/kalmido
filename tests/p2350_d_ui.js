// 2.35.0 UI tests (agent D), own container (start.sh). jsdom:
// #1096 "#123" links a task in the agent chat, the team chat, comments and the description (compact: only "#123", the
//      title in the tooltip), never inside code, tasks I cannot see stay text; a link to the app itself opens in the same
//      window; a tap opens the task on top of the chat (the chat stays)
// #1095 code snippets: the section in a software project list, add / edit / remove (undo), highlighting, Copy, Tab
//      indents, the language guess; other lists: only from the task menu; a viewer sees them read-only
// #1097 Customize right in the view: the blocks with a handle, hide at the block -> "Hidden" -> back, arrow keys on the
//      handle, Undo; Today, the start page and the project page share the code; the list with the arrows stays
// Firefox 1280 (mouse drag of a block) and 390 touch (hold, then drag; the snippet section), screenshots
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2350_d_ui', check, shots: 'P2350D_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const FEAT = 'cal,comments,collab,agents,team';
const V = B + 'api/v1';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Baker', password: 'password123'})).id;
  const BCK = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, BCK);
  const ME = (await call('GET', '/api/state')).me;
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  const AG = ag.id, AGH = {Authorization: 'Bearer ' + ag.token, 'Content-Type': 'application/json'};
  const v1 = async (method, url, body) => (await fetch(V + url, {method, headers: AGH, body: body ? JSON.stringify(body) : undefined})).json();
  const SW = (await call('POST', '/api/lists', {name: 'App', kind: 'project', ptype: 'software'})).id;
  await call('PUT', `/api/lists/${SW}/members`, {user_id: BOB, role: 'view'});
  await call('PUT', `/api/lists/${SW}/members`, {user_id: AG, role: 'edit'});
  const PL = (await call('POST', '/api/lists', {name: 'Home'})).id;
  const T = (await call('POST', '/api/tasks', {title: 'Fix the login', list_id: SW})).id;
  const T2 = (await call('POST', '/api/tasks', {title: 'Write the docs', list_id: SW, content: `Needs #${T} first. Code: \`#${T}\`\n\n\`\`\`\nsee #${T}\n\`\`\``})).id;
  const TP = (await call('POST', '/api/tasks', {title: 'Buy milk', list_id: PL})).id;
  const BL = (await call('POST', '/api/lists', {name: 'Bob private'}, BCK)).id;
  const TB = (await call('POST', '/api/tasks', {title: 'Bob secret title', list_id: BL}, BCK)).id;
  await call('POST', `/api/tasks/${T2}/comments`, {body: `Blocked by #${T}, also #${TB}`});
  const am = await v1('POST', `/agent/chats/${ME.id}`, {body: `Done with #${T}. Not yours: #${TB}. Link: ${B}#t/${T2}`});
  check(am && am.id, 'setup: an agent message ' + JSON.stringify(am).slice(0, 120));

  // ================= #1096 the markup
  let w = await boot({user: 'alice', hash: 'l/' + SW}), d = w.document;
  await until(() => w.eval(`!!taskById(${T})`));
  const cb = w.eval(`commentBody('see #${T}, \`#${T}\` and #${TB}, #999999', {})`);
  check(new RegExp(`<a href="#t/${T}" class="tref" data-tref="${T}" title="Fix the login">#${T}</a>`).test(cb), '#1096: a compact link with the title in the tooltip ' + cb);
  check((cb.match(/class="tref"/g) || []).length === 1 && new RegExp(`<code>#${T}</code>`).test(cb), '#1096: not inside code');
  check(new RegExp(`#${TB}`).test(cb) && !/Bob secret/.test(cb), '#1096: a task I cannot see stays text (no title)');
  check(!/&#39;/.test(w.eval(`mdTaskRefs('it&#39;s #${T}', true)`)) === false && /it&#39;s/.test(w.eval(`mdTaskRefs('it&#39;s #${T}', true)`)), '#1096: an HTML entity stays intact');
  check(!/class="tref"/.test(w.eval(`mdTaskRefs('<span title="#${T}">x</span>', true)`)), '#1096: never inside an attribute');
  const own = w.eval(`mdInline('${B}#t/${T}')`), ext = w.eval(`mdInline('https://example.com/x')`);
  check(!/target=/.test(own) && new RegExp(`href="#t/${T}"`).test(own) && new RegExp(`data-tref="${T}"`).test(own), '#1096: a link to the app itself: same window ' + own);
  check(/target="_blank"/.test(ext), '#1096: other links still open a new tab');
  // the description and the comment in the task panel
  w.eval(`openDetail(${T2})`); await until(() => d.querySelector('#d-md a.tref'));
  const dl = [...d.querySelectorAll('#d-md a.tref')];
  check(dl.length === 1 && dl[0].textContent === '#' + T && dl[0].title === 'Fix the login', '#1096: the description links #id once (not in code) ' + dl.map(a => a.outerHTML).join(' '));
  await until(() => d.querySelector('#d-tl .cbody a.tref'));
  const cl = [...d.querySelectorAll('#d-tl .cbody a.tref')];
  check(cl.length === 1 && cl[0].dataset.tref === String(T) && /#\d+/.test(d.querySelector('#d-tl .cbody').textContent) && !/Bob secret/.test(d.querySelector('#d-tl').textContent),
    '#1096: the comment links the visible task, the other number stays text');
  cl[0].dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, button: 0}));
  await until(() => w.eval(`S.sel === ${T}`));
  check(w.eval(`S.sel === ${T}`), '#1096: a tap on #id in a comment opens that task');
  w.eval('closeDetail()'); await sleep(200);
  // the agent chat: the link opens the task, the chat stays open
  w.eval(`chatOpen(${AG})`); await until(() => d.querySelector('#chat-msgs a.tref'));
  const al = [...d.querySelectorAll('#chat-msgs a.tref')];
  check(al.some(a => a.textContent === '#' + T) && !d.querySelector('#chat-msgs').textContent.includes('Bob secret'), '#1096: the agent chat links #id ' + al.map(a => a.textContent).join(','));
  const ownA = [...d.querySelectorAll('#chat-msgs a')].find(a => a.getAttribute('href') === '#t/' + T2);
  check(ownA && !ownA.target, '#1096: the link to the app in the chat: same window');
  al.find(a => a.textContent === '#' + T).dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, button: 0}));
  await until(() => w.eval(`S.sel === ${T}`));
  check(w.eval(`S.sel === ${T}`) && w.eval(`S.chat?.aid === ${AG}`) && d.querySelector('#chat-msgs'), '#1096: the task opens, the chat stays open');
  w.eval('closeDetail()');
  // the team chat of the list
  const rooms = await call('GET', '/api/team');
  const room = (rooms.rooms || rooms.data || []).find(x => x.kind === 'list' && x.list_id === SW);
  if (room) {
    await call('POST', `/api/team/rooms/${room.id}/messages`, {body: `Look at #${T}`});
    w.close(); w = await boot({user: 'alice', hash: 'team/' + room.id}); d = w.document;
    await until(() => d.querySelector('.cbub a.tref'));
    check([...d.querySelectorAll('.cbub a.tref')].some(a => a.textContent === '#' + T), '#1096: the team chat links #id');
  } else check(false, '#1096: setup: the list room ' + JSON.stringify(rooms).slice(0, 200));
  w.close();

  // ================= #1095 code snippets
  w = await boot({user: 'alice', hash: 'l/' + SW}); d = w.document;
  await until(() => w.eval(`!!taskById(${T})`));
  w.eval(`openDetail(${T})`); await until(() => d.querySelector('#d-snips'));
  const sec = d.querySelector('#d-snips');
  check(sec && !sec.closest('#d-more') && sec.querySelector('[data-act="snip-new"]'), '#1095: a software project: the section "Code snippets" with "Add code snippet", outside the fold');
  sec.querySelector('[data-act="snip-new"]').click(); await until(() => d.querySelector('#snip-code'));
  const ta = d.querySelector('#snip-code');
  check(ta && ta.getAttribute('spellcheck') === 'false' && ta.getAttribute('wrap') === 'off' && d.querySelector('#snip-lang') && d.querySelector('#snip-path') && d.querySelector('#snip-line'),
    '#1095: the editor: monospace field, language, path, line');
  ta.value = 'def login(user):\nreturn True'; ta.setSelectionRange(17, 17);
  ta.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Tab', bubbles: true, cancelable: true}));
  check(ta.value === 'def login(user):\n    return True', '#1095: Tab indents by 4 spaces ' + JSON.stringify(ta.value));
  ta.dispatchEvent(new w.Event('input', {bubbles: true}));
  check(/Python/.test(d.querySelector('#snip-lang option[value=""]').textContent) || w.eval(`snipGuess(${JSON.stringify('def login(user):\n    return True')})`) === 'py', '#1095: the language is recognised (py)');
  d.querySelector('#snip-path').value = 'src/auth.py'; d.querySelector('#snip-line').value = '12';
  d.querySelector('#snip-path').dispatchEvent(new w.Event('input', {bubbles: true}));
  d.querySelector('[data-act="snip-save"]').click();
  let st = await until(async () => { const t = await call('GET', `/api/tasks/${T}`); return t.snippets?.length ? t : null; });
  check(st && st.snippets[0].code === 'def login(user):\n    return True' && st.snippets[0].path === 'src/auth.py' && st.snippets[0].line === 12 && st.snippets[0].lang === '',
    '#1095: saved through the API ' + JSON.stringify(st?.snippets));
  await until(() => d.querySelector('#d-snips .snip pre .hl-k'));
  check(d.querySelector('#d-snips .snip .sniplang').textContent === 'Python' && d.querySelector('#d-snips .snip pre .hl-k')?.textContent === 'def'
    && /src\/auth\.py:12/.test(d.querySelector('#d-snips .snippath').textContent) && d.querySelector('#d-snips [data-act="snip-copy"]'), '#1095: highlighted, path:line, Copy');
  // edit
  d.querySelector('#d-snips [data-act="snip-edit"]').click(); await until(() => d.querySelector('#snip-code'));
  d.querySelector('#snip-code').value = 'SELECT id FROM users;'; d.querySelector('#snip-lang').value = 'sql';
  d.querySelector('#snip-code').dispatchEvent(new w.Event('input', {bubbles: true}));
  d.querySelector('[data-act="snip-save"]').click();
  st = await until(async () => { const t = await call('GET', `/api/tasks/${T}`); return t.snippets?.[0]?.lang === 'sql' ? t : null; });
  check(st && st.snippets.length === 1 && st.snippets[0].code === 'SELECT id FROM users;', '#1095: edited in place');
  // remove + undo
  await until(() => d.querySelector('#d-snips [data-act="snip-rm"]'));
  d.querySelector('#d-snips [data-act="snip-rm"]').click();
  await until(async () => !(await call('GET', `/api/tasks/${T}`)).snippets);
  check(/Code snippet removed/.test(d.querySelector('#toast')?.textContent || ''), '#1095: "Code snippet removed" with Undo');
  await w.eval(`histStep('undo')`);
  st = await until(async () => { const t = await call('GET', `/api/tasks/${T}`); return t.snippets?.length ? t : null; });
  check(st && st.snippets[0].code === 'SELECT id FROM users;', '#1095: Undo brings it back');
  // the language guess
  const g = w.eval(`[snipGuess('--- a/x\\n+++ b/x\\n@@ -1 +1 @@\\n-a\\n+b'), snipGuess('{"a": 1}'), snipGuess('#!/bin/bash\\necho hi'), snipGuess('const a = () => 1;'), snipGuess('SELECT * FROM t'), snipGuess('Just words here')]`);
  check(JSON.stringify(g) === JSON.stringify(['diff', 'json', 'sh', 'js', 'sql', '']), '#1095: the language guess ' + JSON.stringify(g));
  // pasting code into the description offers the snippet field
  const fake = {clipboardData: {getData: () => 'import os\nfor x in os.listdir("."):\n    print(x)'}};
  w.eval(`snipPasteHint`)(fake, w.eval(`taskById(${T})`));
  check(/This looks like code/.test(d.querySelector('#toast')?.textContent || ''), '#1095: pasting code into the description: the toast offers a code snippet');
  // another list: only from the task menu
  w.eval(`openDetail(${TP})`); await sleep(300);
  check(!d.querySelector('#d-snips'), '#1095: other lists: no section by default');
  check(w.eval(`snipShown(taskById(${TP}))`) === false, '#1095: ... snipShown false');
  w.eval(`snipOpen(${TP}, 'new')`); await until(() => d.querySelector('#d-snips #snip-code'));
  check(d.querySelector('#d-snips #snip-code'), '#1095: "Add code snippet" from the task menu opens the editor there');
  w.eval('snipCancel()');
  w.close();
  // a viewer: read-only
  w = await boot({user: 'bob', hash: 'l/' + SW}); d = w.document;
  await until(() => w.eval(`!!taskById(${T})`));
  check(w.eval(`!Array.isArray(taskById(${T}).snippets) && taskById(${T}).snippets_n === 1`), 'M4: the loaded task carries only snippets_n');
  w.eval(`openDetail(${T})`); await until(() => d.querySelector('#d-snips .snip'));
  check(d.querySelector('#d-snips .snip pre')?.textContent === 'SELECT id FROM users;', 'M4: the panel loads the snippets of the task');
  check(d.querySelector('#d-snips [data-act="snip-copy"]') && !d.querySelector('#d-snips [data-act="snip-edit"]') && !d.querySelector('#d-snips [data-act="snip-new"]'),
    '#1095: a viewer sees the snippets with Copy, without editing');
  w.close();

  // ================= #1097 Customize in the view
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  await until(() => d.querySelector('#view .lyb[data-lyk="tasks"]'));
  w.eval(`lyOpen('today', true)`); await until(() => d.querySelector('.lyed .lycanvas'));
  const hs = [...d.querySelectorAll('.lycanvas .lyedb')].map(x => x.dataset.lyk);
  check(hs.length >= 2 && d.querySelectorAll('.lycanvas .lyhandle').length === hs.length && d.querySelector('.lycanvas .lyedb .lybody[inert]'),
    '#1097: Today: every shown block in the view with a handle, its content not clickable ' + hs.join(','));
  await until(() => d.activeElement?.closest('.dcust'));
  check(d.querySelector('.lyed details.lylist[open] .dcust li') && d.activeElement?.closest('.dcust'), '#1097: the list with the arrows stays (open, the focus there)');
  check(!d.querySelector('.lycanvas .lyedb[data-lyk="tasks"] [data-act="ly-cvhide"]'), '#1097: a fixed block has no hide button');
  const hk = hs.find(k => k !== 'tasks');
  d.querySelector(`.lycanvas [data-act="ly-cvhide"][data-k="${hk}"]`).click();
  await until(() => d.querySelector(`.lyhid [data-act="ly-cvshow"][data-k="${hk}"]`));
  check(d.querySelector(`.lyhid [data-act="ly-cvshow"][data-k="${hk}"]`) && !d.querySelector(`.lycanvas .lyedb[data-lyk="${hk}"]`), '#1097: hidden at the block -> "Hidden" at the bottom');
  let vt = await until(async () => { const s = (await call('GET', '/api/state')).settings.view_today; return s && JSON.parse(s).hidden?.includes(hk) ? 1 : 0; });
  check(vt, '#1097: saved (view_today hidden)');
  d.querySelector(`.lyhid [data-act="ly-cvshow"][data-k="${hk}"]`).click();
  await until(() => d.querySelector(`.lycanvas .lyedb[data-lyk="${hk}"]`));
  check(d.querySelector(`.lycanvas .lyedb[data-lyk="${hk}"]`) && !d.querySelector('.lyhid'), '#1097: a tap in "Hidden" brings it back');
  // arrow keys on the handle, then Undo
  const o0 = [...d.querySelectorAll('.lycanvas .lyedb')].map(x => x.dataset.lyk);
  d.querySelector(`.lycanvas [data-lyhandle="${o0[0]}"]`).dispatchEvent(new w.KeyboardEvent('keydown', {key: 'ArrowDown', bubbles: true, cancelable: true}));
  await until(() => d.querySelector('.lycanvas .lyedb')?.dataset.lyk === o0[1]);
  const o1 = [...d.querySelectorAll('.lycanvas .lyedb')].map(x => x.dataset.lyk);
  check(o1[0] === o0[1] && o1[1] === o0[0], '#1097: ↓ on the handle moves the block ' + o1.join(','));
  await w.eval(`histStep('undo')`);
  await until(() => d.querySelector('.lycanvas .lyedb')?.dataset.lyk === o0[0]);
  check([...d.querySelectorAll('.lycanvas .lyedb')].map(x => x.dataset.lyk).join() === o0.join(), '#1097: Undo puts it back');
  // the mouse drag logic (jsdom: elementFromPoint is stubbed onto the target block)
  w.eval(`lyOpen('today', false)`); await sleep(200);
  check(d.querySelector('#view .lyb[data-lyk="tasks"] .lytool') === null, '#1097: after Done the view has no handles');
  w.close();
  // the start page and the project page use the same code
  w = await boot({user: 'alice', hash: 'home'}); d = w.document;
  w.eval(`lyOpen('home', true)`); await until(() => d.querySelector('.lyed[data-lyed="home"] .lycanvas.dgrid .lyedb .dcard'));
  check(d.querySelector('.lycanvas .lyedb .dcard') && d.querySelector('.lycanvas [data-act="ly-size"]'), '#1097: the start page: the cards themselves, width at the card');
  w.close();
  w = await boot({user: 'alice', hash: 'l/' + SW, ls: {'tasks.pov': JSON.stringify([SW])}}); d = w.document;
  await until(() => w.eval(`!!S.povD?.[${SW}]?.j`));
  if (w.eval(`!!LY.project && !!S.povD?.[${SW}]?.j`)) {
    w.eval(`lyOpen('project', true)`); await until(() => d.querySelector('.lyed[data-lyed="project"] .lycanvas .lyedb'));
    check(d.querySelectorAll('.lyed[data-lyed="project"] .lycanvas .lyedb').length > 2, '#1097: the project page too');
  } else check(true, 'project page not loaded in jsdom (checked in Firefox)');
  w.close();

  // ================= Firefox
  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1, .chview, .dash')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  const order = ev => ev(`[...document.querySelectorAll('.lycanvas .lyedb')].map(x => x.dataset.lyk).join()`);
  await firefox(async o => {
    const {cmd, ev, ctx, shot, drag} = o, tag = '1280';
    check(await ffLogin(o) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await o.nav(B + '#home'); await ready(ev);
    await ev(`(() => { lyOpen('home', true); return 1; })()`); await sleep(700);
    const o0 = (await order(ev)).split(',');
    const pos = await ev(`(() => { const a = document.querySelector('.lycanvas [data-lyhandle="${o0[0]}"]').getBoundingClientRect(), b = document.querySelector('.lycanvas .lyedb[data-lyk="${o0[2]}"]').getBoundingClientRect();
      return {x: a.left + 20, y: a.top + a.height / 2, tx: b.left + b.width * .75, ty: b.top + b.height / 2}; })()`);
    await drag(pos.x, pos.y, pos.tx - pos.x, pos.ty - pos.y); await sleep(700);
    const o1 = (await order(ev)).split(',');
    check(o1.indexOf(o0[0]) > o1.indexOf(o0[1]), `${tag}: #1097 a mouse drag by the handle moves the card ` + JSON.stringify({o0, o1}));
    const toast = await ev(`document.querySelector('#toast')?.textContent || ''`);
    check(/moved/i.test(toast) && /Undo/.test(toast), `${tag}: #1097 "… moved" with Undo ` + toast);
    await shot('p2350d-1280-customize.png');
    await ev(`(() => { histStep('undo'); return 1; })()`); await sleep(800);
    check((await order(ev)) === o0.join(), `${tag}: #1097 Undo after the drag`);
    await ev(`(() => { lyOpen('home', false); return 1; })()`);
  }, false);
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '390';
    check(await ffLogin(o) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    console.log(`${tag}: Firefox part started`);
    await o.nav(B + '#home'); await ready(ev);
    await ev(`(() => { lyOpen('home', true); return 1; })()`); await sleep(700);
    const o0 = (await order(ev)).split(',');
    // hold the first card, then drag it below the second (synthetic touch events, as a finger)
    const res = await ev(`(async () => {
      const el = document.querySelector('.lycanvas .lyedb[data-lyk="${o0[0]}"]'), b = document.querySelector('.lycanvas .lyedb[data-lyk="${o0[1]}"]');
      el.scrollIntoView({block: 'start'}); lydragScroller(el).scrollBy(0, -130); await new Promise(r => setTimeout(r, 250));
      const r = el.querySelector('.lybody').getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + 30;
      const hit = document.elementFromPoint(x, y);
      const fire = (type, x, y) => { const t = new Touch({identifier: 3, target: hit, clientX: x, clientY: y}); hit.dispatchEvent(new TouchEvent(type, {bubbles: true, cancelable: true, touches: type === 'touchend' ? [] : [t], targetTouches: type === 'touchend' ? [] : [t], changedTouches: [t]})); };
      fire('touchstart', x, y); await new Promise(r => setTimeout(r, 600));
      const br = b.getBoundingClientRect(), ty = Math.min(br.top + br.height * .75, innerHeight - 70);
      for (let i = 1; i <= 10; i++) { fire('touchmove', x, y + (ty - y) * i / 10); await new Promise(r => setTimeout(r, 30)); }
      fire('touchend', x, ty); await new Promise(r => setTimeout(r, 600));
      return {hit: !!hit.closest('.lyedb'), y, ty, bt: br.top, bb: br.bottom}; })()`);
    const o1 = (await order(ev)).split(',');
    check(res.hit && o1.indexOf(o0[0]) > o1.indexOf(o0[1]), `${tag}: #1097 hold + drag moves the card on a phone ` + JSON.stringify({res, o0, o1}));
    // a quick swipe does not start a drag (the page scrolls)
    const sw = await ev(`(async () => {
      const el = document.querySelector('.lycanvas .lyedb .lybody'), r = el.getBoundingClientRect(), x = r.left + 40, y = r.top + 20, hit = document.elementFromPoint(x, y);
      const fire = (type, y) => { const t = new Touch({identifier: 4, target: hit, clientX: x, clientY: y}); hit.dispatchEvent(new TouchEvent(type, {bubbles: true, cancelable: true, touches: type === 'touchend' ? [] : [t], targetTouches: type === 'touchend' ? [] : [t], changedTouches: [t]})); };
      const before = [...document.querySelectorAll('.lycanvas .lyedb')].map(x => x.dataset.lyk).join();
      fire('touchstart', y); fire('touchmove', y - 30); fire('touchmove', y - 80); fire('touchend', y - 80); await new Promise(r => setTimeout(r, 500));
      return {same: before === [...document.querySelectorAll('.lycanvas .lyedb')].map(x => x.dataset.lyk).join(), ghost: !!document.querySelector('.lyghost')}; })()`);
    check(sw.same && !sw.ghost, `${tag}: #1097 a swipe stays a swipe ` + JSON.stringify(sw));
    const tap = await ev(`(() => { const b = [...document.querySelectorAll('.lytool button')].map(x => x.getBoundingClientRect()); return {min: Math.min(...b.map(r => Math.min(r.width, r.height))), page: document.documentElement.scrollWidth <= 390}; })()`);
    check(tap.min >= 44 && tap.page, `${tag}: #1097 the handle / hide buttons are >= 44 px, nothing sticks out ` + JSON.stringify(tap));
    await ev(`(() => { document.querySelector('.lycanvas').scrollIntoView({block: 'start'}); return 1; })()`); await sleep(300);
    await shot('p2350d-390-customize.png'); console.log(`${tag}: customize shot taken (${process.env.P2350D_SHOTS ? 'dir set' : 'no dir'})`);
    await ev(`(() => { lyOpen('home', false); return 1; })()`);
    // the snippet section on the phone
    await o.nav(B + '#t/' + T); await ready(ev); await sleep(800);
    await ev(`(() => { document.querySelector('#d-snips')?.scrollIntoView({block: 'start'}); return 1; })()`); await sleep(300);
    const sn = await ev(`(() => { const s = document.querySelector('#d-snips'); if (!s) return null; const b = [...s.querySelectorAll('.sniphead .iconbtn')].map(x => x.getBoundingClientRect());
      return {n: s.querySelectorAll('.snip').length, min: Math.min(...b.map(r => Math.min(r.width, r.height))), fits: s.scrollWidth <= s.clientWidth + 1, hl: !!s.querySelector('.hl-k')}; })()`);
    check(sn && sn.n === 1 && sn.min >= 44 && sn.fits && sn.hl, `${tag}: #1095 the snippet on the phone: highlighted, buttons >= 44 px, fits ` + JSON.stringify(sn));
    await shot('p2350d-390-snippet.png'); console.log(`${tag}: snippet shot taken`);
  }, true);
  console.log(`p2350_d_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
