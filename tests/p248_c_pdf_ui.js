// 2.48.0 part C (#1367): the PDF preview (static/js/pdfview.js, the bundled pdf.js), own container (start.sh), Firefox:
// - a PDF attachment of a task opens in the preview (lightbox, role dialog), not in a new tab; the link keeps its address
//   and target, so Ctrl/Cmd-click still opens a new tab
// - the pages are drawn (canvas), "Page 1 of 3", the next-page button turns to page 2, zoom in changes the percentage
// - Esc closes it and gives the focus back to the link
// - a damaged PDF shows a clear message with a download button instead of an empty area
// - the library is served from the same origin as a JavaScript module (no CDN)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p248_c_pdf_ui', check, shots: 'P248C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.BASE) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };

// a small valid PDF with n pages, each saying "Page k" (Helvetica, no embedded font)
function makePdf(n) {
  const objs = ['<< /Type /Catalog /Pages 2 0 R >>', null, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'];
  const kids = [];
  for (let k = 1; k <= n; k++) {
    const s = `BT /F1 36 Tf 72 700 Td (Page ${k}) Tj ET`;
    objs.push(`<< /Length ${s.length} >>\nstream\n${s}\nendstream`);
    objs.push(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> /Contents ${objs.length} 0 R >>`);
    kids.push(`${objs.length} 0 R`);
  }
  objs[1] = `<< /Type /Pages /Kids [${kids.join(' ')}] /Count ${n} >>`;
  let out = '%PDF-1.4\n'; const off = [];
  objs.forEach((o, i) => { off.push(out.length); out += `${i + 1} 0 obj\n${o}\nendobj\n`; });
  const x = out.length;
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n` + off.map(o => String(o).padStart(10, '0') + ' 00000 n \n').join('');
  out += `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${x}\n%%EOF\n`;
  return Buffer.from(out, 'latin1');
}
async function upload(tid, name, buf) {
  const fd = new FormData(); fd.append('file', new Blob([buf], {type: 'application/pdf'}), name);
  const r = await fetch(B + `api/tasks/${tid}/attachments`, {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
  return r.json();
}

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const L = (await call('POST', '/api/lists', {name: 'Papers'})).id;
  const T = (await call('POST', '/api/tasks', {title: 'Read the contract', list_id: L})).id;
  const a1 = await upload(T, 'contract.pdf', makePdf(3));
  const a2 = await upload(T, 'broken.pdf', Buffer.from('this is no pdf at all'));
  check(a1.attachments?.length === 1 && a2.attachments?.length === 2, 'two PDF attachments uploaded');
  const lib = await fetch(B + 'static/vendor/pdfjs/pdf.min.mjs');
  check(lib.ok && /javascript/.test(lib.headers.get('content-type') || ''), '#1367: pdf.js is served from the same origin as a JavaScript module ' + lib.headers.get('content-type'));
  const wk = await fetch(B + 'static/vendor/pdfjs/pdf.worker.min.mjs');
  check(wk.ok, '#1367: the pdf.js worker is served');

  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 800}});
    await nav(B + '#t/' + T);
    for (let i = 0; i < 40 && !(await ev(`!!document.querySelector('.att.file a[data-pview]')`).catch(() => false)); i++) await sleep(300);
    const link = await ev(`(() => { const a = [...document.querySelectorAll('.att.file a[data-pview]')].find(x => x.title === 'contract.pdf'); return a ? {t: a.target, h: a.getAttribute('href')} : null; })()`);
    check(link && link.t === '_blank' && /\/api\/attachments\/\d+/.test(link.h), '#1367: the PDF link keeps its address and new-tab target (Ctrl/Cmd-click) ' + JSON.stringify(link));
    await ev(`(() => { const a = [...document.querySelectorAll('.att.file a[data-pview]')].find(x => x.title === 'contract.pdf'); a.focus(); a.click(); return 1; })()`);
    let st = null;
    for (let i = 0; i < 60; i++) { st = await ev(`(() => { const m = document.querySelector('.lightbox.pview'); return m ? {role: m.getAttribute('role'), pages: m.querySelectorAll('.pvpage').length, cv: m.querySelectorAll('.pvpage canvas').length, no: m.querySelector('.pvno')?.textContent, fail: m.querySelector('.pvfail')?.textContent || ''} : null; })()`); if (st && (st.cv || st.fail)) break; await sleep(250); }
    check(st && st.role === 'dialog' && st.pages === 3 && st.cv >= 1 && st.no === 'Page 1 of 3', '#1367: the preview opens with three pages, the first drawn, "Page 1 of 3" ' + JSON.stringify(st));
    const ink = await ev(`(() => { const c = document.querySelector('.pvpage canvas'); if (!c) return -1; const d = c.getContext('2d').getImageData(0, 0, c.width, Math.floor(c.height / 4)).data; let n = 0; for (let i = 0; i < d.length; i += 4) if (d[i] < 128) n++; return n; })()`);
    check(ink > 50, '#1367: the page shows its text (dark pixels on the canvas) ' + ink);
    await shot('p248c-pdf-open.png');
    await ev(`(document.querySelector('.pview [data-pv="next"]').click(), 1)`); await sleep(900);
    const st2 = await ev(`(() => { const m = document.querySelector('.lightbox.pview'); return {no: m.querySelector('.pvno').textContent, top: Math.round(m.querySelector('.pvbody').scrollTop), cv2: !!m.querySelectorAll('.pvpage')[1].querySelector('canvas')}; })()`);
    check(st2.no === 'Page 2 of 3' && st2.top > 100 && st2.cv2, '#1367: next page scrolls to page 2 and draws it ' + JSON.stringify(st2));
    const z0 = await ev(`document.querySelector('.pview .pvpct').textContent`);
    await ev(`(document.querySelector('.pview [data-pv="in"]').click(), 1)`); await sleep(500);
    const z1 = await ev(`document.querySelector('.pview .pvpct').textContent`);
    check(parseInt(z1) > parseInt(z0), `#1367: zoom in raises the percentage (${z0} -> ${z1})`);
    check(await ev(`!!document.querySelector('.pview a[download]') && !!document.querySelector('.pview a[target="_blank"]')`), '#1367: download and open-in-new-tab in the head');
    await cmd('input.performActions', {context: ctx, actions: [{type: 'key', id: 'k', actions: [{type: 'keyDown', value: ''}, {type: 'keyUp', value: ''}]}]});
    await sleep(300);
    const after = await ev(`({open: !!document.querySelector('.lightbox'), focus: document.activeElement?.title || document.activeElement?.tagName})`);
    check(!after.open && after.focus === 'contract.pdf', '#1367: Esc closes the preview and gives the focus back to the link ' + JSON.stringify(after));
    // a damaged file: a message and a download button, no empty area
    await ev(`(() => { const a = [...document.querySelectorAll('.att.file a[data-pview]')].find(x => x.title === 'broken.pdf'); a.click(); return 1; })()`);
    let f = null;
    for (let i = 0; i < 40; i++) { f = await ev(`(() => { const m = document.querySelector('.lightbox.pview .pvfail'); return m ? {t: m.textContent.trim(), dl: !!m.querySelector('a[download]')} : null; })()`); if (f) break; await sleep(250); }
    check(f && f.dl && f.t.length > 10, '#1367: a damaged PDF shows a message with a download button ' + JSON.stringify(f));
    await shot('p248c-pdf-fail.png');
    await ev(`(document.querySelector('.pview [data-pv="x"]').click(), 1)`); await sleep(200);
    check(!(await ev(`!!document.querySelector('.lightbox')`)), '#1367: the close button closes it');
    // phone width: the head wraps, the page fits the width
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 800}});
    await sleep(300);
    await ev(`(pdfView({url: document.querySelector('.att.file a[title="contract.pdf"]')?.getAttribute('href') || '', name: 'contract.pdf', size: 1000}), 1)`);
    let pw = null;
    for (let i = 0; i < 40; i++) { pw = await ev(`(() => { const p = document.querySelector('.pview .pvpage canvas')?.parentElement, b = document.querySelector('.pview .pvbody'); return p && b ? {pw: p.getBoundingClientRect().width, bw: b.clientWidth} : null; })()`); if (pw) break; await sleep(250); }
    check(pw && pw.pw <= pw.bw && pw.pw > pw.bw * 0.8, '#1367: on a phone the page fits the width ' + JSON.stringify(pw));
    await shot('p248c-pdf-phone.png');
  }, false);

  console.log(`p248_c_pdf_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
