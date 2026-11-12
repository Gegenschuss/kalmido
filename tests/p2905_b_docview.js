// 2.905.0 UI test, part B (#5393: the document view's preview picture), own container (start.sh), Firefox (1440 px; a touch
// kalmido-suite: fresh
// screen for the neighbours drawn ahead). Invented data only. frida works without an organisation (freelancer-matrix: docs).
// The preview picture stands at once in the size and place of the full first page: the page's rectangle before the full file
// is loaded (it is held back in the page until measured) and after it is drawn is the same within 2 px - for a landscape PDF,
// a portrait PDF and a picture, opened from the list and reached by leafing with the arrow keys, with "Whole page" too; on a
// touch screen also for a neighbour drawn ahead (the swipe's body). Template: job/3917 (tests/p2905_b_docview.js), rebuilt on today's main.
const {execFileSync} = require('child_process');
const path = require('path');
const zlib = require('zlib');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2905_b_docview', check, shots: 'P2905B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2905B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(250); } return fn(); };

function pdfOf(objs) {  // objs: strings or [dict, Buffer] streams; object 1 the catalog
  const parts = [Buffer.from('%PDF-1.4\n', 'latin1')], offs = []; let len = parts[0].length;
  objs.forEach((o, i) => {
    offs.push(len);
    const b = Array.isArray(o) ? Buffer.concat([Buffer.from(`${i + 1} 0 obj\n<< ${o[0]} /Length ${o[1].length} >>\nstream\n`, 'latin1'), o[1], Buffer.from('\nendstream\nendobj\n', 'latin1')])
      : Buffer.from(`${i + 1} 0 obj\n${o}\nendobj\n`, 'latin1');
    parts.push(b); len += b.length;
  });
  parts.push(Buffer.from(`xref\n0 ${objs.length + 1}\n0000000000 65535 f \n` + offs.map(o => String(o).padStart(10, '0') + ' 00000 n \n').join('')
    + `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${len}\n%%EOF\n`, 'latin1'));
  return Buffer.concat(parts);
}
const esc = s => s.replace(/[\\()]/g, c => '\\' + c);
function textPdf(pages, w = 595, h = 842) {  // a digital PDF: vector text, one page per entry
  const objs = ['<< /Type /Catalog /Pages 2 0 R >>', `<< /Type /Pages /Kids [${pages.map((_, i) => `${4 + 2 * i} 0 R`).join(' ')}] /Count ${pages.length} >>`,
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'];
  pages.forEach((lines, i) => {
    objs.push(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${w} ${h}] /Contents ${5 + 2 * i} 0 R /Resources << /Font << /F1 3 0 R >> >> >>`,
      ['', Buffer.from(`BT /F1 14 Tf 60 ${h - 80} Td 18 TL ` + lines.map(l => `(${esc(l)}) '`).join(' ') + ' ET', 'latin1')]);
  });
  return pdfOf(objs);
}
function pixels(w, h) {  // grey paper with darker stripes (a "photographed" page), RGB rows
  const row = y => Buffer.from(Array.from({length: w * 3}, (_, k) => ((y % 40) < 4 || (Math.floor(k / 3) % 97) < 3 ? 60 : 232)));
  return Array.from({length: h}, (_, y) => row(y));
}
function scanPdf(w = 595, h = 842) {  // one page filled by a picture, no text
  const raw = zlib.deflateSync(Buffer.concat(pixels(w, h)));
  return pdfOf(['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${w} ${h}] /Contents 4 0 R /Resources << /XObject << /Im0 5 0 R >> >> >>`,
    ['', Buffer.from(`q ${w} 0 0 ${h} 0 0 cm /Im0 Do Q`, 'latin1')],
    [`/Type /XObject /Subtype /Image /Width ${w} /Height ${h} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode`, raw]]);
}
function png(w, h) {
  const crcT = Array.from({length: 256}, (_, n) => { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1; return c >>> 0; });
  const crc = b => { let c = 0xFFFFFFFF; for (const x of b) c = crcT[(c ^ x) & 255] ^ (c >>> 8); return (c ^ 0xFFFFFFFF) >>> 0; };
  const chunk = (t, d) => { const l = Buffer.alloc(4); l.writeUInt32BE(d.length); const td = Buffer.concat([Buffer.from(t, 'latin1'), d]); const c = Buffer.alloc(4); c.writeUInt32BE(crc(td)); return Buffer.concat([l, td, c]); };
  const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(w, 0); ihdr.writeUInt32BE(h, 4); ihdr[8] = 8; ihdr[9] = 2;
  const raw = Buffer.concat(pixels(w, h).map(r => Buffer.concat([Buffer.from([0]), r])));
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', ihdr), chunk('IDAT', zlib.deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]);
}
async function upload(name, data, mime) {
  const fd = new FormData();
  fd.append('files', new Blob([data], {type: mime}), name);
  fd.append('ws', 'private');
  const r = await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
  const id = ((await r.json()).ids || [])[0];
  await until(async () => ['done', 'failed'].includes((await call('GET', `/api/docs/${id}`)).state), 200);
  return call('GET', `/api/docs/${id}`);
}

// in the page: the full file of a document (pdf.js fetch / the picture's src) is held back while g.on, g.open() lets it through
const GATE = `(() => { if (window.__g) { window.__g.on = true; return 1; }
  const g = window.__g = {on: true, held: []}, isFile = u => /\\/api\\/docs\\/\\d+\\/file/.test(String(u));
  const d = Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, 'src');
  Object.defineProperty(HTMLImageElement.prototype, 'src', {configurable: true, get() { return d.get.call(this); },
    set(v) { if (g.on && isFile(v)) { const el = this; g.held.push(() => d.set.call(el, v)); return; } d.set.call(this, v); }});
  const f0 = window.fetch;
  window.fetch = function (u, o) { if (g.on && isFile(u && u.url || u)) return new Promise(res => g.held.push(() => res(f0.call(window, u, o)))); return f0.call(window, u, o); };
  g.open = () => { g.on = false; const h = g.held; g.held = []; h.forEach(f => f()); return h.length; };
  return 1; })()`;
// the first page's rectangle in the open view
const RECT = `(() => { const p = document.querySelector('.dv-view .dc-body .dv-pages .dv-pg'); if (!p) return null; const r = p.getBoundingClientRect();
  return JSON.stringify({l: Math.round(r.left), t: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height), thumb: p.classList.contains('dv-thumb')}); })()`;
const thumbReady = id => `(() => { const b = document.querySelector('.dv-view .dc-body'); if (!b || b.dataset.id !== '${id}') return false;
  const p = b.querySelector('.dv-pages .dv-pg.dv-thumb'), im = p && p.querySelector('img');
  return !!p && !!p.style.width && p.style.visibility !== 'hidden' && !!im && im.complete && im.naturalWidth > 0; })()`;
const fullReady = (id, img) => `(() => { const b = document.querySelector('.dv-view .dc-body'); if (!b || b.dataset.id !== '${id}') return false;
  ${img ? `const im = b.querySelector('.dv-pages .dv-pg.dv-img:not(.dv-thumb) img'); return !!im && im.complete && im.naturalWidth > 0;`
    : `return !!b.querySelector('.dv-pages .dv-pg[data-i="0"] canvas');`} })()`;
const same = (a, b) => !!a && !!b && ['l', 't', 'w', 'h'].every(k => Math.abs(a[k] - b[k]) <= 2);

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true}, CA);
  const u = await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []}, CA);
  check(u.status < 300, 'setup: frida (no organisation) ' + u.status);
  CK = await login('frida');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: 'collab,files,docs'});
  check(((await call('GET', '/api/state')).me?.workspaces || []).length === 0, 'setup: frida is in no organisation');
  // the oldest first: the list shows the newest first (L, IMG, P1 at its top)
  const SC = await upload('scan.pdf', scanPdf(), 'application/pdf');
  const NUM = await upload('second.pdf', textPdf([['Muster Versicherung', 'Police 2026']]), 'application/pdf');
  const P1 = await upload('portrait.pdf', textPdf([['Kita Beispiel', 'Elternbrief', 'Datum 01.09.2026'], ['Seite zwei']]), 'application/pdf');
  const IMG = await upload('photo.png', png(1200, 900), 'image/png');
  const L = await upload('landscape.pdf', textPdf([['Stadtwerke Musterstadt', 'Jahresabrechnung quer']], 842, 595), 'application/pdf');
  const all = [SC, NUM, P1, IMG, L];
  check(all.every(d => d.state === 'done' && d.thumb), 'setup: five documents read, each with a preview ' + all.map(d => d.state + '/' + d.thumb).join(' '));
  check(JSON.stringify(L.page) === '[842,595,842]' && JSON.stringify(P1.page) === '[595,842,595]' && JSON.stringify(IMG.page) === '[1200,900]', '#5393: the server knows the first page\'s size ' + JSON.stringify(all.map(d => d.page)));
  const kind = Object.fromEntries(all.map(d => [d.id, /^image\//.test(d.mime) ? 'image' : 'pdf']));

  const login_ = async ev => check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'frida', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: frida logs in');
  // one document: the preview's rectangle (its full file held back), then the full page's -> the same
  const measure = async (ev, wait, id, what, cached = false) => {
    check(await wait(thumbReady(id), 80), `${what}: the preview picture stands sized (${kind[id]} ${id})`);
    // 2.965.0 (#5642): a PDF asks for its file only after pdf.js is loaded (docview.js dcv_pvDraw: loadModule, pv_load); on the
    // slower CI the preview stood before that and was measured with nothing held yet - wait until the file is asked for
    // (held back here), so the preview is measured while the full file waits, as meant
    if (!cached) await wait('window.__g.held.length > 0', 80);
    const held = await ev('window.__g.held.length');
    const a = JSON.parse(await ev(RECT) || 'null');
    // "Whole page" reopens a document whose file this page already loaded (opened by its address): nothing is fetched again
    // then, the preview still stands when measured - the size check below is the point
    check((held > 0 || cached) && a?.thumb, `${what}: measured while the full file waits (${held} held) ${JSON.stringify(a)}`);
    await ev('window.__g.open()');
    check(await wait(fullReady(id, kind[id] === 'image'), 80), `${what}: the full ${kind[id]} is drawn`);
    const b = JSON.parse(await ev(RECT) || 'null');
    check(same(a, b) && !b.thumb, `#5393 ${what}: the first page keeps size and place (±2 px) ${kind[id]} ${JSON.stringify([a, b])}`);
    await ev('(window.__g.on = true, 1)');
  };

  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    const wait = async (js, k = 60) => { for (let i = 0; i < k; i++) { if (await ev(js).catch(() => false)) return true; await sleep(250); } return false; };
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    await login_(ev);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await nav(B + '#docs');
    check(await wait(`document.querySelectorAll('.dc-card').length === 5`), 'Firefox: five cards');
    await ev(GATE);
    const order = JSON.parse(await ev('JSON.stringify(DC.docs.map(x => x.id))'));
    // ---- #5393 from the list, then leafing on twice (arrow right = the next in the list)
    await ev(`(document.querySelector('.dc-view [data-dco="${order[0]}"]').click(), 1)`);
    await measure(ev, wait, order[0], 'opened from the list');
    await shot('p2905-b-docview-1440.png');
    const seen = [order[0]];
    for (let k = 1; k <= 2; k++) {
      await ev(`(document.activeElement && document.activeElement.blur(), document.body.dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowRight', bubbles: true, cancelable: true})), 1)`);
      check(await wait(`document.querySelector('.dv-view .dc-body')?.dataset.id === '${order[k]}'`), `leafed to the next one (${order[k]})`);
      await measure(ev, wait, order[k], `leafed (${k})`);
      seen.push(order[k]);
    }
    check(seen.some(id => kind[id] === 'image') && seen.some(id => kind[id] === 'pdf'), 'pictures and PDFs were both measured ' + JSON.stringify(seen.map(id => kind[id])));
    // "Whole page" kept on the device: the preview fits the same way
    await ev(`(document.querySelector('.dv-view [data-dc="dvz:page"]').click(), 1)`);
    await ev('window.__g.open()');
    await nav(B + 'static/icon.svg');
    await nav(B + `#docs/${L.id}`);
    await ev(GATE);
    // the view opened by the address loads at once: open it again from the list to hold its file
    await ev(`(document.body.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true, cancelable: true})), 1)`);
    check(await wait(`!document.querySelector('.dv-view') && document.querySelectorAll('.dc-card').length === 5`), 'back in the list');
    await ev(`(document.querySelector('.dc-view [data-dco="${L.id}"]').click(), 1)`);
    await measure(ev, wait, L.id, 'Whole page', true);
    await ev(`(document.querySelector('.dv-view [data-dc="dvz:width"]').click(), 1)`);
    await ev('window.__g.open()');

  });

  // ---- #5393 on a touch screen: the neighbours are drawn ahead (dcv_nbDraw); the swipe's body takes over -> the same check
  await firefox(async ({cmd, ev, nav, ctx}) => {
    const wait = async (js, k = 60) => { for (let i = 0; i < k; i++) { if (await ev(js).catch(() => false)) return true; await sleep(250); } return false; };
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1024, height: 800}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    await login_(ev);
    await nav(B + '#docs');
    check(await wait(`document.querySelectorAll('.dc-card').length === 5`), 'touch: five cards');
    const touch = await ev('typeof dc_nbOn === "function" && dc_nbOn()');
    check(touch, 'touch: the neighbours are drawn ahead here');
    await ev(GATE);
    const order = JSON.parse(await ev('JSON.stringify(DC.docs.map(x => x.id))'));
    await ev(`(document.querySelector('.dc-view [data-dco="${order[0]}"]').click(), 1)`);
    check(await wait(thumbReady(order[0]), 80), 'touch: opened, its preview picture sized');
    // its full file and the neighbour's stay held: the neighbour's body waits with its preview picture only
    check(await wait(`!!DCW.nb && DCW.nb.has(${order[1]}) && !!DCW.nb.get(${order[1]}).el && !!DCW.nb.get(${order[1]}).el.querySelector('.dv-pg.dv-thumb')`, 80), 'touch: the next one is drawn ahead (its preview picture)');
    await ev(`(document.activeElement && document.activeElement.blur(), document.body.dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowRight', bubbles: true, cancelable: true})), 1)`);
    check(await wait(`document.querySelector('.dv-view .dc-body')?.dataset.id === '${order[1]}'`), 'touch: leafed to the one drawn ahead');
    await measure(ev, wait, order[1], 'touch: the neighbour drawn ahead');
  }, true);

  console.log(`p2905_b_docview: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
