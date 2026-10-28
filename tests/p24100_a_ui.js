// kalmido-suite: fresh
// 2.410.0 A (#3514): a choice field marked "Ordered (stages)" shows a stage bar instead of the text, Firefox (desktop and
// 390 px phone width, screenshots with P24100A_SHOTS). A list with the field as a column: dots with the current stage as a
// ring and its name, the stages before it filled; a special state (red) on the stage that follows it in the options, in
// its signal colour; an empty field = grey dots, no name. A board card (pinned field): the bar. The task panel: the wide
// bar with a name under every stage and "since …" from the activity. On a phone the rows show only the dots. The field
// dialog has the switch and, per option, the kind (stage / special state).
// freelancer-matrix: lists  (frida has no organisation: the same field and bars)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p24100_a_ui', check, shots: 'P24100A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P24100A_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const SH = !!process.env.P24100A_SHOTS;
const OPTS = [{name: 'Planned'}, {name: 'Building'}, {name: 'Review'}, {name: 'Parked', special: 'red'}, {name: 'In main'}, {name: 'Live'}];

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {org_name: 'Example Org', lang: 'en', collab_all: true});
  await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const C = await login('frida');
  await call(C, 'PATCH', '/api/settings', {tour: 'done', lang: 'en', features: 'fields,kanban,collab,comments'});
  check(!((await call(C, 'GET', '/api/state')).me.workspaces || []).length, 'setup: frida has no organisation');
  const id = (f, n) => f.options.options.find(o => o.name === n).id;
  // a list with the field as a column
  const L = (await call(C, 'POST', '/api/lists', {name: 'Releases'})).id;
  const FL = await call(C, 'POST', `/api/lists/${L}/fields`, {name: 'Build', type: 'select', options: {stages: 1, options: OPTS}});
  await call(C, 'PATCH', `/api/lists/${L}`, {columns: ['due', 'f:' + FL.id]});
  const T1 = (await call(C, 'POST', '/api/tasks', {title: 'Logo size', list_id: L})).id;
  const T2 = (await call(C, 'POST', '/api/tasks', {title: 'Team chat', list_id: L})).id;
  const T3 = (await call(C, 'POST', '/api/tasks', {title: 'Not started yet', list_id: L})).id;
  await call(C, 'PATCH', `/api/tasks/${T1}`, {fields: {[FL.id]: id(FL, 'Building')}});
  await call(C, 'PATCH', `/api/tasks/${T1}`, {fields: {[FL.id]: id(FL, 'Review')}});
  await call(C, 'PATCH', `/api/tasks/${T2}`, {fields: {[FL.id]: id(FL, 'Parked')}});
  // a board with the field pinned to the cards
  const K = (await call(C, 'POST', '/api/lists', {name: 'Board'})).id;
  await call(C, 'PATCH', `/api/lists/${K}`, {view: 'kanban'});
  const FK = await call(C, 'POST', `/api/lists/${K}/fields`, {name: 'Step', type: 'select', pinned: true, options: {stages: 1, options: OPTS}});
  const T4 = (await call(C, 'POST', '/api/tasks', {title: 'Card task', list_id: K})).id;
  await call(C, 'PATCH', `/api/tasks/${T4}`, {fields: {[FK.id]: id(FK, 'Building')}});
  // a plain list with the field pinned (the rows on a phone)
  const P = (await call(C, 'POST', '/api/lists', {name: 'Phone list'})).id;
  const FP = await call(C, 'POST', `/api/lists/${P}/fields`, {name: 'Phase', type: 'select', pinned: true, options: {stages: 1, options: OPTS}});
  const T5 = (await call(C, 'POST', '/api/tasks', {title: 'Row task', list_id: P})).id;
  await call(C, 'PATCH', `/api/tasks/${T5}`, {fields: {[FP.id]: id(FP, 'In main')}});
  check(FL.id && FK.id && FP.id && T1 && T2 && T3 && T4 && T5 && FL.options.stages === 1, 'setup');
  const ready = async (ev, expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const bar = sel => `(() => { const b = document.querySelector(${JSON.stringify(sel)}); if (!b) return null; const l = b.querySelector('.cfst-l'); return {stage: b.dataset.stage, n: b.dataset.stages, sp: b.dataset.sp || '', aria: b.getAttribute('aria-label'), cur: b.querySelectorAll('circle.c').length, done: b.querySelectorAll('circle.d').length, open: b.querySelectorAll('circle.o').length, spDot: b.querySelectorAll('circle.s').length, label: l ? l.textContent : '', labelShown: !!l && l.getClientRects().length > 0 && getComputedStyle(l).display !== 'none', w: b.getBoundingClientRect().width}; })()`;

  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'frida', password: 'password123'})}).then(r => r.status)`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg'); await nav(B + '#l/' + L);
    check(await ready(ev, `typeof S === 'object' && !!S.me && !!document.querySelector('#view .lc[data-k="f:${FL.id}"] .cfst')`, 80), 'the list shows the stage bar in the column');
    let b = await ev(bar(`#tc-${T1} .cfst`));
    check(b && b.stage === '3' && b.n === '5' && b.cur === 1 && b.done === 2 && b.open === 2 && b.label === 'Review' && b.labelShown,
      `#3514: stage 3 of 5: two filled, the ring, two open, the name beside (special states are no stage) ${JSON.stringify(b)}`);
    check(b && /Build: Stage 3 of 5: Review/.test(b.aria || ''), `#3514: aria-label "Stage 3 of 5: name" ${b && b.aria}`);
    b = await ev(bar(`#tc-${T2} .cfst`));
    check(b && b.sp === 'red' && b.stage === '4' && b.spDot === 1 && b.done === 3 && b.cur === 0 && b.label === 'Parked',
      `#3514: the special state sits on the next stage (In main = 4), red, three filled, its name beside ${JSON.stringify(b)}`);
    check(await ev(`(() => { const c = document.querySelector('#tc-${T2} .cfst circle.s'), l = document.querySelector('#tc-${T2} .cfst-l'), d = getComputedStyle(document.documentElement).getPropertyValue('--danger').trim(); const rgb = x => { const e = document.createElement('i'); e.style.color = x; document.body.append(e); const v = getComputedStyle(e).color; e.remove(); return v; }; return getComputedStyle(c).fill === rgb(d) && getComputedStyle(l).color === rgb(d); })()`),
      '#3514: dot and name of the special state in the signal colour (--danger)');
    check(await ev(`(() => { const c = document.querySelector('#tc-${T1} .cfst circle.d'), a = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim(); const e = document.createElement('i'); e.style.color = a; document.body.append(e); const v = getComputedStyle(e).color; e.remove(); return getComputedStyle(c).fill === v; })()`),
      '#3514: a done stage in the accent colour');
    b = await ev(bar(`#tc-${T3} .cfst`));
    check(b && b.stage === '0' && b.cur === 0 && b.done === 0 && b.open === 5 && !b.label, `#3514: an empty field = grey dots, no name ${JSON.stringify(b)}`);
    if (SH) await shot('p24100a-list-1280.png');

    // the task panel: the wide bar
    await ev(`(() => { openDetail(${T1}); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('#detail .cfstw')`), '#3514: the task panel shows the wide stage bar');
    const wd = await ev(`(() => { const w = document.querySelector('#detail .cfstw'); const names = [...w.querySelectorAll('div[aria-hidden] > span')].map(s => s.textContent); return {stage: w.dataset.stage, names, cur: w.querySelectorAll('circle.c').length, done: w.querySelectorAll('circle.d').length, aria: w.getAttribute('aria-label'), wide: w.getBoundingClientRect().width > 200, sel: !!document.querySelector('#detail #cf-${FL.id}')}; })()`);
    check(wd && wd.stage === '3' && wd.names.join('|') === 'Planned|Building|Review|In main|Live' && wd.cur === 1 && wd.done === 2 && wd.wide && wd.sel,
      `#3514: the wide bar with a name under every stage, the select to change it stays ${JSON.stringify(wd)}`);
    check(await ready(ev, `/^since /.test(document.querySelector('#detail .cfstw-m')?.textContent || '')`, 60), '#3514: "since …" from the last change of the field');
    if (SH) await shot('p24100a-detail-1280.png');
    // changing the value in the panel moves the bar
    check(await ev(`!!document.querySelector('#detail #cf-${FL.id}')`), '#3514: the select of the field in the panel');
    await ev(`(() => { const s = document.querySelector('#detail #cf-${FL.id}'); if (!s) return 0; s.value = ${JSON.stringify(id(FL, 'Live'))}; s.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    check(await ready(ev, `document.querySelector('#detail .cfstw')?.dataset.stage === '5' && document.querySelector('#tc-${T1} .cfst')?.dataset.stage === '5'`), '#3514: a new value moves the bar in the panel and the row');

    // the field dialog: the switch and the kind per option
    await ev(`(() => { fieldModal(${L}, fieldById(${FL.id}), () => {}); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal #fd-stages')?.checked && document.querySelectorAll('.modal [data-osp]').length === 6 && document.querySelector('.modal [data-osp="3"]').value === 'red'`),
      '#3514: the field dialog has "Ordered (stages)" on and the kind per option (Parked = red)');
    const osp = await ev(`(() => { const s = document.querySelector('.modal [data-osp="1"]'); if (!s) return [...document.querySelectorAll('.modal')].map(m => m.className + ':' + m.querySelectorAll('[data-osp]').length).join(','); s.value = 'orange'; s.dispatchEvent(new Event('change', {bubbles: true})); document.querySelector('.modal [data-m="save"]').click(); return 1; })()`);
    check(osp === 1, `#3514: the kind of option 2 changed in the dialog ${osp}`);
    check(await ready(ev, `fieldById(${FL.id})?.options.options[1].special === 'orange' && !document.querySelector('.modal #fd-stages')`), '#3514: the dialog saves a special state');
    await ev(`(() => { fieldModal(${L}, null, () => {}); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal #fd-type')`), 'the new field dialog');
    check(await ev(`(() => { const t = document.querySelector('.modal #fd-type'); t.value = 'select'; t.dispatchEvent(new Event('change', {bubbles: true})); return !!document.querySelector('.modal #fd-stages') && !document.querySelector('.modal [data-osp]'); })()`),
      '#3514: a new choice field offers the switch, the kind per option only when it is on');
    check(await ev(`(() => { const t = document.querySelector('.modal #fd-type'); t.value = 'multiselect'; t.dispatchEvent(new Event('change', {bubbles: true})); return !document.querySelector('.modal #fd-stages'); })()`),
      '#3514: a multiple choice field has no stages');
    await ev(`(() => { document.querySelectorAll('.modal').forEach(m => m.remove()); return 1; })()`);

    // the board card
    await nav(B + 'static/icon.svg'); await nav(B + '#l/' + K);
    check(await ready(ev, `!!document.querySelector('#view .kanban .cfst')`, 80), '#3514: the board card shows the stage bar');
    b = await ev(bar('#view .kanban .cfst'));
    check(b && b.stage === '2' && b.cur === 1 && b.done === 1 && b.label === 'Building' && b.labelShown, `#3514: the card: stage 2 with its name ${JSON.stringify(b)}`);
    if (SH) await shot('p24100a-board-1280.png');

    // a phone: only the dots
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + 'static/icon.svg'); await nav(B + '#l/' + P);
    check(await ready(ev, `!!document.querySelector('#view .cfst')`, 80), '#3514: the phone list shows the stage bar on the row');
    b = await ev(bar('#view .cfst'));
    check(b && b.stage === '4' && b.cur === 1 && b.label === 'In main' && !b.labelShown && b.w < 80, `#3514: on a phone only the dots (the name stays in aria-label / title) ${JSON.stringify(b)}`);
    check(b && /Phase: Stage 4 of 5: In main/.test(b.aria || ''), '#3514: the phone row keeps the aria-label');
    if (SH) await shot('p24100a-list-390.png');
    await nav(B + 'static/icon.svg'); await nav(B + '#l/' + K);
    check(await ready(ev, `!!document.querySelector('#view .cfst')`, 80), '#3514: the phone board shows the bar');
    b = await ev(bar('#view .cfst'));
    check(b && b.stage === '2' && !b.labelShown, `#3514: the phone board: only the dots ${JSON.stringify(b)}`);
  });
  console.log(`p24100_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
