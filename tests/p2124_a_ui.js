// 2.124.0 part A UI test (#2109 #2115), own container (start.sh), jsdom. Invented names only.
// - a formula with a new function typed into the grid shows its result (SUMMEWENN), a lookup that finds nothing reads "Not found"
// - the completion after "=" offers SVERWEIS
// - the table's menu "Chart…": the dialog (kind, labels, numbers), saving draws an SVG with one bar per row (one undo step:
//   Undo removes it again, Redo brings it back), a changed cell redraws the bar, a tap on a bar shows its values
// - line chart with two series: a legend; hide / show; a reader sees the chart without the edit button
// - without a chart the table looks as before (no chart box); sizes in rem; no script errors
// - Firefox: bars with two series in light and dark, the phone (the chart scrolls inside); screenshots with P2124A_SHOTS=<dir>
// P2124A_NOSTART=1 = the server already runs.
const path = require('path');
const fs = require('fs');
const {execFileSync} = require('child_process');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2124A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j._status = r.status; return j; };
const FEAT = 'collab,comments,sheets';
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { try { if (await fn()) return true; } catch { /* not yet */ } await sleep(150); } return false; };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const key = (w, el, k, o = {}) => el && el.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true, ...o}));
const firefox = require('./ff')({tag: 'p2124_a_ui', check, shots: 'P2124A_SHOTS'});
const item = (d, re) => [...d.querySelectorAll('[role="menuitem"]')].find(b => re.test(b.textContent));

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  const CAROL = (await call('POST', '/api/users', {orgs: [ORG], username: 'carol', display_name: 'Carol', password: 'password123', email: 'carol@example.com'})).id;
  const CC = await login('carol');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, CC);

  // ---- static: the chart's styles in rem, no px but hairlines
  const css = fs.readFileSync(path.join(__dirname, '..', 'static', 'css', 'sheets.css'), 'utf8');
  const part = css.slice(css.indexOf('#2115'));
  // 2.139.1 (#2372): media-query breakpoints are not style sizes, later rules in the sheet use them
  const px = (part.replace(/\/\*[\s\S]*?\*\//g, '').replace(/@media[^{]*\{/g, '{').match(/(\d+(\.\d+)?)px/g) || []).filter(x => parseFloat(x) > 2);
  check(part.length > 100 && !px.length, 'chart styles: rem only ' + px.slice(0, 3));

  const L = (await call('POST', '/api/lists', {name: 'Harvest', org_id: ORG})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: CAROL, role: 'view'});
  const S = await call('POST', '/api/sheets', {title: 'Harvest', space: `org:${ORG}`, list_id: L});
  check(S._status === 201 && S.chart === null, 'a table without a chart ' + JSON.stringify(S).slice(0, 120));
  const SID = S.id, R = S.rows.map(r => r.id), C = S.columns.map(c => c.id);
  await call('PUT', `/api/sheets/${SID}/cells`, {cells: [{cell: 'A1', raw: 'Apples'}, {cell: 'A2', raw: 'Pears'}, {cell: 'A3', raw: 'apples'},
    {cell: 'B1', raw: '4'}, {cell: 'B2', raw: '9'}, {cell: 'B3', raw: '6'}]});

  let w = await boot({user: 'alice', hash: 'sheets/' + SID}), d = w.document;
  check(await until(() => d.querySelector('#shv-scroll td.shvc')), 'the table is open');
  check(!d.getElementById('shc-box'), 'no chart: no chart box (the view as before)');
  const td = (r, c) => d.getElementById(`shv-c-${r}-${c}`);
  const sc = () => d.getElementById('shv-scroll');
  const cellOf = (sh, addr) => (sh.cells || []).find(c => c.addr === addr);

  // ---- a new function typed into the grid
  w.eval(`shvSelect(${R[4]}, ${C[2]})`); sc().focus();
  key(w, sc(), '=');
  let ed = d.getElementById('shv-ed');
  check(await until(() => d.querySelector('#shv-ac button[data-shvac]')), 'after "=" the suggestions open');
  ed.value = '=SVER'; ed.setSelectionRange(5, 5); ed.dispatchEvent(new w.Event('input', {bubbles: true}));
  check(await until(() => [...d.querySelectorAll('#shv-ac code')].some(c => c.textContent === 'SVERWEIS')), 'typing SVER suggests SVERWEIS');
  key(w, ed, 'Escape');
  ed.value = '=SUMMEWENN(A1:A3;"apples";B1:B3)'; ed.dispatchEvent(new w.Event('input', {bubbles: true})); key(w, ed, 'Enter');
  check(await until(async () => cellOf(await call('GET', `/api/sheets/${SID}`), 'C5')?.value === 10), 'SUMMEWENN typed in: saved = 10');
  check(await until(() => /10/.test(td(R[4], C[2])?.textContent || '')), 'the cell shows 10 ' + td(R[4], C[2])?.textContent);
  w.eval(`shvSelect(${R[5]}, ${C[2]})`); sc().focus();
  key(w, sc(), '='); ed = d.getElementById('shv-ed');
  ed.value = '=SVERWEIS("Plums";A1:B3;2)'; ed.dispatchEvent(new w.Event('input', {bubbles: true})); key(w, ed, 'Enter');
  check(await until(() => /Not found/.test(td(R[5], C[2])?.textContent || '')), 'a lookup that finds nothing: "Not found" ' + td(R[5], C[2])?.textContent);

  // ---- the chart from the menu
  click(w, d.querySelector('[data-shv="menu"]'));
  check(await until(() => item(d, /Chart…/)), 'the menu offers "Chart…"');
  click(w, item(d, /Chart…/));
  check(await until(() => d.querySelector('.modal .shc-ys')), 'the chart dialog opens');
  let md = d.querySelector('.modal');
  check(md.querySelector('input[name="shc-t"][value="bar"]').checked, 'bars by default');
  md.querySelector('#shc-x').value = String(C[0]);
  md.querySelectorAll('.shc-ys input').forEach(i => { i.checked = +i.value === C[1]; });
  click(w, md.querySelector('[data-m="save"]'));
  check(await until(() => d.querySelectorAll('#shc-box svg.shc-svg path.shc-s0').length === 3), 'saved: an SVG with three bars ' + d.getElementById('shc-box')?.innerHTML.slice(0, 200));
  check((await call('GET', `/api/sheets/${SID}`)).chart?.y?.[0] === C[1], 'the setting is stored');
  check(/Apples/.test(d.querySelector('#shc-box svg.shc-svg').textContent) && /Pears/.test(d.querySelector('#shc-box svg.shc-svg').textContent), 'the labels from column A');
  // one undo step: Undo removes the chart, Redo brings it back
  await w.eval(`histStep('undo')`);
  check(await until(async () => (await call('GET', `/api/sheets/${SID}`)).chart === null && !d.getElementById('shc-box')), 'undo: no chart again');
  await w.eval(`histStep('redo')`);
  check(await until(async () => (await call('GET', `/api/sheets/${SID}`)).chart?.y?.[0] === C[1] && d.getElementById('shc-box')), 'redo: the chart is back');
  const bar = () => [...d.querySelectorAll('#shc-box path.shc-s0')].map(p => p.getAttribute('d'));
  const before = bar().join('|');
  // a changed cell redraws the chart
  w.eval(`shvSelect(${R[1]}, ${C[1]})`); sc().focus();
  key(w, sc(), '2'); key(w, d.getElementById('shv-ed'), 'Enter');
  check(await until(() => bar().join('|') !== before), 'changing B2 redraws the bars');
  // a tap on a bar: its values
  click(w, d.querySelector('#shc-box .shc-hit[data-shc-i="1"]'));
  check(await until(() => !d.getElementById('shc-tip').hidden && /Pears/.test(d.getElementById('shc-tip').textContent)), 'a tap shows the values ' + d.getElementById('shc-tip')?.textContent);

  // ---- a line with two series: a legend
  click(w, d.querySelector('#shc-box [data-shc="edit"]'));
  check(await until(() => d.querySelector('.modal .shc-ys')), 'the edit button opens the dialog');
  md = d.querySelector('.modal');
  md.querySelector('input[name="shc-t"][value="line"]').checked = true;
  md.querySelector('input[name="shc-t"][value="bar"]').checked = false;
  md.querySelectorAll('.shc-ys input').forEach(i => { i.checked = [C[1], C[2]].includes(+i.value); });
  click(w, md.querySelector('[data-m="save"]'));
  check(await until(() => d.querySelectorAll('#shc-box path.shc-ln').length === 2 && d.querySelectorAll('#shc-box .shc-leg li').length === 2), 'a line chart with two lines and a legend');
  // hide / show
  click(w, d.querySelector('#shc-box [data-shc="hide"]'));
  check(!d.getElementById('shc-box'), 'hidden');
  click(w, d.querySelector('[data-shv="menu"]'));
  check(await until(() => item(d, /Show chart/)), 'the menu offers "Show chart"');
  click(w, item(d, /Show chart/));
  check(await until(() => d.getElementById('shc-box')), 'shown again');
  check(errs.length === 0, 'no JS errors: ' + errs.slice(0, 3).join(' | '));

  // ---- a reader sees the chart, without the edit button
  w = await boot({user: 'carol', hash: 'sheets/' + SID}); d = w.document;
  check(await until(() => d.querySelector('#shc-box svg.shc-svg')), 'the reader sees the chart');
  check(!d.querySelector('#shc-box [data-shc="edit"]'), 'no edit button for a reader');
  click(w, d.querySelector('[data-shv="menu"]'));
  await sleep(300);
  check(!item(d, /Chart…|Edit chart/), 'no chart entry in a reader\'s menu');
  check(errs.length === 0, 'no JS errors: ' + errs.slice(0, 3).join(' | '));

  // ---- Firefox: the real look (bars, two series, a legend), light / dark, the phone
  await call('PUT', `/api/sheets/${SID}/cells`, {cells: [{cell: 'A4', raw: 'Plums'}, {cell: 'A5', raw: 'Quinces'}, {cell: 'B4', raw: '-3'}, {cell: 'B5', raw: '12'},
    {cell: 'C1', raw: '3'}, {cell: 'C2', raw: '5'}, {cell: 'C3', raw: '=B3*1,5'}, {cell: 'C4', raw: '2'}, {cell: 'C5', raw: '=SUMMEWENN(A1:A3;"apples";B1:B3)'}]});
  await call('PUT', `/api/sheets/${SID}/chart`, {chart: {type: 'bar', x: C[0], y: [C[1], C[2]]}});
  const ffLogin = async ({ev, nav}, theme) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"${theme}"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const look = async (o, vw, vh, theme) => {
    const {cmd, ev, nav, shot} = o, tag = `${vw} ${theme}`;
    await cmd('browsingContext.setViewport', {context: o.ctx, viewport: {width: vw, height: vh}});
    check(await ffLogin(o, theme) === 200, tag + ': login');
    await nav(B + '#sheets/' + SID);
    for (let i = 0; i < 40 && !(await ev(`!!document.querySelector('#shc-box svg.shc-svg')`).catch(() => false)); i++) await sleep(250);
    await sleep(400);
    const x = await ev(`(() => { const b = document.querySelector('#shc-box'), s = b && b.querySelector('.shc-scroll'), p = b && b.querySelector('path.shc-s0'), q = b && b.querySelector('path.shc-s1');
      return {box: !!b, bw: b ? Math.round(b.getBoundingClientRect().width) : 0, sw: s ? Math.round(s.getBoundingClientRect().width) : 0, vw: innerWidth,
        f0: p && getComputedStyle(p).fill, f1: q && getComputedStyle(q).fill, acc: getComputedStyle(document.documentElement).getPropertyValue('--accent').trim(),
        bars: b ? b.querySelectorAll('path.shc-s0, path.shc-s1').length : 0, leg: b ? b.querySelectorAll('.shc-leg li').length : 0}; })()`);
    check(x && x.box && x.bars === 10 && x.leg === 2, `${tag}: bars of two series and a legend ` + JSON.stringify(x));
    check(x && x.f0 && x.f1 && x.f0 !== x.f1, `${tag}: the series differ in colour ` + JSON.stringify(x));
    check(x && x.bw <= x.vw && x.sw <= x.vw, `${tag}: the chart stays inside the screen (scrolls inside) ` + JSON.stringify(x));
    await ev(`(() => { const h = document.querySelector('#shc-box .shc-hit[data-shc-i="1"]'); h && h.dispatchEvent(new MouseEvent('click', {bubbles: true})); return 1; })()`);
    await sleep(300);
    await shot(`p2124a-${vw}-${theme}.png`);
  };
  await firefox(async o => { await look(o, 1280, 800, 'light'); await look(o, 1280, 800, 'dark'); }, false);
  await firefox(async o => { await look(o, 390, 844, 'dark'); }, true);

  check(errs.length === 0, 'no JS errors at the end: ' + errs.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
