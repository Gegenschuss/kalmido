// 2.857.0 A UI test (#5518): the documents' saved views on the shared core's filter (static/js/docviews.js dcv_cat / dcv_edit,
// kalmido-suite: fresh
// fltdlg.js kflt_dialog). Own container (start.sh), jsdom, invented names and generated texts only. Used as a person would:
// - the sidebar under Files offers "+ New filter"; it opens the filter dialog of the lists with the documents' conditions
// - a condition: Sender / is one of / the value menu with the senders; the live count (from the server) shows the number
// - a date condition "from" is a date field
// - Save: the filter shows in the sidebar with its number, opens, and the list shows its documents by their names
// - the open view's menu "Edit filter…": the same dialog with its condition; "is none of" keeps the document without a sender;
//   saved, the list follows; leaving the view and opening it again from the sidebar shows the same documents
// freelancer-matrix: n/a - nur Oberfläche (die Person ohne Organisation prüft p2857_a_docfilter_test.py)
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2857A_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const input = (w, el, v) => { if (!el) return; el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); };
const change = (w, el, v) => { if (!el) return; el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const until = async (fn, n = 100) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const docNew = async (name, text, fields) => {
  const fd = new FormData(); fd.append('ws', 'private'); fd.append('files', new Blob([text], {type: 'text/plain'}), name);
  const id = (await (await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd})).json()).ids[0];
  await until(async () => ['done', 'failed'].includes((await call('GET', `/api/docs/${id}`)).state), 300);
  if (fields) await call('PATCH', `/api/docs/${id}`, fields);
  return id;
};

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: 'files,docs', workspace: 'private'});
  const D1 = await docNew('walrus-invoice.txt', 'Walrus invoice spring', {sender: 'Polar Ltd'});
  const D2 = await docNew('walrus-letter.txt', 'Walrus letter summer', {sender: 'Ice GmbH'});
  const D3 = await docNew('narwhal-note.txt', 'Narwhal note autumn');

  const w = await boot({user: 'alice', hash: 'ablage/docs'}), d = w.document;
  check(await until(() => w.eval(`typeof DC !== 'undefined' && DC.total === 3 && typeof dcv_edit === 'function'`)), 'the documents and the saved views are there');
  const nb = await until(() => d.querySelector('#side [data-dcv="new"]'));
  check(nb && /New filter/.test(nb.textContent), 'the sidebar under Files offers "+ New filter"');

  // ---- a new filter from the sidebar
  click(w, nb);
  const md = () => d.querySelector('.modal.fltdlg');
  const rows = () => [...(md()?.querySelectorAll('#f-conds .fcond') || [])];
  const row = (i = 0) => rows()[i];
  const cnt = () => md()?.querySelector('#f-count')?.textContent || '';
  check(await until(() => md() && /^3 documents match/.test(cnt())), `the dialog starts empty, the server counts all three: ${cnt()}`);
  check(/New filter/.test(md()?.querySelector('h3')?.textContent || ''), 'its title: New filter');
  click(w, md().querySelector('[data-m="cond-add"]'));
  check(rows().length === 1 && row().querySelector('.fc-f').value === 'sender' && row().querySelector('.fc-op').value === 'in', 'a row: Sender / is one of');
  const what = [...row().querySelectorAll('.fc-f option')].map(o => o.textContent);
  check(['Sender', 'Document type', 'Folder', 'Tag', 'Document date', 'Added on', 'File type', 'Archive number', 'To review', 'Text'].every(x => what.includes(x)),
    'the documents\' conditions ' + JSON.stringify(what));
  const pick = async (i, label) => {
    click(w, row(i).querySelector('.fc-v'));
    const pop = await until(() => { const p = d.querySelector('#pop'); return p && !p.classList.contains('hidden') && p.querySelector('[role="menuitemcheckbox"]') && p; });
    const items = pop ? [...pop.querySelectorAll('[role="menuitemcheckbox"]')] : [];
    click(w, items.find(b => b.textContent.trim() === label));
    return items.map(b => b.textContent.trim());
  };
  const vals = await pick(0, 'Polar Ltd');
  check(vals.includes('Polar Ltd') && vals.includes('Ice GmbH'), 'the value menu holds the senders ' + JSON.stringify(vals));
  check(await until(() => /^1 document matches/.test(cnt())) && /Polar Ltd/.test(row().querySelector('.fc-v').textContent), `the count follows the condition: ${cnt()}`);
  // a date row: "from" is a date field
  click(w, md().querySelector('[data-m="cond-add"]'));
  change(w, row(1).querySelector('.fc-f'), 'date');
  change(w, row(1).querySelector('.fc-op'), 'from');
  check(row(1).querySelector('input.fc-n')?.type === 'date', 'Document date "from": a date field');
  input(w, row(1).querySelector('input.fc-n'), '2000-01-01');
  check(await until(() => /^1 document matches/.test(cnt())), `a date long ago changes nothing: ${cnt()}`);
  input(w, md().querySelector('#f-name'), 'Polar papers');
  click(w, md().querySelector('[data-m="save"]'));
  const VID = await until(() => w.eval(`(DCV.items || []).find(v => v.title === 'Polar papers')?.id`));
  check(VID && await until(() => !md() && w.location.hash === '#ablage/v/' + VID), 'saved: the dialog closes, the filter opens');
  const R = w.eval(`JSON.stringify(dcv_get(${VID})?.rules)`);
  check(/"f":"sender","op":"in"/.test(R) && /"f":"date","op":"from","v":"2000-01-01"/.test(R), 'it keeps the conditions ' + R);
  const side = await until(() => (e => e && e.querySelector('.c')?.textContent === '1' ? e : null)(d.querySelector(`#side [data-sbbpart="docs-view"][data-dcvid="${VID}"]`)));
  check(side && side.textContent.includes('Polar papers') && side.getAttribute('aria-current') === 'page', 'the sidebar: the filter with its number, marked as open ' + side?.outerHTML?.slice(0, 200));
  const shown = () => w.eval(`!DC.loading && DC.dv === ${VID} ? DC.docs.map(x => x.id).sort((a, b) => a - b).join() : ''`);
  check(await until(() => shown() === String(D1)), 'the list shows the filter\'s document ' + shown());
  check(await until(() => /walrus-invoice/.test(d.querySelector('#view')?.textContent || '') && !/narwhal-note/.test(d.querySelector('#view')?.textContent || '')),
    'the list shows it by its name (and not the others)');

  // ---- edit the open view through its menu: is none of keeps the document without a sender
  const items = w.eval(`dcv_menuItems(dcv_get(${VID})).filter(x => x !== '-').map(x => x.label)`);
  check(items.includes('Edit filter…'), 'the view\'s menu offers "Edit filter…" ' + JSON.stringify(items));
  w.eval(`dcv_menuItems(dcv_get(${VID})).find(x => x && x.label === 'Edit filter…').fn()`);
  check(await until(() => md() && rows().length === 2 && /^1 document matches/.test(cnt())), `the dialog with the view's conditions and its count: ${cnt()}`);
  check(/Edit filter/.test(md().querySelector('h3')?.textContent || '') && md().querySelector('#f-name').value === 'Polar papers' && /Polar Ltd/.test(row().querySelector('.fc-v').textContent),
    'Edit filter: its name and its sender');
  change(w, row(0).querySelector('.fc-op'), 'nin');
  check(/Polar Ltd/.test(row(0).querySelector('.fc-v')?.textContent || ''), 'switched to "is none of": the sender stays chosen');
  check(await until(() => /^2 documents match/.test(cnt())), `is none of: the letter and the note without a sender: ${cnt()}`);
  click(w, md().querySelector('[data-m="save"]'));
  check(await until(() => !md() && shown() === [D2, D3].sort((a, b) => a - b).join()), 'saved: the list follows ' + shown());
  check(await until(() => d.querySelector(`#side [data-dcvid="${VID}"] .c`)?.textContent === '2'), 'the sidebar\'s number follows');
  // leave and come back through the sidebar
  w.location.hash = 'ablage/docs';
  check(await until(() => w.eval(`DC.dv === null && !DC.loading && DC.total === 3`)), 'back to all documents: three');
  click(w, d.querySelector(`#side [data-dcvid="${VID}"]`));
  check(await until(() => shown() === [D2, D3].sort((a, b) => a - b).join() && /narwhal-note/.test(d.querySelector('#view')?.textContent || '')), 'the sidebar row opens the filter again with its documents');

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  console.log(`p2857_a_docfilter_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
