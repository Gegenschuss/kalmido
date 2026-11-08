// 2.583.0 UI test, part A (#4835 the document view, includes #4829 and #4832): own container (start.sh), jsdom + Firefox
// kalmido-suite: fresh
// (1440 px and phone 390 px). Invented data only. P2583A_NOSTART=1 = the container runs.
// - a click on a card leaves the cards: the document view with its own address #docs/<id> (head: back, title, "1 of 3",
//   Download / Actions / Delete; the strip of the list, the fields in tabs, the preview), no dialog, no pane
// - the arrow keys right / left leaf through the list as shown (the address follows), not while typing in a field; the strip
//   jumps to a document
// - a field saves without a button ("Saved" with Undo in the head; Undo takes it back on the server)
// - Esc leads back to the list (#docs) with the card of the document looked at last in view and focused
// - the address #docs/<id> opened anew (reload) draws the view directly
// - "To review": Checked brings the next one, the arrows go on, Esc back to "To review"; Full screen leafs, the view follows
// - Firefox: the head stays in view when the fields scroll; the grips go up to the edge (#4829), Home / double click = standard;
//   three columns side by side; every page of a three-page PDF: page 1 drawn sharp at once, page 3 when scrolled to
//   (the counter "Page 3 / 3"), a zoom draws the page anew at its new size, "Whole page" fits the page into the box; phone:
//   one column, the preview above the fields
// P4: alice works without an organisation (private documents): the person without an organisation (freelancer-matrix: docs)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2583_a_docview', check, shots: 'P2583A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2583A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(200); } return fn(); };
const click = (w, el, o = {}) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const keyOn = (w, el, k, o = {}) => el.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true, ...o}));

