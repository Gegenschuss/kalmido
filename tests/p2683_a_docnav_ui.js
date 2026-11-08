// kalmido-suite:
// 2.683.0 UI test (#5150: every document view on the phone can leaf), own container (start.sh), jsdom (phone). Invented data only.
// P2683A_NOSTART=1 = the container runs.
// - the file store: a document card of a folder opens its sheet with "x of N", the arrows and the swipe through the folder's
//   documents in the order shown; the route stays on the folder; the list view's "Open as document" leafs the same way
// - the documents opened by address (#docs/<id>) when the document stands further down than the loaded page: the next
//   pages load until it is found, then "4 of 4" and the arrows are there
// - a locked folder (decryption simulated in the page): a picture opens with all pictures of the folder, each one is
//   decrypted only when it is turned to; a PDF leafs through the folder's PDFs and pictures (pdfview.js o.step)
// P4: alice works without an organisation (private documents and folders) (freelancer-matrix: docs)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2683A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(200); } return fn(); };
const click = (w, el, o = {}) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));

function textPdf(lines) {  // a one-page PDF with a text layer, written by hand
  const esc = s => s.replace(/[\\()]/g, c => '\\' + c);
  const stream = 'BT /F1 12 Tf 60 740 Td 16 TL ' + lines.map(l => `(${esc(l)}) '`).join(' ') + ' ET';
  const objs = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'];
  let out = '%PDF-1.4\n'; const offs = [];
  objs.forEach((o, i) => { offs.push(out.length); out += `${i + 1} 0 obj\n${o}\nendobj\n`; });
  const x = out.length;
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n` + offs.map(o => String(o).padStart(10, '0') + ' 00000 n \n').join('');
  out += `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${x}\n%%EOF\n`;
  return Buffer.from(out, 'latin1');
}
async function upload(name, lines) {
  const fd = new FormData();
  fd.append('files', new Blob([textPdf(lines)], {type: 'application/pdf'}), name);
  fd.append('ws', 'private');
  const r = await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
  const id = (await r.json()).ids[0];
  await until(async () => ['done', 'failed'].includes((await call('GET', `/api/docs/${id}`)).state), 150);
  return id;
}
function touch(w, el, type, pts) {  // jsdom has no Touch constructor: touches as plain objects
  const ev = new w.Event(type, {bubbles: true, cancelable: true});
  Object.defineProperty(ev, 'touches', {value: type === 'touchend' || type === 'touchcancel' ? [] : pts.map(([x, y]) => ({clientX: x, clientY: y, target: el}))});
  el.dispatchEvent(ev);
}
function swipe(w, el, dx) {
  touch(w, el, 'touchstart', [[200, 300]]);
  for (const f of [.25, .5, .75, 1]) touch(w, el, 'touchmove', [[200 + dx * f, 300]]);
  touch(w, el, 'touchend', []);
}

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'});
  const IDS = [];
  for (const [n, l] of [['one.pdf', 'Versicherung Beispiel AG'], ['two.pdf', 'Stadtwerke Musterstadt'], ['three.pdf', 'Telefon Beispiel GmbH'],
    ['four.pdf', 'Verein Beispielhausen']]) IDS.push(await upload(n, [l, 'Brief', 'Datum 0' + (IDS.length + 1) + '.10.2026']));
  for (const id of IDS) await call('POST', `/api/docs/${id}/review`, {done: true});
  const pid = (await call('GET', `/api/docs/${IDS[0]}`)).parent_id;
  check(pid && (await call('GET', `/api/docs/${IDS[3]}`)).parent_id === pid, 'the four documents lie in one folder');
  await call('PATCH', '/api/settings', {set_delta: {ab_cards: {add: ['n:' + pid]}}});

  // ================= the file store on the phone: the folder as cards
  const m = await boot({user: 'alice', hash: 'ablage/' + pid, mobile: true}), d = m.document;
  check(await until(() => d.querySelectorAll('.abview [data-dco]').length === 4), 'the folder shows four document cards');
  const order = [...d.querySelectorAll('.abview [data-dco]')].map(x => +x.dataset.dco);
  const shown = () => +(d.querySelector('.modal.dc-md .dc-body')?.dataset.id || 0);
  const nav = () => d.querySelector('.modal.dc-md .dc-navn')?.textContent || '';
  const prev = () => d.querySelector('.modal.dc-md .dc-prev');
  click(m, d.querySelector(`.abview [data-dco="${order[1]}"]`));
  check(await until(() => shown() === order[1] && prev()), 'a card opens the document sheet');
  check(await until(() => nav() === '2 of 4'), 'the sheet over the file store: "2 of 4" (the folder as shown): ' + nav());
  check(!d.querySelector('.dc-nav [data-dc="step:-1"]').disabled && !d.querySelector('.dc-nav [data-dc="step:1"]').disabled, '... both arrows on');
  swipe(m, prev(), -150);
  check(await until(() => shown() === order[2] && nav() === '3 of 4'), 'a swipe to the left: the next document of the folder ' + nav());
  check(m.location.hash === '#ablage/' + pid && m.eval('S.route.mod') === 'ablage', '... the route stays on the folder: ' + m.location.hash);
  click(m, d.querySelector('.modal.dc-md [data-dc="step:1"]'));
  check(await until(() => shown() === order[3] && nav() === '4 of 4'), 'the arrow forward: the last one, "4 of 4"');
  check(d.querySelector('.dc-nav [data-dc="step:1"]').disabled, '... the arrow forward is off at the end');
  swipe(m, prev(), 150);
  check(await until(() => shown() === order[2]), 'a swipe to the right: the one before');
  click(m, d.querySelector('.modal.dc-md .dc-back'));
  check(await until(() => !d.querySelector('.dc-md') && !m.eval('DC.navSrc')), 'closed: the sheet and its list are gone');
  // the list view: "Open as document" of the row's menu leafs through the folder's documents too
  m.eval(`S.settings.ab_cards = '[]'; ab_draw(); 1`);
  await until(() => !d.querySelector('.abview [data-dco]') && d.querySelector('.ablist'));
  m.eval(`abd_menuItems(ab_item(${order[0]})).find(x => x.label === 'Open as document').fn(); 1`);
  check(await until(() => shown() === order[0] && nav() === '1 of 4'), 'the list view: "Open as document" shows "1 of 4" ' + nav());
  click(m, d.querySelector('.modal.dc-md .dc-back'));
  await until(() => !d.querySelector('.dc-md'));
  m.close();

  // ================= the documents opened by address: the document stands behind the loaded page
  const w = await boot({user: 'alice', hash: 'docs', mobile: true}), dw = w.document;
  await until(() => dw.querySelectorAll('.dc-card').length === 4);
  const all = w.eval('DC.docs.map(x => x.id)');
  w.eval('DC.page = 1; DC.docs = null; DC.at = 0; dc_load()');
  check(await until(() => dw.querySelectorAll('.dc-card').length === 1), 'a page of 1: one card');
  w.location.hash = '#docs/' + all[3];
  const navW = () => dw.querySelector('.modal.dc-md .dc-navn')?.textContent || '';
  check(await until(() => +(dw.querySelector('.modal.dc-md .dc-body')?.dataset.id || 0) === all[3]), 'the address opens the fourth document');
  check(await until(() => navW() === '4 of 4' && w.eval('DC.docs.length') === 4), 'the next pages load until it is found: "4 of 4" ' + navW());
  click(w, dw.querySelector('.modal.dc-md [data-dc="step:-1"]'));
  check(await until(() => +(dw.querySelector('.modal.dc-md .dc-body')?.dataset.id || 0) === all[2] && navW() === '3 of 4'), '... and leafs back: "3 of 4"');
  w.close();

  // ================= a locked folder (simulated): pictures and PDFs leaf, each decrypted only when turned to
  const k = await boot({user: 'alice', hash: 'ablage/' + pid, mobile: true}), dk = k.document;
  await until(() => k.eval(`typeof fsl_open === 'function' && typeof attLightbox === 'function' && !!AB.data`));
  k.eval(`(() => {
    ab_load = async () => {};  // the simulated folder stays (ab_reload loads with it)
    const f = (id, name, mime) => ({id, kind: 'file', name, mime, size: 100, locked: true, lock_id: 7, _enc: true});
    AB.data = {...AB.data, items: [f(901, 'a.pdf', 'application/pdf'), f(902, 'b.png', 'image/png'), f(903, 'c.png', 'image/png'), f(904, 'd.png', 'image/png'), {...f(905, 'Encrypted', 'image/png'), _sealed: true}]};
    window.__dec = [];
    // boot.js hands the page Node's Blob (fetch / FormData), which jsdom's FileReader refuses: a reader for it
    window.FileReader = class { readAsDataURL(b) { b.arrayBuffer().then(x => { this.result = 'data:' + b.type + ';base64,' + btoa(String.fromCharCode(...new Uint8Array(x))); this.onload(); }, () => this.onerror()); } };
    URL.createObjectURL = () => 'blob:test'; URL.revokeObjectURL = () => {};  // (jsdom has neither)
    fslKeys = async () => true;
    fslFetch = async n => { window.__dec.push(n.id); return n.id; };
    fslFileDec = async (lid, id) => { const n = AB.data.items.find(x => x.id === id); return {name: n.name, type: n.mime, data: new Uint8Array([37, 80, 68, 70, id % 256])}; };
    return 1; })()`);
  k.eval(`fsl_open(ab_item(903)); 1`);
  const lb = () => dk.querySelector('.lightbox');
  check(await until(() => lb()?.querySelector('img')), 'a picture of the locked folder opens in the image viewer');
  check(JSON.stringify(k.eval('window.__dec')) === '[903]', 'only the opened picture is decrypted, not all in advance: ' + JSON.stringify(k.eval('window.__dec')));
  check(!!lb().querySelector('[data-lb="1"]') && !!lb().querySelector('[data-lb="-1"]'), '... with the arrows of the folder\'s pictures');
  const src0 = lb().querySelector('img').getAttribute('src');
  click(k, lb().querySelector('[data-lb="1"]'));
  check(await until(() => lb()?.querySelector('img') && lb().querySelector('img').getAttribute('src') !== src0 && /d\.png/.test(lb().textContent)), 'the arrow forward: the next picture (d.png), decrypted now');
  check(JSON.stringify(k.eval('window.__dec')) === '[903,904]', '... decrypted when turned to: ' + JSON.stringify(k.eval('window.__dec')));
  click(k, lb().querySelector('[data-lb="1"]'));
  check(await until(() => /b\.png/.test(lb()?.textContent || '') && lb().querySelector('img')), '... round to the first picture (b.png); the sealed one and the PDF are not in the row');
  click(k, lb().querySelector('[data-lb="1"]'));
  check(await until(() => /c\.png/.test(lb()?.textContent || '')), '... and on to c.png');
  check(JSON.stringify(k.eval('window.__dec')) === '[903,904,902]', '... a picture shown before is not decrypted again: ' + JSON.stringify(k.eval('window.__dec')));
  lb().remove();
  // a PDF: the PDF view leafs through the folder's PDFs and pictures
  k.eval(`window.__dec = []; window.__pv = null; pdfView = o => { window.__pv = o; }; fsl_open(ab_item(901)); 1`);
  check(await until(() => k.eval('window.__pv && window.__pv.pos')), 'a PDF of the locked folder opens with leafing');
  check(k.eval('window.__pv.pos') === '1 of 4' && k.eval('window.__pv.first') && !k.eval('window.__pv.last') && k.eval('!!window.__pv.data'), '... "1 of 4", the bytes decrypted in the browser: ' + k.eval('window.__pv.pos'));
  check(JSON.stringify(k.eval('window.__dec')) === '[901]', '... only the PDF is decrypted: ' + JSON.stringify(k.eval('window.__dec')));
  k.eval(`window.__pv.step(1).then(o => { window.__pv2 = o; }); 1`);
  check(await until(() => k.eval('!!window.__pv2')), 'the step forward gives the next one');
  check(k.eval('window.__pv2.pos') === '2 of 4' && k.eval('window.__pv2.kind') === 'img' && /^data:image\/png/.test(k.eval('window.__pv2.img')), '... the picture b.png as "2 of 4": ' + k.eval('window.__pv2.pos'));
  check(JSON.stringify(k.eval('window.__dec')) === '[901,902]', '... decrypted only now: ' + JSON.stringify(k.eval('window.__dec')));
  k.close();

  console.log(`p2683_a_docnav_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
