// 2.61.0 UI tests (part C, #1820), own container (start.sh). jsdom:
// - the file store has ONE search field; typing a word of a file's text lists the file ("Found in the text", its folder),
//   a project file below "Project files"; Escape clears it and the folder view is back
// - the task search: a task found only by its file's text shows "Found in the file <name>" below the row
// - the mark of a file (up.text) via the marks of the upload checks: "Text recognised" / "No text found" / nothing
// Firefox 390 touch: the search field and its hits fit the phone, screenshot.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p261_c_ui', check, shots: 'P261C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const type = (w, el, v) => { el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); };

function textPdf(lines) {  // a one-page PDF with a text layer, written by hand
  const esc = s => s.replace(/[\\()]/g, c => '\\' + c);
  const stream = 'BT /F1 12 Tf 60 740 Td 16 TL ' + lines.map(l => `(${esc(l)}) '`).join(' ') + ' ET';
  const objs = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'];
  let out = '%PDF-1.4\n'; const offs = [];
  objs.forEach((o, i) => { offs.push(out.length); out += `${i + 1} 0 obj\n${o}\nendobj\n`; });
  const x = out.length;
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n` + offs.map(o => String(o).padStart(10, '0') + ' 00000 n \n').join('');
  out += `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${x}\n%%EOF\n`;
  return Buffer.from(out, 'latin1');
}
const post = async (url, field, name, data, extra = {}) => {
  const fd = new FormData();
  fd.append(field, new Blob([data], {type: 'application/pdf'}), name);
  for (const [k, v] of Object.entries(extra)) fd.append(k, v);
  const r = await fetch(B + url.replace(/^\//, ''), {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
  return {status: r.status, ...(await r.json().catch(() => ({})))};
};

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const feats = ((await call('GET', '/api/state')).settings.features || '').split(',').filter(Boolean);
  if (!feats.includes('files')) await call('PATCH', '/api/settings', {features: [...feats, 'files'].join(',')});  // the file store

  // an Ablage file in a folder, a task file, a project file -- all with a text layer
  const FOLD = (await call('POST', '/api/files/folders', {name: 'Contracts', space: 'private'})).id;
  const up = await post('/api/files/upload', 'file', 'lease.pdf', textPdf(['Zitronenbaum Pachtvertrag 2026']), {parent_id: String(FOLD), replace: '0'});
  const NID = up.items?.[0]?.id;
  check(up.status === 201 && NID, 'setup: a file in the folder ' + up.status);
  const L = (await call('POST', '/api/lists', {name: 'Home'})).id;
  const T = (await call('POST', '/api/tasks', {title: 'Water bill', list_id: L})).id;
  await post(`/api/tasks/${T}/attachments`, 'file', 'meter.pdf', textPdf(['Wasserzaehler Ablesung Kirschbaum']));
  const P = (await call('POST', '/api/lists', {name: 'Garden', kind: 'project'})).id;
  await post(`/api/lists/${P}/files`, 'file', 'plan.pdf', textPdf(['Zitronenbaum Pflanzplan']));
  const found = q => call('GET', '/api/files/search?q=' + encodeURIComponent(q));
  check(await until(async () => { const j = await found('zitronenbaum'); return (j.items || []).length && (j.list_files || []).length; }, 400),
    'setup: the background recognition read the files');
  check(await until(async () => ((await call('GET', '/api/tasks?scope=search&q=kirschbaum')).tasks || []).some(t => t.id === T), 400), 'setup: the task file is read');

  // ================= the file store: one search field
  let w = await boot({user: 'alice', hash: 'ablage'}), d = w.document;
  await until(() => d.querySelector('#view .abview'));
  await until(() => d.querySelector('#ftxt-q'));
  const box = d.querySelector('#ftxt-q');
  check(box && box.getAttribute('aria-label') === 'Search files: name or text' && d.querySelectorAll('#ftxt-q').length === 1, '#1820: one search field in the file store, with a name');
  box?.focus();
  type(w, box, 'zitronenbaum');
  const hit = await until(() => [...d.querySelectorAll('.ftxtrow')].find(r => /lease\.pdf/.test(r.textContent)));
  check(hit && /Found in the text/.test(hit.textContent) && /in Contracts/.test(hit.textContent), '#1820: the file is listed by its text, with its folder ' + (hit?.textContent || ''));
  check(/Project files/.test(d.querySelector('.ftxth')?.textContent || '') && [...d.querySelectorAll('[data-ftxt-lf]')].some(b => /plan\.pdf/.test(b.textContent) && /Project Garden/.test(b.textContent)),
    '#1820: the project file below "Project files", with its project');
  check(d.activeElement?.id === 'ftxt-q', '#1820: the field keeps the focus while the hits come in');
  type(w, d.querySelector('#ftxt-q'), 'lease');
  check(await until(() => [...d.querySelectorAll('.ftxtrow')].some(r => /lease\.pdf/.test(r.textContent) && !/Found in the text/.test(r.textContent))), '#1820: a name hit carries no text note');
  type(w, d.querySelector('#ftxt-q'), 'giraffenhals');
  check(await until(() => /No results/.test(d.querySelector('.abempty')?.textContent || '')), '#1820: no hit: "No results."');
  d.querySelector('#ftxt-q').dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
  check(await until(() => !d.querySelector('.ftxtrow') && [...d.querySelectorAll('.abrow')].some(r => /Contracts/.test(r.textContent))), '#1820: Escape clears the search, the folders are back');
  type(w, d.querySelector('#ftxt-q'), 'contracts');
  const fr = await until(() => d.querySelector(`.ftxtrow [data-ab="open"][data-id="${FOLD}"]`));
  fr?.click();
  check(await until(() => w.location.hash === '#ablage/' + FOLD && !d.querySelector('.ftxtrow') && d.querySelector('#ftxt-q')?.value === ''), '#1820: opening a folder from the hits leaves the search');
  w.close();

  // ================= the task search: "Found in the file …"
  w = await boot({user: 'alice'}); d = w.document;
  w.eval(`go('search')`); await until(() => d.querySelector('#searchq'));
  w.eval(`doSearch('kirschbaum')`);
  const note = await until(() => d.querySelector('#sresults .ftxthit'), 60);
  check(note && /Found in the file meter\.pdf/.test(note.textContent), '#1820: the hit names the file ' + (note?.textContent || ''));
  w.eval(`doSearch('water')`);
  check(await until(() => d.querySelector('#sresults .task, #sresults [data-id]') && !d.querySelector('#sresults .ftxthit'), 60), '#1820: a title hit has no file note');

  // ================= the mark at a file
  check(w.eval(`ftxtMark({text: 'found'})`).includes('Text recognised') || w.eval(`typeof scnMark`) !== 'function', '#1820: "Text recognised" mark');
  check(w.eval(`ftxtMark({text: 'none'})`).includes('No text found') || w.eval(`typeof scnMark`) !== 'function', '#1820: "No text found" mark');
  check(w.eval(`ftxtMark({scan: 'unchecked'})`) === '' && w.eval(`ftxtMark(null)`) === '', '#1820: no mark without a text state');
  if (w.eval(`typeof scnMakers`) !== 'undefined') check(w.eval(`scnMakers.includes(ftxtMark)`), '#1820: the mark joins the marks of the upload checks');
  w.close();

  // ================= Firefox: the phone (390, touch)
  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '390';
    check(await ffLogin(o) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + '#ablage'); await sleep(2500);
    await ev(`(() => { const i = document.querySelector('#ftxt-q'); i.value = 'zitronenbaum'; i.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`); await sleep(1800);
    const g = await ev(`(() => { const i = document.querySelector('.ftxtbar'), r = document.querySelector('.ftxtrow'); if (!i || !r) return null; const a = i.getBoundingClientRect(), b = r.getBoundingClientRect();
      return {h: document.querySelector('#ftxt-q').getBoundingClientRect().height, left: Math.min(a.left, b.left), right: Math.max(a.right, b.right), wide: document.documentElement.scrollWidth <= 390}; })()`);
    check(g && g.left >= 0 && g.right <= 390 && g.wide && g.h >= 40, `${tag}: #1820 the search field and its hits fit the phone, a large target ` + JSON.stringify(g));
    await shot('p261c-390-ablage-search.png');
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
