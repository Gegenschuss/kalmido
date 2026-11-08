// kalmido-suite:
// 2.652.0 UI test (#5071, #5073: leafing with a swipe in the full screen of a document and in the image viewer, one helper
// swipenav.js), own container (start.sh), jsdom + Firefox (phone 390 px, touch tablet 840 px). Invented data only.
// P2652A_NOSTART=1 = the container runs.
// #5071 - the full screen ("Show", pdfview.js) of a document leafs through the list on the phone too (before: only on the
//   computer, with keys and buttons): a swipe to the left = the next document, to the right = the one before; at the first
//   it springs back; a start at the screen's edge (the phone's Back gesture) and up / down change nothing; the end of a
//   swipe closes nothing. The same in tablet width with a touch screen. A PDF of a file store folder leafs through the
//   folder's PDFs and pictures; alone in its folder nothing to leaf. Firefox: the real swipe, the bar fits, enlarged (zoom
//   in) one finger moves the page and does not leaf.
// #5073 - the image viewer (attLightbox): a swipe leafs to the next / previous picture, at the ends it springs back; the edge
//   and up / down change nothing; the end of a swipe closes nothing, a plain tap still closes; Firefox: zoomed, one finger
//   does not leaf.
// P4: alice works without an organisation (private documents and files): the person without an organisation
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2652_a_swipe_ui', check, shots: 'P2652A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2652A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n = 60) => require('./boot').until(fn, {timeout: Math.max(15000, n * 200), step: 150});
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
// a 1x1 PNG
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==', 'base64');
async function docUp(name, lines) {
  const fd = new FormData();
  fd.append('files', new Blob([textPdf(lines)], {type: 'application/pdf'}), name);
  fd.append('ws', 'private');
  const r = await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
  const id = (await r.json()).ids[0];
  await until(async () => ['done', 'failed'].includes((await call('GET', `/api/docs/${id}`)).state), 150);
  return id;
}
async function fileUp(name, buf, type, parent) {
  const fd = new FormData(); fd.append('file', new Blob([buf], {type}), name); fd.append('space', 'private');
  if (parent) fd.append('parent_id', String(parent));
  const r = await fetch(B + 'api/files/upload', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
  return (await r.json()).items[0].id;
}
// a touch event (jsdom has no Touch constructor): touches as plain objects (pts = [[x, y], ...])
function touch(w, el, type, pts) {
  const ev = new w.Event(type, {bubbles: true, cancelable: true});
  Object.defineProperty(ev, 'touches', {value: type === 'touchend' || type === 'touchcancel' ? [] : pts.map(([x, y]) => ({clientX: x, clientY: y, target: el}))});
  el.dispatchEvent(ev);
  return ev;
}
function swipe(w, el, dx, dy = 0, x0 = 200) {  // one finger from (x0, 300) by dx / dy in a few steps
  touch(w, el, 'touchstart', [[x0, 300]]);
  for (const f of [.25, .5, .75, 1]) touch(w, el, 'touchmove', [[x0 + dx * f, 300 + dy * f]]);
  touch(w, el, 'touchend', []);
}

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'});
  const IDS = [];
  for (const [n, l] of [['one.pdf', 'Versicherung Beispiel AG'], ['two.pdf', 'Stadtwerke Musterstadt'], ['three.pdf', 'Telefon Beispiel GmbH']]) IDS.push(await docUp(n, [l, 'Brief']));
  for (const id of IDS) await call('POST', `/api/docs/${id}/review`, {done: true});
  const K = (await call('POST', '/api/files/folders', {name: 'Kiste', space: 'private'})).id, K2 = (await call('POST', '/api/files/folders', {name: 'Allein', space: 'private'})).id;
  const FP1 = await fileUp('a-brief.pdf', textPdf(['Brief eins']), 'application/pdf', K);
  await fileUp('b-bild.png', PNG, 'image/png', K);
  await fileUp('c-brief.pdf', textPdf(['Brief zwei']), 'application/pdf', K);
  await fileUp('d-notiz.txt', 'nur Text', 'text/plain', K);
  const FA = await fileUp('allein.pdf', textPdf(['Allein']), 'application/pdf', K2);

  // ================= #5071: the full screen of a document, phone (390) and touch tablet (wider, hover: none)
  for (const [label, opt] of [['phone', {mobile: true}], ['tablet', {media: {'(hover: none)': true, '(pointer: coarse)': true}}]]) {
    const m = await boot({user: 'alice', hash: 'docs', ...opt}), d = m.document;
    await until(() => d.querySelectorAll('.dc-card').length === 3);
    const order = m.eval('DC.docs.map(x => x.id)');
    click(m, d.querySelector(`.dc-view [data-dco="${order[0]}"]`));
    check(await until(() => d.querySelector(`.dc-md .dc-body[data-id="${order[0]}"] .dc-prev`)), `${label}: the document opens with its preview`);
    click(m, d.querySelector('.dc-md [data-dc="view"]'));
    const lb = () => d.querySelector('.lightbox.pview'), no = () => lb()?.querySelector('.pvdno')?.textContent || '', body = () => lb()?.querySelector('.pvbody');
    check(await until(() => lb() && no() === '1 of 3'), `${label}: the full screen leafs through the list: "1 of 3" (${no()})`);
    swipe(m, body(), -150);
    check(await until(() => no() === '2 of 3' && m.eval('DC.doc?.id') === order[1]), `${label}: a swipe to the left in the full screen = the next document (${no()})`);
    check(lb()?.isConnected && d.querySelectorAll('.lightbox').length === 1, `${label}: ... still one full screen`);
    swipe(m, body(), 150);
    check(await until(() => no() === '1 of 3' && m.eval('DC.doc?.id') === order[0]), `${label}: a swipe to the right = the one before`);
    swipe(m, body(), 150);
    click(m, lb());
    check(await until(() => !body()?.style.transform) && no() === '1 of 3' && lb(), `${label}: before the first it springs back; the end of the swipe closes nothing`);
    swipe(m, body(), -150, 0, 8);
    swipe(m, body(), -20, -160);
    await until(() => m.eval('DC.doc?.id') === order[0]);
    check(no() === '1 of 3', `${label}: a start at the screen's edge and a swipe up do not leaf`);
    click(m, lb().querySelector('[data-pv="x"]'));
    await until(() => !lb());
    m.close();
  }

  // ================= #5071: a PDF of a file store folder leafs through the folder's PDFs and pictures (phone)
  {
    const m = await boot({user: 'alice', hash: `ablage/${K}`, mobile: true, ls: {abSpace: '"private"'}}), d = m.document;
    check(await until(() => m.eval(`(AB.data?.items || []).length === 4`)), 'file store: the folder with four files');
    m.eval(`ab_openFile(ab_item(${FP1}))`);
    const lb = () => d.querySelector('.lightbox.pview'), no = () => lb()?.querySelector('.pvdno')?.textContent || '', name = () => lb()?.querySelector('.tvname b')?.textContent || '';
    check(await until(() => no() === '1 of 3' && name() === 'a-brief.pdf'), `file store: a PDF of the folder leafs: "1 of 3" (the text file is left out) (${no()} ${name()})`);
    swipe(m, lb().querySelector('.pvbody'), -150);
    check(await until(() => no() === '2 of 3' && name() === 'b-bild.png' && lb().querySelector('.pvimg')), 'file store: a swipe = the picture after it, shown in the full screen');
    swipe(m, lb().querySelector('.pvbody'), -150);
    check(await until(() => no() === '3 of 3' && name() === 'c-brief.pdf'), 'file store: ... and the PDF after that');
    check(lb().querySelector('[data-pv="dnext"]').disabled, 'file store: ... the last: forward off');
    click(m, lb().querySelector('[data-pv="x"]'));
    await until(() => !lb());
    m.eval(`go('ablage/${K2}')`);
    await until(() => m.eval(`(AB.data?.items || []).length === 1 && AB.data.items[0].id === ${FA}`));
    m.eval(`ab_openFile(ab_item(${FA}))`);
    check(await until(() => lb()?.querySelector('.tvname b')?.textContent === 'allein.pdf') && !lb().querySelector('.pvdocs'), 'file store: alone in its folder nothing to leaf');
    m.close();
  }

  // ================= #5073: the image viewer, phone and touch tablet
  for (const [label, opt] of [['phone', {mobile: true}], ['tablet', {media: {'(hover: none)': true, '(pointer: coarse)': true}}]]) {
    const m = await boot({user: 'alice', hash: 'ablage', ...opt}), d = m.document;
    const open = () => m.eval(`attLightbox('a', ['a', 'b', 'c'].map(id => ({id, name: id + '.png', size: 10})), (a, dl) => '/static/icon.svg?' + a.id + (dl ? '&dl' : ''))`);
    open();
    const lb = () => d.querySelector('.lightbox:not(.pview)'), img = () => lb()?.querySelector('img'), at = () => (img()?.getAttribute('src') || '').replace(/.*\?/, '');
    check(lb() && at() === 'a', `${label} viewer: the first picture`);
    swipe(m, img(), -150);
    click(m, img());  // 2.727.0 (#5202): the tap right after the swipe (the next picture snaps in meanwhile, then it is drawn)
    check(await until(() => at() === 'b'), `${label} viewer: a swipe to the left = the next picture (${at()})`);
    check(lb() && at() === 'b', `${label} viewer: the end of a swipe is no tap (the view stays open)`);
    swipe(m, img(), 150);
    check(await until(() => at() === 'a'), `${label} viewer: a swipe to the right = the one before`);
    swipe(m, img(), 150);
    check(await until(() => !img()?.style.transform) && at() === 'a', `${label} viewer: before the first it springs back (no wrap round)`);
    swipe(m, img(), -150, 0, 8);
    swipe(m, img(), -20, -160);
    check(at() === 'a', `${label} viewer: a start at the screen's edge and a swipe up do not leaf`);
    click(m, lb().querySelector('[data-lb="x"]'));
    open();
    click(m, img());
    check(await until(() => !lb()), `${label} viewer: a plain tap on the picture still closes it`);
    m.close();
  }

  // ================= Firefox: the real layout on a touch screen, phone 390 and tablet 840
  await firefox(async ({cmd, ev, nav: go, ctx, shot}) => {
    await go(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: login');
    const wait = async (js, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(js).catch(() => false)) return true; await sleep(250); } return false; };
    const TOUCH = `const tc = (el, type, pts) => { const e = new Event(type, {bubbles: true, cancelable: true}); Object.defineProperty(e, 'touches', {value: type === 'touchend' ? [] : pts.map(([x, y]) => ({clientX: x, clientY: y, target: el}))}); el.dispatchEvent(e); };
      const sw = (el, dx) => { const r = el.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + Math.min(120, r.height / 2); tc(el, 'touchstart', [[x, y]]); for (const f of [.25, .5, .75, 1]) tc(el, 'touchmove', [[x + dx * f, y]]); tc(el, 'touchend', []); };`;
    for (const W of [390, 840]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: W, height: 760}});
      check(await wait(`innerWidth === ${W}`, 40), `Firefox ${W}: the window has its size`);
      await go(B + '#docs');
      check(await wait(`document.querySelectorAll('.dc-card').length === 3 && !!DC.docs`), `Firefox ${W}: three cards`);
      check(await ev(`isTouch()`), `Firefox ${W}: a touch screen`);
      await ev(`(document.querySelector('.dc-view [data-dco="' + DC.docs[0].id + '"]').click(), 1)`);
      check(await wait(`!!document.querySelector('.dc-md [data-dc="view"]')`), `Firefox ${W}: the document is open`);
      await ev(`(document.querySelector('.dc-md [data-dc="view"]').click(), 1)`);
      const NO = `(document.querySelector('.lightbox.pview .pvdno')?.textContent || '')`;
      check(await wait(`${NO} === '1 of 3' && !!document.querySelector('.lightbox.pview .pvpage canvas')`, 80), `Firefox ${W}: the full screen "1 of 3", the page drawn`);
      const bar = await ev(`(() => { const b = document.querySelector('.lightbox.pview .pvbar'), p = document.querySelector('.lightbox.pview .pvdocs').getBoundingClientRect(); return {sw: b.scrollWidth, cw: b.clientWidth, r: Math.round(p.right), ta: getComputedStyle(document.querySelector('.lightbox.pview .pvbody')).touchAction}; })()`);
      check(bar.sw <= bar.cw + 1 && bar.r <= W && bar.ta === 'pan-y', `Firefox ${W}: the bar with "x of N" fits, the page takes sideways swipes ` + JSON.stringify(bar));
      await ev(`(() => { ${TOUCH} sw(document.querySelector('.lightbox.pview .pvbody'), -${Math.round(W * .4)}); return 1; })()`);
      check(await wait(`${NO} === '2 of 3' && DC.doc.id === DC.docs[1].id`), `Firefox ${W}: a swipe in the full screen = the next document`);
      await shot(`p2652a-full-${W}.png`);
      check(await wait(`!!document.querySelector('.lightbox.pview .pvpage canvas')`, 80), `Firefox ${W}: ... its page drawn`);
      await ev(`(document.querySelector('.lightbox.pview [data-pv="in"]').click(), document.querySelector('.lightbox.pview [data-pv="in"]').click(), 1)`);
      check(await wait(`document.querySelector('.lightbox.pview .pvpage').offsetWidth > document.querySelector('.lightbox.pview .pvbody').clientWidth`), `Firefox ${W}: zoomed in, wider than the view`);
      await ev(`(() => { ${TOUCH} sw(document.querySelector('.lightbox.pview .pvbody'), -${Math.round(W * .4)}); return 1; })()`);
      await sleep(400);  // nothing may happen: no state to wait for
      check(await ev(`${NO} === '2 of 3' && getComputedStyle(document.querySelector('.lightbox.pview .pvbody')).touchAction !== 'pan-y'`), `Firefox ${W}: enlarged, one finger does not leaf (the page scrolls)`);
      await ev(`(document.querySelector('.lightbox.pview [data-pv="x"]').click(), 1)`);
      await wait(`!document.querySelector('.lightbox')`);
      // #5073: the image viewer
      await ev(`(attLightbox('a', ['a', 'b'].map(id => ({id, name: id + '.png', size: 10})), (a, dl) => '/static/icon.svg?' + a.id + (dl ? '&dl' : '')), 1)`);
      const AT = `(document.querySelector('.lightbox > img')?.getAttribute('src') || '').replace(/.*\\?/, '')`;
      check(await wait(`${AT} === 'a' && document.querySelector('.lightbox > img').complete && typeof swn_attach === 'function'`), `Firefox ${W}: the image viewer open`);
      // 2.727.0 (#5202): the tap right after the swipe (the next picture snaps in first)
      await ev(`(() => { ${TOUCH} sw(document.querySelector('.lightbox > img'), -${Math.round(W * .4)}); document.querySelector('.lightbox > img').click(); return 1; })()`);
      check(await wait(`${AT} === 'b'`), `Firefox ${W}: a swipe on the picture = the next picture`);
      check(await ev(`!!document.querySelector('.lightbox')`), `Firefox ${W}: ... the end of the swipe does not close it`);
      const img = `document.querySelector('.lightbox > img')`;
      await ev(`(async () => { const el = ${img}, r = el.getBoundingClientRect(); for (let i = 0; i < 3; i++) { el.dispatchEvent(new WheelEvent('wheel', {deltaY: -100, ctrlKey: true, clientX: r.left + r.width / 2, clientY: r.top + r.height / 2, bubbles: true, cancelable: true})); await new Promise(f => requestAnimationFrame(f)); } return 1; })()`);
      check(await wait(`pz_busy() === false && document.querySelector('.lightbox').classList.contains('lbz')`), `Firefox ${W}: the picture zoomed`);
      await ev(`(() => { ${TOUCH} sw(${img}, ${Math.round(W * .4)}); return 1; })()`);
      await sleep(400);  // nothing may happen: no state to wait for
      check(await ev(`${AT} === 'b'`), `Firefox ${W}: zoomed, one finger does not leaf`);
      await ev(`(document.querySelector('.lightbox [data-lb="x"]').click(), 1)`);
    }
  }, true);

  console.log(`p2652_a_swipe_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
