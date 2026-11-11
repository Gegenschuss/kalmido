// 2.777.0 UI test, part B (#4874: pages of a PDF document deleted / turned as a new version): own container (start.sh), jsdom + Firefox.
// kalmido-suite: fresh
// Invented data only. P2777B_NOSTART=1 = the container runs.
// - the document view's preview bar has "Pages": the strip opens under it with every page (numbers 1-3), page 2 (white)
//   carries "Blank?" and the hint says it is only marked; the note says the original stays as an older version
// - a click marks a page (aria-pressed), Del marks it for deletion ("2 of 3 pages stay"), Del again keeps it, Esc closes
//   the strip (not the view); "Save as new version" stays off until something changed
// - saved: the strip closes, the toast offers Undo, the server has version 2 with 2 pages, the strip opened again counts
//   "2 pages" and two pages, the tab History lists v1 (restorable) and v2 (current)
// - Undo (the toast): version 1 on top again (as version 3), the strip counts 3 pages again
// - turn right: page 1 turned (its small page shows it), saved as a new version
// - a reader (a view share) and a text document: no "Pages" button
// - Firefox (1440 and phone 390): the strip's small pages are drawn from the PDF, a page clicked and deleted by the key Del,
//   saved - the preview's counter says "Page 1 / 2"; nothing sideways on the phone
// - review fixes: Shift+End marks the span (F8); Undo after a newer version from elsewhere keeps it, says so and drops the
//   step (F1); more pages than max or no right to write (a locked month): a hint instead of the strip (F7 / F4)
// P4: alice works without an organisation (private documents): the person without an organisation (freelancer-matrix: files)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2777_b_docpages_ui', check, shots: 'P2777B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2777B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 75) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(200); } return fn(); };
const click = (w, el, o = {}) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const keyOn = (w, el, k, o = {}) => el.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true, ...o}));

