// 2.156.0 UI tests, part B (list fields), own container (start.sh), Firefox on a desktop (1440 x 900, mouse):
// - #2069: a rating column: a click on a star sets it, a click on the same star clears it; a multiple choice in the detail
//   panel: tapping options toggles them (both saved, in the order of the options); a task link shows the linked title and
//   its picker sets another task; the field dialog loads the currency / rating part on demand (cfkinds.js)
// - #2070: a formula with WENN / RUNDEN shows its value in the column, a division by 0 shows a short error text
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2156_b_ui', check, shots: 'P2156B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'comments,collab,fields'});
  const L = (await call(CA, 'POST', '/api/lists', {name: 'Purchases', kind: 'project'})).id;
  const MS = await call(CA, 'POST', `/api/lists/${L}/fields`, {name: 'Colours', type: 'multiselect', options: {options: [{name: 'Red', color: '#e5484d'}, {name: 'Green', color: '#30a46c'}, {name: 'Blue'}]}});
  const [RED, GREEN] = MS.options.options.map(o => o.id);
  const CU = (await call(CA, 'POST', `/api/lists/${L}/fields`, {name: 'Price', type: 'currency', options: {currency: 'EUR'}})).id;
  const RT = (await call(CA, 'POST', `/api/lists/${L}/fields`, {name: 'Stars', type: 'rating'})).id;
  const TK = (await call(CA, 'POST', `/api/lists/${L}/fields`, {name: 'Depends on', type: 'task'})).id;
  const FX = (await call(CA, 'POST', `/api/lists/${L}/fields`, {name: 'Net', type: 'formula', formula: 'WENN({Price} > 100; RUNDEN({Price} * 0,9; 2); {Price})'})).id;
  const FD = (await call(CA, 'POST', `/api/lists/${L}/fields`, {name: 'Per star', type: 'formula', formula: '{Price} / {Stars}'})).id;
  check(MS.id && CU && RT && TK && FX && FD, 'setup: fields');
  await call(CA, 'PATCH', `/api/lists/${L}`, {columns: [`f:${MS.id}`, `f:${CU}`, `f:${RT}`, `f:${TK}`, `f:${FX}`, `f:${FD}`]});
  const T2 = (await call(CA, 'POST', '/api/tasks', {title: 'Dock', list_id: L})).id;
  const T3 = (await call(CA, 'POST', '/api/tasks', {title: 'Charger', list_id: L})).id;
  const T1 = (await call(CA, 'POST', '/api/tasks', {title: 'Laptop', list_id: L, fields: {[CU]: '120', [TK]: String(T2)}})).id;
  const fv = async id => (await call(CA, 'GET', `/api/tasks/${id}`)).fields || {};

  await firefox(async o => {
    const {cmd, ev, ctx, nav, shot} = o;
    const ready = async (expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
    const act = actions => cmd('input.performActions', {context: ctx, actions}).then(() => cmd('input.releaseActions', {context: ctx}));
    const clickAt = (x, y) => act([{type: 'pointer', id: 'm', parameters: {pointerType: 'mouse'}, actions: [{type: 'pointerMove', x: Math.round(x), y: Math.round(y)}, {type: 'pointerDown', button: 0}, {type: 'pointerUp', button: 0}]}]);
    const mid = sel => ev(`(() => { const e = document.querySelector(${JSON.stringify(sel)}); if (!e) return null; const b = e.getBoundingClientRect(); return {x: b.left + b.width / 2, y: b.top + b.height / 2}; })()`);
    const click = async sel => { const p = await mid(sel); if (!p) return false; await clickAt(p.x, p.y); return true; };
    const until = async (fn, n = 20) => { for (let i = 0; i < n; i++) { if (await fn()) return true; await sleep(250); } return false; };
    const cell = fid => `#tc-${T1} .lc[data-k="f:${fid}"]`;
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await nav(B + '#l/' + L);
    check(await ready(`!!document.querySelector('${cell(RT)}')`), 'Firefox: the list with the new columns');
    await sleep(400);

    // ================= #2070 formula values, #2069 task link title
    const net = await ev(`document.querySelector('${cell(FX)}').textContent.trim()`);
    check(net === '108', '#2070: WENN / RUNDEN in the column: ' + net);
    const per = await ev(`document.querySelector('${cell(FD)}').textContent.trim()`);
    check(per === 'Division by 0', '#2070: a division by 0 shows a short error: ' + per);
    check(await ready(`(document.querySelector('${cell(TK)} .cfktl')?.textContent || '').includes('Dock')`), '#2069: the task link shows the linked title');

    // ================= #2069 rating: a star sets, the same star clears
    check(await click(`${cell(RT)} [data-n="3"]`), '#2069: the third star is there');
    check(await until(async () => (await fv(T1))[RT] === '3'), '#2069: a click on the third star saves 3');
    check(await ready(`document.querySelectorAll('${cell(RT)} button.on').length === 3`), '#2069: three stars lit');
    await shot('p2156b-list.png');
    await click(`${cell(RT)} [data-n="3"]`);
    check(await until(async () => !(RT in (await fv(T1)))), '#2069: the same star again clears it');

    // ================= #2069 multiple choice in the detail panel
    await ev(`openDetail(${T1})`);
    check(await ready(`!!document.querySelector('[data-cfkms="${MS.id}"][data-o="${GREEN}"]')`), '#2069: the options in the detail panel');
    await click(`[data-cfkms="${MS.id}"][data-o="${GREEN}"]`);
    check(await until(async () => (await fv(T1))[MS.id] === GREEN), '#2069: tapping Green chooses it');
    await sleep(300);
    await click(`[data-cfkms="${MS.id}"][data-o="${RED}"]`);
    check(await until(async () => (await fv(T1))[MS.id] === `${RED},${GREEN}`), '#2069: tapping Red adds it (order of the options)');
    check(await ready(`document.querySelector('[data-cfkms="${MS.id}"][data-o="${RED}"]').getAttribute('aria-pressed') === 'true'`), '#2069: the chosen option is pressed');
    check(await ready(`document.querySelectorAll('${cell(MS.id)} .fchip.sel').length === 2`), '#2069: the column shows both options');

    // ================= #2069 task link picker (loaded on demand)
    await click(`[data-cfkpick="${TK}"]`);
    check(await ready(`!!document.querySelector('#cfk-list [data-cfkp="${T3}"]')`), '#2069: the picker lists the open tasks');
    await shot('p2156b-picker.png');
    await click(`#cfk-list [data-cfkp="${T3}"]`);
    check(await until(async () => (await fv(T1))[TK] === String(T3)), '#2069: picking a task links it');
    await shot('p2156b-detail.png');

    // ================= #2069 the field dialog: the rating part comes from the module on demand
    await ev(`(fieldModal(${L}), 1)`);
    check(await ready(`!!document.querySelector('#fd-type')`), '#2069: the field dialog');
    await ev(`(() => { const s = document.querySelector('#fd-type'); s.value = 'rating'; s.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    check(await ready(`!!document.querySelector('#fd-rmax')`), '#2069: the rating part (number of stars) is shown');
    await ev(`(() => { document.querySelector('#fd-name').value = 'Mood'; document.querySelector('#fd-rmax').value = '7'; return 1; })()`);
    await click('.modal [data-m="save"]');
    const mood = async () => ((await call(CA, 'GET', '/api/state')).fields || []).find(f => f.name === 'Mood');
    check(await until(async () => (await mood())?.options?.max === 7), '#2069: a rating field with 7 stars saved');
  }, false);

  console.log(`p2156_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
