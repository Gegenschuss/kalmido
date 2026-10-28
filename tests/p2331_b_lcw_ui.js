// kalmido-suite: fresh
// 2.331.0 B (#3304) UI test, own container (start.sh), Firefox on a desktop (1440 x 900, mouse): dragging a column width moves
// only the column title and the guide line; the rows keep their width until the mouse is released, then title and rows have
// the same width and it is stored (per device and list). The guide line follows the column's left edge. A person without an
// organisation in her private list.
// freelancer-matrix: lists (no route touched; the person has no organisation)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2331_b_lcw_ui', check, shots: 'P2331B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', modules: ['fields']});
  // the freelancer: created without an organisation, her own private list
  const fr = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com'});
  check(fr.id > 0, 'the person without an organisation (setup)');
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'fields'});
  const st = await call(CF, 'GET', '/api/state');
  check(!(st.orgs || []).length, 'frida has no organisation');
  const L = (await call(CF, 'POST', '/api/lists', {name: 'Private things'})).id;
  const FT = (await call(CF, 'POST', `/api/lists/${L}/fields`, {name: 'Note', type: 'text'})).id;
  await call(CF, 'PATCH', `/api/lists/${L}`, {columns: ['due', `f:${FT}`]});
  const T = [];
  for (let i = 0; i < 8; i++) T.push((await call(CF, 'POST', '/api/tasks', {title: `Thing ${i + 1}`, list_id: L, due: '2026-11-0' + (1 + i % 9), fields: {[FT]: `note ${i}`}})).id);
  check(T.every(Boolean), 'eight tasks with a note (setup)');

  await firefox(async o => {
    const {cmd, ev, ctx, nav, shot} = o;
    const ready = async (expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
    const act = actions => cmd('input.performActions', {context: ctx, actions});
    const mid = sel => ev(`(() => { const e = document.querySelector('${sel}'); if (!e) return null; const b = e.getBoundingClientRect(); return {x: b.left + b.width / 2, y: b.top + b.height / 2, w: b.width, l: b.left}; })()`);
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'frida', password: 'password123'})}).then(r => r.status)`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await nav(B + '#l/' + L);
    check(await ready(`!!document.querySelector('#view .lchead .lcg[data-lcg="f:${FT}"]') && !!document.querySelector('#tc-${T[7]}')`), 'Firefox: the private list with columns');
    await sleep(400);
    const K = `f:${FT}`, rowW = `document.querySelector('#tc-${T[3]} .lc[data-k="${K}"]').getBoundingClientRect().width`;
    const g = await mid(`.lchead .lcg[data-lcg="${K}"]`), h0 = await mid(`.lchead .lc[data-k="${K}"]`), r0 = await ev(rowW);
    check(Math.abs(h0.w - r0) <= 1, `title and rows start with the same width (${h0.w} / ${r0})`);
    // press, move 60 px to the left in a few steps, keep the button down
    await act([{type: 'pointer', id: 'p1', parameters: {pointerType: 'mouse'}, actions: [{type: 'pointerMove', x: Math.round(g.x), y: Math.round(g.y)}, {type: 'pointerDown', button: 0},
      ...[15, 30, 45, 60].map(d => ({type: 'pointerMove', x: Math.round(g.x - d), y: Math.round(g.y), duration: 30}))]}]);
    check(await ready(`Math.abs(document.querySelector('.lchead .lc[data-k="${K}"]').getBoundingClientRect().width - ${h0.w + 60}) <= 2`), '#3304: while dragging the column title follows the mouse');
    const mid1 = await ev(`(() => { const h = document.querySelector('.lchead .lc[data-k="${K}"]').getBoundingClientRect(), gl = document.querySelector('body > .lcguide');
      return {rw: ${rowW}, gx: gl ? parseFloat(gl.style.left) : null, hl: h.left, stored: localStorage.getItem('tasks.lcw.${L}'), style: document.getElementById('lcw-style')?.textContent || ''}; })()`);
    check(Math.abs(mid1.rw - r0) <= 1, `#3304: while dragging the rows keep their width (${r0} -> ${mid1.rw})`);
    check(mid1.gx != null && Math.abs(mid1.gx - (g.x - 60)) <= 2 && Math.abs(mid1.gx - (mid1.hl - (h0.l - g.x))) <= 2, `#3304: the guide line follows the column's left edge (${mid1.gx}, title from ${mid1.hl})`);
    check(!mid1.stored && !/data-k/.test(mid1.style), '#3304: nothing stored or applied to the rows before the release');
    await shot('p2331b-lcw-drag.png');
    await act([{type: 'pointer', id: 'p1', parameters: {pointerType: 'mouse'}, actions: [{type: 'pointerUp', button: 0}]}]);
    await cmd('input.releaseActions', {context: ctx});
    check(await ready(`!document.querySelector('body > .lcguide') && !document.body.classList.contains('pgdrag')`), 'the guide line is gone after the release');
    const end = await ev(`(() => { const h = document.querySelector('.lchead .lc[data-k="${K}"]'); return {hw: h.getBoundingClientRect().width, rw: ${rowW}, inline: h.style.width,
      w: (JSON.parse(localStorage.getItem('tasks.lcw.${L}') || '{}'))['${K}'] || 0, rem: parseFloat(getComputedStyle(document.documentElement).fontSize)}; })()`);
    check(Math.abs(end.hw - end.rw) <= 1 && Math.abs(end.rw - (r0 + 60)) <= 2, `#3304: after the release title and rows have the same new width (${end.hw} / ${end.rw}, was ${r0})`);
    check(!end.inline, '#3304: the title keeps no width of its own (the stored one applies)');
    check(Math.abs(end.w * end.rem - (h0.w + 60)) <= 2, `#3304: the width is stored for the list (${end.w} rem)`);
    // after a reload the stored width applies to title and rows
    await nav(B + '#l/' + L);
    check(await ready(`!!document.querySelector('#tc-${T[3]} .lc[data-k="${K}"]') && Math.abs(${rowW} - ${end.rw}) <= 1 && Math.abs(document.querySelector('.lchead .lc[data-k="${K}"]').getBoundingClientRect().width - ${end.rw}) <= 1`), '#3304: after a reload the stored width applies');
  }, false);

  console.log(`p2331_b_lcw_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
