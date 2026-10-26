// 2.146.0 UI tests, part B (#2452 #2453): receipts -- several files on the receipt button, photos merged into one receipt,
// the same file not twice, the warning "Possibly a duplicate of" with "No duplicate", the DATEV dialog's switch. Own
// container (start.sh), Firefox. Invented companies and figures only; every picture / PDF is made in the page.
// freelancer-matrix: files
// - a person without organisation (personal office, a phone): the bookkeeping tab has the camera button (multiple) and
//   "Upload files" (multiple, ZIP); two photos -> the dialog "One receipt per photo / Merge"; merged -> ONE PDF receipt, its
//   sheet opens; the same PDF twice -> the toast "This file already exists" with Open (no second document)
// - two text invoices of the same supplier + number: the receipt sheet of the newer one warns with a link to the older
//   one; "No duplicate" removes the warning (stored), the toast's undo brings it back
// - the DATEV dialog has "Include possibly duplicate receipts", off
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2146_b_ui', check, shots: 'P2146B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2146B_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const upText = async (ck, name, text) => {
  const fd = new FormData(); fd.append('ws', 'private'); fd.append('files', new Blob([text], {type: 'text/plain'}), name);
  const r = await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: ck}, body: fd});
  return (await r.json()).ids?.[0];
};
const FEAT = 'cal,comments,collab,office,clients,docs,files';
const CRAFT = `Muster Bau GmbH · Werkstraße 12 · 54321 Beispielort
Rechnung
Rechnungs-Nr.: RE-2026-118
Datum: 06.10.2026
Material              60,00 €
Gesamtbetrag          71,40 €
USt-IdNr. DE123456789
`;
// in the page: a JPEG photo of one colour, a tiny PDF with a text layer
const MKJPG = `(c => new Promise(res => { const cv = document.createElement('canvas'); cv.width = 120; cv.height = 160; const x = cv.getContext('2d'); x.fillStyle = c; x.fillRect(0, 0, 120, 160); x.fillStyle = '#000'; x.fillText('Kasse', 10, 20); cv.toBlob(b => res(new File([b], c.replace('#', 'p') + '.jpg', {type: 'image/jpeg'})), 'image/jpeg', 0.9); }))`;
const PDF = '%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fu.http < 300, 'a person without organisation ' + fu.http);
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(((await call(CF, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'frida is in no organisation');
  // two text invoices: the same supplier + invoice number (the newer one = a possible duplicate)
  const T1 = await upText(CF, 'bau-mail.txt', CRAFT);
  let d1; for (let i = 0; i < 120 && !['done', 'failed'].includes((d1 = await call(CF, 'GET', `/api/docs/${T1}`)).state); i++) await sleep(500);
  const T2 = await upText(CF, 'bau-foto.txt', CRAFT + '\nFoto\n');
  let d2; for (let i = 0; i < 120 && !['done', 'failed'].includes((d2 = await call(CF, 'GET', `/api/docs/${T2}`)).state); i++) await sleep(500);
  check(d2.duplicate_of?.id === T1, 'the newer invoice is a possible duplicate ' + JSON.stringify(d2.duplicate_of));

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const count = `fetch('/api/docs?ws=private&limit=200&facets=0', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => j.total)`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});  // a phone
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'frida');
    await nav(B + '#office/books');
    check(await ready(ev, `!!document.querySelector('#bk-file') && !!document.querySelector('#bk-files')`, 80), 'the bookkeeping tab with both buttons');
    check(await ev(`document.querySelector('#bk-file').multiple && document.querySelector('#bk-files').multiple && /\\.zip/.test(document.querySelector('#bk-files').accept)`),
      'both take several files, "Upload files" takes a ZIP');
    await shot('p2146-b-buttons.png');
    const n0 = await ev(count);
    // two photos -> merged into one receipt
    await ev(`(async () => { const a = await ${MKJPG}('#ffeedd'), b = await ${MKJPG}('#ddeeff'); window.__p = bkFiles([a, b]); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.cdlg [name="bk-merge"][value="one"]')`, 40), 'two photos: the dialog asks how to file them');
    check(await ev(`document.querySelector('.cdlg [name="bk-merge"][value="each"]').checked`), 'default: one receipt per photo');
    await shot('p2146-b-merge.png');
    await ev(`(() => { const r = document.querySelector('.cdlg [name="bk-merge"][value="one"]'); r.checked = true; r.dispatchEvent(new Event('change', {bubbles: true})); document.querySelector('.cdlg [data-cd="yes"]').click(); return 1; })()`);
    check(await ready(ev, `${count}.then(n => n === ${n0} + 1)`, 80), 'merged: ONE new document');
    check(await ready(ev, `!!document.querySelector('.bk-sheet') && /\\.pdf$/.test(document.querySelector('.bk-sheet .bk-sname')?.textContent || '')`, 60),
      'the receipt sheet of the PDF opens ' + await ev(`document.querySelector('.bk-sheet .bk-sname')?.textContent || ''`));
    await ev(`(() => { document.querySelector('.bk-sheet [data-m="close"]')?.click(); return 1; })()`);
    // the same PDF twice: the second time a toast with Open, no new document
    await ev(`(() => { window.__f = new File([${JSON.stringify(PDF)}], 'beleg.pdf', {type: 'application/pdf'}); bkUpload([window.__f]); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.bk-sheet')`, 60), 'a PDF: its sheet');
    await ev(`(() => { document.querySelector('.bk-sheet [data-m="close"]')?.click(); return 1; })()`);
    const n1 = await ev(count);
    await ev(`(() => { bkUpload([window.__f]); return 1; })()`);
    check(await ready(ev, `/This file already exists/.test(document.querySelector('#toast')?.textContent || '')`, 60), 'the same PDF again: "This file already exists" ' + await ev(`document.querySelector('#toast')?.textContent || ''`));
    check(await ev(`[...document.querySelectorAll('#toast button')].some(b => b.textContent === 'Open')`), 'the toast offers Open');
    check(await ev(count) === n1, 'no second document');
    await shot('p2146-b-dup-file.png');
    // the receipt sheet of the possible duplicate: warning + link, "No duplicate", undo
    await ev(`(() => { bkSheet(${T2}, false); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.bk-sheet .rx-dup a[href="#docs/${T1}"]')`, 60), 'the sheet warns "Possibly a duplicate of" with a link to the older one');
    check(await ev(`/Possibly a duplicate of/.test(document.querySelector('.bk-sheet .rx-dup').textContent) && /bau-mail\\.txt/.test(document.querySelector('.bk-sheet .rx-dup').textContent)`), 'the text names the older one');
    await shot('p2146-b-dup-warn.png');
    await ev(`(() => { document.querySelector('.bk-sheet .rx-dup [data-rx^="nodup:"]').click(); return 1; })()`);
    check(await ready(ev, `fetch('/api/docs/${T2}', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => !j.duplicate_of)`, 60), '"No duplicate": stored');
    check(await ready(ev, `!!document.querySelector('.bk-sheet') && !document.querySelector('.bk-sheet .rx-dup')`, 60), 'the warning goes');
    // CI of 2.307.7: the own toast before its button (the "already exists" toast and its Open can still be there on a slow runner)
    check(await ready(ev, `/Marked as no duplicate/.test(document.querySelector('#toast')?.textContent || '') && /Undo/.test(document.querySelector('#toast button')?.textContent || '')`, 60), 'the undo toast of "No duplicate"');
    await ev(`(() => { document.querySelector('#toast button')?.click(); return 1; })()`);
    check(await ready(ev, `fetch('/api/docs/${T2}', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => j.duplicate_of && j.duplicate_of.id === ${T1})`, 60), 'undo: the warning is back');
    await ev(`(() => { document.querySelectorAll('.modal').forEach(m => m.remove()); return 1; })()`);
    // the DATEV dialog: possible duplicates stay out unless ticked
    check(await ready(ev, `typeof dx_dialog === 'function'`, 40), 'the DATEV dialog is loaded');
    await ev(`(() => { dx_dialog(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('#dx-dups') && !document.querySelector('#dx-dups').checked`, 40), 'DATEV: "Include possibly duplicate receipts", off');
  }, false);

  console.log(`p2146_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
