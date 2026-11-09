// 2.764.0 part A UI test (#5040), own container (start.sh), Firefox on a phone (320 px, touch): the client link of an image /
// kalmido-suite: fresh
// PDF sign-off without an account (videos/vdmedia.py vdm_pub_stage, static/js/pubvideo.js). The image shows from the link's
// media route; a tap on it sets the point of the next comment (a pending point "1", "at point 1", the form's x / y), "without
// point" takes it back, the comment sent stands at its point (the app has pos and mark 1) and the page draws its point there.
// A PDF: the page drawn by the bundled pdf.js under the page's strict CSP (fetch / worker from this server only), "Page 1 of 2",
// the next page, a tap there = page 2 + point; after sending, a tap on the comment's "p. 2 · 1" turns to page 2 and shows the
// point. Nothing sticks out sideways at 320 px. Invented names only.
// freelancer-matrix: videos (the API suite p2642_a_reviewlink_test.py runs the person without an organisation)
// P2764AUI_NOSTART=1 = the server already runs.
const {execFileSync} = require('child_process');
const path = require('path');
const zlib = require('zlib');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2764_a_guestmedia_ui', check, shots: 'P2764A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2764AUI_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); if (!r.ok) console.log('call failed', method, url, r.status); return r.json().catch(() => ({})); };
const upload = async (taskId, name, bytes, mime, title) => {
  const fd = new FormData();
  fd.append('task_id', String(taskId)); fd.append('title', title); fd.append('file', new Blob([bytes], {type: mime}), name);
  const r = await fetch(B + 'api/videos', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
  if (!r.ok) console.log('upload failed', r.status, (await r.text()).slice(0, 200));
  return r.json().catch(() => ({}));
};
// a real PNG of 40 x 20 (no library)
const CRC = (() => { const t = []; for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t.push(c >>> 0); } return t; })();
const crc32 = b => { let c = 0xffffffff; for (const x of b) c = CRC[(c ^ x) & 0xff] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };
const chunk = (t, d) => { const len = Buffer.alloc(4), crc = Buffer.alloc(4), td = Buffer.concat([Buffer.from(t), d]); len.writeUInt32BE(d.length); crc.writeUInt32BE(crc32(td)); return Buffer.concat([len, td, crc]); };
const png = (w, h) => {
  const ih = Buffer.alloc(13); ih.writeUInt32BE(w, 0); ih.writeUInt32BE(h, 4); ih[8] = 8; ih[9] = 2;
  const raw = Buffer.concat(Array.from({length: h}, () => Buffer.concat([Buffer.from([0]), Buffer.from(Array.from({length: w}, () => [200, 120, 30]).flat())])));
  return Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), chunk('IHDR', ih), chunk('IDAT', zlib.deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]);
};
// a plain PDF of two pages (A4-like 200 x 283)
const pdf2 = () => {
  const objs = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 283] >>', '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 283] >>'];
  let out = '%PDF-1.4\n'; const offs = [];
  objs.forEach((o, i) => { offs.push(out.length); out += `${i + 1} 0 obj\n${o}\nendobj\n`; });
  const x = out.length;
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n` + offs.map(o => `${String(o).padStart(10, '0')} 00000 n \n`).join('');
  return Buffer.from(out + `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${x}\n%%EOF\n`, 'latin1');
};
const FIT = sel => `(() => { const vw = document.documentElement.clientWidth, e = document.querySelector(${JSON.stringify(sel)}), r = e && e.getBoundingClientRect();
  return JSON.stringify({vw, sx: document.documentElement.scrollWidth, l: r ? Math.round(r.left) : null, r: r ? Math.round(r.right) : null}); })()`;
const TAP = (fx, fy) => `(() => { const s = document.querySelector('.vdr-stage'), r = s.getBoundingClientRect();
  s.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, clientX: r.left + r.width * ${fx}, clientY: r.top + r.height * ${fy}})); return 1; })()`;
const SEND = text => `(() => { document.getElementById('vd-name').value = 'Kundin Example'; document.getElementById('vd-text').value = ${JSON.stringify(text)}; document.getElementById('vdr-f').submit(); return 1; })()`;

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'collab,comments,clients,videos'});
  const L = await call('POST', '/api/lists', {name: 'Plakat', kind: 'project'});
  const T = await call('POST', '/api/tasks', {title: 'Entwurf', list_id: L.id});
  const RI = await upload(T.id, 'plakat.png', png(40, 20), 'image/png', 'Plakat Entwurf');
  const RP = await upload(T.id, 'flyer.pdf', pdf2(), 'application/pdf', 'Flyer Entwurf');
  check(RI.kind === 'image' && RP.kind === 'pdf', 'setup: an image and a PDF sign-off ' + RI.kind + ' ' + RP.kind);
  const SI = await call('POST', `/api/videos/${RI.id}/signoff`, {}), SP = await call('POST', `/api/videos/${RP.id}/signoff`, {});
  const TI = (SI.url || '').split('/s/q/')[1] || '', TP = (SP.url || '').split('/s/q/')[1] || '';
  check(TI && TP, 'setup: a client link for each');

  await firefox(async o => {
    const {cmd, ev, ctx, until, idle, shot} = o;
    await o.nav(B + 'static/icon.svg');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 320, height: 640}});

    // ================= the image
    await o.nav(B + 's/q/' + TI); await idle();
    check(await until(`(() => { const i = document.querySelector('.vdr-stage img'); return !!i && i.complete && i.naturalWidth === 40; })()`), 'the image loads from the link (CSP img-src self)');
    check(await ev(`document.getElementById('vd-pt').hidden && !document.getElementById('vd-at')`), 'no point yet, no timecode field');
    await ev(TAP(0.75, 0.25));
    check(await until(`document.querySelector('.vdr-pin.new')?.textContent === '1' && Math.abs(parseFloat(document.querySelector('.vdr-pin.new').style.left) - 75) < 0.5`), 'a tap sets the pending point 1 at its place '
      + await ev(`String(document.querySelector('.vdr-pin.new')?.style.cssText)`));
    const pt = JSON.parse(await ev(`JSON.stringify({x: document.getElementById('vd-px').value, y: document.getElementById('vd-py').value, st: document.getElementById('vd-pt').hidden, t: document.querySelector('#vd-pt span').textContent, f: document.activeElement?.id})`));
    check(Math.abs(+pt.x - 0.75) < 0.01 && Math.abs(+pt.y - 0.25) < 0.01 && !pt.st && pt.t === 'at point 1' && pt.f === 'vd-text', 'the form has the point, says "at point 1", the text field has the focus ' + JSON.stringify(pt));
    await ev(`document.querySelector('[data-pt-clear]').click(), 1`);
    check(await ev(`!document.querySelector('.vdr-pin.new') && document.getElementById('vd-px').value === '' && document.getElementById('vd-pt').hidden`), '"without point" takes it back');
    await ev(TAP(0.75, 0.25));
    await ev(SEND('Schrift größer'));
    check(await until(`document.readyState === 'complete' && /Thank you, your comment has arrived/.test(document.body.textContent)`), 'the comment arrived');
    check(await until(`(() => { const p = document.querySelector('.vdr-pin[data-id]'); return !!p && !p.hidden && p.textContent === '1' && Math.abs(parseFloat(p.style.left) - 75) < 0.5 && Math.abs(parseFloat(p.style.top) - 25) < 0.5; })()`),
      'the page draws point 1 at its place');
    const ri = await call('GET', `/api/videos/${RI.id}`);
    const c1 = (ri.comments || []).find(x => x.body === 'Schrift größer');
    check(c1 && c1.customer && c1.mark === 1 && Math.abs(c1.pos.x - 0.75) < 0.01 && Math.abs(c1.pos.y - 0.25) < 0.01, 'in the app: the guest comment at point 1 ' + JSON.stringify(c1));
    const fi = JSON.parse(await ev(FIT('.vdr-stage')));
    check(fi.sx <= fi.vw && fi.r <= fi.vw && fi.l >= 0, 'image page: nothing sticks out sideways at 320 px ' + JSON.stringify(fi));
    await shot('p2764a-image-320.png');

    // ================= the PDF
    await o.nav(B + 's/q/' + TP); await idle();
    check(await until(`!!document.querySelector('.vdr-cv canvas') && document.querySelector('.vdr-pgno')?.textContent === 'Page 1 of 2'`, {timeout: 20000}),
      'pdf.js draws page 1 under the page\'s CSP ' + await ev(`String(document.querySelector('.vdr-pgmsg')?.textContent) + ' ' + String(document.querySelector('.vdr-pgmsg')?.hidden)`));
    check(await ev(`!document.querySelector('.vdr-pgbar').hidden && document.querySelector('[data-pg="-1"]').disabled && document.querySelector('.vdr-pgmsg').hidden`), 'the page bar: page 1 of 2, back disabled, no message');
    await ev(`document.querySelector('[data-pg="1"]').click(), 1`);
    check(await until(`document.querySelector('.vdr-pgno')?.textContent === 'Page 2 of 2' && document.querySelector('.vdr-cv canvas')?.getAttribute('aria-label') === 'Page 2'`), 'the next page: page 2');
    await ev(TAP(0.5, 0.5));
    check(await until(`document.getElementById('vd-pg').value === '2' && Math.abs(+document.getElementById('vd-px').value - 0.5) < 0.01`), 'a tap on page 2: page 2 and the point in the form');
    await ev(SEND('Telefonnummer fehlt'));
    check(await until(`document.readyState === 'complete' && /Thank you, your comment has arrived/.test(document.body.textContent) && !!document.querySelector('.vdr-cv canvas')`, {timeout: 20000}), 'the PDF comment arrived');
    const rp = await call('GET', `/api/videos/${RP.id}`);
    const c2 = (rp.comments || []).find(x => x.body === 'Telefonnummer fehlt');
    check(c2 && c2.pos && c2.pos.page === 2 && c2.mark === 1, 'in the app: page 2, point 1 ' + JSON.stringify(c2));
    check(await ev(`document.querySelector('a.vdr-pt')?.textContent === 'p. 2 · 1' && document.querySelector('.vdr-pin[data-id]')?.hidden === true`), 'the comment says p. 2 · 1; on page 1 its point is hidden');
    await ev(`document.querySelector('a.vdr-pt').click(), 1`);
    check(await until(`document.querySelector('.vdr-pgno')?.textContent === 'Page 2 of 2' && (() => { const p = document.querySelector('.vdr-pin[data-id]'); return !p.hidden && Math.abs(parseFloat(p.style.left) - 50) < 0.5; })()`),
      'a tap on "p. 2 · 1" turns to page 2 and shows the point');
    const fp = JSON.parse(await ev(FIT('.vdr-stage')));
    check(fp.sx <= fp.vw && fp.r <= fp.vw && fp.l >= 0, 'PDF page: nothing sticks out sideways at 320 px ' + JSON.stringify(fp));
    await shot('p2764a-pdf-320.png');
  }, true);

  console.log(`p2764_a_guestmedia_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