function pdf(pages) {  // a PDF with one text page per entry, written by hand
  const esc = s => s.replace(/[\\()]/g, c => '\\' + c), n = pages.length;
  const objs = ['<< /Type /Catalog /Pages 2 0 R >>', `<< /Type /Pages /Kids [${pages.map((_, i) => `${4 + 2 * i} 0 R`).join(' ')}] /Count ${n} >>`,
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'];
  pages.forEach((lines, i) => {
    const st = 'BT /F1 12 Tf 60 740 Td 16 TL ' + lines.map(l => `(${esc(l)}) '`).join(' ') + ' ET';
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
async function upload(name, pages) {
  const fd = new FormData();
  fd.append('files', new Blob([pdf(pages)], {type: 'application/pdf'}), name);
  fd.append('ws', 'private');
  const r = await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
  const id = (await r.json()).ids[0];
  await until(async () => ['done', 'failed'].includes((await call('GET', `/api/docs/${id}`)).state), 150);
  return id;
}

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'});
  const D1 = await upload('handbook.pdf', [['Kita Beispiel', 'Elternhandbuch', 'Datum 01.09.2026'], ['Seite zwei', 'Oeffnungszeiten'], ['Seite drei', 'Kontakt']]);
  const D2 = await upload('power.pdf', [['Stadtwerke Musterstadt', 'Abschlag Strom', 'Datum 03.10.2026']]);
  const D3 = await upload('phone.pdf', [['Telefon Beispiel GmbH', 'Monatsrechnung', 'Datum 05.10.2026']]);
  check([D1, D2, D3].every(Boolean), 'three documents uploaded (one with three pages)');

  // ================= computer (jsdom): the card -> the view, arrow keys, the strip, saving, Esc back
  const w = await boot({user: 'alice', hash: 'docs'}), d = w.document;
  await until(() => d.querySelectorAll('.dc-card').length === 3);
  const order = w.eval('DC.docs.map(x => x.id)');
  check(order.length === 3, 'three cards in the list');
  const viewId = () => +(d.querySelector('.dv-view .dc-body')?.dataset.id || 0);
  click(w, d.querySelector(`.dc-view [data-dco="${order[0]}"]`));
  check(await until(() => viewId() === order[0] && w.location.hash === `#ablage/${order[0]}`), 'a click on a card opens the document view with its own address ' + w.location.hash);
  check(!d.querySelector('.dc-view') && !d.querySelector('.modal') && !d.querySelector('.dc-pane'), '... the cards are left (no list, no dialog, no pane)');
  const v = () => d.querySelector('.dv-view');
  check(v().querySelector('.dv-head [data-dc="close"]') && v().querySelector('#dc-h')?.textContent.trim() && /1 of 3/.test(v().querySelector('.dv-head .dc-navn')?.textContent || ''), '... the head: back, the title, "1 of 3"');
  check(v().querySelector('.dv-head .dv-dl[download]') && v().querySelector('.dv-head [data-dc="actsmore"]') && v().querySelector('.dv-head [data-dc="del"]'), '... Download, Actions, Delete in the head');
  check(v().querySelectorAll('.dv-strip [data-dvgo]').length === 3 && v().querySelector(`.dv-strip [data-dvgo="${order[0]}"]`)?.classList.contains('on'), '... the strip with the documents of the list, the open one marked');
  const tabs = [...v().querySelectorAll('[role="tab"]')].map(t => t.dataset.dvtab);
  check(tabs.join() === 'details,text,hist,share', '... the tabs Details / Content / History / Shares ' + tabs.join());
  check(v().querySelector('#dv-p-details #dc-sender') && v().querySelector('#dv-p-details .dv-more #dc-amount') && v().querySelector('.dv-pv .dv-pages'), '... the fields, the rare ones under "More fields", the preview');
  check(![...v().querySelectorAll('button')].some(b => /^\s*Save\s*$/.test(b.textContent)), '... no Save button');

  // the arrow keys right / left, not while typing
  d.activeElement?.blur?.();
  keyOn(w, d.body, 'ArrowRight');
  check(await until(() => viewId() === order[1] && w.location.hash === `#ablage/${order[1]}`), 'arrow right: the next document, the address follows');
  check(/2 of 3/.test(v().querySelector('.dc-navn')?.textContent || '') && v().querySelector(`.dv-strip [data-dvgo="${order[1]}"]`)?.classList.contains('on'), '... "2 of 3", the strip follows');
  keyOn(w, d.body, 'ArrowLeft');
  check(await until(() => viewId() === order[0]), 'arrow left: the one before');
  keyOn(w, d.body, 'ArrowLeft');
  await sleep(400);
  check(viewId() === order[0], '... the first stays');
  const snd = v().querySelector('#dc-sender');
  snd.focus(); keyOn(w, snd, 'ArrowRight');
  await sleep(400);
  check(viewId() === order[0], '... not while typing in a field');
  snd.blur();
  click(w, v().querySelector(`.dv-strip [data-dvgo="${order[2]}"]`));
  check(await until(() => viewId() === order[2] && w.location.hash === `#ablage/${order[2]}`), 'a click in the strip jumps to that document');

  // a field saves without a button, Undo in the head takes it back
  const f = v().querySelector('#dc-sender'), old = f.value;
  f.value = 'Beispiel Telefon'; f.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(async () => (await call('GET', `/api/docs/${order[2]}`)).sender?.name === 'Beispiel Telefon'), 'a changed field saves at once (no button)');
  check(await until(() => /Saved/.test(v().querySelector('.dv-saved')?.textContent || '') && v().querySelector('.dv-saved [data-dc="dvundo"]')), '... the head says "Saved" with Undo');
  click(w, v().querySelector('.dv-saved [data-dc="dvundo"]'));
  check(await until(async () => ((await call('GET', `/api/docs/${order[2]}`)).sender?.name || '') === old), '... Undo takes it back on the server');
  const bf = v().querySelector('#dc-sender');
  check(await until(() => v().querySelector('#dc-sender')?.value === old), '... and in the field ' + bf?.value);

  // Esc: back to the list, the card of the document looked at last in view and focused
  d.activeElement?.blur?.();
  keyOn(w, d.body, 'Escape');
  check(await until(() => !v() && d.querySelector('.dc-view .dc-card') && /^#ablage\/docs$/.test(w.location.hash)), 'Esc leads back to the list ' + w.location.hash);
  check(await until(() => d.querySelector(`.dc-card[data-k="dc${order[2]}"]`)?.classList.contains('dc-cur') && d.activeElement === d.querySelector(`.dc-view [data-dco="${order[2]}"]`)), '... the card of the document looked at last is marked and has the focus');
  w.close();

  // ================= the address opened anew (reload): the view directly
  const w2 = await boot({user: 'alice', hash: `docs/${D2}`}), d2 = w2.document;
  check(await until(() => +(d2.querySelector('.dv-view .dc-body')?.dataset.id || 0) === D2 && !d2.querySelector('.dc-view') && !d2.querySelector('.modal')), 'the address #docs/<id> loads the view directly');
  check(await until(() => /of 3/.test(d2.querySelector('.dv-view .dc-navn')?.textContent || '')), '... with its place in the list ("x of 3")');
  // from p2521_c_docread_ui (#4476): Full screen leafs through the list without closing, the view follows
  const at = w2.eval('DC.docs.findIndex(x => x.id === DC.doc.id)'), lb = () => d2.querySelector('.lightbox.pview');
  click(w2, d2.querySelector('.dv-view [data-dc="view"]'));
  check(await until(() => lb()?.querySelector('.pvdocs [data-pv="dnext"]')), 'Full screen: the buttons previous / next document');
  const dir = at < 2 ? 'dnext' : 'dprev', to = w2.eval(`DC.docs[${at < 2 ? at + 1 : at - 1}].id`);
  click(w2, lb().querySelector(`[data-pv="${dir}"]`));
  check(await until(() => +(d2.querySelector('.dv-view .dc-body')?.dataset.id || 0) === to && w2.location.hash === `#ablage/${to}`), '... the next document in the full screen, the view follows');
  check(d2.querySelectorAll('.lightbox').length === 1, '... one full screen, not one per document');
  click(w2, lb().querySelector('[data-pv="x"]'));
  check(await until(() => !lb() && +(d2.querySelector('.dv-view .dc-body')?.dataset.id || 0) === to), '... closed, the view stays on that document');
  click(w2, d2.querySelector('.dv-view [data-dc="close"]'));
  check(await until(() => !d2.querySelector('.dv-view') && d2.querySelector('.dc-view .dc-card') && w2.location.hash === '#ablage/docs'), '... "Documents" (back) leads to the list');
  w2.close();

  // ================= from p2521_c_docread_ui (#4476): "To review" - Checked brings the next one, the arrows go on from there
  for (const id of [D1, D2, D3]) await call('POST', `/api/docs/${id}/review`, {done: false});
  const w3 = await boot({user: 'alice', hash: 'docs/review'}), d3 = w3.document;
  await until(() => d3.querySelectorAll('.dc-card').length === 3);
  const rv = w3.eval('DC.docs.map(x => x.id)'), vid = () => +(d3.querySelector('.dv-view .dc-body')?.dataset.id || 0);
  click(w3, d3.querySelector(`.dc-view [data-dco="${rv[0]}"]`));
  await until(() => vid() === rv[0] && d3.querySelector('.dv-view [data-dc="checked"]'));
  click(w3, d3.querySelector('.dv-view [data-dc="checked"]'));
  check(await until(() => vid() === rv[1] && d3.querySelector('.dv-view [data-dc="checked"]')), 'To review: after "Checked" the next one at once');
  d3.activeElement?.blur?.();
  keyOn(w3, d3.body, 'ArrowRight');
  check(await until(() => vid() === rv[2]), '... arrow right goes on with the one after it');
  keyOn(w3, d3.body, 'Escape');
  check(await until(() => w3.location.hash === '#ablage/review' && d3.querySelector('.dc-view')), '... Esc leads back to "To review"');
  w3.close();

  // ================= phone (jsdom): the same view, back to the list
  const m = await boot({user: 'alice', hash: 'docs', mobile: true}), dm = m.document;
  await until(() => dm.querySelectorAll('.dc-card').length === 3);
  click(m, dm.querySelector(`[data-dco="${D3}"]`));
  check(await until(() => dm.querySelector('.dv-view #dc-sender') && !dm.querySelector('.modal.dc-md')), 'phone: the document opens as the view (no sheet)');
  click(m, dm.querySelector('.dv-view .dv-back'));
  check(await until(() => !dm.querySelector('.dv-view') && dm.querySelector('.dc-view .dc-card')), 'phone: back leads to the list');
  m.close();

  // ================= Firefox: the real layout and the pages
  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await nav(B + '#docs');
    const wait = async (js, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(js).catch(() => false)) return true; await sleep(250); } return false; };
    check(await wait(`document.querySelectorAll('.dc-card').length === 3`), 'Firefox: three cards');
    await ev(`(document.querySelector('.dc-view [data-dco="${D1}"]').click(), 1)`);
    check(await wait(`!!document.querySelector('.dv-view #dc-sender') && location.hash === '#ablage/${D1}'`), 'Firefox: the view opens');
    const r = await ev(`(() => { const q = s => document.querySelector('.dv-view ' + s).getBoundingClientRect(); const s = q('.dv-strip'), m = q('.dv-mask'), p = q('.dv-pv'), h = q('.dv-head');
      return {sr: Math.round(s.right), ml: Math.round(m.left), mr: Math.round(m.right), pl: Math.round(p.left), pw: Math.round(p.width), pb: Math.round(p.bottom), ht: Math.round(h.bottom), mt: Math.round(m.top), vh: innerHeight}; })()`);
    check(r && r.sr <= r.ml && r.mr <= r.pl && r.pw > r.mr - r.ml && r.mt >= r.ht && r.pb <= r.vh, 'Firefox: strip, fields and preview side by side below the head, the preview the widest ' + JSON.stringify(r));
    check(await wait(`document.querySelectorAll('.dv-pages .dv-pg').length === 3 && !!document.querySelector('.dv-pages .dv-pg[data-i="0"] canvas')`, 80), 'Firefox: three page boxes, page 1 drawn');
    const sharp = await ev(`(() => { const c = document.querySelector('.dv-pages .dv-pg[data-i="0"] canvas'), r = c.getBoundingClientRect(); return {cw: c.width, w: Math.round(r.width), dpr: devicePixelRatio}; })()`);
    check(sharp && sharp.cw >= Math.floor(sharp.w * Math.min(sharp.dpr, 3)) - 2 && sharp.w > 300, 'Firefox: page 1 sharp at the size shown ' + JSON.stringify(sharp));
    check(await ev(`!document.querySelector('.dv-pages .dv-pg[data-i="2"] canvas') || document.querySelector('.dv-pages').scrollHeight < document.querySelector('.dv-pages').clientHeight + 1400`), 'Firefox: page 3 waits until it comes near (or the box is short)');
    await ev(`(() => { const b = document.querySelector('.dv-pages'); b.scrollTop = b.scrollHeight; b.dispatchEvent(new Event('scroll')); return 1; })()`);
    check(await wait(`!!document.querySelector('.dv-pages .dv-pg[data-i="2"] canvas')`, 60), 'Firefox: scrolled down, page 3 is drawn');
    check(await wait(`/Page 3 \\/ 3/.test(document.querySelector('.dv-pgn').textContent)`), 'Firefox: the counter says "Page 3 / 3"');
    await shot('p2583-docview-1440.png');
    const w0 = await ev(`document.querySelector('.dv-pages .dv-pg[data-i="2"] canvas').width`);
    await ev(`(document.querySelector('.dv-view [data-dc="dvz:in"]').click(), 1)`);
    check(await wait(`(() => { const c = document.querySelector('.dv-pages .dv-pg[data-i="2"] canvas'); return !!c && c.width > ${w0} * 1.15; })()`, 60), 'Firefox: zoomed in, the page is drawn anew at its new size');
    await ev(`(document.querySelector('.dv-view [data-dc="dvz:page"]').click(), 1)`);
    check(await wait(`(() => { const b = document.querySelector('.dv-pages'), p = b.querySelector('.dv-pg'); return p.getBoundingClientRect().height <= b.clientHeight && document.querySelector('[data-dc="dvz:page"]').getAttribute('aria-pressed') === 'true'; })()`), 'Firefox: "Whole page" fits the page into the box');
    await ev(`(document.querySelector('.dv-view [data-dc="dvz:width"]').click(), 1)`);
    // from p2519_a_docpane_sticky_ui (#4467): the fields scrolled to their end, the head with Back stays in view and clickable
    const hv = await ev(`(() => { const m = document.querySelector('.dv-mask'); m.scrollTop = m.scrollHeight; const b = document.querySelector('.dv-back').getBoundingClientRect(); const hit = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2); return {top: Math.round(b.top), hit: !!hit && !!hit.closest('.dv-back')}; })()`);
    check(hv && hv.top >= 0 && hv.hit, 'Firefox: the fields scrolled, Back stays in view and clickable ' + JSON.stringify(hv));
    // #4829 (and #4399 of p2521_c): the grips go up to the edge (the preview keeps a small rest), kept on the device, Home = standard
    const gr = async () => JSON.parse(await ev(`JSON.stringify({m: Math.round(document.querySelector('.dv-mask').getBoundingClientRect().width), p: Math.round(document.querySelector('.dv-pv').getBoundingClientRect().width), ls: LS.get('dv.maskW', 0)})`));
    const g0 = await gr();
    await ev(`(() => { const g = document.querySelector('[data-dvgrip="mask"]'), r = g.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + 40, o = k => ({bubbles: true, cancelable: true, button: 0, pointerId: 1, clientX: k, clientY: y}); g.dispatchEvent(new PointerEvent('pointerdown', o(x))); for (let k = 1; k <= 10; k++) document.dispatchEvent(new PointerEvent('pointermove', o(x + k * 200))); document.dispatchEvent(new PointerEvent('pointerup', o(x + 2000))); return 1; })()`);  // dragged far to the right
    const g1 = await gr();
    check(g1.m > g0.m + 300 && g1.p <= 120 && g1.ls, 'Firefox: the grip of the fields goes up to the edge, the preview keeps a small rest, kept ' + JSON.stringify([g0, g1]));
    await ev(`(document.querySelector('[data-dvgrip="mask"]').dispatchEvent(new MouseEvent('dblclick', {bubbles: true})), 1)`);
    check(await wait(`Math.abs(document.querySelector('.dv-mask').getBoundingClientRect().width - ${g0.m}) <= 2 && !LS.get('dv.maskW', 0)`, 20), 'Firefox: a double click: the standard width again ' + await ev(`JSON.stringify({n: document.querySelectorAll('.dv-view').length, st: document.querySelector('.dv-view').getAttribute('style'), m: document.querySelector('.dv-mask').getBoundingClientRect().width, cols: getComputedStyle(document.querySelector('.dv-cols')).gridTemplateColumns})`));
    const g2 = await gr();
    await ev(`(() => { const g = document.querySelector('[data-dvgrip="mask"]'); g.focus(); g.dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowRight', bubbles: true, cancelable: true})); return 1; })()`);
    check(await wait(`document.querySelector('.dv-mask').getBoundingClientRect().width >= ${g2.m + 12} && LS.get('dv.maskW', 0) > 0`, 20), 'Firefox: the arrow key on the grip widens it by a step ' + JSON.stringify([g2, await gr(), await ev(`document.querySelectorAll('.dv-view').length + ' ' + document.querySelector('.dv-view').getAttribute('style')`)]));
    await ev(`(document.querySelector('[data-dvgrip="mask"]').dispatchEvent(new KeyboardEvent('keydown', {key: 'Home', bubbles: true, cancelable: true})), 1)`);
    check(!(await gr()).ls, '... Home: the standard width again');
    await ev(`(() => { const g = document.querySelector('[data-dvgrip="strip"]'), r = g.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + 40, o = k => ({bubbles: true, cancelable: true, button: 0, pointerId: 1, clientX: k, clientY: y}); g.dispatchEvent(new PointerEvent('pointerdown', o(x))); for (let k = 1; k <= 10; k++) document.dispatchEvent(new PointerEvent('pointermove', o(x + k * 200))); document.dispatchEvent(new PointerEvent('pointerup', o(x + 2000))); return 1; })()`);
    const g3 = JSON.parse(await ev(`JSON.stringify({s: Math.round(document.querySelector('.dv-strip').getBoundingClientRect().width), p: Math.round(document.querySelector('.dv-pv').getBoundingClientRect().width)})`));
    check(g3.s > 400 && g3.p <= 120, 'Firefox: the grip of the strip goes up to the edge too ' + JSON.stringify(g3));
    await ev(`(document.querySelector('[data-dvgrip="strip"]').dispatchEvent(new MouseEvent('dblclick', {bubbles: true})), 1)`);
    check(await wait(`!LS.get('dv.stripW', 0) && document.querySelector('.dv-strip').getBoundingClientRect().width < 160`), 'Firefox: a double click: the strip at its standard width');
    await ev(`(document.activeElement && document.activeElement.blur(), document.body.dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowLeft', bubbles: true, cancelable: true})), 1)`);  // D1 is the oldest: the last of the list
    check(await wait(`location.hash !== '#ablage/${D1}' && /2 of 3/.test(document.querySelector('.dc-navn').textContent)`), 'Firefox: arrow left leafs on (to the one before)');
    await ev(`(document.body.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true, cancelable: true})), 1)`);
    check(await wait(`!document.querySelector('.dv-view') && location.hash === '#ablage/docs' && document.querySelectorAll('.dc-card').length === 3`), 'Firefox: Esc, back in the list');
    // phone: one column, the preview above the fields
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + `#docs/${D1}`);
    check(await wait(`!!document.querySelector('.dv-view #dc-sender') && !!document.querySelector('.dv-pages .dv-pg canvas')`, 80), 'Firefox phone: the view with the drawn page');
    const p = await ev(`(() => { const pv = document.querySelector('.dv-pv').getBoundingClientRect(), m = document.querySelector('.dv-mask').getBoundingClientRect(), v = document.querySelector('.dv-view');
      return {pvb: Math.round(pv.bottom), mt: Math.round(m.top), pw: Math.round(pv.width), strip: getComputedStyle(document.querySelector('.dv-strip')).display, sw: v.scrollWidth, cw: v.clientWidth}; })()`);
    check(p && p.pvb <= p.mt && p.pw >= 340 && p.strip === 'none' && p.sw <= p.cw + 1, 'Firefox phone: one column, the preview above the fields, no strip, nothing sideways ' + JSON.stringify(p));
    await shot('p2583-docview-phone.png');
  });

  console.log(`p2583_a_docview: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
