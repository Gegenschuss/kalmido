// kalmido-suite:
// 2.476.0 UI test (#3935: leafing through the open document with a swipe, "x of N", arrow buttons, the list loads the next
// page at its end), own container (start.sh), jsdom + Firefox (phone 390 px and 320 px). Invented data only.
// P2476A_NOSTART=1 = the container runs. A small page (DC.page = 2, the test switch) stands for the 200 of a real load.
// - phone: "1 of 5" and two arrow buttons above the preview; a swipe to the left on the preview = the next document (glides
//   in with the swipe - 2.727.0 #5202, the address follows), to the right = the one before; a swipe on the fields below or up / down changes nothing; the
//   end of a swipe opens no viewer
// - past the last loaded document the next page loads (swipe and arrow button); at the real end the page springs back
// - the preview enlarged with two fingers: one finger moves it, no turn; back at normal size the swipe turns again
// - the list: "Load more (2 of 5)" at its end loads the next page (Firefox: its end coming into view loads it by itself)
// - "To review": "Checked" brings the next document at once (pane on the computer, the page on the phone)
// P4: alice works without an organisation (private documents): the person without an organisation (freelancer-matrix: docs)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2476_a_docswipe_ui', check, shots: 'P2476A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2476A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
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
// a touch event (jsdom has no Touch constructor): touches as plain objects (pts = [[x, y], ...])
function touch(w, el, type, pts) {
  const ev = new w.Event(type, {bubbles: true, cancelable: true});
  Object.defineProperty(ev, 'touches', {value: type === 'touchend' || type === 'touchcancel' ? [] : pts.map(([x, y]) => ({clientX: x, clientY: y, target: el}))});
  el.dispatchEvent(ev);
  return ev;
}
function swipe(w, el, dx, dy = 0) {  // one finger from (200, 300) by dx / dy in a few steps
  touch(w, el, 'touchstart', [[200, 300]]);
  for (const f of [.25, .5, .75, 1]) touch(w, el, 'touchmove', [[200 + dx * f, 300 + dy * f]]);
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
    ['four.pdf', 'Bäckerei Mustermann'], ['five.pdf', 'Verein Beispielhausen']]) IDS.push(await upload(n, [l, 'Brief', 'Datum 0' + (IDS.length + 1) + '.10.2026']));
  for (const id of IDS) await call('POST', `/api/docs/${id}/review`, {done: true});  // all out of "To review" first

  // ================= phone: the whole page
  const m = await boot({user: 'alice', hash: 'docs', mobile: true}), d = m.document;
  await until(() => d.querySelectorAll('.dc-card').length === 5);
  m.eval('DC.page = 2; DC.docs = null; DC.at = 0; dc_load()');
  check(await until(() => d.querySelectorAll('.dc-card').length === 2), 'a page of 2: two cards');
  check(/Load more \(2 of 5\)/.test(d.querySelector('.dc-moreld [data-dc="loadmore"]')?.textContent || '') && !/narrow the search/.test(d.body.textContent), 'the end of the list: "Load more (2 of 5)" instead of "narrow the search"');
  const order = m.eval('DC.docs.map(x => x.id)');
  const shown = () => +(d.querySelector('.dv-view .dc-body')?.dataset.id || 0);
  const nav = () => d.querySelector('.dv-view .dc-navn')?.textContent || '';
  const prev = () => d.querySelector('.dv-view .dv-pages');
  click(m, d.querySelector(`[data-dco="${order[0]}"]`));
  check(await until(() => shown() === order[0] && prev()), 'phone: the document opens as the page');
  check(nav() === '1 of 5', '"1 of 5" above the preview: ' + nav());
  // 2.583.0 (#4835): the view: "1 of 5" in its head, the preview below it
  const top = d.querySelector('.dv-view .dv-navslot');
  check(top?.firstElementChild?.classList.contains('dc-nav') && d.querySelector('.dc-nav').compareDocumentPosition(prev()) & m.Node.DOCUMENT_POSITION_FOLLOWING, '... above the preview');
  check(d.querySelector('.dc-nav [data-dc="step:-1"]').disabled && !d.querySelector('.dc-nav [data-dc="step:1"]').disabled, '... the arrow back is off at the first, the arrow forward on');
  check(d.querySelector('.dc-nav [data-dc="step:1"]').getAttribute('aria-label') === 'Next document', '... the arrows are named');

  m.eval('window.__pv = 0; pdfView = () => { window.__pv++; }');
  swipe(m, prev(), -150);
  click(m, prev());  // 2.727.0 (#5202): the tap the browser sends right after the swipe (the next one snaps in meanwhile)
  check(await until(() => shown() === order[1]), 'a swipe to the left on the preview: the next document');
  check(m.location.hash === `#ablage/${order[1]}` && nav() === '2 of 5', '... the address and "2 of 5" follow ' + m.location.hash + ' ' + nav());
  // 2.727.0 (#5202): it snapped in with the swipe (the placeholder glided along, p2727_c_glide_ui): no glide-in afterwards
  // 2.736.0 (#5212): the neighbours drawn ahead wait outside the view (.dv-nbhold): no placeholder left IN the view
  check(!d.querySelector('.dv-view .dc-body').classList.contains('dc-in-n') && !d.querySelector('.dv-view .dc-nb'), '... it stands in place, no glide-in afterwards');
  check(m.eval('window.__pv') === 0, '... the end of the swipe opens no viewer');
  swipe(m, prev(), 150);
  check(await until(() => shown() === order[0] && nav() === '1 of 5'), 'a swipe to the right: the document before');
  swipe(m, prev(), 150);
  await sleep(300);
  check(shown() === order[0] && d.querySelector('.dv-view .dc-body').classList.contains('dc-bnc-p'), 'before the first: it springs back, the first stays');
  swipe(m, d.querySelector('.dv-view #dc-sender'), -150);
  await sleep(300);
  check(shown() === order[0], 'a swipe on the fields below changes nothing');
  swipe(m, prev(), -20, -160);
  await sleep(300);
  check(shown() === order[0], 'a swipe up on the preview changes nothing (the page scrolls)');

  // past the loaded page: the next one loads
  click(m, d.querySelector('.dv-view [data-dc="step:1"]'));
  check(await until(() => shown() === order[1]), 'the arrow button forward: the next document');
  swipe(m, prev(), -150);
  check(await until(() => m.eval('DC.docs.length') === 4 && shown() === m.eval('DC.docs[2].id')), 'past the loaded page the swipe loads the next one and turns');
  check(nav() === '3 of 5', '... "3 of 5": ' + nav());
  click(m, d.querySelector('.dv-view [data-dc="step:1"]'));
  await until(() => shown() === m.eval('DC.docs[3].id'));
  click(m, d.querySelector('.dv-view [data-dc="step:1"]'));
  check(await until(() => m.eval('DC.docs.length') === 5 && shown() === m.eval('DC.docs[4].id') && nav() === '5 of 5'), 'the arrow button loads the next page too: "5 of 5"');
  check(d.querySelector('.dc-nav [data-dc="step:1"]').disabled, '... the arrow forward is off at the real end');
  const last = shown();
  swipe(m, prev(), -150);
  await sleep(300);
  check(shown() === last && d.querySelector('.dv-view .dc-body').classList.contains('dc-bnc-n'), 'at the real end: it springs back');
  check(new Set(m.eval('DC.docs.map(x => x.id)')).size === 5, '... the list holds each document once');

  // two fingers enlarge the preview: one finger moves it then, no turn
  const box = prev();
  touch(m, box, 'touchstart', [[150, 300], [200, 300]]);
  touch(m, box, 'touchmove', [[110, 300], [240, 300]]);
  touch(m, box, 'touchmove', [[100, 300], [250, 300]]);
  touch(m, box, 'touchend', []);
  check(m.eval(`document.querySelector('.dv-view .dv-pages')._z.k`) > 2.5 && box.classList.contains('dc-zoomed'), 'two fingers enlarge the preview ' + m.eval(`document.querySelector('.dv-view .dv-pages')._z.k`));
  swipe(m, prev(), 150);
  await sleep(300);
  check(shown() === last && box.classList.contains('dc-zoomed'), '... enlarged a swipe moves the picture, the document stays');
  touch(m, box, 'touchstart', [[100, 300], [250, 300]]);
  touch(m, box, 'touchmove', [[150, 300], [200, 300]]);
  touch(m, box, 'touchend', []);
  check(!box.classList.contains('dc-zoomed') && m.eval(`document.querySelector('.dv-view .dv-pages')._z.k`) === 1, '... shrunk back: normal size');
  swipe(m, prev(), 150);
  check(await until(() => shown() === m.eval('DC.docs[3].id') && nav() === '4 of 5'), '... at normal size the swipe turns again');
  click(m, d.querySelector('.dv-view .dv-back'));
  await until(() => !d.querySelector('.dc-md') && m.location.hash === '#ablage/docs' && d.querySelector('.dc-view'));  // 2.583.0 (#4835): Back goes back in the history

  // "To review" on the phone: Checked -> the next one at once
  for (const id of IDS.slice(0, 3)) await call('POST', `/api/docs/${id}/review`, {done: false});
  m.location.hash = '#docs/review';
  check(await until(() => d.querySelectorAll('.dc-card').length === 2 && m.eval('DC.f.review')), 'phone: "To review" (page of 2 of 3)');
  const rv = m.eval('DC.docs.map(x => x.id)');
  click(m, d.querySelector(`[data-dco="${rv[0]}"]`));
  await until(() => shown() === rv[0] && d.querySelector('.dv-view [data-dc="checked"]'));
  click(m, d.querySelector('.dv-view [data-dc="checked"]'));
  check(await until(() => shown() === rv[1] && d.querySelector('.dv-view [data-dc="checked"]')), 'phone: after "Checked" the next document to review comes at once');
  check(await until(async () => !(await call('GET', `/api/docs/${rv[0]}`)).review), '... the first is checked');
  m.close();

  // ================= computer: the list loads the next page, "To review" in the pane
  const w = await boot({user: 'alice', hash: 'docs'}), dw = w.document;
  await until(() => dw.querySelectorAll('.dc-card').length === 5);
  w.eval('DC.page = 2; DC.docs = null; DC.at = 0; dc_load()');
  await until(() => dw.querySelectorAll('.dc-card').length === 2);
  click(w, dw.querySelector('.dc-moreld [data-dc="loadmore"]'));
  check(await until(() => dw.querySelectorAll('.dc-card').length === 4 && /4 of 5/.test(dw.querySelector('.dc-moreld')?.textContent || '')), '"Load more" adds the next page: 4 cards, "4 of 5"');
  click(w, dw.querySelector('.dc-moreld [data-dc="loadmore"]'));
  check(await until(() => dw.querySelectorAll('.dc-card').length === 5 && !dw.querySelector('.dc-moreld')), '... the last page: 5 cards, no button any more');
  w.eval('dc_load()');  // the same list loaded again keeps the pages after the first
  await sleep(600);
  check(await until(() => !w.eval('DC.loading') && dw.querySelectorAll('.dc-card').length === 5), 'loaded again (the poll): the later pages stay');
  w.close();
  const w2 = await boot({user: 'alice', hash: 'docs/review'}), d2 = w2.document;
  await until(() => d2.querySelectorAll('.dc-card').length === 2);
  const rv2 = w2.eval('DC.docs.map(x => x.id)');
  const pane = () => +(d2.querySelector('.dv-view .dc-body')?.dataset.id || 0);
  click(w2, d2.querySelector(`.dc-view [data-dco="${rv2[0]}"]`));
  await until(() => pane() === rv2[0] && d2.querySelector('.dv-view [data-dc="checked"]'));
  check(/1 of 2/.test(d2.querySelector('.dv-view .dc-navn')?.textContent || ''), 'computer: "1 of 2" in the pane too');
  click(w2, d2.querySelector('.dv-view [data-dc="checked"]'));
  check(await until(() => pane() === rv2[1] && d2.querySelector('.dv-view') && w2.location.hash === `#ablage/${rv2[1]}`), 'computer: after "Checked" the pane shows the next document to review');
  check(await until(() => /1 of 1/.test(d2.querySelector('.dv-view .dc-navn')?.textContent || '')), '... the counter follows the shorter list: "1 of 1"');
  click(w2, d2.querySelector('.dv-view [data-dc="checked"]'));
  check(await until(() => !d2.querySelector('.dv-view')), '... the last one checked: the pane closes');
  w2.close();

  // ================= Firefox: the real layout on phones (390 / 320 px), a touch screen
  await firefox(async ({cmd, ev, nav: go, ctx, shot}) => {
    await go(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: login');
    const wait = async (js, n = 50) => { for (let i = 0; i < n; i++) { if (await ev(js).catch(() => false)) return true; await sleep(250); } return false; };
    const TOUCH = `const tc = (el, type, pts) => { const e = new Event(type, {bubbles: true, cancelable: true}); Object.defineProperty(e, 'touches', {value: type === 'touchend' ? [] : pts.map(([x, y]) => ({clientX: x, clientY: y, target: el}))}); el.dispatchEvent(e); };
      const sw = (el, dx) => { const r = el.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + Math.min(80, r.height / 2); tc(el, 'touchstart', [[x, y]]); for (const f of [.25, .5, .75, 1]) tc(el, 'touchmove', [[x + dx * f, y]]); tc(el, 'touchend', []); };`;
    for (const W of [390, 320]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: W, height: 700}});
      await go(B + '#docs');
      check(await wait(`document.querySelectorAll('.dc-card').length === 5`), `Firefox ${W}: five cards`);
      // the list: scrolled to its end it loads the next page by itself
      await ev(`(DC.page = 2, DC.docs = null, DC.at = 0, dc_load(), 1)`);
      // (two cards fill no phone: the end of the list is in view at once, page after page follows until all are there)
      check(await wait(`DC.docs.length === 5 && document.querySelectorAll('.dc-card').length === 5 && !document.querySelector('.dc-moreld')`), `Firefox ${W}: the end of the list in view loads the next pages by itself`);
      const first = await ev(`DC.docs[0].id`);
      await ev(`(document.querySelector('.dc-view [data-dco="${first}"]').click(), 1)`);
      check(await wait(`!!document.querySelector('.dv-view .dc-nav') && !!document.querySelector('.dv-view .dv-pages')`), `Firefox ${W}: the page with "x of N"`);
      const r = await ev(`(() => { const n = document.querySelector('.dv-view .dc-nav').getBoundingClientRect(), p = document.querySelector('.dv-view .dv-pages'), c = document.querySelector('.dv-view');
        return {l: Math.round(n.left), r: Math.round(n.right), cw: Math.round(c.getBoundingClientRect().width), ta: getComputedStyle(p).touchAction, txt: document.querySelector('.dc-navn').textContent, sw: c.scrollWidth, ccw: c.clientWidth}; })()`);
      check(r && r.l >= 0 && r.r <= W && r.ta === 'pan-y' && r.txt === '1 of 5' && r.sw <= r.ccw + 1, `Firefox ${W}: the counter fits, the preview takes sideways swipes, no sideways scrolling ` + JSON.stringify(r));
      await ev(`(() => { ${TOUCH} sw(document.querySelector('.dv-view .dv-pages'), -${Math.round(W * .4)}); return 1; })()`);
      check(await wait(`+document.querySelector('.dv-view .dc-body').dataset.id === DC.docs[1].id && /^2 of /.test(document.querySelector('.dc-navn').textContent)`), `Firefox ${W}: a swipe on the preview turns to the next document`);
      check(await ev(`location.hash === '#ablage/' + DC.docs[1].id`), `Firefox ${W}: ... the address follows`);
      await ev(`(() => { ${TOUCH} sw(document.querySelector('.dv-view #dc-sender'), -${Math.round(W * .4)}); return 1; })()`);
      await sleep(400);
      check(await ev(`+document.querySelector('.dv-view .dc-body').dataset.id === DC.docs[1].id`), `Firefox ${W}: a swipe on the fields does not turn`);
      await shot(`p2476a-docswipe-${W}.png`);
      await ev(`(document.querySelector('.dv-view .dv-back').click(), 1)`);
      await wait(`!document.querySelector('.dc-md')`);
    }
  }, true);

  console.log(`p2476_a_docswipe_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
