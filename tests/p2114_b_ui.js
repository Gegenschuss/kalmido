// 2.114.0 part B UI test, own container (start.sh), Firefox (the real layout).
// #2060 (#2033): Kanban swimlanes. The button above the board picks the lanes (none / person / priority / a select or
// checkbox field); none = the board as before. With priority: all four lanes, the cards in the lane of their priority and
// the column of their section, the column heads (with their menu) once on top. A card dropped into another lane and
// column takes over both (one undo step puts both back); "+ Task" in a lane creates the task with the lane's value; a
// lane folds and stays folded; the choice is remembered after a reload. Lanes by field and by person set the field / the
// assignee. A read-only member sees the lanes but cannot move a card. 390 px (touch): the page does not overflow sideways
// (only the board scrolls), a long press drags a card into another lane. A person without an organisation uses lanes in
// an own list (freelancer-matrix: lists).
// Screenshots with P2114B_SHOTS=<dir>.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2114_b_ui', check, shots: 'P2114B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2114B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return Array.isArray(j) ? j : {...j, status: r.status}; };
const FEAT = 'cal,kanban,collab,comments,fields';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ALICE = (await call('GET', '/api/state')).me.id;
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'})).id;
  const BK = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, BK);
  const P = (await call('POST', '/api/lists', {name: 'Board Alpha', kind: 'project'})).id;
  await call('PATCH', `/api/lists/${P}`, {view: 'kanban'});
  const S1 = (await call('POST', '/api/sections', {list_id: P, name: 'Doing'})).id, S2 = (await call('POST', '/api/sections', {list_id: P, name: 'Review'})).id;
  const fs = await call('POST', `/api/lists/${P}/fields`, {name: 'Stage', type: 'select', options: {options: [{name: 'Idea', color: '#94a3b8'}, {name: 'Build', color: '#6d8cff'}]}});
  const FS = fs.id, OPT = Object.fromEntries((fs.options?.options || []).map(o => [o.name, o.id]));
  check(FS && OPT.Idea && OPT.Build, 'setup: the select field with two options ' + JSON.stringify(fs));
  const mk = async (title, sid, priority, extra = {}) => (await call('POST', '/api/tasks', {title, list_id: P, section_id: sid, priority, ...extra})).id;
  const T1 = await mk('Alpha card', S1, 5, {fields: {[FS]: OPT.Idea}, assignee_id: ALICE}), T2 = await mk('Beta card', S2, 0), T3 = await mk('Gamma card', S1, 3);
  await call('PUT', `/api/lists/${P}/members`, {user_id: BOB, role: 'view'});
  const task = async (id, ck = CK) => (await call('GET', '/api/state', null, ck)).tasks.find(t => t.id === id) || {};
  const until = async (fn, n = 30) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(200); } return fn(); };

  const ffLogin = async ({ev, nav}, theme, user = 'alice') => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"${theme}"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${user}', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, sel, n = 40) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('${sel}')`).catch(() => false)); i++) await sleep(250); await sleep(700); };
  // the lanes menu: pick an entry by its text
  const pick = async (ev, re) => {
    await ev(`(() => { document.querySelector('#view [data-swl-menu]').click(); return 1; })()`); await sleep(400);
    const items = await ev(`[...document.querySelectorAll('.menu-list [role="menuitem"]')].map(b => b.textContent.trim())`);
    await ev(`(() => { const b = [...document.querySelectorAll('.menu-list [role="menuitem"]')].find(b => ${re}.test(b.textContent.trim())); b && b.click(); return !!b; })()`); await sleep(600);
    return items;
  };
  const cell = (lane, sec) => `#view .swlane[data-swl="${lane}"] .kcol[data-kcol="${sec}"]`;
  const inCell = (ev, id, lane, sec) => ev(`!!document.querySelector('${cell(lane, sec)} .trow[data-id="${id}"]')`);
  // a mouse drag: the app's own dragstart / dragover / drop / dragend listeners with a real DataTransfer
  const dnd = (ev, id, sel) => ev(`(() => { const r = document.querySelector('#view .trow[data-id="${id}"]'), t = document.querySelector('${sel}'); if (!r || !t) return 'missing';
    const dt = new DataTransfer(), f = (el, type) => { const b = el.getBoundingClientRect(); const e = new DragEvent(type, {bubbles: true, cancelable: true, dataTransfer: dt, clientX: b.left + 10, clientY: b.top + b.height - 4}); el.dispatchEvent(e); return e; };
    f(r, 'dragstart'); return new Promise(res => setTimeout(() => { const o = f(t, 'dragover'); f(t, 'drop'); f(r.isConnected ? r : document.body, 'dragend'); res(o.defaultPrevented ? 'ok' : 'refused'); }, 60)); })()`);
  const undo = async ev => { await ev(`(() => { histStep('undo'); return 1; })()`); await sleep(1300); };

  const desk = async (o, theme) => {
    const {ev, shot} = o, tag = `1440 ${theme}`;
    await o.cmd('browsingContext.setViewport', {context: o.ctx, viewport: {width: 1440, height: 900}});
    check(await ffLogin(o, theme) === 200, tag + ': login');
    await o.nav(B + '#l/' + P); await ready(ev, '#view .kanban .kcol');
    // none: the board as before, the button above it
    check(await ev(`!!document.querySelector('#view [data-swl-menu]') && !document.querySelector('#view .kanban.swl') && document.querySelectorAll('#view .kanban > .kcol').length === 2`), `${tag}: no lanes by default, the board as before`);
    const items = await pick(ev, '/^Priority$/');
    check(['None', 'Person', 'Priority', 'Stage'].every(x => items.includes(x)), `${tag}: the menu offers none, person, priority and the select field ` + JSON.stringify(items));
    const lanes = await ev(`[...document.querySelectorAll('#view .swlane')].map(l => l.dataset.swl + ':' + l.querySelector('.swln').textContent + ':' + l.querySelector('.swlh .c').textContent).join('|')`);
    const want = theme === 'light' ? 'p5:High:1|p3:Medium:1|p1:Low:0|p0:No priority:1' : 'p5:High:1|p3:Medium:2|p1:Low:0|p0:No priority:1';  // (dark: + the task added in the light run)
    check(lanes === want, `${tag}: four priority lanes, "No priority" last, with counts ` + lanes);
    check(await inCell(ev, T1, 'p5', S1) && await inCell(ev, T3, 'p3', S1) && await inCell(ev, T2, 'p0', S2), `${tag}: every card in the lane of its priority and the column of its section`);
    check(await ev(`document.querySelectorAll('#view .swlhrow .khead').length === 2 && document.querySelectorAll('#view .khead').length === 2 && !!document.querySelector('#view .swlhrow [data-act="section-menu"][data-id="${S1}"]')`), `${tag}: the column heads (with their menu) once, on top`);
    if (theme === 'dark') { await shot('p2114b-prio-1440-dark.png'); return; }
    await shot('p2114b-prio-1440-light.png');
    // a card into another lane and column: priority and section, one undo step for both
    check(await dnd(ev, T2, cell('p5', S1)) === 'ok', `${tag}: a lane cell takes the dragged card`);
    check(await until(async () => { const t = await task(T2); return t.priority === 5 && t.section_id === S1; }), `${tag}: dropped into High / Doing: priority and column set ` + JSON.stringify(await task(T2)));
    check(await until(() => inCell(ev, T2, 'p5', S1)), `${tag}: the card shows in its new lane`);
    await undo(ev);
    check(await until(async () => { const t = await task(T2); return t.priority === 0 && t.section_id === S2; }), `${tag}: one undo puts priority and column back ` + JSON.stringify(await task(T2)));
    // "+ Task" in a lane: the lane's priority
    await ev(`(() => { const i = document.querySelector('${cell('p3', S2)} [data-kadd]'); i.value = 'Delta card'; i.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true, cancelable: true})); return 1; })()`);
    const nd = await until(async () => (await call('GET', '/api/state')).tasks.find(t => t.title === 'Delta card'));
    check(nd && nd.priority === 3 && nd.section_id === S2, `${tag}: "+ Task" in Medium / Review creates the task with priority Medium ` + JSON.stringify(nd && {p: nd.priority, s: nd.section_id}));
    // fold a lane; it stays folded
    await ev(`(() => { document.querySelector('#view .swlane[data-swl="p1"] .swlh').click(); return 1; })()`); await sleep(500);
    check(await ev(`document.querySelector('#view .swlane[data-swl="p1"]').classList.contains('closed') && !document.querySelector('#view .swlane[data-swl="p1"] .kcol')`), `${tag}: a lane folds`);
    // lanes by the select field
    await pick(ev, '/^Stage$/');
    const fl = await ev(`[...document.querySelectorAll('#view .swlane .swln')].map(x => x.textContent).join('|')`);
    check(fl === 'Idea|Build|No value', `${tag}: lanes by the field: its options, "No value" last ` + fl);
    check(await inCell(ev, T1, 'v' + OPT.Idea, S1) && await inCell(ev, T3, 'n', S1), `${tag}: the cards in the lane of their value`);
    await shot('p2114b-field-1440-light.png');
    check(await dnd(ev, T3, cell('v' + OPT.Build, S1)) === 'ok', `${tag}: field lane takes the card`);
    check(await until(async () => String((await task(T3)).fields?.[FS] ?? '') === String(OPT.Build)), `${tag}: dropped into Build: the field is set ` + JSON.stringify((await task(T3)).fields));
    await undo(ev);
    check(await until(async () => (await task(T3)).fields?.[FS] == null), `${tag}: one undo clears the field again ` + JSON.stringify((await task(T3)).fields));
    // remembered after a reload (per list, on this account)
    await o.nav(B + 'static/icon.svg'); await o.nav(B + '#l/' + P); await ready(ev, '#view .kanban.swl');
    check(await ev(`document.querySelector('#view .kanban.swl')?.dataset.swlmode === 'f${FS}'`), `${tag}: the choice is remembered after a reload`);
    await pick(ev, '/^Priority$/');
    check(await ev(`document.querySelector('#view .swlane[data-swl="p1"]').classList.contains('closed')`), `${tag}: the folded lane is still folded`);
    // lanes by person: Alice (T1) and nobody; a card into Alice's lane assigns her
    await pick(ev, '/^Person$/');
    const pl = await ev(`[...document.querySelectorAll('#view .swlane')].map(l => l.dataset.swl).join('|')`);
    check(pl === `u${ALICE}|n`, `${tag}: lanes by person: the people with tasks, then nobody ` + pl);
    check(await dnd(ev, T2, cell('u' + ALICE, S2)) === 'ok' && await until(async () => (await task(T2)).assignee_id === ALICE), `${tag}: dropped into Alice's lane: assigned to her`);
    await undo(ev);
    check(await until(async () => !(await task(T2)).assignee_id), `${tag}: one undo takes the assignment back`);
    await shot('p2114b-person-1440-light.png');
    // a read-only member: lanes yes, moving no
    check(await ffLogin(o, theme, 'bob') === 200, `${tag}: bob logs in`);
    await o.nav(B + '#l/' + P); await ready(ev, '#view .kanban .kcol');
    await pick(ev, '/^Priority$/');
    check(await ev(`!!document.querySelector('#view .kanban.swl') && !document.querySelector('#view [data-kadd]') && !document.querySelector('#view .swlhrow .knew')`), `${tag}: read only: lanes, but no "+ Task" and no new column`);
    await ev(`(async () => { await dropTask(${T2}, document.querySelector('${cell('p5', S2)}'), 10); return 1; })()`); await sleep(900);
    check((await task(T2)).priority === 0, `${tag}: read only: a drop into another lane changes nothing`);
  };

  const phone = async o => {
    const {ev, shot, cmd, ctx} = o, tag = '390 touch';
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    check(await ffLogin(o, 'light') === 200, tag + ': login');
    await o.nav(B + '#l/' + P); await ready(ev, '#view .kanban .kcol');
    await pick(ev, '/^Priority$/');
    const ov = await ev(`(() => { const k = document.querySelector('#view .kanban.swl'); return {page: document.documentElement.scrollWidth, vw: innerWidth, bw: k ? k.scrollWidth : 0, bc: k ? k.clientWidth : 0}; })()`);
    check(ov.page <= ov.vw + 1, `${tag}: the page does not overflow sideways ` + JSON.stringify(ov));
    check(ov.bw > ov.bc, `${tag}: the board itself scrolls sideways ` + JSON.stringify(ov));
    await shot('p2114b-prio-390.png');
    // long press on Gamma (Medium / Doing), drag down into the No priority lane, same column
    await ev(`(() => { document.querySelector('#view .swlane[data-swl="p3"]').scrollIntoView({block: 'start'}); return 1; })()`); await sleep(400);
    const r = await ev(`(() => { const a = document.querySelector('#view .trow[data-id="${T3}"]').getBoundingClientRect(), b = document.querySelector('${cell('p0', S1)}').getBoundingClientRect(); return {x: a.left + 30, y: a.top + a.height / 2, tx: b.left + 30, ty: b.top + Math.min(b.height - 6, 24), vh: innerHeight}; })()`);
    check(r.ty < r.vh - 10, `${tag}: the target lane is on screen ` + JSON.stringify(r));
    const P0 = {type: 'pointerMove', x: Math.round(r.x), y: Math.round(r.y)};
    await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'f1', parameters: {pointerType: 'touch'}, actions: [P0, {type: 'pointerDown', button: 0}, {type: 'pause', duration: 650},
      {type: 'pointerMove', x: Math.round(r.x), y: Math.round((r.y + r.ty) / 2), duration: 250}, {type: 'pointerMove', x: Math.round(r.tx), y: Math.round(r.ty), duration: 250}, {type: 'pause', duration: 200}, {type: 'pointerUp', button: 0}]}]});
    await cmd('input.releaseActions', {context: ctx});
    check(await until(async () => { const t = await task(T3); return t.priority === 0 && t.section_id === S1; }), `${tag}: a long press drags the card into the No priority lane ` + JSON.stringify(await task(T3)));
    await undo(ev);
    check(await until(async () => (await task(T3)).priority === 3), `${tag}: undo puts the priority back`);
  };

  // freelancer-matrix: lists -- a person without an organisation, an own list with a checkbox field
  const freelancer = async o => {
    const {ev, shot} = o, tag = 'freelancer';
    const fr = await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
    const FK = await login('frida');
    await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, FK);
    check(fr.id && !((await call('GET', '/api/state', null, FK)).me.workspaces || []).length, `${tag}: a person without an organisation`);
    const L = (await call('POST', '/api/lists', {name: 'My board', kind: 'project'}, FK)).id;
    await call('PATCH', `/api/lists/${L}`, {view: 'kanban'}, FK);
    const FC = (await call('POST', `/api/lists/${L}/fields`, {name: 'Urgent', type: 'checkbox'}, FK)).id;
    const X = (await call('POST', '/api/tasks', {title: 'Own card', list_id: L}, FK)).id;
    await o.cmd('browsingContext.setViewport', {context: o.ctx, viewport: {width: 1440, height: 900}});
    check(await ffLogin(o, 'light', 'frida') === 200, `${tag}: login`);
    await o.nav(B + '#l/' + L); await ready(ev, '#view .kanban .kcol');
    const items = await pick(ev, '/^Urgent$/');
    check(!items.includes('Stage') && items.includes('Urgent'), `${tag}: the menu offers the own checkbox field ` + JSON.stringify(items));
    const fl = await ev(`[...document.querySelectorAll('#view .swlane .swln')].map(x => x.textContent).join('|')`);
    check(fl === 'Urgent: yes|Urgent: no', `${tag}: checkbox lanes ` + fl);
    check(await dnd(ev, X, '#view .swlane[data-swl="v1"] .kcol') === 'ok' && await until(async () => (await task(X, FK)).fields?.[FC] === '1'), `${tag}: dropped into "Urgent: yes": the box is ticked`);
    await shot('p2114b-freelancer-1440.png');
  };

  await firefox(async o => { await desk(o, 'light'); await desk(o, 'dark'); await freelancer(o); }, false);
  await firefox(async o => { await phone(o); }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
