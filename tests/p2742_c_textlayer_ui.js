// 2.742.0 UI test, part C (#4861): text in the preview of a document can be marked and copied, own container (start.sh),
// kalmido-suite: fresh
// jsdom + Firefox (1440 px, a mouse). Invented data only. P2742C2_NOSTART=1 = the container runs.
// - Firefox: over each drawn page of a text PDF lies the text layer of pdf.js (its words as text, transparent, the size of
//   the page); a drag with the mouse over a line marks its text and does not move the page (no scroll, no leafing); a zoom
//   draws page and layer anew at the new scale, the layer still covers the page; a page without its canvas has no layer;
//   Ctrl+A in the preview marks the pages' text (not the app), the copy then gets the text of ALL pages (also page 3);
//   Shift+arrow (extending a marking) does not leaf; the full-screen viewer (pdfview.js) has the layer too
// - jsdom: "Copy text" with the recognised text for a scan (recognised by OCR) and an image, not for a PDF with text; a click
//   copies the recognised text; the recognised text goes into the page as text only (never as markup)
// P4: alice works without an organisation (private documents): the person without an organisation (freelancer-matrix: docs)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2742_c_textlayer', check, shots: 'P2742C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2742C2_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(200); } return fn(); };
const click = (w, el, o = {}) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));