function pdf(pages) {  // a PDF with one text page per entry (an empty entry = a white page), written by hand
  const esc = s => s.replace(/[\\()]/g, c => '\\' + c), n = pages.length;
  const objs = ['<< /Type /Catalog /Pages 2 0 R >>', `<< /Type /Pages /Kids [${pages.map((_, i) => `${4 + 2 * i} 0 R`).join(' ')}] /Count ${n} >>`,
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'];
  pages.forEach((lines, i) => {
    const st = lines.length ? 'BT /F1 12 Tf 60 740 Td 16 TL ' + lines.map(l => `(${esc(l)}) '`).join(' ') + ' ET' : '';
    objs.push(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents ${5 + 2 * i} 0 R /Resources << /Font << /F1 3 0 R >> >> >>`,
      `<< /Length ${st.length} >>\nstream\n${st}\nendstream`);
  });
  let out = '%PDF-1.4\n'; const offs = [];
  objs.forEach((o, i) => { offs.push(out.length); out += `${i + 1} 0 obj\n${o}\nendobj\n`; });
  const x = out.length;
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n` + offs.map(o => String(o).padStart(10, '0') + ' 00000 n \n').join('');
  out += `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${x}\n%%EOF\n`;
  return Buffer.from(out, 'latin1');
}
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
const three = tag => [['Kita Beispiel', 'Elternbrief ' + tag, 'Datum 01.09.2026'], [], ['Seite drei', 'Kontakt']];  // tag: other bytes (no duplicate)

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Example', password: 'password123'})).id;
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'}, await login('bob'));
  const D = await upload('elternbrief.pdf', pdf(three('A')));
  const T = await upload('notiz.txt', Buffer.from('Eine Notiz\n'), 'text/plain');
  check((await call('GET', `/api/docs/${D}`)).pages === 3, 'setup: a three-page PDF recognised');
  check(await until(async () => (await call('GET', `/api/docs/${D}/pages`)).blank?.includes(2), 100), 'setup: the stack scan marked page 2 blank');
  check((await call('POST', `/api/files/nodes/${D}/shares`, {user_id: BOB, role: 'view'})).status < 300, 'setup: bob may read it');

  // ================= jsdom: the strip, mark, Del, save, history, undo
  const w = await boot({user: 'alice', hash: `ablage/${D}`}), d = w.document;
  const v = () => d.querySelector('.dv-view');
  const strip = () => d.querySelector('.dv-view .dpg:not([hidden])');
  const pg = n => strip()?.querySelector(`[data-dpgp="${n}"]`);
  const btn = a => strip()?.querySelector(`[data-dpg="${a}"]`);
  check(await until(() => v()?.querySelector('.dc-body')?.dataset.id === String(D) && v().querySelector('.dv-pvbar [data-dpg="open"]')), 'the view of the PDF: "Pages" in the preview bar');
  check(!strip(), '... the strip is closed at first');
  click(w, v().querySelector('[data-dpg="open"]'));
  check(await until(() => strip() && strip().querySelectorAll('[data-dpgp]').length === 3), 'Pages: the strip opens with three pages');
  check([1, 2, 3].every(n => pg(n)?.querySelector('.dpg-no')?.textContent === String(n)), '... each with its number');
  check(v().querySelector('[data-dpg="open"]').getAttribute('aria-expanded') === 'true', '... the button says it is open');
  check(pg(2)?.classList.contains('blank') && /Blank\?/.test(pg(2).textContent) && !pg(1).classList.contains('blank'), '... page 2 marked "Blank?" (only page 2)');
  check(/1 page looks blank \(marked\) - nothing is deleted without you/.test(strip().querySelector('.dpg-hint')?.textContent || ''), '... the hint: only marked, nothing deleted ' + (strip().querySelector('.dpg-hint')?.textContent || '').trim());
  check(/original stays as an older version/.test(strip().querySelector('.dpg-note')?.textContent || ''), '... the note: the original stays as an older version');
  check(/3 pages/.test(strip().querySelector('.dpg-cnt')?.textContent || '') && btn('save').disabled && btn('del').disabled, '... "3 pages", Save and Delete off while nothing is chosen');

  click(w, pg(2));
  check(await until(() => pg(2)?.getAttribute('aria-pressed') === 'true' && !btn('del').disabled), 'a click marks page 2');
  keyOn(w, pg(2), 'Delete');
  check(await until(() => pg(2)?.classList.contains('gone') && /2 of 3 pages stay/.test(strip().querySelector('.dpg-cnt').textContent)), 'Del: page 2 to be deleted, "2 of 3 pages stay"');
  check(!btn('save').disabled && /Keep/.test(btn('del').textContent), '... Save on, the button now keeps it');
  check(v() && w.location.hash === `#ablage/${D}`, '... the key did not leave the view');
  keyOn(w, pg(2), 'Delete');
  check(await until(() => !pg(2)?.classList.contains('gone') && btn('save').disabled), 'Del again: page 2 stays, nothing to save');
  keyOn(w, pg(2), 'Escape');
  check(await until(() => !strip()) && v() && w.location.hash === `#ablage/${D}`, 'Esc in the strip closes the strip, the view stays');

  click(w, v().querySelector('[data-dpg="open"]'));
  await until(() => pg(2));
  click(w, pg(2)); keyOn(w, pg(2), 'Delete');
  await until(() => !btn('save')?.disabled);
  click(w, btn('save'));
  check(await until(async () => (await call('GET', `/api/files/nodes/${D}`)).version === 2, 100), 'Save: the server has version 2');
  check(await until(() => !strip()), '... the strip closes');
  check(await until(() => /Saved as version 2 with 2 pages - the original stays as version 1/.test(d.querySelector('#toast')?.textContent || '') && d.querySelector('#toast button')), '... the toast says so and offers Undo ' + (d.querySelector('#toast')?.textContent || ''));
  check(await until(async () => (await call('GET', `/api/docs/${D}`)).pages === 2, 150), '... recognised again with 2 pages');
  await settled(D);
  click(w, v().querySelector('[data-dpg="open"]'));
  check(await until(() => strip()?.querySelectorAll('[data-dpgp]').length === 2 && /^2 pages/.test(strip().querySelector('.dpg-cnt').textContent.trim())), 'opened again: "2 pages", two pages in the strip');
  check(!strip().querySelector('.blank') && !strip().querySelector('.dpg-hint'), '... no blank page left');
  click(w, v().querySelector('[data-dvtab="hist"]'));
  const hist = () => d.querySelector('.dv-view #dv-p-hist');
  check(await until(() => hist() && !hist().hidden && hist().querySelector('.abvrow[data-abvno="1"] [data-abv="1"]') && /current/.test(hist().querySelector('.abvrow[data-abvno="2"]')?.textContent || '')), 'the tab History: v2 current, the original v1 restorable');

  // undo (the app's Undo, one step - the toast may be gone by now): version 1 on top again
  check(w.eval('HIST.undo[HIST.undo.length - 1]?.label') === 'Pages of “elternbrief.pdf” changed', 'the step on top of Undo: "Pages of … changed"');
  await w.eval(`histStep('undo')`);
  // 2.905.0 (#5255): the server's step (files/fsundo.py) points the document back at version 1 (was: a new version 3 made by the browser)
  check(await until(async () => (await call('GET', `/api/files/nodes/${D}`)).version === 1, 100), 'Undo: version 1 on top again');
  check(await until(async () => (await call('GET', `/api/docs/${D}`)).pages === 3, 150), '... recognised again at once: 3 pages');
  await settled(D);
  if (strip()) click(w, btn('cancel'));
  check(await until(() => !strip()), '... (strip closed)');
  click(w, v().querySelector('[data-dpg="open"]'));
  check(await until(() => strip()?.querySelectorAll('[data-dpgp]').length === 3), '... the strip counts three pages again');

  // review F8: Shift+End marks the whole span from the page to the last one (not only both ends)
  click(w, pg(1));
  keyOn(w, pg(1), 'End', {shiftKey: true});
  check(await until(() => [1, 2, 3].every(n => pg(n)?.getAttribute('aria-pressed') === 'true')), 'Shift+End: pages 1 to 3 marked (the span, page 2 too)');
  click(w, pg(1));
  check(await until(() => pg(1)?.getAttribute('aria-pressed') === 'true' && pg(2)?.getAttribute('aria-pressed') === 'false'), '... a click marks page 1 alone again');

  // turn right: the small page shows it, saved as a new version
  click(w, btn('right'));
  check(await until(() => pg(1)?.querySelector('.dpg-th')?.style.getPropertyValue('--dpg-r') === '90deg' && /turned by 90°/.test(pg(1).getAttribute('aria-label'))), 'turn right: page 1 shown turned by 90');
  click(w, btn('save'));
  let vt = 0;
  check(await until(async () => (vt = (await call('GET', `/api/files/nodes/${D}`)).version) >= 3, 100), `... saved as a new version (${vt})`);
  await settled(D);

  // review F1: meanwhile a newer version from elsewhere - Undo never skips it. 2.905.0 (#5255): a version saved by the same
  // person on another device is that person's newest step: Undo takes it back first, then the turn (the server's order)
  check(w.eval(`(window.__dpgE = HIST.undo[HIST.undo.length - 1])?.label`) === 'Pages of “elternbrief.pdf” changed', 'the turn is the step on top of Undo');
  const ve = (await call('POST', `/api/docs/${D}/pages`, {rotate: {'2': 90}, expect_version: vt})).version;
  check(ve > vt, `elsewhere: a newer version saved (${ve})`);
  await settled(D);
  await w.eval(`histStep('undo')`);
  check(await until(async () => (await call('GET', `/api/files/nodes/${D}`)).version === vt, 100), '... Undo: the newer version from elsewhere goes back first (not skipped)');
  check(w.eval('HIST.undo.includes(window.__dpgE)'), '... the turn is still there to undo');
  await w.eval(`histStep('undo')`);
  check(await until(async () => (await call('GET', `/api/files/nodes/${D}`)).version === 1, 100), '... Undo again: the turn');
  check(w.eval('!HIST.undo.includes(window.__dpgE) && HIST.redo.includes(window.__dpgE)'), '... the turn is on the redo side');

  // review F7 / F4: more pages than the server changes, or no right to write (a locked month): a hint instead of the strip
  w.eval(`window.__dpgApi = api; api = (m, u, b) => window.__dpgApi(m, u, b).then(j => m === 'GET' && String(u).endsWith('/pages') ? {...j, ...window.__dpgOver} : j)`);
  for (const [over, re, what] of [[{max: 2}, /more than 2 pages - its pages cannot be changed here/, 'more pages than max'], [{write: false}, /cannot be changed \(read-only or a locked month\)/, 'no right to write']]) {
    w.eval(`window.__dpgOver = ${JSON.stringify(over)}`);
    if (strip()) click(w, btn('cancel'));
    await until(() => !strip());
    click(w, v().querySelector('[data-dpg="open"]'));
    check(await until(() => re.test(strip()?.querySelector('.dpg-stop')?.textContent || '')) && !strip().querySelector('[data-dpgp]') && !btn('save'), `${what}: the hint, no pages, no Save`);
    click(w, btn('cancel'));
    check(await until(() => !strip()) && v(), `... Close shuts the hint, the view stays`);
  }
  w.eval('api = window.__dpgApi');
  w.close();

  // ================= a reader and a text document: no "Pages"
  const wb = await boot({user: 'bob', hash: `ablage/${D}`}), db = wb.document;
  check(await until(() => db.querySelector('.dv-view .dv-pvbar')) && !db.querySelector('.dv-view [data-dpg="open"]'), 'a reader: no "Pages" button');
  wb.close();
  const wt = await boot({user: 'alice', hash: `ablage/${T}`}), dt = wt.document;
  check(await until(() => dt.querySelector('.dv-view .dv-pvbar')) && !dt.querySelector('.dv-view [data-dpg="open"]'), 'a text document: no "Pages" button');
  wt.close();

  // ================= Firefox: drawn small pages, Del, the preview counts the pages
  const D2 = await upload('drei-seiten.pdf', pdf(three('B')));
  for (const [vw, vh, tag] of [[1440, 900, '1440'], [390, 844, 'phone']]) {
    const id = tag === '1440' ? D2 : await upload('telefon.pdf', pdf(three('C')));
    await firefox(async ({cmd, ev, nav, ctx, shot}) => {
      await nav(B + 'static/icon.svg');
      await ev(`(() => { localStorage.clear(); return 1; })()`);
      check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, `Firefox ${tag}: login`);
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
      await nav(B + `#ablage/${id}`);
      const wait = async (js, n = 80) => { for (let i = 0; i < n; i++) { if (await ev(js).catch(() => false)) return true; await sleep(250); } return false; };
      check(await wait(`document.querySelectorAll('.dv-view .dv-pages .dv-pg').length === 3 && !!document.querySelector('.dv-view .dv-pages .dv-pg[data-i="0"] canvas') && /Page 1 \\/ 3/.test(document.querySelector('.dv-view .dv-pgn').textContent)`), `Firefox ${tag}: the preview with three pages ("Page 1 / 3")`);
      await ev(`(document.querySelector('.dv-view [data-dpg="open"]').click(), 1)`);
      check(await wait(`document.querySelectorAll('.dpg [data-dpgt] canvas').length === 3`), `Firefox ${tag}: the strip's three small pages are drawn from the PDF`);
      const lay = await ev(`(() => { const s = document.querySelector('.dpg').getBoundingClientRect(), p = document.querySelector('.dv-view .dv-pages').getBoundingClientRect(), b = document.querySelector('.dpg [data-dpg="save"]').getBoundingClientRect(), v = document.querySelector('.dv-view');
        return {sb: Math.round(s.bottom), pt: Math.round(p.top), ph: Math.round(p.height), bw: Math.round(b.width), br: Math.round(b.right), vw: innerWidth, sw: v.scrollWidth, cw: v.clientWidth}; })()`);
      check(lay && lay.sb <= lay.pt + 1 && lay.ph > 120 && lay.bw > 40 && lay.br <= lay.vw && lay.sw <= lay.cw + 1, `Firefox ${tag}: the strip above the pages, the pages keep room, Save in view, nothing sideways ` + JSON.stringify(lay));
      check(await ev(`document.querySelector('.dpg [data-dpgp="2"]').classList.contains('blank')`), `Firefox ${tag}: page 2 marked "Blank?"`);
      await ev(`(() => { const b = document.querySelector('.dpg [data-dpgp="2"]'); b.click(); return 1; })()`);
      await ev(`(() => { const b = document.querySelector('.dpg [data-dpgp="2"]'); b.focus(); b.dispatchEvent(new KeyboardEvent('keydown', {key: 'Delete', bubbles: true, cancelable: true})); return 1; })()`);
      check(await wait(`document.querySelector('.dpg [data-dpgp="2"]').classList.contains('gone') && document.querySelector('.dv-view .dv-pg[data-i="1"]').classList.contains('dpg-gone')`), `Firefox ${tag}: Del marks page 2, the large preview shows it faded`);
      await shot(`p2777-docpages-${tag}.png`);
      await ev(`(document.querySelector('.dpg [data-dpg="save"]').click(), 1)`);
      check(await wait(`!document.querySelector('.dpg:not([hidden])') && document.querySelectorAll('.dv-view .dv-pages .dv-pg').length === 2 && /Page 1 \\/ 2/.test(document.querySelector('.dv-view .dv-pgn').textContent)`), `Firefox ${tag}: saved - the preview now counts "Page 1 / 2"`);
    }, tag === 'phone');
    await settled(id);
  }

  console.log(`p2777_b_docpages_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
