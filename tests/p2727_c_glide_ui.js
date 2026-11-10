// kalmido-suite:
// 2.727.0 UI test (#5202: leafing like turning a page - the neighbour lies beside the open document as a placeholder and glides
// along with the finger; let go, it snaps into place and only then its content loads), own container (start.sh), jsdom (phone).
// Invented data only. P2727C_NOSTART=1 = the container runs.
// - documents (docs.js, 2.583.0: in the document view docview.js, its preview .dv-pages): mid-swipe the next document's placeholder (its title, its small picture fetched ahead) is in the page and
//   moved with the open one; let go: the open one first slides fully out (nothing is fetched yet), then the next one loads and
//   stands in place (no glide-in, no placeholder left); a short swipe springs back; at the real end no placeholder, the short
//   spring back stays; prefers-reduced-motion: it changes at once
// - swipenav.js (image viewer attLightbox, full screen pdfview): the next picture lies beside it and glides along, it snaps in
//   before the viewer shows it; the first has nothing before it
// P4: alice works without an organisation (private documents): the person without an organisation (freelancer-matrix: docs)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2727C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n = 60) => require('./boot').until(fn, {timeout: Math.max(15000, n * 200), step: 100});
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
// one finger from (200, 300) by dx in a few steps, held (not let go)
function hold(w, el, dx) {
  touch(w, el, 'touchstart', [[200, 300]]);
  for (const f of [.25, .5, .75, 1]) touch(w, el, 'touchmove', [[200 + dx * f, 300]]);
}
// 2.882.0 (#5557): the swipe is swipenav.js now (the body is the frame that stays, its parts glide, the neighbours lie in it as .swn-nb)
const tx = el => { const m = /translateX\((-?[\d.]+)px\)/.exec(el?.style.transform || ''); return m ? +m[1] : 0; };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'});
  const IDS = [];
  for (const [n, l] of [['one.pdf', 'Versicherung Beispiel AG'], ['two.pdf', 'Stadtwerke Musterstadt'], ['three.pdf', 'Telefon Beispiel GmbH']]) IDS.push(await upload(n, [l, 'Brief']));
  for (const id of IDS) await call('POST', `/api/docs/${id}/review`, {done: true});

  // ================= documents on the phone
  const m = await boot({user: 'alice', hash: 'docs', mobile: true}), d = m.document;
  await until(() => d.querySelectorAll('.dc-card').length === 3);
  const order = m.eval('DC.docs.map(x => x.id)'), names = m.eval('DC.docs.map(x => x.name)');
  m.eval('DC.docs.forEach(x => { x.thumb = x.thumb || 1; }); 1');  // every one with a small picture (the address is enough here)
  const body = () => d.querySelector('.dv-view .dc-body'), part = () => body()?.querySelector(':scope > .dv-pv'), shown = () => +(body()?.dataset.id || 0), prev = () => d.querySelector('.dv-view .dv-pages');
  // 2.736.0 (#5212): the neighbours are drawn whole ahead now (p2736_b_docswipe_seamless_ui); here the placeholder that stands
  // while their data are not there yet: nothing is fetched ahead in this window
  m.eval('dc_nbAhead = () => {}; 1');
  click(m, d.querySelector(`[data-dco="${order[0]}"]`));
  check(await until(() => shown() === order[0] && prev()), 'phone: the first document opens');
  const u1 = m.eval(`dc_nbThumb(DC.docs[1])`);
  check(u1 && await until(() => m.eval(`!!DCW.pre?.has(${JSON.stringify(u1)})`)), 'the next one\'s small picture is fetched ahead: ' + u1);

  hold(m, prev(), -120);
  const nb = () => d.querySelector('.dv-view .dc-body > .swn-nb[data-dir="1"] > .dc-nb'), gone = () => !d.querySelector('.dv-view .dc-nb, .dv-view .swn-nb');
  check(nb() && nb().querySelector('h3')?.textContent === names[1], 'mid-swipe: the next document lies beside it as a placeholder with its title: ' + nb()?.textContent);
  check(nb()?.querySelector('.dc-nbv img')?.getAttribute('src') === u1, '... with its small picture (the one fetched ahead)');
  check(tx(part()) === -120 && tx(nb().parentElement) > 0, '... the open one and the placeholder beside it moved with the finger: ' + part().style.transform + ' / ' + nb()?.parentElement.style.transform);
  check(!d.querySelector('.dv-view .dc-body > .swn-nb[data-dir="-1"]'), '... the first has nothing before it');
  check(m.eval('DC.opening') == null && shown() === order[0], '... nothing fetched yet');
  touch(m, prev(), 'touchend', []);
  check(tx(part()) < -120 && m.eval('DCW.snap === true') && m.eval('DC.opening') == null && shown() === order[0], 'let go: it snaps fully over first, the next one is not fetched yet: ' + part().style.transform);
  check(await until(() => shown() === order[1]), 'then the next document is loaded');
  check(await until(() => !tx(part()) && gone()) /* 2.736.0 (#5212): in the view */ && !body().classList.contains('dc-in-n') && !body().classList.contains('dc-in-p'), '... in place at once: no placeholder left, no glide-in afterwards');

  hold(m, prev(), -25);  // short and slow: under the threshold
  check(d.querySelector('.dv-view .dc-body > .swn-nb[data-dir="1"] > .dc-nb') && d.querySelector('.dv-view .dc-body > .swn-nb[data-dir="-1"] > .dc-nb'), 'in the middle: placeholders on both sides');
  touch(m, prev(), 'touchend', []);
  check(await until(() => !tx(part()) && gone()) && shown() === order[1], 'a short swipe springs back: the same one, no placeholder left');

  click(m, d.querySelector('.dv-view [data-dc="step:1"]'));
  check(await until(() => shown() === order[2]), 'the arrow forward: the last one');
  hold(m, prev(), -150);
  check(!d.querySelector('.dv-view .dc-body > .swn-nb') && tx(part()) === -45, 'at the real end: no placeholder, it follows only a little: ' + part().style.transform);
  touch(m, prev(), 'touchend', []);
  check(await until(() => !tx(part())) && shown() === order[2] && m.eval('DC.opening') == null, '... and springs back (2.882.0, #5557: the spring back of swipenav.js)');
  m.close();

  // ================= reduced motion: it changes at once
  const r = await boot({user: 'alice', hash: 'docs', mobile: true, media: {'(prefers-reduced-motion: reduce)': true}}), dr = r.document;
  await until(() => dr.querySelectorAll('.dc-card').length === 3);
  click(r, dr.querySelector(`[data-dco="${order[0]}"]`));
  await until(() => +(dr.querySelector('.dv-view .dc-body')?.dataset.id || 0) === order[0] && dr.querySelector('.dv-view .dv-pages'));
  hold(r, dr.querySelector('.dv-view .dv-pages'), -150);
  touch(r, dr.querySelector('.dv-view .dv-pages'), 'touchend', []);
  check(r.eval('DC.opening') === order[1], 'reduced motion: let go, the next one is fetched at once (no snapping animation)');
  check(await until(() => +(dr.querySelector('.dv-view .dc-body')?.dataset.id || 0) === order[1] && !dr.querySelector('.dv-view .dc-nb, .dv-view .swn-nb')), '... and shown');
  r.close();

  // ================= swipenav.js: the image viewer and the full screen
  const v = await boot({user: 'alice', hash: 'docs', mobile: true}), dv = v.document;
  await until(() => dv.querySelectorAll('.dc-card').length === 3);
  v.eval(`attLightbox('a', ['a', 'b', 'c'].map(id => ({id, name: id + '.png', size: 10})), (a, dl) => '/static/icon.svg?' + a.id + (dl ? '&dl' : ''))`);
  const lb = () => dv.querySelector('.lightbox:not(.pview)'), img = () => lb()?.querySelector('img'), at = () => (img()?.getAttribute('src') || '').replace(/.*\?/, '');
  check(await until(() => v.eval(`typeof swn_attach === 'function'`) && at() === 'a'), 'viewer: the first picture (swipenav loaded)');
  check(await until(() => v.eval(`SWN_PRE.has('/static/icon.svg?b')`)), 'viewer: the next picture is fetched ahead');
  hold(v, img(), -120);
  const snb = () => lb()?.querySelector('.swn-nb[data-dir="1"]');
  check(snb()?.querySelector('img')?.getAttribute('src') === '/static/icon.svg?b' && /translateX\(\d+px\)/.test(snb().style.transform), 'viewer mid-swipe: the next picture lies beside it and moves along: ' + snb()?.style.transform);
  check(tx(img()) === -120 && !lb().querySelector('.swn-nb[data-dir="-1"]'), '... the picture moved with the finger, nothing before the first');
  touch(v, img(), 'touchend', []);
  check(at() === 'a' && /translateX\(0px\)/.test(snb()?.style.transform || ''), 'let go: the next one snaps into place before the viewer shows it');
  check(await until(() => at() === 'b' && !lb().querySelector('.swn-nb')), '... then the viewer shows it, no placeholder left');
  check(await until(() => v.eval(`SWN_PRE.has('/static/icon.svg?c')`)), '... and fetches the one after it ahead');
  click(v, lb().querySelector('[data-lb="x"]'));
  await until(() => !lb());
  // the full screen of a document (pdfview): the next one's placeholder glides along
  click(v, dv.querySelector(`[data-dco="${order[0]}"]`));
  await until(() => +(dv.querySelector('.dv-view .dc-body')?.dataset.id || 0) === order[0] && dv.querySelector('.dv-view [data-dc="view"]'));
  click(v, dv.querySelector('.dv-view [data-dc="view"]'));
  const pv = () => dv.querySelector('.lightbox.pview'), no = () => pv()?.querySelector('.pvdno')?.textContent || '';
  check(await until(() => no() === '1 of 3' && v.eval(`typeof swn_attach === 'function'`)), 'full screen: "1 of 3"');
  hold(v, pv().querySelector('.pvbody'), -120);
  check(pv().querySelector('.swn-nb[data-dir="1"]') && tx(pv().querySelector('.pvbody')) === -120, 'full screen mid-swipe: the next one\'s placeholder lies beside the page');
  touch(v, pv().querySelector('.pvbody'), 'touchend', []);
  check(await until(() => no() === '2 of 3' && !dv.querySelector('.swn-nb')), 'full screen: then the next document, no placeholder left');
  v.close();

  console.log(`p2727_c_glide_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
