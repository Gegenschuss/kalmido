// 2.543.0 part A UI test (#4611): tables on touch, own container (start.sh), Firefox with a touch screen (coarse pointer, touch
// kalmido-suite: fresh
// events, no hover) and once with a mouse. Invented names only.
// - writing a formula: a real finger tap on a cell puts its address in, a finger drawn over cells a range A2:B3 (the grid does not
//   scroll meanwhile); the field never loses its focus (no focusout), the cursor stays at the end of the reference
// - every reference its own colour: the box on the grid, the text in the cell's editor and in the formula bar the same colour; the
//   box a solid frame, the text underlined; the growing range is coloured while the finger is still down
// - cells 2rem high on touch like on a computer, the column as wide as on a computer
// - suggestions after "=": entries >= 44 px, the short help visible in the row; a tap puts SUM( in, the cursor in the bracket, the
//   field keeps its focus
// - a person without an organisation (freelancer-matrix: sheets): a tap on a named cell puts its name in, coloured
// - the mouse: the help stays a tooltip (no line), a click puts the address in, a drag a range
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2543A_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const firefox = require('./ff')({tag: 'p2543_a_ui', check, shots: 'P2543A_SHOTS'});

(async () => {
  await sleep(600);
  const r0 = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r0.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {org_name: 'Nordwind', lang: 'en', modules: ['comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'comments,sheets'});
  const S = await call(CA, 'POST', '/api/sheets', {title: 'Touch sheet'});
  check(S.http === 201, 'a table ' + S.http);
  await call(CA, 'PUT', `/api/sheets/${S.id}/cells`, {cells: [{cell: 'A1', raw: '1'}, {cell: 'A2', raw: '2'}, {cell: 'A3', raw: '3'}, {cell: 'B1', raw: '4'}, {cell: 'B2', raw: '5'}, {cell: 'B3', raw: '6'}]});
  // the freelancer: no organisation, an own table with a named cell
  const fr = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fr.http < 300, 'the freelancer ' + fr.http);
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'comments,sheets'});
  check(((await call(CF, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'frida is in no organisation');
  const SF = await call(CF, 'POST', '/api/sheets', {title: 'Frida sheet'});
  check(SF.http === 201, 'the freelancer has a table ' + SF.http);
  await call(CF, 'PUT', `/api/sheets/${SF.id}/cells`, {cells: [{cell: 'A1', raw: '10'}, {cell: 'B1', raw: '3'}]});
  const b1 = ((await call(CF, 'GET', `/api/sheets/${SF.id}`)).cells || []).find(c => c.addr === 'B1');
  const nm = b1 && await call(CF, 'POST', `/api/sheets/${SF.id}/cells/${b1.id}/name`, {name: 'rate'});
  check(nm && nm.http < 300, 'B1 is named "rate" ' + (nm && nm.http));

  // signed in on a plain file of the server, then the app loads fresh (no login screen of a first load left with the focus)
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  // the middle of a cell (viewport coordinates)
  const at = (ev, addr) => ev(`(() => { const sh = SHV.sh, col = sh.columns.find(c => c.letter === '${addr[0]}'), row = sh.rows[${+addr.slice(1)} - 1];
    const td = document.getElementById('shv-c-' + row.id + '-' + col.id), sc = document.getElementById('shv-scroll'), o = sc.getBoundingClientRect();
    let r = td.getBoundingClientRect();
    if (r.left < o.left + 48 || r.right > o.right) { sc.scrollLeft += r.left - o.left - 48; r = td.getBoundingClientRect(); }  // in view beside the sticky row numbers
    const x = Math.round(r.left + r.width / 2), y = Math.round(r.top + r.height / 2), h = document.elementFromPoint(x, y);
    return {x, y, hit: !!h && td.contains(h), on: h ? h.tagName + '#' + h.id + '.' + h.className : ''}; })()`);
  const tap = async ({cmd, ctx}, p, kind = 'touch') => {
    if (p.hit === false) check(false, 'the pointer would hit something else: ' + p.on);
    await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'f1', parameters: {pointerType: kind}, actions: [{type: 'pointerMove', x: p.x, y: p.y}, {type: 'pointerDown', button: 0}, {type: 'pointerUp', button: 0}]}]});
    await cmd('input.releaseActions', {context: ctx});
  };
  // a finger (or the mouse) down on a, resting a moment, drawn to b, still down (up: lift it)
  const press = ({cmd, ctx}, a, b, kind) => cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'f1', parameters: {pointerType: kind}, actions: [{type: 'pointerMove', x: a.x, y: a.y}, {type: 'pointerDown', button: 0}, {type: 'pause', duration: 150},
    {type: 'pointerMove', x: Math.round((a.x + b.x) / 2), y: Math.round((a.y + b.y) / 2), duration: 120}, {type: 'pointerMove', x: b.x, y: b.y, duration: 120}]}]});
  const move = ({cmd, ctx}, b, kind) => cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'f1', parameters: {pointerType: kind}, actions: [{type: 'pointerMove', x: b.x, y: b.y, duration: 120}]}]});
  const lift = async ({cmd, ctx}, kind) => { await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'f1', parameters: {pointerType: kind}, actions: [{type: 'pointerUp', button: 0}]}]}); await cmd('input.releaseActions', {context: ctx}); };
  // edit the cell addr with this text (the editor focused, the cursor at its end), count the editor's focus losses from now on
  const edit = (ev, addr, text) => ev(`(() => { const sh = SHV.sh, col = sh.columns.find(c => c.letter === '${addr[0]}'), row = sh.rows[${+addr.slice(1)} - 1];
    if (SHV.ed) shvEditEnd(false); shvSelect(row.id, col.id); shvEditStart(${JSON.stringify(text)});
    window.__fo = 0; window.__md = 0; if (!window.__foOn) { window.__foOn = 1; document.addEventListener('focusout', e => { if (e.target.id === 'shv-ed') window.__fo++; }, true);
      for (const t of ['mousedown', 'click']) window.addEventListener(t, () => { window.__md++; }, true); }  // the emulated mouse of a touch (it moves the focus on phones)
    return document.activeElement?.id; })()`);
  const typed = (ev, v) => ev(`(() => { const i = document.getElementById('shv-ed'); i.value = ${JSON.stringify(v)}; i.setSelectionRange(i.value.length, i.value.length); i.dispatchEvent(new Event('input', {bubbles: true})); return i.value; })()`);
  const state = ev => ev(`(() => { const i = document.getElementById('shv-ed'), b = document.getElementById('shv-in');
    const col = el => el ? getComputedStyle(el).color : null;
    const toks = s => [...document.querySelectorAll(s + ' .shvrt')].map(x => ({t: x.textContent, c: col(x), u: getComputedStyle(x).textDecorationLine}));
    const sc = document.getElementById('shv-scroll');
    return {v: i?.value, pos: i?.selectionStart, active: document.activeElement?.id, fo: window.__fo, md: window.__md, ed: !!SHV.ed,
      inpColor: col(i), caret: i ? getComputedStyle(i).caretColor : null, bar: b?.value,
      cell: toks('.shvc.editing'), barT: toks('.shvinw'), sx: sc.scrollLeft, sy: sc.scrollTop,
      boxes: [...document.querySelectorAll('#shv-scroll > .shvrb')].map(x => { const s = getComputedStyle(x), r = x.getBoundingClientRect(); return {ref: x.dataset.ref, c: s.borderTopColor, st: s.borderTopStyle, l: Math.round(r.left), t: Math.round(r.top), r: Math.round(r.right), b: Math.round(r.bottom)}; })}; })()`);
  const rect = (ev, addr) => ev(`(() => { const sh = SHV.sh, col = sh.columns.find(c => c.letter === '${addr[0]}'), row = sh.rows[${+addr.slice(1)} - 1];
    const r = document.getElementById('shv-c-' + row.id + '-' + col.id).getBoundingClientRect(); return {l: Math.round(r.left), t: Math.round(r.top), r: Math.round(r.right), b: Math.round(r.bottom)}; })()`);
  const near = (a, b) => Math.abs(a - b) <= 2;

  // ---- touch (a tablet in landscape, 1180 x 820)
  await firefox(async o => {
    const {cmd, ev, ctx, nav, until, shot} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1180, height: 820}});
    await nav(B + 'static/icon.svg'); check(await signIn(ev, 'alice') === 200, 'touch: login');
    await nav(B + '#sheets/' + S.id);
    check(await until(`typeof SHV !== 'undefined' && SHV.sh?.id === ${S.id} && !!document.querySelector('#shv-scroll td.shvc')`), 'touch: the table is open');
    check(await ev(`matchMedia('(hover: none)').matches && matchMedia('(pointer: coarse)').matches && isTouch()`), 'touch: the browser is a touch screen');

    // cells as compact as on a computer
    const sz = await ev(`(() => { const td = document.querySelector('#shv-scroll td.shvc'), rem = parseFloat(getComputedStyle(document.documentElement).fontSize), c = SHV.sh._col.get(+td.dataset.c);
      return {h: td.getBoundingClientRect().height, w: td.getBoundingClientRect().width, want: shvW(c) / 16 * rem, rem, hd: document.querySelector('#shv-scroll .shvchb').getBoundingClientRect().height}; })()`);
    check(Math.abs(sz.h - 2 * sz.rem) <= 1.5 && Math.abs(sz.hd - 2 * sz.rem) <= 1.5, 'touch: cells and column heads are 2rem high ' + JSON.stringify(sz));
    check(Math.abs(sz.w - sz.want) <= 2, 'touch: the column is as wide as on a computer ' + JSON.stringify(sz));

    // a tap on a cell while writing a formula
    { const a = await edit(ev, 'C1', '=SUM('); check(a === 'shv-ed', 'touch: the cell editor has the focus ' + a); }
    await tap(o, await at(ev, 'A1'));
    check(await until(`document.getElementById('shv-ed')?.value === '=SUM(A1'`), 'touch: a tap on A1 puts its address in ' + JSON.stringify(await state(ev)));
    let s = await state(ev);
    check(s.active === 'shv-ed' && s.fo === 0 && s.ed && s.pos === 7, 'touch: the field keeps the focus and the cursor behind A1 ' + JSON.stringify(s));
    check(s.md === 0, 'touch: the tap on the cell is done with the finger, no emulated mouse follows (it would take the focus on a phone) ' + s.md);
    check(s.bar === '=SUM(A1', 'touch: the formula bar shows the same text ' + s.bar);
    const box = s.boxes.find(b => b.ref === 'A1'), ra1 = await rect(ev, 'A1');
    check(box && near(box.l, ra1.l) && near(box.t, ra1.t) && near(box.r, ra1.r) && near(box.b, ra1.b) && box.st === 'solid', 'touch: A1 has a solid frame ' + JSON.stringify([box, ra1]));
    check(box && s.cell[0]?.t === 'A1' && s.cell[0].c === box.c && s.barT[0]?.t === 'A1' && s.barT[0].c === box.c, 'touch: frame, cell text and bar text of A1 in one colour ' + JSON.stringify(s));
    check(s.cell[0]?.u.includes('underline') && s.barT[0]?.u.includes('underline'), 'touch: the reference text is underlined (not only colour)');
    check(s.inpColor === 'rgba(0, 0, 0, 0)' && s.caret && s.caret !== 'rgba(0, 0, 0, 0)', 'touch: the field\'s own text is transparent, the cursor visible ' + s.inpColor + ' ' + s.caret);

    // a finger drawn over cells: a range, coloured while it grows, no scrolling
    await typed(ev, '=SUM(A1;');
    for (const x of ['A2', 'B3']) await at(ev, x);  // both in view first, then their places (a later scroll would move the earlier ones)
    const a2 = await at(ev, 'A2'), b2 = await at(ev, 'B2'), b3 = await at(ev, 'B3'), s0 = await state(ev);
    check(a2.hit && b2.hit && b3.hit, 'touch: A2, B2 and B3 are on screen ' + JSON.stringify([a2, b2, b3]));
    await ev(`(() => { window.__pl = []; for (const t of ['pointerdown', 'pointermove', 'pointerup', 'pointercancel', 'touchstart', 'touchmove', 'touchend']) document.addEventListener(t, e => { const p = e.touches ? e.changedTouches[0] : e; const td = shvTdOf(document.elementFromPoint(p.clientX, p.clientY)); window.__pl.push(t + '@' + Math.round(p.clientX) + ',' + Math.round(p.clientY) + (td ? ':' + shvAddr(+td.dataset.r, +td.dataset.c) : '') + (t === 'pointerdown' ? ' v=' + document.getElementById('shv-ed')?.value : '')); }, true); return 1; })()`);
    await press(o, a2, b2, 'touch');
    check(await until(`document.getElementById('shv-ed')?.value === '=SUM(A1;A2:B2'`), 'touch: the finger on its way: A2:B2 ' + (await state(ev)).v + ' ' + JSON.stringify([a2, b2, await ev('window.__pl.slice(0, 12)')]));
    s = await state(ev);
    const grow = s.boxes.find(b => b.ref === 'A2:B2');
    check(grow && grow.c !== s.boxes.find(b => b.ref === 'A1')?.c, 'touch: the growing range already has its own colour ' + JSON.stringify(s.boxes));
    await move(o, b3, 'touch');
    await lift(o, 'touch');
    check(await until(`document.getElementById('shv-ed')?.value === '=SUM(A1;A2:B3'`), 'touch: drawn from A2 to B3: the range A2:B3 ' + (await state(ev)).v);
    s = await state(ev);
    const rg = s.boxes.find(b => b.ref === 'A2:B3'), q0 = await rect(ev, 'A2'), q1 = await rect(ev, 'B3');
    check(rg && near(rg.l, q0.l) && near(rg.t, q0.t) && near(rg.r, q1.r) && near(rg.b, q1.b), 'touch: the frame spans A2 to B3 ' + JSON.stringify([rg, q0, q1]));
    check(s.boxes.length === 2 && s.cell.length === 2 && s.cell[1].t === 'A2:B3' && s.cell[1].c === rg?.c && s.barT[1]?.c === rg?.c, 'touch: the range\'s text in its colour in cell and bar ' + JSON.stringify(s));
    check(s.active === 'shv-ed' && s.fo === 0 && s.pos === s.v.length, 'touch: after the drag the field still has the focus and the cursor ' + JSON.stringify(s));
    check(s.sx === s0.sx && s.sy === s0.sy, 'touch: the grid did not scroll during the drag ' + JSON.stringify([s0.sx, s0.sy, s.sx, s.sy]));
    await shot('p2543a-touch-refs.png');
    // a tap after the drag does not shrink the range by its late click: a new reference needs an operator
    await typed(ev, '=SUM(A1;A2:B3)');
    check(!(await ev(`document.getElementById('shv-scroll').classList.contains('shvfx')`)), 'touch: behind ")" no reference goes in (the grid scrolls again)');
    await ev(`(() => { shvEditEnd(true); return 1; })()`);
    check(await until(async () => ((await call(CA, 'GET', `/api/sheets/${S.id}`)).cells || []).find(c => c.addr === 'C1')?.value === 17), 'touch: the formula saved: 1 + 16 = 17');
    check(await ev(`!document.querySelector('#shv-scroll > .shvrb') && !document.querySelector('.shvmir')`), 'touch: after the edit no frames and no mirror are left');

    // suggestions on touch
    await edit(ev, 'C2', '=SU');
    check(await until(`[...document.querySelectorAll('#shv-ac code')].some(c => c.textContent === 'SUM')`), 'touch: "=SU" suggests SUM');
    const ac = await ev(`(() => { const bs = [...document.querySelectorAll('#shv-ac button')], b = bs.find(x => x.querySelector('code').textContent === 'SUM'), h = b?.querySelector('.shvach');
      return {min: Math.min(...bs.map(x => x.getBoundingClientRect().height)), help: h ? h.textContent : '', shown: !!h && getComputedStyle(h).display !== 'none' && h.getBoundingClientRect().height > 0}; })()`);
    check(ac.min >= 44, 'touch: every suggestion is at least 44 px high ' + JSON.stringify(ac));
    check(ac.shown && ac.help.length > 3, 'touch: the short help of SUM is visible in its row ' + JSON.stringify(ac));
    await shot('p2543a-touch-suggest.png');
    const p = await ev(`(() => { const b = [...document.querySelectorAll('#shv-ac button')].find(x => x.querySelector('code').textContent === 'SUM'); b.scrollIntoView({block: 'nearest'}); const r = b.querySelector('code').getBoundingClientRect(); return {x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2)}; })()`);
    await tap(o, p);
    check(await until(`document.getElementById('shv-ed')?.value === '=SUM('`), 'touch: a tap on the suggestion puts SUM( in ' + (await state(ev)).v);
    s = await state(ev);
    check(s.active === 'shv-ed' && s.fo === 0 && s.pos === 5 && s.ed, 'touch: the field keeps the focus, the cursor in the bracket ' + JSON.stringify(s));
    check(s.md === 0, 'touch: the suggestion is picked when the finger lifts, no emulated mouse follows ' + s.md);
    check(await ev(`!document.getElementById('shv-ac')`), 'touch: the suggestions closed');
    // the help line is in the list's markup only once per entry, and the tooltip stays for a mouse
    check(await ev(`document.querySelector('.shvach') === null`), 'touch: the closed list leaves no help line behind');
    await ev(`(() => { shvEditEnd(false); return 1; })()`);
  }, true);

  // ---- the freelancer (touch): a named cell goes in by its name, coloured
  await firefox(async o => {
    const {cmd, ev, ctx, nav, until} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1180, height: 820}});
    await nav(B + 'static/icon.svg'); check(await signIn(ev, 'frida') === 200, 'freelancer: login');
    await nav(B + '#sheets/' + SF.id);
    check(await until(`typeof SHV !== 'undefined' && SHV.sh?.id === ${SF.id} && !!document.querySelector('#shv-scroll td.shvc')`), 'freelancer: the own table is open');
    await edit(ev, 'C1', '=A1*');
    await tap(o, await at(ev, 'B1'));
    check(await until(`document.getElementById('shv-ed')?.value === '=A1*rate'`), 'freelancer: a tap on the named B1 puts "rate" in ' + (await state(ev)).v);
    const s = await state(ev), ra = await rect(ev, 'B1'), bx = s.boxes.find(b => b.ref === 'B1');
    check(s.active === 'shv-ed' && s.fo === 0, 'freelancer: the field keeps the focus ' + JSON.stringify(s));
    check(s.boxes.length === 2 && bx && near(bx.l, ra.l) && near(bx.t, ra.t), 'freelancer: A1 and the named B1 framed ' + JSON.stringify(s.boxes));
    check(s.cell.length === 2 && s.cell[1].t === 'rate' && s.cell[1].c === bx?.c && s.cell[0].c !== s.cell[1].c, 'freelancer: "rate" in the colour of its frame, A1 in another ' + JSON.stringify(s.cell));
    await ev(`(() => { shvEditEnd(true); return 1; })()`);
    check(await until(async () => ((await call(CF, 'GET', `/api/sheets/${SF.id}`)).cells || []).find(c => c.addr === 'C1')?.value === 30), 'freelancer: the formula saved: 30');
  }, true);

  // ---- the mouse: the help stays a tooltip; click = address, drag = range; dark theme colours differ from light
  await firefox(async o => {
    const {cmd, ev, ctx, nav, until} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 800}});
    await nav(B + 'static/icon.svg'); check(await signIn(ev, 'alice') === 200, 'mouse: login');
    await nav(B + '#sheets/' + S.id);
    check(await until(`typeof SHV !== 'undefined' && SHV.sh?.id === ${S.id} && !!document.querySelector('#shv-scroll td.shvc')`), 'mouse: the table is open');
    check(await ev(`!isTouch()`), 'mouse: no touch screen');
    await edit(ev, 'C3', '=SU');
    check(await until(`[...document.querySelectorAll('#shv-ac code')].some(c => c.textContent === 'SUM')`), 'mouse: "=SU" suggests SUM');
    check(await ev(`(() => { const b = [...document.querySelectorAll('#shv-ac button')].find(x => x.querySelector('code').textContent === 'SUM'), h = b.querySelector('.shvach'); return !!b.title && (!h || getComputedStyle(h).display === 'none'); })()`), 'mouse: the help is a tooltip, no line');
    await typed(ev, '=SUM(');
    await ev(`(() => { shvAcClose(); return 1; })()`);
    await tap(o, await at(ev, 'B1'), 'mouse');
    check(await until(`document.getElementById('shv-ed')?.value === '=SUM(B1'`), 'mouse: a click puts B1 in ' + (await state(ev)).v);
    await typed(ev, '=SUM(B1;');
    await press(o, await at(ev, 'A1'), await at(ev, 'A3'), 'mouse'); await lift(o, 'mouse');
    check(await until(`document.getElementById('shv-ed')?.value === '=SUM(B1;A1:A3'`), 'mouse: a drag puts the range A1:A3 in ' + (await state(ev)).v);
    const s = await state(ev);
    check(s.active === 'shv-ed' && s.fo === 0 && s.boxes.length === 2 && s.boxes[0].c !== s.boxes[1].c, 'mouse: focus kept, two frames in two colours ' + JSON.stringify(s));
    const pal = await ev(`(() => { const w = document.querySelector('.shvwrap'), g = () => getComputedStyle(w).getPropertyValue('--shr0').trim(); const root = document.documentElement, t0 = root.dataset.theme;
      root.dataset.theme = 'light'; const l = g(); root.dataset.theme = 'dark'; const d = g(); root.dataset.theme = t0; return {l, d}; })()`);
    check(pal.l && pal.d && pal.l !== pal.d, 'mouse: the colours have a light and a dark set ' + JSON.stringify(pal));
    await ev(`(() => { shvEditEnd(false); return 1; })()`);
  }, false);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
