// kalmido-suite:
// 2.736.0 UI test (#5212: leafing without a seam, on the document view of 2.583.0 - the direct neighbours of the open document
// are fetched completely and drawn ahead with the same drawing as the open one (docview.js dcv_bodyHtml); after the snap the
// body is only swapped: no request for the document, no picture that jumps, no text that comes later), own container
// (start.sh), jsdom (phone) + Firefox (touch, 320 and 460 px). Invented data only. P2736B_NOSTART=1 = the container runs.
// - documents (docs.js / docview.js): the next one is drawn ahead (title, fields, preview box) outside the page without ids
//   (the open one's fields stay the only ones with their ids); mid-swipe that real body lies beside the open one; after the
//   snap its nodes are the body (the same preview box, the same fields), no GET /api/docs/<id> after letting go, the body left
//   waits as the neighbour on the other side (no request either), the fields work (a title change saves against the version
//   fetched ahead, no conflict); leafing on stops the one that is no neighbour any more (aborted, gone); fetched a while ago =
//   compared quietly after the swap (a title changed elsewhere follows)
// - Firefox 320 / 460: the preview box of the next one stands after the snap exactly where it lay beside the open one (top, size)
//   and where the open one stood (left), its page drawn ahead is the same canvas (not drawn again), its fields at once; the full
//   screen (pdfview): the next page lies beside it drawn, after the snap it is there at once (no Loading…); the image viewer: the
//   next picture lies where it will stand
// P4: alice works without an organisation (private documents): the person without an organisation (freelancer-matrix: docs)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2736_b_docswipe_seamless_ui', check, shots: 'P2736B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2736B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
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
function hold(w, el, dx) {  // one finger from (200, 300) by dx in a few steps, held (not let go)
  touch(w, el, 'touchstart', [[200, 300]]);
  for (const f of [.25, .5, .75, 1]) touch(w, el, 'touchmove', [[200 + dx * f, 300]]);
}

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'});
  const IDS = [];
  for (const [n, l] of [['one.pdf', 'Versicherung Beispiel AG'], ['two.pdf', 'Stadtwerke Musterstadt'], ['three.pdf', 'Telefon Beispiel GmbH']]) IDS.push(await upload(n, [l, 'Brief']));
  for (const id of IDS) await call('POST', `/api/docs/${id}/review`, {done: true});

  // ================= documents on the phone (jsdom)
  const m = await boot({user: 'alice', hash: 'docs', mobile: true}), d = m.document;
  await until(() => d.querySelectorAll('.dc-card').length === 3);
  const order = m.eval('DC.docs.map(x => x.id)'), names = m.eval('DC.docs.map(x => x.name)');
  // every request of the page from here on (rawFetch / api use the global fetch)
  m.eval(`window.__f = []; { const f0 = window.fetch; window.fetch = function (u) { __f.push(String(u && u.url || u)); return f0.apply(this, arguments); }; } 1`);
  const body = () => d.querySelector('.dv-view .dc-body'), shown = () => +(body()?.dataset.id || 0), prev = () => d.querySelector('.dv-view .dv-pages');
  const docGets = id => m.eval(`__f.filter(u => /\\/api\\/docs\\/${id}(\\?|$)/.test(u)).length`);
  click(m, d.querySelector(`[data-dco="${order[0]}"]`));
  check(await until(() => shown() === order[0] && prev()), 'phone: the first document opens');
  check(await until(() => m.eval(`!!DCW.nb?.get(${order[1]})?.el?.querySelector('[data-dcp="name"]')`)), 'the next one is fetched and drawn ahead with its fields');
  check(m.eval(`DCW.nb.get(${order[1]}).el.querySelector('[data-dcp="name"]').value`) === names[1] && m.eval(`!!DCW.nb.get(${order[1]}).el.querySelector('.dv-pages') && !!DCW.nb.get(${order[1]}).el.querySelector('.dv-tabs')`), '... its title field, its tabs and its preview box (the same drawing as the open one)');
  check(d.querySelectorAll('[id="dc-name"]').length === 1 && d.querySelectorAll('[id="dc-props"]').length === 1 && d.querySelector('#dc-name').closest('.dv-view'), '... without ids while it waits: the open one\'s fields stay the only ones');
  check(m.eval(`!DCW.nb.get(${order[1]}).el.closest('.dv-view') && DCW.nb.get(${order[1]}).el.inert === true`), '... outside the view, not reachable');
  check(!m.eval(`DCW.nb.has(${order[2]})`), '... only the direct neighbours (the third is not fetched)');

  hold(m, prev(), -120);
  const nb = () => d.querySelector('.dv-view .dc-body > .dc-nb-n');
  check(nb()?.querySelector('[data-dcp="name"]')?.value === names[1] && nb().querySelector('.dc-props'), 'mid-swipe: the real sheet of the next one lies beside it, all fields there: ' + nb()?.textContent.slice(0, 80));
  check(nb()?.inert === true && nb()?.getAttribute('aria-hidden') === 'true', '... not reachable meanwhile (inert, hidden from screen readers)');
  m.eval(`window.__pv = document.querySelector('.dv-view .dc-body > .dc-nb-n .dv-pages'); window.__in = document.querySelector('.dv-view .dc-body > .dc-nb-n [data-dcp="name"]'); window.__old = document.querySelector('.dv-view .dc-body'); 1`);
  const before = docGets(order[1]), before0 = docGets(order[0]);
  touch(m, prev(), 'touchend', []);
  check(await until(() => shown() === order[1]), 'let go: the next document stands there');
  check(m.eval(`document.querySelector('.dv-view .dc-body .dv-pages') === __pv && document.querySelector('.dv-view [data-dcp="name"]') === __in`), '... the body drawn ahead was taken over as it was (the same preview box, the same field: nothing drawn anew)');
  check(d.querySelector('.dv-view [data-dcp="name"]').value === names[1] && !d.querySelector('.dv-view .dc-nb') && !body().style.transform, '... its title at once, no placeholder left, in place');
  check(d.querySelector('.dv-view #dc-name') === d.querySelector('.dv-view [data-dcp="name"]') && d.querySelectorAll('[id="dc-name"]').length === 1, '... its ids back (the label and the field belong together again)');
  // the body left behind waits as the neighbour before it once its preview was finished (jsdom draws no PDF: fetched anew then; Firefox below)
  check(m.eval(`__old.querySelector('.dv-pages')?._base ? DCW.nb.get(${order[0]})?.el === __old && !__old.closest('.dv-view') : !__old.closest('.dv-view')`) && (m.eval(`!!__old.querySelector('.dv-pages')?._base`) ? docGets(order[0]) === before0 : true), '... the body left behind is out of the view (waits as the neighbour before it when its preview was finished)');
  check(docGets(order[1]) === before, `... no request for the document after letting go (${docGets(order[1])} / ${before})`);
  check(m.eval('DC.doc.id') === order[1] && m.eval('DC.opening') == null, '... it is the open document');
  check(await until(() => m.eval(`!!DCW.nb.get(${order[2]})?.el && !!DCW.nb.get(${order[0]})?.el`)), '... and its own neighbours are drawn ahead (both sides)');

  // the sheet taken over works: a title change saves against the version fetched ahead (no conflict)
  const ti = d.querySelector('.dv-view [data-dcp="name"]');
  ti.value = 'Stadtwerke neu'; ti.dispatchEvent(new m.Event('change', {bubbles: true}));
  check(await until(async () => (await call('GET', `/api/docs/${order[1]}`)).name === 'Stadtwerke neu'), 'the taken-over sheet saves a title change');
  check(!d.querySelector('.conflict, .cfdlg') && !m.eval(`document.body.textContent.includes('Changed elsewhere')`), '... without a conflict');

  // leafing on: the one that is no neighbour any more is stopped and dropped
  m.eval(`window.__e0 = DCW.nb.get(${order[0]}); 1`);
  click(m, d.querySelector('.dv-view [data-dc="step:1"]'));
  check(await until(() => shown() === order[2]), 'the arrow forward: the last one');
  check(m.eval(`__e0.ctrl.signal.aborted && !DCW.nb.has(${order[0]})`), '... the first one (no neighbour now) is stopped and gone');

  // fetched a while ago and changed elsewhere meanwhile: shown at once, then quietly brought up to date
  check(await until(() => m.eval(`!!DCW.nb.get(${order[1]})?.el`)), 'the one before is drawn ahead again');
  await call('PATCH', `/api/docs/${order[1]}`, {name: 'Stadtwerke anderswo'});
  m.eval(`DCW.nb.get(${order[1]}).at -= 60000; 1`);
  const b2 = docGets(order[1]);
  click(m, d.querySelector('.dv-view [data-dc="step:-1"]'));
  check(await until(() => shown() === order[1]), 'back to the one before (fetched a while ago)');
  check(await until(() => d.querySelector('.dv-view [data-dcp="name"]')?.value === 'Stadtwerke anderswo'), '... the title changed elsewhere follows quietly: ' + d.querySelector('.dv-view [data-dcp="name"]')?.value);
  check(docGets(order[1]) === b2 + 1, `... with one quiet request behind it (${docGets(order[1]) - b2})`);
  m.close();

  // ================= Firefox, a touch screen: 320 and 460 px
  await firefox(async ({cmd, ev, nav: go, ctx, shot}) => {
    await go(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: login');
    const wait = async (js, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(js).catch(() => false)) return true; await sleep(150); } return false; };
    const TOUCH = `const tc = (el, type, pts) => { const e = new Event(type, {bubbles: true, cancelable: true}); Object.defineProperty(e, 'touches', {value: type === 'touchend' ? [] : pts.map(([x, y]) => ({clientX: x, clientY: y, target: el}))}); el.dispatchEvent(e); };
      const at = el => { const r = el.getBoundingClientRect(); return [r.left + r.width / 2, r.top + Math.min(120, r.height / 2)]; };
      const hold = (el, dx) => { const [x, y] = at(el); tc(el, 'touchstart', [[x, y]]); for (const f of [.25, .5, .75, 1]) tc(el, 'touchmove', [[x + dx * f, y]]); };`;
    const R = `r => ({l: Math.round(r.left), t: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height)})`;
    for (const W of [320, 460]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: W, height: 760}});
      check(await wait(`innerWidth === ${W}`, 40), `Firefox ${W}: the window has its size`);
      await go(B + '#docs');
      check(await wait(`document.querySelectorAll('.dc-card').length === 3 && !!DC.docs && isTouch()`), `Firefox ${W}: three cards, a touch screen`);
      await ev(`(document.querySelector('.dc-view [data-dco="' + DC.docs[0].id + '"]').click(), 1)`);
      const NB = `DCW.nb?.get(DC.docs[1].id)`;
      check(await wait(`DC.doc?.id === DC.docs[0].id && !!document.querySelector('.dv-view .dv-pages canvas') && !!${NB}?.el?.querySelector('.dv-pages canvas')`, 120), `Firefox ${W}: open, the next one drawn ahead with its page`);
      const r0 = await ev(`(() => { const c = document.querySelector('.dv-view .dc-body .dv-pages canvas'); if (c) c.__was = 1; return (${R})(document.querySelector('.dv-view .dc-body .dv-pages').getBoundingClientRect()); })()`);
      const mid = await ev(`(() => { ${TOUCH} hold(document.querySelector('.dv-view .dc-body .dv-pages'), -${Math.round(W * .35)});
        const n = document.querySelector('.dv-view .dc-body > .dc-nb-n'); if (!n) return null; const cv = n.querySelector('.dv-pages canvas'); if (cv) cv.__ahead = 1;
        return {pv: (${R})(n.querySelector('.dv-pages').getBoundingClientRect()), name: n.querySelector('[data-dcp="name"]')?.value, cv: !!cv, t0: performance.now()}; })()`);
      check(mid?.cv && mid.name === await ev(`DC.docs[1].name`), `Firefox ${W}: mid-swipe the next one lies there with its page and its title ` + JSON.stringify(mid));
      await ev(`(() => { ${TOUCH} tc(document.querySelector('.dv-view .dc-body .dv-pages'), 'touchend', []); return 1; })()`);
      check(await wait(`DC.doc?.id === DC.docs[1].id && document.querySelector('.dv-view .dc-body')?.dataset.id === String(DC.docs[1].id)`), `Firefox ${W}: let go, the next one is open`);
      const at1 = await ev(`({pv: (${R})(document.querySelector('.dv-view .dc-body .dv-pages').getBoundingClientRect()), name: document.querySelector('.dv-view [data-dcp="name"]')?.value, same: document.querySelector('.dv-view .dc-body .dv-pages canvas')?.__ahead === 1})`);
      check(at1.name === mid?.name && at1.same, `Firefox ${W}: at once its title and the same page drawn ahead (not drawn again) ` + JSON.stringify(at1));
      check(await wait(`!window.__net || window.__net.n === 0`, 80) && await wait(`!document.querySelector('.dv-view .dc-nb') && !document.querySelector('.dv-view .dc-body').style.transform`), `Firefox ${W}: settled (no request open)`);
      const at2 = await ev(`({pv: (${R})(document.querySelector('.dv-view .dc-body .dv-pages').getBoundingClientRect()), same: document.querySelector('.dv-view .dc-body .dv-pages canvas')?.__ahead === 1,
        gets: performance.getEntriesByType('resource').filter(e => e.startTime > ${mid?.t0 || 0} && new URL(e.name).pathname === '/api/docs/' + DC.docs[1].id).map(e => e.name)})`);
      const near = (a, b) => typeof a === 'number' && typeof b === 'number' && Math.abs(a - b) <= 1;
      check(near(at2.pv.t, mid.pv.t) && near(at2.pv.w, mid.pv.w) && near(at2.pv.h, mid.pv.h) && near(at2.pv.l, r0.l), `Firefox ${W}: the preview box stands where it lay beside it (top, size) and where the open one stood (left): no jump ` + JSON.stringify({r0, mid: mid?.pv, at1: at1.pv, at2: at2.pv}));
      check(near(at1.pv.t, at2.pv.t) && near(at1.pv.h, at2.pv.h) && at2.same, `Firefox ${W}: ... and it stays there (nothing loads in later and moves it)`);
      check(!at2.gets.length, `Firefox ${W}: no request for the document after letting go ` + JSON.stringify(at2.gets));
      check(await ev(`DCW.nb.get(DC.docs[0].id)?.el?.querySelector('.dv-pages canvas')?.__was === 1 && !DCW.nb.get(DC.docs[0].id).el.closest('.dv-view') && document.querySelectorAll('[id="dc-name"]').length === 1`), `Firefox ${W}: the body left behind waits as the neighbour before it, its page still drawn (the way back without a request), no second #dc-name`);
      await shot(`p2736b-docs-${W}.png`);

      // the full screen (pdfview): the next page lies beside it drawn, after the snap it is there at once
      check(await wait(`Date.now() - DCW.end > 750`), `Firefox ${W}: the swipe's end is past (a tap counts again)`);
      await ev(`(document.querySelector('.dv-view .dc-body [data-dc="view"]').click(), 1)`);
      const NO = `(document.querySelector('.lightbox.pview .pvdno')?.textContent || '')`;
      check(await wait(`${NO} === '2 of 3' && !!document.querySelector('.lightbox.pview .pvpage canvas') && !!document.querySelector('.lightbox.pview')._pre?.[1]?.v?.cv`, 120), `Firefox ${W}: full screen "2 of 3", the next page made ready ahead ` + await ev(`JSON.stringify({no: ${NO}, cv: !!document.querySelector('.lightbox.pview .pvpage canvas'), pre: Object.entries(document.querySelector('.lightbox.pview')?._pre || {}).map(([k, e]) => [k, !!e.v, !!e.v?.cv, e.ac.signal.aborted])})`));
      if (!await ev(`!!document.querySelector('.lightbox.pview')`)) continue;
      const fmid = await ev(`(() => { ${TOUCH} hold(document.querySelector('.lightbox.pview .pvbody'), -${Math.round(W * .35)}); const n = document.querySelector('.lightbox.pview .swn-nb[data-dir="1"]'), cv = n?.querySelector('.pvpage canvas'); if (cv) cv.__ahead = 1; return !!cv; })()`);
      check(fmid, `Firefox ${W}: full screen mid-swipe: the next page lies beside it, drawn`);
      await ev(`(() => { ${TOUCH} tc(document.querySelector('.lightbox.pview .pvbody'), 'touchend', []); return 1; })()`);
      check(await wait(`${NO} === '3 of 3'`), `Firefox ${W}: full screen: the next document`);
      check(await ev(`document.querySelector('.lightbox.pview .pvpage canvas')?.__ahead === 1 && !document.querySelector('.lightbox.pview .tvmsg')`), `Firefox ${W}: ... its page at once, the one drawn ahead (no Loading…)`);
      await shot(`p2736b-full-${W}.png`);
      await ev(`(document.querySelector('.lightbox.pview [data-pv="x"]').click(), 1)`);
      await wait(`!document.querySelector('.lightbox')`);
      await ev(`(document.querySelector('.dv-view [data-dc="close"]')?.click(), 1)`);
      await wait(`!document.querySelector('.dv-view') && !document.querySelector('.dv-nbhold')`);

      // the image viewer: the next picture lies where it will stand (o.full: the viewer's frame, not the box of the one shown)
      await ev(`(attLightbox('a', ['a', 'b'].map(id => ({id, name: id + '.png', size: 10})), (a, dl) => '/static/icon.svg?' + a.id + (dl ? '&dl' : '')), 1)`);
      const IMG = `document.querySelector('.lightbox > img')`;
      check(await wait(`${IMG}?.complete && typeof swn_attach === 'function' && SWN_PRE.has('/static/icon.svg?b')`), `Firefox ${W}: the image viewer open`);
      const imid = await ev(`(() => { ${TOUCH} const dx = -${Math.round(W * .35)}; hold(${IMG}, dx); const n = document.querySelector('.lightbox .swn-nb[data-dir="1"]'), im = n?.querySelector('img'); if (!im) return null;
        const m = /translateX\\((-?[\\d.]+)px\\)/.exec(n.style.transform), r = im.getBoundingClientRect(); return {l: Math.round(r.left - (m ? +m[1] : 0)), t: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height)}; })()`);
      await ev(`(() => { ${TOUCH} tc(${IMG}, 'touchend', []); return 1; })()`);
      check(await wait(`(${IMG}?.getAttribute('src') || '').endsWith('?b') && ${IMG}.complete && !document.querySelector('.swn-nb')`), `Firefox ${W}: a swipe = the next picture`);
      const iat = await ev(`(${R})(${IMG}.getBoundingClientRect())`);
      check(imid && near(imid.l, iat.l) && near(imid.t, iat.t) && near(imid.w, iat.w) && near(imid.h, iat.h), `Firefox ${W}: the next picture lay where it stands now: no jump ` + JSON.stringify({imid, iat}));
      await ev(`(document.querySelector('.lightbox [data-lb="x"]').click(), 1)`);
      await wait(`!document.querySelector('.lightbox')`);
    }
  }, true);

  console.log(`p2736_b_docswipe_seamless_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
