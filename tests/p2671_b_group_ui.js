// 2.671.0 part B UI test (#3463 a): tables grouped by one column with subtotals, own container (start.sh), Firefox, a mouse.
// kalmido-suite: fresh
// A person without an organisation (freelancer-matrix: sheets) groups her own table. Invented names only.
// - the column menu's "Group by this column": a head per group in the groups' order (text alphabetical, empty last), its number of rows
// - the subtotal row per group: sum by default, count / average chosen per column (an average of no numbers reads "–")
// - a head closes / opens its group (the rows leave / come back, the head and the subtotal stay)
// - the filter works first (only the rows that pass are grouped); a date column groups by month, the bar's menu by year
// - a selection groups in the order of its options; a write changes the subtotal at once
// - subtotal rows are no data rows: no cell ids, a double click does not edit, a click does not choose; the arrows skip them
// - while grouped rows are not moved (a hint); "Remove grouping" brings the plain table back
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2671BU_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const ffm = require('./ff');
const firefox = ffm({tag: 'p2671_b_ui', check, shots: 'P2671BU_SHOTS'});
const byPos = xs => (xs || []).slice().sort((a, b) => a.pos - b.pos).map(x => x.id);

(async () => {
  await sleep(600);
  const r0 = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r0.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {org_name: 'Nordwind', lang: 'en', modules: ['comments']});
  const fr = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fr.http < 300, 'the freelancer ' + fr.http);
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'comments,sheets'});
  check(((await call(CF, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'frida is in no organisation');

  // her table: A customer (text), B date, C amount (currency), D status (selection Open / Done); 10 rows, 6 filled
  const t = await call(CF, 'POST', '/api/sheets', {title: 'Invoices 2026'});
  check(t.http === 201, 'a table ' + t.http);
  const SID = t.id, s0 = await call(CF, 'GET', `/api/sheets/${SID}`), C0 = byPos(s0.columns), R = byPos(s0.rows);
  check(C0.length === 3 && R.length >= 6, 'three columns, ten rows ' + JSON.stringify([C0.length, R.length]));
  const [CA_, CB_, CC_] = C0;
  await call(CF, 'PATCH', `/api/sheets/${SID}/columns/${CA_}`, {title: 'Customer', kind: 'text'});
  await call(CF, 'PATCH', `/api/sheets/${SID}/columns/${CB_}`, {title: 'Date', kind: 'date'});
  await call(CF, 'PATCH', `/api/sheets/${SID}/columns/${CC_}`, {title: 'Amount', kind: 'currency'});
  const cd = await call(CF, 'POST', `/api/sheets/${SID}/columns`, {title: 'Status', kind: 'select', options: [{label: 'Open'}, {label: 'Done'}]});
  check(cd.http < 300, 'the selection column ' + cd.http + ' ' + JSON.stringify(cd));
  const CD_ = cd.column?.id || byPos((await call(CF, 'GET', `/api/sheets/${SID}`)).columns)[3];
  const rows = [['Acme', '2026-03-05', '100', 'Open'], ['Birch', '2026-03-20', '50', 'Done'], ['Acme', '2026-04-02', '30', 'Done'],
    ['Acme', '2026-04-10', '20', 'Open'], ['Birch', '2026-04-15', '40', 'Open'], ['Cedar', '2026-03-28', '', 'Done']];
  const cells = rows.flatMap((v, i) => [CA_, CB_, CC_, CD_].map((c, j) => ({row_id: R[i], col_id: c, raw: v[j]}))).filter(x => x.raw !== '');
  const put = await call(CF, 'PUT', `/api/sheets/${SID}/cells`, {cells});
  check(put.http === 200, 'the cells ' + put.http);
  const s1 = await call(CF, 'GET', `/api/sheets/${SID}`);
  const val = (r, c) => (s1.cells || []).find(x => x.row_id === r && x.col_id === c)?.value;
  check(val(R[0], CC_) === 100 && String(val(R[0], CB_)).startsWith('2026-03-05'), 'the values are numbers / dates ' + JSON.stringify([val(R[0], CC_), val(R[0], CB_)]));

  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  await firefox(async o => {
    const {cmd, ev, ctx, nav, until, shot} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1400, height: 900}});
    await nav(B + 'static/icon.svg'); check(await signIn(ev, 'frida') === 200, 'frida: login');
    await nav(B + '#sheets/' + SID);
    check(await until(`typeof SHV !== 'undefined' && SHV.sh?.id === ${SID} && !!document.querySelector('#shv-scroll td.shvc') && typeof shg_set === 'function'`), 'the table is open, sheetgroup.js loaded');
    const heads = () => ev(`[...document.querySelectorAll('#shv-scroll tr.shgh')].map(x => x.querySelector('.shgt b').textContent + '|' + x.querySelector('.shgn').textContent)`);
    const dataIds = () => ev(`[...document.querySelectorAll('#shv-scroll tbody tr[data-id]')].map(x => +x.dataset.id)`);
    const sumOf = (gi, c) => ev(`(() => { const td = document.querySelector('#shv-scroll tr.shgs[data-gi="${gi}"] td[data-c="${c}"]'); return td ? {v: td.dataset.v, agg: td.dataset.agg, t: td.textContent} : null; })()`);
    const colMenu = async c => { await ev(`(() => { document.querySelector('#shv-scroll [data-shv="col"][data-c="${c}"]').click(); return 1; })()`); };

    // ---- group by the customer through the column menu
    await colMenu(CA_);
    check(await ffm.act(ev, 'shg-by'), 'the column menu has "Group by this column"');
    check(await until(`document.querySelectorAll('#shv-scroll tr.shgh').length === 4`), 'four groups');
    check(JSON.stringify(await heads()) === JSON.stringify(['Acme|3 rows', 'Birch|2 rows', 'Cedar|1 row', '(empty)|4 rows']), 'the heads: alphabetical, empty last, with their rows ' + JSON.stringify(await heads()));
    check(JSON.stringify((await dataIds()).slice(0, 6)) === JSON.stringify([R[0], R[2], R[3], R[1], R[4], R[5]]), 'the rows bundled in their groups, the order kept inside ' + JSON.stringify(await dataIds()));
    check(await ev(`!!document.querySelector('.shvtop [data-shg="bar"]') && document.querySelector('.shvtop [data-shg="bar"]').textContent.includes('Customer')`), 'the top bar says "Grouped by Customer"');
    let x = await sumOf(0, CC_);
    check(x && x.agg === 'sum' && +x.v === 150 && x.t.includes('150'), 'Acme: the sum of the amounts is 150 ' + JSON.stringify(x));
    check(+(await sumOf(1, CC_))?.v === 90, 'Birch: the sum is 90');
    check(await ev(`!document.querySelector('#shv-scroll tr.shgs td[data-c="${CA_}"]') || !document.querySelector('#shv-scroll tr.shgs td[data-c="${CA_}"] button')`), 'a text column has no subtotal');
    await shot('p2671b-grouped.png');

    // ---- count / average per column
    await ev(`(() => { document.querySelector('#shv-scroll tr.shgs[data-gi="0"] td[data-c="${CC_}"] button').click(); return 1; })()`);
    check(await ffm.act(ev, 'shg-agg-count'), 'the subtotal menu has Count');
    check(await until(`document.querySelector('#shv-scroll tr.shgs[data-gi="0"] td[data-c="${CC_}"]')?.dataset.agg === 'count'`), 'the subtotal is a count now');
    check(+(await sumOf(0, CC_)).v === 3 && +(await sumOf(2, CC_)).v === 0, 'count: Acme 3, Cedar 0 (an empty amount does not count) ' + JSON.stringify([await sumOf(0, CC_), await sumOf(2, CC_)]));
    await ev(`(() => { document.querySelector('#shv-scroll tr.shgs[data-gi="0"] td[data-c="${CC_}"] button').click(); return 1; })()`);
    check(await ffm.act(ev, 'shg-agg-avg'), 'the subtotal menu has Average');
    check(await until(`document.querySelector('#shv-scroll tr.shgs[data-gi="0"] td[data-c="${CC_}"]')?.dataset.agg === 'avg'`), 'the subtotal is an average now');
    x = await sumOf(0, CC_); const xc = await sumOf(2, CC_);
    check(+x.v === 50 && x.t.includes('50') && x.t.includes('Average'), 'average: Acme 50 ' + JSON.stringify(x));
    check(xc.v === '' && xc.t.includes('–'), 'average of no numbers: "–" ' + JSON.stringify(xc));
    await ev(`(() => { document.querySelector('#shv-scroll tr.shgs[data-gi="0"] td[data-c="${CC_}"] button').click(); return 1; })()`);
    check(await ffm.act(ev, 'shg-agg-sum'), 'back to the sum');
    check(await until(`document.querySelector('#shv-scroll tr.shgs[data-gi="0"] td[data-c="${CC_}"]')?.dataset.v === '150'`), 'the sum again');

    // ---- close / open a group
    const r1 = await ffm.realClick(o, '#shv-scroll tr.shgh[data-gi="0"] th button');
    check(r1.ok, 'the head\'s button is hit ' + r1.on);
    check(await until(`document.querySelector('#shv-scroll tr.shgh[data-gi="0"] th button')?.getAttribute('aria-expanded') === 'false'`), 'Acme is closed');
    let ids = await dataIds();
    check(![R[0], R[2], R[3]].some(id => ids.includes(id)) && ids.includes(R[1]), 'its rows left, the others stay ' + JSON.stringify(ids));
    check(await ev(`!!document.querySelector('#shv-scroll tr.shgs[data-gi="0"]') && document.querySelector('#shv-scroll tr.shgh[data-gi="0"] .shgn').textContent === '3 rows'`), 'closed: the head with its 3 rows and the subtotal stay');
    check(+(await sumOf(0, CC_)).v === 150, 'closed: the subtotal still counts its rows');
    await ev(`(() => { shvSelect(${R[1]}, ${CA_}); return 1; })()`);
    await ev(`(() => { shvMove('up'); return 1; })()`);
    check(await ev(`SHV.cur.r === ${R[1]}`), 'the arrow up from Birch\'s first row does not land in the closed group');
    await ffm.realClick(o, '#shv-scroll tr.shgh[data-gi="0"] .shgt');
    check(await until(`document.querySelector('#shv-scroll tr.shgh[data-gi="0"] th button')?.getAttribute('aria-expanded') === 'true'`), 'Acme is open again (a click on its title)');
    ids = await dataIds();
    check([R[0], R[2], R[3]].every(id => ids.includes(id)), 'its rows are back ' + JSON.stringify(ids));

    // ---- subtotal rows are no data rows
    check(await ev(`[...document.querySelectorAll('#shv-scroll tr.shgs td, #shv-scroll tr.shgh td')].every(td => !td.id && !td.dataset.r && !td.classList.contains('shvc'))`), 'heads / subtotals: no cell ids, no row');
    await ev(`(() => { shvSelect(${R[0]}, ${CA_}); return 1; })()`);
    const p = await ev(`(() => { const r = document.querySelector('#shv-scroll tr.shgs[data-gi="1"] td[data-c="${CC_}"]').getBoundingClientRect(); return {x: Math.round(r.left + 8), y: Math.round(r.top + r.height / 2)}; })()`);
    await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'm1', parameters: {pointerType: 'mouse'}, actions: [
      {type: 'pointerMove', x: p.x, y: p.y}, {type: 'pointerDown', button: 0}, {type: 'pointerUp', button: 0}, {type: 'pointerDown', button: 0}, {type: 'pointerUp', button: 0}]}]});
    await cmd('input.releaseActions', {context: ctx});
    await sleep(300);  // nothing may happen: the double click had time to start an editor
    check(await ev(`!SHV.ed && SHV.cur?.r === ${R[0]} && SHV.cur?.c === ${CA_}`), 'a double click on a subtotal neither edits nor chooses ' + JSON.stringify(await ev(`({ed: !!SHV.ed, cur: SHV.cur})`)));
    await ev(`(() => { closePop(); return 1; })()`);
    await ev(`(() => { shvSelect(${R[3]}, ${CC_}); shvMove('down'); return 1; })()`);
    check(await ev(`SHV.cur.r === ${R[1]}`), 'the arrow down from Acme\'s last row goes to Birch\'s first row (past the subtotal and the head)');
    check(await ev(`shvGrid()[0].length === 10`), 'the grid knows only the 10 data rows');

    // ---- a write: the subtotal follows at once
    await ev(`(async () => { SHV.sh.can_write && await shvPut([{row_id: ${R[0]}, col_id: ${CC_}, raw: '200'}], 'test'); return 1; })()`);
    check(await until(`document.querySelector('#shv-scroll tr.shgs[data-gi="0"] td[data-c="${CC_}"]')?.dataset.v === '250'`), 'after a write Acme\'s sum is 250');

    // ---- moving rows waits while grouped
    await ev(`(async () => { await shmv_go('row', [${R[0]}], 4); return 1; })()`);
    check(await until(`(document.getElementById('toast')?.textContent || '').includes('Remove the grouping to move rows')`), 'grouped: a hint instead of a move');
    check(JSON.stringify(byPos((await call(CF, 'GET', `/api/sheets/${SID}`)).rows)) === JSON.stringify(R), 'the order on the server is unchanged');

    // ---- the filter works first
    await ev(`(() => { SHV.filt[${SID}] = {${CD_}: {opts: [SHV.sh._col.get(${CD_}).options.find(o => o.label === 'Open').id]}}; shvRender(); return 1; })()`);
    check(await until(`document.querySelectorAll('#shv-scroll tr.shgh').length === 2`), 'filtered on Open: two groups');
    check(JSON.stringify(await heads()) === JSON.stringify(['Acme|2 rows', 'Birch|1 row']), 'filtered: Acme 2, Birch 1 ' + JSON.stringify(await heads()));
    check(+(await sumOf(0, CC_)).v === 220 && +(await sumOf(1, CC_)).v === 40, 'filtered: the subtotals of the passing rows only (220, 40) ' + JSON.stringify([await sumOf(0, CC_), await sumOf(1, CC_)]));
    await ev(`(() => { delete SHV.filt[${SID}]; shvRender(); return 1; })()`);

    // ---- a date column: by month, then by year
    await colMenu(CB_);
    check(await ffm.act(ev, 'shg-by'), 'group by the date');
    check(await until(`document.querySelector('.shvtop [data-shg="bar"]')?.textContent.includes('Date')`), 'grouped by Date');
    let hs = await heads();
    check(hs.length === 3 && hs[0] === 'March 2026|3 rows' && hs[1] === 'April 2026|3 rows' && hs[2] === '(empty)|4 rows', 'by month: March, April, empty ' + JSON.stringify(hs));
    check(+(await sumOf(0, CC_)).v === 250 && +(await sumOf(1, CC_)).v === 90, 'by month: March 250, April 90');
    await ev(`(() => { document.querySelector('.shvtop [data-shg="bar"]').click(); return 1; })()`);
    check(await ffm.act(ev, 'shg-unit-year'), 'the bar\'s menu has Year');
    check(await until(`document.querySelectorAll('#shv-scroll tr.shgh').length === 2`), 'by year: two groups');
    hs = await heads();
    check(hs[0] === '2026|6 rows', 'by year: 2026 with 6 rows ' + JSON.stringify(hs));

    // ---- a selection: the order of its options
    await colMenu(CD_);
    check(await ffm.act(ev, 'shg-by'), 'group by the status');
    check(await until(`document.querySelectorAll('#shv-scroll tr.shgh').length === 3`), 'three status groups');
    hs = await heads();
    check(JSON.stringify(hs) === JSON.stringify(['Open|3 rows', 'Done|3 rows', '(empty)|4 rows']), 'the options in their order: Open, Done ' + JSON.stringify(hs));
    await shot('p2671b-status.png');

    // ---- remove the grouping
    await ev(`(() => { document.querySelector('.shvtop [data-shg="bar"]').click(); return 1; })()`);
    check(await ffm.act(ev, 'shg-off'), 'the bar\'s menu has "Remove grouping"');
    check(await until(`!document.querySelector('#shv-scroll tr.shgh') && !document.querySelector('#shv-scroll tr.shgs') && !document.querySelector('[data-shg="bar"]')`), 'no heads, no subtotals, no bar button');
    check(JSON.stringify(await dataIds()) === JSON.stringify(R), 'the plain order of the rows again');
    const s2 = await call(CF, 'GET', `/api/sheets/${SID}`);
    check((s2.rows || []).length === R.length && (s2.cells || []).every(c => c.row_id && R.includes(c.row_id)), 'the server has the same rows, no subtotal rows');
  }, false);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
