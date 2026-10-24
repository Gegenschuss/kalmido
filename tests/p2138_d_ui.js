// 2.138.0 D UI tests, own container (start.sh, a fresh one per section), invented data.
// (taken over from the 2.114.0 A / B / C suites, only the cases of #2256 #2060)
// ---- numranges (jsdom): #2256 number ranges (office_numranges.js).
// The settings page shows the next running number of every series below the number schemes: the preview follows the
// input, an invoice jump asks for a reason, "Apply" saves (confirm) and the scheme's "next: …" follows. The document editor:
// a click on the pencil next to the number opens the field; after saving the head AND the document list show the new
// number at once; a change made elsewhere (the console) reaches an open list with the next state load.
// ---- rules (jsdom):
// #2060 list settings > Rules: the dialog offers the new triggers (created, assigned, custom field) and actions (priority,
//       list tag, custom field) with their choices; "When a task is created, then priority high" is saved from the dialog,
//       the row shows the sentence, a new task gets the high priority (visible in the list); the field trigger shows the
//       values of a checkbox field, the field action the value input of a number field.
// ---- swimlanes (Firefox, the real layout):
// #2060 (#2033): Kanban swimlanes. The button above the board picks the lanes (none / person / priority / a select or
// checkbox field); none = the board as before. With priority: all four lanes, the cards in the lane of their priority and
// the column of their section, the column heads (with their menu) once on top. A card dropped into another lane and
// column takes over both (one undo step puts both back); "+ Task" in a lane creates the task with the lane's value; a
// lane folds and stays folded; the choice is remembered after a reload. Lanes by field and by person set the field / the
// assignee. A read-only member sees the lanes but cannot move a card. 390 px (touch): the page does not overflow sideways
// (only the board scrolls), a long press drags a card into another lane. A person without an organisation uses lanes in
// an own list (freelancer-matrix: lists).
// Screenshots with P2138D_SHOTS=<dir>.
// P2138D_NOSTART=1: a running server, no start.sh - then only one section, P2138D_PART=<name> (default the first)
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const NOSTART = !!process.env.P2138D_NOSTART;
const start = () => { if (!NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'}); };

async function part_numranges() {
  start();
  let CK;
  const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
  const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
  const Y = String(new Date().getFullYear());
  const range = async k => (await call('GET', '/api/office/number-ranges')).ranges.find(x => x.kind === k);
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,office,clients'});
  const st = await call('PUT', '/api/office/settings', {offer_scheme: 'A-{seq:03}', invoice_scheme: 'RE-{yyyy}-{seq:03}'});
  check(st.http === 200, 'schemes set ' + st.http);

  // ---- the settings page: the block below the number schemes (the person without an organisation = its own admin)
  const w = await boot({hash: 'office/settings'}); const d = w.document;
  w.confirm = () => true;
  check(!!await until(() => d.querySelector('#onum-invoice'), 80), 'the block "Next running number" is there');
  check(d.querySelectorAll('#onum-box .onumrow').length === 5, 'five series: quotation, invoice, credit note, reminder, delivery note');
  check(!d.querySelector('#onum-box input[id^="os-"]') && d.querySelector('#onum-box').hasAttribute('data-fg-skip'), 'not part of the settings save (no os- ids, form guard skipped)');
  const rowI = () => d.querySelector('.onumrow[data-kind="invoice"]');
  check(new RegExp('applies to ' + Y).test(rowI().textContent) && /at least 1/.test(rowI().textContent), 'invoice: "applies to <year>", smallest value');
  check(!/applies to/.test(d.querySelector('.onumrow[data-kind="offer"]').textContent), 'quotation without a year in the scheme: no year hint');
  check(rowI().querySelector('[data-onum="set"]').disabled && !d.querySelector('#onum-invoice-why'), 'unchanged: Apply off, no reason field');
  const inp = d.querySelector('#onum-invoice'); inp.value = '1001';
  inp.dispatchEvent(new w.Event('input', {bubbles: true}));
  check(await until(() => d.querySelector('#onum-invoice-why')), 'a jump in the invoice series asks for a reason');
  check(d.querySelector('#onum-invoice-pv').textContent.includes(`RE-${Y}-1001`), 'the preview shows the finished number: ' + d.querySelector('#onum-invoice-pv').textContent);
  check(d.activeElement && d.activeElement.id === 'onum-invoice', 'the focus stays in the field');
  check(d.activeElement.selectionStart === d.activeElement.value.length, 'the caret stays at the end after the redraw (device test: typing 1001 gave 0110)');  // 2.138.0 (#2256)
  check(!rowI().querySelector('[data-onum="set"]').disabled, 'Apply on');
  // without a reason: the server's error at the row
  rowI().querySelector('[data-onum="set"]').click();
  check(await until(() => /reason/.test(rowI().querySelector('[role="alert"]')?.textContent || '')), 'without a reason: the error at the row');
  check((await range('invoice')).next === 1, 'nothing saved without a reason');
  const why = d.querySelector('#onum-invoice-why'); why.value = 'Nummern bis 1000 im Altprogramm';
  why.dispatchEvent(new w.Event('input', {bubbles: true}));
  rowI().querySelector('[data-onum="set"]').click();
  check(await until(async () => (await range('invoice')).next === 1001, 40), 'Apply: the series continues at 1001');
  check(await until(() => /at least 1001/.test(rowI().textContent) && d.querySelector('#onum-invoice').value === '1001'), 'the row shows the new state');
  check(await until(() => (d.querySelector('#os-inv-scheme-pv')?.textContent || '').includes(`RE-${Y}-1001`)), 'the scheme\'s preview follows: ' + d.querySelector('#os-inv-scheme-pv')?.textContent);
  const log = await call('GET', '/api/office/log?limit=20');
  check(log.log.some(x => x.target === 'number_range' && x.detail.after.reason === 'Nummern bis 1000 im Altprogramm'), 'the reason is in the office log');
  // a quotation needs no reason
  const io = d.querySelector('#onum-offer'); io.value = '40'; io.dispatchEvent(new w.Event('input', {bubbles: true}));
  check(!d.querySelector('#onum-offer-why'), 'quotations: no reason field');
  d.querySelector('.onumrow[data-kind="offer"] [data-onum="set"]').click();
  check(await until(async () => (await range('offer')).next === 40, 40), 'quotation series at 40');
  w.close();

  // ---- the document editor: the draft's number, head and list at once
  const o1 = await call('POST', '/api/office/docs', {kind: 'offer', items: [{title: 'Schnitt', qty: 1, rate: 100}]});
  check(o1.http === 201 && o1.number === 'A-040', 'a new quotation gets A-040: ' + o1.number);
  const w2 = await boot({hash: 'office/offers'}); const d2 = w2.document;
  check(await until(() => (d2.querySelector('.ofdlist')?.textContent || '').includes('A-040'), 80), 'the list shows A-040');
  w2.location.hash = `office/offers/${o1.id}`;
  check(!!await until(() => d2.querySelector('[data-onum="doc-open"]'), 60), 'the draft has the pencil next to its number');
  d2.querySelector('[data-onum="doc-open"]').click();
  const din = await until(() => d2.querySelector('#onum-doc'));
  check(din && din.value === 'A-040', 'the field holds the number');
  check(/counter of the series stays/.test(d2.querySelector('.onumdoc')?.textContent || ''), 'quotation: the hint that the counter stays');
  din.value = 'A-777'; din.dispatchEvent(new w2.Event('input', {bubbles: true}));
  d2.querySelector('[data-onum="doc-save"]').click();
  check(await until(() => (d2.querySelector('.ofdhead .ofdnum b')?.textContent || '').includes('A-777') && !d2.querySelector('#onum-doc')), 'the head shows A-777 at once');
  check((await call('GET', `/api/office/docs/${o1.id}`)).number === 'A-777', 'saved on the server');
  w2.location.hash = 'office/offers';
  check(await until(() => { const t = d2.querySelector('.ofdlist')?.textContent || ''; return t.includes('A-777') && !t.includes('A-040'); }, 60), 'the list shows the new number at once');
  // a used number: the error at the field
  const o2 = await call('POST', '/api/office/docs', {kind: 'offer'});
  w2.location.hash = `office/offers/${o2.id}`;
  await until(() => w2.eval('OFD.doc && OFD.doc.id') === o2.id, 60);
  (await until(() => d2.querySelector('[data-onum="doc-open"]'))).click();
  const din2 = await until(() => d2.querySelector('#onum-doc')); din2.value = 'A-777';
  din2.dispatchEvent(new w2.Event('input', {bubbles: true}));
  d2.querySelector('[data-onum="doc-save"]').click();
  check(await until(() => /already used/.test(d2.querySelector('.onumdoc [role="alert"]')?.textContent || '')), 'a used number: the error at the field');
  d2.querySelector('[data-onum="doc-x"]').click();
  check(await until(() => !d2.querySelector('#onum-doc')), 'Cancel closes the field');
  // a sent quotation: no pencil
  await call('POST', `/api/office/docs/${o1.id}/status`, {status: 'sent'});
  w2.location.hash = `office/offers/${o1.id}`;
  await until(() => w2.eval('OFD.doc && OFD.doc.id') === o1.id, 60);
  await w2.eval(`ofdLoadDoc(${o1.id}, true)`);
  check(await until(() => d2.querySelector('.ofdhead') && w2.eval('OFD.doc.status') === 'sent') && !d2.querySelector('[data-onum="doc-open"]'), 'a sent quotation: no number field');
  // a change made elsewhere (the console) reaches the open list with the next state load
  w2.location.hash = 'office/offers';
  await until(() => (d2.querySelector('.ofdlist')?.textContent || '').includes(o2.number || 'A-041'), 60);
  const ch = await call('POST', `/api/office/docs/${o2.id}/number`, {number: 'A-555'});
  check(ch.http === 200, 'number changed through the API');
  await w2.eval('load()');
  check(await until(() => (d2.querySelector('.ofdlist')?.textContent || '').includes('A-555'), 60), 'the open list follows a change made elsewhere');
  w2.close();
}

async function part_rules() {
  start();
  let CK;
  const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
  const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
  const click = (w, el, o = {}) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
  const change = (w, el, v) => { if (!el) return; el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
  const FEAT = 'cal,comments,collab,fields';
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  const L = (await call('POST', '/api/lists', {name: 'Work', org_id: ORG})).id;
  const OKF = (await call('POST', `/api/lists/${L}/fields`, {name: 'Signed', type: 'checkbox'})).id;
  const HRS = (await call('POST', `/api/lists/${L}/fields`, {name: 'Hours', type: 'number'})).id;
  await call('POST', `/api/lists/${L}/tags`, {name: 'hot'});

  let w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  w.eval(`listModal(${L})`);
  await until(() => d.querySelector('#l-rules [data-rul-add]'));
  const box = () => d.querySelector('#l-rules');
  click(w, box().querySelector('[data-rul-add]'));
  await until(() => d.querySelector('.rul-dlg'));
  const dl = () => d.querySelector('.rul-dlg');
  const kinds = sel => [...(dl().querySelector(sel)?.options || [])].map(o => o.value);
  check(['created', 'assigned', 'field'].every(k => kinds('#rul-trig').includes(k)), '#2060: the new triggers in the dialog ' + kinds('#rul-trig'));
  check(['priority', 'tag', 'field'].every(k => kinds('#rul-act').includes(k)), '#2060: the new actions in the dialog ' + kinds('#rul-act'));
  // the choices of the new kinds
  change(w, dl().querySelector('#rul-trig'), 'assigned');
  check(kinds('#rul-tuser')[0] === '' && kinds('#rul-tuser').length >= 2, '#2060: assigned: anybody or a person ' + kinds('#rul-tuser'));
  change(w, dl().querySelector('#rul-trig'), 'field');
  check(kinds('#rul-tfld').includes(String(OKF)), '#2060: field trigger lists the custom fields');
  change(w, dl().querySelector('#rul-tfld'), String(OKF));
  check(kinds('#rul-tfv').join() === ',1,0', '#2060: checkbox field: any change / checked / unchecked ' + kinds('#rul-tfv'));
  change(w, dl().querySelector('#rul-act'), 'field');
  change(w, dl().querySelector('#rul-afld'), String(HRS));
  check(dl().querySelector('#rul-fval')?.tagName === 'INPUT', '#2060: number field: a value input');
  change(w, dl().querySelector('#rul-act'), 'tag');
  check(dl().querySelector('#rul-atag')?.options.length === 1, '#2060: tag action lists the list tags');
  // When a task is created, then priority high
  dl().querySelector('#rul-name').value = 'Hot';
  change(w, dl().querySelector('#rul-trig'), 'created');
  check(dl().querySelector('#rul-tv').hidden && dl().querySelector('#rul-tv2').hidden, '#2060: created needs no further choice');
  change(w, dl().querySelector('#rul-act'), 'priority');
  check(dl().querySelector('#rul-prio')?.value === 'high', '#2060: priority: high is the default');
  click(w, dl().querySelector('[data-m="save"]'));
  await until(() => !dl());
  const rules = (await call('GET', `/api/lists/${L}/rules`)).rules || [];
  check(rules.length === 1 && rules[0].trigger.kind === 'created' && rules[0].action.kind === 'priority' && rules[0].action.priority === 'high',
    '#2060: saved on the server ' + JSON.stringify(rules));
  await until(() => box()?.querySelector('.rul-row'));
  const txt = box()?.querySelector('.rul-row')?.textContent || '';
  check(/When a task is created, then set its priority to High\./.test(txt), '#2060: the row reads the sentence: ' + txt);
  d.querySelector('.modal [data-m="close"], .modal .x')?.click?.();
  w.close();

  // a new task gets the high priority, visible in the list
  const t = await call('POST', '/api/tasks', {list_id: L, title: 'Fresh lead'});
  check(t.priority === 5 || (await call('GET', `/api/tasks/${t.id}`)).priority === 5, '#2060: the rule set priority high');
  w = await boot({user: 'alice', hash: 'l/' + L}); d = w.document;
  const row = await until(() => d.querySelector(`#view .trow[data-id="${t.id}"]`));
  check(row && row.classList.contains('pr5') && row.querySelector('.chk.p5'), '#2060: the task shows the high priority in the list '
    + (row?.className || `missing (${d.querySelectorAll('#view .trow').length} rows, hash ${w.location.hash})`));
  w.close();
}

async function part_swimlanes() {
  start();
  const firefox = require('./ff')({tag: 'p2138_d_ui', check, shots: 'P2138D_SHOTS'});
  let CK;
  const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return Array.isArray(j) ? j : {...j, status: r.status}; };
  const FEAT = 'cal,kanban,collab,comments,fields';
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
  // 2.284.0 A (#3120): the step lands in HIST only after the client has the PATCH answer - the server (which the test polls)
  // can be there first on a busy place, and an early histStep undid nothing. mark(ev) before the action; undo waits for a new
  // top step (and no undo running), then for its end
  const mark = ev => ev(`(() => { window.__h0 = HIST.undo[HIST.undo.length - 1] || null; return 1; })()`);
  const undo = async ev => {
    await until(() => ev(`!HIST.busy && (HIST.undo[HIST.undo.length - 1] || null) !== window.__h0`), 60);
    await ev(`(() => { histStep('undo'); return 1; })()`);
    await sleep(200); await until(() => ev(`!HIST.busy`), 60);
  };

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
    if (theme === 'dark') { await shot('p2138d-prio-1440-dark.png'); return; }
    await shot('p2138d-prio-1440-light.png');
    // a card into another lane and column: priority and section, one undo step for both
    await mark(ev);
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
    await shot('p2138d-field-1440-light.png');
    await mark(ev);
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
    await mark(ev);
    check(await dnd(ev, T2, cell('u' + ALICE, S2)) === 'ok' && await until(async () => (await task(T2)).assignee_id === ALICE), `${tag}: dropped into Alice's lane: assigned to her`);
    await undo(ev);
    check(await until(async () => !(await task(T2)).assignee_id), `${tag}: one undo takes the assignment back`);
    await shot('p2138d-person-1440-light.png');
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
    await shot('p2138d-prio-390.png');
    // long press on Gamma (Medium / Doing), drag down into the No priority lane, same column
    await ev(`(() => { document.querySelector('#view .swlane[data-swl="p3"]').scrollIntoView({block: 'start'}); return 1; })()`); await sleep(400);
    const r = await ev(`(() => { const a = document.querySelector('#view .trow[data-id="${T3}"]').getBoundingClientRect(), b = document.querySelector('${cell('p0', S1)}').getBoundingClientRect(); return {x: a.left + 30, y: a.top + a.height / 2, tx: b.left + 30, ty: b.top + Math.min(b.height - 6, 24), vh: innerHeight}; })()`);
    check(r.ty < r.vh - 10, `${tag}: the target lane is on screen ` + JSON.stringify(r));
    await mark(ev);
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
    await shot('p2138d-freelancer-1440.png');
  };

  await firefox(async o => { await desk(o, 'light'); await desk(o, 'dark'); await freelancer(o); }, false);
  await firefox(async o => { await phone(o); }, true);
}

const PARTS = {numranges: part_numranges, rules: part_rules, swimlanes: part_swimlanes};
(async () => {
  for (const n of NOSTART ? [process.env.P2138D_PART || 'numranges'] : Object.keys(PARTS)) await PARTS[n]();
  console.log(`p2138_d_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
