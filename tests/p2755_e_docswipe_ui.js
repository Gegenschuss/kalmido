// 2.755.0 UI test (#5236: leafing without a seam at the rest of the places, after #5212 / p2736_b) - own container (start.sh),
// kalmido-suite:
// 2.882.0 (#5557): the swipe is swipenav.js now: the neighbour lies in the body as .swn-nb > .dc-nb, the body's parts glide
// jsdom (phone) + Firefox (touch, 400 px). Invented data only. P2755E_NOSTART=1 = the container runs.
// - documents (docview.js dcv_nbDraw): the neighbour drawn ahead has its receipt line (receipts.js rc_nbFill), its letters
//   (letterdoc.js ltd_nbFill) and the runs of its flows (docflows.js dfl_runs) FILLED before the swipe, with its own data: the
//   open one's state (RC / LTD) stays the open one's, its frames carry no ids while it waits; after the snap the filled frames
//   are the open ones at once (no request for its receipt / letters after letting go, the flows' text there in the same step),
//   and RC / LTD belong to the new one (rc_take / ltd_take); the next neighbours get their own again
//   (the letters and the flows answer here from a stand-in: the office's letters need an office, a flow's run a flow)
// - the file store's full screen (ablage.js ab_pvOpts o.near): the next file is made ready ahead (its first page drawn), a swipe
//   lays it beside the page drawn, after the snap it is there at once (no Loading…, the same canvas)
// - Rückfall: without #5236 the neighbour's receipt / letter / flow frames are empty and the file store's full screen has no
//   o.near (the placeholder): every check of the frames and of "_pre" fails then
// P4: alice works without an organisation (private documents): the person without an organisation (freelancer-matrix: docs)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2755_e_docswipe_ui', check, shots: 'P2755E_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2755E_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
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
  const order = m.eval('DC.docs.map(x => x.id)');
  // every request of the page from here on; the office's letters of a document and the runs of its flows answer from a
  // stand-in (each names its document: a mix of two documents shows)
  m.eval(`window.__f = []; { const f0 = window.fetch;
    const js = j => Promise.resolve({status: 200, ok: true, type: 'basic', headers: {get: k => /content-type/i.test(k) ? 'application/json' : null}, json: async () => j});
    window.fetch = function (u) { const s = String(u && u.url || u); __f.push(s);
      let x = /\\/api\\/office\\/letters\\/doc\\/(\\d+)$/.exec(s);
      if (x) return js({available: true, letters: [{id: +x[1], subject: 'Letter of ' + x[1], href: '#office/letters/' + x[1], date: null, status: 'sent', kind: 'reply'}], deadline: null, refs: [], task: null, can_write: true});
      x = /\\/api\\/docs\\/(\\d+)\\/flowruns$/.exec(s);
      if (x) return js({runs: [{id: +x[1], name: 'Flow of ' + x[1], at: new Date().toISOString(), did: ['tags'], undone: false}], can_undo: false});
      return f0.apply(this, arguments); }; } 1`);
  const body = () => d.querySelector('.dv-view .dc-body'), shown = () => +(body()?.dataset.id || 0), prev = () => d.querySelector('.dv-view .dv-pages');
  const gets = (id, what) => m.eval(`__f.filter(u => u.endsWith('${what.replace('#', id)}')).length`);
  click(m, d.querySelector(`[data-dco="${order[0]}"]`));
  check(await until(() => shown() === order[0] && prev()), 'phone: the first document opens');
  check(await until(() => d.querySelector('.dv-view .dc-body .ltd')?.textContent.includes('Letter of ' + order[0]) && d.querySelector('.dv-view .dc-body .rc-slot')?.children.length), 'the open one: its letters and its receipt line');
  const NB = `DCW.nb?.get(${order[1]})`;
  check(await until(() => m.eval(`!!${NB}?.rc && !!${NB}?.ltd && (${NB}.el?.querySelector('.dc-flows')?.textContent || '').includes('Flow of ${order[1]}')`)),
    'the next one drawn ahead: its receipt, its letters and its flows fetched and filled before any swipe');
  const nbEl = () => m.eval(`${NB}.el`);
  check(nbEl().querySelector('.rc-slot')?.children.length > 0 && nbEl().querySelector('.rc-slot').textContent === d.querySelector('.dv-view .dc-body .rc-slot').textContent,
    '... its receipt line is filled (drawn by the same lines as the open one\'s): ' + nbEl().querySelector('.rc-slot')?.textContent.slice(0, 60));
  check((nbEl().querySelector(`.ltd[data-nid="${order[1]}"]`)?.textContent || '').includes('Letter of ' + order[1]) && !nbEl().textContent.includes('Letter of ' + order[0]), '... its letter line shows its own letters (not the open one\'s)');
  check(!nbEl().querySelector('[id]'), '... no ids in it while it waits (the open one\'s fields stay the only ones): ' + [...nbEl().querySelectorAll('[id]')].map(x => x.id).join(','));
  check(m.eval('RC.id') === order[0] && m.eval('LTD.id') === order[0] && (d.querySelector('.dv-view .dc-body .ltd')?.textContent || '').includes('Letter of ' + order[0]) && !d.querySelector('.dv-view .dc-body .ltd')?.textContent.includes('Letter of ' + order[1]),
    '... the open one\'s state stays its own (RC / LTD, its letter line)');

  hold(m, prev(), -120);
  const nb = () => d.querySelector('.dv-view .dc-body > .swn-nb[data-dir="1"] > .dc-nb');
  check((nb()?.querySelector('.ltd')?.textContent || '').includes('Letter of ' + order[1]) && nb()?.querySelector('.rc-slot')?.children.length > 0 && (nb()?.querySelector('.dc-flows')?.textContent || '').includes('Flow of ' + order[1]),
    'mid-swipe: the sheet beside it shows its receipt, its letters and its flows already');
  m.eval(`window.__ltd = document.querySelector('.dv-view .dc-body > .swn-nb[data-dir="1"] > .dc-nb .ltd'); window.__rc = document.querySelector('.dv-view .dc-body > .swn-nb[data-dir="1"] > .dc-nb .rc-slot'); 1`);
  const b = {rc: gets(order[1], '/api/docs/#/receipt'), lt: gets(order[1], '/api/office/letters/doc/#')};
  touch(m, prev(), 'touchend', []);
  check(await until(() => shown() === order[1]), 'let go: the next document stands there');
  // the same step: what was filled ahead is there (the flows' own request after the draw has not come back yet)
  const at = m.eval(`({fl: document.querySelector('.dv-view .dc-body .dc-flows')?.textContent || '', lt: document.querySelector('.dv-view .dc-body .ltd')?.textContent || '', rc: document.querySelector('.dv-view .dc-body .rc-slot')?.children.length || 0,
    same: document.querySelector('.dv-view .dc-body .ltd') === __ltd && document.querySelector('.dv-view .dc-body .rc-slot') === __rc})`);
  check(at.fl.includes('Flow of ' + order[1]) && at.lt.includes('Letter of ' + order[1]) && at.rc > 0, '... its receipt, its letters and its flows at once, nothing comes later: ' + JSON.stringify(at));
  check(at.same, '... the frames filled ahead are the open ones (taken over, not drawn anew empty)');
  check(m.eval('RC.id') === order[1] && m.eval('LTD.id') === order[1] && m.eval('!!RC.d'), '... the open state is the new one\'s (rc_take / ltd_take)');
  check(await until(() => m.eval(`!!DCW.nb?.get(${order[2]})?.ltd`)), '... its own next neighbour drawn ahead with its letters');
  check(gets(order[1], '/api/docs/#/receipt') === b.rc && gets(order[1], '/api/office/letters/doc/#') === b.lt, `... no request for its receipt or letters after letting go (${gets(order[1], '/api/docs/#/receipt') - b.rc} / ${gets(order[1], '/api/office/letters/doc/#') - b.lt})`);
  check((d.querySelector('.dv-view .dc-body .ltd')?.textContent || '').includes('Letter of ' + order[1]) && !(d.querySelector('.dv-view .dc-body .ltd')?.textContent || '').includes('Letter of ' + order[2])
    && (m.eval(`${'DCW.nb.get(' + order[2] + ')'}.el.querySelector('.ltd')?.textContent`) || '').includes('Letter of ' + order[2]), '... two documents never mix: the open one shows its letters, the neighbour its own');
  // the open one's line still works by its state: a redraw of the open document keeps its letters and receipt (no empty frame)
  m.eval('dc_mdDraw(document.querySelector(".dv-view")); 1');
  check((d.querySelector('.dv-view .dc-body .ltd')?.textContent || '').includes('Letter of ' + order[1]) && d.querySelector('.dv-view .dc-body .rc-slot')?.children.length > 0, '... a redraw keeps its letters and its receipt line');
  m.close();

  // ================= Firefox, a touch screen: the file store's full screen
  const node = await call('GET', `/api/files/nodes/${IDS[0]}`);
  await firefox(async ({cmd, ev, nav: go, ctx, shot}) => {
    await go(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: login');
    const wait = async (js, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(js).catch(() => false)) return true; await sleep(150); } return false; };
    const TOUCH = `const tc = (el, type, pts) => { const e = new Event(type, {bubbles: true, cancelable: true}); Object.defineProperty(e, 'touches', {value: type === 'touchend' ? [] : pts.map(([x, y]) => ({clientX: x, clientY: y, target: el}))}); el.dispatchEvent(e); };
      const at = el => { const r = el.getBoundingClientRect(); return [r.left + r.width / 2, r.top + Math.min(120, r.height / 2)]; };
      const hold = (el, dx) => { const [x, y] = at(el); tc(el, 'touchstart', [[x, y]]); for (const f of [.25, .5, .75, 1]) tc(el, 'touchmove', [[x + dx * f, y]]); };`;
    const W = 400;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: W, height: 760}});
    check(await wait(`innerWidth === ${W}`, 40), `Firefox ${W}: the window has its size`);
    await go(B + (node.parent_id ? `#ablage/${node.parent_id}` : '#ablage/s/private'));
    const PDFS = `(AB.data?.items || []).filter(x => x.kind === 'file' && ab_isPdf(x))`;
    check(await wait(`typeof ab_pvOpts === 'function' && ${PDFS}.length === 3 && isTouch()`, 120), `Firefox ${W}: the file store's folder with the three PDFs, a touch screen ` + await ev(`JSON.stringify({h: location.hash, n: (window.AB?.data?.items || []).map(x => x.name)})`).catch(() => ''));
    check(await ev(`typeof ab_pvOpts(${PDFS}[0]).near === 'function'`), `Firefox ${W}: the full screen of the file store gets its neighbours (o.near)`);
    // the full screen as the file store opens it (ab_openFile: the PDF view with leafing through the folder)
    await ev(`(ab_openFile(${PDFS}[0], {raw: true}), 1)`);
    const NO = `(document.querySelector('.lightbox.pview .pvdno')?.textContent || '')`;
    check(await wait(`${NO} === '1 of 3' && !!document.querySelector('.lightbox.pview .pvpage canvas') && !!document.querySelector('.lightbox.pview')._pre?.[1]?.v?.cv`, 120),
      `Firefox ${W}: full screen "1 of 3", the next file made ready ahead (its first page drawn) ` + await ev(`JSON.stringify({no: ${NO}, pre: Object.entries(document.querySelector('.lightbox.pview')?._pre || {}).map(([k, e]) => [k, !!e.v, !!e.v?.cv])})`));
    if (await ev(`!!document.querySelector('.lightbox.pview')`)) {
      const fmid = await ev(`(() => { ${TOUCH} hold(document.querySelector('.lightbox.pview .pvbody'), -${Math.round(W * .35)}); const n = document.querySelector('.lightbox.pview .swn-nb[data-dir="1"]'), cv = n?.querySelector('.pvpage canvas'); if (cv) cv.__ahead = 1; return {cv: !!cv, ph: !!n?.querySelector('img, .swn-ph')}; })()`);
      check(fmid?.cv, `Firefox ${W}: mid-swipe the next file lies beside it, its page drawn (no placeholder) ` + JSON.stringify(fmid));
      await ev(`(() => { ${TOUCH} tc(document.querySelector('.lightbox.pview .pvbody'), 'touchend', []); return 1; })()`);
      check(await wait(`${NO} === '2 of 3'`), `Firefox ${W}: let go, the next file`);
      check(await ev(`document.querySelector('.lightbox.pview .pvpage canvas')?.__ahead === 1 && !document.querySelector('.lightbox.pview .tvmsg')`), `Firefox ${W}: ... its page at once, the one drawn ahead (no Loading…)`);
      check(await wait(`!!document.querySelector('.lightbox.pview')._pre?.[1]?.v?.cv && !!document.querySelector('.lightbox.pview')._pre?.[-1]?.v?.cv`, 120), `Firefox ${W}: ... and both its neighbours made ready ahead`);
      await shot(`p2755e-ablage-full-${W}.png`);
      await ev(`(document.querySelector('.lightbox.pview [data-pv="x"]').click(), 1)`);
    }
  }, true);

  console.log(`p2755_e_docswipe_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
