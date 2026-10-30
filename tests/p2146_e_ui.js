// 2.146.0 UI tests, part E (#2456 #2457), own container (start.sh). Invented data only; the files are made here.
// jsdom (a person without an organisation: the personal office, the own address book):
// - #2456: the legacy import's file choice takes .xlsx, .csv (and .xls for the clear message); a CSV with Firma | Straße |
//   PLZ | Ort shows the column box open ("Address in separate columns") with a choice per field, the found columns
//   preselected and the client card filled; changing a column reads the file again with the new choice (one column per
//   field: the column taken from another field is freed there); Cancel forgets the file
// - #2457: "Import a vCard file…" lets several files be chosen and takes .zip; several files or one ZIP go to the import
//   at once (no CSV column dialog); one .vcf as before; the import panel names how many files were read and which not
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2146E_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const card = (uid, fn) => `BEGIN:VCARD\r\nVERSION:3.0\r\nUID:${uid}\r\nFN:${fn}\r\nN:${fn.split(' ')[1]};${fn.split(' ')[0]};;;\r\nEND:VCARD\r\n`;

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,office,clients,contacts'});
  let w, d;

  // ================= #2456: address columns + CSV in the legacy import
  w = await boot({hash: 'office/import'}); d = w.document;
  const inp = await until(() => d.querySelector('.oim #oim-xlsx'), 60);
  check(!!inp && /\.xlsx/.test(inp.accept) && /\.csv/.test(inp.accept) && /\.xls(,|$)/.test(inp.accept), '#2456: the file choice takes .xlsx, .csv, .xls: ' + inp?.accept);
  const csv = 'Firma;Straße;PLZ;Ort;Land\r\nBeispiel Ton GmbH;Lindenallee 7;50667;Köln;Deutschland\r\n';
  // the browser's own way: oimPreview with a File (jsdom's fetch of the app sends the form)
  await w.eval(`oimPreview(new File([${JSON.stringify(csv)}], 'kunden.csv', {type: 'text/csv'}))`);
  const box = await until(() => d.querySelector('.oimpv .e46map'), 60);
  check(!!box && box.open && /Address in separate columns/.test(box.querySelector('summary')?.textContent || ''), '#2456: the column box is open and says separate columns: ' + (box?.textContent || '').slice(0, 120));
  const sel = k => d.querySelector(`.oimpv [data-e46-map="${k}"]`);
  check(sel('name')?.value === '0' && sel('street')?.value === '1' && sel('zip')?.value === '2' && sel('city')?.value === '3' && sel('country')?.value === '4' && sel('contact')?.value === '',
    '#2456: the found columns are preselected: ' + ['name', 'street', 'zip', 'city', 'country', 'contact'].map(k => sel(k)?.value).join());
  check([...(sel('street')?.options || [])].map(o => o.textContent).join('|') === 'not in the file|Firma|Straße|PLZ|Ort|Land', '#2456: the choice lists the columns as written');
  const val = k => d.querySelector(`.oimpv .oimcard input[data-k="${k}"]`)?.value;
  check(val('name') === 'Beispiel Ton GmbH' && val('street') === 'Lindenallee 7' && val('zip') === '50667' && val('city') === 'Köln', '#2456: the card is filled from the columns');
  // a change reads the file again with the new choice; the column moves away from the field that had it
  let got = null;
  await w.eval(`window.__e46 = oimPreview; oimPreview = (f, m) => { window.__e46got = {name: f && f.name, m}; }`);
  const s = sel('contact'); s.value = '1'; s.dispatchEvent(new w.Event('change', {bubbles: true}));
  got = await until(() => w.eval('window.__e46got'), 20);
  check(got?.name === 'kunden.csv' && got.m.contact === 1 && !('street' in got.m) && got.m.zip === 2, '#2456: a change reads the same file again with the new choice: ' + JSON.stringify(got));
  await w.eval('oimPreview = window.__e46');
  d.querySelector('.oimpv [data-oim="cancel"]')?.click();
  check(await until(() => !d.querySelector('.oimpv') && w.eval('!OIM.file'), 20), '#2456: Cancel closes the preview and forgets the file');
  w.close();

  // ================= #2457: several vCards / ZIP
  const BK = (await call('POST', '/api/books', {name: 'Mine', org_id: null})).id;
  w = await boot({hash: 'contacts'}); d = w.document;
  await until(() => w.eval('typeof ctImport === "function"'), 40);
  await w.eval(`window.__runs = []; window.__inp = null; importTargetConfirm = async () => true;
    ctImpRun = (bid, f, m) => window.__runs.push({bid, many: Array.isArray(f), n: Array.isArray(f) ? f.length : 1, name: Array.isArray(f) ? f[0].name : f.name});
    ctx_csvMap = (bid, f) => window.__runs.push({bid, csv: true, name: f.name});
    HTMLInputElement.prototype.click = function () { if (this.type === 'file') window.__inp = this; }; 1`);
  const pick = async names => {
    await w.eval(`window.__inp = null; ctImport(${BK}); 1`);
    await until(() => w.eval('!!window.__inp'), 20);
    return w.eval(`(() => { const i = window.__inp; Object.defineProperty(i, 'files', {value: ${JSON.stringify(names)}.map(n => new File(['x'], n))}); i.onchange(); return {accept: i.accept, multiple: i.multiple}; })()`);
  };
  const a = await pick(['a.vcf', 'b.vcf']);
  check(a.multiple && /\.vcf/.test(a.accept) && /\.zip/.test(a.accept), '#2457: the vCard choice takes several files and .zip: ' + JSON.stringify(a));
  await until(() => w.eval('window.__runs.length >= 1'), 20);
  await pick(['takeout.zip']);
  await until(() => w.eval('window.__runs.length >= 2'), 20);
  await pick(['one.vcf']);
  const runs = await until(() => w.eval('window.__runs.length >= 3 && window.__runs'), 20);
  check(runs?.[0]?.many && runs[0].n === 2 && runs[0].bid === BK, '#2457: two .vcf files go to the import together: ' + JSON.stringify(runs?.[0]));
  check(runs?.[1]?.many && runs[1].name === 'takeout.zip' && !runs[1].csv, '#2457: a ZIP goes to the import, not to the CSV columns: ' + JSON.stringify(runs?.[1]));
  check(runs?.[2] && !runs[2].many && !runs[2].csv && runs[2].name === 'one.vcf', '#2457: one .vcf as before: ' + JSON.stringify(runs?.[2]));
  w.close();

  // the import panel with several real files: the server reads them (sent from here with the session; jsdom's XHR has
  // no cookie), the panel shows the server's answer
  const fd = new FormData();
  fd.append('files', new Blob([card('u1', 'Anna Probe')]), 'a.vcf'); fd.append('files', new Blob([card('u2', 'Ben Probe')]), 'b.vcf'); fd.append('files', new Blob(['hello']), 'note.txt');
  const res = await fetch(B + `api/books/${BK}/import?background=1`, {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
  const answer = await res.text();
  check(res.status === 200 && JSON.parse(answer).files?.files === 2, '#2457: the server reads several files: ' + answer.slice(0, 200));
  w = await boot({hash: 'contacts'}); d = w.document;
  await until(() => w.eval('typeof ctImpRun === "function"'), 40);
  w.__answer = answer;
  await w.eval(`window.__sent = null; XMLHttpRequest = class { open(m, u) { this.u = u; } setRequestHeader() {} get upload() { return {}; }
    send(b) { window.__sent = b.getAll('files').map(f => f.name); this.status = 200; this.responseText = window.__answer; setTimeout(() => this.onload(), 0); } };
    ctImpRun(${BK}, [new File(['a'], 'a.vcf'), new File(['b'], 'b.vcf'), new File(['hello'], 'note.txt')]); 1`);
  const done = await until(() => d.querySelector('#ctimp.done'), 60);
  const t = done?.textContent || '';
  check(JSON.stringify(await w.eval('window.__sent')) === '["a.vcf","b.vcf","note.txt"]', '#2457: the app sends every chosen file in the field files');
  check(/2 files/.test(t) && /2 new/.test(t) && /1 file not read/.test(t) && /note\.txt/.test(t), '#2457: the panel names the files read and the one not read: ' + t.slice(0, 200));
  const list = await call('GET', `/api/contacts?book_id=${BK}`);
  check((list.items || []).map(c => c.fn).sort().join() === 'Anna Probe,Ben Probe', '#2457: both contacts are in the book');
  w.close();

  console.log(`p2146_e_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
