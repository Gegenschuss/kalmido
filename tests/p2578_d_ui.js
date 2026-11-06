// 2.578.0 part D UI test (#3462), own container (start.sh), jsdom + Firefox. Invented names only.
// kalmido-suite: fresh
// - charts: a pie draws one part per row with a number above zero, every second part hatched, a legend with value and share;
//   a tap on a part (or its legend line) shows its values; a ring has the total in the middle; stacked bars draw one segment
//   per series and row, the legend keys of hatched series are hatched; the dialog offers the five kinds and refuses a pie
//   with two columns (the hint, nothing saved)
// - the print dialog ("Print / PDF…" in the table's menu): portrait / landscape, the options, "Selection" only with selected
//   cells; "Show PDF" sends the options and the shown rows / the selection and opens the PDF view; "Browser print" is the
//   quick print of 2.124.0
// - Firefox: pie and stacked bars in light and dark (the parts differ, the hatching is drawn); screenshots with P2578D_SHOTS=<dir>
// P2578D_NOSTART=1 = the server already runs.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2578D_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j._status = r.status; return j; };
const FEAT = 'collab,comments,sheets';
const until = (fn, n) => require('./boot').until(async () => { try { return await fn(); } catch { return false; } }, {timeout: n ? n * 150 : 15000, step: 150});
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const firefox = require('./ff')({tag: 'p2578_d_ui', check, shots: 'P2578D_SHOTS'});
const item = (d, re) => [...d.querySelectorAll('[role="menuitem"]')].find(b => re.test(b.textContent));

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  const S = await call('POST', '/api/sheets', {title: 'Harvest', space: `org:${ORG}`});
  const SID = S.id, R = S.rows.map(r => r.id), C = S.columns.map(c => c.id);
  await call('PUT', `/api/sheets/${SID}/cells`, {cells: [{cell: 'A1', raw: 'Apples'}, {cell: 'A2', raw: 'Pears'}, {cell: 'A3', raw: 'Plums'},
    {cell: 'A4', raw: 'Quinces'}, {cell: 'A5', raw: 'Figs'}, {cell: 'B1', raw: '40'}, {cell: 'B2', raw: '30'}, {cell: 'B3', raw: '20'},
    {cell: 'B4', raw: '10'}, {cell: 'B5', raw: '0'}, {cell: 'C1', raw: '5'}, {cell: 'C2', raw: '-2'}, {cell: 'C3', raw: '7'}, {cell: 'C4', raw: '1'}]});
  check((await call('PUT', `/api/sheets/${SID}/chart`, {chart: {type: 'pie', x: C[0], y: [C[1]]}}))._status === 200, 'a pie chart is set');

  let w = await boot({user: 'alice', hash: 'sheets/' + SID}), d = w.document;
  check(await until(() => d.querySelector('#shc-box svg.shc-pie')), 'the pie is drawn');
  const parts = () => [...d.querySelectorAll('#shc-box svg.shc-pie path.shc-sl')];
  check(parts().length === 4, 'one part per row with a number above zero (the 0 of Figs left out) ' + parts().length);
  check(d.querySelectorAll('#shc-box svg.shc-pie path.shc-hatch').length === 2 && d.querySelector('#shc-box pattern'), 'every second part hatched');
  const leg = [...d.querySelectorAll('#shc-box .shc-pleg li')];
  check(leg.length === 4 && /Apples/.test(leg[0].textContent) && /40%/.test(leg[0].textContent.replace(/\s/g, '')), 'the legend: label, value and share ' + leg[0]?.textContent);
  check(leg[1].querySelector('.shc-key.shc-kh') && !leg[0].querySelector('.shc-key.shc-kh'), 'the legend key of a hatched part is hatched');
  click(w, d.querySelector('#shc-box .shc-slhit[data-shc-i="1"]'));
  check(await until(() => !d.getElementById('shc-tip').hidden && /Pears/.test(d.getElementById('shc-tip').textContent)), 'a tap on a part shows its values');
  click(w, leg[2]);
  check(await until(() => /Plums/.test(d.getElementById('shc-tip').textContent) && leg[2].classList.contains('on')), 'a tap on its legend line too');
  // the ring
  await call('PUT', `/api/sheets/${SID}/chart`, {chart: {type: 'donut', x: C[0], y: [C[1]]}});
  w = await boot({user: 'alice', hash: 'sheets/' + SID}); d = w.document;
  check(await until(() => d.querySelector('#shc-box svg.shc-pie .shc-total')), 'the ring is drawn with its total');
  check(/100/.test(d.querySelector('#shc-box .shc-total').textContent), 'the total in the middle ' + d.querySelector('#shc-box .shc-total')?.textContent);
  // stacked bars
  await call('PUT', `/api/sheets/${SID}/chart`, {chart: {type: 'stacked', x: C[0], y: [C[1], C[2]]}});
  w = await boot({user: 'alice', hash: 'sheets/' + SID}); d = w.document;
  check(await until(() => d.querySelector('#shc-box svg.shc-svg:not(.shc-pie)')), 'stacked bars are drawn');
  const s0 = d.querySelectorAll('#shc-box path.shc-s0').length, s1 = d.querySelectorAll('#shc-box path.shc-s1').length;
  check(s0 === 4 && s1 === 4, `a segment per series and row with a number (${s0} / ${s1})`);
  check(d.querySelectorAll('#shc-box path.shc-hatch').length === 4 && d.querySelector('#shc-box .shc-leg li:nth-child(2) .shc-kh'), 'the second series hatched, in the legend too');
  // the dialog: five kinds, a pie with two columns refused
  w.eval('shc_dialog(SHV.sh)');
  check(await until(() => d.querySelector('.modal .shc-kind')), 'the chart dialog opens');
  let md = d.querySelector('.modal');
  check(['bar', 'stacked', 'line', 'pie', 'donut'].every(k => md.querySelector(`input[name="shc-t"][value="${k}"]`)), 'five kinds');
  check(md.querySelector('input[name="shc-t"][value="stacked"]').checked, 'the stored kind is chosen');
  md.querySelector('input[name="shc-t"][value="pie"]').checked = true;
  click(w, md.querySelector('button[data-m="save"]'));
  check(await until(() => /one column/.test(d.getElementById('shc-err')?.textContent || '')), 'a pie with two columns: the hint');
  check((await call('GET', `/api/sheets/${SID}`)).chart.type === 'stacked', 'nothing saved');
  click(w, md.querySelector('button[data-m="close"]'));
  await until(() => !d.querySelector('.modal'));

  // ---- the print dialog
  w.eval(`window.__pv = []; pdfView = o => { window.__pv.push(o); }; loadModule = () => Promise.resolve();`);
  click(w, d.querySelector('[data-shv="menu"]'));
  check(await until(() => item(d, /Print \/ PDF/)), 'the menu offers "Print / PDF…"');
  click(w, item(d, /Print \/ PDF/));
  check(await until(() => d.querySelector('.modal.shpmd')), 'the print dialog opens');
  md = d.querySelector('.modal.shpmd');
  check(md.querySelector('input[name="shp-o"][value="portrait"]').checked && md.querySelector('input[name="shp-w"][value="sel"]').disabled, 'portrait, no selection: "Selection" is off');
  check(['fit', 'head', 'numbers'].every(k => md.querySelector(`input[data-shp="${k}"]`).checked), 'fit, header row, page numbers on by default');
  md.querySelector('input[name="shp-o"][value="landscape"]').checked = true;
  md.querySelector('input[data-shp="numbers"]').checked = false;
  // what the client sends: the request is watched, the server answers the PDF
  w.eval(`window.__req = []; const f0 = window.fetch; window.fetch = (u, o) => { if (String(u).includes('print.pdf')) window.__req.push(JSON.parse(o.body)); return f0(u, o); };`);
  click(w, md.querySelector('button[data-m="pdf"]'));
  check(await until(() => w.eval('window.__pv.length') === 1), 'Show PDF opens the PDF view');
  const req = w.eval('window.__req[0]'), pv = w.eval('window.__pv[0]');
  check(req && req.orient === 'landscape' && req.fit === true && req.head === true && req.numbers === false && req.rows === null && req.cols === null, 'the options and the whole sheet are sent ' + JSON.stringify(req));
  check(pv && pv.data && pv.data.length > 1000 && /Harvest\.pdf$/.test(pv.name), 'the PDF view gets the file ' + JSON.stringify({n: pv?.name, l: pv?.data?.length}));
  check(await until(() => !d.querySelector('.modal.shpmd')), 'the dialog closes');
  // a selection of cells: "Selection" is chosen and sent
  w.eval(`SHV.anc = {r: ${R[0]}, c: ${C[0]}}; SHV.cur = {r: ${R[1]}, c: ${C[1]}};`);
  w.eval('shp_dialog(SHV.sh)');
  check(await until(() => d.querySelector('.modal.shpmd')), 'the print dialog again');
  md = d.querySelector('.modal.shpmd');
  check(md.querySelector('input[name="shp-o"][value="landscape"]').checked, 'the last choice is kept');
  check(md.querySelector('input[name="shp-w"][value="sel"]').checked && /2 × 2/.test(md.textContent), 'the selection is offered and chosen (2 × 2 cells)');
  click(w, md.querySelector('button[data-m="pdf"]'));
  check(await until(() => w.eval('window.__pv.length') === 2), 'the PDF of the selection');
  await until(() => !d.querySelector('.modal.shpmd'));
  const req2 = w.eval('window.__req[1]');
  check(req2 && JSON.stringify(req2.rows) === JSON.stringify([R[0], R[1]]) && JSON.stringify(req2.cols) === JSON.stringify([C[0], C[1]]), 'the selection is sent ' + JSON.stringify(req2));
  // Browser print = the quick print view of 2.124.0
  w.eval('window.print = () => {};');
  w.eval('shp_dialog(SHV.sh)');
  check(await until(() => d.querySelector('.modal.shpmd')), 'the dialog for the browser print');
  click(w, d.querySelector('.modal.shpmd button[data-m="quick"]'));
  check(await until(() => d.getElementById('shk-print') && d.body.classList.contains('shkprint')), 'Browser print builds the quick print view');
  check(errs.length === 0, 'no JS errors: ' + errs.slice(0, 3).join(' | '));

  // ---- Firefox: pie and stacked bars, light and dark
  const ffLogin = async ({ev, nav}, theme) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"${theme}"'); localStorage.setItem('tasks.lookLocal', 'true'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const look = async (o, kind, theme) => {
    const {cmd, ev, nav, shot} = o, tag = `${kind} ${theme}`;
    await call('PUT', `/api/sheets/${SID}/chart`, {chart: kind === 'pie' ? {type: 'pie', x: C[0], y: [C[1]]} : {type: 'stacked', x: C[0], y: [C[1], C[2]]}});
    await cmd('browsingContext.setViewport', {context: o.ctx, viewport: {width: 1280, height: 800}});
    check(await ffLogin(o, theme) === 200, tag + ': login');
    await nav(B + '#sheets/' + SID);
    for (let i = 0; i < 40 && !(await ev(`!!document.querySelector('#shc-box svg.shc-svg')`).catch(() => false)); i++) await sleep(250);
    await sleep(400);
    const x = await ev(`(() => { const b = document.querySelector('#shc-box'), p = b && b.querySelector('path.shc-s0'), q = b && b.querySelector('path.shc-s1'), h = b && b.querySelector('path.shc-hatch');
      return {box: !!b, f0: p && getComputedStyle(p).fill, f1: q && getComputedStyle(q).fill, hatch: h ? h.getBBox().width : 0, vw: innerWidth, bw: b ? Math.round(b.getBoundingClientRect().width) : 0}; })()`);
    check(x && x.box && x.f0 && x.f1 && x.f0 !== x.f1, `${tag}: the parts differ in colour ` + JSON.stringify(x));
    check(x && x.hatch > 0, `${tag}: the hatching is drawn ` + JSON.stringify(x));
    check(x && x.bw <= x.vw, `${tag}: inside the screen ` + JSON.stringify(x));
    await shot(`p2578d-${kind}-${theme}.png`);
  };
  await firefox(async o => { await look(o, 'pie', 'light'); await look(o, 'pie', 'dark'); await look(o, 'stacked', 'light'); }, false);

  check(errs.length === 0, 'no JS errors at the end: ' + errs.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
