// 2.641.0 part B UI test (#4769), own container (start.sh): the approval of an image with numbered points, on a phone.
// kalmido-suite: fresh
// - a task's section "Approval" offers "Add image or PDF" next to "Add video link"
// - the review view shows the image (its bytes route) with the points of its comments, numbered 1, 2 at their place
// - a tap on the image sets the point of the next comment (a pending point "3", the composer says "at point 3"), the text
//   typed before stays, sending stores {x, y} (the server has it) and draws point 3
// - a tap on a comment's number marks its point, a tap on a point marks its comment; "without point" takes the point back
// - an image review has no client link; v2 shows its own (no) points, v1 picked in the version select shows its three again
// - a PDF comment's number names its page ("p. 2")
// - the styles keep the image inside a 320 px screen (max-width 100 %, the dialog full width on a phone)
// P2641BUI_NOSTART=1 = the server already runs.
const path = require('path');
const zlib = require('zlib');
const {execFileSync} = require('child_process');
const {boot, errs, sleep, B, login, allCss} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2641BUI_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const upload = async (url, fields, name, bytes, mime) => {
  const fd = new FormData();
  for (const [k, v] of Object.entries(fields)) fd.append(k, String(v));
  fd.append('file', new Blob([bytes], {type: mime}), name);
  const r = await fetch(B + url.replace(/^\//, ''), {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
  return {status: r.status, ...(await r.json().catch(() => ({})))};
};
const until = fn => require('./boot').until(fn, {timeout: 15000, step: 100});
function png(w, h) {  // a real small PNG
  const crcT = []; for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; crcT[n] = c >>> 0; }
  const crc = b => { let c = 0xffffffff; for (const x of b) c = crcT[(c ^ x) & 255] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };
  const chunk = (t, d) => { const l = Buffer.alloc(4); l.writeUInt32BE(d.length); const td = Buffer.concat([Buffer.from(t), d]); const c = Buffer.alloc(4); c.writeUInt32BE(crc(td)); return Buffer.concat([l, td, c]); };
  const ih = Buffer.alloc(13); ih.writeUInt32BE(w, 0); ih.writeUInt32BE(h, 4); ih[8] = 8; ih[9] = 2;
  const raw = Buffer.concat(Array.from({length: h}, () => Buffer.concat([Buffer.from([0]), Buffer.alloc(w * 3, 180)])));
  return Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), chunk('IHDR', ih), chunk('IDAT', zlib.deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]);
}
const PDF = Buffer.from('%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>\nendobj\n'
  + '3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>\nendobj\n4 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n');

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'collab,comments,clients,videos'});
  const L = await call('POST', '/api/lists', {name: 'Logo Bäckerei', ptype: 'agency'});
  const T = await call('POST', '/api/tasks', {title: 'Logo Entwurf', list_id: L.id});
  const R = await upload('/api/videos', {task_id: T.id, title: 'Logo'}, 'logo.png', png(4, 2), 'image/png');
  check(R.status === 200 && R.kind === 'image', 'an image review by upload ' + R.status + ' ' + (R.error || ''));
  for (const [x, y, b] of [[0.25, 0.5, 'Schrift größer'], [0.75, 0.25, 'Farbe wärmer']]) await call('POST', `/api/videos/${R.id}/comments`, {body: b, pos: {x, y}});
  const P = await upload('/api/videos', {task_id: T.id, title: 'Flyer'}, 'flyer.pdf', PDF, 'application/pdf');
  check(P.kind === 'pdf', 'a PDF review by upload ' + P.status + ' ' + (P.error || ''));
  await call('POST', `/api/videos/${P.id}/comments`, {body: 'Seite 2 Rand', pos: {page: 2, x: 0.5, y: 0.5}});

  const w = await boot({user: 'alice', mobile: true, hash: 't/' + T.id}), d = w.document;
  const key = JSON.stringify('task_id:' + T.id);
  await until(() => w.eval('S.sel') === T.id && w.eval("typeof VDR === 'object'") && w.eval(`Array.isArray(VDR.by[${key}])`));
  w.eval('renderDetail()');
  check(d.querySelector('#d-vdr [data-vdr="newfile"]') && /Add image or PDF/.test(d.querySelector('#d-vdr').textContent), 'the section offers "Add image or PDF"');
  check(d.querySelectorAll('#d-vdr [data-vdr="open"]').length === 2, 'the two reviews are listed');

  // the review view: the image with its points
  w.eval(`vdr_open(${R.id})`);
  await until(() => d.querySelector('.vdrdlg .vdrstage img') && d.querySelectorAll('.vdrdlg .vdrpin').length === 2);
  const img = d.querySelector('.vdrdlg .vdrstage img');
  check(img.getAttribute('src') === `/api/videos/${R.id}/versions/${R.versions[0].id}/file`, 'the image comes from its bytes route ' + img.getAttribute('src'));
  const pins = [...d.querySelectorAll('.vdrdlg .vdrpin')];
  check(pins.map(p => p.textContent).join(',') === '1,2' && parseFloat(pins[0].style.left) === 25 && parseFloat(pins[0].style.top) === 50, 'points 1 and 2 at their place ' + pins.map(p => p.style.cssText).join(' | '));
  check(!d.querySelector('.vdrdlg .vdrsig h4'), 'an image review has no client link');
  check(!d.querySelector('.vdrdlg .vdrtl:not([hidden]) .vdrmk'), 'no time line');

  // the text typed first stays when the point is set
  const ta = () => d.querySelector('#vdr-in');
  ta().value = 'Logo kleiner';
  const stage = d.querySelector('.vdrdlg .vdrstage');
  stage.getBoundingClientRect = () => ({left: 0, top: 0, width: 200, height: 100, right: 200, bottom: 100, x: 0, y: 0});
  img.dispatchEvent(new w.MouseEvent('click', {bubbles: true, clientX: 50, clientY: 80}));
  check(d.querySelector('.vdrdlg .vdrpin.new')?.textContent === '3', 'a tap on the image: the pending point 3');
  check(/at point 3/.test(d.querySelector('[data-vdr="pt"]')?.textContent || '') && d.querySelector('[data-vdr="pt"]').getAttribute('aria-pressed') === 'true', 'the composer says "at point 3"');
  check(ta().value === 'Logo kleiner', 'the text typed before stays');
  // "without point" takes it back, a second tap sets it again
  d.querySelector('[data-vdr="pt"]').click();
  check(!d.querySelector('.vdrdlg .vdrpin.new') && /without point/.test(d.querySelector('[data-vdr="pt"]').textContent), 'the point taken back');
  img.dispatchEvent(new w.MouseEvent('click', {bubbles: true, clientX: 50, clientY: 80}));
  d.querySelector('[data-vdr="send"]').click();
  const got = await until(async () => { const j = await call('GET', `/api/videos/${R.id}`); return (j.comments || []).find(c => c.body === 'Logo kleiner'); });
  check(got && got.pos && got.pos.x === 0.25 && got.pos.y === 0.8 && got.mark === 3, 'sent: the server has {x: 0.25, y: 0.8} as point 3 ' + JSON.stringify(got && got.pos));
  await until(() => d.querySelectorAll('.vdrdlg .vdrpin:not(.new)').length === 3);
  check(d.querySelectorAll('.vdrdlg .vdrpin:not(.new)').length === 3 && !d.querySelector('.vdrdlg .vdrpin.new'), 'point 3 drawn, nothing pending');

  // the number of a comment marks its point, a point marks its comment
  const c1 = got && (await call('GET', `/api/videos/${R.id}`)).comments.find(c => c.mark === 1);
  d.querySelector(`.vdrdlg .vdrc[data-cid="${c1.id}"] [data-vdr="pin"]`).click();
  await until(() => d.querySelector(`.vdrdlg .vdrpin[data-id="${c1.id}"]`)?.classList.contains('hl'));
  check(d.querySelector(`.vdrdlg .vdrpin[data-id="${c1.id}"]`).classList.contains('hl'), 'a tap on the number 1 marks point 1');
  d.querySelector(`.vdrdlg .vdrpin[data-id="${got.id}"]`).click();
  check(d.querySelector(`.vdrdlg .vdrc[data-cid="${got.id}"]`).classList.contains('hl'), 'a tap on point 3 marks its comment');

  // a new version: its own points; v1 in the select shows the three again
  const v2 = await upload(`/api/videos/${R.id}/versions`, {}, 'logo-v2.png', png(5, 3), 'image/png');
  check(v2.version === 2, 'v2 by upload ' + v2.status);
  d.querySelector('.vdrdlg [data-m="close"]').click();
  w.eval(`vdr_open(${R.id})`);
  await until(() => d.querySelector('.vdrdlg #vdr-ver') && d.querySelector('.vdrdlg .vdrstage img'));
  check(d.querySelectorAll('.vdrdlg .vdrpin').length === 0, 'v2 opens without points');
  const sel = d.querySelector('.vdrdlg #vdr-ver');
  sel.value = String(R.versions[0].id); sel.dispatchEvent(new w.Event('change', {bubbles: true}));
  await until(() => d.querySelectorAll('.vdrdlg .vdrpin').length === 3);
  check(d.querySelectorAll('.vdrdlg .vdrpin').length === 3 && /An older version/.test(d.querySelector('.vdrdlg .vdrstate').textContent), 'v1: its three points and the hint of an older version');
  d.querySelector('.vdrdlg [data-m="close"]').click();

  // a PDF comment names its page
  w.eval(`vdr_open(${P.id})`);
  await until(() => d.querySelector('.vdrdlg .vdrk-pdf') && d.querySelector('.vdrdlg .vdrpb'));
  check(/p\. 2 · 1/.test(d.querySelector('.vdrdlg .vdrpb').textContent), 'the PDF comment: "p. 2 · 1" ' + d.querySelector('.vdrdlg .vdrpb').textContent);
  d.querySelector('.vdrdlg [data-m="close"]').click();

  // 320 px: the image never wider than its box, the dialog full width on a phone
  const css = (await allCss()).replace(/\s+/g, '');
  check(/\.vdrstage\{[^}]*max-width:100%/.test(css) && /\.vdrstageimg\{[^}]*max-width:100%/.test(css), 'the image stays inside the screen (max-width 100 %)');
  check(/@media\(max-width:767px\)\{\.vdrdlg\.card\{width:100%\}/.test(css), 'the dialog takes the whole width on a phone');

  check(errs.length === 0, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  w.close();
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
