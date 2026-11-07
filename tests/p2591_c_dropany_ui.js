// 2.591.0 (#4894) UI test: files dragged from the computer onto the window (static/js/dropany.js).
// kalmido-suite: fresh
// Own container (start.sh, mode workspaces), Firefox with a mouse (+ one touch session). Invented data only; every file is made in the page.
// freelancer-matrix: files
// - a person without organisation, Office > Bookkeeping (one upload button on a desktop): a file dragged over the view frames
//   the window with "Drop here: Upload files"; released -> the receipt is uploaded (one document more) through the button's own
//   input; a file of a wrong type -> "This file type does not fit here", nothing uploaded
// - a dialog on top of the view: the file goes into the dialog's input, not into the view's; two files on its single field ->
//   "Only one file fits here", nothing happens
// - Office > Settings (several buttons: logo, letterhead, import): the window says "Drag onto a row", each button's row takes the
//   drop; released on the letterhead row -> the letterhead upload runs (it used to be wired only when the button was clicked)
// - Documents (an own drop): the documents' drop uploads as before, no frame of dropany, the file input is not filled
// - an organisation's credit card statement (one "Upload receipt" per position): the position under the pointer stands out,
//   released there -> that position's input, not another one; released outside every row -> nothing
// - touch (no hover): no frame, nothing filled
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2591_c_dropany_ui', check, shots: 'P2591C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients,docs,files';
const pdf = lines => {  // a PDF with a text layer, hand-written
  const stream = `BT /F1 10 Tf 12 TL 40 760 Td\n${lines.map(x => `(${x}) Tj T*`).join('\n')}\nET`;
  const objs = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>', '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'];
  let out = '%PDF-1.4\n'; const offs = [];
  objs.forEach((o, i) => { offs.push(out.length); out += `${i + 1} 0 obj\n${o}\nendobj\n`; });
  const x = out.length;
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n${offs.map(o => String(o).padStart(10, '0') + ' 00000 n \n').join('')}trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${x}\n%%EOF\n`;
  return out;
};
const upload = async (ck, url, field, name, text, extra = {}) => { const fd = new FormData(); fd.append(field, new Blob([text], {type: 'application/pdf'}), name); for (const [k, v] of Object.entries(extra)) fd.append(k, v);
  const r = await fetch(B + url.replace(/^\//, ''), {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: ck}, body: fd}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const RPDF = pdf(['Rechnung Beispiel GmbH', 'Rechnungs-Nr. RE-77', 'Gesamtbetrag 23,80 EUR']), VPDF = pdf(['Vertrag Muster AG', 'Laufzeit 12 Monate']);  // two contents: the same bytes twice would be a duplicate
// in the page: files, a drag event on an element (a DataTransfer with the files, like a drag from the desktop), the spy of the
// file inputs' change (capture: before the module's handler empties the input)
const PAGE = `(() => {
  window.__mk = (name, type, text) => new File([text || 'x'], name, {type});
  window.__pdf = (name, v) => new File([v ? ${JSON.stringify(VPDF)} : ${JSON.stringify(RPDF)}], name || 'beleg.pdf', {type: 'application/pdf'});
  window.__drag = (el, type, files) => { if (typeof el === 'string') el = document.querySelector(el); const dt = new DataTransfer(); for (const f of files) dt.items.add(f);
    const b = el.getBoundingClientRect(), e = new DragEvent(type, {bubbles: true, cancelable: true, dataTransfer: dt, clientX: b.left + 4, clientY: b.top + 4}); el.dispatchEvent(e); return e; };
  window.__ch = [];
  if (!window.__chOn) { window.__chOn = 1; document.addEventListener('change', e => { const t = e.target; if (t.type === 'file') window.__ch.push(t.id || Object.entries(t.dataset).map(([k, v]) => k + '=' + v).join(',')); }, true); }
  return 1; })()`;

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CA, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  const card = await call(CA, 'POST', '/api/office/cards', {holder_name: 'Alice', last4: '4711'});
  const st = await upload(CA, `/api/office/cards/${card.id}/statements`, 'file', 'abrechnung.pdf', pdf(['Abrechnung vom 15.01.2025', 'Karte 5232 12XX XXXX 4711', '03.01. 04.01. Cafe Beispiel Berlin 12,50-', '05.01. 05.01. Druckerei Muster 30,00-', '07.01. 07.01. Buchladen Beispiel 18,40-', 'Neuer Saldo 60,90-']));
  check(st.http === 201, 'the statement is uploaded ' + st.http);
  const sid = st.id || st.statement?.id;
  const cf = await call(CA, 'POST', `/api/office/cards/statements/${sid}/confirm`, {accept_diff: true});
  check(cf.http < 300, 'its positions are confirmed ' + cf.http + ' ' + JSON.stringify(cf).slice(0, 160));
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fu.http < 300, 'a person without organisation ' + fu.http);
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(((await call(CF, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'frida is in no organisation');

  const ready = async (ev, expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.ok)`);
  const count = `fetch('/api/docs?ws=private&limit=200&facets=0', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => j.total)`;
  const hint = `(document.getElementById('dahint')?.textContent || '')`;
  const toastT = `(document.querySelector('#toast')?.textContent || '')`;

  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'frida');
    // ---- bookkeeping: one upload button -> the whole window
    await nav(B + '#office/books');
    check(await ready(ev, `!!document.querySelector('#bk-files')`, 80), 'the bookkeeping tab with "Upload files"');
    await ev(PAGE);
    check(await ev(`matchMedia('(hover: hover)').matches`), 'a mouse: hover');
    const n0 = await ev(count);
    await ev(`(() => { const e = __drag('#view', 'dragover', [__pdf()]); window.__dp = e.defaultPrevented; return 1; })()`);
    check(await ev(`window.__dp && document.documentElement.classList.contains('dropany-one')`), 'dragged over the view: the window takes the drop (frame)');
    check(await ev(`${hint} === 'Drop here: Upload files'`), 'the hint names the button ' + await ev(hint));
    await shot('p2591c-books-frame.png');
    await ev(`(() => { __drag('#view .ofcbar, #view', 'drop', [__pdf('kasse.pdf')]); return 1; })()`);
    check(await ev(`!document.getElementById('dahint') && !document.documentElement.classList.contains('dropany-one')`), 'released: the frame goes');
    check(await ev(`window.__ch.join() === 'bk-files'`), 'the file went into the button\'s own input ' + await ev(`window.__ch.join()`));
    check(await ready(ev, `${count}.then(n => n === ${n0} + 1)`, 80), 'the receipt is uploaded (one document more)');
    await ev(`(() => { document.querySelector('.bk-sheet [data-m="close"]')?.click(); document.querySelectorAll('.modal').forEach(m => m.remove()); return 1; })()`);
    // a wrong type: a hint, nothing uploaded
    await ev(`(() => { window.__ch = []; __drag('#view', 'dragover', [__mk('tool.exe', 'application/x-msdownload')]); __drag('#view', 'drop', [__mk('tool.exe', 'application/x-msdownload')]); return 1; })()`);
    check(await ready(ev, `/This file type does not fit here/.test(${toastT})`, 20), 'a wrong type: "This file type does not fit here" ' + await ev(toastT));
    check(await ev(`window.__ch.length === 0`), 'a wrong type: the input stays empty');
    await sleep(800);
    check(await ev(count) === n0 + 1, 'a wrong type: nothing uploaded');
    // ---- a dialog on top: its input, not the view's
    await ev(`(() => { window.__ch = []; const m = modal('<h3>Import</h3><div class="row"><label class="btn" id="p2591-l">Choose CSV<input type="file" id="p2591-f" accept=".csv,text/csv" hidden></label></div>'); m.classList.add('p2591dlg'); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.p2591dlg #p2591-f')`, 20), 'a dialog with one upload button is open');
    await ev(`(() => { __drag('.p2591dlg .card', 'dragover', [__mk('kunden.csv', 'text/csv', 'a;b')]); return 1; })()`);
    check(await ev(`${hint} === 'Drop here: Choose CSV'`), 'the dialog: the hint names the dialog\'s button ' + await ev(hint));
    await shot('p2591c-dialog.png');
    await ev(`(() => { __drag('.p2591dlg .card', 'drop', [__mk('kunden.csv', 'text/csv', 'a;b')]); return 1; })()`);
    check(await ev(`window.__ch.join() === 'p2591-f'`), 'the dialog: the file went into its input, not into the view\'s ' + await ev(`window.__ch.join()`));
    await ev(`(() => { window.__ch = []; __drag('.p2591dlg .card', 'drop', [__mk('a.csv', 'text/csv', 'a'), __mk('b.csv', 'text/csv', 'b')]); return 1; })()`);
    check(await ready(ev, `/Only one file fits here/.test(${toastT})`, 20), 'two files on a single field: "Only one file fits here" ' + await ev(toastT));
    check(await ev(`window.__ch.length === 0`), 'two files on a single field: nothing filled');
    await ev(`(() => { document.querySelectorAll('.modal').forEach(m => m.remove()); return 1; })()`);
    // ---- office settings: several buttons -> rows; the letterhead row uploads through its input's change
    await nav(B + '#office/settings');
    check(await ready(ev, `!!document.querySelector('#bpset [data-bp-act="pick"]') && !!document.querySelector('#os-logo')`, 80), 'the office settings with logo and letterhead');
    await ev(PAGE);
    await ev(`(() => { window.__bp = null; window.bp_upload = f => { window.__bp = f && f.name; }; return 1; })()`);
    await ev(`(() => { const e = __drag('#bpset [data-bp-act="pick"]', 'dragover', [__pdf('briefpapier.pdf')]); window.__de = e.dataTransfer.dropEffect; return 1; })()`);
    check(await ev(`${hint} === 'Drag onto a row'`), 'several buttons: "Drag onto a row" ' + await ev(hint));
    // under load the settings may render once more after the first dragover (it clears the marks): drag again until it holds
    check(await ready(ev, `(() => { const e = __drag('#bpset [data-bp-act="pick"]', 'dragover', [__pdf('briefpapier.pdf')]); window.__de = e.dataTransfer.dropEffect; return document.querySelectorAll('.dropany-zone').length >= 2 && !!document.querySelector('#bpset [data-bp-act="pick"]').closest('.dropany-over') && document.querySelectorAll('.dropany-over').length === 1 && window.__de === 'copy'; })()`, 40), 'each button\'s row is framed, the letterhead row under the pointer stands out ' + await ev(`[...document.querySelectorAll('.dropany-zone')].map(z => z.tagName + '.' + z.className + (z.classList.contains('dropany-over') ? '*' : '')).join(' | ') + ' de=' + window.__de`));
    await shot('p2591c-settings-rows.png');
    await ev(`(() => { __drag('#bpset [data-bp-act="pick"]', 'drop', [__pdf('briefpapier.pdf')]); return 1; })()`);
    check(await ev(`window.__ch.join() === 'bp-file'`), 'released on the letterhead row: its input ' + await ev(`window.__ch.join()`));
    check(await ready(ev, `window.__bp === 'briefpapier.pdf'`, 20), 'the letterhead upload runs from the input\'s change (not only after a click)');
    // ---- documents keep their own drop
    await nav(B + '#docs');
    check(await ready(ev, `!!document.querySelector('.dc-view')`, 80), 'the documents view');
    await ev(PAGE);
    const d0 = await ev(count);
    await ev(`(() => { __drag('.dc-view', 'dragover', [__pdf('vertrag.pdf')]); return 1; })()`);
    check(await ev(`!document.documentElement.classList.contains('dropany-on') && !document.getElementById('dahint')`), 'documents: no frame of dropany (its own drop)');
    await ev(`(() => { __drag('.dc-view', 'drop', [__pdf('vertrag.pdf', 1)]); return 1; })()`);
    check(await ready(ev, `${count}.then(n => n === ${d0} + 1)`, 80), 'documents: its own drop uploads as before ' + await ev(toastT));
    check(await ev(`window.__ch.length === 0`), 'documents: no file input filled');
    // ---- an organisation's credit card statement: one button per position
    await ev(`fetch('/api/auth/logout', {method: 'POST', headers: {'X-Requested-With': 'kalmido'}}).then(r => r.ok)`);
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    await nav(B + '#office/cards');
    check(await ready(ev, `!!document.querySelector('[data-cc="card"]')`, 100), 'the card is listed');
    await ev(`(() => { document.querySelector('[data-cc="card"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('[data-cc="stmt"]')`), 'the card lists its statement');
    await ev(`(() => { document.querySelector('[data-cc="stmt"]').click(); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('[data-cc-rc]').length >= 2`), 'the positions each have "Upload receipt" ' + await ev(`document.querySelectorAll('[data-cc-rc]').length`));
    await ev(PAGE);
    const ids = await ev(`[...document.querySelectorAll('[data-cc-rc]')].map(i => i.dataset.ccRc).join()`);
    const second = ids.split(',')[1];
    await ev(`(() => { const row = document.querySelectorAll('[data-cc-rc]')[1].closest('.bnkrow'); const e = __drag(row.querySelector('.bnkhead') || row, 'dragover', [__pdf('druckerei.pdf')]); window.__de = e.dataTransfer.dropEffect; return 1; })()`);
    check(await ev(`${hint} === 'Drag onto a row' && document.querySelectorAll('.dropany-zone').length === document.querySelectorAll('[data-cc-rc]').length`), 'the statement: every position is a drop row');
    check(await ev(`document.querySelectorAll('[data-cc-rc]')[1].closest('.dropany-over') !== null && document.querySelectorAll('[data-cc-rc]')[0].closest('.dropany-over') === null && window.__de === 'copy'`),
      'the position under the pointer stands out, the others not');
    await shot('p2591c-card-rows.png');
    // outside every row: no drop
    await ev(`(() => { const h = document.querySelector('.ccfacts') || document.querySelector('#view h3'); const e = __drag(h, 'dragover', [__pdf()]); window.__de = e.dataTransfer.dropEffect; __drag(h, 'drop', [__pdf()]); return 1; })()`);
    check(await ev(`window.__de === 'none' && window.__ch.length === 0`), 'outside every row: no drop, nothing filled');
    await ev(`(() => { const row = document.querySelectorAll('[data-cc-rc]')[1].closest('.bnkrow'); __drag(row.querySelector('.bnkhead') || row, 'drop', [__pdf('druckerei.pdf')]); return 1; })()`);
    check(await ev(`window.__ch.join() === 'ccRc=${second}'`), 'released on the second position: its input, no other ' + await ev(`window.__ch.join()`));
  }, false);

  // ---- touch: nothing changes
  await firefox(async ({cmd, ev, ctx, nav}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); return 1; })()`);
    await signIn(ev, 'frida');
    await nav(B + '#office/books');
    check(await ready(ev, `!!document.querySelector('#bk-files')`, 80), 'touch: the bookkeeping tab');
    await ev(PAGE);
    check(await ev(`!matchMedia('(hover: hover)').matches`), 'touch: no hover');
    await ev(`(() => { const e = __drag('#view', 'dragover', [__pdf()]); window.__dp = e.defaultPrevented; __drag('#view', 'drop', [__pdf()]); return 1; })()`);
    check(await ev(`!window.__dp && !document.getElementById('dahint') && window.__ch.length === 0`), 'touch: no frame, nothing filled');
  }, true);

  console.log(`p2591_c_dropany_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
