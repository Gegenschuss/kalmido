// 2.122.0 UI tests of part B (own container, start.sh; P2122B_NOSTART=1: the container runs already). jsdom:
// - #2099 the file store: tags on a row, the tag picker in the details (a tag on / off, a new one) = ONE undo step, the tag
//   filter of a space (with, without, the line of filters, taking one out)
// - #2294 documents: the filter panel (several tags with / without, several senders), the line above the list with each
//   filter to take out and the number of hits, the search syntax; phones (390 px): the filters in a sheet, not as rows
//   above the list; the chosen documents get a tag at once (ONE undo step); the ZIP of the choice
// - #2295 Shift-click: a range forwards and backwards, unchoosing a range, Ctrl-click one, Shift-click without choosing
//   turns choosing on, another folder / another filter = a new anchor -- in the file store and in the documents
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2122B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const upload = async (name, text, form) => {
  const fd = new FormData(); fd.append('file', new Blob([text]), name);
  for (const [k, v] of Object.entries(form || {space: 'private'})) fd.append(k, v);
  const r = await fetch(B + 'api/files/upload', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
  return (await r.json()).items[0].id;
};
const docNew = async (name, text, fields) => {
  const fd = new FormData(); fd.append('ws', 'private'); fd.append('files', new Blob([text], {type: 'text/plain'}), name);
  const id = (await (await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd})).json()).ids[0];
  await until(async () => ['done', 'failed'].includes((await call('GET', `/api/docs/${id}`)).state), 300);
  if (fields) await call('PATCH', `/api/docs/${id}`, fields);
  return id;
};
const click = (w, el, o = {}) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const tagsOf = async id => ((await call('GET', `/api/files/nodes/${id}/tags`)).tags || []).map(t => t.name).sort().join(',');

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: 'files,docs,collab,comments'});
  const K = (await call('POST', '/api/files/folders', {name: 'Kiste', space: 'private'})).id;
  const R = [];
  for (const n of ['a-eins.txt', 'b-zwei.txt', 'c-drei.txt', 'd-vier.txt', 'e-fuenf.txt']) R.push(await upload(n, 'Datei ' + n));
  const IN = await upload('innen.txt', 'im Ordner', {parent_id: String(K)});
  await call('PUT', `/api/files/nodes/${R[0]}/tags`, {tags: ['Steuer']});
  await call('PUT', `/api/files/nodes/${R[1]}/tags`, {tags: ['Steuer', 'Kunde']});

  // ================= #2099 the file store: tags on rows, the picker, the filter
  const w = await boot({user: 'alice', hash: 'ablage', ls: {abSpace: '"private"'}}), d = w.document;
  const row0 = await until(() => d.querySelector(`.abrow[data-abid="${R[0]}"] .abtag`) && d.querySelector(`.abrow[data-abid="${R[0]}"]`), 60);
  check(row0 && /Steuer/.test(row0.querySelector('.abtags')?.textContent || ''), 'a row shows its tag');
  check(!d.querySelector(`.abrow[data-abid="${R[2]}"] .abtags`), 'a row without tags shows none');
  w.__dialogs = 'manual';
  w.eval(`dt_abEdit(AB.data.items.find(x => x.id === ${R[2]}))`);
  const pk = await until(() => d.querySelector('.modal.tsdlg .tspick [data-tsp]') && d.querySelector('.modal.tsdlg'));
  check(pk && [...pk.querySelectorAll('[data-tsp]')].map(b => b.dataset.tsp).sort().join(',') === 'Kunde,Steuer', 'the picker offers the tags of the space');
  if (pk) {
    click(w, pk.querySelector('[data-tsp="Steuer"]'));
    check(pk.querySelector('[data-tsp="Steuer"]').getAttribute('aria-pressed') === 'true', 'a click switches a tag on');
    pk.querySelector('#ts-new').value = 'Neu 2025'; click(w, pk.querySelector('[data-tsadd]'));
    check(pk.querySelector('[data-tsp="Neu 2025"]')?.getAttribute('aria-pressed') === 'true', 'a new tag is added and on');
    click(w, pk.querySelector('[data-cd="yes"]'));
  }
  check(await until(async () => (await tagsOf(R[2])) === 'Neu 2025,Steuer', 60), 'the tags are saved');
  check(await until(() => /Neu 2025/.test(d.querySelector(`.abrow[data-abid="${R[2]}"] .abtags`)?.textContent || '')), 'the row shows them');
  check(w.eval(`/Tags/.test(HIST.undo[HIST.undo.length - 1]?.label || '')`), 'ONE undo step');
  await w.eval(`histStep('undo')`);
  check(await until(async () => (await tagsOf(R[2])) === '', 60), 'undo: no tags again');
  w.__dialogs = undefined;
  // the tag filter
  click(w, d.querySelector('[data-dtab="filter"]'));
  const fm = await until(() => d.querySelector('.modal.tsdlg [data-dtf="Steuer"]') && d.querySelector('.modal.tsdlg'));
  check(fm, 'the tag filter opens with the tags of the space');
  if (fm) {
    click(w, fm.querySelector('[data-dtf="Steuer"]'));
    check(await until(() => d.querySelector('.tsfbar [data-dtabx="Steuer"]') && [...d.querySelectorAll('.ablist .abrow')].map(r => +r.dataset.abid).sort().join(',') === [R[0], R[1]].sort().join(',')),
      'filter "Steuer": only the two tagged files, the line shows the filter');
    check(/2 hits/.test(d.querySelector('.tsfbar')?.textContent || ''), 'the number of hits');
    click(w, fm.querySelector('[data-dtf="Steuer"]'));  // again: without
    check(await until(() => d.querySelector('.tsfbar .tsfx.not') && !d.querySelector(`.ablist .abrow[data-abid="${R[0]}"]`) && d.querySelector(`.ablist .abrow[data-abid="${R[3]}"]`)),
      'again: without Steuer');
    click(w, fm.querySelector('[data-m="close"]'));
  }
  click(w, d.querySelector('[data-dtabx="Steuer"]'));
  check(await until(() => !d.querySelector('.tsfbar') && d.querySelector(`.abrow[data-abid="${R[0]}"]`) && d.querySelector(`.abrow[data-abid="${K}"]`)), 'taking the filter out: the folder again');

  // ================= #2295 the file store: Shift ranges
  const box = id => d.querySelector(`[data-absel="one"][data-id="${id}"]`);
  const sel = () => w.eval('[...AB.sel].sort((a, b) => a - b).join(",")');
  const order = () => [...d.querySelectorAll('.ablist .abrow')].map(r => +r.dataset.abid);
  click(w, d.querySelector(`.abrow[data-abid="${R[0]}"] .abopen`), {shiftKey: true});
  check(await until(() => w.eval('AB.selOn') && sel() === String(R[0])), 'Shift-click without choosing turns choosing on with that row');
  const o = order(), at = id => o.indexOf(id);
  click(w, box(R[3]), {shiftKey: true});
  const want = o.slice(at(R[0]), at(R[3]) + 1).sort((a, b) => a - b).join(',');
  check(await until(() => sel() === want), `Shift-click: the range forwards (${sel()} vs ${want})`);
  await sleep(100);
  check(d.querySelectorAll('.absel input:checked').length === want.split(',').length, 'the boxes show the range');
  click(w, box(R[3]), {shiftKey: true});
  check(await until(() => sel() === ''), 'Shift-click on a chosen target: the range unchosen');
  click(w, box(R[4]));  // a plain click: the anchor
  check(await until(() => sel() === String(R[4])), 'a click chooses one and sets the anchor');
  click(w, box(R[1]), {shiftKey: true});
  const back = o.slice(at(R[1]), at(R[4]) + 1).sort((a, b) => a - b).join(',');
  check(await until(() => sel() === back), 'Shift-click: the range backwards');
  click(w, box(R[2]), {ctrlKey: true});
  check(await until(() => !w.eval(`AB.sel.has(${R[2]})`) && w.eval(`AB.sel.has(${R[1]})`)), 'Ctrl-click switches one');
  w.eval(`go('ablage/${K}')`);
  await until(() => d.querySelector(`.abrow[data-abid="${IN}"]`), 60);
  if (!w.eval('AB.selOn')) click(w, d.querySelector('[data-absel="mode"]'));
  await until(() => box(IN));
  w.eval('AB.sel.clear()');
  click(w, box(IN), {shiftKey: true});
  check(await until(() => sel() === String(IN)), 'another folder: a new anchor (Shift-click chooses only the row)');
  w.close();

  // ================= #2294 documents: filters, the line, syntax
  const D1 = await docNew('telekom.txt', 'Rechnung Telekom Mobilfunk Beispiel', {date: '2025-03-10', sender: 'Telekom Beispiel', type: 'Rechnung', tags: ['Steuer', 'Privat']});
  const D2 = await docNew('allianz.txt', 'Vertrag Versicherung Hausrat Beispiel', {date: '2024-06-01', sender: 'Allianz Beispiel', type: 'Vertrag', tags: ['Steuer']});
  const D3 = await docNew('prospekt.txt', 'Werbung Prospekt Beispiel', {date: '2025-07-01', sender: 'Laden Beispiel', type: 'Werbung'});
  const v = await boot({user: 'alice', hash: 'docs'}), vd = v.document;
  const cards = () => [...vd.querySelectorAll('.dc-card [data-dco]')].map(b => +b.dataset.dco).sort((a, b) => a - b).join(',');
  check(await until(() => vd.querySelectorAll('.dc-card').length === 3, 80), 'three documents');
  click(v, vd.querySelector('[data-dc="more"]'));
  const panel = await until(() => vd.querySelector('.dc-fpanel [data-dcftg="Steuer"]') && vd.querySelector('.dc-fpanel'));
  check(panel && panel.querySelector('[data-dcfsender="Allianz Beispiel"]') && panel.querySelector('[data-dcfft="pdf"]') && panel.querySelector('[data-dcf2="afrom"]'),
    'the panel: tags, senders, file types, date of arrival');
  click(v, vd.querySelector('[data-dcftg="Steuer"]'));
  check(await until(() => cards() === [D1, D2].join(',') && /2 hits/.test(vd.querySelector('.dc-fbar')?.textContent || '')), 'tag Steuer: two documents, "2 hits" in the line');
  click(v, vd.querySelector('[data-dcftg="Privat"]'));
  await until(() => vd.querySelector('[data-dcfm="all"]'));
  click(v, vd.querySelector('[data-dcfm="all"]'));
  check(await until(() => cards() === String(D1)), 'Steuer and Privat, every one: one document');
  click(v, vd.querySelector('[data-dcftg="Privat"]'));  // again: without Privat
  check(await until(() => cards() === String(D2) && vd.querySelector('.dc-fbar .tsfx.not')), 'Steuer without Privat: one document, the line shows "not"');
  click(v, vd.querySelector('[data-dc="clear"]'));
  check(await until(() => cards() === [D1, D2, D3].join(',') && !vd.querySelector('.dc-fbar')), 'reset: every document, no line');
  click(v, vd.querySelector('[data-dcfsender="Telekom Beispiel"]'));
  await until(() => cards() === String(D1));
  click(v, vd.querySelector('[data-dcfsender="Laden Beispiel"]'));
  check(await until(() => cards() === [D1, D3].join(',')), 'two senders: one of them');
  const fx = await until(() => vd.querySelector('.dc-fbar [data-dcx="0"]'));
  click(v, fx);
  check(await until(() => cards() === String(D3) && vd.querySelectorAll('.dc-fbar [data-dcx]').length === 1), 'one filter taken out in the line');
  click(v, vd.querySelector('[data-dc="clear"]'));
  await until(() => cards() === [D1, D2, D3].join(','));
  const q = vd.querySelector('#dc-q'); q.value = 'typ:Vertrag'; q.dispatchEvent(new v.Event('input', {bubbles: true}));
  check(await until(() => cards() === String(D2) && /typ:Vertrag/.test(vd.querySelector('.dc-fbar')?.textContent || ''), 60), 'syntax typ:Vertrag: one document, the search in the line');
  click(v, vd.querySelector('.dc-fbar [data-dcx="q"]'));
  check(await until(() => cards() === [D1, D2, D3].join(',') && !vd.querySelector('#dc-q')?.value), 'taking the search out');

  // ================= #2295 documents: Shift ranges
  const dsel = () => v.eval('[...DC.sel.keys()].sort((a, b) => a - b).join(",")');
  const dorder = () => v.eval('DC.docs.map(x => x.id)');
  const card = id => vd.querySelector(`[data-dco="${id}"]`);
  const od = dorder();
  click(v, card(od[0]), {shiftKey: true});
  check(await until(() => v.eval('DC.selOn') && dsel() === String(od[0]) && !vd.querySelector('.dc-md')), 'documents: Shift-click turns choosing on, nothing opens');
  click(v, card(od[2]), {shiftKey: true});
  check(await until(() => dsel() === [...od].sort((a, b) => a - b).join(',')), 'documents: the range forwards');
  click(v, card(od[1]), {shiftKey: true});
  check(await until(() => dsel() === String(od[2])), 'documents: Shift-click on a chosen target unchooses the range up to it');
  click(v, vd.querySelector(`[data-dcchk="${od[2]}"]`));  // the box: off again, the anchor here (2.430.0 (#3582): a plain click opens)
  click(v, card(od[0]), {shiftKey: true});
  check(await until(() => dsel() === [...od].sort((a, b) => a - b).join(',')), 'documents: the range backwards');
  click(v, card(od[1]), {metaKey: true});
  check(await until(() => !v.eval(`DC.sel.has(${od[1]})`)), 'documents: Cmd-click switches one');
  // the chosen documents at once: a tag (ONE undo step)
  v.eval(`DC.sel = new Map([[${D1}, null], [${D3}, null]]); dc_draw()`);
  v.__dialogs = 'manual';
  click(v, vd.querySelector('[data-dcsel="edit"]'));
  const mi = await until(() => [...vd.querySelectorAll('#pop [role="menuitem"]')].find(b => /Add tags/.test(b.textContent)));
  check(mi, 'the bar: "Edit" offers "Add tags…"');
  mi?.click();
  const pk2 = await until(() => vd.querySelector('.modal.tsdlg'));
  if (pk2) { pk2.querySelector('#ts-new').value = 'Stapel'; click(v, pk2.querySelector('[data-tsadd]')); click(v, pk2.querySelector('[data-cd="yes"]')); }
  const has = async (id, t) => ((await call('GET', `/api/docs/${id}`)).tags || []).some(x => x.name === t);
  check(await until(async () => await has(D1, 'Stapel') && await has(D3, 'Stapel') && !(await has(D2, 'Stapel')), 60), 'both chosen documents have the tag');
  check(v.eval(`/Tags added/.test(HIST.undo[HIST.undo.length - 1]?.label || '')`), 'ONE undo step');
  await v.eval(`histStep('undo')`);
  check(await until(async () => !(await has(D1, 'Stapel')) && !(await has(D3, 'Stapel')), 60), 'undo: the tag is gone from both');
  v.__dialogs = undefined;
  // the ZIP
  v.eval(`DC.sel = new Map([[${D1}, null], [${D2}, null]]); dc_draw()`);
  click(v, vd.querySelector('[data-dcsel="zip"]'));
  check(await until(() => /being prepared/.test(vd.body.textContent)), 'ZIP: the hint while it is prepared');
  v.close();

  // ================= #2294 phones (390 px): the filters in a sheet, not as rows above the list
  const m = await boot({user: 'alice', hash: 'docs', mobile: true}), md = m.document;
  await until(() => md.querySelectorAll('.dc-card').length === 3, 80);
  click(m, md.querySelector('[data-dc="more"]'));
  const sh = await until(() => md.querySelector('.modal.dc-fsheet [data-dcftg="Steuer"]') && md.querySelector('.modal.dc-fsheet'));
  check(sh && !md.querySelector('.dc-view .dc-fpanel'), 'phones: the filters open as a sheet, not above the list');
  if (sh) {
    click(m, sh.querySelector('[data-dcftg="Steuer"]'));
    check(await until(() => md.querySelectorAll('.dc-card').length === 2 && /Show 2 documents/.test(sh.querySelector('.foot [data-m="close"]')?.textContent || '')),
      'phones: a tag in the sheet filters at once, the button names the hits');
    click(m, sh.querySelector('.foot [data-m="close"]'));
  }
  check(await until(() => !md.querySelector('.dc-fsheet') && md.querySelector('.dc-fbar')), 'phones: the line of filters above the list stays');
  m.close();

  console.log(`p2122_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
