// 2.658.0 UI tests, part B (#5092): a finished write on a module's own data is not put again by an older state of the app
// kalmido-suite: fresh
// (optWrite {mod: true}, like feeds / entertainment / budget in 2.651), own container (start.sh, mode workspaces), jsdom.
// Invented places, titles and figures only. For every module that got {mod: true}: the write runs through the module's own
// code, then the module's data is as a later own step leaves it (an Undo, a reload: the data from before the write), then a
// state of the app fetched before the write arrives (applyState): the write must not come back. Before 2.658 OPT_DONE put it
// again (the bookmark deleted again, the tick set again, the old title replaced again ...).
// - Bookmarks (bm_del), Read later (rdl_tick), Pipeline (pp_patch), Travel expenses (rk_tripDel), Logbook (the dialog's
//   Save), Books (bkChkPut), All receipts (rclChecked), the receipt in the document sheet (receipts.js rc_put)
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login, until: until0} = require('./boot');
const TC = require('./testclock');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const until = fn => until0(fn, {timeout: 15000, step: 100});
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const FEAT = 'cal,comments,collab,office,clients,docs,feeds,reading';
const DAY = TC.today();
const ev = (w, js) => { try { return w.eval(js); } catch { return undefined; } };

function tinyPdf(text) {  // a one-page PDF with a text layer
  const s = `BT /F1 12 Tf 40 700 Td (${text}) Tj ET`;
  const o = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>', '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    `<< /Length ${s.length} >>\nstream\n${s}\nendstream`, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'];
  let out = '%PDF-1.4\n'; const offs = [];
  o.forEach((x, i) => { offs.push(out.length); out += `${i + 1} 0 obj\n${x}\nendobj\n`; });
  const xr = out.length; out += `xref\n0 ${o.length + 1}\n0000000000 65535 f \n` + offs.map(n => String(n).padStart(10, '0') + ' 00000 n \n').join('');
  return out + `trailer\n<< /Size ${o.length + 1} /Root 1 0 R >>\nstartxref\n${xr}\n%%EOF\n`;
}