function pdf(pages) {  // a PDF with one text page per entry, written by hand
  const esc = s => s.replace(/[\\()]/g, c => '\\' + c), n = pages.length;
  const objs = ['<< /Type /Catalog /Pages 2 0 R >>', `<< /Type /Pages /Kids [${pages.map((_, i) => `${4 + 2 * i} 0 R`).join(' ')}] /Count ${n} >>`,
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'];
  pages.forEach((lines, i) => {
    const st = 'BT /F1 18 Tf 60 740 Td 24 TL ' + lines.map(l => `(${esc(l)}) '`).join(' ') + ' ET';
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
  await call('POST', '/api/admin/setup', {lang: 'en'});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'});
  const D1 = await upload('handbook.pdf', [['Kita Beispiel', 'Elternhandbuch Seite eins', 'Datum 01.09.2026'], ['Seite zwei', 'Oeffnungszeiten'], ['Seite drei', 'Kontaktliste Ende']]);
  check(D1, 'a text PDF with three pages uploaded');

  // ================= jsdom: "Copy text" for a scan / an image with the recognised text
  const w = await boot({user: 'alice', hash: `docs/${D1}`}), d = w.document;
  check(await until(() => d.querySelector('.dv-view .dv-pvbar') && w.eval(`DC.doc?.id === ${D1}`)), 'the view of the document');
  check(!d.querySelector('.dv-view [data-dc="dvcopy"]'), 'a PDF with text: no "Copy text" (it is marked in the preview)');
  const MARK = '<img alt=x data-bad=1> Recognised words';
  w.eval(`DC.doc = {...DC.doc, method: 'ocr', text: ${JSON.stringify(MARK)}}; dc_mdDraw(document.querySelector('.dv-view'))`);
  check(await until(() => d.querySelector('.dv-view [data-dc="dvcopy"]')), 'a scan (recognised by OCR): "Copy text"');
  w.eval(`window.__clip = null; Object.defineProperty(navigator, 'clipboard', {configurable: true, value: {writeText: async t => { window.__clip = t; }}})`);
  click(w, d.querySelector('.dv-view [data-dc="dvcopy"]'));
  check(await until(() => w.eval('window.__clip') === MARK), 'a click copies the recognised text');
  check(!d.querySelector('.dv-view img[data-bad], .dv-view [data-bad]'), 'the recognised text is no markup in the page');
  w.eval(`DC.doc = {...DC.doc, method: 'none', mime: 'image/png', text: 'Bild Text'}; dc_mdDraw(document.querySelector('.dv-view'))`);
  check(await until(() => d.querySelector('.dv-view [data-dc="dvcopy"]')), 'an image with recognised text: "Copy text"');
  w.eval(`DC.doc = {...DC.doc, mime: 'image/png', text: ''}; dc_mdDraw(document.querySelector('.dv-view'))`);
  check(await until(() => !d.querySelector('.dv-view [data-dc="dvcopy"]')), 'nothing recognised: no button');
  w.close();

  // ================= Firefox: marking with the mouse, zoom, Ctrl+A, the full-screen viewer
  await firefox(async ({cmd, ev, nav, ctx, shot, drag}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await nav(B + `#docs/${D1}`);
    const wait = async (js, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(js).catch(() => false)) return true; await sleep(250); } return false; };
    const P0 = `document.querySelector('.dv-pages .dv-pg[data-i="0"]')`;
    check(await wait(`!!${P0}?.querySelector('canvas') && !!${P0}.querySelector('.textLayer span')`, 100), 'Firefox: page 1 drawn with its text layer');
    // 2.771.0 (#5338): CI v2.762.0 "tl is null" - a redraw (zoom, the fields beside it) swaps the page's layer: measure once
    // page and layer are both there again (a real state, no fixed time)
    const geo = async () => { for (let i = 0; ; i++) { await wait(`!!${P0}?.querySelector('canvas') && !!${P0}.querySelector('.textLayer span')`, 80); try { return await geo1(); } catch (e) { if (i >= 5) throw e; } } };
    const geo1 = async () => JSON.parse(await ev(`(() => { const p = ${P0}, tl = p.querySelector('.textLayer'), a = p.getBoundingClientRect(), b = tl.getBoundingClientRect(), sp = [...tl.querySelectorAll('span')].find(s => /Elternhandbuch/.test(s.textContent)), c = sp && sp.getBoundingClientRect(), box = document.querySelector('.dv-pages');
      return JSON.stringify({dl: Math.round(b.left - a.left), dt: Math.round(b.top - a.top), dw: Math.round(b.width - a.width), dh: Math.round(b.height - a.height), color: sp && getComputedStyle(sp).color, sel: getComputedStyle(tl).userSelect,
        sx: c && Math.round(c.left - a.left), sy: c && Math.round(c.top - a.top), sw: c && Math.round(c.width), sh: c && Math.round(c.height), pw: Math.round(a.width), s: box._s, sf: tl.style.getPropertyValue('--scale-factor')}); })()`));
    // the layout settles (the fields load beside it, a new width draws the page anew): the same layer over three looks
    let stable = 0;
    for (let i = 0; i < 40 && stable < 3; i++) { stable = await ev(`(() => { const tl = ${P0}.querySelector('.textLayer'); const same = !!tl && tl === window.__tl; window.__tl = tl; return same; })()`) ? stable + 1 : 0; if (stable < 3) await sleep(250); }
    check(stable >= 3, 'Firefox: the page stands still');
    const g0 = await geo();
    check(Math.abs(g0.dl) <= 2 && Math.abs(g0.dt) <= 2 && Math.abs(g0.dw) <= 3 && Math.abs(g0.dh) <= 3, 'Firefox: the layer covers the page ' + JSON.stringify(g0));
    check(g0.color === 'rgba(0, 0, 0, 0)' && g0.sel !== 'none', 'Firefox: its text is invisible and can be marked ' + JSON.stringify([g0.color, g0.sel]));
    // the line "Elternhandbuch Seite eins" sits where pdf.js drew it: 60 pt from the left, the second line from the top
    const s0 = g0.s;
    check(g0.sw > 0 && Math.abs(g0.sx - 60 * s0) <= 6 + 2 * s0 && g0.sy > 40 * s0 && g0.sy < 90 * s0, 'Firefox: the words lie on the drawn line ' + JSON.stringify(g0));
    // a drag with the mouse over the line marks its text; the page does not move, the view does not leaf
    const pos = JSON.parse(await ev(`(() => { const sp = [...${P0}.querySelectorAll('.textLayer span')].find(s => /Elternhandbuch/.test(s.textContent)), r = sp.getBoundingClientRect(), b = document.querySelector('.dv-pages');
      return JSON.stringify({x: r.left + 2, y: r.top + r.height / 2, w: r.width, st: b.scrollTop, sl: b.scrollLeft, h: location.hash}); })()`));
    await drag(pos.x, pos.y, pos.w - 4, 0, 'mouse');
    const after = JSON.parse(await ev(`JSON.stringify({sel: String(getSelection()), st: document.querySelector('.dv-pages').scrollTop, sl: document.querySelector('.dv-pages').scrollLeft, h: location.hash})`));
    check(/Elternhandbuch/.test(after.sel), 'Firefox: a drag with the mouse marks the words ' + JSON.stringify(after.sel));
    check(after.st === pos.st && after.sl === pos.sl && after.h === pos.h, 'Firefox: marking does not move the page or leaf ' + JSON.stringify([pos, after]));
    await shot('p2742c-textlayer-marked.png');
    // Shift + arrow right (extending a marking) does not leaf
    // the key handlers run at once: dc_step watched while the key is sent (no wait needed)
    const leafed = await ev(`(() => { const s0 = dc_step; let n = 0; dc_step = (...a) => { n++; return s0(...a); };
      try { document.querySelector('.dv-pages').dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowRight', shiftKey: true, bubbles: true, cancelable: true})); } finally { dc_step = s0; } return n; })()`);
    // 2.771.0 (#5338): since #4887 a #docs/<id> link opens the document under #ablage/...: the hash before the key is the measure
    const hk = await ev(`location.hash`);
    check(leafed === 0 && hk === pos.h, 'Firefox: Shift+arrow does not leaf ' + JSON.stringify({leafed, before: pos.h, after: hk}));
    // zoom: page and layer anew at the new scale, the layer still covers the page
    await ev(`(document.querySelector('.dv-view [data-dc="dvz:in"]').click(), 1)`);
    check(await wait(`(() => { const p = ${P0}, tl = p.querySelector('.textLayer'), b = document.querySelector('.dv-pages'); return !!tl && +tl.style.getPropertyValue('--scale-factor') === b._s && b._s > ${s0} * 1.15 && !!p.querySelector('canvas') && p.dataset.s === String(b._s); })()`, 80), 'Firefox: zoomed, the layer at the new scale');
    const g1 = await geo();
    check(Math.abs(g1.dw) <= 3 && Math.abs(g1.dh) <= 3 && Math.abs(g1.sx - 60 * g1.s) <= 6 + 2 * g1.s && g1.sw > g0.sw * 1.1, 'Firefox: zoomed, the layer still covers the page and its words ' + JSON.stringify([g0, g1]));
    // a page without its canvas has no layer (freed together)
    check(await ev(`[...document.querySelectorAll('.dv-pages .dv-pg')].every(p => !p.querySelector('.textLayer') || !!p.querySelector('canvas'))`), 'Firefox: no layer without its page');
    await ev(`(document.querySelector('.dv-view [data-dc="dvz:width"]').click(), 1)`);
    // the page is drawn anew at the width scale; its text is there (the old layer stays until the new one is drawn)
    check(await wait(`(() => { const p = ${P0}, b = document.querySelector('.dv-pages'); return !!p.querySelector('canvas') && p.dataset.s === String(b._s) && /Elternhandbuch/.test(p.querySelector('.textLayer')?.textContent || ''); })()`, 80), 'Firefox: back at the width, the page has its text');
    // Ctrl+A in the preview: the pages' text, not the app; the copy has every page
    await ev(`(document.querySelector('.dv-pages').focus(), getSelection().removeAllRanges(), 1)`);
    await cmd('input.performActions', {context: ctx, actions: [{type: 'key', id: 'k1', actions: [{type: 'keyDown', value: ''}, {type: 'keyDown', value: 'a'}, {type: 'keyUp', value: 'a'}, {type: 'keyUp', value: ''}]}]});
    await cmd('input.releaseActions', {context: ctx});
    const all = JSON.parse(await ev(`(() => { const s = getSelection(), r = s.rangeCount ? s.getRangeAt(0) : null; return JSON.stringify({t: String(s), inCol: !!r && r.startContainer === document.querySelector('.dv-pgcol'), side: /Properties|Details/.test(String(s))}); })()`));
    check(all.inCol && /Elternhandbuch/.test(all.t) && !all.side, 'Firefox: Ctrl+A marks the text of the pages, not the app ' + JSON.stringify(all));
    check(await wait(`/Kontaktliste/.test(document.querySelector('.dv-pgcol')._pvall || '')`, 40), 'Firefox: the text of all pages is ready');
    const cp = await ev(`(() => { const dt = new DataTransfer(), e = new ClipboardEvent('copy', {clipboardData: dt, bubbles: true, cancelable: true}); let got = '';
      const look = x => { got = x.clipboardData.getData('text/plain'); }; window.addEventListener('copy', look); document.querySelector('.dv-pages').dispatchEvent(e); window.removeEventListener('copy', look); if (got) return got; const r = getSelection().rangeCount ? getSelection().getRangeAt(0) : null, col = document.querySelector('.dv-pgcol');
      return JSON.stringify({prevented: e.defaultPrevented, cd: !!e.clipboardData, r: r && [r.startContainer.nodeName, r.startOffset, r.endContainer.nodeName, r.endOffset, col.childNodes.length], k: (col._pvr || []).map(x => x?.nodeName || x)}); })()`);
    check(/Elternhandbuch/.test(cp) && /Oeffnungszeiten/.test(cp) && /Kontaktliste/.test(cp), 'Firefox: the copy has the text of every page ' + JSON.stringify(cp));
    // the full-screen viewer (pdfview.js): the layer over its pages too
    await ev(`(getSelection().removeAllRanges(), document.querySelector('.dv-view [data-dc="view"]').click(), 1)`);
    check(await wait(`!!document.querySelector('.lightbox.pview .pvpage[data-i="0"] canvas') && /Elternhandbuch/.test(document.querySelector('.lightbox.pview .pvpage[data-i="0"] .textLayer')?.textContent || '')`, 80), 'Firefox: the full-screen viewer has the text layer');
    const lg = JSON.parse(await ev(`(() => { const p = document.querySelector('.lightbox.pview .pvpage[data-i="0"]'), a = p.getBoundingClientRect(), b = p.querySelector('.textLayer').getBoundingClientRect(); return JSON.stringify({dw: Math.round(b.width - a.width), dh: Math.round(b.height - a.height), dl: Math.round(b.left - a.left), dt: Math.round(b.top - a.top)}); })()`));
    check(Math.abs(lg.dw) <= 3 && Math.abs(lg.dh) <= 3 && Math.abs(lg.dl) <= 2 && Math.abs(lg.dt) <= 2, 'Firefox: ... covering its page ' + JSON.stringify(lg));
    await shot('p2742c-textlayer-fullscreen.png');
  });

  console.log(`p2742_c_textlayer_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
