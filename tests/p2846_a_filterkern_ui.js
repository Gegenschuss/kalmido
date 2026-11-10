// 2.846.0 A UI test (#5520): the filter of the shared core (static/js/fltkern.js + fltdlg.js kflt_rows / kflt_dialog).
// kalmido-suite: fresh
// Used by an area with its own catalog: a stand-in "documents" catalog (kind, text) over invented file names, jsdom against an own
// container (start.sh). A person without an organisation (frida).
// freelancer-matrix: lists (the filter dialog of the own space; the core has no routes of its own)
// - the dialog starts empty with the live count of all items; "+ Condition" adds the catalog's first "what"; the value menu
//   holds the catalog's values, a click checks one, the count and the row's summary follow at once
// - a row switched to "Text" becomes a text field; OR counts any one; "is none of" holds on top also with OR (the hint says so)
// - Save hands {op, conds} with only the conditions that are on; reopening shows the same rows, values, AND / OR and count;
//   x removes a row and the count follows; Cancel closes
// - kflt_match in the page gives the same items as the count; the lists' filterMatch still runs through the core
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2846A_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const input = (w, el, v) => { if (!el) return; el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); };
const change = (w, el, v) => { if (!el) return; el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const until = async (fn, n = 80) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };

// the stand-in catalog of an area (as #5518 documents would pass it): items, their kinds, a text
const SETUP = `(() => {
  window.DOCS = [{name: 'offer-a.pdf', kind: 'pdf'}, {name: 'offer-b.pdf', kind: 'pdf'}, {name: 'photo.jpg', kind: 'img'},
    {name: 'meeting notes.docx', kind: 'doc'}, {name: 'readme', kind: ''}];
  window.DCAT = {has: {kind: (x, y) => x.kind === y}, empty: {kind: ''}, text: x => [x.name],
    what: () => [['kind', 'Kind'], ['text', 'Text']], ops: c => (c.f === 'text' ? ['has', 'nhas'] : ['in', 'nin', 'empty']),
    vals: () => [['pdf', 'PDF'], ['img', 'Image'], ['doc', 'Word']], add: () => 'kind',
    fresh: k => (k === 'text' ? {f: 'text', op: 'has', v: ''} : {f: k, op: 'in', v: []})};
  window.dOpen = rules => kflt_dialog({cat: DCAT, rules, name: rules ? 'Offers' : '', title: rules ? 'Edit filter' : 'New filter',
    count: r => DOCS.filter(x => kflt_match(x, r, DCAT)).length + ' documents match',
    save: (name, r, md) => { window.SAVED = {name, rules: r}; md.remove(); }});
  return 1;
})()`;

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  CK = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  check(!((await call('GET', '/api/state')).me.workspaces || []).length, 'setup: frida has no organisation');
  const lid = (await call('POST', '/api/lists', {name: 'Own project'})).id;
  await call('POST', '/api/tasks', {title: 'Send the offer', list_id: lid, priority: 5});
  await call('POST', '/api/tasks', {title: 'Water the plants', list_id: lid, priority: 1});

  const w = await boot({user: 'frida', hash: 'today'}), d = w.document;
  check(await until(() => w.eval('!!(S.booted && typeof loadModule === "function" && typeof kflt_match === "function")')), 'the app and the core filter are there');
  await w.eval(`loadModule('fltdlg').then(() => ${SETUP})`);
  check(await until(() => w.eval('typeof kflt_dialog === "function" && !!window.dOpen')), 'the dialog part loads on demand');

  // ---- a new filter with the stand-in catalog
  w.eval('dOpen(null)');
  const md = () => d.querySelector('.modal.fltdlg');
  const rows = () => [...(md()?.querySelectorAll('#f-conds .fcond') || [])];
  const row = (i = 0) => rows()[i];
  const cnt = () => md()?.querySelector('#f-count')?.textContent || '';
  check(await until(() => md()) && rows().length === 0 && /^5 documents match/.test(cnt()), `starts empty, all 5 count: ${cnt()}`);
  click(w, md().querySelector('[data-m="cond-add"]'));
  check(rows().length === 1 && row().querySelector('.fc-f').value === 'kind' && row().querySelector('.fc-op').value === 'in' && /Select/.test(row().querySelector('.fc-v')?.textContent || ''),
    'a row of the catalog: Kind / is one of / Select…');
  check([...row().querySelectorAll('.fc-f option')].map(o => o.textContent).join(',') === 'Kind,Text', 'the what list is the catalog\'s');
  check([...row().querySelectorAll('.fc-op option')].map(o => o.value).join(',') === 'in,nin,empty', 'the comparisons are the catalog\'s');
  const pick = async (i, label) => {
    click(w, row(i).querySelector('.fc-v'));
    const pop = await until(() => { const p = d.querySelector('#pop'); return p && !p.classList.contains('hidden') && p.querySelector('[role="menuitemcheckbox"]') && p; });
    const items = pop ? [...pop.querySelectorAll('[role="menuitemcheckbox"]')] : [];
    const it = items.find(b => b.textContent.trim() === label);
    click(w, it);
    return {items: items.map(b => b.textContent.trim()), on: it?.getAttribute('aria-checked')};
  };
  const p1 = await pick(0, 'PDF');
  check(p1.items.join(',') === 'PDF,Image,Word' && p1.on === 'true', `the value menu holds the catalog's values, PDF checked: ${JSON.stringify(p1)}`);
  check(/^2 documents match/.test(cnt()) && /PDF/.test(row().querySelector('.fc-v').textContent), `the count and the row follow at once: ${cnt()}`);

  // a second row, switched to Text; OR
  click(w, md().querySelector('[data-m="cond-add"]'));
  change(w, row(1).querySelector('.fc-f'), 'text');
  check(row(1).querySelector('.fc-t') && row(1).querySelector('.fc-op').value === 'has', 'a row switched to Text is a text field with "contains"');
  input(w, row(1).querySelector('.fc-t'), 'notes');
  check(/^0 documents match/.test(cnt()), `AND: a PDF that contains "notes" is none: ${cnt()}`);
  click(w, md().querySelector('#f-op [data-op="or"]'));
  check(/^3 documents match/.test(cnt()), `OR: the two PDFs and the notes: ${cnt()}`);
  // a third row: is none of PDF holds on top
  click(w, md().querySelector('[data-m="cond-add"]'));
  change(w, row(2).querySelector('.fc-op'), 'nin');
  await pick(2, 'PDF');
  check(/^1 documents match/.test(cnt()) && /always applies on top/.test(cnt()), `"is none of" holds on top also with OR, the hint says so: ${cnt()}`);
  click(w, md().querySelector('[data-m="cond-add"]'));  // a fourth row without a value is off and not saved
  check(rows().length === 4 && /^1 documents match/.test(cnt()), 'a row without a value changes nothing');
  input(w, md().querySelector('#f-name'), 'Offers');
  click(w, md().querySelector('[data-m="save"]'));
  const saved = await until(() => w.eval('window.SAVED ? JSON.stringify(SAVED) : ""'));
  const S1 = JSON.parse(saved || '{}');
  check(S1.name === 'Offers' && S1.rules?.op === 'or' && JSON.stringify(S1.rules.conds) === JSON.stringify([{f: 'kind', op: 'in', v: ['pdf']}, {f: 'text', op: 'has', v: 'notes'}, {f: 'kind', op: 'nin', v: ['pdf']}]),
    `save hands {op, conds} with the conditions that are on: ${saved}`);
  check(await until(() => !md()), 'the dialog closed after saving');
  check(w.eval(`DOCS.filter(x => kflt_match(x, SAVED.rules, DCAT)).map(x => x.name).join(',')`) === 'meeting notes.docx', 'kflt_match: the same item as the count');

  // ---- reopen: the same rows, values, OR and count
  w.eval('dOpen(SAVED.rules)');
  check(await until(() => md() && rows().length === 3), 'reopened: three rows');
  check(row(0).querySelector('.fc-f').value === 'kind' && /PDF/.test(row(0).querySelector('.fc-v').textContent) && row(1).querySelector('.fc-t').value === 'notes'
    && row(2).querySelector('.fc-op').value === 'nin' && /PDF/.test(row(2).querySelector('.fc-v').textContent), 'reopened: the rows with their values');
  check(md().querySelector('#f-op [data-op="or"]').classList.contains('on') && md().querySelector('#f-name').value === 'Offers' && /^1 documents match/.test(cnt()),
    `reopened: OR, the name and the count: ${cnt()}`);
  click(w, row(2).querySelector('.fc-x'));
  check(rows().length === 2 && /^3 documents match/.test(cnt()), `x removes the row, the count follows: ${cnt()}`);
  click(w, md().querySelector('[data-m="close"]'));
  check(await until(() => !md()), 'Cancel closes');
  check(w.eval('JSON.stringify(SAVED.rules.conds.length)') === '3', 'Cancel kept the saved filter as it was');

  // ---- the lists still filter through the core
  check(w.eval(`openTasks().filter(t => filterMatch(t, {op: 'and', conds: [{f: 'prio', op: 'in', v: [5]}]})).map(t => t.title).join(',')`) === 'Send the offer', 'the lists\' filterMatch runs through the core');
  check(w.eval(`openTasks().filter(t => filterMatch(t, {prios: [1]})).map(t => t.title).join(',')`) === 'Water the plants', 'an older rule of the lists still converts');

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
