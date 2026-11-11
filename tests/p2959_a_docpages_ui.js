// 2.959.0 UI test, part A (#4805: pages of a PDF document reordered, several PDF documents merged): own container (start.sh), jsdom + Firefox.
// kalmido-suite: fresh
// Invented data only. P2959A_NOSTART=1 = the container runs. Every page of the test PDFs has its own width, so the order of the
// pages the server stored can be read back (pypdf in the test container).
// - the page strip: page 3 chosen, "Move left" twice -> the strip shows it first ("1 (3)", "was page 3"), Save on; Ctrl+Shift+
//   arrow moves the chosen page with the keys; saved -> the server's new version has the pages in the order the strip showed,
//   the toast says so, the strip opened again shows 1, 2, 3 of the new file
// - merging: All documents, "Select", two PDF documents ticked, the bar's "More" offers "Merge PDFs…" (not with a text document
//   chosen); the dialog lists both in order, "Down" swaps them, "Merge into one PDF" -> the dialog closes, the toast offers Undo,
//   the list shows one card fewer, the remaining document (the one that came first) has every page in that order, the other
//   lies in the trash; Undo brings it back
// - Firefox, 1440 (mouse) and phone 390 (finger: hold, then drag): a page dragged onto another place in the strip -> the strip
//   shows the new order, saved -> the server has it; the merge dialog on the phone: both rows and the button in view, nothing
//   sideways, merged -> one document with all pages
// P4: alice works with private documents here; the person without an organisation is checked in p2959_a_docpages_api_test.py
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2959_a_docpages_ui', check, shots: 'P2959A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const CT = process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test';
if (!process.env.P2959A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 75) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(200); } return fn(); };
const click = (w, el, o = {}) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const keyOn = (w, el, k, o = {}) => el.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true, ...o}));