// one case: o.ready (the module's data is there), o.snap (the data a later own step leaves: taken before the write), o.act
// (the write through the module's code: a js text run in the page, or a function here), o.restore (puts window.__snap back),
// o.back (true while the write is not there)
async function oneCase(ck, w, name, o) {
  check(await until(() => ev(w, o.ready)), `${name}: the module's data is there`);
  const old = JSON.stringify(await call(ck, 'GET', '/api/state'));  // fetched before the write, arriving after it
  w.__snap = ev(w, o.snap);
  check(typeof w.__snap === 'string', `${name}: the data before the write`);
  const n0 = ev(w, 'OPT_DONE.size');
  try { if (typeof o.act === 'function') await o.act(); else await w.eval(`(async () => { ${o.act} })()`); } catch (e) { check(false, `${name}: the write ran ` + e.message); }
  check(await until(() => ev(w, 'OPT.size') === 0), `${name}: the write is done`);
  check(!ev(w, `!!(${o.back})`), `${name}: the write shows`);
  check(ev(w, 'OPT_DONE.size') === n0, `${name}: the finished write is not kept for applyState (OPT_DONE ${n0} -> ${ev(w, 'OPT_DONE.size')})`);
  w.__old = old;
  const res = ev(w, `(() => { ${o.restore}; applyState(JSON.parse(window.__old)); render(); return !!(${o.back}); })()`);
  check(res === true, `${name}: an older state of the app after the write does not bring the write back`);
}

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', lang: 'en'})});
  check(r.ok, 'setup');
  const ck = await login('alice');
  await call(ck, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call(ck, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(ck, 'GET', '/api/state')).me;
  const org = await call(ck, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(ck, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  const ws = `org:${org.id}`;

  // ---- data
  const bm = await call(ck, 'POST', '/api/bookmarks', {url: 'https://example.org/garden-notes', space: ws, title: 'Garden notes'});
  const BM = bm.bookmark?.id; check(bm.http === 201 && BM, 'a bookmark ' + bm.http);
  const rl = await call(ck, 'POST', '/api/reading', {url: 'https://example.org/long-read', space: ws, title: 'A long read'});
  const RL = rl.task_id; check(rl.http === 201 && RL, 'a link to read later ' + rl.http);
  const deal = await call(ck, 'POST', '/api/office/deals', {title: 'Imagefilm', value: 1000, stage: 'inquiry'});
  check(deal.http === 201 && deal.id, 'a deal ' + deal.http);
  const trip = await call(ck, 'POST', '/api/office/trips', {date_from: DAY, dest: 'Kiel', people: [], items: [{date: DAY, category: 'train', amount: 40}]});
  const TRIP = trip.id || trip.trip?.id; check(trip.http === 201 && TRIP, 'a trip ' + trip.http);
  const veh = await call(ck, 'POST', '/api/office/vehicles', {name: 'Kombi', kind: 'private', odo_start: '1000'});
  const drive = await call(ck, 'POST', '/api/office/drives', {vehicle_id: veh.id, day: DAY, start_place: 'Hamburg', dest: 'Kiel', purpose: 'Dreh', odo_start: 1000, odo_end: 1100, km: 100, kind: 'business'});
  check(drive.http === 201 && drive.id, 'a drive ' + drive.http);
  const fd = new FormData(); fd.append('ws', ws); fd.append('files', new Blob([tinyPdf('Beleg Papier')], {type: 'application/pdf'}), 'papier.pdf');
  const up = await (await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: ck}, body: fd})).json();
  const RC = up.ids?.[0]; check(RC, 'a receipt uploaded');
  await call(ck, 'PATCH', `/api/docs/${RC}`, {amount: '119.00', date: DAY});
  check((await call(ck, 'PUT', `/api/docs/${RC}/receipt`, {category: 'Material', vat_pct: '19', keep: true})).http === 200, 'the receipt: category Material');

  // ---- bookmarks, read later (the shown space: the organisation)
  let w = await boot({user: 'alice', hash: 'bookmarks'});
  await oneCase(ck, w, 'Bookmarks: delete', {ready: `BM.items?.some(x => x.id === ${BM})`, snap: 'JSON.stringify(BM.items)', act: `await bm_del(${BM})`,
    restore: 'BM.items = JSON.parse(window.__snap)', back: `bm_item(${BM})`});
  w.close();
  w = await boot({user: 'alice', hash: 'reading'});
  await oneCase(ck, w, 'Read later: tick off', {ready: `RDL.items?.some(x => x.id === ${RL})`, snap: 'JSON.stringify(RDL.items)', act: `await rdl_tick(${RL})`,
    restore: 'RDL.items = JSON.parse(window.__snap)', back: `rdl_item(${RL})`});
  w.close();

  // ---- office: pipeline, travel expenses, logbook
  w = await boot({user: 'alice', hash: 'office/pipeline'});
  await oneCase(ck, w, 'Pipeline: a deal saved', {ready: `pp_item(${deal.id})`, snap: 'JSON.stringify(PPS.data)', act: `await pp_patch(${deal.id}, {title: 'Werbefilm', value: 1000})`,
    restore: 'PPS.data = JSON.parse(window.__snap)', back: `pp_item(${deal.id})?.title === 'Imagefilm'`});
  w.close();
  w = await boot({user: 'alice', hash: 'office/travel'});
  await oneCase(ck, w, 'Travel expenses: a trip deleted', {ready: `rk_trip(${TRIP})`, snap: 'JSON.stringify(RK.data)', act: `await rk_tripDel(rk_trip(${TRIP}))`,
    restore: 'RK.data = JSON.parse(window.__snap)', back: `rk_trip(${TRIP})`});
  const d = w.document, dlg = () => d.querySelector('.modal.ofcdlg');
  const rowOf = re => [...d.querySelectorAll('.lgb-list [data-lgb="open"]')].find(b => re.test(b.textContent));
  check(await until(() => d.querySelector('[data-rk="view"][data-v="logbook"]')), 'the travel tab has the logbook');
  click(w, d.querySelector('[data-rk="view"][data-v="logbook"]'));
  check(await until(() => rowOf(/Hamburg/)), 'the logbook shows the drive');
  await oneCase(ck, w, 'Logbook: a drive saved', {ready: `LB.drives?.some(x => x.id === ${drive.id})`, snap: 'JSON.stringify(LB.drives)',
    act: async () => {
      click(w, rowOf(/Hamburg/)); await until(() => dlg()?.querySelector('#lgb-dest')?.value === 'Kiel');
      dlg().querySelector('#lgb-dest').value = 'Kiel Hafen'; click(w, dlg().querySelector('[data-m="save"]'));
      await until(async () => ((await call(ck, 'GET', `/api/office/drives?year=${DAY.slice(0, 4)}&vehicle_id=${veh.id}`)).drives || []).some(x => x.dest === 'Kiel Hafen'));
    },
    restore: 'LB.drives = JSON.parse(window.__snap)', back: `LB.drives?.find(x => x.id === ${drive.id})?.dest === 'Kiel'`});
  w.close();

  // ---- books: the tick "Checked" (receipt sheet and all receipts), the receipt in the document sheet
  w = await boot({user: 'alice', hash: 'office/books/receipts'});
  check(await until(() => ev(w, `RCL.rows?.some(x => x.node_id === ${RC})`)), 'all receipts list the receipt');
  await w.eval('bkLoad()');
  const unchecked = `bkRows(${RC}).length > 0 && bkRows(${RC}).every(x => !x.checked_at)`;
  const snapBk = 'JSON.stringify({info: BK.info, rows: RCL.rows})', restoreBk = 'const s = JSON.parse(window.__snap); BK.info = s.info; RCL.rows = s.rows';
  await oneCase(ck, w, 'Books: the receipt ticked "Checked"', {ready: `BK.info && ${unchecked}`, snap: snapBk, act: `await bkChkPut(${RC}, true)`, restore: restoreBk, back: unchecked});
  await call(ck, 'POST', '/api/office/books/receipts/checked', {node_ids: [RC], checked: false});
  await w.eval('bkLoad()');
  await w.eval('(() => { RCL.key = ""; return rclLoad(false); })()');
  await oneCase(ck, w, 'All receipts: "Mark as checked"', {ready: `BK.info && ${unchecked}`, snap: snapBk, act: `await rclChecked([${RC}], true)`, restore: restoreBk, back: unchecked});
  await w.eval(`(async () => { RC.id = ${RC}; RC.d = null; await rc_load(); })()`);
  await oneCase(ck, w, 'Receipt: the category', {ready: `RC.d?.receipt?.category === 'Material'`, snap: 'JSON.stringify(RC.d)', act: `await rc_put(${RC}, {...rc_cur(), category: 'Software'})`,
    restore: 'RC.d = JSON.parse(window.__snap)', back: `RC.d?.receipt?.category === 'Material'`});
  w.close();

  console.log(`p2658_b_optmod_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
