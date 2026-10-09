// 2.32.0 UI tests, part C ("shorter ways on the phone"), own container (start.sh). Firefox, 390 x 844 touch:
// #1055 a long press on a row selects it (no menu); the bar: Move, Date, Complete, More; a tap on another row adds it;
//       More holds Edit / Select all / Delete; Move lists the lists; while selecting each row has a grip that drags it
// #1060 Settings on a phone: inside an area no strip of area tabs, a back arrow, the header names the area; sub-tabs keep
//       their width (flex: none) and scroll sideways; the agent card's "Send test" / "Edit" carry words
// #1071 a sideways swipe on the open task goes to the next / previous task of the list, "3 of n" shows; Back closes the task;
//       not from the screen edge, not on the comments
// #1074 typing in the comment box does not scroll the task panel: with the focus in the docked box the panel has no
//       scroll padding at the bottom, autosize() keeps the panel's scroll position
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2320_c_ui', check, shots: 'P2320_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const FEAT = 'cal,comments,collab,time,progress,agents,kanban,timeline,fields,family,team';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Baker', password: 'password123'})).id;
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  const L = (await call('POST', '/api/lists', {name: 'Long list', org_id: ORG})).id;
  const L2 = (await call('POST', '/api/lists', {name: 'Other list', org_id: ORG})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: BOB, role: 'edit'});
  const desc = Array.from({length: 14}, (_, i) => `Paragraph ${i + 1}: a long description so that the task panel scrolls far enough to see an effect.`).join('\n\n');
  const T = (await call('POST', '/api/tasks', {title: 'Long task with comments', list_id: L, content: desc})).id;
  for (let i = 1; i <= 20; i++) await call('POST', `/api/tasks/${T}/comments`, {body: `Comment ${i}: some text so that the history gets long. `.repeat(2)});
  for (let i = 1; i <= 8; i++) await call('POST', '/api/tasks', {title: `Task ${i}`, list_id: L});

  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  await firefox(async o => {
    const {cmd, ev, ctx, shot, nav} = o, tag = '390';
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    check(await ffLogin(o) === 200, tag + ': login');
    await nav(B + '#l/' + L); await ready(ev);
    const touch = acts => cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'f' + Math.random(), parameters: {pointerType: 'touch'}, actions: acts}]}).then(() => cmd('input.releaseActions', {context: ctx}));
    const hold = (x, y, ms) => touch([{type: 'pointerMove', x: Math.round(x), y: Math.round(y)}, {type: 'pointerDown', button: 0}, {type: 'pause', duration: ms}, {type: 'pointerUp', button: 0}]);
    const swipe = (x1, x2, y) => touch([{type: 'pointerMove', x: x1, y}, {type: 'pointerDown', button: 0}, {type: 'pointerMove', x: Math.round((x1 + x2) / 2), y, duration: 120}, {type: 'pointerMove', x: x2, y, duration: 120}, {type: 'pointerUp', button: 0}]);
    const rowAt = i => ev(`(() => { const r = [...document.querySelectorAll('#view .trow .tmain')][${i}].getBoundingClientRect(); return {x: r.left + 40, y: r.top + r.height / 2}; })()`);

    // ================= #1055 long press = select, the bar
    let p = await rowAt(1); await hold(p.x, p.y, 700); await sleep(500);
    const s1 = await ev(`(() => { const b = document.querySelector('#mbar'), r = b.getBoundingClientRect(); return {m: S.multiMode, n: S.multi.size, pop: !!document.querySelector('#pop:not(.hidden) [role="menuitem"]'), in: r.left >= 0 && r.right <= innerWidth + .5, lab: [...b.querySelectorAll('.mbb .mbl')].map(x => x.textContent).join('|'), grips: document.querySelectorAll('#view .trow .tgrip').length, gh: Math.round(document.querySelector('#view .trow .tgrip')?.getBoundingClientRect().height || 0)}; })()`);
    check(s1.m && s1.n === 1 && !s1.pop && s1.in && s1.lab === 'Move|Date|Complete|More', '#1055: a long press selects the row, the bar Move | Date | Complete | More ' + JSON.stringify(s1));
    check(s1.grips >= 8 && s1.gh >= 44, '#1055: while selecting every row has a grip (44 px) ' + JSON.stringify(s1));
    p = await rowAt(3); await hold(p.x, p.y, 60); await sleep(400);
    check(await ev(`S.multi.size === 2 && !S.sel`), '#1055: a tap on another row adds it (no task opens)');
    await shot('p2320c-390-select.png');
    await ev(`(() => { document.querySelector('#mbar [data-act="mb-menu"]').click(); return 1; })()`); await sleep(300);
    const more = await ev(`[...document.querySelectorAll('#pop [role="menuitem"]')].map(x => x.textContent).join('|')`);
    check(more === 'Edit|Select all|Delete', '#1055: More = Edit, Select all, Delete ' + more);
    await ev(`(() => { closePop(); document.querySelector('#mbar [data-act="mb-move"]').click(); return 1; })()`); await sleep(300);
    const ids2 = await ev(`JSON.stringify([...S.multi])`);
    const mv = await ev(`(() => { const b = [...document.querySelectorAll('#pop [role="menuitem"]')].find(x => x.textContent === 'Other list'); if (b) b.click(); return !!b; })()`); await sleep(1200);
    const moved = await Promise.all(JSON.parse(ids2).map(async id => (await call('GET', `/api/tasks/${id}`)).list_id));
    check(mv && moved.every(x => x === L2) && await ev(`!S.multiMode && !S.multi.size`), '#1055: Move > a list moves the selection there and ends it ' + JSON.stringify(moved));
    // the grip drags a row while selecting
    p = await rowAt(0); await hold(p.x, p.y, 700); await sleep(400);
    const g = await ev(`(() => { const gs = [...document.querySelectorAll('#view .trow .tgrip')]; const a = gs[1].getBoundingClientRect(), b = gs[4].getBoundingClientRect(); return {x: a.x + a.width / 2, y: a.y + a.height / 2, y2: b.y + b.height * .8, id: +gs[1].closest('.trow').dataset.id}; })()`);
    const before = await ev(`JSON.stringify([...document.querySelectorAll('#view .trow')].map(r => +r.dataset.id))`);
    await touch([{type: 'pointerMove', x: Math.round(g.x), y: Math.round(g.y)}, {type: 'pointerDown', button: 0}, {type: 'pause', duration: 60}, {type: 'pointerMove', x: Math.round(g.x), y: Math.round(g.y + 20), duration: 100}, {type: 'pointerMove', x: Math.round(g.x), y: Math.round(g.y2), duration: 300}, {type: 'pointerUp', button: 0}]);
    await sleep(1200);
    const after = await ev(`JSON.stringify([...document.querySelectorAll('#view .trow')].map(r => +r.dataset.id))`);
    check(JSON.parse(before).indexOf(g.id) < JSON.parse(after).indexOf(g.id), `#1055: the grip drags the row down ${before} -> ${after}`);
    await ev(`(() => { S.multi.clear(); S.multiMode = false; render(); return 1; })()`); await sleep(300);

    // ================= #1071 swipe to the next / previous task
    const order = JSON.parse(await ev(`JSON.stringify([...document.querySelectorAll('#view .trow')].map(r => +r.dataset.id))`));
    await ev(`(() => { openDetail(${order[1]}); return 1; })()`); await sleep(1000);
    const ty = await ev(`(() => { const r = document.querySelector('#d-title').getBoundingClientRect(); return Math.round(r.top + r.height / 2); })()`);
    await swipe(300, 90, ty); await sleep(300);
    const pos = await ev(`document.querySelector('#dswpos')?.textContent || ''`);
    await sleep(500);
    check(await ev('S.sel') === order[2] && pos === `3 of ${order.length}`, `#1071: a swipe to the left opens the next task, "3 of n" shows (${pos})`);
    await swipe(90, 300, ty); await sleep(800);
    check(await ev('S.sel') === order[1], '#1071: a swipe to the right goes back');
    await swipe(6, 250, ty); await sleep(800);
    check(await ev('S.sel') === order[1], '#1071: a swipe from the screen edge does nothing (the phone\'s Back)');
    await ev(`(() => { openDetail(${order[0]}); return 1; })()`); await sleep(800);
    await swipe(90, 300, ty); await sleep(800);
    check(await ev('S.sel') === order[0], '#1071: at the first task a swipe to the right springs back');
    await ev(`(() => { closeDetail(); return 1; })()`); await sleep(500);

    // ================= #1074 typing in the comment box keeps the panel where it is
    await ev(`(() => { openDetail(${T}); return 1; })()`); await sleep(1500);
    const k = await ev(`(async () => { const d = document.querySelector('#detail'), ta = document.querySelector('#c-input'); d.scrollTop = 400; await new Promise(r => setTimeout(r, 100));
      const pad0 = getComputedStyle(d).scrollPaddingBottom; ta.focus({preventScroll: true}); await new Promise(r => setTimeout(r, 100));
      const pad1 = getComputedStyle(d).scrollPaddingBottom, top0 = d.scrollTop, tops = [];
      for (const c of 'abcde\\nfg\\nh') { ta.value += c; ta.dispatchEvent(new Event('input', {bubbles: true})); await new Promise(r => setTimeout(r, 30)); tops.push(d.scrollTop); }
      ta.value = ''; ta.dispatchEvent(new Event('input', {bubbles: true})); ta.blur();
      const rule = [...document.styleSheets].some(x => { try { return [...x.cssRules].some(r => (r.selectorText || '').includes('#detail:has(.dbot :focus)') && r.style.scrollPaddingBottom === '0px'); } catch { return false; } });
      return {pad0, pad1, top0, tops, rule, foc: document.hasFocus()}; })()`);
    // a headless Firefox without window focus does not match :focus: then the rule itself is checked
    check(k.pad0 !== '0px' && (k.pad1 === '0px' || (!k.foc && k.rule)), '#1074: with the focus in the comment box the panel drops its bottom scroll padding ' + JSON.stringify(k));
    check(k.tops.every(x => x === k.top0), '#1074: typing (also new lines) does not move the panel ' + JSON.stringify(k));
    await ev(`(() => { closeDetail(); return 1; })()`); await sleep(500);

    // ================= #1060 Settings on the phone
    await ev(`(() => { settingsModal('ai'); return 1; })()`); await sleep(1500);
    const st = await ev(`(() => { const m = document.querySelector('.smodal'), n = m.querySelector('.snav'), sub = m.querySelector('.aisub'), bs = [...sub.querySelectorAll('button')];
      const lbl = s => { const b = m.querySelector('#s-ags [data-ag="' + s + '"] .aglbl'); return b ? getComputedStyle(b).display !== 'none' && b.textContent : ''; };
      return {nav: getComputedStyle(n).display, back: getComputedStyle(m.querySelector('.sback')).display, h: m.querySelector('.shdr h3').textContent,
        flex: getComputedStyle(bs[0]).flexGrow, sc: sub.scrollWidth > sub.clientWidth, ox: getComputedStyle(sub).overflowX, test: lbl('test'), edit: lbl('edit'), over: document.documentElement.scrollWidth <= 390}; })()`);
    check(st.nav === 'none' && st.back !== 'none' && st.h === 'Agents', '#1060: inside an area no area tabs, a back arrow, the header names the area ' + JSON.stringify(st));
    check(st.flex === '0' && st.sc && st.ox === 'auto' && st.over, '#1060: the sub-tabs keep their width and scroll sideways ' + JSON.stringify(st));
    check(st.test === 'Send test' && st.edit === 'Edit', '#1060: the agent card says "Send test" and "Edit" in words ' + JSON.stringify(st));
    await shot('p2320c-390-settings-agents.png');
    await ev(`(() => { document.querySelector('.smodal .sback').click(); return 1; })()`); await sleep(400);
    const ix = await ev(`(() => { const m = document.querySelector('.smodal'); return {idx: m.classList.contains('sidx'), h: m.querySelector('.shdr h3').textContent, nav: getComputedStyle(m.querySelector('.snav')).display}; })()`);
    check(ix.idx && ix.h === 'Settings' && ix.nav !== 'none', '#1060: back = the list of areas, header "Settings" ' + JSON.stringify(ix));
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