// a PDF with one text page per width (MediaBox width = the page's mark), written by hand
function pdf(widths, tag) {
  const n = widths.length;
  const objs = ['<< /Type /Catalog /Pages 2 0 R >>', `<< /Type /Pages /Kids [${widths.map((_, i) => `${4 + 2 * i} 0 R`).join(' ')}] /Count ${n} >>`,
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'];
  widths.forEach((wd, i) => {
    const st = `BT /F1 14 Tf 40 700 Td (Beispiel ${tag} Seite ${i + 1} Breite ${wd}) Tj ET`;
    objs.push(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${wd} 792] /Contents ${5 + 2 * i} 0 R /Resources << /Font << /F1 3 0 R >> >> >>`,
      `<< /Length ${st.length} >>\nstream\n${st}\nendstream`);
  });
  let out = '%PDF-1.4\n'; const offs = [];
  objs.forEach((o, i) => { offs.push(out.length); out += `${i + 1} 0 obj\n${o}\nendobj\n`; });
  const x = out.length;
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n` + offs.map(o => String(o).padStart(10, '0') + ' 00000 n \n').join('');
  out += `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${x}\n%%EOF\n`;
  return Buffer.from(out, 'latin1');
}
// the page widths of the file's current version, read with pypdf in the test container
async function widths(id) {
  const r = await fetch(B + `api/files/nodes/${id}/content`, {headers: {'X-Requested-With': 'kalmido', Cookie: CK}});
  if (!r.ok) return null;
  const b64 = Buffer.from(await r.arrayBuffer()).toString('base64');
  const code = 'import base64,io,json,sys\nfrom pypdf import PdfReader\nr=PdfReader(io.BytesIO(base64.b64decode(sys.stdin.read())))\nprint(json.dumps([round(float(p.mediabox.width)) for p in r.pages]))';
  try { return JSON.parse(execFileSync('docker', ['exec', '-i', CT, 'python', '-c', code], {input: b64}).toString()); } catch { return null; }
}
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
async function upload(name, data, type = 'application/pdf') {
  const fd = new FormData();
  fd.append('files', new Blob([data], {type}), name);
  fd.append('ws', 'private');
  const r = await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
  const id = (await r.json()).ids[0];
  await until(async () => ['done', 'failed'].includes((await call('GET', `/api/docs/${id}`)).state), 150);
  return id;
}
const settled = async id => until(async () => (await call('GET', `/api/docs/${id}`)).state === 'done', 150);
const ver = async id => (await call('GET', `/api/files/nodes/${id}`)).version;

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: 'docs,files'});

  // ================= jsdom: reorder in the page strip (buttons and keys)
  const D = await upload('drei-seiten.pdf', pdf([400, 450, 500], 'A'));
  check(same(await widths(D), [400, 450, 500]), 'setup: three pages in their order');
  let w = await boot({user: 'alice', hash: `ablage/${D}`}), d = w.document;
  const v = () => d.querySelector('.dv-view');
  const strip = () => d.querySelector('.dv-view .dpg:not([hidden])');
  const pg = n => strip()?.querySelector(`[data-dpgp="${n}"]`);
  const btn = a => strip()?.querySelector(`[data-dpg="${a}"]`);
  const shown = () => [...(strip()?.querySelectorAll('[data-dpgp]') || [])].map(x => +x.dataset.dpgp);
  check(await until(() => v()?.querySelector('.dv-pvbar [data-dpg="open"]')), 'the view of the PDF: "Pages" in the preview bar');
  click(w, v().querySelector('[data-dpg="open"]'));
  check(await until(() => shown().length === 3), 'Pages: the strip with three pages');
  check(btn('mvl')?.disabled && btn('mvr')?.disabled, '... "Move left" / "Move right" off while nothing is chosen');
  check(/Drag a page to its new place/.test(strip().textContent), '... the hint how to reorder by dragging');
  click(w, pg(3));
  check(await until(() => !btn('mvl')?.disabled), 'page 3 chosen: "Move left" on');
  click(w, btn('mvl'));
  check(await until(() => same(shown(), [1, 3, 2])), 'Move left: page 3 now second ' + shown());
  click(w, btn('mvl'));
  check(await until(() => same(shown(), [3, 1, 2])), 'Move left again: page 3 first ' + shown());
  check(/^1\s*\(3\)/.test(pg(3).querySelector('.dpg-no')?.textContent.trim() || '') && /Page 1, was page 3/.test(pg(3).getAttribute('aria-label') || ''),
    '... it shows its new place and where it was: ' + pg(3).querySelector('.dpg-no')?.textContent.trim());
  check(!btn('save').disabled, '... Save on (something changed)');
  click(w, btn('mvl'));
  check(same(shown(), [3, 1, 2]), 'Move left at the first place: nothing moves');
  // the keys: Ctrl+Shift+ArrowRight moves the chosen page one place, back with Ctrl+Shift+ArrowLeft
  keyOn(w, pg(3), 'ArrowRight', {ctrlKey: true, shiftKey: true});
  check(await until(() => same(shown(), [1, 3, 2])), 'Ctrl+Shift+ArrowRight: the chosen page one place to the right ' + shown());
  keyOn(w, pg(3), 'ArrowLeft', {ctrlKey: true, shiftKey: true});
  check(await until(() => same(shown(), [3, 1, 2])), 'Ctrl+Shift+ArrowLeft: back to the first place ' + shown());
  click(w, btn('save'));
  check(await until(async () => await ver(D) === 2, 100), 'Save: the server has version 2');
  check(same(await widths(D), [500, 400, 450]), '... with the pages in the order the strip showed');
  check(await until(() => /Saved as version 2 with 3 pages/.test(d.querySelector('#toast')?.textContent || '')), '... the toast says so');
  await settled(D);
  click(w, v().querySelector('[data-dpg="open"]'));
  check(await until(() => same(shown(), [1, 2, 3]) && !strip().querySelector('.moved')), 'opened again: the new file\'s pages 1, 2, 3 (nothing marked moved)');
  w.close();

  // ================= jsdom: merge two documents from the selection bar
  const M1 = await upload('teil-eins.pdf', pdf([300, 310], 'B'));
  const M2 = await upload('teil-zwei.pdf', pdf([320], 'C'));
  const TX = await upload('notiz.txt', Buffer.from('Eine Notiz\n'), 'text/plain');
  w = await boot({user: 'alice', hash: 'docs'}); d = w.document;
  const card = id => d.querySelector(`#view [data-dcchk="${id}"]`);
  check(await until(() => d.querySelector('.dc-view [data-absel="mode"]') && w.eval(`DC.docs.length`) >= 4), 'All documents: the list with the documents');
  click(w, d.querySelector('.dc-view [data-absel="mode"]'));
  check(await until(() => card(M1) && card(M2)), '"Select": each card has its mark');
  click(w, card(M1)); click(w, card(TX));
  await until(() => w.eval('AB.sel.size') === 2);
  click(w, d.querySelector('#ab-sbar [data-absel="more"]'));
  check(await until(() => d.querySelector('#pop .menu-list')) && !d.querySelector('#pop .msm-merge'), 'a PDF and a text document chosen: no "Merge PDFs…"');
  w.eval('closePop()');
  click(w, card(TX)); click(w, card(M2));
  check(await until(() => w.eval('AB.sel.size') === 2 && w.eval(`AB.sel.has(${M1}) && AB.sel.has(${M2})`)), 'two PDFs chosen');
  click(w, d.querySelector('#ab-sbar [data-absel="more"]'));
  const mi = await until(() => d.querySelector('#pop .menu-list .msm-merge'));
  check(mi && /Merge PDFs…/.test(mi.textContent), 'More offers "Merge PDFs…"');
  mi?.click();
  const dlg = () => d.querySelector('.dpm-md');
  const rows = () => [...(dlg()?.querySelectorAll('.dpm-row .dpm-nm') || [])].map(x => x.firstChild.textContent.trim());
  check(await until(() => rows().length === 2), 'the dialog lists both documents');
  check(/new version of the first one/.test(dlg().textContent) && /keeps its archive number/.test(dlg().querySelector('.dpm-row').textContent), '... says what happens, the first keeps its archive number');
  const first = rows()[0], other = rows()[1];
  click(w, dlg().querySelector('[data-dpmi="0"] [data-dpm="down"]'));
  check(await until(() => rows()[0] === other && rows()[1] === first), 'Down: the order swapped ' + rows());
  check(d.activeElement?.closest?.('[data-dpmi="1"]'), '... the focus stays on the moved row');
  const keepId = other === 'teil-zwei.pdf' ? M2 : M1, goneId = keepId === M2 ? M1 : M2;
  const want = [...(keepId === M2 ? [320] : [300, 310]), ...(keepId === M2 ? [300, 310] : [320])];
  click(w, dlg().querySelector('[data-dpm="run"]'));
  check(await until(() => !dlg()), 'Merge: the dialog closes');
  check(await until(() => /2 documents merged into/.test(d.querySelector('#toast')?.textContent || '') && d.querySelector('#toast button')), '... the toast says so and offers Undo ' + (d.querySelector('#toast')?.textContent || ''));
  check(same(await widths(keepId), want), '... the first document has every page in the chosen order ' + JSON.stringify(want));
  check((await call('GET', `/api/docs/${goneId}`)).status === 404, '... the other one is gone (in the trash)');
  check(await until(() => !card(goneId) && !d.querySelector(`#view [data-dco="${goneId}"]`) && d.querySelector(`#view [data-dco="${keepId}"]`)), '... the list shows one card fewer, the merged one stays');
  check(!w.eval('AB.selOn'), '... the choice ended');
  await settled(keepId);
  // Undo (the app's one step): the original back, the other document out of the trash
  await w.eval(`histStep('undo')`);
  check(await until(async () => (await call('GET', `/api/docs/${goneId}`)).status !== 404, 100), 'Undo: the other document is back');
  check(await until(async () => await ver(keepId) === 1, 100), '... the first on its original version');
  check(await until(() => d.querySelector(`#view [data-dco="${goneId}"]`), 100), '... and in the list again');
  w.close();
  await settled(keepId);

  // ================= Firefox: drag a page (mouse / finger), the merge dialog on the phone
  for (const [vw, vh, tag] of [[1440, 900, '1440'], [390, 844, 'phone']]) {
    const touch = tag === 'phone';
    const id = await upload(`ziehen-${tag}.pdf`, pdf([410, 420, 430], 'D' + tag));
    await firefox(async ({cmd, ev, nav, ctx, shot, drag}) => {
      await nav(B + 'static/icon.svg');
      await ev(`(() => { localStorage.clear(); return 1; })()`);
      check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, `Firefox ${tag}: login`);
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
      await nav(B + `#ablage/${id}`);
      const wait = async (js, n = 80) => { for (let i = 0; i < n; i++) { if (await ev(js).catch(() => false)) return true; await sleep(250); } return false; };
      check(await wait(`document.querySelectorAll('.dv-view .dv-pages .dv-pg').length === 3 && !!document.querySelector('.dv-view [data-dpg="open"]')`), `Firefox ${tag}: the view with three pages`);
      await ev(`(document.querySelector('.dv-view [data-dpg="open"]').click(), 1)`);
      check(await wait(`document.querySelectorAll('.dpg [data-dpgp]').length === 3`), `Firefox ${tag}: the strip open`);
      // measured once the small pages are drawn and the strip stands still (two equal readings)
      await wait(`document.querySelectorAll('.dpg [data-dpgt] canvas').length === 3`);
      const posJs = `(() => { const r = document.querySelector('.dpg [data-dpgp="1"]').getBoundingClientRect(), t = document.querySelector('.dpg [data-dpgp="3"]').getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2, tx: t.left + t.width * 0.8}; })()`;
      let r1 = await ev(posJs);
      for (let i = 0; i < 40; i++) { await sleep(150); const r2 = await ev(posJs); if (JSON.stringify(r2) === JSON.stringify(r1)) break; r1 = r2; }
      // page 1 dragged onto the right half of page 3 (a finger holds first)
      await drag(r1.x, r1.y, r1.tx - r1.x, 0, touch ? 'touch' : 'mouse', touch ? 600 : 0);
      const order = `[...document.querySelectorAll('.dpg [data-dpgp]')].map(x => +x.dataset.dpgp).join(',')`;
      check(await wait(`${order} === '2,3,1'`), `Firefox ${tag}: page 1 dragged behind page 3 - the strip shows 2, 3, 1 (${await ev(order)})`);
      const lay = await ev(`(() => { const v = document.querySelector('.dv-view'), b = document.querySelector('.dpg [data-dpg="save"]').getBoundingClientRect(); return {sw: v.scrollWidth, cw: v.clientWidth, br: Math.round(b.right), vw: innerWidth}; })()`);
      check(lay && lay.sw <= lay.cw + 1 && lay.br <= lay.vw, `Firefox ${tag}: Save in view, nothing sideways ` + JSON.stringify(lay));
      await shot(`p2959-docpages-${tag}.png`);
      await ev(`(document.querySelector('.dpg [data-dpg="save"]').click(), 1)`);
      check(await until(async () => await ver(id) === 2, 100), `Firefox ${tag}: saved as a new version`);
      check(same(await widths(id), [420, 430, 410]), `Firefox ${tag}: the server has the dragged order`);
      if (!touch) return;
      // the merge dialog on the phone: both rows and the button in view, nothing sideways
      await settled(id);
      const P1 = await upload('handy-eins.pdf', pdf([330], 'E')), P2 = await upload('handy-zwei.pdf', pdf([340, 350], 'F'));
      await nav(B + '#docs');
      check(await wait(`typeof ab_selPick === 'function' && typeof dpm_selItem === 'function' && !!document.querySelector('#view [data-dco="${P1}"]') && !!document.querySelector('#view [data-dco="${P2}"]')`), 'Firefox phone: All documents with both new documents');
      await ev(`(document.querySelector('.dc-view [data-absel="mode"]').click(), 1)`);
      await wait(`!!document.querySelector('#view [data-dcchk="${P1}"]')`);
      await ev(`(document.querySelector('#view [data-dcchk="${P1}"]').click(), document.querySelector('#view [data-dcchk="${P2}"]').click(), 1)`);
      check(await wait(`AB.sel.size === 2`), 'Firefox phone: two documents ticked');
      await ev(`(document.querySelector('#ab-sbar [data-absel="more"]').click(), 1)`);
      check(await wait(`!!document.querySelector('#pop .msm-merge')`), 'Firefox phone: More offers "Merge PDFs…"');
      await ev(`(document.querySelector('#pop .msm-merge').click(), 1)`);
      check(await wait(`document.querySelectorAll('.dpm-md .dpm-row').length === 2`), 'Firefox phone: the merge dialog with both rows');
      // the phone's dialog slides in from below: measured once it stands (a real state, no fixed wait)
      const mlJs = `(() => { const m = document.querySelector('.dpm-md'), b = m.querySelector('[data-dpm="run"]').getBoundingClientRect(), rs = [...m.querySelectorAll('.dpm-row')].map(r => r.getBoundingClientRect());
        return {sw: m.scrollWidth, cw: m.clientWidth, bb: Math.round(b.bottom), br: Math.round(b.right), vh: innerHeight, vw: innerWidth, rr: Math.max(...rs.map(r => Math.round(r.right)))}; })()`;
      await wait(`(${mlJs.replace(/;\s*$/, '')}).bb <= innerHeight && !document.querySelector('.dpm-md').getAnimations({subtree: true}).length`, 40);
      const ml = await ev(mlJs);
      check(ml && ml.sw <= ml.cw + 1 && ml.br <= ml.vw && ml.bb <= ml.vh && ml.rr <= ml.vw, 'Firefox phone: rows and the button in view, nothing sideways ' + JSON.stringify(ml));
      await shot('p2959-merge-phone.png');
      await ev(`(document.querySelector('.dpm-md [data-dpm="run"]').click(), 1)`);
      check(await wait(`!document.querySelector('.dpm-md')`), 'Firefox phone: merged, the dialog closes');
      const gone = async x => (await call('GET', `/api/docs/${x}`)).status === 404;
      check(await until(async () => (await gone(P1)) !== (await gone(P2)), 50), 'Firefox phone: one of the two is in the trash, the other stays');
      const kept = (await call('GET', `/api/docs/${P1}`)).status === 404 ? P2 : P1;
      check((await widths(kept))?.length === 3, 'Firefox phone: the remaining document has all three pages');
      check(await wait(`!!document.querySelector('#view [data-dco="${kept}"]') && !document.querySelector('#view [data-dco="${kept === P1 ? P2 : P1}"]')`), 'Firefox phone: the list shows the merged document, the other is gone');
    }, touch);
  }

  console.log(`p2959_a_docpages_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
