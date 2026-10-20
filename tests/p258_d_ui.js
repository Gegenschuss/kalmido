// 2.58.0 UI tests, part D (#1644 #1756 ...), own container (start.sh). jsdom, invented data only:
// - #1644 the Office master data search keeps the focus (and the caret) while typing
// - #1756 a shown "New message" / "New comment" pill stays on a redraw (morph)
// - #1758 Esc in a number field of the task detail puts the saved value back
// - #1812 the office privacy switch sits above the Save button
// - #1765 the German Crew heading; #1757 Back closes the topmost dialog (touch), sheets keep a visible X
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.BASE) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});  // BASE = a ready app (quick local check)
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el, o = {}) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const firefox = require('./ff')({tag: 'p258_d_ui', check, shots: 'P258D_SHOTS'});
const FEAT = 'cal,comments,collab,time,progress,kanban,timeline,fields,team';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['cal', 'comments', 'office']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT + ',office'});

  // ================= #1644: Office search keeps focus
  for (const n of ['Camera A', 'Camera B', 'Lens']) await call('POST', '/api/office/equipment', {name: n, category: 'Cam', daily_rate: 10});
  let w = await boot({user: 'alice', hash: 'office/equipment', mobile: !!process.env.MOB}), d = w.document;
  await until(() => d.querySelector('#ofc-q'));
  const q0 = d.querySelector('#ofc-q');
  check(!!q0, '#1644: search field there');
  if (q0) {
    q0.focus();
    for (const v of ['c', 'ca', 'cam']) {
      const q = d.querySelector('#ofc-q'); q.value = v; q.setSelectionRange(v.length, v.length); q.dispatchEvent(new w.Event('input', {bubbles: true})); await sleep(200);
    }
    const q3 = d.querySelector('#ofc-q');
    check(d.activeElement === q3 && q3.value === 'cam', '#1644: focus + text kept after typing: ' + d.activeElement?.tagName + '#' + d.activeElement?.id + ' ' + q3?.value);
    check(q3 === q0, '#1644: the same input node');
  }
  // ================= #1756: the pill survives a morph
  check(w.eval(`(() => { const a = document.createElement('div'), b = document.createElement('div'); a.innerHTML = '<button id="tc-new" class="chnew">New</button><button id="cm-new" class="chnew">N</button>'; b.innerHTML = '<button id="tc-new" class="chnew hidden">New</button><button id="cm-new" class="chnew hidden">N</button>'; morphKids(a, b); return !a.querySelector('#tc-new').classList.contains('hidden') && !a.querySelector('#cm-new').classList.contains('hidden'); })()`), '#1756: a shown tc-new / cm-new pill stays shown on a morph');
  w.close();

  // ================= #1812: the office privacy switch above Save; 2.113.0 (#2247): no Save button, the switch sits in the area Access
  w = await boot({user: 'alice', hash: 'office/settings'}); d = w.document;
  await until(() => d.querySelector('#os-agents-read'));
  const sw1 = d.querySelector('#os-agents-read');
  check(sw1 && sw1.closest('[data-ostp]')?.dataset.ostp === 'access' && !d.querySelector('[data-ofc="save-settings"]'), '#1812: the switch sits in the area Access (no Save button)');
  w.close();

  // ================= #1758: Esc in a detail number field
  const P = (await call('POST', '/api/lists', {name: 'Fields', kind: 'project'})).id;
  const FN = (await call('POST', `/api/lists/${P}/fields`, {name: 'Budget', type: 'number'})).id;
  const T = (await call('POST', '/api/tasks', {title: 'Plan', list_id: P})).id;
  await call('PATCH', `/api/tasks/${T}`, {fields: {[FN]: '5'}});
  w = await boot({user: 'alice', hash: 't/' + T}); d = w.document;
  await until(() => d.querySelector(`#cf-${FN}`));
  const nf = d.querySelector(`#cf-${FN}`);
  check(!!nf, '#1758: the number field is in the detail');
  if (nf) {
    nf.focus(); nf.value = '77'; nf.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true, cancelable: true})); await sleep(200);
    check(nf.value === '5', '#1758: Esc puts the saved value back: ' + nf.value);
  }
  w.close();
  // the real browser: typing keys (jsdom does not blur a moved node)
  await firefox(async ({cmd, ev, nav, ctx}) => {
    await nav(B + 'static/icon.svg');
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    await nav(B + '?v=1#office/equipment');
    for (let i = 0; i < 30 && !(await ev(`!!document.querySelector('#ofc-q')`).catch(() => false)); i++) await sleep(300);
    await ev(`document.querySelector('#ofc-q').focus()`);
    const typeKey = k => cmd('input.performActions', {context: ctx, actions: [{type: 'key', id: 'k1', actions: [{type: 'keyDown', value: k}, {type: 'keyUp', value: k}]}]});
    for (const k of ['c', 'a', 'm']) { await typeKey(k); await sleep(400); }
    const st = await ev(`(() => { const a = document.activeElement; return {id: a && a.id, v: a && a.value}; })()`);
    check(st.id === 'ofc-q' && st.v === 'cam', '#1644: Firefox: typing three keys keeps the focus: ' + JSON.stringify(st));
  }, true);

  // ================= #1757: Back closes the topmost dialog on a phone
  await firefox(async ({cmd, ev, nav, ctx}) => {
    await nav(B + 'static/icon.svg');
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + '?v=2#office/equipment');
    for (let i = 0; i < 30 && !(await ev(`!!document.querySelector('#ofc-q')`).catch(() => false)); i++) await sleep(300);
    const h0 = await ev(`location.hash`);
    await ev(`(() => { modal('<h3>Test dialog</h3><button data-m="close" class="iconbtn">x</button>'); return 1; })()`); await sleep(400);
    check(await ev(`!!document.querySelector('.modal')`) && await ev(`!!(history.state && history.state.f8d)`), '#1757: an open dialog has its history entry');
    await cmd('browsingContext.traverseHistory', {context: ctx, delta: -1}); await sleep(600);
    check(!(await ev(`!!document.querySelector('.modal:not(.an-out)')`)) && (await ev(`location.hash`)) === h0, '#1757: Back closed the dialog and kept the route: ' + await ev(`location.hash`));
    await ev(`(() => { modal('<h3>Second</h3>'); return 1; })()`); await sleep(300);
    await ev(`(() => { modalClose(document.querySelector('.modal')); return 1; })()`); await sleep(600);
    check(!(await ev(`!!(history.state && history.state.f8d)`)), '#1757: closing the dialog by hand takes its entry away again');
  }, true);
  console.log(F.length ? 'FAILED ' + F.length : 'ok', ok);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('crash', e); process.exit(1); });
